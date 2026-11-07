// Essais des trames du pilote TMC2209 du bras (notice de Trinamic).
#include "essai.h"
#include "tmc2209.h"

static void controle_connu(void) {
    // Question « lire GCONF » à l'adresse 0 : 05 00 00, contrôle 0x48.
    uint8_t q[TMC_QUESTION];
    tmc_question(q, 0, TMC_GCONF);
    VERIFIER(q[0] == 0x05 && q[1] == 0 && q[2] == 0 && q[3] == 0x48);
    tmc_question(q, 0, TMC_IFCNT);
    VERIFIER(q[3] == 0x8F);
}

static void ecriture(void) {
    uint8_t t[TMC_ECRITURE];
    tmc_ecriture(t, 2, TMC_IHOLD_IRUN, 0x00081409);
    VERIFIER(t[0] == 0x05 && t[1] == 2 && t[2] == 0x90);
    VERIFIER(t[3] == 0x00 && t[4] == 0x08 && t[5] == 0x14 && t[6] == 0x09);
    VERIFIER(t[7] == tmc_crc(t, 7));
}

static void reponse_apres_l_echo(void) {
    // Sur un seul fil : d'abord l'écho de la question (4 octets), puis la réponse (8 octets).
    uint8_t recus[12];
    tmc_question(recus, 0, TMC_IOIN);
    uint8_t *r = recus + 4;
    r[0] = 0x05;
    r[1] = 0xFF;
    r[2] = TMC_IOIN;
    r[3] = 0x21;
    r[4] = 0x00;
    r[5] = 0x01;
    r[6] = 0x40;
    r[7] = tmc_crc(r, 7);
    uint32_t valeur = 0;
    VERIFIER(tmc_chercher_reponse(recus, 12, TMC_IOIN, &valeur));
    VERIFIER(valeur == 0x21000140);
    VERIFIER(tmc_version_juste(valeur));
    VERIFIER(!tmc_version_juste(0x20000000));
    // Pas le bon registre, ou un octet abîmé : rien.
    VERIFIER(!tmc_chercher_reponse(recus, 12, TMC_GSTAT, &valeur));
    r[5] ^= 0x10;
    VERIFIER(!tmc_chercher_reponse(recus, 12, TMC_IOIN, &valeur));
    // Réponse coupée : rien.
    VERIFIER(!tmc_chercher_reponse(recus, 11, TMC_IOIN, &valeur));
}

static void valeurs_des_registres(void) {
    // pdn_disable, mstep_reg_select, multistep_filt.
    VERIFIER(tmc_gconf() == 0x1C0);
    VERIFIER(tmc_ihold_irun(9, 20) == 0x00081409);
    // 16 micro-pas : MRES 4.
    VERIFIER(tmc_chopconf(16, false) == 0x14000053);
    VERIFIER(tmc_chopconf(16, true) == (0x14000053 | (1u << 17)));
    VERIFIER(tmc_chopconf(256, false) == 0x10000053);
    VERIFIER(tmc_chopconf(1, false) == 0x18000053);
    VERIFIER(tmc_chopconf(3, false) == 0);
}

void essais_tmc2209(void) {
    printf("Pilote TMC2209\n");
    LANCER(controle_connu);
    LANCER(ecriture);
    LANCER(reponse_apres_l_echo);
    LANCER(valeurs_des_registres);
}
