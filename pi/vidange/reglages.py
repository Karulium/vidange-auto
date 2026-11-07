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
    # Geste du portique (partie « portique ») : sa prise d'origine dans l'ordre, ou son garage.
    portique: Literal["origine", "garage"] | None = None
    # Délai maximal du geste (nom dans « durees »).
    delai: Nom

    @model_validator(mode="after")
    def _un_seul_geste(self) -> "GesteLieuSur":
        if [self.prise_origine, self.aller, self.portique].count(None) != 2:
            raise ValueError(
                "écrire « prise_origine: carte », « aller: position » ou « portique: origine » "
                "(un seul)"
            )
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
    """Pesée du plateau du fût (sans fil : boîte du poste sur le bus des pesées, tâche 17 bis).

    L'étalonnage (zéro, pente) est dans pesees.yaml (etalonnage → pesee_fut), comme les autres
    pesées du bus ; ici, ce que le poste du fût fait du poids."""

    # Vrai tant que la tare et les bornes n'ont pas été mesurées sur la vraie pesée.
    exemple: bool = False
    # Poids lu avec un fût vide et son couvercle (kg) : poids net du substrat = poids lu − tare.
    tare_kg: float = Field(ge=0)
    # Poids lu plausible quand un fût est sur le plateau (kg) : une valeur hors de ces bornes
    # est rejetée (pas de poids).
    plausible_kg: Intervalle
    # Après « plateau en place », la pesée doit répondre dans ce délai (s) : sinon, « pesée
    # absente » (message, journal, alerte ; jamais un refus ni un arrêt).
    delai_apres_plateau_s: float = Field(gt=0)
    # Écart permis entre la somme des doses de la griffe et la baisse de la pesée (kg) :
    # au-delà, un avertissement (pas un arrêt).
    ecart_doses_max_kg: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier(self) -> "PeseeFut":
        if self.plausible_kg[0] >= self.plausible_kg[1]:
            raise ValueError("plausible_kg : aller du plus petit au plus grand")
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
    # Plateau du fût absent ou en mouvement : le pont reste hors de cet intervalle de x
    # (le fût monte à 1,06, le chariot X du pont descend à 1,11).
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


class PointDemiTourGriffe(Modele):
    """Point des demi-tours de la tête hors du fût et de la recherche de l'origine de A : mât en
    (x, y), axes à z, godet fermé (fil Griffe, 03/11/2026)."""

    x: float
    y: float
    z: float
    # « Au point » à tant près (m).
    tolerance_m: float = Field(default=0.001, gt=0)


class OrigineRotationGriffe(Modele):
    """Prise d'origine de la rotation de la tête (fanion de 180°, PR n° 56, point 4) : le Pi
    tourne d'abord en − jusqu'au fanion s'il est libre (au plus recherche_deg, à vitesse_deg_s),
    puis « $HA » (approche finale en +, lente)."""

    recherche_deg: float = Field(gt=0, le=360)
    vitesse_deg_s: float = Field(gt=0)


class TrajetGriffe(Modele):
    """Trajet fût ↔ poste de remplissage : jamais en diagonale."""

    # Hauteur des axes pendant les trajets.
    z: float
    # D'abord en x avec le mât à y ≥ mat_y_min, puis en y seulement une fois le mât à
    # x ≥ mat_x_min_pour_y ; retour dans l'ordre inverse.
    mat_y_min: float
    mat_x_min_pour_y: float


class BandeGriffe(Modele):
    """Y minimum du mât pour une bande de x du mât, godet fermé, à moitié ouvert, grand ouvert
    (volumes interdits). Les bandes se chevauchent exprès : une pose est refusée par toute
    bande qui la contient."""

    x: Intervalle
    y_min: tuple[float, float, float]


class YMinMatGriffe(Modele):
    """Tables « y minimum du mât » de l'agitateur fixe (docs/decisions.md, 02/11/2026) : une
    pour les axes en butée haute, une pour les axes dessous."""

    butee_haute: list[BandeGriffe] = Field(min_length=1)
    sous_butee: list[BandeGriffe] = Field(min_length=1)


class OuvertureFutGriffe(Modele):
    """Mât à x < 0,78 et axes de z_min à la butée haute : la tête passe dans l'ouverture du
    poste du fût. Permis seulement le mât à au plus rayon_mat_max de l'axe du fût (godet fermé,
    à moitié ouvert, grand ouvert)."""

    rayon_mat_max: tuple[float, float, float]
    z_min: float
    # Le mât doit être à x < mat_x_max_m pour que la règle s'applique (au-delà, tables seules).
    mat_x_max_m: float


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
    # les bras dépassent du mât, de demi_longueur_haut le long du bras. Godet fermé, c'est vrai
    # jusqu'en bas (haut_sous_axes_ferme) ; godet ouvert, la tête s'élargit en descendant sous
    # les axes : profil_ouvert = [profondeur sous les axes jusqu'à laquelle la demi-longueur
    # tient, demi-longueur] (griffe.json), croissant ; au-delà, la tête ouverte entière.
    demi_longueur_haut: float = Field(gt=0)
    haut_sous_axes_ferme: float = Field(ge=0)
    profil_ouvert: list[tuple[float, float]] = Field(min_length=1)

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
    """Porte du coffret du spray ouverte : griffe interdite en x < x_max et y < y_max (x < 0,50
    et y < 0,40 depuis la Maquette du 31/10), et jamais au « Bain des têtes » (geste pas encore
    écrit : à brancher avec lui)."""

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
    # Au-dessus du seau du remplissage (mât à moins de ça de seau_remplissage), godet ouvert, la
    # tête reste bras le long du pont (A = 0 ou 180°, tolérance rotation → tolerance_deg) : tournée,
    # elle touche le boîtier de la caméra du bocal.
    zone_seau_m: float = Field(gt=0)


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
    # Ouverture du godet pendant l'essuyage : de 0 (fermé) à moins de 1 (grand ouvert touche le
    # moteur des barres du Remplissage, docs/decisions.md, 01/11/2026).
    ouverture_godet: float = Field(ge=0, lt=1)


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
    # Diamètre du couvercle (m) : pour la Fermeture des seaux (tâche 41) et le contrôle de la
    # bande du haut du Stockage (bord du couvercle ≤ bord_x_max, décisions, PR n° 54).
    diametre_couvercle: float | None = Field(default=None, gt=0)


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
    # Mât en y godet grand ouvert ; godet fermé : course de chariot_y, et au moins
    # mat_y_min_ferme (None : le début de la course).
    mat_y_grand_ouvert: Intervalle
    mat_y_min_ferme: float | None = None
    trajet: TrajetGriffe
    y_min_mat: YMinMatGriffe
    ouverture_fut: OuvertureFutGriffe
    # Écart sous lequel les axes sont « en butée haute » (fin de la course de griffe_z), en m.
    tolerance_butee_haute_m: float = Field(gt=0)
    dosage: ZoneMatGriffe
    camera_bocal: CameraBocalGriffe
    bout_cote_fut: BoutCoteFutGriffe
    porte_spray: PorteSprayGriffe
    # Demi-tours hors du fût et recherche de l'origine de A (None : pas de point).
    point_demi_tour: PointDemiTourGriffe | None = None
    # Prise d'origine de la rotation (None : pas de prise d'origine de A par le Pi).
    origine_rotation: OrigineRotationGriffe | None = None
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
    # Le mât quand la griffe vide dans le seau du chariot de remplissage (au vidage, y 0,42).
    seau_remplissage: tuple[float, float]
    # Où le mât attend, hors de la zone du plateau du fût, quand le fût est vide.
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
        for nom, bandes in (
            ("butee_haute", self.y_min_mat.butee_haute),
            ("sous_butee", self.y_min_mat.sous_butee),
        ):
            for bande in bandes:
                if bande.x[0] >= bande.x[1]:
                    erreurs.append(f"y_min_mat → {nom} : x du plus petit au plus grand")
        rayons = list(self.ouverture_fut.rayon_mat_max)
        if rayons != sorted(rayons, reverse=True):
            erreurs.append("ouverture_fut → rayon_mat_max : du plus grand au plus petit")
        if self.fond.force_max_n < self.fond.seuil_appui_n:
            erreurs.append("fond → force_max_n doit être au moins seuil_appui_n")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


# Délais (machine.yaml → durees) des étapes du Mycélium.
DUREES_MYCELIUM = ("mycelium_geste_max", "mycelium_chariot_max", "mycelium_agitation_max")
# L'axe de l'agitateur du Mycélium (carte n° 3) et son unité. L'agitateur est FIXE depuis le
# 01/11/2026 (plus de glissière) : seule la manivelle bouge.
AXES_MYCELIUM = {
    "manivelle": "deg",  # manivelle qui secoue le bocal (360° = un tour)
}


class ChariotMycelium(Modele):
    """Le chariot de remplissage vu du Mycélium (verrous, hauteur du plateau)."""

    # Demi-tour du bocal, et manivelle ailleurs qu'en bas, seulement chariot à y ≥ y_ecarte_min.
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
    # Les 3 trous de la manivelle (course du bocal, m).
    courses_possibles_m: list[float] = Field(min_length=1)
    # Vitesse la plus forte permise (tr/min, fiche).
    max_tr_min: float = Field(gt=0)
    origine: OrigineManivelle


class VitessesMycelium(Modele):
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
    """Module Mycélium (dosage), fiche v10 du 01/11/2026 : agitateur FIXE au-dessus du poste.

    Repère du portique, en mètres. Un verrou du logiciel ne protège que la machine : la sécurité
    des personnes reste câblée.
    """

    exemple: bool = False
    # Axe du bocal (x, y), toujours au même endroit (plus de glissière).
    bocal: tuple[float, float]
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
    # Derniers mm de la pose du bocal entre les mors (porte_bocal → descente_lente_pose_m).
    pose_bocal: float | None = Field(default=None, gt=0)
    # Pose du couvercle sur le seau plein (tâche 41 bis) : approche de la pile, décollage et
    # dégagement (20 mm/s) ; approche de la pose sur le seau (10 mm/s).
    couvercle_pile: float | None = Field(default=None, gt=0)
    couvercle_pose: float | None = Field(default=None, gt=0)
    # Bocal neuf de semence (tâche 19 quater) : levée de 3 cm après la prise (20 mm/s), approche
    # du col du bocal et du porte-bocal (5 mm/s), appui et décollage (2 mm/s). Les 10 mm/s de
    # l'approche de la capsule sont ceux de « approche ».
    bocal_levee: float | None = Field(default=None, gt=0)
    bocal_col: float | None = Field(default=None, gt=0)
    bocal_appui: float | None = Field(default=None, gt=0)


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


class CouloirPorteBocal(Modele):
    """Couloir d'accès au bocal (Maquette, 06/11/2026 ; décisions, « Agitateur fixe, réponses à
    la PR n° 64 », point (c)) : du départ, face à face_z, en −y jusqu'à la verticale du bocal (et
    retour en +y). Largeur en x autour de l'axe du bocal (m) : tête seule ± demi_largeur_x_tete ;
    avec un bocal largeur_x_bocal (−, +) ; dans le porte-bocal ± demi_largeur_x_mors."""

    depart: tuple[float, float]
    face_z: float
    demi_largeur_x_tete: float = Field(gt=0)
    largeur_x_bocal: Intervalle
    demi_largeur_x_mors: float = Field(gt=0)


class PorteBocalPrehension(Modele):
    """Pose et reprise du bocal dans le porte-bocal, sur l'agitateur fixe, MANIVELLE EN BAS
    (décisions, « Agitateur fixe, réponses à la PR n° 64 », point 2)."""

    # Axe du bocal (m).
    x: float
    y: float
    # Face de la tête au contact de la capsule (bocal à sa hauteur exacte entre les mors),
    # manivelle en bas : elle dépend de la course de l'agitation (trou du maneton), choisie avec
    # mycelium → course_agitation_m. {course (m) : face (m)}.
    contact_capsule_z: dict[float, float] = Field(min_length=1)
    # Le contact doit rester au moins tant sous la face haute (prehension → haut_z, m) : sinon
    # la pose est impossible et le démarrage refuse cette course.
    marge_face_haute_m: float = Field(ge=0)
    # Écart permis sur l'orientation de la tête (°, grâce aux méplats : prehension →
    # angle_meplats_deg).
    tolerance_orientation_deg: float = Field(gt=0)
    # Écart permis sur la hauteur du bocal (m), remontée avant le serrage (m).
    tolerance_hauteur_m: float = Field(gt=0)
    remontee_min_m: float = Field(gt=0)
    # Autour de l'axe du bocal (m) : tête « entre les mors » (elle ne tourne pas) sous le contact
    # de la capsule + descente → approche_m.
    rayon_zone_m: float = Field(gt=0)
    # Attente maximale d'un geste des mors (s).
    mors_max_s: float = Field(gt=0)
    # Le seul trajet permis dans la zone du porte-bocal (None : en ligne droite d'un point hors
    # de la zone, ancienne règle).
    couloir: CouloirPorteBocal | None = None
    # Avant de descendre sur le bocal : axe de la tête à x ± tolerance_pose_x_m et y dans
    # tolerance_pose_y_m (−, +) de la verticale (m).
    tolerance_pose_x_m: float = Field(default=0.001, gt=0)
    tolerance_pose_y_m: Intervalle = (-0.001, 0.001)
    # Les derniers mm de la pose du bocal, à la vitesse vitesses → pose_bocal (m ; 0 : rien).
    descente_lente_pose_m: float = Field(default=0.0, ge=0)

    def contact_z(self, course_m: float) -> float | None:
        """Face de la tête au contact de la capsule pour cette course de l'agitation (None : pas
        dans la table)."""
        for course, face in self.contact_capsule_z.items():
            if math.isclose(course, course_m, abs_tol=1e-9):
                return face
        return None


class ZonePorteBocalPrehension(Modele):
    """Zone du porte-bocal (décisions, « Agitateur fixe, réponses à la PR n° 64 », point 3) :
    rectangle x, y où rien de la tête (rayon de la tête + marge_m + rayon de l'objet tenu) ne va
    plus bas que z_haut + marge_m. Seule exception : la verticale du bocal, pour le poser ou le
    reprendre."""

    x: Intervalle
    y: Intervalle
    # Le plus haut point dans la zone (m) : porte-bocal pendant le demi-tour.
    z_haut: float
    marge_m: float = Field(ge=0)

    @model_validator(mode="after")
    def _verifier(self) -> "ZonePorteBocalPrehension":
        if self.x[0] >= self.x[1] or self.y[0] >= self.y[1]:
            raise ValueError("x et y : du plus petit au plus grand")
        return self


class OrigineRotationTete(Modele):
    """Prise d'origine de la rotation de la tête (capteur Hall, compte-tours ; décisions,
    « Origine de la rotation de la tête de préhension », 05/11/2026)."""

    # Compte-tours lu hors de cette plage (°) : potentiomètre hors plage ou débranché.
    compte_tours_plage_deg: Intervalle
    # Précision du compte-tours (°).
    precision_compte_tours_deg: float = Field(gt=0)
    # Avant « $HA », la tête est ramenée à tant de degrés AVANT le Hall (côté −) : la recherche
    # en + le trouve sans faire un tour de plus.
    avant_hall_deg: float = Field(gt=0, lt=180)
    # Vitesse du retour près de 0 (°/s).
    vitesse_deg_s: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier(self) -> "OrigineRotationTete":
        if self.avant_hall_deg <= self.precision_compte_tours_deg:
            raise ValueError(
                "avant_hall_deg doit dépasser precision_compte_tours_deg (sinon la recherche "
                "pourrait partir après le Hall et faire un tour de trop)"
            )
        return self


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
    zone_porte_bocal: ZonePorteBocalPrehension
    # Angle « méplats en face des mors en V » par rapport au Hall (°) : la tête se pose au
    # porte-bocal à angle_meplats_deg + k × 120°.
    angle_meplats_deg: float = 0.0
    # Écart permis entre l'angle enregistré et le compte-tours (°).
    ecart_compte_tours_max_deg: float = Field(default=30.0, gt=0)
    # Prise d'origine de la rotation (None : pas de prise d'origine de A par le Pi).
    origine_rotation: OrigineRotationTete | None = None

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
    # Jet d'air du col : centre du seau (axe de la tête) décalé de (dx, dy) du centre du fût de
    # lavage, face à la buse, son bord arrêté à jet_bord_z.
    jet_decalage: tuple[float, float]
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
    à la griffe et à la préhension pendant qu'elle pivote est « prehension → camera_dosage ».
    Pas de pivot pendant le demi-tour du bocal (décision du 01/11/2026, point 6)."""

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
    """Les positions interdites du chariot (fichier des positions, règles 2 à 14). Ces verrous
    ne protègent que la machine : la sécurité des personnes reste câblée. (La règle 1, anneaux
    du fût, est périmée et supprimée depuis le 31/10/2026.)"""

    # Règle 2 : barres entre les joues de l'élévateur (bande de hw) : plateau ≤ tant.
    joues_barres: Intervalle
    joues_plateau_max_z: float
    # Règle 3 : plateau au-dessus de tant : barres ouvertes (hw ≥ barres_ouvertes_min).
    barres_ouvertes_au_dessus_z: float
    barres_ouvertes_min: float
    # Règle 4 (règle 12 du fichier des positions, 31/10) : pousseur sorti à toute hauteur,
    # seulement barres ouvertes (barres_ouvertes_min) et bras du galet rangé : pas de chiffre.
    # Règle 5 : plateau au-dessus de tant seulement bras du galet rangé.
    galet_plateau_max_z: float
    # Règle 6 (spray, tâche 39) : plateau ≤ min(spray_plateau_max_z ; spray_bord_max_z − h),
    # entraxe des barres > spray_entraxe_min_m.
    spray_plateau_max_z: float
    spray_bord_max_z: float
    spray_entraxe_min_m: float = Field(gt=0)
    # Règle 8 (agitateur fixe, 01/11/2026) : en deçà du dosage (y < dosage_y, le poste), bord du
    # seau (plateau + h) ≤ poste_bord_max_z TOUJOURS (manivelle en bas : à 0,70 le seau touche).
    poste_bord_max_z: float
    # Règle 7 : plateau du fût pas en place : bout du chariot côté allée (y + bout_y_m) ≤
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


class BandeHautRemplissage(Modele):
    """Rangement sur la bande du haut (plateau du Stockage) : chariot à y, plateau à plateau_z,
    jamais hors de plateau_plage_z pendant la poussée ; le pousseur va jusqu'à pousseur_m."""

    y: float
    plateau_z: float
    plateau_plage_z: Intervalle
    pousseur_m: float


class RangementRemplissage(Modele):
    files: dict[Nom, FileRemplissage] = Field(default_factory=dict)
    # Bande du haut (None : pas de bande du haut).
    bande_haut: BandeHautRemplissage | None = None


class FormatRemplissage(Modele):
    """Ce que le Remplissage sait d'un format de seau (en plus de la table de la griffe)."""

    # Plateau à la pose du seau vide (dessus, m) : bord d'un seul seau sous la barrière.
    pose_plateau_z: float
    # Barres au contact du corps, sous le rebord (hw, m) : centrage en position.
    centrage_hw_m: float


class CouverclesRemplissage(Modele):
    """Mode couvercles (retourneur, tâche 21 bis) : chariot à y, plateau fixe, sans rotation.
    Règle 14 : pendant les demi-tours de la tête de la griffe, chariot à y ≥
    y_demi_tour_griffe_min ; il ne revient à y qu'après."""

    y: float
    plateau_z: float
    y_demi_tour_griffe_min: float


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
    # Positions en y : poste (spray, micropore ; sous le bocal du mycélium), dosage du mycélium,
    # recul (au moins) pour le demi-tour du bocal, vidage par la griffe (le seau vide y attend),
    # pose du seau vide et du couvercle.
    poste_y: float
    dosage_y: float
    ecarte_y: float
    vidage_y: float
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
    # Hauteur du plateau (dessus) pendant la lecture du QR du flanc par la caméra du micropore,
    # seau vide à la pose, avant le serrage des barres (fil Guidage caméra, 07/11/2026). None :
    # le plateau reste où la pose l'a laissé (valeur à venir du fil Micropore).
    plateau_lecture_qr: float | None = None
    # Où se fait la lecture (m, y du chariot) ; None : à la pose (pose_y). Jamais au poste (règle
    # C2 : 3 formats sur 4 y toucheraient le bord limite) : là où rien n'est au-dessus du seau.
    # `lecture_qr_bord_max_z` : limite du bord du seau à cette position (obligatoire avec
    # plateau_lecture_qr) ; vérifié au démarrage : plateau_lecture_qr + hauteur du seau.
    lecture_qr_y: float | None = None
    lecture_qr_bord_max_z: float | None = None
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
        intervalles = [("verrous → joues_barres", v.joues_barres)]
        bande = self.rangement.bande_haut
        if bande is not None:
            intervalles.append(("rangement → bande_haut → plateau_plage_z", bande.plateau_plage_z))
            debut, fin = bande.plateau_plage_z
            if not debut <= bande.plateau_z <= fin:
                erreurs.append(
                    f"rangement → bande_haut → plateau_z : {bande.plateau_z:g} hors de "
                    f"plateau_plage_z ({debut:g} à {fin:g})"
                )
        for nom, (debut, fin) in intervalles:
            if debut >= fin:
                erreurs.append(f"{nom} : du plus petit au plus grand")
        if self.couvercles.y_demi_tour_griffe_min < self.couvercles.y:
            erreurs.append("couvercles → y_demi_tour_griffe_min : au moins couvercles → y")
        if not self.poste_y < self.dosage_y < self.ecarte_y <= self.vidage_y:
            erreurs.append("poste_y < dosage_y < ecarte_y ≤ vidage_y : dans cet ordre")
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
    # L'axe de chaque pile de fin de lot à x ≥ pile_axe_x_min (règle de la caméra du bocal : il
    # faut pouvoir longer en −x la rangée y 0,215 avec l'axe à cette valeur ou plus).
    pile_axe_x_min: float


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
    # Une pile un peu hors de la course du chariot (rangée y 0,84, mâts jusqu'à 0,83) est prise
    # tête au bout de la course, à tant au plus de son axe (m) ; le seau tenu garde son axe.
    prise_hors_axe_max_m: float = Field(default=0.0, ge=0)


class TiroirStockage(Modele):
    """Tiroir du bas : les files du Remplissage, poussées vers +x jusqu'à la butée."""

    tole_z: float
    entree_x: float
    butee_x: float
    avance_par_seau_m: float = Field(gt=0)
    poussee_min_m: float = Field(gt=0)
    effort_n: Intervalle
    # Seuil de blocage du pousseur (N) : au-delà (courant ou écart du codeur), le Pi s'arrête et
    # alerte. Au-dessus de l'effort attendu.
    seuil_blocage_n: float = Field(gt=0)
    # Noms des files (remplissage → rangement → files), remplies dans cet ordre.
    files: list[Nom] = Field(min_length=1)
    # Seaux par file, par format.
    places: dict[Nom, dict[Nom, Annotated[int, Field(ge=0)]]] = Field(min_length=1)
    # Centres des places en x, par format et par file (facultatif : vérifiés au démarrage).
    centres_x: dict[Nom, dict[Nom, list[float]]] = Field(default_factory=dict)
    # Cales posées contre la butée, par format et par file (m) : la course du pousseur de cette
    # file est plus courte d'autant.
    cales: dict[Nom, dict[Nom, Annotated[float, Field(gt=0)]]] = Field(default_factory=dict)


class BandeHautStockage(Modele):
    """Bande du haut (seaux pleins poussés sur le plateau, tâche 35 bis) : entrée au bord de P1,
    fin de course logicielle (bord du seau à x ≤ bord_x_max), photo après chaque poussée."""

    active: bool = False
    y: float
    entree_x: float
    bord_x_max: float
    tolerance_y_m: float = Field(gt=0)
    # Centres des places en x, par format : du plus loin (1er seau poussé) au plus près (où
    # arrive le seau poussé).
    places: dict[Nom, list[float]] = Field(default_factory=dict)


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
    """Haut du seau tenu au-dessus de haut_max_z seulement axe y + rayon du bord ≤ bord_y_max."""

    bord_y_max: float
    haut_max_z: float


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
    # Capacité d'un lot (tiroir + bande du haut) par format, chiffres de l'étude : facultatif ;
    # vérifiée au démarrage contre les places.
    capacite_lot: dict[Nom, Annotated[int, Field(ge=1)]] = Field(default_factory=dict)
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
        if self.tiroir.seuil_blocage_n <= self.tiroir.effort_n[1]:
            erreurs.append("tiroir : seuil_blocage_n au-dessus de l'effort attendu (effort_n)")
        if self.tiroir.entree_x >= self.tiroir.butee_x:
            erreurs.append("tiroir : l'entrée (entree_x) avant la butée (butee_x)")
        if len(set(self.tiroir.files)) != len(self.tiroir.files):
            erreurs.append("tiroir → files : une file écrite deux fois")
        if self.boites.dessus_z <= self.boites.fond_z:
            erreurs.append("boites : le dessus (dessus_z) au-dessus du fond (fond_z)")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


def _places_en_ligne(
    quoi: str, centres: list[float], rayon: float, debut: float, fin: float
) -> list[str]:
    """Des seaux en ligne (centres en x, du plus loin au plus près) : du plus grand au plus
    petit, sans se chevaucher, tous entre debut et fin (bords des seaux)."""
    erreurs = []
    if not centres:
        return [f"{quoi} : aucune place"]
    for loin, pres in zip(centres, centres[1:], strict=False):
        if loin - pres < 2 * rayon - 1e-9:
            erreurs.append(
                f"{quoi} : les places {loin:g} et {pres:g} se chevauchent (seaux de rayon "
                f"{rayon:g})"
            )
    if centres[0] + rayon > fin + 1e-9:
        erreurs.append(
            f"{quoi} : le 1er seau ({centres[0]:g}) dépasse {fin:g} (bord à {centres[0] + rayon:g})"
        )
    if centres[-1] - rayon < debut - 1e-9:
        erreurs.append(f"{quoi} : la dernière place ({centres[-1]:g}) sort avant {debut:g}")
    return erreurs


# Les 4 axes du portique sur lesquels portent ses règles (le pont, le chariot, les deux Z).
AXES_PORTIQUE = ("pont_x", "chariot_y", "griffe_z", "prehension_z")
# Les places de photo du plafond, par zone photographiée (pont au bout opposé).
ZONES_PHOTO = ("fut_poste", "stockage")


class ChariotPortique(Modele):
    """Chariot Y du pont : son centre, et les deux mâts (griffe, préhension) décalés en y.
    L'axe chariot_y de machine.yaml est le y des mâts : centre = mâts − mats_moins_centre_y."""

    centre_y: Intervalle
    mats_moins_centre_y: float


class PlaqueZPortique(Modele):
    """Course du centre de la plaque Z d'un outil (haut = fin de course = origine), et l'axe
    de machine.yaml qui en donne la hauteur d'outil (axes de la griffe, face de la préhension)."""

    axe: Nom
    course: Intervalle


class VitessesPortique(Modele):
    """Vitesses (m/s) et accélérations (m/s²) du portique (décidées le 28/10/2026)."""

    xy_rapide_m_s: float = Field(gt=0)
    xy_approche_m_s: float = Field(gt=0)
    xy_acceleration_vide_m_s2: float = Field(gt=0)
    xy_acceleration_seau_m_s2: float = Field(gt=0)
    z_rapide_m_s: float = Field(gt=0)
    z_approche_m_s: float = Field(gt=0)
    z_acceleration_m_s2: float = Field(gt=0)
    # Photo prise à l'arrêt, après ce temps (s).
    photo_apres_arret_s: float = Field(ge=0)

    @model_validator(mode="after")
    def _verifier(self) -> "VitessesPortique":
        erreurs = []
        if self.xy_approche_m_s > self.xy_rapide_m_s:
            erreurs.append("xy_approche_m_s doit être au plus xy_rapide_m_s")
        if self.z_approche_m_s > self.z_rapide_m_s:
            erreurs.append("z_approche_m_s doit être au plus z_rapide_m_s")
        if self.xy_acceleration_seau_m_s2 > self.xy_acceleration_vide_m_s2:
            erreurs.append("xy_acceleration_seau_m_s2 doit être au plus xy_acceleration_vide_m_s2")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class PlenumPortique(Modele):
    """Plénum du Nettoyage : préhension au-dessus de plaque_z_min (centre de sa plaque Z) ⇒
    chariot (son centre) à y ≤ chariot_centre_y_max. Vérifié sur toute la course au démarrage."""

    plaque_z_min: float
    chariot_centre_y_max: float


class BoutBloqueGriffe(Modele):
    """Pont dans cette bande de x (et axes de la tête sous axes_z_max, s'il est donné) : tête
    de la griffe à l'un de ces angles seulement (aucun : interdit)."""

    pont_x: Intervalle
    axes_z_max: float | None = None
    angles_deg: list[float] = Field(default_factory=list)


class ChainePrehension(Modele):
    """Chaîne Z de la préhension : plaque Z au-dessus de plaque_z_min ⇒ mâts à y ≤ mat_y_max
    (sinon le brin de la chaîne touche le plénum du Nettoyage ; Préhension +22 cm, 04/11)."""

    plaque_z_min: float
    mat_y_max: float


class Portique(Modele):
    """Le portique : pont (2 moteurs X1 et X2), chariot Y, Z de la griffe et de la préhension.

    Fiche du module « Portique », gelé le 28/10/2026, et fichier du fil Portique (01/11).
    Repère du portique, en mètres. Les positions nommées citées ici sont dans « positions »."""

    exemple: bool = False
    chariot: ChariotPortique
    plaques_z: dict[Nom, PlaqueZPortique] = Field(min_length=1)
    # Prise d'origine, dans l'ordre : les axes d'un groupe ensemble (« $H » et leurs lettres, sur
    # chacune de leurs cartes), le groupe suivant quand il est fini. Vérifié : les Z avant Y,
    # Y avant X.
    origine: list[Annotated[list[Nom], Field(min_length=1)]] = Field(min_length=1)
    vitesses: VitessesPortique
    # Les deux outils en haut (position nommée : griffe_z et prehension_z en haut de course).
    outils_en_haut: Nom
    # Garage de repos (arrêt, nuit, ozone) : position nommée du pont et du chariot ; les Z sont
    # d'abord montés (outils_en_haut), les freins serrés à la fin.
    garage: Nom
    # Photo du plafond, par zone photographiée : position nommée du pont (au bout opposé).
    photo: dict[Nom, Nom]
    # Écart permis entre le pont et sa place de photo (m).
    photo_tolerance_m: float = Field(gt=0)
    plenum: PlenumPortique
    # Chaîne Z de la préhension (None : pas de règle).
    chaine_prehension: ChainePrehension | None = None
    # Face de la préhension sous tete_basse_z ⇒ accélération X et Y × ce facteur (mât souple),
    # en plus de la règle « seau tenu ». None : pas de réduction.
    tete_basse_z: float | None = None
    facteur_acceleration_tete_basse: float = Field(default=1.0, gt=0, le=1)
    # Griffe : bandes du pont où la tête reste à un angle permis (pas de rotation).
    bouts_bloques_griffe: list[BoutBloqueGriffe] = Field(default_factory=list)

    def face_max_chaine(self, mats_y: float, bas_face_z: float) -> float | None:
        """La face de la préhension la plus haute permise par la chaîne Z, mâts à mats_y
        (bas_face_z : le bas de la course de la face, qui va avec le bas de la plaque Z) ; None :
        pas de limite."""
        chaine = self.chaine_prehension
        plaque = self.plaques_z.get("prehension")
        if chaine is None or plaque is None or mats_y <= chaine.mat_y_max + 1e-6:
            return None
        return chaine.plaque_z_min - plaque.course[0] + bas_face_z

    def refus_chaine(self, mats_y: float, face_z: float, bas_face_z: float) -> str | None:
        """Raison du refus de la chaîne Z (face de la préhension à face_z, mâts à mats_y ;
        bas_face_z : le bas de la course de la face), ou None."""
        maximum = self.face_max_chaine(mats_y, bas_face_z)
        if maximum is None:
            return None
        if face_z <= maximum + 1e-6:
            return None
        chaine = self.chaine_prehension
        assert chaine is not None
        return (
            f"chaîne Z de la préhension : face à {face_z:.3f} m (plaque Z au-dessus de "
            f"{chaine.plaque_z_min:g}) avec les mâts à y {mats_y:.3f} m : il faut y ≤ "
            f"{chaine.mat_y_max:g} m, ou la face au plus à {maximum:.3f} m (le brin de la chaîne "
            "toucherait le plénum du Nettoyage)"
        )

    @model_validator(mode="after")
    def _verifier(self) -> "Portique":
        manquent = [zone for zone in ZONES_PHOTO if zone not in self.photo]
        if manquent:
            raise ValueError(f"photo : il manque {', '.join(manquent)}")
        return self


# ------------------------------------------------------------------ nettoyage


class Boite(Modele):
    """Une boîte dans le repère du portique : [min, max] sur chaque axe (m)."""

    x: Intervalle
    y: Intervalle
    z: Intervalle

    @model_validator(mode="after")
    def _dans_l_ordre(self) -> "Boite":
        for axe, (debut, fin) in (("x", self.x), ("y", self.y), ("z", self.z)):
            if debut >= fin:
                raise ValueError(f"sur {axe}, aller du plus petit au plus grand")
        return self


class EnceinteGeometrie(Modele):
    interieur: Boite
    exterieur: Boite
    sol_pvc_dessus_z: float
    dos_ane: Boite
    # Centres (x, y) des bondes du sol.
    bondes: list[tuple[float, float]] = Field(default_factory=list)
    bonde_diametre_m: float = Field(gt=0)


class TubeStore(Modele):
    x: Intervalle
    y: float
    z: float


class MoteurStore(Modele):
    cote: Literal["portes", "fut"]
    x: Intervalle
    tension_v: float = Field(gt=0)


class StoreGeometrie(Modele):
    tube_axe: TubeStore
    moteur: MoteurStore
    nappe_plan_y: float
    # Barre basse posée sur le seuil (fin de course basse du moteur).
    barre_basse_ferme_z: Intervalle
    # Dessous de la barre basse, store en haut (fin de course haute du moteur).
    barre_basse_ouvert_z_bas: float
    course_m: float = Field(gt=0)
    coffre: Boite
    reed_bas: Boite
    verrous: Boite
    # Ni bord sensible ni cellule (Karulium, 01/11) : la commande maintenue câblée protège.
    securite_anti_ecrasement: Literal["commande_maintenue"]


class PlenumGeometrie(Modele):
    boite: Boite
    fente_soufflage: Boite
    entree_gaine_x: float
    generateur_ozone: Boite


class VentilateurGeometrie(Modele):
    centre_x: float
    centre_z: float


class RepriseAirGeometrie(Modele):
    grille: Boite
    caisson_filtrant: Boite
    boite_hepa: Boite
    ventilateur: VentilateurGeometrie


class RubansLed(Modele):
    cote_mur: Boite
    cote_facade: Boite


class GeometrieNettoyage(Modele):
    """Chiffres figés de l'enceinte propre (validés par Karulium le 04/11/2026) : le Pi ne fait
    bouger aucun de ces éléments ; ils sont gardés ici pour les autres modules et les essais."""

    enceinte: EnceinteGeometrie
    store: StoreGeometrie
    plenum: PlenumGeometrie
    reprise_air: RepriseAirGeometrie
    rubans_led: RubansLed
    capteurs: dict[Nom, Boite] = Field(default_factory=dict)


class StoreNettoyage(Modele):
    """Ce que le Pi fait du store (il ne commande pas son moteur : commande maintenue câblée)."""

    # « store_ferme » vrai depuis ce temps (s) pour le croire (le reed peut rebondir).
    stabilite_s: float = Field(gt=0)
    # Durée d'une montée ou d'une descente (s), pour information.
    mouvement_s: float = Field(gt=0)
    # Après une demande de fermeture, store toujours pas fermé au bout de ce temps (s) : alerte.
    alerte_fermeture_s: float = Field(gt=0)
    # Verrous libérés et store jamais ouvert au bout de ce temps (s) : verrous remis.
    deverrouille_max_s: float = Field(gt=0)


class PurgeNettoyage(Modele):
    """Purge après fermeture du store (règle du 12/10, figée)."""

    duree_min_s: float = Field(gt=0)
    alerte_s: float = Field(gt=0)
    # particules_dedans ≤ ce rapport × particules_dehors, stable pendant stabilite_particules_s.
    rapport_particules_max: float = Field(gt=0)
    stabilite_particules_s: float = Field(gt=0)
    # Surpression de l'enceinte pour finir la purge (Pa), sans ou avec balais au store.
    pression_fin_pa: float = Field(gt=0)
    pression_fin_balais_pa: float = Field(gt=0)
    balais: bool = False
    # Surpression normale, purge finie (Pa) : pour information.
    pression_normale_pa: Intervalle

    @property
    def pression_fin(self) -> float:
        return self.pression_fin_balais_pa if self.balais else self.pression_fin_pa


class VentilateurNettoyage(Modele):
    """Consigne 0-10 V du moteur EC (il s'arrête sans signal) : 3 niveaux (V)."""

    arret_v: float = Field(ge=0, le=10)
    normal_v: float = Field(ge=0, le=10)
    plein_v: float = Field(ge=0, le=10)


class OzoneNettoyage(Modele):
    """La nuit UV-ozone (personne présent). La sécurité ozone reste câblée."""

    # Ozone dedans sous ce seuil (ppm), stable stabilite_retour_s : fin de la nuit, ouverture.
    seuil_ouverture_ppm: float = Field(gt=0)
    stabilite_retour_s: float = Field(gt=0)
    # Ozone dehors au-dessus (ppm) : fuite (alerte forte, générateur coupé).
    seuil_fuite_ppm: float = Field(gt=0)
    # Comptés depuis le départ de la nuit (s) : génération, fin du contact, retour au plus tard.
    t_generation_s: float = Field(gt=0)
    t_contact_s: float = Field(gt=0)
    t_max_retour_s: float = Field(gt=0)
    # Heure de départ réglée (« 22:00 »).
    heure_depart: Annotated[str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]
    # ozone_dedans noté au registre tous les combien (s).
    journal_s: float = Field(gt=0)
    # Au moins cette valeur (ppm) lue dedans pendant le contact, sinon « mesure incohérente ».
    attendu_min_ppm: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier(self) -> "OzoneNettoyage":
        if not self.t_generation_s < self.t_contact_s < self.t_max_retour_s:
            raise ValueError(
                "il faut t_generation_s < t_contact_s < t_max_retour_s (comptés depuis le départ)"
            )
        return self


class UvTetes(Modele):
    """Lampe UV-C des têtes : garage UV après le bain des têtes (figé : 5 + 5 min)."""

    garage_s: list[Annotated[float, Field(gt=0)]] = Field(min_length=1)


class Nettoyage(Modele):
    """Nettoyage : enceinte, store, air, UV, ozone (module gelé le 28/10/2026, regelé le
    04/11/2026). Le Pi lit et attend ; la sécurité est câblée (store dans la boucle d'arrêt du
    portique, chaîne UV-ozone, verrous fermés sans courant, alarme d'ozone câblée)."""

    # Vrai tant que des chiffres sont des exemples (durées de l'ozone, heure, ventilateur...).
    exemple: bool = False
    # Relit ses signaux tous les combien (s).
    periode_s: float = Field(gt=0)
    geometrie: GeometrieNettoyage
    store: StoreNettoyage
    purge: PurgeNettoyage
    ventilateur: VentilateurNettoyage
    ozone: OzoneNettoyage
    uv_tetes: UvTetes

    @model_validator(mode="after")
    def _verifier(self) -> "Nettoyage":
        erreurs = []
        v = self.ventilateur
        if not v.arret_v < v.normal_v < v.plein_v:
            erreurs.append("ventilateur : il faut arret_v < normal_v < plein_v (entre 0 et 10 V)")
        purge = self.purge
        if purge.duree_min_s >= purge.alerte_s:
            erreurs.append("purge : duree_min_s doit être plus courte que alerte_s")
        if purge.stabilite_particules_s > purge.alerte_s:
            erreurs.append("purge : stabilite_particules_s plus longue que alerte_s")
        bas, haut = purge.pression_normale_pa
        if bas > haut:
            erreurs.append("purge → pression_normale_pa : aller du plus petit au plus grand")
        if purge.pression_fin_balais_pa > purge.pression_fin_pa:
            erreurs.append("purge : pression_fin_balais_pa doit être au plus pression_fin_pa")
        store = self.geometrie.store
        course = store.barre_basse_ouvert_z_bas - store.barre_basse_ferme_z[0]
        if abs(course - store.course_m) > 0.005:
            erreurs.append(
                f"geometrie → store : course_m {store.course_m:g} m, mais la barre basse va de "
                f"{store.barre_basse_ferme_z[0]:g} à {store.barre_basse_ouvert_z_bas:g} "
                f"({course:.3f} m)"
            )
        if store.barre_basse_ferme_z[0] >= store.barre_basse_ferme_z[1]:
            erreurs.append("geometrie → store → barre_basse_ferme_z : du plus petit au plus grand")
        if self.store.alerte_fermeture_s < self.store.mouvement_s:
            erreurs.append("store : alerte_fermeture_s plus courte que la descente (mouvement_s)")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class BrasSpray(Modele):
    """Bras de la buse du spray (fiche v5.8) : 0° = rangé (capteur), butée logicielle."""

    # Axe du pivot (x, y), vertical. Figé (v5.8).
    axe_xy: tuple[float, float]
    course_deg: Intervalle
    # Angle du bras au-dessus de chaque format de seau (Maquette v45.103).
    angles: dict[Nom, float] = Field(min_length=1)
    # Écart accepté entre l'angle demandé et l'angle dit par la carte.
    tolerance_deg: float = Field(gt=0)
    vitesse_deg_s: float = Field(gt=0)
    # Temps maximum pour sortir, ranger ou prendre l'origine (la carte s'arrête et le dit).
    temps_max_s: float = Field(gt=0)
    courant_a: float = Field(gt=0)


class DoseSpray(Modele):
    """Dose de culture d'un seau : le poids perdu par le flacon, mesuré par sa balance."""

    # Dose de chaque format (g ; densité ≈ 1).
    par_format_g: dict[Nom, Annotated[float, Field(gt=0)]] = Field(min_length=1)
    # Emplacement (flacon 1 à 4) de chaque format, en attendant la règle du logiciel de culture.
    emplacement_par_format: dict[Nom, Annotated[int, Field(ge=1, le=4)]] = Field(min_length=1)
    tolerance_trop_forte_g: float = Field(gt=0)
    temps_max_pompage_s: float = Field(gt=0)
    air_avant_s: float = Field(gt=0)
    chasse_s: float = Field(gt=0)
    air_apres_s: float = Field(gt=0)
    # Le seau tourne pendant le spray (°).
    rotation_seau_deg: float = Field(gt=0)
    # Ajoutée à la première dose après un changement de flacon (le tube neuf est vide).
    amorce_g: float = Field(ge=0)


class FlaconsSpray(Modele):
    """Les 4 flacons (500 ml au plus), chacun sur sa balance."""

    contenu_max_g: float = Field(gt=0)
    # Poids de chaque flacon vide (g), emplacements 1 à 4 (tare à enregistrer).
    vide_g: dict[Annotated[int, Field(ge=1, le=4)], Annotated[float, Field(ge=0)]]
    # Pas de dose si le flacon descendrait sous « vide + réserve ».
    reserve_g: float = Field(gt=0)
    # Alerte « cartouche bientôt vide » sous ce nombre de doses restantes.
    alerte_doses_restantes: int = Field(ge=1)
    # Le poids d'un emplacement monte d'au moins ça : nouvelle cartouche ?
    changement_min_g: float = Field(gt=0)

    @model_validator(mode="after")
    def _quatre(self) -> "FlaconsSpray":
        if sorted(self.vide_g) != [1, 2, 3, 4]:
            raise ValueError("vide_g : il faut le poids à vide des 4 emplacements (1 à 4)")
        return self


class AgitateursSpray(Modele):
    """Une seule sortie PWM pour les 4 agitateurs."""

    vitesse_pct: int = Field(gt=0, le=100)
    avant_dose_s: float = Field(gt=0)
    # 1 min toutes les 15 min (en dehors des doses).
    periode_s: float = Field(gt=0)
    duree_s: float = Field(gt=0)


class NettoyageSpray(Modele):
    """Nettoyage des tubes (fin de journée) à l'alcool à 70 %."""

    pompe_s: float = Field(gt=0)
    sechage_s: float = Field(gt=0)
    alcool_par_nettoyage_ml: float = Field(gt=0)
    flacon_alcool_ml: float = Field(gt=0)
    # Alerte « alcool à remettre » sous ce nombre de nettoyages restants.
    alerte_nettoyages_restants: int = Field(ge=0)


class LiaisonSpray(Modele):
    """Liaison avec la carte n° 5 (Modbus, bus rs485_spray)."""

    # Le Pi bat au moins tous les ... (s) pendant un geste du spray.
    battement_s: float = Field(gt=0)
    # La carte s'arrête seule (pompe, air, bras rangé) si le Pi se tait plus de ... (s).
    silence_max_s: float = Field(gt=0)
    # Plus de réponse valable depuis ... (s) : carte « muette » (bras supposé sorti).
    muette_s: float = Field(gt=0)

    @model_validator(mode="after")
    def _battre_assez(self) -> "LiaisonSpray":
        if self.battement_s * 2 > self.silence_max_s:
            raise ValueError(
                "liaison : battement_s doit valoir au plus la moitié de silence_max_s (sinon la "
                "carte s'arrêterait au moindre retard)"
            )
        return self


# Broches de l'ESP32-S3 de la carte n° 5 du spray (exemple : ESP32-S3-DevKitC-1, module N8) : 0 à
# 48, sans celles qui n'existent pas (22 à 25) ni celles qui servent déjà à la carte.
BROCHES_INTERDITES_ESP32S3 = {
    0: "démarrage (bouton BOOT)",
    3: "démarrage (JTAG)",
    19: "USB",
    20: "USB",
    **{broche: "n'existe pas sur l'ESP32-S3" for broche in range(22, 26)},
    **{broche: "mémoire flash" for broche in range(26, 33)},
    **{
        broche: "mémoire PSRAM de certaines cartes, ou absente du module"
        for broche in range(33, 38)
    },
    43: "fenêtre texte (UART0)",
    44: "fenêtre texte (UART0)",
    45: "démarrage (tension de la flash)",
    46: "démarrage (messages au démarrage)",
}
BrocheEsp32s3 = Annotated[int, Field(ge=0, le=48)]
# Micro-pas que le pilote TMC2209 du bras sait faire (réglés par son UART).
MICRO_PAS_TMC2209 = (1, 2, 4, 8, 16, 32, 64, 128, 256)


class BrochesCarteSpray(Modele):
    """Broches de l'ESP32-S3 de la carte n° 5 (numéros GPIO). EXEMPLES jusqu'à l'Implantation."""

    # L'émetteur-récepteur RS485 3,3 V (MAX3485) : DI, RO, et DE et /RE reliées (1 = parler).
    rs485_tx: BrocheEsp32s3
    rs485_rx: BrocheEsp32s3
    rs485_sens: BrocheEsp32s3
    # UART du pilote TMC2209 du bras (fil PDN_UART : RX direct, TX par une résistance de 1 kΩ).
    pilote_bras_tx: BrocheEsp32s3
    pilote_bras_rx: BrocheEsp32s3
    # Pas et sens du moteur du bras.
    bras_pas: BrocheEsp32s3
    bras_sens: BrocheEsp32s3
    # EN des 5 pilotes TMC2209 (bras et 4 pompes), reliés ensemble : 0 = moteurs alimentés.
    activer_moteurs: BrocheEsp32s3
    # Pas des 4 pompes (emplacements 1 à 4), pilotes TMC2209 en pas/direction.
    pompes_pas: tuple[BrocheEsp32s3, BrocheEsp32s3, BrocheEsp32s3, BrocheEsp32s3]
    # Sens des 4 pompes, une broche pour les 4. null : sens câblé en dur sur les pilotes (une pompe
    # péristaltique ne tourne que dans un sens).
    pompes_sens: BrocheEsp32s3 | None = None
    # Les 4 HX711 des balances (emplacements 1 à 4) : DT et SCK de chacun.
    hx711_dt: tuple[BrocheEsp32s3, BrocheEsp32s3, BrocheEsp32s3, BrocheEsp32s3]
    hx711_sck: tuple[BrocheEsp32s3, BrocheEsp32s3, BrocheEsp32s3, BrocheEsp32s3]
    # Capteur du bras rangé, par l'optocoupleur PC817 : bras rangé = broche à 0 (logique inversée).
    bras_spray_range: BrocheEsp32s3
    # Sorties MOSFET 24 V (1 = allumée), chacune avec 10 kΩ vers le 0 V (éteinte au démarrage).
    ev_buse_spray: BrocheEsp32s3
    ev_chasse_spray: BrocheEsp32s3
    agitateurs_spray: BrocheEsp32s3  # en PWM, une seule sortie pour les 4
    pompe_nettoyage_spray: BrocheEsp32s3
    # Petit voyant de la carte. null : pas de voyant.
    voyant: BrocheEsp32s3 | None = None

    @model_validator(mode="after")
    def _verifier(self) -> "BrochesCarteSpray":
        erreurs = []
        deja_vues: dict[int, str] = {}
        for nom, valeur in self.model_dump().items():
            liste = valeur if isinstance(valeur, list | tuple) else [valeur]
            for numero, broche in enumerate(liste, start=1):
                if broche is None:
                    continue
                quoi = f"{nom} n° {numero}" if isinstance(valeur, list | tuple) else nom
                if broche in BROCHES_INTERDITES_ESP32S3:
                    erreurs.append(
                        f"{quoi} ({broche}) : broche de l'ESP32-S3 réservée "
                        f"({BROCHES_INTERDITES_ESP32S3[broche]})"
                    )
                autre = deja_vues.setdefault(broche, quoi)
                if autre != quoi:
                    erreurs.append(f"la broche {broche} est prise deux fois ({autre} et {quoi})")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class MoteurBrasCarteSpray(Modele):
    """Le moteur du bras (NEMA 17 sur TMC2209 en UART) vu par la carte."""

    # Pas entiers par tour du moteur (200 pour un 17HS4401, 1,8° par pas).
    pas_par_tour: int = Field(gt=0, le=1000)
    micro_pas: int
    # Tours du moteur pour un tour du bras (1 : bras sur l'axe du moteur). EXEMPLE.
    rapport: float = Field(gt=0, le=100)
    acceleration_deg_s2: float = Field(gt=0)
    # Pour « ranger », la carte va au plus jusqu'à ... (°) au-delà de 0 pour trouver le capteur.
    depassement_max_deg: float = Field(gt=0, le=30)
    # Le sens de rotation du moteur est inversé (broche « bras_sens » à 1 pour sortir).
    sens_inverse: bool = False
    # Capteur vu ou perdu pendant ce temps (ms) avant d'y croire (« bras poussé »).
    filtre_capteur_ms: int = Field(ge=0, le=500)
    # Résistance de mesure du courant sur la carte du pilote (Ω ; 0,11 sur la plupart).
    resistance_mesure_ohm: float = Field(gt=0, le=1)
    # Courant à l'arrêt, en % du courant de marche (bras.courant_a).
    maintien_pct: int = Field(ge=0, le=100)
    # Adresse du pilote sur son UART (broches MS1 et MS2 du pilote : 0 à 3) et vitesse.
    adresse_uart: int = Field(ge=0, le=3)
    vitesse_uart_bauds: int = Field(ge=9600, le=500000)
    # Le pilote est relu tous les ... (ms) : pas de réponse = erreur « pilote du bras ».
    lecture_pilote_ms: int = Field(ge=100, le=60000)

    @model_validator(mode="after")
    def _verifier(self) -> "MoteurBrasCarteSpray":
        if self.micro_pas not in MICRO_PAS_TMC2209:
            raise ValueError(
                f"micro_pas ({self.micro_pas}) : le TMC2209 ne sait faire que "
                + ", ".join(str(n) for n in MICRO_PAS_TMC2209)
            )
        pas = self.pas_par_tour * self.micro_pas * self.rapport
        if abs(pas - round(pas)) > 1e-6:
            raise ValueError(
                f"pas_par_tour × micro_pas × rapport ({pas:g}) doit faire un nombre entier de "
                "pas par tour du bras"
            )
        return self

    @property
    def pas_par_tour_bras(self) -> int:
        return round(self.pas_par_tour * self.micro_pas * self.rapport)


class PompesCarteSpray(Modele):
    """Les 4 pompes péristaltiques (NEMA 17 sur TMC2209 en pas/direction ; micro-pas et courant
    réglés sur chaque pilote : broches MS1/MS2 et potentiomètre)."""

    vitesse_pas_s: int = Field(gt=0)
    acceleration_pas_s2: int = Field(gt=0)
    # Niveau de la broche pompes_sens pour pomper (si elle existe).
    sens_inverse: bool = False


class BalancesCarteSpray(Modele):
    """Les 4 HX711 des balances des flacons (étalonnage : pesees.yaml → balances_spray)."""

    # Cadence du HX711, choisie sur sa carte par la broche RATE (au 3,3 V : 80). Sert à vérifier
    # les autres chiffres.
    mesures_par_seconde: Literal[10, 80]
    # Le poids est la moyenne des ... dernières mesures.
    moyenne_de: int = Field(ge=1, le=16)
    # Plus de mesure depuis ce temps (ms) : balance muette.
    sans_mesure_ms: int = Field(ge=20, le=10000)
    # Entre la plus petite et la plus grande des dernières mesures, plus que ça (g) : instable.
    instable_g: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier(self) -> "BalancesCarteSpray":
        periode_ms = 1000 / self.mesures_par_seconde
        if self.sans_mesure_ms < 3 * periode_ms:
            raise ValueError(
                f"sans_mesure_ms ({self.sans_mesure_ms}) doit valoir au moins 3 fois le temps "
                f"entre deux mesures du HX711 ({periode_ms:g} ms)"
            )
        return self


class CarteSpray(Modele):
    """Programme de la carte ESP32 n° 5 (tâche 39 bis, dossier spray/). Copié dans le programme
    quand on le fabrique, avec le reste de « spray » et pesees.yaml → balances_spray."""

    broches: BrochesCarteSpray
    voyant_actif_bas: bool = False
    moteur_bras: MoteurBrasCarteSpray
    pompes: PompesCarteSpray
    balances: BalancesCarteSpray
    # Fréquence du PWM des agitateurs (Hz).
    agitateurs_pwm_hz: int = Field(ge=100, le=40000)
    # Le générateur de pas tourne toutes les ... (µs) : au plus un pas tous les 2 tours.
    periode_pas_us: int = Field(ge=20, le=1000)
    # Attente avant de répondre (µs), le temps que l'adaptateur du Pi repasse en écoute.
    delai_avant_reponse_us: int = Field(ge=0, le=1000)
    # Programme figé plus longtemps que ça (ms) : la carte redémarre.
    chien_de_garde_ms: int = Field(ge=100, le=60000)
    # Fenêtre texte sur le câble USB (essais) : une ligne d'état tous les ... (ms).
    periode_affichage_ms: int = Field(ge=100, le=600000)

    @property
    def pas_max_par_s(self) -> float:
        return 1_000_000 / (2 * self.periode_pas_us)


class Spray(Modele):
    """Spray (fiche v5.8 du 01/11/2026, module gelé) : carte ESP32 n° 5, 4 flacons pesés, bras
    pivotant. Le spray ne protège personne : la règle du bras (règle 6) protège la machine."""

    exemple: bool = False
    signal: Nom
    bras: BrasSpray
    dose: DoseSpray
    flacons: FlaconsSpray
    agitateurs: AgitateursSpray
    nettoyage: NettoyageSpray
    liaison: LiaisonSpray
    # Programme de la carte n° 5 (None : pas de programme à fabriquer, pour des réglages d'essai).
    carte: CarteSpray | None = None

    @model_validator(mode="after")
    def _verifier(self) -> "Spray":
        erreurs = []
        debut, fin = self.bras.course_deg
        if not 0 <= debut < fin <= 110:
            erreurs.append("bras → course_deg : entre 0 et 110°, du plus petit au plus grand")
        for nom, angle in self.bras.angles.items():
            if not debut < angle <= fin:
                erreurs.append(
                    f"bras → angles → {nom} : {angle:g}° hors de la course du bras "
                    f"({debut:g} à {fin:g}°)"
                )
        if self.flacons.reserve_g >= self.flacons.contenu_max_g:
            erreurs.append("flacons : reserve_g doit être plus petite que contenu_max_g")
        for nom, dose in self.dose.par_format_g.items():
            if dose + self.dose.amorce_g >= self.flacons.contenu_max_g - self.flacons.reserve_g:
                erreurs.append(f"dose → par_format_g → {nom} : plus grande qu'un flacon plein")
        if self.carte is not None:
            erreurs += self._verifier_carte(self.carte)
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self

    def _verifier_carte(self, carte: CarteSpray) -> list[str]:
        """Les chiffres de la carte n° 5 vont avec ceux du bras et des gestes."""
        erreurs = []
        debut, fin = self.bras.course_deg
        if debut != 0:
            erreurs.append("bras → course_deg : la carte compte depuis 0° (bras rangé, capteur)")
        # Toute la course, avec la montée et la descente en vitesse.
        vitesse, acceleration = self.bras.vitesse_deg_s, carte.moteur_bras.acceleration_deg_s2
        course = fin - debut
        if course >= vitesse**2 / acceleration:
            duree = course / vitesse + vitesse / acceleration
        else:
            duree = 2 * math.sqrt(course / acceleration)
        if duree >= self.bras.temps_max_s:
            erreurs.append(
                f"bras → temps_max_s ({self.bras.temps_max_s:g} s) : le bras n'a pas le temps de "
                f"faire toute sa course ({course:g}° en {duree:.2f} s à {vitesse:g} °/s)"
            )
        pas_deg = carte.moteur_bras.pas_par_tour_bras / 360
        vitesse_bras = self.bras.vitesse_deg_s * pas_deg
        for quoi, vitesse in (
            ("bras → vitesse_deg_s", vitesse_bras),
            ("carte → pompes → vitesse_pas_s", carte.pompes.vitesse_pas_s),
        ):
            if vitesse > carte.pas_max_par_s:
                erreurs.append(
                    f"{quoi} : {vitesse:g} pas/s, plus que ce que fait le générateur de pas "
                    f"({carte.pas_max_par_s:g} pas/s avec periode_pas_us "
                    f"{carte.periode_pas_us})"
                )
        if self.bras.tolerance_deg * pas_deg < 1:
            erreurs.append(
                "bras → tolerance_deg : plus petite qu'un pas du moteur du bras (augmenter les "
                "micro-pas ou la tolérance)"
            )
        if self.liaison.silence_max_s * 1000 <= carte.chien_de_garde_ms:
            erreurs.append(
                "carte → chien_de_garde_ms doit être plus court que liaison → silence_max_s"
            )
        try:
            courants_tmc2209(self.bras.courant_a, carte.moteur_bras)
        except ValueError as erreur:
            erreurs.append(str(erreur))
        return erreurs


# Pleine échelle du courant du TMC2209 (V aux bornes de la résistance de mesure), selon VSENSE.
TENSION_PLEINE_ECHELLE_TMC2209 = {0: 0.325, 1: 0.180}


def courants_tmc2209(courant_a: float, moteur: MoteurBrasCarteSpray) -> tuple[int, int, int]:
    """(VSENSE, IRUN, IHOLD) du pilote TMC2209 pour ce courant (A efficaces), d'après sa notice :
    I = (CS + 1) / 32 × V / (R + 0,02 Ω) / √2. Le courant obtenu ne dépasse jamais celui demandé.
    ValueError si le pilote ne peut pas le donner avec cette résistance de mesure."""
    resistance = moteur.resistance_mesure_ohm + 0.02
    # D'abord la petite échelle (VSENSE 1), plus fine, si elle suffit.
    for vsense in (1, 0):
        tension = TENSION_PLEINE_ECHELLE_TMC2209[vsense]
        cs = math.floor(32 * math.sqrt(2) * courant_a * resistance / tension + 1e-9) - 1
        if 0 <= cs <= 31:
            ihold = math.floor((cs + 1) * moteur.maintien_pct / 100 + 1e-9) - 1
            return vsense, cs, max(ihold, 0)
    raise ValueError(
        f"bras → courant_a ({courant_a:g} A) : le pilote TMC2209 ne peut pas le donner avec une "
        f"résistance de mesure de {moteur.resistance_mesure_ohm:g} Ω"
    )


# ------------------------------------------------------------- micropore (tâche 40)


class RangeeMicropore(Modele):
    """Une rangée de trous d'un format de seau : sa hauteur (centre des trous, au-dessus du fond
    du seau), le rayon de la paroi à cette hauteur et le nombre de trous attendus. La vraie carte
    des trous vient de la caméra, seau par seau."""

    hauteur_m: float = Field(gt=0)
    rayon_paroi_m: float = Field(gt=0)
    trous: int = Field(ge=1, le=12)
    # Rangée du fond : posée seulement quand la balance voit assez de substrat dans le seau (le
    # seau ne glisse pas sous l'appui), au vidage (le bord y dépasse 0,68).
    fond: bool = False


class FormatMicropore(Modele):
    """Les rangées de trous d'un format de seau (de haut en bas)."""

    rangees: list[RangeeMicropore] = Field(min_length=1)
    # Rangée du fond : substrat (kg) qu'il faut dans le seau, à la place de fond_poids_min_kg.
    fond_poids_min_kg: float | None = Field(default=None, gt=0)


class TofMicropore(Modele):
    """Le capteur de distance VL6180X qui vise l'équerre cible : la position de la tête (mm)."""

    # Tête escamotée : ≈ 77 mm ; tête en butée : ≈ 8 mm (figés).
    escamotee_mm: float = Field(gt=0)
    butee_mm: float = Field(gt=0)
    # Vue escamotée si la distance est au moins escamotee_mm − tant (précision 1 à 2 mm).
    tolerance_escamotee_mm: float = Field(gt=0)
    # Contact vu : la distance ne baisse plus que de tant au plus entre l'approche et l'appui.
    contact_ecart_max_mm: float = Field(gt=0)
    # Précision d'une mesure (mm).
    precision_mm: float = Field(gt=0)
    # Une mesure plus vieille que ça n'est pas prise (ms : âge dit par la carte).
    age_max_ms: int = Field(gt=0)
    # La dernière lecture du Pi ne compte plus après ce temps (s).
    fraicheur_s: float = Field(gt=0)


class ServosMicropore(Modele):
    """Les deux servos de la tête, sur la PCA9685 de la carte du plateau."""

    # Course de la tête (mm) par degré du servo d'escamotage, près du contact ; +1 : un angle
    # plus grand avance la tête vers la paroi (−1 : il la recule).
    mm_par_degre: float = Field(gt=0)
    sens_avance: Literal[-1, 1]
    # Temps laissé au servo d'escamotage pour aller à son angle (s).
    mouvement_s: float = Field(gt=0)
    # Lame (MG90S) : angle de repos (lame haute), angle bas (ruban coupé), temps par sens (s).
    lame_repos_deg: float
    lame_bas_deg: float
    lame_s: float = Field(gt=0)
    # Après un redémarrage de la carte (servos relâchés) : le ToF ne compte qu'après ce temps (s).
    stabilisation_s: float = Field(gt=0)
    # Le Pi renvoie les angles au moins tous les tant (s) : la carte veut un ordre toutes les 2 s.
    battement_s: float = Field(gt=0)
    # La tête n'est pas vue escamotée au bout de ce temps (s) : le plateau ne bouge pas, alerte.
    attente_max_s: float = Field(gt=0)
    # Apprendre un format : le servo avance de tant (°) à la fois ; contact quand la distance du
    # ToF n'a pas baissé de plus de tof → precision_mm pendant tant de pas de suite (tête libre,
    # ces pas font au moins 2 × precision_mm : vérifié au démarrage).
    pas_apprentissage_deg: float = Field(gt=0)
    apprentissage_pas_plats: int = Field(ge=2)


class PoseMicropore(Modele):
    """Les chiffres de la pose d'un morceau (mm de ruban ou de paroi)."""

    # Rouleau à tant de la paroi à l'approche ; appui : angle du contact + tant de course ;
    # contrôle : la tête recule de tant.
    approche_mm: float = Field(gt=0)
    appui_mm: float = Field(gt=0)
    controle_recul_mm: float = Field(gt=0)
    # Avance du bout du ruban (de la lame à sous le rouleau), pose avant la coupe, après la coupe.
    avance_mm: float = Field(gt=0)
    avant_coupe_mm: float = Field(gt=0)
    apres_coupe_mm: float = Field(gt=0)
    # Trou amené tant avant le rouleau ; recul de tension avant la coupe.
    trou_avant_rouleau_mm: float = Field(ge=0)
    tension_mm: float = Field(ge=0)
    # Vitesse de la paroi (et du ruban) pendant la pose, vitesse du ruban seul (mm/s).
    vitesse_pose_mm_s: float = Field(gt=0)
    vitesse_avance_mm_s: float = Field(gt=0)
    # Sens de rotation du plateau pendant la pose (+1 : angle croissant).
    sens_rotation: Literal[-1, 1]
    # Trou découvert (contrôle à la caméra) : nouveaux essais sur ce trou.
    nouveaux_essais: int = Field(ge=0, le=3)


class AvanceMicropore(Modele):
    """Le moteur d'avance du ruban (NEMA 11 sur TMC2209, en pas/direction) : un axe relatif de
    FluidNC, sans origine et sans codeur."""

    signal: Nom
    carte: Nom
    lettre: Lettre


class RouleauMicropore(Modele):
    """Le rouleau de micropore : morceaux d'un rouleau neuf, alerte « changer le rouleau » sous
    tant de morceaux (environ un fût)."""

    morceaux: int = Field(ge=1)
    alerte_sous: int = Field(ge=0)


class Micropore(Modele):
    """Micropore (module gelé le 28/10/2026, micropore-pour-logiciel.md du 06/11) : la tête est
    sur le chariot de remplissage ; le plateau du chariot tourne et monte le seau. Rien de propre
    au micropore n'est une sécurité (fin de course haut du plateau et butée de la tête : câblés).
    Les angles des gestes (escamoté, approche, contact, appui, caméra → rouleau) sont APPRIS par
    format : ils sont dans le fichier des gestes appris (donnees/micropore-appris.yaml), jamais
    ici."""

    exemple: bool = False
    # Signaux (entrees-sorties.yaml ; voies de la PCA9685 et ToF : pesees.yaml → i2c).
    servo_escamotage: Nom
    servo_lame: Nom
    tof_signal: Nom
    # La caméra du micropore (vision.yaml → cameras).
    camera: Nom
    avance: AvanceMicropore
    # Hauteur du centre du ruban (m, figé) : plateau = ruban_z − hauteur de la rangée.
    ruban_z: float = Field(gt=0)
    # Bord du seau accepté pour la pose (diamètre, m) ; parois que la tête atteint (rayon, m).
    bord_diametre_max_m: float = Field(gt=0)
    paroi_rayon_m: Intervalle
    tof: TofMicropore
    servos: ServosMicropore
    pose: PoseMicropore
    # Rangée du fond : substrat (kg) qu'il faut dans le seau (balance du chariot moins la tare).
    fond_poids_min_kg: float = Field(gt=0)
    rouleau: RouleauMicropore
    formats: dict[Nom, FormatMicropore] = Field(min_length=1)

    @model_validator(mode="after")
    def _verifier(self) -> "Micropore":
        erreurs = []
        debut, fin = self.paroi_rayon_m
        if not 0 < debut < fin:
            erreurs.append("paroi_rayon_m : du plus petit au plus grand")
        if self.tof.butee_mm >= self.tof.escamotee_mm - self.tof.tolerance_escamotee_mm:
            erreurs.append("tof : butee_mm doit être loin sous escamotee_mm − tolerance")
        if self.rouleau.alerte_sous >= self.rouleau.morceaux:
            erreurs.append("rouleau : alerte_sous doit être plus petit que morceaux")
        if self.servos.battement_s >= 2:
            erreurs.append("servos → battement_s : sous 2 s (la carte garde les angles après 2 s)")
        if self.servos.lame_repos_deg == self.servos.lame_bas_deg:
            erreurs.append("servos : lame_repos_deg et lame_bas_deg sont différents")
        servos = self.servos
        course = servos.apprentissage_pas_plats * servos.pas_apprentissage_deg * servos.mm_par_degre
        if course < 2 * self.tof.precision_mm:
            erreurs.append(
                "servos : apprentissage_pas_plats × pas_apprentissage_deg × mm_par_degre (course "
                f"libre de {course:g} mm) doit faire au moins 2 × tof → precision_mm, sinon "
                "l'apprentissage prend une tête qui avance encore pour un contact"
            )
        for nom, format in self.formats.items():
            for numero, rangee in enumerate(format.rangees, start=1):
                if not debut <= rangee.rayon_paroi_m <= fin:
                    erreurs.append(
                        f"formats → {nom} → rangée {numero} : paroi à {rangee.rayon_paroi_m:g} m "
                        f"de l'axe, la tête n'atteint que {debut:g} à {fin:g}"
                    )
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class FormatAppris(Modele):
    """Les gestes appris d'un format de seau (angles de l'axe du servo d'escamotage, en °)."""

    approche_deg: float
    contact_deg: float
    appui_deg: float
    # Distance du ToF au contact, quand le format a été appris (mm, pour comparer).
    contact_mm: float = Field(gt=0)
    # Rotation du plateau (°) qui amène sous le rouleau un trou vu au centre de la caméra.
    camera_rouleau_deg: float


class ChangementAppris(Modele):
    """Une ligne de l'historique : ce qui a changé (« escamote » ou un format), avant et après."""

    numero: int = Field(ge=1)
    quand: str
    qui: str
    cle: Nom
    avant: FormatAppris | float | None = None
    apres: FormatAppris | float | None = None
    # Changement annulé ensuite (par le changement n° annule_par).
    annule_par: int | None = None
    # Ce changement annule le n° annule.
    annule: int | None = None


class GestesAppris(Modele):
    """Le fichier des gestes appris du micropore (donnees/micropore-appris.yaml) : écrit par le
    Pi quand Karulium apprend un format, jamais à la main."""

    # Angle « escamoté » du servo d'escamotage (ToF à la position escamotée).
    escamote_deg: float | None = None
    formats: dict[Nom, FormatAppris] = Field(default_factory=dict)
    historique: list[ChangementAppris] = Field(default_factory=list)


# ------------------------------------------------------------- fermeture des seaux (tâche 41)


class RampeBras(Modele):
    """Le bras ne reçoit jamais un saut : il va à son angle par petits ordres, à cette vitesse."""

    # Il fait `degres` en `duree_s` ; un ordre toutes les `pas_s`.
    degres: float = Field(gt=0)
    duree_s: float = Field(gt=0)
    pas_s: float = Field(gt=0)


class BrasFermeture(Modele):
    """Le bras du galet, tourné à vide par un servo DS3225 (aucun capteur sur le bras). Les angles
    du BRAS sont en degrés, 0 au travail (le doigt sur sa butée), trigo positif (vu de dessus) ;
    ceux du SERVO sont ceux de son axe (0 à 270°), par l'étalonnage `butee_servo_deg`."""

    # Angle rangé du bras (négatif : sens horaire depuis le travail).
    range_deg: float = Field(lt=0, gt=-360)
    # Au travail, le servo va de tant (°) au-delà de la butée, en sens trigo.
    surcourse_deg: float = Field(ge=0, le=10)
    # +1 : l'angle de l'axe du servo grandit quand le bras tourne en sens trigo ; -1 : il baisse.
    sens_servo: Literal[-1, 1]
    # ÉTALONNAGE (à la mise en service) : angle de l'axe du servo où le doigt touche le plat des
    # paliers. Rangé = cet angle + sens × range_deg ; travail = cet angle + sens × surcourse.
    butee_servo_deg: float
    rampe: RampeBras
    # Attente après chaque ordre (s).
    attente_s: float = Field(gt=0)
    # Après un redémarrage de la carte (servos relâchés), le bras compte rangé de nouveau après (s).
    stabilisation_s: float = Field(gt=0)
    # Le Pi renvoie l'angle au moins tous les tant (s) : la carte veut un ordre toutes les 2 s.
    battement_s: float = Field(gt=0)


class MonteeFermeture(Modele):
    """Les chiffres de la montée en appui, vus par la balance du plateau du chariot."""

    # Vitesse de montée de l'approche jusqu'à Hf (m/s).
    vitesse_m_s: float = Field(gt=0)
    # Contact : l'effort au-dessus du poids d'avant (N). F = (P − P0) × 9,81.
    force_contact_n: float = Field(gt=0)
    # Arrêt et descente au-delà de cet effort (N), sans jamais dépasser la limite de la cellule.
    force_max_n: float = Field(gt=0)
    force_max_limite_n: float = Field(gt=0)
    # Le clip s'enfonce de tant (m) : Hc = Hf − cet enfoncement (cotes des seaux).
    enfoncement_clip_m: float = Field(gt=0)
    # Approche : Hc − cette marge (m), mais jamais sous la course basse du plateau.
    marge_approche_m: float = Field(gt=0)
    # Le contact est attendu dans Hc ± fenetre_contact_m ; avant Hc − contact_trop_tot_m : trop tôt.
    fenetre_contact_m: float = Field(gt=0)
    contact_trop_tot_m: float = Field(gt=0)
    # Après les ordres au servo, le temps laissé à la balance pour se stabiliser est celui de
    # remplissage → pesee → attente_s.


class RotationFermeture(Modele):
    """Le clipsage : le plateau tourne à Hf, TOUJOURS en sens horaire."""

    # Signe de l'angle du plateau (axe A de FluidNC) pour le sens HORAIRE vu de dessus.
    sens_horaire: Literal[-1, 1]
    tours: float = Field(gt=0)
    tr_min: float = Field(gt=0)


class FormatFermeture(Modele):
    """Hf : hauteur du dessus du plateau, seau clipsé, pour un format (m, vérifié sur les seaux)."""

    hf_m: float = Field(gt=0)


class Fermeture(Modele):
    """Fermeture des seaux (module gelé, fermeture-seaux-pour-logiciel.md du 01/11/2026) : un bras
    porte un rouleau ; le PLATEAU monte et tourne pour clipser le couvercle, sous la surveillance
    de la balance. Rien n'est câblé en dur pour ce module (la force vient du plateau, limité par
    ses propres protections) : ces réglages protègent la machine, jamais les personnes."""

    exemple: bool = False
    # Voie de la PCA9685 (pesees.yaml → i2c) du servo DS3225 du bras.
    servo: Nom
    # Position du chariot en y pendant la fermeture (m) : figée par le Remplissage (règle 1 de
    # regles-positions.md : c'est là que la préhension pose le couvercle).
    chariot_y: float
    # Le bras ne quitte le rangé que si la préhension a lâché le couvercle et est remontée au-dessus
    # de ce z (m, figé d'après le Remplissage), ou est partie ailleurs.
    prehension_libre_z: float
    bras: BrasFermeture
    montee: MonteeFermeture
    rotation: RotationFermeture
    formats: dict[Nom, FormatFermeture] = Field(min_length=1)

    def hc(self, format: str) -> float:
        """Hauteur du plateau où le couvercle touche le rouleau."""
        return self.formats[format].hf_m - self.montee.enfoncement_clip_m

    def h_approche(self, format: str, course_basse: float) -> float:
        """Hauteur du plateau avant le geste : Hc − marge, mais pas sous la course basse."""
        return max(self.hc(format) - self.montee.marge_approche_m, course_basse)

    def servo_travail_deg(self) -> float:
        return self.bras.butee_servo_deg + self.bras.sens_servo * self.bras.surcourse_deg

    def servo_range_deg(self) -> float:
        return self.bras.butee_servo_deg + self.bras.sens_servo * self.bras.range_deg

    @model_validator(mode="after")
    def _verifier(self) -> "Fermeture":
        erreurs = []
        m = self.montee
        if m.force_max_n > m.force_max_limite_n:
            erreurs.append(
                f"montee → force_max_n ({m.force_max_n:g}) : au plus {m.force_max_limite_n:g} N "
                "(limite de la cellule de 30 kg avec un seau plein)"
            )
        if m.force_contact_n >= m.force_max_n:
            erreurs.append("montee : force_contact_n doit être plus petit que force_max_n")
        if m.contact_trop_tot_m <= m.fenetre_contact_m:
            erreurs.append("montee : contact_trop_tot_m doit être plus grand que fenetre_contact_m")
        if m.marge_approche_m <= m.contact_trop_tot_m:
            erreurs.append(
                "montee : marge_approche_m doit être plus grand que contact_trop_tot_m (sinon le "
                "contact « trop tôt » ne peut pas se voir)"
            )
        if m.enfoncement_clip_m <= m.fenetre_contact_m:
            erreurs.append("montee : enfoncement_clip_m doit être plus grand que fenetre_contact_m")
        if self.bras.battement_s >= 2:
            erreurs.append("bras → battement_s : sous 2 s (la carte garde les angles après 2 s)")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


# ------------------------------------------------------------- entonnoir à bocaux (tâche 43)


class PriseEntonnoir(Modele):
    """Contrôle du contact quand la ventouse descend sur l'oreille (fiche, geste 6)."""

    # Contact plus haut que l'attendu de plus de tant : « entonnoir mal posé ».
    trop_haut_m: float = Field(gt=0)
    # Pas de contact avant tant sous l'attendu : « entonnoir absent ».
    trop_bas_m: float = Field(gt=0)


class PoseEntonnoir(Modele):
    """Contrôle du contact quand l'entonnoir se pose sur un col (fiche, geste 10)."""

    # Posé : contact à l'attendu ± tolerance_m.
    tolerance_m: float = Field(gt=0)
    # Plus haut de bord_du_verre_m ou plus : la pointe est sur le bord du verre, pas dedans.
    bord_du_verre_m: float = Field(gt=0)


class VideEntonnoir(Modele):
    """Seuils propres à l'entonnoir ; la prise (−55 kPa) et la perte (−40 kPa) sont celles de la
    Préhension (prehension → vide)."""

    # Délai pour atteindre le vide de la prise avant un nouvel essai (s).
    delai_prise_s: float = Field(gt=0)
    # Lâché : le vide est revenu au-dessus de ce seuil (kPa), attendu au plus delai_lacher_s.
    lache_kpa: float = Field(lt=0)
    delai_lacher_s: float = Field(gt=0)
    # Après un vide pas atteint : remonter de tant avant de redescendre (m).
    remontee_reessai_m: float = Field(gt=0)


class ColEntonnoir(Modele):
    """Ce que la caméra du plafond doit donner, et ce que le cône rattrape (fiche, § 3)."""

    # Précision demandée sur le centre du col (m) et erreur que le cône 60° capte seul (m).
    precision_m: float = Field(gt=0)
    capture_m: float = Field(gt=0)


class Entonnoir(Modele):
    """Entonnoir à bocaux (module sans capteur ni moteur : fiche entonnoir-pour-logiciel.md du
    06/11/2026). La Préhension le prend par une oreille soudée à plat, ventouse, électroaimants
    éteints. Repère du portique, en mètres ; « z » = face de la ventouse. Rien n'est câblé pour
    ce module : ces réglages protègent la machine, jamais les personnes."""

    exemple: bool = False
    # La ventouse tient l'oreille à tant de l'axe du bocal (oreille côté +x), figé.
    decalage_oreille_x_m: float
    decalage_oreille_y_m: float
    # Face de la ventouse au contact de l'oreille, entonnoir posé : À MESURER sur la pièce reçue.
    oreille_z: float
    # Pointe et haut du cône, entonnoir posé : à mesurer aussi.
    pointe_z: float
    cone_haut_z: float
    # Bord du col des bocaux posés (mesuré).
    bord_col_z: float
    # Levée de transport (m) : l'entonnoir roule à cette hauteur au-dessus de sa pose.
    levee_m: float = Field(gt=0)
    # Garde minimale entre la pointe en transport et le bord des cols voisins (m).
    garde_voisins_min_m: float = Field(gt=0)
    # Fin de la descente rapide : tant au-dessus du haut de l'oreille (m).
    approche_m: float = Field(gt=0)
    # Après le lâcher, la tête remonte de tant en vitesse d'approche (l'entonnoir reste posé).
    remontee_lacher_m: float = Field(gt=0)
    prise: PriseEntonnoir
    pose: PoseEntonnoir
    vide: VideEntonnoir
    col: ColEntonnoir

    @property
    def face_transport_z(self) -> float:
        """Face de la ventouse quand l'entonnoir roule."""
        return self.oreille_z + self.levee_m

    @model_validator(mode="after")
    def _verifier(self) -> "Entonnoir":
        erreurs = []
        if self.pointe_z >= self.oreille_z:
            erreurs.append("pointe_z doit être plus bas que oreille_z")
        if self.cone_haut_z > self.oreille_z:
            erreurs.append("cone_haut_z ne peut pas dépasser oreille_z (l'oreille est en haut)")
        if self.pointe_z >= self.cone_haut_z:
            erreurs.append("pointe_z doit être plus bas que cone_haut_z")
        garde = self.pointe_z + self.levee_m - self.bord_col_z
        if garde < self.garde_voisins_min_m - 1e-9:
            erreurs.append(
                f"en transport la pointe n'est qu'à {garde * 1000:.0f} mm au-dessus du bord des "
                f"cols voisins ({self.bord_col_z:g} m) : il en faut "
                f"{self.garde_voisins_min_m * 1000:g}"
            )
        if self.col.precision_m > self.col.capture_m:
            erreurs.append(
                f"col → precision_m ({self.col.precision_m:g}) plus grande que capture_m "
                f"({self.col.capture_m:g}) : le cône ne se centrerait pas seul"
            )
        if self.pose.tolerance_m >= self.pose.bord_du_verre_m:
            erreurs.append("pose → tolerance_m doit être plus petit que bord_du_verre_m")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


# ------------------------------------------------------------- couvercle sur le seau plein (41 bis)


class PileCouvercle(Modele):
    """Prise à la pile des couvercles du stockage (fiche, § 1 a, étapes 1 à 6)."""

    # Haut prévu de la pile quand le Pi n'a pas de mémoire de la dernière prise (face, m).
    haut_sans_memoire_z: float
    # Descente rapide jusqu'à tant au-dessus du haut prévu (m), puis lente jusqu'au contact.
    approche_m: float = Field(gt=0)
    # Épaisseur du dernier couvercle (m) : pas de contact avant fond + tant = pile vide.
    epaisseur_dernier_m: float = Field(gt=0)
    # Décollage lent sur tant (m) : deux couvercles empilés peuvent coller.
    decollage_m: float = Field(gt=0)


class VideCouvercle(Modele):
    """Le vide de la prise (−55 kPa) et celui de l'arrêt (−40 kPa) sont ceux de la Préhension
    (prehension → vide) ; ici ce qui est propre au couvercle."""

    # Une impulsion du venturi dure tant (s) ; au plus tant d'impulsions par essai.
    impulsion_s: float = Field(gt=0)
    impulsions_max: int = Field(ge=1)
    # Essais de prise (souffler, remonter de remontee_reessai_m, redescendre au contact).
    essais_max: int = Field(ge=1)
    remontee_reessai_m: float = Field(gt=0)
    # Lâché : le vide est revenu au-dessus de ce seuil (kPa) ; « souffler » dure souffle_s.
    lache_kpa: float = Field(lt=0)
    souffle_s: float = Field(gt=0)
    delai_lacher_s: float = Field(gt=0)


class PoseCouvercle(Modele):
    """Pose sur le seau plein, plateau déjà à H_app (fiche, § 1 b et § 2)."""

    # Axe de l'outil à la pose (figé : compense le décalage de 1 cm de la prise).
    x: float
    y: float
    # Dessus du couvercle posé quand le plateau est à Hc : Z_pose = H_app + dessus_pose_z − Hc.
    dessus_pose_z: float
    # Descente rapide jusqu'à Z_pose + tant (m), puis à la vitesse couvercle_pose.
    rapide_m: float = Field(gt=0)
    # Contact attendu à Z_pose ± fenetre_m ; plus haut que Z_pose + fenetre_m : « mal posé » ;
    # pas de contact à Z_pose − sans_contact_m : « pas de seau ».
    fenetre_m: float = Field(gt=0)
    sans_contact_m: float = Field(gt=0)
    # Dégagement lent sur tant (m) ; le M8 doit retomber dans les premiers m8_retombe_m.
    degagement_m: float = Field(gt=0)
    m8_retombe_m: float = Field(gt=0)


class FormatCouvercle(Modele):
    # Masse d'un couvercle de ce format (kg) : À PESER sur les vrais couvercles.
    masse_kg: float = Field(gt=0)
    # Format C (fiche, § 5 point 1) : descente à la vitesse de la pose entre ces deux faces (m),
    # en attendant la réponse du Micropore (passage à 2,3 mm de sa tête escamotée).
    descente_lente_z: tuple[float, float] | None = None


class Couvercle(Modele):
    """Pose du couvercle sur le seau plein par la Préhension (tâche 41 bis ; fiche
    pose-couvercle-pour-logiciel.md du 07/11/2026). Rien n'est câblé en dur pour ce geste : le
    vide, le M8 et les pesées ne protègent jamais personne."""

    exemple: bool = False
    # Masse d'un couvercle = m_c ± tolerance_pct % (contrôle « un seul couvercle » et pesée sur
    # la balance du chariot).
    tolerance_pct: float = Field(gt=0, lt=100)
    # Après le lâcher, le palier pesé revient à vide à ± tant (N).
    palier_vide_n: float = Field(gt=0)
    pile: PileCouvercle
    vide: VideCouvercle
    pose: PoseCouvercle
    formats: dict[Nom, FormatCouvercle] = Field(min_length=1)

    def tolerance_kg(self, format: str) -> float:
        return self.formats[format].masse_kg * self.tolerance_pct / 100


# ------------------------------------------------------------- bocal neuf de semence (19 quater)


class BocalDeSemence(Modele):
    """Le bocal de semence (fiche de la Préhension du 07/11/2026) : Ø 95, capsule twist-off en fer
    Ø 103 × 13 avec son QR, couvercle percé « salière » de même capsule."""

    # Hauteur avec la capsule (ou le couvercle percé) bien vissée (m, ± 0,5 mm) : le bocal pend
    # sous la face de la tête de tant quand la tête le porte.
    hauteur_m: float = Field(gt=0)
    # Masses À PESER (kg) : capsule, couvercle percé, bocal plein de semence (bocal vide : 350 g).
    # Contrôle des pesées : masse attendue ± tolerance_pct %.
    m_capsule_kg: float = Field(gt=0)
    m_couv_perce_kg: float = Field(gt=0)
    m_bocal_plein_kg: float = Field(gt=0)
    tolerance_pct: float = Field(gt=0, lt=100)

    def tolerance_n(self, masse_kg: float) -> float:
        return masse_kg * self.tolerance_pct / 100 * 9.81


class DevissageBocalNeuf(Modele):
    """Dévisser la capsule sur sa place du stockage (étapes 1 à 6 de la fiche)."""

    # La tête tourne, en l'air, à cet angle avant de descendre (° ; dans la course de la rotation).
    angle_depart_deg: float
    # Dévissage en sens trigo (positif), au plus tant de degrés en tout ; 1er essai de décollage
    # après premier_essai_deg, puis tous les pas_essai_deg.
    rotation_max_deg: float = Field(gt=0)
    premier_essai_deg: float = Field(gt=0)
    pas_essai_deg: float = Field(gt=0)
    # Pas de contact jusqu'à tant sous la cote du dessus de la capsule : pas de bocal.
    sans_bocal_m: float = Field(gt=0)
    # Essai de décollage : la poussée est relâchée par petits pas de relache_pas_m (au plus
    # relache_pas_max) jusqu'à relache_n, puis la tête monte de decollage_m.
    relache_n: float = Field(ge=0)
    relache_pas_m: float = Field(gt=0)
    relache_pas_max: int = Field(ge=1)
    decollage_m: float = Field(gt=0)


class VissageBocalNeuf(Modele):
    """Visser le couvercle percé sur le bocal (étapes 9 à 11 de la fiche)."""

    # Vissage en sens horaire (négatif) à partir de cet angle, au plus rotation_max_deg.
    angle_depart_deg: float
    rotation_max_deg: float = Field(gt=0)
    # Face au calage : cote du dessus de la capsule au stockage ± tant (m).
    hauteur_tolerance_m: float = Field(gt=0)
    # Poussée relâchée jusqu'à appui_nul_n, puis la tête monte de levee_m avec le bocal.
    appui_nul_n: float = Field(ge=0)
    levee_m: float = Field(gt=0)
    # Essais de vissage (couvercle pas encore vissé à la pesée) avant l'alerte.
    essais_max: int = Field(ge=1)


class CaleBocalNeuf(Modele):
    """Le moteur de la rotation cale quand l'erreur de son codeur dépasse err_deg pendant
    duree_s. Le couple de serrage C_vis (≈ 1,5 N·m au mât) se règle À LA MAIN sur le pilote, au
    premier essai : le logiciel ne le commande pas."""

    err_deg: float = Field(gt=0)
    duree_s: float = Field(ge=0)


class BoitesBocalNeuf(Modele):
    """Les boîtes à capsules du Stockage (stockage → boites) et leurs gestes."""

    # Noms des boîtes dans stockage → boites → places.
    capsules: Nom
    couvercles_perces: Nom
    # Descente rapide jusqu'à tant au-dessus de la cote prévue (m), puis lente jusqu'au contact.
    approche_m: float = Field(gt=0)
    # Axe de l'outil centré sur la boîte à tant près (m).
    centrage_m: float = Field(gt=0)
    # Contact à la cote prévue ± tant (m), sinon alerte (compte faux ou capsule de travers).
    fenetre_m: float = Field(gt=0)
    # Capsule lâchée : attente avant la remontée (s). Remontée lente (m).
    attente_lacher_s: float = Field(ge=0)
    remontee_m: float = Field(gt=0)
    # Prises du couvercle percé (deux collés : reposés et refaits) avant l'alerte.
    prises_max: int = Field(ge=1)


class BocalNeuf(Modele):
    """Bocal neuf de semence, du stockage au porte-bocal (tâche 19 quater ; fiche
    `prehension/logiciel/bocal-neuf-pour-logiciel.md` du 07/11/2026, module Préhension gelé le
    27/10). Rien n'est câblé en dur pour ce geste : l'appui, le M8, les pesées et le calage du
    moteur ne protègent jamais personne. L'appui de dévissage et de vissage (F_devis, 80 N) est
    celui de prehension → vissage ; la place des bocaux et la cote du dessus de la capsule
    (z_capsule_stock) sont celles de stockage → bocaux (semence, capsule_haut_z)."""

    exemple: bool = False
    bocal: BocalDeSemence
    # Descente rapide jusqu'à tant au-dessus de la cote du contact attendu (m), puis lente.
    approche_m: float = Field(gt=0)
    devissage: DevissageBocalNeuf
    vissage: VissageBocalNeuf
    cale: CaleBocalNeuf
    boites: BoitesBocalNeuf
    # Le palier pesé revient à vide à ± tant (N) quand le bocal est lâché (± 30 g).
    palier_vide_n: float = Field(gt=0)


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
    # Portique : pont, chariot, les deux Z (None : pas de portique, pour des réglages d'essai).
    portique: Portique | None = None
    # Nettoyage : enceinte, store, purge, nuit UV-ozone (None : pas de nettoyage).
    nettoyage: Nettoyage | None = None
    # Spray : carte n° 5, flacons, bras de la buse (None : pas de spray). Demande la griffe
    # (table des formats) et le remplissage (règle 6 du bras).
    spray: Spray | None = None
    # Micropore : tête sur le chariot de remplissage (None : pas de micropore). Demande la griffe
    # (formats) et le remplissage (plateau, règles 9 et C2).
    micropore: Micropore | None = None
    # Fermeture des seaux : bras du galet sur le chariot de remplissage (None : pas de fermeture).
    # Demande la griffe (formats), le remplissage (plateau, règle 5) et le micropore n'est pas
    # nécessaire.
    fermeture: Fermeture | None = None
    # Entonnoir à bocaux (None : pas d'entonnoir). Demande la préhension (objet « entonnoir ») et
    # le stockage (places des bocaux).
    entonnoir: Entonnoir | None = None
    # Pose du couvercle sur le seau plein (None : pas de couvercle). Demande la préhension (objet
    # « couvercle »), le stockage (pile des couvercles), la fermeture (hauteurs) et la griffe.
    couvercle: Couvercle | None = None
    # Bocal neuf de semence pris au stockage et posé sur le porte-bocal (None : pas de geste).
    # Demande la préhension, le stockage, le porte-bocal, le mycélium et la griffe.
    bocal_neuf: BocalNeuf | None = None

    @model_validator(mode="after")
    def _verifier_positions_et_zones(self) -> "Machine":
        erreurs: list[str] = []
        for numero, geste in enumerate(self.lieu_sur, start=1):
            if geste.delai not in self.durees:
                erreurs.append(f"lieu_sur n° {numero} : délai « {geste.delai} » absent de durees")
            if geste.portique is not None and self.portique is None:
                erreurs.append(f"lieu_sur n° {numero} : il faut aussi la partie « portique »")
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
        erreurs += self._verifier_portique()
        erreurs += self._verifier_spray()
        erreurs += self._verifier_micropore()
        erreurs += self._verifier_fermeture()
        erreurs += self._verifier_entonnoir()
        erreurs += self._verifier_couvercle()
        erreurs += self._verifier_bocal_neuf()
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

    def _verifier_portique(self) -> list[str]:
        """Axes du portique, chariot et mâts, plaques Z, vitesses, places, plénum."""
        portique = self.portique
        if portique is None:
            return []
        erreurs = []
        for nom in AXES_PORTIQUE:
            axe = self.axes.get(nom)
            if axe is None:
                erreurs.append(f"portique : axe « {nom} » absent de axes")
            elif axe.unite != "m" or axe.carte is None:
                erreurs.append(f"portique : l'axe « {nom} » doit être en « m », avec sa carte")
        if erreurs:
            return erreurs
        egal = 1e-6
        # Chariot : les mâts sont à centre + décalage.
        chariot = portique.chariot
        mats = tuple(c + chariot.mats_moins_centre_y for c in chariot.centre_y)
        course_y = self.axes["chariot_y"].course
        if any(abs(a - b) > egal for a, b in zip(mats, course_y, strict=True)):
            erreurs.append(
                f"portique → chariot : centre de {chariot.centre_y[0]:g} à "
                f"{chariot.centre_y[1]:g} m et mâts à centre {chariot.mats_moins_centre_y:+g} m "
                f"donnent les mâts de {mats[0]:g} à {mats[1]:g} m ; la course de chariot_y "
                f"(le y des mâts) doit être la même (elle va de {course_y[0]:g} à "
                f"{course_y[1]:g} m)"
            )
        # Plaques Z : même course que la hauteur d'outil qu'elles portent.
        for nom, plaque in portique.plaques_z.items():
            axe = self.axes.get(plaque.axe)
            if axe is None or axe.unite != "m":
                erreurs.append(f"portique → plaques_z → {nom} : axe « {plaque.axe} » inconnu")
                continue
            bas, haut = plaque.course
            if bas >= haut:
                erreurs.append(f"portique → plaques_z → {nom} : aller du bas vers le haut")
                continue
            longueur = axe.course[1] - axe.course[0]
            if abs((haut - bas) - longueur) > 0.001:
                erreurs.append(
                    f"portique → plaques_z → {nom} : la plaque Z fait {haut - bas:.3f} m de "
                    f"course, l'axe « {plaque.axe} » {longueur:.3f} m : les hauteurs ne "
                    "concordent pas"
                )
        # Prise d'origine : chaque axe une fois, avec sa carte ; les Z, puis Y, puis X.
        groupe_de: dict[str, int] = {}
        for numero, groupe in enumerate(portique.origine, start=1):
            for nom in groupe:
                axe = self.axes.get(nom)
                if axe is None or axe.carte is None or axe.lettre is None:
                    erreurs.append(
                        f"portique → origine n° {numero} : « {nom} » n'est pas un axe avec sa "
                        "carte et sa lettre"
                    )
                elif nom in groupe_de:
                    erreurs.append(f"portique → origine : « {nom} » écrit deux fois")
                groupe_de.setdefault(nom, numero)
        verticaux = [plaque.axe for plaque in portique.plaques_z.values()]
        ordre = [*verticaux, "chariot_y", "pont_x"]
        paires = [(z, "chariot_y") for z in verticaux] + [("chariot_y", "pont_x")]
        if "griffe_b" in groupe_de:
            # Le godet après le portique (Z en haut, PR n° 56, point 4).
            paires.append(("pont_x", "griffe_b"))
        manquent = [nom for nom in ordre if nom not in groupe_de]
        if manquent:
            erreurs.append(f"portique → origine : il manque {', '.join(manquent)}")
        else:
            for avant, apres in paires:
                if groupe_de[avant] >= groupe_de[apres]:
                    erreurs.append(
                        f"portique → origine : « {avant} » doit avoir fini sa prise d'origine "
                        f"avant « {apres} » (les Z en haut, puis Y, puis X, puis le godet)"
                    )
        if self.griffe is not None and self.griffe.origine_rotation is not None:
            if "griffe_a" in groupe_de:
                erreurs.append(
                    "portique → origine : « griffe_a » n'y va pas : sa prise d'origine est faite "
                    "par le Pi (griffe → origine_rotation), au point de demi-tour"
                )
            if self.griffe.point_demi_tour is None:
                erreurs.append("griffe → origine_rotation : il faut aussi griffe → point_demi_tour")
            if "griffe_b" not in groupe_de:
                # La recherche se fait godet fermé : le godet a déjà fait sa prise d'origine.
                erreurs.append("portique → origine : il manque « griffe_b » (le godet)")
        # Vitesses : celles des outils au plus celles du portique ; accélération de la
        # préhension = celle du portique (à vide, seau tenu).
        v = portique.vitesses
        plafonds = []
        if self.griffe is not None:
            g = self.griffe.vitesses
            plafonds += [
                ("griffe → vitesses → pont_x", g.pont_x, v.xy_rapide_m_s),
                ("griffe → vitesses → chariot_y", g.chariot_y, v.xy_rapide_m_s),
                ("griffe → vitesses → griffe_z", g.griffe_z, v.z_rapide_m_s),
            ]
        if self.prehension is not None:
            p = self.prehension
            plafonds += [
                ("prehension → vitesses → pont_x", p.vitesses.pont_x, v.xy_rapide_m_s),
                ("prehension → vitesses → chariot_y", p.vitesses.chariot_y, v.xy_rapide_m_s),
                ("prehension → vitesses → z", p.vitesses.z, v.z_rapide_m_s),
            ]
            for quoi, valeur, voulue in (
                ("normale_mm_s2", p.acceleration.normale_mm_s2, v.xy_acceleration_vide_m_s2),
                ("seau_mm_s2", p.acceleration.seau_mm_s2, v.xy_acceleration_seau_m_s2),
            ):
                if abs(valeur - voulue * 1000) > egal:
                    erreurs.append(
                        f"prehension → acceleration → {quoi} ({valeur:g}) doit être celle du "
                        f"portique ({voulue * 1000:g} mm/s²)"
                    )
        for quoi, valeur, plafond in plafonds:
            if valeur > plafond + egal:
                erreurs.append(f"{quoi} ({valeur:g} m/s) dépasse celle du portique ({plafond:g})")

        # Places nommées.
        def position(quoi: str, nom: str, axes: tuple[str, ...]) -> dict[str, float] | None:
            valeurs = self.positions.get(nom)
            if valeurs is None:
                erreurs.append(f"portique → {quoi} : position « {nom} » absente de positions")
                return None
            manquent = [axe for axe in axes if axe not in valeurs]
            if manquent:
                erreurs.append(
                    f"portique → {quoi} : la position « {nom} » doit donner {', '.join(manquent)}"
                )
                return None
            return valeurs

        en_haut = position("outils_en_haut", portique.outils_en_haut, ("griffe_z", "prehension_z"))
        if en_haut is not None:
            for axe in ("griffe_z", "prehension_z"):
                haut = self.axes[axe].course[1]
                if abs(en_haut[axe] - haut) > egal:
                    erreurs.append(
                        f"portique → outils_en_haut : {axe} doit être en haut de sa course "
                        f"({haut:g} m)"
                    )
        position("garage", portique.garage, ("pont_x", "chariot_y"))
        for zone, nom in portique.photo.items():
            if zone not in ZONES_PHOTO:
                erreurs.append(
                    f"portique → photo : zone inconnue « {zone} » (connues : "
                    f"{', '.join(ZONES_PHOTO)})"
                )
            position(f"photo → {zone}", nom, ("pont_x",))
        # Plénum du Nettoyage : vrai sur toute la course, ou le dire.
        plenum = portique.plenum
        plaque = portique.plaques_z.get("prehension")
        if plaque is None:
            erreurs.append("portique → plaques_z : il manque « prehension » (règle du plénum)")
        elif (
            plaque.course[1] > plenum.plaque_z_min + egal
            and chariot.centre_y[1] > plenum.chariot_centre_y_max + egal
        ):
            erreurs.append(
                f"portique → plenum : la préhension monte à {plaque.course[1]:g} m (plus de "
                f"{plenum.plaque_z_min:g}) et le chariot va à y {chariot.centre_y[1]:g} m (plus "
                f"de {plenum.chariot_centre_y_max:g}) : la tête toucherait le plénum du Nettoyage"
            )
        # Chaîne Z de la préhension : seuil dans la course de la plaque ; aucune position nommée
        # (ni le garage, outils en haut) ne la met en défaut.
        chaine = portique.chaine_prehension
        if chaine is not None and plaque is not None:
            if not plaque.course[0] < chaine.plaque_z_min < plaque.course[1]:
                erreurs.append(
                    f"portique → chaine_prehension : plaque_z_min {chaine.plaque_z_min:g} hors de "
                    f"la course de la plaque Z de la préhension ({plaque.course[0]:g} à "
                    f"{plaque.course[1]:g})"
                )
            bas_face = self.axes[plaque.axe].course[0]
            places = {nom: dict(valeurs) for nom, valeurs in self.positions.items()}
            if portique.garage in places and en_haut is not None:
                places[portique.garage].setdefault("prehension_z", en_haut["prehension_z"])
            for nom, valeurs in places.items():
                if "chariot_y" in valeurs and "prehension_z" in valeurs:
                    refus = portique.refus_chaine(
                        valeurs["chariot_y"], valeurs["prehension_z"], bas_face
                    )
                    if refus is not None:
                        erreurs.append(f"position « {nom} » : {refus}")
        if portique.tete_basse_z is not None:
            debut, fin = self.axes["prehension_z"].course
            if not debut <= portique.tete_basse_z <= fin:
                erreurs.append(
                    f"portique → tete_basse_z ({portique.tete_basse_z:g}) hors de la course de "
                    f"prehension_z ({debut:g} à {fin:g})"
                )
        # Bouts du pont où la tête de la griffe ne tourne pas.
        if portique.bouts_bloques_griffe and self.griffe is None:
            erreurs.append("portique → bouts_bloques_griffe : il faut aussi la partie « griffe »")
        pont = self.axes["pont_x"].course
        for numero, bout in enumerate(portique.bouts_bloques_griffe, start=1):
            if not pont[0] - egal <= bout.pont_x[0] < bout.pont_x[1] <= pont[1] + egal:
                erreurs.append(
                    f"portique → bouts_bloques_griffe n° {numero} : {bout.pont_x[0]:g} à "
                    f"{bout.pont_x[1]:g} m doit aller du plus petit au plus grand, dans la "
                    f"course du pont ({pont[0]:g} à {pont[1]:g} m)"
                )
            z_debut, z_fin = self.axes["griffe_z"].course if "griffe_z" in self.axes else (0, 0)
            if bout.axes_z_max is not None and not z_debut < bout.axes_z_max <= z_fin:
                erreurs.append(
                    f"portique → bouts_bloques_griffe n° {numero} : axes_z_max "
                    f"{bout.axes_z_max:g} hors de la course de griffe_z ({z_debut:g} à {z_fin:g})"
                )
            if bout.axes_z_max is None and not bout.angles_deg:
                erreurs.append(
                    f"portique → bouts_bloques_griffe n° {numero} : sans axes_z_max ni angle "
                    "permis, la griffe ne pourrait jamais y aller : donner l'un ou l'autre"
                )
        return erreurs

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
        point = griffe.point_demi_tour
        if point is not None:
            hauteur("point_demi_tour", point.z)
            if point.z > griffe.rotation.libre_z_max + 1e-9:
                erreurs.append(
                    f"griffe → point_demi_tour : axes à {point.z:g} m, au-dessus de rotation → "
                    f"libre_z_max ({griffe.rotation.libre_z_max:g}) : la tête n'y tourne pas"
                )
            if not pont[0] <= point.x - griffe.decalage_mat_x <= pont[1]:
                erreurs.append("griffe → point_demi_tour : x hors de la course du pont")
            debut, fin = self.axes["chariot_y"].course
            if not debut - 1e-9 <= point.y <= fin + 1e-9:
                erreurs.append("griffe → point_demi_tour : y hors de la course de chariot_y")
            chaine = None if self.portique is None else self.portique.chaine_prehension
            if chaine is not None and point.y > chaine.mat_y_max + 1e-9:
                # La prise d'origine y va préhension en haut.
                erreurs.append(
                    f"griffe → point_demi_tour : y {point.y:g} au-delà de chaine_prehension → "
                    f"mat_y_max ({chaine.mat_y_max:g}) : la préhension y est en haut"
                )
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
        zone = prehension.zone_porte_bocal
        if not (
            zone.x[0] <= porte_bocal.x <= zone.x[1] and zone.y[0] <= porte_bocal.y <= zone.y[1]
        ):
            erreurs.append(
                f"prehension → zone_porte_bocal : le bocal ({porte_bocal.x:g} ; "
                f"{porte_bocal.y:g}) n'est pas dans la zone"
            )
        mycelium = self.mycelium
        if mycelium is None:
            erreurs.append(
                "prehension : il faut la partie « mycelium » (sa course de l'agitation choisit le "
                "contact de la capsule)"
            )
        else:
            course = mycelium.course_agitation_m
            contact = porte_bocal.contact_z(course)
            maximum = prehension.haut_z - porte_bocal.marge_face_haute_m
            if contact is None:
                erreurs.append(
                    f"prehension → porte_bocal → contact_capsule_z : rien pour la course "
                    f"{course:g} m (mycelium → course_agitation_m)"
                )
            elif contact < debut:
                erreurs.append(
                    f"prehension → porte_bocal → contact_capsule_z : {contact:g} m (course "
                    f"{course:g} m) sous la course de prehension_z ({debut:g} à {fin:g} m)"
                )
            elif contact > maximum + 1e-9:
                erreurs.append(
                    f"mycelium → course_agitation_m : {course:g} m refusée, contact de la capsule "
                    f"à {contact:g} m, au-dessus de la face haute ({prehension.haut_z:g} m) moins "
                    f"{porte_bocal.marge_face_haute_m:g} m : la préhension ne peut pas poser le "
                    "bocal (changer le maneton de trou)"
                )
            x, y = mycelium.bocal
            if math.hypot(porte_bocal.x - x, porte_bocal.y - y) > prehension.tolerance_m:
                erreurs.append(
                    f"prehension → porte_bocal : ({porte_bocal.x:g} ; {porte_bocal.y:g}), pas "
                    f"sur le bocal du mycélium (mycelium → bocal : ({x:g} ; {y:g}))"
                )
        couloir = porte_bocal.couloir
        if couloir is not None:
            # Le départ, sur l'axe du bocal côté allée, hors de la zone (tête, bocal tenu) ; face
            # dans la course ; la tête seule et le bocal dans le couloir.
            if abs(couloir.depart[0] - porte_bocal.x) > 1e-9 or couloir.depart[1] <= porte_bocal.y:
                erreurs.append(
                    "prehension → porte_bocal → couloir → depart : sur l'axe du bocal en x, "
                    "côté allée (y plus grand que celui du bocal)"
                )
            bocal = prehension.objets.get("bocal")
            autour = prehension.rayon_tete_m + zone.marge_m + (bocal.rayon_m if bocal else 0.0)
            if couloir.depart[1] < zone.y[1] + autour - 1e-9:
                erreurs.append(
                    f"prehension → porte_bocal → couloir → depart : y {couloir.depart[1]:g} m dans "
                    f"la zone du porte-bocal (il faut y ≥ {zone.y[1] + autour:.3f} m)"
                )
            if not debut <= couloir.face_z <= fin:
                erreurs.append("prehension → porte_bocal → couloir → face_z hors de la course de Z")
            moins, plus = couloir.largeur_x_bocal
            if not moins < 0 < plus or couloir.demi_largeur_x_mors > min(-moins, plus):
                erreurs.append(
                    "prehension → porte_bocal → couloir : largeur_x_bocal (−, +) autour de 0, "
                    "plus large que demi_largeur_x_mors"
                )
            if porte_bocal.tolerance_pose_x_m > couloir.demi_largeur_x_mors:
                erreurs.append(
                    "prehension → porte_bocal → tolerance_pose_x_m : plus large que le couloir "
                    "dans les mors (couloir → demi_largeur_x_mors)"
                )
        if not porte_bocal.tolerance_pose_y_m[0] <= 0 <= porte_bocal.tolerance_pose_y_m[1]:
            erreurs.append("prehension → porte_bocal → tolerance_pose_y_m : (−, +) autour de 0")
        if porte_bocal.descente_lente_pose_m > 0 and prehension.vitesses.pose_bocal is None:
            erreurs.append(
                "prehension → porte_bocal → descente_lente_pose_m : il faut vitesses → pose_bocal"
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
            hors_portee(
                f"formats → {nom} → jet_decalage",
                centre_x + reglage.jet_decalage[0],
                lavage.centre_fut[1] + reglage.jet_decalage[1],
            )
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
        for nom in ("poste_y", "dosage_y", "ecarte_y", "vidage_y", "pose_y"):
            dans(nom, "remplissage_y", getattr(r, nom))
        dans("couvercles → y", "remplissage_y", r.couvercles.y)
        dans("plateau_en_bas_z", "plateau_z", r.plateau_en_bas_z)
        dans(
            "couvercles → y_demi_tour_griffe_min",
            "remplissage_y",
            r.couvercles.y_demi_tour_griffe_min,
        )
        dans("couvercles → plateau_z", "plateau_z", r.couvercles.plateau_z)
        dans("inspection → plateau_z", "plateau_z", r.inspection.plateau_z)
        if r.plateau_lecture_qr is not None:
            dans("plateau_lecture_qr", "plateau_z", r.plateau_lecture_qr)
            lecture_y = r.pose_y if r.lecture_qr_y is None else r.lecture_qr_y
            dans("lecture_qr_y", "remplissage_y", lecture_y)
            limite = r.lecture_qr_bord_max_z
            if limite is None:
                erreurs.append(
                    "remplissage → lecture_qr_bord_max_z : il manque (limite du bord du seau à "
                    "la position de lecture du QR, avec plateau_lecture_qr)"
                )
            else:
                if lecture_y < r.dosage_y:
                    # Au poste (règle C2), le bord du seau reste ≤ poste_bord_max_z toujours.
                    limite = min(limite, r.verrous.poste_bord_max_z)
                for nom, seau in self.griffe.formats.items():
                    if seau.hauteur is None:
                        continue
                    bord = r.plateau_lecture_qr + seau.hauteur
                    if bord > limite + 1e-9:
                        erreurs.append(
                            f"remplissage → plateau_lecture_qr : {r.plateau_lecture_qr:g} + "
                            f"hauteur du seau {nom} ({seau.hauteur:g}) = {bord:.4f} dépasse la "
                            f"limite de hauteur du bord ({limite:g}) à la position de lecture "
                            f"y {lecture_y:g}"
                        )
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
        if r.rangement.bande_haut is not None:
            bande = r.rangement.bande_haut
            dans("rangement → bande_haut → y", "remplissage_y", bande.y)
            dans("rangement → bande_haut → plateau_z", "plateau_z", bande.plateau_z)
            dans("rangement → bande_haut → pousseur_m", "pousseur", bande.pousseur_m)
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
            # Prise double, étape c) : la face de la préhension (pose + face au-dessus du plateau
            # − descente de la tête) reste dans sa course (PR n° 56, points 1 et 2).
            if "prehension_z" in self.axes:
                face_c = (
                    reglage.pose_plateau_z
                    + r.face_au_dessus_plateau_m
                    - r.prise_double.descente_tete_m
                )
                bas_face = self.axes["prehension_z"].course[0]
                if face_c < bas_face - 1e-9:
                    erreurs.append(
                        f"remplissage → formats → {nom} : à l'étape c) de la prise double, la "
                        f"face de la préhension irait à {face_c:.4f} m, sous le bas de sa course "
                        f"({bas_face:g} m)"
                    )
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
            dans(f"formats → {nom} (plateau au vidage)", "plateau_z", plateau)
            # Au poste, bord du seau ≤ verrous → poste_bord_max_z (règle 8).
            bord = min(seau.haut_z, r.verrous.poste_bord_max_z)
            plateau = min(bord - seau.hauteur, self.axes["plateau_z"].course[1])
            dans(f"formats → {nom} (plateau au poste)", "plateau_z", plateau)
        for nom in r.formats:
            if nom not in self.griffe.formats:
                erreurs.append(f"remplissage → formats → {nom} : absent de griffe → formats")
        x, y = self.griffe.seau_remplissage
        # Le mât au-dessus du seau au vidage (à remplissage → tolerance_y_m près).
        if math.hypot(x - r.axe_x, y - r.vidage_y) > r.tolerance_y_m + 1e-9:
            erreurs.append(
                f"griffe → seau_remplissage ({x:g} ; {y:g}) : il faut le mât sur le seau au vidage "
                f"(remplissage → axe_x : {r.axe_x:g}, vidage_y : {r.vidage_y:g})"
            )
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
                y = places.prise_y(self, y)
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
            for x, _ in places.places_fin_de_lot(self, format):
                if x < stockage.piles.fin_de_lot.pile_axe_x_min - 1e-9:
                    erreurs.append(
                        f"stockage → piles → fin_de_lot ({format}) : l'axe d'une pile "
                        f"(x {x:g}) est avant pile_axe_x_min "
                        f"({stockage.piles.fin_de_lot.pile_axe_x_min:g})"
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
            rayon = formats[format].rayon_haut
            for nom, nombre in par_file.items():
                cale = tiroir.cales.get(format, {}).get(nom, 0.0)
                centres = tiroir.centres_x.get(format, {}).get(nom)
                if centres is None:
                    if nombre * tiroir.avance_par_seau_m > longueur - cale + 1e-9:
                        erreurs.append(
                            f"stockage → tiroir → places → {format} → {nom} : {nombre} seaux × "
                            f"{tiroir.avance_par_seau_m:g} m dépassent la butée (file de "
                            f"{longueur - cale:g} m)"
                        )
                    continue
                quoi = f"stockage → tiroir → centres_x → {format} → {nom}"
                if len(centres) != nombre:
                    erreurs.append(f"{quoi} : {len(centres)} centres pour {nombre} places")
                erreurs.extend(
                    _places_en_ligne(quoi, centres, rayon, tiroir.entree_x, tiroir.butee_x - cale)
                )
        for nom, par_file in [*tiroir.cales.items(), *tiroir.centres_x.items()]:
            for file in par_file:
                if file not in tiroir.files:
                    erreurs.append(f"stockage → tiroir ({nom}) : file inconnue « {file} »")
        bande = stockage.bande_haut
        for format, centres in bande.places.items():
            if format not in formats:
                continue
            erreurs.extend(
                _places_en_ligne(
                    f"stockage → bande_haut → places → {format}",
                    centres,
                    formats[format].rayon_haut,
                    bande.entree_x,
                    bande.bord_x_max,
                )
            )
        if bande.active:
            for format, centres in bande.places.items():
                seau = formats.get(format)
                if seau is None or not centres:
                    continue
                if seau.diametre_couvercle is None:
                    erreurs.append(
                        f"stockage → bande_haut : le format « {format} » n'a pas de "
                        "diametre_couvercle (griffe → formats)"
                    )
                elif centres[0] + seau.diametre_couvercle / 2 > bande.bord_x_max + 1e-9:
                    erreurs.append(
                        f"stockage → bande_haut → places → {format} : le bord du couvercle du 1er "
                        f"seau ({centres[0] + seau.diametre_couvercle / 2:g}) dépasse "
                        f"{bande.bord_x_max:g} (hublot)"
                    )
            rangement = self.remplissage.rangement.bande_haut
            if rangement is None:
                erreurs.append(
                    "stockage → bande_haut active : il faut remplissage → rangement → bande_haut"
                )
            elif abs(rangement.y - bande.y) > 1e-9:
                erreurs.append(
                    "stockage → bande_haut → y : le même que remplissage → rangement → bande_haut"
                )
            for format in formats:
                if format not in bande.places:
                    erreurs.append(
                        f"stockage → bande_haut → places : il faut le format « {format} »"
                    )
        for nom in [*tiroir.places, *tiroir.centres_x, *tiroir.cales, *bande.places]:
            if nom not in formats:
                erreurs.append(f"stockage : format « {nom} » absent de griffe → formats")
        # Capacité d'un lot : celle de l'étude doit être celle des places.
        for format, attendue in stockage.capacite_lot.items():
            if format not in formats:
                erreurs.append(f"stockage → capacite_lot : format « {format} » absent de griffe")
            elif set(tiroir.places.get(format, {})) != set(tiroir.files):
                continue  # déjà signalé plus haut
            elif places.capacite_lot(self, format) != attendue:
                erreurs.append(
                    f"stockage → capacite_lot → {format} : {attendue} dans les réglages, mais "
                    f"les places du tiroir et de la bande en donnent "
                    f"{places.capacite_lot(self, format)}"
                )
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
        # Le coin d'inspection reste à la portée du mât de la griffe.
        for quoi, liste in coin:
            for j, i in liste:
                place = quinconce.get(places.nom_bocal(j, i))
                if place is not None and place[0] > stockage.trajets.griffe_x_max + 1e-9:
                    erreurs.append(
                        f"stockage → bocaux → inspection → {quoi} : la place [{j}, {i}] "
                        f"(x {place[0]:g}) est hors de la portée de la griffe "
                        f"(x ≤ {stockage.trajets.griffe_x_max:g})"
                    )
        if places.capacite_boite(self) < 1:
            erreurs.append("stockage → boites : pas une capsule entre le fond et le dessus")
        return erreurs

    def _verifier_spray(self) -> list[str]:
        spray = self.spray
        if spray is None:
            return []
        if self.griffe is None or self.remplissage is None:
            return ["spray : il faut aussi les parties « griffe » (formats) et « remplissage »"]
        erreurs = []
        for quoi, table in (
            ("bras → angles", spray.bras.angles),
            ("dose → par_format_g", spray.dose.par_format_g),
            ("dose → emplacement_par_format", spray.dose.emplacement_par_format),
        ):
            for nom in table:
                if nom not in self.griffe.formats:
                    erreurs.append(f"spray → {quoi} : format de seau inconnu « {nom} »")
            for nom in self.griffe.formats:
                if nom not in table:
                    erreurs.append(f"spray → {quoi} : il manque le format « {nom} »")
        return erreurs

    def _verifier_micropore(self) -> list[str]:
        """Chaque format du micropore est un format de la griffe, chaque rangée tient dans le
        seau ; le moteur d'avance n'a pas la lettre d'un autre axe de sa carte."""
        micropore = self.micropore
        if micropore is None:
            return []
        if self.griffe is None or self.remplissage is None:
            return ["micropore : il faut aussi les parties « griffe » (formats) et « remplissage »"]
        erreurs = []
        for nom, format in micropore.formats.items():
            seau = self.griffe.formats.get(nom)
            if seau is None:
                erreurs.append(f"micropore → formats : format de seau inconnu « {nom} »")
                continue
            if seau.hauteur is None:
                erreurs.append(f"micropore → formats → {nom} : il faut la hauteur du seau (griffe)")
                continue
            for numero, rangee in enumerate(format.rangees, start=1):
                if rangee.hauteur_m >= seau.hauteur:
                    erreurs.append(
                        f"micropore → formats → {nom} → rangée {numero} : à {rangee.hauteur_m:g} m "
                        f"du fond, plus haut que le seau ({seau.hauteur:g} m)"
                    )
        avance = micropore.avance
        for nom, axe in self.axes.items():
            if axe.carte == avance.carte and axe.lettre == avance.lettre:
                erreurs.append(
                    f"micropore → avance : la lettre {avance.lettre} de la carte "
                    f"« {avance.carte} » est déjà celle de l'axe « {nom} »"
                )
        return erreurs

    def _verifier_fermeture(self) -> list[str]:
        """Chaque format de la fermeture est un format de la griffe (avec sa hauteur et son
        diamètre de couvercle) ; Hf, l'approche et le chariot tiennent dans les courses et dans la
        règle 5 (bras du galet : plateau ≤ galet_plateau_max_z)."""
        fermeture = self.fermeture
        if fermeture is None:
            return []
        if self.griffe is None or self.remplissage is None:
            return ["fermeture : il faut aussi les parties « griffe » (formats) et « remplissage »"]
        erreurs = []
        remplissage = self.remplissage
        bas, haut = self.axes["plateau_z"].course
        debut_y, fin_y = self.axes["remplissage_y"].course
        if not debut_y <= fermeture.chariot_y <= fin_y:
            erreurs.append(
                f"fermeture → chariot_y : {fermeture.chariot_y:g} m hors de la course du chariot "
                f"({debut_y:g} à {fin_y:g} m)"
            )
        limite_bras = remplissage.verrous.galet_plateau_max_z
        for nom in fermeture.formats:
            seau = self.griffe.formats.get(nom)
            if seau is None:
                erreurs.append(f"fermeture → formats : format de seau inconnu « {nom} »")
                continue
            if seau.diametre_couvercle is None:
                erreurs.append(f"fermeture → formats → {nom} : il faut diametre_couvercle (griffe)")
            if seau.hauteur is None:
                erreurs.append(f"fermeture → formats → {nom} : il faut la hauteur du seau (griffe)")
                continue
            hf = fermeture.formats[nom].hf_m
            h_app = fermeture.h_approche(nom, bas)
            if not bas <= hf <= haut:
                erreurs.append(
                    f"fermeture → formats → {nom} : Hf {hf:g} m hors de la course du plateau "
                    f"({bas:g} à {haut:g} m)"
                )
            if hf > limite_bras:
                erreurs.append(
                    f"fermeture → formats → {nom} : Hf {hf:g} m, le bras du galet ne tourne que "
                    f"plateau ≤ {limite_bras:g} (règle 5)"
                )
            trop_tot = fermeture.hc(nom) - fermeture.montee.contact_trop_tot_m
            if h_app >= trop_tot:
                erreurs.append(
                    f"fermeture → formats → {nom} : l'approche ({h_app:g} m) doit être sous "
                    f"Hc − contact_trop_tot_m ({trop_tot:g} m) : sinon un contact trop tôt ne se "
                    "voit pas"
                )
            if fermeture.chariot_y < remplissage.dosage_y - remplissage.tolerance_y_m and (
                hf + seau.hauteur > remplissage.verrous.poste_bord_max_z
            ):
                erreurs.append(
                    f"fermeture → formats → {nom} : au poste, le bord du seau serait à "
                    f"{hf + seau.hauteur:g} m (au plus {remplissage.verrous.poste_bord_max_z:g})"
                )
        return erreurs

    def _verifier_couvercle(self) -> list[str]:
        """Les formats, les hauteurs (Z_pose, pile), les vitesses et la position de la pose
        tiennent dans les courses et s'accordent avec la fermeture, le remplissage et le
        stockage."""
        from vidange.stockage import places

        couvercle = self.couvercle
        if couvercle is None:
            return []
        manque = [
            nom
            for nom in ("prehension", "stockage", "fermeture", "remplissage", "griffe")
            if getattr(self, nom) is None
        ]
        if manque:
            return [
                "couvercle : il faut aussi les parties " + ", ".join(f"« {nom} »" for nom in manque)
            ]
        assert self.prehension and self.stockage and self.fermeture and self.remplissage
        assert self.griffe
        erreurs = []
        prehension = self.prehension
        if "couvercle" not in prehension.objets:
            erreurs.append("couvercle : il manque l'objet « couvercle » dans prehension → objets")
        for vitesse in ("couvercle_pile", "couvercle_pose"):
            valeur = getattr(prehension.vitesses, vitesse)
            if valeur is None:
                erreurs.append(f"couvercle : il manque prehension → vitesses → {vitesse}")
            elif valeur > prehension.vitesses.z:
                erreurs.append(
                    f"prehension → vitesses → {vitesse} ({valeur:g}) plus grande que la vitesse "
                    f"de Z ({prehension.vitesses.z:g})"
                )
        bas, haut = self.axes["prehension_z"].course
        haut = min(haut, prehension.haut_z)
        pile, pose, vide = couvercle.pile, couvercle.pose, couvercle.vide
        fond = self.stockage.plateau_z
        bas_pile = fond + pile.epaisseur_dernier_m - prehension.tolerance_m
        if bas_pile < bas:
            erreurs.append(
                f"couvercle : la descente à la pile irait à {bas_pile:g} m, sous la course de la "
                f"tête ({bas:g} à {haut:g} m)"
            )
        if pile.haut_sans_memoire_z + pile.approche_m > haut:
            erreurs.append(
                f"couvercle → pile : haut sans mémoire {pile.haut_sans_memoire_z:g} + approche "
                f"{pile.approche_m:g} m au-dessus de la butée haute ({haut:g} m)"
            )
        if pile.haut_sans_memoire_z <= fond + pile.epaisseur_dernier_m:
            erreurs.append("couvercle → pile → haut_sans_memoire_z doit être au-dessus du fond")
        if vide.lache_kpa <= prehension.vide.perte_kpa:
            erreurs.append(
                f"couvercle → vide → lache_kpa ({vide.lache_kpa:g}) doit être au-dessus de "
                f"prehension → vide → perte_kpa ({prehension.vide.perte_kpa:g})"
            )
        if pose.fenetre_m >= pose.rapide_m:
            erreurs.append("couvercle → pose : fenetre_m doit être plus petit que rapide_m")
        if pose.m8_retombe_m >= pose.degagement_m:
            erreurs.append("couvercle → pose : m8_retombe_m doit être plus petit que degagement_m")
        pont = pose.x - prehension.decalage_mat_x
        debut_x, fin_x = self.axes["pont_x"].course
        debut_y, fin_y = self.axes["chariot_y"].course
        if not debut_x <= pont <= fin_x or not debut_y <= pose.y <= fin_y:
            erreurs.append(
                f"couvercle → pose : l'outil en ({pose.x:g} ; {pose.y:g}) est hors des courses "
                f"(pont à {pont:g} m : {debut_x:g} à {fin_x:g} ; chariot : {debut_y:g} à {fin_y:g})"
            )
        if abs(pose.x - self.remplissage.axe_x) > 1e-6:
            erreurs.append(
                f"couvercle → pose → x ({pose.x:g}) doit être l'axe du plateau "
                f"(remplissage → axe_x : {self.remplissage.axe_x:g})"
            )
        # Le couvercle est pris à 1 cm hors d'axe (pile en y 0,84, outil en y 0,83) : l'outil se
        # pose du même côté, pour que le couvercle arrive centré sur le seau (chariot_y).
        pile_y = self.stockage.piles.couvercles[1]
        decalage = pile_y - places.prise_y(self, pile_y)
        voulu = self.fermeture.chariot_y - decalage
        if abs(pose.y - voulu) > 1e-6:
            erreurs.append(
                f"couvercle → pose → y ({pose.y:g}) : la pile est prise à {decalage:g} m hors "
                f"d'axe, donc l'outil se pose à fermeture → chariot_y − {decalage:g} = {voulu:g}"
            )
        for nom, reglage in couvercle.formats.items():
            seau = self.griffe.formats.get(nom)
            if seau is None or nom not in self.fermeture.formats:
                erreurs.append(
                    f"couvercle → formats → {nom} : format absent de griffe → formats ou de "
                    "fermeture → formats"
                )
                continue
            if seau.diametre_couvercle is None:
                erreurs.append(f"couvercle → formats → {nom} : il faut diametre_couvercle (griffe)")
            zp = self.z_pose_couvercle(nom)
            if zp - pose.sans_contact_m < bas:
                erreurs.append(
                    f"couvercle → formats → {nom} : Z_pose {zp:g} m, la descente de contrôle "
                    f"irait sous la course de la tête ({bas:g} m)"
                )
            if zp + pose.rapide_m > haut:
                erreurs.append(f"couvercle → formats → {nom} : Z_pose {zp:g} m trop haut")
            lente = reglage.descente_lente_z
            if lente is not None and not (zp + pose.rapide_m < lente[1] < lente[0] <= haut):
                erreurs.append(
                    f"couvercle → formats → {nom} → descente_lente_z : il faut "
                    f"Z_pose + rapide_m < fin < début ≤ {haut:g} m"
                )
        for nom in self.fermeture.formats:
            if nom not in couvercle.formats:
                erreurs.append(
                    f"couvercle → formats : le format « {nom} » de la fermeture n'a pas de "
                    "masse de couvercle"
                )
        return erreurs

    def _verifier_bocal_neuf(self) -> list[str]:
        """Les angles tiennent dans la course de la rotation (± 500°, cordon), les cotes dans les
        courses de la tête, du pont et du chariot, les vitesses existent, les boîtes sont celles du
        Stockage."""
        neuf = self.bocal_neuf
        if neuf is None:
            return []
        manque = [
            nom
            for nom in ("prehension", "stockage", "porte_bocal", "mycelium", "griffe")
            if getattr(self, nom) is None
        ]
        if manque:
            return [
                "bocal_neuf : il faut aussi les parties "
                + ", ".join(f"« {nom} »" for nom in manque)
            ]
        assert self.prehension and self.stockage
        prehension = self.prehension
        erreurs = []
        for objet in ("bocal", "capsule"):
            if objet not in prehension.objets:
                erreurs.append(
                    f"bocal_neuf : il manque l'objet « {objet} » dans prehension → objets"
                )
        capsule = prehension.objets.get("capsule")
        if capsule is not None and not capsule.aimants:
            erreurs.append(
                "bocal_neuf : l'objet « capsule » de prehension → objets doit avoir aimants"
            )
        for vitesse in ("bocal_levee", "bocal_col", "bocal_appui"):
            valeur = getattr(prehension.vitesses, vitesse)
            if valeur is None:
                erreurs.append(f"bocal_neuf : il manque prehension → vitesses → {vitesse}")
            elif valeur > prehension.vitesses.z:
                erreurs.append(
                    f"prehension → vitesses → {vitesse} ({valeur:g}) plus grande que la vitesse "
                    f"de Z ({prehension.vitesses.z:g})"
                )
        debut_a, fin_a = self.axes["prehension_a"].course
        dev, vis = neuf.devissage, neuf.vissage
        if not debut_a <= dev.angle_depart_deg <= fin_a:
            erreurs.append(
                f"bocal_neuf → devissage → angle_depart_deg ({dev.angle_depart_deg:g}°) hors de la "
                f"course de la rotation ({debut_a:g} à {fin_a:g}°)"
            )
        elif dev.angle_depart_deg + dev.rotation_max_deg > fin_a:
            erreurs.append(
                f"bocal_neuf → devissage : {dev.angle_depart_deg:g}° + {dev.rotation_max_deg:g}° "
                f"sort de la course de la rotation (jusqu'à {fin_a:g}°)"
            )
        if not debut_a <= vis.angle_depart_deg <= fin_a:
            erreurs.append(
                f"bocal_neuf → vissage → angle_depart_deg ({vis.angle_depart_deg:g}°) hors de la "
                f"course de la rotation ({debut_a:g} à {fin_a:g}°)"
            )
        elif vis.angle_depart_deg - vis.rotation_max_deg < debut_a:
            erreurs.append(
                f"bocal_neuf → vissage : {vis.angle_depart_deg:g}° − {vis.rotation_max_deg:g}° "
                f"sort de la course de la rotation (jusqu'à {debut_a:g}°)"
            )
        if dev.premier_essai_deg > dev.rotation_max_deg:
            erreurs.append("bocal_neuf → devissage : premier_essai_deg après rotation_max_deg")
        if prehension.vissage.angle_deg <= 0:
            erreurs.append("bocal_neuf : prehension → vissage → angle_deg doit être positif")
        boites = self.stockage.boites
        for quoi, nom in (
            ("capsules", neuf.boites.capsules),
            ("couvercles_perces", neuf.boites.couvercles_perces),
        ):
            if nom not in boites.places:
                erreurs.append(
                    f"bocal_neuf → boites → {quoi} : « {nom} » n'est pas dans stockage → boites → "
                    f"places ({', '.join(boites.places)})"
                )
        if neuf.boites.capsules == neuf.boites.couvercles_perces:
            erreurs.append(
                "bocal_neuf → boites : la même boîte pour les capsules et les couvercles"
            )
        bas, haut = self.axes["prehension_z"].course
        haut = min(haut, prehension.haut_z)
        z_capsule = self.stockage.bocaux.capsule_haut_z
        if z_capsule - dev.sans_bocal_m < bas:
            erreurs.append(
                f"bocal_neuf : la descente au bocal irait à {z_capsule - dev.sans_bocal_m:g} m, "
                f"sous la course de la tête ({bas:g} m)"
            )
        sommet_boite = boites.dessus_z + boites.epaisseur_capsule_m
        for quoi, cote in (
            ("capsule du stockage", z_capsule + neuf.approche_m),
            ("boîtes", sommet_boite + neuf.boites.approche_m),
        ):
            if cote > haut:
                erreurs.append(
                    f"bocal_neuf : approche de la {quoi} à {cote:g} m, au-dessus de {haut:g} m"
                )
        if boites.fond_z - neuf.boites.fenetre_m < bas:
            erreurs.append("bocal_neuf : le fond des boîtes est trop bas pour la course de la tête")
        pont_debut, pont_fin = self.axes["pont_x"].course
        y_debut, y_fin = self.axes["chariot_y"].course
        from vidange.stockage import places

        points = {
            **{nom: point for nom, point in places.places_semence(self).items()},
            **{f"boîte {nom}": point for nom, point in boites.places.items()},
        }
        for nom, (x, y) in points.items():
            pont = x - prehension.decalage_mat_x
            if not pont_debut <= pont <= pont_fin or not y_debut <= y <= y_fin:
                erreurs.append(
                    f"bocal_neuf : l'outil en ({x:g} ; {y:g}) ({nom}) est hors des courses (pont à "
                    f"{pont:g} m : {pont_debut:g} à {pont_fin:g} ; chariot : {y_debut:g} à "
                    f"{y_fin:g})"
                )
        couloir = prehension.porte_bocal.couloir
        if couloir is None:
            erreurs.append(
                "bocal_neuf : il faut prehension → porte_bocal → couloir (route d'accès)"
            )
        return erreurs

    def z_pose_couvercle(self, format: str) -> float:
        """Face de la ventouse quand le couvercle est posé, pas clipsé, sur le seau : Z_pose =
        H_app + dessus_pose_z − Hc (fiche, § 2)."""
        assert self.couvercle and self.fermeture
        bas = self.axes["plateau_z"].course[0]
        return (
            self.fermeture.h_approche(format, bas)
            + self.couvercle.pose.dessus_pose_z
            - self.fermeture.hc(format)
        )

    def _verifier_entonnoir(self) -> list[str]:
        """L'objet « entonnoir » existe, les hauteurs tiennent dans la course de la tête, le seuil
        de lâcher est au-dessus de celui de la perte, et la ventouse atteint l'oreille de chaque
        bocal (pont et chariot dans leurs courses)."""
        from vidange.stockage import places

        entonnoir = self.entonnoir
        if entonnoir is None:
            return []
        if self.prehension is None or self.stockage is None:
            return ["entonnoir : il faut aussi les parties « prehension » et « stockage »"]
        erreurs = []
        prehension = self.prehension
        if "entonnoir" not in prehension.objets:
            erreurs.append("entonnoir : il manque l'objet « entonnoir » dans prehension → objets")
        bas, haut = self.axes["prehension_z"].course
        mini = entonnoir.oreille_z - entonnoir.prise.trop_bas_m
        if mini < bas:
            erreurs.append(
                f"entonnoir → oreille_z : la descente de contrôle irait à {mini:g} m, sous la "
                f"course de la tête ({bas:g} à {haut:g} m)"
            )
        if entonnoir.face_transport_z > min(prehension.haut_z, haut):
            erreurs.append(
                f"entonnoir : face de transport {entonnoir.face_transport_z:g} m (oreille_z + "
                f"levee_m) au-dessus de la butée haute ({min(prehension.haut_z, haut):g} m)"
            )
        if entonnoir.vide.lache_kpa <= prehension.vide.perte_kpa:
            erreurs.append(
                f"entonnoir → vide → lache_kpa ({entonnoir.vide.lache_kpa:g}) doit être au-dessus "
                f"de prehension → vide → perte_kpa ({prehension.vide.perte_kpa:g})"
            )
        if entonnoir.bord_col_z <= self.stockage.bocaux.pose_z:
            erreurs.append(
                "entonnoir → bord_col_z doit être au-dessus du bocal posé (bocaux → pose_z)"
            )
        debut_x, fin_x = self.axes["pont_x"].course
        debut_y, fin_y = self.axes["chariot_y"].course
        for nom, (x, y) in places.places_bocaux(self).items():
            pont = x + entonnoir.decalage_oreille_x_m - prehension.decalage_mat_x
            tete_y = y + entonnoir.decalage_oreille_y_m
            if not debut_x <= pont <= fin_x or not debut_y <= tete_y <= fin_y:
                erreurs.append(
                    f"entonnoir : la ventouse n'atteint pas l'oreille du bocal « {nom} » "
                    f"(pont à {pont:g} m, chariot à {tete_y:g} m ; courses {debut_x:g} à "
                    f"{fin_x:g} et {debut_y:g} à {fin_y:g} m)"
                )
                break
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


class ReglagesLot(Modele):
    """Lancer un lot depuis la page web, puis le Go à l'écran (tâche 45 quater)."""

    # Un lot proposé et pas lancé est oublié au bout de (s).
    proposition_max_s: float = Field(gt=0)
    # Boîtier du chariot (micropore, fermeture) lu et battu tous les (s), pendant un lot.
    fond_periode_s: float = Field(gt=0, le=1)
    # Le lot tourne-t-il encore ? Regardé tous les (s).
    suivi_periode_s: float = Field(gt=0, le=5)


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
    lot: ReglagesLot

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
    ou une pesée qui change (poids posé, boîte qui ne répond plus, radio du plateau muette)."""

    # Compté depuis le début de cette étape (« module.etape ») ; sans « apres » : depuis le
    # début de la simulation.
    apres: (
        Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")] | None
    ) = None
    attente_s: float = Field(ge=0)
    # Entrée tout-ou-rien de docs/entrees-sorties.yaml, actionnée ou non...
    capteur: Nom | None = None
    actionne: bool | None = None
    # ... ou pesée du poste du fût (pesee_fut) : poids lu en kg (la radio parle), boîte qui ne
    # répond plus (debranchee), ou radio du plateau muette (plateau endormi, accu vide).
    pesee: Nom | None = None
    kg: float | None = None
    debranchee: bool = False
    radio_muette: bool = False
    # ... ou mesure de docs/entrees-sorties.yaml (analogique ou ozone) qui prend cette valeur,
    # dans l'unité du signal (ozone_dehors : ppm).
    mesure: Nom | None = None
    valeur: float | None = None

    @model_validator(mode="after")
    def _une_seule_chose(self) -> "EvenementSimule":
        capteur = self.capteur is not None and self.actionne is not None
        choses = (self.kg is not None) + self.debranchee + self.radio_muette
        pesee = self.pesee is not None and choses == 1
        mesure = self.mesure is not None and self.valeur is not None
        reste_capteur = self.capteur is not None or self.actionne is not None
        reste_pesee = self.pesee is not None or choses > 0
        reste_mesure = self.mesure is not None or self.valeur is not None
        if not (
            (capteur and not reste_pesee and not reste_mesure)
            or (pesee and not reste_capteur and not reste_mesure)
            or (mesure and not reste_capteur and not reste_pesee)
        ):
            raise ValueError(
                "écrire « capteur » et « actionne », ou « pesee » avec « kg », "
                "« debranchee: true » ou « radio_muette: true », ou « mesure » et « valeur » "
                "(une seule chose par événement)"
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
    # Seaux pleins déjà rangés au départ, par file du tiroir (pour jouer un lot plein sans
    # simuler tous les seaux).
    files_pleines: dict[Nom, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)


class BocalNeufSimule(Modele):
    """Le stockage imaginaire du bocal neuf de semence (tâche 19 quater) : `bocaux` bocaux de la
    variété du lot sur les premières places de semence, des capsules déjà dans la boîte des
    capsules, des couvercles percés dans l'autre. La physique imaginaire : le filet de la capsule
    se libère à `devisse_deg` degrés de dévissage ; le couvercle percé cale (moteur) à `filet_deg`
    degrés de vissage ; la tôle et la capsule se compriment de `raideur_n_m` (N par m). Tout est
    d'EXEMPLE : c'est la machine imaginaire."""

    bocaux: int = Field(ge=0)
    capsules: int = Field(default=0, ge=0)
    couvercles_perces: int = Field(ge=0)
    devisse_deg: float = Field(gt=0)
    filet_deg: float = Field(gt=0)
    raideur_n_m: float = Field(gt=0)


class CycleSimule(Modele):
    """Le lot du mode seaux joué par « vidange-simulateur cycle » (tâche 45) : des seaux vides d'un
    format, pris sur les piles chargées au départ, remplis, dosés et rangés par le même code que
    sur la machine. Les seaux sont nommés `prefixe` + numéro (à partir de `premier`)."""

    format: Nom
    variete: str
    seaux: int = Field(ge=1)
    prefixe: str = Field(min_length=1)
    premier: int = Field(default=1, ge=0)
    chiffres: int = Field(default=4, ge=1, le=9)
    piles: dict[Nom, PileSimulee] = Field(min_length=1)
    files_pleines: dict[Nom, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    # Numéros (dans le lot, à partir de 1) des seaux posés avec un 2e seau emboîté (prise double).
    prises_doubles: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list)
    # Angle des oreilles de l'anse vu par la fausse caméra (°), le même pour tous les seaux.
    anse_deg: float = 0.0
    # La pile de couvercles du stockage imaginaire (tâche 41 bis) : combien, et le pas d'empilage
    # (m, À MESURER sur les vrais couvercles).
    couvercles: int = Field(default=0, ge=0)
    pas_couvercles_m: float = Field(default=0.009, gt=0)

    # Le bocal neuf de semence (tâche 19 quater) : bocaux de semence du stockage imaginaire.
    bocal_neuf: BocalNeufSimule | None = None

    @model_validator(mode="after")
    def _verifier_seaux(self) -> "CycleSimule":
        sur_les_piles = sum(pile.nombre for pile in self.piles.values())
        erreurs = []
        if self.seaux > sur_les_piles:
            erreurs.append(
                f"{self.seaux} seaux à remplir, mais seulement {sur_les_piles} sur les piles"
            )
        autres = sorted({p.format for p in self.piles.values()} - {self.format})
        if autres:
            erreurs.append(f"piles d'un autre format que {self.format} : {', '.join(autres)}")
        trop = [n for n in self.prises_doubles if n > self.seaux]
        if trop:
            erreurs.append(f"prises_doubles : seau n° {trop[0]} au-delà des {self.seaux} seaux")
        if erreurs:
            raise ValueError(" ; ".join(erreurs))
        return self


class NettoyageSimule(Modele):
    """L'enceinte imaginaire du Nettoyage : store, air, particules, surpression, ozone."""

    # Le store met course_s à monter ou descendre (Karulium tient le bouton) ; arrivé en bas, le
    # reed rebondit (ouvert / fermé toutes les rebond_pas_s) pendant rebond_s.
    course_s: float = Field(gt=0)
    rebond_s: float = Field(ge=0)
    rebond_pas_s: float = Field(gt=0)
    # Particules (µg/m³) : dehors (le conteneur), dedans quand le store est ouvert ; store fermé,
    # ventilateur à plein, le dedans tend vers fond × dehors (air filtré par le HEPA) avec cette
    # constante de temps (s ; plus longue quand le ventilateur tourne moins vite).
    particules_dehors: float = Field(gt=0)
    particules_ouvert: float = Field(gt=0)
    particules_fond: float = Field(gt=0)
    constante_particules_s: float = Field(gt=0)
    # Surpression (Pa) avec une consigne de 10 V, store fermé ; constante de temps (s) ; facteur
    # quand le HEPA est colmaté (scénario « purge_trop_longue »).
    pression_10v_pa: float = Field(gt=0)
    constante_pression_s: float = Field(gt=0)
    facteur_hepa_colmate: float = Field(gt=0, le=1)
    # Ozone dedans (ppm) : montée quand le générateur est alimenté, demi-vie (s).
    montee_ozone_ppm_s: float = Field(gt=0)
    demi_vie_ozone_s: float = Field(gt=0)


class MicroporeSimule(Modele):
    """La tête du micropore imaginaire (scénario « remplissage ») : ses gestes appris (sur la vraie
    machine : donnees/micropore-appris.yaml, appris par Karulium) et ce que voit sa caméra."""

    appris: GestesAppris
    # Le premier trou de chaque rangée est vu à tant (°) de l'angle du plateau au début du tour
    # de repérage ; les autres sont répartis sur le tour.
    premier_trou_deg: float = 20.0


class FermetureSimulee(Modele):
    """Le couvercle imaginaire de la Fermeture des seaux (scénario « remplissage »)."""

    # Raideur du couvercle contre le rouleau (N par m de plateau au-dessus du contact).
    raideur_n_par_m: float = Field(gt=0)
    # Écart (m) entre la vraie hauteur de contact et Hc (négatif : le couvercle touche plus tôt).
    ecart_contact_m: float = 0.0


class EntonnoirSimule(Modele):
    """L'entonnoir imaginaire (scénario « entonnoir »)."""

    # Les bocaux du lot à remplir (noms du quinconce du Stockage), dans le désordre : le Pi choisit
    # l'ordre.
    bocaux: list[Nom] = Field(min_length=1)
    # Durée du versement de la griffe dans un bocal (s).
    verse_s: float = Field(ge=0)


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
    # Le lot du mode seaux (« vidange-simulateur cycle », tâche 45).
    cycle: CycleSimule | None = None
    # L'enceinte imaginaire du Nettoyage (store, air, ozone).
    nettoyage: NettoyageSimule | None = None
    # La tête du micropore imaginaire (gestes appris, trous vus par la caméra).
    micropore: MicroporeSimule | None = None
    # Le couvercle imaginaire de la Fermeture des seaux.
    fermeture: FermetureSimulee | None = None
    # L'entonnoir imaginaire (lot de bocaux, durée du versement).
    entonnoir: EntonnoirSimule | None = None


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


class PeseeLente(Modele):
    """Une pesée du bus lue moins souvent que les autres (la boîte du poste du fût)."""

    # Au plus une question toutes les ... (s).
    espacement_s: float = Field(gt=0, le=60)
    # Mesure plus vieille que ça (ms) : la pesée est dite muette (remplace age_max_ms).
    age_max_ms: int = Field(gt=0, le=60000)

    @model_validator(mode="after")
    def _age(self) -> "PeseeLente":
        if self.age_max_ms <= self.espacement_s * 1000:
            raise ValueError(
                f"age_max_ms ({self.age_max_ms}) doit dépasser espacement_s "
                f"({self.espacement_s:g} s) : sinon la pesée serait toujours dite muette"
            )
        return self


class AccuPlateauFut(Modele):
    """Accu 18650 du plateau de pesée du poste du fût : seuils des alertes (tâche 17 bis)."""

    # Tension (V) : au moins bon_v = bon ; sous recharger_v : alerte « recharger le plateau » ;
    # sous bientot_absente_v : alerte forte « pesée bientôt absente ».
    bon_v: float = Field(gt=0, le=5)
    recharger_v: float = Field(gt=0, le=5)
    bientot_absente_v: float = Field(gt=0, le=5)
    # Plateau au poste depuis plus de ... (s) sans le « 5 V de la recharge sans contact présent »
    # (registre 8, bit 1 = valeur 2 ; vrai aussi accu plein) : alerte « recharge sans contact en
    # panne ? ».
    sans_recharge_max_s: float = Field(gt=0, le=86400)

    @model_validator(mode="after")
    def _ordre(self) -> "AccuPlateauFut":
        if not self.bientot_absente_v < self.recharger_v <= self.bon_v:
            raise ValueError(
                "seuils de l'accu dans le désordre : il faut bientot_absente_v "
                f"({self.bientot_absente_v:g}) < recharger_v ({self.recharger_v:g}) ≤ bon_v "
                f"({self.bon_v:g})"
            )
        return self


# Broches de l'ESP32-C3 (numéros GPIO, de 0 à 21) que les programmes du poste du fût ne prennent
# jamais : celles de la mémoire flash (11 à 17 sur beaucoup de cartes) et celles de l'USB (18, 19 :
# le câble des mises à jour et de la fenêtre texte).
BROCHES_INTERDITES_ESP32C3 = {
    **{broche: "mémoire flash" for broche in range(11, 18)},
    18: "USB",
    19: "USB",
}
# Seules les broches 0 à 5 réveillent l'ESP32-C3 endormi ; 0 à 4 sont les entrées analogiques ADC1
# (l'ADC2 ne marche pas quand la radio est allumée).
BROCHES_REVEIL_ESP32C3 = range(0, 6)
BROCHES_ADC1_ESP32C3 = range(0, 5)
# Points de la courbe de l'accu au plus (taille du tableau dans le programme du plateau).
POINTS_COURBE_ACCU_MAX = 16

BrocheEsp32c3 = Annotated[int, Field(ge=0, le=21)]
AdresseRadio = Annotated[
    str, StringConstraints(pattern=r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$", to_upper=True)
]


def _verifier_broches_esp32c3(broches: dict[str, int | None]) -> list[str]:
    erreurs = []
    deja_vues: dict[int, str] = {}
    for nom, broche in broches.items():
        if broche is None:
            continue
        if broche in BROCHES_INTERDITES_ESP32C3:
            erreurs.append(
                f"{nom} ({broche}) : broche de l'ESP32-C3 réservée "
                f"({BROCHES_INTERDITES_ESP32C3[broche]})"
            )
        autre = deja_vues.setdefault(broche, nom)
        if autre != nom:
            erreurs.append(f"la broche {broche} est prise deux fois ({autre} et {nom})")
    return erreurs


class RadioPosteFut(Modele):
    """ESP-NOW entre le plateau et la boîte du poste : chaque carte prend son adresse d'ici."""

    adresse_plateau: AdresseRadio
    adresse_boite: AdresseRadio
    # Canal radio, le même pour les deux cartes.
    canal: int = Field(ge=1, le=13)
    # Puissance d'émission maximale (dBm).
    puissance_dbm: int = Field(ge=2, le=20)

    @model_validator(mode="after")
    def _adresses(self) -> "RadioPosteFut":
        erreurs = []
        for nom in ("adresse_plateau", "adresse_boite"):
            adresse = getattr(self, nom)
            premier = int(adresse[:2], 16)
            if premier & 1:
                erreurs.append(
                    f"{nom} ({adresse}) : adresse de groupe (premier octet impair), il faut "
                    "l'adresse d'une seule carte (exemple : 02:50:46:00:00:01)"
                )
            if adresse == "00:00:00:00:00:00":
                erreurs.append(f"{nom} : l'adresse 00:00:00:00:00:00 n'est pas permise")
        if self.adresse_plateau == self.adresse_boite:
            erreurs.append(
                f"adresse_plateau et adresse_boite sont les mêmes ({self.adresse_plateau})"
            )
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class BrochesPlateauFut(Modele):
    hx711_dt: BrocheEsp32c3
    hx711_sck: BrocheEsp32c3
    # Contact reed de réveil, entre la broche et le 0 V (fermé = au poste).
    reed: BrocheEsp32c3
    # Pont diviseur de l'accu (entrée analogique).
    accu: BrocheEsp32c3
    # 5 V de la recharge sans contact et 5 V de l'USB-C de secours, par un pont diviseur
    # (1 = présent).
    recharge_5v: BrocheEsp32c3
    usb_5v: BrocheEsp32c3
    voyant: BrocheEsp32c3 | None = None

    @model_validator(mode="after")
    def _verifier(self) -> "BrochesPlateauFut":
        erreurs = _verifier_broches_esp32c3(self.model_dump())
        if self.reed not in BROCHES_REVEIL_ESP32C3:
            erreurs.append(
                f"reed ({self.reed}) : seules les broches 0 à 5 réveillent l'ESP32-C3 endormi"
            )
        if self.accu not in BROCHES_ADC1_ESP32C3:
            erreurs.append(
                f"accu ({self.accu}) : il faut une entrée analogique ADC1 (broche 0 à 4)"
            )
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class PlateauFut(Modele):
    """Programme de l'ESP32-C3 du plateau de pesée (poste_fut_radio/plateau)."""

    broches: BrochesPlateauFut
    # Voyant allumé quand sa broche est à 0 (cas de beaucoup de petites cartes).
    voyant_actif_bas: bool = False
    # Cadence du HX711, choisie sur sa carte par la broche RATE (à la masse : 10). Sert à vérifier
    # les autres chiffres.
    mesures_par_seconde_hx711: Literal[10, 80]
    # Une trame radio toutes les ... (ms), avec la moyenne des « moyenne_de » dernières mesures.
    periode_trame_ms: int = Field(ge=100, le=10000)
    moyenne_de: int = Field(ge=1, le=16)
    # Plus de mesure du HX711 depuis ce temps (ms) : « HX711 muet ».
    sans_mesure_ms: int = Field(ge=50, le=10000)
    # Reed ouvert depuis ce temps (s) : la carte s'endort.
    sommeil_apres_s: float = Field(ge=1, le=3600)
    # Pont diviseur de l'accu : tension de l'accu / tension sur la broche.
    rapport_pont_accu: float = Field(gt=1, le=10)
    # Niveau de l'accu : points (tension en mV, %), tension croissante.
    courbe_accu: list[tuple[int, int]] = Field(min_length=2, max_length=POINTS_COURBE_ACCU_MAX)
    chien_de_garde_ms: int = Field(ge=100, le=60000)
    periode_affichage_ms: int = Field(ge=100, le=600000)

    @model_validator(mode="after")
    def _verifier(self) -> "PlateauFut":
        erreurs = []
        periode_mesure_ms = 1000 / self.mesures_par_seconde_hx711
        if self.sans_mesure_ms < 3 * periode_mesure_ms:
            erreurs.append(
                f"sans_mesure_ms ({self.sans_mesure_ms}) doit valoir au moins 3 fois le temps "
                f"entre deux mesures du HX711 ({periode_mesure_ms:g} ms)"
            )
        if self.moyenne_de * periode_mesure_ms > self.periode_trame_ms * 4:
            erreurs.append(
                f"moyenne_de ({self.moyenne_de}) : la moyenne prendrait plus de 4 trames de "
                "mesures (trop lente)"
            )
        if self.sommeil_apres_s * 1000 < 2 * self.periode_trame_ms:
            erreurs.append("sommeil_apres_s doit laisser passer au moins 2 trames")
        tensions = [mv for mv, _ in self.courbe_accu]
        niveaux = [pct for _, pct in self.courbe_accu]
        if any(b <= a for a, b in zip(tensions, tensions[1:], strict=False)):
            erreurs.append("courbe_accu : les tensions (mV) doivent aller en montant")
        if any(b < a for a, b in zip(niveaux, niveaux[1:], strict=False)):
            erreurs.append("courbe_accu : les niveaux (%) ne doivent jamais redescendre")
        if any(not 0 <= pct <= 100 for pct in niveaux):
            erreurs.append("courbe_accu : un niveau doit aller de 0 à 100 %")
        if any(not 1000 <= mv <= 6000 for mv in tensions):
            erreurs.append("courbe_accu : une tension doit aller de 1000 à 6000 mV")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class BrochesBoiteFut(Modele):
    # L'émetteur-récepteur RS485 3,3 V (MAX3485) : DI, RO, et DE et /RE reliées (1 = parler).
    rs485_tx: BrocheEsp32c3
    rs485_rx: BrocheEsp32c3
    rs485_sens: BrocheEsp32c3
    voyant: BrocheEsp32c3 | None = None

    @model_validator(mode="after")
    def _verifier(self) -> "BrochesBoiteFut":
        erreurs = _verifier_broches_esp32c3(self.model_dump())
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class BoiteFut(Modele):
    """Programme de l'ESP32-C3 de la boîte du poste (poste_fut_radio/boite)."""

    broches: BrochesBoiteFut
    voyant_actif_bas: bool = False
    # Rien reçu du plateau depuis ce temps (ms) : bit « radio muette » (registre 4, valeur 4).
    radio_muette_ms: int = Field(ge=200, le=60000)
    chien_de_garde_ms: int = Field(ge=100, le=60000)
    periode_affichage_ms: int = Field(ge=100, le=600000)


class PosteFutRadio(Modele):
    """Programmes des 2 ESP32-C3 du poste du fût (tâche 17 ter, dossier poste_fut_radio/)."""

    radio: RadioPosteFut
    plateau: PlateauFut
    boite: BoiteFut

    @model_validator(mode="after")
    def _verifier(self) -> "PosteFutRadio":
        if self.boite.radio_muette_ms < 2 * self.plateau.periode_trame_ms:
            raise ValueError(
                f"boite → radio_muette_ms ({self.boite.radio_muette_ms}) doit valoir au moins "
                f"2 fois plateau → periode_trame_ms ({self.plateau.periode_trame_ms}) : sinon "
                "une seule trame perdue dirait « radio muette »"
            )
        return self


class BrochesI2cPesee(Modele):
    """Les deux fils de l'I2C de la carte du plateau du remplissage (numéros GPIO du RP2040)."""

    sda: BrocheRp2040
    scl: BrocheRp2040

    @property
    def bloc_i2c(self) -> int:
        """Bloc I2C du RP2040 (0 ou 1) qui sort sur ces broches."""
        return (self.sda // 2) % 2

    @model_validator(mode="after")
    def _verifier_broches(self) -> "BrochesI2cPesee":
        erreurs = []
        # Sur le RP2040, la broche n sort le bloc I2C (n // 2) % 2, en SDA si n est pair.
        if self.sda % 2 != 0:
            erreurs.append(f"sda ({self.sda}) doit être une broche paire")
        if self.scl % 2 != 1:
            erreurs.append(f"scl ({self.scl}) doit être une broche impaire")
        if not erreurs and (self.sda // 2) % 2 != (self.scl // 2) % 2:
            erreurs.append(
                f"sda ({self.sda}) et scl ({self.scl}) ne sont pas du même bloc I2C "
                "(I2C0 : SDA 0, 4, 8... SCL 1, 5, 9... ; I2C1 : SDA 2, 6, 10... SCL 3, 7, 11...)"
            )
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class VoieServoPesee(Modele):
    """Une voie de la PCA9685 : un servo, sa plage d'angle et les largeurs d'impulsion qui vont
    avec (fiche du servo). Le Pi demande un angle, la carte en fait une impulsion."""

    canal: int = Field(ge=0, le=15)
    # Angle de l'axe du servo (°) à la plus petite et à la plus grande impulsion. Hors de cette
    # plage, la carte refuse l'ordre.
    angle_min_deg: float = Field(ge=-3000, le=3000)
    angle_max_deg: float = Field(ge=-3000, le=3000)
    impulsion_min_us: int = Field(gt=0)
    impulsion_max_us: int = Field(gt=0)

    @model_validator(mode="after")
    def _verifier(self) -> "VoieServoPesee":
        if self.angle_min_deg >= self.angle_max_deg:
            raise ValueError(
                f"angle_min_deg ({self.angle_min_deg:g}) doit être plus petit que "
                f"angle_max_deg ({self.angle_max_deg:g})"
            )
        if self.impulsion_min_us >= self.impulsion_max_us:
            raise ValueError(
                f"impulsion_min_us ({self.impulsion_min_us}) doit être plus petite que "
                f"impulsion_max_us ({self.impulsion_max_us})"
            )
        return self

    @property
    def angle_min_dix(self) -> int:
        """En dixièmes de degré, comme dans les registres de la carte."""
        return round(self.angle_min_deg * 10)

    @property
    def angle_max_dix(self) -> int:
        return round(self.angle_max_deg * 10)


class Pca9685Pesee(Modele):
    """La PCA9685 (16 sorties PWM) du boîtier du chariot."""

    adresse: int = Field(ge=0x40, le=0x6F)
    # Fréquence des impulsions des servos (Hz) : 50 en général. La puce va de 24 à 1526 Hz.
    frequence_pwm_hz: int = Field(ge=24, le=1526)
    # Oscillateur interne de la puce (Hz) : 25 MHz à environ 10 % près.
    horloge_hz: int = Field(ge=20_000_000, le=30_000_000)
    # Attente après le réveil de la puce avant de lui parler (µs) : 500 au moins (fiche).
    reveil_us: int = Field(ge=500, le=100_000)
    # Une voie par servo, avec le nom de son signal dans entrees-sorties.yaml. L'ordre est celui
    # des registres : la première voie est le registre 16, la suivante le 17...
    voies: dict[Nom, VoieServoPesee] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _verifier(self) -> "Pca9685Pesee":
        erreurs = []
        # prescale = arrondi(horloge / (4096 × fréquence)) − 1, de 3 à 255 dans la puce.
        prescale = round(self.horloge_hz / (4096 * self.frequence_pwm_hz)) - 1
        if not 3 <= prescale <= 255:
            erreurs.append(
                f"frequence_pwm_hz ({self.frequence_pwm_hz}) avec horloge_hz ({self.horloge_hz}) "
                f"demande un réglage de {prescale}, la puce accepte de 3 à 255"
            )
        periode_us = 1e6 / self.frequence_pwm_hz
        canaux: dict[int, str] = {}
        for nom, voie in self.voies.items():
            if voie.impulsion_max_us >= periode_us:
                erreurs.append(
                    f"voies → {nom} : impulsion_max_us ({voie.impulsion_max_us}) ne tient pas "
                    f"dans la période de {periode_us:.0f} µs ({self.frequence_pwm_hz} Hz)"
                )
            autre = canaux.setdefault(voie.canal, nom)
            if autre != nom:
                erreurs.append(
                    f"voies : le canal {voie.canal} est pris deux fois ({autre} et {nom})"
                )
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class Vl6180xPesee(Modele):
    """Le capteur de distance VL6180X (temps de vol) du boîtier du chariot."""

    # Le signal de entrees-sorties.yaml qui le décrit (type mesure, en mm).
    signal: Nom
    adresse: int = Field(ge=0x08, le=0x77)
    # Entre deux mesures (ms).
    periode_ms: int = Field(ge=10, le=10_000)
    # Entre deux « la mesure est-elle prête ? » (ms).
    sondage_ms: int = Field(ge=1, le=1000)
    # Une mesure lancée qui n'est pas finie au bout de ce temps (ms) : capteur muet.
    delai_max_ms: int = Field(ge=10, le=10_000)

    @model_validator(mode="after")
    def _verifier(self) -> "Vl6180xPesee":
        if self.sondage_ms >= self.periode_ms:
            raise ValueError(
                f"sondage_ms ({self.sondage_ms}) doit être plus petit que periode_ms "
                f"({self.periode_ms})"
            )
        if self.delai_max_ms <= self.sondage_ms:
            raise ValueError(
                f"delai_max_ms ({self.delai_max_ms}) doit dépasser sondage_ms ({self.sondage_ms})"
            )
        return self


# Silence de fin de trame du Modbus à 115 200 bauds (µs) : une transaction I2C plus longue
# couperait en deux la trame d'une autre carte que la carte entend passer (pesee/src/modbus.h).
SILENCE_MODBUS_US = 1750


class I2cPesee(Modele):
    """L'I2C d'UNE carte de pesée : celle du plateau du remplissage, avec la PCA9685 des servos
    et le VL6180X. Les autres cartes n'ont pas d'I2C. Copié dans le programme de cette carte quand
    on le fabrique ; les registres sont décrits dans pesee/README.md."""

    # La carte (signal « carte_pesee » de entrees-sorties.yaml) qui porte cet I2C.
    carte: Nom
    broches: BrochesI2cPesee
    frequence_hz: Literal[100_000, 400_000]
    # Une transaction I2C qui n'a pas fini au bout de ce temps (µs) est abandonnée (bus bloqué).
    delai_transaction_us: int = Field(ge=100)
    # Après une panne d'une puce, nouvel essai toutes les ... (ms).
    reessai_ms: int = Field(ge=50, le=60_000)
    # Plus d'ordre du Pi depuis ce temps (ms) : la carte GARDE les angles (aucun mouvement) et le
    # dit dans le registre 12.
    silence_pi_ms: int = Field(ge=100, le=60_000)
    pca9685: Pca9685Pesee
    vl6180x: Vl6180xPesee

    @model_validator(mode="after")
    def _verifier(self) -> "I2cPesee":
        erreurs = []
        if self.delai_transaction_us >= SILENCE_MODBUS_US:
            erreurs.append(
                f"delai_transaction_us ({self.delai_transaction_us}) doit rester sous "
                f"{SILENCE_MODBUS_US} µs : une transaction I2C plus longue couperait en deux une "
                "trame du bus des pesées"
            )
        if self.pca9685.adresse == self.vl6180x.adresse:
            erreurs.append(
                f"pca9685 et vl6180x ont la même adresse I2C (0x{self.vl6180x.adresse:02X})"
            )
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class ReglagesPesees(Modele):
    """pesees.yaml : les pesées du bus RS485 des pesées (cartes RP2040 + HX711, et la boîte du
    poste du fût)."""

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
    # Pesées lues moins souvent, avec leur propre âge maximal (la boîte du poste du fût).
    lentes: dict[Nom, PeseeLente] = {}
    # Plus aucune carte ne répond : nouvel essai toutes les ... (s).
    reconnexion_s: float = Field(gt=0, le=3600)
    etalonnage: dict[Nom, EtalonnagePesee] = Field(min_length=1)
    # Accu du plateau du poste du fût (seulement s'il y a une boîte du poste sur le bus).
    accu_plateau_fut: AccuPlateauFut | None = None
    # Programmes des 2 ESP32-C3 du poste du fût (seulement s'il y a une boîte du poste).
    poste_fut_radio: PosteFutRadio | None = None
    # Balances des 4 flacons du spray (cellules de 1 kg + HX711 sur la carte n° 5), emplacements
    # 1 à 4 : brut_par_kg compte par kilogramme. Copié dans le programme de la carte quand on le
    # fabrique (tâche 39 bis) : c'est la carte qui pèse les doses.
    balances_spray: dict[Annotated[int, Field(ge=1, le=4)], EtalonnagePesee] | None = None
    # L'I2C de la carte du plateau du remplissage (servos et capteur de distance). Les autres
    # cartes de pesée n'en ont pas : un réglage par carte, pas pour toutes.
    i2c: I2cPesee | None = None

    @model_validator(mode="after")
    def _verifier_cartes(self) -> "ReglagesPesees":
        erreurs = []
        if self.i2c is not None:
            if self.i2c.carte not in self.etalonnage:
                erreurs.append(f"i2c → carte : « {self.i2c.carte} » n'est pas une carte de pesée")
            prises = {
                nom: broche
                for nom, broche in self.broches.model_dump().items()
                if broche is not None
            }
            for nom, broche in (("sda", self.i2c.broches.sda), ("scl", self.i2c.broches.scl)):
                for autre, numero in prises.items():
                    if numero == broche:
                        erreurs.append(
                            f"la broche {broche} est prise deux fois (i2c → broches → {nom} "
                            f"et broches → {autre})"
                        )
        for nom in dict.fromkeys(self.tour):
            if nom not in self.etalonnage:
                erreurs.append(f"tour : « {nom} » n'a pas d'étalonnage (section etalonnage)")
        for nom in self.etalonnage:
            if nom not in self.tour:
                erreurs.append(f"etalonnage : « {nom} » n'est jamais lue (absente de « tour »)")
        for nom in self.lentes:
            if nom not in self.tour:
                erreurs.append(f"lentes : « {nom} » n'est jamais lue (absente de « tour »)")
        if self.balances_spray is not None and sorted(self.balances_spray) != [1, 2, 3, 4]:
            erreurs.append("balances_spray : il faut l'étalonnage des 4 emplacements (1 à 4)")
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


class GeometrieInspection(Modele):
    """Où est la caméra de la tête du micropore (`cam_inspection` du projet mécanique) par rapport
    à l'axe du plateau, et où est le rouleau. Azimuts : ° depuis +x, vus de dessus (sens inverse
    des aiguilles d'une montre), dans le repère du portique."""

    # Objectif par rapport à l'axe du plateau (ΔX, ΔY en m) : fiche du micropore, figé
    # (azimut −122°).
    decalage_m: tuple[float, float]
    # Azimut visé par l'axe optique de la caméra ; None : elle vise l'axe du plateau.
    cap_deg: float | None = Field(default=None, ge=-180, le=180)
    # Azimut du rouleau vu de l'axe du plateau : la tête vient du mur (y petit), donc côté −y
    # (direction d'escamotage de la fiche) : EXEMPLE tant que la tête n'est pas montée.
    rouleau_azimut_deg: float = Field(ge=-180, le=180)
    # Rayon du flanc à la hauteur du QR (m) : sert seulement si la caméra ne vise pas l'axe.
    rayon_qr_m: float = Field(gt=0)
    # La caméra est fixe sur la plaque (elle ne recule pas avec l'escamotage) : centre de son
    # objectif à cette hauteur (m, fil Micropore du 07/11/2026). Elle ne voit qu'UNE rangée de
    # trous par image (rangées écartées de 10 à 17 cm) : ±3,5 cm en hauteur, dont `vue_utile_m`
    # (±2,5 cm) utiles. Le plateau se met à « objectif_z_m − hauteur de la rangée » (tour de
    # repérage de la rangée) ; la pose se fait à « ruban_z − hauteur » (9 mm plus bas).
    objectif_z_m: float = Field(gt=0)
    vue_utile_m: float = Field(gt=0)
    # Hauteur du centre de l'étiquette QR au-dessus du fond du seau (m), la même sur tous les
    # formats (consigne : 14 cm, entre deux trous) : plateau_lecture_qr = objectif − cette hauteur.
    etiquette_hauteur_m: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier(self) -> "GeometrieInspection":
        if self.decalage_m == (0, 0):
            raise ValueError("decalage_m : la caméra n'est pas sur l'axe du plateau")
        return self


class LectureFlancInspection(Modele):
    """Le QR du flanc lu pendant que le plateau tourne le seau (Remplissage, étape
    `orienter_l_anse`) et le tour de repérage du micropore (QR, trous)."""

    # Attente (s) entre deux regards sur la vidéo quand il n'y a pas d'image nouvelle.
    pause_s: float = Field(gt=0, le=1)
    # Lectures du QR à des angles différents pour trouver l'angle où il passe au centre de
    # l'image. Une seule lecture ne compte que si le QR est à moins de `centre_tolerance_px`
    # du centre.
    lectures_min: int = Field(ge=1)
    centre_tolerance_px: float = Field(gt=0)
    # Le centre trouvé ne peut être qu'à cette distance (°) des angles où le QR a été lu.
    marge_deg: float = Field(ge=0)
    # Le QR repasse devant la caméra à chaque tour : deux lectures séparées de plus que ça (°)
    # sont de deux passages.
    ecart_passage_deg: float = Field(gt=0)
    # Écart attaches de l'anse / QR (°) d'un seau dont l'écart n'est pas enregistré : EXEMPLE.
    ecart_attaches_defaut_deg: float = Field(ge=-90, lt=90)


class TrousInspection(Modele):
    """Les trous du seau (Ø ≈ 1 cm) vus pendant le tour de repérage : taches rondes qui
    tranchent sur la paroi."""

    diametre_mm: float = Field(gt=0)
    # Un trou a un diamètre dans diametre ± cette part.
    tolerance_diametre: float = Field(gt=0, lt=1)
    circularite_min: float = Field(gt=0, le=1)
    # Écart de gris (0 à 255) avec la paroi pour qu'une tache compte.
    contraste_min: float = Field(gt=0, le=255)
    # Un trou suivi d'une image à l'autre ne change pas de hauteur de plus (points).
    suivi_max_y_px: float = Field(gt=0)
    # Un trou suivi d'une image à l'autre ne bouge pas de plus (points).
    suivi_max_px: float = Field(gt=0)
    # Deux trous vus à moins de tant de degrés sont le même (début et fin du tour).
    fusion_deg: float = Field(gt=0)


class PieceInspection(Modele):
    """Le contrôle du morceau de micropore posé (geste 11 de la fiche)."""

    longueur_mm: float = Field(gt=0)
    largeur_mm: float = Field(gt=0)
    # Un morceau mal coupé : longueur ou largeur hors de la cote ± cette part.
    tolerance_taille: float = Field(gt=0, lt=1)
    # Un morceau de travers : son grand côté s'écarte de l'horizontale de plus que ça (°).
    inclinaison_max_deg: float = Field(gt=0, lt=90)
    contraste_min: float = Field(gt=0, le=255)
    # Le trou doit rester sous le morceau avec cette marge (mm) de chaque côté.
    marge_mm: float = Field(ge=0)


class InspectionVision(Modele):
    """La caméra de la tête du micropore (tâche 40 ter) : QR du flanc, trous, morceaux posés.
    Ce qui demande des photos réelles (attaches de l'anse, morceau bien collé) reste un faux."""

    exemple: bool = False
    # Nom de la caméra dans `cameras` (même que machine.yaml → micropore → camera).
    camera: Nom
    geometrie: GeometrieInspection
    # Taille d'un point de l'image sur la paroi (mm), à mesurer avec un objet connu : EXEMPLE.
    echelle_mm_par_point: float = Field(gt=0)
    flanc: LectureFlancInspection
    trous: TrousInspection
    piece: PieceInspection

    @model_validator(mode="after")
    def _verifier(self) -> "InspectionVision":
        erreurs = []
        petit = self.trous.diametre_mm
        if self.piece.longueur_mm < petit + 2 * self.piece.marge_mm:
            erreurs.append(
                f"piece → longueur_mm ({self.piece.longueur_mm:g}) trop courte pour couvrir un "
                f"trou de Ø {petit:g} mm avec sa marge"
            )
        if self.piece.largeur_mm < petit + 2 * self.piece.marge_mm:
            erreurs.append(
                f"piece → largeur_mm ({self.piece.largeur_mm:g}) trop étroite pour couvrir un "
                f"trou de Ø {petit:g} mm avec sa marge"
            )
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class ReglagesVision(Modele):
    """vision.yaml : caméras, QR, repères ArUco, caméra du plafond (tâche 22), caméra du
    micropore (tâche 40 ter)."""

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
    inspection: InspectionVision | None = None

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
        if self.inspection is not None:
            camera = self.cameras.get(self.inspection.camera)
            if camera is None:
                erreurs.append(
                    f"inspection → camera : « {self.inspection.camera} » absente de cameras"
                )
            elif camera.video is None:
                erreurs.append(
                    f"cameras → {self.inspection.camera} : il faut sa vidéo (video), la caméra "
                    "d'inspection du micropore en a besoin"
                )
        if "plafond" in self.cameras and self.cameras["plafond"].position is None:
            erreurs.append("cameras → plafond : il faut sa position")
        if "tete_griffe" in self.cameras and self.cameras["tete_griffe"].tete is None:
            erreurs.append("cameras → tete_griffe : il faut sa place sur la tête (tete)")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


# ----------------------------------------------------------------- air.yaml


class ReglagesAir(Modele):
    """air.yaml : le compresseur, seule sortie du module Air comprimé (tâche 42)."""

    exemple: bool = False
    # Attente après la fermeture du relais avant un geste qui consomme de l'air (s).
    attente_mise_en_pression_s: float = Field(ge=0)
    # Rappel de vider le bidon de purge, en jours.
    rappel_bidon_jours: int = Field(ge=1)
    # Tous les combien le Pi regarde s'il doit commander le relais (s).
    periode_s: float = Field(gt=0, le=60)

    @model_validator(mode="after")
    def _verifier_ensemble(self) -> "ReglagesAir":
        if self.periode_s * 10 > self.attente_mise_en_pression_s > 0:
            raise ValueError(
                f"periode_s ({self.periode_s:g} s) est trop grande devant "
                f"attente_mise_en_pression_s ({self.attente_mise_en_pression_s:g} s) : "
                "l'attente serait imprécise"
            )
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
    air: ReglagesAir


# Nom du fichier → (nom dans Reglages, modèle). Ajouter ici chaque nouveau fichier.
FICHIERS: dict[str, tuple[str, type[Modele]]] = {
    "machine.yaml": ("machine", Machine),
    "programme.yaml": ("programme", Programme),
    "fluidnc.yaml": ("fluidnc", Fluidnc),
    "simulateur.yaml": ("simulateur", ReglagesSimulateur),
    "accelerometre.yaml": ("accelerometre", ReglagesAccelerometre),
    "pesees.yaml": ("pesees", ReglagesPesees),
    "vision.yaml": ("vision", ReglagesVision),
    "air.yaml": ("air", ReglagesAir),
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
    # Pendant un lot, le boîtier du chariot doit recevoir son battement à temps (tâche 45 quater).
    battements = []
    if machine.micropore is not None:
        battements.append(("micropore → servos", machine.micropore.servos.battement_s))
    if machine.fermeture is not None:
        battements.append(("fermeture → bras", machine.fermeture.bras.battement_s))
    erreurs += [
        f"programme.yaml, lot → fond_periode_s ({programme.lot.fond_periode_s:g} s) doit être "
        f"plus court que machine.yaml, {ou} → battement_s ({battement:g} s)"
        for ou, battement in battements
        if programme.lot.fond_periode_s >= battement
    ]
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
    # Capteurs d'origine des rotations (tâche 36 bis) : chacun est le fin de course de son axe
    # (« $HA », « $HB »), donc sur sa carte, avec la lettre de l'axe.
    origines_capteurs: list[tuple[str, str]] = []
    if machine.prehension is not None and machine.prehension.origine_rotation is not None:
        origines_capteurs.append(("origine_rotation_tete", "prehension_a"))
    if machine.griffe is not None and machine.griffe.origine_rotation is not None:
        origines_capteurs += [
            ("origine_rotation_griffe", "griffe_a"),
            ("origine_godet_griffe", "griffe_b"),
        ]
    for signal, nom_axe in origines_capteurs:
        axe = machine.axes.get(nom_axe)
        if axe is None or axe.carte is None:
            continue
        carte = fluidnc.cartes.get(axe.carte)
        lettre = None if carte is None else carte.entrees.get(signal)
        if carte is not None and lettre != axe.lettre:
            erreurs.append(
                f"fluidnc.yaml, cartes → {axe.carte} → entrees → {signal} : doit être la lettre "
                f"de l'axe {nom_axe} (« {axe.lettre} »), c'est son fin de course"
                + ("" if lettre is None else f", pas « {lettre} »")
            )
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
    erreurs += _verifier_micropore_entre_fichiers(valeurs)
    erreurs += _verifier_fermeture_entre_fichiers(valeurs)
    if simulateur.depart is not None and simulateur.depart not in machine.positions:
        erreurs.append(
            f"simulateur.yaml, depart : position « {simulateur.depart} » absente de machine.yaml"
        )
    return erreurs


def _verifier_micropore_entre_fichiers(valeurs: dict[str, Modele]) -> list[str]:
    """Les servos et le ToF du micropore sont ceux de l'I2C de pesees.yaml ; les angles de la lame
    tiennent dans la plage de sa voie ; la carte du moteur d'avance est dans fluidnc.yaml, la
    caméra dans vision.yaml ; les gestes appris du simulateur vont avec les formats."""
    machine, pesees = valeurs["machine"], valeurs["pesees"]
    fluidnc, vision = valeurs["fluidnc"], valeurs["vision"]
    simulateur = valeurs["simulateur"]
    assert isinstance(machine, Machine) and isinstance(pesees, ReglagesPesees)
    assert isinstance(fluidnc, Fluidnc) and isinstance(vision, ReglagesVision)
    assert isinstance(simulateur, ReglagesSimulateur)
    micropore = machine.micropore
    if micropore is None:
        return []
    erreurs = []
    if micropore.avance.carte not in fluidnc.cartes:
        erreurs.append(
            f"machine.yaml, micropore → avance : carte « {micropore.avance.carte} » absente de "
            "fluidnc.yaml"
        )
    if micropore.camera not in vision.cameras:
        erreurs.append(
            f"machine.yaml, micropore → camera : « {micropore.camera} » absente de vision.yaml "
            "(cameras)"
        )
    if vision.inspection is not None:
        geometrie = vision.inspection.geometrie
        ecart = geometrie.objectif_z_m - micropore.ruban_z
        if abs(ecart) > geometrie.vue_utile_m + 1e-9:
            erreurs.append(
                f"vision.yaml, inspection → geometrie → objectif_z_m ({geometrie.objectif_z_m:g}) "
                f"est à {abs(ecart) * 100:.1f} cm de micropore → ruban_z ({micropore.ruban_z:g}) : "
                f"la rangée sort de la zone utile de la caméra ({geometrie.vue_utile_m * 100:g} cm)"
            )
        remplissage = machine.remplissage
        if remplissage is not None and remplissage.plateau_lecture_qr is not None:
            voulu = geometrie.objectif_z_m - geometrie.etiquette_hauteur_m
            if abs(remplissage.plateau_lecture_qr - voulu) > 1e-6:
                erreurs.append(
                    "machine.yaml, remplissage → plateau_lecture_qr "
                    f"({remplissage.plateau_lecture_qr:g})"
                    f" doit valoir objectif_z_m − etiquette_hauteur_m de vision.yaml ({voulu:g})"
                )
    if vision.inspection is not None and vision.inspection.camera != micropore.camera:
        erreurs.append(
            f"vision.yaml, inspection → camera : « {vision.inspection.camera} », machine.yaml dit "
            f"« {micropore.camera} » (micropore → camera)"
        )
    i2c = pesees.i2c
    if i2c is None:
        return [*erreurs, "machine.yaml, micropore : il faut l'I2C de pesees.yaml (servos, ToF)"]
    if i2c.vl6180x.signal != micropore.tof_signal:
        erreurs.append(
            f"machine.yaml, micropore → tof_signal : « {micropore.tof_signal} », pesees.yaml dit "
            f"« {i2c.vl6180x.signal} » (i2c → vl6180x → signal)"
        )
    for quoi, voie in (
        ("servo_escamotage", micropore.servo_escamotage),
        ("servo_lame", micropore.servo_lame),
    ):
        if voie not in i2c.pca9685.voies:
            erreurs.append(
                f"machine.yaml, micropore → {quoi} : voie « {voie} » absente de pesees.yaml "
                "(i2c → pca9685 → voies)"
            )
    lame = i2c.pca9685.voies.get(micropore.servo_lame)
    if lame is not None:
        for quoi in ("lame_repos_deg", "lame_bas_deg"):
            angle = getattr(micropore.servos, quoi)
            if not lame.angle_min_deg <= angle <= lame.angle_max_deg:
                erreurs.append(
                    f"machine.yaml, micropore → servos → {quoi} : {angle:g}° hors de la plage de "
                    f"la voie ({lame.angle_min_deg:g} à {lame.angle_max_deg:g}°, pesees.yaml)"
                )
    escamotage = i2c.pca9685.voies.get(micropore.servo_escamotage)
    if simulateur.micropore is not None and escamotage is not None:
        plage = (escamotage.angle_min_deg, escamotage.angle_max_deg)
        erreurs += [
            f"simulateur.yaml, micropore → appris : {erreur}"
            for erreur in verifier_appris(simulateur.micropore.appris, micropore, plage)
        ]
    return erreurs


def _verifier_fermeture_entre_fichiers(valeurs: dict[str, Modele]) -> list[str]:
    """Le servo de la fermeture est une voie de la PCA9685 de pesees.yaml, et ses angles (travail,
    rangé) tiennent dans la plage de cette voie."""
    machine, pesees = valeurs["machine"], valeurs["pesees"]
    assert isinstance(machine, Machine) and isinstance(pesees, ReglagesPesees)
    fermeture = machine.fermeture
    if fermeture is None:
        return []
    i2c = pesees.i2c
    if i2c is None:
        return ["machine.yaml, fermeture : il faut l'I2C de pesees.yaml (servo du bras)"]
    voie = i2c.pca9685.voies.get(fermeture.servo)
    if voie is None:
        return [
            f"machine.yaml, fermeture → servo : voie « {fermeture.servo} » absente de pesees.yaml "
            "(i2c → pca9685 → voies)"
        ]
    erreurs = []
    for quoi, angle in (
        ("travail", fermeture.servo_travail_deg()),
        ("rangé", fermeture.servo_range_deg()),
    ):
        if not voie.angle_min_deg <= angle <= voie.angle_max_deg:
            erreurs.append(
                f"machine.yaml, fermeture → bras : l'angle du servo « {quoi} » ({angle:g}°) est "
                f"hors de la plage de la voie ({voie.angle_min_deg:g} à {voie.angle_max_deg:g}°, "
                "pesees.yaml) : revoir butee_servo_deg"
            )
    if machine.micropore is not None and fermeture.servo in (
        machine.micropore.servo_escamotage,
        machine.micropore.servo_lame,
    ):
        erreurs.append("machine.yaml, fermeture → servo : la voie est déjà celle du micropore")
    return erreurs


def verifier_appris(
    appris: GestesAppris, micropore: Micropore, plage_deg: tuple[float, float]
) -> list[str]:
    """Les gestes appris vont avec la tête : angles dans la plage de la voie du servo, dans
    l'ordre escamoté → approche → contact → appui (dans le sens de l'avance), formats connus."""
    erreurs = []
    debut, fin = plage_deg
    sens = micropore.servos.sens_avance

    def dans(quoi: str, angle: float) -> None:
        if not debut <= angle <= fin:
            erreurs.append(f"{quoi} : {angle:g}° hors de la plage du servo ({debut:g} à {fin:g}°)")

    if appris.escamote_deg is not None:
        dans("escamote_deg", appris.escamote_deg)
    for nom, format in appris.formats.items():
        if nom not in micropore.formats:
            erreurs.append(f"formats → {nom} : format absent de machine.yaml (micropore → formats)")
        for quoi in ("approche_deg", "contact_deg", "appui_deg"):
            dans(f"formats → {nom} → {quoi}", getattr(format, quoi))
        angles = [format.approche_deg, format.contact_deg, format.appui_deg]
        if appris.escamote_deg is not None:
            angles.insert(0, appris.escamote_deg)
        if any(sens * (b - a) <= 0 for a, b in zip(angles, angles[1:], strict=False)):
            erreurs.append(
                f"formats → {nom} : les angles ne vont pas dans l'ordre escamoté → approche → "
                "contact → appui (sens de l'avance de la tête)"
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
