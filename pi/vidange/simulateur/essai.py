"""Essai d'un réglage dans le simulateur (tâche 30, fonction 68).

    vidange simuler --essayer machine.yaml=griffe.vitesses.pont_x=0.2
    vidange simuler --essayer machine.yaml=griffe.vitesses.pont_x=0.2 --essayer programme.yaml=...

Rejoue un lot simulé (le même que `vidange-simulateur cycle`) avec le réglage changé, sans toucher
aux vrais fichiers (le changement est fait sur une copie provisoire), et le compare au lot simulé
normal : durée totale, alertes (alarme, ordre du cycle pas suivi, retour à l'ordre normal du
solveur) et refus du chef. Le réglage changé passe d'abord TOUTES les vérifications du
démarrage : un réglage que le programme refuserait est refusé ici avec le même message.

Les valeurs du simulateur sont celles de simulateur.yaml (souvent des exemples) : un essai dit ce
que le logiciel ferait, jamais ce que la vraie machine ferait. Rien n'est appliqué : pour garder un
réglage, le changer à la main (ou depuis la page web pour les réglages permis).
"""

import shutil
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from vidange.chef import ErreurChef
from vidange.reglages import FICHIERS, ErreurReglages, Reglages, lire_yaml
from vidange.simulateur.planning import duree_lisible
from vidange.simulateur.simulateur import ErreurSimulation


class ErreurEssai(Exception):
    """Réglage à essayer mal écrit, inconnu ou refusé par les vérifications du démarrage."""


@dataclass(frozen=True)
class Changement:
    fichier: str
    chemin: str
    valeur: Any
    avant: Any

    def en_texte(self) -> str:
        return f"{self.fichier} : {self.chemin} = {self.valeur} (avant : {self.avant})"


@dataclass
class ResultatLot:
    """Ce que le lot simulé a donné."""

    fini: bool = False
    temps_total_s: float = 0.0
    alertes: list[str] = field(default_factory=list)
    refus: str = ""

    def en_dict(self) -> dict[str, Any]:
        return {
            "fini": self.fini,
            "temps_total_s": round(self.temps_total_s, 1),
            "alertes": self.alertes,
            "refus": self.refus,
        }


@dataclass
class Comparaison:
    changements: list[Changement]
    normal: ResultatLot
    essai: ResultatLot

    @property
    def sans_probleme(self) -> bool:
        return self.essai.fini and not self.essai.alertes and not self.essai.refus

    def en_texte(self) -> str:
        lignes = [
            "Essai d'un réglage dans le simulateur (rien n'est écrit dans les vrais fichiers)",
            "Réglage(s) essayé(s) :",
            *[f"  {changement.en_texte()}" for changement in self.changements],
            "",
            _ligne("", "Lot normal", "Lot avec l'essai", "Écart"),
            _ligne("Durée totale", _duree(self.normal), _duree(self.essai), self._ecart()),
            _ligne("Alertes", _alertes(self.normal), _alertes(self.essai)),
            _ligne("Refus du chef", self.normal.refus or "aucun", self.essai.refus or "aucun"),
        ]
        for nom, resultat in (("normal", self.normal), ("essai", self.essai)):
            lignes += [f"  Alerte du lot {nom} : {alerte}" for alerte in resultat.alertes]
        lignes.append("")
        if self.sans_probleme:
            lignes.append(
                "Verdict : le lot simulé va au bout avec ce réglage, sans alerte ni refus."
            )
        else:
            lignes.append(
                "Verdict : ce réglage donne une alerte, un refus ou un lot qui ne finit pas."
            )
        lignes.append(
            "Ce n'est qu'une simulation (réglages du simulateur) : essayer d'abord à vide sur la "
            "machine (pi/systeme/essai-vitesse-estimation.md)."
        )
        return "\n".join(lignes)

    def _ecart(self) -> str:
        if not (self.normal.fini and self.essai.fini) or self.normal.temps_total_s <= 0:
            return "—"
        ecart = self.essai.temps_total_s - self.normal.temps_total_s
        pct = 100 * ecart / self.normal.temps_total_s
        signe = "+" if ecart >= 0 else "-"
        return f"{signe}{duree_lisible(abs(ecart))} ({signe}{abs(pct):.1f} %)".replace(".", ",")

    def en_dict(self) -> dict[str, Any]:
        return {
            "changements": [
                {"fichier": c.fichier, "chemin": c.chemin, "valeur": c.valeur, "avant": c.avant}
                for c in self.changements
            ],
            "normal": self.normal.en_dict(),
            "essai": self.essai.en_dict(),
            "sans_probleme": self.sans_probleme,
            "texte": self.en_texte(),
        }


def _ligne(titre: str, normal: str, essai: str, ecart: str = "") -> str:
    return f"{titre:<16}{normal:<22}{essai:<22}{ecart}".rstrip()


def _duree(resultat: ResultatLot) -> str:
    return duree_lisible(resultat.temps_total_s) if resultat.fini else "pas fini"


def _alertes(resultat: ResultatLot) -> str:
    return str(len(resultat.alertes)) if resultat.alertes else "aucune"


# ------------------------------------------------------------ les changements demandés


def lire_changement(texte: str) -> tuple[str, str, Any]:
    """« machine.yaml=griffe.vitesses.pont_x=0.2 » → (fichier, chemin, valeur lue en YAML)."""
    morceaux = texte.split("=", 2)
    if len(morceaux) != 3 or not all(m.strip() for m in morceaux):
        raise ErreurEssai(
            f"« {texte} » : écrire fichier=chemin=valeur (exemple : "
            "machine.yaml=griffe.vitesses.pont_x=0.2)"
        )
    fichier, chemin, brut = (m.strip() for m in morceaux)
    if "." not in fichier:
        fichier += ".yaml"
    if fichier not in FICHIERS:
        raise ErreurEssai(f"« {fichier} » : fichier inconnu (fichiers : {', '.join(FICHIERS)})")
    try:
        valeur = yaml.safe_load(brut)
    except yaml.YAMLError:
        raise ErreurEssai(f"« {texte} » : valeur mal écrite") from None
    if isinstance(valeur, dict | list) or valeur is None:
        raise ErreurEssai(f"« {texte} » : seulement un nombre, un oui/non ou un mot")
    return fichier, chemin, valeur


def _trouver(donnees: Any, morceaux: list[str]) -> tuple[dict[str, Any], str] | None:
    """Le dictionnaire et la clé où se trouve « a.b.c » (une clé peut elle-même contenir des
    points, comme « griffe.vitesses.pont_x » dans montee_vitesse → vitesses)."""
    if not isinstance(donnees, dict):
        return None
    for longueur in range(len(morceaux), 0, -1):
        cle = ".".join(morceaux[:longueur])
        if cle not in donnees:
            continue
        if longueur == len(morceaux):
            return donnees, cle
        trouve = _trouver(donnees[cle], morceaux[longueur:])
        if trouve is not None:
            return trouve
    return None


def _changer(donnees: dict[str, Any], chemin: str, valeur: Any, fichier: str) -> Any:
    """Change la valeur de « a.b.c » dans les données lues ; rend l'ancienne."""
    trouve = _trouver(donnees, chemin.split("."))
    if trouve is None:
        raise ErreurEssai(f"{fichier} : « {chemin} » n'existe pas")
    courant, cle = trouve
    if isinstance(courant[cle], dict | list):
        raise ErreurEssai(f"{fichier} : « {chemin} » n'est pas une valeur simple")
    ancien = courant[cle]
    courant[cle] = valeur
    return ancien


def copie_provisoire(dossier: Path, demandes: list[str], destination: Path) -> list[Changement]:
    """Copie les réglages dans `destination` avec les changements demandés (les vrais fichiers ne
    bougent pas). Rend les changements faits."""
    lus = [lire_changement(demande) for demande in demandes]
    if not lus:
        raise ErreurEssai("aucun réglage à essayer (--essayer fichier=chemin=valeur)")
    shutil.copytree(dossier, destination, dirs_exist_ok=True)
    par_fichier: dict[str, dict[str, Any]] = {}
    faits: list[Changement] = []
    for fichier, chemin, valeur in lus:
        if fichier not in par_fichier:
            try:
                par_fichier[fichier] = lire_yaml(destination / fichier)
            except ErreurReglages as erreur:
                raise ErreurEssai(str(erreur)) from None
        ancien = _changer(par_fichier[fichier], chemin, valeur, fichier)
        faits.append(Changement(fichier, chemin, valeur, ancien))
    for fichier, donnees in par_fichier.items():
        (destination / fichier).write_text(
            yaml.safe_dump(donnees, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    return faits


# ------------------------------------------------------------ le lot simulé


def jouer_le_lot(reglages: Reglages, liste: Any) -> ResultatLot:
    """Le lot de seaux simulé (même code que la machine) : durée, alertes, refus du chef."""
    from vidange.cycle.simulation import jouer_cycle
    from vidange.simulateur.simulateur import Simulateur

    resultat = ResultatLot()
    try:
        with Simulateur(reglages, liste, "cycle") as simulateur:
            _, planning, problemes = jouer_cycle(simulateur)
    except (ErreurSimulation, ErreurChef) as erreur:
        resultat.refus = str(erreur)
        return resultat
    resultat.temps_total_s = planning.temps_total
    resultat.fini = planning.fini
    if planning.probleme:
        resultat.alertes.append(planning.probleme)
    resultat.alertes += [f"ordre du cycle pas suivi : {probleme}" for probleme in problemes]
    if planning.recul_programme:
        resultat.alertes.append(f"retour à l'ordre normal : {planning.recul_programme}")
    return resultat


def essayer(
    dossier_reglages: Path,
    chemin_entrees_sorties: Path,
    demandes: list[str],
    jouer: Callable[[Reglages, Any], ResultatLot] | None = None,
) -> Comparaison:
    """Le lot simulé normal contre le même lot avec les changements. ErreurEssai si un réglage est
    mal écrit ou refusé par les vérifications du démarrage."""
    from vidange.demarrage import erreurs_de_reglages
    from vidange.entrees_sorties import charger_entrees_sorties
    from vidange.reglages import charger_reglages

    with tempfile.TemporaryDirectory(prefix="vidange-essai-") as provisoire:
        copie = Path(provisoire) / "reglages"
        changements = copie_provisoire(dossier_reglages, demandes, copie)
        erreurs = erreurs_de_reglages(copie, chemin_entrees_sorties)
        if erreurs:
            raise ErreurEssai(
                "réglage refusé, comme le ferait le démarrage du programme :\n"
                + "\n".join(f"  - {erreur}" for erreur in erreurs)
            )
        liste = charger_entrees_sorties(chemin_entrees_sorties)
        jouer = jouer or jouer_le_lot
        normal = jouer(charger_reglages(dossier_reglages), liste)
        essai = jouer(charger_reglages(copie), liste)
    return Comparaison(changements, normal, essai)


class EssaiEnFond:
    """Le bouton de la page web (rôle « régler ») : un seul essai à la fois, dans un fil à part ;
    la page demande ensuite où il en est. Refusé quand le programme ne veut pas (un lot tourne)."""

    def __init__(
        self,
        dossier_reglages: Path,
        chemin_entrees_sorties: Path,
        refus: Callable[[], str] = lambda: "",
        jouer: Callable[[Reglages, Any], ResultatLot] | None = None,
        en_fond: bool = True,
    ) -> None:
        self._dossier = dossier_reglages
        self._liste = chemin_entrees_sorties
        self._refus = refus
        self._jouer = jouer
        self._en_fond = en_fond
        self._verrou = threading.Lock()
        self._etat: dict[str, Any] = {"en_cours": False, "resultat": None, "erreur": None}

    def lancer(self, demandes: list[str], qui: str) -> dict[str, Any]:
        with self._verrou:
            if self._etat["en_cours"]:
                raise ErreurEssai("un essai est déjà en cours")
            pourquoi = self._refus()
            if pourquoi:
                raise ErreurEssai(f"essai refusé : {pourquoi}")
            # Les réglages mal écrits sont refusés tout de suite (avant le fil).
            lire = [lire_changement(demande) for demande in demandes]
            if not lire:
                raise ErreurEssai("aucun réglage à essayer")
            self._etat = {
                "en_cours": True,
                "resultat": None,
                "erreur": None,
                "demandes": list(demandes),
                "qui": qui,
            }
        if self._en_fond:
            threading.Thread(
                target=self._faire, args=(demandes,), name="essai", daemon=True
            ).start()
        else:
            self._faire(demandes)
        return self.etat()

    def _faire(self, demandes: list[str]) -> None:
        resultat, erreur = None, None
        try:
            resultat = essayer(self._dossier, self._liste, demandes, self._jouer).en_dict()
        except ErreurEssai as probleme:
            erreur = str(probleme)
        except Exception as probleme:
            erreur = f"essai raté : {probleme}"
        with self._verrou:
            self._etat.update({"en_cours": False, "resultat": resultat, "erreur": erreur})

    def etat(self) -> dict[str, Any]:
        with self._verrou:
            return dict(self._etat)


def lancer_essai(arguments: list[str], dossier_reglages: Path, chemin_entrees_sorties: Path) -> int:
    """« vidange simuler --essayer fichier=chemin=valeur ... » : code de sortie 0 si le lot essayé
    va au bout sans alerte ni refus, 1 sinon, 2 si un réglage est mal écrit ou refusé."""
    import argparse
    import sys

    lecteur = argparse.ArgumentParser(
        prog="vidange simuler",
        description="Essaie un réglage dans le simulateur (rien n'est écrit).",
    )
    lecteur.add_argument(
        "--essayer",
        action="append",
        default=[],
        metavar="FICHIER=CHEMIN=VALEUR",
        help="réglage à essayer, par exemple machine.yaml=griffe.vitesses.pont_x=0.2 (répétable)",
    )
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument("--entrees-sorties", help="liste des entrées/sorties")
    options = lecteur.parse_args(arguments)
    if not options.essayer:
        lecteur.error("donner au moins un réglage : --essayer fichier=chemin=valeur")
    if options.reglages:
        dossier_reglages = Path(options.reglages)
    if options.entrees_sorties:
        chemin_entrees_sorties = Path(options.entrees_sorties)
    try:
        comparaison = essayer(dossier_reglages, chemin_entrees_sorties, options.essayer)
    except (ErreurEssai, ErreurReglages) as erreur:
        print(f"Essai impossible : {erreur}", file=sys.stderr)
        return 2
    print(comparaison.en_texte())
    return 0 if comparaison.sans_probleme else 1
