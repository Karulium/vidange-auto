// Essais des pilotes de la PCA9685 et du VL6180X, sur un faux bus I2C.
#include "essai.h"
#include "faux_i2c.h"
#include "pca9685.h"
#include "vl6180x.h"

static void pca_prescale_et_pas(void) {
    pca9685_config_t c = {0x40, 50, 25000000};
    // 25 MHz / (4096 × 50 Hz) = 122,07 → 122 − 1 = 121.
    VERIFIER(pca9685_prescale(&c) == 121);
    // Un pas dure 122 / 25 MHz = 4,88 µs : 1500 µs → 307 pas, 500 µs → 102, 2500 µs → 512.
    VERIFIER(pca9685_pas(&c, 1500) == 307);
    VERIFIER(pca9685_pas(&c, 500) == 102);
    VERIFIER(pca9685_pas(&c, 2500) == 512);
    VERIFIER(pca9685_pas(&c, 20000) == 4095);  // jamais plus que la période
    pca9685_config_t rapide = {0x40, 200, 25000000};
    VERIFIER(pca9685_prescale(&rapide) == 30);
}

static void pca_demarrage_sorties_coupees(void) {
    faux_i2c_t f;
    faux_i2c_init(&f);
    i2c_bus_t bus = faux_i2c_bus(&f);
    pca9685_config_t c = {0x40, 50, 25000000};
    // Avant : des sorties qui suivent un ancien ordre.
    VERIFIER(!faux_pca_coupee(&f, 0));
    for (unsigned etape = 0; etape < PCA9685_ETAPES_DEMARRAGE; etape++) {
        VERIFIER(pca9685_etape_demarrage(&bus, &c, etape));
    }
    for (unsigned canal = 0; canal < 16; canal++) {
        VERIFIER(faux_pca_coupee(&f, canal));
    }
    VERIFIER(f.pca[0xFE] == 121);
    VERIFIER(f.pca[0x00] == 0x20);  // réveillée, adresse qui s'incrémente
    VERIFIER(f.transactions == PCA9685_ETAPES_DEMARRAGE);
}

static void pca_regler_et_couper(void) {
    faux_i2c_t f;
    faux_i2c_init(&f);
    i2c_bus_t bus = faux_i2c_bus(&f);
    pca9685_config_t c = {0x40, 50, 25000000};
    VERIFIER(pca9685_regler(&bus, &c, 3, 307));
    VERIFIER(faux_pca_fin(&f, 3) == 307 && !faux_pca_coupee(&f, 3));
    VERIFIER(f.pca[0x06 + 12] == 0 && f.pca[0x06 + 13] == 0);  // début à 0
    VERIFIER(pca9685_couper(&bus, &c, 3));
    VERIFIER(faux_pca_coupee(&f, 3));
    f.pca_presente = false;
    VERIFIER(!pca9685_regler(&bus, &c, 3, 100));
}

static vl6180x_config_t config_tof(void) {
    vl6180x_config_t c = {0x29, 50, 5, 100, 500};
    return c;
}

// Fait tourner le capteur jusqu'à `jusqu_a` ; chaque transaction fait avancer l'horloge du faux.
static void tourner(vl6180x_t *t, faux_i2c_t *f, uint64_t jusqu_a) {
    i2c_bus_t bus = faux_i2c_bus(f);
    while (f->horloge_us < jusqu_a) {
        vl6180x_pas(t, &bus, f->horloge_us);
        f->horloge_us += 20;
    }
}

static void tof_une_mesure(void) {
    faux_i2c_t f;
    faux_i2c_init(&f);
    vl6180x_t t;
    vl6180x_config_t c = config_tof();
    vl6180x_init(&t, &c, 0);
    VERIFIER(vl6180x_etat(&t) == TOF_ETAT_PAS_ENCORE && vl6180x_distance(&t) == 0xFFFF);
    f.tof_distance = 87;
    tourner(&t, &f, 200000);
    VERIFIER(vl6180x_etat(&t) == TOF_ETAT_BONNE);
    VERIFIER(vl6180x_distance(&t) == 87);
    // Réglages obligatoires écrits, puce notée « plus en sortie de reset ».
    VERIFIER(f.tof[0x016] == 0);
    VERIFIER(f.tof[0x0207] == 1 && f.tof[0x0198] == 1);
    // La distance suit l'objet.
    f.tof_distance = 20;
    tourner(&t, &f, 400000);
    VERIFIER(vl6180x_distance(&t) == 20);
}

static void tof_code_d_erreur(void) {
    faux_i2c_t f;
    faux_i2c_init(&f);
    f.tof_code = 11;  // la puce dit « hors de portée »
    vl6180x_t t;
    vl6180x_config_t c = config_tof();
    vl6180x_init(&t, &c, 0);
    tourner(&t, &f, 200000);
    VERIFIER(vl6180x_etat(&t) == 11);
    VERIFIER(vl6180x_distance(&t) == 0xFFFF);
}

static void tof_muet_puis_de_retour(void) {
    faux_i2c_t f;
    faux_i2c_init(&f);
    f.tof_present = false;
    vl6180x_t t;
    vl6180x_config_t c = config_tof();
    vl6180x_init(&t, &c, 0);
    tourner(&t, &f, 1000000);
    VERIFIER(vl6180x_etat(&t) == TOF_ETAT_MUET && vl6180x_distance(&t) == 0xFFFF);
    // Un essai toutes les 500 ms au plus : pas de bus saturé par un capteur absent.
    VERIFIER(t.echecs >= 1 && t.echecs <= 3);
    f.tof_present = true;
    tourner(&t, &f, 2500000);
    VERIFIER(vl6180x_etat(&t) == TOF_ETAT_BONNE && vl6180x_distance(&t) == 42);
}

static void tof_jamais_fini(void) {
    // Mesure lancée mais jamais prête : muet après delai_max_ms.
    faux_i2c_t f;
    faux_i2c_init(&f);
    f.tof_duree_us = 100000000;
    vl6180x_t t;
    vl6180x_config_t c = config_tof();
    vl6180x_init(&t, &c, 0);
    tourner(&t, &f, 400000);
    VERIFIER(vl6180x_etat(&t) == TOF_ETAT_MUET);
}

void essais_pca9685(void) {
    printf("PCA9685\n");
    LANCER(pca_prescale_et_pas);
    LANCER(pca_demarrage_sorties_coupees);
    LANCER(pca_regler_et_couper);
}

void essais_vl6180x(void) {
    printf("VL6180X\n");
    LANCER(tof_une_mesure);
    LANCER(tof_code_d_erreur);
    LANCER(tof_muet_puis_de_retour);
    LANCER(tof_jamais_fini);
}
