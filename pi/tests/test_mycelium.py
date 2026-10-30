"""Mycélium : réglages, verrous, gestes au simulateur, agitateur sur le faux FluidNC, registre."""

import threading
import time
from zoneinfo import ZoneInfo

import pytest

from vidange.chef import ErreurEtape
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.envois.cycle import donnees_cycle
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.griffe.bras import G
from vidange.griffe.simulation import FausseForce
from vidange.mycelium import (
    AgitateurFluidnc,
    EtatChariot,
    Pas,
    PoseAgitateur,
    ReglesMycelium,
    module_mycelium,
)
from vidange.mycelium.agitateur import QUOI_FAIRE_SAUT
from vidange.mycelium.regles import ecart_angle
from vidange.mycelium.simulation import mycelium_du_simulateur
from vidange.registre import Registre
from vidange.reglages import Machine, charger_reglages
from vidange.simulateur import Simulateur
from vidange.simulateur.outil import main as simulateur

from .conftest import DOSSIER_PI
from .test_fluidnc_liaison import DELAI, reglages_essai
from .test_reglages import erreur_de, remplacer

LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
MYCELIUM = MACHINE.mycelium
assert MYCELIUM is not None and MACHINE.griffe is not None
REGLES = ReglesMycelium(MACHINE)
FORMATS = MACHINE.griffe.formats
GARAGE = PoseAgitateur(x=0.565, angle=0.0)
DOSAGE_BAS = PoseAgitateur(x=0.925, angle=180.0)
ECARTE = EtatChariot(y=0.375, plateau_z=0.53)
AU_DOSAGE = EtatChariot(y=0.155, plateau_z=0.53)


# ---------------------------------------------------------------- réglages


def test_reglages_du_mycelium_du_depot():
    assert MYCELIUM.exemple
    assert (MYCELIUM.garage_x, MYCELIUM.demi_tour_x, MYCELIUM.dosage_x) == (0.565, 0.865, 0.925)
    assert MACHINE.axes["manivelle"].unite == "deg"
    assert FORMATS["seau_b"].seaux_par_bocal == 2 and FORMATS["seau_a"].seaux_par_bocal == 1
    # Plateau pendant le dosage : min(0,78 − h ; 0,575).
    assert REGLES.plateau_dosage(FORMATS["seau_a"]) == pytest.approx(0.53)
    assert REGLES.plateau_dosage(FORMATS["seau_b"]) == pytest.approx(0.575)


def test_course_de_l_agitation_verifiee(reglages):
    remplacer(reglages / "machine.yaml", "course_agitation_m: 0.07", "course_agitation_m: 0.08")
    message = erreur_de(reglages)
    assert (
        "course_agitation_m : 0.08 n'est pas un trou de la manivelle (0.04, 0.07, 0.1)" in message
    )


def test_reglages_du_mycelium_verifies(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "      hauteur: 0.25\n", "      hauteur: 0.20\n")
    remplacer(machine, "course: [-72000, 72000]", "course: [-3600, 3600]")
    remplacer(machine, "  mycelium_agitation_max: 300", "  mycelium_agitation_max: 60")
    message = erreur_de(reglages)
    assert "formats → seau_a : au dosage, plateau à 0.575 m et bord du seau à 0.775 m" in message
    assert "manivelle : une agitation peut faire 198 tours" in message
    assert "durees → mycelium_agitation_max doit dépasser" in message


def test_glissiere_verifiee(reglages):
    remplacer(reglages / "machine.yaml", "  dosage_x: 0.925", "  dosage_x: 0.95")
    assert "mycelium → dosage_x : x 0.95 hors de la course de agitateur_x" in erreur_de(reglages)


def test_seaux_du_simulateur_verifies(reglages):
    remplacer(reglages / "simulateur.yaml", "format: seau_a, variete", "format: seau_z, variete")
    assert "mycelium → seaux : format « seau_z » absent de machine.yaml" in erreur_de(reglages)


# ---------------------------------------------------------------- verrous


def test_agitateur_ne_roule_que_chariot_ecarte():
    assert REGLES.refus_glissiere(GARAGE, 0.865, ECARTE) is None
    refus = REGLES.refus_glissiere(GARAGE, 0.865, EtatChariot(y=0.30, plateau_z=0.53))
    assert "chariot de remplissage est à y ≥ 0,375 m (il est à y 0,3 m)" in refus
    assert "inconnu" in REGLES.refus_glissiere(GARAGE, 0.865, None)
    # Toujours manivelle en haut ; jamais hors de la course.
    assert "manivelle en haut" in REGLES.refus_glissiere(GARAGE.avec(angle=180), 0.865, ECARTE)
    assert "hors de sa course" in REGLES.refus_glissiere(GARAGE, 0.95, ECARTE)


def test_chariot_ne_roule_que_si_l_agitateur_le_permet():
    assert REGLES.refus_chariot(GARAGE, en_mouvement=False) is None
    assert REGLES.refus_chariot(DOSAGE_BAS, en_mouvement=False) is None
    assert "bouge" in REGLES.refus_chariot(GARAGE, en_mouvement=True)
    # Au dosage manivelle en haut, au demi-tour, au garage manivelle en bas : refusé.
    for pose in (
        DOSAGE_BAS.avec(angle=0),
        PoseAgitateur(x=0.865, angle=0),
        GARAGE.avec(angle=180),
        DOSAGE_BAS.avec(angle=90),
    ):
        assert "le chariot de remplissage ne roule qu'" in REGLES.refus_chariot(pose, False)
    assert "inconnue" in REGLES.refus_chariot(None, False)


def test_manivelle_au_garage_pas_avec_10_cm(reglages):
    assert REGLES.refus_manivelle(GARAGE, ECARTE) is None
    remplacer(reglages / "machine.yaml", "course_agitation_m: 0.07", "course_agitation_m: 0.10")
    regles = ReglesMycelium(charger_reglages(reglages).machine)
    assert "course de 10 cm" in regles.refus_manivelle(GARAGE, ECARTE)
    # Ailleurs, la course de 10 cm est permise.
    assert regles.refus_manivelle(DOSAGE_BAS, AU_DOSAGE) is None


def test_manivelle_au_dosage_jamais_chariot_en_route():
    assert REGLES.refus_manivelle(DOSAGE_BAS, ECARTE) is None
    assert REGLES.refus_manivelle(DOSAGE_BAS, AU_DOSAGE) is None
    en_route = EtatChariot(y=0.25, plateau_z=0.53, immobile=False)
    assert "pendant que le chariot" in REGLES.refus_manivelle(DOSAGE_BAS, en_route)
    assert "qu'au garage, au demi-tour ou au dosage" in REGLES.refus_manivelle(
        PoseAgitateur(x=0.7, angle=0), ECARTE
    )


def test_camera_ne_pivote_qu_agitateur_gare():
    assert REGLES.camera_peut_pivoter(GARAGE)
    assert REGLES.camera_peut_pivoter(GARAGE.avec(x=0.62))
    assert not REGLES.camera_peut_pivoter(GARAGE.avec(x=0.63))
    assert not REGLES.camera_peut_pivoter(None)


def test_angles_de_la_manivelle():
    assert REGLES.angle_proche(10, bas=False) == pytest.approx(0)
    assert REGLES.angle_proche(10, bas=True) == pytest.approx(180)
    assert REGLES.angle_proche(-200, bas=True) == pytest.approx(-180)
    assert REGLES.angle_proche(700, bas=False) == pytest.approx(720)
    # Prochain « en bas » dans le sens de rotation, ou celui-ci si elle y est.
    assert REGLES.bas_suivant(180, 1) == pytest.approx(180)
    assert REGLES.bas_suivant(180.5, -1) == pytest.approx(180)
    assert REGLES.bas_suivant(200, 1) == pytest.approx(540)
    assert REGLES.bas_suivant(200, -1) == pytest.approx(180)
    assert REGLES.bas_suivant(-1000, 1) == pytest.approx(-900)


def test_plateau_verifie():
    assert REGLES.refus_plateau(FORMATS["seau_a"], AU_DOSAGE) is None
    refus = REGLES.refus_plateau(FORMATS["seau_b"], AU_DOSAGE)
    assert "plateau du chariot de remplissage à z 0,53 m, il faut 0,575 m" in refus


# ---------------------------------------------------------------- au simulateur


def jouer(tmp_path=None, reglages=REGLAGES):
    registre = None
    if tmp_path is not None:
        registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    cycle = None if registre is None else registre.commencer_cycle("vidange")
    with Simulateur(reglages, LISTE, "dosage_mycelium") as simu:
        mycelium = mycelium_du_simulateur(simu, cycle=cycle, registre=registre)
        planning = simu.jouer([module_mycelium(mycelium)])
    return planning, mycelium, registre


def test_simulateur_un_seau_a_puis_deux_petits_seaux_avec_un_bocal():
    planning, mycelium, _ = jouer()
    assert planning.fini, planning.probleme
    doses = mycelium.doses
    # Seau A : 4 couches, un bocal ; 2 petits seaux B : 2 couches chacun, un seul bocal.
    assert [(d.seau, d.couche, d.bocal) for d in doses] == [
        ("S0001", 1, "B0001"),
        ("S0001", 2, "B0001"),
        ("S0001", 3, "B0001"),
        ("S0001", 4, "B0001"),
        ("S0002", 1, "B0002"),
        ("S0002", 2, "B0002"),
        ("S0003", 1, "B0002"),
        ("S0003", 2, "B0002"),
    ]
    for dose in doses:
        voulu = FORMATS["seau_a" if dose.seau == "S0001" else "seau_b"].mycelium_kg
        assert dose.kg == pytest.approx(voulu, abs=0.03)
    etapes = [ligne.etape for ligne in planning.lignes]
    assert etapes.count("agiter") == 8 and etapes.count("changer_de_bocal") == 2
    # Bocal retourné tête en bas puis remis debout à chaque couche (8 fois).
    gestes = mycelium.materiel_porte_bocal.gestes
    assert gestes == ["tete_en_bas", "debout"] * 8
    # La manivelle ne s'arrête jamais entre le haut et le bas, et reste près de 0.
    angle = mycelium.agitateur.position().angle
    assert REGLES.en_haut(mycelium.agitateur.position()) and abs(angle) <= 360 * 200


def test_casse_du_bloc_seulement_au_premier_seau_du_bocal():
    with Simulateur(REGLAGES, LISTE, "dosage_mycelium") as simu:
        mycelium = mycelium_du_simulateur(simu)
        pas: list[str] = []
        executer = mycelium.agitateur.executer

        def noter(un_pas, cible):
            if un_pas.texte == "casse du bloc":
                pas.append(f"{mycelium.demande.seau}:{un_pas.texte}")
            executer(un_pas, cible)

        mycelium.agitateur.executer = noter
        assert simu.jouer([module_mycelium(mycelium)]).fini
    # Une casse par bocal : au 1er seau A, et au 1er des 2 petits seaux (pas au 2e).
    assert pas == ["S0001:casse du bloc", "S0002:casse du bloc"]


def test_registre_doses_par_couche_et_variete(tmp_path):
    planning, _, registre = jouer(tmp_path)
    assert planning.fini, planning.probleme
    doses = registre.lire(
        "SELECT s.code AS seau, d.couche, b.code AS bocal, b.variete, d.quantite_g "
        "FROM doses_mycelium d JOIN seaux_du_cycle sc ON sc.id = d.seau_du_cycle_id "
        "JOIN seaux s ON s.id = sc.seau_id JOIN bocaux b ON b.id = d.bocal_id ORDER BY d.id"
    )
    assert len(doses) == 8
    assert doses[0]["couche"] == 1 and doses[3]["couche"] == 4
    assert {d["variete"] for d in doses} == {"pleurote_grise"}
    assert doses[0]["quantite_g"] == pytest.approx(150, abs=30)
    envoi = donnees_cycle(registre, 1, "cle", "machine", ZoneInfo("America/Guadeloupe"))
    assert [s["seau"] for s in envoi["seaux"]] == ["S0001", "S0002", "S0003"]
    assert envoi["seaux"][0]["defaut"] is None
    assert [d["couche"] for d in envoi["seaux"][0]["doses"]] == [1, 2, 3, 4]


def test_bocal_vide_alarme_et_seau_marque(tmp_path, reglages):
    # Un bocal neuf ne contient que 0,2 kg : la 2e couche du seau A ne monte plus.
    remplacer(reglages / "simulateur.yaml", "bocal_kg: 0.9", "bocal_kg: 0.2")
    planning, mycelium, registre = jouer(tmp_path, charger_reglages(reglages))
    assert "alarme de « mycelium », étape « agiter »" in planning.probleme
    assert "poids qui ne monte plus" in planning.probleme
    assert "Changer ou déboucher le bocal" in planning.probleme
    seau = registre.trouver("seau", "S0001")
    assert seau["defaut"].startswith("poids qui ne monte plus")
    # Le seau attend : la griffe ne vient pas le reprendre.
    assert mycelium.couche_en_attente()


def test_verrou_du_chariot_au_simulateur():
    with Simulateur(REGLAGES, LISTE, "dosage_mycelium") as simu:
        mycelium = mycelium_du_simulateur(simu)
        chariot = mycelium.chariot
        # Au garage manivelle en haut : le chariot peut rouler.
        chariot.ecarter()
        # Agitateur au demi-tour : le chariot refuse de rouler.
        simu.etat_axes.positions["agitateur_x"] = 0.865
        with pytest.raises(ErreurEtape, match="chariot de remplissage refusé"):
            chariot.amener_au_dosage(0.53)
        assert mycelium.dosage_en_cours() and not mycelium.camera_peut_pivoter()


def test_position_de_l_agitateur_pour_la_prehension():
    with Simulateur(REGLAGES, LISTE, "dosage_mycelium") as simu:
        mycelium = mycelium_du_simulateur(simu)
        # Au garage, manivelle en haut, arrêté.
        assert mycelium.x_agitateur() == pytest.approx(0.565)
        assert not mycelium.manivelle_en_bas()
        simu.etat_axes.positions["agitateur_x"] = 0.865
        assert mycelium.x_agitateur() == pytest.approx(0.865)


def test_agitateur_refuse_de_rouler_chariot_pas_ecarte():
    with Simulateur(REGLAGES, LISTE, "dosage_mycelium") as simu:
        mycelium = mycelium_du_simulateur(simu)
        mycelium.chariot.duree_s = 0
        mycelium.chariot._trajet.arrivee = EtatChariot(y=0.2, plateau_z=0.53)
        with pytest.raises(ErreurEtape, match="l'agitateur ne roule que si le chariot"):
            mycelium.lancer(mycelium.geste_aller_doser)


def test_outil_simulateur_mycelium(capsys):
    assert simulateur(["mycelium"]) == 0
    texte = capsys.readouterr().out
    assert "agiter" in texte and "Temps total" in texte


# ---------------------------------------------------------------- le vrai agitateur


def machine_rapide(**origine) -> Machine:
    """machine.yaml, avec un tour lent de la prise d'origine plus rapide (essais en vrai temps)."""
    donnees = MACHINE.model_dump()
    donnees["mycelium"]["manivelle"]["origine"].update({"vitesse_deg_s": 300, **origine})
    return Machine.model_validate(donnees)


class BancAgitateur:
    """Le vrai agitateur sur un faux FluidNC (glissière X, manivelle A), avec une fausse balance
    et un faux capteur de la manivelle : du métal partout sauf à ± `demi_zone` degrés du haut
    (`haut` : angle du moteur)."""

    def __init__(self, haut: float = 37.0, demi_zone: float = 95.0, **origine) -> None:
        self.faux = FauxFluidnc(axes="XYZA")
        self.faux.positions.update(X=925.0, A=180.0 + haut)
        self.haut, self.demi_zone = haut, demi_zone
        self.faux.monde = self._capteur
        self.balance = FausseForce(5.0 * G)
        self.liaison = Liaison("portique", reglages_essai(), ouvrir=self.faux.ouvrir)
        self.machine = machine_rapide(**origine)

    def _capteur(self) -> None:
        if ecart_angle(self.faux.positions["A"], self.haut) > self.demi_zone:
            self.faux.entrees.add("A")
        else:
            self.faux.entrees.discard("A")

    def __enter__(self) -> "BancAgitateur":
        self.liaison.demarrer()
        self.liaison.attendre_connexion(DELAI)
        carte = REGLAGES.fluidnc.cartes["mycelium_lavage"]
        self.agitateur = AgitateurFluidnc(self.machine, self.liaison, self.balance, carte)
        self.arret = threading.Event()
        self.agitateur.demarrer(self.arret)
        return self

    def prendre_origine(self) -> None:
        """Prise d'origine de la manivelle, puis manivelle remise en bas pile (180°)."""
        attendre(lambda: self.agitateur.glissiere_x() == pytest.approx(0.925), ignorer=ErreurEtape)
        self.agitateur.executer(Pas("origine", origine=True), None)
        attendre(self.agitateur.fini, 5)
        haut = self.agitateur.angle_haut_moteur
        assert haut is not None and ecart_angle(haut, self.haut) <= 3
        self.faux.positions["A"] = 180.0 + haut
        attendre(lambda: self.agitateur.position().angle == pytest.approx(180, abs=0.01))

    def __exit__(self, *_: object) -> None:
        self.arret.set()
        self.liaison.arreter()


def attendre(condition, delai: float = DELAI, ignorer=()) -> None:
    fin = time.monotonic() + delai
    while True:
        try:
            if condition():
                return
        except ignorer:
            pass
        assert time.monotonic() < fin, "pas arrivé à temps"
        time.sleep(0.01)


def test_agitateur_va_a_une_pose():
    with BancAgitateur() as banc:
        # Pas de position de la manivelle avant sa prise d'origine.
        attendre(lambda: banc.agitateur.glissiere_x() == pytest.approx(0.925), ignorer=ErreurEtape)
        with pytest.raises(ErreurEtape, match="origine de la manivelle pas faite"):
            banc.agitateur.position()
        banc.prendre_origine()
        pose = banc.agitateur.position()
        assert pose.x == 0.925 and pose.angle == pytest.approx(180, abs=0.01)
        banc.agitateur.executer(Pas("vers le demi-tour", x=0.9), pose.avec(x=0.9))
        assert banc.faux.lignes_recues[-1] == "$J=G53 X900.000 F6000"
        attendre(banc.agitateur.fini)
        banc.agitateur.executer(Pas("manivelle", angle=0, tr_min=20), pose.avec(x=0.9, angle=0))
        # 20 tr/min = 7200 °/min ; l'angle envoyé est celui du moteur.
        haut = banc.agitateur.angle_haut_moteur
        assert banc.faux.lignes_recues[-1] == f"$J=G53 A{haut:.3f} F7200"
        attendre(banc.agitateur.fini)
        assert banc.agitateur.position().angle == pytest.approx(0, abs=0.01)


def test_agitation_s_arrete_a_la_dose():
    with BancAgitateur() as banc:
        banc.prendre_origine()
        time.sleep(0.2)
        depart = time.monotonic()
        # Les grains tombent : +0,5 kg/s sur le plateau.
        banc.balance.fonction = lambda: (5.0 + 0.5 * (time.monotonic() - depart)) * G
        pose = banc.agitateur.position()
        pas = Pas("agitation", angle=180 + 360 * 50, tr_min=120, jusqu_a_kg=5.2)
        banc.agitateur.executer(pas, pose.avec(angle=pas.angle))
        attendre(banc.agitateur.fini, 5)
        resultat = banc.agitateur.resultat()
        assert resultat.arrete
        assert 180 < resultat.pose.angle < 180 + 360 * 50


def test_saut_de_poids_arrete_la_manivelle():
    with BancAgitateur() as banc:
        banc.prendre_origine()
        time.sleep(0.2)
        pose = banc.agitateur.position()
        pas = Pas("agitation", angle=180 + 360 * 50, tr_min=120, jusqu_a_kg=6.0)
        banc.agitateur.executer(pas, pose.avec(angle=pas.angle))
        time.sleep(0.1)
        # Le bocal tombe dans le seau : +0,8 kg d'un coup.
        banc.balance.newtons = 5.8 * G
        with pytest.raises(ErreurEtape, match="saut de poids") as erreur:
            attendre(lambda: banc.agitateur.fini() and False, 3)
        assert erreur.value.quoi_faire == QUOI_FAIRE_SAUT
        assert banc.agitateur.saut
        assert banc.agitateur.position().angle < 180 + 360 * 50


def test_balance_muette_arrete_l_agitation():
    with BancAgitateur() as banc:
        banc.prendre_origine()
        time.sleep(0.2)
        pose = banc.agitateur.position()
        pas = Pas("agitation", angle=180 + 360 * 50, tr_min=120, jusqu_a_kg=6.0)
        banc.agitateur.executer(pas, pose.avec(angle=pas.angle))
        banc.balance.muette = True
        with pytest.raises(ErreurEtape, match="balance du chariot muette"):
            attendre(lambda: banc.agitateur.fini() and False, 3)
