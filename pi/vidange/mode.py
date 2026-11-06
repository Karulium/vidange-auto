"""Le mode de la machine : production, lavage, UV-ozone ou maïs.

    mode = ModeMachine(donnees / "mode.json", chef, registre)
    mode.actuel            # « production »
    mode.refus()           # pourquoi on ne peut pas changer maintenant, ou None
    mode.changer("lavage", "écran de l'armoire")

On ne change de mode que machine au repos (aucun module en route ni en alarme). Le mode est
gardé dans un fichier (il survit à une coupure) et chaque changement est noté dans le
registre (qui, quand, ancien, nouveau). Les modules liront le mode quand leurs gestes
seront écrits ; la sécurité (UV, ozone, panneau du poste du fût) reste câblée.

Mode maïs (tâche 38) : store ouvert, ventilateur de l'enceinte coupé (la vapeur moisit le filtre
HEPA), pas de purge ; le portique lent par la clé relève du module Portique.
D'autres morceaux peuvent refuser le changement (`refus_supplementaires` : le Nettoyage pendant
une nuit UV-ozone).
"""

import json
import os
from collections.abc import Callable
from pathlib import Path

from vidange.chef import Chef
from vidange.journal import donner_journal
from vidange.registre import ErreurRegistre, Registre

journal = donner_journal("mode")

MODES = {"production": "Production", "lavage": "Lavage", "uv_ozone": "UV-ozone", "mais": "Maïs"}
PAR_DEFAUT = "production"


class ErreurMode(Exception):
    """Changement de mode impossible maintenant."""


class ModeMachine:
    def __init__(self, fichier: Path, chef: Chef, registre: Registre | None = None) -> None:
        self.fichier = fichier
        self.chef = chef
        self.registre = registre
        self._actuel = self._lire()
        # Autres raisons de refuser un changement : refus() → raison, ou None.
        self.refus_supplementaires: list[Callable[[], str | None]] = []

    def _lire(self) -> str:
        if not self.fichier.exists():
            return PAR_DEFAUT
        try:
            mode = json.loads(self.fichier.read_text(encoding="utf-8"))["mode"]
        except (OSError, ValueError, KeyError, TypeError) as erreur:
            journal.warning("Fichier du mode illisible (%s) : mode « %s »", erreur, PAR_DEFAUT)
            return PAR_DEFAUT
        if mode not in MODES:
            journal.warning("Mode inconnu « %s » dans le fichier : mode « %s »", mode, PAR_DEFAUT)
            return PAR_DEFAUT
        return mode

    @property
    def actuel(self) -> str:
        return self._actuel

    @property
    def libelle(self) -> str:
        return MODES[self._actuel]

    def refus(self) -> str | None:
        """Pourquoi on ne peut pas changer de mode maintenant (None : c'est possible)."""
        occupes = [m.module for m in self.chef.etat().modules if m.statut in ("en_cours", "alarme")]
        if occupes:
            return f"pas pendant un cycle ({', '.join(occupes)})"
        for refus in self.refus_supplementaires:
            raison = refus()
            if raison is not None:
                return raison
        return None

    def changer(self, nouveau: str, qui: str) -> None:
        if nouveau not in MODES:
            raise ErreurMode(f"mode inconnu « {nouveau} »")
        if nouveau == self._actuel:
            return
        refus = self.refus()
        if refus is not None:
            raise ErreurMode(f"Changement de mode refusé : {refus}")
        ancien = self._actuel
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        provisoire = self.fichier.with_suffix(".tmp")
        provisoire.write_text(json.dumps({"mode": nouveau}), encoding="utf-8")
        os.replace(provisoire, self.fichier)
        self._actuel = nouveau
        journal.warning("Mode « %s » → « %s » (%s)", ancien, nouveau, qui)
        if self.registre is not None:
            try:
                self.registre.noter_reglage(qui, self.fichier.name, "mode", ancien, nouveau)
            except ErreurRegistre as erreur:
                journal.error("Changement de mode pas noté dans le registre : %s", erreur)
