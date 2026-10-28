#include "fiche.h"

#include <string.h>

uint32_t fiche_crc32(uint32_t crc, const uint8_t *octets, size_t n) {
    crc = ~crc;
    for (size_t i = 0; i < n; i++) {
        crc ^= octets[i];
        for (int bit = 0; bit < 8; bit++) {
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
        }
    }
    return ~crc;
}

bool fiche_nom_valide(const char *nom) {
    size_t n = 0;
    for (; nom[n]; n++) {
        char c = nom[n];
        bool bon = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                   c == '.' || c == '_' || c == '+' || c == '-';
        if (!bon || n + 1 >= FICHE_NOM_MAX) {
            return false;
        }
    }
    return n > 0;
}

static void ecrire_32(uint8_t *octets, uint32_t valeur) {
    for (int i = 0; i < 4; i++) {
        octets[i] = (uint8_t)(valeur >> (8 * i));
    }
}

static uint32_t lire_32(const uint8_t *octets) {
    return (uint32_t)octets[0] | (uint32_t)octets[1] << 8 | (uint32_t)octets[2] << 16 |
           (uint32_t)octets[3] << 24;
}

void fiche_ecrire(const fiche_t *fiche, uint8_t octets[FICHE_TAILLE]) {
    memset(octets, 0, FICHE_TAILLE);
    ecrire_32(octets, FICHE_MAGIE);
    ecrire_32(octets + 4, FICHE_FORMAT);
    ecrire_32(octets + 8, fiche->adresse);
    ecrire_32(octets + 12, fiche->taille);
    ecrire_32(octets + 16, fiche->crc);
    size_t n = strnlen(fiche->nom, FICHE_NOM_MAX - 1);
    memcpy(octets + 20, fiche->nom, n);
    ecrire_32(octets + FICHE_TAILLE - 4, fiche_crc32(0, octets, FICHE_TAILLE - 4));
}

bool fiche_lire(const uint8_t octets[FICHE_TAILLE], fiche_t *fiche) {
    if (lire_32(octets) != FICHE_MAGIE || lire_32(octets + 4) != FICHE_FORMAT ||
        lire_32(octets + FICHE_TAILLE - 4) != fiche_crc32(0, octets, FICHE_TAILLE - 4)) {
        return false;
    }
    fiche->adresse = lire_32(octets + 8);
    fiche->taille = lire_32(octets + 12);
    fiche->crc = lire_32(octets + 16);
    memcpy(fiche->nom, octets + 20, FICHE_NOM_MAX);
    fiche->nom[FICHE_NOM_MAX - 1] = '\0';
    return fiche_nom_valide(fiche->nom);
}
