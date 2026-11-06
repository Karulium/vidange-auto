"""Griffe : réglages, règles de position, doses, gestes au simulateur, bras sur le faux FluidNC."""

import logging
import math
import threading
import time

import pytest

from vidange.chef import ErreurEtape
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.griffe import BrasFluidnc, Contexte, Doses, Pas, Pose, Prise, ReglesGriffe
from vidange.griffe.doses import ouverture_pour_volume, volume_l
from vidange.griffe.module import module_griffe
from vidange.griffe.simulation import FausseForce, griffe_du_simulateur
from vidange.poste_fut.poste import QUOI_FAIRE_PERTE
from vidange.registre import Registre
from vidange.reglages import EvenementSimule, charger_reglages
from vidange.simulateur import Simulateur
from vidange.simulateur.outil import main as simulateur

from .conftest import DOSSIER_PI
from .test_fluidnc_liaison import DELAI, reglages_essai
from .test_reglages import erreur_de, remplacer

LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
GRIFFE = MACHINE.griffe
assert GRIFFE is not None
REGLES = ReglesGriffe(MACHINE)
PRODUCTION = Contexte()
# Au-dessus du centre du fût, à la hauteur des trajets, tête bloquée, godet fermé.
HAUT = Pose(x=0.29, y=0.57, z=1.29, a=0.0, b=0.0)


# ---------------------------------------------------------------- réglages


def test_reglages_de_la_griffe_du_depot():
    assert GRIFFE.exemple
    assert MACHINE.axes["griffe_a"].unite == "deg"
    assert set(GRIFFE.formats) == {"seau_a", "seau_b", "seau_c", "seau_d"}
    assert GRIFFE.formats["seau_b"].tassement_bas_max_sous_bord_m == 0.08


def test_reglages_de_la_griffe_verifies(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "format_par_defaut: seau_a", "format_par_defaut: seau_99l")
    remplacer(machine, "seau_remplissage: [0.925, 0.42]", "seau_remplissage: [0.70, 0.42]")
    message = erreur_de(reglages)
    assert "format_par_defaut : « seau_99l » absent de formats" in message
    assert "seau_remplissage : mât à x 0.7, il faut x ≥ trajet → mat_x_min_pour_y" in message


def test_table_des_volumes_verifiee(reglages):
    remplacer(reglages / "machine.yaml", "      - [2.0, 2.4, 2.7]", "      - [0.2, 0.3, 0.4]")
    assert "litres : le volume doit grandir avec l'ouverture" in erreur_de(reglages)


def test_hauteurs_de_la_griffe_dans_la_course(reglages):
    remplacer(reglages / "machine.yaml", "      haut_z: 0.775", "      haut_z: 1.20")
    message = erreur_de(reglages)
    assert "griffe → formats → seau_b (vidage) : axes à z 1.43 m, hors de la course" in message


def test_axe_de_la_griffe_manquant(reglages):
    remplacer(reglages / "machine.yaml", "  chariot_y:\n", "  chariot_y:\n    unite: deg\n")
    assert "griffe : l'axe « chariot_y » doit être en « m », avec sa carte" in erreur_de(reglages)


def test_axe_tournant_dans_son_tour(reglages):
    remplacer(reglages / "machine.yaml", "course: [-370, 370]", "course: [-500, 370]")
    assert "la course (-500 à 370 deg) sort du rail (-400 à 400 deg)" in erreur_de(reglages)


# ---------------------------------------------------------------- règles


def refus(pose: Pose, contexte: Contexte = PRODUCTION) -> str | None:
    return REGLES.refus_pose(pose, contexte)


def test_rotation_selon_la_hauteur():
    assert refus(HAUT) is None and refus(HAUT.avec(a=180)) is None
    assert "orientation bloquée" in refus(HAUT.avec(a=30))
    # Entre 1,075 et 1,11 : libre godet fermé, ±45° au plus godet ouvert.
    milieu = HAUT.avec(z=1.09, a=90)
    assert refus(milieu) is None
    assert "plus de 45°" in refus(milieu.avec(b=1.0))
    assert refus(milieu.avec(a=40, b=1.0)) is None
    # En dessous de 1,075 : libre.
    assert refus(HAUT.avec(z=1.0, a=120, b=1.0)) is None


def test_godet_jamais_au_dela_de_ferme():
    assert "au-delà de « fermé »" in refus(HAUT.avec(b=-0.01))


def test_mat_en_y_godet_ouvert():
    bord = Pose(x=0.60, y=0.10, z=1.29, a=0, b=0)
    assert refus(bord) is None
    assert "godet ouvert avec le mât à y 0,1 m" in refus(bord.avec(b=1.0))


def test_agitateur_y_min_du_mat():
    # Godet fermé, bras le long du pont.
    bas = Pose(x=0.90, y=0.28, z=1.29, a=0, b=0)  # en butée haute : bande 0,295
    assert "il faut y ≥ 0,295 m" in refus(bas)
    assert refus(bas.avec(x=0.60)) is None
    # Sous la butée haute : 0,325 ; en butée haute : 0,295.
    assert refus(bas.avec(y=0.31)) is None
    assert "il faut y ≥ 0,325 m" in refus(bas.avec(y=0.31, z=1.20))
    # Caméra du dosage : refusée sous la butée, permise en butée haute.
    camera = Pose(x=1.05, y=0.39, z=1.20, a=0, b=0)
    assert "il faut y ≥ 0,395 m" in refus(camera)
    assert refus(camera.avec(z=1.29)) is None
    # Grand ouvert : 0,365 en butée haute.
    assert "il faut y ≥ 0,365 m" in refus(bas.avec(y=0.34, b=1.0))
    # Les bandes se chevauchent : la plus stricte compte (x 1,115 : 0,215 et 0,11).
    assert "il faut y ≥ 0,215 m" in refus(Pose(x=1.115, y=0.20, z=1.29, a=0, b=0))
    # Tête tournée, godet fermé : 0,295 + (0,139 − 0,111).
    tournee = Pose(x=0.80, y=0.34, z=1.0, a=90, b=0)  # sous la butée : 0,325 + 0,028
    assert "il faut y ≥ 0,353 m" in refus(tournee)
    assert refus(tournee.avec(y=0.36)) is None


def test_ouverture_du_poste_du_fut():
    # Mât à x < 0,78, axes de 1,11 à la butée : seulement près de l'axe du fût.
    assert "ouverture du poste du fût" in refus(Pose(x=0.50, y=0.60, z=1.15, a=0, b=0))
    assert refus(Pose(x=0.29, y=0.57, z=1.15, a=0, b=0)) is None
    # Au bord du cercle : 0,16 godet fermé, 0,105 grand ouvert.
    assert refus(Pose(x=0.29, y=0.57 + 0.15, z=1.15, a=0, b=0)) is None
    assert "au plus 0,105 m" in refus(Pose(x=0.29, y=0.57 + 0.12, z=1.15, a=0, b=1.0))
    # Tête tournée, godet fermé : le rayon perd (0,139 − 0,111).
    assert "ouverture du poste du fût" in refus(Pose(x=0.29, y=0.57 + 0.15, z=1.15, a=90, b=0))
    # Sous 1,11, ce sont les règles du fût.
    assert "dans le fût" in refus(Pose(x=0.29, y=0.80, z=0.5, a=0, b=0))


def test_tables_du_mat_verifiees(reglages):
    remplacer(
        reglages / "machine.yaml",
        "{x: [0.77, 0.99], y_min: [0.325",
        "{x: [0.99, 0.77], y_min: [0.325",
    )
    assert "y_min_mat → sous_butee : x du plus petit au plus grand" in erreur_de(reglages)


def test_ouverture_godet_de_l_essuyage_verifiee(reglages):
    remplacer(reglages / "machine.yaml", "ouverture_godet: 0.5", "ouverture_godet: 1.0")
    assert "ouverture_godet" in erreur_de(reglages)


def test_encombrement_de_la_tete():
    # Bras le long du pont (A = 0), raclette côté fût (−x).
    corps, raclette = REGLES.encombrement(Pose(x=1.0, y=0.5, z=1.0, a=0, b=0))
    xs, ys = [x for x, _ in corps], [y for _, y in corps]
    assert min(xs) == pytest.approx(0.914) and max(xs) == pytest.approx(1.086)
    assert min(ys) == pytest.approx(0.389) and max(ys) == pytest.approx(0.611)
    assert raclette[1] == pytest.approx((0.89, 0.5))
    # Godet ouvert : 0,165 le long du bras. Tête tournée de 90° : le bras est le long de x.
    corps, raclette = REGLES.encombrement(Pose(x=1.0, y=0.5, z=1.0, a=90, b=0.5))
    xs, ys = [x for x, _ in corps], [y for _, y in corps]
    assert min(xs) == pytest.approx(0.835) and max(xs) == pytest.approx(1.165)
    assert min(ys) == pytest.approx(0.414) and max(ys) == pytest.approx(0.586)
    assert raclette[1] == pytest.approx((1.0, 0.39))


def test_dosage_et_porte_du_spray():
    seau = Pose(x=0.90, y=0.34, z=0.98, a=0, b=0)
    assert refus(seau) is None
    assert "dosage du mycélium" in refus(seau, Contexte(dosage_en_cours=True))
    # La tête (0,086 en travers du bras) entre dans la zone de la porte, pas le mât.
    devant = Pose(x=0.14, y=0.35, z=1.29, a=0, b=0)
    porte = Contexte(porte_spray_ouverte=True)
    assert refus(devant) is None
    assert "porte du coffret du spray" in refus(devant, porte)
    assert refus(devant.avec(y=0.45), porte) is None


def test_boitier_de_la_camera_du_bocal():
    # Boîtier x 0,997-1,091 (plan de commande v230) : le bout de la tête est à 0,086 du mât côté
    # +x (bras le long du pont, raclette côté fût), donc mât à x ≤ 0,911.
    devant = Pose(x=0.91, y=0.33, z=0.98, a=0, b=0)
    assert refus(devant) is None
    assert "caméra du bocal" in refus(devant.avec(x=0.95))
    # Godet ouvert : seuls les bras (0,117) comptent tant que les joues (0,09 sous les axes) sont
    # sous le bas du boîtier (0,975), donc jusqu'à des axes à 1,065 ; plus haut, les coquilles
    # ouvertes (0,165) aussi.
    ouvert = Pose(x=0.80, y=0.38, z=1.06, a=90, b=1.0)
    assert refus(ouvert) is None
    # Le mât est hors de la bande y 0,22-0,28, mais la tête la recouvre (bras le long du pont).
    assert "caméra du bocal" in refus(Pose(x=0.95, y=0.34, z=0.98, a=0, b=0.5))
    # Bas de la tête à 1,07 ou plus : la tête passe au-dessus (haut du boîtier 1,068). Bas compté
    # à 1,077 en butée haute (0,213 sous les axes).
    assert refus(Pose(x=1.0, y=0.30, z=1.29, a=0, b=0)) is None
    assert "caméra du bocal" in refus(Pose(x=0.95, y=0.33, z=1.065 + 0.213 - 0.01, a=0, b=0))


def test_poignee_du_volet():
    # Mât au bout de sa course (y 0,83, Portique du 01/11) : même tournée, la tête (rayon balayé
    # 0,139) reste à y ≤ 0,97, sous la poignée (y ≥ 1,005).
    pres = Pose(x=0.55, y=0.83, z=1.0, a=0, b=0)
    assert refus(pres) is None
    assert refus(pres.avec(a=45)) is None
    assert "hors de la course (0,04 à 0,83)" in refus(pres.avec(y=0.884))
    # La poignée reste vérifiée (un mât plus loin, réglages d'essai).
    regles = ReglesGriffe(MACHINE)
    regles.courses["chariot_y"] = (0.04, 0.884)
    loin = Pose(x=0.55, y=0.884, z=1.0, a=0, b=0)
    assert regles.refus_pose(loin, Contexte()) is None
    assert "poignée du volet" in regles.refus_pose(loin.avec(a=45), Contexte())


def essuyage(nom_format: str, direction_deg: float) -> Pose:
    """La pose de l'essuyage du bord : raclette sur le bord du seau, godet à moitié ouvert."""
    seau = GRIFFE.formats[nom_format]
    x, y = GRIFFE.seau_remplissage
    distance = seau.rayon_haut + GRIFFE.essuyage.decalage_m
    angle = math.radians(direction_deg)
    return Pose(
        x=x + distance * math.cos(angle),
        y=y + distance * math.sin(angle),
        z=seau.haut_z + GRIFFE.essuyage.au_dessus_haut_m,
        a=direction_deg + 180 - GRIFFE.raclette_angle_deg,
        b=GRIFFE.essuyage.ouverture_godet,
    )


def test_essuyage_au_vidage_loin_du_boitier_de_la_camera():
    # Seau au vidage (y 0,42, agitateur fixe) : côté +x ne touche plus le boîtier de la caméra du
    # bocal (décision du 02/11, point 5) ; on garde le côté allée (+y).
    for nom in GRIFFE.formats:
        assert refus(essuyage(nom, 0)) is None
    assert GRIFFE.essuyage.direction_deg == 90
    for nom in GRIFFE.formats:
        assert refus(essuyage(nom, 90)) is None


def test_vidage_au_poste_du_remplissage():
    # Mât en (0,925 ; 0,42), godet grand ouvert, tête à 0° ou 180° : les 4 formats passent.
    x, y = GRIFFE.seau_remplissage
    for seau in GRIFFE.formats.values():
        z = seau.haut_z + GRIFFE.vidage.au_dessus_haut_m
        pose = Pose(x=x, y=y, z=z, a=0, b=1.0)
        assert refus(pose) is None
        assert refus(pose.avec(a=180)) is None
        # Tournée de 45°, godet ouvert : refusé ; godet fermé, la rotation reste possible.
        assert "godet ouvert au-dessus du seau" in refus(pose.avec(a=45))
        assert "godet ouvert au-dessus du seau" in refus(pose.avec(a=135))
    # Rotation godet ouvert au-dessus du seau : refusée.
    depart = Pose(x=x, y=y, z=1.0, a=0, b=1.0)
    assert "godet ouvert au-dessus du seau" in REGLES.refus_mouvement(
        depart, depart.avec(a=45), PRODUCTION
    )
    assert GRIFFE.vidage.rotation_deg == 0
    assert GRIFFE.essuyage.ouverture_godet == 0.5


def test_tete_godet_ouvert_s_elargit_sous_les_axes():
    # Boîtier de z 0,975 à 1,068, y 0,22-0,28 ; mât à y 0,40, godet grand ouvert, bras le long du
    # pont. Bas du boîtier à 0,025 sous les axes : 0,117 de chaque côté, y 0,283, dégagé. À
    # 0,05 sous les axes : 0,135, y 0,265, contre le boîtier.
    ouvert = Pose(x=0.95, y=0.40, z=1.0, a=0, b=1.0)
    assert refus(ouvert) is None
    assert "caméra du bocal" in refus(ouvert.avec(z=1.025))
    # Godet fermé : toute la tête reste à 0,117 au plus jusqu'à 0,09 sous les axes.
    assert "caméra du bocal" not in (refus(ouvert.avec(z=1.025, b=0)) or "")


def test_dans_le_fut():
    assert refus(Pose(x=0.29, y=0.57, z=0.5, a=0, b=1)) is None
    assert "au plus 0,197 m" in refus(Pose(x=0.29, y=0.80, z=0.5, a=0, b=0))
    assert "côté −x" in refus(Pose(x=0.11, y=0.57, z=0.5, a=0, b=0))
    # Mode lavage, volet relevé : pas de griffe au-dessus du fût.
    assert "volet est relevé" in refus(HAUT, Contexte(mode="lavage", volet_releve=True))


def test_bout_cote_fut():
    # Tête sous x 0,12, hors du fût : bas de la tête ≥ 0,85 (axes ≥ 1,063).
    assert "hors du fût" in refus(Pose(x=0.10, y=0.15, z=1.0, a=0, b=0))
    assert refus(Pose(x=0.10, y=0.15, z=1.07, a=0, b=0)) is None
    # Le mât est à x 0,22, mais la raclette (côté −x) va jusqu'à 0,11 ; sa tête est au-dessus
    # de la paroi du fût. Raclette côté +x : la tête reste à x ≥ 0,135.
    loin = Pose(x=0.22, y=0.24, z=1.0, a=0, b=0)
    assert "tête sous x 0,12 m au-dessus de la paroi du fût" in refus(loin)
    assert refus(loin.avec(a=180)) is None
    # Mât hors du fût, mais la tête au-dessus de sa paroi : bas ≥ 1,05.
    paroi = Pose(x=0.10, y=0.57 - 0.36, z=1.0, a=0, b=0)
    assert "au-dessus de la paroi du fût" in refus(paroi)
    assert refus(paroi.avec(z=1.29)) is None
    # Mât au-dessus de l'intérieur du fût : les règles du fût comptent (prises côté −x).
    assert refus(Pose(x=0.12, y=0.57, z=0.5, a=180, b=0)) is None


def test_trajet_jamais_en_diagonale():
    seau = Pose(x=0.95, y=0.30, z=1.29, a=0, b=0)
    assert "diagonale" in REGLES.refus_mouvement(HAUT, seau, PRODUCTION)
    # D'abord en x (mât à y ≥ 0,36), puis en y une fois le mât à x ≥ 0,86.
    milieu = HAUT.avec(x=0.95)
    assert REGLES.refus_mouvement(HAUT, milieu, PRODUCTION) is None
    assert REGLES.refus_mouvement(milieu, seau, PRODUCTION) is None
    bas = HAUT.avec(x=0.95, y=0.34)
    assert "en x avec le mât à y < 0,36" in REGLES.refus_mouvement(
        bas.avec(x=0.60), bas, PRODUCTION
    )
    dehors = Pose(x=0.70, y=0.80, z=1.29, a=0, b=0)
    assert "en y avec le mât à x < 0,86" in REGLES.refus_mouvement(
        dehors, dehors.avec(y=0.6), PRODUCTION
    )
    # Au-dessus du fût, tout est permis.
    assert REGLES.refus_mouvement(HAUT, HAUT.avec(x=0.4, y=0.45), PRODUCTION) is None


def test_mouvement_verifie_point_par_point():
    # Les deux bouts sont permis (en butée haute, puis dans le fût), mais la descente à 0,18 m
    # de l'axe du fût traverse l'ouverture du poste, où le mât ne va qu'à 0,16 m au plus.
    depart = Pose(x=0.29, y=0.75, z=1.29, a=0, b=0)
    arrivee = depart.avec(z=1.0)
    assert refus(depart) is None and refus(arrivee) is None
    assert "ouverture du poste du fût" in REGLES.refus_mouvement(depart, arrivee, PRODUCTION)
    # Pas de rotation quand le pont est au-delà de x 2,0.
    loin = Pose(x=2.0, y=0.5, z=1.0, a=0, b=0)
    assert "pont est au-delà de x 2" in REGLES.refus_mouvement(loin, loin.avec(a=10), PRODUCTION)


# ---------------------------------------------------------------- doses


def test_table_des_volumes():
    table = GRIFFE.volumes
    assert volume_l(table, 1.0, 0.02) == pytest.approx(2.8)
    assert volume_l(table, 0.5, 0.01) == pytest.approx((0.8 + 1.0 + 1.4 + 1.7) / 4)
    assert volume_l(table, 0.0, 0.0) == pytest.approx(0.3)  # hors table : le bord
    assert ouverture_pour_volume(table, 1.7, 0.02) == pytest.approx(0.6)
    assert ouverture_pour_volume(table, 99, 0.02) == 1.0


def test_densite_apprise_sur_le_fut():
    doses = Doses(GRIFFE)
    assert doses.densite() == GRIFFE.doses.densite_defaut_kg_l
    assert doses.densite("paroi") == pytest.approx(0.7 * 0.8)

    def prise(lieu, poids, volume):
        return Prise(lieu, 1.0, 0.02, 4, 0.5, 0.29, 0.57, poids, volume)

    for _ in range(GRIFFE.doses.prises_avant_apprentissage):
        doses.noter(prise("couche", 1.0, 2.0))
    assert doses.densite() == pytest.approx(0.5)
    assert doses.densite("fond") == pytest.approx(0.5 * 0.7)
    for _ in range(GRIFFE.doses.prises_avant_correction):
        doses.noter(prise("fond", 0.2, 1.0))
    assert doses.densite("fond") == pytest.approx(0.2)
    # Pour 1 kg avec une densité de 0,5 : 2 L.
    assert doses.volume(doses.ouverture_pour(1.0, 0.02), 0.02) == pytest.approx(2.0)
    assert doses.ouverture_pour(1.0, 0.02, maximum=0.2) == 0.2
    doses.nouveau_fut()
    assert doses.densite() == GRIFFE.doses.densite_defaut_kg_l


# ---------------------------------------------------------------- au simulateur


def reglages_simules(densite: float | None = None, evenements=()):
    simulation = REGLAGES.simulateur
    assert simulation.griffe is not None
    griffe = simulation.griffe
    if densite is not None:
        griffe = griffe.model_copy(update={"densite_kg_l": densite})
    scenario = simulation.scenarios["vidange_fut"]
    scenario = scenario.model_copy(update={"evenements": [*scenario.evenements, *evenements]})
    simulation = simulation.model_copy(
        update={"griffe": griffe, "scenarios": {**simulation.scenarios, "vidange_fut": scenario}}
    )
    return REGLAGES.model_copy(update={"simulateur": simulation})


def vider(reglages=REGLAGES, registre=None, **options):
    """Rejoue la vidange d'un fût ; rend le planning, la griffe, le simulateur (fermé) et
    l'état du poste du fût à la fin."""
    with Simulateur(reglages, LISTE, "vidange_fut") as simulation:
        griffe = griffe_du_simulateur(simulation, **options)
        griffe.registre = registre
        planning = simulation.jouer([module_griffe(griffe)])
        return planning, griffe, simulation, simulation.poste_fut().etat()


def etapes(planning) -> list[str]:
    return [ligne.etape for ligne in planning.lignes]


def test_vidange_d_un_fut_complet(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    try:
        planning, griffe, simulation, etat = vider(registre=registre)
        assert planning.fini, planning.probleme
        fut = griffe.bras.fut
        # Presque tout le substrat est dans les seaux ; la densité vraie est apprise.
        assert fut.verse_kg > 55 and fut.masse < 3
        assert griffe.doses.densite() == pytest.approx(0.62, rel=0.02)
        assert etat.messages[-1].startswith(f"Fût vide : {griffe.plan.seaux_finis} seaux")
        assert etat.doses_kg == pytest.approx(fut.verse_kg, abs=0.01)
        assert etat.chariot  # le chariot peut partir : la griffe est hors de sa zone
        assert simulation.etat_axes.positions["pont_x"] > MACHINE.poste_fut.pont_interdit_x[1]
        suite = etapes(planning)
        assert suite[0] == "attendre_le_fut" and suite[-1] == "fut_vide"
        assert "racler" in suite
        # Chaque prise est notée dans le registre ; il y en a au fond et le long de la paroi.
        lieux = {ligne["lieu"] for ligne in registre.lire("SELECT lieu FROM prises_griffe")}
        assert lieux == {"couche", "fond", "paroi"}
    finally:
        registre.fermer()


def test_memoire_de_la_vidange():
    _, griffe, _, _ = vider(reglages_simules(evenements=[]))
    memoire = griffe.memoire()
    autre = griffe_du_simulateur(Simulateur(REGLAGES, LISTE, "vidange_fut"))
    autre.retrouver(memoire)
    assert autre.plan == griffe.plan


def test_hygiene_tasser_avant_le_mycelium_et_essuyer_a_la_fin():
    couches: list[int] = []
    planning, griffe, _, _ = vider(couche_finie=couches.append)
    suite = etapes(planning)
    # Le tassement suit toujours un vidage, et le mycélium n'est annoncé qu'après lui.
    # Seul le dernier seau (fût vide en cours de couche) est fini après un retour au fût.
    fin = len(suite) - 4
    for i, etape in enumerate(suite[:fin]):
        if etape == "tasser":
            assert suite[i - 1] == "vider_dans_le_seau"
        if etape == "essuyer_le_bord":
            assert suite[i - 1] in ("tasser", "vider_dans_le_seau")
    assert suite.count("essuyer_le_bord") == griffe.plan.seaux_finis
    # Le mycélium va entre les couches, pas sur la dernière couche d'un seau.
    assert set(couches) == {1, 2, 3}
    assert len(couches) == suite.count("tasser") - griffe.plan.seaux_finis


def test_seau_de_5_l_tasse_seulement_a_la_derniere_couche():
    planning, griffe, _, _ = vider(prochain_format=lambda: "seau_b")
    assert planning.fini, planning.probleme
    suite = etapes(planning)
    # 2 couches par seau de 5 L : un seul tassement par seau (la dernière couche).
    assert suite.count("tasser") == suite.count("essuyer_le_bord") == griffe.plan.seaux_finis


def test_pas_de_machouillage_pour_le_mais(caplog):
    with caplog.at_level(logging.DEBUG, logger="vidange.griffe"):
        vider(machouiller=lambda: False)
    assert "Griffe : bouchée 1" not in caplog.text
    with caplog.at_level(logging.DEBUG, logger="vidange.griffe"):
        vider()
    assert "Griffe : bouchée 4" in caplog.text


def test_trop_leger_reprendre_a_cote():
    # Substrat bien plus léger que la densité par défaut : les premières prises sont légères.
    planning, griffe, _, _ = vider(reglages_simules(densite=0.35))
    assert planning.fini, planning.probleme
    suite = etapes(planning)
    reprises = sum(
        1 for a, b in zip(suite, suite[1:], strict=False) if a == b == "prendre_une_dose"
    )
    assert reprises >= 1
    assert griffe.doses.densite() == pytest.approx(0.35, rel=0.05)


def test_trop_lourd_s_entrouvrir(caplog):
    with caplog.at_level(logging.DEBUG, logger="vidange.griffe"):
        planning, _, _, _ = vider(reglages_simules(densite=1.1))
    assert planning.fini, planning.probleme
    assert "Griffe : s'entrouvrir" in caplog.text


def test_pas_refuse_par_les_regles():
    # Caméra du dosage qui pivote : la griffe ne peut pas aller au seau, elle ne bouge pas.
    planning, _, _, _ = vider(camera_dosage_pivote=lambda: True)
    assert not planning.fini
    assert "refusé : la caméra du dosage pivote" in planning.probleme


def test_chariot_perdu_pendant_la_vidange():
    perdu = EvenementSimule(attente_s=300, capteur="chariot_fut_en_place", actionne=False)
    planning, _, simulation, _ = vider(reglages_simules(evenements=[perdu]))
    assert "plus tenu : chariot du fût en place" in planning.probleme
    assert QUOI_FAIRE_PERTE in planning.probleme
    # Le pont s'est retiré hors de la zone du chariot, tête en haut.
    positions = simulation.etat_axes.positions
    assert positions["pont_x"] > MACHINE.poste_fut.pont_interdit_x[1]
    assert positions["griffe_z"] == GRIFFE.trajet.z


def test_simulateur_en_ligne_de_commande(capsys):
    assert simulateur(["griffe"]) == 0
    texte = capsys.readouterr().out
    assert "fut_vide" in texte and "Temps total" in texte


# ---------------------------------------------------------------- le vrai bras


class BancBras:
    """Le vrai bras sur un faux FluidNC à 5 axes, avec une fausse pesée."""

    def __init__(self) -> None:
        self.faux = FauxFluidnc(axes="XYZAB")
        # Pont à 1,035 (mât 0,86), mât à y 0,57, axes à 1,0 m, tête à 0°, godet fermé.
        self.faux.positions.update(X=1035.0, Y=570.0, Z=1000.0)
        self.force = FausseForce(120.0)
        self.liaison = Liaison("portique", reglages_essai(), ouvrir=self.faux.ouvrir)

    def __enter__(self) -> "BancBras":
        self.liaison.demarrer()
        self.liaison.attendre_connexion(DELAI)
        self.bras = BrasFluidnc(MACHINE, self.liaison, self.force)
        self.arret = threading.Event()
        self.bras.demarrer(self.arret)
        attendre(lambda: self.bras.resultat().pose.z == pytest.approx(1.0))
        return self

    def __exit__(self, *_: object) -> None:
        self.arret.set()
        self.liaison.arreter()


def attendre(condition, delai: float = DELAI) -> None:
    fin = time.monotonic() + delai
    while not condition():
        assert time.monotonic() < fin, "pas arrivé à temps"
        time.sleep(0.01)


def test_bras_va_a_une_pose():
    with BancBras() as banc:
        pose = banc.bras.position()
        # Pont à 1,035 : mât à 1,035 − 0,187.
        assert pose.x == pytest.approx(0.848) and pose.z == pytest.approx(1.0) and pose.b == 0
        banc.bras.executer(Pas("monter", {"z": 1.01}), pose.avec(z=1.01, b=0.5))
        assert banc.faux.lignes_recues[-1].startswith("$J=G53 X1035.000 Y570.000 Z1010.000 A0.000")
        # Godet à moitié : 15 mm de vis.
        assert "B15.000" in banc.faux.lignes_recues[-1]
        attendre(banc.bras.fini)
        assert banc.bras.resultat().pose.z == pytest.approx(1.01)


def test_bras_s_arrete_au_contact():
    with BancBras() as banc:
        # La charge baisse de 30 N quand le godet touche, à 0,995 m.
        banc.force.fonction = lambda: 120.0 if banc.faux.positions["Z"] > 995 else 90.0
        time.sleep(0.2)
        pose = banc.bras.position()
        pas = Pas(
            "descente au contact", {"z": 0.98}, vitesse="descente_lente", arret_si_baisse_n=15
        )
        banc.bras.executer(pas, pose.avec(z=0.98))
        attendre(banc.bras.fini, 5)
        resultat = banc.bras.resultat()
        assert resultat.arrete
        assert 0.993 < resultat.pose.z <= 0.995


def test_bras_choc_pendant_un_trajet():
    with BancBras() as banc:
        time.sleep(0.2)
        pose = banc.bras.position()
        banc.bras.executer(Pas("trajet", {"x": 0.9}, choc=True), pose.avec(x=0.9))
        banc.force.newtons = 300.0
        with pytest.raises(ErreurEtape, match="choc") as erreur:
            attendre(lambda: banc.bras.fini() and False, 3)
        assert "remontera d'abord lentement" in erreur.value.quoi_faire
        assert banc.bras.choc


def test_bras_pesee_muette_arrete_la_descente():
    with BancBras() as banc:
        time.sleep(0.2)
        pose = banc.bras.position()
        pas = Pas("descente au contact", {"z": 0.9}, vitesse="descente_lente", arret_si_baisse_n=15)
        banc.bras.executer(pas, pose.avec(z=0.9))
        banc.force.muette = True
        with pytest.raises(ErreurEtape, match="pesée de la griffe muette"):
            attendre(lambda: banc.bras.fini() and False, 3)
        assert banc.bras.position().z > 0.98
