"""Les expéditeurs : ce qui envoie vraiment une ligne de la file vers sa destination.

- ExpediteurCulture : un cycle (ou un plan d'essais appliqué, tâche 31), en JSON, vers l'app
  « machine » du logiciel de culture (HTTP POST, jeton Django REST Framework). Format :
  docs/django.md.
- ExpediteurSecours : un fichier ou un dossier, vers la maison, par la commande réglée
  (rsync par Tailscale, par exemple).

Un envoi raté lève EchecEnvoi. `refuse` : le destinataire dit que les données sont fausses ;
renvoyer les mêmes ne servirait à rien (on ne réessaie plus tout seul).
"""

import json
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from vidange.envois.cycle import donnees_cycle
from vidange.registre import Registre
from vidange.reglages import EnvoiCulture, EnvoiSecours

# Réponses du logiciel de culture qui veulent dire « données fausses » (les autres erreurs :
# jeton, adresse, serveur en panne... se règlent sans toucher aux données : on réessaie).
REFUS = (400, 422)


class EchecEnvoi(Exception):
    def __init__(self, message: str, refuse: bool = False) -> None:
        super().__init__(message)
        self.refuse = refuse


class Expediteur(Protocol):
    def envoyer(self, envoi: dict[str, Any], arret: threading.Event) -> None:
        """Envoie une ligne de la table « envois », ou lève EchecEnvoi."""


class ExpediteurCulture:
    def __init__(self, reglages: EnvoiCulture, jeton: str, registre: Registre) -> None:
        self.reglages = reglages
        self.registre = registre
        self._jeton = jeton
        self._fuseau = ZoneInfo(reglages.fuseau_horaire)
        # Jamais de proxy : le logiciel de culture est sur le réseau local.
        self._ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def donnees(self, envoi: dict[str, Any]) -> dict[str, Any]:
        if envoi["sorte"] == "essais":
            # Un plan d'essais appliqué (tâche 31), vers sa propre adresse.
            from vidange.essais.envoi import donnees_plan

            return donnees_plan(
                self.registre,
                int(envoi["objet"]),
                envoi["cle"],
                self.reglages.machine,
                self._fuseau,
            )
        if envoi["sorte"] != "cycle":
            raise EchecEnvoi(
                f"sorte « {envoi['sorte']} » inconnue du logiciel de culture", refuse=True
            )
        return donnees_cycle(
            self.registre, int(envoi["objet"]), envoi["cle"], self.reglages.machine, self._fuseau
        )

    def adresse(self, envoi: dict[str, Any]) -> str:
        if envoi["sorte"] == "essais":
            return self.reglages.adresse_essais
        return self.reglages.adresse

    def envoyer(self, envoi: dict[str, Any], arret: threading.Event) -> None:
        corps = json.dumps(self.donnees(envoi), ensure_ascii=False).encode("utf-8")
        requete = urllib.request.Request(
            self.adresse(envoi),
            data=corps,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "Authorization": f"Token {self._jeton}",
            },
        )
        try:
            with self._ouvreur.open(requete, timeout=self.reglages.delai_reponse_s) as reponse:
                reponse.read()
        except urllib.error.HTTPError as erreur:
            detail = erreur.read(300).decode("utf-8", errors="replace").strip()
            raise EchecEnvoi(
                f"le logiciel de culture répond {erreur.code} {erreur.reason}"
                + (f" : {detail}" if detail else ""),
                refuse=erreur.code in REFUS,
            ) from None
        except (urllib.error.URLError, OSError) as erreur:
            raison = getattr(erreur, "reason", erreur)
            raise EchecEnvoi(f"logiciel de culture injoignable ({raison})") from None


class ExpediteurSecours:
    def __init__(self, reglages: EnvoiSecours, donnees: Path) -> None:
        self.reglages = reglages
        self.donnees = donnees

    def envoyer(self, envoi: dict[str, Any], arret: threading.Event) -> None:
        if envoi["sorte"] != "fichier":
            raise EchecEnvoi(f"sorte « {envoi['sorte']} » inconnue de la copie de secours", True)
        chemin = self.donnees / envoi["objet"]
        if not chemin.exists():
            raise EchecEnvoi(f"« {envoi['objet']} » n'existe plus sur le Pi", refuse=True)
        commande = [morceau.replace("{chemin}", str(chemin)) for morceau in self.reglages.commande]
        with tempfile.TemporaryFile() as sortie:
            try:
                processus = subprocess.Popen(
                    commande, stdin=subprocess.DEVNULL, stdout=sortie, stderr=subprocess.STDOUT
                )
            except OSError as erreur:
                raise EchecEnvoi(
                    f"commande « {commande[0]} » impossible à lancer : {erreur}"
                ) from None
            debut = time.monotonic()
            while processus.poll() is None:
                trop_long = time.monotonic() - debut > self.reglages.duree_max_s
                if arret.wait(0.2) or trop_long:
                    processus.kill()
                    processus.wait()
                    raison = "trop longue" if trop_long else "arrêt du programme"
                    raise EchecEnvoi(f"copie interrompue ({raison})")
            if processus.returncode != 0:
                sortie.seek(0)
                texte = sortie.read()[-300:].decode("utf-8", errors="replace").strip()
                code = processus.returncode
                raise EchecEnvoi(f"« {commande[0]} » a échoué (code {code}) {texte}".strip())
