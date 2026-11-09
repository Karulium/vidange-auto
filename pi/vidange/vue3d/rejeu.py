"""Rejeu d'incident (fonction 55) : les positions des axes autour de chaque alarme.

Un petit fil relève les positions toutes les `periode_s` secondes et garde les `avant_s` dernières
secondes en mémoire. À chaque alarme du chef, ces secondes sont mises de côté, puis les `apres_s`
secondes suivantes sont ajoutées ; ensuite un fichier « donnees/rejeux/NNNNNNNN.json » est écrit
(NNNNNNNN = numéro de l'alarme dans le registre). Quand le dossier dépasse `dossier_max_mo`, les
plus vieux fichiers sont effacés.

Format du fichier (JSON, une position de chaque axe par ligne d'« echantillons ») :
    {"version": 1, "alarme": 12, "module": "...", "message": "...", "quand": "2026-11-09T10:00:00",
     "periode_s": 0.2, "axes": ["pont_x", ...], "zones_tenues": {"zone": "module"},
     "echantillons": [[-60.0, 1.035, null, ...], ...]}
Le premier nombre d'un échantillon est le temps (s) par rapport à l'alarme (négatif : avant).

Le chef appelle `recevoir` pendant qu'il tient son verrou : rien de lent ici. Tout ce fil peut
planter sans toucher la machine (règle 1) ; il ne commande rien.
"""

import json
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from vidange.chef import Alarme
from vidange.journal import donner_journal
from vidange.reglages import RejeuVue3d

journal = donner_journal("vue3d.rejeu")

DOSSIER_REJEUX = "rejeux"
VERSION = 1
Valeurs = dict[str, float | None]


class ErreurRejeu(Exception):
    """Pas de rejeu pour cette alarme (jamais enregistré, ou déjà effacé)."""


@dataclass
class _Attente:
    """Une alarme dont on attend encore la fin des `apres_s` secondes."""

    alarme: Alarme
    debut: float
    quand: str
    zones: dict[str, str]
    avant: list[tuple[float, Valeurs]]
    apres: list[tuple[float, Valeurs]] = field(default_factory=list)
    numero: int | None = None


class EnregistreurRejeu:
    def __init__(
        self,
        dossier_donnees: Path,
        reglages: RejeuVue3d,
        lire_positions: Callable[[], Valeurs],
        zones_tenues: Callable[[], dict[str, str]] | None = None,
        horloge: Callable[[], float] = time.monotonic,
        maintenant: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.dossier = dossier_donnees / DOSSIER_REJEUX
        self.reglages = reglages
        self._lire = lire_positions
        self._zones = zones_tenues
        self._horloge = horloge
        self._maintenant = maintenant
        # Les dernières secondes : autant de relevés qu'il en faut pour `avant_s`, plus un.
        place = int(reglages.avant_s / reglages.periode_s) + 2
        self._recent: deque[tuple[float, Valeurs]] = deque(maxlen=place)
        self._attentes: list[_Attente] = []
        self._verrou = threading.Lock()

    # ------------------------------------------------------------ côté chef et bilans

    def recevoir(self, alarme: Alarme) -> None:
        """Appelée par le chef à chaque nouvelle alarme (chef.sur_alarme) : rapide."""
        maintenant = self._horloge()
        try:
            valeurs = self._lire()
            zones = {} if self._zones is None else self._zones()
        except Exception as erreur:
            journal.warning("Positions illisibles à l'alarme de « %s » : %s", alarme.module, erreur)
            valeurs, zones = {}, {}
        with self._verrou:
            debut = maintenant - self.reglages.avant_s
            avant = [(t, v) for t, v in self._recent if debut <= t < maintenant]
            avant.append((maintenant, valeurs))
            self._attentes.append(
                _Attente(
                    alarme,
                    maintenant,
                    self._maintenant().isoformat(timespec="seconds"),
                    zones,
                    avant,
                )
            )

    def numero(self, alarme: Alarme, numero: int) -> None:
        """Le registre a noté l'alarme (Bilans.sur_numero) : son fichier portera ce numéro."""
        with self._verrou:
            for attente in self._attentes:
                if attente.alarme is alarme:
                    attente.numero = numero

    # ------------------------------------------------------------ le relevé

    def echantillonner(self) -> None:
        """Un relevé des positions : à garder, et à ajouter aux alarmes qui attendent leur fin."""
        maintenant = self._horloge()
        valeurs = self._lire()
        a_ecrire: list[_Attente] = []
        with self._verrou:
            self._recent.append((maintenant, valeurs))
            gardees = []
            for attente in self._attentes:
                if maintenant - attente.debut <= self.reglages.apres_s:
                    attente.apres.append((maintenant, valeurs))
                if maintenant - attente.debut < self.reglages.apres_s:
                    gardees.append(attente)
                elif attente.numero is not None:
                    a_ecrire.append(attente)
                elif maintenant - attente.debut > self.reglages.apres_s + self.reglages.avant_s:
                    journal.error(
                        "Rejeu perdu : l'alarme de « %s » n'a jamais eu de numéro",
                        attente.alarme.module,
                    )
                else:
                    gardees.append(attente)  # le bilan n'a pas encore rendu son numéro
            self._attentes = gardees
        for attente in a_ecrire:
            self._ecrire_sans_planter(attente)

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        """Le fil des relevés. À l'arrêt, les alarmes en attente sont écrites en l'état."""

        def boucle() -> None:
            while not arret.wait(self.reglages.periode_s):
                try:
                    self.echantillonner()
                except Exception:
                    journal.exception("Relevé des positions raté")
            self.terminer()

        fil = threading.Thread(target=boucle, name="rejeux", daemon=True)
        fil.start()
        return fil

    def terminer(self) -> None:
        with self._verrou:
            restantes, self._attentes = self._attentes, []
        for attente in restantes:
            if attente.numero is not None:
                self._ecrire_sans_planter(attente)

    # ------------------------------------------------------------ les fichiers

    def chemin(self, numero: int) -> Path:
        return self.dossier / f"{numero:08d}.json"

    def _ecrire_sans_planter(self, attente: _Attente) -> None:
        try:
            self._ecrire(attente)
        except OSError as erreur:
            journal.error("Rejeu de l'alarme n° %s pas écrit : %s", attente.numero, erreur)

    def _ecrire(self, attente: _Attente) -> None:
        assert attente.numero is not None
        echantillons = [*attente.avant, *attente.apres]
        axes = sorted({axe for _, valeurs in echantillons for axe in valeurs})
        lignes = [
            [round(t - attente.debut, 2), *(valeurs.get(axe) for axe in axes)]
            for t, valeurs in echantillons
        ]
        contenu: dict[str, Any] = {
            "version": VERSION,
            "alarme": attente.numero,
            "module": attente.alarme.module,
            "message": attente.alarme.message,
            "quand": attente.quand,
            "periode_s": self.reglages.periode_s,
            "axes": axes,
            "zones_tenues": attente.zones,
            "echantillons": lignes,
        }
        self.dossier.mkdir(parents=True, exist_ok=True)
        chemin = self.chemin(attente.numero)
        provisoire = chemin.with_suffix(".json.tmp")
        provisoire.write_text(
            json.dumps(contenu, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        os.replace(provisoire, chemin)
        journal.info("Rejeu de l'alarme n° %d écrit (%d relevés)", attente.numero, len(lignes))
        self.purger(garder=chemin)

    def purger(self, garder: Path | None = None) -> None:
        """Efface les plus vieux fichiers (numéros les plus bas) tant que le dossier déborde."""
        limite = int(self.reglages.dossier_max_mo * 1_000_000)
        fichiers = sorted(self.dossier.glob("*.json"))
        total = sum(f.stat().st_size for f in fichiers)
        for fichier in fichiers:
            if total <= limite:
                break
            if fichier == garder:
                continue
            total -= fichier.stat().st_size
            fichier.unlink()
            journal.info("Rejeu %s effacé (dossier plein)", fichier.name)

    def numeros(self) -> list[int]:
        """Les numéros d'alarme qui ont un rejeu, du plus récent au plus ancien."""
        if not self.dossier.is_dir():
            return []
        return sorted(
            (int(f.stem) for f in self.dossier.glob("*.json") if f.stem.isdigit()), reverse=True
        )

    def lire(self, numero: int) -> dict[str, Any]:
        chemin = self.chemin(numero)
        try:
            return json.loads(chemin.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ErreurRejeu(
                f"pas de rejeu pour l'alarme n° {numero} (jamais gardé, ou effacé)"
            ) from None
        except (OSError, ValueError) as erreur:
            raise ErreurRejeu(f"rejeu de l'alarme n° {numero} illisible : {erreur}") from None
