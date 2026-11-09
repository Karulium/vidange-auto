"""Estimation de fin d'un lot qui apprend (tâche 30, fonction 7).

    estimation = Estimation(reglages.programme.estimation, registre, lot_en_cours, base)
    chef.sur_etape_finie.append(estimation.sur_etape_finie)   # garde les vraies durées
    estimation.calculer()                                     # l'estimation du lot qui tourne

Comment elle est calculée :
1. La base : le simulateur rejoue le lot (même code que la machine) et donne le temps total et,
   pour chaque geste (« module.etape »), sa durée simulée et son nombre de passages. Sans
   historique, c'est tout : l'estimation est le calcul du simulateur.
2. Le registre garde la VRAIE durée de chaque geste fini (sans les attentes ni les pauses), par
   format de seau. Pour chaque geste, rapport = moyenne glissante des dernières vraies durées /
   durée simulée, borné (réglages), et seulement si assez de durées vraies existent.
3. Rapport du lot = moyenne des rapports pondérée par le poids de chaque geste dans le lot
   simulé ; un geste sans historique pèse avec un rapport de 1.
4. Avancement = part des gestes déjà faits dans ce lot, pondérée de la même façon. Temps restant
   = temps total simulé × rapport du lot × (1 - avancement). Les attentes du Go et les pauses ne
   sont pas prévues (elles s'ajoutent).
5. Fourchette : écart relatif des vraies durées (pondéré), entre deux bornes (réglages) ; sans
   historique, une grande fourchette fixe.

C'est une INFORMATION : elle ne règle rien et ne protège rien.
"""

import statistics
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from vidange.journal import donner_journal
from vidange.registre.base import Registre
from vidange.reglages import ReglagesEstimation
from vidange.simulateur.planning import Planning, duree_lisible

if TYPE_CHECKING:
    from vidange.entrees_sorties import EntreesSorties
    from vidange.reglages import Reglages

journal = donner_journal("estimation")

# Un geste simulé plus court que cela n'apprend rien (division par presque zéro) : rapport de 1.
SIMULE_MIN_S = 0.05


@dataclass(frozen=True)
class BaseSimulee:
    """Ce que le simulateur dit d'un lot : temps total, et pour chaque geste sa durée totale
    simulée et son nombre de passages."""

    temps_total_s: float
    par_geste: dict[str, tuple[float, int]] = field(default_factory=dict)
    # Réglages d'exemple (valeurs inventées) : dit dans le texte.
    exemple: bool = False


def base_depuis_planning(
    planning: Planning, facteur: float = 1.0, exemple: bool = False
) -> BaseSimulee:
    """La base d'un planning du simulateur. `facteur` : lot simulé plus court que le vrai lot
    (les durées et les passages sont mis à l'échelle)."""
    cumul: dict[str, tuple[float, int]] = {}
    for ligne in planning.lignes:
        if ligne.fin is None:
            continue
        somme, nombre = cumul.get(f"{ligne.module}.{ligne.etape}", (0.0, 0))
        cumul[f"{ligne.module}.{ligne.etape}"] = (somme + ligne.geste, nombre + 1)
    return BaseSimulee(
        planning.temps_total * facteur,
        {
            cle: (somme * facteur, max(1, round(nombre * facteur)))
            for cle, (somme, nombre) in cumul.items()
        },
        exemple,
    )


def base_du_simulateur(
    reglages: "Reglages", liste: "EntreesSorties", format: str, nombre: int
) -> BaseSimulee:
    """Le simulateur rejoue un lot de `nombre` seaux de ce format (au plus ce que les piles
    imaginaires de simulateur.yaml portent ; le reste est mis à l'échelle). ErreurSimulation ou
    ErreurChef si le lot simulé est impossible."""
    from vidange.cycle.simulation import jouer_cycle
    from vidange.simulateur.simulateur import ErreurSimulation, Simulateur

    cycle = reglages.simulateur.cycle
    if cycle is None:
        raise ErreurSimulation("simulateur.yaml n'a pas de partie « cycle »")
    portent = sum(pile.nombre for pile in cycle.piles.values())
    simules = max(1, min(nombre, portent))
    piles = {nom: pile.model_copy(update={"format": format}) for nom, pile in cycle.piles.items()}
    cycle = cycle.model_copy(update={"format": format, "seaux": simules, "piles": piles})
    simulateur_reglages = reglages.simulateur.model_copy(update={"cycle": cycle})
    reglages = reglages.model_copy(update={"simulateur": simulateur_reglages})
    with Simulateur(reglages, liste, "cycle") as simulateur:
        _, planning, _ = jouer_cycle(simulateur)
    if not planning.fini:
        raise ErreurSimulation(f"lot simulé arrêté : {planning.probleme}")
    return base_depuis_planning(planning, nombre / simules, reglages.simulateur.exemple)


class Estimation:
    def __init__(
        self,
        reglages: ReglagesEstimation,
        registre: Registre,
        lot_en_cours: Callable[[], tuple[str, int, object] | None],
        base: Callable[[str, int], BaseSimulee],
        horloge: Callable[[], datetime] = datetime.now,
        en_fond: bool = True,
    ) -> None:
        """`lot_en_cours` : (format, nombre de seaux, identité du lot) du lot de seaux qui tourne,
        ou None. `base(format, nombre)` : la base du simulateur (lève une erreur si impossible).
        `en_fond` : la base se calcule dans un fil à part (elle dure quelques secondes)."""
        self.reglages = reglages
        self._registre = registre
        self._lot_en_cours = lot_en_cours
        self._base = base
        self._horloge = horloge
        self._en_fond = en_fond
        self._verrou = threading.RLock()
        self._identite: object = None
        self._faites: Counter[str] = Counter()
        # (format, nombre) → base, ou le texte de l'erreur ; ou absent (pas encore demandée).
        self._bases: dict[tuple[str, int], BaseSimulee | str] = {}
        self._en_calcul: set[tuple[str, int]] = set()
        self._derniere: tuple[datetime, dict[str, Any] | None] | None = None

    # ------------------------------------------------------------ ce que le chef raconte

    def sur_etape_finie(self, module: str, etape: str, duree_s: float) -> None:
        """Appelée par le chef (chef.sur_etape_finie) : compte le geste fait et garde sa durée."""
        if not self.reglages.actif:
            return
        lot = self._lot_en_cours()
        if lot is None:
            return
        format, _, identite = lot
        cle = f"{module}.{etape}"
        with self._verrou:
            self._suivre(identite)
            self._faites[cle] += 1
        if duree_s < self.reglages.duree_min_s:
            return
        try:
            self._registre.noter_duree_geste(
                cle, round(duree_s, 3), format, self.reglages.garde_par_geste
            )
        except Exception:
            journal.exception("Durée du geste « %s » pas gardée au registre", cle)

    def _suivre(self, identite: object) -> None:
        if identite is not self._identite:
            self._identite = identite
            self._faites = Counter()

    # ------------------------------------------------------------ la base du simulateur

    def _obtenir_base(self, format: str, nombre: int) -> BaseSimulee | str | None:
        """La base, le texte de son erreur, ou None (calcul en cours dans un fil à part)."""
        cle = (format, nombre)
        with self._verrou:
            if cle in self._bases:
                return self._bases[cle]
            if cle in self._en_calcul:
                return None
            self._en_calcul.add(cle)
        if self._en_fond:
            threading.Thread(
                target=self._calculer_base, args=(cle,), name="estimation", daemon=True
            ).start()
            return None
        self._calculer_base(cle)
        return self._bases[cle]

    def _calculer_base(self, cle: tuple[str, int]) -> None:
        try:
            resultat: BaseSimulee | str = self._base(*cle)
        except Exception as erreur:
            journal.warning("Estimation : le simulateur n'a pas pu rejouer ce lot : %s", erreur)
            resultat = f"le simulateur n'a pas pu rejouer ce lot ({erreur})"
        with self._verrou:
            self._bases[cle] = resultat
            self._en_calcul.discard(cle)

    # ------------------------------------------------------------ l'estimation

    def calculer(self) -> dict[str, Any] | None:
        """L'estimation du lot de seaux qui tourne (None : aucun lot, ou estimation coupée)."""
        if not self.reglages.actif:
            return None
        lot = self._lot_en_cours()
        if lot is None:
            return None
        format, nombre, identite = lot
        maintenant = self._horloge()
        with self._verrou:
            self._suivre(identite)
            if self._derniere is not None and (
                maintenant - self._derniere[0] < timedelta(seconds=self.reglages.rafraichir_s)
            ):
                return self._derniere[1]
            base = self._obtenir_base(format, nombre)
            if base is None:
                return {
                    "disponible": False,
                    "texte": "Fin du lot : calcul de l'estimation en cours.",
                }
            if isinstance(base, str):
                return {
                    "disponible": False,
                    "texte": f"Fin du lot : estimation impossible, {base}.",
                }
            resultat = self._estimer(base, format, maintenant)
            self._derniere = (maintenant, resultat)
            return resultat

    def _estimer(self, base: BaseSimulee, format: str, maintenant: datetime) -> dict[str, Any]:
        reglages = self.reglages
        poids_total = sum(somme for somme, _ in base.par_geste.values())
        corriges = 0
        somme_rapports = 0.0
        ecarts: list[tuple[float, float]] = []
        fait = 0.0
        for cle, (somme, nombre) in base.par_geste.items():
            moyenne_simulee = somme / nombre
            fait += min(self._faites[cle], nombre) * moyenne_simulee
            rapport = 1.0
            vraies = self._registre.durees_du_geste(cle, format, reglages.moyenne_sur)
            if len(vraies) >= reglages.mesures_min and moyenne_simulee > SIMULE_MIN_S:
                moyenne = statistics.fmean(vraies)
                rapport = min(
                    max(moyenne / moyenne_simulee, reglages.correction_min), reglages.correction_max
                )
                corriges += 1
                if len(vraies) >= 2 and moyenne > 0:
                    ecarts.append((somme, statistics.stdev(vraies) / moyenne))
            somme_rapports += rapport * somme
        rapport_du_lot = somme_rapports / poids_total if poids_total > 0 else 1.0
        avancement = min(fait / poids_total, 1.0) if poids_total > 0 else 0.0
        reste = max(base.temps_total_s * rapport_du_lot * (1 - avancement), 0.0)
        if ecarts:
            poids = sum(p for p, _ in ecarts)
            pct = 100 * sum(p * e for p, e in ecarts) / poids
            pct = min(max(pct, reglages.fourchette_min_pct), reglages.fourchette_max_pct)
        else:
            pct = reglages.fourchette_sans_historique_pct
        bas, haut = reste * (1 - pct / 100), reste * (1 + pct / 100)
        fin = maintenant + timedelta(seconds=reste)
        source = (
            f"corrigée par {corriges} geste(s) appris sur {len(base.par_geste)}"
            if corriges
            else "d'après le simulateur seulement (rien d'appris encore)"
        )
        texte = (
            f"Fin du lot : environ {duree_lisible(reste)} (entre {duree_lisible(bas)} et "
            f"{duree_lisible(haut)}), vers {fin:%H:%M}. Estimation {source}"
            + (", réglages d'exemple" if base.exemple else "")
            + ". Attentes du Go et pauses en plus."
        )
        return {
            "disponible": True,
            "reste_s": round(reste),
            "bas_s": round(bas),
            "haut_s": round(haut),
            "fin": fin.isoformat(timespec="seconds"),
            "avancement_pct": round(100 * avancement, 1),
            "rapport": round(rapport_du_lot, 3),
            "gestes_appris": corriges,
            "gestes": len(base.par_geste),
            "fourchette_pct": round(pct, 1),
            "simulateur_seul": corriges == 0,
            "exemple": base.exemple,
            "texte": texte,
            "texte_court": f"Fin vers {fin:%H:%M} (env. {duree_lisible(reste)})",
        }
