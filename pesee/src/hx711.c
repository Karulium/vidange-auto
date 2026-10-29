#include "hx711.h"

// Impulsions de SCK après les 24 bits : 1 = voie A, gain 128 (2 : voie B ; 3 : voie A, gain 64).
#define IMPULSIONS_GAIN 1

bool hx711_pret(const broches_hx711_t *broches) {
    return !broches->lire_dt(broches->contexte);
}

static bool impulsion(const broches_hx711_t *broches) {
    broches->ecrire_sck(broches->contexte, true);
    // DT change au plus 0,1 µs après la montée de SCK ; 1 µs suffit largement.
    broches->attendre_us(broches->contexte, 1);
    bool bit = broches->lire_dt(broches->contexte);
    broches->ecrire_sck(broches->contexte, false);
    broches->attendre_us(broches->contexte, 1);
    return bit;
}

int32_t hx711_lire(const broches_hx711_t *broches) {
    uint32_t valeur = 0;
    for (int i = 0; i < 24; i++) {
        valeur = (valeur << 1) | (impulsion(broches) ? 1u : 0u);
    }
    for (int i = 0; i < IMPULSIONS_GAIN; i++) {
        impulsion(broches);
    }
    // Signe sur 24 bits → 32 bits.
    if (valeur & 0x800000u) {
        valeur |= 0xFF000000u;
    }
    return (int32_t)valeur;
}
