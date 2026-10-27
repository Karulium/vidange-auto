"""Liaison série avec l'écran Nextion (UART du Pi, GPIO 4/5).

    liaison = LiaisonEcran(reglages.programme.ecran, ouvrir_port_ecran("/dev/ttyAMA2", 9600))
    trames = liaison.tour()                 # ouvre le port s'il le faut, lit les appuis
    liaison.afficher(page, {"t_mode.txt": "Mode : Production", "b_go.bco": 2016})
    liaison.fermer()

Rien n'attend jamais : un écran débranché ou muet ne bloque pas le programme. Le port est
rouvert tout seul après une coupure du câble.

Pour ne pas encombrer le fil, seules les valeurs qui ont changé sont envoyées. Quand l'écran
a pu tout oublier (il redémarre, il a été muet, il n'est plus sur la page attendue), tout lui
est renvoyé. Le Pi demande la page affichée (« sendme ») toutes les « presence_s » : c'est
aussi comme ça qu'il sait si l'écran répond.
"""

import time
from collections.abc import Callable
from typing import Any, Protocol

import serial

from vidange.ecran.pages import Page
from vidange.ecran.protocole import (
    CODE_REVEIL,
    CODE_SUCCES,
    CODE_TOUCHER,
    CODE_VEILLE,
    Appui,
    Decodeur,
    Demarrage,
    NumeroPage,
    Retour,
    Trame,
    ordre,
    ordre_page,
    ordre_valeur,
)
from vidange.fiabilite.constats import Constat
from vidange.journal import donner_journal
from vidange.reglages import ReglagesEcran

journal = donner_journal("ecran")

SUJET = "écran de l'armoire"
# Le signal de docs/entrees-sorties.yaml qui mène à l'écran (son « fichier » : l'UART du Pi).
SIGNAL = "ecran_nextion"


class PortEcran(Protocol):
    """Ce que la liaison utilise d'un port série (pyserial ou le faux écran)."""

    def write(self, donnees: bytes) -> Any: ...

    def read(self, taille: int) -> bytes:
        """Ce qui est déjà arrivé (au plus `taille` octets), sans attendre."""
        ...

    def close(self) -> None: ...


def ouvrir_port_ecran(fichier: str, vitesse_bauds: int) -> Callable[[], PortEcran]:
    """De quoi ouvrir le vrai port (fichier de Linux de l'UART, dans entrees-sorties.yaml)."""
    return lambda: serial.Serial(fichier, vitesse_bauds, timeout=0, write_timeout=1)


class LiaisonEcran:
    def __init__(
        self,
        reglages: ReglagesEcran,
        ouvrir: Callable[[], PortEcran],
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.reglages = reglages
        self._ouvrir = ouvrir
        self._horloge = horloge
        self._port: PortEcran | None = None
        self._decodeur = Decodeur()
        self._derniere_ouverture: float | None = None
        self._derniere_demande: float | None = None
        self._derniere_reponse: float | None = None
        self._ouvert_le = 0.0
        self._muet = True
        # « Ne répond pas » déjà écrit au journal (une fois, jusqu'à ce qu'il réponde).
        self._muet_signale = False
        self._erreur_ouverture: str | None = None
        # Ce que l'écran montre : la page (None = inconnue) et les valeurs envoyées.
        self._page: Page | None = None
        self._envoye: dict[str, str | int] = {}
        self._erreurs_vues: set[int] = set()

    # ------------------------------------------------------------ chaque tour

    def tour(self) -> list[Trame]:
        """Ouvre le port s'il le faut, demande la page affichée, rend les appuis reçus."""
        maintenant = self._horloge()
        if self._port is None and not self._essayer_ouvrir(maintenant):
            return []
        try:
            recu = self._lire()
            trames = self._decodeur.ajouter(recu)
            if trames:
                self._derniere_reponse = maintenant
            appuis = self._recevoir(trames)
            self._surveiller(maintenant)
        except (OSError, serial.SerialException) as erreur:
            self._perdre(f"liaison coupée : {erreur}")
            return []
        return appuis

    def _essayer_ouvrir(self, maintenant: float) -> bool:
        if (
            self._derniere_ouverture is not None
            and maintenant - self._derniere_ouverture < self.reglages.reconnexion_s
        ):
            return False
        self._derniere_ouverture = maintenant
        try:
            self._port = self._ouvrir()
        except Exception as erreur:
            if self._erreur_ouverture != str(erreur):
                journal.error("Écran : port série impossible à ouvrir : %s", erreur)
            self._erreur_ouverture = str(erreur)
            return False
        journal.info("Écran : port série ouvert")
        self._erreur_ouverture = None
        self._decodeur = Decodeur()
        self._derniere_demande = None
        self._derniere_reponse = None
        self._ouvert_le = maintenant
        self._muet = True
        self._muet_signale = False
        self.oublier()
        return True

    def _lire(self) -> bytes:
        assert self._port is not None
        recu = b""
        while morceau := self._port.read(256):
            recu += morceau
        return recu

    def _recevoir(self, trames: list[Trame]) -> list[Trame]:
        appuis: list[Trame] = []
        for trame in trames:
            if isinstance(trame, Appui):
                appuis.append(trame)
            elif isinstance(trame, Demarrage):
                journal.info("Écran : il vient de démarrer, tout lui est renvoyé")
                self.oublier()
            elif isinstance(trame, NumeroPage):
                if self._page is not None and trame.numero != self._page.numero:
                    journal.warning(
                        "Écran : il montre la page n° %d au lieu de « %s » (n° %d) : "
                        "elle lui est renvoyée",
                        trame.numero,
                        self._page.nom,
                        self._page.numero,
                    )
                    self.oublier()
            else:
                self._noter_retour(trame)
        return appuis

    def _noter_retour(self, trame: Retour) -> None:
        if trame.code == CODE_TOUCHER:
            journal.warning(
                "Écran : un objet touché (page n° %d, objet n° %d) n'envoie pas son nom : "
                "vérifier son code « prints » (nextion/pages.md)",
                *trame.donnees[:2],
            )
        elif trame.code in (CODE_SUCCES, CODE_VEILLE, CODE_REVEIL):
            return
        elif trame.erreur is not None:
            # Une seule fois par page affichée : sinon le journal déborderait.
            if trame.code not in self._erreurs_vues:
                self._erreurs_vues.add(trame.code)
                nom = self._page.nom if self._page else "?"
                journal.warning(
                    "Écran : %s (page « %s ») : comparer la page avec nextion/pages.md",
                    trame.erreur,
                    nom,
                )
        else:
            journal.debug("Écran : trame inconnue %r", trame)

    def _surveiller(self, maintenant: float) -> None:
        """Demande la page affichée de temps en temps ; repère un écran muet, puis revenu."""
        reponse = self._derniere_reponse
        muet = reponse is None or maintenant - reponse > self.reglages.silence_s
        depuis = self._ouvert_le if reponse is None else reponse
        if muet and not self._muet_signale and maintenant - depuis > self.reglages.silence_s:
            journal.warning("Écran : il ne répond pas (débranché, éteint, mauvaise vitesse ?)")
            self._muet_signale = True
        if self._muet and not muet:
            journal.info("Écran : il répond")
            self._muet_signale = False
            self.oublier()
        self._muet = muet
        if (
            self._derniere_demande is None
            or maintenant - self._derniere_demande >= self.reglages.presence_s
        ):
            self._derniere_demande = maintenant
            self._ecrire(ordre("sendme"))

    def _perdre(self, raison: str) -> None:
        journal.error("Écran : %s", raison)
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
        self._port = None
        self._muet = True
        self.oublier()

    def _ecrire(self, donnees: bytes) -> None:
        assert self._port is not None
        self._port.write(donnees)

    # ------------------------------------------------------------ affichage

    def oublier(self) -> None:
        """L'écran a pu tout oublier : la page et toutes les valeurs seront renvoyées."""
        self._page = None
        self._envoye = {}
        self._erreurs_vues = set()

    def afficher(self, page: Page, valeurs: dict[str, str | int]) -> None:
        """Montre la page avec ces valeurs (« objet.attribut » → valeur)."""
        if self._port is None:
            return
        try:
            if self._page != page:
                # En changeant de page, l'écran reprend les valeurs de Nextion Editor.
                self._ecrire(ordre_page(page.nom))
                self._page = page
                self._envoye = {}
                self._erreurs_vues = set()
            for attribut, valeur in valeurs.items():
                if self._envoye.get(attribut) != valeur:
                    self._ecrire(ordre_valeur(attribut, valeur))
                    self._envoye[attribut] = valeur
        except (OSError, serial.SerialException) as erreur:
            self._perdre(f"liaison coupée : {erreur}")

    # ------------------------------------------------------------ état

    @property
    def en_ligne(self) -> bool:
        return self._port is not None and not self._muet

    def constats(self) -> list[Constat]:
        """Pour la check-list. Sans écran, la machine peut tourner (page web) : jamais bloquant."""
        if self.en_ligne:
            return [Constat(SUJET, "ok", "il répond")]
        if self._port is not None and not self._muet_signale:
            return [Constat(SUJET, "inconnu", "pas encore de réponse (il démarre ?)")]
        if self._port is None:
            texte = f"port série fermé ({self._erreur_ouverture or 'pas encore ouvert'})"
        else:
            texte = "il ne répond pas"
        return [
            Constat(
                SUJET,
                "attention",
                texte,
                "Vérifier que l'écran est allumé et son câble (GPIO 4/5), puis lire le journal. "
                "La page web reste utilisable.",
            )
        ]

    def fermer(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None
