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

La boîte du poste du fût (ESP32-C3 qui reçoit par radio les mesures du plateau de pesée, tâche
17 bis, programme : tâche 17 ter) répond sur le même bus avec les mêmes registres 0 à 7, sauf :
la mesure est la moyenne de 5 faite par le plateau (2 par seconde), le registre 4 a un bit de
plus (4 = radio du plateau muette : rien reçu depuis 2 s), et la signature est 0x5046 (« PF »).
Elle a 5 registres de plus :

| Registre | Contenu |
|---|---|
| 8 | plateau : 1 = reed fermé (au poste), 2 = recharge en cours, 4 = alimenté par l'USB-C |
| 9 | tension de l'accu du plateau, en mV (dernière trame) |
| 10 | niveau de l'accu, en % (calculé par le plateau) |
| 11 | force du signal radio, en dBm + 200 (120 = −80 dBm) |
| 12 | trames radio perdues (numéros sautés), depuis le démarrage de la boîte |
"""

from dataclasses import dataclass, replace

from vidange.materiel.puces import ErreurMateriel

FONCTION = 4
NB_REGISTRES = 8
SIGNATURE = 0x5053
ETAT_HX711_MUET = 1
ETAT_EXEMPLE = 2
# La boîte du poste du fût.
NB_REGISTRES_BOITE = 13
SIGNATURE_BOITE = 0x5046
ETAT_RADIO_MUETTE = 4
PLATEAU_AU_POSTE = 1
PLATEAU_EN_RECHARGE = 2
PLATEAU_SUR_USB = 4
# Registre 11 : force du signal en dBm + ce décalage.
DECALAGE_SIGNAL_DBM = 200


@dataclass(frozen=True)
class Plateau:
    """Ce que la boîte du poste du fût dit du plateau (dernière trame radio reçue)."""

    au_poste: bool
    en_recharge: bool
    sur_usb: bool
    accu_mv: int
    accu_pct: int
    signal_dbm: int
    trames_perdues: int


@dataclass(frozen=True)
class MesureCarte:
    brut: int
    numero: int
    age_ms: int
    hx711_muet: bool
    exemple: bool
    par_seconde: int
    trames_abimees: int
    # Boîte du poste du fût seulement.
    radio_muette: bool = False
    plateau: Plateau | None = None


def decoder(registres: list[int]) -> MesureCarte:
    """Les registres lus → la mesure ; ErreurMateriel si ce n'est pas une carte de pesée."""
    if len(registres) != NB_REGISTRES or registres[7] != SIGNATURE:
        raise ErreurMateriel(
            "l'appareil à cette adresse n'est pas une carte de pesée (mauvaise adresse, ou "
            "autre appareil sur le bus ?)"
        )
    return _decoder_mesure(registres)


def decoder_boite(registres: list[int]) -> MesureCarte:
    """Les 13 registres de la boîte du poste du fût → la mesure, avec le plateau ;
    ErreurMateriel si ce n'est pas elle (une carte de pesée RP2040 dit 0x5053)."""
    if len(registres) != NB_REGISTRES_BOITE or registres[7] != SIGNATURE_BOITE:
        trouve = f"0x{registres[7]:04X}" if len(registres) > 7 else "rien"
        raise ErreurMateriel(
            f"l'appareil à cette adresse n'est pas la boîte du poste du fût (signature {trouve}, "
            f"0x{SIGNATURE_BOITE:04X} attendue : mauvaise adresse, ou carte de pesée RP2040 ?)"
        )
    mesure = _decoder_mesure(registres)
    plateau = registres[8]
    return replace(
        mesure,
        radio_muette=bool(registres[4] & ETAT_RADIO_MUETTE),
        plateau=Plateau(
            au_poste=bool(plateau & PLATEAU_AU_POSTE),
            en_recharge=bool(plateau & PLATEAU_EN_RECHARGE),
            sur_usb=bool(plateau & PLATEAU_SUR_USB),
            accu_mv=registres[9],
            accu_pct=registres[10],
            signal_dbm=registres[11] - DECALAGE_SIGNAL_DBM,
            trames_perdues=registres[12],
        ),
    )


def _decoder_mesure(registres: list[int]) -> MesureCarte:
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


def encoder(mesure: MesureCarte, signature: int = SIGNATURE) -> list[int]:
    """L'inverse (pour les fausses cartes des tests) : 8 registres, ou 13 avec le plateau."""
    brut = mesure.brut & 0xFFFFFFFF
    etat = (
        (ETAT_HX711_MUET if mesure.hx711_muet else 0)
        | (ETAT_EXEMPLE if mesure.exemple else 0)
        | (ETAT_RADIO_MUETTE if mesure.radio_muette else 0)
    )
    registres = [
        brut >> 16,
        brut & 0xFFFF,
        mesure.numero & 0xFFFF,
        min(mesure.age_ms, 0xFFFF),
        etat,
        mesure.par_seconde,
        mesure.trames_abimees & 0xFFFF,
        signature,
    ]
    plateau = mesure.plateau
    if plateau is None:
        return registres
    bits = (
        (PLATEAU_AU_POSTE if plateau.au_poste else 0)
        | (PLATEAU_EN_RECHARGE if plateau.en_recharge else 0)
        | (PLATEAU_SUR_USB if plateau.sur_usb else 0)
    )
    return registres + [
        bits,
        plateau.accu_mv & 0xFFFF,
        plateau.accu_pct & 0xFFFF,
        max(0, min(plateau.signal_dbm + DECALAGE_SIGNAL_DBM, 0xFFFF)),
        plateau.trames_perdues & 0xFFFF,
    ]
