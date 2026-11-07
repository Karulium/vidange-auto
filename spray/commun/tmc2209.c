#include "tmc2209.h"

#define SYNCHRO 0x05
#define ADRESSE_MAITRE 0xFF

// GCONF : pdn_disable (bit 6 : PDN_UART sert à l'UART), mstep_reg_select (bit 7 : micro-pas
// par MRES), multistep_filt (bit 8). I_scale_analog (bit 0) à 0 : courant par IRUN, pas par VREF.
#define GCONF_PDN_DISABLE (1u << 6)
#define GCONF_MSTEP_REG_SELECT (1u << 7)
#define GCONF_MULTISTEP_FILT (1u << 8)
// CHOPCONF de la notice au démarrage : TOFF 3, HSTRT 5, intpol (bit 28 : 256 micro-pas vus
// par le moteur, quels que soient les pas reçus).
#define CHOPCONF_USINE 0x10000053u
#define CHOPCONF_VSENSE (1u << 17)
#define CHOPCONF_MRES_DECALAGE 24
#define CHOPCONF_MRES_MASQUE (0xFu << CHOPCONF_MRES_DECALAGE)
// IHOLDDELAY : descente du courant à l'arrêt en douceur (environ 2^18 horloges par cran).
#define IHOLDDELAY 8u

uint8_t tmc_crc(const uint8_t *octets, size_t n) {
    // CRC-8 de la notice : polynôme x^8 + x^2 + x + 1, chaque octet pris par le bit faible.
    uint8_t crc = 0;
    for (size_t i = 0; i < n; i++) {
        uint8_t octet = octets[i];
        for (int b = 0; b < 8; b++) {
            if ((crc >> 7) ^ (octet & 0x01)) {
                crc = (uint8_t)((crc << 1) ^ 0x07);
            } else {
                crc = (uint8_t)(crc << 1);
            }
            octet >>= 1;
        }
    }
    return crc;
}

void tmc_ecriture(uint8_t *trame, uint8_t adresse, uint8_t registre, uint32_t valeur) {
    trame[0] = SYNCHRO;
    trame[1] = adresse;
    trame[2] = (uint8_t)(registre | 0x80);
    trame[3] = (uint8_t)(valeur >> 24);
    trame[4] = (uint8_t)(valeur >> 16);
    trame[5] = (uint8_t)(valeur >> 8);
    trame[6] = (uint8_t)valeur;
    trame[7] = tmc_crc(trame, 7);
}

void tmc_question(uint8_t *trame, uint8_t adresse, uint8_t registre) {
    trame[0] = SYNCHRO;
    trame[1] = adresse;
    trame[2] = (uint8_t)(registre & 0x7F);
    trame[3] = tmc_crc(trame, 3);
}

bool tmc_chercher_reponse(const uint8_t *octets, size_t n, uint8_t registre, uint32_t *valeur) {
    for (size_t i = 0; i + TMC_REPONSE <= n; i++) {
        const uint8_t *r = octets + i;
        if (r[0] == SYNCHRO && r[1] == ADRESSE_MAITRE && r[2] == (registre & 0x7F) &&
            tmc_crc(r, 7) == r[7]) {
            *valeur = (uint32_t)r[3] << 24 | (uint32_t)r[4] << 16 | (uint32_t)r[5] << 8 | r[6];
            return true;
        }
    }
    return false;
}

uint32_t tmc_gconf(void) {
    return GCONF_PDN_DISABLE | GCONF_MSTEP_REG_SELECT | GCONF_MULTISTEP_FILT;
}

uint32_t tmc_ihold_irun(uint8_t ihold, uint8_t irun) {
    return (IHOLDDELAY & 0xF) << 16 | (uint32_t)(irun & 0x1F) << 8 | (ihold & 0x1F);
}

uint32_t tmc_chopconf(uint16_t micro_pas, bool vsense) {
    // MRES : 0 = 256 micro-pas, 1 = 128, ..., 8 = pas entiers.
    uint32_t mres = 8;
    uint16_t n = 1;
    while (n < micro_pas && mres > 0) {
        n = (uint16_t)(n * 2);
        mres--;
    }
    if (n != micro_pas) {
        return 0;
    }
    uint32_t valeur = (CHOPCONF_USINE & ~CHOPCONF_MRES_MASQUE) | mres << CHOPCONF_MRES_DECALAGE;
    return vsense ? valeur | CHOPCONF_VSENSE : valeur;
}

bool tmc_version_juste(uint32_t ioin) {
    return (ioin >> 24) == TMC_VERSION;
}
