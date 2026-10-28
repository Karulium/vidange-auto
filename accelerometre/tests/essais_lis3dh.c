#include "essai.h"
#include "faux_lis3dh.h"
#include "lis3dh.h"

static void demarrage_et_mesure(void) {
    faux_lis3dh_t faux;
    faux_lis3dh_preparer(&faux);
    lis3dh_t capteur;
    VERIFIER(lis3dh_demarrer(&capteur, &faux.bus, 0x18, 8, 400) == LIS3DH_BIEN);
    // Réglé en haute résolution, ±8 g, 400 mesures par seconde, 3 axes.
    VERIFIER(faux.registres[0x20] == 0x77);
    VERIFIER(faux.registres[0x23] == 0xA8);
    VERIFIER(faux.lectures_suite_sans_bit == 0);
    VERIFIER(capteur.autotest_ecart[0] == 100);  // 400 mg / 4 mg par pas
    faux.mg[0] = 1500;
    faux.mg[1] = -800;
    int32_t mg[3];
    bool nouvelle;
    bool debordement;
    VERIFIER(lis3dh_lire(&capteur, mg, &nouvelle, &debordement) == LIS3DH_BIEN);
    VERIFIER(nouvelle);
    VERIFIER(!debordement);
    VERIFIER(mg[0] == 1500 && mg[1] == -800 && mg[2] == 1000);
}

static void pleines_echelles(void) {
    const uint8_t echelles[4] = {2, 4, 8, 16};
    for (int i = 0; i < 4; i++) {
        faux_lis3dh_t faux;
        faux_lis3dh_preparer(&faux);
        lis3dh_t capteur;
        VERIFIER(lis3dh_demarrer(&capteur, &faux.bus, 0x18, echelles[i], 100) == LIS3DH_BIEN);
        faux.mg[0] = -1200;
        int32_t mg[3];
        bool nouvelle;
        bool debordement;
        lis3dh_lire(&capteur, mg, &nouvelle, &debordement);
        VERIFIER(mg[0] == -1200);
    }
}

static void capteur_absent_ou_autre_puce(void) {
    faux_lis3dh_t faux;
    faux_lis3dh_preparer(&faux);
    lis3dh_t capteur;
    VERIFIER(lis3dh_demarrer(&capteur, &faux.bus, 0x19, 8, 400) == LIS3DH_ABSENT);
    faux.muet = true;
    VERIFIER(lis3dh_demarrer(&capteur, &faux.bus, 0x18, 8, 400) == LIS3DH_ABSENT);
    faux_lis3dh_preparer(&faux);
    faux.who_am_i = 0x44;
    VERIFIER(lis3dh_demarrer(&capteur, &faux.bus, 0x18, 8, 400) == LIS3DH_MAUVAISE_PUCE);
}

static void autotest_rate(void) {
    faux_lis3dh_t faux;
    lis3dh_t capteur;
    // Capteur qui ne bouge pas à l'autotest (cassé, décollé).
    faux_lis3dh_preparer(&faux);
    faux.autotest_mg = 0;
    VERIFIER(lis3dh_demarrer(&capteur, &faux.bus, 0x18, 8, 400) == LIS3DH_AUTOTEST_RATE);
    // Qui bouge beaucoup trop.
    faux_lis3dh_preparer(&faux);
    faux.autotest_mg = 1900;
    VERIFIER(lis3dh_demarrer(&capteur, &faux.bus, 0x18, 8, 400) == LIS3DH_AUTOTEST_RATE);
    // Qui ne mesure jamais rien : abandon au bout d'un temps court.
    faux_lis3dh_preparer(&faux);
    faux.sans_mesure = true;
    VERIFIER(lis3dh_demarrer(&capteur, &faux.bus, 0x18, 8, 400) == LIS3DH_AUTOTEST_RATE);
    VERIFIER(faux.attendu_ms < 500);
}

static void reglages_inconnus(void) {
    faux_lis3dh_t faux;
    faux_lis3dh_preparer(&faux);
    lis3dh_t capteur;
    VERIFIER(lis3dh_demarrer(&capteur, &faux.bus, 0x18, 6, 400) == LIS3DH_REGLAGE_INCONNU);
    VERIFIER(lis3dh_demarrer(&capteur, &faux.bus, 0x18, 8, 333) == LIS3DH_REGLAGE_INCONNU);
}

static void lecture_ratee_et_sans_nouvelle_mesure(void) {
    faux_lis3dh_t faux;
    faux_lis3dh_preparer(&faux);
    lis3dh_t capteur;
    VERIFIER(lis3dh_demarrer(&capteur, &faux.bus, 0x18, 8, 400) == LIS3DH_BIEN);
    int32_t mg[3] = {7, 7, 7};
    bool nouvelle;
    bool debordement;
    faux.erreurs_a_venir = 1;
    VERIFIER(lis3dh_lire(&capteur, mg, &nouvelle, &debordement) == LIS3DH_ERREUR_BUS);
    VERIFIER(!nouvelle);
    faux.sans_mesure = true;
    VERIFIER(lis3dh_lire(&capteur, mg, &nouvelle, &debordement) == LIS3DH_BIEN);
    VERIFIER(!nouvelle);
    VERIFIER(mg[0] == 7);
}

void essais_lis3dh(void) {
    LANCER(demarrage_et_mesure);
    LANCER(pleines_echelles);
    LANCER(capteur_absent_ou_autre_puce);
    LANCER(autotest_rate);
    LANCER(reglages_inconnus);
    LANCER(lecture_ratee_et_sans_nouvelle_mesure);
}
