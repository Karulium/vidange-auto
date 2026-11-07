"""Nettoyage : le store de l'enceinte, la purge après fermeture, la nuit UV-ozone, le mode maïs.

    nettoyage = Nettoyage(reglages.machine.nettoyage, materiel, donnees / "nettoyage.json",
                          registre, mode=lambda: mode.actuel, cycle_tourne=..., pause=chef.pause)
    nettoyage.demarrer(arret)                 # relit les signaux en fond
    nettoyage.demander_ouverture("écran")     # libère les verrous du store, ou ErreurNettoyage
    nettoyage.programmer_nuit("écran")        # nuit UV-ozone à l'heure réglée (ou tout de suite)
    nettoyage.etat()                          # pour l'écran et la page web

**Le Pi lit et attend ; la sécurité est câblée** (module gelé le 28/10, regelé le 04/11/2026) :
- `store_ferme` (2e contact) est dans la boucle d'arrêt du portique ;
- la chaîne UV-ozone (reeds bas du store + porte du spray en série) alimente `generateur_ozone` et
  `lampe_uv` : un contact ouvert les éteint, même si le Pi dit « marche » ;
- les verrous du store sont fermés sans courant (clé de dépannage) ;
- le moteur du store est en commande maintenue (2 boutons câblés) : **le Pi ne le commande pas** ;
- l'alarme d'ozone câblée (« porte verrouillée tant que l'ozone dépasse 0,1 ppm ») n'a pas encore
  d'appareil : **aucun code ici ne la remplace**. Son contact `ozone_securite_ok`, s'il est un jour
  dans entrees-sorties.yaml, est seulement affiché.

Le store :
- « ouvrir le store » (écran, page web) est refusé pendant un cycle, pendant la purge, pendant une
  nuit UV-ozone pas finie, en mode UV-ozone tant que l'ozone dedans n'est pas sous 0,1 ppm, et
  après une nuit en erreur (seule la clé de dépannage ouvre). Sinon : verrous sous tension.
- `store_ferme` faux (stable `stabilite_s`) : « store ouvert », aucune étape ne commence (condition
  générale du chef), c'est dit à l'écran. Pendant un cycle (hors mode maïs) : alerte « store mal
  fermé » et pause.
- `store_ferme` vrai stable : verrous remis (hors tension), puis purge (sauf en mode maïs).
- Demande de fermeture et store pas fermé au bout de `alerte_fermeture_s` : alerte « store mal
  fermé ». Verrous libérés et store jamais ouvert au bout de `deverrouille_max_s` : verrous remis.

La purge : ventilateur en marche, consigne « plein ». Pendant la purge, le chef refuse les gestes
protégés (dosage de la semence, ouverture d'une capsule, versement dans un seau ouvert) avec la
raison « purge en cours ». Finie quand : au moins `duree_min_s`, ET particules dedans ≤ rapport ×
particules dehors stable `stabilite_particules_s`, ET pression ≥ `pression_fin`. Alors consigne
« normal ». Pas finie à `alerte_s` : alerte ; Karulium attend ou passe outre (noté au journal).
Store rouvert : purge remise à zéro. Capteur absent ou muet : sa condition n'est jamais vraie.

La nuit UV-ozone (mode « uv_ozone ») : conditions de départ (store fermé, verrous remis, porte du
spray fermée, aucun cycle, capteur d'ozone dedans lu, pas de fuite). Le panneau long du poste du
fût n'est PAS une condition : levé (contact fermé, la position normale) ou rabattu, il est noté au
journal au départ ; on n'exige jamais « rabattu » (avec un fût, il ne peut pas se rabattre).
À l'heure réglée ou tout de suite : ventilateur de l'enceinte, compresseur et ventilateur
de l'armoire coupés ; générateur en marche `t_generation_s`, contact jusqu'à `t_contact_s`,
`ozone_dedans` noté au registre ; retour : ozone dedans sous le seuil, stable `stabilite_retour_s`.
Alors le compresseur et les ventilateurs sont de nouveau permis ; le store reste verrouillé
jusqu'à une demande d'ouverture. Erreurs (pas sous le seuil à `t_max_retour_s`, capteur muet,
mesure incohérente) : alerte, cycle envoyé (file), store verrouillé, ouverture par la clé seulement.
Store ou porte du spray ouverts pendant la nuit : générateur coupé, alerte. Après une coupure de
courant en pleine nuit : générateur coupé, reprise à l'attente du retour ; jamais de nouvelle
génération sans Karulium.

`ozone_dehors` au-dessus du seuil de fuite, à tout moment : alerte forte (écran, voyant et buzzer,
file) et générateur coupé.

Lampe UV des têtes : permise seulement store fermé (le geste du bain des têtes est celui de son
module). Éclairage : à la demande et pendant un cycle, éteint en mode UV-ozone. Mode maïs : store
ouvert permis, ventilateur coupé (la vapeur moisit le filtre HEPA), pas de purge.

Le logiciel peut planter sans danger : tout ce qu'il commande retombe au repos (verrous fermés,
générateur, lampe, ventilateur et LED coupés).
"""

import json
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from vidange.chef import Condition
from vidange.chef.chef import GESTES_PROTEGES
from vidange.fiabilite.constats import Constat, lancer_boucle
from vidange.journal import donner_journal
from vidange.materiel import ErreurMateriel, Materiel
from vidange.materiel.ozone import MesureOzone, texte_ppm
from vidange.nettoyage.capteurs import CapteurMesure, Consigne
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import Nettoyage as ReglagesNettoyage

journal = donner_journal("nettoyage")

MODULE = "nettoyage"
# Sujet de ses constats dans la check-list.
SUJET = "enceinte"
# Les signaux (docs/entrees-sorties.yaml). Un signal absent de la liste est simplement ignoré.
STORE = "store_ferme"
VERROUS = "verrous_store"
ECLAIRAGE = "eclairage_enceinte"
VENTILATEUR = "ventilateur_enceinte"
GENERATEUR = "generateur_ozone"
LAMPE_UV = "lampe_uv"
COMPRESSEUR = "relais_compresseur"
COUPURE_ARMOIRE = "coupure_ventilateur_armoire"
PORTE_SPRAY = "porte_spray"
PANNEAU = "reed_panneau_poste_fut"
OZONE_DEDANS = "ozone_dedans"
OZONE_DEHORS = "ozone_dehors"
OZONE_SECURITE = "ozone_securite_ok"
VOYANT = "voyant_buzzer"

# État du store (vu stable).
INCONNU, FERME, OUVERT = "inconnu", "ferme", "ouvert"
LIBELLES_STORE = {
    INCONNU: "Store : on ne sait pas encore",
    FERME: "Store fermé",
    OUVERT: "Store ouvert",
}

# Phases de la nuit UV-ozone.
ATTENTE, GENERATION, CONTACT, RETOUR, FINI, ERREUR = (
    "attente_depart",
    "generation",
    "contact",
    "retour",
    "fini",
    "erreur",
)
# Pendant ces phases, de l'ozone est (ou peut être) dans l'enceinte : ventilateurs coupés.
NUIT_ACTIVE = (GENERATION, CONTACT, RETOUR, ERREUR)
LIBELLES_NUIT = {
    None: "Pas de nuit UV-ozone",
    ATTENTE: "Nuit UV-ozone prévue",
    GENERATION: "Nuit UV-ozone : génération d'ozone",
    CONTACT: "Nuit UV-ozone : contact",
    RETOUR: "Nuit UV-ozone : retour sous le seuil",
    FINI: "Nuit UV-ozone finie",
    ERREUR: "Nuit UV-ozone en erreur",
}

ARRET, NORMAL, PLEIN = "arret", "normal", "plein"

QUOI_FAIRE_STORE = (
    "Le store n'est pas fermé (les 2 reeds du bas) : le redescendre jusqu'en bas en tenant le "
    "bouton « descendre ». S'il est en bas, regarder les reeds et leur câble. Rien ne bouge "
    "tant qu'il n'est pas fermé (câblé)."
)
QUOI_FAIRE_PURGE = (
    "La purge dure trop (filtre bouché, store mal fermé, capteur de particules ou de pression "
    "absent ou en panne ?). Pour continuer d'attendre : RÉPARÉ. Pour passer outre : page MODE, "
    "ENCEINTE, PASSER OUTRE (noté au journal)."
)
QUOI_FAIRE_NUIT = (
    "Ne pas ouvrir le store : l'ozone est peut-être encore là. Le store reste verrouillé ; on ne "
    "l'ouvre qu'avec la clé de dépannage, après avoir vérifié l'ozone avec un détecteur à part. "
    "Regarder le capteur d'ozone du dedans et le générateur (pi/systeme/essai-nettoyage.md)."
)
QUOI_FAIRE_FUITE = (
    "FUITE D'OZONE : le générateur est coupé. Ne pas entrer, aérer l'atelier, vérifier le store, "
    "la porte du spray, le clapet et la gaine. La sécurité ozone câblée reste en place."
)
QUOI_FAIRE_OUVERT_NUIT = (
    "Le store ou la porte du spray s'est ouvert pendant la nuit UV-ozone : le générateur est "
    "coupé (le câblage le coupe aussi). Ne pas entrer sans détecteur d'ozone ; refermer, puis "
    "attendre le retour sous 0,1 ppm."
)


class ErreurNettoyage(Exception):
    """Ordre refusé (ouvrir le store, lancer la nuit...) : le message dit pourquoi."""


@dataclass(frozen=True)
class EtatNettoyage:
    store: str
    store_libelle: str
    # Verrous sous tension (déverrouillés) par le Pi.
    verrous_liberes: bool
    store_mal_ferme: bool
    mode: str
    purge: bool
    purge_depuis_s: float | None
    # Les 3 conditions de fin de purge (durée, particules stables, pression).
    purge_duree_ok: bool
    purge_particules_ok: bool
    purge_pression_ok: bool
    purge_alerte: bool
    particules_dedans: float | None
    particules_dehors: float | None
    pression_pa: float | None
    ventilateur: str
    eclairage: bool
    lampe_uv: bool
    nuit: str | None
    nuit_libelle: str
    nuit_depart_prevu: str | None
    nuit_depuis_s: float | None
    nuit_erreur: str
    ozone_dedans: str
    ozone_dehors: str
    # Panneau long du poste du fût : « levé (position normale) », « rabattu »... (pas une
    # condition de la nuit).
    panneau: str
    # Contact de l'alarme d'ozone câblée, s'il est dans la liste (None : absent ou illisible).
    ozone_securite_ok: bool | None
    fuite: bool
    refus_ouverture: str | None
    refus_nuit: str | None
    messages: tuple[str, ...]
    exemple: bool

    def en_dict(self) -> dict:
        return asdict(self)


class _Suivi:
    """Une valeur, et depuis quand elle n'a pas changé."""

    def __init__(self) -> None:
        self.valeur: bool | None = None
        self.depuis = 0.0

    def voir(self, valeur: bool | None, maintenant: float) -> None:
        if valeur != self.valeur:
            self.valeur, self.depuis = valeur, maintenant

    def stable(self, valeur: bool, maintenant: float, duree: float) -> bool:
        return self.valeur is valeur and maintenant - self.depuis >= duree


@dataclass
class _Nuit:
    """Où en est la nuit UV-ozone (gardé dans un fichier : reprise après coupure)."""

    phase: str | None = None
    # Départ (horloge du Pi) et départ en heure du jour (pour la reprise).
    debut: float | None = None
    debut_jour: str | None = None
    depart_prevu: datetime | None = None
    cycle: int | None = None
    # La génération a été coupée avant la fin (store, porte, fuite, coupure de courant) : pas de
    # contrôle « mesure incohérente ».
    generation_coupee: bool = False
    max_ppm: float | None = None
    ozone_bas_depuis: float | None = None
    dernier_journal: float | None = None
    erreur: str = ""
    # Erreur : la clé de dépannage a ouvert le store (l'erreur sera close à sa fermeture).
    cle_vue: bool = False
    alertes: set[str] = field(default_factory=set)


def _ppm(valeur: float) -> str:
    return f"{valeur:g}".replace(".", ",")


def _minutes(secondes: float) -> str:
    return f"{secondes / 60:.0f} min"


class Nettoyage:
    def __init__(
        self,
        reglages: ReglagesNettoyage,
        materiel: Materiel,
        fichier: Path | None = None,
        registre: Registre | None = None,
        mode: Callable[[], str] = lambda: "production",
        cycle_tourne: Callable[[], bool] = lambda: False,
        pause: Callable[[], object] = lambda: None,
        particules_dedans: CapteurMesure | None = None,
        particules_dehors: CapteurMesure | None = None,
        pression: CapteurMesure | None = None,
        consigne: Consigne | None = None,
        horloge: Callable[[], float] = time.monotonic,
        maintenant: Callable[[], datetime] = datetime.now,
    ) -> None:
        """`fichier` : où garder la nuit UV-ozone (reprise après coupure ; None : nulle part).
        `mode` : le mode de la machine (ModeMachine.actuel). `cycle_tourne` : un module est en
        plein travail (ni en pause, ni en attente du Go). `pause` : met la machine en pause (store
        ouvert en plein cycle). Capteurs de particules, de pression et consigne :
        `vidange.nettoyage.capteurs.capteurs_du_materiel` ; None : absents."""
        self.reglages = reglages
        self.materiel = materiel
        self.fichier = fichier
        self.registre = registre
        self._mode = mode
        self._cycle_tourne = cycle_tourne
        self._pause = pause
        self.particules_dedans = particules_dedans
        self.particules_dehors = particules_dehors
        self.capteur_pression = pression
        self.consigne = consigne
        self._horloge = horloge
        self._maintenant = maintenant
        self._verrou = threading.RLock()
        self._ferme = _Suivi()
        self._store = INCONNU
        self._verrous_liberes = False
        self._liberes_depuis = 0.0
        self._vu_ouvert_depuis_liberation = False
        self._demande_fermeture: float | None = None
        self._mal_ferme = False
        self._purge_debut: float | None = None
        self._particules_ok_depuis: float | None = None
        self._purge_alerte = False
        self._eclairage_demande = False
        self._lampe_demandee = False
        self._fuite = False
        self._ozone_dedans: MesureOzone | None = None
        self._ozone_dedans_vu: float | None = None
        self._ozone_dehors: MesureOzone | None = None
        self._mesures: dict[str, float | None] = {}
        self._commandes: dict[str, bool] = {}
        self._consigne_v: float | None = None
        self._erreurs_vues: set[str] = set()
        self._messages: deque[str] = deque(maxlen=10)
        # Appelés à chaque message (le simulateur les met dans son planning).
        self.ecouteurs: list[Callable[[str], object]] = []
        # Autres raisons de ne pas lancer la nuit : refus() → raison, ou None (le programme
        # principal : poste « nuit UV-ozone » pas prêt, réglages d'EXEMPLE sur la vraie machine).
        # Elles ne touchent jamais une nuit déjà partie : elle va au bout, ou reprend après une
        # coupure (générateur coupé).
        self.refus_nuit_en_plus: list[Callable[[], str | None]] = []
        self._porte_spray_ouverte = False
        self._debut = horloge()
        self.nuit = _Nuit()
        self._reprendre()

    # ------------------------------------------------------------ en fond

    def demarrer(self, arret: threading.Event) -> list[threading.Thread]:
        return [lancer_boucle(MODULE, self.reglages.periode_s, self.observer, arret)]

    def _noter_erreur(self, cle: str, message: str) -> None:
        """Une panne de signal n'est notée qu'une fois au journal (pas à chaque tour)."""
        if cle not in self._erreurs_vues:
            self._erreurs_vues.add(cle)
            journal.warning("Nettoyage : %s", message)

    def _existe(self, nom: str) -> bool:
        return nom in self.materiel.branchements

    def _lire(self, nom: str) -> bool | None:
        if not self._existe(nom):
            return None
        try:
            valeur = self.materiel.lire(nom)
        except (ErreurMateriel, KeyError) as erreur:
            self._noter_erreur(nom, str(erreur))
            return None
        self._erreurs_vues.discard(nom)
        return valeur

    def _commander(self, nom: str, commande: bool) -> None:
        """Une sortie, seulement si elle change (ou n'a jamais été écrite)."""
        if self._commandes.get(nom) is commande:
            return
        if not self._existe(nom):
            self._noter_erreur(nom, f"signal « {nom} » absent de la liste : pas commandé")
            return
        try:
            self.materiel.ecrire(nom, commande)
        except (ErreurMateriel, KeyError) as erreur:
            self._noter_erreur(nom, str(erreur))
            return
        self._erreurs_vues.discard(nom)
        self._commandes[nom] = commande

    def commande(self, nom: str) -> bool:
        """Ce que le Pi commande sur cette sortie (False s'il ne l'a jamais commandée)."""
        return self._commandes.get(nom, False)

    def _lire_ozone(self, nom: str) -> MesureOzone | None:
        if not self._existe(nom):
            return None
        try:
            mesure = self.materiel.lire_ozone(nom)
        except (ErreurMateriel, KeyError) as erreur:
            self._noter_erreur(nom, str(erreur))
            return None
        self._erreurs_vues.discard(nom)
        return mesure

    def _mesurer(self, capteur: CapteurMesure | None) -> float | None:
        if capteur is None:
            return None
        try:
            valeur = capteur.lire()
        except (ErreurMateriel, OSError) as erreur:
            self._noter_erreur(capteur.nom, str(erreur))
            return None
        self._erreurs_vues.discard(capteur.nom)
        return valeur

    # ------------------------------------------------------------ chaque tour

    def observer(self) -> None:
        """Relit signaux et capteurs, fait avancer store, purge et nuit, règle les sorties."""
        with self._verrou:
            maintenant = self._horloge()
            mode = self._mode()
            self._lire_capteurs(maintenant)
            self._suivre_store(maintenant, mode)
            self._suivre_purge(maintenant, mode)
            self._suivre_fuite()
            self._suivre_nuit(maintenant, mode)
            self._regler_sorties(mode)

    def _lire_capteurs(self, maintenant: float) -> None:
        self._ozone_dedans = self._lire_ozone(OZONE_DEDANS)
        if self._ozone_dedans is not None:
            self._ozone_dedans_vu = maintenant
        self._ozone_dehors = self._lire_ozone(OZONE_DEHORS)
        self._mesures = {
            "particules_dedans": self._mesurer(self.particules_dedans),
            "particules_dehors": self._mesurer(self.particules_dehors),
            "pression": self._mesurer(self.capteur_pression),
        }

    # ------------------------------------------------------------ le store

    def _suivre_store(self, maintenant: float, mode: str) -> None:
        # Illisible (None) : ni ouvert ni fermé, « on ne sait pas » (rien ne commence).
        self._ferme.voir(self._lire(STORE), maintenant)
        stabilite = self.reglages.store.stabilite_s
        avant = self._store
        for valeur, etat in ((True, FERME), (False, OUVERT), (None, INCONNU)):
            if self._ferme.stable(valeur, maintenant, stabilite):
                self._store = etat
        if self._store != avant:
            journal.info("Nettoyage : %s", LIBELLES_STORE[self._store].lower())
            if self._store == OUVERT:
                self._store_ouvert(mode, avant)
            elif self._store == FERME:
                self._store_ferme(maintenant, mode)
        reglage = self.reglages.store
        if (
            self._verrous_liberes
            and self._store == FERME
            and not self._vu_ouvert_depuis_liberation
            and maintenant - self._liberes_depuis > reglage.deverrouille_max_s
        ):
            self._verrouiller()
            self._dire("Store pas ouvert : verrous remis.")
        if self._store == OUVERT:
            self._vu_ouvert_depuis_liberation = True
        attente = self._demande_fermeture
        if (
            attente is not None
            and self._store != FERME
            and maintenant - attente > reglage.alerte_fermeture_s
        ):
            self._demande_fermeture = None
            self._mal_ferme = True
            self._alerter(
                f"Store mal fermé : pas fermé {reglage.alerte_fermeture_s:g} s après la demande "
                "de fermeture. Pas de purge ni d'ozone.",
                QUOI_FAIRE_STORE,
            )

    def _store_ouvert(self, mode: str, avant: str) -> None:
        if self._purge_debut is not None:
            self._purge_debut = None
            self._purge_alerte = False
            self._particules_ok_depuis = None
            journal.warning("Nettoyage : store rouvert pendant la purge, purge remise à zéro")
            self._dire("Store rouvert : purge remise à zéro.")
        if self._lampe_demandee:
            self._lampe_demandee = False
            self._dire("Store ouvert : lampe UV des têtes éteinte.")
        nuit = self.nuit
        if nuit.phase in (GENERATION, CONTACT, RETOUR):
            self._couper_generation()
            self._alerter("Store ouvert pendant la nuit UV-ozone.", QUOI_FAIRE_OUVERT_NUIT)
        elif nuit.phase == ERREUR and not self._verrous_liberes:
            nuit.cle_vue = True
            journal.warning("Nettoyage : store ouvert par la clé de dépannage (nuit en erreur)")
        elif not self._verrous_liberes and avant == FERME:
            journal.warning("Nettoyage : store ouvert sans que le Pi libère les verrous (clé ?)")
        if not self._verrous_liberes:
            # Store déjà ouvert (clé, ou Pi redémarré store ouvert) : les verrous restent libres
            # jusqu'à sa fermeture, pour que la barre basse redescende sur le seuil.
            self._verrous_liberes = True
            self._liberes_depuis = self._horloge()
        if self._cycle_tourne() and mode != "mais":
            self._mal_ferme = True
            self._alerter("Store mal fermé : il s'est ouvert pendant un cycle.", QUOI_FAIRE_STORE)
            self._pause()

    def _store_ferme(self, maintenant: float, mode: str) -> None:
        if self._verrous_liberes:
            self._verrouiller()
        self._demande_fermeture = None
        self._mal_ferme = False
        nuit = self.nuit
        if nuit.phase == ERREUR and nuit.cle_vue:
            journal.warning(
                "Nettoyage : store refermé après la clé de dépannage : nuit en erreur close"
            )
            self._dire("Store refermé après la clé de dépannage : nuit UV-ozone close.")
            self._nouvelle_nuit()
        if mode != "mais" and self.nuit.phase not in NUIT_ACTIVE:
            self._commencer_purge(maintenant)

    def _verrouiller(self) -> None:
        self._verrous_liberes = False
        self._vu_ouvert_depuis_liberation = False
        journal.info("Nettoyage : verrous du store remis (hors tension)")

    def refus_ouverture(self) -> str | None:
        """Pourquoi « ouvrir le store » est refusé maintenant (None : permis)."""
        with self._verrou:
            if self._cycle_tourne():
                return "pas pendant un cycle"
            if self._purge_debut is not None:
                return "purge en cours"
            phase = self.nuit.phase
            if phase == ERREUR:
                return (
                    "nuit UV-ozone en erreur : ouverture seulement par la clé de dépannage, après "
                    "avoir vérifié l'ozone"
                )
            if phase in (GENERATION, CONTACT, RETOUR):
                return "nuit UV-ozone pas finie (l'ozone n'est pas encore revenu sous le seuil)"
            if self._mode() == "uv_ozone":
                seuil = self.reglages.ozone.seuil_ouverture_ppm
                mesure = self._ozone_dedans
                if mesure is None:
                    return "mode UV-ozone : capteur d'ozone du dedans muet, ouverture refusée"
                if mesure.au_plafond or mesure.ppm >= seuil:
                    return (
                        f"mode UV-ozone : ozone dedans {self._texte_ozone(mesure)}, ouverture "
                        f"seulement sous {_ppm(seuil)} ppm"
                    )
            return None

    def demander_ouverture(self, qui: str) -> None:
        """« Ouvrir le store » : libère les verrous (sous tension). Le moteur reste à Karulium
        (bouton « monter », commande maintenue câblée)."""
        with self._verrou:
            refus = self.refus_ouverture()
            if refus is not None:
                raise ErreurNettoyage(f"Ouverture du store refusée : {refus}.")
            if self._verrous_liberes:
                return
            self._verrous_liberes = True
            self._liberes_depuis = self._horloge()
            self._vu_ouvert_depuis_liberation = self._store == OUVERT
            self._commander(VERROUS, True)
            journal.warning("Nettoyage : verrous du store libérés (%s)", qui)
            self._dire("Verrous libérés : tenir le bouton « monter » du store.")

    def demander_fermeture(self, qui: str) -> None:
        """Karulium va refermer le store (bouton « descendre ») : alerte s'il n'est pas fermé à
        temps. Store déjà fermé et jamais ouvert : les verrous sont remis tout de suite."""
        with self._verrou:
            if self._store == FERME and not self._vu_ouvert_depuis_liberation:
                if self._verrous_liberes:
                    self._verrouiller()
                    self._commander(VERROUS, False)
                    self._dire("Store fermé : verrous remis.")
                return
            self._demande_fermeture = self._horloge()
            journal.info("Nettoyage : fermeture du store demandée (%s)", qui)
            self._dire("Tenir le bouton « descendre » jusqu'en bas.")

    @property
    def condition_store(self) -> Condition:
        """Condition générale du chef : rien ne commence store ouvert (sauf en mode maïs, où le
        portique lent par la clé relève du module Portique)."""
        return Condition(
            "store de l'enceinte fermé", self.store_permet_les_mouvements, QUOI_FAIRE_STORE
        )

    def store_permet_les_mouvements(self) -> bool:
        with self._verrou:
            return self._mode() == "mais" or self._store == FERME

    # ------------------------------------------------------------ la purge

    def _commencer_purge(self, maintenant: float) -> None:
        self._purge_debut = maintenant
        self._purge_alerte = False
        self._particules_ok_depuis = None
        journal.info("Nettoyage : purge après fermeture, ventilateur au plein")
        self._dire("Store fermé : purge (ventilateur au plein).")

    def _conditions_purge(self, maintenant: float) -> tuple[bool, bool, bool]:
        """Les 3 conditions de fin de purge : durée, particules stables, pression."""
        reglage = self.reglages.purge
        assert self._purge_debut is not None
        duree = maintenant - self._purge_debut >= reglage.duree_min_s
        particules = (
            self._particules_ok_depuis is not None
            and maintenant - self._particules_ok_depuis >= reglage.stabilite_particules_s
        )
        pression = self._mesures.get("pression")
        return duree, particules, pression is not None and pression >= reglage.pression_fin

    def _suivre_purge(self, maintenant: float, mode: str) -> None:
        if self._purge_debut is None:
            return
        if mode == "mais":
            self._purge_debut = None
            self._dire("Mode maïs : pas de purge.")
            return
        if self._store != FERME:
            return
        reglage = self.reglages.purge
        dedans = self._mesures.get("particules_dedans")
        dehors = self._mesures.get("particules_dehors")
        if (
            dedans is not None
            and dehors is not None
            and dedans <= reglage.rapport_particules_max * dehors
        ):
            if self._particules_ok_depuis is None:
                self._particules_ok_depuis = maintenant
        else:
            self._particules_ok_depuis = None
        duree, particules, pression = self._conditions_purge(maintenant)
        if duree and particules and pression:
            ecoule = maintenant - self._purge_debut
            self._purge_debut = None
            journal.info("Nettoyage : purge finie en %s, ventilateur au normal", _minutes(ecoule))
            self._dire(f"Purge finie ({_minutes(ecoule)}) : ventilateur au normal.")
            return
        alerte = self.reglages.purge.alerte_s
        if not self._purge_alerte and maintenant - self._purge_debut >= alerte:
            self._purge_alerte = True
            manque = [
                texte
                for ok, texte in (
                    (particules, "particules pas assez basses (ou capteur absent)"),
                    (pression, "surpression trop faible (ou capteur absent)"),
                )
                if not ok
            ]
            self._alerter(
                f"Purge pas finie après {_minutes(alerte)} : {', '.join(manque) or 'durée'}. "
                "Dosage et versements restent interdits.",
                QUOI_FAIRE_PURGE,
            )

    def passer_outre(self, qui: str) -> None:
        """Karulium décide de finir la purge sans ses conditions (noté au journal)."""
        with self._verrou:
            if self._purge_debut is None:
                raise ErreurNettoyage("Pas de purge en cours.")
            self._purge_debut = None
            journal.warning("Nettoyage : purge PASSÉE OUTRE par %s (conditions pas atteintes)", qui)
            self._dire("Purge passée outre (noté au journal) : ventilateur au normal.")

    @property
    def purge_en_cours(self) -> bool:
        return self._purge_debut is not None

    def refus_geste(self, geste: str) -> str | None:
        """Pour le chef (Chef.interdire) : les gestes protégés sont interdits pendant la purge."""
        if geste in GESTES_PROTEGES and self._purge_debut is not None:
            return "purge en cours"
        return None

    # ------------------------------------------------------------ fuite d'ozone

    def _suivre_fuite(self) -> None:
        mesure = self._ozone_dehors
        if mesure is None:
            return
        seuil = self.reglages.ozone.seuil_fuite_ppm
        fuite = mesure.au_plafond or mesure.ppm > seuil
        if fuite and not self._fuite:
            self._fuite = True
            self._couper_generation()
            self._alerter(
                f"FUITE D'OZONE : ozone dehors {self._texte_ozone(mesure)} (seuil {_ppm(seuil)} "
                "ppm). Générateur coupé.",
                QUOI_FAIRE_FUITE,
                envoyer=True,
            )
        elif not fuite and self._fuite:
            self._fuite = False
            journal.warning("Nettoyage : ozone dehors de nouveau sous le seuil de fuite")
            self._dire("Ozone dehors de nouveau sous le seuil.")

    # ------------------------------------------------------------ la nuit UV-ozone

    def refus_nuit(self) -> str | None:
        """Pourquoi la nuit UV-ozone ne peut pas partir maintenant (None : elle peut)."""
        with self._verrou:
            if self._mode() != "uv_ozone":
                return "mode « UV-ozone » pas choisi"
            for refus in self.refus_nuit_en_plus:
                raison = refus()
                if raison is not None:
                    return raison
            if self._cycle_tourne():
                return "pas pendant un cycle"
            if self.nuit.phase in NUIT_ACTIVE:
                return "une nuit UV-ozone est déjà en cours (ou en erreur)"
            if self._store != FERME:
                return "store pas fermé"
            if self._verrous_liberes:
                return "verrous du store pas remis"
            if self._mal_ferme:
                return "store mal fermé"
            porte = self._lire(PORTE_SPRAY) if self._existe(PORTE_SPRAY) else False
            if porte is None:
                return "porte du spray illisible"
            if porte:
                return "porte du spray ouverte"
            if self._ozone_dedans is None:
                return "capteur d'ozone du dedans muet"
            if self._fuite:
                return "fuite d'ozone en cours"
            return None

    def programmer_nuit(self, qui: str, tout_de_suite: bool = False) -> None:
        """La nuit UV-ozone, à l'heure réglée (aujourd'hui, ou demain si elle est passée) ou tout
        de suite. Les conditions sont revues au départ."""
        with self._verrou:
            refus = self.refus_nuit()
            if refus is not None:
                raise ErreurNettoyage(f"Nuit UV-ozone refusée : {refus}.")
            if tout_de_suite:
                journal.warning("Nettoyage : nuit UV-ozone lancée tout de suite (%s)", qui)
                self._partir(self._horloge())
                return
            heure, minute = (int(x) for x in self.reglages.ozone.heure_depart.split(":"))
            jour = self._maintenant()
            prevu = jour.replace(hour=heure, minute=minute, second=0, microsecond=0)
            if prevu <= jour:
                prevu += timedelta(days=1)
            self.nuit = _Nuit(phase=ATTENTE, depart_prevu=prevu)
            journal.warning("Nettoyage : nuit UV-ozone prévue à %s (%s)", prevu.isoformat(), qui)
            self._dire(f"Nuit UV-ozone prévue à {prevu:%H:%M}.")

    def annuler_nuit(self, qui: str) -> None:
        with self._verrou:
            if self.nuit.phase != ATTENTE:
                raise ErreurNettoyage(
                    "Pas de nuit UV-ozone prévue à annuler (une nuit partie va au bout)."
                )
            self.nuit = _Nuit()
            journal.warning("Nettoyage : nuit UV-ozone prévue annulée (%s)", qui)
            self._dire("Nuit UV-ozone annulée.")

    def _partir(self, maintenant: float) -> None:
        nuit = _Nuit(phase=GENERATION, debut=maintenant, debut_jour=self._maintenant().isoformat())
        self.nuit = nuit
        # Plus de purge : la nuit coupe le ventilateur.
        self._purge_debut = None
        if self.registre is not None:
            try:
                nuit.cycle = self.registre.commencer_cycle(MODULE, remarque="nuit UV-ozone")
            except ErreurRegistre as erreur:
                journal.error("Nettoyage : registre : %s", erreur)
        panneau = self.texte_panneau()
        journal.warning(
            "Nettoyage : nuit UV-ozone, génération d'ozone ; panneau du poste : %s", panneau
        )
        self._dire(f"Nuit UV-ozone : génération d'ozone (panneau du poste du fût {panneau}).")
        self._garder()

    def texte_panneau(self) -> str:
        """Le panneau long du poste du fût, pour le journal et l'affichage (jamais une condition) :
        « levé » (contact fermé) est la position normale."""
        if not self._existe(PANNEAU):
            return "absent de la liste"
        panneau = self._lire(PANNEAU)
        if panneau is None:
            return "illisible"
        return "levé (position normale)" if panneau else "rabattu"

    def _couper_generation(self) -> None:
        """Le générateur s'arrête (store, porte, fuite) : la nuit passe à l'attente du retour."""
        nuit = self.nuit
        if nuit.phase == GENERATION:
            nuit.phase = CONTACT
            nuit.generation_coupee = True
            self._garder()
        self._commander(GENERATEUR, False)

    def _suivre_nuit(self, maintenant: float, mode: str) -> None:
        nuit = self.nuit
        if nuit.phase == ATTENTE:
            if mode != "uv_ozone":
                self.nuit = _Nuit()
                self._dire("Mode changé : nuit UV-ozone prévue annulée.")
                return
            assert nuit.depart_prevu is not None
            if self._maintenant() < nuit.depart_prevu:
                return
            refus = self.refus_nuit()
            if refus is not None:
                self.nuit = _Nuit()
                self._alerter(f"Nuit UV-ozone pas partie à l'heure : {refus}.", QUOI_FAIRE_STORE)
                return
            self._partir(maintenant)
            return
        if nuit.phase not in (GENERATION, CONTACT, RETOUR):
            return
        assert nuit.debut is not None
        ozone = self.reglages.ozone
        ecoule = maintenant - nuit.debut
        mesure = self._ozone_dedans
        if mesure is not None:
            nuit.max_ppm = mesure.ppm if nuit.max_ppm is None else max(nuit.max_ppm, mesure.ppm)
            if nuit.dernier_journal is None or maintenant - nuit.dernier_journal >= ozone.journal_s:
                nuit.dernier_journal = maintenant
                self._noter_ozone(mesure)
        porte = self._lire(PORTE_SPRAY)
        if porte and not self._porte_spray_ouverte:
            self._couper_generation()
            self._alerter(
                "Porte du spray ouverte pendant la nuit UV-ozone.", QUOI_FAIRE_OUVERT_NUIT
            )
        self._porte_spray_ouverte = bool(porte)
        muet = self._delai_muet()
        vu = self._ozone_dedans_vu if self._ozone_dedans_vu is not None else self._debut
        if mesure is None and maintenant - max(vu, nuit.debut) > muet:
            self._erreur("capteur d'ozone du dedans muet")
            return
        if ecoule > ozone.t_max_retour_s:
            self._erreur(
                f"ozone dedans pas revenu sous {_ppm(ozone.seuil_ouverture_ppm)} ppm au bout de "
                f"{ozone.t_max_retour_s / 3600:g} h"
            )
            return
        if nuit.phase == GENERATION and ecoule >= ozone.t_generation_s:
            nuit.phase = CONTACT
            journal.info("Nettoyage : fin de la génération d'ozone, contact")
            self._garder()
        if nuit.phase == CONTACT and ecoule >= ozone.t_contact_s:
            if (
                not nuit.generation_coupee
                and nuit.max_ppm is not None
                and nuit.max_ppm < ozone.attendu_min_ppm
            ):
                self._erreur(
                    f"mesure incohérente : au plus {_ppm(round(nuit.max_ppm, 2))} ppm lus dedans "
                    f"pendant le contact (attendu au moins {_ppm(ozone.attendu_min_ppm)} ppm : "
                    "générateur en panne, ou capteur faux ?)"
                )
                return
            nuit.phase = RETOUR
            journal.info("Nettoyage : fin du contact, attente du retour sous le seuil")
            self._garder()
        if nuit.phase != RETOUR:
            return
        bas = (
            mesure is not None and not mesure.au_plafond and mesure.ppm < ozone.seuil_ouverture_ppm
        )
        if not bas:
            nuit.ozone_bas_depuis = None
            return
        if nuit.ozone_bas_depuis is None:
            nuit.ozone_bas_depuis = maintenant
        if maintenant - nuit.ozone_bas_depuis >= ozone.stabilite_retour_s:
            nuit.phase = FINI
            journal.warning("Nettoyage : nuit UV-ozone finie (%s)", _minutes(ecoule))
            self._dire("Nuit UV-ozone finie : ozone sous le seuil. Le store reste verrouillé.")
            self._finir_cycle("termine")
            self._garder()

    def _delai_muet(self) -> float:
        signal = self.materiel.liste.signaux.get(OZONE_DEDANS)
        if signal is not None and signal.ozone is not None:
            return signal.ozone.delai_muet_s
        return 0.0

    def _erreur(self, raison: str) -> None:
        nuit = self.nuit
        self._commander(GENERATEUR, False)
        nuit.phase = ERREUR
        nuit.erreur = raison
        self._alerter(f"Nuit UV-ozone en erreur : {raison}. Store verrouillé.", QUOI_FAIRE_NUIT)
        # Le cycle de la nuit part tout de suite (file d'envoi), avec cette alerte.
        self._finir_cycle("abandonne")
        self._garder()

    def _noter_ozone(self, mesure: MesureOzone) -> None:
        if self.registre is None:
            return
        try:
            self.registre.noter_mesure(
                OZONE_DEDANS,
                round(mesure.ppm, 3),
                "ppm",
                capteur=OZONE_DEDANS,
                cycle=self.nuit.cycle,
            )
        except ErreurRegistre as erreur:
            journal.error("Nettoyage : registre : %s", erreur)

    def _finir_cycle(self, issue: str) -> None:
        nuit = self.nuit
        if self.registre is None or nuit.cycle is None:
            return
        try:
            self.registre.finir_cycle(nuit.cycle, issue)  # type: ignore[arg-type]
        except ErreurRegistre as erreur:
            journal.error("Nettoyage : registre : %s", erreur)
        nuit.cycle = None

    def _nouvelle_nuit(self) -> None:
        self.nuit = _Nuit()
        self._garder()

    def refus_changement_mode(self) -> str | None:
        """Pour ModeMachine : pas de changement de mode pendant une nuit qui n'est pas revenue."""
        if self.nuit.phase in (GENERATION, CONTACT, RETOUR):
            return "nuit UV-ozone en cours (attendre le retour de l'ozone sous le seuil)"
        return None

    @property
    def air_permis(self) -> bool:
        """Pour le module Air comprimé (pas écrit) : le compresseur peut-il tourner ?"""
        return self.nuit.phase not in NUIT_ACTIVE

    # ------------------------------------------------------------ la reprise

    def _garder(self) -> None:
        """La nuit dans son fichier (sauf la nuit prévue : elle ne repart jamais seule)."""
        if self.fichier is None:
            return
        nuit = self.nuit
        donnees = {}
        if nuit.phase in NUIT_ACTIVE:
            donnees = {
                "phase": nuit.phase,
                "debut_jour": nuit.debut_jour,
                "cycle": nuit.cycle,
                "erreur": nuit.erreur,
            }
        try:
            self.fichier.parent.mkdir(parents=True, exist_ok=True)
            provisoire = self.fichier.with_suffix(".tmp")
            provisoire.write_text(json.dumps(donnees), encoding="utf-8")
            os.replace(provisoire, self.fichier)
        except OSError as erreur:
            journal.error("Nettoyage : nuit pas gardée dans %s : %s", self.fichier, erreur)

    def _reprendre(self) -> None:
        """Après une coupure en pleine nuit : générateur coupé, reprise à l'attente du retour."""
        if self.fichier is None or not self.fichier.exists():
            return
        try:
            donnees = json.loads(self.fichier.read_text(encoding="utf-8"))
            phase = donnees.get("phase")
        except (OSError, ValueError, AttributeError) as erreur:
            journal.error("Nettoyage : fichier de la nuit illisible (%s) : ignoré", erreur)
            return
        if phase not in NUIT_ACTIVE:
            return
        debut = self._horloge()
        try:
            ecoule = (
                self._maintenant() - datetime.fromisoformat(donnees["debut_jour"])
            ).total_seconds()
            debut -= max(ecoule, 0.0)
        except (KeyError, TypeError, ValueError):
            pass
        self.nuit = _Nuit(
            phase=ERREUR if phase == ERREUR else RETOUR,
            debut=debut,
            debut_jour=donnees.get("debut_jour"),
            cycle=donnees.get("cycle"),
            generation_coupee=True,
            erreur=donnees.get("erreur", ""),
        )
        journal.warning(
            "Nettoyage : reprise d'une nuit UV-ozone (%s) : générateur coupé, %s",
            phase,
            "toujours en erreur" if phase == ERREUR else "attente du retour sous le seuil",
        )
        self._dire("Reprise de la nuit UV-ozone après une coupure : générateur coupé.")
        self._garder()

    # ------------------------------------------------------------ lampe UV, éclairage

    def lampe_uv(self, allumer: bool, qui: str) -> None:
        """Lampe UV-C des têtes (bain des têtes) : permise seulement store fermé."""
        with self._verrou:
            if allumer and self._store != FERME:
                raise ErreurNettoyage("Lampe UV des têtes refusée : store pas fermé.")
            self._lampe_demandee = allumer
            journal.info(
                "Nettoyage : lampe UV des têtes %s (%s)", "allumée" if allumer else "éteinte", qui
            )
            self._commander(LAMPE_UV, allumer)

    def lampe_uv_permise(self) -> bool:
        with self._verrou:
            return self._store == FERME

    def eclairage(self, allumer: bool, qui: str) -> None:
        with self._verrou:
            if allumer and self._mode() == "uv_ozone":
                raise ErreurNettoyage("Éclairage refusé : il reste éteint en mode UV-ozone.")
            self._eclairage_demande = allumer
            journal.info("Nettoyage : éclairage %s (%s)", "allumé" if allumer else "éteint", qui)
            self._regler_sorties(self._mode())

    # ------------------------------------------------------------ les sorties

    def niveau_ventilateur(self, mode: str) -> str:
        if self.nuit.phase in NUIT_ACTIVE or mode == "mais":
            return ARRET
        if self._purge_debut is not None:
            return PLEIN
        return NORMAL

    def _regler_sorties(self, mode: str) -> None:
        nuit_active = self.nuit.phase in NUIT_ACTIVE
        self._commander(VERROUS, self._verrous_liberes)
        niveau = self.niveau_ventilateur(mode)
        self._commander(VENTILATEUR, niveau != ARRET)
        self._regler_consigne(getattr(self.reglages.ventilateur, f"{niveau}_v"))
        generation = self.nuit.phase == GENERATION and not self._fuite and self._store == FERME
        self._commander(GENERATEUR, generation)
        if self._store != FERME:
            self._lampe_demandee = False
        self._commander(LAMPE_UV, self._lampe_demandee)
        if mode == "uv_ozone":
            self._eclairage_demande = False
        self._commander(
            ECLAIRAGE, mode != "uv_ozone" and (self._eclairage_demande or self._cycle_tourne())
        )
        if nuit_active:
            self._commander(COMPRESSEUR, False)
        self._commander(COUPURE_ARMOIRE, nuit_active)
        if self._existe(VOYANT) and (self._fuite or self._commandes.get(VOYANT)):
            # Le voyant et le buzzer sonnent tant que la fuite dure (ils servent aussi au
            # pilotage à distance : on ne les éteint que si c'est nous qui les avons allumés).
            self._commander(VOYANT, self._fuite)

    def _regler_consigne(self, volts: float) -> None:
        if self.consigne is None or self._consigne_v == volts:
            return
        try:
            self.consigne.regler(volts)
        except ErreurMateriel as erreur:
            self._noter_erreur("consigne_ventilateur", str(erreur))
            return
        self._erreurs_vues.discard("consigne_ventilateur")
        self._consigne_v = volts

    # ------------------------------------------------------------ alertes et état

    def _dire(self, message: str) -> None:
        self._messages.append(message)
        for ecouteur in self.ecouteurs:
            ecouteur(message)

    def _alerter(self, message: str, quoi_faire: str, envoyer: bool = False) -> None:
        """Une alerte : journal, messages, alarme du registre (écran, page web), avec le cycle de
        la nuit s'il y en a un. `envoyer` : elle part aussi tout de suite par la file d'envoi,
        dans un cycle à elle (fuite d'ozone)."""
        journal.warning("Nettoyage : %s", message)
        self._dire(message)
        if self.registre is None:
            return
        try:
            if envoyer:
                cycle = self.registre.commencer_cycle(MODULE, remarque=message)
                self.registre.noter_alarme(MODULE, message, quoi_faire, cycle=cycle)
                self.registre.finir_cycle(cycle, "abandonne")
            else:
                self.registre.noter_alarme(MODULE, message, quoi_faire, cycle=self.nuit.cycle)
        except ErreurRegistre as erreur:
            journal.error("Nettoyage : registre : %s", erreur)

    def _texte_ozone(self, mesure: MesureOzone | None, nom: str = OZONE_DEDANS) -> str:
        if mesure is None:
            return "muet" if self._existe(nom) else "absent"
        signal = self.materiel.liste.signaux[nom]
        plafond = signal.ozone.plafond_ppm if signal.ozone is not None else 10.0
        return texte_ppm(mesure, plafond)

    def etat(self) -> EtatNettoyage:
        with self._verrou:
            maintenant = self._horloge()
            mode = self._mode()
            purge = self._purge_debut is not None
            conditions = self._conditions_purge(maintenant) if purge else (False, False, False)
            nuit = self.nuit
            securite = self._lire(OZONE_SECURITE) if self._existe(OZONE_SECURITE) else None
            return EtatNettoyage(
                store=self._store,
                store_libelle=LIBELLES_STORE[self._store],
                verrous_liberes=self._verrous_liberes,
                store_mal_ferme=self._mal_ferme,
                mode=mode,
                purge=purge,
                purge_depuis_s=None if not purge else maintenant - self._purge_debut,  # type: ignore[operator]
                purge_duree_ok=conditions[0],
                purge_particules_ok=conditions[1],
                purge_pression_ok=conditions[2],
                purge_alerte=self._purge_alerte,
                particules_dedans=self._mesures.get("particules_dedans"),
                particules_dehors=self._mesures.get("particules_dehors"),
                pression_pa=self._mesures.get("pression"),
                ventilateur=self.niveau_ventilateur(mode),
                eclairage=self.commande(ECLAIRAGE),
                lampe_uv=self.commande(LAMPE_UV),
                nuit=nuit.phase,
                nuit_libelle=LIBELLES_NUIT[nuit.phase],
                nuit_depart_prevu=None
                if nuit.depart_prevu is None
                else nuit.depart_prevu.isoformat(),
                nuit_depuis_s=None if nuit.debut is None else maintenant - nuit.debut,
                nuit_erreur=nuit.erreur,
                ozone_dedans=self._texte_ozone(self._ozone_dedans),
                ozone_dehors=self._texte_ozone(self._ozone_dehors, OZONE_DEHORS),
                panneau=self.texte_panneau(),
                ozone_securite_ok=securite,
                fuite=self._fuite,
                refus_ouverture=self.refus_ouverture(),
                refus_nuit=self.refus_nuit(),
                messages=tuple(self._messages),
                exemple=self.reglages.exemple,
            )

    def constats(self) -> list[Constat]:
        """Pour la check-list de démarrage. Jamais bloquant : la sécurité est câblée."""
        etat = self.etat()
        constats = []
        absents = [
            nom
            for nom, capteur in (
                ("particules_dedans", self.particules_dedans),
                ("particules_dehors", self.particules_dehors),
                ("pression_enceinte", self.capteur_pression),
            )
            if capteur is None
        ]
        if absents:
            constats.append(
                Constat(
                    SUJET,
                    "attention",
                    f"capteurs de purge pas encore branchés ({', '.join(absents)}) : chaque purge "
                    "finira en alerte au bout de "
                    f"{_minutes(self.reglages.purge.alerte_s)}",
                    "Attendre la fin de purge ou passer outre à l'écran (page « Enceinte »), "
                    "jusqu'au choix des capteurs.",
                )
            )
        if self.consigne is None:
            constats.append(
                Constat(
                    SUJET,
                    "attention",
                    "consigne 0-10 V du ventilateur pas encore branchée : le moteur EC reste à "
                    "l'arrêt même relais fermé",
                    "Choisir le convertisseur (question de la tâche 38).",
                )
            )
        if etat.nuit == ERREUR:
            constats.append(
                Constat(
                    SUJET,
                    "attention",
                    f"nuit UV-ozone en erreur : {etat.nuit_erreur}",
                    QUOI_FAIRE_NUIT,
                )
            )
        if etat.fuite:
            constats.append(Constat(SUJET, "attention", "fuite d'ozone dehors", QUOI_FAIRE_FUITE))
        if not constats:
            constats.append(Constat(SUJET, "ok", etat.store_libelle.lower()))
        return constats
