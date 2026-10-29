"""Verrous du Mycélium avec le chariot de remplissage et la caméra du dosage (24/10/2026).

    regles = ReglesMycelium(reglages.machine)
    regles.refus_glissiere(pose, x, chariot)        # raison du refus, ou None
    regles.refus_manivelle(pose, chariot)
    regles.refus_chariot(pose, en_mouvement)        # le chariot de remplissage peut-il rouler ?
    regles.camera_peut_pivoter(pose)

Une PoseAgitateur dit où est l'agitateur : x sur sa glissière (m), angle de la manivelle (°).
Le chariot de remplissage est décrit par EtatChariot (son module n'est pas encore écrit).

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
    x: float  # glissière (m)
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
        self.course_x = machine.axes["agitateur_x"].course

    # ------------------------------------------------------------ où est l'agitateur

    def _a(self, x: float, cible: float) -> bool:
        return abs(x - cible) <= self.reglages.tolerance_x_m + _EGAL

    def au_garage(self, pose: PoseAgitateur) -> bool:
        return self._a(pose.x, self.reglages.garage_x)

    def au_demi_tour(self, pose: PoseAgitateur) -> bool:
        return self._a(pose.x, self.reglages.demi_tour_x)

    def au_dosage(self, pose: PoseAgitateur) -> bool:
        return self._a(pose.x, self.reglages.dosage_x)

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

    # ------------------------------------------------------------ les verrous

    def refus_glissiere(
        self, depart: PoseAgitateur, x: float, chariot: EtatChariot | None
    ) -> str | None:
        """L'agitateur ne roule que chariot de remplissage écarté, manivelle en haut."""
        debut, fin = self.course_x
        if not debut - _EGAL <= x <= fin + _EGAL:
            return f"agitateur à x {_m(x)} m, hors de sa course ({_m(debut)} à {_m(fin)} m)"
        if not self.chariot_ecarte(chariot):
            y = "inconnu" if chariot is None else f"à y {_m(chariot.y)} m"
            return (
                f"l'agitateur ne roule que si le chariot de remplissage est à y ≥ "
                f"{_m(self.reglages.chariot.y_ecarte_min)} m (il est {y})"
            )
        if not self.en_haut(depart):
            return "l'agitateur ne roule que manivelle en haut"
        return None

    def refus_manivelle(self, pose: PoseAgitateur, chariot: EtatChariot | None) -> str | None:
        """La manivelle ne tourne qu'au garage, au demi-tour ou au dosage ; au garage, pas avec
        la course de 10 cm ; au dosage, chariot écarté ou seau au dosage (jamais en route)."""
        reglages = self.reglages
        if self.au_garage(pose):
            if reglages.course_agitation_m > reglages.manivelle.course_max_garage_m + _EGAL:
                return (
                    f"au garage, la manivelle ne tourne pas avec une course de "
                    f"{_m(reglages.course_agitation_m * 100)} cm (le fond du bocal toucherait la "
                    f"marche du poste du fût) : {_m(reglages.manivelle.course_max_garage_m * 100)}"
                    " cm au plus"
                )
            return None
        if self.au_demi_tour(pose):
            return None
        if self.au_dosage(pose):
            if self.chariot_ecarte(chariot) or self.chariot_au_dosage(chariot):
                return None
            return (
                "au dosage, la manivelle ne tourne pas pendant que le chariot de remplissage roule"
            )
        return "la manivelle ne tourne qu'au garage, au demi-tour ou au dosage"

    def refus_chariot(self, pose: PoseAgitateur | None, en_mouvement: bool) -> str | None:
        """Le chariot de remplissage ne roule que si l'agitateur est au garage manivelle en haut,
        ou au dosage manivelle en bas (et ne bouge pas)."""
        if pose is None:
            return "position de l'agitateur du mycélium inconnue"
        if en_mouvement:
            return "l'agitateur du mycélium bouge"
        if self.au_garage(pose) and self.en_haut(pose):
            return None
        if self.au_dosage(pose) and self.en_bas(pose):
            return None
        return (
            f"agitateur du mycélium à x {_m(pose.x)} m, manivelle à {pose.angle % 360:.0f}° : le "
            "chariot de remplissage ne roule qu'agitateur au garage manivelle en haut, ou au "
            "dosage manivelle en bas"
        )

    def camera_peut_pivoter(self, pose: PoseAgitateur | None) -> bool:
        """La caméra du dosage ne pivote vers le seau que si l'agitateur est garé (règle 2 ;
        la condition de la griffe et de la préhension est vérifiée par la tâche Vision)."""
        return pose is not None and pose.x <= self.reglages.camera_x_max + _EGAL
