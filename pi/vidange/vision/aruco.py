"""Repères ArUco : le repère de 40 mm du lave-bocal, ceux du calibrage du plafond.

    reperes = chercher_reperes(image, "DICT_4X4_50")     # {numéro: Repere}
    7 in reperes                                          # le lave-bocal est vu

Un repère caché en partie, flou ou de travers au point de ne plus être lu n'est pas vu : pour
le lave-bocal, « pas vu » ne veut pas dire « absent » (vidange.vision.plafond décide).
"""

import math
from dataclasses import dataclass

import cv2
import numpy as np

Point = tuple[float, float]


@dataclass(frozen=True)
class Repere:
    numero: int
    # Coins dans l'image (points), dans l'ordre du repère.
    coins: tuple[Point, Point, Point, Point]
    centre: Point
    # Côté moyen (points) : sa taille dans l'image.
    cote_px: float


_DETECTEURS: dict[str, cv2.aruco.ArucoDetector] = {}


def _detecteur(dictionnaire: str) -> cv2.aruco.ArucoDetector:
    if dictionnaire not in _DETECTEURS:
        dico = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionnaire))
        _DETECTEURS[dictionnaire] = cv2.aruco.ArucoDetector(dico, cv2.aruco.DetectorParameters())
    return _DETECTEURS[dictionnaire]


def chercher_reperes(image: np.ndarray, dictionnaire: str) -> dict[int, Repere]:
    """Les repères vus dans l'image, par numéro."""
    gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    coins, numeros, _ = _detecteur(dictionnaire).detectMarkers(gris)
    reperes = {}
    if numeros is None:
        return reperes
    for quatre, numero in zip(coins, numeros.ravel(), strict=True):
        points = np.asarray(quatre, dtype=np.float64).reshape(4, 2)
        centre = points.mean(axis=0)
        cote = sum(math.dist(points[i], points[(i + 1) % 4]) for i in range(4)) / 4
        reperes[int(numero)] = Repere(
            int(numero),
            tuple((float(x), float(y)) for x, y in points),  # type: ignore[arg-type]
            (float(centre[0]), float(centre[1])),
            cote,
        )
    return reperes
