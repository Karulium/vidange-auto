"""Outil « vidange-micropore » : essayer la tête du micropore et apprendre ses gestes.

  vidange-micropore etat                       distance du ToF, angles, gestes appris
  vidange-micropore escamote 40                servo d'escamotage à 40° : si le ToF voit la tête
                                               escamotée, cet angle est appris (« escamoté »)
  vidange-micropore apprendre seau_a           un seau A devant la tête (procédure) : le servo
                                               avance doucement jusqu'au contact vu au ToF ; le
                                               Pi apprend approche, contact et appui, et l'angle
                                               caméra → rouleau que donne la vision
                                               (vision.yaml → inspection)
  vidange-micropore apprendre seau_a --camera-rouleau 32
                                               pareil, mais l'angle caméra → rouleau est FORCÉ
  vidange-micropore servo 55                   servo d'escamotage à 55° (SANS seau devant : la
                                               tête avance librement), distance du ToF lue
  vidange-micropore lame                       une coupe (lame en bas, puis au repos)
  vidange-micropore charger                    rouleau neuf passé : une coupe, compteur à neuf
  vidange-micropore historique                 les changements des gestes appris
  vidange-micropore annuler                    défait le dernier changement
  ... --faux                                   pareil, avec le faux matériel (pour essayer)

Les gestes appris vont dans donnees/micropore-appris.yaml (jamais dans pi/reglages/) ; chaque
changement est noté (quand, qui, avant, après) et peut être annulé. Le plateau, lui, se règle
avec vidange-remplissage (hauteur de la rangée, rotation). Procédure : systeme/essai-micropore.md.

À ne lancer que quand le programme principal est arrêté (l'adaptateur ne s'ouvre qu'une fois).
"""

import argparse
import json
import sys
import time
from collections.abc import Callable

from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.journal import configurer_journal
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel
from vidange.micropore.appris import NOM_APPRIS, FichierAppris
from vidange.micropore.simulation import distance_imaginaire
from vidange.micropore.tete import TeteMicropore
from vidange.reglages import (
    ErreurReglages,
    FormatAppris,
    Reglages,
    charger_reglages,
    verifier_appris,
)
from vidange.vision.inspection import angle_camera_rouleau

NOM_ETAT = "micropore.json"


def main(
    arguments: list[str] | None = None,
    fabrique=None,
    attendre: Callable[[float], None] = time.sleep,
    horloge: Callable[[], float] = time.monotonic,
) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-micropore", description=__doc__.split("\n")[0])
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument(
        "--entrees-sorties", help="liste des entrées/sorties (défaut : docs/entrees-sorties.yaml)"
    )
    lecteur.add_argument("--donnees", help="dossier des données (défaut : pi/donnees)")
    lecteur.add_argument("--qui", default="karulium", help="qui apprend (noté dans l'historique)")
    lecteur.add_argument("--faux", action="store_true", help="avec le faux matériel")
    commandes = lecteur.add_subparsers(dest="commande", required=True)
    commandes.add_parser("etat", help="distance du ToF, angles, gestes appris")
    escamote = commandes.add_parser("escamote", help="apprend l'angle « escamoté »")
    escamote.add_argument("angle", type=float, help="angle du servo d'escamotage (°)")
    apprendre = commandes.add_parser("apprendre", help="apprend un format de seau")
    apprendre.add_argument("format", help="format du seau (exemple : seau_a)")
    apprendre.add_argument(
        "--camera-rouleau",
        type=float,
        default=None,
        help="force l'angle caméra → rouleau : rotation du plateau (°) d'un trou vu au centre de "
        "la caméra jusqu'au rouleau (sans cette option, c'est la vision qui le donne)",
    )
    servo = commandes.add_parser("servo", help="servo d'escamotage à cet angle, ToF lu")
    servo.add_argument("angle", type=float, help="angle du servo d'escamotage (°)")
    commandes.add_parser("lame", help="une coupe")
    commandes.add_parser("charger", help="rouleau neuf : une coupe, compteur à neuf")
    commandes.add_parser("historique", help="les changements des gestes appris")
    commandes.add_parser("annuler", help="défait le dernier changement")
    options = lecteur.parse_args(arguments)
    configurer_journal()
    dossier = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    chemin_liste = _chemin(
        options.entrees_sorties,
        "VIDANGE_ENTREES_SORTIES",
        DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml",
    )
    donnees = _chemin(options.donnees, "VIDANGE_DONNEES", DOSSIER_PI / "donnees")
    try:
        reglages = charger_reglages(dossier)
        liste = charger_entrees_sorties(chemin_liste)
    except ErreurReglages as erreur:
        print(erreur, file=sys.stderr)
        return 2
    micropore, i2c = reglages.machine.micropore, reglages.pesees.i2c
    if micropore is None or i2c is None:
        print(
            "machine.yaml n'a pas de « micropore » (ou pesees.yaml pas d'« i2c »)", file=sys.stderr
        )
        return 2
    appris = FichierAppris(donnees / NOM_APPRIS)
    if appris.erreur is not None:
        print(f"Gestes appris illisibles : {appris.erreur}", file=sys.stderr)
        return 2
    if options.commande == "historique":
        return _historique(appris)
    if options.commande == "annuler":
        numero = appris.annuler(options.qui)
        print("Rien à annuler." if numero is None else f"Changement n° {numero} annulé.")
        return 0
    if fabrique is None and options.faux:
        fabrique = FausseFabrique(liste)
        _brancher_faux(fabrique, reglages, getattr(options, "format", None))
    with Materiel(liste, fabrique, seulement=[i2c.carte]) as materiel:
        tete = TeteMicropore(micropore, i2c, materiel, appris, horloge)
        try:
            if options.commande == "etat":
                return _etat(tete, reglages, appris)
            if options.commande == "escamote":
                return _escamote(tete, appris, options.angle, options.qui, attendre)
            if options.commande == "servo":
                return _servo(tete, options.angle, attendre)
            if options.commande in ("lame", "charger"):
                return _lame(tete, reglages, donnees, options.commande == "charger", attendre)
            return _apprendre(
                tete,
                reglages,
                appris,
                options.format,
                options.camera_rouleau,
                options.qui,
                attendre,
            )
        except ErreurMateriel as erreur:
            print(f"ÉCHEC : {erreur}", file=sys.stderr)
            return 1


def _brancher_faux(fabrique: FausseFabrique, reglages: Reglages, format: str | None) -> None:
    """--faux : le faux boîtier et une tête imaginaire, escamotée à l'angle appris du simulateur
    (simulateur.yaml → micropore) ; pour « apprendre », un seau de ce format devant elle."""
    i2c, micropore = reglages.pesees.i2c, reglages.machine.micropore
    assert i2c is not None and micropore is not None
    plages = [(voie.angle_min_deg, voie.angle_max_deg) for voie in i2c.pca9685.voies.values()]
    boitier = fabrique.carte_pesee(i2c.carte).brancher_boitier(plages)
    simule = reglages.simulateur.micropore
    if simule is None or simule.appris.escamote_deg is None:
        return
    escamote = simule.appris.escamote_deg
    appris = simule.appris.formats.get(format) if format is not None else None
    contact = None if appris is None else appris.contact_deg
    voie = list(i2c.pca9685.voies).index(micropore.servo_escamotage)
    derniere = [round(micropore.tof.escamotee_mm)]

    def tof(angles: tuple[float | None, ...]) -> int:
        if angles[voie] is not None:
            derniere[0] = distance_imaginaire(micropore, angles[voie], escamote, contact)
        return derniere[0]

    boitier.tof_selon_angles = tof


def _plage(reglages: Reglages) -> tuple[float, float]:
    assert reglages.machine.micropore is not None and reglages.pesees.i2c is not None
    voie = reglages.pesees.i2c.pca9685.voies[reglages.machine.micropore.servo_escamotage]
    return voie.angle_min_deg, voie.angle_max_deg


def _historique(appris: FichierAppris) -> int:
    historique = appris.gestes.historique
    if not historique:
        print("Aucun geste appris.")
    for c in historique:
        quoi = f"annule le n° {c.annule}" if c.annule is not None else f"{c.cle} appris"
        annule = f" (annulé par le n° {c.annule_par})" if c.annule_par is not None else ""
        print(f"n° {c.numero}  {c.quand}  {c.qui}  {quoi}{annule}")
        print(f"    avant : {_texte(c.avant)}")
        print(f"    après : {_texte(c.apres)}")
    return 0


def _texte(valeur: FormatAppris | float | None) -> str:
    if valeur is None:
        return "rien"
    if isinstance(valeur, FormatAppris):
        return ", ".join(f"{cle} {v:g}" for cle, v in valeur.model_dump().items())
    return f"{valeur:g}°"


def _etat(tete: TeteMicropore, reglages: Reglages, appris: FichierAppris) -> int:
    etat = tete.lire()
    distance = "pas de mesure" if etat.distance_mm is None else f"{etat.distance_mm} mm"
    angles = ", ".join(
        f"{voie} {'coupée' if angle is None else f'{angle:g}°'}"
        for voie, angle in zip(tete.voies, etat.angles_deg, strict=True)
    )
    print(f"ToF {distance} (état {etat.etat_tof})  démarrages {etat.demarrages}  {angles}")
    gestes = appris.gestes
    escamote = "pas appris" if gestes.escamote_deg is None else f"{gestes.escamote_deg:g}°"
    print(f"Escamoté : {escamote}")
    for nom, format in gestes.formats.items():
        print(f"{nom} : {_texte(format)}")
    assert reglages.machine.micropore is not None
    erreurs = verifier_appris(gestes, reglages.machine.micropore, _plage(reglages))
    for erreur in erreurs:
        print(f"À REVOIR : {erreur}")
    return 1 if erreurs else 0


def _lire_distance(tete: TeteMicropore, attendre: Callable[[float], None]) -> float | None:
    attendre(tete.reglages.servos.mouvement_s)
    tete.lire()
    return tete.distance_mm()


def _servo(tete: TeteMicropore, angle: float, attendre: Callable[[float], None]) -> int:
    tete.commander(escamotage=angle, lame=tete.reglages.servos.lame_repos_deg)
    distance = _lire_distance(tete, attendre)
    lu = "pas de mesure" if distance is None else f"{distance:g} mm"
    print(f"Servo d'escamotage à {angle:g}° : ToF {lu}.")
    return 0 if distance is not None else 1


def _escamote(
    tete: TeteMicropore,
    appris: FichierAppris,
    angle: float,
    qui: str,
    attendre: Callable[[float], None],
) -> int:
    tete.commander(escamotage=angle, lame=tete.reglages.servos.lame_repos_deg)
    distance = _lire_distance(tete, attendre)
    tof = tete.reglages.tof
    if not tete.vue_escamotee(distance):
        lu = "pas de mesure" if distance is None else f"{distance:g} mm"
        print(
            f"Tête pas vue escamotée à {angle:g}° (ToF {lu}, au moins "
            f"{tof.escamotee_mm - tof.tolerance_escamotee_mm:g} mm attendus) : rien n'est appris. "
            "Essayer un angle plus en arrière.",
            file=sys.stderr,
        )
        return 1
    numero = appris.noter_escamote(angle, qui)
    print(f"Escamoté appris : {angle:g}° (ToF {distance:g} mm), changement n° {numero}.")
    return 0


def _lame(
    tete: TeteMicropore,
    reglages: Reglages,
    donnees,
    charger: bool,
    attendre: Callable[[float], None],
) -> int:
    servos = tete.reglages.servos
    tete.commander(lame=servos.lame_bas_deg)
    attendre(servos.lame_s)
    tete.commander(lame=servos.lame_repos_deg)
    attendre(servos.lame_s)
    print("Une coupe faite (lame en bas, puis au repos).")
    if charger:
        morceaux = tete.reglages.rouleau.morceaux
        fichier = donnees / NOM_ETAT
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(
            json.dumps({"morceaux_restants": morceaux, "alerte_rouleau_faite": False}),
            encoding="utf-8",
        )
        print(f"Rouleau neuf : compteur à {morceaux} morceaux. Changer aussi le morceau de lame.")
    return 0


def _apprendre(
    tete: TeteMicropore,
    reglages: Reglages,
    appris: FichierAppris,
    format: str,
    camera_rouleau: float | None,
    qui: str,
    attendre: Callable[[float], None],
) -> int:
    micropore = tete.reglages
    if format not in micropore.formats:
        print(
            f"format inconnu « {format} » (formats : {', '.join(micropore.formats)})",
            file=sys.stderr,
        )
        return 2
    if camera_rouleau is None:
        inspection = reglages.vision.inspection
        if inspection is None:
            print(
                "Pas de partie « inspection » dans vision.yaml : donner l'angle caméra → rouleau "
                "avec --camera-rouleau.",
                file=sys.stderr,
            )
            return 2
        rangees = micropore.formats[format].rangees
        camera_rouleau = round(angle_camera_rouleau(inspection, rangees[0].rayon_paroi_m), 2)
        print(f"Angle caméra → rouleau donné par la vision : {camera_rouleau:g}°.")
    escamote = appris.escamote_deg
    if escamote is None:
        print("Apprendre d'abord l'angle escamoté (vidange-micropore escamote).", file=sys.stderr)
        return 2
    servos, tof, pose = micropore.servos, micropore.tof, micropore.pose
    tete.escamoter()
    depart = _lire_distance(tete, attendre)
    if not tete.vue_escamotee(depart):
        print("Tête pas vue escamotée au départ : rien n'est appris.", file=sys.stderr)
        return 1
    debut, fin = _plage(reglages)
    angle = escamote
    mesures: list[tuple[float, float]] = []
    while True:
        angle += servos.sens_avance * servos.pas_apprentissage_deg
        if not debut <= angle <= fin:
            tete.escamoter()
            print("Bout de la plage du servo sans contact : rien n'est appris.", file=sys.stderr)
            return 1
        tete.commander(escamotage=angle)
        distance = _lire_distance(tete, attendre)
        if distance is None:
            tete.escamoter()
            print("Plus de mesure du ToF : rien n'est appris.", file=sys.stderr)
            return 1
        if distance <= tof.butee_mm + tof.precision_mm:
            tete.escamoter()
            print(
                "La tête est allée jusqu'à sa butée sans toucher de paroi (pas de seau, seau mal "
                "placé ?) : rien n'est appris.",
                file=sys.stderr,
            )
            return 1
        mesures.append((angle, distance))
        plats = servos.apprentissage_pas_plats
        if len(mesures) > plats:
            angle_contact, distance_contact = mesures[-plats - 1]
            if distance_contact - distance <= tof.precision_mm:
                break
    tete.escamoter()
    sens = servos.sens_avance
    valeurs = FormatAppris(
        approche_deg=round(angle_contact - sens * pose.approche_mm / servos.mm_par_degre, 2),
        contact_deg=round(angle_contact, 2),
        appui_deg=round(angle_contact + sens * pose.appui_mm / servos.mm_par_degre, 2),
        contact_mm=distance_contact,
        camera_rouleau_deg=camera_rouleau,
    )
    essai = appris.gestes.model_copy(update={"formats": {format: valeurs}})
    erreurs = verifier_appris(essai, micropore, (debut, fin))
    if erreurs:
        print("Gestes pas appris : " + " ; ".join(erreurs), file=sys.stderr)
        return 1
    numero = appris.noter_format(format, valeurs, qui)
    print(
        f"{format} appris (changement n° {numero}) : contact à {valeurs.contact_deg:g}° (ToF "
        f"{distance_contact:g} mm), approche {valeurs.approche_deg:g}°, appui "
        f"{valeurs.appui_deg:g}°, caméra → rouleau {camera_rouleau:g}°."
    )
    return 0


def lancer() -> None:
    sys.exit(main())
