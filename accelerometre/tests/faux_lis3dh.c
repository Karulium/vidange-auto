#include "faux_lis3dh.h"

#include <string.h>

// Pas de mesure (mg par pas) selon la pleine échelle, en haute résolution et en mode normal.
static const int32_t mg_hr[4] = {1, 2, 4, 12};
static const int32_t mg_normal[4] = {4, 8, 16, 48};

static uint8_t encoder(faux_lis3dh_t *f, int axe, int octet) {
    uint8_t ctrl4 = f->registres[0x23];
    int echelle = (ctrl4 >> 4) & 3;
    bool hr = ctrl4 & 0x08;
    int32_t mg = f->mg[axe] + ((ctrl4 & 0x06) ? f->autotest_mg : 0);
    int32_t pas = mg / (hr ? mg_hr[echelle] : mg_normal[echelle]);
    int32_t limite = hr ? 2047 : 511;
    if (pas > limite) pas = limite;
    if (pas < -limite - 1) pas = -limite - 1;
    uint16_t brut = (uint16_t)((uint32_t)pas << (hr ? 4 : 6));
    return octet ? (uint8_t)(brut >> 8) : (uint8_t)brut;
}

static int ecrire(void *contexte, uint8_t adresse, const uint8_t *octets, size_t n) {
    faux_lis3dh_t *f = contexte;
    if (f->muet || adresse != f->adresse || n < 2) {
        return -1;
    }
    uint8_t registre = octets[0] & 0x7F;
    for (size_t i = 1; i < n; i++) {
        f->registres[(registre + i - 1) & 0x3F] = octets[i];
    }
    f->registres[0x24] &= 0x7F;  // BOOT s'efface tout seul
    return 0;
}

static int lire(void *contexte, uint8_t adresse, uint8_t registre, uint8_t *octets, size_t n) {
    faux_lis3dh_t *f = contexte;
    if (f->muet || adresse != f->adresse) {
        return -1;
    }
    if (f->erreurs_a_venir > 0) {
        f->erreurs_a_venir--;
        return -1;
    }
    if (n > 1 && !(registre & 0x80)) {
        f->lectures_suite_sans_bit++;
    }
    for (size_t i = 0; i < n; i++) {
        uint8_t r = (uint8_t)((registre & 0x7F) + i);
        if (r == 0x0F) {
            octets[i] = f->who_am_i;
        } else if (r == 0x27) {
            octets[i] = f->sans_mesure ? 0x00 : 0x08;
        } else if (r >= 0x28 && r <= 0x2D) {
            octets[i] = encoder(f, (r - 0x28) / 2, (r - 0x28) % 2);
        } else {
            octets[i] = f->registres[r & 0x3F];
        }
    }
    return 0;
}

static void attendre_ms(void *contexte, uint32_t ms) {
    faux_lis3dh_t *f = contexte;
    f->attendu_ms += ms;
}

void faux_lis3dh_preparer(faux_lis3dh_t *f) {
    memset(f, 0, sizeof *f);
    f->adresse = 0x18;
    f->who_am_i = 0x33;
    f->mg[2] = 1000;  // pesanteur sur z
    f->autotest_mg = 400;
    f->bus = (bus_i2c_t){ecrire, lire, attendre_ms, f};
}
