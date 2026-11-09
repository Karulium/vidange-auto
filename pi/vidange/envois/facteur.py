"""Le facteur : le fil qui vide la file d'envoi, sans jamais faire attendre la machine.

La file est la table « envois » du registre : elle survit aux coupures. Ce qui y entre :
- chaque cycle fini (Registre.finir_cycle), pour le logiciel de culture ;
- chaque copie quotidienne de la base, et le dossier des photos, pour la copie de secours
  de la maison (si sa commande est réglée) ;
- chaque message pour le téléphone (ntfy, Telegram : tâche 27, vidange/notifications), un par canal
  allumé : sans réseau ils attendent et partent plus tard, les plus vieux d'abord, sans doublon.

Tous les « periode_s », le facteur prend, pour chaque destination, les envois en attente du
plus vieux au plus récent. Un envoi qui rate (réseau coupé, serveur éteint) arrête la tournée
de cette destination : nouvel essai après une attente qui double à chaque échec (plafonnée).
Un envoi refusé (données fausses) est mis de côté avec son erreur ; les suivants partent.

Une coupure pendant un envoi : l'envoi est refait au démarrage suivant, avec la même clé ;
le destinataire reconnaît ce qu'il a déjà reçu.
"""

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from vidange.envois.expediteurs import (
    EchecEnvoi,
    Expediteur,
    ExpediteurCulture,
    ExpediteurSecours,
)
from vidange.envois.telephone import CANAUX, expediteurs_telephone
from vidange.fiabilite.constats import Constat
from vidange.fichier_secrets import Secrets
from vidange.journal import donner_journal
from vidange.registre import DOSSIER_PHOTOS, Registre
from vidange.registre.base import maintenant
from vidange.reglages import EnvoiSecours, ReglagesEnvois, ReglagesNotifications

journal = donner_journal("envois")

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DESTINATIONS = {
    "culture": "logiciel de culture",
    "secours": "copie de secours (maison)",
    "ntfy": "notifications ntfy",
    "telegram": "notifications Telegram",
}


@dataclass
class _Tournee:
    """Où en est une destination : échecs à la suite, et pas d'essai avant `prochain`."""

    echecs: int = 0
    prochain: float = 0.0


def relatif(chemin: Path, donnees: Path) -> str:
    return chemin.resolve().relative_to(donnees.resolve()).as_posix()


def mettre_en_file_secours(
    registre: Registre, reglages: EnvoiSecours, donnees: Path
) -> Callable[[Path], None] | None:
    """Ce qu'il faut faire après chaque copie quotidienne de la base : la mettre dans la file
    (elle remplace une copie plus ancienne qui attendait encore), avec le dossier des photos.
    None si la copie de secours n'est pas réglée (rien n'est mis en file)."""
    if not reglages.commande:
        return None

    def ajouter(copie: Path) -> None:
        objet = relatif(copie, donnees)
        # Une copie plus ancienne qui attend encore (« registre-AAAA-MM-JJ.sqlite », ou
        # « fichiers-AAAA-MM-JJ.tar.gz ») est remplacée par la nouvelle.
        motif = (Path(objet).parent / _DATE.sub("%", copie.name)).as_posix()
        registre.ajouter_envoi("secours", "fichier", objet, remplace=motif)
        if reglages.photos and copie.name.startswith("registre-"):
            registre.ajouter_envoi("secours", "fichier", DOSSIER_PHOTOS)

    return ajouter


class Facteur:
    def __init__(
        self,
        registre: Registre,
        reglages: ReglagesEnvois,
        expediteurs: dict[str, Expediteur | None],
        pas_regle: dict[str, str] | None = None,
        horloge: Callable[[], datetime] = maintenant,
        monotone: Callable[[], float] = time.monotonic,
    ) -> None:
        """`expediteurs` : destination → expéditeur, ou None si elle n'est pas réglée
        (ses envois attendent) ; `pas_regle` dit pourquoi, pour la check-list."""
        self.registre = registre
        self.reglages = reglages
        self.expediteurs = expediteurs
        self.pas_regle = pas_regle or {}
        self._horloge = horloge
        self._monotone = monotone
        self._tournees = {destination: _Tournee() for destination in expediteurs}
        # Une tournée à la fois : le fil du facteur et le notificateur (qui veut faire partir un
        # message tout de suite) ne doivent jamais envoyer deux fois la même ligne.
        self._verrou = threading.Lock()

    def en_attente(self, destination: str) -> list[dict[str, Any]]:
        return self.registre.lire(
            "SELECT * FROM envois WHERE destination = ? AND statut = 'attente' ORDER BY id",
            (destination,),
        )

    def tournee(self, arret: threading.Event | None = None) -> int:
        """Essaie d'envoyer ce qui attend ; rend le nombre d'envois réussis."""
        with self._verrou:
            return self._tournee(arret or threading.Event())

    def _tournee(self, arret: threading.Event) -> int:
        reussis = 0
        for destination, expediteur in self.expediteurs.items():
            tournee = self._tournees[destination]
            if expediteur is None or self._monotone() < tournee.prochain:
                continue
            for envoi in self.en_attente(destination):
                if arret.is_set():
                    return reussis
                issue = self._essayer(expediteur, envoi, tournee, arret)
                if issue == "envoye":
                    reussis += 1
                elif issue == "rate":
                    break
        jours = self.reglages.garder_envoyes_jours
        self.registre.effacer_envois(self._horloge() - timedelta(days=jours))
        return reussis

    def _essayer(
        self, expediteur: Expediteur, envoi: dict[str, Any], tournee: _Tournee, arret
    ) -> str:
        """Un essai ; rend « envoye », « refuse » ou « rate » (on réessaiera)."""
        nom = f"envoi n° {envoi['id']} ({DESTINATIONS[envoi['destination']]}, {envoi['objet']})"
        try:
            expediteur.envoyer(envoi, arret)
        except EchecEnvoi as erreur:
            if erreur.refuse:
                self.registre.noter_essai_envoi(envoi["id"], "refuse", str(erreur))
                journal.error("%s refusé : %s", nom, erreur)
                return "refuse"
            self._echec(nom, envoi, tournee, str(erreur))
            return "rate"
        except Exception as erreur:
            # Erreur imprévue (programme) : notée en entier, et on réessaiera comme pour le réseau.
            journal.exception("%s : erreur imprévue", nom)
            self._echec(nom, envoi, tournee, f"erreur imprévue : {erreur}")
            return "rate"
        self.registre.noter_essai_envoi(envoi["id"], "envoye")
        journal.info("%s : envoyé.", nom)
        tournee.echecs = 0
        tournee.prochain = 0.0
        return "envoye"

    def _echec(self, nom: str, envoi: dict[str, Any], tournee: _Tournee, erreur: str) -> None:
        self.registre.noter_essai_envoi(envoi["id"], "attente", erreur)
        tournee.echecs += 1
        attente = min(
            self.reglages.attente_premier_echec_s * 2 ** (tournee.echecs - 1),
            self.reglages.attente_max_min * 60,
        )
        tournee.prochain = self._monotone() + attente
        journal.warning("%s raté (%s) ; nouvel essai dans %d s.", nom, erreur, attente)

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        """Un fil qui fait une tournée tous les « periode_s », jusqu'à `arret`."""

        def boucle() -> None:
            while not arret.is_set():
                try:
                    self.tournee(arret)
                except Exception:
                    journal.exception("Tournée de la file d'envoi ratée, nouvel essai plus tard")
                if arret.wait(self.reglages.periode_s):
                    return

        fil = threading.Thread(target=boucle, name="file-envoi", daemon=True)
        fil.start()
        return fil

    # ------------------------------------------------------------ check-list

    def constats(self) -> list[Constat]:
        """Pour la check-list : jamais bloquant (la machine ne dépend pas du réseau)."""
        constats = []
        for destination, nom in DESTINATIONS.items():
            if destination not in self.expediteurs:
                continue
            constats.append(self._constat(destination, f"envoi : {nom}"))
        return constats

    def _constat(self, destination: str, sujet: str) -> Constat:
        attente = self.en_attente(destination)
        refuses = self.registre.lire(
            "SELECT id FROM envois WHERE destination = ? AND statut = 'refuse' ORDER BY id",
            (destination,),
        )
        if refuses:
            numeros = ", ".join(str(ligne["id"]) for ligne in refuses[:10])
            return Constat(
                sujet,
                "attention",
                f"{len(refuses)} envoi(s) refusé(s) par le destinataire (n° {numeros})",
                "Lire l'erreur (« vidange-envois etat »), corriger, puis « vidange-envois "
                "renvoyer <n°> ».",
            )
        if self.expediteurs[destination] is None:
            raison = self.pas_regle.get(destination, "pas réglé")
            if destination in CANAUX:
                return Constat(sujet, "ok", f"éteint ({raison}) ; ce n'est pas une erreur")
            texte = f"pas encore réglé ({raison})"
            if attente:
                texte += f" : {len(attente)} envoi(s) attendent dans la file"
            return Constat(sujet, "ok", texte)
        if not attente:
            return Constat(sujet, "ok", "rien en attente")
        plus_vieux = datetime.fromisoformat(attente[0]["cree_le"])
        age_h = (self._horloge() - plus_vieux).total_seconds() / 3600
        texte = f"{len(attente)} envoi(s) en attente, le plus vieux depuis {age_h:.0f} h"
        erreur = next((e["derniere_erreur"] for e in attente if e["derniere_erreur"]), None)
        if erreur:
            texte += f" ; dernière erreur : {erreur}"
        if age_h < self.reglages.signaler_apres_h:
            return Constat(sujet, "ok", texte)
        return Constat(
            sujet,
            "attention",
            texte,
            "Vérifier que le destinataire est allumé et joignable (réseau, Tailscale). "
            "Rien n'est perdu : tout partira dès qu'il répondra.",
        )


def preparer_facteur(
    registre: Registre,
    reglages: ReglagesEnvois,
    jeton_culture: str | None,
    donnees: Path,
    notifications: ReglagesNotifications | None = None,
    secrets: Secrets | None = None,
) -> Facteur:
    """Le facteur et ses expéditeurs, d'après les réglages et le jeton du fichier de secrets.
    Avec `notifications`, les canaux du téléphone (ntfy, Telegram) sont ajoutés : allumés si leurs
    secrets sont remplis, éteints sinon (la check-list le dit)."""
    expediteurs: dict[str, Expediteur | None] = {}
    pas_regle: dict[str, str] = {}
    culture = reglages.culture
    if not culture.adresse:
        pas_regle["culture"] = "adresse vide dans programme.yaml"
    elif jeton_culture is None:
        pas_regle["culture"] = "pas de « jeton_culture » dans le fichier de secrets"
    expediteurs["culture"] = (
        None if "culture" in pas_regle else ExpediteurCulture(culture, jeton_culture, registre)
    )
    if reglages.secours.commande:
        expediteurs["secours"] = ExpediteurSecours(reglages.secours, donnees)
    else:
        expediteurs["secours"] = None
        pas_regle["secours"] = "commande vide dans programme.yaml"
    if notifications is not None:
        canaux, pas_regle_canaux = expediteurs_telephone(
            notifications, secrets or Secrets(), registre
        )
        expediteurs.update(canaux)
        pas_regle.update(pas_regle_canaux)
    for destination, raison in pas_regle.items():
        if destination in CANAUX:
            journal.info("Notifications « %s » éteintes : %s.", DESTINATIONS[destination], raison)
            continue
        journal.warning("Envoi « %s » pas encore réglé : %s.", DESTINATIONS[destination], raison)
    return Facteur(registre, reglages, expediteurs, pas_regle)
