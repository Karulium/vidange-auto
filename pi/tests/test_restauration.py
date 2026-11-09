"""Tests de la sauvegarde des fichiers hors Git et de la restauration d'un Pi neuf (tâche 25).

Tout se passe dans des dossiers provisoires, avec une fausse « maison » (un dossier) et de fausses
commandes du système (rsync, systemctl, tailscale) : aucun Pi n'est nécessaire.
"""

import shutil
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

import pytest

from vidange.comptes import Comptes, Role
from vidange.demarrage import NOM_CARNET, principal
from vidange.mises_a_jour.pi import NOM_NOTE
from vidange.registre import NOM_BASE, Registre, SauvegardeQuotidienne, ouvrir_registre
from vidange.registre.fichiers_hors_git import archiver, fichiers_a_garder
from vidange.reglages import charger_reglages
from vidange.restauration import Chemins, ErreurRestauration, restaurer
from vidange.restauration.outil import lancer_restauration
from vidange.restauration.restauration import Options, source_par_defaut

from .conftest import DOSSIER_PI

REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MOT = "une phrase facile a retenir"


class FausseSource:
    """Un ancien Pi : son registre, ses fichiers, ses photos, ses comptes."""

    def __init__(self, racine: Path) -> None:
        self.donnees = racine / "ancien" / "donnees"
        self.comptes = racine / "ancien" / "comptes.yaml"
        self.donnees.mkdir(parents=True)
        self.registre = ouvrir_registre(self.donnees)
        cycle = self.registre.commencer_cycle("vidange", fut="F3")
        self.registre.finir_cycle(cycle)
        (self.donnees / "angles.json").write_text('{"griffe": 90}', encoding="utf-8")
        (self.donnees / "entonnoir.json").write_text('{"vide": false}', encoding="utf-8")
        (self.donnees / NOM_CARNET).write_text('{"module": "vidange"}', encoding="utf-8")
        (self.donnees / "photos" / "2026-10-27").mkdir(parents=True)
        (self.donnees / "photos" / "2026-10-27" / "a.jpg").write_bytes(b"jpeg")
        Comptes(self.comptes).ajouter("gael", Role.KARULIUM, MOT)
        # Des choses qui ne doivent PAS partir dans l'archive.
        (self.donnees / "journal").mkdir()
        (self.donnees / "journal" / "vidange.log").write_text("journal", encoding="utf-8")

    def sauvegarder_vers(self, maison: Path, jour=datetime(2026, 10, 27, 5, 0)) -> None:
        """Fait la copie du jour puis l'envoie dans « la maison » (un simple dossier)."""
        sauvegarde = SauvegardeQuotidienne(
            self.registre,
            self.donnees / "sauvegardes",
            REGLAGES.programme.registre,
            horloge=lambda: jour,
            archiver_fichiers=lambda cible: archiver(self.donnees, self.comptes, cible),
        )
        sauvegarde.faire_si_besoin()
        maison.mkdir(parents=True, exist_ok=True)
        for fichier in (self.donnees / "sauvegardes").iterdir():
            shutil.copy(fichier, maison / fichier.name)
        shutil.copytree(self.donnees / "photos", maison / "photos", dirs_exist_ok=True)


class FausseCommandes:
    def __init__(self, maison: Path | None = None) -> None:
        self.appels: list[list[str]] = []
        self.maison = maison
        self.reponses: dict[str, tuple[int, str]] = {}

    def lancer(self, commande: list[str], delai_s: float) -> tuple[int, str]:
        self.appels.append(commande)
        if commande[0] == "rsync" and self.maison is not None and "rsync" not in self.reponses:
            shutil.copytree(self.maison, commande[-1], dirs_exist_ok=True)
            return 0, ""
        return self.reponses.get(commande[0], (0, ""))


@pytest.fixture
def ancien(tmp_path):
    source = FausseSource(tmp_path)
    maison = tmp_path / "maison"
    source.sauvegarder_vers(maison)
    yield source, maison
    source.registre.fermer()


@pytest.fixture
def neuf(tmp_path):
    return Chemins(
        donnees=tmp_path / "neuf" / "donnees",
        secrets=tmp_path / "neuf" / "etc" / "secrets.yaml",
        comptes=tmp_path / "neuf" / "etc" / "comptes.yaml",
        secrets_exemple=DOSSIER_PI / "secrets.exemple.yaml",
    )


def rien(*_):
    pass


# ---------------------------------------------------------------- la copie de secours


def test_l_archive_reprend_les_petits_fichiers_et_les_comptes_mais_pas_les_secrets(ancien):
    source, maison = ancien
    (archive,) = maison.glob("fichiers-*.tar.gz")
    with tarfile.open(archive) as tar:
        noms = sorted(tar.getnames())
    assert noms == [
        "comptes.yaml",
        "donnees/angles.json",
        "donnees/entonnoir.json",
        f"donnees/{NOM_CARNET}",
    ]
    assert all(not n.startswith("donnees/registre") for n in noms)
    assert not any("secrets" in n for n in noms)


def test_fichiers_a_garder_ignore_registre_dossiers_et_temporaires(tmp_path):
    for nom in ("registre.sqlite", "registre.sqlite-wal", "x.tmp", ".cache", "ok.json"):
        (tmp_path / nom).write_text("x", encoding="utf-8")
    (tmp_path / "photos").mkdir()
    assert [f.name for f in fichiers_a_garder(tmp_path)] == ["ok.json"]


def test_l_archive_est_privee(ancien):
    (archive,) = ancien[1].glob("fichiers-*.tar.gz")
    source_archive = next((ancien[0].donnees / "sauvegardes").glob("fichiers-*.tar.gz"))
    assert source_archive.stat().st_mode & 0o077 == 0
    assert archive.exists()


def test_les_vieilles_archives_sont_effacees_comme_les_copies(ancien):
    source, _ = ancien
    sauvegarde = SauvegardeQuotidienne(
        source.registre,
        source.donnees / "sauvegardes",
        REGLAGES.programme.registre.model_copy(update={"copies_gardees": 2}),
        horloge=lambda: datetime(2026, 10, 30, 5, 0),
        archiver_fichiers=lambda cible: archiver(source.donnees, source.comptes, cible),
    )
    for jour in (28, 29, 30):
        sauvegarde.sauvegarder(source.donnees / "sauvegardes" / f"registre-2026-10-{jour}.sqlite")
    noms = sorted(f.name for f in (source.donnees / "sauvegardes").iterdir())
    assert [n for n in noms if n.startswith("registre-")] == [
        "registre-2026-10-29.sqlite",
        "registre-2026-10-30.sqlite",
    ]
    assert len([n for n in noms if n.startswith("fichiers-")]) == 2


def test_une_archive_ratee_ne_gache_pas_la_copie_du_registre(ancien):
    source, _ = ancien

    def ratee(_cible: Path) -> Path:
        raise OSError("disque plein")

    sauvegarde = SauvegardeQuotidienne(
        source.registre,
        source.donnees / "sauvegardes",
        REGLAGES.programme.registre,
        horloge=lambda: datetime(2026, 10, 31, 5, 0),
        archiver_fichiers=ratee,
    )
    assert sauvegarde.faire_si_besoin() is not None


def test_l_archive_part_a_la_maison_et_remplace_la_precedente(ancien):
    from vidange.envois import mettre_en_file_secours

    source, _ = ancien
    secours = REGLAGES.programme.envois.secours.model_copy(
        update={"commande": ["rsync", "{chemin}", "maison:"]}
    )
    envoyes = []
    ajouter = mettre_en_file_secours(source.registre, secours, source.donnees)
    sauvegarde = SauvegardeQuotidienne(
        source.registre,
        source.donnees / "sauvegardes",
        REGLAGES.programme.registre,
        horloge=lambda: datetime(2026, 11, 1, 5, 0),
        apres_copie=lambda c: (envoyes.append(c.name), ajouter(c)),
        archiver_fichiers=lambda cible: archiver(source.donnees, source.comptes, cible),
    )
    sauvegarde.faire_si_besoin()
    assert envoyes == ["registre-2026-11-01.sqlite", "fichiers-2026-11-01.tar.gz"]
    objets = [e["objet"] for e in source.registre.lire("SELECT * FROM envois ORDER BY id")]
    # La copie du registre, l'archive, et les photos une seule fois.
    assert objets.count("photos") == 1
    assert "sauvegardes/fichiers-2026-11-01.tar.gz" in objets


def test_les_fichiers_a_ne_pas_restaurer_existent_vraiment():
    ignores = REGLAGES.programme.registre.restauration_ignore
    assert NOM_CARNET in ignores and NOM_NOTE in ignores
    from vidange.fiabilite.marche import NOM_FICHIER

    assert NOM_FICHIER in ignores


# ---------------------------------------------------------------- la restauration


def test_restauration_complete_sur_un_pi_neuf(ancien, neuf):
    source, maison = ancien
    commandes = FausseCommandes()
    commandes.reponses["tailscale"] = (1, "pas installé")
    bilan = restaurer(
        neuf,
        REGLAGES,
        str(maison),
        commandes,
        verifier=lambda: 0,
        options=Options(attente_service_s=0),
        donner_au_programme=rien,
    )
    assert bilan.reussi, bilan.problemes
    # Le registre est revenu, avec son cycle.
    registre = Registre(neuf.donnees / NOM_BASE, neuf.donnees / "photos")
    assert registre.compter()["cycles"] == 1
    registre.fermer()
    # Les fichiers appris sont revenus, pas l'état du cycle en cours.
    assert (neuf.donnees / "angles.json").read_text(encoding="utf-8") == '{"griffe": 90}'
    assert (neuf.donnees / "entonnoir.json").exists()
    assert not (neuf.donnees / NOM_CARNET).exists()
    # Les comptes sont revenus et marchent.
    assert Comptes(neuf.comptes).verifier("gael", MOT) is not None
    assert neuf.comptes.stat().st_mode & 0o077 == 0
    # Les photos aussi.
    assert (neuf.donnees / "photos" / "2026-10-27" / "a.jpg").read_bytes() == b"jpeg"
    # Les secrets ne sont pas dans la sauvegarde : un modèle vide est posé, en 600.
    assert neuf.secrets.exists() and neuf.secrets.stat().st_mode & 0o077 == 0
    # Rien de provisoire ne reste.
    assert not (neuf.donnees / ".restauration").exists()
    # Le service est lancé et vérifié.
    assert ["systemctl", "enable", "--now", "vidange"] in commandes.appels
    assert ["systemctl", "is-active", "--quiet", "vidange"] in commandes.appels
    # Et le bilan dit ce qui reste à la main.
    a_faire = " ".join(bilan.a_la_main)
    assert "secrets" in a_faire and "Tailscale" in a_faire and "ATTEND le Go" in a_faire


def test_un_pi_qui_a_deja_un_registre_n_est_pas_ecrase(ancien, neuf):
    _, maison = ancien
    neuf.donnees.mkdir(parents=True)
    ouvrir_registre(neuf.donnees).fermer()
    with pytest.raises(ErreurRestauration, match="--ecraser"):
        restaurer(neuf, REGLAGES, str(maison), FausseCommandes(), lambda: 0)
    # Avec --ecraser, l'ancien est mis de côté (jamais perdu).
    bilan = restaurer(
        neuf,
        REGLAGES,
        str(maison),
        FausseCommandes(),
        lambda: 0,
        Options(ecraser=True, avec_service=False),
        rien,
    )
    assert (neuf.donnees / f"{NOM_BASE}.avant-restauration").exists()
    assert any("mis de côté" in ligne for ligne in bilan.fait)


def test_la_copie_la_plus_recente_est_abimee_on_prend_la_precedente(ancien, neuf):
    source, maison = ancien
    source.sauvegarder_vers(maison, datetime(2026, 10, 28, 5, 0))
    (maison / "registre-2026-10-28.sqlite").write_bytes(b"pas une base" * 100)
    bilan = restaurer(
        neuf, REGLAGES, str(maison), FausseCommandes(), lambda: 0, Options(avec_service=False), rien
    )
    assert any("registre-2026-10-28" in p and "abîmée" in p for p in bilan.problemes)
    assert any("2026-10-27" in ligne for ligne in bilan.fait)
    assert (neuf.donnees / NOM_BASE).stat().st_size > 0


def test_aucune_copie_aucune_restauration(tmp_path, neuf):
    vide = tmp_path / "vide"
    vide.mkdir()
    with pytest.raises(ErreurRestauration, match="aucune copie du registre"):
        restaurer(neuf, REGLAGES, str(vide), FausseCommandes(), lambda: 0)
    with pytest.raises(ErreurRestauration, match="n'est pas un dossier"):
        restaurer(neuf, REGLAGES, str(tmp_path / "absent"), FausseCommandes(), lambda: 0)


def test_archive_piegee_refusee(ancien, neuf, tmp_path):
    _, maison = ancien
    for archive in maison.glob("fichiers-*.tar.gz"):
        archive.unlink()
    mechant = tmp_path / "mechant.txt"
    mechant.write_text("x", encoding="utf-8")
    with tarfile.open(maison / "fichiers-2026-10-27.tar.gz", "w:gz") as tar:
        tar.add(mechant, arcname="../../evasion.txt")
        tar.add(mechant, arcname="/etc/evasion.txt")
        tar.add(mechant, arcname="donnees/../../evasion2.txt")
        tar.add(mechant, arcname="donnees/bon.json")
    bilan = restaurer(
        neuf, REGLAGES, str(maison), FausseCommandes(), lambda: 0, Options(avec_service=False), rien
    )
    assert (neuf.donnees / "bon.json").exists()
    assert len([p for p in bilan.problemes if "refusé" in p]) == 3
    assert not list(tmp_path.rglob("evasion*"))


def test_sans_archive_il_faut_recreer_un_compte(ancien, neuf):
    _, maison = ancien
    for archive in maison.glob("fichiers-*.tar.gz"):
        archive.unlink()
    bilan = restaurer(
        neuf, REGLAGES, str(maison), FausseCommandes(), lambda: 0, Options(avec_service=False), rien
    )
    assert any("pas d'archive" in p for p in bilan.problemes)
    assert not bilan.reussi


def test_copie_distante_par_rsync(ancien, neuf):
    _, maison = ancien
    commandes = FausseCommandes(maison)
    bilan = restaurer(
        neuf,
        REGLAGES,
        "vidange@maison:sauvegardes-vidange",
        commandes,
        lambda: 0,
        Options(avec_service=False),
        rien,
    )
    assert bilan.reussi, bilan.problemes
    rsync = commandes.appels[0]
    assert rsync[:3] == ["rsync", "-a", "--partial"]
    assert rsync[3] == "vidange@maison:sauvegardes-vidange/"
    assert (neuf.donnees / NOM_BASE).exists()
    assert not (neuf.donnees / ".restauration").exists()


def test_rsync_en_echec_dit_quoi_verifier(neuf):
    commandes = FausseCommandes()
    commandes.reponses["rsync"] = (255, "Permission denied (publickey)")
    with pytest.raises(ErreurRestauration, match="(?s)Permission denied.*Tailscale.*clé SSH"):
        restaurer(neuf, REGLAGES, "vidange@maison:x", commandes, lambda: 0)
    assert not (neuf.donnees / ".restauration").exists()


def test_verification_ou_service_en_echec_est_dit(ancien, neuf):
    _, maison = ancien
    commandes = FausseCommandes()
    commandes.reponses["systemctl"] = (3, "inactive")
    bilan = restaurer(
        neuf,
        REGLAGES,
        str(maison),
        commandes,
        verifier=lambda: 2,
        options=Options(attente_service_s=0),
        donner_au_programme=rien,
        dormir=rien,
    )
    assert not bilan.reussi
    texte = " ".join(bilan.problemes)
    assert "vérification des réglages a échoué" in texte and "service" in texte


def test_photos_seulement(ancien, neuf):
    _, maison = ancien
    bilan = restaurer(
        neuf,
        REGLAGES,
        str(maison),
        FausseCommandes(),
        lambda: 1 / 0,  # pas appelée
        Options(photos_seulement=True),
    )
    assert bilan.reussi
    assert (neuf.donnees / "photos" / "2026-10-27" / "a.jpg").exists()
    assert not (neuf.donnees / NOM_BASE).exists()


def test_secrets_deja_la_on_dit_seulement_ce_qui_est_vide(ancien, neuf):
    _, maison = ancien
    neuf.secrets.parent.mkdir(parents=True)
    neuf.secrets.write_text('jeton_culture: "abc"\n', encoding="utf-8")
    neuf.secrets.chmod(0o600)
    bilan = restaurer(
        neuf, REGLAGES, str(maison), FausseCommandes(), lambda: 0, Options(avec_service=False), rien
    )
    assert neuf.secrets.read_text(encoding="utf-8") == 'jeton_culture: "abc"\n'
    assert any(
        "jeton_github" in ligne and "jeton_culture" not in ligne for ligne in bilan.a_la_main
    )


def test_la_source_par_defaut_est_la_maison_des_copies_quotidiennes():
    secours = REGLAGES.programme.envois.secours.model_copy(
        update={"commande": ["rsync", "{chemin}", "vidange@maison:sauvegardes-vidange/"]}
    )
    programme = REGLAGES.programme.model_copy(
        update={"envois": REGLAGES.programme.envois.model_copy(update={"secours": secours})}
    )
    assert source_par_defaut(REGLAGES.model_copy(update={"programme": programme})) == (
        "vidange@maison:sauvegardes-vidange/"
    )
    assert source_par_defaut(REGLAGES) is None  # le dépôt n'a pas encore d'adresse de maison


# ---------------------------------------------------------------- la commande « vidange restaurer »


def arguments_cli(tmp_path, maison, *en_plus):
    return [
        "--depuis", str(maison),
        "--reglages", str(DOSSIER_PI / "reglages"),
        "--entrees-sorties", str(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"),
        "--secrets", str(tmp_path / "cli" / "secrets.yaml"),
        "--donnees", str(tmp_path / "cli" / "donnees"),
        *en_plus,
    ]  # fmt: skip


def test_commande_restaurer_de_bout_en_bout(ancien, tmp_path, capsys):
    _, maison = ancien
    commandes = FausseCommandes()
    code = lancer_restauration(
        arguments_cli(tmp_path, maison, "--sans-service"), commandes=commandes, root=False
    )
    sortie = capsys.readouterr().out
    assert code == 0, sortie
    assert "FAIT :" in sortie and "IL RESTE À FAIRE À LA MAIN :" in sortie
    # La vraie vérification des réglages a tourné sur les fichiers restaurés.
    assert (tmp_path / "cli" / "donnees" / NOM_BASE).exists()
    assert (tmp_path / "cli" / "comptes.yaml").exists()
    assert "réglages vérifiés" in sortie
    # Le Pi restauré démarre : « vidange --verifier » est content des comptes restaurés.
    assert (
        principal(
            [
                "--verifier",
                "--reglages",
                str(DOSSIER_PI / "reglages"),
                "--entrees-sorties",
                str(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"),
                "--secrets",
                str(tmp_path / "cli" / "secrets.yaml"),
                "--donnees",
                str(tmp_path / "cli" / "donnees"),
            ]  # fmt: skip
        )
        == 0
    )


def test_commande_restaurer_sans_source_dit_quoi_faire(tmp_path, capsys):
    code = lancer_restauration(arguments_cli(tmp_path, "")[2:], commandes=FausseCommandes())
    assert code == 2
    assert "--depuis" in capsys.readouterr().err


def test_vidange_restaurer_passe_par_la_commande_principale(ancien, tmp_path, capsys):
    _, maison = ancien
    avant = tmp_path / "cli"
    assert (
        principal(["restaurer", "--depuis", str(tmp_path / "absent"), "--donnees", str(avant)]) == 2
    )
    assert "n'est pas un dossier" in capsys.readouterr().err


# ---------------------------------------------------------------- le script d'installation


SCRIPT = DOSSIER_PI / "systeme" / "restaurer.sh"


def test_le_script_est_du_bash_valide():
    assert subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True).returncode == 0


def test_le_script_a_blanc_liste_toutes_les_etapes(tmp_path):
    env = {
        "VIDANGE_A_BLANC": "1",
        "VIDANGE_CONFIG_PI": str(tmp_path / "config.txt"),
        "PATH": "/usr/bin:/bin",
    }
    fin = subprocess.run(
        ["bash", str(SCRIPT), "--depuis", "vidange@maison:sauvegardes-vidange/", "--sans-photos"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert fin.returncode == 0, fin.stderr
    sortie = fin.stdout
    for attendu in (
        "apt-get install -y git python3-venv rsync",
        "useradd --system",
        "raspi-config nonint do_i2c 0",
        "dtoverlay=uart2-pi5",
        "pip install -e",
        "vidange.service",
        "sudoers.d/vidange-extinction",
        "chien-de-garde.conf",
        "rsync -a --partial",
        "restaurer --depuis /var/lib/vidange/.copie-recue --sans-photos",
    ):
        assert attendu in sortie, attendu
    assert not (tmp_path / "config.txt").exists()  # à blanc : rien n'est écrit


def test_le_script_ne_contient_aucun_secret():
    texte = SCRIPT.read_text(encoding="utf-8")
    for interdit in ("ghp_", "github_pat_", "password=", "cle_api"):
        assert interdit not in texte
