// L'accu 18650 du plateau : sa tension (pont diviseur sur une entrée analogique) et son niveau
// en %, d'après la courbe de pi/reglages/pesees.yaml (poste_fut_radio → plateau → courbe_accu).
// Aucun matériel ici (essayé sur PC).
#pragma once

#include <stddef.h>
#include <stdint.h>

typedef struct {
    const uint16_t *mv;   // tensions, en montant
    const uint8_t *pct;   // niveau à chaque tension
    size_t points;
} courbe_accu_t;

// Tension de l'accu (mV) : tension lue sur la broche (mV) × rapport du pont (en millièmes),
// arrondie, 65 535 au plus.
uint16_t accu_tension_mv(uint32_t broche_mv, uint32_t rapport_milliemes);

// Niveau (%) à cette tension : entre deux points de la courbe, en ligne droite ; sous le premier
// point, son niveau ; au-dessus du dernier, le sien.
uint8_t accu_pourcentage(const courbe_accu_t *courbe, uint16_t mv);
