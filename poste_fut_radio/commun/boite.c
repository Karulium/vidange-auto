#include "boite.h"

#include <string.h>

void boite_init(boite_t *b, uint32_t radio_muette_ms, bool exemple,
                const uint8_t adresse_plateau[6], uint64_t t_us) {
    memset(b, 0, sizeof(*b));
    b->radio_muette_ms = radio_muette_ms;
    b->exemple = exemple;
    memcpy(b->adresse_plateau, adresse_plateau, 6);
    b->heure_us = t_us;
    b->debut_seconde_us = t_us;
}

void boite_avancer(boite_t *b, uint64_t t_us) {
    if (t_us - b->debut_seconde_us < 1000000) {
        return;
    }
    // Plus d'une seconde sans appel : la seconde passée est quand même comptée seule.
    b->par_seconde = t_us - b->debut_seconde_us < 2000000 ? b->compte : 0;
    b->compte = 0;
    b->debut_seconde_us = t_us;
}

boite_reception_t boite_recevoir(boite_t *b, const uint8_t adresse[6], const uint8_t *octets,
                                 size_t n, int8_t signal_dbm, uint64_t t_us) {
    if (memcmp(adresse, b->adresse_plateau, 6) != 0) {
        b->autre_adresse++;
        memcpy(b->derniere_autre_adresse, adresse, 6);
        return BOITE_TRAME_AUTRE_ADRESSE;
    }
    trame_t t;
    if (!trame_lire(octets, n, &t)) {
        b->abimees++;
        return BOITE_TRAME_ABIMEE;
    }
    boite_avancer(b, t_us);
    if (b->une_trame) {
        uint16_t ecart = (uint16_t)(t.numero - b->derniere.numero);
        if (ecart == 0) {
            return BOITE_TRAME_EN_DOUBLE;
        }
        // Numéros sautés entre deux trames proches (moins de radio_muette_ms d'écart). Après un
        // long silence, ou si le numéro recule (plateau rallumé), rien n'est compté : la radio
        // muette le dit déjà.
        bool proche = t_us - b->heure_us <= (uint64_t)b->radio_muette_ms * 1000;
        if (proche && ecart < 0x8000) {
            b->perdues = (uint16_t)(b->perdues + ecart - 1);
        }
    }
    b->une_trame = true;
    b->derniere = t;
    b->signal_dbm = signal_dbm;
    b->heure_us = t_us;
    b->numero++;
    if (b->compte < UINT16_MAX) {
        b->compte++;
    }
    return BOITE_TRAME_PRISE;
}

bool boite_radio_muette(const boite_t *b, uint64_t t_us) {
    return !b->une_trame || t_us - b->heure_us > (uint64_t)b->radio_muette_ms * 1000;
}

void boite_registres(const boite_t *b, uint16_t questions_abimees, uint64_t t_us,
                     uint16_t *registres) {
    const trame_t *t = &b->derniere;
    uint32_t brut = (uint32_t)t->brut;
    uint64_t age_ms = b->une_trame ? (t_us - b->heure_us) / 1000 : UINT16_MAX;
    uint16_t etat = 0;
    if (b->une_trame && t->hx711_muet) {
        etat |= BOITE_ETAT_HX711_MUET;
    }
    if (b->exemple || (b->une_trame && t->exemple)) {
        etat |= BOITE_ETAT_EXEMPLE;
    }
    if (boite_radio_muette(b, t_us)) {
        etat |= BOITE_ETAT_RADIO_MUETTE;
    }
    uint16_t plateau = 0;
    if (b->une_trame) {
        plateau = (uint16_t)((t->au_poste ? BOITE_PLATEAU_AU_POSTE : 0) |
                             (t->recharge_presente ? BOITE_PLATEAU_RECHARGE_PRESENTE : 0) |
                             (t->sur_usb ? BOITE_PLATEAU_SUR_USB : 0));
    }
    int signal = b->une_trame ? b->signal_dbm + BOITE_DECALAGE_SIGNAL_DBM : 0;
    registres[0] = (uint16_t)(brut >> 16);
    registres[1] = (uint16_t)(brut & 0xFFFF);
    registres[2] = b->numero;
    registres[3] = age_ms > UINT16_MAX ? UINT16_MAX : (uint16_t)age_ms;
    registres[BOITE_REGISTRE_ETAT] = etat;
    registres[5] = b->par_seconde;
    registres[6] = questions_abimees;
    registres[7] = BOITE_SIGNATURE;
    registres[BOITE_REGISTRE_PLATEAU] = plateau;
    registres[9] = b->une_trame ? t->accu_mv : 0;
    registres[10] = b->une_trame ? t->accu_pct : 0;
    registres[11] = (uint16_t)(signal < 0 ? 0 : signal);
    registres[12] = b->perdues;
}

uint64_t boite_heure_octet(uint64_t t_lecture_us, size_t n, size_t i, uint32_t bauds,
                           uint64_t *precedent_us) {
    // 10 bits par octet (8N1).
    uint64_t octet_us = bauds ? 10000000ull / bauds : 0;
    uint64_t recul = (uint64_t)(n - 1 - i) * octet_us;
    uint64_t t = recul > t_lecture_us ? 0 : t_lecture_us - recul;
    if (t < *precedent_us) {
        t = *precedent_us;
    }
    *precedent_us = t;
    return t;
}
