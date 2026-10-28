// Faux capteur LIS3DH sur un faux bus I2C, pour essayer le pilote sans matériel.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "bus_i2c.h"

typedef struct {
    uint8_t adresse;      // adresse où il répond
    uint8_t who_am_i;     // 0x33 pour un vrai LIS3DH
    uint8_t registres[0x40];
    int32_t mg[3];        // accélération qu'il « ressent »
    int32_t autotest_mg;  // ce que l'autotest ajoute sur chaque axe (un vrai : quelques centaines)
    bool muet;            // ne répond plus à rien
    bool sans_mesure;     // répond, mais n'a jamais de mesure nouvelle
    int erreurs_a_venir;  // les prochaines lectures ratent
    int lectures_suite_sans_bit;  // lectures de plusieurs registres sans le bit 0x80 (faute)
    uint32_t attendu_ms;  // temps total passé à attendre
    bus_i2c_t bus;
} faux_lis3dh_t;

void faux_lis3dh_preparer(faux_lis3dh_t *faux);
