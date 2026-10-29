#include "modbus.h"

uint16_t modbus_crc(const uint8_t *octets, size_t n) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < n; i++) {
        crc ^= octets[i];
        for (int b = 0; b < 8; b++) {
            crc = (crc & 1) ? (uint16_t)((crc >> 1) ^ 0xA001) : (uint16_t)(crc >> 1);
        }
    }
    return crc;
}

static void ajouter_crc(uint8_t *trame, size_t n) {
    uint16_t crc = modbus_crc(trame, n);
    trame[n] = (uint8_t)(crc & 0xFF);
    trame[n + 1] = (uint8_t)(crc >> 8);
}

void modbus_init(modbus_t *m, uint8_t adresse) {
    m->adresse = adresse;
    m->dernier_octet_us = 0;
    m->trames_abimees = 0;
    modbus_oublier(m);
}

void modbus_oublier(modbus_t *m) {
    m->n = 0;
    m->reponse_attendue = false;
    m->perdu = false;
}

bool modbus_recevoir(modbus_t *m, uint8_t octet, uint64_t t_us) {
    if (t_us - m->dernier_octet_us > MODBUS_SILENCE_US) {
        modbus_oublier(m);
    }
    m->dernier_octet_us = t_us;
    if (m->perdu) {
        return false;
    }
    if (m->n < MODBUS_QUESTION) {
        m->trame[m->n] = octet;
    }
    m->n++;
    if (m->reponse_attendue) {
        // Réponse d'une autre carte : adresse, fonction, nombre d'octets de données, données,
        // contrôle ; ou exception (fonction + 0x80) : 5 octets.
        if (m->n >= 3) {
            size_t longueur = (m->trame[1] & 0x80) ? 5 : 5 + (size_t)m->trame[2];
            if (m->n >= longueur) {
                modbus_oublier(m);
            }
        }
        return false;
    }
    if (m->n < MODBUS_QUESTION) {
        return false;
    }
    m->n = 0;
    bool pour_moi = m->trame[0] == m->adresse;
    uint16_t crc = (uint16_t)(m->trame[6] | (m->trame[7] << 8));
    if (modbus_crc(m->trame, 6) != crc) {
        if (pour_moi) {
            m->trames_abimees++;
        }
        m->perdu = true;
        return false;
    }
    if (pour_moi) {
        return true;
    }
    // Personne ne répond à un message à tous (adresse 0).
    m->reponse_attendue = m->trame[0] != 0;
    return false;
}

static size_t exception(const modbus_t *m, uint8_t code, uint8_t *reponse) {
    reponse[0] = m->adresse;
    reponse[1] = (uint8_t)(m->trame[1] | 0x80);
    reponse[2] = code;
    ajouter_crc(reponse, 3);
    return 5;
}

size_t modbus_repondre(const modbus_t *m, const uint16_t *registres, size_t nb,
                       uint8_t *reponse) {
    uint8_t fonction = m->trame[1];
    if (fonction != 3 && fonction != 4) {
        return exception(m, MODBUS_FONCTION_INCONNUE, reponse);
    }
    size_t premier = (size_t)(m->trame[2] << 8 | m->trame[3]);
    size_t nombre = (size_t)(m->trame[4] << 8 | m->trame[5]);
    if (nombre == 0 || nombre > MODBUS_REGISTRES_MAX) {
        return exception(m, MODBUS_NOMBRE_FAUX, reponse);
    }
    if (premier + nombre > nb) {
        return exception(m, MODBUS_REGISTRE_INCONNU, reponse);
    }
    reponse[0] = m->adresse;
    reponse[1] = fonction;
    reponse[2] = (uint8_t)(2 * nombre);
    for (size_t i = 0; i < nombre; i++) {
        uint16_t valeur = registres[premier + i];
        reponse[3 + 2 * i] = (uint8_t)(valeur >> 8);
        reponse[4 + 2 * i] = (uint8_t)(valeur & 0xFF);
    }
    ajouter_crc(reponse, 3 + 2 * nombre);
    return 5 + 2 * nombre;
}
