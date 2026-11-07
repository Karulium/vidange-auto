"""La tête du micropore vue par le Pi : ses 2 servos et son capteur de distance, à travers la carte
de pesée du plateau du remplissage (boîtier du chariot, tâche 40 bis, vidange.materiel.carte_pesee).

    tete = TeteMicropore(reglages.machine.micropore, reglages.pesees.i2c, materiel, appris)
    tete.observer()               # en fond : lit le boîtier, renvoie les angles (battement,
                                  # redémarrage de la carte)
    tete.commander(escamotage=73.1, lame=145)    # angles de l'axe des servos (°)
    tete.lire()                   # une lecture tout de suite (distance du ToF...)
    tete.escamotee()              # True : vue escamotée au ToF ; False : vue sortie ; None : ?

Les angles sont ceux de l'AXE du servo (décisions, PR n° 84, point 1), en degrés. Le Pi les
renvoie au moins toutes les `battement_s` (sinon, au bout de 2 s, la carte garde les angles et le
dit). Au démarrage de la carte, la PCA9685 a ses sorties coupées : le Pi voit le compteur de
démarrages CHANGER (pas forcément de +1 : décisions, PR n° 84, point 4) et renvoie tout de suite
les angles. Les servos ont pu se relâcher pendant ce temps : la distance du ToF ne compte de
nouveau qu'après `stabilisation_s`, lue après le renvoi. Pareil après chaque ordre au servo
d'escamotage (`mouvement_s`).

« Escamotée » demande les trois : angle d'escamotage demandé = l'angle escamoté appris, lame au
repos (en haut), et une distance du ToF fraîche, lue après le dernier ordre, au moins à
escamotee_mm − tolerance. Rien de tout ça n'est une sécurité : la tête est petite et l'enceinte
fermée ; ce verrou protège la tête et le seau.
"""

import threading
import time
from collections.abc import Callable

from vidange.journal import donner_journal
from vidange.materiel import ErreurMateriel, Materiel
from vidange.materiel.carte_pesee import BoitierChariot
from vidange.micropore.appris import FichierAppris
from vidange.reglages import I2cPesee, Micropore

journal = donner_journal("micropore.tete")


class TeteMicropore:
    def __init__(
        self,
        reglages: Micropore,
        i2c: I2cPesee,
        materiel: Materiel,
        appris: FichierAppris,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.reglages = reglages
        self.carte = i2c.carte
        self.voies = list(i2c.pca9685.voies)
        self.voie_escamotage = self.voies.index(reglages.servo_escamotage)
        self.voie_lame = self.voies.index(reglages.servo_lame)
        self.materiel = materiel
        self.appris = appris
        self._horloge = horloge
        self._verrou = threading.RLock()
        # Angles demandés (°) par voie ; absents : jamais demandés depuis le démarrage du Pi.
        self.angles: dict[int, float] = {}
        self.etat: BoitierChariot | None = None
        self.lu_a: float | None = None
        self.erreur: str | None = None
        self.demarrages: int | None = None
        self.redemarrages_vus = 0
        self._envoye_a: float | None = None
        # La distance du ToF ne compte qu'à partir de cette heure (après un ordre, un redémarrage).
        self._valide_apres = 0.0

    # ------------------------------------------------------------ ordres

    def commander(self, escamotage: float | None = None, lame: float | None = None) -> None:
        """Envoie ces angles (les autres restent). Lève ErreurMateriel si la carte refuse."""
        with self._verrou:
            if escamotage is not None:
                self.angles[self.voie_escamotage] = escamotage
                self._valide_apres = self._horloge() + self.reglages.servos.mouvement_s
            if lame is not None:
                self.angles[self.voie_lame] = lame
            self._envoyer()

    def escamoter(self) -> None:
        """Tête escamotée, lame au repos (lève ErreurMateriel ; ValueError si l'angle escamoté
        n'est pas appris)."""
        escamote = self.appris.escamote_deg
        if escamote is None:
            raise ValueError("angle « escamoté » pas appris (vidange-micropore escamote)")
        self.commander(escamotage=escamote, lame=self.reglages.servos.lame_repos_deg)

    def _envoyer(self) -> None:
        for voie, angle in sorted(self.angles.items()):
            self.materiel.ecrire_angles_chariot(self.carte, [angle], premiere_voie=voie)
        self._envoye_a = self._horloge()

    # ------------------------------------------------------------ lectures

    def lire(self) -> BoitierChariot:
        """Une lecture du boîtier tout de suite ; renvoie les angles si la carte a redémarré.
        Lève ErreurMateriel si elle ne répond pas."""
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
                journal.warning(
                    "Micropore : la carte du plateau a redémarré (compteur %d → %d) : angles "
                    "renvoyés, ToF relu dans %g s",
                    self.demarrages,
                    etat.demarrages,
                    self.reglages.servos.stabilisation_s,
                )
                self._valide_apres = maintenant + self.reglages.servos.stabilisation_s
                if self.angles:
                    self._envoyer()
            elif etat.aucun_ordre and self.angles:
                # La carte n'a pas encore reçu d'ordre (premier ordre perdu) : on renvoie.
                self._envoyer()
            self.demarrages = etat.demarrages
            self.etat, self.lu_a = etat, maintenant
            return etat

    def observer(self) -> None:
        """En fond (et à chaque instant du simulateur) : une lecture, et le battement."""
        try:
            self.lire()
            with self._verrou:
                envoye = self._envoye_a
                if self.angles and (
                    envoye is None or self._horloge() - envoye >= self.reglages.servos.battement_s
                ):
                    self._envoyer()
        except ErreurMateriel as erreur:
            journal.debug("Micropore : boîtier du chariot : %s", erreur)

    def prochain(self) -> float | None:
        """Pour le simulateur : la prochaine heure où il y a quelque chose à faire."""
        with self._verrou:
            heures = [self._valide_apres]
            if self.angles and self._envoye_a is not None:
                heures.append(self._envoye_a + self.reglages.servos.battement_s)
        futures = [heure for heure in heures if heure > self._horloge()]
        return min(futures) if futures else None

    def distance_mm(self) -> float | None:
        """La dernière distance du ToF qui compte : bonne mesure, assez jeune, lue après le dernier
        ordre au servo d'escamotage et après le dernier redémarrage de la carte ; sinon None."""
        with self._verrou:
            etat, lu_a = self.etat, self.lu_a
            valide_apres = self._valide_apres
        if etat is None or lu_a is None or etat.distance_mm is None or etat.etat_tof != 0:
            return None
        if etat.aucun_ordre or etat.age_tof_ms > self.reglages.tof.age_max_ms:
            return None
        if lu_a < valide_apres or self._horloge() - lu_a > self.reglages.tof.fraicheur_s:
            return None
        return float(etat.distance_mm)

    def vue_escamotee(self, distance: float | None) -> bool:
        tof = self.reglages.tof
        return distance is not None and distance >= tof.escamotee_mm - tof.tolerance_escamotee_mm

    def escamotee(self) -> bool | None:
        """Pour le Remplissage (le plateau ne bouge que tête escamotée), le spray et la préhension.
        True : escamotée demandée ET vue au ToF ; False : vue sortie (ou pas demandée escamotée) ;
        None : on ne sait pas (ToF muet, pas encore relu après un redémarrage...)."""
        escamote = self.appris.escamote_deg
        with self._verrou:
            esc = self.angles.get(self.voie_escamotage)
            lame = self.angles.get(self.voie_lame)
        distance = self.distance_mm()
        if escamote is None or esc is None or lame is None:
            return None
        if abs(esc - escamote) > 1e-6 or abs(lame - self.reglages.servos.lame_repos_deg) > 1e-6:
            return False
        if distance is None:
            return None
        return self.vue_escamotee(distance)

    def en_dict(self) -> dict[str, object]:
        etat = self.etat
        return {
            "distance_mm": None if etat is None else etat.distance_mm,
            "demarrages": None if etat is None else etat.demarrages,
            "escamotee": self.escamotee(),
            "angles_deg": {self.voies[v]: a for v, a in self.angles.items()},
            "erreur": self.erreur,
        }
