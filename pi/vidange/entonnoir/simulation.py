"""L'entonnoir sur la machine imaginaire du simulateur (scénario « entonnoir »).

    scenario = entonnoir_du_simulateur(simulateur)
    planning = simulateur.jouer([scenario.module])

Un faux entonnoir (`MondeEntonnoir`) est posé sur un bocal, tenu par la tête, ou ailleurs
(tombé, ou hors machine). La vraie Préhension simulée le prend et le pose ; le faux monde répond
ce que le vrai ferait : le contact de la ventouse à la cote de l'oreille (entonnoir sur le bocal),
le contact sur le col quand elle le pose (au fond du col si l'axe est à moins de capture_m du
centre du col, sur le bord du verre un peu plus loin), le vide qui vient quand « aspirer »
s'ouvre sur l'oreille, et qui part quand « souffler » s'ouvre (tâche 45 undecies : fermer
« aspirer » ne lâche rien).

Pannes pour les essais (attributs de MondeEntonnoir) :
- `ou` : où est vraiment l'entonnoir (un bocal ; « absent » : nulle part, la ventouse ne trouve
  rien) ;
- `ecart_oreille_m` : l'oreille est tant plus haut (+) que l'attendu (entonnoir de travers) ;
- `poses_sur_le_bord` : tant de poses atterrissent sur le bord du verre, même centrées ;
- `ecart_col_m` : la caméra se trompe de tant sur le centre du col (en x) ;
- `cols_introuvables` : bocaux dont la caméra ne trouve pas le col ;
- `invisible` : la caméra ne voit pas l'entonnoir ;
- `tete.pertes_de_vide`, `tete.vides_refuses`, `tete.vides_colles` (TeteSimulee).
"""

import math
from dataclasses import dataclass, field

from vidange.chef import Module
from vidange.entonnoir.entonnoir import Entonnoir
from vidange.entonnoir.module import module_entonnoir
from vidange.prehension.prehension import Prehension
from vidange.prehension.simulation import TeteSimulee, prehension_du_simulateur
from vidange.simulateur.simulateur import ErreurSimulation, Simulateur
from vidange.stockage import places

HORS_MACHINE = "hors_machine"
TENU = "tenu"
ABSENT = "absent"
# Rayon du col (verre) autour du centre : au-delà, l'entonnoir ne repose sur rien (m).
RAYON_VERRE_M = 0.0475
# Le bord du verre porte la pointe plus haut de tant (m) qu'au fond du col.
HAUTEUR_BORD_M = 0.012
# La ventouse trouve l'oreille si elle est à moins de tant de son centre (m).
TOLERANCE_OREILLE_M = 0.03


class MondeEntonnoir:
    """Où est vraiment l'entonnoir, et ce que la caméra en voit."""

    def __init__(self, entonnoir: Entonnoir, tete: TeteSimulee) -> None:
        self.entonnoir = entonnoir
        self.tete = tete
        self.reglages = entonnoir.reglages
        self.places = entonnoir.places
        # Un nom de bocal, TENU, ABSENT, ou HORS_MACHINE.
        self.ou = HORS_MACHINE
        self.ecart_oreille_m = 0.0
        self.poses_sur_le_bord = 0
        self.ecart_col_m = 0.0
        self.cols_introuvables: set[str] = set()
        self.invisible = False
        self.versements: list[str] = []
        self.verse_s = 0.0
        self._fin_versement = 0.0
        self.horloge = lambda: 0.0
        tete.contact_physique = self.contact
        tete.apres_perte_de_vide = self.tombe
        vanne, souffler = tete.vanne, tete.souffler

        def vanne_suivie(ouverte: bool) -> None:
            vanne(ouverte)
            if ouverte:
                self._aspirer()

        def souffler_suivi(ouverte: bool) -> None:
            souffler(ouverte)
            if ouverte:
                self._souffler()

        tete.vanne = vanne_suivie  # type: ignore[method-assign]
        tete.souffler = souffler_suivi  # type: ignore[method-assign]

    # ------------------------------------------------------------ la physique

    def _sous_la_tete(self, x: float, y: float) -> tuple[str | None, float]:
        """Le bocal dont le centre est le plus près de l'axe de l'entonnoir tenu (la tête moins le
        décalage de l'oreille), et sa distance."""
        axe = (x - self.reglages.decalage_oreille_x_m, y - self.reglages.decalage_oreille_y_m)
        meilleur, distance = None, math.inf
        for nom, centre in self.places.items():
            d = math.dist(axe, centre)
            if d < distance:
                meilleur, distance = nom, d
        return meilleur, distance

    def contact(self, x: float, y: float) -> float | None:
        """La cote où la face de la ventouse touche quelque chose sous (x ; y), ou None."""
        reg = self.reglages
        if self.ou in self.places:
            bx, by = self.places[self.ou]
            oreille = (bx + reg.decalage_oreille_x_m, by + reg.decalage_oreille_y_m)
            if math.dist((x, y), oreille) <= TOLERANCE_OREILLE_M:
                return reg.oreille_z + self.ecart_oreille_m
            return None
        if self.ou != TENU:
            return None
        nom, distance = self._sous_la_tete(x, y)
        if nom is None or distance > RAYON_VERRE_M:
            return None
        if self.poses_sur_le_bord > 0:
            self.poses_sur_le_bord -= 1
            return reg.oreille_z + HAUTEUR_BORD_M
        if distance <= reg.col.capture_m:
            return reg.oreille_z
        return reg.oreille_z + HAUTEUR_BORD_M

    def _aspirer(self) -> None:
        pose = self.tete.position()
        if self.ou in self.places and self.tete._vide:
            bx, by = self.places[self.ou]
            oreille = (
                bx + self.reglages.decalage_oreille_x_m,
                by + self.reglages.decalage_oreille_y_m,
            )
            if math.dist((pose.x, pose.y), oreille) <= TOLERANCE_OREILLE_M:
                self.ou = TENU

    def _souffler(self) -> None:
        pose = self.tete.position()
        if self.ou == TENU and not self.tete._vide:
            nom, distance = self._sous_la_tete(pose.x, pose.y)
            self.ou = nom if nom is not None and distance <= RAYON_VERRE_M else ABSENT

    def tombe(self) -> None:
        if self.ou == TENU:
            self.ou = ABSENT

    def a_la_main(self, bocal: str | None) -> None:
        """Karulium pose l'entonnoir sur ce bocal (None : il l'enlève)."""
        self.ou = HORS_MACHINE if bocal is None else bocal

    # ------------------------------------------------------------ la caméra du plafond

    def entonnoir_vu(self, bocal: str) -> bool | None:
        return not self.invisible and self.ou == bocal

    def centre_du_col(self, bocal: str) -> tuple[float, float] | None:
        if bocal in self.cols_introuvables:
            return None
        x, y = self.places[bocal]
        return (x + self.ecart_col_m, y)

    # ------------------------------------------------------------ la griffe

    def verser(self, bocal: str) -> None:
        self.versements.append(bocal)
        self._fin_versement = self.horloge() + self.verse_s

    def versement_fini(self) -> bool:
        return self.horloge() >= self._fin_versement


@dataclass
class ScenarioEntonnoir:
    entonnoir: Entonnoir
    prehension: Prehension
    monde: MondeEntonnoir
    # None si le programme principal (vidange.cycle.mode_bocaux) construit le module lui-même.
    module: Module | None
    # Les bocaux que le Pi a marqués « suspects ».
    suspects: list[str] = field(default_factory=list)


def entonnoir_du_simulateur(
    simulateur: Simulateur, fichier=None, avec_module: bool = True, **options
) -> ScenarioEntonnoir:
    """Le module « entonnoir » sur la Préhension simulée. `options` : ceux de Entonnoir.
    `avec_module` faux : seulement les pièces (le programme principal, vidange.cycle.mode_bocaux,
    construit alors le module avec son `module_entonnoir`, comme sur la machine)."""
    reglages = simulateur.reglages
    machine = reglages.machine
    simule = reglages.simulateur.entonnoir
    if simule is None or machine.entonnoir is None:
        raise ErreurSimulation("simulateur.yaml ou machine.yaml n'a pas de partie « entonnoir »")
    inconnus = [bocal for bocal in simule.bocaux if bocal not in places.places_bocaux(machine)]
    if inconnus:
        raise ErreurSimulation(
            f"simulateur.yaml, entonnoir : « {inconnus[0]} » n'est pas une place du quinconce"
        )
    prehension = prehension_du_simulateur(simulateur)
    tete = prehension.tete
    assert isinstance(tete, TeteSimulee)
    suspects: list[str] = []
    monde_a_faire: list[MondeEntonnoir] = []

    class Vision:
        def entonnoir_vu(self, bocal: str) -> bool | None:
            return monde_a_faire[0].entonnoir_vu(bocal)

        def centre_du_col(self, bocal: str) -> tuple[float, float] | None:
            return monde_a_faire[0].centre_du_col(bocal)

    entonnoir = Entonnoir(
        machine,
        fichier,
        vision=Vision(),
        main=lambda bocal: monde_a_faire[0].a_la_main(bocal),
        marquer_suspect=suspects.append,
        **options,
    )
    monde = MondeEntonnoir(entonnoir, tete)
    monde_a_faire.append(monde)
    monde.horloge = lambda: simulateur.temps
    monde.verse_s = simule.verse_s
    module = None
    if avec_module:
        module = module_entonnoir(
            entonnoir,
            prehension,
            list(simule.bocaux),
            verser=monde.verser,
            versement_fini=monde.versement_fini,
        )
    return ScenarioEntonnoir(entonnoir, prehension, monde, module, suspects)
