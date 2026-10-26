"""Zones réservées entre modules (les zones sont nommées dans machine.yaml).

Un module qui va travailler dans une zone la réserve d'abord ; un autre module qui la veut
attend qu'elle soit libérée. Les zones de machine.yaml ne se chevauchent pas (c'est vérifié
au démarrage) : une zone = un seul module à la fois suffit.
"""

from collections.abc import Iterable

from vidange.chef.etapes import ErreurChef


class Reservations:
    def __init__(self, zones: Iterable[str]) -> None:
        self._tenues: dict[str, str | None] = dict.fromkeys(zones)

    def verifier(self, zones: Iterable[str]) -> list[str]:
        """Les zones inconnues de machine.yaml."""
        return [zone for zone in zones if zone not in self._tenues]

    def tenant(self, zone: str) -> str | None:
        """Le module qui tient la zone, ou None si elle est libre."""
        return self._tenues[zone]

    def reserver(self, zones: Iterable[str], module: str) -> tuple[str, str] | None:
        """Réserve toutes les zones, ou aucune.

        Rend None si c'est fait, sinon (zone, module qui la tient) pour la première zone prise.
        """
        zones = list(zones)
        for zone in zones:
            if zone not in self._tenues:
                raise ErreurChef(f"zone « {zone} » absente de machine.yaml")
            tenant = self._tenues[zone]
            if tenant is not None and tenant != module:
                return zone, tenant
        for zone in zones:
            self._tenues[zone] = module
        return None

    def liberer(self, zones: Iterable[str], module: str) -> None:
        """Libère les zones que ce module tient (les autres ne changent pas)."""
        for zone in zones:
            if self._tenues.get(zone) == module:
                self._tenues[zone] = None

    def liberer_tout(self, module: str) -> None:
        self.liberer(self.tenues_par(module), module)

    def tenues_par(self, module: str) -> list[str]:
        return [zone for zone, tenant in self._tenues.items() if tenant == module]
