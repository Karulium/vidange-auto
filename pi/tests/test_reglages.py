"""Tests du chargement et de la vérification des réglages."""

from pathlib import Path

import pytest

from vidange.reglages import ErreurReglages, charger_reglages

from .conftest import DOSSIER_PI


def remplacer(chemin: Path, ancien: str, nouveau: str) -> None:
    texte = chemin.read_text(encoding="utf-8")
    assert ancien in texte, f"« {ancien} » absent de {chemin.name}"
    chemin.write_text(texte.replace(ancien, nouveau, 1), encoding="utf-8")


def ajouter(chemin: Path, texte: str) -> None:
    with chemin.open("a", encoding="utf-8") as fichier:
        fichier.write(texte)


def erreur_de(dossier: Path) -> str:
    with pytest.raises(ErreurReglages) as erreur:
        charger_reglages(dossier)
    return str(erreur.value)


def test_les_reglages_du_depot_sont_corrects():
    reglages = charger_reglages(DOSSIER_PI / "reglages")
    assert reglages.machine.exemple is True
    assert reglages.machine.axes["exemple_x"].course == (0.0, 1.9)
    assert reglages.programme.journal.niveau == "info"


def test_dossier_absent(tmp_path):
    assert "n'existe pas" in erreur_de(tmp_path / "rien")


def test_fichier_manquant(reglages):
    (reglages / "programme.yaml").unlink()
    assert "programme.yaml : fichier manquant" in erreur_de(reglages)


def test_fichier_inconnu(reglages):
    (reglages / "machin.yaml").write_text("a: 1\n", encoding="utf-8")
    assert "machin.yaml : fichier inconnu" in erreur_de(reglages)


def test_fichier_vide(reglages):
    (reglages / "programme.yaml").write_text("# rien\n", encoding="utf-8")
    assert "programme.yaml : fichier vide" in erreur_de(reglages)


def test_fichier_mal_ecrit_donne_la_ligne(reglages):
    (reglages / "programme.yaml").write_text("journal:\n  niveau: [info\n", encoding="utf-8")
    message = erreur_de(reglages)
    assert "programme.yaml, ligne" in message
    assert "fichier mal écrit" in message


def test_nom_ecrit_deux_fois(reglages):
    ajouter(reglages / "machine.yaml", "\naxes:\n  exemple_x:\n    longueur_rail: 1\n")
    assert "« axes » est écrit deux fois" in erreur_de(reglages)


def test_nom_inconnu(reglages):
    remplacer(reglages / "programme.yaml", "niveau:", "niveua:")
    message = erreur_de(reglages)
    assert "programme.yaml, journal → niveua : nom inconnu (faute de frappe ?)" in message
    assert "programme.yaml, journal → niveau : manque" in message


def test_nombre_mal_ecrit(reglages):
    remplacer(reglages / "machine.yaml", "longueur_rail: 2.0", "longueur_rail: deux")
    assert "axes → exemple_x → longueur_rail : doit être un nombre" in erreur_de(reglages)


def test_niveau_de_journal_inconnu(reglages):
    remplacer(reglages / "programme.yaml", "niveau: info", "niveau: bavard")
    assert "niveau : doit être l'un de" in erreur_de(reglages)


def test_nom_avec_majuscule(reglages):
    remplacer(reglages / "machine.yaml", "exemple_zone_b:", "Zone_B:")
    assert "zones → Zone_B : nom à écrire en minuscules" in erreur_de(reglages)


def test_course_plus_longue_que_le_rail(reglages):
    remplacer(reglages / "machine.yaml", "course: [0.0, 1.9]", "course: [0.0, 2.5]")
    message = erreur_de(reglages)
    assert "axes → exemple_x : la course (0 à 2.5 m) sort du rail (0 à 2 m)" in message


def test_course_a_l_envers(reglages):
    remplacer(reglages / "machine.yaml", "course: [0.0, 1.9]", "course: [1.9, 0.0]")
    assert "du plus petit au plus grand" in erreur_de(reglages)


def test_course_avec_trois_nombres(reglages):
    remplacer(reglages / "machine.yaml", "course: [0.0, 1.9]", "course: [0.0, 1.0, 1.9]")
    assert "exemple_x → course : doit être deux nombres" in erreur_de(reglages)


def test_position_hors_course(reglages):
    remplacer(reglages / "machine.yaml", "exemple_z: 1.0", "exemple_z: 1.15")
    message = erreur_de(reglages)
    assert "position « exemple_repos » : exemple_z = 1.15 m sort de la course" in message


def test_position_sur_axe_inconnu(reglages):
    remplacer(reglages / "machine.yaml", "exemple_z: 1.0", "exemple_w: 1.0")
    assert "position « exemple_repos » : axe inconnu « exemple_w »" in erreur_de(reglages)


def test_zone_hors_course(reglages):
    remplacer(reglages / "machine.yaml", "exemple_x: [1.0, 1.9]", "exemple_x: [1.0, 2.0]")
    assert "zone « exemple_zone_b » : sur exemple_x" in erreur_de(reglages)


def test_zones_qui_se_chevauchent(reglages):
    remplacer(reglages / "machine.yaml", "exemple_x: [1.0, 1.9]", "exemple_x: [0.4, 1.9]")
    message = erreur_de(reglages)
    assert "les zones « exemple_zone_a » et « exemple_zone_b » se chevauchent" in message


def test_zones_qui_se_touchent_au_bord_sont_permises(reglages):
    remplacer(reglages / "machine.yaml", "exemple_x: [1.0, 1.9]", "exemple_x: [0.5, 1.9]")
    charger_reglages(reglages)


def test_zones_separees_par_un_seul_axe_sont_permises(reglages):
    # Même x, mais l'une en y bas et l'autre en y haut : pas de chevauchement.
    remplacer(
        reglages / "machine.yaml",
        "exemple_x: [1.0, 1.9]",
        "exemple_x: [0.0, 0.5]\n    exemple_y: [0.3, 0.9]",
    )
    charger_reglages(reglages)


def test_toutes_les_erreurs_sont_dites_d_un_coup(reglages):
    remplacer(reglages / "programme.yaml", "nombre_fichiers: 10", "nombre_fichiers: 0")
    remplacer(reglages / "machine.yaml", "longueur_rail: 2.0", "longueur_rail: -2")
    message = erreur_de(reglages)
    assert "nombre_fichiers : doit valoir au moins 1" in message
    assert "longueur_rail : doit être plus grand que 0" in message


# ---------------------------------------------------------------- fluidnc.yaml


def test_fluidnc_du_depot():
    fluidnc = charger_reglages(DOSSIER_PI / "reglages").fluidnc
    assert fluidnc.exemple is True
    assert set(fluidnc.cartes) == {"portique", "chariot", "mycelium_lavage", "prehension"}


def test_fluidnc_numero_de_serie_en_double(reglages):
    remplacer(reglages / "fluidnc.yaml", '"EXEMPLE-CHARIOT"', '"EXEMPLE-PORTIQUE"')
    message = erreur_de(reglages)
    assert (
        "les cartes « portique » et « chariot » ont le même numéro de série USB "
        "« EXEMPLE-PORTIQUE »" in message
    )


def test_fluidnc_numero_de_serie_sans_guillemets(reglages):
    remplacer(reglages / "fluidnc.yaml", '"EXEMPLE-CHARIOT"', "0001")
    message = erreur_de(reglages)
    assert "chariot → numero_serie_usb : doit être un texte (entre guillemets" in message


def test_fluidnc_numero_de_serie_vide(reglages):
    remplacer(reglages / "fluidnc.yaml", '"EXEMPLE-CHARIOT"', '"  "')
    assert "chariot → numero_serie_usb" in erreur_de(reglages)


def test_fluidnc_silence_trop_court(reglages):
    remplacer(reglages / "fluidnc.yaml", "delai_silence_s: 2", "delai_silence_s: 0.5")
    message = erreur_de(reglages)
    assert "delai_silence_s (0.5 s) doit valoir au moins 3 fois periode_etat_s (0.2 s)" in message


def test_axe_sur_carte_inconnue(reglages):
    remplacer(reglages / "machine.yaml", "carte: portique", "carte: chariot_inconnu")
    message = erreur_de(reglages)
    assert "machine.yaml, axes → exemple_x : carte « chariot_inconnu » absente de fluidnc.yaml" in (
        message
    )


def test_axe_avec_carte_sans_lettre(reglages):
    remplacer(reglages / "machine.yaml", "    lettre: X\n", "")
    assert "« carte » et « lettre » vont ensemble" in erreur_de(reglages)


def test_deux_axes_avec_la_meme_lettre(reglages):
    remplacer(reglages / "machine.yaml", "lettre: Y", "lettre: X")
    message = erreur_de(reglages)
    assert "les axes « exemple_x » et « exemple_y » ont la même lettre X" in message


def test_lettre_d_axe_inconnue(reglages):
    remplacer(reglages / "machine.yaml", "lettre: Y", "lettre: W")
    assert "exemple_y → lettre : doit être l'un de" in erreur_de(reglages)


def test_duree_negative(reglages):
    remplacer(
        reglages / "machine.yaml", "exemple_deplacement_max: 30", "exemple_deplacement_max: -1"
    )
    assert "durees → exemple_deplacement_max : doit être plus grand que 0" in erreur_de(reglages)


def test_reglages_du_chef_manquants(reglages):
    remplacer(reglages / "programme.yaml", "  alarme_pause_tout: true\n", "")
    assert "programme.yaml, chef → alarme_pause_tout : manque" in erreur_de(reglages)
