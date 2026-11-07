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
   « rabattu » ⇒ face en haut, sans exception (le porte-bocal est à x 0,925 depuis le 01/11).
   Zone du porte-bocal (`zone_porte_bocal`, agitateur FIXE, bocal en (0,925 ; 0,150)) : la tête
   et l'objet tenu (rayon de la tête + marge + rayon de l'objet) ne vont jamais dans ce rectangle
   plus bas que z_haut + marge ; la face montant au plus à haut_z, les trajets le contournent.
   Seule exception, manivelle du mycélium arrêtée EN BAS : la verticale du bocal (axe sur le
   bocal à x ± 1 mm, y −1 / +2 mm), pour le poser ou le reprendre, et le COULOIR d'accès
   (`porte_bocal → couloir`, Maquette 06/11) : du départ (0,925 ; 0,40), face à 1,10, en −y
   jusqu'à la verticale (et retour en +y), x dans la largeur permise (tête seule ± 0,06 ; avec
   un bocal −0,06 / +0,04). Tout autre trajet dans la zone est refusé (côté mur, côtés en x). Pour
   descendre sur le bocal : caméra du dosage à 0°, mors ouverts (fin de course) pour poser un
   bocal, serrés pour le prendre.
3. Seau tenu : son bord au plus à bord_max_operateur_z côté opérateur, à bord_max_piles_z
   au-dessus des piles. Chaîne Z (portique → chaine_prehension) : plaque Z au-dessus de 2,02
   (face au-dessus de 0,942) ⇒ mât à y ≤ 0,80 ; plus loin en y, la face « en haut » est plus
   basse.
4. Boîtier de la caméra du bocal (griffe → camera_bocal) : près de lui, la tête et l'objet tenu
   restent au-dessus de son haut + marge.
5. Caméra du dosage : pendant qu'elle pivote, la tête n'entre pas dans sa boîte.
De plus : la tête ne tourne jamais entre les mors du porte-bocal ; le pont respecte le verrou du
poste du fût (pas de pont dans la zone du chariot pendant l'échange du fût).

Tous les chiffres viennent de machine.yaml (`prehension`, `griffe → camera_bocal`, `poste_fut`).
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
    # Objet pris hors d'axe : son axe est à y de la tête + decalage_y_m (seau d'une pile de la
    # rangée y 0,84 pris tête à 0,83, au bout de la course du chariot).
    decalage_y_m: float = 0.0
    # Idem en x : l'entonnoir est tenu par son oreille, son axe est à 0,140 m en −x de la tête.
    decalage_x_m: float = 0.0

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
    # Le plateau du fût est absent ou en mouvement.
    echange_fut: bool = False
    # L'objet tenu (None : rien).
    objet: Objet | None = None
    # La manivelle du Mycélium, arrêtée « haut » ou « bas » ; None : elle bouge (ou demi-tour),
    # entre les deux, ou inconnue. La tête ne va dans la zone du porte-bocal que manivelle en bas.
    manivelle: str | None = None
    # Les mors du porte-bocal : « ouverts », « serres », ou None (entre les deux, inconnus).
    mors: str | None = None


def _m(valeur: float) -> str:
    return f"{valeur:.3f}".rstrip("0").rstrip(".").replace(".", ",")


class ReglesPrehension:
    def __init__(self, machine: Machine) -> None:
        assert machine.prehension is not None and machine.griffe is not None
        assert machine.poste_fut is not None and machine.mycelium is not None
        self.reglages = machine.prehension
        # Face de la tête au contact de la capsule, pour la course de l'agitation réglée (vérifié
        # au démarrage).
        contact = machine.prehension.porte_bocal.contact_z(machine.mycelium.course_agitation_m)
        assert contact is not None
        self.contact_capsule_z = contact
        self.poste = machine.poste_fut
        self.portique = machine.portique
        self.entonnoir = machine.entonnoir
        self.camera_bocal = machine.griffe.camera_bocal
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
        if objet is not None and objet.sorte == "entonnoir" and self.entonnoir is not None:
            # Exception voulue par la fiche de l'Entonnoir : il roule à 6 cm au-dessus de sa pose.
            haut = min(haut, self.entonnoir.face_transport_z)
        if objet is not None and objet.sorte == "seau":
            haut = min([haut, *(self.bord_max_seau(y) - objet.dessus_m for y in ys)])
        for y in ys:
            maximum = self.face_max_chaine(y)
            if maximum is not None:
                haut = min(haut, maximum)
        return max(haut, self.courses["z"][0])

    def face_max_chaine(self, y: float) -> float | None:
        """La face la plus haute permise par la chaîne Z, mât à y (None : pas de limite)."""
        if self.portique is None:
            return None
        return self.portique.face_max_chaine(y, self.courses["z"][0])

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

    def y_approche_porte_bocal(self, objet: Objet | None) -> float:
        """Le mât arrive sur la verticale du porte-bocal par le côté fût : y plus grand que la
        zone du boîtier de la caméra du bocal ET que la zone du porte-bocal (le boîtier est à 7 cm
        du bocal : un trajet en diagonale le frôlerait). Plus la tolérance de position."""
        zone = self.reglages.zone_porte_bocal
        autour = (
            self.reglages.rayon_tete_m + zone.marge_m + (0.0 if objet is None else objet.rayon_m)
        )
        return max(self.zone_camera_bocal(objet)[1], zone.y[1] + autour) + self.reglages.tolerance_m

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
        au-dessus de lui, face à moins de descente → approche_m du contact de la capsule ?"""
        porte_bocal = self.reglages.porte_bocal
        return (
            math.hypot(pose.x - porte_bocal.x, pose.y - porte_bocal.y)
            <= porte_bocal.rayon_zone_m + _EGAL
            and pose.z < self.contact_capsule_z + self.reglages.descente.approche_m - _EGAL
        )

    def sur_le_bocal(self, pose: Pose) -> bool:
        """L'axe de la tête est-il sur celui du bocal du porte-bocal (à la verticale : x ±
        tolerance_pose_x_m, y dans tolerance_pose_y_m) ?"""
        porte_bocal = self.reglages.porte_bocal
        moins, plus = porte_bocal.tolerance_pose_y_m
        dy = pose.y - porte_bocal.y
        return (
            abs(pose.x - porte_bocal.x) <= porte_bocal.tolerance_pose_x_m + _EGAL
            and moins - _EGAL <= dy <= plus + _EGAL
        )

    def angle_meplats(self, actuel: float) -> float:
        """L'angle de pose au porte-bocal le plus proche de `actuel` : angle_meplats_deg + k ×
        120° (méplats tous les 120°), dans la course de la rotation : au plus 60° de rotation."""
        debut, fin = self.courses["a"]
        base = self.reglages.angle_meplats_deg
        k_min = math.ceil((debut - base) / 120 - 1e-9)
        k_max = math.floor((fin - base) / 120 + 1e-9)
        candidats = [base + 120 * k for k in range(k_min, k_max + 1)]
        if not candidats:
            raise ValueError("aucun angle des méplats dans la course de la rotation")
        return min(candidats, key=lambda a: (abs(a - actuel), abs(a)))

    def dans_le_couloir(self, pose: Pose, objet: Objet | None) -> bool:
        """La tête est-elle dans le couloir d'accès au bocal (face à sa hauteur, entre le départ
        et la verticale du bocal, x dans la largeur permise pour ce qu'elle tient) ?"""
        porte_bocal = self.reglages.porte_bocal
        couloir = porte_bocal.couloir
        if couloir is None:
            return False
        if objet is None:
            moins, plus = -couloir.demi_largeur_x_tete, couloir.demi_largeur_x_tete
        elif objet.sorte == "bocal":
            moins, plus = couloir.largeur_x_bocal
        else:
            return False
        dx = pose.x - porte_bocal.x
        return (
            moins - _EGAL <= dx <= plus + _EGAL
            and porte_bocal.y + porte_bocal.tolerance_pose_y_m[0] - _EGAL
            <= pose.y
            <= couloir.depart[1] + _EGAL
            and abs(pose.z - couloir.face_z) <= self.reglages.tolerance_m + _EGAL
        )

    def pres_du_bocal(self, pose: Pose) -> bool:
        """L'axe de la tête est-il près de celui du bocal (dans rayon_zone_m), à sa verticale ou
        pas ?"""
        porte_bocal = self.reglages.porte_bocal
        return (
            math.hypot(pose.x - porte_bocal.x, pose.y - porte_bocal.y)
            <= porte_bocal.rayon_zone_m + _EGAL
        )

    def dans_zone_porte_bocal(self, pose: Pose, objet: Objet | None) -> bool:
        """La tête (rayon de la tête + marge + rayon de l'objet tenu) est-elle dans le rectangle
        de la zone du porte-bocal, plus bas que z_haut + marge ?"""
        zone = self.reglages.zone_porte_bocal
        rayon = (
            self.reglages.rayon_tete_m + zone.marge_m + (0.0 if objet is None else objet.rayon_m)
        )
        dx = max(zone.x[0] - pose.x, 0.0, pose.x - zone.x[1])
        dy = max(zone.y[0] - pose.y, 0.0, pose.y - zone.y[1])
        if math.hypot(dx, dy) >= rayon - _EGAL:
            return False
        return self.bas(pose, objet) < zone.z_haut + zone.marge_m - _EGAL

    # ------------------------------------------------------------ une pose

    def refus_pose(self, pose: Pose, contexte: Contexte, acces: bool = False) -> str | None:
        """`acces` : la pose est sur le trajet qui mène à la verticale du bocal (ou en revient),
        face en haut, manivelle en bas (refus_mouvement) : la zone du porte-bocal est permise."""
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
        if self.portique is not None:
            refus = self.portique.refus_chaine(pose.y, pose.z, self.courses["z"][0])
            if refus is not None:
                return refus
        basse = pose.z < p.haut_z - p.tolerance_m
        if (
            not acces
            and self.dans_zone_porte_bocal(pose, objet)
            and not (self.sur_le_bocal(pose) and contexte.manivelle == "bas")
        ):
            return self._texte_zone(contexte)
        if basse and pose.x < p.isolation_fut_x_max - _EGAL and not contexte.panneau_rabattu:
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

    def _texte_zone(self, contexte: Contexte) -> str:
        zone, porte_bocal = self.reglages.zone_porte_bocal, self.reglages.porte_bocal
        manivelle = {"bas": "", "haut": " (manivelle en haut)"}.get(
            contexte.manivelle or "", " (manivelle qui bouge, demi-tour, ou position inconnue)"
        )
        return (
            f"zone du porte-bocal (x {_m(zone.x[0])} à {_m(zone.x[1])}, y {_m(zone.y[0])} à "
            f"{_m(zone.y[1])}, jusqu'à z {_m(zone.z_haut)} m) : la tête la contourne ; elle n'y va "
            f"que pour poser ou reprendre le bocal, à sa verticale ({_m(porte_bocal.x)} ; "
            f"{_m(porte_bocal.y)}), manivelle du mycélium en bas{manivelle}"
        )

    # ------------------------------------------------------------ un mouvement

    def acces_porte_bocal(self, depart: Pose, arrivee: Pose, contexte: Contexte) -> bool:
        """Le trajet du pont qui mène à la verticale du bocal (ou en revient), manivelle en bas :
        dans le couloir (porte_bocal → couloir), en y seulement ; sans couloir dans les
        réglages, en ligne droite depuis (ou vers) un point hors de la zone, face en haut."""
        if contexte.manivelle != "bas" or abs(arrivee.z - depart.z) > _EGAL:
            return False
        if self.reglages.porte_bocal.couloir is not None:
            return (
                abs(arrivee.x - depart.x) <= _EGAL
                and self.dans_le_couloir(depart, contexte.objet)
                and self.dans_le_couloir(arrivee, contexte.objet)
            )
        if not self.en_haut(depart, contexte.objet, arrivee.y):
            return False
        if self.sur_le_bocal(arrivee) and not self.sur_le_bocal(depart):
            dehors = depart
        elif self.sur_le_bocal(depart) and not self.sur_le_bocal(arrivee):
            dehors = arrivee
        else:
            return False
        return not self.dans_zone_porte_bocal(dehors, contexte.objet)

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
        if (
            abs(arrivee.a - depart.a) > _EGAL
            and contexte.objet is not None
            and contexte.objet.sorte == "entonnoir"
        ):
            return (
                "la tête ne tourne jamais en tenant l'entonnoir (l'oreille doit rester côté +x "
                "pour que la ventouse la retrouve)"
            )
        if abs(arrivee.a - depart.a) > _EGAL and (
            self.entre_les_mors(depart) or self.entre_les_mors(arrivee)
        ):
            return "la tête ne tourne jamais entre les mors du porte-bocal"
        descend = arrivee.z < depart.z - _EGAL and arrivee.z < p.haut_z - p.tolerance_m
        if descend and self.sur_le_bocal(arrivee):
            refus = self.refus_descente_porte_bocal(contexte)
            if refus is not None:
                return f"descente au porte-bocal refusée : {refus}"
        elif descend and self.pres_du_bocal(arrivee):
            porte_bocal = p.porte_bocal
            moins, plus = porte_bocal.tolerance_pose_y_m
            return (
                f"descente au porte-bocal refusée : axe de la tête à "
                f"({_m(arrivee.x)} ; {_m(arrivee.y)}), il faut x {_m(porte_bocal.x)} ± "
                f"{porte_bocal.tolerance_pose_x_m * 1000:g} mm et y {_m(porte_bocal.y)} "
                f"{moins * 1000:+g} / {plus * 1000:+g} mm (1,3 mm de jeu entre les mors)"
            )
        longueur = max(
            math.dist((depart.x, depart.y, depart.z), (arrivee.x, arrivee.y, arrivee.z)),
            # 1° de rotation ≈ 1 mm.
            abs(arrivee.a - depart.a) / 1000,
        )
        points = max(1, math.ceil(longueur / p.pas_verification_m))
        acces = bouge_xy and self.acces_porte_bocal(depart, arrivee, contexte)
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
            refus = self.refus_pose(pose, contexte, acces=acces)
            if refus is not None:
                return refus
        return None

    def refus_descente_porte_bocal(self, contexte: Contexte) -> str | None:
        """Descendre sur le bocal du porte-bocal : manivelle en bas, caméra du dosage à 0°, mors
        ouverts pour poser le bocal tenu, serrés (sur le bocal) pour le prendre, tête vide. Rien
        d'autre n'y descend."""
        if contexte.manivelle != "bas":
            return "il faut la manivelle du mycélium en bas (pose et reprise manivelle en bas)"
        if contexte.camera_dosage_pivote:
            return "il faut la caméra du dosage à 0° (vers le bocal)"
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
