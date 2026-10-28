"""Tests du démarrage du programme."""

import configparser
import json
import socket
import threading
import urllib.request

from vidange.accelerometre.faux import FauxRp2040
from vidange.cameras import FausseCamera
from vidange.demarrage import (
    CODE_OK,
    CODE_REDEMARRER,
    CODE_REGISTRE_ABIME,
    CODE_REGLAGES_FAUX,
    Raccords,
    principal,
)
from vidange.ecran import FauxNextion
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fluidnc import FauxFluidnc
from vidange.journal import NOM_FICHIER
from vidange.materiel import FausseFabrique
from vidange.mises_a_jour import CarteEsp32, FausseCarteEsp32, faux_programme
from vidange.registre import Registre
from vidange.reglages import charger_reglages

from .conftest import DOSSIER_PI
from .test_chef_exemple import attendre
from .test_maj_gestion import FauxPi
from .test_reglages import remplacer


def options(reglages, tmp_path):
    return [
        "--reglages",
        str(reglages),
        "--secrets",
        str(tmp_path / "secrets.yaml"),
        "--donnees",
        str(tmp_path / "donnees"),
    ]


def test_verifier_des_reglages_corrects(reglages, tmp_path, capsys):
    assert principal([*options(reglages, tmp_path), "--verifier"]) == CODE_OK
    sortie = capsys.readouterr().err
    assert "Réglages corrects" in sortie
    assert "valeurs d'EXEMPLE" in sortie
    assert "entrees-sorties.yaml : 19 lignes d'EXEMPLE" in sortie
    # La simple vérification n'écrit pas de journal sur le disque.
    assert not (tmp_path / "donnees").exists()


def test_reglages_faux_empechent_de_demarrer(reglages, tmp_path, capsys):
    (reglages / "programme.yaml").unlink()
    arret = threading.Event()
    arret.set()
    assert principal(options(reglages, tmp_path), arret) == CODE_REGLAGES_FAUX
    assert "programme.yaml : fichier manquant" in capsys.readouterr().err


def test_entrees_sorties_fausses_empechent_de_demarrer(reglages, entrees_sorties, tmp_path, capsys):
    texte = entrees_sorties.read_text(encoding="utf-8")
    entrees_sorties.write_text(texte.replace("broche: E2", "broche: E1"), encoding="utf-8")
    arguments = [*options(reglages, tmp_path), "--entrees-sorties", str(entrees_sorties)]
    assert principal([*arguments, "--verifier"]) == CODE_REGLAGES_FAUX
    assert "broche E1 : utilisée par plusieurs signaux" in capsys.readouterr().err


def test_demarrage_puis_arret_propre(reglages, tmp_path):
    arret = threading.Event()
    arret.set()  # l'ordre d'arrêt est déjà donné : le programme démarre puis s'arrête.
    assert principal(options(reglages, tmp_path), arret) == CODE_OK
    contenu = (tmp_path / "donnees" / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    assert "démarré" in contenu
    assert "arrêt propre" in contenu


def test_les_variables_d_environnement_donnent_les_chemins(reglages, tmp_path, monkeypatch):
    (reglages / "programme.yaml").unlink()
    monkeypatch.setenv("VIDANGE_REGLAGES", str(reglages))
    assert principal(["--verifier"]) == CODE_REGLAGES_FAUX


def test_le_service_systemd_ne_relance_pas_des_reglages_faux():
    service = configparser.ConfigParser(strict=False, interpolation=None)
    service.optionxform = str
    service.read(DOSSIER_PI / "systeme" / "vidange.service", encoding="utf-8")
    assert service["Service"]["Restart"] == "on-failure"
    codes = service["Service"]["RestartPreventExitStatus"].split()
    assert codes == [str(CODE_REGLAGES_FAUX), str(CODE_REGISTRE_ABIME)]
    assert service["Install"]["WantedBy"] == "multi-user.target"


def test_demarrage_cree_le_registre(reglages, tmp_path):
    arret = threading.Event()
    arret.set()
    assert principal(options(reglages, tmp_path), arret) == CODE_OK
    assert (tmp_path / "donnees" / "registre.sqlite").exists()
    assert (tmp_path / "donnees" / "photos").is_dir()


def test_registre_abime_arrete_le_demarrage(reglages, tmp_path, capsys):
    (tmp_path / "donnees").mkdir()
    (tmp_path / "donnees" / "registre.sqlite").write_bytes(b"abime" * 1000)
    arret = threading.Event()
    arret.set()
    assert principal(options(reglages, tmp_path), arret) == CODE_REGISTRE_ABIME
    assert "base du registre abîmée" in capsys.readouterr().err


# ---------------------------------------------------------------- tâche 7 : fiabilité


def test_le_service_systemd_a_son_chien_de_garde():
    service = configparser.ConfigParser(strict=False, interpolation=None)
    service.optionxform = str
    service.read(DOSSIER_PI / "systeme" / "vidange.service", encoding="utf-8")
    assert service["Service"]["Type"] == "notify"
    assert service["Service"]["NotifyAccess"] == "main"
    reglages = charger_reglages(DOSSIER_PI / "reglages")
    gardien = reglages.programme.fiabilite.chien_de_garde
    # systemd attend assez longtemps : le programme dit « je vis » plusieurs fois avant.
    assert float(service["Service"]["WatchdogSec"]) >= 3 * gardien.periode_s


def raccords_faux(entrees_sorties):
    liste = charger_entrees_sorties(entrees_sorties)
    reglages = charger_reglages(DOSSIER_PI / "reglages")
    cartes = {nom: FauxFluidnc() for nom in reglages.fluidnc.cartes}
    messages, commandes = [], []
    raccords = Raccords(
        fabrique=FausseFabrique(liste),
        ports={nom: carte.ouvrir for nom, carte in cartes.items()},
        notifier=lambda message: messages.append(message) or True,
        lancer=commandes.append,
        ecran=FauxNextion().ouvrir,
        accelerometre=FauxRp2040(reglages.accelerometre).ouvrir,
        cameras={nom: FausseCamera(nom).ouvrir for nom in reglages.programme.cameras.liste},
    )
    return raccords, messages, commandes


def test_l_onduleur_arrete_proprement_puis_eteint_le_pi(reglages, entrees_sorties, tmp_path):
    remplacer(reglages / "programme.yaml", "delai_avant_arret_s: 60", "delai_avant_arret_s: 0")
    raccords, messages, commandes = raccords_faux(entrees_sorties)
    arguments = [*options(reglages, tmp_path), "--entrees-sorties", str(entrees_sorties)]
    resultat = []
    arret = threading.Event()  # pas donné : c'est l'onduleur qui arrête le programme
    fil = threading.Thread(target=lambda: resultat.append(principal(arguments, arret, raccords)))
    fil.start()
    attendre(lambda: "READY=1" in messages)
    raccords.fabrique.actionner("onduleur_sur_batterie")
    fil.join(10)
    assert resultat == [CODE_OK]
    assert commandes == [["sudo", "-n", "/usr/bin/systemctl", "poweroff"]]
    assert messages[-1] == "STOPPING=1"
    journal = (tmp_path / "donnees" / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    assert "Courant coupé" in journal
    assert "Check-list de démarrage" in journal
    assert "Retour en lieu sûr proposé" in journal
    etat = json.loads((tmp_path / "donnees" / "etat-programme.json").read_text(encoding="utf-8"))
    assert etat["en_marche"] is False and etat["raison"] == "onduleur"


def test_une_coupure_de_courant_est_notee(reglages, tmp_path):
    donnees = tmp_path / "donnees"
    donnees.mkdir()
    # Le programme était « en marche » depuis 1970 : le Pi a redémarré depuis.
    (donnees / "etat-programme.json").write_text(
        '{"version": 1, "en_marche": true, "depuis": 0, "date": "1970-01-01T00:00:00"}',
        encoding="utf-8",
    )
    arret = threading.Event()
    arret.set()
    assert principal(options(reglages, tmp_path), arret) == CODE_OK
    registre = Registre(donnees / "registre.sqlite", donnees / "photos")
    try:
        alarme = registre.alarmes_ouvertes()[0]
    finally:
        registre.fermer()
    assert alarme["module"] == "alimentation"
    assert "s'est arrêté net" in alarme["message"]
    assert "prise d'origine" in alarme["quoi_faire"]


def test_l_api_demarre_avec_la_cle_et_s_arrete_avec_le_programme(
    reglages, entrees_sorties, tmp_path
):
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        port = prise.getsockname()[1]
    remplacer(reglages / "programme.yaml", "adresse: 0.0.0.0", "adresse: 127.0.0.1")
    remplacer(reglages / "programme.yaml", "port: 8080", f"port: {port}")
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("cle_api: une-cle-de-test-assez-longue\n", encoding="utf-8")
    secrets.chmod(0o600)
    raccords, messages, _ = raccords_faux(entrees_sorties)
    arguments = [*options(reglages, tmp_path), "--entrees-sorties", str(entrees_sorties)]
    arret = threading.Event()
    fil = threading.Thread(target=lambda: principal(arguments, arret, raccords))
    fil.start()
    try:
        attendre(lambda: "READY=1" in messages)
        demande = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/etat",
            headers={"Authorization": "Bearer une-cle-de-test-assez-longue"},
        )
        with urllib.request.urlopen(demande, timeout=5) as reponse:
            etat = json.loads(reponse.read())
        # Le retour en lieu sûr est proposé au démarrage : il attend le Go.
        assert etat["attendent_go"] == ["lieu_sur"]
    finally:
        arret.set()
        fil.join(10)
    journal = (tmp_path / "donnees" / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    assert f"API et page web à l'écoute : http://127.0.0.1:{port}" in journal
    assert "API et page web : pas de clé" not in journal
    assert "API arrêtée" in journal


def test_sans_cle_la_machine_demarre_sans_api(reglages, tmp_path):
    arret = threading.Event()
    arret.set()
    assert principal(options(reglages, tmp_path), arret) == CODE_OK
    journal = (tmp_path / "donnees" / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    assert "l'API et la page web ne démarrent pas" in journal
    assert "[attention] API et page web : pas de clé" in journal


# ---------------------------------------------------------------- tâche 9 : écran de l'armoire


def test_l_ecran_montre_l_etat_et_donne_le_go(reglages, entrees_sorties, tmp_path):
    nextion = FauxNextion()
    raccords, messages, _ = raccords_faux(entrees_sorties)
    raccords.ecran = nextion.ouvrir
    arguments = [*options(reglages, tmp_path), "--entrees-sorties", str(entrees_sorties)]
    arret = threading.Event()
    fil = threading.Thread(target=lambda: principal(arguments, arret, raccords))
    fil.start()
    try:
        attendre(lambda: "READY=1" in messages)
        # Le retour en lieu sûr est proposé au démarrage : il attend le Go.
        attendre(lambda: nextion.texte("b_bandeau") == "ATTEND LE GO")
        assert nextion.texte("t_mode") == "Mode : Production"
        nextion.appuyer("b_go")
        attendre(lambda: nextion.page == "confirmer")
        assert "lieu sur" in nextion.texte("t_question")
        nextion.appuyer("b_non")
        attendre(lambda: nextion.page == "etat")
    finally:
        arret.set()
        fil.join(10)
    assert not fil.is_alive()
    journal = (tmp_path / "donnees" / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    assert "Écran : port série ouvert" in journal


def test_sans_ecran_dans_la_liste_la_machine_demarre(reglages, entrees_sorties, tmp_path):
    remplacer(entrees_sorties, "  ecran_nextion:", "  autre_ecran:")
    arret = threading.Event()
    arret.set()
    arguments = [*options(reglages, tmp_path), "--entrees-sorties", str(entrees_sorties)]
    assert principal(arguments, arret) == CODE_OK
    journal = (tmp_path / "donnees" / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    assert "pas d'écran de l'armoire" in journal
    assert "[attention] écran de l'armoire : pas de signal « ecran_nextion »" in journal


# ---------------------------------------------------------------- tâche 12 : accès à distance


def test_pilotage_a_distance_puis_l_armoire_reprend_la_main(reglages, entrees_sorties, tmp_path):
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        port = prise.getsockname()[1]
    remplacer(reglages / "programme.yaml", "adresse: 0.0.0.0", "adresse: 127.0.0.1")
    remplacer(reglages / "programme.yaml", "port: 8080", f"port: {port}")
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("cle_api: une-cle-de-test-assez-longue\n", encoding="utf-8")
    secrets.chmod(0o600)
    nextion = FauxNextion()
    raccords, messages, _ = raccords_faux(entrees_sorties)
    raccords.ecran = nextion.ouvrir
    arguments = [*options(reglages, tmp_path), "--entrees-sorties", str(entrees_sorties)]
    arret = threading.Event()
    fil = threading.Thread(target=lambda: principal(arguments, arret, raccords))
    fil.start()

    def demander(chemin: str, methode: str = "GET"):
        demande = urllib.request.Request(
            f"http://127.0.0.1:{port}{chemin}",
            method=methode,
            headers={"Authorization": "Bearer une-cle-de-test-assez-longue"},
        )
        with urllib.request.urlopen(demande, timeout=5) as reponse:
            return reponse.headers, reponse.read()

    try:
        attendre(lambda: "READY=1" in messages)
        # Les fausses caméras envoient leur vidéo.
        entetes, image = demander("/api/cameras/plafond/image")
        assert image.startswith(b"\xff\xd8") and int(entetes["X-Image"]) >= 1
        etat = json.loads(demander("/api/distance/activer", "POST")[1])
        assert etat["actif"] and [axe["nom"] for axe in etat["axes"]] == [
            "exemple_x",
            "exemple_y",
            "exemple_z",
        ]
        attendre(lambda: nextion.texte("b_bandeau") == "À DISTANCE : TOUCHER = STOP")
        nextion.appuyer("b_pause")
        attendre(lambda: not json.loads(demander("/api/distance")[1])["actif"])
        journal_distance = json.loads(demander("/api/distance/journal")[1])
        assert [ligne["action"] for ligne in journal_distance] == ["reprise_sur_place", "activer"]
        assert journal_distance[0]["qui"] == "écran de l'armoire"
    finally:
        arret.set()
        fil.join(10)
    assert not fil.is_alive()
    journal = (tmp_path / "donnees" / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    assert "Pilotage à distance terminé (écran de l'armoire)" in journal


# ---------------------------------------------------------------- tâche 13 : mises à jour


def test_le_service_systemd_relance_apres_une_mise_a_jour():
    service = configparser.ConfigParser(strict=False, interpolation=None)
    service.optionxform = str
    service.read(DOSSIER_PI / "systeme" / "vidange.service", encoding="utf-8")
    assert service["Service"]["RestartForceExitStatus"] == str(CODE_REDEMARRER)
    assert service["Service"]["SuccessExitStatus"] == str(CODE_REDEMARRER)


def test_mise_a_jour_d_une_carte_puis_du_pi_depuis_la_page(reglages, entrees_sorties, tmp_path):
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        port = prise.getsockname()[1]
    remplacer(reglages / "programme.yaml", "adresse: 0.0.0.0", "adresse: 127.0.0.1")
    remplacer(reglages / "programme.yaml", "port: 8080", f"port: {port}")
    remplacer(reglages / "programme.yaml", "delai_commande_s: 5", "delai_commande_s: 0.05")
    remplacer(reglages / "programme.yaml", "delai_reponse_s: 30", "delai_reponse_s: 0.5")
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("cle_api: une-cle-de-test-assez-longue\n", encoding="utf-8")
    secrets.chmod(0o600)
    raccords, messages, _ = raccords_faux(entrees_sorties)
    faux = FausseCarteEsp32()
    raccords.cartes_maj = {
        "portique": CarteEsp32(
            "portique",
            charger_reglages(reglages).programme.mises_a_jour.cartes,
            tmp_path / "copies",
            faux.trouver_port,
            faux.ouvrir,
            faux.esptool,
        )
    }
    # Jamais la vraie copie Git du dépôt dans un essai : un faux programme du Pi.
    raccords.programme_pi = FauxPi()
    arguments = [*options(reglages, tmp_path), "--entrees-sorties", str(entrees_sorties)]
    resultat = []
    arret = threading.Event()
    fil = threading.Thread(target=lambda: resultat.append(principal(arguments, arret, raccords)))
    fil.start()

    def demander(chemin: str, methode: str = "GET", corps: bytes | None = None, json_=None):
        if json_ is not None:
            corps = json.dumps(json_).encode()
        demande = urllib.request.Request(
            f"http://127.0.0.1:{port}{chemin}",
            data=corps,
            method=methode,
            headers={
                "Authorization": "Bearer une-cle-de-test-assez-longue",
                "Content-Type": "application/json"
                if json_ is not None
                else "application/octet-stream",
            },
        )
        with urllib.request.urlopen(demande, timeout=5) as reponse:
            return json.loads(reponse.read())

    def dernier():
        return demander("/api/mises-a-jour")["dernier"]

    try:
        attendre(lambda: "READY=1" in messages)
        # Le retour en lieu sûr attend le Go de sa première étape : rien n'a bougé.
        assert demander("/api/mises-a-jour")["refus"] is None
        demander("/api/mises-a-jour/programmes?nom=v5.bin", "POST", faux_programme("3.9.5"))
        demander("/api/mises-a-jour/cartes/portique/programme", "POST", json_={"fichier": "v5.bin"})
        attendre(lambda: (dernier() or {}).get("reussi") is True)
        assert faux.version == "3.9.5"
        # La liaison ordinaire avec la carte est repartie.
        assert demander("/api/etat")["mise_a_jour"] is False
        demander("/api/mises-a-jour/pi/installer", "POST")
        fil.join(10)
    finally:
        arret.set()
        fil.join(10)
    assert resultat == [CODE_REDEMARRER]
    journal = (tmp_path / "donnees" / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    assert "Redémarrage du programme (nouvelle version)." in journal


# ---------------------------------------------------------------- tâche 15 : accéléromètre


def test_un_choc_de_l_accelerometre_est_note_au_registre(reglages, entrees_sorties, tmp_path):
    rp2040 = FauxRp2040(charger_reglages(reglages).accelerometre)
    rp2040.choc(3.2, duree_ms=12)
    raccords, messages, _ = raccords_faux(entrees_sorties)
    raccords.accelerometre = rp2040.ouvrir
    arguments = [*options(reglages, tmp_path), "--entrees-sorties", str(entrees_sorties)]
    arret = threading.Event()
    fil = threading.Thread(target=lambda: principal(arguments, arret, raccords))
    fil.start()
    try:
        attendre(lambda: "READY=1" in messages)
        attendre(lambda: "CHOC 1" in rp2040.questions)
    finally:
        arret.set()
        fil.join(10)
    assert not fil.is_alive()
    registre = Registre(tmp_path / "donnees" / "registre.sqlite", tmp_path / "donnees" / "photos")
    try:
        chocs = registre.lire("SELECT valeur, unite, capteur FROM mesures WHERE nom = 'choc'")
    finally:
        registre.fermer()
    assert chocs == [{"valeur": 3.2, "unite": "g", "capteur": "accelerometre_fil"}]
    journal = (tmp_path / "donnees" / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    assert "Accéléromètre : CHOC n° 1 de 3.20 g pendant 12 ms" in journal
