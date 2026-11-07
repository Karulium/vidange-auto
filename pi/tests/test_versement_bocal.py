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


# Un lot de taille normale (plus de limite à 3 bocaux depuis la tâche 45 octies).
LOT = [
    BOCAL,
    "bocal_1_3",
    "bocal_2_3",
    "bocal_2_4",
    "bocal_3_3",
    "bocal_3_4",
    "bocal_4_3",
    "bocal_4_4",
]


def test_lot_de_bocaux_avec_le_vrai_versement():
    reglages = reglages_simules(apres="entonnoir.verser")
    with Simulateur(reglages, LISTE, "vidange_fut") as simulation:
        scenario = entonnoir_du_simulateur(simulation, avec_module=False)
        griffe = griffe_du_simulateur(simulation, machouiller=lambda: False)
        versement = Versement(griffe, scenario.entonnoir)
        tournes = []
        executer = griffe.bras.executer

        def noter(pas, cible):
            if pas.texte.startswith("tête à 0° dans le fût"):
                tournes.append((griffe.regles.dans_le_fut(griffe.bras.position()), cible.a))
            executer(pas, cible)

        griffe.bras.executer = noter
        module = module_entonnoir(scenario.entonnoir, scenario.prehension, LOT, versement=versement)
        planning = simulation.jouer([module])
        assert planning.fini, planning.probleme
        assert set(versement.doses) == set(LOT)
        assert all(0.290 <= dose <= 0.310 for dose in versement.doses.values())
        assert griffe.bras.fut.verse_kg == pytest.approx(sum(versement.doses.values()))
        suite = [ligne.etape for ligne in planning.lignes]
        assert suite.count("verser") == len(LOT) and suite[-1] == "enlever_a_la_main"
        # Défaut d'avant la tâche 45 octies : la prise tourne la raclette vers le centre du fût
        # et la sortie prenait l'orientation bloquée la plus proche (parfois −180°). Maintenant,
        # la tête est mise à 0° dans le fût, avant la sortie (ici : plusieurs fois sur 8 bocaux).
        assert tournes and all(dedans and a == 0 for dedans, a in tournes)


def test_la_prise_du_mode_bocaux_finit_tete_a_0_dans_le_fut():
    with Simulateur(reglages_simules(), LISTE, "vidange_fut") as simulation:
        griffe = griffe_du_simulateur(simulation)
        centre_x, centre_y = griffe.fut.centre_fut
        dans_le_fut = Pose(x=centre_x + 0.05, y=centre_y, z=griffe.fut.fut_bord_z, a=-100.0, b=0.0)
        assert griffe.regles.dans_le_fut(dans_le_fut)
        griffe.pose = dans_le_fut
        pas = list(griffe._tete_a_dans_le_fut(0.0))
        assert [(p.texte, p.cibles) for p in pas] == [("tête à 0° dans le fût", {"a": 0.0})]
        # Godet pas fermé : fermé d'abord. La tête ne peut pas tourner là : d'abord au centre.
        griffe.pose = dans_le_fut.avec(b=0.3)
        griffe.regles.refus_mouvement = lambda depart, arrivee, contexte: "gêné"
        pas = list(griffe._tete_a_dans_le_fut(0.0))
        assert [p.texte for p in pas] == [
            "fermer le godet",
            "vers le centre du fût",
            "tête à 0° dans le fût",
        ]
        assert pas[1].cibles == {"x": centre_x, "y": centre_y}
        # Déjà à 0° : rien.
        griffe.pose = dans_le_fut.avec(a=0.2)
        assert list(griffe._tete_a_dans_le_fut(0.0)) == []
        # Hors du fût, tête à −180° : jamais de sortie, alarme.
        griffe.pose = dans_le_fut.avec(z=GRIFFE.trajet.z, a=-180.0)
        with pytest.raises(ErreurEtape, match="tête à -180° hors du fût, il faut 0°"):
            list(griffe._tete_a_dans_le_fut(0.0))


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
    bocaux = [
        "bocal_0_5",
        "bocal_8_0",
        "bocal_0_6",
        "bocal_8_3",
        "bocal_1_2",
        "bocal_0_3",
        "bocal_8_4",
        "bocal_4_4",
    ]
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
    # Pont partagé (tâche 45 sexies) : la griffe traînée irait au-dessus de l'agitateur. Carte de
    # la Maquette refaite à la vraie butée haute, axes 1,29 (tâche 45 decies) : seul bocal_0_0 est
    # posé à la main ; bocal_0_1, bocal_1_0 et bocal_2_0 par le chemin, bocal_2_1 par la table.
    assert "ne peut pas poser l'entonnoir" in sortie and "pose finale seulement) : 1" in sortie
    assert "  bocal_0_0  (1,2075 ; 0,06) : mât de la griffe à 1,0315" in sortie
    for bocal in ("bocal_0_1", "bocal_1_0", "bocal_2_0", "bocal_2_1"):
        assert f"  {bocal}  (" not in sortie
    assert "Bocaux posés par la machine grâce au chemin d'une exception : 3" in sortie
    for bocal, zone_du_mat in (
        ("bocal_0_1", "x 1,09-1,3, y 0,04-0,11"),
        ("bocal_1_0", "x 1,08-1,3, y 0,12-0,2"),
        ("bocal_2_0", "x 1,02-1,3, y 0,21-0,29"),
    ):
        chemin = f"{bocal}  zone du mât {zone_du_mat} : on y entre et on en sort en x"
        assert f"{chemin}, par x 1,22" in sortie


# ------------------- pose de l'entonnoir, griffe traînée (tâches 45 octies, 45 nonies, 45 decies)

LIGNE_BOCAL = "      - bocal: bocal_0_1"
ZONE = "        x: [1.09, 1.30]\n        y: [0.04, 0.11]\n"
ENTREE = "        entree_x: 1.22\n"
DESSUS = "          - {x: [0.78, 1.30], y: [0.12, 0.40]}   # au-dessus du chariot de l'agitateur\n"
DROITE = "          - {x: [1.09, 1.30], y: [0.04, 0.40]}   # à droite du chariot de l'agitateur\n"
# Les mâts de la griffe pour la pose de l'entonnoir (x bocal + 0,140 − 0,316, même y).
MATS = {
    "bocal_0_0": (1.0315, 0.06),
    "bocal_0_1": (1.1415, 0.06),
    "bocal_1_0": (1.0865, 0.1553),
    "bocal_2_0": (1.0315, 0.2506),
    "bocal_2_1": (1.1415, 0.2506),
}


def zone(x, y):
    return f"        x: {x}\n        y: {y}\n"


def interdit(x, y):
    """Le seul rectangle interdit de la carte à 1,29 (chariot de l'agitateur), compté jusqu'à
    x 1,08 (« moins de 1 cm ») : x ≤ 1,08 et y ≤ 0,11."""
    return x <= 1.08 + 1e-9 and y <= 0.11 + 1e-9


def test_exceptions_de_la_carte_a_1_29_dans_le_depot():
    # Carte refaite par la Maquette le 07/11 17 h, axes 1,29 (v45.121) : figée, chemin par x 1,22.
    exceptions = GRIFFE.y_min_mat.exceptions_butee_haute
    assert [e.bocal for e in exceptions] == ["bocal_0_1", "bocal_1_0", "bocal_2_0"]
    assert [(e.x, e.y) for e in exceptions] == [
        ((1.09, 1.30), (0.04, 0.11)),
        ((1.08, 1.30), (0.12, 0.20)),
        ((1.02, 1.30), (0.21, 0.29)),
    ]
    for exception in exceptions:
        assert exception.entree_x == 1.22 and "axes 1,29" in exception.source
        assert [(r.x, r.y) for r in exception.libres] == [
            ((0.78, 1.30), (0.12, 0.40)),
            ((1.09, 1.30), (0.04, 0.40)),
        ]
        # Aucune zone ne touche le rectangle interdit.
        (x0, x1), (y0, y1) = exception.x, exception.y
        assert not any(interdit(x, y) for x in (x0, x1) for y in (y0, y1))
    # Mât de la griffe = x bocal + 0,140 − 0,316 (la ventouse tient l'oreille).
    for bocal, mat in MATS.items():
        x, y = {
            "bocal_0_0": (1.2075, 0.06),
            "bocal_0_1": (1.3175, 0.06),
            "bocal_1_0": (1.2625, 0.1553),
            "bocal_2_0": (1.2075, 0.2506),
            "bocal_2_1": (1.3175, 0.2506),
        }[bocal]
        assert MACHINE.mat_griffe_entonnoir(x, y) == mat
    # bocal_0_0 (contact) : refusé, et dans aucune zone ; bocal_2_1 : la table le permet déjà.
    assert GRIFFE.y_min_mat.refuse_en_butee_haute(*MATS["bocal_0_0"])
    assert GRIFFE.y_min_mat.exception_requise(*MATS["bocal_0_0"]) is None
    assert not GRIFFE.y_min_mat.refuse_en_butee_haute(*MATS["bocal_2_1"])
    for bocal in ("bocal_0_1", "bocal_1_0", "bocal_2_0"):
        assert GRIFFE.y_min_mat.exception_requise(*MATS[bocal]).bocal == bocal


def test_exception_a_la_mauvaise_place_refusee_au_demarrage(reglages):
    # Une zone qui ne contient pas le vrai mât (1,1415 ; 0,06).
    remplacer(reglages / "machine.yaml", ZONE, zone("[1.15, 1.30]", "[0.04, 0.11]"))
    message = erreur_de(reglages)
    assert "exceptions_butee_haute → bocal_0_1 : la zone (x 1.15-1.3" in message
    assert "(1.1415 ; 0.06) : la mesure n'est pas à la bonne place" in message


def test_exception_qui_couvre_un_autre_bocal_refusee_au_demarrage(reglages):
    # bocal_0_1 (mât 1,1415 ; 0,06) et bocal_0_0 (1,0315 ; 0,06, refusé par la table) : non.
    remplacer(reglages / "machine.yaml", ZONE, zone("[1.00, 1.30]", "[0.04, 0.11]"))
    assert "la zone contient aussi le mât pour le bocal « bocal_0_0 »" in erreur_de(reglages)


def test_exception_hors_des_rectangles_libres_refusee_au_demarrage(reglages):
    # Tâche 45 decies : la table n'y compte pas, la zone doit être libre dans la mesure. Une
    # zone qui déborde sur le rectangle interdit (x 1,05) : refusée.
    remplacer(reglages / "machine.yaml", ZONE, zone("[1.05, 1.30]", "[0.10, 0.11]"))
    message = erreur_de(reglages)
    assert (
        "bocal_0_1 : la zone (x 1.05-1.3, y 0.1-0.11) n'est dans aucun rectangle libre" in message
    )


def test_exception_qui_contient_un_bocal_deja_permis_acceptee():
    # La zone de bocal_0_1 contient le mât de bocal_0_2 (1,2515 ; 0,06), et celle de bocal_2_0
    # celui de bocal_2_1 (1,1415 ; 0,2506), que la table permet déjà : rien de plus pour eux.
    assert MACHINE.mat_griffe_entonnoir(1.4275, 0.06) == (1.2515, 0.06)
    for mat in ((1.2515, 0.06), MATS["bocal_2_1"]):
        assert not GRIFFE.y_min_mat.refuse_en_butee_haute(*mat)
        assert GRIFFE.y_min_mat.exception_requise(*mat) is None
    assert GRIFFE.y_min_mat.refuse_en_butee_haute(1.1415, 0.06)


def test_exception_d_un_bocal_inconnu_refusee_au_demarrage(reglages):
    remplacer(reglages / "machine.yaml", LIGNE_BOCAL, "      - bocal: bocal_9_9")
    assert "exceptions_butee_haute → bocal_9_9 : bocal inconnu du stockage" in erreur_de(reglages)


def test_entree_du_chemin_hors_de_la_zone_refusee_au_demarrage(reglages):
    remplacer(reglages / "machine.yaml", ENTREE, "        entree_x: 1.05\n")
    assert "entree_x (1.05) hors de la zone (x 1.09-1.3)" in erreur_de(reglages)


def test_deux_entrees_differentes_refusees_au_demarrage(reglages):
    # D'une zone à l'autre (bocal_0_1 vers bocal_1_0), le trajet irait de x 1,25 à x 1,22 en
    # changeant de y : en diagonale. Une seule entrée pour toutes les zones.
    remplacer(reglages / "machine.yaml", ENTREE, "        entree_x: 1.25\n")
    assert "un seul entree_x pour toutes les zones (vu : 1.22, 1.25)" in erreur_de(reglages)


def test_chemin_hors_des_rectangles_libres_refuse_au_demarrage(reglages):
    # Sans le rectangle de droite, la ligne x = 1,22 (et la zone) ne sont dans aucun rectangle
    # libre de la mesure.
    remplacer(reglages / "machine.yaml", DROITE, "")
    message = erreur_de(reglages)
    assert "la ligne x = 1.22 (y 0.04-0.11) n'est dans aucun rectangle libre" in message


def test_rectangle_libre_mal_ecrit_refuse_au_demarrage(reglages):
    remplacer(reglages / "machine.yaml", DROITE, "          - {x: [1.30, 1.09], y: [0.04, 0.40]}\n")
    assert "bocal_0_1 → libres n° 2 : x et y du plus petit au plus grand" in erreur_de(reglages)


def test_exception_seulement_en_butee_haute_godet_ferme_bras_le_long_du_pont():
    haut = Pose(x=1.1415, y=0.06, z=GRIFFE.trajet.z, a=0, b=0)
    assert REGLES.exception_butee_haute(haut) == "bocal_0_1"
    assert REGLES.refus_pose(haut, Contexte()) is None
    # La règle d'avant partout ailleurs : sous la butée haute, godet ouvert, entre deux zones
    # (x 1,10, y 0,115 : la table y veut y ≥ 0,215), ou un autre bocal (bocal_0_0, mât 1,0315).
    assert REGLES.refus_pose(haut.avec(z=1.15), Contexte()) is not None
    assert REGLES.refus_pose(haut.avec(b=0.5), Contexte()) is not None
    assert REGLES.refus_pose(haut.avec(x=1.10, y=0.115), Contexte()) is not None
    assert REGLES.refus_pose(haut.avec(x=1.0315), Contexte()) is not None


def test_chemin_de_la_maquette_pour_entrer_et_sortir():
    # Arrivée par R1 (y ≥ 0,32) : en x jusqu'à 1,22, en y jusqu'à 0,06 (R2), puis en −x (R3).
    assert REGLES.passages_exception(1.00, 0.35, 1.1415, 0.06) == [(1.22, 0.35), (1.22, 0.06)]
    # Arrivée par R2 : d'abord en x jusqu'à 1,22.
    assert REGLES.passages_exception(1.30, 0.25, 1.1415, 0.06) == [(1.22, 0.25), (1.22, 0.06)]
    # Sortie : la même chose à l'envers.
    assert REGLES.passages_exception(1.1415, 0.06, 1.0865, 0.3459) == [(1.22, 0.06), (1.22, 0.3459)]
    # Même y, ou déjà à x 1,22 : un point de moins.
    assert REGLES.passages_exception(1.1415, 0.06, 1.2515, 0.06) == [(1.22, 0.06)]
    assert REGLES.passages_exception(1.22, 0.30, 1.1415, 0.06) == [(1.22, 0.06)]
    # Aucune des deux places n'a besoin de l'exception : pas de chemin.
    assert REGLES.passages_exception(1.30, 0.35, 1.2515, 0.06) == []
    # Chaque point du chemin et chaque pas entre eux, dans les règles de la griffe (butée haute).
    z = GRIFFE.trajet.z
    points = [(1.00, 0.35), (1.22, 0.35), (1.22, 0.06), (1.1415, 0.06)]
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        depart, arrivee = Pose(x=x0, y=y0, z=z, a=0, b=0), Pose(x=x1, y=y1, z=z, a=0, b=0)
        assert REGLES.refus_mouvement(depart, arrivee, Contexte()) is None
    # Le pas tout droit, lui, est refusé (il passerait au-dessus de l'agitateur).
    depart, arrivee = Pose(x=1.00, y=0.35, z=z, a=0, b=0), Pose(x=1.1415, y=0.06, z=z, a=0, b=0)
    assert REGLES.refus_mouvement(depart, arrivee, Contexte()) is not None


def test_la_griffe_sort_de_la_zone_par_le_chemin():
    # Griffe traînée à la pose de l'entonnoir sur bocal_0_1, puis elle va au fût : d'abord en +x
    # jusqu'à 1,22, puis son trajet habituel (y ≥ 0,36, puis en x).
    with Simulateur(reglages_simules(), LISTE, "vidange_fut") as simulation:
        griffe = griffe_du_simulateur(simulation)
        z = GRIFFE.trajet.z
        depart = Pose(x=1.1415, y=0.06, z=z, a=0, b=0)
        centre_x, centre_y = MACHINE.poste_fut.centre_fut
        points = griffe._chemin(depart, centre_x, centre_y)
        assert points[0] == (1.22, 0.06)
        assert points[1] == (1.22, max(GRIFFE.trajet.mat_y_min, centre_y))
        assert points[-1] == (centre_x, centre_y)
        # Et l'inverse : vers la zone, par x 1,22, en dernier en −x.
        retour = griffe._chemin(Pose(x=centre_x, y=centre_y, z=z, a=0, b=0), 1.1415, 0.06)
        assert retour[-2:] == [(1.22, 0.06), (1.1415, 0.06)]
        chemin = [(depart.x, depart.y), *points]
        for (x0, y0), (x1, y1) in zip(chemin, chemin[1:], strict=False):
            debut, fin = depart.avec(x=x0, y=y0), depart.avec(x=x1, y=y1)
            assert griffe.regles.refus_mouvement(debut, fin, Contexte()) is None, (x1, y1)


def test_lot_qui_pose_l_entonnoir_sur_bocal_0_1():
    # Entonnoir posé à la main sur bocal_0_2, puis la Préhension le pose sur bocal_0_1 (griffe
    # traînée par le chemin de la Maquette), la griffe y verse (elle sort de la zone par x 1,22),
    # puis la Préhension le reprend et le pose sur bocal_1_1.
    ordre = ["bocal_0_2", "bocal_0_1", "bocal_1_1"]
    mats = []

    def preparer(scenario, versement):
        scenario.entonnoir.ordre_de_remplissage = lambda bocaux: list(bocaux)
        griffe = versement.griffe
        executer = scenario.prehension.tete.executer

        def noter(pas, cible, poids):
            mats.append((pas.texte, griffe.bras.position()))
            executer(pas, cible, poids)

        scenario.prehension.tete.executer = noter

    planning, versement, griffe, pas_tete = lot_avec_la_tete_de_prehension(ordre, preparer)
    assert planning.fini, planning.probleme
    assert set(versement.doses) == set(ordre)
    chemins = [texte for texte, _, _ in pas_tete if "chemin de la griffe traînée" in texte]
    # Transport vers bocal_0_1 depuis bocal_0_2 (même y : x 1,22 seulement), reprise sur bocal_0_1
    # (tête vide, x 1,22), transport vers bocal_1_1 (sortie : x 1,22, puis y 0,1553).
    assert len(chemins) == 4
    # Le mât de la griffe n'est passé au-dessus de l'agitateur qu'à la pose (zone R3).
    for texte, mat in mats:
        if REGLES.en_butee_haute(mat.z) and GRIFFE.y_min_mat.refuse_en_butee_haute(mat.x, mat.y):
            assert REGLES.exception_butee_haute(mat) == "bocal_0_1", (texte, mat)


def test_lot_qui_pose_l_entonnoir_sur_les_bocaux_de_la_carte_a_1_29():
    # Tâche 45 decies : entonnoir posé à la main sur bocal_2_1, puis la Préhension le pose sur
    # bocal_2_0, bocal_1_0, bocal_0_1 (griffe traînée par le chemin, x 1,22), puis bocal_0_2.
    ordre = ["bocal_2_1", "bocal_2_0", "bocal_1_0", "bocal_0_1", "bocal_0_2"]
    mats = []

    def preparer(scenario, versement):
        scenario.entonnoir.ordre_de_remplissage = lambda bocaux: list(bocaux)
        griffe = versement.griffe
        executer = scenario.prehension.tete.executer

        def noter(pas, cible, poids):
            mats.append((pas.texte, griffe.bras.position()))
            executer(pas, cible, poids)

        scenario.prehension.tete.executer = noter

    planning, versement, griffe, pas_tete = lot_avec_la_tete_de_prehension(ordre, preparer)
    assert planning.fini, planning.probleme
    assert set(versement.doses) == set(ordre)
    assert [texte for texte, _, _ in pas_tete if "chemin de la griffe traînée" in texte]
    zones = {e.bocal for e in GRIFFE.y_min_mat.exceptions_butee_haute}
    vus = set()
    for texte, mat in mats:
        if not REGLES.en_butee_haute(mat.z):
            continue
        # Jamais au-dessus du chariot de l'agitateur (seul rectangle interdit de la carte).
        assert not (mat.x >= 0.78 and interdit(mat.x, mat.y)), (texte, mat)
        if GRIFFE.y_min_mat.refuse_en_butee_haute(mat.x, mat.y):
            bocal = REGLES.exception_butee_haute(mat)
            assert bocal in zones, (texte, mat)
            vus.add(bocal)
    assert vus == {"bocal_2_0", "bocal_1_0", "bocal_0_1"}
