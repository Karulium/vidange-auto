"""Fausse caméra, pour les tests et le simulateur.

    fausse = FausseCamera(images_par_s=20)
    camera = Camera("plafond", "essai", fausse.ouvrir, reglages)
    fausse.figee = True      # la commande tourne mais n'envoie plus rien
    fausse.en_panne = True   # la commande ne se lance plus (caméra débranchée)

Ses images sont de vraies images JPEG pour le découpage (début, morceaux, fin), avec un
texte dedans, mais pas des photos : un navigateur ne sait pas les afficher.
"""

import threading

from vidange.cameras.mjpeg import DEBUT


def fausse_image(texte: str) -> bytes:
    """Une image JPEG minimale : un commentaire (le texte), des données, la fin."""
    commentaire = texte.encode("utf-8")[:1000]
    return (
        DEBUT
        + b"\xff\xfe"
        + (len(commentaire) + 2).to_bytes(2, "big")
        + commentaire
        # Données de l'image, avec un FF suivi de 00 comme dans une vraie.
        + b"\xff\xda\x00\x02\x12\xff\x00\x34"
        + b"\xff\xd9"
    )


class FausseCamera:
    def __init__(self, nom: str = "fausse", images_par_s: float = 20) -> None:
        self.nom = nom
        self.images_par_s = images_par_s
        self.figee = False
        self.en_panne = False
        self.ouvertures = 0
        self.envoyees = 0

    def ouvrir(self) -> "FauxFlux":
        if self.en_panne:
            raise OSError(f"fausse caméra « {self.nom} » : introuvable")
        self.ouvertures += 1
        return FauxFlux(self)


class FauxFlux:
    def __init__(self, camera: FausseCamera) -> None:
        self.camera = camera
        self._ferme = threading.Event()

    def lire(self) -> bytes:
        if self._ferme.wait(1 / self.camera.images_par_s):
            return b""
        while self.camera.figee:
            if self._ferme.wait(0.01):
                return b""
        self.camera.envoyees += 1
        return fausse_image(f"{self.camera.nom} {self.camera.envoyees}")

    def fermer(self) -> None:
        self._ferme.set()
