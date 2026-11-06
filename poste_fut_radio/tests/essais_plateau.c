// Essais du plateau sans le matériel : faux HX711 à 10 mesures par seconde, reed, trames, sommeil.
#include "essai.h"
#include "faux_hx711.h"
#include "plateau.h"

#define MS 1000ull
#define S 1000000ull
// La boucle de main.c (plateau/) : toutes les 5 ms.
#define BOUCLE_US (5 * MS)

// Les réglages d'exemple de pesees.yaml.
static const reglages_plateau_t reglages = {
    .moyenne_de = 5,
    .periode_trame_ms = 500,
    .sans_mesure_ms = 500,
    .sommeil_apres_ms = 30000,
    .exemple = true,
};

static const entrees_plateau_t entrees = {
    .au_poste = true, .recharge_presente = true, .sur_usb = false, .accu_mv = 4000, .accu_pct = 83};

typedef struct {
    plateau_t plateau;
    faux_hx711_t hx711;
    uint64_t t_us;
    trame_t trames[200];
    uint64_t heures[200];
    int nb_trames;
    bool reed;
    bool endormi;
    uint64_t heure_sommeil_us;
} banc_t;

static void banc_init(banc_t *b, int32_t valeur, uint16_t numero) {
    b->t_us = 7 * S;  // l'horloge de la carte ne part pas de 0 au réveil
    b->nb_trames = 0;
    b->reed = true;
    b->endormi = false;
    faux_hx711_init(&b->hx711, valeur, 100 * MS, b->t_us);
    // Au réveil, le HX711 met environ 400 ms pour sa première mesure.
    b->hx711.prochaine_us = b->t_us + 400 * MS;
    plateau_init(&b->plateau, &reglages, numero, b->reed, b->t_us);
}

// Fait tourner la boucle de main.c pendant `duree_us`.
static void tourner(banc_t *b, uint64_t duree_us) {
    broches_hx711_t broches = faux_hx711_broches(&b->hx711);
    uint64_t fin = b->t_us + duree_us;
    while (b->t_us < fin && !b->endormi) {
        b->t_us += BOUCLE_US;
        faux_hx711_avancer(&b->hx711, b->t_us);
        if (hx711_pret(&broches)) {
            plateau_noter_mesure(&b->plateau, hx711_lire(&broches), b->t_us);
        }
        plateau_noter_reed(&b->plateau, b->reed, b->t_us);
        if (plateau_trame_due(&b->plateau, b->t_us)) {
            entrees_plateau_t e = entrees;
            e.au_poste = b->reed;
            if (b->nb_trames < 200) {
                plateau_faire_trame(&b->plateau, &e, b->t_us, &b->trames[b->nb_trames]);
                b->heures[b->nb_trames] = b->t_us;
                b->nb_trames++;
            }
        }
        if (plateau_dormir(&b->plateau, b->t_us)) {
            b->endormi = true;
            b->heure_sommeil_us = b->t_us;
        }
    }
}

static void dix_mesures_et_deux_trames_par_seconde(void) {
    banc_t b;
    banc_init(&b, 123456, 0);
    tourner(&b, 10 * S);
    VERIFIER(b.hx711.lues >= 95 && b.hx711.lues <= 97);
    VERIFIER(b.plateau.par_seconde == 10);
    // Une trame toutes les 0,5 s ; la première à 0,5 s (le HX711 a déjà mesuré à 0,4 s).
    VERIFIER(b.nb_trames == 20);
    for (int i = 1; i < b.nb_trames; i++) {
        VERIFIER(b.heures[i] - b.heures[i - 1] == 500 * MS);
        VERIFIER(b.trames[i].numero == b.trames[i - 1].numero + 1);
    }
    VERIFIER(b.trames[0].numero == 1);
    trame_t *t = &b.trames[5];
    VERIFIER(t->brut == 123456 && !t->hx711_muet);
    VERIFIER(t->au_poste && t->recharge_presente && !t->sur_usb && t->exemple);
    VERIFIER(t->accu_mv == 4000 && t->accu_pct == 83);
}

static void moyenne_des_5_dernieres(void) {
    banc_t b;
    banc_init(&b, 1000, 0);
    tourner(&b, 2 * S);
    // Le poids monte d'un coup : la trame suivante a la moyenne des 5 dernières mesures, toutes
    // nouvelles (10 par seconde, une trame toutes les 0,5 s).
    b.hx711.valeur = 2000;
    int avant = b.nb_trames;
    tourner(&b, 1 * S);
    VERIFIER(b.nb_trames == avant + 2);
    VERIFIER(b.trames[b.nb_trames - 1].brut == 2000);
    // Moyenne arrondie : directement dans le plateau.
    plateau_t p;
    plateau_init(&p, &reglages, 0, true, 0);
    const int32_t valeurs[] = {10, 11, 11, 11, 11, -7, -8, -8, -8, -8};
    for (int i = 0; i < 10; i++) {
        plateau_noter_mesure(&p, valeurs[i], (uint64_t)(i + 1) * 100 * MS);
    }
    trame_t t;
    plateau_faire_trame(&p, &entrees, 1000 * MS, &t);
    VERIFIER(t.brut == -8);  // les 5 dernières seulement : (-7 - 8 × 4) / 5 = -7,8 → -8
    plateau_t q;
    plateau_init(&q, &reglages, 0, true, 0);
    plateau_noter_mesure(&q, 3, 100 * MS);
    plateau_noter_mesure(&q, 4, 200 * MS);
    plateau_faire_trame(&q, &entrees, 250 * MS, &t);
    VERIFIER(t.brut == 4);  // 2 mesures seulement (au réveil) : 3,5 → 4
}

static void hx711_debranche_puis_rebranche(void) {
    banc_t b;
    banc_init(&b, 5000, 0);
    tourner(&b, 2 * S);
    VERIFIER(!b.trames[b.nb_trames - 1].hx711_muet);
    b.hx711.debranche = true;
    b.hx711.pret = false;
    tourner(&b, 2 * S);
    // Plus de 500 ms sans mesure : les trames continuent et disent « HX711 muet », sans mesure.
    trame_t *t = &b.trames[b.nb_trames - 1];
    VERIFIER(t->hx711_muet && t->brut == 0);
    // Rebranché, avec un autre poids : la moyenne oublie les mesures d'avant la coupure.
    b.hx711.debranche = false;
    b.hx711.valeur = 9000;
    tourner(&b, 800 * MS);
    t = &b.trames[b.nb_trames - 1];
    VERIFIER(!t->hx711_muet && t->brut == 9000);
}

static void reveil_sans_hx711(void) {
    // HX711 absent dès le réveil : pas de trame avant 500 ms, puis des trames « HX711 muet »
    // (la boîte doit savoir que le plateau est là, mais sans pesée).
    banc_t b;
    banc_init(&b, 0, 0);
    b.hx711.debranche = true;
    tourner(&b, 500 * MS);
    VERIFIER(b.nb_trames == 0);
    tourner(&b, 1 * S);
    VERIFIER(b.nb_trames == 2);
    VERIFIER(b.trames[0].hx711_muet && b.trames[1].hx711_muet);
}

static void numero_continue_apres_le_sommeil(void) {
    banc_t b;
    banc_init(&b, 1, 4242);
    tourner(&b, 1 * S);
    VERIFIER(b.nb_trames == 2 && b.trames[0].numero == 4243 && b.trames[1].numero == 4244);
    VERIFIER(b.plateau.numero == 4244);
    // Il repart à 0 après 65 535.
    banc_init(&b, 1, 65535);
    tourner(&b, 1 * S);
    VERIFIER(b.trames[0].numero == 0 && b.trames[1].numero == 1);
}

static void sommeil_30_s_apres_l_ouverture_du_reed(void) {
    banc_t b;
    banc_init(&b, 1, 0);
    tourner(&b, 60 * S);
    VERIFIER(!b.endormi);  // reed fermé : jamais de sommeil
    b.reed = false;
    uint64_t ouverture = b.t_us + BOUCLE_US;
    tourner(&b, 20 * S);
    VERIFIER(!b.endormi);
    // Le reed se referme (plateau repoussé) : le compte repart de zéro à la prochaine ouverture.
    b.reed = true;
    tourner(&b, 1 * S);
    b.reed = false;
    ouverture = b.t_us + BOUCLE_US;
    tourner(&b, 29 * S);
    VERIFIER(!b.endormi);
    // Les trames continuent pendant ces 30 s, et disent « reed ouvert ».
    VERIFIER(!b.trames[b.nb_trames - 1].au_poste);
    tourner(&b, 2 * S);
    VERIFIER(b.endormi);
    VERIFIER(b.heure_sommeil_us - ouverture >= 30 * S);
    VERIFIER(b.heure_sommeil_us - ouverture < 30 * S + 2 * BOUCLE_US);
}

static void allume_reed_ouvert(void) {
    // Mise sous tension loin du poste (accu changé, USB-C) : 30 s éveillé, puis sommeil.
    plateau_t p;
    plateau_init(&p, &reglages, 0, false, 5 * S);
    VERIFIER(!plateau_dormir(&p, 34 * S));
    VERIFIER(plateau_dormir(&p, 35 * S));
}

static void pas_de_rafale_apres_un_retard(void) {
    // Programme bloqué 3 s (radio lente...) : une seule trame en retard, pas 6 d'un coup.
    plateau_t p;
    plateau_init(&p, &reglages, 0, true, 0);
    plateau_noter_mesure(&p, 1, 100 * MS);
    VERIFIER(plateau_trame_due(&p, 500 * MS));
    VERIFIER(!plateau_trame_due(&p, 600 * MS));
    VERIFIER(plateau_trame_due(&p, 3600 * MS));
    VERIFIER(!plateau_trame_due(&p, 3700 * MS));
    VERIFIER(plateau_trame_due(&p, 4100 * MS));
}

void essais_plateau(void) {
    printf("Plateau\n");
    LANCER(dix_mesures_et_deux_trames_par_seconde);
    LANCER(moyenne_des_5_dernieres);
    LANCER(hx711_debranche_puis_rebranche);
    LANCER(reveil_sans_hx711);
    LANCER(numero_continue_apres_le_sommeil);
    LANCER(sommeil_30_s_apres_l_ouverture_du_reed);
    LANCER(allume_reed_ouvert);
    LANCER(pas_de_rafale_apres_un_retard);
}
