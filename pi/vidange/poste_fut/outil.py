"""Outil « vidange-pesee » : lire et étalonner la pesée sans fil du plateau du fût.

  vidange-pesee lire                 poids, accu et radio chaque seconde (Ctrl+C pour finir)
  vidange-pesee zero                 étape 1 : zéro, plateau vide au poste
  vidange-pesee etalonner 20         étape 2 : un poids connu (ici 20 kg) au centre du plateau
  vidange-pesee tare                 étape 3 : un fût VIDE (avec son couvercle) sur le plateau
  ... --faux                         pareil, avec le faux matériel (pour essayer l'outil)

La pesée passe par la boîte du poste, sur le bus des pesées (pesee_fut) : le plateau doit être
au poste (son reed le réveille). Les étapes 1 et 2 affichent les lignes à recopier dans
pi/reglages/pesees.yaml (etalonnage → pesee_fut) ; l'étape 3, celle à recopier dans
pi/reglages/machine.yaml (poste_fut → pesee). L'outil n'écrit jamais lui-même dans les
réglages. Procédure complète : pi/systeme/essai-poste-fut.md.

À ne lancer que quand le programme principal est arrêté (l'adaptateur ne s'ouvre qu'une fois).
"""

import argparse
import sys
import time
from statistics import median

from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.journal import configurer_journal
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel
from vidange.pesees.outil import DUREE_ETALONNAGE_S, _etalonner, _pendant
from vidange.pesees.tour import TourPesees
from vidange.poste_fut.pesee import SIGNAL, PeseePlateau
from vidange.reglages import ErreurReglages, charger_reglages


def main(arguments: list[str] | None = None, fabrique=None) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-pesee", description=__doc__.split("\n")[0])
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument(
        "--entrees-sorties", help="liste des entrées/sorties (défaut : docs/entrees-sorties.yaml)"
    )
    lecteur.add_argument("--faux", action="store_true", help="avec le faux matériel")
    commandes = lecteur.add_subparsers(dest="commande", required=True)
    lire = commandes.add_parser("lire", help="poids, accu et radio chaque seconde")
    lire.add_argument("--tours", type=int, help="nombre de lignes (défaut : sans fin)")
    commandes.add_parser("zero", help="étape 1 : zéro, plateau vide au poste")
    etalonner = commandes.add_parser("etalonner", help="étape 2 : poids connu au centre")
    etalonner.add_argument("kg", type=float, help="le poids connu, en kg (exemple : 20)")
    commandes.add_parser("tare", help="étape 3 : fût vide (avec son couvercle) sur le plateau")
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
    if SIGNAL not in reglages.pesees.etalonnage:
        print(f"pesees.yaml : « {SIGNAL} » n'est pas dans etalonnage ni dans tour", file=sys.stderr)
        return 2
    if fabrique is None and options.faux:
        fabrique = FausseFabrique(liste)
    with Materiel(liste, fabrique, seulement=[SIGNAL]) as materiel:
        tour = TourPesees(reglages.pesees, materiel)
        pesee = PeseePlateau(poste.pesee, tour)
        if options.commande == "lire":
            return _lire(pesee, options.tours)
        if options.commande in ("zero", "etalonner"):
            return _etalonner(tour, SIGNAL, options.commande, getattr(options, "kg", 0.0))
        return _tare(pesee)


def _ligne(pesee: PeseePlateau) -> str:
    lecture = pesee.lire()
    if lecture.poids_lu_kg is None:
        poids = f"ÉCHEC : {lecture.probleme}"
    else:
        lu = lecture.poids_lu_kg
        poids = f"poids lu {lu:8.2f} kg   substrat {pesee.net(lu):8.2f} kg"
    plateau = lecture.plateau
    if plateau is None:
        return poids
    recharge = "en recharge" if plateau.en_recharge else "PAS EN RECHARGE"
    return (
        f"{poids}   accu {plateau.accu_mv / 1000:.2f} V {plateau.accu_pct:3d} % {recharge}"
        + ("  (USB-C)" if plateau.sur_usb else "")
        + f"   radio {plateau.signal_dbm} dBm, {plateau.trames_perdues} trames perdues"
    )


def _lire(pesee: PeseePlateau, tours: int | None) -> int:
    try:
        while tours is None or tours > 0:
            pesee.tour.interroger(pesee.signal)
            print(_ligne(pesee))
            if tours is not None:
                tours -= 1
            if tours != 0:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    return 0


def _tare(pesee: PeseePlateau) -> int:
    """Fût vide sur le plateau, avec le zéro et la pente déjà recopiés : la médiane des poids
    lus pendant DUREE_ETALONNAGE_S (sans les bornes plausibles : c'est ce qu'on mesure)."""
    valeurs = []
    tour = pesee.tour
    fin = time.monotonic() + DUREE_ETALONNAGE_S
    while time.monotonic() < fin:
        _pendant(tour, 0.25)
        try:
            valeurs.append(pesee.capteur.lire_kg())
        except ErreurMateriel:
            pass
    if not valeurs:
        print(f"ÉCHEC : aucun poids lu ({pesee.lire().probleme})", file=sys.stderr)
        return 1
    lu = median(valeurs)
    print(f"Fût vide et son couvercle : {lu:.2f} kg.")
    print("Recopier dans machine.yaml (poste_fut → pesee) :")
    print(f"    tare_kg: {lu:.2f}")
    return 0


def lancer() -> None:
    sys.exit(main())
