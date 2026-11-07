"""Le mode bocaux du programme principal (tâche 45 bis) : lot de bocaux et lavage des bocaux.

    mode = ModeBocaux(reglages, pieces, chef, mode_actuel)
    mode.etats                       # chaque poste d'ORDRE_BOCAUX : prêt, ou pas lancé et pourquoi
    mode.refus_lot()                 # None : un lot de bocaux peut partir ; sinon pourquoi
    mode.lancer_lot(lot)             # le module « entonnoir » donné au chef
    mode.refus_lavage()              # idem pour laver les bocaux et les capsules
    mode.lancer_lavage()             # le module « lavage » (lave-bocal) donné au chef
    mode.modules_a_reprendre(...)    # après une coupure : le lot de bocaux du carnet

Même méthode que le mode seaux (vidange.cycle.mode_seaux) et mêmes pièces : `PiecesMachine` au
démarrage, `PiecesSimulees` dans le simulateur (`vidange-simulateur cycle --lot bocaux`). On ne
réécrit aucun module : `module_entonnoir` et `module_lavage_bocaux` sont ceux des tâches 43
et 21 bis.

Un lot de bocaux tourne en mode « production », laver les bocaux en mode « lavage » (c'est ce que
demande `Lavage.refus_mode`). Un seul lot à la fois : pas de lot de bocaux pendant un lot de seaux.

Ce qui n'est pas lancé, et pourquoi (écran, check-list, journal) :
- le versement de la griffe dans le bocal : sa case est vide (enchaînement avec la préhension,
  tâche 23) ; sur la vraie machine un lot de bocaux ne part donc pas ;
- sur la vraie machine, la Préhension, la lecture de la photo du plafond (entonnoir sur le bocal)
  et le Lavage ne sont pas encore construits ici (voir vidange.cycle.machine) ;
- une partie de machine.yaml absente, ou en EXEMPLE sur la vraie machine.

Après une coupure, le lot est noté dans le carnet du chef après chaque étape (bocal où est
l'entonnoir, bocaux restants, bocaux versés) ; l'entonnoir garde de son côté sa place
(`entonnoir_place`, fichier). Le lot est repris à son étape, après le Go de Karulium.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from vidange.chef import Chef, ErreurChef, Module
from vidange.cycle.ordre import ORDRE_BOCAUX, Poste
from vidange.cycle.postes import (
    EtatPoste,
    etat_du_poste,
    noter_apres_chaque_etape,
    refus_lancement,
)
from vidange.entonnoir.entonnoir import Entonnoir
from vidange.entonnoir.module import module_entonnoir
from vidange.fiabilite.constats import Constat
from vidange.journal import donner_journal
from vidange.lavage.bocaux import LavageBocaux
from vidange.lavage.module import module_lavage_bocaux
from vidange.prehension.prehension import Prehension
from vidange.reglages import ObjetLaveBocalSimule, Reglages

journal = donner_journal("mode_bocaux")

ENTONNOIR = "entonnoir"
LAVAGE = "lavage"
SUJET = "mode bocaux"
QUOI_FAIRE = (
    "Rien à faire pour l'instant : ce poste sera lancé quand ce qui manque sera écrit ou réglé "
    "(voir docs/taches.md)."
)
# Les postes sans lesquels un lot de bocaux, ou laver les bocaux, ne part pas.
POSTES_DU_LOT = ("fut", "entonnoir", "versement")
POSTES_DU_LAVAGE = ("lavage_bocaux",)

PARTIES: dict[str, tuple[str, ...]] = {
    "fut": ("poste_fut",),
    "entonnoir": ("entonnoir", "prehension", "stockage"),
    "versement": ("griffe", "poste_fut"),
    "lavage_bocaux": ("lavage.lave_bocal", "prehension"),
}


@dataclass(frozen=True)
class LotBocaux:
    """Les bocaux vides à remplir d'un lot (noms du quinconce du Stockage ; le Pi choisit
    l'ordre, en serpentin)."""

    bocaux: tuple[str, ...]

    def memoire(self) -> dict[str, Any]:
        return {"bocaux": list(self.bocaux)}

    @classmethod
    def depuis(cls, memoire: Mapping[str, Any]) -> "LotBocaux":
        return cls(tuple(memoire["bocaux"]))


@dataclass
class PiecesEntonnoir:
    """Ce que les pièces construisent pour un lot de bocaux : l'entonnoir, la Préhension, et le
    versement de la griffe (case vide sur la machine ; un faux dans le simulateur)."""

    entonnoir: Entonnoir
    prehension: Prehension
    verser: Callable[[str], object] = lambda bocal: None
    versement_fini: Callable[[], bool] = lambda: True


@dataclass
class PiecesLavageBocaux:
    """Le lave-bocal, et les bocaux vides et capsules à laver (où la tête les prend)."""

    bocaux: LavageBocaux
    objets: Sequence[ObjetLaveBocalSimule]


class PiecesDesBocaux(Protocol):
    vraie_machine: bool

    def manque(self, poste: str) -> str | None: ...

    def entonnoir(self, lot: LotBocaux) -> PiecesEntonnoir: ...

    def lavage_bocaux(self) -> PiecesLavageBocaux: ...


@dataclass
class _LotEnCours:
    lot: LotBocaux
    pieces: PiecesEntonnoir


class ModeBocaux:
    def __init__(
        self,
        reglages: Reglages,
        pieces: PiecesDesBocaux,
        chef: Chef,
        mode_actuel: Callable[[], str] | None = None,
    ) -> None:
        """`mode_actuel` : le mode de la machine (ModeMachine.actuel). None : pas vérifié
        (simulateur)."""
        self.reglages = reglages
        self.pieces = pieces
        self.chef = chef
        self.mode_actuel = mode_actuel
        self.etats: dict[str, EtatPoste] = {}
        for poste in ORDRE_BOCAUX:
            self.etats[poste.nom] = etat_du_poste(poste, reglages, pieces, PARTIES, self.etats)
        self.en_cours: _LotEnCours | None = None
        for etat in self.etats.values():
            journal.info("Mode bocaux, %s : %s", etat.poste.nom, etat.en_texte())

    # ------------------------------------------------------------ ce qu'on dit

    def pret(self, nom: str) -> bool:
        return self.etats[nom].pret

    @property
    def postes_lances(self) -> list[str]:
        return [nom for nom, etat in self.etats.items() if etat.pret]

    def _manquant(self, noms: Sequence[str], lavage: bool = False) -> EtatPoste | None:
        """Le premier de ces postes qui empêche de partir : le cœur toujours ; sur la vraie
        machine, aussi un poste obligatoire (le simulateur saute ceux qui manquent, et le dit)."""
        for nom in noms:
            etat = self.etats[nom]
            poste: Poste = etat.poste
            if etat.pret:
                continue
            if lavage or poste.coeur or (poste.obligatoire and self.pieces.vraie_machine):
                return etat
        return None

    def refus_lot(self) -> str | None:
        """None : un lot de bocaux peut partir ; sinon pourquoi pas."""
        etat = self._manquant(POSTES_DU_LOT)
        return None if etat is None else f"« {etat.poste.nom} » pas lancé : {etat.raison}"

    def refus_lavage(self) -> str | None:
        """None : laver les bocaux peut partir ; sinon pourquoi pas."""
        etat = self._manquant(POSTES_DU_LAVAGE, lavage=True)
        return None if etat is None else f"« {etat.poste.nom} » pas lancé : {etat.raison}"

    def constats(self) -> list[Constat]:
        """Pour la check-list : chaque poste qui manque (attention), le lot et le lavage."""
        constats = [
            Constat(f"{SUJET}, {etat.poste.nom}", "attention", etat.en_texte(), QUOI_FAIRE)
            for etat in self.etats.values()
            if not etat.pret
        ]
        refus = self.refus_lot()
        if refus is None:
            constats.append(Constat(SUJET, "ok", "un lot de bocaux peut partir"))
        else:
            # Jamais bloquant : la production de seaux n'en dépend pas.
            constats.append(
                Constat(SUJET, "attention", f"aucun lot de bocaux ne peut partir : {refus}")
            )
        refus = self.refus_lavage()
        if refus is None:
            constats.append(Constat(f"{SUJET}, lavage", "ok", "les bocaux peuvent être lavés"))
        else:
            constats.append(
                Constat(f"{SUJET}, lavage", "attention", f"lavage des bocaux impossible : {refus}")
            )
        return constats

    def texte_ecran(self) -> tuple[str, str]:
        """Pour l'écran de l'armoire, quand aucun cycle ne tourne : quel poste manque (ligne
        courte) et pourquoi (ligne d'information)."""
        etat = self._manquant(POSTES_DU_LOT)
        if etat is None:
            return "Lot de bocaux : prêt", ""
        return f"Lot de bocaux : {etat.poste.nom.replace('_', ' ')} pas prêt", etat.raison

    def en_texte(self) -> str:
        lignes = ["Mode bocaux (entonnoir, versement, lavage) :"]
        for etat in self.etats.values():
            lignes.append(f"  {etat.poste.nom:<13} {etat.poste.texte} : {etat.en_texte()}")
        refus = self.refus_lot()
        lignes.append("  lot : " + ("peut partir" if refus is None else f"impossible ({refus})"))
        refus = self.refus_lavage()
        lignes.append("  lavage : " + ("peut partir" if refus is None else f"impossible ({refus})"))
        return "\n".join(lignes)

    # ------------------------------------------------------------ le lot de bocaux

    def modules_du_lot(
        self, lot: LotBocaux, memoire: Mapping[str, Any] | None = None
    ) -> list[Module]:
        """Le module « entonnoir » du chef pour ce lot. `memoire` : celle du carnet, après une
        coupure (bocal où est l'entonnoir, bocaux restants et versés)."""
        refus = self.refus_lot()
        if refus is not None:
            raise ErreurChef(f"lot de bocaux impossible : {refus}")
        pieces = self.pieces.entonnoir(lot)
        module = module_entonnoir(
            pieces.entonnoir,
            pieces.prehension,
            list(lot.bocaux),
            verser=pieces.verser,
            versement_fini=pieces.versement_fini,
            # Le venturi de la tête prend l'entonnoir : attente de la mise en pression (tâche 42).
            air=self.chef.condition_permission("air"),
        )
        if memoire is not None:
            self._retrouver(pieces.entonnoir, memoire)
        en_cours = _LotEnCours(lot, pieces)
        self.en_cours = en_cours
        return [noter_apres_chaque_etape(module, self._noter)]

    def lancer_lot(self, lot: LotBocaux) -> list[str]:
        """Donne le module du lot au chef (règle 6 : un lot est proposé puis lancé après le Go
        de Karulium : c'est à celui qui appelle de l'avoir eu)."""
        refus = refus_lancement(self.chef, self.mode_actuel, "production", "lot de bocaux refusé")
        if refus is not None:
            raise ErreurChef(refus)
        modules = self.modules_du_lot(lot)
        for module in modules:
            self.chef.lancer(module)
        self._noter()
        journal.info("Lot de %d bocaux lancé", len(lot.bocaux))
        return [module.nom for module in modules]

    def modules_a_reprendre(self, etat_carnet: Mapping[str, Any] | None) -> list[Module]:
        """Après une coupure : le module du lot de bocaux noté dans le carnet (vide s'il n'y en a
        pas). Un lot noté mais impossible maintenant n'est pas reconstruit : le chef dira alors
        que le carnet ne correspond pas au programme (check-list : bloquant)."""
        if not etat_carnet:
            return []
        for note in etat_carnet.get("modules", []):
            if note.get("module") != ENTONNOIR or note.get("statut") not in ("en_cours", "alarme"):
                continue
            memoire = note.get("memoire") or {}
            if "lot" not in memoire:
                journal.error("Carnet : lot de bocaux pas noté, il ne peut pas être repris.")
                return []
            refus = self.refus_lot()
            if refus is not None:
                journal.error("Carnet : lot de bocaux, mais lot impossible maintenant : %s", refus)
                return []
            lot = LotBocaux.depuis(memoire["lot"])
            journal.warning(
                "Reprise du lot de %d bocaux : entonnoir sur %s, %d déjà versés",
                len(lot.bocaux),
                memoire.get("prochain"),
                len(memoire.get("verses", [])),
            )
            return self.modules_du_lot(lot, memoire)
        return []

    @staticmethod
    def _retrouver(entonnoir: Entonnoir, memoire: Mapping[str, Any]) -> None:
        """Remet le lot là où le carnet l'a laissé (`demarrer_lot` l'avait remis au début)."""
        entonnoir.restants = list(memoire.get("restants", []))
        entonnoir.prochain = memoire.get("prochain")
        centre = memoire.get("centre")
        entonnoir.centre = None if centre is None else (float(centre[0]), float(centre[1]))
        entonnoir.verses = set(memoire.get("verses", []))
        entonnoir.suspects = list(memoire.get("suspects", []))

    def _noter(self) -> None:
        en_cours = self.en_cours
        if en_cours is None:
            return
        entonnoir = en_cours.pieces.entonnoir
        centre = entonnoir.centre
        try:
            self.chef.memoriser(
                ENTONNOIR,
                lot=en_cours.lot.memoire(),
                prochain=entonnoir.prochain,
                restants=list(entonnoir.restants),
                centre=None if centre is None else list(centre),
                verses=sorted(entonnoir.verses),
                suspects=list(entonnoir.suspects),
            )
        except ErreurChef as erreur:
            journal.error("Lot de bocaux pas noté dans le carnet : %s", erreur)

    # ------------------------------------------------------------ laver les bocaux

    def modules_lavage(self) -> list[Module]:
        """Le module « lavage » du lave-bocal (tâche 21 bis) pour les bocaux et capsules à laver."""
        refus = self.refus_lavage()
        if refus is not None:
            raise ErreurChef(f"lavage des bocaux impossible : {refus}")
        pieces = self.pieces.lavage_bocaux()
        return [module_lavage_bocaux(pieces.bocaux, pieces.objets)]

    def lancer_lavage(self) -> list[str]:
        """Donne le module du lavage des bocaux au chef (mode « lavage », après le Go)."""
        refus = refus_lancement(self.chef, self.mode_actuel, "lavage", "lavage des bocaux refusé")
        if refus is not None:
            raise ErreurChef(refus)
        modules = self.modules_lavage()
        for module in modules:
            self.chef.lancer(module)
        journal.info("Lavage des bocaux lancé")
        return [module.nom for module in modules]
