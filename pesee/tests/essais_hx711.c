// Essais de la lecture du HX711, avec un faux HX711 au bout des deux broches.
#include "essai.h"
#include "hx711.h"

typedef struct {
    uint32_t valeur;   // 24 bits envoyés, le plus fort d'abord
    bool pret;         // DT à 0 : une mesure attend
    bool sck;
    int impulsions;
    uint32_t haut_us;  // temps passé SCK à 1, depuis la dernière descente
    uint32_t haut_max_us;
} faux_hx711_t;

static bool faux_dt(void *contexte) {
    faux_hx711_t *f = contexte;
    if (!f->pret) {
        return true;
    }
    if (f->impulsions == 0) {
        return false;
    }
    if (f->impulsions > 24) {
        return true;  // après le 24e bit, DT remonte
    }
    return (f->valeur >> (24 - f->impulsions)) & 1;
}

static void faux_sck(void *contexte, bool haut) {
    faux_hx711_t *f = contexte;
    if (haut && !f->sck) {
        f->impulsions++;
        f->haut_us = 0;
    }
    if (!haut && f->sck && f->haut_us > f->haut_max_us) {
        f->haut_max_us = f->haut_us;
    }
    f->sck = haut;
}

static void faux_attendre(void *contexte, uint32_t us) {
    faux_hx711_t *f = contexte;
    if (f->sck) {
        f->haut_us += us;
    }
}

static int32_t lire(faux_hx711_t *f) {
    broches_hx711_t broches = {faux_dt, faux_sck, faux_attendre, f};
    return hx711_lire(&broches);
}

static void pret_quand_dt_a_zero(void) {
    faux_hx711_t f = {.valeur = 0x123456};
    broches_hx711_t broches = {faux_dt, faux_sck, faux_attendre, &f};
    VERIFIER(!hx711_pret(&broches));
    f.pret = true;
    VERIFIER(hx711_pret(&broches));
}

static void valeurs_signees_sur_24_bits(void) {
    faux_hx711_t f = {.valeur = 0x123456, .pret = true};
    VERIFIER(lire(&f) == 0x123456);
    faux_hx711_t g = {.valeur = 0xFFFFFF, .pret = true};
    VERIFIER(lire(&g) == -1);
    faux_hx711_t h = {.valeur = 0x800000, .pret = true};
    VERIFIER(lire(&h) == -8388608);
    faux_hx711_t i = {.valeur = 0x7FFFFF, .pret = true};
    VERIFIER(lire(&i) == 8388607);
}

static void vingt_cinq_impulsions_courtes(void) {
    // Voie A, gain 128 : 25 impulsions ; SCK jamais à 1 plus de 60 µs (la puce s'endormirait).
    faux_hx711_t f = {.valeur = 0xABCDEF, .pret = true};
    lire(&f);
    VERIFIER(f.impulsions == 25);
    VERIFIER(!f.sck);
    VERIFIER(f.haut_max_us > 0 && f.haut_max_us < 60);
}

void essais_hx711(void) {
    printf("HX711\n");
    LANCER(pret_quand_dt_a_zero);
    LANCER(valeurs_signees_sur_24_bits);
    LANCER(vingt_cinq_impulsions_courtes);
}
