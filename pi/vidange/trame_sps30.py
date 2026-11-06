"""Trames du capteur de particules Sensirion SPS30 sur sa liaison série (protocole SHDLC).

ATTENTION : écrit de mémoire d'après la fiche « SPS30 Interface Description » de Sensirion, sans la
notice sous les yeux. Tous les nombres de ce fichier sont À VÉRIFIER sur la notice avant le premier
essai (voir pi/systeme/essai-capteurs-purge.md). Ce fichier ne contient que ce qui est fixé par le
protocole ; tout ce qui dépend de la machine (vitesse, grandeur lue, délai « muet ») est dans
`docs/entrees-sorties.yaml`.

Une trame SHDLC : 0x7E, le contenu, 0x7E.
  Question du Pi : adresse, commande, longueur des données, données, somme.
  Réponse        : adresse, commande, état, longueur des données, données, somme.
  Somme de contrôle : (inverse des bits de la somme des octets du contenu) sur un octet.
  Octets échappés dans le contenu : 0x7E, 0x7D, 0x11 et 0x13 deviennent 0x7D suivi de
  l'octet XOR 0x20 (0x7E → 7D 5E, 0x7D → 7D 5D, 0x11 → 7D 31, 0x13 → 7D 33).

Commandes utilisées : « start measurement » (0x00, données 01 03 : mesures en nombres à virgule
flottante IEEE 754 sur 4 octets, poids fort d'abord) et « read measured values » (0x03). La réponse
fait 40 octets de données : 10 nombres. Sans mesure nouvelle, la réponse a 0 octet de données.
"""

import struct
from typing import NamedTuple

OCTET_FIN_TRAME = 0x7E
OCTET_ECHAPPEMENT = 0x7D
MASQUE_ECHAPPEMENT = 0x20
OCTETS_A_ECHAPPER = (0x7E, 0x7D, 0x11, 0x13)

# Le SPS30 répond à l'adresse 0 (elle ne se change pas).
ADRESSE = 0x00

COMMANDE_DEMARRER = 0x00
COMMANDE_ARRETER = 0x01
COMMANDE_LIRE = 0x03
# Données de « start measurement » : sous-commande fixe, puis le format des mesures
# (0x03 = nombres à virgule flottante IEEE 754).
DONNEES_DEMARRER = bytes([0x01, 0x03])

# « read measured values » : 10 nombres de 4 octets.
NOMBRE_VALEURS = 10
LONGUEUR_DONNEES_MESURE = NOMBRE_VALEURS * 4
# Rang de chaque concentration en masse (µg/m³) parmi les 10 nombres.
RANG_GRANDEUR = {"pm1_0": 0, "pm2_5": 1, "pm4_0": 2, "pm10": 3}

# Octet « état » de la réponse : 0 = pas d'erreur. Le bit 7 dit seulement qu'un avertissement du
# capteur existe (vitesse du ventilateur...) : la mesure reste valable.
MASQUE_CODE_ERREUR = 0x7F

ERREURS_CAPTEUR = {
    0x01: "mauvaise longueur de données",
    0x02: "commande inconnue",
    0x03: "pas le droit d'utiliser la commande",
    0x04: "paramètre refusé",
    0x28: "paramètre hors limites",
    0x43: "commande pas permise dans cet état",
}


class ErreurTrame(Exception):
    """Une trame coupée, abîmée (somme fausse) ou pas celle qu'on attend."""


class Reponse(NamedTuple):
    adresse: int
    commande: int
    etat: int
    donnees: bytes


def somme_de_controle(contenu: bytes) -> int:
    return (~sum(contenu)) & 0xFF


def echapper(contenu: bytes) -> bytes:
    sortie = bytearray()
    for octet in contenu:
        if octet in OCTETS_A_ECHAPPER:
            sortie += bytes([OCTET_ECHAPPEMENT, octet ^ MASQUE_ECHAPPEMENT])
        else:
            sortie.append(octet)
    return bytes(sortie)


def retirer_echappements(contenu: bytes) -> bytes:
    sortie = bytearray()
    suivant_echappe = False
    for octet in contenu:
        if suivant_echappe:
            sortie.append(octet ^ MASQUE_ECHAPPEMENT)
            suivant_echappe = False
        elif octet == OCTET_ECHAPPEMENT:
            suivant_echappe = True
        else:
            sortie.append(octet)
    if suivant_echappe:
        raise ErreurTrame("trame coupée au milieu d'un octet échappé")
    return bytes(sortie)


def construire_question(commande: int, donnees: bytes = b"") -> bytes:
    contenu = bytes([ADRESSE, commande, len(donnees)]) + donnees
    contenu += bytes([somme_de_controle(contenu)])
    return bytes([OCTET_FIN_TRAME]) + echapper(contenu) + bytes([OCTET_FIN_TRAME])


def construire_reponse(commande: int, donnees: bytes = b"", etat: int = 0) -> bytes:
    """Une réponse valable (pour le faux capteur et les tests)."""
    contenu = bytes([ADRESSE, commande, etat, len(donnees)]) + donnees
    contenu += bytes([somme_de_controle(contenu)])
    return bytes([OCTET_FIN_TRAME]) + echapper(contenu) + bytes([OCTET_FIN_TRAME])


def decoder_reponse(trame: bytes) -> Reponse:
    """Lève ErreurTrame si la trame est coupée, de travers ou à la somme fausse."""
    if len(trame) < 2 or trame[0] != OCTET_FIN_TRAME or trame[-1] != OCTET_FIN_TRAME:
        raise ErreurTrame("trame sans début ou sans fin")
    contenu = retirer_echappements(trame[1:-1])
    # adresse, commande, état, longueur, (données), somme
    if len(contenu) < 5:
        raise ErreurTrame("trame trop courte")
    if somme_de_controle(contenu[:-1]) != contenu[-1]:
        raise ErreurTrame("somme de contrôle fausse")
    longueur = contenu[3]
    if len(contenu) != 5 + longueur:
        raise ErreurTrame("longueur annoncée différente de la longueur reçue")
    return Reponse(contenu[0], contenu[1], contenu[2], contenu[4:-1])


def decouper_trames(octets: bytes) -> tuple[list[bytes], bytes]:
    """Les trames complètes (0x7E … 0x7E) de ces octets, et ce qui reste (début d'une trame)."""
    trames: list[bytes] = []
    debut: int | None = None
    for position, octet in enumerate(octets):
        if octet != OCTET_FIN_TRAME:
            continue
        if debut is None:
            debut = position
        elif position == debut + 1:
            # Deux 0x7E de suite : le second est peut-être le vrai début.
            debut = position
        else:
            trames.append(bytes(octets[debut : position + 1]))
            debut = None
    reste = bytes(octets[debut:]) if debut is not None else b""
    return trames, reste


def valeurs_mesurees(donnees: bytes) -> tuple[float, ...]:
    """Les 10 nombres (IEEE 754, poids fort d'abord) d'une réponse « read measured values »."""
    if len(donnees) != LONGUEUR_DONNEES_MESURE:
        raise ErreurTrame(f"{len(donnees)} octets de mesure au lieu de {LONGUEUR_DONNEES_MESURE}")
    return struct.unpack(f">{NOMBRE_VALEURS}f", donnees)


def donnees_de_mesure(valeurs: tuple[float, ...]) -> bytes:
    """L'inverse (pour le faux capteur et les tests)."""
    return struct.pack(f">{NOMBRE_VALEURS}f", *valeurs)
