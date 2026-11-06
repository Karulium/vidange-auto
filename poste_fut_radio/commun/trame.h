// La trame radio ESP-NOW que le plateau envoie à la boîte du poste, 2 fois par seconde.
// Aucun matériel ici (essayé sur PC).
//
// 15 octets, les nombres le faible d'abord :
//
// | Octets | Contenu |
// |---|---|
// | 0 et 1 | « PF » : une trame du plateau du fût |
// | 2 | version de la trame (TRAME_VERSION) |
// | 3 et 4 | numéro de la trame (+1 à chaque trame, gardé pendant le sommeil du plateau) |
// | 5 à 8 | mesure brute du HX711 : moyenne des dernières mesures (signée, 32 bits) |
// | 9 | état : 1 = HX711 muet, 2 = reed fermé (au poste), 4 = 5 V de la recharge présent, |
// |   | 8 = sur l'USB-C de secours, 16 = programme fait avec des réglages d'exemple |
// | 10 et 11 | tension de l'accu, en mV |
// | 12 | niveau de l'accu, en % |
// | 13 et 14 | contrôle CRC-16 des octets 0 à 12 (le même calcul que Modbus) |
//
// « 5 V de la recharge présent » veut dire que le récepteur de la recharge sans contact donne
// son 5 V, pas « en charge » : il reste vrai quand l'accu est plein (docs/decisions.md, réponses
// à la PR n° 77).
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define TRAME_TAILLE 15
#define TRAME_VERSION 1

#define TRAME_HX711_MUET 1
#define TRAME_AU_POSTE 2
#define TRAME_RECHARGE_PRESENTE 4
#define TRAME_SUR_USB 8
#define TRAME_EXEMPLE 16

typedef struct {
    uint16_t numero;
    int32_t brut;
    bool hx711_muet;
    bool au_poste;           // reed fermé
    bool recharge_presente;  // 5 V de la recharge sans contact présent (vrai aussi accu plein)
    bool sur_usb;            // 5 V de l'USB-C de secours présent
    bool exemple;
    uint16_t accu_mv;
    uint8_t accu_pct;
} trame_t;

// Écrit la trame dans `octets` (TRAME_TAILLE octets) ; rend TRAME_TAILLE.
size_t trame_ecrire(const trame_t *t, uint8_t *octets);

// Lit une trame reçue ; faux si elle n'en est pas une (taille, « PF », version ou contrôle).
bool trame_lire(const uint8_t *octets, size_t n, trame_t *t);
