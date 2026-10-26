"""Santé de l'informatique du Pi (fonction 45).

Tous les « periode_min » : température du Pi, alimentation (tension trop faible, ralentissement),
place libre sur le SSD, mémoire vive, heure du Pi, âge de la dernière copie de secours.
Les valeurs sont notées dans le registre (mesures « temperature_pi », « disque_libre »,
« memoire_libre », capteur « pi ») ; un changement de niveau est écrit au journal.

Sur un PC (essais), ce qui n'existe pas (température, vcgencmd) donne « inconnu », sans erreur.
"""

import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vidange.fiabilite.constats import Constat, lancer_boucle
from vidange.journal import donner_journal
from vidange.registre import Registre
from vidange.reglages import ReglagesSante

journal = donner_journal("fiabilite.sante")

# Une heure du Pi avant cette année veut dire que l'horloge est fausse (pile vide, sans réseau).
ANNEE_MINIMALE = 2026

# Bits de « vcgencmd get_throttled » (documentation Raspberry Pi).
SOUS_TENSION = 0x1
RALENTI = 0x2 | 0x4 | 0x8
SOUS_TENSION_DEPUIS_DEMARRAGE = 0x10000
RALENTI_DEPUIS_DEMARRAGE = 0x20000 | 0x40000 | 0x80000

FICHIER_TEMPERATURE = Path("/sys/class/thermal/thermal_zone0/temp")
FICHIER_MEMOIRE = Path("/proc/meminfo")


def lire_temperature() -> float | None:
    try:
        return int(FICHIER_TEMPERATURE.read_text().strip()) / 1000
    except (OSError, ValueError):
        return None


def lire_alimentation() -> int | None:
    """Le mot « throttled » du Pi (tension, ralentissement), ou None hors d'un Pi."""
    try:
        sortie = subprocess.run(
            ["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=5, check=True
        ).stdout
        return int(sortie.strip().split("=")[1], 16)
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return None


def lire_memoire_libre_mo() -> float | None:
    try:
        for ligne in FICHIER_MEMOIRE.read_text().splitlines():
            if ligne.startswith("MemAvailable:"):
                return int(ligne.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def lire_disque_libre_go(dossier: Path) -> float:
    return shutil.disk_usage(dossier).free / 1e9


@dataclass
class Sondes:
    """Où lire la santé du Pi (les tests en donnent des fausses). None = pas disponible."""

    temperature_c: Callable[[], float | None] = lire_temperature
    alimentation: Callable[[], int | None] = lire_alimentation
    memoire_libre_mo: Callable[[], float | None] = lire_memoire_libre_mo
    disque_libre_go: Callable[[Path], float] = lire_disque_libre_go
    maintenant: Callable[[], datetime] = datetime.now


class Sante:
    def __init__(
        self,
        dossier_donnees: Path,
        reglages: ReglagesSante,
        registre: Registre | None = None,
        copies: Callable[[], list[Path]] = list,
        sondes: Sondes | None = None,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        """`copies` : les copies de secours du registre (SauvegardeQuotidienne.copies)."""
        self.dossier = dossier_donnees
        self.reglages = reglages
        self.registre = registre
        self._copies = copies
        self.sondes = sondes or Sondes()
        self._horloge = horloge
        self._debut = horloge()
        # Une mesure à la fois (le fil de la santé et la check-list peuvent demander ensemble).
        self._verrou = threading.RLock()
        self._derniers: list[Constat] | None = None
        self._niveaux: dict[str, str] = {}

    def constats(self) -> list[Constat]:
        """Les constats de la dernière mesure (mesure tout de suite s'il n'y en a pas eu)."""
        with self._verrou:
            return self._derniers if self._derniers is not None else self.mesurer()

    def mesurer(self) -> list[Constat]:
        """Mesure tout, note dans le registre, écrit au journal ce qui a changé."""
        with self._verrou:
            return self._mesurer()

    def _mesurer(self) -> list[Constat]:
        temperature = self.sondes.temperature_c()
        memoire = self.sondes.memoire_libre_mo()
        disque = self.sondes.disque_libre_go(self.dossier)
        constats = [
            self._temperature(temperature),
            self._alimentation(self.sondes.alimentation()),
            self._disque(disque),
            self._memoire(memoire),
            self._horloge_du_pi(self.sondes.maintenant()),
            self._copie_de_secours(),
        ]
        self._noter(
            [
                ("temperature_pi", temperature, "°C"),
                ("disque_libre", disque, "Go"),
                ("memoire_libre", memoire, "Mo"),
            ]
        )
        self._prevenir(constats)
        self._derniers = constats
        return constats

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        return lancer_boucle("sante", self.reglages.periode_min * 60, self.mesurer, arret)

    # ------------------------------------------------------------ chaque mesure

    def _temperature(self, valeur: float | None) -> Constat:
        sujet = "température du Pi"
        if valeur is None:
            return Constat(sujet, "inconnu", "illisible (pas sur un Pi ?)")
        if valeur >= self.reglages.temperature_pi_attention_c:
            return Constat(
                sujet,
                "attention",
                f"{valeur:.0f} °C (seuil {self.reglages.temperature_pi_attention_c:g} °C)",
                "Vérifier le ventilateur du Pi et l'aération de l'armoire.",
            )
        return Constat(sujet, "ok", f"{valeur:.0f} °C")

    @staticmethod
    def _alimentation(mot: int | None) -> Constat:
        sujet = "alimentation du Pi"
        quoi_tension = (
            "Vérifier l'alimentation du Pi (bloc 5 V 5 A) et son câble : une tension trop faible "
            "fait planter le Pi et peut abîmer le SSD."
        )
        if mot is None:
            return Constat(sujet, "inconnu", "illisible (pas sur un Pi ?)")
        if mot & SOUS_TENSION:
            return Constat(sujet, "attention", "tension trop faible en ce moment", quoi_tension)
        if mot & SOUS_TENSION_DEPUIS_DEMARRAGE:
            texte = "tension trop faible depuis le démarrage"
            return Constat(sujet, "attention", texte, quoi_tension)
        if mot & (RALENTI | RALENTI_DEPUIS_DEMARRAGE):
            return Constat(
                sujet,
                "attention",
                "le Pi s'est ralenti (chaleur)",
                "Vérifier le ventilateur du Pi et l'aération de l'armoire.",
            )
        return Constat(sujet, "ok", "normale")

    def _disque(self, libre_go: float) -> Constat:
        sujet = "disque du Pi"
        texte = f"{libre_go:.1f} Go libres"
        quoi_faire = (
            "Faire de la place : copier puis effacer de vieilles photos (dossier des données, "
            "photos) ; vérifier que les copies de secours ne s'entassent pas."
        )
        if libre_go < self.reglages.disque_libre_minimum_go:
            return Constat(sujet, "bloquant", texte, quoi_faire)
        if libre_go < self.reglages.disque_libre_attention_go:
            return Constat(sujet, "attention", texte, quoi_faire)
        return Constat(sujet, "ok", texte)

    def _memoire(self, libre_mo: float | None) -> Constat:
        sujet = "mémoire du Pi"
        if libre_mo is None:
            return Constat(sujet, "inconnu", "illisible")
        texte = f"{libre_mo:.0f} Mo libres"
        if libre_mo < self.reglages.memoire_libre_attention_mo:
            return Constat(
                sujet,
                "attention",
                texte,
                "Redémarrer le programme quand la machine est à l'arrêt ; si ça revient, "
                "le signaler (le programme garde peut-être trop de choses en mémoire).",
            )
        return Constat(sujet, "ok", texte)

    @staticmethod
    def _horloge_du_pi(maintenant: datetime) -> Constat:
        sujet = "heure du Pi"
        texte = maintenant.strftime("%d/%m/%Y %H:%M")
        if maintenant.year < ANNEE_MINIMALE:
            return Constat(
                sujet,
                "attention",
                f"{texte} : l'heure est fausse",
                "Vérifier la pile de l'horloge du Pi 5, puis remettre l'heure (réseau, ou "
                "« sudo date -s ») : sinon les dates du registre sont fausses.",
            )
        return Constat(sujet, "ok", texte)

    def _copie_de_secours(self) -> Constat:
        sujet = "copie de secours"
        quoi_faire = "Regarder dans le journal pourquoi la copie de secours quotidienne échoue."
        copies = self._copies()
        age_max_h = self.reglages.sauvegarde_age_max_h
        if not copies:
            if self._horloge() - self._debut < age_max_h * 3600:
                return Constat(sujet, "inconnu", "pas encore de copie")
            return Constat(sujet, "attention", "aucune copie de secours", quoi_faire)
        try:
            date_copie = copies[-1].stat().st_mtime
        except OSError:
            return Constat(sujet, "inconnu", "copie illisible")
        age_h = (self.sondes.maintenant().timestamp() - date_copie) / 3600
        texte = f"dernière copie il y a {age_h:.0f} h"
        if age_h > age_max_h:
            return Constat(sujet, "attention", texte, quoi_faire)
        return Constat(sujet, "ok", texte)

    # ------------------------------------------------------------ registre et journal

    def _noter(self, mesures: list[tuple[str, float | None, str]]) -> None:
        if self.registre is None:
            return
        for nom, valeur, unite in mesures:
            if valeur is None:
                continue
            try:
                self.registre.noter_mesure(nom, round(valeur, 3), unite, capteur="pi")
            except Exception as erreur:
                journal.error("Mesure « %s » pas notée dans le registre : %s", nom, erreur)

    def _prevenir(self, constats: list[Constat]) -> None:
        """Au journal : seulement quand un niveau change (pas toutes les 5 minutes)."""
        for constat in constats:
            avant = self._niveaux.get(constat.sujet)
            self._niveaux[constat.sujet] = constat.niveau
            if avant == constat.niveau:
                continue
            if constat.niveau in ("attention", "bloquant"):
                journal.warning(
                    "Santé du Pi, %s : %s. %s", constat.sujet, constat.texte, constat.quoi_faire
                )
            elif avant in ("attention", "bloquant"):
                journal.info(
                    "Santé du Pi, %s : revenu à la normale (%s)", constat.sujet, constat.texte
                )
