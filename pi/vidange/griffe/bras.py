"""Le bras de la griffe : 5 axes de la carte du portique et la pesée de la griffe.

    bras = BrasFluidnc(reglages.machine, liaison_portique, capteur_force)
    bras.demarrer(arret)        # lit la pesée 80 fois par seconde, en fond
    bras.executer(pas, cible)   # envoie un pas (sans attendre)
    bras.fini()                 # vrai quand le pas est fini ; ErreurEtape s'il a échoué
    bras.resultat()             # où il s'est arrêté, contact ou pas, charge pesée

Chaque pas est un déplacement manuel de FluidNC (« $J= ») vers une position absolue : il est
rejouable, et on peut l'arrêter tout de suite sans perdre la position (0x85, le « feed hold »
des déplacements manuels). C'est ce que fait le fil de la pesée :
- descente au contact (`arret_si_baisse_n`) : la charge pendue baisse → arrêt immédiat ;
- trajet (`choc`) : force inattendue → arrêt immédiat de Z et du pont, alarme ; quand l'étape
  est refaite (après le Go), la griffe remonte d'abord lentement.
Pesée muette pendant une descente ou un trajet : arrêt aussi (jamais de descente « à l'aveugle »).

La pesée de la griffe est lue par une carte RP2040 sur le bus RS485 des pesées : sur la
machine, `TourPesees(...).capteur("pesee_griffe")` (vidange.pesees) ; une fausse pesée pour les
tests (vidange.griffe.simulation.FausseForce).
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from statistics import median
from typing import Protocol

from vidange.chef import Condition, ErreurEtape
from vidange.fiabilite.constats import lancer_boucle
from vidange.fluidnc import Liaison
from vidange.griffe.regles import Pose
from vidange.journal import donner_journal
from vidange.quoi_faire import pour_carte
from vidange.reglages import Machine

journal = donner_journal("griffe.bras")

# Accélération de la pesanteur (m/s²), pour passer des newtons aux kilogrammes.
G = 9.81
MM_PAR_M = 1000
# Écart (mm ou °) sous lequel un axe arrêté est arrivé à sa cible.
TOLERANCE_ARRIVEE = 0.05

QUOI_FAIRE_CHOC = (
    "La griffe a senti un choc pendant un trajet et s'est arrêtée. Regarder la vidéo et la photo "
    "(page web) : qu'a-t-elle touché ? Dégager, vérifier le godet et le mât, puis acquitter et "
    "donner le Go : la griffe remontera d'abord lentement."
)
QUOI_FAIRE_PESEE = (
    "La pesée de la griffe ne répond plus : la griffe s'est arrêtée (elle ne descend jamais sans "
    "sa pesée). Vérifier le câble du bus des pesées et la carte de la griffe, puis acquitter et "
    "donner le Go."
)


class CapteurForce(Protocol):
    """La pesée de la griffe : charge pendue au mât, en newtons."""

    def lire_n(self) -> float:
        """Lève une exception si la pesée ne répond pas."""
        ...


@dataclass(frozen=True)
class Pas:
    """Un mouvement de la tête, vers une pose (seuls les axes cités bougent)."""

    texte: str
    cibles: dict[str, float] = field(default_factory=dict)
    # Vitesse lente de l'axe Z (nom dans machine.yaml → griffe → vitesses), sinon la plus rapide.
    vitesse: str | None = None
    # Vitesse de la vis à billes du godet (m/s), sinon la plus rapide (versement dans un bocal).
    vitesse_b: float | None = None
    # Arrêt dès que la charge baisse de tant (N) : contact, appui, force limitée.
    arret_si_baisse_n: float | None = None
    # Descente vers la surface du substrat (pour le simulateur : sinon, une poussée).
    contact: bool = False
    # Surveiller les chocs pendant le mouvement (trajets).
    choc: bool = False
    # Attente après le mouvement (s), puis pesée (médiane de plusieurs lectures).
    attente_s: float = 0.0
    pesee: bool = False


@dataclass(frozen=True)
class Resultat:
    pose: Pose
    # Le mouvement a été arrêté par la pesée (contact, appui).
    arrete: bool = False
    # Charge pendue (N), si le pas demandait une pesée.
    charge_n: float | None = None


class Bras(Protocol):
    pretes: Condition
    surveillance: Condition

    def position(self) -> Pose: ...

    def moyenne_n(self, duree_s: float) -> float: ...

    def executer(self, pas: Pas, cible: Pose) -> None: ...

    def enchainer(self, poses: list[Pose], vitesse: str | None) -> None: ...

    def fini(self) -> bool: ...

    def resultat(self) -> Resultat: ...

    def pauser(self) -> None: ...

    def reprendre(self) -> None: ...

    def arreter(self) -> None: ...

    @property
    def choc(self) -> bool: ...

    def oublier_choc(self) -> None: ...


class Conversion:
    """Pose de la griffe ↔ positions des axes de machine.yaml."""

    def __init__(self, machine: Machine) -> None:
        assert machine.griffe is not None
        self.griffe = machine.griffe
        self.axes = {nom: machine.axes[nom] for nom in ("pont_x", "chariot_y", "griffe_z")}
        self.axes.update(griffe_a=machine.axes["griffe_a"], griffe_b=machine.axes["griffe_b"])
        self.godet = machine.axes["griffe_b"].course

    def vers_axes(self, pose: Pose) -> dict[str, float]:
        """Nom d'axe → valeur (m ou °)."""
        ferme, ouvert = self.godet
        return {
            "pont_x": pose.x - self.griffe.decalage_mat_x,
            "chariot_y": pose.y,
            "griffe_z": pose.z,
            "griffe_a": pose.a,
            "griffe_b": ferme + pose.b * (ouvert - ferme),
        }

    def depuis_axes(self, valeurs: dict[str, float]) -> Pose:
        ferme, ouvert = self.godet
        return Pose(
            x=valeurs["pont_x"] + self.griffe.decalage_mat_x,
            y=valeurs["chariot_y"],
            z=valeurs["griffe_z"],
            a=valeurs["griffe_a"],
            b=(valeurs["griffe_b"] - ferme) / (ouvert - ferme),
        )

    def vitesses(self, vitesse: str | None, vitesse_b: float | None = None) -> dict[str, float]:
        """Vitesse maximale de chaque axe (m/s ou °/s) pour un pas."""
        v = self.griffe.vitesses
        vitesses = {
            "pont_x": v.pont_x,
            "chariot_y": v.chariot_y,
            "griffe_z": v.griffe_z,
            "griffe_a": v.griffe_a,
            "griffe_b": v.griffe_b,
        }
        if vitesse is not None:
            vitesses["griffe_z"] = min(v.griffe_z, getattr(v, vitesse))
        if vitesse_b is not None:
            vitesses["griffe_b"] = min(v.griffe_b, vitesse_b)
        return vitesses

    def facteur(self, nom: str) -> float:
        """machine.yaml → FluidNC : mètres → mm ; degrés tels quels."""
        return MM_PAR_M if self.axes[nom].unite == "m" else 1


class BrasFluidnc:
    def __init__(
        self,
        machine: Machine,
        liaison: Liaison,
        capteur: CapteurForce,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        assert machine.griffe is not None
        self.conversion = Conversion(machine)
        self.reglages = machine.griffe
        self.liaison = liaison
        self.capteur = capteur
        self._horloge = horloge
        self._verrou = threading.Lock()
        self._lettres = {nom: axe.lettre for nom, axe in self.conversion.axes.items()}
        # Lectures récentes de la pesée : (heure, newtons).
        self._lectures: deque[tuple[float, float]] = deque(maxlen=400)
        self._derniere_lecture: float | None = None
        self._pas: Pas | None = None
        self._cible: dict[str, float] = {}
        self._f = 0.0
        self._rapports_a_l_envoi = 0
        self._fin_mouvement: float | None = None
        self._reference_n: float | None = None
        self._arrete = False
        self._choc = False
        self._muette = False
        self._en_pause = False
        nom = f"carte « {liaison.nom} » connectée et sans alarme"
        self.pretes = Condition(nom, self._carte_prete)
        self.surveillance = Condition(nom, self._surveiller)

    # ------------------------------------------------------------ pesée en fond

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        return lancer_boucle(
            "pesee_griffe", 1 / self.reglages.force.frequence_hz, self.lire_force, arret
        )

    def lire_force(self) -> None:
        """Une lecture de la pesée ; arrête la descente ou le trajet s'il le faut."""
        maintenant = self._horloge()
        try:
            charge = self.capteur.lire_n()
        except Exception as erreur:
            with self._verrou:
                surveille = self._surveille()
                silence = maintenant - (self._derniere_lecture or maintenant)
                if surveille and silence >= self.reglages.force.silence_max_s and not self._muette:
                    self._muette = True
                    self._annuler(f"pesée de la griffe muette ({erreur})")
            return
        with self._verrou:
            self._derniere_lecture = maintenant
            self._lectures.append((maintenant, charge))
            pas, reference = self._pas, self._reference_n
            if pas is None or reference is None or self._arrete or self._fin_mouvement is not None:
                return
            if pas.arret_si_baisse_n is not None and reference - charge >= pas.arret_si_baisse_n:
                self._arrete = True
                self._annuler(f"{pas.texte} : la charge a baissé de {reference - charge:.0f} N")
            elif pas.choc and abs(charge - reference) >= self.reglages.force.choc_n:
                self._choc = True
                self._annuler(f"choc pendant « {pas.texte} » ({charge - reference:+.0f} N)")

    def _surveille(self) -> bool:
        pas = self._pas
        return (
            pas is not None
            and (pas.arret_si_baisse_n is not None or pas.choc)
            and self._fin_mouvement is None
        )

    def _annuler(self, pourquoi: str) -> None:
        journal.info("Griffe : arrêt, %s", pourquoi)
        self.liaison.annuler_deplacement()

    def moyenne_n(self, duree_s: float) -> float:
        """Moyenne des lectures de la pesée des `duree_s` dernières secondes (pesée à l'arrêt du
        versement dans un bocal)."""
        maintenant = self._horloge()
        with self._verrou:
            lectures = [charge for quand, charge in self._lectures if maintenant - quand <= duree_s]
        if not lectures:
            raise ErreurEtape("pesée de la griffe sans lecture", QUOI_FAIRE_PESEE)
        return sum(lectures) / len(lectures)

    def _charge_recente(self, combien: int) -> float | None:
        if not self._lectures:
            return None
        return median(charge for _, charge in list(self._lectures)[-combien:])

    # ------------------------------------------------------------ mouvements

    def position(self) -> Pose:
        positions = self.liaison.etat.positions
        try:
            valeurs = {
                nom: positions[lettre] / self.conversion.facteur(nom)
                for nom, lettre in self._lettres.items()
            }
        except KeyError as manque:
            raise ErreurEtape(
                f"position de l'axe {manque} inconnue (carte pas encore lue)"
            ) from None
        return self.conversion.depuis_axes(valeurs)

    def _ligne(
        self,
        depart: dict[str, float],
        cible: Pose,
        vitesse: str | None,
        vitesse_b: float | None = None,
    ) -> dict:
        """Positions (mm ou °) par lettre, et vitesse F de FluidNC pour aller à la cible."""
        valeurs = self.conversion.vers_axes(cible)
        vitesses = self.conversion.vitesses(vitesse, vitesse_b)
        duree = max(
            (abs(valeurs[nom] - depart[nom]) / vitesses[nom] for nom in valeurs), default=0.0
        )
        mm = {nom: valeurs[nom] * self.conversion.facteur(nom) for nom in valeurs}
        longueur = math.sqrt(
            sum((mm[nom] - depart[nom] * self.conversion.facteur(nom)) ** 2 for nom in mm)
        )
        f = 60 * longueur / duree if duree > 0 else 60 * vitesses["griffe_z"] * MM_PAR_M
        return {"positions": {self._lettres[nom]: mm[nom] for nom in mm}, "f": max(f, 1.0)}

    def executer(self, pas: Pas, cible: Pose) -> None:
        depart = self.conversion.vers_axes(self.position())
        ligne = self._ligne(depart, cible, pas.vitesse, pas.vitesse_b)
        with self._verrou:
            self._pas, self._arrete, self._muette = pas, False, False
            self._cible, self._f = ligne["positions"], ligne["f"]
            self._fin_mouvement = None
            self._reference_n = self._charge_recente(8)
            self._rapports_a_l_envoi = self.liaison.etat.rapports_recus
        if (pas.arret_si_baisse_n is not None or pas.choc) and self._reference_n is None:
            raise ErreurEtape("pesée de la griffe sans lecture : pas de descente", QUOI_FAIRE_PESEE)
        commande = self.liaison.deplacer_manuel(ligne["positions"], ligne["f"])
        if commande.erreur is not None:
            raise ErreurEtape(f"griffe, « {commande.ligne} » : {commande.erreur}")

    def enchainer(self, poses: list[Pose], vitesse: str | None) -> None:
        """Plusieurs déplacements à la suite, envoyés d'un coup (retrait d'urgence)."""
        depart = self.conversion.vers_axes(self.position())
        for pose in poses:
            ligne = self._ligne(depart, pose, vitesse)
            self.liaison.deplacer_manuel(ligne["positions"], ligne["f"])
            depart = self.conversion.vers_axes(pose)
        with self._verrou:
            self._pas = None

    def fini(self) -> bool:
        self._surveiller()
        with self._verrou:
            if self._choc:
                raise ErreurEtape("choc pendant un trajet de la griffe", QUOI_FAIRE_CHOC)
            if self._muette:
                raise ErreurEtape("pesée de la griffe muette pendant un geste", QUOI_FAIRE_PESEE)
            pas = self._pas
            if pas is None:
                return True
            etat = self.liaison.etat
            if self._en_pause or not etat.au_repos:
                return False
            if etat.rapports_recus <= self._rapports_a_l_envoi + 1:
                return False
            if self._fin_mouvement is None:
                if not self._arrete and not self._arrive(etat.positions):
                    # Arrêtée avant la cible sans contact : déplacement annulé par la carte.
                    raise ErreurEtape(f"griffe arrêtée avant la fin de « {pas.texte} »")
                self._fin_mouvement = self._horloge()
            return self._horloge() - self._fin_mouvement >= pas.attente_s

    def _arrive(self, positions: dict[str, float]) -> bool:
        return all(
            abs(positions.get(lettre, math.inf) - valeur) <= TOLERANCE_ARRIVEE
            for lettre, valeur in self._cible.items()
        )

    def resultat(self) -> Resultat:
        pose = self.position()
        with self._verrou:
            pas = self._pas
            charge = None
            if pas is not None and pas.pesee:
                charge = self._charge_recente(self.reglages.force.lectures_pesee)
            return Resultat(pose=pose, arrete=self._arrete, charge_n=charge)

    def _carte_prete(self) -> bool:
        etat = self.liaison.etat
        return etat.connectee and etat.etat is not None and not etat.en_alarme

    def _surveiller(self) -> bool:
        probleme = pour_carte(self.liaison.etat)
        if probleme is not None:
            texte, quoi_faire = probleme
            raise ErreurEtape(f"carte « {self.liaison.nom} » : {texte}", quoi_faire)
        return True

    @property
    def choc(self) -> bool:
        return self._choc

    def oublier_choc(self) -> None:
        with self._verrou:
            self._choc = False

    def pauser(self) -> None:
        """Pause de Karulium : le déplacement s'arrête ; il sera renvoyé à la reprise."""
        with self._verrou:
            self._en_pause = True
        self.liaison.annuler_deplacement()

    def reprendre(self) -> None:
        with self._verrou:
            self._en_pause = False
            pas, cible, f = self._pas, dict(self._cible), self._f
            self._rapports_a_l_envoi = self.liaison.etat.rapports_recus
        if pas is not None and self._fin_mouvement is None and not self._arrete:
            # La même cible (positions absolues) : le pas repart d'où il s'est arrêté.
            self.liaison.deplacer_manuel(cible, f)

    def arreter(self) -> None:
        with self._verrou:
            self._pas = None
        self.liaison.annuler_deplacement()
