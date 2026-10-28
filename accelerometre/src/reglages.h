// Réglages du programme de l'accéléromètre, avec leur vérification.
//
// Les valeurs de départ viennent de pi/reglages/accelerometre.yaml (copiées dans
// reglages_genere.h quand on fabrique le programme). Elles sont revérifiées ici au démarrage,
// et à chaque changement (seuil changé à la console ; plus tard, réglages envoyés par le Pi).
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Axes du capteur, en bits (même valeurs que vidange/accelerometre/entete.py).
#define AXE_X 1u
#define AXE_Y 2u
#define AXE_Z 4u

typedef struct {
    uint8_t pleine_echelle_g;      // 2, 4, 8 ou 16
    uint16_t mesures_par_seconde;  // 1, 10, 25, 50, 100, 200, 400 ou 1344
    uint8_t axes;                  // AXE_X | AXE_Y | AXE_Z : les axes horizontaux
    uint32_t seuil_mg;             // un choc dépasse ce seuil (millièmes de g)...
    uint32_t duree_min_ms;         // ... pendant au moins cette durée
    uint32_t maintien_ms;          // « OK » reste coupé ce temps après le dernier dépassement
    uint32_t constante_fond_ms;    // temps de réponse du fond lent retiré de la mesure
    uint32_t sans_mesure_ms;       // plus de mesure depuis ce temps : panne
    uint32_t erreurs_lecture_max;  // lectures I2C ratées de suite : panne
    uint32_t figee_ms;             // mêmes valeurs exactes pendant ce temps : panne
    uint32_t reessai_ms;           // attente avant de revérifier le capteur après une panne
} reglages_t;

// Les réglages de départ (ceux de accelerometre.yaml).
reglages_t reglages_depart(void);

// true si les réglages sont bons. Sinon, écrit dans « message » ce qui ne va pas.
bool reglages_verifier(const reglages_t *r, char *message, size_t taille);
