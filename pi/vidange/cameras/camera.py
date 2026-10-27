"""Une caméra : sa vidéo lue en continu, sa dernière image et sa mémoire tournante.

    camera = Camera("plafond", "Caméra du plafond", ouvrir_commande(commande), reglages)
    camera.demarrer()
    camera.derniere()          # Image(numero, heure, date, donnees) ou None
    camera.age(numero)         # âge (s) d'une image encore en mémoire, ou None
    camera.memoire()           # les images des « memoire_s » dernières secondes (clip)
    camera.surveiller()        # appelée régulièrement : relance une caméra figée
    camera.arreter()

La vidéo vient d'une commande (rpicam-vid, ffmpeg...) qui écrit des images JPEG à la suite
sur sa sortie : aucune bibliothèque de plus, et une commande qui plante ne fait pas tomber le
programme. Elle est relancée seule si elle s'arrête, ou si elle n'envoie plus d'image.
"""

import os
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from vidange.cameras.mjpeg import Decoupeur
from vidange.journal import donner_journal
from vidange.reglages import ReglagesCameras


@dataclass(frozen=True)
class Image:
    # Numéro de l'image, qui augmente de 1 à chaque image de cette caméra.
    numero: int
    # Heure de réception (horloge du Pi qui ne recule jamais) : sert à dire si la vidéo est figée.
    heure: float
    # Heure de réception, lisible (pour les clips).
    date: datetime
    donnees: bytes


class Flux(Protocol):
    """La vidéo d'une caméra en train d'arriver."""

    def lire(self) -> bytes:
        """Attend des octets de la vidéo ; b"" : la vidéo est finie (commande arrêtée)."""
        ...

    def fermer(self) -> None:
        """Arrête la vidéo ; un `lire` en attente rend alors b"". Peut être appelée deux fois."""
        ...


class FluxCommande:
    """La vidéo écrite par une commande sur sa sortie."""

    def __init__(self, commande: list[str], journal_erreurs: Callable[[str], None]) -> None:
        self._processus = subprocess.Popen(
            commande, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        assert self._processus.stdout is not None and self._processus.stderr is not None
        self._sortie = self._processus.stdout
        erreurs = self._processus.stderr

        def lire_erreurs() -> None:
            # La commande parle sur sa sortie d'erreur (démarrage, caméra absente...).
            for ligne in erreurs:
                texte = ligne.decode("utf-8", errors="replace").strip()
                if texte:
                    journal_erreurs(texte)

        threading.Thread(target=lire_erreurs, name="camera-erreurs", daemon=True).start()

    def lire(self) -> bytes:
        return os.read(self._sortie.fileno(), 65536)

    def fermer(self) -> None:
        if self._processus.poll() is None:
            self._processus.terminate()
            try:
                self._processus.wait(2)
            except subprocess.TimeoutExpired:
                self._processus.kill()
                self._processus.wait()


class Camera:
    def __init__(
        self,
        nom: str,
        description: str,
        ouvrir: Callable[[], Flux],
        reglages: ReglagesCameras,
        horloge: Callable[[], float] = time.monotonic,
        maintenant: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.nom = nom
        self.description = description
        self.reglages = reglages
        self._ouvrir = ouvrir
        self._horloge = horloge
        self._maintenant = maintenant
        self._journal = donner_journal(f"cameras.{nom}")
        self._verrou = threading.Lock()
        self._images: deque[Image] = deque()
        self._numero = 0
        self._flux: Flux | None = None
        self._ouverte_a: float | None = None
        # Dernière chose dite par la commande ou par l'ouverture (pour la check-list).
        self.derniere_erreur = ""
        self.relances = 0
        self._arret = threading.Event()
        self._fil: threading.Thread | None = None

    @classmethod
    def depuis_commande(
        cls, nom: str, description: str, commande: list[str], reglages: ReglagesCameras
    ) -> "Camera":
        camera: Camera

        def ouvrir() -> Flux:
            return FluxCommande(commande, camera._noter_erreur)

        camera = cls(nom, description, ouvrir, reglages)
        return camera

    def _noter_erreur(self, texte: str) -> None:
        self.derniere_erreur = texte
        self._journal.debug("Caméra « %s » : %s", self.nom, texte)

    # ------------------------------------------------------------ marche / arrêt

    def demarrer(self) -> None:
        if self._fil is not None:
            return
        self._arret.clear()
        self._fil = threading.Thread(target=self._boucle, name=f"camera-{self.nom}", daemon=True)
        self._fil.start()

    def arreter(self) -> None:
        self._arret.set()
        with self._verrou:
            flux = self._flux
        if flux is not None:
            flux.fermer()
        if self._fil is not None:
            self._fil.join(5)
            self._fil = None

    def _boucle(self) -> None:
        while not self._arret.is_set():
            try:
                flux = self._ouvrir()
            except Exception as erreur:
                self._noter_erreur(f"lancement impossible : {erreur}")
                self._journal.warning("Caméra « %s » : lancement impossible (%s)", self.nom, erreur)
                self._arret.wait(self.reglages.relance_s)
                continue
            with self._verrou:
                self._flux = flux
                self._ouverte_a = self._horloge()
            if self._arret.is_set():
                flux.fermer()
            decoupeur = Decoupeur()
            try:
                while not self._arret.is_set():
                    donnees = flux.lire()
                    if not donnees:
                        break
                    for donnees_image in decoupeur.ajouter(donnees):
                        self._recevoir(donnees_image)
            except Exception as erreur:
                self._noter_erreur(f"lecture impossible : {erreur}")
            finally:
                flux.fermer()
                with self._verrou:
                    self._flux = None
            if not self._arret.is_set():
                self.relances += 1
                self._journal.warning(
                    "Caméra « %s » arrêtée (%s) : relance dans %g s",
                    self.nom,
                    self.derniere_erreur or "sans message",
                    self.reglages.relance_s,
                )
                self._arret.wait(self.reglages.relance_s)

    def _recevoir(self, donnees: bytes) -> None:
        heure = self._horloge()
        with self._verrou:
            self._numero += 1
            self._images.append(Image(self._numero, heure, self._maintenant(), donnees))
            limite = heure - self.reglages.memoire_s
            while self._images and self._images[0].heure < limite:
                self._images.popleft()

    # ------------------------------------------------------------ ce qu'on sait

    def derniere(self) -> Image | None:
        with self._verrou:
            return self._images[-1] if self._images else None

    def age(self, numero: int) -> float | None:
        """Âge (s) de l'image de ce numéro, ou None si elle n'est plus (ou pas) en mémoire."""
        with self._verrou:
            if not self._images:
                return None
            rang = numero - self._images[0].numero
            if not 0 <= rang < len(self._images):
                return None
            return self._horloge() - self._images[rang].heure

    def silence(self) -> float | None:
        """Depuis combien de temps (s) la caméra n'a pas envoyé d'image (None : jamais lancée)."""
        with self._verrou:
            depuis = self._images[-1].heure if self._images else self._ouverte_a
        return None if depuis is None else self._horloge() - depuis

    def memoire(self) -> list[Image]:
        with self._verrou:
            return list(self._images)

    def surveiller(self) -> None:
        """Une commande lancée mais muette depuis « figee_s » est arrêtée (puis relancée)."""
        with self._verrou:
            flux = self._flux
            depuis = self._images[-1].heure if self._images else None
            if self._ouverte_a is not None and (depuis is None or depuis < self._ouverte_a):
                depuis = self._ouverte_a
        if flux is None or depuis is None:
            return
        if self._horloge() - depuis > self.reglages.figee_s:
            self._noter_erreur(f"aucune image depuis {self.reglages.figee_s:g} s")
            self._journal.warning("Caméra « %s » figée : commande arrêtée", self.nom)
            flux.fermer()
