"""Outil « vidange-stockage » : les places du Stockage que le Pi calcule (sans la machine).

  vidange-stockage places                     toutes les places, pour le format par défaut
  vidange-stockage places seau_b              mêmes places, piles de fin de lot de ce format
  vidange-stockage piles seau_a               seaux par pile, bord du seau du haut pour chaque k

Sert à l'essai sur le vrai matériel (pi/systeme/essai-stockage.md) : mesurer au mètre les cotes
annoncées. Tout vient de pi/reglages/machine.yaml (partie « stockage »).
"""

import argparse
import sys

from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.reglages import ErreurReglages, Machine, charger_reglages
from vidange.stockage import places


def _cm(valeur: float) -> str:
    return f"{valeur:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def _places(machine: Machine, format: str) -> list[str]:
    assert machine.stockage is not None
    lignes = [f"Piles de seaux vides (fin de lot en « {format} »), dans l'ordre de vidage :"]
    points = places.places_piles(machine, format)
    for nom in places.ordre_piles(machine, points):
        x, y = points[nom]
        lignes.append(f"  {nom:8} x {_cm(x):7} y {_cm(y)}")
    x, y = machine.stockage.piles.couvercles
    lignes.append(f"  couvercles x {_cm(x)} y {_cm(y)}")
    lignes.append(f"Tiroir ({format}) :")
    for nom, nombre in places.places_tiroir(machine, format).items():
        assert machine.remplissage is not None
        y_file = machine.remplissage.rangement.files[nom].y
        lignes.append(f"  {nom} y {_cm(y_file)} : {nombre} seaux")
    lignes.append(f"  capacité du tiroir : {places.capacite_tiroir(machine, format)} seaux")
    centres = places.places_bande(machine, format)
    if centres:
        x = ", ".join(_cm(c) for c in centres)
        lignes.append(
            f"Bande du haut y {_cm(machine.stockage.bande_haut.y)} : {len(centres)} places "
            f"(centres x {x})"
        )
    else:
        lignes.append("Bande du haut : désactivée")
    lignes.append(f"Capacité d'un lot : {places.capacite_lot(machine, format)} seaux")
    lignes.append(
        f"Bocaux : {len(places.places_bocaux(machine))} places en quinconce "
        f"({len(places.places_saines(machine))} saines en mode inspection), "
        f"{len(places.places_semence(machine))} places de semence"
    )
    suspects, separation = places.coin_inspection(machine)
    lignes.append(f"  coin d'inspection : suspects {', '.join(suspects)}")
    lignes.append(f"  séparation : {', '.join(separation)}")
    for nom, (x, y) in machine.stockage.boites.places.items():
        lignes.append(
            f"Boîte « {nom} » x {_cm(x)} y {_cm(y)} : {places.capacite_boite(machine)} capsules"
        )
    return lignes


def _piles(machine: Machine, format: str) -> list[str]:
    n = places.seaux_par_pile(machine, format)
    lignes = [f"Pile de « {format} » : {n} seaux au plus. Bord du seau du haut :"]
    for k in range(1, n + 1):
        lignes.append(
            f"  {k} seau(x) : bord à {_cm(places.bord_pile(machine, format, k))} m, face de la "
            f"tête au contact à {_cm(places.contact_prise(machine, format, k))} m"
        )
    return lignes


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-stockage", description=__doc__.split("\n")[0])
    lecteur.add_argument("commande", choices=["places", "piles"])
    lecteur.add_argument("format", nargs="?", help="format de seau (défaut : format_par_defaut)")
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    options = lecteur.parse_args(arguments)
    dossier = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    try:
        machine = charger_reglages(dossier).machine
    except ErreurReglages as erreur:
        print(erreur, file=sys.stderr)
        return 2
    if machine.stockage is None or machine.griffe is None:
        print("machine.yaml n'a pas de partie « stockage »", file=sys.stderr)
        return 2
    format = options.format or machine.griffe.format_par_defaut
    if format not in machine.griffe.formats:
        connus = ", ".join(machine.griffe.formats)
        print(f"format inconnu « {format} » (formats : {connus})", file=sys.stderr)
        return 2
    lignes = _places(machine, format) if options.commande == "places" else _piles(machine, format)
    print("\n".join(lignes))
    return 0


def lancer() -> None:
    sys.exit(main())
