"""Tests de l'API du Pi et de la page web : vrai chef, vrai registre, fausse horloge."""

import logging
import socket
import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient

from vidange.api import ServeurApi, Services, constats_api, creer_app
from vidange.fiabilite import Bilans
from vidange.fiabilite.constats import Constat
from vidange.registre import Registre
from vidange.reglages import ReglagesApi, ReglagesBilan

from .test_chef import Banc, Horloge, etat_de, module_simple, nouveau_chef, tour

CLE = "une-cle-de-test-assez-longue"
LOCAL = ("192.168.1.20", 50000)


def reglages_api(port: int = 8080) -> ReglagesApi:
    return ReglagesApi.model_validate(
        {
            "adresse": "127.0.0.1",
            "port": port,
            "reseaux_autorises": ["127.0.0.0/8", "192.168.0.0/16", "100.64.0.0/10"],
            "rafraichir_s": 2,
            "lignes_max": 3,
        }
    )


class BancApi:
    """Un chef avec le module d'essai lancé, un registre, et l'API devant."""

    def __init__(self, dossier) -> None:
        self.horloge = Horloge()
        self.banc = Banc()
        self.chef = nouveau_chef(self.horloge)
        self.chef.lancer(module_simple(self.banc))
        self.registre = Registre(dossier / "registre.sqlite", dossier / "photos")
        self.bilans = Bilans(dossier, ReglagesBilan(lignes_journal=0), self.registre, self.chef)
        self.constats = [Constat("disque du Pi", "ok", "place libre")]
        services = Services(
            self.chef, self.registre, self.bilans.acquitter, checklist=lambda: self.constats
        )
        self.app = creer_app(services, reglages_api(), CLE)

    def client(self, adresse=LOCAL, cle: str | None = CLE) -> TestClient:
        entetes = {"Authorization": f"Bearer {cle}"} if cle is not None else {}
        return TestClient(self.app, client=adresse, headers=entetes)

    def jusqu_au_go(self) -> None:
        """Le module passe l'étape « un » et attend le Go de l'étape « deux »."""
        self.banc.drapeaux["pret"] = True
        tour(self.chef, self.horloge)
        self.banc.drapeaux["essai.un_fini"] = True
        tour(self.chef, self.horloge)
        tour(self.chef, self.horloge)


@pytest.fixture
def b(tmp_path):
    banc = BancApi(tmp_path)
    yield banc
    banc.registre.fermer()


@pytest.fixture
def caplog(caplog, monkeypatch):
    """Le journal « vidange » ne remonte pas au journal général : on le fait remonter pour lire."""
    monkeypatch.setattr(logging.getLogger("vidange"), "propagate", True)
    return caplog


# ---------------------------------------------------------------- garde-fous


def test_pas_d_api_sans_cle(b):
    with pytest.raises(ValueError):
        creer_app(Services(b.chef, b.registre, b.bilans.acquitter, list), reglages_api(), "")


@pytest.mark.parametrize("cle", [None, "fausse-cle", CLE + "x"])
def test_cle_absente_ou_fausse_refusee(b, cle, caplog):
    reponse = b.client(cle=cle).get("/api/etat")
    assert reponse.status_code == 401
    assert reponse.json()["detail"] == "clé de l'API absente ou fausse"
    assert "192.168.1.20" in caplog.text
    # Un ordre aussi est refusé, et il n'a pas lieu.
    assert b.client(cle=cle).post("/api/pause").status_code == 401
    assert not b.chef.en_pause


def test_cle_dans_un_autre_format_refusee(b):
    client = TestClient(b.app, client=LOCAL, headers={"Authorization": CLE})
    assert client.get("/api/etat").status_code == 401


@pytest.mark.parametrize("adresse", ["8.8.8.8", "2001:db8::1", "testclient"])
def test_adresse_hors_des_reseaux_autorises_refusee(b, adresse):
    client = b.client(adresse=(adresse, 50000))
    # Même avec la bonne clé, et même pour la page.
    assert client.get("/api/etat").status_code == 403
    assert client.get("/").status_code == 403


@pytest.mark.parametrize("adresse", ["127.0.0.1", "100.101.102.103", "::ffff:192.168.1.30"])
def test_reseau_local_et_tailscale_acceptes(b, adresse):
    assert b.client(adresse=(adresse, 50000)).get("/api/etat").status_code == 200


def test_pas_de_documentation_automatique(b):
    client = b.client()
    for adresse in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(adresse).status_code == 404


# ---------------------------------------------------------------- page et état


def test_la_page_se_charge_sans_cle(b):
    reponse = b.client(cle=None).get("/")
    assert reponse.status_code == 200
    assert "text/html" in reponse.headers["content-type"]
    assert '<html lang="fr">' in reponse.text
    assert "width=device-width" in reponse.text  # lisible sur téléphone


def test_etat(b):
    tour(b.chef, b.horloge)
    etat = b.client().get("/api/etat").json()
    assert etat["en_pause"] is False
    assert etat["rafraichir_s"] == 2
    assert etat["attendent_go"] == []
    (module,) = etat["modules"]
    assert module["module"] == "essai"
    assert module["etape"] == "un"
    assert module["attend"] == "pret"
    assert module["nombre_etapes"] == 2


def test_checklist(b):
    liste = b.client().get("/api/checklist").json()
    assert liste["prete"] is True
    assert liste["constats"][0]["sujet"] == "disque du Pi"
    b.constats.append(Constat("cartes", "bloquant", "carte muette", "Brancher la carte."))
    liste = b.client().get("/api/checklist").json()
    assert liste["prete"] is False
    assert liste["niveau"] == "bloquant"
    assert liste["constats"][1]["quoi_faire"] == "Brancher la carte."


# ---------------------------------------------------------------- ordres


def test_pause_et_reprise(b, caplog):
    client = b.client()
    with caplog.at_level(logging.INFO, logger="vidange.api"):
        assert client.post("/api/pause").json() == {"en_pause": True}
    assert b.chef.en_pause
    assert "Pause demandée par la page web (192.168.1.20)" in caplog.text
    assert client.get("/api/etat").json()["en_pause"] is True
    assert client.post("/api/reprendre").json() == {"en_pause": False}
    assert not b.chef.en_pause


def test_go(b):
    client = b.client()
    # Pas encore de Go attendu : refusé, avec la raison.
    reponse = client.post("/api/go/essai")
    assert reponse.status_code == 409
    assert "n'attend pas de Go" in reponse.json()["detail"]

    b.jusqu_au_go()
    assert client.get("/api/etat").json()["attendent_go"] == ["essai"]
    assert client.post("/api/go/essai").json() == {"go": "essai"}
    tour(b.chef, b.horloge)
    assert b.banc.appels[-1] == "essai.deux"


def test_go_a_un_module_inconnu(b):
    assert b.client().post("/api/go/inconnu").status_code == 409


# ---------------------------------------------------------------- alarmes


def test_alarme_du_chef_acquittee_depuis_la_page(b):
    # L'étape « un » dépasse son délai : alarme dans le chef, notée dans le registre.
    b.banc.drapeaux["pret"] = True
    tour(b.chef, b.horloge)
    tour(b.chef, b.horloge, 11)
    alarme = etat_de(b.chef).alarme
    assert alarme is not None
    numero = b.registre.noter_alarme("essai", alarme.message, alarme.quoi_faire, alarme.etape)

    client = b.client()
    etat = client.get("/api/etat").json()
    assert etat["modules"][0]["statut"] == "alarme"
    (ouverte,) = etat["alarmes_ouvertes"]
    assert ouverte["id"] == numero
    assert ouverte["quoi_faire"] == alarme.quoi_faire

    assert client.post(f"/api/alarmes/{numero}/acquitter").json() == {"acquittee": numero}
    assert client.get("/api/alarmes").json() == []
    # Le module repart après un Go.
    assert etat_de(b.chef).statut == "en_cours"
    assert client.get("/api/etat").json()["attendent_go"] == ["essai"]
    (ligne,) = client.get("/api/alarmes?toutes=true").json()
    assert ligne["acquittee_par"] == "page web (192.168.1.20)"

    # Deux fois : refusé.
    assert client.post(f"/api/alarmes/{numero}/acquitter").status_code == 409
    assert client.post("/api/alarmes/999/acquitter").status_code == 409


def test_dernieres_alarmes_par_pages(b):
    numeros = [b.registre.noter_alarme("essai", f"alarme {n}") for n in range(5)]
    client = b.client()
    assert len(client.get("/api/alarmes").json()) == 5
    # Au plus « lignes_max » (3) d'un coup, de la plus récente à la plus ancienne.
    page = client.get("/api/alarmes?toutes=true&limite=50").json()
    assert [a["id"] for a in page] == numeros[:1:-1]
    suite = client.get(f"/api/alarmes?toutes=true&avant={page[-1]['id']}").json()
    assert [a["id"] for a in suite] == numeros[1::-1]


# ---------------------------------------------------------------- historique et photos


def remplir_registre(b, tmp_path):
    cycle = b.registre.commencer_cycle("vidange", fut="F3")
    seau = b.registre.ajouter_seau(cycle, "S1293", bocal="B327")
    b.registre.ajouter_dose(seau, "B328", quantite_g=40)
    b.registre.noter_mesure("poids_seau", 6.2, "kg", capteur="balance", cycle=cycle, seau="S1293")
    fichier = tmp_path / "photos" / "2026-10-26" / "dose.jpg"
    fichier.parent.mkdir(parents=True)
    fichier.write_bytes(b"\xff\xd8 photo")
    photo = b.registre.noter_photo(fichier, camera="dosage", cycle=cycle, seau="S1293")
    b.registre.finir_cycle(cycle)
    return cycle, photo


def test_historique(b, tmp_path):
    cycle, photo = remplir_registre(b, tmp_path)
    autre = b.registre.commencer_cycle("lavage")
    client = b.client()
    cycles = client.get("/api/historique").json()
    assert [c["id"] for c in cycles] == [autre, cycle]
    assert cycles[1]["fut"] == "F3"
    assert cycles[1]["nombre_seaux"] == 1
    assert cycles[1]["issue"] == "termine"
    assert [c["id"] for c in client.get(f"/api/historique?avant={autre}").json()] == [cycle]

    detail = client.get(f"/api/historique/{cycle}").json()
    assert detail["fut"] == "F3"
    (seau,) = detail["seaux"]
    assert seau["seau"] == "S1293"
    assert [d["bocal"] for d in seau["doses"]] == ["B327", "B328"]
    assert seau["doses"][1]["quantite_g"] == 40
    assert detail["mesures"][0]["valeur"] == 6.2
    assert detail["photos"][0]["id"] == photo

    assert client.get("/api/historique/999").status_code == 404


def test_photos(b, tmp_path):
    cycle, photo = remplir_registre(b, tmp_path)
    client = b.client()
    (ligne,) = client.get("/api/photos?seau=S1293").json()
    assert ligne["id"] == photo
    assert ligne["camera"] == "dosage"
    assert ligne["cycle_id"] == cycle
    assert client.get("/api/photos?seau=S0000").json() == []

    reponse = client.get(f"/api/photos/{photo}")
    assert reponse.status_code == 200
    assert reponse.content == b"\xff\xd8 photo"
    assert reponse.headers["content-type"] == "image/jpeg"
    assert client.get("/api/photos/999").status_code == 404
    # La photo demande la clé, comme le reste.
    assert b.client(cle=None).get(f"/api/photos/{photo}").status_code == 401


def test_photo_effacee_ou_hors_du_dossier(b, tmp_path):
    _, photo = remplir_registre(b, tmp_path)
    client = b.client()
    # Un chemin abîmé dans la base ne fait jamais sortir du dossier des photos.
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    b.registre._cnx.execute("UPDATE photos SET chemin = '../secret.txt' WHERE id = ?", (photo,))
    assert client.get(f"/api/photos/{photo}").status_code == 404
    b.registre._cnx.execute("UPDATE photos SET chemin = 'manque.jpg' WHERE id = ?", (photo,))
    assert client.get(f"/api/photos/{photo}").status_code == 404


# ---------------------------------------------------------------- vrai serveur


def port_libre() -> int:
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        return prise.getsockname()[1]


def test_vrai_serveur_demarre_et_s_arrete(b):
    reglages = reglages_api(port_libre())
    serveur = ServeurApi(b.app, reglages)
    assert constats_api(serveur)[0].niveau == "attention"
    serveur.demarrer()
    try:
        assert serveur.en_route
        assert constats_api(serveur)[0].niveau == "ok"
        demande = urllib.request.Request(
            f"http://127.0.0.1:{reglages.port}/api/etat",
            headers={"Authorization": f"Bearer {CLE}"},
        )
        with urllib.request.urlopen(demande, timeout=5) as reponse:
            assert reponse.status == 200
        with pytest.raises(urllib.error.HTTPError) as refus:
            urllib.request.urlopen(f"http://127.0.0.1:{reglages.port}/api/etat", timeout=5)
        assert refus.value.code == 401
    finally:
        serveur.arreter()
    assert not serveur.en_route


def test_port_deja_pris(b, caplog):
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        prise.listen()
        serveur = ServeurApi(b.app, reglages_api(prise.getsockname()[1]))
        with caplog.at_level(logging.ERROR, logger="vidange.api"):
            serveur.demarrer()
            serveur.arreter()
    assert not serveur.en_route
    assert "L'API s'est arrêtée" in caplog.text
    assert "ne répond pas" in constats_api(serveur)[0].texte


def test_sans_cle_la_check_list_le_dit():
    (constat,) = constats_api(None)
    assert constat.niveau == "attention"
    assert "cle_api" in constat.quoi_faire
