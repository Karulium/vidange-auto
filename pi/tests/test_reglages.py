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
    remplacer(reglages / "machine.yaml", "carte: mycelium_lavage\n", "carte: chariot_inconnu\n")
    message = erreur_de(reglages)
    assert "machine.yaml, axes → exemple_x : carte « chariot_inconnu » absente de fluidnc.yaml" in (
        message
    )


def test_axe_avec_carte_sans_lettre(reglages):
    remplacer(reglages / "machine.yaml", "    lettre: X\n", "")
    assert "« carte » et « lettre » vont ensemble" in erreur_de(reglages)


def test_deux_axes_avec_la_meme_lettre(reglages):
    remplacer(reglages / "machine.yaml", "lettre: B", "lettre: Z")
    message = erreur_de(reglages)
    assert "les axes « exemple_x » et « exemple_y » ont la même lettre Z" in message


def test_lettre_d_axe_inconnue(reglages):
    remplacer(reglages / "machine.yaml", "lettre: B", "lettre: W")
    assert "exemple_y → lettre : doit être l'un de" in erreur_de(reglages)


def test_duree_negative(reglages):
    remplacer(
        reglages / "machine.yaml", "exemple_deplacement_max: 30", "exemple_deplacement_max: -1"
    )
    assert "durees → exemple_deplacement_max : doit être plus grand que 0" in erreur_de(reglages)


def test_reglages_du_chef_manquants(reglages):
    remplacer(reglages / "programme.yaml", "  alarme_pause_tout: true\n", "")
    assert "programme.yaml, chef → alarme_pause_tout : manque" in erreur_de(reglages)


# ---------------------------------------------------------------- tâche 7 : fiabilité


def test_lieu_sur_du_depot():
    reglages = charger_reglages(DOSSIER_PI / "reglages")
    gestes = reglages.machine.lieu_sur
    assert [(g.prise_origine, g.aller) for g in gestes] == [
        ("mycelium_lavage", None),
        (None, "exemple_repos"),
    ]
    assert reglages.programme.fiabilite.onduleur.commande_arret[0] == "sudo"


def test_lieu_sur_verifie(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "  - prise_origine: mycelium_lavage\n", "  - prise_origine: inconnue\n")
    remplacer(machine, "  - aller: exemple_repos\n", "  - aller: nulle_part\n")
    ajouter(machine, "  - prise_origine: portique\n    delai: absent\n")
    message = erreur_de(reglages)
    assert "lieu_sur n° 2 : position inconnue « nulle_part »" in message
    assert "lieu_sur n° 3 : délai « absent » absent de durees" in message


def test_un_seul_geste_par_ligne_de_lieu_sur(reglages):
    ajouter(reglages / "machine.yaml", "  - delai: exemple_deplacement_max\n")
    message = erreur_de(reglages)
    assert "machine.yaml, lieu_sur → n° 3 : écrire « prise_origine: carte » ou « aller" in message


def test_lieu_sur_carte_inconnue(reglages):
    remplacer(
        reglages / "machine.yaml",
        "  - prise_origine: mycelium_lavage\n",
        "  - prise_origine: zut\n",
    )
    assert "lieu_sur n° 1 : carte « zut » absente de fluidnc.yaml" in erreur_de(reglages)


def test_seuils_de_sante_verifies(reglages):
    remplacer(
        reglages / "programme.yaml", "disque_libre_minimum_go: 5", "disque_libre_minimum_go: 80"
    )
    remplacer(reglages / "programme.yaml", "chef_fige_s: 10", "chef_fige_s: 3")
    message = erreur_de(reglages)
    assert "disque_libre_minimum_go doit être plus petit que disque_libre_attention_go" in message
    assert "chef_fige_s (3 s) doit valoir au moins 2 fois periode_s (2 s)" in message


def test_garde_fous_du_pilotage_a_distance_verifies(reglages):
    programme = reglages / "programme.yaml"
    remplacer(programme, "homme_mort_s: 0.6", "homme_mort_s: 0.3")
    remplacer(programme, "pilotage tous les (s).\n  periode_s: 0.05", "pilotage.\n  periode_s: 0.2")
    texte = erreur_de(reglages)
    assert "homme_mort_s (0.3 s) doit valoir au moins 2 fois battement_s (0.2 s)" in texte
    assert "homme_mort_s (0.3 s) doit valoir au moins 2 fois periode_s (0.2 s)" in texte


def test_video_figee_laisse_passer_des_images(reglages):
    remplacer(reglages / "programme.yaml", "video_figee_s: 2", "video_figee_s: 0.4")
    assert "video_figee_s (0.4 s) doit laisser passer au moins 2 images" in erreur_de(reglages)


def test_avance_du_pilotage_et_etat_des_cartes(reglages):
    remplacer(reglages / "fluidnc.yaml", "periode_etat_s: 0.2", "periode_etat_s: 0.3")
    assert "distance → avance_s (0.5 s) doit valoir au moins 2 fois periode_etat_s" in erreur_de(
        reglages
    )


def test_commande_de_camera_vide_refusee(reglages):
    remplacer(reglages / "programme.yaml", "commande: [rpicam-vid,", "commande: []\n      x: [")
    assert "cameras → liste → plafond → commande : ne doit pas être vide" in erreur_de(reglages)
