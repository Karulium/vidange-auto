"""Tests de la lecture des messages de FluidNC."""

from vidange.fluidnc.protocole import (
    classer_ligne,
    decrire_alarme,
    decrire_erreur,
    decrire_etat,
    lire_rapport_etat,
)


def test_rapport_simple():
    rapport = lire_rapport_etat("<Idle|MPos:1.000,-2.500,30.125|FS:0,0>")
    assert rapport is not None
    assert rapport.etat == "Idle"
    assert rapport.positions == {"X": 1.0, "Y": -2.5, "Z": 30.125}
    assert rapport.repere == "machine"
    assert rapport.vitesse == 0


def test_rapport_six_axes_avec_tout():
    rapport = lire_rapport_etat(
        "<Hold:0|MPos:1,2,3,4,5,6|FS:1500,0|WCO:0.000,0.000,1.000|Pn:XZ|Ov:100,100,100>"
    )
    assert rapport is not None
    assert rapport.etat == "Hold:0"
    assert rapport.positions == {"X": 1, "Y": 2, "Z": 3, "A": 4, "B": 5, "C": 6}
    assert rapport.vitesse == 1500
    assert rapport.decalage == {"X": 0, "Y": 0, "Z": 1}
    assert rapport.entrees_actives == "XZ"
    assert rapport.autres == {"Ov": "100,100,100"}


def test_rapport_en_repere_de_travail():
    rapport = lire_rapport_etat("<Run|WPos:1.0,2.0,3.0|F:500>")
    assert rapport is not None
    assert rapport.repere == "travail"
    assert rapport.vitesse == 500


def test_rapports_abimes():
    assert lire_rapport_etat("ok") is None
    assert lire_rapport_etat("<Idle|MPos:1.0,abc,3.0>") is None
    assert lire_rapport_etat("<Idle|FS:0,0>") is None  # pas de positions
    assert lire_rapport_etat("<Idle|MPos:1,2,3,4,5,6,7>") is None  # trop d'axes
    assert lire_rapport_etat("<Idle|MPos:1.0,2") is None  # coupé en route


def test_classer_les_lignes():
    assert classer_ligne("ok") == ("ok", None)
    assert classer_ligne("error:22") == ("erreur", 22)
    assert classer_ligne("ALARM:1") == ("alarme", 1)
    assert classer_ligne("<Idle|MPos:0,0,0>") == ("etat", None)
    assert classer_ligne("Grbl 3.7 [FluidNC v3.7.8 '$' for help]") == ("bienvenue", None)
    assert classer_ligne("[MSG:Caution: Unlocked]") == ("message", None)
    assert classer_ligne("n'importe quoi") == ("autre", None)


def test_descriptions_en_francais():
    assert decrire_alarme(1) == "alarme 1 : fin de course matérielle touchée"
    assert "documentation FluidNC" in decrire_alarme(99)
    assert decrire_erreur(9) == "erreur 9 : G-code refusé : carte en alarme ou bloquée"
    assert "documentation FluidNC" in decrire_erreur(99)
    assert decrire_etat("Hold:1") == "en pause"
    assert decrire_etat("Bizarre") == "Bizarre"
