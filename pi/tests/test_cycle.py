"""Tests du programme principal du mode seaux (tâche 45)."""

import json
import threading

import pytest

from vidange.chef import Carnet, Chef, ErreurChef
from vidange.cycle import ORDRE_SEAU, ModeSeaux, verifier_ordre
from vidange.cycle.machine import BOCAL_NEUF, QR_DU_FLANC, VISION_MICROPORE, PiecesMachine
from vidange.cycle.simulation import PiecesSimulees, jouer_cycle, lot_du_simulateur
from vidange.demarrage import CODE_OK, principal
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.journal import NOM_FICHIER
from vidange.reglages import charger_reglages
from vidange.simulateur import Simulateur
from vidange.simulateur.outil import main as simulateur

from .conftest import DOSSIER_PI
from .test_demarrage import options, raccords_faux
from .test_ecran import BancEcran


@pytest.fixture(scope="module")
def reglages_depot():
    return charger_reglages(DOSSIER_PI / "reglages")


@pytest.fixture(scope="module")
def liste():
    return charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")


def sans_partie(reglages, partie):
    return reglages.model_copy(
        update={"machine": reglages.machine.model_copy(update={partie: None})}
    )


def duree_max(reglages, secondes):
    simule = reglages.simulateur.model_copy(update={"duree_max_s": secondes})
    return reglages.model_copy(update={"simulateur": simule})


class PiecesDeLaMachine:
    """Des pièces sur la vraie machine, auxquelles rien ne manquerait."""

    vraie_machine = True

    def manque(self, poste):
        return None

    def remplissage(self, lot, avec_micropore, avec_fermeture):
        raise AssertionError("pas de lot sur la vraie machine en EXEMPLE")


# ---------------------------------------------------------------- l'ordre du cycle


def test_un_seul_endroit_dit_l_ordre_du_cycle_d_un_seau():
    noms = [poste.nom for poste in ORDRE_SEAU]
    assert noms == [
        "fut",
        "seau_vide",
        "griffe",
        "mycelium",
        "spray",
        "micropore",
        "couvercle",
        "fermeture",
        "stockage",
        "lavage",
    ]
    # Les gestes pas encore écrits restent des cases vides : jamais lancés.
    vides = {poste.nom for poste in ORDRE_SEAU if poste.case_vide}
    assert vides == {"griffe", "spray", "couvercle", "lavage"}
    assert "41 bis" in next(p for p in ORDRE_SEAU if p.nom == "couvercle").case_vide


def test_les_etapes_d_ordre_seau_existent_dans_les_modules(reglages_depot, liste):
    with Simulateur(reglages_depot, liste, "cycle") as simulateur:
        mode = ModeSeaux(reglages_depot, PiecesSimulees(simulateur), simulateur.chef)
        modules = mode.modules_du_lot(lot_du_simulateur(simulateur))
    etapes = {f"{module.nom}.{etape.nom}" for module in modules for etape in module.etapes}
    for poste in ORDRE_SEAU:
        if mode.pret(poste.nom):
            assert set(poste.etapes) <= etapes, poste.nom


def test_un_seau_qui_ne_suit_pas_l_ordre_est_vu():
    lances = ["seau_vide", "mycelium", "stockage"]
    bon = [
        "remplissage.prendre_le_seau",
        "remplissage.poser_le_seau",
        "remplissage.centrer",
        "remplissage.ramener_au_vidage",
        "mycelium.agiter",
        "remplissage.ranger",
    ]
    assert verifier_ordre(bon * 2, lances) == []
    mauvais = [*bon[:4], "remplissage.ranger", "mycelium.agiter"]
    problemes = verifier_ordre(mauvais, lances)
    assert problemes == [
        "seau n° 1 : ordre remplissage.prendre_le_seau → remplissage.poser_le_seau → "
        "remplissage.centrer → remplissage.ramener_au_vidage → remplissage.ranger → "
        "mycelium.agiter au lieu de remplissage.prendre_le_seau → remplissage.poser_le_seau → "
        "remplissage.centrer → remplissage.ramener_au_vidage → mycelium.agiter → "
        "remplissage.ranger"
    ]
    assert verifier_ordre(bon[:-1], lances) == [
        "seau n° 1 : étape « remplissage.ranger » pas faite"
    ]
    assert verifier_ordre([], lances) == ["aucun seau commencé"]


# ---------------------------------------------------------------- ce qui est prêt


def test_avec_le_faux_materiel_les_modules_attendus_sont_prets(reglages_depot, liste):
    with Simulateur(reglages_depot, liste, "cycle") as simulateur:
        mode = ModeSeaux(reglages_depot, PiecesSimulees(simulateur), simulateur.chef)
    assert mode.postes_lances == ["seau_vide", "mycelium", "micropore", "stockage"]
    assert mode.refus_lot() is None
    assert "tâche 23" in mode.etats["griffe"].raison
    assert mode.etats["fermeture"].en_texte() == "pas lancé : attend « couvercle » (pas prêt)"
    assert "vidange-simulateur poste_fut" in mode.etats["fut"].raison


def test_un_module_sans_reglage_n_est_pas_lance(reglages_depot, liste):
    reglages = sans_partie(reglages_depot, "micropore")
    with Simulateur(reglages, liste, "cycle") as simulateur:
        mode = ModeSeaux(reglages, PiecesSimulees(simulateur), simulateur.chef)
    assert mode.etats["micropore"].en_texte() == (
        "pas lancé : machine.yaml n'a pas de partie « micropore »"
    )
    # Le micropore n'est pas du cœur : le lot peut partir sans lui.
    assert mode.refus_lot() is None

    reglages = sans_partie(reglages_depot, "stockage")
    with Simulateur(reglages, liste, "cycle") as simulateur:
        mode = ModeSeaux(reglages, PiecesSimulees(simulateur), simulateur.chef)
        assert mode.etats["stockage"].raison == "machine.yaml n'a pas de partie « stockage »"
        assert mode.etats["seau_vide"].raison == "attend « stockage » (pas prêt)"
        assert mode.refus_lot() == ("« seau_vide » pas lancé : attend « stockage » (pas prêt)")
        with pytest.raises(ErreurChef, match="lot de seaux impossible"):
            mode.modules_du_lot(lot_du_simulateur(simulateur))
    constats = {constat.sujet: constat for constat in mode.constats()}
    assert constats["mode seaux, stockage"].niveau == "attention"
    assert constats["mode seaux"].niveau == "bloquant"
    assert mode.texte_ecran() == (
        "Lot de seaux : seau vide pas prêt",
        "attend « stockage » (pas prêt)",
    )


def test_sur_la_vraie_machine_les_reglages_d_exemple_sont_interdits(reglages_depot):
    chef = Chef(reglages_depot.machine, reglages_depot.programme.chef)
    mode = ModeSeaux(reglages_depot, PiecesDeLaMachine(), chef)
    for nom in ("fut", "seau_vide", "mycelium", "micropore", "stockage"):
        assert "valeurs d'EXEMPLE dans machine.yaml" in mode.etats[nom].raison, nom
        assert "interdit sur la vraie machine" in mode.etats[nom].raison
    assert "remplissage" in mode.etats["seau_vide"].raison
    assert mode.refus_lot().startswith("« fut » pas lancé : valeurs d'EXEMPLE")


def test_les_pieces_de_la_machine_disent_ce_qui_manque(reglages_depot):
    reglages = reglages_depot.model_copy(
        update={"machine": reglages_depot.machine.model_copy(update={"exemple": False})}
    )
    chef = Chef(reglages.machine, reglages.programme.chef)
    # Faux matériel (essai) : les EXEMPLES des parties sont permis ; poste du fût pas ouvert.
    mode = ModeSeaux(reglages, PiecesMachine(None, None, vraie_machine=False), chef)
    assert mode.etats["seau_vide"].raison == QR_DU_FLANC
    assert mode.etats["mycelium"].raison == BOCAL_NEUF
    assert mode.etats["micropore"].raison == VISION_MICROPORE
    assert mode.etats["fut"].raison == "poste du fût pas suivi (entrées/sorties pas ouvertes)"
    assert mode.refus_lot() == f"« seau_vide » pas lancé : {QR_DU_FLANC}"


def test_l_ecran_dit_quel_poste_manque_et_pourquoi(tmp_path, reglages_depot):
    banc = BancEcran(tmp_path)
    try:
        chef = Chef(reglages_depot.machine, reglages_depot.programme.chef)
        banc.ecran.mode_seaux = ModeSeaux(
            reglages_depot, PiecesMachine(None, None, vraie_machine=False), chef
        )
        banc.tour()
        # Un cycle tourne : l'écran parle de lui.
        assert banc.texte("t_module") == "essai, étape 1/2 : un"
        banc.chef.abandonner("essai")
        banc.tour()
        assert banc.texte("t_module") == "Aucun cycle en cours"
        assert banc.texte("t_attend") == "Lot de seaux : seau vide pas prêt"
        assert banc.texte("t_info").startswith("lecture du QR du flanc du seau")
    finally:
        banc.registre.fermer()


def test_au_demarrage_la_check_list_dit_ce_qui_manque(reglages, entrees_sorties, tmp_path):
    raccords, messages, _ = raccords_faux(entrees_sorties)
    arguments = [*options(reglages, tmp_path), "--entrees-sorties", str(entrees_sorties)]
    arret = threading.Event()
    fil = threading.Thread(target=lambda: principal(arguments, arret, raccords))
    fil.start()
    try:
        from .test_chef_exemple import attendre

        attendre(lambda: "READY=1" in messages)
    finally:
        arret.set()
        fil.join(10)
    journal = (tmp_path / "donnees" / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    assert "Mode seaux, fut : prêt" in journal
    assert f"Mode seaux, seau_vide : pas lancé : {QR_DU_FLANC}" in journal
    assert f"[attention] mode seaux, micropore : pas lancé : {VISION_MICROPORE}" in journal
    assert "[attention] mode seaux, couvercle : pas lancé : geste pas encore écrit" in journal
    assert "[bloquant] mode seaux : aucun lot de seaux ne peut partir" in journal


# ---------------------------------------------------------------- le lot simulé


def test_lot_complet_simule_sans_alarme(reglages_depot, liste):
    with Simulateur(reglages_depot, liste, "cycle") as simulateur:
        mode, planning, problemes = jouer_cycle(simulateur)
        magasin = mode.en_cours.pieces.plan.magasin
        faits = list(mode.en_cours.pieces.plan.faits)
    assert planning.probleme == ""
    assert problemes == []
    assert faits == [f"S{numero:04d}" for numero in range(301, 321)]
    assert [ligne.etape for ligne in planning.lignes].count("ranger") == 20
    # Lot complet : 6 seaux déjà dans la file 1, 14 au tiroir, 6 sur la bande, puis fin de lot.
    assert magasin.messages[-1].startswith("fin de lot")
    assert magasin.seaux_pleins() == 0


def test_l_outil_joue_le_cycle(capsys):
    assert simulateur(["cycle", "--delai-go", "0"]) == 0
    sortie = capsys.readouterr().out
    assert "Mode seaux (ordre du cycle d'un seau) :" in sortie
    assert "lot : peut partir" in sortie
    assert "Ordre du cycle pas suivi" not in sortie


def test_cycle_se_joue_seul():
    with pytest.raises(SystemExit):
        simulateur(["cycle", "griffe"])


# ---------------------------------------------------------------- reprise après une coupure


def test_reprise_apres_une_coupure_au_milieu_d_un_seau(reglages_depot, liste, tmp_path):
    carnet = Carnet(tmp_path / "etat-cycle.json")
    # Coupure de courant au bout de 1300 s simulées : 4e seau, dosage de sa 2e couche.
    coupe = duree_max(reglages_depot, 1300)
    with Simulateur(coupe, liste, "cycle", carnet=carnet) as simulateur:
        _, planning, _ = jouer_cycle(simulateur)
    assert planning.probleme.startswith("bloqué au bout de duree_max_s")
    etat = carnet.lire()
    note = next(n for n in etat["modules"] if n["module"] == "remplissage")
    memoire = note["memoire"]
    assert note["statut"] == "en_cours"
    assert (note["etape"], memoire["numero"], memoire["couche"]) == ("doser", 3, 2)
    assert memoire["seau_plateau"]["code"] == "S0304"
    assert memoire["lot"]["seaux"][0]["seau"] == "S0301"

    # Le Pi redémarre : nouveau chef, nouvelles pièces, même carnet.
    with Simulateur(reglages_depot, liste, "cycle") as simulateur:
        chef = Chef(reglages_depot.machine, reglages_depot.programme.chef, carnet)
        mode = ModeSeaux(reglages_depot, PiecesSimulees(simulateur), chef)
        repris = chef.reprendre_cycle(mode.modules_a_reprendre(carnet.lire()))
    assert sorted(repris) == ["mycelium", "remplissage"]
    remplissage = next(m for m in chef.etat().modules if m.module == "remplissage")
    assert remplissage.etape == note["etape"]
    assert remplissage.attend == "Go de Karulium"
    plan = mode.en_cours.pieces.plan
    assert (plan.numero, plan.couche) == (memoire["numero"], memoire["couche"])
    assert plan.seau.seau == f"S{301 + memoire['numero']:04d}"
    seau = mode.en_cours.pieces.remplissage.seau
    assert seau is not None and seau.code == memoire["seau_plateau"]["code"]


def test_un_lot_du_carnet_impossible_maintenant_est_signale(reglages, entrees_sorties, tmp_path):
    donnees = tmp_path / "donnees"
    donnees.mkdir()
    lot = {"format": "seau_a", "fin_de_lot": True, "seaux": []}
    note = {
        "module": "remplissage",
        "statut": "en_cours",
        "etape": "verser",
        "phase": "go",
        "go_recu": False,
        "zones": [],
        "alarme": None,
        "memoire": {"lot": lot, "numero": 0, "couche": 2},
    }
    (donnees / "etat-cycle.json").write_text(
        json.dumps({"version": 1, "modules": [note]}), encoding="utf-8"
    )
    arret = threading.Event()
    arret.set()
    assert principal(options(reglages, tmp_path), arret) == CODE_OK
    journal = (donnees / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    assert "Carnet : lot en cours, mais lot impossible maintenant" in journal
    assert "[bloquant] reprise du cycle : carnet : module « remplissage » inconnu" in journal
