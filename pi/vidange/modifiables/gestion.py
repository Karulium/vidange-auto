"""Changer un réglage depuis la page web, avec garde-fous (tâche 28 bis, fonction 56).

    modifiables = Modifiables(reglages.modifiables, reglages, dossier_reglages, registre,
                              verifier=erreurs_de_reglages, occupe=lambda: "")
    modifiables.changer("calmes_debut", "20:30", "page web (karulium, 100.1.2.3)")
    modifiables.revenir(numero, qui)

Ce que ça ne fait JAMAIS : changer autre chose que les réglages de `modifiables.yaml`, et ce
fichier ne peut viser que ce que `SECTIONS_MODIFIABLES` (vidange/reglages.py) permet : jamais une
position, une course, une zone, une broche, ni rien qui touche au mouvement (vérifié au démarrage).

Chaque changement, dans l'ordre :
  1. refusé si un geste ou un lot est en cours (`occupe`) ;
  2. la valeur est vérifiée (genre, bornes) ;
  3. la nouvelle version du fichier est fabriquée en ne changeant que cette valeur (les
     commentaires restent), relue avec le vrai lecteur YAML pour être sûr de ce qui a été écrit ;
  4. TOUTES les vérifications du démarrage tournent sur la nouvelle version, dans un dossier
     provisoire : une erreur (le résumé du soir tombe dans les heures calmes...) refuse le
     changement, rien n'est écrit ;
  5. le fichier est remplacé d'un seul coup (fichier provisoire, puis renommage) ;
  6. le changement est noté dans le registre (« reglages_appliques » : qui, quand, avant, après),
     ce qui permet de « revenir ».

Le programme ne relit pas ses réglages en route : un changement agit au prochain démarrage
(`redemarrage_necessaire` le dit). Les fichiers de réglages sont dans Git : une mise à jour du
programme depuis la page remet de côté, puis reprend, les valeurs changées ici.
"""

import json
import os
import shutil
import stat
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from vidange.journal import donner_journal
from vidange.modifiables.texte_yaml import ErreurTexteYaml, remplacer_valeur
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import (
    FICHIERS,
    ErreurReglages,
    ReglageModifiable,
    Reglages,
    ReglagesModifiables,
    lire_yaml,
    valeur_au_chemin,
    valeur_dans_les_bornes,
)

journal = donner_journal("modifiables")

# Dans le registre, ce qui distingue les changements faits depuis cette page des autres.
PREFIXE_RAISON = "page : "


class ErreurModifiable(Exception):
    """Changement refusé. `statut` : 404 (réglage inconnu), 422 (valeur fausse), 409 (pas
    maintenant, ou les vérifications du démarrage refusent)."""

    def __init__(self, message: str, statut: int = 409) -> None:
        super().__init__(message)
        self.statut = statut


def ecrire_fichier_surement(chemin: Path, texte: str) -> None:
    """Remplace le fichier d'un seul coup : jamais un fichier à moitié écrit, même si le courant
    se coupe (fichier provisoire écrit et forcé sur le disque, puis renommage)."""
    provisoire = chemin.with_name(chemin.name + ".nouveau")
    droits = stat.S_IMODE(chemin.stat().st_mode)
    with provisoire.open("w", encoding="utf-8", newline="") as fichier:
        fichier.write(texte)
        fichier.flush()
        os.fsync(fichier.fileno())
    os.chmod(provisoire, droits)
    os.replace(provisoire, chemin)
    dossier = os.open(chemin.parent, os.O_RDONLY)
    try:
        os.fsync(dossier)
    finally:
        os.close(dossier)


def _en_json(valeur: str | None) -> Any:
    return None if valeur is None else json.loads(valeur)


class Modifiables:
    def __init__(
        self,
        liste: ReglagesModifiables,
        au_demarrage: Reglages,
        dossier: Path,
        registre: Registre,
        verifier: Callable[[Path], list[str]],
        occupe: Callable[[], str] = lambda: "",
    ) -> None:
        """`au_demarrage` : les réglages tels que le programme les utilise (pour dire si un
        redémarrage est nécessaire). `verifier(dossier)` : les vérifications du démarrage sur un
        dossier de réglages, une liste d'erreurs en français (vide : tout va bien). `occupe()` :
        pourquoi on ne peut pas changer maintenant (geste ou lot en cours), ou "" si on peut."""
        self.liste = liste
        self.dossier = dossier
        self.registre = registre
        self._verifier = verifier
        self._occupe = occupe
        self._verrou = threading.Lock()
        self._en_vigueur = {
            fichier: modele
            for fichier, (cle, _) in FICHIERS.items()
            if (modele := getattr(au_demarrage, cle)) is not None
        }

    # ------------------------------------------------------------ lecture

    def _valeur_du_fichier(self, reglage: ReglageModifiable) -> Any:
        return valeur_au_chemin(lire_yaml(self.dossier / reglage.fichier), reglage.chemin)

    def _valeur_en_vigueur(self, reglage: ReglageModifiable) -> Any:
        modele = self._en_vigueur[reglage.fichier]
        return valeur_au_chemin(modele.model_dump(), reglage.chemin)

    def _nom_de(self, fichier: str, chemin: str) -> str | None:
        for nom, reglage in self.liste.reglages.items():
            if (reglage.fichier, reglage.chemin) == (fichier, chemin):
                return nom
        return None

    def historique(self, limite: int = 50) -> list[dict[str, Any]]:
        """Les changements faits depuis la page, du plus récent au plus ancien."""
        lignes = self.registre.lire(
            "SELECT id, quand, qui, fichier, reglage, ancien, nouveau, raison "
            "FROM reglages_appliques WHERE raison LIKE ? ORDER BY id DESC LIMIT ?",
            (PREFIXE_RAISON + "%", limite),
        )
        resultat = []
        for ligne in lignes:
            nom = self._nom_de(ligne["fichier"], ligne["reglage"])
            resultat.append(
                {
                    "numero": ligne["id"],
                    "quand": ligne["quand"],
                    "qui": ligne["qui"],
                    "nom": nom,
                    "libelle": self.liste.reglages[nom].libelle if nom else ligne["reglage"],
                    "ancien": _en_json(ligne["ancien"]),
                    "nouveau": _en_json(ligne["nouveau"]),
                    "raison": ligne["raison"][len(PREFIXE_RAISON) :],
                }
            )
        return resultat

    def _dernier_changement(self, reglage: ReglageModifiable) -> dict[str, Any] | None:
        lignes = self.registre.lire(
            "SELECT id, quand, qui, ancien, nouveau FROM reglages_appliques "
            "WHERE fichier = ? AND reglage = ? AND raison LIKE ? ORDER BY id DESC LIMIT 1",
            (reglage.fichier, reglage.chemin, PREFIXE_RAISON + "%"),
        )
        if not lignes:
            return None
        ligne = lignes[0]
        return {
            "numero": ligne["id"],
            "quand": ligne["quand"],
            "qui": ligne["qui"],
            "ancien": _en_json(ligne["ancien"]),
            "nouveau": _en_json(ligne["nouveau"]),
        }

    def etat(self) -> dict[str, Any]:
        """Tout ce qu'il faut à la page : chaque réglage (valeur, bornes, aide...), ce qui change
        au prochain redémarrage, et si c'est le moment ou non."""
        reglages = []
        for nom, reglage in self.liste.reglages.items():
            valeur = self._valeur_du_fichier(reglage)
            en_vigueur = self._valeur_en_vigueur(reglage)
            dernier = self._dernier_changement(reglage)
            # « Revenir » seulement si le dernier changement est encore celui du fichier.
            peut_revenir = dernier is not None and dernier["nouveau"] == valeur
            reglages.append(
                {
                    "nom": nom,
                    "libelle": reglage.libelle,
                    "fichier": reglage.fichier,
                    "chemin": reglage.chemin,
                    "genre": reglage.genre,
                    "min": reglage.min,
                    "max": reglage.max,
                    "unite": reglage.unite,
                    "aide": reglage.aide,
                    "valeur": valeur,
                    "en_vigueur": en_vigueur,
                    "redemarrage_necessaire": reglage.redemarrage and valeur != en_vigueur,
                    "dernier_changement": dernier,
                    "peut_revenir": peut_revenir,
                }
            )
        return {
            "exemple": self.liste.exemple,
            "occupe": self._occupe(),
            "redemarrage_necessaire": any(r["redemarrage_necessaire"] for r in reglages),
            "reglages": reglages,
        }

    # ------------------------------------------------------------ changements

    def changer(self, nom: str, valeur: Any, qui: str) -> dict[str, Any]:
        """Change un réglage (toutes les protections ci-dessus). Rend ce qui a été fait."""
        reglage = self.liste.reglages.get(nom)
        if reglage is None:
            connus = ", ".join(self.liste.reglages)
            raise ErreurModifiable(
                f"réglage « {nom} » pas dans la liste des réglages modifiables ({connus})", 404
            )
        return self._appliquer(nom, reglage, valeur, qui, "changement")

    def revenir(self, numero: int, qui: str) -> dict[str, Any]:
        """Remet la valeur d'avant le changement n° `numero` (seulement si c'est le dernier
        changement de ce réglage et que le fichier n'a pas bougé depuis)."""
        lignes = self.registre.lire(
            "SELECT id, fichier, reglage, ancien, nouveau FROM reglages_appliques "
            "WHERE id = ? AND raison LIKE ?",
            (numero, PREFIXE_RAISON + "%"),
        )
        if not lignes:
            raise ErreurModifiable(f"changement n° {numero} inconnu", 404)
        ligne = lignes[0]
        nom = self._nom_de(ligne["fichier"], ligne["reglage"])
        if nom is None:
            raise ErreurModifiable(
                f"{ligne['fichier']} → {ligne['reglage']} n'est plus dans la liste des réglages "
                "modifiables : on ne peut plus y toucher d'ici",
                409,
            )
        reglage = self.liste.reglages[nom]
        dernier = self._dernier_changement(reglage)
        if dernier is None or dernier["numero"] != numero:
            raise ErreurModifiable(
                f"le changement n° {numero} n'est plus le dernier de « {reglage.libelle} » : "
                "revenir d'abord sur le plus récent, ou changer la valeur directement"
            )
        if self._valeur_du_fichier(reglage) != _en_json(ligne["nouveau"]):
            raise ErreurModifiable(
                f"« {reglage.libelle} » a été changé autrement depuis le changement n° {numero} "
                "(à la main dans le fichier ?) : changer la valeur directement"
            )
        ancien = _en_json(ligne["ancien"])
        if ancien is None:
            raise ErreurModifiable(f"le changement n° {numero} n'a pas d'ancienne valeur")
        return self._appliquer(nom, reglage, ancien, qui, f"retour avant le changement n° {numero}")

    def _appliquer(
        self, nom: str, reglage: ReglageModifiable, valeur: Any, qui: str, motif: str
    ) -> dict[str, Any]:
        pourquoi = valeur_dans_les_bornes(reglage, valeur)
        if pourquoi is not None:
            raise ErreurModifiable(f"« {reglage.libelle} » : {valeur!r} {pourquoi}", 422)
        if reglage.genre == "entier":
            valeur = int(valeur)
        with self._verrou:
            occupe = self._occupe()
            if occupe:
                raise ErreurModifiable(f"refusé maintenant : {occupe}")
            chemin = self.dossier / reglage.fichier
            ancien = self._valeur_du_fichier(reglage)
            if ancien == valeur:
                raise ErreurModifiable(f"« {reglage.libelle} » vaut déjà {valeur}")
            texte = chemin.read_text(encoding="utf-8")
            try:
                neuf = remplacer_valeur(texte, reglage.chemin, valeur)
            except ErreurTexteYaml as erreur:
                raise ErreurModifiable(f"{reglage.fichier} : {erreur}") from None
            self._verifier_avant_d_ecrire(reglage, neuf, valeur)
            ecrire_fichier_surement(chemin, neuf)
            try:
                numero = self.registre.noter_reglage(
                    qui,
                    reglage.fichier,
                    reglage.chemin,
                    ancien,
                    valeur,
                    PREFIXE_RAISON + f"{nom} ({motif})",
                )
            except ErreurRegistre as erreur:
                # Le fichier est déjà changé : on le dit, la trace manque au registre.
                journal.error("Réglage %s changé mais pas noté au registre : %s", nom, erreur)
                numero = None
        journal.warning(
            "Réglage « %s » (%s → %s) changé de %r à %r par %s (%s)",
            nom,
            reglage.fichier,
            reglage.chemin,
            ancien,
            valeur,
            qui,
            motif,
        )
        return {
            "nom": nom,
            "libelle": reglage.libelle,
            "ancien": ancien,
            "nouveau": valeur,
            "numero": numero,
            "redemarrage": reglage.redemarrage,
        }

    def _verifier_avant_d_ecrire(self, reglage: ReglageModifiable, neuf: str, valeur: Any) -> None:
        """Le fichier neuf se relit comme prévu ET toutes les vérifications du démarrage passent
        sur lui, dans un dossier provisoire. Sinon : ErreurModifiable, rien n'est écrit."""
        with tempfile.TemporaryDirectory(prefix="reglages-essai-") as provisoire:
            essai = Path(provisoire)
            for fichier in [*self.dossier.glob("*.yaml"), *self.dossier.glob("*.yml")]:
                shutil.copy2(fichier, essai / fichier.name)
            (essai / reglage.fichier).write_text(neuf, encoding="utf-8", newline="")
            try:
                relu = valeur_au_chemin(lire_yaml(essai / reglage.fichier), reglage.chemin)
            except ErreurReglages as erreur:
                raise ErreurModifiable(f"le fichier changé serait mal écrit : {erreur}") from None
            if relu != valeur or type(relu) is not type(valeur):
                raise ErreurModifiable(
                    f"{reglage.fichier} : la ligne de {reglage.chemin} est écrite d'une façon que "
                    f"le programme ne sait pas changer sans risque ({relu!r} relu au lieu de "
                    f"{valeur!r}) : changer la valeur à la main"
                )
            erreurs = self._verifier(essai)
        if erreurs:
            raise ErreurModifiable(
                "refusé par les vérifications du démarrage (rien n'a été changé) :\n"
                + "\n".join(f"- {erreur}" for erreur in erreurs)
            )
