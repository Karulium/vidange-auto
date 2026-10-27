"""Outil « vidange-envois » pour regarder la file d'envoi et agir dessus.

  vidange-envois etat             ce qui attend, ce qui est refusé, les dernières erreurs
  vidange-envois montrer <cycle>  les données d'un cycle, telles que le logiciel de culture
                                  les reçoit (JSON, format de docs/django.md)
  vidange-envois renvoyer <n°>    remet un envoi dans la file (après une correction)
  vidange-envois essayer          une tournée tout de suite, sans attendre (essais du réseau)

Peut tourner pendant que le programme principal tourne. Un envoi fait deux fois (par l'outil
et par le programme) n'est pas grave : il porte la même clé, le destinataire le reconnaît.
"""

import argparse
import json
import sys
from zoneinfo import ZoneInfo

from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.envois.cycle import donnees_cycle
from vidange.envois.facteur import DESTINATIONS, preparer_facteur
from vidange.fichier_secrets import charger_secrets
from vidange.journal import configurer_journal
from vidange.registre import ErreurRegistre, Registre, ouvrir_registre
from vidange.reglages import ErreurReglages, ReglagesEnvois, charger_reglages


def montrer_etat(registre: Registre, reglages: ReglagesEnvois) -> None:
    for destination, nom in DESTINATIONS.items():
        comptes = {
            ligne["statut"]: ligne["nombre"]
            for ligne in registre.lire(
                "SELECT statut, COUNT(*) AS nombre FROM envois WHERE destination = ? "
                "GROUP BY statut",
                (destination,),
            )
        }
        print(
            f"{nom} : {comptes.get('attente', 0)} en attente, {comptes.get('refuse', 0)} "
            f"refusé(s), {comptes.get('envoye', 0)} envoyé(s) ces "
            f"{reglages.garder_envoyes_jours} derniers jours"
        )
        for envoi in registre.lire(
            "SELECT * FROM envois WHERE destination = ? AND statut != 'envoye' ORDER BY id "
            "LIMIT 20",
            (destination,),
        ):
            print(
                f"  n° {envoi['id']:<6} {envoi['statut']:<8} {envoi['sorte']} {envoi['objet']}"
                f" (depuis {envoi['cree_le']}, {envoi['essais']} essai(s))"
            )
            if envoi["derniere_erreur"]:
                print(f"           {envoi['derniere_erreur']}")


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-envois", description=__doc__.split("\n")[0])
    lecteur.add_argument("ordre", choices=["etat", "montrer", "renvoyer", "essayer"])
    lecteur.add_argument("numero", nargs="?", type=int, help="n° du cycle ou de l'envoi")
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument("--donnees", help="dossier des données (défaut : pi/donnees)")
    lecteur.add_argument("--secrets", help="fichier de secrets (défaut : pi/secrets.yaml)")
    options = lecteur.parse_args(arguments)
    if options.ordre in ("montrer", "renvoyer") and options.numero is None:
        lecteur.error(f"« {options.ordre} » demande un numéro")
    configurer_journal()
    reglages_dossier = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    donnees = _chemin(options.donnees, "VIDANGE_DONNEES", DOSSIER_PI / "donnees")
    try:
        reglages = charger_reglages(reglages_dossier)
        registre = ouvrir_registre(donnees)
    except (ErreurReglages, ErreurRegistre) as erreur:
        print(erreur, file=sys.stderr)
        return 2
    envois = reglages.programme.envois
    try:
        if options.ordre == "etat":
            montrer_etat(registre, envois)
        elif options.ordre == "montrer":
            lignes = registre.lire(
                "SELECT cle FROM envois WHERE sorte = 'cycle' AND objet = ? ORDER BY id DESC",
                (str(options.numero),),
            )
            cle = lignes[0]["cle"] if lignes else "(pas encore dans la file)"
            donnees_json = donnees_cycle(
                registre,
                options.numero,
                cle,
                envois.culture.machine,
                ZoneInfo(envois.culture.fuseau_horaire),
            )
            print(json.dumps(donnees_json, ensure_ascii=False, indent=2))
        elif options.ordre == "renvoyer":
            registre.renvoyer(options.numero)
            print(f"Envoi n° {options.numero} remis dans la file.")
        else:
            chemin_secrets = _chemin(
                options.secrets, "VIDANGE_SECRETS", DOSSIER_PI / "secrets.yaml"
            )
            jeton = charger_secrets(chemin_secrets).jeton_culture
            facteur = preparer_facteur(
                registre, envois, jeton.get_secret_value() if jeton else None, donnees
            )
            print(f"{facteur.tournee()} envoi(s) réussi(s).")
            montrer_etat(registre, envois)
        return 0
    except (ErreurRegistre, ErreurReglages) as erreur:
        print(erreur, file=sys.stderr)
        return 1
    finally:
        registre.fermer()


def lancer() -> None:
    sys.exit(main())
