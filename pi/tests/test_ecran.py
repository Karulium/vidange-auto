"""Tests de l'écran de l'armoire : vrai chef, vrai registre, faux écran Nextion, fausse horloge."""

import logging

import pytest

from vidange.ecran import Ecran, FauxNextion, LiaisonEcran
from vidange.ecran.ecran import couper, decouper
from vidange.ecran.protocole import couleur_565
from vidange.fiabilite import Bilans
from vidange.mode import ErreurMode, ModeMachine
from vidange.registre import Registre
from vidange.reglages import ErreurReglages, ReglagesBilan, charger_reglages

from .conftest import DOSSIER_PI
from .test_chef import Banc, Horloge, etat_de, module_simple, nouveau_chef, tour
from .test_reglages import remplacer

REGLAGES = charger_reglages(DOSSIER_PI / "reglages").programme.ecran
COULEURS = REGLAGES.couleurs


def fond(nom: str) -> int:
    return couleur_565(getattr(COULEURS, nom).fond)


class BancEcran:
    """Un chef avec le module d'essai lancé, un registre, et l'écran (faux) devant."""

    def __init__(self, dossier) -> None:
        self.horloge = Horloge()
        self.banc = Banc()
        self.chef = nouveau_chef(self.horloge)
        self.chef.lancer(module_simple(self.banc))
        self.registre = Registre(dossier / "registre.sqlite", dossier / "photos")
        self.bilans = Bilans(dossier, ReglagesBilan(lignes_journal=0), self.registre, self.chef)
        self.mode = ModeMachine(dossier / "mode.json", self.chef, self.registre)
        self.nextion = FauxNextion()
        self.liaison = LiaisonEcran(REGLAGES, self.nextion.ouvrir, horloge=self.horloge)
        self.ecran = Ecran(
            REGLAGES,
            self.liaison,
            self.chef,
            self.registre,
            self.bilans.acquitter,
            self.mode,
            horloge=self.horloge,
        )

    def tour(self, secondes: float = 0.2) -> None:
        """Un tour du chef et deux de l'écran (le second lit les réponses du premier)."""
        tour(self.chef, self.horloge, secondes)
        self.ecran.tour()
        self.ecran.tour()

    def appuyer(self, bouton: str) -> None:
        self.nextion.appuyer(bouton)
        self.tour()

    def jusqu_au_go(self) -> None:
        """Le module passe l'étape « un » et attend le Go de l'étape « deux »."""
        self.banc.drapeaux["pret"] = True
        self.tour()
        self.banc.drapeaux["essai.un_fini"] = True
        self.tour()
        self.tour()

    def texte(self, objet: str) -> str:
        return self.nextion.texte(objet)


@pytest.fixture
def b(tmp_path):
    banc = BancEcran(tmp_path)
    banc.tour()
    yield banc
    banc.registre.fermer()


@pytest.fixture
def caplog(caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("vidange"), "propagate", True)
    return caplog


# ---------------------------------------------------------------- page d'état


def test_page_d_etat_en_marche(b):
    assert b.nextion.page == "etat"
    assert b.texte("b_bandeau") == "EN MARCHE"
    assert b.nextion.couleur("b_bandeau") == fond("marche")
    assert b.texte("t_mode") == "Mode : Production"
    assert b.texte("t_module") == "essai, étape 1/2 : un"
    assert b.texte("t_attend").startswith("Attend : ")
    assert b.texte("b_go") == "GO" and b.nextion.couleur("b_go") == fond("inactif")
    assert b.texte("b_pause") == "PAUSE"


def test_seules_les_valeurs_changees_sont_renvoyees(b):
    b.nextion.ordres.clear()
    b.tour()
    assert [o for o in b.nextion.ordres if o != "sendme"] == []
    b.banc.drapeaux["pret"] = True
    b.tour()
    assert "page etat" not in b.nextion.ordres
    assert any(o.startswith("t_attend.txt=") for o in b.nextion.ordres)


def test_go_demande_une_confirmation(b):
    b.appuyer("b_go")
    assert b.texte("t_info") == "Aucun Go attendu."
    b.jusqu_au_go()
    assert b.texte("b_bandeau") == "ATTEND LE GO"
    assert b.nextion.couleur("b_go") == fond("go")
    b.appuyer("b_go")
    assert b.nextion.page == "confirmer"
    assert b.texte("t_question") == "Donner le Go à « essai » pour l'étape « deux » ?"
    # « Non » : rien ne se passe.
    b.appuyer("b_non")
    assert b.nextion.page == "etat"
    assert etat_de(b.chef).attend == "Go de Karulium"
    b.appuyer("b_go")
    b.appuyer("b_oui")
    assert b.nextion.page == "etat"
    b.tour()
    assert etat_de(b.chef).attend != "Go de Karulium"
    assert "essai.deux" in b.banc.appels


def test_une_question_sans_reponse_est_abandonnee(b):
    b.jusqu_au_go()
    b.appuyer("b_go")
    b.horloge.t += REGLAGES.confirmation_s + 1
    b.tour()
    assert b.nextion.page == "etat"
    # Un « Oui » tardif (reçu sur la page d'état) ne donne pas le Go.
    b.appuyer("b_oui")
    assert etat_de(b.chef).attend == "Go de Karulium"


def test_pause_tout_de_suite_reprise_apres_oui(b):
    b.appuyer("b_pause")
    assert b.chef.en_pause
    assert b.texte("b_bandeau") == "EN PAUSE"
    assert b.nextion.couleur("b_bandeau") == fond("pause")
    assert b.texte("b_pause") == "REPRENDRE"
    b.appuyer("b_pause")
    assert b.nextion.page == "confirmer"
    assert b.chef.en_pause
    b.appuyer("b_oui")
    assert not b.chef.en_pause
    assert b.texte("b_pause") == "PAUSE"


def test_bouton_inconnu_ignore(b, caplog):
    b.appuyer("b_oui")
    b.appuyer("b_lancer_fusee")
    assert b.nextion.page == "etat"
    assert "bouton « b_lancer_fusee » reçu sur la page « etat » : ignoré" in caplog.text


# ---------------------------------------------------------------- alarmes


def alarme_du_chef(b) -> int:
    """L'étape « un » dépasse son délai : alarme dans le chef, notée dans le registre."""
    b.banc.drapeaux["pret"] = True
    b.tour()
    tour(b.chef, b.horloge, 11)
    alarme = etat_de(b.chef).alarme
    return b.registre.noter_alarme("essai", alarme.message, alarme.quoi_faire, alarme.etape)


def test_une_alarme_fait_venir_sa_page_et_se_repare(b):
    numero = alarme_du_chef(b)
    b.tour()
    assert b.nextion.page == "alarme"
    assert b.texte("t_bandeau") == "ALARME 1/1 : essai"
    assert b.nextion.couleur("t_bandeau") == fond("alarme")
    assert b.texte("t_message")
    assert b.texte("t_quoi")
    # Retour à l'état : le bandeau rouge ramène à l'alarme.
    b.appuyer("b_retour")
    assert b.texte("b_bandeau") == "ALARME (1) : TOUCHER ICI"
    b.appuyer("b_bandeau")
    assert b.nextion.page == "alarme"
    b.appuyer("b_repare")
    assert b.registre.alarmes_ouvertes() == []
    (ligne,) = b.registre.lire("SELECT acquittee_par FROM alarmes WHERE id = ?", (numero,))
    assert ligne["acquittee_par"] == "écran de l'armoire"
    # Plus d'alarme : retour à l'état ; l'étape attend un nouveau Go.
    assert b.nextion.page == "etat"
    assert etat_de(b.chef).attend == "Go de Karulium"


def test_quoi_faire_long_en_morceaux_et_alarmes_suivantes(b):
    long = " ".join(f"mot{n}" for n in range(60))
    b.registre.noter_alarme("alimentation", "Courant coupé", long)
    b.registre.noter_alarme("programme", "Plantage", "Relancer.")
    b.tour()
    # La plus récente est montrée.
    assert b.texte("t_bandeau") == "ALARME 2/2 : programme"
    assert b.nextion.couleur("b_suite") == fond("inactif")
    b.appuyer("b_suivante")
    assert b.texte("t_bandeau") == "ALARME 1/2 : alimentation"
    morceaux = decouper(long, 80)
    assert len(morceaux) > 2
    assert b.texte("t_quoi") == morceaux[0]
    assert b.texte("t_suite").startswith(f"Suite 1/{len(morceaux)}, le ")
    b.appuyer("b_suite")
    assert b.texte("t_quoi") == morceaux[1]
    # La page d'alarme ne s'en va pas toute seule.
    b.horloge.t += REGLAGES.retour_accueil_s + 1
    b.tour()
    assert b.nextion.page == "alarme"


def test_decouper_et_couper():
    assert decouper("un deux trois", 8) == ["un deux", "trois"]
    assert decouper("abcdefghij", 4) == ["abcd", "efgh", "ij"]
    assert decouper("", 10) == [""]
    assert couper("abcdefghij", 6) == "abc..."
    assert couper("court", 6) == "court"


# ---------------------------------------------------------------- compteurs et mode


def test_compteurs(b):
    cycle = b.registre.commencer_cycle("essai", fut="F12")
    for seau in ("S1", "S2", "S3"):
        b.registre.ajouter_seau(cycle, seau)
    b.appuyer("b_compteurs")
    assert b.nextion.page == "compteurs"
    assert b.texte("t_seaux_jour") == "Seaux remplis aujourd'hui : 3"
    assert b.texte("t_seaux_fut") == "Seaux du fût en cours : 3"
    assert b.texte("t_futs_jour") == "Fûts vidés aujourd'hui : 0"
    assert b.texte("t_alarmes_jour") == "Alarmes aujourd'hui : 0"
    b.registre.finir_cycle(cycle)
    b.tour()
    assert b.texte("t_futs_jour") == "Fûts vidés aujourd'hui : 1"
    assert b.texte("t_seaux_fut") == "Pas de fût en cours"
    b.horloge.t += REGLAGES.retour_accueil_s + 1
    b.tour()
    assert b.nextion.page == "etat"


def test_changer_de_mode(b, tmp_path):
    b.appuyer("b_mode")
    assert b.nextion.page == "mode"
    assert b.nextion.couleur("b_production") == fond("mode")
    # Le module d'essai tourne : pas de changement de mode.
    b.appuyer("b_lavage")
    assert b.nextion.page == "mode"
    assert b.texte("t_info") == "Impossible : pas pendant un cycle (essai)."
    b.chef.abandonner("essai")
    b.appuyer("b_lavage")
    assert b.texte("t_question") == "Passer en mode Lavage ?"
    b.appuyer("b_oui")
    assert b.nextion.page == "mode"
    assert b.mode.actuel == "lavage"
    assert b.texte("t_titre") == "MODE : LAVAGE"
    b.appuyer("b_retour")
    assert b.texte("t_mode") == "Mode : Lavage"
    assert b.nextion.couleur("t_mode") == fond("mode")
    # Le mode survit à un redémarrage, et le changement est noté au registre.
    assert ModeMachine(tmp_path / "mode.json", b.chef).actuel == "lavage"
    (ligne,) = b.registre.lire("SELECT * FROM reglages_appliques")
    assert (ligne["qui"], ligne["ancien"], ligne["nouveau"]) == (
        "écran de l'armoire",
        '"production"',
        '"lavage"',
    )


def test_mode_refuse_pendant_un_cycle_meme_sans_l_ecran(b):
    with pytest.raises(ErreurMode, match="pas pendant un cycle"):
        b.mode.changer("uv_ozone", "essai")
    with pytest.raises(ErreurMode, match="mode inconnu"):
        b.mode.changer("turbo", "essai")


def test_fichier_du_mode_abime(b, tmp_path):
    (tmp_path / "abime.json").write_text("{pas du json", encoding="utf-8")
    assert ModeMachine(tmp_path / "abime.json", b.chef).actuel == "production"
    (tmp_path / "inconnu.json").write_text('{"mode": "turbo"}', encoding="utf-8")
    assert ModeMachine(tmp_path / "inconnu.json", b.chef).actuel == "production"


# ---------------------------------------------------------------- liaison


def test_l_ecran_redemarre_et_tout_lui_est_renvoye(b):
    assert b.texte("b_bandeau") == "EN MARCHE"
    b.nextion.redemarrer()
    assert b.texte("b_bandeau") == ""
    b.tour()
    assert b.texte("b_bandeau") == "EN MARCHE"
    assert b.texte("t_mode") == "Mode : Production"


def test_l_ecran_change_de_page_tout_seul(b):
    # Un redémarrage dont l'annonce s'est perdue : il répond à « sendme » par la page 0.
    b.appuyer("b_compteurs")
    b.nextion.page = "etat"
    b.nextion.valeurs = {}
    b.horloge.t += REGLAGES.presence_s
    b.tour()
    assert b.nextion.page == "compteurs"
    assert b.texte("t_titre") == "COMPTEURS"


def test_cable_coupe_puis_rebranche(b, caplog):
    assert b.liaison.constats()[0].niveau == "ok"
    b.nextion.debrancher()
    b.tour()
    assert "Écran : liaison coupée" in caplog.text
    assert b.liaison.constats()[0].niveau == "attention"
    # Le programme continue : le chef avance, l'écran attend.
    b.horloge.t += REGLAGES.reconnexion_s + 1
    b.tour()
    b.nextion.rebrancher()
    b.nextion.redemarrer()
    b.horloge.t += REGLAGES.reconnexion_s + 1
    b.tour()
    b.tour()
    assert b.nextion.ouvertures == 2
    assert b.liaison.en_ligne
    assert b.texte("b_bandeau") == "EN MARCHE"


def test_ecran_muet(b, caplog):
    caplog.set_level(logging.INFO, logger="vidange")
    b.nextion.muet = True
    b.horloge.t += REGLAGES.silence_s + 1
    b.tour()
    assert "Écran : il ne répond pas" in caplog.text
    assert not b.liaison.en_ligne
    (constat,) = b.liaison.constats()
    assert constat.niveau == "attention" and constat.texte == "il ne répond pas"
    b.nextion.muet = False
    b.horloge.t += REGLAGES.presence_s
    b.tour()
    assert b.liaison.en_ligne
    assert "Écran : il répond" in caplog.text


def test_port_impossible_a_ouvrir(tmp_path, caplog):
    banc = BancEcran(tmp_path)
    try:
        banc.nextion.debrancher()
        banc.tour()
        assert "port série impossible à ouvrir" in caplog.text
        (constat,) = banc.liaison.constats()
        assert constat.niveau == "attention" and "port série fermé" in constat.texte
        # Pas de nouvel essai avant « reconnexion_s ».
        banc.nextion.rebrancher()
        banc.tour()
        assert banc.nextion.ouvertures == 0
        banc.horloge.t += REGLAGES.reconnexion_s
        banc.tour()
        assert banc.nextion.ouvertures == 1
        assert banc.liaison.constats()[0].niveau == "ok"
    finally:
        banc.registre.fermer()


def test_erreur_de_l_ecran_notee_une_fois(b, caplog):
    # Une page montée dans Nextion Editor sans l'objet « t_info ».
    b.nextion._erreur(0x02)
    b.nextion._erreur(0x02)
    b.tour()
    assert caplog.text.count("objet inconnu sur la page") == 1


# ---------------------------------------------------------------- réglages


def test_reglages_de_l_ecran_verifies(reglages):
    programme = reglages / "programme.yaml"
    remplacer(programme, 'go: {fond: "#FFD000"', 'go: {fond: "jaune"')
    with pytest.raises(ErreurReglages, match="ecran → couleurs → go → fond : couleur à écrire"):
        charger_reglages(reglages)
    remplacer(programme, 'go: {fond: "jaune"', 'go: {fond: "#FFD000"')
    remplacer(programme, "silence_s: 6", "silence_s: 3")
    with pytest.raises(ErreurReglages, match=r"silence_s \(3 s\) doit valoir au moins 2 fois"):
        charger_reglages(reglages)


# ---------------------------------------------------------------- pilotage à distance


class PiloteEnCours:
    """Un pilotage à distance en cours, vu par l'écran."""

    def __init__(self) -> None:
        self.actif = True
        self.repris_par: list[str] = []

    def reprendre_la_main(self, qui: str) -> None:
        self.repris_par.append(qui)
        self.actif = False


def test_pilotage_a_distance_affiche_et_appui_reprend_la_main(b):
    b.jusqu_au_go()
    pilote = PiloteEnCours()
    b.ecran.pilote = pilote
    b.chef.pause()
    b.tour()
    assert b.texte("b_bandeau") == "À DISTANCE : TOUCHER = STOP"
    assert b.nextion.couleur("b_bandeau") == fond("distance")
    assert b.texte("t_info").startswith("Pilotage à distance en cours")
    # N'importe quel bouton (ici GO) reprend la main, et ne fait rien d'autre.
    b.appuyer("b_go")
    assert pilote.repris_par == ["écran de l'armoire"]
    assert b.nextion.page == "etat"
    assert b.texte("t_info") == "Pilotage à distance arrêté : la main est à l'armoire."
    assert b.chef.etat().attendent_go == ["essai"]
    assert b.texte("b_bandeau") == "EN PAUSE"
    # Ensuite, les boutons refont leur travail habituel.
    b.appuyer("b_go")
    assert b.nextion.page == "confirmer"
