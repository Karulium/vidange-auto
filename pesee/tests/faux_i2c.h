// Faux bus I2C pour les essais sur PC : une fausse PCA9685 et un faux VL6180X, avec le temps
// que prend chaque transaction (100 kHz : 9 bits par octet, adresse comprise).
#pragma once

#include "i2c_bus.h"

typedef struct {
    uint64_t horloge_us;        // avance de la durée de chaque transaction
    uint32_t octet_us;          // durée d'un octet sur le bus
    uint32_t blocage_us;        // durée d'une transaction avec un appareil absent (0 : refus immédiat)
    bool pca_presente;
    bool tof_present;
    uint8_t pca_adresse;
    uint8_t tof_adresse;
    uint8_t pca[256];
    uint8_t tof[0x400];
    uint8_t tof_distance;
    uint8_t tof_code;
    uint32_t tof_duree_us;      // temps d'une mesure
    uint64_t tof_lancee_us;
    bool tof_en_cours;
    // Compte et durées.
    unsigned transactions;
    unsigned ecritures_pca;     // écritures qui touchent un canal de sortie
    uint64_t plus_longue_us;
} faux_i2c_t;

void faux_i2c_init(faux_i2c_t *f);
i2c_bus_t faux_i2c_bus(faux_i2c_t *f);

// Registres d'un canal de la fausse PCA9685.
uint16_t faux_pca_fin(const faux_i2c_t *f, unsigned canal);   // LEDn_OFF (12 bits)
bool faux_pca_coupee(const faux_i2c_t *f, unsigned canal);    // bit « toujours éteinte »
bool faux_pca_allumee_pour_de_bon(const faux_i2c_t *f, unsigned canal);

// Réglages pour les essais (les mêmes sortes de valeurs que pesees.yaml, écrites ici pour que les
// essais ne dépendent pas de lui).
#include "plateau.h"
plateau_config_t config_essai(void);
