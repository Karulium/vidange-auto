"""Images fabriquées par OpenCV : QR, repères ArUco, mire en damier, et scènes qui les posent
sur un fond (tournés, flous, cachés). Elles servent aux tests, au simulateur, et à imprimer la
mire et les repères (« vidange-vision fabriquer »).

    qr = image_qr("S1293")                          # gris, noir sur blanc
    repere = image_aruco("DICT_4X4_50", 7)
    damier = image_damier(9, 6)                     # 9 × 6 coins intérieurs
    scene = poser(fond(800, 600), [(qr, (200, 300), 30)])   # QR tourné de 30°
"""

import cv2
import numpy as np


def image_qr(code: str, case_px: int = 8, marge_cases: int = 4) -> np.ndarray:
    """Le QR du code, noir sur blanc (une case du QR = case_px points)."""
    qr = cv2.QRCodeEncoder.create().encode(code)
    qr = cv2.resize(qr, None, fx=case_px, fy=case_px, interpolation=cv2.INTER_NEAREST)
    marge = marge_cases * case_px
    return cv2.copyMakeBorder(qr, marge, marge, marge, marge, cv2.BORDER_CONSTANT, value=255)


def image_aruco(dictionnaire: str, numero: int, taille_px: int = 200, marge_px: int = 40):
    """Le repère ArUco `numero` du dictionnaire (nom OpenCV, « DICT_4X4_50 »)."""
    dico = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionnaire))
    repere = cv2.aruco.generateImageMarker(dico, numero, taille_px)
    return cv2.copyMakeBorder(
        repere, marge_px, marge_px, marge_px, marge_px, cv2.BORDER_CONSTANT, value=255
    )


def image_damier(colonnes: int, lignes: int, case_px: int = 60) -> np.ndarray:
    """Mire en damier : colonnes × lignes coins intérieurs (une case de plus de chaque côté)."""
    cases = np.indices((lignes + 1, colonnes + 1)).sum(axis=0) % 2
    damier = np.where(cases == 0, 0, 255).astype(np.uint8)
    damier = cv2.resize(damier, None, fx=case_px, fy=case_px, interpolation=cv2.INTER_NEAREST)
    return cv2.copyMakeBorder(
        damier, case_px, case_px, case_px, case_px, cv2.BORDER_CONSTANT, value=255
    )


def fond(largeur: int, hauteur: int, gris: int = 170) -> np.ndarray:
    """Un fond gris uni (couleurs BGR)."""
    return np.full((hauteur, largeur, 3), gris, np.uint8)


def poser(
    image: np.ndarray, objets: list[tuple[np.ndarray, tuple[float, float], float]]
) -> np.ndarray:
    """Pose chaque objet (image grise, centre en points, angle en ° dans le sens inverse des
    aiguilles d'une montre, vu sur l'écran) sur une copie de l'image."""
    scene = image.copy()
    hauteur, largeur = scene.shape[:2]
    for objet, (cx, cy), angle in objets:
        h, w = objet.shape[:2]
        matrice = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        matrice[0, 2] += cx - w / 2
        matrice[1, 2] += cy - h / 2
        couleur = cv2.cvtColor(objet, cv2.COLOR_GRAY2BGR) if objet.ndim == 2 else objet
        tourne = cv2.warpAffine(couleur, matrice, (largeur, hauteur), flags=cv2.INTER_LINEAR)
        masque = cv2.warpAffine(np.full((h, w), 255, np.uint8), matrice, (largeur, hauteur))
        scene[masque > 127] = tourne[masque > 127]
    return scene


def flouter(image: np.ndarray, rayon_px: int) -> np.ndarray:
    """Flou d'une photo pas nette (rayon en points)."""
    taille = 2 * rayon_px + 1
    return cv2.GaussianBlur(image, (taille, taille), 0)


def cacher(image: np.ndarray, coin: tuple[int, int], taille: tuple[int, int]) -> np.ndarray:
    """Un objet sombre posé devant une partie de l'image (vue cachée)."""
    cachee = image.copy()
    x, y = coin
    cv2.rectangle(cachee, (x, y), (x + taille[0], y + taille[1]), (60, 60, 60), -1)
    return cachee


def vues_de_mire(
    colonnes: int, lignes: int, taille: tuple[int, int] = (1280, 720), focale_px: float = 800
) -> list[np.ndarray]:
    """Photos d'une mire en damier vue sous 12 angles par une caméra parfaite (sans
    déformation, focale donnée) : pour essayer la calibration sans caméra."""
    mire = image_damier(colonnes, lignes, 40)
    h, w = mire.shape
    k = np.array([[focale_px, 0, taille[0] / 2], [0, focale_px, taille[1] / 2], [0, 0, 1.0]])
    coins_m = np.array([[0, 0, 0], [w, 0, 0], [w, h, 0], [0, h, 0]], np.float64) * 0.001
    tournes = (
        (0, 0, 0), (0.3, 0, 0), (-0.3, 0.1, 0.2), (0, 0.35, -0.1), (0.2, -0.3, 0.4),
        (-0.25, -0.25, -0.3), (0.1, 0.4, 0), (0.35, 0.2, 0.1), (-0.1, -0.4, 0.2),
        (0.3, -0.1, -0.4), (0, 0, 0.5), (-0.3, 0.3, 0),
    )  # fmt: skip
    vues = []
    for rotation in tournes:
        deplacement = np.array([-w / 2 * 0.001, -h / 2 * 0.001, 0.9])
        projetes, _ = cv2.projectPoints(
            coins_m, np.array(rotation, np.float64), deplacement, k, None
        )
        matrice = cv2.getPerspectiveTransform(
            np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(projetes.reshape(4, 2))
        )
        vue = cv2.warpPerspective(mire, matrice, taille, borderValue=170)
        vues.append(cv2.cvtColor(vue, cv2.COLOR_GRAY2BGR))
    return vues
