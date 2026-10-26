"""Outils communs aux tests."""

import shutil
from pathlib import Path

import pytest

DOSSIER_PI = Path(__file__).resolve().parent.parent


@pytest.fixture
def reglages(tmp_path: Path) -> Path:
    """Copie des réglages d'exemple du dépôt, que chaque test peut abîmer à sa guise."""
    dossier = tmp_path / "reglages"
    shutil.copytree(DOSSIER_PI / "reglages", dossier)
    return dossier
