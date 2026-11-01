"""La caméra du plafond : contrôle du lave-bocal, et « deviner le travail ».

    plafond = CameraPlafond(reglages.vision, photographe, reconnaissance, pont_x,
                            places_photo(reglages.machine), tolerance)
    controle = ControleLaveBocal(plafond, alerter)
    controle.refus(ecran_pose=False)       # avant de lever un seau dans le fût de lavage...
    deviner = DevinerTravail(plafond)
    proposition = deviner.regarder()       # la règle qui gagne, son travail, la photo

Une photo du plafond ne se prend que pont garé au bout opposé à la zone photographiée (sinon il
cache la vue : places du Portique, `vidange.portique.places_photo`), et une photo plus vieille que
`photo_age_max_s` est refusée.

1. Lave-bocal, juste avant chaque geste dangereux pour lui (lever un seau dans le fût de lavage,
   tourner noyau ou couronne) : repère ArUco vu ⇒ lave-bocal posé (seau, noyau, couronne
   interdits) ; fût vide vu clairement ⇒ seaux permis ; doute (vue cachée, buée, objet inconnu)
   ⇒ rien ne bouge, alerte avec la photo, on attend « Vérifié ». La caméra et la confirmation à
   l'écran (tâche 21 bis) doivent être d'accord ; sinon, doute.
2. Deviner le travail : la photo devient une liste d'objets (`Inventaire`, donnée par une
   `Reconnaissance`), puis des faits (« fût plein », « bocaux sales »...), puis la première
   règle de vision.yaml qui correspond. Le Pi PROPOSE le travail et attend le Go de Karulium.

La reconnaissance des objets demande une trentaine de photos réelles par situation : il n'y a ici
que l'interface et un faux (`FausseReconnaissance`). Sans reconnaissance sûre : doute (règle 1).
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import numpy as np

from vidange.journal import donner_journal
from vidange.reglages import FAITS_PLAFOND, ReglagesVision, RegleVision
from vidange.vision.aruco import chercher_reperes
from vidange.vision.photo import ErreurVision, Photo, Photographe, verifier_age

journal = donner_journal("vision.plafond")

QUOI_FAIRE_DOUTE = (
    "La caméra du plafond n'est pas sûre de ce qu'elle voit (photo dans le registre et sur la "
    "page web). Aller voir le fût de lavage, corriger (lave-bocal posé ou enlevé, confirmé à "
    "l'écran ; objet retiré), puis appuyer sur « Vérifié » et donner le Go."
)


@dataclass(frozen=True)
class BocalVu:
    vide: bool
    propre: bool
    capsule: bool = True


@dataclass(frozen=True)
class SeauVu:
    plein: bool
    propre: bool
    couvercle: bool = False


@dataclass(frozen=True)
class Inventaire:
    """Ce que la reconnaissance voit sur la photo du plafond."""

    # La reconnaissance est-elle sûre d'elle ?
    sur: bool = True
    # Fût du poste du fût (None : pas de fût).
    fut_poste: Literal["vide", "plein_mais", "plein_substrat"] | None = None
    # Bocaux au stockage.
    bocaux: tuple[BocalVu, ...] = ()
    seaux: tuple[SeauVu, ...] = ()
    couvercles_sales: int = 0
    places_libres: int = 0
    # Bocal de semence prêt au garage du mycélium.
    bocal_semence_pret: bool = False
    # Fût de lavage (None : pas vu).
    fut_lavage: Literal["vide", "seau", "lave_bocal"] | None = None
    # Objets inconnus, et pièces mal placées sur un trajet (ce que c'est, dit simplement).
    inconnus: tuple[str, ...] = ()
    mal_places: tuple[str, ...] = ()


class Reconnaissance(Protocol):
    def reconnaitre(self, image: np.ndarray) -> Inventaire | None:
        """Les objets de la photo ; None si elle ne sait pas."""
        ...


class FausseReconnaissance:
    """Rend l'inventaire qu'on lui donne (tests, simulateur) ; None par défaut : pas sûre."""

    def __init__(self, inventaire: Inventaire | None = None) -> None:
        self.inventaire = inventaire
        self.appels = 0

    def reconnaitre(self, image: np.ndarray) -> Inventaire | None:
        self.appels += 1
        return self.inventaire


def faits(inventaire: Inventaire | None, lave_bocal_vu: bool) -> dict[str, bool]:
    """Les conditions des règles (FAITS_PLAFOND) d'après l'inventaire et le repère du
    lave-bocal. Le repère et la reconnaissance en désaccord sur le lave-bocal : doute."""
    if inventaire is None:
        resultat = dict.fromkeys(FAITS_PLAFOND, False)
        resultat.update(doute=True, lave_bocal_pose=lave_bocal_vu)
        return resultat
    inv = inventaire
    lave_bocal_reconnu = inv.fut_lavage == "lave_bocal"
    desaccord = inv.fut_lavage is not None and lave_bocal_reconnu != lave_bocal_vu
    resultat = {
        "doute": not inv.sur or desaccord,
        "objet_inconnu": bool(inv.inconnus),
        "piece_mal_placee": bool(inv.mal_places),
        "fut_plein": inv.fut_poste in ("plein_mais", "plein_substrat"),
        "fut_plein_mais": inv.fut_poste == "plein_mais",
        "bocaux_vides_propres": any(b.vide and b.propre for b in inv.bocaux),
        "seaux_vides_propres": any(not s.plein and s.propre for s in inv.seaux),
        "bocal_semence_pret": inv.bocal_semence_pret,
        "bocaux_sales": any(not b.propre for b in inv.bocaux),
        "seaux_sales": any(not s.propre for s in inv.seaux),
        "couvercles_sales": inv.couvercles_sales > 0,
        "lave_bocal_pose": lave_bocal_vu or lave_bocal_reconnu,
        "places_libres": inv.places_libres > 0,
    }
    assert set(resultat) == set(FAITS_PLAFOND)
    return resultat


def _vraie(condition: str, faits_vus: dict[str, bool]) -> bool:
    if condition.startswith("pas "):
        return not faits_vus[condition.removeprefix("pas ")]
    return faits_vus[condition]


def choisir(regles: list[RegleVision], faits_vus: dict[str, bool]) -> RegleVision:
    """La première règle qui correspond (la dernière, sans condition, correspond toujours)."""
    for regle in regles:
        if all(_vraie(c, faits_vus) for c in regle.si) and (
            not regle.si_un_de or any(_vraie(c, faits_vus) for c in regle.si_un_de)
        ):
            return regle
    return regles[-1]


class CameraPlafond:
    def __init__(
        self,
        reglages: ReglagesVision,
        photographe: Photographe,
        reconnaissance: Reconnaissance,
        pont_x: Callable[[], float | None],
        places_pont: Mapping[str, float],
        tolerance_m: float,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        """`pont_x` : position du pont (None : inconnue). `places_pont` : x du pont pour
        photographier chaque zone (« fut_poste », « stockage »), à `tolerance_m` près."""
        self.reglages = reglages
        self.plafond = reglages.plafond
        self.photographe = photographe
        self.reconnaissance = reconnaissance
        self._pont_x = pont_x
        self.places_pont = dict(places_pont)
        self.tolerance_m = tolerance_m
        self.horloge = horloge

    def refus_photo(self, zone: str = "fut_poste") -> str | None:
        """Pourquoi on ne peut pas photographier cette zone maintenant (pont pas garé au bout
        opposé), ou None."""
        x = self._pont_x()
        if x is None:
            return "position du pont inconnue : pas de photo du plafond"
        place = self.places_pont[zone]
        if abs(x - place) > self.tolerance_m + 1e-9:
            return (
                f"pont pas garé (x {x:.3f} m, il faut x {place:.3f} m pour photographier "
                f"« {zone} ») : il cache la vue du plafond"
            )
        return None

    def photo(self, zone: str = "fut_poste") -> Photo:
        refus = self.refus_photo(zone)
        if refus is not None:
            raise ErreurVision(refus)
        return self.photographe.mesure("plafond")

    def verifier(self, photo: Photo) -> np.ndarray:
        """L'image d'une photo assez récente ; PhotoTropVieille sinon."""
        verifier_age(photo, self.plafond.photo_age_max_s, self.horloge)
        return photo.image()

    def lave_bocal_vu(self, image: np.ndarray) -> bool:
        aruco = self.reglages.aruco
        return aruco.lave_bocal in chercher_reperes(image, aruco.dictionnaire)


@dataclass(frozen=True)
class Proposition:
    regle: RegleVision
    faits: dict[str, bool]
    photo: Photo
    # Fichier de la photo gardée (alertes), ou None.
    chemin: Path | None = None
    # Règle « attendre » : nouvelle photo dans ce temps (s).
    prochaine_photo_s: float | None = None

    @property
    def travail(self) -> str:
        return self.regle.travail

    @property
    def sorte(self) -> str:
        return self.regle.sorte

    @property
    def message(self) -> str:
        return self.regle.message


class DevinerTravail:
    def __init__(self, plafond: CameraPlafond) -> None:
        self.plafond = plafond
        self.derniere: Proposition | None = None

    def regarder(self) -> Proposition:
        """Prend la photo (pont garé) et propose le travail ; ErreurVision si la photo est
        impossible ou trop vieille (rien n'est proposé)."""
        return self.juger(self.plafond.photo())

    def juger(self, photo: Photo) -> Proposition:
        image = self.plafond.verifier(photo)
        vu = self.plafond.lave_bocal_vu(image)
        faits_vus = faits(self.plafond.reconnaissance.reconnaitre(image), vu)
        regle = choisir(self.plafond.plafond.regles, faits_vus)
        chemin = None
        if regle.sorte == "alerte":
            chemin = self.plafond.photographe.enregistrer(photo, f"plafond : {regle.message}")
        attente = self.plafond.plafond.attente_s if regle.sorte == "attendre" else None
        proposition = Proposition(regle, faits_vus, photo, chemin, attente)
        journal.info("Plafond : règle n° %d (%s) : %s", regle.numero, regle.sorte, regle.message)
        self.derniere = proposition
        return proposition


class ControleLaveBocal:
    def __init__(
        self, plafond: CameraPlafond, alerter: Callable[[str], object] = lambda message: None
    ) -> None:
        """`alerter(message)` : alerte (écran, téléphone) ; elle va aussi au journal."""
        self.plafond = plafond
        self._alerter = alerter
        # « Vérifié » de Karulium : le prochain contrôle passe (une fois).
        self._verifie = False

    @property
    def actif(self) -> bool:
        return self.plafond.plafond.controle_lave_bocal

    def marquer_verifie(self) -> None:
        """Bouton « Vérifié » : Karulium est allé voir ; le prochain geste passe sans photo."""
        self._verifie = True
        journal.info("Plafond : lave-bocal vérifié par Karulium")

    def verdict(self, photo: Photo) -> tuple[str, str]:
        """(« lave_bocal » | « vide » | « doute », raison)."""
        image = self.plafond.verifier(photo)
        if self.plafond.lave_bocal_vu(image):
            return "lave_bocal", "repère du lave-bocal vu"
        inventaire = self.plafond.reconnaissance.reconnaitre(image)
        if inventaire is None or not inventaire.sur:
            return "doute", "fût de lavage pas vu clairement"
        if inventaire.inconnus:
            return "doute", f"objet inconnu : {', '.join(inventaire.inconnus)}"
        if inventaire.fut_lavage != "vide":
            return "doute", "fût de lavage pas vu vide (repère du lave-bocal pas vu)"
        return "vide", "fût de lavage vu vide"

    def refus(self, ecran_pose: bool) -> str | None:
        """Avant de lever un seau dans le fût de lavage, ou de tourner noyau ou couronne :
        raison du refus, ou None. `ecran_pose` : le lave-bocal est confirmé posé à l'écran."""
        if not self.actif:
            return None
        if self._verifie:
            self._verifie = False
            return None
        photo = None
        try:
            photo = self.plafond.photo()
            verdict, raison = self.verdict(photo)
        except ErreurVision as erreur:
            verdict, raison = "doute", str(erreur)
        if verdict == "lave_bocal" and not ecran_pose:
            verdict, raison = "doute", "la caméra voit le lave-bocal, l'écran le dit enlevé"
        elif verdict == "vide" and ecran_pose:
            verdict, raison = "doute", "la caméra voit le fût vide, l'écran dit le lave-bocal posé"
        if verdict == "vide":
            return None
        if verdict == "lave_bocal":
            return "lave-bocal vu par la caméra du plafond : seau, noyau et couronne interdits"
        message = f"caméra du plafond, doute : {raison} ; rien ne bouge"
        if photo is not None:
            self.plafond.photographe.enregistrer(photo, message)
        journal.warning("Plafond : %s", message)
        self._alerter(message)
        return message
