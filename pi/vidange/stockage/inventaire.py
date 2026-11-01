"""L'inventaire du Stockage : ce que le Pi sait de chaque place (aucun capteur de présence).

Chaque changement est noté par `noter(place, contenu, nombre)` (dans le registre, table
« inventaire_stockage ») ; au démarrage, l'inventaire reprend ce que le registre a gardé.
Les caméras vérifient (vision, plus tard) ; l'opérateur corrige depuis l'écran.

Noms des places : pile_1..., fin_1... (piles de seaux vides), couvercles, file_1... (tiroir),
bande_haut (seaux pleins sur le plateau, un seul format), bocal_j_i et semence_r_i (bocaux),
boite_<nom> (boîtes à capsules).
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Pile:
    """Une pile de seaux (vides, ou pleins sur la bande du haut) : son format (None : vide) et
    son nombre de seaux."""

    format: str | None = None
    nombre: int = 0


class InventaireStockage:
    def __init__(
        self,
        piles: list[str],
        files: list[str],
        boites: list[str],
        noter: Callable[[str, str | None, int], object] = lambda place, contenu, nombre: None,
    ) -> None:
        self.piles = {nom: Pile() for nom in piles}
        self.couvercles = 0
        self.files = {nom: 0 for nom in files}
        self.bande_haut = Pile()
        # Bocaux posés : place → ce qu'il y a (« bocal », « suspect », « semence »...).
        self.bocaux: dict[str, str] = {}
        self.boites = {nom: 0 for nom in boites}
        self._noter = noter

    # ------------------------------------------------------------ changements

    def changer_pile(self, nom: str, format: str | None, nombre: int) -> None:
        pile = self.piles[nom]
        pile.format, pile.nombre = (format, nombre) if nombre > 0 else (None, 0)
        self._noter(nom, pile.format, pile.nombre)

    def changer_couvercles(self, nombre: int) -> None:
        self.couvercles = nombre
        self._noter("couvercles", None, nombre)

    def changer_file(self, nom: str, nombre: int) -> None:
        self.files[nom] = nombre
        self._noter(nom, None, nombre)

    def changer_bande(self, format: str | None, nombre: int) -> None:
        self.bande_haut = Pile(format, nombre) if nombre > 0 else Pile()
        self._noter("bande_haut", self.bande_haut.format, self.bande_haut.nombre)

    def changer_bocal(self, place: str, contenu: str | None) -> None:
        if contenu is None:
            self.bocaux.pop(place, None)
        else:
            self.bocaux[place] = contenu
        self._noter(place, contenu, 0 if contenu is None else 1)

    def changer_boite(self, nom: str, capsules: int) -> None:
        self.boites[nom] = capsules
        self._noter(f"boite_{nom}", None, capsules)

    # ------------------------------------------------------------ reprise

    def reprendre(self, lignes: dict[str, tuple[str | None, int]]) -> None:
        """Reprend l'inventaire gardé (place → contenu, nombre), sans le noter à nouveau. Une
        place que les réglages n'ont plus est ignorée."""
        for place, (contenu, nombre) in lignes.items():
            if place in self.piles:
                self.piles[place] = Pile(contenu, nombre) if nombre > 0 else Pile()
            elif place in self.files:
                self.files[place] = nombre
            elif place == "couvercles":
                self.couvercles = nombre
            elif place == "bande_haut":
                self.bande_haut = Pile(contenu, nombre) if nombre > 0 else Pile()
            elif place.startswith("boite_") and place[6:] in self.boites:
                self.boites[place[6:]] = nombre
            elif place.startswith(("bocal_", "semence_")) and contenu is not None and nombre:
                self.bocaux[place] = contenu
