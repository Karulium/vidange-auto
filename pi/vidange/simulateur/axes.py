"""Axes imaginaires du simulateur : même usage que vidange.chef.axes.Axes, sans carte FluidNC.

    axes = simulateur.axes()  # un objet par module, comme les vrais Axes
    Etape(..., action=lambda: axes.aller("repos"), fin=axes.arrives, entree=(axes.pretes,))

Un déplacement dure le temps de l'axe le plus long à arriver : chaque axe accélère, roule à sa
vitesse, puis freine (vitesse et accélération dans simulateur.yaml). Comme sur une vraie carte,
un mouvement demandé à une carte qui bouge encore part après le précédent. Les axes de tous les
modules partagent les mêmes positions : il n'y a qu'une machine.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

from vidange.chef.etapes import Condition, ErreurEtape
from vidange.reglages import Machine, ReglagesSimulateur

# Marge pour comparer deux heures calculées (s).
_MARGE = 1e-9


@dataclass(frozen=True)
class Mouvement:
    """Un déplacement vers une position nommée."""

    position: str
    # Axe → (départ, arrivée), en m.
    axes: dict[str, tuple[float, float]]
    # Heure de la demande et heure d'arrivée prévue (s, temps simulé).
    debut: float
    fin: float


def duree_trajet(distance: float, vitesse: float, acceleration: float) -> float:
    """Temps (s) pour parcourir la distance (m) : accélérer, rouler, freiner."""
    distance = abs(distance)
    if distance == 0:
        return 0.0
    if distance >= vitesse**2 / acceleration:
        # Assez long pour atteindre la vitesse : accélération + palier + freinage.
        return distance / vitesse + vitesse / acceleration
    # Trop court : on freine avant d'avoir atteint la vitesse.
    return 2 * math.sqrt(distance / acceleration)


class EtatAxes:
    """Positions des axes de toute la machine imaginaire, et mouvements de chaque carte.

    Les heures des mouvements sont comptées sans les pauses (une pause fige les axes).
    """

    def __init__(
        self, machine: Machine, reglages: ReglagesSimulateur, horloge: Callable[[], float]
    ) -> None:
        self._machine = machine
        self._reglages = reglages
        self._horloge = horloge
        depart = machine.positions[reglages.depart] if reglages.depart is not None else {}
        # Positions à la fin des mouvements déjà demandés (m).
        self.positions = {nom: depart.get(nom, axe.course[0]) for nom, axe in machine.axes.items()}
        # Tous les mouvements demandés, dans l'ordre.
        self.mouvements: list[Mouvement] = []
        # Carte → heure (sans les pauses) où elle aura fini ses mouvements.
        self._libre: dict[str, float] = {}
        self._temps_en_pause = 0.0
        self._pause_depuis: float | None = None

    def _sans_pauses(self) -> float:
        maintenant = self._horloge()
        pause_en_cours = 0.0 if self._pause_depuis is None else maintenant - self._pause_depuis
        return maintenant - self._temps_en_pause - pause_en_cours

    def aller(self, position: str) -> dict[str, float]:
        """Demande le mouvement ; rend, par carte, l'heure (sans les pauses) de son arrivée."""
        if position not in self._machine.positions:
            raise ErreurEtape(f"position « {position} » absente de machine.yaml")
        maintenant = self._sans_pauses()
        trajets: dict[str, tuple[float, float]] = {}
        durees: dict[str, float] = {}
        for nom_axe, cible in self._machine.positions[position].items():
            carte = self._machine.axes[nom_axe].carte
            if carte is None:
                raise ErreurEtape(f"axe « {nom_axe} » : pas de carte FluidNC dans machine.yaml")
            reglage = self._reglages.axes.get(nom_axe)
            if reglage is None:
                raise ErreurEtape(
                    f"axe « {nom_axe} » : pas de vitesse ni d'accélération dans simulateur.yaml"
                )
            depart = self.positions[nom_axe]
            trajets[nom_axe] = (depart, cible)
            duree = duree_trajet(cible - depart, reglage.vitesse, reglage.acceleration)
            durees[carte] = max(durees.get(carte, 0.0), duree)
        arrivees = {}
        for carte, duree in durees.items():
            arrivees[carte] = max(maintenant, self._libre.get(carte, 0.0)) + duree
            self._libre[carte] = arrivees[carte]
        self.positions.update({nom: cible for nom, (_, cible) in trajets.items()})
        decalage = self._horloge() - maintenant
        self.mouvements.append(
            Mouvement(
                position=position,
                axes=trajets,
                debut=self._horloge(),
                fin=max(arrivees.values(), default=maintenant) + decalage,
            )
        )
        return arrivees

    def arrives(self, arrivees: dict[str, float]) -> bool:
        maintenant = self._sans_pauses()
        return all(arrivee <= maintenant + _MARGE for arrivee in arrivees.values())

    def prochaine_arrivee(self) -> float | None:
        """Heure (temps simulé) où le prochain mouvement en cours finira, ou None."""
        if self._pause_depuis is not None:
            return None
        maintenant = self._sans_pauses()
        a_venir = [libre for libre in self._libre.values() if libre > maintenant + _MARGE]
        if not a_venir:
            return None
        return min(a_venir) + self._horloge() - maintenant

    def pauser(self) -> None:
        if self._pause_depuis is None:
            self._pause_depuis = self._horloge()

    def reprendre(self) -> None:
        if self._pause_depuis is not None:
            self._temps_en_pause += self._horloge() - self._pause_depuis
            self._pause_depuis = None


class AxesSimulees:
    """Ce que voit un module : les mêmes noms que vidange.chef.axes.Axes."""

    def __init__(self, etat: EtatAxes) -> None:
        self._etat = etat
        self._arrivees: dict[str, float] = {}
        # Pas de vraie carte : toujours prêtes, jamais en alarme.
        self.pretes = Condition("cartes simulées prêtes", lambda: True)
        self.surveillance = Condition("cartes simulées sans alarme", lambda: True)
        self.arrives = Condition("axes arrivés", self.arrive)

    def aller(self, position: str) -> None:
        self._arrivees = self._etat.aller(position)

    def arrive(self) -> bool:
        return self._etat.arrives(self._arrivees)

    def pauser(self) -> None:
        self._etat.pauser()

    def reprendre(self) -> None:
        self._etat.reprendre()
