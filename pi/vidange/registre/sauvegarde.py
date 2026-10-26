"""Copie de secours quotidienne de la base du registre.

Une fois par jour, à partir de l'heure réglée (programme.yaml → registre), une copie complète
et vérifiée de la base est posée dans le dossier des sauvegardes, sous le nom
« registre-AAAA-MM-JJ.sqlite ». On garde les dernières copies (nombre réglé), les plus
vieilles sont effacées. Si le Pi était éteint à l'heure dite, la copie se fait dès qu'il tourne.

Les photos ne sont pas dans cette copie (elles restent en fichiers) ; l'envoi des copies hors
de la machine viendra avec la file d'envoi (tâche 10).

Une copie ratée est notée dans le journal et réessayée plus tard : elle n'arrête jamais la machine.
"""

import re
import threading
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from vidange.journal import donner_journal
from vidange.registre.base import Registre, maintenant
from vidange.reglages import ReglagesRegistre

journal = donner_journal("registre")

_NOM = re.compile(r"^registre-(\d{4}-\d{2}-\d{2})\.sqlite$")


def nom_de_copie(jour: date) -> str:
    return f"registre-{jour.isoformat()}.sqlite"


class SauvegardeQuotidienne:
    def __init__(
        self,
        registre: Registre,
        dossier: Path,
        reglages: ReglagesRegistre,
        horloge: Callable[[], datetime] = maintenant,
    ) -> None:
        self.registre = registre
        self.dossier = dossier
        self.reglages = reglages
        self._horloge = horloge

    def copies(self) -> list[Path]:
        """Les copies quotidiennes présentes, de la plus vieille à la plus récente."""
        if not self.dossier.is_dir():
            return []
        return sorted(f for f in self.dossier.iterdir() if _NOM.match(f.name))

    def faire_si_besoin(self) -> Path | None:
        """Fait la copie du jour si l'heure est passée et qu'elle n'existe pas encore."""
        maintenant = self._horloge()
        if maintenant.hour < self.reglages.heure_sauvegarde:
            return None
        cible = self.dossier / nom_de_copie(maintenant.date())
        if cible.exists():
            return None
        return self.sauvegarder(cible)

    def sauvegarder(self, cible: Path | None = None) -> Path:
        """Fait une copie tout de suite (celle du jour par défaut), efface les plus vieilles."""
        if cible is None:
            cible = self.dossier / nom_de_copie(self._horloge().date())
        self.registre.copier_vers(cible)
        journal.info("Copie de secours du registre faite : %s", cible)
        self.nettoyer()
        return cible

    def nettoyer(self) -> list[Path]:
        """Efface les copies quotidiennes en trop (les plus vieilles)."""
        en_trop = self.copies()[: -self.reglages.copies_gardees]
        for copie in en_trop:
            copie.unlink()
            journal.info("Vieille copie de secours effacée : %s", copie)
        return en_trop

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        """Un fil qui regarde régulièrement s'il faut faire la copie du jour, jusqu'à `arret`."""

        def boucle() -> None:
            while True:
                try:
                    self.faire_si_besoin()
                except Exception:
                    journal.exception("Copie de secours du registre ratée, nouvel essai plus tard")
                if arret.wait(self.reglages.periode_verification_min * 60):
                    return

        fil = threading.Thread(target=boucle, name="sauvegarde-registre", daemon=True)
        fil.start()
        return fil
