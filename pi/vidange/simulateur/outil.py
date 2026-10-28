"""Outil « vidange-simulateur » : rejoue un cycle sur la machine imaginaire et sort son planning.

  vidange-simulateur exemple                   planning du module d'exemple, et temps total
  vidange-simulateur exemple --delai-go 0      même chose si Karulium donne le Go tout de suite
  vidange-simulateur exemple --json p.json     planning aussi en JSON (page web, comparaisons...)
  vidange-simulateur poste_fut                 échange d'un fût (scénario « echange_fut »)

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
from vidange.poste_fut.module import module_echange_fut
from vidange.reglages import ErreurReglages, charger_reglages
from vidange.simulateur.simulateur import ErreurSimulation, Simulateur

# Modules qu'on sait simuler : nom → fabrique (simulateur → module).
# Chaque vrai module s'ajoutera ici quand ses gestes seront écrits.
MODULES: dict[str, Callable[[Simulateur], Module]] = {
    # Les modules attendent des Axes ; les axes imaginaires ont les mêmes noms.
    "exemple": lambda simulateur: module_exemple(simulateur.axes(), simulateur.materiel),
    "poste_fut": lambda simulateur: module_echange_fut(simulateur.poste_fut()),
}
# Scénario de simulateur.yaml joué par défaut avec un module (sinon : le haut du fichier).
SCENARIOS = {"poste_fut": "echange_fut"}


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-simulateur", description=__doc__.split("\n")[0])
    lecteur.add_argument("modules", nargs="+", choices=sorted(MODULES), help="modules à rejouer")
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
            planning = simulateur.jouer([MODULES[nom](simulateur) for nom in noms])
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
