"""Les messages pour le téléphone : ntfy (HTTP POST vers un serveur et un sujet) et, en option,
Telegram (HTTP POST vers l'API d'un bot). Aucune bibliothèque de plus : urllib.

Ce sont des expéditeurs de la file d'envoi (voir facteur.py) : une ligne de la table « envois »
(destination « ntfy » ou « telegram », sorte « message ») = un message pour un canal. Un canal
dont les secrets ne sont pas remplis est éteint : rien n'est mis dans la file pour lui.

Le contenu d'un message (JSON, colonne « contenu ») :
    niveau       « urgent », « normal » ou « info »
    titre, texte ce qui est dit, en français
    lien         la page web (vide : aucun)
    groupe       « principal » ou « renfort » (2ᵉ liste de destinataires de l'escalade)
    rappel       vrai pour une alarme urgente renvoyée (priorité la plus haute)
    prevu_le     l'heure où le message a été préparé
    annuler_si_vue   numéro d'une alarme : si elle a été vue ou effacée entre-temps, le message
                 (rappel, renfort) n'est plus utile et ne part pas

Ces messages INFORMENT : ils ne protègent personne (la sécurité est câblée, jamais ici).
"""

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from typing import Any

from vidange.envois.expediteurs import EchecEnvoi, Expediteur
from vidange.fichier_secrets import Secrets
from vidange.journal import donner_journal
from vidange.registre import Registre
from vidange.registre.base import maintenant
from vidange.reglages import ReglagesNotifications

journal = donner_journal("envois.telephone")

CANAUX = ("ntfy", "telegram")
# ntfy dit « 400 » quand le message lui-même est faux : renvoyer le même ne servirait à rien.
REFUS_NTFY = (400, 413)
# Les serveurs coupent au-delà de 4096 caractères.
LONGUEUR_MAX = 3500

_TAGS_NTFY = {"urgent": "rotating_light", "normal": "warning", "info": "information_source"}


def decrire_contenu(contenu: str | None) -> dict[str, Any]:
    try:
        donnees = json.loads(contenu or "")
    except ValueError:
        raise EchecEnvoi("contenu du message illisible", refuse=True) from None
    if not isinstance(donnees, dict) or "texte" not in donnees:
        raise EchecEnvoi("contenu du message sans texte", refuse=True)
    return donnees


class _Message:
    """Un message prêt à partir : ce qu'il dit, avec « en retard » s'il a trop attendu."""

    def __init__(
        self,
        envoi: dict[str, Any],
        reglages: ReglagesNotifications,
        registre: Registre,
        horloge: Callable[[], datetime],
    ) -> None:
        contenu = decrire_contenu(envoi.get("contenu"))
        self.niveau = contenu.get("niveau", "info")
        self.groupe = contenu.get("groupe", "principal")
        self.rappel = bool(contenu.get("rappel"))
        self.lien = contenu.get("lien") or ""
        self.titre = str(contenu.get("titre") or "Vidange automatique")
        self.texte = str(contenu["texte"])
        prevu = datetime.fromisoformat(envoi["cree_le"])
        retard_min = (horloge() - prevu).total_seconds() / 60
        if retard_min > reglages.en_retard_apres_min:
            quand = prevu.astimezone().strftime("%H:%M")
            self.titre += " (en retard)"
            self.texte = (
                f"[En retard : préparé à {quand}, parti seulement maintenant.]\n{self.texte}"
            )
        self.annuler = False
        alarme = contenu.get("annuler_si_vue")
        if alarme is not None:
            lignes = registre.lire(
                "SELECT vue_le, acquittee_le FROM alarmes WHERE id = ?", (int(alarme),)
            )
            self.annuler = bool(lignes and (lignes[0]["vue_le"] or lignes[0]["acquittee_le"]))

    def texte_complet(self) -> str:
        return self.texte[:LONGUEUR_MAX]


def _poster(
    adresse: str, corps: dict[str, Any], entetes: dict[str, str], delai_s: float, refus: tuple
) -> None:
    requete = urllib.request.Request(
        adresse,
        data=json.dumps(corps, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8", **entetes},
    )
    try:
        # Les proxys de l'environnement sont respectés : c'est Internet, pas le réseau local.
        with urllib.request.urlopen(requete, timeout=delai_s) as reponse:
            reponse.read()
    except urllib.error.HTTPError as erreur:
        raise EchecEnvoi(
            f"le serveur répond {erreur.code} {erreur.reason}", refuse=erreur.code in refus
        ) from None
    except (urllib.error.URLError, OSError) as erreur:
        # Jamais l'adresse dans le message : elle contient le jeton (Telegram).
        raison = getattr(erreur, "reason", erreur)
        raise EchecEnvoi(f"serveur injoignable ({raison})") from None


class ExpediteurNtfy:
    def __init__(
        self,
        reglages: ReglagesNotifications,
        serveur: str,
        sujets: list[str],
        sujets_renfort: list[str],
        jeton: str | None,
        registre: Registre,
        horloge: Callable[[], datetime] = maintenant,
    ) -> None:
        self.reglages = reglages
        self.serveur = serveur
        self.sujets = {"principal": sujets, "renfort": sujets_renfort}
        self._jeton = jeton
        self.registre = registre
        self._horloge = horloge

    def a_renfort(self) -> bool:
        """Vrai si la 2ᵉ liste de destinataires (escalade) est remplie."""
        return bool(self.sujets["renfort"])

    def envoyer(self, envoi: dict[str, Any], arret: threading.Event) -> None:
        if envoi["sorte"] != "message":
            raise EchecEnvoi(f"sorte « {envoi['sorte']} » inconnue de ntfy", refuse=True)
        message = _Message(envoi, self.reglages, self.registre, self._horloge)
        if message.annuler:
            journal.info("ntfy : « %s » n'est plus utile (alarme vue ou effacée).", envoi["objet"])
            return
        priorites = self.reglages.priorites_ntfy
        priorite = priorites.rappel if message.rappel else getattr(priorites, message.niveau)
        entetes = {"Authorization": f"Bearer {self._jeton}"} if self._jeton else {}
        for sujet in self.sujets.get(message.groupe, []):
            corps: dict[str, Any] = {
                "topic": sujet,
                "title": message.titre,
                "message": message.texte_complet(),
                "priority": priorite,
                "tags": [_TAGS_NTFY.get(message.niveau, "information_source")],
            }
            if message.lien:
                corps["click"] = message.lien
            _poster(self.serveur, corps, entetes, self.reglages.delai_reponse_s, REFUS_NTFY)


class ExpediteurTelegram:
    def __init__(
        self,
        reglages: ReglagesNotifications,
        jeton_bot: str,
        chats: list[str],
        chats_renfort: list[str],
        registre: Registre,
        horloge: Callable[[], datetime] = maintenant,
    ) -> None:
        self.reglages = reglages
        self._jeton_bot = jeton_bot
        self.chats = {"principal": chats, "renfort": chats_renfort}
        self.registre = registre
        self._horloge = horloge

    def a_renfort(self) -> bool:
        """Vrai si la 2ᵉ liste de destinataires (escalade) est remplie."""
        return bool(self.chats["renfort"])

    def envoyer(self, envoi: dict[str, Any], arret: threading.Event) -> None:
        if envoi["sorte"] != "message":
            raise EchecEnvoi(f"sorte « {envoi['sorte']} » inconnue de Telegram", refuse=True)
        message = _Message(envoi, self.reglages, self.registre, self._horloge)
        if message.annuler:
            journal.info(
                "Telegram : « %s » n'est plus utile (alarme vue ou effacée).", envoi["objet"]
            )
            return
        adresse = f"{self.reglages.telegram_adresse.rstrip('/')}/bot{self._jeton_bot}/sendMessage"
        texte = f"{message.titre}\n{message.texte_complet()}"[:LONGUEUR_MAX]
        for chat in self.chats.get(message.groupe, []):
            corps = {
                "chat_id": chat,
                "text": texte,
                # Un message « info » arrive sans sonnerie.
                "disable_notification": message.niveau == "info",
            }
            _poster(adresse, corps, {}, self.reglages.delai_reponse_s, ())


def expediteurs_telephone(
    reglages: ReglagesNotifications,
    secrets: Secrets,
    registre: Registre,
    horloge: Callable[[], datetime] = maintenant,
) -> tuple[dict[str, Expediteur | None], dict[str, str]]:
    """Les expéditeurs ntfy et Telegram d'après le fichier de secrets, et pour chaque canal éteint
    la raison (pour la check-list). Un secret vide n'est pas une erreur : le canal est éteint."""
    expediteurs: dict[str, Expediteur | None] = {}
    pas_regle: dict[str, str] = {}
    manque = [
        nom
        for nom, valeur in (
            ("ntfy_serveur", secrets.ntfy_serveur),
            ("ntfy_sujet", secrets.ntfy_sujet),
        )
        if not valeur
    ]
    if manque:
        pas_regle["ntfy"] = (
            "pas de « " + " » ni de « ".join(manque) + " » dans le fichier de secrets"
        )
        expediteurs["ntfy"] = None
    else:
        expediteurs["ntfy"] = ExpediteurNtfy(
            reglages,
            secrets.ntfy_serveur,
            [secrets.ntfy_sujet.get_secret_value()],
            [sujet.get_secret_value() for sujet in secrets.ntfy_sujets_renfort],
            secrets.ntfy_jeton.get_secret_value() if secrets.ntfy_jeton else None,
            registre,
            horloge,
        )
    manque = [
        nom
        for nom, valeur in (
            ("telegram_jeton_bot", secrets.telegram_jeton_bot),
            ("telegram_chat", secrets.telegram_chat),
        )
        if not valeur
    ]
    if manque:
        pas_regle["telegram"] = (
            "pas de « " + " » ni de « ".join(manque) + " » dans le fichier de secrets"
        )
        expediteurs["telegram"] = None
    else:
        expediteurs["telegram"] = ExpediteurTelegram(
            reglages,
            secrets.telegram_jeton_bot.get_secret_value(),
            [secrets.telegram_chat.get_secret_value()],
            [chat.get_secret_value() for chat in secrets.telegram_chats_renfort],
            registre,
            horloge,
        )
    return expediteurs, pas_regle
