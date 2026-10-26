"""Tests de la santé de l'informatique du Pi, avec de fausses sondes."""

import logging
import os
from datetime import datetime

import pytest

from vidange.fiabilite import Sante, Sondes
from vidange.fiabilite.constats import pire
from vidange.registre import Registre
from vidange.reglages import ReglagesSante

REGLAGES = ReglagesSante(
    periode_min=5,
    temperature_pi_attention_c=75,
    disque_libre_attention_go=50,
    disque_libre_minimum_go=5,
    memoire_libre_attention_mo=300,
    sauvegarde_age_max_h=30,
)
MAINTENANT = datetime(2026, 10, 26, 14, 0)


class Fausses:
    def __init__(self) -> None:
        self.temperature: float | None = 50
        self.alimentation: int | None = 0
        self.memoire: float | None = 2000
        self.disque = 500.0
        self.maintenant = MAINTENANT

    def sondes(self) -> Sondes:
        return Sondes(
            temperature_c=lambda: self.temperature,
            alimentation=lambda: self.alimentation,
            memoire_libre_mo=lambda: self.memoire,
            disque_libre_go=lambda dossier: self.disque,
            maintenant=lambda: self.maintenant,
        )


@pytest.fixture
def fausses() -> Fausses:
    return Fausses()


def par_sujet(constats):
    return {constat.sujet: constat for constat in constats}


def test_tout_va_bien_et_mesures_notees(tmp_path, fausses):
    copie = tmp_path / "registre-2026-10-26.sqlite"
    copie.write_bytes(b"copie")
    os.utime(copie, (MAINTENANT.timestamp() - 3600,) * 2)
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    try:
        sante = Sante(tmp_path, REGLAGES, registre, lambda: [copie], fausses.sondes())
        constats = sante.mesurer()
        assert pire(constats) == "ok"
        assert par_sujet(constats)["copie de secours"].texte == "dernière copie il y a 1 h"
        mesures = {m["nom"]: m["valeur"] for m in registre.lire("SELECT * FROM mesures")}
        assert mesures == {"temperature_pi": 50, "disque_libre": 500, "memoire_libre": 2000}
    finally:
        registre.fermer()


def test_seuils_depasses(tmp_path, fausses, caplog):
    fausses.temperature = 80
    fausses.alimentation = 0x50005  # tension trop faible maintenant
    fausses.memoire = 100
    fausses.disque = 20
    fausses.maintenant = datetime(1970, 1, 1)
    sante = Sante(tmp_path, REGLAGES, sondes=fausses.sondes())
    constats = par_sujet(sante.mesurer())
    assert constats["température du Pi"].niveau == "attention"
    assert constats["alimentation du Pi"].texte == "tension trop faible en ce moment"
    assert constats["mémoire du Pi"].niveau == "attention"
    assert constats["disque du Pi"].niveau == "attention"
    assert constats["heure du Pi"].niveau == "attention"
    assert "Vérifier le ventilateur" in caplog.text

    fausses.disque = 2
    assert par_sujet(sante.mesurer())["disque du Pi"].niveau == "bloquant"


def test_journal_seulement_quand_ca_change(tmp_path, fausses, caplog):
    caplog.set_level(logging.INFO, logger="vidange")
    sante = Sante(tmp_path, REGLAGES, sondes=fausses.sondes())
    fausses.temperature = 80
    sante.mesurer()
    sante.mesurer()
    assert caplog.text.count("température du Pi : 80 °C") == 1
    fausses.temperature = 50
    sante.mesurer()
    assert "température du Pi : revenu à la normale" in caplog.text


def test_sur_un_pc_rien_n_est_faux(tmp_path, fausses):
    fausses.temperature = fausses.alimentation = fausses.memoire = None
    constats = Sante(tmp_path, REGLAGES, sondes=fausses.sondes()).mesurer()
    assert pire(constats) == "inconnu"


def test_copie_de_secours_trop_vieille_ou_absente(tmp_path, fausses):
    copie = tmp_path / "registre-2026-10-20.sqlite"
    copie.write_bytes(b"copie")
    os.utime(copie, (MAINTENANT.timestamp() - 48 * 3600,) * 2)
    sante = Sante(tmp_path, REGLAGES, copies=lambda: [copie], sondes=fausses.sondes())
    assert par_sujet(sante.mesurer())["copie de secours"].niveau == "attention"

    # Pas de copie : rien à dire le premier jour, puis attention.
    temps = [0.0]
    sante = Sante(tmp_path, REGLAGES, sondes=fausses.sondes(), horloge=lambda: temps[0])
    assert par_sujet(sante.mesurer())["copie de secours"].niveau == "inconnu"
    temps[0] = 31 * 3600
    assert par_sujet(sante.mesurer())["copie de secours"].niveau == "attention"


def test_vraies_sondes_ne_plantent_pas(tmp_path):
    """Sur le PC des tests comme sur le Pi : une valeur, ou None."""
    sondes = Sondes()
    assert sondes.disque_libre_go(tmp_path) > 0
    for lire in (sondes.temperature_c, sondes.alimentation, sondes.memoire_libre_mo):
        valeur = lire()
        assert valeur is None or valeur >= 0
