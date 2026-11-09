"""Copie de secours quotidienne de la base du registre.

Une fois par jour, à partir de l'heure réglée (programme.yaml → registre), une copie complète
et vérifiée de la base est posée dans le dossier des sauvegardes, sous le nom
« registre-AAAA-MM-JJ.sqlite ». On garde les dernières copies (nombre réglé), les plus
vieilles sont effacées. Si le Pi était éteint à l'heure dite, la copie se fait dès qu'il tourne.

Avec elle, une archive « fichiers-AAAA-MM-JJ.tar.gz » reprend les petits fichiers des données et
les comptes de la page web (fichiers_hors_git.py), pour remettre un Pi neuf en état (tâche 25).

Les photos ne sont pas dans cette copie (elles restent en fichiers). Chaque copie faite est
donnée à `apres_copie` : la file d'envoi l'emporte à la maison (vidange/envois).

Une copie ratée est notée dans le journal et réessayée plus tard : elle n'arrête jamais la machine.
"""

import re
import threading
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from vidange.journal import donner_journal
from vidange.registre.base import Registre, maintenant
from vidange.registre.fichiers_hors_git import est_une_archive, nom_de_archive
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
        apres_copie: Callable[[Path], None] | None = None,
        archiver_fichiers: Callable[[Path], Path] | None = None,
    ) -> None:
        self.registre = registre
        self.dossier = dossier
        self.reglages = reglages
        self._horloge = horloge
        self._apres_copie = apres_copie
        # Fabrique l'archive des fichiers hors Git à l'endroit donné (None : pas d'archive).
        self._archiver_fichiers = archiver_fichiers

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
        if self._apres_copie is not None:
            self._apres_copie(cible)
        self._archiver_les_fichiers()
        return cible

    def _archiver_les_fichiers(self) -> None:
        """L'archive des fichiers hors Git du jour (un échec ne gâche pas la copie du registre)."""
        if self._archiver_fichiers is None:
            return
        try:
            archive = self._archiver_fichiers(self.dossier / nom_de_archive(self._horloge().date()))
            journal.info("Copie de secours des fichiers hors Git faite : %s", archive)
            if self._apres_copie is not None:
                self._apres_copie(archive)
        except Exception:
            journal.exception("Copie de secours des fichiers hors Git ratée")

    def nettoyer(self) -> list[Path]:
        """Efface les copies quotidiennes en trop (les plus vieilles)."""
        en_trop = self.copies()[: -self.reglages.copies_gardees]
        for copie in en_trop:
            copie.unlink()
            journal.info("Vieille copie de secours effacée : %s", copie)
        archives = (
            sorted(f for f in self.dossier.iterdir() if est_une_archive(f.name))
            if self.dossier.is_dir()
            else []
        )
        for archive in archives[: -self.reglages.copies_gardees]:
            archive.unlink()
            journal.info("Vieille archive de secours effacée : %s", archive)
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
