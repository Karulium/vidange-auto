"""Le chariot de remplissage sur sa carte (n° 2, « chariot ») : avance, plateau, rotation, barres,
pousseur ; sa balance (carte de pesée RS485) et sa barrière lumineuse.

    chariot = ChariotFluidnc(reglages.machine, liaison_chariot, balance, signaux)
    chariot.demarrer(arret)        # lit la balance en fond
    chariot.executer(pas, cible)   # envoie un pas (sans attendre)
    chariot.fini()                 # vrai quand le pas est fini ; ErreurEtape s'il a échoué
    chariot.resultat()             # où il s'est arrêté, contact, poids lu

Chaque pas est un déplacement manuel de FluidNC (« $J= ») vers une position absolue : il est
rejouable, et on peut l'arrêter tout de suite sans perdre la position (0x85). Les axes cités
bougent ensemble, en ligne droite.
- Barres : la carte compte 0 à l'origine côté mur ; le Pi ajoute `barres → origine_hw_m`
  (position de la carte en mm = (hw − origine) × 1000).
- Centrage (`courant_reduit`) : la sortie « courant_reduit_barres » est commandée pendant le pas.
- Contact du plateau (`contact_kg`) : le plateau monte lentement ; dès que la balance a gagné
  tant de kg, le fil de la balance arrête le mouvement (0x85).
La balance est lue `pesee → frequence_hz` fois par seconde : une pesée est la médiane des
dernières lectures, plateau arrêté depuis `attente_s`.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from statistics import median
from typing import Literal, Protocol

from vidange.chef import Condition, ErreurEtape
from vidange.fiabilite.constats import lancer_boucle
from vidange.fluidnc import Liaison
from vidange.griffe.bras import MM_PAR_M, TOLERANCE_ARRIVEE, CapteurForce, G
from vidange.journal import donner_journal
from vidange.porte_bocal.signaux import Signaux, SignauxFluidnc
from vidange.quoi_faire import pour_carte
from vidange.reglages import CarteFluidnc, Machine
from vidange.remplissage.regles import AXES, Pose

journal = donner_journal("remplissage.chariot")

# Noms des signaux (docs/entrees-sorties.yaml, fluidnc.yaml).
BARRIERE = "barriere_remplissage"
COURANT_REDUIT = "courant_reduit_barres"
# Vitesse nommée d'un pas → l'axe qu'elle ralentit.
VITESSES_LENTES = {"centrage": "barres", "contact": "z"}

QUOI_FAIRE_BALANCE = (
    "La balance du plateau du chariot de remplissage ne répond plus. Vérifier le câble du bus des "
    "pesées et la carte du plateau, puis acquitter et donner le Go."
)


@dataclass(frozen=True)
class Pas:
    """Un mouvement du chariot (seuls les axes cités bougent), ou une attente (pesée)."""

    texte: str
    cibles: dict[str, float] = field(default_factory=dict)
    # Vitesse lente (« centrage » : barres, « contact » : plateau), sinon celle de chaque axe.
    vitesse: Literal["centrage", "contact"] | None = None
    # Barres au courant réduit pendant le pas (centrage).
    courant_reduit: bool = False
    # Le plateau monte jusqu'à ce que la balance gagne tant de kg (contact du fond d'un seau).
    contact_kg: float | None = None
    # Le plateau monte pour le dosage du mycélium (verrou : bocal au-dessus).
    dosage: bool = False
    # Attente après le mouvement (s), puis pesée (médiane des dernières lectures).
    attente_s: float = 0.0
    pesee: bool = False


@dataclass(frozen=True)
class Resultat:
    pose: Pose
    # Le plateau s'est arrêté au contact (balance).
    contact: bool = False
    # Poids lu sur le plateau (kg), si le pas demandait une pesée.
    poids_kg: float | None = None


class Chariot(Protocol):
    pretes: Condition
    surveillance: Condition

    def position(self) -> Pose: ...

    def executer(self, pas: Pas, cible: Pose) -> None: ...

    def fini(self) -> bool: ...

    def resultat(self) -> Resultat: ...

    def barriere_coupee(self) -> bool | None:
        """Faisceau de la barrière lumineuse coupé ; None : pas lu."""
        ...

    def pauser(self) -> None: ...

    def reprendre(self) -> None: ...

    def arreter(self) -> None: ...


def signaux_chariot(liaison: Liaison, carte: CarteFluidnc) -> SignauxFluidnc:
    return SignauxFluidnc(liaison, carte, entrees=(BARRIERE,), sorties=(COURANT_REDUIT,))


class ChariotFluidnc:
    def __init__(
        self,
        machine: Machine,
        liaison: Liaison,
        balance: CapteurForce,
        signaux: Signaux,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        assert machine.remplissage is not None
        self.reglages = machine.remplissage
        self.liaison = liaison
        self.balance = balance
        self.signaux = signaux
        self._horloge = horloge
        self._lettres = {cle: machine.axes[nom].lettre for cle, nom in AXES.items()}
        v = self.reglages.vitesses
        # Vitesse de chaque axe (m/s, °/s).
        self._vitesses = {
            "y": v.y,
            "z": v.plateau,
            "a": v.rotation,
            "barres": v.barres,
            "pousseur": v.pousseur,
        }
        self._verrou = threading.Lock()
        # Lectures récentes de la balance : (heure, kg).
        self._lectures: deque[tuple[float, float]] = deque(maxlen=200)
        self._derniere_lecture: float | None = None
        self._pas: Pas | None = None
        self._cible: dict[str, float] = {}
        self._f = 0.0
        self._rapports_a_l_envoi = 0
        self._fin_mouvement: float | None = None
        self._contact = False
        self._contact_depuis_kg: float | None = None
        self._en_pause = False
        nom = f"carte « {liaison.nom} » connectée et sans alarme"
        self.pretes = Condition(nom, self._carte_prete)
        self.surveillance = Condition(nom, self._surveiller)

    # ------------------------------------------------------------ balance en fond

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        return lancer_boucle(
            "balance_remplissage", 1 / self.reglages.pesee.frequence_hz, self.lire_balance, arret
        )

    def lire_balance(self) -> None:
        """Une lecture de la balance ; arrête la montée au contact s'il le faut."""
        try:
            kg = self.balance.lire_n() / G
        except Exception:
            return
        maintenant = self._horloge()
        with self._verrou:
            self._derniere_lecture = maintenant
            self._lectures.append((maintenant, kg))
            pas, depart = self._pas, self._contact_depuis_kg
            if pas is None or pas.contact_kg is None or depart is None or self._contact:
                return
            if self._fin_mouvement is not None:
                return
            if kg >= depart + pas.contact_kg:
                self._contact = True
        if self._contact:
            journal.info("Remplissage : contact du plateau (%.2f kg, départ %.2f kg)", kg, depart)
            self.liaison.annuler_deplacement()

    def peser(self) -> float:
        """Poids sur le plateau (kg) : médiane des dernières lectures."""
        with self._verrou:
            lectures = [kg for _, kg in self._lectures][-self.reglages.pesee.lectures :]
            recente = self._derniere_lecture
        silence = None if recente is None else self._horloge() - recente
        if not lectures or silence is None or silence > 1:
            raise ErreurEtape("balance du plateau sans lecture", QUOI_FAIRE_BALANCE)
        return median(lectures)

    # ------------------------------------------------------------ positions

    def _vers_carte(self, cle: str, valeur: float) -> float:
        if cle == "a":
            return valeur
        if cle == "barres":
            valeur -= self.reglages.barres.origine_hw_m
        return valeur * MM_PAR_M

    def _depuis_carte(self, cle: str, valeur: float) -> float:
        if cle == "a":
            return valeur
        valeur /= MM_PAR_M
        if cle == "barres":
            valeur += self.reglages.barres.origine_hw_m
        return valeur

    def position(self) -> Pose:
        positions = self.liaison.etat.positions
        try:
            return Pose(
                **{
                    cle: self._depuis_carte(cle, positions[lettre])  # type: ignore[index]
                    for cle, lettre in self._lettres.items()
                }
            )
        except KeyError as manque:
            raise ErreurEtape(
                f"position de l'axe {manque} inconnue (carte pas encore lue)"
            ) from None

    def barriere_coupee(self) -> bool | None:
        return self.signaux.entree(BARRIERE)

    # ------------------------------------------------------------ mouvements

    def executer(self, pas: Pas, cible: Pose) -> None:
        depart = self.position()
        positions: dict[str, float] = {}
        duree = 0.0
        carres = 0.0
        for cle in pas.cibles:
            ecart = getattr(cible, cle) - getattr(depart, cle)
            if abs(ecart) <= 1e-9:
                continue
            vitesse = self._vitesses[cle]
            if pas.vitesse is not None and VITESSES_LENTES[pas.vitesse] == cle:
                vitesse = min(vitesse, getattr(self.reglages.vitesses, pas.vitesse))
            duree = max(duree, abs(ecart) / vitesse)
            carres += (
                self._vers_carte(cle, getattr(cible, cle))
                - self._vers_carte(cle, getattr(depart, cle))
            ) ** 2
            positions[self._lettres[cle]] = self._vers_carte(cle, getattr(cible, cle))  # type: ignore[index]
        with self._verrou:
            self._pas, self._contact = pas, False
            self._cible = positions
            self._f = math.sqrt(carres) / duree * 60 if duree > 0 else 0.0
            self._fin_mouvement = None if positions else self._horloge()
            self._rapports_a_l_envoi = self.liaison.etat.rapports_recus
            recentes = [kg for _, kg in self._lectures][-self.reglages.pesee.lectures :]
            self._contact_depuis_kg = median(recentes) if recentes else None
        if pas.contact_kg is not None and self._contact_depuis_kg is None:
            raise ErreurEtape(
                "balance du plateau sans lecture : pas de contact", QUOI_FAIRE_BALANCE
            )
        if not positions:
            return
        if pas.courant_reduit:
            self.signaux.sortie(COURANT_REDUIT, True)
        commande = self.liaison.deplacer_manuel(positions, self._f)
        if commande.erreur is not None:
            raise ErreurEtape(f"chariot de remplissage, « {commande.ligne} » : {commande.erreur}")

    def fini(self) -> bool:
        self._surveiller()
        with self._verrou:
            pas = self._pas
            if pas is None:
                return True
            if self._fin_mouvement is None:
                etat = self.liaison.etat
                if self._en_pause or not etat.au_repos:
                    return False
                if etat.rapports_recus <= self._rapports_a_l_envoi + 1:
                    return False
                if not self._contact and not self._arrive(etat.positions):
                    raise ErreurEtape(
                        f"chariot de remplissage arrêté avant la fin de « {pas.texte} »"
                    )
                self._fin_mouvement = self._horloge()
                courant = pas.courant_reduit
            else:
                courant = False
            attente = pas.attente_s
            if pas.pesee:
                attente = max(attente, self.reglages.pesee.attente_s)
        if courant:
            self.signaux.sortie(COURANT_REDUIT, False)
        assert self._fin_mouvement is not None
        return self._horloge() - self._fin_mouvement >= attente

    def _arrive(self, positions: dict[str, float]) -> bool:
        return all(
            abs(positions.get(lettre, float("inf")) - valeur) <= TOLERANCE_ARRIVEE
            for lettre, valeur in self._cible.items()
        )

    def resultat(self) -> Resultat:
        pose = self.position()
        with self._verrou:
            pas = self._pas
            contact = self._contact
        poids = self.peser() if pas is not None and pas.pesee else None
        return Resultat(pose=pose, contact=contact, poids_kg=poids)

    def _carte_prete(self) -> bool:
        etat = self.liaison.etat
        return etat.connectee and etat.etat is not None and not etat.en_alarme

    def _surveiller(self) -> bool:
        probleme = pour_carte(self.liaison.etat)
        if probleme is not None:
            texte, quoi_faire = probleme
            raise ErreurEtape(f"carte « {self.liaison.nom} » : {texte}", quoi_faire)
        return True

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
            reprendre = pas is not None and self._fin_mouvement is None and not self._contact
        if reprendre and cible:
            self.liaison.deplacer_manuel(cible, f)

    def arreter(self) -> None:
        with self._verrou:
            pas, self._pas = self._pas, None
        self.liaison.annuler_deplacement()
        if pas is not None and pas.courant_reduit:
            self.signaux.sortie(COURANT_REDUIT, False)
