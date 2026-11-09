"""Ce que la page web a besoin pour dessiner la machine : la scène (les boîtes, les zones) et les
positions des axes.

Aucun chiffre de la machine ici : la scène vient de `vue3d.yaml` et de `machine.yaml`, les
positions des rapports d'état des cartes FluidNC (les mêmes que celles du pilotage à distance).
"""

from collections.abc import Callable, Mapping
from typing import Any

from vidange.fluidnc import Liaison
from vidange.reglages import Machine, ReglagesVue3d

# machine.yaml est en mètres, FluidNC en millimètres (un axe tournant reste en degrés).
MM_PAR_M = 1000


class Vue3d:
    """La scène et les positions. `zones_tenues` : zone → module qui la tient (le chef)."""

    def __init__(
        self,
        reglages: ReglagesVue3d,
        machine: Machine,
        liaisons: Mapping[str, Liaison],
        zones_tenues: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        self.reglages = reglages
        self.machine = machine
        self.liaisons = liaisons
        self._zones_tenues = zones_tenues

    # ------------------------------------------------------------ la scène

    def axes_lus(self) -> list[str]:
        """Les axes dont on lit la position : ceux qui ont une carte FluidNC."""
        return [nom for nom, axe in self.machine.axes.items() if axe.carte is not None]

    def scene(self) -> dict[str, Any]:
        """Tout ce que la page dessine, en mètres (degrés pour un axe tournant)."""
        r = self.reglages
        return {
            "exemple": r.exemple,
            "rafraichir_s": r.rafraichir_s,
            "etendue": {sens: list(getattr(r.etendue, sens)) for sens in ("x", "y", "z")},
            "couleurs": {
                "fond": r.couleurs.fond,
                "sol": r.couleurs.sol,
                "zone_libre": r.couleurs.zone_libre,
                "zone_tenue": r.couleurs.zone_tenue,
            },
            "axes": {
                nom: {"unite": axe.unite, "course": list(axe.course)}
                for nom, axe in self.machine.axes.items()
                if axe.carte is not None
            },
            "boites": [
                {
                    "nom": nom,
                    "libelle": boite.libelle,
                    "couleur": r.couleurs.boites[boite.couleur],
                    "taille": list(boite.taille),
                    "x": {"axe": boite.x.axe, "decalage": boite.x.decalage},
                    "y": {"axe": boite.y.axe, "decalage": boite.y.decalage},
                    "z": {"axe": boite.z.axe, "decalage": boite.z.decalage},
                    "tourne": boite.tourne,
                }
                for nom, boite in r.boites.items()
            ],
            "zones": self._zones(),
            "rejeu": {
                "avant_s": r.rejeu.avant_s,
                "apres_s": r.rejeu.apres_s,
                "periode_s": r.rejeu.periode_s,
                "vitesses": list(r.rejeu.vitesses),
                "alarmes_proposees": r.rejeu.alarmes_proposees,
            },
        }

    def _zones(self) -> list[dict[str, Any]]:
        """Chaque zone de machine.yaml en boîte : un intervalle par sens. Un sens que la zone ne
        cite pas prend tout le volume dessiné ; deux axes dans le même sens : leur enveloppe."""
        zones = []
        for nom, zone in self.machine.zones.items():
            intervalles: dict[str, list[float]] = {}
            for axe, (debut, fin) in zone.items():
                sens = self.reglages.axes_monde.get(axe)
                if sens is None:
                    continue  # axe tournant : la zone ne se dessine pas dans ce sens
                ancien = intervalles.get(sens)
                intervalles[sens] = (
                    [debut, fin] if ancien is None else [min(ancien[0], debut), max(ancien[1], fin)]
                )
            for sens in ("x", "y", "z"):
                intervalles.setdefault(sens, list(getattr(self.reglages.etendue, sens)))
            zones.append({"nom": nom, **intervalles})
        return zones

    # ------------------------------------------------------------ les positions

    def positions(self) -> dict[str, float | None]:
        """Position de chaque axe lu (m, ou ° pour un axe tournant) ; None si la carte n'a pas
        encore donné de position."""
        valeurs: dict[str, float | None] = {}
        for nom in self.axes_lus():
            axe = self.machine.axes[nom]
            liaison = self.liaisons.get(axe.carte or "")
            position = None if liaison is None else liaison.etat.positions.get(axe.lettre or "")
            if position is None:
                valeurs[nom] = None
            else:
                facteur = MM_PAR_M if axe.unite == "m" else 1
                valeurs[nom] = round(position / facteur, 4)
        return valeurs

    def zones_tenues(self) -> dict[str, str]:
        return {} if self._zones_tenues is None else self._zones_tenues()
