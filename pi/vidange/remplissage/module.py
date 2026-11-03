"""Le module « remplissage » : un seau vide posé, rempli couche après couche, rangé.

Il tourne avec le module « mycelium », qui mène le chariot pendant le dosage (Mycelium.demander,
puis `ecarter` et `amener_au_dosage` du Remplissage). Les versements de la griffe sont ceux d'un
`Plan` (le seau tourne pendant `versement_s`) : le vrai enchaînement avec la griffe viendra avec
le solveur (tâche 23). C'est le scénario « remplissage » du simulateur, et un essai.

    aller_a_la_pose        chariot à y 0,50, barres à l'approche, plateau sous la hauteur de pose
    prendre_le_seau        la préhension prend un seau vide au stockage
    poser_le_seau          plateau au contact (balance), centrage ; barrière coupée : prise double
    rendre_le_seau_du_dessus   après une prise double : le seau du dessus rendu au stockage
    orienter_l_anse        QR du flanc lu, oreilles de l'anse à 45° des barres
    centrer                barres en position au contact du corps, puis ouvertes
    ramener_au_vidage      y 0,42, plateau à la hauteur du vidage (manivelle du mycélium en bas
                           si le chariot part de près du poste)
    verser                 versement de la griffe au vidage : le seau tourne
    doser                  le Mycélium dose la couche (il mène le chariot : poste, dosage, retour
                           au vidage)
    revenir_au_vidage      couche suivante : retour au vidage (plateau à sa hauteur)
    ranger                 anse à son angle, chariot à sa file plateau en bas, le pousseur pousse ;
                           ou sur la bande du haut (plateau à 0,4985), quand le tiroir est plein
    fin                    plus de seau

Avec le Stockage (`Plan.magasin`, tâche 35), les seaux vides viennent des piles (dans l'ordre de
vidage), le seau du dessus d'une prise double retourne sur sa pile, la place est choisie par
l'inventaire (le tiroir, puis la bande du haut), et chaque geste attend la boucle du stockage
fermée (elle est aussi surveillée pendant les gestes). Quatre étapes de plus :

    verifier_place         une place libre pour ce seau ? sinon : vider le tiroir (et la bande)
    photo_de_la_bande      après une poussée sur la bande du haut : photo du plafond, chaque
                           seau à y 0,215 ± 0,007 (sinon arrêt et alerte)
    vider_le_tiroir        plus de place (ou fin de lot) : substrat restant noté, le Pi attend que
                           la boucle s'ouvre (tiroir tiré) puis se referme
    confirmer_tiroir_vide  Go de Karulium à l'écran : les files repartent vides
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from vidange.chef import Condition, ErreurEtape, Etape, Module
from vidange.mycelium.mycelium import Demande, Mycelium
from vidange.prehension.prehension import QUOI_FAIRE as QUOI_FAIRE_PREHENSION
from vidange.prehension.prehension import Prehension
from vidange.reglages import PlaceSimulee
from vidange.remplissage.remplissage import QUOI_FAIRE, Remplissage
from vidange.stockage.stockage import BANDE, QUOI_FAIRE_BANDE, QUOI_FAIRE_TIROIR, Stockage

GESTE = "remplissage_geste_max"
GESTE_PREHENSION = "prehension_geste_max"
DOSAGE = "remplissage_dosage_max"


@dataclass(frozen=True)
class SeauAFaire:
    seau: str
    format: str
    variete: str
    # Sans file : le Stockage la choisit (Plan.magasin).
    file: str | None = None
    cycle: int | None = None


@dataclass
class Plan:
    """Les seaux à remplir, où les prendre et où rendre le seau du dessus d'une prise double :
    places fixes (`stockage`, `rendu` : simulateur, essais), ou le Stockage (`magasin`)."""

    seaux: list[SeauAFaire]
    versement_s: float
    stockage: PlaceSimulee | None = None
    rendu: PlaceSimulee | None = None
    magasin: Stockage | None = None
    # Fin de lot : le tiroir est vidé à la fin, comme quand il est plein (avec le Stockage).
    fin_de_lot: bool = False
    # Substrat qui reste dans le fût (kg), noté quand le cycle attend le vidage du tiroir.
    substrat_restant: Callable[[], float | None] = lambda: None
    # Appelé quand la préhension va prendre ce seau, et à chaque versement (simulateur).
    debut_seau: Callable[[SeauAFaire], object] = lambda seau: None
    versement: Callable[[SeauAFaire, int], object] = lambda seau, couche: None
    numero: int = 0
    couche: int = 1
    faits: list[str] = field(default_factory=list)
    # La file où le seau en cours est rangé (choisie par le Stockage).
    file_en_cours: str | None = None

    @property
    def seau(self) -> SeauAFaire:
        return self.seaux[self.numero]


def module_remplissage(
    remplissage: Remplissage, prehension: Prehension, mycelium: Mycelium, plan: Plan
) -> Module:
    chariot, tete = remplissage.chariot, prehension.tete
    magasin = plan.magasin
    # Règle 9 : la tête ne descend au-dessus du chariot que barres ouvertes, micropore rentré.
    remplissage.brancher_prehension(prehension)
    # Stockage : verrous des trajets au-dessus des piles, boucle du tiroir et des panneaux.
    boucle: tuple[Condition, ...] = ()
    if magasin is not None:
        magasin.brancher_prehension(prehension)
        boucle = (magasin.boucle,)
    fin = Condition("geste du chariot de remplissage fini", remplissage.geste_fini)
    fin_tete = Condition("geste de la préhension fini", prehension.geste_fini)
    manivelle_en_bas = Condition(
        "manivelle du mycélium en bas, arrêtée (le chariot peut rouler près du poste)",
        lambda: remplissage.contexte().refus_mycelium is None,
    )
    libre = Condition("chariot de remplissage libre", remplissage.libre)
    # Règle 7 : sans le chariot du fût en place, l'axe du plateau reste à y ≤ 0,475.
    pose_permise = Condition(
        "chariot du fût en place (le chariot de remplissage va à la pose du seau vide)",
        lambda: remplissage.place_permise(remplissage.reglages.pose_y),
    )

    def file_du_seau() -> str:
        """La file du seau, ou BANDE (bande du haut du Stockage)."""
        if magasin is None:
            if plan.seau.file is None:
                raise ErreurEtape(f"remplissage : pas de file pour le seau {plan.seau.seau}")
            return plan.seau.file
        place = magasin.place_libre(plan.seau.format)
        if place is None:
            raise ErreurEtape("remplissage : plus de place au stockage", QUOI_FAIRE)
        return place

    def y_du_rangement(place: str) -> float:
        rangement = remplissage.reglages.rangement
        if place == BANDE:
            assert rangement.bande_haut is not None
            return rangement.bande_haut.y
        return rangement.files[place].y

    file_permise = Condition(
        "chariot du fût en place (le chariot de remplissage va à la file du seau)",
        lambda: remplissage.place_permise(y_du_rangement(file_du_seau())),
    )

    def geste(nom: str, fabrique, ensuite=None, entree=()) -> Etape:
        return Etape(
            nom,
            QUOI_FAIRE,
            action=lambda: remplissage.lancer(fabrique),
            fin=fin,
            delai_max=GESTE,
            entree=(chariot.pretes, *boucle, *entree),
            ensuite=ensuite,
        )

    def geste_tete(nom: str, fabrique, ensuite=None) -> Etape:
        return Etape(
            nom,
            QUOI_FAIRE_PREHENSION,
            action=lambda: prehension.lancer(fabrique),
            fin=fin_tete,
            delai_max=GESTE_PREHENSION,
            entree=(tete.pretes, chariot.pretes, *boucle),
            ensuite=ensuite,
        )

    def place_fixe(place: PlaceSimulee | None, quoi: str) -> PlaceSimulee:
        if place is None:
            raise ErreurEtape(f"remplissage : pas de place pour {quoi} (ni Stockage)")
        return place

    def prendre():
        seau = plan.seau
        plan.debut_seau(seau)
        if magasin is not None:
            return magasin.geste_prendre_seau(prehension, seau.format)
        place = place_fixe(plan.stockage, "prendre les seaux vides")
        return prehension.geste_prendre("seau", place.x, place.y, place.contact_z, seau.format)

    def poser():
        seau = plan.seau
        return remplissage.geste_poser_seau(prehension, seau.format, seau.seau, seau.cycle)

    def apres_pose() -> str:
        if not remplissage.seau_du_dessus:
            return "orienter_l_anse"
        if magasin is not None:
            magasin.prise_double()
        return "rendre_le_seau_du_dessus"

    def rendre():
        if magasin is not None:
            return magasin.geste_rendre_seau(prehension)
        place = place_fixe(plan.rendu, "rendre le seau du dessus")
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
            return "revenir_au_vidage"
        return "ranger"

    def ranger():
        place = plan.file_en_cours = file_du_seau()
        if place == BANDE:
            return remplissage.geste_ranger_en_haut()
        if magasin is None:
            return remplissage.geste_ranger(place)
        course = remplissage.reglages.rangement.files[place].pousseur_m
        return remplissage.geste_ranger(
            place, magasin.course_pousseur(place, plan.seau.format, course)
        )

    def apres_rangement() -> str:
        if magasin is not None and plan.file_en_cours is not None:
            magasin.seau_range(plan.file_en_cours, plan.seau.format)
            if plan.file_en_cours == BANDE:
                return "photo_de_la_bande"
        return suite()

    def suite() -> str:
        plan.faits.append(plan.seau.seau)
        plan.numero += 1
        plan.couche = 1
        if plan.numero < len(plan.seaux):
            return "aller_a_la_pose" if magasin is None else "verifier_place"
        mycelium.terminer()
        if magasin is not None and plan.fin_de_lot and magasin.seaux_pleins() > 0:
            magasin.demander_vidage("fin de lot", plan.substrat_restant())
            return "vider_le_tiroir"
        return "fin"

    def verifier_place() -> str:
        assert magasin is not None
        if magasin.place_libre(plan.seau.format) is not None:
            return "aller_a_la_pose"
        magasin.demander_vidage("plus de place au stockage", plan.substrat_restant())
        return "vider_le_tiroir"

    def apres_vidage() -> str:
        return "verifier_place" if plan.numero < len(plan.seaux) else "fin"

    etapes_stockage: tuple[Etape, ...] = ()
    if magasin is not None:
        etapes_stockage = (
            Etape(
                "photo_de_la_bande",
                QUOI_FAIRE_BANDE,
                action=magasin.verifier_bande,
                ensuite=suite,
            ),
            Etape(
                "vider_le_tiroir",
                QUOI_FAIRE_TIROIR,
                entree=(
                    Condition(
                        "tiroir du stockage vidé (boucle vue ouverte, puis refermée)",
                        magasin.tiroir_ressorti_et_remis,
                        QUOI_FAIRE_TIROIR,
                    ),
                ),
            ),
            Etape(
                "confirmer_tiroir_vide",
                "Confirmer à l'écran que le tiroir du stockage est vide (Go).",
                action=magasin.tiroir_vide,
                entree=(magasin.boucle,),
                demande_go=True,
                ensuite=apres_vidage,
            ),
        )
    debut: tuple[Etape, ...] = ()
    if magasin is not None:
        debut = (
            # La boucle est surveillée à chaque étape : on l'attend ici (le Pi le dit à l'écran).
            Etape("verifier_place", QUOI_FAIRE_TIROIR, entree=boucle, ensuite=verifier_place),
        )

    return Module(
        nom="remplissage",
        etapes=(
            *debut,
            geste(
                "aller_a_la_pose",
                lambda: remplissage.geste_aller_a_la_pose(plan.seau.format),
                entree=(manivelle_en_bas, pose_permise),
            ),
            geste_tete("prendre_le_seau", prendre),
            geste_tete("poser_le_seau", poser, apres_pose),
            geste_tete(
                "rendre_le_seau_du_dessus", rendre, lambda: apres_rendu() or "orienter_l_anse"
            ),
            geste("orienter_l_anse", remplissage.geste_orienter_anse),
            geste("centrer", remplissage.geste_centrer),
            geste(
                "ramener_au_vidage", remplissage.geste_ramener_au_vidage, entree=(manivelle_en_bas,)
            ),
            geste("verser", verser),
            Etape(
                "doser",
                "Le Mycélium dose la couche : regarder son module s'il est en alarme.",
                action=doser,
                fin=Condition(
                    "dose de la couche versée, bocal remis debout, manivelle en bas",
                    lambda: not mycelium.couche_en_attente() and not mycelium.dosage_en_cours(),
                ),
                delai_max=DOSAGE,
                ensuite=apres_dose,
            ),
            geste(
                "revenir_au_vidage",
                remplissage.geste_ramener_au_vidage,
                lambda: "verser",
                entree=(libre, manivelle_en_bas),
            ),
            geste(
                "ranger", ranger, apres_rangement, entree=(libre, manivelle_en_bas, file_permise)
            ),
            *etapes_stockage,
            Etape("fin", "Rien à faire : plus de seau à remplir.", ensuite=lambda: None),
        ),
        surveillances=(chariot.surveillance, tete.surveillance, *boucle),
        pauser=lambda: (remplissage.pauser(), prehension.pauser()),
        reprendre=lambda: (remplissage.reprendre(), prehension.reprendre()),
        arreter=lambda: (remplissage.arreter(), prehension.arreter()),
    )
