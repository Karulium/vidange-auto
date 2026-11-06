"""Nettoyage (tâche 38) : store, purge après fermeture, nuit UV-ozone, fuite, mode maïs."""

import logging
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from vidange.api.app import Services, creer_app
from vidange.chef import Etape, Module
from vidange.demarrage import cycle_tourne, preparer_nettoyage
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.materiel import FausseFabrique, Materiel
from vidange.mode import ErreurMode, ModeMachine
from vidange.nettoyage import ErreurNettoyage, FausseConsigne, FauxCapteur, Nettoyage
from vidange.nettoyage.nettoyage import (
    CONTACT,
    ERREUR,
    FERME,
    FINI,
    GENERATION,
    INCONNU,
    OUVERT,
    RETOUR,
)
from vidange.nettoyage.simulation import (
    module_fermeture_purge,
    module_fuite,
    module_nuit,
    module_purge_trop_longue,
    nettoyage_du_simulateur,
)
from vidange.registre import Registre
from vidange.reglages import charger_reglages
from vidange.remplissage.simulation import remplissage_du_simulateur
from vidange.simulateur import ErreurSimulation, Simulateur
from vidange.simulateur.outil import SCENARIOS, main

from .conftest import DOSSIER_PI
from .test_api import CLE, LOCAL, reglages_api
from .test_chef import Horloge, nouveau_chef
from .test_reglages import erreur_de, remplacer

LISTE = DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
NETTOYAGE = REGLAGES.machine.nettoyage
assert NETTOYAGE is not None
PURGE = NETTOYAGE.purge
OZONE = NETTOYAGE.ozone


class Jour:
    """Une fausse heure du jour, qui avance avec l'horloge du banc."""

    def __init__(self, horloge: Horloge, depart: datetime) -> None:
        self.horloge = horloge
        self.depart = depart

    def __call__(self) -> datetime:
        return self.depart + timedelta(seconds=self.horloge.t)


class Banc:
    """Le vrai Nettoyage sur le faux matériel, avec un vrai registre et une fausse horloge."""

    def __init__(self, dossier, fichier=True, debut=datetime(2026, 11, 6, 10, 0)) -> None:
        self.dossier = dossier
        self.horloge = Horloge()
        self.jour = Jour(self.horloge, debut)
        liste = charger_entrees_sorties(LISTE)
        self.faux = FausseFabrique(liste)
        self.materiel = Materiel(liste, self.faux)
        self.registre = Registre(dossier / "registre.sqlite", dossier / "photos")
        self.mode = "production"
        self.cycle = False
        self.pauses = 0
        self.dedans = FauxCapteur("particules_dedans", "µg/m³", 40.0)
        self.dehors = FauxCapteur("particules_dehors", "µg/m³", 12.0)
        self.pression = FauxCapteur("pression_enceinte", "Pa", 0.0)
        self.consigne = FausseConsigne()
        self.fichier = dossier / "nettoyage.json" if fichier else None
        self.faux.regler("ozone_dedans", 0.0)
        self.faux.regler("ozone_dehors", 0.0)
        self.n = self.nouveau()

    def nouveau(self) -> Nettoyage:
        """Un Nettoyage neuf (comme après un redémarrage du Pi), sur le même matériel."""
        return Nettoyage(
            NETTOYAGE,
            self.materiel,
            self.fichier,
            self.registre,
            mode=lambda: self.mode,
            cycle_tourne=lambda: self.cycle,
            pause=self._pause,
            particules_dedans=self.dedans,
            particules_dehors=self.dehors,
            pression=self.pression,
            consigne=self.consigne,
            horloge=self.horloge,
            maintenant=self.jour,
        )

    def _pause(self) -> None:
        self.pauses += 1

    def avancer(self, secondes: float, pas: float = 1.0) -> None:
        fin = self.horloge.t + secondes
        while self.horloge.t < fin - 1e-9:
            self.horloge.t = min(fin, self.horloge.t + pas)
            self.n.observer()

    def store(self, ferme: bool, attendre: float = 3.0) -> None:
        self.faux.actionner("store_ferme", ferme)
        self.avancer(attendre)

    def commande(self, nom: str) -> bool:
        return self.faux.commande(nom)

    def bon_air(self) -> None:
        """Particules au niveau du dehors, surpression atteinte."""
        self.dedans.valeur = 12.0
        self.pression.valeur = 10.0

    def alarmes(self) -> list[str]:
        return [alarme["message"] for alarme in self.registre.alarmes_ouvertes()]

    def preparer_nuit(self) -> None:
        """Store fermé, purge finie, mode UV-ozone, panneau du poste levé, porte du spray fermée."""
        self.faux.actionner("reed_panneau_poste_fut", True)
        self.store(True)
        self.bon_air()
        self.avancer(PURGE.duree_min_s + 5)
        assert not self.n.purge_en_cours
        self.mode = "uv_ozone"
        self.avancer(1)


@pytest.fixture
def b(tmp_path):
    banc = Banc(tmp_path)
    yield banc
    banc.registre.fermer()


# ------------------------------------------------------------------ le store


def test_store_ferme_au_demarrage_puis_purge(b):
    b.avancer(1)
    assert b.n.etat().store == INCONNU
    b.store(True)
    etat = b.n.etat()
    assert etat.store == FERME and etat.purge and etat.ventilateur == "plein"
    assert b.commande("ventilateur_enceinte") and b.consigne.volts == NETTOYAGE.ventilateur.plein_v
    assert not b.commande("verrous_store")


def test_ouvrir_le_store_libere_les_verrous_puis_remis_apres_2_s_stables(b):
    b.store(True)
    b.bon_air()
    b.avancer(PURGE.duree_min_s + 5)
    assert not b.n.purge_en_cours
    b.n.demander_ouverture("essai")
    assert b.commande("verrous_store")
    b.store(False)
    assert b.n.etat().store == OUVERT
    assert b.commande("verrous_store")
    # La barre arrive sur le seuil : le reed rebondit, les verrous restent libres.
    for _ in range(3):
        b.faux.actionner("store_ferme", True)
        b.avancer(0.5, pas=0.5)
        b.faux.actionner("store_ferme", False)
        b.avancer(0.3, pas=0.3)
    assert b.commande("verrous_store")
    b.faux.actionner("store_ferme", True)
    b.avancer(1.5, pas=0.5)
    assert b.commande("verrous_store"), "pas encore 2 s stables"
    b.avancer(1, pas=0.5)
    assert not b.commande("verrous_store")
    assert b.n.purge_en_cours


def test_ouverture_refusee_pendant_un_cycle_la_purge_et_l_ozone(b):
    b.store(True)
    with pytest.raises(ErreurNettoyage, match="purge en cours"):
        b.n.demander_ouverture("essai")
    b.bon_air()
    b.avancer(PURGE.duree_min_s + 5)
    b.cycle = True
    with pytest.raises(ErreurNettoyage, match="pendant un cycle"):
        b.n.demander_ouverture("essai")
    b.cycle = False
    b.mode = "uv_ozone"
    b.faux.regler("ozone_dedans", 0.5)
    b.avancer(1)
    with pytest.raises(ErreurNettoyage, match="0,50 ppm"):
        b.n.demander_ouverture("essai")
    b.faux.regler("ozone_dedans", 12)
    b.avancer(1)
    with pytest.raises(ErreurNettoyage, match="≥ 10 ppm"):
        b.n.demander_ouverture("essai")
    b.faux.regler("ozone_dedans", 0.05)
    b.avancer(1)
    b.n.demander_ouverture("essai")
    assert b.commande("verrous_store")


def test_verrous_remis_si_le_store_n_est_pas_ouvert(b):
    b.store(True)
    b.bon_air()
    b.avancer(PURGE.duree_min_s + 5)
    b.n.demander_ouverture("essai")
    b.avancer(NETTOYAGE.store.deverrouille_max_s + 2)
    assert not b.commande("verrous_store")
    assert not b.n.purge_en_cours


def test_store_ouvert_pas_de_mouvement_et_condition_du_chef(b):
    horloge = Horloge()
    chef = nouveau_chef(horloge)
    chef.conditions_generales.append(b.n.condition_store)
    faits = []
    chef.lancer(Module("essai", (Etape("un", "Rien.", action=lambda: faits.append("un")),)))
    b.store(False)
    chef.avancer()
    assert not faits
    assert chef.etat().modules[0].attend == "store de l'enceinte fermé"
    b.store(True)
    chef.avancer()
    assert faits == ["un"]


def test_store_qui_retombe_pendant_un_cycle_alerte_et_pause(b):
    b.store(True)
    b.cycle = True
    b.store(False)
    assert b.pauses == 1
    assert any("Store mal fermé" in message for message in b.alarmes())
    assert b.n.etat().store_mal_ferme


def test_store_mal_ferme_apres_la_demande_de_fermeture(b):
    b.store(False)
    b.n.demander_fermeture("essai")
    b.avancer(NETTOYAGE.store.alerte_fermeture_s + 2)
    assert any("pas fermé" in message for message in b.alarmes())
    assert not b.n.purge_en_cours
    b.store(True)
    assert b.n.purge_en_cours and not b.n.etat().store_mal_ferme


def test_store_illisible_ni_ouvert_ni_ferme(b, monkeypatch):
    b.store(True)
    assert b.n.purge_en_cours

    def illisible(nom):
        from vidange.materiel import ErreurMateriel

        raise ErreurMateriel("carte d'entrées muette")

    monkeypatch.setattr(b.materiel, "lire", illisible)
    b.avancer(3)
    etat = b.n.etat()
    assert etat.store == INCONNU and not b.n.store_permet_les_mouvements()
    assert not etat.verrous_liberes, "jamais déverrouillé parce qu'un capteur est illisible"


# ------------------------------------------------------------------ la purge


def test_purge_finie_seulement_avec_les_3_conditions(b):
    b.store(True)
    # Durée atteinte, mais particules trop hautes et pas de surpression.
    b.avancer(PURGE.duree_min_s + 5)
    assert b.n.purge_en_cours
    etat = b.n.etat()
    assert etat.purge_duree_ok and not etat.purge_particules_ok and not etat.purge_pression_ok
    # Particules bonnes, mais pas encore stables 1 min ; toujours pas de pression.
    b.dedans.valeur = 18.0  # ≤ 1,5 × 12
    b.avancer(PURGE.stabilite_particules_s + 2)
    etat = b.n.etat()
    assert b.n.purge_en_cours and etat.purge_particules_ok and not etat.purge_pression_ok
    b.pression.valeur = PURGE.pression_fin - 0.5
    b.avancer(2)
    assert b.n.purge_en_cours
    b.pression.valeur = PURGE.pression_fin
    b.avancer(2)
    assert not b.n.purge_en_cours
    assert b.consigne.volts == NETTOYAGE.ventilateur.normal_v


def test_particules_stables_une_minute(b):
    b.store(True)
    b.pression.valeur = 10.0
    b.avancer(PURGE.duree_min_s)
    b.dedans.valeur = 12.0
    b.avancer(PURGE.stabilite_particules_s - 10)
    b.dedans.valeur = 30.0  # remonte : le chrono repart
    b.avancer(2)
    b.dedans.valeur = 12.0
    b.avancer(PURGE.stabilite_particules_s - 10)
    assert b.n.purge_en_cours
    b.avancer(15)
    assert not b.n.purge_en_cours


def test_purge_trop_longue_alerte_puis_passer_outre(b):
    b.store(True)
    b.avancer(PURGE.alerte_s + 2)
    assert b.n.purge_en_cours and b.n.etat().purge_alerte
    alertes = [m for m in b.alarmes() if "Purge pas finie" in m]
    assert len(alertes) == 1
    b.avancer(60)
    assert len([m for m in b.alarmes() if "Purge pas finie" in m]) == 1
    b.n.passer_outre("essai")
    assert not b.n.purge_en_cours
    with pytest.raises(ErreurNettoyage):
        b.n.passer_outre("essai")


def test_capteur_muet_jamais_fini(b):
    b.store(True)
    b.bon_air()
    b.dehors.muet = True
    b.avancer(PURGE.alerte_s + 5)
    assert b.n.purge_en_cours and b.n.etat().purge_alerte
    assert not b.n.etat().purge_particules_ok


def test_sans_capteurs_la_purge_n_est_jamais_finie(tmp_path):
    banc = Banc(tmp_path)
    banc.n.particules_dedans = banc.n.particules_dehors = banc.n.capteur_pression = None
    banc.store(True)
    banc.avancer(PURGE.alerte_s + 5)
    assert banc.n.purge_en_cours and banc.n.etat().purge_alerte
    banc.registre.fermer()


def test_purge_remise_a_zero_si_le_store_se_rouvre(b):
    b.store(True)
    b.bon_air()
    b.avancer(PURGE.duree_min_s - 60)
    b.store(False)
    assert not b.n.purge_en_cours
    b.store(True)
    assert b.n.purge_en_cours
    b.avancer(PURGE.duree_min_s - 60)
    assert b.n.purge_en_cours, "la purge a recommencé à zéro"
    b.avancer(70)
    assert not b.n.purge_en_cours


def test_dosage_et_versement_refuses_pendant_la_purge(b):
    chef = nouveau_chef(Horloge())
    chef.interdire(b.n.refus_geste)
    b.store(True)
    for geste in ("dosage_semence", "ouverture_capsule", "versement_seau_ouvert"):
        assert chef.permission(geste) == "purge en cours"
    assert not chef.condition_permission("dosage_semence").test()
    b.bon_air()
    b.avancer(PURGE.duree_min_s + 5)
    assert chef.permission("dosage_semence") is None


def test_le_mycelium_et_le_remplissage_demandent_la_permission(b):
    reglages = charger_reglages(DOSSIER_PI / "reglages")
    with Simulateur(reglages, charger_entrees_sorties(LISTE), "remplissage") as simulateur:
        scenario = remplissage_du_simulateur(simulateur)
        # Le simulateur leur donne la permission du chef ; le Nettoyage y met sa purge.
        simulateur.chef.interdire(b.n.refus_geste)
        b.store(True)
        assert scenario.mycelium.refus_dosage() == "purge en cours"
        assert not scenario.remplissage.versement_permis()
        b.bon_air()
        b.avancer(PURGE.duree_min_s + 5)
        assert scenario.mycelium.dosage_permis() and scenario.remplissage.versement_permis()


# ------------------------------------------------------------------ mode maïs, éclairage, UV


def test_mode_mais_store_ouvert_ventilateur_coupe_pas_de_purge(b):
    b.mode = "mais"
    b.store(True)
    assert not b.n.purge_en_cours
    assert not b.commande("ventilateur_enceinte")
    assert b.consigne.volts == NETTOYAGE.ventilateur.arret_v
    b.store(False)
    assert b.n.store_permet_les_mouvements()
    b.cycle = True
    b.store(True)
    b.store(False)
    assert b.pauses == 0 and not b.alarmes()


def test_eclairage_a_la_demande_pendant_un_cycle_eteint_en_uv_ozone(b):
    b.avancer(1)
    assert not b.commande("eclairage_enceinte")
    b.n.eclairage(True, "essai")
    assert b.commande("eclairage_enceinte")
    b.n.eclairage(False, "essai")
    b.cycle = True
    b.avancer(1)
    assert b.commande("eclairage_enceinte")
    b.cycle = False
    b.n.eclairage(True, "essai")
    b.mode = "uv_ozone"
    b.avancer(1)
    assert not b.commande("eclairage_enceinte")
    with pytest.raises(ErreurNettoyage):
        b.n.eclairage(True, "essai")


def test_lampe_uv_seulement_store_ferme(b):
    b.store(False)
    with pytest.raises(ErreurNettoyage, match="store pas fermé"):
        b.n.lampe_uv(True, "bain des têtes")
    b.store(True)
    b.n.lampe_uv(True, "bain des têtes")
    assert b.commande("lampe_uv")
    b.store(False)
    assert not b.commande("lampe_uv")


# ------------------------------------------------------------------ la nuit UV-ozone


def nuit_complete(b, coupure_apres: float | None = None):
    """Génération, contact, puis l'ozone redescend ; rend le Nettoyage à la fin."""
    b.n.programmer_nuit("essai", tout_de_suite=True)
    b.faux.regler("ozone_dedans", 12)  # au plafond
    b.avancer(1)
    assert b.n.nuit.phase == GENERATION
    assert b.commande("generateur_ozone")
    assert not b.commande("ventilateur_enceinte") and not b.commande("relais_compresseur")
    assert b.commande("coupure_ventilateur_armoire")
    assert "≥ 10 ppm" in b.n.etat().ozone_dedans
    b.avancer(OZONE.t_generation_s)
    assert b.n.nuit.phase == CONTACT and not b.commande("generateur_ozone")


def test_nuit_complete(b):
    b.preparer_nuit()
    nuit_complete(b)
    with pytest.raises(ErreurNettoyage, match="pas finie"):
        b.n.demander_ouverture("essai")
    b.avancer(OZONE.t_contact_s - OZONE.t_generation_s, pas=30)
    assert b.n.nuit.phase == RETOUR
    b.faux.regler("ozone_dedans", 0.05)
    b.avancer(OZONE.stabilite_retour_s - 60, pas=30)
    assert b.n.nuit.phase == RETOUR
    b.avancer(90, pas=30)
    assert b.n.nuit.phase == FINI
    assert not b.commande("coupure_ventilateur_armoire")
    assert b.n.air_permis
    # Le store reste verrouillé jusqu'à la demande d'ouverture, permise sous 0,1 ppm.
    assert not b.commande("verrous_store")
    b.n.demander_ouverture("essai")
    assert b.commande("verrous_store")
    mesures = b.registre.lire("SELECT * FROM mesures WHERE nom = 'ozone_dedans'")
    assert len(mesures) > 100
    cycles = b.registre.lire("SELECT * FROM cycles")
    assert cycles[0]["module"] == "nettoyage" and cycles[0]["issue"] == "termine"


def test_nuit_refusee_si_les_conditions_manquent(b):
    with pytest.raises(ErreurNettoyage, match="mode"):
        b.n.programmer_nuit("essai")
    b.preparer_nuit()
    b.faux.actionner("porte_spray", True)
    with pytest.raises(ErreurNettoyage, match="porte du spray ouverte"):
        b.n.programmer_nuit("essai")
    b.faux.actionner("porte_spray", False)
    b.cycle = True
    with pytest.raises(ErreurNettoyage, match="cycle"):
        b.n.programmer_nuit("essai")
    b.cycle = False
    b.n.programmer_nuit("essai")


def test_nuit_a_l_heure_reglee(b):
    b.preparer_nuit()
    b.n.programmer_nuit("essai")
    etat = b.n.etat()
    assert etat.nuit == "attente_depart" and etat.nuit_depart_prevu.endswith("22:00:00")
    b.avancer(3600, pas=60)
    assert b.n.nuit.phase == "attente_depart"
    debut = b.jour()
    reste = (debut.replace(hour=22, minute=0, second=0) - debut).total_seconds()
    b.faux.regler("ozone_dedans", 12)
    b.avancer(reste + 2, pas=60)
    assert b.n.nuit.phase == GENERATION


def test_nuit_prevue_annulee_si_le_mode_change(b):
    b.preparer_nuit()
    b.n.programmer_nuit("essai")
    b.mode = "production"
    b.avancer(1)
    assert b.n.nuit.phase is None


def test_generateur_jamais_relance_apres_une_coupure(b):
    b.preparer_nuit()
    b.n.programmer_nuit("essai", tout_de_suite=True)
    b.faux.regler("ozone_dedans", 12)
    b.avancer(30)
    assert b.n.nuit.phase == GENERATION and b.commande("generateur_ozone")
    # Coupure de courant : toutes les sorties retombent au repos, le Pi redémarre.
    b.materiel.mettre_au_repos()
    b.horloge.t += 60
    b.n = b.nouveau()
    assert b.n.nuit.phase == RETOUR
    b.avancer(OZONE.t_generation_s * 2)
    assert not b.commande("generateur_ozone")
    assert not b.commande("ventilateur_enceinte")
    assert b.commande("coupure_ventilateur_armoire")
    with pytest.raises(ErreurNettoyage, match="pas finie"):
        b.n.demander_ouverture("essai")
    b.faux.regler("ozone_dedans", 0.02)
    b.avancer(OZONE.stabilite_retour_s + 30, pas=30)
    assert b.n.nuit.phase == FINI
    assert not b.commande("generateur_ozone")


def test_fuite_dehors_coupe_le_generateur(b):
    b.preparer_nuit()
    b.n.programmer_nuit("essai", tout_de_suite=True)
    b.faux.regler("ozone_dedans", 12)
    b.avancer(10)
    assert b.commande("generateur_ozone")
    b.faux.regler("ozone_dehors", 0.15)
    b.avancer(1)
    assert not b.commande("generateur_ozone")
    assert b.commande("voyant_buzzer")
    assert b.n.etat().fuite
    assert any("FUITE D'OZONE" in m for m in b.alarmes())
    envois = b.registre.lire("SELECT * FROM envois WHERE sorte = 'cycle'")
    assert envois, "l'alerte part par la file d'envoi"
    b.avancer(OZONE.t_generation_s)
    assert not b.commande("generateur_ozone"), "jamais relancé"
    b.faux.regler("ozone_dehors", 0.0)
    b.avancer(1)
    assert not b.commande("voyant_buzzer") and not b.n.etat().fuite


def test_fuite_hors_de_la_nuit_aussi(b):
    b.store(True)
    b.faux.regler("ozone_dehors", 0.2)
    b.avancer(1)
    assert b.n.etat().fuite and b.commande("voyant_buzzer")


def test_store_ouvert_pendant_la_nuit(b):
    b.preparer_nuit()
    b.n.programmer_nuit("essai", tout_de_suite=True)
    b.faux.regler("ozone_dedans", 12)
    b.avancer(10)
    b.store(False)
    assert not b.commande("generateur_ozone")
    assert any("Store ouvert pendant la nuit" in m for m in b.alarmes())
    b.store(True)
    assert not b.commande("generateur_ozone")
    assert not b.n.purge_en_cours, "pas de purge : l'ozone est encore là"


def test_porte_du_spray_ouverte_pendant_la_nuit(b):
    b.preparer_nuit()
    b.n.programmer_nuit("essai", tout_de_suite=True)
    b.faux.regler("ozone_dedans", 12)
    b.avancer(10)
    b.faux.actionner("porte_spray", True)
    b.avancer(1)
    assert not b.commande("generateur_ozone")
    assert any("Porte du spray" in m for m in b.alarmes())


def test_pas_sous_le_seuil_a_temps_store_verrouille_cle_de_depannage(b):
    b.preparer_nuit()
    nuit_complete(b)
    b.avancer(OZONE.t_max_retour_s, pas=60)
    assert b.n.nuit.phase == ERREUR
    assert any("en erreur" in m for m in b.alarmes())
    assert b.registre.lire("SELECT issue FROM cycles")[0]["issue"] == "abandonne"
    b.mode = "production"
    with pytest.raises(ErreurNettoyage, match="clé de dépannage"):
        b.n.demander_ouverture("essai")
    # Karulium ouvre avec la clé, puis referme : l'erreur est close.
    b.store(False)
    b.store(True)
    assert b.n.nuit.phase is None
    assert b.n.purge_en_cours


def test_capteur_d_ozone_muet_pendant_la_nuit(b):
    b.preparer_nuit()
    nuit_complete(b)
    b.faux.capteur_ozone("ozone_dedans").cable_coupe = True
    b.avancer(10)
    assert b.n.nuit.phase == ERREUR and "muet" in b.n.nuit.erreur


def test_mesure_incoherente(b):
    b.preparer_nuit()
    b.n.programmer_nuit("essai", tout_de_suite=True)
    b.faux.regler("ozone_dedans", 0.3)  # le générateur ne fait presque rien
    b.avancer(OZONE.t_contact_s + 5, pas=30)
    assert b.n.nuit.phase == ERREUR and "incohérente" in b.n.nuit.erreur


def test_pas_de_changement_de_mode_pendant_la_nuit(b):
    horloge = Horloge()
    chef = nouveau_chef(horloge)
    mode = ModeMachine(b.dossier / "mode.json", chef)
    mode.refus_supplementaires.append(b.n.refus_changement_mode)
    mode.changer("uv_ozone", "essai")
    b.mode = mode.actuel
    b.preparer_nuit()
    b.n.programmer_nuit("essai", tout_de_suite=True)
    b.faux.regler("ozone_dedans", 12)
    b.avancer(1)
    with pytest.raises(ErreurMode, match="nuit UV-ozone"):
        mode.changer("production", "essai")


# ------------------------------------------------------------------ réglages


def test_reglages_verifies(reglages):
    remplacer(reglages / "machine.yaml", "    t_generation_s: 120 ", "    t_generation_s: 9000 ")
    message = erreur_de(reglages)
    assert "t_generation_s < t_contact_s < t_max_retour_s" in message


def test_niveaux_du_ventilateur_croissants(reglages):
    remplacer(reglages / "machine.yaml", "    normal_v: 5", "    normal_v: 11")
    assert "inférieur ou égal à 10" in erreur_de(reglages) or "10" in erreur_de(reglages)


def test_niveaux_du_ventilateur_dans_l_ordre(reglages):
    remplacer(reglages / "machine.yaml", "    normal_v: 5", "    normal_v: 10")
    assert "arret_v < normal_v < plein_v" in erreur_de(reglages)


def test_course_du_store_verifiee(reglages):
    remplacer(reglages / "machine.yaml", "      course_m: 2.178", "      course_m: 2.5")
    assert "course_m" in erreur_de(reglages)


def test_duree_negative_refusee(reglages):
    remplacer(reglages / "machine.yaml", "    duree_min_s: 420 ", "    duree_min_s: -1 ")
    assert "duree_min_s" in erreur_de(reglages)


# ------------------------------------------------------------------ simulateur


# Scénario → (gestes de Karulium, options de l'enceinte imaginaire).
GESTES = {
    "nettoyage_purge": (module_fermeture_purge, {}),
    "nettoyage_purge_longue": (module_purge_trop_longue, {"hepa_colmate": True}),
    "nettoyage_nuit": (module_nuit, {}),
    "nettoyage_fuite": (module_fuite, {}),
}


def simuler_nettoyage(nom, dossier=DOSSIER_PI / "reglages"):
    """Un scénario du Nettoyage dans le simulateur : (planning, simulation)."""
    reglages = charger_reglages(dossier)
    gestes, options = GESTES[nom]
    with Simulateur(reglages, charger_entrees_sorties(LISTE), SCENARIOS[nom]) as simulateur:
        simulation = nettoyage_du_simulateur(simulateur, **options)
        return simulateur.jouer([gestes(simulation)]), simulation


def lignes(planning):
    return {ligne.etape: ligne for ligne in planning.lignes}


def faits(planning):
    return [texte for _, texte in planning.evenements]


def test_simulation_fermeture_puis_purge():
    planning, simulation = simuler_nettoyage("nettoyage_purge")
    assert planning.fini, planning.probleme
    etapes = lignes(planning)
    simule = REGLAGES.simulateur.nettoyage
    # Le store descend, le reed rebondit, puis 2 s stables avant « fermé ».
    attendu = simule.course_s + simule.rebond_s + NETTOYAGE.store.stabilite_s
    assert etapes["fermer_le_store"].fin == pytest.approx(attendu, abs=0.01)
    assert etapes["purge"].fin - etapes["purge"].debut == pytest.approx(PURGE.duree_min_s, abs=1)
    assert "Nettoyage : Store fermé : purge (ventilateur au plein)." in faits(planning)
    assert any("Purge finie" in texte for texte in faits(planning))
    assert simulation.store.historique == ["descendre", "monter"]
    assert simulation.nettoyage.etat().store == OUVERT


def test_simulation_reed_qui_rebondit():
    reglages = charger_reglages(DOSSIER_PI / "reglages")
    with Simulateur(reglages, charger_entrees_sorties(LISTE)) as simulateur:
        simulation = nettoyage_du_simulateur(simulateur)
        store, simule = simulation.store, reglages.simulateur.nettoyage
        store.descendre()
        vus = []
        while simulateur.temps < simule.course_s + 1:
            simulateur.temps = min(
                simulateur.temps + 1, store.prochain_instant() or simulateur.temps + 1
            )
            simulation.tourner()
            vus.append(simulation.nettoyage.materiel.lire("store_ferme"))
        # Fermé, ouvert, fermé, ouvert... puis fermé pour de bon.
        changements = sum(1 for a, b in zip(vus, vus[1:], strict=False) if a != b)
        assert changements >= 4 and vus[-1] is True
        # Pas encore « fermé » : le reed n'est pas stable depuis 2 s.
        assert simulation.nettoyage.etat().store == OUVERT


def test_simulation_store_bloque_par_les_verrous():
    reglages = charger_reglages(DOSSIER_PI / "reglages")
    with Simulateur(reglages, charger_entrees_sorties(LISTE)) as simulateur:
        simulation = nettoyage_du_simulateur(simulateur)
        simulation.store.hauteur, simulation.store.sens = 0.0, 0
        simulation.tourner()
        assert simulation.store.monter() is False
        assert simulation.store.monter(cle=True) is True


def test_simulation_purge_trop_longue():
    planning, simulation = simuler_nettoyage("nettoyage_purge_longue")
    assert planning.fini, planning.probleme
    etapes = lignes(planning)
    alerte = etapes["purge_en_alerte"]
    assert alerte.fin - alerte.debut == pytest.approx(PURGE.alerte_s, abs=1)
    assert any("Purge pas finie après 20 min : surpression" in texte for texte in faits(planning))
    outre = etapes["passer_outre"]
    assert outre.go is not None and outre.go >= alerte.fin
    assert any("Purge passée outre" in texte for texte in faits(planning))
    assert simulation.enceinte.pression.valeur < PURGE.pression_fin


def test_simulation_nuit_uv_ozone_complete():
    planning, simulation = simuler_nettoyage("nettoyage_nuit")
    assert planning.fini, planning.probleme
    etapes = lignes(planning)
    depart = etapes["generation"].debut
    assert etapes["generation"].fin - depart == pytest.approx(OZONE.t_generation_s, abs=1)
    assert etapes["contact"].fin - depart == pytest.approx(OZONE.t_contact_s, abs=1)
    retour = etapes["retour"].fin - depart
    assert OZONE.t_contact_s + OZONE.stabilite_retour_s <= retour < OZONE.t_max_retour_s
    # L'ozone est monté au-dessus du plafond du capteur, puis redescendu sous le seuil.
    assert simulation.enceinte.ozone_max_ppm > 10
    assert simulation.enceinte.ozone_ppm < OZONE.seuil_ouverture_ppm
    assert any("Nuit UV-ozone finie" in texte for texte in faits(planning))
    assert any("panneau du poste du fût levé (position normale)" in t for t in faits(planning))
    assert simulation.nettoyage.etat().store == OUVERT


def test_simulation_fuite_d_ozone_dehors():
    planning, simulation = simuler_nettoyage("nettoyage_fuite")
    assert planning.fini, planning.probleme
    assert "mesure « ozone_dehors » : 0.4" in faits(planning)
    # Panneau du poste rabattu dans ce scénario : la nuit part quand même (pas une condition).
    assert any("panneau du poste du fût rabattu" in texte for texte in faits(planning))
    assert any("FUITE D'OZONE" in texte for texte in faits(planning))
    n = simulation.nettoyage
    assert n.etat().fuite and not n.commande("generateur_ozone")
    assert not simulation.simulateur.fabrique.commande("generateur_ozone")
    # Le générateur a tourné 30 s au plus.
    simule = REGLAGES.simulateur.nettoyage
    assert simulation.enceinte.ozone_max_ppm <= 31 * simule.montee_ozone_ppm_s


def test_simulation_mesure_inconnue(reglages):
    remplacer(
        reglages / "simulateur.yaml", "        mesure: ozone_dehors", "        mesure: store_ferme"
    )
    with pytest.raises(ErreurSimulation, match="« store_ferme » n'est pas une mesure"):
        simuler_nettoyage("nettoyage_fuite", reglages)


def test_evenement_mesure_sans_valeur(reglages):
    remplacer(reglages / "simulateur.yaml", "        valeur: 0.4\n", "")
    assert "« mesure » et « valeur »" in erreur_de(reglages)


def test_outil_scenarios_du_nettoyage(capsys):
    for nom in GESTES:
        assert main([nom, "--delai-go", "0"]) == 0, nom
    assert "Nuit UV-ozone finie" in capsys.readouterr().out


# ------------------------------------------------------------------ page web et démarrage


def client_api(b, nettoyage):
    services = Services(
        nouveau_chef(Horloge()), b.registre, lambda *_: None, list, nettoyage=nettoyage
    )
    app = creer_app(services, reglages_api(), CLE)
    return TestClient(app, client=LOCAL, headers={"Authorization": f"Bearer {CLE}"})


def test_api_du_nettoyage(b):
    client = client_api(b, b.n)
    b.store(True)
    assert client.get("/api/nettoyage").json()["purge"] is True
    assert client.get("/api/etat").json()["nettoyage"]["store"] == FERME
    reponse = client.post("/api/nettoyage/ouvrir")
    assert reponse.status_code == 409 and "purge en cours" in reponse.json()["detail"]
    assert client.post("/api/nettoyage/outre").json()["purge"] is False
    assert client.post("/api/nettoyage/ouvrir").json()["verrous_liberes"] is True
    assert client.post("/api/nettoyage/eclairage").json()["eclairage"] is True
    assert client.post("/api/nettoyage/voler").status_code == 404


def test_api_sans_nettoyage(b):
    assert client_api(b, None).get("/api/nettoyage").status_code == 404


def test_branche_au_chef_et_au_mode_au_demarrage(b, tmp_path):
    chef = nouveau_chef(Horloge())
    mode = ModeMachine(tmp_path / "mode.json", chef, b.registre)
    n = preparer_nettoyage(REGLAGES, b.materiel, tmp_path, b.registre, chef, mode)
    assert n is not None and n.fichier == tmp_path / "nettoyage.json"
    assert chef.conditions_generales == [n.condition_store]
    assert mode.refus_supplementaires == [n.refus_changement_mode]
    assert chef.permission("dosage_semence") is None
    assert not cycle_tourne(chef)
    sans = REGLAGES.machine.model_copy(update={"nettoyage": None})
    reglages = REGLAGES.model_copy(update={"machine": sans})
    assert preparer_nettoyage(reglages, b.materiel, tmp_path, b.registre, chef, mode) is None
    assert preparer_nettoyage(REGLAGES, None, tmp_path, b.registre, chef, mode) is None


def test_constats_de_la_check_list(b):
    sans_capteurs = Nettoyage(NETTOYAGE, b.materiel)
    textes = [constat.texte for constat in sans_capteurs.constats()]
    assert any("capteurs de purge pas encore branchés" in texte for texte in textes)
    assert any("consigne 0-10 V" in texte for texte in textes)
    assert all(constat.niveau != "bloquant" for constat in sans_capteurs.constats())
    b.store(True)
    assert [(c.niveau, c.texte) for c in b.n.constats()] == [("ok", "store fermé")]


@pytest.mark.parametrize("leve", [True, False])
def test_panneau_du_poste_pas_une_condition_de_la_nuit(b, leve, caplog, monkeypatch):
    """Levé (contact fermé, normal) ou rabattu : la nuit part, la position est notée au journal."""
    # Le journal « vidange » ne remonte pas au journal général : on le fait remonter pour lire.
    monkeypatch.setattr(logging.getLogger("vidange"), "propagate", True)
    b.preparer_nuit()
    b.faux.actionner("reed_panneau_poste_fut", leve)
    b.avancer(1)
    attendu = "levé (position normale)" if leve else "rabattu"
    assert b.n.refus_nuit() is None and b.n.etat().panneau == attendu
    with caplog.at_level("WARNING", logger="vidange"):
        b.n.programmer_nuit("essai", tout_de_suite=True)
    assert f"panneau du poste : {attendu}" in caplog.text
    assert b.n.etat().nuit == GENERATION
    assert f"(panneau du poste du fût {attendu})" in b.n.etat().messages[-1]
