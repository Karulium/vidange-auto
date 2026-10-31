"""Outil « vidange-porte-bocal » : essayer le porte-bocal et l'origine de la manivelle (carte n° 3).

  vidange-porte-bocal etat          écart des mors, verrou, inclinaison, capteur de la manivelle
  vidange-porte-bocal origine       prise d'origine de la manivelle (tour lent) : donne H
  vidange-porte-bocal ouvrir        mors ouverts (origine des mors reprise)
  vidange-porte-bocal serrer        serrage du bocal : donne son diamètre
  vidange-porte-bocal tete-en-bas   demi-tour du bocal (voir plus bas)
  vidange-porte-bocal debout        demi-tour du bocal, retour debout
  ... --faux                        avec un faux FluidNC et un faux porte-bocal (essai de l'outil)

Un demi-tour fait d'abord la prise d'origine de la manivelle, vérifie que l'agitateur est au
demi-tour, met la manivelle en bas, retourne le bocal, puis remet la manivelle en haut. Le chariot
de remplissage n'est pas encore écrit : vérifier soi-même qu'il est écarté (y ≥ 0,40).
Procédure complète : pi/systeme/essai-porte-bocal.md. À ne lancer que programme principal arrêté
(une seule liaison par carte).
"""

import argparse
import sys
import threading
import time
from collections.abc import Callable

from vidange.chef import ErreurEtape
from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.fluidnc.ports import ErreurFluidnc
from vidange.journal import configurer_journal
from vidange.mycelium.agitateur import AgitateurFluidnc, Pas
from vidange.mycelium.regles import EtatChariot, ReglesMycelium, ecart_angle
from vidange.porte_bocal.faux import FauxMaterielPorteBocal
from vidange.porte_bocal.porte_bocal import (
    INCLINAISON,
    VERROU,
    PorteBocalFluidnc,
    signaux_porte_bocal,
)
from vidange.reglages import ErreurReglages, Reglages, charger_reglages

CARTE = "mycelium_lavage"
# Attente de la première réponse de la carte (s).
CONNEXION_S = 10


class _SansBalance:
    """L'outil n'agite pas : pas de balance."""

    def lire_n(self) -> float:
        raise OSError("pas de balance dans l'outil")


def _faux(reglages: Reglages) -> Callable[[], object]:
    """Un faux FluidNC, avec un faux porte-bocal (bocal posé) et un faux capteur de manivelle."""
    machine = reglages.machine
    carte = FauxFluidnc(axes="XYZA")
    carte.positions.update(X=machine.mycelium.demi_tour_x * 1000, A=200.0)  # type: ignore[union-attr]
    materiel = FauxMaterielPorteBocal(
        carte, machine, reglages.fluidnc.cartes[CARTE], 2.3, time.monotonic
    )
    materiel.poser_bocal()
    # Bocal déjà serré.
    carte.positions[machine.axes["mors"].lettre] = machine.porte_bocal.diametre_bocal_m * 1000  # type: ignore[union-attr]
    lettre = reglages.fluidnc.cartes[CARTE].entrees["origine_manivelle"]
    porte_bocal = materiel.avancer

    def monde() -> None:
        porte_bocal()
        if ecart_angle(carte.positions["A"], 0) > 95:
            carte.entrees.add(lettre)
        else:
            carte.entrees.discard(lettre)

    carte.monde = monde
    return carte.ouvrir


def _attendre(fini: Callable[[], bool], delai_s: float) -> None:
    fin = time.monotonic() + delai_s
    while not fini():
        if time.monotonic() > fin:
            raise ErreurEtape(f"pas fini en {delai_s:g} s")
        time.sleep(0.05)


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(
        prog="vidange-porte-bocal", description=__doc__.split("\n")[0]
    )
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument("--faux", action="store_true", help="avec un faux FluidNC")
    lecteur.add_argument(
        "commande", choices=["etat", "origine", "ouvrir", "serrer", "tete-en-bas", "debout"]
    )
    options = lecteur.parse_args(arguments)
    configurer_journal()
    dossier = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    try:
        reglages = charger_reglages(dossier)
    except ErreurReglages as erreur:
        print(erreur, file=sys.stderr)
        return 2
    machine = reglages.machine
    if machine.porte_bocal is None or machine.mycelium is None:
        print("machine.yaml n'a pas de partie « porte_bocal » ou « mycelium »", file=sys.stderr)
        return 2
    try:
        liaison = Liaison(CARTE, reglages.fluidnc, ouvrir=_faux(reglages) if options.faux else None)
    except ErreurFluidnc as erreur:
        print(erreur, file=sys.stderr)
        return 2
    arret = threading.Event()
    with liaison:
        try:
            liaison.attendre_connexion(CONNEXION_S)
            carte = reglages.fluidnc.cartes[CARTE]
            agitateur = AgitateurFluidnc(machine, liaison, _SansBalance(), carte)  # type: ignore[arg-type]
            agitateur.demarrer(arret)
            porte_bocal = PorteBocalFluidnc(machine, liaison, signaux_porte_bocal(liaison, carte))
            return _faire(options.commande, reglages, agitateur, porte_bocal)
        except (ErreurEtape, ErreurFluidnc) as erreur:
            print(f"ÉCHEC : {erreur}", file=sys.stderr)
            quoi_faire = getattr(erreur, "quoi_faire", "")
            if quoi_faire:
                print(f"Quoi faire : {quoi_faire}", file=sys.stderr)
            return 1
        finally:
            arret.set()


def _faire(
    commande: str, reglages: Reglages, agitateur: AgitateurFluidnc, porte_bocal: PorteBocalFluidnc
) -> int:
    machine = reglages.machine
    delai = machine.durees["mycelium_geste_max"]
    if commande == "etat":
        diametre = porte_bocal.diametre()
        signaux = porte_bocal.signaux
        print(f"écart des mors : {'inconnu' if diametre is None else f'{diametre * 1000:.1f} mm'}")
        print(f"verrou du plateau engagé : {signaux.entree(VERROU)}")
        print(f"capteur d'inclinaison actionné : {signaux.entree(INCLINAISON)}")
        print(f"capteur de la manivelle (métal) : {signaux.entree('origine_manivelle')}")
        return 0
    if commande in ("ouvrir", "serrer"):
        (porte_bocal.ouvrir_mors if commande == "ouvrir" else porte_bocal.serrer_bocal)()
        _attendre(porte_bocal.fini, delai)
        diametre = porte_bocal.diametre() or 0
        quoi = "ouverts" if commande == "ouvrir" else "serrés"
        print(f"Mors {quoi} : écart {diametre * 1000:.1f} mm")
        return 0
    agitateur.executer(Pas("origine de la manivelle", origine=True), None)
    _attendre(agitateur.fini, delai)
    print(f"Manivelle en haut : H = {agitateur.angle_haut_moteur:.1f}° (angle du moteur, A)")
    if commande == "origine":
        return 0
    regles = ReglesMycelium(machine)
    assert machine.mycelium is not None
    # Le chariot de remplissage n'est pas écrit : on le croit écarté (Karulium l'a vérifié).
    ecarte = EtatChariot(y=machine.mycelium.chariot.y_ecarte_min, plateau_z=0)
    pose = agitateur.position()
    if not regles.au_demi_tour(pose):
        raise ErreurEtape(f"agitateur à x {pose.x:.3f} m : l'amener au demi-tour d'abord")

    def manivelle(bas: bool) -> None:
        pose = agitateur.position()
        cible = pose.avec(angle=regles.angle_proche(pose.angle, bas))
        agitateur.executer(Pas("manivelle", angle=cible.angle), cible)
        _attendre(agitateur.fini, delai)

    manivelle(bas=True)
    porte_bocal.verrou = lambda: regles.refus_demi_tour(agitateur.position(), ecarte)
    if commande == "tete-en-bas":
        porte_bocal.retourner_tete_en_bas()
    else:
        porte_bocal.remettre_debout()
    _attendre(porte_bocal.fini, delai)
    manivelle(bas=False)
    print(f"Bocal {'tête en bas' if commande == 'tete-en-bas' else 'debout'}, manivelle en haut.")
    return 0


def lancer() -> None:
    """Point d'entrée de la commande « vidange-porte-bocal »."""
    sys.exit(main())
