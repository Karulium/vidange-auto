#include <string.h>

#include "essai.h"
#include "reglages.h"

static void reglages_du_depot_bons(void) {
    reglages_t r = reglages_depart();
    char message[96];
    VERIFIER(reglages_verifier(&r, message, sizeof message));
    VERIFIER(message[0] == '\0');
}

static void seuil_plus_fort_que_la_pleine_echelle(void) {
    reglages_t r = reglages_depart();
    r.pleine_echelle_g = 2;
    r.seuil_mg = 2000;
    char message[96];
    VERIFIER(!reglages_verifier(&r, message, sizeof message));
    VERIFIER(strstr(message, "seuil") != NULL);
}

static void valeurs_que_la_puce_n_a_pas(void) {
    char message[96];
    reglages_t r = reglages_depart();
    r.pleine_echelle_g = 3;
    VERIFIER(!reglages_verifier(&r, message, sizeof message));
    r = reglages_depart();
    r.mesures_par_seconde = 300;
    VERIFIER(!reglages_verifier(&r, message, sizeof message));
    VERIFIER(strstr(message, "mesures_par_seconde") != NULL);
    r = reglages_depart();
    r.axes = 0;
    VERIFIER(!reglages_verifier(&r, message, sizeof message));
}

static void delais_trop_courts_pour_la_vitesse_de_mesure(void) {
    char message[96];
    reglages_t r = reglages_depart();
    r.mesures_par_seconde = 10;  // une mesure toutes les 100 ms
    r.sans_mesure_ms = 250;      // moins de 3 mesures
    VERIFIER(!reglages_verifier(&r, message, sizeof message));
    VERIFIER(strstr(message, "sans_mesure_ms") != NULL);
    r.sans_mesure_ms = 300;
    r.figee_ms = 1000;  // 10 mesures seulement
    VERIFIER(!reglages_verifier(&r, message, sizeof message));
    VERIFIER(strstr(message, "figee_ms") != NULL);
}

void essais_reglages(void) {
    LANCER(reglages_du_depot_bons);
    LANCER(seuil_plus_fort_que_la_pleine_echelle);
    LANCER(valeurs_que_la_puce_n_a_pas);
    LANCER(delais_trop_courts_pour_la_vitesse_de_mesure);
}
