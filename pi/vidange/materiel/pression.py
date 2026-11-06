"""Lecture d'un capteur de pression différentielle Sensirion SDP810-125Pa sur le bus I2C.

Le Pi lit la pression pour **attendre la fin de la purge** : la sécurité est câblée. Une puce qui
ne répond pas, une mesure à la somme de contrôle fausse ou sans facteur d'échelle : ErreurMateriel,
jamais une valeur (le Nettoyage ne tient alors pas la condition pour vraie).
"""

import time
from collections.abc import Callable

from vidange import trame_sdp810 as sdp
from vidange.materiel.puces import BusI2c, ErreurMateriel, PuceI2c, crc_sht31


class Sdp810(PuceI2c):
    """Mesure continue : la commande de démarrage est envoyée à la première lecture, et à nouveau
    après une erreur (la puce a pu perdre le courant)."""

    def __init__(
        self,
        bus: BusI2c,
        adresse: int,
        inverser: bool = False,
        attendre: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(bus, adresse)
        self.inverser = inverser
        self._attendre = attendre
        self._demarre = False

    def _demarrer(self) -> None:
        # D'abord l'arrêt (sans importance s'il ne mesurait pas), puis le démarrage.
        try:
            self.bus.ecrire(self.adresse, sdp.COMMANDE_ARRETER)
        except OSError:
            pass
        self._attendre(sdp.ATTENTE_ARRET_S)
        self._echanger(lambda: self.bus.ecrire(self.adresse, sdp.COMMANDE_DEMARRER))
        self._attendre(sdp.ATTENTE_DEMARRAGE_S)
        self._demarre = True

    def mesurer(self) -> float:
        """La pression différentielle en Pa (positive : le côté « enceinte » est plus haut)."""
        try:
            if not self._demarre:
                self._demarrer()
            octets = self._echanger(lambda: self.bus.lire(self.adresse, sdp.LONGUEUR_REPONSE))
        except ErreurMateriel:
            self._demarre = False
            raise
        for debut in (0, 3, 6):
            if crc_sht31(octets[debut : debut + 2]) != octets[debut + 2]:
                self._demarre = False
                raise ErreurMateriel(
                    f"puce SDP810 0x{self.adresse:02x} : mesure abîmée (somme de contrôle fausse)"
                )
        echelle = int.from_bytes(octets[6:8], "big")
        if echelle == 0:
            raise ErreurMateriel(f"puce SDP810 0x{self.adresse:02x} : facteur d'échelle nul")
        pascals = int.from_bytes(octets[0:2], "big", signed=True) / echelle
        return -pascals if self.inverser else pascals
