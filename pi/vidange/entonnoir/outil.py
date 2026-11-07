"""Outil « vidange-entonnoir » : les places et les hauteurs que le Pi calcule, et l'état gardé.

  vidange-entonnoir places                 où va la ventouse pour chaque bout de rangée
  vidange-entonnoir places bocal_0_3       idem pour ce bocal (rangée 0, place 3)
  vidange-entonnoir hauteurs               hauteurs de la prise, du transport, de la pose
  vidange-entonnoir etat                   où le Pi croit que l'entonnoir est (fichier de donnees/)
  vidange-entonnoir noter hors_machine     change cet état (programme principal ARRÊTÉ) :
  vidange-entonnoir noter inconnu          « hors_machine », « inconnu » ou un nom de bocal
  vidange-entonnoir versement              hauteurs et ouvertures du versement de la griffe, et
                                           les bocaux où ses règles l'interdisent

Sert à l'essai sur le vrai matériel (pi/systeme/essai-entonnoir.md) : mesurer au mètre les cotes
annoncées. Tout vient de pi/reglages/machine.yaml (partie « entonnoir »).
"""

import argparse
import sys

from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.entonnoir import etat as garde
from vidange.entonnoir.etat import HORS_MACHINE, INCONNU, NOM_FICHIER
from vidange.reglages import ErreurReglages, Machine, charger_reglages
from vidange.stockage import places


def _m(valeur: float) -> str:
    return f"{valeur:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def _places(machine: Machine, bocal: str | None) -> list[str]:
    assert machine.entonnoir is not None and machine.prehension is not None
    reg, mat = machine.entonnoir, machine.prehension.decalage_mat_x
    tous = places.places_bocaux(machine)
    if bocal is not None:
        choisis = [bocal]
    else:
        # Les deux bouts de chaque type de rangée (paire, impaire), première rangée de chaque.
        choisis = [
            places.nom_bocal(0, 0),
            places.nom_bocal(0, machine.stockage.bocaux.paires.places - 1),  # type: ignore[union-attr]
            places.nom_bocal(1, 0),
            places.nom_bocal(1, machine.stockage.bocaux.impaires.places - 1),  # type: ignore[union-attr]
        ]
    lignes = ["Ventouse sur l'oreille (entonnoir posé sur le bocal) :"]
    for nom in choisis:
        x, y = tous[nom]
        lignes.append(
            f"  {nom:10} bocal ({_m(x)} ; {_m(y)}) → tête x {_m(x + reg.decalage_oreille_x_m)} "
            f"y {_m(y + reg.decalage_oreille_y_m)}, pont x {_m(x + reg.decalage_oreille_x_m - mat)}"
        )
    return lignes


def _hauteurs(machine: Machine) -> list[str]:
    assert machine.entonnoir is not None
    reg = machine.entonnoir
    return [
        "Haut de l'oreille, entonnoir posé (face de la ventouse au contact) : "
        f"{_m(reg.oreille_z)} m",
        f"  descente rapide jusqu'à {_m(reg.oreille_z + reg.approche_m)} m, puis vitesse "
        "d'approche",
        f"  pas de contact avant {_m(reg.oreille_z - reg.prise.trop_bas_m)} m : « entonnoir "
        "absent »",
        f"  contact au-dessus de {_m(reg.oreille_z + reg.prise.trop_haut_m)} m : « mal posé »",
        f"Pointe posée {_m(reg.pointe_z)} m, haut du cône {_m(reg.cone_haut_z)} m",
        f"Transport : face à {_m(reg.face_transport_z)} m (levée {_m(reg.levee_m)}), pointe à "
        f"{_m(reg.pointe_z + reg.levee_m)} m, garde sur les cols voisins "
        f"{_m(reg.pointe_z + reg.levee_m - reg.bord_col_z)} m (bord à {_m(reg.bord_col_z)} m)",
        f"Pose : posé si contact à {_m(reg.oreille_z)} ± {_m(reg.pose.tolerance_m)} m ; pointe sur "
        f"le bord du verre à {_m(reg.oreille_z + reg.pose.bord_du_verre_m)} m ou plus",
    ]


def _versement(machine: Machine) -> list[str]:
    """Le versement de la griffe (griffe → versement_bocal) : ses chiffres, et les bocaux où les
    règles de la griffe refusent de verser (tête de préhension comptée en haut, sauf dans la
    dernière rangée, où elle est comptée basse quand `tete_basse` est réglée)."""
    from vidange.griffe.regles import Contexte, ReglesGriffe
    from vidange.griffe.versement import contexte_du_bocal, poses_du_bocal

    griffe = machine.griffe
    reg = None if griffe is None else griffe.versement_bocal
    if griffe is None or reg is None:
        return ["machine.yaml n'a pas de partie « griffe → versement_bocal »"]
    godet, secousses = reg.godet, reg.secousses
    angles = (reg.ouverture_deg, *secousses.angles_deg, secousses.grand_ouvert_deg)
    lignes = [
        f"Dose {_m(reg.dose_kg * 1000)} g (acceptée de {_m(reg.dose.plage_kg[0] * 1000)} à "
        f"{_m(reg.dose.plage_kg[1] * 1000)} g), mât au plus à {_m(reg.centrage_max_m)} m du col",
        f"Axes des coquilles à {_m(reg.axes_z)} m (permis {_m(reg.axes_z_permis[0])} à "
        f"{_m(reg.axes_z_permis[1])}) : bas des dents à "
        f"{_m(reg.axes_z - griffe.bas_godet_sous_axes)} m",
        "Ouvertures du godet (0 fermé, 1 grand ouvert) : "
        + ", ".join(f"{_m(a)}° → {_m(godet.b_pour(a))}" for a in angles),
        f"Garde du boîtier de la caméra du bocal : mât à y {_m(reg.garde_camera_bocal.mat_y[0])}"
        f"-{_m(reg.garde_camera_bocal.mat_y[1])} → x ≥ {_m(reg.garde_camera_bocal.mat_x_min)}",
    ]
    if reg.tete_basse is not None:
        tete = reg.tete_basse
        lignes.append(
            "Dernière rangée (chaîne Z) : tête de préhension vide à la face "
            f"{_m(tete.prehension_face_basse_versement)} m, préhension à x ≥ "
            f"{_m(tete.prehension_x_min_tete_basse)}"
        )
    if reg.exemples():
        lignes.append("EXEMPLE (à régler à l'essai) : " + ", ".join(reg.exemples()))
    regles = ReglesGriffe(machine)
    refus = []
    for nom, (x, y) in places.places_bocaux(machine).items():
        contexte = contexte_du_bocal(reg, regles, Contexte(), y)
        poses = poses_du_bocal(reg, x, y)
        haut = poses[0].avec(z=griffe.trajet.z)
        for depart, arrivee in ((haut, poses[0]), *((poses[0], pose) for pose in poses[1:])):
            raison = regles.refus_mouvement(depart, arrivee, contexte)
            if raison is not None:
                refus.append(f"  {nom:10} ({_m(x)} ; {_m(y)}) : {raison}")
                break
    lignes.append(f"Bocaux où la griffe ne peut pas verser : {len(refus)}")
    return lignes + refus + _griffe_trainee(machine, regles)


def _griffe_trainee(machine: Machine, regles) -> list[str]:
    """Les bocaux où la Préhension ne peut pas poser l'entonnoir (tenu par son oreille) parce
    que la griffe, sur le même pont et en butée haute, serait traînée là où ses règles
    l'interdisent (tâche 45 sexies). Pose finale seulement : le trajet n'est pas regardé."""
    from vidange.griffe.regles import Contexte, Pose
    from vidange.griffe.versement import contexte_du_bocal

    griffe, entonnoir, prehension = machine.griffe, machine.entonnoir, machine.prehension
    if griffe is None or entonnoir is None or prehension is None:
        return []
    assert griffe.versement_bocal is not None
    refus = []
    for nom, (x, y) in places.places_bocaux(machine).items():
        mat_x, mat_y = machine.mat_griffe_entonnoir(x, y)
        pose = Pose(x=mat_x, y=mat_y, z=griffe.trajet.z, a=0, b=0)
        contexte = contexte_du_bocal(griffe.versement_bocal, regles, Contexte(), mat_y)
        raison = regles.refus_pose(pose, contexte)
        if raison is not None:
            refus.append(
                f"  {nom:10} ({_m(x)} ; {_m(y)}) : mât de la griffe à {_m(pose.x)} : {raison}"
            )
    return [
        "Bocaux où la Préhension ne peut pas poser l'entonnoir (la griffe, même pont, en butée "
        f"haute, serait traînée là ; pose finale seulement) : {len(refus)}",
        *refus,
    ]


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-entonnoir", description=__doc__.split("\n")[0])
    lecteur.add_argument("commande", choices=["places", "hauteurs", "etat", "noter", "versement"])
    lecteur.add_argument("valeur", nargs="?", help="un bocal (places) ou le nouvel état (noter)")
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument("--donnees", help="dossier des données (défaut : pi/donnees)")
    options = lecteur.parse_args(arguments)
    dossier = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    fichier = _chemin(options.donnees, "VIDANGE_DONNEES", DOSSIER_PI / "donnees") / NOM_FICHIER
    try:
        machine = charger_reglages(dossier).machine
    except ErreurReglages as erreur:
        print(erreur, file=sys.stderr)
        return 2
    if machine.entonnoir is None or machine.stockage is None:
        print("machine.yaml n'a pas de partie « entonnoir »", file=sys.stderr)
        return 2
    tous = places.places_bocaux(machine)
    if options.commande == "places":
        if options.valeur is not None and options.valeur not in tous:
            print(f"bocal inconnu « {options.valeur} » (exemple : bocal_0_3)", file=sys.stderr)
            return 2
        print("\n".join(_places(machine, options.valeur)))
    elif options.commande == "hauteurs":
        print("\n".join(_hauteurs(machine)))
    elif options.commande == "versement":
        print("\n".join(_versement(machine)))
    elif options.commande == "etat":
        etat, existe = garde.lire(fichier)
        print(f"Fichier : {fichier} ({'trouvé' if existe else 'absent : hors machine'})")
        print(f"entonnoir_place = {etat.place}{' (tenu par la tête)' if etat.tenu else ''}")
    else:
        valeur = options.valeur
        if valeur is None or (valeur not in (HORS_MACHINE, INCONNU) and valeur not in tous):
            print("noter : hors_machine, inconnu ou un nom de bocal (bocal_0_3)", file=sys.stderr)
            return 2
        garde.ecrire(fichier, garde.EtatGarde(valeur, False))
        print(f"entonnoir_place = {valeur} (écrit dans {fichier})")
    return 0


def lancer() -> None:
    sys.exit(main())
