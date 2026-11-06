"""Outil « vidange-portique » : essayer le portique (cartes n° 1 et n° 4).

  vidange-portique etat              positions, centre du chariot, fins de course, alarmes
  vidange-portique origine           contrôles, freins desserrés, prise d'origine : les Z, Y, X,
                                     godet, rotations de la griffe et de la tête de préhension
  vidange-portique garage            outils en haut, pont au garage, freins serrés
  vidange-portique photo stockage    outils en haut, pont au bout opposé (fut_poste, stockage)
  vidange-portique freins serrer     serrer (ou desserrer) les freins des deux Z
  ... --faux                         avec de faux FluidNC (essai de l'outil)
  ... --confirmer                    tête de la griffe remise à 0° à la main, cordon de la tête
                                     de préhension vérifié : les contrôles passent

Les gestes sont ceux du programme (vidange.portique), dans l'ordre de machine.yaml (portique →
origine). Procédure complète : pi/systeme/essai-portique.md. À ne lancer que programme principal
arrêté (une seule liaison par carte), arrêt d'urgence à portée de main.
"""

import argparse
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from pathlib import Path

from vidange.angles_gardes import AnglesGardes
from vidange.chef import ErreurEtape, Etape
from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.fluidnc.ports import ErreurFluidnc
from vidange.journal import configurer_journal
from vidange.materiel import ErreurMateriel, Materiel
from vidange.portique.portique import Portique
from vidange.reglages import ErreurReglages, Machine, charger_reglages

# Attente de la première réponse des cartes (s).
CONNEXION_S = 10
# Le compte-tours de la tête de préhension (docs/entrees-sorties.yaml).
COMPTE_TOURS = "compte_tours_tete"
# Les fins de course lus dans « Pn: » (lettre de l'axe sur sa carte).
FINS_DE_COURSE = {
    "pont_x": "pont (X1 ou X2)",
    "chariot_y": "chariot Y",
    "griffe_z": "Z de la griffe",
    "prehension_z": "Z de la préhension",
}


def _faux(machine: Machine) -> dict[str, Callable[[], object]]:
    """De faux FluidNC (cartes du pont et de la préhension), en alarme à la mise sous tension."""
    ouvrir: dict[str, Callable[[], object]] = {}
    cartes: dict[str, str] = {}
    origines: dict[str, dict[str, float]] = {}
    for nom, axe in machine.axes.items():
        if axe.carte is None or axe.lettre is None:
            continue
        cartes[axe.carte] = cartes.get(axe.carte, "") + axe.lettre
        if axe.unite == "deg":
            # Une rotation : son origine est 0 (fanion, Hall).
            fin = 0.0
        else:
            fin = (axe.course[1] if nom.endswith("_z") else axe.course[0]) * 1000
        origines.setdefault(axe.carte, {})[axe.lettre] = fin
    for carte, lettres in cartes.items():
        # Comme une vraie carte, le rapport donne les axes depuis X jusqu'au dernier défini.
        dernier = max("XYZABC".index(lettre) for lettre in lettres)
        faux = FauxFluidnc(
            axes="XYZABC"[: dernier + 1],
            vitesse_rapide_mm_min=60_000,
            en_alarme_au_depart=True,
            origines=origines[carte],
        )
        ouvrir[carte] = faux.ouvrir
    return ouvrir


def jouer(etapes: Iterable[Etape], portique: Portique, machine: Machine) -> None:
    """Joue des étapes l'une après l'autre (sans le chef) ; ErreurEtape si l'une échoue."""
    for etape in etapes:
        print(f"→ {etape.nom}")
        fin_entree = time.monotonic() + CONNEXION_S
        while not all(condition.test() for condition in etape.entree):
            if time.monotonic() > fin_entree:
                attendues = ", ".join(condition.texte for condition in etape.entree)
                raise ErreurEtape(f"{etape.nom} : en attente de « {attendues} »")
            time.sleep(0.05)
        if etape.action is not None:
            etape.action()
        if etape.fin is None:
            continue
        delai = machine.durees[etape.delai_max] if etape.delai_max else CONNEXION_S
        fin = time.monotonic() + delai
        while not etape.fin.test():
            portique.pas_d_alarme.test()
            if time.monotonic() > fin:
                portique.arreter()
                raise ErreurEtape(f"{etape.nom} : pas fini en {delai:g} s")
            time.sleep(0.05)


def _etat(portique: Portique, machine: Machine) -> None:
    print("Positions (m) :")
    for nom in FINS_DE_COURSE:
        axe = machine.axes[nom]
        assert axe.carte is not None and axe.lettre is not None
        etat = portique.liaisons[axe.carte].etat
        mm = etat.positions.get(axe.lettre)
        valeur = "inconnue" if mm is None else f"{mm / 1000:.3f}"
        actif = "DÉCLENCHÉ" if axe.lettre in etat.entrees_actives else "libre"
        print(f"  {nom:14} {valeur:>9}   fin de course {FINS_DE_COURSE[nom]} : {actif}")
        if nom == "chariot_y" and mm is not None:
            print(f"  {'':14} centre du chariot à {portique.centre_chariot(mm / 1000):.3f}")
    for nom, liaison in sorted(portique.liaisons.items()):
        print(f"Carte « {nom} » : {liaison.etat.etat or 'pas de réponse'}")
    alarmes = portique.pilotes_en_alarme()
    print(f"Pilotes en alarme : {', '.join(alarmes) if alarmes else 'aucun'}")


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-portique", description=__doc__.split("\n")[0])
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument("--faux", action="store_true", help="avec de faux FluidNC")
    lecteur.add_argument(
        "--entrees-sorties", help="liste des signaux (défaut : docs/entrees-sorties.yaml)"
    )
    lecteur.add_argument("--donnees", help="dossier des données (défaut : pi/donnees)")
    lecteur.add_argument(
        "--confirmer",
        action="store_true",
        help="tête de la griffe remise à 0° à la main, cordon de la préhension vérifié",
    )
    lecteur.add_argument("commande", choices=["etat", "origine", "garage", "photo", "freins"])
    lecteur.add_argument("valeur", nargs="?", help="zone de la photo ; serrer ou desserrer")
    options = lecteur.parse_args(arguments)
    configurer_journal()
    dossier = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    try:
        reglages = charger_reglages(dossier)
    except ErreurReglages as erreur:
        print(erreur, file=sys.stderr)
        return 2
    machine = reglages.machine
    if machine.portique is None:
        print("machine.yaml n'a pas de partie « portique »", file=sys.stderr)
        return 2
    if options.commande == "photo" and options.valeur not in machine.portique.photo:
        lecteur.error(f"photo : zone parmi {', '.join(machine.portique.photo)}")
    if options.commande == "freins" and options.valeur not in ("serrer", "desserrer"):
        lecteur.error("freins : serrer ou desserrer")
    noms = sorted({axe.carte for axe in machine.axes.values() if axe.carte is not None})
    ouvrir = _faux(machine) if options.faux else {}
    with ExitStack() as pile:
        try:
            garde, compte_tours = _angles(options, pile)
            liaisons = {}
            for nom in noms:
                liaison = Liaison(nom, reglages.fluidnc, ouvrir=ouvrir.get(nom))  # type: ignore[arg-type]
                liaisons[nom] = pile.enter_context(liaison)
            portique = Portique(
                machine,
                reglages.fluidnc.cartes,
                liaisons,
                garde=garde,
                compte_tours=compte_tours,
            )
            if options.confirmer:
                portique.rotations.confirmer()
            for nom in portique.cartes:
                liaisons[nom].attendre_connexion(CONNEXION_S)
            if options.commande == "etat":
                pass
            elif options.commande == "origine":
                jouer(portique.etapes_origine(), portique, machine)
            elif options.commande == "garage":
                jouer(portique.etapes_garage(), portique, machine)
            elif options.commande == "photo":
                jouer(portique.etapes_photo(options.valeur), portique, machine)
            elif options.valeur == "serrer":
                portique.serrer_freins()
            else:
                portique.desserrer_freins()
            # Le temps d'un rapport d'état de chaque carte après le dernier geste.
            time.sleep(0.5)
            _etat(portique, machine)
        except (ErreurEtape, ErreurFluidnc, ErreurMateriel, ErreurReglages, ValueError) as erreur:
            print(f"ERREUR : {erreur}", file=sys.stderr)
            quoi_faire = getattr(erreur, "quoi_faire", "")
            if quoi_faire:
                print(f"Quoi faire : {quoi_faire}", file=sys.stderr)
            return 1
    return 0


def _angles(
    options: argparse.Namespace, pile: ExitStack
) -> tuple[AnglesGardes, Callable[[], float | None] | None]:
    """Les angles gardés et le compte-tours de la tête : les vrais (fichier du programme,
    ADS1115), ou de faux (griffe et tête à 0°, essai de l'outil)."""
    if options.faux:
        dossier = Path(pile.enter_context(tempfile.TemporaryDirectory()))
        garde = AnglesGardes(dossier / "angles.json")
        garde.noter("griffe_a", 0.0)
        garde.noter("prehension_a", 0.0)
        return garde, lambda: 0.0
    donnees = _chemin(options.donnees, "VIDANGE_DONNEES", DOSSIER_PI / "donnees")
    garde = AnglesGardes(donnees / "angles.json")
    chemin = _chemin(
        options.entrees_sorties,
        "VIDANGE_ENTREES_SORTIES",
        DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml",
    )
    liste = charger_entrees_sorties(chemin)
    if COMPTE_TOURS not in liste.signaux:
        return garde, None
    materiel = pile.enter_context(Materiel(liste, None, {COMPTE_TOURS}))
    return garde, lambda: materiel.mesurer(COMPTE_TOURS)


def lancer() -> None:
    sys.exit(main())
