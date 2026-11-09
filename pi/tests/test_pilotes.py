"""Alarmes ALM des pilotes (tâches 24 et 24 bis) : la liste axe → alarme dans machine.yaml, une
entrée groupée par carte, vérifiée au démarrage ; lecture sur le faux FluidNC ; arrêt du module ;
alarme voulue du vissage (qui masque les autres pilotes de la carte) et sa remise à zéro, avec la
coupure du courant du pilote en 2e essai."""

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
    remplacer(reglages / "fluidnc.yaml", '      alarme_carte4: "0"\n', "")
    message = erreur_de(reglages)
    assert "il manque « alarme_carte4 » (alarme du pilote de l'axe « prehension_z »)" in message


def test_une_entree_alarme_sans_axe(reglages):
    remplacer(
        reglages / "fluidnc.yaml",
        '      alarme_carte4: "0"\n',
        '      alarme_carte4: "0"\n      alarme_fantome: "2"\n',
    )
    message = erreur_de(reglages)
    assert "alarme_fantome : aucun axe de machine.yaml" in message


def test_une_alarme_est_partagee_par_tous_les_axes_de_sa_carte():
    pilotes = MACHINE.pilotes
    assert pilotes is not None
    par_carte: dict[str, set[str]] = {}
    for axe, signaux in pilotes.alarmes.items():
        for signal in signaux:
            par_carte.setdefault(signal, set()).add(MACHINE.axes[axe].carte or "")
    assert sorted(par_carte) == ["alarme_carte1", "alarme_carte2", "alarme_carte3", "alarme_carte4"]
    assert all(len(cartes) == 1 for cartes in par_carte.values())
    # La griffe a ses ALM sur la carte n° 1 : elle n'est plus en sans_alarme.
    assert pilotes.alarmes["griffe_a"] == pilotes.alarmes["griffe_b"] == ["alarme_carte1"]
    assert "griffe_a" not in pilotes.sans_alarme and "griffe_b" not in pilotes.sans_alarme


def test_une_alarme_partagee_par_des_cartes_differentes_empeche_de_demarrer(reglages):
    remplacer(
        reglages / "machine.yaml",
        "    pousseur: [alarme_carte2]",
        "    pousseur: [alarme_carte1]",
    )
    assert "« alarme_carte1 » est donné à des axes de cartes différentes" in erreur_de(reglages)


def test_deux_entrees_d_une_carte_ne_peuvent_plus_avoir_la_meme_lettre(reglages):
    remplacer(
        reglages / "fluidnc.yaml",
        '      alarme_carte4: "0"\n',
        '      alarme_carte4: "0"\n      alarme_fantome: "0"\n',
    )
    assert "ont la même (0)" in erreur_de(reglages)


def test_coupure_active_sans_sortie_empeche_de_demarrer(reglages):
    remplacer(
        reglages / "machine.yaml",
        "      actif: false\n      # Axe",
        "      actif: true\n      # Axe",
    )
    remplacer(
        reglages / "machine.yaml",
        "        prehension_a: reset_pilote_rotation_prehension\n",
        "        manivelle_inconnue: reset_pilote_rotation_prehension\n",
    )
    message = erreur_de(reglages)
    assert "coupure → sorties : l'axe « manivelle_inconnue » n'a pas d'alarme" in message


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
    faux["portique"].lever_alarme_pilote(lettre("portique", "alarme_carte1"))
    attendre(lambda: pilotes.en_alarme(["pont_x"]), DELAI)
    # Une seule entrée pour la carte : les deux axes sont en alarme, un seul texte.
    assert len(pilotes.en_alarme(["chariot_y", "pont_x"])) == 1
    assert pilotes.en_alarme(["chariot_y"]) == pilotes.en_alarme(["pont_x"])
    # Les axes des autres cartes ne sont pas touchés.
    assert pilotes.en_alarme(["prehension_z", "plateau_z", "manivelle"]) == []


def test_l_alarme_de_la_carte_dit_qu_on_ne_sait_pas_lequel(cartes):
    faux, liaisons = cartes
    pilotes = Pilotes(MACHINE, CARTES, liaisons)
    faux["chariot"].lever_alarme_pilote(lettre("chariot", "alarme_carte2"))
    attendre(lambda: pilotes.en_alarme(["plateau_z"]), DELAI)
    texte = pilotes.en_alarme(["plateau_z"])[0]
    assert "un pilote de la carte « chariot »" in texte and "on ne sait pas lequel" in texte
    for axe in ("plateau_a", "pousseur", "barres", "barre_allee", "remplissage_y"):
        assert axe in texte
    assert "voyants" in pilotes.probleme_du_module("remplissage")[1]


def test_probleme_du_module_ignore_l_alarme_voulue(cartes):
    faux, liaisons = cartes
    pilotes = Pilotes(MACHINE, CARTES, liaisons)
    faux["prehension"].lever_alarme_pilote(lettre("prehension", "alarme_carte4"))
    attendre(lambda: pilotes.probleme_du_module("prehension"), DELAI)
    message, quoi_faire = pilotes.probleme_du_module("prehension")
    assert "un pilote de la carte « prehension »" in message and "pilote" in quoi_faire
    assert pilotes.probleme_du_module("mycelium") is None
    pilotes.attendre("prehension_a")
    assert pilotes.probleme_du_module("prehension") is None


def test_l_alarme_voulue_masque_les_autres_pilotes_de_la_carte_pendant_le_pas(cartes):
    faux, liaisons = cartes
    pilotes = Pilotes(MACHINE, CARTES, liaisons)
    faux["prehension"].lever_alarme_pilote(lettre("prehension", "alarme_carte4"))
    attendre(lambda: pilotes.axes_en_alarme(["prehension_z"]), DELAI)
    pilotes.attendre("prehension_a")
    # Le Z, le noyau et la couronne sont sur la même carte : masqués aussi, pour tous les modules.
    for module in ("prehension", "entonnoir", "lavage", "portique_origine"):
        assert pilotes.probleme_du_module(module) is None, module
    # Mais la lecture brute reste vraie (la tête voit son calage).
    assert pilotes.axes_en_alarme(["prehension_a"]) == ["prehension_a"]
    # Les autres cartes ne sont pas masquées.
    faux["chariot"].lever_alarme_pilote(lettre("chariot", "alarme_carte2"))
    attendre(lambda: pilotes.probleme_du_module("remplissage"), DELAI)
    # La remise à zéro rend la surveillance normale.
    pilotes.attendues.discard("prehension_a")
    assert pilotes.probleme_du_module("prehension") is not None


def test_remise_a_zero_de_l_alarme(cartes):
    faux, liaisons = cartes
    pilotes = Pilotes(MACHINE, CARTES, liaisons, dormir=lambda s: None)
    carte = faux["prehension"]
    carte.lignes_remise_pilote = {ligne.upper() for ligne in MACHINE.pilotes.remise_a_zero.lignes}
    carte.lever_alarme_pilote(lettre("prehension", "alarme_carte4"))
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
    carte.lever_alarme_pilote(lettre("prehension", "alarme_carte4"))
    attendre(lambda: pilotes.axes_en_alarme(["prehension_a"]), DELAI)
    court = MACHINE.pilotes.remise_a_zero.model_copy(update={"delai_max_s": 0.2, "attente_s": 0})
    pilotes.reglages = MACHINE.pilotes.model_copy(update={"remise_a_zero": court})
    from vidange.chef import ErreurEtape

    with pytest.raises(ErreurEtape, match="l'alarme ne retombe pas"):
        pilotes.remettre_a_zero("prehension_a")


class FauxRelais:
    """Le relais du Pi qui coupe le +48 V d'un pilote : à la coupure, son ALM retombe."""

    def __init__(self, carte=None, lettre=None, efface=True):
        self.appels = []
        self._carte, self._lettre, self._efface = carte, lettre, efface

    def ecrire(self, nom, commande):
        self.appels.append((nom, commande))
        if commande and self._efface and self._carte is not None:
            self._carte.retomber_alarme_pilote(self._lettre)


def pilotes_a_coupure(liaisons, relais, actif=True):
    coupure = MACHINE.pilotes.remise_a_zero.coupure
    assert coupure is not None and not coupure.actif
    court = MACHINE.pilotes.remise_a_zero.model_copy(
        update={
            "delai_max_s": 0.2,
            "attente_s": 0,
            "coupure": coupure.model_copy(update={"actif": actif, "attente_retour_s": 0}),
        }
    )
    machine = MACHINE.model_copy(
        update={"pilotes": MACHINE.pilotes.model_copy(update={"remise_a_zero": court})}
    )
    return Pilotes(machine, CARTES, liaisons, dormir=lambda s: None, relais=relais)


def alarme_qui_ne_retombe_qu_a_la_coupure(cartes, efface=True):
    faux, liaisons = cartes
    carte = faux["prehension"]
    carte.lignes_remise_pilote = {"$MD", "$ME"}
    carte.remise_impossible = True
    lettre_alarme = lettre("prehension", "alarme_carte4")
    carte.lever_alarme_pilote(lettre_alarme)
    return carte, FauxRelais(carte, lettre_alarme, efface), liaisons


def test_la_coupure_du_courant_est_le_2e_essai(cartes):
    carte, relais, liaisons = alarme_qui_ne_retombe_qu_a_la_coupure(cartes)
    pilotes = pilotes_a_coupure(liaisons, relais)
    attendre(lambda: pilotes.axes_en_alarme(["prehension_a"]), DELAI)
    pilotes.attendre("prehension_a")
    pilotes.remettre_a_zero("prehension_a")
    # D'abord $MD puis $ME, puis le relais K3 : coupé (True) puis remis (False).
    assert carte.lignes_recues[-2:] == ["$MD", "$ME"]
    assert relais.appels == [
        ("reset_pilote_rotation_prehension", True),
        ("reset_pilote_rotation_prehension", False),
    ]
    assert "prehension_a" not in pilotes.attendues


def test_pas_de_coupure_si_les_lignes_suffisent(cartes):
    faux, liaisons = cartes
    carte = faux["prehension"]
    carte.lignes_remise_pilote = {"$MD", "$ME"}
    carte.lever_alarme_pilote(lettre("prehension", "alarme_carte4"))
    relais = FauxRelais()
    pilotes = pilotes_a_coupure(liaisons, relais)
    attendre(lambda: pilotes.axes_en_alarme(["prehension_a"]), DELAI)
    pilotes.remettre_a_zero("prehension_a")
    assert relais.appels == []


def test_coupure_desactivee_par_defaut_l_alarme_reste(cartes):
    from vidange.chef import ErreurEtape

    carte, relais, liaisons = alarme_qui_ne_retombe_qu_a_la_coupure(cartes)
    pilotes = pilotes_a_coupure(liaisons, relais, actif=False)
    attendre(lambda: pilotes.axes_en_alarme(["prehension_a"]), DELAI)
    with pytest.raises(ErreurEtape, match="l'alarme ne retombe pas") as erreur:
        pilotes.remettre_a_zero("prehension_a")
    assert "même après" not in str(erreur.value)
    assert relais.appels == []


def test_la_coupure_qui_ne_sert_a_rien_est_dite(cartes):
    from vidange.chef import ErreurEtape

    carte, relais, liaisons = alarme_qui_ne_retombe_qu_a_la_coupure(cartes, efface=False)
    pilotes = pilotes_a_coupure(liaisons, relais)
    attendre(lambda: pilotes.axes_en_alarme(["prehension_a"]), DELAI)
    with pytest.raises(ErreurEtape, match="même après la coupure du courant"):
        pilotes.remettre_a_zero("prehension_a")
    # Le courant est toujours remis, même quand cela ne sert à rien.
    assert relais.appels[-1] == ("reset_pilote_rotation_prehension", False)


def test_coupure_active_sans_relais_est_refusee(cartes):
    _, liaisons = cartes
    with pytest.raises(ValueError, match="pas la carte des relais"):
        pilotes_a_coupure(liaisons, None)


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
        faux["chariot"].lever_alarme_pilote(lettre("chariot", "alarme_carte2"))
        attendre(lambda: chef.etat().modules[0].statut == "alarme", DELAI)
        etat = chef.etat().modules[0]
        assert "alarme du pilote" in etat.alarme.message
        assert arrete == [True]
    finally:
        chef.arreter()


def test_la_sortie_de_coupure_doit_etre_dans_la_liste_des_entrees_sorties(cartes):
    from types import SimpleNamespace

    from vidange.cycle.machine import _construire_pilotes

    _, liaisons = cartes
    coupure = MACHINE.pilotes.remise_a_zero.coupure.model_copy(update={"actif": True})
    remise = MACHINE.pilotes.remise_a_zero.model_copy(update={"coupure": coupure})
    machine = MACHINE.model_copy(
        update={"pilotes": MACHINE.pilotes.model_copy(update={"remise_a_zero": remise})}
    )
    reglages = REGLAGES.model_copy(update={"machine": machine})
    with pytest.raises(ValueError, match="reset_pilote_rotation_prehension"):
        _construire_pilotes(reglages, liaisons, None)
    sans = SimpleNamespace(branchements={})
    with pytest.raises(ValueError, match="reset_pilote_rotation_prehension"):
        _construire_pilotes(reglages, liaisons, sans)
    avec = SimpleNamespace(branchements={"reset_pilote_rotation_prehension": object()})
    assert isinstance(_construire_pilotes(reglages, liaisons, avec), Pilotes)
