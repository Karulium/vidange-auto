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
void essais_reglages(void);
void essais_lis3dh(void);
void essais_detecteur(void);
void essais_console(void);
