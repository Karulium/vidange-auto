"""Boîtier du chariot sur la carte de pesée du plateau du remplissage (tâche 40 bis) : les
registres en plus (servos PCA9685 et capteur de distance VL6180X), lus et écrits par le Pi,
les réglages de l'I2C et leur copie dans le programme de cette seule carte."""

import pytest

from vidange.entrees_sorties import charger_entrees_sorties
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel
from vidange.materiel import carte_pesee as cp
from vidange.pesees import entete, outil
from vidange.pesees.verification import verifier_avec_liste
from vidange.reglages import charger_reglages

from .conftest import DOSSIER_PI
from .test_reglages import erreur_de, remplacer

PLATEAU = "pesee_plateau_remplissage"
CARTES = ["pesee_griffe", "pesee_prehension", PLATEAU]


@pytest.fixture
def liste():
    return charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")


@pytest.fixture
def reglages_pesees():
    return charger_reglages(DOSSIER_PI / "reglages").pesees


@pytest.fixture
def faux(liste):
    return FausseFabrique(liste)


@pytest.fixture
def boitier(faux, reglages_pesees):
    """Le faux boîtier du plateau, avec les plages d'angle de pesees.yaml."""
    plages = [
        (voie.angle_min_deg, voie.angle_max_deg)
        for voie in reglages_pesees.i2c.pca9685.voies.values()
    ]
    return faux.carte_pesee(PLATEAU).brancher_boitier(plages)


@pytest.fixture
def materiel(liste, faux, boitier):
    with Materiel(liste, faux, seulement=CARTES) as materiel:
        yield materiel


# ------------------------------------------------------------- la table


def test_boitier_aller_et_retour():
    boitier = cp.BoitierChariot(
        distance_mm=None,
        etat_tof=cp.TOF_ETAT_MUET,
        age_tof_ms=70000,
        demarrages=31000,
        pca9685_muette=True,
        tof_muet=True,
        aucun_ordre=False,
        pi_silencieux=True,
        pca9685_demarre_pas=True,
        echecs_i2c=5,
        silence_pi_ms=2500,
        angles_deg=(135.0, None, -13.5),
    )
    registres = cp.encoder_boitier(boitier)
    assert registres[:8] == [0xFFFF, 512, 0xFFFF, 31000, 1 | 2 | 8 | 16, 5, 2500, 3]
    assert registres[8:] == [1350, 0x8000, 0x10000 - 135]
    assert cp.decoder_boitier(registres, 3) == replace_age(boitier)


def replace_age(boitier):
    # L'âge est plafonné à 65 535 ms dans le registre.
    from dataclasses import replace

    return replace(boitier, age_tof_ms=0xFFFF)


def test_angles_en_dixiemes_de_degre():
    assert cp.registre_angle(90) == 900
    assert cp.registre_angle(-0.1) == 0xFFFF
    assert cp.registre_angle(None) == 0x8000
    assert cp.angle_du_registre(0xFFFF) == -0.1
    assert cp.angle_du_registre(0x8000) is None
    with pytest.raises(ErreurMateriel, match="impossible"):
        cp.registre_angle(4000)


def test_nombre_de_voies_different(materiel):
    with pytest.raises(ErreurMateriel, match="refaire le programme"):
        materiel.lire_boitier_chariot(PLATEAU, 2)  # 2 voies lues, la carte en a 3
    # Une carte qui a 3 voies, lue pour 4 : la lecture déborde de sa table.
    with pytest.raises(ErreurMateriel, match="registre inconnu"):
        materiel.lire_boitier_chariot(PLATEAU, 4)


# ------------------------------------------------- lecture et écriture


def test_la_pesee_garde_ses_registres_0_a_7(materiel, faux):
    faux.regler_pesee(PLATEAU, 4321)
    mesure = materiel.lire_carte_pesee(PLATEAU)
    assert mesure.brut == 4321 and mesure.par_seconde == 80
    assert materiel.peser(PLATEAU) == 4321


def test_lecture_du_boitier(materiel, boitier, reglages_pesees):
    nb_voies = len(reglages_pesees.i2c.pca9685.voies)
    boitier.distance_mm = 63
    etat = materiel.lire_boitier_chariot(PLATEAU, nb_voies)
    assert etat.distance_mm == 63 and etat.etat_tof == 0
    assert etat.demarrages == 1
    assert etat.aucun_ordre  # sorties coupées : aucun ordre depuis le démarrage
    assert etat.angles_deg == (None, None, None)
    boitier.distance_mm = None
    boitier.etat_tof = 11  # code d'erreur de la puce : hors de portée
    etat = materiel.lire_boitier_chariot(PLATEAU, nb_voies)
    assert etat.distance_mm is None and etat.etat_tof == 11


def test_ecriture_des_angles(materiel, boitier):
    materiel.ecrire_angles_chariot(PLATEAU, [135.0, None, 270.0])
    etat = materiel.lire_boitier_chariot(PLATEAU, 3)
    assert etat.angles_deg == (135.0, None, 270.0)
    assert not etat.aucun_ordre and boitier.ordres == 1
    # Une voie seule, à partir de sa place.
    materiel.ecrire_angles_chariot(PLATEAU, [45.5], premiere_voie=1)
    assert materiel.lire_boitier_chariot(PLATEAU, 3).angles_deg == (135.0, 45.5, 270.0)


def test_angle_hors_de_la_plage_refuse_tout(materiel, boitier):
    materiel.ecrire_angles_chariot(PLATEAU, [10.0, 10.0, 10.0])
    # La voie 1 (lame) va de 0 à 180° : 181° est refusé, et la voie 0 de la même écriture aussi.
    with pytest.raises(ErreurMateriel, match="valeur refusée"):
        materiel.ecrire_angles_chariot(PLATEAU, [50.0, 181.0])
    assert boitier.angles_deg == (10.0, 10.0, 10.0)


def test_registres_inconnus_ou_en_lecture_seule(materiel):
    with pytest.raises(ErreurMateriel, match="registre inconnu"):
        materiel.ecrire_angles_chariot(PLATEAU, [1.0] * 4)  # une voie de trop
    client = materiel._clients["rs485_pesee"]
    for registre in (0, 8, 15):
        with pytest.raises(ErreurMateriel, match="registre inconnu"):
            client.ecrire_registres(3, registre, [1])


def test_les_autres_cartes_n_ont_pas_d_i2c(materiel):
    for nom in ("pesee_griffe", "pesee_prehension"):
        with pytest.raises(ErreurMateriel, match="registre inconnu"):
            materiel.lire_boitier_chariot(nom, 3)
        with pytest.raises(ErreurMateriel, match="fonction non comprise"):
            materiel.ecrire_angles_chariot(nom, [1.0])


def test_redemarrage_vu_par_le_compteur(materiel, boitier):
    materiel.ecrire_angles_chariot(PLATEAU, [90.0, 90.0, 90.0])
    avant = materiel.lire_boitier_chariot(PLATEAU, 3)
    boitier.redemarrer()
    apres = materiel.lire_boitier_chariot(PLATEAU, 3)
    assert apres.demarrages != avant.demarrages
    # La PCA9685 est sortie coupée : le Pi renvoie les angles.
    assert apres.angles_deg == (None, None, None) and apres.aucun_ordre


def test_pi_silencieux_angles_gardes(materiel, boitier):
    materiel.ecrire_angles_chariot(PLATEAU, [90.0, 90.0, 90.0])
    boitier.silence_pi_ms = 2500
    etat = materiel.lire_boitier_chariot(PLATEAU, 3)
    assert etat.pi_silencieux and etat.angles_deg == (90.0, 90.0, 90.0)


# ---------------------------------------------------------- les réglages


def test_exemples_du_depot(reglages_pesees):
    i2c = reglages_pesees.i2c
    assert i2c.carte == PLATEAU
    assert (i2c.broches.sda, i2c.broches.scl, i2c.broches.bloc_i2c) == (4, 5, 0)
    assert i2c.frequence_hz == 100000
    assert list(i2c.pca9685.voies) == [
        "servo_escamotage_micropore",
        "servo_lame_micropore",
        "servo_fermeture_seaux",
    ]
    assert i2c.silence_pi_ms == 2000


def test_pesees_et_signaux_vont_ensemble(reglages_pesees, liste):
    assert verifier_avec_liste(reglages_pesees, liste) == []


@pytest.mark.parametrize(
    ("ancien", "nouveau", "message"),
    [
        (
            "  rs485_sens: 6",
            "  rs485_sens: 4",
            "la broche 4 est prise deux fois (i2c → broches → sda et broches → rs485_sens)",
        ),
        ("    sda: 4", "    sda: 5", "sda (5) doit être une broche paire"),
        ("    scl: 5", "    scl: 7", "ne sont pas du même bloc I2C"),
        ("  delai_transaction_us: 1500", "  delai_transaction_us: 1800", "doit rester sous 1750"),
        ("    adresse: 0x29", "    adresse: 0x40", "même adresse I2C"),
        ("        canal: 1\n", "        canal: 0\n", "le canal 0 est pris deux fois"),
        ("        canal: 2\n", "        canal: 16\n", "canal"),
        ("        angle_max_deg: 180", "        angle_max_deg: 0", "plus petit que angle_max_deg"),
        ("        impulsion_max_us: 2400", "        impulsion_max_us: 500", "impulsion_min_us"),
        ("        impulsion_max_us: 2400", "        impulsion_max_us: 21000", "ne tient pas"),
        ("    frequence_pwm_hz: 50", "    frequence_pwm_hz: 5", "frequence_pwm_hz"),
        ("    sondage_ms: 5", "    sondage_ms: 60", "plus petit que periode_ms"),
        ("  frequence_hz: 100000", "  frequence_hz: 50000", "frequence_hz"),
        (
            "  carte: pesee_plateau_remplissage\n  # I2C0",
            "  carte: pesee_fantome\n  # I2C0",
            "pesee_fantome",
        ),
    ],
)
def test_reglages_i2c_verifies(reglages, ancien, nouveau, message):
    remplacer(reglages / "pesees.yaml", ancien, nouveau)
    assert message in erreur_de(reglages)


def test_voie_et_signal_vont_ensemble(reglages_pesees, liste):
    voies = dict(reglages_pesees.i2c.pca9685.voies)
    voies["servo_inconnu"] = voies.pop("servo_lame_micropore")
    pca = reglages_pesees.i2c.pca9685.model_copy(update={"voies": voies})
    i2c = reglages_pesees.i2c.model_copy(update={"pca9685": pca})
    erreurs = "\n".join(verifier_avec_liste(reglages_pesees.model_copy(update={"i2c": i2c}), liste))
    assert "voie « servo_inconnu » n'est pas un signal" in erreurs


def test_canal_different_dans_la_liste(reglages, entrees_sorties, tmp_path, capsys):
    remplacer(entrees_sorties, "    broche: CH1\n", "    broche: CH4\n")
    code = entete.main([str(reglages / "pesees.yaml"), str(entrees_sorties), str(tmp_path)])
    assert code == 1
    assert "« servo_lame_micropore » doit avoir « broche: CH1 »" in capsys.readouterr().err


# ----------------------------------------- copie dans le programme


def test_i2c_copie_dans_le_programme_de_la_seule_carte(tmp_path):
    entete.ecrire(
        DOSSIER_PI / "reglages" / "pesees.yaml",
        DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml",
        tmp_path,
    )
    texte_h = (tmp_path / "reglages_genere.h").read_text(encoding="utf-8")
    texte_cmake = (tmp_path / "reglages_genere.cmake").read_text(encoding="utf-8")
    assert "#define REGLAGE_I2C_BROCHE_SDA 4" in texte_h
    assert "#define REGLAGE_I2C_BROCHE_SCL 5" in texte_h
    assert "#define REGLAGE_I2C_BLOC 0" in texte_h
    assert "#define REGLAGE_I2C_FREQUENCE_HZ 100000" in texte_h
    assert ".pca = {.adresse = 64, .frequence_hz = 50, .horloge_hz = 25000000}" in texte_h
    assert ".nb_voies = 3" in texte_h
    assert (
        "{.canal = 1, .angle_min_dix = 0, .angle_max_dix = 1800, .impulsion_min_us = 500, "
        ".impulsion_max_us = 2400}"
    ) in texte_h
    assert ".silence_pi_ms = 2000" in texte_h
    # Un seul programme a l'I2C (CMakeLists.txt compare à ce nom).
    assert 'set(CARTE_PESEE_I2C "pesee_plateau_remplissage")' in texte_cmake


def test_sans_i2c_rien_n_est_copie(reglages, entrees_sorties, tmp_path):
    texte = (reglages / "pesees.yaml").read_text(encoding="utf-8")
    debut = texte.index("i2c:\n  carte:")
    fin = texte.index("# Côté Pi : l'ordre des questions")
    (reglages / "pesees.yaml").write_text(texte[:debut] + texte[fin:], encoding="utf-8")
    entete.ecrire(reglages / "pesees.yaml", entrees_sorties, tmp_path)
    assert "I2C" not in (tmp_path / "reglages_genere.h").read_text(encoding="utf-8")
    assert 'set(CARTE_PESEE_I2C "")' in (tmp_path / "reglages_genere.cmake").read_text(
        encoding="utf-8"
    )


# ------------------------------------------------------------- l'outil


def _outil(faux, *arguments: str) -> int:
    chemin = DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"
    return outil.main(
        ["--reglages", str(DOSSIER_PI / "reglages"), "--entrees-sorties", str(chemin), *arguments],
        fabrique=faux,
    )


def test_outil_servo_et_chariot(faux, boitier, capsys):
    assert _outil(faux, "servo", "servo_lame_micropore", "90,5") == 0
    assert "servo_lame_micropore : 90.5°" in capsys.readouterr().out
    assert boitier.angles_deg == (None, 90.5, None)
    assert _outil(faux, "chariot", "--secondes", "1") == 0
    sortie = capsys.readouterr().out
    assert "distance 50 mm" in sortie and "servo_lame_micropore 90.5°" in sortie
    assert "servo_escamotage_micropore coupée" in sortie
    assert _outil(faux, "servo", "servo_lame_micropore", "coupe") == 0
    assert boitier.angles_deg == (None, None, None)


def test_outil_servo_refuse_avant_d_envoyer(faux, boitier, capsys):
    assert _outil(faux, "servo", "servo_lame_micropore", "181") == 2
    assert "hors de sa plage (0° à 180°)" in capsys.readouterr().err
    assert _outil(faux, "servo", "servo_inconnu", "10") == 2
    assert "voie inconnue" in capsys.readouterr().err
    assert _outil(faux, "servo", "servo_lame_micropore", "beaucoup") == 2
    assert boitier.ordres == 0


def test_outil_chariot_carte_sans_i2c(faux, capsys):
    # La carte du faux n'a pas d'I2C branché : la lecture échoue clairement.
    assert _outil(faux, "chariot", "--secondes", "1") == 1
    assert "registre inconnu" in capsys.readouterr().err
