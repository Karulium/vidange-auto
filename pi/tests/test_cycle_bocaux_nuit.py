"""Tests du programme principal : mode bocaux et nuit UV-ozone (tâche 45 bis)."""

import threading

import pytest

from vidange.chef import Carnet, Chef, ErreurChef
from vidange.cycle import (
    ORDRE_BOCAUX,
    ORDRE_NUIT,
    ModeBocaux,
    ModeNuit,
    ModeSeaux,
    verifier_ordre,
)
from vidange.cycle.machine import (
    BOCAUX_SALES,
    CARTES_PAS_CONSTRUITES,
    NETTOYAGE_ABSENT,
    PHOTO_DU_PLAFOND,
    PiecesMachine,
)
from vidange.cycle.mode_bocaux import LotBocaux
from vidange.cycle.ordre import DEBUT_DU_LOT_BOCAUX
from vidange.cycle.simulation import (
    PiecesSimulees,
    jouer_bocaux,
    jouer_lavage_bocaux,
    jouer_nuit,
    lot_bocaux_du_simulateur,
    lot_du_simulateur,
)
from vidange.demarrage import principal
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.journal import NOM_FICHIER
from vidange.mode import ErreurMode, ModeMachine
from vidange.nettoyage import ErreurNettoyage
from vidange.reglages import charger_reglages
from vidange.simulateur import Simulateur
from vidange.simulateur.outil import main as simulateur

from .conftest import DOSSIER_PI
from .test_chef_exemple import attendre
from .test_cycle import duree_max, sans_partie
from .test_demarrage import options, raccords_faux
from .test_ecran import BancEcran
from .test_nettoyage import Banc


@pytest.fixture(scope="module")
def reglages_depot():
    return charger_reglages(DOSSIER_PI / "reglages")


@pytest.fixture(scope="module")
def liste():
    return charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")


class PiecesVraies:
    """Des pièces sur la vraie machine, auxquelles rien ne manquerait."""

    vraie_machine = True

    def manque(self, poste):
        return None


def mode_bocaux_simule(reglages, liste, scenario, **options):
    simulateur_ = Simulateur(reglages, liste, scenario, **options)
    mode = ModeBocaux(reglages, PiecesSimulees(simulateur_), simulateur_.chef)
    return simulateur_, mode


# ---------------------------------------------------------------- l'ordre


def test_l_ordre_des_bocaux_et_de_la_nuit_est_ecrit_a_un_seul_endroit():
    assert [poste.nom for poste in ORDRE_BOCAUX] == [
        "fut",
        "entonnoir",
        "versement",
        "lavage_bocaux",
    ]
    assert [poste.nom for poste in ORDRE_NUIT] == ["enceinte", "ozone", "purge"]
    # Le versement de la griffe est une case vide : jamais lancé, ni sur la machine ni en faux.
    vides = {poste.nom for poste in ORDRE_BOCAUX if poste.case_vide}
    assert vides == set()
    # La nuit : seuls l'enceinte et l'ozone la bloquent.
    assert {poste.nom for poste in ORDRE_NUIT if poste.coeur} == {"enceinte", "ozone"}


def test_les_etapes_d_ordre_bocaux_existent_dans_les_modules(reglages_depot, liste):
    with Simulateur(reglages_depot, liste, "entonnoir") as simulateur_:
        mode = ModeBocaux(reglages_depot, PiecesSimulees(simulateur_), simulateur_.chef)
        modules = mode.modules_du_lot(lot_bocaux_du_simulateur(simulateur_)) + mode.modules_lavage()
    etapes = {f"{module.nom}.{etape.nom}" for module in modules for etape in module.etapes}
    for poste in ORDRE_BOCAUX:
        if mode.pret(poste.nom):
            assert set(poste.etapes) <= etapes, poste.nom


def test_un_lot_de_bocaux_qui_ne_suit_pas_l_ordre_est_vu():
    bon = [
        "entonnoir.demander_la_pose",
        "entonnoir.controler_la_camera",
        "entonnoir.verser",
        "entonnoir.lire_le_col_suivant",
        "entonnoir.prendre_l_entonnoir",
        "entonnoir.poser_sur_le_bocal",
        "entonnoir.verser",
        "entonnoir.lire_le_col_suivant",
        "entonnoir.enlever_a_la_main",
    ]
    args = (ORDRE_BOCAUX, DEBUT_DU_LOT_BOCAUX, "lot de bocaux")
    assert verifier_ordre(bon, ["entonnoir"], *args) == []
    # Versement avant que la caméra ait vu l'entonnoir.
    mauvais = [bon[0], bon[2], bon[1], *bon[3:]]
    probleme = verifier_ordre(mauvais, ["entonnoir"], *args)
    assert len(probleme) == 1 and probleme[0].startswith("lot de bocaux n° 1 : ordre")
    assert verifier_ordre([], ["entonnoir"], *args) == ["aucun lot de bocaux commencé"]


# ---------------------------------------------------------------- ce qui est prêt


def test_avec_le_faux_materiel_les_postes_des_bocaux_et_de_la_nuit_sont_prets(
    reglages_depot, liste
):
    with Simulateur(reglages_depot, liste, "entonnoir") as simulateur_:
        mode = ModeBocaux(reglages_depot, PiecesSimulees(simulateur_), simulateur_.chef)
    assert mode.postes_lances == ["entonnoir", "lavage_bocaux"]
    assert mode.refus_lot() is None and mode.refus_lavage() is None
    assert "joué en faux" in mode.etats["versement"].raison
    assert "vidange-simulateur poste_fut" in mode.etats["fut"].raison
    assert mode.texte_ecran() == ("Lot de bocaux : prêt", "")

    with Simulateur(reglages_depot, liste, "nuit_uv_ozone") as simulateur_:
        from vidange.nettoyage.simulation import nettoyage_du_simulateur

        nuit = ModeNuit(
            reglages_depot,
            PiecesSimulees(simulateur_),
            nettoyage_du_simulateur(simulateur_).nettoyage,
        )
    assert nuit.postes_lances == ["enceinte", "ozone", "purge"]
    assert nuit.refus_poste() is None
    assert nuit.texte_ecran() == ("Nuit UV-ozone : prête", "")


def test_un_poste_sans_reglage_n_est_pas_lance_avec_la_raison(reglages_depot, liste):
    reglages = sans_partie(reglages_depot, "entonnoir")
    with Simulateur(reglages, liste, "entonnoir") as simulateur_:
        mode = ModeBocaux(reglages, PiecesSimulees(simulateur_), simulateur_.chef)
        assert mode.etats["entonnoir"].en_texte() == (
            "pas lancé : machine.yaml n'a pas de partie « entonnoir »"
        )
        assert mode.refus_lot() == (
            "« entonnoir » pas lancé : machine.yaml n'a pas de partie « entonnoir »"
        )
        with pytest.raises(ErreurChef, match="lot de bocaux impossible"):
            mode.modules_du_lot(lot_bocaux_du_simulateur(simulateur_))
    constats = {constat.sujet: constat for constat in mode.constats()}
    assert constats["mode bocaux, entonnoir"].niveau == "attention"
    assert constats["mode bocaux"].niveau == "attention"
    assert mode.texte_ecran() == (
        "Lot de bocaux : entonnoir pas prêt",
        "machine.yaml n'a pas de partie « entonnoir »",
    )
    # Le lavage des bocaux ne dépend pas de l'entonnoir.
    assert mode.refus_lavage() is None

    reglages = sans_partie(reglages_depot, "lavage")
    with Simulateur(reglages, liste, "lavage_bocaux") as simulateur_:
        mode = ModeBocaux(reglages, PiecesSimulees(simulateur_), simulateur_.chef)
        assert mode.etats["lavage_bocaux"].raison == (
            "machine.yaml n'a pas de partie « lavage.lave_bocal »"
        )
        with pytest.raises(ErreurChef, match="lavage des bocaux impossible"):
            mode.modules_lavage()

    reglages = sans_partie(reglages_depot, "nettoyage")
    with Simulateur(reglages, liste, "entonnoir") as simulateur_:
        nuit = ModeNuit(reglages, PiecesSimulees(simulateur_), None)
    assert nuit.etats["enceinte"].raison == "machine.yaml n'a pas de partie « nettoyage »"
    assert nuit.refus_poste() == (
        "poste « enceinte » pas lancé : machine.yaml n'a pas de partie « nettoyage »"
    )
    constats = {constat.sujet: constat for constat in nuit.constats()}
    assert constats["nuit UV-ozone"].niveau == "attention"
    assert nuit.texte_ecran()[0] == "Nuit UV-ozone : enceinte pas prêt"


def test_sur_la_vraie_machine_les_reglages_d_exemple_sont_interdits(reglages_depot):
    chef = Chef(reglages_depot.machine, reglages_depot.programme.chef)
    mode = ModeBocaux(reglages_depot, PiecesVraies(), chef)
    for nom in ("fut", "entonnoir", "lavage_bocaux"):
        assert "valeurs d'EXEMPLE dans machine.yaml" in mode.etats[nom].raison, nom
        assert "interdit sur la vraie machine" in mode.etats[nom].raison
    assert mode.refus_lot().startswith("« fut » pas lancé : valeurs d'EXEMPLE")
    assert "lave_bocal" in mode.etats["lavage_bocaux"].raison or "lavage" in (
        mode.etats["lavage_bocaux"].raison
    )
    nuit = ModeNuit(reglages_depot, PiecesVraies(), None)
    assert "valeurs d'EXEMPLE dans machine.yaml (nettoyage)" in nuit.etats["enceinte"].raison
    assert nuit.refus_poste() is not None


def test_les_pieces_de_la_machine_disent_ce_qui_manque(reglages_depot):
    reglages = reglages_depot.model_copy(
        update={"machine": reglages_depot.machine.model_copy(update={"exemple": False})}
    )
    chef = Chef(reglages.machine, reglages.programme.chef)
    mode = ModeBocaux(reglages, PiecesMachine(None, None, vraie_machine=False), chef)
    assert mode.etats["entonnoir"].raison == CARTES_PAS_CONSTRUITES
    assert mode.etats["lavage_bocaux"].raison == CARTES_PAS_CONSTRUITES
    assert mode.refus_lot() is not None and mode.refus_lavage() is not None
    nuit = ModeNuit(reglages, PiecesMachine(None, None, vraie_machine=False), None)
    assert nuit.etats["enceinte"].raison == NETTOYAGE_ABSENT


def test_la_nuit_part_si_son_poste_est_pret_meme_sans_capteurs_de_purge(reglages_depot, tmp_path):
    b = Banc(tmp_path)
    try:
        b.preparer_nuit()
        # Le Nettoyage n'a pas ses capteurs de purge : le poste « purge » manque, pas la nuit.
        b.n.particules_dedans = None
        pieces = PiecesMachine(None, b.materiel, vraie_machine=False, nettoyage=b.n)
        nuit = ModeNuit(reglages_depot, pieces, b.n)
        assert nuit.postes_lances == ["enceinte", "ozone"]
        assert nuit.etats["purge"].raison == "capteurs de la purge absents (particules_dedans)"
        assert nuit.refus_poste() is None
        b.n.programmer_nuit("essai")
        b.n.annuler_nuit("essai")
        constats = {c.sujet: c for c in nuit.constats()}
        assert constats["nuit UV-ozone, purge"].niveau == "attention"
        assert constats["nuit UV-ozone"].niveau == "ok"
    finally:
        b.registre.fermer()


def test_la_nuit_refuse_de_partir_sur_la_vraie_machine_en_exemple(reglages_depot, tmp_path):
    b = Banc(tmp_path)
    try:
        b.preparer_nuit()
        # Vraie machine, machine.yaml → nettoyage en EXEMPLE : nuit refusée, avec la raison, par le
        # bouton de l'écran comme par la page web (Nettoyage.refus_nuit).
        vraie = PiecesMachine(None, b.materiel, vraie_machine=True, nettoyage=b.n)
        nuit = ModeNuit(reglages_depot, vraie, b.n)
        assert nuit.refus_poste() is not None
        with pytest.raises(ErreurNettoyage, match="Nuit UV-ozone refusée : poste « enceinte »"):
            b.n.programmer_nuit("essai")
        assert "valeurs d'EXEMPLE" in b.n.etat().refus_nuit
    finally:
        b.registre.fermer()


# ---------------------------------------------------------------- un seul mode, un seul lot


def test_pas_de_changement_de_mode_pendant_un_lot_de_bocaux(reglages_depot, liste, tmp_path):
    with Simulateur(reglages_depot, liste, "entonnoir") as simulateur_:
        chef = simulateur_.chef
        mode_machine = ModeMachine(tmp_path / "mode.json", chef)
        mode = ModeBocaux(
            reglages_depot,
            PiecesSimulees(simulateur_),
            chef,
            mode_actuel=lambda: mode_machine.actuel,
        )
        lot = lot_bocaux_du_simulateur(simulateur_)
        # Mauvais mode : le lot de bocaux est un travail du mode « production ».
        mode_machine.changer("uv_ozone", "essai")
        with pytest.raises(ErreurChef, match="mode « production » n'est pas choisi"):
            mode.lancer_lot(lot)
        mode_machine.changer("lavage", "essai")
        with pytest.raises(ErreurChef, match="mode « production » n'est pas choisi"):
            mode.lancer_lot(lot)
        # Laver les bocaux est un travail du mode « lavage ».
        mode_machine.changer("production", "essai")
        with pytest.raises(ErreurChef, match="mode « lavage » n'est pas choisi"):
            mode.lancer_lavage()

        assert mode.lancer_lot(lot) == ["entonnoir"]
        # Pendant le lot : ni changement de mode, ni second lot, ni lavage.
        with pytest.raises(ErreurMode, match="pas pendant un cycle \\(entonnoir\\)"):
            mode_machine.changer("lavage", "essai")
        assert mode_machine.actuel == "production"
        with pytest.raises(ErreurChef, match="un lot est déjà en route"):
            mode.lancer_lot(lot)
        seaux = ModeSeaux(reglages_depot, PiecesSimulees(simulateur_), chef, lambda: "production")
        with pytest.raises(ErreurChef, match="un lot est déjà en route"):
            seaux.lancer_lot(lot_du_simulateur(simulateur_))


def test_pas_de_lot_de_bocaux_pendant_un_lot_de_seaux(reglages_depot, liste):
    with Simulateur(reglages_depot, liste, "cycle") as simulateur_:
        chef = simulateur_.chef
        seaux = ModeSeaux(reglages_depot, PiecesSimulees(simulateur_), chef, lambda: "production")
        bocaux = ModeBocaux(
            reglages_depot, PiecesSimulees(simulateur_), chef, mode_actuel=lambda: "production"
        )
        assert seaux.lancer_lot(lot_du_simulateur(simulateur_)) == ["remplissage", "mycelium"]
        with pytest.raises(ErreurChef, match="un lot est déjà en route"):
            bocaux.lancer_lot(LotBocaux(("bocal_0_0",)))
        with pytest.raises(ErreurChef, match="lot de seaux refusé"):
            seaux.lancer_lot(lot_du_simulateur(simulateur_))


# ---------------------------------------------------------------- les lots simulés


def test_lot_de_bocaux_simule_sans_alarme(reglages_depot, liste):
    with Simulateur(reglages_depot, liste, "entonnoir") as simulateur_:
        mode, planning, problemes = jouer_bocaux(simulateur_)
        entonnoir = mode.en_cours.pieces.entonnoir
        lot = lot_bocaux_du_simulateur(simulateur_)
    assert planning.probleme == ""
    assert problemes == []
    assert entonnoir.verses == set(lot.bocaux)
    assert entonnoir.suspects == []
    etapes = [ligne.etape for ligne in planning.lignes]
    assert etapes.count("verser") == len(lot.bocaux)
    assert etapes[-1] == "enlever_a_la_main"
    assert entonnoir.place == "hors_machine"


def test_lavage_des_bocaux_simule_sans_alarme(reglages_depot, liste):
    with Simulateur(reglages_depot, liste, "lavage_bocaux") as simulateur_:
        mode, planning, problemes = jouer_lavage_bocaux(simulateur_)
        objets = simulateur_.reglages.simulateur.lavage.bocaux
    assert planning.probleme == ""
    assert problemes == []
    etapes = [ligne.etape for ligne in planning.lignes]
    assert etapes.count("laver_le_bocal") == len(objets)
    assert etapes[-1] == "finir_la_serie"


def test_nuit_uv_ozone_simulee_sans_alarme(reglages_depot, liste):
    with Simulateur(reglages_depot, liste, "nuit_uv_ozone") as simulateur_:
        mode, planning, problemes = jouer_nuit(simulateur_)
    assert planning.probleme == ""
    assert problemes == []
    assert mode.postes_lances == ["enceinte", "ozone", "purge"]
    etapes = [ligne.etape for ligne in planning.lignes]
    assert etapes[:6] == [
        "fermer_le_store",
        "purge",
        "lancer_la_nuit",
        "generation",
        "contact",
        "retour",
    ]


def test_l_outil_joue_les_bocaux_et_la_nuit(capsys):
    assert simulateur(["cycle", "--lot", "bocaux", "--delai-go", "0"]) == 0
    sortie = capsys.readouterr().out
    assert "Mode bocaux (entonnoir, versement, lavage) :" in sortie
    assert "lot : peut partir" in sortie
    assert "Ordre du cycle pas suivi" not in sortie

    assert simulateur(["cycle", "--lot", "nuit", "--delai-go", "0"]) == 0
    sortie = capsys.readouterr().out
    assert "Nuit UV-ozone (le Nettoyage la mène" in sortie
    assert "nuit : peut partir" in sortie


def test_l_outil_joue_tout_d_un_coup(capsys):
    assert simulateur(["cycle", "--lot", "tout", "--delai-go", "0"]) == 0
    sortie = capsys.readouterr().out
    for titre in ("seaux", "bocaux", "lavage_bocaux", "nuit"):
        assert f"===== {titre} =====" in sortie
    assert "Ordre du cycle pas suivi" not in sortie


# ---------------------------------------------------------------- reprise après une coupure


def test_reprise_d_un_lot_de_bocaux_apres_une_coupure(reglages_depot, liste, tmp_path):
    carnet = Carnet(tmp_path / "etat-cycle.json")
    # Coupure de courant à 30 s simulées : le 1er bocal est versé, l'entonnoir est transporté.
    coupe = duree_max(reglages_depot, 30)
    with Simulateur(coupe, liste, "entonnoir", carnet=carnet) as simulateur_:
        _, planning, _ = jouer_bocaux(simulateur_)
        lot = lot_bocaux_du_simulateur(simulateur_)
    assert planning.probleme.startswith("bloqué au bout de duree_max_s")
    note = next(n for n in carnet.lire()["modules"] if n["module"] == "entonnoir")
    memoire = note["memoire"]
    assert note["statut"] == "en_cours"
    assert note["etape"] in ("prendre_l_entonnoir", "poser_sur_le_bocal")
    assert len(memoire["verses"]) == 1
    assert memoire["lot"]["bocaux"] == list(lot.bocaux)
    assert memoire["prochain"] is not None and memoire["prochain"] not in memoire["verses"]

    # Le Pi redémarre : nouveau chef, nouvelles pièces, même carnet.
    with Simulateur(reglages_depot, liste, "entonnoir") as simulateur_:
        chef = Chef(reglages_depot.machine, reglages_depot.programme.chef, carnet)
        mode = ModeBocaux(reglages_depot, PiecesSimulees(simulateur_), chef)
        repris = chef.reprendre_cycle(mode.modules_a_reprendre(carnet.lire()))
    assert repris == ["entonnoir"]
    etat = next(m for m in chef.etat().modules if m.module == "entonnoir")
    assert etat.etape == note["etape"] and etat.attend == "Go de Karulium"
    entonnoir = mode.en_cours.pieces.entonnoir
    assert sorted(entonnoir.verses) == memoire["verses"]
    assert entonnoir.prochain == memoire["prochain"]
    assert entonnoir.restants == memoire["restants"]
    assert list(entonnoir.centre) == memoire["centre"]


def test_un_carnet_sans_lot_de_bocaux_ne_reprend_rien(reglages_depot, liste):
    with Simulateur(reglages_depot, liste, "entonnoir") as simulateur_:
        mode = ModeBocaux(reglages_depot, PiecesSimulees(simulateur_), simulateur_.chef)
        assert mode.modules_a_reprendre(None) == []
        assert mode.modules_a_reprendre({"modules": []}) == []
        sans_lot = {"modules": [{"module": "entonnoir", "statut": "en_cours", "memoire": {}}]}
        assert mode.modules_a_reprendre(sans_lot) == []


def test_reprise_en_pleine_nuit_le_generateur_n_est_jamais_relance_seul(reglages_depot, tmp_path):
    b = Banc(tmp_path)
    try:
        b.preparer_nuit()
        b.n.programmer_nuit("essai", tout_de_suite=True)
        b.faux.regler("ozone_dedans", 12)
        b.avancer(30)
        assert b.n.nuit.phase == "generation" and b.commande("generateur_ozone")
        # Coupure de courant : toutes les sorties retombent, le Pi redémarre (nouveau Nettoyage et
        # nouveau poste « nuit », même fichier de la nuit).
        b.materiel.mettre_au_repos()
        b.horloge.t += 60
        b.n = b.nouveau()
        pieces = PiecesMachine(None, b.materiel, vraie_machine=False, nettoyage=b.n)
        nuit = ModeNuit(reglages_depot, pieces, b.n)
        assert nuit.refus_poste() is None
        assert b.n.nuit.phase == "retour"
        # Le poste dit à la check-list que la nuit est reprise et que rien n'est relancé.
        textes = [c.texte for c in nuit.constats() if c.sujet == "nuit UV-ozone"]
        assert any("retour sous le seuil" in t and "jamais relancé seul" in t for t in textes)
        # Une 2e nuit ne peut pas partir pendant la reprise.
        with pytest.raises(ErreurNettoyage, match="déjà en cours"):
            b.n.programmer_nuit("essai", tout_de_suite=True)
        b.avancer(10 * 60, pas=30)
        assert not b.commande("generateur_ozone")
        assert not b.commande("ventilateur_enceinte")
    finally:
        b.registre.fermer()


# ---------------------------------------------------------------- l'écran et la check-list


def test_l_ecran_dit_ce_qui_manque_selon_le_mode(tmp_path, reglages_depot):
    banc = BancEcran(tmp_path)
    try:
        chef = banc.chef
        pieces = PiecesMachine(None, None, vraie_machine=False)
        banc.ecran.mode_seaux = ModeSeaux(reglages_depot, pieces, chef)
        banc.ecran.mode_bocaux = ModeBocaux(reglages_depot, pieces, chef)
        banc.ecran.mode_nuit = ModeNuit(reglages_depot, pieces, None)
        banc.chef.abandonner("essai")
        banc.tour()
        # Production : les seaux d'abord (comme avant), puis les bocaux si les seaux sont prêts.
        assert banc.texte("t_attend") == "Lot de seaux : seau vide pas prêt"
        assert banc.texte("t_info").startswith("cartes du chariot et de la tête")
        banc.mode.changer("lavage", "essai")
        banc.tour()
        assert banc.texte("t_attend") == "Lavage des bocaux : pas prêt"
        assert PHOTO_DU_PLAFOND not in banc.texte("t_info")
        assert banc.texte("t_info").startswith("« lavage_bocaux » pas lancé")
        banc.mode.changer("uv_ozone", "essai")
        banc.tour()
        assert banc.texte("t_attend") == "Nuit UV-ozone : enceinte pas prêt"
        assert banc.texte("t_info") == NETTOYAGE_ABSENT
    finally:
        banc.registre.fermer()


def test_au_demarrage_la_check_list_dit_ce_qui_manque(reglages, entrees_sorties, tmp_path):
    raccords, messages, _ = raccords_faux(entrees_sorties)
    arguments = [*options(reglages, tmp_path), "--entrees-sorties", str(entrees_sorties)]
    arret = threading.Event()
    fil = threading.Thread(target=lambda: principal(arguments, arret, raccords))
    fil.start()
    try:
        attendre(lambda: "READY=1" in messages)
    finally:
        arret.set()
        fil.join(10)
    journal = (tmp_path / "donnees" / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    # Faux matériel : la nuit UV-ozone est prête, les bocaux ne le sont pas (la Préhension est
    # construite, la photo du plafond n'est pas lue).
    assert "Nuit UV-ozone, enceinte : prêt" in journal
    assert "Nuit UV-ozone, ozone : prêt" in journal
    assert "nuit UV-ozone, enceinte" not in journal  # prête : rien à signaler
    assert f"Mode bocaux, entonnoir : pas lancé : {PHOTO_DU_PLAFOND}" in journal
    # La griffe est construite sur le faux matériel (tâche 45 sexies) : le versement est prêt.
    assert "Mode bocaux, versement : prêt" in journal
    assert f"[attention] mode bocaux, lavage_bocaux : pas lancé : {BOCAUX_SALES}" in journal
    assert "[attention] mode bocaux : aucun lot de bocaux ne peut partir" in journal
