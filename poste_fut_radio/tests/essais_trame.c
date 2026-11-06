// Essais de la trame radio du plateau : écrite puis relue, et les trames fausses refusées.
#include <string.h>

#include "essai.h"
#include "trame.h"

static trame_t exemple(void) {
    trame_t t = {.numero = 0xBEEF,
                 .brut = -1234567,
                 .hx711_muet = false,
                 .au_poste = true,
                 .recharge_presente = true,
                 .sur_usb = false,
                 .exemple = true,
                 .accu_mv = 3987,
                 .accu_pct = 82};
    return t;
}

static void aller_retour(void) {
    trame_t t = exemple(), lue;
    uint8_t octets[TRAME_TAILLE];
    VERIFIER(trame_ecrire(&t, octets) == TRAME_TAILLE);
    VERIFIER(octets[0] == 'P' && octets[1] == 'F' && octets[2] == TRAME_VERSION);
    VERIFIER(octets[9] == (TRAME_AU_POSTE | TRAME_RECHARGE_PRESENTE | TRAME_EXEMPLE));
    VERIFIER(trame_lire(octets, sizeof(octets), &lue));
    VERIFIER(lue.numero == 0xBEEF && lue.brut == -1234567);
    VERIFIER(!lue.hx711_muet && lue.au_poste && lue.recharge_presente && !lue.sur_usb);
    VERIFIER(lue.exemple && lue.accu_mv == 3987 && lue.accu_pct == 82);
    // Les extrêmes du HX711 (24 bits signés) et tous les bits d'état.
    t.brut = 8388607;
    t.hx711_muet = t.sur_usb = true;
    trame_ecrire(&t, octets);
    VERIFIER(trame_lire(octets, sizeof(octets), &lue) && lue.brut == 8388607);
    VERIFIER(lue.hx711_muet && lue.sur_usb);
    t.brut = -8388608;
    trame_ecrire(&t, octets);
    VERIFIER(trame_lire(octets, sizeof(octets), &lue) && lue.brut == -8388608);
}

static void trames_fausses_refusees(void) {
    trame_t t = exemple(), lue;
    uint8_t octets[TRAME_TAILLE + 1];
    trame_ecrire(&t, octets);
    // Mauvaise taille.
    VERIFIER(!trame_lire(octets, TRAME_TAILLE - 1, &lue));
    VERIFIER(!trame_lire(octets, TRAME_TAILLE + 1, &lue));
    // Un octet abîmé, n'importe où : le contrôle le voit.
    for (size_t i = 0; i < TRAME_TAILLE; i++) {
        uint8_t abime[TRAME_TAILLE];
        memcpy(abime, octets, TRAME_TAILLE);
        abime[i] ^= 0x04;
        VERIFIER(!trame_lire(abime, TRAME_TAILLE, &lue));
    }
    // Autre version de la trame (programme du plateau plus récent que celui de la boîte).
    uint8_t autre[TRAME_TAILLE];
    memcpy(autre, octets, TRAME_TAILLE);
    autre[2] = TRAME_VERSION + 1;
    VERIFIER(!trame_lire(autre, TRAME_TAILLE, &lue));
}

void essais_trame(void) {
    printf("Trame radio\n");
    LANCER(aller_retour);
    LANCER(trames_fausses_refusees);
}
