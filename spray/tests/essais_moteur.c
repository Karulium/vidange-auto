// Essais du générateur de pas : rampe, vitesse, cible exacte, capteur, changement de sens.
#include "essai.h"
#include "moteur.h"

#define PERIODE_US 50

// Fait tourner le générateur `tours` fois ; rend le nombre de pas, note la position la plus
// grande et vérifie qu'il n'y a jamais deux pas de suite (l'impulsion dure un tour).
static int tourner(moteur_t *m, long tours, bool (*capteur)(const moteur_t *), int32_t *maxi) {
    int pas = 0;
    for (long t = 0; t < tours; t++) {
        bool avant = m->impulsion;
        int p = moteur_tick(m, capteur ? capteur(m) : false);
        if (p) {
            VERIFIER(!avant);
            pas++;
        }
        if (maxi && m->position > *maxi) {
            *maxi = m->position;
        }
    }
    return pas;
}

static void aller_a_la_cible(void) {
    moteur_t m;
    moteur_init(&m, 800, 1600, PERIODE_US);
    moteur_aller(&m, 1000, false);
    VERIFIER(moteur_bouge(&m));
    int32_t maxi = 0;
    long tours = 0;
    while (moteur_bouge(&m) && tours < 200000) {
        tourner(&m, 1, NULL, &maxi);
        tours++;
    }
    VERIFIER(m.position == 1000);
    VERIFIER(maxi == 1000);  // jamais au-delà
    // 200 pas pour monter à 800 pas/s, 600 à 800 pas/s, 200 pour descendre : ≈ 1,75 s.
    double secondes = tours * PERIODE_US / 1e6;
    VERIFIER(secondes > 1.65 && secondes < 1.9);
    // Il reste à sa place.
    VERIFIER(tourner(&m, 20000, NULL, NULL) == 0);
    VERIFIER(m.position == 1000);
}

static void vitesse_et_plafond(void) {
    moteur_t m;
    moteur_init(&m, 800, 1600, PERIODE_US);
    moteur_tourner(&m, 1, false);
    tourner(&m, 20000, NULL, NULL);  // 1 s : la rampe est finie
    int pas = tourner(&m, 20000, NULL, NULL);
    VERIFIER(pas >= 795 && pas <= 805);
    // Plus vite que le générateur ne peut : au plus un pas tous les 2 tours (10 000 pas/s).
    moteur_init(&m, 50000, 1000000, PERIODE_US);
    moteur_tourner(&m, -1, false);
    tourner(&m, 2000, NULL, NULL);
    pas = tourner(&m, 20000, NULL, NULL);
    VERIFIER(pas >= 9990 && pas <= 10000);
    VERIFIER(m.position < 0);
    moteur_arreter(&m);
    VERIFIER(!moteur_bouge(&m));
    VERIFIER(tourner(&m, 100, NULL, NULL) == 0);
}

static bool capteur_sous_moins_500(const moteur_t *m) {
    return m->position <= -500;
}

static void arret_sur_le_capteur(void) {
    moteur_t m;
    moteur_init(&m, 800, 1600, PERIODE_US);
    moteur_tourner(&m, -1, true);
    tourner(&m, 200000, capteur_sous_moins_500, NULL);
    VERIFIER(m.capteur_atteint);
    VERIFIER(m.position_capteur == -500 && m.position == -500);
    VERIFIER(!moteur_bouge(&m));
    moteur_zero_au_capteur(&m);
    VERIFIER(m.position == 0 && !m.capteur_atteint);
    // Capteur déjà vu au départ : arrêt tout de suite, sans un pas.
    m.position = -600;
    moteur_tourner(&m, -1, true);
    VERIFIER(tourner(&m, 10, capteur_sous_moins_500, NULL) == 0);
    VERIFIER(m.capteur_atteint && m.position_capteur == -600);
    // Sans arret_sur_capteur, le capteur ne l'arrête pas.
    moteur_init(&m, 800, 1600, PERIODE_US);
    m.position = -600;
    moteur_aller(&m, -700, false);
    tourner(&m, 100000, capteur_sous_moins_500, NULL);
    VERIFIER(m.position == -700 && !m.capteur_atteint);
}

static void changement_de_sens(void) {
    moteur_t m;
    moteur_init(&m, 800, 1600, PERIODE_US);
    moteur_aller(&m, 1000, false);
    tourner(&m, 10000, NULL, NULL);  // 0,5 s : à pleine vitesse, vers 200 pas
    int32_t milieu = m.position;
    VERIFIER(milieu > 150 && milieu < 250);
    moteur_aller(&m, 0, false);
    int32_t maxi = milieu;
    tourner(&m, 100000, NULL, &maxi);
    // Il freine d'abord (un peu plus loin), puis revient : jamais de demi-tour brutal.
    VERIFIER(maxi > milieu + 150 && maxi < milieu + 250);
    VERIFIER(m.position == 0 && !moteur_bouge(&m));
}

void essais_moteur(void) {
    printf("Moteurs\n");
    LANCER(aller_a_la_cible);
    LANCER(vitesse_et_plafond);
    LANCER(arret_sur_le_capteur);
    LANCER(changement_de_sens);
}
