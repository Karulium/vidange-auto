"""Qui a le droit de quoi, pour l'API (tâche 25).

- `Exige(niveau, ...)` : la « dépendance » FastAPI que chaque route de l'API déclare. Elle lit le
  cookie de session, refuse si personne n'est connecté (401) ou si le rôle ne suffit pas (403), et
  note au journal des actions qui a demandé quoi (niveau « produire » ou « régler »).
- `verifier_roles_declares(app)` : au démarrage, refuse une route sans niveau déclaré.
- `JournalActions` : le journal « qui a fait quoi » (un fichier de lignes JSON, dans les données,
  donc dans la copie de secours).
- `LimiteConnexions` : après trop d'essais de mot de passe ratés depuis une adresse, elle est
  bloquée un moment.
"""

import json
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute

from vidange.comptes import Comptes, ErreurComptes, Niveau
from vidange.journal import donner_journal

journal = donner_journal("api")

COOKIE = "vidange_session"
NOM_JOURNAL_ACTIONS = "actions.jsonl"

# Seules routes sans niveau : la page elle-même, et de quoi se connecter / savoir où on en est.
ROUTES_PUBLIQUES = {
    ("GET", "/"),
    ("GET", "/api/moi"),
    ("POST", "/api/connexion"),
    ("POST", "/api/deconnexion"),
}

_MOTS = {Niveau.REGARDER: "regarder", Niveau.PRODUIRE: "produire", Niveau.REGLER: "régler"}
_ROLES = {Niveau.REGARDER: "visiteur", Niveau.PRODUIRE: "employé", Niveau.REGLER: "karulium"}


def mot_du_niveau(niveau: Niveau) -> str:
    return _MOTS[niveau]


class JournalActions:
    """Une ligne JSON par action « produire » ou « régler » (et par connexion)."""

    def __init__(self, chemin: Path, horloge: Callable[[], datetime] = datetime.now) -> None:
        self.chemin = chemin
        self._horloge = horloge
        self._verrou = threading.Lock()

    def noter(self, **champs: Any) -> None:
        ligne = {"quand": self._horloge().isoformat(timespec="seconds"), **champs}
        with self._verrou:
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
            with self.chemin.open("a", encoding="utf-8") as fichier:
                fichier.write(json.dumps(ligne, ensure_ascii=False) + "\n")

    def dernieres(self, nombre: int) -> list[dict[str, Any]]:
        """Les dernières actions, la plus récente d'abord."""
        if not self.chemin.exists():
            return []
        with self._verrou:
            lignes = self.chemin.read_text(encoding="utf-8").splitlines()
        resultat = []
        for ligne in reversed(lignes):
            try:
                resultat.append(json.loads(ligne))
            except ValueError:
                continue
            if len(resultat) >= nombre:
                break
        return resultat


class LimiteConnexions:
    """Compte les mots de passe ratés par adresse ; trop d'essais = adresse bloquée un moment."""

    def __init__(
        self, essais_max: int, blocage_s: float, horloge: Callable[[], float] = time.monotonic
    ) -> None:
        self.essais_max = essais_max
        self.blocage_s = blocage_s
        self._horloge = horloge
        self._ratees: dict[str, list[float]] = {}
        self._verrou = threading.Lock()

    def attente_s(self, adresse: str) -> float:
        """0 si l'adresse peut essayer ; sinon le nombre de secondes à attendre."""
        with self._verrou:
            maintenant = self._horloge()
            recents = [t for t in self._ratees.get(adresse, []) if maintenant - t < self.blocage_s]
            self._ratees[adresse] = recents
            if len(recents) < self.essais_max:
                return 0
            return recents[0] + self.blocage_s - maintenant

    def rater(self, adresse: str) -> None:
        with self._verrou:
            self._ratees.setdefault(adresse, []).append(self._horloge())

    def reussir(self, adresse: str) -> None:
        with self._verrou:
            self._ratees.pop(adresse, None)


class Exige:
    """Dépendance FastAPI : « cette route demande au moins ce niveau »."""

    def __init__(
        self,
        niveau: Niveau,
        comptes: Comptes,
        actions: JournalActions,
        journaliser: bool = True,
    ) -> None:
        self.niveau = niveau
        self.comptes = comptes
        self.actions = actions
        # Seules les actions « produire » et « régler » sont notées au journal des actions.
        self.journaliser = journaliser and niveau >= Niveau.PRODUIRE

    def __call__(self, requete: Request) -> None:
        adresse = requete.client.host if requete.client else "adresse inconnue"
        if self.comptes.vide:
            raise HTTPException(
                503,
                "aucun compte : en créer un sur le Pi (« vidange compte ajouter », voir la page "
                "d'accueil)",
            )
        compte = self.comptes.lire_session(requete.cookies.get(COOKIE))
        if compte is None:
            raise HTTPException(401, "connexion demandée (nom et mot de passe)")
        if not compte.role.permet(self.niveau):
            journal.warning(
                "Droit insuffisant : %s (%s, %s) demande « %s » sur %s",
                compte.nom,
                compte.role.nom,
                adresse,
                mot_du_niveau(self.niveau),
                requete.url.path,
            )
            raise HTTPException(
                403,
                f"droit insuffisant : « {mot_du_niveau(self.niveau)} » demande le rôle "
                f"{_ROLES[self.niveau]} ou plus (vous êtes {compte.role.nom})",
            )
        requete.state.compte = compte
        if self.journaliser:
            self.actions.noter(
                qui=compte.nom,
                role=compte.role.nom,
                adresse=adresse,
                niveau=mot_du_niveau(self.niveau),
                methode=requete.method,
                chemin=requete.url.path,
            )


def verifier_roles_declares(app: Any) -> None:
    """Chaque route dit son niveau (ou est publique), sinon le programme ne démarre pas."""
    sans_niveau = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            sans_niveau.append(f"{route.path} (route qui n'est pas une route de l'API)")
            continue
        declare = any(isinstance(d.dependency, Exige) for d in route.dependencies)
        for methode in sorted(route.methods - {"HEAD"}):
            if not declare and (methode, route.path) not in ROUTES_PUBLIQUES:
                sans_niveau.append(f"{methode} {route.path}")
    if sans_niveau:
        raise ErreurComptes(
            "routes de l'API sans niveau de droit déclaré (regarder, produire ou régler) :\n"
            + "\n".join(f"  - {route}" for route in sans_niveau)
        )
