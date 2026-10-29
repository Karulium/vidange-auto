// La puce de pesée HX711 (voie A, gain 128), lue par deux broches : DT (données) et SCK
// (horloge). Aucun matériel ici : les broches sont données par le programme (main.c) ou par
// les essais sur PC (tests/faux_hx711.c).
//
// La puce dit qu'une mesure est prête en mettant DT à 0. On la lit alors en 24 impulsions de
// SCK (un bit à chaque fois, le plus fort d'abord), puis une 25e qui choisit la voie A, gain 128,
// pour la mesure suivante. SCK ne doit jamais rester à 1 plus de 60 µs (la puce s'endormirait) :
// le programme coupe les interruptions pendant la lecture (environ 50 µs).
//
// La cadence (10 ou 80 mesures par seconde) se choisit sur la carte HX711 elle-même, par sa
// broche RATE : 80 mesures par seconde = RATE au 3,3 V (voir essai-etabli.md).
#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool (*lire_dt)(void *contexte);
    void (*ecrire_sck)(void *contexte, bool haut);
    void (*attendre_us)(void *contexte, uint32_t us);
    void *contexte;
} broches_hx711_t;

// Une mesure attend d'être lue (DT à 0).
bool hx711_pret(const broches_hx711_t *broches);

// Lit la mesure prête : un nombre signé de 24 bits (de -8 388 608 à 8 388 607).
int32_t hx711_lire(const broches_hx711_t *broches);
