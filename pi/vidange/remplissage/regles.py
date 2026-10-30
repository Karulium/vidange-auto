"""Verrous du chariot de remplissage (fichier des positions interdites du chariot, v3.44 à 3.46).

    regles = ReglesRemplissage(reglages.machine)
    regles.refus_pose(pose, contexte)                 # raison du refus, ou None
    regles.refus_mouvement(depart, arrivee, contexte)
    regles.refus_bras_galet(pose)                     # pour la fermeture des seaux (tâche 41)
    regles.refus_bras_spray(pose, hauteur_seau)       # pour le spray (tâche 39)
    regles.refus_descente_prehension(pose, micropore_rentre)   # pour la préhension

Une Pose dit où est le chariot : y (axe du plateau), z (dessus du plateau), a (rotation, °),
barres (hw : axe d'une barre à l'axe du plateau), pousseur. Les règles :
1. anneaux du fût : en y 0,14-0,41 et 0,59-0,86, plateau en bas ; libre au poste (et au dosage)
   et entre 0,41 et 0,59 : le plateau descend avant de quitter le poste, ne remonte qu'au poste ;
2. barres entre les joues de l'élévateur (hw 0,235-0,255) : plateau ≤ 0,48 ;
3. plateau au-dessus de 0,515 : barres ouvertes (hw ≥ 0,29) ;
4. pousseur sorti seulement plateau en bas ;
5. plateau au-dessus de 0,26 seulement bras du galet rangé ;
6. bras du spray sorti : plateau ≤ min(0,50 ; 0,71 − h), entraxe des barres > 0,50 ;
7. chariot du fût pas en place : bout du chariot à y ≤ 0,875 ;
8. le chariot ne roule près du poste (y < recul de l'agitateur) que si le Mycélium le permet
   (agitateur au garage manivelle en haut, ou au dosage manivelle en bas) ; et le plateau ne
   monte au poste qu'agitateur au garage, sauf pour le dosage (son bocal est au-dessus) ;
9. la préhension ne descend sous ≈ 0,84 qu'avec barres ouvertes et tête du micropore rentrée.
Un mouvement est vérifié point par point (tous les pas_verification_m), axes ensemble en ligne
droite comme le fait FluidNC. Tous les chiffres viennent de machine.yaml (`remplissage`).

Ces verrous ne protègent que la MACHINE : la sécurité des personnes reste câblée.
"""

import math
from dataclasses import dataclass, fields, replace

from vidange.reglages import Machine

# Écart sous lequel deux valeurs sont égales (m ou °).
_EGAL = 1e-6
# Clés d'une Pose → axes de machine.yaml.
AXES = {
    "y": "remplissage_y",
    "z": "plateau_z",
    "a": "plateau_a",
    "barres": "barres",
    "pousseur": "pousseur",
}


@dataclass(frozen=True)
class Pose:
    y: float
    z: float
    a: float
    barres: float
    pousseur: float

    def avec(self, **valeurs: float) -> "Pose":
        return replace(self, **valeurs)


@dataclass(frozen=True)
class Contexte:
    """Ce que disent les autres modules (cases vides : valeurs prudentes par défaut)."""

    chariot_fut_en_place: bool = False
    # Raison pour laquelle le Mycélium interdit de rouler près du poste (None : permis).
    refus_mycelium: str | None = "position de l'agitateur du mycélium inconnue"
    agitateur_au_garage: bool = False
    # Bras du galet (tâche 41) rangé ; None : pas connu.
    bras_galet_range: bool | None = None
    # Bras du spray (tâche 39) sorti, et hauteur du seau sur le plateau (m).
    bras_spray_sorti: bool = False
    hauteur_seau: float | None = None


def _m(valeur: float) -> str:
    return f"{valeur:.4f}".rstrip("0").rstrip(".").replace(".", ",")


class ReglesRemplissage:
    def __init__(self, machine: Machine) -> None:
        assert machine.remplissage is not None and machine.poste_fut is not None
        self.reglages = machine.remplissage
        self.verrous = machine.remplissage.verrous
        self.bout_max_y = machine.poste_fut.remplissage_y_bout_max
        self.courses = {cle: machine.axes[nom].course for cle, nom in AXES.items()}

    # ------------------------------------------------------------ où est le chariot

    def en_bas(self, pose: Pose) -> bool:
        return pose.z <= self.reglages.plateau_en_bas_z + _EGAL

    def pousseur_rentre(self, pose: Pose) -> bool:
        reglages = self.reglages
        return abs(pose.pousseur - reglages.pousseur_rentre_m) <= reglages.tolerance_m + _EGAL

    def barres_ouvertes(self, pose: Pose) -> bool:
        return pose.barres >= self.verrous.barres_ouvertes_min - _EGAL

    def au_poste(self, y: float) -> bool:
        """Dans la zone du poste et du dosage, où le plateau peut être haut (règle 1)."""
        debut, fin = self.verrous.libre_poste_y
        return debut - _EGAL <= y <= fin + _EGAL

    def pres_du_poste(self, y: float) -> bool:
        """Là où le chariot gêne l'agitateur du mycélium (en deçà du recul)."""
        return y < self.reglages.ecarte_y - self.reglages.tolerance_y_m

    def a(self, y: float, cible: float) -> bool:
        return abs(y - cible) <= self.reglages.tolerance_y_m + _EGAL

    def dans_les_joues(self, barres: float) -> bool:
        debut, fin = self.verrous.joues_barres
        return debut - _EGAL <= barres <= fin + _EGAL

    # ------------------------------------------------------------ une pose

    def refus_pose(self, pose: Pose, contexte: Contexte) -> str | None:
        v = self.verrous
        for cle, (debut, fin) in self.courses.items():
            valeur = getattr(pose, cle)
            if not debut - _EGAL <= valeur <= fin + _EGAL:
                return f"{AXES[cle]} à {_m(valeur)}, hors de sa course ({_m(debut)} à {_m(fin)})"
        if not self.au_poste(pose.y) and pose.z > v.anneaux_plateau_max_z + _EGAL:
            for debut, fin in v.anneaux_y:
                if debut - _EGAL <= pose.y <= fin + _EGAL:
                    return (
                        f"chariot à y {_m(pose.y)}, sous les anneaux du fût ({_m(debut)} à "
                        f"{_m(fin)}) : plateau en bas (≤ {_m(v.anneaux_plateau_max_z)}), il est "
                        f"à {_m(pose.z)}"
                    )
        if self.dans_les_joues(pose.barres) and pose.z > v.joues_plateau_max_z + _EGAL:
            return (
                f"barres à {_m(pose.barres)}, entre les joues de l'élévateur : plateau ≤ "
                f"{_m(v.joues_plateau_max_z)} (il est à {_m(pose.z)})"
            )
        if pose.z > v.barres_ouvertes_au_dessus_z + _EGAL and not self.barres_ouvertes(pose):
            return (
                f"plateau à {_m(pose.z)}, au-dessus de {_m(v.barres_ouvertes_au_dessus_z)} : "
                f"barres ouvertes seulement (hw ≥ {_m(v.barres_ouvertes_min)}, elles sont à "
                f"{_m(pose.barres)})"
            )
        if not self.pousseur_rentre(pose) and not any(
            debut - _EGAL <= pose.z <= fin + _EGAL for debut, fin in v.pousseur_plages_z
        ):
            return f"pousseur sorti avec le plateau à {_m(pose.z)} : il doit être rentré"
        if pose.z > v.galet_plateau_max_z + _EGAL and contexte.bras_galet_range is not True:
            etat = "pas connu" if contexte.bras_galet_range is None else "pas rangé"
            return (
                f"plateau au-dessus de {_m(v.galet_plateau_max_z)} : bras du galet {etat} (il "
                "doit être rangé)"
            )
        if contexte.bras_spray_sorti:
            refus = self.refus_bras_spray(pose, contexte.hauteur_seau)
            if refus is not None:
                return refus
        if not contexte.chariot_fut_en_place:
            bout = pose.y + v.bout_y_m
            if bout > self.bout_max_y + _EGAL:
                return (
                    f"chariot du fût pas en place : le bout du chariot de remplissage doit rester "
                    f"à y ≤ {_m(self.bout_max_y)} (il serait à {_m(bout)})"
                )
        return None

    # ------------------------------------------------------------ un mouvement

    def refus_mouvement(
        self, depart: Pose, arrivee: Pose, contexte: Contexte, dosage: bool = False
    ) -> str | None:
        """Le mouvement de `depart` à `arrivee` (tous les axes ensemble, en ligne droite).
        `dosage` : le plateau monte au dosage du mycélium (bocal au-dessus, manivelle en bas)."""
        refus = self.refus_pose(arrivee, contexte)
        if refus is not None:
            return refus
        roule = abs(arrivee.y - depart.y) > _EGAL
        if roule and (self.pres_du_poste(depart.y) or self.pres_du_poste(arrivee.y)):
            if contexte.refus_mycelium is not None:
                return f"le chariot ne roule pas près du poste : {contexte.refus_mycelium}"
        monte = arrivee.z > depart.z + _EGAL and arrivee.z > self.reglages.plateau_en_bas_z
        if monte and self.pres_du_poste(arrivee.y) and not dosage:
            if not contexte.agitateur_au_garage:
                return "le plateau ne monte au poste qu'agitateur du mycélium au garage"
        if self.refus_pose(depart, contexte) is not None:
            # Départ déjà interdit (après une coupure, un essai à la main) : seule l'arrivée
            # compte, pour pouvoir en sortir.
            return None
        lineaires = [
            abs(getattr(arrivee, cle) - getattr(depart, cle))
            for cle in ("y", "z", "barres", "pousseur")
        ]
        etapes = max(1, math.ceil(max(lineaires) / self.reglages.pas_verification_m))
        for i in range(1, etapes):
            t = i / etapes
            point = Pose(
                **{
                    champ.name: getattr(depart, champ.name)
                    + t * (getattr(arrivee, champ.name) - getattr(depart, champ.name))
                    for champ in fields(Pose)
                }
            )
            refus = self.refus_pose(point, contexte)
            if refus is not None:
                return f"en route : {refus}"
        return None

    # ------------------------------------------------------------ pour les autres modules

    def refus_bras_galet(self, pose: Pose) -> str | None:
        """Le bras du galet (fermeture, tâche 41) ne tourne que plateau ≤ 0,26 (règle 5)."""
        limite = self.verrous.galet_plateau_max_z
        if pose.z > limite + _EGAL:
            return f"le bras du galet ne tourne que plateau ≤ {_m(limite)} (il est à {_m(pose.z)})"
        return None

    def refus_bras_spray(self, pose: Pose, hauteur_seau: float | None) -> str | None:
        """Pendant le pivot du bras du spray et la pulvérisation (tâche 39, règle 6) : plateau
        ≤ min(0,50 ; 0,71 − h) ; le bras ne bouge que barres ouvertes à plus de 0,50 d'entraxe."""
        v = self.verrous
        if 2 * pose.barres <= v.spray_entraxe_min_m + _EGAL:
            return (
                f"bras du spray : barres à {_m(2 * pose.barres)} d'entraxe, il en faut plus de "
                f"{_m(v.spray_entraxe_min_m)}"
            )
        if hauteur_seau is None:
            return "bras du spray : hauteur du seau sur le plateau inconnue"
        limite = min(v.spray_plateau_max_z, v.spray_bord_max_z - hauteur_seau)
        if pose.z > limite + _EGAL:
            return f"bras du spray : plateau ≤ {_m(limite)} (il est à {_m(pose.z)})"
        return None

    def refus_descente_prehension(self, pose: Pose, micropore_rentre: bool | None) -> str | None:
        """La préhension ne descend sous ≈ 0,84 au-dessus du chariot que barres ouvertes et
        tête du micropore rentrée (règle 9 ; le micropore : tâche 40)."""
        v = self.verrous
        if not self.barres_ouvertes(pose):
            return (
                f"la préhension ne descend sous {_m(v.prehension_libre_z)} au-dessus du chariot "
                f"que barres ouvertes (hw ≥ {_m(v.barres_ouvertes_min)} ; elles sont à "
                f"{_m(pose.barres)})"
            )
        if micropore_rentre is not True:
            etat = "pas connue" if micropore_rentre is None else "sortie"
            return (
                f"la préhension ne descend sous {_m(v.prehension_libre_z)} au-dessus du chariot "
                f"que tête du micropore rentrée (elle est {etat})"
            )
        return None

    def angle_proche(self, actuel: float, cible: float, modulo: float = 360.0) -> float:
        """L'angle ≡ cible (modulo `modulo`) le plus proche de l'angle actuel."""
        return actuel + (cible - actuel + modulo / 2) % modulo - modulo / 2
