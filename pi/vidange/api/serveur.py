"""Le serveur web de l'API (uvicorn), dans un fil à part du programme.

    serveur = ServeurApi(app, reglages.programme.api)
    serveur.demarrer()
    serveur.arreter()

Un serveur qui plante (port déjà pris...) ne fait pas tomber la machine : l'écran de l'armoire
reste là. La check-list le signale (`constats_api`).
"""

import threading
import time

import uvicorn
from fastapi import FastAPI

from vidange.fiabilite.constats import Constat
from vidange.journal import donner_journal
from vidange.reglages import ReglagesApi

journal = donner_journal("api")

SUJET = "API et page web"
QUOI_FAIRE_CLE = (
    "Mettre une clé dans « cle_api » du fichier de secrets (voir pi/systeme/installation.md), "
    "puis redémarrer le programme."
)


class ServeurApi:
    def __init__(self, app: FastAPI, reglages: ReglagesApi) -> None:
        self.reglages = reglages
        config = uvicorn.Config(
            app,
            host=reglages.adresse,
            port=reglages.port,
            # Le journal de uvicorn reste le sien : on note nous-mêmes ce qui compte.
            log_config=None,
            access_log=False,
            lifespan="off",
        )
        self._serveur = uvicorn.Server(config)
        self._fil: threading.Thread | None = None

    def demarrer(self, attente_s: float = 5) -> threading.Thread:
        """Lance le serveur et attend (au plus `attente_s`) qu'il écoute, ou qu'il échoue."""
        self._fil = threading.Thread(target=self._tourner, name="api", daemon=True)
        self._fil.start()
        fin = time.monotonic() + attente_s
        while not self._serveur.started and self._fil.is_alive() and time.monotonic() < fin:
            time.sleep(0.05)
        if self.en_route:
            adresse, port = self.reglages.adresse, self.reglages.port
            journal.info("API et page web à l'écoute : http://%s:%d", adresse, port)
        return self._fil

    def _tourner(self) -> None:
        try:
            self._serveur.run()
        except BaseException as erreur:
            # uvicorn quitte par SystemExit si le port est déjà pris.
            journal.error(
                "L'API s'est arrêtée (port %d déjà pris ?) : %r", self.reglages.port, erreur
            )
            return
        journal.info("API arrêtée")

    def arreter(self, delai_s: float = 10) -> None:
        self._serveur.should_exit = True
        if self._fil is not None:
            self._fil.join(delai_s)

    @property
    def en_route(self) -> bool:
        return self._serveur.started and self._fil is not None and self._fil.is_alive()


def constats_api(serveur: ServeurApi | None) -> list[Constat]:
    """Pour la check-list. Sans API, la machine peut tourner : jamais bloquant."""
    if serveur is None:
        texte = "pas de clé : l'API n'est pas démarrée"
        return [Constat(SUJET, "attention", texte, QUOI_FAIRE_CLE)]
    if not serveur.en_route:
        return [
            Constat(
                SUJET,
                "attention",
                f"l'API ne répond pas (port {serveur.reglages.port})",
                "Lire le journal (port déjà pris par un autre programme ?), puis redémarrer.",
            )
        ]
    return [Constat(SUJET, "ok", f"à l'écoute sur le port {serveur.reglages.port}")]
