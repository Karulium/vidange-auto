"""Le bras de la fermeture vu par le Pi : un seul servo DS3225, sur une voie de la PCA9685 du
boîtier du chariot, à travers la carte de pesée du plateau (tâche 40 bis,
vidange.materiel.carte_pesee).

    bras = BrasFermeture(reglages.machine.fermeture, reglages.pesees.i2c, materiel)
    bras.observer()          # en fond : lit le boîtier, renvoie l'angle (battement, redémarrage)
    bras.commander(202.5)    # angle de l'AXE du servo (°)
    bras.est_range()         # True : ordonné rangé ET fini ; False : ailleurs ; None : inconnu

Le bras n'a AUCUN capteur : « rangé » veut dire « le Pi l'a ordonné, l'attente est passée, la carte
n'a pas oublié l'ordre ». Jamais d'ordre « sortie coupée » : le signal du servo n'est jamais coupé,
même à l'arrêt (un servo numérique sans signal se relâche).

Au démarrage de la carte, la PCA9685 a ses sorties coupées : le Pi voit le compteur de démarrages
CHANGER (pas forcément de +1, décisions, PR n° 84, point 4) et renvoie l'angle tout de suite ; le
bras ne compte de nouveau « rangé » qu'après `stabilisation_s`.

Rien de tout ça n'est une sécurité : le servo est faible et il bouge à vide ; ce suivi protège la
machine, jamais les personnes.
"""

import threading
import time
from collections.abc import Callable

from vidange.journal import donner_journal
from vidange.materiel import ErreurMateriel, Materiel
from vidange.materiel.carte_pesee import BoitierChariot
from vidange.reglages import Fermeture, I2cPesee

journal = donner_journal("fermeture.bras")


class BrasFermeture:
    def __init__(
        self,
        reglages: Fermeture,
        i2c: I2cPesee,
        materiel: Materiel,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.reglages = reglages
        self.carte = i2c.carte
        self.voies = list(i2c.pca9685.voies)
        self.voie = self.voies.index(reglages.servo)
        self.materiel = materiel
        self._horloge = horloge
        self._verrou = threading.RLock()
        # Angle de l'axe demandé (°) ; None : jamais demandé depuis le démarrage du Pi.
        self.angle: float | None = None
        self.etat: BoitierChariot | None = None
        self.erreur: str | None = None
        self.demarrages: int | None = None
        self.redemarrages_vus = 0
        self._envoye_a: float | None = None
        # Le bras compte arrivé à partir de cette heure (attente après l'ordre, stabilisation).
        self._pret_a = 0.0

    # ------------------------------------------------------------ ordres

    def angle_range(self) -> float:
        return self.reglages.servo_range_deg()

    def angle_travail(self) -> float:
        return self.reglages.servo_travail_deg()

    def commander(self, angle: float) -> None:
        """Envoie cet angle de l'axe (°). Lève ErreurMateriel si la carte refuse (angle hors de la
        plage de la voie) ou ne répond pas."""
        with self._verrou:
            self._envoyer(angle)
            self.angle = angle
            self._pret_a = max(self._pret_a, self._horloge() + self.reglages.bras.attente_s)

    def _envoyer(self, angle: float) -> None:
        self.materiel.ecrire_angles_chariot(self.carte, [angle], premiere_voie=self.voie)
        self._envoye_a = self._horloge()

    # ------------------------------------------------------------ lectures

    def lire(self) -> BoitierChariot:
        """Une lecture du boîtier tout de suite ; renvoie l'angle si la carte a redémarré. Lève
        ErreurMateriel si elle ne répond pas."""
        with self._verrou:
            try:
                etat = self.materiel.lire_boitier_chariot(self.carte, len(self.voies))
            except ErreurMateriel as erreur:
                self.erreur = str(erreur)
                self.etat = None
                raise
            maintenant = self._horloge()
            self.erreur = None
            if self.demarrages is not None and etat.demarrages != self.demarrages:
                self.redemarrages_vus += 1
                stabilisation = self.reglages.bras.stabilisation_s
                journal.warning(
                    "Fermeture : la carte du plateau a redémarré (compteur %d → %d) : angle "
                    "renvoyé, bras compté rangé de nouveau dans %g s",
                    self.demarrages,
                    etat.demarrages,
                    stabilisation,
                )
                self._pret_a = max(self._pret_a, maintenant + stabilisation)
                if self.angle is not None:
                    self._envoyer(self.angle)
            elif etat.aucun_ordre and self.angle is not None:
                # La carte n'a pas encore reçu d'ordre (premier ordre perdu) : on renvoie.
                self._envoyer(self.angle)
            self.demarrages = etat.demarrages
            self.etat = etat
            return etat

    def observer(self) -> None:
        """En fond (et à chaque instant du simulateur) : une lecture, et le battement."""
        try:
            self.lire()
            with self._verrou:
                envoye = self._envoye_a
                if self.angle is not None and (
                    envoye is None or self._horloge() - envoye >= self.reglages.bras.battement_s
                ):
                    self._envoyer(self.angle)
        except ErreurMateriel as erreur:
            journal.debug("Fermeture : boîtier du chariot : %s", erreur)

    def prochain(self) -> float | None:
        """Pour le simulateur : la prochaine heure où il y a quelque chose à faire."""
        with self._verrou:
            heures = [self._pret_a]
            if self.angle is not None and self._envoye_a is not None:
                heures.append(self._envoye_a + self.reglages.bras.battement_s)
        futures = [heure for heure in heures if heure > self._horloge()]
        return min(futures) if futures else None

    def est_range(self) -> bool | None:
        """Le bras est-il rangé ? True : rangé ordonné, ordre fini, carte vivante ; False : il est
        ailleurs (au travail, en route) ; None : on ne sait pas (jamais ordonné depuis le démarrage
        du Pi, carte muette ou qui n'a pas d'ordre)."""
        with self._verrou:
            angle, etat = self.angle, self.etat
            pret = self._horloge() >= self._pret_a
        if angle is None or etat is None or self.erreur is not None:
            return None
        if etat.aucun_ordre or etat.pca9685_muette or etat.pi_silencieux:
            return None
        if abs(angle - self.angle_range()) > 1e-6:
            return False
        return pret

    def en_dict(self) -> dict[str, object]:
        return {
            "angle_deg": self.angle,
            "range": self.est_range(),
            "demarrages": None if self.etat is None else self.etat.demarrages,
            "erreur": self.erreur,
        }
