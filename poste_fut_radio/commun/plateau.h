// Ce que fait la carte du plateau de pesée, sans le matériel (essayé sur PC avec un faux HX711) :
// la moyenne des dernières mesures du HX711, une trame toutes les periode_trame_ms, « HX711
// muet », et quand s'endormir (reed ouvert depuis sommeil_apres_ms).
//
// main.c (plateau/) lit le HX711, le reed, les 5 V et l'accu, et envoie la trame par radio.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "trame.h"

// Mesures gardées pour la moyenne, au plus (pesees.yaml : moyenne_de ≤ 16).
#define PLATEAU_MOYENNE_MAX 16

typedef struct {
    uint8_t moyenne_de;
    uint32_t periode_trame_ms;
    uint32_t sans_mesure_ms;
    uint32_t sommeil_apres_ms;
    bool exemple;
} reglages_plateau_t;

// Ce que main.c lit juste avant chaque trame.
typedef struct {
    bool au_poste;           // reed fermé
    bool recharge_presente;  // 5 V de la recharge sans contact présent (vrai aussi accu plein)
    bool sur_usb;            // 5 V de l'USB-C de secours présent
    uint16_t accu_mv;
    uint8_t accu_pct;
} entrees_plateau_t;

typedef struct {
    reglages_plateau_t r;
    int32_t dernieres[PLATEAU_MOYENNE_MAX];
    uint8_t nb;    // mesures gardées (moyenne_de au plus)
    uint8_t pos;   // où ranger la prochaine
    bool une_mesure;
    uint64_t debut_us;
    uint64_t derniere_mesure_us;
    uint64_t prochaine_trame_us;
    bool reed_ferme;
    uint64_t reed_ouvert_depuis_us;
    uint16_t numero;  // de la dernière trame envoyée
    uint16_t par_seconde;  // mesures du HX711 pendant la dernière seconde (fenêtre USB)
    uint16_t compte;
    uint64_t debut_seconde_us;
} plateau_t;

// Au démarrage ou au réveil, à l'heure t_us. `numero` : celui de la dernière trame avant le
// sommeil (gardé par main.c pendant le sommeil), pour que la boîte compte bien les trames perdues.
void plateau_init(plateau_t *p, const reglages_plateau_t *r, uint16_t numero, bool reed_ferme,
                  uint64_t t_us);

// Une mesure lue du HX711.
void plateau_noter_mesure(plateau_t *p, int32_t brut, uint64_t t_us);

// L'état du reed, lu souvent.
void plateau_noter_reed(plateau_t *p, bool ferme, uint64_t t_us);

bool plateau_hx711_muet(const plateau_t *p, uint64_t t_us);

// Vrai quand une trame doit partir maintenant : main.c lit alors ses entrées et appelle
// plateau_faire_trame. Juste après le réveil, la première trame attend la première mesure du
// HX711 (ou sans_mesure_ms : le HX711 est alors dit muet).
bool plateau_trame_due(plateau_t *p, uint64_t t_us);

// Remplit la trame (numéro suivant, moyenne des dernières mesures, état).
void plateau_faire_trame(plateau_t *p, const entrees_plateau_t *e, uint64_t t_us, trame_t *t);

// Vrai quand la carte doit s'endormir : reed ouvert depuis sommeil_apres_ms.
bool plateau_dormir(const plateau_t *p, uint64_t t_us);
