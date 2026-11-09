"""Compteurs d'usure : ce que chaque axe et chaque actionneur a fait depuis la mise en service.

    compteurs = Compteurs(reglages.entretien.compteurs, reglages.machine, reglages.fluidnc,
                          donnees / "entretien.json")
    liaison.ecouteur_rapport = compteurs.noter_rapport     # positions des axes
    liaison.ecouteur_ligne = compteurs.noter_ligne         # M62 à M65 : vannes, freins...
    materiel.ecouteur_sortie = compteurs.noter_sortie      # relais du Pi
    compteurs.demarrer(arret)                              # écriture groupée en fond

Pour chaque axe de machine.yaml qui a une carte : la distance parcourue (mètres, ou degrés pour un
axe tournant), le nombre de mouvements et les heures de marche (le temps où l'axe bouge). Pour
chaque sortie tout-ou-rien : le nombre de manœuvres (mises en marche). Ce sont des TOTAUX À VIE :
rien n'est remis à zéro ici (une pièce remise à neuf garde un point de départ, voir `Entretien`).

Le Pi ne fait que lire ce que les cartes rapportent : il ne commande rien. Un compteur peut se
tromper un peu (une ligne envoyée mais perdue par la carte compte quand même) : c'est un ordre de
grandeur pour l'entretien, jamais une mesure de précision, et jamais une protection.

Les compteurs vivent en mémoire et sont écrits dans « entretien.json » (dossier des données) d'un
seul coup toutes les `ecriture_periode_s` secondes, seulement s'ils ont changé, et à l'arrêt :
pas d'écriture à chaque geste (usure du disque). Le fichier est dans la copie de secours
quotidienne (tous les petits fichiers du dossier des données le sont) et relu au démarrage.
"""

import json
import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from vidange.fiabilite.constats import lancer_boucle
from vidange.journal import donner_journal
from vidange.reglages import CompteursEntretien, Fluidnc, Machine

journal = donner_journal("entretien.compteurs")

NOM_FICHIER = "entretien.json"
VERSION = 1
# « M64 P2 » (sortie numérique allumée tout de suite), « M62 P2 » (synchronisée avec le
# mouvement) ; « M65 » et « M63 » les éteignent.
_SORTIE = re.compile(r"^M6([2-5])\s+P(\d+)\b", re.IGNORECASE)
MM_PAR_M = 1000


def _axe_vide() -> dict[str, float]:
    return {"distance": 0.0, "mouvements": 0.0, "heures": 0.0}


def heure_iso(moment: datetime) -> str:
    return moment.astimezone().isoformat(timespec="seconds")


class Compteurs:
    def __init__(
        self,
        reglages: CompteursEntretien,
        machine: Machine,
        fluidnc: Fluidnc,
        fichier: Path | None = None,
        maintenant: Callable[[], datetime] = datetime.now,
    ) -> None:
        """`fichier` : où garder les compteurs (None : nulle part, pour les essais)."""
        self.reglages = reglages
        self.fichier = fichier
        self._maintenant = maintenant
        self._verrou = threading.RLock()
        # Axe de machine.yaml → (carte, lettre), et le contraire pour lire les rapports.
        self._axes_de = {
            nom: (axe.carte, axe.lettre)
            for nom, axe in machine.axes.items()
            if axe.carte is not None and axe.lettre is not None
        }
        self._unite = {nom: axe.unite for nom, axe in machine.axes.items()}
        self._lettres: dict[str, dict[str, str]] = {}
        for nom, (carte, lettre) in self._axes_de.items():
            self._lettres.setdefault(carte, {})[lettre] = nom
        # Sortie de carte FluidNC (carte, numéro) → nom du signal.
        self._sorties_fluidnc = {
            (nom_carte, numero): nom
            for nom_carte, carte in fluidnc.cartes.items()
            for nom, numero in carte.sorties.items()
        }
        self.axes: dict[str, dict[str, float]] = {nom: _axe_vide() for nom in self._axes_de}
        self.actionneurs: dict[str, int] = {}
        # Point de départ de chaque pièce d'usure (écrit par `Entretien`, gardé dans le même
        # fichier) : nom de la pièce → {valeur, date, fait_le, fait_par}.
        self.departs: dict[str, dict[str, Any]] = {}
        self.cree_le = heure_iso(maintenant())
        # Ce qui ne sert qu'à compter (jamais écrit) : dernière position et heure de chaque axe,
        # heure du dernier mouvement, état des sorties.
        self._derniere: dict[tuple[str, str], tuple[float, float]] = {}
        self._dernier_mouvement: dict[str, float] = {}
        self._sorties_allumees: dict[str, bool] = {}
        self._saut_signale: set[str] = set()
        self._a_ecrire = False
        # Ce que la lecture du fichier a trouvé de faux (la check-list le dit), ou None.
        self.erreur_lecture: str | None = None
        self._lire()

    # ------------------------------------------------------------ ce que les cartes rapportent

    def noter_rapport(
        self, carte: str, positions: Mapping[str, float] | None, temps: float
    ) -> None:
        """Un rapport d'état d'une carte : positions machine (mm, ou degrés) par lettre d'axe, et
        l'heure du rapport en secondes (une horloge qui ne revient jamais en arrière)."""
        lettres = self._lettres.get(carte)
        if lettres is None:
            return
        with self._verrou:
            if not positions:
                # Carte coupée ou muette : au retour, on ne compte pas le trajet entre-temps.
                for lettre in lettres:
                    self._derniere.pop((carte, lettre), None)
                return
            for lettre, axe in lettres.items():
                position = positions.get(lettre)
                if position is None:
                    continue
                avant = self._derniere.get((carte, lettre))
                self._derniere[(carte, lettre)] = (position, temps)
                if avant is not None:
                    self._compter_pas(axe, abs(position - avant[0]), temps - avant[1], temps)

    def _compter_pas(self, axe: str, ecart: float, duree_s: float, temps: float) -> None:
        reglages = self.reglages
        if duree_s <= 0:
            return
        if ecart > reglages.saut_max_mm:
            if axe not in self._saut_signale:
                self._saut_signale.add(axe)
                journal.warning(
                    "Axe « %s » : saut de %.0f entre deux rapports, pas compté (repère perdu ?)",
                    axe,
                    ecart,
                )
            return
        if ecart < reglages.seuil_mouvement_mm:
            return
        compteur = self.axes[axe]
        compteur["distance"] += ecart / MM_PAR_M if self._unite[axe] == "m" else ecart
        if duree_s <= reglages.trou_max_s:
            compteur["heures"] += duree_s / 3600
        dernier = self._dernier_mouvement.get(axe)
        if dernier is None or temps - dernier > reglages.arret_s:
            compteur["mouvements"] += 1
        self._dernier_mouvement[axe] = temps
        self._a_ecrire = True

    def noter_mouvement(self, axe: str, distance: float, duree_s: float) -> None:
        """Un mouvement connu en entier (le simulateur) : distance dans l'unité de l'axe."""
        if axe not in self.axes or distance <= 0:
            return
        with self._verrou:
            compteur = self.axes[axe]
            compteur["distance"] += distance
            compteur["mouvements"] += 1
            compteur["heures"] += max(duree_s, 0.0) / 3600
            self._a_ecrire = True

    def noter_ligne(self, carte: str, ligne: str) -> None:
        """Une ligne de G-code envoyée à une carte : compte les mises en marche des sorties."""
        trouve = _SORTIE.match(ligne.strip())
        if trouve is None:
            return
        nom = self._sorties_fluidnc.get((carte, int(trouve.group(2))))
        if nom is not None:
            self.noter_sortie(nom, trouve.group(1) in ("2", "4"))

    def noter_sortie(self, nom: str, actif: bool) -> None:
        """Une sortie commandée (True = en marche). Seul le passage « arrêt → marche » compte :
        redire « en marche » à une sortie déjà en marche n'est pas une manœuvre de plus."""
        with self._verrou:
            avant = self._sorties_allumees.get(nom, False)
            self._sorties_allumees[nom] = actif
            if actif and not avant:
                self.actionneurs[nom] = self.actionneurs.get(nom, 0) + 1
                self._a_ecrire = True

    def noter_rapport_liaison(self, nom: str, etat: Any) -> None:
        """Pour `Liaison.ecouteur_rapport` : un EtatCarte tout juste mis à jour."""
        positions = etat.positions if etat.connectee else None
        temps = etat.date_rapport if etat.date_rapport is not None else time.monotonic()
        self.noter_rapport(nom, positions, temps)

    # ------------------------------------------------------------ lecture

    def valeur_axe(self, axe: str, genre: str) -> float:
        with self._verrou:
            return self.axes[axe][genre]

    def valeur_actionneur(self, nom: str) -> int:
        with self._verrou:
            return self.actionneurs.get(nom, 0)

    def unite_axe(self, axe: str) -> str:
        return "°" if self._unite.get(axe) == "deg" else "m"

    def instantane(self) -> dict[str, Any]:
        """Tous les compteurs, pour la page (copie : on peut la garder)."""
        with self._verrou:
            return {
                "cree_le": self.cree_le,
                "axes": {
                    nom: {**valeurs, "unite": self.unite_axe(nom)}
                    for nom, valeurs in self.axes.items()
                },
                "actionneurs": dict(sorted(self.actionneurs.items())),
            }

    # ------------------------------------------------------------ le fichier

    def _lire(self) -> None:
        if self.fichier is None or not self.fichier.exists():
            return
        try:
            donnees = json.loads(self.fichier.read_text(encoding="utf-8"))
            for nom, valeurs in donnees.get("axes", {}).items():
                if nom in self.axes:
                    for genre in self.axes[nom]:
                        self.axes[nom][genre] = float(valeurs.get(genre, 0.0))
            self.actionneurs = {
                str(nom): int(valeur) for nom, valeur in donnees.get("actionneurs", {}).items()
            }
            self.departs = {
                str(nom): dict(depart) for nom, depart in donnees.get("departs", {}).items()
            }
            self.cree_le = str(donnees.get("cree_le", self.cree_le))
        except (OSError, ValueError, TypeError, AttributeError) as erreur:
            self.erreur_lecture = f"fichier des compteurs illisible ({self.fichier}) : {erreur}"
            journal.error("%s : les compteurs repartent de zéro", self.erreur_lecture)
            try:
                os.replace(self.fichier, self.fichier.with_name(self.fichier.name + ".abime"))
            except OSError:
                pass
            self.axes = {nom: _axe_vide() for nom in self._axes_de}
            self.actionneurs = {}
            self.departs = {}
            self._a_ecrire = True

    def a_ecrire(self) -> bool:
        return self._a_ecrire

    def contenu(self) -> dict[str, Any]:
        with self._verrou:
            return {
                "version": VERSION,
                "cree_le": self.cree_le,
                "axes": {nom: dict(valeurs) for nom, valeurs in self.axes.items()},
                "actionneurs": dict(self.actionneurs),
                "departs": {nom: dict(depart) for nom, depart in self.departs.items()},
            }

    def changer_depart(self, piece: str, depart: dict[str, Any]) -> None:
        """Le point de départ d'une pièce change : écrit tout de suite (c'est rare, et c'est
        ce que Karulium vient de faire)."""
        with self._verrou:
            self.departs[piece] = dict(depart)
            self._a_ecrire = True
        self.ecrire()

    def ecrire(self, force: bool = False) -> bool:
        """Écrit les compteurs s'ils ont changé (ou si `force`). Vrai si le fichier est écrit."""
        if self.fichier is None:
            return False
        with self._verrou:
            if not self._a_ecrire and not force:
                return False
            texte = json.dumps(self.contenu(), ensure_ascii=False, indent=1)
            self._a_ecrire = False
        return self._ecrire_texte(texte)

    def _ecrire_texte(self, texte: str) -> bool:
        assert self.fichier is not None
        try:
            self.fichier.parent.mkdir(parents=True, exist_ok=True)
            provisoire = self.fichier.with_name(self.fichier.name + ".tmp")
            provisoire.write_text(texte, encoding="utf-8")
            os.replace(provisoire, self.fichier)
        except OSError as erreur:
            self._a_ecrire = True
            journal.error("Compteurs pas gardés dans %s : %s", self.fichier, erreur)
            return False
        return True

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        """L'écriture groupée en fond. À l'arrêt du programme, appeler `ecrire()` une dernière
        fois, une fois les liaisons arrêtées."""
        return lancer_boucle("entretien", self.reglages.ecriture_periode_s, self.ecrire, arret)
