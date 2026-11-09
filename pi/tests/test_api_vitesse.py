"""Tests de l'API de la montée en vitesse, de l'estimation et de l'essai d'un réglage (tâche 30)."""

import time
from datetime import datetime

import pytest

from vidange.api import Services
from vidange.estimation import BaseSimulee, Estimation
from vidange.fiabilite import Bilans
from vidange.registre import Registre
from vidange.reglages import ReglagesBilan
from vidange.simulateur.essai import EssaiEnFond, ResultatLot
from vidange.vitesse import MonteeVitesse

from .test_api import AIDE, CHEF, INVITE, client_connecte, creer_app_de_test
from .test_chef import Horloge, nouveau_chef
from .test_estimation import LOT, reglages_estimation
from .test_vitesse import montee_reglages


class Banc:
    def __init__(self, dossier, reglages, entrees_sorties, refus="") -> None:
        horloge = Horloge()
        self.chef = nouveau_chef(horloge)
        self.registre = Registre(dossier / "registre.sqlite", dossier / "photos")
        bilans = Bilans(dossier, ReglagesBilan(lignes_journal=0), self.registre, self.chef)
        self.montee = MonteeVitesse(montee_reglages(), dossier / "montee.json", self.registre)
        self.estimation = Estimation(
            reglages_estimation(),
            self.registre,
            lambda: LOT,
            lambda format, nombre: BaseSimulee(600.0, {"m.a": (600.0, 6)}),
            horloge=datetime.now,
            en_fond=False,
        )
        self.essai = EssaiEnFond(
            reglages,
            entrees_sorties,
            refus=lambda: refus,
            jouer=lambda r, liste: ResultatLot(
                fini=True, temps_total_s=1000 * 0.25 / r.machine.griffe.vitesses.pont_x
            ),
        )
        services = Services(
            self.chef,
            self.registre,
            bilans.acquitter,
            checklist=lambda: [],
            montee=self.montee,
            estimation=self.estimation,
            essai=self.essai,
        )
        self.app = creer_app_de_test(services, dossier)

    def client(self, nom=CHEF):
        return client_connecte(self.app, nom)


@pytest.fixture
def banc(tmp_path, reglages, entrees_sorties):
    banc = Banc(tmp_path, reglages, entrees_sorties)
    yield banc
    banc.registre.fermer()


def test_l_etat_porte_l_estimation_du_lot(banc):
    estimation = banc.client().get("/api/etat").json()["estimation"]
    assert estimation["disponible"] is True
    assert estimation["reste_s"] == 600
    assert "Fin du lot : environ 10 min 00 s" in estimation["texte"]


def test_la_vitesse_se_lit_avec_le_role_regler(banc):
    etat = banc.client().get("/api/vitesse").json()
    assert (etat["actif"], etat["palier"], etat["palier_max"]) == (True, 0, 4)
    assert etat["plafonds"]["griffe.vitesses.pont_x"] == 0.30
    assert banc.client(AIDE).get("/api/vitesse").status_code == 403
    assert banc.client(INVITE).get("/api/vitesse").status_code == 403


def test_annuler_la_montee_se_fait_avec_le_role_regler(banc):
    for _ in range(3):
        banc.montee.cycle_fini()
    assert banc.client().get("/api/vitesse").json()["palier"] == 1
    assert banc.client(AIDE).post("/api/vitesse/annuler").status_code == 403
    reponse = banc.client().post("/api/vitesse/annuler")
    assert reponse.status_code == 200
    assert reponse.json()["palier"] == 0
    # Rien d'autre à annuler : refus clair, pas d'erreur 500.
    deuxieme = banc.client().post("/api/vitesse/annuler")
    assert deuxieme.status_code == 409
    assert "rien à annuler" in deuxieme.json()["detail"]


def test_l_annulation_est_au_journal_des_actions(banc):
    for _ in range(3):
        banc.montee.cycle_fini()
    banc.client().post("/api/vitesse/annuler")
    actions = banc.client().get("/api/actions").json()
    assert any(a.get("chemin") == "/api/vitesse/annuler" for a in actions)


def test_l_essai_se_lance_et_se_lit(banc):
    client = banc.client()
    reponse = client.post(
        "/api/essai", json={"changements": ["machine.yaml=griffe.vitesses.pont_x=0.2"]}
    )
    assert reponse.status_code == 200
    for _ in range(100):
        etat = client.get("/api/essai").json()
        if not etat["en_cours"]:
            break
        time.sleep(0.1)
    assert etat["erreur"] is None
    assert etat["resultat"]["essai"]["temps_total_s"] == 1250
    assert "Lot avec l'essai" in etat["resultat"]["texte"]


def test_l_essai_est_reserve_au_role_regler(banc):
    corps = {"changements": ["machine.yaml=griffe.vitesses.pont_x=0.2"]}
    assert banc.client(AIDE).post("/api/essai", json=corps).status_code == 403
    assert banc.client(AIDE).get("/api/essai").status_code == 403


def test_l_essai_mal_ecrit_est_refuse_clairement(banc):
    reponse = banc.client().post("/api/essai", json={"changements": ["n'importe quoi"]})
    assert reponse.status_code == 409
    assert "fichier=chemin=valeur" in reponse.json()["detail"]


def test_l_essai_est_refuse_pendant_un_lot(tmp_path, reglages, entrees_sorties):
    banc = Banc(tmp_path, reglages, entrees_sorties, refus="un lot tourne")
    reponse = banc.client().post(
        "/api/essai", json={"changements": ["machine.yaml=griffe.vitesses.pont_x=0.2"]}
    )
    assert reponse.status_code == 409
    assert "un lot tourne" in reponse.json()["detail"]
    banc.registre.fermer()


def test_sans_ces_services_les_routes_repondent_404(tmp_path):
    horloge = Horloge()
    chef = nouveau_chef(horloge)
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    bilans = Bilans(tmp_path, ReglagesBilan(lignes_journal=0), registre, chef)
    app = creer_app_de_test(Services(chef, registre, bilans.acquitter, lambda: []), tmp_path)
    client = client_connecte(app, CHEF)
    assert client.get("/api/vitesse").status_code == 404
    assert client.get("/api/essai").status_code == 404
    assert client.get("/api/etat").json()["estimation"] is None
    registre.fermer()
