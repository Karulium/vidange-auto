"""Mises à jour lancées depuis la page web : machine à l'arrêt, un travail à la fois, API."""

import threading

import pytest

from vidange.api import Services, creer_app
from vidange.fluidnc import EtatCarte
from vidange.mises_a_jour import (
    CarteEsp32,
    ErreurMiseAJour,
    FausseCarteEsp32,
    MisesAJour,
    faux_programme,
)
from vidange.reglages import ReglagesMajPi, ReglagesMisesAJour

from .test_api import CLE, BancApi, reglages_api
from .test_chef import tour
from .test_maj_cartes import REGLAGES_FLUIDNC, reglages_cartes


class FausseLiaison:
    def __init__(self) -> None:
        self.etat = EtatCarte(connectee=True, etat="Idle")
        self.appels: list[str] = []

    def arreter(self) -> None:
        self.appels.append("arreter")

    def demarrer(self) -> None:
        self.appels.append("demarrer")


class FauxPi:
    """Le programme du Pi vu par MisesAJour."""

    distante = "origin/main"

    def __init__(self) -> None:
        self.court = "aaaaaaa"
        self.nouvelles = [{"commit": "b" * 40, "court": "bbbbbbb", "date": "", "titre": "T2"}]
        self.bloquer = threading.Event()
        self.bloquer.set()
        self.rate = False

    def version(self) -> dict:
        return {"commit": self.court * 6, "court": self.court, "date": "", "titre": "T1"}

    def avant(self):
        return None

    def chercher(self) -> list:
        return self.nouvelles

    def installer(self, qui: str) -> str:
        self.bloquer.wait(5)
        if self.rate:
            raise ErreurMiseAJour("la nouvelle version ne passe pas")
        self.court = "bbbbbbb"
        return "programme du Pi : aaaaaaa → bbbbbbb"

    def revenir(self, qui: str) -> str:
        self.court = "aaaaaaa"
        return "programme du Pi revenu"


class FauxPilote:
    actif = False


def reglages_maj() -> ReglagesMisesAJour:
    return ReglagesMisesAJour(
        cartes=reglages_cartes(),
        pi=ReglagesMajPi(depot="origin", branche="main", duree_max_s=60),
    )


class BancMaj(BancApi):
    """L'API avec le chef d'essai, une fausse carte « portique » et un faux programme du Pi."""

    def __init__(self, dossier) -> None:
        super().__init__(dossier)
        self.faux = FausseCarteEsp32()
        self.liaison = FausseLiaison()
        self.pi = FauxPi()
        self.pilote = FauxPilote()
        self.redemarrages = 0
        self.fluidnc = dossier / "fluidnc"
        self.fluidnc.mkdir()
        carte = CarteEsp32(
            "portique",
            reglages_cartes(),
            dossier / "maj" / "copies",
            self.faux.trouver_port,
            self.faux.ouvrir,
            self.faux.esptool,
        )
        self.maj = MisesAJour(
            reglages_maj(),
            dossier / "maj",
            {"portique": carte},
            self.pi,
            self.chef,
            {"portique": self.liaison},
            self.fluidnc,
            self.registre,
            self.pilote,
            redemarrer=self.redemarrer,
        )
        services = Services(
            self.chef,
            self.registre,
            self.bilans.acquitter,
            checklist=list,
            pilote=None,
            mises_a_jour=self.maj,
        )
        self.app = creer_app(services, reglages_api(), CLE)

    def redemarrer(self) -> None:
        self.redemarrages += 1

    def envoyer_programme(self, nom="fluidnc-3.9.5.bin", version="3.9.5 FluidNC v3.9.5"):
        return self.client().post(
            "/api/mises-a-jour/programmes", params={"nom": nom}, content=faux_programme(version)
        )

    def dernier(self) -> dict:
        self.maj.attendre(10)
        return self.client().get("/api/mises-a-jour").json()["dernier"]


@pytest.fixture
def b(tmp_path):
    banc = BancMaj(tmp_path)
    yield banc
    banc.registre.fermer()


# ---------------------------------------------------------------- machine à l'arrêt


def test_module_qui_attend_le_go_de_sa_premiere_etape_ne_gene_pas(b):
    # Le module d'essai vient d'être lancé : rien n'a bougé.
    assert b.maj.refus() is None


def test_refus_pendant_un_cycle_en_alarme_en_mouvement_ou_a_distance(b):
    b.banc.drapeaux["pret"] = True
    tour(b.chef, b.horloge)
    tour(b.chef, b.horloge)
    assert "cycle en cours : « essai » (étape « un »)" in b.maj.refus()
    with pytest.raises(ErreurMiseAJour, match="refusée : cycle en cours"):
        b.maj.installer_pi("essai")

    b.chef.abandonner("essai")
    assert b.maj.refus() is None
    b.liaison.etat = EtatCarte(connectee=True, etat="Jog")
    assert b.maj.refus() == "axes en mouvement (cartes portique)"
    b.liaison.etat = EtatCarte(connectee=True, etat="Hold:1")
    assert b.maj.refus() is not None
    b.liaison.etat = EtatCarte(connectee=True, etat="Hold:0")
    assert b.maj.refus() is None
    b.liaison.etat = EtatCarte(connectee=True, etat="Alarm")
    assert b.maj.refus() is None
    b.pilote.actif = True
    assert b.maj.refus() == "pilotage à distance en cours"


# ---------------------------------------------------------------- cartes


def test_programme_envoye_puis_ecrit_dans_la_carte(b):
    reponse = b.envoyer_programme()
    assert reponse.status_code == 200, reponse.text
    etat = b.client().get("/api/mises-a-jour").json()
    assert [p["nom"] for p in etat["programmes"]] == ["fluidnc-3.9.5.bin"]
    assert etat["cartes"][0]["nom"] == "portique" and etat["cartes"][0]["copies"] == []

    reponse = b.client().post(
        "/api/mises-a-jour/cartes/portique/programme", json={"fichier": "fluidnc-3.9.5.bin"}
    )
    assert reponse.status_code == 200, reponse.text
    dernier = b.dernier()
    assert dernier["reussi"] is True, dernier
    assert b.faux.version == "3.9.5 FluidNC v3.9.5"
    assert dernier["etapes"][0] == "Machine mise en pause"
    assert "Liaison ordinaire avec la carte arrêtée" in dernier["etapes"]
    assert b.liaison.appels == ["arreter", "demarrer"]
    # La machine reste en pause après : Reprendre quand on veut.
    assert b.chef.en_pause
    (note,) = b.registre.lire("SELECT * FROM reglages_appliques")
    assert (note["fichier"], note["reglage"], note["qui"]) == (
        "carte portique",
        "programme",
        "page web (192.168.1.20)",
    )
    assert note["ancien"] == '"3.9.4 FluidNC v3.9.4"' and note["nouveau"] == '"fluidnc-3.9.5.bin"'
    etat = b.client().get("/api/mises-a-jour").json()
    assert len(etat["cartes"][0]["copies"]) == 1 and etat["en_cours"] is None


def test_programme_rate_la_liaison_repart_quand_meme(b):
    b.envoyer_programme("casse.bin", "CASSE")
    b.client().post("/api/mises-a-jour/cartes/portique/programme", json={"fichier": "casse.bin"})
    dernier = b.dernier()
    assert dernier["reussi"] is False and "ancienne version est remise" in dernier["message"]
    assert b.liaison.appels == ["arreter", "demarrer"]
    assert b.registre.lire("SELECT * FROM reglages_appliques") == []


def test_fichiers_de_programme_refuses_et_vieux_effaces(b):
    assert b.envoyer_programme("../x.bin").status_code == 409
    assert b.envoyer_programme("x.exe").status_code == 409
    reponse = b.client().post(
        "/api/mises-a-jour/programmes", params={"nom": "texte.bin"}, content=b"bonjour"
    )
    assert reponse.status_code == 409 and "pas un programme" in reponse.json()["detail"]
    for numero in range(3):
        assert b.envoyer_programme(f"v{numero}.bin").status_code == 200
    noms = {p["nom"] for p in b.maj.programmes()}
    assert len(noms) == 2 and "v2.bin" in noms
    reponse = b.client().post(
        "/api/mises-a-jour/cartes/portique/programme", json={"fichier": "absent.bin"}
    )
    assert reponse.status_code == 409


def test_programme_trop_gros_refuse_avant_lecture(b):
    reponse = b.client().post(
        "/api/mises-a-jour/programmes",
        params={"nom": "gros.bin"},
        content=b"\xe9" * (2 * 1024 * 1024),
    )
    assert reponse.status_code == 413


def test_reglages_et_retour_a_une_copie(b):
    reponse = b.client().post("/api/mises-a-jour/cartes/portique/reglages")
    assert reponse.status_code == 409 and "fluidnc/portique.yaml" in reponse.json()["detail"]
    (b.fluidnc / "portique.yaml").write_bytes(REGLAGES_FLUIDNC)
    assert b.client().get("/api/mises-a-jour").json()["cartes"][0]["reglages"] is True
    b.client().post("/api/mises-a-jour/cartes/portique/reglages")
    assert b.dernier()["reussi"] is True
    assert b.faux.fichiers["config.yaml"].startswith(REGLAGES_FLUIDNC)

    reponse = b.client().post("/api/mises-a-jour/cartes/portique/revenir", json={"copie": "x"})
    assert reponse.status_code == 409
    b.client().post("/api/mises-a-jour/cartes/portique/revenir", json={})
    assert b.dernier()["reussi"] is True
    assert "config.yaml" not in b.faux.fichiers
    reglages = [n["reglage"] for n in b.registre.lire("SELECT * FROM reglages_appliques")]
    assert reglages == ["réglages FluidNC", "retour à une copie"]


def test_carte_inconnue(b):
    reponse = b.client().post("/api/mises-a-jour/cartes/inconnue/revenir", json={})
    assert reponse.status_code == 409 and "inconnue" in reponse.json()["detail"]


# ---------------------------------------------------------------- programme du Pi


def test_chercher_puis_installer_redemarre_le_programme(b):
    b.client().post("/api/mises-a-jour/pi/chercher")
    assert b.dernier()["message"] == "1 changement(s) à installer"
    assert b.client().get("/api/mises-a-jour").json()["pi"]["nouvelles"][0]["titre"] == "T2"
    b.client().post("/api/mises-a-jour/pi/installer")
    dernier = b.dernier()
    assert dernier["reussi"] is True and b.redemarrages == 1
    assert "redémarre" in dernier["etapes"][-1]
    (note,) = b.registre.lire("SELECT * FROM reglages_appliques")
    assert (note["fichier"], note["ancien"], note["nouveau"]) == (
        "programme du Pi",
        '"aaaaaaa"',
        '"bbbbbbb"',
    )
    b.client().post("/api/mises-a-jour/pi/revenir")
    assert b.dernier()["reussi"] is True and b.redemarrages == 2


def test_installation_ratee_ne_redemarre_pas(b):
    b.pi.rate = True
    b.client().post("/api/mises-a-jour/pi/installer")
    assert b.dernier()["reussi"] is False and b.redemarrages == 0


def test_chercher_est_permis_pendant_un_cycle(b):
    b.banc.drapeaux["pret"] = True
    tour(b.chef, b.horloge)
    tour(b.chef, b.horloge)
    assert b.client().post("/api/mises-a-jour/pi/chercher").status_code == 200
    assert b.dernier()["reussi"] is True
    assert not b.chef.en_pause


def test_une_seule_a_la_fois_et_rien_ne_bouge_pendant(b):
    b.pi.bloquer.clear()
    assert b.client().post("/api/mises-a-jour/pi/installer").status_code == 200
    client = b.client()
    assert client.get("/api/etat").json()["mise_a_jour"] is True
    reponse = client.post("/api/mises-a-jour/pi/chercher")
    assert reponse.status_code == 409 and "déjà en cours" in reponse.json()["detail"]
    assert "en cours" in client.get("/api/mises-a-jour").json()["refus"]
    reponse = client.post("/api/reprendre")
    assert reponse.status_code == 409 and "mise à jour" in reponse.json()["detail"]
    assert client.post("/api/go/essai").status_code == 409
    b.pi.bloquer.set()
    assert b.dernier()["reussi"] is True
    assert client.get("/api/etat").json()["mise_a_jour"] is False


def test_sans_mises_a_jour(tmp_path):
    banc = BancApi(tmp_path)
    try:
        assert banc.client().get("/api/mises-a-jour").status_code == 404
        assert banc.client().get("/api/etat").json()["mise_a_jour"] is False
    finally:
        banc.registre.fermer()
