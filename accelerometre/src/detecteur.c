#include "detecteur.h"

#include <math.h>
#include <stddef.h>

#define US_PAR_MS 1000ull

static choc_t *choc_en_cours(detecteur_t *d) {
    return &d->historique[(d->chocs - 1) % HISTORIQUE_CHOCS];
}

static void finir_choc(detecteur_t *d) {
    if (d->en_choc) {
        choc_en_cours(d)->fini = true;
    }
    d->en_choc = false;
}

static void oublier_mesures(detecteur_t *d) {
    finir_choc(d);
    d->fond_pret = false;
    d->erreurs_suite = 0;
    d->niveau_mg = 0;
    d->en_depassement = false;
}

static void tomber_en_panne(detecteur_t *d, uint64_t t_us, uint32_t panne) {
    d->pannes |= panne;
    d->pannes_vues |= panne;
    d->pret = false;
    d->t_reessai_us = t_us + d->reglages.reessai_ms * US_PAR_MS;
    oublier_mesures(d);
}

void detecteur_demarrer(detecteur_t *d, const reglages_t *reglages) {
    *d = (detecteur_t){0};
    d->reglages = *reglages;
    char message[96];
    if (!reglages_verifier(reglages, message, sizeof message)) {
        d->pannes = d->pannes_vues = PANNE_REGLAGES;
    }
}

bool detecteur_changer_seuil(detecteur_t *d, uint32_t seuil_mg) {
    reglages_t essai = d->reglages;
    essai.seuil_mg = seuil_mg;
    return detecteur_changer_reglages(d, &essai);
}

bool detecteur_changer_reglages(detecteur_t *d, const reglages_t *reglages) {
    char message[96];
    if (!reglages_verifier(reglages, message, sizeof message)) {
        return false;
    }
    bool revoir_capteur = (d->pannes & PANNE_REGLAGES) ||
                          reglages->pleine_echelle_g != d->reglages.pleine_echelle_g ||
                          reglages->mesures_par_seconde != d->reglages.mesures_par_seconde;
    d->reglages = *reglages;
    d->pannes &= ~PANNE_REGLAGES;
    if (revoir_capteur) {
        // Le capteur doit être redémarré avec ses nouveaux réglages : tout de suite.
        d->pret = false;
        d->t_reessai_us = 0;
        oublier_mesures(d);
    }
    return true;
}

bool detecteur_choc(const choc_t historique[HISTORIQUE_CHOCS], uint32_t chocs, uint32_t numero,
                    choc_t *choc) {
    if (numero == 0 || numero > chocs) {
        return false;
    }
    const choc_t *trouve = &historique[(numero - 1) % HISTORIQUE_CHOCS];
    if (trouve->numero != numero) {
        return false;
    }
    *choc = *trouve;
    return true;
}

bool detecteur_verification_due(const detecteur_t *d, uint64_t t_us) {
    return !(d->pannes & PANNE_REGLAGES) && !d->pret && t_us >= d->t_reessai_us;
}

void detecteur_verification_faite(detecteur_t *d, uint64_t t_us, uint32_t panne) {
    if (panne) {
        tomber_en_panne(d, t_us, panne);
        return;
    }
    // Le capteur vient de passer son autotest : les pannes du capteur sont effacées.
    d->pannes &= PANNE_REGLAGES;
    d->pret = d->pannes == 0;
    d->t_mesure_us = t_us;
    oublier_mesures(d);
}

void detecteur_erreur_lecture(detecteur_t *d, uint64_t t_us) {
    if (!d->pret) {
        return;
    }
    if (++d->erreurs_suite >= d->reglages.erreurs_lecture_max) {
        tomber_en_panne(d, t_us, PANNE_LECTURE);
    }
}

void detecteur_surveiller(detecteur_t *d, uint64_t t_us) {
    // Une heure prise avant la dernière vérification du capteur ne compte pas.
    if (d->pret && t_us > d->t_mesure_us &&
        t_us - d->t_mesure_us > d->reglages.sans_mesure_ms * US_PAR_MS) {
        tomber_en_panne(d, t_us, PANNE_MESURE_ABSENTE);
    }
}

void detecteur_mesure(detecteur_t *d, uint64_t t_us, const int32_t mg[3]) {
    if (!d->pret) {
        return;
    }
    const reglages_t *r = &d->reglages;
    if (t_us < d->t_mesure_us) {
        t_us = d->t_mesure_us;  // heure prise avant la vérification du capteur
    }
    uint64_t ecart_us = t_us - d->t_mesure_us;
    d->t_mesure_us = t_us;
    d->erreurs_suite = 0;

    // Un vrai capteur a toujours un peu de bruit : des valeurs identiques trop longtemps
    // veulent dire qu'il ne mesure plus.
    if (d->fond_pret && mg[0] == d->precedente[0] && mg[1] == d->precedente[1] &&
        mg[2] == d->precedente[2]) {
        if (t_us - d->t_identique_us >= r->figee_ms * US_PAR_MS) {
            tomber_en_panne(d, t_us, PANNE_MESURE_FIGEE);
            return;
        }
    } else {
        d->t_identique_us = t_us;
        for (int axe = 0; axe < 3; axe++) {
            d->precedente[axe] = mg[axe];
        }
    }

    if (!d->fond_pret) {
        for (int axe = 0; axe < 3; axe++) {
            d->fond[axe] = (float)mg[axe];
        }
        d->fond_pret = true;
        d->t_identique_us = t_us;
        return;
    }

    float somme = 0.0f;
    for (int axe = 0; axe < 3; axe++) {
        if (r->axes & (1u << axe)) {
            float ecart = (float)mg[axe] - d->fond[axe];
            somme += ecart * ecart;
        }
    }
    d->niveau_mg = (uint32_t)sqrtf(somme);

    if (d->niveau_mg >= r->seuil_mg) {
        if (!d->en_depassement) {
            d->en_depassement = true;
            d->t_depassement_us = t_us;
            d->pic_depassement_mg = 0;
        }
        if (d->niveau_mg > d->pic_depassement_mg) {
            d->pic_depassement_mg = d->niveau_mg;
        }
        if (d->en_choc) {
            d->t_dernier_us = t_us;
            if (d->niveau_mg > d->pic_choc_mg) {
                d->pic_choc_mg = d->niveau_mg;
            }
        } else if (t_us - d->t_depassement_us >= r->duree_min_ms * US_PAR_MS) {
            d->en_choc = true;
            d->chocs++;
            d->t_dernier_us = t_us;
            d->pic_choc_mg = d->pic_depassement_mg;
            *choc_en_cours(d) = (choc_t){.numero = d->chocs, .t_debut_us = d->t_depassement_us};
        }
        if (d->en_choc) {
            choc_t *choc = choc_en_cours(d);
            choc->pic_mg = d->pic_choc_mg;
            choc->duree_ms = (uint32_t)((t_us - choc->t_debut_us) / US_PAR_MS);
        }
        // Pendant un dépassement, le fond ne suit pas (le choc ne doit pas s'y fondre).
        return;
    }

    d->en_depassement = false;
    // Fond lent : il rattrape la mesure avec un temps de réponse constante_fond_ms.
    float part = (float)ecart_us / (float)(r->constante_fond_ms * US_PAR_MS);
    if (part > 1.0f) {
        part = 1.0f;
    }
    for (int axe = 0; axe < 3; axe++) {
        d->fond[axe] += part * ((float)mg[axe] - d->fond[axe]);
    }
    if (d->en_choc && t_us - d->t_dernier_us >= r->maintien_ms * US_PAR_MS) {
        finir_choc(d);
    }
}

bool detecteur_ok(const detecteur_t *d) {
    return d->pret && d->pannes == 0 && d->fond_pret && !d->en_choc;
}

const char *detecteur_texte_panne(uint32_t pannes) {
    if (pannes & PANNE_REGLAGES) return "réglages faux";
    if (pannes & PANNE_CAPTEUR) return "capteur absent";
    if (pannes & PANNE_AUTOTEST) return "autotest raté";
    if (pannes & PANNE_LECTURE) return "lectures I2C ratées";
    if (pannes & PANNE_MESURE_ABSENTE) return "plus de mesure";
    if (pannes & PANNE_MESURE_FIGEE) return "mesure figée";
    return "aucune";
}
