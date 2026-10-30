"""Remplissage (tâches 34 et 34 bis) : réglages, positions interdites du chariot, gestes sur le
chariot imaginaire, scénario « remplissage » du simulateur avec le Mycélium, chariot sur un faux
FluidNC, outil d'essai."""

import threading
import time

import pytest

from vidange.chef import ErreurEtape
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.griffe.simulation import FausseForce
from vidange.lavage.module import module_lavage_couvercles
from vidange.lavage.simulation import couvercles_du_simulateur
from vidange.mycelium.module import module_mycelium
from vidange.prehension.regles import Pose as PosePrehension
from vidange.reglages import Fluidnc, charger_reglages
from vidange.remplissage.chariot import ChariotFluidnc, Pas, signaux_chariot
from vidange.remplissage.module import module_remplissage
from vidange.remplissage.outil import main as outil
from vidange.remplissage.regles import Contexte, Pose, ReglesRemplissage
from vidange.remplissage.remplissage import Remplissage, SeauPlateau
from vidange.remplissage.simulation import ChariotSimule, remplissage_du_simulateur
from vidange.simulateur import Simulateur
from vidange.simulateur.axes import EtatAxes
from vidange.simulateur.outil import main as simulateur

from .conftest import DOSSIER_PI
from .test_reglages import erreur_de, remplacer

LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
REMPLISSAGE = MACHINE.remplissage
assert REMPLISSAGE is not None
REGLES = ReglesRemplissage(MACHINE)
# Tout est permis par les autres modules (chacun est essayé à part).
PERMIS = Contexte(
    chariot_fut_en_place=True,
    refus_mycelium=None,
    agitateur_au_garage=True,
    bras_galet_range=True,
)
# Au poste, plateau en bas, barres ouvertes, pousseur rentré.
POSTE = Pose(y=0.135, z=0.175, a=0.0, barres=0.30, pousseur=0.0)


# ---------------------------------------------------------------- réglages


def test_reglages_du_remplissage():
    r = REMPLISSAGE
    assert (r.poste_y, r.dosage_y, r.ecarte_y, r.pose_y) == (0.135, 0.155, 0.375, 0.50)
    assert MACHINE.axes["plateau_z"].course == (0.175, 0.575)
    assert MACHINE.axes["barres"].course == (0.1195, 0.305)
    assert r.verrous.anneaux_y == [(0.14, 0.41), (0.59, 0.86)]
    assert r.verrous.joues_barres == (0.235, 0.255) and r.verrous.joues_plateau_max_z == 0.48
    assert (r.verrous.barres_ouvertes_au_dessus_z, r.verrous.barres_ouvertes_min) == (0.515, 0.29)
    assert r.formats["seau_b"].pose_plateau_z == 0.5125
    assert r.couvercles.plateau_z == 0.459 and r.inspection.plateau_z == 0.575
    assert r.prise_double.traction_max_par_barre_n == 35
    # Tâche 34 bis : pousseur rentré à son zéro (côté fût), course 0,325 ; bout du chariot à
    # 0,40 de l'axe ; plus de bande du haut.
    assert r.pousseur_rentre_m == 0 and MACHINE.axes["pousseur"].course == (0.0, 0.325)
    assert r.verrous.pousseur_plateau_max_z == 0.20 and r.verrous.bout_y_m == 0.40
    assert {file.pousseur_m for file in r.rangement.files.values()} == {0.325}
    # Les 5 axes sur la carte n° 2, les axes d'exemple sur la n° 3.
    assert {MACHINE.axes[nom].carte for nom in ("remplissage_y", "barres", "plateau_a")} == {
        "chariot"
    }
    assert MACHINE.axes["exemple_x"].carte == "mycelium_lavage"


def test_un_format_sans_reglage_du_remplissage_est_refuse(reglages):
    remplacer(
        reglages / "machine.yaml",
        "    seau_d: {pose_plateau_z: 0.4475, centrage_hw_m: 0.128}\n",
        "",
    )
    assert "remplissage : il faut « formats → seau_d »" in erreur_de(reglages)


def test_une_file_hors_de_la_course_est_refusee(reglages):
    remplacer(reglages / "machine.yaml", "file_2: {y: 0.785", "file_2: {y: 0.95")
    assert "remplissage → rangement → files → file_2 → y : 0.95 hors de la course" in erreur_de(
        reglages
    )


def test_le_dosage_doit_etre_celui_du_mycelium(reglages):
    remplacer(reglages / "machine.yaml", "  dosage_y: 0.155\n", "  dosage_y: 0.150\n")
    assert "remplissage → dosage_y : le même que mycelium" in erreur_de(reglages)


def test_le_plateau_ne_depasse_jamais_0_575(reglages):
    remplacer(
        reglages / "machine.yaml", "    course: [0.175, 0.575]\n", "    course: [0.175, 0.578]\n"
    )
    charger_reglages(reglages)
    remplacer(
        reglages / "machine.yaml", "    course: [0.175, 0.578]\n", "    course: [0.175, 0.58]\n"
    )
    assert "course (0.175 à 0.58 m) sort du rail" in erreur_de(reglages)


# ---------------------------------------------------------------- règles de position


def test_regle_1_anneaux_du_fut():
    haut = POSTE.avec(z=0.45)
    assert REGLES.refus_pose(haut, PERMIS) is None  # au poste
    assert REGLES.refus_pose(haut.avec(y=0.155), PERMIS) is None  # au dosage
    assert REGLES.refus_pose(haut.avec(y=0.50), PERMIS) is None  # entre 0,41 et 0,59
    for y in (0.25, 0.70):
        assert "anneaux du fût" in REGLES.refus_pose(haut.avec(y=y), PERMIS)
        assert REGLES.refus_pose(POSTE.avec(y=y), PERMIS) is None
    # Quitter le poste plateau haut : refusé en route.
    refus = REGLES.refus_mouvement(haut, haut.avec(y=0.50), PERMIS)
    assert refus is not None and "en route" in refus and "anneaux" in refus


def test_regle_2_barres_entre_les_joues():
    pose = POSTE.avec(y=0.50, barres=0.245)
    assert REGLES.refus_pose(pose.avec(z=0.48), PERMIS) is None
    assert "joues de l'élévateur" in REGLES.refus_pose(pose.avec(z=0.49), PERMIS)
    # Fermer les barres plateau à 0,5125 (seau B) traverse les joues : refusé.
    depart = POSTE.avec(y=0.50, z=0.5125)
    assert "joues" in REGLES.refus_mouvement(depart, depart.avec(barres=0.1195), PERMIS)


def test_regle_3_barres_ouvertes_au_dessus_de_0_515():
    pose = POSTE.avec(y=0.50)
    assert REGLES.refus_pose(pose.avec(z=0.5125, barres=0.1195), PERMIS) is None
    assert "barres ouvertes" in REGLES.refus_pose(pose.avec(z=0.52, barres=0.20), PERMIS)
    assert REGLES.refus_pose(pose.avec(z=0.575, barres=0.29), PERMIS) is None


def test_regle_4_pousseur_rentre_des_que_le_plateau_monte():
    sorti = POSTE.avec(y=0.215, pousseur=0.325)
    assert REGLES.refus_pose(sorti, PERMIS) is None
    assert "pousseur sorti" in REGLES.refus_pose(POSTE.avec(y=0.50, z=0.30, pousseur=0.32), PERMIS)
    # Poussée refusée plateau au-dessus de 0,20, partout (même entre les anneaux).
    for z in (0.21, 0.4985):
        assert "pousseur sorti" in REGLES.refus_pose(sorti.avec(y=0.50, z=z), PERMIS)
    # Le plateau ne monte pas pousseur sorti.
    refus = REGLES.refus_mouvement(sorti.avec(y=0.50), sorti.avec(y=0.50, z=0.25), PERMIS)
    assert refus is not None and "pousseur sorti" in refus


def test_le_pousseur_rentre_a_son_zero_et_pousse_vers_le_stockage():
    banc = Banc()
    banc.jouer(lambda: banc.remplissage.geste_plateau(0.25))
    # Sortir le pousseur plateau à 0,25 : le plateau descend d'abord.
    banc.jouer(lambda: banc.remplissage.geste_pousseur(0.325))
    assert (banc.pose.z, banc.pose.pousseur) == (0.175, 0.325)
    # Monter le plateau : le pousseur rentre d'abord à son zéro.
    banc.jouer(lambda: banc.remplissage.geste_plateau(0.25))
    assert banc.pas()[-2:] == ["pousseur rentré", "plateau à 0,25"]
    assert (banc.pose.z, banc.pose.pousseur) == (0.25, 0.0)


def test_regle_5_bras_du_galet():
    pose = POSTE.avec(y=0.50, z=0.30)
    assert "bras du galet pas connu" in REGLES.refus_pose(pose, Contexte(chariot_fut_en_place=True))
    assert "pas rangé" in REGLES.refus_pose(pose, Contexte(True, None, True, False))
    assert REGLES.refus_pose(pose.avec(z=0.26), Contexte(chariot_fut_en_place=True)) is None
    assert REGLES.refus_bras_galet(pose) is not None
    assert REGLES.refus_bras_galet(pose.avec(z=0.25)) is None


def test_regle_6_bras_du_spray():
    pose = POSTE.avec(y=0.50, z=0.45, barres=0.30)
    # Seau A (h 0,25) : plateau ≤ min(0,50 ; 0,46).
    assert REGLES.refus_bras_spray(pose, 0.25) is None
    assert "plateau ≤ 0,46" in REGLES.refus_bras_spray(pose.avec(z=0.47), 0.25)
    assert "entraxe" in REGLES.refus_bras_spray(pose.avec(barres=0.25), 0.25)
    contexte = Contexte(True, None, True, True, bras_spray_sorti=True, hauteur_seau=0.25)
    assert "bras du spray" in REGLES.refus_pose(pose.avec(z=0.47), contexte)


def test_regle_7_chariot_du_fut_absent():
    absent = Contexte(chariot_fut_en_place=False, refus_mycelium=None, bras_galet_range=True)
    # Bout du chariot à 0,40 de l'axe : axe du plateau à y ≤ 0,875 − 0,40 = 0,475.
    assert REGLES.refus_pose(POSTE.avec(y=0.475), absent) is None
    for y in (0.48, 0.50, 0.785):
        refus = REGLES.refus_pose(POSTE.avec(y=y), absent)
        assert refus is not None and "chariot du fût pas en place" in refus
        assert "axe du plateau ≤ 0,475" in refus
    assert REGLES.refus_pose(POSTE.avec(y=0.785), PERMIS) is None


def test_regle_8_ordre_avec_l_agitateur():
    refuse = Contexte(True, "agitateur du mycélium à x 0,7 m", False, True)
    # Rouler près du poste : refusé ; loin du poste (0,50 → 0,785) : permis.
    assert "agitateur du mycélium" in REGLES.refus_mouvement(POSTE, POSTE.avec(y=0.375), refuse)
    loin = POSTE.avec(y=0.50)
    assert REGLES.refus_mouvement(loin, loin.avec(y=0.785), refuse) is None
    # Le plateau ne monte au poste qu'agitateur au garage, sauf pour le dosage.
    garage_inconnu = Contexte(True, None, False, True)
    au_dosage = POSTE.avec(y=0.155)
    assert "agitateur du mycélium au garage" in REGLES.refus_mouvement(
        au_dosage, au_dosage.avec(z=0.53), garage_inconnu
    )
    assert REGLES.refus_mouvement(au_dosage, au_dosage.avec(z=0.53), garage_inconnu, True) is None


def test_regle_9_descente_de_la_prehension():
    assert REGLES.refus_descente_prehension(POSTE, True) is None
    assert "barres ouvertes" in REGLES.refus_descente_prehension(POSTE.avec(barres=0.2), True)
    assert "micropore" in REGLES.refus_descente_prehension(POSTE, None)
    # Au-dessus du chariot : près de son axe en x, entre y − 0,40 et y + 0,40 (EXEMPLES).
    x = REMPLISSAGE.axe_x
    assert REGLES.au_dessus_du_chariot(x, 0.50, POSTE.avec(y=0.50))
    assert not REGLES.au_dessus_du_chariot(x + 0.30, 0.50, POSTE.avec(y=0.50))
    assert not REGLES.au_dessus_du_chariot(x, 0.95, POSTE.avec(y=0.50))
    assert REGLES.au_dessus_du_chariot(x, 0.95, None)  # chariot qui bouge : tout son rail


def test_une_pose_deja_interdite_peut_en_sortir():
    # Après une coupure : plateau haut sous les anneaux. Le descendre est permis.
    perdu = POSTE.avec(y=0.30, z=0.45)
    assert REGLES.refus_mouvement(perdu, perdu.avec(z=0.175), PERMIS) is None
    assert REGLES.refus_mouvement(perdu, perdu.avec(z=0.50), PERMIS) is not None


# ---------------------------------------------------------------- gestes (chariot imaginaire)


class Banc:
    """Le vrai Remplissage sur le chariot imaginaire, à l'heure d'une horloge à la main."""

    def __init__(self, **options) -> None:
        self.temps = [0.0]
        horloge = lambda: self.temps[0]  # noqa: E731
        self.etat = EtatAxes(MACHINE, REGLAGES.simulateur, horloge)
        self.etat.positions.update(MACHINE.positions["remplissage_poste"])
        self.chariot = ChariotSimule(self.etat, MACHINE, horloge)
        self.photos: list[str] = []
        valeurs = {
            "chariot_fut_en_place": lambda: True,
            "refus_mycelium": lambda: None,
            "agitateur_au_garage": lambda: True,
            "bras_galet_range": lambda: True,
            "micropore_rentre": lambda: True,
            "photo": self.photos.append,
        }
        valeurs.update(options)
        self.remplissage = Remplissage(MACHINE, self.chariot, horloge=horloge, **valeurs)

    def finir(self) -> None:
        for _ in range(20000):
            if self.remplissage.geste_fini():
                return
            self.temps[0] += 0.25
        raise AssertionError("geste pas fini")

    def jouer(self, fabrique) -> None:
        self.remplissage.lancer(fabrique)
        self.finir()

    @property
    def pose(self) -> Pose:
        return self.chariot.position()

    def pas(self) -> list[str]:
        return [mouvement.position for mouvement in self.etat.mouvements]


def test_aller_a_la_pose_passe_par_les_bons_detours():
    banc = Banc()
    banc.jouer(lambda: banc.remplissage.geste_aller_a_la_pose("seau_b"))
    assert banc.pose == Pose(y=0.50, z=0.5125, a=0.0, barres=0.30, pousseur=0.0)
    # Seau B : centrage (barres à 0,1195 + jeu) plateau à 0,5125 : le plateau descend sous les
    # joues, les barres passent, le plateau remonte.
    banc.remplissage.seau = SeauPlateau("seau_b", "S1", angle_anse=0.0)
    banc.jouer(banc.remplissage.geste_centrer)
    assert banc.pas()[-6:] == [
        "plateau plus bas, pour bouger les barres",
        "centrer le seau (barres au contact)",
        "plateau remonté",
        "plateau plus bas, pour bouger les barres",
        "barres ouvertes",
        "plateau remonté",
    ]
    assert (banc.pose.barres, banc.pose.z) == (0.30, 0.5125)


def test_ramener_au_poste_puis_ranger():
    banc = Banc()
    remplissage = banc.remplissage
    banc.jouer(lambda: remplissage.geste_aller_a_la_pose("seau_a"))
    remplissage.seau = SeauPlateau("seau_a", "S1", angle_anse=12.0)
    banc.jouer(remplissage.geste_ramener_au_poste)
    assert (banc.pose.y, banc.pose.z) == (0.135, pytest.approx(0.53))
    assert "plateau en bas" in banc.pas()
    assert remplissage.seau_au_poste()
    # Le seau tourne pendant les versements, puis revient à l'angle de l'anse (modulo 90°).
    remplissage.tourner_seau(True)
    assert not remplissage.seau_au_poste()
    banc.temps[0] += 10
    remplissage.tourner_seau(False)
    assert banc.pose.a == pytest.approx(600, abs=1)
    banc.chariot.seau_pose, banc.chariot.contenu_kg = True, 6.0
    banc.jouer(lambda: remplissage.geste_ranger("file_1"))
    assert banc.pose.a % 90 == pytest.approx(12.0)
    assert banc.pose.y == 0.215 and banc.pose.pousseur == 0.0
    assert banc.pas()[-2:] == ["le pousseur pousse le seau", "pousseur rentré"]
    poussee = banc.etat.mouvements[-2]
    assert poussee.axes["pousseur"][1] == 0.325 and banc.pose.z == 0.175
    assert remplissage.seau is None
    assert remplissage.derniere_pesee_kg == pytest.approx(6.5)
    assert banc.photos == ["seau S1 rangé en file_1"]


def test_ranger_loin_refuse_sans_chariot_du_fut():
    banc = Banc(chariot_fut_en_place=lambda: False)
    remplissage = banc.remplissage
    with pytest.raises(ErreurEtape, match="chariot du fût pas en place"):
        banc.jouer(lambda: remplissage.geste_aller(0.85))
    assert banc.pose.y == 0.135
    # La file 2 (0,785) est refusée au-delà de 0,475 sans le chariot du fût ; la file 1 passe.
    remplissage.seau = SeauPlateau("seau_a", "S1", angle_anse=0.0)
    with pytest.raises(ErreurEtape, match="axe du plateau ≤ 0,475"):
        banc.jouer(lambda: remplissage.geste_ranger("file_2"))
    assert banc.pose.y == 0.135
    banc.chariot.seau_pose = True
    banc.jouer(lambda: remplissage.geste_ranger("file_1"))
    assert banc.pose.y == 0.215 and remplissage.seau is None


def test_alarme_des_barres_pendant_le_centrage():
    banc = Banc()
    remplissage = banc.remplissage
    banc.jouer(lambda: remplissage.geste_aller_a_la_pose("seau_a"))
    remplissage.seau = SeauPlateau("seau_a", "S1", angle_anse=0.0)
    remplissage.lancer(remplissage.geste_centrer)
    banc.temps[0] += 0.5
    banc.chariot.alarme_barres_active = True
    with pytest.raises(ErreurEtape, match="alarme du pilote des barres") as erreur:
        banc.finir()
    assert "forcent" in erreur.value.quoi_faire
    assert banc.photos == ["alarme du pilote des barres"]
    assert remplissage.libre()


def test_le_chariot_attend_l_agitateur_pres_du_poste():
    banc = Banc(refus_mycelium=lambda: "agitateur du mycélium à x 0,7 m")
    with pytest.raises(ErreurEtape, match="ne roule pas près du poste"):
        banc.jouer(lambda: banc.remplissage.geste_aller(0.50))
    banc = Banc(agitateur_au_garage=lambda: False)
    banc.remplissage.seau = SeauPlateau("seau_a", "S1", angle_anse=0.0)
    with pytest.raises(ErreurEtape, match="qu'agitateur du mycélium au garage"):
        banc.jouer(banc.remplissage.geste_ramener_au_poste)


def test_le_mycelium_mene_le_chariot_au_dosage():
    banc = Banc()
    remplissage = banc.remplissage
    banc.jouer(lambda: remplissage.geste_plateau(0.53))
    remplissage.ecarter()
    etat = remplissage.etat()
    assert etat is not None and not etat.immobile and etat.y == 0.135
    banc.finir()
    assert remplissage.etat() == remplissage.etat().__class__(0.375, 0.175, True)  # type: ignore[union-attr]
    remplissage.amener_au_dosage(0.53)
    banc.finir()
    assert (banc.pose.y, banc.pose.z, banc.pose.barres) == (0.155, 0.53, 0.30)


def test_mode_couvercles_pour_le_retourneur():
    banc = Banc()
    remplissage = banc.remplissage
    assert not remplissage.chariot_en_place()
    with pytest.raises(ErreurEtape, match="hors du mode couvercles"):
        remplissage.regler_barres(0.19)
    banc.jouer(remplissage.geste_mode_couvercles)
    assert remplissage.chariot_en_place()
    remplissage.regler_barres(0.19)
    assert remplissage.ecart_barres() is None
    banc.finir()
    assert remplissage.ecart_barres() == 0.19
    assert remplissage.barriere_coupee() is False
    banc.chariot.double = True
    assert remplissage.barriere_coupee() is True
    with pytest.raises(ErreurEtape, match="pas de rotation"):
        remplissage.tourner_seau(True)


def test_mode_inspection_des_bocaux():
    banc = Banc()
    remplissage = banc.remplissage
    banc.jouer(remplissage.geste_mode_inspection)
    assert (banc.pose.y, banc.pose.z, banc.pose.barres) == (0.50, 0.575, 0.30)
    banc.jouer(remplissage.geste_tourner_inspection)
    assert banc.pose.a == 45
    banc.chariot.contenu_kg = 1.0
    banc.jouer(lambda: remplissage.geste_peser_bocal(1.05))
    with pytest.raises(ErreurEtape, match="pas d'accord|la balance lit"):
        banc.jouer(lambda: remplissage.geste_peser_bocal(1.5))


def test_fonctions_pour_les_autres_modules():
    banc = Banc()
    remplissage = banc.remplissage
    assert remplissage.refus_bras_galet() is None
    assert remplissage.refus_descente_prehension() is None
    assert "hauteur du seau" in remplissage.refus_bras_spray()
    banc.jouer(lambda: remplissage.geste_barres(0.2))
    assert "barres ouvertes" in remplissage.refus_descente_prehension()


def test_regle_9_dans_la_prehension():
    """La tête ne descend sous 0,84 au-dessus du chariot que barres ouvertes et micropore
    rentré, sauf en mode couvercles."""
    banc = Banc()
    remplissage = banc.remplissage
    x = REMPLISSAGE.axe_x
    haut = PosePrehension(x, 0.135, 1.10, 0.0)
    bas = PosePrehension(x, 0.135, 0.60, 0.0)
    assert remplissage.refus_prehension(haut, bas) is None
    banc.jouer(lambda: remplissage.geste_barres(0.2))
    assert "barres ouvertes" in remplissage.refus_prehension(haut, bas)
    # Monter, rester au-dessus de 0,84 ou descendre loin du chariot : permis.
    assert remplissage.refus_prehension(bas, haut) is None
    assert remplissage.refus_prehension(haut, PosePrehension(x, 0.135, 0.85, 0.0)) is None
    assert remplissage.refus_prehension(haut, PosePrehension(x + 0.4, 0.135, 0.6, 0.0)) is None
    # Mode couvercles (retourneur) : barres à 0,19, la tête descend quand même.
    banc.jouer(lambda: remplissage.geste_barres(0.30))
    banc.jouer(remplissage.geste_mode_couvercles)
    remplissage.regler_barres(0.19)
    banc.finir()
    retourneur = PosePrehension(x, 0.50, 0.60, 0.0)
    assert remplissage.refus_prehension(haut.avec(y=0.50), retourneur) is None
    banc.jouer(remplissage.geste_fin_de_mode)
    banc.jouer(lambda: remplissage.geste_barres(0.19))
    assert "barres ouvertes" in remplissage.refus_prehension(haut.avec(y=0.50), retourneur)
    # Micropore pas rentré : refusé aussi.
    banc = Banc(micropore_rentre=lambda: None)
    assert "micropore" in banc.remplissage.refus_prehension(haut, bas)


def test_la_prehension_applique_la_regle_9():
    with Simulateur(REGLAGES, LISTE, "remplissage") as simulation:
        scenario = remplissage_du_simulateur(simulation)
        remplissage, prehension = scenario.remplissage, scenario.prehension
        remplissage.brancher_prehension(prehension)
        poste = simulation.poste_fut()
        for _ in range(100):
            if not poste.echange_en_cours:
                break
            simulation.temps += 0.5
        prehension.lancer(lambda: prehension.geste_aller(REMPLISSAGE.axe_x, 0.135))
        while not prehension.geste_fini():
            simulation.temps += 0.25
        cible = PosePrehension(REMPLISSAGE.axe_x, 0.135, 0.60, 0.0)
        assert prehension.refus_manuel(cible) is None
        remplissage.lancer(lambda: remplissage.geste_barres(0.2))
        assert "il bouge" in prehension.refus_manuel(cible)
        while not remplissage.geste_fini():
            simulation.temps += 0.25
        assert "barres ouvertes" in prehension.refus_manuel(cible)
        with pytest.raises(ErreurEtape, match="refusé"):
            prehension.lancer(lambda: prehension.descendre(0.60, "essai"))


def test_le_vrai_chariot_remplace_le_faux_retourneur():
    with Simulateur(REGLAGES, LISTE, "lavage_couvercles") as simulation:
        couvercles = couvercles_du_simulateur(simulation)
        etat = simulation.etat_axes
        etat.positions.update(MACHINE.positions["remplissage_poste"])
        chariot = ChariotSimule(etat, MACHINE, lambda: simulation.temps)
        remplissage = Remplissage(
            MACHINE,
            chariot,
            horloge=lambda: simulation.temps,
            chariot_fut_en_place=lambda: True,
            refus_mycelium=lambda: None,
            agitateur_au_garage=lambda: True,
            bras_galet_range=lambda: True,
        )
        # Le chariot va au retourneur avant le lavage des couvercles.
        remplissage.lancer(remplissage.geste_mode_couvercles)
        while not remplissage.geste_fini():
            simulation.temps += 0.5
        couvercles.retourneur = remplissage
        lavage = REGLAGES.simulateur.lavage
        assert lavage is not None
        planning = simulation.jouer([module_lavage_couvercles(couvercles, lavage.couvercles)])
    assert planning.fini, planning.probleme
    barres = [m.axes["barres"][1] for m in etat.mouvements if "barres" in m.axes]
    assert barres[0] == 0.19 and set(barres) == {0.19, 0.30}


# ---------------------------------------------------------------- scénario du simulateur


def jouer_scenario(regler=lambda scenario: None):
    with Simulateur(REGLAGES, LISTE, "remplissage") as simulation:
        scenario = remplissage_du_simulateur(simulation)
        regler(scenario)
        modules = [
            module_remplissage(
                scenario.remplissage, scenario.prehension, scenario.mycelium, scenario.plan
            ),
            module_mycelium(scenario.mycelium),
        ]
        return simulation.jouer(modules), scenario


def test_scenario_remplissage_va_au_bout():
    planning, scenario = jouer_scenario()
    assert planning.fini, planning.probleme
    etapes = [ligne.etape for ligne in planning.lignes if ligne.module == "remplissage"]
    # Seau A : prise double séparée, le seau du dessus rendu ; seau B : posé simplement.
    assert etapes.count("rendre_le_seau_du_dessus") == 1
    assert etapes.count("ranger") == 2 and etapes.count("doser") == 4 + 2
    assert scenario.plan.faits == ["S0101", "S0102"]
    assert [dose.seau for dose in scenario.mycelium.doses] == ["S0101"] * 4 + ["S0102"] * 2
    assert scenario.remplissage.seau is None and not scenario.remplissage.seau_du_dessus


def test_prise_double_dans_l_ordre_a_a_h():
    planning, scenario = jouer_scenario()
    assert planning.fini, planning.probleme
    tous = scenario.chariot._etat.mouvements
    mouvements = [m for m in tous if m.position.startswith("prise double")]
    assert [m.position for m in mouvements] == [
        "prise double : barres au centrage",
        "prise double a) : la tête monte",
        "prise double b) : lâcher (barres)",
        "prise double c) : la tête descend",
        "prise double d) : barres contre la lèvre du seau du dessous",
        "prise double e) : le plateau monte toucher le fond du seau du dessous",
        "prise double f) : la tête emporte le seau du haut",
        "prise double g) : lâcher (barres)",
        "prise double h) : le plateau remonte",
    ]
    # Le plateau ne bouge pas avant e.
    e = [m.position for m in mouvements].index(
        "prise double e) : le plateau monte toucher le fond du seau du dessous"
    )
    assert not any("plateau_z" in m.axes for m in mouvements[:e])
    assert "plateau_z" in mouvements[-1].axes
    # Barres : centrage (seau A, 0,125 + jeu), + 1,5 cm, lèvre (Ø haut + 6 mm), + 1,5 cm.
    barres = [m.axes["barres"][1] for m in mouvements if "barres" in m.axes]
    seau_a = MACHINE.griffe.formats["seau_a"]  # type: ignore[union-attr]
    levre = seau_a.rayon_haut + 0.003
    assert barres == pytest.approx([0.127, 0.142, levre, levre + 0.015])


def test_prise_double_qui_echoue():
    def regler(scenario):
        scenario.chariot.separation_ratee = True

    planning, scenario = jouer_scenario(regler)
    assert not planning.fini
    assert "barrière lumineuse encore coupée après la séparation" in planning.probleme


def test_barriere_muette():
    def regler(scenario):
        scenario.chariot.barriere_muette = True

    planning, _ = jouer_scenario(regler)
    assert not planning.fini and "barrière lumineuse du chariot pas lue" in planning.probleme


def test_qr_du_flanc_illisible():
    def regler(scenario):
        scenario.vision.illisible = True

    planning, _ = jouer_scenario(regler)
    assert not planning.fini and "QR du flanc du seau pas lu" in planning.probleme


def test_outil_simulateur_remplissage(capsys):
    assert simulateur(["remplissage", "--delai-go", "0"]) == 0
    assert "remplissage" in capsys.readouterr().out


# ---------------------------------------------------------------- chariot sur un faux FluidNC


def reglages_carte() -> Fluidnc:
    return Fluidnc.model_validate(
        {
            "liaison": {
                "vitesse_bauds": 115200,
                "taille_tampon": 128,
                "periode_etat_s": 0.02,
                "delai_silence_s": 0.3,
                "delai_reconnexion_s": 0.05,
            },
            "cartes": {
                "chariot": {
                    "numero_serie_usb": "A2",
                    "entrees": {"barriere_remplissage": "0", "alarme_barres": "1"},
                },
            },
        }
    )


def attendre(condition, delai: float = 5.0) -> None:
    fin = time.monotonic() + delai
    while not condition():
        assert time.monotonic() < fin, "pas arrivé à temps"
        time.sleep(0.01)


def test_chariot_sur_un_faux_fluidnc():
    carte = FauxFluidnc(axes="XYZABC", vitesse_rapide_mm_min=60000)
    # Au poste ; barres à hw 0,30 = 0,30 − 0,309 = −9 mm pour la carte.
    carte.positions.update(Y=135.0, Z=175.0, A=0.0, B=-9.0, C=0.0)
    reglages = reglages_carte()
    liaison = Liaison("chariot", reglages, ouvrir=carte.ouvrir)
    liaison.demarrer()
    arret = threading.Event()
    try:
        liaison.attendre_connexion(5)
        balance = FausseForce(9.81 * 0.5)
        chariot = ChariotFluidnc(
            MACHINE, liaison, balance, signaux_chariot(liaison, reglages.cartes["chariot"])
        )
        chariot.demarrer(arret)
        attendre(lambda: chariot.position().barres == pytest.approx(0.30))
        assert chariot.position() == Pose(0.135, 0.175, 0.0, pytest.approx(0.30), 0.0)
        assert chariot.barriere_coupee() is False
        assert chariot.alarme_barres() is False
        carte.entrees.add("0")
        attendre(lambda: chariot.barriere_coupee() is True)
        # Centrage en position : barres à 0,125 (−184 mm pour la carte), sans sortie.
        cible = chariot.position().avec(barres=0.125)
        chariot.executer(Pas("centrer", {"barres": 0.125}), cible)
        attendre(chariot.fini)
        assert carte.positions["B"] == pytest.approx(-184.0)
        assert not carte.sorties
        # Alarme ALM du pilote des barres, lue dans « Pn: ».
        carte.entrees.add("1")
        attendre(lambda: chariot.alarme_barres() is True)
        attendre(lambda: abs(chariot.peser() - 0.5) < 1e-6)
    finally:
        arret.set()
        liaison.arreter()


def test_outil_etat_avec_un_faux_fluidnc(capsys):
    assert outil(["--faux", "etat"]) == 0
    sortie = capsys.readouterr().out
    assert "chariot : y 0.1350 m" in sortie and "barres : hw 0.3000 m" in sortie
    with pytest.raises(SystemExit):
        outil(["--faux", "aller"])
