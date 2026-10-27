"""Place prête pour le solveur d'ordonnancement (OR-Tools, tâche 23). Rien n'est calculé ici.

Le solveur cherchera l'ordre des étapes le plus court qui respecte toutes les règles. Il partira
des « tâches » tirées d'un planning simulé :
- chaque étape faite = une tâche, avec la durée de son geste (celle du simulateur, plus tard
  recalée sur les vrais temps mesurés) ;
- une étape ne commence qu'après la précédente du même module (`apres`) ;
- deux tâches qui tiennent la même zone ne se font jamais en même temps (`zones`) ;
- une étape qui demande le Go attend Karulium (`demande_go`) : le solveur ne décide pas à sa place.

Avec OR-Tools (CP-SAT, gratuit), cela donnera : une variable « intervalle » par tâche, une
contrainte « pas de chevauchement » par zone, une contrainte « après » par module, et le temps
total à rendre le plus court. Le simulateur rejouera ensuite le programme trouvé pour le vérifier
avant que le Pi l'envoie.
"""

from dataclasses import dataclass

from vidange.simulateur.planning import Planning


@dataclass(frozen=True)
class Tache:
    module: str
    etape: str
    # Durée du geste (s) : de l'action à la condition de fin.
    duree_s: float
    # Zones tenues pendant le geste.
    zones: tuple[str, ...]
    # Tâche qui doit être finie avant (« module.etape »), ou None pour la première du module.
    apres: str | None
    demande_go: bool

    @property
    def nom(self) -> str:
        return f"{self.module}.{self.etape}"


def taches(planning: Planning) -> list[Tache]:
    """Les étapes finies du planning, en tâches pour le solveur."""
    resultat = []
    precedente: dict[str, str] = {}
    for ligne in planning.lignes:
        if ligne.fin is None:
            continue
        tache = Tache(
            module=ligne.module,
            etape=ligne.etape,
            duree_s=ligne.geste,
            zones=ligne.zones,
            apres=precedente.get(ligne.module),
            demande_go=ligne.go is not None,
        )
        precedente[ligne.module] = tache.nom
        resultat.append(tache)
    return resultat


def ordonner(taches: list[Tache]) -> dict[str, float]:
    """Heure de début de chaque tâche (nom → s), la plus courte possible. Tâche 23."""
    raise NotImplementedError("solveur d'ordonnancement pas encore écrit (tâche 23, OR-Tools)")
