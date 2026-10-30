"""Lavage des couvercles de seau dans le fût, et leur retourneur (tâche 21 bis).

    couvercles = LavageCouvercles(lavage, retourneur, vision, demander_pause=chef_pause)
    couvercles.verifier_retourneur()    # avant le mode : bac et tige à leur place (caméra)
    prehension.lancer(lambda: couvercles.geste_laver("seau_a", "dessous"))
    prehension.lancer(lambda: couvercles.geste_retourner("dessous"))
    prehension.lancer(lambda: couvercles.geste_laver("seau_a", "dessus"))
    prehension.lancer(lambda: couvercles.geste_retourner("dessus"))

Laver une face (la tête tient le couvercle, la face à laver vers le bas) :
1. au-dessus du noyau, centre (0,352 ; 0,65), déjà décalé du décalage du format : le pont ne
   bouge que tête en haut (règle de la préhension), le décalage est donc pris avant la descente ;
2. le repère (collé sur le dessus, près du bord) est mis à ≈ 60° de −X côté +Y, photo par la
   caméra du plafond ;
3. descente : plateau flottant déclenché face au-dessus de 0,735 : arrêt et alerte ; appui de
   ≈ 15 N, jamais plus ;
4. noyau ≈ 5 s à 100 tr/min, bain dans les rampes (on ne brosse jamais à sec), couvercle tourné
   lentement (10 à 20 tr/min), vide surveillé ;
5. le repère est contrôlé par tranches de controle_s : à plus de 10° de l'angle commandé, le
   couvercle glisse (noyau arrêté, remontée de 2 mm, reprise) ; alerte au 2e glissement ;
6. repère ramené à son angle de photo, rinçage propre (comme pour les seaux : eau propre dans
   les rampes, la pompe garde le même niveau, l'eau du réseau remet le flotteur haut) ;
7. remontée, égouttage, 2e photo : repère à ± 10°, sinon alerte et couvercle « à vérifier »
   (le lavage continue).
Face « dessus » (couvercle retourné) : le repère est dessous, la caméra du plafond ne le voit
pas : ni orientation ni contrôle de glissement (le vide reste surveillé).

Retourneur (tige sur une barre du chariot de remplissage, bac inox sur le plateau fixe) : lâcher
au-dessus de la tige (barres fermées), remonter, reculer (axe à x ≤ 0,87), photo du bac ; barres
ouvertes avant que la tête descende sous 0,75, reprise au centre mesuré, barres refermées tête
au-dessus de 0,80. Pas retourné : nouvelle chute, alerte après 2 échecs ; hors du bac ou penché :
arrêt, alerte. La barrière lumineuse (à 0,7315) est surveillée pendant tout le mode : coupée,
la machine se met en pause avec un message.

Les barres et le chariot appartiennent au Remplissage (tâche 34) : ici, `Retourneur` est une
interface (un faux dans le simulateur). L'analyse des images est dans la tâche 22 : ici,
`VisionCouvercles` est un point d'appel (un faux dans le simulateur).

Ces verrous ne protègent que la MACHINE : la sécurité des personnes reste câblée.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from vidange.chef import ErreurEtape
from vidange.journal import donner_journal
from vidange.lavage.lavage import QUOI_FAIRE, QUOI_FAIRE_LAVE_BOCAL, QUOI_FAIRE_PANNEAU, Lavage
from vidange.prehension.prehension import Attente, Geste
from vidange.prehension.tete import Pas

journal = donner_journal("lavage.couvercles")

Face = Literal["dessous", "dessus"]

QUOI_FAIRE_RETOURNEUR = (
    "Le retourneur de couvercles n'est pas prêt : regarder la vidéo (bac inox sur le plateau, "
    "tige sur sa barre, chariot de remplissage à sa place, barres libres). Le remettre en place, "
    "puis acquitter et donner le Go."
)
QUOI_FAIRE_REPERE = (
    "La caméra du plafond ne voit pas le repère du couvercle : regarder la vidéo (repère "
    "décollé, couvercle à l'envers, caméra sale ?). Corriger, puis acquitter et donner le Go."
)
QUOI_FAIRE_PLATEAU = (
    "Le plateau flottant de la tête a touché trop haut au-dessus du noyau : regarder la vidéo "
    "(couvercle de travers, objet sur le noyau, fût de lavage mal posé ?). Corriger, puis "
    "acquitter et donner le Go."
)
QUOI_FAIRE_GLISSEMENT = (
    "Le couvercle glisse sur le noyau au lieu de tourner avec la tête : regarder la ventouse "
    "(usée, sale ?) et le couvercle (déformé, dépôts ?). Corriger, puis acquitter et donner le Go."
)
QUOI_FAIRE_VIDE = (
    "La ventouse ne tient plus le couvercle pendant son lavage : le noyau est arrêté. Regarder "
    "le couvercle (tombé dans le fût ?) et la ventouse. Le reprendre à la main s'il le faut, "
    "puis acquitter et donner le Go."
)
QUOI_FAIRE_BAC = (
    "Le couvercle n'est pas à plat dans le bac du retourneur (hors du bac ou penché) : le "
    "remettre à plat dans le bac à la main, puis acquitter et donner le Go."
)
QUOI_FAIRE_CHUTES = (
    "Le couvercle ne se retourne pas sur la tige du retourneur : regarder la vidéo (tige à sa "
    "place, hauteur du lâcher ?). Retourner le couvercle à la main dans le bac, puis acquitter et "
    "donner le Go."
)
MESSAGE_BARRIERE = (
    "Barrière lumineuse du retourneur coupée : la machine est en pause. Retirer ce qui coupe la "
    "barrière (main, objet), puis reprendre."
)

# Écart sous lequel deux positions sont égales (m).
_EGAL = 1e-6


@dataclass(frozen=True)
class PhotoBac:
    """Ce que la caméra voit du couvercle dans le bac du retourneur, après la chute."""

    dans_le_bac: bool
    a_plat: bool
    # Face du couvercle vue en haut (« dessus » : le repère est visible), None : pas sûr.
    face_visible: Face | None
    # Centre mesuré (axe de la tête pour le reprendre), None : pas mesuré.
    centre: tuple[float, float] | None


class VisionCouvercles(Protocol):
    """Ce que le lavage des couvercles demande à la caméra du plafond (Vision, tâche 22)."""

    def angle_repere(self) -> float | None:
        """Angle du repère du couvercle tenu (°, depuis −X côté +Y) ; None : pas vu."""
        ...

    def photo_bac(self) -> PhotoBac: ...

    def place_retourneur(self) -> tuple[float, float] | None:
        """Écarts (m) du bac et de la tige à leur place ; None : pas trouvés."""
        ...


class Retourneur(Protocol):
    """Ce que le lavage des couvercles demande au Remplissage (barres, chariot : tâche 34)."""

    def regler_barres(self, ecart_m: float) -> None:
        """Barres à `ecart_m` de l'axe de la tête (sans attendre)."""
        ...

    def ecart_barres(self) -> float | None:
        """Écart des barres (m) quand elles sont arrêtées ; None : en mouvement ou inconnu."""
        ...

    def chariot_en_place(self) -> bool: ...

    def barriere_coupee(self) -> bool | None:
        """Barrière lumineuse à 0,7315 coupée ; None : pas lue."""
        ...


def ecart_angle(a: float, b: float) -> float:
    """a − b ramené entre −180 et 180°."""
    return (a - b + 180) % 360 - 180


def _m(valeur: float) -> str:
    return f"{valeur:.3f}".rstrip("0").rstrip(".").replace(".", ",")


class LavageCouvercles:
    def __init__(
        self,
        lavage: Lavage,
        retourneur: Retourneur,
        vision: VisionCouvercles,
        demander_pause: Callable[[str], object] | None = None,
        alerter: Callable[[str], object] = lambda message: None,
    ) -> None:
        """`demander_pause(message)` : met la machine en pause (barrière coupée) ; None : la
        barrière coupée met le module en alarme. `alerter(message)` : alerte qui n'arrête rien
        (couvercle « à vérifier ») ; elle va aussi au journal."""
        assert lavage.reglages.couvercles is not None
        self.reglages = lavage.reglages.couvercles
        self.lavage = lavage
        self.prehension = lavage.prehension
        self.eau = lavage.eau
        self.retourneur = retourneur
        self.vision = vision
        self._demander_pause = demander_pause
        self._alerter = alerter
        self.retourneur_verifie = False
        # Couvercles dont le repère n'est pas revenu à sa place (2e photo) : à vérifier.
        self.a_verifier: list[str] = []
        self.couvercles_laves = 0
        self._barriere_coupee = False

    # ------------------------------------------------------------ mode et verrous

    def verifier_retourneur(self) -> None:
        """Avant le mode couvercles : la caméra trouve le bac et la tige à leur place, le
        chariot de remplissage est à la sienne ; sinon le mode ne démarre pas."""
        self.retourneur_verifie = False
        tolerance = self.reglages.retourneur.tolerance_place_m
        place = self.vision.place_retourneur()
        if place is None:
            raise ErreurEtape(
                "couvercles : la caméra ne trouve pas le bac et la tige du retourneur",
                QUOI_FAIRE_RETOURNEUR,
            )
        for quoi, ecart in zip(("bac", "tige"), place, strict=True):
            if abs(ecart) > tolerance + _EGAL:
                raise ErreurEtape(
                    f"couvercles : {quoi} du retourneur à {ecart * 1000:.0f} mm de sa place (au "
                    f"plus {tolerance * 1000:g} mm)",
                    QUOI_FAIRE_RETOURNEUR,
                )
        if not self.retourneur.chariot_en_place():
            raise ErreurEtape(
                "couvercles : chariot de remplissage pas à sa place (retourneur)",
                QUOI_FAIRE_RETOURNEUR,
            )
        self.retourneur_verifie = True
        journal.info("Lavage : retourneur de couvercles trouvé à sa place")

    def refus_mode(self) -> str | None:
        refus = self.lavage.refus_mode() or self.lavage.refus_fut("couvercles")
        if refus is not None:
            return refus
        if not self.retourneur_verifie:
            return "retourneur de couvercles pas vérifié par la caméra (bac et tige)"
        return None

    def mode_permis(self) -> bool:
        return self.refus_mode() is None

    def barriere_libre(self) -> bool:
        """Surveillance du mode couvercles : barrière lumineuse coupée ⇒ pause avec message
        (alarme si personne ne peut mettre la machine en pause, ou si la barrière n'est pas
        lue)."""
        coupee = self.retourneur.barriere_coupee()
        if coupee is None:
            return False
        if not coupee:
            self._barriere_coupee = False
            return True
        if not self._barriere_coupee:
            journal.warning("Lavage : %s", MESSAGE_BARRIERE)
        self._barriere_coupee = True
        if self._demander_pause is None:
            return False
        self._demander_pause(MESSAGE_BARRIERE)
        return True

    def _verifier_objet(self) -> None:
        p = self.prehension
        if p.objet is None or p.objet.sorte != "couvercle":
            raise ErreurEtape("couvercles : la tête ne tient pas de couvercle", QUOI_FAIRE)
        refus = self.refus_mode()
        if refus is not None:
            quoi_faire = QUOI_FAIRE_LAVE_BOCAL if "lave-bocal" in refus else QUOI_FAIRE_PANNEAU
            raise ErreurEtape(f"couvercles refusés : {refus}", quoi_faire)

    # ------------------------------------------------------------ morceaux

    def _angle_proche(self, angle: float) -> float:
        """L'angle (à 360° près) le plus proche de la tête, dans la course de sa rotation."""
        p = self.prehension
        assert p.pose is not None
        debut, fin = p.course_a
        candidats = [angle + 360 * tour for tour in range(-3, 4)]
        candidats = [a for a in candidats if debut <= a <= fin]
        if not candidats:
            raise ErreurEtape(f"couvercles : {angle:g}° hors de la course de la tête")
        return min(candidats, key=lambda a: abs(a - p.pose.a))  # type: ignore[union-attr]

    def _tourner(self, angle: float, texte: str) -> Geste:
        p = self.prehension
        assert p.pose is not None
        if abs(p.pose.a - angle) <= p.reglages.tolerance_deg:
            return
        resultat = yield Pas(texte, {"a": angle}, vide_perte_kpa=p.reglages.vide.perte_kpa)
        assert resultat is not None
        if resultat.arret == "vide":
            raise ErreurEtape(f"couvercles : vide perdu ({texte})", QUOI_FAIRE_VIDE)

    def _barres(self, ecart_m: float) -> Geste:
        """Barres du retourneur à `ecart_m` ; refermées seulement tête au-dessus de
        fermees_au_dessus_z."""
        r = self.reglages.retourneur
        p = self.prehension
        assert p.pose is not None
        tolerance = p.reglages.tolerance_m

        def arrivees() -> bool:
            ecart = self.retourneur.ecart_barres()
            return ecart is not None and abs(ecart - ecart_m) <= tolerance

        if arrivees():
            return
        if ecart_m < r.barres_ouvertes_m - _EGAL and p.pose.z < r.fermees_au_dessus_z - _EGAL:
            raise ErreurEtape(
                f"couvercles : barres du retourneur refermées seulement tête au-dessus de "
                f"{_m(r.fermees_au_dessus_z)} m (face à {_m(p.pose.z)} m)",
                QUOI_FAIRE_RETOURNEUR,
            )
        self.retourneur.regler_barres(ecart_m)
        yield Attente(
            f"barres du retourneur à {_m(ecart_m)} m",
            arrivees,
            r.barres_max_s,
            f"barres du retourneur pas à {_m(ecart_m)} m en {r.barres_max_s:g} s",
            QUOI_FAIRE_RETOURNEUR,
        )

    # ------------------------------------------------------------ laver une face

    def geste_laver(self, format: str, face: Face) -> Geste:
        """Laver la face `face` du couvercle tenu (« dessous » : couvercle à l'endroit, repère
        en haut ; « dessus » : couvercle retourné)."""
        c = self.reglages
        reglage = c.formats.get(format)
        if reglage is None:
            raise ErreurEtape(f"couvercles : format inconnu « {format} »")
        self._verifier_objet()
        # Noyau et couronne vont tourner : la caméra du plafond regarde le fût de lavage.
        self.lavage.verifier_plafond()
        if not self.eau.eau_dans_le_fut:
            raise ErreurEtape("couvercles : le fût de lavage n'est pas rempli", QUOI_FAIRE)
        p = self.prehension
        objet = p.objet
        assert objet is not None
        dx, dy = c.direction_decalage
        longueur = math.hypot(dx, dy)
        x = c.centre[0] + reglage.decalage_m * dx / longueur
        y = c.centre[1] + reglage.decalage_m * dy / longueur
        repere_visible = face == "dessous"
        journal.info("Lavage d'un couvercle %s, face %s", format, face)
        # 1. Au-dessus du noyau, décalage compris (le pont ne bouge que tête en haut).
        yield from p.aller(x, y)
        assert p.pose is not None
        # 2. Repère à son angle, photo.
        a_ref = repere_ref = repere_photo = 0.0
        if repere_visible:
            mesure = self.vision.angle_repere()
            if mesure is None:
                raise ErreurEtape(
                    "couvercles : la caméra ne voit pas le repère du couvercle", QUOI_FAIRE_REPERE
                )
            ecart = ecart_angle(c.repere_angle_deg, mesure)
            cible = self._angle_proche(p.pose.a + c.sens_repere * ecart)
            yield from self._tourner(cible, "repère du couvercle à son angle")
            photo = self.vision.angle_repere()
            repere_photo = c.repere_angle_deg if photo is None else photo
            a_ref, repere_ref = p.pose.a, repere_photo
            journal.info("Couvercle : repère à %.1f° (photo), tête à %.1f°", repere_photo, a_ref)
        # 3. Descente, plateau flottant surveillé au-dessus de contact_trop_haut_z, appui.
        face_z = getattr(reglage, f"bas_{face}_z") + objet.dessous_m
        resultat = yield Pas(
            "descente au-dessus du noyau", {"z": c.contact_trop_haut_z}, palper=True
        )
        assert resultat is not None
        if resultat.contact:
            raise ErreurEtape(
                f"couvercles : plateau flottant déclenché face à {_m(resultat.pose.z)} m, "
                f"au-dessus de {_m(c.contact_trop_haut_z)} m",
                QUOI_FAIRE_PLATEAU,
            )
        yield Pas("approche du noyau", {"z": face_z + c.approche_m})
        yield Pas(
            f"appui du couvercle sur le noyau (au plus {c.appui_n:g} N)",
            {"z": face_z},
            vitesse="approche",
            appui_arret_n=c.appui_n,
        )
        # 4. et 5. Bain dans les rampes, noyau et rotation lente, repère contrôlé.
        yield from self.eau.geste_arroser()
        debut, fin = p.course_a
        sens = 1 if p.pose.a <= (debut + fin) / 2 else -1
        degres_noyau_s = c.noyau_tr_min * 6
        degres_tete_s = c.rotation_tr_min * 6
        reste = c.duree_s
        glissements = 0
        while reste > _EGAL:
            duree = min(c.controle_s, reste)
            if not self.eau.arrosage_en_marche():
                raise ErreurEtape(
                    "couvercles : arrosage arrêté, on ne brosse jamais à sec", QUOI_FAIRE
                )
            resultat = yield Pas(
                f"brossage du couvercle ({face}) : noyau {c.noyau_tr_min:g} tr/min, couvercle "
                f"{c.rotation_tr_min:g} tr/min",
                {"a": p.pose.a + sens * degres_tete_s * duree},
                brosses={"noyau": degres_noyau_s * duree},
                duree_s=duree,
                vide_perte_kpa=p.reglages.vide.perte_kpa,
            )
            assert resultat is not None
            if resultat.arret == "vide":
                raise ErreurEtape(
                    f"couvercles : vide perdu pendant le brossage ({face}) : noyau arrêté",
                    QUOI_FAIRE_VIDE,
                )
            reste -= duree
            if not repere_visible:
                continue
            mesure = self.vision.angle_repere()
            if mesure is None:
                continue
            attendu = repere_ref + c.sens_repere * (p.pose.a - a_ref)
            ecart = ecart_angle(mesure, attendu)
            if abs(ecart) <= c.glissement_max_deg:
                continue
            glissements += 1
            journal.warning(
                "Couvercle : repère à %.1f° pour %.1f° commandé : il glisse (n° %d)",
                mesure,
                attendu,
                glissements,
            )
            if glissements >= c.glissements_max:
                raise ErreurEtape(
                    f"couvercles : le couvercle a glissé {glissements} fois sur le noyau (repère "
                    f"à {abs(ecart):.0f}° de l'angle commandé)",
                    QUOI_FAIRE_GLISSEMENT,
                )
            # Le noyau est arrêté (fin de la tranche) : remontée, puis reprise.
            yield Pas(
                f"couvercle qui glisse : remontée de {c.remontee_glissement_m * 1000:g} mm",
                {"z": p.pose.z + c.remontee_glissement_m},
            )
            a_ref, repere_ref = p.pose.a, mesure
        # 6. Repère ramené à son angle de photo, rinçage propre (comme pour les seaux).
        if repere_visible:
            cible = a_ref + c.sens_repere * ecart_angle(repere_photo, repere_ref)
            yield from self._tourner(self._angle_proche(cible), "repère ramené à son angle")
        self.eau.arreter_arrosage()
        yield from self.eau.geste_rincer()
        # 7. Remontée, égouttage, 2e photo.
        resultat = yield Pas(
            "remonter le couvercle",
            {"z": p.reglages.haut_z},
            vide_perte_kpa=p.reglages.vide.perte_kpa,
        )
        assert resultat is not None
        if resultat.arret == "vide":
            raise ErreurEtape(
                "couvercles : vide perdu en remontant : le couvercle est resté dans le fût",
                QUOI_FAIRE_VIDE,
            )
        yield Pas("égoutter le couvercle au-dessus du fût", attente_s=c.egouttage_s)
        if repere_visible:
            mesure = self.vision.angle_repere()
            if mesure is None or abs(ecart_angle(mesure, repere_photo)) > c.glissement_max_deg:
                vu = "pas vu" if mesure is None else f"à {mesure:.0f}°"
                message = (
                    f"couvercle {format} à vérifier : repère {vu} après le lavage, attendu à "
                    f"{repere_photo:.0f}° (± {c.glissement_max_deg:g}°)"
                )
                journal.warning("Lavage : %s", message)
                self.a_verifier.append(format)
                self._alerter(message)
        if face == "dessus":
            self.couvercles_laves += 1
        journal.info("Lavage : couvercle %s lavé, face %s", format, face)

    # ------------------------------------------------------------ retourneur

    def geste_retourner(self, face_lavee: Face) -> Geste:
        """Lâcher le couvercle tenu au-dessus de la tige, le reprendre retourné dans le bac.
        `face_lavee` : la face qu'on vient de laver (tournée vers le bas) ; après la chute,
        c'est elle qui doit être vue en haut."""
        r = self.reglages.retourneur
        p = self.prehension
        self._verifier_objet()
        if not self.retourneur.chariot_en_place():
            raise ErreurEtape(
                "couvercles : chariot de remplissage pas à sa place (retourneur)",
                QUOI_FAIRE_RETOURNEUR,
            )
        chutes = 0
        while True:
            # Lâcher au-dessus de la tige, barres fermées (tête en haut pour les refermer).
            yield from p.monter()
            yield from self._barres(r.barres_fermees_m)
            yield from p.aller(*r.lacher)
            yield Pas("descendre au-dessus de la tige", {"z": r.lacher_face_z})
            yield from p.lacher()
            chutes += 1
            # Remonter, reculer pour la photo du bac.
            yield from p.aller(min(r.recul_x_max, r.lacher[0]), r.lacher[1])
            photo = self.vision.photo_bac()
            if not photo.dans_le_bac or not photo.a_plat or photo.centre is None:
                quoi = "hors du bac" if not photo.dans_le_bac else "penché ou pas mesuré"
                raise ErreurEtape(f"couvercles : couvercle {quoi} après la chute", QUOI_FAIRE_BAC)
            # Barres ouvertes avant que la tête descende sous ouvertes_sous_z ; reprise.
            yield from self._barres(r.barres_ouvertes_m)
            yield from p.geste_prendre("couvercle", *photo.centre, r.bac_contact_z)
            yield from self._barres(r.barres_fermees_m)
            if photo.face_visible == face_lavee:
                journal.info("Lavage : couvercle retourné (face %s en haut)", face_lavee)
                return
            journal.warning("Lavage : couvercle pas retourné (chute n° %d)", chutes)
            if chutes >= r.chutes_max:
                raise ErreurEtape(
                    f"couvercles : couvercle pas retourné après {chutes} chutes",
                    QUOI_FAIRE_CHUTES,
                )
