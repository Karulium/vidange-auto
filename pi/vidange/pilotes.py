"""Les alarmes ALM des pilotes boucle fermée : un seul endroit pour toute la machine (tâche 24).

    pilotes = Pilotes(reglages.machine, reglages.fluidnc.cartes, liaisons)
    pilotes.en_alarme(["chariot_y"])          # textes des alarmes levées pour ces axes
    chef.surveillance_pilotes = pilotes.probleme_du_module   # un geste s'arrête si l'ALM se lève
    pilotes.attendre("prehension_a")          # une ALM voulue (vissage) : le chef l'ignore
    pilotes.remettre_a_zero("prehension_a")   # remise à zéro de l'ALM, ou ErreurEtape

La liste « axe → entrées alarme_* » est dans machine.yaml (pilotes → alarmes) ; la lettre de
chaque entrée dans « Pn: » est dans fluidnc.yaml. Le code ne cite aucun nom d'axe ni broche.
Plusieurs alarmes peuvent être câblées en OU sur une même entrée : on dit alors « l'un des
pilotes ... ».

Le pilote rattrape seul ses pas ; il lève ALM quand l'erreur de suivi dépasse son réglage (fait
sur le pilote, jamais ici). Le Pi ne lit jamais la position du codeur. Ces alarmes protègent la
MACHINE ; la sécurité des personnes reste câblée.
"""

import time
from collections.abc import Callable, Iterable, Mapping

from vidange.chef import ErreurEtape
from vidange.fluidnc import Liaison
from vidange.journal import donner_journal
from vidange.reglages import CarteFluidnc, Machine

journal = donner_journal("pilotes")

QUOI_FAIRE = (
    "Un pilote de moteur est en alarme (effort trop grand, moteur bloqué ou câble) : regarder "
    "ce qui bloque l'axe, sans desserrer le frein d'un Z. Dégager, couper puis remettre le "
    "courant du pilote (son voyant d'alarme s'éteint), puis acquitter et donner le Go."
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
    ) -> None:
        if machine.pilotes is None:
            raise ValueError("machine.yaml n'a pas de partie « pilotes »")
        self.reglages = machine.pilotes
        self._machine = machine
        self._liaisons = dict(liaisons)
        self._dormir = dormir
        self._horloge = horloge
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

    def axes_en_alarme(self, axes: Iterable[str]) -> list[str]:
        """Les axes de la liste dont une entrée d'alarme est active (même lettre partagée)."""
        return [
            axe
            for axe in axes
            if any(self._active(carte, lettre) for _, carte, lettre in self._entrees.get(axe, ()))
        ]

    def en_alarme(self, axes: Iterable[str]) -> list[str]:
        """Les textes des alarmes levées pour ces axes ; vide si tout va bien."""
        textes = []
        for axe in self.axes_en_alarme(axes):
            lettres = {
                (c, lettre) for _, c, lettre in self._entrees[axe] if self._active(c, lettre)
            }
            partages = sorted(
                {
                    autre
                    for autre, entrees in self._entrees.items()
                    for _, c, lettre in entrees
                    if (c, lettre) in lettres
                }
            )
            texte = (
                f"pilote de l'axe « {axe} »"
                if partages == [axe]
                else f"l'un des pilotes {', '.join(partages)} (alarmes câblées ensemble)"
            )
            if texte not in textes:
                textes.append(texte)
        return textes

    def axes_du_module(self, module: str) -> tuple[str, ...]:
        return tuple(self.reglages.modules.get(module, ()))

    def probleme_du_module(self, module: str) -> tuple[str, str] | None:
        """(message, quoi faire) si un pilote d'un axe du module est en alarme, sinon None.
        Les alarmes voulues (`attendre`) sont ignorées."""
        axes = [axe for axe in self.axes_du_module(module) if axe not in self.attendues]
        textes = self.en_alarme(axes)
        if not textes:
            return None
        message = f"alarme du pilote : {' ; '.join(textes)}"
        journal.error("Module « %s » : %s", module, message)
        return message, QUOI_FAIRE

    # ------------------------------------------------------------ alarme voulue et remise à zéro

    def attendre(self, axe: str) -> None:
        """L'ALM de cet axe est voulue (le moteur va caler pour finir un vissage)."""
        self.attendues.add(axe)

    def remettre_a_zero(self, axe: str) -> None:
        """Remet l'ALM de l'axe à zéro avec les lignes de pilotes → remise_a_zero, puis attend
        qu'elle retombe. Lève ErreurEtape si elle ne retombe pas."""
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
            fin = self._horloge() + remise.delai_max_s
            while self.axes_en_alarme([axe]):
                if self._horloge() >= fin:
                    raise ErreurEtape(
                        f"pilote de « {axe} » : l'alarme ne retombe pas en "
                        f"{remise.delai_max_s:g} s",
                        QUOI_FAIRE_REMISE,
                    )
                self._dormir(0.02)
        self.attendues.discard(axe)
