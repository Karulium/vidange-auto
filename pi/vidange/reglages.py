"""Chargement et vérification des fichiers de réglages (`pi/reglages/*.yaml`).

Chaque fichier a son modèle ci-dessous. Au démarrage, tout est vérifié ; la moindre
erreur arrête le programme avec un message en français qui dit quel fichier,
quel réglage, et ce qui ne va pas. Toutes les erreurs sont listées d'un coup.
"""

import math
import re
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    IPvAnyNetwork,
    StringConstraints,
    ValidationError,
    model_validator,
)


class ErreurReglages(Exception):
    """Réglages faux : le programme ne doit pas démarrer."""


class Modele(BaseModel):
    """Base de tous les réglages : un nom inconnu est une erreur (faute de frappe)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# Noms des axes, positions, zones : minuscules sans accent, comme dans le code.
Nom = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
Intervalle = tuple[float, float]
# Lettres des axes d'une carte FluidNC.
Lettre = Literal["X", "Y", "Z", "A", "B", "C"]


# ---------------------------------------------------------------- machine.yaml


class Axe(Modele):
    """Un axe : longueur de son rail et course permise, en mètres (en degrés pour un axe
    tournant : « longueur_rail » est alors le tour permis, la course commence à -longueur_rail)."""

    longueur_rail: float = Field(gt=0)
    course: Intervalle
    # Carte FluidNC qui fait bouger l'axe (nom dans fluidnc.yaml) et lettre de l'axe sur la carte.
    carte: Nom | None = None
    lettre: Lettre | None = None
    # « m » : axe droit (rail et course en mètres) ; « deg » : axe tournant (en degrés).
    unite: Literal["m", "deg"] = "m"
    # Faux : jamais piloté seul à distance (page web), par exemple un axe qui ne bouge qu'avec
    # un autre (les 2 barres du remplissage).
    pilotage_distance: bool = True

    @model_validator(mode="after")
    def _verifier_course(self) -> "Axe":
        if (self.carte is None) != (self.lettre is None):
            raise ValueError("« carte » et « lettre » vont ensemble : écrire les deux, ou aucun")
        debut, fin = self.course
        if debut >= fin:
            raise ValueError(
                f"la course doit aller du plus petit au plus grand ({debut:g} puis {fin:g})"
            )
        bas = -self.longueur_rail if self.unite == "deg" else 0
        if debut < bas or fin > self.longueur_rail:
            raise ValueError(
                f"la course ({debut:g} à {fin:g} {self.unite}) sort du rail "
                f"({bas:g} à {self.longueur_rail:g} {self.unite})"
            )
        return self


class GesteLieuSur(Modele):
    """Un geste du retour en lieu sûr : une prise d'origine d'une carte, ou aller à une position."""

    # Carte FluidNC (nom dans fluidnc.yaml) dont on fait la prise d'origine ($H).
    prise_origine: Nom | None = None
    # Position nommée (plus haut dans « positions ») où envoyer les axes.
    aller: Nom | None = None
    # Délai maximal du geste (nom dans « durees »).
    delai: Nom

    @model_validator(mode="after")
    def _un_seul_geste(self) -> "GesteLieuSur":
        if (self.prise_origine is None) == (self.aller is None):
            raise ValueError("écrire « prise_origine: carte » ou « aller: position » (un seul)")
        return self


class Rectangle(Modele):
    """Un rectangle vu de dessus, dans le repère du portique (m)."""

    x: Intervalle
    y: Intervalle

    @model_validator(mode="after")
    def _dans_l_ordre(self) -> "Rectangle":
        for axe, (debut, fin) in (("x", self.x), ("y", self.y)):
            if debut >= fin:
                raise ValueError(f"sur {axe}, aller du plus petit au plus grand")
        return self

    def contient(self, x: float, y: float) -> bool:
        return self.x[0] <= x <= self.x[1] and self.y[0] <= y <= self.y[1]


class PeseeFut(Modele):
    """Pesée du chariot du fût (carte HX711 lue par le Pi)."""

    # Vrai tant que l'étalonnage et la tare n'ont pas été faits sur la vraie pesée.
    exemple: bool = False
    # Étalonnage (pi/systeme/essai-poste-fut.md) : mesure brute à vide, et nombre de points
    # de la mesure brute par kilogramme posé.
    zero_brut: int
    brut_par_kg: float
    # Poids du berceau + fût vide (kg) : poids net du substrat = poids lu − tare.
    tare_kg: float = Field(ge=0)
    # Poids lu (berceau + fût + contenu) plausible quand un fût est en place (kg).
    plausible_kg: Intervalle
    # Une pesée = la médiane de plusieurs lectures ; une lecture qui s'en écarte de plus de
    # « ecart_aberrant_kg » est jetée ; il en faut au moins « lectures_valides_min ».
    lectures: int = Field(ge=1, le=50)
    lectures_valides_min: int = Field(ge=1)
    ecart_aberrant_kg: float = Field(gt=0)
    # Attente maximale de la carte à chaque lecture (s) : au-delà, « pesée débranchée ».
    delai_reponse_s: float = Field(gt=0)
    # Une pesée tous les combien (s), sur la machine.
    periode_s: float = Field(gt=0)
    # Écart permis entre la somme des doses de la griffe et la baisse de la pesée (kg) :
    # au-delà, un avertissement (pas un arrêt).
    ecart_doses_max_kg: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier(self) -> "PeseeFut":
        erreurs = []
        if self.brut_par_kg == 0:
            erreurs.append("brut_par_kg ne peut pas valoir 0")
        if self.plausible_kg[0] >= self.plausible_kg[1]:
            erreurs.append("plausible_kg : aller du plus petit au plus grand")
        if self.lectures_valides_min > self.lectures:
            erreurs.append("lectures_valides_min ne peut pas dépasser lectures")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class PosteFut(Modele):
    """Poste du fût (module figé le 23/10/2026) : géométrie, zones, signaux stables, pesée.

    Repère du portique, en mètres. Rien ne bouge seul au poste : ces chiffres servent aux
    verrous des autres modules (pont, chariot de remplissage, griffe, préhension) et à l'état
    du poste. La sécurité des personnes reste câblée.
    """

    # Le fût (toujours debout dans la machine).
    centre_fut: tuple[float, float]
    ouverture_diametre: float = Field(gt=0)
    ouverture_z: float
    fut_diametre_interieur: float = Field(gt=0)
    fut_profondeur_interieure: float = Field(gt=0)
    # Fond intérieur et bord, à peu près : le fond est trouvé au toucher par la griffe.
    fut_fond_interieur_z: float
    fut_bord_z: float
    # Chariot du fût absent ou en mouvement : le pont reste hors de cet intervalle de x
    # (le chariot monte à 1,06, le chariot X du pont descend à 1,11).
    pont_interdit_x: Intervalle
    # Pendant ce temps, le bout du chariot de remplissage reste à y ≤ cette valeur
    # (poste ou files 1 et 2, jamais devant la 3ᵉ file).
    remplissage_y_bout_max: float
    # Griffe au-dessus de la poignée du volet : le bas de sa tête reste à z ≥ cette valeur.
    poignee_volet: Rectangle
    griffe_bas_min_poignee_z: float
    # Préhension en lavage, pour passer la paroi côté stockage : fond du seau à z ≥ ... et
    # axe à y ≤ ...
    lavage_paroi_fond_seau_min_z: float
    lavage_paroi_axe_y_max: float
    # Les signaux du poste doivent être stables depuis ce temps (s) pour compter.
    stabilite_s: float = Field(ge=0)
    # Le poste relit ses signaux tous les combien (s).
    periode_s: float = Field(gt=0)
    # Voyant du bouton « Prêt » : demi-période du clignotement (s).
    clignotement_s: float = Field(gt=0)
    pesee: PeseeFut

    @model_validator(mode="after")
    def _verifier(self) -> "PosteFut":
        erreurs = []
        if self.pont_interdit_x[0] >= self.pont_interdit_x[1]:
            erreurs.append("pont_interdit_x : aller du plus petit au plus grand")
        if self.fut_fond_interieur_z >= self.fut_bord_z:
            erreurs.append("le fond du fût (fut_fond_interieur_z) doit être sous son bord")
        if self.fut_diametre_interieur > self.ouverture_diametre:
            erreurs.append(
                "fut_diametre_interieur plus grand que l'ouverture du dessus : chiffre faux ?"
            )
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


# Les 5 axes de la griffe, par leur nom dans machine.yaml (tous sur la carte du portique).
AXES_GRIFFE = {
    "pont_x": "m",  # le pont (Portique) ; le mât de la griffe est à pont + decalage_mat_x
    "chariot_y": "m",  # le chariot du pont : y du mât
    "griffe_z": "m",  # hauteur des axes de la tête
    "griffe_a": "deg",  # rotation de la tête
    "griffe_b": "m",  # vis du godet : début de la course = fermé, fin = grand ouvert
}


class RotationGriffe(Modele):
    """Rotation de la tête (axe A), selon la hauteur des axes (plan de commande)."""

    # Libre si les axes sont à z ≤ libre_z_max.
    libre_z_max: float
    # Au-dessus : orientation bloquée (bras le long du pont), à l'une de ces orientations.
    bloquee_z_min: float
    orientations_bloquees_deg: tuple[float, float]
    # Entre les deux : libre godet fermé, à ± ouvert_ecart_max_deg d'une orientation bloquée
    # godet ouvert.
    ouvert_ecart_max_deg: float = Field(gt=0)
    # Écart permis pour « à 0° ou 180° » (°).
    tolerance_deg: float = Field(gt=0)
    # Pas de rotation quand le pont est au-delà de ce x.
    pont_x_max: float

    @model_validator(mode="after")
    def _verifier(self) -> "RotationGriffe":
        if self.libre_z_max > self.bloquee_z_min:
            raise ValueError("libre_z_max doit être sous bloquee_z_min")
        return self


class TrajetGriffe(Modele):
    """Trajet fût ↔ poste de remplissage : jamais en diagonale."""

    # Hauteur des axes pendant les trajets.
    z: float
    # D'abord en x avec le mât à y ≥ mat_y_min, puis en y seulement une fois le mât à
    # x ≥ mat_x_min_pour_y ; retour dans l'ordre inverse.
    mat_y_min: float
    mat_x_min_pour_y: float


class BandeGriffe(Modele):
    """Garage et glissière de l'agitateur : y minimum du mât pour une bande de x du mât,
    godet fermé, à moitié ouvert, grand ouvert (volumes interdits à toute hauteur)."""

    x: Intervalle
    y_min: tuple[float, float, float]
    # Bande permise à la griffe en butée haute (garage, quand la préhension est au porte-bocal :
    # bas du godet au-dessus de tout le Mycélium, docs/decisions.md, 29/10/2026).
    permise_en_butee_haute: bool = False


class ZoneMatGriffe(Modele):
    """Une règle « mât à x ≤ ... ou y ≥ ... »."""

    mat_x_max: float
    mat_y_min: float


class TeteGriffe(Modele):
    """Encombrement de la tête vu de dessus, autour du mât (m).

    « Le long du bras » : le long du pont quand l'orientation est bloquée ; « en travers » : vers
    la raclette."""

    demi_longueur_ferme: float = Field(gt=0)
    demi_longueur_ouvert: float = Field(gt=0)
    demi_largeur: float = Field(gt=0)
    # Rayon balayé en tournant, godet fermé.
    rayon_balaye: float = Field(gt=0)
    # Partie haute de la tête (tout ce qui est au-dessus de « axes − haut_sous_axes ») : seuls
    # les bras dépassent du mât, de demi_longueur_haut le long du bras.
    demi_longueur_haut: float = Field(gt=0)
    haut_sous_axes: float = Field(ge=0)

    @model_validator(mode="after")
    def _verifier(self) -> "TeteGriffe":
        if self.demi_longueur_ouvert < self.demi_longueur_ferme:
            raise ValueError("demi_longueur_ouvert doit être au moins demi_longueur_ferme")
        if self.rayon_balaye < max(self.demi_longueur_ferme, self.demi_largeur):
            raise ValueError("rayon_balaye doit être au moins la demi-longueur et la demi-largeur")
        return self


class CameraBocalGriffe(Modele):
    """Boîtier de la caméra du bocal, vu de dessus : la tête ne doit pas le toucher tant que
    son bas est sous bas_z_max. Quand seule la partie haute de la tête (voir TeteGriffe) arrive à
    la hauteur du boîtier (au-dessus de z_bas), c'est elle seule qui compte."""

    x: Intervalle
    y: Intervalle
    bas_z_max: float
    z_bas: float
    # Haut du boîtier (m) : la préhension passe au-dessus (obligatoire s'il y a la préhension).
    z_haut: float | None = None


class BoutCoteFutGriffe(Modele):
    """Bout côté fût : tête sous x = x_max → bas de la tête ≥ bas_min_hors_fut hors du fût,
    ≥ bas_min_paroi au-dessus de la paroi du fût."""

    x_max: float
    bas_min_hors_fut: float
    bas_min_paroi: float


class PorteSprayGriffe(Modele):
    """Porte du coffret du spray ouverte : griffe interdite en x < x_max et y < y_max."""

    x_max: float
    y_max: float


class VitessesGriffe(Modele):
    """Vitesses maximales (m/s ; °/s pour la rotation)."""

    pont_x: float = Field(gt=0)
    chariot_y: float = Field(gt=0)
    griffe_z: float = Field(gt=0)
    griffe_a: float = Field(gt=0)
    griffe_b: float = Field(gt=0)
    # Vitesses lentes de l'axe Z, par nom.
    descente_lente: float = Field(gt=0)
    plongee: float = Field(gt=0)
    remontee_choc: float = Field(gt=0)


class DescenteGriffe(Modele):
    # Descente rapide jusqu'au dernier niveau connu + marge, puis lente.
    marge_niveau_m: float = Field(gt=0)
    # Contact : la charge pendue baisse de plus que ce seuil (N).
    seuil_contact_n: float = Field(gt=0)
    # Butée basse logicielle (secours) : bas du godet au plus à cette distance sous le fond.
    butee_sous_fond_m: float = Field(ge=0)


class MachouillerGriffe(Modele):
    bouchees: int = Field(ge=0, le=10)
    # Le godet se ferme jusqu'à cette ouverture (0 fermé, 1 grand ouvert) et se rouvre.
    fermeture: float = Field(ge=0, le=1)
    # Entre deux bouchées, le mât enfonce le godet de tant, force limitée.
    enfoncement_m: float = Field(ge=0)
    force_max_n: float = Field(gt=0)


class PriseGriffe(Modele):
    enfoncement_m: float = Field(ge=0)
    # Le mât descend encore de tant pendant la fermeture (prise en plongée).
    plongee_m: float = Field(ge=0)
    # Pesée : le mât remonte de tant et s'arrête.
    remontee_m: float = Field(gt=0)
    pesee_attente_s: float = Field(ge=0)
    # Prise bonne si son poids est à ± tolerance (fraction) du poids voulu.
    tolerance: float = Field(gt=0, lt=1)
    volume_max_l: float = Field(gt=0)
    # Trop lourd : le godet s'entrouvre de tant, se referme, et on repèse.
    entrouvrir: float = Field(gt=0, le=1)
    entrouvrir_essais_max: int = Field(ge=0)
    # Trop léger : on reprend à côté au plus tant de fois, puis on porte ce qu'on a.
    reprises_max: int = Field(ge=0)
    # Moins que ça (kg) au fond : pas de prise utile, le fût est vide.
    utile_min_kg: float = Field(ge=0)
    # Où prendre pendant les couches : des cercles autour de l'axe du fût (rayon du mât, m)
    # et le nombre de prises sur chacun, pris à tour de rôle.
    rayons_m: list[Annotated[float, Field(ge=0)]] = Field(min_length=1)
    points: list[Annotated[int, Field(ge=1)]] = Field(min_length=1)

    @model_validator(mode="after")
    def _verifier(self) -> "PriseGriffe":
        if len(self.rayons_m) != len(self.points):
            raise ValueError("rayons_m et points : autant de valeurs l'un que l'autre")
        return self


class VidageGriffe(Modele):
    # Hauteur des axes au vidage = haut du seau + ça.
    au_dessus_haut_m: float
    # Le godet s'ouvre en grand en tournant de tant (au plus).
    rotation_deg: float = Field(ge=0)
    # Haut du seau au-dessus de ça : vidage tête bloquée, sans tourner.
    rotation_haut_max_z: float


class TassementGriffe(Modele):
    # Le fond du godet fermé appuie sur la couche jusqu'à ce que la charge baisse de tant (N).
    force_n: float = Field(gt=0)
    appuis: int = Field(ge=1)
    # Entre deux appuis, le godet remonte de tant et attend (le seau tourne).
    remontee_m: float = Field(gt=0)
    attente_s: float = Field(ge=0)


class EssuyageGriffe(Modele):
    # Mât à rayon du haut du seau + decalage_m de l'axe du seau, axes à haut + au_dessus_haut_m.
    decalage_m: float = Field(gt=0)
    au_dessus_haut_m: float
    # Direction (°, depuis +x) où va le mât par rapport à l'axe du seau.
    direction_deg: float
    # Temps d'un tour du seau sous la raclette (s).
    duree_s: float = Field(gt=0)


class RaclageGriffe(Modele):
    # La tranche de la lame appuie de tant contre la paroi.
    appui_m: float = Field(ge=0)
    # Le tour commence avec le bas du godet à tant sous le bord du fût.
    depart_sous_bord_m: float = Field(ge=0)
    points_par_tour: int = Field(ge=4)


class FondGriffe(Modele):
    """Passe de fond : elle commence quand la pesée du fût annonce les derniers kilos."""

    # Substrat restant (kg) qui lance la passe de fond...
    passe_kg: float = Field(ge=0)
    # ... ou niveau (bas du godet au contact) à moins de tant au-dessus du fond (sans pesée).
    passe_hauteur_m: float = Field(ge=0)
    # Godet en appui au fond : la charge baisse de tant (N) ; poussée limitée à force_max_n.
    seuil_appui_n: float = Field(gt=0)
    force_max_n: float = Field(gt=0)
    # Prises en appui en spirale depuis le centre : un cercle tous les spirale_pas_m (mât),
    # jusqu'à spirale_rayon_max_m.
    spirale_pas_m: float = Field(gt=0)
    spirale_rayon_max_m: float = Field(ge=0)
    # Prises le long de la paroi : combien, rayon du mât, ouverture au plus.
    paroi_prises: int = Field(ge=0)
    paroi_rayon_m: float = Field(gt=0)
    paroi_ouverture_max: float = Field(gt=0, le=1)
    # Orientation (° dans la tête, à A = 0) de la joue du godet : à mettre parallèle à la paroi.
    joue_angle_deg: float
    # Chasse-neige : godet fermé, lame inclinée de tant par rapport au rayon, bas du godet à
    # tant au-dessus du fond.
    chasse_neige_angle_deg: float
    chasse_neige_au_dessus_fond_m: float = Field(ge=0)
    centre_prises: int = Field(ge=0)


class ForceGriffe(Modele):
    """Pesée de la griffe (capteur 50 kg + HX711, lue par une carte RP2040 sur le bus RS485
    des pesées : vidange.pesees ; étalonnage dans pesees.yaml)."""

    # Lectures par seconde pendant les descentes et les trajets.
    frequence_hz: float = Field(gt=0)
    # Choc : force qui s'écarte de tant (N) de celle attendue pendant un trajet.
    choc_n: float = Field(gt=0)
    # Lectures prises pour une pesée (médiane).
    lectures_pesee: int = Field(ge=1)
    # Pesée muette pendant tant de secondes : la griffe s'arrête.
    silence_max_s: float = Field(gt=0)


class TableVolumes(Modele):
    """Volume pris (L) selon l'ouverture du godet (0 à 1) et l'enfoncement (m)."""

    ouvertures: list[Annotated[float, Field(ge=0, le=1)]] = Field(min_length=2)
    enfoncements_m: list[Annotated[float, Field(ge=0)]] = Field(min_length=1)
    # Une ligne par ouverture, une colonne par enfoncement.
    litres: list[list[Annotated[float, Field(ge=0)]]]

    @model_validator(mode="after")
    def _verifier(self) -> "TableVolumes":
        erreurs = []
        for nom, valeurs in (
            ("ouvertures", self.ouvertures),
            ("enfoncements_m", self.enfoncements_m),
        ):
            if any(a >= b for a, b in zip(valeurs, valeurs[1:], strict=False)):
                erreurs.append(f"{nom} : du plus petit au plus grand, sans doublon")
        if len(self.litres) != len(self.ouvertures) or any(
            len(ligne) != len(self.enfoncements_m) for ligne in self.litres
        ):
            erreurs.append("litres : une ligne par ouverture, une colonne par enfoncement")
        else:
            for colonne in range(len(self.enfoncements_m)):
                volumes = [ligne[colonne] for ligne in self.litres]
                if any(a >= b for a, b in zip(volumes, volumes[1:], strict=False)):
                    erreurs.append("litres : le volume doit grandir avec l'ouverture")
                    break
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class DosesGriffe(Modele):
    """Apprendre les doses : poids ≈ densité × volume (table des volumes)."""

    # Densité (kg/L) des premières prises d'un fût, avant d'en avoir appris assez.
    densite_defaut_kg_l: float = Field(gt=0)
    prises_avant_apprentissage: int = Field(ge=1)
    # Densité apprise sur les dernières prises du fût (combien).
    prises_apprises: int = Field(ge=1)
    # Corrections de départ des prises près de la paroi et au fond (densité × facteur),
    # remplacées par celles apprises après prises_avant_correction prises de ce genre.
    correction_paroi: float = Field(gt=0)
    correction_fond: float = Field(gt=0)
    prises_avant_correction: int = Field(ge=1)


class FormatSeau(Modele):
    """Un format de seau, posé au poste de remplissage (table des formats)."""

    # Haut du seau, rayon du haut (m).
    haut_z: float
    rayon_haut: float = Field(gt=0)
    couches: int = Field(ge=1)
    # Substrat par couche (kg).
    dose_kg: float = Field(gt=0)
    # Tasser chaque couche (sinon : seulement la dernière, comme le seau de 5 L).
    tasser_chaque_couche: bool
    # Tassement : mât à tant de l'axe du seau (0 : tête centrée), bas du godet au plus à tant
    # sous le bord.
    tassement_rayon_m: float = Field(ge=0)
    tassement_bas_max_sous_bord_m: float = Field(gt=0)
    # Pour le Mycélium (obligatoires s'il y a la partie « mycelium ») : hauteur du seau (m),
    # mycélium par couche (kg), et combien de seaux de ce format un bocal peut servir (2 pour
    # les petits seaux, de la même variété).
    hauteur: float | None = Field(default=None, gt=0)
    mycelium_kg: float | None = Field(default=None, gt=0)
    seaux_par_bocal: int = Field(default=1, ge=1, le=2)
    # Poids du seau vide (kg), tare par type de seau (docs/decisions.md). La préhension s'en sert
    # pour confirmer la prise d'un seau vide ; sans lui, elle prend son poids estimé.
    tare_kg: float | None = Field(default=None, gt=0)
    # Pour le Stockage (obligatoire s'il y a la partie « stockage ») : de combien monte le bord
    # quand on ajoute un seau à une pile (m).
    pas_pile_m: float | None = Field(default=None, gt=0)


class Griffe(Modele):
    """Griffe sur mât (transfert fût → seau), module gelé le 25/10/2026.

    Repère du portique, en mètres. « z » = hauteur des axes de la tête ; « mât » = position du
    mât de la griffe (pont + decalage_mat_x en x). Un verrou du logiciel ne protège que la
    machine : la sécurité des personnes reste câblée.
    """

    # Vrai tant que des chiffres sont inventés (formats, vitesses, doses...).
    exemple: bool = False
    decalage_mat_x: float
    # Bas du godet = hauteur des axes − bas_godet_sous_axes.
    bas_godet_sous_axes: float = Field(gt=0)
    tete: TeteGriffe
    pont_x_min: float
    rotation: RotationGriffe
    # Mât en y godet grand ouvert (godet fermé : course de chariot_y).
    mat_y_grand_ouvert: Intervalle
    trajet: TrajetGriffe
    garage_glissiere: list[BandeGriffe]
    # Écart sous lequel les axes sont « en butée haute » (fin de la course de griffe_z), en m.
    tolerance_butee_haute_m: float = Field(gt=0)
    dosage: ZoneMatGriffe
    camera_bocal: CameraBocalGriffe
    bout_cote_fut: BoutCoteFutGriffe
    porte_spray: PorteSprayGriffe
    # Dans le fût (bas du godet sous le bord) : mât à au plus fut_rayon_mat_max_m de l'axe du
    # fût, et côté −x au plus fut_moins_x_max_m.
    fut_rayon_mat_max_m: float = Field(gt=0)
    fut_moins_x_max_m: float = Field(gt=0)
    # Distance entre deux points vérifiés le long d'un mouvement (m).
    pas_verification_m: float = Field(gt=0)
    # Orientation (°, depuis +x) de la raclette quand A = 0, et distance mât → tranche de la lame.
    raclette_angle_deg: float
    raclette_decalage_m: float = Field(gt=0)
    vitesses: VitessesGriffe
    descente: DescenteGriffe
    machouiller: MachouillerGriffe
    prise: PriseGriffe
    vidage: VidageGriffe
    tassement: TassementGriffe
    essuyage: EssuyageGriffe
    raclage: RaclageGriffe
    fond: FondGriffe
    force: ForceGriffe
    volumes: TableVolumes
    doses: DosesGriffe
    formats: dict[Nom, FormatSeau] = Field(min_length=1)
    format_par_defaut: Nom
    # Axe du seau au poste de remplissage, en position du mât (Remplissage pas figé).
    seau_remplissage: tuple[float, float]
    # Où le mât attend, hors de la zone du chariot du fût, quand le fût est vide.
    attente: tuple[float, float]

    @model_validator(mode="after")
    def _verifier(self) -> "Griffe":
        erreurs = []
        if self.format_par_defaut not in self.formats:
            erreurs.append(f"format_par_defaut : « {self.format_par_defaut} » absent de formats")
        if self.trajet.z <= self.rotation.bloquee_z_min:
            erreurs.append(
                "trajet → z : les trajets se font tête bloquée (au-dessus de bloquee_z_min)"
            )
        for nom, (x, _) in (("seau_remplissage", self.seau_remplissage), ("attente", self.attente)):
            if x < self.trajet.mat_x_min_pour_y:
                erreurs.append(
                    f"{nom} : mât à x {x:g}, il faut x ≥ trajet → mat_x_min_pour_y "
                    f"({self.trajet.mat_x_min_pour_y:g}) pour y aller en y"
                )
        for bande in self.garage_glissiere:
            if bande.x[0] >= bande.x[1]:
                erreurs.append("garage_glissiere : x du plus petit au plus grand")
        if self.fond.force_max_n < self.fond.seuil_appui_n:
            erreurs.append("fond → force_max_n doit être au moins seuil_appui_n")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


# Délais (machine.yaml → durees) des étapes du Mycélium.
DUREES_MYCELIUM = ("mycelium_geste_max", "mycelium_chariot_max", "mycelium_agitation_max")
# Les 2 axes de l'agitateur du Mycélium (carte n° 3) et leur unité.
AXES_MYCELIUM = {
    "agitateur_x": "m",  # glissière de l'agitateur (repère du portique)
    "manivelle": "deg",  # manivelle qui secoue le bocal (360° = un tour)
}


class ChariotMycelium(Modele):
    """Le chariot de remplissage vu du Mycélium (verrous, hauteur du plateau)."""

    # L'agitateur ne roule que si le chariot est à y ≥ y_ecarte_min.
    y_ecarte_min: float
    # Le seau sous le bocal : chariot à y_dosage.
    y_dosage: float
    tolerance_y_m: float = Field(gt=0)
    # Plateau pendant le dosage : min(bord_seau_z − hauteur du seau ; plateau_max_z).
    bord_seau_z: float
    plateau_max_z: float
    tolerance_plateau_m: float = Field(gt=0)


class OrigineManivelle(Modele):
    """Prise d'origine de la manivelle par le Pi (docs/decisions.md, 29/10/2026).

    Le capteur origine_manivelle voit du métal quand la manivelle n'est PAS en haut, et rien sur
    une zone d'environ 190° autour du haut. Un tour lent, toujours dans le même sens : « en haut »
    = le milieu de la zone sans métal, plus un décalage (hystérésis du capteur).
    """

    # Vitesse du tour lent (°/s). Précision ≈ vitesse × periode_etat_s (fluidnc.yaml) / 2.
    vitesse_deg_s: float = Field(gt=0)
    # Largeur de la zone sans métal, mesurée une fois sur la machine (°), et l'écart permis à
    # chaque prise d'origine : au-delà, arrêt et alerte « capteur manivelle ».
    largeur_zone_deg: float = Field(gt=0, lt=360)
    ecart_largeur_max_deg: float = Field(gt=0)
    # Décalage fixe ajouté au milieu de la zone (°), réglé une fois sur la machine.
    decalage_deg: float = Field(ge=-180, le=180)
    # Le tour lent fait 360° + largeur + écart + cette marge (°) : la zone est vue en entier,
    # même en partant de dedans.
    marge_deg: float = Field(ge=0)

    def balayage_deg(self) -> float:
        return 360 + self.largeur_zone_deg + self.ecart_largeur_max_deg + self.marge_deg

    @model_validator(mode="after")
    def _verifier(self) -> "OrigineManivelle":
        if self.largeur_zone_deg + self.ecart_largeur_max_deg >= 360:
            raise ValueError("largeur_zone_deg + ecart_largeur_max_deg doit rester < 360")
        if self.ecart_largeur_max_deg >= self.largeur_zone_deg:
            raise ValueError("ecart_largeur_max_deg doit rester < largeur_zone_deg")
        return self


class ManivelleMycelium(Modele):
    # Angle (°) de « manivelle en haut » ; « en bas » = 180° plus loin. Écart permis (°).
    angle_haut_deg: float
    tolerance_deg: float = Field(gt=0)
    # Les 3 trous de la manivelle (course du bocal, m), et la plus grande permise au garage
    # (au-delà, le fond du bocal toucherait la marche du poste du fût).
    courses_possibles_m: list[float] = Field(min_length=1)
    course_max_garage_m: float = Field(gt=0)
    # Vitesse la plus forte permise (tr/min, fiche).
    max_tr_min: float = Field(gt=0)
    origine: OrigineManivelle


class VitessesMycelium(Modele):
    glissiere_m_s: float = Field(gt=0)
    # Manivelle (tr/min) : pour aller en haut ou en bas, pour doser, pour la casse du bloc.
    placement_tr_min: float = Field(gt=0)
    agitation_tr_min: float = Field(gt=0)
    casse_tr_min: float = Field(gt=0)


class DoseMycelium(Modele):
    # Arrêter de secouer quand il manque encore tant (kg) : grains qui tombent pendant l'arrêt.
    arret_avant_kg: float = Field(ge=0)
    # Écart permis (part de la dose) : au-delà, la dose est signalée dans le journal.
    tolerance: float = Field(ge=0, lt=1)
    # Au plus tant de secondes d'agitation pour une couche (casse du bloc non comprise).
    temps_max_s: float = Field(gt=0)
    # Casse du bloc, au 1er seau d'un bocal seulement (s ; 0 : pas de casse).
    casse_du_bloc_s: float = Field(ge=0)
    # Attente avant de peser (le plateau ne bouge plus), s.
    attente_pesee_s: float = Field(ge=0)


class PeseeMycelium(Modele):
    """La balance du chariot de remplissage, lue pendant l'agitation."""

    frequence_hz: float = Field(gt=0)
    # Médiane de tant de lectures pour une pesée.
    lectures_pesee: int = Field(ge=1)
    # Saut brutal : la médiane des « lectures_saut » dernières lectures s'écarte de plus de
    # saut_kg de celle des « lectures_saut » d'avant.
    lectures_saut: int = Field(ge=1)
    saut_kg: float = Field(gt=0)
    # Balance muette pendant tant de secondes pendant l'agitation : arrêt.
    silence_max_s: float = Field(gt=0)


class Mycelium(Modele):
    """Module Mycélium (dosage), validé le 24/10/2026 (option B : module relevé de 12 mm).

    Repère du portique, en mètres ; x = position de l'agitateur sur sa glissière. Un verrou du
    logiciel ne protège que la machine : la sécurité des personnes reste câblée.
    """

    exemple: bool = False
    garage_x: float
    demi_tour_x: float
    dosage_x: float
    tolerance_x_m: float = Field(gt=0)
    # La caméra du dosage ne pivote vers le seau que si l'agitateur est à x ≤ camera_x_max.
    camera_x_max: float
    # Axe de la manivelle (m) : pour mémoire (aucun geste n'en dépend).
    manivelle_z: float
    # Course choisie à la main (trou de la bielle), tenue à jour par Karulium (m).
    course_agitation_m: float
    chariot: ChariotMycelium
    manivelle: ManivelleMycelium
    vitesses: VitessesMycelium
    dose: DoseMycelium
    pesee: PeseeMycelium

    @model_validator(mode="after")
    def _verifier(self) -> "Mycelium":
        erreurs = []
        if not self.garage_x < self.demi_tour_x < self.dosage_x:
            erreurs.append("garage_x < demi_tour_x < dosage_x : dans cet ordre")
        if self.camera_x_max < self.garage_x:
            erreurs.append("camera_x_max : la caméra doit pouvoir pivoter agitateur au garage")
        manivelle = self.manivelle
        if self.course_agitation_m not in manivelle.courses_possibles_m:
            possibles = ", ".join(f"{c:g}" for c in manivelle.courses_possibles_m)
            erreurs.append(
                f"course_agitation_m : {self.course_agitation_m:g} n'est pas un trou de la "
                f"manivelle ({possibles})"
            )
        v = self.vitesses
        for nom in ("placement_tr_min", "agitation_tr_min", "casse_tr_min"):
            if getattr(v, nom) > manivelle.max_tr_min:
                erreurs.append(
                    f"vitesses → {nom} : au plus manivelle → max_tr_min ({manivelle.max_tr_min:g})"
                )
        if self.chariot.y_dosage >= self.chariot.y_ecarte_min:
            erreurs.append("chariot → y_dosage doit être sous y_ecarte_min")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self

    def tours_max(self) -> int:
        """Le plus de tours d'une agitation (casse du bloc + dosage), arrondi au-dessus."""
        dose, v = self.dose, self.vitesses
        casse = -int(-v.casse_tr_min * dose.casse_du_bloc_s // 60)
        return casse - int(-v.agitation_tr_min * dose.temps_max_s // 60)


class DemiTourPorteBocal(Modele):
    """Le demi-tour du bocal : motoréducteur JGY370 (pont en H) et verrou à électroaimant."""

    # Le doigt du verrou est retiré pendant tant de secondes au départ (le plateau quitte son
    # trou), puis relâché : il frotte, puis entre dans le trou suivant.
    relache_s: float = Field(gt=0)
    # Le contact « verrou engagé » doit revenir dans ce délai (s), sinon arrêt du moteur, alerte.
    delai_max_s: float = Field(gt=0)
    # Attente après l'arrêt du moteur avant de lire le capteur d'inclinaison (s) ; au moins
    # 2 fois periode_etat_s de fluidnc.yaml (les entrées de la carte arrivent avec son état).
    attente_inclinaison_s: float = Field(ge=0)

    @model_validator(mode="after")
    def _verifier(self) -> "DemiTourPorteBocal":
        if self.relache_s >= self.delai_max_s:
            raise ValueError("relache_s doit être plus court que delai_max_s")
        return self


class ApprochePorteBocal(Modele):
    """Mors approchés à « Ø 98 » à faible courant, pendant que la préhension pose le bocal :
    ils le guident sans le serrer, et cèdent s'il les touche."""

    # Écart entre les mors (m).
    ecart_m: float = Field(gt=0)
    # Courant du pilote des mors (A) pendant l'approche, puis celui du serrage (le même que
    # run_amps dans fluidnc/), remis avant tout autre geste des mors.
    courant_faible_a: float = Field(gt=0)
    courant_serrage_a: float = Field(gt=0)


class PorteBocal(Modele):
    """Porte-bocal (mors et demi-tour du bocal), validé le 24/10/2026.

    Les mors sont l'axe « mors » de machine.yaml : sa position est l'écart entre les 2 mors (m).
    """

    exemple: bool = False
    # Bocal droit (diamètre serré par les mors) et sa capsule (m).
    diametre_bocal_m: float = Field(gt=0)
    diametre_capsule_m: float = Field(gt=0)
    # Écart permis sur le diamètre mesuré au serrage : au-delà, bocal absent, cassé ou mal posé.
    tolerance_diametre_m: float = Field(gt=0)
    # Vitesse de palpage des mors (m/s, chaque mors), au-dessus du minimum de StallGuard.
    palpage_m_s: float = Field(gt=0)
    demi_tour: DemiTourPorteBocal
    # Ce que dit le capteur d'inclinaison quand il est actionné.
    inclinaison_actionne: Literal["tete_en_bas", "debout"]
    # Mors approchés pour la pose du bocal par la préhension (None : pas d'approche).
    approche: ApprochePorteBocal | None = None


# Les 2 axes de la tête de préhension (carte n° 4) et leur unité. Le mât de la préhension est
# sur le même pont et le même chariot que la griffe (pont_x, chariot_y, carte n° 1).
AXES_PREHENSION = {
    "pont_x": "m",
    "chariot_y": "m",
    "prehension_z": "m",
    "prehension_a": "deg",
}
# Signaux de la tête lus ou commandés par sa carte FluidNC (docs/entrees-sorties.yaml).
ENTREES_PREHENSION = ("contact_tete",)
SORTIES_PREHENSION = ("vanne_vide", "electroaimants_capsule")
# Objets que la tête sait prendre (les modules qui s'en servent en ajouteront).
OBJETS_PREHENSION = ("seau", "couvercle", "bocal", "capsule")


class SeauTenuPrehension(Modele):
    """Seau tenu : son bord (le haut du seau) au plus à bord_max_operateur_z quand son axe est
    côté opérateur (y > y_operateur), au plus à bord_max_piles_z au-dessus des piles."""

    y_operateur: float
    bord_max_operateur_z: float
    bord_max_piles_z: float


class CameraDosagePrehension(Modele):
    """Boîte où la tête (et ce qu'elle tient) ne va pas pendant que la caméra du dosage pivote :
    x < x_max, y < y_max, z dans z."""

    x_max: float
    y_max: float
    z: Intervalle


class AccelerationPrehension(Modele):
    """Accélération des axes X et Y de la carte du portique (mm/s²) : normale (celle de
    fluidnc/), et réduite quand la tête tient un seau (l'anse balance)."""

    normale_mm_s2: float = Field(gt=0)
    seau_mm_s2: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier(self) -> "AccelerationPrehension":
        if self.seau_mm_s2 > self.normale_mm_s2:
            raise ValueError("seau_mm_s2 doit être au plus normale_mm_s2")
        return self


class VitessesPrehension(Modele):
    """Vitesses maximales (m/s ; °/s pour la rotation)."""

    pont_x: float = Field(gt=0)
    chariot_y: float = Field(gt=0)
    z: float = Field(gt=0)
    a: float = Field(gt=0)
    # Vitesses lentes de Z, par nom : derniers cm d'une descente, début de la levée, levée quand
    # le vide est faible, remontée après un choc ; rotation pendant le vissage (°/s).
    approche: float = Field(gt=0)
    levee_lente: float = Field(gt=0)
    remontee_choc: float = Field(gt=0)
    vissage_deg_s: float = Field(gt=0)


class DescentePrehension(Modele):
    # Lente sur les derniers cm (m) au-dessus de la cote attendue du contact.
    approche_m: float = Field(gt=0)
    # Contact à plus de tant de la cote attendue (m) : arrêt et alerte.
    ecart_contact_max_m: float = Field(gt=0)


class VidePrehension(Modele):
    """Vide de la ventouse (kPa, négatif : −55 = 55 kPa sous la pression de l'air)."""

    # Prise bonne quand le vide atteint prise_kpa ; perdue s'il remonte au-dessus de perte_kpa.
    prise_kpa: float = Field(lt=0)
    perte_kpa: float = Field(lt=0)
    # Attente maximale du vide après l'ouverture de la vanne (s).
    delai_prise_s: float = Field(gt=0)
    # Attente après la fermeture de la vanne, pour que l'objet se détache (s).
    relache_s: float = Field(ge=0)
    # Lectures par seconde, et combien sont moyennées.
    frequence_hz: float = Field(gt=0)
    moyenne: int = Field(ge=1)
    # Après tant d'échecs de levée (vide perdu), alerte.
    essais_max: int = Field(ge=1)
    # Zéro recalé à chaque démarrage, vanne fermée : moyenne de tant de lectures. Un zéro plus
    # loin que zero_ecart_max_kpa de 0 : capteur déréglé ou vanne qui fuit, arrêt.
    zero_lectures: int = Field(ge=1)
    zero_ecart_max_kpa: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier(self) -> "VidePrehension":
        if self.prise_kpa >= self.perte_kpa:
            raise ValueError("prise_kpa doit être un vide plus fort (plus bas) que perte_kpa")
        return self


class ForcePrehension(Modele):
    """Palier pesé du mât (carte de pesée RS485) : lecture = poids porté − poussée (N)."""

    frequence_hz: float = Field(gt=0)
    # Pesée muette pendant tant de secondes pendant un geste : arrêt.
    silence_max_s: float = Field(gt=0)
    # Une pesée = médiane de tant de lectures, après attente_pesee_s d'arrêt.
    lectures_pesee: int = Field(ge=1)
    attente_pesee_s: float = Field(ge=0)
    # Choc en trajet : écart de plus de choc_n entre la force lue et le poids porté, pendant
    # plus de choc_duree_s.
    choc_n: float = Field(gt=0)
    choc_duree_s: float = Field(ge=0)
    # Remontée lente après un choc (m).
    remontee_choc_m: float = Field(gt=0)


class ObjetPrehension(Modele):
    """Un objet que la tête prend : encombrement autour de l'axe de la tête et poids estimé."""

    rayon_m: float = Field(gt=0)
    # Ce qui dépasse au-dessus et au-dessous de la face de la tête quand elle le tient (m).
    dessus_m: float = Field(ge=0)
    dessous_m: float = Field(ge=0)
    # Poids estimé (N) et écart permis ; None : trop léger pour être contrôlé (capsule).
    poids_n: float | None = Field(default=None, gt=0)
    tolerance_n: float = Field(default=0, ge=0)
    # Tenu par les électroaimants (capsule), pas par la ventouse.
    aimants: bool = False


class VissagePrehension(Modele):
    """Visser ou dévisser une capsule Twist-Off : rotation et Z ensemble sur la carte n° 4."""

    # Appui (N) : consigne, plage acceptée, arrêt et alerte au-delà de arret_n.
    appui_n: float = Field(gt=0)
    appui_min_n: float = Field(gt=0)
    appui_max_n: float = Field(gt=0)
    arret_n: float = Field(gt=0)
    # Course maximale de Z pour trouver l'appui (m), angle de vissage (°), et descente de Z
    # pendant le vissage (m, le porte-ventouse à ressort absorbe le reste).
    course_appui_m: float = Field(gt=0)
    angle_deg: float = Field(gt=0)
    descente_m: float = Field(ge=0)

    @model_validator(mode="after")
    def _verifier(self) -> "VissagePrehension":
        if not self.appui_min_n <= self.appui_n <= self.appui_max_n < self.arret_n:
            raise ValueError("il faut appui_min_n ≤ appui_n ≤ appui_max_n < arret_n")
        return self


class PorteBocalPrehension(Modele):
    """Pose et reprise du bocal dans le porte-bocal, au garage de l'agitateur."""

    # Axe du bocal (m) et face de la tête quand le bocal est à sa hauteur exacte entre les mors.
    x: float
    y: float
    face_z: float
    # Orientation de la tête (°, grâce aux méplats) et écart permis.
    orientation_deg: float
    tolerance_orientation_deg: float = Field(gt=0)
    # Écart permis sur la hauteur du bocal (m), remontée avant le serrage (m).
    tolerance_hauteur_m: float = Field(gt=0)
    remontee_min_m: float = Field(gt=0)
    # Autour de l'axe du bocal (m) : tête « entre les mors » (elle ne tourne pas) sous face_z +
    # descente → approche_m.
    rayon_zone_m: float = Field(gt=0)
    # Attente maximale d'un geste des mors (s).
    mors_max_s: float = Field(gt=0)
    # Zone du garage : axe de la tête à zone_garage_m près de (x, y) en x et en y. Seule
    # exception à l'isolation du fût : la tête y descend à la verticale, agitateur au garage
    # manivelle en bas avec la course déclarée course_manivelle_m (celle de face_z), mors ouverts
    # pour poser, serrés pour prendre, griffe en butée haute.
    zone_garage_m: float = Field(gt=0)
    course_manivelle_m: float = Field(gt=0)
    # Haut de la capsule manivelle en haut (m) : la tête (et l'objet tenu) ne passe pas au-dessus
    # du bocal au garage, à marge_bocal_m près, tant que la manivelle n'est pas en bas.
    capsule_manivelle_haut_z: float
    marge_bocal_m: float = Field(ge=0)


class Prehension(Modele):
    """Tête de préhension (ventouse, électroaimants, rotation), module validé le 27/10/2026.

    Repère du portique, en mètres. « x, y » = axe de la tête (pont + decalage_mat_x en x, même y
    que la griffe) ; « z » = hauteur de la face de la tête. Un verrou du logiciel ne protège que
    la machine : la sécurité des personnes reste câblée.
    """

    exemple: bool = False
    decalage_mat_x: float
    # Face de la tête en butée haute : « en haut ».
    haut_z: float
    rayon_tete_m: float = Field(gt=0)
    # Isolation du fût : axe de la tête sous x isolation_fut_x_max et panneau du poste du fût
    # pas vu rabattu ⇒ face en haut.
    isolation_fut_x_max: float
    seau_tenu: SeauTenuPrehension
    # Boîtier de la caméra du bocal (griffe → camera_bocal) : marge autour (m).
    camera_bocal_marge_m: float = Field(ge=0)
    camera_dosage: CameraDosagePrehension
    acceleration: AccelerationPrehension
    # Écart sous lequel la face est « en haut » ou à une cote voulue (m ; ° pour la rotation).
    tolerance_m: float = Field(gt=0)
    tolerance_deg: float = Field(gt=0)
    # Distance entre deux points vérifiés le long d'un mouvement (m).
    pas_verification_m: float = Field(gt=0)
    vitesses: VitessesPrehension
    descente: DescentePrehension
    vide: VidePrehension
    # Levée lente sur les premiers mm (m).
    levee_lente_m: float = Field(gt=0)
    force: ForcePrehension
    objets: dict[Nom, ObjetPrehension]
    vissage: VissagePrehension
    porte_bocal: PorteBocalPrehension

    @model_validator(mode="after")
    def _verifier(self) -> "Prehension":
        erreurs = [
            f"objets : il manque « {nom} »" for nom in OBJETS_PREHENSION if nom not in self.objets
        ]
        if "capsule" in self.objets and not self.objets["capsule"].aimants:
            erreurs.append("objets → capsule : elle est tenue par les électroaimants (aimants)")
        bas, haut = self.camera_dosage.z
        if bas >= haut:
            erreurs.append("camera_dosage → z : du plus petit au plus grand")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


# Les 2 axes des brosses du lavage (NEMA 23 sur la carte de la préhension : la rotation de la
# tête est dans la même commande, elle suit le seau). Pas de capteur d'origine.
AXES_LAVAGE = {"lavage_noyau": "deg", "lavage_couronne": "deg"}
# Signaux du lavage (docs/entrees-sorties.yaml), chacun sur la carte FluidNC où fluidnc.yaml le
# met (cartes n° 3 et n° 4).
ENTREES_LAVAGE = ("flotteur_lavage",)
SORTIES_LAVAGE = (
    "eau_reseau_lavage",
    "vanne_vidange_lavage",
    "pompe_lavage",
    "vanne_rampes_lavage",
    "rincage_lavage",
    "air_col_lavage",
    "chauffage_lavage",
)


# Objets lavés au lave-bocal (prehension → objets) : le bocal vide retourné, la capsule.
OBJETS_LAVE_BOCAL = ("bocal_vide", "capsule")


class FormatLavage(Modele):
    """Ce qui change d'un format de seau à l'autre, au lavage (en m)."""

    # Brossage : tête décalée de façon fixe vers +x (c'est le seau qui tourne dessous).
    decalage_brossage_m: float = Field(ge=0)
    # Passe 2 (le bord) : remontée de la tête depuis l'appui de la passe 1 (0 : même hauteur).
    remontee_passe_2_m: float = Field(ge=0)
    # Jet d'air du col : centre du seau (axe de la tête, x, y) face à la buse, son bord arrêté à
    # jet_bord_z.
    jet_centre: tuple[float, float]
    jet_bord_z: float


class PhaseBrossage(Modele):
    """Un moment d'une passe : noyau, couronne et seau tournent ensemble pendant duree_s."""

    duree_s: float = Field(gt=0)
    # Noyau et couronne ne tournent que dans un sens (« en avant »).
    noyau_tr_min: float = Field(ge=0)
    couronne_tr_min: float = Field(ge=0)
    # Tours du seau (rotation de la tête) pendant la phase ; négatif : dans l'autre sens.
    seau_tours: float

    @model_validator(mode="after")
    def _verifier(self) -> "PhaseBrossage":
        if not (self.noyau_tr_min or self.couronne_tr_min or self.seau_tours):
            raise ValueError("une phase fait tourner au moins le noyau, la couronne ou le seau")
        return self


class BrossageLavage(Modele):
    # Face de la tête quand le fond du seau retourné touche le noyau (à peu près : l'appui est
    # cherché au capteur de force). Descente rapide jusqu'à approche_m au-dessus, puis lente
    # jusqu'à l'appui, sur course_appui_m au plus.
    face_contact_z: float
    approche_m: float = Field(gt=0)
    appui_n: float = Field(gt=0)
    course_appui_m: float = Field(gt=0)
    # Rotation de la tête (°) : chaque passe part de − depart_passe_deg si ses tours vont dans
    # le sens +, de + depart_passe_deg sinon, et la tête revient à 0 à la fin de la passe. Deux
    # passes de suite ne tournent jamais dans le même sens (cordon spiralé du vide et des fils).
    depart_passe_deg: float = Field(gt=0)
    passe_1: list[PhaseBrossage] = Field(min_length=1)
    passe_2: list[PhaseBrossage] = Field(min_length=1)


class EauLavage(Modele):
    # Temps pour ouvrir ou fermer la vanne à bille motorisée, pour tourner la vanne 3 voies (s).
    vanne_vidange_s: float = Field(ge=0)
    vanne_rampes_s: float = Field(ge=0)
    # Le flotteur compte quand il n'a pas bougé depuis tant de secondes (vagues).
    flotteur_stable_s: float = Field(ge=0)
    # Remplissage : temps maximal tant que le premier n'est pas mesuré, puis temps du premier
    # remplissage mesuré + marge (0,2 = 20 %). Au-delà : électrovanne fermée, alerte.
    premier_remplissage_max_s: float = Field(gt=0)
    marge_remplissage: float = Field(ge=0)
    # Vidange : temps maximal jusqu'au flotteur bas, puis pompe encore apres_flotteur_s.
    vidange_max_s: float = Field(gt=0)
    apres_flotteur_s: float = Field(ge=0)
    # Eau changée après tant de seaux (None : une eau par série, vidée à la fin).
    seaux_max_par_eau: int | None = Field(default=None, ge=1)


class VerrouLavage(Modele):
    """Noyau et couronne ne tournent que si la tête est à sa hauteur de travail au-dessus du fût
    (axe à moins de rayon_m du centre, face sous face_max_z) et qu'elle tient un objet (vide)."""

    rayon_m: float = Field(gt=0)
    face_max_z: float


class RincageLavage(Modele):
    # Électrovanne de rinçage ouverte tant de secondes (≈ 0,5 L dans les rampes), puis la
    # pompe vide jusqu'au flotteur bas (au plus vidange_max_s), puis l'eau du réseau remet le
    # fût au flotteur haut (au plus remise_max_s), pour que le bain reste chauffé.
    duree_s: float = Field(gt=0)
    vidange_max_s: float = Field(gt=0)
    remise_max_s: float = Field(gt=0)


class JetAirLavage(Modele):
    # Un tour du seau devant la buse (s), puis égouttage au-dessus du fût (s).
    tour_s: float = Field(gt=0)
    egouttage_s: float = Field(ge=0)


class FormatCouvercle(Modele):
    """Couvercle d'un format de seau, au lavage dans le fût (en m)."""

    # Bas du couvercle tenu (son point le plus bas) à l'appui sur le noyau : face « dessous »
    # lavée (couvercle à l'endroit), ou face « dessus » lavée (couvercle retourné).
    bas_dessous_z: float
    bas_dessus_z: float
    # Centre du couvercle décalé de tant depuis le centre du noyau, pendant le brossage.
    decalage_m: float = Field(ge=0)


class RetourneurCouvercles(Modele):
    """Retourneur de couvercles : tige sur une barre du chariot de remplissage, bac inox sur le
    plateau fixe. Les barres et le chariot appartiennent au Remplissage."""

    # Axe de la tête pour lâcher le couvercle au-dessus de la tige, et hauteur de sa face.
    lacher: tuple[float, float]
    lacher_face_z: float
    # Après la chute, axe de la tête à x ≤ recul_x_max pour la photo du bac.
    recul_x_max: float
    # Écart des barres depuis l'axe de la tête (m) : fermées, ouvertes. Ouvertes avant que la
    # tête descende sous ouvertes_sous_z ; refermées seulement tête au-dessus de
    # fermees_au_dessus_z ; au plus barres_max_s pour bouger.
    barres_fermees_m: float = Field(gt=0)
    barres_ouvertes_m: float = Field(gt=0)
    ouvertes_sous_z: float
    fermees_au_dessus_z: float
    barres_max_s: float = Field(gt=0)
    # Face de la tête au contact d'un couvercle à plat dans le bac.
    bac_contact_z: float
    # La caméra trouve le bac et la tige à tant de leur place, sinon le mode ne démarre pas.
    tolerance_place_m: float = Field(gt=0)
    # Couvercle pas retourné après la chute : nouvelle chute ; alerte après tant d'échecs.
    chutes_max: int = Field(ge=1)


class CouverclesLavage(Modele):
    """Lavage des couvercles de seau dans le fût, contre le noyau."""

    # Axe de la tête au-dessus du noyau (le pont est à sa limite : x ≥ 0,352).
    centre: tuple[float, float]
    # Repère collé sur le dessus : avant la pose, la tête le met à repere_angle_deg (compté depuis
    # −X, côté +Y, comme les angles de la caméra). sens_repere : +1 si l'angle du repère grandit
    # quand la rotation de la tête grandit, −1 sinon.
    repere_angle_deg: float
    sens_repere: Literal[1, -1] = 1
    # Descente rapide jusqu'à approche_m au-dessus de l'appui ; plateau flottant déclenché avec
    # la face au-dessus de contact_trop_haut_z : arrêt et alerte. Appui de appui_n, jamais plus.
    contact_trop_haut_z: float
    approche_m: float = Field(gt=0)
    appui_n: float = Field(gt=0)
    # Brossage : noyau à noyau_tr_min pendant duree_s, couvercle tourné à rotation_tr_min ;
    # centre décalé dans la direction (x, y). Le repère est contrôlé tous les controle_s.
    noyau_tr_min: float = Field(gt=0)
    duree_s: float = Field(gt=0)
    rotation_tr_min: float = Field(gt=0)
    direction_decalage: tuple[float, float]
    controle_s: float = Field(gt=0)
    # Repère à plus de glissement_max_deg de l'angle commandé : le couvercle glisse (arrêt du
    # noyau, remontée de remontee_glissement_m, reprise) ; alerte au glissements_max-ième.
    glissement_max_deg: float = Field(gt=0)
    remontee_glissement_m: float = Field(gt=0)
    glissements_max: int = Field(ge=1)
    egouttage_s: float = Field(ge=0)
    formats: dict[Nom, FormatCouvercle] = Field(min_length=1)
    retourneur: RetourneurCouvercles

    @model_validator(mode="after")
    def _verifier(self) -> "CouverclesLavage":
        if math.hypot(*self.direction_decalage) < 1e-6:
            raise ValueError("couvercles → direction_decalage : une direction, pas (0, 0)")
        r = self.retourneur
        if r.barres_ouvertes_m <= r.barres_fermees_m:
            raise ValueError("couvercles → retourneur : barres ouvertes plus loin que fermées")
        if r.fermees_au_dessus_z < r.ouvertes_sous_z:
            raise ValueError("couvercles → retourneur : fermees_au_dessus_z sous ouvertes_sous_z")
        if r.lacher_face_z < r.ouvertes_sous_z:
            raise ValueError(
                "couvercles → retourneur → lacher_face_z : sous ouvertes_sous_z (les barres "
                "fermées sont sous la tête)"
            )
        return self


class LaveBocal(Modele):
    """Lave-bocal (rince-verre de bar) posé à la main sur l'anneau de rive du fût de lavage."""

    # Axe de la tête au-dessus du plateau du rince-verre, et hauteur du plateau.
    centre: tuple[float, float]
    plateau_z: float
    # Descente rapide jusqu'à approche_m au-dessus du plateau, puis appui de appui_n (cherché
    # sur course_appui_m au plus), tenu duree_s ; puis égouttage au-dessus du fût.
    approche_m: float = Field(gt=0)
    appui_n: float = Field(gt=0)
    course_appui_m: float = Field(gt=0)
    duree_s: float = Field(gt=0)
    egouttage_s: float = Field(ge=0)


class Lavage(Modele):
    """Lavage des seaux (fût de lavage, noyau, couronne, eau), module validé le 25/10/2026.

    Repère du portique, en mètres ; « x, y » = axe de la tête de préhension, « z » = sa face.
    Un verrou du logiciel ne protège que la machine : la sécurité des personnes reste câblée.
    """

    exemple: bool = False
    # Centre du fût de lavage (pas celui du fût de production : poste_fut → centre_fut).
    centre_fut: tuple[float, float]
    fut_diametre_interieur: float = Field(gt=0)
    # Couloir du seau retourné : du fût en ligne droite jusqu'au coude, puis vers +x à son y.
    coude_couloir: tuple[float, float]
    verrou: VerrouLavage
    eau: EauLavage
    # Pompe en marche (voie des rampes) depuis tant de secondes avant de brosser.
    arrosage_avant_s: float = Field(ge=0)
    brossage: BrossageLavage
    rincage: RincageLavage
    jet_air: JetAirLavage
    formats: dict[Nom, FormatLavage] = Field(min_length=1)
    # Couvercles et bocaux (tâche 21 bis) ; None : pas lavés par la machine.
    couvercles: CouverclesLavage | None = None
    lave_bocal: LaveBocal | None = None


class ImpulsionServo(Modele):
    """Impulsion du servo (µs) pour deux angles (°) : droite entre les deux."""

    angles_deg: Intervalle
    us: Intervalle


class PwmServo(Modele):
    """Sortie PWM matérielle du Pi 5 (overlay « pwm-2chan ») : dossier de Linux et canal."""

    fichier: Annotated[str, StringConstraints(pattern=r"^/sys/class/pwm/pwmchip[0-9]+$")]
    canal: int = Field(ge=0, le=3)
    periode_us: int = Field(gt=0)


class CameraDosage(Modele):
    """La caméra du dosage sur son servo DS3225 (docs/decisions.md, règle 2). La boîte interdite
    à la griffe et à la préhension pendant qu'elle pivote est « prehension → camera_dosage » ;
    l'agitateur garé, « mycelium → camera_x_max »."""

    exemple: bool = False
    # Nom du signal du servo dans docs/entrees-sorties.yaml.
    signal: Nom
    angle_bocal_deg: float
    angle_seau_deg: float
    # Temps (s) pour aller d'un angle à l'autre (le servo ne dit pas où il est).
    pivot_s: float = Field(gt=0)
    impulsion: ImpulsionServo
    pwm: PwmServo

    @model_validator(mode="after")
    def _verifier(self) -> "CameraDosage":
        erreurs = []
        (a0, a1), (u0, u1) = self.impulsion.angles_deg, self.impulsion.us
        if a0 >= a1:
            erreurs.append("impulsion → angles_deg : du plus petit au plus grand")
        if not 0 < u0 < self.pwm.periode_us or not 0 < u1 < self.pwm.periode_us:
            erreurs.append(f"impulsion → us : entre 0 et pwm → periode_us ({self.pwm.periode_us})")
        for nom in ("angle_bocal_deg", "angle_seau_deg"):
            angle = getattr(self, nom)
            if a0 < a1 and not a0 <= angle <= a1:
                erreurs.append(f"{nom} ({angle:g}°) hors de impulsion → angles_deg")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


# Délais (machine.yaml → durees) d'un geste du Remplissage et du dosage d'une couche.
DUREES_REMPLISSAGE = ("remplissage_geste_max", "remplissage_dosage_max")
# Les 5 axes du chariot de remplissage (carte n° 2) et leur unité.
AXES_REMPLISSAGE = {
    "remplissage_y": "m",  # avance du chariot (repère du portique)
    "plateau_z": "m",  # dessus du plateau
    "plateau_a": "deg",  # rotation du plateau
    "barres": "m",  # écartement hw : axe de la barre côté mur à l'axe du plateau
    "pousseur": "m",
    "barre_allee": "m",  # écartement hw de la barre côté allée (son propre moteur, 31/10)
}


class VerrousRemplissage(Modele):
    """Les positions interdites du chariot (fichier des positions, règles 1 à 11). Ces verrous
    ne protègent que la machine : la sécurité des personnes reste câblée."""

    # Règle 1 : anneaux du fût (bandes de y) : plateau en bas (dessus ≤ anneaux_plateau_max_z),
    # sauf dans la zone du poste et du dosage (libre_poste_y).
    anneaux_y: list[Intervalle] = Field(min_length=1)
    anneaux_plateau_max_z: float
    libre_poste_y: Intervalle
    # Règle 2 : barres entre les joues de l'élévateur (bande de hw) : plateau ≤ tant.
    joues_barres: Intervalle
    joues_plateau_max_z: float
    # Règle 3 : plateau au-dessus de tant : barres ouvertes (hw ≥ barres_ouvertes_min).
    barres_ouvertes_au_dessus_z: float
    barres_ouvertes_min: float
    # Règle 4 : pousseur sorti seulement plateau en bas (plateau_en_bas_z) et au plus à tant
    # (dessus du plateau) : la plus stricte des deux s'applique.
    pousseur_plateau_max_z: float
    # Règle 5 : plateau au-dessus de tant seulement bras du galet rangé.
    galet_plateau_max_z: float
    # Règle 6 (spray, tâche 39) : plateau ≤ min(spray_plateau_max_z ; spray_bord_max_z − h),
    # entraxe des barres > spray_entraxe_min_m.
    spray_plateau_max_z: float
    spray_bord_max_z: float
    spray_entraxe_min_m: float = Field(gt=0)
    # Règle 7 : chariot du fût pas en place : bout du chariot côté allée (y + bout_y_m) ≤
    # poste_fut → remplissage_y_bout_max.
    bout_y_m: float = Field(ge=0)
    # Règle 9 (préhension) : pas de descente de la face de la tête sous tant au-dessus du
    # chariot, sauf barres ouvertes et tête du micropore rentrée (et en mode couvercles).
    # « Au-dessus du chariot » : axe de la tête à moins de emprise_demi_x_m de axe_x, et en y entre
    # y − emprise_mur_y_m et y + bout_y_m (y : axe du plateau).
    prehension_libre_z: float
    emprise_demi_x_m: float = Field(gt=0)
    emprise_mur_y_m: float = Field(ge=0)


class BarresRemplissage(Modele):
    # hw (m) où la plaque de chaque barre actionne son origine (côté mur, côté allée) : FluidNC
    # compte 0 là, le Pi ajoute ce décalage (réglé une fois sur la machine).
    origine_hw_m: float
    origine_allee_hw_m: float
    # Les 2 barres bougent ensemble : plus d'écart que tant (m) entre elles est refusé.
    ecart_max_m: float = Field(gt=0)
    # « Ouvertes » pour les gestes (hw, m).
    ouvertes_m: float
    # Centrage en position : barres à formats → centrage_hw_m + tant (m).
    jeu_centrage_m: float = Field(ge=0)
    # Lâcher pendant la prise double : chaque barre s'écarte de tant (m).
    lacher_m: float = Field(gt=0)
    # Contre la lèvre du seau du dessous (prise double) : entraxe = Ø haut + jeu.
    jeu_rainure_m: float = Field(ge=0)
    # Ouverture complète (s), pour mémoire et pour le simulateur.
    ouverture_s: float = Field(gt=0)


class VitessesRemplissage(Modele):
    """Vitesses (m/s, °/s pour la rotation)."""

    y: float = Field(gt=0)
    plateau: float = Field(gt=0)
    rotation: float = Field(gt=0)
    barres: float = Field(gt=0)
    pousseur: float = Field(gt=0)
    # Barres qui centrent le seau, plateau qui monte au contact.
    centrage: float = Field(gt=0)
    contact: float = Field(gt=0)


class PoseSeauRemplissage(Modele):
    """Pose d'un seau vide (docs/decisions.md, Remplissage, point 5) : barres à l'approche et
    plateau sous la hauteur de pose avant que la tête descende ; puis le plateau monte jusqu'au
    contact du fond, lu par la balance."""

    # Barres à l'approche (hw, m) : sous les joues de l'élévateur, plus larges que tout seau.
    barres_approche_hw_m: float = Field(gt=0)
    # Plateau d'approche : formats → pose_plateau_z − tant (et pas au-dessus des joues). Il doit
    # rester sous le contact d'une prise double (≈ 3 cm plus bas qu'un seau seul).
    plateau_sous_pose_m: float = Field(gt=0)
    # Le plateau monte au plus jusqu'à formats → pose_plateau_z + tant pour trouver le contact.
    contact_au_dessus_m: float = Field(ge=0)
    # Contact du plateau : la balance gagne tant de kg (pose et prise double e).
    contact_kg: float = Field(gt=0)


class PriseDoubleRemplissage(Modele):
    """Séparation de deux seaux emboîtés posés ensemble (barrière coupée après la pose, barres
    déjà serrées) : le plateau descend de descente_plateau_m (b), la tête de descente_tete_m (c),
    le plateau remonte au contact du seau du dessous (e), la tête tire de tirage_m (f), le
    plateau remonte de remontee_plateau_m à la fin (h)."""

    descente_plateau_m: float = Field(gt=0)
    descente_tete_m: float = Field(gt=0)
    tirage_m: float = Field(gt=0)
    remontee_plateau_m: float = Field(ge=0)
    # Au plus tant de newtons par barre pendant le tirage (capteur de force de la tête).
    traction_max_par_barre_n: float = Field(gt=0)
    # Le plateau monte au plus de tant pour toucher le fond du seau du dessous (e).
    toucher_max_m: float = Field(gt=0)


class PeseeRemplissage(Modele):
    """La balance du plateau (carte de pesée RS485, tâche 22 bis)."""

    frequence_hz: float = Field(gt=0)
    # Médiane de tant de lectures, après attente_s plateau arrêté.
    lectures: int = Field(ge=1)
    attente_s: float = Field(ge=0)
    # Poids d'un seau vide quand son format n'a pas de tare (kg), et le seuil « deux seaux » :
    # au-delà de seuil_deux_seaux × poids d'un seau, il y en a plus d'un.
    seau_vide_kg: float = Field(gt=0)
    seuil_deux_seaux: float = Field(gt=1, lt=2)
    # Mode inspection : poids du bocal posé, lu par la tête et par la balance, d'accord à tant
    # près (kg).
    accord_kg: float = Field(gt=0)


class FileRemplissage(Modele):
    """Une file de rangement (place exacte : Stockage, tâche 35), poussée plateau en bas."""

    y: float
    # Le pousseur va jusque-là pour pousser le seau sur la file (m, axe « pousseur »).
    pousseur_m: float


class RangementRemplissage(Modele):
    files: dict[Nom, FileRemplissage] = Field(default_factory=dict)


class FormatRemplissage(Modele):
    """Ce que le Remplissage sait d'un format de seau (en plus de la table de la griffe)."""

    # Plateau à la pose du seau vide (dessus, m) : bord d'un seul seau sous la barrière.
    pose_plateau_z: float
    # Barres au contact du corps, sous le rebord (hw, m) : centrage en position.
    centrage_hw_m: float


class CouverclesRemplissage(Modele):
    """Mode couvercles (retourneur, tâche 21 bis) : chariot à y, plateau fixe, sans rotation."""

    y: float
    plateau_z: float


class InspectionRemplissage(Modele):
    """Mode inspection des bocaux : plateau fixe, barres ouvertes, arrêts de pas_deg."""

    plateau_z: float
    pas_deg: float = Field(gt=0, le=180)


class Remplissage(Modele):
    """Module Remplissage, gelé le 27/10/2026 : le chariot des seaux (avance, plateau, rotation,
    barres, pousseur, balance). Repère du portique, en mètres ; y = axe du plateau. Un verrou du
    logiciel ne protège que la machine : la sécurité des personnes reste câblée."""

    exemple: bool = False
    # Axe du plateau en x (le chariot roule en y).
    axe_x: float
    # Positions en y : poste (sous la griffe), dosage du mycélium, recul pendant le passage de
    # l'agitateur (au moins), pose du seau vide et du couvercle.
    poste_y: float
    dosage_y: float
    ecarte_y: float
    pose_y: float
    # Écarts permis (m, °) ; un mouvement est vérifié point par point, tous les tant (m).
    tolerance_y_m: float = Field(gt=0)
    tolerance_m: float = Field(gt=0)
    tolerance_deg: float = Field(gt=0)
    pas_verification_m: float = Field(gt=0)
    # Plateau « en bas » : dessus ≤ tant.
    plateau_en_bas_z: float
    # Pousseur rentré (m, axe « pousseur »).
    pousseur_rentre_m: float
    # Direction des barres (° depuis +x, vue de dessus) ; oreilles de l'anse à anse_deg de cette
    # direction, modulo 90°.
    barres_direction_deg: float
    anse_deg: float
    # La face de la tête de préhension touche le fond intérieur du seau à tant au-dessus du
    # plateau (pose du seau vide).
    face_au_dessus_plateau_m: float = Field(ge=0)
    verrous: VerrousRemplissage
    barres: BarresRemplissage
    vitesses: VitessesRemplissage
    pose_seau: PoseSeauRemplissage
    prise_double: PriseDoubleRemplissage
    pesee: PeseeRemplissage
    rangement: RangementRemplissage
    formats: dict[Nom, FormatRemplissage] = Field(min_length=1)
    couvercles: CouverclesRemplissage
    inspection: InspectionRemplissage

    @model_validator(mode="after")
    def _verifier(self) -> "Remplissage":
        erreurs = []
        v = self.verrous
        for nom, (debut, fin) in [
            ("verrous → libre_poste_y", v.libre_poste_y),
            ("verrous → joues_barres", v.joues_barres),
            *((f"verrous → anneaux_y n° {i}", a) for i, a in enumerate(v.anneaux_y, start=1)),
        ]:
            if debut >= fin:
                erreurs.append(f"{nom} : du plus petit au plus grand")
        if not v.libre_poste_y[0] <= self.poste_y <= v.libre_poste_y[1]:
            erreurs.append("poste_y doit être dans verrous → libre_poste_y")
        if not self.poste_y < self.ecarte_y:
            erreurs.append("ecarte_y doit être au-delà de poste_y")
        if v.barres_ouvertes_min > self.barres.ouvertes_m:
            erreurs.append("barres → ouvertes_m doit être au moins verrous → barres_ouvertes_min")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


# -------------------------------------------------------------- stockage


Point = tuple[float, float]


class FinDeLotStockage(Modele):
    """Places de fin de lot, sur une bande en y : x calculés par le Pi (vidange.stockage.places)."""

    y: float
    # Bord de la 1re pile au plus près de x_debut ; ecart_m entre deux piles ; bord de la dernière
    # à marge_hublot_m au moins de l'axe du hublot ; au plus places_max piles.
    x_debut: float
    ecart_m: float = Field(ge=0)
    marge_hublot_m: float = Field(ge=0)
    places_max: int = Field(ge=0)


class PilesStockage(Modele):
    """Piles de seaux vides (mode seaux) : n = min(⌊(bord_max_m − h)/pas⌋ + 1 ;
    ⌊(sortie_max_m − 2h)/pas⌋ + 1)."""

    bord_max_m: float = Field(gt=0)
    sortie_max_m: float = Field(gt=0)
    # Rangées vidées dans cet ordre (y) ; dans une rangée, la pile la plus proche du chariot.
    ordre_rangees_y: list[float] = Field(min_length=1)
    places: dict[Nom, Point] = Field(min_length=1)
    fin_de_lot: FinDeLotStockage
    couvercles: Point


class QuinconceStockage(Modele):
    cale_m: float = Field(gt=0)


class TiroirStockage(Modele):
    """Tiroir du bas : les files du Remplissage, poussées vers +x jusqu'à la butée."""

    tole_z: float
    entree_x: float
    butee_x: float
    avance_par_seau_m: float = Field(gt=0)
    poussee_min_m: float = Field(gt=0)
    effort_n: Intervalle
    # Noms des files (remplissage → rangement → files), remplies dans cet ordre.
    files: list[Nom] = Field(min_length=1)
    # Seaux par file, par format.
    places: dict[Nom, dict[Nom, Annotated[int, Field(ge=0)]]] = Field(min_length=1)
    quinconce: dict[Nom, QuinconceStockage] = Field(default_factory=dict)


class BandeHautStockage(Modele):
    """Bande du haut (seaux pleins sur le plateau) : case vide, désactivée (tâche 35 bis)."""

    active: bool = False
    y: float
    places: dict[Nom, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)


class RangeeBocaux(Modele):
    places: int = Field(ge=1)
    x0: float


class SemenceStockage(Modele):
    x0: float
    pas_x: float = Field(gt=0)
    colonnes: int = Field(ge=1)
    y: list[float] = Field(min_length=1)


class InspectionStockage(Modele):
    """Coin d'inspection : places [rangée j, rang i] du quinconce."""

    suspects: list[tuple[int, int]] = Field(min_length=1)
    separation: list[tuple[int, int]] = Field(default_factory=list)


class BocauxStockage(Modele):
    rangees: int = Field(ge=1)
    y0: float
    pas_y: float = Field(gt=0)
    pas_x: float = Field(gt=0)
    paires: RangeeBocaux
    impaires: RangeeBocaux
    pose_z: float
    capsule_haut_z: float
    semence: SemenceStockage
    inspection: InspectionStockage


class BoitesStockage(Modele):
    fond_z: float
    dessus_z: float
    diametre_m: float = Field(gt=0)
    epaisseur_capsule_m: float = Field(gt=0)
    places: dict[Nom, Point] = Field(min_length=1)


class HublotStockage(Modele):
    x: float
    y: float
    fond_bocal_z: Intervalle


class RailOperateurStockage(Modele):
    y_min: float
    bord_max_z: float


class CameraBocalStockage(Modele):
    seau_y_libre: float
    seau_x_min: float
    seau_fond_min_z: float
    # Coin du boîtier (x, y) : tête vide ou autre objet, axe à y ≥ coin y + rayon tant que
    # x < coin x + rayon.
    coin: Point


class TrajetsStockage(Modele):
    griffe_x_max: float
    seau_fond_min_z: float
    sortie_pile_marge_m: float = Field(ge=0)
    rail_operateur: RailOperateurStockage
    boites_bas_min_z: float
    camera_bocal: CameraBocalStockage


class Stockage(Modele):
    """Module Stockage, gelé le 27/10/2026 : passif (aucun moteur, aucun capteur de présence).
    Le Pi tient l'inventaire et calcule les places (vidange.stockage). Repère du portique (m)."""

    exemple: bool = False
    plateau_z: float
    panneaux: dict[Nom, Intervalle] = Field(min_length=1)
    piles: PilesStockage
    tiroir: TiroirStockage
    bande_haut: BandeHautStockage
    bocaux: BocauxStockage
    boites: BoitesStockage
    hublot: HublotStockage
    trajets: TrajetsStockage

    @model_validator(mode="after")
    def _verifier(self) -> "Stockage":
        erreurs = []
        intervalles = [
            *((f"panneaux → {nom}", valeur) for nom, valeur in self.panneaux.items()),
            ("tiroir → effort_n", self.tiroir.effort_n),
            ("hublot → fond_bocal_z", self.hublot.fond_bocal_z),
        ]
        for nom, (debut, fin) in intervalles:
            if debut >= fin:
                erreurs.append(f"{nom} : du plus petit au plus grand")
        if self.tiroir.entree_x >= self.tiroir.butee_x:
            erreurs.append("tiroir : l'entrée (entree_x) avant la butée (butee_x)")
        if len(set(self.tiroir.files)) != len(self.tiroir.files):
            erreurs.append("tiroir → files : une file écrite deux fois")
        if self.boites.dessus_z <= self.boites.fond_z:
            erreurs.append("boites : le dessus (dessus_z) au-dessus du fond (fond_z)")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class Machine(Modele):
    """machine.yaml : axes, positions nommées, zones réservées."""

    # Vrai tant que le fichier contient des valeurs inventées : le programme le signale.
    exemple: bool = False
    axes: dict[Nom, Axe] = Field(min_length=1)
    # Une position donne une valeur (m) pour un ou plusieurs axes.
    positions: dict[Nom, dict[Nom, float]] = Field(default_factory=dict)
    # Une zone donne un intervalle (m) pour un ou plusieurs axes ;
    # un axe non cité veut dire « toute sa course ».
    zones: dict[Nom, Annotated[dict[Nom, Intervalle], Field(min_length=1)]] = Field(
        default_factory=dict
    )
    # Délais maximaux des étapes (s), par nom : le code des modules ne cite que ces noms.
    durees: dict[Nom, Annotated[float, Field(gt=0)]] = Field(default_factory=dict)
    # Retour en lieu sûr (après une coupure, ou à la mise en route) : gestes faits dans l'ordre.
    lieu_sur: list[GesteLieuSur] = Field(default_factory=list)
    # Poste du fût (None : pas de poste du fût, pour des réglages d'essai).
    poste_fut: PosteFut | None = None
    # Griffe (None : pas de griffe, pour des réglages d'essai). Demande le poste du fût.
    griffe: Griffe | None = None
    # Mycélium (None : pas de mycélium). Demande la griffe (table des formats).
    mycelium: Mycelium | None = None
    # Porte-bocal (None : pas de porte-bocal). Son axe « mors » est sur une carte FluidNC.
    porte_bocal: PorteBocal | None = None
    # Préhension (None : pas de préhension). Demande la griffe (boîtier de la caméra du bocal,
    # formats des seaux) et le poste du fût.
    prehension: Prehension | None = None
    # Lavage des seaux (None : pas de lavage). Demande la préhension.
    lavage: Lavage | None = None
    # Caméra du dosage sur son servo (None : pas de servo). Demande la préhension (sa boîte)
    # et le mycélium (agitateur garé).
    camera_dosage: CameraDosage | None = None
    # Remplissage : le chariot des seaux (None : pas de remplissage). Demande la griffe (table
    # des formats) et le poste du fût.
    remplissage: Remplissage | None = None
    # Stockage : piles, tiroir, bocaux (None : pas de stockage). Demande la griffe (table des
    # formats), la préhension et le remplissage (files du tiroir).
    stockage: Stockage | None = None

    @model_validator(mode="after")
    def _verifier_positions_et_zones(self) -> "Machine":
        erreurs: list[str] = []
        for numero, geste in enumerate(self.lieu_sur, start=1):
            if geste.delai not in self.durees:
                erreurs.append(f"lieu_sur n° {numero} : délai « {geste.delai} » absent de durees")
            if geste.aller is None:
                continue
            if geste.aller not in self.positions:
                erreurs.append(f"lieu_sur n° {numero} : position inconnue « {geste.aller} »")
                continue
            for axe in self.positions[geste.aller]:
                if axe in self.axes and self.axes[axe].carte is None:
                    erreurs.append(
                        f"lieu_sur n° {numero} : l'axe « {axe} » de la position "
                        f"« {geste.aller} » n'a pas de carte FluidNC"
                    )
        lettres_prises: dict[tuple[str, str], str] = {}
        for nom, axe in self.axes.items():
            if axe.carte is None or axe.lettre is None:
                continue
            autre = lettres_prises.setdefault((axe.carte, axe.lettre), nom)
            if autre != nom:
                erreurs.append(
                    f"les axes « {autre} » et « {nom} » ont la même lettre {axe.lettre} "
                    f"sur la carte « {axe.carte} »"
                )
        for nom, valeurs in self.positions.items():
            for axe, valeur in valeurs.items():
                if axe not in self.axes:
                    erreurs.append(f"position « {nom} » : axe inconnu « {axe} »")
                    continue
                debut, fin = self.axes[axe].course
                if not debut <= valeur <= fin:
                    erreurs.append(
                        f"position « {nom} » : {axe} = {valeur:g} m sort de la course "
                        f"({debut:g} à {fin:g} m)"
                    )
        zones_correctes = []
        for nom, intervalles in self.zones.items():
            correcte = True
            for axe, (debut, fin) in intervalles.items():
                if axe not in self.axes:
                    erreurs.append(f"zone « {nom} » : axe inconnu « {axe} »")
                    correcte = False
                    continue
                course_debut, course_fin = self.axes[axe].course
                if debut >= fin:
                    erreurs.append(
                        f"zone « {nom} » : sur {axe}, aller du plus petit au plus grand "
                        f"({debut:g} puis {fin:g})"
                    )
                    correcte = False
                elif debut < course_debut or fin > course_fin:
                    erreurs.append(
                        f"zone « {nom} » : sur {axe}, {debut:g} à {fin:g} m sort de la course "
                        f"({course_debut:g} à {course_fin:g} m)"
                    )
                    correcte = False
            if correcte:
                zones_correctes.append(nom)
        erreurs += self._verifier_griffe()
        erreurs += self._verifier_mycelium()
        erreurs += self._verifier_porte_bocal()
        erreurs += self._verifier_prehension()
        erreurs += self._verifier_lavage()
        erreurs += self._verifier_remplissage()
        erreurs += self._verifier_stockage()
        if self.camera_dosage is not None and (self.prehension is None or self.mycelium is None):
            erreurs.append(
                "camera_dosage : il faut aussi les parties « prehension » et « mycelium »"
            )
        for i, nom_a in enumerate(zones_correctes):
            for nom_b in zones_correctes[i + 1 :]:
                if self._se_chevauchent(nom_a, nom_b):
                    erreurs.append(f"les zones « {nom_a} » et « {nom_b} » se chevauchent")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self

    def _verifier_griffe(self) -> list[str]:
        """Les axes de la griffe existent, et ses hauteurs ne sortent pas de leur course."""
        griffe = self.griffe
        if griffe is None:
            return []
        if self.poste_fut is None:
            return ["griffe : il faut aussi la partie « poste_fut »"]
        erreurs = []
        for nom, unite in AXES_GRIFFE.items():
            axe = self.axes.get(nom)
            if axe is None:
                erreurs.append(f"griffe : axe « {nom} » absent de axes")
            elif axe.unite != unite or axe.carte is None:
                erreurs.append(f"griffe : l'axe « {nom} » doit être en « {unite} », avec sa carte")
        if erreurs:
            return erreurs
        bas, haut = self.axes["griffe_z"].course

        def hauteur(quoi: str, z: float) -> None:
            if not bas <= z <= haut:
                erreurs.append(
                    f"griffe → {quoi} : axes à z {z:g} m, hors de la course de griffe_z "
                    f"({bas:g} à {haut:g} m)"
                )

        hauteur("trajet", griffe.trajet.z)
        for nom, seau in griffe.formats.items():
            hauteur(f"formats → {nom} (vidage)", seau.haut_z + griffe.vidage.au_dessus_haut_m)
            hauteur(f"formats → {nom} (essuyage)", seau.haut_z + griffe.essuyage.au_dessus_haut_m)
        pont = self.axes["pont_x"].course
        if pont[0] < griffe.pont_x_min:
            erreurs.append(f"pont_x : la course doit commencer à x ≥ {griffe.pont_x_min:g} m")
        return erreurs

    def _verifier_mycelium(self) -> list[str]:
        """Axes de l'agitateur, positions dans leur course, formats complets, délais."""
        mycelium = self.mycelium
        if mycelium is None:
            return []
        if self.griffe is None:
            return ["mycelium : il faut aussi la partie « griffe » (table des formats)"]
        erreurs = []
        for nom, unite in AXES_MYCELIUM.items():
            axe = self.axes.get(nom)
            if axe is None:
                erreurs.append(f"mycelium : axe « {nom} » absent de axes")
            elif axe.unite != unite or axe.carte is None:
                erreurs.append(
                    f"mycelium : l'axe « {nom} » doit être en « {unite} », avec sa carte"
                )
        for nom in DUREES_MYCELIUM:
            if nom not in self.durees:
                erreurs.append(f"mycelium : délai « {nom} » absent de durees")
        if erreurs:
            return erreurs
        debut, fin = self.axes["agitateur_x"].course
        for nom in ("garage_x", "demi_tour_x", "dosage_x"):
            x = getattr(mycelium, nom)
            if not debut - 1e-9 <= x <= fin + 1e-9:
                erreurs.append(
                    f"mycelium → {nom} : x {x:g} hors de la course de agitateur_x "
                    f"({debut:g} à {fin:g} m)"
                )
        debut, fin = self.axes["manivelle"].course
        tours = mycelium.tours_max() + 1
        if tours * 360 > min(-debut, fin):
            erreurs.append(
                f"manivelle : une agitation peut faire {tours} tours ({tours * 360:g}°) ; "
                f"la course ({debut:g} à {fin:g}°) doit les permettre dans les deux sens"
            )
        origine = mycelium.manivelle.origine
        tour_lent = origine.balayage_deg() / origine.vitesse_deg_s
        if self.durees.get("mycelium_geste_max", 0) <= tour_lent:
            erreurs.append(
                f"durees → mycelium_geste_max doit dépasser le tour lent de la prise d'origine de "
                f"la manivelle ({tour_lent:.0f} s)"
            )
        agitation = mycelium.dose.temps_max_s + mycelium.dose.casse_du_bloc_s
        if self.durees.get("mycelium_agitation_max", 0) <= agitation:
            erreurs.append(
                f"durees → mycelium_agitation_max doit dépasser dose → temps_max_s + "
                f"casse_du_bloc_s ({agitation:g} s)"
            )
        chariot = mycelium.chariot
        for nom, seau in self.griffe.formats.items():
            if seau.hauteur is None or seau.mycelium_kg is None:
                erreurs.append(
                    f"griffe → formats → {nom} : « hauteur » et « mycelium_kg » sont demandés "
                    "par le mycélium"
                )
                continue
            plateau = min(chariot.bord_seau_z - seau.hauteur, chariot.plateau_max_z)
            if abs(plateau + seau.hauteur - seau.haut_z) > 0.001:
                erreurs.append(
                    f"griffe → formats → {nom} : au dosage, plateau à {plateau:g} m et bord du "
                    f"seau à {plateau + seau.hauteur:g} m, mais haut_z vaut {seau.haut_z:g}"
                )
        return erreurs

    def _verifier_porte_bocal(self) -> list[str]:
        """L'axe des mors existe ; ouverts, ils laissent passer la capsule ; le diamètre attendu
        est dans leur course."""
        porte_bocal = self.porte_bocal
        if porte_bocal is None:
            return []
        axe = self.axes.get("mors")
        if axe is None or axe.unite != "m" or axe.carte is None:
            return ["porte_bocal : il faut l'axe « mors » en « m », avec sa carte"]
        erreurs = []
        ferme, ouvert = axe.course
        if ouvert < porte_bocal.diametre_capsule_m:
            erreurs.append(
                f"porte_bocal : mors ouverts à {ouvert:g} m (fin de la course de « mors »), la "
                f"capsule ({porte_bocal.diametre_capsule_m:g} m) ne passerait pas"
            )
        tolerance = porte_bocal.tolerance_diametre_m
        if not ferme < porte_bocal.diametre_bocal_m - tolerance:
            erreurs.append(
                f"porte_bocal : le début de la course de « mors » ({ferme:g} m) doit être sous "
                "diametre_bocal_m − tolerance_diametre_m (pour voir un bocal absent)"
            )
        if not porte_bocal.diametre_bocal_m + tolerance < ouvert:
            erreurs.append(
                "porte_bocal : diametre_bocal_m + tolerance_diametre_m doit être sous les mors "
                f"ouverts ({ouvert:g} m)"
            )
        return erreurs

    def _verifier_prehension(self) -> list[str]:
        """Les axes de la préhension existent ; ses cotes sont dans leur course."""
        prehension = self.prehension
        if prehension is None:
            return []
        if self.griffe is None or self.poste_fut is None:
            return ["prehension : il faut aussi les parties « griffe » et « poste_fut »"]
        erreurs = []
        for nom, unite in AXES_PREHENSION.items():
            axe = self.axes.get(nom)
            if axe is None or axe.unite != unite or axe.carte is None:
                erreurs.append(
                    f"prehension : il faut l'axe « {nom} » en « {unite} », avec sa carte"
                )
        if erreurs:
            return erreurs
        z, a = self.axes["prehension_z"], self.axes["prehension_a"]
        if z.carte != a.carte:
            erreurs.append(
                "prehension : prehension_z et prehension_a sur la même carte (vissage : rotation "
                "et Z ensemble)"
            )
        if self.axes["pont_x"].carte == z.carte:
            erreurs.append("prehension : le pont et la tête sont sur deux cartes différentes")
        if "prehension_geste_max" not in self.durees:
            erreurs.append("prehension : délai « prehension_geste_max » absent de durees")
        debut, fin = z.course
        if not debut <= prehension.haut_z <= fin:
            erreurs.append(
                f"prehension → haut_z : {prehension.haut_z:g} m hors de la course de "
                f"prehension_z ({debut:g} à {fin:g} m)"
            )
        porte_bocal = prehension.porte_bocal
        if not debut <= porte_bocal.face_z <= fin:
            erreurs.append(
                f"prehension → porte_bocal → face_z : {porte_bocal.face_z:g} m hors de la course "
                f"de prehension_z ({debut:g} à {fin:g} m)"
            )
        mycelium = self.mycelium
        if mycelium is not None:
            if abs(porte_bocal.x - mycelium.garage_x) > porte_bocal.zone_garage_m:
                erreurs.append(
                    f"prehension → porte_bocal → x : {porte_bocal.x:g} m, loin du garage de "
                    f"l'agitateur (mycelium → garage_x : {mycelium.garage_x:g} m)"
                )
            manivelle = mycelium.manivelle
            course = porte_bocal.course_manivelle_m
            if (
                course not in manivelle.courses_possibles_m
                or course > manivelle.course_max_garage_m
            ):
                erreurs.append(
                    f"prehension → porte_bocal → course_manivelle_m : {course:g} m n'est pas un "
                    "trou de la manivelle permis au garage (mycelium → manivelle)"
                )
        if self.griffe.camera_bocal.z_haut is None:
            erreurs.append("griffe → camera_bocal : il faut « z_haut » pour la préhension")
        if self.porte_bocal is None or self.porte_bocal.approche is None:
            erreurs.append("prehension : il faut la partie « porte_bocal » avec son « approche »")
        return erreurs

    def _verifier_lavage(self) -> list[str]:
        """Les axes des brosses existent sur la carte de la tête ; chaque position du lavage est
        à la portée de la tête ; les tours du seau tiennent dans la course de sa rotation."""
        lavage = self.lavage
        if lavage is None:
            return []
        prehension, griffe, poste = self.prehension, self.griffe, self.poste_fut
        if prehension is None or griffe is None or poste is None:
            return ["lavage : il faut aussi la partie « prehension »"]
        if any(nom not in self.axes for nom in AXES_PREHENSION):
            return []
        erreurs = []
        carte_tete = self.axes["prehension_z"].carte
        for nom, unite in AXES_LAVAGE.items():
            axe = self.axes.get(nom)
            if axe is None or axe.unite != unite or axe.carte != carte_tete:
                erreurs.append(
                    f"lavage : il faut l'axe « {nom} » en « {unite} », sur la carte de la tête "
                    f"« {carte_tete} » (la rotation de la tête est dans la même commande)"
                )
        for duree in ("lavage_geste_max", "lavage_eau_max"):
            if duree not in self.durees:
                erreurs.append(f"lavage : délai « {duree} » absent de durees")
        if "seau_retourne" not in prehension.objets:
            erreurs.append("lavage : il faut l'objet « seau_retourne » dans prehension → objets")
        for nom, seau in griffe.formats.items():
            if nom not in lavage.formats:
                erreurs.append(f"lavage → formats : il manque « {nom} » (griffe → formats)")
            elif seau.hauteur is None:
                erreurs.append(f"griffe → formats → {nom} : il faut « hauteur » pour le lavage")
        erreurs += [
            f"lavage → formats → {nom} : format absent de griffe → formats"
            for nom in lavage.formats
            if nom not in griffe.formats
        ]
        pont_debut, pont_fin = self.axes["pont_x"].course
        x_min, x_max = pont_debut + prehension.decalage_mat_x, pont_fin + prehension.decalage_mat_x
        z_debut, z_fin = self.axes["prehension_z"].course
        centre_x = lavage.centre_fut[0]
        brossage = lavage.brossage
        if brossage.face_contact_z > lavage.verrou.face_max_z:
            erreurs.append(
                "lavage → brossage → face_contact_z : au-dessus de verrou → face_max_z (le noyau "
                "ne pourrait pas tourner)"
            )
        if not z_debut <= brossage.face_contact_z - brossage.course_appui_m:
            erreurs.append(
                "lavage → brossage : face_contact_z − course_appui_m sous la course de prehension_z"
            )
        y_debut, y_fin = self.axes["chariot_y"].course

        def hors_portee(ou: str, x: float, y: float | None = None) -> None:
            if not x_min - 1e-9 <= x <= x_max + 1e-9:
                erreurs.append(
                    f"lavage → {ou} : axe de la tête à x {x:g} m, hors de sa portée ({x_min:g} à "
                    f"{x_max:g} m = course du pont + {prehension.decalage_mat_x:g})"
                )
            if y is not None and not y_debut - 1e-9 <= y <= y_fin + 1e-9:
                erreurs.append(f"lavage → {ou} : axe de la tête à y {y:g} m, hors de sa course")

        for nom, reglage in lavage.formats.items():
            if nom not in griffe.formats:
                continue
            hors_portee(
                f"formats → {nom} → decalage_brossage_m", centre_x + reglage.decalage_brossage_m
            )
            hors_portee(f"formats → {nom} → jet_centre", *reglage.jet_centre)
            if reglage.decalage_brossage_m > lavage.verrou.rayon_m:
                erreurs.append(
                    f"lavage → formats → {nom} → decalage_brossage_m : plus loin du centre que "
                    "verrou → rayon_m (le noyau ne pourrait pas tourner)"
                )
            hauteur = griffe.formats[nom].hauteur
            if hauteur is not None and not z_debut <= reglage.jet_bord_z + hauteur <= z_fin:
                erreurs.append(
                    f"lavage → formats → {nom} → jet_bord_z : face de la tête à "
                    f"{reglage.jet_bord_z + hauteur:g} m, hors de la course de prehension_z"
                )
        a_debut, a_fin = self.axes["prehension_a"].course
        depart = brossage.depart_passe_deg
        if not (a_debut <= -depart and depart <= a_fin):
            erreurs.append("lavage → brossage → depart_passe_deg : hors de la course de la tête")
        sens_passes = []
        for nom_passe, phases in (("passe_1", brossage.passe_1), ("passe_2", brossage.passe_2)):
            tours = sum(phase.seau_tours for phase in phases)
            if abs(tours) < 1e-9:
                erreurs.append(f"lavage → brossage → {nom_passe} : le seau doit tourner")
                continue
            sens_passes.append(tours > 0)
            angle = -depart if tours > 0 else depart
            for numero, phase in enumerate(phases, start=1):
                angle += phase.seau_tours * 360
                if not a_debut <= angle <= a_fin:
                    erreurs.append(
                        f"lavage → brossage → {nom_passe} : après la phase n° {numero}, la tête "
                        f"serait à {angle:g}°, hors de la course de prehension_a ({a_debut:g} à "
                        f"{a_fin:g}°)"
                    )
                    break
        if len(sens_passes) == 2 and sens_passes[0] == sens_passes[1]:
            erreurs.append(
                "lavage → brossage : passe_1 et passe_2 tournent dans le même sens (jamais deux "
                "passes de suite dans le même sens)"
            )
        if a_fin < 360 and a_debut > -360:
            erreurs.append(
                "lavage : depuis 0, la rotation de la tête doit pouvoir faire un tour (jet d'air)"
            )
        # Le couloir passe la paroi côté stockage selon les règles du poste du fût.
        if lavage.coude_couloir[1] > poste.lavage_paroi_axe_y_max:
            erreurs.append(
                "lavage → coude_couloir : y au-delà de poste_fut → lavage_paroi_axe_y_max"
            )
        if prehension.haut_z < poste.lavage_paroi_fond_seau_min_z:
            erreurs.append(
                "lavage : prehension → haut_z sous poste_fut → lavage_paroi_fond_seau_min_z"
            )
        couvercles = lavage.couvercles
        if couvercles is not None:
            hors_portee("couvercles → centre", *couvercles.centre)
            for nom in griffe.formats:
                if nom not in couvercles.formats:
                    erreurs.append(f"lavage → couvercles → formats : il manque « {nom} »")
            erreurs += [
                f"lavage → couvercles → formats → {nom} : format absent de griffe → formats"
                for nom in couvercles.formats
                if nom not in griffe.formats
            ]
            couvercle = prehension.objets.get("couvercle")
            dx, dy = couvercles.direction_decalage
            longueur = math.hypot(dx, dy)
            for nom, reglage in couvercles.formats.items():
                x = couvercles.centre[0] + reglage.decalage_m * dx / longueur
                y = couvercles.centre[1] + reglage.decalage_m * dy / longueur
                hors_portee(f"couvercles → formats → {nom} → decalage_m", x, y)
                ecart = math.hypot(x - lavage.centre_fut[0], y - lavage.centre_fut[1])
                if ecart > lavage.verrou.rayon_m + 1e-9:
                    erreurs.append(
                        f"lavage → couvercles → formats → {nom} : axe de la tête à {ecart:.3f} m "
                        "du centre du fût, plus loin que verrou → rayon_m (le noyau ne pourrait "
                        "pas tourner)"
                    )
                if couvercle is None:
                    continue
                for face in ("dessous", "dessus"):
                    face_z = getattr(reglage, f"bas_{face}_z") + couvercle.dessous_m
                    if face_z > lavage.verrou.face_max_z + 1e-9:
                        erreurs.append(
                            f"lavage → couvercles → formats → {nom} → bas_{face}_z : face de la "
                            "tête au-dessus de verrou → face_max_z (le noyau ne pourrait pas "
                            "tourner)"
                        )
                    if face_z >= couvercles.contact_trop_haut_z:
                        erreurs.append(
                            f"lavage → couvercles → formats → {nom} → bas_{face}_z : appui "
                            "au-dessus de contact_trop_haut_z"
                        )
            r = couvercles.retourneur
            hors_portee("couvercles → retourneur → lacher", *r.lacher)
            if r.recul_x_max >= r.lacher[0]:
                erreurs.append("lavage → couvercles → retourneur : recul_x_max au-delà de lacher")
            for quoi, z in (("lacher_face_z", r.lacher_face_z), ("bac_contact_z", r.bac_contact_z)):
                if not z_debut <= z <= z_fin:
                    erreurs.append(
                        f"lavage → couvercles → retourneur → {quoi} : hors de la course de "
                        "prehension_z"
                    )
        lave_bocal = lavage.lave_bocal
        if lave_bocal is not None:
            hors_portee("lave_bocal → centre", *lave_bocal.centre)
            for nom in OBJETS_LAVE_BOCAL:
                objet = prehension.objets.get(nom)
                if objet is None:
                    erreurs.append(f"lavage : il faut l'objet « {nom} » dans prehension → objets")
                    continue
                bas = lave_bocal.plateau_z + objet.dessous_m - lave_bocal.course_appui_m
                if bas < z_debut:
                    erreurs.append(
                        f"lavage → lave_bocal : appui d'un(e) {nom} sous la course de prehension_z"
                    )
        return erreurs

    def _verifier_remplissage(self) -> list[str]:
        """Les 5 axes du chariot sur une même carte ; chaque position, hauteur et file dans la
        course de son axe ; un réglage par format de la griffe ; mêmes y que le Mycélium."""
        remplissage = self.remplissage
        if remplissage is None:
            return []
        if self.griffe is None or self.poste_fut is None:
            return ["remplissage : il faut aussi les parties « griffe » et « poste_fut »"]
        erreurs = []
        for nom, unite in AXES_REMPLISSAGE.items():
            axe = self.axes.get(nom)
            if axe is None or axe.unite != unite or axe.carte is None:
                erreurs.append(
                    f"remplissage : il faut l'axe « {nom} » en « {unite} », avec sa carte"
                )
        if erreurs:
            return erreurs
        if len({self.axes[nom].carte for nom in AXES_REMPLISSAGE}) > 1:
            erreurs.append("remplissage : les 6 axes du chariot sont sur la même carte")
        if self.axes["barre_allee"].course != self.axes["barres"].course:
            erreurs.append(
                "remplissage : barre_allee a la même course que barres (elles bougent ensemble)"
            )
        for nom in DUREES_REMPLISSAGE:
            if nom not in self.durees:
                erreurs.append(f"remplissage : délai « {nom} » absent de durees")

        def dans(quoi: str, axe: str, valeur: float) -> None:
            debut, fin = self.axes[axe].course
            if not debut - 1e-9 <= valeur <= fin + 1e-9:
                erreurs.append(
                    f"remplissage → {quoi} : {valeur:g} hors de la course de {axe} "
                    f"({debut:g} à {fin:g})"
                )

        r = remplissage
        for nom in ("poste_y", "dosage_y", "ecarte_y", "pose_y"):
            dans(nom, "remplissage_y", getattr(r, nom))
        dans("couvercles → y", "remplissage_y", r.couvercles.y)
        dans("plateau_en_bas_z", "plateau_z", r.plateau_en_bas_z)
        dans("verrous → pousseur_plateau_max_z", "plateau_z", r.verrous.pousseur_plateau_max_z)
        dans("couvercles → plateau_z", "plateau_z", r.couvercles.plateau_z)
        dans("inspection → plateau_z", "plateau_z", r.inspection.plateau_z)
        dans("pousseur_rentre_m", "pousseur", r.pousseur_rentre_m)
        dans("barres → ouvertes_m", "barres", r.barres.ouvertes_m)
        approche = r.pose_seau.barres_approche_hw_m
        dans("pose_seau → barres_approche_hw_m", "barres", approche)
        joues = r.verrous.joues_barres[0]
        if approche >= joues:
            erreurs.append(
                f"remplissage → pose_seau → barres_approche_hw_m : sous les joues de l'élévateur "
                f"(moins de {joues:g})"
            )
        for nom, file in r.rangement.files.items():
            dans(f"rangement → files → {nom} → y", "remplissage_y", file.y)
            dans(f"rangement → files → {nom} → pousseur_m", "pousseur", file.pousseur_m)
        if r.barres.origine_hw_m < self.axes["barres"].course[1]:
            erreurs.append("remplissage → barres → origine_hw_m : au-delà de la course des barres")
        if r.barres.origine_allee_hw_m < self.axes["barre_allee"].course[1]:
            erreurs.append(
                "remplissage → barres → origine_allee_hw_m : au-delà de la course de barre_allee"
            )
        if self.axes["plateau_z"].course[0] > r.plateau_en_bas_z:
            erreurs.append("remplissage → plateau_en_bas_z : sous la course du plateau")
        for nom, seau in self.griffe.formats.items():
            reglage = r.formats.get(nom)
            if reglage is None or seau.hauteur is None:
                erreurs.append(
                    f"remplissage : il faut « formats → {nom} » et la hauteur du seau (griffe → "
                    "formats)"
                )
                continue
            dans(f"formats → {nom} → pose_plateau_z", "plateau_z", reglage.pose_plateau_z)
            dans(f"formats → {nom} → centrage_hw_m", "barres", reglage.centrage_hw_m)
            approche_z = min(
                r.verrous.joues_plateau_max_z,
                reglage.pose_plateau_z - r.pose_seau.plateau_sous_pose_m,
            )
            dans(f"formats → {nom} (plateau d'approche de la pose)", "plateau_z", approche_z)
            # Pose et prise double : les barres restent sous les joues de l'élévateur (elles
            # ne les traversent que plateau ≤ 0,48, avant la pose), et sous l'approche.
            levre = max(seau.rayon_haut + r.barres.jeu_rainure_m / 2, self.axes["barres"].course[0])
            centrage = reglage.centrage_hw_m + r.barres.jeu_centrage_m
            plus_large = max(centrage, levre) + r.barres.lacher_m
            if plus_large >= min(joues, approche):
                erreurs.append(
                    f"remplissage → formats → {nom} : pendant la prise double, les barres iraient "
                    f"à {plus_large:g} : il faut moins que l'approche ({approche:g}) et que les "
                    f"joues ({joues:g})"
                )
            plateau = min(seau.haut_z - seau.hauteur, self.axes["plateau_z"].course[1])
            dans(f"formats → {nom} (plateau au poste)", "plateau_z", plateau)
        for nom in r.formats:
            if nom not in self.griffe.formats:
                erreurs.append(f"remplissage → formats → {nom} : absent de griffe → formats")
        mycelium = self.mycelium
        if mycelium is not None:
            if abs(mycelium.chariot.y_dosage - r.dosage_y) > 1e-9:
                erreurs.append("remplissage → dosage_y : le même que mycelium → chariot → y_dosage")
            if abs(mycelium.chariot.y_ecarte_min - r.ecarte_y) > 1e-9:
                erreurs.append(
                    "remplissage → ecarte_y : le même que mycelium → chariot → y_ecarte_min"
                )
        lavage = self.lavage
        if lavage is not None and lavage.couvercles is not None:
            retourneur = lavage.couvercles.retourneur
            dans(
                "lavage → couvercles → retourneur → barres_fermees_m",
                "barres",
                retourneur.barres_fermees_m,
            )
            dans(
                "lavage → couvercles → retourneur → barres_ouvertes_m",
                "barres",
                retourneur.barres_ouvertes_m,
            )
        return erreurs

    def _verifier_stockage(self) -> list[str]:
        """Les places du Stockage, calculées par le Pi, tiennent : seaux par pile, piles qui ne se
        chevauchent pas, tiroir qui ne dépasse pas la butée, coin d'inspection, courses."""
        stockage = self.stockage
        if stockage is None:
            return []
        if self.griffe is None or self.prehension is None or self.remplissage is None:
            return [
                "stockage : il faut aussi les parties « griffe », « prehension » et « remplissage »"
            ]
        # Les calculs des places sont ceux du programme (une seule façon de les faire).
        from vidange.stockage import places

        erreurs: list[str] = []
        formats = self.griffe.formats
        for nom, seau in formats.items():
            if seau.hauteur is None or seau.pas_pile_m is None:
                erreurs.append(
                    f"stockage : il faut la hauteur et pas_pile_m du format « {nom} » "
                    "(griffe → formats)"
                )
        if erreurs:
            return erreurs
        for nom in formats:
            if places.seaux_par_pile(self, nom) < 1:
                erreurs.append(f"stockage → piles : aucun seau « {nom} » ne tient dans une pile")
        # Les piles ne se chevauchent pas (rayon du haut du plus grand seau, + celui des boîtes).
        rayon = max(seau.rayon_haut for seau in formats.values())
        cercles = {nom: (point, rayon) for nom, point in stockage.piles.places.items()}
        cercles["couvercles"] = (stockage.piles.couvercles, rayon)
        for nom, point in stockage.boites.places.items():
            cercles[f"boîte {nom}"] = (point, stockage.boites.diametre_m / 2)
        noms = list(cercles)
        for i, nom_a in enumerate(noms):
            for nom_b in noms[i + 1 :]:
                (pa, ra), (pb, rb) = cercles[nom_a], cercles[nom_b]
                if math.dist(pa, pb) < ra + rb - 1e-9:
                    erreurs.append(
                        f"stockage : les places « {nom_a} » et « {nom_b} » se chevauchent"
                    )
        rangees = stockage.piles.ordre_rangees_y
        for nom, (_, y) in [
            *stockage.piles.places.items(),
            ("fin_de_lot", (0.0, stockage.piles.fin_de_lot.y)),
        ]:
            if not any(abs(y - rangee) < 1e-6 for rangee in rangees):
                erreurs.append(f"stockage → piles → {nom} : y {y:g} absent de ordre_rangees_y")
        # Places atteintes par la préhension (pont, chariot) et contact d'un seul seau.
        pont = self.axes["pont_x"].course
        chariot = self.axes["chariot_y"].course
        tete_z = self.axes["prehension_z"].course
        for format in formats:
            points = places.places_piles(self, format)
            for nom, (x, y) in points.items():
                x_pont = x - self.prehension.decalage_mat_x
                if not (pont[0] <= x_pont <= pont[1] and chariot[0] <= y <= chariot[1]):
                    erreurs.append(
                        f"stockage → {nom} ({format}) : ({x:g} ; {y:g}) hors de portée de la "
                        "préhension (courses de pont_x et chariot_y)"
                    )
            contact = places.contact_prise(self, format, 1)
            if not tete_z[0] <= contact <= tete_z[1]:
                erreurs.append(
                    f"stockage : prise d'un seau « {format} » seul à {contact:g}, hors de la "
                    "course de prehension_z"
                )
            if len(places.places_fin_de_lot(self, format)) < 1:
                erreurs.append(f"stockage → fin_de_lot : aucune place pour « {format} »")
        # Tiroir : ses files sont celles du Remplissage ; le premier seau ne dépasse pas la butée.
        tiroir = stockage.tiroir
        files = self.remplissage.rangement.files
        for nom in tiroir.files:
            if nom not in files:
                erreurs.append(
                    f"stockage → tiroir → files : « {nom} » absente de remplissage → "
                    "rangement → files"
                )
        longueur = tiroir.butee_x - tiroir.entree_x
        for format in formats:
            par_file = tiroir.places.get(format)
            if par_file is None:
                erreurs.append(f"stockage → tiroir → places : il faut le format « {format} »")
                continue
            if set(par_file) != set(tiroir.files):
                erreurs.append(
                    f"stockage → tiroir → places → {format} : il faut une valeur pour chaque "
                    "file de tiroir → files, et seulement elles"
                )
            if format in tiroir.quinconce:
                continue
            for nom, nombre in par_file.items():
                if nombre * tiroir.avance_par_seau_m > longueur + 1e-9:
                    erreurs.append(
                        f"stockage → tiroir → places → {format} → {nom} : {nombre} seaux × "
                        f"{tiroir.avance_par_seau_m:g} m dépassent la butée (file de "
                        f"{longueur:g} m)"
                    )
        for nom in [*tiroir.places, *tiroir.quinconce, *stockage.bande_haut.places]:
            if nom not in formats:
                erreurs.append(f"stockage : format « {nom} » absent de griffe → formats")
        # Coin d'inspection : des places du quinconce, chacune une seule fois.
        quinconce = places.places_bocaux(self)
        inspection = stockage.bocaux.inspection
        vues: set[tuple[int, int]] = set()
        coin = (("suspects", inspection.suspects), ("separation", inspection.separation))
        for quoi, liste in coin:
            for j, i in liste:
                if places.nom_bocal(j, i) not in quinconce:
                    erreurs.append(
                        f"stockage → bocaux → inspection → {quoi} : pas de place [{j}, {i}]"
                    )
                elif (j, i) in vues:
                    erreurs.append(
                        f"stockage → bocaux → inspection : place [{j}, {i}] écrite deux fois"
                    )
                vues.add((j, i))
        if places.capacite_boite(self) < 1:
            erreurs.append("stockage → boites : pas une capsule entre le fond et le dessus")
        return erreurs

    def _se_chevauchent(self, nom_a: str, nom_b: str) -> bool:
        """Deux zones se chevauchent si elles se recouvrent sur tous les axes à la fois."""
        zone_a, zone_b = self.zones[nom_a], self.zones[nom_b]
        for axe in zone_a.keys() | zone_b.keys():
            debut_a, fin_a = zone_a.get(axe, self.axes[axe].course)
            debut_b, fin_b = zone_b.get(axe, self.axes[axe].course)
            # Deux zones qui se touchent juste au bord ne se chevauchent pas.
            if max(debut_a, debut_b) >= min(fin_a, fin_b):
                return False
        return True


# -------------------------------------------------------------- programme.yaml


class Journal(Modele):
    niveau: Literal["detail", "info", "avertissement", "erreur"]
    taille_fichier_mo: float = Field(gt=0)
    nombre_fichiers: int = Field(ge=1)


class ReglagesChef(Modele):
    """Réglages du chef d'orchestre."""

    # Tous les combien il regarde les conditions des étapes (s).
    periode_s: float = Field(gt=0, le=1)
    # Une alarme dans un module met toute la machine en pause, ou seulement ce module.
    alarme_pause_tout: bool


class ReglagesRegistre(Modele):
    """Réglages du registre (base SQLite) et de sa copie de secours quotidienne."""

    # La copie du jour se fait à partir de cette heure (heure du Pi, de 0 à 23).
    heure_sauvegarde: int = Field(ge=0, le=23)
    # Nombre de copies quotidiennes gardées ; les plus vieilles sont effacées.
    copies_gardees: int = Field(ge=1)
    # Tous les combien (minutes) on regarde s'il faut faire la copie du jour.
    periode_verification_min: float = Field(gt=0, le=60)


class ReglagesSante(Modele):
    """Santé de l'informatique du Pi (fonction 45) : seuils d'alerte."""

    # Tous les combien (minutes) on mesure et on note dans le registre.
    periode_min: float = Field(gt=0, le=60)
    # Le Pi 5 ralentit vers 80-85 °C : on prévient avant.
    temperature_pi_attention_c: float = Field(gt=0)
    # Place libre sur le SSD (dossier des données), en Go : attention, puis démarrage refusé.
    disque_libre_attention_go: float = Field(gt=0)
    disque_libre_minimum_go: float = Field(gt=0)
    # Mémoire vive disponible, en Mo.
    memoire_libre_attention_mo: float = Field(gt=0)
    # La dernière copie de secours du registre ne doit pas être plus vieille que (heures).
    sauvegarde_age_max_h: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier_seuils(self) -> "ReglagesSante":
        if self.disque_libre_minimum_go >= self.disque_libre_attention_go:
            raise ValueError(
                "disque_libre_minimum_go doit être plus petit que disque_libre_attention_go"
            )
        return self


class ReglagesChienDeGarde(Modele):
    """Chien de garde (fonction 14) : le Pi surveille les cartes, et se fait surveiller."""

    # Tous les combien (s) il regarde les cartes et le chef, et dit « je vis » à systemd.
    periode_s: float = Field(gt=0, le=10)
    # Le chef qui n'a pas fait de tour depuis ce temps (s) est déclaré figé.
    chef_fige_s: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier_delais(self) -> "ReglagesChienDeGarde":
        if self.chef_fige_s < 2 * self.periode_s:
            raise ValueError(
                f"chef_fige_s ({self.chef_fige_s:g} s) doit valoir au moins 2 fois "
                f"periode_s ({self.periode_s:g} s)"
            )
        return self


class ReglagesOnduleur(Modele):
    """Arrêt propre sur onduleur (fonction 4)."""

    # Tous les combien (s) on regarde le signal de l'onduleur.
    periode_s: float = Field(gt=0, le=10)
    # Courant coupé depuis ce temps (s) : machine en pause, état noté, puis le Pi s'éteint.
    delai_avant_arret_s: float = Field(ge=0)
    # Commande qui éteint le Pi (le compte « vidange » doit avoir le droit de la lancer).
    commande_arret: list[Annotated[str, StringConstraints(min_length=1)]] = Field(min_length=1)


class ReglagesBilan(Modele):
    """Bilan écrit à chaque alarme (fonction 17)."""

    # Les dernières lignes du journal recopiées dans le bilan.
    lignes_journal: int = Field(ge=0, le=1000)


class ReglagesFiabilite(Modele):
    sante: ReglagesSante
    chien_de_garde: ReglagesChienDeGarde
    onduleur: ReglagesOnduleur
    bilan: ReglagesBilan


class ReglagesApi(Modele):
    """API du Pi et page web locale (tâche 8)."""

    # Adresse où l'API écoute : « 0.0.0.0 » = toutes les liaisons réseau du Pi (local et Tailscale).
    adresse: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    # Seuls ces réseaux peuvent joindre l'API et la page : les autres sont refusés d'office.
    reseaux_autorises: list[IPvAnyNetwork] = Field(min_length=1)
    # La page web redemande l'état tous les (s).
    rafraichir_s: float = Field(gt=0, le=60)
    # Nombre de lignes rendues au plus d'un coup (historique, alarmes, photos).
    lignes_max: int = Field(ge=1, le=10000)


# Une couleur « #RRGGBB » (rouge, vert, bleu en hexadécimal), comme dans un logiciel de dessin.
Couleur = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]


class FondTexte(Modele):
    fond: Couleur
    texte: Couleur


class CouleursEcran(Modele):
    """Code couleur de l'écran (fonction 47)."""

    marche: FondTexte
    go: FondTexte
    pause: FondTexte
    alarme: FondTexte
    repos: FondTexte
    mode: FondTexte
    # Pilotage à distance en cours (tâche 12).
    distance: FondTexte
    bouton: FondTexte
    inactif: FondTexte


class ReglagesEcran(Modele):
    """Écran Nextion de la porte de l'armoire (tâche 9)."""

    vitesse_bauds: int = Field(gt=0)
    # Le Pi lit les boutons et met l'écran à jour tous les (s).
    periode_s: float = Field(gt=0, le=2)
    # Il demande à l'écran s'il est là tous les (s) ; muet : sans réponse depuis « silence_s ».
    presence_s: float = Field(gt=0)
    silence_s: float = Field(gt=0)
    # Port série impossible à ouvrir : nouvel essai tous les (s).
    reconnexion_s: float = Field(gt=0)
    # Retour à la page d'état sans appui depuis ce temps (s) ; une question « Oui / Non »
    # sans réponse est abandonnée plus vite.
    retour_accueil_s: float = Field(gt=0)
    confirmation_s: float = Field(gt=0)
    # Durée d'affichage d'un message (« Aucun Go attendu »...).
    message_s: float = Field(gt=0)
    couleurs: CouleursEcran

    @model_validator(mode="after")
    def _verifier_delais(self) -> "ReglagesEcran":
        if self.silence_s < 2 * self.presence_s:
            raise ValueError(
                f"silence_s ({self.silence_s:g} s) doit valoir au moins 2 fois "
                f"presence_s ({self.presence_s:g} s)"
            )
        return self


class EnvoiCulture(Modele):
    """Envoi des cycles au logiciel de culture (Django), format dans docs/django.md."""

    # Adresse de l'app « machine » qui reçoit les cycles ; vide : pas encore prête, les cycles
    # attendent dans la file (rien n'est perdu).
    adresse: str = ""
    # Nom de cette machine, envoyé avec chaque cycle.
    machine: str = Field(min_length=1)
    # Le logiciel de culture compte en heure locale sans fuseau (USE_TZ = False) : les heures
    # lui sont envoyées dans ce fuseau.
    fuseau_horaire: str = Field(min_length=1)
    # Sans réponse après ce temps (s), l'essai est raté. Court : l'arrêt du programme l'attend.
    delai_reponse_s: float = Field(gt=0, le=10)

    @model_validator(mode="after")
    def _verifier(self) -> "EnvoiCulture":
        if self.adresse and not self.adresse.startswith(("http://", "https://")):
            raise ValueError(f"adresse « {self.adresse} » : doit commencer par http:// ou https://")
        try:
            ZoneInfo(self.fuseau_horaire)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(
                f"fuseau horaire inconnu « {self.fuseau_horaire} » (exemple : America/Guadeloupe)"
            ) from None
        return self


class EnvoiSecours(Modele):
    """Copie de secours vers la maison (par Tailscale)."""

    # Commande qui copie un fichier ou un dossier vers la maison ; « {chemin} » y est remplacé
    # par ce qu'il faut copier. Vide : pas encore prête, les copies attendent dans la file.
    commande: list[Annotated[str, StringConstraints(min_length=1)]] = Field(default_factory=list)
    # La commande est arrêtée si elle dure plus que ça (s).
    duree_max_s: float = Field(gt=0)
    # Envoyer aussi, chaque jour, le dossier des photos (seules les nouvelles partent avec rsync).
    photos: bool

    @model_validator(mode="after")
    def _verifier(self) -> "EnvoiSecours":
        if self.commande and not any("{chemin}" in morceau for morceau in self.commande):
            raise ValueError("commande : il manque « {chemin} » (ce qu'il faut copier)")
        return self


class ReglagesEnvois(Modele):
    """File d'envoi vers l'extérieur (tâche 10). La machine n'attend jamais le réseau."""

    # La file est regardée tous les (s).
    periode_s: float = Field(gt=0, le=3600)
    # Après un essai raté vers une destination, on attend ce temps (s), doublé à chaque nouvel
    # échec, sans dépasser « attente_max_min ».
    attente_premier_echec_s: float = Field(gt=0)
    attente_max_min: float = Field(gt=0)
    # Un envoi qui attend depuis plus que ça (h) est signalé dans la check-list.
    signaler_apres_h: float = Field(gt=0)
    # Les envois réussis restent visibles ce nombre de jours, puis sont effacés de la file.
    garder_envoyes_jours: int = Field(ge=1)
    culture: EnvoiCulture
    secours: EnvoiSecours

    @model_validator(mode="after")
    def _verifier_attentes(self) -> "ReglagesEnvois":
        if self.attente_max_min * 60 < self.attente_premier_echec_s:
            raise ValueError("attente_max_min doit être plus long que attente_premier_echec_s")
        return self


class Camera(Modele):
    """Une caméra : la commande qui écrit sa vidéo (images JPEG à la suite, « MJPEG »)."""

    description: str = ""
    # La commande et ses options (taille d'image, images par seconde, appareil...). Le Pi la
    # relance seule si elle s'arrête.
    commande: list[Annotated[str, StringConstraints(min_length=1)]] = Field(min_length=1)


class ReglagesCameras(Modele):
    """Caméras (tâche 12) : vidéo en direct sur la page web, clips des alarmes."""

    # Vrai tant que les commandes sont des exemples : le programme le signale.
    exemple: bool = False
    # Mémoire tournante de chaque caméra (s) : gardée en clip à chaque alarme.
    memoire_s: float = Field(gt=0)
    # Une caméra sans nouvelle image depuis ce temps (s) est déclarée figée.
    figee_s: float = Field(gt=0)
    # Commande arrêtée ou figée : relancée après ce temps (s).
    relance_s: float = Field(gt=0)
    # La page web demande une nouvelle image ce nombre de fois par seconde.
    page_images_par_s: float = Field(gt=0, le=30)
    # Les clips plus vieux que ce nombre de jours sont effacés.
    clips_gardes_jours: int = Field(ge=1)
    liste: dict[Nom, Camera] = Field(default_factory=dict)


class ReglagesDistance(Modele):
    """Pilotage manuel à distance (tâche 12) : ses garde-fous logiciels."""

    # Vitesse des axes pilotés à distance, au plus (m/s).
    vitesse_max_m_s: float = Field(gt=0)
    # Bouton tenu : la page redit « je tiens » tous les (s).
    battement_s: float = Field(gt=0)
    # « Homme mort » : sans « je tiens » depuis ce temps (s), le mouvement s'arrête.
    homme_mort_s: float = Field(gt=0)
    # Le Pi regarde le pilotage tous les (s).
    periode_s: float = Field(gt=0, le=1)
    # La carte n'a jamais plus que ce temps (s) de mouvement d'avance : si le Pi se fige,
    # l'axe s'arrête de lui-même après au plus « vitesse_max × avance_s ».
    avance_s: float = Field(gt=0)
    # L'image vue sur la page est plus vieille que ça (s) : vidéo figée, arrêt.
    video_figee_s: float = Field(gt=0)
    # Voyant et buzzer sur place : allumés ce temps (s) avant le premier mouvement, et gardés
    # ce temps (s) après le dernier.
    voyant_avant_s: float = Field(ge=0)
    voyant_apres_s: float = Field(ge=0)
    # Mode à distance sans aucun mouvement depuis ce temps (min) : il se termine seul.
    inactivite_max_min: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier_delais(self) -> "ReglagesDistance":
        erreurs = []
        if self.homme_mort_s < 2 * self.battement_s:
            erreurs.append(
                f"homme_mort_s ({self.homme_mort_s:g} s) doit valoir au moins 2 fois "
                f"battement_s ({self.battement_s:g} s)"
            )
        for nom in ("homme_mort_s", "avance_s"):
            if getattr(self, nom) < 2 * self.periode_s:
                erreurs.append(
                    f"{nom} ({getattr(self, nom):g} s) doit valoir au moins 2 fois "
                    f"periode_s ({self.periode_s:g} s)"
                )
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class ReglagesMajCartes(Modele):
    """Mises à jour des cartes ESP32 par leur câble USB (esptool, et la console de FluidNC)."""

    # Vitesse de la liaison USB pendant l'écriture (esptool).
    vitesse_bauds: int = Field(gt=0)
    # Adresse du programme dans la mémoire de la carte.
    adresse_programme: int = Field(ge=0)
    # Nom du fichier de réglages de FluidNC dans la carte.
    fichier_reglages: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]+$")]
    # Copies complètes de la mémoire gardées par carte (une avant chaque changement).
    copies_gardees: int = Field(ge=1)
    # Fichiers de programme envoyés par la page web, gardés sur le Pi.
    programmes_gardes: int = Field(ge=1)
    taille_max_mo: float = Field(gt=0)
    # Durée maximale d'une lecture ou d'une écriture de toute la mémoire (esptool).
    duree_max_esptool_s: float = Field(gt=0)
    # Réponse d'une ligne de la console de FluidNC, au plus.
    delai_commande_s: float = Field(gt=0)
    # Après un changement, la carte doit redémarrer et répondre dans ce délai.
    delai_reponse_s: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier_delais(self) -> "ReglagesMajCartes":
        if self.delai_reponse_s < self.delai_commande_s:
            raise ValueError(
                f"delai_reponse_s ({self.delai_reponse_s:g} s) doit valoir au moins "
                f"delai_commande_s ({self.delai_commande_s:g} s)"
            )
        return self


class ReglagesMajPi(Modele):
    """Mise à jour du programme du Pi depuis GitHub (versions acceptées par Karulium)."""

    depot: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    branche: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    # Durée maximale de chaque commande (téléchargement, installation, vérification).
    duree_max_s: float = Field(gt=0)


class ReglagesMisesAJour(Modele):
    """Mises à jour (tâche 13), seulement machine à l'arrêt."""

    cartes: ReglagesMajCartes
    pi: ReglagesMajPi


class Programme(Modele):
    """programme.yaml : réglages du programme lui-même (pas de la machine)."""

    journal: Journal
    chef: ReglagesChef
    registre: ReglagesRegistre
    fiabilite: ReglagesFiabilite
    api: ReglagesApi
    ecran: ReglagesEcran
    envois: ReglagesEnvois
    cameras: ReglagesCameras
    distance: ReglagesDistance
    mises_a_jour: ReglagesMisesAJour

    @model_validator(mode="after")
    def _verifier_video(self) -> "Programme":
        # La page doit recevoir au moins 2 images avant que la vidéo soit dite figée.
        if self.distance.video_figee_s * self.cameras.page_images_par_s < 2:
            raise ValueError(
                f"distance → video_figee_s ({self.distance.video_figee_s:g} s) doit laisser "
                f"passer au moins 2 images de la page (cameras → page_images_par_s : "
                f"{self.cameras.page_images_par_s:g})"
            )
        return self


# ---------------------------------------------------------------- fluidnc.yaml


class LiaisonFluidnc(Modele):
    """Réglages communs aux liaisons série avec les cartes FluidNC."""

    vitesse_bauds: int = Field(gt=0)
    # Place dans le tampon de réception de la carte (octets) : le contrôle de flux
    # n'envoie jamais plus de lignes sans réponse que ce qui y tient.
    taille_tampon: int = Field(ge=16)
    # Tous les combien on demande l'état (« ? »).
    periode_etat_s: float = Field(gt=0)
    # Sans rien recevoir pendant ce temps, la carte est déclarée muette et la liaison reprise.
    delai_silence_s: float = Field(gt=0)
    # Attente entre deux essais de connexion.
    delai_reconnexion_s: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier_delais(self) -> "LiaisonFluidnc":
        if self.delai_silence_s < 3 * self.periode_etat_s:
            raise ValueError(
                f"delai_silence_s ({self.delai_silence_s:g} s) doit valoir au moins "
                f"3 fois periode_etat_s ({self.periode_etat_s:g} s)"
            )
        return self


class CarteFluidnc(Modele):
    description: str = ""
    # Numéro de série de l'USB de la carte : c'est lui qui la reconnaît, jamais l'ordre des ports.
    numero_serie_usb: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    # Entrées lues dans le rapport d'état de la carte (« Pn: ») : nom du signal
    # (docs/entrees-sorties.yaml) → sa lettre dans FluidNC (fin de course d'un axe, macro0 = 0...).
    entrees: dict[Nom, Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]$")]] = Field(
        default_factory=dict
    )
    # Sorties tout-ou-rien de la carte (« user_outputs ») : nom du signal → numéro de la sortie
    # (M64 P<n> l'allume, M65 P<n> l'éteint).
    sorties: dict[Nom, Annotated[int, Field(ge=0, le=7)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _verifier_signaux(self) -> "CarteFluidnc":
        erreurs = []
        for quoi, valeurs in (("entrees", self.entrees), ("sorties", self.sorties)):
            vus: dict[object, str] = {}
            for nom, valeur in valeurs.items():
                autre = vus.setdefault(valeur, nom)
                if autre != nom:
                    erreurs.append(f"{quoi} : « {autre} » et « {nom} » ont la même ({valeur})")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class Fluidnc(Modele):
    """fluidnc.yaml : les cartes FluidNC et leur liaison avec le Pi."""

    exemple: bool = False
    liaison: LiaisonFluidnc
    cartes: dict[Nom, CarteFluidnc] = Field(min_length=1)

    @model_validator(mode="after")
    def _verifier_numeros(self) -> "Fluidnc":
        deja_vus: dict[str, str] = {}
        erreurs = []
        for nom, carte in self.cartes.items():
            autre = deja_vus.setdefault(carte.numero_serie_usb, nom)
            if autre != nom:
                erreurs.append(
                    f"les cartes « {autre} » et « {nom} » ont le même numéro de série USB "
                    f"« {carte.numero_serie_usb} »"
                )
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


# ------------------------------------------------------------- simulateur.yaml


class MouvementSimule(Modele):
    """Comment un axe bouge dans le simulateur : vitesse (m/s) et accélération (m/s²)."""

    vitesse: float = Field(gt=0)
    acceleration: float = Field(gt=0)


class EvenementSimule(Modele):
    """Un capteur qui change pendant la simulation (Karulium ferme un panneau...),
    ou une pesée qui change (poids posé, prise débranchée)."""

    # Compté depuis le début de cette étape (« module.etape ») ; sans « apres » : depuis le
    # début de la simulation.
    apres: (
        Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")] | None
    ) = None
    attente_s: float = Field(ge=0)
    # Entrée tout-ou-rien de docs/entrees-sorties.yaml, actionnée ou non...
    capteur: Nom | None = None
    actionne: bool | None = None
    # ... ou pesée (signal de type pesee) : poids lu en kg, ou prise débranchée.
    pesee: Nom | None = None
    kg: float | None = None
    debranchee: bool = False

    @model_validator(mode="after")
    def _une_seule_chose(self) -> "EvenementSimule":
        capteur = self.capteur is not None and self.actionne is not None
        pesee = self.pesee is not None and (self.kg is not None) != self.debranchee
        reste_capteur = self.capteur is not None or self.actionne is not None
        reste_pesee = self.pesee is not None or self.kg is not None or self.debranchee
        if not ((capteur and not reste_pesee) or (pesee and not reste_capteur)):
            raise ValueError(
                "écrire « capteur » et « actionne », ou « pesee » avec « kg » ou "
                "« debranchee: true » (une seule chose par événement)"
            )
        return self


class GriffeSimulee(Modele):
    """Le substrat du fût imaginaire, pour la griffe du simulateur."""

    # Densité vraie du substrat dans le fût (kg/L) : la griffe doit l'apprendre.
    densite_kg_l: float = Field(gt=0)
    # Prises près de la paroi (mât à au moins paroi_rayon_m de l'axe) et au fond (bas du godet à
    # moins de fond_hauteur_m du fond) : poids × facteur.
    paroi_rayon_m: float = Field(gt=0)
    facteur_paroi: float = Field(gt=0, le=1)
    fond_hauteur_m: float = Field(ge=0)
    facteur_fond: float = Field(gt=0, le=1)
    # Godet entrouvert puis refermé : part du contenu qui retombe.
    entrouvrir_rendu: float = Field(ge=0, le=1)
    # Charge pendue godet vide (N).
    charge_vide_n: float = Field(gt=0)


class SeauSimule(Modele):
    """Un seau à doser dans le simulateur (le QR vient de la vision, tâche 22)."""

    seau: str
    format: Nom
    variete: str


class MyceliumSimule(Modele):
    """Le bocal et le chariot imaginaires du Mycélium."""

    # Grains qui tombent pendant que la manivelle tourne, bocal tête en bas (kg/s).
    debit_kg_s: float = Field(gt=0)
    # Mycélium dans un bocal neuf (kg).
    bocal_kg: float = Field(gt=0)
    # Durée d'un demi-tour du porte-bocal, d'un trajet du chariot de remplissage (s).
    demi_tour_s: float = Field(ge=0)
    chariot_s: float = Field(ge=0)
    # Les seaux à doser, dans l'ordre (chaque couche de leur format).
    seaux: list[SeauSimule] = Field(min_length=1)


class PlaceSimulee(Modele):
    """Où un objet attend, pour le simulateur : axe de la tête, et cote de sa face au contact."""

    x: float
    y: float
    contact_z: float


class PrehensionSimulee(Modele):
    """Les objets imaginaires de la préhension (scénario « prehension »)."""

    # Vide atteint quand la ventouse est sur un objet (kPa).
    vide_kpa: float = Field(lt=0)
    # Où prendre et où poser chaque objet du scénario ; où visser la capsule.
    seau: PlaceSimulee
    seau_pose: PlaceSimulee
    couvercle: PlaceSimulee
    couvercle_pose: PlaceSimulee
    bocal: PlaceSimulee
    capsule: PlaceSimulee
    vissage: PlaceSimulee
    # Durée d'un geste des mors du porte-bocal (s).
    mors_s: float = Field(ge=0)


class SeauLavageSimule(Modele):
    """Un seau retourné (ou un couvercle) à laver : son format, où la tête le prend et le
    repose."""

    format: Nom
    x: float
    y: float
    contact_z: float


class ObjetLaveBocalSimule(Modele):
    """Un bocal vide (retourné) ou une capsule à laver : où la tête le prend et le repose."""

    sorte: Literal["bocal_vide", "capsule"]
    x: float
    y: float
    contact_z: float


class LavageSimule(Modele):
    """L'eau imaginaire du fût de lavage, et les seaux à laver (scénario « lavage »)."""

    # Eau au-dessus de laquelle le flotteur est « haut » (L) ; débits (L/s) de l'eau du réseau,
    # de la pompe (vers la bonde), de l'électrovanne de rinçage.
    niveau_flotteur_l: float = Field(gt=0)
    debit_eau_l_s: float = Field(ge=0)
    debit_pompe_l_s: float = Field(gt=0)
    debit_rincage_l_s: float = Field(ge=0)
    seaux: list[SeauLavageSimule] = Field(min_length=1)
    # Scénario « lavage_couvercles » : les couvercles à laver (format, où la tête les prend et
    # les repose), et le temps que mettent les barres du retourneur à bouger (s).
    couvercles: list[SeauLavageSimule] = Field(default_factory=list)
    barres_s: float = Field(default=2, ge=0)
    # Scénario « lavage_bocaux » : les bocaux vides et les capsules à laver au lave-bocal.
    bocaux: list[ObjetLaveBocalSimule] = Field(default_factory=list)


class SeauRemplissageSimule(Modele):
    """Un seau vide à remplir dans le simulateur : QR, format, variété, file de rangement ; deux
    seaux emboîtés posés ensemble (prise double) ; angle des oreilles de l'anse vu par la
    caméra (°)."""

    seau: str
    format: Nom
    variete: str
    # Sans file : c'est le Stockage qui la choisit (scénario « stockage »).
    file: Nom | None = None
    prise_double: bool = False
    anse_deg: float = 0.0


class RemplissageSimule(Modele):
    """Les seaux imaginaires du Remplissage (scénario « remplissage »)."""

    # Où la tête prend les seaux vides (Stockage, pas encore écrit), où elle rend le seau du
    # dessus après une prise double.
    stockage: PlaceSimulee
    rendu: PlaceSimulee
    # Durée d'un versement de la griffe (le seau tourne), substrat versé par couche (kg).
    versement_s: float = Field(gt=0)
    # Deux seaux emboîtés : le fond de celui du dessous dépasse de tant sous celui du dessus.
    double_plus_bas_m: float = Field(default=0.03, ge=0)
    seaux: list[SeauRemplissageSimule] = Field(min_length=1)


class PileSimulee(Modele):
    format: Nom
    nombre: int = Field(ge=0)


class StockageSimule(Modele):
    """Le stockage imaginaire (scénario « stockage ») : piles de seaux vides chargées au départ
    (place → format et nombre), et les seaux à remplir (sans file : le Stockage la choisit)."""

    piles: dict[Nom, PileSimulee] = Field(min_length=1)
    seaux: list[SeauRemplissageSimule] = Field(min_length=1)


class ScenarioSimule(Modele):
    """Un scénario : capteurs actionnés au départ et événements, à la place de ceux du haut."""

    capteurs_actionnes: list[Nom] = Field(default_factory=list)
    evenements: list[EvenementSimule] = Field(default_factory=list)


class ReglagesSimulateur(Modele):
    """simulateur.yaml : la machine imaginaire du simulateur de cycle (jumeau, version 0)."""

    exemple: bool = False
    # La simulation saute d'un événement au suivant, sans jamais avancer de plus que ce pas (s).
    pas_max_s: float = Field(gt=0, le=60)
    # Au-delà de ce temps simulé (s), le cycle est déclaré bloqué.
    duree_max_s: float = Field(gt=0)
    # Temps que met Karulium à donner le Go quand une étape le demande (s).
    delai_go_s: float = Field(ge=0)
    # Axes de machine.yaml qui bougent dans la simulation.
    axes: dict[Nom, MouvementSimule] = Field(default_factory=dict)
    # Position de machine.yaml où sont les axes au départ ; les autres sont au début de leur course.
    depart: Nom | None = None
    # Capteurs actionnés au départ (les autres ne le sont pas).
    capteurs_actionnes: list[Nom] = Field(default_factory=list)
    evenements: list[EvenementSimule] = Field(default_factory=list)
    # Scénarios nommés (« echange_fut »...), choisis au lancement du simulateur.
    scenarios: dict[Nom, ScenarioSimule] = Field(default_factory=dict)
    # Le substrat du fût imaginaire (simulation de la griffe).
    griffe: GriffeSimulee | None = None
    # Le bocal, le chariot et les seaux imaginaires (simulation du mycélium).
    mycelium: MyceliumSimule | None = None
    # Les objets imaginaires de la préhension.
    prehension: PrehensionSimulee | None = None
    # L'eau et les seaux imaginaires du lavage.
    lavage: LavageSimule | None = None
    # Les seaux imaginaires du remplissage.
    remplissage: RemplissageSimule | None = None
    # Le stockage imaginaire (piles de seaux vides, seaux rangés dans le tiroir).
    stockage: StockageSimule | None = None


# ---------------------------------------------------------- accelerometre.yaml

# Broches GPIO du RP2040.
BrocheRp2040 = Annotated[int, Field(ge=0, le=29)]


class BrochesAccelerometre(Modele):
    i2c_sda: BrocheRp2040
    i2c_scl: BrocheRp2040
    sortie_ok: BrocheRp2040
    fil_serie: BrocheRp2040
    voyant: BrocheRp2040 | None = None

    @property
    def bloc_i2c(self) -> int:
        """Bloc I2C du RP2040 (0 ou 1) qui sort sur ces broches."""
        return (self.i2c_sda // 2) % 2

    @model_validator(mode="after")
    def _verifier_broches(self) -> "BrochesAccelerometre":
        erreurs = []
        # Sur le RP2040, la broche n sort le bloc I2C (n // 2) % 2, en SDA si n est pair.
        if self.i2c_sda % 2 != 0:
            erreurs.append(f"i2c_sda ({self.i2c_sda}) doit être une broche paire")
        if self.i2c_scl % 2 != 1:
            erreurs.append(f"i2c_scl ({self.i2c_scl}) doit être une broche impaire")
        if not erreurs and (self.i2c_sda // 2) % 2 != (self.i2c_scl // 2) % 2:
            erreurs.append(
                f"i2c_sda ({self.i2c_sda}) et i2c_scl ({self.i2c_scl}) ne sont pas du même "
                "bloc I2C (I2C0 : SDA 0, 4, 8... SCL 1, 5, 9... ; I2C1 : SDA 2, 6, 10... "
                "SCL 3, 7, 11...)"
            )
        deja_vues: dict[int, str] = {}
        for nom, broche in self.model_dump().items():
            if broche is None:
                continue
            autre = deja_vues.setdefault(broche, nom)
            if autre != nom:
                erreurs.append(f"la broche {broche} est prise deux fois ({autre} et {nom})")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class CapteurAccelerometre(Modele):
    adresse_i2c: Literal[0x18, 0x19]
    frequence_i2c_hz: Literal[100000, 400000]
    pleine_echelle_g: Literal[2, 4, 8, 16]
    mesures_par_seconde: Literal[1, 10, 25, 50, 100, 200, 400, 1344]
    axes: list[Literal["x", "y", "z"]] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def _verifier_axes(self) -> "CapteurAccelerometre":
        if len(set(self.axes)) != len(self.axes):
            raise ValueError("axes : un axe est écrit deux fois")
        return self


class ChocAccelerometre(Modele):
    seuil_g: float = Field(gt=0)
    duree_min_ms: int = Field(ge=0, le=1000)
    maintien_ms: int = Field(ge=10, le=60000)
    constante_fond_ms: int = Field(ge=100, le=600000)


class PanneAccelerometre(Modele):
    sans_mesure_ms: int = Field(gt=0, le=10000)
    erreurs_lecture_max: int = Field(ge=1, le=1000)
    figee_ms: int = Field(gt=0, le=600000)
    reessai_ms: int = Field(ge=100, le=600000)
    # Le chien de garde du RP2040 ne compte pas plus loin que 8,3 s.
    chien_de_garde_ms: int = Field(ge=10, le=8000)


class ConsoleAccelerometre(Modele):
    periode_affichage_ms: int = Field(ge=100, le=600000)


# Plus longue trame de la liaison (accelerometre/src/liaison.h, LIAISON_LIGNE_MAX).
LIGNE_MAX_LIAISON = 256


class LiaisonAccelerometre(Modele):
    """Le fil série unique entre le Pi et le RP2040 (half-duplex)."""

    vitesse_bauds: Literal[9600, 19200, 38400, 57600, 115200, 230400]
    periode_ms: int = Field(ge=20, le=60000)
    attente_reponse_ms: int = Field(ge=5, le=10000)
    sans_reponse_max: int = Field(ge=1, le=100)
    reconnexion_s: float = Field(gt=0, le=3600)
    niveau_max_s: float = Field(ge=0, le=86400)
    envoyer_reglages: bool

    @model_validator(mode="after")
    def _verifier_delais(self) -> "LiaisonAccelerometre":
        erreurs = []
        # Une question et sa réponse, les plus longues possible (10 bits par octet).
        aller_retour_ms = 2 * LIGNE_MAX_LIAISON * 10 * 1000 / self.vitesse_bauds
        if self.attente_reponse_ms < aller_retour_ms:
            erreurs.append(
                f"attente_reponse_ms ({self.attente_reponse_ms} ms) doit valoir au moins "
                f"{aller_retour_ms:.0f} ms : le temps d'une question et d'une réponse à "
                f"{self.vitesse_bauds} bauds"
            )
        if self.periode_ms < self.attente_reponse_ms:
            erreurs.append(
                f"periode_ms ({self.periode_ms} ms) doit valoir au moins attente_reponse_ms "
                f"({self.attente_reponse_ms} ms)"
            )
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class ChargeurAccelerometre(Modele):
    """Le chargeur du RP2040 : mise à jour du programme par le fil série (tâche 16)."""

    # Dans le chargeur (le réinstaller par l'USB pour les changer).
    attente_demarrage_ms: int = Field(ge=50, le=5000)
    abandon_s: int = Field(ge=5, le=3600)
    chien_de_garde_ms: int = Field(ge=1000, le=8000)
    # Côté Pi.
    attente_ecriture_ms: int = Field(ge=100, le=10000)
    redemarrage_s: float = Field(gt=0, le=60)
    essais: int = Field(ge=1, le=20)


class ReglagesAccelerometre(Modele):
    """accelerometre.yaml : le programme du RP2040 qui surveille les chocs du chariot Z."""

    exemple: bool = False
    # Nom de la carte pour le Pico SDK (PICO_BOARD).
    carte: Nom
    broches: BrochesAccelerometre
    capteur: CapteurAccelerometre
    choc: ChocAccelerometre
    panne: PanneAccelerometre
    console: ConsoleAccelerometre
    liaison: LiaisonAccelerometre
    chargeur: ChargeurAccelerometre

    @model_validator(mode="after")
    def _verifier_ensemble(self) -> "ReglagesAccelerometre":
        erreurs = []
        pleine_echelle = self.capteur.pleine_echelle_g
        if self.choc.seuil_g >= pleine_echelle:
            erreurs.append(
                f"choc → seuil_g ({self.choc.seuil_g:g} g) doit être plus petit que "
                f"capteur → pleine_echelle_g ({pleine_echelle} g) : le capteur ne mesure pas plus"
            )
        periode_ms = 1000 / self.capteur.mesures_par_seconde
        regles = [
            ("panne → sans_mesure_ms", self.panne.sans_mesure_ms, 3),
            ("panne → figee_ms", self.panne.figee_ms, 20),
            ("choc → constante_fond_ms", self.choc.constante_fond_ms, 10),
        ]
        for nom, valeur, fois in regles:
            if valeur < fois * periode_ms:
                erreurs.append(
                    f"{nom} ({valeur} ms) doit valoir au moins {fois} fois le temps entre deux "
                    f"mesures ({periode_ms:g} ms avec {self.capteur.mesures_par_seconde} "
                    "mesures par seconde)"
                )
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


# --------------------------------------------------------------- pesees.yaml

# Broches UART du RP2040 : (bloc, TX possibles, RX possibles).
UARTS_RP2040 = ((0, (0, 12, 16, 28), (1, 13, 17, 29)), (1, (4, 8, 20, 24), (5, 9, 21, 25)))


class BrochesPesee(Modele):
    hx711_dt: BrocheRp2040
    hx711_sck: BrocheRp2040
    rs485_tx: BrocheRp2040
    rs485_rx: BrocheRp2040
    # Entrées DE et /RE de l'émetteur-récepteur RS485, reliées ensemble (1 = parler).
    rs485_sens: BrocheRp2040
    voyant: BrocheRp2040 | None = None

    @property
    def bloc_uart(self) -> int:
        """Bloc UART du RP2040 (0 ou 1) qui sort sur ces broches."""
        return next(bloc for bloc, tx, _ in UARTS_RP2040 if self.rs485_tx in tx)

    @model_validator(mode="after")
    def _verifier_broches(self) -> "BrochesPesee":
        erreurs = []
        bloc_tx = [bloc for bloc, tx, _ in UARTS_RP2040 if self.rs485_tx in tx]
        bloc_rx = [bloc for bloc, _, rx in UARTS_RP2040 if self.rs485_rx in rx]
        if not bloc_tx:
            erreurs.append(
                f"rs485_tx ({self.rs485_tx}) n'est pas une broche TX d'UART "
                "(UART0 : 0, 12, 16, 28 ; UART1 : 4, 8, 20, 24)"
            )
        if not bloc_rx:
            erreurs.append(
                f"rs485_rx ({self.rs485_rx}) n'est pas une broche RX d'UART "
                "(UART0 : 1, 13, 17, 29 ; UART1 : 5, 9, 21, 25)"
            )
        if bloc_tx and bloc_rx and bloc_tx != bloc_rx:
            erreurs.append(
                f"rs485_tx ({self.rs485_tx}) et rs485_rx ({self.rs485_rx}) ne sont pas du même UART"
            )
        deja_vues: dict[int, str] = {}
        for nom, broche in self.model_dump().items():
            if broche is None:
                continue
            autre = deja_vues.setdefault(broche, nom)
            if autre != nom:
                erreurs.append(f"la broche {broche} est prise deux fois ({autre} et {nom})")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class ProgrammePesee(Modele):
    """Copié dans le programme des cartes (pesee/) quand on le fabrique."""

    # Plus de mesure du HX711 depuis ce temps (ms) : « HX711 muet ».
    sans_mesure_ms: int = Field(ge=20, le=10000)
    # Attente avant de répondre (µs), le temps que l'adaptateur du Pi repasse en écoute.
    delai_avant_reponse_us: int = Field(ge=0, le=1000)
    # Le chien de garde du RP2040 ne compte pas plus loin que 8,3 s.
    chien_de_garde_ms: int = Field(ge=10, le=8000)
    periode_affichage_ms: int = Field(ge=100, le=600000)


class EtalonnagePesee(Modele):
    """Mesure brute à vide, et nombre de points de la mesure brute par kilogramme posé."""

    zero_brut: int
    brut_par_kg: float

    @model_validator(mode="after")
    def _pente(self) -> "EtalonnagePesee":
        if self.brut_par_kg == 0:
            raise ValueError("brut_par_kg ne peut pas valoir 0")
        return self


class ReglagesPesees(Modele):
    """pesees.yaml : les cartes de pesée RP2040 + HX711 du bus RS485 des pesées."""

    exemple: bool = False
    # Nom de la carte RP2040 pour le Pico SDK (PICO_BOARD).
    carte: Nom
    broches: BrochesPesee
    programme: ProgrammePesee
    # Côté Pi : ordre des questions (une carte peut revenir plusieurs fois par tour).
    tour: list[Nom] = Field(min_length=1)
    pause_entre_tours_ms: int = Field(ge=0, le=10000)
    # Mesure plus vieille que ça (ms) : la pesée est dite muette pour qui la lit.
    age_max_ms: int = Field(gt=0, le=60000)
    # Plus aucune carte ne répond : nouvel essai toutes les ... (s).
    reconnexion_s: float = Field(gt=0, le=3600)
    etalonnage: dict[Nom, EtalonnagePesee] = Field(min_length=1)

    @model_validator(mode="after")
    def _verifier_cartes(self) -> "ReglagesPesees":
        erreurs = []
        for nom in dict.fromkeys(self.tour):
            if nom not in self.etalonnage:
                erreurs.append(f"tour : « {nom} » n'a pas d'étalonnage (section etalonnage)")
        for nom in self.etalonnage:
            if nom not in self.tour:
                erreurs.append(f"etalonnage : « {nom} » n'est jamais lue (absente de « tour »)")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


# --------------------------------------------------------------- vision.yaml

# Caméras que le code de la vision connaît par leur nom (tâche 22).
CAMERAS_VISION = ("plafond", "tete_griffe", "dosage")

# Dictionnaires de repères ArUco d'OpenCV → nombre de repères qu'ils contiennent.
DICTIONNAIRES_ARUCO = {
    "DICT_4X4_50": 50,
    "DICT_4X4_100": 100,
    "DICT_4X4_250": 250,
    "DICT_5X5_50": 50,
    "DICT_5X5_100": 100,
    "DICT_5X5_250": 250,
    "DICT_6X6_50": 50,
    "DICT_6X6_250": 250,
}

# Ce que la caméra du plafond sait dire d'une photo (vidange.vision.plafond.faits) : les
# conditions des règles « situation → travail ». « pas <fait> » : le contraire.
FAITS_PLAFOND = (
    "doute",
    "objet_inconnu",
    "piece_mal_placee",
    "fut_plein",
    "fut_plein_mais",
    "bocaux_vides_propres",
    "seaux_vides_propres",
    "bocal_semence_pret",
    "bocaux_sales",
    "seaux_sales",
    "couvercles_sales",
    "lave_bocal_pose",
    "places_libres",
)


class TeteCameraVision(Modele):
    """Caméra portée par la tête de la griffe : son objectif par rapport à l'axe du mât (tête à
    0°, m) et au-dessus des axes de la tête (m)."""

    decalage_m: tuple[float, float]
    au_dessus_axes_m: float


class CameraVision(Modele):
    description: Annotated[str, StringConstraints(min_length=1)]
    # Nom de la vidéo dans programme.yaml (cameras → liste). None : caméra seulement déclarée
    # (servie par la tâche qui s'en sert).
    video: Nom | None = None
    # Champ de vision (horizontal, vertical, °) : mesure grossière tant qu'il n'y a pas de
    # fichier de calibration.
    champ_deg: tuple[Annotated[float, Field(gt=0, lt=180)], Annotated[float, Field(gt=0, lt=180)]]
    # Fichier de calibration (dans le dossier des calibrations), fait par « vidange-vision
    # calibrer ».
    calibration: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]+$")] | None = None
    # Caméra fixe : objectif (x, y, z) dans le repère du portique, vue vers le bas.
    position: tuple[float, float, float] | None = None
    # Caméra sur la tête de la griffe.
    tete: TeteCameraVision | None = None
    # Angle (°) du bord haut de l'image (de gauche à droite) avec l'axe x du portique (tête à
    # 0° pour une caméra de tête).
    orientation_deg: float = 0

    @model_validator(mode="after")
    def _verifier(self) -> "CameraVision":
        if self.position is not None and self.tete is not None:
            raise ValueError("une caméra est fixe (position) ou sur la tête (tete), pas les deux")
        return self


class CalibrationVision(Modele):
    """Mire en damier (OpenCV) pour corriger la déformation du grand angle."""

    # Dossier des fichiers de calibration, dans le dossier des données du Pi.
    dossier: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]+$")]
    # Coins intérieurs du damier (une case de plus de chaque côté), et côté d'une case (m).
    colonnes: int = Field(ge=3, le=30)
    lignes: int = Field(ge=3, le=30)
    case_m: float = Field(gt=0)
    # Photos prises par l'outil, et photos où le damier doit être trouvé (au moins).
    photos: int = Field(ge=3, le=100)
    photos_min: int = Field(ge=3)
    attente_entre_s: float = Field(ge=0)
    # Erreur moyenne de la calibration au-dessus de laquelle elle est refusée (points).
    erreur_max_px: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier(self) -> "CalibrationVision":
        if self.photos_min > self.photos:
            raise ValueError(
                f"photos_min ({self.photos_min}) plus grand que photos ({self.photos})"
            )
        if self.colonnes == self.lignes:
            # Un damier carré n'a pas de sens : OpenCV ne sait pas où est le haut.
            raise ValueError("colonnes et lignes doivent être différentes (damier pas carré)")
        return self


class LectureTeteQr(Modele):
    """Lecture des QR par la caméra de tête : godet grand ouvert, axes à cette hauteur."""

    axes_z: float
    godet_ouvert: float = Field(gt=0, le=1)
    # Hauteur des axes de la photo de secours (QR illisible deux fois).
    autre_axes_z: float


class QrVision(Modele):
    # Forme des codes du registre (« S1293 », « B327 »...) : un QR d'une autre forme est ignoré.
    forme: Annotated[str, StringConstraints(min_length=1)]
    lecture_tete: LectureTeteQr
    # Angle de l'objet = angle du QR + ce décalage (repère d'angle, plan v181).
    angle_objet_deg: float = Field(ge=-180, le=180)
    # Photos à la même hauteur avant la photo de secours (2 : la première et un deuxième tour).
    essais_meme_hauteur: int = Field(ge=1, le=5)

    @model_validator(mode="after")
    def _verifier(self) -> "QrVision":
        try:
            re.compile(self.forme)
        except re.error as erreur:
            raise ValueError(f"forme : expression mal écrite ({erreur})") from None
        return self


class ArucoVision(Modele):
    dictionnaire: Literal[tuple(DICTIONNAIRES_ARUCO)]  # type: ignore[valid-type]
    # Repère de 40 mm sur le plateau du rince-verre du lave-bocal.
    lave_bocal: int = Field(ge=0)
    taille_lave_bocal_m: float = Field(gt=0)
    # Repères du calibrage du plafond.
    calibrage_plafond: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _verifier(self) -> "ArucoVision":
        numeros = [self.lave_bocal, *self.calibrage_plafond]
        erreurs = []
        if len(set(numeros)) != len(numeros):
            erreurs.append("un numéro de repère est pris deux fois")
        taille = DICTIONNAIRES_ARUCO[self.dictionnaire]
        erreurs += [
            f"repère n° {n} : le dictionnaire {self.dictionnaire} va de 0 à {taille - 1}"
            for n in numeros
            if n >= taille
        ]
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class RegleVision(Modele):
    """Une règle « situation → travail » de la caméra du plafond. Elle correspond si toutes les
    conditions de « si » sont vraies, et au moins une de « si_un_de » (si elle en a)."""

    numero: int = Field(ge=1)
    si: list[str] = Field(default_factory=list)
    si_un_de: list[str] = Field(default_factory=list)
    # Nom du travail, et ce que le Pi en fait : alerte (rien ne bouge), proposer (attend le Go),
    # demander (à Karulium de faire quelque chose), attendre (nouvelle photo plus tard).
    travail: Nom
    sorte: Literal["alerte", "proposer", "demander", "attendre"]
    message: Annotated[str, StringConstraints(min_length=1)]

    @model_validator(mode="after")
    def _verifier(self) -> "RegleVision":
        inconnus = [
            condition
            for condition in (*self.si, *self.si_un_de)
            if condition.removeprefix("pas ") not in FAITS_PLAFOND
        ]
        if inconnus:
            raise ValueError(
                f"règle n° {self.numero} : condition inconnue {', '.join(inconnus)} (connues : "
                f"{', '.join(FAITS_PLAFOND)}, et « pas » devant)"
            )
        return self


class PlafondVision(Modele):
    # Une photo plus vieille que ça (s) est refusée.
    photo_age_max_s: float = Field(gt=0)
    # Photo seulement pont garé au bout opposé : pont à x ≥ ... (m).
    pont_gare_x_min: float
    # Règle « rien à faire » : nouvelle photo après ce temps (s).
    attente_s: float = Field(gt=0)
    # Contrôle du lave-bocal par la caméra avant chaque geste dangereux pour lui.
    controle_lave_bocal: bool
    # Dans l'ordre : la première qui correspond gagne. La dernière n'a pas de condition.
    regles: list[RegleVision] = Field(min_length=1)

    @model_validator(mode="after")
    def _verifier(self) -> "PlafondVision":
        erreurs = [
            f"regles : la règle n° {regle.numero} est à la place n° {place}"
            for place, regle in enumerate(self.regles, start=1)
            if regle.numero != place
        ]
        derniere = self.regles[-1]
        if derniere.si or derniere.si_un_de:
            erreurs.append(
                f"regles : la dernière (n° {derniere.numero}) doit être sans condition (« rien "
                "de tout cela »)"
            )
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class ReglagesVision(Modele):
    """vision.yaml : caméras, QR, repères ArUco, caméra du plafond (tâche 22)."""

    exemple: bool = False
    # Photos de mesure : à l'arrêt, après ce temps (s).
    stabilisation_s: float = Field(ge=0)
    # Une photo qui n'arrive pas dans ce délai (s) : caméra en panne.
    delai_photo_s: float = Field(gt=0)
    cameras: dict[Nom, CameraVision]
    calibration: CalibrationVision
    qr: QrVision
    aruco: ArucoVision
    plafond: PlafondVision

    @model_validator(mode="after")
    def _verifier(self) -> "ReglagesVision":
        erreurs = [
            f"cameras : il manque « {nom} »" for nom in CAMERAS_VISION if nom not in self.cameras
        ]
        if self.delai_photo_s <= self.stabilisation_s:
            erreurs.append(
                f"delai_photo_s ({self.delai_photo_s:g} s) doit dépasser stabilisation_s "
                f"({self.stabilisation_s:g} s)"
            )
        for nom in ("plafond", "dosage"):
            camera = self.cameras.get(nom)
            if camera is not None and camera.video is None:
                erreurs.append(f"cameras → {nom} : il faut sa vidéo (video)")
        if "plafond" in self.cameras and self.cameras["plafond"].position is None:
            erreurs.append("cameras → plafond : il faut sa position")
        if "tete_griffe" in self.cameras and self.cameras["tete_griffe"].tete is None:
            erreurs.append("cameras → tete_griffe : il faut sa place sur la tête (tete)")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


# --------------------------------------------------------------- l'ensemble


class Reglages(Modele):
    machine: Machine
    programme: Programme
    fluidnc: Fluidnc
    simulateur: ReglagesSimulateur
    accelerometre: ReglagesAccelerometre
    pesees: ReglagesPesees
    vision: ReglagesVision


# Nom du fichier → (nom dans Reglages, modèle). Ajouter ici chaque nouveau fichier.
FICHIERS: dict[str, tuple[str, type[Modele]]] = {
    "machine.yaml": ("machine", Machine),
    "programme.yaml": ("programme", Programme),
    "fluidnc.yaml": ("fluidnc", Fluidnc),
    "simulateur.yaml": ("simulateur", ReglagesSimulateur),
    "accelerometre.yaml": ("accelerometre", ReglagesAccelerometre),
    "pesees.yaml": ("pesees", ReglagesPesees),
    "vision.yaml": ("vision", ReglagesVision),
}


def charger_reglages(dossier: Path) -> Reglages:
    """Lit et vérifie tous les fichiers de réglages, ou lève ErreurReglages."""
    if not dossier.is_dir():
        raise ErreurReglages(f"Le dossier des réglages n'existe pas : {dossier}")
    erreurs: list[str] = []
    for chemin in sorted([*dossier.glob("*.yaml"), *dossier.glob("*.yml")]):
        if chemin.name not in FICHIERS:
            erreurs.append(
                f"{chemin.name} : fichier inconnu (fichiers attendus : {', '.join(FICHIERS)})"
            )
    valeurs: dict[str, Modele] = {}
    for nom_fichier, (cle, modele) in FICHIERS.items():
        chemin = dossier / nom_fichier
        if not chemin.exists():
            erreurs.append(f"{nom_fichier} : fichier manquant")
            continue
        try:
            valeurs[cle] = modele.model_validate(lire_yaml(chemin))
        except ErreurReglages as erreur:
            erreurs.append(str(erreur))
        except ValidationError as erreur:
            erreurs.extend(traduire_erreurs(erreur, nom_fichier))
    if not erreurs:
        erreurs.extend(_verifier_entre_fichiers(valeurs))
    if erreurs:
        raise ErreurReglages(rediger(erreurs, dossier))
    return Reglages.model_validate(valeurs)


def _verifier_entre_fichiers(valeurs: dict[str, Modele]) -> list[str]:
    """Ce qu'un fichier cite d'un autre fichier doit y exister."""
    machine, fluidnc = valeurs["machine"], valeurs["fluidnc"]
    assert isinstance(machine, Machine) and isinstance(fluidnc, Fluidnc)
    cartes = ", ".join(fluidnc.cartes)
    erreurs = [
        f"machine.yaml, axes → {nom} : carte « {axe.carte} » absente de fluidnc.yaml "
        f"(cartes : {cartes})"
        for nom, axe in machine.axes.items()
        if axe.carte is not None and axe.carte not in fluidnc.cartes
    ]
    erreurs += [
        f"machine.yaml, lieu_sur n° {numero} : carte « {geste.prise_origine} » absente de "
        f"fluidnc.yaml (cartes : {cartes})"
        for numero, geste in enumerate(machine.lieu_sur, start=1)
        if geste.prise_origine is not None and geste.prise_origine not in fluidnc.cartes
    ]
    programme = valeurs["programme"]
    assert isinstance(programme, Programme)
    avance, periode_etat = programme.distance.avance_s, fluidnc.liaison.periode_etat_s
    if avance < 2 * periode_etat:
        # Le Pi ajoute du mouvement d'après les positions lues : elles doivent être fraîches.
        erreurs.append(
            f"programme.yaml, distance → avance_s ({avance:g} s) doit valoir au moins 2 fois "
            f"periode_etat_s de fluidnc.yaml ({periode_etat:g} s)"
        )
    if machine.mycelium is not None:
        # Le Pi lit le capteur de la manivelle à chaque état de la carte : le pas entre deux
        # lectures doit rester sous la moitié de l'écart permis sur la largeur de la zone.
        origine = machine.mycelium.manivelle.origine
        pas_deg = origine.vitesse_deg_s * periode_etat
        if pas_deg > origine.ecart_largeur_max_deg / 2:
            erreurs.append(
                f"machine.yaml, mycelium → manivelle → origine → vitesse_deg_s : "
                f"{origine.vitesse_deg_s:g} °/s × periode_etat_s de fluidnc.yaml "
                f"({periode_etat:g} s) = {pas_deg:g}° entre deux lectures du capteur, plus que "
                f"ecart_largeur_max_deg / 2 ({origine.ecart_largeur_max_deg / 2:g}°)"
            )
    if machine.porte_bocal is not None:
        attente = machine.porte_bocal.demi_tour.attente_inclinaison_s
        if attente < 2 * periode_etat:
            erreurs.append(
                f"machine.yaml, porte_bocal → demi_tour → attente_inclinaison_s ({attente:g} s) "
                f"doit valoir au moins 2 fois periode_etat_s de fluidnc.yaml ({periode_etat:g} s)"
            )
    if machine.prehension is not None:
        carte_tete = machine.axes["prehension_z"].carte
        carte = fluidnc.cartes.get(carte_tete or "")
        if carte is not None:
            erreurs += [
                f"fluidnc.yaml, cartes → {carte_tete} → {quoi} : il manque « {nom} » (préhension)"
                for quoi, noms, connus in (
                    ("entrees", ENTREES_PREHENSION, carte.entrees),
                    ("sorties", SORTIES_PREHENSION, carte.sorties),
                )
                for nom in noms
                if nom not in connus
            ]
    if machine.lavage is not None:
        # Chaque signal du lavage est sur une seule carte (n° 3 ou n° 4 : le plan de câblage
        # choisit) ; le code ne connaît que son nom.
        for quoi, noms in (("entrees", ENTREES_LAVAGE), ("sorties", SORTIES_LAVAGE)):
            for nom in noms:
                cartes_du_signal = [
                    carte
                    for carte, reglage in fluidnc.cartes.items()
                    if nom in getattr(reglage, quoi)
                ]
                if len(cartes_du_signal) != 1:
                    ou = ", ".join(cartes_du_signal) or "aucune carte"
                    erreurs.append(
                        f"fluidnc.yaml : « {nom} » (lavage) doit être dans les {quoi} d'une seule "
                        f"carte ({ou})"
                    )
    vision = valeurs["vision"]
    assert isinstance(vision, ReglagesVision)
    videos = ", ".join(programme.cameras.liste) or "aucune"
    erreurs += [
        f"vision.yaml, cameras → {nom} : vidéo « {camera.video} » absente de programme.yaml "
        f"(cameras → liste : {videos})"
        for nom, camera in vision.cameras.items()
        if camera.video is not None and camera.video not in programme.cameras.liste
    ]
    simulateur = valeurs["simulateur"]
    assert isinstance(simulateur, ReglagesSimulateur)
    erreurs += [
        f"simulateur.yaml, axes → {nom} : axe absent de machine.yaml"
        for nom in simulateur.axes
        if nom not in machine.axes
    ]
    if simulateur.mycelium is not None:
        formats = machine.griffe.formats if machine.griffe is not None else {}
        erreurs += [
            f"simulateur.yaml, mycelium → seaux : format « {seau.format} » absent de "
            "machine.yaml (griffe → formats)"
            for seau in simulateur.mycelium.seaux
            if seau.format not in formats
        ]
    if simulateur.lavage is not None:
        formats = machine.lavage.formats if machine.lavage is not None else {}
        erreurs += [
            f"simulateur.yaml, lavage → seaux : format « {seau.format} » absent de machine.yaml "
            "(lavage → formats)"
            for seau in simulateur.lavage.seaux
            if seau.format not in formats
        ]
    if simulateur.depart is not None and simulateur.depart not in machine.positions:
        erreurs.append(
            f"simulateur.yaml, depart : position « {simulateur.depart} » absente de machine.yaml"
        )
    return erreurs


def rediger(erreurs: list[str], dossier: Path) -> str:
    lignes = "\n".join(f"  - {erreur}" for erreur in erreurs)
    return f"Réglages faux dans {dossier}, le programme ne démarre pas :\n{lignes}"


# ------------------------------------------------------ lecture des fichiers


class _LecteurStrict(yaml.SafeLoader):
    """Lecteur YAML qui refuse un nom écrit deux fois (YAML garderait le second sans rien dire)."""


def _construire_dict(lecteur: _LecteurStrict, noeud: yaml.MappingNode) -> dict[Any, Any]:
    resultat: dict[Any, Any] = {}
    for noeud_cle, noeud_valeur in noeud.value:
        cle = lecteur.construct_object(noeud_cle, deep=True)
        if cle in resultat:
            raise yaml.constructor.ConstructorError(
                None, None, f"« {cle} » est écrit deux fois", noeud_cle.start_mark
            )
        resultat[cle] = lecteur.construct_object(noeud_valeur, deep=True)
    return resultat


_LecteurStrict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construire_dict)


def lire_yaml(chemin: Path) -> dict[str, Any]:
    """Lit un fichier YAML qui doit contenir une liste de « nom: valeur »."""
    try:
        with chemin.open(encoding="utf-8") as fichier:
            donnees = yaml.load(fichier, Loader=_LecteurStrict)
    except yaml.YAMLError as erreur:
        repere = getattr(erreur, "problem_mark", None)
        ligne = f", ligne {repere.line + 1}" if repere is not None else ""
        probleme = getattr(erreur, "problem", None) or str(erreur)
        raise ErreurReglages(f"{chemin.name}{ligne} : fichier mal écrit ({probleme})") from None
    except UnicodeDecodeError:
        raise ErreurReglages(f"{chemin.name} : fichier non enregistré en UTF-8") from None
    if donnees is None:
        raise ErreurReglages(f"{chemin.name} : fichier vide")
    if not isinstance(donnees, dict):
        raise ErreurReglages(f"{chemin.name} : le fichier doit être une liste de « nom: valeur »")
    return donnees


# ---------------------------------------------- erreurs de pydantic en français

_MESSAGES = {
    "missing": "manque",
    "extra_forbidden": "nom inconnu (faute de frappe ?)",
    "float_parsing": "doit être un nombre",
    "float_type": "doit être un nombre",
    "int_parsing": "doit être un nombre entier",
    "int_type": "doit être un nombre entier",
    "int_from_float": "doit être un nombre entier",
    "bool_parsing": "doit être « true » (oui) ou « false » (non)",
    "bool_type": "doit être « true » (oui) ou « false » (non)",
    "string_type": "doit être un texte (entre guillemets s'il n'a que des chiffres)",
    "dict_type": "doit être une liste de « nom: valeur »",
    "list_type": "doit être une liste (une ligne « - nom » par élément)",
    "model_type": "doit être une liste de « nom: valeur »",
    "tuple_type": "doit être deux nombres entre crochets, par exemple [0.0, 1.0]",
    "string_pattern_mismatch": "nom à écrire en minuscules, sans accent ni espace (a-z, 0-9, _)",
}


def _message(detail: dict[str, Any]) -> str:
    sorte = detail["type"]
    contexte = detail.get("ctx", {})
    if sorte == "string_pattern_mismatch" and str(contexte.get("pattern", "")).startswith("^#"):
        return 'couleur à écrire « #RRGGBB » entre guillemets (exemple : "#00A000")'
    if sorte in _MESSAGES:
        return _MESSAGES[sorte]
    if sorte in ("too_short", "too_long") and detail["loc"] and detail["loc"][-1] == "course":
        return "doit être deux nombres entre crochets, par exemple [0.0, 1.0]"
    if sorte == "too_short":
        return "ne doit pas être vide" if contexte.get("min_length") == 1 else "trop court"
    if sorte == "too_long":
        return "trop d'éléments"
    if sorte == "greater_than":
        return f"doit être plus grand que {contexte['gt']}"
    if sorte == "greater_than_equal":
        return f"doit valoir au moins {contexte['ge']}"
    if sorte == "less_than":
        return f"doit être plus petit que {contexte['lt']}"
    if sorte == "less_than_equal":
        return f"doit valoir au plus {contexte['le']}"
    if sorte == "literal_error":
        return f"doit être l'un de : {contexte['expected']}"
    if sorte == "union_tag_invalid":
        return f"type: doit être l'un de : {contexte['expected_tags']}"
    if sorte == "union_tag_not_found":
        return f"« {contexte['discriminator'].strip(chr(39))} » manque"
    if sorte == "value_error":
        return str(contexte["error"])
    return detail["msg"]


def traduire_erreurs(erreur: ValidationError, nom_fichier: str) -> list[str]:
    """Une ligne en français par erreur : « fichier, endroit : ce qui ne va pas »."""
    lignes = []
    for detail in erreur.errors():
        # « [key] » : pydantic signale que l'erreur est dans le nom lui-même.
        # Un nombre : la place dans une liste, comptée à partir de 1 (pydantic part de 0).
        endroit = " → ".join(
            f"n° {morceau + 1}" if isinstance(morceau, int) else str(morceau)
            for morceau in detail["loc"]
            if morceau != "[key]"
        )
        debut = f"{nom_fichier}, {endroit}" if endroit else nom_fichier
        for ligne in _message(detail).split("\n"):
            lignes.append(f"{debut} : {ligne}")
    return lignes
