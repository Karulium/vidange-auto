"""Pilotage à distance : faux FluidNC (temps réel), faux voyant, horloge du pilote à la main."""

import time
from dataclasses import dataclass

import pytest

from vidange.chef import Chef
from vidange.distance import ErreurDistance, PiloteDistance
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.materiel import FausseFabrique, Materiel
from vidange.registre import Registre
from vidange.reglages import Machine, ReglagesDistance

from .conftest import DOSSIER_PI
from .test_chef import Banc, Horloge, module_simple, nouveau_chef
from .test_fluidnc_liaison import reglages_essai

DELAI = 5  # attente maximale dans les tests, en s (bien plus que nécessaire)
QUI = "page web (essai)"


def reglages(**valeurs) -> ReglagesDistance:
    return ReglagesDistance.model_validate(
        {
            "vitesse_max_m_s": 0.05,  # 50 mm/s : « avance » de 10 mm
            "battement_s": 0.1,
            "homme_mort_s": 0.5,
            "periode_s": 0.02,
            "avance_s": 0.2,
            "video_figee_s": 1,
            "voyant_avant_s": 3,
            "voyant_apres_s": 10,
            "inactivite_max_min": 1,
            **valeurs,
        }
    )


def machine() -> Machine:
    return Machine.model_validate(
        {
            "axes": {
                "x": {"longueur_rail": 1, "course": [0.0, 0.04], "carte": "portique", "lettre": "X"}
            }
        }
    )


class Images:
    """L'âge de l'image que la page dit afficher (réglé à la main)."""

    def __init__(self) -> None:
        self.age: float | None = 0.1

    def __call__(self, camera: str, numero: int) -> float | None:
        return self.age if camera == "plafond" else None


@dataclass
class BancDistance:
    pilote: PiloteDistance
    faux: FauxFluidnc
    fabrique: FausseFabrique
    horloge: Horloge
    images: Images
    chef: Chef
    registre: Registre
    liaison: Liaison

    @property
    def voyant(self) -> bool:
        return self.fabrique.commande("voyant_buzzer")

    def tenir(self, sens: int = 1) -> None:
        self.pilote.tenir(QUI, "x", sens, "plafond", 1)

    def tour(self, secondes: float = 0.02) -> None:
        self.horloge.t += secondes
        self.pilote.tour()

    def jusqu_a(self, condition, tenir: int | None = 1) -> None:
        """Fait tourner le pilote (en tenant le bouton si `tenir`) jusqu'à la condition."""
        fin = time.monotonic() + DELAI
        while not condition():
            assert time.monotonic() < fin, "attente trop longue"
            if tenir is not None:
                self.tenir(tenir)
            self.tour()
            time.sleep(0.01)

    def lancer(self) -> None:
        """Mode activé, bouton « + » tenu jusqu'à ce que l'axe bouge."""
        self.pilote.activer(QUI)
        self.attendre_le_voyant()
        self.jusqu_a(lambda: self.faux.positions["X"] > 1)

    def attendre_le_voyant(self) -> None:
        """Bouton tenu pendant « voyant_avant_s » (3 s)."""
        for _ in range(13):
            self.tenir()
            self.tour(0.25)

    def jusqu_a_l_arret(self) -> None:
        self.jusqu_a(lambda: not self.faux.en_mouvement and self.liaison.etat.etat == "Idle", None)

    def actions(self) -> list[str]:
        lignes = self.registre.lire("SELECT action FROM actions_distance ORDER BY id")
        return [ligne["action"] for ligne in lignes]


@pytest.fixture
def b(tmp_path):
    liste = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
    fabrique = FausseFabrique(liste)
    faux = FauxFluidnc()
    horloge = Horloge()
    images = Images()
    chef = nouveau_chef(horloge)
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    with (
        Materiel(liste, fabrique) as materiel,
        Liaison("portique", reglages_essai(), ouvrir=faux.ouvrir) as liaison,
    ):
        liaison.attendre_connexion(DELAI)
        pilote = PiloteDistance(
            reglages(), machine(), {"portique": liaison}, chef, materiel, images, registre, horloge
        )
        yield BancDistance(pilote, faux, fabrique, horloge, images, chef, registre, liaison)
        pilote.arreter()
    registre.fermer()


# ---------------------------------------------------------------- activer et quitter


def test_activer_met_la_machine_en_pause_et_note(b):
    assert b.pilote.refus() is None
    b.pilote.activer(QUI)
    assert b.pilote.actif and b.chef.en_pause
    assert b.pilote.etat()["qui"] == QUI
    b.pilote.quitter(QUI)
    assert not b.pilote.actif
    # Rien ne repart sans Go : la machine reste en pause.
    assert b.chef.en_pause
    assert "reste en pause" in b.pilote.message
    lignes = b.registre.lire("SELECT qui, action FROM actions_distance ORDER BY id")
    assert lignes == [{"qui": QUI, "action": "activer"}, {"qui": QUI, "action": "quitter"}]


def test_pas_de_mode_a_distance_pendant_un_geste(b):
    chef, horloge, banc = b.chef, b.horloge, Banc()
    chef.lancer(module_simple(banc))
    banc.drapeaux["pret"] = True
    horloge.t += 0.1
    chef.avancer()  # l'étape « un » est lancée, elle attend sa fin
    with pytest.raises(ErreurDistance, match="un geste du cycle est en cours"):
        b.pilote.activer(QUI)
    assert not b.pilote.actif and not chef.en_pause
    assert b.actions() == ["refus"]


def test_pas_de_mode_a_distance_avec_un_objet_encore_tenu(b):
    # Tâche 45 nonies : au redémarrage, objet encore tenu à la ventouse : aucun mouvement.
    b.chef.empecher_go(lambda: "objet encore tenu à la ventouse (vide -50 kPa)")
    with pytest.raises(ErreurDistance, match="objet encore tenu à la ventouse"):
        b.pilote.activer(QUI)
    assert not b.pilote.actif


def test_pas_de_mode_a_distance_sans_voyant(b):
    pilote = PiloteDistance(
        reglages(), machine(), {"portique": b.liaison}, b.chef, None, b.images, horloge=b.horloge
    )
    with pytest.raises(ErreurDistance, match="voyant"):
        pilote.activer(QUI)


def test_tenir_refuse_sans_le_mode(b):
    with pytest.raises(ErreurDistance, match="pas activé"):
        b.tenir()


def test_pas_de_mouvement_si_le_voyant_ne_s_allume_pas(b, monkeypatch):
    b.pilote.activer(QUI)

    # Le voyant-buzzer est sur un GPIO direct (le faux ne le débranche pas) : l'écriture échoue.
    def ecriture_impossible(nom, valeur):
        raise OSError("module relais du buzzer sans réponse")

    monkeypatch.setattr(b.pilote.materiel, "ecrire", ecriture_impossible)
    with pytest.raises(ErreurDistance, match="Voyant-buzzer impossible à allumer"):
        b.tenir()
    assert b.pilote.etat()["mouvement"] is None


def test_axe_inconnu_refuse(b):
    b.pilote.activer(QUI)
    with pytest.raises(ErreurDistance, match="inconnu"):
        b.pilote.tenir(QUI, "y", 1, "plafond", 1)


# ---------------------------------------------------------------- mouvement


def test_voyant_avant_puis_mouvement_puis_lache(b):
    b.pilote.activer(QUI)
    b.tenir()
    # Le voyant-buzzer sonne sur place ; l'axe attend « voyant_avant_s ».
    assert b.voyant
    assert b.pilote.etat()["mouvement"] == {
        "axe": "x",
        "sens": 1,
        "lance": False,
        "depart_dans_s": 3,
    }
    for _ in range(14):
        b.tenir()
        b.tour(0.2)
    assert not any(ligne.startswith("$J=") for ligne in b.faux.lignes_recues)
    b.tenir()
    b.tour(0.3)
    b.jusqu_a(lambda: b.faux.positions["X"] > 15)
    manuels = [ligne for ligne in b.faux.lignes_recues if ligne.startswith("$J=")]
    # Petits pas à la vitesse plafond (50 mm/s = 3000 mm/min), jamais plus de 10 mm d'avance.
    assert manuels[0] == "$J=G53 X10.000 F3000"
    assert len(manuels) >= 2
    assert b.voyant

    b.pilote.lacher(QUI)
    b.jusqu_a_l_arret()
    arret = b.faux.positions["X"]
    time.sleep(0.1)
    assert b.faux.positions["X"] == arret
    assert b.pilote.etat()["mouvement"] is None
    assert "bouton lâché" in b.pilote.message
    # Le voyant reste allumé un peu après le dernier mouvement, puis s'éteint.
    b.tour(1)
    assert b.voyant
    b.tour(10)
    assert not b.voyant
    assert b.actions() == ["activer", "mouvement", "arret"]
    detail = b.registre.lire("SELECT detail FROM actions_distance WHERE action = 'mouvement'")
    assert detail[0]["detail"] == "x vers +, depuis 0.0000 m"


def test_appuis_rapproches_sans_attendre_le_voyant(b):
    b.lancer()
    b.pilote.lacher(QUI)
    b.jusqu_a_l_arret()
    depart = b.faux.positions["X"]
    # Le voyant est encore allumé : l'axe repart tout de suite, dans l'autre sens.
    b.tenir(-1)
    assert b.pilote.etat()["mouvement"]["depart_dans_s"] == 0
    b.jusqu_a(lambda: b.faux.positions["X"] < depart - 1, tenir=-1)


def test_bout_de_course(b):
    b.lancer()
    b.jusqu_a(lambda: "bout de sa course" in b.pilote.message)
    b.jusqu_a_l_arret()
    # La course de machine.yaml (0,04 m) n'est jamais dépassée.
    assert b.faux.positions["X"] == pytest.approx(40)
    manuels = [ligne for ligne in b.faux.lignes_recues if ligne.startswith("$J=")]
    assert manuels[-1] == "$J=G53 X40.000 F3000"


def test_changement_de_sens(b):
    b.lancer()
    b.jusqu_a(lambda: b.faux.positions["X"] > 5)
    b.jusqu_a(lambda: b.faux.positions["X"] < 4, tenir=-1)
    assert b.pilote.etat()["mouvement"]["sens"] == -1
    assert b.actions() == ["activer", "mouvement", "arret", "mouvement"]


# ---------------------------------------------------------------- arrêts imposés


def test_homme_mort_connexion_coupee(b):
    b.lancer()
    # Plus de « je tiens » (bouton lâché sans le dire, connexion coupée...).
    b.tour(0.6)
    assert b.pilote.etat()["mouvement"] is None
    assert "plus de nouvelles de la page" in b.pilote.message
    b.jusqu_a_l_arret()
    # Il faut lâcher le bouton avant de repartir.
    with pytest.raises(ErreurDistance, match="Lâcher le bouton"):
        b.tenir()
    b.pilote.lacher(QUI)
    b.tenir()
    assert b.pilote.etat()["mouvement"] is not None


def test_video_figee(b):
    b.lancer()
    b.images.age = 3
    b.tour()
    assert b.pilote.etat()["mouvement"] is None
    assert "vidéo figée" in b.pilote.message
    b.jusqu_a_l_arret()
    b.pilote.lacher(QUI)
    with pytest.raises(ErreurDistance, match="Vidéo figée"):
        b.tenir()


def test_cable_coupe(b):
    b.lancer()
    b.faux.couper_cable()
    b.jusqu_a(lambda: b.pilote.etat()["mouvement"] is None)
    assert "carte « portique » coupée" in b.pilote.message
    assert b.actions()[-1] == "arret"
    # La carte, elle, n'a jamais plus de 10 mm d'avance : elle s'arrête seule.
    b.jusqu_a(lambda: not b.faux.en_mouvement, None)
    assert b.faux.positions["X"] <= 40


def test_pi_fige_l_axe_s_arrete_seul(b):
    b.lancer()
    depart = b.faux.positions["X"]
    # Le pilote ne tourne plus (Pi figé) : la carte finit ce qu'elle a, au plus 10 mm.
    fin = time.monotonic() + DELAI
    while b.faux.en_mouvement:
        assert time.monotonic() < fin
        time.sleep(0.01)
    assert b.faux.positions["X"] <= depart + 10.001


def test_pause_sur_place_reprend_la_main(b):
    b.lancer()
    b.liaison.pause()  # bouton de pause de l'armoire, câblé sur la carte
    b.jusqu_a(lambda: not b.pilote.actif)
    assert "carte « portique » en pause" in b.pilote.message
    assert b.actions()[-1] == "reprise_sur_place"


def test_carte_qui_annule_seule_le_deplacement(b):
    # Sur FluidNC, une pause pendant un déplacement manuel l'annule : la carte s'arrête avant
    # sa cible sans qu'on l'ait demandé.
    b.lancer()
    b.liaison.annuler_deplacement()
    b.jusqu_a(lambda: not b.pilote.actif)
    assert "arrêtée sur place" in b.pilote.message


def test_ecran_reprend_la_main(b):
    b.lancer()
    b.pilote.reprendre_la_main("écran de l'armoire")
    assert not b.pilote.actif
    b.jusqu_a_l_arret()
    assert "la main est reprise sur place (écran de l'armoire)" in b.pilote.message
    assert b.actions()[-2:] == ["arret", "reprise_sur_place"]


def test_machine_reprise_autrement(b):
    b.pilote.activer(QUI)
    b.chef.reprendre()
    b.tour()
    assert not b.pilote.actif
    assert "la machine a été reprise" in b.pilote.message


def test_fin_seule_sans_mouvement(b):
    b.pilote.activer(QUI)
    b.tour(59)
    assert b.pilote.actif
    b.tour(2)
    assert not b.pilote.actif
    assert "aucun mouvement depuis 1 min" in b.pilote.message


def test_carte_figee_par_la_pause_remise_au_repos(b):
    # Sur FluidNC, la pause de la machine met une carte au repos en « Hold » : sans geste en
    # cours, le pilote la remet au repos avant de la piloter.
    b.faux.en_pause = True
    b.liaison.attendre(lambda etat: etat.etat == "Hold:0", DELAI)
    b.lancer()
    assert b.pilote.actif


def test_geste_du_cycle_en_cours_sur_la_carte(b):
    b.liaison.envoyer("G4 P5")  # un geste du cycle qui n'est pas fini
    b.pilote.activer(QUI)
    with pytest.raises(ErreurDistance, match="Lâcher le bouton"):
        b.attendre_le_voyant()
    assert b.pilote.etat()["mouvement"] is None
    assert "un geste du cycle est en cours (1 ligne(s))" in b.pilote.message
    assert not any(ligne.startswith("$J=") for ligne in b.faux.lignes_recues)


def test_arret_du_programme(b):
    b.lancer()
    b.pilote.arreter()
    assert not b.pilote.actif and not b.voyant
    b.jusqu_a_l_arret()
