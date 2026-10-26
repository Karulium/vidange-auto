"""Module d'EXEMPLE : montre comment écrire un module. Il ne correspond à aucun vrai module.

Il utilise les axes, positions, zones et délais d'exemple de machine.yaml :
1. aller au repos, si le panneau du poste du fût est fermé ;
2. après le Go de Karulium, entrer dans la zone A (réservée) ;
3. revenir au repos et libérer la zone A.
"""

from vidange.chef.axes import Axes
from vidange.chef.etapes import Condition, Etape, Module
from vidange.materiel import Materiel

QUOI_FAIRE = (
    "Regarder si un axe est bloqué ou si sa carte est en alarme ; corriger, "
    "puis acquitter et donner le Go."
)


def module_exemple(axes: Axes, materiel: Materiel) -> Module:
    panneau_ferme = Condition(
        "panneau du poste du fût fermé", lambda: materiel.lire("reed_panneau_poste_fut")
    )
    return Module(
        nom="exemple",
        etapes=(
            Etape(
                "aller_au_repos",
                QUOI_FAIRE,
                action=lambda: axes.aller("exemple_repos"),
                fin=axes.arrives,
                delai_max="exemple_deplacement_max",
                entree=(axes.pretes, panneau_ferme),
            ),
            Etape(
                "entrer_dans_la_zone_a",
                QUOI_FAIRE,
                action=lambda: axes.aller("exemple_dans_zone_a"),
                fin=axes.arrives,
                delai_max="exemple_deplacement_max",
                entree=(axes.pretes,),
                reserver=("exemple_zone_a",),
                demande_go=True,
            ),
            Etape(
                "revenir_au_repos",
                QUOI_FAIRE,
                action=lambda: axes.aller("exemple_repos"),
                fin=axes.arrives,
                delai_max="exemple_deplacement_max",
                liberer=("exemple_zone_a",),
            ),
        ),
        surveillances=(axes.surveillance,),
        pauser=axes.pauser,
        reprendre=axes.reprendre,
        # Arrêt sur alarme : les axes se figent sur place (sans perdre leur position).
        arreter=axes.pauser,
    )
