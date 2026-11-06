"""La tête de préhension sur ses deux cartes : le pont et le chariot (X, Y) sur la carte du
portique, Z et la rotation sur la carte de la préhension ; le vide de la ventouse (ADS1115) et le
palier pesé du mât (carte de pesée RS485).

    tete = TeteFluidnc(reglages.machine, liaison_portique, liaison_prehension, signaux, force, vide)
    tete.demarrer(arret)            # zéro du vide recalé (vanne fermée), puis surveillance rapide
    tete.executer(pas, cible, 0)    # envoie un pas (sans attendre)
    tete.fini()                     # vrai quand le pas est fini ; ErreurEtape s'il a échoué
    tete.resultat()                 # où elle s'est arrêtée, contact, appui...

Un pas bouge soit le pont (X, Y), soit la tête (Z, rotation), jamais les deux (règle 1).
Les brosses du lavage (noyau, couronne : même carte que la tête) tournent dans le même
déplacement manuel que la rotation de la tête (`brosses`), pendant `duree_s`.
- Descente au contact (`palper`) : palpage de FluidNC (« G38.3 ») ; le contact de la tête
  (plateau flottant vu par un inductif M8) est le palpeur de la carte : elle s'arrête tout de
  suite au contact, et le Pi lit la cote Z où elle s'est arrêtée.
- Les autres pas sont des déplacements manuels (« $J= ») vers une position absolue : on peut les
  arrêter tout de suite sans perdre la position (0x85, le « feed hold » des déplacements
  manuels). C'est ce que fait la surveillance rapide (≈ 100 fois par seconde) :
  * levée (`vide_perte_kpa`) : le vide remonte au-dessus du seuil → arrêt ;
  * trajet (`choc`) : la force lue s'écarte du poids porté de plus de choc_n pendant plus de
    choc_duree_s → arrêt de Z et du pont ;
  * appui (`appui_arret_n`, `appui_max_n`) : l'appui atteint la consigne → arrêt ; dépasse le
    maximum (vissage au-delà de 150 N) → arrêt et alerte.
Pesée ou vide muets pendant un pas qui les surveille : arrêt aussi.

La force est tarée tête en l'air (`tarer`) : lecture = poids porté − poussée.
Le zéro du vide est recalé à chaque démarrage, vanne fermée (`CapteurVide.recaler_zero`).
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from statistics import fmean, median
from typing import Literal, Protocol

from vidange.chef import Condition, ErreurEtape
from vidange.fiabilite.constats import lancer_boucle
from vidange.fluidnc import Commande, Liaison
from vidange.griffe.bras import MM_PAR_M, TOLERANCE_ARRIVEE, CapteurForce
from vidange.journal import donner_journal
from vidange.porte_bocal.signaux import Signaux, SignauxFluidnc
from vidange.prehension.regles import Pose
from vidange.quoi_faire import pour_carte
from vidange.reglages import CarteFluidnc, Machine, VidePrehension

journal = donner_journal("prehension.tete")

# Noms des signaux (docs/entrees-sorties.yaml, fluidnc.yaml).
CONTACT = "contact_tete"
VANNE = "vanne_vide"
AIMANTS = "electroaimants_capsule"

Arret = Literal["vide", "choc", "appui", "appui_max", "traction"]
# Les brosses du lavage, par leur nom court dans un Pas → axe de machine.yaml.
BROSSES = {"noyau": "lavage_noyau", "couronne": "lavage_couronne"}

QUOI_FAIRE_CHOC = (
    "La préhension a senti un choc pendant un trajet : le pont et la tête se sont arrêtés, la "
    "tête est remontée lentement. Regarder la vidéo et la photo (page web) : qu'a-t-elle "
    "touché ? Dégager, vérifier la tête et ce qu'elle tient, puis acquitter et donner le Go."
)
QUOI_FAIRE_PESEE = (
    "La pesée de la préhension ne répond plus : la tête s'est arrêtée. Vérifier le câble du bus "
    "des pesées et la carte de la préhension, puis acquitter et donner le Go."
)
QUOI_FAIRE_VIDE = (
    "Le capteur de vide de la ventouse ne répond plus, ou son zéro est faux (vanne qui fuit ?). "
    "Vérifier le capteur, son câble vers l'ADS1115 et la vanne du venturi, puis redémarrer."
)
QUOI_FAIRE_PALPAGE = (
    "La carte de la préhension est restée en pause pendant une descente au contact. Sur place : "
    "regarder la tête, réinitialiser la carte (page web, cartes) et refaire sa prise "
    "d'origine, puis acquitter et donner le Go."
)


class ErreurVide(Exception):
    """Capteur de vide muet ou déréglé."""


@dataclass(frozen=True)
class Pas:
    """Un mouvement : du pont (x, y) ou de la tête (z, a), jamais des deux."""

    texte: str
    cibles: dict[str, float] = field(default_factory=dict)
    # Vitesse lente de Z (nom dans machine.yaml → prehension → vitesses), sinon la plus rapide.
    vitesse: str | None = None
    # Descente au contact de la tête (palpage).
    palper: bool = False
    # Levée : arrêt si le vide remonte au-dessus de ce seuil (kPa).
    vide_perte_kpa: float | None = None
    # Trajet : arrêt sur un choc.
    choc: bool = False
    # Appui (N) : arrêt quand il atteint appui_arret_n ; arrêt et alerte au-delà de appui_max_n.
    appui_arret_n: float | None = None
    appui_max_n: float | None = None
    # Tirage (N) : arrêt si la tête tire plus que tant vers le haut (séparation de deux seaux
    # emboîtés, Remplissage).
    traction_max_n: float | None = None
    # Vissage : la rotation va à la vitesse du vissage (Z la suit).
    vissage: bool = False
    # Attente après le mouvement (s), puis pesée (médiane de plusieurs lectures).
    attente_s: float = 0.0
    pesee: bool = False
    # Lavage : brosses (noyau, couronne) qui tournent pendant le pas, de tant de degrés (« en
    # avant »), et durée imposée du pas (s ; la vitesse en découle, pour tous les axes).
    brosses: dict[str, float] = field(default_factory=dict)
    duree_s: float | None = None


@dataclass(frozen=True)
class Resultat:
    pose: Pose
    # La descente s'est arrêtée au contact de la tête.
    contact: bool = False
    # Pourquoi le mouvement a été arrêté avant sa cible (None : il est allé au bout).
    arret: Arret | None = None
    # Poids porté − poussée (N), si le pas demandait une pesée.
    force_n: float | None = None
    # Appui (N) à la fin du pas, et le plus fort pendant le pas.
    appui_n: float | None = None
    appui_max_n: float | None = None


def _surveille_la_force(pas: Pas) -> bool:
    return pas.choc or any(
        valeur is not None for valeur in (pas.appui_arret_n, pas.appui_max_n, pas.traction_max_n)
    )


class Tete(Protocol):
    pretes: Condition
    surveillance: Condition

    def position(self) -> Pose: ...

    def executer(self, pas: Pas, cible: Pose, poids_porte_n: float) -> None: ...

    def fini(self) -> bool: ...

    def resultat(self) -> Resultat: ...

    def peser(self) -> float: ...

    def tarer(self) -> None: ...

    def vanne(self, ouverte: bool) -> None: ...

    def aimants(self, actifs: bool) -> None: ...

    def vide_kpa(self) -> float | None: ...

    def acceleration_seau(self, reduite: bool, facteur: float = 1.0) -> None: ...

    def pauser(self) -> None: ...

    def reprendre(self) -> None: ...

    def arreter(self) -> None: ...

    @property
    def choc(self) -> bool: ...

    def oublier_choc(self) -> None: ...


def signaux_prehension(liaison: Liaison, carte: CarteFluidnc) -> SignauxFluidnc:
    """Les signaux de la tête sur sa carte (erreur claire s'il en manque dans fluidnc.yaml)."""
    return SignauxFluidnc(liaison, carte, (CONTACT,), (VANNE, AIMANTS))


class CapteurVide:
    """Le vide de la ventouse (kPa), moyenné ; zéro recalé à chaque démarrage, vanne fermée.

    `lire` : une lecture brute en kPa (sur la machine : `materiel.mesurer("vide_venturi")`, la
    conversion tension → kPa est dans docs/entrees-sorties.yaml)."""

    def __init__(self, reglages: VidePrehension, lire: Callable[[], float]) -> None:
        self.reglages = reglages
        self._lire = lire
        self._lectures: deque[float] = deque(maxlen=reglages.moyenne)
        self.zero: float | None = None

    def recaler_zero(self) -> float:
        """Vanne fermée : la moyenne de zero_lectures lectures devient le zéro."""
        try:
            zero = fmean(self._lire() for _ in range(self.reglages.zero_lectures))
        except Exception as erreur:
            raise ErreurVide(f"capteur de vide muet ({erreur})") from erreur
        if abs(zero) > self.reglages.zero_ecart_max_kpa:
            raise ErreurVide(
                f"zéro du capteur de vide à {zero:+.1f} kPa, vanne fermée (au plus ± "
                f"{self.reglages.zero_ecart_max_kpa:g} kPa) : capteur déréglé ou vanne qui fuit"
            )
        self.zero = zero
        self._lectures.clear()
        journal.info("Préhension : zéro du capteur de vide recalé (%+.2f kPa)", zero)
        return zero

    def lire(self) -> float:
        """Une lecture de plus ; rend la moyenne des dernières."""
        if self.zero is None:
            raise ErreurVide("zéro du capteur de vide pas encore recalé")
        self._lectures.append(self._lire() - self.zero)
        return fmean(self._lectures)

    def valeur(self) -> float | None:
        return fmean(self._lectures) if self._lectures else None


class TeteFluidnc:
    def __init__(
        self,
        machine: Machine,
        portique: Liaison,
        prehension: Liaison,
        signaux: Signaux,
        force: CapteurForce,
        vide: CapteurVide,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        assert machine.prehension is not None
        self.reglages = machine.prehension
        self.portique = portique
        self.liaison_tete = prehension
        self.signaux = signaux
        self.capteur = force
        self.vide = vide
        self._horloge = horloge
        self._verrou = threading.Lock()
        self._noms = {"x": "pont_x", "y": "chariot_y", "z": "prehension_z", "a": "prehension_a"}
        self._lettres = {cle: machine.axes[nom].lettre for cle, nom in self._noms.items()}
        self._unites = {cle: machine.axes[nom].unite for cle, nom in self._noms.items()}
        # Axes des brosses du lavage (sur la carte de la tête), s'il y en a.
        self._brosses = {
            cle: machine.axes[nom] for cle, nom in BROSSES.items() if nom in machine.axes
        }
        # Lectures récentes de la force : (heure, newtons bruts).
        self._lectures: deque[tuple[float, float]] = deque(maxlen=400)
        self._derniere_lecture: float | None = None
        self._tare = 0.0
        self._pas: Pas | None = None
        self._liaison: Liaison = prehension
        self._cible: dict[str, float] = {}
        self._f = 0.0
        self._commandes: list[Commande] = []
        self._rapports_a_l_envoi = 0
        self._fin_mouvement: float | None = None
        self._poids_porte = 0.0
        self._arret: Arret | None = None
        self._appui: float | None = None
        self._appui_max: float | None = None
        self._choc_depuis: float | None = None
        self._choc = False
        self._muette: str | None = None
        self._en_pause = False
        self._acceleration_reduite: tuple[bool, float] | None = None
        self.pretes = Condition(
            f"cartes « {portique.nom} » et « {prehension.nom} » connectées et sans alarme",
            self._cartes_pretes,
        )
        self.surveillance = Condition(self.pretes.texte, self._surveiller)

    # ------------------------------------------------------------ surveillance rapide

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        """Vanne fermée, zéro du vide recalé (ErreurVide s'il est faux), puis la surveillance."""
        for nom in (VANNE, AIMANTS):
            try:
                self.signaux.sortie(nom, False)
            except ErreurEtape as erreur:
                journal.warning("Préhension : %s", erreur)
        self.vide.recaler_zero()
        return lancer_boucle(
            "prehension", 1 / self.reglages.vide.frequence_hz, self.surveiller, arret
        )

    def surveiller(self) -> None:
        """Une lecture du vide et de la force ; arrête le mouvement s'il le faut."""
        maintenant = self._horloge()
        try:
            vide: float | None = self.vide.lire()
        except Exception as erreur:
            vide = None
            with self._verrou:
                pas = self._pas
                if pas is not None and pas.vide_perte_kpa is not None and self._en_mouvement():
                    self._muette = f"capteur de vide muet ({erreur})"
                    self._annuler(self._liaison)
        try:
            brute = self.capteur.lire_n()
        except Exception as erreur:
            with self._verrou:
                silence = maintenant - (self._derniere_lecture or maintenant)
                if (
                    self._surveille_force()
                    and silence >= self.reglages.force.silence_max_s
                    and self._muette is None
                ):
                    self._muette = f"pesée de la préhension muette ({erreur})"
                    self._annuler(self.portique, self.liaison_tete)
            return
        with self._verrou:
            self._derniere_lecture = maintenant
            self._lectures.append((maintenant, brute))
            pas = self._pas
            if pas is None or self._arret is not None or not self._en_mouvement():
                return
            lecture = brute - self._tare
            appui = self._poids_porte - lecture
            self._appui = appui
            self._appui_max = appui if self._appui_max is None else max(self._appui_max, appui)
            if pas.vide_perte_kpa is not None and vide is not None and vide > pas.vide_perte_kpa:
                self._arreter_sur("vide", f"vide perdu pendant « {pas.texte} » ({vide:.0f} kPa)")
            elif pas.traction_max_n is not None and -appui > pas.traction_max_n:
                self._arreter_sur("traction", f"traction de {-appui:.0f} N pendant « {pas.texte} »")
            elif pas.appui_max_n is not None and appui > pas.appui_max_n:
                self._arreter_sur("appui_max", f"appui de {appui:.0f} N pendant « {pas.texte} »")
            elif pas.appui_arret_n is not None and appui >= pas.appui_arret_n:
                self._arreter_sur("appui", f"appui de {appui:.0f} N atteint")
            elif pas.choc:
                force = self.reglages.force
                if abs(lecture - self._poids_porte) <= force.choc_n:
                    self._choc_depuis = None
                elif self._choc_depuis is None:
                    self._choc_depuis = maintenant
                elif maintenant - self._choc_depuis >= force.choc_duree_s:
                    self._choc = True
                    self._arret = "choc"
                    journal.warning(
                        "Préhension : choc pendant « %s » (%+.0f N), pont et tête arrêtés",
                        pas.texte,
                        lecture - self._poids_porte,
                    )
                    self._annuler(self.portique, self.liaison_tete)

    def _en_mouvement(self) -> bool:
        return self._fin_mouvement is None

    def _surveille_force(self) -> bool:
        pas = self._pas
        return pas is not None and _surveille_la_force(pas) and self._en_mouvement()

    def _arreter_sur(self, arret: Arret, pourquoi: str) -> None:
        self._arret = arret
        journal.info("Préhension : arrêt, %s", pourquoi)
        self._annuler(self._liaison)

    def _annuler(self, *liaisons: Liaison) -> None:
        for liaison in liaisons:
            liaison.annuler_deplacement()

    def _force_recente(self, combien: int) -> float | None:
        if not self._lectures:
            return None
        return median(brute for _, brute in list(self._lectures)[-combien:])

    # ------------------------------------------------------------ capteurs et sorties

    def tarer(self) -> None:
        """Tête en l'air, rien de tenu : la lecture devient zéro."""
        with self._verrou:
            brute = self._force_recente(self.reglages.force.lectures_pesee)
            if brute is None:
                raise ErreurEtape(
                    "pesée de la préhension sans lecture : pas de tare", QUOI_FAIRE_PESEE
                )
            self._tare = brute

    def peser(self) -> float:
        with self._verrou:
            brute = self._force_recente(self.reglages.force.lectures_pesee)
        if brute is None:
            raise ErreurEtape("pesée de la préhension sans lecture", QUOI_FAIRE_PESEE)
        return brute - self._tare

    def vide_kpa(self) -> float | None:
        return self.vide.valeur()

    def vanne(self, ouverte: bool) -> None:
        self.signaux.sortie(VANNE, ouverte)

    def aimants(self, actifs: bool) -> None:
        self.signaux.sortie(AIMANTS, actifs)

    def acceleration_seau(self, reduite: bool, facteur: float = 1.0) -> None:
        """Accélération réduite des axes X et Y du portique quand la tête tient un seau, et
        multipliée par `facteur` (tête basse : portique → facteur_acceleration_tete_basse)."""
        if self._acceleration_reduite == (reduite, facteur):
            return
        acceleration = self.reglages.acceleration
        valeur = (acceleration.seau_mm_s2 if reduite else acceleration.normale_mm_s2) * facteur
        for cle in ("x", "y"):
            lettre = (self._lettres[cle] or "").lower()
            commande = self.portique.envoyer(f"$/axes/{lettre}/acceleration_mm_per_sec2={valeur:g}")
            if commande.finie and commande.erreur is not None:
                raise ErreurEtape(f"accélération du portique : {commande.erreur}")
        self._acceleration_reduite = (reduite, facteur)

    # ------------------------------------------------------------ mouvements

    def _facteur(self, cle: str) -> float:
        return MM_PAR_M if self._unites[cle] == "m" else 1

    def position(self) -> Pose:
        valeurs = {}
        for cle, lettre in self._lettres.items():
            liaison = self.portique if cle in "xy" else self.liaison_tete
            valeur = liaison.etat.positions.get(lettre or "")
            if valeur is None:
                raise ErreurEtape(
                    f"position de l'axe {self._noms[cle]} inconnue (carte « {liaison.nom} » pas "
                    "encore lue)"
                )
            valeurs[cle] = valeur / self._facteur(cle)
        return Pose(
            x=valeurs["x"] + self.reglages.decalage_mat_x,
            y=valeurs["y"],
            z=valeurs["z"],
            a=valeurs["a"],
        )

    def _axes(self, pose: Pose) -> dict[str, float]:
        """Clé (x, y, z, a) → valeur de l'axe (m ou °)."""
        return {"x": pose.x - self.reglages.decalage_mat_x, "y": pose.y, "z": pose.z, "a": pose.a}

    def _vitesses(self, pas: Pas) -> dict[str, float]:
        v = self.reglages.vitesses
        vitesses = {"x": v.pont_x, "y": v.chariot_y, "z": v.z, "a": v.a}
        if pas.vitesse is not None:
            vitesses["z"] = min(v.z, getattr(v, pas.vitesse))
        if pas.vissage:
            vitesses["a"] = v.vissage_deg_s
        return vitesses

    def executer(self, pas: Pas, cible: Pose, poids_porte_n: float) -> None:
        cles = set(pas.cibles)
        if cles & {"x", "y"} and cles & {"z", "a"}:
            raise ErreurEtape(f"préhension, « {pas.texte} » : pont et tête jamais ensemble")
        liaison = self.portique if cles & {"x", "y"} else self.liaison_tete
        if liaison is self.liaison_tete and (liaison.etat.etat or "").startswith("Hold"):
            raise ErreurEtape("carte de la préhension en pause", QUOI_FAIRE_PALPAGE)
        depart = self._axes(self.position())
        arrivee = self._axes(cible)
        mm = {cle: arrivee[cle] * self._facteur(cle) for cle in cles}
        brosses = self._cibles_brosses(pas)
        with self._verrou:
            self._pas, self._liaison, self._arret, self._muette = pas, liaison, None, None
            self._poids_porte = poids_porte_n
            self._appui = self._appui_max = self._choc_depuis = None
            self._fin_mouvement = None
            self._cible = {self._lettres[cle] or "": valeur for cle, valeur in mm.items()}
            self._cible.update(brosses)
            self._rapports_a_l_envoi = liaison.etat.rapports_recus
            self._commandes = []
            recente = self._force_recente(8)
        surveille = _surveille_la_force(pas)
        if surveille and recente is None:
            raise ErreurEtape(
                "pesée de la préhension sans lecture : pas de mouvement", QUOI_FAIRE_PESEE
            )
        if pas.vide_perte_kpa is not None and self.vide.valeur() is None:
            raise ErreurEtape("capteur de vide sans lecture : pas de levée", QUOI_FAIRE_VIDE)
        vitesses = self._vitesses(pas)
        if pas.palper:
            course = (depart["z"] - arrivee["z"]) * MM_PAR_M
            f = 60 * vitesses["z"] * MM_PAR_M
            lettre = self._lettres["z"]
            lignes = [f"G91 G38.3 {lettre}-{course:.3f} F{f:.0f}", "G90"]
            self._commandes = [liaison.envoyer(ligne) for ligne in lignes]
            return
        duree = max((abs(arrivee[cle] - depart[cle]) / vitesses[cle] for cle in cles), default=0.0)
        carres = [(mm[cle] - depart[cle] * self._facteur(cle)) ** 2 for cle in cles]
        carres += [degres**2 for degres in pas.brosses.values()]
        longueur = math.sqrt(sum(carres))
        if pas.duree_s is not None:
            duree = pas.duree_s
        f = 60 * longueur / duree if duree > 0 else 60 * vitesses["z"] * MM_PAR_M
        self._f = max(f, 1.0)
        commande = liaison.deplacer_manuel(self._cible, self._f)
        if commande.erreur is not None:
            raise ErreurEtape(f"préhension, « {commande.ligne} » : {commande.erreur}")

    def _cibles_brosses(self, pas: Pas) -> dict[str, float]:
        """Lettre → position visée (°) des brosses qui tournent pendant le pas."""
        cibles = {}
        for cle, degres in pas.brosses.items():
            axe = self._brosses.get(cle)
            if axe is None or axe.carte != self.liaison_tete.nom or axe.lettre is None:
                nom = BROSSES.get(cle, cle)
                raise ErreurEtape(f"préhension : pas d'axe « {nom} » sur la carte de la tête")
            position = self.liaison_tete.etat.positions.get(axe.lettre)
            if position is None:
                raise ErreurEtape(f"position de l'axe {BROSSES[cle]} inconnue")
            cible = position + degres
            debut, fin = axe.course
            if not debut <= cible <= fin:
                raise ErreurEtape(
                    f"compteur de l'axe {BROSSES[cle]} plein ({position:.0f}°) : redémarrer la "
                    f"carte « {self.liaison_tete.nom} » sur place (elle repart de 0)"
                )
            cibles[axe.lettre] = cible
        return cibles

    def fini(self) -> bool:
        self._surveiller()
        with self._verrou:
            if self._choc:
                raise ErreurEtape("choc pendant un trajet de la préhension", QUOI_FAIRE_CHOC)
            if self._muette is not None:
                quoi_faire = QUOI_FAIRE_VIDE if "vide" in self._muette else QUOI_FAIRE_PESEE
                raise ErreurEtape(self._muette, quoi_faire)
            pas = self._pas
            if pas is None:
                return True
            etat = self._liaison.etat
            if self._en_pause or not etat.au_repos:
                return False
            if pas.palper:
                if not all(commande.finie for commande in self._commandes):
                    return False
                for commande in self._commandes:
                    if commande.erreur is not None:
                        self._pas = None
                        raise ErreurEtape(f"préhension, « {commande.ligne} » : {commande.erreur}")
                deja = max(commande.rapports_a_la_reponse for commande in self._commandes)
                if etat.rapports_recus <= deja:
                    return False
            elif etat.rapports_recus <= self._rapports_a_l_envoi + 1:
                return False
            if self._fin_mouvement is None:
                if not pas.palper and self._arret is None and not self._arrive(etat.positions):
                    raise ErreurEtape(f"préhension arrêtée avant la fin de « {pas.texte} »")
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
            contact = False
            if pas is not None and pas.palper:
                contact = bool(self.signaux.entree(CONTACT)) or not self._arrive(
                    self._liaison.etat.positions
                )
            force = None
            if pas is not None and pas.pesee:
                brute = self._force_recente(self.reglages.force.lectures_pesee)
                force = None if brute is None else brute - self._tare
            return Resultat(
                pose=pose,
                contact=contact,
                arret=self._arret,
                force_n=force,
                appui_n=self._appui,
                appui_max_n=self._appui_max,
            )

    def _cartes_pretes(self) -> bool:
        return all(
            etat.connectee and etat.etat is not None and not etat.en_alarme
            for etat in (self.portique.etat, self.liaison_tete.etat)
        )

    def _surveiller(self) -> bool:
        for liaison in (self.portique, self.liaison_tete):
            probleme = pour_carte(liaison.etat)
            if probleme is not None:
                texte, quoi_faire = probleme
                raise ErreurEtape(f"carte « {liaison.nom} » : {texte}", quoi_faire)
        return True

    @property
    def choc(self) -> bool:
        return self._choc

    def oublier_choc(self) -> None:
        with self._verrou:
            self._choc = False

    def pauser(self) -> None:
        """Pause de Karulium : le mouvement s'arrête ; il repart à la reprise."""
        with self._verrou:
            self._en_pause = True
            pas, liaison = self._pas, self._liaison
        if pas is not None and pas.palper:
            liaison.pause()
        else:
            self._annuler(self.portique, self.liaison_tete)

    def reprendre(self) -> None:
        with self._verrou:
            self._en_pause = False
            pas, liaison, cible, f = self._pas, self._liaison, dict(self._cible), self._f
            self._rapports_a_l_envoi = liaison.etat.rapports_recus
        if pas is None or self._fin_mouvement is not None or self._arret is not None:
            return
        if pas.palper:
            liaison.reprendre()
        else:
            # La même cible (positions absolues) : le pas repart d'où il s'est arrêté.
            liaison.deplacer_manuel(cible, f)

    def arreter(self) -> None:
        """Alarme : le mouvement s'arrête. Une descente au contact (palpage) est mise en pause
        (« feed hold ») : la carte se débloque sur place."""
        with self._verrou:
            pas, liaison = self._pas, self._liaison
            self._pas = None
        if pas is not None and pas.palper and self._fin_mouvement is None:
            liaison.pause()
        self._annuler(self.portique, self.liaison_tete)
