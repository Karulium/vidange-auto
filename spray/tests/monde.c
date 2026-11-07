#include "monde.h"

#include <string.h>

#define ADRESSE 1
#define OCTET_US 87

void monde_init(monde_t *w) {
    memset(w, 0, sizeof(*w));
    // Les réglages d'exemple de machine.yaml → spray (et spray → carte).
    w->r = (spray_reglages_t){
        .exemple = true,
        .course_dixiemes = 1100,
        .bras_pas_par_tour = 3200,
        .bras_depassement_pas = 89,
        .bras_temps_max_ms = 3000,
        .filtre_capteur_ms = 20,
        .air_avant_ms = 500,
        .temps_max_pompage_ms = 15000,
        .chasse_ms = 4500,
        .air_apres_ms = 1000,
        .nettoyage_pompe_ms = 5000,
        .sechage_ms = 15000,
        .silence_max_ms = 2000,
    };
    w->periode_us = 50;
    moteur_init(&w->bras, 800, 1600, w->periode_us);
    moteur_t *pompes[SPRAY_NB_FLACONS];
    for (int i = 0; i < SPRAY_NB_FLACONS; i++) {
        moteur_init(&w->pompes[i], 1600, 8000, w->periode_us);
        pompes[i] = &w->pompes[i];
        balance_init(&w->balances[i], 1000, 400000.0f, 8, 100, 30);
        w->grammes[i] = 400.0;
    }
    w->zero_brut = 1000;
    w->brut_par_g = 400.0;
    w->periode_mesure_us = 12500;  // 80 mesures par seconde
    w->g_par_pas = 1.0 / 1600;     // 1 g/s
    w->zone_capteur_pas = 9;       // ≈ 1°
    w->pilote_ok = true;
    w->t_us = 1000000;
    spray_init(&w->spray, &w->r, &w->bras, pompes, w->balances, 7, w->t_us);
    modbus_init(&w->bus, ADRESSE);
    // Les balances ont déjà mesuré un peu avant les essais.
    monde_avancer(w, 200);
}

static bool capteur_reel(const monde_t *w) {
    return !w->capteur_en_panne && w->bras_reel <= w->zone_capteur_pas;
}

static void mesurer(monde_t *w) {
    w->mesures++;
    for (int i = 0; i < SPRAY_NB_FLACONS; i++) {
        if (w->balance_debranchee[i]) {
            continue;
        }
        double g = w->grammes[i] + ((w->mesures & 1) ? w->bruit_g[i] : -w->bruit_g[i]);
        balance_mesure(&w->balances[i], (int32_t)(w->zero_brut + g * w->brut_par_g), w->t_us);
    }
}

void monde_avancer(monde_t *w, uint32_t ms) {
    uint32_t tours_par_ms = 1000 / w->periode_us;
    for (uint32_t m = 0; m < ms; m++) {
        for (uint32_t t = 0; t < tours_par_ms; t++) {
            w->t_us += w->periode_us;
            bool impulsion_avant = w->bras.impulsion;
            int pas = moteur_tick(&w->bras, capteur_reel(w));
            if (pas && impulsion_avant) {
                w->pas_simultanes++;
            }
            if (pas && !w->bras_bloque) {
                w->bras_reel += pas;
            }
            for (int i = 0; i < SPRAY_NB_FLACONS; i++) {
                if (moteur_tick(&w->pompes[i], false) > 0) {
                    w->pas_pompes[i]++;
                    if (!w->tube_pince[i]) {
                        w->grammes[i] -= w->g_par_pas;
                    }
                }
            }
            if (w->t_us >= w->prochaine_mesure_us) {
                w->prochaine_mesure_us = w->t_us + w->periode_mesure_us;
                mesurer(w);
            }
        }
        if (w->battre_auto && w->t_us >= w->prochain_battement_us) {
            w->prochain_battement_us = w->t_us + 250000;
            monde_battre(w);
        }
        spray_avancer(&w->spray, capteur_reel(w), w->pilote_ok, w->t_us);
        spray_sorties_t s = spray_sorties(&w->spray);
        w->buse_ms += s.ev_buse;
        w->chasse_ms += s.ev_chasse;
        w->nettoyage_ms += s.pompe_nettoyage;
    }
}

bool monde_attendre(monde_t *w, int registre, uint16_t masque, uint16_t valeur, uint32_t max_ms) {
    uint16_t r[SPRAY_NB_REGISTRES];
    for (uint32_t ms = 0; ms <= max_ms; ms += 10) {
        monde_lire(w, r);
        if ((r[registre] & masque) == valeur) {
            return true;
        }
        monde_avancer(w, 10);
    }
    return false;
}

size_t monde_trame_lecture(uint8_t *trame, uint8_t adresse, uint8_t fonction, uint16_t premier,
                           uint16_t nombre) {
    trame[0] = adresse;
    trame[1] = fonction;
    trame[2] = (uint8_t)(premier >> 8);
    trame[3] = (uint8_t)premier;
    trame[4] = (uint8_t)(nombre >> 8);
    trame[5] = (uint8_t)nombre;
    uint16_t crc = modbus_crc(trame, 6);
    trame[6] = (uint8_t)crc;
    trame[7] = (uint8_t)(crc >> 8);
    return 8;
}

size_t monde_trame_ecriture(uint8_t *trame, uint8_t adresse, uint16_t premier,
                            const uint16_t *valeurs, uint16_t nombre) {
    trame[0] = adresse;
    trame[1] = 16;
    trame[2] = (uint8_t)(premier >> 8);
    trame[3] = (uint8_t)premier;
    trame[4] = (uint8_t)(nombre >> 8);
    trame[5] = (uint8_t)nombre;
    trame[6] = (uint8_t)(2 * nombre);
    for (uint16_t i = 0; i < nombre; i++) {
        trame[7 + 2 * i] = (uint8_t)(valeurs[i] >> 8);
        trame[8 + 2 * i] = (uint8_t)valeurs[i];
    }
    size_t n = 7 + 2 * (size_t)nombre;
    uint16_t crc = modbus_crc(trame, n);
    trame[n] = (uint8_t)crc;
    trame[n + 1] = (uint8_t)(crc >> 8);
    return n + 2;
}

size_t monde_question(monde_t *w, const uint8_t *trame, size_t n, uint8_t *reponse) {
    // Un silence avant la question, puis un octet toutes les 87 µs (115 200 bauds).
    uint64_t t = w->t_us + 2000;
    size_t taille = 0;
    for (size_t i = 0; i < n; i++) {
        t += OCTET_US;
        if (modbus_recevoir(&w->bus, trame[i], t)) {
            taille = spray_repondre(&w->spray, &w->bus, w->t_us, reponse);
            modbus_oublier(&w->bus);
        }
    }
    return taille;
}

void monde_lire(monde_t *w, uint16_t *registres) {
    uint8_t q[8], r[MODBUS_REPONSE_MAX];
    monde_trame_lecture(q, ADRESSE, 4, 0, SPRAY_NB_REGISTRES);
    size_t n = monde_question(w, q, 8, r);
    for (int i = 0; i < SPRAY_NB_REGISTRES; i++) {
        registres[i] = n == 65 ? (uint16_t)(r[3 + 2 * i] << 8 | r[4 + 2 * i]) : 0;
    }
}

void monde_battre(monde_t *w) {
    uint8_t q[MODBUS_TRAME_MAX], r[MODBUS_REPONSE_MAX];
    w->battement++;
    size_t n = monde_trame_ecriture(q, ADRESSE, SPRAY_REGISTRE_BATTEMENT, &w->battement, 1);
    monde_question(w, q, n, r);
}

uint8_t monde_ordre(monde_t *w, uint16_t code, uint16_t p1, uint16_t p2) {
    uint8_t q[MODBUS_TRAME_MAX], r[MODBUS_REPONSE_MAX];
    w->numero++;
    uint16_t valeurs[4] = {code, p1, p2, w->numero};
    size_t n = monde_trame_ecriture(q, ADRESSE, SPRAY_REGISTRE_ORDRE, valeurs, 4);
    size_t taille = monde_question(w, q, n, r);
    return taille == 5 ? r[2] : 0;
}

bool monde_sortir(monde_t *w, uint16_t dixiemes) {
    monde_ordre(w, ORDRE_ORIGINE, 0, 0);
    if (!monde_attendre(w, 3, SPRAY_ETAT_ORIGINE_FAITE, SPRAY_ETAT_ORIGINE_FAITE, 4000)) {
        return false;
    }
    w->battre_auto = true;
    monde_battre(w);
    monde_ordre(w, ORDRE_SORTIR, dixiemes, 0);
    return monde_attendre(w, 3, SPRAY_ETAT_BRAS_SORTI, SPRAY_ETAT_BRAS_SORTI, 4000);
}

int32_t monde_angle_reel(const monde_t *w) {
    return (int32_t)((int64_t)w->bras_reel * 3600 / w->r.bras_pas_par_tour);
}
