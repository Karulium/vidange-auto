"""Tests du programme principal du mode seaux (tâche 45)."""

import json
import threading

import pytest

from vidange.chef import Carnet, Chef, ErreurChef
from vidange.cycle import ORDRE_SEAU, ModeSeaux, verifier_ordre
from vidange.cycle.machine import (
    CAMERA_ABSENTE,
    CARTE_SPRAY,
    CARTES_PAS_CONSTRUITES,
    INSPECTION_ABSENTE,
    INSPECTION_EXEMPLE,
    VISION_ABSENTE,
    PiecesMachine,
)
from vidange.cycle.simulation import JOUES_EN_FAUX, PiecesSimulees, jouer_cycle, lot_du_simulateur
from vidange.demarrage import CODE_OK, principal
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.journal import NOM_FICHIER
from vidange.materiel import carte_spray as table_spray
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
    stockage = None

    def manque(self, poste):
        return None

    def remplissage(self, lot, avec_micropore, avec_fermeture, avec_spray):
        raise AssertionError("pas de lot sur la vraie machine en EXEMPLE")


# ---------------------------------------------------------------- l'ordre du cycle


def test_un_seul_endroit_dit_l_ordre_du_cycle_d_un_seau():
    noms = [poste.nom for poste in ORDRE_SEAU]
    # Ordre corrigé du 07/11/2026 : QR du flanc avant le serrage des barres, spray puis
    # rangées du haut du micropore sur le seau vide au poste, puis les couches.
    assert noms == [
        "fut",
        "seau_vide",
        "qr_du_flanc",
        "au_poste",
        "spray",
        "micropore",
        "griffe",
        "mycelium",
        "couvercle",
        "fermeture",
        "stockage",
        "lavage",
    ]
    # Les gestes pas encore écrits restent des cases vides : jamais lancés.
    vides = {poste.nom for poste in ORDRE_SEAU if poste.case_vide}
    assert vides == {"griffe", "lavage"}
    # Sur la vraie machine, pas de lot sans spray ni micropore (question 3 de la PR n° 89 en
    # attente), ni sans couvercle et fermeture.
    obligatoires = {poste.nom for poste in ORDRE_SEAU if poste.obligatoire}
    assert {"spray", "micropore", "couvercle", "fermeture"} <= obligatoires
    # Le couvercle (tâche 41 bis) est posé avant d'être clipsé, la fermeture vient juste après.
    couvercle = next(p for p in ORDRE_SEAU if p.nom == "couvercle")
    assert (
        couvercle.case_vide is None and couvercle.etapes[0] == "remplissage.preparer_le_couvercle"
    )
    assert "fermeture" in couvercle.besoin_ensuite


def test_les_etapes_d_ordre_seau_existent_dans_les_modules(reglages_depot, liste):
    with Simulateur(reglages_depot, liste, "cycle") as simulateur:
        mode = ModeSeaux(reglages_depot, PiecesSimulees(simulateur), simulateur.chef)
        modules = mode.modules_du_lot(lot_du_simulateur(simulateur))
    etapes = {f"{module.nom}.{etape.nom}" for module in modules for etape in module.etapes}
    for poste in ORDRE_SEAU:
        if mode.pret(poste.nom):
            assert set(poste.etapes) <= etapes, poste.nom


LANCES = ["seau_vide", "qr_du_flanc", "au_poste", "spray", "micropore", "griffe", "mycelium"]
BON = [
    "remplissage.prendre_le_seau",
    "remplissage.poser_le_seau",
    "remplissage.orienter_l_anse",
    "remplissage.centrer",
    "remplissage.aller_au_poste",
    "remplissage.spray_pulveriser",
    "remplissage.spray_ranger_le_bras",
    "remplissage.micropore_rangee_du_haut",
    "remplissage.ramener_au_vidage",
    "remplissage.verser",
    "mycelium.agiter",
    "remplissage.verser",
    "mycelium.agiter",
]


def deplacer(etapes, etape, avant):
    """`etape` (sa 1re fois) déplacée juste avant la 1re fois de `avant`."""
    etapes = list(etapes)
    etapes.remove(etape)
    etapes.insert(etapes.index(avant), etape)
    return etapes


def test_un_seau_qui_ne_suit_pas_l_ordre_est_vu():
    assert verifier_ordre(BON * 2, LANCES) == []
    # QR du flanc lu avant le serrage des barres (centrage).
    probleme = verifier_ordre(
        deplacer(BON, "remplissage.centrer", "remplissage.orienter_l_anse"), LANCES
    )
    assert len(probleme) == 1
    assert "remplissage.centrer → remplissage.orienter_l_anse" in probleme[0]
    # Spray avant la 1re couche.
    probleme = verifier_ordre(
        deplacer(BON, "remplissage.verser", "remplissage.spray_pulveriser"), LANCES
    )
    assert len(probleme) == 1 and probleme[0].startswith("seau n° 1 : ordre")
    # Rangées du haut après le spray...
    probleme = verifier_ordre(
        deplacer(BON, "remplissage.micropore_rangee_du_haut", "remplissage.spray_pulveriser"),
        LANCES,
    )
    assert len(probleme) == 1
    assert "remplissage.micropore_rangee_du_haut → remplissage.spray_pulveriser" in probleme[0]
    # ... et avant la 1re couche.
    tard = [e for e in BON if e != "remplissage.micropore_rangee_du_haut"]
    tard.insert(tard.index("mycelium.agiter"), "remplissage.micropore_rangee_du_haut")
    probleme = verifier_ordre(tard, LANCES)
    assert len(probleme) == 1
    assert "remplissage.verser → remplissage.micropore_rangee_du_haut" in probleme[0]
    # Un poste lancé dont l'étape manque.
    sans_spray = [e for e in BON if not e.startswith("remplissage.spray_")]
    assert verifier_ordre(sans_spray, LANCES) == [
        "seau n° 1 : étape « remplissage.spray_pulveriser » pas faite",
        "seau n° 1 : étape « remplissage.spray_ranger_le_bras » pas faite",
    ]
    assert verifier_ordre([], LANCES) == ["aucun seau commencé"]


# ---------------------------------------------------------------- ce qui est prêt


def test_avec_le_faux_materiel_les_modules_attendus_sont_prets(reglages_depot, liste):
    with Simulateur(reglages_depot, liste, "cycle") as simulateur:
        mode = ModeSeaux(reglages_depot, PiecesSimulees(simulateur), simulateur.chef)
    assert mode.postes_lances == [
        "seau_vide",
        "qr_du_flanc",
        "au_poste",
        "spray",
        "micropore",
        "mycelium",
        "couvercle",
        "fermeture",
        "stockage",
    ]
    assert mode.refus_lot() is None
    assert "tâche 23" in mode.etats["griffe"].raison
    assert "vidange-simulateur poste_fut" in mode.etats["fut"].raison


def test_un_module_sans_reglage_n_est_pas_lance(reglages_depot, liste):
    reglages = sans_partie(reglages_depot, "micropore")
    with Simulateur(reglages, liste, "cycle") as simulateur:
        mode = ModeSeaux(reglages, PiecesSimulees(simulateur), simulateur.chef)
    assert mode.etats["micropore"].en_texte() == (
        "pas lancé : machine.yaml n'a pas de partie « micropore »"
    )
    # Le micropore n'est pas du cœur : dans le simulateur, le lot peut partir sans lui.
    assert mode.refus_lot() is None

    reglages = sans_partie(reglages_depot, "spray")
    with Simulateur(reglages, liste, "cycle") as simulateur:
        mode = ModeSeaux(reglages, PiecesSimulees(simulateur), simulateur.chef)
    assert mode.etats["spray"].raison == "machine.yaml n'a pas de partie « spray »"
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
    for nom in ("fut", "seau_vide", "qr_du_flanc", "spray", "mycelium", "micropore", "stockage"):
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
    assert mode.etats["seau_vide"].raison == CARTES_PAS_CONSTRUITES
    # Sans la vision donnée aux pièces, la raison est dite (jamais « tâche 40 ter manquante »).
    assert mode.etats["qr_du_flanc"].raison == VISION_ABSENTE
    assert mode.etats["spray"].raison == CARTE_SPRAY
    assert mode.etats["mycelium"].raison == CARTES_PAS_CONSTRUITES
    assert mode.etats["micropore"].raison == VISION_ABSENTE
    assert mode.etats["fut"].raison == "poste du fût pas suivi (entrées/sorties pas ouvertes)"
    assert mode.refus_lot() == f"« seau_vide » pas lancé : {CARTES_PAS_CONSTRUITES}"


def test_la_vision_du_micropore_ne_manque_que_pour_ses_reglages_ou_sa_camera(reglages_depot):
    """Tâche 40 ter : le QR du flanc et le micropore ne sont plus « pas écrits ». Sur la vraie
    machine, ils attendent les valeurs vraies de vision.yaml (inspection) ; ailleurs, la caméra."""
    vision = reglages_depot.vision
    inspection = vision.inspection
    regard = object()  # le poste ne demande que sa présence

    def pieces(vraie, vision_donnee=vision, regard_donne=regard):
        return PiecesMachine(
            None, None, vraie_machine=vraie, vision=vision_donnee, regard=regard_donne
        )

    # Vraie machine : EXEMPLE interdit.
    assert pieces(True).manque("qr_du_flanc") == INSPECTION_EXEMPLE
    assert pieces(True).manque("micropore") == INSPECTION_EXEMPLE
    # Seule la partie « inspection » compte (le haut de vision.yaml est celui des autres caméras).
    sans_exemple = inspection.model_copy(update={"exemple": False})
    vrai = vision.model_copy(update={"inspection": sans_exemple})
    assert vrai.exemple
    # Puis les cartes du chariot et de la tête (tâche 45 ter : tests/test_cycle_cartes.py).
    assert pieces(True, vrai).manque("qr_du_flanc") == CARTES_PAS_CONSTRUITES
    assert pieces(True, vrai).manque("micropore") == CARTES_PAS_CONSTRUITES
    sans_partie = vrai.model_copy(update={"inspection": None})
    assert pieces(True, sans_partie).manque("qr_du_flanc") == INSPECTION_ABSENTE
    # Sans caméra ouverte.
    assert pieces(True, vrai, None).manque("qr_du_flanc") == CAMERA_ABSENTE
    # Faux matériel : les EXEMPLES sont permis.
    assert pieces(False).manque("qr_du_flanc") == CARTES_PAS_CONSTRUITES
    assert "40 ter" not in " ".join(
        str(pieces(False).manque(poste)) for poste in ("qr_du_flanc", "micropore")
    )


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
        assert banc.texte("t_info").startswith("cartes du chariot et de la tête")
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
    # Les cartes du chariot et de la tête sont construites sur le faux matériel (tâche 45 ter) ;
    # le boîtier du chariot n'y est pas branché (pas de PCA9685 ni de ToF).
    assert "Mode seaux, seau_vide : pas lancé : attend « mycelium » (pas prêt)" in journal
    assert "Mode seaux, qr_du_flanc : pas lancé : attend « mycelium » (pas prêt)" in journal
    assert "[attention] mode seaux, micropore : pas lancé : boîtier du chariot" in journal
    assert "[attention] mode seaux, couvercle : pas lancé : attend « fermeture »" in journal
    assert "[bloquant] mode seaux : aucun lot de seaux ne peut partir" in journal


# ---------------------------------------------------------------- le lot simulé


def test_lot_complet_simule_sans_alarme(reglages_depot, liste):
    with Simulateur(reglages_depot, liste, "cycle") as simulateur:
        mode, planning, problemes = jouer_cycle(simulateur)
        magasin = mode.en_cours.pieces.plan.magasin
        faits = list(mode.en_cours.pieces.plan.faits)
    assert planning.probleme == ""
    assert problemes == []
    seaux = reglages_depot.simulateur.cycle.seaux
    assert faits == [f"S{numero:04d}" for numero in range(301, 301 + seaux)]
    assert [ligne.etape for ligne in planning.lignes].count("ranger") == seaux
    # Lot de 18 : 6 seaux déjà dans la file 1, 14 au tiroir, 4 sur la bande, puis fin de lot.
    assert magasin.messages[-1].startswith("fin de lot")
    assert magasin.seaux_pleins() == 0


def test_dans_le_lot_simule_spray_et_micropore_suivent_l_ordre_corrige(reglages_depot, liste):
    """Fils Spray, Micropore et Guidage caméra (07/11/2026) : QR lu avant le serrage des barres,
    spray sur le seau vide avant la 1re couche, rangées du haut après le spray et avant la 1re
    couche, rangée du fond seulement quand le seau pèse assez."""
    with Simulateur(reglages_depot, liste, "cycle") as simulateur:
        pieces = PiecesSimulees(simulateur)
        mode = ModeSeaux(reglages_depot, pieces, simulateur.chef)
        modules = mode.modules_du_lot(lot_du_simulateur(simulateur))
        scenario = pieces.scenario
        micropore = scenario.micropore.micropore
        poses = []
        poser = micropore._poser_rangee

        def espion(suivi, rang, rangee, au_poste):
            contenu = scenario.chariot.contenu_kg
            poses.append((suivi.seau.code, "fond" if rangee.fond else "haut", contenu))
            yield from poser(suivi, rang, rangee, au_poste)

        micropore._poser_rangee = espion
        planning = simulateur.jouer(modules)
        doses = [o for o in simulateur.carte_spray().ordres if o[0] == table_spray.ORDRE_SPRAY]
    assert planning.probleme == ""
    assert (
        verifier_ordre(
            [f"{ligne.module}.{ligne.etape}" for ligne in planning.lignes],
            [*mode.postes_lances, *JOUES_EN_FAUX],
        )
        == []
    )
    etapes = [ligne.etape for ligne in planning.lignes if ligne.module == "remplissage"]
    # Une dose de spray par seau, une seule fois.
    seaux = reglages_depot.simulateur.cycle.seaux
    assert etapes.count("spray_pulveriser") == seaux
    assert len(doses) == seaux
    # Le 1er seau : QR, centrage, poste, spray, rangées du haut, puis la 1re couche.
    premier = etapes[: etapes.index("verser")]
    suite = [
        "orienter_l_anse",
        "centrer",
        "aller_au_poste",
        "spray_pulveriser",
        "spray_ranger_le_bras",
        "micropore_rangee_du_haut",
    ]
    assert [e for e in premier if e in suite] == suite
    seuil = reglages_depot.machine.micropore.fond_poids_min_kg
    codes = {code for code, _, _ in poses}
    assert len(codes) == seaux
    for code in codes:
        du_seau = [(quoi, kg) for c, quoi, kg in poses if c == code]
        hauts = [kg for quoi, kg in du_seau if quoi == "haut"]
        fonds = [kg for quoi, kg in du_seau if quoi == "fond"]
        # Rangées du haut sur le seau vide, rangée du fond après le poids mini.
        assert hauts and all(kg == 0.0 for kg in hauts), code
        assert fonds and all(kg >= seuil for kg in fonds), code
        assert [quoi for quoi, _ in du_seau].index("fond") > 0


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
    # Coupure de courant au bout de 2460 s simulées : 4e seau, dosage de sa 3e couche.
    coupe = duree_max(reglages_depot, 2460)
    with Simulateur(coupe, liste, "cycle", carnet=carnet) as simulateur:
        _, planning, _ = jouer_cycle(simulateur)
    assert planning.probleme.startswith("bloqué au bout de duree_max_s")
    etat = carnet.lire()
    note = next(n for n in etat["modules"] if n["module"] == "remplissage")
    memoire = note["memoire"]
    assert note["statut"] == "en_cours"
    assert (note["etape"], memoire["numero"], memoire["couche"]) == ("doser", 3, 3)
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
