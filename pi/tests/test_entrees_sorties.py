"""Tests de la vérification de la liste des entrées/sorties (docs/entrees-sorties.yaml)."""

from pathlib import Path

import pytest

from vidange.entrees_sorties import charger_entrees_sorties
from vidange.reglages import ErreurReglages

from .conftest import DOSSIER_PI
from .test_reglages import ajouter, remplacer


def erreur_de(chemin: Path) -> str:
    with pytest.raises(ErreurReglages) as erreur:
        charger_entrees_sorties(chemin)
    return str(erreur.value)


def test_la_liste_du_depot_est_correcte():
    liste = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
    assert liste.signaux["reed_panneau_poste_fut"].broche == ("E1",)
    assert liste.signaux["sht31_armoire"].broche == ("GPIO2", "GPIO3")
    assert liste.signaux["sht31_armoire"].adresse == 0x44
    # Tout est encore marqué « exemple ».
    assert set(liste.exemples()) == {*liste.cartes, *liste.signaux}


def test_fichier_manquant(tmp_path):
    assert "entrees-sorties.yaml : fichier manquant" in erreur_de(tmp_path / "entrees-sorties.yaml")


def test_signal_ecrit_deux_fois(entrees_sorties):
    ajouter(entrees_sorties, "\n  ecran_nextion:\n    carte: pi\n")
    assert "« ecran_nextion » est écrit deux fois" in erreur_de(entrees_sorties)


def test_broche_en_double(entrees_sorties):
    remplacer(entrees_sorties, "broche: E2", "broche: E1")
    message = erreur_de(entrees_sorties)
    assert (
        "carte « entrees_24v_1 », broche E1 : utilisée par plusieurs signaux "
        "(reed_panneau_poste_fut, porte_spray)"
    ) in message


def test_broche_en_double_malgre_les_majuscules(entrees_sorties):
    remplacer(entrees_sorties, "broche: E2", "broche: e1")
    assert "broche E1 : utilisée par plusieurs signaux" in erreur_de(entrees_sorties)


def test_une_broche_de_bus_ne_sert_pas_a_autre_chose(entrees_sorties):
    remplacer(entrees_sorties, "broche: [GPIO4, GPIO5]", "broche: [GPIO3, GPIO5]")
    message = erreur_de(entrees_sorties)
    assert "carte « pi », broche GPIO3 : utilisée par plusieurs signaux" in message
    assert "sht31_armoire, ads1115_bus, ecran_nextion" in message


def test_bus_partage_sans_adresse(entrees_sorties):
    # Deux appareils série sur les mêmes broches, sans adresse : refusé.
    ajouter(
        entrees_sorties,
        "  autre_ecran:\n    carte: pi\n    broche: [GPIO4, GPIO5]\n    type: serie\n"
        "    tension: 3.3\n    module: armoire\n",
    )
    message = erreur_de(entrees_sorties)
    assert "broche GPIO4 : utilisée par plusieurs signaux (ecran_nextion, autre_ecran)" in message
    assert "chacun doit avoir son adresse" in message


def test_adresse_i2c_en_double(entrees_sorties):
    remplacer(entrees_sorties, "adresse: 0x48", "adresse: 0x44")
    message = erreur_de(entrees_sorties)
    assert (
        "bus i2c de la carte « pi » (GPIO2, GPIO3) : adresse 0x44 utilisée par plusieurs "
        "signaux (sht31_armoire, ads1115_bus)"
    ) in message


def test_carte_inconnue(entrees_sorties):
    remplacer(entrees_sorties, "carte: relais_1", "carte: relais_9")
    assert "signal « voyant_buzzer » : carte inconnue « relais_9 »" in erreur_de(entrees_sorties)


def test_module_inconnu(entrees_sorties):
    remplacer(entrees_sorties, "module: stockage", "module: stokage")
    message = erreur_de(entrees_sorties)
    assert "signal « fdc_stockage_haut » : module inconnu « stokage »" in message


def test_trop_d_entrees_sur_une_carte(entrees_sorties):
    remplacer(entrees_sorties, "entrees: 8", "entrees: 2")
    message = erreur_de(entrees_sorties)
    assert "carte « entrees_24v_1 » : 3 entrées branchées pour 2 disponibles" in message


def test_trop_de_sorties_sur_une_carte(entrees_sorties):
    remplacer(entrees_sorties, "sorties: 8", "sorties: 0")
    message = erreur_de(entrees_sorties)
    assert "carte « relais_1 » : 1 sorties branchées pour 0 disponibles" in message


def test_24_volts_sans_isolement(entrees_sorties):
    remplacer(
        entrees_sorties, "carte: entrees_24v_1\n    broche: E3", "carte: pi\n    broche: GPIO17"
    )
    message = erreur_de(entrees_sorties)
    assert "signal « fdc_stockage_haut » : 24 V sur la carte « pi » qui n'est pas isolée" in message


def test_24_volts_sans_isolement_meme_si_la_carte_dit_accepter_24_volts(entrees_sorties):
    remplacer(
        entrees_sorties, "tension_max: 3.3\n    isolee: false", "tension_max: 24\n    isolee: false"
    )
    remplacer(
        entrees_sorties, "carte: entrees_24v_1\n    broche: E3", "carte: pi\n    broche: GPIO17"
    )
    assert "qui n'est pas isolée" in erreur_de(entrees_sorties)


def test_tension_trop_forte_pour_la_carte(entrees_sorties):
    remplacer(
        entrees_sorties,
        "tension: 3.3\n    module: prehension",
        "tension: 5\n    module: prehension",
    )
    message = erreur_de(entrees_sorties)
    assert (
        "signal « vide_venturi » : 5 V, plus que les 3.3 V acceptés par la carte « ads1115 »"
        in message
    )


def test_repos_oublie(entrees_sorties):
    remplacer(entrees_sorties, "    repos: ferme\n", "")
    message = erreur_de(entrees_sorties)
    assert (
        "signaux → porte_spray : un signal de type contact doit dire son état au repos" in message
    )


def test_repos_inutile(entrees_sorties):
    remplacer(entrees_sorties, "type: mesure\n", "type: mesure\n    repos: ouvert\n")
    message = erreur_de(entrees_sorties)
    assert "« repos » n'a pas de sens pour un signal de type mesure" in message


def test_repos_mal_ecrit(entrees_sorties):
    remplacer(entrees_sorties, "repos: ferme", "repos: fermé")
    assert "porte_spray → repos : doit être l'un de" in erreur_de(entrees_sorties)


def test_adresse_i2c_oubliee(entrees_sorties):
    remplacer(entrees_sorties, "    adresse: 0x44\n", "")
    message = erreur_de(entrees_sorties)
    assert "signaux → sht31_armoire : un signal i2c doit avoir son adresse" in message


def test_adresse_hors_d_un_bus(entrees_sorties):
    remplacer(entrees_sorties, "type: mesure\n", "type: mesure\n    adresse: 3\n")
    assert "« adresse » ne sert qu'aux bus" in erreur_de(entrees_sorties)


def test_type_inconnu(entrees_sorties):
    remplacer(entrees_sorties, "type: pnp", "type: PNP")
    assert "fdc_stockage_haut → type : doit être l'un de" in erreur_de(entrees_sorties)


def test_broche_vide(entrees_sorties):
    remplacer(entrees_sorties, "broche: A0", "broche: []")
    assert "vide_venturi → broche : doit être une broche" in erreur_de(entrees_sorties)


def test_broche_en_nombre_acceptee(entrees_sorties):
    remplacer(entrees_sorties, "broche: E3", "broche: 3")
    liste = charger_entrees_sorties(entrees_sorties)
    assert liste.signaux["fdc_stockage_haut"].broche == ("3",)


def test_toutes_les_erreurs_sont_dites_d_un_coup(entrees_sorties):
    remplacer(entrees_sorties, "broche: E2", "broche: E1")
    remplacer(entrees_sorties, "carte: relais_1", "carte: relais_9")
    remplacer(entrees_sorties, "module: stockage", "module: stokage")
    message = erreur_de(entrees_sorties)
    assert "broche E1 : utilisée par plusieurs signaux" in message
    assert "carte inconnue « relais_9 »" in message
    assert "module inconnu « stokage »" in message
