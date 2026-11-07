"""Air comprimé (tâche 42) : relais du compresseur, attente de mise en pression, bidon de purge."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from vidange.air import Air
from vidange.api.app import Services, creer_app
from vidange.chef import Condition
from vidange.chef.chef import GESTES_PROTEGES
from vidange.demarrage import constats_air, preparer_air
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.lavage.module import module_lavage
from vidange.lavage.simulation import lavage_du_simulateur
from vidange.materiel import FausseFabrique, Materiel
from vidange.prehension.module import module_prehension
from vidange.prehension.simulation import prehension_du_simulateur
from vidange.registre import Registre
from vidange.reglages import ReglagesAir, charger_reglages
from vidange.simulateur import Simulateur

from .conftest import DOSSIER_PI
from .test_api import CLE, LOCAL, reglages_api
from .test_chef import Horloge, nouveau_chef
from .test_nettoyage import Banc, nuit_complete
from .test_reglages import erreur_de, remplacer

LISTE = DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
AIR = REGLAGES.air
DEBUT = datetime(2026, 11, 7, 8, 0)


class BancAir:
    """Le vrai Air sur le faux matériel, avec une fausse horloge et une fausse date."""

    def __init__(self, dossier, permis=True) -> None:
        self.dossier = dossier
        self.horloge = Horloge()
        self.permis = permis
        liste = charger_entrees_sorties(LISTE)
        self.faux = FausseFabrique(liste)
        self.materiel = Materiel(liste, self.faux)
        self.air = self.nouveau()

    def nouveau(self) -> Air:
        """Un Air neuf (comme après un redémarrage du Pi), sur le même matériel."""
        return Air(
            AIR,
            self.materiel,
            self.dossier / "air.json",
            air_permis=lambda: self.permis,
            horloge=self.horloge,
            maintenant=lambda: DEBUT + timedelta(seconds=self.horloge.t),
        )

    def avancer(self, secondes: float) -> None:
        self.horloge.t += secondes
        self.air.avancer()

    def compresseur(self) -> bool:
        return self.faux.commande("relais_compresseur")


@pytest.fixture
def a(tmp_path):
    return BancAir(tmp_path)


# ------------------------------------------------------------------ le relais


def test_le_relais_est_ferme_puis_on_attend_la_mise_en_pression(a):
    assert not a.compresseur() and not a.air.etat().compresseur
    a.air.avancer()
    assert a.compresseur()
    etat = a.air.etat()
    assert etat.compresseur and not etat.en_pression
    assert etat.reste_s == AIR.attente_mise_en_pression_s
    refus = a.air.refus_geste("air")
    assert refus is not None and "mise en pression" in refus
    a.avancer(AIR.attente_mise_en_pression_s - 1)
    assert a.air.refus_geste("air") is not None
    a.avancer(1)
    assert a.air.refus_geste("air") is None and a.air.etat().en_pression


def test_le_spray_attend_aussi_l_air_mais_pas_les_autres_gestes(a):
    a.air.avancer()
    assert a.air.refus_geste("spray_seau") is not None
    assert a.air.refus_geste("dosage_semence") is None


def test_relais_ouvert_quand_l_air_n_est_pas_permis(a):
    a.air.avancer()
    a.avancer(AIR.attente_mise_en_pression_s)
    a.permis = False
    a.avancer(1)
    assert not a.compresseur()
    assert a.air.refus_geste("air") == "compresseur coupé (relais ouvert)"
    # Il est permis de nouveau : l'attente complète recommence.
    a.permis = True
    a.avancer(1)
    assert a.compresseur() and a.air.etat().reste_s == AIR.attente_mise_en_pression_s
    assert not a.air.etat().en_pression


def test_coupure_du_pi_attente_complete_au_redemarrage(a):
    a.air.avancer()
    a.avancer(AIR.attente_mise_en_pression_s)
    neuf = a.nouveau()
    neuf.avancer()
    assert neuf.etat().reste_s == AIR.attente_mise_en_pression_s


def test_signal_absent_de_la_liste_ne_plante_pas(tmp_path):
    liste = charger_entrees_sorties(LISTE)
    materiel = Materiel(liste, FausseFabrique(liste))
    materiel.branchements.pop("relais_compresseur")
    air = Air(AIR, materiel)
    air.avancer()
    assert not air.etat().compresseur


def test_apres_la_nuit_uv_ozone_le_compresseur_est_referme(tmp_path):
    b = Banc(tmp_path)
    horloge = b.horloge
    air = Air(AIR, b.materiel, air_permis=lambda: b.n.air_permis, horloge=horloge)
    try:
        air.avancer()
        assert b.commande("relais_compresseur")
        b.preparer_nuit()
        nuit_complete(b)
        air.avancer()
        assert not b.commande("relais_compresseur") and not air.etat().compresseur
        b.avancer(10_000, pas=30)
        b.faux.regler("ozone_dedans", 0.05)
        b.avancer(1_000, pas=30)
        assert b.n.air_permis
        air.avancer()
        assert b.commande("relais_compresseur") and air.etat().compresseur
        assert air.etat().reste_s == AIR.attente_mise_en_pression_s
        assert not air.etat().en_pression
    finally:
        b.registre.fermer()


# ------------------------------------------------------------------ le bidon de purge


def test_rappel_du_bidon_apres_le_nombre_de_jours_et_remise_a_zero(a):
    assert not a.air.bidon_a_vider()
    a.horloge.t = (AIR.rappel_bidon_jours * 86400) - 1
    assert not a.air.bidon_a_vider()
    a.horloge.t = AIR.rappel_bidon_jours * 86400
    assert a.air.bidon_a_vider()
    constat = a.air.constats()[0]
    assert constat.niveau == "attention" and "bidon" in constat.texte
    a.air.bidon_vide("essai")
    assert not a.air.bidon_a_vider() and a.air.constats()[0].niveau == "ok"


def test_la_date_du_bidon_survit_a_une_coupure(a):
    a.horloge.t = 3 * 86400
    a.air.bidon_vide("essai")
    a.horloge.t = 3 * 86400 + (AIR.rappel_bidon_jours - 1) * 86400
    neuf = a.nouveau()
    assert neuf.etat().bidon_jours == AIR.rappel_bidon_jours - 1


def test_fichier_du_bidon_illisible_on_repart_d_aujourd_hui(a):
    (a.dossier / "air.json").write_text("pas du json", encoding="utf-8")
    assert a.nouveau().etat().bidon_jours == 0


# ------------------------------------------------------------------ réglages


def test_les_reglages_du_depot_sont_marques_exemple():
    assert AIR.exemple and AIR.attente_mise_en_pression_s == 240 and AIR.rappel_bidon_jours == 7


def test_reglages_air_manquant(reglages):
    (reglages / "air.yaml").unlink()
    assert "air.yaml : fichier manquant" in erreur_de(reglages)


def test_reglages_air_faute_de_frappe(reglages):
    remplacer(reglages / "air.yaml", "rappel_bidon_jours:", "rapel_bidon_jours:")
    message = erreur_de(reglages)
    assert "air.yaml, rapel_bidon_jours : nom inconnu" in message
    assert "air.yaml, rappel_bidon_jours : manque" in message


def test_reglages_air_valeurs_impossibles(reglages):
    remplacer(reglages / "air.yaml", "rappel_bidon_jours: 7", "rappel_bidon_jours: 0")
    assert "air.yaml, rappel_bidon_jours" in erreur_de(reglages)


def test_reglages_air_periode_trop_grande(reglages):
    remplacer(
        reglages / "air.yaml", "attente_mise_en_pression_s: 240", "attente_mise_en_pression_s: 5"
    )
    assert "periode_s" in erreur_de(reglages) and "imprécise" in erreur_de(reglages)


def test_modele_sans_exemple_par_defaut():
    assert not ReglagesAir(
        attente_mise_en_pression_s=10, rappel_bidon_jours=1, periode_s=0.5
    ).exemple


# ------------------------------------------------------------------ démarrage et page web


def test_branche_au_chef_au_demarrage(a, tmp_path):
    chef = nouveau_chef(Horloge())
    air = preparer_air(REGLAGES, a.materiel, tmp_path, chef, None)
    assert air is not None and air.fichier == tmp_path / "air.json"
    air.avancer()
    assert chef.permission("air") is not None
    assert "air" in GESTES_PROTEGES
    assert preparer_air(REGLAGES, None, tmp_path, chef, None) is None
    assert constats_air(None)[0].niveau == "attention"


def client_api(tmp_path, air):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    services = Services(nouveau_chef(Horloge()), registre, lambda *_: None, list, air=air)
    app = creer_app(services, reglages_api(), CLE)
    return TestClient(app, client=LOCAL, headers={"Authorization": f"Bearer {CLE}"}), registre


def test_api_de_l_air(a, tmp_path):
    client, registre = client_api(tmp_path, a.air)
    try:
        a.air.avancer()
        assert client.get("/api/air").json()["compresseur"] is True
        assert client.get("/api/etat").json()["air"]["en_pression"] is False
        a.horloge.t = AIR.rappel_bidon_jours * 86400
        assert client.get("/api/air").json()["bidon_a_vider"] is True
        assert client.post("/api/air/bidon_vide").json()["bidon_a_vider"] is False
    finally:
        registre.fermer()


def test_api_sans_air(tmp_path):
    client, registre = client_api(tmp_path, None)
    try:
        assert client.get("/api/air").status_code == 404
        assert client.get("/api/etat").json()["air"] is None
    finally:
        registre.fermer()


# ---------------------------------------------- la Préhension et le Lavage attendent l'air

ATTEND_AIR = Condition("air en pression", lambda: True)


def avec_air(module) -> set[str]:
    return {etape.nom for etape in module.etapes if ATTEND_AIR in etape.entree}


def test_la_prehension_attend_l_air_pour_prendre_par_le_venturi():
    with Simulateur(REGLAGES, charger_entrees_sorties(LISTE), "prehension") as simulation:
        prehension = prehension_du_simulateur(simulation)
        places = REGLAGES.simulateur.prehension
        module = module_prehension(prehension, places, ATTEND_AIR)
        assert avec_air(module) == {
            "prendre_le_seau",
            "prendre_le_couvercle",
            "prendre_le_bocal",
            "reprendre_au_porte_bocal",
            "prendre_la_capsule",
        }
        # Sans la condition, rien ne change (le module reste utilisable seul).
        assert avec_air(module_prehension(prehension, places)) == set()
        # Avec l'air, le cycle de la Préhension se rejoue en entier.
        planning = simulation.jouer([module])
        assert planning.lignes


def test_le_lavage_attend_l_air_pour_le_jet_et_la_prise_du_seau():
    with Simulateur(REGLAGES, charger_entrees_sorties(LISTE), "lavage") as simulation:
        lavage = lavage_du_simulateur(simulation)
        seaux = REGLAGES.simulateur.lavage.seaux
        module = module_lavage(lavage, seaux, ATTEND_AIR)
        assert avec_air(module) == {"prendre_le_seau", "laver_le_seau"}
        assert avec_air(module_lavage(lavage, seaux)) == set()
        planning = simulation.jouer([module])
        assert planning.lignes


def test_la_condition_du_chef_suit_la_mise_en_pression(a):
    chef = nouveau_chef(Horloge())
    chef.interdire(a.air.refus_geste)
    condition = chef.condition_permission("air")
    a.air.avancer()
    assert not condition.test()
    a.avancer(AIR.attente_mise_en_pression_s)
    assert condition.test()
