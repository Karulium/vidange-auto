"""Le mode seaux du programme principal (tâche 45) : quels modules sont prêts, le lot, la reprise.

    mode = ModeSeaux(reglages, pieces, chef)      # pieces : vrai matériel ou simulateur
    mode.etats                                    # chaque poste d'ORDRE_SEAU : prêt, ou pas
    mode.refus_lot()                              # None : un lot peut partir ; sinon pourquoi
    mode.lancer_lot(lot)                          # les modules du lot donnés au chef
    mode.modules_a_reprendre(carnet.lire())       # après une coupure : le lot du carnet

Le MÊME code sert au démarrage de la vraie machine (vidange.demarrage, pièces de
vidange.cycle.machine) et au simulateur (`vidange-simulateur cycle`, pièces de
vidange.cycle.simulation). Seules les pièces changent : ce qui touche le matériel.

Un poste n'est pas lancé, et la check-list et l'écran disent pourquoi, quand :
- son geste n'est pas encore écrit (`case_vide` d'ORDRE_SEAU : griffe, lavage...) ;
- machine.yaml n'a pas sa partie ;
- sur la vraie machine, sa partie de machine.yaml est en EXEMPLE (`exemple: true`) ;
- les pièces disent qu'il manque quelque chose (matériel, vision pas écrite : tâche 40 ter...) ;
- un poste dont il a besoin n'est pas prêt.
Jamais de geste inventé : un poste pas prêt est sauté (il n'est pas remplacé par un faux geste).

Le lot (les seaux vides à remplir, d'un format) est donné au chef sous deux modules :
« remplissage » (avec la préhension, le stockage, le micropore et la fermeture branchés) et
« mycelium ». Où en est le lot (seau en cours, couche, seau sur le plateau) est noté dans le carnet
du chef après chaque étape : après une coupure, le lot est reconstruit et repris à son étape, après
le Go de Karulium.

Les conditions entre modules sont branchées ici, comme le disent docs/decisions.md et les
tâches : air comprimé (`chef.condition_permission("air")`, avant de prendre un seau par le
venturi), purge et store (permissions et conditions générales du chef, déjà données aux pièces),
préhension dégagée et bras rangé (Fermeture, par le Remplissage). Rien de cela ne protège
personne : la sécurité est câblée.
"""

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import TYPE_CHECKING, Any, Protocol

from vidange.chef import Chef, ErreurChef, Etape, Module
from vidange.cycle.ordre import ORDRE_SEAU, SUR_LE_CHARIOT, Poste
from vidange.fiabilite.constats import Constat
from vidange.journal import donner_journal
from vidange.mycelium.module import module_mycelium
from vidange.mycelium.mycelium import Mycelium
from vidange.prehension.prehension import Prehension
from vidange.reglages import Reglages
from vidange.remplissage.module import Plan, SeauAFaire, module_remplissage
from vidange.remplissage.remplissage import Remplissage, SeauPlateau

if TYPE_CHECKING:
    from vidange.couvercle.couvercle import Couvercle
    from vidange.spray.spray import Spray

journal = donner_journal("mode_seaux")

REMPLISSAGE = "remplissage"
MYCELIUM = "mycelium"
SUJET = "mode seaux"
QUOI_FAIRE = (
    "Rien à faire pour l'instant : ce poste sera lancé quand ce qui manque sera écrit ou réglé "
    "(voir docs/taches.md)."
)
QUOI_FAIRE_EXEMPLE = (
    "Régler cette partie de machine.yaml aux essais (procédure pi/systeme/essai-*.md), puis passer "
    "« exemple » à false."
)

# Les parties de machine.yaml dont chaque poste a besoin.
PARTIES: dict[str, tuple[str, ...]] = {
    "fut": ("poste_fut",),
    "seau_vide": ("remplissage", "prehension", "griffe"),
    # Le QR du flanc est lu par la caméra du micropore (cam_inspection, fil Guidage caméra) : sa
    # lecture manque sur la machine (tâche 40 ter) ; dans le simulateur, une fausse caméra.
    "qr_du_flanc": ("remplissage",),
    "au_poste": ("remplissage",),
    "griffe": ("griffe", "poste_fut"),
    "mycelium": ("mycelium", "porte_bocal"),
    "spray": ("spray",),
    "micropore": ("micropore",),
    "couvercle": ("couvercle", "prehension", "stockage", "fermeture", "remplissage"),
    "fermeture": ("fermeture",),
    "stockage": ("stockage",),
    "lavage": ("lavage",),
}


@dataclass(frozen=True)
class Lot:
    """Les seaux vides d'un lot, tous du même format (règle 3 de la caméra du plafond : remplir
    les seaux et ajouter le mycélium). `fin_de_lot` : le tiroir est vidé à la fin."""

    format: str
    seaux: tuple[SeauAFaire, ...]
    fin_de_lot: bool = True

    def memoire(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "fin_de_lot": self.fin_de_lot,
            "seaux": [asdict(seau) for seau in self.seaux],
        }

    @classmethod
    def depuis(cls, memoire: Mapping[str, Any]) -> "Lot":
        seaux = tuple(SeauAFaire(**seau) for seau in memoire["seaux"])
        return cls(memoire["format"], seaux, bool(memoire.get("fin_de_lot", True)))


@dataclass
class PiecesRemplissage:
    """Ce que les pièces construisent pour un lot : le chariot, la tête, le mycélium et le plan
    (avec le Stockage dans `plan.magasin`) ; le spray (None : pas de spray), branché au chariot,
    ce qui dit que la griffe est partie du poste chercher sa 1re prise, et le couvercle (None :
    pas de pose du couvercle)."""

    remplissage: Remplissage
    prehension: Prehension
    mycelium: Mycelium
    plan: Plan
    spray: "Spray | None" = None
    griffe_partie: Callable[[], bool] = lambda: False
    couvercle: "Couvercle | None" = None


class Pieces(Protocol):
    """Ce qui dépend du matériel : vraies cartes (démarrage) ou machine imaginaire (simulateur)."""

    # Vrai matériel : des réglages d'EXEMPLE y sont interdits.
    vraie_machine: bool

    def manque(self, poste: str) -> str | None:
        """Ce qui manque pour ce poste ici (matériel, vision pas écrite...), ou None."""
        ...

    def remplissage(
        self,
        lot: Lot,
        avec_micropore: bool,
        avec_fermeture: bool,
        avec_spray: bool,
        avec_couvercle: bool,
    ) -> PiecesRemplissage: ...


@dataclass(frozen=True)
class EtatPoste:
    poste: Poste
    pret: bool
    # Pourquoi il n'est pas lancé (vide s'il est prêt).
    raison: str = ""

    def en_texte(self) -> str:
        return "prêt" if self.pret else f"pas lancé : {self.raison}"


@dataclass
class _LotEnCours:
    lot: Lot
    pieces: PiecesRemplissage
    modules: list[Module] = field(default_factory=list)


class ModeSeaux:
    def __init__(self, reglages: Reglages, pieces: Pieces, chef: Chef) -> None:
        self.reglages = reglages
        self.pieces = pieces
        self.chef = chef
        self.etats: dict[str, EtatPoste] = {}
        for poste in ORDRE_SEAU:
            self.etats[poste.nom] = self._verifier(poste)
        # Le cœur (seau vide, mycélium, stockage) va ensemble : sans l'un, pas les autres.
        coeur = [p.nom for p in ORDRE_SEAU if p.coeur]
        absents = [nom for nom in coeur if not self.etats[nom].pret]
        for nom in coeur:
            if self.etats[nom].pret and absents:
                raison = f"attend « {absents[0]} » (pas prêt)"
                self.etats[nom] = EtatPoste(self.etats[nom].poste, False, raison)
        # Un couvercle posé et pas clipsé ne tient pas : pas de couvercle sans fermeture.
        for poste in ORDRE_SEAU:
            for besoin in poste.besoin_ensuite:
                if self.etats[poste.nom].pret and not self.etats[besoin].pret:
                    raison = f"attend « {besoin} » (pas prêt)"
                    self.etats[poste.nom] = EtatPoste(poste, False, raison)
        # Un poste qui sert le seau du chariot n'a pas de sens sans le cœur.
        for nom in SUR_LE_CHARIOT:
            if self.etats[nom].pret and absents:
                self.etats[nom] = EtatPoste(self.etats[nom].poste, False, "pas de lot possible")
        self.en_cours: _LotEnCours | None = None
        for etat in self.etats.values():
            journal.info("Mode seaux, %s : %s", etat.poste.nom, etat.en_texte())

    def _verifier(self, poste: Poste) -> EtatPoste:
        if poste.case_vide is not None:
            return EtatPoste(poste, False, f"geste pas encore écrit : {poste.case_vide}")
        machine = self.reglages.machine
        for partie in PARTIES.get(poste.nom, ()):
            if getattr(machine, partie) is None:
                return EtatPoste(poste, False, f"machine.yaml n'a pas de partie « {partie} »")
        if self.pieces.vraie_machine:
            exemples = [
                partie
                for partie in PARTIES.get(poste.nom, ())
                if getattr(getattr(machine, partie), "exemple", False)
            ]
            if machine.exemple or exemples:
                ou = ", ".join(exemples) if exemples else "le haut du fichier"
                return EtatPoste(
                    poste,
                    False,
                    f"valeurs d'EXEMPLE dans machine.yaml ({ou}) : interdit sur la vraie machine",
                )
        manque = self.pieces.manque(poste.nom)
        if manque is not None:
            return EtatPoste(poste, False, manque)
        for besoin in poste.besoin:
            if not self.etats[besoin].pret:
                return EtatPoste(poste, False, f"attend « {besoin} » (pas prêt)")
        return EtatPoste(poste, True)

    # ------------------------------------------------------------ ce qu'on dit

    def pret(self, nom: str) -> bool:
        return self.etats[nom].pret

    @property
    def postes_lances(self) -> list[str]:
        return [nom for nom, etat in self.etats.items() if etat.pret]

    def manquant(self) -> EtatPoste | None:
        """Le premier poste qui empêche un lot de partir, ou None. Sans le cœur, jamais de lot ;
        sur la vraie machine, pas sans un poste obligatoire (le simulateur saute ceux qui
        manquent, et le dit)."""
        for etat in self.etats.values():
            poste = etat.poste
            if etat.pret or not (poste.coeur or (poste.obligatoire and self.pieces.vraie_machine)):
                continue
            return etat
        return None

    def refus_lot(self) -> str | None:
        """None : un lot peut partir ; sinon pourquoi pas."""
        etat = self.manquant()
        return None if etat is None else f"« {etat.poste.nom} » pas lancé : {etat.raison}"

    def constats(self) -> list[Constat]:
        """Pour la check-list : chaque poste qui manque (attention), et le lot (bloquant)."""
        constats = [
            Constat(f"{SUJET}, {etat.poste.nom}", "attention", etat.en_texte(), QUOI_FAIRE)
            for etat in self.etats.values()
            if not etat.pret
        ]
        refus = self.refus_lot()
        if refus is None:
            postes = ", ".join(self.postes_lances)
            constats.append(Constat(SUJET, "ok", f"un lot de seaux peut partir ({postes})"))
        else:
            constats.append(
                Constat(SUJET, "bloquant", f"aucun lot de seaux ne peut partir : {refus}")
            )
        return constats

    def texte_ecran(self) -> tuple[str, str]:
        """Pour l'écran de l'armoire, quand aucun cycle ne tourne : quel poste manque (ligne
        courte) et pourquoi (ligne d'information)."""
        etat = self.manquant()
        if etat is None:
            return "Lot de seaux : prêt", ""
        return f"Lot de seaux : {etat.poste.nom.replace('_', ' ')} pas prêt", etat.raison

    def en_texte(self) -> str:
        lignes = ["Mode seaux (ordre du cycle d'un seau) :"]
        for etat in self.etats.values():
            lignes.append(f"  {etat.poste.nom:<11} {etat.poste.texte} : {etat.en_texte()}")
        refus = self.refus_lot()
        lignes.append("  lot : " + ("peut partir" if refus is None else f"impossible ({refus})"))
        return "\n".join(lignes)

    # ------------------------------------------------------------ le lot

    def modules_du_lot(self, lot: Lot, memoire: Mapping[str, Any] | None = None) -> list[Module]:
        """Les modules du chef pour ce lot (« remplissage » et « mycelium »). `memoire` : celle
        du carnet, après une coupure (seau en cours, couche, seau sur le plateau)."""
        refus = self.refus_lot()
        if refus is not None:
            raise ErreurChef(f"lot de seaux impossible : {refus}")
        pieces = self.pieces.remplissage(
            lot,
            self.pret("micropore"),
            self.pret("fermeture"),
            self.pret("spray"),
            self.pret("couvercle"),
        )
        plan = pieces.plan
        plan.fin_de_lot = lot.fin_de_lot
        if memoire is not None:
            self._retrouver(pieces, memoire)
        remplissage = module_remplissage(
            pieces.remplissage,
            pieces.prehension,
            pieces.mycelium,
            plan,
            # Le venturi de la tête prend le seau : attente de la mise en pression (tâche 42).
            air=self.chef.condition_permission("air"),
            # Ordre corrigé du 07/11/2026 : seau vide au poste, spray, rangées du haut du
            # micropore, puis la 1re couche.
            seau_vide_au_poste=True,
            spray=pieces.spray,
            griffe_partie=pieces.griffe_partie,
            couvercle=pieces.couvercle,
        )
        en_cours = _LotEnCours(lot, pieces)
        en_cours.modules = [
            self._noter_le_lot(remplissage, en_cours),
            module_mycelium(pieces.mycelium),
        ]
        self.en_cours = en_cours
        return list(en_cours.modules)

    def lancer_lot(self, lot: Lot) -> list[str]:
        """Donne les modules du lot au chef (règle 6 : un lot est proposé puis lancé après le Go
        de Karulium : c'est à celui qui appelle de l'avoir eu)."""
        modules = self.modules_du_lot(lot)
        for module in modules:
            self.chef.lancer(module)
        self._noter()
        journal.info(
            "Lot de %d seaux « %s » lancé (%s)",
            len(lot.seaux),
            lot.format,
            ", ".join(self.postes_lances),
        )
        return [module.nom for module in modules]

    def modules_a_reprendre(self, etat_carnet: Mapping[str, Any] | None) -> list[Module]:
        """Après une coupure : les modules du lot noté dans le carnet (vide s'il n'y en a pas).
        Un lot noté mais impossible maintenant n'est pas reconstruit : le chef dira alors que le
        carnet ne correspond pas au programme (check-list : bloquant)."""
        if not etat_carnet:
            return []
        for note in etat_carnet.get("modules", []):
            if note.get("module") != REMPLISSAGE or note.get("statut") not in (
                "en_cours",
                "alarme",
            ):
                continue
            memoire = note.get("memoire") or {}
            if "lot" not in memoire:
                journal.error("Carnet : lot du remplissage pas noté, il ne peut pas être repris.")
                return []
            refus = self.refus_lot()
            if refus is not None:
                journal.error("Carnet : lot en cours, mais lot impossible maintenant : %s", refus)
                return []
            lot = Lot.depuis(memoire["lot"])
            journal.warning(
                "Reprise du lot « %s » : seau n° %d, couche %d",
                lot.format,
                memoire.get("numero", 0) + 1,
                memoire.get("couche", 1),
            )
            return self.modules_du_lot(lot, memoire)
        return []

    def _retrouver(self, pieces: PiecesRemplissage, memoire: Mapping[str, Any]) -> None:
        plan = pieces.plan
        plan.numero = int(memoire.get("numero", 0))
        plan.couche = int(memoire.get("couche", 1))
        plan.faits = list(memoire.get("faits", []))
        plan.file_en_cours = memoire.get("file_en_cours")
        seau = memoire.get("seau_plateau")
        if seau is not None:
            pieces.remplissage.seau = SeauPlateau(**seau)

    def _noter_le_lot(self, module: Module, en_cours: _LotEnCours) -> Module:
        """Le même module, qui note où en est le lot dans le carnet à la fin de chaque étape."""

        def suivie(etape: Etape) -> Etape:
            ensuite = etape.ensuite

            def apres() -> str | None:
                suivante = ensuite() if ensuite is not None else None
                self._noter(en_cours)
                return suivante

            return replace(etape, ensuite=apres)

        return replace(module, etapes=tuple(suivie(etape) for etape in module.etapes))

    def _noter(self, en_cours: _LotEnCours | None = None) -> None:
        en_cours = en_cours or self.en_cours
        if en_cours is None:
            return
        plan, seau = en_cours.pieces.plan, en_cours.pieces.remplissage.seau
        try:
            self.chef.memoriser(
                REMPLISSAGE,
                lot=en_cours.lot.memoire(),
                numero=plan.numero,
                couche=plan.couche,
                faits=list(plan.faits),
                file_en_cours=plan.file_en_cours,
                seau_plateau=None if seau is None else asdict(seau),
            )
        except ErreurChef as erreur:
            journal.error("Lot pas noté dans le carnet : %s", erreur)
