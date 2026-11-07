// Un faux monde autour de la carte du spray, pour les essais sur PC : les 5 moteurs avancés par
// leur générateur de pas, un faux bras (qui peut être bloqué), un faux capteur « bras rangé »
// (qui peut être en panne), 4 faux flacons sur leurs fausses balances, et le Pi qui parle par
// Modbus (vraies trames, passées par modbus.c).
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "spray.h"

typedef struct {
    spray_reglages_t r;
    moteur_t bras;
    moteur_t pompes[SPRAY_NB_FLACONS];
    balance_t balances[SPRAY_NB_FLACONS];
    spray_t spray;
    modbus_t bus;
    uint64_t t_us;
    uint32_t periode_us;
    // Le faux bras : sa vraie position en pas (0 = au capteur), et ses pannes.
    int32_t bras_reel;
    int32_t zone_capteur_pas;  // le capteur voit le bras jusque-là
    bool bras_bloque;          // les pas ne le font plus bouger
    bool capteur_en_panne;
    bool pilote_ok;
    // Les faux flacons et leurs balances.
    double grammes[SPRAY_NB_FLACONS];
    double g_par_pas;  // débit des pompes
    bool tube_pince[SPRAY_NB_FLACONS];
    bool balance_debranchee[SPRAY_NB_FLACONS];
    double bruit_g[SPRAY_NB_FLACONS];  // mesures qui sautent de ± ça
    int32_t zero_brut;
    double brut_par_g;
    uint32_t periode_mesure_us;
    uint64_t prochaine_mesure_us;
    uint32_t mesures;
    // Le Pi.
    bool battre_auto;  // battre toutes les 250 ms, comme le Pi pendant un geste
    uint64_t prochain_battement_us;
    uint16_t battement;
    uint16_t numero;
    // Ce qui s'est passé (pour les essais).
    uint64_t buse_ms, chasse_ms, nettoyage_ms;
    uint32_t pas_pompes[SPRAY_NB_FLACONS];
    uint32_t pas_simultanes;  // deux pas de suite sans redescente : jamais
} monde_t;

void monde_init(monde_t *w);
// Le temps passe (ms).
void monde_avancer(monde_t *w, uint32_t ms);
// Avance jusqu'à ce que le registre `registre` vaille `valeur`, au plus `max_ms` ; rend vrai si
// atteint.
bool monde_attendre(monde_t *w, int registre, uint16_t masque, uint16_t valeur, uint32_t max_ms);
// Lit les 30 registres (fonction 4).
void monde_lire(monde_t *w, uint16_t *registres);
// Le Pi écrit un battement (registre 100).
void monde_battre(monde_t *w);
// Le Pi envoie un ordre (registres 101 à 104, numéro suivant). Rend le code d'exception (0 si
// accepté par le bus).
uint8_t monde_ordre(monde_t *w, uint16_t code, uint16_t p1, uint16_t p2);
// Envoie des octets ; rend la taille de la réponse (0 : pas de réponse).
size_t monde_question(monde_t *w, const uint8_t *trame, size_t n, uint8_t *reponse);
// Écrit une question de lecture (8 octets) ou d'écriture ; rend sa longueur.
size_t monde_trame_lecture(uint8_t *trame, uint8_t adresse, uint8_t fonction, uint16_t premier,
                           uint16_t nombre);
size_t monde_trame_ecriture(uint8_t *trame, uint8_t adresse, uint16_t premier,
                            const uint16_t *valeurs, uint16_t nombre);
// Le bras sorti : origine, battement, sortir à `dixiemes`, attendre.
bool monde_sortir(monde_t *w, uint16_t dixiemes);
// Angle vrai du bras en dixièmes de degré.
int32_t monde_angle_reel(const monde_t *w);
