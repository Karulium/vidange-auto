"""Verrous des trajets au-dessus du Stockage (fichier du fil Stockage, 31/10/2026, tâche 35).

    regles = ReglesStockage(machine)
    regles.refus_prehension(depart, arrivee, objet, piles, boucle_fermee)   # raison, ou None
    regles.refus_griffe(depart_x, arrivee_x, boucle_fermee)

Ils s'ajoutent aux règles de la préhension (vidange.prehension.regles) et de la griffe : la plus
stricte gagne. Un mouvement est vérifié point par point (pas de la préhension).

1. Boucle du stockage ouverte (tiroir sorti ou pas verrouillé, ou un panneau relevé) : aucun
   mouvement du portique (ni de la préhension, ni de la griffe).
2. Griffe : axe du mât à x ≤ griffe_x_max (butée logicielle).
3. Seau tenu, pendant un déplacement du pont (le pont et la tête ne bougent jamais ensemble) :
   a) au-dessus du plateau (x des panneaux), fond à seau_fond_min_z au moins ;
   b) jamais au-dessus d'une pile qui a des seaux, sauf celle d'où il part ou celle où il arrive,
      et alors son fond à sortie_pile_marge_m au moins au-dessus du bord de cette pile ;
   c) rail opérateur (réponses à la PR n° 52) : haut du seau au-dessus de haut_max_z seulement
      axe y + rayon du bord ≤ bord_y_max.
4. Boîtes à capsules, pendant un déplacement du pont : au-dessus de leur emprise (cercle agrandi
   du rayon de l'objet), point le plus bas à boites_bas_min_z au moins.
5. Caméra du bocal (boîtier de la griffe), à tout moment :
   - seau tenu, axe entre x coin et x seau_x_min : axe à y ≥ seau_y_libre ; et pendant un
     déplacement du pont en y < seau_y_libre, fond à seau_fond_min_z au moins (sortie de la bande
     y 0,215 vers −x) ;
   - tête vide ou autre objet : axe à y ≥ coin y + rayon tant que x est entre le bord −x du
     boîtier − rayon et coin x + rayon.

Ces verrous protègent la MACHINE, jamais les personnes (portes et arrêt d'urgence sont câblés).
"""

import math
from dataclasses import dataclass

from vidange.prehension.regles import Objet, Pose
from vidange.reglages import Machine

_EGAL = 1e-6


@dataclass(frozen=True)
class PileVue:
    """Une pile qui a des seaux, telle que l'inventaire la connaît."""

    nom: str
    x: float
    y: float
    rayon: float
    bord_z: float


def _m(valeur: float) -> str:
    return f"{valeur:.3f}".rstrip("0").rstrip(".").replace(".", ",")


class ReglesStockage:
    def __init__(self, machine: Machine) -> None:
        assert machine.stockage is not None and machine.prehension is not None
        assert machine.griffe is not None
        self.reglages = machine.stockage
        self.trajets = machine.stockage.trajets
        self.rayon_tete = machine.prehension.rayon_tete_m
        self.pas = machine.prehension.pas_verification_m
        self.boitier_x_min = machine.griffe.camera_bocal.x[0]
        panneaux = machine.stockage.panneaux.values()
        self.plateau_x = (min(p[0] for p in panneaux), max(p[1] for p in panneaux))

    # ------------------------------------------------------------ outils

    def rayon(self, objet: Objet | None) -> float:
        return self.rayon_tete if objet is None else max(self.rayon_tete, objet.rayon_m)

    @staticmethod
    def bas(pose: Pose, objet: Objet | None) -> float:
        return pose.z - (0.0 if objet is None else objet.dessous_m)

    def _points(self, depart: Pose, arrivee: Pose) -> list[Pose]:
        longueur = math.dist((depart.x, depart.y, depart.z), (arrivee.x, arrivee.y, arrivee.z))
        nombre = max(1, math.ceil(longueur / self.pas))
        return [
            Pose(
                depart.x + (arrivee.x - depart.x) * i / nombre,
                depart.y + (arrivee.y - depart.y) * i / nombre,
                depart.z + (arrivee.z - depart.z) * i / nombre,
                depart.a + (arrivee.a - depart.a) * i / nombre,
            )
            for i in range(nombre + 1)
        ]

    @staticmethod
    def _sur(pose: Pose, x: float, y: float, rayon: float) -> bool:
        return math.hypot(pose.x - x, pose.y - y) < rayon - _EGAL

    # ------------------------------------------------------------ la préhension

    def refus_prehension(
        self,
        depart: Pose,
        arrivee: Pose,
        objet: Objet | None,
        piles: list[PileVue],
        boucle_fermee: bool,
    ) -> str | None:
        """Raison du refus d'un pas de la préhension de `depart` à `arrivee`, ou None.
        `piles` : celles qui ont des seaux."""
        bouge = any(abs(getattr(arrivee, cle) - getattr(depart, cle)) > _EGAL for cle in "xyza")
        if not bouge:
            return None
        if not boucle_fermee:
            return (
                "boucle du stockage ouverte (tiroir sorti ou pas verrouillé, ou panneau P1 ou P2 "
                "relevé) : aucun mouvement du portique"
            )
        bouge_xy = abs(arrivee.x - depart.x) > _EGAL or abs(arrivee.y - depart.y) > _EGAL
        seau = objet is not None and objet.sorte == "seau"
        rayon = self.rayon(objet)
        bouts = [
            pile
            for pile in piles
            if self._sur(depart, pile.x, pile.y, pile.rayon + rayon)
            or self._sur(arrivee, pile.x, pile.y, pile.rayon + rayon)
        ]
        decalage_x = 0.0 if objet is None else objet.decalage_x_m
        for pose in self._points(depart, arrivee):
            # L'objet tenu hors d'axe (entonnoir par son oreille) : ses règles valent pour son axe.
            centre = pose if decalage_x == 0.0 else pose.avec(x=pose.x + decalage_x)
            refus = self._refus_camera_bocal(centre, objet, seau, rayon, bouge_xy)
            if refus is not None:
                return refus
            if not bouge_xy:
                continue
            refus = self._refus_boites(centre, objet, rayon)
            if refus is not None:
                return refus
            if seau:
                assert objet is not None
                refus = self._refus_seau(pose, objet, rayon, piles, bouts)
                if refus is not None:
                    return refus
        return None

    def _refus_camera_bocal(
        self, pose: Pose, objet: Objet | None, seau: bool, rayon: float, bouge_xy: bool
    ) -> str | None:
        camera = self.trajets.camera_bocal
        coin_x, coin_y = camera.coin
        if seau:
            if coin_x - _EGAL <= pose.x < camera.seau_x_min - _EGAL and (
                pose.y < camera.seau_y_libre - _EGAL
            ):
                return (
                    f"caméra du bocal : seau tenu à x {_m(pose.x)}, y {_m(pose.y)} m ; entre x "
                    f"{_m(coin_x)} et {_m(camera.seau_x_min)}, l'axe reste à y ≥ "
                    f"{_m(camera.seau_y_libre)} m"
                )
            # Le fond minimal vaut pour le trajet, pas pour la sortie tout droit vers le haut.
            fond = self.bas(pose, objet)
            if (
                bouge_xy
                and pose.x >= coin_x - _EGAL
                and pose.y < camera.seau_y_libre - _EGAL
                and fond < camera.seau_fond_min_z - _EGAL
            ):
                return (
                    f"sortie de la bande y < {_m(camera.seau_y_libre)} : fond du seau à "
                    f"{_m(fond)} m, il faut {_m(camera.seau_fond_min_z)} m au moins"
                )
            return None
        if (
            self.boitier_x_min - rayon + _EGAL < pose.x < coin_x + rayon - _EGAL
            and pose.y < coin_y + rayon - _EGAL
        ):
            return (
                f"caméra du bocal : tête à x {_m(pose.x)}, y {_m(pose.y)} m ; tant que x < "
                f"{_m(coin_x + rayon)}, l'axe reste à y ≥ {_m(coin_y + rayon)} m"
            )
        return None

    def _au_dessus_du_plateau(self, pose: Pose, rayon: float) -> bool:
        debut, fin = self.plateau_x
        return debut - rayon < pose.x < fin + rayon

    def _refus_boites(self, pose: Pose, objet: Objet | None, rayon: float) -> str | None:
        boites = self.reglages.boites
        bas = self.bas(pose, objet)
        if bas >= self.trajets.boites_bas_min_z - _EGAL:
            return None
        for nom, (x, y) in boites.places.items():
            if self._sur(pose, x, y, boites.diametre_m / 2 + rayon):
                return (
                    f"boîte à capsules « {nom} » : au-dessus d'elle, point le plus bas à "
                    f"{_m(self.trajets.boites_bas_min_z)} m au moins (il est à {_m(bas)} m)"
                )
        return None

    def _refus_seau(
        self,
        pose: Pose,
        objet: Objet,
        rayon: float,
        piles: list[PileVue],
        bouts: list[PileVue],
    ) -> str | None:
        t = self.trajets
        fond = self.bas(pose, objet)
        bord = pose.z + objet.dessus_m
        if self._au_dessus_du_plateau(pose, rayon) and fond < t.seau_fond_min_z - _EGAL:
            return (
                f"seau tenu au-dessus du stockage : fond à {_m(fond)} m, il faut "
                f"{_m(t.seau_fond_min_z)} m au moins"
            )
        for pile in piles:
            if not self._sur(pose, pile.x, pile.y, pile.rayon + rayon):
                continue
            if pile not in bouts:
                return (
                    f"seau tenu au-dessus de la pile « {pile.nom} », qui a des seaux : "
                    "il faut la contourner (ordre de vidage)"
                )
            minimum = pile.bord_z + t.sortie_pile_marge_m
            if fond < minimum - _EGAL:
                return (
                    f"seau tenu au-dessus de la pile « {pile.nom} » : fond à {_m(fond)} m, il "
                    f"faut {_m(minimum)} m au moins (bord de la pile + "
                    f"{_m(t.sortie_pile_marge_m * 100)} cm)"
                )
        rail = t.rail_operateur
        cote_allee = pose.y + objet.decalage_y_m + objet.rayon_m
        if bord > rail.haut_max_z + _EGAL and cote_allee > rail.bord_y_max + _EGAL:
            return (
                f"rail opérateur : seau tenu en haut à {_m(bord)} m (plus de "
                f"{_m(rail.haut_max_z)} m) : il faut axe y + rayon du bord ≤ "
                f"{_m(rail.bord_y_max)} m (il est à {_m(cote_allee)} m)"
            )
        return None

    # ------------------------------------------------------------ la griffe

    def refus_griffe(self, depart_x: float, arrivee_x: float, boucle_fermee: bool) -> str | None:
        if not boucle_fermee:
            return (
                "boucle du stockage ouverte (tiroir sorti ou pas verrouillé, ou panneau P1 ou P2 "
                "relevé) : aucun mouvement du portique"
            )
        x_max = self.trajets.griffe_x_max
        if max(depart_x, arrivee_x) > x_max + _EGAL:
            return f"griffe : axe du mât à x ≤ {_m(x_max)} m (au-dessus du stockage)"
        return None

    # ------------------------------------------------------------ hublot de la caméra du fond

    def refus_photo_du_fond(self, fond_bocal_z: float, entonnoir_sur_plateau: bool) -> str | None:
        """Photo du fond d'un bocal présenté au hublot : fond dans la plage, pas d'entonnoir."""
        if entonnoir_sur_plateau:
            return "photo du fond refusée : l'entonnoir est sur le plateau"
        debut, fin = self.reglages.hublot.fond_bocal_z
        if not debut - _EGAL <= fond_bocal_z <= fin + _EGAL:
            return (
                f"photo du fond refusée : fond du bocal à {_m(fond_bocal_z)} m, il faut "
                f"{_m(debut)} à {_m(fin)} m"
            )
        return None
