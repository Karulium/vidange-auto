"""Tests du code des fonctions sensibles de l'écran (tâche 29) : faux écran, vrai chef."""

import json
import stat
from types import SimpleNamespace

import pytest

from vidange.api import JournalActions
from vidange.demarrage import principal
from vidange.ecran.code import CodeEcran, ecrire_code, lire_hachage
from vidange.ecran.outil_code import lancer_code_ecran
from vidange.ecran.pages import CODE, PAGES
from vidange.reglages import ErreurReglages

from .conftest import DOSSIER_PI
from .test_ecran import REGLAGES, BancEcran
from .test_reglages import erreur_de, remplacer

CODE_BON = "2468"


def taper(b, chiffres: str) -> None:
    for chiffre in chiffres:
        b.appuyer(f"b_{chiffre}")


@pytest.fixture
def c(tmp_path):
    """Un banc avec un code réglé (2468) et le journal des actions."""
    banc = BancEcran(tmp_path)
    chemin = tmp_path / "code_ecran.yaml"
    ecrire_code(chemin, CODE_BON, REGLAGES.code.longueur)
    banc.code = CodeEcran(chemin, REGLAGES.code, horloge=banc.horloge)
    banc.actions = JournalActions(tmp_path / "actions.jsonl")
    banc.ecran.code, banc.ecran.actions = banc.code, banc.actions
    banc.tour()
    banc.chef.abandonner("essai")  # plus de cycle : le mode peut changer
    banc.tour()
    yield banc
    banc.registre.fermer()


def test_la_page_du_code_est_dans_les_pages():
    assert PAGES["code"] is CODE
    assert CODE.boutons == [*[f"b_{i}" for i in range(10)], "b_effacer", "b_retour"]


def test_la_liste_des_reglages_est_celle_de_l_ecran():
    assert REGLAGES.code.fonctions_sensibles == [
        "changer_mode",
        "enceinte_store",
        "enceinte_nuit",
        "enceinte_outre",
    ]
    assert 4 <= REGLAGES.code.longueur <= 6


def test_mode_demande_le_code_puis_le_oui(c):
    c.appuyer("b_mode")
    c.appuyer("b_lavage")
    assert c.nextion.page == "code"
    assert c.texte("t_saisie") == "----"
    taper(c, "24")
    assert c.texte("t_saisie") == "**--"
    taper(c, "68")
    # Code juste : la page du mode revient avec la question « Oui / Non ».
    assert c.texte("t_question") == "Passer en mode Lavage ?"
    c.appuyer("b_oui")
    assert c.mode.actuel == "lavage"
    (ligne,) = c.actions.dernieres(5)
    assert ligne["qui"] == "écran" and ligne["chemin"] == "ecran/changer_mode"
    assert ligne["detail"] == "lavage"
    assert "2468" not in json.dumps(ligne)


def test_effacer_et_retour(c):
    c.appuyer("b_mode")
    c.appuyer("b_lavage")
    taper(c, "99")
    c.appuyer("b_effacer")
    assert c.texte("t_saisie") == "*---"
    c.appuyer("b_retour")
    assert c.nextion.page == "etat"
    assert c.mode.actuel == "production"


def test_code_faux_puis_attente_puis_nouvel_essai(c):
    c.appuyer("b_mode")
    c.appuyer("b_lavage")
    taper(c, "1111")
    assert c.nextion.page == "code"
    assert c.texte("t_info") == "Code faux. Encore 2 essai(s)."
    assert c.texte("t_saisie") == "----"
    taper(c, "1111")
    taper(c, "1111")
    # Trop d'essais ratés : retour au mode, avec l'attente.
    assert c.nextion.page == "mode"
    assert c.texte("t_info") == f"Trop de codes faux : attendre {REGLAGES.code.attente_s:.0f} s."
    # Même le bon code ne passe pas pendant l'attente.
    c.appuyer("b_lavage")
    assert c.nextion.page == "mode"
    assert c.mode.actuel == "production"
    c.horloge.t += REGLAGES.code.attente_s + 1
    c.appuyer("b_lavage")
    taper(c, CODE_BON)
    assert c.texte("t_question") == "Passer en mode Lavage ?"


def test_le_code_reste_valable_un_moment_puis_il_faut_le_retaper(c):
    c.appuyer("b_mode")
    c.appuyer("b_lavage")
    taper(c, CODE_BON)
    c.appuyer("b_non")
    # Tout de suite après : pas de nouveau code.
    c.appuyer("b_lavage")
    assert c.texte("t_question") == "Passer en mode Lavage ?"
    c.appuyer("b_non")
    c.horloge.t += REGLAGES.code.valable_s + 1
    c.appuyer("b_lavage")
    assert c.nextion.page == "code"


def test_sans_code_regle_les_fonctions_sensibles_sont_refusees(c):
    c.code.chemin.unlink()
    c.appuyer("b_mode")
    c.appuyer("b_lavage")
    assert c.nextion.page == "mode"
    assert "pas réglé" in c.texte("t_info") and "vidange code-ecran" in c.texte("t_info")
    assert c.mode.actuel == "production"
    (constat,) = c.code.constats()
    assert constat.niveau == "attention" and "pas réglé" in constat.texte


def test_ce_qui_ne_demande_pas_de_code(c):
    # Pause, Go, compteurs, mode déjà choisi : jamais de code.
    c.appuyer("b_pause")
    assert c.chef.en_pause
    c.appuyer("b_pause")
    assert c.nextion.page == "confirmer"
    c.appuyer("b_non")
    c.appuyer("b_compteurs")
    assert c.nextion.page == "compteurs"
    assert c.actions.dernieres(5) == []


def test_une_question_sans_reponse_au_code_revient_a_l_etat(c):
    c.appuyer("b_mode")
    c.appuyer("b_lavage")
    c.horloge.t += REGLAGES.confirmation_s + 1
    c.tour()
    assert c.nextion.page == "etat"


class FauxNettoyage:
    def __init__(self):
        self.appels = []
        self.reglages = SimpleNamespace(ozone=SimpleNamespace(heure_depart="22:00"))
        self._etat = SimpleNamespace(
            store="ferme",
            verrous_liberes=False,
            eclairage=False,
            nuit="repos",
            refus_nuit=None,
            purge=True,
            messages=["ok"],
        )

    def etat(self):
        return self._etat

    def demander_ouverture(self, qui):
        self.appels.append(("ouvrir", qui))

    def demander_fermeture(self, qui):
        self.appels.append(("fermer", qui))

    def programmer_nuit(self, qui, tout_de_suite=False):
        self.appels.append(("nuit", tout_de_suite))

    def passer_outre(self, qui):
        self.appels.append(("outre", qui))


def test_store_et_purge_demandent_le_code(c):
    faux = FauxNettoyage()
    c.ecran.nettoyage = faux
    c.ecran._aller(PAGES["nettoyage"])
    c.ecran.appuyer("b_store")
    assert c.ecran.page == "code" and faux.appels == []
    for chiffre in CODE_BON:
        c.ecran.appuyer(f"b_{chiffre}")
    assert c.ecran.page == "nettoyage"
    assert faux.appels == [("ouvrir", "écran de l'armoire")]
    (ligne,) = c.actions.dernieres(5)
    assert ligne["chemin"] == "ecran/enceinte_store" and ligne["detail"] == "ouvrir"
    # « Passer outre » : le code est encore valable, donc la question vient tout de suite.
    c.ecran.appuyer("b_outre")
    assert c.ecran.page == "confirmer"
    c.ecran.appuyer("b_oui")
    assert faux.appels[-1] == ("outre", "écran de l'armoire")
    assert c.actions.dernieres(1)[0]["chemin"] == "ecran/enceinte_outre"
    # La lumière ne demande jamais de code (ici, l'écran n'a pas ce faux : on vérifie la liste).
    assert "lumiere" not in "".join(REGLAGES.code.fonctions_sensibles)


def test_fonction_retiree_de_la_liste_ne_demande_plus_de_code(c):
    c.code.reglages = c.code.reglages.model_copy(update={"fonctions_sensibles": []})
    c.appuyer("b_mode")
    c.appuyer("b_lavage")
    assert c.texte("t_question") == "Passer en mode Lavage ?"
    c.appuyer("b_oui")
    assert c.actions.dernieres(5) == []  # pas sensible : pas noté


# ------------------------------------------------------------------ le fichier et la commande


def test_le_fichier_ne_garde_que_le_hachage(tmp_path):
    chemin = tmp_path / "code_ecran.yaml"
    ecrire_code(chemin, "135790", 6)
    assert "135790" not in chemin.read_text()
    assert chemin.read_text().count("scrypt$") == 1
    assert stat.S_IMODE(chemin.stat().st_mode) == 0o600
    assert lire_hachage(chemin).startswith("scrypt$")


@pytest.mark.parametrize("mauvais", ["123", "12345", "12a4", "١٢٣٤", " 123", ""])
def test_code_mal_forme_refuse(tmp_path, mauvais):
    with pytest.raises(ErreurReglages, match="4 chiffres"):
        ecrire_code(tmp_path / "x.yaml", mauvais, 4)
    assert not (tmp_path / "x.yaml").exists()


def test_fichier_faux_est_signale(tmp_path):
    chemin = tmp_path / "code_ecran.yaml"
    chemin.write_text('code: "1234"\n')
    with pytest.raises(ErreurReglages, match="pas un code haché"):
        lire_hachage(chemin)
    chemin.write_text("autre: 1\n")
    with pytest.raises(ErreurReglages, match="seule la ligne"):
        lire_hachage(chemin)
    chemin.write_text('code: ""\n')
    assert lire_hachage(chemin) is None


def test_le_modele_vide_est_permis():
    assert lire_hachage(DOSSIER_PI / "code_ecran.exemple.yaml") is None


def test_changer_le_code_est_pris_tout_de_suite(tmp_path):
    chemin = tmp_path / "code_ecran.yaml"
    code = CodeEcran(chemin, REGLAGES.code)
    assert not code.regle
    ecrire_code(chemin, "1357", 4)
    assert code.regle and code.verifier("1357") and code.encore_valable()
    ecrire_code(chemin, "9999", 4)
    assert not code.encore_valable()
    assert not code.verifier("1357") and code.verifier("9999")


def test_commande_code_ecran(tmp_path, monkeypatch, capsys):
    chemin = tmp_path / "code_ecran.yaml"
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("8642\n"))
    assert lancer_code_ecran(["--code-sur-stdin"], chemin, DOSSIER_PI / "reglages") == 0
    assert CodeEcran(chemin, REGLAGES.code).verifier("8642")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("86\n"))
    assert lancer_code_ecran(["--code-sur-stdin"], chemin, DOSSIER_PI / "reglages") == 2
    assert "4 chiffres" in capsys.readouterr().err
    assert lancer_code_ecran(["--retirer"], chemin, DOSSIER_PI / "reglages") == 0
    assert not chemin.exists()


def test_commande_code_ecran_dans_le_programme(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDANGE_CODE_ECRAN", str(tmp_path / "code_ecran.yaml"))
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("1234\n"))
    assert principal(["code-ecran", "--code-sur-stdin"]) == 0
    assert (tmp_path / "code_ecran.yaml").exists()


# ------------------------------------------------------------------ les réglages


def test_fonction_inconnue_dans_les_reglages(reglages):
    remplacer(
        reglages / "programme.yaml",
        "fonctions_sensibles: [changer_mode,",
        "fonctions_sensibles: [reglages,",
    )
    assert "fonction « reglages » inconnue" in erreur_de(reglages)


@pytest.mark.parametrize("longueur", ["3", "7"])
def test_longueur_du_code_entre_4_et_6(reglages, longueur):
    remplacer(reglages / "programme.yaml", "longueur: 4 ", f"longueur: {longueur} ")
    assert "longueur" in erreur_de(reglages)


def test_fonction_ecrite_deux_fois(reglages):
    remplacer(
        reglages / "programme.yaml",
        "fonctions_sensibles: [changer_mode,",
        "fonctions_sensibles: [changer_mode, changer_mode,",
    )
    assert "écrite deux fois" in erreur_de(reglages)
