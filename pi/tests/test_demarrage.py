"""Tests du démarrage du programme."""

import configparser
import json
import threading

from vidange.demarrage import (
    CODE_OK,
    CODE_REGISTRE_ABIME,
    CODE_REGLAGES_FAUX,
    Raccords,
    principal,
)
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fluidnc import FauxFluidnc
from vidange.journal import NOM_FICHIER
from vidange.materiel import FausseFabrique
from vidange.registre import Registre
from vidange.reglages import charger_reglages

from .conftest import DOSSIER_PI
from .test_chef_exemple import attendre
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
    assert "entrees-sorties.yaml : 18 lignes d'EXEMPLE" in sortie
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
