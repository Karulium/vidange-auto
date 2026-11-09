"""Copie de secours des fichiers qui ne sont ni dans Git ni dans le registre (tâche 25).

Chaque jour, avec la copie du registre, une archive « fichiers-AAAA-MM-JJ.tar.gz » reprend :
  - les petits fichiers du dossier des données (angles, état de l'entonnoir, de l'eau de lavage,
    appris de la tête de préhension...), sans le registre (copié à part), ni les dossiers
    (photos, journal, clips : les photos partent déjà à part) ;
  - le fichier des comptes de la page web (mots de passe hachés), sous le nom « comptes.yaml » ;
  - les RÉGLAGES que le Pi a changés par rapport à Git (changés depuis la page ou à la main : les
    vrais chiffres de la machine), sous « reglages/CHEMIN-DANS-LE-DEPOT » (tâche 25 bis). La liste
    vient de Git (`git status`), limitée à pi/reglages, fluidnc et docs/entrees-sorties.yaml.
Le fichier de SECRETS n'y est jamais (clés et jetons : à garder dans le gestionnaire de mots de
passe de Karulium, voir pi/systeme/essai-restauration.md).

Sur un Pi neuf, `vidange restaurer` remet tout cela (vidange/restauration).
"""

import os
import re
import subprocess
import tarfile
from datetime import date
from pathlib import Path

from vidange.journal import donner_journal

journal = donner_journal("registre")

NOM_COMPTES = "comptes.yaml"
DOSSIER_DONNEES_DANS_ARCHIVE = "donnees"
DOSSIER_REGLAGES_DANS_ARCHIVE = "reglages"
# Les seuls endroits du dépôt dont on copie les changements (jamais de secrets : ils sont hors Git).
RACINES_REGLAGES = ("pi/reglages", "fluidnc", "docs/entrees-sorties.yaml")
_PARTIE_SURE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
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


def chemin_de_reglage_sur(chemin: str) -> bool:
    """Vrai si `chemin` (relatif au dépôt) est un fichier de réglages qu'on a le droit de copier."""
    morceaux = chemin.split("/")
    if not all(_PARTIE_SURE.match(m) for m in morceaux):
        return False
    if any(mot in chemin.lower() for mot in ("secret", "comptes")):
        return False
    return any(chemin == r or chemin.startswith(r + "/") for r in RACINES_REGLAGES)


def reglages_changes(depot: Path) -> list[str]:
    """Les fichiers de réglages suivis par Git que le Pi a changés (chemins relatifs au dépôt).

    Rend une liste vide, sans rien casser, si Git ne répond pas."""
    try:
        fin = subprocess.run(
            # safe.directory : la restauration tourne en root, le dépôt est au compte vidange.
            ["git", "-c", f"safe.directory={depot}", "status", "--porcelain", "-z",
             "--untracked-files=no", "--", *RACINES_REGLAGES],
            cwd=depot, capture_output=True, text=True, timeout=30, check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        journal.warning("Git ne répond pas : réglages du Pi non copiés", exc_info=True)
        return []
    if fin.returncode != 0:
        journal.warning("« git status » a échoué (%s) : réglages du Pi non copiés", fin.stderr)
        return []
    entrees = fin.stdout.split("\0")
    chemins: list[str] = []
    i = 0
    while i < len(entrees):
        entree = entrees[i]
        i += 1
        if len(entree) < 4:
            continue
        etat, chemin = entree[:2], entree[3:]
        if "R" in etat or "C" in etat:
            i += 1  # le renommage est suivi de l'ancien nom
        if "D" in etat or not chemin_de_reglage_sur(chemin):
            continue
        fichier = depot / chemin
        if fichier.is_file() and not fichier.is_symlink():
            chemins.append(chemin)
    return sorted(chemins)


def archiver(donnees: Path, comptes: Path | None, cible: Path, depot: Path | None = None) -> Path:
    """Fabrique l'archive d'un coup (jamais à moitié, lisible par son seul propriétaire)."""
    cible.parent.mkdir(parents=True, exist_ok=True)
    temporaire = cible.with_name(cible.name + ".tmp")
    descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descripteur, "wb") as sortie, tarfile.open(fileobj=sortie, mode="w:gz") as tar:
        for fichier in fichiers_a_garder(donnees):
            tar.add(fichier, arcname=f"{DOSSIER_DONNEES_DANS_ARCHIVE}/{fichier.name}")
        if comptes is not None and comptes.is_file():
            tar.add(comptes, arcname=NOM_COMPTES)
        for chemin in reglages_changes(depot) if depot is not None else []:
            tar.add(depot / chemin, arcname=f"{DOSSIER_REGLAGES_DANS_ARCHIVE}/{chemin}")
    os.replace(temporaire, cible)
    return cible
