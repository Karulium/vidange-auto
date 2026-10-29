"""Le mycélium sur la machine imaginaire du simulateur : faux agitateur, vrai porte-bocal sur un
faux FluidNC (faux plateau, faux bocal : vidange.porte_bocal.faux), faux chariot de remplissage.

    mycelium = mycelium_du_simulateur(simulateur)   # les seaux de simulateur.yaml → mycelium
    module = module_mycelium(mycelium)

`faux_porte_bocal=True` remplace le vrai porte-bocal par un faux tout simple (FauxPorteBocal :
chaque geste dure `demi_tour_s`), pour les essais du Mycélium seul.

Quand la manivelle tourne, bocal tête en bas au dosage et seau dessous, les grains tombent dans
le seau tant que le bocal n'est pas vide (`debit_kg_s` à la vitesse d'agitation, moins quand elle
tourne plus lentement) : le faux chariot en porte le poids.
Le faux chariot vérifie le verrou du mycélium avant chaque trajet : s'il est refusé, alarme.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from vidange.chef import Condition, ErreurEtape
from vidange.fluidnc import FauxFluidnc
from vidange.fluidnc.directe import LiaisonDirecte
from vidange.mycelium.agitateur import Pas, Resultat
from vidange.mycelium.mycelium import Bocal, Demande, Mycelium, PorteBocal
from vidange.mycelium.regles import EtatChariot, PoseAgitateur, ReglesMycelium
from vidange.porte_bocal import PorteBocalFluidnc, signaux_porte_bocal
from vidange.porte_bocal.faux import FauxMaterielPorteBocal
from vidange.reglages import Machine, MyceliumSimule
from vidange.simulateur.axes import EtatAxes
from vidange.simulateur.simulateur import ErreurSimulation, Simulateur

CARTE = "mycelium_lavage"


class FauxPorteBocal:
    """Le porte-bocal tout simple : chaque geste dure `duree_s`."""

    def __init__(self, duree_s: float, horloge: Callable[[], float]) -> None:
        self.duree_s = duree_s
        self._horloge = horloge
        self._fin = 0.0
        self.tete_en_bas = False
        # Demi-tours, et gestes des mors.
        self.gestes: list[str] = []
        self.mors: list[str] = []

    def _geste(self, nom: str, tete_en_bas: bool) -> None:
        self.gestes.append(nom)
        self._fin = self._horloge() + self.duree_s
        self.tete_en_bas = tete_en_bas

    def retourner_tete_en_bas(self) -> None:
        self._geste("tete_en_bas", True)

    def remettre_debout(self) -> None:
        self._geste("debout", False)

    def ouvrir_mors(self) -> None:
        self.mors.append("ouvrir")
        self._fin = self._horloge() + self.duree_s

    def serrer_bocal(self) -> None:
        self.mors.append("serrer")
        self._fin = self._horloge() + self.duree_s

    def fini(self) -> bool:
        return self._horloge() >= self._fin

    def arreter(self) -> None:
        self._fin = 0.0


@dataclass
class _Trajet:
    depart: EtatChariot
    arrivee: EtatChariot
    debut: float


class FauxChariot:
    """Le chariot de remplissage : il roule en `duree_s`, si le verrou du mycélium le permet."""

    def __init__(
        self,
        machine: Machine,
        duree_s: float,
        horloge: Callable[[], float],
        verrou: Callable[[], str | None] = lambda: None,
    ) -> None:
        assert machine.mycelium is not None
        self.reglages = machine.mycelium.chariot
        self.duree_s = duree_s
        self._horloge = horloge
        self.verrou = verrou
        position = EtatChariot(y=self.reglages.y_ecarte_min, plateau_z=self.reglages.plateau_max_z)
        self._trajet = _Trajet(position, position, 0.0)
        # Poids sur le plateau (kg) : seau et ce qui y tombe.
        self.poids_kg = 0.0

    def etat(self) -> EtatChariot:
        trajet = self._trajet
        t = 1.0 if self.duree_s == 0 else (self._horloge() - trajet.debut) / self.duree_s
        if t >= 1:
            return trajet.arrivee
        depart, arrivee = trajet.depart, trajet.arrivee
        return EtatChariot(
            y=depart.y + t * (arrivee.y - depart.y),
            plateau_z=depart.plateau_z + t * (arrivee.plateau_z - depart.plateau_z),
            immobile=False,
        )

    def _aller(self, y: float, plateau_z: float) -> None:
        refus = self.verrou()
        if refus is not None:
            raise ErreurEtape(f"chariot de remplissage refusé : {refus}")
        self._trajet = _Trajet(self.etat(), EtatChariot(y, plateau_z), self._horloge())

    def ecarter(self) -> None:
        self._aller(self.reglages.y_ecarte_min, self.etat().plateau_z)

    def amener_au_dosage(self, plateau_z: float) -> None:
        self._aller(self.reglages.y_dosage, plateau_z)


class AgitateurSimule:
    """L'agitateur sur les axes imaginaires (mêmes noms que AgitateurFluidnc)."""

    def __init__(
        self,
        etat: EtatAxes,
        machine: Machine,
        reglages: MyceliumSimule,
        chariot: FauxChariot,
        tete_en_bas: Callable[[], bool],
        origine_connue: bool = True,
    ) -> None:
        """`origine_connue` : False pour rejouer aussi la prise d'origine de la manivelle (un
        tour lent, sans faux capteur)."""
        assert machine.mycelium is not None
        self._etat = etat
        self.regles = ReglesMycelium(machine)
        self.vitesses = machine.mycelium.vitesses
        self.reglages = reglages
        self.chariot = chariot
        self.tete_en_bas = tete_en_bas
        self.origine = machine.mycelium.manivelle.origine
        self._origine_connue = origine_connue
        # Mycélium encore dans le bocal (kg).
        self.bocal_kg = reglages.bocal_kg
        self._arrivees: dict[str, float] = {}
        self._resultat: Resultat | None = None
        self._pas: Pas | None = None
        self.pretes = Condition("cartes simulées prêtes", lambda: True)
        self.surveillance = Condition("cartes simulées sans alarme", lambda: True)

    def position(self) -> PoseAgitateur:
        return PoseAgitateur(
            x=self._etat.positions["agitateur_x"], angle=self._etat.positions["manivelle"]
        )

    def glissiere_x(self) -> float:
        return self._etat.positions["agitateur_x"]

    def origine_connue(self) -> bool:
        return self._origine_connue

    def _verse(self, pose: PoseAgitateur) -> bool:
        """Les grains tombent dans le seau quand la manivelle tourne à cette pose."""
        return (
            self.tete_en_bas()
            and self.regles.au_dosage(pose)
            and self.regles.chariot_au_dosage(self.chariot.etat())
        )

    def executer(self, pas: Pas, cible: PoseAgitateur | None) -> None:
        if pas.origine:
            # Tour lent ; l'angle imaginaire compte déjà depuis « en haut ».
            angle = self._etat.positions["manivelle"] + self.origine.balayage_deg()
            self._arrivees = self._etat.aller_vers(
                pas.texte, {"manivelle": angle}, {"manivelle": self.origine.vitesse_deg_s}
            )
            self._pas, self._origine_connue = pas, True
            self._resultat = Resultat(pose=self.position().avec(angle=angle))
            return
        assert cible is not None
        depart = self.position()
        arrete = False
        tour = abs(cible.angle - depart.angle)
        vitesse = 6 * (pas.tr_min or self.vitesses.placement_tr_min)
        if tour > 0 and self._verse(depart):
            duree = tour / vitesse
            debit = self.reglages.debit_kg_s * vitesse / (6 * self.vitesses.agitation_tr_min)
            manque = math.inf if pas.jusqu_a_kg is None else pas.jusqu_a_kg - self.chariot.poids_kg
            if debit * duree >= manque and self.bocal_kg >= manque:
                # Dose atteinte avant la fin : la balance arrête la manivelle.
                duree = max(manque, 0.0) / debit
                sens = 1 if cible.angle > depart.angle else -1
                cible, arrete = cible.avec(angle=depart.angle + sens * vitesse * duree), True
            tombe = min(debit * duree, self.bocal_kg)
            self.bocal_kg -= tombe
            self.chariot.poids_kg += tombe
        self._arrivees = self._etat.aller_vers(
            pas.texte,
            {"agitateur_x": cible.x, "manivelle": cible.angle},
            {"agitateur_x": self.vitesses.glissiere_m_s, "manivelle": vitesse},
        )
        if pas.attente_s:
            self._arrivees = self._etat.attendre(CARTE, pas.attente_s)
        self._pas = pas
        self._resultat = Resultat(
            pose=cible, arrete=arrete, poids_kg=self.chariot.poids_kg if pas.pesee else None
        )

    def fini(self) -> bool:
        return self._pas is None or self._etat.arrives(self._arrivees)

    def resultat(self) -> Resultat:
        assert self._resultat is not None
        return self._resultat

    def pauser(self) -> None:
        self._etat.pauser()

    def reprendre(self) -> None:
        self._etat.reprendre()

    def arreter(self) -> None:
        self._pas = None

    @property
    def saut(self) -> bool:
        return False

    def oublier_saut(self) -> None:
        pass


def mycelium_du_simulateur(
    simulateur: Simulateur,
    cycle: int | None = None,
    faux_porte_bocal: bool = False,
    controle: Callable[[], str] = lambda: "bon",
    origine_connue: bool = True,
    **options: Any,
) -> Mycelium:
    """Le mycélium sur la machine imaginaire, avec les seaux de simulateur.yaml (chaque couche
    de leur format, dans l'ordre, dans ce cycle du registre). Le bocal attend au garage
    (position agitateur_garage). `controle` : réponse de la photo de contrôle du bocal.
    `origine_connue=False` : la prise d'origine de la manivelle est rejouée aussi.
    `options` : registre, photo..."""
    reglages = simulateur.reglages
    machine = reglages.machine
    simule = reglages.simulateur.mycelium
    if simule is None or machine.mycelium is None or machine.griffe is None:
        raise ErreurSimulation("simulateur.yaml ou machine.yaml n'a pas de partie « mycelium »")
    horloge = lambda: simulateur.temps  # noqa: E731
    etat = simulateur.etat_axes
    if "agitateur_garage" in machine.positions:
        etat.positions.update(machine.positions["agitateur_garage"])
    porte_bocal: PorteBocal
    materiel: FauxMaterielPorteBocal | None = None
    if faux_porte_bocal or machine.porte_bocal is None:
        faux = FauxPorteBocal(simule.demi_tour_s, horloge)
        porte_bocal, tete_en_bas = faux, lambda: faux.tete_en_bas
    else:
        # Le vrai porte-bocal, sur un faux FluidNC (carte n° 3) à l'heure du simulateur.
        carte = FauxFluidnc(axes="XY", horloge=horloge)
        liaison = LiaisonDirecte(CARTE, carte)
        reglages_carte = reglages.fluidnc.cartes[CARTE]
        materiel = FauxMaterielPorteBocal(
            carte, machine, reglages_carte, simule.demi_tour_s, horloge
        )
        porte_bocal = PorteBocalFluidnc(
            machine,
            liaison,  # type: ignore[arg-type]
            signaux_porte_bocal(liaison, reglages_carte),  # type: ignore[arg-type]
            horloge=horloge,
            photo=options.get("photo", lambda raison: None),
            controle=controle,
        )
        tete_en_bas = lambda: materiel.tete_en_bas  # noqa: E731
    chariot = FauxChariot(machine, simule.chariot_s, horloge)
    agitateur = AgitateurSimule(etat, machine, simule, chariot, tete_en_bas, origine_connue)
    bocaux: list[Bocal] = []

    def nouveau_bocal(variete: str) -> Bocal:
        bocaux.append(Bocal(f"B{len(bocaux) + 1:04d}", variete))
        agitateur.bocal_kg = simule.bocal_kg
        if materiel is not None:
            materiel.poser_bocal()
        return bocaux[-1]

    mycelium = Mycelium(
        machine, agitateur, porte_bocal, chariot, nouveau_bocal, horloge=horloge, **options
    )
    mycelium.materiel_porte_bocal = materiel
    chariot.verrou = mycelium.refus_chariot
    if isinstance(porte_bocal, PorteBocalFluidnc):
        porte_bocal.verrou = mycelium.refus_demi_tour
    for seau in simule.seaux:
        for couche in range(1, machine.griffe.formats[seau.format].couches + 1):
            mycelium.demander(Demande(seau.seau, seau.format, couche, seau.variete, cycle))
    mycelium.terminer()
    return mycelium
