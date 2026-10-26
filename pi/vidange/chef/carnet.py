"""Carnet de l'état du cycle : un petit fichier réécrit à chaque changement.

Il dit, pour chaque module en cours : son étape, où il en est, les zones qu'il tient,
son alarme. Après une coupure de courant, on le relit pour savoir où reprendre.

Le fichier n'est jamais à moitié écrit : on écrit un fichier à côté, on le force sur le disque,
puis on le met à la place de l'ancien d'un seul coup. Une coupure pendant l'écriture laisse
l'ancien état, complet.
"""

import json
import os
from pathlib import Path
from typing import Any

from vidange.chef.etapes import ErreurChef

VERSION = 1


class Carnet:
    def __init__(self, chemin: Path) -> None:
        self.chemin = chemin

    def ecrire(self, etat: dict[str, Any]) -> None:
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        provisoire = self.chemin.with_name(self.chemin.name + ".nouveau")
        texte = json.dumps({"version": VERSION, **etat}, ensure_ascii=False, indent=1)
        with provisoire.open("w", encoding="utf-8") as fichier:
            fichier.write(texte)
            fichier.flush()
            os.fsync(fichier.fileno())
        os.replace(provisoire, self.chemin)
        # Le changement de nom lui-même doit aussi être sur le disque.
        dossier = os.open(self.chemin.parent, os.O_RDONLY)
        try:
            os.fsync(dossier)
        finally:
            os.close(dossier)

    def lire(self) -> dict[str, Any] | None:
        """Le dernier état noté, ou None s'il n'y en a pas."""
        if not self.chemin.exists():
            return None
        try:
            etat = json.loads(self.chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError) as erreur:
            raise ErreurChef(
                f"carnet de l'état du cycle illisible ({self.chemin}) : {erreur}"
            ) from None
        if not isinstance(etat, dict) or etat.get("version") != VERSION:
            raise ErreurChef(f"carnet de l'état du cycle d'une autre version ({self.chemin})")
        return etat
