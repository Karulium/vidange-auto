"""L'agitateur du mycélium : glissière et manivelle (carte n° 3), et la balance du chariot.

    agitateur = AgitateurFluidnc(reglages.machine, liaison_mycelium_lavage, balance)
    agitateur.demarrer(arret)        # lit la balance 80 fois par seconde, en fond
    agitateur.executer(pas, cible)   # envoie un pas (sans attendre)
    agitateur.fini()                 # vrai quand le pas est fini ; ErreurEtape s'il a échoué
    agitateur.resultat()             # où il s'est arrêté, dose atteinte ou pas, poids lu

Chaque pas est un déplacement manuel de FluidNC (« $J= ») vers une position absolue : il est
rejouable, et on peut l'arrêter tout de suite sans perdre la position (0x85). C'est ce que fait le
fil de la balance pendant une agitation (`jusqu_a_kg`) :
- dose atteinte (le plateau pèse `jusqu_a_kg`) → arrêt de la manivelle ;
- saut brutal du poids (bocal ou couvercle cassé, bocal tombé) → arrêt, alarme ;
- balance muette → arrêt, alarme (jamais d'agitation « à l'aveugle » : le seau déborderait).

La balance du plateau du chariot de remplissage est lue par une carte RP2040 sur le bus RS485
des pesées (tâche 22 bis) : ici, la même interface que la pesée de la griffe (`CapteurForce`, en
newtons), et une fausse pesée pour les tests (vidange.griffe.simulation.FausseForce).
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from statistics import median
from typing import Literal, Protocol

from vidange.chef import Condition, ErreurEtape
from vidange.fiabilite.constats import lancer_boucle
from vidange.fluidnc import Liaison
from vidange.griffe.bras import MM_PAR_M, TOLERANCE_ARRIVEE, CapteurForce, G
from vidange.journal import donner_journal
from vidange.mycelium.regles import PoseAgitateur
from vidange.quoi_faire import pour_carte
from vidange.reglages import Machine

journal = donner_journal("mycelium.agitateur")

QUOI_FAIRE_SAUT = (
    "Le poids du seau a sauté pendant l'agitation : bocal ou couvercle cassé, bocal tombé ? La "
    "manivelle s'est arrêtée. Regarder la photo et la vidéo du dosage (page web), retirer le verre "
    "et le seau s'il le faut (il est marqué « pas bon » dans le registre), remettre un bocal, puis "
    "acquitter et donner le Go."
)
QUOI_FAIRE_BALANCE = (
    "La balance du chariot de remplissage ne répond plus : l'agitation s'est arrêtée (elle ne se "
    "fait jamais sans la balance). Vérifier le câble du bus des pesées et la carte du plateau, "
    "puis acquitter et donner le Go."
)


@dataclass(frozen=True)
class Pas:
    """Un mouvement de l'agitateur (seuls les axes cités bougent), ou un geste du porte-bocal."""

    texte: str
    x: float | None = None
    angle: float | None = None
    # Vitesse de la manivelle (tr/min) ; la glissière va à sa vitesse (machine.yaml).
    tr_min: float | None = None
    # Agitation : arrêt dès que le plateau pèse tant (kg) : poids d'avant la couche + dose.
    jusqu_a_kg: float | None = None
    # Attente après le mouvement (s), puis pesée (médiane de plusieurs lectures).
    attente_s: float = 0.0
    pesee: bool = False
    # Geste du porte-bocal (tâche 20), fait au demi-tour.
    porte_bocal: Literal["tete_en_bas", "debout"] | None = None

    @property
    def bouge(self) -> bool:
        return self.x is not None or self.angle is not None


@dataclass(frozen=True)
class Resultat:
    pose: PoseAgitateur
    # L'agitation a été arrêtée par la balance (dose atteinte).
    arrete: bool = False
    # Poids lu sur le plateau (kg), si le pas demandait une pesée.
    poids_kg: float | None = None


class Agitateur(Protocol):
    pretes: Condition
    surveillance: Condition

    def position(self) -> PoseAgitateur: ...

    def executer(self, pas: Pas, cible: PoseAgitateur) -> None: ...

    def fini(self) -> bool: ...

    def resultat(self) -> Resultat: ...

    def pauser(self) -> None: ...

    def reprendre(self) -> None: ...

    def arreter(self) -> None: ...

    @property
    def saut(self) -> bool: ...

    def oublier_saut(self) -> None: ...


class AgitateurFluidnc:
    def __init__(
        self,
        machine: Machine,
        liaison: Liaison,
        balance: CapteurForce,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        assert machine.mycelium is not None
        self.reglages = machine.mycelium
        self.liaison = liaison
        self.balance = balance
        self._horloge = horloge
        self._lettres = {nom: machine.axes[nom].lettre for nom in ("agitateur_x", "manivelle")}
        self._verrou = threading.Lock()
        # Lectures récentes de la balance : (heure, kg).
        self._lectures: deque[tuple[float, float]] = deque(maxlen=400)
        self._derniere_lecture: float | None = None
        self._pas: Pas | None = None
        self._cible: dict[str, float] = {}
        self._f = 0.0
        self._rapports_a_l_envoi = 0
        self._fin_mouvement: float | None = None
        self._arrete = False
        self._saut = False
        self._muette = False
        self._en_pause = False
        nom = f"carte « {liaison.nom} » connectée et sans alarme"
        self.pretes = Condition(nom, self._carte_prete)
        self.surveillance = Condition(nom, self._surveiller)

    # ------------------------------------------------------------ balance en fond

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        return lancer_boucle(
            "balance_mycelium", 1 / self.reglages.pesee.frequence_hz, self.lire_balance, arret
        )

    def lire_balance(self) -> None:
        """Une lecture de la balance ; arrête l'agitation s'il le faut."""
        maintenant = self._horloge()
        pesee = self.reglages.pesee
        try:
            kg = self.balance.lire_n() / G
        except Exception as erreur:
            with self._verrou:
                silence = maintenant - (self._derniere_lecture or maintenant)
                if self._agite() and silence >= pesee.silence_max_s and not self._muette:
                    self._muette = True
                    self._annuler(f"balance du chariot muette ({erreur})")
            return
        with self._verrou:
            self._derniere_lecture = maintenant
            self._lectures.append((maintenant, kg))
            if not self._agite() or self._arrete or self._saut:
                return
            n = pesee.lectures_saut
            recentes = [poids for _, poids in list(self._lectures)[-2 * n :]]
            if len(recentes) == 2 * n:
                ecart = median(recentes[n:]) - median(recentes[:n])
                if abs(ecart) >= pesee.saut_kg:
                    self._saut = True
                    self._annuler(f"saut de poids de {ecart:+.2f} kg pendant l'agitation")
                    return
            pas = self._pas
            assert pas is not None and pas.jusqu_a_kg is not None
            poids = median(recentes[-n:])
            if poids >= pas.jusqu_a_kg:
                self._arrete = True
                self._annuler(f"dose atteinte (plateau à {poids:.3f} kg)")

    def _agite(self) -> bool:
        pas = self._pas
        return pas is not None and pas.jusqu_a_kg is not None and self._fin_mouvement is None

    def _annuler(self, pourquoi: str) -> None:
        journal.info("Mycélium : arrêt de la manivelle, %s", pourquoi)
        self.liaison.annuler_deplacement()

    def _poids_recent(self, combien: int) -> float | None:
        if not self._lectures:
            return None
        return median(kg for _, kg in list(self._lectures)[-combien:])

    # ------------------------------------------------------------ mouvements

    def _facteur(self, nom: str) -> float:
        return MM_PAR_M if nom == "agitateur_x" else 1

    def position(self) -> PoseAgitateur:
        positions = self.liaison.etat.positions
        try:
            x, angle = (positions[self._lettres[nom]] for nom in ("agitateur_x", "manivelle"))
        except KeyError as manque:
            raise ErreurEtape(
                f"position de l'axe {manque} inconnue (carte pas encore lue)"
            ) from None
        return PoseAgitateur(x=x / MM_PAR_M, angle=angle)

    def executer(self, pas: Pas, cible: PoseAgitateur) -> None:
        depart = self.position()
        positions = {}
        if pas.x is not None:
            positions[self._lettres["agitateur_x"]] = cible.x * MM_PAR_M
        if pas.angle is not None:
            positions[self._lettres["manivelle"]] = cible.angle
        # Un seul axe bouge à la fois : F est sa vitesse (mm/min, ou °/min pour la manivelle).
        if pas.angle is not None and abs(cible.angle - depart.angle) > TOLERANCE_ARRIVEE:
            f = (pas.tr_min or self.reglages.vitesses.placement_tr_min) * 360
        else:
            f = self.reglages.vitesses.glissiere_m_s * 60 * MM_PAR_M
        with self._verrou:
            self._pas, self._arrete, self._saut, self._muette = pas, False, False, False
            self._cible, self._f = positions, f
            self._fin_mouvement = None
            sans_lecture = not self._lectures
            self._rapports_a_l_envoi = self.liaison.etat.rapports_recus
        if pas.jusqu_a_kg is not None and sans_lecture:
            raise ErreurEtape(
                "balance du chariot sans lecture : pas d'agitation", QUOI_FAIRE_BALANCE
            )
        commande = self.liaison.deplacer_manuel(positions, f)
        if commande.erreur is not None:
            raise ErreurEtape(f"agitateur, « {commande.ligne} » : {commande.erreur}")

    def fini(self) -> bool:
        self._surveiller()
        with self._verrou:
            if self._saut:
                raise ErreurEtape("saut de poids pendant l'agitation", QUOI_FAIRE_SAUT)
            if self._muette:
                raise ErreurEtape(
                    "balance du chariot muette pendant l'agitation", QUOI_FAIRE_BALANCE
                )
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
                    raise ErreurEtape(f"agitateur arrêté avant la fin de « {pas.texte} »")
                self._fin_mouvement = self._horloge()
            return self._horloge() - self._fin_mouvement >= pas.attente_s

    def _arrive(self, positions: dict[str, float]) -> bool:
        return all(
            abs(positions.get(lettre, float("inf")) - valeur) <= TOLERANCE_ARRIVEE
            for lettre, valeur in self._cible.items()
        )

    def resultat(self) -> Resultat:
        pose = self.position()
        with self._verrou:
            pas = self._pas
            poids = None
            if pas is not None and pas.pesee:
                poids = self._poids_recent(self.reglages.pesee.lectures_pesee)
            return Resultat(pose=pose, arrete=self._arrete, poids_kg=poids)

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
    def saut(self) -> bool:
        return self._saut

    def oublier_saut(self) -> None:
        with self._verrou:
            self._saut = False

    def pauser(self) -> None:
        """Pause de Karulium : le déplacement s'arrête ; il sera renvoyé à la reprise (une
        agitation repart, et s'arrête toujours au même poids)."""
        with self._verrou:
            self._en_pause = True
        self.liaison.annuler_deplacement()

    def reprendre(self) -> None:
        with self._verrou:
            self._en_pause = False
            pas, cible, f = self._pas, dict(self._cible), self._f
            self._rapports_a_l_envoi = self.liaison.etat.rapports_recus
        if pas is not None and self._fin_mouvement is None and not self._arrete:
            self.liaison.deplacer_manuel(cible, f)

    def arreter(self) -> None:
        with self._verrou:
            self._pas = None
        self.liaison.annuler_deplacement()
