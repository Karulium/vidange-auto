"""Règles de position de la griffe (plan de commande v221, fiche « Griffe sur mât »).

    regles = ReglesGriffe(reglages.machine)
    regles.refus_pose(pose, contexte)               # raison du refus, ou None
    regles.refus_mouvement(depart, arrivee, contexte)

Une Pose dit où est la tête : mât en x et y, hauteur des axes z, rotation a (°), ouverture du
godet b (0 fermé, 1 grand ouvert). Un mouvement va en ligne droite sur tous les axes à la fois
(comme FluidNC) : il est vérifié point par point (`pas_verification_m`), plus les règles de
trajet (jamais en diagonale entre le fût et le poste de remplissage).

L'encombrement de la tête (`griffe → tete`) compte pour les obstacles : poignée du volet,
boîtier de la caméra du bocal, bout côté fût, porte du spray, garage de l'agitateur (tête
tournée). Vue de dessus, la tête est un rectangle autour du mât (le long du bras, en travers)
plus la lame de la raclette (un segment en travers) ; en hauteur, elle va de son bas vers le haut.

Tous les chiffres viennent de machine.yaml (`griffe`, `poste_fut`, courses des axes).
Ces verrous ne protègent que la MACHINE : la sécurité des personnes reste câblée.
"""

import math
from dataclasses import dataclass, replace

from vidange.geometrie import Forme, touche_rectangle
from vidange.poste_fut import regles as regles_poste
from vidange.reglages import Machine

# Écart sous lequel deux valeurs sont égales (m ou °).
_EGAL = 1e-6
# Assez loin pour une zone ouverte d'un côté (« x < 0,50 »), en m.
_LOIN = 10.0


@dataclass(frozen=True)
class Pose:
    x: float  # mât (m)
    y: float  # mât (m)
    z: float  # hauteur des axes de la tête (m)
    a: float  # rotation de la tête (°)
    b: float  # ouverture du godet : 0 fermé, 1 grand ouvert

    def avec(self, **valeurs: float) -> "Pose":
        return replace(self, **valeurs)


@dataclass(frozen=True)
class Contexte:
    """Ce que les autres modules disent (cases vides tant qu'ils ne sont pas écrits)."""

    mode: str = "production"
    # Pas de capteur du volet du dessus : relevé en mode lavage, contact du panneau ouvert.
    volet_releve: bool = False
    porte_spray_ouverte: bool = False
    dosage_en_cours: bool = False


def _m(valeur: float) -> str:
    return f"{valeur:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def ecart_angle(a: float, b: float) -> float:
    """Écart entre deux angles (°), de 0 à 180."""
    return abs((a - b + 180) % 360 - 180)


class ReglesGriffe:
    def __init__(self, machine: Machine) -> None:
        assert machine.griffe is not None and machine.poste_fut is not None
        self.griffe = machine.griffe
        self.poste = machine.poste_fut
        self.courses = {nom: machine.axes[nom].course for nom in ("pont_x", "chariot_y")}
        self.courses.update(z=machine.axes["griffe_z"].course, a=machine.axes["griffe_a"].course)

    # ------------------------------------------------------------ outils

    def bas(self, pose: Pose) -> float:
        """Bas du godet (pris pour le bas de la tête)."""
        return pose.z - self.griffe.bas_godet_sous_axes

    def pont(self, pose: Pose) -> float:
        return pose.x - self.griffe.decalage_mat_x

    def distance_axe_fut(self, x: float, y: float) -> float:
        centre_x, centre_y = self.poste.centre_fut
        return math.hypot(x - centre_x, y - centre_y)

    def au_dessus_du_fut(self, x: float, y: float) -> bool:
        return regles_poste.au_dessus_du_fut(self.poste, x, y)

    def dans_le_fut(self, pose: Pose) -> bool:
        """Bas du godet sous le bord du fût, au-dessus de son ouverture."""
        return self.bas(pose) < self.poste.fut_bord_z and self.au_dessus_du_fut(pose.x, pose.y)

    def en_butee_haute(self, z: float) -> bool:
        """Les axes de la tête sont-ils en butée haute (fin de la course de griffe_z) ?"""
        return z >= self.courses["z"][1] - self.griffe.tolerance_butee_haute_m

    def bloquee(self, a: float) -> bool:
        """La tête est-elle à une orientation bloquée (bras le long du pont) ?"""
        rotation = self.griffe.rotation
        return any(
            ecart_angle(a, cible) <= rotation.tolerance_deg
            for cible in rotation.orientations_bloquees_deg
        )

    def ecart_bloquee(self, a: float) -> float:
        return min(ecart_angle(a, c) for c in self.griffe.rotation.orientations_bloquees_deg)

    def encombrement(self, pose: Pose, longueur: float | None = None) -> tuple[Forme, Forme]:
        """La tête vue de dessus : son corps (rectangle) et la lame de la raclette (segment).
        longueur : demi-longueur le long du bras, si on ne regarde qu'une partie de la tête."""
        tete = self.griffe.tete
        if longueur is None:
            longueur = tete.demi_longueur_ouvert if pose.b > _EGAL else tete.demi_longueur_ferme
        largeur = tete.demi_largeur
        angle = math.radians(self.griffe.raclette_angle_deg + pose.a)
        # u : en travers du bras, vers la raclette ; v : le long du bras.
        ux, uy = math.cos(angle), math.sin(angle)
        vx, vy = -uy, ux

        def point(le_long: float, en_travers: float) -> tuple[float, float]:
            return (
                pose.x + le_long * vx + en_travers * ux,
                pose.y + le_long * vy + en_travers * uy,
            )

        corps = [
            point(longueur, largeur),
            point(-longueur, largeur),
            point(-longueur, -largeur),
            point(longueur, -largeur),
        ]
        raclette = [point(0, largeur), point(0, self.griffe.raclette_decalage_m)]
        return corps, raclette

    def _touche(
        self,
        pose: Pose,
        x: tuple[float, float],
        y: tuple[float, float],
        longueur: float | None = None,
    ) -> bool:
        return any(touche_rectangle(forme, x, y) for forme in self.encombrement(pose, longueur))

    def _classe_ouverture(self, b: float) -> int:
        """0 : fermé ; 1 : à moitié ouvert au plus ; 2 : plus ouvert."""
        if b <= _EGAL:
            return 0
        return 1 if b <= 0.5 + _EGAL else 2

    # ------------------------------------------------------------ une pose

    def refus_pose(self, pose: Pose, contexte: Contexte) -> str | None:
        g, poste = self.griffe, self.poste
        bas = self.bas(pose)
        pont = self.pont(pose)
        debut, fin = self.courses["pont_x"]
        if not debut - _EGAL <= pont <= fin + _EGAL or pont < g.pont_x_min - _EGAL:
            return f"pont à x {_m(pont)} m, hors de sa course ({_m(debut)} à {_m(fin)} m)"
        for nom, valeur, (debut, fin) in (
            ("mât en y", pose.y, self.courses["chariot_y"]),
            ("axes de la tête en z", pose.z, self.courses["z"]),
            ("rotation de la tête", pose.a, self.courses["a"]),
        ):
            if not debut - _EGAL <= valeur <= fin + _EGAL:
                return f"{nom} à {_m(valeur)}, hors de la course ({_m(debut)} à {_m(fin)})"
        if pose.b < -_EGAL:
            return "godet au-delà de « fermé » (le capot du boîtier de tête n'a que 4 mm de garde)"
        if pose.b > 1 + _EGAL:
            return "godet au-delà de « grand ouvert »"
        classe = self._classe_ouverture(pose.b)
        if classe:
            debut, fin = g.mat_y_grand_ouvert
            if not debut - _EGAL <= pose.y <= fin + _EGAL:
                return (
                    f"godet ouvert avec le mât à y {_m(pose.y)} m : permis de y {_m(debut)} "
                    f"à {_m(fin)} m seulement"
                )
        for bande in g.garage_glissiere:
            if bande.permise_en_butee_haute and self.en_butee_haute(pose.z):
                continue
            minimum = bande.y_min[classe]
            if not self.bloquee(pose.a):
                # Tête tournée : elle dépasse en y plus que bras le long du pont.
                tete = g.tete
                minimum = (
                    bande.y_min[2]
                    if classe
                    else minimum + tete.rayon_balaye - tete.demi_longueur_ferme
                )
            if bande.x[0] <= pose.x <= bande.x[1] and pose.y < minimum - _EGAL:
                butee = " (ou la tête en butée haute)" if bande.permise_en_butee_haute else ""
                return (
                    f"garage ou glissière de l'agitateur : mât à x {_m(pose.x)}, "
                    f"y {_m(pose.y)} m ; il faut y ≥ {_m(minimum)} m ici{butee}"
                )
        if contexte.dosage_en_cours and pose.x > g.dosage.mat_x_max and pose.y < g.dosage.mat_y_min:
            return (
                f"dosage du mycélium en cours : mât à x ≤ {_m(g.dosage.mat_x_max)} m ou "
                f"y ≥ {_m(g.dosage.mat_y_min)} m"
            )
        camera = g.camera_bocal
        # Seule la partie haute de la tête (les bras) arrive à la hauteur du boîtier : elle seule
        # peut le toucher.
        haut_seul = (
            g.tete.demi_longueur_haut if pose.z - g.tete.haut_sous_axes <= camera.z_bas else None
        )
        if bas < camera.bas_z_max - _EGAL and self._touche(pose, camera.x, camera.y, haut_seul):
            return (
                f"la tête toucherait le boîtier de la caméra du bocal (x {_m(camera.x[0])} à "
                f"{_m(camera.x[1])}, y {_m(camera.y[0])} à {_m(camera.y[1])} m) : bas de la "
                f"tête à {_m(bas)} m, sous {_m(camera.bas_z_max)} m"
            )
        if contexte.porte_spray_ouverte and self._touche(
            pose, (-_LOIN, g.porte_spray.x_max), (-_LOIN, g.porte_spray.y_max)
        ):
            return (
                f"porte du coffret du spray ouverte : griffe interdite en x < "
                f"{_m(g.porte_spray.x_max)} m et y < {_m(g.porte_spray.y_max)} m"
            )
        refus = self._refus_rotation(pose)
        if refus is not None:
            return refus
        refus = regles_poste.refus_griffe(
            poste, pose.x, pose.y, bas, contexte.volet_releve, self.encombrement(pose)
        )
        if refus is not None:
            return refus
        return self._refus_fut(pose, bas)

    def _refus_rotation(self, pose: Pose) -> str | None:
        rotation = self.griffe.rotation
        if pose.z > rotation.bloquee_z_min + _EGAL and not self.bloquee(pose.a):
            return (
                f"tête tournée à {_m(pose.a)}° avec les axes à {_m(pose.z)} m : au-dessus de "
                f"{_m(rotation.bloquee_z_min)} m, orientation bloquée (bras le long du pont)"
            )
        if (
            pose.z > rotation.libre_z_max + _EGAL
            and pose.b > _EGAL
            and self.ecart_bloquee(pose.a) > rotation.ouvert_ecart_max_deg + _EGAL
        ):
            return (
                f"godet ouvert, tête tournée de plus de {_m(rotation.ouvert_ecart_max_deg)}° "
                f"avec les axes au-dessus de {_m(rotation.libre_z_max)} m"
            )
        return None

    def _refus_fut(self, pose: Pose, bas: float) -> str | None:
        g, poste = self.griffe, self.poste
        distance = self.distance_axe_fut(pose.x, pose.y)
        if self.dans_le_fut(pose):
            if distance > g.fut_rayon_mat_max_m + _EGAL:
                return (
                    f"dans le fût, mât à {_m(distance)} m de son axe : au plus "
                    f"{_m(g.fut_rayon_mat_max_m)} m"
                )
            if pose.x < poste.centre_fut[0] - g.fut_moins_x_max_m - _EGAL:
                return (
                    f"dans le fût, côté −x, le mât ne va qu'à {_m(g.fut_moins_x_max_m)} m "
                    "de l'axe du fût"
                )
        bout = g.bout_cote_fut
        formes = self.encombrement(pose)
        tete_x = min(x for forme in formes for x, _ in forme)
        # Mât au-dessus de l'intérieur du fût : ce sont les règles du fût qui comptent.
        if tete_x < bout.x_max - _EGAL and distance >= poste.fut_diametre_interieur / 2:
            rayon = max(math.dist((x, y), (pose.x, pose.y)) for forme in formes for x, y in forme)
            paroi = distance - rayon <= poste.ouverture_diametre / 2
            minimum = bout.bas_min_paroi if paroi else bout.bas_min_hors_fut
            if bas < minimum - _EGAL:
                ou = "au-dessus de la paroi du fût" if paroi else "hors du fût"
                return (
                    f"tête sous x {_m(bout.x_max)} m {ou} : bas de la tête à "
                    f"{_m(bas)} m, il faut au moins {_m(minimum)} m"
                )
        return None

    # ------------------------------------------------------------ un mouvement

    def refus_mouvement(self, depart: Pose, arrivee: Pose, contexte: Contexte) -> str | None:
        refus = self._refus_trajet(depart, arrivee)
        if refus is not None:
            return refus
        tourne = abs(depart.a - arrivee.a) > _EGAL
        if tourne and max(self.pont(depart), self.pont(arrivee)) > self.griffe.rotation.pont_x_max:
            return (
                f"pas de rotation de la tête quand le pont est au-delà de x "
                f"{_m(self.griffe.rotation.pont_x_max)} m"
            )
        longueur = max(
            math.dist((depart.x, depart.y, depart.z), (arrivee.x, arrivee.y, arrivee.z)),
            # La rotation et le godet comptent aussi : 1° ≈ 1 mm, godet entier ≈ 3 cm.
            abs(arrivee.a - depart.a) / 1000,
            abs(arrivee.b - depart.b) * 0.03,
        )
        points = max(1, math.ceil(longueur / self.griffe.pas_verification_m))
        for i in range(points + 1):
            t = i / points
            pose = Pose(
                *(
                    debut + (fin - debut) * t
                    for debut, fin in zip(
                        (depart.x, depart.y, depart.z, depart.a, depart.b),
                        (arrivee.x, arrivee.y, arrivee.z, arrivee.a, arrivee.b),
                        strict=True,
                    )
                )
            )
            refus = self.refus_pose(pose, contexte)
            if refus is not None:
                return refus
        return None

    def _refus_trajet(self, depart: Pose, arrivee: Pose) -> str | None:
        """Trajet fût ↔ poste de remplissage : jamais en diagonale."""
        trajet = self.griffe.trajet
        bouge_x = abs(arrivee.x - depart.x) > _EGAL
        bouge_y = abs(arrivee.y - depart.y) > _EGAL
        if not (bouge_x or bouge_y):
            return None
        dedans = self.au_dessus_du_fut(depart.x, depart.y) and self.au_dessus_du_fut(
            arrivee.x, arrivee.y
        )
        cote_seau = min(depart.x, arrivee.x) >= trajet.mat_x_min_pour_y - _EGAL
        if dedans or cote_seau:
            return None
        if bouge_x and bouge_y:
            return "trajet en diagonale refusé : d'abord en x, puis en y"
        if bouge_x and min(depart.y, arrivee.y) < trajet.mat_y_min - _EGAL:
            return f"trajet en x avec le mât à y < {_m(trajet.mat_y_min)} m refusé"
        if bouge_y:
            return (
                f"trajet en y avec le mât à x < {_m(trajet.mat_x_min_pour_y)} m refusé "
                "(seulement au-dessus du fût, ou côté remplissage)"
            )
        return None
