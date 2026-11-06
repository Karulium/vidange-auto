"""Verrous du Mycélium avec le chariot de remplissage et la caméra du dosage (agitateur FIXE
au-dessus du poste depuis le 01/11/2026, docs/decisions.md « Agitateur du mycélium FIXE »).

    regles = ReglesMycelium(reglages.machine)
    regles.refus_manivelle(cible, chariot, agitation)   # raison du refus, ou None
    regles.refus_demi_tour(pose, chariot, camera_pivote)  # le bocal peut-il se retourner ?
    regles.refus_chariot(pose, en_mouvement)             # le chariot de remplissage peut-il rouler
                                                         # près du poste ?

Une PoseAgitateur dit où est la manivelle (°). Le bocal est toujours au même endroit
(`mycelium → bocal`). Le chariot de remplissage est décrit par EtatChariot.
Les règles :
1. Manivelle EN HAUT seulement pour le demi-tour ; EN BAS pour la pose et la reprise du bocal par
   la préhension (décision du 05/11/2026), dès que le chariot de remplissage est au poste, et pour
   attendre. La manivelle ne quitte
   « en bas » (aller en haut, prise d'origine) que chariot à y ≥ y_ecarte_min (0,40) ; chariot
   plus près du poste, elle ne fait qu'aller en bas (chariot arrêté), ou secouer au dosage (seau
   au dosage, arrêtée pile en bas).
2. Demi-tour du bocal seulement manivelle en haut, chariot à y ≥ 0,40, caméra du dosage à 0°.
3. Le chariot de remplissage ne roule près du poste (et son plateau n'y monte) que manivelle en
   bas, agitateur arrêté (le Remplissage vérifie ses propres règles : bord du seau ≤ 0,68...).

Tous les chiffres viennent de machine.yaml (`mycelium`, formats de la griffe). Ces verrous ne
protègent que la MACHINE : la sécurité des personnes reste câblée.
"""

import math
from dataclasses import dataclass, replace

from vidange.reglages import FormatSeau, Machine

# Écart sous lequel deux valeurs sont égales (m ou °).
_EGAL = 1e-6


@dataclass(frozen=True)
class PoseAgitateur:
    angle: float  # manivelle (°)

    def avec(self, **valeurs: float) -> "PoseAgitateur":
        return replace(self, **valeurs)


@dataclass(frozen=True)
class EtatChariot:
    """Le chariot de remplissage, tel que son module le dit."""

    y: float
    # Hauteur du plateau (m).
    plateau_z: float
    # Arrêté (pas de trajet en cours).
    immobile: bool = True


def _m(valeur: float) -> str:
    return f"{valeur:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def ecart_angle(a: float, b: float) -> float:
    """Écart entre deux angles (°), de 0 à 180."""
    return abs((a - b + 180) % 360 - 180)


class ReglesMycelium:
    def __init__(self, machine: Machine) -> None:
        assert machine.mycelium is not None and machine.griffe is not None
        self.reglages = machine.mycelium
        self.formats = machine.griffe.formats

    # ------------------------------------------------------------ la manivelle

    def en_haut(self, pose: PoseAgitateur) -> bool:
        manivelle = self.reglages.manivelle
        return ecart_angle(pose.angle, manivelle.angle_haut_deg) <= manivelle.tolerance_deg + _EGAL

    def en_bas(self, pose: PoseAgitateur) -> bool:
        manivelle = self.reglages.manivelle
        bas = manivelle.angle_haut_deg + 180
        return ecart_angle(pose.angle, bas) <= manivelle.tolerance_deg + _EGAL

    def angle_proche(self, actuel: float, bas: bool) -> float:
        """L'angle « en haut » (ou « en bas ») le plus proche de l'angle actuel."""
        cible = self.reglages.manivelle.angle_haut_deg + (180 if bas else 0)
        return actuel + (cible - actuel + 180) % 360 - 180

    def bas_suivant(self, actuel: float, sens: int) -> float:
        """Le premier angle « en bas » atteint en tournant dans ce sens (+1 ou −1) : celui-ci
        si la manivelle y est déjà."""
        manivelle = self.reglages.manivelle
        tours = (actuel - manivelle.angle_haut_deg - 180) / 360
        marge = manivelle.tolerance_deg / 360
        tours = math.ceil(tours - marge) if sens > 0 else math.floor(tours + marge)
        return manivelle.angle_haut_deg + 180 + 360 * tours

    # ------------------------------------------------------------ le chariot de remplissage

    def chariot_ecarte(self, chariot: EtatChariot | None) -> bool:
        return chariot is not None and chariot.y >= self.reglages.chariot.y_ecarte_min - _EGAL

    def chariot_au_dosage(self, chariot: EtatChariot | None) -> bool:
        reglage = self.reglages.chariot
        return (
            chariot is not None
            and chariot.immobile
            and abs(chariot.y - reglage.y_dosage) <= reglage.tolerance_y_m + _EGAL
        )

    def plateau_dosage(self, format: FormatSeau) -> float:
        """Hauteur du plateau pendant le dosage : min(bord du seau − hauteur ; plateau maxi)."""
        assert format.hauteur is not None
        chariot = self.reglages.chariot
        return min(chariot.bord_seau_z - format.hauteur, chariot.plateau_max_z)

    def refus_plateau(self, format: FormatSeau, chariot: EtatChariot) -> str | None:
        voulu = self.plateau_dosage(format)
        if abs(chariot.plateau_z - voulu) > self.reglages.chariot.tolerance_plateau_m + _EGAL:
            return (
                f"plateau du chariot de remplissage à z {_m(chariot.plateau_z)} m, il faut "
                f"{_m(voulu)} m pour ce seau (bord du seau sous le bocal)"
            )
        return None

    def _y_ecarte(self) -> str:
        return _m(self.reglages.chariot.y_ecarte_min)

    # ------------------------------------------------------------ les verrous

    def refus_manivelle(
        self, cible: PoseAgitateur | None, chariot: EtatChariot | None, agitation: bool = False
    ) -> str | None:
        """La manivelle va à `cible` (None : prise d'origine, un tour lent). Chariot de
        remplissage à y ≥ 0,40 : tout est permis. Plus près du poste : seulement aller en bas,
        chariot arrêté, ou secouer au dosage (seau au dosage, arrêt pile en bas)."""
        if self.chariot_ecarte(chariot):
            return None
        if chariot is None:
            return "position du chariot de remplissage inconnue"
        if not chariot.immobile:
            return "la manivelle ne tourne pas pendant que le chariot de remplissage roule"
        if agitation:
            if self.chariot_au_dosage(chariot) and cible is not None and self.en_bas(cible):
                return None
            return (
                f"l'agitation ne se fait que seau au dosage (chariot de remplissage à y "
                f"{_m(self.reglages.chariot.y_dosage)} m) ou chariot à y ≥ {self._y_ecarte()} m"
            )
        if cible is not None and self.en_bas(cible):
            return None
        quoi = "la prise d'origine (tour lent)" if cible is None else "la manivelle hors du bas"
        return (
            f"{quoi} : chariot de remplissage à y {_m(chariot.y)} m, il doit être à y ≥ "
            f"{self._y_ecarte()} m (manivelle en bas dès que le chariot est au poste)"
        )

    def refus_demi_tour(
        self, pose: PoseAgitateur, chariot: EtatChariot | None, camera_pivote: bool = False
    ) -> str | None:
        """Le bocal ne se retourne que manivelle en haut, chariot de remplissage à y ≥ 0,40,
        caméra du dosage à 0° (tournée vers le bocal)."""
        if not self.en_haut(pose):
            return "le demi-tour du bocal ne se fait que manivelle en haut"
        if not self.chariot_ecarte(chariot):
            return (
                f"le demi-tour du bocal ne se fait que chariot de remplissage à y ≥ "
                f"{self._y_ecarte()} m"
            )
        if camera_pivote:
            return "le demi-tour du bocal ne démarre que caméra du dosage à 0° (vers le bocal)"
        return None

    def refus_chariot(self, pose: PoseAgitateur | None, en_mouvement: bool) -> str | None:
        """Le chariot de remplissage ne roule près du poste (et son plateau n'y monte) que
        manivelle en bas, agitateur arrêté."""
        if pose is None:
            return "position de la manivelle du mycélium inconnue"
        if en_mouvement:
            return "l'agitateur du mycélium bouge"
        if self.en_bas(pose):
            return None
        return (
            f"manivelle du mycélium à {pose.angle % 360:.0f}° : près du poste, le chariot de "
            "remplissage ne roule (et son plateau ne monte) que manivelle en bas"
        )
