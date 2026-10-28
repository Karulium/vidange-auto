"""Une fausse carte ESP32 avec FluidNC, pour essayer les mises à jour sans matériel.

    faux = FausseCarteEsp32(version="3.9.4 FluidNC v3.9.4")
    carte = CarteEsp32("portique", reglages, dossier, faux.trouver_port, faux.ouvrir, faux.esptool)

- `esptool` remplace la commande esptool : « read-flash 0 ALL fichier » écrit la mémoire de la
  fausse carte (programme et fichiers), « write-flash 0 fichier » la remet, « write-flash
  ADRESSE fichier » écrit un nouveau programme ;
- `ouvrir` donne sa console : « $I », « $SS », « $LocalFS/Show= », « $Xmodem/Receive= »
  (vrai XMODEM avec CRC), « $Bye ».
Un faux programme est un fichier qui commence par l'octet 0xE9 suivi de sa version et d'un
octet nul (`faux_programme`). Une version qui commence par « CASSE » fait une carte muette ;
un fichier de réglages qui contient « ERREUR » donne une erreur au démarrage.
"""

import binascii
import json
import sys
from pathlib import Path

from vidange.mises_a_jour.commun import ErreurMiseAJour
from vidange.mises_a_jour.console import ACK, CAN, DEBUT_CRC, EOT, NAK, SOH, TAILLE_BLOC

ADRESSE_PROGRAMME = 0x10000


def faux_programme(version: str) -> bytes:
    return b"\xe9" + version.encode("ascii") + b"\x00" + b"\xff" * 64


class FausseCarteEsp32:
    def __init__(self, version: str = "3.9.4 FluidNC v3.9.4", port: str = "/dev/ttyFAUX0") -> None:
        self.programme = faux_programme(version)
        self.fichiers: dict[str, bytes] = {}
        self.port = port
        self.branchee = True
        # Commandes esptool reçues (sans « python -m esptool »).
        self.commandes: list[list[str]] = []
        # Panne d'esptool à la prochaine commande qui contient ce mot (« write-flash »...).
        self.panne_esptool: str | None = None
        # Nombre de blocs XMODEM à refuser (NAK) avant de les prendre.
        self.blocs_a_refuser = 0
        self.redemarrages = 0

    @property
    def version(self) -> str:
        return self.programme[1:].split(b"\x00", 1)[0].decode("ascii", errors="replace")

    @property
    def muette(self) -> bool:
        return self.version.startswith("CASSE")

    def trouver_port(self) -> str:
        if not self.branchee:
            raise ErreurMiseAJour("carte débranchée")
        return self.port

    def ouvrir(self) -> "FauxPortConsole":
        if not self.branchee:
            raise OSError("carte débranchée")
        return FauxPortConsole(self)

    # ------------------------------------------------------------ esptool

    def esptool(self, commande: list[str], duree_max_s: float, *_: object) -> str:
        if commande[:3] != [sys.executable, "-m", "esptool"]:
            raise ErreurMiseAJour(f"commande inattendue : {commande}")
        arguments = commande[3:]
        self.commandes.append(arguments)
        if self.panne_esptool is not None and self.panne_esptool in arguments:
            self.panne_esptool = None
            raise ErreurMiseAJour("« esptool » a échoué (code 2) : A fatal error occurred")
        if "read-flash" in arguments:
            *_, adresse, taille, fichier = arguments
            assert (adresse, taille) == ("0", "ALL")
            memoire = {
                "programme": self.programme.hex(),
                "fichiers": {nom: contenu.hex() for nom, contenu in self.fichiers.items()},
            }
            Path(fichier).write_text(json.dumps(memoire))
        elif "write-flash" in arguments:
            *_, adresse, fichier = arguments
            contenu = Path(fichier).read_bytes()
            if int(adresse, 0) == 0:
                memoire = json.loads(contenu)
                self.programme = bytes.fromhex(memoire["programme"])
                self.fichiers = {n: bytes.fromhex(c) for n, c in memoire["fichiers"].items()}
            else:
                assert int(adresse, 0) == ADRESSE_PROGRAMME
                self.programme = contenu
        else:
            raise ErreurMiseAJour(f"commande esptool inconnue du faux : {arguments}")
        self.redemarrages += 1
        return "Hard resetting via RTS pin...\n"


class FauxPortConsole:
    """Le port USB de la fausse carte, ouvert : ce que la console lit et écrit."""

    def __init__(self, carte: FausseCarteEsp32) -> None:
        self.carte = carte
        self.ferme = False
        self._entree = b""
        self._sortie = bytearray()
        # Fichier en cours de réception par XMODEM : son nom, ses données.
        self._xmodem: str | None = None
        self._recu = bytearray()
        self._attendu = 1
        # Au démarrage, la carte dit bonjour.
        self._dire("Grbl 3.9 [FluidNC faux '$' for help]")

    def _dire(self, *lignes: str) -> None:
        if not self.carte.muette:
            for ligne in lignes:
                self._sortie += (ligne + "\r\n").encode("ascii")

    def close(self) -> None:
        self.ferme = True

    def read(self, taille: int = 1) -> bytes:
        donnees = bytes(self._sortie[:taille])
        del self._sortie[:taille]
        return donnees

    def readline(self) -> bytes:
        fin = self._sortie.find(b"\n")
        taille = len(self._sortie) if fin < 0 else fin + 1
        return self.read(taille)

    def write(self, donnees: bytes) -> int:
        if self.ferme:
            raise OSError("port fermé")
        if self.carte.muette:
            return len(donnees)
        self._entree += donnees
        while self._entree:
            if self._xmodem is not None:
                if not self._recevoir_xmodem():
                    break
            elif b"\n" in self._entree:
                ligne, self._entree = self._entree.split(b"\n", 1)
                self._executer(ligne.decode("ascii").strip())
            else:
                break
        return len(donnees)

    def _executer(self, ligne: str) -> None:
        carte = self.carte
        if ligne == "$I":
            self._dire(f"[VER:{carte.version}:]", "[OPT:PH]", "ok")
        elif ligne == "$SS":
            lignes = [f"[MSG:INFO: FluidNC {carte.version}]"]
            if b"ERREUR" in carte.fichiers.get("config.yaml", b""):
                lignes.append("[MSG:ERR: Configuration is invalid]")
            self._dire(*lignes, "ok")
        elif ligne.startswith("$LocalFS/Show="):
            nom = ligne.split("=", 1)[1]
            if nom not in carte.fichiers:
                self._dire("error:60")
                return
            texte = carte.fichiers[nom].decode("ascii")
            self._dire(*texte.split("\n"), "ok")
        elif ligne.startswith("$Xmodem/Receive="):
            self._xmodem = ligne.split("=", 1)[1]
            self._recu = bytearray()
            self._attendu = 1
            self._sortie.append(DEBUT_CRC)
        elif ligne == "$Bye":
            carte.redemarrages += 1
            self._dire("[MSG:INFO: Restarting]", "Grbl 3.9 [FluidNC faux '$' for help]")
        elif ligne:
            self._dire("ok")

    def _recevoir_xmodem(self) -> bool:
        """Traite un paquet XMODEM entier ; rend False s'il n'est pas encore tout arrivé."""
        if self._entree[0] == EOT:
            self._entree = self._entree[1:]
            self._sortie.append(ACK)
            assert self._xmodem is not None
            self.carte.fichiers[self._xmodem] = bytes(self._recu)
            self._dire(f"[MSG:INFO: Received {len(self._recu)} bytes to file {self._xmodem}]", "ok")
            self._xmodem = None
            return True
        taille = 3 + TAILLE_BLOC + 2
        if len(self._entree) < taille:
            return False
        paquet, self._entree = self._entree[:taille], self._entree[taille:]
        donnees = paquet[3 : 3 + TAILLE_BLOC]
        bon = (
            paquet[0] == SOH
            and paquet[1] == self._attendu % 256
            and paquet[2] == 255 - paquet[1]
            and binascii.crc_hqx(donnees, 0).to_bytes(2, "big") == paquet[-2:]
        )
        if not bon:
            self._sortie.append(CAN)
            self._xmodem = None
            return True
        if self.carte.blocs_a_refuser:
            self.carte.blocs_a_refuser -= 1
            self._sortie.append(NAK)
            return True
        self._recu += donnees
        self._attendu += 1
        self._sortie.append(ACK)
        return True
