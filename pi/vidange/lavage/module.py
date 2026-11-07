"""Les modules « lavage » du simulateur : une série de seaux, de couvercles ou de bocaux lavés.

Ce n'est pas encore le module de production : la prise et la pose des seaux sur les piles sont
au Stockage (pas figé). Ici, la tête prend chaque seau retourné à sa place (simulateur.yaml), le
lave et le repose au même endroit ; ce module sert au scénario « lavage » et aux essais.

    remplir            eau neuve jusqu'au flotteur haut
    prendre_le_seau    la tête prend le seau retourné (case vide du Stockage)
    laver_le_seau      couloir, brosses (2 passes), rinçage, remontée, jet d'air, égouttage
    poser_le_seau      la tête le repose (case vide du Stockage)
    vider              vidange par la bonde (fin de série, ou eau à changer)
    finir_la_serie     refusé tant que le fût de lavage n'est pas vidé

Couvercles (`module_lavage_couvercles`, scénario « lavage_couvercles ») : le retourneur est
vérifié par la caméra, puis pour chaque couvercle : prendre, laver le dessous, retourner, laver
le dessus, remettre à l'endroit, poser (le rangement est au Stockage) ; vidange à la fin.
Bocaux (`module_lavage_bocaux`, scénario « lavage_bocaux ») : Karulium confirme à l'écran que
le lave-bocal est posé (son Go), puis pour chaque bocal ou capsule : prendre, laver, poser ;
vidange, et Karulium confirme qu'il a enlevé le lave-bocal.

Les étapes se répètent (un seau, le suivant...) : `ensuite` dit laquelle vient après.
"""

from collections.abc import Callable, Sequence

from vidange.chef import Condition, Etape, Module
from vidange.lavage.bocaux import LavageBocaux
from vidange.lavage.couvercles import QUOI_FAIRE_RETOURNEUR, LavageCouvercles
from vidange.lavage.lavage import (
    QUOI_FAIRE,
    QUOI_FAIRE_LAVE_BOCAL,
    QUOI_FAIRE_PANNEAU,
    QUOI_FAIRE_SERIE,
    Lavage,
)
from vidange.prehension.prehension import QUOI_FAIRE as QUOI_FAIRE_PREHENSION
from vidange.reglages import ObjetLaveBocalSimule, SeauLavageSimule

GESTE = "lavage_geste_max"
EAU = "lavage_eau_max"
PREHENSION = "prehension_geste_max"
QUOI_FAIRE_EAU = (
    "Regarder le fût de lavage, la pompe, les vannes et le flotteur. Corriger, puis acquitter et "
    "donner le Go."
)


class _Serie:
    """Où en est la série : le seau en cours (rang dans la liste)."""

    def __init__(self, lavage: Lavage, seaux: Sequence[SeauLavageSimule]) -> None:
        self.lavage = lavage
        self.seaux = list(seaux)
        self.rang = 0

    @property
    def seau(self) -> SeauLavageSimule:
        return self.seaux[self.rang]

    def apres_pose(self) -> str | None:
        self.rang += 1
        if self.rang < len(self.seaux) and not self.lavage.eau_a_changer():
            return "prendre_le_seau"
        return "vider"

    def apres_vidange(self) -> str | None:
        return "remplir" if self.rang < len(self.seaux) else None


class _Liste:
    """Où en est une série de couvercles ou de bocaux : l'objet en cours (rang)."""

    def __init__(self, objets: Sequence, apres_dernier: str) -> None:
        self.objets = list(objets)
        self.rang = 0
        self.apres_dernier = apres_dernier

    @property
    def objet(self):
        return self.objets[self.rang]

    def apres_pose(self, premiere: str) -> Callable[[], str | None]:
        def ensuite() -> str | None:
            self.rang += 1
            return premiere if self.rang < len(self.objets) else self.apres_dernier

        return ensuite


def _surveillances(lavage: Lavage, *autres: Condition) -> tuple[Condition, ...]:
    return (
        lavage.prehension.tete.surveillance,
        Condition(
            "panneau du poste du fût rabattu pendant le lavage",
            lavage.panneau_tenu,
            QUOI_FAIRE_PANNEAU,
        ),
        Condition("thermoplongeur seulement flotteur haut, pompe arrêtée", lavage.eau.surveiller),
        Condition(
            "niveau du fût de lavage tenu (ni fuite ni siphon)", lavage.eau.niveau_tenu, QUOI_FAIRE
        ),
        *autres,
    )


def _fabrique_geste(lavage: Lavage, mode: Condition, air: Condition | None = None):
    prehension = lavage.prehension
    fin = Condition("geste du lavage fini", prehension.geste_fini)

    def geste(
        nom: str,
        fabrique,
        delai: str,
        quoi_faire: str = QUOI_FAIRE,
        ensuite=None,
        avec_air: bool = False,
    ) -> Etape:
        entree = (prehension.tete.pretes, mode)
        if avec_air and air is not None:
            entree = (*entree, air)
        return Etape(
            nom,
            quoi_faire,
            action=lambda: prehension.lancer(fabrique),
            fin=fin,
            delai_max=delai,
            entree=entree,
            ensuite=ensuite,
        )

    return geste


def module_lavage(
    lavage: Lavage, seaux: Sequence[SeauLavageSimule], air: Condition | None = None
) -> Module:
    """`air` : condition d'entrée du jet d'air et de la prise du seau par le venturi (sur la
    machine : `chef.condition_permission("air")`, la mise en pression du module Air)."""
    prehension = lavage.prehension
    serie = _Serie(lavage, seaux)
    mode = Condition("mode « lavage » choisi, panneau du poste du fût rabattu", lavage.mode_permis)
    geste = _fabrique_geste(lavage, mode, air)

    return Module(
        nom="lavage",
        etapes=(
            geste("remplir", lavage.geste_remplir, EAU, QUOI_FAIRE_EAU),
            geste(
                "prendre_le_seau",
                lambda: prehension.geste_prendre(
                    "seau_retourne",
                    serie.seau.x,
                    serie.seau.y,
                    serie.seau.contact_z,
                    serie.seau.format,
                ),
                PREHENSION,
                QUOI_FAIRE_PREHENSION,
                avec_air=True,
            ),
            geste(
                "laver_le_seau",
                lambda: lavage.geste_laver_seau(serie.seau.format),
                GESTE,
                avec_air=True,
            ),
            geste(
                "poser_le_seau",
                lambda: prehension.geste_poser(serie.seau.x, serie.seau.y, serie.seau.contact_z),
                PREHENSION,
                QUOI_FAIRE_PREHENSION,
                ensuite=serie.apres_pose,
            ),
            geste("vider", lavage.geste_vider, EAU, QUOI_FAIRE_EAU, ensuite=serie.apres_vidange),
            Etape("finir_la_serie", QUOI_FAIRE_SERIE, action=lavage.finir_serie),
        ),
        surveillances=_surveillances(lavage),
        pauser=lavage.pauser,
        reprendre=lavage.reprendre,
        arreter=lavage.arreter,
    )


def module_lavage_couvercles(
    couvercles: LavageCouvercles, objets: Sequence[SeauLavageSimule]
) -> Module:
    lavage = couvercles.lavage
    prehension = lavage.prehension
    liste = _Liste(objets, "vider")
    mode = Condition(
        "mode « lavage » choisi, panneau rabattu, retourneur vérifié, pas de lave-bocal",
        couvercles.mode_permis,
    )
    geste = _fabrique_geste(lavage, mode)
    entree_lavage = Condition(
        "mode « lavage » choisi, panneau du poste du fût rabattu", lavage.mode_permis
    )

    def format() -> str:
        return liste.objet.format

    return Module(
        nom="lavage",
        etapes=(
            Etape(
                "verifier_le_retourneur",
                QUOI_FAIRE_RETOURNEUR,
                action=couvercles.verifier_retourneur,
                entree=(prehension.tete.pretes, entree_lavage),
            ),
            geste("remplir", lavage.geste_remplir, EAU, QUOI_FAIRE_EAU),
            geste(
                "prendre_le_couvercle",
                lambda: prehension.geste_prendre(
                    "couvercle", liste.objet.x, liste.objet.y, liste.objet.contact_z
                ),
                PREHENSION,
                QUOI_FAIRE_PREHENSION,
            ),
            geste("laver_le_dessous", lambda: couvercles.geste_laver(format(), "dessous"), GESTE),
            geste("retourner", lambda: couvercles.geste_retourner("dessous"), PREHENSION),
            geste("laver_le_dessus", lambda: couvercles.geste_laver(format(), "dessus"), GESTE),
            geste("remettre_a_l_endroit", lambda: couvercles.geste_retourner("dessus"), PREHENSION),
            geste(
                "poser_le_couvercle",
                lambda: prehension.geste_poser(liste.objet.x, liste.objet.y, liste.objet.contact_z),
                PREHENSION,
                QUOI_FAIRE_PREHENSION,
                ensuite=liste.apres_pose("prendre_le_couvercle"),
            ),
            geste("vider", lavage.geste_vider, EAU, QUOI_FAIRE_EAU),
            Etape("finir_la_serie", QUOI_FAIRE_SERIE, action=lavage.finir_serie),
        ),
        surveillances=_surveillances(
            lavage,
            Condition(
                "barrière lumineuse du retourneur libre",
                couvercles.barriere_libre,
                QUOI_FAIRE_RETOURNEUR,
            ),
        ),
        pauser=lavage.pauser,
        reprendre=lavage.reprendre,
        arreter=lavage.arreter,
    )


def module_lavage_bocaux(bocaux: LavageBocaux, objets: Sequence[ObjetLaveBocalSimule]) -> Module:
    lavage = bocaux.lavage
    prehension = lavage.prehension
    liste = _Liste(objets, "vider")
    entree_lavage = Condition(
        "mode « lavage » choisi, panneau du poste du fût rabattu", lavage.mode_permis
    )
    mode = Condition(
        "mode « lavage » choisi, panneau rabattu, lave-bocal confirmé posé", bocaux.mode_permis
    )
    geste = _fabrique_geste(lavage, mode)
    geste_lavage = _fabrique_geste(lavage, entree_lavage)
    return Module(
        nom="lavage",
        etapes=(
            Etape(
                "confirmer_le_lave_bocal",
                "Poser le lave-bocal sur l'anneau de rive du fût de lavage, ouvrir son robinet, "
                "puis donner le Go.",
                action=lambda: lavage.confirmer_lave_bocal(True),
                entree=(prehension.tete.pretes, entree_lavage),
                demande_go=True,
            ),
            geste(
                "prendre_le_bocal",
                lambda: prehension.geste_prendre(
                    liste.objet.sorte, liste.objet.x, liste.objet.y, liste.objet.contact_z
                ),
                PREHENSION,
                QUOI_FAIRE_PREHENSION,
            ),
            geste("laver_le_bocal", bocaux.geste_laver, GESTE),
            geste(
                "poser_le_bocal",
                lambda: prehension.geste_poser(liste.objet.x, liste.objet.y, liste.objet.contact_z),
                PREHENSION,
                QUOI_FAIRE_PREHENSION,
                ensuite=liste.apres_pose("prendre_le_bocal"),
            ),
            geste_lavage("vider", lavage.geste_vider, EAU, QUOI_FAIRE_EAU),
            Etape(
                "enlever_le_lave_bocal",
                QUOI_FAIRE_LAVE_BOCAL,
                action=lambda: lavage.confirmer_lave_bocal(False),
                demande_go=True,
            ),
            Etape("finir_la_serie", QUOI_FAIRE_SERIE, action=lavage.finir_serie),
        ),
        surveillances=_surveillances(lavage),
        pauser=lavage.pauser,
        reprendre=lavage.reprendre,
        arreter=lavage.arreter,
    )
