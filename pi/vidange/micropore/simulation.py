"""Le micropore sur la machine imaginaire : vraie tête (TeteMicropore) sur le faux boîtier du
chariot (FauxBoitierChariot, branché par le simulateur), fausse paroi, faux moteur d'avance,
fausse caméra. Les gestes appris viennent de simulateur.yaml (micropore → appris).

    simule = micropore_du_simulateur(simulateur, remplissage, chariot)
    simule.physique.sans_paroi = True       # pas de seau devant la tête : pas de contact
    simule.physique.tof_fige_mm = 40        # ToF qui ne voit plus l'escamotage
    simule.vision.rates = 1                 # le prochain morceau est vu découvert
    simule.vision.manquants[0] = 1          # un trou de la rangée 1 pas vu
    simule.boitier.redemarrer()             # la carte du plateau redémarre

La fausse tête : elle avance de (angle − escamoté) × mm_par_degre ; le ToF lit escamotee_mm moins
cette avance. Un seau posé sur le plateau l'arrête là où le contact de son format a été appris.
Servos sortie coupée (carte redémarrée) : la tête reste où elle était.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from vidange.materiel.faux import FauxBoitierChariot
from vidange.micropore.appris import FichierAppris
from vidange.micropore.avance import AvanceSimulee
from vidange.micropore.micropore import Micropore, Reperage
from vidange.micropore.tete import TeteMicropore
from vidange.reglages import Micropore as ReglagesMicropore
from vidange.reglages import MicroporeSimule
from vidange.remplissage.regles import Pose

if TYPE_CHECKING:
    from vidange.remplissage.remplissage import Remplissage
    from vidange.simulateur.simulateur import Simulateur


class ChariotVu(Protocol):
    seau_pose: bool

    def position(self) -> Pose: ...


def distance_imaginaire(
    reglages: ReglagesMicropore, angle: float, escamote: float, contact: float | None
) -> int:
    """Le ToF de la tête imaginaire : escamotee_mm moins l'avance (angle − escamoté) ×
    mm_par_degre, arrêtée au contact d'une paroi (angle `contact`, None : pas de paroi) ou à la
    butée."""
    servos, tof = reglages.servos, reglages.tof
    avance = max(0.0, (angle - escamote) * servos.sens_avance * servos.mm_par_degre)
    if contact is not None:
        avance = min(
            avance, max(0.0, (contact - escamote) * servos.sens_avance * servos.mm_par_degre)
        )
    return round(max(tof.butee_mm, tof.escamotee_mm - avance))


class TeteSimulee:
    """La fausse tête devant la fausse paroi : la distance du ToF selon les angles des servos."""

    def __init__(
        self,
        reglages: ReglagesMicropore,
        appris: FichierAppris,
        remplissage: "Remplissage",
        chariot: ChariotVu,
        voie: int,
    ) -> None:
        self.reglages = reglages
        self.appris = appris
        self.remplissage = remplissage
        self.chariot = chariot
        self.voie = voie
        # Pannes.
        self.sans_paroi = False
        self.tof_fige_mm: int | None = None
        self._derniere = round(reglages.tof.escamotee_mm)

    def tof(self, angles: tuple[float | None, ...]) -> int | None:
        if self.tof_fige_mm is not None:
            return self.tof_fige_mm
        angle, escamote = angles[self.voie], self.appris.escamote_deg
        if angle is None or escamote is None:
            # Servo relâché : la tête ne bouge pas.
            return self._derniere
        contact = None
        seau = self.remplissage.seau
        if seau is not None and self.chariot.seau_pose and not self.sans_paroi:
            appris = self.appris.format(seau.format)
            if appris is not None:
                contact = appris.contact_deg
        self._derniere = distance_imaginaire(self.reglages, angle, escamote, contact)
        return self._derniere


class FausseVisionMicropore:
    """La caméra imaginaire : au tour de repérage, le QR du seau et ses trous (le premier à
    premier_trou_deg du départ, les autres répartis sur le tour) ; chaque morceau est vu couvert,
    sauf les `rates` suivants."""

    def __init__(
        self,
        reglages: ReglagesMicropore,
        simule: MicroporeSimule,
        remplissage: "Remplissage",
        chariot: ChariotVu,
    ) -> None:
        self.reglages = reglages
        self.simule = simule
        self.remplissage = remplissage
        self.chariot = chariot
        self._depart = 0.0
        self.illisible = False
        # Par rangée : trous pas vus.
        self.manquants: dict[int, int] = {}
        self.rates = 0
        self.tours = 0
        self.controles: list[tuple[int, float, bool]] = []

    def commencer_tour(self) -> None:
        self._depart = self.chariot.position().a

    def finir_tour(self) -> Reperage | None:
        self.tours += 1
        seau = self.remplissage.seau
        if self.illisible or seau is None:
            return None
        format = self.reglages.formats.get(seau.format)
        trous: dict[int, list[float]] = {}
        for rang, rangee in enumerate([] if format is None else format.rangees):
            vus = max(0, rangee.trous - self.manquants.get(rang, 0))
            trous[rang] = [
                self._depart + self.simule.premier_trou_deg + k * 360 / rangee.trous
                for k in range(vus)
            ]
        return Reperage(seau.code, None, trous)

    def controler_morceau(self, rangee: int, angle_deg: float) -> bool | None:
        couvert = self.rates <= 0
        self.rates = max(0, self.rates - 1)
        self.controles.append((rangee, angle_deg, couvert))
        return couvert


@dataclass
class MicroporeDuSimulateur:
    micropore: Micropore
    tete: TeteMicropore
    physique: TeteSimulee
    vision: FausseVisionMicropore
    avance: AvanceSimulee
    boitier: FauxBoitierChariot
    appris: FichierAppris
    notes: list[str] = field(default_factory=list)


def micropore_possible(simulateur: "Simulateur") -> bool:
    """Les réglages ont un micropore (machine.yaml, simulateur.yaml, pesees.yaml → i2c) et le
    simulateur a branché le faux boîtier du chariot."""
    reglages = simulateur.reglages
    i2c = reglages.pesees.i2c
    if reglages.machine.micropore is None or reglages.simulateur.micropore is None or i2c is None:
        return False
    return simulateur.fabrique.carte_pesee(i2c.carte).boitier is not None


def micropore_du_simulateur(
    simulateur: "Simulateur",
    remplissage: "Remplissage",
    chariot: ChariotVu,
    registre=None,
) -> MicroporeDuSimulateur | None:
    """Le micropore branché au Remplissage du simulateur ; None si les réglages n'en ont pas
    (machine.yaml → micropore, simulateur.yaml → micropore, pesees.yaml → i2c)."""
    if not micropore_possible(simulateur):
        return None
    reglages = simulateur.reglages
    machine, simule, i2c = reglages.machine, reglages.simulateur.micropore, reglages.pesees.i2c
    assert machine.micropore is not None and simule is not None and i2c is not None
    boitier = simulateur.fabrique.carte_pesee(i2c.carte).boitier
    assert boitier is not None
    horloge = lambda: simulateur.temps  # noqa: E731
    appris = FichierAppris(None, simule.appris)
    tete = TeteMicropore(machine.micropore, i2c, simulateur.materiel, appris, horloge)
    physique = TeteSimulee(machine.micropore, appris, remplissage, chariot, tete.voie_escamotage)
    boitier.tof_selon_angles = physique.tof
    vision = FausseVisionMicropore(machine.micropore, simule, remplissage, chariot)
    avance = AvanceSimulee(horloge)
    micropore = Micropore(machine, tete, avance, vision, appris, registre=registre, horloge=horloge)
    micropore.brancher(remplissage)
    # Mise en route : la tête escamotée, relue en fond (battement, redémarrages de la carte).
    tete.escamoter()
    simulateur.ajouter_fond(tete.observer, tete.prochain)
    return MicroporeDuSimulateur(micropore, tete, physique, vision, avance, boitier, appris)
