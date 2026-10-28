"""Pesée du chariot du fût : de la carte HX711 au poids en kilogrammes.

    pesee = Pesee(reglages.machine.poste_fut.pesee, materiel)
    pesee.peser()          # poids lu (berceau + fût + contenu), en kg
    pesee.net(poids_lu)    # poids du substrat seul : poids lu − tare (berceau + fût vide)

Une pesée = la médiane de plusieurs lectures (`lectures`) ; une lecture trop loin de la
médiane (`ecart_aberrant_kg`) est jetée, et il en faut assez de bonnes (`lectures_valides_min`).
Une lecture interrompue par Linux (impulsion d'horloge trop longue) est refaite.

La prise de la pesée est souvent débranchée (≈ 800 fois par an) : sans réponse, `peser` lève
ErreurPesee avec `debranchee = True`. Ce n'est jamais une erreur qui arrête le Pi.

Étalonnage (pi/systeme/essai-poste-fut.md) : `zero_brut` = mesure brute à vide, puis
`brut_par_kg` = (mesure brute avec un poids connu − zéro) / ce poids.
"""

from statistics import median

from vidange.materiel import ErreurMateriel, LectureInterrompue, Materiel, PeseeMuette
from vidange.reglages import PeseeFut

SIGNAL = "pesee_fut"


class ErreurPesee(Exception):
    """Pas de poids : pesée débranchée, ou lectures trop dispersées."""

    def __init__(self, message: str, debranchee: bool = False) -> None:
        super().__init__(message)
        self.debranchee = debranchee


def filtrer(valeurs: list[float], ecart: float, minimum: int) -> float:
    """La médiane des valeurs proches de la médiane ; ErreurPesee s'il en reste trop peu."""
    if not valeurs:
        raise ErreurPesee("aucune lecture de la pesée")
    milieu = median(valeurs)
    bonnes = [valeur for valeur in valeurs if abs(valeur - milieu) <= ecart]
    if len(bonnes) < minimum:
        raise ErreurPesee(
            f"lectures de la pesée trop dispersées ({len(bonnes)} bonnes sur {len(valeurs)}, "
            f"il en faut {minimum}) : chariot qui bouge, ou câble abîmé ?"
        )
    return median(bonnes)


def pente(zero_brut: int, brut_avec_poids: int, poids_kg: float) -> float:
    """Le « brut_par_kg » de l'étalonnage, d'après un poids connu posé sur la pesée."""
    if poids_kg <= 0:
        raise ValueError("le poids connu doit être plus grand que 0")
    if brut_avec_poids == zero_brut:
        raise ValueError("la mesure n'a pas bougé avec le poids : pesée mal branchée ?")
    return (brut_avec_poids - zero_brut) / poids_kg


class Pesee:
    def __init__(self, reglages: PeseeFut, materiel: Materiel, signal: str = SIGNAL) -> None:
        self.reglages = reglages
        self.materiel = materiel
        self.signal = signal
        # Lectures faites et lectures interrompues par Linux, depuis le démarrage (pour juger
        # sur la vraie machine si la lecture directe par le Pi reste fiable).
        self.lectures = 0
        self.interrompues = 0

    def lire_brut(self) -> list[int]:
        """Les lectures brutes d'une pesée (les lectures interrompues sont refaites)."""
        reglages = self.reglages
        valeurs: list[int] = []
        essais = 0
        while len(valeurs) < reglages.lectures and essais < 2 * reglages.lectures:
            essais += 1
            self.lectures += 1
            try:
                valeurs.append(self.materiel.peser(self.signal, reglages.delai_reponse_s))
            except LectureInterrompue:
                self.interrompues += 1
            except PeseeMuette:
                raise ErreurPesee("pesée débranchée", debranchee=True) from None
            except ErreurMateriel as erreur:
                raise ErreurPesee(f"pesée en panne : {erreur}") from None
        if len(valeurs) < reglages.lectures_valides_min:
            raise ErreurPesee(
                f"lectures de la pesée interrompues par Linux ({essais - len(valeurs)} sur "
                f"{essais}) : Pi trop occupé ? (voir pi/systeme/essai-poste-fut.md)"
            )
        return valeurs

    def kg(self, brut: float) -> float:
        """Poids lu (kg) d'après une mesure brute."""
        return (brut - self.reglages.zero_brut) / self.reglages.brut_par_kg

    def brut(self, kg: float) -> int:
        """L'inverse : la mesure brute d'un poids (pour le simulateur)."""
        return round(self.reglages.zero_brut + kg * self.reglages.brut_par_kg)

    def peser(self) -> float:
        """Poids lu (berceau + fût + contenu), en kg."""
        reglages = self.reglages
        return filtrer(
            [self.kg(valeur) for valeur in self.lire_brut()],
            reglages.ecart_aberrant_kg,
            reglages.lectures_valides_min,
        )

    def net(self, poids_lu_kg: float) -> float:
        """Poids du substrat seul (kg) : poids lu − tare (berceau + fût vide)."""
        return poids_lu_kg - self.reglages.tare_kg

    def plausible(self, poids_lu_kg: float) -> bool:
        debut, fin = self.reglages.plausible_kg
        return debut <= poids_lu_kg <= fin
