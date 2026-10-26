"""Tests de l'arrêt propre sur onduleur, avec le faux signal de l'onduleur."""

import pytest

from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fiabilite import Onduleur
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel
from vidange.reglages import ReglagesOnduleur

from .conftest import DOSSIER_PI

REGLAGES = ReglagesOnduleur(periode_s=1, delai_avant_arret_s=60, commande_arret=["eteindre"])


class FauxChef:
    def __init__(self) -> None:
        self.pauses = 0

    def pause(self) -> None:
        self.pauses += 1


class Horloge:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def banc():
    liste = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
    fabrique = FausseFabrique(liste)
    with Materiel(liste, fabrique) as materiel:
        horloge, chef, arrets = Horloge(), FauxChef(), []
        onduleur = Onduleur(REGLAGES, materiel, chef, arrets.append, horloge)
        yield onduleur, fabrique, horloge, chef, arrets


def test_coupure_courte_la_machine_reste_en_pause(banc, caplog):
    onduleur, fabrique, horloge, chef, arrets = banc
    onduleur.tour()
    assert onduleur.constats()[0].niveau == "ok"
    fabrique.actionner("onduleur_sur_batterie")
    onduleur.tour()
    assert chef.pauses == 1
    assert onduleur.constats()[0].niveau == "bloquant"
    horloge.t = 30
    onduleur.tour()
    fabrique.actionner("onduleur_sur_batterie", False)
    onduleur.tour()
    assert "Courant revenu après 30 s. La machine reste en pause" in caplog.text
    assert chef.pauses == 1 and arrets == []


def test_coupure_longue_arret_propre(banc):
    onduleur, fabrique, horloge, chef, arrets = banc
    fabrique.actionner("onduleur_sur_batterie")
    onduleur.tour()
    horloge.t = 59
    onduleur.tour()
    assert arrets == []
    horloge.t = 60
    onduleur.tour()
    onduleur.tour()
    assert arrets == ["onduleur"]  # une seule fois


class MaterielMuet:
    branchements = {"onduleur_sur_batterie": None}

    def lire(self, nom):
        raise ErreurMateriel(f"signal « {nom} » : pas de réponse")


def test_sans_signal_ou_illisible():
    muet = Onduleur(REGLAGES, MaterielMuet(), None, lambda raison: None)
    muet.tour()
    assert muet.constats()[0].texte.startswith("illisible")
    sans = Onduleur(REGLAGES, None, None, lambda raison: None)
    sans.tour()
    assert "une coupure de courant arrête le Pi net" in sans.constats()[0].texte
