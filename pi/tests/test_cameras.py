"""Caméras : découpage de la vidéo, fausses caméras, commande qui plante, clips des alarmes."""

import json
import sys
import time
from datetime import datetime, timedelta

import pytest

from vidange.cameras import (
    Camera,
    Cameras,
    Decoupeur,
    ErreurCamera,
    FausseCamera,
    fausse_image,
)
from vidange.chef import Alarme
from vidange.fiabilite import Bilans
from vidange.registre import Registre
from vidange.reglages import ReglagesBilan, ReglagesCameras

from .test_chef import Horloge, nouveau_chef

DELAI = 5


def attendre(condition, delai_s: float = DELAI) -> None:
    fin = time.monotonic() + delai_s
    while not condition():
        assert time.monotonic() < fin, "attente trop longue"
        time.sleep(0.01)


def reglages(**valeurs) -> ReglagesCameras:
    return ReglagesCameras.model_validate(
        {
            "memoire_s": 60,
            "figee_s": 0.3,
            "relance_s": 0.05,
            "page_images_par_s": 4,
            "clips_gardes_jours": 2,
            "liste": {
                "plafond": {"description": "Caméra du plafond", "commande": ["rien"]},
                "tete": {"description": "Tête de griffe", "commande": ["rien"]},
            },
            **valeurs,
        }
    )


# ---------------------------------------------------------------- découpage


def test_decoupe_des_images_coupees_n_importe_ou():
    images = [fausse_image(f"image {n}") for n in range(5)]
    flux = b"salete au debut" + b"".join(images)
    decoupeur = Decoupeur()
    recues = []
    for debut in range(0, len(flux), 7):
        recues += decoupeur.ajouter(flux[debut : debut + 7])
    assert recues == images


def test_une_vignette_dans_l_image_ne_la_coupe_pas():
    vignette = fausse_image("vignette")
    # Une image avec, dans ses informations (APP1), une vignette qui a sa propre fin FF D9.
    app1 = b"\xff\xe1" + (len(vignette) + 2).to_bytes(2, "big") + vignette
    image = b"\xff\xd8" + app1 + b"\xff\xda\x00\x02\x01\x02\xff\x00\xff\xd0\x03\xff\xd9"
    assert Decoupeur().ajouter(image + fausse_image("suivante")) == [
        image,
        fausse_image("suivante"),
    ]


def test_jpeg_progressif_a_plusieurs_morceaux_de_donnees():
    donnees = b"\xff\xda\x00\x02\x01\x02"
    image = b"\xff\xd8" + donnees + b"\xff\xc4\x00\x02" + donnees + b"\xff\xd9"
    assert Decoupeur().ajouter(image) == [image]


def test_image_abimee_jetee():
    decoupeur = Decoupeur()
    assert decoupeur.ajouter(b"\xff\xd8\x00\x00" + fausse_image("bonne")) == [fausse_image("bonne")]
    assert decoupeur.abimees == 1


def test_image_trop_grosse_jetee():
    decoupeur = Decoupeur(taille_max=100)
    debut = b"\xff\xd8\xff\xda\x00\x02" + b"\x01" * 200
    assert decoupeur.ajouter(debut) == []
    assert decoupeur.abimees == 1
    assert decoupeur.ajouter(fausse_image("ok")) == [fausse_image("ok")]


# ---------------------------------------------------------------- une caméra


def test_images_numerotees_et_memoire_tournante():
    horloge = Horloge()
    camera = Camera("plafond", "", FausseCamera().ouvrir, reglages(memoire_s=10), horloge)
    for donnees in (b"a", b"b", b"c"):
        camera._recevoir(donnees)
        horloge.t += 4
    assert [image.numero for image in camera.memoire()] == [1, 2, 3]
    camera._recevoir(b"d")  # t = 12 : l'image n° 1 (t = 0) a plus de 10 s
    assert [image.numero for image in camera.memoire()] == [2, 3, 4]
    assert camera.derniere().donnees == b"d"
    assert camera.age(2) == 8
    assert camera.age(1) is None
    assert camera.age(99) is None


def test_fausse_camera_figee_puis_relancee():
    fausse = FausseCamera(images_par_s=50)
    camera = Camera("plafond", "", fausse.ouvrir, reglages())
    camera.demarrer()
    try:
        attendre(lambda: camera.derniere() is not None)
        fausse.figee = True
        attendre(lambda: (camera.silence() or 0) > 0.35)
        camera.surveiller()
        attendre(lambda: fausse.ouvertures == 2)
        assert camera.relances == 1
        assert "aucune image depuis" in camera.derniere_erreur
        fausse.figee = False
        numero = camera.derniere().numero
        attendre(lambda: camera.derniere().numero > numero)
    finally:
        camera.arreter()


def test_camera_en_panne_reessayee():
    fausse = FausseCamera()
    fausse.en_panne = True
    camera = Camera("plafond", "", fausse.ouvrir, reglages())
    camera.demarrer()
    try:
        attendre(lambda: "introuvable" in camera.derniere_erreur)
        fausse.en_panne = False
        attendre(lambda: camera.derniere() is not None)
    finally:
        camera.arreter()


ECRIVAIN = """
import sys, time
debut = b"\\xff\\xd8\\xff\\xfe\\x00\\x05abc\\xff\\xda\\x00\\x02"
for numero in range(3):
    sys.stdout.buffer.write(debut + bytes([numero]) + b"\\xff\\xd9")
    sys.stdout.buffer.flush()
    time.sleep(0.01)
sys.stderr.write("plus de film\\n")
"""


def test_vraie_commande_qui_s_arrete_et_relancee():
    camera = Camera.depuis_commande(
        "plafond", "", [sys.executable, "-c", ECRIVAIN], reglages(relance_s=0.05)
    )
    camera.demarrer()
    try:
        attendre(lambda: camera.relances >= 1 and len(camera.memoire()) >= 4)
        assert camera.memoire()[0].donnees.endswith(b"\x00\xff\xd9")
        assert camera.derniere_erreur == "plus de film"
    finally:
        camera.arreter()


def test_commande_introuvable():
    camera = Camera.depuis_commande("plafond", "", ["commande-qui-n-existe-pas"], reglages())
    camera.demarrer()
    try:
        attendre(lambda: "lancement impossible" in camera.derniere_erreur)
    finally:
        camera.arreter()


# ---------------------------------------------------------------- toutes les caméras et clips


class Moment:
    def __init__(self) -> None:
        self.quand = datetime(2026, 10, 27, 15, 30, 12)

    def __call__(self) -> datetime:
        return self.quand


@pytest.fixture
def cameras(tmp_path):
    horloge, moment = Horloge(), Moment()
    sources = {"plafond": FausseCamera().ouvrir, "tete": FausseCamera().ouvrir}
    cameras = Cameras(reglages(), tmp_path, sources, horloge, moment)
    cameras.horloge, cameras.moment = horloge, moment
    return cameras


def test_clip_garde_et_relu(cameras, tmp_path):
    plafond = cameras.camera("plafond")
    for donnees in (fausse_image("un"), fausse_image("deux")):
        plafond._recevoir(donnees)
        cameras.horloge.t += 0.5
    assert cameras.garder_clip() == "clips/2026-10-27/153012"
    # Deuxième clip à la même seconde.
    assert cameras.garder_clip("essai") == "clips/2026-10-27/153012-2"
    resume = json.loads((tmp_path / "clips/2026-10-27/153012/clip.json").read_text())
    assert resume["cameras"] == {"plafond": {"images": 2, "duree_s": 0.5}}
    assert not (tmp_path / "clips/2026-10-27/153012/tete.mjpeg").exists()
    mjpeg = (tmp_path / "clips/2026-10-27/153012/plafond.mjpeg").read_bytes()
    assert mjpeg == fausse_image("un") + fausse_image("deux")

    clips = cameras.lister_clips(10)
    assert [clip["clip"] for clip in clips] == ["2026-10-27_153012-2", "2026-10-27_153012"]
    assert clips[0]["raison"] == "essai"
    assert [c["clip"] for c in cameras.lister_clips(10, avant="2026-10-27_153012-2")] == [
        "2026-10-27_153012"
    ]
    index = cameras.index_du_clip("2026-10-27_153012", "plafond")
    assert len(index) == 2
    assert cameras.image_du_clip("2026-10-27_153012", "plafond", 1) == fausse_image("deux")


def test_pas_de_clip_sans_image(cameras, tmp_path):
    assert cameras.garder_clip() is None
    assert cameras.lister_clips(10) == []


def test_chemins_interdits_dans_les_clips(cameras):
    cameras.camera("plafond")._recevoir(fausse_image("un"))
    cameras.garder_clip()
    for clip, camera in (
        ("../../etc", "plafond"),
        ("2026-10-27_153012", "../clip"),
        ("2026-10-27_153012", "tete"),
        ("2026-10-28_000000", "plafond"),
    ):
        with pytest.raises(ErreurCamera):
            cameras.index_du_clip(clip, camera)
    with pytest.raises(ErreurCamera, match="absente"):
        cameras.image_du_clip("2026-10-27_153012", "plafond", 5)
    with pytest.raises(ErreurCamera, match="inconnue"):
        cameras.derniere("cuisine")
    assert cameras.age("cuisine", 1) is None


def test_vieux_clips_effaces(cameras, tmp_path):
    cameras.camera("plafond")._recevoir(fausse_image("un"))
    cameras.garder_clip()
    cameras.moment.quand += timedelta(days=3)
    cameras.garder_clip()
    assert not (tmp_path / "clips/2026-10-27").exists()
    assert (tmp_path / "clips/2026-10-30").exists()


def test_constats_et_description(cameras):
    assert {c.niveau for c in cameras.constats()} == {"attention"}
    assert "jamais lancée" in cameras.constats()[0].texte
    cameras.camera("plafond")._recevoir(fausse_image("un"))
    cameras.camera("tete")._recevoir(fausse_image("un"))
    assert {c.niveau for c in cameras.constats()} == {"ok"}
    cameras.horloge.t += 1
    tete = cameras.decrire()[1]
    assert tete["nom"] == "tete" and not tete["marche"] and tete["silence_s"] == 1


def test_sans_camera(tmp_path):
    cameras = Cameras(reglages(liste={}), tmp_path)
    assert "aucune caméra" in cameras.constats()[0].texte


def test_marche_et_arret(tmp_path):
    fausses = {"plafond": FausseCamera(images_par_s=50), "tete": FausseCamera(images_par_s=50)}
    cameras = Cameras(reglages(), tmp_path, {nom: f.ouvrir for nom, f in fausses.items()})
    cameras.demarrer()
    try:
        attendre(lambda: all(cameras.derniere(nom) is not None for nom in fausses))
        fausses["tete"].figee = True
        # La surveillance (toutes les 0,1 s ici) relance la caméra figée.
        attendre(lambda: fausses["tete"].ouvertures == 2)
    finally:
        cameras.arreter()


def test_clip_dans_le_bilan_d_une_alarme(cameras, tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    try:
        bilans = Bilans(
            tmp_path, ReglagesBilan(lignes_journal=0), registre, nouveau_chef(Horloge())
        )
        # Comme au démarrage du programme (vidange/demarrage.py).
        bilans.collecteurs["clip_video"] = lambda: cameras.garder_clip("alarme")
        cameras.camera("plafond")._recevoir(fausse_image("un"))
        alarme = Alarme("essai", "un", "trop long", "regarder", "2026-10-27T15:30:12")
        numero = bilans.traiter(alarme)
        chemin = registre.lire("SELECT bilan FROM alarmes WHERE id = ?", (numero,))[0]["bilan"]
        bilan = json.loads((tmp_path / chemin).read_text(encoding="utf-8"))
        assert bilan["clip_video"] == "clips/2026-10-27/153012"
        assert (tmp_path / bilan["clip_video"] / "plafond.mjpeg").is_file()
    finally:
        registre.fermer()
