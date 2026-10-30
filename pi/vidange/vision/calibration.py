"""Calibration des caméras (mire en damier) et passage d'un point de l'image au repère du
portique.

    coins = trouver_damier(image, 9, 6)                  # None si le damier n'est pas vu
    calibration = calculer(images, reglages.vision.calibration)
    enregistrer(calibration, chemin) / charger(chemin)
    calibration = sans_calibration((102, 67), (1280, 720))   # grossier : le champ de vision
    points = vers_portique([(640, 360)], calibration, PoseCamera(1.45, 0.50, 2.35, 0), 0.75)

Une caméra regarde vers le bas. `PoseCamera` dit où est son objectif (repère du portique, m)
et l'angle du bord haut de l'image avec l'axe x. Un point vu dans l'image est sur un plan
horizontal de hauteur connue (`z_plan` : le dessus des couvercles...) : la calibration
corrige la déformation du grand angle, puis la distance au plan donne l'échelle.
"""

import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from vidange.reglages import CalibrationVision, CameraVision
from vidange.vision.photo import ErreurVision

Point = tuple[float, float]


@dataclass(frozen=True)
class Calibration:
    # Matrice de la caméra (fx, 0, cx / 0, fy, cy / 0, 0, 1) et déformation (OpenCV).
    matrice: tuple[tuple[float, float, float], ...]
    distorsion: tuple[float, ...]
    # Taille des images calibrées (points).
    taille: tuple[int, int]
    # Erreur moyenne (points) ; None : pas de vraie calibration (champ de vision seul).
    erreur_px: float | None

    @property
    def k(self) -> np.ndarray:
        return np.array(self.matrice, dtype=np.float64)

    @property
    def d(self) -> np.ndarray:
        return np.array(self.distorsion, dtype=np.float64)

    def a_la_taille(self, taille: tuple[int, int]) -> "Calibration":
        """La même calibration pour des images d'une autre taille (même cadrage)."""
        if taille == self.taille:
            return self
        sx, sy = taille[0] / self.taille[0], taille[1] / self.taille[1]
        k = self.k
        k[0] *= sx
        k[1] *= sy
        return Calibration(
            tuple(tuple(float(v) for v in ligne) for ligne in k),
            self.distorsion,
            taille,
            self.erreur_px,
        )


@dataclass(frozen=True)
class PoseCamera:
    x: float
    y: float
    # Hauteur de l'objectif (m).
    z: float
    # Angle (°) du bord haut de l'image (de gauche à droite) avec l'axe x du portique.
    angle_deg: float = 0.0


def sans_calibration(champ_deg: tuple[float, float], taille: tuple[int, int]) -> Calibration:
    """Calibration grossière tirée du champ de vision (aucune déformation corrigée)."""
    largeur, hauteur = taille
    fx = (largeur / 2) / math.tan(math.radians(champ_deg[0]) / 2)
    fy = (hauteur / 2) / math.tan(math.radians(champ_deg[1]) / 2)
    matrice = ((fx, 0.0, largeur / 2), (0.0, fy, hauteur / 2), (0.0, 0.0, 1.0))
    return Calibration(matrice, (0.0, 0.0, 0.0, 0.0, 0.0), taille, None)


def _gris(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image


def trouver_damier(image: np.ndarray, colonnes: int, lignes: int) -> np.ndarray | None:
    """Les coins intérieurs du damier, précis au dixième de point ; None s'il n'est pas vu."""
    gris = _gris(image)
    trouve, coins = cv2.findChessboardCorners(
        gris, (colonnes, lignes), cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
    )
    if not trouve:
        return None
    critere = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.01)
    return cv2.cornerSubPix(gris, coins, (5, 5), (-1, -1), critere)


def calculer(images: Sequence[np.ndarray], reglages: CalibrationVision) -> Calibration:
    """La calibration d'après les photos de la mire ; ErreurVision si elle est mauvaise."""
    if not images:
        raise ErreurVision("calibration : aucune photo")
    taille = (images[0].shape[1], images[0].shape[0])
    modele = np.zeros((reglages.lignes * reglages.colonnes, 3), np.float32)
    modele[:, :2] = np.mgrid[0 : reglages.colonnes, 0 : reglages.lignes].T.reshape(-1, 2)
    modele *= reglages.case_m
    points_mire, points_image = [], []
    for image in images:
        if (image.shape[1], image.shape[0]) != taille:
            raise ErreurVision("calibration : photos de tailles différentes")
        coins = trouver_damier(image, reglages.colonnes, reglages.lignes)
        if coins is not None:
            points_mire.append(modele)
            points_image.append(coins)
    if len(points_image) < reglages.photos_min:
        raise ErreurVision(
            f"calibration : damier trouvé sur {len(points_image)} photos sur {len(images)}, il "
            f"en faut {reglages.photos_min} (mire bien éclairée, entière dans l'image, nette)"
        )
    erreur, k, d, _, _ = cv2.calibrateCamera(points_mire, points_image, taille, None, None)
    if erreur > reglages.erreur_max_px:
        raise ErreurVision(
            f"calibration refusée : erreur moyenne {erreur:.2f} points (au plus "
            f"{reglages.erreur_max_px:g}) ; refaire les photos, mire bien à plat"
        )
    return Calibration(
        tuple(tuple(float(v) for v in ligne) for ligne in k),
        tuple(float(v) for v in d.ravel()),
        taille,
        float(erreur),
    )


def enregistrer(calibration: Calibration, chemin: Path) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(asdict(calibration), indent=1), encoding="utf-8")


def charger(chemin: Path) -> Calibration:
    try:
        valeurs = json.loads(chemin.read_text(encoding="utf-8"))
        return Calibration(
            tuple(tuple(float(v) for v in ligne) for ligne in valeurs["matrice"]),
            tuple(float(v) for v in valeurs["distorsion"]),
            (int(valeurs["taille"][0]), int(valeurs["taille"][1])),
            None if valeurs["erreur_px"] is None else float(valeurs["erreur_px"]),
        )
    except (OSError, ValueError, KeyError, TypeError, IndexError) as erreur:
        raise ErreurVision(f"fichier de calibration illisible ({chemin}) : {erreur}") from None


def calibration_de(camera: CameraVision, dossier: Path, taille: tuple[int, int]) -> Calibration:
    """La calibration d'une caméra pour des images de cette taille : son fichier s'il existe,
    sinon le champ de vision (mesure grossière)."""
    if camera.calibration is not None and (dossier / camera.calibration).is_file():
        return charger(dossier / camera.calibration).a_la_taille(taille)
    return sans_calibration(camera.champ_deg, taille)


def redresser(image: np.ndarray, calibration: Calibration) -> np.ndarray:
    """L'image sans la déformation du grand angle."""
    taille = (image.shape[1], image.shape[0])
    calibration = calibration.a_la_taille(taille)
    return cv2.undistort(image, calibration.k, calibration.d)


def _normaliser(points: Sequence[Point], calibration: Calibration) -> np.ndarray:
    tableau = np.array(points, dtype=np.float64).reshape(-1, 1, 2)
    return cv2.undistortPoints(tableau, calibration.k, calibration.d).reshape(-1, 2)


def _axes(pose: PoseCamera) -> tuple[np.ndarray, np.ndarray]:
    """Directions (repère du portique, vues de dessus) des axes u (vers la droite) et v (vers le
    bas) de l'image, pour une caméra qui regarde vers le bas."""
    angle = math.radians(pose.angle_deg)
    c, s = math.cos(angle), math.sin(angle)
    return np.array([c, s]), np.array([s, -c])


def vers_portique(
    points: Sequence[Point], calibration: Calibration, pose: PoseCamera, z_plan: float
) -> list[Point]:
    """Les points de l'image (en points) → (x, y) du portique, sur le plan de hauteur z_plan."""
    distance = pose.z - z_plan
    if distance <= 0:
        raise ErreurVision(f"plan à {z_plan:g} m pas sous l'objectif ({pose.z:g} m)")
    u, v = _axes(pose)
    resultat = []
    for xn, yn in _normaliser(points, calibration):
        x, y = np.array([pose.x, pose.y]) + distance * (xn * u + yn * v)
        resultat.append((float(x), float(y)))
    return resultat


def angle_vers_portique(debut: Point, fin: Point, calibration: Calibration, pose: PoseCamera):
    """Angle (°, de -180 à 180) dans le repère du portique de la flèche début → fin vue dans
    l'image."""
    (x0, y0), (x1, y1) = _normaliser([debut, fin], calibration)
    u, v = _axes(pose)
    direction = (x1 - x0) * u + (y1 - y0) * v
    return math.degrees(math.atan2(direction[1], direction[0]))
