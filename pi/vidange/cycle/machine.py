"""Les pièces du programme principal sur la machine (tâches 45, 45 bis et 45 ter).

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
- « spray » : la carte ESP32 n° 5 du spray (bus rs485_spray), qui répond.
Une pièce absente (signal pas dans la liste, ligne `exemple: true` ou réglage d'EXEMPLE sur la vraie
machine, numéro de série introuvable, carte qui ne répond pas) n'arrête jamais le démarrage : elle
n'est pas construite, et les postes qui en ont besoin sont « pas lancés : raison » (check-list,
écran, journal). La présence est regardée une fois, au démarrage : une carte branchée après
demande de relancer le programme. Rien n'est commandé au démarrage (aucun ordre aux servos ni aux
sorties) : les boucles en fond de ces pièces partiront avec le lot.

Ce qui manque encore pour qu'un lot parte sur la machine, sans rien inventer :
- griffe (case vide d'ORDRE_SEAU) : son enchaînement avec la préhension (solveur, tâche 23) ;
- mycélium : le geste du bocal neuf de semence est écrit (vidange.bocal_neuf, tâche 19 quater),
  mais il lui manque deux sources que la machine n'a pas encore : la lecture du QR du bocal par la
  caméra de la tête de la griffe, et l'erreur du codeur de la rotation de la tête (calage du
  moteur) ;
- QR du flanc et micropore : la vision (vidange.vision.inspection, tâche 40 ter) attend ses
  réglages vrais (vision.yaml → inspection) et la caméra ;
- stockage : il faut le signal de la boucle du tiroir et des panneaux ;
- entonnoir : la lecture de la photo du plafond (l'entonnoir est-il sur le bocal ? où est le
  centre du col ?) n'est pas écrite ;
- lavage des bocaux : la liste des bocaux sales vient de la caméra du plafond (règle 7), pas
  écrite ;
- nuit UV-ozone : tout est là (le Nettoyage tourne déjà) ; elle ne manque que si le Nettoyage n'est
  pas construit ou si un signal de la nuit manque dans la liste des entrées/sorties.
Tant que ces cases vides restent, `remplissage`, `entonnoir` et `lavage_bocaux` ne sont jamais
appelés sur la machine (le poste « mycelium », cœur du lot, dit lequel manque).
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vidange.angles_gardes import AnglesGardes
from vidange.cycle.mode_bocaux import LotBocaux, PiecesEntonnoir, PiecesLavageBocaux
from vidange.cycle.mode_seaux import Lot, PiecesRemplissage
from vidange.entrees_sorties import EntreesSorties
from vidange.fermeture.bras import BrasFermeture
from vidange.fiabilite.constats import Constat
from vidange.fluidnc import Liaison
from vidange.fluidnc.ports import CarteIntrouvable, lister_ports_usb, trouver_port
from vidange.journal import donner_journal
from vidange.lavage.eau import NOM_EAU, EauLavage
from vidange.lavage.lavage import Lavage
from vidange.lavage.signaux import signaux_lavage
from vidange.materiel import Materiel
from vidange.micropore.appris import NOM_APPRIS, FichierAppris
from vidange.micropore.avance import AvanceFluidnc
from vidange.micropore.tete import TeteMicropore
from vidange.mycelium.agitateur import AgitateurFluidnc
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
from vidange.reglages import ENTREES_LAVAGE, SORTIES_LAVAGE, Fluidnc, Reglages, ReglagesVision
from vidange.remplissage.chariot import ALARMES_BARRES, BARRIERE, ChariotFluidnc, signaux_chariot
from vidange.spray.spray import Spray
from vidange.stockage.simulation import BOUCLE
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
PHOTO_DU_PLAFOND = (
    "lecture de la photo du plafond (entonnoir sur le bocal, centre du col) pas écrite"
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
    absentes: dict[str, str] = field(default_factory=dict)

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
) -> CartesMachine:
    """Construit les pièces du chariot et de la tête qui sont là ; jamais d'exception (une pièce
    absente est notée avec sa raison, dans le journal aussi). `presence` : presence_fluidnc ;
    `mode` : ModeMachine.actuel (Lavage) ; `garde` : les angles gardés (rotation de la tête)."""
    cartes = CartesMachine()
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
        cartes.tete = TeteFluidnc(machine, pont, liaison, signaux, force, vide)
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
        faire.signaux(*ENTREES_LAVAGE, *SORTIES_LAVAGE)
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
            signaux_lavage(liaisons, reglages.fluidnc),
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
    ):
        essayer(piece, construire)
    return cartes


class PiecesMachine:
    """`vraie_machine` : vrai matériel (le programme tourne sur le Pi) ; faux pour les essais avec
    un faux matériel (des réglages d'EXEMPLE y sont permis). `cartes` : celles de
    construire_cartes (None : pas construites)."""

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
            return self.manque_cartes(poste) or BOCAL_NEUF
        if poste == "stockage" and (
            self.materiel is None or BOUCLE not in self.materiel.branchements
        ):
            return f"pas de signal « {BOUCLE} » ouvert (entrées/sorties)"
        if poste == "entonnoir":
            return self.manque_cartes(poste) or PHOTO_DU_PLAFOND
        if poste == "lavage_bocaux":
            return self.manque_cartes(poste) or BOCAUX_SALES
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

    def remplissage(
        self,
        lot: Lot,
        avec_micropore: bool,
        avec_fermeture: bool,
        avec_spray: bool,
        avec_couvercle: bool,
    ) -> PiecesRemplissage:
        # Jamais appelé : le poste « mycelium » (cœur) manque toujours (BOCAL_NEUF : QR du bocal,
        # codeur de la rotation), et la griffe est une case vide. Les cartes sont là
        # (self.cartes, dont l'agitateur et le porte-bocal) ; le Mycélium, le Stockage, le
        # BocalNeuf, le Micropore, la Fermeture, le Couvercle et le Spray seront assemblés dessus
        # comme dans vidange.cycle.simulation.
        raise NotImplementedError(BOCAL_NEUF)

    def entonnoir(self, lot: LotBocaux) -> PiecesEntonnoir:
        # Jamais appelé : le poste « entonnoir » manque toujours (photo du plafond).
        raise NotImplementedError(PHOTO_DU_PLAFOND)

    def lavage_bocaux(self) -> PiecesLavageBocaux:
        # Jamais appelé : le poste « lavage_bocaux » manque toujours (bocaux sales).
        raise NotImplementedError(BOCAUX_SALES)
