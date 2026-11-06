"""Pesée du plateau du fût : de la boîte du poste (bus des pesées) au poids en kilogrammes.

    pesee = PeseePlateau(reglages.machine.poste_fut.pesee, tour)   # tour : TourPesees
    lecture = pesee.lire()     # LecturePesee : poids lu (kg) ou None, problème, plateau
    pesee.net(lecture.poids_lu_kg)   # poids du substrat seul : poids lu − tare

Le plateau (4 capteurs, un seul HX711, ESP32-C3) envoie par radio 2 mesures par seconde, chacune
la moyenne de 5 ; la boîte du poste les rend au Pi sur le bus des pesées (tâche 17 bis). Le tour
des pesées (vidange.pesees) l'interroge au plus une fois par seconde : ici, on lit seulement
la dernière réponse, sans refaire de moyenne. Seule une valeur hors des bornes plausibles est
rejetée.

Pas de réponse, radio du plateau muette, ou mesure trop vieille : pas de poids (« pesée
absente »). Ce n'est jamais une erreur qui arrête quoi que ce soit.

Étalonnage (pi/systeme/essai-poste-fut.md) : `zero_brut` et `brut_par_kg` dans pesees.yaml
(etalonnage → pesee_fut) ; la tare (fût vide) dans machine.yaml (poste_fut → pesee).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vidange.materiel import ErreurMateriel
from vidange.materiel.carte_pesee import Plateau
from vidange.reglages import PeseeFut

if TYPE_CHECKING:
    # Seulement pour les types : vidange.pesees importe la griffe, qui importe le poste du fût.
    from vidange.pesees.tour import TourPesees

SIGNAL = "pesee_fut"


@dataclass(frozen=True)
class LecturePesee:
    # Poids lu (plateau + fût + contenu), ou None : pas de poids.
    poids_lu_kg: float | None
    # "" si le poids est bon, sinon pourquoi il n'y en a pas (pour l'écran et la page web).
    probleme: str
    # Ce que la dernière trame du plateau dit de lui (accu, recharge, radio), si la radio
    # parle ; sinon None.
    plateau: Plateau | None


def pente(zero_brut: int, brut_avec_poids: int, poids_kg: float) -> float:
    """Le « brut_par_kg » de l'étalonnage, d'après un poids connu posé sur la pesée."""
    if poids_kg <= 0:
        raise ValueError("le poids connu doit être plus grand que 0")
    if brut_avec_poids == zero_brut:
        raise ValueError("la mesure n'a pas bougé avec le poids : pesée mal branchée ?")
    return (brut_avec_poids - zero_brut) / poids_kg


def _kg(valeur: float) -> str:
    return f"{valeur:.1f}".replace(".", ",")


class PeseePlateau:
    def __init__(self, reglages: PeseeFut, tour: "TourPesees", signal: str = SIGNAL) -> None:
        self.reglages = reglages
        self.tour = tour
        self.signal = signal
        self.capteur = tour.capteur(signal)

    def lire(self) -> LecturePesee:
        """La dernière mesure de la boîte du poste, en kg, ou pourquoi il n'y en a pas."""
        try:
            poids = self.capteur.lire_kg()
        except ErreurMateriel:
            return LecturePesee(None, "pesée absente : " + self._raison(), None)
        derniere = self.tour.etats[self.signal].derniere
        plateau = None if derniere is None else derniere[1].plateau
        if not self.plausible(poids):
            debut, fin = self.reglages.plausible_kg
            return LecturePesee(
                None,
                f"poids rejeté : {_kg(poids)} kg lus, attendu entre {debut:g} et {fin:g} kg",
                plateau,
            )
        return LecturePesee(poids, "", plateau)

    def _raison(self) -> str:
        """Pourquoi pas de poids, en peu de mots (le détail est au journal)."""
        etat = self.tour.etats[self.signal]
        if etat.derniere is None:
            return "la boîte du poste ne répond pas"
        mesure = etat.derniere[1]
        if etat.erreur:
            return "la boîte du poste ne répond plus"
        if mesure.radio_muette:
            return "radio du plateau muette"
        if mesure.hx711_muet:
            return "HX711 du plateau muet"
        return "mesure trop vieille"

    def net(self, poids_lu_kg: float) -> float:
        """Poids du substrat seul (kg) : poids lu − tare (fût vide et son couvercle)."""
        return poids_lu_kg - self.reglages.tare_kg

    def plausible(self, poids_lu_kg: float) -> bool:
        debut, fin = self.reglages.plausible_kg
        return debut <= poids_lu_kg <= fin

    def brut(self, kg: float) -> int:
        """L'inverse : la mesure brute d'un poids lu (pour le simulateur et les tests)."""
        etalonnage = self.capteur.etalonnage
        return round(etalonnage.zero_brut + kg * etalonnage.brut_par_kg)
