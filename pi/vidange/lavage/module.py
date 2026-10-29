"""Le module « lavage » du simulateur : une série de seaux lavés dans le fût de lavage.

Ce n'est pas encore le module de production : la prise et la pose des seaux sur les piles sont
au Stockage (pas figé). Ici, la tête prend chaque seau retourné à sa place (simulateur.yaml), le
lave et le repose au même endroit ; ce module sert au scénario « lavage » et aux essais.

    remplir            eau neuve jusqu'au flotteur haut
    prendre_le_seau    la tête prend le seau retourné (case vide du Stockage)
    laver_le_seau      couloir, brosses (2 passes), rinçage, remontée, jet d'air, égouttage
    poser_le_seau      la tête le repose (case vide du Stockage)
    vider              vidange par la bonde (fin de série, ou eau à changer)
    finir_la_serie     refusé tant que le fût de lavage n'est pas vidé

Les étapes se répètent (un seau, le suivant...) : `ensuite` dit laquelle vient après.
"""

from collections.abc import Sequence

from vidange.chef import Condition, Etape, Module
from vidange.lavage.lavage import QUOI_FAIRE, QUOI_FAIRE_PANNEAU, QUOI_FAIRE_SERIE, Lavage
from vidange.prehension.prehension import QUOI_FAIRE as QUOI_FAIRE_PREHENSION
from vidange.reglages import SeauLavageSimule

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


def module_lavage(lavage: Lavage, seaux: Sequence[SeauLavageSimule]) -> Module:
    prehension = lavage.prehension
    tete = prehension.tete
    serie = _Serie(lavage, seaux)
    fin = Condition("geste du lavage fini", prehension.geste_fini)
    mode = Condition("mode « lavage » choisi, panneau du poste du fût rabattu", lavage.mode_permis)

    def geste(nom: str, fabrique, delai: str, quoi_faire: str = QUOI_FAIRE, ensuite=None) -> Etape:
        return Etape(
            nom,
            quoi_faire,
            action=lambda: prehension.lancer(fabrique),
            fin=fin,
            delai_max=delai,
            entree=(tete.pretes, mode),
            ensuite=ensuite,
        )

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
            ),
            geste("laver_le_seau", lambda: lavage.geste_laver_seau(serie.seau.format), GESTE),
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
        surveillances=(
            tete.surveillance,
            Condition(
                "panneau du poste du fût rabattu pendant le lavage",
                lavage.panneau_tenu,
                QUOI_FAIRE_PANNEAU,
            ),
            Condition(
                "thermoplongeur seulement flotteur haut, pompe arrêtée", lavage.eau.surveiller
            ),
        ),
        pauser=lavage.pauser,
        reprendre=lavage.reprendre,
        arreter=lavage.arreter,
    )
