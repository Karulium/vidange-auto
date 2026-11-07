"""Zone du bras du spray (fil Spray, 07/11/2026 ; réponse à la PR n° 99, point 4).

    zone = ZoneDuBras(reglages.machine, griffe=griffe, prehension=prehension)
    zone.refus()       # raison (« la tête de la griffe est dans la zone... »), ou None
    zone.libre()       # condition d'entrée de « sortir le bras » et de « ranger le bras »

Le bras du spray ne sort et ne rentre que si aucune partie de la tête de la griffe, de la tête de
préhension ou de ce qu'elles tiennent n'est dans la zone `spray → bras → zone` (x, y, plus bas
que z_max). C'est la ZONE qui fait foi, pas le moment (« griffe partie du poste ») : chaque outil
est regardé là où il est, qu'il ait bougé lui-même ou qu'il ait été traîné par le pont (en butée
haute, avec sa charge : un seau pendu sous la tête de préhension descend plus bas qu'elle).

Vue de dessus : la griffe est son encombrement (corps et raclette, godet ouvert ou fermé, règles
de la griffe), de son bas (bas du godet) vers le haut ; la préhension est un disque autour de son
axe (rayon de la tête) dont le bas est la face, et l'objet tenu un disque autour de son axe à lui
(décalé pour l'entonnoir) dont le bas est la face moins ce qui pend dessous.

Position d'un outil inconnue : la zone n'est pas libre (on ne bouge pas à l'aveugle). Sans griffe
ou sans préhension branchée (simulateur, essais), seul l'autre est regardé. Les chiffres sont dans
machine.yaml (spray → bras → zone, EXEMPLE tant que la Maquette ne l'a pas balayée). Ce verrou ne
protège que la MACHINE : la sécurité des personnes reste câblée.
"""

import math
from typing import TYPE_CHECKING

from vidange.geometrie import touche_rectangle
from vidange.reglages import Machine, ZoneBrasSpray

if TYPE_CHECKING:
    from vidange.griffe.griffe import Griffe
    from vidange.griffe.regles import Pose as PoseGriffe
    from vidange.griffe.regles import ReglesGriffe
    from vidange.prehension.prehension import Prehension
    from vidange.prehension.regles import Objet, ReglesPrehension
    from vidange.prehension.regles import Pose as PosePrehension

# Recouvrement sous lequel on ne compte pas un outil dans la zone (bord contre bord), en m.
_EGAL = 1e-6


def _m(valeur: float) -> str:
    return f"{valeur:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def _disque_dedans(zone: ZoneBrasSpray, x: float, y: float, rayon: float) -> bool:
    dx = max(zone.x[0] - x, 0.0, x - zone.x[1])
    dy = max(zone.y[0] - y, 0.0, y - zone.y[1])
    return math.hypot(dx, dy) < rayon - _EGAL


def griffe_dans_la_zone(zone: ZoneBrasSpray, regles: "ReglesGriffe", pose: "PoseGriffe") -> bool:
    """Une partie de la tête de la griffe (ou ce qu'elle tient, dans son godet) dans la zone ?"""
    if regles.bas(pose) >= zone.z_max - _EGAL:
        return False
    return any(touche_rectangle(forme, zone.x, zone.y) for forme in regles.encombrement(pose))


def prehension_dans_la_zone(
    zone: ZoneBrasSpray,
    regles: "ReglesPrehension",
    pose: "PosePrehension",
    objet: "Objet | None",
) -> bool:
    """Une partie de la tête de préhension ou de l'objet qu'elle tient dans la zone ?"""
    if pose.z < zone.z_max - _EGAL and _disque_dedans(
        zone, pose.x, pose.y, regles.reglages.rayon_tete_m
    ):
        return True
    if objet is None:
        return False
    return regles.bas(pose, objet) < zone.z_max - _EGAL and _disque_dedans(
        zone, pose.x + objet.decalage_x_m, pose.y + objet.decalage_y_m, objet.rayon_m
    )


class ZoneDuBras:
    def __init__(
        self,
        machine: Machine,
        griffe: "Griffe | None" = None,
        prehension: "Prehension | None" = None,
    ) -> None:
        assert machine.spray is not None
        self.zone = machine.spray.bras.zone
        self.griffe = griffe
        self.prehension = prehension

    def _texte_zone(self) -> str:
        zone = self.zone
        return (
            f"zone du bras du spray (x {_m(zone.x[0])} à {_m(zone.x[1])}, y {_m(zone.y[0])} à "
            f"{_m(zone.y[1])}, sous z {_m(zone.z_max)} m)"
        )

    def refus(self) -> str | None:
        """Pourquoi le bras ne peut pas bouger maintenant (None : la zone est libre)."""
        griffe, prehension = self.griffe, self.prehension
        if griffe is not None:
            try:
                pose = griffe.bras.position()
            except Exception as erreur:
                return f"position de la griffe inconnue ({erreur}) : {self._texte_zone()}"
            if griffe_dans_la_zone(self.zone, griffe.regles, pose):
                return f"la tête de la griffe est dans la {self._texte_zone()}"
        if prehension is not None:
            try:
                pose_p = prehension.tete.position()
            except Exception as erreur:
                return f"position de la préhension inconnue ({erreur}) : {self._texte_zone()}"
            if prehension_dans_la_zone(self.zone, prehension.regles, pose_p, prehension.objet):
                tenu = "" if prehension.objet is None else f" (ou le/la {prehension.objet.sorte})"
                return f"la tête de préhension{tenu} est dans la {self._texte_zone()}"
        return None

    def libre(self) -> bool:
        return self.refus() is None
