"""Carte de pesée RP2040 + HX711 sur le bus RS485 des pesées : sa table de registres Modbus.

La même table que dans le programme de la carte (pesee/src/mesures.h) :

| Registre | Contenu |
|---|---|
| 0 et 1 | dernière mesure brute du HX711 (signée, 32 bits, le mot fort d'abord) |
| 2 | numéro de cette mesure (+1 à chaque mesure, repart à 0 après 65 535) |
| 3 | âge de cette mesure en ms (65 535 au plus) |
| 4 | état : 1 = HX711 muet (débranché ?), 2 = programme fait avec des réglages d'exemple |
| 5 | mesures faites pendant la dernière seconde (80 attendues) |
| 6 | questions arrivées abîmées depuis le démarrage de la carte |
| 7 | signature 0x5053 (« PS ») |

Le Pi lit les 8 d'un coup (fonction 4). Le poids en kilogrammes est calculé par le Pi
(vidange.pesees) : la carte ne donne que la mesure brute.
"""

from dataclasses import dataclass

from vidange.materiel.puces import ErreurMateriel

FONCTION = 4
NB_REGISTRES = 8
SIGNATURE = 0x5053
ETAT_HX711_MUET = 1
ETAT_EXEMPLE = 2


@dataclass(frozen=True)
class MesureCarte:
    brut: int
    numero: int
    age_ms: int
    hx711_muet: bool
    exemple: bool
    par_seconde: int
    trames_abimees: int


def decoder(registres: list[int]) -> MesureCarte:
    """Les registres lus → la mesure ; ErreurMateriel si ce n'est pas une carte de pesée."""
    if len(registres) != NB_REGISTRES or registres[7] != SIGNATURE:
        raise ErreurMateriel(
            "l'appareil à cette adresse n'est pas une carte de pesée (mauvaise adresse, ou "
            "autre appareil sur le bus ?)"
        )
    brut = registres[0] << 16 | registres[1]
    if brut >= 1 << 31:
        brut -= 1 << 32
    etat = registres[4]
    return MesureCarte(
        brut=brut,
        numero=registres[2],
        age_ms=registres[3],
        hx711_muet=bool(etat & ETAT_HX711_MUET),
        exemple=bool(etat & ETAT_EXEMPLE),
        par_seconde=registres[5],
        trames_abimees=registres[6],
    )


def encoder(mesure: MesureCarte) -> list[int]:
    """L'inverse (pour la fausse carte des tests)."""
    brut = mesure.brut & 0xFFFFFFFF
    etat = (ETAT_HX711_MUET if mesure.hx711_muet else 0) | (ETAT_EXEMPLE if mesure.exemple else 0)
    return [
        brut >> 16,
        brut & 0xFFFF,
        mesure.numero & 0xFFFF,
        min(mesure.age_ms, 0xFFFF),
        etat,
        mesure.par_seconde,
        mesure.trames_abimees & 0xFFFF,
        SIGNATURE,
    ]
