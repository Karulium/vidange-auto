// Le bus I2C vu par le pilote du LIS3DH. Sur le RP2040 : main.c ; dans les essais sur PC :
// un faux LIS3DH (tests/faux_lis3dh.c).
#pragma once

#include <stddef.h>
#include <stdint.h>

typedef struct {
    // Envoie « n » octets à l'appareil « adresse ». Rend 0 si tout est bien passé.
    int (*ecrire)(void *contexte, uint8_t adresse, const uint8_t *octets, size_t n);
    // Lit « n » octets à partir du registre « registre ». Rend 0 si tout est bien passé.
    int (*lire)(void *contexte, uint8_t adresse, uint8_t registre, uint8_t *octets, size_t n);
    // Attend « ms » millisecondes (le chien de garde doit rester nourri pendant ce temps).
    void (*attendre_ms)(void *contexte, uint32_t ms);
    void *contexte;
} bus_i2c_t;
