"""Constats : ce qu'une vérification a trouvé, en clair, avec ce qu'il faut faire.

Chaque vérification (santé du Pi, cartes, onduleur, check-list...) rend des constats :
- ok : rien à dire ;
- inconnu : impossible à savoir ici (exemple : température du Pi lue sur un PC) ;
- attention : la machine peut tourner, mais il faut s'en occuper ;
- bloquant : la check-list refuse de lancer la production tant que ce n'est pas réglé.
"""

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from vidange.journal import donner_journal

Niveau = Literal["ok", "inconnu", "attention", "bloquant"]
GRAVITE: dict[str, int] = {"ok": 0, "inconnu": 1, "attention": 2, "bloquant": 3}


@dataclass(frozen=True)
class Constat:
    # De quoi on parle : « carte portique », « disque du Pi »...
    sujet: str
    niveau: Niveau
    # Ce qu'on a vu, en clair.
    texte: str
    # Ce que Karulium doit faire (vide si tout va bien).
    quoi_faire: str = ""


def pire(constats: Iterable[Constat]) -> Niveau:
    """Le niveau le plus grave d'une liste de constats (« ok » si elle est vide)."""
    niveau: Niveau = "ok"
    for constat in constats:
        if GRAVITE[constat.niveau] > GRAVITE[niveau]:
            niveau = constat.niveau
    return niveau


def rediger(constat: Constat) -> str:
    texte = f"[{constat.niveau}] {constat.sujet} : {constat.texte}"
    if constat.quoi_faire:
        texte += f" → {constat.quoi_faire}"
    return texte


def lancer_boucle(
    nom: str, periode_s: float, tour: Callable[[], object], arret: threading.Event
) -> threading.Thread:
    """Un fil qui appelle `tour` tous les `periode_s`, jusqu'à `arret`.

    Une erreur dans un tour est notée au journal, et le tour suivant a lieu quand même :
    une vérification qui plante ne doit jamais arrêter la surveillance.
    """
    journal = donner_journal(f"fiabilite.{nom}")

    def boucle() -> None:
        while True:
            try:
                tour()
            except Exception:
                journal.exception("Erreur pendant la vérification « %s »", nom)
            if arret.wait(periode_s):
                return

    fil = threading.Thread(target=boucle, name=nom, daemon=True)
    fil.start()
    return fil
