// Le bus I2C vu par le reste du programme : deux fonctions, données par main.c (le vrai bus du
// RP2040) ou par les essais sur PC (un faux bus avec une fausse PCA9685 et un faux VL6180X).
// Chaque fonction rend vrai si l'appareil a répondu, faux s'il n'a pas répondu à temps (débranché,
// bus bloqué) : l'attente est limitée par la fonction, jamais infinie.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
    // Écrit n octets à l'appareil d'adresse adr.
    bool (*ecrire)(void *contexte, uint8_t adr, const uint8_t *octets, size_t n);
    // Écrit ni octets (le numéro du registre), puis lit n octets (redémarrage, sans arrêt entre).
    bool (*lire)(void *contexte, uint8_t adr, const uint8_t *index, size_t ni, uint8_t *dest,
                 size_t n);
    void *contexte;
} i2c_bus_t;
