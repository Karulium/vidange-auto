"""Démarrage du programme du Pi.

1. Lit et vérifie les réglages et la liste des entrées/sorties : une erreur arrête
   tout, avec un message clair (code de sortie 2 : systemd ne relance pas en boucle
   un programme mal réglé).
2. Met en place le journal et lit les secrets.
3. Ouvre le registre (base SQLite, montée à la dernière version) : une base abîmée arrête
   tout (code de sortie 3). Lance la copie de secours quotidienne.
4. Attend l'ordre d'arrêt (pas encore de logique de machine).

Où trouver les fichiers (du plus fort au plus faible) : option de la ligne de
commande, puis variable d'environnement (posée par le service systemd), puis
l'emplacement dans le dépôt (pour les essais sur un PC).
"""

import argparse
import os
import signal
import sys
import threading
from pathlib import Path

from vidange import __version__
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fichier_secrets import charger_secrets
from vidange.journal import configurer_journal, donner_journal
from vidange.registre import (
    DOSSIER_SAUVEGARDES,
    ErreurRegistre,
    SauvegardeQuotidienne,
    ouvrir_registre,
)
from vidange.reglages import ErreurReglages, charger_reglages

# Codes de sortie. Le service systemd (pi/systeme/vidange.service) utilise CODE_REGLAGES_FAUX.
CODE_OK = 0
CODE_PLANTAGE = 1
CODE_REGLAGES_FAUX = 2
CODE_REGISTRE_ABIME = 3

DOSSIER_PI = Path(__file__).resolve().parent.parent

journal = donner_journal("demarrage")


def _chemin(option: str | None, variable: str, defaut: Path) -> Path:
    if option:
        return Path(option)
    if os.environ.get(variable):
        return Path(os.environ[variable])
    return defaut


def lire_arguments(arguments: list[str] | None) -> argparse.Namespace:
    lecteur = argparse.ArgumentParser(
        prog="vidange", description="Programme du Pi de la machine « Vidange automatique »."
    )
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument(
        "--entrees-sorties",
        help="liste des entrées/sorties (défaut : docs/entrees-sorties.yaml)",
    )
    lecteur.add_argument("--secrets", help="fichier de secrets (défaut : pi/secrets.yaml)")
    lecteur.add_argument("--donnees", help="dossier des données : journal... (défaut : pi/donnees)")
    lecteur.add_argument(
        "--verifier", action="store_true", help="vérifie les réglages et s'arrête sans démarrer"
    )
    return lecteur.parse_args(arguments)


def principal(arguments: list[str] | None = None, arret: threading.Event | None = None) -> int:
    """Lance le programme et rend le code de sortie. `arret` sert aux tests."""
    options = lire_arguments(arguments)
    dossier_reglages = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    chemin_entrees_sorties = _chemin(
        options.entrees_sorties,
        "VIDANGE_ENTREES_SORTIES",
        DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml",
    )
    chemin_secrets = _chemin(options.secrets, "VIDANGE_SECRETS", DOSSIER_PI / "secrets.yaml")
    dossier_donnees = _chemin(options.donnees, "VIDANGE_DONNEES", DOSSIER_PI / "donnees")

    # Journal à l'écran seulement, le temps de lire ses propres réglages.
    configurer_journal()
    try:
        reglages = charger_reglages(dossier_reglages)
        reglages_journal = reglages.programme.journal
        configurer_journal(
            niveau=reglages_journal.niveau,
            dossier=None if options.verifier else dossier_donnees / "journal",
            taille_fichier_mo=reglages_journal.taille_fichier_mo,
            nombre_fichiers=reglages_journal.nombre_fichiers,
        )
        entrees_sorties = charger_entrees_sorties(chemin_entrees_sorties)
        charger_secrets(chemin_secrets)
    except ErreurReglages as erreur:
        journal.error("%s", erreur)
        return CODE_REGLAGES_FAUX

    if reglages.machine.exemple:
        journal.warning(
            "machine.yaml contient des valeurs d'EXEMPLE (exemple: true) : "
            "ne pas faire bouger la vraie machine avec."
        )
    if reglages.fluidnc.exemple:
        journal.warning(
            "fluidnc.yaml contient des numéros de série d'EXEMPLE (exemple: true) : "
            "les cartes FluidNC ne seront pas trouvées."
        )
    exemples = entrees_sorties.exemples()
    if exemples:
        journal.warning(
            "entrees-sorties.yaml : %d lignes d'EXEMPLE (exemple: true) : ne pas brancher "
            "la vraie machine d'après elles.",
            len(exemples),
        )
    if options.verifier:
        journal.info("Réglages corrects (%s).", dossier_reglages)
        return CODE_OK

    try:
        registre = ouvrir_registre(dossier_donnees)
    except ErreurRegistre as erreur:
        journal.error("%s", erreur)
        return CODE_REGISTRE_ABIME

    if arret is None:
        arret = threading.Event()
        for sorte in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sorte, lambda *_: arret.set())
    sauvegarde = SauvegardeQuotidienne(
        registre, dossier_donnees / DOSSIER_SAUVEGARDES, reglages.programme.registre
    )
    fil_sauvegarde = sauvegarde.demarrer(arret)
    try:
        journal.info(
            "Programme du Pi version %s démarré, réglages : %s", __version__, dossier_reglages
        )
        arret.wait()
        journal.info("Arrêt demandé : arrêt propre.")
    finally:
        # Une copie en cours se finit avant qu'on ferme la base.
        fil_sauvegarde.join()
        registre.fermer()
    return CODE_OK


def main() -> None:
    """Point d'entrée de la commande « vidange » (lancée par systemd)."""
    try:
        code = principal()
    except Exception:
        # Plantage imprévu : on le note en entier, systemd relance le programme.
        journal.exception("Plantage imprévu du programme")
        code = CODE_PLANTAGE
    sys.exit(code)
