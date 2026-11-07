"""Versement de la griffe dans un bocal de semence, mode bocaux (tâche 43 bis)."""

import json
import math

import pytest

from vidange.chef import Condition, ErreurEtape, Etape, Module
from vidange.cycle.griffe_du_lot import brancher_pont
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
    # La bande de garde s'arrête à 1,205 (Maquette v45.120, 07/11 ; 1,207 avant).
    assert VERSEMENT.garde_camera_bocal.mat_x_min == 1.205
    assert (VERSEMENT.pesee.attente_s, VERSEMENT.pesee.moyenne_s) == (0.3, 0.5)
    # Proposés ou à mesurer : en EXEMPLE (la face basse de la préhension : proposée, 07/11).
    assert VERSEMENT.exemples() == [
        "dose",
        "ouverture",
        "secousses",
        "fin",
        "godet",
        "bouchage",
        "tete_basse",
    ]
    tete = VERSEMENT.tete_basse
    assert tete is not None
    assert (tete.prehension_face_basse_versement, tete.prehension_x_min_tete_basse) == (0.90, 1.20)
    # Au-dessus du stockage, le godet ouvert n'a plus de y minimum (fil Griffe, 07/11).
    assert GRIFFE.godet_ouvert_sans_y_min == (1.10, 2.70)
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
        machine, "{mat_y: [0.21, 0.29], mat_x_min: 1.205}", "{mat_y: [0.23, 0.29], mat_x_min: 1.20}"
    )
    message = erreur_de(reglages)
    assert "mat_y doit couvrir le boîtier de la caméra du bocal" in message
    assert "la raclette (mât − 0.11) toucherait le boîtier" in message


def test_chaque_bocal_de_la_bande_tient_la_garde(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "mat_x_min: 1.205}", "mat_x_min: 1.25}")
    message = erreur_de(reglages)
    # La colonne x 1,2075 de la rangée 2 passe à 2,5 mm de 1,205 : plus avec 1,25.
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
    # La garde est vérifiée sans la table « y minimum du mât » (qui refuse aussi x 1,15-1,204).
    sans_table = GRIFFE.y_min_mat.model_copy(update={"sous_butee": [], "butee_haute": []})
    machine = MACHINE.model_copy(
        update={"griffe": GRIFFE.model_copy(update={"y_min_mat": sans_table})}
    )
    regles = ReglesGriffe(machine)

    def refus_garde(pose: Pose) -> str:
        return regles.refus_pose(pose, Contexte()) or ""

    ouvert = Pose(x=1.2075, y=0.2506, z=VERSEMENT.axes_z, a=0, b=B20)
    # Raclette à mât − 0,11 : à x 1,20 elle toucherait le boîtier (règle de la géométrie) ; à
    # 1,204 elle passe à moins de 9 mm (Maquette v45.120) : la garde refuse.
    assert "toucherait le boîtier" in refus_garde(ouvert.avec(x=1.20))
    assert "garde du boîtier" in refus_garde(ouvert.avec(x=1.204))
    assert "il faut x ≥ 1,205" in refus_garde(ouvert.avec(x=1.204, y=0.215))
    # Hors de la bande y 0,21-0,29, ou tête au-dessus du boîtier : rien de plus.
    assert refus_garde(ouvert.avec(x=1.204, y=0.30)) == ""
    assert refus_garde(ouvert.avec(x=1.204, z=1.29, b=0)) == ""
    # À x 1,205 et au-delà : la garde est tenue (9 mm ; bocal_2_0 à 1,2075 : 11,5 mm).
    assert refus_garde(ouvert.avec(x=1.205)) == ""
    assert refus_garde(ouvert) == ""
    assert refus(ouvert.avec(x=1.3175)) is None
    # Avec la table du dépôt (ligne 1,15 – 1,204, sans l'élargir d'1 cm), bocal_2_0 passe aussi,
    # et bocal_0_0 (y 0,06).
    assert refus(ouvert) is None
    assert refus(ouvert.avec(y=0.06)) is None
    # La ligne refuse toujours le mât à x 1,204, y 0,25 sous la butée haute.
    assert "agitateur du mycélium" in refus(ouvert.avec(x=1.204))


def test_godet_ouvert_sans_y_minimum_au_dessus_du_stockage():
    # Fil Griffe (07/11) : rangée 1 (mât y 0,06), godet à 20° ou grand ouvert, au-dessus du
    # stockage : permis.
    ouvert = Pose(x=1.5375, y=0.06, z=VERSEMENT.axes_z, a=0, b=B20)
    assert refus(ouvert) is None
    assert refus(ouvert.avec(b=1.0)) is None
    # Hors de la bande x 1,10-2,70 : le y minimum 0,11 reste (cylindre prudent).
    assert "godet ouvert avec le mât à y 0,06" in refus(ouvert.avec(x=2.72))
    # Godet fermé : toujours y ≥ 0,056 ; et jamais hors de la course de chariot_y.
    assert "godet fermé avec le mât à y 0,05" in refus(ouvert.avec(y=0.05, b=0))
    assert "hors de la course" in refus(ouvert.avec(y=0.035))


def test_bande_sans_y_minimum_verifiee(reglages):
    remplacer(
        reglages / "machine.yaml",
        "  godet_ouvert_sans_y_min: [1.10, 2.70]",
        "  godet_ouvert_sans_y_min: [2.70, 1.10]",
    )
    assert "godet_ouvert_sans_y_min : x du plus petit au plus grand" in erreur_de(reglages)


def test_tete_basse_de_la_derniere_rangee_verifiee(reglages):
    machine = reglages / "machine.yaml"
    # Face au-dessus de ce que la chaîne Z permet au-delà de y 0,80 (0,942).
    remplacer(
        machine,
        "      prehension_face_basse_versement: 0.90",
        "      prehension_face_basse_versement: 0.95",
    )
    # Préhension (mât de la griffe + 0,316) à x 1,52 pour la colonne x 1,2075 : sous 1,60.
    remplacer(
        machine,
        "      prehension_x_min_tete_basse: 1.20",
        "      prehension_x_min_tete_basse: 1.60",
    )
    message = erreur_de(reglages)
    assert "prehension_face_basse_versement (0.95) : pour le bocal « bocal_8_0 »" in message
    assert "il faut une face de 0.23 à 0.942 m (chaîne Z)" in message
    assert "pour le bocal « bocal_8_0 », la préhension serait à x 1.52" in message
    assert "bocal_8_3 », la préhension" not in message


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


def test_rangee_1_et_colonne_de_la_garde_remplies():
    # Rangée 1 (y 0,06) et bocal_0_0 (x 1,2075) : plus refusés (fils Griffe et Maquette, 07/11).
    for bocal in ("bocal_0_1", "bocal_0_0", "bocal_2_0"):
        planning, versement, _ = verser(bocal)
        assert planning.fini, planning.probleme
        assert 0.290 <= versement.doses[bocal] <= 0.310


def test_derniere_rangee_sans_prehension_refusee_avant_toute_prise():
    # Dernière rangée (y 0,8224) : la tête de préhension doit être basse ; sans elle, refusé
    # avant toute prise.
    planning, versement, bras = verser("bocal_8_3")
    assert not planning.fini
    assert "ne peut pas verser dans le bocal rangée 9, place 4" in planning.probleme
    assert "la tête de préhension doit y être basse" in planning.probleme
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


def lot_avec_la_tete_de_prehension(bocaux, preparer=lambda scenario, versement: None):
    """Un lot de bocaux, versement branché sur la tête de préhension du même pont (dernière
    rangée). Rend le planning, le versement, la griffe et les pas de la tête (texte, face visée,
    y des mâts au départ)."""
    reglages = reglages_simules(apres="entonnoir.verser")
    with Simulateur(reglages, LISTE, "vidange_fut") as simulation:
        scenario = entonnoir_du_simulateur(simulation, avec_module=False)
        prehension = scenario.prehension
        griffe = griffe_du_simulateur(
            simulation,
            machouiller=lambda: False,
            prehension_face_z=lambda: prehension.tete.position().z,
        )
        brancher_pont(griffe, prehension)
        versement = Versement(griffe, scenario.entonnoir, prehension=prehension)
        pas_tete = []
        executer = prehension.tete.executer

        def noter(pas, cible, poids):
            pas_tete.append((pas.texte, cible.z, prehension.tete.position().y))
            executer(pas, cible, poids)

        prehension.tete.executer = noter
        preparer(scenario, versement)
        module = module_entonnoir(scenario.entonnoir, prehension, bocaux, versement=versement)
        planning = simulation.jouer([module])
        return planning, versement, griffe, pas_tete


def test_derniere_rangee_tete_de_prehension_basse_pendant_le_versement():
    bocaux = ["bocal_8_3", "bocal_8_4"]
    planning, versement, griffe, pas_tete = lot_avec_la_tete_de_prehension(bocaux)
    assert planning.fini, planning.probleme
    assert set(versement.doses) == set(bocaux)
    tete = VERSEMENT.tete_basse
    assert tete is not None
    face = tete.prehension_face_basse_versement
    basses = [p for p in pas_tete if p[0].startswith("tête basse pendant le versement")]
    hautes = [i for i, p in enumerate(pas_tete) if p[0] == "monter"]
    # Une descente par bocal, à la face 0,90, mâts encore à y ≤ 0,80 (avant que la griffe y
    # passe) ; une remontée après chacune, mâts revenus à y ≤ 0,80.
    assert len(basses) == 2
    assert all(z == pytest.approx(face) and y <= 0.80 + 1e-6 for _, z, y in basses)
    for i, (texte, _, _) in enumerate(pas_tete):
        if texte.startswith("tête basse pendant le versement"):
            suivante = next(j for j in hautes if j > i)
            assert pas_tete[suivante][2] <= 0.80 + 1e-6
    # À la fin, tête de préhension en haut, griffe en haut à y ≤ 0,80.
    pose = griffe.bras.position()
    assert pose.z == pytest.approx(GRIFFE.trajet.z) and pose.y <= 0.80 + 1e-6


def test_derniere_rangee_tete_de_prehension_qui_tient_un_objet_refusee():
    def preparer(scenario, versement):
        prehension = scenario.prehension
        prehension.objet = prehension.objet_par_nom("capsule")

    planning, versement, griffe, pas_tete = lot_avec_la_tete_de_prehension(["bocal_8_3"], preparer)
    assert not planning.fini
    assert "tête de préhension basse refusée : elle tient un(e) capsule" in planning.probleme
    assert not [p for p in pas_tete if p[0].startswith("tête basse")]
    # Refus avant de passer y 0,80 : la griffe n'y est jamais allée.
    assert griffe.bras.position().y <= 0.80 + 1e-6


def test_lot_avec_les_bocaux_autrefois_refuses():
    # Rangée 1 et dernière rangée, l'entonnoir posé par la Préhension d'un bocal à l'autre.
    bocaux = ["bocal_0_5", "bocal_8_0", "bocal_0_6"]
    planning, versement, *_ = lot_avec_la_tete_de_prehension(bocaux)
    assert planning.fini, planning.probleme
    assert set(versement.doses) == set(bocaux)


def test_tete_basse_trainee_par_le_pont():
    tete = VERSEMENT.tete_basse
    assert tete is not None
    with Simulateur(reglages_simules(), LISTE, "vidange_fut") as simulation:
        scenario = entonnoir_du_simulateur(simulation, avec_module=False)
        prehension = scenario.prehension
        griffe = griffe_du_simulateur(simulation)
        brancher_pont(griffe, prehension)
        etat = simulation.etat_axes.positions
        etat["prehension_z"] = tete.prehension_face_basse_versement
        etat["chariot_y"] = 0.80
        # Préhension au-dessus du plateau du haut (x 1,84) : le pont peut rouler (fiche).
        etat["pont_x"] = 1.84 - MACHINE.prehension.decalage_mat_x
        mat = griffe.bras.position()
        haut = mat.avec(z=GRIFFE.trajet.z, b=0.0, a=0.0)
        assert griffe.verrou_pont(haut, haut.avec(y=0.8224)) is None
        assert griffe.verrou_pont(haut, haut.avec(x=haut.x + 0.3)) is None
        # Vers l'entrée, sous x 1,20 : refusé (ailleurs, la tête reste à 1,10).
        refus = griffe.verrou_pont(haut, haut.avec(x=haut.x - 0.7))
        assert refus is not None and "elle ne va qu'au-dessus du plateau du haut" in refus
        # Une autre face basse (pas celle du versement) : la règle « tête en haut » d'avant.
        etat["prehension_z"] = 0.70
        refus = griffe.verrou_pont(haut, haut.avec(y=0.70))
        assert refus is not None and "tête basse refusé" in refus


# ---------------------------------------------------------------- outil


def test_outil_versement(capsys):
    assert outil(["versement"]) == 0
    sortie = capsys.readouterr().out
    assert "Dose 300 g (acceptée de 290 à 310 g)" in sortie
    assert "bas des dents à 0,812 m" in sortie
    assert "20° → 0,28" in sortie
    # Plus aucun des 122 bocaux refusé (réponses des fils du 07/11, tâche 45 septies).
    assert "Bocaux où la griffe ne peut pas verser : 0" in sortie
    assert "Garde du boîtier de la caméra du bocal : mât à y 0,21-0,29 → x ≥ 1,205" in sortie
    assert "tête de préhension vide à la face 0,9 m, préhension à x ≥ 1,2" in sortie
    # Autre limite (pont partagé, tâche 45 sexies, question à Karulium) : la Préhension ne pose
    # pas l'entonnoir sur 4 bocaux, la griffe traînée irait au-dessus de l'agitateur.
    assert "ne peut pas poser l'entonnoir" in sortie and "pose finale seulement) : 4" in sortie
    assert "bocal_2_0  (1,2075 ; 0,2506) : mât de la griffe à 1,0315" in sortie
