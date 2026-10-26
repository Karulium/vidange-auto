"""Tests du démarrage du programme."""

import configparser
import threading

from vidange.demarrage import CODE_OK, CODE_REGLAGES_FAUX, principal
from vidange.journal import NOM_FICHIER

from .conftest import DOSSIER_PI


def options(reglages, tmp_path):
    return [
        "--reglages",
        str(reglages),
        "--secrets",
        str(tmp_path / "secrets.yaml"),
        "--donnees",
        str(tmp_path / "donnees"),
    ]


def test_verifier_des_reglages_corrects(reglages, tmp_path, capsys):
    assert principal([*options(reglages, tmp_path), "--verifier"]) == CODE_OK
    sortie = capsys.readouterr().err
    assert "Réglages corrects" in sortie
    assert "valeurs d'EXEMPLE" in sortie
    assert "entrees-sorties.yaml : 12 lignes d'EXEMPLE" in sortie
    # La simple vérification n'écrit pas de journal sur le disque.
    assert not (tmp_path / "donnees").exists()


def test_reglages_faux_empechent_de_demarrer(reglages, tmp_path, capsys):
    (reglages / "programme.yaml").unlink()
    arret = threading.Event()
    arret.set()
    assert principal(options(reglages, tmp_path), arret) == CODE_REGLAGES_FAUX
    assert "programme.yaml : fichier manquant" in capsys.readouterr().err


def test_entrees_sorties_fausses_empechent_de_demarrer(reglages, entrees_sorties, tmp_path, capsys):
    texte = entrees_sorties.read_text(encoding="utf-8")
    entrees_sorties.write_text(texte.replace("broche: E2", "broche: E1"), encoding="utf-8")
    arguments = [*options(reglages, tmp_path), "--entrees-sorties", str(entrees_sorties)]
    assert principal([*arguments, "--verifier"]) == CODE_REGLAGES_FAUX
    assert "broche E1 : utilisée par plusieurs signaux" in capsys.readouterr().err


def test_demarrage_puis_arret_propre(reglages, tmp_path):
    arret = threading.Event()
    arret.set()  # l'ordre d'arrêt est déjà donné : le programme démarre puis s'arrête.
    assert principal(options(reglages, tmp_path), arret) == CODE_OK
    contenu = (tmp_path / "donnees" / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    assert "démarré" in contenu
    assert "arrêt propre" in contenu


def test_les_variables_d_environnement_donnent_les_chemins(reglages, tmp_path, monkeypatch):
    (reglages / "programme.yaml").unlink()
    monkeypatch.setenv("VIDANGE_REGLAGES", str(reglages))
    assert principal(["--verifier"]) == CODE_REGLAGES_FAUX


def test_le_service_systemd_ne_relance_pas_des_reglages_faux():
    service = configparser.ConfigParser(strict=False, interpolation=None)
    service.optionxform = str
    service.read(DOSSIER_PI / "systeme" / "vidange.service", encoding="utf-8")
    assert service["Service"]["Restart"] == "on-failure"
    assert service["Service"]["RestartPreventExitStatus"] == str(CODE_REGLAGES_FAUX)
    assert service["Install"]["WantedBy"] == "multi-user.target"
