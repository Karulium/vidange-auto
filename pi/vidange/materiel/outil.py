"""Outil « vidange-es » pour les essais des entrées/sorties sur le vrai matériel (et sur le faux).

  vidange-es lister                  chaque signal lu par le Pi, avec sa valeur du moment
  vidange-es lister sht31_armoire    seulement ces signaux (une carte à la fois)
  vidange-es surveiller [NOMS...]    affiche chaque entrée qui change (Ctrl+C pour finir)
  vidange-es commander voyant_buzzer oui    (ou non) : commande une sortie
  vidange-es consigne consigne_ventilateur 5    règle la consigne 0-10 V (en volts)
  ... --faux                         pareil, avec le faux matériel

À ne lancer que quand le programme principal est arrêté (les broches ne se prennent qu'une fois).
En sortant, toutes les sorties reviennent au repos.
"""

import argparse
import sys
import time

from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.journal import configurer_journal
from vidange.materiel.faux import FausseFabrique
from vidange.materiel.materiel import Materiel, tracer_branchements
from vidange.materiel.ozone import texte_ppm
from vidange.materiel.puces import ErreurMateriel
from vidange.reglages import ErreurReglages


def valeur(materiel: Materiel, nom: str) -> str:
    sorte = materiel.branchements[nom].sorte
    try:
        if sorte == "entree":
            return "ACTIONNÉ" if materiel.lire(nom) else "repos"
        if sorte == "sortie":
            return "COMMANDÉE" if materiel.lire(nom) else "repos"
        if sorte == "pesee":
            return f"{materiel.peser(nom)} (mesure brute, voir vidange-pesees)"
        if sorte == "ozone":
            reglage = materiel.liste.signaux[nom].ozone
            mesure = materiel.lire_ozone(nom)
            texte = texte_ppm(mesure, reglage.plafond_ppm)
            return f"{texte} ({mesure.trames_ignorees} trames ignorées)"
        if sorte == "spray":
            etat = materiel.lire_spray(nom)
            return (
                f"carte du spray, {etat.demarrages} démarrages, bras à {etat.angle_deg:g}° "
                f"({'rangé' if etat.bras_range else 'PAS RANGÉ'}) (voir vidange-spray)"
            )
        if sorte == "consigne":
            return "consigne 0-10 V (se règle avec « vidange-es consigne NOM VOLTS »)"
        if sorte == "ambiance":
            ambiance = materiel.ambiance(nom)
            return f"{ambiance.temperature_c:.1f} °C, {ambiance.humidite_pct:.0f} %"
        return f"{materiel.mesurer(nom):.4g} {materiel.unite(nom)}".strip()
    except ErreurMateriel as erreur:
        return f"ÉCHEC : {erreur}"


def lister(materiel: Materiel) -> int:
    for nom, branchement in materiel.branchements.items():
        print(f"{nom} ({branchement.sorte}) : {valeur(materiel, nom)}")
    ignores = [
        nom for nom in materiel.liste.signaux if nom not in tracer_branchements(materiel.liste)
    ]
    if ignores:
        print(f"Pas lus par le Pi lui-même : {', '.join(ignores)}")
    return 0


def surveiller(materiel: Materiel, periode_s: float, tours: int | None = None) -> int:
    print("Actionner les capteurs un par un ; Ctrl+C pour finir.")
    avant: dict[str, str] = {}
    try:
        while tours is None or tours > 0:
            for nom, branchement in materiel.branchements.items():
                if branchement.sorte != "entree":
                    continue
                maintenant = valeur(materiel, nom)
                if avant.get(nom) != maintenant:
                    print(f"{time.strftime('%H:%M:%S')}  {nom} : {maintenant}")
                    avant[nom] = maintenant
            if tours is not None:
                tours -= 1
            time.sleep(periode_s)
    except KeyboardInterrupt:
        pass
    return 0


def commander(materiel: Materiel, nom: str, commande: bool) -> int:
    try:
        materiel.ecrire(nom, commande)
    except ErreurMateriel as erreur:
        print(f"ÉCHEC : {erreur}")
        return 1
    print(f"{nom} : {'COMMANDÉE' if commande else 'repos'}")
    if commande and sys.stdin.isatty():
        input("Entrée pour remettre au repos et finir... ")
    return 0


def regler_consigne(materiel: Materiel, nom: str, volts: float) -> int:
    try:
        materiel.regler_consigne(nom, volts)
    except ErreurMateriel as erreur:
        print(f"ÉCHEC : {erreur}")
        return 1
    print(f"{nom} : {volts:g} V")
    if volts > 0 and sys.stdin.isatty():
        input("Entrée pour remettre à 0 V et finir... ")
    return 0


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(
        prog="vidange-es", description="Essais des entrées/sorties du Pi."
    )
    lecteur.add_argument(
        "--entrees-sorties", help="liste des entrées/sorties (défaut : docs/entrees-sorties.yaml)"
    )
    lecteur.add_argument("--faux", action="store_true", help="avec le faux matériel")
    sous = lecteur.add_subparsers(dest="action", required=True)
    parties = sous.add_parser("lister", help="chaque signal et sa valeur")
    parties.add_argument("noms", nargs="*", help="seulement ces signaux")
    parties = sous.add_parser("surveiller", help="affiche les entrées qui changent")
    parties.add_argument("noms", nargs="*", help="seulement ces signaux")
    parties.add_argument("--periode", type=float, default=0.1, help="en s (défaut : 0.1)")
    parties = sous.add_parser("commander", help="commande une sortie")
    parties.add_argument("signal", help="nom de la sortie (exemple : voyant_buzzer)")
    parties.add_argument("etat", choices=["oui", "non"])
    parties = sous.add_parser("consigne", help="règle une consigne 0-10 V (PWM)")
    parties.add_argument("signal", help="nom de la consigne (exemple : consigne_ventilateur)")
    parties.add_argument("volts", type=float)
    options = lecteur.parse_args(arguments)

    configurer_journal()
    chemin = _chemin(
        options.entrees_sorties,
        "VIDANGE_ENTREES_SORTIES",
        DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml",
    )
    try:
        liste = charger_entrees_sorties(chemin)
        fabrique = FausseFabrique(liste) if options.faux else None
        if options.action in ("commander", "consigne"):
            seulement = [options.signal]
        else:
            seulement = options.noms or None
        materiel = Materiel(liste, fabrique, seulement)
    except (ErreurReglages, ErreurMateriel) as erreur:
        print(erreur)
        return 2
    with materiel:
        if options.action == "lister":
            return lister(materiel)
        if options.action == "surveiller":
            return surveiller(materiel, options.periode)
        if options.action == "consigne":
            return regler_consigne(materiel, options.signal, options.volts)
        return commander(materiel, options.signal, options.etat == "oui")


def lancer() -> None:
    """Point d'entrée de la commande « vidange-es »."""
    sys.exit(main())
