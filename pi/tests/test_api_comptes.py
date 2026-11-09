"""Tests des droits de l'API et de la connexion (tâche 25)."""

import json

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from vidange.api import JournalActions, Services, creer_app
from vidange.api.acces import COOKIE, Exige, verifier_roles_declares
from vidange.comptes import Comptes, ErreurComptes, Niveau

from .test_api import (
    AIDE,
    CHEF,
    INVITE,
    LOCAL,
    MOT_DE_PASSE,
    BancApi,
    client_connecte,
    reglages_api,
)


@pytest.fixture
def b(tmp_path):
    banc = BancApi(tmp_path)
    yield banc
    banc.registre.fermer()


def niveaux_des_routes(app) -> dict[tuple[str, str], Niveau]:
    resultat = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for depend in route.dependencies:
            if isinstance(depend.dependency, Exige):
                for methode in route.methods - {"HEAD"}:
                    resultat[(methode, route.path)] = depend.dependency.niveau
    return resultat


# ---------------------------------------------------------------- chaque route dit son niveau


def test_toutes_les_routes_de_l_api_declarent_un_niveau(b):
    verifier_roles_declares(b.app)  # ne lève rien
    niveaux = niveaux_des_routes(b.app)
    assert len(niveaux) > 40
    chemins_publics = {
        "/",
        "/api/moi",
        "/api/connexion",
        "/api/deconnexion",
        "/manifeste.webmanifest",
        "/sw.js",
        "/icones/{nom}",
    }
    for route in b.app.routes:
        if isinstance(route, APIRoute) and route.path not in chemins_publics:
            assert any(chemin == route.path for (_, chemin) in niveaux), route.path


def test_une_route_sans_niveau_empeche_de_demarrer(b):
    @b.app.get("/api/oubliee")
    def oubliee() -> dict:
        return {}

    with pytest.raises(ErreurComptes, match=r"GET /api/oubliee"):
        verifier_roles_declares(b.app)


def test_creer_app_refuse_une_route_sans_niveau(b, monkeypatch):
    """Le contrôle est bien fait à la création de l'application, pas seulement à part."""
    from vidange.api import app as module

    appels = []
    monkeypatch.setattr(module, "verifier_roles_declares", lambda app: appels.append(app))
    creer_app(
        Services(b.chef, b.registre, b.bilans.acquitter, list),
        reglages_api(),
        b.app.comptes_de_test,
        JournalActions(b.dossier / "x.jsonl"),
    )
    assert len(appels) == 1


def test_le_niveau_de_chaque_famille_de_routes(b):
    niveaux = niveaux_des_routes(b.app)
    # Regarder : toute lecture.
    lectures_reglees = {
        "/api/actions",
        "/api/reglages-modifiables",
        "/api/reglages-modifiables/historique",
    }
    assert all(
        n is Niveau.REGARDER
        for (m, chemin), n in niveaux.items()
        if m == "GET" and chemin not in lectures_reglees
    )
    # Produire : Go, Pause, lots, boutons de production.
    for methode, chemin in [
        ("POST", "/api/go/{module}"),
        ("POST", "/api/pause"),
        ("POST", "/api/reprendre"),
        ("POST", "/api/lot/seaux"),
        ("POST", "/api/lot/bocaux"),
        ("POST", "/api/nettoyage/{ordre}"),
        ("POST", "/api/alarmes/{numero}/acquitter"),
        ("POST", "/api/alarmes/{numero}/vue"),
        ("POST", "/api/carnet"),
        ("POST", "/api/carnet/{numero}/barrer"),
    ]:
        assert niveaux[(methode, chemin)] is Niveau.PRODUIRE, chemin
    # Régler : mises à jour, pilotage à distance, journal des actions.
    for methode, chemin in [
        ("POST", "/api/mises-a-jour/pi/installer"),
        ("POST", "/api/mises-a-jour/cartes/{carte}/reglages"),
        ("POST", "/api/distance/activer"),
        ("POST", "/api/distance/tenir"),
        ("GET", "/api/actions"),
        ("GET", "/api/reglages-modifiables"),
        ("POST", "/api/reglages-modifiables/{nom}"),
        ("POST", "/api/reglages-modifiables/retour/{numero}"),
    ]:
        assert niveaux[(methode, chemin)] is Niveau.REGLER, chemin


# ---------------------------------------------------------------- les trois rôles


def test_visiteur_regarde_seulement(b):
    client = b.client(nom=INVITE)
    assert client.get("/api/etat").status_code == 200
    assert client.get("/api/alarmes").status_code == 200
    reponse = client.post("/api/pause")
    assert reponse.status_code == 403
    assert (
        "droit insuffisant" in reponse.json()["detail"] and "visiteur" in reponse.json()["detail"]
    )
    assert not b.chef.en_pause
    assert client.post("/api/go/essai").status_code == 403
    assert client.get("/api/actions").status_code == 403


def test_employe_produit_sans_regler(b):
    client = b.client(nom=AIDE)
    assert client.get("/api/etat").status_code == 200
    assert client.post("/api/pause").status_code == 200
    assert b.chef.en_pause
    assert client.post("/api/reprendre").status_code == 200
    # Pas de réglages : mises à jour, pilotage à distance, journal des actions.
    assert client.post("/api/mises-a-jour/pi/installer").status_code == 403
    assert client.post("/api/mises-a-jour/cartes/portique/reglages").status_code == 403
    assert client.post("/api/distance/activer").status_code == 403
    assert client.get("/api/actions").status_code == 403


def test_karulium_a_tous_les_droits(b):
    client = b.client(nom=CHEF)
    assert client.get("/api/etat").status_code == 200
    assert client.post("/api/pause").status_code == 200
    # Régler : la route répond (409 « pas de mises à jour » ou autre), mais n'est pas refusée.
    assert client.post("/api/mises-a-jour/pi/installer").status_code not in (401, 403)
    assert client.get("/api/actions").status_code == 200


def test_le_go_demande_produire(b):
    b.jusqu_au_go()
    assert b.client(nom=INVITE).post("/api/go/essai").status_code == 403
    assert b.chef.etat().attendent_go == ["essai"]
    assert b.client(nom=AIDE).post("/api/go/essai").status_code == 200


# ---------------------------------------------------------------- journal de qui a fait quoi


def test_journal_des_actions_produire_et_regler(b):
    b.client(nom=AIDE).post("/api/pause")
    b.client(nom=CHEF).post("/api/mises-a-jour/pi/installer")
    b.client(nom=INVITE).get("/api/etat")  # regarder : rien à noter
    b.client(nom=INVITE).post("/api/pause")  # refusé : rien à noter non plus
    actions = b.client(nom=CHEF).get("/api/actions").json()
    assert [(a["qui"], a["niveau"], a["chemin"]) for a in actions] == [
        (CHEF, "régler", "/api/mises-a-jour/pi/installer"),
        (AIDE, "produire", "/api/pause"),
    ]
    assert actions[1]["role"] == "employe" and actions[1]["adresse"] == "192.168.1.20"
    assert actions[1]["quand"].startswith("20")
    # Le fichier est en lignes JSON, dans le dossier des données (donc dans la copie de secours).
    lignes = (b.dossier / "actions.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(ligne)["qui"] for ligne in lignes] == [AIDE, CHEF]


def test_qui_a_donne_l_ordre_est_au_journal_du_programme(b, caplog):
    import logging

    logging.getLogger("vidange").propagate = True
    with caplog.at_level(logging.INFO, logger="vidange.api"):
        b.client(nom=AIDE).post("/api/pause")
    assert f"page web ({AIDE}, 192.168.1.20)" in caplog.text


def test_droit_insuffisant_est_au_journal_du_programme(b, caplog):
    import logging

    logging.getLogger("vidange").propagate = True
    with caplog.at_level(logging.WARNING, logger="vidange.api"):
        b.client(nom=INVITE).post("/api/pause")
    assert "Droit insuffisant" in caplog.text and INVITE in caplog.text


# ---------------------------------------------------------------- connexion


def test_connexion_deconnexion_et_cookie(b):
    client = TestClient(b.app, client=LOCAL)
    assert client.get("/api/moi").json() == {"aucun_compte": False, "connecte": False}
    reponse = client.post("/api/connexion", json={"nom": AIDE, "mot_de_passe": MOT_DE_PASSE})
    assert reponse.status_code == 200 and reponse.json() == {"nom": AIDE, "role": "employe"}
    cookie = reponse.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/moi").json()["droits"] == ["regarder", "produire"]
    assert client.post("/api/pause").status_code == 200
    client.post("/api/deconnexion")
    assert client.get("/api/etat").status_code == 401


def test_mauvais_mot_de_passe_ou_nom(b):
    client = TestClient(b.app, client=LOCAL)
    for nom, mot in [(AIDE, "faux faux faux"), ("inconnu", MOT_DE_PASSE)]:
        reponse = client.post("/api/connexion", json={"nom": nom, "mot_de_passe": mot})
        assert reponse.status_code == 401
        assert reponse.json()["detail"] == "nom ou mot de passe faux"
    assert COOKIE not in client.cookies


def test_trop_d_essais_rates_bloquent_l_adresse(b):
    client = TestClient(b.app, client=LOCAL)
    for _ in range(3):  # connexions_ratees_max du banc d'essai
        assert (
            client.post("/api/connexion", json={"nom": AIDE, "mot_de_passe": "x"}).status_code
            == 401
        )
    reponse = client.post("/api/connexion", json={"nom": AIDE, "mot_de_passe": MOT_DE_PASSE})
    assert reponse.status_code == 429 and "réessayer" in reponse.json()["detail"]
    # Une autre adresse n'est pas gênée.
    autre = TestClient(b.app, client=("192.168.1.99", 5000))
    assert (
        autre.post("/api/connexion", json={"nom": AIDE, "mot_de_passe": MOT_DE_PASSE}).status_code
        == 200
    )


def test_le_blocage_se_leve_avec_le_temps():
    from vidange.api.acces import LimiteConnexions

    maintenant = [0.0]
    limite = LimiteConnexions(2, 60, horloge=lambda: maintenant[0])
    limite.rater("a")
    limite.rater("a")
    assert limite.attente_s("a") == 60
    maintenant[0] = 61
    assert limite.attente_s("a") == 0


def test_la_connexion_reussie_est_notee(b):
    TestClient(b.app, client=LOCAL).post(
        "/api/connexion", json={"nom": CHEF, "mot_de_passe": MOT_DE_PASSE}
    )
    (ligne,) = b.client(nom=CHEF).get("/api/actions").json()
    assert ligne["niveau"] == "connexion" and ligne["qui"] == CHEF


# ---------------------------------------------------------------- pas de compte


@pytest.fixture
def sans_compte(tmp_path):
    banc = BancApi(tmp_path)
    comptes = Comptes(tmp_path / "vide.yaml")
    banc.app = creer_app(
        Services(banc.chef, banc.registre, banc.bilans.acquitter, list),
        reglages_api(),
        comptes,
        JournalActions(tmp_path / "a.jsonl"),
    )
    banc.comptes_vides = comptes
    yield banc
    banc.registre.fermer()


def test_sans_compte_tout_est_refuse_sauf_la_page_qui_explique(sans_compte):
    client = TestClient(sans_compte.app, client=LOCAL)
    page = client.get("/")
    assert page.status_code == 200
    assert "vidange compte ajouter" in page.text and "premier compte" in page.text
    assert "formulaire-cle" not in page.text  # pas de formulaire de connexion
    for methode, chemin in [
        ("get", "/api/etat"),
        ("get", "/api/photos/1"),
        ("post", "/api/pause"),
        ("post", "/api/go/essai"),
        ("get", "/api/actions"),
    ]:
        reponse = getattr(client, methode)(chemin)
        assert reponse.status_code == 503, chemin
        assert "aucun compte" in reponse.json()["detail"]
    assert client.post("/api/connexion", json={"nom": "a", "mot_de_passe": "b"}).status_code == 503
    assert client.get("/api/moi").json()["aucun_compte"] is True
    assert not sans_compte.chef.en_pause


def test_le_premier_compte_ouvre_la_page_sans_redemarrer(sans_compte):
    from vidange.comptes import Role

    client = TestClient(sans_compte.app, client=LOCAL)
    sans_compte.comptes_vides.ajouter("gael", Role.KARULIUM, MOT_DE_PASSE)
    assert "formulaire-cle" in client.get("/").text
    assert (
        client.post(
            "/api/connexion", json={"nom": "gael", "mot_de_passe": MOT_DE_PASSE}
        ).status_code
        == 200
    )
    assert client.get("/api/etat").status_code == 200


def test_la_check_list_dit_qu_il_n_y_a_aucun_compte(sans_compte):
    from vidange.api import ServeurApi, constats_api

    serveur = ServeurApi(sans_compte.app, reglages_api(1), sans_compte.comptes_vides)
    serveur._serveur.started = True
    serveur._fil = type("F", (), {"is_alive": lambda self: True})()
    (constat,) = constats_api(serveur)
    assert constat.niveau == "attention" and "aucun compte" in constat.texte
    assert "vidange compte ajouter" in constat.quoi_faire


def test_client_connecte_sert_aux_autres_tests(b):
    assert client_connecte(b.app, CHEF).get("/api/etat").status_code == 200


def test_j_ai_vu_demande_produire_et_est_note_au_journal_des_actions(b):
    numero = b.registre.noter_alarme("essai", "bruit", "Regarder.")
    assert b.client(nom=INVITE).post(f"/api/alarmes/{numero}/vue").status_code == 403
    reponse = b.client(nom=AIDE).post(f"/api/alarmes/{numero}/vue")
    assert reponse.status_code == 200 and reponse.json()["premiere_fois"] is True
    ligne = b.registre.lire("SELECT * FROM alarmes WHERE id = ?", (numero,))[0]
    assert AIDE in ligne["vue_par"] and ligne["acquittee_le"] is None
    # L'alarme reste ouverte, avec sa marque « vue ».
    ouvertes = b.client(nom=INVITE).get("/api/alarmes").json()
    assert ouvertes[0]["vue_le"] is not None
    actions = b.client(nom=CHEF).get("/api/actions").json()
    assert (actions[0]["qui"], actions[0]["chemin"]) == (AIDE, f"/api/alarmes/{numero}/vue")
    assert b.client(nom=AIDE).post("/api/alarmes/999/vue").status_code >= 400
