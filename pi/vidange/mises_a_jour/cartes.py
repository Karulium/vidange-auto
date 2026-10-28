"""Mise à jour d'une carte ESP32 (FluidNC) par son câble USB, depuis le Pi.

    carte = CarteEsp32("portique", reglages.programme.mises_a_jour.cartes, dossier,
                       trouver_port, ouvrir_console)
    carte.ecrire_programme(Path("fluidnc-3.9.5.bin"))   # programme de la carte (esptool)
    carte.envoyer_reglages(Path("fluidnc/portique.yaml"))   # son fichier config.yaml
    carte.revenir()                                     # remet la dernière copie
    carte.copies()                                      # copies gardées, la plus récente d'abord

Chaque changement se fait en trois temps :
1. copie de TOUTE la mémoire de la carte sur le Pi (programme et réglages ensemble,
   « esptool read-flash ») : c'est elle qu'on remet pour revenir en arrière ;
2. le changement ;
3. vérification : la carte redémarre et répond, sans erreur dans ses messages de démarrage
   (et ses réglages relus sont bien ceux envoyés). Si la vérification rate, la copie est remise
   toute seule et revérifiée.

La liaison ordinaire avec la carte doit être arrêtée pendant ce temps (le port USB ne s'ouvre
qu'une fois) : c'est le travail de MisesAJour (gestion.py), ou de l'outil « vidange-maj ».
Le programme des cartes vient de FluidNC (fichier « firmware.bin » de leurs versions) ; ses
réglages sont dans le dossier fluidnc/ du dépôt (un fichier par carte).
"""

import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import NoReturn, TypeVar

import yaml

from vidange.fluidnc.ports import ErreurFluidnc
from vidange.journal import donner_journal
from vidange.mises_a_jour.commun import ErreurMiseAJour, Lanceur, lancer_commande
from vidange.mises_a_jour.console import Console, PortConsole, meme_texte
from vidange.reglages import ReglagesMajCartes

# Premier octet d'un programme pour ESP32 (« image » d'esptool).
DEBUT_PROGRAMME = 0xE9
MO = 1024 * 1024
# Attente entre deux essais d'ouverture du port USB (pendant que la carte redémarre).
ATTENTE_PORT_S = 0.5

T = TypeVar("T")


def rien(_: str) -> None:
    """Pas d'affichage des étapes."""


@dataclass(frozen=True)
class Resultat:
    """Le compte rendu d'un changement."""

    message: str
    avant: str | None  # version du programme de la carte avant (None : inconnue)
    apres: str  # version après


@dataclass(frozen=True)
class Copie:
    """Une copie de toute la mémoire d'une carte, faite avant un changement."""

    nom: str  # « 20261027-140212-01 » : le nom de ses fichiers
    quand: str
    raison: str  # « avant le programme « fluidnc-3.9.5.bin » »...
    version: str | None  # version du programme de la carte à ce moment (None : inconnue)


def verifier_contenu_programme(nom: str, contenu: bytes, reglages: ReglagesMajCartes) -> None:
    """Refuse ce qui ne ressemble pas à un programme pour ESP32."""
    if len(contenu) > reglages.taille_max_mo * MO:
        raise ErreurMiseAJour(f"« {nom} » : trop gros (plus de {reglages.taille_max_mo:g} Mo)")
    if not contenu or contenu[0] != DEBUT_PROGRAMME:
        raise ErreurMiseAJour(
            f"« {nom} » n'est pas un programme pour ESP32 (prendre le fichier "
            "« firmware.bin » de la version de FluidNC)"
        )


def verifier_programme(fichier: Path, reglages: ReglagesMajCartes) -> None:
    try:
        contenu = fichier.read_bytes()
    except OSError as erreur:
        raise ErreurMiseAJour(f"fichier de programme illisible : {erreur}") from None
    verifier_contenu_programme(fichier.name, contenu, reglages)


def lire_reglages_fluidnc(fichier: Path) -> bytes:
    """Le contenu d'un fichier de réglages FluidNC, s'il est en YAML lisible."""
    try:
        contenu = fichier.read_bytes()
    except OSError:
        raise ErreurMiseAJour(f"pas de fichier de réglages « {fichier} »") from None
    try:
        texte = contenu.decode("ascii")
        donnees = yaml.safe_load(texte)
    except (UnicodeDecodeError, yaml.YAMLError) as erreur:
        raise ErreurMiseAJour(
            f"« {fichier.name} » illisible (YAML, sans accents) : {erreur}"
        ) from None
    if not isinstance(donnees, dict) or not donnees:
        raise ErreurMiseAJour(f"« {fichier.name} » : pas de réglages dedans")
    return contenu


class CarteEsp32:
    def __init__(
        self,
        nom: str,
        reglages: ReglagesMajCartes,
        dossier: Path,
        trouver_port: Callable[[], str],
        ouvrir_console: Callable[[], PortConsole],
        lancer: Lanceur = lancer_commande,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.nom = nom
        self.reglages = reglages
        # Les copies de la mémoire de cette carte.
        self.dossier = dossier / nom
        self._trouver_port = trouver_port
        self._ouvrir_console = ouvrir_console
        self._lancer = lancer
        self._horloge = horloge
        self._journal = donner_journal(f"mises_a_jour.{nom}")

    # ------------------------------------------------------------ outils

    def _esptool(self, *arguments: str) -> str:
        try:
            port = self._trouver_port()
        except ErreurFluidnc as erreur:
            raise ErreurMiseAJour(str(erreur)) from None
        commande = [
            sys.executable,
            "-m",
            "esptool",
            "--port",
            port,
            "--baud",
            str(self.reglages.vitesse_bauds),
            *arguments,
        ]
        self._journal.info("esptool : %s", " ".join(commande[3:]))
        return self._lancer(commande, self.reglages.duree_max_esptool_s)

    def _avec_console(self, faire: Callable[[Console], T], attendre: bool = True) -> T:
        """Ouvre la console (en laissant à l'USB le temps de revenir), fait, puis ferme."""
        fin = self._horloge() + (self.reglages.delai_reponse_s if attendre else 0)
        while True:
            try:
                port = self._ouvrir_console()
                break
            except (OSError, ErreurFluidnc) as erreur:
                if self._horloge() >= fin:
                    raise ErreurMiseAJour(
                        f"port USB de la carte impossible à ouvrir : {erreur}"
                    ) from None
                time.sleep(ATTENTE_PORT_S)
        console = Console(port, self.reglages.delai_commande_s, self._horloge)
        try:
            return faire(console)
        except OSError as erreur:
            raise ErreurMiseAJour(f"liaison USB coupée : {erreur}") from None
        finally:
            console.fermer()

    # ------------------------------------------------------------ ce qu'on sait

    def lire_version(self) -> str | None:
        """La version du programme de la carte, ou None si elle ne répond pas."""
        try:
            return self._avec_console(lambda console: console.version(), attendre=False)
        except ErreurMiseAJour as erreur:
            self._journal.warning("Version de la carte illisible : %s", erreur)
            return None

    def verifier(self, reglages_attendus: bytes | None = None) -> str:
        """La carte (re)démarrée répond, sans erreur au démarrage. Rend sa version."""

        def faire(console: Console) -> str:
            version = console.attendre_reponse(self.reglages.delai_reponse_s)
            erreurs = console.erreurs_demarrage()
            if erreurs:
                raise ErreurMiseAJour("erreurs au démarrage de la carte : " + " ; ".join(erreurs))
            if reglages_attendus is not None:
                relus = console.lire_fichier(self.reglages.fichier_reglages)
                if not meme_texte(relus, reglages_attendus.decode("ascii")):
                    raise ErreurMiseAJour(
                        "les réglages relus dans la carte ne sont pas ceux envoyés"
                    )
            return version

        return self._avec_console(faire)

    def copies(self) -> list[Copie]:
        """Les copies gardées, la plus récente d'abord."""
        copies = []
        for fichier in sorted(self.dossier.glob("*.json"), reverse=True):
            if not fichier.with_suffix(".bin").is_file():
                continue
            try:
                copies.append(Copie(**json.loads(fichier.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError) as erreur:
                self._journal.warning("Copie « %s » illisible : %s", fichier.name, erreur)
        return copies

    # ------------------------------------------------------------ copies

    def sauvegarder(self, raison: str, version: str | None) -> Copie:
        """Copie toute la mémoire de la carte sur le Pi (une minute ou plus)."""
        self.dossier.mkdir(parents=True, exist_ok=True)
        # Le numéro de fin range dans l'ordre les copies faites dans la même seconde.
        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        rangs = [int(f.stem.rsplit("-", 1)[1]) for f in self.dossier.glob(f"{base}-[0-9]*.json")]
        nom = f"{base}-{max(rangs, default=0) + 1:02d}"
        fichier = self.dossier / f"{nom}.bin"
        provisoire = self.dossier / f"{nom}.provisoire"
        try:
            self._esptool("read-flash", "0", "ALL", str(provisoire))
            if not provisoire.is_file() or provisoire.stat().st_size == 0:
                raise ErreurMiseAJour("esptool n'a rien copié")
            os.replace(provisoire, fichier)
        finally:
            provisoire.unlink(missing_ok=True)
        quand = datetime.now().astimezone().isoformat(timespec="seconds")
        copie = Copie(nom, quand, raison, version)
        (self.dossier / f"{nom}.json").write_text(
            json.dumps(asdict(copie), ensure_ascii=False), encoding="utf-8"
        )
        self._journal.info("Copie de la mémoire de la carte : %s (%s)", nom, raison)
        for vieille in self.copies()[self.reglages.copies_gardees :]:
            for suffixe in (".bin", ".json"):
                (self.dossier / f"{vieille.nom}{suffixe}").unlink(missing_ok=True)
        return copie

    def _remettre(self, copie: Copie) -> None:
        self._esptool("write-flash", "0", str(self.dossier / f"{copie.nom}.bin"))

    def _secours(
        self, copie: Copie, erreur: ErreurMiseAJour, etape: Callable[[str], None]
    ) -> NoReturn:
        """Le changement a raté : on remet la copie faite juste avant, et on revérifie."""
        self._journal.error("Changement raté (%s) : remise de la copie %s", erreur, copie.nom)
        etape(f"Raté ({erreur}) : remise de la copie d'avant")
        try:
            self._remettre(copie)
            version = self.verifier()
        except ErreurMiseAJour as autre:
            raise ErreurMiseAJour(
                f"{erreur}. La copie d'avant n'a pas pu être remise non plus ({autre}) : "
                "voir « Secours » dans pi/systeme/essai-mises-a-jour.md"
            ) from None
        raise ErreurMiseAJour(
            f"{erreur}. L'ancienne version est remise, la carte répond ({version})."
        ) from None

    # ------------------------------------------------------------ changements

    def ecrire_programme(self, fichier: Path, etape: Callable[[str], None] = rien) -> Resultat:
        """Écrit un nouveau programme dans la carte. Rend le compte rendu, en clair."""
        verifier_programme(fichier, self.reglages)
        etape("Lecture de la version actuelle")
        avant = self.lire_version()
        etape("Copie de toute la mémoire de la carte (une minute ou plus)")
        copie = self.sauvegarder(f"avant le programme « {fichier.name} »", avant)
        try:
            etape(f"Écriture du programme « {fichier.name} »")
            self._esptool("write-flash", hex(self.reglages.adresse_programme), str(fichier))
            etape("Vérification : la carte redémarre et répond")
            apres = self.verifier()
        except ErreurMiseAJour as erreur:
            self._secours(copie, erreur, etape)
        message = f"programme « {fichier.name} » écrit ; la carte répond : {apres}"
        return Resultat(message, avant, apres)

    def envoyer_reglages(self, fichier: Path, etape: Callable[[str], None] = rien) -> Resultat:
        """Envoie le fichier de réglages FluidNC de la carte, puis la redémarre."""
        contenu = lire_reglages_fluidnc(fichier)
        etape("Lecture de la version actuelle")
        avant = self.lire_version()
        if avant is None:
            raise ErreurMiseAJour(
                "la carte ne répond pas : ses réglages ne peuvent pas être envoyés (écrire "
                "d'abord son programme, ou revenir à une copie)"
            )
        etape("Copie de toute la mémoire de la carte (une minute ou plus)")
        copie = self.sauvegarder(f"avant les réglages « {fichier.name} »", avant)
        nom = self.reglages.fichier_reglages
        delai = self.reglages.delai_reponse_s
        try:
            etape(f"Envoi de « {fichier.name} » (devient « {nom} » dans la carte), redémarrage")

            def envoyer(console: Console) -> None:
                console.envoyer_fichier(nom, contenu)
                console.redemarrer(delai)

            self._avec_console(envoyer)
            etape("Vérification : la carte redémarre, répond, et ses réglages sont les bons")
            apres = self.verifier(contenu)
        except ErreurMiseAJour as erreur:
            self._secours(copie, erreur, etape)
        message = f"réglages « {fichier.name} » envoyés ; la carte répond : {apres}"
        return Resultat(message, avant, apres)

    def revenir(
        self, nom_copie: str | None = None, etape: Callable[[str], None] = rien
    ) -> Resultat:
        """Remet une copie (la plus récente si aucune n'est nommée)."""
        copies = self.copies()
        if nom_copie is None:
            if not copies:
                raise ErreurMiseAJour(f"aucune copie de la carte « {self.nom} » sur le Pi")
            choisie = copies[0]
        else:
            trouvees = [copie for copie in copies if copie.nom == nom_copie]
            if not trouvees:
                raise ErreurMiseAJour(f"pas de copie « {nom_copie} » pour la carte « {self.nom} »")
            choisie = trouvees[0]
        etape("Lecture de la version actuelle")
        avant = self.lire_version()
        etape("Copie de la mémoire actuelle (pour pouvoir y revenir)")
        try:
            self.sauvegarder(f"avant le retour à la copie {choisie.nom}", avant)
        except ErreurMiseAJour as erreur:
            # Pour sauver une carte, on remet la copie quand même.
            self._journal.error("Copie de la mémoire actuelle impossible : %s", erreur)
            etape(f"Copie impossible ({erreur}) : on remet quand même la copie choisie")
        etape(f"Remise de la copie {choisie.nom} ({choisie.raison})")
        self._remettre(choisie)
        etape("Vérification : la carte redémarre et répond")
        apres = self.verifier()
        message = f"copie {choisie.nom} remise ; la carte répond : {apres}"
        return Resultat(message, avant, apres)
