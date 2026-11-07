"""Le mode seaux sur la machine imaginaire (`vidange-simulateur cycle`, tâche 45).

    with Simulateur(reglages, liste, "cycle") as simulateur:
        mode, planning, problemes = jouer_cycle(simulateur)

Les pièces imaginaires (faux chariot, fausse tête, faux agitateur, fausse caméra du QR du flanc et
du micropore, stockage imaginaire) sont celles des scénarios « remplissage » et « stockage » ; le
reste (ce qui est prêt, les conditions, le lot, le carnet) est le code du programme principal
(vidange.cycle.mode_seaux). Le lot est la partie « cycle » de simulateur.yaml.

Ce qui n'est pas dans le lot simulé, et pourquoi, est dit par `mode.en_texte()` :
- le fût est déjà au poste et prêt (l'échange se joue à part : `vidange-simulateur poste_fut`) ;
- la griffe : chaque versement est une rotation du seau (étape « verser » du remplissage) ;
- les cases vides d'ORDRE_SEAU (spray, couvercle, et donc la fermeture ; lavage).
"""

from vidange.cycle.mode_seaux import Lot, ModeSeaux, PiecesRemplissage
from vidange.cycle.ordre import verifier_ordre
from vidange.reglages import CycleSimule, SeauRemplissageSimule
from vidange.remplissage.module import SeauAFaire
from vidange.simulateur.planning import Planning
from vidange.simulateur.simulateur import ErreurSimulation, Simulateur
from vidange.stockage.simulation import BOUCLE
from vidange.stockage.stockage import Stockage


class PiecesSimulees:
    """Les pièces du mode seaux sur la machine imaginaire. `vraie_machine` est faux : des réglages
    d'EXEMPLE sont permis (comme pour tout le simulateur)."""

    vraie_machine = False

    def __init__(self, simulateur: Simulateur) -> None:
        self.simulateur = simulateur

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
        return None

    def remplissage(
        self, lot: Lot, avec_micropore: bool, avec_fermeture: bool
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
        options = {} if avec_micropore else {"micropore_rentre": lambda: True}
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
        return PiecesRemplissage(
            scenario.remplissage, scenario.prehension, scenario.mycelium, scenario.plan
        )


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
    problemes = verifier_ordre(faites, mode.postes_lances) if planning.fini else []
    return mode, planning, problemes
