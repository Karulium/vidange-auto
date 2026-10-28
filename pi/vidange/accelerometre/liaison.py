"""Liaison du Pi avec le RP2040 de l'accéléromètre, par le fil série unique (half-duplex).

    liaison = LiaisonAccelerometre(reglages.accelerometre, ouvrir_port("/dev/ttyAMA0", 115200),
                                   registre)
    fil = liaison.demarrer(arret)      # un tour toutes les « periode_ms »
    liaison.constats()                 # pour la check-list

À chaque tour, le Pi demande l'état du RP2040, puis chaque nouveau choc, qu'il note au
registre (table des mesures : « choc » en g et « choc_duree » en ms, capteur
« accelerometre_fil ») et au journal. La plus forte vibration est notée au registre toutes
les « niveau_max_s » (« vibration_max », en g), pour aider à choisir le seuil.
Le RP2040 garde ses 16 derniers chocs : un silence du fil ou un redémarrage du programme du
Pi ne fait rien perdre (et un choc déjà au registre n'est pas noté deux fois).

Au premier contact, et après chaque redémarrage ou silence du RP2040, le Pi lit ses réglages
et lui envoie ceux de accelerometre.yaml s'ils sont différents (`envoyer_reglages`).

Le Pi entend aussi ce qu'il envoie (son TX et son RX sont sur le même fil) : il ne garde que
la ligne qui répond à sa question. Le RP2040 ne parle jamais sans question.

Rien de tout cela ne protège : la sortie « OK » du RP2040 va directement à l'ESP32 n° 1.
Le Pi enregistre et informe seulement ; un Pi absent ne change rien aux chocs.
"""

import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Protocol

import serial

from vidange.accelerometre.protocole import (
    HISTORIQUE_CHOCS,
    Choc,
    Decodeur,
    ErreurProtocole,
    EtatRp2040,
    lire_reglages,
    question_regler,
    reglages_pour_rp2040,
    texte_pannes,
    trame,
)
from vidange.fiabilite.constats import Constat, lancer_boucle
from vidange.journal import donner_journal
from vidange.registre import ErreurRegistre, Registre
from vidange.registre.base import maintenant
from vidange.reglages import ReglagesAccelerometre

journal = donner_journal("accelerometre")

SUJET = "accéléromètre"
# Le signal de docs/entrees-sorties.yaml qui mène au RP2040 (son « fichier » : l'UART du Pi).
SIGNAL = "accelerometre_fil"


class PortAccelerometre(Protocol):
    """Ce que la liaison utilise d'un port série (pyserial ou le faux RP2040)."""

    def write(self, donnees: bytes) -> Any: ...

    def read(self, taille: int) -> bytes:
        """Ce qui est arrivé (au plus `taille` octets), en attendant un court instant."""
        ...

    def reset_input_buffer(self) -> None: ...

    def close(self) -> None: ...


def ouvrir_port(fichier: str, vitesse_bauds: int) -> Callable[[], PortAccelerometre]:
    """De quoi ouvrir le vrai port (fichier de Linux de l'UART, dans entrees-sorties.yaml)."""
    return lambda: serial.Serial(fichier, vitesse_bauds, timeout=0.005, write_timeout=1)


class LiaisonAccelerometre:
    def __init__(
        self,
        reglages: ReglagesAccelerometre,
        ouvrir: Callable[[], PortAccelerometre],
        registre: Registre | None = None,
        horloge: Callable[[], float] = time.monotonic,
        heure: Callable[[], datetime] = maintenant,
    ) -> None:
        self.reglages = reglages
        self._liaison = reglages.liaison
        self._ouvrir = ouvrir
        self._registre = registre
        self._horloge = horloge
        self._heure = heure
        self._verrou = threading.Lock()
        self._port: PortAccelerometre | None = None
        self._derniere_ouverture: float | None = None
        self._erreur_ouverture: str | None = None
        self._sans_reponse = 0
        self._muet_signale = False
        # Ce qu'on sait du RP2040.
        self.etat: EtatRp2040 | None = None  # None : il ne répond pas
        self._precedent: EtatRp2040 | None = None
        self._dernier_choc = 0  # dernier choc noté (numéro du RP2040)
        self._deja_notes_avant: datetime | None = None
        self._reglages_a_voir = True
        self._reglages_refuses: str | None = None
        self._niveau_max_mg = 0
        self._debut_niveau: float | None = None

    # ------------------------------------------------------------ questions

    def demander(self, question: str) -> str | None:
        """Pose une question et rend la réponse (sans le contrôle), ou None sans réponse."""
        with self._verrou:
            return self._demander(question)

    def _demander(self, question: str) -> str | None:
        if self._port is None and not self._essayer_ouvrir():
            return None
        assert self._port is not None
        mot = question.split(" ", 1)[0]
        decodeur = Decodeur()
        try:
            self._port.reset_input_buffer()
            self._port.write(trame(question))
            limite = self._horloge() + self._liaison.attente_reponse_ms / 1000
            while self._horloge() < limite:
                for texte in decodeur.ajouter(self._port.read(256)):
                    # Notre propre question revient (même fil) : on la saute.
                    if texte == question:
                        continue
                    if texte.split(" ", 1)[0] in (mot, "ERREUR"):
                        return texte
        except (OSError, serial.SerialException) as erreur:
            self._perdre(f"liaison coupée : {erreur}")
        return None

    def _essayer_ouvrir(self) -> bool:
        maintenant_s = self._horloge()
        if (
            self._derniere_ouverture is not None
            and maintenant_s - self._derniere_ouverture < self._liaison.reconnexion_s
        ):
            return False
        self._derniere_ouverture = maintenant_s
        try:
            self._port = self._ouvrir()
        except Exception as erreur:
            if self._erreur_ouverture != str(erreur):
                journal.error("Accéléromètre : port série impossible à ouvrir : %s", erreur)
            self._erreur_ouverture = str(erreur)
            return False
        journal.info("Accéléromètre : port série ouvert")
        self._erreur_ouverture = None
        return True

    def _perdre(self, raison: str) -> None:
        journal.error("Accéléromètre : %s", raison)
        self.fermer()

    # ------------------------------------------------------------ chaque tour

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        return lancer_boucle("accelerometre", self._liaison.periode_ms / 1000, self.tour, arret)

    def tour(self) -> None:
        """Demande l'état, note les nouveaux chocs, la vibration, et envoie les réglages."""
        with self._verrou:
            reponse = self._demander("ETAT")
            if reponse is None:
                self._silence()
                return
            try:
                etat = EtatRp2040.lire(reponse)
            except ErreurProtocole as erreur:
                journal.warning("Accéléromètre : %s", erreur)
                return
            self._recevoir_etat(etat)
            self._lire_chocs(etat)
            self._noter_niveau(etat)
            if self._reglages_a_voir and self._liaison.envoyer_reglages:
                self._accorder_reglages()

    def _silence(self) -> None:
        self._sans_reponse += 1
        if self._sans_reponse >= self._liaison.sans_reponse_max and not self._muet_signale:
            self._muet_signale = True
            self._reglages_a_voir = True
            self.etat = None
            journal.warning(
                "Accéléromètre : il ne répond pas (fil série, alimentation du boîtier ?)"
            )

    def _recevoir_etat(self, etat: EtatRp2040) -> None:
        # Le dernier état reçu, même avant un silence : on sait ainsi si le RP2040 a redémarré.
        precedent = self._precedent
        if self._muet_signale:
            journal.info("Accéléromètre : il répond")
        self._sans_reponse = 0
        self._muet_signale = False
        if precedent is None or etat.t_ms < precedent.t_ms:
            self._nouveau_demarrage(etat, premier=precedent is None)
        elif etat.pannes != precedent.pannes:
            if etat.pannes:
                journal.warning(
                    "Accéléromètre : panne (%s) : « OK » coupé", texte_pannes(etat.pannes)
                )
            else:
                journal.info("Accéléromètre : panne finie (%s)", texte_pannes(precedent.pannes))
        if etat.sortie_contredit and (precedent is None or not precedent.sortie_contredit):
            journal.warning(
                "Accéléromètre : la broche « OK » ne suit pas ce que le RP2040 lui commande "
                "(court-circuit, câblage de l'optocoupleur ?)"
            )
        self.etat = self._precedent = etat

    def _nouveau_demarrage(self, etat: EtatRp2040, premier: bool) -> None:
        if not premier:
            journal.warning("Accéléromètre : le RP2040 a redémarré")
        if etat.redemarre_par_chien:
            journal.warning(
                "Accéléromètre : son dernier démarrage vient du chien de garde "
                "(son programme s'était figé)"
            )
        if etat.pannes:
            journal.warning("Accéléromètre : panne (%s) : « OK » coupé", texte_pannes(etat.pannes))
        self._reglages_a_voir = True
        # Les numéros de chocs repartent de 1 après un redémarrage du RP2040.
        self._dernier_choc = 0
        self._deja_notes_avant = None
        if premier:
            # Le programme du Pi vient de démarrer (le RP2040, peut-être pas) : on prend les
            # chocs que le RP2040 garde encore, sauf ceux déjà au registre.
            self._dernier_choc = max(0, etat.chocs - HISTORIQUE_CHOCS)
            self._deja_notes_avant = self._dernier_choc_au_registre()

    def _dernier_choc_au_registre(self) -> datetime | None:
        if self._registre is None:
            return None
        try:
            lignes = self._registre.lire(
                "SELECT MAX(quand) AS quand FROM mesures WHERE nom = 'choc' AND capteur = ?",
                (SIGNAL,),
            )
        except ErreurRegistre as erreur:
            journal.error("Accéléromètre : registre illisible : %s", erreur)
            return None
        quand = lignes[0]["quand"] if lignes else None
        return datetime.fromisoformat(quand) if quand else None

    def _lire_chocs(self, etat: EtatRp2040) -> None:
        while self._dernier_choc < etat.chocs:
            numero = self._dernier_choc + 1
            reponse = self._demander(f"CHOC {numero}")
            if reponse is None:
                return  # on redemandera au tour suivant
            try:
                choc = Choc.lire(reponse)
            except ErreurProtocole as erreur:
                journal.warning("Accéléromètre : %s", erreur)
                return
            if choc.numero != numero:
                return
            if choc.absent:
                journal.warning(
                    "Accéléromètre : choc n° %d perdu (trop vieux, le Pi ne l'a pas lu à temps)",
                    numero,
                )
            elif not choc.fini:
                return  # il dure encore : on le prendra fini
            else:
                self._noter_choc(etat, choc)
            self._dernier_choc = numero

    def _noter_choc(self, etat: EtatRp2040, choc: Choc) -> None:
        quand = self._heure() - timedelta(milliseconds=max(0, etat.t_ms - choc.t_ms))
        avant = self._deja_notes_avant
        if avant is not None and quand.replace(microsecond=0) <= avant:
            return  # déjà noté par le programme du Pi d'avant
        pic_g = choc.pic_mg / 1000
        journal.warning(
            "Accéléromètre : CHOC n° %d de %.2f g pendant %d ms (« OK » coupé)",
            choc.numero,
            pic_g,
            choc.duree_ms,
        )
        if self._registre is None:
            return
        try:
            self._registre.noter_mesure("choc", pic_g, "g", capteur=SIGNAL, quand=quand)
            self._registre.noter_mesure(
                "choc_duree", choc.duree_ms, "ms", capteur=SIGNAL, quand=quand
            )
        except ErreurRegistre as erreur:
            journal.error("Accéléromètre : choc pas noté dans le registre : %s", erreur)

    def _noter_niveau(self, etat: EtatRp2040) -> None:
        periode_s = self._liaison.niveau_max_s
        if periode_s <= 0:
            return
        maintenant_s = self._horloge()
        if self._debut_niveau is None:
            self._debut_niveau = maintenant_s
        self._niveau_max_mg = max(self._niveau_max_mg, etat.max_mg)
        if maintenant_s - self._debut_niveau < periode_s:
            return
        niveau_g = self._niveau_max_mg / 1000
        self._debut_niveau = maintenant_s
        self._niveau_max_mg = 0
        if self._registre is None:
            return
        try:
            self._registre.noter_mesure("vibration_max", niveau_g, "g", capteur=SIGNAL)
        except ErreurRegistre as erreur:
            journal.error("Accéléromètre : vibration pas notée dans le registre : %s", erreur)

    def _accorder_reglages(self) -> None:
        reponse = self._demander("REGLAGES")
        if reponse is None:
            return
        try:
            chez_lui = lire_reglages(reponse)
        except ErreurProtocole as erreur:
            journal.warning("Accéléromètre : %s", erreur)
            return
        voulus = reglages_pour_rp2040(self.reglages)
        differents = [nom for nom, valeur in voulus.items() if chez_lui[nom] != valeur]
        if not differents:
            self._reglages_a_voir = False
            self._reglages_refuses = None
            return
        details = ", ".join(f"{nom} {chez_lui[nom]} → {voulus[nom]}" for nom in differents)
        reponse = self._demander(question_regler(voulus))
        if reponse is None:
            return
        if reponse == "REGLER ok":
            journal.info("Accéléromètre : réglages envoyés (%s)", details)
            self._reglages_a_voir = False
            self._reglages_refuses = None
            return
        raison = reponse.removeprefix("REGLER refuse").strip() or reponse
        if self._reglages_refuses != raison:
            journal.error(
                "Accéléromètre : il refuse les réglages de accelerometre.yaml (%s) : %s",
                details,
                raison,
            )
        self._reglages_refuses = raison
        self._reglages_a_voir = False

    # ------------------------------------------------------------ état

    @property
    def en_ligne(self) -> bool:
        return self.etat is not None

    def constats(self) -> list[Constat]:
        """Pour la check-list. Jamais bloquant : la sortie « OK » va directement à l'ESP32 n° 1."""
        etat = self.etat
        quoi_faire_fil = (
            "Vérifier l'alimentation du boîtier et le fil série (accelerometre/essai-etabli.md), "
            "puis lire le journal. La détection des chocs ne dépend pas du Pi."
        )
        if etat is None:
            if self._port is None and self._erreur_ouverture is not None:
                texte = f"port série fermé ({self._erreur_ouverture})"
            elif self._muet_signale:
                texte = "il ne répond pas"
            else:
                return [Constat(SUJET, "inconnu", "pas encore de réponse")]
            return [Constat(SUJET, "attention", texte, quoi_faire_fil)]
        constats = []
        if etat.pannes:
            constats.append(
                Constat(
                    SUJET,
                    "attention",
                    f"panne : {texte_pannes(etat.pannes)} (« OK » coupé)",
                    "Vérifier le capteur et son câble dans le boîtier du chariot Z "
                    "(accelerometre/essai-etabli.md).",
                )
            )
        if self._reglages_refuses is not None:
            constats.append(
                Constat(
                    SUJET,
                    "attention",
                    f"il refuse les réglages de accelerometre.yaml : {self._reglages_refuses}",
                    "Corriger accelerometre.yaml (ou refabriquer le programme du RP2040).",
                )
            )
        if etat.sortie_contredit:
            constats.append(
                Constat(
                    SUJET,
                    "attention",
                    "la broche « OK » ne suit pas ce qu'on lui commande",
                    "Vérifier le câblage de l'optocoupleur dans le boîtier.",
                )
            )
        if not constats:
            if etat.ok:
                texte = "il répond, « OK » donné"
            elif etat.en_choc:
                texte = "il répond, « OK » coupé (choc)"
            else:
                texte = "il répond, « OK » coupé (démarrage)"
            constats.append(Constat(SUJET, "ok", texte))
        return constats

    def fermer(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None
