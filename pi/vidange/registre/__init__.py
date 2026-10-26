"""Registre : base SQLite de tout ce que la machine a fait (fûts, seaux, cycles, mesures...).

Dans le dossier des données : « registre.sqlite » (la base), « photos/ » (les fichiers des
photos, dont la base garde le chemin) et « sauvegardes/ » (copies de secours quotidiennes).
"""

from pathlib import Path

from vidange.registre.base import ErreurRegistre, Registre
from vidange.registre.sauvegarde import SauvegardeQuotidienne

NOM_BASE = "registre.sqlite"
DOSSIER_PHOTOS = "photos"
DOSSIER_SAUVEGARDES = "sauvegardes"


def ouvrir_registre(donnees: Path) -> Registre:
    """Ouvre (ou crée) le registre du dossier des données, monté à la dernière version."""
    return Registre(donnees / NOM_BASE, donnees / DOSSIER_PHOTOS)


__all__ = [
    "DOSSIER_PHOTOS",
    "DOSSIER_SAUVEGARDES",
    "NOM_BASE",
    "ErreurRegistre",
    "Registre",
    "SauvegardeQuotidienne",
    "ouvrir_registre",
]
