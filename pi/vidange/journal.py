"""Journal (logs) commun à tout le programme.

Chaque morceau du programme prend son journal avec « donner_journal("nom") ».
Tout va à l'écran (que systemd range dans son propre journal) et, si un dossier
est donné, dans un fichier qui tourne (les plus vieux fichiers sont effacés).
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

RACINE = "vidange"
NOM_FICHIER = "vidange.log"
FORMAT = "%(asctime)s %(levelname)-8s %(name)s : %(message)s"

# Les niveaux s'écrivent en français dans programme.yaml.
NIVEAUX = {
    "detail": logging.DEBUG,
    "info": logging.INFO,
    "avertissement": logging.WARNING,
    "erreur": logging.ERROR,
}


def donner_journal(nom: str) -> logging.Logger:
    """Journal d'un morceau du programme (exemple : « fluidnc », « registre »)."""
    return logging.getLogger(f"{RACINE}.{nom}")


def configurer_journal(
    niveau: str = "info",
    dossier: Path | None = None,
    taille_fichier_mo: float | None = None,
    nombre_fichiers: int | None = None,
) -> None:
    """Met en place le journal. On peut l'appeler plusieurs fois : il repart de zéro."""
    racine = logging.getLogger(RACINE)
    for sortie in list(racine.handlers):
        racine.removeHandler(sortie)
        sortie.close()
    racine.setLevel(NIVEAUX[niveau])
    # Le journal « vidange » ne passe pas au journal général de Python :
    # sinon une bibliothèque qui configure ce dernier ferait écrire chaque ligne deux fois.
    racine.propagate = False
    forme = logging.Formatter(FORMAT)

    ecran = logging.StreamHandler(sys.stderr)
    ecran.setFormatter(forme)
    racine.addHandler(ecran)

    if dossier is not None:
        if taille_fichier_mo is None or nombre_fichiers is None:
            raise ValueError(
                "taille_fichier_mo et nombre_fichiers sont nécessaires avec un dossier"
            )
        dossier.mkdir(parents=True, exist_ok=True)
        fichier = RotatingFileHandler(
            dossier / NOM_FICHIER,
            maxBytes=int(taille_fichier_mo * 1024 * 1024),
            backupCount=nombre_fichiers,
            encoding="utf-8",
        )
        fichier.setFormatter(forme)
        racine.addHandler(fichier)
