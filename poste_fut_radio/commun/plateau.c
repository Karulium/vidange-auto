#include "plateau.h"

void plateau_init(plateau_t *p, const reglages_plateau_t *r, uint16_t numero, bool reed_ferme,
                  uint64_t t_us) {
    p->r = *r;
    if (p->r.moyenne_de < 1) {
        p->r.moyenne_de = 1;
    }
    if (p->r.moyenne_de > PLATEAU_MOYENNE_MAX) {
        p->r.moyenne_de = PLATEAU_MOYENNE_MAX;
    }
    p->nb = 0;
    p->pos = 0;
    p->une_mesure = false;
    p->debut_us = t_us;
    p->derniere_mesure_us = t_us;
    p->prochaine_trame_us = t_us + (uint64_t)r->periode_trame_ms * 1000;
    p->reed_ferme = reed_ferme;
    p->reed_ouvert_depuis_us = t_us;
    p->numero = numero;
    p->par_seconde = 0;
    p->compte = 0;
    p->debut_seconde_us = t_us;
}

static void avancer_seconde(plateau_t *p, uint64_t t_us) {
    if (t_us - p->debut_seconde_us < 1000000) {
        return;
    }
    p->par_seconde = t_us - p->debut_seconde_us < 2000000 ? p->compte : 0;
    p->compte = 0;
    p->debut_seconde_us = t_us;
}

void plateau_noter_mesure(plateau_t *p, int32_t brut, uint64_t t_us) {
    // Après un HX711 muet, les vieilles mesures ne comptent plus dans la moyenne.
    if (plateau_hx711_muet(p, t_us)) {
        p->nb = 0;
        p->pos = 0;
    }
    avancer_seconde(p, t_us);
    p->dernieres[p->pos] = brut;
    p->pos = (uint8_t)((p->pos + 1) % p->r.moyenne_de);
    if (p->nb < p->r.moyenne_de) {
        p->nb++;
    }
    p->une_mesure = true;
    p->derniere_mesure_us = t_us;
    if (p->compte < UINT16_MAX) {
        p->compte++;
    }
}

void plateau_noter_reed(plateau_t *p, bool ferme, uint64_t t_us) {
    avancer_seconde(p, t_us);
    if (!ferme && p->reed_ferme) {
        p->reed_ouvert_depuis_us = t_us;
    }
    p->reed_ferme = ferme;
}

bool plateau_hx711_muet(const plateau_t *p, uint64_t t_us) {
    // Sans aucune mesure, on compte depuis le réveil.
    return t_us - p->derniere_mesure_us > (uint64_t)p->r.sans_mesure_ms * 1000;
}

bool plateau_trame_due(plateau_t *p, uint64_t t_us) {
    if (t_us < p->prochaine_trame_us) {
        return false;
    }
    uint64_t periode_us = (uint64_t)p->r.periode_trame_ms * 1000;
    // Pas de trame avant la première mesure, sauf si le HX711 est muet (la boîte doit le
    // savoir). Le créneau est sauté.
    bool pret = p->une_mesure || plateau_hx711_muet(p, t_us);
    // Sans dérive ; mais après un grand retard (programme bloqué), on repart d'ici.
    p->prochaine_trame_us += periode_us;
    if (p->prochaine_trame_us <= t_us) {
        p->prochaine_trame_us = t_us + periode_us;
    }
    return pret;
}

static int32_t moyenne(const plateau_t *p) {
    if (p->nb == 0) {
        return 0;
    }
    int64_t somme = 0;
    for (uint8_t i = 0; i < p->nb; i++) {
        somme += p->dernieres[i];
    }
    // Arrondi au plus proche, aussi pour les nombres négatifs.
    int64_t n = p->nb;
    int64_t m = somme >= 0 ? (somme + n / 2) / n : -((-somme + n / 2) / n);
    return (int32_t)m;
}

void plateau_faire_trame(plateau_t *p, const entrees_plateau_t *e, uint64_t t_us, trame_t *t) {
    bool muet = plateau_hx711_muet(p, t_us);
    p->numero++;
    t->numero = p->numero;
    t->brut = muet ? 0 : moyenne(p);
    t->hx711_muet = muet;
    t->au_poste = e->au_poste;
    t->recharge_presente = e->recharge_presente;
    t->sur_usb = e->sur_usb;
    t->exemple = p->r.exemple;
    t->accu_mv = e->accu_mv;
    t->accu_pct = e->accu_pct;
}

bool plateau_dormir(const plateau_t *p, uint64_t t_us) {
    uint64_t sommeil_us = (uint64_t)p->r.sommeil_apres_ms * 1000;
    return !p->reed_ferme && t_us - p->reed_ouvert_depuis_us >= sommeil_us;
}
