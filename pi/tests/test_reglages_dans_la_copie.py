"""Tâche 25 bis : les réglages que le Pi a changés partent dans la copie de secours et reviennent.

Tout se passe dans de faux dépôts Git (dossiers provisoires) : ni Pi, ni vrai dépôt touché."""

import subprocess
import tarfile
from pathlib import Path

import pytest

from vidange.registre.fichiers_hors_git import archiver, chemin_de_reglage_sur, reglages_changes
from vidange.restauration import Chemins, restaurer
from vidange.restauration.restauration import Bilan, Options, remettre_reglages

from .conftest import DOSSIER_PI

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


def git(depot: Path, *args: str) -> None:
    subprocess.run([*GIT, *args], cwd=depot, check=True, capture_output=True)


@pytest.fixture
def depot(tmp_path):
    racine = tmp_path / "depot"
    for chemin, texte in {
        "pi/reglages/machine.yaml": "course: 100\n",
        "pi/reglages/programme.yaml": "a: 1\n",
        "fluidnc/carte1.yaml": "vitesse: 5\n",
        "docs/entrees-sorties.yaml": "broche: 1\n",
        "docs/autre.md": "texte\n",
        "pi/secrets.yaml": "jeton: x\n",
    }.items():
        fichier = racine / chemin
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(texte, encoding="utf-8")
    racine.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=racine, check=True)
    git(racine, "add", "-A")
    git(racine, "commit", "-q", "-m", "départ")
    return racine


def changer(depot: Path, chemin: str, texte: str) -> None:
    (depot / chemin).write_text(texte, encoding="utf-8")


def archive_de(tmp_path: Path, depot: Path) -> Path:
    donnees = tmp_path / "donnees"
    donnees.mkdir(exist_ok=True)
    return archiver(donnees, None, tmp_path / "fichiers-2026-11-09.tar.gz", depot)


def chemins_neufs(tmp_path: Path, depot: Path) -> Chemins:
    return Chemins(
        donnees=tmp_path / "neuf" / "donnees",
        secrets=tmp_path / "neuf" / "secrets.yaml",
        comptes=tmp_path / "neuf" / "comptes.yaml",
        secrets_exemple=DOSSIER_PI / "secrets.exemple.yaml",
        depot=depot,
    )


def test_la_liste_vient_de_git_et_se_limite_aux_reglages(depot):
    assert reglages_changes(depot) == []
    changer(depot, "pi/reglages/machine.yaml", "course: 250\n")
    changer(depot, "fluidnc/carte1.yaml", "vitesse: 9\n")
    changer(depot, "docs/entrees-sorties.yaml", "broche: 2\n")
    changer(depot, "docs/autre.md", "changé\n")  # pas un réglage
    changer(depot, "pi/secrets.yaml", "jeton: secret\n")  # jamais
    (depot / "pi/reglages/nouveau.yaml").write_text("x: 1\n")  # pas suivi par Git
    assert reglages_changes(depot) == [
        "docs/entrees-sorties.yaml",
        "fluidnc/carte1.yaml",
        "pi/reglages/machine.yaml",
    ]


def test_sans_git_la_liste_est_vide_sans_casser(tmp_path):
    assert reglages_changes(tmp_path) == []


def test_chemins_refuses():
    assert chemin_de_reglage_sur("pi/reglages/machine.yaml")
    for mauvais in (
        "pi/reglages/../secrets.yaml",
        "/etc/passwd",
        "pi/secrets.yaml",
        "pi/reglages/secrets.yaml",
        "pi/reglages/comptes.yaml",
        "pi/vidange/demarrage.py",
        "docs/autre.md",
    ):
        assert not chemin_de_reglage_sur(mauvais), mauvais


def test_l_archive_reprend_les_reglages_changes_jamais_les_secrets(tmp_path, depot):
    changer(depot, "pi/reglages/machine.yaml", "course: 250\n")
    changer(depot, "pi/secrets.yaml", "jeton: secret\n")
    archive = archive_de(tmp_path, depot)
    with tarfile.open(archive) as tar:
        assert tar.getnames() == ["reglages/pi/reglages/machine.yaml"]
        contenu = tar.extractfile("reglages/pi/reglages/machine.yaml").read()
    assert contenu == b"course: 250\n"


def test_sans_changement_l_archive_n_a_pas_de_reglages(tmp_path, depot):
    with tarfile.open(archive_de(tmp_path, depot)) as tar:
        assert tar.getnames() == []


def faux_pi_neuf(tmp_path: Path) -> Path:
    """Un Pi neuf : le dépôt tout juste cloné (valeurs de Git)."""
    neuf = tmp_path / "depot-neuf"
    subprocess.run(
        ["git", "clone", "-q", str(tmp_path / "depot"), str(neuf)], check=True, capture_output=True
    )
    return neuf


def faire_copie(tmp_path: Path, depot: Path) -> Path:
    """La « maison » : l'archive (et ce qu'il faut pour restaurer le registre)."""
    maison = tmp_path / "maison"
    maison.mkdir()
    archive = archive_de(tmp_path, depot)
    archive.rename(maison / archive.name)
    return maison


class Commandes:
    def lancer(self, commande, delai_s):
        return (1, "") if commande[0] == "tailscale" else (0, "")


def restaurer_reglages_seuls(tmp_path, depot_neuf, maison, verifier, ecraser=False):
    """Appelle les deux étapes sans registre : lit l'archive puis remet les réglages."""
    from vidange.restauration.restauration import restaurer_fichiers

    chemins = chemins_neufs(tmp_path, depot_neuf)
    bilan = Bilan()
    trouves = restaurer_fichiers(maison, chemins, [], ecraser, bilan)
    remis = remettre_reglages(chemins, trouves, ecraser, verifier, bilan)
    return bilan, remis, chemins


def test_les_reglages_reviennent_et_la_commande_le_dit(tmp_path, depot):
    changer(depot, "pi/reglages/machine.yaml", "course: 250\n")
    changer(depot, "fluidnc/carte1.yaml", "vitesse: 9\n")
    maison = faire_copie(tmp_path, depot)
    neuf = faux_pi_neuf(tmp_path)
    appels = []
    bilan, remis, _ = restaurer_reglages_seuls(
        tmp_path, neuf, maison, lambda: appels.append(1) or 0
    )
    assert (neuf / "pi/reglages/machine.yaml").read_text() == "course: 250\n"
    assert (neuf / "fluidnc/carte1.yaml").read_text() == "vitesse: 9\n"
    assert (neuf / "pi/reglages/programme.yaml").read_text() == "a: 1\n"
    assert len(remis) == 2 and len(appels) == 1
    texte = " ".join(bilan.fait)
    assert "pi/reglages/machine.yaml" in texte and "fluidnc/carte1.yaml" in texte
    assert not any("réglage" in ligne.lower() for ligne in bilan.a_la_main)


def test_un_reglage_qui_ne_passe_plus_est_mis_de_cote_les_autres_reviennent(tmp_path, depot):
    changer(depot, "pi/reglages/machine.yaml", "course: 250\n")
    changer(depot, "fluidnc/carte1.yaml", "vitesse: 9\n")
    maison = faire_copie(tmp_path, depot)
    neuf = faux_pi_neuf(tmp_path)

    def verifier() -> int:  # le code du jour refuse l'ancienne machine.yaml
        return 1 if (neuf / "pi/reglages/machine.yaml").read_text() == "course: 250\n" else 0

    bilan, remis, chemins = restaurer_reglages_seuls(tmp_path, neuf, maison, verifier)
    assert (neuf / "pi/reglages/machine.yaml").read_text() == "course: 100\n"  # comme Git
    assert (neuf / "fluidnc/carte1.yaml").read_text() == "vitesse: 9\n"  # remis quand même
    de_cote = chemins.donnees / "reglages-mis-de-cote" / "pi__reglages__machine.yaml"
    assert de_cote.read_text() == "course: 250\n"
    assert len(remis) == 1
    message = " ".join(bilan.a_la_main)
    assert "PAS remis" in message and "pi/reglages/machine.yaml" in message
    assert "vérification" in message


def test_un_fichier_disparu_de_la_version_du_jour_est_mis_de_cote(tmp_path, depot):
    changer(depot, "pi/reglages/programme.yaml", "a: 7\n")
    maison = faire_copie(tmp_path, depot)
    neuf = faux_pi_neuf(tmp_path)
    (neuf / "pi/reglages/programme.yaml").unlink()
    bilan, remis, chemins = restaurer_reglages_seuls(tmp_path, neuf, maison, lambda: 0)
    assert remis == []
    assert (chemins.donnees / "reglages-mis-de-cote" / "pi__reglages__programme.yaml").exists()
    assert "n'existe plus" in " ".join(bilan.a_la_main)


def test_un_reglage_deja_change_sur_le_pi_neuf_est_garde_sauf_ecraser(tmp_path, depot):
    changer(depot, "pi/reglages/machine.yaml", "course: 250\n")
    maison = faire_copie(tmp_path, depot)
    neuf = faux_pi_neuf(tmp_path)
    changer(neuf, "pi/reglages/machine.yaml", "course: 300\n")
    bilan, _, _ = restaurer_reglages_seuls(tmp_path, neuf, maison, lambda: 0)
    assert (neuf / "pi/reglages/machine.yaml").read_text() == "course: 300\n"
    assert "gardé tel quel" in " ".join(bilan.a_la_main)
    restaurer_reglages_seuls(tmp_path, neuf, maison, lambda: 0, ecraser=True)
    assert (neuf / "pi/reglages/machine.yaml").read_text() == "course: 250\n"


def test_verification_deja_fausse_sans_les_reglages_du_pi_ils_sont_remis(tmp_path, depot):
    changer(depot, "pi/reglages/machine.yaml", "course: 250\n")
    maison = faire_copie(tmp_path, depot)
    neuf = faux_pi_neuf(tmp_path)
    bilan, remis, _ = restaurer_reglages_seuls(tmp_path, neuf, maison, lambda: 1)
    assert (neuf / "pi/reglages/machine.yaml").read_text() == "course: 250\n"
    assert len(remis) == 1 and "échouait déjà" in " ".join(bilan.a_la_main)


def test_sans_depot_connu_rien_n_est_remis_et_c_est_dit(tmp_path, depot):
    changer(depot, "pi/reglages/machine.yaml", "course: 250\n")
    maison = faire_copie(tmp_path, depot)
    chemins = chemins_neufs(tmp_path, depot)
    chemins.depot = None
    bilan = Bilan()
    assert (
        remettre_reglages(chemins, {"pi/reglages/machine.yaml": b"x"}, False, lambda: 0, bilan)
        == []
    )
    assert "dépôt du logiciel est inconnu" in bilan.a_la_main[0]
    assert maison.exists()


def test_restauration_complete_remet_les_reglages_apres_le_reste(tmp_path, depot):
    """De bout en bout : vrai registre, archive de la copie quotidienne."""
    from datetime import datetime

    from vidange.registre import SauvegardeQuotidienne, ouvrir_registre
    from vidange.reglages import charger_reglages

    reglages = charger_reglages(DOSSIER_PI / "reglages")
    changer(depot, "pi/reglages/machine.yaml", "course: 250\n")
    donnees = tmp_path / "ancien"
    registre = ouvrir_registre(donnees)
    maison = tmp_path / "maison"
    SauvegardeQuotidienne(
        registre,
        donnees / "sauvegardes",
        reglages.programme.registre,
        horloge=lambda: datetime(2026, 11, 9, 5, 0),
        archiver_fichiers=lambda cible: archiver(donnees, None, cible, depot),
    ).faire_si_besoin()
    registre.fermer()
    maison.mkdir()
    for fichier in (donnees / "sauvegardes").iterdir():
        (maison / fichier.name).write_bytes(fichier.read_bytes())
    neuf = faux_pi_neuf(tmp_path)
    bilan = restaurer(
        chemins_neufs(tmp_path, neuf),
        reglages,
        str(maison),
        Commandes(),
        verifier=lambda: 0,
        options=Options(avec_service=False),
    )
    assert bilan.reussi, bilan.problemes
    assert (neuf / "pi/reglages/machine.yaml").read_text() == "course: 250\n"
    assert any("réglages de l'ancien Pi remis" in ligne for ligne in bilan.fait)
