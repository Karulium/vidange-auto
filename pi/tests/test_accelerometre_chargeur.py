"""Mise à jour du programme du RP2040 de l'accéléromètre par son fil série (tâche 16)."""

import re
import struct
from pathlib import Path

import pytest

from vidange.accelerometre import outil as outil_accelerometre
from vidange.accelerometre.chargeur import ChargeurAccelerometre, ErreurChargeur
from vidange.accelerometre.faux import ADRESSE_PROGRAMME, FauxRp2040, faux_fichier
from vidange.accelerometre.fichier_programme import (
    FICHE_TAILLE,
    ErreurFichier,
    Fiche,
    assembler,
    lire_fichier,
    main,
    uf2,
)
from vidange.accelerometre.liaison import LiaisonAccelerometre
from vidange.accelerometre.protocole import LIGNE_MAX_CHARGEUR
from vidange.mises_a_jour import ErreurMiseAJour
from vidange.reglages import charger_reglages

from .conftest import DOSSIER_PI
from .test_accelerometre_liaison import Horloge
from .test_maj_gestion import BancMaj
from .test_reglages import erreur_de, remplacer

DOSSIER_ACCELEROMETRE = DOSSIER_PI.parent / "accelerometre"


@pytest.fixture
def accelerometre(reglages: Path):
    return charger_reglages(reglages).accelerometre


def preparer(accelerometre, installe: bytes | None = None):
    rp2040 = FauxRp2040(accelerometre, installe)
    return rp2040, ChargeurAccelerometre(accelerometre, rp2040.ouvrir, horloge=Horloge())


# ---------------------------------------------------------------- fichier du programme


def test_fichier_du_programme_fiche_puis_programme():
    fichier = assembler(b"\x01\x02" * 300, ADRESSE_PROGRAMME, "3f2a9c1")
    fiche, programme = lire_fichier(fichier)
    assert fiche == Fiche(ADRESSE_PROGRAMME, 600, fiche.crc, "3f2a9c1")
    assert programme == b"\x01\x02" * 300
    assert fichier[:4] == b"ACCL" and len(fichier) == FICHE_TAILLE + 600
    # Même contrôle de fiche que le programme du RP2040 (accelerometre/tests/essais_chargeur.c).
    octets = Fiche(0x10009000, 1234, 0xDEADBEEF, "3f2a9c1").octets()
    assert struct.unpack("<I", octets[-4:])[0] == 0x6A3F9EB5


@pytest.mark.parametrize(
    ("abimer", "message"),
    [
        (lambda f: b"XXXX" + f[4:], "ce n'est pas un programme de l'accéléromètre"),
        (lambda f: f[:30] + b"!" + f[31:], "fiche du programme abîmée"),
        (lambda f: f[:-1], "fichier coupé ou trop long"),
        (lambda f: f[:-1] + bytes([f[-1] ^ 1]), "programme abîmé (contrôle faux)"),
        (lambda f: f[:100], "fiche absente"),
    ],
)
def test_fichier_abime_refuse(abimer, message):
    with pytest.raises(ErreurFichier, match=re.escape(message)):
        lire_fichier(abimer(faux_fichier()))


def test_nom_du_programme_refuse():
    with pytest.raises(ErreurFichier, match="nom de programme refusé"):
        assembler(b"\x00", ADRESSE_PROGRAMME, "avec espace")


def test_uf2_pour_le_rp2040():
    contenu = uf2([(0x10000000, b"\xaa" * 300), (0x10008000, b"\xbb" * 10)])
    assert len(contenu) == 3 * 512
    blocs = [contenu[i : i + 512] for i in range(0, len(contenu), 512)]
    adresses = []
    for numero, bloc in enumerate(blocs):
        debut, deuxieme, drapeaux, adresse, taille, n, total, famille = struct.unpack(
            "<8I", bloc[:32]
        )
        assert (debut, deuxieme, struct.unpack("<I", bloc[-4:])[0]) == (
            0x0A324655,
            0x9E5D5157,
            0x0AB16F30,
        )
        assert (drapeaux, taille, n, total, famille) == (0x2000, 256, numero, 3, 0xE48BFF56)
        adresses.append(adresse)
    assert adresses == [0x10000000, 0x10000100, 0x10008000]
    assert blocs[1][32 : 32 + 44] == b"\xaa" * 44 and blocs[1][32 + 44] == 0xFF
    with pytest.raises(ErreurFichier, match="pas au début d'une page"):
        uf2([(0x10000010, b"\x00")])


def test_fabrication_par_cmake(tmp_path: Path, capsys):
    (tmp_path / "chargeur.bin").write_bytes(b"\x11" * 1000)
    (tmp_path / "programme.bin").write_bytes(b"\x22" * 3000)
    arguments = [
        "--chargeur",
        str(tmp_path / "chargeur.bin"),
        "--programme",
        str(tmp_path / "programme.bin"),
        "--adresse-flash",
        "0x10000000",
        "--adresse-fiche",
        "0x10008000",
        "--adresse-programme",
        "0x10009000",
        "--nom",
        "essai-1",
        "--sortie-bin",
        str(tmp_path / "accelerometre.bin"),
        "--sortie-uf2",
        str(tmp_path / "accelerometre-complet.uf2"),
    ]
    assert main(arguments) == 0
    assert "Programme « essai-1 » : 3000 octets" in capsys.readouterr().out
    fiche, programme = lire_fichier((tmp_path / "accelerometre.bin").read_bytes())
    assert (fiche.nom, fiche.adresse, programme) == ("essai-1", 0x10009000, b"\x22" * 3000)
    # Chargeur (4 pages), fiche (1), programme (12).
    assert len((tmp_path / "accelerometre-complet.uf2").read_bytes()) == (4 + 1 + 12) * 512

    # Un chargeur trop gros pour sa place est refusé.
    (tmp_path / "chargeur.bin").write_bytes(b"\x11" * 0x8001)
    assert main(arguments) == 1
    assert "ne tient pas dans sa place" in capsys.readouterr().err


def test_memes_nombres_que_le_programme_du_rp2040():
    trame = (DOSSIER_ACCELEROMETRE / "src" / "liaison_trame.h").read_text(encoding="utf-8")
    assert f"#define LIAISON_TRAME_MAX {LIGNE_MAX_CHARGEUR}\n" in trame
    plan = (DOSSIER_ACCELEROMETRE / "plan_memoire.cmake").read_text(encoding="utf-8")
    flash = int(re.search(r"PLAN_ADRESSE_FLASH (0x\w+)", plan).group(1), 16)
    chargeur = int(re.search(r"PLAN_TAILLE_CHARGEUR (0x\w+)", plan).group(1), 16)
    assert ADRESSE_PROGRAMME == flash + chargeur + 0x1000


# ---------------------------------------------------------------- mise à jour par le fil


def test_mise_a_jour_complete(accelerometre):
    rp2040, chargeur = preparer(accelerometre)
    ancien = rp2040.installe
    etapes: list[str] = []
    copies: list[bytes] = []
    resultat = chargeur.mettre_a_jour(faux_fichier("nouveau", 5000), etapes.append, copies.append)
    assert (resultat.avant, resultat.apres) == ("origine", "nouveau")
    assert copies == [ancien]  # copie relue page par page, identique
    assert rp2040.installe == faux_fichier("nouveau", 5000)
    assert rp2040.mode == "programme" and rp2040.redemarrages == 2
    assert etapes[1] == "Le programme du RP2040 redémarre dans le chargeur (« OK » coupé)"
    assert "Programme écrit et vérifié par le chargeur (contrôle juste)" in etapes
    assert etapes[-1].startswith("Le programme répond : « nouveau »")
    assert chargeur.version() == f"VERSION nom=nouveau taille=5000 crc={resultat_crc(rp2040)}"


def resultat_crc(rp2040) -> str:
    return f"{Fiche.lire(rp2040.installe).crc:08X}"


def test_mise_a_jour_depuis_le_chargeur_sans_programme(accelerometre):
    rp2040, chargeur = preparer(accelerometre, installe=b"")  # programme abîmé
    rp2040.mode = "chargeur"
    etapes: list[str] = []
    copies: list[bytes] = []
    chargeur.mettre_a_jour(faux_fichier("nouveau"), etapes.append, copies.append)
    assert copies == []
    assert "Pas de copie du programme présent (abime)" in etapes
    assert rp2040.mode == "programme" and rp2040.installe == faux_fichier("nouveau")


def test_reponses_perdues_reposees(accelerometre):
    rp2040, chargeur = preparer(accelerometre)
    rp2040.mode = "chargeur"
    rp2040.abimer = 3  # trois réponses abîmées par un parasite : le Pi redemande
    chargeur.mettre_a_jour(faux_fichier("nouveau"), lambda _: None)
    assert rp2040.installe == faux_fichier("nouveau")


def test_fichier_refuse_avant_de_toucher_au_rp2040(accelerometre):
    rp2040, chargeur = preparer(accelerometre)
    with pytest.raises(ErreurChargeur, match="fichier refusé : programme abîmé"):
        chargeur.mettre_a_jour(faux_fichier()[:-1] + b"\x00", lambda _: None)
    assert rp2040.questions == [] and rp2040.mode == "programme"


def test_ecriture_ratee_le_programme_d_avant_est_remis(accelerometre):
    rp2040, chargeur = preparer(accelerometre)
    ancien = rp2040.installe
    rp2040.panne_ecriture = 1
    etapes: list[str] = []
    with pytest.raises(ErreurChargeur, match="écriture ratée ; le programme d'avant a été remis"):
        chargeur.mettre_a_jour(faux_fichier("nouveau"), etapes.append)
    assert "Remise du programme d'avant (copie)" in etapes
    assert rp2040.installe == ancien and rp2040.mode == "programme"


def test_programme_fabrique_pour_une_autre_adresse(accelerometre):
    rp2040, chargeur = preparer(accelerometre)
    autre = assembler(b"\x00" * 100, 0x10000000, "sans-chargeur")
    with pytest.raises(
        ErreurChargeur,
        match="l'adresse 10000000, pas 10009000 ; le programme d'avant a été relancé",
    ):
        chargeur.mettre_a_jour(autre, lambda _: None)
    assert rp2040.installe == faux_fichier() and rp2040.mode == "programme"


def test_rp2040_muet(accelerometre):
    rp2040, chargeur = preparer(accelerometre)
    rp2040.muet = True
    with pytest.raises(ErreurChargeur, match="le chargeur du RP2040 ne répond pas"):
        chargeur.mettre_a_jour(faux_fichier("nouveau"), lambda _: None)
    rp2040.debrancher()
    with pytest.raises(ErreurChargeur, match="port série impossible à ouvrir"):
        chargeur.mettre_a_jour(faux_fichier("nouveau"), lambda _: None)


def test_programme_d_avant_le_chargeur(accelerometre):
    rp2040, chargeur = preparer(accelerometre)
    rp2040._repondre = lambda question: "ERREUR commande inconnue"  # programme de la tâche 15
    with pytest.raises(ErreurChargeur, match="Charger une fois accelerometre-complet.uf2"):
        chargeur.mettre_a_jour(faux_fichier("nouveau"), lambda _: None)


def test_sortie_ok_du_chargeur_differente(accelerometre):
    rp2040, chargeur = preparer(accelerometre)
    rp2040.sortie_ok = 7
    etapes: list[str] = []
    chargeur.mettre_a_jour(faux_fichier("nouveau"), etapes.append)
    assert any("le chargeur coupe « OK » sur la broche 7" in etape for etape in etapes)


# ---------------------------------------------------------------- liaison ordinaire


def test_la_liaison_prete_le_fil_et_voit_le_chargeur(accelerometre):
    rp2040 = FauxRp2040(accelerometre)
    liaison = LiaisonAccelerometre(accelerometre, rp2040.ouvrir, horloge=Horloge())
    liaison.tour()
    assert liaison.en_ligne
    with liaison.preter_le_fil():
        avant = len(rp2040.questions)
        liaison.tour()
        assert len(rp2040.questions) == avant  # elle se tait
        assert liaison.constats()[0].texte == "mise à jour du programme en cours"
    # Resté dans le chargeur (mise à jour pas finie) : dit dans la check-list.
    rp2040.mode = "chargeur"
    liaison.tour()
    assert liaison.en_chargeur and not liaison.en_ligne
    (constat,) = liaison.constats()
    assert constat.niveau == "attention" and "dans son chargeur" in constat.texte
    rp2040.mode = "programme"
    liaison.tour()
    assert liaison.en_ligne and not liaison.en_chargeur


# ---------------------------------------------------------------- page web


@pytest.fixture
def b(tmp_path, reglages: Path):
    banc = BancMaj(tmp_path)
    accelerometre = charger_reglages(reglages).accelerometre
    banc.rp2040 = FauxRp2040(accelerometre)
    banc.liaison_acc = LiaisonAccelerometre(accelerometre, banc.rp2040.ouvrir, horloge=Horloge())
    banc.maj.accelerometre = ChargeurAccelerometre(
        accelerometre, banc.rp2040.ouvrir, horloge=Horloge()
    )
    banc.maj.liaison_accelerometre = banc.liaison_acc
    yield banc
    banc.registre.fermer()


def envoyer(b, nom: str, contenu: bytes):
    return b.client().post("/api/mises-a-jour/programmes", params={"nom": nom}, content=contenu)


def test_page_web_ecrit_puis_revient(b):
    assert envoyer(b, "accelerometre-nouveau.bin", faux_fichier("nouveau")).status_code == 200
    b.envoyer_programme()  # un programme d'ESP32 à côté
    etat = b.client().get("/api/mises-a-jour").json()
    assert {p["nom"]: p["pour"] for p in etat["programmes"]} == {
        "accelerometre-nouveau.bin": "accelerometre",
        "fluidnc-3.9.5.bin": "esp32",
    }
    assert etat["accelerometre"] == {"copies": []}

    reponse = b.client().post(
        "/api/mises-a-jour/accelerometre/programme", json={"fichier": "accelerometre-nouveau.bin"}
    )
    assert reponse.status_code == 200, reponse.text
    dernier = b.dernier()
    assert dernier["reussi"] is True, dernier
    assert dernier["etapes"][0] == "Machine mise en pause"
    assert "Liaison ordinaire avec l'accéléromètre arrêtée" in dernier["etapes"]
    assert b.rp2040.installe == faux_fichier("nouveau")
    (note,) = b.registre.lire("SELECT * FROM reglages_appliques")
    assert (note["fichier"], note["reglage"]) == ("accéléromètre", "programme")
    assert (note["ancien"], note["nouveau"]) == ('"origine"', '"nouveau"')
    (copie,) = b.client().get("/api/mises-a-jour").json()["accelerometre"]["copies"]
    assert copie["version"] == "origine" and copie["nom"].endswith("-origine.bin")

    # La liaison ordinaire reprend après (le RP2040 a redémarré).
    b.liaison_acc.tour()
    assert b.liaison_acc.en_ligne

    reponse = b.client().post("/api/mises-a-jour/accelerometre/revenir", json={})
    assert reponse.status_code == 200, reponse.text
    assert b.dernier()["reussi"] is True
    assert b.rp2040.installe == faux_fichier()
    copies = b.client().get("/api/mises-a-jour").json()["accelerometre"]["copies"]
    assert {c["version"] for c in copies} == {"origine", "nouveau"}


def test_page_web_refus(b):
    reponse = envoyer(b, "accelerometre.bin", faux_fichier()[:-3])
    assert reponse.status_code == 409 and "fichier coupé" in reponse.text
    b.envoyer_programme()
    with pytest.raises(ErreurMiseAJour, match="n'est pas un programme de l'accéléromètre"):
        b.maj.ecrire_accelerometre("fluidnc-3.9.5.bin", "essai")
    with pytest.raises(ErreurMiseAJour, match="pas de fichier de programme « absent.bin »"):
        b.maj.ecrire_accelerometre("absent.bin", "essai")
    with pytest.raises(ErreurMiseAJour, match="pas de copie « récente » de l'accéléromètre"):
        b.maj.revenir_accelerometre(None, "essai")
    b.pilote.actif = True
    envoyer(b, "accelerometre.bin", faux_fichier())
    with pytest.raises(ErreurMiseAJour, match="pilotage à distance en cours"):
        b.maj.ecrire_accelerometre("accelerometre.bin", "essai")


def test_page_web_mise_a_jour_ratee(b):
    envoyer(b, "accelerometre.bin", faux_fichier("nouveau"))
    b.rp2040.muet = True
    b.maj.ecrire_accelerometre("accelerometre.bin", "essai")
    dernier = b.dernier()
    assert dernier["reussi"] is False
    assert dernier["message"].startswith("accéléromètre : le chargeur du RP2040 ne répond pas")
    assert b.registre.lire("SELECT * FROM reglages_appliques") == []


# ---------------------------------------------------------------- outil et réglages


def test_outil_version_et_ecrire(reglages: Path, tmp_path: Path, capsys):
    base = ["--reglages", str(reglages), "--faux"]
    assert outil_accelerometre.main([*base, "version"]) == 0
    assert "VERSION nom=origine taille=3000" in capsys.readouterr().out
    fichier = tmp_path / "accelerometre.bin"
    fichier.write_bytes(faux_fichier("nouveau"))
    arguments = [*base, "ecrire", str(fichier), "--copies", str(tmp_path), "--attendre", "1"]
    assert outil_accelerometre.main(arguments) == 0
    sortie = capsys.readouterr().out
    assert "Couper puis remettre l'alimentation du boîtier" in sortie
    assert "Fini : programme « nouveau »" in sortie
    (copie,) = tmp_path.glob("copie-accelerometre-*-origine.bin")
    assert copie.read_bytes() == faux_fichier()
    assert outil_accelerometre.main([*base, "ecrire", str(tmp_path / "absent.bin")]) == 1


def test_outil_dans_le_chargeur(reglages: Path, capsys, monkeypatch):
    rp2040 = FauxRp2040(charger_reglages(reglages).accelerometre)
    rp2040.mode = "chargeur"
    monkeypatch.setattr(outil_accelerometre, "FauxRp2040", lambda _: rp2040)
    assert outil_accelerometre.main(["--reglages", str(reglages), "--faux", "etat"]) == 1
    assert "Le RP2040 est dans son chargeur" in capsys.readouterr().out


def test_reglages_du_chargeur(reglages: Path, tmp_path: Path):
    from vidange.accelerometre.entete import main as entete

    assert entete([str(reglages / "accelerometre.yaml"), str(tmp_path)]) == 0
    texte = (tmp_path / "reglages_genere.h").read_text(encoding="utf-8")
    assert "#define REGLAGE_CHARGEUR_ATTENTE_DEMARRAGE_MS 300\n" in texte
    assert "#define REGLAGE_CHARGEUR_CHIEN_DE_GARDE_MS 2000\n" in texte
    remplacer(reglages / "accelerometre.yaml", "chien_de_garde_ms: 2000", "chien_de_garde_ms: 500")
    assert "chien_de_garde_ms : doit valoir au moins 1000" in erreur_de(reglages)
