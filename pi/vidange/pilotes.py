"""Les alarmes ALM des pilotes boucle fermée : un seul endroit pour toute la machine (tâche 24).

    pilotes = Pilotes(reglages.machine, reglages.fluidnc.cartes, liaisons)
    pilotes.en_alarme(["chariot_y"])          # textes des alarmes levées pour ces axes
    chef.surveillance_pilotes = pilotes.probleme_du_module   # un geste s'arrête si l'ALM se lève
    pilotes.attendre("prehension_a")          # une ALM voulue (vissage) : le chef l'ignore, ainsi
                                              # que celle des autres pilotes de la même carte
    pilotes.remettre_a_zero("prehension_a")   # remise à zéro de l'ALM, ou ErreurEtape

La liste « axe → entrée alarme_* » est dans machine.yaml (pilotes → alarmes) ; la lettre de
chaque entrée dans « Pn: » est dans fluidnc.yaml. Le code ne cite aucun nom d'axe ni broche.
Depuis la tâche 24 bis, il y a UNE entrée d'alarme par carte FluidNC : les ALM de tous ses pilotes
y sont câblés ensemble (en série ou en parallèle : le sens est un réglage de la broche dans
fluidnc/<carte>.yaml). Le Pi sait qu'un pilote de la carte est en alarme, pas lequel : on le dit
(« un pilote de la carte ... ») et on renvoie aux voyants des pilotes.

Le pilote rattrape seul ses pas ; il lève ALM quand l'erreur de suivi dépasse son réglage (fait
sur le pilote, jamais ici). Le Pi ne lit jamais la position du codeur. Ces alarmes protègent la
MACHINE ; la sécurité des personnes reste câblée.
"""

import time
from collections.abc import Callable, Iterable, Mapping
from typing import Protocol

from vidange.chef import ErreurEtape
from vidange.fluidnc import Liaison
from vidange.journal import donner_journal
from vidange.reglages import CarteFluidnc, Machine


class RelaisDuPi(Protocol):
    def ecrire(self, nom: str, commande: bool) -> None: ...


journal = donner_journal("pilotes")

QUOI_FAIRE = (
    "Un pilote de moteur est en alarme (effort trop grand, moteur bloqué ou câble). Le Pi ne sait "
    "pas lequel : regarder les voyants des pilotes de la carte indiquée, puis ce qui bloque l'axe "
    "concerné, sans desserrer le frein d'un Z. Dégager, couper puis remettre le courant du pilote "
    "(son voyant d'alarme s'éteint), puis acquitter et donner le Go."
)
QUOI_FAIRE_REMISE = (
    "L'alarme du pilote ne retombe pas : couper puis remettre le courant du pilote (voyant "
    "d'alarme éteint), puis acquitter et donner le Go. Si cela revient à chaque fois, la façon "
    "de la remettre à zéro est à revoir (pilotes → remise_a_zero dans machine.yaml)."
)


class Pilotes:
    def __init__(
        self,
        machine: Machine,
        cartes: Mapping[str, CarteFluidnc],
        liaisons: Mapping[str, Liaison],
        dormir: Callable[[float], None] = time.sleep,
        horloge: Callable[[], float] = time.monotonic,
        relais: RelaisDuPi | None = None,
    ) -> None:
        if machine.pilotes is None:
            raise ValueError("machine.yaml n'a pas de partie « pilotes »")
        self.reglages = machine.pilotes
        self._machine = machine
        self._liaisons = dict(liaisons)
        self._dormir = dormir
        self._horloge = horloge
        self._relais = relais
        coupure = self.reglages.remise_a_zero.coupure
        if coupure is not None and coupure.actif and relais is None:
            raise ValueError(
                "machine.yaml, pilotes → remise_a_zero → coupure est actif, mais le Pi n'a pas la "
                "carte des relais (docs/entrees-sorties.yaml)"
            )
        # Axe → [(signal, carte, lettre)].
        self._entrees: dict[str, list[tuple[str, str, str]]] = {}
        for axe, signaux in self.reglages.alarmes.items():
            carte = machine.axes[axe].carte
            assert carte is not None
            for signal in signaux:
                lettre = cartes[carte].entrees.get(signal)
                if lettre is None:
                    raise ValueError(f"fluidnc.yaml : il manque « {signal} » (carte « {carte} »)")
                self._entrees.setdefault(axe, []).append((signal, carte, lettre))
        # Axes dont l'ALM est voulue en ce moment (vissage qui cale).
        self.attendues: set[str] = set()

    # ------------------------------------------------------------ lecture

    def _active(self, carte: str, lettre: str) -> bool:
        liaison = self._liaisons.get(carte)
        if liaison is None:
            return False
        etat = liaison.etat
        return etat.connectee and etat.etat is not None and lettre in etat.entrees_actives

    def _masquees(self) -> set[tuple[str, str]]:
        """Les entrées (carte, lettre) dont l'ALM est voulue en ce moment : elles masquent aussi
        les autres pilotes de la même carte, qu'on ne peut pas séparer."""
        return {
            (carte, lettre)
            for axe in self.attendues
            for _, carte, lettre in self._entrees.get(axe, ())
        }

    def axes_en_alarme(self, axes: Iterable[str], *, sans_voulues: bool = False) -> list[str]:
        """Les axes de la liste dont une entrée d'alarme est active (même lettre partagée).
        `sans_voulues` : les entrées d'une alarme voulue (`attendre`) ne comptent pas."""
        masquees = self._masquees() if sans_voulues else set()
        return [
            axe
            for axe in axes
            if any(
                self._active(carte, lettre)
                for _, carte, lettre in self._entrees.get(axe, ())
                if (carte, lettre) not in masquees
            )
        ]

    def en_alarme(self, axes: Iterable[str], *, sans_voulues: bool = False) -> list[str]:
        """Les textes des alarmes levées pour ces axes ; vide si tout va bien."""
        textes = []
        masquees = self._masquees() if sans_voulues else set()
        for axe in self.axes_en_alarme(axes, sans_voulues=sans_voulues):
            lettres = {
                (c, lettre)
                for _, c, lettre in self._entrees[axe]
                if self._active(c, lettre) and (c, lettre) not in masquees
            }
            partages = sorted(
                {
                    autre
                    for autre, entrees in self._entrees.items()
                    for _, c, lettre in entrees
                    if (c, lettre) in lettres
                }
            )
            cartes = sorted({c for c, _ in lettres})
            texte = (
                f"pilote de l'axe « {axe} »"
                if partages == [axe]
                else f"un pilote de la carte « {', '.join(cartes)} » (axes {', '.join(partages)} : "
                "on ne sait pas lequel, regarder les voyants des pilotes)"
            )
            if texte not in textes:
                textes.append(texte)
        return textes

    def axes_du_module(self, module: str) -> tuple[str, ...]:
        return tuple(self.reglages.modules.get(module, ()))

    def probleme_du_module(self, module: str) -> tuple[str, str] | None:
        """(message, quoi faire) si un pilote d'un axe du module est en alarme, sinon None.
        Les alarmes voulues (`attendre`) sont ignorées, avec celles des pilotes de leur carte."""
        textes = self.en_alarme(self.axes_du_module(module), sans_voulues=True)
        if not textes:
            return None
        message = f"alarme du pilote : {' ; '.join(textes)}"
        journal.error("Module « %s » : %s", module, message)
        return message, QUOI_FAIRE

    # ------------------------------------------------------------ alarme voulue et remise à zéro

    def attendre(self, axe: str) -> None:
        """L'ALM de cet axe est voulue (le moteur va caler pour finir un vissage)."""
        self.attendues.add(axe)

    def _attendre_retombee(self, axe: str, delai_s: float) -> bool:
        """Vrai si l'alarme de l'axe retombe dans le délai."""
        fin = self._horloge() + delai_s
        while self.axes_en_alarme([axe]):
            if self._horloge() >= fin:
                return False
            self._dormir(0.02)
        return True

    def _couper_le_courant(self, axe: str) -> bool:
        """2e essai : coupe puis remet l'alimentation du pilote de l'axe par le relais du Pi
        (pilotes → remise_a_zero → coupure). Faux s'il n'est pas prévu pour cet axe."""
        coupure = self.reglages.remise_a_zero.coupure
        if coupure is None or not coupure.actif or axe not in coupure.sorties:
            return False
        signal = coupure.sorties[axe]
        assert self._relais is not None
        journal.warning("Pilote de « %s » : coupure de son alimentation (%s)", axe, signal)
        try:
            self._relais.ecrire(signal, True)
            self._dormir(coupure.duree_s)
        except Exception as erreur:
            raise ErreurEtape(
                f"pilote de « {axe} » : coupure de l'alimentation impossible ({erreur})",
                QUOI_FAIRE_REMISE,
            ) from erreur
        finally:
            try:
                self._relais.ecrire(signal, False)
            except Exception:
                journal.exception("Pilote de « %s » : impossible de remettre le courant", axe)
        self._dormir(coupure.attente_retour_s)
        return True

    def remettre_a_zero(self, axe: str) -> None:
        """Remet l'ALM de l'axe à zéro avec les lignes de pilotes → remise_a_zero, puis attend
        qu'elle retombe ; sinon, si c'est prévu, 2e essai en coupant le courant du pilote. Lève
        ErreurEtape si elle ne retombe pas."""
        remise = self.reglages.remise_a_zero
        carte = self._machine.axes[axe].carte
        liaison = self._liaisons.get(carte or "")
        if liaison is None:
            raise ErreurEtape(f"pilote de « {axe} » : carte pas reliée", QUOI_FAIRE_REMISE)
        if self.axes_en_alarme([axe]):
            journal.info("Pilote de « %s » : remise à zéro de l'alarme", axe)
            for ligne in remise.lignes:
                commande = liaison.envoyer(ligne)
                self._dormir(remise.attente_s)
                if commande.finie and commande.erreur is not None:
                    raise ErreurEtape(
                        f"pilote de « {axe} » : « {ligne} » refusée ({commande.erreur})",
                        QUOI_FAIRE_REMISE,
                    )
            if not self._attendre_retombee(axe, remise.delai_max_s):
                essai = self._couper_le_courant(axe)
                if not essai or not self._attendre_retombee(axe, remise.delai_max_s):
                    raise ErreurEtape(
                        f"pilote de « {axe} » : l'alarme ne retombe pas en "
                        f"{remise.delai_max_s:g} s"
                        + (" (même après la coupure du courant)" if essai else ""),
                        QUOI_FAIRE_REMISE,
                    )
        self.attendues.discard(axe)
