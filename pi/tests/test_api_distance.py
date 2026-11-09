"""API : vidéos, clips et pilotage à distance (faux pilote, fausses caméras)."""

import pytest

from vidange.api import Services
from vidange.cameras import Cameras, FausseCamera, fausse_image
from vidange.distance import ErreurDistance

from .test_api import LOCAL, BancApi, creer_app_de_test
from .test_cameras import reglages as reglages_cameras


class FauxPilote:
    """Le pilote vu par l'API : il note les ordres reçus."""

    def __init__(self) -> None:
        self.actif = False
        self.ordres: list[tuple] = []
        self.refuser: str | None = None

    def _ordre(self, *ordre) -> None:
        if self.refuser:
            raise ErreurDistance(self.refuser)
        self.ordres.append(ordre)

    def etat(self) -> dict:
        return {"actif": self.actif}

    def activer(self, qui: str) -> None:
        self._ordre("activer", qui)
        self.actif = True

    def quitter(self, qui: str) -> None:
        self._ordre("quitter", qui)
        self.actif = False

    def tenir(self, qui: str, axe: str, sens: int, camera: str, numero: int) -> None:
        self._ordre("tenir", qui, axe, sens, camera, numero)

    def lacher(self, qui: str) -> None:
        self._ordre("lacher", qui)


@pytest.fixture
def b(tmp_path):
    banc = BancApi(tmp_path)
    banc.pilote = FauxPilote()
    banc.cameras = Cameras(
        reglages_cameras(), tmp_path, {"plafond": FausseCamera().ouvrir, "tete": lambda: None}
    )
    services = Services(
        banc.chef,
        banc.registre,
        banc.bilans.acquitter,
        checklist=list,
        cameras=banc.cameras,
        pilote=banc.pilote,
    )
    banc.app = creer_app_de_test(services, banc.dossier)
    yield banc
    banc.registre.fermer()


QUI = f"page web (chef, {LOCAL[0]})"


def test_ordres_du_pilotage(b):
    client = b.client()
    assert client.get("/api/distance").json() == {"actif": False}
    assert client.post("/api/distance/activer").json() == {"actif": True}
    assert client.get("/api/etat").json()["distance"] is True
    corps = {"axe": "x", "sens": -1, "camera": "plafond", "image": 12}
    assert client.post("/api/distance/tenir", json=corps).status_code == 200
    assert client.post("/api/distance/lacher").status_code == 200
    assert client.post("/api/distance/quitter").json() == {"actif": False}
    assert b.pilote.ordres == [
        ("activer", QUI),
        ("tenir", QUI, "x", -1, "plafond", 12),
        ("lacher", QUI),
        ("quitter", QUI),
    ]


def test_ordre_refuse_par_le_pilote(b):
    b.pilote.refuser = "Vidéo figée"
    reponse = b.client().post(
        "/api/distance/tenir", json={"axe": "x", "sens": 1, "camera": "plafond", "image": 1}
    )
    assert reponse.status_code == 409
    assert reponse.json()["detail"] == "Vidéo figée"


def test_tenir_mal_ecrit(b):
    assert b.client().post("/api/distance/tenir", json={"axe": "x"}).status_code == 422


def test_pas_de_go_ni_de_reprise_pendant_le_pilotage(b):
    b.jusqu_au_go()
    client = b.client()
    client.post("/api/distance/activer")
    b.chef.pause()
    for chemin, mot in (("/api/go/essai", "Go"), ("/api/reprendre", "Reprise")):
        reponse = client.post(chemin)
        assert reponse.status_code == 409
        assert reponse.json()["detail"].startswith(f"{mot} refusé : quitter d'abord")
    assert b.chef.en_pause
    assert b.chef.etat().attendent_go == ["essai"]


def test_pilotage_et_cameras_demandent_une_connexion(b):
    client = b.client(nom=None)
    for chemin in ("/api/distance", "/api/cameras", "/api/cameras/plafond/image", "/api/clips"):
        assert client.get(chemin).status_code == 401
    assert client.post("/api/distance/activer").status_code == 401
    assert not b.pilote.ordres


def test_journal_du_pilotage(b):
    for action in ("activer", "mouvement", "arret"):
        b.registre.noter_action_distance(QUI, action, "détail")
    lignes = b.client().get("/api/distance/journal?limite=2").json()
    assert [ligne["action"] for ligne in lignes] == ["arret", "mouvement"]


# ---------------------------------------------------------------- vidéos et clips


def test_image_en_direct(b):
    client = b.client()
    cameras = client.get("/api/cameras").json()
    assert cameras["images_par_s"] == 4
    assert [c["nom"] for c in cameras["cameras"]] == ["plafond", "tete"]
    assert client.get("/api/cameras/plafond/image").status_code == 503
    b.cameras.camera("plafond")._recevoir(fausse_image("un"))
    b.cameras.camera("plafond")._recevoir(fausse_image("deux"))
    reponse = client.get("/api/cameras/plafond/image")
    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == "image/jpeg"
    assert reponse.headers["x-image"] == "2"
    assert reponse.headers["cache-control"] == "no-store"
    assert reponse.content == fausse_image("deux")
    assert client.get("/api/cameras/cuisine/image").status_code == 404


def test_clips(b):
    client = b.client()
    assert client.get("/api/clips").json() == []
    b.cameras.camera("plafond")._recevoir(fausse_image("un"))
    nom = b.cameras.garder_clip().removeprefix("clips/").replace("/", "_")
    clips = client.get("/api/clips").json()
    assert [clip["clip"] for clip in clips] == [nom]
    index = client.get(f"/api/clips/{nom}/plafond").json()
    assert len(index["heures"]) == 1
    assert client.get(f"/api/clips/{nom}/plafond/0").content == fausse_image("un")
    assert client.get(f"/api/clips/{nom}/plafond/1").status_code == 404
    assert client.get(f"/api/clips/{nom}/tete").status_code == 404
    assert client.get("/api/clips/..%2F..%2Fetc/plafond").status_code == 404


def test_sans_cameras_ni_pilote(b):
    services = Services(b.chef, b.registre, b.bilans.acquitter, checklist=list)
    b.app = creer_app_de_test(services, b.dossier)
    client = b.client()
    assert client.get("/api/cameras").json() == {"cameras": [], "images_par_s": 0}
    assert client.get("/api/distance").status_code == 404
    assert client.post("/api/distance/activer").status_code == 404
    assert client.get("/api/etat").json()["distance"] is False
    # Go et Reprise marchent comme avant.
    assert client.post("/api/reprendre").status_code == 200
