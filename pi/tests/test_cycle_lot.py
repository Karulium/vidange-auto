"""Tests du lot complet sur les vraies cartes (tâche 45 quater) : pièces assemblées, boucles de
fond, taille du lot, bouton de la page web, Go à l'écran.

Le faux matériel est branché par le même chemin que le vrai (Banc de test_cycle_cartes :
Materiel et sa fausse fabrique, faux FluidNC, tour des pesées, construire_cartes). Ce que la
machine n'a pas encore (griffe, QR du bocal, codeur, photo du plafond) est donné en faux par
`Sources`, comme le ferait le code qui l'écrira.
"""

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from vidange.api import Services, creer_app
from vidange.bocal_neuf.bocal_neuf import BocalNeuf
from vidange.chef import Chef, ErreurChef
from vidange.chef.chef import ATTENTE_GO, EtatChef, EtatModule
from vidange.couvercle.couvercle import Couvercle
from vidange.cycle import Lancement, ModeBocaux, ModeSeaux
from vidange.cycle.machine import (
    BOCAL_NEUF,
    BOCAUX_SALES,
    CARTES_PAS_CONSTRUITES,
    CODEUR,
    GRIFFE_DU_LOT,
    PHOTO_DE_LA_BANDE,
    PHOTO_DU_PLAFOND,
    QR_DU_BOCAL,
    VERSEMENT_BOCAL,
    FondDuLot,
    PiecesMachine,
    Sources,
    construire_cartes,
    presence_fluidnc,
    stockage_de_la_machine,
)
from vidange.cycle.mode_bocaux import LotBocaux
from vidange.cycle.mode_seaux import Lot, refus_taille_lot
from vidange.cycle.simulation import jouer_cycle
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fermeture.fermeture import Fermeture
from vidange.lavage.bocaux import LavageBocaux
from vidange.micropore.micropore import Micropore
from vidange.mycelium.mycelium import Mycelium
from vidange.reglages import ObjetLaveBocalSimule, charger_reglages
from vidange.remplissage.module import SeauAFaire
from vidange.remplissage.remplissage import Remplissage
from vidange.simulateur import Simulateur
from vidange.stockage import places

from .conftest import DOSSIER_PI
from .test_api import CLE, LOCAL, reglages_api
from .test_cycle_cartes import Banc
from .test_ecran import BancEcran

REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
VARIETE = "pleurote_grise"
FORMAT = "seau_a"
SEMENCE = list(places.places_semence(MACHINE))
BOITES = MACHINE.bocal_neuf.boites
REGLAGES_LOT = REGLAGES.programme.lot


@pytest.fixture(scope="module")
def liste():
    return charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")


class FausseGriffe:
    """La griffe que la tâche 23 écrira : un versement dure tant, elle est vue partie."""

    versement_s = 1.0

    def partie(self) -> bool:
        return True


class FauxPlafond:
    def entonnoir_vu(self, bocal):
        return True

    def centre_du_col(self, bocal):
        return places.places_bocaux(MACHINE)[bocal]

    def seaux_de_la_bande(self):
        return []


class FauxVersement:
    def verser(self, bocal):
        return None

    def fini(self):
        return True


def toutes_les_sources() -> Sources:
    plafond = FauxPlafond()
    return Sources(
        griffe=FausseGriffe(),
        qr_du_bocal=lambda place: f"SEM-{place}",
        bande=plafond,
        entonnoir=plafond,
        versement_bocal=FauxVersement(),
        bocaux_sales=lambda: [
            ObjetLaveBocalSimule(sorte="bocal_vide", x=1.0, y=0.5, contact_z=0.9)
        ],
    )


def remplir_le_stockage(stockage, bocaux=None, capsules=0, couvercles=18, variete=VARIETE):
    for place in SEMENCE[:bocaux]:
        stockage.poser_bocal(place, variete)
    stockage.inventaire.changer_boite(BOITES.capsules, capsules)
    stockage.inventaire.changer_boite(BOITES.couvercles_perces, couvercles)


class Machine:
    """Le faux matériel, les cartes construites comme au démarrage, et les pièces du lot."""

    def __init__(self, liste, sources=None, codeur=True, vraie_machine=False):
        self.banc = Banc(REGLAGES, liste)
        # Vide du venturi au repos : 0 kPa (le zéro est recalé au départ du lot).
        self.banc.fabrique.regler("vide_venturi", 0.0)
        self.cartes = construire_cartes(
            REGLAGES,
            self.banc.materiel,
            self.banc.liaisons,
            self.banc.pesees,
            self.banc.poste,
            vraie_machine,
            presence_fluidnc(REGLAGES.fluidnc, self.banc.ports, lister=list),
            mode=lambda: "production",
            erreur_codeur=(lambda: 0.0) if codeur else None,
        )
        self.stockage = stockage_de_la_machine(MACHINE, self.banc.materiel, vision=None)
        self.chef = Chef(MACHINE, REGLAGES.programme.chef)
        self.pieces = PiecesMachine(
            self.banc.poste,
            self.banc.materiel,
            vraie_machine=vraie_machine,
            vision=REGLAGES.vision,
            regard=object(),
            cartes=self.cartes,
            machine=MACHINE,
            permission=self.chef.permission,
            stockage=self.stockage,
            sources=toutes_les_sources() if sources is None else sources,
        )

    def mode_seaux(self, mode="production"):
        return ModeSeaux(REGLAGES, self.pieces, self.chef, mode_actuel=lambda: mode)

    def fermer(self):
        self.banc.fermer()


@pytest.fixture
def machine(liste):
    machine = Machine(liste)
    remplir_le_stockage(machine.stockage)
    yield machine
    machine.fermer()


def lot_de(nombre, variete=VARIETE):
    return Lot(FORMAT, tuple(SeauAFaire("", FORMAT, variete) for _ in range(nombre)))


# ---------------------------------------------------------------- les pièces du lot


def test_pieces_construites_le_remplissage_est_pret(machine):
    assert machine.cartes.absentes == {}
    pieces = machine.pieces
    assert pieces.manque("mycelium") is None
    mode = machine.mode_seaux()
    assert mode.refus_lot() is None
    assert mode.refus_lancer(lot_de(18)) is None
    lot = pieces.remplissage(lot_de(2), True, True, False, True)
    cartes = machine.cartes
    # Assemblé sur les cartes construites au démarrage (aucune pièce imaginaire).
    assert isinstance(lot.remplissage, Remplissage)
    assert lot.remplissage.chariot is cartes.chariot
    assert lot.prehension is cartes.prehension
    assert isinstance(lot.mycelium, Mycelium)
    assert lot.mycelium.agitateur is cartes.agitateur
    assert lot.mycelium.porte_bocal is cartes.porte_bocal
    assert isinstance(lot.mycelium.pose_bocal_neuf, BocalNeuf)
    assert lot.mycelium.pose_bocal_neuf.stockage is machine.stockage
    # Micropore et Fermeture branchés au Remplissage, sur la tête et le bras du chariot.
    assert lot.remplissage.micropore_branche and lot.remplissage.fermeture_branchee
    assert isinstance(lot.remplissage._micropore.__self__, Micropore)
    assert lot.remplissage._micropore.__self__.tete is cartes.tete_micropore
    assert isinstance(lot.remplissage._bras_galet.__self__, Fermeture)
    assert isinstance(lot.couvercle, Couvercle)
    assert lot.plan.magasin is machine.stockage
    assert lot.plan.versement_s == FausseGriffe.versement_s
    assert lot.griffe_partie()
    # Les modules du chef se construisent sur ces pièces.
    modules = mode.modules_du_lot(lot_de(2))
    assert [module.nom for module in modules] == ["remplissage", "mycelium"]


def test_piece_manquante_le_lot_dit_pourquoi(liste):
    machine = Machine(liste, sources=Sources(), codeur=False)
    try:
        pieces = machine.pieces
        assert pieces.manque("mycelium") == BOCAL_NEUF
        pieces.sources.qr_du_bocal = lambda place: "SEM"
        assert pieces.manque("mycelium") == CODEUR
        mode = machine.mode_seaux()
        assert mode.etats["mycelium"].raison == CODEUR
        assert "mycelium" in mode.refus_lot()
        with pytest.raises(ErreurChef, match="erreur du codeur"):
            pieces.remplissage(lot_de(1), False, False, False, False)
        assert pieces.manque("entonnoir") == PHOTO_DU_PLAFOND
        with pytest.raises(ErreurChef, match="photo du plafond"):
            pieces.entonnoir(LotBocaux(("bocal_0_0",)))
        assert pieces.manque("lavage_bocaux") == BOCAUX_SALES
        with pytest.raises(ErreurChef, match="bocaux sales"):
            pieces.lavage_bocaux()
    finally:
        machine.fermer()
    machine = Machine(liste, sources=Sources(qr_du_bocal=lambda place: "SEM"))
    try:
        # QR et codeur là : il manque encore la griffe (tâche 23), jamais inventée.
        assert machine.pieces.manque("mycelium") is None
        with pytest.raises(ErreurChef, match="griffe"):
            machine.pieces.remplissage(lot_de(1), False, False, False, False)
        assert GRIFFE_DU_LOT.startswith("enchaînement de la griffe")
        machine.pieces.sources.entonnoir = FauxPlafond()
        with pytest.raises(ErreurChef, match="versement de la griffe"):
            machine.pieces.entonnoir(LotBocaux(("bocal_0_0",)))
        assert VERSEMENT_BOCAL.startswith("versement de la griffe")
        machine.pieces.sources.qr_du_bocal = None
        assert machine.pieces.manque("mycelium") == QR_DU_BOCAL
    finally:
        machine.fermer()
    # Sans cartes construites : la raison, jamais un lot.
    sans = PiecesMachine(None, None, vraie_machine=False, machine=MACHINE)
    with pytest.raises(ErreurChef, match="cartes du chariot"):
        sans.remplissage(lot_de(1), False, False, False, False)
    assert sans.manque("mycelium") == CARTES_PAS_CONSTRUITES


def test_sur_la_vraie_machine_le_stockage_attend_la_photo_de_la_bande(machine):
    machine.pieces.vraie_machine = True
    machine.pieces.sources.bande = None
    assert machine.pieces.manque("stockage") == PHOTO_DE_LA_BANDE


def test_entonnoir_et_lave_bocal_sur_la_tete(machine):
    cartes = machine.cartes
    pieces = machine.pieces.entonnoir(LotBocaux(("bocal_0_0",)))
    assert pieces.prehension is cartes.prehension
    assert pieces.versement_fini()
    lavage = machine.pieces.lavage_bocaux()
    assert isinstance(lavage.bocaux, LavageBocaux)
    assert lavage.bocaux.lavage is cartes.lavage
    assert len(lavage.objets) == 1


# ---------------------------------------------------------------- la taille du lot


def test_un_lot_ne_depasse_pas_les_bocaux_de_semence_ni_les_capsules(liste):
    machine = Machine(liste)
    try:
        stockage = machine.stockage
        remplir_le_stockage(stockage)
        assert len(SEMENCE) == 18 and places.capacite_boite(MACHINE) == 18
        assert refus_taille_lot(MACHINE, stockage, lot_de(18)) is None
        refus = refus_taille_lot(MACHINE, stockage, lot_de(19))
        assert "19 seaux « pleurote_grise » mais 18 bocaux de semence" in refus
        assert "pas de rechargement en milieu de lot" in refus
        assert "bocaux de semence « shiitake »" in refus_taille_lot(
            MACHINE, stockage, lot_de(1, "shiitake")
        )
        stockage.inventaire.changer_boite(BOITES.capsules, 1)
        assert "17 places libres dans la boîte des capsules" in refus_taille_lot(
            MACHINE, stockage, lot_de(18)
        )
        stockage.inventaire.changer_boite(BOITES.capsules, 0)
        stockage.inventaire.changer_boite(BOITES.couvercles_perces, 10)
        assert "10 couvercles percés" in refus_taille_lot(MACHINE, stockage, lot_de(18))
        # Le bouton refuse avec la même raison.
        stockage.inventaire.changer_boite(BOITES.couvercles_perces, 18)
        lancement = Lancement(REGLAGES_LOT, MACHINE, machine.mode_seaux(), None, stockage)
        with pytest.raises(ErreurChef, match="19 seaux .* 18 bocaux de semence"):
            lancement.proposer_seaux(FORMAT, 19, VARIETE, "page web")
    finally:
        machine.fermer()


def test_lot_simule_trop_grand_refuse(liste):
    cycle = REGLAGES.simulateur.cycle.model_copy(update={"seaux": 19})
    reglages = REGLAGES.model_copy(
        update={"simulateur": REGLAGES.simulateur.model_copy(update={"cycle": cycle})}
    )
    with Simulateur(reglages, liste, "cycle") as simulateur:
        with pytest.raises(ErreurChef, match="19 seaux .* 18 bocaux de semence"):
            jouer_cycle(simulateur)


def test_le_lot_du_simulateur_respecte_la_regle():
    cycle = REGLAGES.simulateur.cycle
    assert cycle.seaux <= min(cycle.bocal_neuf.bocaux, places.capacite_boite(MACHINE))
    assert cycle.seaux <= cycle.bocal_neuf.couvercles_perces


# ---------------------------------------------------------------- le bouton, puis le Go


def test_bouton_refuse_si_un_poste_n_est_pas_pret(liste):
    machine = Machine(liste, sources=Sources(), codeur=False)
    try:
        remplir_le_stockage(machine.stockage)
        lancement = Lancement(REGLAGES_LOT, MACHINE, machine.mode_seaux(), None, machine.stockage)
        with pytest.raises(ErreurChef, match="pas lancé"):
            lancement.proposer_seaux(FORMAT, 2, VARIETE, "page web")
        assert lancement.proposition is None
    finally:
        machine.fermer()


def test_bouton_refuse_si_le_mode_ne_va_pas_ou_le_format_est_inconnu(machine):
    lancement = Lancement(
        REGLAGES_LOT, MACHINE, machine.mode_seaux("lavage"), None, machine.stockage
    )
    with pytest.raises(ErreurChef, match="mode « production » n'est pas choisi"):
        lancement.proposer_seaux(FORMAT, 2, VARIETE, "page web")
    lancement = Lancement(REGLAGES_LOT, MACHINE, machine.mode_seaux(), None, machine.stockage)
    with pytest.raises(ErreurChef, match="format « seau_z » inconnu"):
        lancement.proposer_seaux("seau_z", 2, VARIETE, "page web")
    with pytest.raises(ErreurChef, match="au moins un seau"):
        lancement.proposer_seaux(FORMAT, 0, VARIETE, "page web")


@dataclass
class FauxFond:
    demarres: list
    arrets: int = 0
    actives: tuple = ()

    def demarrer(self, modules):
        self.demarres.append(list(modules))

    def arreter(self):
        self.arrets += 1


def test_go_lance_le_lot_propose_et_refuse_un_second_lot(machine):
    fond = FauxFond([])
    horloge = [0.0]
    lancement = Lancement(
        REGLAGES_LOT,
        MACHINE,
        machine.mode_seaux(),
        None,
        machine.stockage,
        fond,
        horloge=lambda: horloge[0],
    )
    with pytest.raises(ErreurChef, match="aucun lot proposé"):
        lancement.go("écran")
    propose = lancement.proposer_seaux(FORMAT, 3, VARIETE, "page web")
    assert propose.texte == "3 seaux seau_a (pleurote_grise)"
    # Rien ne part sans le Go.
    assert machine.chef.etat().modules == ()
    assert lancement.texte_ecran() == (
        "Lot de 3 seaux seau_a (pleurote_grise) : GO ?",
        "Toucher GO pour lancer le lot.",
    )
    assert lancement.go("écran") == ["remplissage", "mycelium"]
    assert fond.demarres == [["remplissage", "mycelium"]]
    statuts = {m.module: m.statut for m in machine.chef.etat().modules}
    assert statuts == {"remplissage": "en_cours", "mycelium": "en_cours"}
    assert lancement.proposition is None and lancement.dernier == propose.texte
    # Un lot tourne : le bouton refuse.
    with pytest.raises(ErreurChef, match="un lot est déjà en route"):
        lancement.proposer_seaux(FORMAT, 1, VARIETE, "page web")


def test_une_proposition_trop_vieille_est_oubliee(machine):
    horloge = [0.0]
    lancement = Lancement(
        REGLAGES_LOT,
        MACHINE,
        machine.mode_seaux(),
        None,
        machine.stockage,
        horloge=lambda: horloge[0],
    )
    lancement.proposer_seaux(FORMAT, 1, VARIETE, "page web")
    horloge[0] = REGLAGES_LOT.proposition_max_s + 1
    assert lancement.proposition is None
    with pytest.raises(ErreurChef, match="aucun lot proposé"):
        lancement.go("écran")


def test_lot_de_bocaux_compte_les_bocaux_vides(machine):
    bocaux = ModeBocaux(REGLAGES, machine.pieces, machine.chef, mode_actuel=lambda: "production")
    lancement = Lancement(REGLAGES_LOT, MACHINE, None, bocaux, machine.stockage)
    with pytest.raises(ErreurChef, match="2 bocaux demandés, 0 bocaux vides"):
        lancement.proposer_bocaux(2, "page web")
    quinconce = list(places.places_bocaux(MACHINE))
    for place in quinconce[:2]:
        machine.stockage.poser_bocal(place)
    propose = lancement.proposer_bocaux(2, "page web")
    assert propose.lot == LotBocaux(tuple(quinconce[:2]))


# ---------------------------------------------------------------- les boucles de fond


class FauxChef:
    """Le chef vu par le suivi des boucles : les statuts des modules du lot."""

    def __init__(self):
        self.modules = {}

    def etat(self):
        return EtatChef(
            False,
            tuple(
                EtatModule(nom, statut, "e", 1, 1, "go", attend, (), None)
                for nom, (statut, attend) in self.modules.items()
            ),
        )


def test_boucles_de_fond_lancees_avec_le_lot_puis_arretees(machine):
    chef = FauxChef()
    fond = FondDuLot(machine.cartes, REGLAGES_LOT, chef)
    tete = machine.cartes.tete
    assert tete.vide.zero is None
    fond.demarrer(["remplissage", "mycelium"], suivi=False)
    assert set(fond.actives) == {"chariot", "agitateur", "tete_micropore", "bras_fermeture", "tete"}
    # Au départ, le zéro du vide est recalé (vanne coupée).
    assert tete.vide.zero is not None
    zero = tete.vide.zero
    chef.modules = {"remplissage": ("en_cours", ""), "mycelium": ("en_cours", "")}
    fond.suivre()
    assert len(fond.actives) == 5
    # Alarme : tout s'arrête, mais le lot reste suivi.
    chef.modules["remplissage"] = ("alarme", "")
    chef.modules["mycelium"] = ("alarme", "")
    fond.suivre()
    assert fond.actives == []
    # Acquittée, le lot repart : les boucles aussi, la tête sans toucher sa vanne ni son zéro.
    tete.vide.zero = zero + 0.5
    chef.modules["remplissage"] = ("en_cours", ATTENTE_GO)
    fond.suivre()
    assert set(fond.actives) == {"chariot", "agitateur", "tete_micropore", "bras_fermeture", "tete"}
    assert tete.vide.zero == zero + 0.5
    # Lot fini : plus aucune boucle, plus de suivi.
    chef.modules = {"remplissage": ("fini", ""), "mycelium": ("fini", "")}
    fond.suivre()
    assert fond.actives == [] and not fond.en_route
    fond.arreter()


def test_lot_repris_du_carnet_la_tete_attend_le_go(machine):
    chef = FauxChef()
    fond = FondDuLot(machine.cartes, REGLAGES_LOT, chef)
    fond.reprendre(["remplissage", "mycelium"], suivi=False)
    assert fond.actives == []
    # Après la coupure, les modules repris attendent le Go de Karulium.
    chef.modules = {
        "remplissage": ("en_cours", ATTENTE_GO),
        "mycelium": ("en_cours", ATTENTE_GO),
    }
    fond.suivre()
    # Rien n'est commandé avant le Go : pas de tête (sa vanne n'est pas touchée).
    assert "tete" not in fond.actives and "chariot" in fond.actives
    assert machine.cartes.tete.vide.zero is None
    chef.modules["remplissage"] = ("en_cours", "")
    fond.suivre()
    assert "tete" in fond.actives
    fond.arreter()
    assert fond.actives == []


def test_go_avec_les_vraies_boucles_puis_abandon(machine):
    fond = FondDuLot(machine.cartes, REGLAGES_LOT, machine.chef)
    lancement = Lancement(REGLAGES_LOT, MACHINE, machine.mode_seaux(), None, machine.stockage, fond)
    lancement.proposer_seaux(FORMAT, 1, VARIETE, "page web")
    lancement.go("écran")
    try:
        assert fond.en_route and "chariot" in fond.actives
        machine.chef.abandonner("remplissage")
        machine.chef.abandonner("mycelium")
        fond.suivre()
        assert fond.actives == [] and not fond.en_route
    finally:
        fond.arreter()


# ---------------------------------------------------------------- l'écran et la page web


class FauxLancement:
    def __init__(self, refus=None):
        self.refus = refus
        self.gos = []
        self.propositions = []

    @property
    def proposition(self):
        return None if self.gos else type("P", (), {"texte": "3 seaux seau_a (pleurote_grise)"})

    def refus_go(self):
        return self.refus

    def texte_ecran(self):
        if self.proposition is None:
            return None
        if self.refus:
            return "Lot de 3 seaux seau_a (pleurote_grise) : impossible", self.refus
        return "Lot de 3 seaux seau_a (pleurote_grise) : GO ?", "Toucher GO pour lancer le lot."

    def go(self, qui):
        self.gos.append(qui)
        return ["remplissage", "mycelium"]

    def proposer_seaux(self, format, nombre, variete, qui):
        if self.refus:
            raise ErreurChef(self.refus)
        self.propositions.append((format, nombre, variete))

    def proposer_bocaux(self, nombre, qui):
        raise ErreurChef("lot de bocaux refusé : « versement » pas lancé")

    def annuler(self, qui):
        pass

    def en_dict(self):
        return {"propositions": len(self.propositions)}


def test_ecran_go_lance_le_lot_propose(tmp_path):
    banc = BancEcran(tmp_path)
    try:
        banc.chef.abandonner("essai")
        banc.ecran.lancement = lancement = FauxLancement()
        banc.tour()
        assert banc.texte("b_bandeau") == "ATTEND LE GO"
        assert banc.texte("t_module") == "Lot de 3 seaux seau_a (pleurote_grise) : GO ?"
        banc.appuyer("b_go")
        assert banc.ecran.page == "confirmer"
        assert lancement.gos == []
        banc.appuyer("b_oui")
        assert lancement.gos == ["écran de l'armoire"]
    finally:
        banc.registre.fermer()


def test_ecran_dit_pourquoi_le_lot_ne_part_pas(tmp_path):
    banc = BancEcran(tmp_path)
    try:
        banc.chef.abandonner("essai")
        refus = "lot de seaux refusé : « mycelium » pas lancé : codeur"
        banc.ecran.lancement = lancement = FauxLancement(refus)
        banc.tour()
        assert banc.texte("t_info") == refus
        banc.appuyer("b_go")
        assert banc.ecran.page == "etat" and lancement.gos == []
        assert banc.texte("t_info") == f"Lot impossible : {refus}."
    finally:
        banc.registre.fermer()


def test_page_web_propose_le_lot_et_dit_le_refus(tmp_path):
    from vidange.fiabilite import Bilans
    from vidange.registre import Registre
    from vidange.reglages import ReglagesBilan

    from .test_chef import Horloge, nouveau_chef

    chef = nouveau_chef(Horloge())
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    try:
        bilans = Bilans(tmp_path, ReglagesBilan(lignes_journal=0), registre, chef)
        lancement = FauxLancement()
        services = Services(chef, registre, bilans.acquitter, list, lancement=lancement)
        client = TestClient(
            creer_app(services, reglages_api(), CLE),
            client=LOCAL,
            headers={"Authorization": f"Bearer {CLE}"},
        )
        reponse = client.post(
            "/api/lot/seaux", json={"format": FORMAT, "nombre": 3, "variete": VARIETE}
        )
        assert reponse.status_code == 200
        assert lancement.propositions == [(FORMAT, 3, VARIETE)]
        assert client.get("/api/etat").json()["lot"] == {"propositions": 1}
        reponse = client.post("/api/lot/bocaux", json={"nombre": 2})
        assert reponse.status_code == 409
        assert "versement" in reponse.json()["detail"]
        # Pas de Go de lot par la page web : il se donne à l'écran.
        assert client.post("/api/lot/go").status_code in (404, 405)
        assert "Lancer un lot" in client.get("/").text
    finally:
        registre.fermer()
