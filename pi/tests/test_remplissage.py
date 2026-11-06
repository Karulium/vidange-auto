"""Remplissage (tâches 34, 34 bis, 34 ter et 35 bis) : réglages, positions interdites du
chariot, gestes sur le chariot imaginaire, scénario « remplissage » du simulateur avec le
Mycélium, chariot sur un faux FluidNC, outil d'essai."""

import threading
import time
from dataclasses import replace

import pytest

from vidange.chef import ErreurEtape
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.griffe.regles import Pose as PoseGriffe
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
    bras_galet_range=True,
)
# Au poste, plateau en bas, barres ouvertes, pousseur rentré.
POSTE = Pose(y=0.135, z=0.175, a=0.0, barres=0.30, pousseur=0.0)


# ---------------------------------------------------------------- réglages


def test_hauteurs_de_pose_vraies():
    # Tâche 36 bis, point 1 : hauteurs de pose vraies des 4 formats ; face = H + 0,003.
    poses = {nom: f.pose_plateau_z for nom, f in REMPLISSAGE.formats.items()}
    assert poses == {"seau_a": 0.4675, "seau_b": 0.5125, "seau_c": 0.4925, "seau_d": 0.4625}
    assert REMPLISSAGE.face_au_dessus_plateau_m == 0.003


def test_face_de_la_prise_double_dans_la_course_verifiee(reglages):
    # Étape c) de la prise double : face = pose + 0,003 − 0,028 ≥ bas de la course de la face.
    # Seau D : 0,4625 + 0,003 − 0,028 = 0,4375 ; avec une course qui commencerait à 0,44 : refusé.
    remplacer(
        reglages / "machine.yaml",
        "    longueur_rail: 1.15\n    course: [0.23, 1.10]",
        "    longueur_rail: 1.15\n    course: [0.44, 1.10]",
    )
    texte = erreur_de(reglages)
    assert (
        "formats → seau_d : à l'étape c) de la prise double, la face de la préhension irait à"
        in (texte)
    )
    assert "0.4375 m, sous le bas de sa course (0.44 m)" in texte


def test_reglages_du_remplissage():
    r = REMPLISSAGE
    # Tâche 34 quater : recul pour l'agitateur à y 0,40 (31/10 ; avant : 0,375). Tâche 19 ter :
    # vidage par la griffe à y 0,42, bord du seau ≤ 0,68 au poste, spray min(0,50 ; 0,68 − h).
    assert (r.poste_y, r.dosage_y, r.ecarte_y, r.pose_y) == (0.135, 0.155, 0.40, 0.50)
    assert r.vidage_y == 0.42 and MACHINE.griffe.seau_remplissage == (0.925, 0.42)
    assert r.verrous.poste_bord_max_z == 0.68 and r.verrous.spray_bord_max_z == 0.68
    assert MACHINE.axes["plateau_z"].course == (0.175, 0.575)
    assert MACHINE.axes["barres"].course == (0.1195, 0.305)
    # Tâche 35 bis : plus de règle des anneaux du fût (31/10).
    assert not hasattr(r.verrous, "anneaux_y")
    assert r.verrous.joues_barres == (0.235, 0.255) and r.verrous.joues_plateau_max_z == 0.48
    assert (r.verrous.barres_ouvertes_au_dessus_z, r.verrous.barres_ouvertes_min) == (0.515, 0.29)
    assert r.formats["seau_b"].pose_plateau_z == 0.5125
    assert r.couvercles.plateau_z == 0.459 and r.inspection.plateau_z == 0.575
    assert r.prise_double.traction_max_par_barre_n == 35
    # Tâche 34 ter : barres à l'approche (hw 0,225) avant la pose ; prise double a) à i).
    assert r.pose_seau.barres_approche_hw_m == 0.225
    assert (r.prise_double.descente_plateau_m, r.prise_double.descente_tete_m) == (0.05, 0.028)
    assert r.prise_double.remontee_plateau_m == 0.028
    # Tâche 34 bis : pousseur rentré à son zéro (côté fût), course 0,325 ; bout du chariot à
    # 0,40 de l'axe. Tâche 35 bis : bande du haut, plateau à 0,4985 (0,496 à 0,501) ; règle 14.
    assert r.pousseur_rentre_m == 0 and MACHINE.axes["pousseur"].course == (0.0, 0.325)
    assert r.verrous.bout_y_m == 0.40
    assert {file.pousseur_m for file in r.rangement.files.values()} == {0.325}
    bande = r.rangement.bande_haut
    assert bande is not None and (bande.y, bande.plateau_z) == (0.215, 0.4985)
    assert bande.plateau_plage_z == (0.496, 0.501)
    assert r.couvercles.y_demi_tour_griffe_min == 0.515
    # Les 6 axes sur la carte n° 2 (dont les 2 barres, tâche 34 quater), les axes d'exemple sur
    # la n° 3.
    axes = ("remplissage_y", "barres", "barre_allee", "plateau_a")
    assert {MACHINE.axes[nom].carte for nom in axes} == {"chariot"}
    assert MACHINE.axes["barre_allee"].course == MACHINE.axes["barres"].course
    assert (r.barres.origine_hw_m, r.barres.origine_allee_hw_m) == (0.309, 0.306)
    assert r.barres.ecart_max_m == 0.001
    assert MACHINE.axes["exemple_x"].carte == "mycelium_lavage"


def test_un_format_sans_reglage_du_remplissage_est_refuse(reglages):
    remplacer(
        reglages / "machine.yaml",
        "    seau_d: {pose_plateau_z: 0.4625, centrage_hw_m: 0.128}\n",
        "",
    )
    assert "remplissage : il faut « formats → seau_d »" in erreur_de(reglages)


def test_une_file_hors_de_la_course_est_refusee(reglages):
    remplacer(reglages / "machine.yaml", "file_3: {y: 0.785", "file_3: {y: 0.95")
    assert "remplissage → rangement → files → file_3 → y : 0.95 hors de la course" in erreur_de(
        reglages
    )


def test_les_barres_restent_sous_les_joues_pendant_la_pose(reglages):
    remplacer(
        reglages / "machine.yaml", "barres_approche_hw_m: 0.225", "barres_approche_hw_m: 0.24"
    )
    assert "pose_seau → barres_approche_hw_m : sous les joues" in erreur_de(reglages)


def test_la_prise_double_reste_sous_l_approche(reglages):
    # Seau C : lèvre 0,1475 + 3 mm, + 1,5 cm au lâcher = 0,1655 : refusé si l'approche est à 0,16.
    remplacer(
        reglages / "machine.yaml", "barres_approche_hw_m: 0.225", "barres_approche_hw_m: 0.16"
    )
    assert "formats → seau_c : pendant la prise double, les barres iraient" in erreur_de(reglages)


def test_le_plateau_d_approche_reste_dans_la_course(reglages):
    remplacer(reglages / "machine.yaml", "plateau_sous_pose_m: 0.05", "plateau_sous_pose_m: 0.30")
    assert "plateau d'approche de la pose" in erreur_de(reglages)


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


def test_plus_de_regle_des_anneaux_du_fut():
    """Tâche 35 bis : la règle des anneaux est périmée (tôle fixe à x 0,655) ; chariot à
    y 0,215 plateau haut : permis, et il roule plateau haut."""
    haut = POSTE.avec(z=0.575)
    for y in (0.135, 0.215, 0.25, 0.50, 0.70):
        assert REGLES.refus_pose(haut.avec(y=y), PERMIS) is None
    assert REGLES.refus_mouvement(haut, haut.avec(y=0.70), PERMIS) is None
    assert REGLES.refus_mouvement(haut.avec(y=0.70), haut.avec(y=0.215), PERMIS) is None


def test_les_2_barres_ont_la_meme_course(reglages):
    remplacer(
        reglages / "machine.yaml",
        "    longueur_rail: 0.306\n    course: [0.1195, 0.305]",
        "    longueur_rail: 0.306\n    course: [0.12, 0.305]",
    )
    assert "barre_allee a la même course que barres" in erreur_de(reglages)


def test_origine_de_la_barre_cote_allee_au_dela_de_sa_course(reglages):
    remplacer(reglages / "machine.yaml", "origine_allee_hw_m: 0.306", "origine_allee_hw_m: 0.30")
    assert "origine_allee_hw_m : au-delà de la course de barre_allee" in erreur_de(reglages)


def test_regle_2_barres_entre_les_joues():
    pose = POSTE.avec(y=0.50, barres=0.245)
    assert REGLES.refus_pose(pose.avec(z=0.48), PERMIS) is None
    assert "joues de l'élévateur" in REGLES.refus_pose(pose.avec(z=0.49), PERMIS)
    # Fermer les barres plateau à 0,5125 (seau B) traverse les joues : refusé.
    depart = POSTE.avec(y=0.50, z=0.5125)
    assert "joues" in REGLES.refus_mouvement(depart, depart.avec(barres=0.1195), PERMIS)
    # Vérifiée pour chaque barre : la barre côté allée seule entre les joues (0,2355, la barre
    # côté mur à 0,2345, écart permis de 1 mm).
    seule = POSTE.avec(y=0.50, barres=0.2345, barre_allee=0.2355)
    assert REGLES.refus_pose(seule.avec(z=0.48), PERMIS) is None
    refus = REGLES.refus_pose(seule.avec(z=0.49), PERMIS)
    assert refus is not None and "barre côté allée à 0,2355" in refus


def test_ecart_entre_les_2_barres_refuse():
    # Les 2 barres bougent ensemble : « barres » seul les met au même hw.
    assert POSTE.avec(barres=0.20).barre_allee == 0.20
    # 1 mm d'écart : permis ; plus : refusé, et plus rien ne bouge (prise d'origine).
    assert REGLES.refus_pose(POSTE.avec(barre_allee=0.299), PERMIS) is None
    ecartees = POSTE.avec(barre_allee=0.298)
    refus = REGLES.refus_pose(ecartees, PERMIS)
    assert refus is not None and "écartées de 2.0 mm" in refus and "prise d'origine" in refus
    assert "écartées" in REGLES.refus_mouvement(ecartees, ecartees.avec(barres=0.30), PERMIS)
    assert "écartées" in REGLES.refus_mouvement(ecartees, POSTE.avec(y=0.20), PERMIS)


def test_regle_3_barres_ouvertes_au_dessus_de_0_515():
    pose = POSTE.avec(y=0.50)
    assert REGLES.refus_pose(pose.avec(z=0.5125, barres=0.1195), PERMIS) is None
    assert "barres ouvertes" in REGLES.refus_pose(pose.avec(z=0.52, barres=0.20), PERMIS)
    assert REGLES.refus_pose(pose.avec(z=0.575, barres=0.29), PERMIS) is None
    # Les 2 barres ouvertes : la barre côté allée à 0,2895 suffit pour refuser.
    allee = pose.avec(z=0.575, barres=0.2905, barre_allee=0.2895)
    assert "elles sont à 0,2895" in REGLES.refus_pose(allee, PERMIS)


def test_regle_12_poussee_a_toute_hauteur():
    """Poussée à 0,4985 (bande du haut) permise barres ouvertes et bras de fermeture rangé,
    refusée sinon ; plateau au plus 0,575 (sa course)."""
    sorti = POSTE.avec(y=0.215, z=0.4985, pousseur=0.325)
    assert REGLES.refus_pose(sorti, PERMIS) is None
    assert REGLES.refus_pose(sorti.avec(z=0.175), PERMIS) is None
    assert REGLES.refus_pose(sorti.avec(z=0.575), PERMIS) is None
    assert "hors de sa course" in REGLES.refus_pose(sorti.avec(z=0.58), PERMIS)
    # Barres pas ouvertes (une seule suffit) : refusé.
    refus = REGLES.refus_pose(sorti.avec(barres=0.2905, barre_allee=0.2895), PERMIS)
    assert refus is not None and "pousseur sorti : seulement barres ouvertes" in refus
    assert "pousseur sorti" in REGLES.refus_pose(sorti.avec(z=0.175, barres=0.25), PERMIS)
    # Bras de fermeture (galet) pas rangé, ou pas connu : refusé, même plateau en bas.
    for bras, etat in ((False, "pas rangé"), (None, "pas connu")):
        contexte = Contexte(True, None, bras)
        assert etat in REGLES.refus_pose(sorti.avec(z=0.175), contexte)
    # Le plateau monte et descend pousseur sorti (plusieurs seaux à la suite).
    assert REGLES.refus_mouvement(sorti, sorti.avec(z=0.30), PERMIS) is None


def test_le_pousseur_rentre_a_son_zero_et_pousse_vers_le_stockage():
    banc = Banc()
    banc.jouer(lambda: banc.remplissage.geste_plateau(0.25))
    # Sortir le pousseur plateau à 0,25 : permis (règle 12), le plateau reste où il est.
    banc.jouer(lambda: banc.remplissage.geste_pousseur(0.325))
    assert (banc.pose.z, banc.pose.pousseur) == (0.25, 0.325)
    # Barres fermées : elles s'ouvrent avant que le pousseur sorte.
    banc.jouer(lambda: banc.remplissage.geste_pousseur(0.0))
    banc.jouer(lambda: banc.remplissage.geste_barres(0.20))
    banc.jouer(lambda: banc.remplissage.geste_pousseur(0.325))
    assert banc.pas()[-2:] == ["barres ouvertes", "pousseur à 0,325"]
    assert (banc.pose.z, banc.pose.pousseur) == (0.25, 0.325)
    # Monter le plateau : le pousseur rentre d'abord à son zéro.
    banc.jouer(lambda: banc.remplissage.geste_plateau(0.30))
    assert banc.pas()[-2:] == ["pousseur rentré", "plateau à 0,3"]
    assert (banc.pose.z, banc.pose.pousseur) == (0.30, 0.0)


def test_regle_5_bras_du_galet():
    pose = POSTE.avec(y=0.50, z=0.30)
    assert "bras du galet pas connu" in REGLES.refus_pose(pose, Contexte(chariot_fut_en_place=True))
    assert "pas rangé" in REGLES.refus_pose(pose, Contexte(True, None, False))
    assert REGLES.refus_pose(pose.avec(z=0.26), Contexte(chariot_fut_en_place=True)) is None
    assert REGLES.refus_bras_galet(pose) is not None
    assert REGLES.refus_bras_galet(pose.avec(z=0.25)) is None


def test_regle_6_bras_du_spray():
    pose = POSTE.avec(y=0.50, z=0.43, barres=0.30)
    # Seau A (h 0,25) : plateau ≤ min(0,50 ; 0,68 − 0,25) = 0,43 (0,71 avant l'agitateur fixe).
    assert REGLES.refus_bras_spray(pose, 0.25) is None
    assert "plateau ≤ 0,43" in REGLES.refus_bras_spray(pose.avec(z=0.44), 0.25)
    # Petit seau (h 0,15) : 0,50 au plus.
    assert "plateau ≤ 0,5" in REGLES.refus_bras_spray(pose.avec(z=0.51), 0.15)
    assert "entraxe" in REGLES.refus_bras_spray(pose.avec(barres=0.25), 0.25)
    # Entraxe = somme des 2 barres.
    assert REGLES.refus_bras_spray(pose.avec(barres=0.25, barre_allee=0.2505), 0.25) is None
    assert "0,4995 d'entraxe" in REGLES.refus_bras_spray(
        pose.avec(barres=0.25, barre_allee=0.2495), 0.25
    )
    contexte = Contexte(True, None, True, bras_spray_sorti=True, hauteur_seau=0.25)
    assert "bras du spray" in REGLES.refus_pose(pose.avec(z=0.44), contexte)


def test_regle_7_chariot_du_fut_absent():
    absent = Contexte(chariot_fut_en_place=False, refus_mycelium=None, bras_galet_range=True)
    # Bout du chariot à 0,40 de l'axe : axe du plateau à y ≤ 0,875 − 0,40 = 0,475.
    assert REGLES.refus_pose(POSTE.avec(y=0.475), absent) is None
    for y in (0.48, 0.50, 0.785):
        refus = REGLES.refus_pose(POSTE.avec(y=y), absent)
        assert refus is not None and "chariot du fût pas en place" in refus
        assert "axe du plateau ≤ 0,475" in refus
    assert REGLES.refus_pose(POSTE.avec(y=0.785), PERMIS) is None


def test_regle_8_manivelle_en_bas_pres_du_poste():
    refuse = Contexte(True, "manivelle du mycélium à 0°", True)
    # Rouler près du poste : refusé ; loin du poste (0,50 → 0,785) : permis.
    assert "manivelle du mycélium" in REGLES.refus_mouvement(POSTE, POSTE.avec(y=0.40), refuse)
    # Recul à y 0,40 : à 0,39, le chariot est encore sous le bocal.
    recule = POSTE.avec(y=0.40)
    assert REGLES.refus_mouvement(recule, recule.avec(y=0.50), refuse) is None
    assert "manivelle du mycélium" in REGLES.refus_mouvement(recule, POSTE.avec(y=0.39), refuse)
    loin = POSTE.avec(y=0.50)
    assert REGLES.refus_mouvement(loin, loin.avec(y=0.785), refuse) is None
    # Le plateau ne monte près du poste que manivelle en bas (dosage compris) ; au vidage, si.
    au_dosage = POSTE.avec(y=0.155)
    assert "le plateau ne monte pas près du poste" in REGLES.refus_mouvement(
        au_dosage, au_dosage.avec(z=0.53), refuse
    )
    assert REGLES.refus_mouvement(au_dosage, au_dosage.avec(z=0.53), PERMIS) is None
    au_vidage = POSTE.avec(y=0.42)
    assert REGLES.refus_mouvement(au_vidage, au_vidage.avec(z=0.53), refuse) is None


def test_regle_8_bord_du_seau_au_poste():
    # Au poste (y 0,135) : bord du seau ≤ 0,68 TOUJOURS. Seau A (h 0,25) : plateau ≤ 0,43.
    seau_a = replace(PERMIS, hauteur_seau=0.25)
    assert REGLES.refus_pose(POSTE.avec(z=0.43), seau_a) is None
    texte = REGLES.refus_pose(POSTE.avec(z=0.44), seau_a)
    assert "bord du seau ≤ 0,68 toujours (il serait à 0,69)" in texte
    # Au dosage (y 0,155), le bord monte à 0,78 ; au vidage aussi.
    assert REGLES.refus_pose(POSTE.avec(y=0.155, z=0.53), seau_a) is None
    assert REGLES.refus_pose(POSTE.avec(y=0.42, z=0.53), seau_a) is None
    # Du dosage au poste, plateau à la hauteur du dosage : refusé.
    assert "bord du seau" in REGLES.refus_mouvement(
        POSTE.avec(y=0.155, z=0.53), POSTE.avec(z=0.53), seau_a
    )
    # Sans seau sur le plateau : le plateau seul (≤ 0,575) est toujours sous 0,68.
    assert REGLES.refus_pose(POSTE.avec(z=0.575), PERMIS) is None


def test_regle_9_descente_de_la_prehension():
    assert REGLES.refus_descente_prehension(POSTE, True) is None
    assert "barres ouvertes" in REGLES.refus_descente_prehension(POSTE.avec(barres=0.2), True)
    allee = POSTE.avec(barres=0.2905, barre_allee=0.2895)
    assert "barres ouvertes" in REGLES.refus_descente_prehension(allee, True)
    assert "micropore" in REGLES.refus_descente_prehension(POSTE, None)
    # Au-dessus du chariot : près de son axe en x, entre y − 0,40 et y + 0,40 (EXEMPLES).
    x = REMPLISSAGE.axe_x
    assert REGLES.au_dessus_du_chariot(x, 0.50, POSTE.avec(y=0.50))
    assert not REGLES.au_dessus_du_chariot(x + 0.30, 0.50, POSTE.avec(y=0.50))
    assert not REGLES.au_dessus_du_chariot(x, 0.95, POSTE.avec(y=0.50))
    assert REGLES.au_dessus_du_chariot(x, 0.95, None)  # chariot qui bouge : tout son rail


def test_une_pose_deja_interdite_peut_en_sortir():
    # Après une coupure : plateau haut, une barre entre les joues. Le descendre est permis.
    perdu = POSTE.avec(y=0.30, z=0.50, barres=0.245)
    assert REGLES.refus_pose(perdu, PERMIS) is not None
    assert REGLES.refus_mouvement(perdu, perdu.avec(z=0.175), PERMIS) is None
    assert REGLES.refus_mouvement(perdu, perdu.avec(z=0.52), PERMIS) is not None


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
    # Pose 1) : barres à l'approche (0,225) et plateau d'approche (0,5125 − 0,05), sous 0,48.
    assert banc.pose == Pose(y=0.50, z=pytest.approx(0.4625), a=0.0, barres=0.225, pousseur=0.0)
    assert banc.pas() == [
        "chariot à la pose du seau vide",
        "pose 1) : barres à l'approche",
        "pose 1) : plateau d'approche",
    ]
    # Plateau haut à la pose (après l'inspection) : il descend sous les joues avant que les
    # barres les traversent, et ne remonte pas (barres fermées : pas au-dessus de 0,515).
    banc.jouer(lambda: banc.remplissage.geste_barres(0.30))
    banc.jouer(lambda: banc.remplissage.geste_plateau(0.575))
    banc.jouer(lambda: banc.remplissage.geste_aller_a_la_pose("seau_b"))
    assert banc.pas()[-3:] == [
        "plateau plus bas, pour bouger les barres",
        "pose 1) : barres à l'approche",
        "pose 1) : plateau d'approche",
    ]
    assert banc.etat.mouvements[-3].axes["plateau_z"][1] == 0.48
    # Seau B posé (plateau au contact, 0,5125) : centrage puis barres ouvertes ; elles ne
    # repassent les joues qu'après la descente du plateau sous 0,48, qui remonte ensuite.
    banc.jouer(lambda: banc.remplissage.geste_plateau(0.5125))
    banc.remplissage.seau = SeauPlateau("seau_b", "S1", angle_anse=0.0)
    banc.jouer(banc.remplissage.geste_centrer)
    assert banc.pas()[-4:] == [
        "centrer le seau (barres au contact)",
        "plateau plus bas, pour bouger les barres",
        "barres ouvertes",
        "plateau remonté",
    ]
    assert (banc.pose.barres, banc.pose.z) == (0.30, 0.5125)


def test_ramener_au_vidage_puis_ranger():
    banc = Banc()
    remplissage = banc.remplissage
    banc.jouer(lambda: remplissage.geste_aller_a_la_pose("seau_a"))
    remplissage.seau = SeauPlateau("seau_a", "S1", angle_anse=12.0)
    banc.jouer(remplissage.geste_ramener_au_vidage)
    # La griffe vide le seau à y 0,42 (agitateur fixe), bord du seau à 0,78.
    assert (banc.pose.y, banc.pose.z) == (0.42, pytest.approx(0.53))
    # Plus de règle des anneaux : le chariot roule plateau haut.
    assert "plateau en bas" not in banc.pas()
    assert remplissage.seau_au_vidage()
    # Le seau tourne pendant les versements, puis revient à l'angle de l'anse (modulo 90°).
    remplissage.tourner_seau(True)
    assert not remplissage.seau_au_vidage()
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
    # Les files 2 et 3 (0,500 et 0,785) sont refusées au-delà de 0,475 sans le chariot du fût ;
    # la file 1 passe.
    remplissage.seau = SeauPlateau("seau_a", "S1", angle_anse=0.0)
    with pytest.raises(ErreurEtape, match="axe du plateau ≤ 0,475"):
        banc.jouer(lambda: remplissage.geste_ranger("file_3"))
    assert banc.pose.y == 0.135
    with pytest.raises(ErreurEtape, match="axe du plateau ≤ 0,475"):
        banc.jouer(lambda: remplissage.geste_ranger("file_2"))
    assert banc.pose.y == 0.135
    banc.chariot.seau_pose = True
    banc.jouer(lambda: remplissage.geste_ranger("file_1"))
    assert banc.pose.y == 0.215 and remplissage.seau is None


def test_ranger_en_haut_dans_l_ordre():
    """Bande du haut : a) bras rangé ; b) barres ouvertes ; c) y 0,215 ; d) plateau 0,4985 ;
    e) poussée ; f) pousseur rentré, plateau redescendu."""
    banc = Banc()
    remplissage = banc.remplissage
    banc.jouer(lambda: remplissage.geste_aller_a_la_pose("seau_a"))
    remplissage.seau = SeauPlateau("seau_a", "S1", angle_anse=0.0)
    banc.jouer(lambda: remplissage.geste_barres(0.125))
    banc.chariot.seau_pose, banc.chariot.contenu_kg = True, 6.0
    banc.jouer(remplissage.geste_ranger_en_haut)
    assert banc.pas()[-7:] == [
        "barres ouvertes",
        "c) chariot à la bande du haut",
        "pesée du seau plein",
        "d) plateau à la hauteur de la bande du haut",
        "e) le pousseur pousse le seau sur la bande du haut",
        "f) pousseur rentré",
        "plateau en bas",
    ]
    # La poussée part plateau à 0,4985 (le pas d'avant), chariot à y 0,215.
    plateau, poussee = banc.etat.mouvements[-4], banc.etat.mouvements[-3]
    assert plateau.axes["plateau_z"][1] == pytest.approx(0.4985)
    assert set(poussee.axes) == {"pousseur"} and poussee.axes["pousseur"][1] == 0.325
    assert banc.pose.y == 0.215
    assert remplissage.seau is None and banc.photos == ["seau S1 rangé en bande_haut"]
    assert (banc.pose.z, banc.pose.pousseur) == (0.175, 0.0)


def test_ranger_en_haut_refuse():
    # a) Bras de fermeture pas rangé : rien ne bouge.
    banc = Banc(bras_galet_range=lambda: None)
    banc.remplissage.seau = SeauPlateau("seau_a", "S1", angle_anse=0.0)
    with pytest.raises(ErreurEtape, match="bras de fermeture pas connu"):
        banc.jouer(banc.remplissage.geste_ranger_en_haut)
    assert banc.etat.mouvements == []
    # Plateau hors de 0,496-0,501 pour la bande du haut : refusé.
    remplissage = Banc().remplissage
    bande = POSTE.avec(y=0.215)
    assert remplissage.refus_poussee_bande(bande.avec(z=0.4985)) is None
    assert remplissage.refus_poussee_bande(bande.avec(z=0.496)) is None
    for z in (0.4955, 0.5015, 0.175):
        assert "entre 0,496 et 0,501" in remplissage.refus_poussee_bande(bande.avec(z=z))
    assert "la bande du haut est à y 0,215" in remplissage.refus_poussee_bande(
        bande.avec(y=0.50, z=0.4985)
    )


def test_plateau_de_la_bande_hors_de_sa_plage_refuse(reglages):
    remplacer(reglages / "machine.yaml", "plateau_z: 0.4985,", "plateau_z: 0.4950,")
    assert "bande_haut → plateau_z : 0.495 hors de plateau_plage_z" in erreur_de(reglages)


def test_ranger_dans_la_file_avec_une_cale():
    banc = Banc()
    remplissage = banc.remplissage
    remplissage.seau = SeauPlateau("seau_c", "S1", angle_anse=0.0)
    banc.jouer(lambda: remplissage.geste_ranger("file_2", 0.175))
    assert banc.etat.mouvements[-2].axes["pousseur"][1] == 0.175


def test_regle_14_demi_tours_de_la_griffe():
    """Mode couvercles : la tête de la griffe ne tourne que chariot à y ≥ 0,515 ; il ne revient
    à y 0,50 qu'après."""
    banc = Banc()
    remplissage = banc.remplissage
    # Hors du mode couvercles : pas de condition.
    assert remplissage.refus_demi_tour_griffe() is None
    banc.jouer(remplissage.geste_mode_couvercles)
    assert banc.pose.y == 0.50
    refus = remplissage.refus_demi_tour_griffe()
    assert refus is not None and "y ≥ 0,515" in refus

    class Griffe:
        verrou_chariot = None
        tourne = False

        def tete_tourne(self) -> bool:
            return self.tourne

    griffe = Griffe()
    remplissage.brancher_griffe(griffe)  # type: ignore[arg-type]
    depart = PoseGriffe(0.5, 0.68, 1.075, 0.0, 0.0)
    assert "y ≥ 0,515" in griffe.verrou_chariot(depart, depart.avec(a=180.0))
    # Sans rotation de la tête : pas concerné.
    assert griffe.verrou_chariot(depart, depart.avec(z=1.10)) is None
    banc.jouer(remplissage.geste_degager_griffe)
    assert banc.pose.y == pytest.approx(0.515)
    assert griffe.verrou_chariot(depart, depart.avec(a=180.0)) is None
    # Retour à y 0,50 refusé tant que la tête tourne, permis après.
    griffe.tourne = True
    with pytest.raises(ErreurEtape, match="règle 14"):
        banc.jouer(remplissage.geste_revenir_au_retourneur)
    griffe.tourne = False
    banc.jouer(remplissage.geste_revenir_au_retourneur)
    assert remplissage.chariot_en_place()


def test_alarme_des_barres_pendant_le_centrage():
    banc = Banc()
    remplissage = banc.remplissage
    banc.jouer(lambda: remplissage.geste_aller_a_la_pose("seau_a"))
    remplissage.seau = SeauPlateau("seau_a", "S1", angle_anse=0.0)
    remplissage.lancer(remplissage.geste_centrer)
    banc.temps[0] += 0.5
    # ALM d'une seule barre (chacune a son pilote) : le geste s'arrête, elle est nommée.
    banc.chariot.alarmes_barres_actives = ["côté allée"]
    with pytest.raises(
        ErreurEtape, match="alarme du pilote de la barre côté allée pendant .* \\(elle force\\)"
    ) as erreur:
        banc.finir()
    assert "force" in erreur.value.quoi_faire
    assert banc.photos == ["alarme du pilote de la barre côté allée"]
    assert remplissage.libre()


def test_ecart_des_barres_arrete_le_geste():
    banc = Banc()
    # Une barre a bougé seule (essai à la main, pas perdus) : le chariot ne bouge plus.
    banc.etat.positions["barre_allee"] = 0.295
    with pytest.raises(ErreurEtape, match="barres écartées de 5.0 mm"):
        banc.jouer(lambda: banc.remplissage.geste_plateau(0.25))


def test_le_chariot_attend_la_manivelle_en_bas_pres_du_poste():
    banc = Banc(refus_mycelium=lambda: "manivelle du mycélium à 0°")
    with pytest.raises(ErreurEtape, match="ne roule pas près du poste"):
        banc.jouer(lambda: banc.remplissage.geste_aller(0.50))
    banc.remplissage.seau = SeauPlateau("seau_a", "S1", angle_anse=0.0)
    with pytest.raises(ErreurEtape, match="ne roule pas près du poste"):
        banc.jouer(banc.remplissage.geste_ramener_au_vidage)


def test_le_mycelium_mene_le_chariot_par_le_poste_au_dosage():
    banc = Banc()
    remplissage = banc.remplissage
    remplissage.seau = SeauPlateau("seau_a", "S1", angle_anse=0.0)
    # Le seau vide attend au vidage (y 0,42) : écarter ne bouge rien.
    banc.jouer(remplissage.geste_ramener_au_vidage)
    remplissage.ecarter()
    banc.finir()
    assert remplissage.etat() == remplissage.etat().__class__(0.42, 0.53, True)  # type: ignore[union-attr]
    # Au dosage par le poste : plateau descendu (bord 0,68), poste (spray, micropore), dosage,
    # plateau remonté (bord 0,78).
    remplissage.amener_au_dosage(0.53)
    banc.finir()
    assert (banc.pose.y, banc.pose.z, banc.pose.barres) == (0.155, 0.53, 0.30)
    assert banc.pas()[-4:] == [
        "plateau à la hauteur du poste",
        "seau au poste (spray, micropore)",
        "seau sous le bocal du mycélium",
        "plateau à la hauteur du dosage",
    ]
    assert banc.etat.mouvements[-4].axes["plateau_z"][1] == pytest.approx(0.43)
    # Retour au vidage (y 0,42), plateau où il est.
    remplissage.ecarter()
    etat = remplissage.etat()
    assert etat is not None and not etat.immobile and etat.y == 0.155
    banc.finir()
    assert (banc.pose.y, banc.pose.z) == (0.42, 0.53)


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
        # Au-dessus du chariot au poste, mais hors de la zone du porte-bocal (y ≤ 0,27 + 5,5 cm).
        prehension.lancer(lambda: prehension.geste_aller(REMPLISSAGE.axe_x, 0.35))
        while not prehension.geste_fini():
            simulation.temps += 0.25
        cible = PosePrehension(REMPLISSAGE.axe_x, 0.35, 0.60, 0.0)
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


def jouer_scenario(regler=lambda scenario: None, reglages=REGLAGES, **options):
    with Simulateur(reglages, LISTE, "remplissage") as simulation:
        scenario = remplissage_du_simulateur(simulation, **options)
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


def test_scenario_un_seau_dans_l_ordre_du_point_5():
    # Agitateur fixe (tâche 19 ter) : vidage par la griffe à y 0,42 → poste (y 0,135 : spray,
    # micropore) → dosage (y 0,155) → retour au vidage ; demi-tour du bocal chariot à y ≥ 0,40.
    textes: list[tuple[str, float]] = []

    def regler(scenario):
        executer = scenario.chariot.executer

        def noter(pas, cible):
            if "y" in pas.cibles or pas.texte == "le seau tourne (versement)":
                textes.append((pas.texte, cible.y))
            executer(pas, cible)

        scenario.chariot.executer = noter

    planning, scenario = jouer_scenario(regler)
    assert planning.fini, planning.probleme
    debut = next(i for i, (texte, _) in enumerate(textes) if texte == "retour au vidage")
    couche = [texte for texte, _ in textes[debut : debut + 5]]
    assert couche == [
        "retour au vidage",
        "le seau tourne (versement)",
        "seau au poste (spray, micropore)",
        "seau sous le bocal du mycélium",
        "retour au vidage",
    ]
    assert [y for _, y in textes[debut : debut + 5]] == pytest.approx(
        [0.42, 0.42, 0.135, 0.155, 0.42]
    )
    # Bocal retourné puis remis debout à chaque couche (4 + 2).
    assert scenario.mycelium.porte_bocal.gestes == ["tete_en_bas", "debout"] * 6


POSE_SIMPLE = [
    "pose 1) : barres à l'approche",
    "pose 1) : plateau d'approche",
    "pose : la tête descend avec le seau",
    "pose : la tête à la hauteur de pose",
    "pose 2) : le plateau monte jusqu'au contact du seau",
    "pose 3) : centrage",
]
PRISE_DOUBLE = [
    "prise double a) : lâcher (barres)",
    "prise double b) : le plateau descend",
    "prise double c) : la tête descend",
    "prise double d) : barres serrées sur la lèvre du seau du dessous",
    "prise double e) : le plateau monte jusqu'au contact du fond du seau du dessous",
    "prise double f) : la tête remonte avec le seau du haut",
    "prise double g) : lâcher (barres)",
    "prise double h) : le plateau monte",
    "prise double : centrage",
]
LACHER = "pose : barres à l'approche (lâcher)"


def poses(scenario) -> list[list]:
    """Les mouvements de chaque pose (de « pose 1) » au lâcher des barres), seau par seau."""
    tous = [
        m
        for m in scenario.chariot._etat.mouvements
        if m.position.startswith(("pose", "prise double"))
    ]
    resultat, courant = [], []
    for mouvement in tous:
        courant.append(mouvement)
        if mouvement.position == LACHER:
            resultat.append(courant)
            courant = []
    return resultat


def verifier_prise_double(mouvements, format: str) -> None:
    """Ordre exact de la pose puis de a) à i), plateau au contact (Hc ≈ 3 cm sous un seau seul),
    barres toujours sous les joues de l'élévateur (0,235)."""
    assert [m.position for m in mouvements] == POSE_SIMPLE + PRISE_DOUBLE + [LACHER]
    plateau = {m.position: m.axes["plateau_z"][1] for m in mouvements if "plateau_z" in m.axes}
    hc = REMPLISSAGE.formats[format].pose_plateau_z - 0.03
    assert plateau["pose 2) : le plateau monte jusqu'au contact du seau"] == pytest.approx(hc)
    assert plateau["prise double b) : le plateau descend"] == pytest.approx(hc - 0.05)
    assert plateau[PRISE_DOUBLE[4]] == pytest.approx(hc - 0.028)
    assert plateau["prise double h) : le plateau monte"] == pytest.approx(hc)
    # Barres : approche, centrage, + 1,5 cm, lèvre (Ø haut + 6 mm), + 1,5 cm, centrage, approche.
    barres = [m.axes["barres"][1] for m in mouvements if "barres" in m.axes]
    centrage = REMPLISSAGE.formats[format].centrage_hw_m + 0.002
    levre = max(MACHINE.griffe.formats[format].rayon_haut + 0.003, 0.1195)  # type: ignore[union-attr]
    assert barres == pytest.approx(
        [0.225, centrage, centrage + 0.015, levre, levre + 0.015, centrage, 0.225]
    )
    assert max(barres) < 0.235
    # Les barres traversent les joues à pose 1), plateau ≤ 0,48 (avant que la tête descende) ;
    # ensuite, plus aucune traversée : hw reste sous 0,235.
    assert mouvements[0].axes["barres"][1] == 0.225
    for m in mouvements[1:]:
        if "barres" in m.axes:
            assert max(m.axes["barres"]) < 0.235


def test_pose_et_prise_double_dans_l_ordre():
    planning, scenario = jouer_scenario()
    assert planning.fini, planning.probleme
    seau_a, seau_b = poses(scenario)
    verifier_prise_double(seau_a, "seau_a")
    # Seau B seul : pose 1) à 3), barrière libre, la tête lâche, les barres reviennent à
    # l'approche ; le plateau est resté au contact (0,5125).
    assert [m.position for m in seau_b] == POSE_SIMPLE + [LACHER]
    contact = [m for m in seau_b if m.position == POSE_SIMPLE[4]][0]
    assert contact.axes["plateau_z"][1] == pytest.approx(0.5125)


def test_prise_double_d_un_seau_b():
    """Seau B : pose à 0,5125, au-dessus des joues. Les barres les traversent avant la pose,
    plateau ≤ 0,48 : la prise double n'est plus bloquée."""
    simule = REGLAGES.simulateur
    assert simule.remplissage is not None
    seaux = [
        seau.model_copy(update={"prise_double": seau.format == "seau_b"})
        for seau in simule.remplissage.seaux
    ]
    reglages = REGLAGES.model_copy(
        update={
            "simulateur": simule.model_copy(
                update={"remplissage": simule.remplissage.model_copy(update={"seaux": seaux})}
            )
        }
    )
    planning, scenario = jouer_scenario(reglages=reglages)
    assert planning.fini, planning.probleme
    etapes = [ligne.etape for ligne in planning.lignes if ligne.module == "remplissage"]
    assert etapes.count("rendre_le_seau_du_dessus") == 1
    seau_a, seau_b = poses(scenario)
    assert [m.position for m in seau_a] == POSE_SIMPLE + [LACHER]
    verifier_prise_double(seau_b, "seau_b")
    assert scenario.plan.faits == ["S0101", "S0102"]


def test_le_contact_est_lu_par_la_balance():
    pas = []

    def regler(scenario):
        executer = scenario.chariot.executer

        def espion(un_pas, cible):
            pas.append(un_pas)
            executer(un_pas, cible)

        scenario.chariot.executer = espion

    planning, _ = jouer_scenario(regler)
    assert planning.fini, planning.probleme
    contacts = [p for p in pas if p.contact_kg is not None]
    assert [p.texte for p in contacts] == [POSE_SIMPLE[4], PRISE_DOUBLE[4], POSE_SIMPLE[4]]
    assert all(p.contact_kg == REMPLISSAGE.pose_seau.contact_kg for p in contacts)
    assert all(p.vitesse == "contact" for p in contacts)


def test_pose_sans_contact_du_plateau():
    def regler(scenario):
        scenario.chariot.sans_contact = True

    planning, _ = jouer_scenario(regler)
    assert not planning.fini
    assert "le plateau n'a pas touché le seau tenu par la tête" in planning.probleme


def test_pose_refusee_micropore_pas_rentre():
    """Pendant la pose, la tête descend barres à l'approche (exception à la règle 9), mais
    jamais tête du micropore sortie."""
    planning, scenario = jouer_scenario(micropore_rentre=lambda: False)
    assert not planning.fini and "tête du micropore rentrée" in planning.probleme
    assert not any(m.position.startswith("pose :") for m in scenario.chariot._etat.mouvements)


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
                    "entrees": {
                        "barriere_remplissage": "0",
                        "alarme_barre_mur": "1",
                        "alarme_barre_allee": "2",
                    },
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
    # Au poste ; barres à hw 0,30 : côté mur 0,30 − 0,309 = −9 mm pour la carte (B), côté allée
    # 0,30 − 0,306 = −6 mm (X).
    carte.positions.update(X=-6.0, Y=135.0, Z=175.0, A=0.0, B=-9.0, C=0.0)
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
        assert chariot.position() == Pose(
            0.135, 0.175, 0.0, pytest.approx(0.30), 0.0, pytest.approx(0.30)
        )
        assert chariot.barriere_coupee() is False
        assert chariot.alarmes_barres() == []
        carte.entrees.add("0")
        attendre(lambda: chariot.barriere_coupee() is True)
        # Centrage en position : les 2 barres à 0,125 dans le même mouvement (côté mur −184 mm,
        # côté allée −181 mm pour la carte), sans sortie.
        cible = chariot.position().avec(barres=0.125)
        chariot.executer(Pas("centrer", {"barres": 0.125}), cible)
        attendre(chariot.fini)
        assert carte.positions["B"] == pytest.approx(-184.0)
        assert carte.positions["X"] == pytest.approx(-181.0)
        jog = [ligne for ligne in carte.lignes_recues if ligne.startswith("$J=")][-1]
        assert "B-184" in jog and "X-181" in jog
        assert chariot.position().barre_allee == pytest.approx(0.125)
        assert not carte.sorties
        # Alarme ALM du pilote de chaque barre, lue dans « Pn: ».
        carte.entrees.add("2")
        attendre(lambda: chariot.alarmes_barres() == ["côté allée"])
        carte.entrees.add("1")
        attendre(lambda: chariot.alarmes_barres() == ["côté mur", "côté allée"])
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
