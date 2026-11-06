"""Le Nettoyage sur la machine imaginaire du simulateur : faux store, fausse enceinte (particules,
surpression, ozone) et les gestes de Karulium, écrits en modules pour le chef du simulateur.

    simulation = nettoyage_du_simulateur(simulateur)       # le VRAI Nettoyage, en temps simulé
    module = module_fermeture_purge(simulation)            # ouvrir, refermer, purge
    planning = simulateur.jouer([module])

Le faux store (`FauxStore`) : Karulium tient le bouton « monter » ou « descendre » (le Pi ne
commande pas le moteur) ; le store ne monte que verrous libérés (ou avec la clé de dépannage) ;
il met course_s à bouger ; arrivé en bas, le reed `store_ferme` rebondit pendant rebond_s.

La fausse enceinte (`FausseEnceinte`) suit ce que le Pi commande :
- particules du dedans : celles du conteneur store ouvert ; store fermé et ventilateur en marche,
  elles tendent vers fond × dehors (HEPA), d'autant plus vite que la consigne est haute ;
- surpression : store fermé et ventilateur en marche, pression_10v_pa × consigne / 10 V (moins si
  le HEPA est colmaté) ;
- ozone du dedans : monte quand le générateur est alimenté (relais du Pi ET chaîne câblée : store
  fermé, porte du spray fermée), baisse de moitié en demi_vie_ozone_s ; plafond du capteur.
L'ozone du dehors ne change que par les événements du scénario (« mesure: ozone_dehors »).

Les modules ci-dessous ne sont PAS des modules de la machine (le Nettoyage tourne en fond) : ce
sont les gestes de Karulium dans un scénario (ouvrir, fermer, choisir le mode, lancer la nuit),
chacun avec ce qu'on attend du Nettoyage.
"""

import math
from collections.abc import Callable
from typing import Any

from vidange.chef import Condition, ErreurEtape, Etape, Module
from vidange.materiel import FausseFabrique
from vidange.nettoyage.capteurs import FausseConsigne, FauxCapteur
from vidange.nettoyage.nettoyage import (
    CONTACT,
    ERREUR,
    FERME,
    FINI,
    GENERATEUR,
    OUVERT,
    OZONE_DEDANS,
    PORTE_SPRAY,
    RETOUR,
    STORE,
    VENTILATEUR,
    VERROUS,
    Nettoyage,
)
from vidange.reglages import NettoyageSimule
from vidange.simulateur.simulateur import ErreurSimulation, Simulateur

QUOI_FAIRE = (
    "Scénario du simulateur : regarder le planning (messages du Nettoyage) et les réglages "
    "machine.yaml → nettoyage et simulateur.yaml → nettoyage."
)


class FauxStore:
    """Le store imaginaire : position (0 en bas, 1 en haut), moteur tenu par Karulium."""

    def __init__(
        self,
        fabrique: FausseFabrique,
        reglages: NettoyageSimule,
        horloge: Callable[[], float],
        ferme: bool = False,
    ) -> None:
        self._fabrique = fabrique
        self.reglages = reglages
        self._horloge = horloge
        # Hauteur de la barre basse, de 0 (sur le seuil) à 1 (sous le coffre).
        self.hauteur = 0.0 if ferme else 1.0
        # Sens du moteur : +1 monte, −1 descend, 0 arrêté ; depuis quand il est arrivé en bas.
        self.sens = 0
        self._depuis = horloge()
        self._en_bas_depuis: float | None = horloge() - reglages.rebond_s if ferme else None
        # Ce que Karulium a fait, pour les tests : « monter », « descendre », « bloqué »...
        self.historique: list[str] = []
        self.avancer()

    def monter(self, cle: bool = False) -> bool:
        """Karulium tient « monter ». Verrous fermés (sans courant) : le store ne bouge pas, sauf
        avec la clé de dépannage. Rend True s'il monte."""
        self.avancer()
        if not cle and not self._fabrique.commande(VERROUS):
            self.historique.append("bloqué par les verrous")
            return False
        self.historique.append("monter (clé)" if cle else "monter")
        self.sens = 1
        self._en_bas_depuis = None
        self.avancer()
        return True

    def descendre(self) -> None:
        self.avancer()
        self.historique.append("descendre")
        self.sens = -1
        self.avancer()

    @property
    def en_bas(self) -> bool:
        return self.hauteur <= 0.0

    def avancer(self) -> None:
        """Le store bouge jusqu'à maintenant ; le reed suit (avec ses rebonds en bas)."""
        maintenant = self._horloge()
        ecoule = maintenant - self._depuis
        self._depuis = maintenant
        if self.sens != 0:
            self.hauteur += self.sens * ecoule / self.reglages.course_s
            if self.sens > 0 and self.hauteur >= 1.0:
                self.hauteur, self.sens = 1.0, 0
            elif self.sens < 0 and self.hauteur <= 0.0:
                arrivee = maintenant + self.hauteur * self.reglages.course_s
                self.hauteur, self.sens = 0.0, 0
                self._en_bas_depuis = arrivee
        self._fabrique.actionner(STORE, self.reed())

    def reed(self) -> bool:
        """Le reed du bas : fermé en bas ; pendant rebond_s après l'arrivée, il s'ouvre et se
        ferme toutes les rebond_pas_s."""
        if self._en_bas_depuis is None or not self.en_bas:
            return False
        ecoule = self._horloge() - self._en_bas_depuis
        if ecoule >= self.reglages.rebond_s - 1e-6:
            return True
        return self._rebond(ecoule) % 2 == 0

    def _rebond(self, ecoule: float) -> int:
        """Numéro du rebond (0, 1, 2...) ; la marge évite qu'un arrondi en saute un."""
        return math.floor(ecoule / self.reglages.rebond_pas_s + 1e-6)

    def prochain_instant(self) -> float | None:
        """Quand le store aura quelque chose de nouveau : arrivée, prochain rebond du reed."""
        maintenant = self._horloge()
        if self.sens > 0:
            return maintenant + (1.0 - self.hauteur) * self.reglages.course_s
        if self.sens < 0:
            return maintenant + self.hauteur * self.reglages.course_s
        if self._en_bas_depuis is not None:
            ecoule = maintenant - self._en_bas_depuis
            if ecoule < self.reglages.rebond_s - 1e-6:
                pas = self.reglages.rebond_pas_s
                return self._en_bas_depuis + min(
                    (self._rebond(ecoule) + 1) * pas, self.reglages.rebond_s
                )
        return None


class FausseEnceinte:
    """L'air imaginaire de l'enceinte : particules, surpression, ozone du dedans."""

    def __init__(
        self,
        fabrique: FausseFabrique,
        reglages: NettoyageSimule,
        store: FauxStore,
        consigne: FausseConsigne,
        horloge: Callable[[], float],
        plafond_ppm: float,
        porte_ouverte: Callable[[], bool] = lambda: False,
        hepa_colmate: bool = False,
    ) -> None:
        self._fabrique = fabrique
        self._porte_ouverte = porte_ouverte
        self.reglages = reglages
        self.store = store
        self.consigne = consigne
        self._horloge = horloge
        self.plafond_ppm = plafond_ppm
        self.hepa_colmate = hepa_colmate
        self._depuis = horloge()
        self.particules_dedans = FauxCapteur(
            "particules_dedans", "µg/m³", reglages.particules_ouvert
        )
        self.particules_dehors = FauxCapteur(
            "particules_dehors", "µg/m³", reglages.particules_dehors
        )
        self.pression = FauxCapteur("pression_enceinte", "Pa", 0.0)
        self.ozone_ppm = 0.0
        # Plus haut ozone du dedans (ppm, vrai, sans le plafond du capteur).
        self.ozone_max_ppm = 0.0
        self._fabrique.regler(OZONE_DEDANS, 0.0)

    def generateur_alimente(self) -> bool:
        """Le relais du Pi ET la chaîne câblée (reed du bas du store, porte du spray fermée)."""
        return (
            self._fabrique.commande(GENERATEUR) and self.store.reed() and not self._porte_ouverte()
        )

    def avancer(self) -> None:
        maintenant = self._horloge()
        dt = maintenant - self._depuis
        self._depuis = maintenant
        self.store.avancer()
        reglages = self.reglages
        volts = self.consigne.volts or 0.0
        souffle = volts / 10.0 if self._fabrique.commande(VENTILATEUR) else 0.0
        ferme = self.store.en_bas
        dedans = self.particules_dedans
        assert dedans.valeur is not None
        if not ferme:
            dedans.valeur = reglages.particules_ouvert
        elif souffle > 0 and dt > 0:
            cible = reglages.particules_fond * reglages.particules_dehors
            constante = reglages.constante_particules_s / souffle
            dedans.valeur = cible + (dedans.valeur - cible) * math.exp(-dt / constante)
        cible_pa = reglages.pression_10v_pa * souffle if ferme else 0.0
        if self.hepa_colmate:
            cible_pa *= reglages.facteur_hepa_colmate
        pression = self.pression.valeur or 0.0
        if dt > 0:
            pression = cible_pa + (pression - cible_pa) * math.exp(
                -dt / reglages.constante_pression_s
            )
        self.pression.valeur = pression
        if dt > 0:
            self.ozone_ppm *= 0.5 ** (dt / reglages.demi_vie_ozone_s)
            if self.generateur_alimente():
                self.ozone_ppm += reglages.montee_ozone_ppm_s * dt
        self.ozone_max_ppm = max(self.ozone_max_ppm, self.ozone_ppm)
        self._fabrique.regler(OZONE_DEDANS, min(self.ozone_ppm, self.plafond_ppm))


class SimulationNettoyage:
    """Le vrai Nettoyage, son faux store et sa fausse enceinte, à l'heure du simulateur."""

    def __init__(self, simulateur: Simulateur, hepa_colmate: bool = False) -> None:
        reglages = simulateur.reglages
        simule = reglages.simulateur.nettoyage
        if reglages.machine.nettoyage is None or simule is None:
            raise ErreurSimulation(
                "machine.yaml ou simulateur.yaml n'a pas de partie « nettoyage »"
            )
        self.simulateur = simulateur
        horloge = lambda: simulateur.temps  # noqa: E731
        fabrique = simulateur.fabrique
        # Le mode de la machine (Karulium le choisit à l'écran dans les scénarios).
        self.mode = "production"
        self.consigne = FausseConsigne()
        self.store = FauxStore(fabrique, simule, horloge)
        signal = simulateur.materiel.liste.signaux.get(OZONE_DEDANS)
        plafond = signal.ozone.plafond_ppm if signal is not None and signal.ozone else 10.0
        materiel = simulateur.materiel
        porte = (
            (lambda: bool(materiel.lire(PORTE_SPRAY)))
            if PORTE_SPRAY in materiel.branchements
            else (lambda: False)
        )
        self.enceinte = FausseEnceinte(
            fabrique, simule, self.store, self.consigne, horloge, plafond, porte, hepa_colmate
        )
        self.nettoyage = Nettoyage(
            reglages.machine.nettoyage,
            simulateur.materiel,
            mode=lambda: self.mode,
            particules_dedans=self.enceinte.particules_dedans,
            particules_dehors=self.enceinte.particules_dehors,
            pression=self.enceinte.pression,
            consigne=self.consigne,
            horloge=horloge,
        )
        self.nettoyage.ecouteurs.append(lambda message: simulateur.noter(f"Nettoyage : {message}"))
        simulateur.ajouter_fond(self.tourner, self.store.prochain_instant)

    def tourner(self) -> None:
        self.enceinte.avancer()
        self.nettoyage.observer()
        # Les sorties ont pu changer (ventilateur, générateur) : l'enceinte repart d'elles.
        self.enceinte.avancer()


def nettoyage_du_simulateur(simulateur: Simulateur, **options: Any) -> SimulationNettoyage:
    """`options` : hepa_colmate=True (la surpression n'atteint jamais le seuil de fin de purge)."""
    return SimulationNettoyage(simulateur, **options)


# ------------------------------------------------------------------ les gestes de Karulium


def _etape(
    nom: str,
    action: Callable[[], object] | None,
    texte: str,
    test: Callable[[], bool],
    delai: str,
    demande_go: bool = False,
) -> Etape:
    return Etape(
        nom,
        QUOI_FAIRE,
        action=action,
        fin=Condition(texte, test),
        delai_max=delai,
        demande_go=demande_go,
    )


def _phase(n: Nettoyage, *voulues: str) -> Callable[[], bool]:
    """La nuit est dans l'une de ces phases (alarme si elle part en erreur)."""

    def test() -> bool:
        etat = n.etat()
        if etat.nuit == ERREUR:
            raise ErreurEtape(f"nuit UV-ozone en erreur : {etat.nuit_erreur}")
        return etat.nuit in voulues

    return test


def _ouvrir(simulation: SimulationNettoyage) -> Etape:
    """Karulium demande l'ouverture (écran), puis tient « monter » : verrous libérés, store en
    haut."""
    n, store = simulation.nettoyage, simulation.store

    def ouvrir() -> None:
        n.demander_ouverture("simulateur")
        if not store.monter():
            raise ErreurEtape("store bloqué par ses verrous")

    return _etape(
        "ouvrir_le_store",
        ouvrir,
        "store vu ouvert, en haut",
        lambda: n.etat().store == OUVERT and store.hauteur >= 1.0,
        "nettoyage_store_max",
    )


def _fermer(simulation: SimulationNettoyage) -> Etape:
    """Karulium dit qu'il ferme (écran), puis tient « descendre » : le reed rebondit en bas, le
    Nettoyage attend qu'il soit stable, remet les verrous et lance la purge."""
    n, store = simulation.nettoyage, simulation.store

    def fermer() -> None:
        n.demander_fermeture("simulateur")
        store.descendre()

    return _etape(
        "fermer_le_store",
        fermer,
        "store vu fermé (reed stable), verrous remis",
        lambda: n.etat().store == FERME and not n.etat().verrous_liberes,
        "nettoyage_store_max",
    )


def _purge(simulation: SimulationNettoyage) -> Etape:
    n = simulation.nettoyage

    def finie() -> bool:
        if n.etat().purge_alerte:
            raise ErreurEtape("purge pas finie au bout du délai d'alerte")
        return not n.purge_en_cours

    return _etape(
        "purge", None, "purge finie (durée, particules, surpression)", finie, "nettoyage_purge_max"
    )


def _lancer_nuit(simulation: SimulationNettoyage) -> Etape:
    """Karulium choisit le mode UV-ozone et lance la nuit tout de suite (Go)."""
    n = simulation.nettoyage

    def lancer() -> None:
        simulation.mode = "uv_ozone"
        n.observer()
        n.programmer_nuit("simulateur", tout_de_suite=True)

    return _etape(
        "lancer_la_nuit",
        lancer,
        "générateur d'ozone en marche",
        lambda: n.commande(GENERATEUR),
        "nettoyage_store_max",
        demande_go=True,
    )


def module_fermeture_purge(simulation: SimulationNettoyage) -> Module:
    """Scénario « fermeture_purge » : store ouvert au départ ; Karulium le referme (le reed
    rebondit), la purge part au plein et finit quand ses 3 conditions sont vraies ; puis il le
    rouvre (verrous libérés)."""
    return Module(
        nom="nettoyage_purge",
        etapes=(_fermer(simulation), _purge(simulation), _ouvrir(simulation)),
    )


def module_purge_trop_longue(simulation: SimulationNettoyage) -> Module:
    """Scénario « purge_trop_longue » (HEPA colmaté : surpression trop faible) : alerte au bout
    de alerte_s, dosage toujours refusé ; Karulium passe outre (Go)."""
    n = simulation.nettoyage
    return Module(
        nom="nettoyage_purge_longue",
        etapes=(
            _fermer(simulation),
            _etape(
                "purge_en_alerte",
                None,
                "alerte « purge pas finie », dosage toujours refusé",
                lambda: n.etat().purge_alerte and n.refus_geste("dosage_semence") is not None,
                "nettoyage_purge_max",
            ),
            _etape(
                "passer_outre",
                lambda: n.passer_outre("simulateur"),
                "purge finie (passée outre)",
                lambda: not n.purge_en_cours,
                "nettoyage_store_max",
                demande_go=True,
            ),
        ),
    )


def module_nuit(simulation: SimulationNettoyage) -> Module:
    """Scénario « nuit_uv_ozone » : store refermé et purgé, mode UV-ozone, nuit lancée tout de
    suite (Go) : génération, contact, retour sous le seuil stable ; store rouvert ensuite."""
    n = simulation.nettoyage
    return Module(
        nom="nettoyage_nuit",
        etapes=(
            _fermer(simulation),
            _purge(simulation),
            _lancer_nuit(simulation),
            _etape(
                "generation",
                None,
                "générateur arrêté (t_generation)",
                _phase(n, CONTACT, RETOUR, FINI),
                "nettoyage_nuit_max",
            ),
            _etape(
                "contact",
                None,
                "fin du temps de contact",
                _phase(n, RETOUR, FINI),
                "nettoyage_nuit_max",
            ),
            _etape(
                "retour",
                None,
                "ozone dedans sous le seuil, stable",
                _phase(n, FINI),
                "nettoyage_nuit_max",
            ),
            _ouvrir(simulation),
        ),
    )


def module_fuite(simulation: SimulationNettoyage) -> Module:
    """Scénario « fuite_ozone » : la nuit part, l'ozone du dehors dépasse le seuil (événement du
    scénario) : générateur coupé, alerte forte « fuite d'ozone »."""
    n = simulation.nettoyage
    return Module(
        nom="nettoyage_fuite",
        etapes=(
            _fermer(simulation),
            _purge(simulation),
            _lancer_nuit(simulation),
            _etape(
                "generation",
                None,
                "fuite d'ozone vue, générateur coupé",
                lambda: n.etat().fuite and not n.commande(GENERATEUR),
                "nettoyage_nuit_max",
            ),
        ),
    )
