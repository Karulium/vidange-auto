"""Tests des cartes du chariot et de la tête construites par le programme principal (tâche 45 ter).

Le faux matériel est branché par le même chemin que le vrai : Materiel et sa fabrique (fausse
ici), les liaisons FluidNC (faux FluidNC ici), le tour des pesées, construire_cartes (celle du
démarrage).
"""

import threading

import pytest

from vidange.chef import Chef
from vidange.cycle import ModeBocaux, ModeSeaux
from vidange.cycle.machine import (
    BOCAUX_SALES,
    CARTES_PAS_CONSTRUITES,
    NOMS_DES_PIECES,
    PHOTO_DU_PLAFOND,
    QR_DU_BOCAL,
    PiecesMachine,
    construire_cartes,
    presence_fluidnc,
)
from vidange.demarrage import principal
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fermeture.bras import BrasFermeture
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.journal import NOM_FICHIER
from vidange.lavage.lavage import Lavage
from vidange.materiel import FausseFabrique, Materiel
from vidange.micropore.avance import AvanceFluidnc
from vidange.micropore.tete import TeteMicropore
from vidange.mycelium.agitateur import AgitateurFluidnc
from vidange.pesees.tour import TourPesees
from vidange.porte_bocal.porte_bocal import PorteBocalFluidnc
from vidange.poste_fut import PosteFut
from vidange.prehension.prehension import Prehension
from vidange.prehension.tete import TeteFluidnc
from vidange.reglages import charger_reglages
from vidange.remplissage.chariot import ChariotFluidnc

from .conftest import DOSSIER_PI
from .test_chef_exemple import attendre
from .test_demarrage import options, raccords_faux

# Les postes qui ont besoin des cartes du chariot ou de la tête.
POSTES_DU_CHARIOT = ("seau_vide", "qr_du_flanc", "micropore", "couvercle", "fermeture", "spray")


@pytest.fixture(scope="module")
def reglages_depot():
    return charger_reglages(DOSSIER_PI / "reglages")


@pytest.fixture(scope="module")
def liste():
    return charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")


def brancher_boitier(fabrique, reglages):
    i2c = reglages.pesees.i2c
    plages = [(voie.angle_min_deg, voie.angle_max_deg) for voie in i2c.pca9685.voies.values()]
    return fabrique.carte_pesee(i2c.carte).brancher_boitier(plages)


class Banc:
    """Le faux matériel de la machine, et les cartes construites dessus comme au démarrage."""

    def __init__(self, reglages, liste, boitier=True, ports=None, lister=list):
        self.reglages = reglages
        self.fabrique = FausseFabrique(liste)
        if boitier:
            self.boitier = brancher_boitier(self.fabrique, reglages)
        self.materiel = Materiel(liste, self.fabrique)
        self.fluidnc = {nom: FauxFluidnc() for nom in reglages.fluidnc.cartes}
        self.ports = (
            {nom: carte.ouvrir for nom, carte in self.fluidnc.items()} if ports is None else ports
        )
        self.lister = lister
        # Les liaisons ne sont pas démarrées : construire les cartes ne parle à aucune.
        self.liaisons = {
            nom: Liaison(nom, reglages.fluidnc, ouvrir=self.ports.get(nom))
            for nom in reglages.fluidnc.cartes
        }
        self.pesees = TourPesees(reglages.pesees, self.materiel)
        self.poste = PosteFut(reglages.machine.poste_fut, self.materiel, lecture_directe=True)

    def cartes(self, vraie_machine=False, materiel=True, pesees=True):
        return construire_cartes(
            self.reglages,
            self.materiel if materiel else None,
            self.liaisons,
            self.pesees if pesees else None,
            self.poste,
            vraie_machine,
            presence_fluidnc(self.reglages.fluidnc, self.ports, lister=self.lister),
            mode=lambda: "production",
        )

    def pieces(self, cartes, vraie_machine=False):
        return PiecesMachine(
            self.poste,
            self.materiel,
            vraie_machine=vraie_machine,
            spray=object(),  # le poste ne demande que sa présence
            vision=self.reglages.vision,
            regard=object(),
            cartes=cartes,
        )

    def fermer(self):
        self.materiel.fermer()


@pytest.fixture
def banc(reglages_depot, liste):
    banc = Banc(reglages_depot, liste)
    yield banc
    banc.fermer()


# ---------------------------------------------------------------- tout est là


def test_tout_present_les_cartes_sont_construites_et_les_postes_prets(banc, reglages_depot):
    cartes = banc.cartes()
    assert cartes.absentes == {}
    assert isinstance(cartes.chariot, ChariotFluidnc)
    assert isinstance(cartes.tete_micropore, TeteMicropore)
    assert isinstance(cartes.bras_fermeture, BrasFermeture)
    assert isinstance(cartes.avance_micropore, AvanceFluidnc)
    assert isinstance(cartes.agitateur, AgitateurFluidnc)
    assert isinstance(cartes.porte_bocal, PorteBocalFluidnc)
    assert isinstance(cartes.tete, TeteFluidnc)
    assert isinstance(cartes.prehension, Prehension)
    # La Préhension voit le porte-bocal du Mycélium (zone du porte-bocal, mors).
    assert cartes.prehension.porte_bocal is cartes.porte_bocal
    assert isinstance(cartes.lavage, Lavage)
    # Les cartes sont celles des liaisons du programme (une seule liaison par carte).
    assert cartes.chariot.liaison is banc.liaisons["chariot"]
    assert cartes.tete.liaison_tete is banc.liaisons["prehension"]
    assert cartes.prehension.tete is cartes.tete
    assert cartes.lavage.prehension is cartes.prehension
    pieces = banc.pieces(cartes)
    for poste in POSTES_DU_CHARIOT:
        assert pieces.manque(poste) is None, poste
    # Le Mycélium a ses pièces ; il lui manque le QR du bocal (l'alarme du pilote de la
    # rotation est lue depuis la tâche 24).
    assert pieces.manque("mycelium") == QR_DU_BOCAL
    # Il ne reste que ce qui n'est pas écrit (photo du plafond).
    assert pieces.manque("entonnoir") == PHOTO_DU_PLAFOND
    assert pieces.manque("lavage_bocaux") == BOCAUX_SALES
    assert all(constat.niveau == "ok" for constat in cartes.constats())
    assert len(cartes.constats()) == len(NOMS_DES_PIECES)


def test_rien_n_est_commande_en_construisant_les_cartes(banc):
    banc.cartes()
    # Aucun ordre aux servos (sortie coupée), aucune ligne envoyée aux cartes FluidNC.
    assert banc.boitier.ordres == 0
    assert banc.boitier.aucun_ordre
    assert all(not liaison.etat.connectee for liaison in banc.liaisons.values())


def test_tout_present_le_mode_seaux_ne_dit_plus_les_cartes(banc, reglages_depot):
    chef = Chef(reglages_depot.machine, reglages_depot.programme.chef)
    pieces = banc.pieces(banc.cartes())
    seaux = ModeSeaux(reglages_depot, pieces, chef)
    # Seul ce qui n'est pas écrit empêche le lot : le bocal neuf du mycélium (cœur), la griffe.
    assert seaux.etats["seau_vide"].raison == "attend « mycelium » (pas prêt)"
    for poste in ("micropore", "couvercle", "fermeture", "spray"):
        assert seaux.etats[poste].raison == "pas de lot possible", poste
    textes = " ".join(etat.raison for etat in seaux.etats.values())
    assert "cartes du chariot" not in textes and "boîtier" not in textes
    bocaux = ModeBocaux(reglages_depot, pieces, chef)
    assert bocaux.etats["entonnoir"].raison == PHOTO_DU_PLAFOND
    assert bocaux.etats["lavage_bocaux"].raison == BOCAUX_SALES


# ---------------------------------------------------------------- une pièce absente


def test_port_fluidnc_introuvable_le_poste_dit_laquelle(reglages_depot, liste):
    ports = {nom: FauxFluidnc().ouvrir for nom in reglages_depot.fluidnc.cartes if nom != "chariot"}
    banc = Banc(reglages_depot, liste, ports=ports)
    try:
        cartes = banc.cartes()
    finally:
        banc.fermer()
    raison = cartes.absentes["chariot"]
    assert raison.startswith("carte FluidNC « chariot » : aucun port USB ne porte le numéro")
    assert set(cartes.absentes) == {"chariot"}
    pieces = banc.pieces(cartes)
    for poste in ("seau_vide", "qr_du_flanc", "micropore", "couvercle", "fermeture"):
        assert pieces.manque(poste) == raison, poste
    assert pieces.manque("spray") is None
    constat = next(c for c in cartes.constats() if "chariot (carte FluidNC" in c.sujet)
    assert constat.niveau == "attention" and constat.texte == raison
    assert "relancer le programme" in constat.quoi_faire


def test_sans_la_carte_du_mycelium_le_poste_mycelium_dit_laquelle(reglages_depot, liste):
    ports = {
        nom: FauxFluidnc().ouvrir
        for nom in reglages_depot.fluidnc.cartes
        if nom != "mycelium_lavage"
    }
    banc = Banc(reglages_depot, liste, ports=ports)
    try:
        cartes = banc.cartes()
    finally:
        banc.fermer()
    raison = cartes.absentes["agitateur"]
    assert "mycelium_lavage" in raison
    assert cartes.absentes["porte_bocal"] == raison
    # La tête est construite, sans porte-bocal : la zone du porte-bocal lui reste interdite.
    assert "tete" not in cartes.absentes and cartes.prehension.porte_bocal is None
    assert banc.pieces(cartes).manque("mycelium") == raison


def test_numero_de_serie_trouve_par_le_vrai_chemin(reglages_depot, liste):
    """Une carte sans port d'essai est cherchée par son numéro de série USB (comme sur le Pi)."""

    class PortVu:
        device = "/dev/ttyACM7"
        description = "FluidNC"
        serial_number = reglages_depot.fluidnc.cartes["chariot"].numero_serie_usb

    ports = {nom: FauxFluidnc().ouvrir for nom in reglages_depot.fluidnc.cartes if nom != "chariot"}
    banc = Banc(reglages_depot, liste, ports=ports, lister=lambda: [PortVu()])
    try:
        assert "chariot" not in banc.cartes().absentes
    finally:
        banc.fermer()


def test_bus_des_pesees_debranche_le_spray_reste(banc):
    banc.fabrique.rs485["rs485_pesee"].cable_coupe = True
    cartes = banc.cartes()
    for piece in ("chariot", "boitier", "tete_micropore", "bras_fermeture", "tete", "lavage"):
        assert "carte de pesée" in cartes.absentes[piece], piece
    assert cartes.chariot is None and cartes.tete is None and cartes.prehension is None
    # Le spray a son bus à lui (rs485_spray) : une panne des pesées ne le coupe pas.
    assert "spray" not in cartes.absentes
    assert "avance_micropore" not in cartes.absentes
    pieces = banc.pieces(cartes)
    assert pieces.manque("entonnoir").startswith("carte de pesée « pesee_prehension »")


def test_boitier_du_chariot_absent_ou_muet(reglages_depot, liste):
    banc = Banc(reglages_depot, liste, boitier=False)
    try:
        cartes = banc.cartes()
    finally:
        banc.fermer()
    assert cartes.absentes["boitier"].startswith("boîtier du chariot (carte « pesee_plateau")
    assert cartes.absentes["tete_micropore"] == cartes.absentes["boitier"]
    assert "chariot" not in cartes.absentes  # la pesée du plateau répond, elle
    pieces = banc.pieces(cartes)
    assert pieces.manque("micropore") == cartes.absentes["boitier"]
    assert pieces.manque("fermeture") == cartes.absentes["boitier"]
    assert pieces.manque("seau_vide") is None


@pytest.mark.parametrize(
    ("panne", "texte"), [("pca9685_muette", "PCA9685 muette"), ("tof_muet", "ToF muet")]
)
def test_boitier_qui_dit_une_puce_muette(banc, panne, texte):
    setattr(banc.boitier, panne, True)
    assert banc.cartes().absentes["boitier"].endswith(texte)


def test_carte_du_spray_muette(banc):
    banc.fabrique.debrancher("carte_spray")
    cartes = banc.cartes()
    assert cartes.absentes["spray"].startswith("carte du spray « carte_spray » : ")
    assert banc.pieces(cartes).manque("spray") == cartes.absentes["spray"]
    assert set(cartes.absentes) == {"spray"}


def test_capteur_de_vide_muet_pas_de_tete(banc):
    banc.fabrique.debrancher("vide_venturi")
    cartes = banc.cartes()
    assert cartes.absentes["tete"].startswith("capteur de vide « vide_venturi » : ")
    # Le Lavage est porté par la tête : il dit la même raison.
    assert cartes.absentes["lavage"] == cartes.absentes["tete"]


def test_sans_bus_des_pesees_ni_entrees_sorties(banc):
    cartes = banc.cartes(pesees=False)
    assert cartes.absentes["chariot"].startswith("pesée « pesee_plateau_remplissage » pas")
    cartes = banc.cartes(materiel=False)
    assert set(cartes.absentes.values()) == {CARTES_PAS_CONSTRUITES}
    assert banc.pieces(None).manque("micropore") == CARTES_PAS_CONSTRUITES


def test_reglage_faux_jamais_de_plantage(banc, reglages_depot):
    """Un réglage qui ne va pas (signal du chariot absent de fluidnc.yaml) : la pièce n'est pas
    construite, avec la raison ; le démarrage continue."""
    carte = reglages_depot.fluidnc.cartes["chariot"]
    entrees = {
        nom: lettre for nom, lettre in carte.entrees.items() if nom != "barriere_remplissage"
    }
    cartes_fluidnc = {
        **reglages_depot.fluidnc.cartes,
        "chariot": carte.model_copy(update={"entrees": entrees}),
    }
    banc.reglages = reglages_depot.model_copy(
        update={"fluidnc": reglages_depot.fluidnc.model_copy(update={"cartes": cartes_fluidnc})}
    )
    cartes = banc.cartes()
    assert cartes.absentes["chariot"].startswith("pas construite : ")
    assert "barriere_remplissage" in cartes.absentes["chariot"]
    assert "tete" not in cartes.absentes


def test_sur_la_vraie_machine_les_lignes_d_exemple_sont_interdites(banc):
    cartes = banc.cartes(vraie_machine=True)
    assert set(cartes.absentes) == set(NOMS_DES_PIECES)
    assert cartes.absentes["chariot"] == (
        "ligne « pesee_plateau_remplissage » de docs/entrees-sorties.yaml en EXEMPLE "
        "(exemple: true) : interdit sur la vraie machine"
    )
    assert "en EXEMPLE" in cartes.absentes["spray"]
    assert "avance_micropore" in cartes.absentes["avance_micropore"]


def test_sur_la_vraie_machine_les_reglages_d_exemple_sont_interdits(reglages_depot, liste):
    """Lignes de la liste vraies : restent les numéros de série et pesees.yaml d'EXEMPLE."""
    vraie = liste.model_copy(
        update={
            "cartes": {n: c.model_copy(update={"exemple": False}) for n, c in liste.cartes.items()},
            "signaux": {
                n: s.model_copy(update={"exemple": False}) for n, s in liste.signaux.items()
            },
        }
    )
    banc = Banc(reglages_depot, vraie)
    try:
        cartes = banc.cartes(vraie_machine=True)
        assert cartes.absentes["chariot"] == (
            "fluidnc.yaml : numéros de série d'EXEMPLE (carte « chariot ») : interdit sur la vraie "
            "machine"
        )
        assert cartes.absentes["boitier"].startswith("pesees.yaml en EXEMPLE")
        assert cartes.absentes["spray"].endswith("programme fait avec des réglages d'EXEMPLE")
        sans_exemple = reglages_depot.model_copy(
            update={
                "fluidnc": reglages_depot.fluidnc.model_copy(update={"exemple": False}),
                "pesees": reglages_depot.pesees.model_copy(update={"exemple": False}),
            }
        )
        banc.reglages = sans_exemple
        cartes = banc.cartes(vraie_machine=True)
        assert set(cartes.absentes) == {"spray"}
        # Le programme d'une carte de pesée fait avec des réglages d'EXEMPLE : interdit aussi.
        banc.fabrique.carte_pesee("pesee_plateau_remplissage").exemple = True
        cartes = banc.cartes(vraie_machine=True)
        assert cartes.absentes["chariot"].endswith("programme fait avec des réglages d'EXEMPLE")
        banc.fabrique.carte_pesee("pesee_plateau_remplissage").exemple = False
        banc.fabrique.carte_spray().exemple = False
        cartes = banc.cartes(vraie_machine=True)
        assert cartes.absentes == {}
    finally:
        banc.fermer()


# ---------------------------------------------------------------- au démarrage


def demarrer(reglages, entrees_sorties, tmp_path, raccords, messages):
    arguments = [*options(reglages, tmp_path), "--entrees-sorties", str(entrees_sorties)]
    arret = threading.Event()
    fil = threading.Thread(target=lambda: principal(arguments, arret, raccords))
    fil.start()
    try:
        attendre(lambda: "READY=1" in messages)
    finally:
        arret.set()
        fil.join(10)
    return (tmp_path / "donnees" / "journal" / NOM_FICHIER).read_text(encoding="utf-8")


def test_au_demarrage_tout_branche_plus_de_carte_qui_manque(reglages, entrees_sorties, tmp_path):
    raccords, messages, _ = raccords_faux(entrees_sorties)
    brancher_boitier(raccords.fabrique, charger_reglages(reglages))
    journal = demarrer(reglages, entrees_sorties, tmp_path, raccords, messages)
    assert "Pièce « " not in journal
    assert "[attention] cartes du chariot et de la tête" not in journal
    for poste in ("micropore", "couvercle", "fermeture", "spray"):
        assert f"Mode seaux, {poste} : pas lancé : pas de lot possible" in journal, poste
    assert f"Mode bocaux, entonnoir : pas lancé : {PHOTO_DU_PLAFOND}" in journal


def test_au_demarrage_une_carte_absente_est_dite_sans_plantage(reglages, entrees_sorties, tmp_path):
    raccords, messages, _ = raccords_faux(entrees_sorties)
    brancher_boitier(raccords.fabrique, charger_reglages(reglages))
    # La carte FluidNC de la tête n'est pas branchée : cherchée par son numéro de série, pas vue.
    raccords.ports = {nom: port for nom, port in raccords.ports.items() if nom != "prehension"}
    journal = demarrer(reglages, entrees_sorties, tmp_path, raccords, messages)
    assert "Pièce « tete » absente : carte FluidNC « prehension » : aucun port USB" in journal
    assert (
        "[attention] cartes du chariot et de la tête, tête de la Préhension : carte FluidNC "
        "« prehension »" in journal
    )
    assert "Mode bocaux, entonnoir : pas lancé : carte FluidNC « prehension »" in journal
    assert "Mode seaux, micropore : pas lancé : pas de lot possible" in journal
