"""Page web, tâche 28 bis : carnet de bord, statistiques, réglages modifiables et appli installable,
par l'API (rôles, journal des actions), avec le vrai chef et le vrai registre."""

import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vidange.api import JournalActions, Services, creer_app
from vidange.api.app import DOSSIER_PAGE, version_coquille
from vidange.demarrage import erreurs_de_reglages
from vidange.modifiables import Modifiables
from vidange.registre import Registre
from vidange.reglages import ReglagesCarnet, charger_reglages

from .conftest import DOSSIER_PI
from .test_api import (
    AIDE,
    CHEF,
    INVITE,
    LOCAL,
    BancApi,
    client_connecte,
    creer_app_de_test,
    reglages_api,
)
from .test_api import b as b  # noqa: F401  (la fixture « b » : un chef, un registre, l'API)

# ---------------------------------------------------------------- le carnet, dans le registre


@pytest.fixture
def registre(tmp_path):
    r = Registre(tmp_path / "r.sqlite", tmp_path / "photos")
    yield r
    r.fermer()


def test_une_note_se_rattache_a_un_cycle_un_seau_une_alarme(registre):
    cycle = registre.commencer_cycle("vidange")
    registre.ajouter_seau(cycle, "S1293")
    alarme = registre.noter_alarme("griffe", "dérapage")
    n1 = registre.noter_carnet("zilca", "Seau un peu sec ce matin")
    n2 = registre.noter_carnet("gael", "Lot du fût 3", cycle=cycle, seau="S1293", alarme=alarme)
    notes = registre.lire_carnet()
    assert [n["id"] for n in notes] == [n2, n1]
    assert notes[0]["cycle_id"] == cycle and notes[0]["seau"] == "S1293"
    assert notes[0]["alarme_id"] == alarme and notes[0]["auteur"] == "gael"
    assert notes[1]["cycle_id"] is None and notes[1]["barre_le"] is None
    assert [n["id"] for n in registre.lire_carnet(seau="S1293")] == [n2]
    assert [n["id"] for n in registre.lire_carnet(cycle=cycle)] == [n2]
    assert [n["id"] for n in registre.lire_carnet(alarme=alarme)] == [n2]


def test_rattachement_inconnu_refuse(registre):
    from vidange.registre import ErreurRegistre

    with pytest.raises(ErreurRegistre, match="cycle n° 9 inconnu"):
        registre.noter_carnet("gael", "x", cycle=9)
    with pytest.raises(ErreurRegistre, match="alarme n° 9 inconnue"):
        registre.noter_carnet("gael", "x", alarme=9)
    with pytest.raises(ErreurRegistre, match="seau « S9 » inconnu"):
        registre.noter_carnet("gael", "x", seau="S9")
    with pytest.raises(ErreurRegistre, match="note vide"):
        registre.noter_carnet("gael", "   ")
    with pytest.raises(ErreurRegistre, match="trop longue"):
        registre.noter_carnet("gael", "abcdef", texte_max=5)
    assert registre.lire_carnet() == []


def test_recherche_simple(registre):
    registre.noter_carnet("zilca", "Odeur de moisi sur le seau 4")
    registre.noter_carnet("gael", "Fût 3 très humide")
    registre.noter_carnet("gael", "100% terminé_ok")
    assert len(registre.lire_carnet(recherche="MOISI")) == 1
    assert len(registre.lire_carnet(recherche="gael")) == 2
    assert len(registre.lire_carnet(recherche="100%")) == 1
    assert registre.lire_carnet(recherche="%") != registre.lire_carnet()
    assert len(registre.lire_carnet(recherche="_ok")) == 1
    assert registre.lire_carnet(recherche="absent") == []


def test_barrer_garde_la_trace_et_ne_supprime_rien(registre):
    from vidange.registre import ErreurRegistre

    note = registre.noter_carnet("zilca", "Erreur de ma part")
    registre.barrer_note(note, "gael", "mauvais seau")
    barree = registre.lire_carnet()[0]
    assert barree["texte"] == "Erreur de ma part"
    assert barree["barre_par"] == "gael" and barree["barre_raison"] == "mauvais seau"
    assert barree["barre_le"]
    assert registre.lire_carnet(avec_barrees=False) == []
    with pytest.raises(ErreurRegistre, match="déjà barrée"):
        registre.barrer_note(note, "gael", "encore")
    with pytest.raises(ErreurRegistre, match="pourquoi"):
        registre.barrer_note(note, "gael", " ")
    with pytest.raises(ErreurRegistre, match="inconnue"):
        registre.barrer_note(99, "gael", "x")


def test_la_base_elle_meme_refuse_de_supprimer_ou_de_corriger(registre):
    note = registre.noter_carnet("zilca", "Texte d'origine")
    cnx = sqlite3.connect(registre.chemin)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="ne se supprime pas"):
            cnx.execute("DELETE FROM carnet_de_bord WHERE id = ?", (note,))
        with pytest.raises(sqlite3.DatabaseError, match="ne se modifie pas"):
            cnx.execute("UPDATE carnet_de_bord SET texte = 'autre' WHERE id = ?", (note,))
        with pytest.raises(sqlite3.DatabaseError, match="ne se modifie pas"):
            cnx.execute("UPDATE carnet_de_bord SET auteur = 'autre' WHERE id = ?", (note,))
    finally:
        cnx.close()
    assert registre.lire_carnet()[0]["texte"] == "Texte d'origine"


def test_le_carnet_est_dans_la_copie_de_secours(registre, tmp_path):
    registre.noter_carnet("zilca", "À garder")
    copie = tmp_path / "secours" / "registre.sqlite"
    registre.copier_vers(copie)
    cnx = sqlite3.connect(copie)
    try:
        assert cnx.execute("SELECT texte FROM carnet_de_bord").fetchall() == [("À garder",)]
    finally:
        cnx.close()
    assert registre.compter()["carnet_de_bord"] == 1


# ---------------------------------------------------------------- le carnet, par l'API


def test_carnet_par_l_api_avec_les_roles(b):
    chef, aide, invite = b.client(), b.client(nom=AIDE), b.client(nom=INVITE)
    # Le visiteur lit, ne peut pas écrire ; l'employé écrit.
    assert invite.get("/api/carnet").status_code == 200
    reponse = invite.post("/api/carnet", json={"texte": "bonjour"})
    assert reponse.status_code == 403
    reponse = aide.post("/api/carnet", json={"texte": "Fût 3 très humide"})
    assert reponse.status_code == 200
    numero = reponse.json()["numero"]
    notes = invite.get("/api/carnet").json()
    # L'auteur est le compte connecté, pas un nom envoyé par la page.
    assert notes[0]["auteur"] == AIDE and notes[0]["texte"] == "Fût 3 très humide"
    # Recherche.
    assert len(chef.get("/api/carnet", params={"recherche": "humide"}).json()) == 1
    assert chef.get("/api/carnet", params={"recherche": "sec"}).json() == []
    # Barrer : employé oui, visiteur non ; la note reste lisible.
    assert invite.post(f"/api/carnet/{numero}/barrer", json={"raison": "x"}).status_code == 403
    assert chef.post(f"/api/carnet/{numero}/barrer", json={"raison": "doublon"}).status_code == 200
    barree = invite.get("/api/carnet").json()[0]
    assert barree["barre_par"] == CHEF and barree["barre_raison"] == "doublon"
    assert invite.get("/api/carnet", params={"barrees": "false"}).json() == []
    # Pas de suppression, pas de modification.
    assert chef.delete(f"/api/carnet/{numero}").status_code in (404, 405)
    assert chef.put(f"/api/carnet/{numero}", json={"texte": "x"}).status_code in (404, 405)
    # Les écritures sont au journal des actions (qui, quand).
    chemins = [a["chemin"] for a in chef.get("/api/actions").json()]
    assert "/api/carnet" in chemins and f"/api/carnet/{numero}/barrer" in chemins


def test_carnet_rattache_a_une_alarme_et_refus_clair(b):
    alarme = b.registre.noter_alarme("griffe", "dérapage")
    aide = b.client(nom=AIDE)
    ok = aide.post("/api/carnet", json={"texte": "vu sur place", "alarme": alarme})
    assert ok.status_code == 200
    assert aide.get("/api/carnet", params={"alarme": alarme}).json()[0]["alarme_id"] == alarme
    refus = aide.post("/api/carnet", json={"texte": "x", "alarme": 999})
    assert refus.status_code == 409 and "inconnue" in refus.json()["detail"]
    assert aide.post("/api/carnet", json={"texte": ""}).status_code == 409


def test_carnet_texte_trop_long_selon_les_reglages(tmp_path):
    banc = BancApi(tmp_path)
    try:
        services = Services(
            banc.chef,
            banc.registre,
            banc.bilans.acquitter,
            checklist=lambda: [],
            carnet=ReglagesCarnet(texte_max=10, notes_par_page=1),
        )
        app = creer_app_de_test(services, tmp_path)
        client = client_connecte(app, AIDE)
        assert client.post("/api/carnet", json={"texte": "x" * 11}).status_code == 409
        client.post("/api/carnet", json={"texte": "un"})
        client.post("/api/carnet", json={"texte": "deux"})
        # Une note par page ; « avant » donne la suivante.
        page = client.get("/api/carnet").json()
        assert len(page) == 1 and page[0]["texte"] == "deux"
        suite = client.get("/api/carnet", params={"avant": page[0]["id"]}).json()
        assert suite[0]["texte"] == "un"
    finally:
        banc.registre.fermer()


# ---------------------------------------------------------------- statistiques


def test_statistiques_par_l_api(tmp_path):
    from vidange.reglages import ReglagesStatistiques
    from vidange.statistiques import Statistiques

    banc = BancApi(tmp_path)
    try:
        cycle = banc.registre.commencer_cycle("vidange")
        banc.registre.ajouter_seau(cycle, "S1")
        banc.registre.finir_cycle(cycle)
        services = Services(
            banc.chef,
            banc.registre,
            banc.bilans.acquitter,
            checklist=lambda: [],
            statistiques=Statistiques(
                banc.registre,
                ReglagesStatistiques(jours=2, semaines=2, mois=2, cycle_ouvert_max_h=12),
            ),
        )
        app = creer_app_de_test(services, tmp_path)
        assert client_connecte(app, None).get("/api/statistiques").status_code == 401
        invite = client_connecte(app, INVITE)
        jour = invite.get("/api/statistiques").json()
        assert jour["echelle"] == "jour" and len(jour["periodes"]) == 2
        assert jour["periodes"][-1]["seaux"] == 1 and jour["periodes"][-1]["cycles_termines"] == 1
        assert len(invite.get("/api/statistiques", params={"par": "mois"}).json()["periodes"]) == 2
        assert invite.get("/api/statistiques", params={"par": "siecle"}).status_code == 422
    finally:
        banc.registre.fermer()


def test_statistiques_absentes_404(b):
    assert b.client(nom=INVITE).get("/api/statistiques").status_code == 404


# ---------------------------------------------------------------- réglages modifiables, par l'API


@pytest.fixture
def banc_reglages(tmp_path, reglages):
    banc = BancApi(tmp_path)
    entrees = DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"
    charges = charger_reglages(reglages)
    occupe = [""]
    services = Services(
        banc.chef,
        banc.registre,
        banc.bilans.acquitter,
        checklist=lambda: [],
        modifiables=Modifiables(
            charges.modifiables,
            charges,
            reglages,
            banc.registre,
            lambda dossier: erreurs_de_reglages(dossier, entrees),
            lambda: occupe[0],
        ),
    )
    banc.app = creer_app_de_test(services, tmp_path)
    banc.occupe = occupe
    banc.reglages = reglages
    yield banc
    banc.registre.fermer()


def test_reglages_seulement_pour_le_role_regler(banc_reglages):
    b = banc_reglages
    for nom in (AIDE, INVITE):
        client = b.client(nom=nom)
        assert client.get("/api/reglages-modifiables").status_code == 403
        assert client.get("/api/reglages-modifiables/historique").status_code == 403
        reponse = client.post("/api/reglages-modifiables/calmes_fin", json={"valeur": "07:00"})
        assert reponse.status_code == 403
        assert client.post("/api/reglages-modifiables/retour/1").status_code == 403
    assert b.client(nom=None).get("/api/reglages-modifiables").status_code == 401
    assert "07:00" not in (b.reglages / "programme.yaml").read_text(encoding="utf-8")


def test_changer_noter_au_journal_et_revenir(banc_reglages):
    b = banc_reglages
    chef = b.client()
    etat = chef.get("/api/reglages-modifiables").json()
    assert {r["nom"] for r in etat["reglages"]} >= {"heure_resume_soir", "usure_avance"}
    reponse = chef.post("/api/reglages-modifiables/calmes_fin", json={"valeur": "07:00"})
    assert reponse.status_code == 200
    fait = reponse.json()
    assert (fait["ancien"], fait["nouveau"], fait["redemarrage"]) == ("06:00", "07:00", True)
    # Journal des actions : qui, quand, avant, après.
    ligne = next(a for a in chef.get("/api/actions").json() if a.get("niveau") == "réglage")
    assert ligne["qui"] == CHEF and ligne["reglage"] == "calmes_fin"
    assert (ligne["avant"], ligne["apres"]) == ("06:00", "07:00") and ligne["quand"]
    # Historique et retour.
    historique = chef.get("/api/reglages-modifiables/historique").json()
    assert historique[0]["nom"] == "calmes_fin" and historique[0]["numero"] == fait["numero"]
    reponse = chef.post(f"/api/reglages-modifiables/retour/{fait['numero']}")
    assert reponse.status_code == 200 and reponse.json()["nouveau"] == "06:00"
    assert 'fin: "06:00"' in (b.reglages / "programme.yaml").read_text(encoding="utf-8")
    ligne = next(a for a in chef.get("/api/actions").json() if a.get("niveau") == "réglage")
    assert (ligne["avant"], ligne["apres"]) == ("07:00", "06:00")


def test_refus_clairs_par_l_api(banc_reglages):
    chef = banc_reglages.client()
    refus = chef.post("/api/reglages-modifiables/calmes_fin", json={"valeur": "23:00"})
    assert refus.status_code == 422 and "bornes" in refus.json()["detail"]
    refus = chef.post("/api/reglages-modifiables/heure_resume_soir", json={"valeur": "21:30"})
    assert refus.status_code == 409 and "heures calmes" in refus.json()["detail"]
    assert (
        chef.post("/api/reglages-modifiables/port_de_l_api", json={"valeur": 1}).status_code == 404
    )
    banc_reglages.occupe[0] = "un geste ou un lot est en cours"
    refus = chef.post("/api/reglages-modifiables/calmes_fin", json={"valeur": "07:00"})
    assert refus.status_code == 409 and "refusé maintenant" in refus.json()["detail"]
    assert chef.get("/api/reglages-modifiables").json()["occupe"]


def test_pas_de_reglages_modifiables_404(b):
    assert b.client().get("/api/reglages-modifiables").status_code == 404


# ---------------------------------------------------------------- appli installable


def test_manifeste_icones_et_service_worker_sans_connexion(b):
    visiteur = TestClient(b.app, client=LOCAL)
    manifeste = visiteur.get("/manifeste.webmanifest")
    assert manifeste.status_code == 200
    assert manifeste.headers["content-type"].startswith("application/manifest+json")
    donnees = manifeste.json()
    assert donnees["display"] == "standalone" and donnees["start_url"] == "/"
    tailles = {icone["sizes"] for icone in donnees["icons"]}
    assert {"192x192", "512x512"} <= tailles
    for icone in donnees["icons"]:
        reponse = visiteur.get(icone["src"])
        assert reponse.status_code == 200 and reponse.headers["content-type"] == icone["type"]
    assert visiteur.get("/icones/../index.html").status_code in (404, 422)
    assert visiteur.get("/icones/inconnue.png").status_code == 404
    sw = visiteur.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["content-type"].startswith("text/javascript")
    assert sw.headers["service-worker-allowed"] == "/" and sw.headers["cache-control"] == "no-cache"


def test_le_service_worker_ne_garde_jamais_l_api(b):
    sw = TestClient(b.app, client=LOCAL).get("/sw.js").text
    assert "__VERSION__" not in sw
    # L'API passe sans le service worker (aucun respondWith), avant tout le reste.
    assert sw.index('startsWith("/api/")') < sw.index("respondWith")
    # Seule la coquille est gardée : la page, le code, les icônes, le manifeste.
    assert "caches.match" in sw and "cache.put" in sw
    assert sw.count("cache.put") == 2
    for ligne in sw.splitlines():
        assert "/api/" not in ligne or "startsWith" in ligne or ligne.lstrip().startswith("//")


def test_le_numero_de_version_du_cache_change_avec_la_page(b, tmp_path):
    version = TestClient(b.app, client=LOCAL).get("/sw.js").text
    assert f'"{version_coquille()}"' in version
    copie = tmp_path / "page"
    shutil.copytree(DOSSIER_PAGE, copie)
    avant = version_coquille(copie)
    assert avant == version_coquille(DOSSIER_PAGE)
    # Chaque sorte de fichier de la page change le numéro.
    for nom in ("index.html", "sw.js", "manifeste.webmanifest", "statique/vue3d.js"):
        fichier = copie / nom
        original = fichier.read_bytes()
        fichier.write_bytes(original + b"\n// modifie\n")
        assert version_coquille(copie) != avant, nom
        fichier.write_bytes(original)
    (copie / "icones" / "icone-192.png").write_bytes(b"autre")
    assert version_coquille(copie) != avant
    # Un nouveau numéro, c'est un nouveau nom de cache : l'ancien est effacé à l'activation.
    assert "PREFIXE_CACHE" in version and "caches.delete" in version


def test_la_vraie_page_porte_la_marque_et_pas_la_page_sans_compte(b, tmp_path):
    reponse = TestClient(b.app, client=LOCAL).get("/")
    assert reponse.headers["x-vidange-coquille"] == "1"
    assert reponse.headers["cache-control"] == "no-cache"
    html = reponse.text
    assert '<link rel="manifest" href="/manifeste.webmanifest">' in html
    assert 'rel="apple-touch-icon"' in html and 'navigator.serviceWorker.register("/sw.js"' in html
    # Sans aucun compte, c'est la page qui explique : le service worker ne la garde pas.
    from vidange.comptes import Comptes

    vide = Comptes(tmp_path / "vide.yaml")
    app = creer_app(
        Services(b.chef, b.registre, b.bilans.acquitter, checklist=lambda: []),
        reglages_api(),
        vide,
        JournalActions(tmp_path / "actions.jsonl"),
    )
    sans = TestClient(app, client=LOCAL).get("/")
    assert "x-vidange-coquille" not in sans.headers


def test_les_routes_de_l_appli_respectent_le_filtre_des_reseaux(b):
    dehors = TestClient(b.app, client=("8.8.8.8", 5000))
    assert dehors.get("/manifeste.webmanifest").status_code == 403
    assert dehors.get("/sw.js").status_code == 403


def test_le_dossier_de_la_page_est_celui_du_depot():
    assert Path(DOSSIER_PAGE, "index.html").is_file()
