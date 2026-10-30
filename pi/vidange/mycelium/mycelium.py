"""Le Mycélium : verser la dose de semence sur chaque couche de substrat (module validé le
24/10/2026, option B).

    mycelium = Mycelium(reglages.machine, agitateur, porte_bocal, chariot, nouveau_bocal=...)
    module = module_mycelium(mycelium)        # vidange/mycelium/module.py
    mycelium.demander(Demande("S1293", "seau_a", couche=1, variete="pleurote_grise"))

Un « agitateur » porte le bocal sur une glissière au-dessus du poste de remplissage. Pour chaque
couche versée et tassée par la griffe :
1. le bocal attend au garage, manivelle en haut ; le chariot de remplissage s'écarte ;
2. l'agitateur roule jusqu'au demi-tour ; manivelle en bas, le bocal est retourné tête en bas
   (Porte-bocal), manivelle en haut (la glissière ne roule que manivelle en haut) ;
3. il roule jusqu'au dosage ; manivelle en bas ;
4. le chariot revient avec le seau, plateau à la hauteur du dosage ;
5. la manivelle secoue le bocal en lisant la balance du chariot ; elle s'arrête quand la dose de
   la couche est atteinte, toujours pile en bas (jamais entre le haut et le bas) ;
6. le chariot repart ; manivelle en haut, retour au demi-tour, manivelle en bas, bocal remis
   debout, manivelle en haut, garage.

Avant tout, la manivelle prend son origine (tour lent, AgitateurFluidnc) : au premier geste, et
à chaque geste tant qu'elle n'est pas connue.

Un bocal sert un seau (toutes ses couches), ou 2 petits seaux de la même variété au plus. La
casse du bloc (agitation plus forte au début) ne se fait qu'à la 1re agitation d'un bocal.
Chaque pas est vérifié avant de partir (vidange.mycelium.regles) : un pas refusé met le module en
alarme, il ne bouge pas. Un geste est rejouable : refait depuis le début (après une alarme et le
Go), il repart de là où est l'agitateur ; la dose d'une couche est comptée depuis le poids du
plateau avant sa 1re agitation.

Le porte-bocal (vidange.porte_bocal, tâche 20) est derrière l'interface `PorteBocal` ; au
changement de bocal, ses mors s'ouvrent, le bocal neuf est posé, puis serré.

Les modules pas encore écrits sont des cases vides, derrière des interfaces simples :
- chariot de remplissage (Remplissage, pas figé) : `ChariotRemplissage` ;
- pose du bocal neuf (Préhension) et QR (tâche 22) : `nouveau_bocal(variete)` ;
- caméra du dosage (tâche 22) : `photo(raison)`.
"""

import math
import time
from collections import deque
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from typing import Literal, Protocol

from vidange.chef import ErreurEtape
from vidange.journal import donner_journal
from vidange.mycelium.agitateur import Agitateur, Pas, Resultat
from vidange.mycelium.regles import EtatChariot, PoseAgitateur, ReglesMycelium
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import FormatSeau, Machine

journal = donner_journal("mycelium")

Geste = Generator[Pas, Resultat, None]

QUOI_FAIRE = (
    "Regarder la vidéo du dosage : l'agitateur est-il bloqué, le bocal bien tenu ? Corriger, puis "
    "acquitter et donner le Go : le geste est refait depuis le début."
)
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


class ChariotRemplissage(Protocol):
    """Le chariot de remplissage (module Remplissage, pas encore figé)."""

    def etat(self) -> EtatChariot | None:
        """Où il est (None : pas connu)."""
        ...

    def ecarter(self) -> None:
        """Aller à y ≥ y_ecarte_min (vers la griffe ou le stockage, le Remplissage décide)."""
        ...

    def amener_au_dosage(self, plateau_z: float) -> None:
        """Le seau sous le bocal (y_dosage), plateau à cette hauteur."""
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
    ) -> None:
        """`nouveau_bocal(variete)` : un bocal neuf de cette variété est mis dans le porte-bocal
        (gestes du Porte-bocal et de la Préhension, QR lu par la vision) ; il rend ce bocal.
        `photo(raison)` : photo de la caméra du dosage, notée avec l'alarme."""
        assert machine.mycelium is not None and machine.griffe is not None
        self.reglages = machine.mycelium
        self.formats = machine.griffe.formats
        self.regles = ReglesMycelium(machine)
        self.agitateur = agitateur
        self.porte_bocal = porte_bocal
        self.chariot = chariot
        self.registre = registre
        self._nouveau_bocal = nouveau_bocal
        self._horloge = horloge
        self._photo = photo
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

    def refus_chariot(self) -> str | None:
        """Pour le chariot de remplissage : la raison pour laquelle il ne doit pas rouler, ou None.
        Il ne roule que si l'agitateur est au garage manivelle en haut, ou au dosage manivelle en
        bas."""
        return self.regles.refus_chariot(self._position(), self._bouge())

    def refus_demi_tour(self) -> str | None:
        """Pour le porte-bocal : pourquoi le demi-tour du bocal est interdit, ou None."""
        pose = self._position()
        if pose is None:
            return "position de l'agitateur du mycélium inconnue"
        return self.regles.refus_demi_tour(pose, self.chariot.etat())

    def camera_peut_pivoter(self) -> bool:
        """Pour la caméra du dosage : elle ne pivote vers le seau qu'agitateur garé."""
        return not self._bouge() and self.regles.camera_peut_pivoter(self._position())

    def x_agitateur(self) -> float | None:
        """Pour la préhension : position de l'agitateur sur sa glissière (son bocal est là, en
        x), None si elle est inconnue ou s'il bouge (toute la glissière est alors interdite)."""
        pose = self._position()
        return None if self._bouge() or pose is None else pose.x

    def manivelle_en_bas(self) -> bool:
        """Pour la préhension : manivelle en bas, agitateur arrêté."""
        pose = self._position()
        return not self._bouge() and pose is not None and self.regles.en_bas(pose)

    def dosage_en_cours(self) -> bool:
        """Pour la griffe : l'agitateur a quitté son garage (zone du dosage interdite)."""
        pose = self._position()
        return self._bouge() or pose is None or not self.regles.au_garage(pose)

    # ------------------------------------------------------------ conditions des étapes

    def couche_ou_fin(self) -> bool:
        return bool(self._demandes) or self._termine

    def au_garage(self) -> bool:
        """Agitateur au garage, manivelle en haut, bocal debout."""
        pose = self.agitateur.position()
        return (
            self.regles.au_garage(pose) and self.regles.en_haut(pose) and not self.plan.tete_en_bas
        )

    def pret_pour_le_seau(self) -> bool:
        """Agitateur au dosage, manivelle en bas, bocal tête en bas."""
        pose = self.agitateur.position()
        return self.regles.au_dosage(pose) and self.regles.en_bas(pose) and self.plan.tete_en_bas

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
        """Pendant que l'agitateur roule, le chariot de remplissage reste écarté."""
        pas = self._pas
        if self._geste is None or pas is None or pas.x is None:
            return True
        return self.chariot_ecarte()

    # ------------------------------------------------------------ actions des étapes

    def ecarter_le_chariot(self) -> None:
        self.chariot.ecarter()

    def amener_le_seau(self) -> None:
        assert self.demande is not None
        self.chariot.amener_au_dosage(self.regles.plateau_dosage(self.format))

    def changer_de_bocal(self) -> None:
        demande = self.demande
        assert demande is not None
        bocal = self._nouveau_bocal(demande.variete)
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

    def _envoyer(self, pas: Pas) -> None:
        self._pas = pas
        self._depuis = self._horloge()
        chariot = self.chariot.etat()
        if pas.origine:
            # Seule la glissière est connue : la manivelle tourne-t-elle à cet endroit ?
            pose = PoseAgitateur(x=self.agitateur.glissiere_x(), angle=math.nan)
            refus = self.regles.refus_manivelle(pose, chariot)
            if refus is not None:
                raise ErreurEtape(f"mycélium, « {pas.texte} » refusé : {refus}", QUOI_FAIRE)
            journal.info("Mycélium : %s", pas.texte)
            self.agitateur.executer(pas, None)
            return
        assert self.pose is not None
        if pas.porte_bocal in ("tete_en_bas", "debout"):
            refus = self.regles.refus_demi_tour(self.pose, chariot)
            if refus is not None:
                raise ErreurEtape(f"« {pas.texte} » refusé : {refus}", QUOI_FAIRE)
            if pas.porte_bocal == "tete_en_bas":
                self.porte_bocal.retourner_tete_en_bas()
            else:
                self.porte_bocal.remettre_debout()
            return
        if pas.porte_bocal is not None:
            if not self.regles.au_garage(self.pose):
                raise ErreurEtape(f"« {pas.texte} » refusé : l'agitateur n'est pas au garage")
            if pas.porte_bocal == "ouvrir":
                self.porte_bocal.ouvrir_mors()
            else:
                self.porte_bocal.serrer_bocal()
            return
        cible = self.pose.avec(
            **{
                nom: valeur
                for nom, valeur in (("x", pas.x), ("angle", pas.angle))
                if valeur is not None
            }
        )
        if pas.x is not None and abs(cible.x - self.pose.x) > 1e-6:
            refus = self.regles.refus_glissiere(self.pose, cible.x, chariot)
        else:
            refus = self.regles.refus_manivelle(self.pose, chariot)
        if refus is not None:
            raise ErreurEtape(f"mycélium, « {pas.texte} » refusé : {refus}", QUOI_FAIRE)
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
            if pas.porte_bocal is not None:
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

    def _glissiere(self, x: float, texte: str) -> Geste:
        """Rouler jusqu'à x, toujours manivelle en haut."""
        assert self.pose is not None
        if abs(self.pose.x - x) <= self.reglages.tolerance_x_m:
            return
        yield from self._manivelle(bas=False)
        yield Pas(texte, x=x)

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
        """Prise d'origine de la manivelle (faite par `lancer` si elle n'est pas connue), puis
        manivelle en haut."""
        yield from self._manivelle(bas=False)

    def geste_changer_de_bocal(self) -> Geste:
        """Mors ouverts (l'ancien bocal est repris), bocal neuf posé, serré."""
        yield Pas("mors ouverts", porte_bocal="ouvrir")
        self.changer_de_bocal()
        yield Pas("bocal serré", porte_bocal="serrer")

    def _demi_tour(self, porte_bocal: Literal["tete_en_bas", "debout"], texte: str) -> Geste:
        """Au demi-tour, toujours manivelle en bas ; la manivelle remonte ensuite."""
        yield from self._glissiere(self.reglages.demi_tour_x, "rouler jusqu'au demi-tour")
        yield from self._manivelle(bas=True)
        yield Pas(texte, porte_bocal=porte_bocal)
        yield from self._manivelle(bas=False)

    def geste_aller_doser(self) -> Geste:
        """Du garage au dosage : demi-tour du bocal tête en bas, puis manivelle en bas."""
        if not self.plan.tete_en_bas:
            yield from self._demi_tour("tete_en_bas", "bocal tête en bas")
        yield from self._glissiere(self.reglages.dosage_x, "rouler jusqu'au dosage")
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
        """Manivelle en haut, retour au demi-tour, bocal remis debout, retour au garage."""
        if self.plan.tete_en_bas:
            yield from self._demi_tour("debout", "bocal remis debout")
        yield from self._glissiere(self.reglages.garage_x, "rouler jusqu'au garage")
        yield from self._manivelle(bas=False)

    # ------------------------------------------------------------ registre

    def _noter_dose(self, demande: Demande, kg: float) -> None:
        bocal = self.plan.bocal
        assert bocal is not None
        self.doses.append(Dose(demande.seau, demande.couche, bocal.code, bocal.variete, kg))
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
        demande = self.demande
        if demande is None:
            return "fin"
        return "changer_de_bocal" if self._besoin_d_un_bocal(demande) else "ecarter_le_chariot"

    def apres_bocal(self) -> str:
        return "ecarter_le_chariot"

    def apres_ecart(self) -> str | None:
        """Le chariot est écarté : une nouvelle couche commence (son poids de départ aussi)."""
        demande = self.demande
        assert demande is not None
        plan = self.plan
        if demande.seau not in plan.seaux_du_bocal:
            plan.seaux_du_bocal.append(demande.seau)
            plan.format_du_bocal = demande.format
        plan.poids_depart_kg = None
        return None

    def apres_agitation(self) -> str | None:
        """La dose est versée : la griffe peut reprendre le seau."""
        self._demandes.popleft()
        self.plan.poids_depart_kg = None
        return None

    def apres_retour(self) -> str:
        return "attendre_une_couche"
