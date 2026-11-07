"""Tests des entrées/sorties du Pi par leur nom, avec le faux matériel."""

import re
import time

import pytest

from vidange.entrees_sorties import charger_entrees_sorties
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel

from .test_reglages import remplacer


@pytest.fixture
def faux_et_materiel(entrees_sorties):
    liste = charger_entrees_sorties(entrees_sorties)
    faux = FausseFabrique(liste)
    with Materiel(liste, faux) as materiel:
        yield faux, materiel


def ouvrir(chemin):
    liste = charger_entrees_sorties(chemin)
    faux = FausseFabrique(liste)
    return faux, Materiel(liste, faux)


def test_au_depart_rien_n_est_actionne_et_tout_est_au_repos(faux_et_materiel):
    faux, materiel = faux_et_materiel
    assert materiel.lire_entrees() == {
        "reed_panneau_poste_fut": False,
        "porte_spray": False,
        "fdc_stockage_haut": False,
        "boucle_stockage": False,
        "onduleur_sur_batterie": False,
        "plateau_fut_en_place": False,
        "bouton_pret_fut": False,
        "store_ferme": False,
    }
    assert materiel.lire("voyant_buzzer") is False
    assert faux.commande("voyant_buzzer") is False
    # La carte relais est « à l'envers » (niveau_actif: bas) : au repos, la broche est haute.
    assert faux.bus["/dev/i2c-1"].appareils[0x20].niveau("P1") is True
    assert faux.gpios["/dev/gpiochip0"].niveau("GPIO23") is True


def test_entrees_actionnees(faux_et_materiel):
    faux, materiel = faux_et_materiel
    faux.actionner("reed_panneau_poste_fut")
    assert materiel.lire("reed_panneau_poste_fut") is True
    faux.actionner("reed_panneau_poste_fut", False)
    assert materiel.lire("reed_panneau_poste_fut") is False


@pytest.mark.parametrize("niveau_actif", ["haut", "bas"])
@pytest.mark.parametrize("repos", ["ouvert", "ferme"])
def test_sens_des_entrees(entrees_sorties, niveau_actif, repos):
    """Le niveau électrique dépend de la carte et du contact ; « actionné » non."""
    remplacer(
        entrees_sorties, "niveau_actif: bas\n      tirage: haut", f"niveau_actif: {niveau_actif}"
    )
    remplacer(
        entrees_sorties,
        "type: contact\n    tension: 24\n    repos: ouvert",
        (f"type: contact\n    tension: 24\n    repos: {repos}"),
    )
    faux, materiel = ouvrir(entrees_sorties)
    gpio = faux.gpios["/dev/gpiochip0"]
    # Contact actionné : courant si repos ouvert, pas de courant si repos fermé.
    faux.actionner("reed_panneau_poste_fut")
    courant = repos == "ouvert"
    assert gpio.niveau("GPIO17") == (courant == (niveau_actif == "haut"))
    assert materiel.lire("reed_panneau_poste_fut") is True
    # Et le calcul à la main, sans le faux : niveau sans courant → pas actionné si repos ouvert.
    gpio.exterieur["GPIO17"] = niveau_actif == "bas"
    assert materiel.lire("reed_panneau_poste_fut") is (repos == "ferme")


def test_commande_d_une_sortie(faux_et_materiel):
    faux, materiel = faux_et_materiel
    materiel.ecrire("voyant_pret_fut", True)
    assert faux.commande("voyant_pret_fut") is True
    assert materiel.lire("voyant_pret_fut") is True
    # Niveau actif bas : relais commandé = broche basse.
    assert faux.bus["/dev/i2c-1"].appareils[0x20].niveau("P1") is False
    materiel.mettre_au_repos()
    assert faux.commande("voyant_pret_fut") is False


def test_le_voyant_buzzer_est_sur_un_gpio_direct_sans_i2c(faux_et_materiel):
    faux, materiel = faux_et_materiel
    materiel.ecrire("voyant_buzzer", True)
    assert faux.commande("voyant_buzzer") is True
    # Niveau actif bas : relais commandé = broche basse ; la carte à relais I2C n'est pas touchée.
    assert faux.gpios["/dev/gpiochip0"].niveau("GPIO23") is False
    assert faux.bus["/dev/i2c-1"].appareils[0x20].niveau("P0") is True
    assert faux.bus["/dev/i2c-1"].appareils[0x20].niveau("P1") is True
    materiel.mettre_au_repos()
    assert faux.commande("voyant_buzzer") is False


def test_a_la_fermeture_les_sorties_reviennent_au_repos(entrees_sorties):
    faux, materiel = ouvrir(entrees_sorties)
    materiel.ecrire("voyant_pret_fut", True)
    materiel.ecrire("voyant_buzzer", True)
    materiel.fermer()
    assert faux.commande("voyant_pret_fut") is False
    assert faux.commande("voyant_buzzer") is False
    assert faux.bus["/dev/i2c-1"].ferme


def relais_par(entrees_sorties, liaison):
    """La carte relais reliée autrement : même programme, même nom de signal."""
    texte = entrees_sorties.read_text(encoding="utf-8")
    debut = texte.index("    # Exemple de liaison par une puce I2C PCF8574")
    fin = texte.index("  rs485_ozone_dedans:")
    entrees_sorties.write_text(texte[:debut] + liaison + texte[fin:], encoding="utf-8")


def test_carte_relais_en_gpio_direct(entrees_sorties):
    relais_par(
        entrees_sorties,
        "    liaison:\n      type: gpio\n      fichier: /dev/gpiochip0\n"
        "      broches:\n        K1: GPIO13\n        K2: GPIO21\n",
    )
    faux, materiel = ouvrir(entrees_sorties)
    gpio = faux.gpios["/dev/gpiochip0"]
    # GPIO12 : le battement du Pi, sur la carte « pi » elle-même.
    # GPIO23 : le module relais du voyant-buzzer (niveau actif bas : haut au repos).
    assert gpio.sorties == {"GPIO12": False, "GPIO21": False, "GPIO23": True}
    materiel.ecrire("voyant_pret_fut", True)
    assert gpio.niveau("GPIO21") is True
    assert faux.commande("voyant_pret_fut") is True


def test_carte_relais_par_un_mcp23017(entrees_sorties):
    relais_par(
        entrees_sorties,
        "    liaison:\n      type: i2c\n      signal: relais_1_bus\n"
        "      broches:\n        K1: B3\n        K2: B4\n      niveau_actif: bas\n",
    )
    remplacer(entrees_sorties, "appareil: pcf8574", "appareil: mcp23017")
    faux, materiel = ouvrir(entrees_sorties)
    puce = faux.bus["/dev/i2c-1"].appareils[0x20]
    assert puce.niveau("B4") is True  # au repos (actif bas)
    materiel.ecrire("voyant_pret_fut", True)
    assert puce.niveau("B4") is False
    assert faux.commande("voyant_pret_fut") is True


def entrees_par_un_pcf8574(entrees_sorties):
    texte = entrees_sorties.read_text(encoding="utf-8")
    texte = re.sub(
        r"    # Exemple de liaison par GPIO direct\.\n.*?tirage: haut\n",
        "    liaison:\n      type: i2c\n      signal: entrees_bus\n"
        "      broches:\n        E1: P0\n        E2: P1\n        E3: P2\n        E4: P3\n"
        "        E5: P4\n        E6: P5\n        E7: P6\n      niveau_actif: bas\n",
        texte,
        flags=re.DOTALL,
    )
    texte += (
        "  entrees_bus:\n    carte: pi\n    broche: [GPIO2, GPIO3]\n    type: i2c\n"
        "    tension: 3.3\n    adresse: 0x22\n    module: armoire\n    appareil: pcf8574\n"
        "    fichier: /dev/i2c-1\n"
    )
    entrees_sorties.write_text(texte, encoding="utf-8")


def test_entrees_24v_par_un_pcf8574(entrees_sorties):
    entrees_par_un_pcf8574(entrees_sorties)
    faux, materiel = ouvrir(entrees_sorties)
    assert materiel.lire("fdc_stockage_haut") is False
    faux.actionner("fdc_stockage_haut")
    assert materiel.lire("fdc_stockage_haut") is True
    assert faux.bus["/dev/i2c-1"].appareils[0x22].niveau("P2") is False


def test_mesure_analogique_convertie(faux_et_materiel):
    faux, materiel = faux_et_materiel
    faux.regler("vide_venturi", -45)
    assert materiel.mesurer("vide_venturi") == pytest.approx(-45, abs=0.02)
    assert materiel.unite("vide_venturi") == "kPa"
    # 0,333 V → 0 kPa et 3,0 V → -100 kPa : 1,533 V → -45 kPa.
    assert faux.bus["/dev/i2c-1"].appareils[0x48].tensions["A0"] == pytest.approx(1.533, abs=0.001)


def test_mesure_sans_conversion_en_volts(entrees_sorties):
    remplacer(
        entrees_sorties,
        "    unite: kPa\n    conversion:\n      volts: [0.333, 3.0]\n      valeurs: [0, -100]\n",
        "",
    )
    faux, materiel = ouvrir(entrees_sorties)
    faux.regler("vide_venturi", 2.2)
    assert materiel.mesurer("vide_venturi") == pytest.approx(2.2, abs=0.001)
    assert materiel.unite("vide_venturi") == "V"


def test_ambiance_de_l_armoire(faux_et_materiel):
    faux, materiel = faux_et_materiel
    faux.regler_ambiance("sht31_armoire", 33.5, 88)
    ambiance = materiel.ambiance("sht31_armoire")
    assert ambiance.temperature_c == pytest.approx(33.5, abs=0.01)
    assert ambiance.humidite_pct == pytest.approx(88, abs=0.01)


def test_ozone_en_ppm(faux_et_materiel):
    faux, materiel = faux_et_materiel
    faux.regler("ozone_dedans", 0.85)
    faux.regler("ozone_dehors", 0.12)
    assert materiel.mesurer("ozone_dedans") == pytest.approx(0.85)
    assert materiel.mesurer("ozone_dehors") == pytest.approx(0.12)
    assert materiel.unite("ozone_dedans") == "ppm"


def test_puce_debranchee_le_reste_continue(faux_et_materiel):
    faux, materiel = faux_et_materiel
    faux.debrancher("sht31_armoire")
    with pytest.raises(ErreurMateriel, match="signal « sht31_armoire » : puce I2C 0x44"):
        materiel.ambiance("sht31_armoire")
    materiel.mesurer("ozone_dedans")  # il a parlé une fois, puis plus rien
    faux.debrancher("ozone_dedans")
    # 100 s plus tard, sans une trame : muet (l'horloge du lecteur avance, pas le test).
    lecteur = materiel._ozones["ozone_dedans"]
    lecteur._horloge = lambda: time.monotonic() + 100
    with pytest.raises(ErreurMateriel, match="signal « ozone_dedans » : rs485_ozone_dedans : muet"):
        materiel.mesurer("ozone_dedans")
    assert materiel.mesurer("ozone_dehors") == 0  # l'autre capteur n'est pas gêné
    faux.debrancher("sht31_armoire", False)
    materiel.ambiance("sht31_armoire")


def test_entree_illisible_dans_lire_entrees(entrees_sorties):
    entrees_par_un_pcf8574(entrees_sorties)
    faux, materiel = ouvrir(entrees_sorties)
    faux.debrancher("porte_spray")
    entrees = materiel.lire_entrees()
    assert isinstance(entrees["porte_spray"], ErreurMateriel)
    assert "signal « porte_spray »" in str(entrees["porte_spray"])


def test_puce_absente_au_demarrage(entrees_sorties):
    liste = charger_entrees_sorties(entrees_sorties)
    faux = FausseFabrique(liste)
    faux.bus["/dev/i2c-1"].appareils[0x20].debranche = True
    attendu = "puce I2C 0x20 .* \\(signaux voyant_pret_fut\\)"
    with pytest.raises(ErreurMateriel, match=attendu):
        Materiel(liste, faux)


def test_mauvais_usage_d_un_nom(faux_et_materiel):
    _, materiel = faux_et_materiel
    with pytest.raises(KeyError, match="signal inconnu « voyant »"):
        materiel.lire("voyant")
    with pytest.raises(ErreurMateriel, match="c'est un signal de sorte « entree »"):
        materiel.ecrire("porte_spray", True)
    with pytest.raises(ErreurMateriel, match="le Pi ne le lit pas lui-même"):
        materiel.lire("ecran_nextion")
    with pytest.raises(ErreurMateriel, match="pas « mesure ou ozone »"):
        materiel.mesurer("sht31_armoire")


def test_signaux_des_cartes_sans_liaison_ignores(entrees_sorties):
    # Une carte que le Pi ne lit pas (comme une carte FluidNC) : ses signaux sont ignorés.
    texte = entrees_sorties.read_text(encoding="utf-8")
    texte = re.sub(
        r"    # Exemple de liaison par GPIO direct\.\n.*?tirage: haut\n", "", texte, flags=re.DOTALL
    )
    entrees_sorties.write_text(texte, encoding="utf-8")
    _, materiel = ouvrir(entrees_sorties)
    assert "reed_panneau_poste_fut" not in materiel.branchements
    # Reste l'entrée branchée sur les broches du Pi lui-même.
    assert materiel.lire_entrees() == {"onduleur_sur_batterie": False}
