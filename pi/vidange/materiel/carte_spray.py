"""Carte ESP32 n° 5 du spray, sur son bus RS485 à elle (`rs485_spray`) : sa table de registres
Modbus. C'est la langue commune avec le programme de la carte (tâche 39 bis) : la table complète,
expliquée, est dans spray/README.md. Toute modification se fait des deux côtés, et change la
VERSION de la table.

Lecture (fonction 4), registres 0 à 29, d'un coup :

| Registre | Contenu |
|---|---|
| 0 | signature 0x5350 (« SP ») |
| 1 | version de la table (VERSION) |
| 2 | compteur de démarrages de la carte (+1 à chaque démarrage, gardé en mémoire) |
| 3 | état (bits ETAT_...) |
| 4 | erreurs (bits ERREUR_...) |
| 5 | angle du bras, en dixièmes de degré (0 = rangé) |
| 6 | numéro du dernier ordre reçu (copie du registre 104) |
| 7 | suite de ce dernier ordre (SUITE_... : aucun, en cours, fait, refusé, échoué) |
| 8 | raison du refus de ce dernier ordre (REFUS_...), 0 sinon |
| 9 | temps depuis le dernier message du Pi, en ms (65 535 au plus) |
| 10 à 17 | mesure brute de chaque balance, 1 à 4 (signée, 32 bits, le mot fort d'abord) |
| 18 à 21 | poids de chaque flacon, 1 à 4, en dixièmes de gramme (signé) |
| 22 | dernière dose : emplacement (1 à 4 ; 0 = aucune depuis le démarrage) |
| 23 | dernière dose : poids demandé, en dixièmes de gramme |
| 24 | dernière dose : poids perdu par le flacon, en dixièmes de gramme (signé) |
| 25 | dernière dose : durée du pompage, en ms |
| 26 | dernière dose : résultat (DOSE_...) |
| 27 | numéro de la dernière dose finie (+1 à chaque dose finie) |
| 28 | vitesse des agitateurs en ce moment, en % |
| 29 | questions pour cette carte arrivées abîmées, depuis son démarrage |

Écriture (fonction 16), registres 100 à 104 :

| Registre | Contenu |
|---|---|
| 100 | battement : le Pi y écrit un nombre qui change (chaque écriture compte) |
| 101 | code de l'ordre (ORDRE_...) |
| 102 | paramètre 1 de l'ordre |
| 103 | paramètre 2 de l'ordre |
| 104 | numéro de l'ordre : la carte exécute l'ordre quand ce numéro change |

Un ordre s'écrit en une seule trame (101 à 104). Ce module ne fait que coder et décoder :
le Pi s'en sert dans vidange.spray, les tests dans la fausse carte (vidange.materiel.faux).
"""

from dataclasses import dataclass

from vidange.materiel.puces import ErreurMateriel

FONCTION_LECTURE = 4
NB_REGISTRES = 30
SIGNATURE = 0x5350
VERSION = 1
REGISTRE_BATTEMENT = 100
REGISTRE_ORDRE = 101
NB_FLACONS = 4

# Registre 3 : état.
ETAT_BRAS_RANGE = 1  # le capteur bras_spray_range voit le bras
ETAT_BRAS_SORTI = 2  # le bras est arrêté à l'angle demandé (ordre « sortir »)
ETAT_BRAS_BOUGE = 4
ETAT_ORIGINE_FAITE = 8
ETAT_SPRAY_EN_COURS = 16  # de l'ouverture de l'air de la buse à sa fermeture
ETAT_NETTOYAGE_EN_COURS = 32
ETAT_AGITATEURS = 64
ETAT_EXEMPLE = 128  # programme fabriqué avec des réglages d'exemple
ETAT_SILENCE_PI = 256  # la carte s'est arrêtée seule : le Pi s'est tu trop longtemps
ETAT_ARRET_IMMEDIAT = 512  # arrêt immédiat reçu (jusqu'au prochain ordre)

# Registre 4 : erreurs. Balance muette : en direct ; les autres restent jusqu'à l'ordre
# « effacer les erreurs » (ou un nouveau geste du bras réussi).
ERREUR_BALANCE_MUETTE = (1, 2, 4, 8)  # HX711 des flacons 1 à 4
ERREUR_BALANCE_INSTABLE = (16, 32, 64, 128)
ERREUR_BRAS_PAS_RANGE = 256  # capteur pas vu dans le temps maximum (ranger, origine)
ERREUR_BRAS_PAS_SORTI = 512  # angle pas atteint dans le temps maximum
ERREUR_BRAS_POUSSE = 1024  # le capteur a perdu le bras sans ordre (bras poussé ?)
ERREUR_PILOTE_BRAS = 2048  # le pilote TMC2209 du bras ne répond pas (UART)

# Registre 7 : suite du dernier ordre.
SUITE_AUCUN = 0
SUITE_EN_COURS = 1
SUITE_FAIT = 2
SUITE_REFUSE = 3
SUITE_ECHOUE = 4  # commencé mais pas fini (voir les erreurs : bras pas arrivé...)

# Registre 8 : raison du refus.
REFUS = {
    0: "",
    1: "ordre inconnu de la carte",
    2: "paramètre hors des limites",
    3: "prise d'origine du bras pas faite",
    4: "pas de battement récent du Pi",
    5: "la carte fait déjà un geste",
    6: "balance du flacon muette ou instable",
    7: "bras du spray pas sorti",
    8: "erreur du bras pas effacée",
}

# Registre 101 : les ordres.
ORDRE_ORIGINE = 1  # prise d'origine du bras (vers « rangé » jusqu'au capteur : 0°)
ORDRE_SORTIR = 2  # paramètre 1 : angle en dixièmes de degré
ORDRE_RANGER = 3
ORDRE_SPRAY = 4  # paramètre 1 : emplacement (1 à 4) ; paramètre 2 : dose en dixièmes de g
ORDRE_NETTOYER = 5
ORDRE_AGITER = 6  # paramètre 1 : vitesse en % ; paramètre 2 : durée en s (0 : arrêt)
ORDRE_ARRET = 7  # arrêt immédiat : pompes, air, nettoyage, agitateurs ; le bras s'arrête
ORDRE_EFFACER = 8  # effacer les erreurs

# Registre 26 : résultat de la dernière dose.
DOSE_AUCUNE = 0
DOSE_EN_COURS = 1
DOSE_ATTEINTE = 2
DOSE_TEMPS_MAX = 3  # pompe arrêtée au temps maximum : chasse faite, bras rangé par la carte
DOSE_INTERROMPUE = 4  # arrêt immédiat ou silence du Pi
DOSE_REFUSEE = 5


@dataclass(frozen=True)
class Flacon:
    brut: int
    grammes: float
    muette: bool
    instable: bool


@dataclass(frozen=True)
class Dose:
    emplacement: int
    demandee_g: float
    perdue_g: float
    duree_s: float
    resultat: int
    numero: int


@dataclass(frozen=True)
class EtatSpray:
    """Ce que dit la carte, en une lecture."""

    version: int
    demarrages: int
    etat: int
    erreurs: int
    angle_deg: float
    numero_ordre: int
    suite_ordre: int
    refus: int
    silence_pi_ms: int
    flacons: tuple[Flacon, ...]
    dose: Dose
    agitateurs_pct: int
    trames_abimees: int

    @property
    def bras_range(self) -> bool:
        return bool(self.etat & ETAT_BRAS_RANGE)

    @property
    def bras_sorti(self) -> bool:
        return bool(self.etat & ETAT_BRAS_SORTI)

    @property
    def bras_bouge(self) -> bool:
        return bool(self.etat & ETAT_BRAS_BOUGE)

    @property
    def origine_faite(self) -> bool:
        return bool(self.etat & ETAT_ORIGINE_FAITE)

    @property
    def spray_en_cours(self) -> bool:
        return bool(self.etat & ETAT_SPRAY_EN_COURS)

    @property
    def nettoyage_en_cours(self) -> bool:
        return bool(self.etat & ETAT_NETTOYAGE_EN_COURS)

    @property
    def exemple(self) -> bool:
        return bool(self.etat & ETAT_EXEMPLE)

    @property
    def raison_du_refus(self) -> str:
        return REFUS.get(self.refus, f"refus n° {self.refus}")

    def erreurs_du_bras(self) -> list[str]:
        textes = {
            ERREUR_BRAS_PAS_RANGE: "bras pas rangé dans le temps maximum",
            ERREUR_BRAS_PAS_SORTI: "bras pas arrivé à son angle dans le temps maximum",
            ERREUR_BRAS_POUSSE: "le capteur « bras rangé » a perdu le bras sans ordre",
            ERREUR_PILOTE_BRAS: "le pilote du moteur du bras ne répond pas",
        }
        return [texte for bit, texte in textes.items() if self.erreurs & bit]


def _signe_16(valeur: int) -> int:
    return valeur - 0x10000 if valeur >= 0x8000 else valeur


def _signe_32(fort: int, faible: int) -> int:
    valeur = fort << 16 | faible
    return valeur - (1 << 32) if valeur >= 1 << 31 else valeur


def decoder(registres: list[int]) -> EtatSpray:
    """Les 30 registres lus → l'état ; ErreurMateriel si ce n'est pas la carte du spray, ou une
    autre version de la table."""
    if len(registres) != NB_REGISTRES or registres[0] != SIGNATURE:
        trouve = f"0x{registres[0]:04X}" if registres else "rien"
        raise ErreurMateriel(
            f"l'appareil à cette adresse n'est pas la carte du spray (signature {trouve}, "
            f"0x{SIGNATURE:04X} attendue : mauvaise adresse ou mauvais adaptateur ?)"
        )
    if registres[1] != VERSION:
        raise ErreurMateriel(
            f"carte du spray : table des registres n° {registres[1]}, le Pi parle la n° "
            f"{VERSION} (programme de la carte ou du Pi pas à jour : spray/README.md)"
        )
    erreurs = registres[4]
    flacons = tuple(
        Flacon(
            brut=_signe_32(registres[10 + 2 * i], registres[11 + 2 * i]),
            grammes=_signe_16(registres[18 + i]) / 10,
            muette=bool(erreurs & ERREUR_BALANCE_MUETTE[i]),
            instable=bool(erreurs & ERREUR_BALANCE_INSTABLE[i]),
        )
        for i in range(NB_FLACONS)
    )
    return EtatSpray(
        version=registres[1],
        demarrages=registres[2],
        etat=registres[3],
        erreurs=erreurs,
        angle_deg=registres[5] / 10,
        numero_ordre=registres[6],
        suite_ordre=registres[7],
        refus=registres[8],
        silence_pi_ms=registres[9],
        flacons=flacons,
        dose=Dose(
            emplacement=registres[22],
            demandee_g=registres[23] / 10,
            perdue_g=_signe_16(registres[24]) / 10,
            duree_s=registres[25] / 1000,
            resultat=registres[26],
            numero=registres[27],
        ),
        agitateurs_pct=registres[28],
        trames_abimees=registres[29],
    )


def _mot(valeur: float) -> int:
    return round(valeur) & 0xFFFF


def encoder(etat: EtatSpray) -> list[int]:
    """L'inverse (pour la fausse carte des tests et du simulateur)."""
    registres = [0] * NB_REGISTRES
    registres[0] = SIGNATURE
    registres[1] = etat.version
    registres[2] = etat.demarrages & 0xFFFF
    registres[3] = etat.etat
    registres[4] = etat.erreurs
    registres[5] = _mot(etat.angle_deg * 10)
    registres[6] = etat.numero_ordre & 0xFFFF
    registres[7] = etat.suite_ordre
    registres[8] = etat.refus
    registres[9] = min(etat.silence_pi_ms, 0xFFFF)
    for i, flacon in enumerate(etat.flacons):
        brut = flacon.brut & 0xFFFFFFFF
        registres[10 + 2 * i] = brut >> 16
        registres[11 + 2 * i] = brut & 0xFFFF
        registres[18 + i] = _mot(flacon.grammes * 10)
    dose = etat.dose
    registres[22] = dose.emplacement
    registres[23] = _mot(dose.demandee_g * 10)
    registres[24] = _mot(dose.perdue_g * 10)
    registres[25] = min(round(dose.duree_s * 1000), 0xFFFF)
    registres[26] = dose.resultat
    registres[27] = dose.numero & 0xFFFF
    registres[28] = etat.agitateurs_pct
    registres[29] = etat.trames_abimees & 0xFFFF
    return registres


def ordre(code: int, numero: int, parametre_1: int = 0, parametre_2: int = 0) -> list[int]:
    """Les registres 101 à 104 d'un ordre (le numéro en dernier : il déclenche l'ordre)."""
    for valeur in (parametre_1, parametre_2):
        if not 0 <= valeur <= 0xFFFF:
            raise ValueError(f"paramètre d'un ordre du spray hors de 0 à 65 535 : {valeur}")
    return [code, parametre_1, parametre_2, numero & 0xFFFF]
