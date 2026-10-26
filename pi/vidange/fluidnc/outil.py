"""Outil « vidange-fluidnc » pour les essais sur le vrai matériel (et sur le faux).

  vidange-fluidnc lister              ports USB série vus, avec leur numéro de série
                                      et la carte de fluidnc.yaml qui leur correspond
  vidange-fluidnc console portique    liaison avec une carte : on tape des lignes de G-code
  vidange-fluidnc console portique --faux    pareil, avec un faux FluidNC

À ne lancer que quand le programme principal est arrêté (un port ne s'ouvre qu'une fois).
"""

import argparse
import sys
import time
from pathlib import Path

from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.fluidnc.faux import FauxFluidnc
from vidange.fluidnc.liaison import ErreurCommande, EtatCarte, Liaison
from vidange.fluidnc.ports import ErreurFluidnc, lister_ports_usb
from vidange.fluidnc.protocole import decrire_alarme, decrire_etat
from vidange.journal import configurer_journal
from vidange.reglages import ErreurReglages, Fluidnc, charger_reglages

AIDE_CONSOLE = """\
Taper une ligne de G-code (exemple : G1 X10 F600) puis Entrée. Mots spéciaux :
  etat      affiche l'état et les positions
  pause     pause immédiate (!)        reprise   reprise après pause (~)
  debloquer sort de l'alarme ($X)      reinit    réinitialisation (Ctrl-X)
  fin       attend la fin des mouvements
  fichier CHEMIN   envoie toutes les lignes d'un fichier d'un coup (contrôle de flux)
  quitter   (ou Ctrl-D)"""


def decrire(etat: EtatCarte) -> str:
    if not etat.connectee:
        return "non connectée"
    texte = decrire_etat(etat.etat) if etat.etat else "état inconnu"
    positions = "  ".join(f"{axe}={valeur:.3f}" for axe, valeur in etat.positions.items())
    if etat.alarme is not None:
        texte += f" ({decrire_alarme(etat.alarme)})"
    return f"{texte}  {positions} mm  ({etat.lignes_en_cours} ligne(s) en cours)"


def lister(reglages: Fluidnc) -> int:
    par_numero = {carte.numero_serie_usb: nom for nom, carte in reglages.cartes.items()}
    ports = lister_ports_usb()
    if not ports:
        print("Aucun port série vu : câble USB branché ? carte alimentée ?")
    for port in ports:
        carte = par_numero.get(port.serial_number or "", "aucune carte de fluidnc.yaml")
        print(
            f"{port.device} : n° de série « {port.serial_number or 'AUCUN'} », "
            f"{port.description} → {carte}"
        )
    return 0


def envoyer_fichier(liaison: Liaison, chemin: Path, delai_s: float) -> None:
    """Toutes les lignes partent sans attendre : seule la liaison règle le débit."""
    try:
        lignes = [ligne.strip() for ligne in chemin.read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeDecodeError) as erreur:
        print(f"ÉCHEC : fichier introuvable ou illisible ({erreur})")
        return
    debut = time.monotonic()
    commandes = [liaison.envoyer(ligne) for ligne in lignes if ligne]
    echecs = 0
    for commande in commandes:
        try:
            commande.attendre(delai_s)
        except ErreurCommande as erreur:
            echecs += 1
            print(f"ÉCHEC : {erreur}")
    duree = time.monotonic() - debut
    print(f"{len(commandes)} lignes envoyées en {duree:.1f} s, {echecs} échec(s)")


def console(liaison: Liaison, delai_s: float) -> int:
    print(AIDE_CONSOLE)
    try:
        etat = liaison.attendre_connexion(delai_s)
    except ErreurFluidnc as erreur:
        print(f"Pas de connexion : {erreur}")
        return 1
    print(decrire(etat))
    for ligne in sys.stdin:
        ligne = ligne.strip()
        try:
            if not ligne:
                continue
            if ligne == "quitter":
                break
            if ligne == "etat":
                print(decrire(liaison.etat))
            elif ligne == "pause":
                liaison.pause()
            elif ligne == "reprise":
                liaison.reprendre()
            elif ligne == "reinit":
                liaison.reinitialiser()
            elif ligne == "debloquer":
                liaison.debloquer().attendre(delai_s)
                print("ok")
            elif ligne.startswith("fichier "):
                envoyer_fichier(liaison, Path(ligne.removeprefix("fichier ").strip()), delai_s)
            elif ligne == "fin":
                liaison.attendre_fin_mouvements(delai_s)
                print("mouvements finis : " + decrire(liaison.etat))
            else:
                liaison.envoyer(ligne).attendre(delai_s)
                print("ok")
        except (ErreurCommande, ErreurFluidnc) as erreur:
            print(f"ÉCHEC : {erreur}")
    return 0


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(
        prog="vidange-fluidnc", description="Essais de la liaison avec les cartes FluidNC."
    )
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    sous = lecteur.add_subparsers(dest="action", required=True)
    sous.add_parser("lister", help="ports USB série et leur numéro de série")
    parties = sous.add_parser("console", help="liaison avec une carte, lignes tapées au clavier")
    parties.add_argument("carte", help="nom de la carte dans fluidnc.yaml (exemple : portique)")
    parties.add_argument("--faux", action="store_true", help="avec un faux FluidNC")
    parties.add_argument(
        "--delai", type=float, default=60, help="attente maximale d'une réponse, en s"
    )
    options = lecteur.parse_args(arguments)

    configurer_journal()
    dossier = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    try:
        reglages = charger_reglages(dossier).fluidnc
    except ErreurReglages as erreur:
        print(erreur)
        return 2
    if options.action == "lister":
        return lister(reglages)
    ouvrir = None
    if options.faux:
        ouvrir = FauxFluidnc(taille_tampon=reglages.liaison.taille_tampon).ouvrir
    try:
        liaison = Liaison(options.carte, reglages, ouvrir=ouvrir)
    except ErreurFluidnc as erreur:
        print(erreur)
        return 2
    with liaison:
        return console(liaison, options.delai)


def lancer() -> None:
    """Point d'entrée de la commande « vidange-fluidnc »."""
    sys.exit(main())
