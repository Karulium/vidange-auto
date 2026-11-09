"""Montée en vitesse par paliers, dans le cadre fixé par Karulium (tâche 30, fonction 69).

    montee = MonteeVitesse(reglages.programme.montee_vitesse, donnees / "montee_vitesse.json",
                           registre, actions)
    reglages = appliquer_vitesses(reglages, montee.palier_en_vigueur, montee.reglages)
    chef.sur_etape_finie.append(montee.sur_etape_finie)   # compte les cycles (seaux rangés)
    chef.sur_alarme.append(montee.sur_alarme)             # recule à la première alarme

Ce que cela fait, et ce que cela ne fait JAMAIS :
- les vitesses listées (programme.yaml → montee_vitesse → vitesses) valent « départ × (1 + palier ×
  palier_pct) », coupées au PLAFOND fixé par Karulium : jamais au-dessus ;
- après `cycles_par_palier` cycles sans alerte, le palier voulu monte d'un ; à la première alerte
  (alarme du chef, ou alarme notée au registre pendant les cycles), il recule d'un palier (ou
  revient au départ : `au_recul`) ;
- chaque changement est noté au journal, au registre (reglages_appliques) et au journal des actions,
  et s'annule (`annuler`) ;
- la sécurité n'est jamais apprise : ce facteur ne touche aucun seuil, aucune zone, aucune règle de
  positions, aucune vitesse de contact ou d'approche (refusées au démarrage). Il ne change que les
  vitesses de déplacement listées, au démarrage du programme (les réglages sont figés en route) ;
  le palier voulu est gardé dans un fichier, donc il survit à une coupure.
"""

import json
import os
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vidange.journal import donner_journal
from vidange.registre.base import Registre, heure
from vidange.reglages import (
    Modele,
    Reglages,
    ReglagesMonteeVitesse,
    valeur_de_la_machine,
)

if TYPE_CHECKING:
    from vidange.api.acces import JournalActions

journal = donner_journal("vitesse")

QUI = "montée en vitesse"
FICHIER = "montee_vitesse.json"
# Changements gardés dans le fichier d'état (les plus récents).
HISTORIQUE_MAX = 50


class ErreurMontee(Exception):
    """Une demande refusée (rien à annuler...)."""


def _remplacer(modele: Modele, morceaux: list[str], valeur: float) -> Modele:
    """Une copie du modèle (figé) où le nombre au bout du chemin est `valeur`."""
    nom = morceaux[0]
    if len(morceaux) == 1:
        return modele.model_copy(update={nom: valeur})
    return modele.model_copy(update={nom: _remplacer(getattr(modele, nom), morceaux[1:], valeur)})


def facteur_du_palier(reglages: ReglagesMonteeVitesse, palier: int) -> float:
    return 1 + palier * reglages.palier_pct / 100


def vitesses_au_palier(
    reglages: ReglagesMonteeVitesse, machine: Any, palier: int
) -> dict[str, float]:
    """Chaque vitesse listée au palier donné : départ × facteur, JAMAIS au-dessus du plafond."""
    facteur = facteur_du_palier(reglages, palier)
    return {
        chemin: min(valeur_de_la_machine(machine, chemin) * facteur, plafond)
        for chemin, plafond in reglages.vitesses.items()
    }


def appliquer_vitesses(
    reglages: Reglages, palier: int, montee: ReglagesMonteeVitesse | None = None
) -> Reglages:
    """Les réglages avec les vitesses du palier (en mémoire seulement : aucun fichier touché).
    Palier 0 ou montée absente : les mêmes réglages."""
    montee = montee or reglages.programme.montee_vitesse
    if montee is None or palier <= 0:
        return reglages
    machine = reglages.machine
    for chemin, valeur in vitesses_au_palier(montee, machine, palier).items():
        machine = _remplacer(machine, chemin.split("."), valeur)  # type: ignore[assignment]
    return reglages.model_copy(update={"machine": machine})


class MonteeVitesse:
    def __init__(
        self,
        reglages: ReglagesMonteeVitesse | None,
        fichier: Path,
        registre: Registre | None = None,
        actions: "JournalActions | None" = None,
        horloge: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.reglages = reglages
        self._fichier = fichier
        self._registre = registre
        self._actions = actions
        self._horloge = horloge
        self._verrou = threading.RLock()
        self._etat: dict[str, Any] = {"palier": 0, "cycles": 0, "depuis": None, "changements": []}
        self._lire()
        # Le palier dont les vitesses sont en vigueur : celui du démarrage (0 si pas actif).
        self.palier_en_vigueur = self.palier if self.actif else 0
        if self.actif:
            self._borner_au_demarrage()
            if self._etat["depuis"] is None:
                self._etat["depuis"] = heure(self._horloge())
                self._ecrire()

    # ------------------------------------------------------------ état

    @property
    def actif(self) -> bool:
        return self.reglages is not None and self.reglages.actif

    @property
    def palier(self) -> int:
        return int(self._etat["palier"])

    @property
    def cycles(self) -> int:
        return int(self._etat["cycles"])

    def _lire(self) -> None:
        try:
            lu = json.loads(self._fichier.read_text(encoding="utf-8"))
            self._etat.update({cle: lu[cle] for cle in self._etat if cle in lu})
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError) as erreur:
            # Fichier abîmé : départ sûr (palier 0), dit au journal.
            journal.error(
                "Montée en vitesse : fichier d'état illisible (%s) : retour au départ", erreur
            )

    def _ecrire(self) -> None:
        self._etat["changements"] = self._etat["changements"][-HISTORIQUE_MAX:]
        provisoire = self._fichier.with_name(self._fichier.name + ".tmp")
        try:
            self._fichier.parent.mkdir(parents=True, exist_ok=True)
            with provisoire.open("w", encoding="utf-8") as sortie:
                json.dump(self._etat, sortie, ensure_ascii=False, indent=1)
                sortie.flush()
                os.fsync(sortie.fileno())
            os.replace(provisoire, self._fichier)
        except OSError as erreur:
            journal.error("Montée en vitesse : état pas écrit (%s)", erreur)

    def _borner_au_demarrage(self) -> None:
        """Un palier plus haut que `paliers_max` (réglage resserré depuis) est ramené au maximum."""
        assert self.reglages is not None
        if self.palier > self.reglages.paliers_max:
            self._changer(self.reglages.paliers_max, "paliers_max resserré dans les réglages")
            self.palier_en_vigueur = self.palier

    def facteur(self, palier: int | None = None) -> float:
        if self.reglages is None:
            return 1.0
        return facteur_du_palier(self.reglages, self.palier if palier is None else palier)

    # ------------------------------------------------------------ ce qui fait monter ou reculer

    def sur_etape_finie(self, module: str, etape: str, _duree_s: float = 0.0) -> None:
        """Appelée par le chef : compte un cycle quand l'étape de cycle finit."""
        if self.reglages is None or not self.actif:
            return
        if f"{module}.{etape}" != self.reglages.etape_de_cycle:
            return
        self.cycle_fini()

    def cycle_fini(self) -> None:
        """Un cycle (un seau rangé) de plus. Une alarme notée au registre depuis le dernier
        changement (spray, micropore... : pas seulement le chef) fait reculer au lieu de compter."""
        assert self.reglages is not None
        with self._verrou:
            self._lire()
            alertes = self._alertes_depuis_le_dernier_changement()
            if alertes:
                self._reculer(f"{alertes} alerte(s) notée(s) au registre pendant les cycles")
                return
            self._etat["cycles"] = self.cycles + 1
            if self.cycles >= self.reglages.cycles_par_palier:
                if self.palier < self.reglages.paliers_max:
                    self._changer(
                        self.palier + 1,
                        f"{self.reglages.cycles_par_palier} cycles de suite sans alerte",
                    )
                else:
                    self._etat["cycles"] = 0
                    self._ecrire()
            else:
                self._ecrire()

    def sur_alarme(self, alarme: Any) -> None:
        """Appelée par le chef à chaque nouvelle alarme (chef.sur_alarme) : recul tout de suite."""
        if not self.actif:
            return
        with self._verrou:
            self._lire()
            self._reculer(f"alarme de « {alarme.module} », étape « {alarme.etape} »")

    def apres_alarme_notee(self, *_: Any) -> None:
        """Appelée par les bilans (bilans.sur_numero) quand l'alarme du chef est notée au registre,
        un peu après `sur_alarme` : elle a déjà fait reculer, elle ne doit pas compter deux fois."""
        if not self.actif:
            return
        with self._verrou:
            self._lire()
            self._etat["depuis"] = heure(self._horloge())
            self._ecrire()

    def _alertes_depuis_le_dernier_changement(self) -> int:
        if self._registre is None:
            return 0
        depuis = self._etat["depuis"]
        if depuis is None:
            return 0
        lignes = self._registre.lire("SELECT COUNT(*) AS n FROM alarmes WHERE quand > ?", (depuis,))
        return int(lignes[0]["n"])

    def _reculer(self, raison: str) -> None:
        assert self.reglages is not None
        if self.palier > 0:
            cible = 0 if self.reglages.au_recul == "depart" else self.palier - 1
            self._changer(cible, f"recul : {raison}")
        else:
            # Déjà au départ : le décompte repart de zéro.
            self._etat["cycles"] = 0
            self._etat["depuis"] = heure(self._horloge())
            self._ecrire()

    def _changer(self, nouveau: int, raison: str, qui: str = QUI, annule: bool = False) -> None:
        with self._verrou:
            ancien = self.palier
            moment = heure(self._horloge())
            self._etat.update({"palier": nouveau, "cycles": 0, "depuis": moment})
            self._etat["changements"].append(
                {
                    "quand": moment,
                    "qui": qui,
                    "avant": ancien,
                    "apres": nouveau,
                    "raison": raison,
                    "annule": annule,
                }
            )
            self._ecrire()
        journal.warning(
            "Montée en vitesse : palier %d → %d (facteur %.3f → %.3f) : %s. Prend effet au "
            "prochain démarrage du programme.",
            ancien,
            nouveau,
            self.facteur(ancien),
            self.facteur(nouveau),
            raison,
        )
        self._noter(qui, ancien, nouveau, raison)

    def _noter(self, qui: str, ancien: int, nouveau: int, raison: str) -> None:
        """Au registre (reglages_appliques) et au journal des actions : qui, quand, avant, après."""
        if self._registre is not None:
            try:
                self._registre.noter_reglage(
                    qui, FICHIER, "palier", ancien, nouveau, f"montée en vitesse : {raison}"
                )
            except Exception:
                journal.exception("Montée en vitesse : changement pas noté au registre")
        if self._actions is not None:
            try:
                self._actions.noter(
                    qui=qui,
                    niveau="réglage",
                    reglage="montee_vitesse.palier",
                    avant=ancien,
                    apres=nouveau,
                    motif=raison,
                )
            except OSError:
                journal.exception("Montée en vitesse : changement pas noté au journal des actions")

    # ------------------------------------------------------------ annuler

    def annuler(self, qui: str) -> dict[str, Any]:
        """Annule le dernier changement de palier (une annulation ne s'annule pas) : le palier
        d'avant revient. Il agit au prochain démarrage, comme tout changement."""
        with self._verrou:
            self._lire()
            changements = self._etat["changements"]
            if not changements or changements[-1].get("annule"):
                raise ErreurMontee("rien à annuler : le dernier changement est déjà une annulation")
            dernier = changements[-1]
            if dernier["apres"] != self.palier:
                raise ErreurMontee(
                    "rien à annuler : le palier n'est plus celui du dernier changement"
                )
            self._changer(dernier["avant"], "annulation du dernier changement", qui, annule=True)
        return self.en_dict()

    # ------------------------------------------------------------ ce qu'on dit

    def en_dict(self) -> dict[str, Any]:
        reglages = self.reglages
        if reglages is None:
            return {"actif": False, "present": False}
        self._lire()
        return {
            "present": True,
            "actif": reglages.actif,
            "palier": self.palier,
            "palier_en_vigueur": self.palier_en_vigueur,
            "palier_max": reglages.paliers_max,
            "facteur": round(self.facteur(), 4),
            "facteur_en_vigueur": round(self.facteur(self.palier_en_vigueur), 4),
            "cycles": self.cycles,
            "cycles_par_palier": reglages.cycles_par_palier,
            "au_recul": reglages.au_recul,
            "plafonds": dict(reglages.vitesses),
            "redemarrage_necessaire": self.palier != self.palier_en_vigueur,
            "peut_annuler": bool(self._etat["changements"])
            and not self._etat["changements"][-1].get("annule"),
            "changements": list(reversed(self._etat["changements"][-10:])),
        }

    def texte(self) -> str:
        if self.reglages is None or not self.reglages.actif:
            return "Montée en vitesse : pas active."
        texte = (
            f"Montée en vitesse : palier {self.palier} sur {self.reglages.paliers_max} "
            f"(vitesses à {self.facteur() * 100:.0f} % du départ), {self.cycles} cycle(s) sur "
            f"{self.reglages.cycles_par_palier} sans alerte."
        )
        if self.palier != self.palier_en_vigueur:
            texte += (
                f" En vigueur depuis le démarrage : palier {self.palier_en_vigueur} ; le palier "
                "voulu agira au prochain démarrage."
            )
        return texte
