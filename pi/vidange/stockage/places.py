"""Les places du Stockage, calculées à partir de machine.yaml (partie « stockage »).

Le code ne contient aucun chiffre de la machine : seulement les formules de la fiche du Stockage
(gelée le 27/10/2026), recopiées dans la tâche 35.

    seaux_par_pile(machine, "seau_a")      # 5 : n = min(⌊(0,39 − h)/pas⌋ + 1 ;
                                           #             ⌊(0,645 − 2h)/pas⌋ + 1)
    bord_pile(machine, "seau_a", k)        # bord du seau du haut : 0,496 + h + (k − 1) × pas
    places_piles(machine, "seau_a")        # places des piles (fin de lot comprise) : nom → (x ; y)
    ordre_piles(machine, places)           # rangée 0,84, puis 0,53, puis 0,215 ; la plus proche
                                           # du chariot d'abord
    places_bocaux(machine)                 # quinconce de 95 bocaux : « bocal_j_i » → (x ; y)

Ces calculs servent aussi à la vérification des réglages au démarrage (vidange.reglages).
"""

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vidange.reglages import FormatSeau, Machine, Stockage

Point = tuple[float, float]

# Pour les arrondis des divisions (0,175 / 0,035 = 4,9999...).
_EGAL = 1e-9


def _stockage(machine: "Machine") -> "Stockage":
    assert machine.stockage is not None
    return machine.stockage


def format_seau(machine: "Machine", format: str) -> "FormatSeau":
    assert machine.griffe is not None
    seau = machine.griffe.formats.get(format)
    if seau is None:
        raise KeyError(f"stockage : format de seau inconnu « {format} »")
    assert seau.hauteur is not None and seau.pas_pile_m is not None
    return seau


# ------------------------------------------------------------ piles de seaux vides


def seaux_par_pile(machine: "Machine", format: str) -> int:
    """Le plus de seaux d'une pile de ce format."""
    piles = _stockage(machine).piles
    seau = format_seau(machine, format)
    h, pas = seau.hauteur, seau.pas_pile_m
    assert h is not None and pas is not None
    par_le_bord = math.floor((piles.bord_max_m - h) / pas + _EGAL) + 1
    par_la_sortie = math.floor((piles.sortie_max_m - 2 * h) / pas + _EGAL) + 1
    return max(0, min(par_le_bord, par_la_sortie))


def fond_pile(machine: "Machine", format: str, k: int) -> float:
    """Le fond (dessous) du k-ième seau d'une pile (k = 1 : posé sur le plateau)."""
    seau = format_seau(machine, format)
    assert seau.pas_pile_m is not None
    return _stockage(machine).plateau_z + (k - 1) * seau.pas_pile_m


def bord_pile(machine: "Machine", format: str, k: int) -> float:
    """Le bord du seau du haut d'une pile de k seaux (k ≥ 1)."""
    seau = format_seau(machine, format)
    assert seau.hauteur is not None
    return fond_pile(machine, format, k) + seau.hauteur


def contact_prise(machine: "Machine", format: str, k: int) -> float:
    """Où la face de la tête touche le fond intérieur du seau du haut d'une pile de k seaux
    (le même écart au fond que sur le plateau du Remplissage)."""
    assert machine.remplissage is not None
    return fond_pile(machine, format, k) + machine.remplissage.face_au_dessus_plateau_m


def places_fin_de_lot(machine: "Machine", format: str) -> list[Point]:
    """Les places de fin de lot de ce format sur la bande : la 1re au plus près de x_debut (son
    axe assez loin de la caméra du bocal pour la sortie), 1 cm entre piles, la dernière assez
    loin du hublot, au plus places_max."""
    stockage = _stockage(machine)
    bande = stockage.piles.fin_de_lot
    rayon = format_seau(machine, format).rayon_haut
    x = max(bande.x_debut + rayon, stockage.trajets.camera_bocal.seau_x_min)
    x_max = stockage.hublot.x - bande.marge_hublot_m
    places: list[Point] = []
    while len(places) < bande.places_max and x + rayon <= x_max + _EGAL:
        places.append((round(x, 6), bande.y))
        x += 2 * rayon + bande.ecart_m
    return places


def nom_fin_de_lot(numero: int) -> str:
    return f"fin_{numero}"


def places_piles(machine: "Machine", format_fin_de_lot: str) -> dict[str, Point]:
    """Toutes les places de piles : les fixes, puis celles de fin de lot (leur x dépend du format
    des piles de la bande, toutes du même format)."""
    places = dict(_stockage(machine).piles.places)
    for numero, point in enumerate(places_fin_de_lot(machine, format_fin_de_lot), start=1):
        places[nom_fin_de_lot(numero)] = point
    return places


def ordre_piles(machine: "Machine", places: dict[str, Point]) -> list[str]:
    """L'ordre de vidage : rangée par rangée (ordre_rangees_y), et dans une rangée la pile la
    plus proche du chariot de remplissage d'abord."""
    assert machine.remplissage is not None
    rangees = _stockage(machine).piles.ordre_rangees_y
    axe_x = machine.remplissage.axe_x

    def rang(nom: str) -> tuple[int, float]:
        x, y = places[nom]
        rangee = min(range(len(rangees)), key=lambda i: abs(rangees[i] - y))
        return rangee, abs(x - axe_x)

    return sorted(places, key=rang)


# ------------------------------------------------------------ tiroir des seaux pleins


def places_tiroir(machine: "Machine", format: str) -> dict[str, int]:
    """Seaux par file du tiroir, dans l'ordre où on les remplit."""
    tiroir = _stockage(machine).tiroir
    par_file = tiroir.places[format]
    return {nom: par_file[nom] for nom in tiroir.files}


def capacite_tiroir(machine: "Machine", format: str) -> int:
    return sum(places_tiroir(machine, format).values())


# ------------------------------------------------------------ bocaux


def nom_bocal(j: int, i: int) -> str:
    return f"bocal_{j}_{i}"


def places_bocaux(machine: "Machine") -> dict[str, Point]:
    """Le quinconce : rangée j à y0 + pas_y × j ; rangées paires et impaires décalées."""
    bocaux = _stockage(machine).bocaux
    places: dict[str, Point] = {}
    for j in range(bocaux.rangees):
        rangee = bocaux.paires if j % 2 == 0 else bocaux.impaires
        y = round(bocaux.y0 + bocaux.pas_y * j, 6)
        for i in range(rangee.places):
            places[nom_bocal(j, i)] = (round(rangee.x0 + bocaux.pas_x * i, 6), y)
    return places


def places_semence(machine: "Machine") -> dict[str, Point]:
    """Les bocaux de semence : « semence_r_i » (rangée r des y, colonne i)."""
    semence = _stockage(machine).bocaux.semence
    return {
        f"semence_{r}_{i}": (round(semence.x0 + semence.pas_x * i, 6), y)
        for r, y in enumerate(semence.y)
        for i in range(semence.colonnes)
    }


def coin_inspection(machine: "Machine") -> tuple[list[str], list[str]]:
    """Le coin d'inspection : (places « suspects », places vides de séparation)."""
    inspection = _stockage(machine).bocaux.inspection
    return (
        [nom_bocal(j, i) for j, i in inspection.suspects],
        [nom_bocal(j, i) for j, i in inspection.separation],
    )


def places_saines(machine: "Machine") -> list[str]:
    """Le quinconce en mode inspection, sans le coin (suspects et séparation)."""
    suspects, separation = coin_inspection(machine)
    coin = {*suspects, *separation}
    return [nom for nom in places_bocaux(machine) if nom not in coin]


# ------------------------------------------------------------ boîtes à capsules


def capacite_boite(machine: "Machine") -> int:
    boites = _stockage(machine).boites
    return math.floor((boites.dessus_z - boites.fond_z) / boites.epaisseur_capsule_m + _EGAL)


def hauteur_boite(machine: "Machine", capsules: int) -> float:
    """Le haut de la pile de capsules d'une boîte."""
    boites = _stockage(machine).boites
    return boites.fond_z + boites.epaisseur_capsule_m * capsules
