"""Tests des puces (SHT31, ADS1115, PCF8574, MCP23017) contre leurs faux, et des GPIO du Pi."""

import pytest

from vidange.materiel.faux import (
    FauxAds1115,
    FauxBusI2c,
    FauxMcp23017,
    FauxPcf8574,
    FauxSht31,
)
from vidange.materiel.puces import (
    Ads1115,
    ErreurMateriel,
    LignesGpio,
    Mcp23017,
    Pcf8574,
    Sht31,
    crc_sht31,
)


def bus_avec(adresse, appareil):
    bus = FauxBusI2c()
    bus.appareils[adresse] = appareil
    return bus


def test_somme_de_controle_du_sht31():
    # Exemple de la fiche technique : 0xBEEF → 0x92.
    assert crc_sht31(bytes([0xBE, 0xEF])) == 0x92


def test_sht31_mesure():
    faux = FauxSht31(temperature_c=31.2, humidite_pct=82.5)
    temperature, humidite = Sht31(bus_avec(0x44, faux), 0x44).mesurer()
    assert temperature == pytest.approx(31.2, abs=0.01)
    assert humidite == pytest.approx(82.5, abs=0.01)


def test_sht31_mesure_abimee():
    faux = FauxSht31()
    faux.abime = True
    with pytest.raises(ErreurMateriel, match="somme de contrôle fausse"):
        Sht31(bus_avec(0x44, faux), 0x44).mesurer()


def test_puce_absente():
    with pytest.raises(ErreurMateriel) as erreur:
        Sht31(FauxBusI2c(), 0x44).mesurer()
    assert "puce I2C 0x44 : pas de réponse (puce débranchée" in str(erreur.value)


def test_ads1115_choisit_l_echelle_la_plus_precise():
    assert Ads1115.pleine_echelle(3.3) == 4.096
    assert Ads1115.pleine_echelle(2.0) == 2.048
    assert Ads1115.pleine_echelle(9) == 6.144


@pytest.mark.parametrize("tension", [0.0, 1.234, 3.3, -0.1])
def test_ads1115_mesure(tension):
    faux = FauxAds1115()
    faux.tensions["A2"] = tension
    faux.tensions["A0"] = 2.5
    mesure = Ads1115(bus_avec(0x48, faux), 0x48).mesurer("A2", tension_max=3.3)
    # Précision d'un pas de 16 bits sur 4,096 V.
    assert mesure == pytest.approx(tension, abs=4.096 / 32768)


def test_pcf8574_entrees_et_sorties():
    faux = FauxPcf8574()
    puce = Pcf8574(bus_avec(0x20, faux), 0x20)
    puce.preparer({"P1": "haut"}, {"P0": True, "P7": False})
    assert faux.octet == 0b0111_1111
    assert puce.lire("P1") is True  # tirée en haut
    faux.exterieur["P1"] = False
    assert puce.lire("P1") is False
    puce.ecrire("P7", True)
    puce.ecrire("P0", False)
    assert faux.octet == 0b1111_1110
    assert faux.niveau("P7") and not faux.niveau("P0")


def test_mcp23017_entrees_et_sorties():
    faux = FauxMcp23017()
    puce = Mcp23017(bus_avec(0x21, faux), 0x21)
    puce.preparer({"A0": "haut", "B7": "aucun"}, {"A1": False, "B0": True})
    # Sens : A1 et B0 en sortie, le reste en entrée ; tirage sur A0.
    assert faux.registres[0x00] == 0b1111_1101 and faux.registres[0x01] == 0b1111_1110
    assert faux.registres[0x0C] == 0b0000_0001 and faux.registres[0x0D] == 0
    assert faux.niveau("B0") and not faux.niveau("A1")
    assert puce.lire("A0") is True
    assert puce.lire("B7") is False
    faux.exterieur["B7"] = True
    assert puce.lire("B7") is True
    puce.ecrire("A1", True)
    assert faux.niveau("A1")
    assert puce.lire("B0") is True


class FausseRequete:
    def __init__(self, fichier, consumer, config):
        self.fichier = fichier
        self.config = config
        self.valeurs = {}
        self.relachee = False

    def get_value(self, broche):
        return self.valeurs[broche]

    def set_value(self, broche, valeur):
        self.valeurs[broche] = valeur

    def release(self):
        self.relachee = True


def test_gpio_du_pi_par_le_nom_des_broches():
    from gpiod.line import Bias, Direction, Value

    requetes = []

    def demander(fichier, consumer, config):
        requetes.append(FausseRequete(fichier, consumer, config))
        return requetes[-1]

    lignes = LignesGpio("/dev/gpiochip0", demander=demander)
    lignes.preparer({"GPIO17": "haut", "GPIO27": "aucun"}, {"GPIO22": True})
    requete = requetes[0]
    assert requete.fichier == "/dev/gpiochip0"
    assert requete.config["GPIO17"].direction == Direction.INPUT
    assert requete.config["GPIO17"].bias == Bias.PULL_UP
    assert requete.config["GPIO27"].bias == Bias.DISABLED
    assert requete.config["GPIO22"].direction == Direction.OUTPUT
    assert requete.config["GPIO22"].output_value == Value.ACTIVE
    requete.valeurs["GPIO17"] = Value.INACTIVE
    assert lignes.lire("GPIO17") is False
    lignes.ecrire("GPIO22", False)
    assert requete.valeurs["GPIO22"] == Value.INACTIVE
    lignes.fermer()
    assert requete.relachee


def test_gpio_broche_impossible_a_prendre():
    def demander(fichier, consumer, config):
        raise OSError("Device or resource busy")

    lignes = LignesGpio("/dev/gpiochip0", demander=demander)
    with pytest.raises(ErreurMateriel, match="GPIO17 de /dev/gpiochip0 impossibles à prendre"):
        lignes.preparer({"GPIO17": "aucun"}, {})


def test_bus_i2c_de_linux(monkeypatch):
    """Le vrai bus, avec un faux smbus2 : les bons messages partent vers Linux."""
    import smbus2

    envois = []

    class FauxSMBus:
        def __init__(self, fichier):
            self.fichier = fichier

        def i2c_rdwr(self, *messages):
            envois.append(messages)
            for message in messages:
                if message.flags:  # lecture
                    for i in range(message.len):
                        message.buf[i] = bytes([0x12 + i])

        def close(self):
            pass

    monkeypatch.setattr(smbus2, "SMBus", FauxSMBus)
    from vidange.materiel.puces import BusI2cLinux

    bus = BusI2cLinux("/dev/i2c-1")
    bus.ecrire(0x20, bytes([0xAA]))
    assert bus.ecrire_lire(0x48, bytes([0x01]), 2) == bytes([0x12, 0x13])
    assert len(envois) == 2 and len(envois[1]) == 2
    assert list(envois[0][0]) == [0xAA]


def test_bus_i2c_absent():
    from vidange.materiel.puces import BusI2cLinux

    with pytest.raises(ErreurMateriel, match="I2C activé dans raspi-config"):
        BusI2cLinux("/dev/i2c-inexistant")
