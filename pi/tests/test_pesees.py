"""Cartes de pesée du bus RS485 : table de registres, lecture par le Materiel, tour du Pi,
réglages, fabrication des réglages du programme des cartes, outil d'essai."""

import threading
from pathlib import Path

import pytest

from vidange.demarrage import constats_pesees
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.griffe.bras import CapteurForce, G
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel, PeseeMuette
from vidange.materiel.carte_pesee import MesureCarte, decoder, encoder
from vidange.pesees import entete, outil
from vidange.pesees.tour import TourPesees
from vidange.pesees.verification import verifier_avec_liste
from vidange.reglages import ErreurReglages, charger_reglages

from .conftest import DOSSIER_PI
from .test_reglages import erreur_de, remplacer

CARTES = ["pesee_griffe", "pesee_prehension", "pesee_plateau_remplissage"]


@pytest.fixture
def liste():
    return charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")


@pytest.fixture
def reglages_pesees():
    return charger_reglages(DOSSIER_PI / "reglages").pesees


@pytest.fixture
def faux(liste):
    return FausseFabrique(liste)


@pytest.fixture
def materiel(liste, faux):
    with Materiel(liste, faux, seulement=CARTES) as materiel:
        yield materiel


class Horloge:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


# ----------------------------------------------------------------- la table


def test_table_des_registres_aller_et_retour():
    mesure = MesureCarte(-123456, 65535, 12, False, True, 80, 3)
    registres = encoder(mesure)
    assert registres[0:2] == [0xFFFE, 0x1DC0]
    assert registres[7] == 0x5053
    assert decoder(registres) == mesure


def test_un_autre_appareil_n_est_pas_une_carte_de_pesee():
    registres = encoder(MesureCarte(0, 0, 0, False, False, 80, 0))
    registres[7] = 0
    with pytest.raises(ErreurMateriel, match="pas une carte de pesée"):
        decoder(registres)


# ------------------------------------------------------------ par le Materiel


def test_lecture_d_une_carte_par_son_nom(materiel, faux):
    faux.regler_pesee("pesee_griffe", -2_000_000)
    faux.regler_pesee("pesee_prehension", 1234)
    mesure = materiel.lire_carte_pesee("pesee_griffe")
    assert mesure.brut == -2_000_000
    assert mesure.par_seconde == 80
    assert not mesure.hx711_muet
    assert materiel.peser("pesee_prehension", 0.5) == 1234
    # Chaque carte à son adresse.
    assert faux.carte_pesee("pesee_griffe").questions == 1
    assert faux.carte_pesee("pesee_plateau_remplissage").questions == 0


def test_hx711_muet_ou_carte_debranchee(materiel, faux):
    faux.carte_pesee("pesee_griffe").hx711_muet = True
    assert materiel.lire_carte_pesee("pesee_griffe").hx711_muet
    with pytest.raises(PeseeMuette, match="HX711 muet"):
        materiel.peser("pesee_griffe", 0.5)
    faux.debrancher("pesee_prehension")
    with pytest.raises(ErreurMateriel, match="pesee_prehension.*pas de réponse"):
        materiel.lire_carte_pesee("pesee_prehension")


def test_l_ozone_et_les_pesees_sont_sur_deux_bus(liste, faux):
    assert set(faux.rs485) == {"rs485_ozone", "rs485_pesee"}
    with Materiel(liste, faux) as materiel:
        faux.regler("ozone_1", 0.05)
        faux.regler_pesee("pesee_griffe", 77)
        assert materiel.mesurer("ozone_1") == pytest.approx(0.05)
        assert materiel.peser("pesee_griffe", 0.5) == 77


# --------------------------------------------------------------- le tour


def test_un_tour_et_le_poids_en_kilos_et_en_newtons(reglages_pesees, materiel, faux):
    etalonnage = reglages_pesees.etalonnage["pesee_griffe"]
    faux.regler_pesee("pesee_griffe", round(etalonnage.zero_brut + 2.5 * etalonnage.brut_par_kg))
    tour = TourPesees(reglages_pesees, materiel, Horloge())
    assert tour.faire_un_tour()
    capteur: CapteurForce = tour.capteur("pesee_griffe")
    assert tour.capteur("pesee_griffe").lire_kg() == pytest.approx(2.5)
    assert capteur.lire_n() == pytest.approx(2.5 * G)
    # La griffe revient deux fois par tour : deux questions.
    assert faux.carte_pesee("pesee_griffe").questions == 2
    assert faux.carte_pesee("pesee_prehension").questions == 1
    assert tour.etats["pesee_griffe"].mesures_vues == 1
    # Une carte qui répond toujours la même mesure (même numéro) : rien de nouveau vu.
    faux.carte_pesee("pesee_griffe").figee = True
    tour.faire_un_tour()
    assert tour.etats["pesee_griffe"].mesures_vues == 1
    with pytest.raises(KeyError):
        tour.capteur("pesee_inconnue")


def test_jamais_une_vieille_mesure(reglages_pesees, materiel, faux):
    horloge = Horloge()
    tour = TourPesees(reglages_pesees, materiel, horloge)
    capteur = tour.capteur("pesee_griffe")
    with pytest.raises(ErreurMateriel, match="aucune réponse"):
        capteur.lire_n()
    tour.faire_un_tour()
    capteur.lire_n()
    # La carte ne répond plus : la dernière mesure vieillit, puis est refusée.
    faux.debrancher("pesee_griffe")
    tour.faire_un_tour()
    horloge.t += reglages_pesees.age_max_ms / 1000 / 2
    capteur.lire_n()
    horloge.t += reglages_pesees.age_max_ms / 1000
    with pytest.raises(ErreurMateriel, match="muette"):
        capteur.lire_n()
    # HX711 muet : refusé tout de suite.
    faux.debrancher("pesee_griffe", False)
    faux.carte_pesee("pesee_griffe").hx711_muet = True
    tour.faire_un_tour()
    with pytest.raises(PeseeMuette):
        capteur.lire_n()


def test_carte_muette_dite_une_fois_au_journal(reglages_pesees, materiel, faux, caplog):
    caplog.set_level("INFO")
    tour = TourPesees(reglages_pesees, materiel, Horloge())
    faux.debrancher("pesee_prehension")
    for _ in range(3):
        assert tour.faire_un_tour()
    assert caplog.text.count("Carte de pesée muette") == 1
    faux.debrancher("pesee_prehension", False)
    tour.faire_un_tour()
    assert "elle répond de nouveau" in caplog.text
    # Plus rien ne répond : le tour le dit (le fil attend alors avant de réessayer).
    for nom in CARTES:
        faux.debrancher(nom)
    assert not tour.faire_un_tour()


def test_constats_de_la_check_list(reglages_pesees, materiel, faux):
    tour = TourPesees(reglages_pesees, materiel, Horloge())
    faux.debrancher("pesee_prehension")
    faux.carte_pesee("pesee_plateau_remplissage").hx711_muet = True
    tour.faire_un_tour()
    constats = {c.sujet: c for c in tour.constats()}
    assert constats["pesée pesee_griffe"].niveau == "ok"
    assert "80 mesures par seconde" in constats["pesée pesee_griffe"].texte
    assert constats["pesée pesee_prehension"].niveau == "attention"
    assert constats["pesée pesee_plateau_remplissage"].texte == "HX711 muet"
    assert constats["pesees.yaml"].niveau == "attention"  # étalonnage d'exemple
    assert all(c.niveau != "bloquant" for c in constats.values())
    assert constats_pesees(None)[0].niveau == "attention"


def test_le_fil_interroge_en_fond(reglages_pesees, materiel, faux):
    tour = TourPesees(reglages_pesees, materiel)
    arret = threading.Event()
    fil = tour.demarrer(arret)
    try:
        for _ in range(200):
            if faux.carte_pesee("pesee_plateau_remplissage").questions >= 3:
                break
            arret.wait(0.01)
        assert faux.carte_pesee("pesee_plateau_remplissage").questions >= 3
    finally:
        arret.set()
        fil.join(2)
    assert not fil.is_alive()


# ------------------------------------------------------------- les réglages


def test_broches_du_rp2040_verifiees(reglages):
    fichier = reglages / "pesees.yaml"
    remplacer(fichier, "rs485_tx: 0", "rs485_tx: 4")
    remplacer(fichier, "rs485_sens: 6", "rs485_sens: 3")
    erreur = erreur_de(reglages)
    assert "ne sont pas du même UART" in erreur
    assert "la broche 3 est prise deux fois (hx711_sck et rs485_sens)" in erreur
    remplacer(fichier, "rs485_tx: 4", "rs485_tx: 2")
    assert "rs485_tx (2) n'est pas une broche TX" in erreur_de(reglages)


def test_tour_et_etalonnage_vont_ensemble(reglages):
    fichier = reglages / "pesees.yaml"
    remplacer(fichier, "  - pesee_prehension\n", "")
    assert "« pesee_prehension » n'est jamais lue" in erreur_de(reglages)
    remplacer(fichier, "brut_par_kg: 40000", "brut_par_kg: 0")
    assert "brut_par_kg ne peut pas valoir 0" in erreur_de(reglages)


def test_pesees_et_entrees_sorties_vont_ensemble(reglages_pesees, entrees_sorties):
    assert verifier_avec_liste(reglages_pesees, charger_entrees_sorties(entrees_sorties)) == []
    remplacer(entrees_sorties, "      delai_reponse_s: 0.02", "      delai_reponse_s: 0.001")
    remplacer(entrees_sorties, "  pesee_prehension:\n", "  pesee_autre:\n")
    liste = charger_entrees_sorties(entrees_sorties)
    erreurs = "\n".join(verifier_avec_liste(reglages_pesees, liste))
    assert "« pesee_prehension » n'est pas une carte de pesée de entrees-sorties.yaml" in erreurs
    assert "la carte de pesée « pesee_autre » n'est pas dans pesees.yaml" in erreurs
    assert "delai_reponse_s (0.001 s) doit valoir au moins" in erreurs


def test_une_carte_de_pesee_a_une_adresse(entrees_sorties):
    remplacer(entrees_sorties, "    adresse: 3\n    module: remplissage", "    module: remplissage")
    with pytest.raises(ErreurReglages, match="adresse sur le bus, de 1 à 247"):
        charger_entrees_sorties(entrees_sorties)


def test_le_demarrage_refuse_des_pesees_qui_ne_vont_pas_ensemble(
    reglages, entrees_sorties, tmp_path, capsys
):
    from vidange.demarrage import CODE_REGLAGES_FAUX, principal

    remplacer(entrees_sorties, "  pesee_prehension:\n", "  pesee_autre:\n")
    options = [
        "--reglages",
        str(reglages),
        "--entrees-sorties",
        str(entrees_sorties),
        "--secrets",
        str(tmp_path / "secrets.yaml"),
        "--donnees",
        str(tmp_path / "donnees"),
        "--verifier",
    ]
    assert principal(options) == CODE_REGLAGES_FAUX
    assert "pesee_autre" in capsys.readouterr().err


# --------------------------------------------- réglages du programme des cartes


def test_reglages_copies_dans_le_programme(tmp_path):
    entete.ecrire(
        DOSSIER_PI / "reglages" / "pesees.yaml",
        DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml",
        tmp_path,
    )
    texte_h = (tmp_path / "reglages_genere.h").read_text(encoding="utf-8")
    texte_cmake = (tmp_path / "reglages_genere.cmake").read_text(encoding="utf-8")
    assert "#define REGLAGE_VITESSE_BAUDS 115200" in texte_h
    assert "#define REGLAGE_BLOC_UART 0" in texte_h
    assert "#define REGLAGE_EXEMPLE 1" in texte_h
    assert 'set(PICO_BOARD "pico")' in texte_cmake
    cartes = "pesee_griffe;1;pesee_prehension;2;pesee_plateau_remplissage;3"
    assert f'set(CARTES_PESEE "{cartes}")' in texte_cmake


def test_fabrication_arretee_par_des_reglages_faux(reglages, entrees_sorties, tmp_path, capsys):
    remplacer(reglages / "pesees.yaml", "hx711_sck: 3", "hx711_sck: 2")
    assert entete.main([str(reglages / "pesees.yaml"), str(entrees_sorties), str(tmp_path)]) == 1
    assert "la broche 2 est prise deux fois" in capsys.readouterr().err
    assert not (tmp_path / "reglages_genere.h").exists()
    assert entete.main([]) == 2


# ------------------------------------------------------------------- l'outil


def _outil(liste: Path, faux, *arguments: str) -> int:
    return outil.main(
        ["--reglages", str(DOSSIER_PI / "reglages"), "--entrees-sorties", str(liste), *arguments],
        fabrique=faux,
    )


def test_outil_etalonnage(liste, faux, reglages_pesees, monkeypatch, capsys):
    monkeypatch.setattr(outil, "DUREE_ETALONNAGE_S", 0.05)
    chemin = DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"
    zero = reglages_pesees.etalonnage["pesee_prehension"].zero_brut
    faux.regler_pesee("pesee_prehension", zero + 250_000)
    assert _outil(chemin, faux, "etalonner", "pesee_prehension", "5") == 0
    assert "brut_par_kg: 50000.00" in capsys.readouterr().out
    assert _outil(chemin, faux, "zero", "pesee_prehension") == 0
    assert f"zero_brut: {zero + 250_000}" in capsys.readouterr().out
    faux.carte_pesee("pesee_prehension").hx711_muet = True
    assert _outil(chemin, faux, "zero", "pesee_prehension") == 1
    assert _outil(chemin, faux, "zero", "pesee_inconnue") == 2


def test_outil_lire(faux, capsys):
    chemin = DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"
    faux.debrancher("pesee_plateau_remplissage")
    assert _outil(chemin, faux, "lire", "--secondes", "1") == 0
    sortie = capsys.readouterr().out
    assert "pesee_griffe" in sortie and "carte  80 mesures/s" in sortie
    assert "pesee_plateau_remplissage    ne répond pas" in sortie
