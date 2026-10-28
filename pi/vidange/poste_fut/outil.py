"""Outil « vidange-pesee » : lire et étalonner la pesée du chariot du fût.

  vidange-pesee lire                 poids lu chaque seconde (Ctrl+C pour finir)
  vidange-pesee zero                 étape 1 : zéro, rien de plus sur le berceau
  vidange-pesee etalonner 20         étape 2 : un poids connu (ici 20 kg) posé sur le berceau
  vidange-pesee tare                 étape 3 : le fût VIDE sur le berceau
  ... --faux                         pareil, avec le faux matériel (pour essayer l'outil)

Chaque étape affiche la ligne à recopier dans pi/reglages/machine.yaml (poste_fut → pesee).
L'outil n'écrit jamais lui-même dans les réglages. Procédure complète :
pi/systeme/essai-poste-fut.md.

À ne lancer que quand le programme principal est arrêté (les broches ne se prennent qu'une fois).
"""

import argparse
import sys
import time

from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.journal import configurer_journal
from vidange.materiel import FausseFabrique, Materiel
from vidange.poste_fut.pesee import SIGNAL, ErreurPesee, Pesee, filtrer, pente
from vidange.reglages import ErreurReglages, PeseeFut, charger_reglages

# Lectures pour une étape d'étalonnage : plus que pour une pesée ordinaire.
LECTURES_ETALONNAGE = 30


def mesure_brute(pesee: Pesee) -> int:
    """La mesure brute la plus sûre : médiane de nombreuses lectures, sans les aberrantes."""
    reglages = pesee.reglages
    valeurs: list[int] = []
    while len(valeurs) < LECTURES_ETALONNAGE:
        valeurs += pesee.lire_brut()
    ecart = reglages.ecart_aberrant_kg * abs(reglages.brut_par_kg)
    return round(filtrer([float(v) for v in valeurs], ecart, len(valeurs) // 2))


def main(arguments: list[str] | None = None, fabrique=None) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-pesee", description=__doc__.split("\n")[0])
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument(
        "--entrees-sorties", help="liste des entrées/sorties (défaut : docs/entrees-sorties.yaml)"
    )
    lecteur.add_argument("--faux", action="store_true", help="avec le faux matériel")
    commandes = lecteur.add_subparsers(dest="commande", required=True)
    lire = commandes.add_parser("lire", help="poids lu chaque seconde")
    lire.add_argument("--tours", type=int, help="nombre de lectures (défaut : sans fin)")
    commandes.add_parser("zero", help="étape 1 : zéro, rien de plus sur le berceau")
    etalonner = commandes.add_parser("etalonner", help="étape 2 : poids connu posé")
    etalonner.add_argument("kg", type=float, help="le poids connu, en kg (exemple : 20)")
    commandes.add_parser("tare", help="étape 3 : fût vide sur le berceau")
    options = lecteur.parse_args(arguments)
    configurer_journal()
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
    poste = reglages.machine.poste_fut
    if poste is None:
        print("machine.yaml n'a pas de partie « poste_fut »", file=sys.stderr)
        return 2
    if fabrique is None and options.faux:
        fabrique = FausseFabrique(liste)
    try:
        with Materiel(liste, fabrique, seulement=[SIGNAL]) as materiel:
            return _faire(options, Pesee(poste.pesee, materiel))
    except ErreurPesee as erreur:
        print(f"ÉCHEC : {erreur}", file=sys.stderr)
        return 1


def _faire(options: argparse.Namespace, pesee: Pesee) -> int:
    reglages: PeseeFut = pesee.reglages
    if options.commande == "lire":
        tours = options.tours
        try:
            while tours is None or tours > 0:
                try:
                    lu = pesee.peser()
                    print(f"poids lu {lu:8.2f} kg   substrat {pesee.net(lu):8.2f} kg")
                except ErreurPesee as erreur:
                    print(f"ÉCHEC : {erreur}")
                if tours is not None:
                    tours -= 1
                if tours != 0:
                    time.sleep(1)
        except KeyboardInterrupt:
            pass
        return 0
    if options.commande == "zero":
        brut = mesure_brute(pesee)
        print("Zéro mesuré. Recopier dans machine.yaml (poste_fut → pesee) :")
        print(f"    zero_brut: {brut}")
        return 0
    if options.commande == "etalonner":
        brut = mesure_brute(pesee)
        try:
            resultat = pente(reglages.zero_brut, brut, options.kg)
        except ValueError as erreur:
            print(f"ÉCHEC : {erreur}", file=sys.stderr)
            return 1
        print(f"Mesure brute avec {options.kg:g} kg : {brut} (zéro : {reglages.zero_brut}).")
        print("Recopier dans machine.yaml (poste_fut → pesee) :")
        print(f"    brut_par_kg: {resultat:.2f}")
        return 0
    # tare : berceau + fût vide, avec le zéro et la pente déjà recopiés.
    lu = pesee.kg(mesure_brute(pesee))
    print(f"Berceau + fût vide : {lu:.2f} kg. Recopier dans machine.yaml (poste_fut → pesee) :")
    print(f"    tare_kg: {lu:.2f}")
    return 0


def lancer() -> None:
    sys.exit(main())
