"""Le module d'exemple joué par le chef, sur le faux FluidNC et les faux capteurs (temps réel)."""

import time

import pytest

from vidange.chef import Axes, Carnet, Chef
from vidange.chef.exemple import module_exemple
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.materiel import FausseFabrique, Materiel
from vidange.reglages import ReglagesChef, charger_reglages

from .conftest import DOSSIER_PI
from .test_fluidnc_liaison import reglages_essai

DELAI = 5  # attente maximale dans les tests, en s (bien plus que nécessaire)


def attendre(condition, delai_s: float = DELAI) -> None:
    fin = time.monotonic() + delai_s
    while not condition():
        assert time.monotonic() < fin, "attente trop longue"
        time.sleep(0.01)


@pytest.fixture
def banc(tmp_path):
    """Le chef, le module d'exemple, une carte FluidNC fausse (rapide) et les faux capteurs."""
    reglages = charger_reglages(DOSSIER_PI / "reglages")
    liste = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
    fabrique = FausseFabrique(liste)
    faux = FauxFluidnc(vitesse_rapide_mm_min=300_000)  # 1 m en 0,2 s
    chef = Chef(
        reglages.machine,
        ReglagesChef(periode_s=0.01, alarme_pause_tout=True),
        Carnet(tmp_path / "etat-cycle.json"),
    )
    with (
        Materiel(liste, fabrique) as materiel,
        Liaison("portique", reglages_essai(), ouvrir=faux.ouvrir) as portique,
    ):
        portique.attendre_connexion(DELAI)
        module = module_exemple(Axes(reglages.machine, {"chariot": portique}), materiel)
        chef.demarrer()
        try:
            yield chef, module, faux, fabrique
        finally:
            chef.arreter()


def etat(chef):
    return chef.etat().modules[0]


def test_cycle_de_l_exemple(banc):
    chef, module, faux, fabrique = banc
    chef.lancer(module)
    attendre(lambda: etat(chef).attend == "panneau du poste du fût fermé")
    assert faux.positions == {"X": 0, "Y": 0, "Z": 0}

    fabrique.actionner("reed_panneau_poste_fut")
    attendre(lambda: chef.etat().attendent_go == ["exemple"])
    assert faux.positions == {"X": 800, "Y": 500, "Z": 1000}
    assert etat(chef).zones == ()

    chef.donner_go("exemple")
    attendre(lambda: etat(chef).statut == "fini")
    assert faux.positions == {"X": 800, "Y": 500, "Z": 1000}
    assert "G90 G0 X300.000 Y200.000 Z900.000" in faux.lignes_recues
    assert etat(chef).zones == ()


def test_alarme_de_la_carte_pendant_un_geste(banc):
    chef, module, faux, fabrique = banc
    fabrique.actionner("reed_panneau_poste_fut")
    faux.vitesse_rapide_mm_min = 6000  # lent : on a le temps de déclencher l'alarme
    chef.lancer(module)
    attendre(lambda: faux.en_mouvement)
    faux.declencher_alarme(1)
    attendre(lambda: etat(chef).statut == "alarme")
    alarme = etat(chef).alarme
    assert alarme.etape == "aller_au_repos"
    # Vue par la surveillance de la carte, ou par la ligne interrompue : les deux disent « alarme ».
    assert "alarme" in alarme.message.lower()
    assert chef.en_pause
