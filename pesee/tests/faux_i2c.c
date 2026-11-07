#include "faux_i2c.h"

#include <string.h>

void faux_i2c_init(faux_i2c_t *f) {
    memset(f, 0, sizeof(*f));
    f->octet_us = 90;  // 100 kHz : 9 bits par octet
    f->pca_presente = true;
    f->tof_present = true;
    f->pca_adresse = 0x40;
    f->tof_adresse = 0x29;
    f->tof_distance = 42;
    f->tof_duree_us = 10000;
    f->tof[0x016] = 1;  // sorti de reset
    // Une PCA9685 qui vient d'être alimentée : toutes ses sorties à 0, éveillée (MODE1 = 0x11 : veille).
    f->pca[0x00] = 0x11;
    f->pca[0xFE] = 0x1E;
    // Les sorties ne sont PAS coupées : elles peuvent suivre un ancien ordre.
    for (unsigned c = 0; c < 16; c++) {
        f->pca[0x06 + 4 * c + 2] = 0x34;  // une vieille impulsion
        f->pca[0x06 + 4 * c + 3] = 0x01;
    }
}

static void durer(faux_i2c_t *f, size_t octets, bool present) {
    uint64_t duree = present ? (uint64_t)(octets + 1) * f->octet_us
                             : (f->blocage_us ? f->blocage_us : f->octet_us);
    f->horloge_us += duree;
    f->transactions++;
    if (duree > f->plus_longue_us) {
        f->plus_longue_us = duree;
    }
}

static void tof_avancer(faux_i2c_t *f) {
    if (f->tof_en_cours && f->horloge_us - f->tof_lancee_us >= f->tof_duree_us) {
        f->tof_en_cours = false;
        f->tof[0x04F] = 4;
        f->tof[0x062] = f->tof_distance;
        f->tof[0x04D] = (uint8_t)(f->tof_code << 4);
    }
}

static bool ecrire(void *contexte, uint8_t adr, const uint8_t *octets, size_t n) {
    faux_i2c_t *f = contexte;
    bool present = (adr == f->pca_adresse && f->pca_presente) ||
                   (adr == f->tof_adresse && f->tof_present);
    durer(f, n, present);
    if (!present) {
        return false;
    }
    if (adr == f->pca_adresse) {
        uint8_t registre = octets[0];
        for (size_t i = 1; i < n; i++) {
            uint8_t r = (uint8_t)(registre + i - 1);
            if (r == 0xFD) {
                // ALL_LED_OFF_H : tous les LEDn_OFF_H.
                for (unsigned c = 0; c < 16; c++) {
                    f->pca[0x06 + 4 * c + 3] = octets[i];
                }
                f->ecritures_pca++;
            } else {
                f->pca[r] = octets[i];
                if (r >= 0x06 && r <= 0x45) {
                    f->ecritures_pca++;
                }
            }
        }
        return true;
    }
    uint16_t registre = (uint16_t)(octets[0] << 8 | octets[1]);
    uint8_t valeur = octets[2];
    tof_avancer(f);
    if (registre == 0x018 && (valeur & 1)) {
        f->tof_en_cours = true;
        f->tof_lancee_us = f->horloge_us;
        f->tof[0x04F] = 0;
    } else if (registre == 0x015) {
        f->tof[0x04F] = 0;
    } else if (registre < sizeof(f->tof)) {
        f->tof[registre] = valeur;
    }
    return true;
}

static bool lire(void *contexte, uint8_t adr, const uint8_t *index, size_t ni, uint8_t *dest,
                 size_t n) {
    faux_i2c_t *f = contexte;
    bool present = (adr == f->pca_adresse && f->pca_presente) ||
                   (adr == f->tof_adresse && f->tof_present);
    durer(f, ni + n + 1, present);
    if (!present) {
        return false;
    }
    if (adr == f->pca_adresse) {
        for (size_t i = 0; i < n; i++) {
            dest[i] = f->pca[(uint8_t)(index[0] + i)];
        }
        return true;
    }
    tof_avancer(f);
    uint16_t registre = (uint16_t)(index[0] << 8 | index[1]);
    for (size_t i = 0; i < n; i++) {
        dest[i] = f->tof[registre + i];
    }
    return true;
}

i2c_bus_t faux_i2c_bus(faux_i2c_t *f) {
    i2c_bus_t bus = {ecrire, lire, f};
    return bus;
}

uint16_t faux_pca_fin(const faux_i2c_t *f, unsigned canal) {
    return (uint16_t)(f->pca[0x06 + 4 * canal + 2] | (f->pca[0x06 + 4 * canal + 3] & 0x0F) << 8);
}

bool faux_pca_coupee(const faux_i2c_t *f, unsigned canal) {
    return f->pca[0x06 + 4 * canal + 3] & 0x10;
}

bool faux_pca_allumee_pour_de_bon(const faux_i2c_t *f, unsigned canal) {
    return f->pca[0x06 + 4 * canal + 1] & 0x10;
}

plateau_config_t config_essai(void) {
    plateau_config_t c = {
        .pca = {.adresse = 0x40, .frequence_hz = 50, .horloge_hz = 25000000},
        .pca_reveil_us = 1000,
        .tof = {.adresse = 0x29, .periode_ms = 50, .sondage_ms = 5, .delai_max_ms = 100,
                .reessai_ms = 500},
        .silence_pi_ms = 2000,
        .reessai_ms = 500,
        .nb_voies = 3,
        .voies = {{.canal = 0, .angle_min_dix = 0, .angle_max_dix = 2700,
                   .impulsion_min_us = 500, .impulsion_max_us = 2500},
                  {.canal = 1, .angle_min_dix = 0, .angle_max_dix = 1800,
                   .impulsion_min_us = 500, .impulsion_max_us = 2400},
                  {.canal = 5, .angle_min_dix = -1350, .angle_max_dix = 1350,
                   .impulsion_min_us = 500, .impulsion_max_us = 2500}},
    };
    return c;
}
