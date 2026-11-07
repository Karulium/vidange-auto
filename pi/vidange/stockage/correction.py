"""Corriger à la main l'inventaire du Stockage depuis la page web (tâche 45 quinquies).

    correction = Correction(stockage, delai_s, refus_occupe)
    correction.proposer("semence_0_3", "shiitake", 0, qui)   # la page web : le Pi propose
    correction.confirmer(qui)                                # la page web : Karulium dit Go

Même principe que le lot (vidange.cycle.lancement) : le Pi PROPOSE la correction (avant → après),
et rien n'est écrit tant que Karulium n'a pas confirmé. Ici la confirmation est un second bouton
de la page web (pas l'écran de l'armoire : une correction de nombres ne fait bouger aucune
machine). Une seule proposition à la fois, oubliée au bout de `delai_s`.

Ce qu'on peut corriger (les noms sont ceux de l'inventaire, vidange.stockage.inventaire) :
- `semence_r_i` : variété du bocal de semence posé (contenu vide : place vide) ;
- `boite_<nom>` : nombre de capsules ou de couvercles percés dans la boîte (0 à la capacité) ;
- `pile_...` et `fin_...` : format et nombre de seaux vides (0 à ce que tient une pile) ;
- `couvercles` : nombre de couvercles (0 ou plus : les réglages ne donnent pas de capacité).

Refusée pendant un lot (`refus_occupe` dit pourquoi), si la place est inconnue ou si la valeur est
impossible. Chaque correction écrite est notée au journal, avant et après. `refus_taille_lot`
(vidange.cycle.mode_seaux) lit ensuite l'inventaire corrigé : rien d'autre à brancher.
Rien de cela ne protège personne : la sécurité est câblée.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vidange.chef import ErreurChef
from vidange.chef.etapes import ErreurEtape
from vidange.journal import donner_journal
from vidange.stockage import places

if TYPE_CHECKING:
    from vidange.stockage.stockage import Stockage

journal = donner_journal("correction_stockage")

PREFIXE_BOITE = "boite_"
PREFIXE_SEMENCE = "semence_"


@dataclass(frozen=True)
class Changement:
    """Une correction proposée : la place, ce qu'elle contient avant et après."""

    place: str
    contenu: str | None
    nombre: int
    avant: str
    apres: str
    qui: str
    depuis: float

    def en_dict(self) -> dict[str, object]:
        return {"place": self.place, "avant": self.avant, "apres": self.apres, "qui": self.qui}


def _texte(contenu: str | None, nombre: int) -> str:
    if contenu is None:
        return f"{nombre}" if nombre else "vide"
    return f"{nombre} × {contenu}" if nombre != 1 else contenu


class Correction:
    def __init__(
        self,
        stockage: "Stockage",
        delai_s: float,
        refus_occupe: Callable[[], str | None] = lambda: None,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        """`refus_occupe` : pourquoi pas maintenant (un lot tourne) ; None : on peut corriger."""
        self.stockage = stockage
        self.delai_s = delai_s
        self._refus_occupe = refus_occupe
        self._horloge = horloge
        self._verrou = threading.Lock()
        self._proposition: Changement | None = None

    # ------------------------------------------------------------ ce que l'inventaire contient

    def _avant(self, place: str) -> tuple[str | None, int]:
        """(contenu, nombre) d'une place connue ; ErreurChef si la place est inconnue."""
        inventaire = self.stockage.inventaire
        if place in inventaire.piles:
            pile = inventaire.piles[place]
            return pile.format, pile.nombre
        if place == "couvercles":
            return None, inventaire.couvercles
        if place.startswith(PREFIXE_BOITE) and place[len(PREFIXE_BOITE) :] in inventaire.boites:
            return None, inventaire.boites[place[len(PREFIXE_BOITE) :]]
        if place in places.places_semence(self.stockage.machine):
            variete = inventaire.bocaux.get(place)
            return variete, 0 if variete is None else 1
        raise ErreurChef(f"correction refusée : place « {place} » inconnue")

    def inventaire(self) -> dict[str, object]:
        """Pour la page web : tout ce qu'on peut corriger, avec les limites."""
        machine, inventaire = self.stockage.machine, self.stockage.inventaire
        assert machine.griffe is not None
        capacite = places.capacite_boite(machine)
        proposition = self.proposition
        return {
            "semence": {
                place: inventaire.bocaux.get(place) for place in places.places_semence(machine)
            },
            "boites": {
                nom: {"nombre": n, "capacite": capacite} for nom, n in inventaire.boites.items()
            },
            "piles": {
                nom: {"format": pile.format, "nombre": pile.nombre}
                for nom, pile in inventaire.piles.items()
            },
            "pile_max": {
                format: places.seaux_par_pile(machine, format) for format in machine.griffe.formats
            },
            "couvercles": inventaire.couvercles,
            "proposition": None if proposition is None else proposition.en_dict(),
            "refus": self._refus_occupe(),
        }

    # ------------------------------------------------------------ la page web propose

    def proposer(self, place: str, contenu: str | None, nombre: int, qui: str) -> Changement:
        """Propose de mettre `place` à (`contenu`, `nombre`). ErreurChef (avec la raison) si la
        correction est impossible ; rien n'est écrit."""
        refus = self._refus_occupe()
        if refus is not None:
            raise ErreurChef(f"correction refusée : {refus}")
        contenu = (contenu or "").strip() or None
        avant = self._avant(place)
        nombre = self._verifier(place, contenu, nombre)
        changement = Changement(
            place,
            contenu,
            nombre,
            _texte(*avant),
            _texte(contenu, nombre),
            qui,
            self._horloge(),
        )
        with self._verrou:
            self._proposition = changement
        journal.info(
            "Correction proposée par la %s : %s, %s → %s (attend la confirmation)",
            qui,
            place,
            changement.avant,
            changement.apres,
        )
        return changement

    def _verifier(self, place: str, contenu: str | None, nombre: int) -> int:
        """Refuse une valeur impossible ; rend le nombre à écrire."""
        machine = self.stockage.machine
        assert machine.griffe is not None
        if nombre < 0:
            raise ErreurChef(f"correction refusée : {place} : nombre négatif ({nombre})")
        if place in self.stockage.inventaire.piles:
            if nombre == 0:
                return 0
            if contenu not in machine.griffe.formats:
                connus = ", ".join(machine.griffe.formats)
                raise ErreurChef(
                    f"correction refusée : {place} : format « {contenu} » inconnu "
                    f"(formats : {connus})"
                )
            plus = places.seaux_par_pile(machine, contenu)
            if nombre > plus:
                raise ErreurChef(
                    f"correction refusée : {place} : {nombre} seaux « {contenu} », une pile "
                    f"en tient {plus} au plus"
                )
        elif place.startswith(PREFIXE_BOITE):
            capacite = places.capacite_boite(machine)
            if nombre > capacite:
                raise ErreurChef(
                    f"correction refusée : {place} : {nombre} pièces, la boîte en tient {capacite} "
                    "au plus"
                )
        elif place.startswith(PREFIXE_SEMENCE):
            return 0 if contenu is None else 1
        return nombre

    # ------------------------------------------------------------ Karulium confirme

    @property
    def proposition(self) -> Changement | None:
        """La correction qui attend la confirmation (None : aucune, ou trop vieille)."""
        with self._verrou:
            proposition = self._proposition
            if proposition is None:
                return None
            if self._horloge() - proposition.depuis > self.delai_s:
                journal.info(
                    "Correction de %s proposée il y a trop longtemps : oubliée", proposition.place
                )
                self._proposition = None
                return None
            return proposition

    def annuler(self, qui: str) -> None:
        with self._verrou:
            proposition, self._proposition = self._proposition, None
        if proposition is not None:
            journal.info("Correction de %s annulée par la %s", proposition.place, qui)

    def confirmer(self, qui: str) -> Changement:
        """Le Go de Karulium : tout est revérifié, puis la correction est écrite et notée au
        journal (avant, après). ErreurChef (avec la raison) sinon."""
        proposition = self.proposition
        if proposition is None:
            raise ErreurChef("aucune correction proposée (ou elle est trop vieille)")
        refus = self._refus_occupe()
        if refus is not None:
            raise ErreurChef(f"correction refusée : {refus}")
        place, contenu, nombre = proposition.place, proposition.contenu, proposition.nombre
        # Revérifié : les réglages ou l'inventaire ont pu changer depuis la proposition.
        avant = _texte(*self._avant(place))
        self._verifier(place, contenu, nombre)
        inventaire = self.stockage.inventaire
        try:
            if place in inventaire.piles and nombre == 0:
                inventaire.changer_pile(place, None, 0)
            elif place in inventaire.piles:
                assert contenu is not None
                self.stockage.charger_pile(place, contenu, nombre)
            elif place == "couvercles":
                inventaire.changer_couvercles(nombre)
            elif place.startswith(PREFIXE_BOITE):
                inventaire.changer_boite(place[len(PREFIXE_BOITE) :], nombre)
            else:
                inventaire.changer_bocal(place, contenu)
        except ErreurEtape as erreur:
            raise ErreurChef(f"correction refusée : {erreur}") from erreur
        with self._verrou:
            if self._proposition is proposition:
                self._proposition = None
        journal.warning(
            "Inventaire du stockage corrigé par la %s : %s, %s → %s",
            qui,
            place,
            avant,
            proposition.apres,
        )
        return proposition
