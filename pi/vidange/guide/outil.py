"""La commande `vidange manuel` : écrit (ou vérifie) le manuel d'utilisation (tâche 32).

vidange manuel               écrit docs/manuel.md d'après les réglages
vidange manuel --verifier    dit si docs/manuel.md est à jour (code de sortie 1 sinon)
"""

import argparse
from pathlib import Path

from vidange.guide.manuel import en_markdown
from vidange.reglages import ErreurReglages, charger_reglages


def lancer_manuel(arguments: list[str], dossier_reglages: Path, fichier: Path) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange manuel", description=__doc__)
    lecteur.add_argument("--verifier", action="store_true", help="ne rien écrire : dire si à jour")
    lecteur.add_argument("--fichier", help=f"où écrire le manuel (défaut : {fichier})")
    options = lecteur.parse_args(arguments)
    cible = Path(options.fichier) if options.fichier else fichier
    try:
        texte = en_markdown(charger_reglages(dossier_reglages))
    except ErreurReglages as erreur:
        print(f"Réglages faux : {erreur}")
        return 2
    if options.verifier:
        if cible.exists() and cible.read_text(encoding="utf-8") == texte:
            print(f"{cible} est à jour.")
            return 0
        print(f"{cible} n'est plus à jour : lancer « vidange manuel » et l'ajouter à la PR.")
        return 1
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(texte, encoding="utf-8")
    print(f"Manuel écrit : {cible}")
    return 0
