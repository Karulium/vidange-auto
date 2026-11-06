"""La griffe sur la machine imaginaire du simulateur, et une fausse pesée pour les tests.

    griffe = griffe_du_simulateur(simulateur)   # le fût est celui du poste du simulateur
    module = module_griffe(griffe)

Le faux fût (`FutSimule`) garde le substrat qui reste : son niveau (fond + volume / section) et
son poids, qu'il écrit sur la fausse pesée du plateau du fût. Le godet prend « densité vraie ×
volume de la table » quand il se ferme dans le substrat (moins près de la paroi et au fond), le
rend au fût s'il s'ouvre dedans, le verse dans le seau ailleurs. Une descente au contact s'arrête
sur le substrat ; une poussée s'arrête sur le fond.
"""

import math
from collections.abc import Callable
from typing import Any

from vidange.chef import Condition
from vidange.griffe.bras import Conversion, G, Pas, Resultat
from vidange.griffe.doses import volume_l
from vidange.griffe.griffe import Griffe
from vidange.griffe.regles import Pose, ReglesGriffe
from vidange.reglages import GriffeSimulee, Machine
from vidange.simulateur.axes import EtatAxes
from vidange.simulateur.simulateur import ErreurSimulation, Simulateur

CARTE = "portique"


class FausseForce:
    """Pesée de la griffe pour les tests : une valeur, ou une fonction de l'heure."""

    def __init__(self, newtons: float = 20.0) -> None:
        self.newtons = newtons
        self.fonction: Callable[[], float] | None = None
        self.muette = False

    def lire_n(self) -> float:
        if self.muette:
            raise TimeoutError("pesée de la griffe muette")
        return self.fonction() if self.fonction is not None else self.newtons


class FutSimule:
    """Le substrat d'un fût imaginaire."""

    def __init__(
        self,
        machine: Machine,
        reglages: GriffeSimulee,
        masse_depart: Callable[[], float | None],
        regler_pesee: Callable[[float], None] = lambda kg: None,
    ) -> None:
        assert machine.poste_fut is not None
        self.fut = machine.poste_fut
        self.reglages = reglages
        self._masse_depart = masse_depart
        self._regler_pesee = regler_pesee
        self._masse: float | None = None
        # Substrat versé dans les seaux (kg).
        self.verse_kg = 0.0

    @property
    def masse(self) -> float:
        if self._masse is None:
            self._masse = max(self._masse_depart() or 0.0, 0.0)
        return self._masse

    def changer(self, kg: float) -> None:
        self._masse = max(self.masse + kg, 0.0)
        self._regler_pesee(self._masse)

    @property
    def niveau(self) -> float:
        """Surface du substrat (m)."""
        section = math.pi * (self.fut.fut_diametre_interieur / 2) ** 2
        hauteur = self.masse / self.reglages.densite_kg_l / 1000 / section
        return min(self.fut.fut_fond_interieur_z + hauteur, self.fut.fut_bord_z)


class BrasSimule:
    """Le bras de la griffe sur les axes imaginaires (mêmes noms que BrasFluidnc)."""

    def __init__(
        self, etat: EtatAxes, machine: Machine, fut: FutSimule, reglages: GriffeSimulee
    ) -> None:
        assert machine.griffe is not None
        self._etat = etat
        self.conversion = Conversion(machine)
        self.regles = ReglesGriffe(machine)
        self.griffe = machine.griffe
        self.fut = fut
        self.reglages = reglages
        self.godet_kg = 0.0
        self._arrivees: dict[str, float] = {}
        self._resultat: Resultat | None = None
        self._pas: Pas | None = None
        self._ouverture_prise = 1.0
        self.pretes = Condition("cartes simulées prêtes", lambda: True)
        self.surveillance = Condition("cartes simulées sans alarme", lambda: True)

    def position(self) -> Pose:
        return self.conversion.depuis_axes(
            {nom: self._etat.positions[nom] for nom in self.conversion.axes}
        )

    def _charge(self) -> float:
        return self.reglages.charge_vide_n + self.godet_kg * G

    def executer(self, pas: Pas, cible: Pose) -> None:
        depart = self.position()
        arrete = False
        if pas.arret_si_baisse_n is not None and cible.z < depart.z:
            # Où la tête s'arrête : sur le substrat (contact), sur le fond (poussée). Dans le
            # seau (tassement), le niveau n'est pas connu : appui après la marge de descente.
            if self.regles.au_dessus_du_fut(cible.x, cible.y):
                surface = self.fut.niveau if pas.contact else self.fut.fut.fut_fond_interieur_z
                arret = surface + self.griffe.bas_godet_sous_axes
            else:
                arret = depart.z - self.griffe.descente.marge_niveau_m
            if cible.z < arret:
                cible, arrete = cible.avec(z=min(arret, depart.z)), True
        if depart.b > 0 and cible.b < depart.b:
            self._fermer(depart, cible)
        elif cible.b > depart.b:
            self._ouvrir(cible)
        self._arrivees = self._etat.aller_vers(
            pas.texte, self.conversion.vers_axes(cible), self.conversion.vitesses(pas.vitesse)
        )
        if pas.attente_s:
            self._arrivees = self._etat.attendre(CARTE, pas.attente_s)
        self._pas = pas
        self._resultat = Resultat(
            pose=cible, arrete=arrete, charge_n=self._charge() if pas.pesee else None
        )

    def _fermer(self, depart: Pose, cible: Pose) -> None:
        """Le godet se ferme : il prend le substrat qu'il entoure (fermeture complète)."""
        if cible.b > 1e-6:
            if self.godet_kg == 0:
                self._ouverture_prise = cible.b
            return
        bas = cible.z - self.griffe.bas_godet_sous_axes
        enfonce = self.fut.niveau - bas
        if enfonce < 0 or not self.regles.dans_le_fut(cible):
            return
        ouverture = self._ouverture_prise if self.godet_kg == 0 else depart.b
        volume = volume_l(self.griffe.volumes, ouverture, enfonce)
        facteur = 1.0
        distance = self.regles.distance_axe_fut(cible.x, cible.y)
        if distance >= self.reglages.paroi_rayon_m:
            facteur = self.reglages.facteur_paroi
        if bas - self.fut.fut.fut_fond_interieur_z <= self.reglages.fond_hauteur_m:
            facteur = min(facteur, self.reglages.facteur_fond)
        if self.godet_kg == 0:
            prise = min(volume * self.reglages.densite_kg_l * facteur, self.fut.masse)
            self.godet_kg = prise
            self.fut.changer(-prise)
        else:
            # Entrouvert puis refermé : une partie est retombée.
            rendu = self.godet_kg * self.reglages.entrouvrir_rendu
            self.godet_kg -= rendu
            self.fut.changer(rendu)

    def _ouvrir(self, cible: Pose) -> None:
        if self.godet_kg == 0:
            self._ouverture_prise = cible.b
            return
        if cible.b < 0.5:
            return  # entrouvert : le reste est compté à la fermeture
        if self.regles.au_dessus_du_fut(cible.x, cible.y):
            self.fut.changer(self.godet_kg)
        else:
            self.fut.verse_kg += self.godet_kg
        self.godet_kg = 0.0
        self._ouverture_prise = cible.b

    def enchainer(self, poses: list[Pose], vitesse: str | None) -> None:
        for pose in poses:
            self._etat.aller_vers(
                "retrait", self.conversion.vers_axes(pose), self.conversion.vitesses(vitesse)
            )
        self._pas = None

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
    def choc(self) -> bool:
        return False

    def oublier_choc(self) -> None:
        pass


def griffe_du_simulateur(simulateur: Simulateur, **options: Any) -> Griffe:
    """La griffe sur la machine imaginaire, avec le poste du fût du simulateur : le fût
    imaginaire part du poids net pesé au « Prêt » et écrit son poids sur la fausse pesée.
    `options` : les cases vides de Griffe (machouiller, prochain_format...)."""
    reglages = simulateur.reglages
    machine = reglages.machine
    if reglages.simulateur.griffe is None:
        raise ErreurSimulation("simulateur.yaml n'a pas de partie « griffe »")
    poste = simulateur.poste_fut()
    pesee = poste.pesee
    if pesee is None:
        raise ErreurSimulation("pas de pesée du poste du fût (pesee_fut dans pesees.yaml, tour)")

    def regler_pesee(kg: float) -> None:
        # Seulement la mesure : une radio muette (scénario) le reste.
        simulateur.fabrique.regler_pesee(pesee.signal, pesee.brut(kg + pesee.reglages.tare_kg))

    fut = FutSimule(machine, reglages.simulateur.griffe, poste.poids_restant_kg, regler_pesee)
    bras = BrasSimule(simulateur.etat_axes, machine, fut, reglages.simulateur.griffe)
    return Griffe(machine, bras, poste, horloge=lambda: simulateur.temps, **options)
