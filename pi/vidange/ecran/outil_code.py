"""La commande « vidange code-ecran » : change le code des fonctions sensibles de l'écran.

  vidange code-ecran            (demande le nouveau code deux fois, il ne s'affiche pas)
  vidange code-ecran --retirer  (plus de code : les fonctions sensibles sont refusées)

Le code se tape à l'écran, jamais dans la commande (l'historique du terminal le garderait). Pour un
script : `--code-sur-stdin` (une ligne lue sur l'entrée). Sur le Pi, lancer la commande avec le
compte du programme, pour que le fichier lui appartienne :
  sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange code-ecran
Ce code évite les fausses manoeuvres ; il ne protège pas les personnes (sécurité câblée).
"""

import argparse
import getpass
import sys
from pathlib import Path

from vidange.ecran.code import ecrire_code
from vidange.reglages import ErreurReglages, charger_reglages


def lancer_code_ecran(arguments: list[str], chemin: Path, dossier_reglages: Path) -> int:
    lecteur = argparse.ArgumentParser(
        prog="vidange code-ecran", description="Code des fonctions sensibles de l'écran."
    )
    lecteur.add_argument("--retirer", action="store_true", help="supprime le code")
    lecteur.add_argument("--code-sur-stdin", action="store_true", help="lit le code sur l'entrée")
    options = lecteur.parse_args(arguments)
    try:
        if options.retirer:
            chemin.unlink(missing_ok=True)
            print("Code retiré : les fonctions sensibles de l'écran sont refusées.")
            return 0
        longueur = charger_reglages(dossier_reglages).programme.ecran.code.longueur
        if options.code_sur_stdin:
            code = sys.stdin.readline().rstrip("\n")
        else:
            code = getpass.getpass(f"Nouveau code ({longueur} chiffres) : ")
            if getpass.getpass("Encore une fois : ") != code:
                raise ErreurReglages("les deux codes ne sont pas pareils, rien n'a été changé")
        ecrire_code(chemin, code, longueur)
        print("Code changé (pris en compte tout de suite, sans redémarrer).")
        return 0
    except (ErreurReglages, OSError) as erreur:
        print(f"Impossible : {erreur}", file=sys.stderr)
        return 2
