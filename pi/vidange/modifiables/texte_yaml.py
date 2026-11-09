"""Changer UNE valeur d'un fichier YAML sans toucher au reste (commentaires compris).

Les fichiers de réglages sont pleins de commentaires qui expliquent chaque chiffre : les réécrire
avec une bibliothèque YAML les effacerait. Ici on remplace seulement la valeur de la ligne
« nom: valeur  # commentaire », en suivant l'indentation pour trouver le bon « nom ».

Ne comprend que les listes de « nom: valeur » écrites en blocs (le cas de nos fichiers). Rien
n'est supposé : l'appelant relit le résultat avec le vrai lecteur YAML et compare (voir gestion.py).
"""

import re
from decimal import Decimal

_LIGNE = re.compile(r"^(?P<indent> *)(?P<nom>[A-Za-z0-9_]+) *:(?P<reste>(?: .*)?)$")
# La valeur : un texte entre guillemets, ou un mot sans espace ; puis le reste (commentaire).
_VALEUR = re.compile(r"""^(?P<espace> +)(?P<valeur>"[^"]*"|'[^']*'|[^\s#]+)(?P<fin>\s*(?:#.*)?)$""")


class ErreurTexteYaml(Exception):
    """Le réglage n'a pas été trouvé (ou pas écrit sur une seule ligne simple)."""


def ecrire_valeur(valeur: float | int | str) -> str:
    """La valeur telle qu'on l'écrit dans le fichier : heure entre guillemets, nombre sans
    exposant (YAML ne lit pas « 1e-05 » comme un nombre)."""
    if isinstance(valeur, str):
        return '"' + valeur + '"'
    if isinstance(valeur, int):
        return str(valeur)
    texte = format(Decimal(repr(valeur)), "f")
    return texte if "." in texte else texte + ".0"


def remplacer_valeur(texte: str, chemin: str, nouvelle: float | int | str) -> str:
    """Le texte du fichier avec la valeur de « a.b.c » remplacée (le reste est identique)."""
    cible = chemin.split(".")
    lignes = texte.split("\n")
    pile: list[tuple[int, str]] = []
    trouvees = []
    for numero, ligne in enumerate(lignes):
        brut = ligne.strip()
        if not brut or brut.startswith(("#", "-")):
            continue
        trouve = _LIGNE.match(ligne)
        if trouve is None:
            continue
        indentation = len(trouve["indent"])
        while pile and pile[-1][0] >= indentation:
            pile.pop()
        reste = trouve["reste"]
        if not reste.strip() or reste.strip().startswith("#"):
            # « nom: » seul : un bloc commence.
            pile.append((indentation, trouve["nom"]))
            continue
        if [nom for _, nom in pile] + [trouve["nom"]] == cible:
            valeur = _VALEUR.match(reste)
            if valeur is None:
                raise ErreurTexteYaml(f"ligne {numero + 1} : valeur de {chemin} pas simple à lire")
            trouvees.append((numero, trouve, valeur))
    if len(trouvees) != 1:
        raise ErreurTexteYaml(
            f"« {chemin} » introuvable (ou écrit plusieurs fois) : {len(trouvees)} fois trouvé"
        )
    numero, trouve, valeur = trouvees[0]
    lignes[numero] = (
        f"{trouve['indent']}{trouve['nom']}:{valeur['espace']}{ecrire_valeur(nouvelle)}"
        f"{valeur['fin']}"
    )
    return "\n".join(lignes)
