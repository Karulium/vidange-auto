"""Le module « remplissage » : un seau vide posé, rempli couche après couche, rangé.

Il tourne avec le module « mycelium », qui mène le chariot pendant le dosage (Mycelium.demander,
puis `ecarter` et `amener_au_dosage` du Remplissage). Les versements de la griffe sont ceux d'un
`Plan` (le seau tourne pendant `versement_s`) : le vrai enchaînement avec la griffe viendra avec
le solveur (tâche 23). C'est le scénario « remplissage » du simulateur, et un essai.

    aller_a_la_pose        chariot à y 0,50, barres ouvertes, plateau à la hauteur de pose
    prendre_le_seau        la préhension prend un seau vide au stockage
    poser_le_seau          posé sur le plateau ; barrière coupée : prise double séparée
    rendre_le_seau_du_dessus   après une prise double : le seau du dessus rendu au stockage
    orienter_l_anse        QR du flanc lu, oreilles de l'anse à 45° des barres
    centrer                barres au contact du corps (courant réduit), puis ouvertes
    ramener_au_poste       plateau en bas, y 0,135, plateau remonté (agitateur au garage)
    verser                 versement de la griffe : le seau tourne
    doser                  le Mycélium dose la couche (il mène le chariot)
    revenir_au_poste       couche suivante : retour au poste (agitateur au garage)
    ranger                 anse à son angle, chariot à sa file, le pousseur pousse le seau
    fin                    plus de seau
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from vidange.chef import Condition, Etape, Module
from vidange.mycelium.mycelium import Demande, Mycelium
from vidange.prehension.prehension import QUOI_FAIRE as QUOI_FAIRE_PREHENSION
from vidange.prehension.prehension import Prehension
from vidange.reglages import PlaceSimulee
from vidange.remplissage.remplissage import QUOI_FAIRE, Remplissage

GESTE = "remplissage_geste_max"
GESTE_PREHENSION = "prehension_geste_max"
DOSAGE = "remplissage_dosage_max"


@dataclass(frozen=True)
class SeauAFaire:
    seau: str
    format: str
    variete: str
    file: str
    cycle: int | None = None


@dataclass
class Plan:
    """Les seaux à remplir, où les prendre et où rendre le seau du dessus d'une prise double."""

    seaux: list[SeauAFaire]
    stockage: PlaceSimulee
    rendu: PlaceSimulee
    versement_s: float
    # Appelé quand la préhension va prendre ce seau, et à chaque versement (simulateur).
    debut_seau: Callable[[SeauAFaire], object] = lambda seau: None
    versement: Callable[[SeauAFaire, int], object] = lambda seau, couche: None
    numero: int = 0
    couche: int = 1
    faits: list[str] = field(default_factory=list)

    @property
    def seau(self) -> SeauAFaire:
        return self.seaux[self.numero]


def module_remplissage(
    remplissage: Remplissage, prehension: Prehension, mycelium: Mycelium, plan: Plan
) -> Module:
    chariot, tete = remplissage.chariot, prehension.tete
    fin = Condition("geste du chariot de remplissage fini", remplissage.geste_fini)
    fin_tete = Condition("geste de la préhension fini", prehension.geste_fini)
    garage = Condition(
        "agitateur du mycélium au garage (le chariot peut rouler et monter au poste)",
        lambda: (
            remplissage.contexte().agitateur_au_garage
            and remplissage.contexte().refus_mycelium is None
        ),
    )
    libre = Condition("chariot de remplissage libre", remplissage.libre)

    def geste(nom: str, fabrique, ensuite=None, entree=()) -> Etape:
        return Etape(
            nom,
            QUOI_FAIRE,
            action=lambda: remplissage.lancer(fabrique),
            fin=fin,
            delai_max=GESTE,
            entree=(chariot.pretes, *entree),
            ensuite=ensuite,
        )

    def geste_tete(nom: str, fabrique, ensuite=None) -> Etape:
        return Etape(
            nom,
            QUOI_FAIRE_PREHENSION,
            action=lambda: prehension.lancer(fabrique),
            fin=fin_tete,
            delai_max=GESTE_PREHENSION,
            entree=(tete.pretes, chariot.pretes),
            ensuite=ensuite,
        )

    def prendre():
        seau, place = plan.seau, plan.stockage
        plan.debut_seau(seau)
        return prehension.geste_prendre("seau", place.x, place.y, place.contact_z, seau.format)

    def poser():
        seau = plan.seau
        return remplissage.geste_poser_seau(prehension, seau.format, seau.seau, seau.cycle)

    def apres_pose() -> str:
        return "rendre_le_seau_du_dessus" if remplissage.seau_du_dessus else "orienter_l_anse"

    def rendre():
        place = plan.rendu
        return prehension.geste_poser(place.x, place.y, place.contact_z)

    def apres_rendu() -> None:
        remplissage.seau_rendu()

    def verser():
        plan.versement(plan.seau, plan.couche)
        return remplissage.geste_tourner(plan.versement_s)

    def doser() -> None:
        seau = plan.seau
        mycelium.demander(Demande(seau.seau, seau.format, plan.couche, seau.variete, seau.cycle))

    def apres_dose() -> str:
        if plan.couche < remplissage.format(plan.seau.format).couches:
            plan.couche += 1
            return "revenir_au_poste"
        return "ranger"

    def apres_rangement() -> str:
        plan.faits.append(plan.seau.seau)
        plan.numero += 1
        plan.couche = 1
        if plan.numero < len(plan.seaux):
            return "aller_a_la_pose"
        mycelium.terminer()
        return "fin"

    return Module(
        nom="remplissage",
        etapes=(
            geste(
                "aller_a_la_pose",
                lambda: remplissage.geste_aller_a_la_pose(plan.seau.format),
                entree=(garage,),
            ),
            geste_tete("prendre_le_seau", prendre),
            geste_tete("poser_le_seau", poser, apres_pose),
            geste_tete(
                "rendre_le_seau_du_dessus", rendre, lambda: apres_rendu() or "orienter_l_anse"
            ),
            geste("orienter_l_anse", remplissage.geste_orienter_anse),
            geste("centrer", remplissage.geste_centrer),
            geste("ramener_au_poste", remplissage.geste_ramener_au_poste, entree=(garage,)),
            geste("verser", verser),
            Etape(
                "doser",
                "Le Mycélium dose la couche : regarder son module s'il est en alarme.",
                action=doser,
                fin=Condition("dose de la couche versée", lambda: not mycelium.couche_en_attente()),
                delai_max=DOSAGE,
                ensuite=apres_dose,
            ),
            geste(
                "revenir_au_poste",
                remplissage.geste_ramener_au_poste,
                lambda: "verser",
                entree=(libre, garage),
            ),
            geste(
                "ranger",
                lambda: remplissage.geste_ranger(plan.seau.file),
                apres_rangement,
                entree=(libre, garage),
            ),
            Etape("fin", "Rien à faire : plus de seau à remplir.", ensuite=lambda: None),
        ),
        surveillances=(chariot.surveillance, tete.surveillance),
        pauser=lambda: (remplissage.pauser(), prehension.pauser()),
        reprendre=lambda: (remplissage.reprendre(), prehension.reprendre()),
        arreter=lambda: (remplissage.arreter(), prehension.arreter()),
    )
