"""Lecture d'un capteur d'ozone ZE25-O3 sur sa propre liaison série (un capteur par adaptateur).

Le Pi lit l'ozone pour **informer et attendre** : la sécurité ozone est câblée (docs/decisions.md).

- Une trame à la somme de contrôle fausse, ou coupée, est ignorée et comptée.
- Plus aucune trame valable depuis `delai_muet_s` : le capteur est « muet » (CapteurMuet).
- Une valeur au plafond (≥ `plafond_ppm`) est dite « au plafond » : l'écran écrit « ≥ 10 ppm »,
  jamais « 10 ».
- Il faut lire au moins une fois par `delai_muet_s` en mode « envoi automatique » : la dernière
  trame valable lue est la mesure.
"""

import threading
import time
from collections.abc import Callable
from typing import NamedTuple

from vidange.entrees_sorties import CapteurOzone
from vidange.materiel.modbus import PortSerie
from vidange.materiel.puces import ErreurMateriel
from vidange.trame_ze25 import (
    LONGUEUR_TRAME,
    OCTET_DEBUT,
    trame_valable,
    valeur_brute,
)

# Tout ce qui est déjà arrivé au plus (protège la mémoire si personne ne lit pendant longtemps).
TAMPON_MAX = 20 * LONGUEUR_TRAME


class CapteurMuet(ErreurMateriel):
    """Aucune trame valable depuis trop longtemps (débranché, pas alimenté, mauvaise vitesse)."""


class MesureOzone(NamedTuple):
    ppm: float
    # La valeur est au plafond du capteur : l'ozone est au moins cette valeur.
    au_plafond: bool
    # Depuis combien de secondes cette trame est arrivée.
    age_s: float
    # Trames à la somme fausse ou coupées, depuis l'ouverture.
    trames_ignorees: int


def texte_ppm(mesure: MesureOzone, plafond_ppm: float) -> str:
    """Pour l'écran et le journal : « 0,85 ppm », ou « ≥ 10 ppm » au plafond."""
    if mesure.au_plafond:
        return f"≥ {plafond_ppm:g} ppm"
    return f"{mesure.ppm:.2f}".replace(".", ",") + " ppm"


class LecteurOzone:
    """Un capteur ZE25-O3. Le port est ouvert à la première lecture, et rouvert après une erreur."""

    def __init__(
        self,
        ouvrir: Callable[[], PortSerie],
        reglage: CapteurOzone,
        nom: str = "ozone",
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ouvrir = ouvrir
        self.reglage = reglage
        self.nom = nom
        self._horloge = horloge
        self._port: PortSerie | None = None
        self._verrou = threading.Lock()
        self._tampon = bytearray()
        self._derniere: tuple[int, float] | None = None  # (valeur brute, moment d'arrivée)
        self._depuis = horloge()
        self.trames_ignorees = 0

    def lire(self) -> MesureOzone:
        """La dernière mesure valable. Lève CapteurMuet si le capteur ne dit plus rien."""
        with self._verrou:
            try:
                if self._port is None:
                    self._port = self._ouvrir()
                    self._port.reset_input_buffer()
                    self._tampon.clear()
                    self._depuis = self._horloge()
                if self.reglage.mode == "question_reponse":
                    self._poser_la_question(self._port)
                else:
                    self._recevoir(self._port)
            except OSError as erreur:
                self._fermer()
                raise ErreurMateriel(f"{self.nom} : port série en panne ({erreur})") from None
            return self._mesure()

    def _poser_la_question(self, port: PortSerie) -> None:
        assert self.reglage.question is not None
        port.reset_input_buffer()
        port.write(self.reglage.question)
        self._ajouter(port.read(LONGUEUR_TRAME))
        # Une réponse coupée ne sert à rien : on ne l'attend pas à la question suivante.
        if self._tampon:
            self.trames_ignorees += 1
            self._tampon.clear()

    def _recevoir(self, port: PortSerie) -> None:
        # On ne lit que ce qui est déjà arrivé : pas d'attente.
        arrive = getattr(port, "in_waiting", 0)
        if arrive:
            self._ajouter(port.read(arrive))

    def _ajouter(self, octets: bytes) -> None:
        self._tampon += octets
        maintenant = self._horloge()
        while len(self._tampon) >= LONGUEUR_TRAME:
            trame = bytes(self._tampon[:LONGUEUR_TRAME])
            if trame_valable(trame):
                brut = valeur_brute(trame, self.reglage.position_valeur)
                self._derniere = (brut, maintenant)
                del self._tampon[:LONGUEUR_TRAME]
                continue
            # Mauvaise somme ou décalage : on avance jusqu'au prochain début de trame possible.
            suivant = self._tampon.find(bytes([OCTET_DEBUT]), 1)
            self.trames_ignorees += 1
            del self._tampon[: suivant if suivant != -1 else len(self._tampon)]
        # Ce qui reste ne commence pas par un début de trame : à jeter.
        if self._tampon and self._tampon[0] != OCTET_DEBUT:
            suivant = self._tampon.find(bytes([OCTET_DEBUT]))
            del self._tampon[: suivant if suivant != -1 else len(self._tampon)]
        del self._tampon[: max(0, len(self._tampon) - TAMPON_MAX)]

    def _mesure(self) -> MesureOzone:
        maintenant = self._horloge()
        delai = self.reglage.delai_muet_s
        if self._derniere is None:
            if maintenant - self._depuis > delai:
                raise CapteurMuet(
                    f"{self.nom} : muet, aucune trame valable depuis {delai:g} s (débranché, "
                    "pas alimenté, mauvaise vitesse ou mauvais mode ?)"
                )
            raise ErreurMateriel(f"{self.nom} : en attente de la première trame")
        brut, moment = self._derniere
        age = maintenant - moment
        if age > delai:
            raise CapteurMuet(f"{self.nom} : muet, aucune trame valable depuis {age:.0f} s")
        ppm = brut * self.reglage.pas_ppm
        return MesureOzone(ppm, ppm >= self.reglage.plafond_ppm - 1e-9, age, self.trames_ignorees)

    def _fermer(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            except OSError:
                pass
            self._port = None

    def fermer(self) -> None:
        with self._verrou:
            self._fermer()
