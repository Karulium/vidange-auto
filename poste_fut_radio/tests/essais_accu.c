// Essais de l'accu : tension par le pont diviseur, niveau par la courbe.
#include "accu.h"
#include "essai.h"

// La courbe d'exemple de pesees.yaml.
static const uint16_t mv[] = {3000, 3300, 3500, 3600, 3700, 3800, 3900, 4000, 4100, 4200};
static const uint8_t pct[] = {0, 5, 20, 30, 45, 60, 72, 83, 93, 100};
static const courbe_accu_t courbe = {mv, pct, 10};

static void tension_par_le_pont(void) {
    // Deux résistances égales : rapport 2.
    VERIFIER(accu_tension_mv(2000, 2000) == 4000);
    // Rapport corrigé à l'essai (2,013) : arrondi au mV.
    VERIFIER(accu_tension_mv(1950, 2013) == 3925);
    VERIFIER(accu_tension_mv(0, 2000) == 0);
    // Jamais plus que 65 535 (registre de 16 bits).
    VERIFIER(accu_tension_mv(40000, 2000) == 65535);
}

static void niveau_par_la_courbe(void) {
    // Sur les points.
    VERIFIER(accu_pourcentage(&courbe, 3300) == 5);
    VERIFIER(accu_pourcentage(&courbe, 3500) == 20);
    VERIFIER(accu_pourcentage(&courbe, 4200) == 100);
    // Entre deux points, en ligne droite (arrondi).
    VERIFIER(accu_pourcentage(&courbe, 3400) == 13);  // 12,5 → 13
    VERIFIER(accu_pourcentage(&courbe, 3650) == 38);  // 37,5 → 38
    VERIFIER(accu_pourcentage(&courbe, 3950) == 78);  // 77,5 → 78
    // Hors de la courbe : le premier ou le dernier niveau.
    VERIFIER(accu_pourcentage(&courbe, 2500) == 0);
    VERIFIER(accu_pourcentage(&courbe, 4350) == 100);
    // Toujours en montant.
    uint8_t avant = 0;
    for (uint16_t t = 2900; t <= 4300; t += 7) {
        uint8_t p = accu_pourcentage(&courbe, t);
        VERIFIER(p >= avant);
        avant = p;
    }
}

void essais_accu(void) {
    printf("Accu\n");
    LANCER(tension_par_le_pont);
    LANCER(niveau_par_la_courbe);
}
