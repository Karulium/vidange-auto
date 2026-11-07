"""Le module « remplissage » : un seau vide posé, rempli couche après couche, rangé.

Il tourne avec le module « mycelium », qui mène le chariot pendant le dosage (Mycelium.demander,
puis `ecarter` et `amener_au_dosage` du Remplissage). Les versements de la griffe sont ceux d'un
`Plan` (le seau tourne pendant `versement_s`) : c'est le scénario « remplissage » du simulateur,
et un essai. Avec la vraie griffe (`griffe`, vidange.cycle.griffe_du_lot, tâche 45 sexies),
l'étape « verser » attend qu'elle ait versé et tassé la couche (le seau tourne quand elle le
demande), et les gestes de la préhension attendent la griffe garée (même pont).

    aller_a_la_pose        chariot à y 0,50, barres à l'approche, plateau sous la hauteur de pose
    prendre_le_seau        la préhension prend un seau vide au stockage
    poser_le_seau          plateau au contact (balance), centrage ; barrière coupée : prise double
    rendre_le_seau_du_dessus   après une prise double : le seau du dessus rendu au stockage
    orienter_l_anse        plateau à plateau_lecture_qr, QR du flanc lu pendant que le seau tourne
                           (un tour au plus), oreilles de l'anse à 45° des barres
    centrer                barres en position au contact du corps, puis ouvertes
    aller_au_poste         (mode seaux) le seau VIDE au poste (y 0,135), plateau à sa hauteur
    spray_...              (avec le Spray) les étapes du module « spray » : une dose par seau,
                           sur le seau vide, pendant le 1er aller-retour de la griffe
    micropore_rangee_du_haut   (avec le Micropore, mode seaux) tour de repérage et rangées du
                           haut, sur le seau vide, après le spray
    ramener_au_vidage      y 0,42, plateau à la hauteur du vidage (manivelle du mycélium en bas
                           si le chariot part de près du poste)
    verser                 versement de la griffe au vidage : le seau tourne (permission du chef :
                           pas pendant la purge de l'enceinte) ; avec la vraie griffe, le seau
                           attend, arrêté, qu'elle ait versé et tassé la couche
    doser                  le Mycélium dose la couche (il mène le chariot : poste, dosage, retour
                           au vidage)
    revenir_au_vidage      couche suivante : retour au vidage (plateau à sa hauteur)
    preparer_le_couvercle  (avec le Couvercle, tâche 41 bis) après la dernière couche : chariot à
                           y 0,50, plateau à H_app, barres ouvertes, pesée P0
    prendre_le_couvercle   la préhension prend un couvercle à la pile du stockage
    poser_le_couvercle     elle le pose sur le seau plein (sans appuyer) et s'en va
    controler_le_couvercle la balance voit P − P0 ≈ la masse d'un couvercle
    ranger_le_bras         (avec la Fermeture, tâche 41) au démarrage : bras du galet rangé,
                           plateau en bas
    fermer_le_seau         (avec la Fermeture) après la dernière couche : le couvercle posé est
                           clipsé (vidange.fermeture) ; une alerte laisse le seau « à vérifier »
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
from typing import TYPE_CHECKING, Protocol

from vidange.chef import Condition, ErreurEtape, Etape, Module
from vidange.mycelium.mycelium import Demande, Mycelium
from vidange.prehension.prehension import QUOI_FAIRE as QUOI_FAIRE_PREHENSION
from vidange.prehension.prehension import Prehension
from vidange.reglages import PlaceSimulee
from vidange.remplissage.remplissage import QUOI_FAIRE, Remplissage
from vidange.stockage.stockage import BANDE, QUOI_FAIRE_BANDE, QUOI_FAIRE_TIROIR, Stockage

if TYPE_CHECKING:
    from vidange.couvercle.couvercle import Couvercle
    from vidange.spray.spray import Spray

GESTE = "remplissage_geste_max"
GESTE_PREHENSION = "prehension_geste_max"
DOSAGE = "remplissage_dosage_max"
# Une couche versée par la vraie griffe (plusieurs prises dans le fût).
COUCHE_GRIFFE = "remplissage_couche_griffe_max"
QUOI_FAIRE_GRIFFE = (
    "La griffe verse la couche de substrat dans le seau : regarder son module (alarme, poste du "
    "fût pas prêt ?) et la vidéo de la griffe. Corriger, puis acquitter et donner le Go."
)


class CouchesDeLaGriffe(Protocol):
    """La vraie griffe vue du Remplissage (vidange.cycle.griffe_du_lot.GriffeDuSeau)."""

    # La griffe ne gêne pas un trajet du pont de la préhension (même pont, même chariot Y).
    garee: Condition

    def attendre(self, seau: int, couche: int) -> None:
        """Le seau `seau` (numéro dans le lot) attend sa couche `couche` au vidage."""
        ...

    def couche_versee(self) -> bool:
        """La couche attendue est versée et tassée (ErreurEtape : elle ne viendra pas)."""
        ...


@dataclass(frozen=True)
class SeauAFaire:
    # Le QR du seau ; "" : pas connu d'avance (lot lancé depuis la page web, tâche 45 quater), le
    # code est celui que lit la caméra du micropore sur le flanc.
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
    remplissage: Remplissage,
    prehension: Prehension,
    mycelium: Mycelium,
    plan: Plan,
    air: Condition | None = None,
    seau_vide_au_poste: bool = False,
    spray: "Spray | None" = None,
    griffe_partie: Callable[[], bool] = lambda: False,
    couvercle: "Couvercle | None" = None,
    zone_bras_spray: Callable[[], bool] = lambda: False,
    griffe: CouchesDeLaGriffe | None = None,
) -> Module:
    """`air` : condition d'entrée de la prise d'un seau par le venturi (sur la machine :
    `chef.condition_permission("air")`, l'attente de mise en pression du module Air, tâche 42).

    `seau_vide_au_poste` (mode seaux, tâche 45, fils Spray et Micropore du 07/11/2026) : après le
    centrage, le seau VIDE va au poste ; le `spray` (s'il est donné) y dose, une fois par seau,
    pendant le 1er aller-retour de la griffe ; son bras ne sort et ne rentre que zone du bras
    libre (`zone_bras_spray` : aucune partie de la griffe, de la préhension ou de ce qu'elles
    tiennent dedans, fil Spray du 07/11/2026, vidange.spray.zone), puis le micropore pose ses
    rangées du haut ; ensuite seulement la 1re couche. La rangée du fond reste au vidage, quand
    le seau pèse assez (micropore → fond_poids_min_kg).

    `couvercle` (tâche 41 bis) : après la dernière couche, la préhension pose un couvercle sur le
    seau plein avant la fermeture ; la pose attend le bras de fermeture rangé et la griffe
    partie (`griffe_partie`).

    `griffe` (tâche 45 sexies) : la vraie griffe. L'étape « verser » ne fait plus tourner le seau
    pendant `plan.versement_s` : elle dit à la griffe quelle couche le seau attend, puis attend
    qu'elle l'ait versée et tassée. Chaque geste de la préhension attend la griffe garée."""
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
    # Pas de versement dans le seau ouvert pendant la purge de l'enceinte (« purge en cours »).
    versement_permis = Condition(
        "permission du chef : versement dans un seau ouvert (pas de purge en cours)",
        remplissage.versement_permis,
    )
    # Règle 7 : sans le plateau du fût en place, l'axe du plateau reste à y ≤ 0,475.
    pose_permise = Condition(
        "plateau du fût en place (le chariot de remplissage va à la pose du seau vide)",
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
        "plateau du fût en place (le chariot de remplissage va à la file du seau)",
        lambda: remplissage.place_permise(y_du_rangement(file_du_seau())),
    )

    # Micropore (tâche 40) : un geste du chariot ne part que tête vue escamotée au ToF (après un
    # redémarrage de la carte du plateau, il attend qu'elle soit relue plutôt que d'être refusé).
    micropore: tuple[Condition, ...] = ()
    if remplissage.micropore_branche:
        micropore = (
            Condition(
                "tête du micropore vue escamotée (capteur de distance)",
                lambda: remplissage.contexte().micropore_escamote is True,
            ),
        )

    # Fermeture (tâche 41) : au démarrage le bras est rangé (plateau en bas), puis chaque seau plein
    # est fermé. Le couvercle est posé par la préhension avant (geste à écrire avec le solveur).
    fermeture: tuple[Etape, ...] = ()
    ranger_le_bras: tuple[Etape, ...] = ()
    if remplissage.fermeture_branchee:
        bas = Condition(
            "plateau assez bas pour tourner le bras de fermeture (zéro de la montée fait)",
            lambda: remplissage.refus_bras_galet() is None,
        )
        ranger_le_bras = (
            Etape(
                "ranger_le_bras",
                QUOI_FAIRE,
                action=lambda: remplissage.lancer(remplissage.geste_ranger_bras),
                fin=fin,
                delai_max=GESTE,
                entree=(chariot.pretes, bas),
            ),
        )

    def geste(nom: str, fabrique, ensuite=None, entree=()) -> Etape:
        return Etape(
            nom,
            QUOI_FAIRE,
            action=lambda: remplissage.lancer(fabrique),
            fin=fin,
            delai_max=GESTE,
            entree=(chariot.pretes, *boucle, *micropore, *entree),
            ensuite=ensuite,
        )

    if remplissage.fermeture_branchee:
        fermeture = (
            geste("fermer_le_seau", remplissage.geste_fermer, entree=(libre, manivelle_en_bas)),
        )

    # Même pont que la griffe : la préhension ne part que griffe garée (tâche 45 sexies).
    griffe_garee: tuple[Condition, ...] = () if griffe is None else (griffe.garee,)

    def geste_tete(nom: str, fabrique, ensuite=None, avec_air: bool = False, entree=()) -> Etape:
        venturi = (air,) if avec_air and air is not None else ()
        return Etape(
            nom,
            QUOI_FAIRE_PREHENSION,
            action=lambda: prehension.lancer(fabrique),
            fin=fin_tete,
            delai_max=GESTE_PREHENSION,
            entree=(tete.pretes, chariot.pretes, *boucle, *venturi, *griffe_garee, *entree),
            ensuite=ensuite,
        )

    # Couvercle (tâche 41 bis) : posé sur le seau plein, avant la fermeture.
    pose_couvercle: tuple[Etape, ...] = ()
    if couvercle is not None:
        bras_range = Condition(
            "bras de fermeture vu rangé (la tête ne pose le couvercle que bras rangé)",
            lambda: remplissage.contexte().bras_galet_range is True,
        )
        griffe_loin = Condition("griffe hors du chemin de la préhension", griffe_partie)

        def format_du_seau() -> str:
            return plan.seau.format

        def masse_et_tolerance():
            return remplissage.geste_controler_couvercle(
                couvercle.masse_kg(format_du_seau()), couvercle.tolerance_kg(format_du_seau())
            )

        def apres_controle() -> str:
            return "fermer_le_seau" if remplissage.fermeture_branchee else "ranger"

        pose_couvercle = (
            geste(
                "preparer_le_couvercle",
                lambda: remplissage.geste_preparer_couvercle(
                    couvercle.plateau_z(format_du_seau()), couvercle.chariot_y()
                ),
                entree=(libre, manivelle_en_bas, bras_range),
            ),
            geste_tete(
                "prendre_le_couvercle",
                lambda: couvercle.geste_prendre(prehension, format_du_seau()),
                avec_air=True,
            ),
            geste_tete(
                "poser_le_couvercle",
                lambda: couvercle.geste_poser(prehension, format_du_seau()),
                entree=(bras_range, griffe_loin),
            ),
            geste("controler_le_couvercle", masse_et_tolerance, apres_controle, entree=(libre,)),
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
        return remplissage.geste_poser_seau(prehension, seau.format, seau.seau or None, seau.cycle)

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

    if griffe is None:
        etape_verser = geste("verser", verser, entree=(versement_permis,))
    else:
        vraie_griffe = griffe

        def attendre_la_griffe() -> None:
            plan.versement(plan.seau, plan.couche)
            vraie_griffe.attendre(plan.numero, plan.couche)

        etape_verser = Etape(
            "verser",
            QUOI_FAIRE_GRIFFE,
            action=attendre_la_griffe,
            fin=Condition(
                "couche de substrat versée et tassée par la griffe (seau arrêté)",
                lambda: vraie_griffe.couche_versee() and remplissage.libre(),
            ),
            delai_max=COUCHE_GRIFFE,
            entree=(chariot.pretes, *boucle, *micropore, versement_permis),
        )

    # Le dernier QR lu sur le flanc du seau en cours (le seau rangé n'est plus sur le plateau).
    dernier_lu = [""]

    def code_du_seau() -> str:
        """Le QR du seau en cours : celui du plan, ou celui lu sur son flanc."""
        sur_le_plateau = remplissage.seau
        if sur_le_plateau is not None and sur_le_plateau.code:
            dernier_lu[0] = sur_le_plateau.code
        return plan.seau.seau or dernier_lu[0]

    def doser() -> None:
        seau = plan.seau
        mycelium.demander(
            Demande(code_du_seau(), seau.format, plan.couche, seau.variete, seau.cycle)
        )

    def apres_dose() -> str:
        if plan.couche < remplissage.format(plan.seau.format).couches:
            plan.couche += 1
            return "revenir_au_vidage"
        # Couvercle (tâche 41 bis) posé sur le seau plein, puis clipsé (tâche 41) avant le rangé.
        if couvercle is not None:
            return "preparer_le_couvercle"
        return "fermer_le_seau" if remplissage.fermeture_branchee else "ranger"

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
        plan.faits.append(code_du_seau())
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

    # Seau vide au poste (y 0,135) : spray, puis rangées du haut du micropore, avant la 1re couche.
    au_poste: tuple[Etape, ...] = ()
    if seau_vide_au_poste or spray is not None:
        au_poste = (
            geste(
                "aller_au_poste",
                remplissage.geste_aller_au_poste,
                entree=(libre, manivelle_en_bas),
            ),
        )
        if spray is not None:
            from vidange.spray.module import etapes_du_spray

            def seau_au_poste() -> tuple[str | None, str] | None:
                seau = remplissage.seau
                if seau is None or not remplissage.au_poste():
                    return None
                return seau.code, seau.format

            au_poste += etapes_du_spray(
                spray,
                seau_au_poste,
                zone_bras_spray,
                lambda: remplissage.contexte().micropore_escamote,
            )
        if remplissage.micropore_branche:
            au_poste += (
                geste(
                    "micropore_rangee_du_haut",
                    remplissage.geste_micropore_au_poste,
                    entree=(libre,),
                ),
            )

    def arreter() -> None:
        remplissage.arreter()
        prehension.arreter()
        if spray is not None:
            spray.arreter()

    return Module(
        nom="remplissage",
        etapes=(
            *ranger_le_bras,
            *debut,
            geste(
                "aller_a_la_pose",
                lambda: remplissage.geste_aller_a_la_pose(plan.seau.format),
                entree=(manivelle_en_bas, pose_permise),
            ),
            geste_tete("prendre_le_seau", prendre, avec_air=True),
            geste_tete("poser_le_seau", poser, apres_pose),
            geste_tete(
                "rendre_le_seau_du_dessus", rendre, lambda: apres_rendu() or "orienter_l_anse"
            ),
            geste("orienter_l_anse", remplissage.geste_orienter_anse),
            geste("centrer", remplissage.geste_centrer),
            *au_poste,
            geste(
                "ramener_au_vidage", remplissage.geste_ramener_au_vidage, entree=(manivelle_en_bas,)
            ),
            etape_verser,
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
            *pose_couvercle,
            *fermeture,
            geste(
                "ranger", ranger, apres_rangement, entree=(libre, manivelle_en_bas, file_permise)
            ),
            *etapes_stockage,
            Etape("fin", "Rien à faire : plus de seau à remplir.", ensuite=lambda: None),
        ),
        surveillances=(chariot.surveillance, tete.surveillance, *boucle),
        pauser=lambda: (remplissage.pauser(), prehension.pauser()),
        reprendre=lambda: (remplissage.reprendre(), prehension.reprendre()),
        arreter=arreter,
    )
