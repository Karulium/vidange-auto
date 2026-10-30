"""Outil « vidange-simulateur » : rejoue un cycle sur la machine imaginaire et sort son planning.

  vidange-simulateur exemple                   planning du module d'exemple, et temps total
  vidange-simulateur exemple --delai-go 0      même chose si Karulium donne le Go tout de suite
  vidange-simulateur exemple --json p.json     planning aussi en JSON (page web, comparaisons...)
  vidange-simulateur poste_fut                 échange d'un fût (scénario « echange_fut »)
  vidange-simulateur griffe                    vidange d'un fût par la griffe (« vidange_fut »)
  vidange-simulateur mycelium                  dosage du mycélium (« dosage_mycelium »)
  vidange-simulateur prehension                gestes de la préhension (« prehension »)
  vidange-simulateur lavage                    3 seaux lavés, eau comprise (« lavage »)
  vidange-simulateur lavage_couvercles         2 couvercles lavés et retournés
  vidange-simulateur lavage_bocaux             3 bocaux et capsules au lave-bocal
  vidange-simulateur remplissage               2 seaux posés (prise double), remplis, dosés, rangés

Les durées se règlent dans reglages/simulateur.yaml (vitesses des axes, délai du Go, capteurs).
Tourne sur n'importe quel PC, sans la machine. Code de sortie 0 si le cycle va au bout, 1 sinon.
"""

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from vidange.chef import ErreurChef, Module
from vidange.chef.exemple import module_exemple
from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.griffe.module import module_griffe
from vidange.griffe.simulation import griffe_du_simulateur
from vidange.lavage.module import module_lavage, module_lavage_bocaux, module_lavage_couvercles
from vidange.lavage.simulation import (
    bocaux_du_simulateur,
    couvercles_du_simulateur,
    lavage_du_simulateur,
)
from vidange.mycelium.module import module_mycelium
from vidange.mycelium.simulation import mycelium_du_simulateur
from vidange.poste_fut.module import module_echange_fut
from vidange.prehension.module import module_prehension
from vidange.prehension.simulation import prehension_du_simulateur
from vidange.reglages import (
    ErreurReglages,
    LavageSimule,
    PrehensionSimulee,
    charger_reglages,
)
from vidange.remplissage.module import module_remplissage
from vidange.remplissage.simulation import remplissage_du_simulateur
from vidange.simulateur.simulateur import ErreurSimulation, Simulateur

# Modules qu'on sait simuler : nom → fabrique (simulateur → module).
# Chaque vrai module s'ajoutera ici quand ses gestes seront écrits.
MODULES: dict[str, Callable[[Simulateur], Module]] = {
    # Les modules attendent des Axes ; les axes imaginaires ont les mêmes noms.
    "exemple": lambda simulateur: module_exemple(simulateur.axes(), simulateur.materiel),
    "poste_fut": lambda simulateur: module_echange_fut(simulateur.poste_fut()),
    "griffe": lambda simulateur: module_griffe(griffe_du_simulateur(simulateur)),
    "mycelium": lambda simulateur: module_mycelium(mycelium_du_simulateur(simulateur)),
    "prehension": lambda simulateur: module_prehension(
        prehension_du_simulateur(simulateur), _places(simulateur)
    ),
    "lavage": lambda simulateur: module_lavage(
        lavage_du_simulateur(simulateur), _lavage(simulateur).seaux
    ),
    "lavage_couvercles": lambda simulateur: module_lavage_couvercles(
        couvercles_du_simulateur(simulateur), _lavage(simulateur).couvercles
    ),
    "lavage_bocaux": lambda simulateur: module_lavage_bocaux(
        bocaux_du_simulateur(simulateur), _lavage(simulateur).bocaux
    ),
}
# Modules simulés à plusieurs (le Remplissage avec le Mycélium, qui mène le chariot au dosage) :
# nom → fabrique (simulateur → modules).
GROUPES: dict[str, Callable[[Simulateur], list[Module]]] = {
    "remplissage": lambda simulateur: _remplissage(simulateur),
}
# Scénario de simulateur.yaml joué par défaut avec un module (sinon : le haut du fichier).
SCENARIOS = {
    "poste_fut": "echange_fut",
    "griffe": "vidange_fut",
    "mycelium": "dosage_mycelium",
    "prehension": "prehension",
    "lavage": "lavage",
    "lavage_couvercles": "lavage_couvercles",
    "lavage_bocaux": "lavage_bocaux",
    "remplissage": "remplissage",
}


def _remplissage(simulateur: Simulateur) -> list[Module]:
    scenario = remplissage_du_simulateur(simulateur)
    return [
        module_remplissage(
            scenario.remplissage, scenario.prehension, scenario.mycelium, scenario.plan
        ),
        module_mycelium(scenario.mycelium),
    ]


def _places(simulateur: Simulateur) -> PrehensionSimulee:
    places = simulateur.reglages.simulateur.prehension
    if places is None:
        raise ErreurSimulation("simulateur.yaml n'a pas de partie « prehension »")
    return places


def _lavage(simulateur: Simulateur) -> LavageSimule:
    lavage = simulateur.reglages.simulateur.lavage
    if lavage is None:
        raise ErreurSimulation("simulateur.yaml n'a pas de partie « lavage »")
    return lavage


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-simulateur", description=__doc__.split("\n")[0])
    lecteur.add_argument(
        "modules", nargs="+", choices=sorted({*MODULES, *GROUPES}), help="modules à rejouer"
    )
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument(
        "--entrees-sorties",
        help="liste des entrées/sorties (défaut : docs/entrees-sorties.yaml)",
    )
    lecteur.add_argument(
        "--delai-go", type=float, help="temps (s) avant le Go de Karulium (remplace le réglage)"
    )
    lecteur.add_argument("--json", help="écrit aussi le planning dans ce fichier JSON")
    lecteur.add_argument(
        "--scenario", help="scénario de simulateur.yaml (défaut : celui du module, s'il en a un)"
    )
    options = lecteur.parse_args(arguments)
    noms = list(dict.fromkeys(options.modules))
    scenario = options.scenario
    if scenario is None:
        scenarios = {SCENARIOS[nom] for nom in noms if nom in SCENARIOS}
        if len(scenarios) > 1:
            lecteur.error("ces modules ont chacun leur scénario : en choisir un (--scenario)")
        scenario = scenarios.pop() if scenarios else None
    dossier = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    chemin_liste = _chemin(
        options.entrees_sorties,
        "VIDANGE_ENTREES_SORTIES",
        DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml",
    )
    try:
        reglages = charger_reglages(dossier)
        liste = charger_entrees_sorties(chemin_liste)
    except ErreurReglages as erreur:
        print(erreur, file=sys.stderr)
        return 2
    if options.delai_go is not None:
        if options.delai_go < 0:
            lecteur.error("--delai-go : un temps positif ou nul")
        simulateur_reglages = reglages.simulateur.model_copy(
            update={"delai_go_s": options.delai_go}
        )
        reglages = reglages.model_copy(update={"simulateur": simulateur_reglages})
    try:
        with Simulateur(reglages, liste, scenario) as simulateur:
            modules: list[Module] = []
            for nom in noms:
                modules += (
                    GROUPES[nom](simulateur) if nom in GROUPES else [MODULES[nom](simulateur)]
                )
            planning = simulateur.jouer(modules)
    except (ErreurSimulation, ErreurChef) as erreur:
        print(f"Simulation impossible : {erreur}", file=sys.stderr)
        return 2
    print(planning.en_texte())
    if options.json:
        Path(options.json).write_text(
            json.dumps(planning.en_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return 0 if planning.fini else 1


def lancer() -> None:
    sys.exit(main())
