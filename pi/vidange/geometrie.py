"""Petits calculs de géométrie vue de dessus (repère du portique, en mètres).

Une forme est une liste de points (x, y) : un polygone convexe (sommets dans l'ordre) ou un
segment (2 points).
"""

from collections.abc import Sequence

Point = tuple[float, float]
Forme = Sequence[Point]

# Recouvrement sous lequel deux formes ne se touchent pas (m) : bord contre bord est permis.
_EGAL = 1e-6


def _projection(points: Sequence[Point], axe: Point) -> tuple[float, float]:
    valeurs = [x * axe[0] + y * axe[1] for x, y in points]
    return min(valeurs), max(valeurs)


def touche_rectangle(forme: Forme, x: tuple[float, float], y: tuple[float, float]) -> bool:
    """La forme convexe recouvre-t-elle le rectangle x × y ?

    Deux formes convexes ne se touchent pas si une droite les sépare : on essaie les côtés du
    rectangle et ceux de la forme.
    """
    coins = [(x[0], y[0]), (x[1], y[0]), (x[1], y[1]), (x[0], y[1])]
    axes = [(1.0, 0.0), (0.0, 1.0)]
    for i, (ax, ay) in enumerate(forme):
        bx, by = forme[(i + 1) % len(forme)]
        if (ax, ay) != (bx, by):
            axes.append((ay - by, bx - ax))
    for axe in axes:
        norme = (axe[0] ** 2 + axe[1] ** 2) ** 0.5
        axe = (axe[0] / norme, axe[1] / norme)
        debut_forme, fin_forme = _projection(forme, axe)
        debut_rect, fin_rect = _projection(coins, axe)
        if fin_forme <= debut_rect + _EGAL or fin_rect <= debut_forme + _EGAL:
            return False
    return True
