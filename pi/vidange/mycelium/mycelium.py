"""Le Mycélium : verser la dose de semence sur chaque couche de substrat (module validé le
24/10/2026, option B ; agitateur FIXE depuis le 01/11/2026, fiche v10).

    mycelium = Mycelium(reglages.machine, agitateur, porte_bocal, chariot, nouveau_bocal=...)
    module = module_mycelium(mycelium)        # vidange/mycelium/module.py
    mycelium.demander(Demande("S1293", "seau_a", couche=1, variete="pleurote_grise"))

Un « agitateur » FIXE porte le bocal au-dessus du poste de remplissage, toujours au même endroit
(`mycelium → bocal`). Pour chaque couche versée (au vidage, y 0,42) et tassée par la griffe :
1. le bocal attend debout, manivelle en bas ; le chariot de remplissage est à y ≥ 0,40 (au
   vidage) ;
2. manivelle en haut, le bocal est retourné tête en bas (Porte-bocal), manivelle en bas ;
3. le chariot amène le seau : au poste (y 0,135 : spray, micropore, bord du seau ≤ 0,68), puis au
   dosage (y 0,155), plateau à la hauteur du dosage ;
4. la manivelle secoue le bocal en lisant la balance du chariot ; elle s'arrête quand la dose de
   la couche est atteinte, toujours pile en bas (jamais entre le haut et le bas) ;
5. le chariot repart au vidage ; manivelle en haut, bocal remis debout, manivelle en bas.
Verrous (vidange.mycelium.regles) : demi-tour seulement manivelle en haut, chariot à y ≥ 0,40 et
caméra du dosage à 0° ; la manivelle ne quitte « en bas » que chariot à y ≥ 0,40. La manivelle ne
tourne pas et le bocal ne se retourne pas pendant que la tête de préhension est dans la zone du
porte-bocal (`prehension_hors_zone`).

Avant tout, la manivelle prend son origine (tour lent, AgitateurFluidnc) : au premier geste, et
à chaque geste tant qu'elle n'est pas connue.

Un bocal sert un seau (toutes ses couches), ou 2 petits seaux de la même variété au plus. La
casse du bloc (agitation plus forte au début) ne se fait qu'à la 1re agitation d'un bocal.
Chaque pas est vérifié avant de partir (vidange.mycelium.regles) : un pas refusé met le module en
alarme, il ne bouge pas. Un geste est rejouable : refait depuis le début (après une alarme et le
Go), il repart de là où est l'agitateur ; la dose d'une couche est comptée depuis le poids du
plateau avant sa 1re agitation.

Le porte-bocal (vidange.porte_bocal, tâche 20) est derrière l'interface `PorteBocal` ; au
changement de bocal (MANIVELLE EN BAS, chariot de remplissage reculé ou au poste ; décision du
05/11/2026), ses mors s'ouvrent (l'ancien bocal est repris), le bocal neuf est posé, puis serré.
La manivelle ne remonte ensuite que pour le demi-tour.

Le bocal neuf (tâche 19 quater) : la Préhension le prend au stockage, dévisse sa capsule, visse un
couvercle percé et le pose sur le porte-bocal (vidange.bocal_neuf). Branchée par
`brancher_bocal_neuf(pose)`, l'étape « changer_de_bocal » lance ce geste et attend sa fin ; sans
elle (essais, simulateurs plus anciens), `nouveau_bocal(variete)` rend tout de suite un bocal.

Les modules pas encore écrits sont des cases vides, derrière des interfaces simples :
- chariot de remplissage (Remplissage, pas figé) : `ChariotRemplissage` ;
- pose du bocal neuf sans la Préhension : `nouveau_bocal(variete)`.

La caméra du dosage (vidange.vision.dosage, tâche 22) : `photo(raison)` pour les alertes, et
`camera` pour la photo du seau après chaque dose (bocal remis debout), notée avec sa dose. Elle ne
pivote pas pendant le demi-tour, et le demi-tour ne démarre que caméra à 0°.
"""

import math
import time
from collections import deque
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from typing import Literal, Protocol

from vidange.chef import Condition, ErreurEtape
from vidange.journal import donner_journal
from vidange.mycelium.agitateur import Agitateur, Pas, Resultat
from vidange.mycelium.regles import EtatChariot, PoseAgitateur, ReglesMycelium
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import FormatSeau, Machine

journal = donner_journal("mycelium")

Geste = Generator[Pas, Resultat, None]

QUOI_FAIRE = (
    "Regarder la vidéo du dosage : la manivelle est-elle bloquée, le bocal bien tenu ? Corriger, "
    "puis acquitter et donner le Go : le geste est refait depuis le début."
)
QUOI_FAIRE_TETE = (
    "La tête de préhension est au-dessus du porte-bocal : attendre qu'elle ait fini de poser ou "
    "de reprendre le bocal, ou la remonter et l'écarter, puis acquitter et donner le Go."
)
QUOI_FAIRE_PURGE = (
    "Le dosage de la semence attend la fin de la purge de l'enceinte (store refermé) : attendre "
    "qu'elle finisse (page MODE, ENCEINTE), puis acquitter et donner le Go."
)
# Le geste protégé du chef (vidange.chef.chef.GESTES_PROTEGES) que demande le Mycélium.
DOSAGE = "dosage_semence"
QUOI_FAIRE_VIDE = (
    "Le poids du seau ne monte plus : bocal vide ou couvercle bouché ? Le seau est marqué « pas "
    "bon » dans le registre. Changer ou déboucher le bocal, puis acquitter et donner le Go : "
    "l'agitation reprend pour finir la dose."
)


class PorteBocal(Protocol):
    """Le demi-tour du bocal (moteur JGY370 et son verrou) et ses mors : vidange.porte_bocal."""

    def retourner_tete_en_bas(self) -> None: ...

    def remettre_debout(self) -> None: ...

    def ouvrir_mors(self) -> None: ...

    def serrer_bocal(self) -> None: ...

    def fini(self) -> bool:
        """Vrai quand le geste est fini ; ErreurEtape s'il a échoué."""
        ...

    def arreter(self) -> None: ...


class PoseBocalNeuf(Protocol):
    """Le geste de la Préhension qui met un bocal de semence neuf dans le porte-bocal
    (vidange.bocal_neuf.BocalNeuf)."""

    pretes: Condition

    def commencer(self, variete: str) -> None:
        """Lance le geste (ErreurEtape si la tête sert déjà ou si une condition manque)."""
        ...

    def fini(self) -> bool:
        """Vrai quand le bocal est posé et serré ; ErreurEtape s'il a échoué."""
        ...

    def bocal(self) -> "Bocal":
        """Le bocal posé (son QR et sa variété)."""
        ...

    def arreter(self) -> None: ...


class ChariotRemplissage(Protocol):
    """Le chariot de remplissage (module Remplissage, pas encore figé)."""

    def etat(self) -> EtatChariot | None:
        """Où il est (None : pas connu)."""
        ...

    def ecarter(self) -> None:
        """Aller à y ≥ y_ecarte_min (au vidage, s'il est plus près du poste)."""
        ...

    def amener_au_dosage(self, plateau_z: float) -> None:
        """Le seau au poste (spray, micropore), puis sous le bocal (y_dosage), plateau à cette
        hauteur."""
        ...


class CameraDosage(Protocol):
    """La caméra du dosage sur son servo (vidange.vision.dosage.CameraDosage)."""

    def commencer_photo_seau(
        self, seau: str, couche: int, bocal: str, grammes: float, cycle: int | None = None
    ) -> None: ...

    def photo_seau_finie(self) -> bool: ...

    def pivote(self) -> bool:
        """Pas tournée vers le bocal (ou position inconnue)."""
        ...


@dataclass(frozen=True)
class Bocal:
    code: str  # QR du bocal
    variete: str


@dataclass(frozen=True)
class Demande:
    """Une couche de substrat versée et tassée, qui attend son mycélium."""

    seau: str  # QR du seau
    format: str  # nom dans machine.yaml (griffe → formats)
    couche: int
    variete: str
    # Cycle du registre (vidange du fût), s'il y en a un.
    cycle: int | None = None


@dataclass(frozen=True)
class Dose:
    """Une dose versée, telle que le Pi la note."""

    seau: str
    couche: int
    bocal: str
    variete: str
    kg: float


@dataclass
class Plan:
    """Où en est le mycélium."""

    bocal: Bocal | None = None
    # Seaux servis par ce bocal, et leur format.
    seaux_du_bocal: list[str] = field(default_factory=list)
    format_du_bocal: str | None = None
    # La 1re agitation du bocal (casse du bloc) est faite.
    casse_faite: bool = False
    tete_en_bas: bool = False
    # Poids du plateau avant la 1re agitation de la couche en cours (kg).
    poids_depart_kg: float | None = None


class Mycelium:
    def __init__(
        self,
        machine: Machine,
        agitateur: Agitateur,
        porte_bocal: PorteBocal,
        chariot: ChariotRemplissage,
        nouveau_bocal: Callable[[str], Bocal],
        registre: Registre | None = None,
        horloge: Callable[[], float] = time.monotonic,
        photo: Callable[[str], object] = lambda raison: None,
        camera: CameraDosage | None = None,
        prehension_hors_zone: Callable[[], bool] = lambda: True,
        permission: Callable[[str], str | None] = lambda geste: None,
    ) -> None:
        """`nouveau_bocal(variete)` : un bocal neuf de cette variété est mis dans le porte-bocal
        (gestes du Porte-bocal et de la Préhension, QR lu par la vision) ; il rend ce bocal.
        `photo(raison)` : photo de la caméra du dosage, notée avec l'alarme. `camera` : la caméra
        du dosage, pour la photo du seau après chaque dose (None : pas de photo).
        `prehension_hors_zone` : la tête de préhension est hors de la zone du porte-bocal
        (Prehension.hors_zone_porte_bocal ; sans préhension branchée : toujours vrai).
        `permission(geste)` : Chef.permission, demandée avant le dosage de la semence
        (« dosage_semence ») ; None = permis (sans chef branché : toujours permis)."""
        assert machine.mycelium is not None and machine.griffe is not None
        self.reglages = machine.mycelium
        self.formats = machine.griffe.formats
        self.regles = ReglesMycelium(machine)
        self.agitateur = agitateur
        self.porte_bocal = porte_bocal
        self.chariot = chariot
        self.registre = registre
        self._nouveau_bocal = nouveau_bocal
        # Le geste de la Préhension (tâche 19 quater), s'il est branché.
        self.pose_bocal_neuf: PoseBocalNeuf | None = None
        self._horloge = horloge
        self._photo = photo
        self.camera = camera
        self._prehension_hors_zone = prehension_hors_zone
        self._permission = permission
        # Dose (et cycle) dont le seau attend sa photo.
        self._a_photographier: tuple[Dose, int | None] | None = None
        self.plan = Plan()
        self.doses: list[Dose] = []
        # Simulateur seulement : le faux matériel du porte-bocal (vidange.porte_bocal.faux).
        self.materiel_porte_bocal: object | None = None
        self._demandes: deque[Demande] = deque()
        self._termine = False
        self._seaux_du_cycle: dict[tuple[int, str], int] = {}
        self.pose: PoseAgitateur | None = None
        self._geste: Geste | None = None
        self._pas: Pas | None = None
        # Le pas en cours veut le chariot de remplissage à y ≥ 0,40 (surveillé).
        self._exige_ecart = False
        self._depuis = 0.0

    # ------------------------------------------------------------ ce que disent les autres

    def demander(self, demande: Demande) -> None:
        """Une couche attend son mycélium (appelé quand la griffe a vidé et tassé la couche)."""
        seau = self.formats.get(demande.format)
        if seau is None:
            raise ValueError(f"format « {demande.format} » absent de machine.yaml")
        if not 1 <= demande.couche <= seau.couches:
            raise ValueError(f"couche n° {demande.couche} : le format en a {seau.couches}")
        self._demandes.append(demande)

    def terminer(self) -> None:
        """Plus de couche à doser : le module finit quand il a tout fait (simulateur, essais)."""
        self._termine = True

    @property
    def demande(self) -> Demande | None:
        return self._demandes[0] if self._demandes else None

    def couche_en_attente(self) -> bool:
        """Pour la griffe : une couche attend encore son mycélium (seau pas prêt)."""
        return bool(self._demandes)

    def _position(self) -> PoseAgitateur | None:
        try:
            return self.agitateur.position()
        except ErreurEtape:
            return None

    def _bouge(self) -> bool:
        pas = self._pas
        return self._geste is not None and pas is not None and (pas.bouge or bool(pas.porte_bocal))

    def _demi_tour_en_cours(self) -> bool:
        pas = self._pas
        return (
            self._geste is not None
            and pas is not None
            and pas.porte_bocal in ("tete_en_bas", "debout")
        )

    def _camera_pivote(self) -> bool:
        return self.camera is not None and self.camera.pivote()

    def refus_chariot(self) -> str | None:
        """Pour le chariot de remplissage : la raison pour laquelle il ne doit pas rouler près du
        poste (ni y monter son plateau), ou None. Permis seulement manivelle en bas, arrêtée."""
        return self.regles.refus_chariot(self._position(), self._bouge())

    def refus_demi_tour(self) -> str | None:
        """Pour le porte-bocal : pourquoi le demi-tour du bocal est interdit, ou None."""
        pose = self._position()
        if pose is None:
            return "position de la manivelle du mycélium inconnue"
        return self.regles.refus_demi_tour(pose, self.chariot.etat(), self._camera_pivote())

    def camera_peut_pivoter(self) -> bool:
        """Pour la caméra du dosage : elle ne pivote pas pendant le demi-tour du bocal (aucune
        condition sur la manivelle, le bocal ni le chariot)."""
        return not self._demi_tour_en_cours()

    def etat_manivelle(self) -> str | None:
        """Pour la préhension : « haut » ou « bas » (manivelle arrêtée là, pas de demi-tour en
        cours), None sinon (elle bouge, entre les deux, ou inconnue)."""
        pose = self._position()
        if self._bouge() or pose is None:
            return None
        if self.regles.en_haut(pose):
            return "haut"
        if self.regles.en_bas(pose):
            return "bas"
        return None

    def dosage_en_cours(self) -> bool:
        """Pour la griffe : le mycélium n'attend pas (manivelle pas en bas, bocal tête en bas,
        ou il bouge) : la zone du dosage lui est interdite."""
        pose = self._position()
        return (
            self._bouge() or pose is None or not self.regles.en_bas(pose) or self.plan.tete_en_bas
        )

    def refus_dosage(self) -> str | None:
        """Le chef permet-il le dosage de la semence maintenant (purge du Nettoyage) ?"""
        return self._permission(DOSAGE)

    def dosage_permis(self) -> bool:
        return self.refus_dosage() is None

    # ------------------------------------------------------------ conditions des étapes

    def couche_ou_fin(self) -> bool:
        return bool(self._demandes) or self._termine

    def en_attente(self) -> bool:
        """Manivelle en bas, bocal debout."""
        pose = self.agitateur.position()
        return self.regles.en_bas(pose) and not self.plan.tete_en_bas

    def pret_pour_le_seau(self) -> bool:
        """Manivelle en bas, bocal tête en bas."""
        pose = self.agitateur.position()
        return self.regles.en_bas(pose) and self.plan.tete_en_bas

    def chariot_ecarte(self) -> bool:
        return self.regles.chariot_ecarte(self.chariot.etat())

    def seau_au_dosage(self) -> bool:
        """Le seau sous le bocal, plateau à la hauteur du dosage (sinon : alarme)."""
        chariot = self.chariot.etat()
        if not self.regles.chariot_au_dosage(chariot):
            return False
        assert chariot is not None and self.demande is not None
        refus = self.regles.refus_plateau(self.formats[self.demande.format], chariot)
        if refus is not None:
            raise ErreurEtape(refus, "Vérifier le réglage du plateau du chariot de remplissage.")
        return True

    def surveiller_chariot(self) -> bool:
        """Pendant un demi-tour, ou quand la manivelle quitte « en bas » (prise d'origine, aller
        en haut), le chariot de remplissage reste à y ≥ 0,40."""
        if self._geste is None or self._pas is None or not self._exige_ecart:
            return True
        return self.chariot_ecarte()

    # ------------------------------------------------------------ actions des étapes

    def ecarter_le_chariot(self) -> None:
        self.chariot.ecarter()

    def amener_le_seau(self) -> None:
        assert self.demande is not None
        self.chariot.amener_au_dosage(self.regles.plateau_dosage(self.format))

    def brancher_bocal_neuf(self, pose: PoseBocalNeuf) -> None:
        """Le bocal neuf est mis par le geste de la Préhension (au lieu de `nouveau_bocal`)."""
        self.pose_bocal_neuf = pose

    def changer_de_bocal(self) -> None:
        demande = self.demande
        assert demande is not None
        self._adopter_bocal(self._nouveau_bocal(demande.variete))

    def _adopter_bocal(self, bocal: Bocal) -> None:
        journal.info("Mycélium : nouveau bocal %s (%s)", bocal.code, bocal.variete)
        self.plan = Plan(bocal=bocal)
        if self.registre is not None:
            try:
                self.registre.objet("bocal", bocal.code, variete=bocal.variete)
            except ErreurRegistre as erreur:
                journal.error("Mycélium : registre : %s", erreur)

    # ------------------------------------------------------------ déroulé d'un geste

    @property
    def format(self) -> FormatSeau:
        assert self.demande is not None
        return self.formats[self.demande.format]

    def lancer(self, geste: Callable[[], Geste]) -> None:
        """Action d'une étape : le geste part depuis là où est l'agitateur (après la prise
        d'origine de la manivelle, si elle n'est pas connue)."""
        self.agitateur.oublier_saut()
        self._pas = None
        if self.agitateur.origine_connue():
            self.pose = self.agitateur.position()
            self._geste = geste()
        else:
            self.pose = None
            self._geste = self._apres_origine(geste)
        self._suivant(None)

    def _apres_origine(self, geste: Callable[[], Geste]) -> Geste:
        resultat = yield Pas("origine de la manivelle (tour lent)", origine=True)
        self.pose = resultat.pose
        yield from geste()

    def _suivant(self, resultat: Resultat | None) -> None:
        assert self._geste is not None
        try:
            pas = next(self._geste) if resultat is None else self._geste.send(resultat)
        except StopIteration:
            self._geste = self._pas = None
            return
        self._envoyer(pas)

    def _refus_tete(self, pas: Pas) -> str | None:
        """La manivelle (et le demi-tour) ne bougent pas pendant que la tête de préhension est
        dans la zone du porte-bocal. Les mors et les pesées ne comptent pas."""
        if pas.porte_bocal in ("ouvrir", "serrer") or not (pas.bouge or pas.porte_bocal):
            return None
        if self._prehension_hors_zone():
            return None
        return (
            f"mycélium, « {pas.texte} » refusé : la tête de préhension est dans la zone du "
            "porte-bocal (ou sa position est inconnue)"
        )

    def _envoyer(self, pas: Pas) -> None:
        self._pas = pas
        self._exige_ecart = False
        self._depuis = self._horloge()
        chariot = self.chariot.etat()
        refus = self._refus_tete(pas)
        if refus is not None:
            raise ErreurEtape(refus, QUOI_FAIRE_TETE)
        if pas.bocal_neuf:
            # La Préhension prend un bocal au stockage et le pose sur le porte-bocal : la
            # manivelle reste en bas, bocal debout (le chariot est reculé ou au poste).
            demande = self.demande
            assert demande is not None and self.pose_bocal_neuf is not None
            if self.pose is None or not self.regles.en_bas(self.pose) or self.plan.tete_en_bas:
                raise ErreurEtape(
                    f"« {pas.texte} » refusé : le bocal neuf ne se pose que manivelle en bas, "
                    "bocal debout",
                    QUOI_FAIRE,
                )
            journal.info("Mycélium : %s (variété %s)", pas.texte, demande.variete)
            self.pose_bocal_neuf.commencer(demande.variete)
            return
        if pas.origine:
            # Tour lent : la manivelle passe en haut.
            refus = self.regles.refus_manivelle(None, chariot)
            if refus is not None:
                raise ErreurEtape(f"mycélium, « {pas.texte} » refusé : {refus}", QUOI_FAIRE)
            journal.info("Mycélium : %s", pas.texte)
            self._exige_ecart = True
            self.agitateur.executer(pas, None)
            return
        assert self.pose is not None
        if pas.porte_bocal in ("tete_en_bas", "debout"):
            refus = self.regles.refus_demi_tour(self.pose, chariot, self._camera_pivote())
            if refus is not None:
                raise ErreurEtape(f"« {pas.texte} » refusé : {refus}", QUOI_FAIRE)
            self._exige_ecart = True
            if pas.porte_bocal == "tete_en_bas":
                self.porte_bocal.retourner_tete_en_bas()
            else:
                self.porte_bocal.remettre_debout()
            return
        if pas.porte_bocal is not None:
            # Les mors : pour la pose et la reprise du bocal par la préhension.
            if not self.regles.en_bas(self.pose) or self.plan.tete_en_bas:
                raise ErreurEtape(
                    f"« {pas.texte} » refusé : les mors ne bougent que manivelle en bas, bocal "
                    "debout",
                    QUOI_FAIRE,
                )
            if pas.porte_bocal == "ouvrir":
                self.porte_bocal.ouvrir_mors()
            else:
                self.porte_bocal.serrer_bocal()
            return
        cible = self.pose if pas.angle is None else self.pose.avec(angle=pas.angle)
        if pas.jusqu_a_kg is not None:
            # L'étape attend déjà la permission ; ceci ne sert que si elle tombe en plein geste.
            refus = self.refus_dosage()
            if refus is not None:
                raise ErreurEtape(f"mycélium, « {pas.texte} » refusé : {refus}", QUOI_FAIRE_PURGE)
        refus = self.regles.refus_manivelle(cible, chariot, agitation=pas.jusqu_a_kg is not None)
        if refus is not None:
            raise ErreurEtape(f"mycélium, « {pas.texte} » refusé : {refus}", QUOI_FAIRE)
        self._exige_ecart = pas.jusqu_a_kg is None and not self.regles.en_bas(cible)
        journal.debug("Mycélium : %s", pas.texte)
        self.agitateur.executer(pas, cible)

    def geste_fini(self) -> bool:
        """Condition de fin des étapes : fait partir les pas l'un après l'autre."""
        try:
            return self._avancer()
        except ErreurEtape:
            if self.agitateur.saut:
                self._marquer_seau("saut de poids pendant l'agitation (bocal cassé ou tombé ?)")
                self._photo("saut de poids pendant l'agitation")
            raise

    def _avancer(self) -> bool:
        while self._geste is not None:
            pas = self._pas
            assert pas is not None
            if pas.bocal_neuf:
                assert self.pose is not None and self.pose_bocal_neuf is not None
                if not self.pose_bocal_neuf.fini():
                    return False
                self._adopter_bocal(self.pose_bocal_neuf.bocal())
                resultat = Resultat(pose=self.pose)
            elif pas.porte_bocal is not None:
                assert self.pose is not None
                if not self.porte_bocal.fini():
                    return False
                if pas.porte_bocal in ("tete_en_bas", "debout"):
                    self.plan.tete_en_bas = pas.porte_bocal == "tete_en_bas"
                resultat = Resultat(pose=self.pose)
            elif not pas.bouge:
                assert self.pose is not None
                if self._horloge() - self._depuis < pas.attente_s:
                    return False
                resultat = Resultat(pose=self.pose)
            else:
                if not self.agitateur.fini():
                    return False
                resultat = self.agitateur.resultat()
                self.pose = resultat.pose
            self._suivant(resultat)
        return True

    def pauser(self) -> None:
        self.agitateur.pauser()

    def reprendre(self) -> None:
        self.agitateur.reprendre()

    def arreter(self) -> None:
        if self._pas is not None and self._pas.bocal_neuf and self.pose_bocal_neuf is not None:
            self.pose_bocal_neuf.arreter()
        self._geste = self._pas = None
        self.agitateur.arreter()
        self.porte_bocal.arreter()

    # ------------------------------------------------------------ morceaux de gestes

    def _manivelle(self, bas: bool) -> Geste:
        assert self.pose is not None
        if (self.regles.en_bas if bas else self.regles.en_haut)(self.pose):
            return
        yield Pas(
            "manivelle en bas" if bas else "manivelle en haut",
            angle=self.regles.angle_proche(self.pose.angle, bas),
            tr_min=self.reglages.vitesses.placement_tr_min,
        )

    def _peser(self, texte: str) -> Pas:
        assert self.pose is not None
        return Pas(
            texte, angle=self.pose.angle, attente_s=self.reglages.dose.attente_pesee_s, pesee=True
        )

    def _poids(self, resultat: Resultat) -> float:
        if resultat.poids_kg is None:
            raise ErreurEtape("balance du chariot sans lecture", QUOI_FAIRE)
        return resultat.poids_kg

    def _agiter(
        self, texte: str, tr_min: float, duree_s: float, jusqu_a_kg: float
    ) -> Generator[Pas, Resultat, bool]:
        """Secouer au plus `duree_s`, arrêt pile en bas ; rend vrai si la dose est atteinte."""
        assert self.pose is not None
        # Le sens qui ramène la manivelle vers 0 : le nombre de degrés ne grandit pas.
        sens = -1 if self.pose.angle > 0 else 1
        tours = max(1, math.ceil(tr_min * duree_s / 60))
        depart = self.regles.bas_suivant(self.pose.angle, sens)
        resultat = yield Pas(
            texte, angle=depart + sens * 360 * tours, tr_min=tr_min, jusqu_a_kg=jusqu_a_kg
        )
        if resultat.arrete:
            yield Pas(
                "manivelle en bas",
                angle=self.regles.bas_suivant(resultat.pose.angle, sens),
                tr_min=self.reglages.vitesses.placement_tr_min,
            )
        return resultat.arrete

    # ------------------------------------------------------------ les gestes

    def geste_origine(self) -> Geste:
        """Prise d'origine de la manivelle (faite par `lancer` si elle n'est pas connue, chariot
        de remplissage à y ≥ 0,40), puis manivelle en bas (l'attente)."""
        yield from self._manivelle(bas=True)

    def geste_changer_de_bocal(self) -> Geste:
        """Manivelle en bas (pose et reprise par la préhension, chariot de remplissage reculé ou
        au poste) ; mors ouverts (l'ancien bocal est repris), bocal neuf posé, serré. La manivelle
        reste en bas : elle ne remonte que pour le demi-tour."""
        yield from self._manivelle(bas=True)
        if self.pose_bocal_neuf is not None:
            # Tâche 19 quater : la Préhension ouvre les mors, prend le bocal au stockage, le pose et
            # le serre (étapes 1 à 20 de sa fiche).
            yield Pas("bocal neuf de semence (Préhension)", bocal_neuf=True)
            return
        yield Pas("mors ouverts", porte_bocal="ouvrir")
        self.changer_de_bocal()
        yield Pas("bocal serré", porte_bocal="serrer")

    def _demi_tour(self, porte_bocal: Literal["tete_en_bas", "debout"], texte: str) -> Geste:
        """Le demi-tour, toujours manivelle en haut ; la manivelle redescend ensuite (attente)."""
        yield from self._manivelle(bas=False)
        yield Pas(texte, porte_bocal=porte_bocal)
        yield from self._manivelle(bas=True)

    def geste_retourner_le_bocal(self) -> Geste:
        """Bocal tête en bas (manivelle en haut, chariot à y ≥ 0,40), puis manivelle en bas."""
        if not self.plan.tete_en_bas:
            yield from self._demi_tour("tete_en_bas", "bocal tête en bas")
        yield from self._manivelle(bas=True)

    def geste_agiter(self) -> Geste:
        """Casse du bloc (1re agitation du bocal), puis agitation jusqu'à la dose de la couche."""
        demande = self.demande
        assert demande is not None
        plan, dose = self.plan, self.reglages.dose
        voulu = self.format.mycelium_kg
        assert voulu is not None
        yield from self._manivelle(bas=True)
        if plan.poids_depart_kg is None:
            plan.poids_depart_kg = self._poids((yield self._peser("pesée avant le dosage")))
        seuil = plan.poids_depart_kg + voulu - dose.arret_avant_kg
        v = self.reglages.vitesses
        atteinte = False
        if not plan.casse_faite and dose.casse_du_bloc_s > 0:
            atteinte = yield from self._agiter(
                "casse du bloc", v.casse_tr_min, dose.casse_du_bloc_s, seuil
            )
            plan.casse_faite = True
        if not atteinte:
            atteinte = yield from self._agiter(
                "agitation", v.agitation_tr_min, dose.temps_max_s, seuil
            )
        verse = self._poids((yield self._peser("pesée de la dose"))) - plan.poids_depart_kg
        if not atteinte:
            raison = f"poids qui ne monte plus : {verse * 1000:.0f} g sur {voulu * 1000:.0f} g"
            self._marquer_seau(raison)
            self._photo(raison)
            raise ErreurEtape(f"mycélium, seau {demande.seau} : {raison}", QUOI_FAIRE_VIDE)
        if abs(verse - voulu) > dose.tolerance * voulu:
            journal.warning(
                "Mycélium : seau %s, couche %d : %.0f g versés pour %.0f g voulus",
                demande.seau,
                demande.couche,
                verse * 1000,
                voulu * 1000,
            )
        self._noter_dose(demande, verse)

    def geste_rentrer(self) -> Geste:
        """Manivelle en haut, bocal remis debout, manivelle en bas (l'attente)."""
        if self.plan.tete_en_bas:
            yield from self._demi_tour("debout", "bocal remis debout")
        yield from self._manivelle(bas=True)

    # ------------------------------------------------------------ registre

    def _noter_dose(self, demande: Demande, kg: float) -> None:
        bocal = self.plan.bocal
        assert bocal is not None
        dose = Dose(demande.seau, demande.couche, bocal.code, bocal.variete, kg)
        self.doses.append(dose)
        self._a_photographier = (dose, demande.cycle)
        journal.info(
            "Mycélium : seau %s, couche %d : %.0f g du bocal %s",
            demande.seau,
            demande.couche,
            kg * 1000,
            bocal.code,
        )
        if self.registre is None or demande.cycle is None:
            return
        try:
            seau_du_cycle = self._seau_du_cycle(demande.cycle, demande.seau)
            self.registre.ajouter_dose(
                seau_du_cycle, bocal.code, round(kg * 1000, 1), couche=demande.couche
            )
        except ErreurRegistre as erreur:
            journal.error("Mycélium : registre : %s", erreur)

    def _seau_du_cycle(self, cycle: int, seau: str) -> int:
        """Le seau dans le cycle du registre (ajouté s'il n'y est pas encore)."""
        assert self.registre is not None
        cle = (cycle, seau)
        if cle not in self._seaux_du_cycle:
            lignes = self.registre.lire(
                "SELECT sc.id FROM seaux_du_cycle sc JOIN seaux s ON s.id = sc.seau_id "
                "WHERE sc.cycle_id = ? AND s.code = ?",
                (cycle, seau),
            )
            self._seaux_du_cycle[cle] = (
                lignes[0]["id"] if lignes else self.registre.ajouter_seau(cycle, seau)
            )
        return self._seaux_du_cycle[cle]

    def _marquer_seau(self, raison: str) -> None:
        """Le seau n'est pas rangé comme bon : le registre le marque."""
        demande = self.demande
        if demande is None:
            return
        journal.warning("Mycélium : seau %s pas bon : %s", demande.seau, raison)
        if self.registre is None:
            return
        try:
            self.registre.objet("seau", demande.seau, defaut=raison)
        except ErreurRegistre as erreur:
            journal.error("Mycélium : registre : %s", erreur)

    # ------------------------------------------------------------ la suite des étapes

    def _besoin_d_un_bocal(self, demande: Demande) -> bool:
        plan = self.plan
        if plan.bocal is None:
            return True
        if demande.seau in plan.seaux_du_bocal:
            return False
        return (
            plan.bocal.variete != demande.variete
            or plan.format_du_bocal != demande.format
            or len(plan.seaux_du_bocal) >= self.formats[demande.format].seaux_par_bocal
        )

    def apres_attente(self) -> str:
        return "fin" if self.demande is None else "ecarter_le_chariot"

    def _nouvelle_couche(self) -> None:
        """Une nouvelle couche commence (son poids de départ aussi)."""
        demande = self.demande
        assert demande is not None
        plan = self.plan
        if demande.seau not in plan.seaux_du_bocal:
            plan.seaux_du_bocal.append(demande.seau)
            plan.format_du_bocal = demande.format
        plan.poids_depart_kg = None

    def apres_ecart(self) -> str:
        """Le chariot est à y ≥ 0,40 : bocal neuf s'il le faut, sinon le demi-tour."""
        demande = self.demande
        assert demande is not None
        if self._besoin_d_un_bocal(demande):
            return "changer_de_bocal"
        self._nouvelle_couche()
        return "retourner_le_bocal"

    def apres_bocal(self) -> str:
        self._nouvelle_couche()
        return "retourner_le_bocal"

    def apres_agitation(self) -> str | None:
        """La dose est versée : la griffe peut reprendre le seau."""
        self._demandes.popleft()
        self.plan.poids_depart_kg = None
        return None

    def photographier_le_seau(self) -> None:
        """Bocal remis debout : la caméra du dosage pivote vers le seau qui vient d'être dosé, le
        photographie, revient au bocal (son verrou est vérifié par elle)."""
        if self.camera is None or self._a_photographier is None:
            return
        dose, cycle = self._a_photographier
        self._a_photographier = None
        self.camera.commencer_photo_seau(dose.seau, dose.couche, dose.bocal, dose.kg * 1000, cycle)

    def photo_du_seau_finie(self) -> bool:
        """La caméra est revenue au bocal : le demi-tour peut repartir."""
        return self.camera is None or self.camera.photo_seau_finie()

    def apres_retour(self) -> str:
        return "attendre_une_couche"
