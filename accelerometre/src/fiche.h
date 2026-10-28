// La fiche du programme : 256 octets écrits dans la flash juste avant le programme, qui disent
// sa taille, son contrôle CRC-32 et son nom (sa version). Le chargeur ne lance le programme que
// si sa fiche est bonne et si le contrôle du programme est juste.
//
// Le fichier du programme envoyé par le Pi (« accelerometre.bin ») est cette fiche suivie du
// programme ; le Pi a le même format en Python (pi/vidange/accelerometre/fichier_programme.py).
//
// Les nombres sont rangés poids faible d'abord :
//   0   « ACCL »           4 octets (FICHE_MAGIE)
//   4   format             FICHE_FORMAT
//   8   adresse            où le programme a été fabriqué pour tourner (plan_memoire.cmake)
//   12  taille             du programme, en octets
//   16  crc                CRC-32 du programme (le même que zlib.crc32 de Python)
//   20  nom                32 octets : texte terminé par des zéros (lettres, chiffres, . _ + -)
//   252 crc de la fiche    CRC-32 des 252 premiers octets
//
// Ce fichier ne touche à aucun matériel : il est essayé sur PC.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define FICHE_TAILLE 256
#define FICHE_MAGIE 0x4C434341u  // « ACCL »
#define FICHE_FORMAT 1u
#define FICHE_NOM_MAX 32  // zéro de fin compris

typedef struct {
    uint32_t adresse;
    uint32_t taille;
    uint32_t crc;
    char nom[FICHE_NOM_MAX];
} fiche_t;

// CRC-32 (celui de zlib) : on peut le continuer morceau par morceau en redonnant le résultat
// d'avant (0 pour commencer).
uint32_t fiche_crc32(uint32_t crc, const uint8_t *octets, size_t n);

// Un nom acceptable : de 1 à 31 caractères, lettres, chiffres, « . », « _ », « + », « - ».
bool fiche_nom_valide(const char *nom);

// Écrit la fiche en octets (pour la flash).
void fiche_ecrire(const fiche_t *fiche, uint8_t octets[FICHE_TAILLE]);

// Relit une fiche. false si elle est absente ou abîmée.
bool fiche_lire(const uint8_t octets[FICHE_TAILLE], fiche_t *fiche);
