#include "lis3dh.h"

#include <stdlib.h>

// Registres et bits (fiche technique LIS3DH, DocID17530).
#define REG_WHO_AM_I 0x0F
#define REG_TEMP_CFG 0x1F
#define REG_CTRL1 0x20
#define REG_CTRL2 0x21
#define REG_CTRL3 0x22
#define REG_CTRL4 0x23
#define REG_CTRL5 0x24
#define REG_STATUS 0x27
#define LIRE_SUITE 0x80  // bit d'adresse : lire plusieurs registres à la suite
#define REPONSE_WHO_AM_I 0x33
#define CTRL1_XYZ 0x07       // les 3 axes en marche
#define CTRL4_BDU 0x80       // les octets d'une mesure ne changent pas pendant la lecture
#define CTRL4_HR 0x08        // haute résolution (12 bits)
#define CTRL4_AUTOTEST 0x02  // autotest « 0 »
#define CTRL5_BOOT 0x80      // recharger les réglages d'usine de la puce
#define STATUS_NOUVELLE 0x08
#define STATUS_DEBORDEMENT 0x80

// Autotest (note d'application AN3308 de ST) : en mode normal (10 bits), ±2 g, 50 mesures/s,
// l'écart de chaque axe doit être entre 17 et 360 pas (fiche technique, tableau 4).
#define AUTOTEST_ODR 0x40  // 50 mesures par seconde
#define AUTOTEST_ATTENTE_MS 90
#define AUTOTEST_MESURES 5
#define AUTOTEST_ECART_MIN 17
#define AUTOTEST_ECART_MAX 360
// Une mesure arrive toutes les 20 ms à 50 mesures/s : au-delà de 100 ms, la puce est muette.
#define ATTENTE_MESURE_MAX_MS 100

static int ecrire_registre(lis3dh_t *c, uint8_t registre, uint8_t valeur) {
    uint8_t octets[2] = {registre, valeur};
    return c->bus->ecrire(c->bus->contexte, c->adresse, octets, 2);
}

static void attendre(lis3dh_t *c, uint32_t ms) { c->bus->attendre_ms(c->bus->contexte, ms); }

static int16_t mot(const uint8_t *octets) {
    return (int16_t)((uint16_t)octets[0] | ((uint16_t)octets[1] << 8));
}

// Code de vitesse de mesure (CTRL_REG1, bits 7 à 4), 0 si inconnue.
static uint8_t code_vitesse(uint16_t mesures_par_seconde) {
    switch (mesures_par_seconde) {
        case 1: return 1;
        case 10: return 2;
        case 25: return 3;
        case 50: return 4;
        case 100: return 5;
        case 200: return 6;
        case 400: return 7;
        case 1344: return 9;
        default: return 0;
    }
}

// Moyenne de quelques mesures brutes en mode normal (10 bits), après en avoir jeté une.
static lis3dh_resultat_t moyenne_autotest(lis3dh_t *c, int32_t moyenne[3]) {
    int32_t somme[3] = {0, 0, 0};
    for (int n = -1; n < AUTOTEST_MESURES; n++) {
        uint8_t octets[7];
        int attente = 0;
        for (;;) {
            if (c->bus->lire(c->bus->contexte, c->adresse, REG_STATUS | LIRE_SUITE, octets, 7)) {
                return LIS3DH_ERREUR_BUS;
            }
            if (octets[0] & STATUS_NOUVELLE) {
                break;
            }
            if (++attente > ATTENTE_MESURE_MAX_MS) {
                return LIS3DH_AUTOTEST_RATE;
            }
            attendre(c, 1);
        }
        if (n < 0) {
            continue;  // la première mesure après un changement n'est pas sûre
        }
        for (int axe = 0; axe < 3; axe++) {
            somme[axe] += mot(&octets[1 + 2 * axe]) >> 6;
        }
    }
    for (int axe = 0; axe < 3; axe++) {
        moyenne[axe] = somme[axe] / AUTOTEST_MESURES;
    }
    return LIS3DH_BIEN;
}

static lis3dh_resultat_t autotest(lis3dh_t *c) {
    int32_t sans[3];
    int32_t avec[3];
    lis3dh_resultat_t resultat;
    if (ecrire_registre(c, REG_CTRL4, CTRL4_BDU) ||
        ecrire_registre(c, REG_CTRL1, AUTOTEST_ODR | CTRL1_XYZ)) {
        return LIS3DH_ERREUR_BUS;
    }
    attendre(c, AUTOTEST_ATTENTE_MS);
    if ((resultat = moyenne_autotest(c, sans)) != LIS3DH_BIEN) {
        return resultat;
    }
    if (ecrire_registre(c, REG_CTRL4, CTRL4_BDU | CTRL4_AUTOTEST)) {
        return LIS3DH_ERREUR_BUS;
    }
    attendre(c, AUTOTEST_ATTENTE_MS);
    resultat = moyenne_autotest(c, avec);
    if (ecrire_registre(c, REG_CTRL4, CTRL4_BDU)) {
        return LIS3DH_ERREUR_BUS;
    }
    if (resultat != LIS3DH_BIEN) {
        return resultat;
    }
    bool bon = true;
    for (int axe = 0; axe < 3; axe++) {
        int32_t ecart = labs(avec[axe] - sans[axe]);
        c->autotest_ecart[axe] = (int16_t)ecart;
        if (ecart < AUTOTEST_ECART_MIN || ecart > AUTOTEST_ECART_MAX) {
            bon = false;
        }
    }
    return bon ? LIS3DH_BIEN : LIS3DH_AUTOTEST_RATE;
}

lis3dh_resultat_t lis3dh_demarrer(lis3dh_t *c, const bus_i2c_t *bus, uint8_t adresse,
                                  uint8_t pleine_echelle_g, uint16_t mesures_par_seconde) {
    c->bus = bus;
    c->adresse = adresse;
    for (int axe = 0; axe < 3; axe++) {
        c->autotest_ecart[axe] = 0;
    }
    uint8_t code_echelle;
    switch (pleine_echelle_g) {
        case 2: code_echelle = 0; c->mg_par_pas = 1; break;
        case 4: code_echelle = 1; c->mg_par_pas = 2; break;
        case 8: code_echelle = 2; c->mg_par_pas = 4; break;
        case 16: code_echelle = 3; c->mg_par_pas = 12; break;
        default: return LIS3DH_REGLAGE_INCONNU;
    }
    uint8_t vitesse = code_vitesse(mesures_par_seconde);
    if (vitesse == 0) {
        return LIS3DH_REGLAGE_INCONNU;
    }

    uint8_t qui = 0;
    if (bus->lire(bus->contexte, adresse, REG_WHO_AM_I, &qui, 1)) {
        return LIS3DH_ABSENT;
    }
    if (qui != REPONSE_WHO_AM_I) {
        return LIS3DH_MAUVAISE_PUCE;
    }
    // Repartir des réglages d'usine, quoi qu'ait laissé un démarrage précédent.
    if (ecrire_registre(c, REG_CTRL5, CTRL5_BOOT)) {
        return LIS3DH_ERREUR_BUS;
    }
    attendre(c, 10);
    if (ecrire_registre(c, REG_CTRL1, 0) || ecrire_registre(c, REG_CTRL2, 0) ||
        ecrire_registre(c, REG_CTRL3, 0) || ecrire_registre(c, REG_CTRL5, 0) ||
        ecrire_registre(c, REG_TEMP_CFG, 0)) {
        return LIS3DH_ERREUR_BUS;
    }
    lis3dh_resultat_t resultat = autotest(c);
    if (resultat != LIS3DH_BIEN) {
        return resultat;
    }
    if (ecrire_registre(c, REG_CTRL4, CTRL4_BDU | CTRL4_HR | (uint8_t)(code_echelle << 4)) ||
        ecrire_registre(c, REG_CTRL1, (uint8_t)(vitesse << 4) | CTRL1_XYZ)) {
        return LIS3DH_ERREUR_BUS;
    }
    // Vider la mesure en cours, faite avec les anciens réglages.
    uint8_t octets[7];
    attendre(c, 1000u / mesures_par_seconde + 2);
    if (bus->lire(bus->contexte, adresse, REG_STATUS | LIRE_SUITE, octets, 7)) {
        return LIS3DH_ERREUR_BUS;
    }
    return LIS3DH_BIEN;
}

lis3dh_resultat_t lis3dh_lire(lis3dh_t *c, int32_t mg[3], bool *nouvelle, bool *debordement) {
    uint8_t octets[7];
    *nouvelle = false;
    *debordement = false;
    if (c->bus->lire(c->bus->contexte, c->adresse, REG_STATUS | LIRE_SUITE, octets, 7)) {
        return LIS3DH_ERREUR_BUS;
    }
    if (!(octets[0] & STATUS_NOUVELLE)) {
        return LIS3DH_BIEN;
    }
    *nouvelle = true;
    *debordement = (octets[0] & STATUS_DEBORDEMENT) != 0;
    for (int axe = 0; axe < 3; axe++) {
        mg[axe] = (int32_t)(mot(&octets[1 + 2 * axe]) >> 4) * c->mg_par_pas;
    }
    return LIS3DH_BIEN;
}

const char *lis3dh_texte(lis3dh_resultat_t resultat) {
    switch (resultat) {
        case LIS3DH_BIEN: return "bien";
        case LIS3DH_ABSENT: return "capteur absent (ne répond pas)";
        case LIS3DH_MAUVAISE_PUCE: return "ce n'est pas un LIS3DH";
        case LIS3DH_AUTOTEST_RATE: return "autotest raté";
        case LIS3DH_ERREUR_BUS: return "erreur du bus I2C";
        case LIS3DH_REGLAGE_INCONNU: return "réglage inconnu";
    }
    return "?";
}
