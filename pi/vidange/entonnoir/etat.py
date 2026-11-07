"""L'état gardé de l'entonnoir (fichier dans donnees/), pour qu'il survive à une coupure.

Le fichier dit où est l'entonnoir (`place` : un bocal, « hors_machine » ou « inconnu ») et si la
tête le tient (`tenu`). Il est réécrit à chaque changement, d'un seul coup (fichier provisoire
puis remplacement) : une coupure ne laisse jamais un fichier à moitié écrit.
"""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from vidange.journal import donner_journal

journal = donner_journal("entonnoir")

NOM_FICHIER = "entonnoir.json"
# Les deux places qui ne sont pas un bocal.
HORS_MACHINE = "hors_machine"
INCONNU = "inconnu"


@dataclass
class EtatGarde:
    place: str = HORS_MACHINE
    tenu: bool = False


def lire(fichier: Path | None) -> tuple[EtatGarde, bool]:
    """L'état gardé, et vrai s'il y avait un fichier lisible. Pas de fichier (première mise en
    route) : hors machine. Fichier illisible : inconnu (par prudence)."""
    if fichier is None or not fichier.exists():
        return EtatGarde(), False
    try:
        donnees = json.loads(fichier.read_text(encoding="utf-8"))
        place, tenu = donnees["place"], donnees["tenu"]
        if not isinstance(place, str) or not isinstance(tenu, bool):
            raise TypeError("place ou tenu mal écrit")
        return EtatGarde(place, tenu), True
    except (OSError, ValueError, KeyError, TypeError) as erreur:
        journal.error("Entonnoir : fichier d'état illisible (%s) : place inconnue", erreur)
        return EtatGarde(INCONNU, False), False


def ecrire(fichier: Path | None, etat: EtatGarde) -> None:
    if fichier is None:
        return
    try:
        fichier.parent.mkdir(parents=True, exist_ok=True)
        provisoire = fichier.with_suffix(".tmp")
        provisoire.write_text(json.dumps(asdict(etat)), encoding="utf-8")
        os.replace(provisoire, fichier)
    except OSError as erreur:
        journal.error("Entonnoir : état pas gardé dans %s : %s", fichier, erreur)
