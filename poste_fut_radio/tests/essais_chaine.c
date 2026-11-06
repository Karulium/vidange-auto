// Toute la chaîne, sans matériel : faux HX711 → plateau → trame → fausse radio → boîte →
// question Modbus du Pi → réponse, décodée comme le fait le Pi (pi/vidange/materiel/carte_pesee.py).
#include <string.h>

#include "boite.h"
#include "essai.h"
#include "faux_hx711.h"
#include "modbus.h"
#include "plateau.h"

#define MS 1000ull
#define S 1000000ull
#define BOUCLE_US (5 * MS)
#define ADRESSE_BOITE 4

static const uint8_t adresse_plateau[6] = {0x02, 0x50, 0x46, 0x00, 0x00, 0x01};

static const reglages_plateau_t reglages = {
    .moyenne_de = 5,
    .periode_trame_ms = 500,
    .sans_mesure_ms = 500,
    .sommeil_apres_ms = 30000,
    .exemple = false,
};

typedef struct {
    // Le plateau (son horloge à lui) et la boîte (la sienne).
    faux_hx711_t hx711;
    plateau_t plateau;
    bool reed;
    bool endormi;
    boite_t boite;
    modbus_t bus;
    uint64_t t_us;
    bool radio_coupee;
    int perdre_une_sur;  // 0 : aucune perte
    int envoyees;
} chaine_t;

static void chaine_init(chaine_t *c, int32_t valeur) {
    memset(c, 0, sizeof(*c));
    c->t_us = 2 * S;
    c->reed = true;
    faux_hx711_init(&c->hx711, valeur, 100 * MS, c->t_us);
    plateau_init(&c->plateau, &reglages, 0, true, c->t_us);
    boite_init(&c->boite, 2000, false, adresse_plateau, 0);
    modbus_init(&c->bus, ADRESSE_BOITE);
}

static void tourner(chaine_t *c, uint64_t duree_us) {
    broches_hx711_t broches = faux_hx711_broches(&c->hx711);
    uint64_t fin = c->t_us + duree_us;
    while (c->t_us < fin) {
        c->t_us += BOUCLE_US;
        boite_avancer(&c->boite, c->t_us);
        if (c->endormi) {
            continue;
        }
        faux_hx711_avancer(&c->hx711, c->t_us);
        if (hx711_pret(&broches)) {
            plateau_noter_mesure(&c->plateau, hx711_lire(&broches), c->t_us);
        }
        plateau_noter_reed(&c->plateau, c->reed, c->t_us);
        if (plateau_trame_due(&c->plateau, c->t_us)) {
            entrees_plateau_t e = {.au_poste = c->reed,
                                   .recharge_presente = c->reed,
                                   .accu_mv = 3900,
                                   .accu_pct = 72};
            trame_t t;
            uint8_t octets[TRAME_TAILLE];
            plateau_faire_trame(&c->plateau, &e, c->t_us, &t);
            trame_ecrire(&t, octets);
            c->envoyees++;
            bool perdue = c->radio_coupee ||
                          (c->perdre_une_sur && c->envoyees % c->perdre_une_sur == 0);
            if (!perdue) {
                // La radio met environ 1 ms.
                boite_recevoir(&c->boite, adresse_plateau, octets, sizeof(octets), -61,
                               c->t_us + 1 * MS);
            }
        }
        if (plateau_dormir(&c->plateau, c->t_us)) {
            c->endormi = true;
        }
    }
}

// Le Pi lit les 13 registres (fonction 4) ; rend faux s'il n'y a pas de bonne réponse.
static bool question_du_pi(chaine_t *c, uint16_t *registres) {
    uint8_t q[8] = {ADRESSE_BOITE, 4, 0, 0, 0, BOITE_NB_REGISTRES};
    uint16_t crc = modbus_crc(q, 6);
    q[6] = (uint8_t)crc;
    q[7] = (uint8_t)(crc >> 8);
    bool complete = false;
    for (int i = 0; i < 8; i++) {
        complete = modbus_recevoir(&c->bus, q[i], c->t_us + (uint64_t)i * 86);
    }
    if (!complete) {
        return false;
    }
    uint16_t table[BOITE_NB_REGISTRES];
    uint8_t r[MODBUS_REPONSE_MAX];
    boite_registres(&c->boite, c->bus.trames_abimees, c->t_us + 1 * MS, table);
    size_t n = modbus_repondre(&c->bus, table, BOITE_NB_REGISTRES, r);
    modbus_oublier(&c->bus);
    crc = modbus_crc(r, n - 2);
    if (n != 5 + 2 * BOITE_NB_REGISTRES || r[0] != ADRESSE_BOITE || r[1] != 4 ||
        r[n - 2] != (uint8_t)crc || r[n - 1] != (uint8_t)(crc >> 8)) {
        return false;
    }
    for (int i = 0; i < BOITE_NB_REGISTRES; i++) {
        registres[i] = (uint16_t)(r[3 + 2 * i] << 8 | r[4 + 2 * i]);
    }
    return true;
}

static int32_t brut_lu(const uint16_t *r) {
    return (int32_t)((uint32_t)r[0] << 16 | r[1]);
}

static void plateau_pose_le_pi_lit_le_poids(void) {
    chaine_t c;
    chaine_init(&c, -654321);
    uint16_t r[BOITE_NB_REGISTRES];
    // Juste réveillé : rien encore (le HX711 met 400 ms environ).
    VERIFIER(question_du_pi(&c, r));
    VERIFIER(r[4] & BOITE_ETAT_RADIO_MUETTE);
    tourner(&c, 5 * S);
    VERIFIER(question_du_pi(&c, r));
    VERIFIER(r[7] == 0x5046);
    VERIFIER(brut_lu(r) == -654321);
    VERIFIER(r[4] == 0);
    VERIFIER(r[3] < 500);
    VERIFIER(r[5] == 2);
    VERIFIER(r[8] == (BOITE_PLATEAU_AU_POSTE | BOITE_PLATEAU_RECHARGE_PRESENTE));
    VERIFIER(r[9] == 3900 && r[10] == 72 && r[11] == 139 && r[12] == 0);
    // Le numéro monte de 2 par seconde.
    uint16_t avant = r[2];
    tourner(&c, 1 * S);
    VERIFIER(question_du_pi(&c, r));
    VERIFIER((uint16_t)(r[2] - avant) == 2);
}

static void radio_coupee_puis_revenue(void) {
    chaine_t c;
    chaine_init(&c, 1000);
    tourner(&c, 3 * S);
    c.radio_coupee = true;
    uint16_t r[BOITE_NB_REGISTRES];
    tourner(&c, 1500 * MS);
    VERIFIER(question_du_pi(&c, r));
    VERIFIER(!(r[4] & BOITE_ETAT_RADIO_MUETTE));
    tourner(&c, 1 * S);
    VERIFIER(question_du_pi(&c, r));
    VERIFIER(r[4] & BOITE_ETAT_RADIO_MUETTE);
    VERIFIER(r[3] > 2000);
    // La boîte répond toujours au Pi : « pesée absente », jamais un arrêt (côté Pi).
    c.radio_coupee = false;
    c.hx711.valeur = 2000;
    tourner(&c, 1 * S);
    VERIFIER(question_du_pi(&c, r));
    VERIFIER(!(r[4] & BOITE_ETAT_RADIO_MUETTE));
    VERIFIER(brut_lu(r) == 2000);
}

static void trames_perdues_comptees(void) {
    chaine_t c;
    chaine_init(&c, 5);
    c.perdre_une_sur = 4;
    tourner(&c, 10 * S + 600 * MS);
    uint16_t r[BOITE_NB_REGISTRES];
    VERIFIER(question_du_pi(&c, r));
    // 21 trames envoyées, 5 perdues (la 4e, la 8e... la 20e : vue perdue quand la 21e arrive).
    VERIFIER(c.envoyees == 21);
    VERIFIER(r[12] == 5);
    VERIFIER(r[2] == 16);
}

static void plateau_sorti_puis_endormi(void) {
    chaine_t c;
    chaine_init(&c, 5);
    tourner(&c, 2 * S);
    c.reed = false;
    tourner(&c, 10 * S);
    uint16_t r[BOITE_NB_REGISTRES];
    VERIFIER(question_du_pi(&c, r));
    VERIFIER(!(r[8] & BOITE_PLATEAU_AU_POSTE));
    VERIFIER(!(r[4] & BOITE_ETAT_RADIO_MUETTE));
    tourner(&c, 21 * S);
    VERIFIER(c.endormi);
    tourner(&c, 3 * S);
    VERIFIER(question_du_pi(&c, r));
    VERIFIER(r[4] & BOITE_ETAT_RADIO_MUETTE);
    // Au réveil (aimant du poste), le numéro du plateau continue : rien de perdu.
    uint16_t numero = c.plateau.numero;
    c.endormi = false;
    c.reed = true;
    faux_hx711_init(&c.hx711, 6, 100 * MS, c.t_us);
    c.hx711.prochaine_us = c.t_us + 400 * MS;
    plateau_init(&c.plateau, &reglages, numero, true, c.t_us);
    tourner(&c, 2 * S);
    VERIFIER(question_du_pi(&c, r));
    VERIFIER(!(r[4] & BOITE_ETAT_RADIO_MUETTE) && brut_lu(r) == 6);
    VERIFIER(r[12] == 0);
}

void essais_chaine(void) {
    printf("Chaîne complète\n");
    LANCER(plateau_pose_le_pi_lit_le_poids);
    LANCER(radio_coupee_puis_revenue);
    LANCER(trames_perdues_comptees);
    LANCER(plateau_sorti_puis_endormi);
}
