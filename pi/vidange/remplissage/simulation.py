"""Le remplissage sur la machine imaginaire du simulateur : faux chariot (axes imaginaires, fausse
balance, fausse barrière), fausse caméra, vraie préhension simulée, vrai Mycélium avec un faux
agitateur et un faux porte-bocal.

    scenario = remplissage_du_simulateur(simulateur)    # seaux de simulateur.yaml → remplissage
    modules = [module_remplissage(...), module_mycelium(scenario.mycelium)]

La fausse balance pèse les seaux posés sur le plateau (tare de leur format, ou le poids d'un
seau vide) et ce qui y tombe (substrat des versements, grains du mycélium). Un seau est sur le
plateau quand le plateau touche son fond, ou quand la tête le lâche au-dessus du plateau (vanne
fermée). Le plateau qui monte au contact s'arrête au fond du seau tenu par la tête (`fond_z`),
≈ 3 cm plus bas pour deux seaux emboîtés. La barrière est coupée tant que deux seaux emboîtés y
sont (`double`) : ils sont séparés quand la tête tire le seau du dessus (prise double f), sauf
`separation_ratee`. Le pousseur qui sort fait partir le seau.
`alarmes_barres_actives` : les barres (« côté mur », « côté allée ») dont le pilote est en alarme
(ALM).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from vidange.chef import Condition
from vidange.mycelium.mycelium import Bocal, Mycelium
from vidange.mycelium.regles import EtatChariot
from vidange.mycelium.simulation import AgitateurSimule, FauxPorteBocal
from vidange.prehension.prehension import Prehension
from vidange.prehension.regles import Pose as PoseTete
from vidange.prehension.simulation import prehension_du_simulateur
from vidange.prehension.tete import Pas as PasTete
from vidange.reglages import Machine, SeauRemplissageSimule
from vidange.remplissage.chariot import VITESSES_LENTES, Pas, Resultat
from vidange.remplissage.module import Plan, SeauAFaire
from vidange.remplissage.regles import AXES, Pose, cles_du_pas
from vidange.remplissage.remplissage import Remplissage
from vidange.simulateur.axes import EtatAxes
from vidange.simulateur.simulateur import ErreurSimulation, Simulateur

CARTE = "chariot"


class ChariotSimule:
    """Le chariot sur les axes imaginaires (mêmes noms que ChariotFluidnc)."""

    def __init__(self, etat: EtatAxes, machine: Machine, horloge: Callable[[], float]) -> None:
        assert machine.remplissage is not None
        self._etat = etat
        self._horloge = horloge
        self.reglages = machine.remplissage
        v = self.reglages.vitesses
        self._vitesses = {
            "y": v.y,
            "z": v.plateau,
            "a": v.rotation,
            "barres": v.barres,
            "pousseur": v.pousseur,
            "barre_allee": v.barres,
        }
        self._arrivees: dict[str, float] = {}
        self._resultat: Resultat | None = None
        self._pas: Pas | None = None
        # Rotation en cours : (heure de départ, angle de départ, °/s signés).
        self._rotation: tuple[float, float, float] | None = None
        # Ce qui est sur le plateau.
        self.poids_un_seau = self.reglages.pesee.seau_vide_kg
        self.seau_pose = False
        self.double = False
        self.contenu_kg = 0.0
        # Fond du seau tenu au-dessus du plateau (None : rien) ; sans cette fonction, le plateau
        # touche tout de suite.
        self.fond_z: Callable[[], float | None] | None = None
        # Pannes.
        self.separation_ratee = False
        self.barriere_muette = False
        self.sans_contact = False
        self.alarmes_barres_actives: list[str] = []
        self.pretes = Condition("cartes simulées prêtes", lambda: True)
        self.surveillance = Condition("cartes simulées sans alarme", lambda: True)

    @property
    def poids_kg(self) -> float:
        seaux = (2 if self.double else 1) * self.poids_un_seau if self.seau_pose else 0.0
        return seaux + self.contenu_kg

    @poids_kg.setter
    def poids_kg(self, valeur: float) -> None:
        # Ce qui tombe dans le seau (grains du mycélium : vidange.mycelium.simulation).
        self.contenu_kg += valeur - self.poids_kg

    def position(self) -> Pose:
        positions = self._etat.positions
        return Pose(**{cle: positions[nom] for cle, nom in AXES.items()})

    def barriere_coupee(self) -> bool | None:
        return None if self.barriere_muette else self.double

    def alarmes_barres(self) -> list[str]:
        return list(self.alarmes_barres_actives)

    def executer(self, pas: Pas, cible: Pose) -> None:
        depart = self.position()
        contact = False
        if pas.contact_kg is not None and not self.sans_contact:
            fond = depart.z if self.fond_z is None else self.fond_z()
            if fond is not None and depart.z - 1e-9 <= fond <= cible.z + 1e-9:
                # Le plateau s'arrête au fond du seau : il le porte.
                cible, contact = cible.avec(z=fond), True
                self.seau_pose = True
        rentre = self.reglages.pousseur_rentre_m
        if "pousseur" in pas.cibles and abs(cible.pousseur - rentre) > 0.05:
            self.seau_pose, self.double, self.contenu_kg = False, False, 0.0
        vitesses = dict(self._vitesses)
        if pas.vitesse is not None:
            for cle in VITESSES_LENTES[pas.vitesse]:
                vitesses[cle] = min(vitesses[cle], getattr(self.reglages.vitesses, pas.vitesse))
        axes = {AXES[cle]: getattr(cible, cle) for cle in cles_du_pas(pas.cibles)}
        self._arrivees = self._etat.aller_vers(
            pas.texte, axes, {AXES[cle]: vitesse for cle, vitesse in vitesses.items()}
        )
        self._rotation = None
        if "a" in pas.cibles and cible.a != depart.a:
            sens = 1 if cible.a > depart.a else -1
            self._rotation = (self._horloge(), depart.a, sens * vitesses["a"])
        attente = pas.attente_s
        if pas.pesee:
            attente = max(attente, self.reglages.pesee.attente_s)
        if attente:
            self._arrivees = self._etat.attendre(CARTE, attente)
        self._pas = pas
        self._resultat = Resultat(
            pose=cible, contact=contact, poids_kg=self.poids_kg if pas.pesee else None
        )

    def fini(self) -> bool:
        return self._pas is None or self._etat.arrives(self._arrivees)

    def resultat(self) -> Resultat:
        assert self._resultat is not None
        if self._resultat.poids_kg is not None:
            return Resultat(self._resultat.pose, self._resultat.contact, self.poids_kg)
        return self._resultat

    def pauser(self) -> None:
        self._etat.pauser()

    def reprendre(self) -> None:
        self._etat.reprendre()

    def arreter(self) -> None:
        """Arrêt tout de suite ; une rotation s'arrête là où elle en est."""
        rotation, self._rotation, self._pas = self._rotation, None, None
        if rotation is not None:
            debut, angle, vitesse = rotation
            self._etat.arreter(CARTE, {"plateau_a": angle + vitesse * (self._horloge() - debut)})


class FausseVisionSeau:
    """La caméra imaginaire : lit le QR du seau posé ; les oreilles de son anse tournent avec
    le plateau."""

    def __init__(self, chariot: ChariotSimule) -> None:
        self.chariot = chariot
        self.code: str | None = None
        self.anse_deg = 0.0
        self._a_la_pose = 0.0
        self.illisible = False

    def poser(self, code: str, anse_deg: float) -> None:
        self.code, self.anse_deg = code, anse_deg
        self._a_la_pose = self.chariot.position().a

    def lire_seau(self) -> tuple[str, float] | None:
        if self.illisible or self.code is None:
            return None
        return self.code, self.anse_deg + self.chariot.position().a - self._a_la_pose


class _ChariotVuParLeMycelium:
    """Pour le faux agitateur : le vrai chariot (où il est) et la fausse balance (les grains)."""

    def __init__(self, remplissage: Remplissage, chariot: ChariotSimule) -> None:
        self.remplissage = remplissage
        self.materiel = chariot

    def etat(self) -> EtatChariot | None:
        return self.remplissage.etat()

    @property
    def poids_kg(self) -> float:
        return self.materiel.poids_kg

    @poids_kg.setter
    def poids_kg(self, valeur: float) -> None:
        self.materiel.poids_kg = valeur


@dataclass
class ScenarioRemplissage:
    remplissage: Remplissage
    prehension: Prehension
    mycelium: Mycelium
    plan: Plan
    chariot: ChariotSimule
    vision: FausseVisionSeau


def remplissage_du_simulateur(
    simulateur: Simulateur,
    cycle: int | None = None,
    seaux_simules: list[SeauRemplissageSimule] | None = None,
    **options: Any,
) -> ScenarioRemplissage:
    """Le remplissage sur la machine imaginaire, avec les seaux de simulateur.yaml
    (`remplissage`, ou `seaux_simules`) : chariot au poste (position remplissage_poste), tête en
    haut, manivelle du mycélium en bas (position agitateur_attente). Bras du galet rangé, tête du
    micropore rentrée (modules pas encore écrits). `options` : cases vides de Remplissage
    (registre, photo...)."""
    reglages = simulateur.reglages
    machine = reglages.machine
    simule = reglages.simulateur.remplissage
    simule_mycelium = reglages.simulateur.mycelium
    if simule is None or simule_mycelium is None or machine.remplissage is None:
        raise ErreurSimulation(
            "simulateur.yaml ou machine.yaml n'a pas de partie « remplissage » (ou « mycelium »)"
        )
    horloge = lambda: simulateur.temps  # noqa: E731
    etat = simulateur.etat_axes
    prehension = prehension_du_simulateur(simulateur)
    for position in ("remplissage_poste", "agitateur_attente"):
        if position in machine.positions:
            etat.positions.update(machine.positions[position])
    chariot = ChariotSimule(etat, machine, horloge)
    vision = FausseVisionSeau(chariot)
    poste = simulateur.poste_fut()
    mycelium: Mycelium | None = None

    def refus_mycelium() -> str | None:
        assert mycelium is not None
        return mycelium.refus_chariot()

    options.setdefault("plateau_fut_en_place", lambda: not poste.echange_en_cours)
    options.setdefault("bras_galet_range", lambda: True)
    options.setdefault("micropore_rentre", lambda: True)
    remplissage = Remplissage(
        machine,
        chariot,
        horloge=horloge,
        refus_mycelium=refus_mycelium,
        vision=vision,
        # Versement dans un seau ouvert : permission du chef (refusée pendant une purge).
        permission=simulateur.chef.permission,
        **options,
    )
    porte_bocal = FauxPorteBocal(simule_mycelium.demi_tour_s, horloge)
    agitateur = AgitateurSimule(
        etat,
        machine,
        simule_mycelium,
        _ChariotVuParLeMycelium(remplissage, chariot),  # type: ignore[arg-type]
        lambda: porte_bocal.tete_en_bas,
    )
    bocaux: list[Bocal] = []

    def nouveau_bocal(variete: str) -> Bocal:
        bocaux.append(Bocal(f"B{len(bocaux) + 1:04d}", variete))
        agitateur.bocal_kg = simule_mycelium.bocal_kg
        return bocaux[-1]

    mycelium = Mycelium(
        machine,
        agitateur,
        porte_bocal,
        remplissage,
        nouveau_bocal,
        horloge=horloge,
        prehension_hors_zone=prehension.hors_zone_porte_bocal,
        permission=simulateur.chef.permission,
    )
    liste = simule.seaux if seaux_simules is None else seaux_simules
    seaux = {seau.seau: seau for seau in liste}

    def debut_seau(seau: SeauAFaire) -> None:
        reglage = seaux[seau.seau]
        tare = machine.griffe.formats[seau.format].tare_kg  # type: ignore[union-attr]
        chariot.poids_un_seau = tare if tare is not None else machine.remplissage.pesee.seau_vide_kg  # type: ignore[union-attr]
        chariot.double = reglage.prise_double
        vision.poser(seau.seau, reglage.anse_deg)

    def versement(seau: SeauAFaire, couche: int) -> None:
        chariot.contenu_kg += machine.griffe.formats[seau.format].dose_kg  # type: ignore[union-attr]

    vanne, executer = prehension.tete.vanne, prehension.tete.executer

    def au_dessus() -> bool:
        pose, plateau = prehension.tete.position(), chariot.position()
        return (
            abs(pose.x - machine.remplissage.axe_x) < 0.01  # type: ignore[union-attr]
            and abs(pose.y - plateau.y) < 0.01
        )

    def vanne_simulee(ouverte: bool) -> None:
        # La tête lâche un seau au-dessus du plateau : il y est posé.
        if not ouverte and au_dessus() and prehension.objet is not None:
            chariot.seau_pose = True
        vanne(ouverte)

    def executer_simule(pas: PasTete, cible: PoseTete, poids_porte_n: float) -> None:
        # Prise double f) : la tête tire le seau du dessus, les barres tiennent celui du dessous.
        if pas.traction_max_n is not None and chariot.double and not chariot.separation_ratee:
            chariot.double = False
        executer(pas, cible, poids_porte_n)

    def fond_z() -> float | None:
        # Fond du seau tenu par la tête (de celui du dessous s'ils sont deux).
        if prehension.objet is None or not au_dessus():
            return None
        fond = prehension.tete.position().z - machine.remplissage.face_au_dessus_plateau_m  # type: ignore[union-attr]
        return fond - (simule.double_plus_bas_m if chariot.double else 0.0)

    prehension.tete.vanne = vanne_simulee  # type: ignore[method-assign]
    prehension.tete.executer = executer_simule  # type: ignore[method-assign]
    chariot.fond_z = fond_z
    plan = Plan(
        seaux=[
            SeauAFaire(seau.seau, seau.format, seau.variete, seau.file, cycle) for seau in liste
        ],
        stockage=simule.stockage,
        rendu=simule.rendu,
        versement_s=simule.versement_s,
        debut_seau=debut_seau,
        versement=versement,
    )
    return ScenarioRemplissage(remplissage, prehension, mycelium, plan, chariot, vision)
