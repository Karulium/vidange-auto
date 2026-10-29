"""Mises à jour des cartes ESP32 : console FluidNC (XMODEM...) et esptool, avec une fausse carte."""

import sys
from pathlib import Path

import pytest

from vidange.mises_a_jour import CarteEsp32, ErreurMiseAJour, FausseCarteEsp32, faux_programme
from vidange.mises_a_jour.console import TAILLE_BLOC, Console, completer, meme_texte
from vidange.reglages import ReglagesMajCartes

REGLAGES_FLUIDNC = b"name: portique\nboard: 6 axes\n\naxes:\n  x:\n    steps_per_mm: 80\n"


def reglages_cartes(**autres) -> ReglagesMajCartes:
    return ReglagesMajCartes.model_validate(
        {
            "vitesse_bauds": 921600,
            "adresse_programme": 0x10000,
            "fichier_reglages": "config.yaml",
            "copies_gardees": 3,
            "programmes_gardes": 2,
            "taille_max_mo": 1,
            "duree_max_esptool_s": 60,
            "delai_commande_s": 0.05,
            "delai_reponse_s": 0.2,
            **autres,
        }
    )


@pytest.fixture
def faux() -> FausseCarteEsp32:
    return FausseCarteEsp32()


@pytest.fixture
def carte(tmp_path, faux) -> CarteEsp32:
    return CarteEsp32(
        "portique",
        reglages_cartes(),
        tmp_path / "copies",
        faux.trouver_port,
        faux.ouvrir,
        faux.esptool,
    )


def ecrire(dossier, nom: str, contenu: bytes):
    chemin = dossier / nom
    chemin.write_bytes(contenu)
    return chemin


# ---------------------------------------------------------------- console


def test_completer_fait_des_blocs_entiers_de_fins_de_ligne():
    assert completer(b"") == b""
    assert completer(b"a" * TAILLE_BLOC) == b"a" * TAILLE_BLOC
    complete = completer(b"abc")
    assert len(complete) == TAILLE_BLOC and complete == b"abc" + b"\n" * (TAILLE_BLOC - 3)


def test_meme_texte_aux_espaces_et_lignes_vides_pres():
    assert meme_texte("a: 1\r\n\nb: 2  \n\n\n", "a: 1\nb: 2")
    assert not meme_texte("a: 1\nb: 2", "a: 1\nb: 3")


def test_console_version_journal_et_redemarrage(faux):
    console = Console(faux.ouvrir(), 0.05)
    assert console.version() == "3.9.4 FluidNC v3.9.4"
    assert console.erreurs_demarrage() == []
    console.redemarrer(0.2)
    assert faux.redemarrages == 1


def test_console_envoie_un_fichier_par_xmodem_meme_avec_des_blocs_refuses(faux):
    faux.blocs_a_refuser = 2
    console = Console(faux.ouvrir(), 0.05)
    contenu = REGLAGES_FLUIDNC * 5  # plusieurs blocs
    console.envoyer_fichier("config.yaml", contenu)
    recu = faux.fichiers["config.yaml"]
    assert recu.startswith(contenu) and len(recu) % TAILLE_BLOC == 0
    assert meme_texte(console.lire_fichier("config.yaml"), contenu.decode())


def test_console_carte_muette_ou_refus(faux):
    console = Console(faux.ouvrir(), 0.05)
    with pytest.raises(ErreurMiseAJour, match="refuse"):
        console.lire_fichier("absent.yaml")
    faux.programme = faux_programme("CASSE")
    with pytest.raises(ErreurMiseAJour, match="ne répond pas"):
        console.version()
    with pytest.raises(ErreurMiseAJour, match="ne répond pas après"):
        console.attendre_reponse(0.15)


# ---------------------------------------------------------------- programme


def test_ecrire_un_programme_copie_puis_ecrit_puis_verifie(tmp_path, carte, faux):
    fichier = ecrire(tmp_path, "fluidnc-3.9.5.bin", faux_programme("3.9.5 FluidNC v3.9.5"))
    resultat = carte.ecrire_programme(fichier)
    assert faux.version == "3.9.5 FluidNC v3.9.5"
    assert (resultat.avant, resultat.apres) == ("3.9.4 FluidNC v3.9.4", "3.9.5 FluidNC v3.9.5")
    assert "fluidnc-3.9.5.bin" in resultat.message
    lectures = [c for c in faux.commandes if "read-flash" in c]
    ecritures = [c for c in faux.commandes if "write-flash" in c]
    assert lectures[0][:4] == ["--port", "/dev/ttyFAUX0", "--baud", "921600"]
    assert ecritures[0][-2:] == ["0x10000", str(fichier)]
    (copie,) = carte.copies()
    assert copie.version == "3.9.4 FluidNC v3.9.4"
    assert copie.raison == "avant le programme « fluidnc-3.9.5.bin »"


def test_programme_qui_ne_repond_pas_remet_la_copie(tmp_path, carte, faux):
    fichier = ecrire(tmp_path, "mauvais.bin", faux_programme("CASSE"))
    with pytest.raises(ErreurMiseAJour, match="ancienne version est remise"):
        carte.ecrire_programme(fichier)
    assert faux.version == "3.9.4 FluidNC v3.9.4"
    assert [c[4] for c in faux.commandes] == ["read-flash", "write-flash", "write-flash"]
    assert faux.commandes[-1][-2] == "0"


def test_ecriture_ratee_remet_la_copie(tmp_path, carte, faux):
    faux.panne_esptool = "write-flash"
    fichier = ecrire(tmp_path, "bon.bin", faux_programme("3.9.5"))
    with pytest.raises(ErreurMiseAJour, match="esptool.*ancienne version est remise"):
        carte.ecrire_programme(fichier)
    assert faux.version == "3.9.4 FluidNC v3.9.4"


def test_copie_impossible_rien_n_est_ecrit(tmp_path, carte, faux):
    faux.panne_esptool = "read-flash"
    fichier = ecrire(tmp_path, "bon.bin", faux_programme("3.9.5"))
    with pytest.raises(ErreurMiseAJour, match="esptool"):
        carte.ecrire_programme(fichier)
    assert faux.version == "3.9.4 FluidNC v3.9.4"
    assert not [c for c in faux.commandes if "write-flash" in c]
    assert carte.copies() == []
    assert not list((tmp_path / "copies" / "portique").glob("*.provisoire"))


def test_fichier_qui_n_est_pas_un_programme_refuse(tmp_path, carte, faux):
    with pytest.raises(ErreurMiseAJour, match="pas un programme pour ESP32"):
        carte.ecrire_programme(ecrire(tmp_path, "texte.bin", b"bonjour"))
    with pytest.raises(ErreurMiseAJour, match="trop gros"):
        carte.ecrire_programme(ecrire(tmp_path, "gros.bin", b"\xe9" * (2 * 1024 * 1024)))
    assert faux.commandes == []


def test_carte_introuvable(tmp_path, carte, faux):
    faux.branchee = False
    fichier = ecrire(tmp_path, "bon.bin", faux_programme("3.9.5"))
    with pytest.raises(ErreurMiseAJour, match="débranchée"):
        carte.ecrire_programme(fichier)


def test_esptool_est_lance_avec_le_python_du_programme(tmp_path, faux):
    commandes = []

    def lancer(commande, duree_max_s):
        commandes.append((commande, duree_max_s))
        return faux.esptool(commande, duree_max_s)

    carte = CarteEsp32(
        "portique", reglages_cartes(), tmp_path, faux.trouver_port, faux.ouvrir, lancer
    )
    carte.sauvegarder("essai", None)
    commande, duree = commandes[0]
    assert commande[:3] == [sys.executable, "-m", "esptool"] and duree == 60


# ---------------------------------------------------------------- réglages FluidNC


def test_envoyer_les_reglages(tmp_path, carte, faux):
    fichier = ecrire(tmp_path, "portique.yaml", REGLAGES_FLUIDNC)
    resultat = carte.envoyer_reglages(fichier)
    assert faux.fichiers["config.yaml"].startswith(REGLAGES_FLUIDNC)
    assert faux.redemarrages >= 2  # copie (esptool) puis $Bye
    assert resultat.apres == "3.9.4 FluidNC v3.9.4"
    assert carte.copies()[0].raison == "avant les réglages « portique.yaml »"


def test_reglages_avec_erreur_au_demarrage_remet_la_copie(tmp_path, carte, faux):
    faux.fichiers["config.yaml"] = b"name: ancien\n"
    fichier = ecrire(tmp_path, "portique.yaml", b"name: ERREUR\n")
    with pytest.raises(ErreurMiseAJour, match="Configuration is invalid.*ancienne version"):
        carte.envoyer_reglages(fichier)
    assert faux.fichiers["config.yaml"] == b"name: ancien\n"


def test_reglages_refuses_si_la_carte_ne_repond_pas(tmp_path, carte, faux):
    faux.programme = faux_programme("CASSE")
    fichier = ecrire(tmp_path, "portique.yaml", REGLAGES_FLUIDNC)
    with pytest.raises(ErreurMiseAJour, match="écrire d'abord son programme"):
        carte.envoyer_reglages(fichier)
    assert faux.commandes == []


@pytest.mark.parametrize(
    "contenu, message",
    [
        ("nom: é\n".encode(), "sans accents"),
        (b"- a\n- b\n", "pas de réglages"),
        (b"a: [\n", "YAML"),
    ],
)
def test_fichier_de_reglages_illisible(tmp_path, carte, contenu, message):
    with pytest.raises(ErreurMiseAJour, match=message):
        carte.envoyer_reglages(ecrire(tmp_path, "portique.yaml", contenu))


@pytest.mark.parametrize(
    "contenu",
    [
        b"# ATTENTION : EXEMPLE.\nname: portique\n",
        b'name: "Vidange carte 1 (EXEMPLE)"\n',
        b"axes:\n  x:\n    # EXEMPLES de broches\n    steps_per_mm: 80\n",
    ],
)
def test_fichier_d_exemple_jamais_envoye(tmp_path, carte, faux, contenu):
    with pytest.raises(ErreurMiseAJour, match="fichier d'EXEMPLE.*enlever chaque mot EXEMPLE"):
        carte.envoyer_reglages(ecrire(tmp_path, "portique.yaml", contenu))
    assert faux.commandes == [] and carte.copies() == []  # rien touché sur la carte


def test_vrai_fichier_d_exemple_du_depot_refuse_avec_ses_lignes(tmp_path, carte, faux):
    # Le fichier du dépôt a aussi des accents : le refus EXEMPLE passe avant, son message est clair.
    fichier = Path(__file__).parents[2] / "fluidnc" / "mycelium_lavage.yaml"
    with pytest.raises(ErreurMiseAJour, match=r"« mycelium_lavage.yaml ».*ligne 3, 19, 20"):
        carte.envoyer_reglages(fichier)
    assert faux.commandes == []


def test_le_mot_exemple_en_minuscules_ne_bloque_pas(tmp_path, carte, faux):
    contenu = REGLAGES_FLUIDNC + b"# par exemple : 80 pas par mm, contre-exemple\n"
    carte.envoyer_reglages(ecrire(tmp_path, "portique.yaml", contenu))
    assert faux.fichiers["config.yaml"].startswith(contenu)


def test_fichier_de_reglages_absent(tmp_path, carte):
    with pytest.raises(ErreurMiseAJour, match="pas de fichier de réglages"):
        carte.envoyer_reglages(tmp_path / "absent.yaml")


# ---------------------------------------------------------------- retour en arrière


def test_revenir_a_la_copie_d_avant(tmp_path, carte, faux):
    carte.ecrire_programme(ecrire(tmp_path, "v5.bin", faux_programme("3.9.5")))
    resultat = carte.revenir()
    assert faux.version == "3.9.4 FluidNC v3.9.4" == resultat.apres
    # La mémoire d'avant le retour est gardée aussi : on peut revenir au retour.
    copies = carte.copies()
    assert [c.version for c in copies] == ["3.9.5", "3.9.4 FluidNC v3.9.4"]
    carte.revenir(copies[0].nom)
    assert faux.version == "3.9.5"


def test_revenir_sans_copie_ou_copie_inconnue(carte):
    with pytest.raises(ErreurMiseAJour, match="aucune copie"):
        carte.revenir()
    with pytest.raises(ErreurMiseAJour, match="pas de copie « x »"):
        carte.revenir("x")


def test_revenir_meme_si_la_copie_de_secours_rate(tmp_path, carte, faux):
    carte.ecrire_programme(ecrire(tmp_path, "v5.bin", faux_programme("3.9.5")))
    faux.panne_esptool = "read-flash"
    carte.revenir()
    assert faux.version == "3.9.4 FluidNC v3.9.4"


def test_seules_les_dernieres_copies_sont_gardees(tmp_path, carte, faux):
    for numero in range(5):
        carte.sauvegarder(f"essai {numero}", None)
    assert [c.raison for c in carte.copies()] == ["essai 4", "essai 3", "essai 2"]
    assert len(list((tmp_path / "copies" / "portique").glob("*.bin"))) == 3


# ---------------------------------------------------------------- outil vidange-maj


def test_outil_avec_une_fausse_carte(reglages, tmp_path, capsys):
    from vidange.mises_a_jour.outil import main

    debut = ["--faux", "--reglages", str(reglages), "--donnees", str(tmp_path / "donnees")]
    assert main([*debut, "version", "portique"]) == 0
    assert "3.9.4 FluidNC v3.9.4" in capsys.readouterr().out
    fichier = ecrire(tmp_path, "v5.bin", faux_programme("3.9.5"))
    assert main([*debut, "programme", "portique", str(fichier)]) == 0
    sortie = capsys.readouterr().out
    assert "Copie de toute la mémoire" in sortie and "Réussi : programme « v5.bin »" in sortie
    assert main([*debut, "copies", "portique"]) == 0
    assert "avant le programme « v5.bin »" in capsys.readouterr().out
    assert main([*debut, "programme", "portique", str(tmp_path / "absent.bin")]) == 1
    assert "ÉCHEC" in capsys.readouterr().out
    assert main([*debut, "version", "inconnue"]) == 2


def test_reglages_des_mises_a_jour_verifies():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="delai_reponse_s"):
        reglages_cartes(delai_reponse_s=0.01)
    with pytest.raises(ValidationError, match="fichier_reglages"):
        reglages_cartes(fichier_reglages="../config.yaml")
