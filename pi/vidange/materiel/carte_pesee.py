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
| 8 | plateau : 1 = reed fermé (au poste), 2 = 5 V de la recharge présent (*), 4 = sur l'USB-C |
| 9 | tension de l'accu du plateau, en mV (dernière trame) |
| 10 | niveau de l'accu, en % (calculé par le plateau) |
| 11 | force du signal radio, en dBm + 200 (120 = −80 dBm) |
| 12 | trames radio perdues (numéros sautés), depuis le démarrage de la boîte |

(*) 5 V de la recharge sans contact présent, pas « en charge » : il reste vrai accu plein.

Seule la carte du plateau du remplissage a de plus l'I2C du boîtier du chariot : les servos
(PCA9685) et le capteur de distance VL6180X (tâche 40 bis, pesee/src/plateau.h). Ses registres en
plus, après les registres 0 à 7 qui ne changent pas (les autres cartes répondent « registre
inconnu » si on les lit) :

| Registre | Contenu | Écriture |
|---|---|---|
| 8 | distance du ToF, en mm (65 535 = pas de bonne mesure) | non |
| 9 | état du ToF : 0 = bonne, 1 à 15 = code de la puce, 256 = pas encore, 512 = muet | non |
| 10 | âge de la dernière mesure du ToF, en ms (65 535 au plus) | non |
| 11 | compteur de démarrages de la carte (CHANGE à chaque démarrage, pas toujours de +1) | non |
| 12 | état de l'I2C (bits I2C_...) | non |
| 13 | transactions I2C sans réponse depuis le démarrage | non |
| 14 | temps depuis le dernier ordre du Pi, en ms (65 535 au plus) | non |
| 15 | nombre de voies de servo du programme de la carte | non |
| 16 et + | angle de chaque voie, en dixièmes de degré (signé ; 0x8000 = coupée) | fonction 16 |

Le Pi lit les registres 8 à 15 + nombre de voies d'un coup, et écrit les angles en une trame.
Toute écriture acceptée est un « ordre » ; le Pi en renvoie au moins un toutes les secondes (même
sans changer d'angle) : sans ordre depuis plus de 2 s la carte garde les angles et le dit (bit
I2C_PI_SILENCIEUX). Au démarrage de la carte, la PCA9685 est sortie coupée : si le compteur de
démarrages a changé, le Pi renvoie tous les angles.
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
PLATEAU_RECHARGE_PRESENTE = 2
PLATEAU_SUR_USB = 4
# Registre 11 : force du signal en dBm + ce décalage.
DECALAGE_SIGNAL_DBM = 200
# Le boîtier du chariot (servos et capteur de distance), sur la carte du plateau du remplissage.
REGISTRE_TOF_MM = 8
REGISTRE_ANGLES = 16
NB_REGISTRES_ENTETE_PLATEAU = 16  # registres 0 à 15 ; les angles suivent
FONCTION_ECRITURE = 16
TOF_PAS_DE_MESURE = 0xFFFF
TOF_ETAT_PAS_ENCORE = 256
TOF_ETAT_MUET = 512
ANGLE_COUPE = 0x8000  # registre d'un angle : sortie coupée (le servo est libre)
# Registre 12.
I2C_PCA9685_MUETTE = 1
I2C_TOF_MUET = 2
I2C_AUCUN_ORDRE = 4
I2C_PI_SILENCIEUX = 8
I2C_PCA9685_DEMARRE_PAS = 16


@dataclass(frozen=True)
class Plateau:
    """Ce que la boîte du poste du fût dit du plateau (dernière trame radio reçue)."""

    au_poste: bool
    recharge_presente: bool
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
            recharge_presente=bool(plateau & PLATEAU_RECHARGE_PRESENTE),
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
        | (PLATEAU_RECHARGE_PRESENTE if plateau.recharge_presente else 0)
        | (PLATEAU_SUR_USB if plateau.sur_usb else 0)
    )
    return registres + [
        bits,
        plateau.accu_mv & 0xFFFF,
        plateau.accu_pct & 0xFFFF,
        max(0, min(plateau.signal_dbm + DECALAGE_SIGNAL_DBM, 0xFFFF)),
        plateau.trames_perdues & 0xFFFF,
    ]


# --------------------------------------------- boîtier du chariot (carte du plateau)


@dataclass(frozen=True)
class BoitierChariot:
    """Ce que la carte du plateau du remplissage dit de son I2C (registres 8 et suivants)."""

    # Distance du ToF (mm) ; None s'il n'y a pas de bonne mesure (voir etat_tof).
    distance_mm: int | None
    # 0 = bonne mesure, 1 à 15 = code de la puce, TOF_ETAT_PAS_ENCORE, TOF_ETAT_MUET.
    etat_tof: int
    age_tof_ms: int
    demarrages: int
    pca9685_muette: bool
    tof_muet: bool
    # Aucun ordre du Pi depuis le démarrage de la carte : tous les servos sont sortie coupée.
    aucun_ordre: bool
    # Plus d'ordre du Pi depuis plus de 2 s : la carte GARDE les angles (aucun mouvement).
    pi_silencieux: bool
    pca9685_demarre_pas: bool
    echecs_i2c: int
    silence_pi_ms: int
    # Un angle par voie, en degrés ; None = sortie coupée.
    angles_deg: tuple[float | None, ...]


def registre_angle(angle_deg: float | None) -> int:
    """Angle en degrés (None : sortie coupée) → valeur du registre, en dixièmes de degré."""
    if angle_deg is None:
        return ANGLE_COUPE
    dix = round(angle_deg * 10)
    if not -0x7FFF <= dix <= 0x7FFF:
        raise ErreurMateriel(f"angle de servo {angle_deg:g}° impossible à écrire dans la carte")
    return dix & 0xFFFF


def angle_du_registre(valeur: int) -> float | None:
    if valeur == ANGLE_COUPE:
        return None
    return (valeur - 0x10000 if valeur >= 0x8000 else valeur) / 10


def decoder_boitier(registres: list[int], nb_voies: int) -> BoitierChariot:
    """Les registres 8 à 15 + `nb_voies` (lus d'un coup) → l'état du boîtier ; ErreurMateriel si
    la carte n'a pas le nombre de voies attendu (programme pas fait avec les réglages du Pi)."""
    attendus = NB_REGISTRES_ENTETE_PLATEAU - REGISTRE_TOF_MM + nb_voies
    if len(registres) != attendus:
        raise ErreurMateriel(
            f"boîtier du chariot : {attendus} registres attendus, {len(registres)} reçus"
        )
    (distance, etat_tof, age, demarrages, i2c, echecs, silence, voies) = registres[:8]
    if voies != nb_voies:
        raise ErreurMateriel(
            f"la carte a {voies} voies de servo, pesees.yaml en compte {nb_voies} : refaire le "
            "programme de la carte avec les réglages actuels (pesee/README.md)"
        )
    return BoitierChariot(
        distance_mm=None if distance == TOF_PAS_DE_MESURE else distance,
        etat_tof=etat_tof,
        age_tof_ms=age,
        demarrages=demarrages,
        pca9685_muette=bool(i2c & I2C_PCA9685_MUETTE),
        tof_muet=bool(i2c & I2C_TOF_MUET),
        aucun_ordre=bool(i2c & I2C_AUCUN_ORDRE),
        pi_silencieux=bool(i2c & I2C_PI_SILENCIEUX),
        pca9685_demarre_pas=bool(i2c & I2C_PCA9685_DEMARRE_PAS),
        echecs_i2c=echecs,
        silence_pi_ms=silence,
        angles_deg=tuple(angle_du_registre(v) for v in registres[8:]),
    )


def encoder_boitier(boitier: BoitierChariot) -> list[int]:
    """L'inverse (pour les fausses cartes des tests) : registres 8 à 15 + une voie par angle."""
    i2c = (
        (I2C_PCA9685_MUETTE if boitier.pca9685_muette else 0)
        | (I2C_TOF_MUET if boitier.tof_muet else 0)
        | (I2C_AUCUN_ORDRE if boitier.aucun_ordre else 0)
        | (I2C_PI_SILENCIEUX if boitier.pi_silencieux else 0)
        | (I2C_PCA9685_DEMARRE_PAS if boitier.pca9685_demarre_pas else 0)
    )
    return [
        TOF_PAS_DE_MESURE if boitier.distance_mm is None else boitier.distance_mm,
        boitier.etat_tof,
        min(boitier.age_tof_ms, 0xFFFF),
        boitier.demarrages & 0xFFFF,
        i2c,
        boitier.echecs_i2c & 0xFFFF,
        min(boitier.silence_pi_ms, 0xFFFF),
        len(boitier.angles_deg),
        *(registre_angle(angle) for angle in boitier.angles_deg),
    ]
