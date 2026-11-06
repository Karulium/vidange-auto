#include "accu.h"

uint16_t accu_tension_mv(uint32_t broche_mv, uint32_t rapport_milliemes) {
    uint64_t mv = ((uint64_t)broche_mv * rapport_milliemes + 500) / 1000;
    return mv > UINT16_MAX ? UINT16_MAX : (uint16_t)mv;
}

uint8_t accu_pourcentage(const courbe_accu_t *courbe, uint16_t mv) {
    const uint16_t *t = courbe->mv;
    const uint8_t *p = courbe->pct;
    size_t n = courbe->points;
    if (n == 0) {
        return 0;
    }
    if (mv <= t[0]) {
        return p[0];
    }
    for (size_t i = 1; i < n; i++) {
        if (mv <= t[i]) {
            // En ligne droite entre les points i-1 et i, arrondi.
            uint32_t dt = (uint32_t)(t[i] - t[i - 1]);
            uint32_t ecart = (uint32_t)(mv - t[i - 1]);
            uint32_t dp = (uint32_t)(p[i] - p[i - 1]);
            return (uint8_t)(p[i - 1] + (dp * ecart + dt / 2) / dt);
        }
    }
    return p[n - 1];
}
