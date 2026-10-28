"""Dialogue direct avec la console de FluidNC, pendant une mise à jour (liaison arrêtée).

    console = Console(port, delai_commande_s=5)
    console.version()                          # « 3.9.5 FluidNC v3.9.5 » ($I)
    console.envoyer_fichier("config.yaml", contenu)   # par XMODEM ($Xmodem/Receive=)
    console.lire_fichier("config.yaml")        # ($LocalFS/Show=)
    console.erreurs_demarrage()                # lignes d'erreur du démarrage ($SS)
    console.redemarrer(30)                     # ($Bye), attend « Grbl ... »

La liaison ordinaire (vidange/fluidnc/liaison.py) est arrêtée pendant ce temps : le port USB
ne s'ouvre qu'une fois. Ici on lit les réponses telles quelles, ligne par ligne, et on envoie
un fichier octet par octet (XMODEM avec CRC, blocs de 128 octets).
"""

import binascii
import time
from collections.abc import Callable
from typing import Any, Protocol

from vidange.mises_a_jour.commun import ErreurMiseAJour

# Commandes de FluidNC (voir la documentation de FluidNC, « Commands and Settings »).
VERSION = "$I"
JOURNAL_DEMARRAGE = "$SS"
RECEVOIR_FICHIER = "$Xmodem/Receive="
MONTRER_FICHIER = "$LocalFS/Show="
REDEMARRER = "$Bye"

# Octets de XMODEM.
SOH, EOT, ACK, NAK, CAN = 0x01, 0x04, 0x06, 0x15, 0x18
DEBUT_CRC = 0x43  # « C » : le receveur demande des blocs avec CRC
TAILLE_BLOC = 128
ESSAIS_BLOC = 10


class PortConsole(Protocol):
    """Ce que la console utilise d'un port série (pyserial ou le faux de faux.py)."""

    def write(self, donnees: bytes) -> Any: ...

    def read(self, taille: int = 1) -> bytes:
        """Au plus `taille` octets, ou rien si rien n'arrive pendant un court instant."""
        ...

    def readline(self) -> bytes: ...

    def close(self) -> None: ...


def completer(contenu: bytes) -> bytes:
    """Complète un fichier texte par des fins de ligne jusqu'à un nombre entier de blocs.

    XMODEM n'envoie que des blocs entiers : sans ça, le dernier serait complété par des
    caractères « Ctrl-Z » qui resteraient au bout du fichier de réglages. Des lignes vides en
    plus ne changent rien à un fichier YAML.
    """
    reste = len(contenu) % TAILLE_BLOC
    return contenu if reste == 0 else contenu + b"\n" * (TAILLE_BLOC - reste)


def meme_texte(a: str, b: str) -> bool:
    """Deux fichiers texte pareils, aux espaces de bout de ligne et aux lignes vides près."""

    def propre(texte: str) -> list[str]:
        lignes = (ligne.strip() for ligne in texte.replace("\r", "").split("\n"))
        return [ligne for ligne in lignes if ligne]

    return propre(a) == propre(b)


class Console:
    def __init__(
        self,
        port: PortConsole,
        delai_commande_s: float,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.port = port
        self.delai_s = delai_commande_s
        self._horloge = horloge
        self._reste = b""

    def fermer(self) -> None:
        self.port.close()

    # ------------------------------------------------------------ lignes

    def _vider(self) -> None:
        """Oublie ce que la carte a déjà dit (messages du démarrage...)."""
        self._reste = b""
        while self.port.readline():
            pass

    def _lire_ligne(self, fin: float) -> str | None:
        while self._horloge() < fin:
            if b"\n" in self._reste:
                brute, self._reste = self._reste.split(b"\n", 1)
                return brute.decode("ascii", errors="replace").strip()
            self._reste += self.port.readline()
        return None

    def commande(self, ligne: str, delai_s: float | None = None) -> list[str]:
        """Envoie une ligne et rend les lignes de la réponse, jusqu'à « ok » (non compris).

        Les rapports d'état (« <Idle|...> ») sont laissés de côté. Lève ErreurMiseAJour si la
        carte répond « error:N » ou ne répond pas à temps.
        """
        self._vider()
        self.port.write((ligne + "\n").encode("ascii"))
        fin = self._horloge() + (self.delai_s if delai_s is None else delai_s)
        lignes: list[str] = []
        while True:
            recue = self._lire_ligne(fin)
            if recue is None:
                raise ErreurMiseAJour(f"la carte ne répond pas à « {ligne} »")
            if recue == "ok":
                return lignes
            if recue.startswith("error"):
                raise ErreurMiseAJour(f"la carte refuse « {ligne} » ({recue})")
            if recue and not recue.startswith("<"):
                lignes.append(recue)

    # ------------------------------------------------------------ ce qu'on demande

    def version(self, delai_s: float | None = None) -> str:
        """La version du programme de la carte (ligne « [VER:...] » de « $I »)."""
        for ligne in self.commande(VERSION, delai_s):
            if ligne.startswith("[VER:"):
                return ligne.removeprefix("[VER:").rstrip("]").rstrip(":").strip()
        raise ErreurMiseAJour("la carte ne donne pas sa version (pas de « [VER:...] »)")

    def attendre_reponse(self, delai_s: float) -> str:
        """Après un redémarrage : redemande la version jusqu'à ce que la carte réponde."""
        fin = self._horloge() + delai_s
        derniere = "pas de réponse"
        while True:
            reste = fin - self._horloge()
            if reste <= 0:
                raise ErreurMiseAJour(f"la carte ne répond pas après {delai_s:g} s ({derniere})")
            try:
                return self.version(min(self.delai_s, reste))
            except ErreurMiseAJour as erreur:
                derniere = str(erreur)

    def erreurs_demarrage(self) -> list[str]:
        """Les lignes d'erreur des messages du démarrage (réglages faux, matériel absent...)."""
        return [ligne for ligne in self.commande(JOURNAL_DEMARRAGE) if "[MSG:ERR" in ligne]

    def lire_fichier(self, nom: str) -> str:
        lignes = self.commande(MONTRER_FICHIER + nom)
        return "\n".join(ligne for ligne in lignes if not ligne.startswith("[MSG:"))

    def redemarrer(self, delai_s: float) -> None:
        """Redémarre la carte et attend son message de bienvenue (« Grbl ... »)."""
        self._vider()
        self.port.write((REDEMARRER + "\n").encode("ascii"))
        fin = self._horloge() + delai_s
        try:
            while True:
                recue = self._lire_ligne(fin)
                if recue is None:
                    raise ErreurMiseAJour(f"la carte n'a pas redémarré en {delai_s:g} s")
                if recue.startswith("Grbl "):
                    return
        except OSError:
            # Port USB disparu : la carte redémarre (USB intégré à l'ESP32).
            return

    # ------------------------------------------------------------ envoi d'un fichier

    def envoyer_fichier(self, nom: str, contenu: bytes) -> None:
        """Écrit un fichier dans la carte (XMODEM), puis attend le « ok » de la carte."""
        self._vider()
        self.port.write((RECEVOIR_FICHIER + nom + "\n").encode("ascii"))
        crc = self._attendre_debut()
        donnees = completer(contenu)
        for rang in range(len(donnees) // TAILLE_BLOC):
            bloc = donnees[rang * TAILLE_BLOC : (rang + 1) * TAILLE_BLOC]
            numero = (rang + 1) % 256
            controle = (
                binascii.crc_hqx(bloc, 0).to_bytes(2, "big") if crc else bytes([sum(bloc) % 256])
            )
            self._envoyer_paquet(bytes([SOH, numero, 255 - numero]) + bloc + controle, rang + 1)
        self._envoyer_paquet(bytes([EOT]), "de fin")
        fin = self._horloge() + self.delai_s
        while True:
            recue = self._lire_ligne(fin)
            if recue is None or recue == "ok":
                # Pas de « ok » : le fichier est quand même relu ensuite pour vérifier.
                return
            if recue.startswith("error"):
                raise ErreurMiseAJour(f"la carte refuse le fichier « {nom} » ({recue})")

    def _attendre_octet(self, attendus: set[int], delai_s: float) -> int | None:
        fin = self._horloge() + delai_s
        while self._horloge() < fin:
            for octet in self.port.read(1):
                if octet in attendus:
                    return octet
        return None

    def _attendre_debut(self) -> bool:
        """Le receveur demande « C » (CRC) ou NAK (somme simple). Rend True pour le CRC."""
        octet = self._attendre_octet({DEBUT_CRC, NAK, CAN}, self.delai_s)
        if octet is None or octet == CAN:
            raise ErreurMiseAJour(
                "la carte ne se met pas à recevoir le fichier (FluidNC trop ancien ?)"
            )
        return octet == DEBUT_CRC

    def _envoyer_paquet(self, paquet: bytes, quoi: int | str) -> None:
        for _ in range(ESSAIS_BLOC):
            self.port.write(paquet)
            reponse = self._attendre_octet({ACK, NAK, CAN}, self.delai_s)
            if reponse == ACK:
                return
            if reponse == CAN:
                raise ErreurMiseAJour(f"la carte a interrompu l'envoi (bloc {quoi})")
        raise ErreurMiseAJour(f"bloc {quoi} refusé {ESSAIS_BLOC} fois par la carte")
