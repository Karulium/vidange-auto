#include "mesures.h"

void mesures_init(mesures_t *m, uint32_t sans_mesure_ms, bool exemple, uint64_t t_us) {
    m->sans_mesure_ms = sans_mesure_ms;
    m->exemple = exemple;
    m->une_mesure = false;
    m->brut = 0;
    m->numero = 0;
    m->heure_us = t_us;
    m->debut_seconde_us = t_us;
    m->compte = 0;
    m->par_seconde = 0;
}

void mesures_avancer(mesures_t *m, uint64_t t_us) {
    if (t_us - m->debut_seconde_us < 1000000) {
        return;
    }
    // Plus d'une seconde sans appel : la seconde passée est quand même comptée seule.
    m->par_seconde = t_us - m->debut_seconde_us < 2000000 ? m->compte : 0;
    m->compte = 0;
    m->debut_seconde_us = t_us;
}

void mesures_noter(mesures_t *m, int32_t brut, uint64_t t_us) {
    mesures_avancer(m, t_us);
    m->une_mesure = true;
    m->brut = brut;
    m->numero++;
    m->heure_us = t_us;
    if (m->compte < UINT16_MAX) {
        m->compte++;
    }
}

bool mesures_muet(const mesures_t *m, uint64_t t_us) {
    return !m->une_mesure || t_us - m->heure_us > (uint64_t)m->sans_mesure_ms * 1000;
}

void mesures_registres(const mesures_t *m, uint16_t trames_abimees, uint64_t t_us,
                       uint16_t *registres) {
    uint32_t brut = (uint32_t)m->brut;
    uint64_t age_ms = (t_us - m->heure_us) / 1000;
    uint16_t etat = 0;
    if (mesures_muet(m, t_us)) {
        etat |= ETAT_HX711_MUET;
    }
    if (m->exemple) {
        etat |= ETAT_EXEMPLE;
    }
    registres[REGISTRE_BRUT_FORT] = (uint16_t)(brut >> 16);
    registres[REGISTRE_BRUT_FAIBLE] = (uint16_t)(brut & 0xFFFF);
    registres[REGISTRE_NUMERO] = m->numero;
    registres[REGISTRE_AGE_MS] = age_ms > UINT16_MAX ? UINT16_MAX : (uint16_t)age_ms;
    registres[REGISTRE_ETAT] = etat;
    registres[REGISTRE_PAR_SECONDE] = m->par_seconde;
    registres[REGISTRE_TRAMES_ABIMEES] = trames_abimees;
    registres[REGISTRE_SIGNATURE] = SIGNATURE;
}
