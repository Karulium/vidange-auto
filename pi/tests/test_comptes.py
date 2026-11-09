"""Tests des comptes de la page web (tâche 25) : fichier, hachage, sessions, commande."""

import stat

import pytest

from vidange.comptes import Compte, Comptes, ErreurComptes, Role, charger_comptes
from vidange.comptes.comptes import hacher, lire_fichier, mot_de_passe_juste
from vidange.comptes.outil import lancer_compte
from vidange.reglages import ErreurReglages

MOT = "une phrase facile a retenir"


@pytest.fixture
def comptes(tmp_path):
    return Comptes(tmp_path / "comptes.yaml")


def test_le_hachage_n_est_pas_le_mot_de_passe():
    hachage = hacher(MOT)
    assert MOT not in hachage and hachage.startswith("scrypt$")
    assert mot_de_passe_juste(MOT, hachage)
    assert not mot_de_passe_juste(MOT + "x", hachage)
    assert hacher(MOT) != hachage  # sel au hasard
    assert not mot_de_passe_juste(MOT, "n'importe quoi")


def test_ajouter_puis_verifier(comptes):
    assert comptes.vide
    comptes.ajouter("Gael", Role.KARULIUM, MOT)
    assert not comptes.vide
    assert comptes.verifier("gael", MOT) == Compte("gael", Role.KARULIUM)
    assert comptes.verifier("GAEL ", MOT) == Compte("gael", Role.KARULIUM)
    assert comptes.verifier("gael", "faux faux faux") is None
    assert comptes.verifier("inconnu", MOT) is None


def test_le_fichier_est_prive_et_sans_mot_de_passe_lisible(comptes):
    comptes.ajouter("gael", Role.KARULIUM, MOT)
    assert stat.S_IMODE(comptes.chemin.stat().st_mode) == 0o600
    assert MOT not in comptes.chemin.read_text(encoding="utf-8")
    assert not list(comptes.chemin.parent.glob("*.tmp"))


def test_noms_et_mots_de_passe_refuses(comptes):
    with pytest.raises(ErreurComptes, match="trop court"):
        comptes.ajouter("gael", Role.KARULIUM, "court")
    for nom in ("G", "1abc", "avec espace", "é", "a" * 40):
        with pytest.raises(ErreurComptes, match="refusé"):
            comptes.ajouter(nom, Role.VISITEUR, MOT)
    assert comptes.vide


def test_doublon_et_inconnu(comptes):
    comptes.ajouter("gael", Role.KARULIUM, MOT)
    with pytest.raises(ErreurComptes, match="existe déjà"):
        comptes.ajouter("gael", Role.VISITEUR, MOT)
    with pytest.raises(ErreurComptes, match="pas de compte"):
        comptes.changer("zilca", mot_de_passe=MOT + "!")
    with pytest.raises(ErreurComptes, match="pas de compte"):
        comptes.supprimer("zilca")


def test_le_dernier_karulium_ne_peut_ni_partir_ni_changer_de_role(comptes):
    comptes.ajouter("gael", Role.KARULIUM, MOT)
    comptes.ajouter("zilca", Role.EMPLOYE, MOT)
    with pytest.raises(ErreurComptes, match="dernier compte « karulium »"):
        comptes.supprimer("gael")
    with pytest.raises(ErreurComptes, match="dernier compte « karulium »"):
        comptes.changer("gael", role=Role.EMPLOYE)
    comptes.supprimer("zilca")  # un employé, lui, peut partir
    assert list(comptes.noms()) == ["gael"]


def test_session_signee(comptes):
    comptes.ajouter("gael", Role.KARULIUM, MOT)
    gael = Compte("gael", Role.KARULIUM)
    jeton = comptes.creer_session(gael, 3600)
    assert comptes.lire_session(jeton) == gael
    corps, _, signature = jeton.partition(".")
    for faux in (
        None,
        "",
        "x",
        corps + ".AAAA",
        "AAAA." + signature,
        corps + "." + signature + "x",
    ):
        assert comptes.lire_session(faux) is None


def test_session_perimee(tmp_path):
    maintenant = [1000.0]
    comptes = Comptes(tmp_path / "comptes.yaml", horloge=lambda: maintenant[0])
    comptes.ajouter("gael", Role.KARULIUM, MOT)
    jeton = comptes.creer_session(Compte("gael", Role.KARULIUM), 60)
    maintenant[0] = 1059
    assert comptes.lire_session(jeton) is not None
    maintenant[0] = 1061
    assert comptes.lire_session(jeton) is None


def test_compte_supprime_ou_change_annule_ses_sessions(comptes):
    comptes.ajouter("gael", Role.KARULIUM, MOT)
    comptes.ajouter("zilca", Role.EMPLOYE, MOT)
    jeton = comptes.creer_session(Compte("zilca", Role.EMPLOYE), 3600)
    assert comptes.lire_session(jeton) is not None
    comptes.changer("zilca", role=Role.VISITEUR)
    assert comptes.lire_session(jeton) is None
    jeton = comptes.creer_session(Compte("zilca", Role.VISITEUR), 3600)
    comptes.changer("zilca", mot_de_passe=MOT + "!")
    assert comptes.lire_session(jeton) is None
    jeton = comptes.creer_session(Compte("zilca", Role.VISITEUR), 3600)
    comptes.supprimer("zilca")
    assert comptes.lire_session(jeton) is None


def test_le_programme_relit_le_fichier_quand_la_commande_le_change(tmp_path):
    programme = Comptes(tmp_path / "comptes.yaml")
    assert programme.vide
    # Une autre instance (la commande « vidange compte ») crée le premier compte.
    Comptes(tmp_path / "comptes.yaml").ajouter("gael", Role.KARULIUM, MOT)
    assert not programme.vide
    assert programme.verifier("gael", MOT) is not None


def test_les_sessions_ne_valent_que_pour_ce_fichier(tmp_path):
    a = Comptes(tmp_path / "a.yaml")
    b = Comptes(tmp_path / "b.yaml")
    a.ajouter("gael", Role.KARULIUM, MOT)
    b.ajouter("gael", Role.KARULIUM, MOT)
    assert b.lire_session(a.creer_session(Compte("gael", Role.KARULIUM), 3600)) is None


@pytest.mark.parametrize(
    ("texte", "message"),
    [
        ("comptes:\n  gael: {role: patron, mot_de_passe: x}\n", "rôle inconnu"),
        (
            "comptes:\n  gael: {role: karulium, mot_de_passe: motdepasse}\n",
            "pas un mot de passe haché",
        ),
        ("comptes:\n  Gael: {role: karulium, mot_de_passe: x}\n", "nom de compte refusé"),
        ("autre: 1\n", "seuls « cle_session » et « comptes »"),
        ("comptes: [a]\n", "mal écrits"),
    ],
)
def test_fichier_des_comptes_faux_empeche_de_demarrer(tmp_path, texte, message):
    chemin = tmp_path / "comptes.yaml"
    chemin.write_text(texte, encoding="utf-8")
    with pytest.raises(ErreurReglages, match=message):
        charger_comptes(chemin)


def test_comptes_sans_cle_de_session_refuses(tmp_path):
    chemin = tmp_path / "comptes.yaml"
    Comptes(chemin).ajouter("gael", Role.KARULIUM, MOT)
    lignes = [ligne for ligne in chemin.read_text().splitlines() if "cle_session" not in ligne]
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    with pytest.raises(ErreurComptes, match="cle_session"):
        lire_fichier(chemin)


def test_pas_de_fichier_ou_fichier_vide_est_permis(tmp_path):
    assert charger_comptes(tmp_path / "absent.yaml").vide
    modele = tmp_path / "modele.yaml"
    modele.write_text("cle_session: ''\ncomptes: {}\n", encoding="utf-8")
    assert charger_comptes(modele).vide


def test_le_modele_du_depot_est_vide():
    from .conftest import DOSSIER_PI

    assert charger_comptes(DOSSIER_PI / "comptes.exemple.yaml").vide


# ---------------------------------------------------------------- la commande « vidange compte »


def commande(chemin, *arguments, mot_de_passe=None, monkeypatch=None):
    if mot_de_passe is not None:
        import io
        import sys

        monkeypatch.setattr(sys, "stdin", io.StringIO(mot_de_passe + "\n"))
    return lancer_compte(list(arguments), chemin)


def test_commande_ajouter_changer_lister_supprimer(tmp_path, monkeypatch, capsys):
    chemin = tmp_path / "comptes.yaml"
    assert commande(chemin, "liste") == 0
    assert "Aucun compte" in capsys.readouterr().out
    assert (
        commande(
            chemin,
            "ajouter",
            "gael",
            "--role",
            "karulium",
            "--mot-de-passe-sur-stdin",
            mot_de_passe=MOT,
            monkeypatch=monkeypatch,
        )
        == 0
    )
    assert commande(chemin, "liste") == 0
    sortie = capsys.readouterr().out
    assert "gael" in sortie and "karulium" in sortie and MOT not in sortie
    assert (
        commande(
            chemin,
            "changer",
            "gael",
            "--mot-de-passe",
            "--mot-de-passe-sur-stdin",
            mot_de_passe=MOT + "!",
            monkeypatch=monkeypatch,
        )
        == 0
    )
    assert Comptes(chemin).verifier("gael", MOT + "!") is not None
    assert commande(chemin, "supprimer", "gael") == 2  # le dernier karulium
    assert "dernier compte" in capsys.readouterr().err


def test_commande_mot_de_passe_trop_court_ne_cree_rien(tmp_path, monkeypatch, capsys):
    chemin = tmp_path / "comptes.yaml"
    code = commande(
        chemin,
        "ajouter",
        "gael",
        "--role",
        "karulium",
        "--mot-de-passe-sur-stdin",
        mot_de_passe="court",
        monkeypatch=monkeypatch,
    )
    assert code == 2 and "trop court" in capsys.readouterr().err
    assert not chemin.exists()


def test_commande_changer_sans_rien_a_changer(tmp_path, capsys):
    assert commande(tmp_path / "comptes.yaml", "changer", "gael") == 2
    assert "rien à changer" in capsys.readouterr().err


def test_vidange_compte_passe_par_la_commande_principale(tmp_path, monkeypatch, capsys):
    from vidange.demarrage import principal

    monkeypatch.setenv("VIDANGE_COMPTES", str(tmp_path / "comptes.yaml"))
    assert principal(["compte", "liste"]) == 0
    assert "Aucun compte" in capsys.readouterr().out
