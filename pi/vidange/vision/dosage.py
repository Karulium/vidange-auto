"""La caméra du dosage sur son servo DS3225 (docs/decisions.md, règle 2) : 0° = bocal,
63° = seau.

    camera = CameraDosage(reglages.machine, photographe, ServoPwm(reglages.machine.camera_dosage),
                          agitateur_gare=mycelium.camera_peut_pivoter,
                          griffe_hors_boite=griffe.hors_boite_camera_dosage,
                          prehension_hors_boite=prehension.hors_boite_camera_dosage)
    camera.ranger()                           # au démarrage : vers le bocal (verrou vérifié)
    camera.pivote()                           # pour la griffe et la préhension (leur verrou)
    camera.photo("saut de poids")             # photo d'une alerte, tout de suite, sans pivoter
    camera.commencer_photo_seau("S1293", 2, "B327", 150.0, cycle)   # après chaque dose
    camera.photo_seau_finie()

Elle pivote SEULEMENT si l'agitateur est garé (bocal x ≤ 0,62) ET si griffe et préhension sont
hors de la boîte x < 1,10, y < 0,34, z 0,95-1,08 ; pendant qu'elle pivote, griffe et préhension
refusent d'y entrer, et l'agitateur attend la fin de la photo (étape du Mycélium) : elle est
revenue avant le retour de l'agitateur ou du godet.

Le servo ne dit pas où il est : la caméra est dite « pivotée » depuis l'ordre de tourner vers
le seau jusqu'à `pivot_s` après l'ordre de revenir au bocal, et tant qu'elle n'a pas été rangée
une première fois (position inconnue). Une photo du seau manquée (verrou, caméra en panne) ne
fait que passer au journal : elle n'arrête jamais la machine.
"""

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from vidange.journal import donner_journal
from vidange.reglages import CameraDosage as ReglagesCameraDosage
from vidange.reglages import Machine
from vidange.vision.photo import ErreurVision, Photographe

journal = donner_journal("vision.dosage")


class Servo(Protocol):
    def tourner(self, angle_deg: float) -> None:
        """Envoie l'ordre (le servo ne répond pas) ; OSError si la sortie ne marche pas."""
        ...


def impulsion_us(reglages: ReglagesCameraDosage, angle_deg: float) -> float:
    (a0, a1), (u0, u1) = reglages.impulsion.angles_deg, reglages.impulsion.us
    return u0 + (angle_deg - a0) * (u1 - u0) / (a1 - a0)


class ServoPwm:
    """Le servo sur une sortie PWM matérielle du Pi 5 (fichiers de Linux, aucune bibliothèque)."""

    def __init__(self, reglages: ReglagesCameraDosage) -> None:
        self.reglages = reglages
        self._puce = Path(reglages.pwm.fichier)
        self._canal = self._puce / f"pwm{reglages.pwm.canal}"
        self._pret = False

    def _ecrire(self, chemin: Path, valeur: int) -> None:
        chemin.write_text(f"{valeur}\n")

    def _preparer(self) -> None:
        if not self._canal.exists():
            self._ecrire(self._puce / "export", self.reglages.pwm.canal)
            # Linux crée le dossier du canal un instant après.
            for _ in range(50):
                if (self._canal / "period").exists():
                    break
                time.sleep(0.01)
        self._ecrire(self._canal / "period", self.reglages.pwm.periode_us * 1000)
        self._pret = True

    def tourner(self, angle_deg: float) -> None:
        if not self._pret:
            self._preparer()
        duree_ns = round(impulsion_us(self.reglages, angle_deg) * 1000)
        self._ecrire(self._canal / "duty_cycle", duree_ns)
        self._ecrire(self._canal / "enable", 1)


class FauxServo:
    """Pour les tests et le simulateur : garde les angles demandés."""

    def __init__(self) -> None:
        self.angles: list[float] = []
        self.en_panne = False

    def tourner(self, angle_deg: float) -> None:
        if self.en_panne:
            raise OSError("faux servo en panne")
        self.angles.append(angle_deg)


class CameraDosage:
    def __init__(
        self,
        machine: Machine,
        photographe: Photographe | None,
        servo: Servo,
        agitateur_gare: Callable[[], bool],
        griffe_hors_boite: Callable[[], bool],
        prehension_hors_boite: Callable[[], bool],
        attendre: Callable[[float], None] = time.sleep,
        en_fond: bool = True,
    ) -> None:
        """`en_fond` : la photo du seau se fait dans un fil à part (le chef n'attend pas) ;
        faux : tout de suite (tests)."""
        assert machine.camera_dosage is not None
        self.reglages = machine.camera_dosage
        self.photographe = photographe
        self.servo = servo
        self._verrous = (
            ("agitateur du mycélium pas garé", agitateur_gare),
            ("griffe dans la boîte de la caméra du dosage", griffe_hors_boite),
            ("préhension dans la boîte de la caméra du dosage", prehension_hors_boite),
        )
        self._attendre = attendre
        self._en_fond = en_fond
        # Position du servo inconnue tant qu'il n'a pas été rangé : comptée comme pivotée.
        self._pivote = True
        self._fil: threading.Thread | None = None
        self.photos_du_seau = 0

    # ------------------------------------------------------------ verrou

    def refus_pivot(self) -> str | None:
        """Pourquoi la caméra ne peut pas pivoter maintenant, ou None."""
        for texte, permis in self._verrous:
            try:
                if not permis():
                    return texte
            except Exception as erreur:
                return f"{texte} ? ({erreur})"
        return None

    def pivote(self) -> bool:
        """Pour la griffe et la préhension : la caméra pivote (ou sa position est inconnue)."""
        return self._pivote

    def _tourner(self, angle: float) -> None:
        self.servo.tourner(angle)
        self._attendre(self.reglages.pivot_s)

    def ranger(self) -> bool:
        """Caméra vers le bocal (au démarrage, après une panne du servo) ; faux si le verrou
        l'interdit ou si le servo ne répond pas."""
        refus = self.refus_pivot()
        if refus is not None:
            journal.warning("Caméra du dosage pas rangée : %s", refus)
            return False
        self._pivote = True
        try:
            self._tourner(self.reglages.angle_bocal_deg)
        except OSError as erreur:
            journal.error("Caméra du dosage : servo : %s (position inconnue)", erreur)
            return False
        self._pivote = False
        return True

    # ------------------------------------------------------------ photos

    def photo(self, raison: str) -> None:
        """Point d'appel `photo(raison)` du Mycélium et de la Préhension : photo tout de suite
        (sans pivoter), notée au registre avec la raison de l'alerte."""
        if self.photographe is None:
            return
        try:
            photo = self.photographe.derniere("dosage")
        except ErreurVision as erreur:
            journal.warning("Pas de photo du dosage (%s) : %s", raison, erreur)
            return
        self.photographe.enregistrer(photo, raison)

    def commencer_photo_seau(
        self, seau: str, couche: int, bocal: str, grammes: float, cycle: int | None = None
    ) -> None:
        """Après chaque dose (agitateur rentré au garage) : pivote vers le seau, photo, revient
        au bocal. La photo est notée au registre avec sa dose."""
        if self._fil is not None and self._fil.is_alive():
            return
        if not self._en_fond:
            self.photo_seau(seau, couche, bocal, grammes, cycle)
            return
        self._fil = threading.Thread(
            target=self.photo_seau,
            args=(seau, couche, bocal, grammes, cycle),
            name="photo-seau",
            daemon=True,
        )
        self._fil.start()

    def photo_seau_finie(self) -> bool:
        return self._fil is None or not self._fil.is_alive()

    def photo_seau(
        self, seau: str, couche: int, bocal: str, grammes: float, cycle: int | None = None
    ) -> None:
        """La photo du seau, d'un bloc (dure ≈ 2 × pivot_s + la stabilisation)."""
        quoi = f"seau {seau}, couche {couche} : {grammes:.0f} g de mycélium du bocal {bocal}"
        if self.photographe is None:
            return
        refus = self.refus_pivot()
        if refus is not None:
            journal.warning("Photo du seau sautée (%s) : %s", quoi, refus)
            return
        photo = None
        self._pivote = True
        try:
            self._tourner(self.reglages.angle_seau_deg)
            photo = self.photographe.mesure("dosage")
        except (OSError, ErreurVision) as erreur:
            journal.warning("Photo du seau manquée (%s) : %s", quoi, erreur)
        try:
            self._tourner(self.reglages.angle_bocal_deg)
            self._pivote = False
        except OSError as erreur:
            journal.error("Caméra du dosage : servo : %s (position inconnue)", erreur)
        if photo is not None:
            self.photos_du_seau += 1
            self.photographe.enregistrer(photo, quoi, seau=seau, bocal=bocal, cycle=cycle)
