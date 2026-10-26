"""Entrées et sorties du Pi (relais, entrées 24 V, I2C, RS485), par leur nom, et faux capteurs."""

from vidange.materiel.faux import FausseFabrique
from vidange.materiel.materiel import Ambiance, Materiel, VraieFabrique
from vidange.materiel.puces import ErreurMateriel

__all__ = ["Ambiance", "ErreurMateriel", "FausseFabrique", "Materiel", "VraieFabrique"]
