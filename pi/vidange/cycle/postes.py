"""Ce que les trois programmes (seaux, bocaux, nuit UV-ozone) ont en commun (tâches 45 et 45 bis).

- `EtatPoste` : un poste est prêt, ou « pas lancé : raison » (écran, check-list, journal) ;
- `etat_du_poste` : la même vérification pour tous les postes (geste pas écrit, partie absente de
  machine.yaml, EXEMPLE sur la vraie machine, matériel qui manque, poste dont il a besoin) ;
- `refus_lancement` : un seul mode à la fois (Production pour les seaux et les bocaux, Lavage pour
  laver les bocaux, UV-ozone pour la nuit), et un seul lot à la fois.

Rien de tout cela ne protège personne : la sécurité est câblée.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol

from vidange.chef import Chef, Etape, Module
from vidange.cycle.ordre import Poste
from vidange.reglages import Reglages


class PiecesDuPoste(Protocol):
    """Le minimum que demande la vérification : vrai matériel ou non, et ce qui manque."""

    vraie_machine: bool

    def manque(self, poste: str) -> str | None: ...


@dataclass(frozen=True)
class EtatPoste:
    poste: Poste
    pret: bool
    # Pourquoi il n'est pas lancé (vide s'il est prêt).
    raison: str = ""

    def en_texte(self) -> str:
        return "prêt" if self.pret else f"pas lancé : {self.raison}"


def _objets_du_chemin(machine: Any, chemin: str) -> list[Any] | None:
    """Les objets de machine.yaml le long d'un chemin « lavage.lave_bocal » (None : un manque)."""
    objets = []
    courant = machine
    for nom in chemin.split("."):
        courant = getattr(courant, nom, None)
        if courant is None:
            return None
        objets.append(courant)
    return objets


def etat_du_poste(
    poste: Poste,
    reglages: Reglages,
    pieces: PiecesDuPoste,
    parties: Mapping[str, tuple[str, ...]],
    etats: Mapping[str, EtatPoste],
) -> EtatPoste:
    """L'état d'un poste. `parties` : les parties de machine.yaml de chaque poste (avec des points
    pour une partie dans une partie) ; `etats` : les postes déjà vérifiés (pour `besoin`)."""
    if poste.case_vide is not None:
        return EtatPoste(poste, False, f"geste pas encore écrit : {poste.case_vide}")
    machine = reglages.machine
    chaines = []
    for partie in parties.get(poste.nom, ()):
        objets = _objets_du_chemin(machine, partie)
        if objets is None:
            return EtatPoste(poste, False, f"machine.yaml n'a pas de partie « {partie} »")
        chaines.append((partie, objets))
    if pieces.vraie_machine:
        exemples = [
            partie
            for partie, objets in chaines
            if any(getattr(objet, "exemple", False) for objet in objets)
        ]
        if machine.exemple or exemples:
            ou = ", ".join(exemples) if exemples else "le haut du fichier"
            return EtatPoste(
                poste,
                False,
                f"valeurs d'EXEMPLE dans machine.yaml ({ou}) : interdit sur la vraie machine",
            )
    manque = pieces.manque(poste.nom)
    if manque is not None:
        return EtatPoste(poste, False, manque)
    for besoin in poste.besoin:
        if not etats[besoin].pret:
            return EtatPoste(poste, False, f"attend « {besoin} » (pas prêt)")
    return EtatPoste(poste, True)


# Les modules du chef qui disent qu'un lot (ou une nuit) est en cours.
STATUTS_OCCUPES = ("en_cours", "alarme")


def refus_lancement(
    chef: Chef, mode_actuel: Callable[[], str] | None, mode_voulu: str, libelle: str
) -> str | None:
    """Pourquoi ce lot ne peut pas partir : mauvais mode (un seul mode à la fois), ou un autre lot
    (seaux, bocaux, lavage...) déjà en route. `mode_actuel` None : le mode n'est pas vérifié
    (simulateur)."""
    if mode_actuel is not None:
        actuel = mode_actuel()
        if actuel != mode_voulu:
            return f"{libelle} : le mode « {mode_voulu} » n'est pas choisi (mode actuel : {actuel})"
    occupes = [m.module for m in chef.etat().modules if m.statut in STATUTS_OCCUPES]
    if occupes:
        return f"{libelle} : un lot est déjà en route ({', '.join(occupes)})"
    return None


def noter_apres_chaque_etape(module: Module, noter: Callable[[], None]) -> Module:
    """Le même module, qui appelle `noter` (écriture dans le carnet du chef) à la fin de chaque
    étape : après une coupure, le lot est repris là où il en était."""

    def suivie(etape: Etape) -> Etape:
        ensuite = etape.ensuite

        def apres() -> str | None:
            suivante = ensuite() if ensuite is not None else None
            noter()
            return suivante

        return replace(etape, ensuite=apres)

    return replace(module, etapes=tuple(suivie(etape) for etape in module.etapes))
