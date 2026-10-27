"""File d'envoi vers l'extérieur : logiciel de culture et copie de secours de la maison.

La machine ne dépend jamais du réseau : ce qui doit partir attend dans le registre
(table « envois ») et le facteur l'envoie dès que le destinataire répond.
"""

from vidange.envois.cycle import FORMAT, donnees_cycle
from vidange.envois.expediteurs import EchecEnvoi, ExpediteurCulture, ExpediteurSecours
from vidange.envois.facteur import Facteur, mettre_en_file_secours, preparer_facteur

__all__ = [
    "FORMAT",
    "EchecEnvoi",
    "ExpediteurCulture",
    "ExpediteurSecours",
    "Facteur",
    "donnees_cycle",
    "mettre_en_file_secours",
    "preparer_facteur",
]
