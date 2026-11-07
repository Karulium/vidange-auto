"""Coupure de courant en plein geste, reprise au bon endroit, bilan d'une alarme.

Le module d'exemple, joué par le chef sur le faux FluidNC et les faux capteurs (temps réel).
"""

import json

import pytest

from vidange.chef import Axes, Carnet, Chef
from vidange.chef.exemple import module_exemple
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fiabilite import Bilans, module_lieu_sur
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.materiel import FausseFabrique, Materiel
from vidange.registre import Registre
from vidange.reglages import ReglagesBilan, ReglagesChef, charger_reglages

from .conftest import DOSSIER_PI
from .test_chef_exemple import attendre
from .test_fluidnc_liaison import DELAI, reglages_essai

REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")


class Machine:
    """Une « machine » : le faux FluidNC et les faux capteurs restent quand le Pi s'arrête."""

    def __init__(self, dossier) -> None:
        self.dossier = dossier
        self.faux = FauxFluidnc(axes="XYZABC", vitesse_rapide_mm_min=300_000)
        self.fabrique = FausseFabrique(LISTE)
        self.carnet = Carnet(dossier / "etat-cycle.json")

    def allumer_le_pi(self):
        """Démarre un « programme du Pi » : liaison, matériel, chef (avec le même carnet)."""
        liaison = Liaison("portique", reglages_essai(), ouvrir=self.faux.ouvrir)
        liaison.demarrer()
        liaison.attendre_connexion(DELAI)
        materiel = Materiel(LISTE, self.fabrique)
        chef = Chef(
            REGLAGES.machine, ReglagesChef(periode_s=0.01, alarme_pause_tout=True), self.carnet
        )
        liaisons = {"mycelium_lavage": liaison}
        exemple = module_exemple(Axes(REGLAGES.machine, liaisons), materiel)
        # Sans le geste du portique (ses cartes ne sont pas là) : seulement la carte n° 3.
        machine = REGLAGES.machine.model_copy(
            update={"lieu_sur": [g for g in REGLAGES.machine.lieu_sur if g.portique is None]}
        )
        lieu_sur = module_lieu_sur(machine, liaisons)
        return Pi(liaison, materiel, chef, exemple, lieu_sur)


class Pi:
    def __init__(self, liaison, materiel, chef, exemple, lieu_sur) -> None:
        self.liaison, self.materiel, self.chef = liaison, materiel, chef
        self.exemple, self.lieu_sur = exemple, lieu_sur

    def module(self, nom):
        return next(m for m in self.chef.etat().modules if m.module == nom)

    def eteindre(self) -> None:
        self.chef.arreter()
        self.liaison.arreter()
        self.materiel.fermer()


def exemple(faux) -> dict:
    """Les 3 axes d'exemple (lettres Z, B et C de la carte n° 3)."""
    return {lettre: faux.positions[lettre] for lettre in "ZBC"}


@pytest.fixture
def machine(tmp_path):
    return Machine(tmp_path)


def test_coupure_en_plein_geste_puis_reprise(machine):
    pi = machine.allumer_le_pi()
    machine.fabrique.actionner("reed_panneau_poste_fut")
    pi.chef.lancer(pi.exemple)
    pi.chef.demarrer()
    attendre(lambda: pi.chef.etat().attendent_go == ["exemple"])
    pi.chef.memoriser("exemple", seau="S1293")
    machine.faux.vitesse_rapide_mm_min = 600  # lent : la coupure arrive pendant le geste
    pi.chef.donner_go("exemple")
    attendre(lambda: machine.faux.en_mouvement)

    # Coupure de courant : le Pi s'arrête net, la carte redémarre (position perdue).
    pi.chef.arreter()
    pi.liaison.arreter()
    machine.faux.redemarrer()
    machine.faux.vitesse_rapide_mm_min = 300_000

    pi = machine.allumer_le_pi()
    assert pi.chef.reprendre_cycle([pi.exemple, pi.lieu_sur]) == ["exemple"]
    assert pi.chef.memoire("exemple") == {"seau": "S1293"}  # reprise au bon seau
    pi.chef.lancer(pi.lieu_sur)
    pi.chef.demarrer()
    try:
        attendre(lambda: pi.chef.etat().attendent_go == ["lieu_sur"])
        assert pi.module("exemple").attend == "fin de « lieu_sur »"
        assert pi.module("exemple").etape == "entrer_dans_la_zone_a"

        pi.chef.donner_go("lieu_sur")
        attendre(lambda: pi.module("lieu_sur").statut == "fini")
        assert "$H" in machine.faux.lignes_recues
        assert exemple(machine.faux) == {"Z": 800, "B": 500, "C": 1000}  # lieu sûr

        # Le module repris attend le Go, puis refait son étape depuis le début.
        attendre(lambda: pi.chef.etat().attendent_go == ["exemple"])
        pi.chef.donner_go("exemple")
        attendre(lambda: pi.module("exemple").statut == "fini")
        assert exemple(machine.faux) == {"Z": 800, "B": 500, "C": 1000}
    finally:
        pi.eteindre()


def test_prise_d_origine_ratee(machine):
    pi = machine.allumer_le_pi()
    pi.chef.lancer(pi.lieu_sur)
    pi.chef.demarrer()
    try:
        attendre(lambda: pi.chef.etat().attendent_go == ["lieu_sur"])
        machine.faux.vitesse_rapide_mm_min = 600
        machine.faux.positions["Z"] = 1000
        pi.chef.donner_go("lieu_sur")
        attendre(lambda: machine.faux.en_mouvement)
        machine.faux.declencher_alarme(9)
        attendre(lambda: pi.module("lieu_sur").statut == "alarme")
        alarme = pi.module("lieu_sur").alarme
        assert "prise d'origine" in alarme.message
        assert "fin de course" in alarme.quoi_faire
    finally:
        pi.eteindre()


def test_bilan_d_une_alarme_puis_acquittement(machine, tmp_path):
    pi = machine.allumer_le_pi()
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    journal = tmp_path / "journal.log"
    journal.write_text("".join(f"ligne {i}\n" for i in range(100)), encoding="utf-8")
    bilans = Bilans(
        tmp_path,
        ReglagesBilan(lignes_journal=3),
        registre,
        pi.chef,
        {"mycelium_lavage": pi.liaison},
        pi.materiel,
        lambda: [],
        journal,
    )
    bilans.collecteurs["essai"] = lambda: "en plus"
    recues = []
    pi.chef.sur_alarme += [bilans.recevoir, recues.append]
    machine.fabrique.actionner("reed_panneau_poste_fut")
    machine.faux.vitesse_rapide_mm_min = 600
    pi.chef.lancer(pi.exemple)
    pi.chef.demarrer()
    try:
        attendre(lambda: machine.faux.en_mouvement)
        pi.chef.memoriser("exemple", seau="S12")
        machine.faux.declencher_alarme(1)
        attendre(lambda: recues)
        numero = bilans.traiter(recues[0])

        alarme = registre.alarmes_ouvertes()[0]
        assert alarme["id"] == numero
        assert "fin de course" in alarme["quoi_faire"]
        bilan = json.loads((tmp_path / alarme["bilan"]).read_text(encoding="utf-8"))
        assert bilan["alarme"]["module"] == "exemple"
        assert bilan["memoire_du_module"] == {"seau": "S12"}
        assert bilan["cartes"]["mycelium_lavage"]["etat"] == "Alarm"
        assert set(bilan["cartes"]["mycelium_lavage"]["positions"]) == set("XYZABC")
        assert bilan["entrees"]["reed_panneau_poste_fut"] is True
        assert bilan["sorties"]["voyant_buzzer"] is False
        assert bilan["ambiance"]["sht31_armoire"]["temperature_c"] == pytest.approx(25, abs=0.1)
        assert bilan["journal"] == ["ligne 97", "ligne 98", "ligne 99"]
        assert bilan["clip_video"] is None
        assert bilan["essai"] == "en plus"

        bilans.acquitter(numero, "karulium")
        assert pi.module("exemple").statut == "en_cours"
        assert registre.alarmes_ouvertes() == []
    finally:
        pi.eteindre()
        registre.fermer()


# ------------------------------------- objet encore tenu à la ventouse (tâche 45 nonies)

VIDE = REGLAGES.machine.prehension.vide
PERIODE = REGLAGES.programme.fiabilite.objet_tenu.periode_s


class Capteur:
    """Un faux capteur de vide : rend `valeur` (kPa) à chaque lecture, ou lève `erreur`."""

    def __init__(self, valeur=0.0, erreur=None):
        self.valeur, self.erreur, self.lectures = valeur, erreur, 0

    def __call__(self):
        if self.erreur is not None:
            raise self.erreur
        self.lectures += 1
        return self.valeur


def test_reglages_de_l_objet_tenu():
    # Chiffre du fil Préhension (07/11/2026) : −20 kPa, entre la perte (−40) et le zéro (± 5).
    assert VIDE.tenu_au_demarrage_kpa == -20
    assert VIDE.perte_kpa <= VIDE.tenu_au_demarrage_kpa < -VIDE.zero_ecart_max_kpa
    assert PERIODE == 1


def test_seuil_de_l_objet_tenu_verifie_au_demarrage(reglages):
    from .test_reglages import erreur_de, remplacer

    remplacer(
        reglages / "machine.yaml",
        "    tenu_au_demarrage_kpa: -20",
        "    tenu_au_demarrage_kpa: -45",
    )
    assert "tenu_au_demarrage_kpa (-45) doit être au-dessus de perte_kpa (-40)" in erreur_de(
        reglages
    )
    remplacer(
        reglages / "machine.yaml", "    tenu_au_demarrage_kpa: -45", "    tenu_au_demarrage_kpa: -3"
    )
    assert "doit être plus bas que −zero_ecart_max_kpa (-5)" in erreur_de(reglages)


def test_objet_encore_tenu_puis_enleve_a_la_main():
    from vidange.fiabilite import ObjetTenu

    lire = Capteur(-51.0)
    objet = ObjetTenu(VIDE, lire, PERIODE)
    objet.regarder()
    # Une mesure = la moyenne de zero_lectures lectures brutes (le zéro n'est pas recalé).
    assert lire.lectures == VIDE.zero_lectures
    assert objet.tenu
    assert objet.refus_go() == (
        "objet encore tenu à la ventouse (vide -51 kPa) : l'enlever à la main"
    )
    (constat,) = objet.constats()
    assert constat.niveau == "bloquant" and "enlever à la main l'objet" in constat.quoi_faire
    # Pas encore enlevé : toujours pas de Go.
    objet._tour()
    assert objet.tenu
    # Karulium décolle un bord : le vide remonte, le Go revient.
    lire.valeur = -2.0
    objet._tour()
    assert not objet.tenu and objet.libere and objet.refus_go() is None
    assert objet.constats()[0].niveau == "ok"
    # Ensuite, plus jamais lu pendant cette marche : la ventouse tient des objets en travail.
    lire.valeur = -55.0
    avant = lire.lectures
    objet._tour()
    objet.regarder()
    assert lire.lectures == avant and objet.refus_go() is None


def test_rien_de_tenu_au_redemarrage():
    from vidange.fiabilite import ObjetTenu

    objet = ObjetTenu(VIDE, Capteur(-1.5), PERIODE)
    objet.regarder()
    assert objet.refus_go() is None and objet.libere
    assert objet.constats()[0].niveau == "ok"


def test_capteur_de_vide_illisible_ou_absent():
    from vidange.fiabilite import ObjetTenu

    objet = ObjetTenu(VIDE, Capteur(erreur=OSError("ADS1115 muet")), PERIODE)
    objet.regarder()
    # Le Pi ne sait pas : il n'attend pas, mais la check-list le dit.
    assert objet.refus_go() is None
    (constat,) = objet.constats()
    assert constat.niveau == "attention" and "illisible (ADS1115 muet)" in constat.texte
    assert "vérifier la tête de préhension" in constat.quoi_faire
    absent = ObjetTenu(VIDE, None, PERIODE, absent="capteur absent")
    absent.regarder()
    assert absent.refus_go() is None and absent.constats()[0].texte == "capteur absent"


def test_le_chef_refuse_tout_go_tant_qu_un_objet_est_tenu(machine):
    from vidange.chef import ErreurChef
    from vidange.fiabilite import ObjetTenu
    from vidange.quoi_faire import COUPURE_COURANT, PLANTAGE

    # La check-list de reprise le dit (fil Préhension, 07/11/2026).
    ligne = "vérifier la tête et le seau : enlever à la main l'objet tenu ou tombé avant le Go"
    assert ligne in COUPURE_COURANT and ligne in PLANTAGE

    # Après une coupure, un seau encore tenu à la ventouse (clapet anti-retour).
    machine.fabrique.regler("vide_venturi", -50)
    pi = machine.allumer_le_pi()
    objet = ObjetTenu(VIDE, lambda: pi.materiel.mesurer("vide_venturi"), PERIODE)
    objet.regarder()
    pi.chef.empecher_go(objet.refus_go)
    pi.chef.lancer(pi.lieu_sur)
    pi.chef.demarrer()
    try:
        attendre(lambda: pi.chef.etat().attendent_go == ["lieu_sur"])
        assert pi.chef.etat().go_empeche.startswith("objet encore tenu à la ventouse")
        with pytest.raises(ErreurChef, match="Go refusé : objet encore tenu à la ventouse"):
            pi.chef.donner_go("lieu_sur")
        # Aucun mouvement, aucune prise d'origine : la machine attend.
        assert "$H" not in machine.faux.lignes_recues
        assert pi.chef.etat().attendent_go == ["lieu_sur"]
        # Objet enlevé à la main : au tour suivant, le Go est accepté.
        machine.fabrique.regler("vide_venturi", 0)
        objet._tour()
        assert pi.chef.etat().go_empeche == ""
        pi.chef.donner_go("lieu_sur")
        attendre(lambda: pi.module("lieu_sur").statut == "fini")
        assert "$H" in machine.faux.lignes_recues
    finally:
        pi.eteindre()


def test_objet_tenu_au_demarrage_du_programme(tmp_path):
    from vidange.demarrage import preparer_objet_tenu

    fabrique = FausseFabrique(LISTE)
    materiel = Materiel(LISTE, fabrique)
    try:
        fabrique.regler("vide_venturi", -48)
        objet = preparer_objet_tenu(REGLAGES, materiel, LISTE, vraie_machine=False)
        objet.regarder()
        assert objet.tenu
        # Sur la vraie machine, une ligne d'EXEMPLE n'est jamais lue (sa conversion est fausse).
        vraie = preparer_objet_tenu(REGLAGES, materiel, LISTE, vraie_machine=True)
        vraie.regarder()
        assert vraie.refus_go() is None and "EXEMPLE" in vraie.constats()[0].texte
    finally:
        materiel.fermer()
    sans = preparer_objet_tenu(REGLAGES, None, LISTE, vraie_machine=False)
    assert "entrées/sorties pas ouvertes" in sans.constats()[0].texte


# ------------------------------- vannes de la ventouse fermées au démarrage (tâche 45 decies)

FLUIDNC = REGLAGES.fluidnc.model_copy(update={"liaison": reglages_essai().liaison})
VANNE = FLUIDNC.cartes["prehension"].sorties["vanne_vide"]


def vannes_sur(faux, fluidnc=FLUIDNC, presence=lambda nom: None, vraie_machine=False):
    from vidange.fiabilite import VannesAuDemarrage

    liaison = Liaison("prehension", fluidnc, ouvrir=faux.ouvrir)
    vannes = VannesAuDemarrage(
        fluidnc, {"prehension": liaison}, LISTE, presence, vraie_machine, attente_s=DELAI
    )
    return liaison, vannes


def test_attente_des_vannes_dans_les_reglages():
    assert REGLAGES.programme.fiabilite.objet_tenu.attente_vannes_s == 5


def test_aspirer_restee_ouverte_apres_un_plantage_est_fermee_jamais_ouverte():
    faux = FauxFluidnc()
    # Le Pi a planté vanne « aspirer » ouverte : la carte la garde ouverte.
    faux.sorties[VANNE] = True
    liaison, vannes = vannes_sur(faux)
    liaison.demarrer()
    try:
        vannes.fermer()
    finally:
        liaison.arreter()
    assert faux.sorties[VANNE] is False
    assert f"M65 P{VANNE}" in faux.lignes_recues
    # Rien d'autre : jamais d'ouverture (« souffler » ou autre), jamais de mouvement.
    assert not [ligne for ligne in faux.lignes_recues if ligne.startswith(("M64", "M62", "$"))]
    assert faux.prises_origine == [] and all(v == 0 for v in faux.positions.values())
    (constat,) = vannes.constats()
    assert constat.niveau == "ok" and constat.texte == "fermées au démarrage (vanne_vide)"
    # Une seule fois.
    avant = list(faux.lignes_recues)
    vannes.fermer()
    assert faux.lignes_recues == avant


def test_souffler_fermee_aussi_le_jour_ou_elle_est_cablee():
    carte = FLUIDNC.cartes["prehension"]
    libre = min(set(range(8)) - set(carte.sorties.values()))
    avec = carte.model_copy(update={"sorties": {**carte.sorties, "vanne_souffler": libre}})
    fluidnc = FLUIDNC.model_copy(update={"cartes": {**FLUIDNC.cartes, "prehension": avec}})
    faux = FauxFluidnc()
    liaison, vannes = vannes_sur(faux, fluidnc)
    liaison.demarrer()
    try:
        vannes.fermer()
    finally:
        liaison.arreter()
    assert vannes.fermees == ["vanne_vide", "vanne_souffler"]
    assert faux.sorties == {VANNE: False, libre: False}
    assert not [ligne for ligne in faux.lignes_recues if ligne.startswith(("M64", "M62"))]


def test_vannes_pas_fermees_la_check_list_le_dit():
    # Carte en alarme : FluidNC refuse l'ordre ; le Pi ne la débloque pas ($X), il le dit.
    faux = FauxFluidnc(en_alarme_au_depart=True)
    liaison, vannes = vannes_sur(faux)
    liaison.demarrer()
    try:
        vannes.fermer()
    finally:
        liaison.arreter()
    assert "$X" not in faux.lignes_recues and vannes.fermees == []
    (constat,) = vannes.constats()
    assert constat.niveau == "attention" and "vanne_vide pas fermée" in constat.texte
    assert "ne jamais ouvrir « souffler »" in constat.quoi_faire
    # Carte absente : rien n'est envoyé, rien n'attend.
    faux = FauxFluidnc()
    _, absente = vannes_sur(faux, presence=lambda nom: f"carte FluidNC « {nom} » pas branchée")
    absente.fermer()
    assert faux.lignes_recues == []
    assert "pas branchée" in absente.constats()[0].texte
    # Vraie machine, câblage en EXEMPLE : jamais d'ordre d'après lui.
    _, exemple = vannes_sur(faux, vraie_machine=True)
    exemple.fermer()
    assert faux.lignes_recues == [] and "EXEMPLE" in exemple.constats()[0].texte
