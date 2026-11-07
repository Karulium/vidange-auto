// Pilote de la PCA9685 (16 sorties PWM, I2C) pour les servos du plateau du remplissage.
// Aucun matériel ici (essayé sur PC avec un faux bus I2C). Tous les chiffres d'une voie (angle,
// largeur d'impulsion) viennent des réglages ; ici seulement la langue de la puce (fiche NXP).
//
// Au démarrage la puce est mise en veille, réglée à la fréquence demandée, TOUTES ses sorties sont
// coupées, puis réveillée : un servo ne reçoit d'impulsion qu'après un ordre du Pi.
#pragma once

#include "i2c_bus.h"

typedef struct {
    uint8_t adresse;
    uint32_t frequence_hz;  // des impulsions des servos (50 Hz en général)
    uint32_t horloge_hz;    // oscillateur interne de la puce (25 MHz)
} pca9685_config_t;

// Étapes du démarrage, une transaction I2C chacune : veille, fréquence, tout couper, réveil.
#define PCA9685_ETAPES_DEMARRAGE 4
#define PCA9685_CANAUX 16

// Valeur du registre PRESCALE pour la fréquence demandée.
uint8_t pca9685_prescale(const pca9685_config_t *c);

// Largeur d'impulsion (µs) → nombre de pas de 1/4096 de la période (au plus 4095).
uint16_t pca9685_pas(const pca9685_config_t *c, uint32_t impulsion_us);

// L'étape `etape` (de 0 à PCA9685_ETAPES_DEMARRAGE - 1) du démarrage.
bool pca9685_etape_demarrage(const i2c_bus_t *bus, const pca9685_config_t *c, unsigned etape);

// Une impulsion de `pas` pas sur un canal (0 à 15), ou la sortie coupée.
bool pca9685_regler(const i2c_bus_t *bus, const pca9685_config_t *c, unsigned canal,
                    uint16_t pas);
bool pca9685_couper(const i2c_bus_t *bus, const pca9685_config_t *c, unsigned canal);
