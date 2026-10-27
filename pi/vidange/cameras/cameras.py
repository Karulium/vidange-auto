"""Toutes les caméras de programme.yaml, et les clips des alarmes.

    cameras = Cameras(reglages.programme.cameras, dossier_donnees)
    cameras.demarrer()
    cameras.derniere("plafond")             # dernière image, pour la page web
    cameras.age("plafond", 1234)            # âge de l'image vue sur la page (vidéo figée ?)
    cameras.garder_clip("alarme")           # « clips/2026-10-27/153012 », ou None
    cameras.lister_clips() / cameras.index_du_clip(...) / cameras.image_du_clip(...)
    cameras.arreter()

Un clip = les « memoire_s » dernières secondes de chaque caméra, gardées dans
« donnees/clips/AAAA-MM-JJ/HHMMSS/ » : par caméra, un fichier « nom.mjpeg » (les images à la
suite, lisible par VLC) et son index « nom.json » (où commence chaque image, et son heure).
Les clips plus vieux que « clips_gardes_jours » sont effacés.
"""

import json
import re
import shutil
import threading
import time
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from vidange.cameras.camera import Camera, Flux, Image
from vidange.fiabilite.constats import Constat, lancer_boucle
from vidange.journal import donner_journal
from vidange.reglages import ReglagesCameras

journal = donner_journal("cameras")

DOSSIER_CLIPS = "clips"
# Un clip est désigné par « AAAA-MM-JJ_HHMMSS » (et « -2 », « -3 »... si deux à la même seconde).
FORME_CLIP = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{6}(?:-\d+)?)$")
SUJET = "caméras"
QUOI_FAIRE = (
    "Vérifier le câble de la caméra, puis sa commande dans programme.yaml (cameras → liste) : "
    "voir pi/systeme/essai-distance.md."
)


class ErreurCamera(Exception):
    """Caméra, clip ou image inconnus."""


class Cameras:
    def __init__(
        self,
        reglages: ReglagesCameras,
        dossier_donnees: Path,
        sources: Mapping[str, Callable[[], Flux]] | None = None,
        horloge: Callable[[], float] = time.monotonic,
        maintenant: Callable[[], datetime] = datetime.now,
    ) -> None:
        """`sources` : nom → ouverture de sa vidéo (fausses caméras) ; sinon, les commandes."""
        self.reglages = reglages
        self.dossier_clips = dossier_donnees / DOSSIER_CLIPS
        self.dossier_donnees = dossier_donnees
        self._maintenant = maintenant
        self.cameras: dict[str, Camera] = {}
        for nom, camera in reglages.liste.items():
            if sources is not None and nom in sources:
                self.cameras[nom] = Camera(
                    nom, camera.description, sources[nom], reglages, horloge, maintenant
                )
            else:
                self.cameras[nom] = Camera.depuis_commande(
                    nom, camera.description, camera.commande, reglages
                )
        self._verrou_clips = threading.Lock()
        self._arret = threading.Event()
        self._fil: threading.Thread | None = None

    # ------------------------------------------------------------ marche / arrêt

    def demarrer(self) -> None:
        for camera in self.cameras.values():
            camera.demarrer()
        self._arret.clear()
        periode = min(1.0, self.reglages.figee_s / 3)
        self._fil = lancer_boucle("cameras", periode, self.surveiller, self._arret)

    def surveiller(self) -> None:
        for camera in self.cameras.values():
            camera.surveiller()

    def arreter(self) -> None:
        self._arret.set()
        for camera in self.cameras.values():
            camera.arreter()
        if self._fil is not None:
            self._fil.join()
            self._fil = None

    # ------------------------------------------------------------ en direct

    def camera(self, nom: str) -> Camera:
        if nom not in self.cameras:
            raise ErreurCamera(f"caméra « {nom} » inconnue (programme.yaml → cameras → liste)")
        return self.cameras[nom]

    def derniere(self, nom: str) -> Image | None:
        return self.camera(nom).derniere()

    def age(self, nom: str, numero: int) -> float | None:
        """Âge (s) d'une image de cette caméra ; None si la caméra ou l'image est inconnue."""
        if nom not in self.cameras:
            return None
        return self.cameras[nom].age(numero)

    def decrire(self) -> list[dict[str, Any]]:
        """Pour la page web : chaque caméra et son état."""
        resultat = []
        for nom, camera in self.cameras.items():
            silence = camera.silence()
            resultat.append(
                {
                    "nom": nom,
                    "description": camera.description,
                    "marche": silence is not None and silence <= self.reglages.figee_s,
                    "silence_s": None if silence is None else round(silence, 1),
                    "erreur": camera.derniere_erreur,
                }
            )
        return resultat

    def constats(self) -> list[Constat]:
        """Pour la check-list. Sans caméra, la machine tourne : jamais bloquant."""
        if not self.cameras:
            return [
                Constat(
                    SUJET,
                    "attention",
                    "aucune caméra dans programme.yaml : ni vidéo, ni clip, ni pilotage à distance",
                    QUOI_FAIRE,
                )
            ]
        constats = []
        for camera in self.decrire():
            sujet = f"caméra {camera['nom']}"
            if camera["marche"]:
                constats.append(Constat(sujet, "ok", "la vidéo arrive"))
                continue
            texte = (
                "jamais lancée"
                if camera["silence_s"] is None
                else f"aucune image depuis {camera['silence_s']:g} s"
            )
            if camera["erreur"]:
                texte += f" ({camera['erreur']})"
            constats.append(Constat(sujet, "attention", texte, QUOI_FAIRE))
        return constats

    # ------------------------------------------------------------ clips

    def garder_clip(self, raison: str = "alarme") -> str | None:
        """Garde la mémoire tournante de chaque caméra. Rend le dossier du clip (relatif au
        dossier des données), ou None s'il n'y avait aucune image."""
        memoires = {nom: camera.memoire() for nom, camera in self.cameras.items()}
        if not any(memoires.values()):
            journal.warning("Pas de clip (%s) : aucune image en mémoire", raison)
            return None
        with self._verrou_clips:
            moment = self._maintenant()
            self._effacer_vieux_clips(moment.date())
            jour = self.dossier_clips / moment.strftime("%Y-%m-%d")
            base = moment.strftime("%H%M%S")
            dossier, numero = jour / base, 2
            while dossier.exists():
                dossier, numero = jour / f"{base}-{numero}", numero + 1
            dossier.mkdir(parents=True)
            resume: dict[str, Any] = {
                "date": moment.isoformat(timespec="seconds"),
                "raison": raison,
                "cameras": {},
            }
            for nom, images in memoires.items():
                if images:
                    self._ecrire_camera(dossier, nom, images)
                    resume["cameras"][nom] = {
                        "images": len(images),
                        "duree_s": round(images[-1].heure - images[0].heure, 1),
                    }
            (dossier / "clip.json").write_text(
                json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        relatif = dossier.relative_to(self.dossier_donnees).as_posix()
        journal.info("Clip gardé (%s) : %s", raison, relatif)
        return relatif

    def _ecrire_camera(self, dossier: Path, nom: str, images: list[Image]) -> None:
        index = []
        decalage = 0
        with (dossier / f"{nom}.mjpeg").open("wb") as fichier:
            for image in images:
                fichier.write(image.donnees)
                index.append(
                    [decalage, len(image.donnees), image.date.isoformat(timespec="milliseconds")]
                )
                decalage += len(image.donnees)
        description = self.cameras[nom].description
        (dossier / f"{nom}.json").write_text(
            json.dumps({"camera": nom, "description": description, "images": index}),
            encoding="utf-8",
        )

    def _effacer_vieux_clips(self, aujourdhui: date) -> None:
        limite = aujourdhui - timedelta(days=self.reglages.clips_gardes_jours)
        if not self.dossier_clips.is_dir():
            return
        for jour in self.dossier_clips.iterdir():
            try:
                quand = date.fromisoformat(jour.name)
            except ValueError:
                continue
            if quand < limite and jour.is_dir():
                shutil.rmtree(jour, ignore_errors=True)
                journal.info("Vieux clips effacés : %s", jour.name)

    def _dossier_clip(self, clip: str) -> Path:
        forme = FORME_CLIP.match(clip)
        dossier = None
        if forme is not None:
            dossier = self.dossier_clips / forme.group(1) / forme.group(2)
        if dossier is None or not (dossier / "clip.json").is_file():
            raise ErreurCamera(f"clip « {clip} » inconnu")
        return dossier

    def lister_clips(self, limite: int, avant: str | None = None) -> list[dict[str, Any]]:
        """Les derniers clips, du plus récent au plus ancien (« avant » : page suivante)."""
        if not self.dossier_clips.is_dir():
            return []
        noms = sorted(
            (
                f"{jour.name}_{dossier.name}"
                for jour in self.dossier_clips.iterdir()
                if jour.is_dir()
                for dossier in jour.iterdir()
                if (dossier / "clip.json").is_file()
            ),
            reverse=True,
        )
        if avant is not None:
            noms = [nom for nom in noms if nom < avant]
        clips = []
        for nom in noms[:limite]:
            try:
                resume = json.loads((self._dossier_clip(nom) / "clip.json").read_text("utf-8"))
            except (OSError, ValueError) as erreur:
                resume = {"erreur": f"clip illisible : {erreur}"}
            clips.append({"clip": nom, **resume})
        return clips

    def index_du_clip(self, clip: str, camera: str) -> list[list[Any]]:
        """[décalage, longueur, heure] de chaque image d'une caméra du clip."""
        if not re.fullmatch(r"[a-z][a-z0-9_]*", camera):
            raise ErreurCamera(f"caméra « {camera} » inconnue")
        chemin = self._dossier_clip(clip) / f"{camera}.json"
        if not chemin.is_file():
            raise ErreurCamera(f"pas de caméra « {camera} » dans le clip « {clip} »")
        return json.loads(chemin.read_text("utf-8"))["images"]

    def image_du_clip(self, clip: str, camera: str, rang: int) -> bytes:
        index = self.index_du_clip(clip, camera)
        if not 0 <= rang < len(index):
            raise ErreurCamera(f"image n° {rang} absente du clip « {clip} » ({camera})")
        decalage, longueur, _ = index[rang]
        with (self._dossier_clip(clip) / f"{camera}.mjpeg").open("rb") as fichier:
            fichier.seek(decalage)
            return fichier.read(longueur)
