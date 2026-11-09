"""Remettre un Pi neuf en état depuis la copie de secours.

    vidange restaurer --depuis vidange@maison:sauvegardes-vidange/

Ce que la commande fait, dans l'ordre (le logiciel lui-même est déjà installé par
`pi/systeme/restaurer.sh`, qui lance cette commande à la fin) :
  1. refuse d'écraser un registre qui existe déjà (sauf `--ecraser`) ;
  2. va chercher la copie de secours (dossier local ou clé USB ; sinon rsync depuis la maison) ;
  3. remet le REGISTRE : la copie la plus récente dont la base est saine, montée à la version du
     programme ;
  4. remet les FICHIERS HORS GIT : petits fichiers des données (sauf l'état d'un cycle en cours,
     programme.yaml → registre → restauration_ignore) et comptes de la page web ;
  5. remet les PHOTOS ;
  6. prépare le fichier de SECRETS (modèle vide s'il n'existe pas : les secrets ne sont pas dans la
     copie de secours) ;
  7. donne les fichiers au compte du programme ;
  7 bis. remet les RÉGLAGES que le Pi avait changés par rapport à Git (tâche 25 bis), un par un :
     un fichier qui ne passe plus la vérification avec le code du jour est mis de côté ;
  8. VÉRIFIE : réglages (comme `vidange --verifier`), puis service lancé ;
  9. dit en français ce qui reste à faire à la main.

Les RÉGLAGES (pi/reglages, fluidnc/, entrees-sorties.yaml) sont dans Git : ils reviennent avec le
logiciel (`git clone`). Seuls ceux que le Pi avait CHANGÉS (vrais chiffres de la machine) sont dans
l'archive et remis par-dessus (étape 7 bis).

Rien ici ne touche à la machine : la restauration remplit des fichiers et lance le service, qui
propose le retour en lieu sûr et attend le Go à l'écran, comme après toute coupure.
"""

import os
import re
import shutil
import sqlite3
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from vidange.fichier_secrets import charger_secrets
from vidange.journal import donner_journal
from vidange.registre import DOSSIER_PHOTOS, NOM_BASE, ErreurRegistre, ouvrir_registre
from vidange.registre.fichiers_hors_git import (
    DOSSIER_DONNEES_DANS_ARCHIVE,
    DOSSIER_REGLAGES_DANS_ARCHIVE,
    NOM_COMPTES,
    chemin_de_reglage_sur,
    est_une_archive,
    reglages_changes,
)
from vidange.reglages import ErreurReglages, Reglages

journal = donner_journal("restauration")

_COPIE_REGISTRE = re.compile(r"^registre-\d{4}-\d{2}-\d{2}\.sqlite$")
_NOM_SIMPLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DOSSIER_MIS_DE_COTE = "reglages-mis-de-cote"
# Une archive de petits fichiers ne dépasse jamais ça (protection contre une archive piégée).
TAILLE_MAX_FICHIER = 50 * 1024 * 1024


class ErreurRestauration(Exception):
    """Une restauration impossible ; le message dit quoi faire."""


class Commandes(Protocol):
    """Lance une commande du système (rsync, systemctl...). Remplacée par un faux dans les tests."""

    def lancer(self, commande: list[str], delai_s: float) -> tuple[int, str]: ...


@dataclass
class Chemins:
    donnees: Path
    secrets: Path
    comptes: Path
    secrets_exemple: Path
    # Dossier du dépôt Git du logiciel (None : les réglages changés ne sont pas remis).
    depot: Path | None = None


@dataclass
class Bilan:
    """Ce qui a été fait, et ce qui reste à faire à la main."""

    fait: list[str] = field(default_factory=list)
    a_la_main: list[str] = field(default_factory=list)
    problemes: list[str] = field(default_factory=list)

    @property
    def reussi(self) -> bool:
        return not self.problemes


@dataclass
class Options:
    ecraser: bool = False
    avec_service: bool = True
    avec_photos: bool = True
    photos_seulement: bool = False
    delai_copie_s: float = 3600
    attente_service_s: float = 30


def _integre(base: Path) -> bool:
    try:
        connexion = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
        try:
            return connexion.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            connexion.close()
    except sqlite3.DatabaseError:
        return False


def source_par_defaut(reglages: Reglages) -> str | None:
    """Où la copie de secours est envoyée chaque jour (programme.yaml → envois → secours)."""
    commande = reglages.programme.envois.secours.commande
    return commande[-1] if commande else None


def recuperer(
    source: str, temporaire: Path, commandes: Commandes, delai_s: float
) -> tuple[Path, bool]:
    """Où lire la copie de secours, et si c'est un dossier provisoire à effacer ensuite.

    `source` avec « : » (machine:dossier) : rsync par SSH (Tailscale) dans `temporaire`.
    Sans « : » : un dossier de ce Pi (clé USB, disque monté, ou copie déjà rapportée par
    restaurer.sh), lu sur place sans le recopier."""
    if ":" in source:
        temporaire.mkdir(parents=True, exist_ok=True)
        origine = source if source.endswith("/") else source + "/"
        code, sortie = commandes.lancer(
            ["rsync", "-a", "--partial", origine, f"{temporaire}/"], delai_s
        )
        if code != 0:
            raise ErreurRestauration(
                f"rsync n'a pas pu aller chercher la copie « {source} » (code {code}) :\n"
                f"{sortie.strip()}\nVérifier Tailscale (« tailscale status »), la clé SSH du "
                "compte vidange (pi/systeme/essai-restauration.md, étape 3) et l'adresse."
            )
        return temporaire, True
    dossier = Path(source)
    if not dossier.is_dir():
        raise ErreurRestauration(f"« {source} » n'est pas un dossier de ce Pi.")
    return dossier, False


def restaurer_registre(copies: Path, donnees: Path, ecraser: bool, bilan: Bilan) -> None:
    candidates = sorted(
        (f for f in copies.rglob("*") if f.is_file() and _COPIE_REGISTRE.match(f.name)),
        key=lambda f: f.name,
        reverse=True,
    )
    if not candidates:
        raise ErreurRestauration(
            "aucune copie du registre (registre-AAAA-MM-JJ.sqlite) dans la copie de secours : "
            "rien à restaurer. Si c'est un tout nouveau départ, lancer simplement le programme."
        )
    for copie in candidates:
        if _integre(copie):
            break
        bilan.problemes.append(f"copie {copie.name} abîmée, on essaie la précédente")
    else:
        raise ErreurRestauration("toutes les copies du registre sont abîmées.")
    cible = donnees / NOM_BASE
    donnees.mkdir(parents=True, exist_ok=True)
    if cible.exists():
        mise_de_cote = cible.with_name(f"{NOM_BASE}.avant-restauration")
        os.replace(cible, mise_de_cote)
        bilan.fait.append(f"ancien registre mis de côté : {mise_de_cote.name}")
    for reste in (donnees / f"{NOM_BASE}-wal", donnees / f"{NOM_BASE}-shm"):
        reste.unlink(missing_ok=True)
    provisoire = cible.with_name(NOM_BASE + ".restauration")
    shutil.copyfile(copie, provisoire)
    os.replace(provisoire, cible)
    # Ouvrir = vérifier et monter à la version du programme (avec copie de l'ancienne).
    try:
        ouvrir_registre(donnees).fermer()
    except ErreurRegistre as erreur:
        raise ErreurRestauration(f"le registre restauré ne s'ouvre pas : {erreur}") from None
    bilan.fait.append(f"registre remis : copie du {copie.name[9:19]}")


def _membre_sur(membre: tarfile.TarInfo) -> str | None:
    """Le nom sous lequel ranger ce membre d'archive, ou None s'il est à refuser."""
    if not membre.isreg() or membre.size > TAILLE_MAX_FICHIER:
        return None
    morceaux = membre.name.split("/")
    if membre.name == NOM_COMPTES:
        return NOM_COMPTES
    if (
        len(morceaux) > 2
        and morceaux[0] == DOSSIER_REGLAGES_DANS_ARCHIVE
        and chemin_de_reglage_sur("/".join(morceaux[1:]))
    ):
        return membre.name
    if (
        len(morceaux) == 2
        and morceaux[0] == DOSSIER_DONNEES_DANS_ARCHIVE
        and _NOM_SIMPLE.match(morceaux[1])
    ):
        return membre.name
    return None


def restaurer_fichiers(
    copies: Path,
    chemins: Chemins,
    ignores: list[str],
    ecraser: bool,
    bilan: Bilan,
) -> dict[str, bytes]:
    """Remet les fichiers des données et les comptes ; rend les réglages du Pi trouvés dans
    l'archive ({chemin dans le dépôt: contenu}), à remettre ensuite par `remettre_reglages`."""
    reglages: dict[str, bytes] = {}
    archives = sorted(
        (f for f in copies.rglob("*") if f.is_file() and est_une_archive(f.name)),
        key=lambda f: f.name,
        reverse=True,
    )
    if not archives:
        bilan.problemes.append(
            "pas d'archive des fichiers hors Git (fichiers-AAAA-MM-JJ.tar.gz) dans la copie de "
            "secours : comptes et fichiers appris non restaurés"
        )
        return reglages
    remis = []
    with tarfile.open(archives[0], "r:gz") as archive:
        for membre in archive:
            nom = _membre_sur(membre)
            if nom is None:
                bilan.problemes.append(f"élément refusé dans l'archive : {membre.name}")
                continue
            source = archive.extractfile(membre)
            if source is None:
                continue
            if nom.startswith(DOSSIER_REGLAGES_DANS_ARCHIVE + "/"):
                reglages[nom.split("/", 1)[1]] = source.read()
                continue
            if nom == NOM_COMPTES:
                cible, discret = chemins.comptes, True
            else:
                fichier = nom.split("/", 1)[1]
                if fichier in ignores:
                    continue
                cible, discret = chemins.donnees / fichier, False
            if cible.exists() and not ecraser:
                bilan.a_la_main.append(
                    f"{cible} existait déjà : gardé tel quel (ajouter --ecraser pour le remplacer)"
                )
                continue
            cible.parent.mkdir(parents=True, exist_ok=True)
            provisoire = cible.with_name(cible.name + ".restauration")
            descripteur = os.open(provisoire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descripteur, "wb") as sortie:
                shutil.copyfileobj(source, sortie)
            os.replace(provisoire, cible)
            if not discret:
                cible.chmod(0o644)
            remis.append(cible.name)
    bilan.fait.append(
        f"fichiers hors Git remis ({archives[0].name}) : {', '.join(remis) or 'aucun'}"
    )
    if NOM_COMPTES not in remis and not chemins.comptes.exists():
        bilan.a_la_main.append(
            "Aucun compte pour la page web : en créer un avec « sudo -u vidange "
            "/opt/vidange-auto/pi/.venv/bin/vidange compte ajouter NOM --role karulium »."
        )
    return reglages


def _ecrire(cible: Path, contenu: bytes) -> None:
    provisoire = cible.with_name(cible.name + ".restauration")
    provisoire.write_bytes(contenu)
    shutil.copymode(cible, provisoire)
    os.replace(provisoire, cible)


def remettre_reglages(
    chemins: Chemins,
    reglages: dict[str, bytes],
    ecraser: bool,
    verifier: Callable[[], int],
    bilan: Bilan,
) -> list[Path]:
    """Remet les réglages que l'ancien Pi avait changés, un par un, avec la vérification des
    réglages après chacun. Un fichier qui ne passe plus avec le code du jour est mis de côté
    (dans donnees/reglages-mis-de-cote) et dit à Karulium ; les autres sont remis quand même.
    Rend les fichiers écrits."""
    if not reglages:
        return []
    depot = chemins.depot
    if depot is None:
        bilan.a_la_main.append(
            f"L'archive contient {len(reglages)} réglage(s) changé(s) sur l'ancien Pi, mais le "
            "dépôt du logiciel est inconnu (--depot) : rien remis."
        )
        return []
    deja = set(reglages_changes(depot))
    a_remettre: dict[str, tuple[Path, bytes, bytes]] = {}  # chemin: (fichier, nouveau, d'origine)
    for chemin, contenu in sorted(reglages.items()):
        fichier = depot / chemin
        if not fichier.is_file():
            _mettre_de_cote(chemins, chemin, contenu, "n'existe plus dans cette version", bilan)
        elif fichier.read_bytes() == contenu:
            continue
        elif chemin in deja and not ecraser:
            bilan.a_la_main.append(
                f"{chemin} était déjà changé sur ce Pi : gardé tel quel (--ecraser pour mettre "
                "celui de l'ancien Pi ; il est dans l'archive)."
            )
        else:
            a_remettre[chemin] = (fichier, contenu, fichier.read_bytes())
    ecrits: list[Path] = []
    remis: list[str] = []

    def poser(chemin: str, nouveau: bool) -> None:
        fichier, contenu, origine = a_remettre[chemin]
        _ecrire(fichier, contenu if nouveau else origine)

    for chemin in a_remettre:
        poser(chemin, True)
    if a_remettre and verifier() == 0:
        remis = list(a_remettre)
    elif a_remettre:
        for chemin in a_remettre:
            poser(chemin, False)
        if verifier() != 0:
            # Les réglages du Pi n'y sont pour rien : on les remet, la vérification finale parlera.
            for chemin in a_remettre:
                poser(chemin, True)
            remis = list(a_remettre)
            bilan.a_la_main.append(
                "La vérification des réglages échouait déjà sans les réglages de l'ancien Pi : "
                "ils sont remis, mais à contrôler après avoir corrigé le reste."
            )
        else:
            for chemin in a_remettre:
                poser(chemin, True)
                if verifier() == 0:
                    remis.append(chemin)
                else:
                    poser(chemin, False)
                    _mettre_de_cote(
                        chemins,
                        chemin,
                        a_remettre[chemin][1],
                        "ne passe plus la vérification avec la version du jour du logiciel",
                        bilan,
                    )
    ecrits = [a_remettre[c][0] for c in remis]
    if remis:
        bilan.fait.append(f"réglages de l'ancien Pi remis : {', '.join(remis)}")
    return ecrits


def _mettre_de_cote(
    chemins: Chemins, chemin: str, contenu: bytes, raison: str, bilan: Bilan
) -> None:
    dossier = chemins.donnees / DOSSIER_MIS_DE_COTE
    dossier.mkdir(parents=True, exist_ok=True)
    cible = dossier / chemin.replace("/", "__")
    cible.write_bytes(contenu)
    bilan.a_la_main.append(
        f"Réglage de l'ancien Pi PAS remis : {chemin} {raison}. Il est gardé dans {cible} : "
        "recopier ses valeurs à la main dans le fichier du dépôt (page des réglages ou éditeur), "
        "puis « vidange --verifier »."
    )


def restaurer_photos(copies: Path, donnees: Path, bilan: Bilan) -> None:
    photos = copies / DOSSIER_PHOTOS
    if not photos.is_dir():
        bilan.a_la_main.append("Pas de dossier de photos dans la copie de secours : rien remis.")
        return
    shutil.copytree(photos, donnees / DOSSIER_PHOTOS, dirs_exist_ok=True)
    bilan.fait.append("photos remises")


def preparer_secrets(chemins: Chemins, bilan: Bilan) -> None:
    """Les secrets ne sont jamais dans la copie de secours : on prépare le fichier à remplir."""
    if not chemins.secrets.exists():
        chemins.secrets.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(chemins.secrets_exemple, chemins.secrets)
        chemins.secrets.chmod(0o600)
        bilan.fait.append(f"modèle de secrets posé : {chemins.secrets}")
        bilan.a_la_main.append(
            f"Remplir {chemins.secrets} avec les secrets gardés dans votre gestionnaire de mots de "
            "passe : jeton_culture (logiciel de culture) et, si le dépôt est privé, jeton_github. "
            "Puis « sudo systemctl restart vidange »."
        )
        return
    try:
        secrets = charger_secrets(chemins.secrets)
    except ErreurReglages as erreur:
        bilan.problemes.append(f"fichier de secrets faux : {erreur}")
        return
    vides = [nom for nom in ("jeton_culture", "jeton_github") if getattr(secrets, nom) is None]
    if vides:
        bilan.a_la_main.append(
            f"Secrets encore vides dans {chemins.secrets} : {', '.join(vides)} "
            "(inutile si vous ne vous en servez pas)."
        )


def attendre_service(
    commandes: Commandes, attente_s: float, dormir: Callable[[float], None]
) -> bool:
    fin = time.monotonic() + attente_s
    while True:
        code, _ = commandes.lancer(["systemctl", "is-active", "--quiet", "vidange"], 10)
        if code == 0:
            return True
        if time.monotonic() >= fin:
            return False
        dormir(1)


def restaurer(
    chemins: Chemins,
    reglages: Reglages,
    source: str,
    commandes: Commandes,
    verifier: Callable[[], int],
    options: Options | None = None,
    donner_au_programme: Callable[[Path], None] | None = None,
    dormir: Callable[[float], None] = time.sleep,
) -> Bilan:
    """Fait toute la restauration. Lève ErreurRestauration si elle est impossible ; sinon rend le
    bilan (`reussi` faux si la vérification finale a trouvé un problème)."""
    options = options or Options()
    bilan = Bilan()
    donnees = chemins.donnees
    if not options.photos_seulement and not options.ecraser and (donnees / NOM_BASE).exists():
        raise ErreurRestauration(
            f"ce Pi a déjà un registre ({donnees / NOM_BASE}) : la restauration le remplacerait. "
            "Si c'est bien ce qu'on veut, ajouter --ecraser (l'ancien est mis de côté)."
        )
    temporaire = donnees / ".restauration"
    shutil.rmtree(temporaire, ignore_errors=True)
    provisoire = False
    reglages_remis: list[Path] = []
    try:
        copies, provisoire = recuperer(source, temporaire, commandes, options.delai_copie_s)
        bilan.fait.append(f"copie de secours trouvée : {source}")
        if options.photos_seulement:
            restaurer_photos(copies, donnees, bilan)
        else:
            restaurer_registre(copies, donnees, options.ecraser, bilan)
            reglages_du_pi = restaurer_fichiers(
                copies,
                chemins,
                reglages.programme.registre.restauration_ignore,
                options.ecraser,
                bilan,
            )
            if options.avec_photos:
                restaurer_photos(copies, donnees, bilan)
            else:
                bilan.a_la_main.append(
                    "Photos pas encore remises : « vidange restaurer --depuis ... "
                    "--photos-seulement » (peut se faire pendant que la machine travaille)."
                )
            preparer_secrets(chemins, bilan)
            reglages_remis = remettre_reglages(
                chemins, reglages_du_pi, options.ecraser, verifier, bilan
            )
    finally:
        if provisoire or ":" in source:
            shutil.rmtree(temporaire, ignore_errors=True)

    if donner_au_programme is not None:
        for chemin in (donnees, chemins.secrets, chemins.comptes, *reglages_remis):
            if chemin.exists():
                donner_au_programme(chemin)
        bilan.fait.append("fichiers donnés au compte du programme")

    if options.photos_seulement:
        return bilan

    if verifier() == 0:
        bilan.fait.append("réglages vérifiés (comme « vidange --verifier »)")
    else:
        bilan.problemes.append(
            "la vérification des réglages a échoué : lire le message ci-dessus, le corriger, "
            "puis « vidange --verifier »"
        )
    if options.avec_service:
        code, sortie = commandes.lancer(["systemctl", "enable", "--now", "vidange"], 60)
        if code != 0:
            bilan.problemes.append(
                f"le service n'a pas pu être lancé (code {code}) : {sortie.strip()}. "
                "Le copier d'abord : voir pi/systeme/installation.md, étape 5."
            )
        elif attendre_service(commandes, options.attente_service_s, dormir):
            bilan.fait.append("service « vidange » lancé et actif")
        else:
            bilan.problemes.append(
                "le service ne reste pas actif : « journalctl -u vidange -n 50 » dit pourquoi"
            )
    else:
        bilan.a_la_main.append("Lancer le service : « sudo systemctl enable --now vidange ».")

    code, _ = commandes.lancer(["tailscale", "status"], 15)
    if code != 0:
        bilan.a_la_main.append(
            "Tailscale n'est pas installé ou pas relié : « curl -fsSL "
            "https://tailscale.com/install.sh | sh » puis « sudo tailscale up » "
            "(pi/systeme/installation.md, étape 8). La page web "
            "marche déjà sur le réseau local."
        )
    bilan.a_la_main.append(
        "Au premier démarrage, la machine propose le retour en lieu sûr et ATTEND le Go à l'écran "
        "de l'armoire : vérifier d'abord que rien ne gêne les axes."
    )
    return bilan
