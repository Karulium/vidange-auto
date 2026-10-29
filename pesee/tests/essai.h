// Petit outil d'essais : chaque essai est une fonction ; VERIFIER note les échecs.
#pragma once

#include <stdio.h>

extern int essai_echecs;

#define VERIFIER(condition)                                                        \
    do {                                                                           \
        if (!(condition)) {                                                        \
            printf("  ÉCHEC %s:%d : %s\n", __FILE__, __LINE__, #condition);        \
            essai_echecs++;                                                        \
        }                                                                          \
    } while (0)

#define LANCER(essai)               \
    do {                            \
        printf("- %s\n", #essai);   \
        essai();                    \
    } while (0)

// Les essais de chaque fichier, lancés par essais.c.
void essais_hx711(void);
void essais_modbus(void);
void essais_mesures(void);
