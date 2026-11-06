"""Le portique : pont (moteurs X1 et X2), chariot Y, Z de la griffe et Z de la préhension.

    portique = Portique(reglages.machine, reglages.fluidnc.cartes, liaisons)
    portique.etapes_origine()            # étapes du chef : freins desserrés, Z, Y, X (dans l'ordre)
    portique.etapes_garage()             # outils en haut, pont au garage, freins serrés
    portique.etapes_photo("stockage")    # outils en haut, pont au bout opposé, attente à l'arrêt
    module_portique(portique, "origine") # un module du chef fait de ces étapes (exclusif)
    portique.refus_position(pont_x=0.2)  # raison du refus, ou None
    portique.pont_gare("fut_poste", x)   # le pont est-il à sa place de photo ?

Fiche du module « Portique » (gelé le 28/10/2026) et fichier du fil Portique (01/11). Tous les
chiffres sont dans machine.yaml (partie « portique », axes et positions nommées) ; le code ne cite
que des noms.

- Le pont a deux moteurs (X1, X2) et deux fins de course côté fût : à la prise d'origine, chacun
  s'arrête sur le sien et le pont se remet d'équerre. FluidNC le fait seul (fluidnc/portique.yaml).
- L'axe chariot_y donne le y des deux mâts ; le centre du chariot est à mâts − décalage.
- Prise d'origine (portique → origine) : d'abord les contrôles (dernière rotation connue de la
  griffe à 0° ou 180°, sinon Z ne monte pas ; tour de la tête de préhension sûr), puis freins des
  Z desserrés, puis chaque groupe d'axes à son tour (« $H » et leurs lettres sur chacune de leurs
  cartes) : les deux Z en haut, Y vers la paroi, X1 et X2 ensemble vers le fût, le godet de la
  griffe ; enfin les rotations de la griffe et de la tête de préhension
  (vidange.portique.rotations).
  Les cartes 2 et 3 gardent leurs propres origines.
- Les freins des Z (à manque de courant, 24 V coupé par l'arrêt d'urgence) sont desserrés avant de
  bouger, serrés à l'arrêt long (garage de repos).
- Une alarme d'un des 5 pilotes (X1, X2, Y, Z griffe, Z préhension), lue dans « Pn: », arrête le
  module et dit lequel.

Ces verrous ne protègent que la MACHINE : la sécurité des personnes reste câblée.
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import replace

from vidange.angles_gardes import AnglesGardes
from vidange.chef import Axes, Condition, ErreurEtape, Etape, Module
from vidange.fluidnc import Commande, ErreurFluidnc, Liaison, protocole
from vidange.journal import donner_journal
from vidange.portique.rotations import OriginesRotations
from vidange.quoi_faire import ALARMES_FLUIDNC, CARTE_COUPEE
from vidange.reglages import CarteFluidnc, Machine
from vidange.reglages import Portique as ReglagesPortique

journal = donner_journal("portique")

# Les alarmes des 5 pilotes (docs/entrees-sorties.yaml, fluidnc.yaml → entrees), et ce qu'on dit.
ALARMES_PILOTES = {
    "alarme_pont_x1": "moteur X1 du pont",
    "alarme_pont_x2": "moteur X2 du pont",
    "alarme_chariot_y": "chariot Y",
    "alarme_griffe_z": "Z de la griffe",
    "alarme_prehension_z": "Z de la préhension",
}
# Les freins des deux Z (fluidnc.yaml → sorties ; commandée = desserré).
FREINS = {"frein_griffe_z": "Z de la griffe", "frein_prehension_z": "Z de la préhension"}

DELAI_ORIGINE = "portique_origine_max"
DELAI_DEPLACEMENT = "portique_deplacement_max"

QUOI_FAIRE = (
    "Regarder la vidéo du portique : un axe est-il bloqué, un outil accroché ? Corriger, puis "
    "acquitter et donner le Go : le geste est refait depuis le début."
)
QUOI_FAIRE_ORIGINE = ALARMES_FLUIDNC[9]
QUOI_FAIRE_PILOTE = (
    "Un pilote du portique est en alarme (moteur bloqué, effort trop grand ou câble) : regarder "
    "ce qui bloque l'axe, sans desserrer le frein d'un Z. Dégager, couper puis remettre le "
    "courant du pilote (son voyant d'alarme s'éteint), puis acquitter et donner le Go : la prise "
    "d'origine du portique est refaite."
)
QUOI_FAIRE_GODET = (
    "Le godet de la griffe n'a pas trouvé son capteur « fermé » (origine_godet_griffe) : il est "
    "peut-être bloqué par du substrat. Vider le godet au-dessus d'un seau, regarder le voyant du "
    "capteur et son câble (multiconducteur de la griffe), puis acquitter et donner le Go."
)
QUOI_FAIRE_FREIN = (
    "Le frein d'un Z n'a pas répondu : regarder la carte (câble USB) et le relais du frein, puis "
    "acquitter et donner le Go."
)

# machine.yaml est en mètres, FluidNC en millimètres.
_MM_PAR_M = 1000
_EGAL = 1e-6


def places_photo(machine: Machine) -> dict[str, float]:
    """Le x du pont pour photographier chaque zone du plafond (au bout opposé) ; vide sans
    partie « portique »."""
    if machine.portique is None:
        return {}
    return {
        zone: machine.positions[position]["pont_x"]
        for zone, position in machine.portique.photo.items()
    }


def _m(valeur: float) -> str:
    return f"{valeur:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def _carte_du_signal(
    cartes: Mapping[str, CarteFluidnc], nom: str, sortie: bool
) -> tuple[str, str | int] | None:
    """(carte, lettre ou numéro) du signal dans fluidnc.yaml, ou None s'il n'y est pas."""
    for carte, reglage in cartes.items():
        valeurs = reglage.sorties if sortie else reglage.entrees
        if nom in valeurs:
            return carte, valeurs[nom]
    return None


class Portique:
    def __init__(
        self,
        machine: Machine,
        cartes: Mapping[str, CarteFluidnc],
        liaisons: Mapping[str, Liaison],
        horloge: Callable[[], float] = time.monotonic,
        garde: AnglesGardes | None = None,
        compte_tours: Callable[[], float | None] | None = None,
    ) -> None:
        """`cartes` : fluidnc.yaml → cartes ; `liaisons` : une par carte (par son nom) ;
        `garde` : les angles gardés au redémarrage ; `compte_tours` : l'angle de la tête de
        préhension lu au compte-tours (vidange.portique.rotations)."""
        if machine.portique is None:
            raise ValueError("machine.yaml n'a pas de partie « portique »")
        self.machine = machine
        self.reglages: ReglagesPortique = machine.portique
        self.liaisons = dict(liaisons)
        self._horloge = horloge
        manquent = []
        self.alarmes: dict[str, tuple[str, str]] = {}
        for nom, quoi in ALARMES_PILOTES.items():
            ou = _carte_du_signal(cartes, nom, sortie=False)
            if ou is None:
                manquent.append(f"entrees → {nom}")
            else:
                self.alarmes[quoi] = (ou[0], str(ou[1]))
        self.freins: dict[str, tuple[str, int]] = {}
        for nom, quoi in FREINS.items():
            ou = _carte_du_signal(cartes, nom, sortie=True)
            if ou is None:
                manquent.append(f"sorties → {nom}")
            else:
                self.freins[quoi] = (ou[0], int(ou[1]))
        if manquent:
            raise ValueError(f"fluidnc.yaml : il manque {', '.join(manquent)} (portique)")
        # Les cartes du portique : celles de ses axes, de ses alarmes et de ses freins.
        noms = {machine.axes[nom].carte for groupe in self.reglages.origine for nom in groupe}
        noms |= {carte for carte, _ in self.alarmes.values()}
        noms |= {carte for carte, _ in self.freins.values()}
        absentes = sorted(nom for nom in noms if nom not in self.liaisons)
        if absentes:
            raise ValueError(f"portique : pas de liaison pour la carte {', '.join(absentes)}")
        # Les noms des cartes du portique (n° 1 et n° 4).
        self.cartes: list[str] = sorted(nom for nom in noms if nom is not None)
        self.axes = Axes(machine, {nom: self.liaisons[nom] for nom in self.cartes})
        self.rotations = OriginesRotations(
            machine, cartes, self.liaisons, self.axes, garde, compte_tours
        )
        self._quoi_faire_origine = QUOI_FAIRE_ORIGINE
        self._commandes: list[tuple[str, Commande]] = []
        self._arret_depuis: float | None = None
        self.freins_desserres = False
        self.pas_d_alarme = Condition(
            "aucun pilote du portique en alarme", self._verifier_pilotes, QUOI_FAIRE_PILOTE
        )
        self.surveillance = Condition(
            "cartes du portique sans alarme, aucun pilote en alarme", self._surveiller
        )
        cartes_freins = sorted({carte for carte, _ in self.freins.values()})
        self.connectees = Condition(
            f"cartes {', '.join(f'« {nom} »' for nom in cartes_freins)} connectées",
            lambda: all(self.liaisons[nom].etat.connectee for nom in cartes_freins),
        )

    # ------------------------------------------------------------ chariot, courses, places

    def centre_chariot(self, mats_y: float) -> float:
        """Le y du centre du chariot quand les mâts sont à mats_y."""
        return mats_y - self.reglages.chariot.mats_moins_centre_y

    def mats_y(self, centre_y: float) -> float:
        """Le y des deux mâts quand le centre du chariot est à centre_y."""
        return centre_y + self.reglages.chariot.mats_moins_centre_y

    def refus_position(
        self,
        pont_x: float | None = None,
        mats_y: float | None = None,
        griffe_z: float | None = None,
        prehension_z: float | None = None,
    ) -> str | None:
        """Raison du refus (hors de la course d'un axe du portique), ou None."""
        for nom, valeur, quoi in (
            ("pont_x", pont_x, "pont en x"),
            ("chariot_y", mats_y, "mâts en y"),
            ("griffe_z", griffe_z, "Z de la griffe"),
            ("prehension_z", prehension_z, "Z de la préhension"),
        ):
            if valeur is None:
                continue
            debut, fin = self.machine.axes[nom].course
            if not debut - _EGAL <= valeur <= fin + _EGAL:
                return f"{quoi} à {_m(valeur)} m, hors de la course ({_m(debut)} à {_m(fin)} m)"
        if mats_y is not None and prehension_z is not None:
            # La chaîne Z de la préhension (portique → chaine_prehension).
            return self.reglages.refus_chaine(
                mats_y, prehension_z, self.machine.axes["prehension_z"].course[0]
            )
        return None

    def place_photo(self, zone: str) -> float:
        """Le x du pont pour photographier cette zone (au bout opposé)."""
        places = places_photo(self.machine)
        if zone not in places:
            raise KeyError(f"portique : pas de place de photo pour « {zone} »")
        return places[zone]

    def pont_gare(self, zone: str, pont_x: float | None) -> bool:
        """Le pont est-il à la place de photo de cette zone (à photo_tolerance_m près) ?"""
        if pont_x is None:
            return False
        return abs(pont_x - self.place_photo(zone)) <= self.reglages.photo_tolerance_m + _EGAL

    def acceleration_xy_mm_s2(self, seau_tenu: bool) -> float:
        """L'accélération des axes X et Y (mm/s²) : réduite quand un seau est tenu."""
        v = self.reglages.vitesses
        valeur = v.xy_acceleration_seau_m_s2 if seau_tenu else v.xy_acceleration_vide_m_s2
        return valeur * _MM_PAR_M

    def position_pont(self) -> float | None:
        """Le x du pont (m), lu sur sa carte ; None si inconnu."""
        axe = self.machine.axes["pont_x"]
        assert axe.carte is not None and axe.lettre is not None
        mm = self.liaisons[axe.carte].etat.positions.get(axe.lettre)
        return None if mm is None else mm / _MM_PAR_M

    # ------------------------------------------------------------ alarmes des pilotes

    def pilotes_en_alarme(self) -> list[str]:
        """Les pilotes en alarme (lus dans « Pn: » de leur carte)."""
        en_alarme = []
        for quoi, (carte, lettre) in self.alarmes.items():
            etat = self.liaisons[carte].etat
            if etat.connectee and etat.etat is not None and lettre in etat.entrees_actives:
                en_alarme.append(quoi)
        return en_alarme

    def _verifier_pilotes(self) -> bool:
        en_alarme = self.pilotes_en_alarme()
        if en_alarme:
            journal.error("Portique : pilote en alarme : %s", ", ".join(en_alarme))
            self.arreter()
            raise ErreurEtape(
                f"portique : alarme du pilote : {', '.join(en_alarme)}", QUOI_FAIRE_PILOTE
            )
        return True

    def _surveiller(self) -> bool:
        return self.axes.surveillance.test() and self._verifier_pilotes()

    # ------------------------------------------------------------ freins

    def _freins(self, desserrer: bool) -> None:
        debloquees: set[str] = set()
        for quoi, (carte, numero) in self.freins.items():
            liaison = self.liaisons[carte]
            ligne = f"M{64 if desserrer else 65} P{numero}"
            try:
                if desserrer and liaison.etat.en_alarme and carte not in debloquees:
                    # À la mise sous tension, la carte attend sa prise d'origine (alarme) : elle
                    # refuserait la sortie. Débloquée ici, elle fait sa prise d'origine juste après.
                    liaison.debloquer()
                    debloquees.add(carte)
                commande = liaison.envoyer(ligne)
            except ErreurFluidnc as erreur:
                raise ErreurEtape(f"frein du {quoi} : {erreur}", QUOI_FAIRE_FREIN) from erreur
            if commande.finie and commande.erreur is not None:
                raise ErreurEtape(f"frein du {quoi} : {commande.erreur}", QUOI_FAIRE_FREIN)
        self.freins_desserres = desserrer
        journal.info("Portique : freins des Z %s", "desserrés" if desserrer else "serrés")

    def desserrer_freins(self) -> None:
        self._freins(True)

    def serrer_freins(self) -> None:
        self._freins(False)

    # ------------------------------------------------------------ prise d'origine

    def lancer_origine(self, numero: int) -> None:
        """Prise d'origine du groupe n° `numero` (à partir de 0) de portique → origine : « $H »
        et les lettres de ses axes, sur chacune de leurs cartes, en même temps."""
        lettres: dict[str, str] = {}
        groupe = self.reglages.origine[numero]
        # Le godet de la griffe : s'il ne trouve pas son capteur, il est sans doute bloqué.
        self._quoi_faire_origine = QUOI_FAIRE_GODET if "griffe_b" in groupe else QUOI_FAIRE_ORIGINE
        for nom in groupe:
            axe = self.machine.axes[nom]
            assert axe.carte is not None and axe.lettre is not None
            lettres[axe.carte] = lettres.get(axe.carte, "") + axe.lettre
        self._commandes = []
        for carte, texte in lettres.items():
            ligne = protocole.PRISE_ORIGINE + texte
            journal.info("Portique : prise d'origine « %s » sur la carte « %s »", ligne, carte)
            self._commandes.append((carte, self.liaisons[carte].envoyer(ligne)))
        self.origine_finie()

    def origine_finie(self) -> bool:
        """Vrai quand la prise d'origine lancée est finie sur toutes ses cartes."""
        for carte, commande in self._commandes:
            if commande.erreur is not None:
                connectee = self.liaisons[carte].etat.connectee
                raise ErreurEtape(
                    f"prise d'origine du portique, carte « {carte} », « {commande.ligne} » : "
                    f"{commande.erreur}",
                    self._quoi_faire_origine if connectee else CARTE_COUPEE,
                )
        return all(commande.finie for _, commande in self._commandes)

    # ------------------------------------------------------------ étapes

    def _aller(self, nom: str, position: str) -> Etape:
        return Etape(
            nom,
            QUOI_FAIRE,
            action=lambda: self.axes.aller(position),
            fin=self.axes.arrives,
            delai_max=DELAI_DEPLACEMENT,
            entree=(self.axes.pretes,),
        )

    def _attendre_arret(self) -> bool:
        """Vrai après photo_apres_arret_s à l'arrêt (photo sans flou)."""
        if self._arret_depuis is None:
            self._arret_depuis = self._horloge()
        attente = self.reglages.vitesses.photo_apres_arret_s
        return self._horloge() - self._arret_depuis >= attente - _EGAL

    def etapes_origine(self) -> tuple[Etape, ...]:
        """Contrôles des rotations, freins desserrés, chaque groupe de portique → origine dans
        l'ordre, puis les rotations de la griffe et de la tête de préhension."""
        etapes = [
            *self.rotations.etapes_controle(),
            Etape(
                "portique_freins_desserres",
                QUOI_FAIRE_FREIN,
                action=self.desserrer_freins,
                entree=(self.connectees,),
            ),
        ]
        fin = Condition("prise d'origine du portique finie", self.origine_finie)
        for numero, groupe in enumerate(self.reglages.origine):
            etapes.append(
                Etape(
                    f"portique_origine_{'_'.join(groupe)}",
                    QUOI_FAIRE_GODET if "griffe_b" in groupe else QUOI_FAIRE_ORIGINE,
                    action=lambda numero=numero: self.lancer_origine(numero),
                    fin=fin,
                    delai_max=DELAI_ORIGINE,
                    entree=(self.pas_d_alarme,),
                )
            )
        etapes += self.rotations.etapes_griffe()
        etapes += self.rotations.etapes_tete()
        return tuple(etapes)

    def etapes_garage(self) -> tuple[Etape, ...]:
        """Garage de repos : outils en haut, pont et chariot au garage, freins serrés."""
        return (
            self._aller("portique_outils_en_haut", self.reglages.outils_en_haut),
            self._aller("portique_au_garage", self.reglages.garage),
            Etape("portique_freins_serres", QUOI_FAIRE_FREIN, action=self.serrer_freins),
        )

    def etapes_photo(self, zone: str) -> tuple[Etape, ...]:
        """Photo du plafond de cette zone : outils en haut, pont au bout opposé, attente à
        l'arrêt (photo_apres_arret_s)."""
        position = self.reglages.photo.get(zone)
        if position is None:
            raise KeyError(f"portique : pas de place de photo pour « {zone} »")

        def arreter_chrono() -> None:
            self._arret_depuis = None

        return (
            self._aller("portique_outils_en_haut", self.reglages.outils_en_haut),
            self._aller(f"portique_photo_{zone}", position),
            Etape(
                "portique_arret_avant_photo",
                QUOI_FAIRE,
                action=arreter_chrono,
                fin=Condition("portique à l'arrêt avant la photo", self._attendre_arret),
                delai_max=DELAI_DEPLACEMENT,
            ),
        )

    # ------------------------------------------------------------ pause, arrêt

    def pauser(self) -> None:
        self.axes.pauser()

    def reprendre(self) -> None:
        self.axes.reprendre()

    def arreter(self) -> None:
        """Les axes du portique s'arrêtent (« ! » de FluidNC), sans rien oublier."""
        self.axes.pauser()


def module_portique(portique: Portique, geste: str, nom: str | None = None) -> Module:
    """Un module du chef pour un geste du portique : « origine », « garage », ou « photo_<zone> ».
    Exclusif : les autres modules attendent ; il attend le Go de Karulium."""
    if geste == "origine":
        etapes = portique.etapes_origine()
    elif geste == "garage":
        etapes = portique.etapes_garage()
    elif geste.startswith("photo_"):
        etapes = portique.etapes_photo(geste.removeprefix("photo_"))
    else:
        raise ValueError(f"portique : geste inconnu « {geste} »")
    etapes = (replace(etapes[0], demande_go=True), *etapes[1:])
    # Avant sa prise d'origine, une carte est en alarme (mise sous tension) : seuls les pilotes
    # sont surveillés ; ensuite, les cartes aussi.
    surveillance = portique.pas_d_alarme if geste == "origine" else portique.surveillance
    return Module(
        nom=nom or f"portique_{geste}",
        etapes=etapes,
        surveillances=(surveillance,),
        pauser=portique.pauser,
        reprendre=portique.reprendre,
        arreter=portique.arreter,
        exclusif=True,
    )
