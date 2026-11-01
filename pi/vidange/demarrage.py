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
from vidange.api import ServeurApi, Services, constats_api, creer_app
from vidange.cameras import Cameras, Flux
from vidange.chef import Carnet, Chef, ErreurChef, Module
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
from vidange.pesees.tour import TourPesees
from vidange.pesees.verification import cartes_de_pesee, verifier_avec_liste
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
    if erreurs_pesees:
        journal.error(
            "Réglages des pesées qui ne vont pas ensemble :\n%s",
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
            "machine.yaml, poste_fut → pesee : zéro, pente et tare d'EXEMPLE : étalonner la "
            "pesée (pi/systeme/essai-poste-fut.md), puis passer « exemple » à false."
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
    camera_dosage = reglages.machine.camera_dosage
    if camera_dosage is not None and camera_dosage.exemple:
        journal.warning(
            "machine.yaml, camera_dosage : temps de pivot, impulsions et sortie PWM d'EXEMPLE : "
            "les régler aux essais (pi/systeme/essai-vision.md), puis passer « exemple » à false."
        )
    if reglages.vision.exemple:
        journal.warning(
            "vision.yaml contient des valeurs d'EXEMPLE (exemple: true) : positions des caméras, "
            "mire, repères ; les régler aux essais (pi/systeme/essai-vision.md), puis passer "
            "« exemple » à false."
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
    # Le poste du fût lit ses signaux en fond. Sans entrées/sorties ouvertes : pas de poste.
    poste: PosteFut | None = None
    if poste_reglages is not None and materiel is not None and erreur_materiel is None:
        poste = PosteFut(poste_reglages, materiel, registre)
    # Les cartes de pesée du bus RS485, interrogées en fond (griffe, préhension, plateau).
    pesees: TourPesees | None = None
    if materiel is not None and erreur_materiel is None and cartes_de_pesee(entrees_sorties):
        pesees = TourPesees(reglages.pesees, materiel)
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
    cameras = Cameras(reglages.programme.cameras, dossier_donnees, raccords.cameras)
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
    mode = ModeMachine(dossier_donnees / NOM_MODE, chef, registre)
    liaison_ecran = preparer_ecran(reglages, entrees_sorties, raccords.ecran)
    # L'écran s'arrête en premier, comme l'API : plus d'ordre pendant l'arrêt.
    arret_ecran = threading.Event()
    fil_ecran: threading.Thread | None = None
    try:
        for liaison in liaisons.values():
            liaison.demarrer()
        _, erreur_reprise = preparer_chef(chef, module_lieu_sur(reglages.machine, liaisons))
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
                "API": lambda: constats_api(serveur),
                "écran": lambda: constats_ecran(liaison_ecran),
                "envois": facteur.constats,
                "caméras": cameras.constats,
                "accéléromètre": lambda: constats_accelerometre(accelerometre),
                "pesées": lambda: constats_pesees(pesees),
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
