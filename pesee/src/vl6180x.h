// Pilote du VL6180X (capteur de distance à temps de vol, I2C) du boîtier du chariot.
// Aucun matériel ici (essayé sur PC avec un faux bus I2C). Une mesure à la fois, sans jamais
// attendre : vl6180x_pas fait AU PLUS UNE transaction I2C, courte, puis rend la main (la carte
// doit continuer à lire son HX711 80 fois par seconde).
#pragma once

#include "i2c_bus.h"

typedef struct {
    uint8_t adresse;
    uint32_t periode_ms;    // entre deux mesures
    uint32_t sondage_ms;    // entre deux « la mesure est-elle prête ? »
    uint32_t delai_max_ms;  // une mesure plus longue que ça : capteur muet
    uint32_t reessai_ms;    // après un échec, nouvel essai au bout de ce temps
} vl6180x_config_t;

// Valeurs du registre « état » (registre 9 de la carte).
#define TOF_ETAT_BONNE 0           // mesure valable (code 0 de la puce)
#define TOF_ETAT_PAS_ENCORE 0x100  // aucune mesure depuis le démarrage
#define TOF_ETAT_MUET 0x200        // le capteur ne répond pas (ou plus)

typedef enum {
    TOF_LIRE_REPOS,   // lire « sorti de reset ? »
    TOF_REGLAGES,     // écrire les réglages obligatoires de la puce, un par pas
    TOF_REPOS,        // attendre l'heure de la prochaine mesure
    TOF_ATTENTE,      // mesure lancée : est-elle prête ?
    TOF_LIRE_DIST,
    TOF_LIRE_CODE,
    TOF_EFFACER
} tof_phase_t;

typedef struct {
    vl6180x_config_t config;
    tof_phase_t phase;
    unsigned reglage;       // prochain réglage à écrire
    bool muet;              // la dernière transaction a échoué
    bool une_mesure;        // au moins une mesure faite
    uint8_t distance_mm;    // de la dernière mesure
    uint8_t code;           // code de la dernière mesure (0 = bonne)
    uint64_t heure_us;      // de la dernière mesure finie
    uint64_t prochain_us;   // pas de transaction avant cette heure
    uint64_t depart_us;     // heure du lancement de la mesure en cours
    uint32_t echecs;        // transactions sans réponse, depuis le démarrage
} vl6180x_t;

void vl6180x_init(vl6180x_t *t, const vl6180x_config_t *config, uint64_t t_us);

// Au plus une transaction I2C. Rend vrai si une transaction a eu lieu (réussie ou non).
bool vl6180x_pas(vl6180x_t *t, const i2c_bus_t *bus, uint64_t t_us);

// Registre 9 : l'état, et registre 8 : la distance (0xFFFF si pas de bonne mesure).
uint16_t vl6180x_etat(const vl6180x_t *t);
uint16_t vl6180x_distance(const vl6180x_t *t);
