"""La caméra de la tête du micropore (tâche 40 ter ; `cam_inspection` du projet mécanique).

    vision = VisionInspection(reglages.vision, photographe, angle_plateau, ecarts)

Elle sert deux modules, par les mêmes images :
- le Remplissage (`VisionSeau`) : QR du flanc lu PENDANT que le plateau tourne le seau, avant le
  serrage des barres ; on en tire l'angle des oreilles de l'anse (`lire_seau`) ;
- le Micropore (`VisionMicropore`) : à chaque tour de repérage (un par rangée : la caméra est fixe
  et ne voit qu'une rangée à la fois), la position des trous de la rangée (`finir_tour`) ;
  puis le contrôle de chaque morceau posé (`controler_morceau`).

Comment l'angle est trouvé (fiche du micropore, geste 0 : « le QR sert de repère d'angle ») : le
plateau tourne, la caméra est fixe. À chaque image on note l'angle du plateau et où est le QR (ou
un trou) dans l'image. Le QR passe au centre de l'image à l'angle `a_c` du plateau, trouvé en
joignant les lectures (droite : position dans l'image en fonction de l'angle du plateau). Au
centre de l'image, le QR est à l'azimut de la caméra vu de l'axe du plateau (−122°, fiche). Ensuite
l'azimut de n'importe quel point du seau suit le plateau :

    azimut du QR = azimut de la caméra + (angle du plateau maintenant − a_c)
    oreilles de l'anse = azimut du QR + écart attaches/QR enregistré pour ce seau

Les trous se repèrent de la même façon : l'angle du plateau où le trou est au centre de l'image.
L'angle caméra → rouleau (appris par format) se calcule de la même géométrie : azimut du rouleau
moins azimut de la caméra (`angle_camera_rouleau`).

Ce qui demande des photos réelles reste un faux avec son interface (comme la tâche 22 ter) :
- les attaches de l'anse (`ReconnaissanceAttaches`, faux : `FausseReconnaissanceAttaches`) ; sans
  elles, l'écart attaches/QR d'un seau vient du fichier des écarts (`vidange-vision ecart`) ou,
  sinon, du réglage `flanc → ecart_attaches_defaut_deg` ;
- le diamètre du bord du seau et le jugement « bien collé » (la fiche ne demande que couvert /
  découvert / de travers / mal coupé).

Rien ici n'est une sécurité.
"""

import json
import math
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from vidange.journal import donner_journal
from vidange.micropore.micropore import Reperage
from vidange.reglages import GeometrieInspection, InspectionVision, ReglagesVision
from vidange.vision.photo import ErreurVision, Photo
from vidange.vision.qr import lire_codes

journal = donner_journal("vision.inspection")

NOM_ECARTS = "ecarts-attaches.json"
# Un trou suivi peut manquer sur autant d'images de suite (image floue) sans que son suivi finisse.
PAUSE_MAX_IMAGES = 2

Point = tuple[float, float]


# ------------------------------------------------------------------- la géométrie


def _normaliser(angle: float) -> float:
    """Angle dans ]−180 ; 180]."""
    return 180 - (180 - angle) % 360


def azimut_au_centre(geometrie: GeometrieInspection, rayon_m: float) -> float:
    """Azimut (°, vu de l'axe du plateau) du point de la paroi, de rayon `rayon_m`, que la
    caméra voit au centre de son image. Caméra visant l'axe du plateau (pas de cap) : c'est
    l'azimut de la caméra, quel que soit le rayon."""
    px, py = geometrie.decalage_m
    if geometrie.cap_deg is None:
        return math.degrees(math.atan2(py, px))
    ux, uy = math.cos(math.radians(geometrie.cap_deg)), math.sin(math.radians(geometrie.cap_deg))
    b = px * ux + py * uy
    c = px * px + py * py - rayon_m * rayon_m
    discriminant = b * b - c
    if discriminant < 0:
        raise ErreurVision(
            f"la caméra ne voit pas la paroi de rayon {rayon_m:g} m (inspection → geometrie → "
            "cap_deg)"
        )
    racine = math.sqrt(discriminant)
    distances = [t for t in (-b - racine, -b + racine) if t > 0]
    if not distances:
        raise ErreurVision("la caméra tourne le dos au seau (inspection → geometrie → cap_deg)")
    t = min(distances)
    return math.degrees(math.atan2(py + t * uy, px + t * ux))


def angle_camera_rouleau(inspection: InspectionVision, rayon_m: float) -> float:
    """Angle (°) dont le plateau tourne pour amener ce qui est au centre de l'image sous le
    rouleau : azimut du rouleau moins azimut de la caméra (pour la paroi de ce rayon)."""
    geometrie = inspection.geometrie
    return _normaliser(geometrie.rouleau_azimut_deg - azimut_au_centre(geometrie, rayon_m))


# ------------------------------------------------------------------- l'écart attaches / QR


class EcartsAttaches:
    """L'écart (°) entre les attaches de l'anse et le QR, enregistré seau par seau
    (donnees/ecarts-attaches.json). Il se mesure une fois par seau (`vidange-vision ecart`, ou
    les attaches vues au premier passage quand la reconnaissance existera) et sert à chaque
    lecture du QR. Fichier réécrit d'un coup, jamais à moitié."""

    def __init__(self, fichier: Path | None = None) -> None:
        self.fichier = fichier
        self._verrou = threading.Lock()
        self._ecarts: dict[str, dict[str, object]] = {}
        self.erreur: str | None = None
        if fichier is not None and fichier.exists():
            try:
                lu = json.loads(fichier.read_text(encoding="utf-8"))
                self._ecarts = {str(code): dict(valeur) for code, valeur in lu.items()}
                for valeur in self._ecarts.values():
                    float(valeur["ecart_deg"])  # type: ignore[arg-type]
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as erreur:
                self._ecarts = {}
                self.erreur = f"{fichier.name} illisible ({erreur})"
                journal.error("Écarts attaches/QR : %s", self.erreur)

    def ecart(self, code: str) -> float | None:
        with self._verrou:
            valeur = self._ecarts.get(code)
        return None if valeur is None else float(valeur["ecart_deg"])  # type: ignore[arg-type]

    def noter(self, code: str, ecart_deg: float, qui: str) -> None:
        ecart = (ecart_deg + 90) % 180 - 90
        with self._verrou:
            self._ecarts[code] = {
                "ecart_deg": ecart,
                "quand": datetime.now().astimezone().isoformat(timespec="seconds"),
                "qui": qui,
            }
            self._sauver()
        journal.info("Écart attaches/QR du seau %s : %.1f° (par %s)", code, ecart, qui)

    def tous(self) -> dict[str, float]:
        with self._verrou:
            return {code: float(v["ecart_deg"]) for code, v in self._ecarts.items()}  # type: ignore[arg-type]

    def _sauver(self) -> None:
        if self.fichier is None:
            return
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        provisoire = self.fichier.with_suffix(".provisoire")
        provisoire.write_text(
            json.dumps(self._ecarts, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        os.replace(provisoire, self.fichier)


# ---------------------------------------------------- ce qui demande des photos réelles


class ReconnaissanceAttaches(Protocol):
    """Trouver les attaches de l'anse sur les images du tour (photos réelles : tâche 22 ter)."""

    def recommencer(self) -> None: ...

    def voir(self, angle_plateau_deg: float, image: np.ndarray) -> None:
        """Une image du tour, prise quand le plateau était à cet angle."""
        ...

    def trouvees(self) -> list[float]:
        """Angles du plateau (°) où une attache est au centre de l'image ; vide : pas vues."""
        ...


class FausseReconnaissanceAttaches:
    """Ne reconnaît rien tant qu'il n'y a pas de photos réelles (ou rend ce qu'on lui dit, pour
    les essais)."""

    def __init__(self, attaches: list[float] | None = None) -> None:
        self.attaches = list(attaches or [])
        self.images_vues = 0

    def recommencer(self) -> None:
        self.images_vues = 0

    def voir(self, angle_plateau_deg: float, image: np.ndarray) -> None:
        self.images_vues += 1

    def trouvees(self) -> list[float]:
        return list(self.attaches)


# ------------------------------------------------------------------- ce qu'on voit dans une image


@dataclass(frozen=True)
class QrVu:
    code: str
    # Écart du centre du QR au centre de l'image (points ; positif : à droite).
    x_px: float
    y_px: float
    # Rectangle du QR dans l'image (x0, y0, x1, y1).
    boite: tuple[float, float, float, float]


@dataclass(frozen=True)
class TrouVu:
    x_px: float
    y_px: float
    diametre_px: float


@dataclass
class Echantillon:
    """Une image du tour : l'angle du plateau et ce qui y est vu."""

    angle: float
    qrs: list[QrVu] = field(default_factory=list)
    trous: list[TrouVu] = field(default_factory=list)


def _gris(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image


def trouver_trous(
    image: np.ndarray,
    inspection: InspectionVision,
    exclure: list[tuple[float, float, float, float]],
) -> list[TrouVu]:
    """Les taches rondes, de la taille d'un trou, qui tranchent sur la paroi. `exclure` : des
    rectangles (les QR) où l'on ne cherche pas. Une tache coupée par le bord de l'image n'est pas
    comptée (on la verra entière une image plus tard)."""
    reglage = inspection.trous
    gris = _gris(image)
    hauteur, largeur = gris.shape
    d_px = reglage.diametre_mm / inspection.echelle_mm_par_point
    # Le fond (la paroi sans les taches) se calcule sur une image 8 fois plus petite : 8 fois
    # plus vite, et assez juste pour une paroi qui change doucement.
    reduit = cv2.resize(gris, (largeur // 8, hauteur // 8), interpolation=cv2.INTER_AREA)
    reduit = cv2.GaussianBlur(reduit, (0, 0), max(2 * d_px, 5) / 8)
    fond = cv2.resize(reduit, (largeur, hauteur), interpolation=cv2.INTER_LINEAR)
    masque = np.where(cv2.absdiff(gris, fond) >= reglage.contraste_min, 255, 0).astype(np.uint8)
    for x0, y0, x1, y1 in exclure:
        masque[max(0, int(y0)) : max(0, int(y1)), max(0, int(x0)) : max(0, int(x1))] = 0
    contours, _ = cv2.findContours(masque, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    trous = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if x <= 0 or y <= 0 or x + w >= largeur or y + h >= hauteur:
            continue
        aire = cv2.contourArea(contour)
        perimetre = cv2.arcLength(contour, True)
        if aire <= 0 or perimetre <= 0:
            continue
        if 4 * math.pi * aire / perimetre**2 < reglage.circularite_min:
            continue
        diametre = math.sqrt(4 * aire / math.pi)
        if abs(diametre - d_px) > reglage.tolerance_diametre * d_px:
            continue
        trous.append(TrouVu(x + w / 2 - largeur / 2, y + h / 2, diametre))
    return trous


def lire_flanc(image: np.ndarray, reglages: ReglagesVision) -> tuple[list[QrVu], list[TrouVu]]:
    """Les QR du flanc (forme des codes du registre) et les trous d'une image."""
    assert reglages.inspection is not None
    largeur = image.shape[1]
    qrs = []
    for code in lire_codes(image, reglages.qr, rapide=True):
        xs = [p[0] for p in code.coins]
        ys = [p[1] for p in code.coins]
        marge = 0.2 * max(max(xs) - min(xs), max(ys) - min(ys))
        qrs.append(
            QrVu(
                code.code,
                code.centre[0] - largeur / 2,
                code.centre[1],
                (min(xs) - marge, min(ys) - marge, max(xs) + marge, max(ys) + marge),
            )
        )
    trous = trouver_trous(image, reglages.inspection, [q.boite for q in qrs])
    return qrs, trous


# ------------------------------------------------------------------- le contrôle d'un morceau


@dataclass(frozen=True)
class VerdictMorceau:
    couvert: bool
    # Pourquoi pas (vide : couvert).
    raison: str = ""


def controler_morceau_image(
    image: np.ndarray, centre_trou: Point, inspection: InspectionVision
) -> VerdictMorceau:
    """Le trou, attendu à `centre_trou` (points), est-il couvert par un morceau de la bonne taille,
    droit ? Découvert, de travers ou mal coupé : pas couvert (fiche, geste 11)."""
    reglage = inspection.piece
    echelle = inspection.echelle_mm_par_point
    longueur, largeur_piece = reglage.longueur_mm / echelle, reglage.largeur_mm / echelle
    rayon = inspection.trous.diametre_mm / echelle / 2
    gris = _gris(image)
    hauteur, largeur = gris.shape
    cx, cy = centre_trou
    demi = 1.5 * longueur
    x0, x1 = max(0, int(cx - demi)), min(largeur, int(cx + demi))
    y0, y1 = max(0, int(cy - demi)), min(hauteur, int(cy + demi))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return VerdictMorceau(False, "le trou n'est pas dans l'image")
    zone = gris[y0:y1, x0:x1]
    paroi = float(np.median(zone))
    masque = np.where(np.abs(zone.astype(np.float32) - paroi) >= reglage.contraste_min, 255, 0)
    contours, _ = cv2.findContours(
        masque.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return VerdictMorceau(False, "trou découvert : pas de morceau vu")
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < 0.3 * longueur * largeur_piece:
        return VerdictMorceau(False, "trou découvert : pas de morceau vu")
    boite = cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float64)
    cotes = [boite[(i + 1) % 4] - boite[i] for i in range(2)]

    def ecart_horizontal(cote: np.ndarray) -> float:
        angle = math.degrees(math.atan2(cote[1], cote[0])) % 180
        return min(angle, 180 - angle)

    # La longueur du morceau (30 mm) suit la paroi, donc l'horizontale de l'image ; sa largeur
    # (25 mm, celle du ruban) est en travers.
    cotes.sort(key=ecart_horizontal)
    grand, petit = cotes
    inclinaison = ecart_horizontal(grand)
    long_mesure, court_mesure = float(np.hypot(*grand)), float(np.hypot(*petit))
    tol = reglage.tolerance_taille
    if abs(long_mesure - longueur) > tol * longueur or (
        abs(court_mesure - largeur_piece) > tol * largeur_piece
    ):
        return VerdictMorceau(
            False,
            f"morceau mal coupé : {long_mesure * echelle:.0f} × {court_mesure * echelle:.0f} mm, "
            f"{reglage.longueur_mm:g} × {reglage.largeur_mm:g} attendus",
        )
    if inclinaison > reglage.inclinaison_max_deg:
        return VerdictMorceau(False, f"morceau de travers ({inclinaison:.0f}°)")
    centre_morceau = boite.mean(axis=0) + np.array([x0, y0])
    ecart = np.array([cx, cy]) - centre_morceau
    u = grand / long_mesure
    v = petit / court_mesure
    marge = reglage.marge_mm / echelle
    if (
        abs(float(ecart @ u)) > long_mesure / 2 - rayon - marge
        or abs(float(ecart @ v)) > court_mesure / 2 - rayon - marge
    ):
        return VerdictMorceau(False, "trou pas couvert : morceau décalé")
    return VerdictMorceau(True)


# ------------------------------------------------------------------- la vision du micropore


class Regard(Protocol):
    """Ce que la vision demande aux caméras (vidange.vision.photo.Photographe)."""

    def mesure(self, nom: str) -> Photo: ...

    def derniere(self, nom: str) -> Photo: ...


@dataclass
class _Piste:
    """Un trou suivi d'une image à l'autre."""

    points: list[tuple[float, float, float]] = field(default_factory=list)  # angle, x, y
    # Numéro de la dernière image où il a été vu.
    derniere: int = 0


def _droite(points: list[tuple[float, float]]) -> tuple[float, float]:
    """x = pente × angle + origine, par les moindres carrés."""
    angles = np.array([p[0] for p in points])
    positions = np.array([p[1] for p in points])
    pente, origine = np.polyfit(angles, positions, 1)
    return float(pente), float(origine)


class VisionInspection:
    def __init__(
        self,
        reglages: ReglagesVision,
        regard: Regard,
        angle_plateau: Callable[[], float | None],
        ecarts: EcartsAttaches | None = None,
        attaches: ReconnaissanceAttaches | None = None,
    ) -> None:
        """`angle_plateau` : l'angle du plateau du chariot (°, continu : un tour de plus fait
        +360) ; None : pas lu. Une rangée de trous par tour (`finir_tour(rangee)`)."""
        assert reglages.inspection is not None
        self.reglages = reglages
        self.inspection = reglages.inspection
        self.regard = regard
        self.angle_plateau = angle_plateau
        self.ecarts = ecarts or EcartsAttaches()
        self.attaches = attaches or FausseReconnaissanceAttaches()
        self._verrou = threading.Lock()
        self._echantillons: list[Echantillon] = []
        self._derniere_image: float | None = None
        self._arret = threading.Event()
        self._fil: threading.Thread | None = None
        # Hauteur dans l'image (points) de chaque rangée vue au dernier tour de repérage.
        self._y_rangees: dict[int, float | None] = {}
        self.dernier_verdict: VerdictMorceau | None = None

    # ------------------------------------------------------------ les images du tour

    def _recommencer(self) -> None:
        self._arreter_le_fil()
        with self._verrou:
            self._echantillons = []
            self._derniere_image = None
        self.attaches.recommencer()
        self._arret.clear()
        self._fil = threading.Thread(target=self._boucle, name="vision-inspection", daemon=True)
        self._fil.start()

    def _arreter_le_fil(self) -> None:
        self._arret.set()
        if self._fil is not None:
            self._fil.join()
            self._fil = None

    def _boucle(self) -> None:
        while not self._arret.is_set():
            try:
                nouvelle = self.regarder()
            except ErreurVision as erreur:
                journal.warning("Caméra d'inspection : %s", erreur)
                nouvelle = False
            if not nouvelle:
                self._arret.wait(self.inspection.flanc.pause_s)

    def regarder(self) -> bool:
        """Regarde la dernière image reçue si elle est nouvelle (angle du plateau à cet instant) ;
        rend vrai si elle a été analysée."""
        photo = self.regard.derniere(self.inspection.camera)
        with self._verrou:
            if photo.heure == self._derniere_image:
                return False
            self._derniere_image = photo.heure
        angle = self.angle_plateau()
        if angle is None:
            return False
        self.analyser(angle, photo.image())
        return True

    def analyser(self, angle_plateau: float, image: np.ndarray) -> Echantillon:
        """Une image prise quand le plateau était à cet angle."""
        qrs, trous = lire_flanc(image, self.reglages)
        echantillon = Echantillon(angle_plateau, qrs, trous)
        with self._verrou:
            self._echantillons.append(echantillon)
        self.attaches.voir(angle_plateau, image)
        return echantillon

    def _echantillons_vus(self) -> list[Echantillon]:
        with self._verrou:
            return list(self._echantillons)

    # ------------------------------------------------------------ le QR

    def _centre_qr(self, echantillons: list[Echantillon]) -> tuple[str, float] | None:
        """Le QR du flanc (code) et l'angle du plateau où il passe au centre de l'image."""
        lectures: dict[str, dict[float, float]] = {}
        for echantillon in echantillons:
            for qr in echantillon.qrs:
                lectures.setdefault(qr.code, {})[round(echantillon.angle, 2)] = qr.x_px
        if not lectures:
            return None
        meilleurs = sorted(lectures, key=lambda code: len(lectures[code]), reverse=True)
        if len(meilleurs) > 1 and len(lectures[meilleurs[0]]) == len(lectures[meilleurs[1]]):
            journal.warning(
                "Plusieurs QR lus en même temps sur le flanc (%s) : aucun n'est retenu",
                ", ".join(meilleurs),
            )
            return None
        code = meilleurs[0]
        points = sorted(lectures[code].items())
        reglage = self.inspection.flanc
        # Le QR repasse devant la caméra à chaque tour : les lectures sont séparées en passages
        # (un trou de plus de `ecart_passage_deg` sans lecture), chacun donne son centre.
        passages: list[list[tuple[float, float]]] = [[points[0]]]
        for point in points[1:]:
            if point[0] - passages[-1][-1][0] > reglage.ecart_passage_deg:
                passages.append([])
            passages[-1].append(point)
        candidats: list[tuple[int, float]] = []
        for passage in passages:
            if len(passage) < max(2, reglage.lectures_min):
                continue
            pente, origine = _droite(passage)
            if abs(pente) <= 1e-9:
                continue
            centre = -origine / pente
            if passage[0][0] - reglage.marge_deg <= centre <= passage[-1][0] + reglage.marge_deg:
                candidats.append((len(passage), centre))
            else:
                journal.warning(
                    "QR %s : centre trouvé à %.0f°, loin des lectures (%.0f à %.0f°) : refusé",
                    code,
                    centre,
                    passage[0][0],
                    passage[-1][0],
                )
        if candidats:
            return code, max(candidats)[1]
        # Pas de passage entier : une lecture avec le QR au centre de l'image suffit.
        proche = min(points, key=lambda p: abs(p[1]))
        if abs(proche[1]) <= reglage.centre_tolerance_px:
            return code, proche[0]
        return None

    def _ecart(self, code: str, centre_qr: float) -> float:
        """L'écart attaches/QR de ce seau : celui du fichier ; sinon celui que donnent les
        attaches vues ce tour (reconnaissance sur photos réelles : un faux pour l'instant) ;
        sinon le réglage."""
        connu = self.ecarts.ecart(code)
        if connu is not None:
            return connu
        vues = self.attaches.trouvees()
        if vues:
            ecart = vues[0] - centre_qr
            self.ecarts.noter(code, ecart, "vision")
            return (ecart + 90) % 180 - 90
        defaut = self.inspection.flanc.ecart_attaches_defaut_deg
        journal.warning(
            "Seau %s : écart attaches/QR pas enregistré, %.1f° du réglage (vidange-vision ecart)",
            code,
            defaut,
        )
        return defaut

    # ------------------------------------------------------------ pour le Remplissage

    def commencer_lecture(self) -> None:
        """Le plateau va tourner le seau : regarder pendant ce temps."""
        self._recommencer()

    def finir_lecture(self) -> None:
        self._arreter_le_fil()

    def lire_seau(self) -> tuple[str, float] | None:
        """QR du seau sur le plateau, et angle des oreilles de son anse (° depuis +x, vue de
        dessus) à l'angle où est le plateau maintenant, corrigé de l'écart attaches/QR de ce
        seau ; None : pas lu. Le plateau est à l'arrêt : une image de plus, stabilisée."""
        try:
            photo = self.regard.mesure(self.inspection.camera)
            angle = self.angle_plateau()
            if angle is not None:
                self.analyser(angle, photo.image())
        except ErreurVision as erreur:
            journal.warning("Lecture du QR du flanc : %s", erreur)
        maintenant = self.angle_plateau()
        if maintenant is None:
            journal.warning("Lecture du QR du flanc : angle du plateau pas lu")
            return None
        lu = self._centre_qr(self._echantillons_vus())
        if lu is None:
            return None
        code, centre = lu
        geometrie = self.inspection.geometrie
        azimut_qr = azimut_au_centre(geometrie, geometrie.rayon_qr_m) + (maintenant - centre)
        oreilles = _normaliser(azimut_qr + self._ecart(code, centre))
        journal.info(
            "QR du flanc %s lu : au centre à %.1f° du plateau, oreilles à %.1f°",
            code,
            centre,
            oreilles,
        )
        return code, oreilles

    # ------------------------------------------------------------ pour le Micropore

    def commencer_tour(self) -> None:
        """Le plateau va faire un tour : regarder (QR, trous, attaches) pendant le tour."""
        self._recommencer()

    def plateau_z_repere(self, hauteur_rangee_m: float) -> float:
        """Plateau pour que la rangée de trous à cette hauteur sur le seau soit devant l'objectif
        (fixe, une seule rangée par image)."""
        return self.inspection.geometrie.objectif_z_m - hauteur_rangee_m

    def finir_tour(self, rangee: int) -> Reperage | None:
        """Le tour devant la rangée n° `rangee` est fini : ce qui a été vu (None : rien de
        lisible). Tous les trous vus sont de cette rangée."""
        self._arreter_le_fil()
        echantillons = self._echantillons_vus()
        qr = self._centre_qr(echantillons)
        code = None if qr is None else qr[0]
        angles, self._y_rangees[rangee] = self._trous_du_tour(echantillons)
        trous = {rangee: angles}
        if code is None and not angles:
            return None
        attaches = [] if qr is None else [round(a, 2) for a in self.attaches.trouvees()]
        if qr is not None and attaches:
            self._ecart(qr[0], qr[1])
        return Reperage(code, None, trous, attaches)

    def _pistes(self, echantillons: list[Echantillon]) -> list[_Piste]:
        reglage = self.inspection.trous
        pistes: list[_Piste] = []
        for rang, echantillon in enumerate(echantillons):
            prises: set[int] = set()
            for trou in echantillon.trous:
                meilleure, ecart = None, None
                for numero, piste in enumerate(pistes):
                    # Un trou qui n'a pas été vu depuis 2 images est fini : un autre trou qui
                    # arrive au même endroit est un autre trou.
                    if numero in prises or rang - piste.derniere > PAUSE_MAX_IMAGES:
                        continue
                    _, x, y = piste.points[-1]
                    dx, dy = abs(trou.x_px - x), abs(trou.y_px - y)
                    if dx <= reglage.suivi_max_px and dy <= reglage.suivi_max_y_px:
                        if ecart is None or dx < ecart:
                            meilleure, ecart = numero, dx
                if meilleure is None:
                    pistes.append(_Piste())
                    meilleure = len(pistes) - 1
                prises.add(meilleure)
                pistes[meilleure].points.append((echantillon.angle, trou.x_px, trou.y_px))
                pistes[meilleure].derniere = rang
        return pistes

    def _trous_du_tour(self, echantillons: list[Echantillon]) -> tuple[list[float], float | None]:
        """Pour chaque trou suivi sur au moins deux images : l'angle du plateau où il passe au
        centre de l'image ; et la hauteur moyenne des trous dans l'image (points)."""
        reglage = self.inspection
        trouves: list[tuple[float, float]] = []  # (y moyen, angle au centre)
        for piste in self._pistes(echantillons):
            angles = sorted({round(a, 2) for a, _, _ in piste.points})
            if len(angles) < 2:
                continue
            pente, origine = _droite([(a, x) for a, x, _ in piste.points])
            if abs(pente) < 1e-9:
                continue
            centre = -origine / pente
            if not (
                angles[0] - reglage.flanc.marge_deg
                <= centre
                <= angles[-1] + reglage.flanc.marge_deg
            ):
                continue
            y = sum(p[2] for p in piste.points) / len(piste.points)
            trouves.append((y, centre))
        # Un même trou vu au début et à la fin du tour : gardé une fois.
        uniques: list[tuple[float, float]] = []
        for y, centre in sorted(trouves, key=lambda t: t[1]):
            if any(abs(_normaliser(centre - c)) < reglage.trous.fusion_deg for _, c in uniques):
                continue
            uniques.append((y, centre))
        if not uniques:
            return [], None
        return sorted(c for _, c in uniques), sum(y for y, _ in uniques) / len(uniques)

    def controler_morceau(self, rangee: int, angle_deg: float) -> bool | None:
        """Le morceau posé sur ce trou est devant la caméra : True couvert, False découvert, de
        travers ou mal coupé, None : photo ratée."""
        try:
            image = self.regard.mesure(self.inspection.camera).image()
        except ErreurVision as erreur:
            journal.warning("Contrôle du morceau : %s", erreur)
            return None
        hauteur, largeur = image.shape[:2]
        y = self._y_rangees.get(rangee)
        centre = (largeur / 2, hauteur / 2 if y is None else y)
        verdict = controler_morceau_image(image, centre, self.inspection)
        self.dernier_verdict = verdict
        journal.info(
            "Micropore : rangée %d, trou à %.1f° : %s",
            rangee + 1,
            angle_deg,
            "couvert" if verdict.couvert else verdict.raison,
        )
        return verdict.couvert
