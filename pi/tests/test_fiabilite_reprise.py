"""Coupure de courant en plein geste, reprise au bon endroit, bilan d'une alarme.

Le module d'exemple, joué par le chef sur le faux FluidNC et les faux capteurs (temps réel).
"""

import json

import pytest

from vidange.chef import Axes, Carnet, Chef
from vidange.chef.exemple import module_exemple
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fiabilite import Bilans, module_lieu_sur
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.materiel import FausseFabrique, Materiel
from vidange.registre import Registre
from vidange.reglages import ReglagesBilan, ReglagesChef, charger_reglages

from .conftest import DOSSIER_PI
from .test_chef_exemple import attendre
from .test_fluidnc_liaison import DELAI, reglages_essai

REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")


class Machine:
    """Une « machine » : le faux FluidNC et les faux capteurs restent quand le Pi s'arrête."""

    def __init__(self, dossier) -> None:
        self.dossier = dossier
        self.faux = FauxFluidnc(vitesse_rapide_mm_min=300_000)
        self.fabrique = FausseFabrique(LISTE)
        self.carnet = Carnet(dossier / "etat-cycle.json")

    def allumer_le_pi(self):
        """Démarre un « programme du Pi » : liaison, matériel, chef (avec le même carnet)."""
        liaison = Liaison("portique", reglages_essai(), ouvrir=self.faux.ouvrir)
        liaison.demarrer()
        liaison.attendre_connexion(DELAI)
        materiel = Materiel(LISTE, self.fabrique)
        chef = Chef(
            REGLAGES.machine, ReglagesChef(periode_s=0.01, alarme_pause_tout=True), self.carnet
        )
        liaisons = {"portique": liaison}
        exemple = module_exemple(Axes(REGLAGES.machine, liaisons), materiel)
        lieu_sur = module_lieu_sur(REGLAGES.machine, liaisons)
        return Pi(liaison, materiel, chef, exemple, lieu_sur)


class Pi:
    def __init__(self, liaison, materiel, chef, exemple, lieu_sur) -> None:
        self.liaison, self.materiel, self.chef = liaison, materiel, chef
        self.exemple, self.lieu_sur = exemple, lieu_sur

    def module(self, nom):
        return next(m for m in self.chef.etat().modules if m.module == nom)

    def eteindre(self) -> None:
        self.chef.arreter()
        self.liaison.arreter()
        self.materiel.fermer()


@pytest.fixture
def machine(tmp_path):
    return Machine(tmp_path)


def test_coupure_en_plein_geste_puis_reprise(machine):
    pi = machine.allumer_le_pi()
    machine.fabrique.actionner("reed_panneau_poste_fut")
    pi.chef.lancer(pi.exemple)
    pi.chef.demarrer()
    attendre(lambda: pi.chef.etat().attendent_go == ["exemple"])
    pi.chef.memoriser("exemple", seau="S1293")
    machine.faux.vitesse_rapide_mm_min = 600  # lent : la coupure arrive pendant le geste
    pi.chef.donner_go("exemple")
    attendre(lambda: machine.faux.en_mouvement)

    # Coupure de courant : le Pi s'arrête net, la carte redémarre (position perdue).
    pi.chef.arreter()
    pi.liaison.arreter()
    machine.faux.redemarrer()
    machine.faux.vitesse_rapide_mm_min = 300_000

    pi = machine.allumer_le_pi()
    assert pi.chef.reprendre_cycle([pi.exemple, pi.lieu_sur]) == ["exemple"]
    assert pi.chef.memoire("exemple") == {"seau": "S1293"}  # reprise au bon seau
    pi.chef.lancer(pi.lieu_sur)
    pi.chef.demarrer()
    try:
        attendre(lambda: pi.chef.etat().attendent_go == ["lieu_sur"])
        assert pi.module("exemple").attend == "fin de « lieu_sur »"
        assert pi.module("exemple").etape == "entrer_dans_la_zone_a"

        pi.chef.donner_go("lieu_sur")
        attendre(lambda: pi.module("lieu_sur").statut == "fini")
        assert "$H" in machine.faux.lignes_recues
        assert machine.faux.positions == {"X": 800, "Y": 500, "Z": 1000}  # lieu sûr

        # Le module repris attend le Go, puis refait son étape depuis le début.
        attendre(lambda: pi.chef.etat().attendent_go == ["exemple"])
        pi.chef.donner_go("exemple")
        attendre(lambda: pi.module("exemple").statut == "fini")
        assert machine.faux.positions == {"X": 800, "Y": 500, "Z": 1000}
    finally:
        pi.eteindre()


def test_prise_d_origine_ratee(machine):
    pi = machine.allumer_le_pi()
    pi.chef.lancer(pi.lieu_sur)
    pi.chef.demarrer()
    try:
        attendre(lambda: pi.chef.etat().attendent_go == ["lieu_sur"])
        machine.faux.vitesse_rapide_mm_min = 600
        machine.faux.positions["X"] = 1000
        pi.chef.donner_go("lieu_sur")
        attendre(lambda: machine.faux.en_mouvement)
        machine.faux.declencher_alarme(9)
        attendre(lambda: pi.module("lieu_sur").statut == "alarme")
        alarme = pi.module("lieu_sur").alarme
        assert "prise d'origine" in alarme.message
        assert "fin de course" in alarme.quoi_faire
    finally:
        pi.eteindre()


def test_bilan_d_une_alarme_puis_acquittement(machine, tmp_path):
    pi = machine.allumer_le_pi()
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    journal = tmp_path / "journal.log"
    journal.write_text("".join(f"ligne {i}\n" for i in range(100)), encoding="utf-8")
    bilans = Bilans(
        tmp_path,
        ReglagesBilan(lignes_journal=3),
        registre,
        pi.chef,
        {"portique": pi.liaison},
        pi.materiel,
        lambda: [],
        journal,
    )
    bilans.collecteurs["essai"] = lambda: "en plus"
    recues = []
    pi.chef.sur_alarme += [bilans.recevoir, recues.append]
    machine.fabrique.actionner("reed_panneau_poste_fut")
    machine.faux.vitesse_rapide_mm_min = 600
    pi.chef.lancer(pi.exemple)
    pi.chef.demarrer()
    try:
        attendre(lambda: machine.faux.en_mouvement)
        pi.chef.memoriser("exemple", seau="S12")
        machine.faux.declencher_alarme(1)
        attendre(lambda: recues)
        numero = bilans.traiter(recues[0])

        alarme = registre.alarmes_ouvertes()[0]
        assert alarme["id"] == numero
        assert "fin de course" in alarme["quoi_faire"]
        bilan = json.loads((tmp_path / alarme["bilan"]).read_text(encoding="utf-8"))
        assert bilan["alarme"]["module"] == "exemple"
        assert bilan["memoire_du_module"] == {"seau": "S12"}
        assert bilan["cartes"]["portique"]["etat"] == "Alarm"
        assert set(bilan["cartes"]["portique"]["positions"]) == {"X", "Y", "Z"}
        assert bilan["entrees"]["reed_panneau_poste_fut"] is True
        assert bilan["sorties"]["voyant_buzzer"] is False
        assert bilan["ambiance"]["sht31_armoire"]["temperature_c"] == pytest.approx(25, abs=0.1)
        assert bilan["journal"] == ["ligne 97", "ligne 98", "ligne 99"]
        assert bilan["clip_video"] is None
        assert bilan["essai"] == "en plus"

        bilans.acquitter(numero, "karulium")
        assert pi.module("exemple").statut == "en_cours"
        assert registre.alarmes_ouvertes() == []
    finally:
        pi.eteindre()
        registre.fermer()
