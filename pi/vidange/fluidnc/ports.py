"""Trouver et ouvrir le port USB d'une carte FluidNC par le numéro de série de son USB.

Jamais par l'ordre des ports : /dev/ttyACM0 et /dev/ttyACM1 peuvent s'échanger à
chaque démarrage ou rebranchement. Le numéro de série, lui, suit la carte.
"""

from collections.abc import Callable, Iterable
from typing import Any, Protocol

import serial
from serial.tools import list_ports


class ErreurFluidnc(Exception):
    """Problème avec une carte FluidNC ou sa liaison."""


class CarteIntrouvable(ErreurFluidnc):
    """Aucun port USB (ou plusieurs) ne porte le numéro de série de la carte."""


class Port(Protocol):
    """Ce que la liaison utilise d'un port série (pyserial ou le faux FluidNC)."""

    def write(self, donnees: bytes) -> Any: ...

    def readline(self) -> bytes:
        """Une ligne, ou moins (ou rien) si rien n'arrive pendant un court instant."""
        ...

    def close(self) -> None: ...


def lister_ports_usb() -> list[Any]:
    """Les ports série vus par le système (avec .device, .serial_number, .description)."""
    return list(list_ports.comports())


def decrire_ports(ports: Iterable[Any]) -> str:
    lignes = [
        f"{port.device} (n° de série : {port.serial_number or 'aucun'}, {port.description})"
        for port in ports
    ]
    return ", ".join(lignes) or "aucun port série"


def trouver_port(numero_serie: str, lister: Callable[[], Iterable[Any]] = lister_ports_usb) -> str:
    """Le chemin du port (/dev/ttyACM0...) qui porte ce numéro de série USB."""
    ports = list(lister())
    trouves = [port.device for port in ports if port.serial_number == numero_serie]
    if not trouves:
        raise CarteIntrouvable(
            f"aucun port USB ne porte le numéro de série « {numero_serie} » "
            f"(câble débranché ou carte éteinte ?). Ports vus : {decrire_ports(ports)}"
        )
    if len(trouves) > 1:
        raise CarteIntrouvable(
            f"plusieurs ports portent le numéro de série « {numero_serie} » "
            f"({', '.join(trouves)}) : impossible de savoir lequel est la bonne carte"
        )
    return trouves[0]


def ouvrir_port_usb(
    numero_serie: str,
    vitesse_bauds: int,
    delai_lecture_s: float,
    lister: Callable[[], Iterable[Any]] = lister_ports_usb,
) -> serial.Serial:
    """Ouvre le port de la carte qui porte ce numéro de série USB."""
    port = serial.Serial()
    port.port = trouver_port(numero_serie, lister)
    port.baudrate = vitesse_bauds
    port.timeout = delai_lecture_s
    port.write_timeout = delai_lecture_s
    # Sur beaucoup de cartes ESP32, les fils DTR et RTS de l'USB redémarrent la carte :
    # on les laisse au repos pour qu'une reconnexion ne fasse pas perdre la position.
    port.dtr = False
    port.rts = False
    # Personne d'autre ne peut ouvrir le port en même temps.
    port.exclusive = True
    port.open()
    return port
