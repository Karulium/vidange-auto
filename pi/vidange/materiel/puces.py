"""Puces et broches que le Pi lit ou commande : GPIO, bus I2C, PCF8574, MCP23017, ADS1115, SHT31.

Les numéros écrits ici (registres, commandes, temps de conversion) sont ceux des fiches
techniques des puces, pas des chiffres de la machine : ceux-là sont dans
`docs/entrees-sorties.yaml`.

Deux sortes de pièces :
- `Lignes` : des broches tout-ou-rien, lues ou commandées par leur nom (GPIO17, P0, A3...).
  Les GPIO du Pi et les extenseurs I2C (PCF8574, MCP23017) ont la même interface :
  c'est ce qui permet de choisir plus tard comment brancher les relais et les entrées 24 V.
- `BusI2c` : un bus I2C, sur lequel parlent les puces. Le vrai passe par Linux (smbus2),
  le faux (`vidange.materiel.faux`) imite les puces.
"""

import errno
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Literal, Protocol

from vidange.entrees_sorties import BROCHES_DES_PUCES

Tirage = Literal["aucun", "haut", "bas"]


class ErreurMateriel(Exception):
    """Une puce ou un appareil ne répond pas, ou répond mal."""


class Lignes(Protocol):
    """Des broches tout-ou-rien. Niveau électrique : True = haut."""

    def preparer(self, entrees: Mapping[str, Tirage], sorties: Mapping[str, bool]) -> None:
        """Met les broches en entrée (avec leur tirage) ou en sortie (niveau de départ)."""
        ...

    def lire(self, broche: str) -> bool: ...

    def ecrire(self, broche: str, haut: bool) -> None: ...

    def fermer(self) -> None: ...


class BusI2c(Protocol):
    def ecrire(self, adresse: int, donnees: bytes) -> None: ...

    def lire(self, adresse: int, nombre: int) -> bytes: ...

    def ecrire_lire(self, adresse: int, donnees: bytes, nombre: int) -> bytes:
        """Écrit puis lit sans relâcher le bus (choix d'un registre puis lecture)."""
        ...

    def fermer(self) -> None: ...


def decrire_erreur_i2c(erreur: OSError) -> str:
    if erreur.errno in (errno.EREMOTEIO, errno.ENXIO, errno.EIO):
        return "pas de réponse (puce débranchée, mauvaise adresse ou pas alimentée ?)"
    return str(erreur)


# ------------------------------------------------------------------ vrais accès


class BusI2cLinux:
    """Le vrai bus I2C du Pi, par le fichier de Linux (/dev/i2c-1)."""

    def __init__(self, fichier: str) -> None:
        from smbus2 import SMBus, i2c_msg

        self._message = i2c_msg
        try:
            self._bus = SMBus(fichier)
        except OSError as erreur:
            raise ErreurMateriel(
                f"bus I2C {fichier} impossible à ouvrir ({erreur}) : I2C activé dans "
                "raspi-config ? compte dans le groupe i2c ?"
            ) from None

    def ecrire(self, adresse: int, donnees: bytes) -> None:
        self._bus.i2c_rdwr(self._message.write(adresse, list(donnees)))

    def lire(self, adresse: int, nombre: int) -> bytes:
        message = self._message.read(adresse, nombre)
        self._bus.i2c_rdwr(message)
        return bytes(list(message))

    def ecrire_lire(self, adresse: int, donnees: bytes, nombre: int) -> bytes:
        lecture = self._message.read(adresse, nombre)
        self._bus.i2c_rdwr(self._message.write(adresse, list(donnees)), lecture)
        return bytes(list(lecture))

    def fermer(self) -> None:
        self._bus.close()


class LignesGpio:
    """Les broches GPIO du Pi, par libgpiod (le seul moyen qui marche sur le Pi 5).

    Les broches sont demandées par leur nom (GPIO17) : c'est Linux qui sait où elles sont.
    `demander` sert aux tests (par défaut : gpiod.request_lines).
    """

    def __init__(self, fichier: str, demander: Callable[..., Any] | None = None) -> None:
        self.fichier = fichier
        self._demander = demander
        self._requete: Any = None

    def preparer(self, entrees: Mapping[str, Tirage], sorties: Mapping[str, bool]) -> None:
        import gpiod
        from gpiod.line import Bias, Direction, Value

        tirages = {"aucun": Bias.DISABLED, "haut": Bias.PULL_UP, "bas": Bias.PULL_DOWN}
        config: dict[Any, Any] = {
            broche: gpiod.LineSettings(direction=Direction.INPUT, bias=tirages[tirage])
            for broche, tirage in entrees.items()
        }
        for broche, haut in sorties.items():
            config[broche] = gpiod.LineSettings(
                direction=Direction.OUTPUT, output_value=Value.ACTIVE if haut else Value.INACTIVE
            )
        if not config:
            return
        self._valeurs = (Value.INACTIVE, Value.ACTIVE)
        demander = self._demander or gpiod.request_lines
        try:
            self._requete = demander(self.fichier, consumer="vidange", config=config)
        except (OSError, ValueError) as erreur:
            raise ErreurMateriel(
                f"broches GPIO {', '.join(config)} de {self.fichier} impossibles à prendre "
                f"({erreur}) : nom de broche juste ? déjà prise par un autre programme ?"
            ) from None

    def lire(self, broche: str) -> bool:
        return self._requete.get_value(broche) == self._valeurs[1]

    def ecrire(self, broche: str, haut: bool) -> None:
        self._requete.set_value(broche, self._valeurs[haut])

    def fermer(self) -> None:
        if self._requete is not None:
            self._requete.release()
            self._requete = None


# ---------------------------------------------------------- puces sur le bus I2C


class PuceI2c:
    def __init__(self, bus: BusI2c, adresse: int) -> None:
        self.bus = bus
        self.adresse = adresse

    def _echanger(self, action: Callable[[], Any]) -> Any:
        try:
            return action()
        except OSError as erreur:
            raise ErreurMateriel(
                f"puce I2C 0x{self.adresse:02x} : {decrire_erreur_i2c(erreur)}"
            ) from None

    def fermer(self) -> None:
        """Le bus est partagé : c'est le Materiel qui le ferme."""


def _numeros(puce: str, broches: Iterable[str]) -> list[int]:
    return [BROCHES_DES_PUCES[puce].index(broche) for broche in broches]


class Pcf8574(PuceI2c):
    """Extenseur 8 broches. Pas de registre : on lit ou écrit un octet.

    Une broche écrite à 1 est tirée vers le haut (faiblement) : elle sert d'entrée.
    """

    def __init__(self, bus: BusI2c, adresse: int) -> None:
        super().__init__(bus, adresse)
        self._octet = 0xFF

    def preparer(self, entrees: Mapping[str, Tirage], sorties: Mapping[str, bool]) -> None:
        self._octet = 0xFF
        for numero, haut in zip(_numeros("pcf8574", sorties), sorties.values(), strict=True):
            if not haut:
                self._octet &= ~(1 << numero)
        self._echanger(lambda: self.bus.ecrire(self.adresse, bytes([self._octet])))

    def lire(self, broche: str) -> bool:
        octet = self._echanger(lambda: self.bus.lire(self.adresse, 1))[0]
        return bool(octet >> _numeros("pcf8574", [broche])[0] & 1)

    def ecrire(self, broche: str, haut: bool) -> None:
        masque = 1 << _numeros("pcf8574", [broche])[0]
        octet = self._octet | masque if haut else self._octet & ~masque
        self._echanger(lambda: self.bus.ecrire(self.adresse, bytes([octet])))
        self._octet = octet


class Mcp23017(PuceI2c):
    """Extenseur 16 broches (A0 à A7, B0 à B7). Registres du mode d'origine (IOCON.BANK = 0)."""

    IODIR = 0x00  # 1 = entrée
    GPPU = 0x0C  # 1 = tirage haut
    GPIO = 0x12  # niveau des broches
    OLAT = 0x14  # niveau demandé aux sorties

    def __init__(self, bus: BusI2c, adresse: int) -> None:
        super().__init__(bus, adresse)
        self._olat = 0

    def _ecrire_registres(self, registre: int, valeur: int) -> None:
        donnees = bytes([registre, valeur & 0xFF, valeur >> 8])
        self._echanger(lambda: self.bus.ecrire(self.adresse, donnees))

    def preparer(self, entrees: Mapping[str, Tirage], sorties: Mapping[str, bool]) -> None:
        direction = 0xFFFF
        tirage = 0
        self._olat = 0
        for numero, haut in zip(_numeros("mcp23017", sorties), sorties.values(), strict=True):
            direction &= ~(1 << numero)
            if haut:
                self._olat |= 1 << numero
        for numero, sorte in zip(_numeros("mcp23017", entrees), entrees.values(), strict=True):
            if sorte == "haut":
                tirage |= 1 << numero
        # Niveau des sorties d'abord, sens des broches ensuite : pas d'à-coup sur les relais.
        self._ecrire_registres(self.OLAT, self._olat)
        self._ecrire_registres(self.GPPU, tirage)
        self._ecrire_registres(self.IODIR, direction)

    def lire(self, broche: str) -> bool:
        octets = self._echanger(lambda: self.bus.ecrire_lire(self.adresse, bytes([self.GPIO]), 2))
        return bool(int.from_bytes(octets, "little") >> _numeros("mcp23017", [broche])[0] & 1)

    def ecrire(self, broche: str, haut: bool) -> None:
        masque = 1 << _numeros("mcp23017", [broche])[0]
        olat = self._olat | masque if haut else self._olat & ~masque
        self._ecrire_registres(self.OLAT, olat)
        self._olat = olat


class Ads1115(PuceI2c):
    """Convertisseur analogique 4 voies, 16 bits. Une conversion à la demande par lecture."""

    CONVERSION = 0x00
    CONFIG = 0x01
    # Pleine échelle (V) → réglage du gain (fiche technique, tableau 8).
    GAINS = {0.256: 0b101, 0.512: 0b100, 1.024: 0b011, 2.048: 0b010, 4.096: 0b001, 6.144: 0b000}
    # 128 mesures/s : une conversion dure 7,8 ms ; on attend au plus 10 fois plus.
    VITESSE = 0b100
    ATTENTE_MAX_S = 0.08

    @classmethod
    def pleine_echelle(cls, tension_max: float) -> float:
        """La plus petite échelle qui contient la tension (la plus précise)."""
        return min((e for e in cls.GAINS if e >= tension_max), default=max(cls.GAINS))

    def mesurer(self, voie: str, tension_max: float) -> float:
        """Tension (V) sur une voie (A0 à A3), mesurée par rapport à la masse."""
        echelle = self.pleine_echelle(tension_max)
        config = (
            1 << 15  # lance une conversion
            | (0b100 + _numeros("ads1115", [voie])[0]) << 12  # voie contre la masse
            | self.GAINS[echelle] << 9
            | 1 << 8  # une seule conversion
            | self.VITESSE << 5
            | 0b11  # comparateur arrêté
        )
        self._echanger(
            lambda: self.bus.ecrire(self.adresse, bytes([self.CONFIG, *config.to_bytes(2, "big")]))
        )
        fin = time.monotonic() + self.ATTENTE_MAX_S
        while True:
            etat = self._echanger(
                lambda: self.bus.ecrire_lire(self.adresse, bytes([self.CONFIG]), 2)
            )
            if etat[0] & 0x80:
                break
            if time.monotonic() > fin:
                raise ErreurMateriel(f"puce ADS1115 0x{self.adresse:02x} : conversion jamais finie")
            time.sleep(0.002)
        brut = self._echanger(
            lambda: self.bus.ecrire_lire(self.adresse, bytes([self.CONVERSION]), 2)
        )
        return int.from_bytes(brut, "big", signed=True) * echelle / 32768


def crc_sht31(donnees: bytes) -> int:
    """Somme de contrôle des mesures du SHT31 (CRC-8, polynôme 0x31, départ 0xFF)."""
    crc = 0xFF
    for octet in donnees:
        crc ^= octet
        for _ in range(8):
            crc = (crc << 1 ^ 0x31 if crc & 0x80 else crc << 1) & 0xFF
    return crc


class Sht31(PuceI2c):
    """Capteur de température et d'humidité."""

    # Mesure seule, haute répétabilité, sans étirement d'horloge ; dure au plus 15,5 ms.
    MESURE = bytes([0x24, 0x00])
    DUREE_S = 0.016

    def mesurer(self) -> tuple[float, float]:
        """(température en °C, humidité relative en %)."""
        self._echanger(lambda: self.bus.ecrire(self.adresse, self.MESURE))
        time.sleep(self.DUREE_S)
        octets = self._echanger(lambda: self.bus.lire(self.adresse, 6))
        if crc_sht31(octets[0:2]) != octets[2] or crc_sht31(octets[3:5]) != octets[5]:
            raise ErreurMateriel(
                f"puce SHT31 0x{self.adresse:02x} : mesure abîmée (somme de contrôle fausse)"
            )
        temperature = -45 + 175 * int.from_bytes(octets[0:2], "big") / 65535
        humidite = 100 * int.from_bytes(octets[3:5], "big") / 65535
        return temperature, humidite
