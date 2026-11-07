"""La Fermeture des seaux, côté Pi (module gelé le 01/11/2026 ; tâche 41) : le couvercle posé sur le
seau plein est clipsé par le PLATEAU du chariot de remplissage, qui monte contre le rouleau d'un
bras puis tourne. Le bras est tourné à vide par un servo (DS3225, voie de la PCA9685 du boîtier du
chariot) ; il n'a aucun capteur : c'est la balance du plateau qui vérifie.

    fermeture = Fermeture(reglages.machine, bras, registre)
    fermeture.brancher(remplissage)    # le Remplissage joue `geste_fermer` et suit le bras

Les gestes (pas du Remplissage, `Remplissage.geste_fermer` amène d'abord le seau à sa hauteur
d'approche, au y de la fermeture, barres ouvertes) :
  1) bras rangé, plateau à H_app (toujours ≤ la limite du bras, règle 5) ;
  2) le bras passe de rangé à travail en sens trigo (rampe, attente) : le servo ne bouge que
     plateau ≤ la limite du bras ; il ne voit rien, c'est l'étape 4 qui le prouve ;
  3) pesée P0 (seau plein + couvercle), plateau immobile ;
  4) montée en appui, lente : le contact (F > F_contact, F = (P − P0) × g) doit venir dans la
     fenêtre Hc ± fenetre ; puis montée jusqu'à Hf, F ≤ F_max tout le temps :
       4a aucun contact à Hc + fenêtre : arrêt, retour à H_app, bras rangé, alerte « pas de
          contact : bras pas au travail ou couvercle absent » ;
       4b contact avant Hc − trop tôt : même retour, alerte « couvercle mal posé » ;
       4c F > F_max avant Hf : même retour, alerte « couvercle bloqué » (pas de nouvel essai tout
          seul : question de la PR) ;
  5) à Hf, le plateau tourne EN SENS HORAIRE (jamais trigo tant qu'il y a contact : le frottement
     garde le doigt plaqué sur sa butée) ; F > F_max : arrêt de la rotation, retour à H_app,
     alerte ;
  6) le plateau redescend à H_app et le Pi attend F < F_contact (sinon : alarme « le couvercle
     reste contre le rouleau », le bras reste où il est) ;
  7) le bras revient à rangé (sens horaire, rampe, attente).

Mode couvercles : le bras reste rangé et ne reçoit aucun ordre. Au démarrage ou après une coupure,
le Pi ne sait pas où est le bras : zéro de la montée d'abord (plateau en bas), puis `geste_ranger`
(premier ordre sans rampe), et seulement ensuite le reste (le Remplissage refuse de monter le
plateau au-dessus de la limite du bras tant qu'il ne l'a pas vu rangé).

Ces verrous ne protègent que la MACHINE : la sécurité des personnes reste câblée (et rien n'est
câblé en dur pour ce module).
"""

import math
import time
from collections.abc import Callable, Generator
from typing import TYPE_CHECKING

from vidange.chef import ErreurEtape
from vidange.fermeture.bras import BrasFermeture
from vidange.griffe.bras import G
from vidange.journal import donner_journal
from vidange.materiel import ErreurMateriel
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import Machine
from vidange.remplissage.chariot import Pas, Resultat
from vidange.vision.qr import marquer_a_verifier

if TYPE_CHECKING:
    from vidange.remplissage.remplissage import Remplissage

journal = donner_journal("fermeture")

MODULE = "fermeture"
Geste = Generator[Pas, Resultat, None]

# Un tour, en degrés ; une minute en secondes (tr/min → °/s).
TOUR_DEG = 360.0
MINUTE_S = 60.0
_EGAL = 1e-6

QUOI_FAIRE = (
    "Regarder le seau à la caméra : le couvercle est-il clipsé ? Le clipser à la main si besoin, "
    "puis marquer le seau « vérifié ». Le cycle continue."
)
QUOI_FAIRE_BRAS = (
    "Le servo du bras de fermeture n'a pas pu être commandé (carte du plateau muette ou ordre "
    "refusé) : vérifier le câble du bus des pesées et la carte du plateau, puis acquitter et "
    "donner le Go."
)
QUOI_FAIRE_PLATEAU = (
    "Le bras de fermeture ne tourne que plateau assez bas, et son premier ordre après un démarrage "
    "se fait plateau en bas : faire le zéro de la montée (prise d'origine de la carte du chariot), "
    "puis acquitter et donner le Go."
)
QUOI_FAIRE_CONTACT = (
    "Le couvercle reste contre le rouleau (ou le plateau ne redescend pas) : regarder la vidéo, "
    "dégager le couvercle à la main SANS toucher au bras, puis acquitter et donner le Go. Le bras "
    "reste où il est."
)


class Fermeture:
    def __init__(
        self,
        machine: Machine,
        bras: BrasFermeture,
        registre: Registre | None = None,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        assert machine.fermeture is not None and machine.remplissage is not None
        self.reglages = machine.fermeture
        self.course_z = machine.axes["plateau_z"].course
        self.bras = bras
        self.registre = registre
        self._horloge = horloge
        self.remplissage: Remplissage | None = None
        self.messages: list[str] = []
        # Le couvercle est (peut-être) contre le rouleau : pas de rotation trigo du plateau.
        self._en_contact = False
        # Seaux fermés depuis le démarrage (codes).
        self.fermes: list[str] = []

    # ------------------------------------------------------------ branchements

    def brancher(self, remplissage: "Remplissage") -> None:
        """Le Remplissage joue `geste_fermer` et `geste_ranger_bras`, suit le bras (règles 4 et 5)
        et le contact (règle 11)."""
        self.remplissage = remplissage
        remplissage.brancher_fermeture(
            bras_range=self.bras_range,
            en_contact=self.en_contact,
            fermer=self.geste_fermer,
            ranger=self.geste_ranger,
            arreter=self.arreter,
        )

    def bras_range(self) -> bool | None:
        return self.bras.est_range()

    def en_contact(self) -> bool:
        return self._en_contact

    def arreter(self) -> None:
        """Arrêt du module : le signal du servo n'est JAMAIS coupé (le bras reste où il est). Le
        couvercle reste noté « contre le rouleau » jusqu'à la prochaine descente vue."""
        journal.info("Fermeture : arrêt (le bras garde son angle)")

    # ------------------------------------------------------------ les gestes

    def geste_ranger(self) -> Geste:
        """Au démarrage, après une coupure, ou bras pas vu rangé : bras rangé, plateau assez bas
        (le premier ordre arrive sans rampe, plateau en bas)."""
        self._en_contact = False
        yield from self._aller("range")

    def geste_fermer(self) -> Geste:
        remplissage = self._remplissage()
        seau = remplissage.seau
        if seau is None:
            return
        format = seau.format
        fmt = self.reglages.formats.get(format)
        if fmt is None:
            self._probleme(seau.code, f"format « {format} » inconnu de la fermeture : pas fermé")
            return
        r = self.reglages
        m = r.montee
        hf, hc = fmt.hf_m, r.hc(format)
        h_app = r.h_approche(format, self.course_z[0])
        # Le seau a été amené à H_app : le couvercle ne touche rien, le bras peut bouger.
        self._en_contact = False
        redemarrages = self.bras.redemarrages_vus
        yield from self._aller("range")
        yield from self._aller("travail")
        # 3) le poids du seau plein avec son couvercle, plateau immobile.
        resultat = yield Pas("fermeture 3) : pesée du seau fermé libre (P0)", pesee=True)
        p0 = self._poids(resultat)
        poids_max = p0 + m.force_max_n / G
        raison = self._carte_redemarree(redemarrages)
        if raison is None:
            # 4) montée en appui : le contact doit venir dans la fenêtre de Hc.
            self._en_contact = True
            resultat = yield Pas(
                "fermeture 4) : montée jusqu'au contact du couvercle",
                {"z": hc + m.fenetre_contact_m},
                vitesse_z=m.vitesse_m_s,
                contact_kg=m.force_contact_n / G,
                poids_max_kg=poids_max,
            )
            raison = self._raison_du_contact(resultat, hc)
        if raison is None:
            resultat = yield Pas(
                "fermeture 4) : montée jusqu'à Hf, couvercle clipsé",
                {"z": hf},
                vitesse_z=m.vitesse_m_s,
                poids_max_kg=poids_max,
                pesee=True,
            )
            raison = self._raison_de_l_effort(resultat) or self._carte_redemarree(redemarrages)
        if raison is None:
            force = (self._poids(resultat) - p0) * G
            journal.info("Fermeture : couvercle clipsé à Hf, effort %.0f N", force)
            self._noter_mesure(seau.code, seau.cycle, force)
            # 5) le plateau tourne en sens HORAIRE (le Remplissage refuse le trigo en contact).
            rot = r.rotation
            cible = resultat.pose.a + rot.sens_horaire * rot.tours * TOUR_DEG
            resultat = yield Pas(
                "fermeture 5) : le plateau tourne en sens horaire",
                {"a": cible},
                vitesse_a=rot.tr_min * TOUR_DEG / MINUTE_S,
                poids_max_kg=poids_max,
            )
            raison = self._raison_de_l_effort(resultat) or self._carte_redemarree(redemarrages)
        if raison is not None:
            yield from self._retour(raison, seau.code, h_app, p0)
            return
        # 6) le plateau redescend ; le Pi attend F < F_contact.
        resultat = yield Pas("fermeture 6) : le plateau redescend", {"z": h_app}, pesee=True)
        if (self._poids(resultat) - p0) * G >= m.force_contact_n:
            raise ErreurEtape(
                "fermeture : le couvercle reste contre le rouleau (le plateau est redescendu mais "
                "la balance lit encore l'effort)",
                QUOI_FAIRE_CONTACT,
            )
        self._en_contact = False
        # 7) le bras revient à rangé.
        yield from self._aller("range")
        if seau.code is not None:
            self.fermes.append(seau.code)
        self._dire(f"seau {seau.code or '?'} fermé")

    # ------------------------------------------------------------ morceaux de gestes

    def _remplissage(self) -> "Remplissage":
        assert self.remplissage is not None, "fermeture pas branchée au Remplissage"
        return self.remplissage

    def _poids(self, resultat: Resultat) -> float:
        if resultat.poids_kg is None:
            raise ErreurEtape("fermeture : la balance du plateau n'a rien lu")
        return resultat.poids_kg

    def _carte_redemarree(self, avant: int) -> str | None:
        if self.bras.redemarrages_vus != avant:
            return (
                "la carte du plateau a redémarré pendant la fermeture (le servo a pu se relâcher)"
            )
        return None

    def _raison_de_l_effort(self, resultat: Resultat) -> str | None:
        if resultat.depasse:
            return "couvercle bloqué : l'effort a dépassé le maximum avant la fin du clipsage"
        return None

    def _raison_du_contact(self, resultat: Resultat, hc: float) -> str | None:
        """4a, 4b, 4c : ce que dit la montée en appui."""
        m = self.reglages.montee
        raison = self._raison_de_l_effort(resultat)
        if raison is not None:
            return raison
        if not resultat.contact:
            return "pas de contact : bras pas au travail ou couvercle absent"
        if resultat.pose.z < hc - m.contact_trop_tot_m - _EGAL:
            return "couvercle mal posé (de travers ou sur l'anse) : contact trop tôt"
        return None

    def _retour(self, raison: str, code: str | None, h_app: float, p0: float) -> Geste:
        """Arrêt de la montée ou de la rotation : retour à H_app, bras rangé, alerte. Le Pi ne
        refait pas l'essai tout seul. Si l'effort ne retombe pas, le bras ne bouge pas."""
        resultat = yield Pas("fermeture : retour à la hauteur d'approche", {"z": h_app}, pesee=True)
        if (self._poids(resultat) - p0) * G >= self.reglages.montee.force_contact_n:
            raise ErreurEtape(
                f"fermeture : {raison} ; le couvercle reste contre le rouleau (le bras ne bouge "
                "pas)",
                QUOI_FAIRE_CONTACT,
            )
        self._en_contact = False
        yield from self._aller("range")
        self._probleme(code, raison)

    def _aller(self, destination: str) -> Geste:
        """Le bras va à « range » ou « travail » par une rampe (le premier ordre après un
        démarrage arrive sans rampe, plateau en bas), puis l'attente."""
        remplissage = self._remplissage()
        bras = self.bras
        if destination == "range" and bras.est_range() is True:
            return
        refus = remplissage.refus_bras_galet()
        if refus is not None:
            raise ErreurEtape(f"fermeture : servo du bras refusé : {refus}", QUOI_FAIRE_PLATEAU)
        cible = bras.angle_range() if destination == "range" else bras.angle_travail()
        rampe = self.reglages.bras.rampe
        actuel = bras.angle
        if actuel is None:
            if not remplissage.regles.en_bas(remplissage.chariot.position()):
                raise ErreurEtape(
                    "fermeture : le bras n'a encore jamais été ordonné depuis le démarrage : son "
                    "premier ordre se fait plateau en bas",
                    QUOI_FAIRE_PLATEAU,
                )
            angles = [cible]
        else:
            par_pas = rampe.degres / rampe.duree_s * rampe.pas_s
            n = max(1, math.ceil(abs(cible - actuel) / par_pas - _EGAL))
            angles = [actuel + (cible - actuel) * i / n for i in range(1, n + 1)]
        texte = "bras au travail" if destination == "travail" else "bras rangé"
        for i, angle in enumerate(angles):
            try:
                bras.commander(angle)
            except ErreurMateriel as erreur:
                raise ErreurEtape(
                    f"fermeture : servo du bras pas commandé ({erreur})", QUOI_FAIRE_BRAS
                ) from erreur
            dernier = i == len(angles) - 1
            yield Pas(
                f"fermeture : {texte}",
                attente_s=self.reglages.bras.attente_s if dernier else rampe.pas_s,
            )

    # ------------------------------------------------------------ alertes et registre

    def _probleme(self, code: str | None, message: str) -> None:
        self._dire(f"seau {code or '?'} : {message}", alerte=True)
        if code is not None:
            marquer_a_verifier(self.registre, "seau", code, f"fermeture à vérifier : {message}")

    def _dire(self, message: str, alerte: bool = False) -> None:
        if alerte:
            journal.warning("Fermeture : %s", message)
        else:
            journal.info("Fermeture : %s", message)
        self.messages.append(message)
        del self.messages[:-50]
        if alerte and self.registre is not None:
            try:
                self.registre.noter_alarme(MODULE, message, QUOI_FAIRE)
            except ErreurRegistre as erreur:
                journal.error("Fermeture : registre : %s", erreur)

    def _noter_mesure(self, code: str | None, cycle: int | None, force_n: float) -> None:
        if self.registre is None or code is None:
            return
        try:
            self.registre.noter_mesure(
                "fermeture_effort_clip", force_n, "N", capteur=MODULE, cycle=cycle, seau=code
            )
        except ErreurRegistre as erreur:
            journal.error("Fermeture : registre : %s", erreur)
