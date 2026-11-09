"""Plans d'essais : faire varier, seau par seau, ce que Karulium permet (tâche 31, fonctions 6, 76).

- `variables` : la seule liste de ce qu'un plan peut faire varier (et où le code le lit) ;
- `plan` : lire et vérifier un plan, l'appliquer aux seaux d'un lot ;
- `plans` : les plans du Pi (chargés, acceptés, lancés, retirés), dans le registre ;
- `envoi` : ce que le logiciel de culture reçoit (format dans docs/django.md) ;
- `outil` : la commande `vidange plan`.
"""

from vidange.essais.plan import Application, ErreurPlan, PlanEssais, appliquer, lire_plan
from vidange.essais.plans import PlansEssais
from vidange.essais.variables import VARIABLES

__all__ = [
    "VARIABLES",
    "Application",
    "ErreurPlan",
    "PlanEssais",
    "PlansEssais",
    "appliquer",
    "lire_plan",
]
