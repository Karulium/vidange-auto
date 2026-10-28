// Pilote du capteur LIS3DH (accéléromètre 3 axes de ST), par le bus I2C.
//
// Au démarrage : la puce est reconnue (WHO_AM_I), puis son autotest est fait (une force
// électrostatique interne doit faire bouger la mesure de chaque axe dans les limites de la
// fiche technique) : un capteur cassé ou décollé de sa carte ne passe pas.
// Ensuite : mesures en haute résolution (12 bits), lues d'un seul coup (pas de mélange
// entre deux mesures).
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "bus_i2c.h"

typedef enum {
    LIS3DH_BIEN = 0,
    LIS3DH_ABSENT,           // personne ne répond à cette adresse
    LIS3DH_MAUVAISE_PUCE,    // une puce répond, mais ce n'est pas un LIS3DH
    LIS3DH_AUTOTEST_RATE,    // l'autotest ne fait pas bouger la mesure comme il faut
    LIS3DH_ERREUR_BUS,       // le bus I2C a raté une lecture ou une écriture
    LIS3DH_REGLAGE_INCONNU,  // pleine échelle ou vitesse de mesure que la puce n'a pas
} lis3dh_resultat_t;

typedef struct {
    const bus_i2c_t *bus;
    uint8_t adresse;
    uint8_t mg_par_pas;  // en haute résolution
    // Ce que l'autotest a fait bouger chaque axe (pas de 4 mg), pour la console.
    int16_t autotest_ecart[3];
} lis3dh_t;

// Reconnaît la puce, fait l'autotest, puis la règle pour les mesures.
lis3dh_resultat_t lis3dh_demarrer(lis3dh_t *capteur, const bus_i2c_t *bus, uint8_t adresse,
                                  uint8_t pleine_echelle_g, uint16_t mesures_par_seconde);

// Lit la dernière mesure, en mg sur x, y, z. « nouvelle » : false si la puce n'a rien mesuré
// depuis la dernière lecture (rien n'est alors écrit dans « mg »). « debordement » : true si
// des mesures ont été perdues (lues trop tard).
lis3dh_resultat_t lis3dh_lire(lis3dh_t *capteur, int32_t mg[3], bool *nouvelle,
                              bool *debordement);

// Le texte d'un résultat, pour la console.
const char *lis3dh_texte(lis3dh_resultat_t resultat);
