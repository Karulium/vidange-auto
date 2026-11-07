// Essais des balances des flacons : faux HX711 lu par hx711.c, moyenne, muette, instable.
#include "balance.h"
#include "essai.h"
#include "faux_hx711.h"
#include "hx711.h"

static void faux_hx711_jusqu_a_la_balance(void) {
    // 250 g posés : zéro 1000, 400 points par gramme → 101 000.
    faux_hx711_t f;
    faux_hx711_init(&f, 101000, 12500, 0);
    broches_hx711_t broches = faux_hx711_broches(&f);
    balance_t b;
    balance_init(&b, 1000, 400000.0f, 8, 100, 30);
    VERIFIER(balance_muette(&b, 0));
    for (uint64_t t = 0; t < 200000; t += 1000) {
        faux_hx711_avancer(&f, t);
        if (hx711_pret(&broches)) {
            balance_mesure(&b, hx711_lire(&broches), t);
        }
    }
    VERIFIER(f.lues == 15);
    VERIFIER(!balance_muette(&b, 200000));
    VERIFIER(balance_brut(&b) == 101000);
    VERIFIER(balance_dixiemes(&b) == 2500);
    VERIFIER(!balance_instable(&b));
    // HX711 débranché (DT reste à 1) : plus de mesure, muette au bout de 100 ms.
    f.debranche = true;
    for (uint64_t t = 200000; t < 400000; t += 1000) {
        faux_hx711_avancer(&f, t);
        if (hx711_pret(&broches)) {
            balance_mesure(&b, hx711_lire(&broches), t);
        }
    }
    VERIFIER(balance_muette(&b, 400000));
}

static void moyenne_des_dernieres(void) {
    balance_t b;
    balance_init(&b, 0, 400000.0f, 4, 100, 1000);
    uint64_t t = 0;
    const int32_t mesures[6] = {400, 800, 1200, 1600, 2000, 2400};
    for (int i = 0; i < 6; i++) {
        balance_mesure(&b, mesures[i], t += 12500);
    }
    // Les 4 dernières : 1200, 1600, 2000, 2400 → 1800, soit 4,5 g.
    VERIFIER(balance_brut(&b) == 1800);
    VERIFIER(balance_dixiemes(&b) == 45);
    // Capteur monté à l'envers : brut_par_kg négatif.
    balance_init(&b, 0, -400000.0f, 1, 100, 1000);
    balance_mesure(&b, -4000, 1);
    VERIFIER(balance_dixiemes(&b) == 100);
}

static void muette_puis_revenue(void) {
    balance_t b;
    balance_init(&b, 0, 400000.0f, 8, 100, 1000);
    balance_mesure(&b, 4000, 1000);
    VERIFIER(!balance_muette(&b, 100000));
    VERIFIER(balance_muette(&b, 101001));
    // Revenue : les mesures d'avant le silence ne comptent plus.
    balance_mesure(&b, 8000, 300000);
    VERIFIER(balance_brut(&b) == 8000);
    VERIFIER(!balance_muette(&b, 300000));
}

static void instable(void) {
    balance_t b;
    balance_init(&b, 0, 400000.0f, 8, 100, 30);  // plus de 3 g d'écart
    uint64_t t = 0;
    for (int i = 0; i < 8; i++) {
        balance_mesure(&b, 100000 + ((i & 1) ? 400 : -400), t += 12500);  // ± 1 g
    }
    VERIFIER(!balance_instable(&b));
    for (int i = 0; i < 8; i++) {
        balance_mesure(&b, 100000 + ((i & 1) ? 800 : -800), t += 12500);  // ± 2 g
    }
    VERIFIER(balance_instable(&b));
}

void essais_balance(void) {
    printf("Balances\n");
    LANCER(faux_hx711_jusqu_a_la_balance);
    LANCER(moyenne_des_dernieres);
    LANCER(muette_puis_revenue);
    LANCER(instable);
}
