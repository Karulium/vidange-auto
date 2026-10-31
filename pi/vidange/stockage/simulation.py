"""Le Stockage sur la machine imaginaire du simulateur (scénario « stockage »).

    scenario = stockage_du_simulateur(simulateur)
    modules = [module_remplissage(..., scenario.remplissage.plan), module_mycelium(...)]

Les piles de seaux vides de simulateur.yaml (`stockage → piles`) sont chargées dans
l'inventaire ; les seaux (`stockage → seaux`, sans file) sont remplis par le vrai Remplissage
simulé, pris sur les piles dans l'ordre de vidage, rangés dans les files du tiroir que choisit
l'inventaire. La boucle du stockage est le faux capteur « boucle_stockage » (ses changements
sont des événements du scénario : tiroir tiré, puis remis).
"""

from dataclasses import dataclass

from vidange.remplissage.simulation import ScenarioRemplissage, remplissage_du_simulateur
from vidange.simulateur.simulateur import ErreurSimulation, Simulateur
from vidange.stockage.stockage import Stockage

BOUCLE = "boucle_stockage"


@dataclass
class ScenarioStockage:
    stockage: Stockage
    remplissage: ScenarioRemplissage


def stockage_du_simulateur(simulateur: Simulateur) -> ScenarioStockage:
    reglages = simulateur.reglages
    simule = reglages.simulateur.stockage
    if simule is None or reglages.machine.stockage is None:
        raise ErreurSimulation("simulateur.yaml ou machine.yaml n'a pas de partie « stockage »")
    materiel = simulateur.materiel
    stockage = Stockage(reglages.machine, boucle_fermee=lambda: materiel.lire(BOUCLE))
    for nom, pile in simule.piles.items():
        stockage.charger_pile(nom, pile.format, pile.nombre)
    remplissage = remplissage_du_simulateur(simulateur, seaux_simules=simule.seaux)
    remplissage.plan.magasin = stockage
    return ScenarioStockage(stockage, remplissage)
