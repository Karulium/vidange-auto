"""Écran Nextion de la porte de l'armoire, côté Pi (tâche 9). Voir ecran.py."""

from vidange.ecran.ecran import Ecran
from vidange.ecran.faux import FauxNextion
from vidange.ecran.liaison import SIGNAL, LiaisonEcran, PortEcran, ouvrir_port_ecran
from vidange.ecran.pages import PAGES

__all__ = [
    "PAGES",
    "SIGNAL",
    "Ecran",
    "FauxNextion",
    "LiaisonEcran",
    "PortEcran",
    "ouvrir_port_ecran",
]
