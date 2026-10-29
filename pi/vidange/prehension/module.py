"""Le module « prehension » du simulateur : tous les gestes de base de la tête, l'un après l'autre.

Ce n'est pas un module de production : les vrais utilisateurs de la préhension (Stockage,
Lavage, Remplissage, Entonnoir) lanceront ces gestes depuis leurs propres étapes. Ce module
sert au scénario « prehension » du simulateur et aux essais.

    prendre_le_seau        prendre un seau vide (contact, vide, levée, pesée)
    poser_le_seau          le poser ailleurs
    prendre_le_couvercle   prendre un couvercle
    poser_le_couvercle     le poser ailleurs
    prendre_le_bocal       prendre un bocal plein
    poser_au_porte_bocal   mors ouverts, bocal à sa hauteur, mors approchés, lâcher, serrer
    reprendre_au_porte_bocal   descente entre les mors, prise, mors ouverts, remontée
    reposer_le_bocal       le reposer où il était
    prendre_la_capsule     prendre une capsule (électroaimants)
    visser_la_capsule      appui 80 N, rotation et Z ensemble, capsule laissée
"""

from vidange.chef import Condition, Etape, Module
from vidange.prehension.prehension import QUOI_FAIRE, Prehension
from vidange.reglages import PlaceSimulee, PrehensionSimulee

DELAI = "prehension_geste_max"


def module_prehension(prehension: Prehension, places: PrehensionSimulee) -> Module:
    fin = Condition("geste de la préhension fini", prehension.geste_fini)
    tete = prehension.tete

    def geste(nom: str, fabrique) -> Etape:
        return Etape(
            nom,
            QUOI_FAIRE,
            action=lambda: prehension.lancer(fabrique),
            fin=fin,
            delai_max=DELAI,
            entree=(tete.pretes,),
        )

    def prendre(nom: str, objet: str, place: PlaceSimulee, format: str | None = None) -> Etape:
        return geste(
            nom,
            lambda: prehension.geste_prendre(objet, place.x, place.y, place.contact_z, format),
        )

    def poser(nom: str, place: PlaceSimulee) -> Etape:
        return geste(nom, lambda: prehension.geste_poser(place.x, place.y, place.contact_z))

    vissage = places.vissage
    return Module(
        nom="prehension",
        etapes=(
            prendre("prendre_le_seau", "seau", places.seau, "seau_a"),
            poser("poser_le_seau", places.seau_pose),
            prendre("prendre_le_couvercle", "couvercle", places.couvercle),
            poser("poser_le_couvercle", places.couvercle_pose),
            prendre("prendre_le_bocal", "bocal", places.bocal),
            geste("poser_au_porte_bocal", prehension.geste_poser_bocal),
            geste("reprendre_au_porte_bocal", prehension.geste_reprendre_bocal),
            poser("reposer_le_bocal", places.bocal),
            prendre("prendre_la_capsule", "capsule", places.capsule),
            geste(
                "visser_la_capsule",
                lambda: prehension.geste_visser(vissage.x, vissage.y, vissage.contact_z),
            ),
        ),
        surveillances=(tete.surveillance,),
        pauser=prehension.pauser,
        reprendre=prehension.reprendre,
        arreter=prehension.arreter,
    )
