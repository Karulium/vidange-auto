"""La commande « vidange compte » : ajouter, changer, supprimer, lister les comptes.

  vidange compte liste
  vidange compte ajouter NOM --role karulium|employe|visiteur
  vidange compte changer NOM [--role ROLE] [--mot-de-passe]
  vidange compte supprimer NOM

Le mot de passe se tape à l'écran (il ne s'affiche pas), jamais dans la commande : il resterait dans
l'historique du terminal. Pour un script : `--mot-de-passe-sur-stdin` (une ligne lue sur l'entrée).
Sur le Pi, lancer cette commande avec le compte du programme, pour que le fichier lui appartienne :
  sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange compte liste
"""

import argparse
import getpass
import sys
from pathlib import Path

from vidange.comptes.comptes import (
    Comptes,
    ErreurComptes,
    Role,
    verifier_mot_de_passe_assez_long,
)


def _lire_mot_de_passe(sur_stdin: bool, confirmer: bool = True) -> str:
    if sur_stdin:
        mot = sys.stdin.readline().rstrip("\n")
    else:
        mot = getpass.getpass("Mot de passe : ")
        if confirmer and getpass.getpass("Encore une fois : ") != mot:
            raise ErreurComptes("les deux mots de passe ne sont pas pareils, rien n'a été changé")
    verifier_mot_de_passe_assez_long(mot)
    return mot


def lancer_compte(arguments: list[str], chemin: Path) -> int:
    lecteur = argparse.ArgumentParser(
        prog="vidange compte", description="Comptes de la page web (karulium, employe, visiteur)."
    )
    ordres = lecteur.add_subparsers(dest="ordre", required=True)
    ordres.add_parser("liste", help="montre les comptes (jamais les mots de passe)")
    ajouter = ordres.add_parser("ajouter", help="crée un compte")
    ajouter.add_argument("nom")
    ajouter.add_argument("--role", required=True, choices=[r.nom for r in Role])
    changer = ordres.add_parser("changer", help="change le rôle ou le mot de passe")
    changer.add_argument("nom")
    changer.add_argument("--role", choices=[r.nom for r in Role])
    changer.add_argument(
        "--mot-de-passe", action="store_true", help="demande un nouveau mot de passe"
    )
    supprimer = ordres.add_parser("supprimer", help="supprime un compte")
    supprimer.add_argument("nom")
    for sous in (ajouter, changer):
        sous.add_argument(
            "--mot-de-passe-sur-stdin", action="store_true", help="lit le mot de passe sur l'entrée"
        )
    options = lecteur.parse_args(arguments)

    try:
        comptes = Comptes(chemin)
        if options.ordre == "liste":
            noms = comptes.noms()
            if not noms:
                print(
                    f"Aucun compte ({chemin}). Créer : vidange compte ajouter NOM --role karulium"
                )
            for nom, role in noms.items():
                print(f"{nom:<20} {role.nom}")
            return 0
        if options.ordre == "ajouter":
            comptes.ajouter(
                options.nom,
                Role.depuis_nom(options.role),
                _lire_mot_de_passe(options.mot_de_passe_sur_stdin),
            )
            print(f"Compte « {options.nom.strip().lower()} » créé ({options.role}).")
        elif options.ordre == "changer":
            if not options.role and not options.mot_de_passe:
                raise ErreurComptes("rien à changer : donner --role et/ou --mot-de-passe")
            mot = (
                _lire_mot_de_passe(options.mot_de_passe_sur_stdin) if options.mot_de_passe else None
            )
            comptes.changer(
                options.nom, Role.depuis_nom(options.role) if options.role else None, mot
            )
            print(f"Compte « {options.nom.strip().lower()} » changé (il devra se reconnecter).")
        else:
            comptes.supprimer(options.nom)
            print(f"Compte « {options.nom.strip().lower()} » supprimé.")
        return 0
    except (ErreurComptes, OSError) as erreur:
        print(f"Impossible : {erreur}", file=sys.stderr)
        return 2
