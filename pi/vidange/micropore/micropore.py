"""Le Micropore, côté Pi (module gelé le 28/10/2026 ; tâche 40) : un morceau de ruban de 30 mm sur
chaque trou du seau, posé comme par une étiqueteuse.

    micropore = Micropore(reglages.machine, tete, avance, vision, appris, registre, donnees / ...)
    micropore.brancher(remplissage)     # le Remplissage joue ses gestes au poste et au vidage

La tête est sur le chariot de remplissage ; c'est le plateau du chariot qui monte et tourne le
seau. Les gestes du micropore sont donc des pas du Remplissage (`brancher`) :
- au poste (y 0,135, après le spray, avant le dosage du mycélium), au premier passage du seau :
  les rangées qui ne sont pas « du fond » ;
- au vidage (y 0,42), quand la balance voit assez de substrat dans le seau (≈ 4 kg, pour que le
  seau ne glisse pas sous l'appui) : la rangée du fond. Elle ne peut pas se poser au poste : son
  plateau mettrait le bord du seau au-dessus de 0,68 (règle C2).
Pour chaque rangée : 0) tour de repérage devant la caméra, plateau à « z de l'objectif − hauteur de
la rangée » (la caméra est fixe et ne voit qu'une rangée à la fois : les trous de cette rangée et
leur angle sur le plateau, attaches de l'anse) ; 1) tête escamotée, VUE au ToF (sinon le plateau
ne bouge pas : règle du Remplissage) ; 2) plateau à ruban_z − hauteur de la rangée (jamais
au-dessus de 0,575 ; au poste, bord ≤ 0,68 : sinon la rangée n'est pas posée, alerte) ;
3) approche. Pour chaque trou :
4) le trou amené 15 mm avant le rouleau (angle du trou vu par la caméra + angle caméra → rouleau
appris) ; 5) avance de 13 mm ; 6) appui, contact vu au ToF (sinon : la tête recule, plus de pose
sur ce seau, alerte) ; 7) pose de 17 mm, le ruban suit la paroi ; 8) tension ; 9) coupe ;
10) fin de pose (13 mm) ; 11) la tête recule de 2 mm, le morceau passe devant la caméra : trou
découvert ⇒ un nouvel essai, puis alerte et seau « micropore à vérifier ». 13) Tête escamotée.

La carte du plateau redémarre (compteur de démarrages changé) : la tête renvoie les angles ; les
servos ont pu se relâcher, donc le morceau en cours est refait depuis l'escamotage, ToF relu.

Les angles des gestes sont appris (vidange.micropore.appris), jamais dans le code. Rien de propre
au micropore n'est une sécurité : ces verrous protègent la tête et le seau.
"""

import json
import math
import os
import threading
import time
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from vidange.chef import ErreurEtape
from vidange.journal import donner_journal
from vidange.materiel import ErreurMateriel
from vidange.micropore.appris import FichierAppris
from vidange.micropore.avance import AvanceRuban
from vidange.micropore.tete import TeteMicropore
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import FormatAppris, Machine, RangeeMicropore
from vidange.remplissage.chariot import Pas, Resultat
from vidange.vision.qr import marquer_a_verifier

if TYPE_CHECKING:
    from vidange.remplissage.remplissage import Remplissage, SeauPlateau

journal = donner_journal("micropore")

MODULE = "micropore"
Geste = Generator[Pas, Resultat, None]
Issue = Literal["couvert", "decouvert", "sans_contact", "redemarrage"]

QUOI_FAIRE = (
    "Regarder le seau à la caméra du micropore : le marquer « micropore fait » au registre après "
    "avoir posé le morceau à la main, ou le laisser « à vérifier ». Le cycle continue."
)
QUOI_FAIRE_TETE = (
    "La tête du micropore n'est pas vue escamotée par son capteur de distance : regarder la tête "
    "(bloquée, servo débranché, capteur sale ou mal visé ?). Corriger, puis acquitter et donner "
    "le Go : le plateau ne bouge pas avant."
)
QUOI_FAIRE_APPRIS = (
    "Les gestes du micropore ne sont pas appris : faire « vidange-micropore escamote » puis "
    "« vidange-micropore apprendre <format> » (pi/systeme/essai-micropore.md)."
)
QUOI_FAIRE_ROULEAU = (
    "Changer le rouleau de micropore entre deux fûts (bouton « rouleau », puis « charger »), et le "
    "morceau de lame."
)

_EGAL = 1e-6


@dataclass(frozen=True)
class Reperage:
    """Ce que la caméra a vu pendant le tour de repérage."""

    code: str | None
    # Diamètre du bord du seau (m) ; None : pas mesuré.
    diametre_bord_m: float | None
    # Par rangée (rang dans machine.yaml → micropore → formats → rangees) : angles du plateau (°)
    # où chaque trou est au centre de la caméra.
    trous: dict[int, list[float]]
    # Angles du plateau (°) des attaches de l'anse, au premier passage.
    attaches_deg: list[float] = field(default_factory=list)


class VisionMicropore(Protocol):
    """Ce que le micropore demande à sa caméra (vidange.vision.inspection, tâche 40 ter)."""

    def plateau_z_repere(self, hauteur_rangee_m: float) -> float:
        """Hauteur du plateau pour que la caméra (fixe) voie la rangée de trous à cette hauteur
        sur le seau."""
        ...

    def commencer_tour(self) -> None:
        """Le plateau va faire un tour devant une rangée : regarder pendant le tour."""
        ...

    def finir_tour(self, rangee: int) -> Reperage | None:
        """Le tour est fini : ce qui a été vu de la rangée n° `rangee` (None : rien de lisible)."""
        ...

    def controler_morceau(self, rangee: int, angle_deg: float) -> bool | None:
        """Le morceau posé sur ce trou est devant la caméra : True couvert, False découvert, de
        travers ou mal coupé, None : photo ratée."""
        ...


@dataclass
class SuiviSeau:
    """Le micropore d'un seau, du tour de repérage au rangement."""

    seau: "SeauPlateau"
    reperage: Reperage | None = None
    # (rangée, trou) couverts, vus à la caméra.
    faits: set[tuple[int, int]] = field(default_factory=set)
    # Rangées traitées (posées, ou laissées avec une alerte).
    rangees_finies: set[int] = field(default_factory=set)
    au_poste_fait: bool = False
    # Plus de pose sur ce seau (format inconnu, pas de contact...).
    abandon: bool = False
    morceaux: int = 0
    problemes: list[str] = field(default_factory=list)


class Micropore:
    def __init__(
        self,
        machine: Machine,
        tete: TeteMicropore,
        avance: AvanceRuban,
        vision: VisionMicropore,
        appris: FichierAppris,
        registre: Registre | None = None,
        fichier_etat: Path | None = None,
        horloge=time.monotonic,
    ) -> None:
        assert machine.micropore is not None and machine.remplissage is not None
        assert machine.griffe is not None
        self.reglages = machine.micropore
        self.formats_seaux = machine.griffe.formats
        self.course_z = machine.axes["plateau_z"].course
        self.poste_bord_max_z = machine.remplissage.verrous.poste_bord_max_z
        self.tete = tete
        self.avance = avance
        self.vision = vision
        self.appris = appris
        self.registre = registre
        self.fichier_etat = fichier_etat
        self._horloge = horloge
        self._verrou = threading.Lock()
        self.remplissage: Remplissage | None = None
        self.suivi: SuiviSeau | None = None
        self.messages: list[str] = []
        self.morceaux_restants = self.reglages.rouleau.morceaux
        self._alerte_rouleau_faite = False
        self._lire_etat()

    # ------------------------------------------------------------ branchements

    def brancher(self, remplissage: "Remplissage") -> None:
        """Le Remplissage ne bouge son plateau que tête vue escamotée, et joue les gestes du
        micropore au poste et au vidage."""
        self.remplissage = remplissage
        remplissage.brancher_micropore(
            escamotee=self.escamotee,
            au_poste=self.geste_au_poste,
            au_vidage=self.geste_au_vidage,
            fin_du_seau=self.fin_du_seau,
            arreter=self.arreter,
        )

    def escamotee(self) -> bool | None:
        return self.tete.escamotee()

    def arreter(self) -> None:
        """Arrêt du module : le ruban s'arrête, la tête recule (sans attendre)."""
        try:
            self.avance.arreter()
        except Exception as erreur:  # noqa: BLE001 : l'arrêt ne doit jamais lever
            journal.error("Micropore : arrêt de l'avance : %s", erreur)
        try:
            self.tete.escamoter()
        except (ErreurMateriel, ValueError) as erreur:
            journal.error("Micropore : tête pas escamotée à l'arrêt : %s", erreur)

    # ------------------------------------------------------------ les gestes (pour le Remplissage)

    def geste_au_poste(self) -> Geste:
        """Au poste, au premier passage du seau : tour de repérage, puis les rangées du haut."""
        suivi = self._suivi_du_seau()
        if suivi is None or suivi.au_poste_fait:
            return
        yield from self._escamoter()
        if not suivi.abandon and self._pret(suivi):
            for rang, rangee in enumerate(self._rangees(suivi)):
                if suivi.abandon:
                    break
                if not rangee.fond and rang not in suivi.rangees_finies:
                    yield from self._poser_rangee(suivi, rang, rangee, au_poste=True)
            yield from self._escamoter()
        suivi.au_poste_fait = True

    def geste_au_vidage(self) -> Geste:
        """Au vidage : la rangée du fond, quand il y a assez de substrat dans le seau."""
        suivi = self.suivi
        remplissage = self.remplissage
        assert remplissage is not None
        if suivi is None or remplissage.seau is not suivi.seau or not suivi.au_poste_fait:
            return
        if suivi.abandon:
            return
        restantes = [
            (rang, rangee)
            for rang, rangee in enumerate(self._rangees(suivi))
            if rangee.fond and rang not in suivi.rangees_finies
        ]
        if not restantes:
            return
        resultat = yield Pas("micropore : pesée (rangée du fond)", pesee=True)
        poids = None if resultat is None else resultat.poids_kg
        format = suivi.seau.format
        contenu = None if poids is None else poids - remplissage.poids_un_seau(format)
        seuil = self._seuil_fond(format)
        if contenu is None or contenu < seuil - _EGAL:
            journal.info(
                "Micropore : rangée du fond en attente (%s de substrat, %g kg attendus)",
                "pesée inconnue" if contenu is None else f"{contenu:.2f} kg",
                seuil,
            )
            return
        for rang, rangee in restantes:
            if suivi.abandon:
                break
            yield from self._poser_rangee(suivi, rang, rangee, au_poste=False)
        yield from self._escamoter()

    def fin_du_seau(self, seau: "SeauPlateau") -> None:
        """Le seau est rangé : rangées pas posées, morceaux au registre."""
        suivi = self.suivi
        if suivi is None or suivi.seau is not seau:
            return
        if not suivi.abandon:
            restantes = len(self._rangees(suivi)) - len(suivi.rangees_finies)
            if restantes > 0:
                seuil = self._seuil_fond(seau.format)
                self._probleme(
                    suivi,
                    f"{restantes} rangée(s) pas posée(s) (rangée du fond : jamais {seuil:g} kg de "
                    "substrat dans le seau)",
                )
        if self.registre is not None and seau.code is not None:
            try:
                self.registre.noter_mesure(
                    "micropore_morceaux",
                    suivi.morceaux,
                    "morceaux",
                    capteur=self.reglages.camera,
                    cycle=seau.cycle,
                    seau=seau.code,
                )
            except ErreurRegistre as erreur:
                journal.error("Micropore : registre : %s", erreur)
        self.suivi = None

    # ------------------------------------------------------------ le rouleau

    def rouleau_charge(self) -> None:
        """Bouton « charger » (rouleau neuf passé, lame descendue une fois) : le compteur repart."""
        with self._verrou:
            self.morceaux_restants = self.reglages.rouleau.morceaux
            self._alerte_rouleau_faite = False
            self._sauver_etat()
        self._dire("rouleau neuf chargé : changer aussi le morceau de lame")

    def _compter_morceau(self, suivi: SuiviSeau) -> None:
        suivi.morceaux += 1
        with self._verrou:
            self.morceaux_restants -= 1
            alerte = (
                self.morceaux_restants < self.reglages.rouleau.alerte_sous
                and not self._alerte_rouleau_faite
            )
            if alerte:
                self._alerte_rouleau_faite = True
            self._sauver_etat()
        if alerte:
            self._dire(
                f"rouleau bientôt vide ({self.morceaux_restants} morceaux) : le changer entre deux "
                "fûts",
                alerte=True,
                quoi_faire=QUOI_FAIRE_ROULEAU,
            )

    def _lire_etat(self) -> None:
        if self.fichier_etat is None or not self.fichier_etat.exists():
            return
        try:
            donnees = json.loads(self.fichier_etat.read_text(encoding="utf-8"))
            self.morceaux_restants = int(donnees["morceaux_restants"])
            self._alerte_rouleau_faite = bool(donnees.get("alerte_rouleau_faite", False))
        except (OSError, ValueError, KeyError, TypeError) as erreur:
            journal.warning("Micropore : état illisible (%s) : compteur du rouleau inconnu", erreur)

    def _sauver_etat(self) -> None:
        if self.fichier_etat is None:
            return
        texte = json.dumps(
            {
                "morceaux_restants": self.morceaux_restants,
                "alerte_rouleau_faite": self._alerte_rouleau_faite,
            }
        )
        self.fichier_etat.parent.mkdir(parents=True, exist_ok=True)
        provisoire = self.fichier_etat.with_suffix(".provisoire")
        provisoire.write_text(texte, encoding="utf-8")
        os.replace(provisoire, self.fichier_etat)

    # ------------------------------------------------------------ morceaux de gestes

    def _suivi_du_seau(self) -> SuiviSeau | None:
        remplissage = self.remplissage
        assert remplissage is not None, "micropore pas branché au Remplissage"
        seau = remplissage.seau
        if seau is None:
            return None
        if self.suivi is None or self.suivi.seau is not seau:
            self.suivi = SuiviSeau(seau)
        return self.suivi

    def _rangees(self, suivi: SuiviSeau) -> list[RangeeMicropore]:
        format = self.reglages.formats.get(suivi.seau.format)
        return [] if format is None else format.rangees

    def _seuil_fond(self, format: str) -> float:
        reglage = self.reglages.formats.get(format)
        if reglage is not None and reglage.fond_poids_min_kg is not None:
            return reglage.fond_poids_min_kg
        return self.reglages.fond_poids_min_kg

    def _appris(self, suivi: SuiviSeau) -> FormatAppris:
        appris = self.appris.format(suivi.seau.format)
        assert appris is not None
        return appris

    def _pret(self, suivi: SuiviSeau) -> bool:
        """Format connu et appris, bord accepté, rouleau pas vide ; sinon alerte, pas de pose."""
        format = suivi.seau.format
        probleme = None
        if format not in self.reglages.formats:
            probleme = f"format « {format} » inconnu du micropore : rempli sans micropore"
        elif self.appris.format(format) is None:
            probleme = f"format « {format} » pas appris : rempli sans micropore"
        elif 2 * self.formats_seaux[format].rayon_haut > self.reglages.bord_diametre_max_m + _EGAL:
            probleme = (
                f"bord du seau de Ø {2 * self.formats_seaux[format].rayon_haut * 100:g} cm (au "
                f"plus {self.reglages.bord_diametre_max_m * 100:g}) : pas de pose"
            )
        elif self.morceaux_restants <= 0:
            probleme = "rouleau vide (compteur à 0) : rempli sans micropore"
        if probleme is None:
            return True
        self._abandonner(suivi, probleme)
        return False

    def _abandonner(self, suivi: SuiviSeau, message: str) -> None:
        suivi.abandon = True
        self._probleme(suivi, message)

    def _probleme(self, suivi: SuiviSeau, message: str) -> None:
        code = suivi.seau.code
        suivi.problemes.append(message)
        self._dire(f"seau {code or '?'} : {message}", alerte=True)
        if code is not None:
            marquer_a_verifier(self.registre, "seau", code, f"micropore à vérifier : {message}")

    def _dire(self, message: str, alerte: bool = False, quoi_faire: str = QUOI_FAIRE) -> None:
        if alerte:
            journal.warning("Micropore : %s", message)
        else:
            journal.info("Micropore : %s", message)
        self.messages.append(message)
        del self.messages[:-50]
        if alerte and self.registre is not None:
            try:
                self.registre.noter_alarme(MODULE, message, quoi_faire)
            except ErreurRegistre as erreur:
                journal.error("Micropore : registre : %s", erreur)

    def _pose(self):
        assert self.remplissage is not None and self.remplissage.pose is not None
        return self.remplissage.pose

    def _attendre(self, texte: str, secondes: float) -> Pas:
        return Pas(texte, attente_s=secondes)

    def _escamoter(self) -> Geste:
        """Tête escamotée, lame au repos, VUE au ToF ; sinon alarme : le plateau ne bouge pas."""
        escamote = self.appris.escamote_deg
        if escamote is None:
            raise ErreurEtape("micropore : angle « escamoté » pas appris", QUOI_FAIRE_APPRIS)
        servos = self.reglages.servos
        tete = self.tete
        deja = (
            tete.angles.get(tete.voie_escamotage) == escamote
            and tete.angles.get(tete.voie_lame) == servos.lame_repos_deg
        )
        try:
            if not deja:
                tete.escamoter()
        except ErreurMateriel as erreur:
            raise ErreurEtape(
                f"micropore : servos pas commandés ({erreur})", QUOI_FAIRE_TETE
            ) from erreur
        if not deja:
            yield self._attendre("micropore 1) : tête escamotée", servos.mouvement_s)
        debut = self._horloge()
        while True:
            try:
                tete.lire()
            except ErreurMateriel:
                pass
            if tete.escamotee() is True:
                return
            if self._horloge() - debut >= servos.attente_max_s - _EGAL:
                distance = tete.distance_mm()
                lu = "pas de mesure" if distance is None else f"{distance:g} mm"
                raise ErreurEtape(
                    f"micropore : tête pas vue escamotée au ToF ({lu} ; au moins "
                    f"{self.reglages.tof.escamotee_mm - self.reglages.tof.tolerance_escamotee_mm:g}"
                    " mm attendus) : le plateau ne bouge pas",
                    QUOI_FAIRE_TETE,
                )
            yield self._attendre("micropore : ToF relu (tête escamotée ?)", 0.2)

    def _servo(self, angle: float, texte: str) -> Geste:
        try:
            self.tete.commander(escamotage=angle)
        except ErreurMateriel as erreur:
            raise ErreurEtape(
                f"micropore : servo pas commandé ({erreur})", QUOI_FAIRE_TETE
            ) from erreur
        yield self._attendre(texte, self.reglages.servos.mouvement_s)

    def _distance(self) -> Generator[Pas, Resultat, float | None]:
        """La distance du ToF lue après le dernier ordre (on attend qu'elle compte, au plus
        attente_max_s) ; None : pas de bonne mesure."""
        debut = self._horloge()
        while True:
            try:
                self.tete.lire()
            except ErreurMateriel:
                pass
            distance = self.tete.distance_mm()
            if distance is not None:
                return distance
            if self._horloge() - debut >= self.reglages.servos.attente_max_s - _EGAL:
                return None
            yield self._attendre("micropore : ToF relu", 0.05)

    def _avancer(self, mm: float, vitesse: float, texte: str) -> Geste:
        self.avance.avancer(mm, vitesse)
        yield self._attendre(texte, abs(mm) / vitesse)
        yield from self._fin_avance(texte)

    def _fin_avance(self, texte: str) -> Geste:
        debut = self._horloge()
        while not self.avance.fini():
            if self._horloge() - debut > self.reglages.servos.attente_max_s:
                raise ErreurEtape(f"micropore : « {texte} » pas fini (moteur d'avance)")
            yield self._attendre(f"{texte} (attente du moteur d'avance)", 0.05)

    def _tourner(self, cible: float, texte: str, vitesse_a: float | None = None) -> Pas:
        return Pas(texte, {"a": cible}, vitesse_a=vitesse_a)

    def _degres(self, mm: float, rangee: RangeeMicropore) -> float:
        """Rotation du plateau (°) pour que la paroi de cette rangée avance de tant de mm."""
        return math.degrees(mm / (rangee.rayon_paroi_m * 1000))

    def _proche(self, cible: float) -> float:
        actuel = self._pose().a
        return actuel + (cible - actuel + 180) % 360 - 180

    def _angle_mm(self, appris: FormatAppris, mm: float) -> float:
        """L'angle du servo qui recule la tête de tant de mm depuis le contact."""
        servos = self.reglages.servos
        return appris.contact_deg - servos.sens_avance * mm / servos.mm_par_degre

    def _refus_hauteur(self, z: float, hauteur_seau: float, au_poste: bool) -> str | None:
        """Pourquoi le plateau ne peut pas être à cette hauteur (règle 9 ; règle C2 au poste)."""
        bas, plafond = self.course_z
        if z > plafond + _EGAL:
            return f"plateau à {z:.3f} m, au plus {plafond:g} (règle 9)"
        if z < bas - _EGAL:
            return f"plateau à {z:.3f} m, sous sa course"
        if au_poste and z + hauteur_seau > self.poste_bord_max_z + _EGAL:
            return (
                f"au poste, le bord du seau serait à {z + hauteur_seau:.3f} m (au plus "
                f"{self.poste_bord_max_z:g}, règle C2)"
            )
        return None

    def _tour(self, suivi: SuiviSeau, rang: int, rangee: RangeeMicropore) -> Geste:
        """0) Tour de repérage devant la caméra, plateau à la hauteur de cette rangée : ses trous
        et leur angle, les attaches de l'anse. Trou introuvable : la rangée n'est pas posée."""
        sens = self.reglages.pose.sens_rotation
        self.vision.commencer_tour()
        try:
            yield self._tourner(
                self._pose().a + sens * 360, f"micropore 0) : tour de repérage, rangée {rang + 1}"
            )
        finally:
            reperage = self.vision.finir_tour(rang)
        seau = suivi.seau
        if reperage is None:
            suivi.rangees_finies.add(rang)
            self._probleme(
                suivi, f"rangée {rang + 1} : rien lu au tour de repérage (trous) : pas posée"
            )
            return
        if seau.code is not None and reperage.code is not None and reperage.code != seau.code:
            self._abandonner(
                suivi, f"QR lu {reperage.code} au tour de repérage, seau attendu : pas de pose"
            )
            return
        bord = reperage.diametre_bord_m
        if bord is not None and bord > self.reglages.bord_diametre_max_m + _EGAL:
            self._abandonner(suivi, f"bord du seau vu à Ø {bord * 100:.1f} cm : pas de pose")
            return
        if suivi.reperage is None:
            suivi.reperage = reperage
        else:
            suivi.reperage.trous.update(reperage.trous)
            suivi.reperage.attaches_deg.extend(reperage.attaches_deg)
        vus = len(reperage.trous.get(rang, []))
        if vus < rangee.trous:
            self._probleme(
                suivi,
                f"rangée {rang + 1} : {vus} trou(s) vu(s) sur {rangee.trous} : pose seulement "
                "sur les trous vus",
            )

    def _poser_rangee(
        self, suivi: SuiviSeau, rang: int, rangee: RangeeMicropore, au_poste: bool
    ) -> Geste:
        hauteur_seau = self.formats_seaux[suivi.seau.format].hauteur
        assert hauteur_seau is not None
        z = self.reglages.ruban_z - rangee.hauteur_m
        refus = self._refus_hauteur(z, hauteur_seau, au_poste)
        if refus is not None:
            refus = f"rangée {rang + 1} : {refus} : pas posée"
        if refus is not None:
            suivi.rangees_finies.add(rang)
            self._probleme(suivi, refus)
            return
        appris = self._appris(suivi)
        yield from self._escamoter()
        # 0) Tour de repérage de CETTE rangée, juste avant sa pose, à la même station.
        z_tour = self.vision.plateau_z_repere(rangee.hauteur_m)
        refus = self._refus_hauteur(z_tour, hauteur_seau, au_poste)
        if refus is not None:
            suivi.rangees_finies.add(rang)
            self._probleme(suivi, f"rangée {rang + 1}, tour de repérage : {refus} : pas posée")
            return
        if abs(self._pose().z - z_tour) > _EGAL:
            yield Pas(f"micropore 0) : plateau au repérage de la rangée {rang + 1}", {"z": z_tour})
        yield from self._tour(suivi, rang, rangee)
        if suivi.abandon or rang in suivi.rangees_finies:
            yield from self._escamoter()
            return
        if abs(self._pose().z - z) > _EGAL:
            yield Pas(f"micropore 2) : plateau à la rangée {rang + 1}", {"z": z})
        assert suivi.reperage is not None
        trous = list(enumerate(suivi.reperage.trous.get(rang, [])))
        nouveaux_essais = self.reglages.pose.nouveaux_essais
        for numero, angle in trous:
            if (rang, numero) in suivi.faits:
                continue
            essais = 0
            while True:
                if self.morceaux_restants <= 0:
                    self._abandonner(suivi, "rouleau vide (compteur à 0) : plus de pose")
                    break
                issue = yield from self._poser_morceau(suivi, rang, rangee, appris, angle)
                if issue == "couvert":
                    suivi.faits.add((rang, numero))
                    break
                if issue == "sans_contact":
                    self._abandonner(
                        suivi,
                        "pas de contact de la tête avec la paroi (pas de seau, seau mal placé ?) : "
                        "la tête recule, pas de pose",
                    )
                    break
                essais += 1
                if essais > nouveaux_essais:
                    quoi = "carte du plateau redémarrée" if issue == "redemarrage" else "découvert"
                    self._probleme(
                        suivi,
                        f"rangée {rang + 1}, trou {numero + 1} : {quoi} après {essais} essais",
                    )
                    break
                journal.warning(
                    "Micropore : rangée %d, trou %d : %s, nouvel essai",
                    rang + 1,
                    numero + 1,
                    "carte redémarrée" if issue == "redemarrage" else "trou découvert",
                )
                if issue == "redemarrage":
                    # Les servos ont pu se relâcher : on repart de la tête escamotée, ToF relu.
                    yield from self._escamoter()
            if suivi.abandon:
                break
        suivi.rangees_finies.add(rang)
        yield from self._escamoter()

    def _poser_morceau(
        self,
        suivi: SuiviSeau,
        rang: int,
        rangee: RangeeMicropore,
        appris: FormatAppris,
        angle: float,
    ) -> Generator[Pas, Resultat, Issue]:
        """Un morceau sur un trou (gestes 3 à 11). Rend ce que la caméra a vu, « sans_contact »
        ou « redemarrage » (la carte du plateau a redémarré pendant le morceau)."""
        pose, servos = self.reglages.pose, self.reglages.servos
        sens = pose.sens_rotation
        redemarrages = self.tete.redemarrages_vus

        def redemarree() -> bool:
            return self.tete.redemarrages_vus != redemarrages

        # 3) Approche : depuis la tête escamotée (début de rangée, après un redémarrage), vue au
        # ToF avant ; ou depuis le recul du contrôle du morceau d'avant.
        tete = self.tete
        actuel = tete.angles.get(tete.voie_escamotage)
        if actuel is None or actuel == self.appris.escamote_deg:
            yield from self._escamoter()
            yield from self._servo(appris.approche_deg, "micropore 3) : approche")
        elif actuel != appris.approche_deg:
            yield from self._servo(appris.approche_deg, "micropore 3) : approche")
        approche = yield from self._distance()
        if approche is None:
            raise ErreurEtape("micropore : pas de mesure du capteur de distance", QUOI_FAIRE_TETE)
        if redemarree():
            return "redemarrage"
        # 4) Le trou 15 mm avant le rouleau.
        cible = (
            angle
            + appris.camera_rouleau_deg
            - sens * self._degres(pose.trou_avant_rouleau_mm, rangee)
        )
        yield self._tourner(self._proche(cible), "micropore 4) : trou amené avant le rouleau")
        # 5) Avance du bout du ruban sous le rouleau.
        yield from self._avancer(
            pose.avance_mm, pose.vitesse_avance_mm_s, "micropore 5) : avance du ruban"
        )
        # 6) Appui : contact vu au ToF (la distance ne baisse plus que de 2 à 3 mm).
        yield from self._servo(appris.appui_deg, "micropore 6) : appui")
        appui = yield from self._distance()
        if redemarree():
            return "redemarrage"
        if appui is None or approche - appui > self.reglages.tof.contact_ecart_max_mm + _EGAL:
            journal.warning(
                "Micropore : pas de contact (ToF %s mm à l'approche, %s à l'appui)",
                f"{approche:g}",
                "?" if appui is None else f"{appui:g}",
            )
            yield from self._escamoter()
            return "sans_contact"
        # 7) Pose : la paroi tire le ruban, le moteur d'avance suit à la même vitesse.
        vitesse_a = self._degres(pose.vitesse_pose_mm_s, rangee)
        a = self._pose().a
        self.avance.avancer(pose.avant_coupe_mm, pose.vitesse_pose_mm_s)
        yield self._tourner(
            a + sens * self._degres(pose.avant_coupe_mm, rangee),
            f"micropore 7) : pose ({pose.avant_coupe_mm:g} mm)",
            vitesse_a,
        )
        yield from self._fin_avance("micropore 7) : pose")
        # 8) Tension : un petit cran en arrière.
        if pose.tension_mm > 0:
            yield from self._avancer(
                -pose.tension_mm, pose.vitesse_avance_mm_s, "micropore 8) : tension"
            )
        # 9) Coupe, plateau arrêté.
        try:
            tete.commander(lame=servos.lame_bas_deg)
            yield self._attendre("micropore 9) : coupe (lame en bas)", servos.lame_s)
            tete.commander(lame=servos.lame_repos_deg)
            yield self._attendre("micropore 9) : lame remontée", servos.lame_s)
        except ErreurMateriel as erreur:
            raise ErreurEtape(
                f"micropore : lame pas commandée ({erreur})", QUOI_FAIRE_TETE
            ) from erreur
        self._compter_morceau(suivi)
        # 10) Fin de pose : le ruban ne bouge pas, le reste du morceau passe sous le rouleau.
        a = self._pose().a
        yield self._tourner(
            a + sens * self._degres(pose.apres_coupe_mm, rangee),
            f"micropore 10) : fin de pose ({pose.apres_coupe_mm:g} mm)",
            vitesse_a,
        )
        # 11) Contrôle : la tête recule de 2 mm, le morceau passe devant la caméra.
        yield from self._servo(
            self._angle_mm(appris, pose.controle_recul_mm), "micropore 11) : la tête recule"
        )
        yield self._tourner(self._proche(angle), "micropore 11) : morceau devant la caméra")
        if redemarree():
            return "redemarrage"
        vu = self.vision.controler_morceau(rang, angle)
        return "couvert" if vu is True else "decouvert"

    # ------------------------------------------------------------ pour la page web

    def en_dict(self) -> dict[str, object]:
        suivi = self.suivi
        return {
            "tete": self.tete.en_dict(),
            "morceaux_restants": self.morceaux_restants,
            "seau": None if suivi is None else suivi.seau.code,
            "messages": list(self.messages[-10:]),
        }
