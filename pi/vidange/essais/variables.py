"""Les variables qu'un plan d'essais peut faire varier d'un seau à l'autre (tâche 31).

C'est la SEULE liste : une variable n'existe que si le code sait l'appliquer à un seau. Le fichier
pi/reglages/essais.yaml en choisit et fixe leurs bornes ; un nom qui n'est pas ici, un genre ou un
« lue_par » différent empêchent le programme de démarrer (vidange.reglages).

Aucune ne touche au mouvement : pas de position, de course, de zone, de vitesse, de durée de geste
ni de seuil. Ce sont des QUANTITÉS de produit (mycélium, spray), que la machine dose déjà seau par
seau en les pesant. Ajouter une variable = écrire dans le code l'endroit qui la lit (une PR), pas
une ligne de réglage.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from vidange.reglages import Machine

Genre = Literal["nombre", "oui_non"]


@dataclass(frozen=True)
class Variable:
    nom: str
    genre: Genre
    # L'endroit du code qui lit la valeur du plan (recopié dans essais.yaml → lue_par).
    lue_par: str
    # La partie de machine.yaml sans laquelle elle n'a pas de sens.
    partie: str
    # La valeur normale pour un format (None : pas réglée), pour la page et le tableau du plan.
    normal: Callable[["Machine", str], float | bool | None]


def _mycelium_g(machine: "Machine", format: str) -> float | None:
    griffe = machine.griffe
    seau = None if griffe is None else griffe.formats.get(format)
    if seau is None or seau.mycelium_kg is None:
        return None
    return round(seau.mycelium_kg * 1000, 1)


def _spray(machine: "Machine", format: str) -> bool | None:
    return None if machine.spray is None else True


def _spray_g(machine: "Machine", format: str) -> float | None:
    spray = machine.spray
    return None if spray is None else spray.dose.par_format_g.get(format)


MYCELIUM_G = "mycelium_g"
SPRAY = "spray"
SPRAY_G = "spray_g"

VARIABLES: dict[str, Variable] = {
    MYCELIUM_G: Variable(
        MYCELIUM_G,
        "nombre",
        "vidange/mycelium/mycelium.py, Mycelium.geste_agiter",
        "mycelium",
        _mycelium_g,
    ),
    SPRAY: Variable(SPRAY, "oui_non", "vidange/spray/spray.py, Spray.preparer", "spray", _spray),
    SPRAY_G: Variable(
        SPRAY_G, "nombre", "vidange/spray/spray.py, Spray.preparer", "spray", _spray_g
    ),
}
