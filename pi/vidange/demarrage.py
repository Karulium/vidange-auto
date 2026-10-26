"""Démarrage du programme du Pi.

1. Lit et vérifie les réglages et la liste des entrées/sorties : une erreur arrête
   tout, avec un message clair (code de sortie 2 : systemd ne relance pas en boucle
   un programme mal réglé).
2. Met en place le journal et lit les secrets.
3. Regarde comment s'est fini le passage précédent (arrêt propre, plantage, coupure de courant).
4. Ouvre le registre (base SQLite, montée à la dernière version) : une base abîmée arrête
   tout (code de sortie 3). Lance la copie de secours quotidienne.
5. Ouvre les entrées/sorties et les liaisons avec les cartes FluidNC. Du matériel qui manque
   n'arrête pas le programme : la check-list le signale et refuse la production.
6. Met en route le chef d'orchestre : reprend le cycle noté dans le carnet (après une coupure),
   et propose le retour en lieu sûr (il attend le Go de Karulium).
7. Lance la surveillance : santé du Pi, onduleur, chien de garde (et dit à systemd « prêt »),
   bilan de chaque alarme. Écrit la check-list de démarrage au journal.
8. Attend l'ordre d'arrêt, puis arrête tout proprement (machine en pause, état noté). Si l'ordre
   vient de l'onduleur, éteint le Pi à la fin.

Où trouver les fichiers (du plus fort au plus faible) : option de la ligne de
commande, puis variable d'environnement (posée par le service systemd), puis
l'emplacement dans le dépôt (pour les essais sur un PC).
"""

import argparse
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from vidange import __version__
from vidange.chef import Carnet, Chef, ErreurChef, Module
from vidange.entrees_sorties import EntreesSorties, charger_entrees_sorties
from vidange.fiabilite import (
    Bilans,
    CheckList,
    ChienDeGarde,
    FinPrecedente,
    Marche,
    Onduleur,
    Sante,
    Sondes,
    module_lieu_sur,
)
from vidange.fiabilite.checklist import (
    constats_chef,
    constats_materiel,
    constats_registre,
    constats_reglages,
)
from vidange.fiabilite.chien_de_garde import notifier_systemd
from vidange.fiabilite.lieu_sur import NOM as NOM_LIEU_SUR
from vidange.fiabilite.onduleur import RAISON_ARRET
from vidange.fiabilite.onduleur import SIGNAL as SIGNAL_ONDULEUR
from vidange.fichier_secrets import charger_secrets
from vidange.fluidnc import Liaison
from vidange.fluidnc.ports import Port
from vidange.journal import NOM_FICHIER, configurer_journal, donner_journal
from vidange.materiel import Materiel
from vidange.materiel.materiel import Fabrique
from vidange.quoi_faire import COUPURE_COURANT, PLANTAGE
from vidange.registre import (
    DOSSIER_SAUVEGARDES,
    ErreurRegistre,
    Registre,
    SauvegardeQuotidienne,
    ouvrir_registre,
)
from vidange.reglages import ErreurReglages, charger_reglages

# Codes de sortie. Le service systemd (pi/systeme/vidange.service) utilise CODE_REGLAGES_FAUX.
CODE_OK = 0
CODE_PLANTAGE = 1
CODE_REGLAGES_FAUX = 2
CODE_REGISTRE_ABIME = 3

DOSSIER_PI = Path(__file__).resolve().parent.parent
NOM_CARNET = "etat-cycle.json"

journal = donner_journal("demarrage")


def lancer_commande(commande: list[str]) -> None:
    subprocess.run(commande, check=True, timeout=60)


@dataclass
class Raccords:
    """Ce qui relie le programme au monde : le vrai matériel, ou des faux pour les essais."""

    # None : vraies broches et vrais bus du Pi.
    fabrique: Fabrique | None = None
    # Nom de carte → ouverture de son port ; None : vrais ports USB (par numéro de série).
    ports: Mapping[str, Callable[[], Port]] | None = None
    sondes: Sondes | None = None
    notifier: Callable[[str], bool] = notifier_systemd
    # Lance une commande du système (extinction du Pi par l'onduleur).
    lancer: Callable[[list[str]], object] = lancer_commande


def _chemin(option: str | None, variable: str, defaut: Path) -> Path:
    if option:
        return Path(option)
    if os.environ.get(variable):
        return Path(os.environ[variable])
    return defaut


def lire_arguments(arguments: list[str] | None) -> argparse.Namespace:
    lecteur = argparse.ArgumentParser(
        prog="vidange", description="Programme du Pi de la machine « Vidange automatique »."
    )
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument(
        "--entrees-sorties",
        help="liste des entrées/sorties (défaut : docs/entrees-sorties.yaml)",
    )
    lecteur.add_argument("--secrets", help="fichier de secrets (défaut : pi/secrets.yaml)")
    lecteur.add_argument("--donnees", help="dossier des données : journal... (défaut : pi/donnees)")
    lecteur.add_argument(
        "--verifier", action="store_true", help="vérifie les réglages et s'arrête sans démarrer"
    )
    return lecteur.parse_args(arguments)


def ouvrir_materiel(
    liste: EntreesSorties, fabrique: Fabrique | None
) -> tuple[Materiel | None, str | None]:
    """Ouvre les entrées/sorties. Si c'est impossible, au moins l'onduleur (arrêt propre).

    Rend le matériel ouvert (ou None) et l'erreur d'ouverture du tout (ou None).
    """
    try:
        return Materiel(liste, fabrique), None
    except Exception as erreur:
        journal.error("Entrées/sorties impossibles à ouvrir : %s", erreur)
        probleme = str(erreur)
    if SIGNAL_ONDULEUR in liste.signaux:
        try:
            materiel = Materiel(liste, fabrique, seulement=[SIGNAL_ONDULEUR])
            journal.warning("Seule l'entrée de l'onduleur est ouverte (arrêt propre).")
            return materiel, probleme
        except Exception as erreur:
            journal.error("Entrée de l'onduleur impossible à ouvrir : %s", erreur)
    return None, probleme


def noter_fin_brutale(registre: Registre, fin: FinPrecedente, carnet: Carnet) -> None:
    """Un plantage ou une coupure de courant est noté comme une alarme (à acquitter)."""
    try:
        etat = carnet.lire() or {}
    except ErreurChef:
        etat = {}
    en_cours = [
        f"« {note['module']} » à l'étape « {note['etape']} »"
        for note in etat.get("modules", [])
        if note.get("statut") in ("en_cours", "alarme") and note.get("module") != NOM_LIEU_SUR
    ]
    message = fin.decrire()
    if en_cours:
        message += " ; en plein cycle : " + ", ".join(en_cours)
    coupure = fin.sorte == "coupure"
    try:
        registre.noter_alarme(
            "alimentation" if coupure else "programme",
            message,
            COUPURE_COURANT if coupure else PLANTAGE,
        )
    except ErreurRegistre as erreur:
        journal.error("Fin brutale pas notée dans le registre : %s", erreur)


def preparer_chef(chef: Chef, lieu_sur: Module | None) -> tuple[list[str], str | None]:
    """Reprend le cycle du carnet ; propose le retour en lieu sûr (exclusif, attend le Go).

    Rend les modules repris et l'erreur de reprise (carnet qui ne correspond pas au programme).
    Les gestes des vrais modules arriveront avec les tâches des modules : pour l'instant,
    seul « lieu_sur » est connu du programme.
    """
    modules = [module for module in (lieu_sur,) if module is not None]
    try:
        repris = chef.reprendre_cycle(modules)
    except ErreurChef as erreur:
        journal.error("Reprise du cycle impossible : %s", erreur)
        return [], str(erreur)
    if lieu_sur is not None and lieu_sur.nom not in repris:
        chef.lancer(lieu_sur)
        journal.info("Retour en lieu sûr proposé : il attend le Go de Karulium.")
    return repris, None


def principal(
    arguments: list[str] | None = None,
    arret: threading.Event | None = None,
    raccords: Raccords | None = None,
) -> int:
    """Lance le programme et rend le code de sortie. `arret` et `raccords` servent aux tests."""
    options = lire_arguments(arguments)
    raccords = raccords or Raccords()
    dossier_reglages = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    chemin_entrees_sorties = _chemin(
        options.entrees_sorties,
        "VIDANGE_ENTREES_SORTIES",
        DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml",
    )
    chemin_secrets = _chemin(options.secrets, "VIDANGE_SECRETS", DOSSIER_PI / "secrets.yaml")
    dossier_donnees = _chemin(options.donnees, "VIDANGE_DONNEES", DOSSIER_PI / "donnees")

    # Journal à l'écran seulement, le temps de lire ses propres réglages.
    configurer_journal()
    try:
        reglages = charger_reglages(dossier_reglages)
        reglages_journal = reglages.programme.journal
        configurer_journal(
            niveau=reglages_journal.niveau,
            dossier=None if options.verifier else dossier_donnees / "journal",
            taille_fichier_mo=reglages_journal.taille_fichier_mo,
            nombre_fichiers=reglages_journal.nombre_fichiers,
        )
        entrees_sorties = charger_entrees_sorties(chemin_entrees_sorties)
        charger_secrets(chemin_secrets)
    except ErreurReglages as erreur:
        journal.error("%s", erreur)
        return CODE_REGLAGES_FAUX

    if reglages.machine.exemple:
        journal.warning(
            "machine.yaml contient des valeurs d'EXEMPLE (exemple: true) : "
            "ne pas faire bouger la vraie machine avec."
        )
    if reglages.fluidnc.exemple:
        journal.warning(
            "fluidnc.yaml contient des numéros de série d'EXEMPLE (exemple: true) : "
            "les cartes FluidNC ne seront pas trouvées."
        )
    exemples = entrees_sorties.exemples()
    if exemples:
        journal.warning(
            "entrees-sorties.yaml : %d lignes d'EXEMPLE (exemple: true) : ne pas brancher "
            "la vraie machine d'après elles.",
            len(exemples),
        )
    if options.verifier:
        journal.info("Réglages corrects (%s).", dossier_reglages)
        return CODE_OK

    marche = Marche(dossier_donnees)
    fin = marche.demarrer()
    journal.info("Passage précédent : %s.", fin.decrire())

    try:
        registre = ouvrir_registre(dossier_donnees)
    except ErreurRegistre as erreur:
        journal.error("%s", erreur)
        marche.noter_arret("registre abîmé")
        return CODE_REGISTRE_ABIME

    if arret is None:
        arret = threading.Event()
        for sorte in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sorte, lambda *_: arret.set())
    raison_arret = ["demandé"]

    def demander_arret(raison: str) -> None:
        raison_arret[0] = raison
        arret.set()

    carnet = Carnet(dossier_donnees / NOM_CARNET)
    if fin.brutale:
        noter_fin_brutale(registre, fin, carnet)
    sauvegarde = SauvegardeQuotidienne(
        registre, dossier_donnees / DOSSIER_SAUVEGARDES, reglages.programme.registre
    )
    fils = [sauvegarde.demarrer(arret)]
    materiel, erreur_materiel = ouvrir_materiel(entrees_sorties, raccords.fabrique)
    ports = raccords.ports or {}
    liaisons = {
        nom: Liaison(nom, reglages.fluidnc, ouvrir=ports.get(nom))
        for nom in reglages.fluidnc.cartes
    }
    fiabilite = reglages.programme.fiabilite
    chef = Chef(reglages.machine, reglages.programme.chef, carnet)
    sante = Sante(dossier_donnees, fiabilite.sante, registre, sauvegarde.copies, raccords.sondes)
    bilans = Bilans(
        dossier_donnees,
        fiabilite.bilan,
        registre,
        chef,
        liaisons,
        materiel,
        sante.constats,
        dossier_donnees / "journal" / NOM_FICHIER,
    )
    chef.sur_alarme.append(bilans.recevoir)
    onduleur = Onduleur(fiabilite.onduleur, materiel, chef, demander_arret)
    gardien = ChienDeGarde(
        fiabilite.chien_de_garde, liaisons, chef, materiel, notifier=raccords.notifier
    )
    # Le fil des bilans s'arrête après le chef : il finit les bilans des dernières alarmes.
    arret_bilans = threading.Event()
    fil_bilans = bilans.demarrer(arret_bilans)
    try:
        for liaison in liaisons.values():
            liaison.demarrer()
        _, erreur_reprise = preparer_chef(chef, module_lieu_sur(reglages.machine, liaisons))
        chef.demarrer()
        fils += [sante.demarrer(arret), onduleur.demarrer(arret), gardien.demarrer(arret)]
        checklist = CheckList(
            {
                "réglages": lambda: constats_reglages(reglages, entrees_sorties),
                "entrées/sorties": lambda: constats_materiel(
                    materiel if erreur_materiel is None else None,
                    erreur_materiel,
                    entrees_sorties,
                ),
                "cartes": gardien.constats,
                "chef": lambda: constats_chef(chef, erreur_reprise),
                "registre": lambda: constats_registre(registre),
                "santé du Pi": sante.constats,
                "onduleur": onduleur.constats,
            }
        )
        gardien.pret()
        journal.info(
            "Programme du Pi version %s démarré, réglages : %s", __version__, dossier_reglages
        )
        checklist.ecrire_au_journal(checklist.verifier())
        arret.wait()
        journal.info("Arrêt (%s) : arrêt propre.", raison_arret[0])
    finally:
        gardien.arreter()
        # Un module en plein geste : les axes s'arrêtent sans perdre leur position, et l'état
        # est noté dans le carnet (reprise au prochain démarrage, après le Go).
        if any(m.statut == "en_cours" and m.phase != "go" for m in chef.etat().modules):
            chef.pause()
        chef.arreter()
        arret.set()
        arret_bilans.set()
        for fil in [*fils, fil_bilans]:
            fil.join()
        for liaison in liaisons.values():
            liaison.arreter()
        if materiel is not None:
            materiel.fermer()
        registre.fermer()
        marche.noter_arret(raison_arret[0])
    if raison_arret[0] == RAISON_ARRET:
        journal.warning("Extinction du Pi : %s", " ".join(fiabilite.onduleur.commande_arret))
        try:
            raccords.lancer(fiabilite.onduleur.commande_arret)
        except Exception as erreur:
            journal.error("Extinction du Pi impossible : %s", erreur)
    return CODE_OK


def main() -> None:
    """Point d'entrée de la commande « vidange » (lancée par systemd)."""
    try:
        code = principal()
    except Exception:
        # Plantage imprévu : on le note en entier, systemd relance le programme.
        journal.exception("Plantage imprévu du programme")
        code = CODE_PLANTAGE
    sys.exit(code)
