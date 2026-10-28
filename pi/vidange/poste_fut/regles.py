"""Verrous du poste du fût pour les modules qui passent par là (fiche validée le 23/10/2026).

Chaque fonction rend la raison du refus (en français, pour l'écran et la page web), ou None si
le geste est permis. Les chiffres viennent de machine.yaml (`poste_fut`). Ces verrous ne
protègent que la MACHINE : la sécurité des personnes reste câblée.

`echange` = le chariot du fût est absent ou en mouvement (pas « en place » de façon stable) :
c'est `PosteFut.echange_en_cours`.

Les modules qui s'en serviront ne sont pas encore écrits (Portique, Remplissage, Griffe,
Préhension, Stockage) : ils appelleront ces verrous avant chaque geste.
"""

from math import hypot

from vidange.reglages import PosteFut


def _m(valeur: float) -> str:
    return f"{valeur:g}".replace(".", ",")


def refus_pont(reglages: PosteFut, echange: bool, x: float) -> str | None:
    """Pont à la position x (cible ou position actuelle)."""
    debut, fin = reglages.pont_interdit_x
    if echange and debut <= x <= fin:
        return (
            f"pont interdit en x {_m(debut)} à {_m(fin)} m tant que le chariot du fût est absent "
            "ou en mouvement (il passe sous le chariot X du pont)"
        )
    return None


def refus_remplissage(reglages: PosteFut, echange: bool, y_bout: float) -> str | None:
    """Chariot de remplissage dont le bout irait en y_bout."""
    maximum = reglages.remplissage_y_bout_max
    if echange and y_bout > maximum:
        return (
            f"chariot de remplissage à garder à y ≤ {_m(maximum)} m (poste, files 1 et 2) "
            "tant que le chariot du fût est absent : il passe en biais devant la 3e file"
        )
    return None


def au_dessus_du_fut(reglages: PosteFut, x: float, y: float) -> bool:
    """Le point (x, y) est-il au-dessus de l'ouverture du fût ?"""
    centre_x, centre_y = reglages.centre_fut
    return hypot(x - centre_x, y - centre_y) <= reglages.ouverture_diametre / 2


def refus_griffe(
    reglages: PosteFut, x: float, y: float, bas_tete_z: float, volet_releve: bool
) -> str | None:
    """Griffe en (x, y), bas de sa tête à bas_tete_z.

    `volet_releve` : il n'y a pas de capteur du volet du dessus. Le volet est considéré relevé
    en mode lavage, contact du panneau ouvert (`PosteFut.volet_considere_releve`).
    """
    minimum = reglages.griffe_bas_min_poignee_z
    if reglages.poignee_volet.contient(x, y) and bas_tete_z < minimum:
        return (
            f"griffe trop basse au-dessus de la poignée du volet : bas de la tête à "
            f"{_m(bas_tete_z)} m, il faut au moins {_m(minimum)} m"
        )
    if volet_releve and au_dessus_du_fut(reglages, x, y):
        return "griffe interdite au-dessus du fût quand le volet est relevé (mode lavage)"
    return None


def refus_passage_paroi_lavage(reglages: PosteFut, fond_seau_z: float, axe_y: float) -> str | None:
    """Préhension en lavage : seau qui passe la paroi côté stockage."""
    fond_min, axe_max = reglages.lavage_paroi_fond_seau_min_z, reglages.lavage_paroi_axe_y_max
    raisons = []
    if fond_seau_z < fond_min:
        raisons.append(f"fond du seau à {_m(fond_seau_z)} m (au moins {_m(fond_min)} m)")
    if axe_y > axe_max:
        raisons.append(f"axe à y {_m(axe_y)} m (au plus {_m(axe_max)} m)")
    if raisons:
        return "passage de la paroi côté stockage refusé : " + ", ".join(raisons)
    return None
