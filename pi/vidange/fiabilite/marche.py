"""Comment le programme s'est arrêté la dernière fois : proprement, planté, ou coupure de courant.

Un petit fichier « etat-programme.json » (dans le dossier des données) dit « en marche depuis... »
pendant que le programme tourne, et « arrêté proprement le... (raison) » après un arrêt propre.
Au démarrage suivant :
- pas de fichier : premier démarrage ;
- « arrêté proprement » : arrêt propre (demandé, ou par l'onduleur) ;
- « en marche » et le Pi n'a pas redémarré depuis : le programme a planté (systemd l'a relancé) ;
- « en marche » et le Pi a redémarré depuis : le Pi s'est arrêté net (coupure de courant).
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from vidange.chef import Carnet, ErreurChef
from vidange.journal import donner_journal

journal = donner_journal("fiabilite.marche")

NOM_FICHIER = "etat-programme.json"
Sorte = Literal["premier", "propre", "plantage", "coupure"]

FICHIER_UPTIME = Path("/proc/uptime")


def lire_demarrage_pi() -> float | None:
    """Heure (secondes depuis 1970) du démarrage du Pi, ou None si on ne sait pas."""
    try:
        return time.time() - float(FICHIER_UPTIME.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


@dataclass(frozen=True)
class FinPrecedente:
    sorte: Sorte
    # Date du démarrage (plantage, coupure) ou de l'arrêt (propre) précédent.
    date: str | None = None
    raison: str | None = None

    @property
    def brutale(self) -> bool:
        return self.sorte in ("plantage", "coupure")

    def decrire(self) -> str:
        if self.sorte == "premier":
            return "premier démarrage"
        if self.sorte == "propre":
            return f"arrêt propre le {self.date} ({self.raison})"
        if self.sorte == "plantage":
            return f"le programme a planté (il tournait depuis le {self.date})"
        return (
            "le Pi s'est arrêté net, coupure de courant ? "
            f"(le programme tournait depuis le {self.date})"
        )


class Marche:
    def __init__(
        self,
        dossier_donnees: Path,
        demarrage_pi: Callable[[], float | None] = lire_demarrage_pi,
        horloge: Callable[[], float] = time.time,
    ) -> None:
        self._carnet = Carnet(dossier_donnees / NOM_FICHIER)
        self._demarrage_pi = demarrage_pi
        self._horloge = horloge

    def demarrer(self) -> FinPrecedente:
        """Lit comment s'est fini le passage précédent, puis note « en marche »."""
        fin = self._lire()
        maintenant = self._horloge()
        self._carnet.ecrire(
            {"en_marche": True, "depuis": maintenant, "date": self._date(maintenant)}
        )
        return fin

    def noter_arret(self, raison: str) -> None:
        maintenant = self._horloge()
        self._carnet.ecrire(
            {
                "en_marche": False,
                "depuis": maintenant,
                "date": self._date(maintenant),
                "raison": raison,
            }
        )

    def _lire(self) -> FinPrecedente:
        try:
            etat = self._carnet.lire()
        except ErreurChef as erreur:
            journal.error("%s : on fait comme après une coupure de courant", erreur)
            return FinPrecedente("coupure")
        if etat is None:
            return FinPrecedente("premier")
        date = etat.get("date")
        if not etat.get("en_marche"):
            return FinPrecedente("propre", date, etat.get("raison"))
        demarrage_pi = self._demarrage_pi()
        # Le Pi a redémarré après le démarrage du programme : il s'est arrêté net.
        if demarrage_pi is None or demarrage_pi > float(etat.get("depuis", 0)):
            return FinPrecedente("coupure", date)
        return FinPrecedente("plantage", date)

    @staticmethod
    def _date(moment: float) -> str:
        return datetime.fromtimestamp(moment).isoformat(timespec="seconds")
