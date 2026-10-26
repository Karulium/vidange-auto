"""Chien de garde Pi ↔ cartes (fonction 14).

Dans les deux sens :
- **le Pi surveille les cartes FluidNC** : la liaison voit déjà une carte muette ou débranchée
  (et se reconnecte seule) ; ici on garde le compte des coupures et des redémarrages tout seuls
  d'une carte (signe d'une alimentation ou d'un câble qui flanche), et on en fait des constats ;
- **le Pi se fait surveiller** : tant que le chef d'orchestre tourne, le programme dit
  « je vis » à systemd (WatchdogSec dans vidange.service). S'il se fige, il se tait, et systemd
  le relance. Le Pi lui-même est surveillé par son chien de garde matériel (procédure
  d'installation), qui le redémarre si tout le système se fige.
  Si la sortie « battement_pi » existe dans la liste des entrées/sorties, le Pi la fait battre
  au même rythme : un relais « chien de garde » branché dessus peut mettre les cartes FluidNC
  en pause quand le Pi se fige (matériel pas encore décidé, voir la PR de la tâche 7).

Rappel : rien de cela ne protège les personnes (sécurité câblée). Un Pi figé laisse au pire
une carte finir le mouvement qu'elle a déjà reçu (positions absolues, dans ses limites).
"""

import os
import socket
import threading
import time
from collections.abc import Callable, Mapping

from vidange.chef import Chef
from vidange.fiabilite.constats import Constat, lancer_boucle
from vidange.fluidnc import Liaison
from vidange.journal import donner_journal
from vidange.materiel import ErreurMateriel, Materiel
from vidange.quoi_faire import CARTE_COUPEE, CARTE_REDEMARREE, pour_carte
from vidange.reglages import ReglagesChienDeGarde

journal = donner_journal("fiabilite.chien_de_garde")

BATTEMENT = "battement_pi"


def notifier_systemd(message: str) -> bool:
    """Envoie un message à systemd (READY=1, WATCHDOG=1...). Rend False hors de systemd."""
    adresse = os.environ.get("NOTIFY_SOCKET")
    if not adresse:
        return False
    if adresse.startswith("@"):
        adresse = "\0" + adresse[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as prise:
            prise.connect(adresse)
            prise.sendall(message.encode("ascii"))
    except OSError as erreur:
        journal.error("Message à systemd impossible (%s) : %s", message, erreur)
        return False
    return True


class ChienDeGarde:
    def __init__(
        self,
        reglages: ReglagesChienDeGarde,
        liaisons: Mapping[str, Liaison],
        chef: Chef | None = None,
        materiel: Materiel | None = None,
        notifier: Callable[[str], bool] = notifier_systemd,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        """`horloge` doit être celle du chef (time.monotonic par défaut)."""
        self.reglages = reglages
        self.liaisons = dict(liaisons)
        self.chef = chef
        self.materiel = materiel
        self._notifier = notifier
        self._horloge = horloge
        self._debut = horloge()
        self._verrou = threading.Lock()
        self._redemarrages = {nom: 0 for nom in self.liaisons}
        self._chef_fige = False
        self._systemd: bool | None = None
        self._battement = False
        self._battement_en_panne = False

    @property
    def battement_branche(self) -> bool:
        return self.materiel is not None and BATTEMENT in self.materiel.branchements

    def pret(self) -> None:
        """Le programme a fini de démarrer (systemd attend ce message : Type=notify)."""
        self._systemd = self._notifier("READY=1")

    def tour(self) -> None:
        self._surveiller_cartes()
        vivant = self._chef_vivant()
        if vivant:
            self._notifier("WATCHDOG=1")
        self._battre(vivant)

    def arreter(self) -> None:
        """Arrêt propre : on prévient systemd, le battement s'arrête (sortie au repos)."""
        self._notifier("STOPPING=1")
        if self.battement_branche:
            try:
                self.materiel.ecrire(BATTEMENT, False)
            except ErreurMateriel as erreur:
                journal.error("Battement : %s", erreur)

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        return lancer_boucle("chien_de_garde", self.reglages.periode_s, self.tour, arret)

    # ------------------------------------------------------------ ce qu'on surveille

    def _surveiller_cartes(self) -> None:
        for nom, liaison in self.liaisons.items():
            etat = liaison.etat
            with self._verrou:
                avant = self._redemarrages[nom]
                self._redemarrages[nom] = etat.redemarrages
            if etat.redemarrages > avant:
                journal.error(
                    "La carte « %s » a redémarré toute seule (%d fois depuis le démarrage du "
                    "programme). %s",
                    nom,
                    etat.redemarrages,
                    CARTE_REDEMARREE,
                )

    def _chef_vivant(self) -> bool:
        if self.chef is None:
            return True
        dernier = self.chef.dernier_tour
        # Pas encore de tour : on compte depuis la création du chien de garde.
        retard = self._horloge() - (self._debut if dernier is None else dernier)
        fige = retard > self.reglages.chef_fige_s
        if fige and not self._chef_fige:
            journal.error(
                "Le chef d'orchestre ne tourne plus (dernier tour il y a %.0f s) : le programme "
                "ne dit plus « je vis » à systemd, qui va le relancer.",
                retard,
            )
        elif not fige and self._chef_fige:
            journal.info("Le chef d'orchestre tourne de nouveau.")
        self._chef_fige = fige
        return not fige

    def _battre(self, vivant: bool) -> None:
        if not self.battement_branche or not vivant:
            return
        self._battement = not self._battement
        try:
            self.materiel.ecrire(BATTEMENT, self._battement)
        except ErreurMateriel as erreur:
            if not self._battement_en_panne:
                journal.error("Battement du Pi impossible : %s", erreur)
            self._battement_en_panne = True
            return
        self._battement_en_panne = False

    # ------------------------------------------------------------ constats

    def constats(self) -> list[Constat]:
        constats = []
        for nom, liaison in self.liaisons.items():
            sujet = f"carte « {nom} »"
            etat = liaison.etat
            probleme = pour_carte(etat)
            if probleme is not None:
                constats.append(Constat(sujet, "bloquant", *probleme))
            elif etat.redemarrages:
                constats.append(
                    Constat(
                        sujet,
                        "attention",
                        f"a redémarré toute seule {etat.redemarrages} fois",
                        CARTE_REDEMARREE,
                    )
                )
            elif etat.coupures:
                texte = f"liaison coupée {etat.coupures} fois"
                constats.append(Constat(sujet, "attention", texte, CARTE_COUPEE))
            else:
                constats.append(Constat(sujet, "ok", "connectée, sans alarme"))
        if self._chef_fige:
            constats.append(
                Constat(
                    "chef d'orchestre",
                    "bloquant",
                    "figé",
                    "Le programme va être relancé par systemd ; sinon redémarrer le Pi.",
                )
            )
        if self._systemd is False:
            constats.append(
                Constat(
                    "chien de garde",
                    "inconnu",
                    "programme pas lancé par systemd : personne ne le relance s'il se fige",
                )
            )
        if not self.battement_branche:
            constats.append(
                Constat(
                    "chien de garde",
                    "inconnu",
                    "pas de sortie « battement_pi » : les cartes ne voient pas un Pi figé",
                )
            )
        elif self._battement_en_panne:
            constats.append(
                Constat(
                    "chien de garde",
                    "attention",
                    "sortie « battement_pi » en panne",
                    "Vérifier le câble du relais chien de garde.",
                )
            )
        return constats
