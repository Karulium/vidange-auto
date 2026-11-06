#include "trame.h"

#include "modbus.h"

#define CONTROLE 13

size_t trame_ecrire(const trame_t *t, uint8_t *octets) {
    uint32_t brut = (uint32_t)t->brut;
    uint8_t etat = (uint8_t)((t->hx711_muet ? TRAME_HX711_MUET : 0) |
                             (t->au_poste ? TRAME_AU_POSTE : 0) |
                             (t->recharge_presente ? TRAME_RECHARGE_PRESENTE : 0) |
                             (t->sur_usb ? TRAME_SUR_USB : 0) | (t->exemple ? TRAME_EXEMPLE : 0));
    octets[0] = 'P';
    octets[1] = 'F';
    octets[2] = TRAME_VERSION;
    octets[3] = (uint8_t)(t->numero & 0xFF);
    octets[4] = (uint8_t)(t->numero >> 8);
    for (int i = 0; i < 4; i++) {
        octets[5 + i] = (uint8_t)(brut >> (8 * i));
    }
    octets[9] = etat;
    octets[10] = (uint8_t)(t->accu_mv & 0xFF);
    octets[11] = (uint8_t)(t->accu_mv >> 8);
    octets[12] = t->accu_pct;
    uint16_t crc = modbus_crc(octets, CONTROLE);
    octets[13] = (uint8_t)(crc & 0xFF);
    octets[14] = (uint8_t)(crc >> 8);
    return TRAME_TAILLE;
}

bool trame_lire(const uint8_t *octets, size_t n, trame_t *t) {
    if (n != TRAME_TAILLE || octets[0] != 'P' || octets[1] != 'F' || octets[2] != TRAME_VERSION) {
        return false;
    }
    uint16_t crc = (uint16_t)(octets[13] | (octets[14] << 8));
    if (modbus_crc(octets, CONTROLE) != crc) {
        return false;
    }
    uint32_t brut = 0;
    for (int i = 0; i < 4; i++) {
        brut |= (uint32_t)octets[5 + i] << (8 * i);
    }
    uint8_t etat = octets[9];
    t->numero = (uint16_t)(octets[3] | (octets[4] << 8));
    t->brut = (int32_t)brut;
    t->hx711_muet = etat & TRAME_HX711_MUET;
    t->au_poste = etat & TRAME_AU_POSTE;
    t->recharge_presente = etat & TRAME_RECHARGE_PRESENTE;
    t->sur_usb = etat & TRAME_SUR_USB;
    t->exemple = etat & TRAME_EXEMPLE;
    t->accu_mv = (uint16_t)(octets[10] | (octets[11] << 8));
    t->accu_pct = octets[12];
    return true;
}
