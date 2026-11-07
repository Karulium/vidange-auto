"""Outil « vidange-fermeture » : essayer le servo du bras de fermeture des seaux et l'étalonner.

  vidange-fermeture etat                    angles du servo, bras rangé ou non, réglages
  vidange-fermeture servo 190 --plateau-bas       servo à cet angle de son AXE (°), tout de suite
                                                  (pour l'étalonnage : avancer pas à pas jusqu'au
                                                  contact du doigt sur le plat des paliers)
  vidange-fermeture ranger --plateau-bas    bras rangé (rampe ; sans rampe si c'est le 1er ordre)
  vidange-fermeture travail --plateau-bas   bras au travail (rampe)
  ... --faux                                pareil, avec le faux matériel (pour essayer)

Le plateau, lui, se règle avec vidange-remplissage (dont « fermer <format> » joue le geste entier).
Le bras tourne À VIDE et seulement plateau assez bas : l'outil ne voit pas le plateau, vous lui
dites que vous l'avez vu en bas, après le zéro de la montée, avec --plateau-bas (sinon il refuse).
Le signal du servo n'est jamais coupé à la fin : le bras reste où il est.

Procédure : systeme/essai-fermeture.md. À ne lancer que quand le programme principal est arrêté
(l'adaptateur ne s'ouvre qu'une fois).
"""

import argparse
import math
import sys
import time
from collections.abc import Callable

from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fermeture.bras import BrasFermeture
from vidange.journal import configurer_journal
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel
from vidange.reglages import ErreurReglages, Reglages, charger_reglages


def main(
    arguments: list[str] | None = None,
    fabrique=None,
    attendre: Callable[[float], None] = time.sleep,
    horloge: Callable[[], float] = time.monotonic,
) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-fermeture", description=__doc__.split("\n")[0])
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument(
        "--entrees-sorties", help="liste des entrées/sorties (défaut : docs/entrees-sorties.yaml)"
    )
    lecteur.add_argument("--faux", action="store_true", help="avec le faux matériel")
    lecteur.add_argument(
        "--plateau-bas",
        action="store_true",
        help="j'ai vu le plateau en bas (zéro de la montée fait) : le bras peut tourner",
    )
    commandes = lecteur.add_subparsers(dest="commande", required=True)
    commandes.add_parser("etat", help="angles du servo, bras rangé ou non")
    servo = commandes.add_parser("servo", help="servo à cet angle de son axe (°)")
    servo.add_argument("angle", type=float, help="angle de l'axe du servo (°)")
    commandes.add_parser("ranger", help="bras rangé")
    commandes.add_parser("travail", help="bras au travail")
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
    fermeture, i2c = reglages.machine.fermeture, reglages.pesees.i2c
    if fermeture is None or i2c is None:
        print(
            "machine.yaml n'a pas de « fermeture » (ou pesees.yaml pas d'« i2c »)", file=sys.stderr
        )
        return 2
    if options.commande != "etat" and not options.plateau_bas:
        print(
            "Le bras ne tourne que plateau assez bas : faire le zéro de la montée, regarder le "
            "plateau en bas, puis relancer avec --plateau-bas.",
            file=sys.stderr,
        )
        return 2
    if fabrique is None and options.faux:
        fabrique = FausseFabrique(liste)
        plages = [(voie.angle_min_deg, voie.angle_max_deg) for voie in i2c.pca9685.voies.values()]
        fabrique.carte_pesee(i2c.carte).brancher_boitier(plages)
    with Materiel(liste, fabrique, seulement=[i2c.carte]) as materiel:
        bras = BrasFermeture(fermeture, i2c, materiel, horloge)
        try:
            if options.commande == "etat":
                return _etat(bras, reglages)
            if options.commande == "servo":
                return _servo(bras, options.angle, attendre)
            return _aller(bras, options.commande == "travail", attendre)
        except ErreurMateriel as erreur:
            print(f"ÉCHEC : {erreur}", file=sys.stderr)
            return 1


def _etat(bras: BrasFermeture, reglages: Reglages) -> int:
    etat = bras.lire()
    angle = etat.angles_deg[bras.voie]
    lu = (
        "coupé (jamais ordonné depuis le démarrage de la carte)" if angle is None else f"{angle:g}°"
    )
    print(f"Servo : {lu}  démarrages {etat.demarrages}")
    fermeture = reglages.machine.fermeture
    assert fermeture is not None
    print(
        f"Réglages : butée {fermeture.bras.butee_servo_deg:g}°, rangé {bras.angle_range():g}°, "
        f"travail {bras.angle_travail():g}° (angles de l'axe du servo)"
    )
    return 0


def _servo(bras: BrasFermeture, angle: float, attendre: Callable[[float], None]) -> int:
    bras.commander(angle)
    attendre(bras.reglages.bras.attente_s)
    bras.lire()
    print(f"Servo à {angle:g}° (angle de l'axe). Le signal reste envoyé.")
    return 0


def _aller(bras: BrasFermeture, travail: bool, attendre: Callable[[float], None]) -> int:
    cible = bras.angle_travail() if travail else bras.angle_range()
    rampe = bras.reglages.bras.rampe
    # Le Pi ne connaît pas l'angle de départ de ce programme : on le lit sur la carte.
    depart = bras.lire().angles_deg[bras.voie]
    if depart is None:
        angles = [cible]
        print("Premier ordre depuis le démarrage de la carte : sans rampe.")
    else:
        n = max(1, math.ceil(abs(cible - depart) / (rampe.degres / rampe.duree_s * rampe.pas_s)))
        angles = [depart + (cible - depart) * i / n for i in range(1, n + 1)]
    for angle in angles:
        bras.commander(angle)
        attendre(rampe.pas_s)
    attendre(bras.reglages.bras.attente_s)
    print(
        f"Bras {'au travail' if travail else 'rangé'} (servo à {cible:g}°). Le signal reste envoyé."
    )
    return 0


def lancer() -> None:
    sys.exit(main())
