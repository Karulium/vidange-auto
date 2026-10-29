"""Faux porte-bocal, branché sur un faux FluidNC : pour les tests et le simulateur.

    carte = FauxFluidnc(axes="XY", horloge=...)
    materiel = FauxMaterielPorteBocal(carte, reglages.machine, reglages_carte, demi_tour_s=2.3)
    materiel.poser_bocal()          # un bocal entre les mors (sinon : pas de bocal)

Le plateau tourne quand une des sorties du pont en H est allumée, à 180° par `demi_tour_s`. Le doigt
du verrou entre dans un trou (tous les 180°) dès que l'électroaimant est relâché : le plateau s'y
arrête, même si le moteur tourne encore. Le capteur d'inclinaison dit tête en bas entre 90° et
270°. Les mors s'arrêtent au palpage sur le bocal posé.

Pannes pour les essais : `bloque` (le plateau ne tourne plus), `doigt_coince` (une fois retiré,
le doigt du verrou ne rentre plus), `inclinaison_forcee` (le capteur d'inclinaison reste actionné,
ou pas), `bocal_m` (diamètre du bocal posé, None : pas de bocal).
"""

from collections.abc import Callable

from vidange.fluidnc import FauxFluidnc
from vidange.griffe.bras import MM_PAR_M
from vidange.porte_bocal.porte_bocal import AIMANT, INCLINAISON, MOTEUR, VERROU
from vidange.reglages import CarteFluidnc, Machine

# Écart (°) sous lequel le doigt est en face d'un trou.
_TROU = 0.5


class FauxMaterielPorteBocal:
    def __init__(
        self,
        carte: FauxFluidnc,
        machine: Machine,
        reglages_carte: CarteFluidnc,
        demi_tour_s: float,
        horloge: Callable[[], float],
    ) -> None:
        assert machine.porte_bocal is not None
        self.reglages = machine.porte_bocal
        self.carte = carte
        self.demi_tour_s = demi_tour_s
        self._horloge = horloge
        self._dernier = horloge()
        self._lettres = {nom: reglages_carte.entrees[nom] for nom in (VERROU, INCLINAISON)}
        self._sorties = {nom: reglages_carte.sorties[nom] for nom in (AIMANT, *MOTEUR.values())}
        mors = machine.axes["mors"]
        self._mors = mors.lettre
        # Mors ouverts au départ, et après chaque prise d'origine.
        carte.origines[self._mors] = mors.course[1] * MM_PAR_M
        carte.positions[self._mors] = mors.course[1] * MM_PAR_M
        # Plateau : 0° = bocal debout ; le sens « vers tête en bas » fait monter l'angle.
        self.angle = 0.0
        self.bocal_m: float | None = None
        self.bloque = False
        self.doigt_coince = False
        self.inclinaison_forcee: bool | None = None
        self._doigt_sorti = False
        # Le trou où le doigt est entré la dernière fois (n° du demi-tour).
        self._trou = 0
        # Demi-tours finis (verrou engagé dans un autre trou).
        self.gestes: list[str] = []
        carte.monde = self.avancer
        carte.palpeur = self.palper
        self.avancer()

    def poser_bocal(self, diametre_m: float | None = None) -> None:
        self.bocal_m = self.reglages.diametre_bocal_m if diametre_m is None else diametre_m

    @property
    def tete_en_bas(self) -> bool:
        return 90 < self.angle % 360 < 270

    def _allumee(self, nom: str) -> bool:
        return self.carte.sorties.get(self._sorties[nom], False)

    def _en_face_d_un_trou(self) -> bool:
        reste = self.angle % 180
        return min(reste, 180 - reste) <= _TROU

    def avancer(self) -> None:
        maintenant = self._horloge()
        duree, self._dernier = maintenant - self._dernier, maintenant
        if self.doigt_coince and self._allumee(AIMANT):
            self._doigt_sorti = True
        aimant = self._allumee(AIMANT) or self._doigt_sorti
        sens = int(self._allumee(MOTEUR["tete_en_bas"])) - int(self._allumee(MOTEUR["debout"]))
        engage = not aimant and self._en_face_d_un_trou()
        if sens and not engage and not self.bloque and duree > 0:
            depart = self.angle
            arrivee = depart + sens * 180 / self.demi_tour_s * duree
            if not aimant:
                # Le doigt frotte : il entre dans le premier trou rencontré.
                trou = (depart // 180 + 1) * 180 if sens > 0 else -((-depart) // 180 + 1) * 180
                if (arrivee - trou) * sens >= 0:
                    arrivee = trou
            self.angle = arrivee
        engage = not aimant and self._en_face_d_un_trou()
        if engage and round(self.angle / 180) != self._trou:
            self._trou = round(self.angle / 180)
            self.gestes.append("tete_en_bas" if self.tete_en_bas else "debout")
        inclinaison = self.tete_en_bas == (self.reglages.inclinaison_actionne == "tete_en_bas")
        if self.inclinaison_forcee is not None:
            inclinaison = self.inclinaison_forcee
        entrees = self.carte.entrees
        for nom, actionne in ((VERROU, engage), (INCLINAISON, inclinaison)):
            if actionne:
                entrees.add(self._lettres[nom])
            else:
                entrees.discard(self._lettres[nom])

    def palper(self, avant: dict[str, float], arrivee: dict[str, float]) -> dict[str, float] | None:
        """Les mors se ferment : arrêt sur le bocal posé (StallGuard)."""
        if self.bocal_m is None or self._mors not in arrivee:
            return None
        bocal = self.bocal_m * MM_PAR_M
        if arrivee[self._mors] < bocal < avant[self._mors]:
            return {**arrivee, self._mors: bocal}
        return None
