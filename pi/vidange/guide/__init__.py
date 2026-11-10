"""Mode guidé pour un employé (84) et manuel d'utilisation tenu à jour (85), tâche 32.

- `guide` : un travail expliqué pas à pas, partagé par la page web et l'écran ;
- `manuel` : le manuel fabriqué d'après les réglages et les « quoi faire » ;
- `verification` : guide.yaml contre entrees-sorties.yaml et la page de l'écran ;
- `outil` : la commande `vidange manuel`.
"""

from vidange.guide.guide import ErreurGuide, EtatGuide, Guide
from vidange.guide.manuel import Section, en_markdown, sections
from vidange.guide.verification import verifier_avec_liste

__all__ = [
    "ErreurGuide",
    "EtatGuide",
    "Guide",
    "Section",
    "en_markdown",
    "sections",
    "verifier_avec_liste",
]
