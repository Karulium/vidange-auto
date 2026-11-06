"""Prises d'origine des rotations, faites par le Pi après celles du portique (tâche 36 bis).

    rotations = OriginesRotations(machine, liaisons, axes, garde, compte_tours)
    rotations.etapes_controle()    # avant que rien ne bouge : rotation de la griffe et cordon
    rotations.etapes_griffe()      # B à 0, au point de recherche, A sur son fanion, remontée
    rotations.etapes_tete()        # tête de préhension près de 0, puis sur son Hall

**Griffe** (fil Griffe, PR n° 56, point 4). Un fanion de 180° : le capteur origine_rotation_griffe
est actionné pour A de −180° à 0°, libre de 0° à +180° ; son état dit de quel côté de 0 est la
tête. La recherche se fait au point des demi-tours (griffe → point_demi_tour : mât en x et y,
axes à z, godet fermé). Le Pi tourne d'abord en − jusqu'au fanion s'il est libre (au plus
griffe → origine_rotation → recherche_deg), puis « $HA » finit toujours en tournant en +, lent,
jusqu'au bord du fanion = A 0. Jamais au-delà de ± 180°. Si la dernière rotation connue n'était
ni 0° ni 180° (coupure en pleine rotation, en bas), Z ne monte pas : alarme, tête remise à la main.

**Tête de préhension** (décisions, « Origine de la rotation de la tête », 05/11). Le Hall voit
l'aimant à chaque tour : le TOUR vient du compte-tours (compte_tours_tete), l'angle gardé
(angles_gardes) sert de contrôle. Compte-tours illisible ou hors plage, angle gardé inconnu ou
noté pendant une rotation, ou les deux en désaccord de plus de prehension →
ecart_compte_tours_max_deg : pas de prise d'origine, l'écran demande de vérifier le cordon et
attend la confirmation (acquitter puis Go). Sinon le Pi ramène la tête à avant_hall_deg avant le
Hall, puis « $HA » le cherche en +, lent : bien moins d'un tour.

Confirmation : l'étape de contrôle lève l'alarme ; après l'acquittement et le Go, elle est
refaite et passe (Karulium a regardé). Ces verrous ne protègent que la MACHINE.
"""

import math
from collections.abc import Callable, Mapping

from vidange.angles_gardes import AngleGarde, AnglesGardes
from vidange.chef import Axes, Condition, ErreurEtape, Etape
from vidange.fluidnc import Commande, Liaison, protocole
from vidange.journal import donner_journal
from vidange.reglages import CarteFluidnc, Machine

journal = donner_journal("portique")

GRIFFE_A = "griffe_a"
GRIFFE_B = "griffe_b"
GRIFFE_Z = "griffe_z"
TETE_A = "prehension_a"
# Signaux (docs/entrees-sorties.yaml) lus dans « Pn: » de leur carte (fluidnc.yaml → entrees).
FANION = "origine_rotation_griffe"
HALL = "origine_rotation_tete"

DELAI_ORIGINE = "portique_origine_max"
DELAI_DEPLACEMENT = "portique_deplacement_max"

QUOI_FAIRE_GRIFFE_A = (
    "La dernière rotation connue de la tête de la griffe n'est ni 0° ni 180° (coupure pendant "
    "une rotation, ou jamais notée) : Z ne monte pas, la tête pourrait accrocher. Moteurs sans "
    "courant, remettre la tête à la main à 0° (bras le long du pont, raclette côté fût, câbles "
    "non vrillés), vérifier qu'elle peut monter sans rien toucher, puis acquitter et donner le Go."
)
QUOI_FAIRE_CORDON = (
    "Vérifier que le cordon spiralé de la tête de préhension n'est pas vrillé ; le remettre droit "
    "à la main si besoin (tête près de 0°). Puis acquitter et donner le Go : la prise d'origine "
    "de la rotation continue."
)
QUOI_FAIRE_FANION = (
    "Le capteur du fanion de la rotation de la griffe (origine_rotation_griffe) n'a pas changé "
    "dans la recherche : regarder son voyant, son câble (multiconducteur de la griffe) et que la "
    "tête tourne bien. Remettre la tête à 0° à la main si besoin, puis acquitter et donner le Go."
)
QUOI_FAIRE_HALL = (
    "La rotation de la tête n'a pas trouvé son capteur Hall (ou un autre problème de la carte) : "
    "regarder le Hall sous la poulie de 60 dents et son câble, et que le cordon n'est pas vrillé. "
    "Puis acquitter et donner le Go."
)
QUOI_FAIRE = (
    "Regarder la vidéo du portique : un axe est-il bloqué, un outil accroché ? Corriger, puis "
    "acquitter et donner le Go : le geste est refait depuis le début."
)

_MM_PAR_M = 1000
_EGAL = 1e-6
# « Bras le long du pont » : à 0° ou ± 180°, à la tolérance de rotation de la griffe près.
_ANGLES_DROITS = (0.0, 180.0, -180.0)


def _deg(valeur: float) -> str:
    return f"{valeur:.1f}".rstrip("0").rstrip(".").replace(".", ",") + "°"


class _Rotation:
    """Un déplacement manuel (« $J= ») ou une prise d'origine (« $H ») d'un axe tournant, sur
    sa carte, et sa fin (réponse reçue, puis carte au repos)."""

    def __init__(self, liaison: Liaison, lettre: str) -> None:
        self.liaison = liaison
        self.lettre = lettre
        self.commande: Commande | None = None
        self._annule_a: int | None = None

    def position(self) -> float | None:
        return self.liaison.etat.positions.get(self.lettre)

    def tourner_de(self, delta_deg: float, vitesse_deg_s: float) -> None:
        """Tourne de delta_deg (relatif à la position lue, même avant la prise d'origine)."""
        depart = self.position() or 0.0
        self._annule_a = None
        self.commande = self.liaison.deplacer_manuel(
            {self.lettre: depart + delta_deg}, vitesse_deg_s * 60
        )

    def prise_origine(self) -> None:
        self._annule_a = None
        self.commande = self.liaison.envoyer(protocole.PRISE_ORIGINE + self.lettre)

    def rien(self) -> None:
        """Pas de mouvement : `finie` est tout de suite vraie."""
        self.commande = None
        self._annule_a = None

    def annuler(self) -> None:
        self.liaison.annuler_deplacement()
        self._annule_a = self.liaison.etat.rapports_recus

    def finie(self, quoi: str, quoi_faire: str) -> bool:
        """Vrai quand la ligne a répondu et que la carte est au repos ; ErreurEtape si refusée."""
        etat = self.liaison.etat
        if self._annule_a is not None:
            # Annulé : attendre un rapport d'après l'annulation, carte au repos.
            return etat.rapports_recus > self._annule_a + 1 and etat.au_repos
        commande = self.commande
        if commande is None:
            return True
        if commande.erreur is not None:
            raise ErreurEtape(f"{quoi}, « {commande.ligne} » : {commande.erreur}", quoi_faire)
        return (
            commande.finie
            and etat.rapports_recus > commande.rapports_a_la_reponse + 1
            and etat.au_repos
        )


class OriginesRotations:
    def __init__(
        self,
        machine: Machine,
        cartes: Mapping[str, CarteFluidnc],
        liaisons: Mapping[str, Liaison],
        axes: Axes,
        garde: AnglesGardes | None = None,
        compte_tours: Callable[[], float | None] | None = None,
    ) -> None:
        """`garde` : les angles gardés au redémarrage (None : inconnus, confirmation demandée) ;
        `compte_tours` : l'angle cumulé de la tête de préhension lu au compte-tours (None : pas
        de compte-tours, confirmation demandée)."""
        self.machine = machine
        self.liaisons = liaisons
        self.axes = axes
        self.garde = garde
        self.compte_tours = compte_tours
        griffe = machine.griffe
        self.griffe = griffe if griffe is not None and griffe.origine_rotation is not None else None
        prehension = machine.prehension
        self.tete = (
            prehension
            if prehension is not None and prehension.origine_rotation is not None
            else None
        )
        # Confirmations reçues (après une alarme, l'étape refaite passe).
        self._a_confirmer: set[str] = set()
        self._estimation_tete = 0.0
        self._griffe_a_depart = 0.0
        self._vu_libre = False
        self._sens = -1
        self._a_griffe: _Rotation | None = None
        self._a_tete: _Rotation | None = None
        self._fanion: str | None = None
        if self.griffe is not None:
            axe = machine.axes[GRIFFE_A]
            assert axe.carte is not None and axe.lettre is not None
            self._a_griffe = _Rotation(liaisons[axe.carte], axe.lettre)
            self._fanion = cartes[axe.carte].entrees.get(FANION) if axe.carte in cartes else None
            if self._fanion is None:
                raise ValueError(f"fluidnc.yaml : il manque entrees → {FANION} (griffe)")
        if self.tete is not None:
            axe = machine.axes[TETE_A]
            assert axe.carte is not None and axe.lettre is not None
            if axe.carte not in liaisons:
                raise ValueError(f"portique : pas de liaison pour la carte {axe.carte}")
            self._a_tete = _Rotation(liaisons[axe.carte], axe.lettre)

    # ------------------------------------------------------------ contrôles

    def _lire(self, axe: str) -> AngleGarde | None:
        return None if self.garde is None else self.garde.lire(axe)

    def _confirmer_ou_refuser(self, cle: str, probleme: str | None, quoi_faire: str) -> bool:
        """Sans problème : vrai. Avec un problème : la première fois, alarme ; refaite après
        l'acquittement et le Go, l'étape passe (Karulium a confirmé) : faux."""
        if probleme is None:
            self._a_confirmer.discard(cle)
            return True
        if cle in self._a_confirmer:
            self._a_confirmer.discard(cle)
            journal.warning("Portique : %s ; confirmé par Karulium (acquitté, Go)", probleme)
            return False
        self._a_confirmer.add(cle)
        journal.error("Portique : %s", probleme)
        raise ErreurEtape(probleme, quoi_faire)

    def confirmer(self) -> None:
        """Karulium a déjà regardé (outil d'essai, option --confirmer) : tête de la griffe à 0° à
        la main, cordon de la tête de préhension droit. Les contrôles le disent et passent."""
        self._a_confirmer |= {GRIFFE_A, TETE_A}

    def probleme_griffe(self) -> str | None:
        """Pourquoi Z ne peut pas monter sans que la tête soit remise à la main, ou None."""
        assert self.griffe is not None
        garde = self._lire(GRIFFE_A)
        if garde is None:
            return "rotation de la griffe inconnue (jamais notée) : Z ne monte pas"
        if garde.en_rotation:
            return (
                f"coupure pendant une rotation de la griffe (partie de {_deg(garde.angle_deg)}) : "
                "Z ne monte pas"
            )
        tolerance = self.griffe.rotation.tolerance_deg
        if not any(abs(garde.angle_deg - a) <= tolerance + _EGAL for a in _ANGLES_DROITS):
            return (
                f"rotation de la griffe à {_deg(garde.angle_deg)}, ni 0° ni 180° : Z ne monte pas"
            )
        return None

    def controler_griffe(self) -> None:
        assert self.griffe is not None
        if self._confirmer_ou_refuser(GRIFFE_A, self.probleme_griffe(), QUOI_FAIRE_GRIFFE_A):
            garde = self._lire(GRIFFE_A)
            assert garde is not None
            self._griffe_a_depart = garde.angle_deg
        else:
            # Tête remise à la main à 0° (QUOI_FAIRE_GRIFFE_A).
            self._griffe_a_depart = 0.0

    def mesure_tete(self) -> float | None:
        """L'angle cumulé de la tête lu au compte-tours, ou None (pas de compte-tours, erreur)."""
        if self.compte_tours is None:
            return None
        try:
            return self.compte_tours()
        except Exception as erreur:  # le matériel peut lever n'importe quoi : on le dit
            journal.error("Compte-tours de la tête illisible : %s", erreur)
            return None

    def probleme_tete(self, mesure: float | None) -> str | None:
        """Pourquoi le tour de la tête n'est pas sûr (cordon à vérifier), ou None."""
        assert self.tete is not None and self.tete.origine_rotation is not None
        origine = self.tete.origine_rotation
        debut, fin = origine.compte_tours_plage_deg
        if mesure is None or not math.isfinite(mesure):
            return "compte-tours de la tête illisible : tour de la tête inconnu"
        if not debut <= mesure <= fin:
            return (
                f"compte-tours de la tête à {_deg(mesure)}, hors de sa plage ({_deg(debut)} à "
                f"{_deg(fin)})"
            )
        garde = self._lire(TETE_A)
        if garde is None:
            return "angle de la tête jamais enregistré : pas de contrôle du compte-tours"
        if garde.en_rotation:
            return f"coupure pendant une rotation de la tête (partie de {_deg(garde.angle_deg)})"
        ecart = abs(mesure - garde.angle_deg)
        if ecart > self.tete.ecart_compte_tours_max_deg + _EGAL:
            return (
                f"compte-tours ({_deg(mesure)}) et angle enregistré ({_deg(garde.angle_deg)}) en "
                f"désaccord de {_deg(ecart)} (au plus {_deg(self.tete.ecart_compte_tours_max_deg)})"
            )
        return None

    def controler_tete(self) -> None:
        assert self.tete is not None
        mesure = self.mesure_tete()
        probleme = self.probleme_tete(mesure)
        ok = self._confirmer_ou_refuser(TETE_A, probleme, QUOI_FAIRE_CORDON)
        plage = self.tete.origine_rotation.compte_tours_plage_deg  # type: ignore[union-attr]
        if ok or (mesure is not None and plage[0] <= mesure <= plage[1]):
            assert mesure is not None
            self._estimation_tete = mesure
        else:
            # Compte-tours inutilisable, cordon vérifié et remis droit : tête près de 0°.
            self._estimation_tete = 0.0
        journal.info("Portique : tête de préhension estimée à %s", _deg(self._estimation_tete))

    def etapes_controle(self) -> list[Etape]:
        """Avant que rien ne bouge (avant la montée des Z)."""
        etapes = []
        if self.griffe is not None:
            etapes.append(
                Etape(
                    "griffe_controle_rotation",
                    QUOI_FAIRE_GRIFFE_A,
                    action=self.controler_griffe,
                )
            )
        if self.tete is not None:
            etapes.append(
                Etape("tete_controle_compte_tours", QUOI_FAIRE_CORDON, action=self.controler_tete)
            )
        return etapes

    # ------------------------------------------------------------ griffe

    def fanion_libre(self) -> bool:
        """Le fanion est-il libre (A de 0 à +180°) ? « Pn: » montre sa lettre quand il l'est
        (broche inversée dans fluidnc/portique.yaml)."""
        assert self._a_griffe is not None and self._fanion is not None
        return self._fanion in self._a_griffe.liaison.etat.entrees_actives

    def _vers_le_fanion(self) -> None:
        """Avant « $HA » : la tête du côté actionné (A ≤ 0), en passant par 0 sans jamais aller
        au-delà de ± 180°. L'angle de départ (gardé, 0° ou ± 180°) lève le doute au bord ± 180°."""
        assert self.griffe is not None and self._a_griffe is not None
        origine = self.griffe.origine_rotation
        assert origine is not None
        self._vu_libre = False
        libre = self.fanion_libre()
        depart = self._griffe_a_depart
        if depart > 90:
            # Vers +180 : en −, il faut voir le fanion libre puis actionné (le bord à 0°).
            self._sens = -1
            self._vu_libre = libre
        elif depart < -90:
            # Vers −180 : déjà actionné ; si libre (juste au-delà de −180°), un peu en +.
            if not libre:
                self._a_griffe.rien()
                return
            self._sens = 1
            self._vu_libre = True
        else:
            # Près de 0 : libre ⇒ en − jusqu'au fanion ; actionné ⇒ « $HA » directement.
            if not libre:
                self._a_griffe.rien()
                return
            self._sens = -1
            self._vu_libre = True
        journal.info("Griffe : recherche du fanion en %s", "−" if self._sens < 0 else "+")
        self._a_griffe.tourner_de(self._sens * origine.recherche_deg, origine.vitesse_deg_s)

    def _fanion_trouve(self) -> bool:
        assert self._a_griffe is not None
        rotation = self._a_griffe
        if rotation.commande is not None and rotation._annule_a is None:
            libre = self.fanion_libre()
            if libre:
                self._vu_libre = True
            elif self._vu_libre:
                rotation.annuler()
                journal.info("Griffe : fanion trouvé (actionné)")
                return False
            if rotation.finie("griffe, recherche du fanion", QUOI_FAIRE_FANION):
                raise ErreurEtape(
                    f"griffe : fanion pas trouvé en "
                    f"{_deg(self.griffe.origine_rotation.recherche_deg)}",  # type: ignore[union-attr]
                    QUOI_FAIRE_FANION,
                )
            return False
        return rotation.finie("griffe, recherche du fanion", QUOI_FAIRE_FANION)

    def _origine_a_griffe(self) -> None:
        assert self._a_griffe is not None
        journal.info("Griffe : prise d'origine de la rotation (« $H%s »)", self._a_griffe.lettre)
        self._a_griffe.prise_origine()

    def _aller(self, nom: str, valeurs: dict[str, float]) -> Etape:
        return Etape(
            nom,
            QUOI_FAIRE,
            action=lambda: self.axes.aller_a(valeurs, nom),
            fin=self.axes.arrives,
            delai_max=DELAI_DEPLACEMENT,
            entree=(self.axes.pretes,),
        )

    def _remonter(self) -> None:
        """A est à 0 : noté, puis les axes de la griffe remontent."""
        assert self.griffe is not None
        if self.garde is not None:
            self.garde.noter(GRIFFE_A, 0.0)
        self.axes.aller_a({GRIFFE_Z: self.machine.axes[GRIFFE_Z].course[1]}, "griffe en haut")

    def etapes_griffe(self) -> list[Etape]:
        """Après « $HB » (godet) et les Z en haut : godet fermé, au point de recherche, axes
        descendus, A sur son fanion puis à 0, axes remontés."""
        if self.griffe is None:
            return []
        point = self.griffe.point_demi_tour
        assert point is not None and self._a_griffe is not None
        fin_fanion = Condition("fanion de la rotation de la griffe trouvé", self._fanion_trouve)
        fin_origine = Condition(
            "prise d'origine de la rotation de la griffe finie",
            lambda: self._a_griffe.finie(  # type: ignore[union-attr]
                "prise d'origine de la rotation de la griffe", QUOI_FAIRE_FANION
            ),
        )
        return [
            self._aller("griffe_origine_godet_ferme", {GRIFFE_B: 0.0}),
            self._aller(
                "griffe_origine_au_point",
                {"pont_x": point.x - self.griffe.decalage_mat_x, "chariot_y": point.y},
            ),
            self._aller("griffe_origine_axes_descendus", {GRIFFE_Z: point.z}),
            Etape(
                "griffe_origine_vers_le_fanion",
                QUOI_FAIRE_FANION,
                action=self._vers_le_fanion,
                fin=fin_fanion,
                delai_max=DELAI_ORIGINE,
                entree=(self.axes.pretes,),
            ),
            Etape(
                "griffe_origine_rotation",
                QUOI_FAIRE_FANION,
                action=self._origine_a_griffe,
                fin=fin_origine,
                delai_max=DELAI_ORIGINE,
                entree=(self.axes.pretes,),
            ),
            self._aller("griffe_origine_rotation_a_0", {GRIFFE_A: 0.0}),
            Etape(
                "griffe_origine_remontee",
                QUOI_FAIRE,
                action=self._remonter,
                fin=self.axes.arrives,
                delai_max=DELAI_DEPLACEMENT,
                entree=(self.axes.pretes,),
            ),
        ]

    # ------------------------------------------------------------ tête de préhension

    def _vers_le_hall(self) -> None:
        """La tête à avant_hall_deg avant le Hall (côté −), d'après l'estimation du tour."""
        assert self.tete is not None and self._a_tete is not None
        origine = self.tete.origine_rotation
        assert origine is not None
        delta = -self._estimation_tete - origine.avant_hall_deg
        journal.info("Tête de préhension : %s vers son Hall", _deg(delta))
        if self.garde is not None:
            self.garde.noter(TETE_A, self._estimation_tete, en_rotation=True)
        self._a_tete.tourner_de(delta, origine.vitesse_deg_s)

    def _origine_tete(self) -> None:
        assert self._a_tete is not None
        journal.info("Tête de préhension : prise d'origine (« $H%s »)", self._a_tete.lettre)
        self._a_tete.prise_origine()

    def _origine_tete_finie(self) -> bool:
        assert self._a_tete is not None
        if not self._a_tete.finie("prise d'origine de la rotation de la tête", QUOI_FAIRE_HALL):
            return False
        if self.garde is not None:
            position = self._a_tete.position()
            self.garde.noter(TETE_A, 0.0 if position is None else position)
        return True

    def etapes_tete(self) -> list[Etape]:
        if self.tete is None:
            return []
        assert self._a_tete is not None
        pretes = Condition(
            "carte de la tête connectée et sans alarme",
            lambda: (
                self._a_tete.liaison.etat.connectee  # type: ignore[union-attr]
                and not self._a_tete.liaison.etat.en_alarme
            ),  # type: ignore[union-attr]
        )
        return [
            Etape(
                "tete_origine_vers_le_hall",
                QUOI_FAIRE_HALL,
                action=self._vers_le_hall,
                fin=Condition(
                    "tête de préhension près de son Hall",
                    lambda: self._a_tete.finie(  # type: ignore[union-attr]
                        "rotation de la tête vers son Hall", QUOI_FAIRE_HALL
                    ),
                ),
                delai_max=DELAI_DEPLACEMENT,
                entree=(pretes,),
            ),
            Etape(
                "tete_origine_rotation",
                QUOI_FAIRE_HALL,
                action=self._origine_tete,
                fin=Condition("prise d'origine de la tête finie", self._origine_tete_finie),
                delai_max=DELAI_ORIGINE,
                entree=(pretes,),
            ),
        ]
