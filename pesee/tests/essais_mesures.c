// Essais de la table des registres que le Pi lit.
#include "essai.h"
#include "mesures.h"

#define S 1000000ull

static void table_des_registres(void) {
    mesures_t m;
    uint16_t r[NB_REGISTRES];
    mesures_init(&m, 100, false, 0);
    mesures_noter(&m, -2, 10 * S);
    mesures_registres(&m, 3, 10 * S + 25000, r);
    VERIFIER(r[REGISTRE_BRUT_FORT] == 0xFFFF && r[REGISTRE_BRUT_FAIBLE] == 0xFFFE);
    VERIFIER(r[REGISTRE_NUMERO] == 1);
    VERIFIER(r[REGISTRE_AGE_MS] == 25);
    VERIFIER(r[REGISTRE_ETAT] == 0);
    VERIFIER(r[REGISTRE_TRAMES_ABIMEES] == 3);
    VERIFIER(r[REGISTRE_SIGNATURE] == 0x5053);
    mesures_noter(&m, 0x123456, 10 * S + 30000);
    mesures_registres(&m, 0, 10 * S + 30000, r);
    VERIFIER(r[REGISTRE_BRUT_FORT] == 0x0012 && r[REGISTRE_BRUT_FAIBLE] == 0x3456);
    VERIFIER(r[REGISTRE_NUMERO] == 2);
}

static void hx711_muet(void) {
    mesures_t m;
    uint16_t r[NB_REGISTRES];
    mesures_init(&m, 100, true, 0);
    // Jamais de mesure : muet tout de suite.
    VERIFIER(mesures_muet(&m, 0));
    mesures_registres(&m, 0, 0, r);
    VERIFIER(r[REGISTRE_ETAT] == (ETAT_HX711_MUET | ETAT_EXEMPLE));
    mesures_noter(&m, 5, S);
    VERIFIER(!mesures_muet(&m, S + 100000));
    VERIFIER(mesures_muet(&m, S + 100001));
    // L'âge plafonne à 65 535 ms.
    mesures_registres(&m, 0, 200 * S, r);
    VERIFIER(r[REGISTRE_AGE_MS] == 65535);
    VERIFIER(r[REGISTRE_ETAT] & ETAT_HX711_MUET);
}

static void mesures_par_seconde(void) {
    mesures_t m;
    uint16_t r[NB_REGISTRES];
    mesures_init(&m, 100, false, 0);
    for (uint64_t t = 0; t < 3 * S; t += 12500) {
        mesures_noter(&m, 0, t);
    }
    mesures_avancer(&m, 3 * S);
    mesures_registres(&m, 0, 3 * S, r);
    VERIFIER(r[REGISTRE_PAR_SECONDE] == 80);
    // Plus aucune mesure : retombe à 0.
    mesures_avancer(&m, 4 * S);
    mesures_avancer(&m, 5 * S);
    mesures_registres(&m, 0, 5 * S, r);
    VERIFIER(r[REGISTRE_PAR_SECONDE] == 0);
}

static void numero_repart_a_zero(void) {
    mesures_t m;
    mesures_init(&m, 100, false, 0);
    m.numero = 65535;
    mesures_noter(&m, 0, 1);
    VERIFIER(m.numero == 0);
}

void essais_mesures(void) {
    printf("Mesures\n");
    LANCER(table_des_registres);
    LANCER(hx711_muet);
    LANCER(mesures_par_seconde);
    LANCER(numero_repart_a_zero);
}
