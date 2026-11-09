"""Dérive de position : contrôle d'origine d'un axe contre le fin de course (tâche 24, point 3).

    controle = ControleDerive(reglages.machine, liaisons)
    module = controle.module()          # module exclusif du chef ; None si inactif
    controle.constats()                 # alertes « dérive » pour la check-list et la page

Un moteur qui rattrape ses pas (boucle fermée) ne voit pas une courroie ou un pignon qui glisse :
FluidNC croit l'axe à une position, l'axe est ailleurs. Le contrôle mesure cet écart avec ce que
FluidNC donne tel qu'il est câblé : le fin de course d'origine de l'axe, lu dans « Pn: » (sa
lettre est celle de l'axe).
1. l'axe va à `distance_depart` avant la position où FluidNC croit son capteur ;
2. déplacement manuel lent (« $J= ») vers le capteur ; dès que « Pn: » le montre, le Pi lit la
   position du MÊME rapport d'état et arrête le déplacement (0x85) ;
3. écart = position lue − `position_capteur`. Au-delà de `seuil_alerte` : alerte (journal et
   check-list). Au-delà de `seuil_arret`, ou capteur jamais vu, ou déjà actif au départ : arrêt
   propre du module. Avec `recaler`, l'axe refait ensuite sa prise d'origine seul (« $H<lettre> »).
Précision de la mesure : vitesse × periode_etat_s.

Cette méthode ne demande aucun câblage de plus, mais suppose que FluidNC laisse l'axe passer son
fin de course d'origine à la main (`soft_limits` compris) : à vérifier à l'essai
(pi/systeme/essai-derive.md). C'est pourquoi `actif` est faux dans machine.yaml.
Ce contrôle protège la MACHINE (positions justes), jamais les personnes.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from vidange.chef import Axes, Condition, ErreurEtape, Etape, Module
from vidange.fiabilite.constats import Constat
from vidange.fluidnc import Commande, Liaison, protocole
from vidange.journal import donner_journal
from vidange.reglages import Derive, Machine

journal = donner_journal("derive")

NOM = "controle_origine"
SUJET = "dérive de position"
MM_PAR_M = 1000
# Marge au-delà du seuil d'arrêt avant de dire « capteur pas vu ».
MARGE = 1.2

QUOI_FAIRE_ARRET = (
    "Un axe a glissé (courroie ou pignon) de plus que le seuil d'arrêt : regarder la courroie et "
    "le pignon de l'axe, les resserrer ou les remplacer. Refaire ensuite la prise d'origine de "
    "l'axe (retour en lieu sûr), puis acquitter et donner le Go."
)
QUOI_FAIRE_CAPTEUR = (
    "Le fin de course d'origine de l'axe n'a pas répondu comme prévu (pas vu, ou déjà actif au "
    "départ) : regarder son voyant et son câble, puis la courroie et le pignon. Refaire la prise "
    "d'origine de l'axe, puis acquitter et donner le Go."
)
QUOI_FAIRE_ALERTE = (
    "Un axe a un peu glissé : surveiller la courroie et le pignon de cet axe, et les resserrer à "
    "la prochaine pause."
)


@dataclass
class _Mesure:
    # Écart mesuré (m ou °), ou None si le capteur n'a pas été vu.
    ecart: float | None
    # Raison quand il n'y a pas de mesure.
    raison: str = ""


class ControleDerive:
    def __init__(
        self,
        machine: Machine,
        liaisons: Mapping[str, Liaison],
    ) -> None:
        if machine.derive is None:
            raise ValueError("machine.yaml n'a pas de partie « derive »")
        self.machine = machine
        self.reglages: Derive = machine.derive
        self.liaisons = dict(liaisons)
        for nom in self.reglages.axes:
            carte = machine.axes[nom].carte
            if carte not in self.liaisons:
                raise ValueError(f"derive : pas de liaison pour la carte « {carte} » (axe {nom})")
        cartes = {machine.axes[nom].carte for nom in self.reglages.axes}
        self.axes = Axes(machine, {c: self.liaisons[c] for c in sorted(cartes) if c})
        self.mesures: dict[str, _Mesure] = {}
        # Dernière alerte par axe (écart en m ou °), pour la check-list.
        self.alertes: dict[str, float] = {}
        self._envoi: dict[str, tuple[Commande, int]] = {}

    # ------------------------------------------------------------ calculs

    def _facteur(self, axe: str) -> float:
        return MM_PAR_M if self.machine.axes[axe].unite == "m" else 1.0

    def _liaison(self, axe: str) -> Liaison:
        carte = self.machine.axes[axe].carte
        assert carte is not None
        return self.liaisons[carte]

    def _lettre(self, axe: str) -> str:
        lettre = self.machine.axes[axe].lettre
        assert lettre is not None
        return lettre

    def depart(self, axe: str) -> float:
        c = self.reglages.axes[axe]
        return c.position_capteur - c.sens * c.distance_depart

    def cible(self, axe: str) -> float:
        c = self.reglages.axes[axe]
        return c.position_capteur + c.sens * c.seuil_arret * MARGE

    def _position(self, axe: str) -> float | None:
        mm = self._liaison(axe).etat.positions.get(self._lettre(axe))
        return None if mm is None else mm / self._facteur(axe)

    # ------------------------------------------------------------ étapes

    def _aller_au_depart(self, axe: str) -> None:
        self.axes.aller_a({axe: self.depart(axe)}, f"depart_{axe}")

    def _approcher(self, axe: str) -> None:
        liaison, lettre = self._liaison(axe), self._lettre(axe)
        c = self.reglages.axes[axe]
        if lettre in liaison.etat.entrees_actives:
            self.mesures[axe] = _Mesure(None, "fin de course déjà actif au départ de l'approche")
            return
        facteur = self._facteur(axe)
        vitesse = c.vitesse * facteur * 60
        cible = self.cible(axe) * facteur
        ligne = f"{protocole.DEPLACEMENT_MANUEL}G53 G90 {lettre}{cible:.3f} F{vitesse:.1f}"
        self._envoi[axe] = (liaison.envoyer(ligne), liaison.etat.rapports_recus)
        self.mesures.pop(axe, None)

    def _approche_finie(self, axe: str) -> bool:
        if axe in self.mesures:
            return True
        liaison, lettre = self._liaison(axe), self._lettre(axe)
        commande, rapports = self._envoi[axe]
        if commande.erreur is not None:
            raise ErreurEtape(
                f"contrôle d'origine de « {axe} » : déplacement refusé ({commande.erreur})",
                QUOI_FAIRE_CAPTEUR,
            )
        etat = liaison.etat
        if etat.rapports_recus <= rapports:
            return False
        position = self._position(axe)
        if lettre in etat.entrees_actives and position is not None:
            liaison.annuler_deplacement()
            self.mesures[axe] = _Mesure(position - self.reglages.axes[axe].position_capteur)
            return True
        if commande.finie and etat.etat == "Idle" and position is not None:
            if abs(position - self.cible(axe)) * self._facteur(axe) < 0.5:
                self.mesures[axe] = _Mesure(
                    None, "fin de course jamais vu avant la fin de l'approche"
                )
                return True
        return False

    def _juger(self, axe: str) -> None:
        mesure = self.mesures[axe]
        c = self.reglages.axes[axe]
        unite = self.machine.axes[axe].unite
        if mesure.ecart is None:
            journal.error("Dérive, axe %s : %s", axe, mesure.raison)
            raise ErreurEtape(f"dérive de « {axe} » : {mesure.raison}", QUOI_FAIRE_CAPTEUR)
        ecart = abs(mesure.ecart)
        if ecart > c.seuil_arret:
            journal.error(
                "Dérive, axe %s : %.4g %s (arrêt au-delà de %g)", axe, ecart, unite, c.seuil_arret
            )
            self.alertes[axe] = ecart
            raise ErreurEtape(
                f"dérive de « {axe} » : {ecart:.4g} {unite}, au-delà du seuil d'arrêt "
                f"({c.seuil_arret:g} {unite})",
                QUOI_FAIRE_ARRET,
            )
        if ecart > c.seuil_alerte:
            journal.warning(
                "Dérive, axe %s : %.4g %s (alerte au-delà de %g)", axe, ecart, unite, c.seuil_alerte
            )
            self.alertes[axe] = ecart
        else:
            journal.info("Dérive, axe %s : %.4g %s, dans la tolérance", axe, ecart, unite)
            self.alertes.pop(axe, None)
        if self.reglages.recaler:
            self._liaison(axe).envoyer(f"{protocole.PRISE_ORIGINE}{self._lettre(axe)}")
            journal.info("Dérive, axe %s : prise d'origine de l'axe seul pour le recaler", axe)

    # ------------------------------------------------------------ module et constats

    def module(self) -> Module | None:
        """Le module exclusif du chef (mesure de chaque axe), ou None si le contrôle est inactif."""
        if not self.reglages.actif:
            return None
        delai = self.reglages.delai
        etapes: list[Etape] = []
        for axe in self.reglages.axes:
            etapes += [
                Etape(
                    f"{axe}_depart",
                    QUOI_FAIRE_CAPTEUR,
                    action=lambda axe=axe: self._aller_au_depart(axe),
                    fin=self.axes.arrives,
                    delai_max=delai,
                    entree=(self.axes.pretes,),
                ),
                Etape(
                    f"{axe}_approche",
                    QUOI_FAIRE_CAPTEUR,
                    action=lambda axe=axe: self._approcher(axe),
                    fin=Condition(
                        f"fin de course d'origine de « {axe} » vu",
                        lambda axe=axe: self._approche_finie(axe),
                    ),
                    delai_max=delai,
                ),
                Etape(f"{axe}_juger", QUOI_FAIRE_ARRET, action=lambda axe=axe: self._juger(axe)),
            ]
        return Module(
            nom=NOM,
            etapes=tuple(etapes),
            surveillances=(self.axes.surveillance,),
            pauser=self.axes.pauser,
            reprendre=self.axes.reprendre,
            arreter=self._arreter,
            exclusif=True,
        )

    def _arreter(self) -> None:
        liaisons = {id(x): x for x in (self._liaison(a) for a in self.reglages.axes)}
        for liaison in liaisons.values():
            liaison.annuler_deplacement()
        self.axes.pauser()

    def constats(self) -> list[Constat]:
        """Pour la check-list : une alerte par axe qui a glissé au dernier contrôle."""
        return [
            Constat(
                SUJET,
                "attention",
                f"axe « {axe} » : écart d'origine de {ecart:.4g}",
                QUOI_FAIRE_ALERTE,
            )
            for axe, ecart in self.alertes.items()
        ]
