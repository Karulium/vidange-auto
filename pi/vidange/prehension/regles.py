"""Règles de mouvement de la préhension (fiche du module, validé le 27/10/2026 ; plan de
commande v221).

    regles = ReglesPrehension(reglages.machine)
    regles.refus_pose(pose, contexte)               # raison du refus, ou None
    regles.refus_mouvement(depart, arrivee, contexte)

Une Pose dit où est la tête : son axe en x et y, la hauteur z de sa FACE, sa rotation a (°).
Un Objet est ce qu'elle tient : il dépasse au-dessus de la face (un seau pris par son fond, de
l'intérieur) ou au-dessous (couvercle, bocal, capsule), sur un rayon autour de l'axe.

Les règles (verrous du logiciel : ils protègent la MACHINE, jamais les personnes) :
1. XY sur la carte du pont, puis Z sur la carte de la tête, jamais les deux à la fois ; la
   tête est en haut avant tout déplacement du pont (« en haut » : la face en butée haute, ou
   moins haut si un seau tenu l'impose, règle 3).
2. Isolation du fût : axe de la tête sous x isolation_fut_x_max et panneau du poste du fût pas vu
   « rabattu » ⇒ face en haut. Seule exception, la petite zone du garage (porte_bocal →
   zone_garage_m autour du bocal) : la tête y descend à la verticale, seulement agitateur au
   garage manivelle en bas (avec la course déclarée), griffe en butée haute, et, pour descendre,
   mors ouverts pour poser un bocal, serrés pour le prendre (ces conditions valent aussi panneau
   rabattu). Manivelle pas en bas, la tête ne passe jamais au-dessus du bocal au garage (sa
   capsule est plus haute que la butée haute de la tête).
3. Seau tenu : son bord au plus à bord_max_operateur_z côté opérateur, à bord_max_piles_z
   au-dessus des piles.
4. Boîtier de la caméra du bocal (griffe → camera_bocal) : près de lui, la tête et l'objet tenu
   restent au-dessus de son haut + marge.
5. Caméra du dosage : pendant qu'elle pivote, la tête n'entre pas dans sa boîte.
De plus : la tête ne tourne jamais entre les mors du porte-bocal ; le pont respecte le verrou du
poste du fût (pas de pont dans la zone du chariot pendant l'échange du fût).

Tous les chiffres viennent de machine.yaml (`prehension`, `griffe → camera_bocal`, `poste_fut`,
`mycelium → course_agitation_m`).
"""

import math
from dataclasses import dataclass, replace

from vidange.poste_fut import regles as regles_poste
from vidange.reglages import Machine, ObjetPrehension

# Écart sous lequel deux valeurs sont égales (m ou °).
_EGAL = 1e-6


@dataclass(frozen=True)
class Pose:
    x: float  # axe de la tête (m)
    y: float  # axe de la tête (m)
    z: float  # face de la tête (m)
    a: float  # rotation de la tête (°)

    def avec(self, **valeurs: float) -> "Pose":
        return replace(self, **valeurs)


@dataclass(frozen=True)
class Objet:
    """Ce que tient la tête."""

    sorte: str
    rayon_m: float
    dessus_m: float
    dessous_m: float
    # Poids estimé (N), écart permis ; None : pas de contrôle (capsule).
    poids_n: float | None = None
    tolerance_n: float = 0.0
    aimants: bool = False

    @classmethod
    def depuis(cls, sorte: str, reglages: ObjetPrehension, **valeurs: float) -> "Objet":
        objet = cls(
            sorte=sorte,
            rayon_m=reglages.rayon_m,
            dessus_m=reglages.dessus_m,
            dessous_m=reglages.dessous_m,
            poids_n=reglages.poids_n,
            tolerance_n=reglages.tolerance_n,
            aimants=reglages.aimants,
        )
        return replace(objet, **valeurs)


@dataclass(frozen=True)
class Contexte:
    """Ce que disent les autres modules et les capteurs, au moment du mouvement."""

    # Panneau du poste du fût vu rabattu (contact ouvert et stable).
    panneau_rabattu: bool = False
    # La caméra du dosage pivote (ou va pivoter).
    camera_dosage_pivote: bool = False
    # Le chariot du fût est absent ou en mouvement.
    echange_fut: bool = False
    # L'objet tenu (None : rien).
    objet: Objet | None = None
    # L'agitateur du Mycélium au garage (le bocal du porte-bocal y est), sa manivelle en bas.
    agitateur_au_garage: bool = True
    manivelle_en_bas: bool = False
    # Les mors du porte-bocal : « ouverts », « serres », ou None (entre les deux, inconnus).
    mors: str | None = None
    # La griffe (même pont) en butée haute.
    griffe_en_butee_haute: bool = False


def _m(valeur: float) -> str:
    return f"{valeur:.3f}".rstrip("0").rstrip(".").replace(".", ",")


class ReglesPrehension:
    def __init__(self, machine: Machine) -> None:
        assert machine.prehension is not None and machine.griffe is not None
        assert machine.poste_fut is not None
        self.reglages = machine.prehension
        self.poste = machine.poste_fut
        self.camera_bocal = machine.griffe.camera_bocal
        # Course de l'agitation déclarée (trou de la manivelle) ; None : pas de Mycélium.
        self.course_agitation_m = (
            None if machine.mycelium is None else machine.mycelium.course_agitation_m
        )
        self.courses = {
            "pont": machine.axes["pont_x"].course,
            "y": machine.axes["chariot_y"].course,
            "z": machine.axes["prehension_z"].course,
            "a": machine.axes["prehension_a"].course,
        }

    # ------------------------------------------------------------ outils

    def pont(self, pose: Pose) -> float:
        return pose.x - self.reglages.decalage_mat_x

    def rayon(self, objet: Objet | None) -> float:
        """Rayon de ce qui entoure l'axe : la tête, ou l'objet tenu s'il est plus large."""
        rayon = self.reglages.rayon_tete_m
        return rayon if objet is None else max(rayon, objet.rayon_m)

    def bas(self, pose: Pose, objet: Objet | None) -> float:
        """Le point le plus bas : la face, ou le bas de l'objet tenu."""
        return pose.z - (0.0 if objet is None else objet.dessous_m)

    def bord_max_seau(self, y: float) -> float:
        seau = self.reglages.seau_tenu
        if y > seau.y_operateur + _EGAL:
            return seau.bord_max_operateur_z
        return seau.bord_max_piles_z

    def hauteur_trajet(self, objet: Objet | None, *ys: float) -> float:
        """La face « en haut » pour un déplacement du pont : la butée haute, ou plus bas si un seau
        tenu l'impose (règle 3), sur toute la longueur du trajet (ses deux bouts en y)."""
        haut = self.reglages.haut_z
        if objet is not None and objet.sorte == "seau":
            haut = min([haut, *(self.bord_max_seau(y) - objet.dessus_m for y in ys)])
        return max(haut, self.courses["z"][0])

    def en_haut(self, pose: Pose, objet: Objet | None, *ys: float) -> bool:
        hauteur = self.hauteur_trajet(objet, pose.y, *ys)
        return pose.z >= hauteur - self.reglages.tolerance_m

    def zone_camera_bocal(self, objet: Objet | None) -> tuple[tuple[float, float], float, float]:
        """Zone autour du boîtier de la caméra du bocal où la tête doit passer au-dessus :
        (x min, x max), y max, et hauteur minimale du bas de la tête et de l'objet."""
        camera = self.camera_bocal
        assert camera.z_haut is not None
        marge = self.rayon(objet) + self.reglages.camera_bocal_marge_m
        return (
            (camera.x[0] - marge, camera.x[1] + marge),
            camera.y[1] + marge,
            camera.z_haut + self.reglages.camera_bocal_marge_m,
        )

    def dans_boite_camera_dosage(self, pose: Pose, objet: Objet | None) -> bool:
        """La tête (ou l'objet tenu) est-elle dans la boîte de la caméra du dosage ? Le mât
        descend d'en haut : la boîte est touchée dès que le bas est sous son haut."""
        boite = self.reglages.camera_dosage
        rayon = self.rayon(objet)
        return (
            pose.x - rayon < boite.x_max - _EGAL
            and pose.y - rayon < boite.y_max - _EGAL
            and self.bas(pose, objet) < boite.z[1] - _EGAL
        )

    def entre_les_mors(self, pose: Pose) -> bool:
        """La tête est-elle au bocal du porte-bocal (le bocal entre les mors, tenu ou à prendre) :
        au-dessus de lui, face à moins de descente → approche_m de sa cote ?"""
        porte_bocal = self.reglages.porte_bocal
        return (
            math.hypot(pose.x - porte_bocal.x, pose.y - porte_bocal.y)
            <= porte_bocal.rayon_zone_m + _EGAL
            and pose.z < porte_bocal.face_z + self.reglages.descente.approche_m - _EGAL
        )

    def dans_zone_garage(self, pose: Pose) -> bool:
        """L'axe de la tête est-il dans la petite zone du garage (à la verticale du bocal) ?"""
        porte_bocal = self.reglages.porte_bocal
        zone = porte_bocal.zone_garage_m + _EGAL
        return abs(pose.x - porte_bocal.x) <= zone and abs(pose.y - porte_bocal.y) <= zone

    def refus_garage(self, contexte: Contexte) -> str | None:
        """Pourquoi la tête ne peut pas être basse dans la zone du garage, ou None."""
        porte_bocal = self.reglages.porte_bocal
        course = self.course_agitation_m
        if not (contexte.agitateur_au_garage and contexte.manivelle_en_bas):
            return "il faut l'agitateur au garage, manivelle en bas"
        if course is None or abs(course - porte_bocal.course_manivelle_m) > _EGAL:
            declaree = "inconnue" if course is None else f"{_m(course * 100)} cm"
            return (
                f"course de la manivelle déclarée {declaree} (mycelium → course_agitation_m), "
                f"il faut {_m(porte_bocal.course_manivelle_m * 100)} cm"
            )
        if not contexte.griffe_en_butee_haute:
            return "il faut la griffe en butée haute"
        return None

    def au_dessus_du_bocal(self, pose: Pose, objet: Objet | None) -> bool:
        """La tête (ou l'objet tenu) touche-t-elle le bocal au garage, manivelle en haut ?"""
        porte_bocal = self.reglages.porte_bocal
        marge = porte_bocal.marge_bocal_m
        rayon = self.rayon(objet) + self.reglages.objets["bocal"].rayon_m + marge
        return (
            math.hypot(pose.x - porte_bocal.x, pose.y - porte_bocal.y) < rayon - _EGAL
            and self.bas(pose, objet) < porte_bocal.capsule_manivelle_haut_z + marge - _EGAL
        )

    # ------------------------------------------------------------ une pose

    def refus_pose(self, pose: Pose, contexte: Contexte) -> str | None:
        p = self.reglages
        objet = contexte.objet
        pont = self.pont(pose)
        debut, fin = self.courses["pont"]
        if not debut - _EGAL <= pont <= fin + _EGAL:
            return f"pont à x {_m(pont)} m, hors de sa course ({_m(debut)} à {_m(fin)} m)"
        for nom, valeur, (debut, fin) in (
            ("axe de la tête en y", pose.y, self.courses["y"]),
            ("face de la tête en z", pose.z, self.courses["z"]),
            ("rotation de la tête", pose.a, self.courses["a"]),
        ):
            if not debut - _EGAL <= valeur <= fin + _EGAL:
                return f"{nom} à {_m(valeur)}, hors de la course ({_m(debut)} à {_m(fin)})"
        refus = regles_poste.refus_pont(self.poste, contexte.echange_fut, pont)
        if refus is not None:
            return refus
        basse = pose.z < p.haut_z - p.tolerance_m
        if contexte.agitateur_au_garage and not contexte.manivelle_en_bas:
            if self.au_dessus_du_bocal(pose, objet):
                capsule = f"{p.porte_bocal.capsule_manivelle_haut_z:g}".replace(".", ",")
                return (
                    f"bocal au garage, manivelle pas en bas : sa capsule monte à {capsule} m, "
                    "la tête ne passe pas au-dessus"
                )
        if basse and self.dans_zone_garage(pose):
            refus = self.refus_garage(contexte)
            if refus is not None:
                return f"zone du garage (porte-bocal), tête sous {_m(p.haut_z)} m : {refus}"
        elif basse and pose.x < p.isolation_fut_x_max - _EGAL and not contexte.panneau_rabattu:
            return (
                f"isolation du fût : tête à x {_m(pose.x)} m (sous {_m(p.isolation_fut_x_max)}) "
                f"et panneau du poste du fût pas vu rabattu : face en haut ({_m(p.haut_z)} m), "
                f"pas à {_m(pose.z)} m"
            )
        if objet is not None and objet.sorte == "seau":
            bord, maximum = pose.z + objet.dessus_m, self.bord_max_seau(pose.y)
            if bord > maximum + _EGAL:
                ou = "côté opérateur" if maximum == p.seau_tenu.bord_max_operateur_z else "piles"
                return (
                    f"seau tenu ({ou}, axe à y {_m(pose.y)} m) : bord à {_m(bord)} m, au plus "
                    f"{_m(maximum)} m"
                )
        (x_min, x_max), y_max, bas_min = self.zone_camera_bocal(objet)
        bas = self.bas(pose, objet)
        if x_min < pose.x < x_max and pose.y < y_max and bas < bas_min - _EGAL:
            return (
                f"boîtier de la caméra du bocal : tête à x {_m(pose.x)}, y {_m(pose.y)} m "
                f"(zone x {_m(x_min)} à {_m(x_max)}, y < {_m(y_max)}), bas à {_m(bas)} m, il "
                f"faut au moins {_m(bas_min)} m"
            )
        if contexte.camera_dosage_pivote and self.dans_boite_camera_dosage(pose, objet):
            boite = p.camera_dosage
            return (
                f"la caméra du dosage pivote : tête interdite dans x < {_m(boite.x_max)}, "
                f"y < {_m(boite.y_max)}, z {_m(boite.z[0])} à {_m(boite.z[1])} m"
            )
        return None

    # ------------------------------------------------------------ un mouvement

    def refus_mouvement(self, depart: Pose, arrivee: Pose, contexte: Contexte) -> str | None:
        p = self.reglages
        bouge_xy = abs(arrivee.x - depart.x) > _EGAL or abs(arrivee.y - depart.y) > _EGAL
        bouge_tete = abs(arrivee.z - depart.z) > _EGAL or abs(arrivee.a - depart.a) > _EGAL
        if bouge_xy and bouge_tete:
            return "pont et tête ensemble refusés : d'abord la tête en haut, puis le pont"
        objet = contexte.objet
        if bouge_xy and not self.en_haut(depart, objet, arrivee.y):
            hauteur = self.hauteur_trajet(objet, depart.y, arrivee.y)
            return (
                f"déplacement du pont tête basse refusé : face à {_m(depart.z)} m, elle doit "
                f"être en haut ({_m(hauteur)} m)"
            )
        if abs(arrivee.a - depart.a) > _EGAL and (
            self.entre_les_mors(depart) or self.entre_les_mors(arrivee)
        ):
            return "la tête ne tourne jamais entre les mors du porte-bocal"
        if (
            arrivee.z < depart.z - _EGAL
            and arrivee.z < p.haut_z - p.tolerance_m
            and self.dans_zone_garage(arrivee)
        ):
            refus = self.refus_descente_garage(contexte)
            if refus is not None:
                return f"descente au porte-bocal refusée : {refus}"
        longueur = max(
            math.dist((depart.x, depart.y, depart.z), (arrivee.x, arrivee.y, arrivee.z)),
            # 1° de rotation ≈ 1 mm.
            abs(arrivee.a - depart.a) / 1000,
        )
        points = max(1, math.ceil(longueur / p.pas_verification_m))
        for i in range(points + 1):
            t = i / points
            pose = Pose(
                *(
                    debut + (fin - debut) * t
                    for debut, fin in zip(
                        (depart.x, depart.y, depart.z, depart.a),
                        (arrivee.x, arrivee.y, arrivee.z, arrivee.a),
                        strict=True,
                    )
                )
            )
            refus = self.refus_pose(pose, contexte)
            if refus is not None:
                return refus
        return None

    def refus_descente_garage(self, contexte: Contexte) -> str | None:
        """Descendre dans la zone du garage : mors ouverts pour poser le bocal tenu, serrés (sur
        le bocal) pour le prendre, tête vide. Rien d'autre n'y descend."""
        objet = contexte.objet
        if objet is not None and objet.sorte == "bocal":
            if contexte.mors != "ouverts":
                return "pour poser le bocal, il faut les mors ouverts"
        elif objet is None:
            if contexte.mors != "serres":
                return "pour prendre le bocal, il faut les mors serrés sur lui"
        else:
            return f"la tête ne descend au porte-bocal que pour un bocal, pas un(e) {objet.sorte}"
        return None
