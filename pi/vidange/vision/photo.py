"""Photos de mesure et photos d'alerte, prises dans la vidéo des caméras (tâche 12).

    photographe = Photographe(cameras, reglages.vision, registre)
    photo = photographe.mesure("plafond")     # à l'arrêt, après 0,3 s de stabilisation
    photo = photographe.derniere("dosage")    # tout de suite (photo d'une alerte)
    image = photo.image()                     # tableau numpy (BGR) pour OpenCV
    verifier_age(photo, 5, horloge)           # PhotoTropVieille si elle a plus de 5 s
    photographe.enregistrer(photo, "dose", seau="S1293")   # fichier + registre

Une photo de mesure est la première image arrivée après le temps de stabilisation : jamais
une image prise pendant un mouvement. Les photos gardées vont dans le dossier des photos du
registre (« photos/AAAA-MM-JJ/HHMMSS-camera.jpg »), qui garde leur chemin.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np

from vidange.cameras import ErreurCamera, Image
from vidange.journal import donner_journal
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import ReglagesVision

journal = donner_journal("vision")


class ErreurVision(Exception):
    """Photo impossible, illisible ou refusée : le message dit pourquoi."""


class PhotoTropVieille(ErreurVision):
    """Une décision ne se prend jamais sur une photo trop vieille."""


@dataclass(frozen=True)
class Photo:
    camera: str
    jpeg: bytes
    # Heure de réception (horloge du Pi qui ne recule jamais), et lisible.
    heure: float
    date: datetime
    _image: list[np.ndarray] = field(default_factory=list, repr=False, compare=False)

    def image(self) -> np.ndarray:
        """L'image décodée (couleurs BGR d'OpenCV) ; ErreurVision si le JPEG est illisible."""
        if not self._image:
            image = cv2.imdecode(np.frombuffer(self.jpeg, np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ErreurVision(f"photo de la caméra « {self.camera} » illisible (JPEG abîmé)")
            self._image.append(image)
        return self._image[0]


def photo_depuis_image(
    camera: str, image: np.ndarray, heure: float, date: datetime | None = None
) -> Photo:
    """Une photo faite d'une image (essais, images fabriquées)."""
    bon, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not bon:
        raise ErreurVision("image impossible à écrire en JPEG")
    photo = Photo(camera, jpeg.tobytes(), heure, date or datetime.now())
    photo._image.append(image)
    return photo


def verifier_age(photo: Photo, age_max_s: float, horloge: Callable[[], float]) -> None:
    age = horloge() - photo.heure
    if age > age_max_s:
        raise PhotoTropVieille(
            f"photo de la caméra « {photo.camera} » trop vieille ({age:.1f} s, au plus "
            f"{age_max_s:g} s) : refusée"
        )


class SourceImages(Protocol):
    """D'où viennent les images : les caméras (vidange.cameras.Cameras), ou des images
    fabriquées (essais)."""

    def derniere(self, nom: str) -> Image | None:
        """Dernière image de cette vidéo ; ErreurCamera si la vidéo est inconnue."""
        ...


class Photographe:
    def __init__(
        self,
        cameras: SourceImages,
        reglages: ReglagesVision,
        registre: Registre | None = None,
        dossier_photos: Path | None = None,
        horloge: Callable[[], float] = time.monotonic,
        attendre: Callable[[float], None] = time.sleep,
    ) -> None:
        """`dossier_photos` : sans registre, où écrire les photos gardées."""
        self.cameras = cameras
        self.reglages = reglages
        self.registre = registre
        if dossier_photos is None and registre is not None:
            dossier_photos = registre.dossier_photos
        self.dossier_photos = dossier_photos
        self._horloge = horloge
        self._attendre = attendre

    def _video(self, nom: str) -> str:
        camera = self.reglages.cameras.get(nom)
        if camera is None or camera.video is None:
            raise ErreurVision(f"caméra « {nom} » sans vidéo (vision.yaml → cameras)")
        return camera.video

    def mesure(self, nom: str) -> Photo:
        """Photo de mesure : la première image arrivée après la stabilisation."""
        video = self._video(nom)
        depart = self._horloge() + self.reglages.stabilisation_s
        self._attendre(self.reglages.stabilisation_s)
        fin = self._horloge() + self.reglages.delai_photo_s - self.reglages.stabilisation_s
        while True:
            try:
                image = self.cameras.derniere(video)
            except ErreurCamera as erreur:
                raise ErreurVision(str(erreur)) from None
            if image is not None and image.heure >= depart:
                return Photo(nom, image.donnees, image.heure, image.date)
            if self._horloge() > fin:
                raise ErreurVision(
                    f"caméra « {nom} » : pas d'image depuis {self.reglages.delai_photo_s:g} s "
                    "(caméra en panne ?)"
                )
            self._attendre(0.02)

    def derniere(self, nom: str) -> Photo:
        """La dernière image reçue, tout de suite (photo d'une alerte)."""
        video = self._video(nom)
        try:
            image = self.cameras.derniere(video)
        except ErreurCamera as erreur:
            raise ErreurVision(str(erreur)) from None
        if image is None:
            raise ErreurVision(f"caméra « {nom} » : aucune image reçue")
        return Photo(nom, image.donnees, image.heure, image.date)

    def enregistrer(self, photo: Photo, remarque: str, **objets: Any) -> Path | None:
        """Écrit la photo dans le dossier des photos et la note au registre (avec `objets` :
        cycle, fut, seau, bocal). Rend son chemin ; None si elle n'a pas pu être gardée (une
        photo manquante n'arrête jamais la machine)."""
        if self.dossier_photos is None:
            journal.warning("Photo « %s » pas gardée : pas de dossier des photos", remarque)
            return None
        jour = self.dossier_photos / photo.date.strftime("%Y-%m-%d")
        base = f"{photo.date.strftime('%H%M%S')}-{photo.camera}"
        chemin, numero = jour / f"{base}.jpg", 2
        try:
            jour.mkdir(parents=True, exist_ok=True)
            while chemin.exists():
                chemin, numero = jour / f"{base}-{numero}.jpg", numero + 1
            chemin.write_bytes(photo.jpeg)
        except OSError as erreur:
            journal.error("Photo « %s » pas gardée : %s", remarque, erreur)
            return None
        if self.registre is not None:
            try:
                self.registre.noter_photo(chemin, camera=photo.camera, remarque=remarque, **objets)
            except ErreurRegistre as erreur:
                journal.error("Photo « %s » : registre : %s", remarque, erreur)
        journal.info("Photo gardée (%s) : %s", remarque, chemin.name)
        return chemin
