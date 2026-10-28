"""Réglages de l'accéléromètre (accelerometre.yaml) et leur copie pour le programme du RP2040."""

from pathlib import Path

import pytest

from vidange.accelerometre.entete import main
from vidange.reglages import charger_reglages

from .test_reglages import erreur_de, remplacer


def test_reglages_du_depot(reglages: Path):
    accelerometre = charger_reglages(reglages).accelerometre
    assert accelerometre.exemple is True
    assert accelerometre.broches.bloc_i2c == 0
    assert accelerometre.capteur.adresse_i2c == 0x18


def test_entete_pour_le_programme(reglages: Path, tmp_path: Path):
    sortie = tmp_path / "genere"
    assert main([str(reglages / "accelerometre.yaml"), str(sortie)]) == 0
    entete = (sortie / "reglages_genere.h").read_text(encoding="utf-8")
    assert "#define REGLAGE_SEUIL_MG 1500\n" in entete
    assert "#define REGLAGE_AXES 6\n" in entete  # y et z
    assert "#define REGLAGE_ADRESSE_LIS3DH 0x18\n" in entete
    assert "#define REGLAGE_BROCHE_VOYANT 25\n" in entete
    assert 'set(PICO_BOARD "pico")' in (sortie / "reglages_genere.cmake").read_text()

    # Sans voyant, le seuil en g arrondi au mg, l'axe z en plus.
    remplacer(reglages / "accelerometre.yaml", "voyant: 25", "voyant: null")
    remplacer(reglages / "accelerometre.yaml", "seuil_g: 1.5", "seuil_g: 2.0004")
    remplacer(reglages / "accelerometre.yaml", "axes: [y, z]", "axes: [x, y, z]")
    assert main([str(reglages / "accelerometre.yaml"), str(sortie)]) == 0
    entete = (sortie / "reglages_genere.h").read_text(encoding="utf-8")
    assert "#define REGLAGE_BROCHE_VOYANT -1\n" in entete
    assert "#define REGLAGE_SEUIL_MG 2000\n" in entete
    assert "#define REGLAGE_AXES 7\n" in entete


def test_entete_refuse_des_reglages_faux(reglages: Path, tmp_path: Path, capsys):
    remplacer(reglages / "accelerometre.yaml", "seuil_g: 1.5", "seuil_g: 9")
    assert main([str(reglages / "accelerometre.yaml"), str(tmp_path / "genere")]) == 1
    message = capsys.readouterr().err
    assert "choc → seuil_g (9 g) doit être plus petit que capteur → pleine_echelle_g (8 g)" in (
        message
    )
    assert not (tmp_path / "genere").exists()


def test_entete_mauvais_arguments(capsys):
    assert main([]) == 2
    assert "Utilisation" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("ancien", "nouveau", "attendu"),
    [
        ("i2c_sda: 4", "i2c_sda: 3", "i2c_sda (3) doit être une broche paire"),
        ("i2c_scl: 5", "i2c_scl: 4", "i2c_scl (4) doit être une broche impaire"),
        ("i2c_scl: 5", "i2c_scl: 7", "ne sont pas du même bloc I2C"),
        ("sortie_ok: 2", "sortie_ok: 5", "la broche 5 est prise deux fois (i2c_scl et sortie_ok)"),
        ("voyant: 25", "voyant: 30", "voyant : doit valoir au plus 29"),
        ("adresse_i2c: 0x18", "adresse_i2c: 0x20", "adresse_i2c : doit être l'un de"),
        ("pleine_echelle_g: 8", "pleine_echelle_g: 6", "pleine_echelle_g : doit être l'un de"),
        ("mesures_par_seconde: 400", "mesures_par_seconde: 500", "mesures_par_seconde"),
        ("axes: [y, z]", "axes: [x, x]", "axes : un axe est écrit deux fois"),
        ("axes: [y, z]", "axes: []", "axes : ne doit pas être vide"),
        (
            "mesures_par_seconde: 400",
            "mesures_par_seconde: 10",
            "panne → sans_mesure_ms (50 ms) doit valoir au moins 3 fois le temps entre deux "
            "mesures (100 ms avec 10 mesures par seconde)",
        ),
        ("figee_ms: 1000", "figee_ms: 20", "panne → figee_ms (20 ms) doit valoir au moins 20"),
        ("chien_de_garde_ms: 100", "chien_de_garde_ms: 9000", "doit valoir au plus 8000"),
        ("maintien_ms: 500", "maintien_ms: 0", "maintien_ms : doit valoir au moins 10"),
        ("carte: pico", "carte: Pico Zero", "carte : nom à écrire en minuscules"),
    ],
)
def test_reglages_faux(reglages: Path, ancien: str, nouveau: str, attendu: str):
    remplacer(reglages / "accelerometre.yaml", ancien, nouveau)
    message = erreur_de(reglages)
    assert "accelerometre.yaml" in message
    assert attendu in message
