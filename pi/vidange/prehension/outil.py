"""Outil « vidange-prehension » : essayer la tête de préhension (cartes n° 1 et n° 4).

  vidange-prehension etat                     position, contact, vide, force
  vidange-prehension vide                     vanne ouverte 5 s : le vide lu (ventouse sur vitre)
  vidange-prehension prendre-poser seau 1.6 0.6 0.6  1.9 0.6 0.6 --format seau_a
                                              prendre un objet (x y contact_z), le poser ailleurs
  vidange-prehension porte-bocal 1.4 0.75 0.95 --manivelle-en-bas
                                              bocal pris là, posé au porte-bocal, repris, reposé
  vidange-prehension visser 1.5 0.5 0.85  1.7 0.5 0.9
                                              capsule prise là, vissée sur le bocal d'ici
  ... --faux                                  avec de faux FluidNC (essai de l'outil : etat)

Les gestes sont ceux du programme, avec tous leurs verrous (vidange.prehension). Les cotes sont
en mètres, dans le repère du portique : x, y = axe de la tête ; contact_z = face de la tête quand
elle touche l'objet. Le panneau du poste du fût est lu (isolation du fût), la hauteur de la
griffe aussi (en butée haute pour le porte-bocal). L'agitateur n'est pas lu : --manivelle-en-bas
dit qu'on a vu l'agitateur au garage, manivelle en bas (sinon la tête ne va pas au porte-bocal et
ne passe pas au-dessus de la glissière de l'agitateur : sa position est inconnue).
Procédure complète :
pi/systeme/essai-prehension.md. À ne lancer que programme principal arrêté (une seule liaison
par carte).
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
from vidange.griffe.regles import ReglesGriffe
from vidange.griffe.simulation import FausseForce
from vidange.journal import configurer_journal
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel
from vidange.pesees.tour import TourPesees
from vidange.porte_bocal.porte_bocal import PorteBocalFluidnc, signaux_porte_bocal
from vidange.poste_fut import PosteFut
from vidange.prehension.prehension import Geste, Prehension
from vidange.prehension.tete import (
    CONTACT,
    CapteurVide,
    ErreurVide,
    TeteFluidnc,
    signaux_prehension,
)
from vidange.reglages import ErreurReglages, Reglages, charger_reglages

PONT = "portique"
TETE = "prehension"
PORTE_BOCAL = "mycelium_lavage"
VIDE = "vide_venturi"
PESEE = "pesee_prehension"
PANNEAU = "reed_panneau_poste_fut"
CHARIOT = "chariot_fut_en_place"
# Attente de la première réponse des cartes (s).
CONNEXION_S = 10


def _faux_ouvrir(reglages: Reglages, lettre_z: str) -> dict[str, Callable[[], object]]:
    """De faux FluidNC : pont à x 1,471 (axe de la tête 1,6), tête en haut."""
    portique = FauxFluidnc(axes="XYZAB")
    portique.positions.update(X=1471.0, Y=600.0)
    tete = FauxFluidnc(axes="XYZA")
    tete.positions[lettre_z] = reglages.machine.prehension.haut_z * 1000  # type: ignore[union-attr]
    return {PONT: portique.ouvrir, TETE: tete.ouvrir}


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-prehension", description=__doc__.split("\n")[0])
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument(
        "--entrees-sorties", help="liste des entrées/sorties (défaut : docs/entrees-sorties.yaml)"
    )
    lecteur.add_argument("--faux", action="store_true", help="avec de faux FluidNC")
    lecteur.add_argument("--format", help="format du seau (machine.yaml → griffe → formats)")
    lecteur.add_argument(
        "--manivelle-en-bas",
        action="store_true",
        help="agitateur vu au garage, manivelle en bas (porte-bocal)",
    )
    lecteur.add_argument(
        "commande", choices=["etat", "vide", "prendre-poser", "porte-bocal", "visser"]
    )
    lecteur.add_argument("valeurs", nargs="*", help="objet et cotes (voir plus haut)")
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
    machine = reglages.machine
    if machine.prehension is None or machine.poste_fut is None:
        print("machine.yaml n'a pas de partie « prehension »", file=sys.stderr)
        return 2
    attendus = {"etat": 0, "vide": 0, "prendre-poser": 7, "porte-bocal": 3, "visser": 6}
    if len(options.valeurs) != attendus[options.commande]:
        lecteur.error(f"« {options.commande} » attend {attendus[options.commande]} valeurs")
    arret = threading.Event()
    with ExitStack() as pile:
        try:
            fabrique = FausseFabrique(liste) if options.faux else None
            # Seulement ce dont la tête a besoin : vide, pesées, panneau et chariot du poste du fût.
            seulement = {VIDE, PANNEAU, CHARIOT, *reglages.pesees.tour}
            materiel = pile.enter_context(Materiel(liste, fabrique, seulement))
            if fabrique is not None:
                fabrique.regler(VIDE, 0.0)
            ouvrir = _faux_ouvrir(reglages, machine.axes["prehension_z"].lettre or "Z")
            liaisons = {}
            noms = [PONT, TETE] + ([PORTE_BOCAL] if options.commande == "porte-bocal" else [])
            for nom in noms:
                liaison = Liaison(
                    nom, reglages.fluidnc, ouvrir=ouvrir.get(nom) if options.faux else None
                )
                liaisons[nom] = pile.enter_context(liaison)
            for liaison in liaisons.values():
                liaison.attendre_connexion(CONNEXION_S)
            if options.faux:
                force = FausseForce(0.0)
            else:
                pesees = TourPesees(reglages.pesees, materiel)
                pesees.demarrer(arret)
                force = pesees.capteur(PESEE)  # type: ignore[assignment]
            carte_tete = reglages.fluidnc.cartes[TETE]
            tete = TeteFluidnc(
                machine,
                liaisons[PONT],
                liaisons[TETE],
                signaux_prehension(liaisons[TETE], carte_tete),
                force,
                CapteurVide(machine.prehension.vide, lambda: materiel.mesurer(VIDE)),
            )
            tete.demarrer(arret)
            time.sleep(0.5)
            porte_bocal = None
            if PORTE_BOCAL in liaisons:
                carte = reglages.fluidnc.cartes[PORTE_BOCAL]
                porte_bocal = PorteBocalFluidnc(
                    machine,
                    liaisons[PORTE_BOCAL],
                    signaux_porte_bocal(liaisons[PORTE_BOCAL], carte),
                )
            poste = PosteFut(machine.poste_fut, materiel, lecture_directe=True)
            regles_griffe = ReglesGriffe(machine)
            garage_x = None if machine.mycelium is None else machine.mycelium.garage_x
            lettre_griffe = machine.axes["griffe_z"].lettre or "Z"

            def griffe_en_butee_haute() -> bool:
                z = liaisons[PONT].etat.positions.get(lettre_griffe)
                return z is not None and regles_griffe.en_butee_haute(z / 1000)

            prehension = Prehension(
                machine,
                tete,
                porte_bocal,
                panneau_rabattu=poste.panneau_vu_rabattu,
                echange_fut=lambda: poste.echange_en_cours,
                agitateur_x=lambda: garage_x if options.manivelle_en_bas else None,
                manivelle_en_bas=lambda: options.manivelle_en_bas,
                griffe_en_butee_haute=griffe_en_butee_haute,
            )
            return _faire(options, reglages, prehension, tete)
        except (ErreurEtape, ErreurFluidnc, ErreurMateriel, ErreurVide) as erreur:
            print(f"ÉCHEC : {erreur}", file=sys.stderr)
            quoi_faire = getattr(erreur, "quoi_faire", "")
            if quoi_faire:
                print(f"Quoi faire : {quoi_faire}", file=sys.stderr)
            return 1
        finally:
            arret.set()


def _jouer(prehension: Prehension, geste: Callable[[], Geste], delai_s: float) -> None:
    prehension.lancer(geste)
    fin = time.monotonic() + delai_s
    try:
        while not prehension.geste_fini():
            prehension.tete.surveillance.test()
            if time.monotonic() > fin:
                raise ErreurEtape(f"geste pas fini en {delai_s:g} s")
            time.sleep(0.02)
    except ErreurEtape:
        prehension.arreter()
        raise


def _faire(
    options: argparse.Namespace, reglages: Reglages, prehension: Prehension, tete: TeteFluidnc
) -> int:
    delai = reglages.machine.durees["prehension_geste_max"]
    valeurs = options.valeurs
    if options.commande == "etat":
        pose = tete.position()
        print(f"axe de la tête : x {pose.x:.4f} m, y {pose.y:.4f} m")
        print(f"face de la tête : z {pose.z:.4f} m ; rotation {pose.a:.1f}°")
        print(f"contact de la tête : {tete.signaux.entree(CONTACT)}")
        print(f"vide : {tete.vide_kpa():.1f} kPa (zéro {tete.vide.zero:+.1f} kPa)")
        print(f"force (poids porté − poussée) : {tete.peser():.1f} N")
        return 0
    if options.commande == "vide":
        tete.vanne(True)
        try:
            for _ in range(10):
                time.sleep(0.5)
                print(f"vide : {tete.vide_kpa():.1f} kPa")
        finally:
            tete.vanne(False)
        return 0
    objet = valeurs[0] if options.commande == "prendre-poser" else None
    try:
        cotes = [float(valeur) for valeur in valeurs[1 if objet else 0 :]]
    except ValueError:
        print("Les cotes s'écrivent en mètres, avec un point : 1.6 0.6 0.6", file=sys.stderr)
        return 2
    if objet is not None:
        x1, y1, z1, x2, y2, z2 = cotes
        _jouer(
            prehension, lambda: prehension.geste_prendre(objet, x1, y1, z1, options.format), delai
        )
        vide, poids = prehension.vide_prise_kpa, prehension.poids_porte_n
        print(f"Pris : vide {vide:.1f} kPa, poids {poids:.1f} N")
        _jouer(prehension, lambda: prehension.geste_poser(x2, y2, z2), delai)
        print("Posé.")
        return 0
    if options.commande == "porte-bocal":
        x, y, z = cotes
        _jouer(prehension, lambda: prehension.geste_prendre("bocal", x, y, z), delai)
        print(f"Bocal pris : poids {prehension.poids_porte_n:.1f} N")
        _jouer(prehension, prehension.geste_poser_bocal, delai)
        print("Bocal posé et serré dans le porte-bocal.")
        _jouer(prehension, prehension.geste_reprendre_bocal, delai)
        print("Bocal repris.")
        _jouer(prehension, lambda: prehension.geste_poser(x, y, z), delai)
        print("Bocal reposé.")
        return 0
    x1, y1, z1, x2, y2, z2 = cotes
    _jouer(prehension, lambda: prehension.geste_prendre("capsule", x1, y1, z1), delai)
    print("Capsule prise.")
    _jouer(prehension, lambda: prehension.geste_visser(x2, y2, z2), delai)
    print("Capsule vissée.")
    return 0


def lancer() -> None:
    """Point d'entrée de la commande « vidange-prehension »."""
    sys.exit(main())
