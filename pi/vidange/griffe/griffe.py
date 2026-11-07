"""La griffe : vider le fût dans les seaux, couche par couche (module gelé le 25/10/2026).

    griffe = Griffe(reglages.machine, bras, poste, registre)
    module = module_griffe(griffe)      # vidange/griffe/module.py
    chef.lancer(module)

Chaque étape du module lance un geste : une suite de pas (vidange.griffe.bras.Pas), écrite
comme dans la fiche. Le pas suivant part quand le précédent est fini ; chaque pas est vérifié
avant de partir (vidange.griffe.regles) : un pas refusé met le module en alarme, il ne bouge
pas. Un geste est rejouable : refait depuis le début (après une alarme et le Go), il part de
là où est la tête (remonter, aller au-dessus du fût ou du seau, descendre).

Une couche (godet unique) :
1. descente rapide jusqu'au dernier niveau connu + 3 cm, puis lente ; au contact (la charge
   baisse), arrêt, niveau noté ;
2. mâchouiller (pas pour le maïs) ; 3. prendre, en plongée ; 4. remonter, peser, ajuster
   (trop léger : reprendre à côté ; trop lourd : s'entrouvrir au-dessus du fût) ;
5. trajet vers le seau, tête bloquée ; 6. vidage en couronne ; 7. tassement (seau qui tourne) ;
8. essuyage du bord à la dernière couche ; 9. retour au fût.
Hygiène (règle de Karulium) : la griffe ne touche jamais une couche de mycélium découverte :
elle tasse juste après avoir vidé le substrat, avant le mycélium, et essuie le bord après la
dernière couche de substrat.

Passe de fond (quand la pesée du fût annonce les derniers kilos) : raclage de la paroi, prises en
appui au fond en spirale, prises le long de la paroi, chasse-neige, prises au centre ; puis le fût
est vide (« finir_vidange » au poste du fût).

Les modules pas encore écrits (Remplissage, Mycélium, Préhension, Vision) sont des cases vides :
ici, seulement des fonctions nommées (`seau_pret`, `tourner_seau`...) qu'ils fourniront.
"""

import math
import time
from collections.abc import Callable, Generator
from dataclasses import asdict, dataclass, field
from typing import Literal

from vidange.angles_gardes import AnglesGardes
from vidange.chef import ErreurEtape
from vidange.griffe.bras import Bras, G, Pas, Resultat
from vidange.griffe.doses import Doses, Lieu, Prise
from vidange.griffe.regles import Contexte, Pose, ReglesGriffe
from vidange.journal import donner_journal
from vidange.poste_fut import PosteFut
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import FormatSeau, Machine

journal = donner_journal("griffe")

Geste = Generator[Pas, Resultat, None]
# Une pesée à l'arrêt (versement dans un bocal) : des pas d'attente, puis la charge pendue (N).
Pesee = Generator[Pas, Resultat, float]
Sorte = Literal["raclage", "fond", "paroi", "chasse_neige", "centre"]

QUOI_FAIRE = (
    "Regarder la vidéo de la griffe : est-elle bloquée, le godet est-il plein de substrat collé ? "
    "Corriger, puis acquitter et donner le Go : le geste est refait depuis le début."
)
QUOI_FAIRE_DOSE = (
    "La griffe n'arrive pas à prendre la dose du bocal dans le fût : regarder la vidéo (maïs collé "
    "en bloc, fût presque vide ?). Corriger, puis acquitter et donner le Go : les prises "
    "recommencent."
)
# Écart sous lequel deux positions sont égales (m).
_EGAL = 1e-6


@dataclass(frozen=True)
class ActionFond:
    """Une action de la passe de fond."""

    sorte: Sorte
    x: float = 0.0
    y: float = 0.0
    # Orientation voulue de la tête (°), ou None : celle du moment.
    a: float | None = None


@dataclass(frozen=True)
class DoseDonnee:
    """Une dose donnée au lieu de celle d'une couche de seau (bocal de semence, maïs : sans
    mâchouiller ni s'entrouvrir). Hors de [min_kg, max_kg], la prise est rendue au fût et
    refaite à côté ; après `reprises_max` reprises, alerte. `peser` : la pesée à l'arrêt."""

    min_kg: float
    max_kg: float
    reprises_max: int
    peser: Callable[[], Pesee]


@dataclass(frozen=True)
class PrisePrevue:
    lieu: Lieu
    x: float
    y: float
    a: float | None
    poids_kg: float
    enfoncement_m: float
    bouchees: int
    ouverture_max: float
    # Contact (baisse de charge) et poussée maximale pendant la fermeture (N, None : pas de limite).
    contact_n: float
    poussee_n: float | None


@dataclass
class Plan:
    """Où en est la vidange du fût (pour la mémoire du chef aussi)."""

    format: str
    seaux_finis: int = 0
    couche: int = 1
    couche_kg: float = 0.0
    couche_tassee: bool = False
    seau_kg: float = 0.0
    # Substrat dans le godet, pesé (kg).
    godet_kg: float = 0.0
    # Dernier niveau connu : bas du godet au contact (m) ; fond trouvé au toucher.
    niveau_z: float | None = None
    fond_z: float | None = None
    # Prochain point de prise des couches.
    point: int = 0
    en_fond: bool = False
    fond: list[ActionFond] = field(default_factory=list)
    reprendre: bool = False
    reprises: int = 0
    vide: bool = False
    # La dose du godet a déjà été dite au poste du fût.
    dose_notee: bool = True


def _rad(angle: float) -> float:
    return math.radians(angle)


class Griffe:
    def __init__(
        self,
        machine: Machine,
        bras: Bras,
        poste: PosteFut,
        registre: Registre | None = None,
        horloge: Callable[[], float] = time.monotonic,
        # Cases vides des autres modules (valeurs pour le simulateur et les essais) :
        mode: Callable[[], str] = lambda: "production",
        porte_spray_ouverte: Callable[[], bool] = lambda: False,
        dosage_en_cours: Callable[[], bool] = lambda: False,
        camera_dosage_pivote: Callable[[], bool] = lambda: False,
        machouiller: Callable[[], bool] = lambda: True,
        prochain_format: Callable[[], str | None] = lambda: None,
        tourner_seau: Callable[[bool], object] = lambda tourne: None,
        couche_finie: Callable[[int], object] = lambda couche: None,
        seau_fini: Callable[[int], object] = lambda numero: None,
        prehension_face_z: Callable[[], float | None] = lambda: None,
        garde: AnglesGardes | None = None,
    ) -> None:
        """`machouiller` : faux pour le maïs. `prochain_format` : format du seau suivant (None :
        celui par défaut). `tourner_seau` : faire tourner le seau du poste de remplissage
        (Remplissage, pas figé). `couche_finie` : une couche de substrat est vidée et tassée,
        le mycélium peut être versé dessus (Mycélium). `seau_fini` : un seau est plein (numéro
        dans le fût). `camera_dosage_pivote` : la caméra du dosage pivote (Vision).
        `prehension_face_z` : face de la tête de préhension (même chariot, chaîne Z ; None :
        inconnue, comptée en haut). `garde` : la rotation de la tête y est notée à chaque arrêt
        (prise d'origine après une coupure)."""
        assert machine.griffe is not None and machine.poste_fut is not None
        self.reglages = machine.griffe
        self.fut = machine.poste_fut
        self.course_a = machine.axes["griffe_a"].course
        self.course_z = machine.axes["griffe_z"].course
        self.regles = ReglesGriffe(machine)
        self.doses = Doses(self.reglages)
        self.bras = bras
        self.poste = poste
        self.registre = registre
        self._horloge = horloge
        self._mode = mode
        self._porte_spray = porte_spray_ouverte
        self._dosage = dosage_en_cours
        self._camera_dosage_pivote = camera_dosage_pivote
        self._machouiller = machouiller
        self._prochain_format = prochain_format
        self.tourner_seau = tourner_seau
        self._couche_finie = couche_finie
        self._seau_fini = seau_fini
        self._prehension_face_z = prehension_face_z
        self.garde = garde
        self.plan = Plan(format=self.reglages.format_par_defaut)
        self.pose: Pose | None = None
        # Tare « godet vide » de la dernière prise d'une dose donnée (N), pesée à l'arrêt.
        self.tare_n: float | None = None
        # Dose donnée : on vise tant de fois le milieu de la plage (corrigé après chaque prise
        # pesée, tant que la densité du fût n'est pas apprise : la plage est étroite).
        self.correction_dose = 1.0
        self._geste: Geste | None = None
        self._pas: Pas | None = None
        self._depuis = 0.0
        self._points = self._points_des_couches()
        # Verrou du Stockage (Stockage.brancher_griffe, tâche 35) pour chaque pas : boucle du
        # tiroir fermée, mât à x ≤ 2,738. Raison du refus, ou None. Sans stockage : rien.
        self.verrou_stockage: Callable[[Pose, Pose], str | None] = lambda depart, arrivee: None
        # Verrou du chariot de remplissage (Remplissage.brancher_griffe, règle 14 : en mode
        # couvercles, la tête ne tourne que chariot à y ≥ 0,515). Sans remplissage : rien.
        self.verrou_chariot: Callable[[Pose, Pose], str | None] = lambda depart, arrivee: None
        # Verrou du pont partagé (vidange.cycle.griffe_du_lot, tâche 45 sexies) : un pas qui
        # bouge le pont ou le chariot Y traîne aussi la tête de préhension (même chariot) ; ses
        # règles à elle sont vérifiées. Sans préhension branchée : rien.
        self.verrou_pont: Callable[[Pose, Pose], str | None] = lambda depart, arrivee: None
        # Verrou de la zone du bras du spray (vidange.spray.zone, tâche 45 octies) : tant que le
        # bras n'est pas vu rangé, un pas qui entrerait dans sa zone ATTEND (raison, ou None), au
        # plus attente_spray_max_s, puis alarme. Sans spray : rien.
        self.verrou_spray: Callable[[Pose, Pose], str | None] = lambda depart, arrivee: None
        self.attente_spray_max_s = 0.0
        self._attente_spray: str | None = None
        self._attente_depuis = 0.0
        self._en_pause = False
        self._pause_depuis = 0.0

    # ------------------------------------------------------------ état

    def contexte(self) -> Contexte:
        mode = self._mode()
        return Contexte(
            mode=mode,
            volet_releve=self.poste.volet_considere_releve(mode),
            porte_spray_ouverte=self._porte_spray(),
            dosage_en_cours=self._dosage(),
            camera_dosage_pivote=self._camera_dosage_pivote(),
            prehension_face_z=self._prehension_face_z(),
        )

    def occupee(self) -> bool:
        """Un geste est en cours (pont partagé avec la préhension, tâche 45 sexies)."""
        return self._geste is not None

    def trajet_en_cours(self) -> tuple[Pose, Pose] | None:
        """(départ, cible) du pas qui bouge la tête en ce moment ; None sans pas parti (un pas qui
        attend le bras du spray n'est pas parti)."""
        pas, pose = self._pas, self.pose
        if self._geste is None or pas is None or pose is None or not pas.cibles:
            return None
        if self._attente_spray is not None:
            return None
        return pose, pose.avec(**pas.cibles)

    def tete_tourne(self) -> bool:
        """Un pas en cours fait tourner la tête (règle 14 du chariot de remplissage)."""
        pas = self._pas
        return self._geste is not None and pas is not None and "a" in pas.cibles

    def hors_du_fut(self) -> bool:
        """Pour la pesée du fût : elle n'est lue que si la griffe n'est pas dans le fût."""
        pose = self.pose
        return pose is None or not self.regles.dans_le_fut(pose)

    def hors_boite_camera_dosage(self) -> bool:
        """Pour le verrou de la caméra du dosage : elle ne pivote que si la tête est hors de sa
        boîte (position inconnue : non)."""
        pose = self.pose
        return pose is not None and not self.regles.dans_boite_camera_dosage(pose)

    @property
    def format(self) -> FormatSeau:
        return self.reglages.formats[self.plan.format]

    @property
    def derniere_couche(self) -> bool:
        return self.plan.couche >= self.format.couches

    def memoire(self) -> dict:
        """L'état de la vidange, à noter dans le carnet du chef (reprise après coupure)."""
        return asdict(self.plan)

    def retrouver(self, memoire: dict) -> None:
        fond = [ActionFond(**action) for action in memoire.get("fond", [])]
        self.plan = Plan(**{**memoire, "fond": fond})

    # ------------------------------------------------------------ déroulé d'un geste

    def lancer(self, geste: Callable[[], Geste]) -> None:
        """Action d'une étape : le geste part depuis là où est la tête."""
        self.pose = self.bras.position()
        self._geste = geste()
        self._pas = None
        self._suivant(None)

    def _suivant(self, resultat: Resultat | None) -> None:
        assert self._geste is not None
        try:
            pas = next(self._geste) if resultat is None else self._geste.send(resultat)
        except StopIteration:
            self._geste = self._pas = None
            return
        self._envoyer(pas)

    def _envoyer(self, pas: Pas) -> None:
        assert self.pose is not None
        self._pas = pas
        self._depuis = self._horloge()
        if not pas.cibles:
            return
        cible = self.pose.avec(**pas.cibles)
        refus = self.regles.refus_mouvement(self.pose, cible, self.contexte())
        if refus is None:
            refus = self.verrou_stockage(self.pose, cible)
        if refus is None:
            refus = self.verrou_chariot(self.pose, cible)
        if refus is None:
            refus = self.verrou_pont(self.pose, cible)
        if refus is not None:
            raise ErreurEtape(f"griffe, « {pas.texte} » refusé : {refus}", QUOI_FAIRE)
        attente = self.verrou_spray(self.pose, cible)
        if attente is not None:
            # Le bras du spray bouge : le pas attend (geste_fini le relance).
            if self._attente_spray is None:
                self._attente_depuis = self._horloge()
                journal.info("Griffe : « %s » attend : %s", pas.texte, attente)
            self._attente_spray = attente
            return
        self._attente_spray = None
        journal.debug("Griffe : %s", pas.texte)
        if self.garde is not None and "a" in pas.cibles:
            self.garde.noter("griffe_a", self.pose.a, en_rotation=True)
        self.bras.executer(pas, cible)

    def geste_fini(self) -> bool:
        """Condition de fin des étapes : fait partir les pas l'un après l'autre."""
        while self._geste is not None:
            pas = self._pas
            assert pas is not None and self.pose is not None
            if self._attente_spray is not None:
                if self._en_pause:
                    return False
                if self._horloge() - self._attente_depuis > self.attente_spray_max_s:
                    raison, self._attente_spray = self._attente_spray, None
                    self._geste = self._pas = None
                    raise ErreurEtape(
                        f"griffe, « {pas.texte} » : attend depuis plus de "
                        f"{self.attente_spray_max_s:g} s : {raison}",
                        QUOI_FAIRE,
                    )
                self._envoyer(pas)
                if self._attente_spray is not None:
                    return False
                continue
            if not pas.cibles:
                if pas.jusqu_a is not None and not pas.jusqu_a():
                    return False
                if self._horloge() - self._depuis < pas.attente_s:
                    return False
                resultat = Resultat(pose=self.pose)
            else:
                if not self.bras.fini():
                    return False
                resultat = self.bras.resultat()
                self.pose = resultat.pose
                if self.garde is not None:
                    self.garde.noter("griffe_a", self.pose.a)
            self._suivant(resultat)
        return True

    def pauser(self) -> None:
        if not self._en_pause:
            self._en_pause = True
            self._pause_depuis = self._horloge()
        self.bras.pauser()

    def reprendre(self) -> None:
        # Le temps de la pause ne compte pas dans l'attente du bras du spray.
        if self._en_pause and self._attente_spray is not None:
            self._attente_depuis += self._horloge() - self._pause_depuis
        self._en_pause = False
        self.bras.reprendre()

    def arreter(self) -> None:
        """Alarme : le mouvement s'arrête. Si le plateau du fût n'est plus vu, le pont se retire
        hors de la zone du plateau (en remontant d'abord)."""
        self._geste = self._pas = None
        self._attente_spray = None
        self.bras.arreter()
        if self.poste.etat().plateau is True:
            return
        try:
            depart = self.bras.position()
            poses = self._retrait(depart)
            precedente = depart
            for pose in poses:
                refus = self.regles.refus_mouvement(precedente, pose, self.contexte())
                if refus is not None:
                    journal.error("Griffe : retrait hors de la zone du plateau refusé : %s", refus)
                    return
                precedente = pose
            journal.warning("Griffe : plateau du fût plus vu, le pont sort de sa zone")
            self.bras.enchainer(poses, None)
            self.pose = poses[-1] if poses else depart
        except ErreurEtape as erreur:
            journal.error("Griffe : retrait impossible : %s", erreur)

    def _retrait(self, depart: Pose) -> list[Pose]:
        poses = []
        pose = depart
        for valeurs in self._vers_le_haut(pose):
            pose = pose.avec(**valeurs)
            poses.append(pose)
        x, y = self.reglages.attente
        for px, py in self._chemin(pose, x, y):
            pose = pose.avec(x=px, y=py)
            poses.append(pose)
        return poses

    # ------------------------------------------------------------ morceaux de gestes

    def _orientation_bloquee(self, a: float) -> float:
        """L'orientation bloquée (bras le long du pont) la plus proche, dans la course de A."""
        return self._angle_proche(a, self.reglages.rotation.orientations_bloquees_deg)

    def _angle_proche(self, actuel: float, cibles: tuple[float, ...] | list[float]) -> float:
        """L'angle le plus proche de `actuel` parmi les cibles (à 360° près), de préférence
        entre −180° et 180° : la tête ne s'enroule pas d'une prise à l'autre (pas de collecteur
        tournant)."""
        debut, fin = self.course_a
        candidats = [
            cible + 360 * tour
            for cible in cibles
            for tour in range(-3, 4)
            if debut <= cible + 360 * tour <= fin
        ]
        if not candidats:
            raise ErreurEtape(f"orientation {cibles} hors de la course de la rotation de la tête")
        # Sans demi-tour d'abord (plus d'un quart de tour : seulement au point des demi-tours,
        # griffe → point_demi_tour, PR n° 56, point 4).
        quart = 90 + self.reglages.rotation.tolerance_deg
        proches = [a for a in candidats if abs(a - actuel) <= quart] or candidats
        sans_tour = [a for a in proches if -180 - _EGAL <= a <= 180 + _EGAL]
        return min(sans_tour or proches, key=lambda a: abs(a - actuel))

    def _vers_le_haut(self, pose: Pose) -> list[dict[str, float]]:
        """Godet fermé, tête bras le long du pont, puis axes à la hauteur des trajets."""
        etapes: list[dict[str, float]] = []
        if pose.b > _EGAL:
            etapes.append({"b": 0.0})
        if not self.regles.bloquee(pose.a):
            etapes.append({"a": self._orientation_bloquee(pose.a)})
        if pose.z < self.reglages.trajet.z - _EGAL:
            etapes.append({"z": self.reglages.trajet.z})
        return etapes

    def _tete_a_dans_le_fut(self, a: float, choc: bool = False) -> Geste:
        """Mode bocaux (tâche 45 octies) : la prise finit tête à `a` (une orientation bloquée),
        dans le fût, avant la sortie. La prise tourne la raclette vers le centre du fût ; sans ce
        pas, la sortie prenait l'orientation bloquée la plus proche (parfois −180°) et le
        versement refusait. Dans le fût, les demi-tours sont permis (règles de la griffe). Si la
        tête ne peut pas tourner là où elle est, elle va d'abord au centre du fût."""
        assert self.pose is not None
        if abs(self.pose.a - a) <= self.reglages.rotation.tolerance_deg:
            return
        if not self.regles.dans_le_fut(self.pose):
            raise ErreurEtape(
                f"griffe : tête à {self.pose.a:g}° hors du fût, il faut {a:g}° avant la sortie",
                QUOI_FAIRE,
            )
        if self.pose.b > _EGAL:
            yield Pas("fermer le godet", {"b": 0.0}, choc=choc)
        contexte = self.contexte()
        cible = self._angle_proche(self.pose.a, [a])
        if self.regles.refus_mouvement(self.pose, self.pose.avec(a=cible), contexte) is not None:
            centre_x, centre_y = self.fut.centre_fut
            yield Pas("vers le centre du fût", {"x": centre_x, "y": centre_y}, choc=choc)
        yield Pas(f"tête à {a:g}° dans le fût", {"a": cible}, choc=choc)

    def _monter(self, choc: bool = False) -> Geste:
        assert self.pose is not None
        if self.bras.choc:
            # Après un choc : d'abord une remontée lente, droit vers le haut.
            self.bras.oublier_choc()
            pose = self.pose
            haut = self.reglages.trajet.z
            if not self.regles.bloquee(pose.a):
                haut = max(pose.z, self.reglages.rotation.libre_z_max)
            if haut > pose.z + _EGAL:
                yield Pas("remontée lente après le choc", {"z": haut}, vitesse="remontee_choc")
        pose = self.pose
        if (
            pose.z < self.reglages.ouverture_fut.z_min - _EGAL
            and self.regles.dans_le_fut(pose)
            and self.regles.hors_ouverture(pose.x, pose.y)
        ):
            # Trop loin de l'axe pour sortir par l'ouverture du poste du fût : d'abord au centre.
            centre_x, centre_y = self.fut.centre_fut
            yield Pas("vers le centre du fût", {"x": centre_x, "y": centre_y}, choc=choc)
        noms = {"b": "fermer le godet", "a": "tête bras le long du pont", "z": "monter"}
        for valeurs in self._vers_le_haut(self.pose):
            (axe,) = valeurs
            yield Pas(noms[axe], valeurs, choc=choc and axe == "z")

    def _chemin(self, depart: Pose, x: float, y: float) -> list[tuple[float, float]]:
        """Les points d'un trajet à la hauteur des trajets, jamais en diagonale : d'abord en x
        (mât à y ≥ mat_y_min), puis en y (mât à x ≥ mat_x_min_pour_y) ; retour à l'inverse.
        Départ ou arrivée dans la zone d'une exception de la table en butée haute (griffe
        traînée là pour la pose de l'entonnoir, tâche 45 nonies) : on en sort, ou on y entre, en
        x seulement, par x = entree_x."""
        tables = self.reglages.y_min_mat
        sortie = tables.exception_requise(depart.x, depart.y)
        entree = tables.exception_requise(x, y)
        if sortie is entree:
            return self._chemin_sans_exception(depart, x, y)
        points: list[tuple[float, float]] = []
        if sortie is not None and not math.isclose(depart.x, sortie.entree_x, abs_tol=_EGAL):
            points.append((sortie.entree_x, depart.y))
        debut = depart.avec(x=points[-1][0]) if points else depart
        if entree is None:
            return points + self._chemin_sans_exception(debut, x, y)
        points += self._chemin_sans_exception(debut, entree.entree_x, y)
        return points + [(x, y)]

    def _chemin_sans_exception(self, depart: Pose, x: float, y: float) -> list[tuple[float, float]]:
        trajet = self.reglages.trajet
        if math.isclose(depart.x, x, abs_tol=_EGAL) and math.isclose(depart.y, y, abs_tol=_EGAL):
            return []
        if self.regles.au_dessus_du_fut(depart.x, depart.y) and self.regles.au_dessus_du_fut(x, y):
            return [(x, y)]
        cote_seau = depart.x >= trajet.mat_x_min_pour_y - _EGAL
        passage = max(trajet.mat_y_min, y if cote_seau else depart.y)
        points = []
        if not math.isclose(depart.y, passage, abs_tol=_EGAL):
            points.append((depart.x, passage))
        if not math.isclose(depart.x, x, abs_tol=_EGAL):
            points.append((x, passage))
        if not math.isclose(passage, y, abs_tol=_EGAL):
            points.append((x, y))
        return points

    def _aller_au_dessus(self, x: float, y: float, choc: bool = False) -> Geste:
        yield from self._monter(choc)
        assert self.pose is not None
        for px, py in self._chemin(self.pose, x, y):
            yield Pas("trajet", {"x": px, "y": py}, choc=choc)

    def _poids(self, resultat: Resultat, charge_vide_n: float) -> float:
        if resultat.charge_n is None:
            raise ErreurEtape("pesée de la griffe sans lecture", QUOI_FAIRE)
        return (resultat.charge_n - charge_vide_n) / G

    def _seau(self) -> tuple[float, float]:
        return self.reglages.seau_remplissage

    # ------------------------------------------------------------ où prendre

    def _points_des_couches(self) -> list[tuple[float, float]]:
        centre_x, centre_y = self.fut.centre_fut
        points = []
        for rayon, nombre in zip(
            self.reglages.prise.rayons_m, self.reglages.prise.points, strict=True
        ):
            for k in range(nombre):
                angle = 2 * math.pi * k / nombre
                points.append(
                    self._dans_le_fut(
                        centre_x + rayon * math.cos(angle), centre_y + rayon * math.sin(angle)
                    )
                )
        return points

    def _dans_le_fut(self, x: float, y: float) -> tuple[float, float]:
        """Côté −x, le mât ne va qu'à fut_moins_x_max_m de l'axe du fût."""
        return max(x, self.fut.centre_fut[0] - self.reglages.fut_moins_x_max_m), y

    def _vers_le_centre(self, x: float, y: float) -> float | None:
        """Orientation de la tête pour que la raclette regarde le centre du fût."""
        centre_x, centre_y = self.fut.centre_fut
        if math.hypot(centre_x - x, centre_y - y) < 0.01:
            return None
        direction = math.degrees(math.atan2(centre_y - y, centre_x - x))
        return direction - self.reglages.raclette_angle_deg

    def _passe_de_fond(self) -> list[ActionFond]:
        fond = self.reglages.fond
        centre_x, centre_y = self.fut.centre_fut
        actions = [ActionFond("raclage")]
        rayon = 0.0
        while rayon <= fond.spirale_rayon_max_m + _EGAL:
            nombre = max(1, round(2 * math.pi * rayon / fond.spirale_pas_m))
            for k in range(nombre):
                # Un cercle après l'autre, décalé d'un demi-pas : une spirale depuis le centre.
                angle = 2 * math.pi * (k + 0.5 * (rayon > 0)) / nombre
                x, y = self._dans_le_fut(
                    centre_x + rayon * math.cos(angle), centre_y + rayon * math.sin(angle)
                )
                actions.append(ActionFond("fond", x, y))
            rayon += fond.spirale_pas_m
        for k in range(fond.paroi_prises):
            angle = 360 * k / fond.paroi_prises
            x, y = self._dans_le_fut(
                centre_x + fond.paroi_rayon_m * math.cos(_rad(angle)),
                centre_y + fond.paroi_rayon_m * math.sin(_rad(angle)),
            )
            # Joue du godet parallèle à la paroi (côté −x : tête orientée vers la paroi).
            actions.append(ActionFond("paroi", x, y, angle - fond.joue_angle_deg))
        actions.append(ActionFond("chasse_neige"))
        actions += [ActionFond("centre", centre_x, centre_y)] * fond.centre_prises
        return actions

    def _prochaine_prise(self, dose: DoseDonnee | None = None) -> PrisePrevue:
        plan, reglages = self.plan, self.reglages
        reste = max(self.format.dose_kg - plan.couche_kg, 0.0)
        poids = reste / self.doses.prises_par_couche(reste) if reste > 0 else self.format.dose_kg
        if dose is not None:
            poids = (dose.min_kg + dose.max_kg) / 2 * self.correction_dose
        if plan.en_fond and plan.fond and dose is None:
            action = plan.fond[0]
            fond = reglages.fond
            paroi = action.sorte == "paroi"
            return PrisePrevue(
                lieu="paroi" if paroi else "fond",
                x=action.x,
                y=action.y,
                a=action.a,
                poids_kg=poids,
                enfoncement_m=0.0,
                bouchees=0,
                ouverture_max=fond.paroi_ouverture_max if paroi else 1.0,
                contact_n=fond.seuil_appui_n,
                poussee_n=fond.force_max_n,
            )
        x, y = self._points[plan.point % len(self._points)]
        return PrisePrevue(
            lieu="couche",
            x=x,
            y=y,
            a=self._vers_le_centre(x, y),
            poids_kg=poids,
            enfoncement_m=reglages.prise.enfoncement_m,
            bouchees=reglages.machouiller.bouchees if self._machouiller() and not dose else 0,
            ouverture_max=1.0,
            contact_n=reglages.descente.seuil_contact_n,
            poussee_n=None,
        )

    def _verifier_passe_de_fond(self) -> None:
        plan, fond = self.plan, self.reglages.fond
        if plan.en_fond:
            return
        restant = self.poste.poids_restant_kg()
        fond_z = self.fut.fut_fond_interieur_z
        bas_niveau = plan.niveau_z is not None and plan.niveau_z - fond_z <= fond.passe_hauteur_m
        if (restant is not None and restant <= fond.passe_kg) or bas_niveau:
            journal.info("Griffe : derniers kilos du fût (%s kg), passe de fond", restant)
            plan.en_fond, plan.fond = True, self._passe_de_fond()

    # ------------------------------------------------------------ les gestes

    def geste_revenir(self) -> Geste:
        """Au-dessus du fût, à la hauteur des trajets (godet fermé, tête bloquée)."""
        yield from self._aller_au_dessus(*self.fut.centre_fut)

    def geste_prendre(self, dose: DoseDonnee | None = None) -> Geste:
        """Descendre au contact, mâchouiller, prendre en plongée, remonter, peser, ajuster.
        `dose` : une dose donnée (bocal de semence), pesée à l'arrêt ; la tare « godet vide »
        (godet ouvert, vide, au-dessus du substrat) est gardée dans `tare_n`."""
        plan, reglages = self.plan, self.reglages
        prevue = self._prochaine_prise(dose)
        bas_offset = reglages.bas_godet_sous_axes
        assert self.pose is not None
        niveau = plan.niveau_z if plan.niveau_z is not None else self.fut.fut_bord_z
        approche = min(niveau + reglages.descente.marge_niveau_m + bas_offset, reglages.trajet.z)
        if plan.reprendre and self.regles.dans_le_fut(self.pose):
            # Trop léger : reprendre à côté sans faire le voyage (godet ouvert, dans le fût).
            yield Pas("à côté, dans le fût", {"x": prevue.x, "y": prevue.y})
        elif self.regles.hors_ouverture(prevue.x, prevue.y) and (
            approche < reglages.ouverture_fut.z_min
        ):
            # Trop loin de l'axe pour passer par l'ouverture du poste du fût : on descend au
            # centre, puis on va à côté dans le fût.
            yield from self._aller_au_dessus(*self.fut.centre_fut)
            yield Pas("descente rapide au centre", {"z": approche})
            yield Pas("à côté, dans le fût", {"x": prevue.x, "y": prevue.y})
        else:
            yield from self._aller_au_dessus(prevue.x, prevue.y)
        plan.reprendre = False
        assert self.pose is not None
        if approche < self.pose.z - _EGAL:
            yield Pas("descente rapide", {"z": approche})
        # Raclette vers le centre du fût, si la tête peut tourner godet ouvert à cette hauteur.
        if prevue.a is not None:
            a = self._angle_proche(self.pose.a, [prevue.a])
            contexte = self.contexte()
            tourne = self.pose.avec(a=a)
            if (
                self.regles.refus_mouvement(self.pose, tourne, contexte) is None
                and self.regles.refus_pose(tourne.avec(b=1.0), contexte) is None
            ):
                yield Pas("tourner la tête", {"a": a})
        ouvert = yield Pas("ouvrir le godet", {"b": 1.0}, pesee=dose is None)
        if dose is None:
            assert ouvert.charge_n is not None
            charge_vide = ouvert.charge_n
        else:
            charge_vide = yield from dose.peser()
            self.tare_n = charge_vide
        fond_z = plan.fond_z if plan.fond_z is not None else self.fut.fut_fond_interieur_z
        z_min = max(self.course_z[0], fond_z - reglages.descente.butee_sous_fond_m + bas_offset)
        contact = yield Pas(
            "descente lente au contact",
            {"z": z_min},
            vitesse="descente_lente",
            arret_si_baisse_n=prevue.contact_n,
            contact=True,
        )
        if not contact.arrete:
            journal.info("Griffe : fond atteint sans contact, le fût est vide")
            plan.vide = True
            yield from self._fermer_apres_vide()
            return
        niveau = self.regles.bas(contact.pose)
        plan.niveau_z = niveau
        if prevue.lieu != "couche":
            plan.fond_z = niveau if plan.fond_z is None else min(plan.fond_z, niveau)
        z = contact.pose.z
        machouiller = reglages.machouiller
        for numero in range(1, prevue.bouchees + 1):
            yield Pas(f"bouchée {numero}", {"b": machouiller.fermeture})
            yield Pas("rouvrir", {"b": 1.0})
            enfonce = yield Pas(
                "enfoncer",
                {"z": max(z - machouiller.enfoncement_m, z_min)},
                vitesse="plongee",
                arret_si_baisse_n=machouiller.force_max_n,
            )
            z = enfonce.pose.z
        # Le volume pris dépend de tout l'enfoncement sous le contact : bouchées, prise, plongée.
        profondeur = (
            niveau - self.regles.bas(self.pose) + prevue.enfoncement_m + reglages.prise.plongee_m
        )
        ouverture = self.doses.ouverture_pour(
            prevue.poids_kg, profondeur, prevue.lieu, prevue.ouverture_max
        )
        yield Pas("ouverture de la dose", {"b": ouverture})
        if prevue.enfoncement_m > 0:
            enfonce = yield Pas(
                "enfoncer",
                {"z": max(z - prevue.enfoncement_m, z_min)},
                vitesse="plongee",
                arret_si_baisse_n=prevue.poussee_n,
            )
            z = enfonce.pose.z
        ferme = yield Pas(
            "fermer en plongée",
            {"z": max(z - reglages.prise.plongee_m, z_min), "b": 0.0},
            vitesse="plongee",
            arret_si_baisse_n=prevue.poussee_n,
        )
        if ferme.arrete:
            yield Pas("finir de fermer", {"b": 0.0})
        prise = reglages.prise
        pese = yield Pas(
            "remonter et peser",
            {"z": min(ferme.pose.z + prise.remontee_m, reglages.trajet.z)},
            attente_s=prise.pesee_attente_s if dose is None else 0.0,
            pesee=dose is None,
        )
        if dose is None:
            poids = self._poids(pese, charge_vide)
        else:
            poids = ((yield from dose.peser()) - charge_vide) / G
            if poids > 0:
                self.correction_dose *= (dose.min_kg + dose.max_kg) / 2 / poids
        essais = 0
        while (
            dose is None
            and poids > prevue.poids_kg * (1 + prise.tolerance)
            and essais < prise.entrouvrir_essais_max
        ):
            # Trop lourd : s'entrouvrir au-dessus du fût jusqu'au bon poids.
            essais += 1
            yield Pas("s'entrouvrir", {"b": prise.entrouvrir})
            pese = yield Pas(
                "refermer et peser", {"b": 0.0}, attente_s=prise.pesee_attente_s, pesee=True
            )
            poids = self._poids(pese, charge_vide)
        profondeur = max(niveau - self.regles.bas(ferme.pose), 0.0)
        volume = self.doses.volume(ouverture, profondeur)
        self._noter_prise(prevue, ouverture, profondeur, niveau, poids, volume)
        if prevue.lieu == "fond" and poids < prise.utile_min_kg:
            journal.info("Griffe : prise au fond de %.2f kg, pas de prise utile : fût vide", poids)
            plan.vide = True
            yield from self._fermer_apres_vide()
            return
        fond = niveau - self.fut.fut_fond_interieur_z <= reglages.fond.passe_hauteur_m
        if dose is not None and fond and poids < prise.utile_min_kg:
            # Dose donnée (pas de passe de fond) : contact au fond, presque rien pris.
            journal.info("Griffe : prise de %.3f kg au fond du fût : fût vide", poids)
            plan.vide = True
            yield from self._fermer_apres_vide()
            return
        if dose is not None and not dose.min_kg <= poids <= dose.max_kg:
            if plan.reprises >= dose.reprises_max:
                plan.reprises = 0
                yield Pas("rendre la prise au fût", {"b": 1.0})
                raise ErreurEtape(
                    f"griffe : pas de dose de {dose.min_kg:g} à {dose.max_kg:g} kg après "
                    f"{dose.reprises_max + 1} prises (dernière : {poids:.3f} kg)",
                    QUOI_FAIRE_DOSE,
                )
            # Hors de la plage : la prise est rendue au fût, puis refaite à côté.
            plan.reprises += 1
            plan.reprendre = True
            plan.point += 1
            yield Pas("rendre la prise au fût", {"b": 1.0})
            return
        trop_leger = poids < prevue.poids_kg * (1 - prise.tolerance)
        if (
            dose is None
            and prevue.lieu == "couche"
            and trop_leger
            and plan.reprises < prise.reprises_max
        ):
            plan.reprises += 1
            plan.reprendre = True
            plan.point += 1
            yield Pas("rendre la prise au fût", {"b": 1.0})
            return
        plan.reprises = 0
        plan.godet_kg, plan.dose_notee = poids, False
        if plan.en_fond and plan.fond:
            plan.fond.pop(0)
        else:
            plan.point += 1

    def _fermer_apres_vide(self) -> Geste:
        """Fût vide : ce qui reste dans le godet retombe au fond ; godet refermé."""
        yield Pas("ouvrir le godet", {"b": 1.0})
        yield Pas("fermer le godet", {"b": 0.0})

    def _noter_prise(
        self,
        prevue: PrisePrevue,
        ouverture: float,
        profondeur: float,
        niveau: float,
        poids: float,
        volume: float,
    ) -> None:
        bouchees = prevue.bouchees
        self.doses.noter(
            Prise(
                prevue.lieu,
                ouverture,
                profondeur,
                bouchees,
                niveau,
                prevue.x,
                prevue.y,
                poids,
                volume,
            )
        )
        journal.info(
            "Griffe : prise %s de %.2f kg (ouverture %.2f, %d bouchées, niveau %.3f m)",
            prevue.lieu,
            poids,
            ouverture,
            bouchees,
            niveau,
        )
        if self.registre is None:
            return
        try:
            self.registre.noter_prise_griffe(
                prevue.lieu,
                round(ouverture, 3),
                round(profondeur, 4),
                bouchees,
                round(niveau, 4),
                round(prevue.x, 4),
                round(prevue.y, 4),
                round(poids, 3),
                round(volume, 3),
                cycle=self.poste.etat().cycle,
            )
        except ErreurRegistre as erreur:
            journal.error("Griffe : registre : %s", erreur)

    def geste_porter(self) -> Geste:
        """Sortir du fût tête bras le long du pont, puis trajet vers le seau."""
        yield from self._monter(choc=True)
        self._noter_dose()
        yield from self._aller_au_dessus(*self._seau(), choc=True)

    def _noter_dose(self) -> None:
        """La dose est dite au poste du fût une fois la griffe sortie du fût."""
        plan = self.plan
        if plan.dose_notee or not self.hors_du_fut():
            return
        plan.dose_notee = True
        message = self.poste.noter_dose(plan.godet_kg)
        if message is not None:
            journal.warning("Griffe : %s", message)

    def geste_vider(self) -> Geste:
        """Godet à 2 cm au-dessus du bord, ouverture en grand en tournant : couche en couronne."""
        vidage, seau = self.reglages.vidage, self.format
        assert self.pose is not None
        if not self._au_dessus_du_seau(self.pose):
            yield from self._aller_au_dessus(*self._seau(), choc=True)
        yield Pas(
            "descendre au-dessus du seau", {"z": seau.haut_z + vidage.au_dessus_haut_m}, choc=True
        )
        assert self.pose is not None
        a = self.pose.a
        if seau.haut_z <= vidage.rotation_haut_max_z and vidage.rotation_deg > 0:
            yield Pas("ouvrir en grand en tournant", {"b": 1.0, "a": a + vidage.rotation_deg})
            yield Pas("tête droite", {"a": a})
        else:
            yield Pas("ouvrir en grand", {"b": 1.0})
        yield Pas("refermer le godet à vide", {"b": 0.0})
        plan = self.plan
        plan.couche_kg += plan.godet_kg
        plan.seau_kg += plan.godet_kg
        plan.godet_kg = 0.0
        plan.couche_tassee = False

    def _au_dessus_du_seau(self, pose: Pose) -> bool:
        x, y = self._seau()
        return math.isclose(pose.x, x, abs_tol=0.001) and math.isclose(pose.y, y, abs_tol=0.001)

    def _point_autour_du_seau(self, distance: float) -> tuple[float, float]:
        x, y = self._seau()
        direction = _rad(self.reglages.essuyage.direction_deg)
        return x + distance * math.cos(direction), y + distance * math.sin(direction)

    def geste_tasser(self) -> Geste:
        """Godet refermé à vide, son fond appuie sur la couche pendant que le seau tourne."""
        seau, tassement = self.format, self.reglages.tassement
        bas_offset = self.reglages.bas_godet_sous_axes
        dessus = seau.haut_z + self.reglages.vidage.au_dessus_haut_m
        x, y = self._point_autour_du_seau(seau.tassement_rayon_m)
        assert self.pose is not None
        if not self._au_dessus_du_seau(self.pose) or self.pose.b > _EGAL:
            yield from self._aller_au_dessus(*self._seau())
            yield Pas("descendre au-dessus du seau", {"z": dessus})
        yield Pas("au-dessus du point d'appui", {"x": x, "y": y})
        z_min = seau.haut_z - seau.tassement_bas_max_sous_bord_m + bas_offset
        self.tourner_seau(True)
        try:
            for numero in range(1, tassement.appuis + 1):
                appui = yield Pas(
                    f"appui {numero} sur la couche",
                    {"z": z_min},
                    vitesse="descente_lente",
                    arret_si_baisse_n=tassement.force_n,
                )
                yield Pas(
                    "relever",
                    {"z": min(appui.pose.z + tassement.remontee_m, dessus)},
                    attente_s=tassement.attente_s,
                )
        finally:
            self.tourner_seau(False)
        yield Pas("remonter au-dessus du seau", {"z": dessus})
        self.plan.couche_tassee = True

    def geste_essuyer(self) -> Geste:
        """Raclette posée sur le bord du seau qui tourne, godet à moitié ouvert."""
        seau, essuyage = self.format, self.reglages.essuyage
        x, y = self._point_autour_du_seau(seau.rayon_haut + essuyage.decalage_m)
        yield from self._aller_au_dessus(x, y)
        z = seau.haut_z + essuyage.au_dessus_haut_m
        yield Pas("descendre à côté du seau", {"z": z + self.reglages.descente.marge_niveau_m})
        assert self.pose is not None
        vers_le_seau = essuyage.direction_deg + 180 - self.reglages.raclette_angle_deg
        yield Pas("raclette vers le seau", {"a": self._angle_proche(self.pose.a, [vers_le_seau])})
        yield Pas("ouvrir le godet à moitié", {"b": essuyage.ouverture_godet})
        yield Pas("raclette sur le bord", {"z": z})
        self.tourner_seau(True)
        try:
            yield Pas("essuyer le bord", attente_s=essuyage.duree_s)
        finally:
            self.tourner_seau(False)
        yield from self._monter()

    def geste_racler(self) -> Geste:
        """Raclage de la paroi (lame contre la paroi, un tour dans chaque sens), ou chasse-neige
        au fond (godet fermé, lame inclinée)."""
        plan, reglages, fut = self.plan, self.reglages, self.fut
        action = plan.fond.pop(0) if plan.fond else ActionFond("raclage")
        centre_x, centre_y = fut.centre_fut
        rayon_lame = fut.fut_diametre_interieur / 2
        fond_z = plan.fond_z if plan.fond_z is not None else fut.fut_fond_interieur_z
        bas_offset = reglages.bas_godet_sous_axes
        if action.sorte == "raclage":
            rayon = rayon_lame + reglages.raclage.appui_m - reglages.raclette_decalage_m
            haut = min(
                fut.fut_bord_z - reglages.raclage.depart_sous_bord_m + bas_offset,
                reglages.rotation.libre_z_max,
            )
            niveau = plan.niveau_z if plan.niveau_z is not None else fond_z
            bas = max(niveau + reglages.descente.marge_niveau_m + bas_offset, self.course_z[0])
            hauteurs = (haut, min(bas, haut))
            biais, ouverture = 0.0, 1.0
        else:
            rayon = rayon_lame - reglages.raclette_decalage_m
            z = max(
                fond_z + reglages.fond.chasse_neige_au_dessus_fond_m + bas_offset, self.course_z[0]
            )
            hauteurs = (z, z)
            biais, ouverture = reglages.fond.chasse_neige_angle_deg, 0.0
        points = reglages.raclage.points_par_tour
        premier = self._dans_le_fut(centre_x + rayon, centre_y)
        # L'ouverture du poste du fût ne laisse passer la tête que près de l'axe du fût (entre
        # 1,11 et la butée haute) : on descend au centre, puis on va contre la paroi dans le fût.
        yield from self._aller_au_dessus(centre_x, centre_y)
        yield Pas("descendre dans le fût", {"z": hauteurs[0]})
        yield Pas("aller contre la paroi", {"x": premier[0], "y": premier[1]})
        assert self.pose is not None
        # Lame dans le plan qui passe par l'axe du fût (chasse-neige : inclinée de « biais »).
        depart = biais - reglages.raclette_angle_deg
        debut_a, fin_a = self.course_a
        a0 = self._angle_proche(self.pose.a, [depart])
        if a0 + 360 > fin_a:
            a0 -= 360
        if a0 < debut_a:
            raise ErreurEtape(
                "pas assez de course de rotation pour un tour de raclette", QUOI_FAIRE
            )
        yield Pas("tête pour le raclage", {"a": a0, "b": ouverture})
        tours = (1, -1) if action.sorte == "raclage" else (1,)
        for sens in tours:
            z_debut, z_fin = hauteurs if sens == 1 else hauteurs[::-1]
            for k in range(1, points + 1):
                t = k / points
                angle = 360 * t if sens == 1 else 360 * (1 - t)
                x, y = self._dans_le_fut(
                    centre_x + rayon * math.cos(_rad(angle)),
                    centre_y + rayon * math.sin(_rad(angle)),
                )
                yield Pas(
                    "raclage" if action.sorte == "raclage" else "chasse-neige",
                    {"x": x, "y": y, "z": z_debut + (z_fin - z_debut) * t, "a": a0 + angle},
                )
        yield Pas("lame décollée de la paroi", {"x": centre_x, "y": centre_y})
        yield from self._monter()

    def geste_fut_vide(self) -> Geste:
        """Fût vide : la griffe sort de la zone du plateau, puis « finir_vidange » au poste."""
        yield from self._aller_au_dessus(*self.reglages.attente)
        message = self.poste.finir_vidange(self.plan.seaux_finis)
        journal.warning("Griffe : %s", message)

    # ------------------------------------------------------------ la suite des étapes

    def nouveau_fut(self) -> str:
        """Le poste est prêt : une nouvelle vidange commence."""
        self.plan = Plan(format=self._prochain_format() or self.reglages.format_par_defaut)
        self.doses.nouveau_fut()
        self.correction_dose = 1.0
        return "revenir_au_fut"

    def apres_retour(self) -> str:
        """Au-dessus du fût : raclage ou chasse-neige, prise, ou fin du fût."""
        self._verifier_passe_de_fond()
        plan = self.plan
        if plan.en_fond and not plan.fond:
            plan.vide = True
        if plan.vide:
            return self._fin_du_fut()
        if plan.en_fond and plan.fond[0].sorte in ("raclage", "chasse_neige"):
            return "racler"
        return "prendre_une_dose"

    def apres_prise(self) -> str:
        plan = self.plan
        if plan.reprendre:
            return "prendre_une_dose"
        if plan.vide:
            return self._fin_du_fut()
        return "porter_au_seau"

    def apres_vidage(self) -> str:
        plan, seau = self.plan, self.format
        complete = plan.couche_kg >= seau.dose_kg * (1 - self.reglages.prise.tolerance)
        if not complete:
            return "revenir_au_fut"
        if seau.tasser_chaque_couche or self.derniere_couche:
            return "tasser"
        return self._couche_suivante()

    def apres_tassement(self) -> str:
        if self.derniere_couche or self.plan.vide:
            return "essuyer_le_bord"
        return self._couche_suivante()

    def _couche_suivante(self) -> str:
        if self.derniere_couche:
            return "essuyer_le_bord"
        plan = self.plan
        # Couche vidée (et tassée si elle doit l'être) : le mycélium peut venir dessus.
        self._couche_finie(plan.couche)
        plan.couche += 1
        plan.couche_kg, plan.couche_tassee = 0.0, False
        return "revenir_au_fut"

    def apres_essuyage(self) -> str:
        plan = self.plan
        plan.seaux_finis += 1
        journal.info("Griffe : seau n° %d plein (%.1f kg)", plan.seaux_finis, plan.seau_kg)
        self._seau_fini(plan.seaux_finis)
        plan.format = self._prochain_format() or self.reglages.format_par_defaut
        plan.couche, plan.couche_kg, plan.seau_kg, plan.couche_tassee = 1, 0.0, 0.0, False
        return "fut_vide" if plan.vide else "revenir_au_fut"

    def _fin_du_fut(self) -> str:
        """Fût vide : finir le seau commencé (tassement si besoin, essuyage), puis la fin."""
        plan = self.plan
        if plan.couche_kg > 0 and not plan.couche_tassee:
            return "tasser"
        if plan.seau_kg > 0:
            return "essuyer_le_bord"
        return "fut_vide"
