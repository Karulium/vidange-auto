"""La fermeture sur la machine imaginaire : vrai bras (BrasFermeture) sur le faux boîtier du
chariot (FauxBoitierChariot, branché par le simulateur), faux couvercle contre le faux rouleau.

    simule = fermeture_du_simulateur(simulateur, remplissage, chariot)
    simule.physique.couvercle = False        # pas de couvercle sur le seau : pas de contact
    simule.physique.ecart_contact_m = -0.02  # le couvercle touche 2 cm trop tôt (de travers)
    simule.physique.raideur_n_par_m = 1e6    # couvercle qui bloque : effort au-delà de F_max
    simule.physique.effort_rotation_n = 300  # frottement de la rotation au-delà de F_max
    simule.boitier.redemarrer()              # la carte du plateau redémarre

Le faux couvercle ne pousse que si le bras est au travail (l'angle du servo est celui du travail)
et si un seau est sur le plateau : effort = raideur × (hauteur du plateau − hauteur du contact), le
contact étant à Hc + ecart_contact_m (simulateur.yaml → fermeture).
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from vidange.fermeture.bras import BrasFermeture
from vidange.fermeture.fermeture import Fermeture
from vidange.materiel import carte_pesee
from vidange.materiel.faux import FauxBoitierChariot
from vidange.reglages import Fermeture as ReglagesFermeture
from vidange.reglages import FermetureSimulee

if TYPE_CHECKING:
    from vidange.remplissage.remplissage import Remplissage
    from vidange.remplissage.simulation import ChariotSimule
    from vidange.simulateur.simulateur import Simulateur

# Le bras est « au travail » à tant de degrés près de l'angle commandé.
TOLERANCE_BRAS_DEG = 1.0


class CouvercleSimule:
    """Le faux couvercle contre le faux rouleau."""

    def __init__(
        self,
        reglages: ReglagesFermeture,
        simule: FermetureSimulee,
        remplissage: "Remplissage",
        chariot: "ChariotSimule",
        boitier: FauxBoitierChariot,
        voie: int,
    ) -> None:
        self.reglages = reglages
        self.remplissage = remplissage
        self.chariot = chariot
        self.boitier = boitier
        self.voie = voie
        self.raideur_n_par_m = simule.raideur_n_par_m
        self.ecart_contact_m = simule.ecart_contact_m
        # Pannes.
        self.couvercle = True
        self.effort_rotation_n = 0.0

    def bras_au_travail(self) -> bool:
        angle = carte_pesee.angle_du_registre(self.boitier.registres_angles[self.voie])
        return angle is not None and abs(angle - self.reglages.servo_travail_deg()) <= (
            TOLERANCE_BRAS_DEG
        )

    def effort(self, z: float, tourne: bool) -> float:
        """L'effort (N) du couvercle sur le plateau quand il est à z."""
        seau = self.remplissage.seau
        if (
            seau is None
            or not self.couvercle
            or not self.chariot.seau_pose
            or seau.format not in self.reglages.formats
            or not self.bras_au_travail()
        ):
            return 0.0
        contact = self.reglages.hc(seau.format) + self.ecart_contact_m
        effort = max(0.0, z - contact) * self.raideur_n_par_m
        return effort + (self.effort_rotation_n if tourne and effort > 0 else 0.0)


@dataclass
class FermetureDuSimulateur:
    fermeture: Fermeture
    bras: BrasFermeture
    physique: CouvercleSimule
    boitier: FauxBoitierChariot
    notes: list[str] = field(default_factory=list)


def fermeture_possible(simulateur: "Simulateur") -> bool:
    """Les réglages ont une fermeture (machine.yaml, simulateur.yaml, pesees.yaml → i2c) et le
    simulateur a branché le faux boîtier du chariot."""
    reglages = simulateur.reglages
    i2c = reglages.pesees.i2c
    if reglages.machine.fermeture is None or reglages.simulateur.fermeture is None or i2c is None:
        return False
    return simulateur.fabrique.carte_pesee(i2c.carte).boitier is not None


def fermeture_du_simulateur(
    simulateur: "Simulateur",
    remplissage: "Remplissage",
    chariot: "ChariotSimule",
    registre=None,
) -> FermetureDuSimulateur | None:
    """La fermeture branchée au Remplissage du simulateur ; None si les réglages n'en ont pas."""
    if not fermeture_possible(simulateur):
        return None
    reglages = simulateur.reglages
    machine, simule, i2c = reglages.machine, reglages.simulateur.fermeture, reglages.pesees.i2c
    assert machine.fermeture is not None and simule is not None and i2c is not None
    boitier = simulateur.fabrique.carte_pesee(i2c.carte).boitier
    assert boitier is not None
    horloge = lambda: simulateur.temps  # noqa: E731
    bras = BrasFermeture(machine.fermeture, i2c, simulateur.materiel, horloge)
    physique = CouvercleSimule(machine.fermeture, simule, remplissage, chariot, boitier, bras.voie)
    chariot.effort_n = physique.effort
    fermeture = Fermeture(machine, bras, registre=registre, horloge=horloge)
    fermeture.brancher(remplissage)
    # Mise en route : le bras n'est pas encore ordonné (position inconnue) ; il est lu et renvoyé
    # en fond (battement, redémarrages de la carte).
    simulateur.ajouter_fond(bras.observer, bras.prochain)
    return FermetureDuSimulateur(fermeture, bras, physique, boitier)
