"""Mise à jour du programme du Pi : avec un vrai dépôt Git d'essai (« GitHub » est un dossier)."""

import json
import os
import subprocess

import pytest

from vidange.mises_a_jour import ErreurMiseAJour, ProgrammePi
from vidange.mises_a_jour.pi import entete_jeton
from vidange.reglages import ReglagesMajPi

PROGRAMME_YAML = "".join(f"reglage_{numero}: {numero}\n" for numero in range(20))
IDENTITE = {
    "GIT_AUTHOR_NAME": "essai",
    "GIT_AUTHOR_EMAIL": "essai@exemple",
    "GIT_COMMITTER_NAME": "essai",
    "GIT_COMMITTER_EMAIL": "essai@exemple",
}


def git(dossier, *arguments) -> str:
    fini = subprocess.run(
        ["git", *arguments],
        cwd=dossier,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **IDENTITE},
    )
    return fini.stdout.strip()


class Depots:
    """« GitHub » (dépôt nu), la copie de travail des sessions, et la copie du Pi."""

    def __init__(self, dossier) -> None:
        self.github = dossier / "github.git"
        self.travail = dossier / "travail"
        self.pi = dossier / "pi"
        git(dossier, "init", "--quiet", "--bare", "-b", "main", str(self.github))
        git(dossier, "clone", "--quiet", str(self.github), str(self.travail))
        git(self.travail, "checkout", "--quiet", "-b", "main")
        self.ecrire("pi/reglages/programme.yaml", PROGRAMME_YAML, "Tâche 1")
        git(dossier, "clone", "--quiet", str(self.github), str(self.pi))

    def ecrire(self, chemin: str, contenu: str, titre: str) -> str:
        fichier = self.travail / chemin
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(contenu)
        git(self.travail, "add", "-A")
        git(self.travail, "commit", "--quiet", "-m", titre)
        git(self.travail, "push", "--quiet", "origin", "main")
        return git(self.travail, "rev-parse", "HEAD")

    def tete_du_pi(self) -> str:
        return git(self.pi, "rev-parse", "HEAD")

    def reglages_du_pi(self) -> str:
        return (self.pi / "pi/reglages/programme.yaml").read_text()

    def changer_sur_le_pi(self, ancien: str, nouveau: str) -> None:
        fichier = self.pi / "pi/reglages/programme.yaml"
        fichier.write_text(fichier.read_text().replace(ancien, nouveau))


class Appels:
    def __init__(self) -> None:
        self.liste: list[str] = []
        self.verification_ratee = False

    def installer(self) -> None:
        self.liste.append("installer")

    def verifier(self) -> None:
        self.liste.append("verifier")
        if self.verification_ratee:
            raise ErreurMiseAJour("« python -m vidange » a échoué (code 2) : réglage inconnu")


@pytest.fixture
def depots(tmp_path) -> Depots:
    return Depots(tmp_path)


@pytest.fixture
def appels() -> Appels:
    return Appels()


@pytest.fixture
def pi(tmp_path, depots, appels) -> ProgrammePi:
    reglages = ReglagesMajPi(depot="origin", branche="main", duree_max_s=60)
    return ProgrammePi(
        reglages, depots.pi, tmp_path / "maj", installer=appels.installer, verifier=appels.verifier
    )


def test_chercher_et_installer(depots, pi, appels):
    ancien = depots.tete_du_pi()
    assert pi.chercher() == []
    assert pi.version()["titre"] == "Tâche 1"
    nouveau = depots.ecrire("pi/vidange/nouveau.py", "x = 1\n", "Tâche 2 — nouveauté")
    (trouvee,) = pi.chercher()
    assert (trouvee["commit"], trouvee["titre"]) == (nouveau, "Tâche 2 — nouveauté")
    assert depots.tete_du_pi() == ancien  # chercher ne change rien

    message = pi.installer("page web")
    assert depots.tete_du_pi() == nouveau
    assert (depots.pi / "pi/vidange/nouveau.py").exists()
    assert appels.liste == ["installer", "verifier"]
    assert ancien[:7] in message and nouveau[:7] in message
    note = pi.avant()
    assert (note["avant"], note["apres"], note["qui"]) == (ancien, nouveau, "page web")


def test_deja_a_jour(pi, appels):
    with pytest.raises(ErreurMiseAJour, match="déjà à jour"):
        pi.installer("page web")
    assert appels.liste == []


def test_les_reglages_changes_sur_le_pi_sont_gardes(depots, pi):
    depots.changer_sur_le_pi("reglage_2: 2", "reglage_2: 222")
    nouveau = PROGRAMME_YAML + "nouvelle_partie: 1\n"
    depots.ecrire("pi/reglages/programme.yaml", nouveau, "Tâche 2")
    pi.installer("page web")
    reglages = depots.reglages_du_pi()
    assert "reglage_2: 222" in reglages and "nouvelle_partie: 1" in reglages
    assert git(depots.pi, "stash", "list") == ""


def test_reglage_change_aux_memes_lignes_refuse_sans_rien_changer(depots, pi, appels):
    ancien = depots.tete_du_pi()
    depots.changer_sur_le_pi("reglage_2: 2", "reglage_2: 222")
    depots.ecrire(
        "pi/reglages/programme.yaml", PROGRAMME_YAML.replace("reglage_2: 2", "reglage_2: 3"), "T2"
    )
    with pytest.raises(ErreurMiseAJour, match="mêmes lignes.*programme.yaml"):
        pi.installer("page web")
    assert depots.tete_du_pi() == ancien
    assert "reglage_2: 222" in depots.reglages_du_pi()
    assert git(depots.pi, "stash", "list") == ""
    assert appels.liste == []


def test_nouvelle_version_qui_ne_passe_pas_la_verification(depots, pi, appels):
    ancien = depots.tete_du_pi()
    depots.changer_sur_le_pi("reglage_5: 5", "reglage_5: 55")
    depots.ecrire("pi/vidange/nouveau.py", "x = 1\n", "Tâche 2")
    appels.verification_ratee = True
    with pytest.raises(ErreurMiseAJour, match="ne passe pas.*réglage inconnu.*version d'avant"):
        pi.installer("page web")
    assert depots.tete_du_pi() == ancien
    assert not (depots.pi / "pi/vidange/nouveau.py").exists()
    assert "reglage_5: 55" in depots.reglages_du_pi()
    # Le programme d'avant est réinstallé.
    assert appels.liste == ["installer", "verifier", "installer"]
    assert pi.avant() is None


def test_revenir_a_la_version_d_avant_et_inversement(depots, pi):
    ancien = depots.tete_du_pi()
    nouveau = depots.ecrire("pi/vidange/nouveau.py", "x = 1\n", "Tâche 2")
    with pytest.raises(ErreurMiseAJour, match="pas de version d'avant"):
        pi.revenir("page web")
    pi.installer("page web")
    depots.changer_sur_le_pi("reglage_7: 7", "reglage_7: 77")
    pi.revenir("page web")
    assert depots.tete_du_pi() == ancien
    assert "reglage_7: 77" in depots.reglages_du_pi()
    assert pi.avant()["avant"] == nouveau
    pi.revenir("page web")
    assert depots.tete_du_pi() == nouveau


def test_le_pi_n_a_pas_ses_propres_versions(depots, pi):
    (depots.pi / "local.txt").write_text("à moi\n")
    git(depots.pi, "add", "local.txt")
    git(depots.pi, "commit", "--quiet", "-m", "changement enregistré sur le Pi")
    depots.ecrire("pi/vidange/nouveau.py", "x = 1\n", "Tâche 2")
    with pytest.raises(ErreurMiseAJour, match="n'est pas dans « origin/main »"):
        pi.installer("page web")


def test_le_jeton_passe_par_les_variables_jamais_dans_la_commande(tmp_path, depots):
    vus = []

    def lancer(commande, duree_max_s, dossier=None, variables=None):
        vus.append((commande, variables or {}))
        return ""

    reglages = ReglagesMajPi(depot="origin", branche="main", duree_max_s=60)
    pi = ProgrammePi(reglages, depots.pi, tmp_path, jeton="secret-123", lancer=lancer)
    pi.chercher()
    telechargement, *autres = vus
    assert "fetch" in telechargement[0]
    assert not any("secret" in morceau for commande, _ in vus for morceau in commande)
    assert (
        telechargement[1]["GIT_CONFIG_VALUE_0"] == entete_jeton("secret-123")["GIT_CONFIG_VALUE_0"]
    )
    assert all("GIT_CONFIG_VALUE_0" not in variables for _, variables in autres)


def test_vraie_installation_et_verification_lancees_avec_ce_python(tmp_path, depots):
    import sys

    vus = []

    def lancer(commande, duree_max_s, dossier=None, variables=None):
        vus.append((commande, dossier))
        return ""

    reglages = ReglagesMajPi(depot="origin", branche="main", duree_max_s=60)
    pi = ProgrammePi(reglages, depots.pi, tmp_path, lancer=lancer)
    pi._installer()
    pi._verifier()
    (installer, dossier), (verifier, _) = vus
    assert installer[:5] == [sys.executable, "-m", "pip", "install", "--quiet"]
    assert dossier == str(depots.pi / "pi")
    assert verifier == [sys.executable, "-m", "vidange", "--verifier"]


def test_note_illisible(tmp_path, pi):
    pi.note.parent.mkdir(parents=True)
    pi.note.write_text("{pas du json")
    assert pi.avant() is None
    pi.note.write_text(json.dumps({"avant": "0" * 40}))
    with pytest.raises(ErreurMiseAJour, match="introuvable"):
        pi.revenir("page web")
