"""Copie de secours des fichiers qui ne sont ni dans Git ni dans le registre (tâche 25).

Chaque jour, avec la copie du registre, une archive « fichiers-AAAA-MM-JJ.tar.gz » reprend :
  - les petits fichiers du dossier des données (angles, état de l'entonnoir, de l'eau de lavage,
    appris de la tête de préhension...), sans le registre (copié à part), ni les dossiers
    (photos, journal, clips : les photos partent déjà à part) ;
  - le fichier des comptes de la page web (mots de passe hachés), sous le nom « comptes.yaml ».
Le fichier de SECRETS n'y est jamais (clés et jetons : à garder dans le gestionnaire de mots de
passe de Karulium, voir pi/systeme/essai-restauration.md).

Sur un Pi neuf, `vidange restaurer` remet tout cela (vidange/restauration).
"""

import os
import re
import tarfile
from datetime import date
from pathlib import Path

NOM_COMPTES = "comptes.yaml"
DOSSIER_DONNEES_DANS_ARCHIVE = "donnees"
_NOM = re.compile(r"^fichiers-(\d{4}-\d{2}-\d{2})\.tar\.gz$")


def nom_de_archive(jour: date) -> str:
    return f"fichiers-{jour.isoformat()}.tar.gz"


def est_une_archive(nom: str) -> bool:
    return _NOM.match(nom) is not None


def fichiers_a_garder(donnees: Path) -> list[Path]:
    """Les petits fichiers du dossier des données (pas le registre, pas les dossiers)."""
    if not donnees.is_dir():
        return []
    return sorted(
        f
        for f in donnees.iterdir()
        if f.is_file()
        and not f.is_symlink()
        and not f.name.startswith(".")
        and not f.name.startswith("registre.sqlite")
        and not f.name.endswith(".tmp")
    )


def archiver(donnees: Path, comptes: Path | None, cible: Path) -> Path:
    """Fabrique l'archive d'un coup (jamais à moitié, lisible par son seul propriétaire)."""
    cible.parent.mkdir(parents=True, exist_ok=True)
    temporaire = cible.with_name(cible.name + ".tmp")
    descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descripteur, "wb") as sortie, tarfile.open(fileobj=sortie, mode="w:gz") as tar:
        for fichier in fichiers_a_garder(donnees):
            tar.add(fichier, arcname=f"{DOSSIER_DONNEES_DANS_ARCHIVE}/{fichier.name}")
        if comptes is not None and comptes.is_file():
            tar.add(comptes, arcname=NOM_COMPTES)
    os.replace(temporaire, cible)
    return cible
