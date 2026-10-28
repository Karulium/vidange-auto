"""Le module « poste_fut » du chef d'orchestre : l'échange d'un fût, tel que le Pi le suit.

Rien ne bouge au poste : le module ne fait qu'attendre Karulium.
1. le chariot du fût vide sort du poste (chariot plus vu depuis `stabilite_s`) ;
2. le chariot suivant est mis au fond, la pesée branchée, puis Karulium appuie sur « Prêt »
   (le poids du fût plein part dans le registre, voir PosteFut).

La vidange elle-même (gestes de la griffe) est la tâche 18 : elle commencera après l'étape 2,
avec `poste.surveillance` pour s'arrêter si le chariot n'est plus vu.
Le simulateur rejoue ce module avec le scénario « echange_fut » de simulateur.yaml.
"""

from vidange.chef import Condition, Etape, Module
from vidange.poste_fut.poste import PosteFut

QUOI_FAIRE = (
    "Regarder l'écran du poste du fût : il dit ce qui manque (chariot au fond, pesée branchée, "
    "bouton « Prêt »)."
)


def module_echange_fut(poste: PosteFut) -> Module:
    return Module(
        nom="poste_fut",
        etapes=(
            Etape(
                "sortir_le_fut_vide",
                QUOI_FAIRE,
                entree=(poste.condition_chariot_parti,),
            ),
            Etape(
                "attendre_le_pret",
                QUOI_FAIRE,
                entree=(
                    Condition(
                        "chariot du fût au fond, immobile", lambda: poste.etat().chariot_stable
                    ),
                    poste.condition_pret,
                ),
            ),
        ),
    )
