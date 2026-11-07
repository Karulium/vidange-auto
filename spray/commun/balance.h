// Une balance de flacon du spray (cellule de 1 kg + HX711), sans matériel : essayée sur PC.
//
// La carte donne chaque mesure brute du HX711 (lue par ../../pesee/src/hx711.c) ; la balance
// garde les `moyenne_de` dernières et en tire :
// - la mesure brute moyenne (registres 10 à 17) ;
// - le poids en dixièmes de gramme, avec l'étalonnage de pesees.yaml (registres 18 à 21) :
//   poids = (brut − zero_brut) / brut_par_kg ;
// - « muette » : aucune mesure depuis `sans_mesure_us` (HX711 débranché) ;
// - « instable » : entre la plus petite et la plus grande des dernières mesures, plus que le
//   seuil (flacon qu'on manipule, cellule abîmée).
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define BALANCE_MESURES_MAX 16

typedef struct {
    int32_t zero_brut;
    float brut_par_kg;
    uint8_t moyenne_de;
    uint64_t sans_mesure_us;
    int32_t instable_dixiemes;
    int32_t mesures[BALANCE_MESURES_MAX];
    uint8_t nb;
    uint8_t prochaine;
    bool une_mesure;
    uint64_t derniere_us;
} balance_t;

void balance_init(balance_t *b, int32_t zero_brut, float brut_par_kg, uint8_t moyenne_de,
                  uint32_t sans_mesure_ms, int32_t instable_dixiemes);

// Une mesure brute du HX711, lue à l'heure t_us.
void balance_mesure(balance_t *b, int32_t brut, uint64_t t_us);

bool balance_muette(const balance_t *b, uint64_t t_us);
bool balance_instable(const balance_t *b);
// Mesure brute moyenne (0 sans mesure).
int32_t balance_brut(const balance_t *b);
// Poids moyen, en dixièmes de gramme (0 sans mesure).
int32_t balance_dixiemes(const balance_t *b);
