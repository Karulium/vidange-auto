"""Verrous du chariot de remplissage (fichier des positions interdites du chariot, v3.44 à 3.46,
règles 12 et 14 du 31/10/2026).

    regles = ReglesRemplissage(reglages.machine)
    regles.refus_pose(pose, contexte)                 # raison du refus, ou None
    regles.refus_mouvement(depart, arrivee, contexte)
    regles.refus_bras_galet(pose)                     # pour la fermeture des seaux (tâche 41)
    regles.refus_bras_spray(pose, hauteur_seau)       # pour le spray (tâche 39)
    regles.refus_descente_prehension(pose, micropore_rentre)   # pour la préhension
    regles.au_dessus_du_chariot(x, y, pose)           # l'axe de la tête est-il au-dessus ?

Une Pose dit où est le chariot : y (axe du plateau), z (dessus du plateau), a (rotation, °),
barres (hw : axe de la barre côté mur à l'axe du plateau), pousseur, barre_allee (hw de la barre
côté allée). Les 2 barres ont chacune leur moteur (31/10) mais bougent toujours ensemble : une
Pose écrite avec `barres` seulement a barre_allee = barres. Les règles 2, 3, 6 et 9 valent pour
chaque barre ; deux barres écartées de plus de `barres → ecart_max_m` : tout mouvement est refusé
(refaire la prise d'origine). Les règles :
1. (anneaux du fût : périmée et supprimée le 31/10/2026 ; une tôle fixe sépare le fût du chariot,
   le plateau peut être haut partout en y) ;
2. barres entre les joues de l'élévateur (hw 0,235-0,255) : plateau ≤ 0,48 ;
3. plateau au-dessus de 0,515 : barres ouvertes (hw ≥ 0,29) ;
4. (règle 12 du fichier des positions, 31/10/2026) pousseur sorti à toute hauteur du plateau
   (≤ 0,575, sa course), seulement barres ouvertes (hw ≥ 0,29) et bras de fermeture (galet)
   rangé ; plusieurs seaux peuvent être poussés à la suite (le pousseur est côté allée, il ne
   passe plus sous la tête du micropore) ;
5. plateau au-dessus de 0,26 seulement bras du galet rangé ;
6. bras du spray sorti : plateau ≤ min(0,50 ; 0,68 − h), entraxe des barres > 0,50 ;
7. plateau du fût pas en place : bout du chariot côté allée (axe + 0,40) à y ≤ 0,875, donc axe
   du plateau à y ≤ 0,475 ;
8. agitateur du mycélium FIXE au-dessus du poste (01/11/2026) : en deçà du dosage (y <
   dosage_y, le poste), bord du seau (plateau + h) ≤ 0,68 TOUJOURS ; près du poste (y <
   ecarte_y, 0,40), le chariot ne roule et son plateau ne monte que si le Mycélium le permet
   (manivelle en bas, arrêtée) ;
9. la préhension ne descend sous ≈ 0,84 au-dessus du chariot qu'avec barres ouvertes et tête du
   micropore rentrée (sauf en mode couvercles et pendant la pose d'un seau vide, barres à
   l'approche : vidange.remplissage.remplissage).
Un mouvement est vérifié point par point (tous les pas_verification_m), axes ensemble en ligne
droite comme le fait FluidNC. Tous les chiffres viennent de machine.yaml (`remplissage`).

Ces verrous ne protègent que la MACHINE : la sécurité des personnes reste câblée.
"""

import math
from collections.abc import Iterable
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
    "barre_allee": "barre_allee",
}


def cles_du_pas(cibles: Iterable[str]) -> list[str]:
    """Les clés d'une Pose qui bougent pour ces cibles : « barres » fait bouger les 2 barres."""
    cles = list(cibles)
    if "barres" in cles and "barre_allee" not in cles:
        cles.append("barre_allee")
    return cles


@dataclass(frozen=True)
class Pose:
    y: float
    z: float
    a: float
    barres: float
    pousseur: float
    # Barre côté allée ; None : la même que la barre côté mur (elles bougent ensemble).
    barre_allee: float = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.barre_allee is None:
            object.__setattr__(self, "barre_allee", self.barres)

    def avec(self, **valeurs: float) -> "Pose":
        # Les 2 barres sont commandées ensemble.
        if "barres" in valeurs and "barre_allee" not in valeurs:
            valeurs["barre_allee"] = valeurs["barres"]
        return replace(self, **valeurs)

    @property
    def barres_les_plus_serrees(self) -> float:
        return min(self.barres, self.barre_allee)


@dataclass(frozen=True)
class Contexte:
    """Ce que disent les autres modules (cases vides : valeurs prudentes par défaut)."""

    plateau_fut_en_place: bool = False
    # Raison pour laquelle le Mycélium interdit de rouler (ou de monter le plateau) près du poste
    # (None : permis).
    refus_mycelium: str | None = "position de la manivelle du mycélium inconnue"
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
        """Les 2 barres ouvertes."""
        return pose.barres_les_plus_serrees >= self.verrous.barres_ouvertes_min - _EGAL

    def pres_du_poste(self, y: float) -> bool:
        """Là où le chariot est sous le bocal du mycélium (en deçà du recul)."""
        return y < self.reglages.ecarte_y - self.reglages.tolerance_y_m

    def au_poste(self, y: float) -> bool:
        """En deçà du dosage : le bord du seau reste ≤ poste_bord_max_z (règle 8)."""
        return y < self.reglages.dosage_y - self.reglages.tolerance_y_m

    def a(self, y: float, cible: float) -> bool:
        return abs(y - cible) <= self.reglages.tolerance_y_m + _EGAL

    def dans_les_joues(self, barres: float) -> bool:
        debut, fin = self.verrous.joues_barres
        return debut - _EGAL <= barres <= fin + _EGAL

    def une_barre_dans_les_joues(self, pose: Pose) -> bool:
        return self.dans_les_joues(pose.barres) or self.dans_les_joues(pose.barre_allee)

    def refus_ecart_barres(self, pose: Pose) -> str | None:
        """Les 2 barres bougent ensemble : plus d'écart que barres → ecart_max_m est refusé."""
        ecart = abs(pose.barres - pose.barre_allee)
        maximum = self.reglages.barres.ecart_max_m
        if ecart > maximum + _EGAL:
            return (
                f"barres écartées de {ecart * 1000:.1f} mm l'une de l'autre (côté mur "
                f"{_m(pose.barres)}, côté allée {_m(pose.barre_allee)} ; au plus "
                f"{maximum * 1000:g} mm) : refaire la prise d'origine du chariot"
            )
        return None

    # ------------------------------------------------------------ une pose

    def refus_pose(self, pose: Pose, contexte: Contexte) -> str | None:
        v = self.verrous
        for cle, (debut, fin) in self.courses.items():
            valeur = getattr(pose, cle)
            if not debut - _EGAL <= valeur <= fin + _EGAL:
                return f"{AXES[cle]} à {_m(valeur)}, hors de sa course ({_m(debut)} à {_m(fin)})"
        refus = self.refus_ecart_barres(pose)
        if refus is not None:
            return refus
        if pose.z > v.joues_plateau_max_z + _EGAL:
            for barre, hw in (("côté mur", pose.barres), ("côté allée", pose.barre_allee)):
                if self.dans_les_joues(hw):
                    return (
                        f"barre {barre} à {_m(hw)}, entre les joues de l'élévateur : plateau ≤ "
                        f"{_m(v.joues_plateau_max_z)} (il est à {_m(pose.z)})"
                    )
        if pose.z > v.barres_ouvertes_au_dessus_z + _EGAL and not self.barres_ouvertes(pose):
            return (
                f"plateau à {_m(pose.z)}, au-dessus de {_m(v.barres_ouvertes_au_dessus_z)} : "
                f"barres ouvertes seulement (hw ≥ {_m(v.barres_ouvertes_min)}, elles sont à "
                f"{_m(pose.barres_les_plus_serrees)})"
            )
        if not self.pousseur_rentre(pose):
            if not self.barres_ouvertes(pose):
                return (
                    f"pousseur sorti : seulement barres ouvertes (hw ≥ "
                    f"{_m(v.barres_ouvertes_min)}, elles sont à "
                    f"{_m(pose.barres_les_plus_serrees)})"
                )
            if contexte.bras_galet_range is not True:
                etat = "pas connu" if contexte.bras_galet_range is None else "pas rangé"
                return f"pousseur sorti : bras de fermeture (galet) {etat}, il doit être rangé"
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
        if self.au_poste(pose.y):
            bord = pose.z + (contexte.hauteur_seau or 0.0)
            if bord > v.poste_bord_max_z + _EGAL:
                return (
                    f"au poste (y {_m(pose.y)}, sous le bocal du mycélium) : bord du seau ≤ "
                    f"{_m(v.poste_bord_max_z)} toujours (il serait à {_m(bord)})"
                )
        if not contexte.plateau_fut_en_place:
            bout = pose.y + v.bout_y_m
            if bout > self.bout_max_y + _EGAL:
                return (
                    f"plateau du fût pas en place : le bout du chariot de remplissage doit rester "
                    f"à y ≤ {_m(self.bout_max_y)} (axe du plateau ≤ "
                    f"{_m(self.bout_max_y - v.bout_y_m)}) ; il serait à {_m(bout)}"
                )
        return None

    # ------------------------------------------------------------ un mouvement

    def refus_mouvement(self, depart: Pose, arrivee: Pose, contexte: Contexte) -> str | None:
        """Le mouvement de `depart` à `arrivee` (tous les axes ensemble, en ligne droite)."""
        refus = self.refus_pose(arrivee, contexte)
        if refus is not None:
            return refus
        roule = abs(arrivee.y - depart.y) > _EGAL
        if roule and (self.pres_du_poste(depart.y) or self.pres_du_poste(arrivee.y)):
            if contexte.refus_mycelium is not None:
                return f"le chariot ne roule pas près du poste : {contexte.refus_mycelium}"
        monte = arrivee.z > depart.z + _EGAL and arrivee.z > self.reglages.plateau_en_bas_z
        if monte and self.pres_du_poste(arrivee.y) and contexte.refus_mycelium is not None:
            return f"le plateau ne monte pas près du poste : {contexte.refus_mycelium}"
        refus = self.refus_ecart_barres(depart)
        if refus is not None:
            # Une barre a glissé ou a été bougée seule : rien ne bouge avant la prise d'origine.
            return refus
        if self.refus_pose(depart, contexte) is not None:
            # Départ déjà interdit (après une coupure, un essai à la main) : seule l'arrivée
            # compte, pour pouvoir en sortir.
            return None
        lineaires = [
            abs(getattr(arrivee, cle) - getattr(depart, cle))
            for cle in ("y", "z", "barres", "barre_allee", "pousseur")
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
        ≤ min(0,50 ; 0,68 − h) ; le bras ne bouge que barres ouvertes à plus de 0,50 d'entraxe."""
        v = self.verrous
        entraxe = pose.barres + pose.barre_allee
        if entraxe <= v.spray_entraxe_min_m + _EGAL:
            return (
                f"bras du spray : barres à {_m(entraxe)} d'entraxe, il en faut plus de "
                f"{_m(v.spray_entraxe_min_m)}"
            )
        if hauteur_seau is None:
            return "bras du spray : hauteur du seau sur le plateau inconnue"
        limite = min(v.spray_plateau_max_z, v.spray_bord_max_z - hauteur_seau)
        if pose.z > limite + _EGAL:
            return f"bras du spray : plateau ≤ {_m(limite)} (il est à {_m(pose.z)})"
        return None

    def au_dessus_du_chariot(self, x: float, y: float, pose: Pose | None) -> bool:
        """L'axe de la tête de préhension (x, y) est au-dessus du chariot qui est à `pose`
        (None : n'importe où sur son rail, quand il bouge)."""
        v = self.verrous
        if abs(x - self.reglages.axe_x) > v.emprise_demi_x_m + _EGAL:
            return False
        if pose is None:
            return True
        return pose.y - v.emprise_mur_y_m - _EGAL <= y <= pose.y + v.bout_y_m + _EGAL

    def refus_descente_prehension(self, pose: Pose, micropore_rentre: bool | None) -> str | None:
        """La préhension ne descend sous ≈ 0,84 au-dessus du chariot que barres ouvertes et
        tête du micropore rentrée (règle 9 ; le micropore : tâche 40)."""
        v = self.verrous
        if not self.barres_ouvertes(pose):
            return (
                f"la préhension ne descend sous {_m(v.prehension_libre_z)} au-dessus du chariot "
                f"que barres ouvertes (hw ≥ {_m(v.barres_ouvertes_min)} ; elles sont à "
                f"{_m(pose.barres_les_plus_serrees)})"
            )
        return self.refus_micropore(micropore_rentre)

    def refus_micropore(self, micropore_rentre: bool | None) -> str | None:
        """Règle 9, seulement le micropore (pose d'un seau vide : les barres sont à l'approche
        ou serrées par le geste du chariot lui-même)."""
        if micropore_rentre is not True:
            etat = "pas connue" if micropore_rentre is None else "sortie"
            return (
                f"la préhension ne descend sous {_m(self.verrous.prehension_libre_z)} au-dessus du "
                f"chariot que tête du micropore rentrée (elle est {etat})"
            )
        return None

    def angle_proche(self, actuel: float, cible: float, modulo: float = 360.0) -> float:
        """L'angle ≡ cible (modulo `modulo`) le plus proche de l'angle actuel."""
        return actuel + (cible - actuel + modulo / 2) % modulo - modulo / 2
