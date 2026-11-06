"""Sortie PWM matérielle du Pi 5 vers le module PWM → 0-10 V (consigne du ventilateur).

Comme `ServoPwm` (vidange/vision/dosage.py) : fichiers de Linux (/sys/class/pwm), aucune
bibliothèque. Le canal n'est préparé qu'à la première consigne : un Pi sans l'overlay PWM ne
fait pas tomber le reste du matériel. Le moteur EC s'arrête sans signal : à la fermeture, le
rapport est remis à 0.

Attention : si le programme du Pi s'arrête, Linux laisse le dernier rapport sortir. Le moteur est
aussi coupé par le relais 230 V `ventilateur_enceinte` (au repos si le Pi s'arrête).
"""

import time
from pathlib import Path

from vidange.entrees_sorties import SortiePwm
from vidange.materiel.puces import ErreurMateriel

# Linux crée le dossier du canal un instant après son « export » : au plus 50 × 10 ms.
ESSAIS_CREATION = 50
ATTENTE_CREATION_S = 0.01


class PwmLinux:
    def __init__(self, reglage: SortiePwm) -> None:
        self.reglage = reglage
        self._puce = Path(reglage.fichier)
        self._canal = self._puce / f"pwm{reglage.canal}"
        self._pret = False

    def _ecrire(self, chemin: Path, valeur: int) -> None:
        chemin.write_text(f"{valeur}\n")

    def _preparer(self) -> None:
        if not self._canal.exists():
            self._ecrire(self._puce / "export", self.reglage.canal)
            for _ in range(ESSAIS_CREATION):
                if (self._canal / "period").exists():
                    break
                time.sleep(ATTENTE_CREATION_S)
        self._ecrire(self._canal / "period", self.reglage.periode_us * 1000)
        self._pret = True

    def regler(self, rapport: float) -> None:
        """Rapport cyclique de 0 à 1. Lève ErreurMateriel si Linux refuse."""
        try:
            if not self._pret:
                self._preparer()
            duree_ns = round(rapport * self.reglage.periode_us * 1000)
            self._ecrire(self._canal / "duty_cycle", duree_ns)
            self._ecrire(self._canal / "enable", 1)
        except OSError as erreur:
            raise ErreurMateriel(
                f"sortie PWM {self.reglage.fichier}/pwm{self.reglage.canal} impossible "
                f"({erreur}) : overlay PWM activé dans config.txt ?"
            ) from None

    def fermer(self) -> None:
        if self._pret:
            try:
                self.regler(0.0)
            except ErreurMateriel:
                pass
