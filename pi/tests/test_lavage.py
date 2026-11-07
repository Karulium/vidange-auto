"""Lavage des seaux (tâche 21) : réglages, eau du fût (faux flotteur), verrou du noyau et de la
couronne, scénario « lavage » au simulateur (pannes comprises), vraie tête sur un faux FluidNC."""

import time

import pytest

from vidange.chef import ErreurEtape
from vidange.distance import PiloteDistance
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.lavage import EauLavage, signaux_lavage
from vidange.lavage.eau import CHAUFFAGE, EAU, POMPE, RAMPES, VIDANGE
from vidange.lavage.module import module_lavage
from vidange.lavage.outil import main as outil
from vidange.lavage.simulation import FausseEauLavage, lavage_du_simulateur
from vidange.prehension import Pas, Pose, signaux_prehension
from vidange.prehension.simulation import prehension_du_simulateur
from vidange.reglages import EvenementSimule, charger_reglages
from vidange.simulateur import Simulateur
from vidange.simulateur.outil import main as simulateur

from .conftest import DOSSIER_PI
from .test_prehension import BancTete, attendre, reglages_cartes
from .test_reglages import erreur_de, remplacer

LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
LAVAGE = MACHINE.lavage
assert LAVAGE is not None
SIMULE = REGLAGES.simulateur.lavage
assert SIMULE is not None


# ---------------------------------------------------------------- réglages


def test_reglages_du_lavage_du_depot():
    assert LAVAGE.exemple
    assert LAVAGE.centre_fut == (0.35, 0.65) and LAVAGE.coude_couloir == (0.45, 0.74)
    assert LAVAGE.brossage.appui_n == 80
    # Jet d'air du col, relatif au centre du fût de lavage (PR n° 56, point 1) : A (+2 ; −15,2),
    # B (+2 ; −23), C (+2 ; 0), D (+2 ; −11,5) mm ; brossage décalé de 2 mm : tête à x 0,352
    # (pont jusqu'à 0,223, point 6).
    assert LAVAGE.formats["seau_a"].jet_decalage == (0.002, -0.0152)
    assert LAVAGE.formats["seau_b"].jet_decalage == (0.002, -0.023)
    assert LAVAGE.formats["seau_c"].jet_decalage == (0.002, 0.0)
    assert LAVAGE.formats["seau_d"].jet_decalage == (0.002, -0.0115)
    assert all(f.decalage_brossage_m == 0.002 for f in LAVAGE.formats.values())
    assert LAVAGE.couvercles.centre == (0.352, 0.65) and LAVAGE.lave_bocal.centre == (0.352, 0.65)
    assert LAVAGE.formats["seau_a"].jet_bord_z == 0.711
    # Passe 2 sans remontée ; rotation de la tête jusqu'à ± 500°.
    assert all(reglage.remontee_passe_2_m == 0 for reglage in LAVAGE.formats.values())
    assert MACHINE.axes["prehension_a"].course == (-500, 500)
    assert LAVAGE.brossage.depart_passe_deg == 500
    for nom in ("lavage_noyau", "lavage_couronne"):
        assert MACHINE.axes[nom].carte == "prehension" and MACHINE.axes[nom].unite == "deg"
    # Chaque signal du lavage cité dans fluidnc.yaml est dans la liste, module « lavage ».
    for carte in REGLAGES.fluidnc.cartes.values():
        for nom in (*carte.entrees, *carte.sorties):
            if nom.endswith("_lavage"):
                assert LISTE.signaux[nom].module == "lavage", nom


def test_positions_du_lavage_a_la_portee_de_la_tete(reglages):
    # La tête ne va pas sous x 0,352 (pont ≥ 0,223, mât à pont + 0,129) : pas au centre exact.
    machine = reglages / "machine.yaml"
    remplacer(machine, "jet_decalage: [0.002, 0.0]", "jet_decalage: [-0.001, 0.0]")
    remplacer(machine, "jet_decalage: [0.002, -0.0115]", "jet_decalage: [0.002, 2.9]")
    remplacer(machine, "  verrou: {rayon_m: 0.05", "  verrou: {rayon_m: 0.001")
    message = erreur_de(reglages)
    assert "lavage → formats → seau_c → jet_decalage : axe de la tête à x 0.349 m" in message
    assert "hors de sa portée (0.352 à" in message
    assert "seau_d → jet_decalage : axe de la tête à y 3.55 m, hors de sa course" in message
    assert "seau_a → decalage_brossage_m : plus loin du centre que verrou → rayon_m" in message


def test_tours_du_seau_dans_la_course_de_la_tete(reglages):
    remplacer(reglages / "machine.yaml", "depart_passe_deg: 500", "depart_passe_deg: 100")
    message = erreur_de(reglages)
    assert "passe_1 : après la phase n° 2, la tête serait à 530°" in message
    assert "passe_2 : après la phase n° 1, la tête serait à -530°" in message


def test_jamais_deux_passes_de_suite_dans_le_meme_sens(reglages):
    remplacer(reglages / "machine.yaml", "seau_tours: -1.75}", "seau_tours: 0.5}")
    message = erreur_de(reglages)
    assert "passe_1 et passe_2 tournent dans le même sens" in message


def test_signaux_du_lavage_sur_une_seule_carte(reglages):
    fluidnc = reglages / "fluidnc.yaml"
    remplacer(fluidnc, '      flotteur_lavage: "2"\n', "")
    remplacer(
        fluidnc, "      air_col_lavage: 5\n", "      air_col_lavage: 5\n      pompe_lavage: 3\n"
    )
    message = erreur_de(reglages)
    assert "« flotteur_lavage » (lavage) doit être dans les entrees d'une seule carte" in message
    assert "« pompe_lavage » (lavage) doit être dans les sorties d'une seule carte" in message


def test_formats_et_delais_du_lavage_verifies(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "  lavage_eau_max: 1200\n", "")
    remplacer(machine, "    seau_d: {decalage_brossage_m", "    seau_z: {decalage_brossage_m")
    message = erreur_de(reglages)
    assert "lavage : délai « lavage_eau_max » absent de durees" in message
    assert "lavage → formats : il manque « seau_d » (griffe → formats)" in message
    assert "lavage → formats → seau_z : format absent de griffe → formats" in message


# ---------------------------------------------------------------- eau


class Horloge:
    def __init__(self) -> None:
        self.temps = 0.0

    def __call__(self) -> float:
        return self.temps


def eau_seule(litres: float = 0.0, fichier=None) -> tuple[EauLavage, FausseEauLavage, Horloge]:
    horloge = Horloge()
    faux = FausseEauLavage(SIMULE, horloge)
    faux.litres = litres
    return EauLavage(LAVAGE, faux, horloge, fichier), faux, horloge


def test_chauffage_seulement_flotteur_haut_et_pompe_arretee():
    eau, faux, horloge = eau_seule(litres=50)
    eau.eau_dans_le_fut = True
    eau.surveiller()
    # Flotteur haut, mais pas encore stable (vagues).
    assert not eau.chauffage
    horloge.temps = 2
    eau.surveiller()
    assert eau.chauffage and faux.sorties[CHAUFFAGE]
    # Pompe en marche : coupé tout de suite.
    eau._pompe(True)
    assert not faux.sorties[CHAUFFAGE]
    eau._pompe(False)
    assert faux.sorties[CHAUFFAGE]
    # Flotteur bas : refusé.
    faux.litres = 40
    horloge.temps = 10
    eau.surveiller()
    assert not eau.chauffage
    horloge.temps = 12
    eau.surveiller()
    assert not eau.chauffage and not faux.sorties[CHAUFFAGE]


def test_chauffage_refuse_fut_pas_rempli_pour_la_serie():
    eau, faux, horloge = eau_seule(litres=50)
    horloge.temps = 5
    eau.surveiller()
    assert not eau.chauffage and faux.sorties[CHAUFFAGE] is False


def test_premier_remplissage_garde_dans_un_fichier(tmp_path):
    fichier = tmp_path / "lavage.json"
    eau, _, _ = eau_seule(fichier=fichier)
    assert eau.remplissage_max_s() == 900
    eau.premier_remplissage_s, eau.eau_dans_le_fut = 200.0, True
    eau._garder()
    relue, _, _ = eau_seule(fichier=fichier)
    assert relue.eau_dans_le_fut and relue.remplissage_max_s() == pytest.approx(240)


def test_vanne_3_voies_sur_rampes_des_que_la_pompe_s_arrete():
    eau, faux, horloge = eau_seule(litres=50)
    eau._commander_voie(rampes=False)
    eau._pompe(True)
    assert faux.sorties[POMPE] and not faux.sorties[RAMPES]
    eau._pompe(False)
    assert faux.sorties[RAMPES] and faux.historique[-1] == "vanne_rampes_lavage oui"
    # La vanne met vanne_rampes_s à tourner : l'arrosage n'attend que le temps qui reste.
    horloge.temps += 4
    pas = next(eau._voie(rampes=True))
    assert pas.attente_s == pytest.approx(LAVAGE.eau.vanne_rampes_s - 4)
    # Alarme : la pompe coupée remet aussi la vanne sur « rampes ».
    eau._commander_voie(rampes=False)
    eau.couper()
    assert faux.sorties[RAMPES]


def test_fuite_ou_siphon_flotteur_retombe_sans_vidange():
    eau, faux, horloge = eau_seule(litres=50)
    eau.eau_dans_le_fut, eau._niveau_haut = True, True
    eau._sortie(VIDANGE, True)
    eau.vidange_ouverte = True
    assert eau.niveau_tenu()
    # Le niveau baisse, pompe arrêtée : alerte une fois le flotteur stable, vanne à bille fermée.
    faux.litres = 40
    horloge.temps = 5
    assert eau.niveau_tenu()
    horloge.temps = 7
    assert not eau.niveau_tenu()
    assert not faux.sorties[VIDANGE] and eau.vidange_ouverte is False
    # Pompe en marche (vidange, rinçage) : pas d'alerte.
    eau._niveau_haut = True
    eau._pompe(True)
    assert eau.niveau_tenu()


def test_pas_d_arrosage_fut_pas_rempli():
    eau, _, _ = eau_seule()
    with pytest.raises(ErreurEtape, match="on ne brosse jamais à sec"):
        next(eau.geste_arroser())


# ---------------------------------------------------------------- simulateur


def reglages_avec(lavage=None, evenements=None):
    simulation = REGLAGES.simulateur
    if lavage is not None:
        simulation = simulation.model_copy(
            update={"lavage": SIMULE.model_copy(update=lavage)}  # type: ignore[union-attr]
        )
    if evenements is not None:
        scenario = simulation.scenarios["lavage"].model_copy(update={"evenements": evenements})
        simulation = simulation.model_copy(
            update={"scenarios": {**simulation.scenarios, "lavage": scenario}}
        )
    return REGLAGES.model_copy(update={"simulateur": simulation})


def reglages_machine(**lavage):
    machine = MACHINE.model_copy(update={"lavage": LAVAGE.model_copy(update=lavage)})
    return REGLAGES.model_copy(update={"machine": machine})


def jouer(regler=lambda lavage: None, reglages=REGLAGES):
    """Rejoue le scénario « lavage » ; rend le planning, le lavage et la fausse eau."""
    with Simulateur(reglages, LISTE, "lavage") as simulation:
        lavage = lavage_du_simulateur(simulation)
        regler(lavage)
        seaux = reglages.simulateur.lavage.seaux
        planning = simulation.jouer([module_lavage(lavage, seaux)])
        return planning, lavage, lavage.eau.signaux


def etapes(planning) -> list[str]:
    return [ligne.etape for ligne in planning.lignes]


def perdre_le_vide(lavage, texte: str, fois: int = 1) -> None:
    """La tête simulée perd le vide pendant les `fois` premiers pas dont le texte contient
    `texte`."""
    tete = lavage.prehension.tete
    executer = tete.executer
    reste = [fois]

    def executer_avec_perte(pas, cible, poids):
        if texte in pas.texte and reste[0] > 0:
            reste[0] -= 1
            tete.pertes_de_vide = 1
        executer(pas, cible, poids)

    tete.executer = executer_avec_perte


def test_trois_seaux_laves_au_simulateur():
    planning, lavage, eau = jouer()
    assert planning.fini, planning.probleme
    assert etapes(planning) == [
        "remplir",
        *["prendre_le_seau", "laver_le_seau", "poser_le_seau"] * 3,
        "vider",
        "finir_la_serie",
    ]
    assert lavage.prehension.objet is None and not lavage.eau.eau_dans_le_fut
    # Premier remplissage mesuré (45 L à 0,2 L/s ≈ 225 s, + 1 s de flotteur stable).
    assert lavage.eau.premier_remplissage_s == pytest.approx(226, abs=1)
    # Après la pompe qui suit chaque rinçage, l'eau du réseau remet le flotteur haut.
    assert eau.historique.count("eau_reseau_lavage oui") == 1 + 3
    # Arrosage, rinçage et jet d'air à chaque seau ; pompe et chauffage coupés à la fin.
    assert eau.historique.count("rincage_lavage oui") == 3
    assert eau.historique.count("air_col_lavage oui") == 3
    assert not eau.sorties[POMPE] and not eau.sorties[CHAUFFAGE] and not eau.sorties[EAU]
    # Le noyau et la couronne ont tourné ; la tête est revenue au coude du couloir, en haut.
    positions = lavage.prehension.tete.position()
    assert positions.z == pytest.approx(1.10)


def test_simulateur_lavage_en_ligne_de_commande(capsys):
    assert simulateur(["lavage"]) == 0
    texte = capsys.readouterr().out
    assert "finir_la_serie" in texte and "Temps total" in texte


def test_brosses_et_rotation_de_la_tete_dans_la_meme_commande():
    planning, lavage, _ = jouer()
    assert planning.fini, planning.probleme
    mouvements = lavage.prehension.tete._etat.mouvements
    passes = [m for m in mouvements if m.position.startswith("brossage")]
    assert len(passes) == 9
    premier = passes[0]
    assert set(premier.axes) == {"prehension_a", "lavage_noyau"}
    # Passe 1 (1) : noyau 5 s à 100 tr/min = 3000° ; seau 1/4 de tour depuis −500°.
    debut, fin = premier.axes["lavage_noyau"]
    assert fin - debut == pytest.approx(3000)
    assert premier.axes["prehension_a"] == pytest.approx((-500, -410))
    # La tête revient à 0 à la fin de chaque passe ; la passe 2 part de +500° (autre sens).
    rotations = [m for m in mouvements if set(m.axes) == {"prehension_a"}]
    textes = [m.position for m in rotations]
    assert textes[:4] == [
        "tête au départ de la passe 1",
        "tête revenue à 0 (fin de la passe 1)",
        "tête au départ de la passe 2",
        "tête revenue à 0 (fin de la passe 2)",
    ]
    assert rotations[1].axes["prehension_a"] == pytest.approx((130, 0))
    assert rotations[2].axes["prehension_a"] == pytest.approx((0, 500))
    assert passes[2].axes["prehension_a"] == pytest.approx((500, -130))
    # Passe 2 : la couronne en avant, le seau revient.
    deuxieme = passes[2]
    assert set(deuxieme.axes) == {"prehension_a", "lavage_couronne"}
    debut, fin = deuxieme.axes["lavage_couronne"]
    assert fin - debut == pytest.approx(60 * 360 * 12 / 60)


def test_couloir_du_seau_retourne():
    planning, lavage, _ = jouer()
    assert planning.fini, planning.probleme
    trajets = [
        m.axes
        for m in lavage.prehension.tete._etat.mouvements
        if m.position == "trajet" and "pont_x" in m.axes
    ]
    # Pont + 0,129 = axe de la tête. Aller : coude (0,45 ; 0,74), puis le fût (0,352 ; 0,65),
    # décalage du brossage 2 mm.
    decalage = MACHINE.prehension.decalage_mat_x  # type: ignore[union-attr]
    axes = [(m["pont_x"][1] + decalage, m["chariot_y"][1]) for m in trajets]
    assert axes[1] == pytest.approx((0.45, 0.74))
    assert axes[2] == pytest.approx((0.352, 0.65))
    # Jet d'air du seau A : (0,352 ; 0,6348) = centre du fût + (2 ; −15,2) mm, décalé en −y vers
    # la buse ; retour au coude.
    assert axes[3] == pytest.approx((0.352, 0.6348))
    assert axes[4] == pytest.approx((0.45, 0.74))


def test_eau_changee_apres_deux_seaux():
    eau = LAVAGE.eau.model_copy(update={"seaux_max_par_eau": 2})
    planning, _, _ = jouer(reglages=reglages_machine(eau=eau))
    assert planning.fini, planning.probleme
    assert etapes(planning)[6:10] == ["poser_le_seau", "vider", "remplir", "prendre_le_seau"]
    assert etapes(planning)[-2:] == ["vider", "finir_la_serie"]


def test_remplissage_trop_long():
    planning, _, eau = jouer(reglages=reglages_avec(lavage={"debit_eau_l_s": 0.05}))
    assert not planning.fini
    assert etapes(planning) == ["remplir"]
    assert "remplissage trop long : flotteur haut pas atteint en 900 s" in planning.probleme
    # L'eau est coupée par l'arrêt du module.
    assert eau.historique[-1] != "eau_reseau_lavage oui" and not eau.sorties[EAU]


def test_remise_au_flotteur_haut_trop_longue():
    rincage = LAVAGE.rincage.model_copy(update={"remise_max_s": 0.5})
    planning, _, eau = jouer(reglages=reglages_machine(rincage=rincage))
    assert not planning.fini
    assert (
        "après le rinçage, flotteur haut pas revenu en 0.5 s d'eau du réseau" in planning.probleme
    )
    assert not eau.sorties[EAU]


def test_noyau_refuse_sans_objet_tenu():
    with Simulateur(REGLAGES, LISTE, "lavage") as simulation:
        lavage = lavage_du_simulateur(simulation)
        travail = Pose(x=0.36, y=0.65, z=0.6, a=0)
        assert "aucun objet tenu (vide pas confirmé)" in lavage.refus_brosses(travail)
        assert "pas au-dessus du fût de lavage" in lavage.refus_brosses(travail.avec(x=0.5))
        assert "pas à sa hauteur de travail" in lavage.refus_brosses(travail.avec(z=0.8))
        # La préhension refuse d'envoyer la rotation des brosses : rien ne part.
        prehension = lavage.prehension

        def geste():
            yield Pas("brosser", {"a": 10}, brosses={"noyau": 360}, duree_s=1)

        with pytest.raises(ErreurEtape, match="refusé : noyau et couronne : tête pas au-dessus"):
            prehension.lancer(geste)
        assert not any(m.position == "brosser" for m in simulation.etat_axes.mouvements)


def test_sans_lavage_les_brosses_ne_tournent_jamais():
    with Simulateur(REGLAGES, LISTE, "lavage") as simulation:
        prehension = prehension_du_simulateur(simulation)

        def geste():
            yield Pas("brosser", {"a": 10}, brosses={"noyau": 360}, duree_s=1)

        with pytest.raises(ErreurEtape, match="pas de lavage"):
            prehension.lancer(geste)


def test_perte_de_vide_pendant_la_rotation():
    planning, lavage, eau = jouer(lambda lavage: perdre_le_vide(lavage, "brossage, passe 1 (2)"))
    assert not planning.fini
    assert "vide perdu pendant le brossage (passe 1 (2)) : noyau et couronne arrêtés" in (
        planning.probleme
    )
    # Arrosage coupé par l'arrêt du module.
    assert not eau.sorties[POMPE]


def test_vide_perdu_une_fois_en_remontant():
    planning, lavage, _ = jouer(lambda lavage: perdre_le_vide(lavage, "sortir le seau"))
    assert planning.fini, planning.probleme
    textes = [m.position for m in lavage.prehension.tete._etat.mouvements]
    assert "redescendre sur le noyau" in textes


def test_vide_perdu_deux_fois_en_remontant_alerte():
    planning, _, _ = jouer(lambda lavage: perdre_le_vide(lavage, "sortir le seau", fois=2))
    assert not planning.fini
    assert "vide perdu 2 fois en sortant le seau des brosses" in planning.probleme


def test_appui_sur_le_noyau_pas_atteint():
    def regler(lavage):
        lavage.prehension.tete.appui_vissage_n = 20.0

    planning, _, _ = jouer(regler)
    assert "appui de 80 N sur le noyau pas atteint" in planning.probleme


def test_serie_refusee_sans_vidange():
    with Simulateur(REGLAGES, LISTE, "lavage") as simulation:
        lavage = lavage_du_simulateur(simulation)
        lavage.eau.eau_dans_le_fut = True
        with pytest.raises(ErreurEtape, match="série pas finie, le fût de lavage n'est pas vidé"):
            lavage.finir_serie()
        lavage.eau.eau_dans_le_fut = False
        simulation.temps = 5
        lavage.finir_serie()


def test_panneau_qui_change_pendant_un_mouvement():
    evenement = EvenementSimule(
        apres="lavage.laver_le_seau", attente_s=20, capteur="reed_panneau_poste_fut", actionne=True
    )
    planning, lavage, eau = jouer(reglages=reglages_avec(evenements=[evenement]))
    assert not planning.fini
    assert etapes(planning)[-1] == "laver_le_seau"
    assert "plus tenu : panneau du poste du fût rabattu pendant le lavage" in planning.probleme
    assert "Rabattre le panneau" in planning.probleme
    assert not eau.sorties.get(POMPE)


def test_lavage_refuse_hors_du_mode_lavage():
    with Simulateur(REGLAGES, LISTE, "lavage") as simulation:
        lavage = lavage_du_simulateur(simulation)
        lavage._mode = lambda: "production"
        assert "mode « lavage » pas choisi (mode actuel : production)" in lavage.refus_mode()


def test_le_pilotage_a_distance_ne_pilote_pas_les_brosses():
    pilote = PiloteDistance(
        REGLAGES.programme.distance,
        MACHINE,
        {"prehension": object(), "portique": object()},  # type: ignore[dict-item]
        chef=None,  # type: ignore[arg-type]
        materiel=None,
        age_image=lambda camera, numero: 0.0,
    )
    assert "prehension_z" in pilote.axes
    assert "lavage_noyau" not in pilote.axes and "lavage_couronne" not in pilote.axes


# ---------------------------------------------------------------- vraie tête, faux FluidNC


class BancBrosses(BancTete):
    """La vraie tête sur deux faux FluidNC ; la carte de la tête a aussi B et C (brosses)."""

    def __init__(self) -> None:
        super().__init__()
        self.carte = FauxFluidnc(axes="XYZABC", vitesse_rapide_mm_min=200000)
        self.carte.positions.update(Z=600.0, A=-350.0)
        self.liaison_tete = Liaison("prehension", reglages_cartes(), ouvrir=self.carte.ouvrir)
        self.signaux = signaux_prehension(self.liaison_tete, reglages_cartes().cartes["prehension"])


def test_tete_envoie_brosses_et_rotation_ensemble():
    with BancBrosses() as banc:
        banc.vide.kpa = -70.0
        time.sleep(0.2)
        pose = banc.tete.position()
        pas = Pas(
            "brossage",
            {"a": -260.0},
            brosses={"noyau": 3000.0},
            duree_s=1.0,
            vide_perte_kpa=-40,
        )
        banc.tete.executer(pas, pose.avec(a=-260.0), 5.0)
        ligne = banc.carte.lignes_recues[-1]
        # A et B dans le même déplacement manuel ; vitesse pour 1 s : √(90² + 3000²) × 60.
        assert ligne.startswith("$J=G53 A-260.000 B3000.000 F180081")
        attendre(banc.tete.fini, 10)
        assert banc.carte.positions["B"] == pytest.approx(3000)
        assert banc.tete.resultat().arret is None


def test_tete_perte_de_vide_arrete_les_brosses():
    with BancBrosses() as banc:
        # Le vide tient jusqu'à 1 000° du noyau, puis lâche (−30 kPa).
        banc.vide.fonction = lambda: -69.7 if banc.carte.positions["B"] < 1000 else -29.7
        time.sleep(0.2)
        pose = banc.tete.position()
        pas = Pas(
            "brossage", {"a": -260.0}, brosses={"noyau": 3000.0}, duree_s=1.0, vide_perte_kpa=-40
        )
        banc.tete.executer(pas, pose.avec(a=-260.0), 5.0)
        attendre(banc.tete.fini, 10)
        assert banc.tete.resultat().arret == "vide"
        assert 1000 < banc.carte.positions["B"] < 2000


def test_tete_compteur_des_brosses_plein():
    with BancBrosses() as banc:
        banc.carte.positions["B"] = 99_999_000.0
        time.sleep(0.1)
        pose = banc.tete.position()
        pas = Pas("brossage", {"a": -260.0}, brosses={"noyau": 3000.0}, duree_s=1.0)
        with pytest.raises(ErreurEtape, match="compteur de l'axe lavage_noyau plein"):
            banc.tete.executer(pas, pose.avec(a=-260.0), 5.0)


def test_signaux_du_lavage_repartis_sur_les_cartes():
    liaisons = {
        nom: Liaison(nom, REGLAGES.fluidnc, ouvrir=FauxFluidnc().ouvrir)
        for nom in ("mycelium_lavage", "prehension")
    }
    signaux = signaux_lavage(liaisons, REGLAGES.fluidnc)
    assert signaux._par_nom["pompe_lavage"].liaison.nom == "mycelium_lavage"
    assert signaux._par_nom["chauffage_lavage"].liaison.nom == "prehension"
    with pytest.raises(ValueError, match="« air_col_lavage » .* carte reliée"):
        signaux_lavage({"mycelium_lavage": liaisons["mycelium_lavage"]}, REGLAGES.fluidnc)


def test_eau_coupee_pendant_une_pause():
    eau, faux, horloge = eau_seule()
    eau._sortie(EAU, True)
    eau.pauser()
    assert not faux.sorties[EAU]
    horloge.temps = 30
    eau.reprendre()
    assert faux.sorties[EAU] and eau._pause_cumulee == 30


def test_outil_avec_de_faux_fluidnc(capsys, tmp_path):
    donnees = ["--faux", "--donnees", str(tmp_path)]
    assert outil([*donnees, "etat"]) == 0
    texte = capsys.readouterr().out
    assert "flotteur : bas" in texte and "premier remplissage : pas mesuré" in texte
    assert outil([*donnees, "brosses"]) == 0
    assert "Refusé, comme prévu : " in capsys.readouterr().out
    assert outil([*donnees, "sortie", "chauffage_lavage", "1"]) == 1
    assert "Chauffage refusé" in capsys.readouterr().err
