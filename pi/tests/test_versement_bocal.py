"""Versement de la griffe dans un bocal de semence, mode bocaux (tâche 43 bis)."""

import json
import math

import pytest

from vidange.chef import Condition, ErreurEtape, Etape, Module
from vidange.entonnoir.entonnoir import Entonnoir
from vidange.entonnoir.module import module_entonnoir
from vidange.entonnoir.outil import main as outil
from vidange.entonnoir.simulation import entonnoir_du_simulateur
from vidange.griffe import Contexte, Pose, ReglesGriffe
from vidange.griffe.simulation import griffe_du_simulateur
from vidange.griffe.versement import FAIT, OUVERT, Versement, poses_du_bocal
from vidange.registre import Registre
from vidange.reglages import EvenementSimule
from vidange.simulateur import Simulateur

from .test_griffe import LISTE, MACHINE, REGLAGES, REGLES, refus
from .test_reglages import erreur_de, remplacer

GRIFFE = MACHINE.griffe
assert GRIFFE is not None
VERSEMENT = GRIFFE.versement_bocal
assert VERSEMENT is not None
B20 = VERSEMENT.godet.b_pour(20)
B25 = VERSEMENT.godet.b_pour(25)
# Deux bocaux où la griffe peut verser (rangée 2 de la fiche : y 0,2506, colonne x 1,3175).
BOCAL = "bocal_1_2"
BOCAL_GARDE = "bocal_2_1"


# ---------------------------------------------------------------- réglages


def test_reglages_du_versement_du_depot():
    # Figés (fiche du 07/11) : pas de « exemple » sur la partie elle-même.
    assert VERSEMENT.dose_kg == 0.300 and VERSEMENT.centrage_max_m == 0.05
    assert VERSEMENT.axes_z == 1.025 and VERSEMENT.axes_z_permis == (1.02, 1.07)
    assert VERSEMENT.a_deg == 0 and VERSEMENT.ouverture_deg == 20
    assert VERSEMENT.garde_camera_bocal.mat_y == (0.21, 0.29)
    assert VERSEMENT.garde_camera_bocal.mat_x_min == 1.207
    assert (VERSEMENT.pesee.attente_s, VERSEMENT.pesee.moyenne_s) == (0.3, 0.5)
    # Proposés ou à mesurer : en EXEMPLE.
    assert VERSEMENT.exemples() == ["dose", "ouverture", "secousses", "fin", "godet", "bouchage"]
    assert VERSEMENT.dose.plage_kg == (0.290, 0.310)
    # Bas des dents à 20° : 1,025 − 0,213 = 0,812, au-dessus du haut du cône.
    assert MACHINE.entonnoir is not None
    assert VERSEMENT.axes_z - GRIFFE.bas_godet_sous_axes > MACHINE.entonnoir.cone_haut_z


def test_ouverture_du_godet_selon_l_angle():
    godet = VERSEMENT.godet
    assert godet.b_pour(0) == 0 and godet.b_pour(35) == 1
    assert godet.b_pour(20) == 0.28
    assert math.isclose(godet.b_pour(17.5), (0.21 + 0.28) / 2)
    with pytest.raises(ValueError, match="hors de la table"):
        godet.b_pour(40)


def test_reglages_du_versement_verifies(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "      plage_kg: [0.290, 0.310]", "      plage_kg: [0.310, 0.350]")
    remplacer(machine, "    axes_z: 1.025\n", "    axes_z: 1.10\n")
    message = erreur_de(reglages)
    assert "plage_kg (0.31 à 0.35) doit entourer dose_kg (0.3)" in message
    assert "axes_z (1.1) hors de axes_z_permis" in message


def test_vitesse_des_secousses_verifiee(reglages):
    remplacer(reglages / "machine.yaml", "      vitesse_m_s: 0.030", "      vitesse_m_s: 0.30")
    message = erreur_de(reglages)
    assert "secousses → vitesse_m_s (0.3) au-dessus de vitesses → griffe_b (0.05)" in message


def test_table_du_godet_verifiee(reglages):
    remplacer(
        reglages / "machine.yaml",
        "      b: [0.0, 0.21, 0.28, 0.36, 1.0]",
        "      b: [0.0, 0.3, 0.28, 0.36, 1.0]",
    )
    assert "godet : b : du plus petit au plus grand" in erreur_de(reglages)


def test_garde_de_la_camera_du_bocal_verifiee(reglages):
    machine = reglages / "machine.yaml"
    # La raclette (mât − 0,11) toucherait le boîtier (x jusqu'à 1,091).
    remplacer(
        machine, "{mat_y: [0.21, 0.29], mat_x_min: 1.207}", "{mat_y: [0.23, 0.29], mat_x_min: 1.20}"
    )
    message = erreur_de(reglages)
    assert "mat_y doit couvrir le boîtier de la caméra du bocal" in message
    assert "la raclette (mât − 0.11) toucherait le boîtier" in message


def test_chaque_bocal_de_la_bande_tient_la_garde(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "mat_x_min: 1.207}", "mat_x_min: 1.25}")
    message = erreur_de(reglages)
    # La colonne x 1,2075 de la rangée 2 passe à 0,5 mm de 1,207 : plus avec 1,25.
    assert "le bocal « bocal_2_0 » (x 1.2075, y 0.2506) demande le mât à x ≥ 1.25" in message


def test_dents_au_dessus_du_cone_verifiees(reglages):
    remplacer(reglages / "machine.yaml", "  cone_haut_z: 0.782", "  cone_haut_z: 0.785")
    remplacer(reglages / "machine.yaml", "  oreille_z: 0.786", "  oreille_z: 0.81")
    remplacer(
        reglages / "machine.yaml",
        "    axes_z_permis: [1.02, 1.07]",
        "    axes_z_permis: [0.99, 1.07]",
    )
    assert "bas des dents à 0.777 m, pas au-dessus du haut du cône" in erreur_de(reglages)


# ---------------------------------------------------------------- règle de la garde


def test_garde_du_boitier_de_la_camera_du_bocal():
    # Aujourd'hui, la table « y minimum du mât » (bande x 1,14-1,21 élargie d'1 cm) refuse déjà
    # ces poses : la garde est vérifiée sans elle, pour le jour où la table changera.
    sans_table = GRIFFE.y_min_mat.model_copy(update={"sous_butee": [], "butee_haute": []})
    machine = MACHINE.model_copy(
        update={"griffe": GRIFFE.model_copy(update={"y_min_mat": sans_table})}
    )
    regles = ReglesGriffe(machine)

    def refus_garde(pose: Pose) -> str:
        return regles.refus_pose(pose, Contexte()) or ""

    ouvert = Pose(x=1.2075, y=0.2506, z=VERSEMENT.axes_z, a=0, b=B20)
    # Raclette à mât − 0,11 : à x 1,20 elle toucherait le boîtier (règle de la géométrie) ; à
    # 1,204 elle passe à 3 mm, la garde de la fiche (5 mm) refuse quand même.
    assert "toucherait le boîtier" in refus_garde(ouvert.avec(x=1.20))
    assert "garde du boîtier" in refus_garde(ouvert.avec(x=1.204))
    assert "il faut x ≥ 1,207" in refus_garde(ouvert.avec(x=1.205, y=0.215))
    # Hors de la bande y 0,21-0,29, ou tête au-dessus du boîtier : rien de plus.
    assert refus_garde(ouvert.avec(x=1.204, y=0.30)) == ""
    assert refus_garde(ouvert.avec(x=1.204, z=1.29, b=0)) == ""
    # À x 1,207 et au-delà : la garde est tenue (bocal_2_0 à 1,2075 ; colonne x 1,3175).
    assert refus_garde(ouvert) == ""
    assert refus(ouvert.avec(x=1.3175)) is None
    # Avec la table du dépôt, bocal_2_0 reste refusé (question à Karulium).
    assert "agitateur du mycélium" in refus(ouvert)


def test_poses_du_bocal():
    poses = poses_du_bocal(VERSEMENT, 1.3175, 0.2506)
    assert [round(pose.b, 2) for pose in poses] == [0, 0.28, 0.21, 0.36, 1.0, 0]
    assert {pose.a for pose in poses} == {0}
    assert poses[-1].z == pytest.approx(1.045)
    for pose in poses:
        assert REGLES.refus_pose(pose, Contexte()) is None


# ---------------------------------------------------------------- au simulateur


def reglages_simules(densite: float = 0.7, apres: str = "essai.verser"):
    """La griffe du simulateur avec cette densité vraie du maïs ; le bouton « Prêt » du poste
    est appuyé au début de l'étape `apres`."""
    simulation = REGLAGES.simulateur
    assert simulation.griffe is not None
    griffe = simulation.griffe.model_copy(update={"densite_kg_l": densite})
    scenario = simulation.scenarios["vidange_fut"]
    pret = [
        EvenementSimule(apres=apres, attente_s=3, capteur="bouton_pret_fut", actionne=True),
        EvenementSimule(apres=apres, attente_s=4, capteur="bouton_pret_fut", actionne=False),
    ]
    scenario = scenario.model_copy(update={"evenements": [*scenario.evenements, *pret]})
    simulation = simulation.model_copy(
        update={"griffe": griffe, "scenarios": {**simulation.scenarios, "vidange_fut": scenario}}
    )
    return REGLAGES.model_copy(update={"simulateur": simulation})


def verser(
    bocal: str = BOCAL,
    densite: float = 0.7,
    fichier=None,
    preparer=lambda versement, bras: None,
    **options,
):
    """Un versement dans un bocal où Karulium a posé l'entonnoir (Go). Rend le planning, le
    versement et le bras simulé."""
    reglages = reglages_simules(densite)
    with Simulateur(reglages, LISTE, "vidange_fut") as simulation:
        griffe = griffe_du_simulateur(simulation, machouiller=lambda: False)
        entonnoir = Entonnoir(MACHINE)
        entonnoir.demarrer_lot([bocal])
        entonnoir.demander_la_pose()
        versement = Versement(griffe, entonnoir, fichier, **options)
        preparer(versement, griffe.bras)
        module = Module(
            nom="essai",
            etapes=(
                Etape(
                    "verser",
                    "Regarder la griffe.",
                    action=lambda: versement.verser(entonnoir.place),
                    fin=Condition("versement fini", versement.fini),
                    entree=versement.entree,
                    delai_max="entonnoir_versement_max",
                ),
            ),
            pauser=versement.pauser,
            reprendre=versement.reprendre,
            arreter=versement.arreter,
        )
        planning = simulation.jouer([module])
        versement.etat_poste = griffe.poste.etat()
        return planning, versement, griffe.bras


def test_un_versement_complet(tmp_path, caplog):
    caplog.set_level("INFO", logger="vidange.griffe")
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    fichier = tmp_path / "donnees" / "versement.json"
    try:

        def preparer(versement, bras):
            versement.griffe.registre = registre

        planning, versement, bras = verser(fichier=fichier, preparer=preparer)
        assert planning.fini, planning.probleme
        dose = versement.doses[BOCAL]
        assert 0.290 <= dose <= 0.310
        # Tout est tombé dans l'entonnoir ; le poste du fût le sait.
        assert bras.fut.verse_kg == pytest.approx(dose, abs=1e-6)
        assert bras.godet_kg == 0
        assert versement.etat_poste.doses_kg == pytest.approx(dose, abs=1e-6)
        # Godet refermé, tête à A = 0, en haut ; phase gardée « fait ».
        pose = bras.position()
        assert pose.b == pytest.approx(0, abs=1e-9) and pose.a == pytest.approx(0, abs=1e-9)
        assert pose.z == pytest.approx(GRIFFE.trajet.z)
        assert json.loads(fichier.read_text())["phase"] == FAIT
        lignes = registre.lire("SELECT nom, valeur FROM mesures WHERE nom = 'dose_bocal'")
        assert len(lignes) == 1
        assert lignes[0]["valeur"] == pytest.approx(dose, abs=1e-4)
        # Le maïs ne se mâchouille pas ; aucune rotation de la tête pendant le versement.
        assert "0 bouchées" in caplog.text
        assert "capteur de distance de la tête pas branché" in caplog.text
    finally:
        registre.fermer()


def test_versement_dans_la_rangee_de_la_garde():
    planning, versement, _ = verser(BOCAL_GARDE)
    assert planning.fini, planning.probleme
    assert BOCAL_GARDE in versement.doses


def test_densite_pas_encore_apprise_la_prise_est_refaite(caplog):
    caplog.set_level("INFO", logger="vidange.griffe")
    planning, versement, bras = verser(densite=0.62)
    assert planning.fini, planning.probleme
    # Première prise trop légère (densité par défaut 0,7) : rendue au fût, refaite à côté.
    assert caplog.text.count("Griffe : prise couche") >= 2
    assert 0.290 <= versement.doses[BOCAL] <= 0.310
    assert bras.fut.verse_kg == pytest.approx(versement.doses[BOCAL], abs=1e-6)


def test_jamais_de_versement_hors_du_bocal_de_l_entonnoir():
    with Simulateur(reglages_simules(), LISTE, "vidange_fut") as simulation:
        griffe = griffe_du_simulateur(simulation)
        entonnoir = Entonnoir(MACHINE)
        versement = Versement(griffe, entonnoir)
        with pytest.raises(ErreurEtape, match="entonnoir_place est « hors_machine »"):
            versement.verser(BOCAL)
        entonnoir.demarrer_lot([BOCAL, "bocal_1_3"])
        entonnoir.demander_la_pose()
        with pytest.raises(ErreurEtape, match="l'entonnoir est sur le bocal rangée 2, place 3"):
            versement.verser("bocal_1_3")
        entonnoir._changer(BOCAL, True)
        with pytest.raises(ErreurEtape, match="tient l'entonnoir"):
            versement.verser(BOCAL)


def test_bocal_ou_la_griffe_ne_peut_pas_ouvrir_refuse_avant_toute_prise():
    # Rangée 0 (y 0,06) : godet ouvert permis de y 0,11 à 0,83 seulement (fiche de la griffe).
    planning, versement, bras = verser("bocal_0_1")
    assert not planning.fini
    assert "ne peut pas verser dans le bocal rangée 1, place 2" in planning.probleme
    assert "godet ouvert avec le mât à y 0,06" in planning.probleme
    assert bras.fut.verse_kg == 0 and bras.godet_kg == 0


def test_grains_colles_decolles_par_les_secousses(caplog):
    caplog.set_level("INFO", logger="vidange.griffe")

    def preparer(versement, bras):
        bras.colle_kg, bras.decolle_b = 0.05, B25

    planning, versement, bras = verser(preparer=preparer)
    assert planning.fini, planning.probleme
    assert "secousses" in caplog.text and "grand ouvert" not in caplog.text
    assert bras.fut.verse_kg == pytest.approx(versement.doses[BOCAL], abs=1e-6)


def test_grains_colles_decolles_grand_ouvert(caplog):
    caplog.set_level("INFO", logger="vidange.griffe")

    def preparer(versement, bras):
        bras.colle_kg, bras.decolle_b = 0.05, 1.0

    planning, versement, bras = verser(preparer=preparer)
    assert planning.fini, planning.probleme
    assert "secousses" in caplog.text and "grand ouvert" in caplog.text


def test_grains_colles_alerte_griffe_immobile_godet_ouvert(tmp_path):
    fichier = tmp_path / "versement.json"

    def preparer(versement, bras):
        bras.colle_kg, bras.decolle_b = 0.05, 2.0

    planning, versement, bras = verser(fichier=fichier, preparer=preparer)
    assert not planning.fini
    assert "grains collés dans le godet" in planning.probleme
    # Jamais refermé au-dessus du bocal avec des grains dedans ; la phase « ouvert » est gardée.
    pose = bras.position()
    assert pose.b == pytest.approx(1.0) and pose.z == pytest.approx(VERSEMENT.axes_z)
    assert bras.godet_kg == pytest.approx(0.05)
    etat = json.loads(fichier.read_text())
    assert etat["phase"] == OUVERT and etat["bocal"] == BOCAL


def test_apres_une_coupure_pendant_le_versement_jamais_une_2e_dose(tmp_path):
    """Coupure godet ouvert au-dessus du bocal : au redémarrage, la griffe (godet refermé par
    sa prise d'origine) remonte, pèse le godet vide et finit, sans reprendre de dose."""
    fichier = tmp_path / "versement.json"
    fichier.write_text(
        json.dumps({"bocal": BOCAL, "phase": OUVERT, "avant_kg": 0.301, "tare_n": 120.0})
    )
    planning, versement, bras = verser(fichier=fichier)
    assert planning.fini, planning.probleme
    assert list(versement.doses) == [BOCAL]
    assert versement.doses[BOCAL] == pytest.approx(0.301)
    # Aucune prise dans le fût, rien de versé de plus.
    assert bras.fut.verse_kg == 0
    assert bras.fut.masse == pytest.approx(60.0)
    assert json.loads(fichier.read_text())["phase"] == FAIT


def test_versement_d_un_autre_bocal_pas_fini_le_bocal_est_suspect(tmp_path):
    fichier = tmp_path / "versement.json"
    fichier.write_text(
        json.dumps({"bocal": "bocal_1_5", "phase": OUVERT, "avant_kg": 0.3, "tare_n": 120.0})
    )
    with Simulateur(reglages_simules(), LISTE, "vidange_fut") as simulation:
        griffe = griffe_du_simulateur(simulation)
        entonnoir = Entonnoir(MACHINE)
        entonnoir.demarrer_lot([BOCAL])
        entonnoir.demander_la_pose()
        versement = Versement(griffe, entonnoir, fichier)
        with pytest.raises(ErreurEtape, match="bocal rangée 2, place 6 n'a pas été fini"):
            versement.verser(BOCAL)
        assert entonnoir.suspects == ["bocal_1_5"]
        # Après le Go de Karulium, le versement repart normalement.
        assert not versement.commence(BOCAL) and versement.etat.phase is None


def test_entonnoir_bouche_bocal_suspect_et_alerte():
    planning, versement, bras = verser(distance_m=lambda: 0.30)
    assert not planning.fini
    assert "entonnoir bouché, bocal rangée 2, place 3" in planning.probleme
    assert versement.entonnoir.suspects == [BOCAL]
    # La dose est notée, le godet vide est refermé après la remontée, la griffe est en haut.
    assert BOCAL in versement.doses and versement.etat.phase == FAIT
    pose = bras.position()
    assert pose.b == pytest.approx(0, abs=1e-9) and pose.z == pytest.approx(GRIFFE.trajet.z)


def test_entonnoir_pas_bouche():
    planning, _, _ = verser(distance_m=lambda: VERSEMENT.bouchage.distance_vide_m)
    assert planning.fini, planning.probleme


def test_pesee_instable_alerte_apres_3_essais():
    lectures = iter(range(10_000))

    def preparer(versement, bras):
        # ± 0,3 N (≈ 30 g) d'une lecture à l'autre.
        bras.bruit_n = lambda: 0.3 * (-1) ** next(lectures)

    planning, _, bras = verser(preparer=preparer)
    assert not planning.fini
    assert "pesée de la griffe instable" in planning.probleme
    assert "3 essais" in planning.probleme


def test_fut_vide_alerte_et_le_poste_le_dit():
    def preparer(versement, bras):
        bras.fut._masse = 0.0

    planning, _, _ = verser(preparer=preparer)
    assert not planning.fini
    assert "Fût vide : 0 bocaux" in planning.probleme


# ---------------------------------------------------------------- avec le module de l'entonnoir


def test_lot_de_bocaux_avec_le_vrai_versement():
    reglages = reglages_simules(apres="entonnoir.verser")
    bocaux = [BOCAL, "bocal_1_3", "bocal_2_3"]
    with Simulateur(reglages, LISTE, "vidange_fut") as simulation:
        scenario = entonnoir_du_simulateur(simulation, avec_module=False)
        griffe = griffe_du_simulateur(simulation, machouiller=lambda: False)
        versement = Versement(griffe, scenario.entonnoir)
        module = module_entonnoir(
            scenario.entonnoir, scenario.prehension, bocaux, versement=versement
        )
        planning = simulation.jouer([module])
        assert planning.fini, planning.probleme
        assert set(versement.doses) == set(bocaux)
        assert all(0.290 <= dose <= 0.310 for dose in versement.doses.values())
        assert griffe.bras.fut.verse_kg == pytest.approx(sum(versement.doses.values()))
        suite = [ligne.etape for ligne in planning.lignes]
        assert suite.count("verser") == 3 and suite[-1] == "enlever_a_la_main"


# ---------------------------------------------------------------- outil


def test_outil_versement(capsys):
    assert outil(["versement"]) == 0
    sortie = capsys.readouterr().out
    assert "Dose 300 g (acceptée de 290 à 310 g)" in sortie
    assert "bas des dents à 0,812 m" in sortie
    assert "20° → 0,28" in sortie
    assert "Bocaux où la griffe ne peut pas verser : 29" in sortie
    assert "bocal_2_0" in sortie and "bocal_0_5" in sortie and "bocal_8_3" in sortie
