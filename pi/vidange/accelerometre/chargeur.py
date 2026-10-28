"""Mise à jour du programme du RP2040 de l'accéléromètre par le fil série unique (tâche 16).

    chargeur = ChargeurAccelerometre(reglages.accelerometre, ouvrir_port("/dev/ttyAMA0", 115200))
    resultat = chargeur.mettre_a_jour(contenu_du_fichier_bin, etape, garder_copie)

Le RP2040 a un petit chargeur au début de sa flash, installé une fois à l'établi par l'USB
(questions et réponses : `accelerometre/src/chargeur_protocole.h`). Une mise à jour :

1. le Pi vérifie le fichier (fiche, taille, contrôle) avant de toucher à quoi que ce soit ;
2. il demande CHARGEUR au programme, qui redémarre dans le chargeur (« OK » coupé : la carte
   FluidNC n° 1 se met en alarme, c'est normal) ;
3. il relit le programme présent page par page et en garde une copie (retour en arrière) ;
4. il écrit le nouveau programme page par page ; le chargeur vérifie son contrôle et écrit sa
   fiche seulement à la fin : un programme à moitié écrit n'est jamais lancé ;
5. il lance le programme et vérifie qu'il répond avec le bon nom et le bon contrôle.
Si l'écriture rate, le Pi remet la copie du programme d'avant.

Le fil est celui de la liaison ordinaire (liaison.py) : elle doit être suspendue pendant ce temps
(`LiaisonAccelerometre.preter_le_fil`). Rien de tout cela ne protège : la sortie « OK » reste
coupée tout le temps du chargeur (sécurité positive).
"""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import serial

from vidange.accelerometre.fichier_programme import (
    ErreurFichier,
    Fiche,
    lire_fichier,
)
from vidange.accelerometre.liaison import PortAccelerometre
from vidange.accelerometre.protocole import (
    LIGNE_MAX_CHARGEUR,
    Decodeur,
    ErreurProtocole,
    lire_champs,
    trame,
)
from vidange.journal import donner_journal
from vidange.reglages import ReglagesAccelerometre

journal = donner_journal("accelerometre")

PAGE = 256
# Attente d'une réponse pendant l'écoute du démarrage du chargeur (s), en plus de la transmission.
ATTENTE_COURTE_S = 0.05


class ErreurChargeur(Exception):
    """Mise à jour de l'accéléromètre refusée ou ratée (avec la raison, en clair)."""


@dataclass(frozen=True)
class InfoChargeur:
    """Réponse du chargeur à CHARGEUR."""

    version: int
    fil: int
    sortie_ok: int
    place: int
    programme: str  # bon, absent ou abime
    fiche: Fiche | None  # celle du programme présent, si elle est lisible

    @classmethod
    def lire(cls, texte: str) -> "InfoChargeur":
        mot, champs = lire_champs(texte.replace("CHARGEUR pret", "CHARGEUR", 1))
        try:
            fiche = None
            if "nom" in champs:
                fiche = Fiche(
                    int(champs["adresse"], 16),
                    int(champs["taille"]),
                    int(champs["crc"], 16),
                    champs["nom"],
                )
            return cls(
                int(champs["version"]),
                int(champs["fil"]),
                int(champs["sortie_ok"]),
                int(champs["place"]),
                champs["programme"],
                fiche,
            )
        except (KeyError, ValueError):
            raise ErreurProtocole(f"réponse du chargeur mal formée « {texte} »") from None

    def decrire(self) -> str:
        if self.fiche is None:
            return f"programme {self.programme}"
        return f"programme « {self.fiche.nom} » ({self.programme}, contrôle {self.fiche.crc:08X})"


@dataclass(frozen=True)
class ResultatChargeur:
    avant: str  # le programme d'avant (nom), ou « aucun »
    apres: str
    message: str


def decrire_fiche(fiche: Fiche) -> str:
    return f"« {fiche.nom} » ({fiche.taille} octets, contrôle {fiche.crc:08X})"


class ChargeurAccelerometre:
    def __init__(
        self,
        reglages: ReglagesAccelerometre,
        ouvrir: Callable[[], PortAccelerometre],
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.reglages = reglages
        self._chargeur = reglages.chargeur
        self._vitesse = reglages.liaison.vitesse_bauds
        self._ouvrir = ouvrir
        self._horloge = horloge
        self._port: PortAccelerometre | None = None

    # ------------------------------------------------------------ fil

    @contextmanager
    def _fil(self) -> Iterator[None]:
        try:
            self._port = self._ouvrir()
        except Exception as erreur:
            raise ErreurChargeur(f"port série impossible à ouvrir : {erreur}") from None
        try:
            yield
        finally:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None

    def _transmission_s(self, question: str) -> float:
        # La question, puis la plus longue réponse ; 10 bits par octet.
        return (len(question) + LIGNE_MAX_CHARGEUR) * 10 / self._vitesse

    def _demander(self, question: str, attente_s: float) -> str | None:
        """Pose une question une fois ; rend la réponse (sans le contrôle), ou None."""
        assert self._port is not None
        mot = question.split(" ", 1)[0]
        decodeur = Decodeur(LIGNE_MAX_CHARGEUR)
        try:
            self._port.reset_input_buffer()
            self._port.write(trame(question, LIGNE_MAX_CHARGEUR))
            limite = self._horloge() + self._transmission_s(question) + attente_s
            while self._horloge() < limite:
                for texte in decodeur.ajouter(self._port.read(1024)):
                    if texte == question:
                        continue  # notre propre question (même fil)
                    if texte.split(" ", 1)[0] in (mot, "ERREUR"):
                        return texte
        except (OSError, serial.SerialException) as erreur:
            raise ErreurChargeur(f"liaison coupée : {erreur}") from None
        return None

    def _poser(self, question: str, attendu: str) -> str:
        """Pose une question (reposée sans réponse) ; rend la réponse « attendu… »."""
        attente_s = self._chargeur.attente_ecriture_ms / 1000
        for _ in range(self._chargeur.essais):
            reponse = self._demander(question, attente_s)
            if reponse is None:
                continue
            if reponse.startswith(attendu):
                return reponse
            nom = question.split(" ", 1)[0]
            raise ErreurChargeur(f"le RP2040 refuse « {nom} » : {reponse}")
        nom = question.split(" ", 1)[0]
        raise ErreurChargeur(
            f"pas de réponse du RP2040 à « {nom} » ({self._chargeur.essais} essais)"
        )

    # ------------------------------------------------------------ étapes

    def version(self) -> str | None:
        """La réponse du programme à VERSION, ou None s'il ne répond pas."""
        with self._fil():
            try:
                return self._poser("VERSION", "VERSION")
            except ErreurChargeur:
                return None

    def _passer_en_chargeur(self, duree_s: float, etape: Callable[[str], None]) -> InfoChargeur:
        """Demande CHARGEUR jusqu'à ce que le chargeur réponde (au plus duree_s)."""
        limite = self._horloge() + duree_s
        annonce = False
        while True:
            reponse = self._demander("CHARGEUR", ATTENTE_COURTE_S)
            if reponse == "ERREUR commande inconnue":
                raise ErreurChargeur(
                    "le programme du RP2040 ne connaît pas CHARGEUR : il date d'avant le chargeur. "
                    "Charger une fois accelerometre-complet.uf2 par l'USB "
                    "(accelerometre/essai-etabli.md, étape 3)"
                )
            if reponse == "CHARGEUR redemarre" and not annonce:
                etape("Le programme du RP2040 redémarre dans le chargeur (« OK » coupé)")
                annonce = True
            elif reponse is not None and reponse.startswith("CHARGEUR pret"):
                try:
                    info = InfoChargeur.lire(reponse)
                except ErreurProtocole as erreur:
                    raise ErreurChargeur(str(erreur)) from None
                break
            if self._horloge() >= limite:
                raise ErreurChargeur(
                    "le chargeur du RP2040 ne répond pas (boîtier alimenté ? fil série ? "
                    "chargeur installé ? voir accelerometre/essai-etabli.md, secours)"
                )
        etape(f"Chargeur du RP2040 prêt (version {info.version}) : {info.decrire()}")
        broches = self.reglages.broches
        if info.sortie_ok != broches.sortie_ok:
            etape(
                f"ATTENTION : le chargeur coupe « OK » sur la broche {info.sortie_ok}, "
                f"accelerometre.yaml dit {broches.sortie_ok} : réinstaller le chargeur par l'USB"
            )
        return info

    def _lire_copie(self, info: InfoChargeur, etape: Callable[[str], None]) -> bytes | None:
        """Le programme présent, relu (fichier .bin), ou None s'il n'est pas bon."""
        if info.programme != "bon" or info.fiche is None:
            etape(f"Pas de copie du programme présent ({info.programme})")
            return None
        fiche = info.fiche
        pages = (fiche.taille + PAGE - 1) // PAGE
        etape(f"Copie du programme présent {decrire_fiche(fiche)} : {pages} pages")
        octets = bytearray()
        for numero in range(pages):
            reponse = self._poser(f"LIRE {numero}", f"LIRE n={numero} ")
            try:
                octets += bytes.fromhex(reponse.split(" ", 2)[2])
            except (IndexError, ValueError):
                raise ErreurChargeur(f"page {numero} mal relue « {reponse[:40]}… »") from None
        programme = bytes(octets[: fiche.taille])
        try:
            fichier = fiche.octets() + programme
            lire_fichier(fichier)
        except ErreurFichier as erreur:
            raise ErreurChargeur(f"copie du programme présent fausse : {erreur}") from None
        return fichier

    def _ecrire(self, fiche: Fiche, programme: bytes, etape: Callable[[str], None]) -> None:
        pages = (fiche.taille + PAGE - 1) // PAGE
        etape(f"Écriture du programme {decrire_fiche(fiche)} : {pages} pages")
        self._poser(
            f"DEBUT adresse={fiche.adresse:08X} taille={fiche.taille} crc={fiche.crc:08X} "
            f"nom={fiche.nom}",
            "DEBUT ok",
        )
        for numero in range(pages):
            page = programme[numero * PAGE : (numero + 1) * PAGE]
            self._poser(f"ECRIRE {numero} {page.hex().upper()}", f"ECRIRE ok n={numero}")
            if pages >= 8 and (numero + 1) % (pages // 4) == 0 and numero + 1 < pages:
                etape(f"Écriture : {100 * (numero + 1) // pages} %")
        self._poser("FIN", "FIN ok")
        etape("Programme écrit et vérifié par le chargeur (contrôle juste)")

    def _lancer(self, fiche: Fiche, etape: Callable[[str], None]) -> None:
        self._poser("LANCER", "LANCER ok")
        etape("Programme lancé")
        limite = self._horloge() + self._chargeur.redemarrage_s
        attendu = f"VERSION nom={fiche.nom} taille={fiche.taille} crc={fiche.crc:08X}"
        while True:
            reponse = self._demander("VERSION", ATTENTE_COURTE_S)
            if reponse == attendu:
                etape(f"Le programme répond : {decrire_fiche(fiche)}")
                return
            if reponse is not None:
                raise ErreurChargeur(f"après le lancement, le RP2040 répond « {reponse} »")
            if self._horloge() >= limite:
                raise ErreurChargeur("après le lancement, le programme ne répond pas")

    # ------------------------------------------------------------ ce qu'on lance

    def mettre_a_jour(
        self,
        fichier: bytes,
        etape: Callable[[str], None],
        garder_copie: Callable[[bytes], object] | None = None,
        attendre_s: float | None = None,
    ) -> ResultatChargeur:
        """Écrit le programme du fichier .bin. `garder_copie` reçoit le programme d'avant.

        `attendre_s` : temps laissé pour trouver le chargeur (secours : le temps de couper et
        remettre l'alimentation du boîtier) ; par défaut « redemarrage_s ».
        """
        try:
            fiche, programme = lire_fichier(fichier)
        except ErreurFichier as erreur:
            raise ErreurChargeur(f"fichier refusé : {erreur}") from None
        etape(f"Fichier vérifié : {decrire_fiche(fiche)}")
        with self._fil():
            info = self._passer_en_chargeur(
                self._chargeur.redemarrage_s if attendre_s is None else attendre_s, etape
            )
            avant = info.fiche.nom if info.fiche is not None else "aucun"
            copie = None
            try:
                copie = self._lire_copie(info, etape)
                if copie is not None and garder_copie is not None:
                    garder_copie(copie)
                self._ecrire(fiche, programme, etape)
                self._lancer(fiche, etape)
            except ErreurChargeur as erreur:
                raise ErreurChargeur(f"{erreur}{self._rattraper(info, copie, etape)}") from None
        message = f"programme {decrire_fiche(fiche)} installé dans l'accéléromètre"
        journal.warning("Accéléromètre : %s (avant : %s)", message, avant)
        return ResultatChargeur(avant, fiche.nom, message)

    def _rattraper(self, info: InfoChargeur, copie: bytes | None, etape) -> str:
        """Après une erreur : relance le programme d'avant (ou le réécrit). Rend une explication."""
        try:
            reponse = self._demander("CHARGEUR", ATTENTE_COURTE_S)
            if reponse is not None and "programme=bon" in reponse and info.fiche is not None:
                etape("Le programme d'avant est intact : relance")
                self._lancer(info.fiche, etape)
                return " ; le programme d'avant a été relancé"
            if copie is not None:
                etape("Remise du programme d'avant (copie)")
                fiche, programme = lire_fichier(copie)
                self._ecrire(fiche, programme, etape)
                self._lancer(fiche, etape)
                return " ; le programme d'avant a été remis"
        except (ErreurChargeur, ErreurFichier) as erreur:
            return f" ; programme d'avant pas remis non plus ({erreur})"
        return " ; le RP2040 reste dans son chargeur, « OK » coupé : refaire la mise à jour"
