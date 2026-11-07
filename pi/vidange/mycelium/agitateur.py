"""L'agitateur du mycélium (fixe) : sa manivelle (carte n° 3), et la balance du chariot.

    agitateur = AgitateurFluidnc(reglages.machine, liaison_mycelium_lavage, balance, carte)
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

Origine de la manivelle (décision du 29/10/2026) : le capteur `origine_manivelle` voit du métal
quand la manivelle n'est PAS en haut, et rien sur ≈ 190° autour du haut. FluidNC ne sait pas
trouver le milieu d'une zone : c'est le Pi qui le fait (pas `origine`). La manivelle fait un tour
lent dans le sens +, le Pi note à chaque état de la carte l'angle du moteur et le capteur (lettre
de « Pn: », fluidnc.yaml) ; « en haut » = milieu de la zone sans métal + décalage
(`trouver_origine`). L'angle donné au Mycélium est celui du moteur moins cet angle. Il est perdu
si la carte redémarre (alarme : retour en lieu sûr, puis la prise d'origine est refaite).

La balance du plateau du chariot de remplissage est lue par une carte RP2040 sur le bus RS485
des pesées, avec la même interface que la pesée de la griffe (`CapteurForce`, en newtons) : sur
la machine, `TourPesees(...).capteur("pesee_plateau_remplissage")` (vidange.pesees) ; une fausse
pesée pour les tests (vidange.griffe.simulation.FausseForce).
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from statistics import median
from typing import Literal, Protocol

from vidange.chef import Condition, ErreurEtape
from vidange.fiabilite.constats import lancer_boucle
from vidange.fluidnc import Liaison
from vidange.griffe.bras import TOLERANCE_ARRIVEE, CapteurForce, G
from vidange.journal import donner_journal
from vidange.mycelium.regles import PoseAgitateur
from vidange.quoi_faire import pour_carte
from vidange.reglages import CarteFluidnc, Machine, OrigineManivelle

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
QUOI_FAIRE_CAPTEUR = (
    "Capteur manivelle : la prise d'origine a vu une zone sans métal de la mauvaise largeur, ou "
    "trop de bords sur un tour (capteur déréglé ou débranché, pièce desserrée, métal étranger ?). "
    "Regarder le capteur et la manivelle, corriger, puis acquitter et donner le Go : la prise "
    "d'origine est refaite."
)
QUOI_FAIRE_ORIGINE = (
    "La carte n° 3 a redémarré : la position de la manivelle est perdue. Faire le retour en lieu "
    "sûr, puis relancer le dosage du mycélium (la prise d'origine de la manivelle est refaite)."
)


def trouver_origine(echantillons: list[tuple[float, bool]], reglages: OrigineManivelle) -> float:
    """L'angle du moteur « manivelle en haut », d'après un tour lent dans le sens + :
    `echantillons` = (angle du moteur, métal vu), dans l'ordre du tour. ValueError si le capteur
    dit n'importe quoi (le message dit quoi)."""
    # Bords : (angle, vrai si on entre dans la zone sans métal), au milieu de deux lectures.
    bords = [
        ((a + b) / 2, metal_a)
        for (a, metal_a), (b, metal_b) in pairwise(echantillons)
        if metal_a != metal_b
    ]
    # Sur un tour (moins l'écart permis : le même bord, un tour plus loin, ne compte pas).
    tour = 360 - reglages.ecart_largeur_max_deg
    for i, (angle, _) in enumerate(bords):
        sur_un_tour = [bord for bord in bords[i:] if bord[0] < angle + tour]
        if len(sur_un_tour) > 2:
            raise ValueError(f"{len(sur_un_tour)} bords sur un tour (2 attendus)")
    entree = next((i for i, (_, entre) in enumerate(bords) if entre), None)
    if entree is None or entree + 1 >= len(bords):
        raise ValueError(
            "zone sans métal pas vue en entier pendant le tour (capteur débranché, ou qui voit "
            "toujours du métal ?)"
        )
    debut, fin = bords[entree][0], bords[entree + 1][0]
    largeur = fin - debut
    if abs(largeur - reglages.largeur_zone_deg) > reglages.ecart_largeur_max_deg:
        raise ValueError(
            f"zone sans métal de {largeur:.0f}° (attendu {reglages.largeur_zone_deg:g} ± "
            f"{reglages.ecart_largeur_max_deg:g}°)"
        )
    journal.info(
        "Mycélium : zone sans métal de la manivelle de %.1f° à %.1f° du moteur (largeur %.1f°)",
        debut,
        fin,
        largeur,
    )
    return (debut + fin) / 2 + reglages.decalage_deg


@dataclass(frozen=True)
class Pas:
    """Un mouvement de la manivelle, ou un geste du porte-bocal."""

    texte: str
    angle: float | None = None
    # Vitesse de la manivelle (tr/min).
    tr_min: float | None = None
    # Agitation : arrêt dès que le plateau pèse tant (kg) : poids d'avant la couche + dose.
    jusqu_a_kg: float | None = None
    # Attente après le mouvement (s), puis pesée (médiane de plusieurs lectures).
    attente_s: float = 0.0
    pesee: bool = False
    # Geste du porte-bocal (tâche 20) : demi-tour, mors.
    porte_bocal: Literal["tete_en_bas", "debout", "ouvrir", "serrer"] | None = None
    # Prise d'origine de la manivelle (tour lent).
    origine: bool = False
    # Bocal neuf de semence pris au stockage et posé sur le porte-bocal par la Préhension
    # (tâche 19 quater) : le pas dure tant que son geste dure ; la manivelle reste en bas.
    bocal_neuf: bool = False

    @property
    def bouge(self) -> bool:
        return self.angle is not None or self.origine


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

    @property
    def angle_haut_moteur(self) -> float | None:
        """L'angle du moteur (FluidNC) quand la manivelle est en haut, s'il est connu."""
        return self._zero if self.origine_connue() else None

    def origine_connue(self) -> bool: ...

    def executer(self, pas: Pas, cible: PoseAgitateur | None) -> None:
        """`cible` : None pour la prise d'origine de la manivelle."""
        ...

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
        carte: CarteFluidnc,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        """`carte` : les réglages de la carte dans fluidnc.yaml (lettre du capteur de la
        manivelle dans « Pn: »)."""
        assert machine.mycelium is not None
        if "origine_manivelle" not in carte.entrees:
            raise ValueError(
                f"fluidnc.yaml, carte « {liaison.nom} » : il manque entrees → origine_manivelle"
            )
        self._lettre_origine = carte.entrees["origine_manivelle"]
        self.reglages = machine.mycelium
        self.liaison = liaison
        self.balance = balance
        self._horloge = horloge
        self._lettre = machine.axes["manivelle"].lettre
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
        # Angle du moteur « manivelle en haut », et la carte quand il a été trouvé
        # (redémarrages, coupures) : s'ils changent, il est perdu.
        self._zero: float | None = None
        self._carte_au_zero: tuple[int, int] | None = None
        # Pendant la prise d'origine : (angle du moteur, métal vu) à chaque état de la carte.
        self._echantillons: list[tuple[float, bool]] = []
        self._rapport_echantillon = -1
        nom = f"carte « {liaison.nom} » connectée et sans alarme"
        self.pretes = Condition(nom, self._carte_prete)
        self.surveillance = Condition(nom, self._surveiller)

    # ------------------------------------------------------------ balance en fond

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        return lancer_boucle(
            "balance_mycelium", 1 / self.reglages.pesee.frequence_hz, self._en_fond, arret
        )

    def _en_fond(self) -> None:
        self._echantillonner()
        self.lire_balance()

    def _echantillonner(self) -> None:
        """Pendant la prise d'origine : note l'angle et le capteur de chaque nouvel état."""
        pas = self._pas
        if pas is None or not pas.origine or self._fin_mouvement is not None:
            return
        etat = self.liaison.etat
        angle = etat.positions.get(self._lettre)
        if etat.rapports_recus == self._rapport_echantillon or angle is None:
            return
        self._rapport_echantillon = etat.rapports_recus
        with self._verrou:
            self._echantillons.append((angle, self._lettre_origine in etat.entrees_actives))

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

    def _lire(self) -> float:
        try:
            return self.liaison.etat.positions[self._lettre]
        except KeyError as manque:
            raise ErreurEtape(
                f"position de l'axe {manque} inconnue (carte pas encore lue)"
            ) from None

    @property
    def angle_haut_moteur(self) -> float | None:
        """L'angle du moteur (FluidNC) quand la manivelle est en haut, s'il est connu."""
        return self._zero if self.origine_connue() else None

    def origine_connue(self) -> bool:
        etat = self.liaison.etat
        if self._carte_au_zero != (etat.redemarrages, etat.coupures):
            self._zero = None
        return self._zero is not None

    def position(self) -> PoseAgitateur:
        """Où est la manivelle ; l'angle compte depuis « manivelle en haut »."""
        angle = self._lire()
        if not self.origine_connue():
            raise ErreurEtape(
                "origine de la manivelle pas faite, ou perdue (la carte a redémarré)",
                QUOI_FAIRE_ORIGINE,
            )
        assert self._zero is not None
        return PoseAgitateur(angle=angle - self._zero)

    def executer(self, pas: Pas, cible: PoseAgitateur | None) -> None:
        if pas.origine:
            # Tour lent dans le sens +, assez long pour voir toute la zone sans métal.
            origine = self.reglages.manivelle.origine
            positions = {self._lettre: self._lire() + origine.balayage_deg()}
            with self._verrou:
                self._echantillons = []
            self._partir(pas, positions, origine.vitesse_deg_s * 60)
            return
        assert cible is not None
        assert self._zero is not None
        positions = {self._lettre: cible.angle + self._zero}
        # F : la vitesse de la manivelle, en °/min.
        f = (pas.tr_min or self.reglages.vitesses.placement_tr_min) * 360
        self._partir(pas, positions, f)

    def _partir(self, pas: Pas, positions: dict[str, float], f: float) -> None:
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
                if pas.origine:
                    self._prendre_origine(etat.redemarrages, etat.coupures)
                self._fin_mouvement = self._horloge()
            return self._horloge() - self._fin_mouvement >= pas.attente_s

    def _prendre_origine(self, redemarrages: int, coupures: int) -> None:
        """Fin du tour lent : « en haut » d'après le capteur (appelé sous le verrou)."""
        try:
            zero = trouver_origine(self._echantillons, self.reglages.manivelle.origine)
        except ValueError as erreur:
            raise ErreurEtape(f"capteur manivelle : {erreur}", QUOI_FAIRE_CAPTEUR) from None
        journal.info("Mycélium : manivelle en haut à %.1f° du moteur", zero)
        self._zero, self._carte_au_zero = zero, (redemarrages, coupures)

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
