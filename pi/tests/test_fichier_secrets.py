"""Tests du fichier de secrets."""

import logging

import pytest
import yaml

from vidange.fichier_secrets import Secrets, charger_secrets
from vidange.reglages import ErreurReglages

from .conftest import DOSSIER_PI


def test_le_modele_du_depot_ne_contient_aucun_secret():
    contenu = yaml.safe_load((DOSSIER_PI / "secrets.exemple.yaml").read_text(encoding="utf-8"))
    assert contenu, "le modèle doit lister les secrets attendus"
    assert all(valeur in ("", None) for valeur in contenu.values())
    # Et chaque nom du modèle est connu du programme.
    assert set(contenu) <= set(Secrets.model_fields)


def test_le_modele_se_charge_et_donne_des_secrets_vides():
    assert charger_secrets(DOSSIER_PI / "secrets.exemple.yaml").cle_api is None


def test_le_vrai_fichier_est_ignore_par_git():
    lignes = (DOSSIER_PI.parent / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "secrets.yaml" in lignes


@pytest.fixture
def caplog(caplog, monkeypatch):
    """Le journal « vidange » ne remonte pas au journal général : on le fait remonter pour lire."""
    monkeypatch.setattr(logging.getLogger("vidange"), "propagate", True)
    return caplog


def test_fichier_absent_donne_des_secrets_vides(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="vidange.secrets"):
        assert charger_secrets(tmp_path / "secrets.yaml") == Secrets()
    assert "Pas de fichier de secrets" in caplog.text


def test_secret_lu_mais_jamais_affiche(tmp_path):
    chemin = tmp_path / "secrets.yaml"
    chemin.write_text("cle_api: tres-secret\n", encoding="utf-8")
    chemin.chmod(0o600)
    secrets = charger_secrets(chemin)
    assert secrets.cle_api.get_secret_value() == "tres-secret"
    assert "tres-secret" not in repr(secrets)
    assert "tres-secret" not in str(secrets)


def test_fichier_lisible_par_tous_donne_un_avertissement(tmp_path, caplog):
    chemin = tmp_path / "secrets.yaml"
    chemin.write_text("cle_api: x\n", encoding="utf-8")
    chemin.chmod(0o644)
    with caplog.at_level(logging.WARNING, logger="vidange.secrets"):
        charger_secrets(chemin)
    assert "chmod 600" in caplog.text


def test_nom_inconnu_dans_les_secrets(tmp_path):
    chemin = tmp_path / "secrets.yaml"
    chemin.write_text("cle_apii: x\n", encoding="utf-8")
    chemin.chmod(0o600)
    with pytest.raises(ErreurReglages, match="secrets.yaml, cle_apii : nom inconnu"):
        charger_secrets(chemin)
