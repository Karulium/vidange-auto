"""Les pièces du programme principal sur la machine (tâches 45, 45 bis, 45 ter et 45 sexies).

    cartes = construire_cartes(reglages, materiel, liaisons, pesees, poste, vraie_machine, ...)
    pieces = PiecesMachine(poste, materiel, vraie_machine, ..., cartes=cartes)
    pieces.manque("micropore")    # None, ou pourquoi le poste n'est pas lancé

Les cartes du chariot et de la tête (tâche 45 ter) sont construites une fois, au démarrage, depuis
docs/entrees-sorties.yaml et les réglages, comme le font les outils d'essai (vidange-remplissage,
vidange-prehension, vidange-micropore, vidange-lavage) :
- « chariot » : la carte FluidNC du chariot (ChariotFluidnc) et sa balance, la carte de pesée
  RP2040-Zero du plateau (bus rs485_pesee) ;
- « boitier » : la PCA9685 (servos) et le ToF VL6180X du boîtier du chariot, sur l'I2C de cette
  même carte ; « tete_micropore » (servos d'escamotage et de lame, ToF) et « bras_fermeture »
  (servo du bras) dessus ;
- « avance_micropore » : le moteur d'avance du ruban (carte FluidNC de machine.yaml → micropore →
  avance) ;
- « tete » : la tête de la Préhension (cartes FluidNC du portique et de la tête, palier pesé, vide
  du venturi) et la Préhension ;
- « lavage » : le Lavage (eau du fût, sur les cartes FluidNC de fluidnc.yaml) sur cette tête ;
- « agitateur » et « porte_bocal » (tâche 19 quater) : l'agitateur du Mycélium (carte FluidNC
  « mycelium_lavage » et balance du plateau) et son porte-bocal (mors, demi-tour), que la Préhension
  voit aussi (zone du porte-bocal, manivelle en bas) ;
- « spray » : la carte ESP32 n° 5 du spray (bus rs485_spray), qui répond ;
- « griffe » (tâche 45 sexies) : le bras de la griffe (5 axes de la carte FluidNC du portique,
  BrasFluidnc) et sa pesée (carte RP2040-Zero « pesee_griffe », bus rs485_pesee), sous la
  surveillance du poste du fût ; elle lit aussi la porte du coffret du spray (règle 3).
Une pièce absente (signal pas dans la liste, ligne `exemple: true` ou réglage d'EXEMPLE sur la vraie
machine, numéro de série introuvable, carte qui ne répond pas) n'arrête jamais le démarrage : elle
n'est pas construite, et les postes qui en ont besoin sont « pas lancés : raison » (check-list,
écran, journal). La présence est regardée une fois, au démarrage : une carte branchée après
demande de relancer le programme. Rien n'est commandé au démarrage (aucun ordre aux servos ni aux
sorties) : les boucles en fond de ces pièces partent avec le lot (FondDuLot). Seule exception
écrite (tâche 45 decies) : la FERMETURE des vannes de la ventouse, faite par
vidange.fiabilite.objet_tenu.VannesAuDemarrage avant la lecture du vide.

Les lots (tâche 45 quater) : `remplissage`, `entonnoir` et `lavage_bocaux` assemblent les modules
sur ces cartes, comme vidange.cycle.simulation le fait sur les pièces imaginaires (Remplissage,
Mycélium et son bocal neuf, Micropore, Fermeture, Couvercle, Spray, Stockage ; Entonnoir ; lave-
bocal). `FondDuLot` lance leurs boucles en fond avec le lot et les arrête à sa fin ou sur alarme.

La griffe (tâche 45 sexies) est assemblée avec chaque lot : dans un lot de seaux,
vidange.cycle.griffe_du_lot.GriffeDuSeau l'enchaîne au Remplissage, au Mycélium et à la Préhension
(même pont) ; dans un lot de bocaux, vidange.griffe.versement.Versement (tâche 43 bis) verse dans le
bocal où est l'entonnoir. `Sources.griffe` et `Sources.versement_bocal` restent pour les essais (un
faux à la place de la vraie griffe).

Ce qui manque encore pour qu'un lot parte sur la machine, sans rien inventer (`Sources` : None sur
la machine, un faux dans les essais ; le poste dit « pas lancé : raison ») :
- griffe : ses réglages sont encore en EXEMPLE (machine.yaml → griffe, versement_bocal) ;
- mycélium : le geste du bocal neuf de semence est écrit (vidange.bocal_neuf, tâche 19 quater),
  mais il lui manque deux sources que la machine n'a pas encore : la lecture du QR du bocal par la
  caméra de la tête de la griffe, et l'erreur du codeur de la rotation de la tête (calage du
  moteur) ;
- QR du flanc et micropore : la vision (vidange.vision.inspection, tâche 40 ter) attend ses
  réglages vrais (vision.yaml → inspection) et la caméra ;
- stockage : il faut le signal de la boucle du tiroir et des panneaux, et (vraie machine) la
  lecture de la photo du plafond de la bande du haut ;
- entonnoir : la lecture de la photo du plafond (l'entonnoir est-il sur le bocal ? où est le
  centre du col ?) n'est pas écrite ;
- lavage des bocaux : la liste des bocaux sales vient de la caméra du plafond (règle 7), pas
  écrite ;
- nuit UV-ozone : tout est là (le Nettoyage tourne déjà) ; elle ne manque que si le Nettoyage n'est
  pas construit ou si un signal de la nuit manque dans la liste des entrées/sorties.
"""

import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from vidange.angles_gardes import AnglesGardes
from vidange.bocal_neuf.bocal_neuf import BocalNeuf
from vidange.chef import Chef, ErreurChef, ErreurEtape
from vidange.chef.chef import ATTENTE_GO
from vidange.couvercle.couvercle import Couvercle
from vidange.cycle.griffe_du_lot import GriffeDuSeau, brancher_pont
from vidange.cycle.mode_bocaux import LotBocaux, PiecesEntonnoir, PiecesLavageBocaux
from vidange.cycle.mode_seaux import Lot, PiecesRemplissage
from vidange.entonnoir.entonnoir import Entonnoir, VisionEntonnoir
from vidange.entonnoir.etat import NOM_FICHIER as NOM_ENTONNOIR
from vidange.entrees_sorties import EntreesSorties
from vidange.fermeture.bras import BrasFermeture
from vidange.fermeture.fermeture import Fermeture
from vidange.fiabilite.constats import Constat, lancer_boucle
from vidange.fluidnc import Liaison
from vidange.fluidnc.ports import CarteIntrouvable, lister_ports_usb, trouver_port
from vidange.griffe.bras import BrasFluidnc
from vidange.griffe.griffe import Griffe
from vidange.griffe.versement import NOM_FICHIER as NOM_VERSEMENT
from vidange.griffe.versement import Versement
from vidange.journal import donner_journal
from vidange.lavage.bocaux import LavageBocaux
from vidange.lavage.eau import NOM_EAU, EauLavage
from vidange.lavage.lavage import Lavage
from vidange.lavage.signaux import signaux_lavage
from vidange.materiel import Materiel
from vidange.micropore.appris import NOM_APPRIS, FichierAppris
from vidange.micropore.avance import AvanceFluidnc
from vidange.micropore.micropore import NOM_ETAT as NOM_ETAT_MICROPORE
from vidange.micropore.micropore import Micropore
from vidange.micropore.tete import TeteMicropore
from vidange.mycelium.agitateur import AgitateurFluidnc
from vidange.mycelium.mycelium import Mycelium
from vidange.mycelium.regles import ReglesMycelium
from vidange.nettoyage.nettoyage import (
    GENERATEUR,
    LAMPE_UV,
    OZONE_DEDANS,
    OZONE_DEHORS,
    Nettoyage,
)
from vidange.pesees.tour import CapteurPesee, TourPesees
from vidange.porte_bocal.porte_bocal import (
    ENTREES as ENTREES_PORTE_BOCAL,
)
from vidange.porte_bocal.porte_bocal import (
    SORTIES as SORTIES_PORTE_BOCAL,
)
from vidange.porte_bocal.porte_bocal import PorteBocalFluidnc, signaux_porte_bocal
from vidange.poste_fut import PosteFut
from vidange.prehension.prehension import Prehension
from vidange.prehension.tete import (
    AIMANTS,
    CONTACT,
    VANNE,
    CapteurVide,
    TeteFluidnc,
    signaux_prehension,
)
from vidange.reglages import (
    ENTREES_LAVAGE,
    RELAIS_CHAUFFAGE_LAVAGE,
    SORTIES_LAVAGE,
    Fluidnc,
    Machine,
    ObjetLaveBocalSimule,
    Reglages,
    ReglagesLot,
    ReglagesVision,
)
from vidange.remplissage.chariot import ALARMES_BARRES, BARRIERE, ChariotFluidnc, signaux_chariot
from vidange.remplissage.module import Plan
from vidange.remplissage.remplissage import Remplissage
from vidange.spray.spray import PORTE as PORTE_SPRAY
from vidange.spray.spray import Spray
from vidange.spray.zone import ZoneDuBras
from vidange.stockage.simulation import BOUCLE
from vidange.stockage.stockage import Stockage, VisionBande
from vidange.vision.inspection import NOM_ECARTS, EcartsAttaches, Regard, VisionInspection

journal = donner_journal("cycle.machine")

VISION_ABSENTE = "vision.yaml pas donné aux pièces : la caméra du micropore ne peut pas lire"
INSPECTION_ABSENTE = "vision.yaml n'a pas de partie « inspection » (caméra du micropore)"
INSPECTION_EXEMPLE = (
    "valeurs d'EXEMPLE dans vision.yaml (inspection) : interdit sur la vraie machine"
)
CAMERA_ABSENTE = "caméra du micropore pas ouverte (photographe absent)"
CARTES_PAS_CONSTRUITES = (
    "cartes du chariot et de la tête pas construites (entrées/sorties pas ouvertes au démarrage)"
)
CARTE_SPRAY = "carte du spray pas ouverte (signal absent de docs/entrees-sorties.yaml ?)"
BOCAL_NEUF = (
    "bocal de semence neuf (vidange.bocal_neuf) : il manque la lecture du QR du bocal par la "
    "caméra de la tête de la griffe et l'erreur du codeur de la rotation de la tête (calage du "
    "moteur), pas encore branchées"
)
QR_DU_BOCAL = (
    "bocal de semence neuf (vidange.bocal_neuf) : lecture du QR du bocal par la caméra de la tête "
    "de la griffe pas encore branchée"
)
CODEUR = (
    "bocal de semence neuf (vidange.bocal_neuf) : erreur du codeur de la rotation de la tête "
    "(calage du moteur) pas encore lue"
)
GRIFFE_DU_LOT = (
    "griffe pas construite au démarrage (bras sur la carte du portique, pesée de la griffe) : "
    "pas de lot de seaux"
)
VERSEMENT_BOCAL = (
    "versement de la griffe dans le bocal : griffe pas construite au démarrage (bras sur la carte "
    "du portique, pesée de la griffe)"
)
VERSEMENT_ABSENT = "machine.yaml n'a pas de partie « griffe → versement_bocal »"
PHOTO_DU_PLAFOND = (
    "lecture de la photo du plafond (entonnoir sur le bocal, centre du col) pas écrite"
)
PHOTO_DE_LA_BANDE = (
    "lecture de la photo du plafond (seaux pleins de la bande du haut) pas écrite : le Stockage "
    "ne vérifierait pas la bande"
)
BOCAUX_SALES = "liste des bocaux sales (caméra du plafond, règle 7) pas écrite"
NETTOYAGE_ABSENT = "Nettoyage pas lancé (partie « nettoyage » de machine.yaml ou entrées/sorties)"
SIGNAUX_DE_LA_NUIT = (OZONE_DEDANS, OZONE_DEHORS, GENERATEUR, LAMPE_UV)

# Les cartes et signaux (fluidnc.yaml, docs/entrees-sorties.yaml) : par leur nom, jamais par leur
# broche.
CARTE_CHARIOT = "chariot"
CARTE_PONT = "portique"
CARTE_TETE = "prehension"
PESEE_PLATEAU = "pesee_plateau_remplissage"
PESEE_TETE = "pesee_prehension"
PESEE_GRIFFE = "pesee_griffe"
CARTE_MYCELIUM = "mycelium_lavage"
VIDE = "vide_venturi"

# Les pièces de chaque poste, dans l'ordre où leur absence est dite.
PIECES_DES_POSTES: dict[str, tuple[str, ...]] = {
    "seau_vide": ("chariot", "tete"),
    "qr_du_flanc": ("chariot",),
    "micropore": ("chariot", "tete_micropore", "avance_micropore"),
    "couvercle": ("chariot", "tete"),
    "fermeture": ("chariot", "bras_fermeture"),
    "spray": ("spray",),
    "mycelium": ("tete", "agitateur", "porte_bocal"),
    # Même pont que la préhension : la griffe ne part pas sans la tête (règles de l'autre).
    "griffe": ("griffe", "tete", "chariot"),
    "versement": ("griffe", "tete"),
    "entonnoir": ("tete",),
    "lavage_bocaux": ("tete", "lavage"),
}
# Ce que chaque pièce est, en clair (check-list).
NOMS_DES_PIECES = {
    "chariot": "chariot (carte FluidNC et balance du plateau)",
    "boitier": "boîtier du chariot (PCA9685, ToF)",
    "tete_micropore": "tête du micropore (servos, ToF)",
    "bras_fermeture": "bras de la fermeture (servo)",
    "avance_micropore": "moteur d'avance du ruban du micropore",
    "agitateur": "agitateur du Mycélium (carte FluidNC, balance du plateau)",
    "porte_bocal": "porte-bocal du Mycélium (mors, demi-tour)",
    "tete": "tête de la Préhension",
    "lavage": "Lavage (eau du fût, brosses)",
    "spray": "carte du spray",
    "griffe": "griffe (bras sur la carte du portique, pesée de la griffe)",
}
SUJET = "cartes du chariot et de la tête"
QUOI_FAIRE_CARTE = (
    "Brancher la carte et vérifier sa ligne dans docs/entrees-sorties.yaml et les réglages (plus "
    "d'EXEMPLE), puis relancer le programme (la présence est regardée au démarrage)."
)


class Absente(Exception):
    """Une pièce n'est pas construite, et pourquoi (en clair)."""


@dataclass
class CartesMachine:
    """Les vraies pièces du chariot et de la tête, construites au démarrage (construire_cartes).
    `absentes` : nom de la pièce → pourquoi elle n'est pas construite."""

    chariot: ChariotFluidnc | None = None
    tete_micropore: TeteMicropore | None = None
    bras_fermeture: BrasFermeture | None = None
    avance_micropore: AvanceFluidnc | None = None
    agitateur: AgitateurFluidnc | None = None
    porte_bocal: PorteBocalFluidnc | None = None
    tete: TeteFluidnc | None = None
    prehension: Prehension | None = None
    lavage: Lavage | None = None
    bras_griffe: BrasFluidnc | None = None
    absentes: dict[str, str] = field(default_factory=dict)
    # Pour la griffe des lots : le mode de la machine et les angles gardés (rotation de sa tête).
    mode: Callable[[], str] = lambda: "production"
    garde: AnglesGardes | None = None

    def manque(self, *pieces: str) -> str | None:
        """Pourquoi la première de ces pièces qui manque n'est pas là ; None : toutes là."""
        for piece in pieces:
            if piece in self.absentes:
                return self.absentes[piece]
        return None

    def constats(self) -> list[Constat]:
        """Pour la check-list : chaque pièce, là ou pas (jamais bloquant : le mode seaux dit déjà
        si un lot peut partir)."""
        constats = []
        for piece, nom in NOMS_DES_PIECES.items():
            raison = self.absentes.get(piece)
            if raison is None:
                constats.append(Constat(f"{SUJET}, {nom}", "ok", "construite"))
            else:
                constats.append(Constat(f"{SUJET}, {nom}", "attention", raison, QUOI_FAIRE_CARTE))
        return constats


def presence_fluidnc(
    fluidnc: Fluidnc,
    ports: Mapping[str, object] | None = None,
    lister: Callable[[], Iterable[Any]] = lister_ports_usb,
) -> Callable[[str], str | None]:
    """Pourquoi une carte FluidNC n'est pas là au démarrage (None : là). `ports` : les ports des
    essais (Raccords.ports) ; une carte qui n'y est pas est cherchée par son numéro de série USB,
    comme sur la vraie machine."""

    def presence(nom: str) -> str | None:
        if ports is not None and nom in ports:
            return None
        try:
            trouver_port(fluidnc.cartes[nom].numero_serie_usb, lister)
        except CarteIntrouvable as erreur:
            return f"carte FluidNC « {nom} » : {erreur}"
        return None

    return presence


class _Construction:
    """Les vérifications communes à toutes les pièces (une Absente dit laquelle manque)."""

    def __init__(
        self,
        reglages: Reglages,
        liste: EntreesSorties,
        materiel: Materiel,
        liaisons: Mapping[str, Liaison],
        pesees: TourPesees | None,
        vraie_machine: bool,
        presence: Callable[[str], str | None],
    ) -> None:
        self.reglages = reglages
        self.liste = liste
        self.materiel = materiel
        self.liaisons = liaisons
        self.pesees = pesees
        self.vraie_machine = vraie_machine
        self.presence = presence

    def signaux(self, *noms: str) -> None:
        """Chaque signal est dans la liste ; sur la vraie machine, ni lui ni sa carte en EXEMPLE."""
        for nom in noms:
            signal = self.liste.signaux.get(nom)
            if signal is None:
                raise Absente(f"signal « {nom} » absent de docs/entrees-sorties.yaml")
            if not self.vraie_machine:
                continue
            for ligne in (nom, signal.carte):
                exemple = self.liste.signaux.get(ligne) or self.liste.cartes.get(ligne)
                if exemple is not None and exemple.exemple:
                    raise Absente(
                        f"ligne « {ligne} » de docs/entrees-sorties.yaml en EXEMPLE "
                        "(exemple: true) : interdit sur la vraie machine"
                    )

    def carte_fluidnc(self, nom: str) -> Liaison:
        if nom not in self.reglages.fluidnc.cartes or nom not in self.liaisons:
            raise Absente(f"carte FluidNC « {nom} » absente de fluidnc.yaml")
        if self.vraie_machine and self.reglages.fluidnc.exemple:
            raise Absente(
                f"fluidnc.yaml : numéros de série d'EXEMPLE (carte « {nom} ») : interdit sur la "
                "vraie machine"
            )
        raison = self.presence(nom)
        if raison is not None:
            raise Absente(raison)
        return self.liaisons[nom]

    def pesees_vraies(self) -> None:
        if self.vraie_machine and self.reglages.pesees.exemple:
            raise Absente(
                "pesees.yaml en EXEMPLE (broches, étalonnage) : interdit sur la vraie machine"
            )

    def carte_pesee(self, nom: str) -> None:
        """La carte de pesée répond sur son bus (même chemin que le reste du programme)."""
        self.pesees_vraies()
        try:
            mesure = self.materiel.lire_carte_pesee(nom)
        except Exception as erreur:
            raise Absente(f"carte de pesée « {nom} » : {erreur}") from None
        if mesure.hx711_muet:
            raise Absente(f"carte de pesée « {nom} » : HX711 muet (débranché ?)")
        if self.vraie_machine and mesure.exemple:
            raise Absente(f"carte de pesée « {nom} » : programme fait avec des réglages d'EXEMPLE")

    def balance(self, nom: str) -> CapteurPesee:
        if self.pesees is None or nom not in self.reglages.pesees.tour:
            raise Absente(f"pesée « {nom} » pas interrogée (bus des pesées, pesees.yaml → tour)")
        self.carte_pesee(nom)
        return self.pesees.capteur(nom)


def construire_cartes(
    reglages: Reglages,
    materiel: Materiel | None,
    liaisons: Mapping[str, Liaison],
    pesees: TourPesees | None,
    poste: PosteFut | None,
    vraie_machine: bool,
    presence: Callable[[str], str | None],
    mode: Callable[[], str],
    donnees: Path | None = None,
    garde: AnglesGardes | None = None,
    erreur_codeur: Callable[[], float | None] | None = None,
) -> CartesMachine:
    """Construit les pièces du chariot et de la tête qui sont là ; jamais d'exception (une pièce
    absente est notée avec sa raison, dans le journal aussi). `presence` : presence_fluidnc ;
    `mode` : ModeMachine.actuel (Lavage) ; `garde` : les angles gardés (rotation de la tête) ;
    `erreur_codeur` : l'erreur du codeur de la rotation de la tête (°), pour le calage du moteur
    (None : pas encore lue sur la machine ; un faux dans les essais)."""
    cartes = CartesMachine(mode=mode, garde=garde)
    if materiel is None:
        for piece in NOMS_DES_PIECES:
            cartes.absentes[piece] = CARTES_PAS_CONSTRUITES
        return cartes
    faire = _Construction(
        reglages, materiel.liste, materiel, liaisons, pesees, vraie_machine, presence
    )
    machine = reglages.machine

    def essayer(piece: str, construire: Callable[[], object]) -> None:
        try:
            construire()
        except Absente as absente:
            cartes.absentes[piece] = str(absente)
        except Exception as erreur:
            cartes.absentes[piece] = f"pas construite : {erreur}"
        if piece in cartes.absentes:
            journal.warning("Pièce « %s » absente : %s", piece, cartes.absentes[piece])

    def avant(*pieces: str) -> None:
        raison = cartes.manque(*pieces)
        if raison is not None:
            raise Absente(raison)

    def chariot() -> None:
        if machine.remplissage is None:
            raise Absente("machine.yaml n'a pas de partie « remplissage »")
        faire.signaux(PESEE_PLATEAU, BARRIERE, *ALARMES_BARRES.values())
        liaison = faire.carte_fluidnc(CARTE_CHARIOT)
        balance = faire.balance(PESEE_PLATEAU)
        signaux = signaux_chariot(liaison, reglages.fluidnc.cartes[CARTE_CHARIOT])
        cartes.chariot = ChariotFluidnc(machine, liaison, balance, signaux)

    def boitier() -> None:
        i2c = reglages.pesees.i2c
        if i2c is None:
            raise Absente("pesees.yaml n'a pas de partie « i2c » (boîtier du chariot)")
        faire.signaux(i2c.carte, *i2c.pca9685.voies, i2c.vl6180x.signal)
        faire.carte_pesee(i2c.carte)
        try:
            etat = materiel.lire_boitier_chariot(i2c.carte, len(i2c.pca9685.voies))
        except Exception as erreur:
            raise Absente(f"boîtier du chariot (carte « {i2c.carte} ») : {erreur}") from None
        if etat.pca9685_muette:
            raise Absente(f"boîtier du chariot (carte « {i2c.carte} ») : PCA9685 muette")
        if etat.tof_muet:
            raise Absente(f"boîtier du chariot (carte « {i2c.carte} ») : ToF muet")

    def tete_micropore() -> None:
        avant("boitier")
        if machine.micropore is None:
            raise Absente("machine.yaml n'a pas de partie « micropore »")
        i2c = reglages.pesees.i2c
        assert i2c is not None
        appris = FichierAppris(None if donnees is None else donnees / NOM_APPRIS)
        cartes.tete_micropore = TeteMicropore(machine.micropore, i2c, materiel, appris)

    def bras_fermeture() -> None:
        avant("boitier")
        if machine.fermeture is None:
            raise Absente("machine.yaml n'a pas de partie « fermeture »")
        i2c = reglages.pesees.i2c
        assert i2c is not None
        cartes.bras_fermeture = BrasFermeture(machine.fermeture, i2c, materiel)

    def avance_micropore() -> None:
        if machine.micropore is None:
            raise Absente("machine.yaml n'a pas de partie « micropore »")
        avance = machine.micropore.avance
        faire.signaux(avance.signal)
        cartes.avance_micropore = AvanceFluidnc(faire.carte_fluidnc(avance.carte), avance)

    def agitateur() -> None:
        if machine.mycelium is None:
            raise Absente("machine.yaml n'a pas de partie « mycelium »")
        liaison = faire.carte_fluidnc(CARTE_MYCELIUM)
        balance = faire.balance(PESEE_PLATEAU)
        cartes.agitateur = AgitateurFluidnc(
            machine, liaison, balance, reglages.fluidnc.cartes[CARTE_MYCELIUM]
        )

    def porte_bocal() -> None:
        if machine.porte_bocal is None:
            raise Absente("machine.yaml n'a pas de partie « porte_bocal »")
        faire.signaux(*ENTREES_PORTE_BOCAL, *SORTIES_PORTE_BOCAL)
        liaison = faire.carte_fluidnc(CARTE_MYCELIUM)
        signaux = signaux_porte_bocal(liaison, reglages.fluidnc.cartes[CARTE_MYCELIUM])
        cartes.porte_bocal = PorteBocalFluidnc(machine, liaison, signaux)

    def manivelle() -> str | None:
        """Ce que voit la tête de la manivelle : « haut », « bas » ou None (inconnue)."""
        if cartes.agitateur is None or machine.mycelium is None:
            return None
        regles = ReglesMycelium(machine)
        try:
            pose = cartes.agitateur.position()
        except Exception:
            return None
        if regles.en_haut(pose):
            return "haut"
        return "bas" if regles.en_bas(pose) else None

    def tete() -> None:
        if machine.prehension is None or machine.griffe is None:
            raise Absente("machine.yaml n'a pas de partie « prehension » (ou « griffe »)")
        if poste is None:
            raise Absente("poste du fût pas suivi : isolation du fût inconnue")
        faire.signaux(PESEE_TETE, VIDE, CONTACT, VANNE, AIMANTS)
        pont = faire.carte_fluidnc(CARTE_PONT)
        liaison = faire.carte_fluidnc(CARTE_TETE)
        force = faire.balance(PESEE_TETE)
        try:
            materiel.mesurer(VIDE)
        except Exception as erreur:
            raise Absente(f"capteur de vide « {VIDE} » : {erreur}") from None
        vide = CapteurVide(machine.prehension.vide, lambda: materiel.mesurer(VIDE))
        signaux = signaux_prehension(liaison, reglages.fluidnc.cartes[CARTE_TETE])
        cartes.tete = TeteFluidnc(
            machine, pont, liaison, signaux, force, vide, erreur_codeur=erreur_codeur
        )
        # Sans l'agitateur ni le porte-bocal (pièces absentes), la manivelle est inconnue : la
        # tête ne va jamais dans la zone du porte-bocal (vidange.prehension).
        cartes.prehension = Prehension(
            machine,
            cartes.tete,
            cartes.porte_bocal,
            manivelle=manivelle,
            panneau_rabattu=poste.panneau_vu_rabattu,
            echange_fut=lambda: poste.echange_en_cours,
            garde=garde,
        )

    def lavage() -> None:
        avant("tete")
        if machine.lavage is None:
            raise Absente("machine.yaml n'a pas de partie « lavage »")
        assert poste is not None and cartes.prehension is not None
        faire.signaux(*ENTREES_LAVAGE, *SORTIES_LAVAGE, RELAIS_CHAUFFAGE_LAVAGE)
        noms = {
            carte
            for nom in (*ENTREES_LAVAGE, *SORTIES_LAVAGE)
            for carte, reglage in reglages.fluidnc.cartes.items()
            if nom in reglage.entrees or nom in reglage.sorties
        }
        for nom in sorted(noms):
            faire.carte_fluidnc(nom)
        eau = EauLavage(
            machine.lavage,
            signaux_lavage(liaisons, reglages.fluidnc, materiel),
            fichier=None if donnees is None else donnees / NOM_EAU,
        )
        cartes.lavage = Lavage(
            machine,
            cartes.prehension,
            eau,
            mode=mode,
            refus_panneau=lambda: poste.refus_lancement("lavage"),
            panneau_rabattu=poste.panneau_vu_rabattu,
        )

    def griffe() -> None:
        if machine.griffe is None:
            raise Absente("machine.yaml n'a pas de partie « griffe »")
        if poste is None:
            raise Absente("poste du fût pas suivi : la griffe ne vide le fût que sous sa garde")
        # La porte du coffret du spray : griffe interdite en x < 0,50 et y < 0,40 (règle 3).
        faire.signaux(PESEE_GRIFFE, PORTE_SPRAY)
        liaison = faire.carte_fluidnc(CARTE_PONT)
        force = faire.balance(PESEE_GRIFFE)
        cartes.bras_griffe = BrasFluidnc(machine, liaison, force)

    def spray() -> None:
        if machine.spray is None:
            raise Absente("machine.yaml n'a pas de partie « spray »")
        faire.signaux(machine.spray.signal)
        try:
            etat = materiel.lire_spray(machine.spray.signal)
        except Exception as erreur:
            raise Absente(f"carte du spray « {machine.spray.signal} » : {erreur}") from None
        if vraie_machine and etat.exemple:
            raise Absente(
                f"carte du spray « {machine.spray.signal} » : programme fait avec des réglages "
                "d'EXEMPLE"
            )

    for piece, construire in (
        ("chariot", chariot),
        ("boitier", boitier),
        ("tete_micropore", tete_micropore),
        ("bras_fermeture", bras_fermeture),
        ("avance_micropore", avance_micropore),
        ("agitateur", agitateur),
        ("porte_bocal", porte_bocal),
        ("tete", tete),
        ("lavage", lavage),
        ("spray", spray),
        ("griffe", griffe),
    ):
        essayer(piece, construire)
    return cartes


class GriffeDuLot(Protocol):
    """Ce que le lot de seaux demande à une griffe jouée en faux (essais) : la vraie est
    vidange.cycle.griffe_du_lot.GriffeDuSeau, construite par PiecesMachine.remplissage."""

    # Le seau tourne tant de secondes pendant chaque versement (étape « verser »).
    versement_s: float

    def partie(self) -> bool:
        """La griffe est partie du poste (la Préhension peut poser le couvercle ; le bras du
        spray, lui, regarde sa zone : vidange.spray.zone)."""
        ...


class VersementBocal(Protocol):
    """Le versement de la griffe dans le bocal où est l'entonnoir, joué en faux (essais) : le
    vrai est vidange.griffe.versement.Versement, construit par PiecesMachine.entonnoir."""

    def verser(self, bocal: str) -> object: ...

    def fini(self) -> bool: ...


@dataclass
class Sources:
    """Ce que la machine n'a pas encore (cases vides, sans rien inventer) : None tant que ce n'est
    pas écrit, et le poste qui en a besoin dit « pas lancé : raison ». Sur la vraie machine,
    vidange.demarrage les laisse toutes à None ; les essais donnent des faux. `griffe` et
    `versement_bocal` : None, c'est la vraie griffe des cartes (tâche 45 sexies) ; un faux la
    remplace dans les essais."""

    # Une griffe jouée en faux (essais) ; None : la vraie, enchaînée au lot (tâche 45 sexies).
    griffe: GriffeDuLot | None = None
    # QR d'un bocal de semence lu par la caméra de la tête de la griffe (place → QR, ou None).
    qr_du_bocal: Callable[[str], str | None] | None = None
    # Photo du plafond : seaux pleins de la bande du haut (Stockage) ; entonnoir et col (bocaux).
    bande: VisionBande | None = None
    entonnoir: VisionEntonnoir | None = None
    # Un versement joué en faux (essais) ; None : le vrai, sur la griffe des cartes (43 bis).
    versement_bocal: VersementBocal | None = None
    # Bocaux sales et capsules à laver, vus par la caméra du plafond (règle 7).
    bocaux_sales: Callable[[], Sequence[ObjetLaveBocalSimule]] | None = None


def stockage_de_la_machine(
    machine: Machine,
    materiel: Materiel | None,
    registre: Any = None,
    vision: VisionBande | None = None,
) -> Stockage | None:
    """Le Stockage de la machine, un seul pour tout le programme : son inventaire (piles, bocaux
    de semence, boîtes à capsules) est repris du registre. None : machine.yaml sans stockage ou
    sans griffe, ou entrées/sorties pas ouvertes."""
    if machine.stockage is None or machine.griffe is None or materiel is None:
        return None
    lire = materiel.lire

    def boucle() -> bool | None:
        if BOUCLE not in materiel.branchements:
            return None
        return bool(lire(BOUCLE))

    return Stockage(machine, boucle_fermee=boucle, registre=registre, vision=vision)


def sans_bocal_neuf(variete: str) -> Any:
    """Le Mycélium sans le geste du bocal neuf : jamais sur la machine (il est branché)."""
    raise ErreurEtape(f"bocal neuf « {variete} » : le geste de la Préhension n'est pas branché")


class PiecesMachine:
    """`vraie_machine` : vrai matériel (le programme tourne sur le Pi) ; faux pour les essais avec
    un faux matériel (des réglages d'EXEMPLE y sont permis). `cartes` : celles de
    construire_cartes (None : pas construites). `machine` : machine.yaml (pour assembler les
    lots). `permission` : Chef.permission. `stockage` : stockage_de_la_machine (le même pour les
    seaux et les bocaux). `sources` : ce qui n'est pas encore écrit (None partout sur la
    machine)."""

    def __init__(
        self,
        poste: PosteFut | None,
        materiel: Materiel | None,
        vraie_machine: bool,
        spray: Spray | None = None,
        nettoyage: Nettoyage | None = None,
        vision: ReglagesVision | None = None,
        regard: Regard | None = None,
        donnees: Path | None = None,
        cartes: CartesMachine | None = None,
        machine: Machine | None = None,
        registre: Any = None,
        permission: Callable[[str], str | None] = lambda geste: None,
        stockage: Stockage | None = None,
        sources: Sources | None = None,
    ) -> None:
        self.poste = poste
        self.materiel = materiel
        self.vraie_machine = vraie_machine
        self.spray = spray
        self.nettoyage = nettoyage
        self.vision = vision
        self.regard = regard
        self.donnees = donnees
        self.cartes = cartes
        self.machine = machine
        self.registre = registre
        self.permission = permission
        self.stockage = stockage
        self.sources = sources or Sources()

    def manque_inspection(self) -> str | None:
        """Ce qui empêche la caméra du micropore de servir (QR du flanc, trous, morceaux)."""
        if self.vision is None:
            return VISION_ABSENTE
        inspection = self.vision.inspection
        if inspection is None:
            return INSPECTION_ABSENTE
        # Seule la partie « inspection » compte : le haut du fichier est celui des autres caméras.
        if self.vraie_machine and inspection.exemple:
            return INSPECTION_EXEMPLE
        if self.regard is None:
            return CAMERA_ABSENTE
        return None

    def manque_cartes(self, poste: str) -> str | None:
        """Les pièces du chariot et de la tête dont ce poste a besoin, ou None."""
        pieces = PIECES_DES_POSTES.get(poste, ())
        if not pieces:
            return None
        if self.cartes is None:
            return CARTES_PAS_CONSTRUITES
        return self.cartes.manque(*pieces)

    def manque_bocal_neuf(self) -> str | None:
        """Les deux sources du geste du bocal neuf que la machine n'a pas encore."""
        qr = self.sources.qr_du_bocal is None
        tete = None if self.cartes is None else self.cartes.tete
        codeur = tete is None or not tete.peut_detecter_le_calage()
        if qr and codeur:
            return BOCAL_NEUF
        if qr:
            return QR_DU_BOCAL
        return CODEUR if codeur else None

    def vision_inspection(
        self,
        angle_plateau: Callable[[], float | None],
    ) -> VisionInspection:
        """La vision du micropore, avec l'angle du plateau (donné par la carte du chariot)."""
        assert self.vision is not None and self.regard is not None
        fichier = None if self.donnees is None else self.donnees / NOM_ECARTS
        return VisionInspection(self.vision, self.regard, angle_plateau, EcartsAttaches(fichier))

    def manque(self, poste: str) -> str | None:
        if poste == "fut" and self.poste is None:
            return "poste du fût pas suivi (entrées/sorties pas ouvertes)"
        if poste in ("qr_du_flanc", "micropore"):
            return self.manque_inspection() or self.manque_cartes(poste)
        if poste == "spray":
            return CARTE_SPRAY if self.spray is None else self.manque_cartes(poste)
        if poste == "mycelium":
            return self.manque_cartes(poste) or self.manque_bocal_neuf()
        if poste == "griffe" and self.sources.griffe is not None:
            return None
        if poste == "versement":
            if self.sources.versement_bocal is not None:
                return None
            if self.machine is not None and (
                self.machine.griffe is None or self.machine.griffe.versement_bocal is None
            ):
                return VERSEMENT_ABSENT
            return self.manque_cartes(poste)
        if poste == "stockage":
            if self.materiel is None or BOUCLE not in self.materiel.branchements:
                return f"pas de signal « {BOUCLE} » ouvert (entrées/sorties)"
            if self.vraie_machine and self.sources.bande is None:
                return PHOTO_DE_LA_BANDE
            return None
        if poste == "entonnoir":
            if self.sources.entonnoir is None:
                return self.manque_cartes(poste) or PHOTO_DU_PLAFOND
            return self.manque_cartes(poste)
        if poste == "lavage_bocaux":
            if self.sources.bocaux_sales is None:
                return self.manque_cartes(poste) or BOCAUX_SALES
            return self.manque_cartes(poste)
        if poste in ("enceinte", "ozone", "purge"):
            return self._manque_nuit(poste)
        return self.manque_cartes(poste)

    def _manque_nuit(self, poste: str) -> str | None:
        if self.nettoyage is None or self.materiel is None:
            return NETTOYAGE_ABSENT
        if poste == "ozone":
            absents = [s for s in SIGNAUX_DE_LA_NUIT if s not in self.materiel.branchements]
            if absents:
                return f"pas de signal « {absents[0]} » ouvert (entrées/sorties)"
        if poste == "purge":
            absents = [
                nom
                for nom, capteur in (
                    ("particules_dedans", self.nettoyage.particules_dedans),
                    ("particules_dehors", self.nettoyage.particules_dehors),
                    ("pression_enceinte", self.nettoyage.capteur_pression),
                    ("consigne_ventilateur", self.nettoyage.consigne),
                )
                if capteur is None
            ]
            if absents:
                return f"capteurs de la purge absents ({', '.join(absents)})"
        return None

    # ------------------------------------------------------------ les lots (tâche 45 quater)

    def _pieces_du_lot(self, *pieces: str) -> CartesMachine:
        """Les cartes, avec ces pièces construites (ErreurChef sinon : jamais de geste inventé)."""
        if self.machine is None:
            raise ErreurChef("pièces de la machine sans machine.yaml : lot impossible")
        if self.cartes is None:
            raise ErreurChef(CARTES_PAS_CONSTRUITES)
        raison = self.cartes.manque(*pieces)
        if raison is not None:
            raise ErreurChef(raison)
        return self.cartes

    def remplissage(
        self,
        lot: Lot,
        avec_micropore: bool,
        avec_fermeture: bool,
        avec_spray: bool,
        avec_couvercle: bool,
    ) -> PiecesRemplissage:
        """Le lot de seaux sur les vraies cartes, assemblé comme vidange.cycle.simulation sur les
        pièces imaginaires : Remplissage (chariot, caméra du micropore), Mycélium (agitateur,
        porte-bocal) et son bocal neuf de semence (Préhension, Stockage), Micropore, Fermeture,
        Couvercle, Spray, et la griffe (GriffeDuSeau, tâche 45 sexies ; un faux des essais s'il
        est dans `sources`). Ce qui manque (griffe, QR du bocal, codeur de la rotation, photo du
        plafond...) : ErreurChef, avec la raison."""
        cartes = self._pieces_du_lot("chariot", "tete", "agitateur", "porte_bocal")
        machine = self.machine
        assert machine is not None
        fausse = self.sources.griffe
        manque_griffe = None
        if fausse is None:
            manque_griffe = cartes.manque("griffe") or (
                None if cartes.bras_griffe is not None else GRIFFE_DU_LOT
            )
        for raison in (
            self.manque_bocal_neuf(),
            manque_griffe,
            self.manque("stockage"),
            self.manque_inspection(),
            None if self.poste is not None else "poste du fût pas suivi",
        ):
            if raison is not None:
                raise ErreurChef(f"lot de seaux impossible : {raison}")
        assert self.stockage is not None and self.poste is not None
        chariot, prehension = cartes.chariot, cartes.prehension
        assert chariot is not None and prehension is not None
        poste = self.poste

        def angle_plateau() -> float | None:
            try:
                return chariot.position().a
            except Exception:
                return None

        vision = self.vision_inspection(angle_plateau)
        mycelium: Mycelium | None = None

        def refus_mycelium() -> str | None:
            return "Mycélium pas encore prêt" if mycelium is None else mycelium.refus_chariot()

        spray = self.spray if avec_spray else None
        remplissage = Remplissage(
            machine,
            chariot,
            registre=self.registre,
            plateau_fut_en_place=lambda: not poste.echange_en_cours,
            refus_mycelium=refus_mycelium,
            bras_spray_sorti=(lambda: False) if spray is None else spray.bras_spray_sorti,
            vision=vision,
            permission=self.permission,
        )
        if spray is not None:
            # Règle 6 : le bras ne sort que plateau assez bas et barres ouvertes ; le seau tourne
            # pendant la dose.
            spray.brancher_chariot(remplissage.refus_bras_spray, remplissage.tourner_pour_spray)
        if avec_micropore:
            assert cartes.tete_micropore is not None and cartes.avance_micropore is not None
            micropore = Micropore(
                machine,
                cartes.tete_micropore,
                cartes.avance_micropore,
                vision,
                cartes.tete_micropore.appris,
                registre=self.registre,
                fichier_etat=None if self.donnees is None else self.donnees / NOM_ETAT_MICROPORE,
            )
            micropore.brancher(remplissage)
        if avec_fermeture:
            assert cartes.bras_fermeture is not None
            Fermeture(machine, cartes.bras_fermeture, registre=self.registre).brancher(remplissage)
        assert cartes.agitateur is not None and cartes.porte_bocal is not None
        mycelium = Mycelium(
            machine,
            cartes.agitateur,
            cartes.porte_bocal,
            remplissage,
            sans_bocal_neuf,
            registre=self.registre,
            prehension_hors_zone=prehension.hors_zone_porte_bocal,
            permission=self.permission,
        )
        mycelium.brancher_bocal_neuf(
            BocalNeuf(
                machine,
                prehension,
                self.stockage,
                registre=self.registre,
                lire_qr=self.sources.qr_du_bocal,
            )
        )
        couvercle = Couvercle(machine, stockage=self.stockage) if avec_couvercle else None
        vraie: GriffeDuSeau | None = None
        if fausse is None:
            assert cartes.bras_griffe is not None
            camera = mycelium.camera
            vraie = GriffeDuSeau(
                machine,
                cartes.bras_griffe,
                poste,
                prehension,
                remplissage,
                lot.seaux,
                registre=self.registre,
                mode=cartes.mode,
                porte_spray_ouverte=self.porte_spray_ouverte,
                dosage_en_cours=mycelium.dosage_en_cours,
                camera_dosage_pivote=(lambda: False) if camera is None else camera.pivote,
                garde=cartes.garde,
            )
            self.stockage.brancher_griffe(vraie.griffe)
        griffe: GriffeDuLot = vraie if vraie is not None else fausse  # type: ignore[assignment]
        plan = Plan(seaux=list(lot.seaux), versement_s=griffe.versement_s, magasin=self.stockage)
        # Le bras du spray ne bouge que zone libre : la griffe, la préhension et ce qu'elles
        # tiennent, là où elles sont (fil Spray, 07/11/2026).
        # Et tant que le bras n'est pas vu rangé, ni l'une ni l'autre n'y entre (tâche 45 octies).
        zone = ZoneDuBras(
            machine,
            griffe=None if vraie is None else vraie.griffe,
            prehension=prehension,
            bras_au_repos=None if spray is None else (lambda: not spray.bras_spray_sorti()),
        )
        zone.brancher()
        return PiecesRemplissage(
            remplissage,
            prehension,
            mycelium,
            plan,
            spray=spray,
            griffe_partie=griffe.partie,
            couvercle=couvercle,
            griffe=vraie,
            zone_bras_spray=zone.libre,
        )

    def porte_spray_ouverte(self) -> bool:
        """La porte du coffret du spray (règle 3 de la griffe) ; illisible : comptée ouverte."""
        if self.materiel is None:
            return True
        try:
            return bool(self.materiel.lire(PORTE_SPRAY))
        except Exception:
            return True

    def griffe_des_bocaux(self) -> Griffe:
        """La griffe d'un lot de bocaux, sur le bras des cartes : maïs, sans mâchouiller ; la
        tête de préhension (même pont) est vérifiée à chaque pas qui bouge le pont."""
        cartes = self._pieces_du_lot("griffe", "tete")
        machine, poste = self.machine, self.poste
        assert machine is not None and cartes.bras_griffe is not None and poste is not None
        prehension = cartes.prehension
        assert prehension is not None

        def face_z() -> float | None:
            try:
                return prehension.tete.position().z
            except Exception:
                return None

        griffe = Griffe(
            machine,
            cartes.bras_griffe,
            poste,
            self.registre,
            mode=cartes.mode,
            porte_spray_ouverte=self.porte_spray_ouverte,
            machouiller=lambda: False,
            prehension_face_z=face_z,
            garde=cartes.garde,
        )
        brancher_pont(griffe, prehension)
        if self.stockage is not None:
            self.stockage.brancher_griffe(griffe)
        return griffe

    def entonnoir(self, lot: LotBocaux) -> PiecesEntonnoir:
        """Le lot de bocaux sur la tête de la Préhension : l'entonnoir (son état dans
        donnees/entonnoir.json), la photo du plafond (case vide : ErreurChef avec la raison tant
        qu'elle manque) et le versement de la griffe (vidange.griffe.versement sur la griffe des
        cartes, tâche 45 sexies ; un faux des essais s'il est dans `sources`)."""
        cartes = self._pieces_du_lot("tete")
        machine = self.machine
        assert machine is not None and cartes.prehension is not None
        vision, faux = self.sources.entonnoir, self.sources.versement_bocal
        if vision is None:
            raise ErreurChef(f"lot de bocaux impossible : {PHOTO_DU_PLAFOND}")
        if faux is None:
            raison = self.manque("versement") or (
                None if cartes.bras_griffe is not None else VERSEMENT_BOCAL
            )
            if raison is not None:
                raise ErreurChef(f"lot de bocaux impossible : {raison}")
        stockage = self.stockage

        def marquer_suspect(bocal: str) -> None:
            if stockage is not None:
                stockage.inventaire.changer_bocal(bocal, "suspect")

        entonnoir = Entonnoir(
            machine,
            None if self.donnees is None else self.donnees / NOM_ENTONNOIR,
            vision=vision,
            marquer_suspect=marquer_suspect,
        )
        if faux is not None:
            return PiecesEntonnoir(
                entonnoir, cartes.prehension, verser=faux.verser, versement_fini=faux.fini
            )
        # La distance de la tête (VL53L1X) n'est pas lue : sans elle, le bouchage de l'entonnoir
        # n'est pas vérifié, et le journal le dit (tâche 43 bis).
        versement = Versement(
            self.griffe_des_bocaux(),
            entonnoir,
            fichier=None if self.donnees is None else self.donnees / NOM_VERSEMENT,
            # Tête de préhension basse pendant les versements de la dernière rangée (07/11).
            prehension=cartes.prehension,
        )
        return PiecesEntonnoir(entonnoir, cartes.prehension, versement=versement)

    def lavage_bocaux(self) -> PiecesLavageBocaux:
        """Le lave-bocal sur le Lavage de la tête, avec les bocaux sales vus par la caméra du
        plafond (case vide : ErreurChef avec la raison tant qu'elle manque)."""
        cartes = self._pieces_du_lot("tete", "lavage")
        assert cartes.lavage is not None
        if self.sources.bocaux_sales is None:
            raise ErreurChef(f"lavage des bocaux impossible : {BOCAUX_SALES}")
        return PiecesLavageBocaux(LavageBocaux(cartes.lavage), self.sources.bocaux_sales())


class FondDuLot:
    """Les boucles en fond des pièces, pendant un lot seulement (rien au démarrage : tâche 45 ter,
    choix 2) : balance du chariot, balance de l'agitateur, pesée de la griffe (tâche 45 sexies),
    lecture et battement du boîtier du chariot (tête du micropore, bras de la fermeture), vide et
    force de la tête.

        fond = FondDuLot(cartes, reglages.programme.lot, chef)
        fond.demarrer(["remplissage", "mycelium"])   # au Go, juste avant le lot ; ErreurChef sinon
        fond.reprendre(["remplissage", "mycelium"])  # lot repris du carnet : le suivi seulement
        fond.suivre()                                # tous les suivi_periode_s (son propre fil)
        fond.arreter()

    Le suivi arrête les boucles quand plus aucun module du lot n'est « en cours » (alarme : elles
    repartent quand le lot repart ; lot fini ou abandonné : tout s'arrête, le suivi aussi). La
    tête : au premier départ, vanne et aimants coupés et zéro du vide recalé (TeteFluidnc.
    demarrer) ; ensuite (après une alarme) la surveillance seule, sans toucher la vanne (elle tient
    peut-être un seau). Lot repris du carnet : la tête attend le Go de Karulium avant de couper sa
    vanne (rien n'est commandé au démarrage du programme)."""

    def __init__(self, cartes: CartesMachine, reglages: ReglagesLot, chef: Chef) -> None:
        self.cartes = cartes
        self.reglages = reglages
        self.chef = chef
        self.modules: tuple[str, ...] = ()
        self._verrou = threading.Lock()
        self._arret: threading.Event | None = None
        self._fils: list[threading.Thread] = []
        self._actives: list[str] = []
        self._arret_suivi: threading.Event | None = None
        self._fil_suivi: threading.Thread | None = None
        # Un seul regard à la fois (le fil du suivi, ou un essai qui appelle suivre()).
        self._verrou_suivi = threading.Lock()

    @property
    def actives(self) -> list[str]:
        """Les boucles en route (noms), pour la page web et les essais."""
        with self._verrou:
            return list(self._actives)

    @property
    def en_route(self) -> bool:
        """Un lot est suivi (boucles en route, ou arrêtées sur alarme)."""
        return self._fil_suivi is not None

    def demarrer(self, modules: Sequence[str], suivi: bool = True) -> None:
        """Au Go : lance les boucles des pièces construites, la tête comprise, et leur suivi
        (`suivi` faux : `suivre()` à la main, pour les essais). ErreurChef si une boucle ne peut
        pas partir (zéro du vide faux...) : le lot ne doit alors pas être lancé."""
        self.arreter()
        self.modules = tuple(modules)
        self._lancer_boucles()
        try:
            self._lancer_tete()
        except ErreurChef:
            self._arreter_boucles()
            raise
        if suivi:
            self._lancer_suivi()

    def reprendre(self, modules: Sequence[str], suivi: bool = True) -> None:
        """Lot repris du carnet après une coupure : le suivi seulement ; les boucles partent quand
        le lot est en cours (la tête, après le Go)."""
        self.arreter()
        self.modules = tuple(modules)
        if suivi:
            self._lancer_suivi()

    def _lancer_suivi(self) -> None:
        self._arret_suivi = threading.Event()
        self._fil_suivi = lancer_boucle(
            "suivi_du_lot", self.reglages.suivi_periode_s, self.suivre, self._arret_suivi
        )

    def _demarrer(self, nom: str, lancer: Callable[[threading.Event], threading.Thread]) -> None:
        with self._verrou:
            if self._arret is None:
                self._arret = threading.Event()
            arret = self._arret
        try:
            fil = lancer(arret)
        except Exception as erreur:
            raise ErreurChef(f"boucle de fond « {nom} » du lot pas lancée : {erreur}") from None
        with self._verrou:
            self._fils.append(fil)
            self._actives.append(nom)
        journal.info("Lot : boucle de fond « %s » lancée", nom)

    def _lancer_boucles(self) -> None:
        """Les boucles qui ne commandent rien : balances, boîtier du chariot (son battement ne
        renvoie que les angles déjà ordonnés)."""
        cartes = self.cartes
        periode = self.reglages.fond_periode_s
        if cartes.chariot is not None:
            self._demarrer("chariot", cartes.chariot.demarrer)
        if cartes.bras_griffe is not None:
            # La pesée de la griffe, 80 fois par seconde : elle ne descend jamais sans elle.
            self._demarrer("griffe", cartes.bras_griffe.demarrer)
        if cartes.agitateur is not None:
            self._demarrer("agitateur", cartes.agitateur.demarrer)
        for nom, piece in (
            ("tete_micropore", cartes.tete_micropore),
            ("bras_fermeture", cartes.bras_fermeture),
        ):
            if piece is not None:
                observer = piece.observer
                self._demarrer(
                    nom, lambda arret, n=nom, o=observer: lancer_boucle(n, periode, o, arret)
                )

    def _lancer_tete(self) -> None:
        tete = self.cartes.tete
        if tete is None or "tete" in self.actives:
            return
        if tete.vide.zero is None:
            # Premier départ : vanne et aimants coupés, zéro du vide recalé.
            self._demarrer("tete", tete.demarrer)
        else:
            self._demarrer("tete", tete.surveiller_en_fond)

    def _arreter_boucles(self) -> None:
        with self._verrou:
            arret, fils, self._arret, self._fils = self._arret, self._fils, None, []
            actives, self._actives = self._actives, []
        if arret is None:
            return
        arret.set()
        for fil in fils:
            fil.join()
        journal.info("Lot : boucles de fond arrêtées (%s)", ", ".join(actives) or "aucune")

    def suivre(self) -> None:
        """Un regard sur le lot : boucles arrêtées sur alarme, relancées quand il repart, tout
        arrêté quand il est fini ou abandonné."""
        with self._verrou_suivi:
            self._suivre()

    def _suivre(self) -> None:
        etats = [m for m in self.chef.etat().modules if m.module in self.modules]
        if not etats:
            # Le lot n'est pas encore donné au chef (les boucles partent juste avant lui).
            return
        en_cours = [m for m in etats if m.statut == "en_cours"]
        if en_cours:
            try:
                if not self.actives:
                    self._lancer_boucles()
                tete = self.cartes.tete
                go_donne = any(m.attend != ATTENTE_GO for m in en_cours)
                if tete is not None and (tete.vide.zero is not None or go_donne):
                    self._lancer_tete()
            except ErreurChef as erreur:
                journal.error("Lot : %s", erreur)
            return
        self._arreter_boucles()
        if not any(m.statut == "alarme" for m in etats):
            journal.info("Lot fini : plus de boucle de fond")
            self._arreter_suivi()

    def _arreter_suivi(self) -> None:
        arret, fil = self._arret_suivi, self._fil_suivi
        self._arret_suivi = self._fil_suivi = None
        self.modules = ()
        if arret is not None:
            arret.set()
        if fil is not None and fil is not threading.current_thread():
            fil.join()

    def arreter(self) -> None:
        """Arrêt de tout (fin du programme, ou nouveau lot)."""
        self._arreter_suivi()
        self._arreter_boucles()
