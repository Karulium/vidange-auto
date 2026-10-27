"""Bilan de chaque alarme (fonction 17) et son « quoi faire » (fonction 18) dans le registre.

À chaque nouvelle alarme du chef d'orchestre, un fichier de bilan est écrit dans
« donnees/bilans/AAAA-MM-JJ/HHMMSS-module.json » : l'alarme et son quoi faire, l'état de tous
les modules, la mémoire du module (seau en cours...), l'état et les positions de chaque carte
FluidNC, toutes les entrées et sorties, les mesures, la santé du Pi, et les dernières lignes
du journal. L'alarme est notée dans le registre avec le chemin de son bilan.

Le clip vidéo des dernières secondes de chaque caméra (tâche 12) est ajouté par le démarrage
dans `collecteurs` (« clip_video » : le dossier du clip) ; d'autres morceaux peuvent l'être aussi.

Le chef appelle `recevoir` pendant qu'il tient son verrou : le bilan est fait dans un fil à
part, pour ne jamais retarder le chef (les lectures de capteurs peuvent prendre du temps).
"""

import json
import queue
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from vidange.chef import Alarme, Chef, ErreurChef
from vidange.fiabilite.constats import Constat
from vidange.fluidnc import Liaison
from vidange.journal import donner_journal
from vidange.materiel import Materiel
from vidange.registre import Registre
from vidange.reglages import ReglagesBilan

journal = donner_journal("fiabilite.bilans")

DOSSIER_BILANS = "bilans"


def _ou_erreur(lire: Callable[[], Any]) -> Any:
    """La valeur lue, ou le texte de l'erreur : un capteur muet ne gâche pas tout le bilan."""
    try:
        return lire()
    except Exception as erreur:
        return f"erreur : {erreur}"


class Bilans:
    def __init__(
        self,
        dossier_donnees: Path,
        reglages: ReglagesBilan,
        registre: Registre,
        chef: Chef,
        liaisons: Mapping[str, Liaison] | None = None,
        materiel: Materiel | None = None,
        sante: Callable[[], list[Constat]] | None = None,
        chemin_journal: Path | None = None,
        horloge: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.dossier_donnees = dossier_donnees
        self.reglages = reglages
        self.registre = registre
        self.chef = chef
        self.liaisons = dict(liaisons or {})
        self.materiel = materiel
        self._sante = sante
        self.chemin_journal = chemin_journal
        self._horloge = horloge
        # Nom → fonction : ce qu'on ajoute au bilan (le clip vidéo de la tâche 12...).
        self.collecteurs: dict[str, Callable[[], Any]] = {}
        self._file: queue.Queue[Alarme] = queue.Queue()

    # ------------------------------------------------------------ côté chef

    def recevoir(self, alarme: Alarme) -> None:
        """Appelée par le chef à chaque nouvelle alarme (chef.sur_alarme) : rapide."""
        self._file.put(alarme)

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        """Le fil qui fait les bilans. À l'arrêt, il finit ceux qui attendent."""

        def boucle() -> None:
            while not (arret.is_set() and self._file.empty()):
                try:
                    alarme = self._file.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    self.traiter(alarme)
                except Exception:
                    journal.exception("Bilan de l'alarme de « %s » raté", alarme.module)

        fil = threading.Thread(target=boucle, name="bilans", daemon=True)
        fil.start()
        return fil

    # ------------------------------------------------------------ le bilan

    def traiter(self, alarme: Alarme) -> int:
        """Écrit le bilan et note l'alarme dans le registre. Rend le numéro de l'alarme."""
        memoire = _ou_erreur(lambda: self.chef.memoire(alarme.module))
        bilan = self.rassembler(alarme, memoire)
        chemin: Path | None = None
        try:
            chemin = self._ecrire(alarme, bilan)
        except OSError as erreur:
            journal.error("Bilan de l'alarme de « %s » pas écrit : %s", alarme.module, erreur)
        relatif = chemin.relative_to(self.dossier_donnees).as_posix() if chemin else None
        cycle = memoire.get("cycle") if isinstance(memoire, dict) else None
        valeurs = {
            "module": alarme.module,
            "message": alarme.message,
            "quoi_faire": alarme.quoi_faire,
            "etape": alarme.etape,
            "bilan": relatif,
        }
        try:
            numero = self.registre.noter_alarme(
                **valeurs, cycle=cycle if isinstance(cycle, int) else None
            )
        except Exception as erreur:
            # Numéro de cycle inconnu du registre : l'alarme est quand même notée.
            journal.error("Alarme notée sans son cycle (%s) : %s", cycle, erreur)
            numero = self.registre.noter_alarme(**valeurs)
        journal.info("Bilan de l'alarme n° %d écrit : %s", numero, relatif)
        return numero

    def rassembler(self, alarme: Alarme, memoire: Any) -> dict[str, Any]:
        bilan: dict[str, Any] = {
            "alarme": asdict(alarme),
            "ecrit_le": self._horloge().isoformat(timespec="seconds"),
            "memoire_du_module": memoire,
            "modules": _ou_erreur(lambda: [asdict(m) for m in self.chef.etat().modules]),
            "machine_en_pause": self.chef.en_pause,
            "cartes": {nom: asdict(liaison.etat) for nom, liaison in self.liaisons.items()},
        }
        if self.materiel is not None:
            bilan.update(self._lire_materiel(self.materiel))
        if self._sante is not None:
            bilan["sante"] = _ou_erreur(lambda: [asdict(c) for c in self._sante()])
        bilan["journal"] = _ou_erreur(self._fin_du_journal)
        # Le clip vidéo (tâche 12) : None s'il n'y a pas de caméra.
        bilan["clip_video"] = None
        for nom, collecteur in self.collecteurs.items():
            bilan[nom] = _ou_erreur(collecteur)
        return bilan

    @staticmethod
    def _lire_materiel(materiel: Materiel) -> dict[str, Any]:
        entrees, sorties, mesures, ambiances = {}, {}, {}, {}
        for nom, branchement in materiel.branchements.items():
            if branchement.sorte == "entree":
                entrees[nom] = _ou_erreur(lambda nom=nom: materiel.lire(nom))
            elif branchement.sorte == "sortie":
                sorties[nom] = _ou_erreur(lambda nom=nom: materiel.lire(nom))
            elif branchement.sorte in ("mesure", "modbus"):
                mesures[nom] = _ou_erreur(
                    lambda nom=nom: {"valeur": materiel.mesurer(nom), "unite": materiel.unite(nom)}
                )
            elif branchement.sorte == "ambiance":
                ambiances[nom] = _ou_erreur(lambda nom=nom: materiel.ambiance(nom)._asdict())
        return {"entrees": entrees, "sorties": sorties, "mesures": mesures, "ambiance": ambiances}

    def _fin_du_journal(self) -> list[str]:
        if self.chemin_journal is None or not self.chemin_journal.exists():
            return []
        nombre = self.reglages.lignes_journal
        with self.chemin_journal.open(encoding="utf-8", errors="replace") as fichier:
            return [ligne.rstrip("\n") for ligne in deque(fichier, maxlen=nombre)] if nombre else []

    def _ecrire(self, alarme: Alarme, bilan: dict[str, Any]) -> Path:
        moment = self._horloge()
        dossier = self.dossier_donnees / DOSSIER_BILANS / moment.strftime("%Y-%m-%d")
        dossier.mkdir(parents=True, exist_ok=True)
        base = f"{moment.strftime('%H%M%S')}-{alarme.module}"
        chemin = dossier / f"{base}.json"
        numero = 2
        while chemin.exists():
            chemin = dossier / f"{base}-{numero}.json"
            numero += 1
        texte = json.dumps(bilan, ensure_ascii=False, indent=1, default=str)
        chemin.write_text(texte, encoding="utf-8")
        return chemin

    # ------------------------------------------------------------ acquittement

    def acquitter(self, alarme: int, qui: str) -> None:
        """Karulium acquitte une alarme du registre (par son numéro).

        Si le module est encore en alarme dans le chef, il est acquitté aussi (son étape sera
        refaite après un Go), et toutes les alarmes encore ouvertes de ce module sont fermées.
        """
        lignes = self.registre.lire("SELECT module FROM alarmes WHERE id = ?", (alarme,))
        if not lignes:
            raise ErreurChef(f"alarme n° {alarme} inconnue")
        module = lignes[0]["module"]
        en_alarme = any(
            m.module == module and m.statut == "alarme" for m in self.chef.etat().modules
        )
        if not en_alarme:
            self.registre.acquitter_alarme(alarme, qui)
            return
        self.chef.acquitter(module)
        for ligne in self.registre.alarmes_ouvertes():
            if ligne["module"] == module:
                self.registre.acquitter_alarme(ligne["id"], qui)
