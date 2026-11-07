"""Zone du bras du spray (fil Spray, 07/11/2026 ; réponse à la PR n° 99, point 4).

    zone = ZoneDuBras(reglages.machine, griffe=griffe, prehension=prehension)
    zone.refus()       # raison (« la tête de la griffe est dans la zone... »), ou None
    zone.libre()       # condition d'entrée de « sortir le bras » et de « ranger le bras »
    zone.brancher()    # verrou : tant que le bras n'est pas vu rangé, rien n'entre dans la zone

Le bras du spray ne sort et ne rentre que si aucune partie de la tête de la griffe, de la tête de
préhension ou de ce qu'elles tiennent n'est dans la zone `spray → bras → zone` (x, y, plus bas
que z_max). C'est la ZONE qui fait foi, pas le moment (« griffe partie du poste ») : chaque outil
est regardé là où il est, qu'il ait bougé lui-même ou qu'il ait été traîné par le pont (en butée
haute, avec sa charge : un seau pendu sous la tête de préhension descend plus bas qu'elle).

Vue de dessus : la griffe est son encombrement (corps et raclette, godet ouvert ou fermé, règles
de la griffe), de son bas (bas du godet) vers le haut ; la préhension est un disque autour de son
axe (rayon de la tête) dont le bas est la face, et l'objet tenu un disque autour de son axe à lui
(décalé pour l'entonnoir) dont le bas est la face moins ce qui pend dessous.

Verrou pendant que le bras bouge (tâche 45 octies, réponse à la PR n° 100, point 3) : tant que
le bras sort, rentre ou n'est pas vu rangé et arrêté par la carte (`bras_au_repos`), ni la
griffe, ni la préhension, ni ce qu'elles tiennent, ni l'outil traîné par le pont (en butée haute,
avec sa charge) n'ENTRENT dans la zone. Le pas qui y entrerait ATTEND (il ne part pas, rien ne
bouge) que le bras soit vu rangé, au plus `zone → attente_max_s`, puis alarme. Un outil déjà dans
la zone peut en sortir. Et l'inverse : un pas en route qui va dans la zone (lancé avant que le
bras bouge) rend la zone occupée pour le bras, comme si l'outil y était déjà. Les zones du chef
(chef.zones) ne servent pas ici : un module les tient pour toute une étape, et les étapes de la
griffe et de la préhension (une couche, un geste) ne passent dans la zone que quelques secondes.

Position d'un outil inconnue : la zone n'est pas libre (on ne bouge pas à l'aveugle). Sans griffe
ou sans préhension branchée (simulateur, essais), seul l'autre est regardé. Les chiffres sont dans
machine.yaml (spray → bras → zone, EXEMPLE tant que la Maquette ne l'a pas balayée). Ce verrou ne
protège que la MACHINE : la sécurité des personnes reste câblée.
"""

import math
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

from vidange.geometrie import touche_rectangle
from vidange.reglages import Machine, ZoneBrasSpray

if TYPE_CHECKING:
    from vidange.griffe.griffe import Griffe
    from vidange.griffe.regles import Pose as PoseGriffe
    from vidange.griffe.regles import ReglesGriffe
    from vidange.prehension.prehension import Prehension
    from vidange.prehension.regles import Objet, ReglesPrehension
    from vidange.prehension.regles import Pose as PosePrehension

# Recouvrement sous lequel on ne compte pas un outil dans la zone (bord contre bord), en m.
_EGAL = 1e-6


def _m(valeur: float) -> str:
    return f"{valeur:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def _disque_dedans(zone: ZoneBrasSpray, x: float, y: float, rayon: float) -> bool:
    dx = max(zone.x[0] - x, 0.0, x - zone.x[1])
    dy = max(zone.y[0] - y, 0.0, y - zone.y[1])
    return math.hypot(dx, dy) < rayon - _EGAL


def griffe_dans_la_zone(zone: ZoneBrasSpray, regles: "ReglesGriffe", pose: "PoseGriffe") -> bool:
    """Une partie de la tête de la griffe (ou ce qu'elle tient, dans son godet) dans la zone ?"""
    if regles.bas(pose) >= zone.z_max - _EGAL:
        return False
    return any(touche_rectangle(forme, zone.x, zone.y) for forme in regles.encombrement(pose))


def prehension_dans_la_zone(
    zone: ZoneBrasSpray,
    regles: "ReglesPrehension",
    pose: "PosePrehension",
    objet: "Objet | None",
) -> bool:
    """Une partie de la tête de préhension ou de l'objet qu'elle tient dans la zone ?"""
    if pose.z < zone.z_max - _EGAL and _disque_dedans(
        zone, pose.x, pose.y, regles.reglages.rayon_tete_m
    ):
        return True
    if objet is None:
        return False
    return regles.bas(pose, objet) < zone.z_max - _EGAL and _disque_dedans(
        zone, pose.x + objet.decalage_x_m, pose.y + objet.decalage_y_m, objet.rayon_m
    )


def _le_long(depart, arrivee, pas: float) -> Iterator:
    """Les poses d'un mouvement, de `depart` à `arrivee` (toutes les valeurs ensemble), tous les
    `pas` mètres au plus (1° compte pour 1 mm, comme les règles de la griffe)."""
    champs = list(vars(depart))
    longueur = max(
        math.dist((depart.x, depart.y, depart.z), (arrivee.x, arrivee.y, arrivee.z)),
        abs(arrivee.a - depart.a) / 1000,
    )
    nombre = max(1, math.ceil(longueur / pas))
    for i in range(nombre + 1):
        t = i / nombre
        yield depart.avec(
            **{
                c: getattr(depart, c) + (getattr(arrivee, c) - getattr(depart, c)) * t
                for c in champs
            }
        )


def _decale(pose, dx: float, dy: float):
    return pose.avec(x=pose.x + dx, y=pose.y + dy)


class ZoneDuBras:
    def __init__(
        self,
        machine: Machine,
        griffe: "Griffe | None" = None,
        prehension: "Prehension | None" = None,
        bras_au_repos: Callable[[], bool] | None = None,
    ) -> None:
        """`bras_au_repos` : le bras est vu rangé et arrêté par la carte, aucun ordre de sortie en
        route (Spray : `not spray.bras_spray_sorti()`). None : pas de spray, pas de verrou."""
        assert machine.spray is not None
        self.zone = machine.spray.bras.zone
        self.attente_max_s = self.zone.attente_max_s
        self.griffe = griffe
        self.prehension = prehension
        self.bras_au_repos = bras_au_repos

    # ------------------------------------------------------------ le verrou (tâche 45 octies)

    def verrouillee(self) -> bool:
        """Le bras sort, rentre, ou n'est pas vu rangé et arrêté : rien n'entre dans la zone.
        Lecture impossible : verrouillée (prudent)."""
        if self.bras_au_repos is None:
            return False
        try:
            return not self.bras_au_repos()
        except Exception:
            return True

    def brancher(self) -> None:
        """Chaque pas de la griffe et de la préhension passe par le verrou (il attend s'il est
        refusé)."""
        if self.griffe is not None:
            self.griffe.verrou_spray = self.refus_griffe
            self.griffe.attente_spray_max_s = self.attente_max_s
        if self.prehension is not None:
            self.prehension.verrou_spray = self.refus_prehension
            self.prehension.attente_spray_max_s = self.attente_max_s

    def _griffe_entre(self, depart: "PoseGriffe", arrivee: "PoseGriffe") -> bool:
        """Le mouvement fait-il entrer une partie de la tête de la griffe dans la zone ?"""
        griffe = self.griffe
        assert griffe is not None
        regles = griffe.regles
        if griffe_dans_la_zone(self.zone, regles, depart):
            return False
        pas = griffe.reglages.pas_verification_m
        return any(
            griffe_dans_la_zone(self.zone, regles, p) for p in _le_long(depart, arrivee, pas)
        )

    def _prehension_entre(self, depart: "PosePrehension", arrivee: "PosePrehension") -> bool:
        """Le mouvement fait-il entrer la tête de préhension ou ce qu'elle tient dans la zone ?"""
        prehension = self.prehension
        assert prehension is not None
        regles, objet = prehension.regles, prehension.objet
        if prehension_dans_la_zone(self.zone, regles, depart, objet):
            return False
        pas = prehension.reglages.pas_verification_m
        return any(
            prehension_dans_la_zone(self.zone, regles, p, objet)
            for p in _le_long(depart, arrivee, pas)
        )

    def _texte_attente(self, qui: str) -> str:
        return f"{qui} entrerait dans la {self._texte_zone()} pendant que le bras bouge"

    def refus_griffe(self, depart: "PoseGriffe", arrivee: "PoseGriffe") -> str | None:
        """Verrou d'un pas de la griffe (et de la tête de préhension qu'il traîne)."""
        if not self.verrouillee():
            return None
        if self.griffe is not None and self._griffe_entre(depart, arrivee):
            return self._texte_attente("la tête de la griffe")
        dx, dy = arrivee.x - depart.x, arrivee.y - depart.y
        if self.prehension is not None and (abs(dx) > _EGAL or abs(dy) > _EGAL):
            try:
                tete = self.prehension.tete.position()
            except Exception as erreur:
                return f"position de la préhension inconnue ({erreur}) : {self._texte_zone()}"
            if self._prehension_entre(tete, _decale(tete, dx, dy)):
                return self._texte_attente("la tête de préhension (traînée par le pont)")
        return None

    def refus_prehension(self, depart: "PosePrehension", arrivee: "PosePrehension") -> str | None:
        """Verrou d'un pas de la préhension (et du mât de la griffe qu'il traîne)."""
        if not self.verrouillee():
            return None
        if self.prehension is not None and self._prehension_entre(depart, arrivee):
            return self._texte_attente("la tête de préhension (ou ce qu'elle tient)")
        dx, dy = arrivee.x - depart.x, arrivee.y - depart.y
        if self.griffe is not None and (abs(dx) > _EGAL or abs(dy) > _EGAL):
            try:
                mat = self.griffe.bras.position()
            except Exception as erreur:
                return f"position de la griffe inconnue ({erreur}) : {self._texte_zone()}"
            if self._griffe_entre(mat, _decale(mat, dx, dy)):
                return self._texte_attente("la tête de la griffe (traînée par le pont)")
        return None

    def _refus_en_route(self) -> str | None:
        """Un pas en route (déjà parti) qui va dans la zone : elle est prise pour le bras."""
        griffe, prehension = self.griffe, self.prehension
        trajet_g = None if griffe is None else griffe.trajet_en_cours()
        trajet_p = None if prehension is None else prehension.trajet_en_cours()
        if trajet_g is not None:
            depart, arrivee = trajet_g
            if self._griffe_entre(depart, arrivee):
                return f"la tête de la griffe va dans la {self._texte_zone()}"
            if prehension is not None:
                tete = prehension.tete.position()
                courant = griffe.bras.position()  # type: ignore[union-attr]
                debut = _decale(tete, depart.x - courant.x, depart.y - courant.y)
                fin = _decale(debut, arrivee.x - depart.x, arrivee.y - depart.y)
                if self._prehension_entre(debut, fin):
                    return f"la tête de préhension, traînée, va dans la {self._texte_zone()}"
        if trajet_p is not None:
            depart, arrivee = trajet_p
            if self._prehension_entre(depart, arrivee):
                return f"la tête de préhension va dans la {self._texte_zone()}"
            if griffe is not None:
                mat = griffe.bras.position()
                courant = prehension.tete.position()  # type: ignore[union-attr]
                debut = _decale(mat, depart.x - courant.x, depart.y - courant.y)
                fin = _decale(debut, arrivee.x - depart.x, arrivee.y - depart.y)
                if self._griffe_entre(debut, fin):
                    return f"la tête de la griffe, traînée, va dans la {self._texte_zone()}"
        return None

    def _texte_zone(self) -> str:
        zone = self.zone
        return (
            f"zone du bras du spray (x {_m(zone.x[0])} à {_m(zone.x[1])}, y {_m(zone.y[0])} à "
            f"{_m(zone.y[1])}, sous z {_m(zone.z_max)} m)"
        )

    def refus(self) -> str | None:
        """Pourquoi le bras ne peut pas bouger maintenant (None : la zone est libre)."""
        griffe, prehension = self.griffe, self.prehension
        if griffe is not None:
            try:
                pose = griffe.bras.position()
            except Exception as erreur:
                return f"position de la griffe inconnue ({erreur}) : {self._texte_zone()}"
            if griffe_dans_la_zone(self.zone, griffe.regles, pose):
                return f"la tête de la griffe est dans la {self._texte_zone()}"
        if prehension is not None:
            try:
                pose_p = prehension.tete.position()
            except Exception as erreur:
                return f"position de la préhension inconnue ({erreur}) : {self._texte_zone()}"
            if prehension_dans_la_zone(self.zone, prehension.regles, pose_p, prehension.objet):
                tenu = "" if prehension.objet is None else f" (ou le/la {prehension.objet.sorte})"
                return f"la tête de préhension{tenu} est dans la {self._texte_zone()}"
        try:
            return self._refus_en_route()
        except Exception as erreur:
            return f"position d'un outil inconnue ({erreur}) : {self._texte_zone()}"

    def libre(self) -> bool:
        return self.refus() is None
