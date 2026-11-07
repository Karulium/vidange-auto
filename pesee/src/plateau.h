// Le boîtier du chariot sur la carte de pesée du plateau du remplissage : servos (PCA9685) et
// capteur de distance (VL6180X) sur l'I2C, et leurs registres Modbus en plus des registres 0 à 7.
// Aucun matériel ici (essayé sur PC avec un faux bus I2C).
//
// | Registre | Contenu | Lecture | Écriture |
// |---|---|---|---|
// | 8 | distance du ToF, en mm (65 535 = pas de bonne mesure) | oui | non |
// | 9 | état du ToF : 0 = bonne mesure, 1 à 15 = code d'erreur de la puce, 256 = pas encore de mesure, 512 = capteur muet | oui | non |
// | 10 | âge de la dernière mesure du ToF, en ms (65 535 au plus) | oui | non |
// | 11 | compteur de démarrages de la carte (change à chaque démarrage) | oui | non |
// | 12 | état de l'I2C (bits I2C_...) | oui | non |
// | 13 | transactions I2C sans réponse depuis le démarrage (repart à 0 après 65 535) | oui | non |
// | 14 | temps depuis le dernier ordre du Pi, en ms (65 535 au plus) | oui | non |
// | 15 | nombre de voies de servo de ce programme | oui | non |
// | 16 et suivants | angle de chaque voie, en dixièmes de degré (nombre signé ; 0x8000 = sortie coupée) | oui | oui |
//
// Les registres 0 à 7 sont ceux de toutes les cartes de pesée (mesures.h) et ne changent pas.
// Ecriture : fonction 6 ou 16. Un angle hors de la plage de sa voie refuse TOUTE l'écriture
// (exception 3). Toute écriture acceptée est un « ordre » : le Pi en renvoie au moins un
// régulièrement (même sans changer d'angle), c'est ce qui dit à la carte qu'il est là.
#pragma once

#include <stddef.h>

#include "i2c_bus.h"
#include "mesures.h"
#include "pca9685.h"
#include "vl6180x.h"

#define PLATEAU_VOIES_MAX 8

#define REGISTRE_TOF_MM 8
#define REGISTRE_TOF_ETAT 9
#define REGISTRE_TOF_AGE_MS 10
#define REGISTRE_DEMARRAGES 11
#define REGISTRE_I2C_ETAT 12
#define REGISTRE_I2C_ECHECS 13
#define REGISTRE_SILENCE_PI_MS 14
#define REGISTRE_NB_VOIES 15
#define REGISTRE_ANGLES 16
#define NB_REGISTRES_PLATEAU_MAX (REGISTRE_ANGLES + PLATEAU_VOIES_MAX)

// Registre 12.
#define I2C_PCA9685_MUETTE 1       // la PCA9685 ne répond pas
#define I2C_TOF_MUET 2             // le VL6180X ne répond pas
#define I2C_AUCUN_ORDRE 4          // aucun ordre du Pi depuis le démarrage : sorties coupées
#define I2C_PI_SILENCIEUX 8        // plus d'ordre depuis longtemps : angles gardés
#define I2C_PCA9685_DEMARRE_PAS 16  // la PCA9685 n'a pas fini son démarrage

// Angle « sortie coupée » (pas d'impulsion : le servo est libre).
#define ANGLE_COUPE ((int16_t)-32768)

typedef struct {
    uint8_t canal;               // de la PCA9685, de 0 à 15
    int16_t angle_min_dix;       // dixièmes de degré, à la plus petite impulsion
    int16_t angle_max_dix;
    uint16_t impulsion_min_us;   // largeur d'impulsion à angle_min
    uint16_t impulsion_max_us;   // à angle_max
} voie_config_t;

typedef struct {
    pca9685_config_t pca;
    uint32_t pca_reveil_us;  // attente après le réveil de la PCA9685
    vl6180x_config_t tof;
    uint32_t silence_pi_ms;  // sans ordre du Pi plus longtemps : angles gardés, signalé
    uint32_t reessai_ms;     // après une panne de la PCA9685, nouvel essai au bout de ce temps
    size_t nb_voies;
    voie_config_t voies[PLATEAU_VOIES_MAX];
} plateau_config_t;

typedef struct {
    plateau_config_t config;
    i2c_bus_t bus;
    uint16_t demarrages;
    int16_t angles[PLATEAU_VOIES_MAX];  // demandés par le Pi
    uint16_t a_ecrire;                  // voies dont la PCA9685 n'a pas encore l'angle
    bool pca_prete;
    bool pca_muette;
    unsigned etape_pca;
    uint64_t pca_libre_us;  // pas de transaction avec la PCA9685 avant cette heure
    bool un_ordre;
    uint64_t dernier_ordre_us;
    uint16_t echecs;
    vl6180x_t tof;
} plateau_t;

// Compteur de démarrages : +1 après un redémarrage de la carte (chien de garde, mémoire de
// démarrage encore bonne) ; après une mise sous tension, un nombre au hasard (pour que le Pi voie
// un changement même alors).
uint16_t plateau_demarrages_suivant(bool memoire_bonne, uint16_t ancien, uint16_t hasard);

void plateau_init(plateau_t *p, const plateau_config_t *config, const i2c_bus_t *bus,
                  uint16_t demarrages, uint64_t t_us);

// Au plus UNE transaction I2C, courte. À appeler quand la carte n'a rien de plus pressé.
void plateau_pas(plateau_t *p, uint64_t t_us);

// Nombre de registres de la table complète (0 à 15 + une voie par registre).
size_t plateau_nb_registres(const plateau_t *p);

// Remplit les registres 8 et suivants de la table (les registres 0 à 7 sont ceux des mesures).
void plateau_registres(const plateau_t *p, uint64_t t_us, uint16_t *registres);

// Écriture de registres (fonction 6 ou 16). Rend 0 si acceptée, sinon le code d'exception Modbus
// (rien n'est changé dans ce cas).
uint8_t plateau_ecrire(plateau_t *p, uint16_t premier, const uint16_t *valeurs, size_t n,
                       uint64_t t_us);

// Angle (dixièmes de degré) → pas de la PCA9685, par les réglages de la voie.
uint16_t plateau_pas_pour_angle(const plateau_t *p, size_t voie, int16_t angle_dix);
