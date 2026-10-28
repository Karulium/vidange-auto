#include "liaison_trame.h"

#include <stdio.h>
#include <string.h>

uint16_t liaison_crc(const char *texte, size_t n) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < n; i++) {
        crc ^= (uint16_t)((uint8_t)texte[i] << 8);
        for (int bit = 0; bit < 8; bit++) {
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

size_t liaison_trame(const char *texte, char *trame, size_t taille) {
    size_t n = strlen(texte);
    // Texte, « * », 4 chiffres, « \n », et le zéro de fin de chaîne.
    if (n + 7 > taille || n + 6 > LIAISON_TRAME_MAX) {
        return 0;
    }
    memcpy(trame, texte, n);
    snprintf(trame + n, taille - n, "*%04X\n", liaison_crc(texte, n));
    return n + 6;
}

static int chiffre_hexa(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

// Vérifie « texte*CRC » ; rend la longueur du texte, ou -1.
static int verifier_ligne(const char *ligne, size_t n) {
    if (n < 5 || ligne[n - 5] != '*') {
        return -1;
    }
    uint16_t lu = 0;
    for (size_t i = n - 4; i < n; i++) {
        int c = chiffre_hexa(ligne[i]);
        if (c < 0) {
            return -1;
        }
        lu = (uint16_t)(lu << 4 | (uint16_t)c);
    }
    size_t longueur = n - 5;
    return liaison_crc(ligne, longueur) == lu ? (int)longueur : -1;
}

bool liaison_recevoir(liaison_lecteur_t *l, uint8_t octet, char *question, size_t taille) {
    if (octet == '\r') {
        return false;
    }
    if (octet != '\n') {
        if (l->n + 1 < sizeof l->texte) {
            l->texte[l->n++] = (char)octet;
        } else {
            l->trop_longue = true;
        }
        return false;
    }
    size_t n = l->n;
    bool trop_longue = l->trop_longue;
    l->n = 0;
    l->trop_longue = false;
    if (n == 0) {
        return false;  // ligne vide (un parasite seul, par exemple)
    }
    int longueur = trop_longue ? -1 : verifier_ligne(l->texte, n);
    if (longueur < 0 || (size_t)longueur + 1 > taille) {
        l->refusees++;
        return false;
    }
    memcpy(question, l->texte, (size_t)longueur);
    question[longueur] = '\0';
    return true;
}
