"""L'ordre du cycle d'un seau, en un seul endroit (tâche 45).

Le programme principal (vidange.cycle.mode_seaux, au démarrage) le lit pour savoir quels modules
construire, lesquels manquent et pourquoi (check-list, écran) ; le simulateur
(`vidange-simulateur cycle`) le lit pour vérifier que chaque seau du lot simulé passe bien par ces
postes, dans cet ordre.

La vie d'un seau du mode seaux (ordre corrigé le 07/11/2026, réponses des fils Spray, Micropore
et Guidage caméra à la PR n° 89) :

    fut          fût plein au poste, « Prêt » de Karulium
    seau_vide    seau vide pris sur sa pile, posé sur le plateau (y 0,50)
    qr_du_flanc  plateau monté (plateau_lecture_qr), le plateau tourne le seau, la caméra du
                 micropore lit le QR du flanc ; format chargé, anse à 45° des barres
    au_poste     barres serrées puis ouvertes (centrage), seau VIDE au poste (y 0,135)
    spray        spray de culture sur le seau vide, une fois par seau, pendant le 1er
                 aller-retour de la griffe (bras sorti, dose, le seau tourne ≈ 200°, bras rangé)
    micropore    rangées du haut sur le seau vide au poste, après le spray ; la rangée du fond
                 au vidage, quand le seau pèse assez (micropore → fond_poids_min_kg)
    griffe       une couche de substrat versée par la griffe, le seau tourne
    mycelium     une dose de semence sur la couche (griffe puis mycélium, à chaque couche)
    couvercle    couvercle posé sur le seau plein
    fermeture    couvercle clipsé
    stockage     seau plein rangé (tiroir, puis bande du haut)
    lavage       les seaux vides sales lavés (travail à part, après le lot)

`etapes` : les étapes du chef (« module.etape ») où le poste se fait, dans l'ordre (la rangée du
fond du micropore n'a pas d'étape à elle : elle se fait pendant le retour au vidage ; un essai,
tests/test_cycle.py, vérifie à part qu'elle attend le poids). `case_vide` : le geste n'est pas
encore écrit, le poste n'est jamais lancé (ni sur la machine ni dans le simulateur) : on ne
l'invente pas. `coeur` : sans lui, aucun lot ne peut partir,
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
        "Seau vide pris sur sa pile, posé sur le plateau (y 0,50)",
        etapes=("remplissage.prendre_le_seau", "remplissage.poser_le_seau"),
        coeur=True,
        obligatoire=True,
    ),
    Poste(
        "qr_du_flanc",
        "QR du flanc lu par la caméra du micropore (le plateau tourne le seau), anse orientée",
        etapes=("remplissage.orienter_l_anse",),
        coeur=True,
        obligatoire=True,
    ),
    Poste(
        "au_poste",
        "Seau centré (barres serrées puis ouvertes), seau vide au poste (y 0,135)",
        etapes=("remplissage.centrer", "remplissage.aller_au_poste"),
        coeur=True,
        obligatoire=True,
    ),
    Poste(
        "spray",
        "Spray de culture sur le seau vide au poste, pendant le 1er aller-retour de la griffe",
        etapes=("remplissage.spray_pulveriser", "remplissage.spray_ranger_le_bras"),
        obligatoire=True,
    ),
    Poste(
        "micropore",
        "Micropore : rangées du haut sur le seau vide ; rangée du fond quand il pèse assez",
        etapes=("remplissage.micropore_rangee_du_haut",),
        obligatoire=True,
    ),
    Poste(
        "griffe",
        "Couche de substrat versée par la griffe, le seau tourne",
        etapes=("remplissage.ramener_au_vidage", "remplissage.verser"),
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

# Postes qui servent le seau du chariot : sans le cœur du lot, ils ne sont pas lancés.
SUR_LE_CHARIOT = ("spray", "micropore", "fermeture")

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
    donnés sont vérifiés (lancés, ou joués en faux par le simulateur : la griffe) ; chacune de
    leurs étapes doit être faite, au moins une fois par seau, et leurs premières fois dans
    l'ordre (QR avant le serrage des barres, spray et rangées du haut avant la 1re couche...)."""
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
