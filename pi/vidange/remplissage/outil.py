"""Outil « vidange-remplissage » : essayer le chariot de remplissage (carte n° 2, balance).

  vidange-remplissage etat                    position des 5 axes, barrière, alarme des barres,
                                              balance
  vidange-remplissage barriere                barrière et balance lues 20 fois (10 s)
  vidange-remplissage aller 0.5               rouler jusqu'à y
  vidange-remplissage plateau 0.45            plateau à cette hauteur (dessus, m)
  vidange-remplissage barres 0.2              barres à cet écartement hw (m)
  vidange-remplissage pousseur 0.325          pousseur à cette position (m ; 0 = rentré)
  vidange-remplissage tourner 90              plateau tourné de tant de degrés
  vidange-remplissage pose seau_a             chariot à la pose du seau vide de ce format
  vidange-remplissage centrer seau_a          barres au contact (en position), puis ouvertes
  vidange-remplissage vidage seau_a           ramener au vidage (plateau à la hauteur du format)
  vidange-remplissage ranger seau_a file_1    pousser le seau du plateau sur cette file
  vidange-remplissage ranger seau_a bande_haut   ... ou sur la bande du haut (plateau à 0,4985)
  vidange-remplissage fermer seau_a           fermer le seau du plateau (couvercle posé à la main) :
                                              bras de fermeture rangé, plateau à l'approche, bras au
                                              travail, montée en appui, rotation horaire, retour
                                              (tâche 41 ; le bras et la balance sont lus pour de
                                              vrai, --galet-range est inutile)
  vidange-remplissage couvercles              mode couvercles (retourneur)
  vidange-remplissage inspection              mode inspection des bocaux, un arrêt de 45°
  ... --faux                                  avec un faux FluidNC (essai de l'outil)

Les gestes sont ceux du programme, avec tous leurs verrous (vidange.remplissage.regles). Le
plateau du fût est lu (règle 7). L'agitateur du mycélium, le bras du galet et la tête du
micropore ne sont pas lus : --manivelle-en-bas, --galet-range et --micropore-rentre disent
qu'on les a vus (sinon le chariot ne roule pas près du poste, le plateau ne monte pas au-dessus
de 0,26, la préhension ne descend pas ; sans --micropore-rentre, le plateau ne monte ni ne
descend : règle 10, tâche 40). Procédure complète : pi/systeme/essai-remplissage.md. À ne
lancer que programme principal arrêté (une seule liaison par carte).
"""

import argparse
import sys
import threading
import time
from collections.abc import Callable
from contextlib import ExitStack

from vidange.chef import ErreurEtape
from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.fluidnc.ports import ErreurFluidnc
from vidange.griffe.bras import MM_PAR_M
from vidange.griffe.simulation import FausseForce
from vidange.journal import configurer_journal
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel
from vidange.pesees.tour import TourPesees
from vidange.poste_fut import PosteFut
from vidange.reglages import ErreurReglages, Machine, charger_reglages
from vidange.remplissage.chariot import ChariotFluidnc, signaux_chariot
from vidange.remplissage.regles import AXES
from vidange.remplissage.remplissage import Geste, Remplissage, SeauPlateau

CARTE = "chariot"
PESEE = "pesee_plateau_remplissage"
PANNEAU = "reed_panneau_poste_fut"
PLATEAU_FUT = "plateau_fut_en_place"
# Attente de la première réponse de la carte (s).
CONNEXION_S = 10
# Commande → nombre de valeurs attendues.
ATTENDUS = {
    "etat": 0,
    "barriere": 0,
    "aller": 1,
    "plateau": 1,
    "barres": 1,
    "pousseur": 1,
    "tourner": 1,
    "pose": 1,
    "centrer": 1,
    "vidage": 1,
    "ranger": 2,
    "fermer": 1,
    "couvercles": 0,
    "inspection": 0,
}


def _faux_ouvrir(machine: Machine) -> Callable[[], object]:
    """Un faux FluidNC : chariot au poste (position remplissage_poste)."""
    assert machine.remplissage is not None
    carte = FauxFluidnc(axes="XYZABC")
    for cle, nom in AXES.items():
        valeur = machine.positions["remplissage_poste"][nom]
        if cle == "barres":
            valeur -= machine.remplissage.barres.origine_hw_m
        if cle == "barre_allee":
            valeur -= machine.remplissage.barres.origine_allee_hw_m
        lettre = machine.axes[nom].lettre or "X"
        carte.positions[lettre] = valeur if cle == "a" else valeur * MM_PAR_M
    return carte.ouvrir


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(
        prog="vidange-remplissage", description=__doc__.split("\n")[0]
    )
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument(
        "--entrees-sorties", help="liste des entrées/sorties (défaut : docs/entrees-sorties.yaml)"
    )
    lecteur.add_argument("--faux", action="store_true", help="avec un faux FluidNC")
    lecteur.add_argument(
        "--manivelle-en-bas",
        action="store_true",
        help="manivelle du mycélium vue en bas, arrêtée",
    )
    lecteur.add_argument("--galet-range", action="store_true", help="bras du galet vu rangé")
    lecteur.add_argument(
        "--prehension-loin",
        action="store_true",
        help="je vois que la préhension est lâchée et remontée (« fermer » : l'outil n'a pas la "
        "préhension, sans cette option le bras reste rangé)",
    )
    lecteur.add_argument(
        "--micropore-rentre", action="store_true", help="tête du micropore vue rentrée"
    )
    lecteur.add_argument("commande", choices=list(ATTENDUS))
    lecteur.add_argument("valeurs", nargs="*", help="valeurs (voir plus haut)")
    options = lecteur.parse_args(arguments)
    configurer_journal()
    if len(options.valeurs) != ATTENDUS[options.commande]:
        lecteur.error(f"« {options.commande} » attend {ATTENDUS[options.commande]} valeur(s)")
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
    machine = reglages.machine
    if machine.remplissage is None or machine.poste_fut is None:
        print("machine.yaml n'a pas de partie « remplissage »", file=sys.stderr)
        return 2
    arret = threading.Event()
    with ExitStack() as pile:
        try:
            fabrique = FausseFabrique(liste) if options.faux else None
            if fabrique is not None and options.commande == "fermer" and reglages.pesees.i2c:
                i2c = reglages.pesees.i2c
                plages = [(v.angle_min_deg, v.angle_max_deg) for v in i2c.pca9685.voies.values()]
                fabrique.carte_pesee(i2c.carte).brancher_boitier(plages)
            seulement = {PANNEAU, PLATEAU_FUT, *reglages.pesees.tour}
            materiel = pile.enter_context(Materiel(liste, fabrique, seulement))
            liaison = Liaison(
                CARTE, reglages.fluidnc, ouvrir=_faux_ouvrir(machine) if options.faux else None
            )
            liaison = pile.enter_context(liaison)
            liaison.attendre_connexion(CONNEXION_S)
            if options.faux:
                balance = FausseForce(0.0)
            else:
                pesees = TourPesees(reglages.pesees, materiel)
                pesees.demarrer(arret)
                balance = pesees.capteur(PESEE)  # type: ignore[assignment]
            carte = reglages.fluidnc.cartes[CARTE]
            chariot = ChariotFluidnc(machine, liaison, balance, signaux_chariot(liaison, carte))
            chariot.demarrer(arret)
            time.sleep(0.5)
            poste = PosteFut(machine.poste_fut, materiel, lecture_directe=True)
            en_bas = options.manivelle_en_bas
            if options.commande == "fermer" and (
                machine.fermeture is None or reglages.pesees.i2c is None
            ):
                print("machine.yaml n'a pas de partie « fermeture »", file=sys.stderr)
                return 2
            remplissage = Remplissage(
                machine,
                chariot,
                plateau_fut_en_place=lambda: not poste.echange_en_cours,
                refus_mycelium=lambda: None if en_bas else "manivelle du mycélium pas vue en bas",
                bras_galet_range=lambda: True if options.galet_range else None,
                micropore_rentre=lambda: True if options.micropore_rentre else None,
            )
            remplissage.prehension_loin_a_la_main = options.prehension_loin
            if options.commande == "fermer":
                options.fermeture = _brancher_fermeture(reglages, materiel, remplissage, arret)
            return _faire(options, remplissage, chariot)
        except (ErreurEtape, ErreurFluidnc, ErreurMateriel) as erreur:
            print(f"ÉCHEC : {erreur}", file=sys.stderr)
            quoi_faire = getattr(erreur, "quoi_faire", "")
            if quoi_faire:
                print(f"Quoi faire : {quoi_faire}", file=sys.stderr)
            return 1
        finally:
            arret.set()


def _brancher_fermeture(reglages, materiel, remplissage, arret):
    """« fermer » : le vrai bras de la fermeture (ou un faux boîtier avec --faux), lu et renvoyé en
    fond pendant le geste (la carte veut un ordre toutes les 2 s)."""
    from vidange.fermeture import BrasFermeture, Fermeture
    from vidange.fiabilite.constats import lancer_boucle

    assert reglages.machine.fermeture is not None and reglages.pesees.i2c is not None
    bras = BrasFermeture(reglages.machine.fermeture, reglages.pesees.i2c, materiel)
    fermeture = Fermeture(reglages.machine, bras)
    fermeture.brancher(remplissage)
    lancer_boucle("bras_fermeture", 0.2, bras.observer, arret)
    return fermeture


def _jouer(remplissage: Remplissage, geste: Callable[[], Geste]) -> None:
    delai = remplissage.durees["remplissage_geste_max"]
    remplissage.lancer(geste)
    fin = time.monotonic() + delai
    try:
        while not remplissage.geste_fini():
            remplissage.chariot.surveillance.test()
            if time.monotonic() > fin:
                raise ErreurEtape(f"geste pas fini en {delai:g} s")
            time.sleep(0.02)
    except ErreurEtape:
        remplissage.arreter()
        raise


def _etat(remplissage: Remplissage, chariot: ChariotFluidnc) -> None:
    pose = chariot.position()
    print(f"chariot : y {pose.y:.4f} m ; plateau : dessus à {pose.z:.4f} m, {pose.a:.1f}°")
    print(
        f"barres : hw {pose.barres:.4f} m côté mur, {pose.barre_allee:.4f} m côté allée ; "
        f"pousseur : {pose.pousseur:.4f} m"
    )
    print(f"barrière coupée : {chariot.barriere_coupee()}")
    alarmes = chariot.alarmes_barres()
    print(f"alarme des pilotes des barres : {', '.join(alarmes) if alarmes else 'aucune'}")
    try:
        print(f"balance : {chariot.peser():.3f} kg")
    except ErreurEtape as erreur:
        print(f"balance : {erreur}")
    refus = remplissage.regles.refus_pose(pose, remplissage.contexte())
    print(f"pose permise : {'oui' if refus is None else f'non, {refus}'}")


def _faire(options: argparse.Namespace, remplissage: Remplissage, chariot: ChariotFluidnc) -> int:
    commande, valeurs = options.commande, options.valeurs
    if commande == "etat":
        _etat(remplissage, chariot)
        return 0
    if commande == "barriere":
        for _ in range(20):
            time.sleep(0.5)
            try:
                poids = f"{chariot.peser():.3f} kg"
            except ErreurEtape:
                poids = "pas de lecture"
            print(f"barrière coupée : {chariot.barriere_coupee()} ; balance : {poids}")
        return 0
    nombre: float | None = None
    if commande in ("aller", "plateau", "barres", "pousseur", "tourner"):
        try:
            nombre = float(valeurs[0])
        except ValueError:
            print("Les cotes s'écrivent en mètres (degrés), avec un point : 0.45", file=sys.stderr)
            return 2
    r = remplissage
    gestes: dict[str, Callable[[], Geste]] = {
        "aller": lambda: r.geste_aller(nombre),  # type: ignore[arg-type]
        "plateau": lambda: r.geste_plateau(nombre),  # type: ignore[arg-type]
        "barres": lambda: r.geste_barres(nombre),  # type: ignore[arg-type]
        "pousseur": lambda: r.geste_pousseur(nombre),  # type: ignore[arg-type]
        "tourner": lambda: r.geste_tourner_de(nombre),  # type: ignore[arg-type]
        "couvercles": r.geste_mode_couvercles,
        "inspection": r.geste_mode_inspection,
    }
    if commande == "fermer":
        format = valeurs[0]
        if format not in r.reglages.formats:
            print(f"Format inconnu : {format}", file=sys.stderr)
            return 2
        # Le seau plein est là, son couvercle posé à la main.
        r.seau = SeauPlateau(format, angle_anse=chariot.position().a)
        # Comme au démarrage du programme : zéro de la montée (plateau en bas), bras rangé (premier
        # ordre sans rampe), puis seulement le reste.
        _jouer(remplissage, lambda: r.geste_plateau(r.course_z[0]))
        _jouer(remplissage, r.geste_ranger_bras)
        _jouer(remplissage, r.geste_fermer)
        for message in options.fermeture.messages:
            print(message)
        _etat(remplissage, chariot)
        return 0
    if commande in ("pose", "centrer", "vidage", "ranger"):
        format = valeurs[0]
        if format not in r.reglages.formats:
            print(f"Format inconnu : {format}", file=sys.stderr)
            return 2
        if commande != "pose":
            # Le seau est là (posé à la main), son anse déjà à l'angle voulu.
            r.seau = SeauPlateau(format, angle_anse=chariot.position().a)
        gestes.update(
            pose=lambda: r.geste_aller_a_la_pose(format),
            centrer=r.geste_centrer,
            vidage=r.geste_ramener_au_vidage,
            ranger=lambda: (
                r.geste_ranger_en_haut()
                if valeurs[1] == "bande_haut"
                else r.geste_ranger(valeurs[1])
            ),
        )
    _jouer(remplissage, gestes[commande])
    if commande == "inspection":
        _jouer(remplissage, remplissage.geste_tourner_inspection)
    _etat(remplissage, chariot)
    return 0


def lancer() -> None:
    sys.exit(main())
