"""Mises à jour (tâche 13) : cartes ESP32 par USB (esptool), programme du Pi depuis « main ».

Voir gestion.py (ce que la page web lance), cartes.py, pi.py et pi/systeme/essai-mises-a-jour.md.
"""

from vidange.mises_a_jour.cartes import CarteEsp32, Copie, Resultat
from vidange.mises_a_jour.commun import ErreurMiseAJour
from vidange.mises_a_jour.faux import FausseCarteEsp32, faux_programme
from vidange.mises_a_jour.gestion import DOSSIER, MisesAJour, preparer_cartes
from vidange.mises_a_jour.pi import ProgrammePi

__all__ = [
    "DOSSIER",
    "CarteEsp32",
    "Copie",
    "ErreurMiseAJour",
    "FausseCarteEsp32",
    "MisesAJour",
    "ProgrammePi",
    "Resultat",
    "faux_programme",
    "preparer_cartes",
]
