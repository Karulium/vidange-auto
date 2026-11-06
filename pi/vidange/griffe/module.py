"""Le module « griffe » du chef d'orchestre : la vidange d'un fût, tel que le fait la griffe.

Les étapes se répètent (prise, seau, prise...) : chacune dit, à sa fin, laquelle vient ensuite
(`Griffe.apres_...`). Tout se passe sous la surveillance du poste du fût : si le chariot n'est
plus vu, alarme, le mouvement s'arrête et le pont sort de la zone du plateau.

    attendre_le_fut      poste du fût prêt, panneau en position production
    revenir_au_fut       au-dessus du fût, à la hauteur des trajets
    racler               raclage de la paroi, ou chasse-neige (passe de fond)
    prendre_une_dose     descente au contact, mâchouiller, prise, pesée ; puis attente, godet
                         fermé dans le fût, que le seau soit prêt (mycélium versé...)
    porter_au_seau       sortie du fût (la dose est dite au poste), trajet vers le seau
    vider_dans_le_seau   couche en couronne
    tasser               fond du godet sur la couche, seau qui tourne
    essuyer_le_bord      dernière couche : raclette sur le bord du seau qui tourne
    fut_vide             sortie de la zone du plateau, « finir_vidange » au poste du fût

Le Go de Karulium n'est pas demandé : le « Prêt » du poste du fût suffit à lancer la vidange.
Après une alarme ou une coupure, le chef demande toujours le Go avant de refaire l'étape.
"""

from collections.abc import Callable

from vidange.chef import Condition, Etape, Module
from vidange.griffe.griffe import QUOI_FAIRE, Griffe

DELAI = "griffe_geste_max"


def module_griffe(
    griffe: Griffe,
    seau_pret: Callable[[], bool] = lambda: True,
    pont_libre: Callable[[], bool] = lambda: True,
) -> Module:
    """`seau_pret` : un seau est au poste de remplissage, et la couche de mycélium d'avant est
    versée (Remplissage et Mycélium, pas encore écrits). `pont_libre` : la préhension n'a pas
    besoin du pont (les deux mâts sont sur le même chariot)."""
    poste = griffe.poste
    poste.griffe_hors_fut = griffe.hors_du_fut
    fin = Condition("geste de la griffe fini", griffe.geste_fini)
    pont = Condition("pont libre (la préhension n'en a pas besoin)", pont_libre)
    seau = Condition("seau prêt au poste de remplissage (mycélium versé)", seau_pret)

    def geste(nom: str, fabrique, ensuite, entree: tuple[Condition, ...] = ()) -> Etape:
        return Etape(
            nom,
            QUOI_FAIRE,
            action=lambda: griffe.lancer(fabrique),
            fin=fin,
            delai_max=DELAI,
            entree=(griffe.bras.pretes, *entree),
            ensuite=ensuite,
        )

    return Module(
        nom="griffe",
        etapes=(
            Etape(
                "attendre_le_fut",
                "Regarder l'écran du poste du fût : il dit ce qui manque.",
                entree=(poste.condition_pret, poste.condition_mode("production")),
                ensuite=griffe.nouveau_fut,
            ),
            geste("revenir_au_fut", griffe.geste_revenir, griffe.apres_retour, (pont,)),
            geste("racler", griffe.geste_racler, griffe.apres_retour, (pont,)),
            geste("prendre_une_dose", griffe.geste_prendre, griffe.apres_prise, (pont,)),
            geste(
                "porter_au_seau", griffe.geste_porter, lambda: "vider_dans_le_seau", (seau, pont)
            ),
            geste("vider_dans_le_seau", griffe.geste_vider, griffe.apres_vidage),
            geste("tasser", griffe.geste_tasser, griffe.apres_tassement),
            geste("essuyer_le_bord", griffe.geste_essuyer, griffe.apres_essuyage),
            geste("fut_vide", griffe.geste_fut_vide, lambda: None),
        ),
        surveillances=(griffe.bras.surveillance, poste.surveillance),
        pauser=griffe.pauser,
        reprendre=griffe.reprendre,
        arreter=griffe.arreter,
    )
