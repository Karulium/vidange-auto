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
    assert "carte « entrees_24v_1 » : 5 entrées branchées pour 2 disponibles" in message


def test_trop_de_sorties_sur_une_carte(entrees_sorties):
    remplacer(entrees_sorties, "sorties: 8", "sorties: 0")
    message = erreur_de(entrees_sorties)
    assert "carte « relais_1 » : 2 sorties branchées pour 0 disponibles" in message


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
    remplacer(entrees_sorties, "E3: GPIO22", "3: GPIO22")
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


# ------------------------------------------------- liaison des cartes au Pi


def test_liaisons_de_la_liste_du_depot():
    liste = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
    assert liste.cartes["entrees_24v_1"].liaison.broches["E1"] == "GPIO17"
    assert liste.cartes["relais_1"].liaison.signal == "relais_1_bus"
    assert liste.signaux["relais_1_bus"].appareil == "pcf8574"
    assert liste.signaux["ozone_2"].modbus.echelle == 0.001


def test_repere_absent_de_la_liaison(entrees_sorties):
    remplacer(entrees_sorties, "        E3: GPIO22\n", "")
    message = erreur_de(entrees_sorties)
    assert (
        "signal « fdc_stockage_haut » : repère E3 absent de la liaison de la carte "
        "« entrees_24v_1 » (liaison → broches)"
    ) in message


def test_broche_du_pi_prise_deux_fois(entrees_sorties):
    # Une entrée 24 V branchée sur la broche de l'écran.
    remplacer(entrees_sorties, "E3: GPIO22", "E3: GPIO4")
    message = erreur_de(entrees_sorties)
    assert "broche GPIO4 du Pi (/dev/gpiochip0) : prise plusieurs fois" in message
    assert "ecran_nextion, entrees_24v_1/E3" in message


def test_broche_du_pi_donnee_a_deux_reperes(entrees_sorties):
    remplacer(entrees_sorties, "E3: GPIO22", "E3: GPIO17")
    message = erreur_de(entrees_sorties)
    assert "prise plusieurs fois (entrees_24v_1/E1, entrees_24v_1/E3)" in message


def test_broche_que_la_puce_n_a_pas(entrees_sorties):
    remplacer(entrees_sorties, "K8: P7", "K8: P8")
    message = erreur_de(entrees_sorties)
    assert "carte « relais_1 », liaison → broches → K8 : la puce pcf8574 n'a pas de broche P8" in (
        message
    )


def test_broche_de_puce_prise_deux_fois(entrees_sorties):
    remplacer(entrees_sorties, "K8: P7", "K8: P0")
    assert "broche P0 de la puce prise deux fois" in erreur_de(entrees_sorties)


def test_voie_de_l_ads1115_inconnue(entrees_sorties):
    remplacer(entrees_sorties, "broche: A0", "broche: A5")
    message = erreur_de(entrees_sorties)
    assert "signal « vide_venturi » : la puce ads1115 n'a pas de broche A5" in message


def test_liaison_vers_un_signal_qui_n_est_pas_un_bus_i2c(entrees_sorties):
    remplacer(entrees_sorties, "signal: relais_1_bus", "signal: voyant_buzzer")
    message = erreur_de(entrees_sorties)
    assert "carte « relais_1 » : liaison → signal « voyant_buzzer » doit être un signal" in message


def test_liaison_vers_une_puce_sans_broches(entrees_sorties):
    remplacer(entrees_sorties, "signal: relais_1_bus", "signal: sht31_armoire")
    assert "(sht31) n'a pas de broches" in erreur_de(entrees_sorties)


def test_signal_impossible_sur_cette_carte(entrees_sorties):
    # Une mesure analogique sur une carte d'entrées tout-ou-rien.
    remplacer(entrees_sorties, "type: pnp", "type: mesure")
    remplacer(entrees_sorties, "    repos: ouvert\n    module: stockage", "    module: stockage")
    message = erreur_de(entrees_sorties)
    assert "signal « fdc_stockage_haut » : un signal de type mesure ne peut pas être" in message


def test_que_des_signaux_serie_sur_un_adaptateur_usb(entrees_sorties):
    remplacer(
        entrees_sorties, "carte: relais_1\n    broche: K1", "carte: rs485_ozone\n    broche: K1"
    )
    message = erreur_de(entrees_sorties)
    assert (
        "signal « voyant_buzzer » : la carte « rs485_ozone » est un port série, "
        "elle ne porte que des signaux de type serie (pas relais)"
    ) in message


def test_bus_du_pi_sans_fichier(entrees_sorties):
    remplacer(entrees_sorties, "    fichier: /dev/ttyAMA2\n", "")
    message = erreur_de(entrees_sorties)
    assert "signal « ecran_nextion » : un bus sur les broches du Pi doit avoir son « fichier »" in (
        message
    )


def test_bus_d_une_carte_sans_fichier(entrees_sorties):
    # Le bus de la carte relais sur une carte que le Pi ne lit pas : pas de fichier exigé, mais
    # alors la carte relais ne saurait pas par où passer.
    texte = entrees_sorties.read_text(encoding="utf-8")
    debut = texte.index("  relais_1_bus:")
    bloc = texte[debut : texte.index("  ozone_1:")]
    nouveau = bloc.replace("carte: pi", "carte: ads1115").replace("    fichier: /dev/i2c-1\n", "")
    entrees_sorties.write_text(texte.replace(bloc, nouveau), encoding="utf-8")
    message = erreur_de(entrees_sorties)
    assert "carte « relais_1 » : le signal « relais_1_bus » doit avoir son « fichier »" in message


def test_meme_bus_fichiers_differents(entrees_sorties):
    remplacer(entrees_sorties, "fichier: /dev/i2c-1", "fichier: /dev/i2c-3")
    message = erreur_de(entrees_sorties)
    assert "signaux sht31_armoire, ads1115_bus, relais_1_bus : même bus" in message


def test_appareil_i2c_oublie(entrees_sorties):
    remplacer(entrees_sorties, "    appareil: sht31\n", "")
    assert "un signal i2c doit dire quel appareil est au bout" in erreur_de(entrees_sorties)


def test_transmetteur_modbus_incomplet(entrees_sorties):
    remplacer(entrees_sorties, "    adresse: 2\n", "")
    remplacer(
        entrees_sorties,
        "    modbus:\n      registre: 0\n      fonction: 3\n      echelle: 0.001\n",
        "",
    )
    message = erreur_de(entrees_sorties)
    assert "un transmetteur Modbus doit dire où lire sa mesure" in message
    assert "un transmetteur Modbus doit avoir son adresse" in message


def test_conversion_avec_deux_fois_la_meme_tension(entrees_sorties):
    remplacer(entrees_sorties, "volts: [0.3, 3.0]", "volts: [0.3, 0.3]")
    assert "les deux tensions de « volts » doivent être différentes" in erreur_de(entrees_sorties)


def test_liaison_de_type_inconnu(entrees_sorties):
    remplacer(entrees_sorties, "      type: usb_serie", "      type: wifi")
    message = erreur_de(entrees_sorties)
    assert "rs485_ozone → liaison : type: doit être l'un de : 'gpio', 'i2c', 'usb_serie'" in message


def test_liaison_sans_type(entrees_sorties):
    remplacer(entrees_sorties, "      type: usb_serie\n", "")
    assert "cartes → rs485_ozone → liaison : « type » manque" in erreur_de(entrees_sorties)


def test_au_demarrage_seulement_pour_les_entrees_tout_ou_rien(entrees_sorties):
    # Sur le relais du voyant-buzzer : refusé.
    remplacer(
        entrees_sorties,
        "    repos: ouvert\n    module: armoire\n",
        "    repos: ouvert\n    module: armoire\n    au_demarrage: repos\n",
    )
    message = erreur_de(entrees_sorties)
    assert "« au_demarrage » ne sert qu'aux entrées contact, pnp ou npn" in message
