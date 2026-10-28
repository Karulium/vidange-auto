// Les trames du fil série unique vers le Pi, communes au programme (liaison.h) et au
// chargeur (chargeur_protocole.h).
//
// Une trame = une ligne de texte, avec à la fin un « * », le contrôle CRC-16 du texte
// (4 chiffres hexadécimaux) et un retour à la ligne : « ETAT*F09B\n ».
// Une ligne au contrôle faux (fil abîmé, parasite) est oubliée sans réponse : le Pi redemande.
//
// Ce fichier ne touche à aucun matériel : il est essayé sur PC.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Plus longue trame (texte, contrôle et fin de ligne compris) : celles du chargeur, qui portent
// une page de 256 octets du programme écrite en hexadécimal. Celles du programme sont plus
// courtes (LIAISON_LIGNE_MAX).
#define LIAISON_TRAME_MAX 560

// Contrôle CRC-16 (CCITT : polynôme 0x1021, départ 0xFFFF) du texte.
uint16_t liaison_crc(const char *texte, size_t n);

// Écrit la trame du texte (texte, « * », contrôle, « \n »). Rend sa longueur (0 : trop longue).
size_t liaison_trame(const char *texte, char *trame, size_t taille);

// Assemble les octets reçus en lignes.
typedef struct {
    char texte[LIAISON_TRAME_MAX];
    size_t n;
    bool trop_longue;
    uint32_t refusees;  // lignes oubliées (CRC faux, mal formées, trop longues)
} liaison_lecteur_t;

// Ajoute un octet reçu. Rend true quand une question complète, au contrôle bon, est prête :
// son texte (sans le contrôle) est alors dans « question ».
bool liaison_recevoir(liaison_lecteur_t *l, uint8_t octet, char *question, size_t taille);
