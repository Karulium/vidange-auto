"""Le lavage sur la machine imaginaire du simulateur : la tête simulée de la préhension, une fausse
eau (faux flotteur) et le poste du fût du simulateur (panneau).

    lavage = lavage_du_simulateur(simulateur)
    module = module_lavage(lavage, simulateur.reglages.simulateur.lavage.seaux)
    couvercles = couvercles_du_simulateur(simulateur)      # faux retourneur, fausse caméra
    bocaux = bocaux_du_simulateur(simulateur)

La fausse eau (`FausseEauLavage`) monte quand l'eau du réseau ou le rinçage coulent, baisse quand
la pompe envoie vers la bonde (vanne à bille ouverte, vanne 3 voies au repos) ; le flotteur est
haut au-dessus de niveau_flotteur_l. Le vide du seau tenu vient de la tête simulée (ses pannes :
vidange.prehension.simulation).

Le faux retourneur (`FauxRetourneur`) bouge ses barres en barres_s ; sa barrière peut être
coupée (`coupee`). La fausse caméra (`FausseVisionCouvercles`) voit le repère du couvercle tenu
tourner avec la tête, et le couvercle se retourner à chaque chute. Pannes pour les essais :
`glissements` (le repère saute de 30° à ces lectures), `rates` (tant de chutes ne retournent
pas le couvercle), `hors_du_bac`, `place` (écarts du bac et de la tige ; None : pas trouvés).
"""

from collections.abc import Callable
from typing import Any

from vidange.lavage.bocaux import LavageBocaux
from vidange.lavage.couvercles import Face, LavageCouvercles, PhotoBac
from vidange.lavage.eau import EAU, FLOTTEUR, POMPE, RAMPES, RINCAGE, VIDANGE, EauLavage
from vidange.lavage.lavage import Lavage
from vidange.prehension.prehension import Prehension
from vidange.prehension.simulation import prehension_du_simulateur
from vidange.reglages import CouverclesLavage, LavageSimule
from vidange.simulateur.simulateur import ErreurSimulation, Simulateur


class FausseEauLavage:
    """Les signaux du lavage (mêmes noms que SignauxRepartis), sur une eau imaginaire (L)."""

    def __init__(self, reglages: LavageSimule, horloge: Callable[[], float]) -> None:
        self.reglages = reglages
        self._horloge = horloge
        self.litres = 0.0
        self._depuis = horloge()
        self.sorties: dict[str, bool] = {}
        # Ce qui a été commandé, dans l'ordre, pour les tests : « pompe_lavage oui »...
        self.historique: list[str] = []
        # Flotteur muet (carte pas lue) pour les essais.
        self.flotteur_muet = False

    def _avancer(self) -> None:
        maintenant = self._horloge()
        reglages, sorties = self.reglages, self.sorties
        debit = 0.0
        if sorties.get(EAU):
            debit += reglages.debit_eau_l_s
        if sorties.get(RINCAGE):
            debit += reglages.debit_rincage_l_s
        if sorties.get(POMPE) and sorties.get(VIDANGE) and not sorties.get(RAMPES):
            debit -= reglages.debit_pompe_l_s
        self.litres = max(0.0, self.litres + debit * (maintenant - self._depuis))
        self._depuis = maintenant

    def entree(self, nom: str) -> bool | None:
        self._avancer()
        if nom != FLOTTEUR or self.flotteur_muet:
            return None
        return self.litres >= self.reglages.niveau_flotteur_l

    def sortie(self, nom: str, actif: bool) -> None:
        self._avancer()
        if self.sorties.get(nom, False) != actif:
            self.historique.append(f"{nom} {'oui' if actif else 'non'}")
        self.sorties[nom] = actif


def lavage_du_simulateur(simulateur: Simulateur, **options: Any) -> Lavage:
    """Le lavage sur la machine imaginaire, mode « lavage », panneau lu sur le faux poste du fût.
    `options` : cases vides de Prehension (anse_levee, photo...)."""
    reglages = simulateur.reglages
    machine = reglages.machine
    simule = reglages.simulateur.lavage
    if simule is None or machine.lavage is None:
        raise ErreurSimulation("simulateur.yaml ou machine.yaml n'a pas de partie « lavage »")
    horloge = lambda: simulateur.temps  # noqa: E731
    prehension = prehension_du_simulateur(simulateur, **options)
    eau = EauLavage(machine.lavage, FausseEauLavage(simule, horloge), horloge)
    poste = simulateur.poste_fut()
    return Lavage(
        machine,
        prehension,
        eau,
        mode=lambda: "lavage",
        refus_panneau=lambda: poste.refus_lancement("lavage"),
        panneau_rabattu=poste.panneau_vu_rabattu,
        horloge=horloge,
    )


class FauxRetourneur:
    """Les barres et le chariot du Remplissage, pour le retourneur de couvercles."""

    def __init__(self, ecart_m: float, duree_s: float, horloge: Callable[[], float]) -> None:
        self._horloge = horloge
        self.duree_s = duree_s
        self.ecart_m = ecart_m
        self._fin = 0.0
        self.chariot = True
        self.coupee: bool | None = False
        # Ce qui a été commandé, pour les tests : écarts des barres.
        self.historique: list[float] = []

    def regler_barres(self, ecart_m: float) -> None:
        self.historique.append(ecart_m)
        self.ecart_m = ecart_m
        self._fin = self._horloge() + self.duree_s

    def ecart_barres(self) -> float | None:
        return self.ecart_m if self._horloge() >= self._fin else None

    def chariot_en_place(self) -> bool:
        return self.chariot

    def barriere_coupee(self) -> bool | None:
        return self.coupee


class FausseVisionCouvercles:
    """La caméra du plafond imaginaire : le repère du couvercle tenu tourne avec la tête."""

    def __init__(self, prehension: Prehension, reglages: CouverclesLavage) -> None:
        self.prehension = prehension
        self.reglages = reglages
        # Angle du repère quand la tête est à 0° (le couvercle a été pris n'importe comment).
        self.repere_a_zero = 200.0
        self.lectures = 0
        # Pannes.
        self.glissements: set[int] = set()
        self.rates = 0
        self.hors_du_bac = False
        self.place: tuple[float, float] | None = (0.001, 0.002)
        # Face du couvercle en haut (il est pris à l'endroit : le dessus, avec le repère).
        self.face_haut: Face = "dessus"
        self.centre_bac = reglages.retourneur.lacher

    def angle_repere(self) -> float | None:
        self.lectures += 1
        if self.lectures in self.glissements:
            self.repere_a_zero += 30
        pose = self.prehension.tete.position()
        return (self.repere_a_zero + self.reglages.sens_repere * pose.a) % 360

    def photo_bac(self) -> PhotoBac:
        if self.rates > 0:
            self.rates -= 1
        else:
            self.face_haut = "dessous" if self.face_haut == "dessus" else "dessus"
        if self.hors_du_bac:
            return PhotoBac(False, False, None, None)
        return PhotoBac(True, True, self.face_haut, self.centre_bac)

    def place_retourneur(self) -> tuple[float, float] | None:
        return self.place


def couvercles_du_simulateur(simulateur: Simulateur, **options: Any) -> LavageCouvercles:
    """Le lavage des couvercles sur la machine imaginaire : faux retourneur, fausse caméra ; la
    barrière coupée met le chef du simulateur en pause."""
    lavage = lavage_du_simulateur(simulateur, **options)
    couvercles = lavage.reglages.couvercles
    simule = simulateur.reglages.simulateur.lavage
    if couvercles is None or simule is None:
        raise ErreurSimulation("machine.yaml n'a pas de partie « lavage → couvercles »")
    retourneur = FauxRetourneur(
        couvercles.retourneur.barres_fermees_m, simule.barres_s, lambda: simulateur.temps
    )
    vision = FausseVisionCouvercles(lavage.prehension, couvercles)
    return LavageCouvercles(
        lavage, retourneur, vision, demander_pause=lambda message: simulateur.chef.pause()
    )


def bocaux_du_simulateur(simulateur: Simulateur, **options: Any) -> LavageBocaux:
    lavage = lavage_du_simulateur(simulateur, **options)
    if lavage.reglages.lave_bocal is None:
        raise ErreurSimulation("machine.yaml n'a pas de partie « lavage → lave_bocal »")
    return LavageBocaux(lavage)
