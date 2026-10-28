"""Apprendre les doses de la griffe : poids ≈ densité × volume pris.

    doses = Doses(reglages.machine.griffe)
    ouverture = doses.ouverture_pour(1.8, enfoncement_m=0.01, lieu="couche")
    doses.noter(Prise(...))     # après la pesée : la densité du fût s'apprend
    doses.nouveau_fut()         # au « Prêt » d'un nouveau fût

Le volume vient de la table (ouverture, enfoncement) de machine.yaml. La densité est apprise sur
les dernières prises du fût (« prises_apprises ») ; avant « prises_avant_apprentissage » prises,
c'est la densité par défaut. Les prises près de la paroi et au fond ont leur propre correction
(densité × facteur), apprise à part. Tout est noté dans le registre (table prises_griffe).
"""

import math
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
from statistics import median
from typing import Literal

from vidange.reglages import Griffe, TableVolumes

Lieu = Literal["couche", "paroi", "fond"]


@dataclass(frozen=True)
class Prise:
    """Une prise pesée, telle que le Pi la note."""

    lieu: Lieu
    ouverture: float
    enfoncement_m: float
    bouchees: int
    # Niveau : bas du godet au contact (m) ; position du mât dans le fût (m).
    niveau_z: float | None
    x: float
    y: float
    poids_kg: float
    volume_l: float


def _entre(valeurs: list[float], valeur: float) -> tuple[int, float]:
    """Indice i et fraction t tels que valeur ≈ valeurs[i] + t × (valeurs[i+1] − valeurs[i])."""
    if len(valeurs) == 1:
        return 0, 0.0
    valeur = min(max(valeur, valeurs[0]), valeurs[-1])
    i = min(bisect_right(valeurs, valeur) - 1, len(valeurs) - 2)
    return i, (valeur - valeurs[i]) / (valeurs[i + 1] - valeurs[i])


def volume_l(table: TableVolumes, ouverture: float, enfoncement_m: float) -> float:
    """Volume pris (L) d'après la table, entre ses lignes et ses colonnes (hors table : bord)."""
    i, t = _entre(table.ouvertures, ouverture)
    j, u = _entre(table.enfoncements_m, enfoncement_m)

    def case(ligne: int, colonne: int) -> float:
        return table.litres[ligne][min(colonne, len(table.enfoncements_m) - 1)]

    haut = case(i, j) + u * (case(i, j + 1) - case(i, j))
    bas = case(i + 1, j) + u * (case(i + 1, j + 1) - case(i + 1, j))
    return haut + t * (bas - haut)


def ouverture_pour_volume(table: TableVolumes, litres: float, enfoncement_m: float) -> float:
    """L'ouverture qui prend ce volume (la table grandit avec l'ouverture)."""
    volumes = [volume_l(table, ouverture, enfoncement_m) for ouverture in table.ouvertures]
    if litres <= volumes[0]:
        return table.ouvertures[0]
    if litres >= volumes[-1]:
        return table.ouvertures[-1]
    i = bisect_right(volumes, litres) - 1
    t = (litres - volumes[i]) / (volumes[i + 1] - volumes[i])
    return table.ouvertures[i] + t * (table.ouvertures[i + 1] - table.ouvertures[i])


class Doses:
    def __init__(self, reglages: Griffe) -> None:
        self.reglages = reglages
        self.doses = reglages.doses
        self._prises: deque[Prise] = deque(maxlen=200)

    def nouveau_fut(self) -> None:
        self._prises.clear()

    @property
    def prises(self) -> tuple[Prise, ...]:
        return tuple(self._prises)

    def noter(self, prise: Prise) -> None:
        if prise.volume_l > 0:
            self._prises.append(prise)

    def _densites(self, lieu: Lieu) -> list[float]:
        return [p.poids_kg / p.volume_l for p in self._prises if p.lieu == lieu]

    def densite(self, lieu: Lieu = "couche") -> float:
        """Densité (kg/L) apprise sur les dernières prises du fût, ou celle par défaut."""
        doses = self.doses
        couche = self._densites("couche")
        if len(couche) >= doses.prises_avant_apprentissage:
            base = median(couche[-doses.prises_apprises :])
        else:
            base = doses.densite_defaut_kg_l
        if lieu == "couche":
            return base
        a_part = self._densites(lieu)
        if len(a_part) >= doses.prises_avant_correction:
            return median(a_part[-doses.prises_apprises :])
        facteur = doses.correction_paroi if lieu == "paroi" else doses.correction_fond
        return base * facteur

    def ouverture_pour(
        self, poids_kg: float, enfoncement_m: float, lieu: Lieu = "couche", maximum: float = 1.0
    ) -> float:
        """L'ouverture du godet pour prendre ce poids (au plus `maximum` et 3 L)."""
        litres = min(poids_kg / self.densite(lieu), self.reglages.prise.volume_max_l)
        ouverture = ouverture_pour_volume(self.reglages.volumes, litres, enfoncement_m)
        return min(ouverture, maximum)

    def volume(self, ouverture: float, enfoncement_m: float) -> float:
        return volume_l(self.reglages.volumes, ouverture, enfoncement_m)

    def prises_par_couche(self, dose_kg: float) -> int:
        """Nombre de prises pour une couche (au plus 3 L par prise)."""
        litres = dose_kg / self.densite()
        volume_max = min(self.reglages.prise.volume_max_l, self.volume(1.0, math.inf))
        return max(1, -int(-litres // volume_max))
