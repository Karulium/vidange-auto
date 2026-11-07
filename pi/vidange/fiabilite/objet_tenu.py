"""Reprise après une coupure avec un objet encore tenu à la ventouse (tâche 45 nonies).

    objet_tenu = ObjetTenu(vide, lire=lambda: materiel.mesurer("vide_venturi"))
    objet_tenu.regarder()               # au démarrage, AVANT tout mouvement
    chef.empecher_go(objet_tenu.refus_go)
    objet_tenu.demarrer(arret)          # relu jusqu'à ce que l'objet soit enlevé à la main
    objet_tenu.constats()               # pour la check-list

Réponse du fil Préhension (07/11/2026) : les électrovannes « aspirer » et « souffler » sont
normalement fermées et un clapet anti-retour garde le vide. À une coupure, l'objet tenu à la
ventouse (seau, couvercle, Pétri) reste d'abord tenu, puis peut tomber au bout d'un temps inconnu
(sous la face 0,545, un couvercle C tomberait de travers sur le seau). Un objet tenu par les
électroaimants (capsule, bocal par son couvercle percé) tombe tout de suite.

Au démarrage, avant tout mouvement, le Pi lit le capteur de vide de la préhension : la moyenne de
`zero_lectures` lectures brutes (le zéro n'est pas encore recalé : il ne l'est qu'au départ d'un
lot, vanne fermée, et il est à ± `zero_ecart_max_kpa` de 0). Plus bas que
`prehension → vide → tenu_au_demarrage_kpa` (−20 kPa), quelque chose est encore tenu : l'écran et
la page disent « objet encore tenu », et le chef refuse TOUT Go (retour en lieu sûr, reprise du
cycle, lot) ainsi que le pilotage à distance, tant que c'est le cas. Le capteur est relu tous les
`fiabilite → objet_tenu → periode_s` ; dès que le vide est remonté au-dessus du seuil (Karulium a
enlevé l'objet à la main), l'attente est finie pour toute cette marche du programme : ensuite, la
ventouse tient des objets en travail, ce n'est plus une reprise.

JAMAIS de « souffler » ni de mouvement automatique au redémarrage : rien n'est commandé ici (la
vanne n'est pas touchée). Sans capteur de vide (signal absent de la liste, ligne en EXEMPLE sur la
vraie machine, entrées/sorties pas ouvertes) ou s'il ne répond pas, le Pi ne peut pas savoir : il
n'attend pas, mais la check-list le dit (« vérifier la tête à la main avant le Go »).

Cette attente protège la machine et le seau, jamais les personnes : la sécurité est câblée.
"""

import threading
from collections.abc import Callable
from statistics import fmean

from vidange.fiabilite.constats import Constat, lancer_boucle
from vidange.journal import donner_journal
from vidange.reglages import VidePrehension

journal = donner_journal("fiabilite.objet_tenu")

SUJET = "objet tenu à la ventouse"
QUOI_FAIRE = (
    "Vérifier la tête de préhension et le seau : enlever à la main l'objet encore tenu ou tombé "
    "(décoller un bord de la ventouse pour laisser entrer l'air). Le Go revient seul dès que le "
    "vide est remonté."
)
QUOI_FAIRE_INCONNU = (
    "Le Pi ne sait pas si la ventouse tient encore quelque chose : vérifier la tête de préhension "
    "et le seau, et enlever à la main l'objet tenu ou tombé avant le Go."
)


class ObjetTenu:
    def __init__(
        self,
        reglages: VidePrehension,
        lire: Callable[[], float] | None,
        periode_s: float,
        absent: str | None = None,
    ) -> None:
        """`lire` : une lecture brute du capteur de vide (kPa) ; None avec `absent` (pourquoi il
        n'est pas lu)."""
        self.seuil_kpa = reglages.tenu_au_demarrage_kpa
        self.lectures = reglages.zero_lectures
        self.periode_s = periode_s
        self._lire = lire
        self._verrou = threading.Lock()
        # Pourquoi le capteur n'est pas lu (None : il l'est).
        self.inconnu: str | None = None if lire is not None else (absent or "pas de capteur")
        # Dernière moyenne lue (kPa, brute), ou None.
        self.vide_kpa: float | None = None
        # Plus rien à attendre : vide remonté au-dessus du seuil, ou capteur pas lisible.
        self.libere = lire is None

    @property
    def tenu(self) -> bool:
        """Un objet est encore tenu (vu au redémarrage, pas encore enlevé)."""
        return not self.libere and self.vide_kpa is not None and self.vide_kpa < self.seuil_kpa

    def regarder(self) -> None:
        """Une mesure (moyenne de `lectures` lectures brutes). Ne commande rien."""
        if self.libere or self._lire is None:
            return
        try:
            vide = fmean(self._lire() for _ in range(self.lectures))
        except Exception as erreur:
            with self._verrou:
                self.inconnu = f"capteur de vide illisible ({erreur})"
                self.libere = True
            journal.error(
                "Reprise : capteur de vide illisible (%s) ; vérifier la tête à la main", erreur
            )
            return
        with self._verrou:
            avant = self.vide_kpa
            self.vide_kpa = vide
            if vide < self.seuil_kpa:
                if avant is None:
                    journal.warning(
                        "Reprise : objet encore tenu à la ventouse (vide %.1f kPa, plus bas que "
                        "%g) : pas de Go tant qu'il n'est pas enlevé à la main",
                        vide,
                        self.seuil_kpa,
                    )
                return
            self.libere = True
        if avant is not None:
            journal.info(
                "Reprise : la ventouse ne tient plus rien (vide %.1f kPa) : Go permis", vide
            )

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        return lancer_boucle("objet_tenu", self.periode_s, self._tour, arret)

    def _tour(self) -> None:
        if not self.libere:
            self.regarder()

    def refus_go(self) -> str | None:
        """Pourquoi aucun Go n'est accepté (objet encore tenu), ou None. Rapide : la dernière
        mesure, sans lire le capteur."""
        with self._verrou:
            if not self.tenu:
                return None
            vide = self.vide_kpa
        assert vide is not None
        return f"objet encore tenu à la ventouse (vide {vide:.0f} kPa) : l'enlever à la main"

    def constats(self) -> list[Constat]:
        refus = self.refus_go()
        if refus is not None:
            return [Constat(SUJET, "bloquant", refus, QUOI_FAIRE)]
        if self.inconnu is not None:
            return [Constat(SUJET, "attention", self.inconnu, QUOI_FAIRE_INCONNU)]
        return [Constat(SUJET, "ok", "rien de tenu au redémarrage (ou enlevé à la main)")]
