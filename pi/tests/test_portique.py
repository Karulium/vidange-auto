"""Le portique (tâche 36) : courses, chariot et mâts, prise d'origine dans l'ordre (pont remis
d'équerre sur le faux FluidNC), freins, alarmes des pilotes, garage, places de photo."""

import pytest

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
DELAI = 10


def test_reglages_du_portique_du_depot():
    assert PORTIQUE is not None and PORTIQUE.exemple
    # Pont 0,233 → 2,495 ; mâts de 0,04 à 0,83 (centre du chariot de 0,08 à 0,87, mâts à − 0,04).
    assert MACHINE.axes["pont_x"].course == (0.233, 2.495)
    assert MACHINE.axes["chariot_y"].course == (0.04, 0.83)
    assert PORTIQUE.chariot.centre_y == (0.08, 0.87)
    # Z : la plaque fait la même course que la hauteur d'outil (0,915 et 0,650).
    assert MACHINE.axes["griffe_z"].course == (0.375, 1.29)
    assert MACHINE.axes["prehension_z"].course == (0.45, 1.10)
    # Vitesses du 28/10 ; la préhension réduit l'accélération du portique seau tenu.
    v = PORTIQUE.vitesses
    assert (v.xy_rapide_m_s, v.xy_approche_m_s, v.z_rapide_m_s, v.z_approche_m_s) == (
        0.25,
        0.05,
        0.08,
        0.02,
    )
    assert MACHINE.prehension.acceleration.seau_mm_s2 == 500
    # Ordre de la prise d'origine : les deux Z, Y, X.
    assert PORTIQUE.origine[:3] == [["griffe_z", "prehension_z"], ["chariot_y"], ["pont_x"]]


@pytest.mark.parametrize(
    ("ancien", "nouveau", "message"),
    [
        (
            "  chariot_y:\n    longueur_rail: 0.95\n    course: [0.04, 0.83]",
            "  chariot_y:\n    longueur_rail: 0.95\n    course: [0.04, 0.884]",
            "la course de chariot_y (le y des mâts) doit être la même",
        ),
        (
            "prehension: {axe: prehension_z, course: [1.308, 1.958]}",
            "prehension: {axe: prehension_z, course: [1.308, 1.978]}",
            "la plaque Z fait 0.670 m de course, l'axe « prehension_z » 0.650 m",
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
    assert "pont en x à 0,232" in portique.refus_position(pont_x=0.232)
    assert portique.refus_position(pont_x=0.233, mats_y=0.83) is None
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


def test_courses_de_la_griffe():
    regles = ReglesGriffe(MACHINE)
    contexte = ContexteGriffe()
    pose = PoseGriffe(x=1.5, y=0.83, z=1.0, a=0, b=0)
    assert regles.refus_pose(pose, contexte) is None
    assert "hors de la course" in regles.refus_pose(pose.avec(y=0.84), contexte)
    # Godet fermé : mât ≥ 0,056 ; godet ouvert : ≥ 0,11.
    assert regles.refus_pose(pose.avec(y=0.056), contexte) is None
    assert "il faut y ≥ 0,056" in regles.refus_pose(pose.avec(y=0.05), contexte)
    assert "godet ouvert" in regles.refus_pose(pose.avec(y=0.10, b=1), contexte)
    # Pont sous 0,233 (mât à pont − 0,187) : refusé.
    assert "hors de sa course" in regles.refus_pose(pose.avec(x=0.233 - 0.187 - 0.001), contexte)


def test_tete_de_la_griffe_bloquee_au_bout_du_pont():
    regles = ReglesGriffe(MACHINE)
    contexte = ContexteGriffe()
    decalage = MACHINE.griffe.decalage_mat_x
    # Pont à 2,2 : tête à 0° ou 180° seulement.
    loin = PoseGriffe(x=2.2 + decalage, y=0.5, z=1.0, a=0, b=0)
    assert regles.refus_pose(loin, contexte) is None
    assert regles.refus_pose(loin.avec(a=180), contexte) is None
    assert "tête à 0° ou 180° seulement" in regles.refus_pose(loin.avec(a=90), contexte)
    # Et pas de rotation au-delà de x 2,0.
    assert "rotation" in regles.refus_mouvement(loin, loin.avec(a=180), contexte)
    pres = loin.avec(x=1.8 + decalage)
    assert regles.refus_pose(pres.avec(a=90), contexte) is None


def test_stockage_rangee_084_prise_hors_axe():
    # Pile à y 0,84 : la tête prend à 0,83 (bout de la course, 1 cm hors d'axe accepté).
    assert places.prise_y(MACHINE, 0.84) == pytest.approx(0.83)
    assert places.prise_y(MACHINE, 0.53) == 0.53
    # Plus d'1 cm hors de la course : rien n'est changé (la place sera refusée au démarrage).
    assert places.prise_y(MACHINE, 0.85) == 0.85


def test_places_de_photo():
    portique = Portique(MACHINE, FLUIDNC.cartes, liaisons_fausses())
    assert portique.place_photo("fut_poste") == 2.495
    assert portique.place_photo("stockage") == 0.233
    assert portique.pont_gare("stockage", 0.236)
    assert not portique.pont_gare("stockage", 0.24)
    assert not portique.pont_gare("fut_poste", None)


def test_lieu_sur_commence_par_la_prise_d_origine_du_portique():
    liaisons = liaisons_fausses()
    liaisons["mycelium_lavage"] = Liaison("mycelium_lavage", FLUIDNC, ouvrir=FauxFluidnc().ouvrir)
    module = module_lieu_sur(MACHINE, liaisons, FLUIDNC.cartes)
    noms = [etape.nom for etape in module.etapes]
    assert noms[:5] == [
        "portique_freins_desserres",
        "portique_origine_griffe_z_prehension_z",
        "portique_origine_chariot_y",
        "portique_origine_pont_x",
        "portique_origine_griffe_a_griffe_b",
    ]
    assert module.etapes[0].demande_go and not module.etapes[1].demande_go
    assert module.etapes[1].delai_max == "portique_origine_max"
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


@pytest.fixture
def banc(tmp_path):
    """Les cartes n° 1 et n° 4 (fausses, en alarme à la mise sous tension), le chef."""
    portique = FauxFluidnc(
        axes="XYZAB",
        vitesse_rapide_mm_min=300_000,
        en_alarme_au_depart=True,
        origines={"X": 233, "Y": 40, "Z": 1290, "A": -370, "B": 30},
    )
    # Z de la préhension plus lent : Y et X doivent attendre qu'il soit en haut.
    prehension = FauxFluidnc(
        axes="XYZABC", vitesse_rapide_mm_min=30_000, en_alarme_au_depart=True, origines={"Z": 1100}
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
    for liaison in liaisons.values():
        liaison.demarrer()
    try:
        for liaison in liaisons.values():
            liaison.attendre_connexion(DELAI)
        chef.demarrer()
        yield chef, Portique(MACHINE, FLUIDNC.cartes, liaisons), portique, prehension, trop_tot
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
    # ensemble sur les 2 cartes, puis Y, puis X1 et X2 ensemble, puis A et B de la griffe.
    assert carte_1.prises_origine == ["Z", "Y", "X", "AB"]
    assert carte_4.prises_origine == ["Z"]
    assert trop_tot == []
    lignes = [ligne for ligne in carte_1.lignes_recues if ligne.startswith(("$H", "$X", "M6"))]
    assert lignes == ["$X", "M64 P0", "$HZ", "$HY", "$HX", "$HAB"]
    assert carte_4.sorties[4] is True and carte_1.sorties[0] is True and portique.freins_desserres
    # Le pont est remis d'équerre : chaque moteur s'est arrêté sur son fin de course.
    assert carte_1.travers["X"] == 0
    assert carte_1.positions["X"] == 233 and carte_4.positions["Z"] == 1100


def test_garage_de_repos_et_photo(banc):
    chef, portique, carte_1, carte_4, _ = banc
    assert jouer(chef, module_portique(portique, "origine")).statut == "fini"
    etat = jouer(chef, module_portique(portique, "photo_stockage"))
    assert etat.statut == "fini", etat.alarme
    # Photo du stockage : pont au bout opposé (0,233), les deux outils en haut.
    assert (carte_1.positions["X"], carte_1.positions["Z"], carte_4.positions["Z"]) == (
        233,
        1290,
        1100,
    )
    attendre(lambda: portique.pont_gare("stockage", portique.position_pont()), DELAI)
    etat = jouer(chef, module_portique(portique, "garage"))
    assert etat.statut == "fini", etat.alarme
    # Garage : pont à 2,495, mâts à 0,46 (centre du chariot à 0,50), freins serrés.
    assert (carte_1.positions["X"], carte_1.positions["Y"]) == (2495, 460)
    assert carte_1.sorties[0] is False and carte_4.sorties[4] is False
    assert portique.pont_gare("fut_poste", 2.495)


def test_alarme_d_un_pilote_arrete_et_dit_lequel(banc):
    chef, portique, carte_1, _, _ = banc
    carte_1.entrees.add("1")  # alarme du pilote de X2
    attendre(lambda: portique.pilotes_en_alarme() == ["moteur X2 du pont"], DELAI)
    etat = jouer(chef, module_portique(portique, "origine"))
    assert etat.statut == "alarme"
    assert "alarme du pilote : moteur X2 du pont" in etat.alarme.message
    assert "pilote du portique est en alarme" in etat.alarme.quoi_faire
    # Rien n'a bougé : la prise d'origine n'est pas lancée.
    assert carte_1.prises_origine == []


def test_outil_sur_de_faux_fluidnc(capsys):
    from vidange.portique.outil import main

    assert main(["--faux", "origine"]) == 0
    sortie = capsys.readouterr().out
    assert "→ portique_origine_chariot_y" in sortie
    assert "pont_x             0.233" in sortie and "prehension_z       1.100" in sortie
    assert "Pilotes en alarme : aucun" in sortie


def test_signaux_du_portique_dans_la_liste():
    from vidange.entrees_sorties import charger_entrees_sorties

    liste = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
    for nom in (*ALARMES_PILOTES, *FREINS, "fdc_pont_x1", "fdc_pont_x2", "fdc_chariot_y"):
        assert liste.signaux[nom].module == "portique", nom
    # Fins de course NF ; « OK » du détecteur de chocs en 24 V sur la carte n° 1.
    assert liste.signaux["fdc_prehension_haut"].repos == "ferme"
    ok = liste.signaux["ok_chocs"]
    assert (ok.carte, ok.tension) == ("fluidnc_portique", 24)
    # Accéléromètre : X vertical, Y le long du pont, Z le long des rails : seuls Y et Z comptent.
    assert list(REGLAGES.accelerometre.capteur.axes) == ["y", "z"]
