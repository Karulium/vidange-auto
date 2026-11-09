"""Alarmes ALM des pilotes (tâche 24, points 1 et 2) : la liste axe → alarme dans machine.yaml,
vérifiée au démarrage ; lecture sur le faux FluidNC ; arrêt du module ; alarme voulue du vissage
et sa remise à zéro."""

import pytest

from vidange.chef import Chef, Etape, Module
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.pilotes import Pilotes
from vidange.reglages import ReglagesChef, charger_reglages

from .conftest import DOSSIER_PI
from .test_chef_exemple import attendre
from .test_fluidnc_liaison import reglages_essai
from .test_reglages import erreur_de, remplacer

REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
CARTES = REGLAGES.fluidnc.cartes
FLUIDNC = REGLAGES.fluidnc.model_copy(update={"liaison": reglages_essai().liaison})
DELAI = 10


def test_les_pilotes_du_depot_couvrent_tous_les_axes_moteur():
    pilotes = MACHINE.pilotes
    assert pilotes is not None and pilotes.remise_a_zero.exemple
    for nom, axe in MACHINE.axes.items():
        if axe.carte is not None:
            assert nom in pilotes.alarmes or nom in pilotes.sans_alarme, nom


def test_un_axe_moteur_sans_alarme_ni_raison_empeche_de_demarrer(reglages):
    remplacer(reglages / "machine.yaml", '    mors: "TMC2209', '    mors_oublie: "TMC2209')
    message = erreur_de(reglages)
    assert "pilotes → sans_alarme : axe inconnu « mors_oublie »" in message
    assert "l'axe moteur « mors » n'a ni entrée d'alarme" in message


def test_une_alarme_qui_manque_dans_fluidnc_yaml(reglages):
    remplacer(reglages / "fluidnc.yaml", '      alarme_rotation_tete: "1"\n', "")
    message = erreur_de(reglages)
    assert (
        "il manque « alarme_rotation_tete » (alarme du pilote de l'axe « prehension_a »)" in message
    )


def test_une_entree_alarme_sans_axe(reglages):
    remplacer(
        reglages / "fluidnc.yaml",
        '      alarme_rotation_tete: "1"\n',
        '      alarme_rotation_tete: "1"\n      alarme_fantome: "2"\n',
    )
    remplacer(reglages / "fluidnc.yaml", '      alarme_noyau_lavage: "2"\n', "")
    message = erreur_de(reglages)
    assert "alarme_fantome : aucun axe de machine.yaml" in message


def test_une_alarme_donnee_a_deux_axes(reglages):
    remplacer(
        reglages / "machine.yaml",
        "    pousseur: [alarme_pousseur]",
        "    pousseur: [alarme_barre_mur]",
    )
    assert "« alarme_barre_mur » est donné aux axes" in erreur_de(reglages)


def test_un_axe_d_alarme_que_aucun_module_ne_surveille(reglages):
    remplacer(reglages / "machine.yaml", "    mycelium: [manivelle]\n", "")
    assert "l'alarme de l'axe « manivelle » n'est surveillée par aucun module" in erreur_de(
        reglages
    )


@pytest.fixture
def cartes():
    portique = FauxFluidnc(axes="XYZAB")
    prehension = FauxFluidnc(axes="XYZABC")
    chariot = FauxFluidnc(axes="XYZABC")
    faux = {"portique": portique, "prehension": prehension, "chariot": chariot}
    liaisons = {nom: Liaison(nom, FLUIDNC, ouvrir=f.ouvrir) for nom, f in faux.items()}
    for liaison in liaisons.values():
        liaison.demarrer()
    try:
        for liaison in liaisons.values():
            liaison.attendre_connexion(DELAI)
        yield faux, liaisons
    finally:
        for liaison in liaisons.values():
            liaison.arreter()


def lettre(carte, signal):
    return CARTES[carte].entrees[signal]


def test_lecture_des_alarmes_par_axe(cartes):
    faux, liaisons = cartes
    pilotes = Pilotes(MACHINE, CARTES, liaisons)
    assert pilotes.en_alarme(["chariot_y", "pont_x"]) == []
    faux["portique"].lever_alarme_pilote(lettre("portique", "alarme_pont_x2"))
    attendre(lambda: pilotes.en_alarme(["pont_x"]), DELAI)
    assert pilotes.en_alarme(["chariot_y", "pont_x"]) == ["pilote de l'axe « pont_x »"]
    assert pilotes.en_alarme(["chariot_y"]) == []


def test_alarmes_cablees_ensemble_disent_l_un_des_pilotes(cartes):
    faux, liaisons = cartes
    pilotes = Pilotes(MACHINE, CARTES, liaisons)
    faux["chariot"].lever_alarme_pilote(lettre("chariot", "alarme_plateau_z"))
    attendre(lambda: pilotes.en_alarme(["plateau_z"]), DELAI)
    texte = pilotes.en_alarme(["plateau_z"])[0]
    assert "l'un des pilotes" in texte and "plateau_a" in texte and "pousseur" in texte


def test_probleme_du_module_ignore_l_alarme_voulue(cartes):
    faux, liaisons = cartes
    pilotes = Pilotes(MACHINE, CARTES, liaisons)
    faux["prehension"].lever_alarme_pilote(lettre("prehension", "alarme_rotation_tete"))
    attendre(lambda: pilotes.probleme_du_module("prehension"), DELAI)
    message, quoi_faire = pilotes.probleme_du_module("prehension")
    assert "pilote de l'axe « prehension_a »" in message and "pilote" in quoi_faire
    assert pilotes.probleme_du_module("mycelium") is None
    pilotes.attendre("prehension_a")
    assert pilotes.probleme_du_module("prehension") is None


def test_remise_a_zero_de_l_alarme(cartes):
    faux, liaisons = cartes
    pilotes = Pilotes(MACHINE, CARTES, liaisons, dormir=lambda s: None)
    carte = faux["prehension"]
    carte.lignes_remise_pilote = {ligne.upper() for ligne in MACHINE.pilotes.remise_a_zero.lignes}
    carte.lever_alarme_pilote(lettre("prehension", "alarme_rotation_tete"))
    attendre(lambda: pilotes.axes_en_alarme(["prehension_a"]), DELAI)
    pilotes.attendre("prehension_a")
    pilotes.remettre_a_zero("prehension_a")
    attendre(lambda: not pilotes.axes_en_alarme(["prehension_a"]), DELAI)
    assert "prehension_a" not in pilotes.attendues
    assert carte.lignes_recues[-2:] == ["$MD", "$ME"]


def test_alarme_qui_ne_retombe_pas(cartes):
    faux, liaisons = cartes
    pilotes = Pilotes(MACHINE, CARTES, liaisons)
    carte = faux["prehension"]
    carte.lignes_remise_pilote = {"$MD", "$ME"}
    carte.remise_impossible = True
    carte.lever_alarme_pilote(lettre("prehension", "alarme_rotation_tete"))
    attendre(lambda: pilotes.axes_en_alarme(["prehension_a"]), DELAI)
    court = MACHINE.pilotes.remise_a_zero.model_copy(update={"delai_max_s": 0.2, "attente_s": 0})
    pilotes.reglages = MACHINE.pilotes.model_copy(update={"remise_a_zero": court})
    from vidange.chef import ErreurEtape

    with pytest.raises(ErreurEtape, match="l'alarme ne retombe pas"):
        pilotes.remettre_a_zero("prehension_a")


def test_le_chef_arrete_le_module_dont_un_pilote_leve_son_alarme(cartes, tmp_path):
    faux, liaisons = cartes
    pilotes = Pilotes(MACHINE, CARTES, liaisons)
    chef = Chef(MACHINE, ReglagesChef(periode_s=0.01, alarme_pause_tout=False))
    chef.surveillance_pilotes = pilotes.probleme_du_module
    arrete = []
    module = Module(
        "remplissage",
        (
            Etape(
                "attendre",
                "rien",
                fin=__import__("vidange.chef", fromlist=["Condition"]).Condition(
                    "jamais", lambda: False
                ),
                delai_max="portique_origine_max",
            ),
        ),
        arreter=lambda: arrete.append(True),
    )
    chef.lancer(module)
    chef.demarrer()
    try:
        attendre(lambda: chef.etat().modules[0].statut == "en_cours", DELAI)
        faux["chariot"].lever_alarme_pilote(lettre("chariot", "alarme_pousseur"))
        attendre(lambda: chef.etat().modules[0].statut == "alarme", DELAI)
        etat = chef.etat().modules[0]
        assert "alarme du pilote" in etat.alarme.message
        assert arrete == [True]
    finally:
        chef.arreter()
