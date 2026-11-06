"""Tests du client Modbus RTU (cartes de pesée) contre le faux RS485."""

import pytest

from vidange.materiel.faux import FauxRs485, FauxTransmetteurModbus
from vidange.materiel.modbus import ClientModbus, crc_modbus, demande_lecture
from vidange.materiel.puces import ErreurMateriel


def fil_avec_transmetteur(adresse=1, registres=None):
    fil = FauxRs485()
    transmetteur = FauxTransmetteurModbus()
    transmetteur.registres.update(registres or {0: 0})
    fil.appareils[adresse] = transmetteur
    return fil, transmetteur


def test_somme_de_controle():
    # Exemple connu : lire 10 registres à partir de 0 sur l'appareil 1.
    assert crc_modbus(bytes.fromhex("01030000000A")) == bytes.fromhex("C5CD")
    assert demande_lecture(1, 3, 0, 10) == bytes.fromhex("01030000000AC5CD")


def test_lecture_de_registres():
    fil, _ = fil_avec_transmetteur(registres={4: 123, 5: 0xFFFF})
    client = ClientModbus(fil.ouvrir, nom="rs485_pesee")
    assert client.lire_registres(1, 3, 4, 2) == [123, 0xFFFF]


def test_pas_de_reponse():
    fil, transmetteur = fil_avec_transmetteur()
    transmetteur.debranche = True
    client = ClientModbus(fil.ouvrir, nom="rs485_pesee")
    with pytest.raises(ErreurMateriel, match="rs485_pesee, appareil 1 : pas de réponse"):
        client.lire_registres(1, 3, 0)
    # Mauvaise adresse : pareil.
    with pytest.raises(ErreurMateriel, match="appareil 7 : pas de réponse"):
        client.lire_registres(7, 3, 0)


def test_registre_inconnu_de_l_appareil():
    fil, _ = fil_avec_transmetteur()
    client = ClientModbus(fil.ouvrir)
    with pytest.raises(ErreurMateriel, match="demande refusée \\(registre inconnu"):
        client.lire_registres(1, 3, 99)


def test_reponse_abimee():
    fil, transmetteur = fil_avec_transmetteur(registres={0: 42})
    vraie_reponse = transmetteur.repondre

    def reponse_abimee(demande):
        reponse = bytearray(vraie_reponse(demande))
        reponse[4] ^= 0x01
        return bytes(reponse)

    transmetteur.repondre = reponse_abimee
    client = ClientModbus(fil.ouvrir)
    with pytest.raises(ErreurMateriel, match="somme de contrôle fausse"):
        client.lire_registres(1, 3, 0)


def test_reprise_apres_debranchement_de_l_adaptateur():
    fil, _ = fil_avec_transmetteur(registres={0: 7})
    client = ClientModbus(fil.ouvrir)
    assert client.lire_registres(1, 4, 0) == [7]
    fil.cable_coupe = True
    with pytest.raises(ErreurMateriel, match="port série en panne"):
        client.lire_registres(1, 4, 0)
    with pytest.raises(ErreurMateriel, match="port série en panne"):
        client.lire_registres(1, 4, 0)
    fil.cable_coupe = False
    assert client.lire_registres(1, 4, 0) == [7]
    # Le port a été rouvert après la panne.
    assert fil.ouvertures == 2
