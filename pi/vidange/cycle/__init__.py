"""Le programme principal (tâches 45 à 45 quater) : ce qui est prêt (ou pourquoi pas), les lots
donnés au chef, la reprise après une coupure, le lancement d'un lot (page web, puis Go à
l'écran).

- mode seaux (`ModeSeaux`) : l'ordre du cycle d'un seau ;
- mode bocaux (`ModeBocaux`) : lot de bocaux avec l'entonnoir, lavage des bocaux ;
- nuit UV-ozone (`ModeNuit`) : la nuit du Nettoyage peut-elle partir ;
- lancement (`Lancement`) : le lot proposé par la page web, lancé au Go de l'écran.
"""

from vidange.cycle.lancement import Lancement, LotPropose
from vidange.cycle.mode_bocaux import LotBocaux, ModeBocaux
from vidange.cycle.mode_nuit import ModeNuit
from vidange.cycle.mode_seaux import Lot, ModeSeaux, Pieces, PiecesRemplissage
from vidange.cycle.ordre import ORDRE_BOCAUX, ORDRE_NUIT, ORDRE_SEAU, Poste, verifier_ordre
from vidange.cycle.postes import EtatPoste

__all__ = [
    "ORDRE_BOCAUX",
    "ORDRE_NUIT",
    "ORDRE_SEAU",
    "EtatPoste",
    "Lancement",
    "Lot",
    "LotBocaux",
    "LotPropose",
    "ModeBocaux",
    "ModeNuit",
    "ModeSeaux",
    "Pieces",
    "PiecesRemplissage",
    "Poste",
    "verifier_ordre",
]
