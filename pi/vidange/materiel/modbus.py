"""Modbus RTU sur RS485 : lecture de registres (fonctions 3 et 4 : cartes de pesée, carte du
spray) et écriture de plusieurs registres (fonction 16 : ordres à la carte du spray).

Une trame : adresse, fonction, données, puis une somme de contrôle (CRC-16 Modbus).
"""

import threading
from collections.abc import Callable
from typing import Any, Protocol

from vidange.materiel.puces import ErreurMateriel


class PortSerie(Protocol):
    """Ce que le client utilise d'un port série (pyserial ou le faux RS485)."""

    def write(self, donnees: bytes) -> Any: ...

    def read(self, nombre: int) -> bytes:
        """Au plus `nombre` octets ; moins si rien n'arrive pendant le délai du port."""
        ...

    def reset_input_buffer(self) -> None: ...

    def close(self) -> None: ...


def crc_modbus(donnees: bytes) -> bytes:
    """CRC-16 Modbus (polynôme 0xA001, départ 0xFFFF), octet de poids faible d'abord."""
    crc = 0xFFFF
    for octet in donnees:
        crc ^= octet
        for _ in range(8):
            crc = crc >> 1 ^ 0xA001 if crc & 1 else crc >> 1
    return crc.to_bytes(2, "little")


def demande_lecture(adresse: int, fonction: int, registre: int, nombre: int) -> bytes:
    trame = bytes([adresse, fonction, *registre.to_bytes(2, "big"), *nombre.to_bytes(2, "big")])
    return trame + crc_modbus(trame)


FONCTION_ECRITURE = 16


def demande_ecriture(adresse: int, registre: int, valeurs: list[int]) -> bytes:
    """Fonction 16 : écrire plusieurs registres de suite, en une trame."""
    donnees = b"".join((v & 0xFFFF).to_bytes(2, "big") for v in valeurs)
    trame = bytes(
        [
            adresse,
            FONCTION_ECRITURE,
            *registre.to_bytes(2, "big"),
            *len(valeurs).to_bytes(2, "big"),
            len(donnees),
        ]
    )
    trame += donnees
    return trame + crc_modbus(trame)


# Codes d'exception Modbus les plus courants, en clair.
EXCEPTIONS = {
    1: "fonction non comprise par l'appareil",
    2: "registre inconnu de l'appareil",
    3: "valeur refusée",
    4: "panne de l'appareil",
}


class ClientModbus:
    """Un client sur un fil RS485. Le port est ouvert à la première demande, et rouvert
    après une erreur (adaptateur débranché puis rebranché)."""

    def __init__(self, ouvrir: Callable[[], PortSerie], nom: str = "RS485") -> None:
        self._ouvrir = ouvrir
        self.nom = nom
        self._port: PortSerie | None = None
        self._verrou = threading.Lock()

    def lire_registres(
        self, adresse: int, fonction: int, registre: int, nombre: int = 1
    ) -> list[int]:
        with self._verrou:
            try:
                if self._port is None:
                    self._port = self._ouvrir()
                return self._echanger(self._port, adresse, fonction, registre, nombre)
            except OSError as erreur:
                self.fermer()
                raise ErreurMateriel(f"{self.nom} : port série en panne ({erreur})") from None

    def ecrire_registres(self, adresse: int, registre: int, valeurs: list[int]) -> None:
        """Écrit `valeurs` à partir de `registre` (fonction 16) ; ErreurMateriel si l'appareil
        ne confirme pas."""
        if not 1 <= len(valeurs) <= 123:
            raise ValueError("Modbus : de 1 à 123 registres par écriture")
        with self._verrou:
            try:
                if self._port is None:
                    self._port = self._ouvrir()
                self._ecrire(self._port, adresse, registre, valeurs)
            except OSError as erreur:
                self.fermer()
                raise ErreurMateriel(f"{self.nom} : port série en panne ({erreur})") from None

    def _ecrire(self, port: PortSerie, adresse: int, registre: int, valeurs: list[int]) -> None:
        port.reset_input_buffer()
        port.write(demande_ecriture(adresse, registre, valeurs))
        appareil = f"{self.nom}, appareil {adresse}"
        debut = port.read(3)
        if len(debut) < 3:
            raise ErreurMateriel(
                f"{appareil} : pas de réponse (débranché, pas alimenté, mauvaise adresse "
                "ou mauvaise vitesse ?)"
            )
        if debut[1] == FONCTION_ECRITURE | 0x80:
            reste = port.read(2)
            trame = debut + reste
            if len(reste) == 2 and crc_modbus(trame[:3]) == trame[3:]:
                cause = EXCEPTIONS.get(debut[2], f"code {debut[2]}")
                raise ErreurMateriel(f"{appareil} : écriture refusée ({cause})")
            raise ErreurMateriel(f"{appareil} : réponse abîmée")
        trame = debut + port.read(5)
        attendu = bytes(
            [
                adresse,
                FONCTION_ECRITURE,
                *registre.to_bytes(2, "big"),
                *len(valeurs).to_bytes(2, "big"),
            ]
        )
        if len(trame) < 8 or crc_modbus(trame[:6]) != trame[6:8]:
            raise ErreurMateriel(f"{appareil} : réponse abîmée (somme de contrôle fausse)")
        if trame[:6] != attendu:
            raise ErreurMateriel(f"{appareil} : réponse inattendue ({trame.hex(' ')})")

    def _echanger(
        self, port: PortSerie, adresse: int, fonction: int, registre: int, nombre: int
    ) -> list[int]:
        port.reset_input_buffer()
        port.write(demande_lecture(adresse, fonction, registre, nombre))
        appareil = f"{self.nom}, appareil {adresse}"
        debut = port.read(3)
        if len(debut) < 3:
            raise ErreurMateriel(
                f"{appareil} : pas de réponse (débranché, pas alimenté, mauvaise adresse "
                "ou mauvaise vitesse ?)"
            )
        if debut[1] == fonction | 0x80:
            reste = port.read(2)
            trame = debut + reste
            if len(reste) == 2 and crc_modbus(trame[:3]) == trame[3:]:
                cause = EXCEPTIONS.get(debut[2], f"code {debut[2]}")
                raise ErreurMateriel(f"{appareil} : demande refusée ({cause})")
            raise ErreurMateriel(f"{appareil} : réponse abîmée")
        if debut[0] != adresse or debut[1] != fonction or debut[2] != 2 * nombre:
            raise ErreurMateriel(f"{appareil} : réponse inattendue ({debut.hex(' ')})")
        reste = port.read(2 * nombre + 2)
        trame = debut + reste
        if len(reste) < 2 * nombre + 2 or crc_modbus(trame[:-2]) != trame[-2:]:
            raise ErreurMateriel(f"{appareil} : réponse abîmée (somme de contrôle fausse)")
        donnees = trame[3:-2]
        return [int.from_bytes(donnees[i : i + 2], "big") for i in range(0, len(donnees), 2)]

    def fermer(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            except OSError:
                pass
            self._port = None
