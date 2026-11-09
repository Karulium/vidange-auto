"""« vidange vitesse » : où en est la montée en vitesse, et l'annuler (tâche 30).

    vidange vitesse            dit le palier, les cycles comptés et les derniers changements
    vidange vitesse annuler    annule le dernier changement de palier (agit au prochain démarrage)

Le palier est gardé dans donnees/montee_vitesse.json : la commande marche programme arrêté ou en
marche. Elle ne change jamais un fichier de réglages.
"""

import argparse
import sys
from pathlib import Path

from vidange.registre.base import ErreurRegistre, Registre
from vidange.reglages import ErreurReglages, charger_reglages
from vidange.vitesse.montee import FICHIER, ErreurMontee, MonteeVitesse

QUI = "commande « vidange vitesse »"


def lancer_vitesse(arguments: list[str], dossier_donnees: Path, dossier_reglages: Path) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange vitesse", description=__doc__.split("\n")[0])
    lecteur.add_argument("action", nargs="?", choices=["etat", "annuler"], default="etat")
    options = lecteur.parse_args(arguments)
    try:
        reglages = charger_reglages(dossier_reglages)
    except ErreurReglages as erreur:
        print(erreur, file=sys.stderr)
        return 2
    registre = None
    try:
        registre = Registre(dossier_donnees / "registre.sqlite", dossier_donnees / "photos")
    except ErreurRegistre as erreur:
        print(f"Registre pas ouvert (le changement ne sera pas noté dedans) : {erreur}")
    try:
        from vidange.api.acces import NOM_JOURNAL_ACTIONS, JournalActions

        montee = MonteeVitesse(
            reglages.programme.montee_vitesse,
            dossier_donnees / FICHIER,
            registre,
            JournalActions(dossier_donnees / NOM_JOURNAL_ACTIONS),
        )
        if options.action == "annuler":
            try:
                montee.annuler(QUI)
            except ErreurMontee as erreur:
                print(erreur, file=sys.stderr)
                return 1
            print("Dernier changement annulé : il agira au prochain démarrage du programme.")
        print(montee.texte())
        for changement in montee.en_dict().get("changements", [])[:5]:
            print(
                f"  {changement['quand']} : palier {changement['avant']} → {changement['apres']}"
                f" ({changement['raison']}, {changement['qui']})"
            )
    finally:
        if registre is not None:
            registre.fermer()
    return 0
