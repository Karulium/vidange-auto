"""Dérive de position (tâche 24, point 3) : contrôle d'origine contre le fin de course, sur le
faux FluidNC qui sait glisser d'un nombre de mm donné."""

import pytest

from vidange.chef import Chef
from vidange.derive import ControleDerive
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.reglages import ReglagesChef, charger_reglages

from .conftest import DOSSIER_PI
from .test_chef_exemple import attendre
from .test_fluidnc_liaison import reglages_essai
from .test_reglages import erreur_de, remplacer

REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
FLUIDNC = REGLAGES.fluidnc.model_copy(update={"liaison": reglages_essai().liaison})
DELAI = 20
# Le fin de course d'origine du chariot Y est, pour FluidNC, à 37 mm (position_capteur).
CAPTEUR_MM = 37.0


def test_derive_est_inactive_dans_le_depot():
    derive = REGLAGES.machine.derive
    assert derive is not None and derive.exemple and not derive.actif
    # Inactif : pas de module.
    assert ControleDerive(REGLAGES.machine, {"portique": object()}).module() is None


def test_seuils_verifies_au_demarrage(reglages):
    remplacer(reglages / "machine.yaml", "      seuil_alerte: 0.002", "      seuil_alerte: 0.006")
    assert "seuil_alerte (0.006) doit être plus petit que seuil_arret (0.005)" in erreur_de(
        reglages
    )


def test_axe_de_derive_inconnu(reglages):
    remplacer(
        reglages / "machine.yaml",
        "  axes:\n    chariot_y:\n      position_capteur",
        "  axes:\n    chariot_z:\n      position_capteur",
    )
    assert "derive → axes → chariot_z : axe inconnu" in erreur_de(reglages)


@pytest.fixture
def banc():
    faux = FauxFluidnc(axes="XYZAB", vitesse_rapide_mm_min=30_000)
    faux.positions["Y"] = 300.0
    faux.definir_fin_de_course("Y", CAPTEUR_MM, "bas")
    liaison = Liaison("portique", FLUIDNC, ouvrir=faux.ouvrir)
    liaison.demarrer()
    liaison.attendre_connexion(DELAI)
    axe = REGLAGES.machine.derive.axes["chariot_y"].model_copy(update={"vitesse": 0.02})
    derive = REGLAGES.machine.derive.model_copy(update={"actif": True, "axes": {"chariot_y": axe}})
    machine = REGLAGES.machine.model_copy(update={"derive": derive})
    controle = ControleDerive(machine, {"portique": liaison})
    chef = Chef(machine, ReglagesChef(periode_s=0.01, alarme_pause_tout=False))
    chef.demarrer()
    try:
        yield faux, controle, chef
    finally:
        chef.arreter()
        liaison.arreter()


def jouer(chef, controle):
    module = controle.module()
    chef.lancer(module)
    attendre(lambda: chef.etat().modules[0].statut in ("fini", "alarme"), DELAI)
    return chef.etat().modules[0]


def test_aucune_derive(banc):
    faux, controle, chef = banc
    etat = jouer(chef, controle)
    assert etat.statut == "fini", etat.alarme
    assert controle.alertes == {} and controle.constats() == []
    assert abs(controle.mesures["chariot_y"].ecart) < 0.002


def test_petite_derive_alerte_sans_arreter(banc):
    faux, controle, chef = banc
    faux.glisser("Y", 3.0)  # la courroie a glissé de 3 mm : entre les deux seuils
    etat = jouer(chef, controle)
    assert etat.statut == "fini", etat.alarme
    ecart = controle.alertes["chariot_y"]
    assert 0.002 < ecart < 0.005
    (constat,) = controle.constats()
    assert constat.niveau == "attention" and "chariot_y" in constat.texte


def test_grande_derive_arrete_proprement(banc):
    faux, controle, chef = banc
    faux.glisser("Y", 8.0)
    etat = jouer(chef, controle)
    assert etat.statut == "alarme"
    assert "dérive de « chariot_y »" in etat.alarme.message
    assert "courroie" in etat.alarme.quoi_faire


def test_derive_dans_l_autre_sens_aussi(banc):
    faux, controle, chef = banc
    faux.glisser("Y", -8.0)
    etat = jouer(chef, controle)
    assert etat.statut == "alarme" and "dérive" in etat.alarme.message


def test_capteur_jamais_vu_arrete(banc):
    faux, controle, chef = banc
    faux.fins_de_course.clear()  # fin de course mort ou câble coupé
    etat = jouer(chef, controle)
    assert etat.statut == "alarme" and "jamais vu" in etat.alarme.message


def test_recalage_apres_la_mesure(banc):
    faux, controle, chef = banc
    controle.reglages = controle.reglages.model_copy(update={"recaler": True})
    faux.glisser("Y", 3.0)
    faux.origines["Y"] = 40.0
    etat = jouer(chef, controle)
    assert etat.statut == "fini", etat.alarme
    attendre(lambda: faux.prises_origine == ["Y"], DELAI)
    assert faux.glissement["Y"] == 0.0
