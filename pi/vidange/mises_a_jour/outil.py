"""Outil « vidange-maj » : les mises à jour à la main, programme principal ARRÊTÉ.

D'ordinaire, les mises à jour se lancent depuis la page web (onglet « Mises à jour »). Cet outil
sert au secours, par SSH, quand le programme ne démarre plus ou qu'une carte ne répond plus :

  vidange-maj version portique                  version du programme de la carte
  vidange-maj copies portique                   copies de sa mémoire gardées sur le Pi
  vidange-maj programme portique FICHIER.bin    écrit un programme (copie, écriture, vérification)
  vidange-maj reglages portique                 envoie fluidnc/portique.yaml
  vidange-maj revenir portique [--copie NOM]    remet une copie (la plus récente par défaut)
  vidange-maj pi chercher | installer | revenir programme du Pi (« main » de GitHub)
  ... --faux                                    pareil avec une fausse carte (essai sur un PC)

Avant : « sudo systemctl stop vidange » (un port USB ne s'ouvre qu'une fois). Après :
« sudo systemctl start vidange ». Ces changements sont notés au journal, pas dans le registre.
"""

import argparse
import sys
from pathlib import Path

from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.fichier_secrets import charger_secrets
from vidange.journal import configurer_journal
from vidange.mises_a_jour.cartes import CarteEsp32
from vidange.mises_a_jour.commun import ErreurMiseAJour
from vidange.mises_a_jour.faux import FausseCarteEsp32
from vidange.mises_a_jour.gestion import DOSSIER, DOSSIER_COPIES, preparer_cartes
from vidange.mises_a_jour.pi import ProgrammePi
from vidange.reglages import ErreurReglages, charger_reglages


def lire_arguments(arguments: list[str] | None) -> argparse.Namespace:
    lecteur = argparse.ArgumentParser(
        prog="vidange-maj",
        description="Mises à jour des cartes ESP32 et du programme du Pi (programme arrêté).",
    )
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument("--donnees", help="dossier des données (défaut : pi/donnees)")
    lecteur.add_argument("--secrets", help="fichier de secrets (défaut : pi/secrets.yaml)")
    lecteur.add_argument("--faux", action="store_true", help="avec une fausse carte")
    sous = lecteur.add_subparsers(dest="action", required=True)
    for action, aide in (
        ("version", "version du programme de la carte"),
        ("copies", "copies de la mémoire de la carte gardées sur le Pi"),
        ("reglages", "envoie fluidnc/CARTE.yaml à la carte"),
    ):
        sous.add_parser(action, help=aide).add_argument("carte")
    programme = sous.add_parser("programme", help="écrit un programme dans la carte")
    programme.add_argument("carte")
    programme.add_argument("fichier", type=Path)
    revenir = sous.add_parser("revenir", help="remet une copie de la mémoire de la carte")
    revenir.add_argument("carte")
    revenir.add_argument("--copie", help="nom de la copie (défaut : la plus récente)")
    pi = sous.add_parser("pi", help="programme du Pi")
    pi.add_argument("travail", choices=["chercher", "installer", "revenir"])
    return lecteur.parse_args(arguments)


def faire_pi(pi: ProgrammePi, travail: str) -> int:
    if travail == "chercher":
        nouvelles = pi.chercher()
        version = pi.version()
        print(f"Version du Pi : {version['court']} du {version['date']} ({version['titre']})")
        for nouvelle in nouvelles:
            print(
                f"  à installer : {nouvelle['court']} du {nouvelle['date']} ({nouvelle['titre']})"
            )
        print(f"{len(nouvelles)} changement(s) à installer.")
        return 0
    print("Quelques minutes (téléchargement, installation, vérification des réglages)…")
    if travail == "installer":
        print(pi.installer("outil vidange-maj"))
    else:
        print(pi.revenir("outil vidange-maj"))
    print("Relancer le programme : sudo systemctl start vidange")
    return 0


def faire_carte(carte: CarteEsp32, options: argparse.Namespace, dossier_fluidnc: Path) -> int:
    action = options.action
    if action == "version":
        version = carte.lire_version()
        print(version or "la carte ne répond pas")
        return 0 if version else 1
    if action == "copies":
        for copie in carte.copies():
            print(f"{copie.nom} : {copie.raison} (version {copie.version or 'inconnue'})")
        return 0
    if action == "programme":
        resultat = carte.ecrire_programme(options.fichier, print)
    elif action == "reglages":
        resultat = carte.envoyer_reglages(dossier_fluidnc / f"{carte.nom}.yaml", print)
    else:
        resultat = carte.revenir(options.copie, print)
    print(f"Réussi : {resultat.message}")
    return 0


def main(arguments: list[str] | None = None) -> int:
    options = lire_arguments(arguments)
    configurer_journal()
    dossier_reglages = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    dossier_donnees = _chemin(options.donnees, "VIDANGE_DONNEES", DOSSIER_PI / "donnees")
    try:
        reglages = charger_reglages(dossier_reglages)
        secrets = charger_secrets(
            _chemin(options.secrets, "VIDANGE_SECRETS", DOSSIER_PI / "secrets.yaml")
        )
    except ErreurReglages as erreur:
        print(erreur)
        return 2
    dossier = dossier_donnees / DOSSIER
    try:
        if options.action == "pi":
            jeton = secrets.jeton_github
            pi = ProgrammePi(
                reglages.programme.mises_a_jour.pi,
                DOSSIER_PI.parent,
                dossier,
                jeton.get_secret_value() if jeton else None,
            )
            return faire_pi(pi, options.travail)
        if options.faux:
            faux = FausseCarteEsp32()
            cartes = {
                nom: CarteEsp32(
                    nom,
                    reglages.programme.mises_a_jour.cartes,
                    dossier / DOSSIER_COPIES,
                    faux.trouver_port,
                    faux.ouvrir,
                    faux.esptool,
                )
                for nom in reglages.fluidnc.cartes
            }
        else:
            cartes = preparer_cartes(reglages, dossier)
        if options.carte not in cartes:
            print(f"Carte « {options.carte} » inconnue (cartes : {', '.join(cartes)})")
            return 2
        return faire_carte(cartes[options.carte], options, DOSSIER_PI.parent / "fluidnc")
    except ErreurMiseAJour as erreur:
        print(f"ÉCHEC : {erreur}")
        return 1


def lancer() -> None:
    """Point d'entrée de la commande « vidange-maj »."""
    sys.exit(main())
