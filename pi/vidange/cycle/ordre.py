"""L'ordre du cycle d'un seau, en un seul endroit (tâche 45).

Le programme principal (vidange.cycle.mode_seaux, au démarrage) le lit pour savoir quels modules
construire, lesquels manquent et pourquoi (check-list, écran) ; le simulateur
(`vidange-simulateur cycle`) le lit pour vérifier que chaque seau du lot simulé passe bien par ces
postes, dans cet ordre.

La vie d'un seau du mode seaux :

    fut          fût plein au poste, « Prêt » de Karulium
    seau_vide    seau vide pris sur sa pile, posé sur le chariot, centré, amené au vidage
    griffe       une couche de substrat versée par la griffe, le seau tourne
    mycelium     une dose de semence sur la couche (griffe puis mycélium, à chaque couche)
    spray        spray de culture au poste
    micropore    micropore posé sur les trous du seau
    couvercle    couvercle posé sur le seau plein
    fermeture    couvercle clipsé
    stockage     seau plein rangé (tiroir, puis bande du haut)
    lavage       les seaux vides sales lavés (travail à part, après le lot)

`etapes` : les étapes du chef (« module.etape ») où le poste se fait, dans l'ordre. Un poste sans
étape à lui (micropore : ses gestes se font pendant les trajets du chariot) n'est pas vérifié dans
le planning. `case_vide` : le geste n'est pas encore écrit, le poste n'est jamais lancé (ni sur la
machine ni dans le simulateur) : on ne l'invente pas. `coeur` : sans lui, aucun lot ne peut partir,
même dans le simulateur. `obligatoire` : sur la vraie machine, un lot ne part pas sans lui.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Poste:
    nom: str
    texte: str
    etapes: tuple[str, ...] = ()
    case_vide: str | None = None
    coeur: bool = False
    obligatoire: bool = False
    # Postes sans lesquels celui-ci ne sert à rien (la fermeture sans couvercle posé...).
    besoin: tuple[str, ...] = ()


ORDRE_SEAU: tuple[Poste, ...] = (
    Poste("fut", "Fût plein au poste, « Prêt » de Karulium", obligatoire=True),
    Poste(
        "seau_vide",
        "Seau vide pris sur sa pile, posé sur le chariot, centré, amené au vidage",
        etapes=(
            "remplissage.prendre_le_seau",
            "remplissage.poser_le_seau",
            "remplissage.centrer",
            "remplissage.ramener_au_vidage",
        ),
        coeur=True,
        obligatoire=True,
    ),
    Poste(
        "griffe",
        "Couche de substrat versée par la griffe, le seau tourne",
        etapes=("remplissage.verser",),
        case_vide=(
            "enchaînement de la griffe avec la préhension (même pont) et avec le seau du chariot "
            "pas écrit (solveur, tâche 23) ; dans le simulateur, chaque versement est une "
            "rotation du seau"
        ),
        obligatoire=True,
    ),
    Poste(
        "mycelium",
        "Dose de semence sur la couche",
        etapes=("mycelium.agiter",),
        coeur=True,
        obligatoire=True,
    ),
    Poste(
        "spray",
        "Spray de culture au poste",
        case_vide=(
            "moment de la dose dans le cycle d'un seau pas écrit (à quel passage au poste : "
            "question de la tâche 45)"
        ),
    ),
    Poste("micropore", "Micropore posé sur les trous du seau"),
    Poste(
        "couvercle",
        "Couvercle posé sur le seau plein",
        case_vide="pose du couvercle sur le seau plein pas écrite (tâche 41 bis)",
        obligatoire=True,
    ),
    Poste(
        "fermeture",
        "Couvercle clipsé",
        etapes=("remplissage.fermer_le_seau",),
        obligatoire=True,
        besoin=("couvercle",),
    ),
    Poste(
        "stockage",
        "Seau plein rangé : tiroir, puis bande du haut",
        etapes=("remplissage.ranger",),
        coeur=True,
        obligatoire=True,
    ),
    Poste(
        "lavage",
        "Seaux vides sales lavés (travail à part, après le lot)",
        case_vide=(
            "lancement par le programme principal pas écrit : la liste des seaux sales vient de "
            "la caméra du plafond (règle 7), panneau du poste rabattu"
        ),
    ),
)

# L'étape du chef qui commence chaque seau (pour découper le planning seau par seau).
DEBUT_DU_SEAU = "remplissage.prendre_le_seau"


def poste(nom: str) -> Poste:
    for candidat in ORDRE_SEAU:
        if candidat.nom == nom:
            return candidat
    raise KeyError(nom)


def verifier_ordre(etapes_faites: Sequence[str], postes_lances: Iterable[str]) -> list[str]:
    """Les étapes faites (« module.etape », dans l'ordre du temps) suivent-elles ORDRE_SEAU pour
    chaque seau ? Rend les problèmes, en clair (liste vide : tout va bien). Seuls les postes
    lancés sont vérifiés ; chacune de leurs étapes doit être faite, au moins une fois par seau."""
    lances = set(postes_lances)
    attendues = [etape for p in ORDRE_SEAU if p.nom in lances for etape in p.etapes]
    debuts = [i for i, etape in enumerate(etapes_faites) if etape == DEBUT_DU_SEAU]
    problemes = [] if debuts or not attendues else ["aucun seau commencé"]
    for numero, debut in enumerate(debuts, start=1):
        fin = debuts[numero] if numero < len(debuts) else len(etapes_faites)
        morceau = list(etapes_faites[debut:fin])
        premieres = []
        for etape in attendues:
            if etape not in morceau:
                problemes.append(f"seau n° {numero} : étape « {etape} » pas faite")
            else:
                premieres.append((morceau.index(etape), etape))
        dans_l_ordre = [etape for _, etape in sorted(premieres)]
        voulu = [etape for etape in attendues if etape in morceau]
        if dans_l_ordre != voulu:
            problemes.append(
                f"seau n° {numero} : ordre {' → '.join(dans_l_ordre)} au lieu de "
                f"{' → '.join(voulu)}"
            )
    return problemes
