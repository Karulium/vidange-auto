"""Lavage des seaux : eau du fût de lavage, brosses, gestes de la tête, simulateur."""

from vidange.lavage.eau import EauLavage
from vidange.lavage.lavage import Lavage
from vidange.lavage.signaux import SignauxRepartis, signaux_lavage

__all__ = ["EauLavage", "Lavage", "SignauxRepartis", "signaux_lavage"]
