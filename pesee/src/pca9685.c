#include "pca9685.h"

// Registres de la puce.
#define MODE1 0x00
#define LED0_ON_L 0x06
#define ALL_LED_OFF_H 0xFD
#define PRESCALE 0xFE
// MODE1 : bit 4 = veille, bit 5 = adresse qui s'incrémente toute seule.
#define MODE1_VEILLE 0x10
#define MODE1_INCREMENT 0x20
// Bit 4 de LEDn_OFF_H : sortie coupée pour de bon.
#define SORTIE_COUPEE 0x10

uint8_t pca9685_prescale(const pca9685_config_t *c) {
    // prescale = arrondi(horloge / (4096 × fréquence)) − 1
    uint64_t diviseur = 4096ull * c->frequence_hz;
    uint64_t valeur = (c->horloge_hz + diviseur / 2) / diviseur;
    valeur = valeur == 0 ? 0 : valeur - 1;
    return (uint8_t)(valeur > 255 ? 255 : valeur);
}

uint16_t pca9685_pas(const pca9685_config_t *c, uint32_t impulsion_us) {
    // Un pas dure (prescale + 1) / horloge secondes : on part de la vraie valeur du registre.
    uint64_t diviseur = 1000000ull * ((uint64_t)pca9685_prescale(c) + 1);
    uint64_t pas = ((uint64_t)impulsion_us * c->horloge_hz + diviseur / 2) / diviseur;
    return (uint16_t)(pas > 4095 ? 4095 : pas);
}

bool pca9685_etape_demarrage(const i2c_bus_t *bus, const pca9685_config_t *c, unsigned etape) {
    uint8_t octets[2];
    switch (etape) {
    case 0:
        octets[0] = MODE1;
        octets[1] = MODE1_VEILLE | MODE1_INCREMENT;
        break;
    case 1:
        octets[0] = PRESCALE;
        octets[1] = pca9685_prescale(c);
        break;
    case 2:
        octets[0] = ALL_LED_OFF_H;
        octets[1] = SORTIE_COUPEE;
        break;
    default:
        octets[0] = MODE1;
        octets[1] = MODE1_INCREMENT;
        break;
    }
    return bus->ecrire(bus->contexte, c->adresse, octets, 2);
}

bool pca9685_regler(const i2c_bus_t *bus, const pca9685_config_t *c, unsigned canal,
                    uint16_t pas) {
    uint8_t octets[5] = {(uint8_t)(LED0_ON_L + 4 * canal), 0, 0, (uint8_t)(pas & 0xFF),
                         (uint8_t)((pas >> 8) & 0x0F)};
    return bus->ecrire(bus->contexte, c->adresse, octets, 5);
}

bool pca9685_couper(const i2c_bus_t *bus, const pca9685_config_t *c, unsigned canal) {
    uint8_t octets[5] = {(uint8_t)(LED0_ON_L + 4 * canal), 0, 0, 0, SORTIE_COUPEE};
    return bus->ecrire(bus->contexte, c->adresse, octets, 5);
}
