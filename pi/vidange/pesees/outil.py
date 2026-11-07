"""Outil « vidange-pesees » : lire et étalonner les pesées du bus RS485.

  vidange-pesees lire                         chaque seconde, une ligne par carte (Ctrl+C)
  vidange-pesees zero pesee_griffe            étape 1 : zéro, rien de plus sur la pesée
  vidange-pesees etalonner pesee_griffe 10    étape 2 : un poids connu (ici 10 kg) posé
  vidange-pesees chariot                      chaque seconde, l'état de l'I2C du plateau (Ctrl+C)
  vidange-pesees servo servo_lame_micropore 90   met un servo à 90° (« coupe » : sortie coupée)
  ... --faux                                  pareil, avec le faux matériel (pour essayer)

« lire » montre, pour chaque carte : la mesure brute, le poids, les mesures faites par la carte
par seconde (80 attendues ; 2 pour la boîte du poste du fût), celles que le Pi a vues, les
questions sans réponse et les questions arrivées abîmées à la carte (câble, terminaison du bus).
La boîte du poste du fût dit aussi l'accu et la radio du plateau (outil « vidange-pesee »).

« chariot » et « servo » ne servent qu'à la carte du plateau du remplissage, qui commande les servos
et lit le capteur de distance du boîtier du chariot (pesee/essai-boitier-chariot.md). « servo »
envoie un seul ordre : la carte garde l'angle, même si l'outil s'arrête.

Chaque étape d'étalonnage affiche les lignes à recopier dans pi/reglages/pesees.yaml
(etalonnage). L'outil n'écrit jamais lui-même dans les réglages. Procédure complète :
pesee/essai-etabli.md.

À ne lancer que quand le programme principal est arrêté (l'adaptateur ne s'ouvre qu'une fois).
"""

import argparse
import sys
import time
from statistics import median

from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.journal import configurer_journal
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel
from vidange.materiel.carte_pesee import TOF_ETAT_MUET, BoitierChariot
from vidange.pesees.tour import TourPesees
from vidange.pesees.verification import pesees_du_bus, verifier_avec_liste
from vidange.poste_fut.pesee import pente
from vidange.reglages import ErreurReglages, I2cPesee, ReglagesPesees, charger_reglages

# Durée d'une étape d'étalonnage (s) : la médiane de toutes les mesures de ce temps.
DUREE_ETALONNAGE_S = 3.0


def main(arguments: list[str] | None = None, fabrique=None) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-pesees", description=__doc__.split("\n")[0])
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument(
        "--entrees-sorties", help="liste des entrées/sorties (défaut : docs/entrees-sorties.yaml)"
    )
    lecteur.add_argument("--faux", action="store_true", help="avec le faux matériel")
    commandes = lecteur.add_subparsers(dest="commande", required=True)
    lire = commandes.add_parser("lire", help="une ligne par carte chaque seconde")
    lire.add_argument("--secondes", type=int, help="durée (défaut : sans fin)")
    zero = commandes.add_parser("zero", help="étape 1 : zéro, rien de plus sur la pesée")
    zero.add_argument("carte", help="nom de la pesée (exemple : pesee_griffe)")
    etalonner = commandes.add_parser("etalonner", help="étape 2 : poids connu posé")
    etalonner.add_argument("carte", help="nom de la pesée (exemple : pesee_griffe)")
    etalonner.add_argument("kg", type=float, help="le poids connu, en kg (exemple : 10)")
    chariot = commandes.add_parser("chariot", help="l'état de l'I2C du plateau, chaque seconde")
    chariot.add_argument("--secondes", type=int, help="durée (défaut : sans fin)")
    servo = commandes.add_parser("servo", help="met un servo à un angle")
    servo.add_argument("voie", help="nom de la voie (exemple : servo_lame_micropore)")
    servo.add_argument("angle", help="angle en degrés, ou « coupe » (sortie coupée)")
    options = lecteur.parse_args(arguments)
    configurer_journal()
    dossier = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    chemin_liste = _chemin(
        options.entrees_sorties,
        "VIDANGE_ENTREES_SORTIES",
        DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml",
    )
    try:
        reglages = charger_reglages(dossier)
        liste = charger_entrees_sorties(chemin_liste)
    except ErreurReglages as erreur:
        print(erreur, file=sys.stderr)
        return 2
    erreurs = verifier_avec_liste(reglages.pesees, liste)
    if erreurs:
        print("\n".join(erreurs), file=sys.stderr)
        return 2
    cartes = list(pesees_du_bus(liste))
    if options.commande in ("zero", "etalonner") and options.carte not in cartes:
        print(f"pesée inconnue « {options.carte} » (pesées : {', '.join(cartes)})", file=sys.stderr)
        return 2
    if fabrique is None and options.faux:
        fabrique = FausseFabrique(liste)
    with Materiel(liste, fabrique, seulement=cartes) as materiel:
        if options.commande in ("chariot", "servo"):
            return _chariot(materiel, reglages.pesees, options)
        tour = TourPesees(reglages.pesees, materiel)
        if options.commande == "lire":
            return _lire(tour, options.secondes)
        return _etalonner(tour, options.carte, options.commande, getattr(options, "kg", 0.0))


def _chariot(materiel: Materiel, reglages: ReglagesPesees, options) -> int:
    """« chariot » : l'état de l'I2C du plateau ; « servo » : un ordre à un servo."""
    i2c = reglages.i2c
    if i2c is None:
        print("pesees.yaml n'a pas d'I2C (section « i2c »)", file=sys.stderr)
        return 2
    voies = list(i2c.pca9685.voies)
    try:
        if options.commande == "servo":
            return _servo(materiel, i2c, voies, options.voie, options.angle)
        secondes = options.secondes
        while secondes is None or secondes > 0:
            etat = materiel.lire_boitier_chariot(i2c.carte, len(voies))
            print(_ligne_chariot(etat, voies))
            time.sleep(1.0)
            if secondes is not None:
                secondes -= 1
    except ErreurMateriel as erreur:
        print(f"ÉCHEC : {erreur}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


def _servo(materiel: Materiel, i2c: I2cPesee, voies: list[str], voie: str, texte: str) -> int:
    if voie not in voies:
        print(f"voie inconnue « {voie} » (voies : {', '.join(voies)})", file=sys.stderr)
        return 2
    reglage = i2c.pca9685.voies[voie]
    angle: float | None = None
    if texte != "coupe":
        try:
            angle = float(texte.replace(",", "."))
        except ValueError:
            print(f"angle « {texte} » : un nombre de degrés, ou « coupe »", file=sys.stderr)
            return 2
        if not reglage.angle_min_deg <= angle <= reglage.angle_max_deg:
            print(
                f"{voie} : {angle:g}° est hors de sa plage ({reglage.angle_min_deg:g}° à "
                f"{reglage.angle_max_deg:g}°), rien n'est envoyé",
                file=sys.stderr,
            )
            return 2
    materiel.ecrire_angles_chariot(i2c.carte, [angle], premiere_voie=voies.index(voie))
    print(f"{voie} : {'sortie coupée' if angle is None else f'{angle:g}°'} (ordre envoyé)")
    return 0


def _ligne_chariot(etat: BoitierChariot, voies: list[str]) -> str:
    if etat.distance_mm is not None:
        distance = f"{etat.distance_mm} mm"
    elif etat.etat_tof == TOF_ETAT_MUET:
        distance = "ToF MUET"
    else:
        distance = f"pas de mesure (état {etat.etat_tof})"
    angles = ", ".join(
        f"{voie} {'coupée' if angle is None else f'{angle:g}°'}"
        for voie, angle in zip(voies, etat.angles_deg, strict=True)
    )
    alertes = [
        texte
        for texte, vrai in (
            ("PCA9685 MUETTE", etat.pca9685_muette),
            ("aucun ordre depuis le démarrage", etat.aucun_ordre),
            ("PI SILENCIEUX (angles gardés)", etat.pi_silencieux),
            ("PCA9685 pas démarrée", etat.pca9685_demarre_pas),
        )
        if vrai
    ]
    return (
        f"distance {distance}  démarrages {etat.demarrages}  "
        f"échecs I2C {etat.echecs_i2c}  dernier ordre il y a {etat.silence_pi_ms} ms  "
        f"{angles}" + ("  " + ", ".join(alertes) if alertes else "")
    )


def _pendant(tour: TourPesees, duree_s: float) -> None:
    """Fait des tours pendant ce temps (sans pause : comme le programme principal)."""
    fin = time.monotonic() + duree_s
    while time.monotonic() < fin:
        if not tour.faire_un_tour():
            time.sleep(min(tour.reglages.reconnexion_s, max(fin - time.monotonic(), 0)))


def _lire(tour: TourPesees, secondes: int | None) -> int:
    avant = {n: (e.questions, e.reponses, e.mesures_vues) for n, e in tour.etats.items()}
    try:
        while secondes is None or secondes > 0:
            _pendant(tour, 1.0)
            for nom, etat in tour.etats.items():
                questions, reponses, vues = avant[nom]
                sans_reponse = (etat.questions - questions) - (etat.reponses - reponses)
                vues = etat.mesures_vues - vues
                avant[nom] = (etat.questions, etat.reponses, etat.mesures_vues)
                print(_ligne(tour, nom, sans_reponse, vues))
            print()
            if secondes is not None:
                secondes -= 1
    except KeyboardInterrupt:
        pass
    return 0


def _ligne(tour: TourPesees, nom: str, sans_reponse: int, vues: int) -> str:
    etat = tour.etats[nom]
    if etat.derniere is None:
        return f"{nom:28} ne répond pas : {etat.erreur}"
    mesure = etat.derniere[1]
    try:
        poids = f"{tour.capteur(nom).lire_kg():9.3f} kg"
    except ErreurMateriel as erreur:
        poids = f"ÉCHEC ({erreur})"
    return (
        f"{nom:28} brut {mesure.brut:9d}  {poids}  carte {mesure.par_seconde:3d} mesures/s  "
        f"vues par le Pi {vues:3d}/s  sans réponse {sans_reponse:3d}  "
        f"trames abîmées {mesure.trames_abimees}"
        + ("  HX711 MUET" if mesure.hx711_muet else "")
        + ("  RADIO MUETTE" if mesure.radio_muette else "")
    )


def _brut_median(tour: TourPesees, nom: str) -> int | None:
    """La médiane des mesures brutes de la carte pendant DUREE_ETALONNAGE_S."""
    valeurs: list[int] = []
    numero = None
    fin = time.monotonic() + DUREE_ETALONNAGE_S
    while time.monotonic() < fin:
        tour.interroger(nom)
        derniere = tour.etats[nom].derniere
        if (
            derniere is not None
            and not derniere[1].hx711_muet
            and not derniere[1].radio_muette
            and derniere[1].numero != numero
        ):
            numero = derniere[1].numero
            valeurs.append(derniere[1].brut)
    if not valeurs:
        etat = tour.etats[nom]
        print(f"ÉCHEC : aucune mesure de « {nom} » ({etat.erreur or 'HX711 ou radio muets'})")
        return None
    return round(median(valeurs))


def _etalonner(tour: TourPesees, nom: str, commande: str, kg: float) -> int:
    brut = _brut_median(tour, nom)
    if brut is None:
        return 1
    if commande == "zero":
        print(f"Zéro mesuré. Recopier dans pesees.yaml (etalonnage → {nom}) :")
        print(f"    zero_brut: {brut}")
        return 0
    zero_brut = tour.reglages.etalonnage[nom].zero_brut
    try:
        resultat = pente(zero_brut, brut, kg)
    except ValueError as erreur:
        print(f"ÉCHEC : {erreur}", file=sys.stderr)
        return 1
    print(f"Mesure brute avec {kg:g} kg : {brut} (zéro : {zero_brut}).")
    print(f"Recopier dans pesees.yaml (etalonnage → {nom}) :")
    print(f"    brut_par_kg: {resultat:.2f}")
    return 0


def lancer() -> None:
    sys.exit(main())
