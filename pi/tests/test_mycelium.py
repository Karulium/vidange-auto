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
EN_HAUT = PoseAgitateur(angle=0.0)
EN_BAS = PoseAgitateur(angle=180.0)
ECARTE = EtatChariot(y=0.40, plateau_z=0.53)
AU_VIDAGE = EtatChariot(y=0.42, plateau_z=0.53)
AU_DOSAGE = EtatChariot(y=0.155, plateau_z=0.53)
AU_POSTE = EtatChariot(y=0.135, plateau_z=0.43)


# ---------------------------------------------------------------- réglages


def test_reglages_du_mycelium_du_depot():
    assert MYCELIUM.exemple
    # Agitateur fixe (01/11/2026) : bocal toujours en (0,925 ; 0,150), plus de glissière.
    assert MYCELIUM.bocal == pytest.approx((0.925, 0.150))
    assert MYCELIUM.manivelle_z == pytest.approx(0.762)
    assert "agitateur_x" not in MACHINE.axes
    assert MACHINE.axes["manivelle"].unite == "deg"
    assert MYCELIUM.chariot.y_ecarte_min == pytest.approx(0.40)
    assert FORMATS["seau_b"].seaux_par_bocal == 2 and FORMATS["seau_a"].seaux_par_bocal == 1
    # Plateau pendant le dosage : min(0,78 − h ; 0,575).
    assert REGLES.plateau_dosage(FORMATS["seau_a"]) == pytest.approx(0.53)
    assert REGLES.plateau_dosage(FORMATS["seau_b"]) == pytest.approx(0.575)


def test_glissiere_retiree_des_entrees_sorties_et_de_fluidnc():
    for nom in (
        "moteur_glissiere_agitateur",
        "alarme_glissiere_agitateur",
        "fdc_agitateur_garage",
        "fdc_agitateur_dosage",
    ):
        assert nom not in LISTE.signaux
    texte = (DOSSIER_PI.parent / "fluidnc" / "mycelium_lavage.yaml").read_text()
    assert "\n  x:\n" not in texte and "\n  y:\n" in texte and "\n  a:\n" in texte


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


def test_seaux_du_simulateur_verifies(reglages):
    remplacer(reglages / "simulateur.yaml", "format: seau_a, variete", "format: seau_z, variete")
    assert "mycelium → seaux : format « seau_z » absent de machine.yaml" in erreur_de(reglages)


# ---------------------------------------------------------------- verrous


def test_demi_tour_seulement_manivelle_en_haut_et_chariot_a_0_40():
    assert REGLES.refus_demi_tour(EN_HAUT, ECARTE) is None
    assert REGLES.refus_demi_tour(EN_HAUT, AU_VIDAGE) is None
    # Manivelle en bas : refusé.
    assert "manivelle en haut" in REGLES.refus_demi_tour(EN_BAS, ECARTE)
    # Chariot à 0,39 : refusé ; inconnu : refusé.
    texte = REGLES.refus_demi_tour(EN_HAUT, EtatChariot(y=0.39, plateau_z=0.53))
    assert "chariot de remplissage à y ≥ 0,4 m" in texte
    assert "chariot" in REGLES.refus_demi_tour(EN_HAUT, None)
    # Caméra du dosage pas à 0° : le demi-tour ne démarre pas (point 6 c).
    assert "caméra du dosage à 0°" in REGLES.refus_demi_tour(EN_HAUT, ECARTE, camera_pivote=True)


def test_manivelle_ne_quitte_le_bas_que_chariot_a_0_40():
    # Chariot à y ≥ 0,40 : tout est permis (aller en haut, prise d'origine).
    assert REGLES.refus_manivelle(EN_HAUT, ECARTE) is None
    assert REGLES.refus_manivelle(None, ECARTE) is None
    # Chariot au poste : manivelle en haut refusée (et la prise d'origine aussi).
    assert "il doit être à y ≥ 0,4 m" in REGLES.refus_manivelle(EN_HAUT, AU_POSTE)
    assert "prise d'origine" in REGLES.refus_manivelle(None, AU_POSTE)
    assert "inconnue" in REGLES.refus_manivelle(EN_HAUT, None)
    # Aller en bas : permis chariot arrêté, jamais pendant qu'il roule.
    assert REGLES.refus_manivelle(EN_BAS, AU_POSTE) is None
    en_route = EtatChariot(y=0.25, plateau_z=0.53, immobile=False)
    assert "pendant que le chariot" in REGLES.refus_manivelle(EN_BAS, en_route)


def test_agitation_seulement_seau_au_dosage():
    assert REGLES.refus_manivelle(EN_BAS.avec(angle=180 + 360 * 5), AU_DOSAGE, True) is None
    assert REGLES.refus_manivelle(EN_BAS, ECARTE, True) is None
    assert "l'agitation ne se fait que seau au dosage" in REGLES.refus_manivelle(
        EN_BAS, AU_POSTE, True
    )
    # Une agitation s'arrête toujours pile en bas.
    assert "l'agitation" in REGLES.refus_manivelle(EN_HAUT, AU_DOSAGE, True)


def test_chariot_ne_roule_pres_du_poste_que_manivelle_en_bas():
    assert REGLES.refus_chariot(EN_BAS, en_mouvement=False) is None
    assert "bouge" in REGLES.refus_chariot(EN_BAS, en_mouvement=True)
    for pose in (EN_HAUT, EN_BAS.avec(angle=90)):
        assert "que manivelle en bas" in REGLES.refus_chariot(pose, False)
    assert "inconnue" in REGLES.refus_chariot(None, False)


def test_plateau_verifie():
    assert REGLES.refus_plateau(FORMATS["seau_a"], AU_DOSAGE) is None
    refus = REGLES.refus_plateau(FORMATS["seau_b"], AU_DOSAGE)
    assert "plateau du chariot de remplissage à z 0,53 m, il faut 0,575 m" in refus


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
    # La manivelle ne s'arrête jamais entre le haut et le bas, et reste près de 0 ; elle
    # attend en bas.
    angle = mycelium.agitateur.position().angle
    assert REGLES.en_bas(mycelium.agitateur.position()) and abs(angle) <= 360 * 200


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
        chariot.duree_s = 0
        # Manivelle en bas (l'attente) : le chariot peut rouler près du poste.
        assert mycelium.refus_chariot() is None
        chariot.amener_au_dosage(0.53)
        # Manivelle en haut : le chariot refuse de rouler.
        simu.etat_axes.positions["manivelle"] = 0.0
        with pytest.raises(ErreurEtape, match="chariot de remplissage refusé"):
            chariot.ecarter()
        # La caméra du dosage n'a pas de condition sur la manivelle (seulement le demi-tour).
        assert mycelium.camera_peut_pivoter()


def test_manivelle_pour_la_prehension():
    with Simulateur(REGLAGES, LISTE, "dosage_mycelium") as simu:
        mycelium = mycelium_du_simulateur(simu)
        # En attente : manivelle en bas, arrêtée.
        assert mycelium.etat_manivelle() == "bas" and not mycelium.dosage_en_cours()
        simu.etat_axes.positions["manivelle"] = 0.0
        assert mycelium.etat_manivelle() == "haut" and mycelium.dosage_en_cours()
        simu.etat_axes.positions["manivelle"] = 90.0
        assert mycelium.etat_manivelle() is None


def test_demi_tour_refuse_au_simulateur():
    with Simulateur(REGLAGES, LISTE, "dosage_mycelium") as simu:
        mycelium = mycelium_du_simulateur(simu, faux_porte_bocal=True)
        mycelium.chariot.duree_s = 0
        # Chariot à y 0,39 : la manivelle ne monte pas (donc pas de demi-tour).
        mycelium.chariot._trajet.arrivee = EtatChariot(y=0.39, plateau_z=0.53)
        with pytest.raises(ErreurEtape, match="il doit être à y ≥ 0,4 m"):
            mycelium.lancer(mycelium.geste_retourner_le_bocal)
        # Manivelle en haut mais chariot à 0,39 : le demi-tour lui-même est refusé.
        simu.etat_axes.positions["manivelle"] = 0.0
        with pytest.raises(ErreurEtape, match="chariot de remplissage à y ≥ 0,4 m"):
            mycelium.lancer(mycelium.geste_retourner_le_bocal)
        # Chariot à 0,40, caméra du dosage pas à 0° : refusé aussi.
        mycelium.chariot._trajet.arrivee = EtatChariot(y=0.40, plateau_z=0.53)

        class CameraPivotee:
            def pivote(self) -> bool:
                return True

        mycelium.camera = CameraPivotee()  # type: ignore[assignment]
        with pytest.raises(ErreurEtape, match="caméra du dosage à 0°"):
            mycelium.lancer(mycelium.geste_retourner_le_bocal)
        # Pendant un demi-tour, la caméra du dosage ne pivote pas.
        mycelium.camera = None
        mycelium.lancer(mycelium.geste_retourner_le_bocal)
        assert mycelium._pas is not None and mycelium._pas.porte_bocal == "tete_en_bas"
        assert not mycelium.camera_peut_pivoter()


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
    """Le vrai agitateur sur un faux FluidNC (manivelle A), avec une fausse balance
    et un faux capteur de la manivelle : du métal partout sauf à ± `demi_zone` degrés du haut
    (`haut` : angle du moteur)."""

    def __init__(self, haut: float = 37.0, demi_zone: float = 95.0, **origine) -> None:
        self.faux = FauxFluidnc(axes="XYZA")
        self.faux.positions.update(A=180.0 + haut)
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
        attendre(lambda: "A" in self.liaison.etat.positions)
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
        attendre(lambda: "A" in banc.liaison.etat.positions)
        with pytest.raises(ErreurEtape, match="origine de la manivelle pas faite"):
            banc.agitateur.position()
        banc.prendre_origine()
        pose = banc.agitateur.position()
        assert pose.angle == pytest.approx(180, abs=0.01)
        banc.agitateur.executer(Pas("manivelle", angle=0, tr_min=20), pose.avec(angle=0))
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
