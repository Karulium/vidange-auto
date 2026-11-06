"""Trames du capteur d'ozone Winsen ZE25-O3 (liaison série UART, via un convertisseur RS485).

ATTENTION : écrit de mémoire d'après la notice Winsen des capteurs de la série ZE, sans la
notice sous les yeux. À VÉRIFIER sur la notice papier du ZE25-O3 avant le premier essai
(voir pi/systeme/essai-ozone.md). Ce fichier ne contient que ce qui est fixé par le protocole ;
tout ce qui dépend du capteur ou de la machine (vitesse, positions de la valeur, pas en ppm,
plafond, délais, question) est dans `docs/entrees-sorties.yaml`.

Une trame fait 9 octets :
  octet 0      : 0xFF (début)
  octets 1 à 7 : le contenu (le gaz, l'unité, la valeur, la pleine échelle...)
  octet 8      : somme de contrôle = (inverse de la somme des octets 1 à 7) + 1, sur un octet.

Deux modes (au choix, dans la liste) :
  - envoi automatique : le capteur envoie une trame environ chaque seconde, tout seul ;
  - question-réponse  : le Pi envoie une trame de 9 octets (la « question », même forme, même
    somme de contrôle) et le capteur répond par une trame.
"""

LONGUEUR_TRAME = 9
OCTET_DEBUT = 0xFF
# Les octets qui comptent dans la somme de contrôle : de 1 à 7 compris.
PREMIER_OCTET_SOMME = 1
DERNIER_OCTET_SOMME = 7
OCTET_SOMME = 8


def somme_de_controle(trame: bytes) -> int:
    """Somme de contrôle des octets 1 à 7 d'une trame (au moins 8 octets)."""
    total = sum(trame[PREMIER_OCTET_SOMME : DERNIER_OCTET_SOMME + 1])
    return ((~total & 0xFF) + 1) & 0xFF


def trame_valable(trame: bytes) -> bool:
    return (
        len(trame) == LONGUEUR_TRAME
        and trame[0] == OCTET_DEBUT
        and trame[OCTET_SOMME] == somme_de_controle(trame)
    )


def construire_trame(contenu: dict[int, int]) -> bytes:
    """Une trame valable : les octets donnés (position → valeur, de 1 à 7), les autres à 0."""
    trame = bytearray(LONGUEUR_TRAME)
    trame[0] = OCTET_DEBUT
    for position, octet in contenu.items():
        trame[position] = octet
    trame[OCTET_SOMME] = somme_de_controle(bytes(trame))
    return bytes(trame)


def valeur_brute(trame: bytes, positions: tuple[int, int]) -> int:
    """Le nombre (sur 2 octets : poids fort d'abord) lu aux positions données."""
    return trame[positions[0]] * 256 + trame[positions[1]]


def trame_avec_valeur(brut: int, positions: tuple[int, int]) -> bytes:
    """Une trame valable qui porte ce nombre brut aux positions données."""
    brut = max(0, min(brut, 0xFFFF))
    return construire_trame({positions[0]: brut >> 8, positions[1]: brut & 0xFF})
