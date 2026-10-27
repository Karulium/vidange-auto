"""Tests du chien de garde : cartes surveillées, chef figé, systemd, battement."""

import socket

import pytest

from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fiabilite import ChienDeGarde
from vidange.fiabilite.chien_de_garde import notifier_systemd
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.materiel import FausseFabrique, Materiel
from vidange.reglages import ReglagesChienDeGarde

from .conftest import DOSSIER_PI
from .test_fluidnc_liaison import DELAI, reglages_essai

REGLAGES = ReglagesChienDeGarde(periode_s=2, chef_fige_s=10)


class FauxChef:
    dernier_tour: float | None = None


class Horloge:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def materiel():
    liste = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
    fabrique = FausseFabrique(liste)
    with Materiel(liste, fabrique) as materiel:
        yield fabrique, materiel


def test_chef_vivant_puis_fige(materiel):
    fabrique, materiel = materiel
    horloge, chef, messages = Horloge(), FauxChef(), []
    gardien = ChienDeGarde(
        REGLAGES, {}, chef, materiel, notifier=lambda m: messages.append(m) or True, horloge=horloge
    )
    gardien.pret()
    assert messages == ["READY=1"]
    # Le chef n'a pas encore fait de tour : on lui laisse le temps de démarrer.
    gardien.tour()
    assert messages[-1] == "WATCHDOG=1"
    battements = [fabrique.commande("battement_pi")]
    for t in (1, 2, 3):
        chef.dernier_tour = horloge.t = t
        gardien.tour()
        battements.append(fabrique.commande("battement_pi"))
    assert battements == [True, False, True, False]
    assert messages.count("WATCHDOG=1") == 4

    horloge.t = 20  # plus de tour depuis 17 s
    gardien.tour()
    gardien.tour()
    assert messages.count("WATCHDOG=1") == 4  # systemd ne reçoit plus rien : il relancera
    assert fabrique.commande("battement_pi") is False  # le battement s'arrête aussi
    assert any(c.sujet == "chef d'orchestre" and c.niveau == "bloquant" for c in gardien.constats())

    gardien.arreter()
    assert messages[-1] == "STOPPING=1"


def test_cartes_surveillees():
    faux = FauxFluidnc()
    # Silence toléré long : un ordinateur d'essai lent ne doit pas faire croire à une coupure.
    reglages = reglages_essai(delai_silence_s=DELAI)
    with Liaison("portique", reglages, ouvrir=faux.ouvrir) as liaison:
        liaison.attendre_connexion(DELAI)
        gardien = ChienDeGarde(REGLAGES, {"portique": liaison}, notifier=lambda m: False)
        gardien.pret()
        constats = gardien.constats()
        assert [(c.sujet, c.niveau) for c in constats if c.sujet.startswith("carte")] == [
            ("carte « portique »", "ok")
        ]
        # Hors de systemd, sans battement : on le dit (inconnu, pas bloquant).
        assert {c.niveau for c in constats if c.sujet == "chien de garde"} == {"inconnu"}

        faux.redemarrer()
        liaison.attendre(lambda etat: etat.redemarrages == 1 and etat.en_alarme, DELAI)
        gardien.tour()
        constat = gardien.constats()[0]
        assert constat.niveau == "bloquant"
        assert "prise d'origine" in constat.quoi_faire

        liaison.debloquer().attendre(DELAI)
        liaison.attendre(lambda etat: not etat.en_alarme, DELAI)
        assert gardien.constats()[0].texte == "a redémarré toute seule 1 fois"

        faux.couper_cable()
        liaison.attendre(lambda etat: not etat.connectee, DELAI)
        assert gardien.constats()[0].texte == "pas connectée"


def test_notifier_systemd(tmp_path, monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert notifier_systemd("READY=1") is False
    adresse = str(tmp_path / "notify")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as prise:
        prise.bind(adresse)
        monkeypatch.setenv("NOTIFY_SOCKET", adresse)
        assert notifier_systemd("WATCHDOG=1") is True
        assert prise.recv(100) == b"WATCHDOG=1"
