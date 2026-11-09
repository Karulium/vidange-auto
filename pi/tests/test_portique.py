"""Le portique (tâches 36 et 36 bis) : courses, chariot et mâts, chaîne Z de la préhension,
bandes du bout côté fût, prise d'origine dans l'ordre (pont remis d'équerre sur le faux FluidNC),
rotations de la griffe (fanion) et de la tête de préhension (Hall, compte-tours), freins, alarmes
des pilotes, garage, places de photo."""

import pytest

from vidange.angles_gardes import AnglesGardes
from vidange.chef import Carnet, Chef
from vidange.fiabilite import module_lieu_sur
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.griffe import Contexte as ContexteGriffe
from vidange.griffe import Pose as PoseGriffe
from vidange.griffe import ReglesGriffe
from vidange.portique import ALARMES_PILOTES, FREINS, Portique, module_portique
from vidange.reglages import ReglagesChef, charger_reglages
from vidange.stockage import places

from .conftest import DOSSIER_PI
from .test_chef_exemple import attendre
from .test_fluidnc_liaison import reglages_essai
from .test_reglages import erreur_de, remplacer

REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
PORTIQUE = MACHINE.portique
# Les vraies cartes de fluidnc.yaml, avec une liaison d'essai rapide.
FLUIDNC = REGLAGES.fluidnc.model_copy(update={"liaison": reglages_essai().liaison})
# Sortie du frein du Z de la préhension sur la carte n° 4 (P2 depuis la tâche 45 undecies).
FREIN_TETE = FLUIDNC.cartes["prehension"].sorties["frein_prehension_z"]
DELAI = 10


def test_reglages_du_portique_du_depot():
    assert PORTIQUE is not None and PORTIQUE.exemple
    # Pont 0,223 → 2,925 ; mâts de 0,04 à 0,83 (centre du chariot de 0,08 à 0,87, mâts à − 0,04).
    assert MACHINE.axes["pont_x"].course == (0.223, 2.925)
    assert MACHINE.axes["chariot_y"].course == (0.04, 0.83)
    assert PORTIQUE.chariot.centre_y == (0.08, 0.87)
    # Z : la plaque fait la même course que la hauteur d'outil (0,915 et 0,870 : préhension
    # +22 cm).
    assert MACHINE.axes["griffe_z"].course == (0.375, 1.29)
    assert MACHINE.axes["prehension_z"].course == (0.23, 1.10)
    assert PORTIQUE.plaques_z["prehension"].course == (1.308, 2.178)
    # Vitesses du 28/10 ; la préhension réduit l'accélération du portique seau tenu.
    v = PORTIQUE.vitesses
    assert (v.xy_rapide_m_s, v.xy_approche_m_s, v.z_rapide_m_s, v.z_approche_m_s) == (
        0.25,
        0.05,
        0.08,
        0.02,
    )
    assert MACHINE.prehension.acceleration.seau_mm_s2 == 500
    # Ordre de la prise d'origine : les deux Z, Y, X, puis le godet (la rotation est faite par
    # le Pi, au point de demi-tour).
    assert PORTIQUE.origine == [
        ["griffe_z", "prehension_z"],
        ["chariot_y"],
        ["pont_x"],
        ["griffe_b"],
    ]
    point = MACHINE.griffe.point_demi_tour
    assert (point.x, point.y, point.z) == (0.86, 0.57, 1.075)


@pytest.mark.parametrize(
    ("ancien", "nouveau", "message"),
    [
        (
            "  chariot_y:\n    longueur_rail: 0.95\n    course: [0.04, 0.83]",
            "  chariot_y:\n    longueur_rail: 0.95\n    course: [0.04, 0.884]",
            "la course de chariot_y (le y des mâts) doit être la même",
        ),
        (
            "prehension: {axe: prehension_z, course: [1.308, 2.178]}",
            "prehension: {axe: prehension_z, course: [1.308, 2.198]}",
            "la plaque Z fait 0.890 m de course, l'axe « prehension_z » 0.870 m",
        ),
        (
            "    - [pont_x]\n    - [griffe_b]\n",
            "    - [pont_x]\n    - [griffe_a, griffe_b]\n",
            "« griffe_a » n'y va pas : sa prise d'origine est faite par le Pi",
        ),
        (
            "    - [pont_x]\n    - [griffe_b]\n",
            "    - [pont_x]\n",
            "il manque « griffe_b » (le godet)",
        ),
        (
            "point_demi_tour: {x: 0.86, y: 0.57, z: 1.075}",
            "point_demi_tour: {x: 0.86, y: 0.81, z: 1.075}",
            "y 0.81 au-delà de chaine_prehension → mat_y_max (0.8)",
        ),
        (
            "point_demi_tour: {x: 0.86, y: 0.57, z: 1.075}",
            "point_demi_tour: {x: 0.86, y: 0.57, z: 1.12}",
            "au-dessus de rotation → libre_z_max",
        ),
        (
            "    - [griffe_z, prehension_z]\n    - [chariot_y]\n",
            "    - [chariot_y]\n    - [griffe_z, prehension_z]\n",
            "« griffe_z » doit avoir fini sa prise d'origine avant « chariot_y »",
        ),
        (
            "plenum: {plaque_z_min: 2.08, chariot_centre_y_max: 0.93}",
            "plenum: {plaque_z_min: 1.90, chariot_centre_y_max: 0.85}",
            "la tête toucherait le plénum du Nettoyage",
        ),
        (
            "acceleration: {normale_mm_s2: 1000, seau_mm_s2: 500}",
            "acceleration: {normale_mm_s2: 1000, seau_mm_s2: 150}",
            "seau_mm_s2 (150) doit être celle du portique (500 mm/s²)",
        ),
        (
            "  portique_outils_en_haut:\n    griffe_z: 1.29",
            "  portique_outils_en_haut:\n    griffe_z: 1.20",
            "outils_en_haut : griffe_z doit être en haut de sa course",
        ),
        (
            "    xy_rapide_m_s: 0.25",
            "    xy_rapide_m_s: 0.20",
            "griffe → vitesses → pont_x (0.25 m/s) dépasse celle du portique (0.2)",
        ),
    ],
)
def test_reglages_du_portique_verifies_au_demarrage(reglages, ancien, nouveau, message):
    remplacer(reglages / "machine.yaml", ancien, nouveau)
    assert message in erreur_de(reglages)


def test_courses_du_pont_et_des_mats():
    portique = Portique(MACHINE, FLUIDNC.cartes, liaisons_fausses())
    assert "pont en x à 0,222" in portique.refus_position(pont_x=0.222)
    assert portique.refus_position(pont_x=0.223, mats_y=0.83) is None
    assert portique.refus_position(pont_x=2.925) is None
    assert "hors de la course (0,223 à 2,925 m)" in portique.refus_position(pont_x=2.926)
    assert "mâts en y à 0,84 m, hors de la course (0,04 à 0,83 m)" in portique.refus_position(
        mats_y=0.84
    )
    # Garage : chariot au centre 0,50, mâts à 0,46.
    assert portique.centre_chariot(MACHINE.positions["portique_garage"]["chariot_y"]) == (
        pytest.approx(0.50)
    )
    assert portique.mats_y(0.87) == pytest.approx(0.83)
    assert portique.acceleration_xy_mm_s2(seau_tenu=True) == 500
    assert portique.acceleration_xy_mm_s2(seau_tenu=False) == 1000


def test_chaine_z_de_la_prehension():
    portique = Portique(MACHINE, FLUIDNC.cartes, liaisons_fausses())
    # Plaque Z au-dessus de 2,02 (face au-dessus de 2,02 − 1,078 = 0,942) ⇒ mâts à y ≤ 0,80.
    assert portique.refus_position(mats_y=0.80, prehension_z=1.10) is None
    texte = portique.refus_position(mats_y=0.81, prehension_z=1.10)
    assert "chaîne Z de la préhension" in texte and "il faut y ≤ 0.8 m" in texte
    assert portique.refus_position(mats_y=0.83, prehension_z=0.942) is None
    assert "chaîne Z" in portique.refus_position(mats_y=0.83, prehension_z=0.95)
    # Au démarrage : une position nommée qui ne la respecte pas est refusée.
    assert PORTIQUE.face_max_chaine(0.81, 0.23) == pytest.approx(0.942)


def test_chaine_z_verifiee_au_demarrage(reglages):
    remplacer(
        reglages / "machine.yaml",
        "chaine_prehension: {plaque_z_min: 2.02, mat_y_max: 0.80}",
        "chaine_prehension: {plaque_z_min: 2.02, mat_y_max: 0.40}",
    )
    assert "chaîne Z de la préhension" in erreur_de(reglages)


def test_courses_de_la_griffe():
    regles = ReglesGriffe(MACHINE)
    # Préhension basse (chaîne Z sans effet) : le mât va jusqu'à 0,83.
    contexte = ContexteGriffe(prehension_face_z=0.90)
    pose = PoseGriffe(x=1.5, y=0.83, z=1.0, a=0, b=0)
    assert regles.refus_pose(pose, contexte) is None
    assert "hors de la course" in regles.refus_pose(pose.avec(y=0.84), contexte)
    # Godet fermé : mât ≥ 0,056 ; godet ouvert : ≥ 0,11, sauf au-dessus du stockage (mât à x
    # 1,10-2,70, fil Griffe du 07/11 : la course seulement).
    assert regles.refus_pose(pose.avec(y=0.056), contexte) is None
    assert "il faut y ≥ 0,056" in regles.refus_pose(pose.avec(y=0.05), contexte)
    assert regles.refus_pose(pose.avec(y=0.10, b=1), contexte) is None
    assert "godet ouvert" in regles.refus_pose(pose.avec(x=2.72, y=0.10, b=1), contexte)
    # Préhension en haut (ou inconnue, comptée en haut) : mâts à y ≤ 0,80.
    assert "chaîne Z" in regles.refus_pose(pose, ContexteGriffe())
    assert regles.refus_pose(pose.avec(y=0.80), ContexteGriffe()) is None
    # Pont sous 0,223 (mât à pont − 0,187) : refusé.
    assert "hors de sa course" in regles.refus_pose(pose.avec(x=0.223 - 0.187 - 0.001), contexte)


def test_tete_de_la_griffe_au_bout_cote_fut():
    regles = ReglesGriffe(MACHINE)
    # Pont 0,233-0,30, axes sous 1,05 : A = 180° seulement.
    assert "tête à 180° seulement" in regles.refus_bout_bloque(0.25, 1.0, 0)
    assert "tête à 180° seulement" in regles.refus_bout_bloque(0.25, 1.0, 90)
    assert regles.refus_bout_bloque(0.25, 1.0, 180) is None
    assert regles.refus_bout_bloque(0.25, 1.06, 0) is None
    # Pont 0,223-0,233, axes sous 1,05 : aucun angle ; au-dessus, rotation libre.
    for a in (0, 90, 180):
        assert "interdit (la tête toucherait la traverse)" in regles.refus_bout_bloque(
            0.228, 1.0, a
        )
        assert regles.refus_bout_bloque(0.228, 1.06, a) is None
    # Hors des bandes : rien.
    assert regles.refus_bout_bloque(0.31, 0.5, 90) is None


def test_tete_de_la_griffe_au_bout_cote_stockage():
    regles = ReglesGriffe(MACHINE)
    contexte = ContexteGriffe(prehension_face_z=0.90)
    decalage = MACHINE.griffe.decalage_mat_x
    # Plus de bande « 0° ou 180° » au-delà de x 2,0 : A = 90 permis à pont 2,2 (sans rotation).
    loin = PoseGriffe(x=2.2 + decalage, y=0.5, z=1.0, a=90, b=0)
    assert regles.refus_pose(loin, contexte) is None
    assert regles.refus_pose(loin.avec(a=0), contexte) is None
    # Mais pas de rotation au-delà de x 2,0 (griffe → rotation → pont_x_max).
    assert "rotation" in regles.refus_mouvement(loin, loin.avec(a=180), contexte)


def test_stockage_rangee_084_prise_hors_axe():
    # Pile à y 0,84 : la tête prend à 0,83 (bout de la course, 1 cm hors d'axe accepté).
    assert places.prise_y(MACHINE, 0.84) == pytest.approx(0.83)
    assert places.prise_y(MACHINE, 0.53) == 0.53
    # Plus d'1 cm hors de la course : rien n'est changé (la place sera refusée au démarrage).
    assert places.prise_y(MACHINE, 0.85) == 0.85


def test_places_de_photo():
    portique = Portique(MACHINE, FLUIDNC.cartes, liaisons_fausses())
    assert portique.place_photo("fut_poste") == 2.925
    assert portique.place_photo("stockage") == 0.223
    assert portique.pont_gare("stockage", 0.226)
    assert not portique.pont_gare("stockage", 0.23)
    assert not portique.pont_gare("fut_poste", None)


def test_lieu_sur_commence_par_la_prise_d_origine_du_portique():
    liaisons = liaisons_fausses()
    liaisons["mycelium_lavage"] = Liaison("mycelium_lavage", FLUIDNC, ouvrir=FauxFluidnc().ouvrir)
    module = module_lieu_sur(MACHINE, liaisons, FLUIDNC.cartes)
    noms = [etape.nom for etape in module.etapes]
    assert noms[:16] == [
        "griffe_controle_rotation",
        "tete_controle_compte_tours",
        "portique_freins_desserres",
        "portique_origine_griffe_z_prehension_z",
        "portique_origine_chariot_y",
        "portique_origine_pont_x",
        "portique_origine_griffe_b",
        "griffe_origine_godet_ferme",
        "griffe_origine_au_point",
        "griffe_origine_axes_descendus",
        "griffe_origine_vers_le_fanion",
        "griffe_origine_rotation",
        "griffe_origine_rotation_a_0",
        "griffe_origine_remontee",
        "tete_origine_vers_le_hall",
        "tete_origine_rotation",
    ]
    assert module.etapes[0].demande_go and not module.etapes[1].demande_go
    assert module.etapes[3].delai_max == "portique_origine_max"
    with pytest.raises(ValueError, match="demande les cartes"):
        module_lieu_sur(MACHINE, liaisons)


# ---------------------------------------------------------------- sur le faux FluidNC


def liaisons_fausses(portique=None, prehension=None):
    portique = portique or FauxFluidnc(axes="XYZAB")
    prehension = prehension or FauxFluidnc(axes="XYZABC")
    return {
        "portique": Liaison("portique", FLUIDNC, ouvrir=portique.ouvrir),
        "prehension": Liaison("prehension", FLUIDNC, ouvrir=prehension.ouvrir),
    }


class Banc:
    """Les fausses cartes n° 1 et n° 4, le chef, les angles gardés et le compte-tours."""

    def __init__(self, chef, liaisons, carte_1, carte_4, garde, trop_tot):
        self.chef, self.liaisons, self.carte_1, self.carte_4 = chef, liaisons, carte_1, carte_4
        self.garde, self.trop_tot = garde, trop_tot
        # Angle de la tête lu au compte-tours (°).
        self.compte_tours = 0.0

    def portique(self, machine=MACHINE):
        return Portique(
            machine,
            FLUIDNC.cartes,
            self.liaisons,
            garde=self.garde,
            compte_tours=lambda: self.compte_tours,
        )

    def __iter__(self):
        # Pour les anciens tests : (chef, portique, carte n° 1, carte n° 4, trop tôt).
        return iter((self.chef, self.portique(), self.carte_1, self.carte_4, self.trop_tot))


@pytest.fixture
def banc(tmp_path):
    """Les cartes n° 1 et n° 4 (fausses, en alarme à la mise sous tension), le chef. Angles
    gardés : griffe et tête à 0° (arrêt normal) ; compte-tours à 0°."""
    portique = FauxFluidnc(
        axes="XYZAB",
        vitesse_rapide_mm_min=300_000,
        en_alarme_au_depart=True,
        origines={"X": 223, "Y": 40, "Z": 1290, "A": 0, "B": 0},
    )
    # Z de la préhension plus lent : Y et X doivent attendre qu'il soit en haut.
    prehension = FauxFluidnc(
        axes="XYZABC",
        vitesse_rapide_mm_min=30_000,
        en_alarme_au_depart=True,
        origines={"Z": 1100, "A": 0},
    )
    prehension.positions["Z"] = 700
    portique.positions.update(X=1200, Y=500, Z=900)
    # Le pont est de travers : X2 3 mm en avance sur X1.
    portique.travers["X"] = 3.0
    trop_tot: list[str] = []

    def surveiller() -> None:
        lignes = portique.lignes_recues
        if any(ligne in ("$HY", "$HX") for ligne in lignes) and "Z" not in "".join(
            prehension.prises_origine
        ):
            trop_tot.append("Y ou X avant que le Z de la préhension soit en haut")

    portique.monde = surveiller
    chef = Chef(
        MACHINE,
        ReglagesChef(periode_s=0.01, alarme_pause_tout=True),
        Carnet(tmp_path / "etat-cycle.json"),
    )
    liaisons = liaisons_fausses(portique, prehension)
    garde = AnglesGardes(tmp_path / "angles.json")
    garde.noter("griffe_a", 0.0)
    garde.noter("prehension_a", 0.0)
    for liaison in liaisons.values():
        liaison.demarrer()
    try:
        for liaison in liaisons.values():
            liaison.attendre_connexion(DELAI)
        chef.demarrer()
        yield Banc(chef, liaisons, portique, prehension, garde, trop_tot)
    finally:
        chef.arreter()
        for liaison in liaisons.values():
            liaison.arreter()


def module_de(chef, nom):
    return next(module for module in chef.etat().modules if module.module == nom)


def jouer(chef, module):
    chef.lancer(module)
    attendre(lambda: chef.etat().attendent_go == [module.nom], DELAI)
    chef.donner_go(module.nom)
    attendre(lambda: module_de(chef, module.nom).statut in ("fini", "alarme"), DELAI)
    return module_de(chef, module.nom)


def test_prise_d_origine_dans_l_ordre_et_pont_d_equerre(banc):
    chef, portique, carte_1, carte_4, trop_tot = banc
    etat = jouer(chef, module_portique(portique, "origine"))
    assert etat.statut == "fini", etat.alarme
    # Freins desserrés d'abord (la carte en alarme est débloquée pour la sortie), puis les Z
    # ensemble sur les 2 cartes, puis Y, puis X1 et X2 ensemble, puis le godet de la griffe,
    # puis sa rotation (au point de recherche) et celle de la tête de préhension.
    assert carte_1.prises_origine == ["Z", "Y", "X", "B", "A"]
    assert carte_4.prises_origine == ["Z", "A"]
    assert trop_tot == []
    lignes = [ligne for ligne in carte_1.lignes_recues if ligne.startswith(("$H", "$X", "M6"))]
    assert lignes == ["$X", "M64 P0", "$HZ", "$HY", "$HX", "$HB", "$HA"]
    assert (
        carte_4.sorties[FREIN_TETE] is True
        and carte_1.sorties[0] is True
        and portique.freins_desserres
    )
    # Le pont est remis d'équerre : chaque moteur s'est arrêté sur son fin de course.
    assert carte_1.travers["X"] == 0
    # La griffe a fini au point de recherche (mât 0,86 ; 0,57 : pont à 0,86 + 0,187), godet
    # fermé, A à 0, axes remontés ; la tête de préhension en haut, sur son Hall.
    assert carte_1.positions == {"X": 1047, "Y": 570, "Z": 1290, "A": 0, "B": 0}
    assert carte_4.positions["Z"] == 1100 and carte_4.positions["A"] == 0


def test_garage_de_repos_et_photo(banc):
    chef, portique, carte_1, carte_4, _ = banc
    assert jouer(chef, module_portique(portique, "origine")).statut == "fini"
    etat = jouer(chef, module_portique(portique, "photo_stockage"))
    assert etat.statut == "fini", etat.alarme
    # Photo du stockage : pont au bout opposé (0,223), les deux outils en haut.
    assert (carte_1.positions["X"], carte_1.positions["Z"], carte_4.positions["Z"]) == (
        223,
        1290,
        1100,
    )
    attendre(lambda: portique.pont_gare("stockage", portique.position_pont()), DELAI)
    etat = jouer(chef, module_portique(portique, "garage"))
    assert etat.statut == "fini", etat.alarme
    # Garage : pont à 2,925, mâts à 0,46 (centre du chariot à 0,50), freins serrés.
    assert (carte_1.positions["X"], carte_1.positions["Y"]) == (2925, 460)
    assert carte_1.sorties[0] is False and carte_4.sorties[FREIN_TETE] is False
    assert portique.pont_gare("fut_poste", 2.925)


def test_alarme_d_un_pilote_arrete_et_dit_lequel(banc):
    chef, portique, carte_1, _, _ = banc
    # Alarme groupée de la carte n° 1 (un des 6 pilotes) : on ne sait pas lequel.
    carte_1.entrees.add(portique.alarmes[ALARMES_PILOTES["alarme_carte1"]][1])
    attendre(lambda: portique.pilotes_en_alarme() == [ALARMES_PILOTES["alarme_carte1"]], DELAI)
    etat = jouer(chef, module_portique(portique, "origine"))
    assert etat.statut == "alarme"
    assert "alarme du pilote : un pilote de la carte n° 1" in etat.alarme.message
    assert "pilote du portique est en alarme" in etat.alarme.quoi_faire
    assert "voyants" in etat.alarme.quoi_faire
    # Rien n'a bougé : la prise d'origine n'est pas lancée.
    assert carte_1.prises_origine == []


def test_outil_sur_de_faux_fluidnc(capsys):
    from vidange.portique.outil import main

    assert main(["--faux", "origine"]) == 0
    sortie = capsys.readouterr().out
    assert "→ portique_origine_chariot_y" in sortie
    assert "pont_x             1.047" in sortie and "prehension_z       1.100" in sortie
    assert "Pilotes en alarme : aucun" in sortie


def test_signaux_du_portique_dans_la_liste():
    from vidange.entrees_sorties import charger_entrees_sorties

    liste = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
    for nom in ("alarme_carte1", *FREINS, "fdc_pont_x1", "fdc_pont_x2", "fdc_chariot_y"):
        assert liste.signaux[nom].module == "portique", nom
    assert set(ALARMES_PILOTES) == {"alarme_carte1", "alarme_carte4"}
    assert liste.signaux["alarme_carte4"].carte == "fluidnc_prehension"
    # Fins de course NF ; « OK » du détecteur de chocs en 24 V sur la carte n° 1.
    assert liste.signaux["fdc_prehension_haut"].repos == "ferme"
    ok = liste.signaux["ok_chocs"]
    assert (ok.carte, ok.tension) == ("fluidnc_portique", 24)
    # Accéléromètre : X vertical, Y le long du pont, Z le long des rails : seuls Y et Z comptent.
    assert list(REGLAGES.accelerometre.capteur.axes) == ["y", "z"]


# ---------------------------------------------------------------- rotations (tâche 36 bis)


def machine_rapide(griffe_deg_s=200.0, tete_deg_s=600.0):
    """machine.yaml avec des rotations plus rapides (le faux FluidNC suit l'horloge vraie)."""
    griffe = MACHINE.griffe.model_copy(
        update={
            "origine_rotation": MACHINE.griffe.origine_rotation.model_copy(
                update={"vitesse_deg_s": griffe_deg_s}
            )
        }
    )
    prehension = MACHINE.prehension.model_copy(
        update={
            "origine_rotation": MACHINE.prehension.origine_rotation.model_copy(
                update={"vitesse_deg_s": tete_deg_s}
            )
        }
    )
    return MACHINE.model_copy(update={"griffe": griffe, "prehension": prehension})


def acquitter_et_go(chef, nom):
    # L'alarme a mis la machine en pause (alarme_pause_tout) : Karulium reprend, acquitte, Go.
    chef.reprendre()
    chef.acquitter(nom)
    attendre(lambda: chef.etat().attendent_go == [nom], DELAI)
    chef.donner_go(nom)
    attendre(lambda: module_de(chef, nom).statut in ("fini", "alarme"), DELAI)
    return module_de(chef, nom)


def test_angles_gardes_relus_apres_un_redemarrage(tmp_path):
    from vidange.angles_gardes import AngleGarde

    fichier = tmp_path / "donnees" / "angles.json"
    garde = AnglesGardes(fichier)
    assert garde.lire("prehension_a") is None
    garde.noter("prehension_a", 370.0, en_rotation=True)
    garde.noter("griffe_a", 180.0)
    # Après un redémarrage (nouvel objet, même fichier) : les mêmes angles.
    relue = AnglesGardes(fichier)
    assert relue.lire("prehension_a") == AngleGarde(370.0, en_rotation=True)
    assert relue.lire("griffe_a") == AngleGarde(180.0)
    relue.noter("prehension_a", 372.5)
    assert AnglesGardes(fichier).lire("prehension_a") == AngleGarde(372.5)
    # Fichier abîmé : angles inconnus (la prise d'origine demandera une confirmation).
    fichier.write_text("{pas du json", encoding="utf-8")
    assert AnglesGardes(fichier).lire("griffe_a") is None


def test_coupure_pendant_une_rotation_de_la_griffe_z_ne_monte_pas(banc):
    banc.garde.noter("griffe_a", 47.0, en_rotation=True)
    nom = "portique_origine"
    etat = jouer(banc.chef, module_portique(banc.portique(), "origine"))
    assert etat.statut == "alarme" and etat.alarme.etape == "griffe_controle_rotation"
    assert "coupure pendant une rotation de la griffe (partie de 47°)" in etat.alarme.message
    assert "remettre la tête à la main à 0°" in etat.alarme.quoi_faire
    # Rien n'a bougé : Z n'est pas monté.
    assert banc.carte_1.prises_origine == [] and banc.carte_4.prises_origine == []
    # Tête remise à la main, acquitté, Go : la prise d'origine continue jusqu'au bout.
    etat = acquitter_et_go(banc.chef, nom)
    assert etat.statut == "fini", etat.alarme
    assert banc.carte_1.prises_origine == ["Z", "Y", "X", "B", "A"]
    assert banc.garde.lire("griffe_a").angle_deg == 0
    assert not banc.garde.lire("griffe_a").en_rotation


def test_rotation_de_la_griffe_ni_0_ni_180_refusee(banc):
    portique = banc.portique()
    for angle, refus in ((0.0, False), (180.0, False), (-180.0, False), (90.0, True)):
        banc.garde.noter("griffe_a", angle)
        probleme = portique.rotations.probleme_griffe()
        assert (probleme is not None) == refus, angle
    assert "à 90°, ni 0° ni 180°" in probleme


def test_griffe_cherche_son_fanion_en_passant_par_0(banc):
    # Tête à 180° (bras le long du pont, raclette côté stockage) : fanion libre. Le Pi tourne en
    # − jusqu'au fanion (il passe par 0), puis « $HA » finit en +. Jamais au-delà de ± 180°.
    carte_1 = banc.carte_1
    banc.garde.noter("griffe_a", 180.0)
    carte_1.positions["A"] = 180.0
    vus = []

    def fanion():
        a = carte_1.positions["A"]
        vus.append(a)
        if 0 < a % 360 <= 180:
            carte_1.entrees.add("A")
        else:
            carte_1.entrees.discard("A")

    carte_1.monde = fanion
    etat = jouer(banc.chef, module_portique(banc.portique(machine_rapide()), "origine"))
    assert etat.statut == "fini", etat.alarme
    # Recherche limitée à 190° (180 − 190 = −10), arrêtée au fanion, puis « $HA ».
    lignes = [ligne for ligne in carte_1.lignes_recues if ligne.startswith(("$J", "$HA"))]
    assert lignes == ["$J=G53 A-10.000 F12000", "$HA"]
    assert min(vus) >= -10 and max(vus) <= 180
    assert carte_1.positions["A"] == 0


def test_fanion_pas_trouve_alarme(banc):
    # Capteur toujours « libre » (câble coupé…) : la recherche s'arrête à 190°, alarme.
    banc.garde.noter("griffe_a", 180.0)
    banc.carte_1.positions["A"] = 180.0
    banc.carte_1.entrees.add("A")
    etat = jouer(banc.chef, module_portique(banc.portique(machine_rapide()), "origine"))
    assert etat.statut == "alarme" and etat.alarme.etape == "griffe_origine_vers_le_fanion"
    assert "fanion pas trouvé en 190°" in etat.alarme.message
    assert "origine_rotation_griffe" in etat.alarme.quoi_faire
    assert "A" not in "".join(banc.carte_1.prises_origine)


def test_tour_de_la_tete_pris_au_compte_tours(banc):
    # Tête à 370° (un tour et 10°) : le Pi la ramène à 20° avant le Hall (370 + 20 = 390° en −),
    # puis « $HA » cherche le Hall en + ; l'angle est noté.
    banc.garde.noter("prehension_a", 372.0)
    banc.compte_tours = 370.0
    etat = jouer(banc.chef, module_portique(banc.portique(machine_rapide()), "origine"))
    assert etat.statut == "fini", etat.alarme
    lignes = [ligne for ligne in banc.carte_4.lignes_recues if ligne.startswith(("$J", "$HA"))]
    assert lignes == ["$J=G53 A-390.000 F36000", "$HA"]
    assert banc.carte_4.prises_origine == ["Z", "A"]
    assert banc.garde.lire("prehension_a").angle_deg == 0


def test_compte_tours_et_angle_garde_en_desaccord_confirmation(banc):
    banc.garde.noter("prehension_a", 0.0)
    banc.compte_tours = 40.0
    nom = "portique_origine"
    etat = jouer(banc.chef, module_portique(banc.portique(machine_rapide()), "origine"))
    assert etat.statut == "alarme" and etat.alarme.etape == "tete_controle_compte_tours"
    assert "en désaccord de 40°" in etat.alarme.message
    assert "le cordon spiralé de la tête de préhension n'est pas vrillé" in etat.alarme.quoi_faire
    assert banc.carte_4.prises_origine == []
    # Cordon vérifié, acquitté, Go : le tour vient du compte-tours (40 + 20 = 60° en −).
    etat = acquitter_et_go(banc.chef, nom)
    assert etat.statut == "fini", etat.alarme
    assert "$J=G53 A-60.000 F36000" in banc.carte_4.lignes_recues


def test_coupure_pendant_une_rotation_de_la_tete_confirmation(banc):
    banc.garde.noter("prehension_a", 120.0, en_rotation=True)
    banc.compte_tours = 125.0
    etat = jouer(banc.chef, module_portique(banc.portique(), "origine"))
    assert etat.statut == "alarme" and etat.alarme.etape == "tete_controle_compte_tours"
    assert "coupure pendant une rotation de la tête (partie de 120°)" in etat.alarme.message
    assert "cordon" in etat.alarme.quoi_faire


def test_compte_tours_hors_plage_ou_illisible():
    portique = Portique(MACHINE, FLUIDNC.cartes, liaisons_fausses())
    rotations = portique.rotations
    assert "hors de sa plage (-540° à 540°)" in rotations.probleme_tete(600.0)
    assert "illisible" in rotations.probleme_tete(None)
    # Sans angle gardé (jamais enregistré) : confirmation demandée aussi.
    assert "jamais enregistré" in rotations.probleme_tete(10.0)


def test_capteurs_d_origine_des_rotations_dans_les_listes(reglages):
    from vidange.entrees_sorties import charger_entrees_sorties

    liste = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
    for nom in ("origine_godet_griffe", "origine_rotation_griffe"):
        signal = liste.signaux[nom]
        assert (signal.carte, signal.type, signal.tension, signal.module) == (
            "fluidnc_portique",
            "pnp",
            24,
            "griffe",
        )
    assert "Hall sous la poulie de 60 dents" in liste.signaux["origine_rotation_tete"].description
    compte_tours = liste.signaux["compte_tours_tete"]
    assert (compte_tours.carte, compte_tours.broche, compte_tours.module) == (
        "ads1115",
        ("A1",),
        "prehension",
    )
    # Chaque capteur est le fin de course de son axe (vérifié au démarrage).
    remplacer(reglages / "fluidnc.yaml", "origine_rotation_griffe: A", "origine_rotation_griffe: C")
    assert "doit être la lettre de l'axe griffe_a (« A »)" in erreur_de(reglages)
