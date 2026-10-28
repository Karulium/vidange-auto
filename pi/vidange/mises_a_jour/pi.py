"""Mise à jour du programme du Pi depuis GitHub : les versions acceptées sur « main ».

    pi = ProgrammePi(reglages.programme.mises_a_jour.pi, depot, dossier, jeton)
    pi.version()      # la version installée (commit, date, titre)
    pi.chercher()     # télécharge ce qui est nouveau sur « main » et le liste
    pi.installer()    # passe à la dernière version de « main »
    pi.revenir()      # revient à la version d'avant la dernière mise à jour

Le programme vit dans une copie Git du dépôt (/opt/vidange-auto). Une mise à jour :
1. télécharge « main » (git fetch) ;
2. met de côté les changements faits à la main sur le Pi (réglages : programme.yaml...),
   passe à la nouvelle version, puis remet ces changements par-dessus. Si un de ces
   changements touche les mêmes lignes que la nouvelle version, rien n'est changé et on dit
   lesquels ;
3. installe le programme (pip, pour ses nouvelles bibliothèques) ;
4. vérifie les réglages avec le NOUVEAU programme (« python -m vidange --verifier ») ;
5. si 3 ou 4 rate, revient tout de suite à la version d'avant.
Le redémarrage du programme est fait ensuite par MisesAJour (gestion.py).

La version d'avant est notée dans « pi.json » (dossier des mises à jour) : c'est elle que
« revenir » remet.
"""

import base64
import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from vidange.journal import donner_journal
from vidange.mises_a_jour.commun import ErreurMiseAJour, Lanceur, lancer_commande
from vidange.reglages import ReglagesMajPi

journal = donner_journal("mises_a_jour.pi")

NOM_NOTE = "pi.json"
MESSAGE_COTE = "vidange : changements faits sur le Pi (mise à jour)"
# Git refuse de mettre des changements de côté sans nom ni adresse : ceux du programme.
IDENTITE = ["-c", "user.name=vidange", "-c", "user.email=vidange@localhost"]
FORMAT = "%H%x1f%h%x1f%cI%x1f%s"


def entete_jeton(jeton: str) -> dict[str, str]:
    """Variables qui donnent le jeton GitHub à git (jamais écrit dans une commande)."""
    code = base64.b64encode(f"x-access-token:{jeton}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {code}",
    }


class ProgrammePi:
    def __init__(
        self,
        reglages: ReglagesMajPi,
        depot: Path,
        dossier: Path,
        jeton: str | None = None,
        lancer: Lanceur = lancer_commande,
        installer: Callable[[], object] | None = None,
        verifier: Callable[[], object] | None = None,
    ) -> None:
        self.reglages = reglages
        # La copie Git du dépôt (son dossier « pi » contient le programme).
        self.depot = depot
        self.note = dossier / NOM_NOTE
        self._jeton = jeton
        self._lancer = lancer
        self._installer = installer or self._installer_paquet
        self._verifier = verifier or self._verifier_reglages

    # ------------------------------------------------------------ outils

    @property
    def distante(self) -> str:
        return f"{self.reglages.depot}/{self.reglages.branche}"

    def _git(self, *arguments: str, jeton: bool = False) -> str:
        variables = {"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        if jeton and self._jeton:
            variables |= entete_jeton(self._jeton)
        commande = ["git", *IDENTITE, *arguments]
        return self._lancer(commande, self.reglages.duree_max_s, str(self.depot), variables)

    def _installer_paquet(self) -> None:
        commande = [sys.executable, "-m", "pip", "install", "--quiet", "-e", str(self.depot / "pi")]
        self._lancer(commande, self.reglages.duree_max_s, str(self.depot / "pi"))

    def _verifier_reglages(self) -> None:
        # Un nouveau Python : il charge le NOUVEAU programme, avec les réglages du Pi
        # (variables VIDANGE_... posées par le service systemd, héritées).
        commande = [sys.executable, "-m", "vidange", "--verifier"]
        self._lancer(commande, self.reglages.duree_max_s, str(self.depot / "pi"))

    def _commit(self, nom: str) -> str:
        return self._git("rev-parse", "--verify", f"{nom}^{{commit}}").strip()

    def _decrire(self, ligne: str) -> dict[str, str]:
        commit, court, date, titre = ligne.split("\x1f", 3)
        return {"commit": commit, "court": court, "date": date, "titre": titre}

    # ------------------------------------------------------------ ce qu'on sait

    def version(self) -> dict[str, str]:
        """La version installée : commit, court, date, titre."""
        return self._decrire(self._git("log", "-1", f"--format={FORMAT}").strip())

    def avant(self) -> dict[str, Any] | None:
        """Ce que « revenir » remettrait (noté à la dernière mise à jour), ou None."""
        try:
            return json.loads(self.note.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def chercher(self) -> list[dict[str, str]]:
        """Télécharge « main » et rend les versions plus récentes que celle du Pi."""
        self._git("fetch", "--quiet", self.reglages.depot, self.reglages.branche, jeton=True)
        # « fetch dépôt branche » ne met pas toujours à jour « dépôt/branche » : on le fait.
        self._git("update-ref", f"refs/remotes/{self.distante}", "FETCH_HEAD")
        sortie = self._git("log", f"--format={FORMAT}", f"HEAD..{self.distante}")
        return [self._decrire(ligne) for ligne in sortie.splitlines() if ligne.strip()]

    # ------------------------------------------------------------ changements

    def _changements_locaux(self) -> bool:
        return bool(self._git("status", "--porcelain", "--untracked-files=no").strip())

    def _aller_a(self, cible: str) -> None:
        """Met la copie du dépôt sur `cible`, en gardant les changements faits sur le Pi."""
        ancien = self._commit("HEAD")
        de_cote = self._changements_locaux()
        if de_cote:
            self._git("stash", "push", "--message", MESSAGE_COTE)
        try:
            self._git("reset", "--hard", "--quiet", cible)
        except ErreurMiseAJour:
            if de_cote:
                self._git("stash", "pop")
            raise
        if not de_cote:
            return
        try:
            self._git("stash", "pop")
        except ErreurMiseAJour:
            conflits = self._git("diff", "--name-only", "--diff-filter=U").split()
            # On revient comme avant : l'ancienne version et les changements du Pi.
            self._git("reset", "--hard", "--quiet", ancien)
            self._git("stash", "pop")
            raise ErreurMiseAJour(
                "des changements faits sur le Pi touchent les mêmes lignes que la nouvelle "
                f"version ({', '.join(conflits) or 'fichiers inconnus'}) : rien n'est changé. "
                "Noter tes valeurs, remettre ces fichiers comme dans le dépôt "
                "(« git checkout -- FICHIER »), mettre à jour, puis réécrire tes valeurs."
            ) from None

    def _passer(self, ancien: str, cible: str, qui: str) -> None:
        """Va sur `cible`, installe et vérifie ; revient sur `ancien` si ça rate."""
        self._aller_a(cible)
        try:
            self._installer()
            self._verifier()
        except ErreurMiseAJour as erreur:
            journal.error("Nouvelle version refusée (%s) : retour à %s", erreur, ancien[:7])
            self._aller_a(ancien)
            try:
                self._installer()
            except ErreurMiseAJour as autre:
                journal.error("Réinstallation de la version d'avant ratée : %s", autre)
            raise ErreurMiseAJour(
                f"la nouvelle version ne passe pas ({erreur}) : la version d'avant est remise"
            ) from None
        self.note.parent.mkdir(parents=True, exist_ok=True)
        note = {
            "avant": ancien,
            "apres": cible,
            "quand": datetime.now().astimezone().isoformat(timespec="seconds"),
            "qui": qui,
        }
        self.note.write_text(json.dumps(note, ensure_ascii=False), encoding="utf-8")

    def installer(self, qui: str) -> str:
        """Passe à la dernière version de « main ». Rend le compte rendu."""
        nouvelles = self.chercher()
        if not nouvelles:
            raise ErreurMiseAJour("le programme du Pi est déjà à jour")
        ancien = self._commit("HEAD")
        cible = self._commit(self.distante)
        try:
            self._git("merge-base", "--is-ancestor", ancien, cible)
        except ErreurMiseAJour:
            raise ErreurMiseAJour(
                f"la version du Pi ({ancien[:7]}) n'est pas dans « {self.distante} » "
                "(changements enregistrés sur le Pi ?) : mise à jour à faire à la main"
            ) from None
        self._passer(ancien, cible, qui)
        return f"programme du Pi : {ancien[:7]} → {cible[:7]} ({len(nouvelles)} changement(s))"

    def revenir(self, qui: str) -> str:
        """Revient à la version d'avant la dernière mise à jour (et inversement)."""
        note = self.avant()
        if note is None:
            raise ErreurMiseAJour("pas de version d'avant notée sur ce Pi")
        ancien = self._commit("HEAD")
        try:
            cible = self._commit(note["avant"])
        except ErreurMiseAJour:
            raise ErreurMiseAJour(f"version d'avant « {note['avant'][:7]} » introuvable") from None
        if cible == ancien:
            raise ErreurMiseAJour("le Pi est déjà sur la version d'avant")
        self._passer(ancien, cible, qui)
        return f"programme du Pi revenu : {ancien[:7]} → {cible[:7]}"
