"""Outil « vidange-lavage » : essayer le lavage des seaux (cartes n° 1, n° 3 et n° 4).

  vidange-lavage etat                         flotteur, eau dans le fût, tête, vide
  vidange-lavage sortie pompe_lavage 3        une sortie du lavage allumée 3 s (câblage)
  vidange-lavage remplir                      eau neuve jusqu'au flotteur haut
  vidange-lavage vider                        vidange par la bonde
  vidange-lavage brosses                      demande la rotation du noyau tête vide : refusée
  vidange-lavage laver seau_a 1.3 0.74 0.95   prendre le seau retourné là (x y contact_z), le
                                              laver, le reposer au même endroit
  ... --faux                                  avec de faux FluidNC (essai de l'outil : etat)

Les gestes sont ceux du programme, avec tous leurs verrous (vidange.lavage, vidange.prehension) :
le panneau du poste du fût doit être rabattu. Le mode « lavage » est celui de l'essai. Les cotes
sont en mètres, repère du portique : x, y = axe de la tête ; contact_z = face de la tête quand
elle touche le fond du seau retourné. Procédure complète : pi/systeme/essai-lavage.md. À ne
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
from vidange.griffe.simulation import FausseForce
from vidange.journal import configurer_journal
from vidange.lavage.eau import CHAUFFAGE, EauLavage
from vidange.lavage.lavage import Lavage
from vidange.lavage.signaux import signaux_lavage
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel
from vidange.pesees.tour import TourPesees
from vidange.poste_fut import PosteFut
from vidange.prehension.prehension import Geste, Prehension
from vidange.prehension.tete import CapteurVide, ErreurVide, Pas, TeteFluidnc, signaux_prehension
from vidange.reglages import SORTIES_LAVAGE, ErreurReglages, Reglages, charger_reglages

PONT = "portique"
TETE = "prehension"
EAU = "mycelium_lavage"
VIDE = "vide_venturi"
PESEE = "pesee_prehension"
PANNEAU = "reed_panneau_poste_fut"
CHARIOT = "chariot_fut_en_place"
# Attente de la première réponse des cartes (s).
CONNEXION_S = 10


def _faux_ouvrir(reglages: Reglages) -> dict[str, Callable[[], object]]:
    """De faux FluidNC : pont à x 1,471 (axe de la tête 1,6), tête en haut."""
    portique = FauxFluidnc(axes="XYZAB")
    portique.positions.update(X=1471.0, Y=600.0)
    tete = FauxFluidnc(axes="XYZABC")
    tete.positions["Z"] = reglages.machine.prehension.haut_z * 1000  # type: ignore[union-attr]
    eau = FauxFluidnc(axes="XYA")
    return {PONT: portique.ouvrir, TETE: tete.ouvrir, EAU: eau.ouvrir}


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-lavage", description=__doc__.split("\n")[0])
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument(
        "--entrees-sorties", help="liste des entrées/sorties (défaut : docs/entrees-sorties.yaml)"
    )
    lecteur.add_argument("--donnees", help="dossier des données (défaut : pi/donnees)")
    lecteur.add_argument("--faux", action="store_true", help="avec de faux FluidNC")
    lecteur.add_argument(
        "commande", choices=["etat", "sortie", "remplir", "vider", "brosses", "laver"]
    )
    lecteur.add_argument("valeurs", nargs="*", help="sortie et durée, ou format et cotes")
    options = lecteur.parse_args(arguments)
    configurer_journal()
    dossier = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    donnees = _chemin(options.donnees, "VIDANGE_DONNEES", DOSSIER_PI / "donnees")
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
    if machine.lavage is None or machine.prehension is None or machine.poste_fut is None:
        print("machine.yaml n'a pas de partie « lavage »", file=sys.stderr)
        return 2
    attendus = {"etat": 0, "sortie": 2, "remplir": 0, "vider": 0, "brosses": 0, "laver": 4}
    if len(options.valeurs) != attendus[options.commande]:
        lecteur.error(f"« {options.commande} » attend {attendus[options.commande]} valeurs")
    arret = threading.Event()
    with ExitStack() as pile:
        try:
            fabrique = FausseFabrique(liste) if options.faux else None
            seulement = {VIDE, PANNEAU, CHARIOT, *reglages.pesees.tour}
            materiel = pile.enter_context(Materiel(liste, fabrique, seulement))
            if fabrique is not None:
                fabrique.regler(VIDE, 0.0)
            ouvrir = _faux_ouvrir(reglages)
            liaisons = {}
            for nom in (PONT, TETE, EAU):
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
            tete = TeteFluidnc(
                machine,
                liaisons[PONT],
                liaisons[TETE],
                signaux_prehension(liaisons[TETE], reglages.fluidnc.cartes[TETE]),
                force,
                CapteurVide(machine.prehension.vide, lambda: materiel.mesurer(VIDE)),
            )
            tete.demarrer(arret)
            time.sleep(0.5)
            poste = PosteFut(machine.poste_fut, materiel, lecture_directe=True)
            prehension = Prehension(
                machine,
                tete,
                panneau_rabattu=poste.panneau_vu_rabattu,
                echange_fut=lambda: poste.echange_en_cours,
            )
            eau = EauLavage(
                machine.lavage,
                signaux_lavage(liaisons, reglages.fluidnc),
                fichier=donnees / "lavage.json",
            )
            lavage = Lavage(
                machine,
                prehension,
                eau,
                mode=lambda: "lavage",
                refus_panneau=lambda: poste.refus_lancement("lavage"),
                panneau_rabattu=poste.panneau_vu_rabattu,
            )
            return _faire(options, reglages, lavage)
        except (ErreurEtape, ErreurFluidnc, ErreurMateriel, ErreurVide, ValueError) as erreur:
            print(f"ÉCHEC : {erreur}", file=sys.stderr)
            quoi_faire = getattr(erreur, "quoi_faire", "")
            if quoi_faire:
                print(f"Quoi faire : {quoi_faire}", file=sys.stderr)
            return 1
        finally:
            arret.set()


def _jouer(lavage: Lavage, geste: Callable[[], Geste], delai_s: float) -> None:
    prehension = lavage.prehension
    prehension.lancer(geste)
    fin = time.monotonic() + delai_s
    try:
        while not prehension.geste_fini():
            prehension.tete.surveillance.test()
            lavage.eau.surveiller()
            if not lavage.panneau_tenu():
                raise ErreurEtape("le panneau du poste du fût a bougé pendant le lavage")
            if time.monotonic() > fin:
                raise ErreurEtape(f"geste pas fini en {delai_s:g} s")
            time.sleep(0.02)
    except ErreurEtape:
        lavage.arreter()
        raise


def _faire(options: argparse.Namespace, reglages: Reglages, lavage: Lavage) -> int:
    durees = reglages.machine.durees
    eau, prehension = lavage.eau, lavage.prehension
    valeurs = options.valeurs
    if options.commande == "etat":
        pose = prehension.tete.position()
        print(f"flotteur : {'haut' if eau.flotteur() else 'bas'} ({eau.flotteur()})")
        print(f"eau dans le fût (gardé) : {'oui' if eau.eau_dans_le_fut else 'non'}")
        premier = eau.premier_remplissage_s
        print(f"premier remplissage : {'pas mesuré' if premier is None else f'{premier:.0f} s'}")
        print(f"tête : x {pose.x:.4f}, y {pose.y:.4f}, face z {pose.z:.4f} m, {pose.a:.1f}°")
        vide = prehension.tete.vide_kpa()
        print(f"vide : {'pas lu' if vide is None else f'{vide:.1f} kPa'}")
        return 0
    if options.commande == "sortie":
        nom, duree = valeurs[0], float(valeurs[1])
        if nom not in SORTIES_LAVAGE:
            print(f"Sortie inconnue « {nom} » ({', '.join(SORTIES_LAVAGE)})", file=sys.stderr)
            return 2
        if nom == CHAUFFAGE and not (eau.flotteur() and eau.eau_dans_le_fut):
            print("Chauffage refusé : fût de lavage pas rempli (flotteur bas)", file=sys.stderr)
            return 1
        eau.signaux.sortie(nom, True)
        try:
            print(f"{nom} allumée {duree:g} s")
            time.sleep(duree)
        finally:
            eau.signaux.sortie(nom, False)
            # Le temps que la ligne parte avant de fermer la liaison.
            time.sleep(0.5)
        print(f"{nom} éteinte")
        return 0
    if options.commande == "remplir":
        _jouer(lavage, lavage.geste_remplir, durees["lavage_eau_max"])
        print(f"Rempli (premier remplissage : {eau.premier_remplissage_s:.0f} s).")
        return 0
    if options.commande == "vider":
        _jouer(lavage, lavage.geste_vider, durees["lavage_eau_max"])
        print("Vidé.")
        return 0
    if options.commande == "brosses":

        def brosser() -> Geste:
            yield Pas("rotation du noyau, tête vide", brosses={"noyau": 360}, duree_s=1)

        try:
            _jouer(lavage, brosser, 10)
        except ErreurEtape as erreur:
            print(f"Refusé, comme prévu : {erreur}")
            return 0
        print("ATTENTION : la rotation n'a pas été refusée !", file=sys.stderr)
        return 1
    format = valeurs[0]
    try:
        x, y, z = (float(valeur) for valeur in valeurs[1:])
    except ValueError:
        print("Les cotes s'écrivent en mètres, avec un point : 1.3 0.74 0.95", file=sys.stderr)
        return 2
    delai = durees["prehension_geste_max"]
    _jouer(lavage, lambda: prehension.geste_prendre("seau_retourne", x, y, z, format), delai)
    print(f"Seau pris : vide {prehension.vide_prise_kpa:.1f} kPa")
    debut = time.monotonic()
    _jouer(lavage, lambda: lavage.geste_laver_seau(format), durees["lavage_geste_max"])
    print(f"Seau lavé en {time.monotonic() - debut:.0f} s.")
    _jouer(lavage, lambda: prehension.geste_poser(x, y, z), delai)
    print("Seau reposé.")
    return 0


def lancer() -> None:
    """Point d'entrée de la commande « vidange-lavage »."""
    sys.exit(main())
