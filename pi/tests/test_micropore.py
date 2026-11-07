"""Tâche 40 : le micropore côté Pi (tête, gestes appris, pose au poste et au vidage)."""

import json
import time
from dataclasses import replace

import pytest

from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.materiel import FausseFabrique, Materiel
from vidange.micropore import AvanceFluidnc, FichierAppris, TeteMicropore
from vidange.micropore.outil import main as outil
from vidange.micropore.simulation import distance_imaginaire
from vidange.mycelium.module import module_mycelium
from vidange.registre import Registre
from vidange.reglages import FormatAppris, GestesAppris, charger_reglages
from vidange.remplissage.module import module_remplissage
from vidange.remplissage.regles import Contexte, Pose, ReglesRemplissage
from vidange.remplissage.simulation import remplissage_du_simulateur
from vidange.simulateur import Simulateur

from .conftest import DOSSIER_PI
from .test_reglages import erreur_de, remplacer

LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
MICROPORE = MACHINE.micropore
I2C = REGLAGES.pesees.i2c
SIMULE = REGLAGES.simulateur.micropore
assert MICROPORE is not None and I2C is not None and SIMULE is not None


class Temps:
    """Une fausse horloge : attendre(s) la fait avancer."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def attendre(self, secondes: float) -> None:
        self.t += secondes


# ---------------------------------------------------------------- réglages


def test_reglages_du_micropore():
    assert MICROPORE.avance.carte == "mycelium_lavage" and MICROPORE.avance.lettre == "X"
    assert set(MICROPORE.formats) <= set(MACHINE.griffe.formats)
    assert MICROPORE.tof_signal == I2C.vl6180x.signal
    # Chaque format a sa rangée du fond ; les gestes du simulateur sont appris pour tous.
    for nom, format in MICROPORE.formats.items():
        assert [rangee.fond for rangee in format.rangees].count(True) == 1
        assert nom in SIMULE.appris.formats


@pytest.mark.parametrize(
    "fichier, ancien, nouveau, message",
    [
        (
            "machine.yaml",
            "    seau_b:\n      fond_poids_min_kg",
            "    seau_z:\n      fond_poids_min_kg",
            "micropore → formats : format de seau inconnu « seau_z »",
        ),
        ("machine.yaml", "lame_bas_deg: 38", "lame_bas_deg: 300", "lame_bas_deg"),
        (
            "machine.yaml",
            "{hauteur_m: 0.19, rayon_paroi_m: 0.129",
            "{hauteur_m: 0.50, rayon_paroi_m: 0.129",
            "plus haut que le seau",
        ),
        (
            "machine.yaml",
            "carte: mycelium_lavage, lettre: X}",
            "carte: mycelium_lavage, lettre: Y}",
            "est déjà celle de l'axe",
        ),
        ("machine.yaml", "apprentissage_pas_plats: 8", "apprentissage_pas_plats: 2", "course"),
        ("machine.yaml", "camera: micropore", "camera: micropore_absente", "micropore_absente"),
        (
            "simulateur.yaml",
            "seau_a: {approche_deg: 73.12",
            "seau_a: {approche_deg: 78.12",
            "ne vont pas dans l'ordre",
        ),
        ("simulateur.yaml", "escamote_deg: 40", "escamote_deg: 400", "hors de la plage"),
    ],
)
def test_reglages_faux_du_micropore(reglages, fichier, ancien, nouveau, message):
    remplacer(reglages / fichier, ancien, nouveau)
    assert message in erreur_de(reglages)


# ---------------------------------------------------------------- gestes appris


VALEURS = FormatAppris(
    approche_deg=73.0, contact_deg=75.5, appui_deg=84.5, contact_mm=49, camera_rouleau_deg=32
)


def test_gestes_appris_notes_relus_et_annules(tmp_path):
    chemin = tmp_path / "micropore-appris.yaml"
    appris = FichierAppris(chemin)
    assert appris.escamote_deg is None and appris.format("seau_a") is None
    assert appris.annuler("karulium") is None
    assert appris.noter_escamote(40, "karulium") == 1
    assert appris.noter_format("seau_a", VALEURS, "karulium") == 2
    assert appris.noter_format("seau_a", replace_format(contact_deg=76.0), "gael") == 3
    # Relu tel quel après un redémarrage du Pi.
    relu = FichierAppris(chemin)
    assert relu.erreur is None
    assert relu.escamote_deg == 40 and relu.format("seau_a").contact_deg == 76.0
    # Annuler défait le dernier changement, puis celui d'avant ; tout reste dans l'historique.
    assert relu.annuler("karulium") == 3
    assert relu.format("seau_a") == VALEURS
    assert relu.annuler("karulium") == 2
    assert relu.format("seau_a") is None and relu.escamote_deg == 40
    historique = FichierAppris(chemin).gestes.historique
    assert [(c.numero, c.annule, c.annule_par) for c in historique] == [
        (1, None, None),
        (2, None, 5),
        (3, None, 4),
        (4, 3, None),
        (5, 2, None),
    ]
    assert historique[2].qui == "gael" and historique[2].avant == VALEURS


def replace_format(**changements) -> FormatAppris:
    return VALEURS.model_copy(update=changements)


def test_gestes_appris_illisibles(tmp_path):
    chemin = tmp_path / "micropore-appris.yaml"
    chemin.write_text("escamote_deg: beaucoup\n", encoding="utf-8")
    appris = FichierAppris(chemin)
    assert appris.erreur is not None and "escamote_deg" in appris.erreur
    assert appris.escamote_deg is None


# ---------------------------------------------------------------- la tête


class Banc:
    """La vraie tête sur le faux boîtier (sans simulateur)."""

    def __init__(self, distance_mm: int | None = 77) -> None:
        self.temps = Temps()
        fabrique = FausseFabrique(LISTE)
        plages = [(voie.angle_min_deg, voie.angle_max_deg) for voie in I2C.pca9685.voies.values()]
        self.boitier = fabrique.carte_pesee(I2C.carte).brancher_boitier(plages)
        self.boitier.distance_mm = distance_mm
        self.materiel = Materiel(LISTE, fabrique, seulement=[I2C.carte])
        self.appris = FichierAppris(None, GestesAppris(escamote_deg=40))
        self.tete = TeteMicropore(MICROPORE, I2C, self.materiel, self.appris, self.temps)

    def apres(self, secondes: float) -> None:
        self.temps.attendre(secondes)
        self.tete.observer()


def test_tete_vue_escamotee_seulement_apres_l_ordre_et_au_tof():
    banc = Banc()
    tete = banc.tete
    banc.tete.lire()
    # Jamais commandée : on ne sait pas.
    assert tete.escamotee() is None
    tete.escamoter()
    assert banc.boitier.angles_deg[:2] == (40, MICROPORE.servos.lame_repos_deg)
    # Une distance lue avant la fin du mouvement ne compte pas.
    tete.lire()
    assert tete.distance_mm() is None and tete.escamotee() is None
    banc.apres(MICROPORE.servos.mouvement_s)
    assert tete.escamotee() is True
    # Tête sortie au ToF (ou bloquée) : pas escamotée.
    banc.boitier.distance_mm = 40
    banc.apres(0.1)
    assert tete.escamotee() is False
    # ToF muet : on ne sait pas.
    banc.boitier.distance_mm = 77
    banc.boitier.tof_muet = True
    banc.apres(0.1)
    assert tete.escamotee() is None
    banc.boitier.tof_muet = False
    banc.apres(0.1)
    assert tete.escamotee() is True
    # Lame en bas, ou tête commandée ailleurs : pas escamotée, même si le ToF le croit.
    tete.commander(lame=MICROPORE.servos.lame_bas_deg)
    assert tete.escamotee() is False
    tete.escamoter()
    tete.commander(escamotage=60)
    banc.apres(1)
    assert tete.escamotee() is False
    # Une mesure trop vieille ne compte pas.
    tete.escamoter()
    banc.apres(1)
    banc.temps.attendre(MICROPORE.tof.fraicheur_s + 0.1)
    assert tete.distance_mm() is None


def test_battement_des_angles():
    banc = Banc()
    banc.tete.escamoter()
    ordres = banc.boitier.ordres
    banc.apres(MICROPORE.servos.battement_s / 2)
    assert banc.boitier.ordres == ordres
    banc.apres(MICROPORE.servos.battement_s / 2)
    # Une écriture par voie commandée (escamotage et lame).
    assert banc.boitier.ordres == ordres + 2
    assert banc.tete.prochain() == pytest.approx(banc.temps() + MICROPORE.servos.battement_s)


def test_carte_redemarree_angles_renvoyes_et_tof_relu_apres_stabilisation():
    banc = Banc()
    tete = banc.tete
    tete.escamoter()
    banc.apres(1)
    assert tete.escamotee() is True
    banc.boitier.redemarrer()
    banc.boitier.demarrages += 4  # pas forcément de +1 (décisions, PR n° 84, point 4)
    assert banc.boitier.angles_deg[0] is None
    banc.apres(0.1)
    # Angles renvoyés tout de suite ; ToF pas cru avant la stabilisation des servos.
    assert tete.redemarrages_vus == 1
    assert banc.boitier.angles_deg[:2] == (40, MICROPORE.servos.lame_repos_deg)
    assert tete.escamotee() is None
    banc.apres(MICROPORE.servos.stabilisation_s)
    assert tete.escamotee() is True


def test_premier_ordre_perdu_renvoye():
    banc = Banc()
    banc.tete.angles = {banc.tete.voie_escamotage: 40.0}
    banc.tete.lire()
    assert banc.tete.demarrages == 1
    assert banc.boitier.angles_deg[0] == 40


def test_avance_fluidnc_en_relatif():
    carte = FauxFluidnc(axes="XYZABC", vitesse_rapide_mm_min=60000)
    liaison = Liaison(MICROPORE.avance.carte, REGLAGES.fluidnc, ouvrir=carte.ouvrir)
    liaison.demarrer()
    try:
        liaison.attendre_connexion(5)
        avance = AvanceFluidnc(liaison, MICROPORE.avance)
        avance.avancer(13, 20)
        attendre(avance.fini)
        avance.avancer(-0.5, 20)
        attendre(avance.fini)
    finally:
        liaison.arreter()
    lignes = [ligne for ligne in carte.lignes_recues if ligne.startswith("G")]
    assert lignes == [
        "G91 G1 X13.000 F1200",
        "G90",
        "G4 P0",
        "G91 G1 X-0.500 F1200",
        "G90",
        "G4 P0",
    ]
    assert carte.positions["X"] == pytest.approx(12.5)


def attendre(condition, delai: float = 5.0) -> None:
    fin = time.monotonic() + delai
    while not condition():
        assert time.monotonic() < fin, "pas arrivé à temps"
        time.sleep(0.01)


# ---------------------------------------------------------------- règle 10


def test_regle_10_le_plateau_ne_bouge_en_hauteur_que_tete_escamotee():
    regles = ReglesRemplissage(MACHINE)
    depart = Pose(y=0.42, z=0.40, a=0.0, barres=0.19, pousseur=0.0)
    for etat, mot in ((None, "pas connue"), (False, "pas escamotée")):
        contexte = Contexte(True, None, True, micropore_escamote=etat)
        refus = regles.refus_mouvement(depart, replace(depart, z=0.45), contexte)
        assert refus is not None and "micropore" in refus and mot in refus
        # Tourner le plateau reste permis (pose des morceaux).
        assert regles.refus_mouvement(depart, replace(depart, a=90.0), contexte) is None
    contexte = Contexte(True, None, True, micropore_escamote=True)
    assert regles.refus_mouvement(depart, replace(depart, z=0.45), contexte) is None


# ---------------------------------------------------------------- scénario du simulateur


def jouer(regler=lambda scenario: None, reglages=REGLAGES, registre=None):
    with Simulateur(reglages, LISTE, "remplissage") as simulation:
        options = {} if registre is None else {"registre": registre}
        scenario = remplissage_du_simulateur(simulation, **options)
        assert scenario.micropore is not None
        textes: list[tuple[str, float, float]] = []
        executer = scenario.chariot.executer

        def noter(pas, cible):
            textes.append((pas.texte, cible.y, cible.z))
            executer(pas, cible)

        scenario.chariot.executer = noter
        regler(scenario.micropore)
        modules = [
            module_remplissage(
                scenario.remplissage, scenario.prehension, scenario.mycelium, scenario.plan
            ),
            module_mycelium(scenario.mycelium),
        ]
        planning = simulation.jouer(modules)
    return planning, scenario, textes


def morceaux_poses(textes) -> int:
    return sum(1 for texte, _, _ in textes if texte.startswith("micropore 9) : coupe"))


def test_scenario_micropore_sur_les_2_seaux(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    planning, scenario, textes = jouer(registre=registre)
    assert planning.fini, planning.probleme
    simule = scenario.micropore
    # 2 seaux × 2 rangées × 4 trous, tous vus couverts du premier coup.
    assert morceaux_poses(textes) == 16 and simule.vision.tours == 2
    assert [couvert for _, _, couvert in simule.vision.controles] == [True] * 16
    assert simule.micropore.morceaux_restants == MICROPORE.rouleau.morceaux - 16
    pose = MICROPORE.pose
    par_morceau = pose.avance_mm + pose.avant_coupe_mm - pose.tension_mm
    assert simule.avance.ruban_mm == pytest.approx(16 * par_morceau)
    # Rangées du haut au poste, rangées du fond au vidage (règle C2), plateau à ruban_z − hauteur.
    rangees = [(y, z) for texte, y, z in textes if texte.startswith("micropore 2)")]
    a, b = MICROPORE.formats["seau_a"].rangees, MICROPORE.formats["seau_b"].rangees
    poste_y = MACHINE.positions["remplissage_poste"]["remplissage_y"]
    attendu = [
        (poste_y, MICROPORE.ruban_z - a[0].hauteur_m),
        (0.42, MICROPORE.ruban_z - a[1].hauteur_m),
        (poste_y, MICROPORE.ruban_z - b[0].hauteur_m),
        (0.42, MICROPORE.ruban_z - b[1].hauteur_m),
    ]
    assert [v for paire in rangees for v in paire] == pytest.approx(
        [v for paire in attendu for v in paire]
    )
    # Rien à vérifier, une mesure par seau au registre.
    assert registre.trouver("seau", "S0101")["a_verifier"] is None
    mesures = registre.lire("SELECT valeur FROM mesures WHERE nom = 'micropore_morceaux'")
    assert [m["valeur"] for m in mesures] == [8, 8]
    assert registre.alarmes_ouvertes() == []
    registre.fermer()


def test_le_plateau_ne_bouge_en_hauteur_que_tete_vue_escamotee():
    # Chaque mouvement du plateau en hauteur : tête escamotée au ToF juste avant.
    vus: list[tuple[str, bool | None]] = []

    def regler(simule):
        executer = simule.micropore.remplissage.chariot.executer

        def noter(pas, cible):
            if "z" in pas.cibles:
                vus.append((pas.texte, simule.tete.escamotee()))
            executer(pas, cible)

        simule.micropore.remplissage.chariot.executer = noter

    planning, _, _ = jouer(regler)
    assert planning.fini, planning.probleme
    assert vus and all(escamotee is True for _, escamotee in vus), vus


def test_tof_qui_ne_voit_pas_l_escamotage_le_plateau_ne_bouge_pas():
    def regler(simule):
        simule.physique.tof_fige_mm = 40

    planning, scenario, textes = jouer(regler)
    assert not planning.fini
    assert "micropore" in planning.probleme
    # Aucun mouvement du plateau en hauteur.
    hauteurs = {z for _, _, z in textes}
    assert len(hauteurs) <= 1, hauteurs


def test_tof_perdu_pendant_le_cycle_alarme_et_plateau_arrete():
    def regler(simule):
        executer = simule.micropore.remplissage.chariot.executer

        def noter(pas, cible):
            if pas.texte.startswith("micropore 11) : morceau devant"):
                simule.physique.tof_fige_mm = 40
            executer(pas, cible)

        simule.micropore.remplissage.chariot.executer = noter

    planning, scenario, textes = jouer(regler)
    assert not planning.fini
    assert "pas vue escamotée" in planning.probleme
    premier = next(i for i, (t, _, _) in enumerate(textes) if t.startswith("micropore 11) : m"))
    assert {z for _, _, z in textes[premier:]} == {textes[premier][2]}


def test_pas_de_contact_la_tete_recule_et_le_seau_est_a_verifier(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")

    def regler(simule):
        simule.physique.sans_paroi = True

    planning, scenario, textes = jouer(regler, registre=registre)
    # Le remplissage continue, sans micropore.
    assert planning.fini, planning.probleme
    assert morceaux_poses(textes) == 0
    assert "pas de contact" in registre.trouver("seau", "S0101")["a_verifier"]
    assert any("pas de contact" in a["message"] for a in registre.alarmes_ouvertes())
    assert scenario.micropore.tete.escamotee() is True
    registre.fermer()


def test_trou_decouvert_puis_nouvel_essai():
    def regler(simule):
        simule.vision.rates = 1

    planning, scenario, textes = jouer(regler)
    assert planning.fini, planning.probleme
    assert morceaux_poses(textes) == 17
    controles = scenario.micropore.vision.controles
    assert [c for _, _, c in controles[:2]] == [False, True]
    # Le nouvel essai est sur le même trou.
    assert controles[0][:2] == controles[1][:2]
    assert not any("découvert" in m for m in scenario.micropore.micropore.messages)


def test_trou_decouvert_deux_fois_alerte(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")

    def regler(simule):
        simule.vision.rates = 2

    planning, scenario, textes = jouer(regler, registre=registre)
    assert planning.fini, planning.probleme
    # 2 essais sur le trou 1, puis les 15 autres.
    assert morceaux_poses(textes) == 17
    assert "trou 1 : découvert après 2 essais" in registre.trouver("seau", "S0101")["a_verifier"]
    registre.fermer()


def test_rangee_trop_haute_pas_posee(reglages):
    # Rangée du haut du seau A à 1 cm du fond : plateau à 0,581 > 0,575 (règle 9).
    remplacer(
        reglages / "machine.yaml",
        "{hauteur_m: 0.19, rayon_paroi_m: 0.129",
        "{hauteur_m: 0.01, rayon_paroi_m: 0.129",
    )
    remplacer(
        reglages / "machine.yaml",
        "{hauteur_m: 0.07, rayon_paroi_m: 0.120",
        "{hauteur_m: 0.10, rayon_paroi_m: 0.120",
    )
    planning, scenario, textes = jouer(reglages=charger_reglages(reglages))
    assert planning.fini, planning.probleme
    assert max(z for _, _, z in textes) <= MACHINE.axes["plateau_z"].course[1] + 1e-9
    assert any("rangée 1 trop haute" in m for m in scenario.micropore.micropore.messages)
    # Les 3 autres rangées sont posées.
    assert morceaux_poses(textes) == 12


def test_format_inconnu_ou_pas_appris_rempli_sans_micropore(reglages):
    remplacer(
        reglages / "machine.yaml",
        "    seau_b:\n      fond_poids_min_kg: 1.5\n",
        "    seau_b_absent:\n      fond_poids_min_kg: 1.5\n",
    )
    remplacer(reglages / "simulateur.yaml", "      seau_b: {", "      seau_b_absent: {")
    # seau_b_absent n'est pas un format de la griffe : on retire seulement seau_b du micropore.
    texte = (reglages / "machine.yaml").read_text(encoding="utf-8")
    debut = texte.index("    seau_b_absent:\n")
    fin = texte.index("    seau_c:\n", debut)
    (reglages / "machine.yaml").write_text(texte[:debut] + texte[fin:], encoding="utf-8")
    texte = (reglages / "simulateur.yaml").read_text(encoding="utf-8")
    debut = texte.index("      seau_b_absent: {")
    fin = texte.index("\n", debut) + 1
    (reglages / "simulateur.yaml").write_text(texte[:debut] + texte[fin:], encoding="utf-8")
    planning, scenario, textes = jouer(reglages=charger_reglages(reglages))
    assert planning.fini, planning.probleme
    assert morceaux_poses(textes) == 8
    assert any("seau_b » inconnu du micropore" in m for m in scenario.micropore.micropore.messages)


def test_format_pas_appris_rempli_sans_micropore(reglages):
    texte = (reglages / "simulateur.yaml").read_text(encoding="utf-8")
    debut = texte.index("      seau_b: {")
    fin = texte.index("\n", debut) + 1
    (reglages / "simulateur.yaml").write_text(texte[:debut] + texte[fin:], encoding="utf-8")
    planning, scenario, textes = jouer(reglages=charger_reglages(reglages))
    assert planning.fini, planning.probleme
    assert morceaux_poses(textes) == 8
    assert any("seau_b » pas appris" in m for m in scenario.micropore.micropore.messages)


def test_carte_redemarree_pendant_une_pose():
    def regler(simule):
        executer = simule.micropore.remplissage.chariot.executer
        fait = []

        def noter(pas, cible):
            executer(pas, cible)
            if pas.texte.startswith("micropore 7)") and not fait:
                fait.append(True)
                simule.boitier.redemarrer()

        simule.micropore.remplissage.chariot.executer = noter

    planning, scenario, textes = jouer(regler)
    assert planning.fini, planning.probleme
    simule = scenario.micropore
    assert simule.tete.redemarrages_vus == 1
    # Le morceau coupé pendant le redémarrage n'est pas compté couvert : un nouvel essai.
    assert len(simule.vision.controles) == 16
    assert morceaux_poses(textes) == 17
    # Tête de nouveau escamotée, vue au ToF, avant de reprendre.
    i = next(i for i, (t, _, _) in enumerate(textes) if t.startswith("micropore 7)"))
    suite = [t for t, _, _ in textes[i:]]
    assert "micropore 1) : tête escamotée" in suite[: suite.index("micropore 3) : approche")]


def test_alerte_du_rouleau_une_fois(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")

    def regler(simule):
        simule.micropore.morceaux_restants = MICROPORE.rouleau.alerte_sous + 1

    planning, scenario, _ = jouer(regler, registre=registre)
    assert planning.fini, planning.probleme
    alertes = [a for a in registre.alarmes_ouvertes() if "rouleau bientôt vide" in a["message"]]
    assert len(alertes) == 1
    registre.fermer()


def test_rouleau_vide_rempli_sans_micropore():
    def regler(simule):
        simule.micropore.morceaux_restants = 3

    planning, scenario, textes = jouer(regler)
    assert planning.fini, planning.probleme
    assert morceaux_poses(textes) == 3
    assert scenario.micropore.micropore.morceaux_restants == 0
    assert any("rouleau vide" in m for m in scenario.micropore.micropore.messages)


# ---------------------------------------------------------------- l'outil


def lancer_outil(donnees, *arguments, temps=None):
    temps = temps or Temps()
    return outil(
        ["--faux", "--donnees", str(donnees), *arguments],
        attendre=temps.attendre,
        horloge=temps,
    )


def test_outil_apprend_escamote_puis_un_format(tmp_path, capsys):
    donnees = tmp_path / "donnees"
    # Format pas appris avant l'angle escamoté.
    assert lancer_outil(donnees, "apprendre", "seau_a", "--camera-rouleau", "32") == 2
    # Trop en avant : la tête n'est pas vue escamotée, rien n'est appris.
    assert lancer_outil(donnees, "escamote", "60") == 1
    assert lancer_outil(donnees, "escamote", "40") == 0
    # Tête libre : 10° de plus, 7,85 mm de moins au ToF.
    capsys.readouterr()
    assert lancer_outil(donnees, "servo", "50") == 0
    assert "ToF 69 mm" in capsys.readouterr().out
    assert lancer_outil(donnees, "apprendre", "seau_a", "--camera-rouleau", "32") == 0
    appris = FichierAppris(donnees / "micropore-appris.yaml")
    format = appris.format("seau_a")
    contact = SIMULE.appris.formats["seau_a"].contact_deg
    # Le contact est trouvé à moins de tof → precision_mm près, jamais après le vrai.
    assert (
        contact - MICROPORE.tof.precision_mm / MICROPORE.servos.mm_par_degre - 1
        <= (format.contact_deg)
        <= contact
    )
    assert format.approche_deg < format.contact_deg < format.appui_deg
    assert format.camera_rouleau_deg == 32
    assert lancer_outil(donnees, "etat") == 0
    assert "seau_a" in capsys.readouterr().out
    # Format inconnu.
    assert lancer_outil(donnees, "apprendre", "seau_z", "--camera-rouleau", "32") == 2
    # Annuler, historique.
    assert lancer_outil(donnees, "annuler") == 0
    assert FichierAppris(donnees / "micropore-appris.yaml").format("seau_a") is None
    capsys.readouterr()
    assert lancer_outil(donnees, "historique") == 0
    sortie = capsys.readouterr().out
    assert "annule le n° 2" in sortie and "(annulé par le n° 3)" in sortie


def test_outil_sans_paroi_n_apprend_rien(tmp_path, capsys):
    donnees = tmp_path / "donnees"
    temps = Temps()
    fabrique = FausseFabrique(LISTE)
    plages = [(voie.angle_min_deg, voie.angle_max_deg) for voie in I2C.pca9685.voies.values()]
    boitier = fabrique.carte_pesee(I2C.carte).brancher_boitier(plages)
    voie = list(I2C.pca9685.voies).index(MICROPORE.servo_escamotage)
    # Pas de seau devant la tête : elle va jusqu'à sa butée.
    boitier.tof_selon_angles = lambda angles: distance_imaginaire(
        MICROPORE, angles[voie] if angles[voie] is not None else 40, 40, None
    )

    def lancer(*arguments):
        return outil(
            ["--donnees", str(donnees), *arguments],
            fabrique=fabrique,
            attendre=temps.attendre,
            horloge=temps,
        )

    assert lancer("escamote", "40") == 0
    assert lancer("apprendre", "seau_a", "--camera-rouleau", "32") == 1
    assert "butée" in capsys.readouterr().err
    assert FichierAppris(donnees / "micropore-appris.yaml").format("seau_a") is None
    # Retour escamotée à la fin.
    assert boitier.angles_deg[voie] == 40
    # ToF muet : rien n'est appris non plus.
    boitier.tof_muet = True
    assert lancer("apprendre", "seau_a", "--camera-rouleau", "32") == 1


def test_outil_charger_remet_le_compteur(tmp_path):
    donnees = tmp_path / "donnees"
    assert lancer_outil(donnees, "charger") == 0
    etat = json.loads((donnees / "micropore.json").read_text(encoding="utf-8"))
    assert etat == {"morceaux_restants": MICROPORE.rouleau.morceaux, "alerte_rouleau_faite": False}
