"""Programme du solveur, joué par le chef (tâche 23).

Un programme dit, pour chaque zone partagée, dans quel ordre les modules doivent la prendre, et à
quelle heure (s depuis le début du programme). Le chef s'en sert pour une seule chose : quand
plusieurs modules attendent une zone, celui dont c'est le tour d'après le programme passe le
premier. Sans programme, c'est l'ordre normal (l'ordre de lancement des modules).

Le programme ne peut rien autoriser de plus : les conditions, les zones et les refus du chef sont
vérifiés comme avant, pour chaque module. Un module qui n'est pas prêt laisse passer les autres.

Décision « La fiabilité d'abord » (28/10/2026) : le chef revient à son ordre normal, et le note au
journal, au premier écart :
- une alarme (n'importe quel module) ;
- un module prend une zone alors que ce n'est pas son tour ;
- un passage plus tôt ou plus tard que prévu de plus de `solveur → ecart_max_s`.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Passage:
    """Un module prend une zone (et la garde un moment)."""

    module: str
    # Heure prévue (s depuis le début du programme).
    heure_s: float


@dataclass(frozen=True)
class Programme:
    # Zone → passages, dans l'ordre prévu.
    passages: Mapping[str, tuple[Passage, ...]]
    # Temps total prévu par le solveur (s), pour comparer.
    temps_total_s: float

    @property
    def nombre_passages(self) -> int:
        return sum(len(passages) for passages in self.passages.values())


class JeuProgramme:
    """Un programme en train d'être joué : les passages qui restent, et les écarts."""

    def __init__(self, programme: Programme, debut: float, ecart_max_s: float) -> None:
        self.programme = programme
        self._debut = debut
        self._ecart_max = ecart_max_s
        self._restants: dict[str, list[Passage]] = {
            zone: list(passages) for zone, passages in programme.passages.items() if passages
        }

    @property
    def fini(self) -> bool:
        return not self._restants

    def rang(self, module: str, zones: Iterable[str]) -> float:
        """Le tour du module pour ces zones (0 : c'est son tour ; plus grand : plus tard)."""
        rangs = []
        for zone in zones:
            restants = self._restants.get(zone, [])
            rangs.append(
                next(
                    (n for n, passage in enumerate(restants) if passage.module == module),
                    float("inf"),
                )
            )
        return max(rangs, default=float("inf"))

    def passage(self, module: str, zones: Iterable[str], maintenant: float) -> str | None:
        """Le module vient de prendre ces zones. Rend l'écart (texte), ou None si c'est prévu."""
        heure = maintenant - self._debut
        for zone in zones:
            restants = self._restants.get(zone)
            if not restants:
                continue
            attendu = restants[0]
            if attendu.module != module:
                return (
                    f"« {module} » a pris la zone « {zone} » alors que le programme attendait "
                    f"« {attendu.module} »"
                )
            ecart = heure - attendu.heure_s
            if abs(ecart) > self._ecart_max:
                return (
                    f"« {module} » a pris la zone « {zone} » à {heure:.1f} s au lieu de "
                    f"{attendu.heure_s:.1f} s (écart de {ecart:+.1f} s, au plus "
                    f"{self._ecart_max:g} s)"
                )
            restants.pop(0)
            if not restants:
                del self._restants[zone]
        return None

    def retard(self, maintenant: float) -> str | None:
        """Un passage attendu depuis plus de `ecart_max_s` : l'écart (texte), sinon None."""
        heure = maintenant - self._debut
        for zone, restants in self._restants.items():
            attendu = restants[0]
            if heure - attendu.heure_s > self._ecart_max:
                return (
                    f"« {attendu.module} » devait prendre la zone « {zone} » à "
                    f"{attendu.heure_s:.1f} s ; à {heure:.1f} s, ce n'est pas fait (au plus "
                    f"{self._ecart_max:g} s de retard)"
                )
        return None
