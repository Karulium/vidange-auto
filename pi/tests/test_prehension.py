"""Préhension (tâche 37) : réglages, règles de mouvement, gestes au simulateur (pannes comprises),
vraie tête sur deux faux FluidNC, approche des mors du porte-bocal."""

import threading
import time

import pytest

from vidange.chef import ErreurEtape
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.fluidnc.directe import LiaisonDirecte
from vidange.griffe.simulation import FausseForce
from vidange.porte_bocal import PorteBocalFluidnc, signaux_porte_bocal
from vidange.porte_bocal.faux import FauxMaterielPorteBocal
from vidange.prehension import (
    CapteurVide,
    Contexte,
    ErreurVide,
    Objet,
    Pas,
    Pose,
    ReglesPrehension,
    TeteFluidnc,
    signaux_prehension,
)
from vidange.prehension.module import module_prehension
from vidange.prehension.outil import main as outil
from vidange.prehension.simulation import prehension_du_simulateur
from vidange.reglages import Fluidnc, charger_reglages
from vidange.simulateur import Simulateur
from vidange.simulateur.outil import main as simulateur

from .conftest import DOSSIER_PI
from .test_fluidnc_liaison import DELAI
from .test_reglages import erreur_de, remplacer

LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
PREHENSION = MACHINE.prehension
assert PREHENSION is not None
REGLES = ReglesPrehension(MACHINE)
OBJETS = PREHENSION.objets
SEAU = Objet.depuis("seau", OBJETS["seau"])
BOCAL = Objet.depuis("bocal", OBJETS["bocal"])
# Panneau du poste du fût levé (production) : isolation du fût.
PRODUCTION = Contexte()
# Tête en haut, loin du fût et des caméras.
HAUT = Pose(x=1.6, y=0.6, z=1.10, a=0.0)


def refus(pose: Pose, contexte: Contexte = PRODUCTION) -> str | None:
    return REGLES.refus_pose(pose, contexte)


# ---------------------------------------------------------------- réglages


def test_reglages_de_la_prehension_du_depot():
    assert PREHENSION.exemple
    assert PREHENSION.decalage_mat_x == 0.129
    assert PREHENSION.haut_z == 1.10
    assert (PREHENSION.vide.prise_kpa, PREHENSION.vide.perte_kpa) == (-55, -40)
    assert MACHINE.axes["prehension_z"].carte == MACHINE.axes["prehension_a"].carte == "prehension"
    # Chaque signal de la carte n° 4 cité dans fluidnc.yaml est dans la liste des entrées/sorties.
    carte = REGLAGES.fluidnc.cartes["prehension"]
    for nom in (*carte.entrees, *carte.sorties):
        assert LISTE.signaux[nom].carte == "fluidnc_prehension", nom
    assert LISTE.signaux["vide_venturi"].module == "prehension"


def test_conversion_du_capteur_de_vide():
    # Repères de la fiche : 0 kPa → 0,333 V lus, −40 → 1,40 V, −55 → 1,80 V, −100 → 3,00 V.
    conversion = LISTE.signaux["vide_venturi"].conversion
    assert conversion is not None
    (v0, v1), (k0, k1) = conversion.volts, conversion.valeurs

    def kpa(volts: float) -> float:
        return k0 + (volts - v0) * (k1 - k0) / (v1 - v0)

    assert kpa(0.333) == pytest.approx(0)
    assert kpa(1.40) == pytest.approx(-40, abs=0.1)
    assert kpa(1.80) == pytest.approx(-55, abs=0.1)
    assert kpa(3.00) == pytest.approx(-100)


def test_reglages_de_la_prehension_verifies(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "    prise_kpa: -55", "    prise_kpa: -30")
    remplacer(machine, "    appui_max_n: 100", "    appui_max_n: 200")
    message = erreur_de(reglages)
    assert "prise_kpa doit être un vide plus fort (plus bas) que perte_kpa" in message
    assert "il faut appui_min_n ≤ appui_n ≤ appui_max_n < arret_n" in message


def test_objets_de_la_prehension_verifies(reglages):
    capsule = "    capsule: {rayon_m: 0.0515, dessus_m: 0, dessous_m: 0.01, aimants: true}\n"
    remplacer(reglages / "machine.yaml", capsule, "")
    assert "objets : il manque « capsule »" in erreur_de(reglages)


def test_hauteurs_et_boitier_de_la_prehension_verifies(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "  haut_z: 1.10\n", "  haut_z: 1.20\n")
    remplacer(machine, ", z_haut: 1.062}", "}")
    remplacer(machine, "  prehension_geste_max: 300\n", "")
    message = erreur_de(reglages)
    assert "prehension → haut_z : 1.2 m hors de la course de prehension_z" in message
    assert "griffe → camera_bocal : il faut « z_haut » pour la préhension" in message
    assert "délai « prehension_geste_max » absent de durees" in message


def test_garage_du_porte_bocal_verifie(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "    x: 0.565\n    y: 0.150\n", "    x: 0.575\n    y: 0.150\n")
    remplacer(machine, "    course_manivelle_m: 0.07\n", "    course_manivelle_m: 0.10\n")
    message = erreur_de(reglages)
    assert "porte_bocal → x : 0.575 m, loin du garage de l'agitateur" in message
    assert "course_manivelle_m : 0.1 m n'est pas un trou de la manivelle permis" in message


def test_signaux_de_la_carte_de_la_prehension_verifies(reglages):
    remplacer(reglages / "fluidnc.yaml", "      vanne_vide: 0\n", "")
    message = erreur_de(reglages)
    assert "cartes → prehension → sorties : il manque « vanne_vide » (préhension)" in message


# ---------------------------------------------------------------- règles


def test_isolation_du_fut():
    # Sous x 0,71, panneau pas vu rabattu : face en haut seulement.
    assert refus(Pose(x=0.65, y=0.30, z=1.10, a=0)) is None
    assert "isolation du fût" in refus(Pose(x=0.65, y=0.30, z=1.0, a=0))
    assert refus(Pose(x=0.65, y=0.30, z=1.0, a=0), Contexte(panneau_rabattu=True)) is None
    assert refus(Pose(x=0.75, y=0.30, z=1.0, a=0)) is None


# Agitateur au garage manivelle en bas, griffe en butée haute : la zone du garage est permise.
GARAGE_PRET = Contexte(manivelle_en_bas=True, griffe_en_butee_haute=True)
PORTE_BOCAL = PREHENSION.porte_bocal
# Tête en haut, à la verticale du bocal au garage.
AU_GARAGE = Pose(x=PORTE_BOCAL.x, y=PORTE_BOCAL.y, z=1.10, a=0)


def test_porte_bocal_au_garage_y_0_150():
    assert PORTE_BOCAL.y == pytest.approx(0.150)
    assert PORTE_BOCAL.zone_garage_m == pytest.approx(0.005)


def test_zone_du_garage_exception_a_l_isolation_du_fut():
    bas = AU_GARAGE.avec(z=PORTE_BOCAL.face_z)
    # Panneau pas vu rabattu : permis dans la petite zone, conditions remplies.
    assert refus(bas, GARAGE_PRET) is None
    assert refus(bas.avec(x=bas.x + 0.005, y=bas.y - 0.005), GARAGE_PRET) is None
    # Hors de la petite zone (6 mm) : l'isolation du fût revient.
    assert "isolation du fût" in refus(bas.avec(x=bas.x + 0.006), GARAGE_PRET)
    assert "isolation du fût" in refus(bas.avec(y=bas.y + 0.006), GARAGE_PRET)


def test_zone_du_garage_manivelle_pas_en_bas():
    bas = AU_GARAGE.avec(z=PORTE_BOCAL.face_z)
    pas_en_bas = Contexte(griffe_en_butee_haute=True)
    # Manivelle en haut : la capsule (1,1325) dépasse la butée haute de la tête (1,10), la tête
    # ne passe jamais au-dessus du bocal, même en haut et panneau rabattu.
    for pose in (AU_GARAGE, bas, AU_GARAGE.avec(x=PORTE_BOCAL.x + 0.09)):
        assert "manivelle pas en bas : sa capsule monte à 1,1325 m" in refus(pose, pas_en_bas)
    rabattu = Contexte(panneau_rabattu=True, griffe_en_butee_haute=True)
    assert "manivelle pas en bas" in refus(AU_GARAGE, rabattu)
    # Avec un bocal tenu, la zone interdite est plus large.
    loin = AU_GARAGE.avec(x=PORTE_BOCAL.x + 0.11)
    assert refus(loin, pas_en_bas) is None
    tenu = Contexte(objet=BOCAL, griffe_en_butee_haute=True)
    assert "manivelle pas en bas" in refus(loin.avec(z=1.10), tenu)
    # Agitateur pas au garage : le bocal n'y est pas, mais la tête n'y descend pas.
    ailleurs = Contexte(agitateur_au_garage=False, griffe_en_butee_haute=True)
    assert refus(AU_GARAGE, ailleurs) is None
    assert "il faut l'agitateur au garage, manivelle en bas" in refus(bas, ailleurs)


def test_zone_du_garage_course_declaree():
    bas = AU_GARAGE.avec(z=PORTE_BOCAL.face_z)
    mycelium = MACHINE.mycelium.model_copy(update={"course_agitation_m": 0.04})
    regles = ReglesPrehension(MACHINE.model_copy(update={"mycelium": mycelium}))
    assert "course de la manivelle déclarée 4 cm" in regles.refus_pose(bas, GARAGE_PRET)
    sans = ReglesPrehension(MACHINE.model_copy(update={"mycelium": None}))
    assert "déclarée inconnue" in sans.refus_pose(bas, GARAGE_PRET)


def test_zone_du_garage_griffe_pas_en_butee_haute():
    bas = AU_GARAGE.avec(z=PORTE_BOCAL.face_z)
    assert "il faut la griffe en butée haute" in refus(bas, Contexte(manivelle_en_bas=True))
    # Même panneau rabattu : la griffe est sur le même pont.
    rabattu = Contexte(panneau_rabattu=True, manivelle_en_bas=True)
    assert "il faut la griffe en butée haute" in refus(bas, rabattu)


def test_zone_du_garage_mors():
    bas = AU_GARAGE.avec(z=PORTE_BOCAL.face_z)

    def descente(**valeurs) -> str | None:
        contexte = Contexte(manivelle_en_bas=True, griffe_en_butee_haute=True, **valeurs)
        return REGLES.refus_mouvement(AU_GARAGE, bas, contexte)

    # Poser : bocal tenu, mors ouverts.
    assert descente(objet=BOCAL, mors="ouverts") is None
    assert "pour poser le bocal, il faut les mors ouverts" in descente(objet=BOCAL, mors="serres")
    assert "il faut les mors ouverts" in descente(objet=BOCAL, mors=None)
    # Prendre : tête vide, mors serrés sur le bocal.
    assert descente(mors="serres") is None
    assert "pour prendre le bocal, il faut les mors serrés" in descente(mors="ouverts")
    assert "il faut les mors serrés" in descente(mors=None)
    # Rien d'autre n'y descend.
    capsule = Objet.depuis("capsule", OBJETS["capsule"])
    assert "que pour un bocal" in descente(objet=capsule, mors="serres")
    # Remonter est toujours permis (mors approchés après la pose).
    contexte = Contexte(manivelle_en_bas=True, griffe_en_butee_haute=True)
    assert REGLES.refus_mouvement(bas, AU_GARAGE, contexte) is None
    # Hors de la zone (panneau rabattu), les mors ne comptent pas.
    loin = Pose(x=0.65, y=0.30, z=1.10, a=0)
    rabattu = Contexte(panneau_rabattu=True)
    assert REGLES.refus_mouvement(loin, loin.avec(z=1.0), rabattu) is None


def test_seau_tenu_bord_limite():
    tenu = Contexte(objet=SEAU)
    # Seau A : 0,25 de haut. Au-dessus des piles, bord ≤ 1,155 ; côté opérateur ≤ 1,10.
    assert refus(Pose(x=1.6, y=0.6, z=0.90, a=0), tenu) is None
    assert "bord à 1,15" not in (refus(Pose(x=1.6, y=0.6, z=0.90, a=0), tenu) or "")
    assert "seau tenu (piles" in refus(Pose(x=1.6, y=0.6, z=0.91, a=0), tenu)
    assert "seau tenu (côté opérateur" in refus(Pose(x=1.6, y=0.87, z=0.86, a=0), tenu)
    assert REGLES.hauteur_trajet(SEAU, 0.6) == pytest.approx(0.905)
    assert REGLES.hauteur_trajet(SEAU, 0.6, 0.87) == pytest.approx(0.85)
    assert REGLES.hauteur_trajet(None, 0.6) == 1.10


def test_boitier_de_la_camera_du_bocal():
    # Contrôle de la fiche : y < 0,335, face sous 1,072 interdite, à partir de x 0,99.
    (x_min, x_max), y_max, bas_min = REGLES.zone_camera_bocal(None)
    assert x_min == pytest.approx(0.99) and y_max == pytest.approx(0.335)
    assert bas_min == pytest.approx(1.072)
    # La fiche dit x ≤ 1,16 : avec la boîte de machine.yaml (x ≤ 1,085), c'est 1,14 (question
    # de la PR de la tâche 37).
    assert x_max == pytest.approx(1.14)
    assert refus(Pose(x=1.05, y=0.30, z=1.07, a=0)) is not None
    assert refus(Pose(x=1.05, y=0.30, z=1.075, a=0)) is None
    assert refus(Pose(x=1.05, y=0.34, z=1.0, a=0)) is None
    # Avec un bocal (rayon 0,0515, 0,17 sous la face) : zone plus large, et le bas du bocal compte.
    (x_min, _), y_max, _ = REGLES.zone_camera_bocal(BOCAL)
    assert x_min == pytest.approx(0.9835) and y_max == pytest.approx(0.3415)
    assert "boîtier de la caméra du bocal" in refus(
        Pose(x=1.05, y=0.30, z=1.10, a=0), Contexte(objet=BOCAL)
    )


def test_camera_du_dosage():
    pivote = Contexte(camera_dosage_pivote=True, panneau_rabattu=True)
    dans = Pose(x=0.9, y=0.2, z=1.05, a=0)
    assert refus(dans, Contexte(panneau_rabattu=True)) is None
    assert "la caméra du dosage pivote" in refus(dans, pivote)
    assert refus(dans.avec(z=1.10), pivote) is None
    assert refus(dans.avec(y=0.40), pivote) is None


def test_pont_et_tete_jamais_ensemble_et_pont_tete_en_haut():
    bas = HAUT.avec(z=0.9)
    assert "pont et tête ensemble refusés" in REGLES.refus_mouvement(
        HAUT, bas.avec(x=1.7), PRODUCTION
    )
    assert "déplacement du pont tête basse refusé" in REGLES.refus_mouvement(
        bas, bas.avec(x=1.7), PRODUCTION
    )
    assert REGLES.refus_mouvement(HAUT, HAUT.avec(x=1.7), PRODUCTION) is None
    # Seau tenu : « en haut » est la hauteur que permet son bord.
    tenu = Contexte(objet=SEAU)
    seau_haut = HAUT.avec(z=0.905)
    assert REGLES.refus_mouvement(seau_haut, seau_haut.avec(x=1.9), tenu) is None


def test_la_tete_ne_tourne_pas_entre_les_mors():
    porte_bocal = PREHENSION.porte_bocal
    rabattu = Contexte(panneau_rabattu=True, manivelle_en_bas=True, griffe_en_butee_haute=True)
    dedans = Pose(x=porte_bocal.x, y=porte_bocal.y, z=porte_bocal.face_z, a=0)
    assert "ne tourne jamais entre les mors" in REGLES.refus_mouvement(
        dedans, dedans.avec(a=10), rabattu
    )
    dessus = dedans.avec(z=1.10)
    assert REGLES.refus_mouvement(dessus, dessus.avec(a=10), rabattu) is None


def test_pont_hors_de_la_zone_du_chariot_pendant_l_echange():
    echange = Contexte(echange_fut=True, panneau_rabattu=True)
    # Pont = axe − 0,129 : interdit en x 0 à 0,80 pendant l'échange du fût.
    assert "pont interdit" in refus(Pose(x=0.9, y=0.6, z=1.10, a=0), echange)
    assert refus(Pose(x=0.95, y=0.6, z=1.10, a=0), echange) is None


# ---------------------------------------------------------------- gestes au simulateur


def reglages_avec_capteurs(*capteurs: str):
    simulation = REGLAGES.simulateur
    scenario = simulation.scenarios["prehension"].model_copy(
        update={"capteurs_actionnes": list(capteurs)}
    )
    simulation = simulation.model_copy(
        update={"scenarios": {**simulation.scenarios, "prehension": scenario}}
    )
    return REGLAGES.model_copy(update={"simulateur": simulation})


def jouer(regler=lambda tete: None, reglages=REGLAGES, preparer=None, **options):
    """Rejoue le scénario « prehension » ; rend le planning, la préhension et le simulateur.
    `preparer(prehension, simulation)` : changer la machine imaginaire avant de jouer."""
    with Simulateur(reglages, LISTE, "prehension") as simulation:
        prehension = prehension_du_simulateur(simulation, **options)
        regler(prehension.tete)
        if preparer is not None:
            preparer(prehension, simulation)
        places = reglages.simulateur.prehension
        assert places is not None
        planning = simulation.jouer([module_prehension(prehension, places)])
        return planning, prehension, simulation


def etapes(planning) -> list[str]:
    return [ligne.etape for ligne in planning.lignes]


def test_tous_les_gestes_au_simulateur():
    planning, prehension, simulation = jouer()
    assert planning.fini, planning.probleme
    assert etapes(planning)[-1] == "visser_la_capsule"
    porte_bocal = prehension.porte_bocal
    assert porte_bocal.gestes == ["ouvrir", "approcher", "serrer", "ouvrir"]
    tete = prehension.tete
    # Accélération réduite pendant les trajets avec le seau seulement.
    assert tete.accelerations[:3] == [False, True, False]
    assert prehension.objet is None
    assert simulation.etat_axes.positions["prehension_z"] == pytest.approx(1.10)


def test_simulateur_en_ligne_de_commande(capsys):
    assert simulateur(["prehension"]) == 0
    texte = capsys.readouterr().out
    assert "visser_la_capsule" in texte and "Temps total" in texte


def test_vide_perdu_une_fois_pendant_la_levee():
    def regler(tete):
        tete.pertes_de_vide = 1

    planning, prehension, _ = jouer(regler)
    assert planning.fini, planning.probleme
    # Redescendu, reposé (vanne fermée), repris (vanne ouverte).
    assert prehension.tete.sorties[:3] == ["vanne ouverte", "vanne fermée", "vanne ouverte"]


def test_vide_perdu_deux_fois_alerte():
    def regler(tete):
        tete.pertes_de_vide = 2

    planning, prehension, _ = jouer(regler)
    assert not planning.fini
    assert "vide perdu 2 fois pendant la levée d'un(e) seau" in planning.probleme
    assert etapes(planning) == ["prendre_le_seau"]
    assert prehension.objet is None and prehension.tete.sorties[-1] == "vanne fermée"


def test_deux_seaux_pris_reposes():
    def regler(tete):
        tete.poids_n = 10.0

    planning, prehension, simulation = jouer(regler)
    assert "deux seaux emboîtés pris (10.0 N" in planning.probleme
    assert prehension.objet is None and prehension.tete.sorties[-1] == "vanne fermée"
    # Reposés, puis la tête est remontée.
    assert simulation.etat_axes.positions["prehension_z"] == pytest.approx(1.10)


def test_contact_trop_bas():
    def regler(tete):
        tete.decalage_contact_m = None

    planning, _, _ = jouer(regler)
    assert "contact trop bas, rien touché jusqu'à 0,595 m (attendu à 0,6 m)" in planning.probleme


def test_contact_trop_haut_anse_levee():
    def regler(tete):
        tete.decalage_contact_m = 0.01

    planning, _, _ = jouer(regler)
    assert "contact à 0,61 m, attendu à 0,6 m (± 0,005) : anse levée ?" in planning.probleme


def test_anse_levee_vue_par_la_camera():
    planning, prehension, _ = jouer(anse_levee=lambda: True)
    assert "la caméra voit une anse levée" in planning.probleme
    assert prehension.tete.sorties == []


def test_choc_pendant_un_trajet():
    photos: list[str] = []

    def regler(tete):
        tete.choc_au_trajet = True

    planning, _, _ = jouer(regler, photo=photos.append)
    assert "choc pendant un trajet de la préhension" in planning.probleme
    assert "remontée lentement" in planning.probleme
    assert photos == ["choc de la préhension"]


def test_porte_bocal_panneau_leve():
    # Panneau du poste du fût levé (contact fermé, production) : la tête descend quand même au
    # porte-bocal, dans la petite zone du garage (exception à l'isolation du fût).
    reglages = reglages_avec_capteurs("chariot_fut_en_place", "reed_panneau_poste_fut")
    planning, _, _ = jouer(reglages=reglages)
    assert planning.fini, planning.probleme


def axe_imaginaire(nom: str, valeur: float):
    def preparer(prehension, simulation):
        simulation.etat_axes.positions[nom] = valeur

    return preparer


def test_porte_bocal_manivelle_en_haut_au_simulateur():
    planning, _, _ = jouer(preparer=axe_imaginaire("manivelle", 0.0))
    assert etapes(planning)[-1] == "poser_au_porte_bocal"
    assert "manivelle pas en bas" in planning.probleme


def test_porte_bocal_griffe_basse_au_simulateur():
    planning, _, _ = jouer(preparer=axe_imaginaire("griffe_z", 1.2))
    assert etapes(planning)[-1] == "poser_au_porte_bocal"
    assert "il faut la griffe en butée haute" in planning.probleme


def test_porte_bocal_mors_pas_ouverts_au_simulateur():
    # Mors restés serrés (l'ouverture n'a rien fait) : la tête ne descend pas poser.
    def preparer(prehension, simulation):
        porte_bocal = prehension.porte_bocal
        porte_bocal.ouvrir_mors = lambda: porte_bocal._geste("ouvrir", "serres")

    planning, _, _ = jouer(preparer=preparer)
    assert etapes(planning)[-1] == "poser_au_porte_bocal"
    assert "pour poser le bocal, il faut les mors ouverts" in planning.probleme


def test_vissage_au_dela_de_150_n():
    def regler(tete):
        tete.appui_vissage_n = 160.0

    planning, _, _ = jouer(regler)
    assert etapes(planning)[-1] == "visser_la_capsule"
    assert "visser : appui de 160 N, au-delà de 150 N : arrêt" in planning.probleme


def test_vissage_appui_trop_faible():
    def regler(tete):
        tete.appui_vissage_n = 40.0

    planning, _, _ = jouer(regler)
    assert "appui de 80 N pas atteint" in planning.probleme


def test_tient_un_objet_et_memoire():
    with Simulateur(REGLAGES, LISTE, "prehension") as simulation:
        prehension = prehension_du_simulateur(simulation)
        assert not prehension.tient_un_objet()
        prehension.objet = SEAU
        prehension.tete.vanne(True)
        assert prehension.tient_un_objet()
        prehension.tete.vanne(False)
        assert not prehension.tient_un_objet()
        memoire = prehension.memoire()
        autre = prehension_du_simulateur(simulation)
        autre.retrouver(memoire)
        assert autre.objet == SEAU
        assert prehension.hors_boite_camera_dosage()
        assert "pont et tête ensemble" in prehension.refus_manuel(Pose(x=1.0, y=0.5, z=0.9, a=0))


def test_seau_au_format_de_la_table():
    with Simulateur(REGLAGES, LISTE, "prehension") as simulation:
        prehension = prehension_du_simulateur(simulation)
        seau_b = prehension.objet_par_nom("seau", "seau_b")
        assert (seau_b.rayon_m, seau_b.dessus_m) == (0.115, 0.20)
        with pytest.raises(ErreurEtape, match="format de seau inconnu"):
            prehension.objet_par_nom("seau", "seau_z")


# ---------------------------------------------------------------- la vraie tête


def reglages_cartes() -> Fluidnc:
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
                "portique": {"numero_serie_usb": "A1"},
                "prehension": {
                    "numero_serie_usb": "A4",
                    "entrees": {"contact_tete": "P"},
                    "sorties": {"vanne_vide": 0, "electroaimants_capsule": 1},
                },
            },
        }
    )


class FauxVide:
    def __init__(self, kpa: float = 0.0) -> None:
        self.kpa = kpa
        self.fonction = None

    def lire(self) -> float:
        return self.fonction() if self.fonction is not None else self.kpa


class BancTete:
    """La vraie tête sur deux faux FluidNC (portique, préhension), fausse pesée, faux vide."""

    def __init__(self) -> None:
        self.portique = FauxFluidnc(axes="XYZAB")
        self.carte = FauxFluidnc(axes="XYZA", vitesse_rapide_mm_min=20000)
        # Pont à 1,471 (axe de la tête 1,6), y 0,6 ; face de la tête à 1,0 m.
        self.portique.positions.update(X=1471.0, Y=600.0)
        self.carte.positions.update(Z=1000.0)
        self.force = FausseForce(20.0)
        self.vide = FauxVide(0.3)
        reglages = reglages_cartes()
        self.liaison_portique = Liaison("portique", reglages, ouvrir=self.portique.ouvrir)
        self.liaison_tete = Liaison("prehension", reglages, ouvrir=self.carte.ouvrir)
        self.signaux = signaux_prehension(self.liaison_tete, reglages.cartes["prehension"])

    def __enter__(self) -> "BancTete":
        for liaison in (self.liaison_portique, self.liaison_tete):
            liaison.demarrer()
            liaison.attendre_connexion(DELAI)
        capteur = CapteurVide(PREHENSION.vide, self.vide.lire)
        self.tete = TeteFluidnc(
            MACHINE, self.liaison_portique, self.liaison_tete, self.signaux, self.force, capteur
        )
        self.arret = threading.Event()
        self.tete.demarrer(self.arret)
        attendre(lambda: self.tete.vide_kpa() is not None)
        time.sleep(0.1)
        return self

    def __exit__(self, *_: object) -> None:
        self.arret.set()
        self.liaison_portique.arreter()
        self.liaison_tete.arreter()


def attendre(condition, delai: float = DELAI) -> None:
    fin = time.monotonic() + delai
    while not condition():
        assert time.monotonic() < fin, "pas arrivé à temps"
        time.sleep(0.01)


def test_zero_du_vide_recale_au_demarrage():
    with BancTete() as banc:
        # Vanne fermée au démarrage ; le zéro (0,3 kPa) est retiré des lectures.
        assert banc.carte.sorties[0] is False
        assert banc.tete.vide.zero == pytest.approx(0.3)
        assert banc.tete.vide_kpa() == pytest.approx(0.0)
    capteur = CapteurVide(PREHENSION.vide, lambda: 8.0)
    with pytest.raises(ErreurVide, match="zéro du capteur de vide à \\+8.0 kPa"):
        capteur.recaler_zero()
    with pytest.raises(ErreurVide, match="pas encore recalé"):
        capteur.lire()


def test_tete_va_a_une_pose_et_ouvre_la_vanne():
    with BancTete() as banc:
        pose = banc.tete.position()
        assert pose.x == pytest.approx(1.6) and pose.z == pytest.approx(1.0)
        banc.tete.executer(Pas("monter", {"z": 1.05}), pose.avec(z=1.05), 0.0)
        assert banc.carte.lignes_recues[-1].startswith("$J=G53 Z1050.000")
        attendre(banc.tete.fini)
        assert banc.tete.resultat().pose.z == pytest.approx(1.05)
        banc.tete.vanne(True)
        attendre(lambda: banc.carte.sorties.get(0) is True)
        with pytest.raises(ErreurEtape, match="pont et tête jamais ensemble"):
            banc.tete.executer(Pas("faux", {"x": 1.7, "z": 1.0}), pose, 0.0)


def test_tete_palpe_le_contact():
    with BancTete() as banc:
        banc.carte.palpeur = lambda avant, arrivee: {**arrivee, "Z": 960.0}
        pose = banc.tete.position()
        pas = Pas("approche lente", {"z": 0.95}, vitesse="approche", palper=True)
        banc.tete.executer(pas, pose.avec(z=0.95), 0.0)
        attendre(banc.tete.fini, 10)
        assert "G91 G38.3 Z-50.000 F600" in banc.carte.lignes_recues
        resultat = banc.tete.resultat()
        assert resultat.contact and resultat.pose.z == pytest.approx(0.96)


def test_tete_vide_perdu_pendant_la_levee():
    with BancTete() as banc:
        # Le vide tient jusqu'à 1,005 m, puis lâche (−30 kPa).
        banc.vide.fonction = lambda: -69.7 if banc.carte.positions["Z"] < 1005 else -29.7
        time.sleep(0.1)
        pose = banc.tete.position()
        pas = Pas("levée", {"z": 1.05}, vitesse="levee_lente", vide_perte_kpa=-40)
        banc.tete.executer(pas, pose.avec(z=1.05), 5.0)
        attendre(banc.tete.fini, 10)
        resultat = banc.tete.resultat()
        assert resultat.arret == "vide"
        assert 1.004 < resultat.pose.z < 1.02


def test_tete_choc_pendant_un_trajet():
    with BancTete() as banc:
        banc.tete.tarer()
        pose = banc.tete.position()
        banc.tete.executer(Pas("trajet", {"x": 1.9}, choc=True), pose.avec(x=1.9), 0.0)
        # 30 N de plus que le poids porté (0), plus de 50 ms.
        banc.force.newtons = 50.0
        with pytest.raises(ErreurEtape, match="choc") as erreur:
            attendre(lambda: banc.tete.fini() and False, 3)
        assert "remontée lentement" in erreur.value.quoi_faire
        assert banc.tete.choc


def test_tete_appui_au_dela_de_150_n():
    with BancTete() as banc:
        banc.tete.tarer()
        # La poussée grandit quand la tête descend sous 0,99 m : 20 N par mm.
        banc.force.fonction = lambda: 20.0 - max(0.0, 990 - banc.carte.positions["Z"]) * 20
        pose = banc.tete.position()
        pas = Pas("visser", {"z": 0.98}, vitesse="approche", appui_max_n=150)
        banc.tete.executer(pas, pose.avec(z=0.98), 0.0)
        attendre(banc.tete.fini, 10)
        resultat = banc.tete.resultat()
        assert resultat.arret == "appui_max" and resultat.appui_max_n > 150
        assert resultat.pose.z > 0.98


def test_tete_acceleration_reduite_avec_un_seau():
    with BancTete() as banc:
        banc.tete.acceleration_seau(True)
        banc.tete.acceleration_seau(True)
        banc.tete.acceleration_seau(False)

        def lignes() -> list[str]:
            return [ligne for ligne in banc.portique.lignes_recues if "acceleration" in ligne]

        attendre(lambda: len(lignes()) == 4)
        assert lignes() == [
            "$/axes/x/acceleration_mm_per_sec2=150",
            "$/axes/y/acceleration_mm_per_sec2=150",
            "$/axes/x/acceleration_mm_per_sec2=500",
            "$/axes/y/acceleration_mm_per_sec2=500",
        ]


# ---------------------------------------------------------------- porte-bocal


def test_mors_approches_a_faible_courant():
    temps = [0.0]
    carte = FauxFluidnc(axes="XY", horloge=lambda: temps[0])
    liaison = LiaisonDirecte("mycelium_lavage", carte)
    reglages_carte = REGLAGES.fluidnc.cartes["mycelium_lavage"]
    materiel = FauxMaterielPorteBocal(carte, MACHINE, reglages_carte, 2.3, lambda: temps[0])
    porte_bocal = PorteBocalFluidnc(
        MACHINE,
        liaison,  # type: ignore[arg-type]
        signaux_porte_bocal(liaison, reglages_carte),  # type: ignore[arg-type]
        horloge=lambda: temps[0],
    )
    materiel.poser_bocal()

    def finir() -> None:
        for _ in range(200):
            temps[0] += 0.1
            if porte_bocal.fini():
                return
        raise AssertionError("geste des mors pas fini")

    porte_bocal.approcher_mors()
    finir()
    assert carte.lignes_recues[-3:] == [
        "$HY",
        "$/axes/y/motor0/tmc_2209/run_amps=0.2",
        "G90 G1 Y98.000 F1200",
    ]
    assert porte_bocal.diametre() == pytest.approx(0.098)
    # Approchés : ni ouverts, ni serrés (la tête ne redescend pas).
    assert not porte_bocal.ouverts() and not porte_bocal.serre()
    # Le courant du serrage est remis avant le serrage.
    porte_bocal.serrer_bocal()
    finir()
    assert "$/axes/y/motor0/tmc_2209/run_amps=0.6" in carte.lignes_recues[-4:]
    assert porte_bocal.serre() and not porte_bocal.ouverts()
    porte_bocal.ouvrir_mors()
    finir()
    assert carte.lignes_recues[-1] == "$HY"
    assert porte_bocal.ouverts() and not porte_bocal.serre()


# ---------------------------------------------------------------- outil


def test_outil_etat_avec_de_faux_fluidnc(capsys):
    assert outil(["--faux", "etat"]) == 0
    sortie = capsys.readouterr().out
    assert "axe de la tête : x 1.6000 m, y 0.6000 m" in sortie
    assert "face de la tête : z 1.1000 m" in sortie
    with pytest.raises(SystemExit):
        outil(["--faux", "visser", "1.5"])
    assert outil(["--faux", "prendre-poser", "seau", "a", "b", "c", "d", "e", "f"]) == 2
