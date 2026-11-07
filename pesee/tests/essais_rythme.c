// La pesée garde son rythme : avec l'I2C en route, la carte lit son HX711 aussi souvent que sans.
//
// Le HX711 à 80 mesures par seconde garde chaque mesure prête pendant 12,5 ms ; si la carte ne la
// lit pas avant la suivante, elle est perdue. Ici le temps est celui d'un faux bus I2C qui prend
// la durée réelle de chaque transaction (100 kHz).
#include "essai.h"
#include "faux_i2c.h"
#include "mesures.h"
#include "modbus.h"
#include "plateau.h"

#define PERIODE_HX711_US 12500ull
#define LECTURE_HX711_US 60ull   // 24 bits lus à la main, avec les interruptions coupées
#define PASSE_US 5ull            // un tour de la boucle de main.c sans rien à faire

typedef struct {
    unsigned lues;
    unsigned perdues;
    uint64_t plus_long_trou_us;  // entre deux tours de la boucle
    unsigned par_seconde;
    unsigned transactions;
    uint64_t transaction_la_plus_longue_us;
} resultat_t;

// avec_i2c : la carte fait tourner le plateau. orde_tous_les_ms : le Pi renvoie les angles.
static resultat_t simuler(bool avec_i2c, bool pca, bool tof, uint32_t blocage_us,
                          uint64_t duree_us) {
    faux_i2c_t faux;
    faux_i2c_init(&faux);
    faux.pca_presente = pca;
    faux.tof_present = tof;
    faux.blocage_us = blocage_us;
    plateau_config_t c = config_essai();
    plateau_t p;
    i2c_bus_t bus = faux_i2c_bus(&faux);
    plateau_init(&p, &c, &bus, 1, 0);
    mesures_t mesures;
    mesures_init(&mesures, 100, false, 0);

    resultat_t r = {0};
    uint64_t t = 0, dernier_tour = 0, prochain_ordre = 0;
    unsigned derniere_lue = 0;  // numéro de la dernière mesure du HX711 lue
    while (t < duree_us) {
        // La mesure k est prête de k × 12,5 ms à (k + 1) × 12,5 ms.
        unsigned prete = (unsigned)(t / PERIODE_HX711_US);
        if (t - dernier_tour > r.plus_long_trou_us) {
            r.plus_long_trou_us = t - dernier_tour;
        }
        dernier_tour = t;
        if (prete > derniere_lue) {
            if (prete > derniere_lue + 1) {
                r.perdues += prete - derniere_lue - 1;
            }
            mesures_noter(&mesures, (int32_t)prete, t);
            derniere_lue = prete;
            r.lues++;
            t += LECTURE_HX711_US;
            continue;
        }
        if (avec_i2c) {
            if (t >= prochain_ordre) {
                // Le Pi renvoie les trois angles toutes les 100 ms.
                uint16_t angles[3] = {1350, 900, 0};
                plateau_ecrire(&p, REGISTRE_ANGLES, angles, 3, t);
                prochain_ordre = t + 100000;
            }
            faux.horloge_us = t;
            plateau_pas(&p, t);
            t = faux.horloge_us;
        }
        t += PASSE_US;
        mesures_avancer(&mesures, t);
    }
    r.par_seconde = mesures.par_seconde;
    r.transactions = faux.transactions;
    r.transaction_la_plus_longue_us = faux.plus_longue_us;
    return r;
}

static void verifier_rythme(const resultat_t *r, uint64_t duree_us) {
    unsigned attendues = (unsigned)(duree_us / PERIODE_HX711_US);
    VERIFIER(r->perdues == 0);
    VERIFIER(r->lues + 1 >= attendues);
    VERIFIER(r->par_seconde == 80);
    // Un trou entre deux tours de la boucle bien plus court que la période du HX711 ...
    VERIFIER(r->plus_long_trou_us < PERIODE_HX711_US / 4);
    // ... et plus court que le silence de fin de trame du Modbus (sinon une trame entendue serait
    // coupée en deux).
    VERIFIER(r->plus_long_trou_us < MODBUS_SILENCE_US);
}

static void rythme_sans_i2c(void) {
    resultat_t r = simuler(false, true, true, 0, 3000000);
    verifier_rythme(&r, 3000000);
    VERIFIER(r.transactions == 0);
}

static void rythme_avec_i2c(void) {
    resultat_t sans = simuler(false, true, true, 0, 3000000);
    resultat_t avec = simuler(true, true, true, 0, 3000000);
    verifier_rythme(&avec, 3000000);
    VERIFIER(avec.transactions > 100);  // les servos et le capteur travaillent vraiment
    VERIFIER(avec.lues == sans.lues);
    VERIFIER(avec.transaction_la_plus_longue_us < MODBUS_SILENCE_US);
}

static void rythme_capteur_absent(void) {
    resultat_t r = simuler(true, true, false, 0, 3000000);
    verifier_rythme(&r, 3000000);
}

static void rythme_puces_absentes(void) {
    resultat_t r = simuler(true, false, false, 0, 3000000);
    verifier_rythme(&r, 3000000);
}

static void rythme_bus_bloque(void) {
    // Bus bloqué : chaque transaction attend sa limite de 1,5 ms avant d'abandonner.
    resultat_t r = simuler(true, false, false, 1500, 3000000);
    verifier_rythme(&r, 3000000);
    VERIFIER(r.transaction_la_plus_longue_us <= 1500);
}

void essais_rythme(void) {
    printf("Rythme de la pesée avec l'I2C\n");
    LANCER(rythme_sans_i2c);
    LANCER(rythme_avec_i2c);
    LANCER(rythme_capteur_absent);
    LANCER(rythme_puces_absentes);
    LANCER(rythme_bus_bloque);
}
