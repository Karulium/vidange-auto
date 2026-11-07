"""Le mode seaux sur la machine imaginaire (`vidange-simulateur cycle`, tâche 45).

    with Simulateur(reglages, liste, "cycle") as simulateur:
        mode, planning, problemes = jouer_cycle(simulateur)

Les pièces imaginaires (faux chariot, fausse tête, faux agitateur, fausse caméra du QR du flanc et
du micropore, stockage imaginaire, fausse carte n° 5 du spray) sont celles des scénarios
« remplissage », « stockage » et du spray ; le reste (ce qui est prêt, les conditions, le lot, le
carnet) est le code du programme principal (vidange.cycle.mode_seaux). Le lot est la partie
« cycle » de simulateur.yaml.

Ce qui n'est pas dans le lot simulé, et pourquoi, est dit par `mode.en_texte()` :
- le fût est déjà au poste et prêt (l'échange se joue à part : `vidange-simulateur poste_fut`) ;
- la griffe : chaque versement est une rotation du seau (étape « verser » du remplissage), et
  elle est vue « partie du poste » dès que le seau vide y arrive (le bras du spray peut sortir) ;
- les cases vides d'ORDRE_SEAU (griffe, lavage).
Le couvercle (tâche 41 bis) est pris sur une pile imaginaire (simulateur.yaml → cycle → couvercles)
par la vraie Préhension simulée, posé sur le seau plein, pesé par la fausse balance, puis clipsé
par la vraie fermeture.
La lecture du QR du flanc est une fausse caméra, pour que le lot reste rapide ; la vraie
(vidange.vision.inspection, tâche 40 ter) est essayée sur des images fabriquées par
tests/test_inspection.py, branchée au même Remplissage.

Tâche 45 bis, même méthode (`vidange-simulateur cycle --lot bocaux|lavage_bocaux|nuit|tout`) :
- lot de bocaux (`jouer_bocaux`) : le vrai `module_entonnoir` sur la Préhension simulée, un faux
  entonnoir qui répond ce que le vrai ferait, la fausse photo du plafond ; chaque versement de la
  griffe dure `entonnoir → verse_s` (la griffe est une case vide) ;
- lavage des bocaux (`jouer_lavage_bocaux`) : le vrai `module_lavage_bocaux` et le lave-bocal
  imaginaire ;
- nuit UV-ozone (`jouer_nuit`) : le vrai Nettoyage (poste « nuit » du programme principal branché
  à lui), son faux store et sa fausse enceinte ; Karulium ferme le store et lance la nuit (Go).
"""

from typing import TYPE_CHECKING

from vidange.bocal_neuf.simulation import MondeBocalNeuf, bocal_neuf_du_simulateur
from vidange.couvercle.simulation import MondeCouvercle, couvercle_du_simulateur
from vidange.cycle.mode_bocaux import (
    LotBocaux,
    ModeBocaux,
    PiecesEntonnoir,
    PiecesLavageBocaux,
)
from vidange.cycle.mode_nuit import ModeNuit
from vidange.cycle.mode_seaux import Lot, ModeSeaux, PiecesRemplissage
from vidange.cycle.ordre import (
    DEBUT_DU_LAVAGE_BOCAUX,
    DEBUT_DU_LOT_BOCAUX,
    ORDRE_BOCAUX,
    Poste,
    verifier_ordre,
)
from vidange.entonnoir.simulation import entonnoir_du_simulateur
from vidange.lavage.simulation import bocaux_du_simulateur
from vidange.nettoyage.nettoyage import GENERATEUR, OZONE_DEDANS, OZONE_DEHORS
from vidange.nettoyage.nettoyage import LAMPE_UV as LAMPE
from vidange.nettoyage.simulation import module_nuit, nettoyage_du_simulateur
from vidange.reglages import CycleSimule, SeauRemplissageSimule
from vidange.remplissage.module import SeauAFaire
from vidange.remplissage.remplissage import Remplissage
from vidange.simulateur.planning import Planning
from vidange.simulateur.simulateur import ErreurSimulation, Simulateur
from vidange.spray.spray import Spray
from vidange.stockage.simulation import BOUCLE
from vidange.stockage.stockage import Stockage

if TYPE_CHECKING:
    from vidange.remplissage.simulation import ScenarioRemplissage

# Postes joués en faux par le simulateur, vérifiés dans le planning comme les postes lancés : la
# griffe (chaque versement est une rotation du seau, étapes « ramener_au_vidage » et « verser »).
JOUES_EN_FAUX = ("griffe",)
# Le lot de bocaux : le versement de la griffe est joué en faux (case vide), il est dans les étapes
# de l'entonnoir (« entonnoir.verser »).
JOUES_EN_FAUX_BOCAUX = ("versement",)
# Les gestes de Karulium et les phases de la nuit du simulateur (module_nuit), dans l'ordre.
ORDRE_DE_LA_NUIT = (
    Poste(
        "nuit",
        "Nuit UV-ozone : lancée (Go), génération, contact, retour sous le seuil",
        etapes=(
            "nettoyage_nuit.lancer_la_nuit",
            "nettoyage_nuit.generation",
            "nettoyage_nuit.contact",
            "nettoyage_nuit.retour",
        ),
    ),
)
DEBUT_DE_LA_NUIT = "nettoyage_nuit.lancer_la_nuit"


class PiecesSimulees:
    """Les pièces du mode seaux sur la machine imaginaire. `vraie_machine` est faux : des réglages
    d'EXEMPLE sont permis (comme pour tout le simulateur)."""

    vraie_machine = False
    # Le Stockage imaginaire est construit avec chaque lot : la taille du lot est contrôlée là
    # (ModeSeaux.modules_du_lot), pas avant.
    stockage = None

    def __init__(self, simulateur: Simulateur) -> None:
        self.simulateur = simulateur
        # Les dernières pièces construites (essais : regarder le micropore, le spray).
        self.scenario: ScenarioRemplissage | None = None
        self.spray: Spray | None = None
        self.monde_couvercle: MondeCouvercle | None = None
        self.monde_bocal_neuf: MondeBocalNeuf | None = None

    def manque(self, poste: str) -> str | None:
        from vidange.fermeture.simulation import fermeture_possible
        from vidange.micropore.simulation import micropore_possible

        reglages = self.simulateur.reglages
        if poste == "fut":
            return (
                "le fût du lot simulé est déjà au poste et prêt (échange joué à part : "
                "vidange-simulateur poste_fut)"
            )
        if poste == "seau_vide" and (
            reglages.simulateur.remplissage is None or reglages.simulateur.mycelium is None
        ):
            return "simulateur.yaml n'a pas de partie « remplissage » (ou « mycelium »)"
        if poste == "stockage" and BOUCLE not in self.simulateur.materiel.branchements:
            return f"pas de signal « {BOUCLE} » dans docs/entrees-sorties.yaml"
        if poste == "micropore" and not micropore_possible(self.simulateur):
            return "simulateur.yaml ou pesees.yaml (i2c) n'a pas de micropore"
        if poste == "fermeture" and not fermeture_possible(self.simulateur):
            return "simulateur.yaml ou pesees.yaml (i2c) n'a pas de fermeture"
        cycle = reglages.simulateur.cycle
        if poste == "couvercle" and (cycle is None or not cycle.couvercles):
            return "simulateur.yaml, cycle : pas de pile de couvercles (couvercles)"
        if poste == "entonnoir" and (
            reglages.simulateur.entonnoir is None or reglages.machine.entonnoir is None
        ):
            return "simulateur.yaml ou machine.yaml n'a pas de partie « entonnoir »"
        lavage = reglages.simulateur.lavage
        if poste == "lavage_bocaux" and (lavage is None or not lavage.bocaux):
            return "simulateur.yaml, lavage : pas de bocaux à laver (bocaux)"
        if poste in ("enceinte", "ozone", "purge") and (
            reglages.simulateur.nettoyage is None or reglages.machine.nettoyage is None
        ):
            return "simulateur.yaml ou machine.yaml n'a pas de partie « nettoyage »"
        if poste == "ozone":
            for signal in (OZONE_DEDANS, OZONE_DEHORS, GENERATEUR, LAMPE):
                if signal not in self.simulateur.materiel.branchements:
                    return f"pas de signal « {signal} » dans docs/entrees-sorties.yaml"
        spray = reglages.machine.spray
        if poste == "spray" and (
            spray is None or spray.signal not in self.simulateur.fabrique.branchements
        ):
            return "pas de carte du spray dans docs/entrees-sorties.yaml"
        return None

    def remplissage(
        self,
        lot: Lot,
        avec_micropore: bool,
        avec_fermeture: bool,
        avec_spray: bool,
        avec_couvercle: bool,
    ) -> PiecesRemplissage:
        from vidange.remplissage.simulation import remplissage_du_simulateur

        simulateur = self.simulateur
        cycle = _cycle(simulateur)
        doubles = {lot.seaux[n - 1].seau for n in cycle.prises_doubles if n <= len(lot.seaux)}
        seaux = [
            SeauRemplissageSimule(
                seau=seau.seau,
                format=seau.format,
                variete=seau.variete,
                prise_double=seau.seau in doubles,
                anse_deg=cycle.anse_deg,
            )
            for seau in lot.seaux
        ]
        options: dict[str, object] = {} if avec_micropore else {"micropore_rentre": lambda: True}
        spray: Spray | None = None
        if avec_spray:
            # Règle 6 : le chariot reste immobile tant que le bras n'est pas vu rangé.
            options["bras_spray_sorti"] = lambda: spray is not None and spray.bras_spray_sorti()
        scenario = remplissage_du_simulateur(
            simulateur, seaux_simules=seaux, avec_fermeture=avec_fermeture, **options
        )
        materiel = simulateur.materiel
        stockage = Stockage(
            simulateur.reglages.machine, boucle_fermee=lambda: materiel.lire(BOUCLE)
        )
        for nom, pile in cycle.piles.items():
            stockage.charger_pile(nom, pile.format, pile.nombre)
        for file, nombre in cycle.files_pleines.items():
            stockage.inventaire.changer_file(file, nombre)
        scenario.plan.magasin = stockage
        if avec_spray:
            spray = self._spray(scenario.remplissage)
        couvercle = None
        if avec_couvercle:
            couvercle, self.monde_couvercle = couvercle_du_simulateur(
                simulateur, scenario, stockage, cycle.couvercles, cycle.pas_couvercles_m
            )
        if cycle.bocal_neuf is not None and reglages_machine_a_bocal_neuf(simulateur):
            # Le bocal neuf de semence est mis par la vraie Préhension simulée (tâche 19 quater).
            _, self.monde_bocal_neuf = bocal_neuf_du_simulateur(simulateur, scenario, stockage)
        self.scenario = scenario
        return PiecesRemplissage(
            scenario.remplissage,
            scenario.prehension,
            scenario.mycelium,
            scenario.plan,
            spray=spray,
            # Pas de griffe sur la machine imaginaire : elle n'est jamais au poste.
            griffe_partie=lambda: True,
            couvercle=couvercle,
        )

    def entonnoir(self, lot: LotBocaux) -> PiecesEntonnoir:
        """L'entonnoir imaginaire sur la Préhension simulée ; le versement de la griffe est un
        faux (il dure `verse_s`)."""
        scenario = entonnoir_du_simulateur(self.simulateur, avec_module=False)
        return PiecesEntonnoir(
            scenario.entonnoir,
            scenario.prehension,
            verser=scenario.monde.verser,
            versement_fini=scenario.monde.versement_fini,
        )

    def lavage_bocaux(self) -> PiecesLavageBocaux:
        lavage = self.simulateur.reglages.simulateur.lavage
        assert lavage is not None
        return PiecesLavageBocaux(bocaux_du_simulateur(self.simulateur), lavage.bocaux)

    def _spray(self, remplissage: Remplissage) -> Spray:
        """Le vrai Spray sur la fausse carte n° 5 du simulateur, branché au chariot (règle 6,
        rotation du seau pendant la dose), lu en fond comme sur la machine."""
        simulateur = self.simulateur
        spray = Spray(
            simulateur.reglages.machine,
            simulateur.materiel,
            horloge=lambda: simulateur.temps,
            refus_chariot=remplissage.refus_bras_spray,
            # Porte de la boîte du spray fermée (machine imaginaire).
            porte_ouverte=lambda: False,
            tourner_seau=remplissage.tourner_pour_spray,
            permission=simulateur.chef.permission,
        )
        simulateur.ajouter_fond(spray.observer)
        self.spray = spray
        return spray


def reglages_machine_a_bocal_neuf(simulateur: Simulateur) -> bool:
    return simulateur.reglages.machine.bocal_neuf is not None


def _cycle(simulateur: Simulateur) -> CycleSimule:
    cycle = simulateur.reglages.simulateur.cycle
    if cycle is None:
        raise ErreurSimulation("simulateur.yaml n'a pas de partie « cycle »")
    formats = (
        simulateur.reglages.machine.griffe.formats if simulateur.reglages.machine.griffe else {}
    )
    if cycle.format not in formats:
        raise ErreurSimulation(
            f"simulateur.yaml, cycle : format « {cycle.format} » absent de machine.yaml "
            "(griffe → formats)"
        )
    return cycle


def lot_du_simulateur(simulateur: Simulateur) -> Lot:
    """Le lot de la partie « cycle » de simulateur.yaml."""
    cycle = _cycle(simulateur)
    seaux = tuple(
        SeauAFaire(f"{cycle.prefixe}{numero:0{cycle.chiffres}d}", cycle.format, cycle.variete)
        for numero in range(cycle.premier, cycle.premier + cycle.seaux)
    )
    return Lot(cycle.format, seaux)


def jouer_cycle(simulateur: Simulateur) -> tuple[ModeSeaux, Planning, list[str]]:
    """Prépare le mode seaux (même code que la machine), joue le lot, puis vérifie que chaque seau
    a suivi ORDRE_SEAU. Rend le mode, le planning et les écarts à l'ordre (vide : aucun)."""
    mode = ModeSeaux(simulateur.reglages, PiecesSimulees(simulateur), simulateur.chef)
    refus = mode.refus_lot()
    if refus is not None:
        raise ErreurSimulation(f"lot de seaux impossible : {refus}")
    planning = simulateur.jouer(mode.modules_du_lot(lot_du_simulateur(simulateur)))
    faites = [f"{ligne.module}.{ligne.etape}" for ligne in planning.lignes]
    verifies = [*mode.postes_lances, *JOUES_EN_FAUX]
    problemes = verifier_ordre(faites, verifies) if planning.fini else []
    return mode, planning, problemes


def lot_bocaux_du_simulateur(simulateur: Simulateur) -> LotBocaux:
    """Le lot de bocaux de la partie « entonnoir » de simulateur.yaml."""
    simule = simulateur.reglages.simulateur.entonnoir
    if simule is None:
        raise ErreurSimulation("simulateur.yaml n'a pas de partie « entonnoir »")
    return LotBocaux(tuple(simule.bocaux))


def jouer_bocaux(simulateur: Simulateur) -> tuple[ModeBocaux, Planning, list[str]]:
    """Prépare le mode bocaux (même code que la machine), joue le lot, puis vérifie l'ordre de
    l'entonnoir (ORDRE_BOCAUX). Rend le mode, le planning et les écarts à l'ordre."""
    mode = ModeBocaux(simulateur.reglages, PiecesSimulees(simulateur), simulateur.chef)
    refus = mode.refus_lot()
    if refus is not None:
        raise ErreurSimulation(f"lot de bocaux impossible : {refus}")
    planning = simulateur.jouer(mode.modules_du_lot(lot_bocaux_du_simulateur(simulateur)))
    faites = [f"{ligne.module}.{ligne.etape}" for ligne in planning.lignes]
    verifies = [nom for nom in mode.postes_lances if nom != "lavage_bocaux"]
    problemes = (
        verifier_ordre(
            faites,
            [*verifies, *JOUES_EN_FAUX_BOCAUX],
            ORDRE_BOCAUX,
            DEBUT_DU_LOT_BOCAUX,
            "lot de bocaux",
        )
        if planning.fini
        else []
    )
    return mode, planning, problemes


def jouer_lavage_bocaux(simulateur: Simulateur) -> tuple[ModeBocaux, Planning, list[str]]:
    """Prépare le mode bocaux, joue le lavage des bocaux et des capsules au lave-bocal, puis
    vérifie l'ordre de la série."""
    mode = ModeBocaux(simulateur.reglages, PiecesSimulees(simulateur), simulateur.chef)
    refus = mode.refus_lavage()
    if refus is not None:
        raise ErreurSimulation(f"lavage des bocaux impossible : {refus}")
    planning = simulateur.jouer(mode.modules_lavage())
    faites = [f"{ligne.module}.{ligne.etape}" for ligne in planning.lignes]
    problemes = (
        verifier_ordre(
            faites, ["lavage_bocaux"], ORDRE_BOCAUX, DEBUT_DU_LAVAGE_BOCAUX, "série de lavage"
        )
        if planning.fini
        else []
    )
    return mode, planning, problemes


def jouer_nuit(simulateur: Simulateur) -> tuple[ModeNuit, Planning, list[str]]:
    """Prépare la nuit UV-ozone (le vrai Nettoyage, le poste « nuit » branché à lui, même code que
    la machine), la joue sur la fausse enceinte, puis vérifie qu'elle a suivi ses phases et que le
    générateur d'ozone est coupé à la fin."""
    simulation = nettoyage_du_simulateur(simulateur)
    mode = ModeNuit(simulateur.reglages, PiecesSimulees(simulateur), simulation.nettoyage)
    refus = mode.refus_poste()
    if refus is not None:
        raise ErreurSimulation(f"nuit UV-ozone impossible : {refus}")
    planning = simulateur.jouer([module_nuit(simulation)])
    faites = [f"{ligne.module}.{ligne.etape}" for ligne in planning.lignes]
    problemes = (
        verifier_ordre(faites, ["nuit"], ORDRE_DE_LA_NUIT, DEBUT_DE_LA_NUIT, "nuit")
        if planning.fini
        else []
    )
    if planning.fini and simulation.nettoyage.commande(GENERATEUR):
        problemes.append("le générateur d'ozone est resté en marche à la fin de la nuit")
    return mode, planning, problemes
