#include "balance.h"

void balance_init(balance_t *b, int32_t zero_brut, float brut_par_kg, uint8_t moyenne_de,
                  uint32_t sans_mesure_ms, int32_t instable_dixiemes) {
    *b = (balance_t){0};
    b->zero_brut = zero_brut;
    b->brut_par_kg = brut_par_kg;
    if (moyenne_de < 1) {
        moyenne_de = 1;
    }
    b->moyenne_de = moyenne_de > BALANCE_MESURES_MAX ? BALANCE_MESURES_MAX : moyenne_de;
    b->sans_mesure_us = (uint64_t)sans_mesure_ms * 1000u;
    b->instable_dixiemes = instable_dixiemes;
}

void balance_mesure(balance_t *b, int32_t brut, uint64_t t_us) {
    // Revenue après un silence : les anciennes mesures ne comptent plus.
    if (balance_muette(b, t_us)) {
        b->nb = 0;
        b->prochaine = 0;
    }
    b->mesures[b->prochaine] = brut;
    b->prochaine = (uint8_t)((b->prochaine + 1) % b->moyenne_de);
    if (b->nb < b->moyenne_de) {
        b->nb++;
    }
    b->une_mesure = true;
    b->derniere_us = t_us;
}

bool balance_muette(const balance_t *b, uint64_t t_us) {
    return !b->une_mesure || t_us - b->derniere_us > b->sans_mesure_us;
}

int32_t balance_brut(const balance_t *b) {
    if (!b->nb) {
        return 0;
    }
    int64_t somme = 0;
    for (uint8_t i = 0; i < b->nb; i++) {
        somme += b->mesures[i];
    }
    // Arrondi au plus proche, négatifs compris.
    int64_t n = b->nb;
    return (int32_t)(somme >= 0 ? (somme + n / 2) / n : -((-somme + n / 2) / n));
}

static int32_t en_dixiemes(const balance_t *b, float brut) {
    if (b->brut_par_kg == 0.0f) {
        return 0;
    }
    float dixiemes = brut * 10000.0f / b->brut_par_kg;
    return (int32_t)(dixiemes >= 0 ? dixiemes + 0.5f : dixiemes - 0.5f);
}

int32_t balance_dixiemes(const balance_t *b) {
    if (!b->nb) {
        return 0;
    }
    return en_dixiemes(b, (float)((int64_t)balance_brut(b) - b->zero_brut));
}

bool balance_instable(const balance_t *b) {
    if (b->nb < 2) {
        return false;
    }
    int32_t petit = b->mesures[0], grand = b->mesures[0];
    for (uint8_t i = 1; i < b->nb; i++) {
        petit = b->mesures[i] < petit ? b->mesures[i] : petit;
        grand = b->mesures[i] > grand ? b->mesures[i] : grand;
    }
    int32_t ecart = en_dixiemes(b, (float)((int64_t)grand - petit));
    return (ecart < 0 ? -ecart : ecart) > b->instable_dixiemes;
}
