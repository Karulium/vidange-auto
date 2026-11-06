// Un faux HX711 au bout des deux broches (DT, SCK), qui fait une mesure toutes les
// periode_us d'un temps imaginaire, comme le vrai à 10 mesures par seconde (RATE à la masse).
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "hx711.h"

typedef struct {
    int32_t valeur;        // la prochaine mesure (24 bits signés)
    uint64_t periode_us;   // entre deux mesures
    uint64_t prochaine_us; // heure de la prochaine mesure
    bool debranche;        // DT reste à 1 (tiré au 3,3 V) : jamais prêt
    // Ce que voient les broches.
    uint64_t maintenant_us;
    bool pret;
    bool sck;
    int impulsions;
    uint32_t envoyee;      // la mesure en cours de lecture (24 bits)
    int lues;
} faux_hx711_t;

void faux_hx711_init(faux_hx711_t *f, int32_t valeur, uint64_t periode_us, uint64_t t_us);

// Le temps passe jusqu'à t_us : une mesure peut devenir prête.
void faux_hx711_avancer(faux_hx711_t *f, uint64_t t_us);

broches_hx711_t faux_hx711_broches(faux_hx711_t *f);
