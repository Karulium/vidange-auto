"""Le Stockage : places, inventaire, verrous des trajets, gestes qui appellent la Préhension.

    stockage = Stockage(machine, boucle_fermee=lambda: materiel.lire("boucle_stockage"),
                        registre=registre)
    stockage.charger_pile("pile_1", "seau_a", 5)        # dit à l'écran par l'opérateur
    stockage.brancher_prehension(prehension)           # verrous des trajets à chaque pas
    stockage.brancher_griffe(griffe)
    prehension.lancer(lambda: stockage.geste_prendre_seau(prehension, "seau_a"))
    stockage.file_libre("seau_a")                      # « file_1 » ; None : tiroir plein

Le Stockage est passif (aucun moteur) et n'a aucun capteur de présence : le Pi tient
l'inventaire de chaque place (vidange.stockage.inventaire, gardé dans le registre). Une seule
entrée : la boucle des 3 microrupteurs NF en série (tiroir rentré et verrouillé, P1 et P2
fermés). Boucle ouverte : aucun mouvement du portique ni du chariot ; le Pi attend et le dit à
l'écran (il ne sait pas lequel des trois est ouvert). Elle informe et fait attendre : la
sécurité des personnes reste câblée (portes, arrêt d'urgence).

Piles de seaux vides : vidées dans l'ordre (rangée y 0,84, puis 0,53, puis la bande 0,215 ; la
pile la plus proche du chariot d'abord), le seau du haut pris à la cote attendue (l'écart de
5 mm de la Préhension s'applique) ; il se sépare seul de la pile (pas de geste spécial). Seau
d'une pile de la bande : il en sort en longeant vers −x jusqu'à x 1,29, puis vers +y jusqu'à
0,44 (caméra du bocal).

Tiroir : files remplies dans l'ordre, la place exacte (y) est celle du Remplissage. Plus de
place libre : le module du Remplissage attend (vidange.remplissage.module), le Pi note le
substrat restant, invite à vider le tiroir, attend que la boucle s'ouvre puis se referme, puis
la confirmation à l'écran (Go) avant de remettre les files à zéro.

Bande du haut : case vide (désactivée par un réglage) ; bocaux, boîtes à capsules : places et
inventaire, les gestes viendront avec l'Entonnoir et la vision.
"""

from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Protocol

from vidange.chef import Condition, ErreurEtape
from vidange.journal import donner_journal
from vidange.prehension.regles import Pose
from vidange.reglages import Machine
from vidange.stockage import places
from vidange.stockage.inventaire import InventaireStockage
from vidange.stockage.regles import PileVue, ReglesStockage

if TYPE_CHECKING:
    from vidange.griffe.griffe import Griffe
    from vidange.prehension.prehension import Prehension

Geste = Generator[object, object, None]

journal = donner_journal("stockage")

QUOI_FAIRE = (
    "Regarder le stockage : tiroir rentré et verrouillé, panneaux P1 et P2 fermés, piles "
    "comme l'écran les montre. Corriger l'inventaire à l'écran si besoin, puis acquitter et "
    "donner le Go."
)
QUOI_FAIRE_BOUCLE = (
    "Rentrer et verrouiller le tiroir du stockage, fermer les panneaux P1 et P2 : le Pi attend "
    "la boucle fermée pour bouger."
)
QUOI_FAIRE_TIROIR = (
    "Tiroir du stockage plein : vider le plateau du haut s'il le faut (bocaux, tapis), relever "
    "P1 et P2, déverrouiller et tirer le tiroir, sortir les seaux pleins, tout remettre (tiroir "
    "rentré et verrouillé, panneaux fermés), puis confirmer à l'écran (Go)."
)


class Registre(Protocol):
    def noter_place_stockage(self, place: str, contenu: str | None, nombre: int) -> None: ...

    def inventaire_stockage(self) -> dict[str, tuple[str | None, int]]: ...


class Stockage:
    def __init__(
        self,
        machine: Machine,
        boucle_fermee: Callable[[], bool | None],
        registre: Registre | None = None,
    ) -> None:
        assert machine.stockage is not None and machine.griffe is not None
        self.machine = machine
        self.reglages = machine.stockage
        self.regles = ReglesStockage(machine)
        self._boucle = boucle_fermee
        fin_de_lot = self.reglages.piles.fin_de_lot.places_max
        piles = [
            *self.reglages.piles.places,
            *(places.nom_fin_de_lot(i) for i in range(1, fin_de_lot + 1)),
        ]
        self.inventaire = InventaireStockage(
            piles,
            list(self.reglages.tiroir.files),
            list(self.reglages.boites.places),
            noter=(lambda *a: None) if registre is None else registre.noter_place_stockage,
        )
        if registre is not None:
            self.inventaire.reprendre(registre.inventaire_stockage())
        self.boucle = Condition(
            "boucle du stockage fermée (tiroir rentré et verrouillé, P1 et P2 fermés)",
            self.boucle_fermee,
            QUOI_FAIRE_BOUCLE,
        )
        # La pile dont vient le seau tenu (pour la prise double et le rendu du seau du dessus).
        self.pile_en_cours: str | None = None
        self.format_en_cours: str | None = None
        # Vidage du tiroir demandé : la boucle a-t-elle été vue ouverte depuis ?
        self.vidage_demande = False
        self._boucle_vue_ouverte = False
        # Ce qui a été dit à l'écran (pauses « plus de place »), pour l'historique et les tests.
        self.messages: list[str] = []

    # ------------------------------------------------------------ boucle

    def boucle_fermee(self) -> bool:
        """Boucle fermée ; capteur muet : comme ouverte (on attend)."""
        return self._boucle() is True

    # ------------------------------------------------------------ piles de seaux vides

    def format_bande(self) -> str:
        """Le format des piles de fin de lot (toutes du même : leurs x en dépendent)."""
        for nom, pile in self.inventaire.piles.items():
            if nom.startswith("fin_") and pile.format is not None:
                return pile.format
        assert self.machine.griffe is not None
        return self.machine.griffe.format_par_defaut

    def places_piles(self) -> dict[str, places.Point]:
        return places.places_piles(self.machine, self.format_bande())

    def seaux_par_pile(self, format: str) -> int:
        return places.seaux_par_pile(self.machine, format)

    def charger_pile(self, nom: str, format: str, nombre: int) -> None:
        """L'opérateur a posé (ou corrigé) une pile : format et nombre de seaux."""
        assert self.machine.griffe is not None
        if nom not in self.inventaire.piles:
            raise ErreurEtape(f"stockage : pas de place de pile « {nom} »", QUOI_FAIRE)
        if format not in self.machine.griffe.formats:
            raise ErreurEtape(f"stockage : format de seau inconnu « {format} »", QUOI_FAIRE)
        maximum = self.seaux_par_pile(format)
        if not 0 <= nombre <= maximum:
            raise ErreurEtape(
                f"stockage : {nombre} seaux « {format} » sur une pile, au plus {maximum}",
                QUOI_FAIRE,
            )
        if nom.startswith("fin_") and nombre > 0:
            for autre, pile in self.inventaire.piles.items():
                if autre.startswith("fin_") and autre != nom and pile.format not in (None, format):
                    raise ErreurEtape(
                        f"stockage : les piles de fin de lot sont toutes du même format (« "
                        f"{autre} » a des « {pile.format} »)",
                        QUOI_FAIRE,
                    )
            numero = int(nom.split("_")[1])
            nombre_places = len(places.places_fin_de_lot(self.machine, format))
            if numero > nombre_places:
                raise ErreurEtape(
                    f"stockage : seaux « {format} » : {nombre_places} places de fin de lot "
                    f"seulement (pas de « {nom} »)",
                    QUOI_FAIRE,
                )
        self.inventaire.changer_pile(nom, format, nombre)

    def charger_couvercles(self, nombre: int) -> None:
        if nombre < 0:
            raise ErreurEtape("stockage : nombre de couvercles négatif", QUOI_FAIRE)
        self.inventaire.changer_couvercles(nombre)

    def ordre_des_piles(self) -> list[str]:
        return places.ordre_piles(self.machine, self.places_piles())

    def pile_a_prendre(self, format: str) -> str | None:
        """La prochaine pile de ce format qui a des seaux, dans l'ordre de vidage."""
        for nom in self.ordre_des_piles():
            pile = self.inventaire.piles[nom]
            if pile.format == format and pile.nombre > 0:
                return nom
        return None

    def seaux_vides(self, format: str) -> int:
        return sum(pile.nombre for pile in self.inventaire.piles.values() if pile.format == format)

    def piles_vues(self) -> list[PileVue]:
        """Les piles qui ont des seaux (pour les verrous des trajets)."""
        assert self.machine.griffe is not None
        points = self.places_piles()
        vues = []
        for nom, pile in self.inventaire.piles.items():
            if pile.nombre <= 0 or pile.format is None or nom not in points:
                continue
            x, y = points[nom]
            vues.append(
                PileVue(
                    nom,
                    x,
                    y,
                    self.machine.griffe.formats[pile.format].rayon_haut,
                    places.bord_pile(self.machine, pile.format, pile.nombre),
                )
            )
        return vues

    def _sortie_de_la_bande(self, nom: str) -> bool:
        return nom.startswith("fin_")

    def geste_prendre_seau(self, prehension: "Prehension", format: str) -> Geste:
        """La préhension prend le seau du haut de la prochaine pile de ce format. L'inventaire
        compte le seau parti dès qu'il est levé ; d'une pile de la bande, le seau sort vers −x
        puis vers +y (caméra du bocal)."""
        nom = self.pile_a_prendre(format)
        if nom is None:
            raise ErreurEtape(
                f"stockage : plus de seau vide « {format} » sur les piles",
                "Charger une pile de seaux vides, la dire à l'écran, puis acquitter et donner "
                "le Go.",
            )
        pile = self.inventaire.piles[nom]
        x, y = self.places_piles()[nom]
        contact = places.contact_prise(self.machine, format, pile.nombre)
        journal.info(
            "Stockage : seau « %s » pris sur %s (%d seaux, bord attendu à %.3f m)",
            format,
            nom,
            pile.nombre,
            places.bord_pile(self.machine, format, pile.nombre),
        )
        self.pile_en_cours, self.format_en_cours = nom, format
        yield from prehension.geste_prendre("seau", x, y, contact, format)
        self.inventaire.changer_pile(nom, format, pile.nombre - 1)
        if self._sortie_de_la_bande(nom):
            # Le long de la bande vers −x (les piles plus proches du chariot sont déjà vides),
            # puis vers +y, loin de la caméra du bocal.
            camera = self.reglages.trajets.camera_bocal
            yield from prehension.geste_aller(camera.seau_x_min, y)
            yield from prehension.geste_aller(camera.seau_x_min, camera.seau_y_libre)

    def prise_double(self) -> None:
        """Le Remplissage a vu deux seaux emboîtés : un seau de plus est parti de la pile."""
        nom = self.pile_en_cours
        if nom is None:
            return
        pile = self.inventaire.piles[nom]
        self.inventaire.changer_pile(nom, pile.format, max(0, pile.nombre - 1))

    def geste_rendre_seau(self, prehension: "Prehension") -> Geste:
        """Le seau du dessus d'une prise double est rendu sur sa pile (emboîté sur ceux qui y
        restent)."""
        nom, format = self.pile_en_cours, self.format_en_cours
        if nom is None or format is None or prehension.objet is None:
            raise ErreurEtape(
                "stockage : on ne sait pas sur quelle pile rendre le seau", QUOI_FAIRE
            )
        pile = self.inventaire.piles[nom]
        if pile.format not in (None, format):
            raise ErreurEtape(
                f"stockage : la pile « {nom} » a maintenant des « {pile.format} »", QUOI_FAIRE
            )
        x, y = self.places_piles()[nom]
        # Le seau rendu se pose emboîté sur ceux qui restent.
        contact = places.contact_prise(self.machine, format, pile.nombre + 1)
        if self._sortie_de_la_bande(nom):
            camera = self.reglages.trajets.camera_bocal
            yield from prehension.geste_aller(camera.seau_x_min, camera.seau_y_libre)
            yield from prehension.geste_aller(camera.seau_x_min, y)
        yield from prehension.geste_poser(x, y, contact)
        self.inventaire.changer_pile(nom, format, pile.nombre + 1)

    # ------------------------------------------------------------ tiroir des seaux pleins

    def places_tiroir(self, format: str) -> dict[str, int]:
        return places.places_tiroir(self.machine, format)

    def file_libre(self, format: str) -> str | None:
        """La file où ranger le prochain seau de ce format ; None : tiroir plein."""
        for nom, nombre in self.places_tiroir(format).items():
            if self.inventaire.files[nom] < nombre:
                return nom
        return None

    def seau_range(self, file: str) -> None:
        self.inventaire.changer_file(file, self.inventaire.files[file] + 1)

    def seaux_au_tiroir(self) -> int:
        return sum(self.inventaire.files.values())

    def demander_vidage(self, raison: str, substrat_restant_kg: float | None = None) -> None:
        """Plus de place (ou fin de lot) : le cycle attend que le tiroir soit vidé."""
        reste = ""
        if substrat_restant_kg is not None:
            reste = f" ; substrat restant ≈ {substrat_restant_kg:.1f} kg"
        message = f"{raison} : vider le tiroir du stockage ({self.seaux_au_tiroir()} seaux){reste}"
        journal.warning("Stockage : %s", message)
        self.messages.append(message)
        self.vidage_demande = True
        self._boucle_vue_ouverte = False

    def tiroir_ressorti_et_remis(self) -> bool:
        """Condition d'attente : la boucle a été vue ouverte (tiroir tiré), puis refermée."""
        if not self.boucle_fermee():
            self._boucle_vue_ouverte = True
            return False
        return self._boucle_vue_ouverte

    def tiroir_vide(self) -> None:
        """Confirmé à l'écran (boucle fermée) : les files repartent vides."""
        if not self.boucle_fermee():
            raise ErreurEtape("stockage : boucle ouverte, tiroir pas confirmé", QUOI_FAIRE_BOUCLE)
        for nom in self.inventaire.files:
            self.inventaire.changer_file(nom, 0)
        self.vidage_demande = False
        self._boucle_vue_ouverte = False
        journal.info("Stockage : tiroir vidé, files remises à zéro")

    # ------------------------------------------------------------ bande du haut (case vide)

    def places_bande_haut(self, format: str) -> int:
        """Places de la bande du haut pour ce format : 0 tant qu'elle est désactivée."""
        bande = self.reglages.bande_haut
        return bande.places.get(format, 0) if bande.active else 0

    # ------------------------------------------------------------ bocaux

    def places_bocaux(self) -> dict[str, places.Point]:
        return places.places_bocaux(self.machine)

    def poser_bocal(self, place: str, contenu: str = "bocal") -> None:
        if place not in self.places_bocaux() and place not in places.places_semence(self.machine):
            raise ErreurEtape(f"stockage : pas de place de bocal « {place} »", QUOI_FAIRE)
        if place in self.inventaire.bocaux:
            raise ErreurEtape(f"stockage : la place « {place} » a déjà un bocal", QUOI_FAIRE)
        self.inventaire.changer_bocal(place, contenu)

    def enlever_bocal(self, place: str) -> None:
        self.inventaire.changer_bocal(place, None)

    def place_suspect_libre(self) -> str:
        """Mode inspection : la prochaine place du coin des « suspects ». Coin plein : arrêt et
        alerte."""
        suspects, separation = places.coin_inspection(self.machine)
        for place in separation:
            if place in self.inventaire.bocaux:
                raise ErreurEtape(
                    f"stockage : un bocal est sur la place de séparation « {place} »", QUOI_FAIRE
                )
        for place in suspects:
            if place not in self.inventaire.bocaux:
                return place
        raise ErreurEtape(
            "stockage : coin d'inspection plein (bocaux suspects)",
            "Sortir les bocaux suspects du coin d'inspection, le dire à l'écran, puis acquitter.",
        )

    def place_saine_libre(self) -> str | None:
        for place in places.places_saines(self.machine):
            if place not in self.inventaire.bocaux:
                return place
        return None

    # ------------------------------------------------------------ boîtes à capsules

    def hauteur_boite(self, boite: str) -> float:
        return places.hauteur_boite(self.machine, self.inventaire.boites[boite])

    def capsule_posee(self, boite: str) -> None:
        if boite not in self.inventaire.boites:
            raise ErreurEtape(f"stockage : pas de boîte « {boite} »", QUOI_FAIRE)
        capsules = self.inventaire.boites[boite]
        if capsules >= places.capacite_boite(self.machine):
            raise ErreurEtape(
                f"stockage : boîte « {boite} » pleine ({capsules} capsules)",
                "Changer la boîte à capsules, le dire à l'écran, puis acquitter.",
            )
        self.inventaire.changer_boite(boite, capsules + 1)

    def boite_changee(self, boite: str) -> None:
        self.inventaire.changer_boite(boite, 0)

    # ------------------------------------------------------------ verrous

    def refus_prehension(self, prehension: "Prehension") -> Callable[[Pose, Pose], str | None]:
        """Le verrou d'un pas de la préhension, de `depart` à `arrivee` (raison, ou None)."""

        def refus(depart: Pose, arrivee: Pose) -> str | None:
            return self.regles.refus_prehension(
                depart,
                arrivee,
                prehension.objet,
                self.piles_vues(),
                list(self.places_piles().values()),
                self.boucle_fermee(),
            )

        return refus

    def brancher_prehension(self, prehension: "Prehension") -> None:
        """La préhension applique les verrous du Stockage à chacun de ses pas (et en manuel)."""
        prehension.verrou_stockage = self.refus_prehension(prehension)

    def brancher_griffe(self, griffe: "Griffe") -> None:
        """La griffe : boucle fermée, axe du mât à x ≤ 2,325."""
        griffe.verrou_stockage = lambda depart, arrivee: self.regles.refus_griffe(
            depart.x, arrivee.x, self.boucle_fermee()
        )
