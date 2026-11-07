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
    m->longueur = 0;
    modbus_oublier(m);
}

void modbus_oublier(modbus_t *m) {
    m->n = 0;
    m->reponse_attendue = false;
    m->perdu = false;
}

static bool ecriture(uint8_t fonction) {
    return fonction == 15 || fonction == 16;
}

// Longueur de la question en cours, d'après ses premiers octets ; 0 tant qu'on ne la sait pas.
static size_t longueur_question(const modbus_t *m) {
    if (m->n < 2) {
        return 0;
    }
    if (ecriture(m->trame[1])) {
        // Le 7e octet donne le nombre d'octets des valeurs.
        return m->n < 7 ? 0 : 9 + (size_t)m->trame[6];
    }
    return MODBUS_QUESTION;
}

// Longueur de la réponse d'une autre carte (au moins 3 octets reçus).
static size_t longueur_reponse(const modbus_t *m) {
    uint8_t fonction = m->trame[1];
    if (fonction & 0x80) {
        return 5;  // exception
    }
    if (fonction == 5 || fonction == 6 || ecriture(fonction)) {
        return 8;  // accusé d'une écriture
    }
    return 5 + (size_t)m->trame[2];  // lecture : nombre d'octets de données, données
}

bool modbus_recevoir(modbus_t *m, uint8_t octet, uint64_t t_us) {
    if (t_us - m->dernier_octet_us > MODBUS_SILENCE_US) {
        modbus_oublier(m);
    }
    m->dernier_octet_us = t_us;
    if (m->perdu) {
        return false;
    }
    if (m->n < MODBUS_TRAME_MAX) {
        m->trame[m->n] = octet;
    }
    m->n++;
    if (m->reponse_attendue) {
        if (m->n >= 3 && m->n >= longueur_reponse(m)) {
            modbus_oublier(m);
        }
        return false;
    }
    size_t longueur = longueur_question(m);
    if (longueur > MODBUS_TRAME_MAX) {
        m->perdu = true;
        return false;
    }
    if (longueur == 0 || m->n < longueur) {
        return false;
    }
    m->n = 0;
    m->longueur = longueur;
    bool pour_moi = m->trame[0] == m->adresse;
    uint16_t crc = (uint16_t)(m->trame[longueur - 2] | (m->trame[longueur - 1] << 8));
    if (modbus_crc(m->trame, longueur - 2) != crc) {
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

size_t modbus_exception(const modbus_t *m, uint8_t code, uint8_t *reponse) {
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
        return modbus_exception(m, MODBUS_FONCTION_INCONNUE, reponse);
    }
    size_t premier = (size_t)(m->trame[2] << 8 | m->trame[3]);
    size_t nombre = (size_t)(m->trame[4] << 8 | m->trame[5]);
    if (nombre == 0 || nombre > MODBUS_REGISTRES_MAX) {
        return modbus_exception(m, MODBUS_NOMBRE_FAUX, reponse);
    }
    if (premier + nombre > nb) {
        return modbus_exception(m, MODBUS_REGISTRE_INCONNU, reponse);
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

uint8_t modbus_fonction(const modbus_t *m) {
    return m->trame[1];
}

size_t modbus_lire_ecriture(const modbus_t *m, uint16_t *premier, uint16_t *valeurs,
                            size_t max) {
    if (m->trame[1] != 16 || m->longueur < 9) {
        return 0;
    }
    size_t nombre = (size_t)(m->trame[4] << 8 | m->trame[5]);
    size_t octets = m->trame[6];
    if (nombre == 0 || nombre > max || octets != 2 * nombre || m->longueur != 9 + octets) {
        return 0;
    }
    *premier = (uint16_t)(m->trame[2] << 8 | m->trame[3]);
    for (size_t i = 0; i < nombre; i++) {
        valeurs[i] = (uint16_t)(m->trame[7 + 2 * i] << 8 | m->trame[8 + 2 * i]);
    }
    return nombre;
}

size_t modbus_repondre_ecriture(const modbus_t *m, uint8_t code, uint8_t *reponse) {
    if (code) {
        return modbus_exception(m, code, reponse);
    }
    for (int i = 0; i < 6; i++) {
        reponse[i] = m->trame[i];
    }
    reponse[0] = m->adresse;
    ajouter_crc(reponse, 6);
    return 8;
}
