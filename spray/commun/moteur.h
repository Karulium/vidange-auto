// Générateur de pas d'un moteur pas à pas (pilote TMC2209 en pas/direction), sans matériel :
// essayé sur PC (tests/), appelé sur la carte par une minuterie toutes les `periode_us`.
//
// À chaque tour, moteur_tick dit s'il faut un pas (et dans quel sens) : la carte monte alors la
// broche PAS, et la redescend au tour suivant (une impulsion dure une période ; au plus un pas
// tous les 2 tours). La vitesse monte et descend en rampe (`acceleration`), et le moteur freine
// à temps pour s'arrêter sur sa cible.
//
// Seulement des nombres entiers : la minuterie de l'ESP32-S3 ne doit pas utiliser de virgule
// flottante. Vitesses en millièmes de pas par seconde à l'intérieur.
//
// Recherche du capteur (prise d'origine, « ranger ») : avec `arret_sur_capteur`, le moteur
// s'arrête net au tour où le capteur voit le bras, et garde la position de cet instant
// (`position_capteur`) : la carte en fait le 0.
#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    // Réglages.
    uint32_t periode_us;
    uint32_t vitesse_max_m;  // millièmes de pas/s
    uint32_t acceleration;   // pas/s²
    uint32_t pas_de_vitesse_m;  // gain de vitesse par tour (millièmes de pas/s)
    // Ce qu'on lui demande.
    bool vers_cible;     // aller à `cible` ;
    int8_t sens_libre;   // sinon tourner sans fin dans ce sens (+1, -1) ; 0 : arrêté
    int32_t cible;
    bool arret_sur_capteur;
    // Ce qu'il fait.
    int32_t position;  // pas
    uint32_t vitesse_m;
    uint64_t accumulateur;  // pas × µs × 1000
    int8_t sens;            // sens du mouvement en cours (+1, -1)
    bool impulsion;         // la broche PAS est en haut
    bool capteur_atteint;
    int32_t position_capteur;
} moteur_t;

void moteur_init(moteur_t *m, uint32_t vitesse_max, uint32_t acceleration, uint32_t periode_us);

// Aller à la position `cible` (pas).
void moteur_aller(moteur_t *m, int32_t cible, bool arret_sur_capteur);

// Tourner sans fin dans un sens (+1 ou -1), jusqu'au capteur ou jusqu'à moteur_arreter.
void moteur_tourner(moteur_t *m, int8_t sens, bool arret_sur_capteur);

// Arrêt net, là où il est.
void moteur_arreter(moteur_t *m);

// Le capteur a été atteint : cet endroit devient la position 0.
void moteur_zero_au_capteur(moteur_t *m);

bool moteur_bouge(const moteur_t *m);

// Un tour du générateur. `capteur` : ce que voit le capteur en ce moment. Rend +1 ou -1 quand un
// pas commence (broche PAS à monter, broche SENS d'après le signe), 0 sinon.
int moteur_tick(moteur_t *m, bool capteur);
