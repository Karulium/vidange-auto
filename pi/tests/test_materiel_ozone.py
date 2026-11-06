"""Tests des capteurs d'ozone ZE25-O3 (trames, somme de contrôle, muet, plafond) avec le faux."""

import pytest

from vidange.entrees_sorties import CapteurOzone, charger_entrees_sorties
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel
from vidange.materiel.ozone import CapteurMuet, LecteurOzone, texte_ppm
from vidange.trame_ze25 import (
    construire_trame,
    somme_de_controle,
    trame_avec_valeur,
    trame_valable,
    valeur_brute,
)

from .test_reglages import remplacer

POSITIONS = (4, 5)
QUESTION = construire_trame({1: 0x01, 2: 0x86})


def reglage(**champs):
    base = {
        "mode": "envoi_automatique",
        "pas_ppm": 0.01,
        "plafond_ppm": 10,
        "delai_muet_s": 5,
        "position_valeur": POSITIONS,
    }
    return CapteurOzone(**{**base, **champs})


class FauxPort:
    """Un port série à la main : ce qu'on y met arrive au Pi."""

    def __init__(self):
        self.arrive = bytearray()
        self.ecrit = []

    @property
    def in_waiting(self):
        return len(self.arrive)

    def read(self, nombre):
        morceau = bytes(self.arrive[:nombre])
        del self.arrive[:nombre]
        return morceau

    def write(self, donnees):
        self.ecrit.append(donnees)

    def reset_input_buffer(self):
        self.arrive.clear()

    def close(self):
        pass


class Horloge:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def lecteur_avec(port, **champs):
    horloge = Horloge()
    lecteur = LecteurOzone(lambda: port, reglage(**champs), nom="ozone_x", horloge=horloge)
    lecteur._port = port  # déjà ouvert : l'ouverture vide ce qui attendait dans le port
    return lecteur, horloge


# ------------------------------------------------------------ les trames


def test_somme_de_controle_connue():
    # La question « lire la valeur » de la notice Winsen : FF 01 86 00 00 00 00 00 79.
    assert somme_de_controle(bytes.fromhex("FF0186000000000079")) == 0x79
    assert trame_valable(bytes.fromhex("FF0186000000000079"))
    assert construire_trame({1: 1, 2: 0x86}) == bytes.fromhex("FF0186000000000079")


def test_trame_fausse_ou_mal_formee():
    bonne = trame_avec_valeur(123, POSITIONS)
    assert trame_valable(bonne) and valeur_brute(bonne, POSITIONS) == 123
    assert not trame_valable(bonne[:-1] + bytes([bonne[-1] ^ 1]))
    assert not trame_valable(b"\x00" + bonne[1:])
    assert not trame_valable(bonne[:8])


# ------------------------------------------------- lecture, envoi automatique


def test_trame_bonne():
    port = FauxPort()
    lecteur, _ = lecteur_avec(port)
    port.arrive += trame_avec_valeur(85, POSITIONS)
    mesure = lecteur.lire()
    assert mesure.ppm == pytest.approx(0.85)
    assert not mesure.au_plafond and mesure.trames_ignorees == 0
    assert texte_ppm(mesure, 10) == "0,85 ppm"


def test_somme_fausse_ignoree_et_comptee():
    port = FauxPort()
    lecteur, _ = lecteur_avec(port)
    port.arrive += trame_avec_valeur(85, POSITIONS)
    lecteur.lire()
    mauvaise = bytearray(trame_avec_valeur(999, POSITIONS))
    mauvaise[8] ^= 0xFF
    port.arrive += mauvaise
    mesure = lecteur.lire()
    assert mesure.ppm == pytest.approx(0.85)  # l'ancienne valeur reste
    assert mesure.trames_ignorees == 1


def test_trame_coupee_puis_la_suite():
    port = FauxPort()
    lecteur, _ = lecteur_avec(port)
    trame = trame_avec_valeur(120, POSITIONS)
    port.arrive += trame[:5]
    with pytest.raises(ErreurMateriel, match="en attente de la première trame"):
        lecteur.lire()
    port.arrive += trame[5:]  # la fin arrive : la trame est complète
    assert lecteur.lire().ppm == pytest.approx(1.2)


def test_trame_coupee_suivie_d_une_trame_entiere():
    port = FauxPort()
    lecteur, _ = lecteur_avec(port)
    port.arrive += trame_avec_valeur(120, POSITIONS)[:5] + trame_avec_valeur(300, POSITIONS)
    mesure = lecteur.lire()
    assert mesure.ppm == pytest.approx(3.0)  # le Pi se recale sur la trame entière
    assert mesure.trames_ignorees >= 1


def test_octets_de_travers_avant_la_trame():
    port = FauxPort()
    lecteur, _ = lecteur_avec(port)
    port.arrive += b"\x12\x34" + trame_avec_valeur(50, POSITIONS)
    assert lecteur.lire().ppm == pytest.approx(0.5)


def test_capteur_muet_apres_le_delai():
    port = FauxPort()
    lecteur, horloge = lecteur_avec(port, delai_muet_s=5)
    port.arrive += trame_avec_valeur(85, POSITIONS)
    lecteur.lire()
    horloge.t = 4
    assert lecteur.lire().age_s == 4  # pas encore muet : la dernière valeur reste valable
    horloge.t = 6
    with pytest.raises(CapteurMuet, match="ozone_x : muet"):
        lecteur.lire()
    port.arrive += trame_avec_valeur(90, POSITIONS)  # il reparle : la mesure revient
    assert lecteur.lire().ppm == pytest.approx(0.9)


def test_muet_depuis_le_depart():
    port = FauxPort()
    lecteur, horloge = lecteur_avec(port)
    with pytest.raises(ErreurMateriel, match="en attente"):
        lecteur.lire()
    horloge.t = 6
    with pytest.raises(CapteurMuet, match="aucune trame valable depuis 5 s"):
        lecteur.lire()


def test_valeur_au_plafond():
    port = FauxPort()
    lecteur, _ = lecteur_avec(port)
    port.arrive += trame_avec_valeur(1000, POSITIONS)  # 10,00 ppm
    mesure = lecteur.lire()
    assert mesure.au_plafond
    assert texte_ppm(mesure, 10) == "≥ 10 ppm"
    port.arrive += trame_avec_valeur(999, POSITIONS)  # 9,99 : pas au plafond
    mesure = lecteur.lire()
    assert not mesure.au_plafond and texte_ppm(mesure, 10) == "9,99 ppm"


# ------------------------------------------------------- question-réponse


def test_question_reponse():
    port = FauxPort()
    champs = {"mode": "question_reponse", "question": QUESTION, "position_valeur": (2, 3)}
    lecteur, _ = lecteur_avec(port, **champs)
    # Le port ne répond que si on lui pose la bonne question.
    ancien_write = port.write

    def write(donnees):
        ancien_write(donnees)
        if donnees == QUESTION:
            port.arrive += trame_avec_valeur(250, (2, 3))

    port.write = write
    assert lecteur.lire().ppm == pytest.approx(2.5)
    assert port.ecrit == [QUESTION]


def test_question_reponse_reponse_coupee():
    port = FauxPort()
    champs = {"mode": "question_reponse", "question": QUESTION, "position_valeur": (2, 3)}
    lecteur, horloge = lecteur_avec(port, **champs)
    port.write = lambda donnees: port.arrive.extend(trame_avec_valeur(250, (2, 3))[:6])
    with pytest.raises(ErreurMateriel, match="en attente"):
        lecteur.lire()
    assert lecteur.trames_ignorees == 1
    horloge.t = 6
    with pytest.raises(CapteurMuet):
        lecteur.lire()


# --------------------------------------- avec le faux matériel et Materiel


@pytest.fixture
def faux_et_materiel(entrees_sorties):
    liste = charger_entrees_sorties(entrees_sorties)
    faux = FausseFabrique(liste)
    with Materiel(liste, faux) as materiel:
        yield faux, materiel


def test_deux_capteurs_independants(faux_et_materiel):
    faux, materiel = faux_et_materiel
    faux.regler("ozone_dedans", 4.2)
    faux.regler("ozone_dehors", 0.3)
    assert materiel.lire_ozone("ozone_dedans").ppm == pytest.approx(4.2)
    assert materiel.lire_ozone("ozone_dehors").ppm == pytest.approx(0.3)
    # Deux adaptateurs, deux ports ouverts séparément.
    assert faux.capteur_ozone("ozone_dedans") is not faux.capteur_ozone("ozone_dehors")
    assert faux.capteur_ozone("ozone_dedans").ouvertures == 1


def test_un_muet_l_autre_lu(faux_et_materiel):
    faux, materiel = faux_et_materiel
    faux.regler("ozone_dehors", 0.3)
    faux.regler("ozone_dedans", 1.0)
    materiel.lire_ozone("ozone_dedans")  # il a parlé une fois, puis plus rien
    faux.capteur_ozone("ozone_dedans").muet = True
    materiel._ozones["ozone_dedans"]._horloge = lambda: 1e9  # bien après le délai
    with pytest.raises(CapteurMuet, match="signal « ozone_dedans »"):
        materiel.lire_ozone("ozone_dedans")
    assert materiel.lire_ozone("ozone_dehors").ppm == pytest.approx(0.3)
    faux.capteur_ozone("ozone_dedans").muet = False
    materiel._ozones["ozone_dedans"]._horloge = lambda: 1e9 + 1
    faux.regler("ozone_dedans", 1.5)
    assert materiel.lire_ozone("ozone_dedans").ppm == pytest.approx(1.5)


def test_trame_abimee_sur_un_seul_capteur(faux_et_materiel):
    faux, materiel = faux_et_materiel
    faux.regler("ozone_dedans", 1.0)
    faux.regler("ozone_dehors", 2.0)
    materiel.lire_ozone("ozone_dedans")  # ouvre le port
    faux.capteur_ozone("ozone_dedans").injecter(b"\xff\x01\x02")
    mesure = materiel.lire_ozone("ozone_dedans")
    assert mesure.ppm == pytest.approx(1.0)
    assert mesure.trames_ignorees == 1
    assert materiel.lire_ozone("ozone_dehors").trames_ignorees == 0


def test_valeur_au_plafond_avec_le_faux(faux_et_materiel):
    faux, materiel = faux_et_materiel
    faux.regler(
        "ozone_dedans", 14
    )  # le capteur ne dépasse pas sa pleine échelle... le Pi le dit « ≥ »
    mesure = materiel.lire_ozone("ozone_dedans")
    assert mesure.au_plafond
    assert materiel.mesurer("ozone_dedans") >= 10


def test_adaptateur_debranche_puis_rebranche(faux_et_materiel):
    faux, materiel = faux_et_materiel
    faux.regler("ozone_dedans", 1.0)
    materiel.lire_ozone("ozone_dedans")
    faux.capteur_ozone("ozone_dedans").cable_coupe = True
    with pytest.raises(ErreurMateriel, match="port série en panne"):
        materiel.lire_ozone("ozone_dedans")
    faux.capteur_ozone("ozone_dedans").cable_coupe = False
    assert materiel.lire_ozone("ozone_dedans").ppm == pytest.approx(1.0)


def test_question_reponse_avec_le_faux(entrees_sorties):
    remplacer(entrees_sorties, "mode: envoi_automatique ", "mode: question_reponse")
    remplacer(
        entrees_sorties,
        "      delai_muet_s: 5 ",
        '      question: "FF0186000000000079"\n      delai_muet_s: 5 ',
    )
    remplacer(entrees_sorties, "position_valeur: [4, 5]", "position_valeur: [2, 3]")
    liste = charger_entrees_sorties(entrees_sorties)
    faux = FausseFabrique(liste)
    with Materiel(liste, faux) as materiel:
        faux.regler("ozone_dedans", 2.5)
        assert materiel.lire_ozone("ozone_dedans").ppm == pytest.approx(2.5)
