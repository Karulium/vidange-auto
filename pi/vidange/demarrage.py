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
6. Construit les cartes du chariot et de la tête qui sont là (vidange.cycle.machine : chariot,
   boîtier du chariot, tête du micropore, bras de la fermeture, tête de la Préhension, Lavage,
   carte du spray ; présence regardée une fois, rien n'est commandé), puis met en route le chef
   d'orchestre : prépare le mode seaux, le mode bocaux et la nuit UV-ozone
   (vidange.cycle : chaque poste est prêt, ou la check-list et l'écran disent pourquoi pas),
   reprend le cycle noté dans le carnet (après une coupure, le lot de seaux ou de bocaux en cours
   compris ; une nuit UV-ozone reprend générateur coupé, jamais relancé seul), et propose le
   retour en lieu sûr (il attend le Go de Karulium). Un lot se lance depuis la page web (le Pi
   propose) puis Go à l'écran de l'armoire (vidange.cycle.lancement) ; les boucles de fond de ses
   pièces partent avec lui.
7. Lance la surveillance : santé du Pi, onduleur, chien de garde (et dit à systemd « prêt »),
   bilan de chaque alarme. Écrit la check-list de démarrage au journal.
   Lance l'API et la page web, si le fichier de secrets donne une clé (sinon la machine
   tourne quand même, et la check-list le signale), et l'écran de l'armoire. Lance la file
   d'envoi (cycles vers le logiciel de culture, copies vers la maison), les caméras (vidéo en
   direct, clip à chaque alarme), le pilotage à distance (qui attend qu'on l'active) et la
   liaison avec l'accéléromètre (chocs notés au registre).
   Prépare les mises à jour (cartes ESP32 et programme du Pi), lancées depuis la page web.
8. Attend l'ordre d'arrêt, puis arrête tout proprement (machine en pause, état noté). Si l'ordre
   vient de l'onduleur, éteint le Pi à la fin. Après une mise à jour du programme du Pi, sort
   avec le code CODE_REDEMARRER : systemd relance aussitôt le nouveau programme.

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
from vidange.accelerometre.chargeur import ChargeurAccelerometre
from vidange.accelerometre.liaison import SIGNAL as SIGNAL_ACCELEROMETRE
from vidange.accelerometre.liaison import LiaisonAccelerometre, PortAccelerometre
from vidange.accelerometre.liaison import ouvrir_port as ouvrir_port_accelerometre
from vidange.air import Air
from vidange.angles_gardes import AnglesGardes
from vidange.api import ServeurApi, Services, constats_api, creer_app
from vidange.cameras import Cameras, Flux
from vidange.chef import Carnet, Chef, ErreurChef, Module
from vidange.cycle import Lancement, ModeBocaux, ModeNuit, ModeSeaux
from vidange.cycle.machine import (
    FondDuLot,
    PiecesMachine,
    Sources,
    construire_cartes,
    presence_fluidnc,
    stockage_de_la_machine,
)
from vidange.cycle.mode_bocaux import ENTONNOIR
from vidange.cycle.mode_seaux import MYCELIUM, REMPLISSAGE
from vidange.cycle.postes import refus_lancement
from vidange.distance import PiloteDistance
from vidange.ecran import SIGNAL as SIGNAL_ECRAN
from vidange.ecran import Ecran, LiaisonEcran, PortEcran, ouvrir_port_ecran
from vidange.entrees_sorties import EntreesSorties, charger_entrees_sorties
from vidange.envois import mettre_en_file_secours, preparer_facteur
from vidange.fiabilite import (
    Bilans,
    CheckList,
    ChienDeGarde,
    FinPrecedente,
    Marche,
    ObjetTenu,
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
from vidange.fiabilite.constats import Constat
from vidange.fiabilite.lieu_sur import NOM as NOM_LIEU_SUR
from vidange.fiabilite.onduleur import RAISON_ARRET
from vidange.fiabilite.onduleur import SIGNAL as SIGNAL_ONDULEUR
from vidange.fichier_secrets import Secrets, charger_secrets
from vidange.fluidnc import Liaison
from vidange.fluidnc.ports import Port
from vidange.journal import NOM_FICHIER, configurer_journal, donner_journal
from vidange.materiel import Materiel
from vidange.materiel.materiel import Fabrique
from vidange.mises_a_jour import DOSSIER as DOSSIER_MISES_A_JOUR
from vidange.mises_a_jour import CarteEsp32, MisesAJour, ProgrammePi, preparer_cartes
from vidange.mode import ModeMachine
from vidange.nettoyage import Nettoyage
from vidange.nettoyage.capteurs import capteurs_du_materiel
from vidange.nettoyage.capteurs import verifier_avec_liste as verifier_nettoyage
from vidange.pesees.tour import TourPesees
from vidange.pesees.verification import pesees_du_bus, verifier_avec_liste
from vidange.poste_fut import PosteFut
from vidange.quoi_faire import COUPURE_COURANT, PLANTAGE
from vidange.registre import (
    DOSSIER_SAUVEGARDES,
    ErreurRegistre,
    Registre,
    SauvegardeQuotidienne,
    ouvrir_registre,
)
from vidange.reglages import ErreurReglages, Reglages, charger_reglages
from vidange.spray.spray import PORTE as PORTE_SPRAY
from vidange.spray.spray import Spray
from vidange.spray.spray import verifier_avec_liste as verifier_spray
from vidange.stockage.correction import Correction
from vidange.vision.photo import Photographe

# Codes de sortie. Le service systemd (pi/systeme/vidange.service) utilise CODE_REGLAGES_FAUX.
CODE_OK = 0
CODE_PLANTAGE = 1
CODE_REGLAGES_FAUX = 2
CODE_REGISTRE_ABIME = 3
# Programme du Pi mis à jour : systemd relance (RestartForceExitStatus dans vidange.service).
CODE_REDEMARRER = 4
RAISON_MISE_A_JOUR = "mise à jour du programme du Pi"

DOSSIER_PI = Path(__file__).resolve().parent.parent
NOM_CARNET = "etat-cycle.json"
NOM_MODE = "mode.json"
# Angles gardés au redémarrage (rotations de la griffe et de la tête de préhension).
NOM_ANGLES = "angles.json"
# La nuit UV-ozone en cours (reprise après une coupure de courant).
NOM_NETTOYAGE = "nettoyage.json"
NOM_SPRAY = "spray.json"
NOM_AIR = "air.json"
# Le compte-tours de la tête de préhension (docs/entrees-sorties.yaml).
SIGNAL_COMPTE_TOURS = "compte_tours_tete"
# Le capteur de vide de la ventouse de la préhension (reprise avec un objet tenu, tâche 45 nonies).
SIGNAL_VIDE = "vide_venturi"

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
    # Ouverture du port de l'écran ; None : l'UART du signal « ecran_nextion ».
    ecran: Callable[[], PortEcran] | None = None
    # Ouverture du fil de l'accéléromètre ; None : l'UART du signal « accelerometre_fil ».
    accelerometre: Callable[[], PortAccelerometre] | None = None
    # Nom de caméra → ouverture de sa vidéo ; None : les commandes de programme.yaml.
    cameras: Mapping[str, Callable[[], Flux]] | None = None
    notifier: Callable[[str], bool] = notifier_systemd
    # Lance une commande du système (extinction du Pi par l'onduleur).
    lancer: Callable[[list[str]], object] = lancer_commande
    # Cartes ESP32 à mettre à jour ; None : les vraies cartes de fluidnc.yaml.
    cartes_maj: Mapping[str, CarteEsp32] | None = None
    # Programme du Pi à mettre à jour ; None : la copie Git où tourne ce programme.
    programme_pi: ProgrammePi | None = None


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


def preparer_chef(
    chef: Chef,
    lieu_sur: Module | None,
    mode_seaux: ModeSeaux | None = None,
    carnet: Carnet | None = None,
    mode_bocaux: ModeBocaux | None = None,
) -> tuple[list[str], str | None]:
    """Reprend le cycle du carnet ; propose le retour en lieu sûr (exclusif, attend le Go).

    Rend les modules repris et l'erreur de reprise (carnet qui ne correspond pas au programme).
    Le programme connaît « lieu_sur » et les modules du lot de seaux noté dans le carnet (mode
    seaux, reconstruits avec la mémoire du lot : seau en cours, couche) et du lot de bocaux (mode
    bocaux : bocal où est l'entonnoir, bocaux restants et versés). La nuit UV-ozone n'est pas un
    module du chef : le Nettoyage la reprend seul (générateur coupé, jamais relancé).
    """
    modules = [module for module in (lieu_sur,) if module is not None]
    try:
        if mode_seaux is not None and carnet is not None:
            modules += mode_seaux.modules_a_reprendre(carnet.lire())
        if mode_bocaux is not None and carnet is not None:
            modules += mode_bocaux.modules_a_reprendre(carnet.lire())
        repris = chef.reprendre_cycle(modules)
    except ErreurChef as erreur:
        journal.error("Reprise du cycle impossible : %s", erreur)
        return [], str(erreur)
    if lieu_sur is not None and lieu_sur.nom not in repris:
        chef.lancer(lieu_sur)
        journal.info("Retour en lieu sûr proposé : il attend le Go de Karulium.")
    return repris, None


def preparer_api(secrets: Secrets, reglages: Reglages, services: Services) -> ServeurApi | None:
    """Le serveur de l'API, ou None s'il n'y a pas de clé (l'API ne tourne jamais sans clé)."""
    if secrets.cle_api is None:
        journal.warning(
            "Pas de clé « cle_api » dans le fichier de secrets : l'API et la page web "
            "ne démarrent pas."
        )
        return None
    app = creer_app(services, reglages.programme.api, secrets.cle_api.get_secret_value())
    return ServeurApi(app, reglages.programme.api)


def constats_ecran(liaison: LiaisonEcran | None) -> list[Constat]:
    """Pour la check-list. Sans écran, la machine peut tourner : jamais bloquant."""
    if liaison is None:
        texte = f"pas de signal « {SIGNAL_ECRAN} » dans entrees-sorties.yaml"
        return [Constat("écran de l'armoire", "attention", texte)]
    return liaison.constats()


def preparer_ecran(
    reglages: Reglages, liste: EntreesSorties, ouvrir: Callable[[], PortEcran] | None
) -> LiaisonEcran | None:
    """La liaison avec l'écran, ou None si la liste des entrées/sorties n'en a pas."""
    if ouvrir is None:
        signal = liste.signaux.get(SIGNAL_ECRAN)
        if signal is None or signal.fichier is None:
            journal.warning(
                "Pas de signal « %s » (avec son « fichier ») dans entrees-sorties.yaml : "
                "pas d'écran de l'armoire.",
                SIGNAL_ECRAN,
            )
            return None
        ouvrir = ouvrir_port_ecran(signal.fichier, reglages.programme.ecran.vitesse_bauds)
    return LiaisonEcran(reglages.programme.ecran, ouvrir)


def constats_accelerometre(liaison: LiaisonAccelerometre | None) -> list[Constat]:
    """Pour la check-list. Jamais bloquant : la sortie « OK » va directement à l'ESP32 n° 1."""
    if liaison is None:
        texte = f"pas de signal « {SIGNAL_ACCELEROMETRE} » dans entrees-sorties.yaml"
        return [Constat("accéléromètre", "attention", texte)]
    return liaison.constats()


def constats_pesees(pesees: TourPesees | None) -> list[Constat]:
    """Pour la check-list. Jamais bloquant : chaque module refuse de bouger sans sa pesée."""
    if pesees is None:
        texte = "bus des pesées pas ouvert (entrées/sorties en panne, ou aucune carte de pesée)"
        return [Constat("pesées", "attention", texte)]
    return pesees.constats()


def cycle_tourne(chef: Chef) -> bool:
    """Un module est en plein travail : pas en pause, ni en attente du Go (pour le Nettoyage)."""
    etat = chef.etat()
    return not etat.en_pause and any(
        module.statut == "en_cours" and module.phase != "go" for module in etat.modules
    )


def preparer_nettoyage(
    reglages: Reglages,
    materiel: Materiel | None,
    dossier_donnees: Path,
    registre: Registre,
    chef: Chef,
    mode: ModeMachine,
) -> Nettoyage | None:
    """Le Nettoyage, branché au chef (gestes interdits pendant la purge, rien ne commence store
    ouvert) et au mode (pas de changement de mode en pleine nuit UV-ozone). Capteurs de
    particules, de pression et consigne 0-10 V : ceux de la liste des entrées/sorties (SPS30,
    SDP810, module PWM) ; un absent de la liste reste « absent » pour le Nettoyage."""
    if reglages.machine.nettoyage is None or materiel is None:
        return None
    dedans, dehors, pression, consigne = capteurs_du_materiel(materiel)
    nettoyage = Nettoyage(
        reglages.machine.nettoyage,
        materiel,
        dossier_donnees / NOM_NETTOYAGE,
        registre,
        mode=lambda: mode.actuel,
        cycle_tourne=lambda: cycle_tourne(chef),
        pause=chef.pause,
        particules_dedans=dedans,
        particules_dehors=dehors,
        pression=pression,
        consigne=consigne,
    )
    chef.interdire(nettoyage.refus_geste)
    chef.conditions_generales.append(nettoyage.condition_store)
    mode.refus_supplementaires.append(nettoyage.refus_changement_mode)
    return nettoyage


def preparer_objet_tenu(
    reglages: Reglages,
    materiel: Materiel | None,
    liste: EntreesSorties,
    vraie_machine: bool,
) -> ObjetTenu | None:
    """La reprise avec un objet encore tenu à la ventouse (tâche 45 nonies) : le capteur de vide
    de la préhension, lu sans rien commander. None : pas de préhension dans machine.yaml."""
    prehension = reglages.machine.prehension
    if prehension is None:
        return None
    periode = reglages.programme.fiabilite.objet_tenu.periode_s
    signal = liste.signaux.get(SIGNAL_VIDE)
    absent = None
    if materiel is None:
        absent = "entrées/sorties pas ouvertes : capteur de vide pas lu"
    elif signal is None or SIGNAL_VIDE not in materiel.branchements:
        absent = f"capteur de vide « {SIGNAL_VIDE} » absent de docs/entrees-sorties.yaml"
    elif vraie_machine and any(
        ligne is not None and ligne.exemple for ligne in (signal, liste.cartes.get(signal.carte))
    ):
        absent = f"capteur de vide « {SIGNAL_VIDE} » en EXEMPLE dans docs/entrees-sorties.yaml"
    if absent is not None:
        journal.warning("Reprise : %s ; vérifier la tête de préhension à la main.", absent)
        return ObjetTenu(prehension.vide, None, periode, absent=absent)
    assert materiel is not None
    return ObjetTenu(prehension.vide, lambda: materiel.mesurer(SIGNAL_VIDE), periode)


def constats_objet_tenu(objet_tenu: ObjetTenu | None) -> list[Constat]:
    return [] if objet_tenu is None else objet_tenu.constats()


def preparer_air(
    reglages: Reglages,
    materiel: Materiel | None,
    dossier_donnees: Path,
    chef: Chef,
    nettoyage: Nettoyage | None,
) -> Air | None:
    """L'Air comprimé : le relais du compresseur (fermé sauf nuit UV-ozone), l'attente de mise en
    pression avant les gestes qui consomment de l'air, le rappel du bidon de purge."""
    if materiel is None or "relais_compresseur" not in materiel.branchements:
        return None
    air = Air(
        reglages.air,
        materiel,
        dossier_donnees / NOM_AIR,
        air_permis=(lambda: True) if nettoyage is None else (lambda: nettoyage.air_permis),
    )
    chef.interdire(air.refus_geste)
    return air


def constats_air(air: Air | None) -> list[Constat]:
    if air is None:
        return [Constat("air comprimé", "attention", "Air pas lancé (relais absent de la liste ?)")]
    return air.constats()


def preparer_spray(
    reglages: Reglages,
    materiel: Materiel | None,
    dossier_donnees: Path,
    registre: Registre,
    chef: Chef,
) -> Spray | None:
    """Le Spray en fond (lecture de la carte n° 5, battement, agitateurs). Ses gestes (un seau,
    nettoyage des tubes) sont des modules du chef : vidange.spray.module."""
    machine = reglages.machine
    if machine.spray is None or materiel is None:
        return None
    if machine.spray.signal not in materiel.branchements:
        return None
    porte = (lambda: materiel.lire(PORTE_SPRAY)) if PORTE_SPRAY in materiel.branchements else None
    return Spray(
        machine,
        materiel,
        registre,
        dossier_donnees / NOM_SPRAY,
        porte_ouverte=porte if porte is not None else (lambda: None),
        permission=chef.permission,
    )


def constats_spray(spray: Spray | None) -> list[Constat]:
    if spray is None:
        return [Constat("spray", "attention", "Spray pas lancé (carte absente de la liste ?)")]
    return spray.constats()


def constats_nettoyage(nettoyage: Nettoyage | None) -> list[Constat]:
    if nettoyage is None:
        return [Constat("enceinte", "attention", "Nettoyage pas lancé (entrées/sorties en panne)")]
    return nettoyage.constats()


def preparer_accelerometre(
    reglages: Reglages,
    liste: EntreesSorties,
    ouvrir: Callable[[], PortAccelerometre] | None,
    registre: Registre,
) -> LiaisonAccelerometre | None:
    """La liaison avec l'accéléromètre, ou None si la liste des entrées/sorties n'en a pas."""
    if ouvrir is None:
        signal = liste.signaux.get(SIGNAL_ACCELEROMETRE)
        if signal is None or signal.fichier is None:
            journal.warning(
                "Pas de signal « %s » (avec son « fichier ») dans entrees-sorties.yaml : "
                "les chocs ne sont pas notés au registre.",
                SIGNAL_ACCELEROMETRE,
            )
            return None
        ouvrir = ouvrir_port_accelerometre(
            signal.fichier, reglages.accelerometre.liaison.vitesse_bauds
        )
    return LiaisonAccelerometre(reglages.accelerometre, ouvrir, registre)


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
        secrets = charger_secrets(chemin_secrets)
    except ErreurReglages as erreur:
        journal.error("%s", erreur)
        return CODE_REGLAGES_FAUX
    erreurs_pesees = verifier_avec_liste(reglages.pesees, entrees_sorties)
    if reglages.machine.nettoyage is not None:
        erreurs_pesees += verifier_nettoyage(reglages.machine.nettoyage, entrees_sorties)
    if reglages.machine.spray is not None:
        erreurs_pesees += verifier_spray(reglages.machine.spray, entrees_sorties)
    if erreurs_pesees:
        journal.error(
            "Réglages qui ne vont pas ensemble (pesées, ventilateur, spray) :\n%s",
            "\n".join(f"  - {erreur}" for erreur in erreurs_pesees),
        )
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
    if reglages.programme.cameras.exemple:
        journal.warning(
            "programme.yaml : les commandes des caméras sont des EXEMPLES (cameras → exemple) : "
            "les vérifier sur le vrai Pi (pi/systeme/essai-distance.md)."
        )
    if reglages.accelerometre.exemple:
        journal.warning(
            "accelerometre.yaml contient des valeurs d'EXEMPLE (exemple: true) : carte, broches "
            "et seuil de choc à choisir à l'essai (accelerometre/essai-etabli.md)."
        )
    if reglages.pesees.exemple:
        journal.warning(
            "pesees.yaml contient des valeurs d'EXEMPLE (exemple: true) : carte, broches et "
            "étalonnage des cartes de pesée à faire à l'essai (pesee/essai-etabli.md)."
        )
    poste_reglages = reglages.machine.poste_fut
    if poste_reglages is not None and poste_reglages.pesee.exemple:
        journal.warning(
            "machine.yaml, poste_fut → pesee : tare et bornes d'EXEMPLE : étalonner la pesée du "
            "plateau (pi/systeme/essai-poste-fut.md), puis passer « exemple » à false."
        )
    griffe = reglages.machine.griffe
    if griffe is not None and griffe.exemple:
        journal.warning(
            "machine.yaml, griffe : formats des seaux, vitesses, doses et seuils d'EXEMPLE : "
            "les régler aux essais (pi/systeme/essai-griffe.md), puis passer « exemple » à false."
        )
    mycelium = reglages.machine.mycelium
    if mycelium is not None and mycelium.exemple:
        journal.warning(
            "machine.yaml, mycelium : vitesses, dose, pesée et course de l'agitation d'EXEMPLE : "
            "les régler aux essais (pi/systeme/essai-mycelium.md), puis passer « exemple » à false."
        )
    porte_bocal = reglages.machine.porte_bocal
    if porte_bocal is not None and porte_bocal.exemple:
        journal.warning(
            "machine.yaml, porte_bocal : tolérance, palpage et durées du demi-tour d'EXEMPLE : "
            "les régler aux essais (pi/systeme/essai-porte-bocal.md), puis passer « exemple » à "
            "false."
        )
    prehension = reglages.machine.prehension
    if prehension is not None and prehension.exemple:
        journal.warning(
            "machine.yaml, prehension : vitesses, poids estimés, encombrement des objets et "
            "porte-bocal d'EXEMPLE : les régler aux essais (pi/systeme/essai-prehension.md), puis "
            "passer « exemple » à false."
        )
    lavage = reglages.machine.lavage
    if lavage is not None and lavage.exemple:
        journal.warning(
            "machine.yaml, lavage : hauteurs, décalages, vitesses des brosses, durées d'EXEMPLE : "
            "les régler aux essais (pi/systeme/essai-lavage.md), puis passer « exemple » à false."
        )
    remplissage = reglages.machine.remplissage
    if remplissage is not None and remplissage.exemple:
        journal.warning(
            "machine.yaml, remplissage : vitesses, files, hauteurs de pose, décalage des barres "
            "d'EXEMPLE : les régler aux essais (pi/systeme/essai-remplissage.md), puis passer "
            "« exemple » à false."
        )
    stockage = reglages.machine.stockage
    if stockage is not None and stockage.exemple:
        journal.warning(
            "machine.yaml, stockage : seaux B par file du tiroir, places de la bande du haut, "
            "bord de la 1re pile de fin de lot d'EXEMPLE : les vérifier aux essais "
            "(pi/systeme/essai-stockage.md), puis passer « exemple » à false."
        )
    nettoyage_reglages = reglages.machine.nettoyage
    if nettoyage_reglages is not None and nettoyage_reglages.exemple:
        journal.warning(
            "machine.yaml, nettoyage : temps du store, niveaux du ventilateur, durées de la nuit "
            "UV-ozone d'EXEMPLE : les régler aux essais (pi/systeme/essai-nettoyage.md), puis "
            "passer « exemple » à false."
        )
    spray_reglages = reglages.machine.spray
    if spray_reglages is not None and spray_reglages.exemple:
        journal.warning(
            "machine.yaml, spray : vitesse du bras, doses, durées, tares des flacons et "
            "agitateurs d'EXEMPLE : les régler aux essais (pi/systeme/essai-spray.md), puis "
            "passer « exemple » à false."
        )
    micropore = reglages.machine.micropore
    if micropore is not None and micropore.exemple:
        journal.warning(
            "machine.yaml, micropore : rangées des seaux, chiffres du capteur de distance et des "
            "servos, moteur d'avance d'EXEMPLE : les régler aux essais "
            "(pi/systeme/essai-micropore.md), puis passer « exemple » à false."
        )
    fermeture = reglages.machine.fermeture
    if fermeture is not None and fermeture.exemple:
        journal.warning(
            "machine.yaml, fermeture : étalonnage du servo du bras, Hf et Hc, efforts, rotation, "
            "rampe et position du chariot d'EXEMPLE : les régler au premier essai sur les 4 vrais "
            "seaux (pi/systeme/essai-fermeture.md), puis passer « exemple » à false."
        )
    entonnoir = reglages.machine.entonnoir
    if entonnoir is not None and entonnoir.exemple:
        journal.warning(
            "machine.yaml, entonnoir : hauteurs de l'oreille, de la pointe et du cône, seuils de "
            "contrôle, du vide et délais d'EXEMPLE : les mesurer sur l'entonnoir reçu "
            "(pi/systeme/essai-entonnoir.md), puis passer « exemple » à false."
        )
    versement = None if griffe is None else griffe.versement_bocal
    if versement is not None and versement.exemples():
        journal.warning(
            "machine.yaml, griffe → versement_bocal : %s en EXEMPLE (proposés ou à mesurer) : "
            "les régler au premier essai avec du maïs chaud (pi/systeme/essai-versement-bocal.md), "
            "puis passer leur « exemple » à false.",
            ", ".join(versement.exemples()),
        )
    couvercle = reglages.machine.couvercle
    if couvercle is not None and couvercle.exemple:
        journal.warning(
            "machine.yaml, couvercle : masses des couvercles, tolérance, haut de la pile, "
            "fenêtre du contact, durées du vide et vitesses d'EXEMPLE : les mesurer sur les vrais "
            "couvercles et seaux (pi/systeme/essai-couvercle.md), puis passer « exemple » à false."
        )
    camera_dosage = reglages.machine.camera_dosage
    if camera_dosage is not None and camera_dosage.exemple:
        journal.warning(
            "machine.yaml, camera_dosage : temps de pivot, impulsions et sortie PWM d'EXEMPLE : "
            "les régler aux essais (pi/systeme/essai-vision.md), puis passer « exemple » à false."
        )
    solveur = reglages.machine.solveur
    if solveur is not None and solveur.exemple:
        journal.warning(
            "machine.yaml, solveur : temps de calcul, pas et écart d'EXEMPLE (%s) : les régler "
            "après les premiers lots, puis passer « exemple » à false.",
            "actif" if solveur.actif else "pas actif : ordre normal du chef",
        )
    if reglages.vision.exemple:
        journal.warning(
            "vision.yaml contient des valeurs d'EXEMPLE (exemple: true) : positions des caméras, "
            "mire, repères ; les régler aux essais (pi/systeme/essai-vision.md), puis passer "
            "« exemple » à false."
        )
    if reglages.vision.inspection is not None and reglages.vision.inspection.exemple:
        journal.warning(
            "vision.yaml, inspection : caméra du micropore (QR du flanc, trous, morceaux) en "
            "valeurs d'EXEMPLE ; les régler aux essais (pi/systeme/essai-inspection.md), puis "
            "passer « inspection → exemple » à false."
        )
    if reglages.air.exemple:
        journal.warning(
            "air.yaml contient des valeurs d'EXEMPLE (exemple: true) : attente de mise en "
            "pression et rappel du bidon ; les mesurer à l'essai (pi/systeme/essai-air.md), "
            "puis passer « exemple » à false."
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
    envois = reglages.programme.envois
    jeton = secrets.jeton_culture
    facteur = preparer_facteur(
        registre, envois, jeton.get_secret_value() if jeton else None, dossier_donnees
    )
    sauvegarde = SauvegardeQuotidienne(
        registre,
        dossier_donnees / DOSSIER_SAUVEGARDES,
        reglages.programme.registre,
        apres_copie=mettre_en_file_secours(registre, envois.secours, dossier_donnees),
    )
    fils = [sauvegarde.demarrer(arret), facteur.demarrer(arret)]
    materiel, erreur_materiel = ouvrir_materiel(entrees_sorties, raccords.fabrique)
    ports = raccords.ports or {}
    liaisons = {
        nom: Liaison(nom, reglages.fluidnc, ouvrir=ports.get(nom))
        for nom in reglages.fluidnc.cartes
    }
    fiabilite = reglages.programme.fiabilite
    chef = Chef(reglages.machine, reglages.programme.chef, carnet)
    # Les pesées du bus RS485, interrogées en fond (griffe, préhension, plateau du remplissage,
    # boîte du poste du fût).
    pesees: TourPesees | None = None
    if materiel is not None and erreur_materiel is None and pesees_du_bus(entrees_sorties):
        pesees = TourPesees(reglages.pesees, materiel)
    # Le poste du fût lit ses signaux en fond. Sans entrées/sorties ouvertes : pas de poste.
    poste: PosteFut | None = None
    if poste_reglages is not None and materiel is not None and erreur_materiel is None:
        poste = PosteFut(poste_reglages, materiel, registre, pesees=pesees)
    spray = preparer_spray(
        reglages, materiel if erreur_materiel is None else None, dossier_donnees, registre, chef
    )
    mode = ModeMachine(dossier_donnees / NOM_MODE, chef, registre)
    cameras = Cameras(reglages.programme.cameras, dossier_donnees, raccords.cameras)
    # Les angles gardés (rotations de la griffe et de la tête) : un seul fichier, un seul gardien.
    angles = AnglesGardes(dossier_donnees / NOM_ANGLES)
    vraie_machine = raccords.fabrique is None
    # Reprise après une coupure (tâche 45 nonies) : AVANT tout mouvement, la ventouse tient-elle
    # encore quelque chose ? Tant que oui, aucun Go (rien n'est commandé : jamais de « souffler »).
    objet_tenu = preparer_objet_tenu(
        reglages, materiel if erreur_materiel is None else None, entrees_sorties, vraie_machine
    )
    if objet_tenu is not None:
        objet_tenu.regarder()
        chef.empecher_go(objet_tenu.refus_go)
    # Les cartes du chariot et de la tête (tâche 45 ter) : construites si elles sont là (présence
    # regardée maintenant, une fois), sinon chaque poste qui en a besoin dit pourquoi.
    cartes = construire_cartes(
        reglages,
        materiel if erreur_materiel is None else None,
        liaisons,
        pesees,
        poste,
        vraie_machine,
        presence_fluidnc(reglages.fluidnc, raccords.ports),
        mode=lambda: mode.actuel,
        donnees=dossier_donnees,
        garde=angles,
    )
    # Un seul Stockage pour tout le programme (inventaire repris du registre : piles, bocaux de
    # semence, boîtes à capsules), et ce qui n'est pas encore écrit (Sources : rien sur la
    # machine ; chaque poste qui en a besoin dit pourquoi il n'est pas lancé).
    stockage = stockage_de_la_machine(
        reglages.machine, materiel if erreur_materiel is None else None, registre
    )
    sources = Sources()
    # Le mode seaux : chaque poste du cycle d'un seau, prêt ou pourquoi pas (vrai matériel :
    # réglages d'EXEMPLE interdits). Un lot de seaux ne part qu'en mode « production ».
    mode_seaux = ModeSeaux(
        reglages,
        PiecesMachine(
            poste,
            materiel if erreur_materiel is None else None,
            vraie_machine=vraie_machine,
            spray=spray,
            vision=reglages.vision,
            regard=Photographe(cameras, reglages.vision, registre),
            donnees=dossier_donnees,
            cartes=cartes,
            machine=reglages.machine,
            registre=registre,
            permission=chef.permission,
            stockage=stockage,
            sources=sources,
        ),
        chef,
        mode_actuel=lambda: mode.actuel,
    )
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
    # Le clip des dernières secondes de chaque caméra, dans le bilan de chaque alarme.
    bilans.collecteurs["clip_video"] = lambda: cameras.garder_clip("alarme")
    pilote = PiloteDistance(
        reglages.programme.distance,
        reglages.machine,
        liaisons,
        chef,
        materiel,
        cameras.age,
        registre,
    )
    onduleur = Onduleur(fiabilite.onduleur, materiel, chef, demander_arret)
    gardien = ChienDeGarde(
        fiabilite.chien_de_garde, liaisons, chef, materiel, notifier=raccords.notifier
    )
    dossier_maj = dossier_donnees / DOSSIER_MISES_A_JOUR
    cartes_maj = raccords.cartes_maj
    if cartes_maj is None:
        cartes_maj = preparer_cartes(reglages, dossier_maj)
    programme_pi = raccords.programme_pi
    if programme_pi is None:
        jeton_github = secrets.jeton_github
        programme_pi = ProgrammePi(
            reglages.programme.mises_a_jour.pi,
            DOSSIER_PI.parent,
            dossier_maj,
            jeton_github.get_secret_value() if jeton_github else None,
        )
    accelerometre = preparer_accelerometre(
        reglages, entrees_sorties, raccords.accelerometre, registre
    )
    mises_a_jour = MisesAJour(
        reglages.programme.mises_a_jour,
        dossier_maj,
        cartes_maj,
        programme_pi,
        chef,
        liaisons,
        DOSSIER_PI.parent / "fluidnc",
        registre,
        pilote,
        redemarrer=lambda: demander_arret(RAISON_MISE_A_JOUR),
        accelerometre=None
        if accelerometre is None
        else ChargeurAccelerometre(reglages.accelerometre, accelerometre.ouvrir),
        liaison_accelerometre=accelerometre,
    )
    # Le fil des bilans s'arrête après le chef : il finit les bilans des dernières alarmes.
    arret_bilans = threading.Event()
    fil_bilans = bilans.demarrer(arret_bilans)
    serveur: ServeurApi | None = None
    nettoyage = preparer_nettoyage(
        reglages,
        materiel if erreur_materiel is None else None,
        dossier_donnees,
        registre,
        chef,
        mode,
    )
    air = preparer_air(
        reglages, materiel if erreur_materiel is None else None, dossier_donnees, chef, nettoyage
    )
    # Mode bocaux et nuit UV-ozone (tâche 45 bis) : mêmes pièces, même règle « prêt, ou pas lancé
    # et pourquoi ». La nuit refuse de partir si son poste n'est pas prêt (Nettoyage.refus_nuit).
    pieces_bocaux = PiecesMachine(
        poste,
        materiel if erreur_materiel is None else None,
        vraie_machine=vraie_machine,
        spray=spray,
        nettoyage=nettoyage,
        vision=reglages.vision,
        donnees=dossier_donnees,
        cartes=cartes,
        machine=reglages.machine,
        registre=registre,
        permission=chef.permission,
        stockage=stockage,
        sources=sources,
    )
    mode_bocaux = ModeBocaux(reglages, pieces_bocaux, chef, mode_actuel=lambda: mode.actuel)
    mode_nuit = ModeNuit(reglages, pieces_bocaux, nettoyage)
    # Lancer un lot (tâche 45 quater) : la page web propose, Go à l'écran de l'armoire. Les
    # boucles de fond des pièces partent avec le lot et s'arrêtent à sa fin ou sur alarme.
    fond = FondDuLot(cartes, reglages.programme.lot, chef)
    lancement = Lancement(
        reglages.programme.lot, reglages.machine, mode_seaux, mode_bocaux, stockage, fond
    )
    # Corriger l'inventaire du stockage depuis la page web (tâche 45 quinquies) : refusé pendant
    # un lot, confirmé par Karulium sur la page.
    correction = (
        None
        if stockage is None
        else Correction(
            stockage,
            reglages.programme.lot.proposition_max_s,
            lambda: refus_lancement(chef, None, "", "un lot tourne"),
        )
    )
    liaison_ecran = preparer_ecran(reglages, entrees_sorties, raccords.ecran)
    # L'écran s'arrête en premier, comme l'API : plus d'ordre pendant l'arrêt.
    arret_ecran = threading.Event()
    fil_ecran: threading.Thread | None = None
    try:
        for liaison in liaisons.values():
            liaison.demarrer()
        compte_tours = None
        if materiel is not None and SIGNAL_COMPTE_TOURS in entrees_sorties.signaux:
            # Une erreur de lecture est vue par le portique : il demande alors une confirmation.
            compte_tours = lambda: materiel.mesurer(SIGNAL_COMPTE_TOURS)  # noqa: E731
        repris, erreur_reprise = preparer_chef(
            chef,
            module_lieu_sur(
                reglages.machine,
                liaisons,
                reglages.fluidnc.cartes,
                garde=angles,
                compte_tours=compte_tours,
            ),
            mode_seaux,
            carnet,
            mode_bocaux,
        )
        du_lot = [nom for nom in repris if nom in (REMPLISSAGE, MYCELIUM, ENTONNOIR)]
        if du_lot:
            # Lot repris du carnet : ses boucles de fond partiront quand il repartira (Go).
            fond.reprendre(du_lot)
        chef.demarrer()
        cameras.demarrer()
        fils += [
            sante.demarrer(arret),
            onduleur.demarrer(arret),
            gardien.demarrer(arret),
            pilote.demarrer(arret),
        ]
        if accelerometre is not None:
            fils.append(accelerometre.demarrer(arret))
        if poste is not None:
            fils += poste.demarrer(arret)
        if pesees is not None:
            fils.append(pesees.demarrer(arret))
        if nettoyage is not None:
            fils += nettoyage.demarrer(arret)
        if spray is not None:
            fils += spray.demarrer(arret)
        if air is not None:
            fils += air.demarrer(arret)
        if objet_tenu is not None:
            fils.append(objet_tenu.demarrer(arret))
        checklist = CheckList(
            {
                "réglages": lambda: constats_reglages(reglages, entrees_sorties),
                "objet tenu": lambda: constats_objet_tenu(objet_tenu),
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
                "API": lambda: constats_api(serveur),
                "écran": lambda: constats_ecran(liaison_ecran),
                "envois": facteur.constats,
                "caméras": cameras.constats,
                "accéléromètre": lambda: constats_accelerometre(accelerometre),
                "pesées": lambda: constats_pesees(pesees),
                "enceinte": lambda: constats_nettoyage(nettoyage),
                "spray": lambda: constats_spray(spray),
                "air": lambda: constats_air(air),
                "cartes du chariot et de la tête": cartes.constats,
                "mode seaux": mode_seaux.constats,
                "mode bocaux": mode_bocaux.constats,
                "nuit UV-ozone": mode_nuit.constats,
            }
        )
        serveur = preparer_api(
            secrets,
            reglages,
            Services(
                chef,
                registre,
                bilans.acquitter,
                checklist.verifier,
                cameras=cameras,
                pilote=pilote,
                mises_a_jour=mises_a_jour,
                poste=poste,
                nettoyage=nettoyage,
                spray=spray,
                air=air,
                lancement=lancement,
                correction=correction,
            ),
        )
        if serveur is not None:
            serveur.demarrer()
        if liaison_ecran is not None:
            ecran = Ecran(
                reglages.programme.ecran,
                liaison_ecran,
                chef,
                registre,
                bilans.acquitter,
                mode,
                pilote=pilote,
                poste=poste,
                nettoyage=nettoyage,
                mode_seaux=mode_seaux,
                mode_bocaux=mode_bocaux,
                mode_nuit=mode_nuit,
                lancement=lancement,
            )
            fil_ecran = ecran.demarrer(arret_ecran)
        gardien.pret()
        journal.info(
            "Programme du Pi version %s démarré, réglages : %s", __version__, dossier_reglages
        )
        checklist.ecrire_au_journal(checklist.verifier())
        arret.wait()
        journal.info("Arrêt (%s) : arrêt propre.", raison_arret[0])
        if mises_a_jour.en_cours:
            journal.error(
                "Arrêt pendant une mise à jour : vérifier la carte ensuite (page web, "
                "« Mises à jour »)."
            )
    finally:
        # Plus d'ordre de la page web ni de l'écran pendant l'arrêt.
        if serveur is not None:
            serveur.arreter()
        arret_ecran.set()
        if fil_ecran is not None:
            fil_ecran.join()
        # Plus de mouvement à distance, voyant éteint.
        pilote.arreter()
        gardien.arreter()
        # Un module en plein geste : les axes s'arrêtent sans perdre leur position, et l'état
        # est noté dans le carnet (reprise au prochain démarrage, après le Go).
        if any(m.statut == "en_cours" and m.phase != "go" for m in chef.etat().modules):
            chef.pause()
        chef.arreter()
        # Les boucles de fond du lot (balances, vide, battement des servos).
        fond.arreter()
        arret.set()
        arret_bilans.set()
        for fil in [*fils, fil_bilans]:
            fil.join()
        cameras.arreter()
        for liaison in liaisons.values():
            liaison.arreter()
        if materiel is not None:
            materiel.fermer()
        if liaison_ecran is not None:
            liaison_ecran.fermer()
        if accelerometre is not None:
            accelerometre.fermer()
        registre.fermer()
        marche.noter_arret(raison_arret[0])
    if raison_arret[0] == RAISON_ARRET:
        journal.warning("Extinction du Pi : %s", " ".join(fiabilite.onduleur.commande_arret))
        try:
            raccords.lancer(fiabilite.onduleur.commande_arret)
        except Exception as erreur:
            journal.error("Extinction du Pi impossible : %s", erreur)
    if raison_arret[0] == RAISON_MISE_A_JOUR:
        journal.warning("Redémarrage du programme (nouvelle version).")
        return CODE_REDEMARRER
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
