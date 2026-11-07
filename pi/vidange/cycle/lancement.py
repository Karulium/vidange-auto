"""Lancer un lot : le bouton de la page web, puis le Go à l'écran de l'armoire (tâche 45 quater).

    lancement = Lancement(reglages.programme.lot, reglages.machine, mode_seaux, mode_bocaux,
                          stockage, fond)
    lancement.proposer_seaux("seau_a", 18, "pleurote_grise", qui)   # page web : le Pi propose
    lancement.proposer_bocaux(12, qui)
    lancement.texte_ecran()                                         # l'écran le montre
    lancement.go(qui)                                               # Go à l'écran : le lot part
    lancement.annuler(qui)

Règle 6 du dépôt : le Pi propose, Karulium dit Go. Le bouton « Lot de seaux » (format, nombre,
variété) ou « Lot de bocaux » (nombre) de la page web ne fait que PROPOSER le lot ; il part quand
Karulium donne le Go sur l'écran de l'armoire (bouton GO de la page d'état, puis « Oui »), devant
la machine. Une seule proposition à la fois ; elle est oubliée au bout de
`lot → proposition_max_s` (programme.yaml).

Un lot est refusé, avec la raison, au bouton comme au Go (tout est revérifié au Go) :
- le mode ne va pas (un lot part en mode « production ») ;
- un lot tourne déjà ;
- un poste n'est pas prêt (« pas lancé : raison », comme la check-list) ;
- lot de seaux : plus de seaux que de bocaux de semence posés de la variété, de places libres
  dans la boîte des capsules ou de couvercles percés (`refus_taille_lot` de vidange.cycle.
  mode_seaux, un seul endroit, sans pause de rechargement en milieu de lot) ;
- lot de bocaux : moins de bocaux vides notés au stockage que demandé ;
- aucun Go n'est accepté (objet encore tenu à la ventouse au redémarrage, tâche 45 nonies).

Les seaux d'un lot lancé ici n'ont pas de nom d'avance : chacun prend le QR lu sur son flanc.
Au Go, les boucles de fond des pièces (FondDuLot : balances, vide, battement des servos) partent
juste avant le lot ; si elles ne peuvent pas partir, le lot n'est pas lancé.

Rien de cela ne protège personne : la sécurité est câblée.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from vidange.bocal_neuf.bocal_neuf import A_VERIFIER
from vidange.chef import ErreurChef
from vidange.cycle.mode_bocaux import LotBocaux, ModeBocaux
from vidange.cycle.mode_seaux import Lot, ModeSeaux
from vidange.journal import donner_journal
from vidange.reglages import Machine, ReglagesLot
from vidange.remplissage.module import SeauAFaire
from vidange.stockage import places

if TYPE_CHECKING:
    from vidange.cycle.machine import FondDuLot
    from vidange.stockage.stockage import Stockage

journal = donner_journal("lancement")

# Ce que l'inventaire du Stockage note pour un bocal vide posé, prêt à remplir.
BOCAL_VIDE = "bocal"
AUCUNE = "aucun lot proposé (bouton « Lot de seaux » ou « Lot de bocaux » de la page web)"


@dataclass(frozen=True)
class LotPropose:
    """Un lot proposé par la page web, qui attend le Go à l'écran."""

    sorte: Literal["seaux", "bocaux"]
    lot: Lot | LotBocaux
    # « 18 seaux seau_a (pleurote_grise) », pour l'écran et la page web.
    texte: str
    qui: str
    depuis: float

    def en_dict(self) -> dict[str, object]:
        return {"sorte": self.sorte, "texte": self.texte, "qui": self.qui}


class Lancement:
    def __init__(
        self,
        reglages: ReglagesLot,
        machine: Machine,
        mode_seaux: ModeSeaux | None,
        mode_bocaux: ModeBocaux | None,
        stockage: "Stockage | None" = None,
        fond: "FondDuLot | None" = None,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        """`stockage` : le Stockage de la machine (bocaux vides d'un lot de bocaux). `fond` : les
        boucles de fond des pièces (None : aucune, essais sans cartes)."""
        self.reglages = reglages
        self.machine = machine
        self.mode_seaux = mode_seaux
        self.mode_bocaux = mode_bocaux
        self.stockage = stockage
        self.fond = fond
        self._horloge = horloge
        self._verrou = threading.Lock()
        self._proposition: LotPropose | None = None
        # Le dernier lot lancé (texte), et ce qui a été dit (pour la page web et l'écran).
        self.dernier: str | None = None

    # ------------------------------------------------------------ la page web propose

    def proposer_seaux(self, format: str, nombre: int, variete: str, qui: str) -> LotPropose:
        """Le bouton « Lot de seaux » : `nombre` seaux vides de ce `format`, semence de cette
        `variete`. ErreurChef (avec la raison) si ce lot ne peut pas partir."""
        if self.mode_seaux is None:
            raise ErreurChef("lot de seaux refusé : mode seaux pas préparé")
        if nombre < 1:
            raise ErreurChef("lot de seaux refusé : au moins un seau")
        if not variete:
            raise ErreurChef("lot de seaux refusé : variété de la semence pas donnée")
        seau = SeauAFaire("", format, variete)
        lot = Lot(format, tuple(seau for _ in range(nombre)))
        refus = self.mode_seaux.refus_lancer(lot)
        if refus is not None:
            raise ErreurChef(refus)
        texte = f"{nombre} seaux {format} ({variete})"
        return self._proposer(LotPropose("seaux", lot, texte, qui, self._horloge()))

    def bocaux_vides(self) -> list[str]:
        """Les bocaux vides notés au Stockage, dans l'ordre du quinconce."""
        if self.stockage is None or self.machine.stockage is None:
            return []
        inventaire = self.stockage.inventaire.bocaux
        return [
            place
            for place in places.places_bocaux(self.machine)
            if inventaire.get(place) == BOCAL_VIDE
        ]

    def proposer_bocaux(self, nombre: int, qui: str) -> LotPropose:
        """Le bouton « Lot de bocaux » : `nombre` bocaux vides du Stockage."""
        if self.mode_bocaux is None:
            raise ErreurChef("lot de bocaux refusé : mode bocaux pas préparé")
        if nombre < 1:
            raise ErreurChef("lot de bocaux refusé : au moins un bocal")
        # Mode, autre lot, postes : avant de compter les bocaux (la raison la plus utile d'abord).
        refus = self.mode_bocaux.refus_lancer(LotBocaux(("?",)))
        if refus is not None:
            raise ErreurChef(refus)
        vides = self.bocaux_vides()
        if nombre > len(vides):
            raise ErreurChef(
                f"lot de bocaux refusé : {nombre} bocaux demandés, {len(vides)} bocaux vides notés "
                "au stockage"
            )
        lot = LotBocaux(tuple(vides[:nombre]))
        refus = self.mode_bocaux.refus_lancer(lot)
        if refus is not None:
            raise ErreurChef(refus)
        return self._proposer(LotPropose("bocaux", lot, f"{nombre} bocaux", qui, self._horloge()))

    def _proposer(self, proposition: LotPropose) -> LotPropose:
        with self._verrou:
            self._proposition = proposition
        journal.info(
            "Lot de %s proposé par la %s : attend le Go à l'écran de l'armoire",
            proposition.texte,
            proposition.qui,
        )
        return proposition

    def annuler(self, qui: str) -> None:
        with self._verrou:
            proposition, self._proposition = self._proposition, None
        if proposition is not None:
            journal.info("Lot de %s proposé : annulé par la %s", proposition.texte, qui)

    @property
    def proposition(self) -> LotPropose | None:
        """Le lot proposé qui attend le Go (None : aucun, ou trop vieux)."""
        with self._verrou:
            proposition = self._proposition
            if proposition is None:
                return None
            if self._horloge() - proposition.depuis > self.reglages.proposition_max_s:
                journal.info(
                    "Lot de %s proposé il y a plus de %g s sans Go : oublié",
                    proposition.texte,
                    self.reglages.proposition_max_s,
                )
                self._proposition = None
                return None
            return proposition

    # ------------------------------------------------------------ Karulium dit Go à l'écran

    def refus_go(self) -> str | None:
        """Pourquoi le Go ne lancerait rien maintenant (None : il lancerait le lot proposé)."""
        proposition = self.proposition
        if proposition is None:
            return AUCUNE
        for mode in (self.mode_seaux, self.mode_bocaux):
            # Un Go empêché (objet encore tenu à la ventouse au redémarrage, tâche 45 nonies).
            empeche = None if mode is None else mode.chef.refus_go()
            if empeche is not None:
                return empeche
        if isinstance(proposition.lot, Lot):
            assert self.mode_seaux is not None
            return self.mode_seaux.refus_lancer(proposition.lot)
        assert self.mode_bocaux is not None
        return self.mode_bocaux.refus_lancer(proposition.lot)

    def go(self, qui: str) -> list[str]:
        """Le Go de Karulium : tout est revérifié, les boucles de fond partent, puis le lot est
        donné au chef. Rend les modules lancés ; ErreurChef (avec la raison) sinon."""
        proposition = self.proposition
        if proposition is None:
            raise ErreurChef(AUCUNE)
        refus = self.refus_go()
        if refus is not None:
            raise ErreurChef(refus)
        lot = proposition.lot
        noms = self._modules(lot)
        if self.fond is not None:
            self.fond.demarrer(noms)
        try:
            if isinstance(lot, Lot):
                assert self.mode_seaux is not None
                lances = self.mode_seaux.lancer_lot(lot)
            else:
                assert self.mode_bocaux is not None
                lances = self.mode_bocaux.lancer_lot(lot)
        except Exception:
            if self.fond is not None:
                self.fond.arreter()
            raise
        with self._verrou:
            if self._proposition is proposition:
                self._proposition = None
        self.dernier = proposition.texte
        journal.warning(
            "Go de la %s : lot de %s lancé (%s)", qui, proposition.texte, ", ".join(lances)
        )
        return lances

    @staticmethod
    def _modules(lot: Lot | LotBocaux) -> list[str]:
        from vidange.cycle.mode_bocaux import ENTONNOIR
        from vidange.cycle.mode_seaux import MYCELIUM, REMPLISSAGE

        return [REMPLISSAGE, MYCELIUM] if isinstance(lot, Lot) else [ENTONNOIR]

    # ------------------------------------------------------------ ce qu'on dit

    def texte_ecran(self) -> tuple[str, str] | None:
        """Pour la page d'état de l'écran : le lot qui attend le Go (ligne courte) et ce que le Go
        ferait (ligne d'information) ; None : rien de proposé."""
        proposition = self.proposition
        if proposition is None:
            return None
        refus = self.refus_go()
        if refus is None:
            return f"Lot de {proposition.texte} : GO ?", "Toucher GO pour lancer le lot."
        return f"Lot de {proposition.texte} : impossible", refus

    def en_dict(self) -> dict[str, object]:
        proposition = self.proposition
        return {
            "proposition": None if proposition is None else proposition.en_dict(),
            "refus_go": None if proposition is None else self.refus_go(),
            "dernier": self.dernier,
            "fond": [] if self.fond is None else list(self.fond.actives),
            "refus_seaux": None if self.mode_seaux is None else self.mode_seaux.refus_lot(),
            "refus_bocaux": None if self.mode_bocaux is None else self.mode_bocaux.refus_lot(),
            "formats": self.formats(),
            "varietes": self.varietes(),
            "bocaux_vides": len(self.bocaux_vides()),
        }

    def formats(self) -> list[str]:
        griffe = self.machine.griffe
        return [] if griffe is None else list(griffe.formats)

    def varietes(self) -> dict[str, int]:
        """Les bocaux de semence posés au Stockage, par variété (pour la page web)."""
        if self.stockage is None or self.machine.stockage is None:
            return {}
        inventaire = self.stockage.inventaire.bocaux
        comptes: dict[str, int] = {}
        for place in places.places_semence(self.machine):
            variete = inventaire.get(place)
            if variete is not None and variete != A_VERIFIER:
                comptes[variete] = comptes.get(variete, 0) + 1
        return comptes
