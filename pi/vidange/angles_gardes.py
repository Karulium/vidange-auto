"""Les angles gardés au redémarrage : la rotation de la griffe et celle de la tête de préhension.

    garde = AnglesGardes(donnees / "angles.json")
    garde.noter("prehension_a", 370.0, en_rotation=True)   # avant une rotation
    garde.noter("prehension_a", 372.5)                     # à l'arrêt
    garde.lire("prehension_a")      # AngleGarde(angle_deg=372.5, en_rotation=False), ou None

Les cartes FluidNC oublient leurs positions à la coupure. Pour la prise d'origine, le Pi garde dans
un fichier (il survit à une coupure, comme le mode de la machine) :
- la tête de préhension : son angle CUMULÉ (tours compris, ± 500° à cause du cordon spiralé) :
  il sert de contrôle du compte-tours (décisions, « Origine de la rotation de la tête », 05/11) ;
- la griffe : sa dernière rotation connue (la prise d'origine ne monte pas Z si elle n'était pas
  bras le long du pont, PR n° 56, point 4).
« en_rotation » : noté avant une rotation, effacé à l'arrêt : vrai après une coupure en pleine
rotation. Le fichier est réécrit d'un coup (fichier provisoire, puis remplacé) : jamais à moitié.
"""

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from vidange.journal import donner_journal

journal = donner_journal("angles_gardes")


@dataclass(frozen=True)
class AngleGarde:
    angle_deg: float
    # Vrai si la coupure est arrivée pendant une rotation (l'angle est celui du départ).
    en_rotation: bool = False


class AnglesGardes:
    def __init__(self, fichier: Path) -> None:
        self.fichier = fichier
        self._verrou = threading.Lock()
        self._angles = self._lire_fichier()

    def _lire_fichier(self) -> dict[str, AngleGarde]:
        if not self.fichier.exists():
            return {}
        try:
            donnees = json.loads(self.fichier.read_text(encoding="utf-8"))
            return {
                nom: AngleGarde(float(v["angle_deg"]), bool(v.get("en_rotation", False)))
                for nom, v in donnees.items()
            }
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as erreur:
            journal.warning("Fichier des angles gardés illisible (%s) : angles inconnus", erreur)
            return {}

    def lire(self, axe: str) -> AngleGarde | None:
        """Le dernier angle noté de cet axe (None : jamais noté, ou fichier illisible)."""
        with self._verrou:
            return self._angles.get(axe)

    def noter(self, axe: str, angle_deg: float, en_rotation: bool = False) -> None:
        with self._verrou:
            nouveau = AngleGarde(round(angle_deg, 3), en_rotation)
            if self._angles.get(axe) == nouveau:
                return
            self._angles[axe] = nouveau
            donnees = {
                nom: {"angle_deg": a.angle_deg, "en_rotation": a.en_rotation}
                for nom, a in self._angles.items()
            }
            try:
                self.fichier.parent.mkdir(parents=True, exist_ok=True)
                provisoire = self.fichier.with_suffix(".tmp")
                provisoire.write_text(json.dumps(donnees), encoding="utf-8")
                os.replace(provisoire, self.fichier)
            except OSError as erreur:
                journal.error("Angles gardés : écriture impossible (%s)", erreur)
