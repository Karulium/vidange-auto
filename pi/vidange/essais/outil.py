"""« vidange plan » : les plans d'essais (tâche 31).

    vidange plan                      la liste des plans (n°, état, nom, lot visé)
    vidange plan verifier FICHIER     vérifie un plan et montre son tableau, sans le garder
    vidange plan charger FICHIER      vérifie un plan et le garde comme PROPOSITION
    vidange plan montrer N            le tableau seau par seau, et ce qui a été appliqué
    vidange plan essayer FICHIER|N    rejoue le lot du plan au simulateur, comparé au lot normal
    vidange plan retirer N            retire un plan chargé ou accepté (pas un plan lancé)

Un plan chargé ne sert à rien tant que Karulium ne l'a pas accepté sur la page web (onglet
« Réglages », rôle « régler ») : la commande ne peut pas accepter. Elle marche programme arrêté ou
en marche (tout est dans le registre). Codes de sortie : 0 bon, 1 refusé, 2 réglages ou registre
illisibles.
"""

import argparse
import getpass
import sys
from pathlib import Path

from vidange.essais.plan import ErreurPlan, lire_plan
from vidange.essais.plans import ETATS, PlansEssais
from vidange.registre.base import ErreurRegistre, Registre
from vidange.reglages import ErreurReglages, charger_reglages


def _qui() -> str:
    try:
        return f"commande « vidange plan » ({getpass.getuser()})"
    except (KeyError, OSError):
        return "commande « vidange plan »"


def _lire_fichier(chemin: str) -> str:
    try:
        return Path(chemin).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ErreurPlan([f"{chemin} : fichier non enregistré en UTF-8"]) from None
    except OSError as erreur:
        raise ErreurPlan([f"{chemin} : fichier illisible ({erreur.strerror})"]) from None


def lancer_plan(
    arguments: list[str],
    dossier_donnees: Path,
    dossier_reglages: Path,
    chemin_entrees_sorties: Path,
) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange plan", description=__doc__.split("\n")[0])
    lecteur.add_argument(
        "action",
        nargs="?",
        choices=["liste", "verifier", "charger", "montrer", "essayer", "retirer"],
        default="liste",
    )
    lecteur.add_argument("quoi", nargs="?", help="fichier du plan, ou n° d'un plan chargé")
    options = lecteur.parse_args(arguments)
    if options.action != "liste" and not options.quoi:
        lecteur.error(f"« vidange plan {options.action} » : donner un fichier ou un n° de plan")
    try:
        reglages = charger_reglages(dossier_reglages)
    except ErreurReglages as erreur:
        print(erreur, file=sys.stderr)
        return 2
    if options.action == "verifier":
        try:
            plan = lire_plan(_lire_fichier(options.quoi), reglages.machine, reglages.essais)
        except ErreurPlan as erreur:
            print(erreur, file=sys.stderr)
            return 1
        print("Plan correct (pas gardé : « vidange plan charger » pour le proposer).")
        print(plan.en_texte(reglages.machine, reglages.essais))
        return 0
    try:
        registre = Registre(dossier_donnees / "registre.sqlite", dossier_donnees / "photos")
    except ErreurRegistre as erreur:
        print(f"Registre illisible : {erreur}", file=sys.stderr)
        return 2
    plans = PlansEssais(registre, reglages.machine, reglages.essais)
    try:
        return _faire(options.action, options.quoi, plans, dossier_reglages, chemin_entrees_sorties)
    except ErreurPlan as erreur:
        print(erreur, file=sys.stderr)
        return 1
    finally:
        registre.fermer()


def _numero(texte: str) -> int:
    if not texte.strip().isdigit():
        raise ErreurPlan([f"« {texte} » : donner le n° du plan (« vidange plan » les liste)"])
    return int(texte)


def _faire(
    action: str,
    quoi: str | None,
    plans: PlansEssais,
    dossier_reglages: Path,
    chemin_entrees_sorties: Path,
) -> int:
    if action == "liste":
        liste = plans.liste()
        if not liste:
            print("Aucun plan d'essais (« vidange plan charger FICHIER » pour en proposer un).")
        for plan in liste:
            print(
                f"n° {plan['numero']} : « {plan['nom']} » de {plan['auteur']}, lot de {plan['lot']}"
            )
            print(f"       {ETATS[plan['etat']]} ; {plan['seaux_faits']} seau(x) fait(s)")
        return 0
    assert quoi is not None
    if action == "charger":
        numero = plans.charger(_lire_fichier(quoi), _qui())
        print(f"Plan chargé : n° {numero}. Il n'est qu'une PROPOSITION : Karulium l'accepte sur la")
        print("page web (onglet « Réglages », rôle « régler »), après avoir vu ce tableau :")
        print(plans.en_dict(numero)["texte"])
        return 0
    if action == "montrer":
        plan = plans.en_dict(_numero(quoi))
        print(f"n° {plan['numero']} : {ETATS[plan['etat']]}")
        print(plan["texte"])
        if plan["appliques"]:
            print("Valeurs vraiment appliquées :")
        for a in plan["appliques"]:
            mesure = "" if a["mesure"] is None else f", mesuré {a['mesure']:g} {a['unite'] or ''}"
            couche = "" if a["couche"] is None else f", couche {a['couche']}"
            print(
                f"  seau n° {a['numero']} ({a['seau'] or '?'}) : {a['variable']} = {a['voulu']}"
                f"{mesure}{couche} ({a['remarque']})"
            )
        return 0
    if action == "retirer":
        plans.retirer(_numero(quoi), _qui())
        print("Plan retiré.")
        return 0
    from vidange.simulateur.essai import ErreurEssai, essayer_plan

    texte = plans.texte(_numero(quoi)) if quoi.strip().isdigit() else _lire_fichier(quoi)
    try:
        comparaison = essayer_plan(dossier_reglages, chemin_entrees_sorties, texte)
    except ErreurEssai as erreur:
        print(f"Essai impossible : {erreur}", file=sys.stderr)
        return 1
    print(comparaison.en_texte())
    return 0 if comparaison.sans_probleme else 1
