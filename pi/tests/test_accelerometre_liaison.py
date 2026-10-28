"""Liaison du Pi avec le RP2040 de l'accéléromètre (fil série unique), avec un faux RP2040."""

import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vidange.accelerometre import outil as outil_accelerometre
from vidange.accelerometre.faux import FauxRp2040
from vidange.accelerometre.liaison import LiaisonAccelerometre
from vidange.accelerometre.protocole import (
    Choc,
    Decodeur,
    ErreurProtocole,
    EtatRp2040,
    crc,
    lire_reglages,
    question_regler,
    reglages_pour_rp2040,
    texte_pannes,
    trame,
    verifier_ligne,
)
from vidange.registre import Registre
from vidange.reglages import charger_reglages

from .test_reglages import erreur_de, remplacer


class Horloge:
    """Une horloge qui avance à chaque lecture (les attentes de réponse finissent)."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 0.001
        return self.t


@pytest.fixture(autouse=True)
def journal_complet(caplog):
    caplog.set_level(logging.INFO)


@pytest.fixture
def accelerometre(reglages: Path):
    return charger_reglages(reglages).accelerometre


@pytest.fixture
def registre(tmp_path: Path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    yield registre
    registre.fermer()


def preparer(accelerometre, registre=None):
    rp2040 = FauxRp2040(accelerometre)
    heure = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
    liaison = LiaisonAccelerometre(
        accelerometre, rp2040.ouvrir, registre, horloge=Horloge(), heure=lambda: heure
    )
    return rp2040, liaison


def mesures(registre, nom):
    return registre.lire(
        "SELECT quand, valeur, unite, capteur FROM mesures WHERE nom = ? ORDER BY id", (nom,)
    )


# ---------------------------------------------------------------- protocole


def test_trames_et_controle():
    # Valeur connue du CRC-16 CCITT (départ 0xFFFF) : « 123456789 » → 0x29B1.
    assert crc(b"123456789") == 0x29B1
    assert trame("ETAT") == f"ETAT*{crc(b'ETAT'):04X}\n".encode()
    assert verifier_ligne(trame("ETAT").rstrip(b"\n")) == "ETAT"
    assert verifier_ligne(trame("ETAT").rstrip(b"\n") + b"\r") == "ETAT"
    assert verifier_ligne(b"ETAU*" + trame("ETAT")[5:9]) is None
    assert verifier_ligne(b"ETAT") is None
    with pytest.raises(ErreurProtocole):
        trame("x" * 300)


def test_le_decodeur_assemble_les_morceaux_et_refuse_les_lignes_abimees():
    decodeur = Decodeur()
    octets = trame("ETAT") + b"ABIME*0000\n" + trame("CHOC 1")
    assert decodeur.ajouter(octets[:3]) == []
    assert decodeur.ajouter(octets[3:]) == ["ETAT", "CHOC 1"]
    assert decodeur.refusees == 1
    assert decodeur.ajouter(b"x" * 300) == []
    assert decodeur.refusees == 2


def test_lecture_des_reponses():
    etat = EtatRp2040.lire(
        "ETAT t_ms=5000 ok=0 choc=0 pannes=6 vues=6 max_mg=80 chocs=2 perdues=0 chien=1 contredit=0"
    )
    assert not etat.ok and etat.pannes == 6 and etat.chocs == 2 and etat.redemarre_par_chien
    assert texte_pannes(etat.pannes) == "capteur absent, autotest raté"
    assert texte_pannes(0) == "aucune"
    choc = Choc.lire("CHOC n=2 t_ms=4000 duree_ms=12 pic_mg=3200 fini=1")
    assert choc == Choc(2, absent=False, t_ms=4000, duree_ms=12, pic_mg=3200, fini=True)
    assert Choc.lire("CHOC n=1 absent=1").absent
    for faux in ("CHOC n=2", "ETAT ok=1", "REGLER ok", "ETAT ok"):
        with pytest.raises(ErreurProtocole):
            (Choc if faux.startswith("CHOC") else EtatRp2040).lire(faux)
    with pytest.raises(ErreurProtocole):
        lire_reglages("REGLAGES seuil_mg=1500")


def test_reglages_envoyes_au_rp2040(accelerometre):
    valeurs = reglages_pour_rp2040(accelerometre)
    assert valeurs["axes"] == "yz"
    assert valeurs["seuil_mg"] == "1500"
    assert question_regler(valeurs).startswith("REGLER pleine_echelle_g=8 mesures_par_seconde=400")
    # Les axes sont toujours écrits dans l'ordre x, y, z (comme le RP2040).
    axes = accelerometre.capteur.model_copy(update={"axes": ["z", "x"]})
    assert reglages_pour_rp2040(accelerometre.model_copy(update={"capteur": axes}))["axes"] == "xz"


# ---------------------------------------------------------------- liaison


def test_question_et_reponse_malgre_l_echo(accelerometre):
    rp2040, liaison = preparer(accelerometre)
    assert liaison.demander("ETAT").startswith("ETAT t_ms=")
    assert liaison.demander("INCONNU") == "ERREUR commande inconnue"
    assert rp2040.questions == ["ETAT", "INCONNU"]


def test_les_chocs_sont_notes_au_registre(accelerometre, registre):
    rp2040, liaison = preparer(accelerometre, registre)
    rp2040.choc(3.2, duree_ms=12)
    liaison.tour()
    choc = mesures(registre, "choc")
    assert [(m["valeur"], m["unite"], m["capteur"]) for m in choc] == [
        (3.2, "g", "accelerometre_fil")
    ]
    assert mesures(registre, "choc_duree")[0]["valeur"] == 12
    # L'heure du choc : l'heure du Pi moins l'écart entre les temps du RP2040.
    assert choc[0]["quand"].startswith("2026-10-28T11:59:59")
    # Un choc qui dure encore est pris quand il est fini.
    rp2040.choc(2.0, fini=False)
    liaison.tour()
    assert len(mesures(registre, "choc")) == 1
    rp2040.finir_choc()
    liaison.tour()
    assert [m["valeur"] for m in mesures(registre, "choc")] == [3.2, 2.0]
    # Rien de neuf : rien de plus.
    liaison.tour()
    assert len(mesures(registre, "choc")) == 2


def test_chocs_trop_vieux_et_redemarrage(accelerometre, registre, caplog):
    rp2040, liaison = preparer(accelerometre, registre)
    liaison.tour()
    for _ in range(18):
        rp2040.choc(2.0)
    liaison.tour()
    # Le RP2040 n'en garde que 16 : les 2 premiers sont perdus.
    assert len(mesures(registre, "choc")) == 16
    assert "choc n° 1 perdu" in caplog.text and "choc n° 2 perdu" in caplog.text
    # Après un redémarrage, les numéros repartent de 1.
    rp2040.redemarrer(chien=True)
    rp2040.choc(4.0)
    liaison.tour()
    assert mesures(registre, "choc")[-1]["valeur"] == 4.0
    assert "le RP2040 a redémarré" in caplog.text
    assert "chien de garde" in caplog.text


def test_pas_de_choc_note_deux_fois_apres_un_silence(accelerometre, registre):
    rp2040, liaison = preparer(accelerometre, registre)
    rp2040.choc(3.0)
    liaison.tour()
    rp2040.muet = True
    for _ in range(accelerometre.liaison.sans_reponse_max):
        liaison.tour()
    rp2040.choc(2.5)  # pendant le silence, sans redémarrage
    rp2040.muet = False
    liaison.tour()
    assert [m["valeur"] for m in mesures(registre, "choc")] == [3.0, 2.5]


def test_programme_du_pi_relance_sans_noter_deux_fois(accelerometre, registre):
    rp2040, liaison = preparer(accelerometre, registre)
    rp2040.choc(3.0)
    liaison.tour()
    # Le programme du Pi redémarre, le RP2040 non : il garde son choc n° 1.
    heure = datetime(2026, 10, 28, 12, 0, 30, tzinfo=UTC)
    liaison = LiaisonAccelerometre(
        accelerometre, rp2040.ouvrir, registre, horloge=Horloge(), heure=lambda: heure
    )
    rp2040.t_ms += 30000
    rp2040.choc(2.5)  # pendant que le programme du Pi était arrêté
    liaison.tour()
    assert [m["valeur"] for m in mesures(registre, "choc")] == [3.0, 2.5]


def test_les_reglages_sont_envoyes_s_ils_sont_differents(accelerometre, caplog):
    rp2040, liaison = preparer(accelerometre)
    rp2040.reglages["seuil_mg"] = "2500"
    liaison.tour()
    assert rp2040.reglages["seuil_mg"] == "1500"
    assert "réglages envoyés (seuil_mg 2500 → 1500)" in caplog.text
    # Ensuite, plus de question sur les réglages (jusqu'au prochain redémarrage).
    rp2040.questions.clear()
    liaison.tour()
    assert rp2040.questions == ["ETAT"]
    rp2040.redemarrer()
    rp2040.reglages["maintien_ms"] = "800"
    liaison.tour()
    assert rp2040.reglages["maintien_ms"] == "500"


def test_reglages_refuses(accelerometre, caplog):
    _, liaison = preparer(accelerometre)
    # Un seuil plus fort que la pleine échelle, que le RP2040 refuse (model_copy ne revérifie
    # pas : comme un fichier du Pi plus récent que le programme du RP2040).
    liaison.reglages = accelerometre.model_copy(
        update={"choc": accelerometre.choc.model_copy(update={"seuil_g": 9.0})}
    )
    liaison.tour()
    assert "il refuse les réglages de accelerometre.yaml" in caplog.text
    constats = liaison.constats()
    assert constats[0].niveau == "attention" and "refuse" in constats[0].texte


def test_sans_envoi_des_reglages(accelerometre):
    sans_envoi = accelerometre.liaison.model_copy(update={"envoyer_reglages": False})
    rp2040, liaison = preparer(accelerometre.model_copy(update={"liaison": sans_envoi}))
    rp2040.reglages["seuil_mg"] = "2500"
    liaison.tour()
    assert rp2040.reglages["seuil_mg"] == "2500"
    assert rp2040.questions == ["ETAT"]


def test_silence_puis_retour(accelerometre, caplog):
    rp2040, liaison = preparer(accelerometre)
    liaison.tour()
    assert liaison.constats()[0].niveau == "ok"
    rp2040.muet = True
    for _ in range(accelerometre.liaison.sans_reponse_max):
        liaison.tour()
    assert "il ne répond pas" in caplog.text
    assert liaison.constats()[0].niveau == "attention"
    rp2040.muet = False
    liaison.tour()
    assert "il répond" in caplog.text
    assert liaison.en_ligne


def test_reponse_abimee_puis_redemandee(accelerometre):
    rp2040, liaison = preparer(accelerometre)
    rp2040.abimer = 1
    liaison.tour()
    assert liaison.etat is None
    liaison.tour()
    assert liaison.etat is not None


def test_cable_coupe_puis_rebranche(accelerometre, caplog):
    rp2040, liaison = preparer(accelerometre)
    liaison.tour()
    rp2040.debrancher()
    liaison.tour()
    assert "liaison coupée" in caplog.text
    rp2040.rebrancher()
    # Le port n'est rouvert qu'après « reconnexion_s ».
    liaison._horloge.t += accelerometre.liaison.reconnexion_s
    liaison.tour()
    assert rp2040.ouvertures == 2
    assert liaison.en_ligne


def test_panne_du_rp2040(accelerometre, caplog):
    rp2040, liaison = preparer(accelerometre)
    liaison.tour()
    rp2040.panne = 0x02
    liaison.tour()
    assert "panne (capteur absent)" in caplog.text
    assert "capteur absent" in liaison.constats()[0].texte
    rp2040.panne = 0
    liaison.tour()
    assert "panne finie" in caplog.text


def test_vibration_maximale_notee(accelerometre, registre):
    rp2040, liaison = preparer(accelerometre, registre)
    rp2040.max_mg = 120
    liaison.tour()
    rp2040.max_mg = 340
    liaison.tour()
    assert mesures(registre, "vibration_max") == []
    liaison._horloge.t += accelerometre.liaison.niveau_max_s
    liaison.tour()
    assert [m["valeur"] for m in mesures(registre, "vibration_max")] == [0.34]


def test_pas_de_port_serie(accelerometre):
    rp2040, liaison = preparer(accelerometre)
    rp2040.debrancher()
    for _ in range(accelerometre.liaison.sans_reponse_max):
        liaison.tour()
    constat = liaison.constats()[0]
    assert constat.niveau == "attention" and "port série fermé" in constat.texte


# ---------------------------------------------------------------- réglages


@pytest.mark.parametrize(
    ("ancien", "nouveau", "attendu"),
    [
        ("fil_serie: 0", "fil_serie: 2", "broche 2 est prise deux fois (sortie_ok et fil_serie)"),
        ("vitesse_bauds: 115200", "vitesse_bauds: 100000", "vitesse_bauds : doit être l'un de"),
        (
            "attente_reponse_ms: 100",
            "attente_reponse_ms: 20",
            "attente_reponse_ms (20 ms) doit valoir au moins 44 ms",
        ),
        ("periode_ms: 200", "periode_ms: 50", "periode_ms (50 ms) doit valoir au moins"),
    ],
)
def test_reglages_de_la_liaison_faux(reglages: Path, ancien: str, nouveau: str, attendu: str):
    remplacer(reglages / "accelerometre.yaml", ancien, nouveau)
    assert attendu in erreur_de(reglages)


# ---------------------------------------------------------------- outil


def test_outil_avec_un_faux_rp2040(reglages: Path, capsys):
    base = ["--reglages", str(reglages), "--faux"]
    assert outil_accelerometre.main([*base, "etat"]) == 0
    sortie = capsys.readouterr().out
    assert "OK | max 0.08 g | chocs 0" in sortie
    assert "seuil_mg = 1500" in sortie
    assert outil_accelerometre.main([*base, "envoyer"]) == 0
    assert "REGLER ok" in capsys.readouterr().out
    assert outil_accelerometre.main([*base, "question", "CHOC", "1"]) == 0
    assert "CHOC n=1 absent=1" in capsys.readouterr().out


def test_outil_suivre(reglages: Path, capsys):
    arret = threading.Event()
    arret.set()
    assert outil_accelerometre.main(["--reglages", str(reglages), "--faux", "suivre"], arret) == 0
    assert "OK | max 0.08 g" in capsys.readouterr().out


def test_outil_sans_signal(reglages: Path, entrees_sorties: Path, capsys):
    remplacer(entrees_sorties, "  accelerometre_fil:", "  autre_fil:")
    arguments = ["--reglages", str(reglages), "--entrees-sorties", str(entrees_sorties), "etat"]
    assert outil_accelerometre.main(arguments) == 2
    assert "Pas de signal « accelerometre_fil »" in capsys.readouterr().out
