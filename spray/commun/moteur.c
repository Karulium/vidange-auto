#include "moteur.h"

// Un pas quand l'accumulateur atteint 1 s (en µs) × 1000 (vitesse en millièmes).
#define UN_PAS 1000000000ull

void moteur_init(moteur_t *m, uint32_t vitesse_max, uint32_t acceleration, uint32_t periode_us) {
    *m = (moteur_t){0};
    m->periode_us = periode_us ? periode_us : 1;
    // Au plus un pas tous les 2 tours (l'impulsion dure un tour).
    uint32_t plafond = 1000000u / (2u * m->periode_us);
    if (vitesse_max > plafond) {
        vitesse_max = plafond;
    }
    m->vitesse_max_m = vitesse_max * 1000u;
    m->acceleration = acceleration ? acceleration : 1;
    uint64_t pas = (uint64_t)m->acceleration * m->periode_us / 1000u;
    m->pas_de_vitesse_m = pas ? (uint32_t)pas : 1;
    m->sens = 1;
}

void moteur_aller(moteur_t *m, int32_t cible, bool arret_sur_capteur) {
    m->vers_cible = true;
    m->sens_libre = 0;
    m->cible = cible;
    m->arret_sur_capteur = arret_sur_capteur;
    m->capteur_atteint = false;
}

void moteur_tourner(moteur_t *m, int8_t sens, bool arret_sur_capteur) {
    m->vers_cible = false;
    m->sens_libre = sens > 0 ? 1 : -1;
    m->arret_sur_capteur = arret_sur_capteur;
    m->capteur_atteint = false;
}

void moteur_arreter(moteur_t *m) {
    m->vers_cible = false;
    m->sens_libre = 0;
    m->arret_sur_capteur = false;
    m->vitesse_m = 0;
    m->accumulateur = 0;
}

void moteur_zero_au_capteur(moteur_t *m) {
    m->position -= m->position_capteur;
    m->cible -= m->position_capteur;
    m->position_capteur = 0;
    m->capteur_atteint = false;
}

bool moteur_bouge(const moteur_t *m) {
    if (m->vitesse_m) {
        return true;
    }
    return m->vers_cible ? m->position != m->cible : m->sens_libre != 0;
}

int moteur_tick(moteur_t *m, bool capteur) {
    m->impulsion = false;
    if (m->arret_sur_capteur && capteur) {
        m->capteur_atteint = true;
        m->position_capteur = m->position;
        moteur_arreter(m);
        return 0;
    }
    int8_t voulu;
    uint64_t restant;  // pas jusqu'à la cible
    if (m->vers_cible) {
        int64_t ecart = (int64_t)m->cible - m->position;
        if (ecart == 0) {
            m->vitesse_m = 0;
            m->accumulateur = 0;
            return 0;
        }
        voulu = ecart > 0 ? 1 : -1;
        restant = (uint64_t)(ecart > 0 ? ecart : -ecart);
    } else if (m->sens_libre) {
        voulu = m->sens_libre;
        restant = UINT64_MAX;
    } else {
        m->vitesse_m = 0;
        m->accumulateur = 0;
        return 0;
    }
    // Freiner : pour changer de sens, ou s'il ne reste que la distance d'arrêt (v² ≥ 2·a·d).
    bool freiner;
    if (m->vitesse_m && voulu != m->sens) {
        freiner = true;
    } else {
        uint64_t v = m->vitesse_m / 1000u;
        freiner = restant != UINT64_MAX && v * v >= 2u * (uint64_t)m->acceleration * restant;
    }
    if (freiner) {
        m->vitesse_m = m->vitesse_m > m->pas_de_vitesse_m ? m->vitesse_m - m->pas_de_vitesse_m : 0;
        if (m->vitesse_m == 0) {
            // Arrêté pour changer de sens ; ou un peu tôt avant la cible : le tour suivant
            // repart doucement.
            m->sens = voulu;
            return 0;
        }
    } else if (m->vitesse_m < m->vitesse_max_m) {
        if (m->vitesse_m == 0) {
            m->sens = voulu;
        }
        m->vitesse_m += m->pas_de_vitesse_m;
        if (m->vitesse_m > m->vitesse_max_m) {
            m->vitesse_m = m->vitesse_max_m;
        }
    }
    m->accumulateur += (uint64_t)m->vitesse_m * m->periode_us;
    if (m->accumulateur < UN_PAS) {
        return 0;
    }
    m->accumulateur -= UN_PAS;
    m->position += m->sens;
    m->impulsion = true;
    return m->sens;
}
