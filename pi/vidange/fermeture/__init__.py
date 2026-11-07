"""Fermeture des seaux, côté Pi (tâche 41) : un bras à rouleau, tourné à vide par un servo, contre
lequel le PLATEAU du chariot de remplissage presse le couvercle, puis tourne pour le clipser."""

from vidange.fermeture.bras import BrasFermeture
from vidange.fermeture.fermeture import Fermeture

__all__ = ["BrasFermeture", "Fermeture"]
