"""Ce que entretien.yaml cite de entrees-sorties.yaml doit y exister (tâche 26)."""

from vidange.entrees_sorties import SORTIES, EntreesSorties
from vidange.reglages import Fluidnc, ReglagesEntretien


def verifier_avec_liste(
    reglages: ReglagesEntretien, liste: EntreesSorties, fluidnc: Fluidnc
) -> list[str]:
    """Une pièce comptée par manœuvres doit citer une sortie tout-ou-rien qui existe (de la liste
    des entrées/sorties, ou d'une carte FluidNC). Rend les erreurs, en français."""
    connues = {nom for nom, signal in liste.signaux.items() if signal.type in SORTIES}
    connues |= {nom for carte in fluidnc.cartes.values() for nom in carte.sorties}
    return [
        f"entretien.yaml, pieces → {nom} → compteur → de : la sortie « {piece.compteur.de} » "
        f"n'est pas dans docs/entrees-sorties.yaml (sorties : relais ou logique) ni dans "
        "les sorties d'une carte de fluidnc.yaml"
        for nom, piece in reglages.pieces.items()
        if piece.compteur.genre == "manoeuvres" and piece.compteur.de not in connues
    ]
