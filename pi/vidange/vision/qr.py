"""Lecture des QR (« S1293 », « B327 »...) : le code, sa place et son angle.

    codes = lire_codes(image, reglages.vision.qr)        # dans l'image (points, ° vus à l'écran)
    codes = lire_vue(Vue(image, calibration, pose, z_plan), reglages.vision.qr)   # + portique
    lecture = lire_avec_reprises(photographier, reglages.vision.qr, attendus=12)
    marquer_a_verifier(registre, "bocal", "B327", "QR illisible")

Le QR donne aussi l'angle de l'objet (repère d'angle, plan v181) : angle du QR (son bord du
haut, de gauche à droite) + `angle_objet_deg`.

Un QR illisible : deuxième tour (même hauteur), puis photo de secours à une autre hauteur, sinon
l'objet est marqué « à vérifier » au registre (par qui connaît son code : le registre sait quel
bocal est à cette place).
"""

import math
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from typing import Literal

import cv2
import numpy as np

from vidange.journal import donner_journal
from vidange.registre import ErreurRegistre, Registre
from vidange.registre.base import Sorte
from vidange.reglages import QrVision
from vidange.vision.calibration import (
    Calibration,
    PoseCamera,
    angle_vers_portique,
    vers_portique,
)

journal = donner_journal("vision.qr")

Point = tuple[float, float]
Hauteur = Literal["normale", "secours"]


@dataclass(frozen=True)
class CodeLu:
    code: str
    # Coins dans l'image (haut gauche, haut droit, bas droit, bas gauche du QR), en points.
    coins: tuple[Point, Point, Point, Point]
    centre: Point
    # Angle du bord haut du QR vu à l'écran (°, sens inverse des aiguilles d'une montre).
    angle_image_deg: float
    # Dans le repère du portique (si la vue le permet) : centre (m) et angle de l'objet (°).
    position: Point | None = None
    angle_deg: float | None = None


@dataclass(frozen=True)
class Vue:
    """Une photo et de quoi la mettre dans le repère du portique."""

    image: np.ndarray
    calibration: Calibration | None = None
    pose: PoseCamera | None = None
    # Hauteur du plan des QR (m).
    z_plan: float = 0.0


def _gris(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image


def _versions(gris: np.ndarray) -> Iterator[tuple[np.ndarray, float]]:
    """L'image telle quelle, puis des versions qui aident un QR difficile (petite, floue, mal
    éclairée) : (image, agrandissement). Calculées à la demande."""
    yield gris, 1.0
    nette = cv2.addWeighted(gris, 1.8, cv2.GaussianBlur(gris, (0, 0), 3), -0.8, 0)
    yield nette, 1.0
    _, seuil = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield seuil, 1.0
    if max(gris.shape) < 2000:
        yield cv2.resize(gris, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC), 2.0


def _angle_image(coins: np.ndarray) -> float:
    (x0, y0), (x1, y1) = coins[0], coins[1]
    return math.degrees(math.atan2(-(y1 - y0), x1 - x0))


def lire_codes(image: np.ndarray, reglages: QrVision, rapide: bool = False) -> list[CodeLu]:
    """Tous les QR lus dans l'image (un code n'y est qu'une fois). Un QR d'une autre forme que
    celle des codes du registre est ignoré. `rapide` : une version de l'image où l'on ne voit
    même pas de QR n'est pas décodée, et on s'arrête à la première version qui a donné des QR
    (images qui se suivent, pendant qu'un seau tourne : la caméra du micropore)."""
    forme = re.compile(reglages.forme)
    detecteur = cv2.QRCodeDetector()
    trouves: dict[str, CodeLu] = {}
    for version, echelle in _versions(_gris(image)):
        if rapide and trouves:
            break
        try:
            if rapide and not detecteur.detect(version)[0]:
                continue
            ok, textes, points, _ = detecteur.detectAndDecodeMulti(version)
        except cv2.error:
            continue
        if not ok or points is None:
            continue
        for texte, coins in zip(textes, points, strict=False):
            texte = texte.strip()
            if not texte or texte in trouves:
                continue
            if not forme.fullmatch(texte):
                journal.warning("QR « %s » ignoré : pas de la forme des codes du registre", texte)
                continue
            coins = np.asarray(coins, dtype=np.float64).reshape(4, 2) / echelle
            centre = coins.mean(axis=0)
            trouves[texte] = CodeLu(
                texte,
                tuple((float(x), float(y)) for x, y in coins),  # type: ignore[arg-type]
                (float(centre[0]), float(centre[1])),
                _angle_image(coins),
            )
    return list(trouves.values())


def _angle(angle: float) -> float:
    return (angle + 180) % 360 - 180


def lire_vue(vue: Vue, reglages: QrVision) -> list[CodeLu]:
    """Les QR de la photo, avec leur place et l'angle de l'objet dans le repère du portique."""
    codes = lire_codes(vue.image, reglages)
    if vue.calibration is None or vue.pose is None:
        return codes
    taille = (vue.image.shape[1], vue.image.shape[0])
    calibration = vue.calibration.a_la_taille(taille)
    resultat = []
    for code in codes:
        position = vers_portique([code.centre], calibration, vue.pose, vue.z_plan)[0]
        angle = angle_vers_portique(code.coins[0], code.coins[1], calibration, vue.pose)
        resultat.append(
            replace(code, position=position, angle_deg=_angle(angle + reglages.angle_objet_deg))
        )
    return resultat


@dataclass(frozen=True)
class Lecture:
    codes: list[CodeLu]
    # Photos prises (première, deuxième tour, secours).
    photos: int
    # Tous les QR attendus ont été lus.
    complete: bool


def lire_avec_reprises(
    photographier: Callable[[Hauteur], Vue], reglages: QrVision, attendus: int = 1
) -> Lecture:
    """Lit `attendus` QR : première photo, deuxième tour (même hauteur), puis photo de secours
    (`photographier("secours")` : une autre hauteur). Les codes lus s'ajoutent d'une photo à
    l'autre ; s'il en manque encore, la lecture n'est pas complète (à l'appelant de marquer
    l'objet « à vérifier »)."""
    trouves: dict[str, CodeLu] = {}
    hauteurs: list[Hauteur] = ["normale"] * reglages.essais_meme_hauteur + ["secours"]
    photos = 0
    for hauteur in hauteurs:
        photos += 1
        for code in lire_vue(photographier(hauteur), reglages):
            trouves.setdefault(code.code, code)
        if len(trouves) >= attendus:
            return Lecture(list(trouves.values()), photos, True)
        journal.info(
            "QR : %d lus sur %d (photo n° %d, %s)", len(trouves), attendus, photos, hauteur
        )
    return Lecture(list(trouves.values()), photos, False)


def marquer_a_verifier(registre: Registre | None, sorte: Sorte, code: str, raison: str) -> None:
    """L'objet est marqué « à vérifier » au registre (sa raison) ; une erreur du registre ne
    fait que passer au journal."""
    journal.warning("%s %s à vérifier : %s", sorte, code, raison)
    if registre is None:
        return
    try:
        registre.objet(sorte, code, a_verifier=raison)
    except ErreurRegistre as erreur:
        journal.error("Registre : %s", erreur)
