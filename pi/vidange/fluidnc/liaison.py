"""Liaison série entre le Pi et une carte FluidNC.

Une liaison par carte. Elle :
- envoie les lignes de G-code avec un contrôle de flux (« comptage de caractères » de Grbl) :
  on n'envoie une ligne que si elle tient dans ce qui reste du tampon de la carte, et chaque
  « ok » ou « error:N » libère la place de la plus ancienne ligne envoyée ;
- demande l'état (« ? ») régulièrement et garde le dernier : état, positions, alarme ;
- débloque, met en pause, reprend, réinitialise ;
- fait les déplacements manuels (« $J= ») du pilotage à distance, et les annule ;
- se reconnecte seule après une coupure du câble (ou une carte muette), en retrouvant la carte
  par le numéro de série de son USB, même si son port a changé de nom.

Après une coupure ou un redémarrage de la carte, rien n'est renvoyé tout seul : on ne sait pas
ce que la carte a fait des lignes en cours. Ces lignes finissent en échec et c'est au chef
d'orchestre de décider de la suite.

Une alarme fait échouer toutes les lignes en cours, et annule celles pas encore envoyées :
après le déblocage, aucun vieux mouvement ne doit partir.
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from vidange.fluidnc import protocole
from vidange.fluidnc.ports import ErreurFluidnc, Port, ouvrir_port_usb
from vidange.journal import donner_journal
from vidange.reglages import Fluidnc


class ErreurCommande(ErreurFluidnc):
    """Une ligne n'a pas été prise par la carte (refusée, annulée ou perdue)."""


@dataclass(frozen=True)
class EtatCarte:
    """Ce qu'on sait d'une carte, à un instant."""

    connectee: bool = False
    # État de FluidNC tel quel (« Idle », « Run », « Hold:0 », « Alarm »...), None si inconnu.
    etat: str | None = None
    # Positions machine en mm, par lettre d'axe (repère de FluidNC).
    positions: dict[str, float] = field(default_factory=dict)
    vitesse: float | None = None
    # Numéro de la dernière alarme, effacé quand la carte n'est plus en alarme.
    alarme: int | None = None
    # Entrées actives de la carte (fins de course...), comme FluidNC les écrit.
    entrees_actives: str = ""
    # Lignes envoyées sans réponse + lignes qui attendent leur tour.
    lignes_en_cours: int = 0
    # Heure (horloge de la liaison) du dernier rapport d'état reçu.
    date_rapport: float | None = None
    # Nombre de coupures de la liaison depuis son démarrage (même si elle est déjà reprise).
    coupures: int = 0
    # Nombre de rapports d'état reçus depuis le démarrage.
    rapports_recus: int = 0
    # Nombre de fois où la carte a redémarré toute seule (alimentation, parasite...) alors
    # qu'elle parlait déjà : pas son démarrage normal, ni une réinitialisation demandée.
    redemarrages: int = 0

    @property
    def au_repos(self) -> bool:
        return self.connectee and self.etat == "Idle" and self.lignes_en_cours == 0

    @property
    def en_alarme(self) -> bool:
        return self.etat is not None and self.etat.startswith("Alarm")


class Commande:
    """Une ligne confiée à la liaison. On peut attendre sa réponse."""

    def __init__(self, ligne: str) -> None:
        self.ligne = ligne
        # Une ligne avec un accent est refusée avant l'envoi (Liaison._verifier_ligne).
        self.donnees = (ligne + "\n").encode("ascii", errors="replace")
        self.erreur: str | None = None
        # Nombre de rapports d'état reçus quand la réponse est arrivée : ceux d'après
        # décrivent la carte après cette ligne.
        self.rapports_a_la_reponse = 0
        self._finie = threading.Event()

    @property
    def finie(self) -> bool:
        return self._finie.is_set()

    @property
    def reussie(self) -> bool:
        return self._finie.is_set() and self.erreur is None

    def _finir(self, erreur: str | None = None) -> None:
        if not self._finie.is_set():
            self.erreur = erreur
            self._finie.set()

    def attendre(self, delai_s: float) -> None:
        """Attend la réponse de la carte ; lève ErreurCommande si elle ne vient pas ou est mauvaise.

        « ok » veut dire que la carte a pris la ligne, pas que le mouvement est fini
        (pour ça : Liaison.attendre_fin_mouvements).
        """
        if not self._finie.wait(delai_s):
            raise ErreurCommande(f"« {self.ligne} » : pas de réponse de la carte en {delai_s:g} s")
        if self.erreur is not None:
            raise ErreurCommande(f"« {self.ligne} » : {self.erreur}")

    def __repr__(self) -> str:
        return f"Commande({self.ligne!r})"


class Liaison:
    """Liaison avec une carte FluidNC, nommée dans fluidnc.yaml (« portique »...)."""

    def __init__(
        self,
        nom: str,
        reglages: Fluidnc,
        ouvrir: Callable[[], Port] | None = None,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        if nom not in reglages.cartes:
            raise ErreurFluidnc(
                f"carte « {nom} » absente de fluidnc.yaml (cartes : {', '.join(reglages.cartes)})"
            )
        self.nom = nom
        self._reglages = reglages.liaison
        if ouvrir is None:
            numero_serie = reglages.cartes[nom].numero_serie_usb
            vitesse = self._reglages.vitesse_bauds
            delai = self._reglages.periode_etat_s

            def ouvrir() -> Port:
                return ouvrir_port_usb(numero_serie, vitesse, delai)

        self._ouvrir = ouvrir
        self._horloge = horloge
        self._journal = donner_journal(f"fluidnc.{nom}")

        # Tout ce qui suit est protégé par ce verrou ; « _change » réveille ceux qui attendent.
        self._verrou = threading.RLock()
        self._change = threading.Condition(self._verrou)
        self._port: Port | None = None
        self._etat = EtatCarte()
        self._a_envoyer: deque[Commande] = deque()
        self._envoyees: deque[Commande] = deque()
        self._octets_envoyes = 0
        self._reste = b""
        self._derniere_reception = 0.0
        self._prochaine_demande = 0.0
        self._prevenu_repere = False
        self._pause_avant_connexion = False
        self._reinitialisation_demandee = False

        self._arret = threading.Event()
        self._fil: threading.Thread | None = None

    # ------------------------------------------------------------ marche / arrêt

    def demarrer(self) -> None:
        """Lance la liaison (elle se connecte, et se reconnecte, toute seule)."""
        if self._fil is not None:
            return
        self._arret.clear()
        self._fil = threading.Thread(target=self._boucle, name=f"fluidnc-{self.nom}", daemon=True)
        self._fil.start()

    def arreter(self) -> None:
        self._arret.set()
        with self._verrou:
            self._deconnecter("arrêt de la liaison", prevenir=False)
        if self._fil is not None:
            self._fil.join()
            self._fil = None

    def __enter__(self) -> "Liaison":
        self.demarrer()
        return self

    def __exit__(self, *_: object) -> None:
        self.arreter()

    # ------------------------------------------------------------ ce qu'on sait

    @property
    def etat(self) -> EtatCarte:
        with self._verrou:
            return self._etat

    def attendre(self, condition: Callable[[EtatCarte], bool], delai_s: float) -> EtatCarte:
        """Attend que l'état de la carte remplisse la condition ; lève ErreurFluidnc sinon."""
        fin = time.monotonic() + delai_s
        with self._change:
            while not condition(self._etat):
                reste = fin - time.monotonic()
                if reste <= 0:
                    raise ErreurFluidnc(
                        f"carte « {self.nom} » : attente trop longue ({delai_s:g} s), "
                        f"état : {self._decrire()}"
                    )
                self._change.wait(reste)
            return self._etat

    def attendre_connexion(self, delai_s: float) -> EtatCarte:
        """Attend d'être connecté et d'avoir reçu un premier état."""
        return self.attendre(lambda etat: etat.connectee and etat.etat is not None, delai_s)

    # ------------------------------------------------------------ commandes

    def envoyer(self, ligne: str) -> Commande:
        """Confie une ligne de G-code à la liaison ; elle part dès qu'elle a de la place."""
        commande = Commande(ligne.strip())
        probleme = self._verifier_ligne(commande)
        with self._verrou:
            if probleme is None and self._port is None:
                probleme = "carte non connectée"
            if probleme is not None:
                commande._finir(probleme)
                return commande
            self._a_envoyer.append(commande)
            self._pousser()
            self._mettre_a_jour()
        return commande

    def envoyer_et_attendre(self, ligne: str, delai_s: float) -> None:
        self.envoyer(ligne).attendre(delai_s)

    def debloquer(self) -> Commande:
        """Sort la carte de l'alarme ($X). À faire seulement quand la cause est comprise."""
        self._journal.warning("Déblocage demandé ($X)")
        return self.envoyer(protocole.DEBLOCAGE)

    def prise_origine(self) -> Commande:
        """Prise d'origine ($H) : la réponse arrive quand elle est finie."""
        return self.envoyer(protocole.PRISE_ORIGINE)

    def attendre_fin_mouvements(self, delai_s: float) -> EtatCarte:
        """Attend que tous les mouvements envoyés soient finis (la carte répond à « G4 P0 »).

        Rend l'état d'après (positions d'arrivée), lu dans un rapport arrivé après la réponse.
        """
        fin = time.monotonic() + delai_s
        commande = self.envoyer(protocole.SYNCHRONISATION)
        commande.attendre(delai_s)
        deja = commande.rapports_a_la_reponse
        return self.attendre(
            lambda etat: etat.rapports_recus > deja, max(fin - time.monotonic(), 0)
        )

    def deplacer_manuel(self, positions_mm: dict[str, float], vitesse_mm_min: float) -> Commande:
        """Déplacement manuel (« $J= ») vers des positions machine (mm, par lettre d'axe).

        Il s'enchaîne après le déplacement manuel d'avant ; `annuler_deplacement` les arrête tous.
        """
        mots = " ".join(f"{lettre}{valeur:.3f}" for lettre, valeur in positions_mm.items())
        return self.envoyer(f"{protocole.DEPLACEMENT_MANUEL}G53 {mots} F{vitesse_mm_min:.0f}")

    def annuler_deplacement(self) -> None:
        """Arrête tout de suite les déplacements manuels (0x85), sans perdre la position."""
        self._ecrire_temps_reel(protocole.ANNULER_DEPLACEMENT)

    def pause(self) -> None:
        """Pause immédiate (« ! ») : les axes ralentissent et s'arrêtent, rien n'est perdu."""
        self._ecrire_temps_reel(protocole.PAUSE)

    def reprendre(self) -> None:
        """Reprise après une pause (« ~ »)."""
        self._ecrire_temps_reel(protocole.REPRISE)

    def reinitialiser(self) -> None:
        """Ctrl-X : la carte s'arrête et oublie toutes les lignes en cours.

        Pendant un mouvement, la position est perdue (alarme 3) : prise d'origine à refaire.
        """
        with self._verrou:
            self._ecrire_temps_reel(protocole.REINITIALISATION)
            self._reinitialisation_demandee = True
            self._abandonner("annulée : réinitialisation de la carte")

    # ------------------------------------------------------------ fonctionnement interne

    def _verifier_ligne(self, commande: Commande) -> str | None:
        if not commande.ligne.isascii() or not commande.ligne.isprintable():
            return "ligne refusée : caractère interdit (accents, retour à la ligne...)"
        if set(commande.ligne) & protocole.CARACTERES_TEMPS_REEL:
            return "ligne refusée : « ? », « ! » et « ~ » sont des commandes à part"
        if len(commande.donnees) > self._reglages.taille_tampon:
            return (
                f"ligne refusée : plus longue que le tampon de la carte "
                f"({self._reglages.taille_tampon} octets)"
            )
        return None

    def _ecrire(self, donnees: bytes) -> bool:
        """Écrit sur le port ; une erreur veut dire câble coupé. Rend False si rien n'est écrit."""
        with self._verrou:
            if self._port is None:
                return False
            try:
                self._port.write(donnees)
            except OSError as erreur:
                self._deconnecter(f"écriture impossible ({erreur})")
                return False
            return True

    def _ecrire_temps_reel(self, caractere: bytes) -> None:
        if not self._ecrire(caractere):
            raise ErreurFluidnc(f"carte « {self.nom} » non connectée")

    def _pousser(self) -> None:
        """Envoie les lignes en attente tant qu'elles tiennent dans le tampon de la carte."""
        while self._a_envoyer and self._port is not None:
            commande = self._a_envoyer[0]
            if self._octets_envoyes + len(commande.donnees) > self._reglages.taille_tampon:
                return
            self._a_envoyer.popleft()
            self._envoyees.append(commande)
            self._octets_envoyes += len(commande.donnees)
            self._journal.debug("→ %s", commande.ligne)
            if not self._ecrire(commande.donnees):
                return

    def _abandonner(self, raison_envoyees: str, raison_a_envoyer: str | None = None) -> None:
        """Termine en échec les lignes envoyées sans réponse et celles en attente."""
        for commande in self._envoyees:
            commande._finir(raison_envoyees)
        for commande in self._a_envoyer:
            commande._finir(raison_a_envoyer or raison_envoyees)
        if self._envoyees or self._a_envoyer:
            self._journal.warning(
                "%d ligne(s) abandonnée(s) : %s",
                len(self._envoyees) + len(self._a_envoyer),
                raison_envoyees,
            )
        self._envoyees.clear()
        self._a_envoyer.clear()
        self._octets_envoyes = 0
        self._mettre_a_jour()

    def _mettre_a_jour(self, **valeurs: object) -> None:
        en_cours = len(self._envoyees) + len(self._a_envoyer)
        self._etat = replace(self._etat, lignes_en_cours=en_cours, **valeurs)
        self._change.notify_all()

    def _decrire(self) -> str:
        etat = self._etat
        if not etat.connectee:
            return "non connectée"
        texte = protocole.decrire_etat(etat.etat) if etat.etat else "état inconnu"
        if etat.alarme is not None:
            texte += f", {protocole.decrire_alarme(etat.alarme)}"
        return f"{texte}, {etat.lignes_en_cours} ligne(s) en cours"

    def _connecter(self) -> None:
        if self._pause_avant_connexion:
            # Juste après une coupure : laisser le temps à l'USB de réapparaître.
            self._pause_avant_connexion = False
            self._arret.wait(self._reglages.delai_reconnexion_s)
            return
        try:
            port = self._ouvrir()
        except (OSError, ErreurFluidnc) as erreur:
            self._journal.debug("Connexion impossible : %s", erreur)
            self._arret.wait(self._reglages.delai_reconnexion_s)
            return
        with self._verrou:
            if self._arret.is_set():
                port.close()
                return
            self._port = port
            self._reste = b""
            maintenant = self._horloge()
            self._derniere_reception = maintenant
            self._prochaine_demande = maintenant
            self._mettre_a_jour(connectee=True, etat=None)
        self._journal.info("Carte « %s » connectée", self.nom)

    def _deconnecter(self, raison: str, prevenir: bool = True) -> None:
        """Ferme le port ; la boucle tentera de se reconnecter. Appelée sous le verrou."""
        if self._port is None:
            return
        port, self._port = self._port, None
        try:
            port.close()
        except OSError:
            pass
        if prevenir:
            self._journal.error(
                "Liaison avec la carte « %s » coupée : %s. Reconnexion automatique.",
                self.nom,
                raison,
            )
        self._abandonner(
            f"perdue : liaison coupée ({raison}), on ne sait pas si la carte l'a exécutée",
            f"annulée : liaison coupée ({raison})",
        )
        self._pause_avant_connexion = True
        self._mettre_a_jour(
            connectee=False, etat=None, vitesse=None, coupures=self._etat.coupures + 1
        )

    def _boucle(self) -> None:
        while not self._arret.is_set():
            port = self._port
            if port is None:
                self._connecter()
                continue
            try:
                recu = port.readline()
            except OSError as erreur:
                with self._verrou:
                    if self._port is port:
                        self._deconnecter(f"lecture impossible ({erreur})")
                continue
            with self._verrou:
                if self._port is not port:
                    continue
                maintenant = self._horloge()
                if recu:
                    self._derniere_reception = maintenant
                    self._recevoir(recu)
                if maintenant - self._derniere_reception > self._reglages.delai_silence_s:
                    self._deconnecter(f"carte muette depuis {self._reglages.delai_silence_s:g} s")
                elif maintenant >= self._prochaine_demande:
                    self._prochaine_demande = maintenant + self._reglages.periode_etat_s
                    self._ecrire(protocole.DEMANDE_ETAT)

    def _recevoir(self, recu: bytes) -> None:
        """Rassemble les morceaux reçus en lignes entières."""
        self._reste += recu
        *lignes, self._reste = self._reste.split(b"\n")
        for brute in lignes:
            ligne = brute.decode("ascii", errors="replace").strip()
            if ligne:
                self._traiter(ligne)

    def _traiter(self, ligne: str) -> None:
        sorte, numero = protocole.classer_ligne(ligne)
        if sorte == "etat":
            self._traiter_rapport(ligne)
        elif sorte in ("ok", "erreur"):
            if not self._envoyees:
                self._journal.warning("Réponse « %s » sans ligne en attente", ligne)
                return
            commande = self._envoyees.popleft()
            self._octets_envoyes -= len(commande.donnees)
            commande.rapports_a_la_reponse = self._etat.rapports_recus
            if sorte == "ok":
                self._journal.debug("← ok (%s)", commande.ligne)
                commande._finir()
            else:
                assert numero is not None
                erreur = protocole.decrire_erreur(numero)
                self._journal.error("« %s » refusée par la carte : %s", commande.ligne, erreur)
                commande._finir(f"refusée par la carte, {erreur}")
            self._pousser()
            self._mettre_a_jour()
        elif sorte == "alarme":
            assert numero is not None
            self._journal.error("Carte « %s » : %s", self.nom, protocole.decrire_alarme(numero))
            # Les lignes envoyées finissent en échec tout de suite, mais restent comptées jusqu'à
            # leur réponse (« error:9 » d'habitude) ; celles qui attendaient ne partiront pas.
            for commande in self._envoyees:
                commande._finir(f"interrompue : {protocole.decrire_alarme(numero)}")
            for commande in self._a_envoyer:
                commande._finir(f"annulée : {protocole.decrire_alarme(numero)}")
            self._a_envoyer.clear()
            self._mettre_a_jour(alarme=numero, etat="Alarm")
        elif sorte == "bienvenue":
            self._journal.warning("La carte « %s » a (re)démarré : %s", self.nom, ligne)
            self._abandonner(
                "perdue : la carte a redémarré, on ne sait pas si elle l'a exécutée",
                "annulée : la carte a redémarré",
            )
            if self._reinitialisation_demandee:
                self._reinitialisation_demandee = False
            elif self._etat.etat is not None:
                self._mettre_a_jour(redemarrages=self._etat.redemarrages + 1)
        elif sorte == "message":
            self._journal.info("Carte « %s » : %s", self.nom, ligne)
        else:
            self._journal.debug("Ligne non reconnue : %s", ligne)

    def _traiter_rapport(self, ligne: str) -> None:
        rapport = protocole.lire_rapport_etat(ligne)
        if rapport is None:
            self._journal.warning("Rapport d'état illisible : %s", ligne)
            return
        if rapport.repere != "machine" and not self._prevenu_repere:
            self._prevenu_repere = True
            self._journal.warning(
                "La carte « %s » donne ses positions dans le repère de travail (WPos) : "
                "régler « $Report/Status=1 » pour avoir le repère machine (MPos).",
                self.nom,
            )
        alarme = self._etat.alarme if rapport.etat.startswith("Alarm") else None
        if rapport.etat != self._etat.etat:
            self._journal.info("Carte « %s » %s", self.nom, protocole.decrire_etat(rapport.etat))
        self._mettre_a_jour(
            etat=rapport.etat,
            positions=rapport.positions,
            vitesse=rapport.vitesse,
            alarme=alarme,
            entrees_actives=rapport.entrees_actives,
            date_rapport=self._horloge(),
            rapports_recus=self._etat.rapports_recus + 1,
        )
