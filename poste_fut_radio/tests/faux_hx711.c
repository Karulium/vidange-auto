#include "faux_hx711.h"

void faux_hx711_init(faux_hx711_t *f, int32_t valeur, uint64_t periode_us, uint64_t t_us) {
    *f = (faux_hx711_t){0};
    f->valeur = valeur;
    f->periode_us = periode_us;
    f->prochaine_us = t_us + periode_us;
    f->maintenant_us = t_us;
}

void faux_hx711_avancer(faux_hx711_t *f, uint64_t t_us) {
    f->maintenant_us = t_us;
    while (t_us >= f->prochaine_us) {
        // Une nouvelle mesure remplace celle qui n'a pas été lue.
        f->pret = !f->debranche;
        f->envoyee = (uint32_t)f->valeur & 0xFFFFFF;
        f->impulsions = 0;
        f->prochaine_us += f->periode_us;
    }
}

static bool faux_dt(void *contexte) {
    faux_hx711_t *f = contexte;
    if (!f->pret) {
        return true;
    }
    if (f->impulsions == 0) {
        return false;
    }
    if (f->impulsions > 24) {
        return true;
    }
    return (f->envoyee >> (24 - f->impulsions)) & 1;
}

static void faux_sck(void *contexte, bool haut) {
    faux_hx711_t *f = contexte;
    if (haut && !f->sck && f->pret) {
        f->impulsions++;
        if (f->impulsions == 25) {
            // 25e impulsion : mesure lue, DT reste à 1 jusqu'à la suivante.
            f->pret = false;
            f->lues++;
        }
    }
    f->sck = haut;
}

static void faux_attendre(void *contexte, uint32_t us) {
    (void)contexte;
    (void)us;
}

broches_hx711_t faux_hx711_broches(faux_hx711_t *f) {
    broches_hx711_t broches = {faux_dt, faux_sck, faux_attendre, f};
    return broches;
}
