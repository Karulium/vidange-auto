"""Outil « vidange-accelerometre » pour les essais à l'établi (accelerometre/essai-etabli.md).

  vidange-accelerometre etat          l'état du RP2040 et ses réglages
  vidange-accelerometre suivre        l'état chaque seconde, et chaque choc (Ctrl-C pour finir)
  vidange-accelerometre envoyer       envoie les réglages de accelerometre.yaml au RP2040
  vidange-accelerometre question ETAT pose une question telle quelle (voir liaison.h)

Options : --port /dev/ttyUSB0 (un autre port que celui de entrees-sorties.yaml),
--faux (avec un faux RP2040, pour voir sans matériel).
À ne lancer que quand le programme principal est arrêté (un port ne s'ouvre qu'une fois).
"""

import argparse
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import replace

from vidange.accelerometre.faux import FauxRp2040
from vidange.accelerometre.liaison import (
    SIGNAL,
    LiaisonAccelerometre,
    PortAccelerometre,
    ouvrir_port,
)
from vidange.accelerometre.protocole import (
    ErreurProtocole,
    EtatRp2040,
    lire_reglages,
    question_regler,
    reglages_pour_rp2040,
    texte_pannes,
)
from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.journal import configurer_journal
from vidange.reglages import ErreurReglages, ReglagesAccelerometre, charger_reglages


def decrire(etat: EtatRp2040) -> str:
    if etat.ok:
        debut = "OK"
    elif etat.pannes:
        debut = f"COUPÉ : panne ({texte_pannes(etat.pannes)})"
    elif etat.en_choc:
        debut = "COUPÉ : choc"
    else:
        debut = "COUPÉ : démarrage"
    texte = (
        f"{debut} | max {etat.max_mg / 1000:.2f} g | chocs {etat.chocs} | "
        f"allumé depuis {etat.t_ms / 1000:.0f} s"
    )
    if etat.redemarre_par_chien:
        texte += " | redémarré par le chien de garde"
    if etat.mesures_perdues:
        texte += f" | mesures perdues {etat.mesures_perdues}"
    if etat.sortie_contredit:
        texte += " | ATTENTION : la broche OK ne suit pas"
    return texte


def montrer_etat(liaison: LiaisonAccelerometre) -> int:
    reponse = liaison.demander("ETAT")
    if reponse is None:
        print("Pas de réponse : voir accelerometre/essai-etabli.md (câblage du fil, vitesse).")
        return 1
    try:
        print(decrire(EtatRp2040.lire(reponse)))
        reponse = liaison.demander("REGLAGES")
        if reponse is None:
            print("Réglages : pas de réponse.")
            return 1
        chez_lui = lire_reglages(reponse)
    except ErreurProtocole as erreur:
        print(f"Réponse mal formée : {erreur}")
        return 1
    voulus = reglages_pour_rp2040(liaison.reglages)
    print("Réglages du RP2040 (entre crochets : accelerometre.yaml, s'il est différent) :")
    for nom, valeur in chez_lui.items():
        autre = "" if voulus.get(nom) == valeur else f"  [{voulus.get(nom)}]"
        print(f"  {nom} = {valeur}{autre}")
    return 0


def suivre(liaison: LiaisonAccelerometre, arret: threading.Event) -> int:
    """Les chocs et les pannes s'écrivent au journal (à l'écran) ; l'état chaque seconde."""
    print("Suivi de l'accéléromètre (Ctrl-C pour finir).")
    dernier: float | None = None
    maximum = 0
    while True:
        liaison.tour()
        etat = liaison.etat
        if etat is not None:
            maximum = max(maximum, etat.max_mg)
        if dernier is None or time.monotonic() - dernier >= 1:
            dernier = time.monotonic()
            print("pas de réponse" if etat is None else decrire(replace(etat, max_mg=maximum)))
            maximum = 0
        if arret.wait(liaison.reglages.liaison.periode_ms / 1000):
            return 0


def envoyer(liaison: LiaisonAccelerometre) -> int:
    reponse = liaison.demander(question_regler(reglages_pour_rp2040(liaison.reglages)))
    print(reponse or "Pas de réponse.")
    return 0 if reponse == "REGLER ok" else 1


def preparer_port(
    options: argparse.Namespace, reglages: ReglagesAccelerometre
) -> Callable[[], PortAccelerometre] | str:
    """De quoi ouvrir le port, ou le message d'erreur."""
    if options.faux:
        return FauxRp2040(reglages).ouvrir
    vitesse = reglages.liaison.vitesse_bauds
    if options.port:
        return ouvrir_port(options.port, vitesse)
    chemin = _chemin(
        options.entrees_sorties,
        "VIDANGE_ENTREES_SORTIES",
        DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml",
    )
    try:
        signal = charger_entrees_sorties(chemin).signaux.get(SIGNAL)
    except ErreurReglages as erreur:
        return str(erreur)
    if signal is None or signal.fichier is None:
        return f"Pas de signal « {SIGNAL} » (avec son « fichier ») dans {chemin} : donner --port."
    return ouvrir_port(signal.fichier, vitesse)


def main(arguments: list[str] | None = None, arret: threading.Event | None = None) -> int:
    lecteur = argparse.ArgumentParser(
        prog="vidange-accelerometre",
        description="Essais du fil série entre le Pi et le RP2040 de l'accéléromètre.",
    )
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument(
        "--entrees-sorties", help="liste des entrées/sorties (défaut : docs/entrees-sorties.yaml)"
    )
    lecteur.add_argument("--port", help="port série à utiliser (exemple : /dev/ttyUSB0)")
    lecteur.add_argument("--faux", action="store_true", help="avec un faux RP2040")
    sous = lecteur.add_subparsers(dest="action", required=True)
    sous.add_parser("etat", help="l'état du RP2040 et ses réglages")
    sous.add_parser("suivre", help="l'état chaque seconde, et chaque choc")
    sous.add_parser("envoyer", help="envoie les réglages de accelerometre.yaml")
    question = sous.add_parser("question", help="pose une question telle quelle")
    question.add_argument("texte", nargs="+", help="exemple : ETAT, ou CHOC 1")
    options = lecteur.parse_args(arguments)

    configurer_journal()
    dossier = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    try:
        reglages = charger_reglages(dossier).accelerometre
    except ErreurReglages as erreur:
        print(erreur)
        return 2
    ouvrir = preparer_port(options, reglages)
    if isinstance(ouvrir, str):
        print(ouvrir)
        return 2
    liaison = LiaisonAccelerometre(reglages, ouvrir)
    try:
        if options.action == "etat":
            return montrer_etat(liaison)
        if options.action == "envoyer":
            return envoyer(liaison)
        if options.action == "question":
            reponse = liaison.demander(" ".join(options.texte))
            print(reponse or "Pas de réponse.")
            return 0 if reponse else 1
        try:
            return suivre(liaison, arret or threading.Event())
        except KeyboardInterrupt:
            return 0
    finally:
        liaison.fermer()


def lancer() -> None:
    """Point d'entrée de la commande « vidange-accelerometre »."""
    sys.exit(main())
