"""Outil « vidange-registre » pour regarder le registre et faire une copie à la main.

  vidange-registre etat          version de la base, nombre de lignes de chaque table, copies
  vidange-registre sauvegarder   copie de secours tout de suite (avant une mise à jour, par exemple)

Peut tourner pendant que le programme principal tourne (la base accepte un lecteur de plus).
"""

import argparse
import sys

from vidange.demarrage import DOSSIER_PI, _chemin, chemin_des_comptes
from vidange.envois import mettre_en_file_secours
from vidange.journal import configurer_journal
from vidange.registre import (
    DOSSIER_SAUVEGARDES,
    ErreurRegistre,
    SauvegardeQuotidienne,
    ouvrir_registre,
)
from vidange.registre.fichiers_hors_git import archiver
from vidange.reglages import ErreurReglages, charger_reglages


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-registre", description=__doc__.split("\n")[0])
    lecteur.add_argument("ordre", choices=["etat", "sauvegarder"])
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument("--donnees", help="dossier des données (défaut : pi/donnees)")
    options = lecteur.parse_args(arguments)
    configurer_journal()
    reglages_dossier = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    donnees = _chemin(options.donnees, "VIDANGE_DONNEES", DOSSIER_PI / "donnees")
    try:
        reglages = charger_reglages(reglages_dossier)
        registre = ouvrir_registre(donnees)
    except (ErreurReglages, ErreurRegistre) as erreur:
        print(erreur, file=sys.stderr)
        return 2
    try:
        sauvegarde = SauvegardeQuotidienne(
            registre,
            donnees / DOSSIER_SAUVEGARDES,
            reglages.programme.registre,
            # La copie faite à la main part aussi à la maison (file d'envoi).
            apres_copie=mettre_en_file_secours(
                registre, reglages.programme.envois.secours, donnees
            ),
            archiver_fichiers=lambda cible: archiver(donnees, chemin_des_comptes(), cible),
        )
        if options.ordre == "sauvegarder":
            print(f"Copie faite : {sauvegarde.sauvegarder()}")
            return 0
        print(f"Base : {registre.chemin} (version {registre.version})")
        for table, nombre in registre.compter().items():
            print(f"  {table:<20} {nombre}")
        copies = sauvegarde.copies()
        dernier = copies[-1].name if copies else "aucune"
        print(f"Copies de secours : {len(copies)} (dernière : {dernier})")
        return 0
    except ErreurRegistre as erreur:
        print(erreur, file=sys.stderr)
        return 1
    finally:
        registre.fermer()


def lancer() -> None:
    sys.exit(main())
