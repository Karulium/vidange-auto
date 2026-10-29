"""Le lavage sur la machine imaginaire du simulateur : la tête simulée de la préhension, une fausse
eau (faux flotteur) et le poste du fût du simulateur (panneau).

    lavage = lavage_du_simulateur(simulateur)
    module = module_lavage(lavage, simulateur.reglages.simulateur.lavage.seaux)

La fausse eau (`FausseEauLavage`) monte quand l'eau du réseau ou le rinçage coulent, baisse quand
la pompe envoie vers la bonde (vanne à bille ouverte, vanne 3 voies au repos) ; le flotteur est
haut au-dessus de niveau_flotteur_l. Le vide du seau tenu vient de la tête simulée (ses pannes :
vidange.prehension.simulation).
"""

from collections.abc import Callable
from typing import Any

from vidange.lavage.eau import EAU, FLOTTEUR, POMPE, RAMPES, RINCAGE, VIDANGE, EauLavage
from vidange.lavage.lavage import Lavage
from vidange.prehension.simulation import prehension_du_simulateur
from vidange.reglages import LavageSimule
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
