"""Arrêt propre sur onduleur (fonction 4).

L'onduleur donne une entrée « onduleur_sur_batterie » (liste des entrées/sorties) : actionnée
quand le courant du secteur est coupé et que le Pi tient sur la batterie.

- Courant coupé : la machine se met en pause tout de suite (les axes s'arrêtent sans perdre
  leur position ; l'état est noté dans le carnet).
- Courant revenu avant le délai : la machine **reste en pause** ; Karulium la reprend quand
  il a vérifié (rien ne repart tout seul).
- Courant coupé depuis « delai_avant_arret_s » : le programme s'arrête proprement (état noté,
  registre fermé), puis lance la commande qui éteint le Pi.

Sans ce signal dans la liste, rien n'est surveillé : une coupure arrête le Pi net
(le carnet permet quand même la reprise ; voir la check-list).
"""

import threading
import time
from collections.abc import Callable

from vidange.chef import Chef
from vidange.fiabilite.constats import Constat, lancer_boucle
from vidange.journal import donner_journal
from vidange.materiel import ErreurMateriel, Materiel
from vidange.reglages import ReglagesOnduleur

journal = donner_journal("fiabilite.onduleur")

SIGNAL = "onduleur_sur_batterie"
RAISON_ARRET = "onduleur"


class Onduleur:
    def __init__(
        self,
        reglages: ReglagesOnduleur,
        materiel: Materiel | None,
        chef: Chef | None,
        demander_arret: Callable[[str], None],
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        """`demander_arret(raison)` : arrête le programme proprement (puis le Pi s'éteint)."""
        self.reglages = reglages
        self.materiel = materiel
        self.chef = chef
        self._demander_arret = demander_arret
        self._horloge = horloge
        self.coupe_depuis: float | None = None
        self.arret_demande = False
        self._erreur: str | None = None

    @property
    def branche(self) -> bool:
        return self.materiel is not None and SIGNAL in self.materiel.branchements

    def tour(self) -> None:
        if not self.branche or self.arret_demande:
            return
        try:
            coupe = self.materiel.lire(SIGNAL)
        except ErreurMateriel as erreur:
            if self._erreur is None:
                journal.error("Onduleur illisible : %s", erreur)
            self._erreur = str(erreur)
            return
        self._erreur = None
        maintenant = self._horloge()
        if not coupe:
            if self.coupe_depuis is not None:
                journal.warning(
                    "Courant revenu après %.0f s. La machine reste en pause : la reprendre "
                    "quand tout est vérifié.",
                    maintenant - self.coupe_depuis,
                )
                self.coupe_depuis = None
            return
        if self.coupe_depuis is None:
            self.coupe_depuis = maintenant
            journal.error(
                "Courant coupé : le Pi tient sur l'onduleur. Machine en pause ; arrêt propre "
                "du Pi dans %g s si le courant ne revient pas.",
                self.reglages.delai_avant_arret_s,
            )
            if self.chef is not None:
                self.chef.pause()
        if maintenant - self.coupe_depuis >= self.reglages.delai_avant_arret_s:
            journal.error("Courant toujours coupé : arrêt propre du programme, puis du Pi.")
            self.arret_demande = True
            self._demander_arret(RAISON_ARRET)

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        return lancer_boucle("onduleur", self.reglages.periode_s, self.tour, arret)

    def constats(self) -> list[Constat]:
        sujet = "onduleur"
        if not self.branche:
            return [
                Constat(
                    sujet,
                    "attention",
                    f"pas de signal « {SIGNAL} » : une coupure de courant arrête le Pi net",
                    "Brancher l'onduleur et ajouter son signal à la liste des entrées/sorties.",
                )
            ]
        if self._erreur is not None:
            return [
                Constat(sujet, "attention", f"illisible : {self._erreur}", "Vérifier son câble.")
            ]
        if self.coupe_depuis is not None:
            return [
                Constat(
                    sujet,
                    "bloquant",
                    "courant du secteur coupé : le Pi tient sur la batterie",
                    "Attendre le retour du courant avant de lancer un cycle.",
                )
            ]
        return [Constat(sujet, "ok", "courant du secteur présent")]
