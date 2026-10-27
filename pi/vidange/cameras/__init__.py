"""Caméras (tâche 12) : vidéo en direct pour la page web, mémoire tournante et clips d'alarme."""

from vidange.cameras.camera import Camera, Flux, FluxCommande, Image
from vidange.cameras.cameras import DOSSIER_CLIPS, Cameras, ErreurCamera
from vidange.cameras.faux import FausseCamera, fausse_image
from vidange.cameras.mjpeg import Decoupeur

__all__ = [
    "DOSSIER_CLIPS",
    "Camera",
    "Cameras",
    "Decoupeur",
    "ErreurCamera",
    "FausseCamera",
    "Flux",
    "FluxCommande",
    "Image",
    "fausse_image",
]
