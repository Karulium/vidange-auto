"""Lavage des couvercles et des bocaux (tâche 21 bis) : réglages, couvercles au simulateur avec
leur retourneur (faux), lave-bocal, bocaux et seaux jamais en même temps."""

import pytest

from vidange.chef import ErreurEtape
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.lavage.couvercles import MESSAGE_BARRIERE, LavageCouvercles, ecart_angle
from vidange.lavage.module import module_lavage_bocaux, module_lavage_couvercles
from vidange.lavage.simulation import (
    bocaux_du_simulateur,
    couvercles_du_simulateur,
    lavage_du_simulateur,
)
from vidange.reglages import charger_reglages
from vidange.simulateur import Simulateur
from vidange.simulateur.outil import main as simulateur

from .conftest import DOSSIER_PI
from .test_reglages import erreur_de, remplacer

LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
LAVAGE = MACHINE.lavage
assert LAVAGE is not None and LAVAGE.couvercles is not None and LAVAGE.lave_bocal is not None
COUVERCLES = LAVAGE.couvercles
SIMULE = REGLAGES.simulateur.lavage
assert SIMULE is not None


def jouer_couvercles(regler=lambda couvercles: None):
    """Rejoue le scénario « lavage_couvercles » ; rend le planning et le lavage des couvercles."""
    with Simulateur(REGLAGES, LISTE, "lavage_couvercles") as simulation:
        couvercles = couvercles_du_simulateur(simulation)
        regler(couvercles)
        planning = simulation.jouer([module_lavage_couvercles(couvercles, SIMULE.couvercles)])
        return planning, couvercles


def jouer_bocaux(regler=lambda bocaux: None):
    with Simulateur(REGLAGES, LISTE, "lavage_bocaux") as simulation:
        bocaux = bocaux_du_simulateur(simulation)
        regler(bocaux)
        planning = simulation.jouer([module_lavage_bocaux(bocaux, SIMULE.bocaux)])
        return planning, bocaux


def etapes(planning) -> list[str]:
    return [ligne.etape for ligne in planning.lignes]


def mouvements(lavage) -> list:
    return lavage.prehension.tete._etat.mouvements


# ---------------------------------------------------------------- réglages


def test_reglages_des_couvercles_et_du_lave_bocal():
    assert COUVERCLES.centre == (0.352, 0.65) and COUVERCLES.appui_n == 15
    assert COUVERCLES.contact_trop_haut_z == 0.735
    assert COUVERCLES.formats["seau_a"].bas_dessous_z == 0.638
    assert COUVERCLES.formats["seau_d"].decalage_m == 0.023
    assert COUVERCLES.retourneur.lacher == (0.9675, 0.53)
    assert (COUVERCLES.retourneur.barres_fermees_m, COUVERCLES.retourneur.barres_ouvertes_m) == (
        0.19,
        0.30,
    )
    assert "bocal_vide" in MACHINE.prehension.objets  # type: ignore[union-attr]


def test_reglages_des_couvercles_verifies(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "decalage_m: 0.023}", "decalage_m: 0.08}")
    remplacer(machine, "seau_b: {bas_dessous_z: 0.637", "seau_z: {bas_dessous_z: 0.637")
    message = erreur_de(reglages)
    assert "couvercles → formats → seau_d : axe de la tête à 0.08" in message
    assert "lavage → couvercles → formats : il manque « seau_b »" in message


def test_barres_du_retourneur_verifiees(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "      barres_ouvertes_m: 0.30", "      barres_ouvertes_m: 0.10")
    assert "barres ouvertes plus loin que fermées" in erreur_de(reglages)


def test_ecart_angle():
    assert ecart_angle(10, 350) == pytest.approx(20)
    assert ecart_angle(350, 10) == pytest.approx(-20)


# ---------------------------------------------------------------- couvercles


def test_deux_couvercles_laves_et_retournes_au_simulateur():
    planning, couvercles = jouer_couvercles()
    assert planning.fini, planning.probleme
    un = [
        "prendre_le_couvercle",
        "laver_le_dessous",
        "retourner",
        "laver_le_dessus",
        "remettre_a_l_endroit",
        "poser_le_couvercle",
    ]
    assert etapes(planning) == [
        "verifier_le_retourneur",
        "remplir",
        *un,
        *un,
        "vider",
        "finir_la_serie",
    ]
    assert couvercles.couvercles_laves == 2 and couvercles.a_verifier == []
    assert couvercles.prehension.objet is None and not couvercles.eau.eau_dans_le_fut
    # Barres : ouvertes pour reprendre le couvercle, refermées ensuite ; 4 chutes.
    barres = couvercles.retourneur.historique  # type: ignore[attr-defined]
    assert barres == [0.30, 0.19] * 4
    # Noyau à 100 tr/min par tranches de 0,5 s (300°), 10 tranches par face.
    brossages = [m for m in mouvements(couvercles) if m.position.startswith("brossage du")]
    assert len(brossages) == 2 * 2 * 10
    debut, fin = brossages[0].axes["lavage_noyau"]
    assert fin - debut == pytest.approx(300)
    debut, fin = brossages[0].axes["prehension_a"]
    assert abs(fin - debut) == pytest.approx(15 * 6 * 0.5)


def test_couvercle_pose_decale_et_repere_a_son_angle():
    planning, couvercles = jouer_couvercles()
    assert planning.fini, planning.probleme
    decalage = MACHINE.prehension.decalage_mat_x  # type: ignore[union-attr]
    trajets = [m.axes for m in mouvements(couvercles) if m.position == "trajet"]
    axes = [(t["pont_x"][1] + decalage, t["chariot_y"][1]) for t in trajets if "pont_x" in t]
    # Couvercle A : centre décalé de 21 mm dans la direction (+0,26 ; −0,97).
    attendu = (0.352 + 0.021 * 0.26 / 1.00424, 0.65 - 0.021 * 0.97 / 1.00424)
    assert axes[1] == pytest.approx(attendu, abs=1e-4)
    # Repère : 200° tête à 0 → mis à 60° (la tête tourne de −140°).
    rotation = next(m for m in mouvements(couvercles) if m.position.startswith("repère du"))
    assert rotation.axes["prehension_a"] == pytest.approx((0, -140))
    # Descente au-dessus du noyau : palpage jusqu'à 0,735, puis appui à 0,638 + 0,015.
    appui = next(m for m in mouvements(couvercles) if m.position.startswith("appui du couvercle"))
    assert appui.axes["prehension_z"][1] == pytest.approx(0.653)


def test_couvercle_qui_glisse_une_fois():
    def regler(couvercles):
        couvercles.vision.glissements = {5}

    planning, couvercles = jouer_couvercles(regler)
    assert planning.fini, planning.probleme
    textes = [m.position for m in mouvements(couvercles)]
    assert "couvercle qui glisse : remontée de 2 mm" in textes
    # Le repère est ramené à son angle de photo malgré le glissement : rien à vérifier.
    assert couvercles.a_verifier == []


def test_couvercle_qui_glisse_deux_fois():
    def regler(couvercles):
        couvercles.vision.glissements = {5, 8}

    planning, couvercles = jouer_couvercles(regler)
    assert not planning.fini
    assert etapes(planning)[-1] == "laver_le_dessous"
    assert "le couvercle a glissé 2 fois sur le noyau" in planning.probleme
    # Arrosage coupé par l'arrêt du module.
    assert not couvercles.eau.pompe


def test_repere_pas_revenu_couvercle_a_verifier():
    alertes = []

    def regler(couvercles):
        # 13e lecture : la 2e photo du premier couvercle (1 + 1 + 10 contrôles + 1).
        couvercles.vision.glissements = {13}
        couvercles._alerter = alertes.append

    planning, couvercles = jouer_couvercles(regler)
    assert planning.fini, planning.probleme
    assert couvercles.a_verifier == ["seau_a"]
    assert "couvercle seau_a à vérifier : repère à" in alertes[0]


def test_plateau_flottant_declenche_trop_haut():
    def regler(couvercles):
        tete = couvercles.prehension.tete
        executer = tete.executer

        def executer_avec_obstacle(pas, cible, poids):
            tete.decalage_contact_m = 0.1 if pas.texte == "descente au-dessus du noyau" else 0.0
            executer(pas, cible, poids)

        tete.executer = executer_avec_obstacle

    planning, _ = jouer_couvercles(regler)
    assert not planning.fini
    assert "plateau flottant déclenché face à 0,805 m, au-dessus de 0,735 m" in planning.probleme


def test_mode_refuse_si_le_bac_n_est_pas_trouve():
    planning, couvercles = jouer_couvercles(lambda c: setattr(c.vision, "place", None))
    assert not planning.fini and etapes(planning) == ["verifier_le_retourneur"]
    assert "la caméra ne trouve pas le bac et la tige du retourneur" in planning.probleme
    assert not couvercles.retourneur_verifie
    planning, _ = jouer_couvercles(lambda c: setattr(c.vision, "place", (0.001, 0.008)))
    assert "tige du retourneur à 8 mm de sa place (au plus 5 mm)" in planning.probleme


def test_couvercle_pas_retourne_nouvelle_chute():
    planning, couvercles = jouer_couvercles(lambda c: setattr(c.vision, "rates", 1))
    assert planning.fini, planning.probleme
    # Une chute de plus que les 4 prévues.
    assert couvercles.retourneur.historique == [0.30, 0.19] * 5  # type: ignore[attr-defined]


def test_couvercle_pas_retourne_deux_fois_alerte():
    planning, _ = jouer_couvercles(lambda c: setattr(c.vision, "rates", 2))
    assert not planning.fini and etapes(planning)[-1] == "retourner"
    assert "couvercle pas retourné après 2 chutes" in planning.probleme


def test_couvercle_hors_du_bac_alerte():
    planning, _ = jouer_couvercles(lambda c: setattr(c.vision, "hors_du_bac", True))
    assert not planning.fini
    assert "couvercle hors du bac après la chute" in planning.probleme


def test_barriere_coupee_pause_avec_message():
    with Simulateur(REGLAGES, LISTE, "lavage_couvercles") as simulation:
        couvercles = couvercles_du_simulateur(simulation)
        assert couvercles.barriere_libre()
        couvercles.retourneur.coupee = True  # type: ignore[attr-defined]
        # Coupée : la machine se met en pause (pas d'alarme).
        assert couvercles.barriere_libre() and simulation.chef.en_pause
        # Sans moyen de mettre en pause, ou barrière pas lue : alarme.
        messages = []
        autre = LavageCouvercles(
            couvercles.lavage, couvercles.retourneur, couvercles.vision, messages.append
        )
        assert autre.barriere_libre() and messages == [MESSAGE_BARRIERE]
        sans_pause = LavageCouvercles(couvercles.lavage, couvercles.retourneur, couvercles.vision)
        assert not sans_pause.barriere_libre()
        couvercles.retourneur.coupee = None  # type: ignore[attr-defined]
        assert not autre.barriere_libre()


def test_barres_refermees_seulement_tete_au_dessus_de_0_80():
    with Simulateur(REGLAGES, LISTE, "lavage_couvercles") as simulation:
        couvercles = couvercles_du_simulateur(simulation)
        p = couvercles.prehension
        p.pose = p.tete.position().avec(z=0.78)
        couvercles.retourneur.ecart_m = 0.30  # type: ignore[attr-defined]
        with pytest.raises(ErreurEtape, match="refermées seulement tête au-dessus de 0,8 m"):
            next(couvercles._barres(0.19))
        p.pose = p.pose.avec(z=0.85)
        attente = next(couvercles._barres(0.19))
        assert attente.texte == "barres du retourneur à 0,19 m"


def test_simulateur_couvercles_et_bocaux_en_ligne_de_commande(capsys):
    assert simulateur(["lavage_couvercles"]) == 0
    assert "remettre_a_l_endroit" in capsys.readouterr().out
    assert simulateur(["lavage_bocaux"]) == 0
    assert "enlever_le_lave_bocal" in capsys.readouterr().out


# ---------------------------------------------------------------- bocaux


def test_trois_bocaux_laves_au_lave_bocal():
    planning, bocaux = jouer_bocaux()
    assert planning.fini, planning.probleme
    assert etapes(planning) == [
        "confirmer_le_lave_bocal",
        *["prendre_le_bocal", "laver_le_bocal", "poser_le_bocal"] * 3,
        "vider",
        "enlever_le_lave_bocal",
        "finir_la_serie",
    ]
    assert bocaux.laves == 3 and not bocaux.lavage.lave_bocal_pose
    # Bocal vide (0,17 sous la face) appuyé sur le plateau ; la capsule aussi (aimants).
    appuis = [m for m in mouvements(bocaux) if m.position == "appui sur le plateau du lave-bocal"]
    assert len(appuis) == 3
    assert appuis[0].axes["prehension_z"][1] == pytest.approx(0.74 + 0.17 - 0.02)
    assert appuis[2].axes["prehension_z"][1] == pytest.approx(0.74 + 0.01 - 0.02)
    # Les brosses ne tournent jamais au lave-bocal.
    assert not any("lavage_noyau" in m.axes for m in mouvements(bocaux))


def test_appui_sur_le_lave_bocal_pas_atteint():
    planning, _ = jouer_bocaux(lambda b: setattr(b.prehension.tete, "appui_vissage_n", 5.0))
    assert not planning.fini
    assert "lave-bocal : appui de 20 N pas atteint" in planning.probleme


def test_bocaux_et_seaux_jamais_en_meme_temps():
    with Simulateur(REGLAGES, LISTE, "lavage") as simulation:
        lavage = lavage_du_simulateur(simulation)
        lavage.refus_mode()
        # Série de seaux pas finie (fût pas vidé) : pas de lave-bocal.
        lavage.eau.eau_dans_le_fut = True
        with pytest.raises(ErreurEtape, match="série de seaux pas finie"):
            lavage.confirmer_lave_bocal(True)
        lavage.eau.eau_dans_le_fut = False
        assert lavage.refus_fut("bocaux") is not None
        lavage.confirmer_lave_bocal(True)
        assert lavage.refus_fut("bocaux") is None
        assert "lave-bocal posé" in lavage.refus_fut("seaux")
        assert "lave-bocal posé" in lavage.refus_fut("couvercles")
        lavage.prehension.objet = lavage.objet_seau("seau_a")
        lavage.eau.eau_dans_le_fut = True
        simulation.temps = 5
        with pytest.raises(ErreurEtape, match="lave-bocal posé sur le fût de lavage"):
            next(lavage.geste_laver_seau("seau_a"))
