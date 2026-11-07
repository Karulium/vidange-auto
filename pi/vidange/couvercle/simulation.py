"""Le couvercle sur la machine imaginaire du simulateur (tâche 41 bis).

    couvercle, monde = couvercle_du_simulateur(simulateur, scenario, stockage, nombre, pas_m)

Un faux monde (`MondeCouvercle`) répond ce que le vrai ferait à la Préhension simulée : le contact
M8 sur le haut de la pile (fond du stockage + nombre de couvercles × pas d'empilage), le contact
sur le seau plein (à Z_pose du format), le vide qui prend un couvercle (ou deux) quand la vanne
s'ouvre sur la pile, le couvercle qui reste sur le seau quand la vanne se ferme au-dessus, la
balance du chariot qui le pèse.

Pannes pour les essais (attributs de MondeCouvercle) :
- `nombre` : couvercles sur la pile (0 : pile vide, aucun contact) ;
- `colles` : tant de prochaines prises amènent DEUX couvercles collés ;
- `ecart_pose_m` : le contact à la pose vient tant plus haut (+ : anse levée, couvercle de
  travers) ou plus bas (−) que Z_pose ;
- `ne_tient_pas_sur_le_seau` : le couvercle lâché tombe à côté (la balance ne le voit pas) ;
- `pas_de_seau` : il n'y a pas de seau sous la tête à la pose (pas de contact) ;
- `palier_n` : le palier pesé garde tant de N après le lâcher (couvercle resté sur la ventouse) ;
- `m8_colle` : tant de « souffler » avant que le M8 retombe au dégagement ;
- `masse_kg` : masse réelle d'un couvercle (None : celle des réglages) ;
- `tete.pertes_de_vide`, `tete.vides_refuses`, `tete.vides_colles` (TeteSimulee).
"""

import math

from vidange.couvercle.couvercle import Couvercle
from vidange.griffe.bras import G
from vidange.prehension.simulation import TeteSimulee
from vidange.simulateur.simulateur import ErreurSimulation, Simulateur
from vidange.stockage import places
from vidange.stockage.stockage import Stockage

# Un endroit « est » sous la tête si elle en est à moins de tant (m) en x et y.
PROXIMITE_M = 0.005


class MondeCouvercle:
    def __init__(
        self,
        couvercle: Couvercle,
        scenario,
        nombre: int,
        pas_m: float,
    ) -> None:
        self.couvercle = couvercle
        self.scenario = scenario
        self.tete = scenario.prehension.tete
        assert isinstance(self.tete, TeteSimulee)
        self.pas_m = pas_m
        self.nombre = nombre
        self.tenus = 0
        self.sur_le_seau = 0
        self.tombes = 0
        # Pannes.
        self.colles = 0
        self.ecart_pose_m = 0.0
        self.ne_tient_pas_sur_le_seau = False
        self.m8_colle = 0
        self.pas_de_seau = False
        self.palier_n = 0.0
        self.masse_kg: float | None = None
        self.prises: list[int] = []
        machine = couvercle.machine
        self.pile = (couvercle.pile_x, places.prise_y(machine, couvercle.pile_y))
        self.pose = couvercle.reglages.pose
        tete = self.tete
        tete.contact_local = self.contact
        tete.contact_actif = self.m8
        tete.apres_perte_de_vide = self.tombe
        vanne, peser = tete.vanne, tete.peser

        def vanne_suivie(ouverte: bool) -> None:
            vanne(ouverte)
            self._vanne(ouverte)

        def peser_suivi() -> float:
            if self.tenus and scenario.prehension.objet is not None:
                return self.tenus * self._masse() * G
            if self.palier_n and self.sur_le_seau > 0 and scenario.prehension.objet is None:
                return self.palier_n
            return peser()

        tete.vanne = vanne_suivie  # type: ignore[method-assign]
        tete.peser = peser_suivi  # type: ignore[method-assign]

    # ------------------------------------------------------------ la physique

    def _masse(self) -> float:
        if self.masse_kg is not None:
            return self.masse_kg
        seau = self.scenario.remplissage.seau
        assert seau is not None
        return self.couvercle.masse_kg(seau.format)

    def _pres(self, point: tuple[float, float], x: float, y: float) -> bool:
        return math.dist(point, (x, y)) <= PROXIMITE_M

    def _seau_au_pose(self) -> bool:
        seau = self.scenario.remplissage.seau
        return seau is not None and self.scenario.chariot.seau_pose and not self.pas_de_seau

    def _z_pose(self) -> float:
        seau = self.scenario.remplissage.seau
        assert seau is not None
        return self.couvercle.z_pose(seau.format) + self.ecart_pose_m

    def contact(self, x: float, y: float) -> tuple[bool, float | None]:
        """(concerne, cote) : ce que le M8 touche sous la tête en (x ; y)."""
        if self._pres(self.pile, x, y):
            if self.nombre + self.tenus <= 0:
                return True, None
            return True, self.couvercle.fond_pile_z + (self.nombre + self.tenus) * self.pas_m
        if self._pres((self.pose.x, self.pose.y), x, y):
            return True, self._z_pose() if self._seau_au_pose() else None
        return False, None

    def m8(self) -> bool:
        if self.m8_colle > 0:
            return True
        pose = self.tete.position()
        if not self._pres((self.pose.x, self.pose.y), pose.x, pose.y) or not self._seau_au_pose():
            return False
        return pose.z <= self._z_pose() + 0.001 and (self.sur_le_seau > 0 or self.tenus > 0)

    def _vanne(self, ouverte: bool) -> None:
        pose = self.tete.position()
        if ouverte:
            if (
                self._pres(self.pile, pose.x, pose.y)
                and self.tete._vide
                and self.tenus == 0
                and self.nombre > 0
            ):
                prises = min(2 if self.colles > 0 else 1, self.nombre)
                if self.colles > 0:
                    self.colles -= 1
                self.nombre -= prises
                self.tenus = prises
                self.prises.append(prises)
            return
        if self.m8_colle > 0 and self.tenus == 0:
            self.m8_colle -= 1
        if self.tenus == 0:
            return
        if self._pres(self.pile, pose.x, pose.y):
            self.nombre += self.tenus
        elif (
            self._pres((self.pose.x, self.pose.y), pose.x, pose.y)
            and self._seau_au_pose()
            and not self.ne_tient_pas_sur_le_seau
        ):
            self.sur_le_seau += self.tenus
            self.scenario.chariot.contenu_kg += self.tenus * self._masse()
        else:
            self.tombes += self.tenus
        self.tenus = 0

    def tombe(self) -> None:
        self.tombes += self.tenus
        self.tenus = 0


def couvercle_du_simulateur(
    simulateur: Simulateur,
    scenario,
    stockage: Stockage | None,
    nombre: int,
    pas_m: float,
    **options,
) -> tuple[Couvercle, MondeCouvercle]:
    """Le Couvercle sur la Préhension simulée du scénario (« remplissage » ou « cycle »). `nombre`,
    `pas_m` : la pile imaginaire. `options` : ceux de Couvercle (photo...)."""
    machine = simulateur.reglages.machine
    if machine.couvercle is None:
        raise ErreurSimulation("machine.yaml n'a pas de partie « couvercle »")
    couvercle = Couvercle(machine, stockage=stockage, **options)
    if stockage is not None:
        stockage.charger_couvercles(nombre)
    return couvercle, MondeCouvercle(couvercle, scenario, nombre, pas_m)
