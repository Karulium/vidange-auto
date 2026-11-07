"""La vraie griffe dans les lots (tâche 45 sexies) : enchaînement avec le Remplissage, le Mycélium
et la Préhension (même pont), sur la machine imaginaire (les axes pont_x et chariot_y du
simulateur sont les mêmes pour la griffe et la préhension, comme sur la machine), et ses
conditions une par une sur de faux morceaux.
"""

import pytest

from vidange.chef import ErreurEtape
from vidange.cycle.griffe_du_lot import GriffeDuSeau, brancher_pont, garee
from vidange.cycle.mode_seaux import Lot, ModeSeaux, PiecesRemplissage
from vidange.cycle.ordre import verifier_ordre
from vidange.cycle.simulation import PiecesSimulees
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.griffe.regles import Pose as PoseGriffe
from vidange.griffe.simulation import griffe_du_simulateur
from vidange.prehension.regles import Pose as PosePrehension
from vidange.reglages import charger_reglages
from vidange.remplissage.module import SeauAFaire
from vidange.simulateur import Simulateur
from vidange.spray.zone import ZoneDuBras

from .conftest import DOSSIER_PI

REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
FORMAT = "seau_a"


@pytest.fixture(scope="module")
def liste():
    return charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")


class PiecesAvecLaGriffe(PiecesSimulees):
    """Les pièces du simulateur, avec la vraie griffe enchaînée au lot (GriffeDuSeau), sur le
    bras imaginaire de la griffe et le poste du fût du simulateur."""

    def __init__(self, simulateur):
        super().__init__(simulateur)
        self.griffe: GriffeDuSeau | None = None

    def manque(self, poste):
        if poste == "griffe":
            return None
        return super().manque(poste)

    def remplissage(self, lot, avec_micropore, avec_fermeture, avec_spray, avec_couvercle):
        pieces = super().remplissage(
            lot, avec_micropore, avec_fermeture, avec_spray, avec_couvercle
        )
        simulateur = self.simulateur
        imaginaire = griffe_du_simulateur(simulateur)
        mycelium = pieces.mycelium
        self.griffe = GriffeDuSeau(
            MACHINE,
            imaginaire.bras,
            imaginaire.poste,
            pieces.prehension,
            pieces.remplissage,
            lot.seaux,
            dosage_en_cours=mycelium.dosage_en_cours,
            horloge=lambda: simulateur.temps,
        )
        if pieces.plan.magasin is not None:
            pieces.plan.magasin.brancher_griffe(self.griffe.griffe)
        spray = pieces.spray
        zone = ZoneDuBras(
            MACHINE,
            self.griffe.griffe,
            pieces.prehension,
            bras_au_repos=None if spray is None else (lambda: not spray.bras_spray_sorti()),
        )
        zone.brancher()
        self.zone = zone
        return PiecesRemplissage(
            pieces.remplissage,
            pieces.prehension,
            mycelium,
            pieces.plan,
            spray=pieces.spray,
            griffe_partie=self.griffe.partie,
            couvercle=pieces.couvercle,
            zone_bras_spray=zone.libre,
            griffe=self.griffe,
        )


def lot_de(nombre):
    seaux = tuple(SeauAFaire(f"S{900 + n}", FORMAT, "pleurote_grise") for n in range(nombre))
    return Lot(FORMAT, seaux)


@pytest.fixture(scope="module")
def lot_joue(liste):
    with Simulateur(REGLAGES, liste, "cycle_griffe") as simulateur:
        pieces = PiecesAvecLaGriffe(simulateur)
        mode = ModeSeaux(REGLAGES, pieces, simulateur.chef)
        assert mode.pret("griffe")
        modules = mode.modules_du_lot(lot_de(2))
        planning = simulateur.jouer(modules)
        yield mode, pieces, planning, simulateur


def test_le_lot_de_seaux_part_avec_la_vraie_griffe(lot_joue):
    mode, pieces, planning, _ = lot_joue
    assert [module.nom for module in mode.en_cours.modules] == ["remplissage", "mycelium", "griffe"]
    assert planning.fini, planning.en_texte()
    # Les deux seaux pleins : 4 couches chacun, versées par la griffe, puis rangés.
    griffe = pieces.griffe
    assert griffe.versees == {0: 4, 1: 4}
    assert griffe.seau == 2
    assert not griffe.interrompus
    faites = [f"{ligne.module}.{ligne.etape}" for ligne in planning.lignes]
    assert faites.count("remplissage.ranger") == 2
    assert faites.count("griffe.essuyer_le_bord") == 2
    assert faites.count("griffe.tasser") >= 8


def test_la_zone_du_bras_du_spray_est_verrouillee_dans_le_lot(lot_joue):
    # Tâche 45 octies : la griffe et la préhension du lot passent par le verrou de la zone, qui
    # suit le bras du spray du lot ; à la fin, bras rangé : plus de verrou.
    _, pieces, planning, _ = lot_joue
    zone = pieces.zone
    assert pieces.griffe.griffe.verrou_spray == zone.refus_griffe
    assert pieces.scenario.prehension.verrou_spray == zone.refus_prehension
    assert zone.bras_au_repos is not None and not zone.verrouillee()
    faites = [f"{ligne.module}.{ligne.etape}" for ligne in planning.lignes]
    assert faites.count("remplissage.spray_sortir_le_bras") == 2


def test_chaque_seau_suit_l_ordre_du_cycle(lot_joue):
    mode, _, planning, _ = lot_joue
    faites = [f"{ligne.module}.{ligne.etape}" for ligne in planning.lignes]
    assert "griffe" in mode.postes_lances
    assert verifier_ordre(faites, mode.postes_lances) == []


def test_la_griffe_ne_descend_que_quand_le_seau_l_attend(lot_joue):
    """Chaque prise de la griffe (dans le fût) commence pendant une étape « verser » du
    Remplissage (le seau attend au vidage) : jamais pendant un geste de la préhension."""
    _, _, planning, _ = lot_joue
    verser = [
        (ligne.debut, ligne.fin)
        for ligne in planning.lignes
        if (ligne.module, ligne.etape) == ("remplissage", "verser")
    ]
    tete = [
        (ligne.debut, ligne.fin)
        for ligne in planning.lignes
        if ligne.module == "remplissage"
        and ligne.etape
        in (
            "prendre_le_seau",
            "poser_le_seau",
            "rendre_le_seau_du_dessus",
            "prendre_le_couvercle",
            "poser_le_couvercle",
        )
    ]
    prises = [
        ligne
        for ligne in planning.lignes
        if ligne.module == "griffe" and ligne.etape in ("prendre_une_dose", "racler")
    ]
    assert prises
    for prise in prises:
        # Le geste part (action) quand le seau attend déjà au vidage.
        assert prise.action is not None and prise.fin is not None, prise
        assert any(debut <= prise.action <= fin for debut, fin in verser), prise
        assert not any(debut < prise.fin and prise.action < fin for debut, fin in tete), prise


def test_le_carnet_garde_la_griffe(lot_joue):
    _, pieces, _, simulateur = lot_joue
    memoire = simulateur.chef.memoire("griffe")
    assert memoire["seau"] == 2
    assert memoire["versees"] == {"0": 4, "1": 4}
    # Une griffe neuve reprend là où le carnet le dit.
    autre = pieces.griffe
    autre.retrouver({"plan": memoire["plan"], "seau": 1, "versees": {"0": 4}, "interrompus": []})
    assert autre.seau == 1 and autre.versees == {0: 4}


# ---------------------------------------------------------------- les conditions, une par une


class FausseTete:
    def __init__(self, pose):
        self.pose = pose

    def position(self):
        return self.pose


class FausseRegles:
    def __init__(self, refus=None):
        self.refus = refus
        self.vus = []

    def refus_mouvement(self, depart, arrivee, contexte):
        self.vus.append((depart, arrivee))
        return self.refus


class FaussePrehension:
    def __init__(self, pose):
        self.tete = FausseTete(pose)
        self.regles = FausseRegles()
        self.occupe = False
        self.objet = None
        self.reglages = MACHINE.prehension
        self.verrou_pont = None
        self.verrou_chariot = lambda depart, arrivee: None
        self.verrou_stockage = lambda depart, arrivee: None

    def contexte(self):
        return None

    def occupee(self):
        return self.occupe


class FauxRemplissage:
    def __init__(self):
        self.au_vidage = True
        self.permis = True
        self.tourne = []
        self.griffe = None

    def seau_au_vidage(self):
        return self.au_vidage

    def versement_permis(self):
        return self.permis

    def tourner_seau(self, tourne):
        self.tourne.append(tourne)

    def brancher_griffe(self, griffe):
        self.griffe = griffe


def placer(griffe, pose):
    """Le bras de la griffe est là (lu sur le bras, comme sur la machine)."""
    griffe.griffe.bras.position = lambda: pose


@pytest.fixture
def morceaux(liste):
    with Simulateur(REGLAGES, liste, "vidange_fut") as simulateur:
        imaginaire = griffe_du_simulateur(simulateur)
        prehension = FaussePrehension(PosePrehension(x=1.5, y=0.5, z=1.1, a=0.0))
        remplissage = FauxRemplissage()
        griffe = GriffeDuSeau(
            MACHINE,
            imaginaire.bras,
            imaginaire.poste,
            prehension,
            remplissage,
            lot_de(2).seaux,
            horloge=lambda: simulateur.temps,
        )
        yield griffe, prehension, remplissage, simulateur


def test_seau_pret_et_fut_permis_seulement_quand_le_seau_attend(morceaux):
    griffe, _, remplissage, _ = morceaux
    assert remplissage.griffe is griffe.griffe
    assert not griffe.fut_permis() and not griffe.seau_pret()
    griffe.attendre(0, 1)
    assert griffe.fut_permis() and griffe.seau_pret()
    # Seau pas arrêté au vidage, ou versement pas permis (purge) : pas de dose portée.
    remplissage.au_vidage = False
    assert griffe.fut_permis() and not griffe.seau_pret()
    remplissage.au_vidage, remplissage.permis = True, False
    assert not griffe.seau_pret()
    remplissage.permis = True
    # Le seau suivant n'est pas celui de la griffe : rien.
    griffe.attendre(1, 1)
    assert not griffe.fut_permis()


def test_la_couche_versee_finit_l_etape_verser(morceaux):
    griffe, _, _, _ = morceaux
    griffe.attendre(0, 1)
    assert not griffe.couche_versee()
    griffe._couche_finie(1)
    assert griffe.couche_versee()
    assert griffe.attendue is None
    # Dernière couche : le seau fini (essuyé) compte pour toutes ses couches.
    griffe.attendre(0, 4)
    griffe.griffe.plan.couche = 4
    griffe._seau_fini(1)
    assert griffe.couche_versee() and griffe.seau == 1


def test_fut_vide_en_plein_seau_alarme_sans_inventer(morceaux):
    griffe, _, _, _ = morceaux
    griffe.griffe.plan.couche = 2
    griffe.griffe.plan.vide = True
    griffe._seau_fini(1)
    assert griffe.interrompus == {0}
    griffe.attendre(0, 2)
    assert griffe.couche_versee()
    griffe.attendre(0, 3)
    with pytest.raises(ErreurEtape, match="fût vide pendant le seau n° 1"):
        griffe.couche_versee()
    # Après « fût vide », la griffe attend un nouveau fût pour le seau suivant.
    assert griffe._apres_fut_vide() == "attendre_le_fut"
    griffe.seau = 2
    assert griffe._apres_fut_vide() is None


def test_pont_libre_et_griffe_garee(morceaux):
    griffe, prehension, _, simulateur = morceaux
    assert griffe.pont_libre()
    prehension.occupe = True
    assert not griffe.pont_libre()
    # Au départ du simulateur, la griffe est à sa place d'attente, en haut, godet fermé.
    assert garee(griffe.griffe) == griffe.garee.test()
    pose = griffe.griffe.bras.position()
    haut = pose.avec(z=MACHINE.axes["griffe_z"].course[1], b=0.0, a=0.0)
    placer(griffe, haut)
    assert griffe.garee.test()
    placer(griffe, haut.avec(z=1.0))
    assert not griffe.garee.test()
    placer(griffe, haut.avec(b=0.5))
    assert not griffe.garee.test()
    # « Partie » : le mât au-dessus du fût.
    centre_x, centre_y = MACHINE.poste_fut.centre_fut
    placer(griffe, haut.avec(x=centre_x, y=centre_y))
    assert griffe.partie()
    x, y = MACHINE.griffe.seau_remplissage
    placer(griffe, haut.avec(x=x, y=y))
    assert not griffe.partie()


def test_le_pont_partage_verifie_les_regles_de_l_autre(morceaux):
    griffe, prehension, _, _ = morceaux
    regles = griffe.griffe.regles
    assert prehension.verrou_pont is not None
    haut = MACHINE.axes["griffe_z"].course[1]
    # Griffe en haut au-dessus du seau de remplissage : la préhension qui part en y ne la gêne pas.
    x, y = MACHINE.griffe.seau_remplissage
    placer(griffe, PoseGriffe(x=x, y=y, z=haut, a=0.0, b=0.0))
    depart = PosePrehension(x=1.5, y=0.5, z=1.1, a=0.0)
    assert prehension.verrou_pont(depart, depart.avec(y=0.6)) is None
    # Rien ne bouge en x, y : pas de vérification.
    assert prehension.verrou_pont(depart, depart.avec(z=0.5)) is None
    # Griffe basse dans le fût : un pas de la préhension qui bouge le pont est refusé.
    centre_x, centre_y = MACHINE.poste_fut.centre_fut
    placer(griffe, PoseGriffe(x=centre_x, y=centre_y, z=0.8, a=0.0, b=0.0))
    assert regles.dans_le_fut(griffe.griffe.bras.position())
    refus = prehension.verrou_pont(depart, depart.avec(x=2.0))
    assert refus is not None and "traîné par le pont" in refus
    # L'inverse : un pas de la griffe qui bouge le pont fait vérifier les règles de la tête.
    prehension.regles.refus = "tête pas en haut"
    a = PoseGriffe(x=x, y=y, z=haut, a=0.0, b=0.0)
    refus = griffe.griffe.verrou_pont(a, a.avec(x=0.5))
    assert refus == "la tête de préhension, traînée par le pont : tête pas en haut"
    debut, fin = prehension.regles.vus[-1]
    assert fin.x == pytest.approx(debut.x + 0.5 - x)
    assert griffe.griffe.verrou_pont(a, a.avec(z=1.0)) is None


def test_brancher_pont_position_inconnue_refuse(morceaux):
    griffe, prehension, _, _ = morceaux

    class Perdue:
        def position(self):
            raise ErreurEtape("carte muette")

    prehension.tete = Perdue()
    brancher_pont(griffe.griffe, prehension)
    a = griffe.griffe.bras.position()
    refus = griffe.griffe.verrou_pont(a, a.avec(x=a.x + 0.1))
    assert refus is not None and "inconnue" in refus
