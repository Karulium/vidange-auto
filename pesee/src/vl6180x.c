#include "vl6180x.h"

// Registres (fiche ST du VL6180X, 16 bits d'index).
#define SYSTEM_FRESH_OUT_OF_RESET 0x016
#define SYSTEM_INTERRUPT_CLEAR 0x015
#define SYSRANGE_START 0x018
#define RESULT_RANGE_STATUS 0x04D
#define RESULT_INTERRUPT_STATUS 0x04F
#define RESULT_RANGE_VAL 0x062
// Bits 2 à 0 de l'état d'interruption : 4 = mesure de distance prête.
#define MESURE_PRETE 4
#define EFFACER_TOUT 0x07
#define LANCER_UNE_MESURE 0x01

typedef struct {
    uint16_t registre;
    uint8_t valeur;
} reglage_t;

// Réglages obligatoires de la puce après un reset (note d'application AN4545 de ST), suivis des
// réglages usuels de la distance. Ce sont les chiffres de la puce, pas ceux de la machine.
static const reglage_t REGLAGES[] = {
    {0x0207, 0x01}, {0x0208, 0x01}, {0x0096, 0x00}, {0x0097, 0xFD}, {0x00E3, 0x00},
    {0x00E4, 0x04}, {0x00E5, 0x02}, {0x00E6, 0x01}, {0x00E7, 0x03}, {0x00F5, 0x02},
    {0x00D9, 0x05}, {0x00DB, 0xCE}, {0x00DC, 0x03}, {0x00DD, 0xF8}, {0x009F, 0x00},
    {0x00A3, 0x3C}, {0x00B7, 0x00}, {0x00BB, 0x3C}, {0x00B2, 0x09}, {0x00CA, 0x09},
    {0x0198, 0x01}, {0x01B0, 0x17}, {0x01AD, 0x00}, {0x00FF, 0x05}, {0x0100, 0x05},
    {0x0199, 0x05}, {0x01A6, 0x1B}, {0x01AC, 0x3E}, {0x01A7, 0x1F}, {0x0030, 0x00},
    // Usuels : interruption sur « mesure prête », moyenne, recalibrage.
    {0x0011, 0x10}, {0x010A, 0x30}, {0x0031, 0xFF}, {0x002E, 0x01}, {0x0014, 0x24},
    // Fini : la puce n'est plus « sortie de reset ».
    {SYSTEM_FRESH_OUT_OF_RESET, 0x00},
};
#define NB_REGLAGES (sizeof(REGLAGES) / sizeof(REGLAGES[0]))

void vl6180x_init(vl6180x_t *t, const vl6180x_config_t *config, uint64_t t_us) {
    t->config = *config;
    t->phase = TOF_LIRE_REPOS;
    t->reglage = 0;
    t->muet = false;
    t->une_mesure = false;
    t->distance_mm = 0;
    t->code = 0;
    t->heure_us = t_us;
    t->prochain_us = t_us;
    t->depart_us = t_us;
    t->echecs = 0;
}

static bool ecrire_registre(const i2c_bus_t *bus, uint8_t adresse, uint16_t registre,
                            uint8_t valeur) {
    uint8_t octets[3] = {(uint8_t)(registre >> 8), (uint8_t)(registre & 0xFF), valeur};
    return bus->ecrire(bus->contexte, adresse, octets, 3);
}

static bool lire_registre(const i2c_bus_t *bus, uint8_t adresse, uint16_t registre,
                          uint8_t *valeur) {
    uint8_t index[2] = {(uint8_t)(registre >> 8), (uint8_t)(registre & 0xFF)};
    return bus->lire(bus->contexte, adresse, index, 2, valeur, 1);
}

static void echec(vl6180x_t *t, uint64_t t_us) {
    t->echecs++;
    t->muet = true;
    // Le capteur a peut-être perdu son alimentation : tout reprendre au début, plus tard.
    t->phase = TOF_LIRE_REPOS;
    t->reglage = 0;
    t->prochain_us = t_us + (uint64_t)t->config.reessai_ms * 1000;
}

bool vl6180x_pas(vl6180x_t *t, const i2c_bus_t *bus, uint64_t t_us) {
    if (t_us < t->prochain_us) {
        return false;
    }
    uint8_t adresse = t->config.adresse;
    uint8_t v = 0;
    bool ok = true;
    switch (t->phase) {
    case TOF_LIRE_REPOS:
        ok = lire_registre(bus, adresse, SYSTEM_FRESH_OUT_OF_RESET, &v);
        if (ok) {
            // Déjà réglée (pas de reset depuis) : directement les mesures.
            t->phase = v == 1 ? TOF_REGLAGES : TOF_REPOS;
            t->reglage = 0;
        }
        break;
    case TOF_REGLAGES:
        ok = ecrire_registre(bus, adresse, REGLAGES[t->reglage].registre,
                             REGLAGES[t->reglage].valeur);
        if (ok && ++t->reglage >= NB_REGLAGES) {
            t->phase = TOF_REPOS;
        }
        break;
    case TOF_REPOS:
        ok = ecrire_registre(bus, adresse, SYSRANGE_START, LANCER_UNE_MESURE);
        if (ok) {
            t->phase = TOF_ATTENTE;
            t->depart_us = t_us;
            t->prochain_us = t_us + (uint64_t)t->config.sondage_ms * 1000;
        }
        break;
    case TOF_ATTENTE:
        ok = lire_registre(bus, adresse, RESULT_INTERRUPT_STATUS, &v);
        if (ok && (v & 7) == MESURE_PRETE) {
            t->phase = TOF_LIRE_DIST;
        } else if (ok) {
            t->prochain_us = t_us + (uint64_t)t->config.sondage_ms * 1000;
            if (t_us - t->depart_us > (uint64_t)t->config.delai_max_ms * 1000) {
                // Lancée mais jamais finie : le capteur est muet.
                ok = false;
            }
        }
        break;
    case TOF_LIRE_DIST:
        ok = lire_registre(bus, adresse, RESULT_RANGE_VAL, &v);
        if (ok) {
            t->distance_mm = v;
            t->phase = TOF_LIRE_CODE;
        }
        break;
    case TOF_LIRE_CODE:
        ok = lire_registre(bus, adresse, RESULT_RANGE_STATUS, &v);
        if (ok) {
            t->code = v >> 4;
            t->une_mesure = true;
            t->heure_us = t_us;
            t->phase = TOF_EFFACER;
        }
        break;
    case TOF_EFFACER:
        ok = ecrire_registre(bus, adresse, SYSTEM_INTERRUPT_CLEAR, EFFACER_TOUT);
        if (ok) {
            t->phase = TOF_REPOS;
            t->prochain_us = t->depart_us + (uint64_t)t->config.periode_ms * 1000;
        }
        break;
    }
    if (!ok) {
        echec(t, t_us);
    } else {
        t->muet = false;
    }
    return true;
}

uint16_t vl6180x_etat(const vl6180x_t *t) {
    if (t->muet) {
        return TOF_ETAT_MUET;
    }
    return t->une_mesure ? t->code : TOF_ETAT_PAS_ENCORE;
}

uint16_t vl6180x_distance(const vl6180x_t *t) {
    return t->une_mesure && !t->muet && t->code == 0 ? t->distance_mm : 0xFFFF;
}
