#include "reglages.h"

#include <stdio.h>

#include "reglages_genere.h"

reglages_t reglages_depart(void) {
    reglages_t r = {
        .pleine_echelle_g = REGLAGE_PLEINE_ECHELLE_G,
        .mesures_par_seconde = REGLAGE_MESURES_PAR_SECONDE,
        .axes = REGLAGE_AXES,
        .seuil_mg = REGLAGE_SEUIL_MG,
        .duree_min_ms = REGLAGE_DUREE_MIN_MS,
        .maintien_ms = REGLAGE_MAINTIEN_MS,
        .constante_fond_ms = REGLAGE_CONSTANTE_FOND_MS,
        .sans_mesure_ms = REGLAGE_SANS_MESURE_MS,
        .erreurs_lecture_max = REGLAGE_ERREURS_LECTURE_MAX,
        .figee_ms = REGLAGE_FIGEE_MS,
        .reessai_ms = REGLAGE_REESSAI_MS,
    };
    return r;
}

static bool faux(char *message, size_t taille, const char *texte, uint32_t valeur) {
    snprintf(message, taille, texte, (unsigned long)valeur);
    return false;
}

bool reglages_verifier(const reglages_t *r, char *message, size_t taille) {
    uint8_t fs = r->pleine_echelle_g;
    if (fs != 2 && fs != 4 && fs != 8 && fs != 16) {
        return faux(message, taille, "pleine_echelle_g (%lu) : 2, 4, 8 ou 16", fs);
    }
    uint16_t f = r->mesures_par_seconde;
    if (f != 1 && f != 10 && f != 25 && f != 50 && f != 100 && f != 200 && f != 400 &&
        f != 1344) {
        return faux(message, taille,
                    "mesures_par_seconde (%lu) : 1, 10, 25, 50, 100, 200, 400 ou 1344", f);
    }
    if (r->axes == 0 || (r->axes & ~(AXE_X | AXE_Y | AXE_Z)) != 0) {
        return faux(message, taille, "axes (%lu) : au moins un axe parmi x, y, z", r->axes);
    }
    if (r->seuil_mg == 0 || r->seuil_mg >= fs * 1000u) {
        return faux(message, taille,
                    "seuil (%lu mg) : plus que 0 et moins que la pleine échelle", r->seuil_mg);
    }
    if (r->duree_min_ms > 1000) {
        return faux(message, taille, "duree_min_ms (%lu) : au plus 1000", r->duree_min_ms);
    }
    if (r->maintien_ms < 10 || r->maintien_ms > 60000) {
        return faux(message, taille, "maintien_ms (%lu) : de 10 à 60000", r->maintien_ms);
    }
    // Mêmes règles que pi/vidange/reglages.py (temps comptés en mesures).
    uint32_t periode_us = 1000000u / f;  // temps entre deux mesures, en µs
    if (r->sans_mesure_ms * 1000u < 3u * periode_us || r->sans_mesure_ms > 10000) {
        return faux(message, taille, "sans_mesure_ms (%lu) : au moins 3 mesures, au plus 10000",
                    r->sans_mesure_ms);
    }
    if (r->figee_ms * 1000ull < 20ull * periode_us || r->figee_ms > 600000) {
        return faux(message, taille, "figee_ms (%lu) : au moins 20 mesures, au plus 600000",
                    r->figee_ms);
    }
    if (r->constante_fond_ms < 100 || r->constante_fond_ms * 1000ull < 10ull * periode_us ||
        r->constante_fond_ms > 600000) {
        return faux(message, taille,
                    "constante_fond_ms (%lu) : au moins 100 et 10 mesures, au plus 600000",
                    r->constante_fond_ms);
    }
    if (r->erreurs_lecture_max < 1 || r->erreurs_lecture_max > 1000) {
        return faux(message, taille, "erreurs_lecture_max (%lu) : de 1 à 1000",
                    r->erreurs_lecture_max);
    }
    if (r->reessai_ms < 100 || r->reessai_ms > 600000) {
        return faux(message, taille, "reessai_ms (%lu) : de 100 à 600000", r->reessai_ms);
    }
    if (taille > 0) {
        message[0] = '\0';
    }
    return true;
}
