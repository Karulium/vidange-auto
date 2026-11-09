"""La commande « vidange restaurer » : remettre un Pi neuf en état (voir restauration.py).

  vidange restaurer [--depuis SOURCE] [--ecraser] [--sans-service] [--sans-photos]
  vidange restaurer --photos-seulement      (remettre les photos plus tard)

SOURCE : « machine:dossier » (rsync par Tailscale) ou un dossier du Pi (clé USB). Sans SOURCE :
là où la copie de secours est envoyée chaque jour (programme.yaml → envois → secours → commande).
Pas à pas : pi/systeme/essai-restauration.md.
"""

import argparse
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

from vidange.restauration.restauration import (
    Chemins,
    Commandes,
    ErreurRestauration,
    Options,
    restaurer,
    source_par_defaut,
)

UTILISATEUR = "vidange"


class CommandesReelles:
    def lancer(self, commande: list[str], delai_s: float) -> tuple[int, str]:
        try:
            fin = subprocess.run(
                commande, capture_output=True, text=True, timeout=delai_s, check=False
            )
        except FileNotFoundError:
            return 127, f"commande introuvable : {commande[0]}"
        except subprocess.TimeoutExpired:
            return 124, f"« {commande[0]} » a duré plus de {int(delai_s)} s"
        return fin.returncode, (fin.stdout + fin.stderr)


def _donner_au_programme(chemin: Path) -> None:
    """Le compte du programme doit pouvoir lire et écrire ce qu'on vient de remettre."""
    try:
        pwd.getpwnam(UTILISATEUR)
    except KeyError:
        return
    if chemin.is_dir():
        for sous in [chemin, *chemin.rglob("*")]:
            shutil.chown(sous, UTILISATEUR, UTILISATEUR)
    else:
        shutil.chown(chemin, UTILISATEUR, UTILISATEUR)


def lancer_restauration(
    arguments: list[str], commandes: Commandes | None = None, root: bool | None = None
) -> int:
    from vidange.demarrage import DOSSIER_PI, _chemin, chemin_des_comptes, principal
    from vidange.journal import configurer_journal
    from vidange.reglages import ErreurReglages, charger_reglages

    lecteur = argparse.ArgumentParser(prog="vidange restaurer", description=__doc__.split("\n")[0])
    lecteur.add_argument("--depuis", help="la copie de secours : machine:dossier, ou un dossier")
    lecteur.add_argument("--ecraser", action="store_true", help="remplacer un registre existant")
    lecteur.add_argument("--sans-service", action="store_true", help="ne pas lancer le service")
    lecteur.add_argument("--sans-photos", action="store_true", help="remettre les photos plus tard")
    lecteur.add_argument("--photos-seulement", action="store_true", help="remettre les photos")
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument("--entrees-sorties", help="liste des entrées/sorties")
    lecteur.add_argument("--secrets", help="fichier de secrets (défaut : pi/secrets.yaml)")
    lecteur.add_argument("--comptes", help="fichier des comptes (défaut : à côté des secrets)")
    lecteur.add_argument("--depot", help="dossier du dépôt Git (défaut : celui du programme)")
    lecteur.add_argument("--donnees", help="dossier des données (défaut : pi/donnees)")
    options = lecteur.parse_args(arguments)

    configurer_journal()
    dossier_reglages = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    chemin_secrets = _chemin(options.secrets, "VIDANGE_SECRETS", DOSSIER_PI / "secrets.yaml")
    chemins = Chemins(
        donnees=_chemin(options.donnees, "VIDANGE_DONNEES", DOSSIER_PI / "donnees"),
        secrets=chemin_secrets,
        comptes=(
            Path(options.comptes)
            if options.comptes
            else chemin_des_comptes()
            if not options.secrets
            else chemin_secrets.with_name("comptes.yaml")
        ),
        secrets_exemple=DOSSIER_PI / "secrets.exemple.yaml",
        depot=Path(options.depot) if options.depot else DOSSIER_PI.parent,
    )
    try:
        reglages = charger_reglages(dossier_reglages)
    except ErreurReglages as erreur:
        print(f"Réglages faux, restauration impossible :\n{erreur}", file=sys.stderr)
        return 2
    source = options.depuis or source_par_defaut(reglages)
    if not source:
        print(
            "Impossible : dire où est la copie de secours avec --depuis machine:dossier (ou un "
            "dossier de clé USB). programme.yaml (envois → secours → commande) est vide.",
            file=sys.stderr,
        )
        return 2

    arguments_verification = ["--verifier", "--reglages", str(dossier_reglages)]
    arguments_verification += ["--secrets", str(chemins.secrets)]
    arguments_verification += ["--comptes", str(chemins.comptes)]
    arguments_verification += ["--donnees", str(chemins.donnees)]
    if options.entrees_sorties:
        arguments_verification += ["--entrees-sorties", options.entrees_sorties]

    est_root = root if root is not None else (shutil.os.geteuid() == 0)
    try:
        bilan = restaurer(
            chemins,
            reglages,
            source,
            commandes or CommandesReelles(),
            verifier=lambda: principal(arguments_verification),
            options=Options(
                ecraser=options.ecraser,
                avec_service=not options.sans_service,
                avec_photos=not options.sans_photos,
                photos_seulement=options.photos_seulement,
            ),
            donner_au_programme=_donner_au_programme if est_root else None,
        )
    except ErreurRestauration as erreur:
        print(f"Restauration impossible : {erreur}", file=sys.stderr)
        return 2

    print("\nFAIT :")
    for ligne in bilan.fait:
        print(f"  - {ligne}")
    if bilan.problemes:
        print("\nPROBLÈMES :")
        for ligne in bilan.problemes:
            print(f"  - {ligne}")
    if bilan.a_la_main:
        print("\nIL RESTE À FAIRE À LA MAIN :")
        for numero, ligne in enumerate(bilan.a_la_main, 1):
            print(f"  {numero}. {ligne}")
    return 0 if bilan.reussi else 1
