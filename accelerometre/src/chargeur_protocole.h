// Le chargeur : ce qu'il répond au Pi sur le fil série unique (mêmes trames que le programme,
// liaison_trame.h). Il met à jour le programme du RP2040 sans démonter le boîtier.
//
// Plan de la flash (plan_memoire.cmake) : le chargeur (jamais réécrit par le fil), puis la
// « zone » : un secteur de 4 Kio pour la fiche du programme (fiche.h), puis le programme.
//
// Questions du Pi et réponses (nombres en décimal, contrôles en hexadécimal) :
//   CHARGEUR    → CHARGEUR pret version=1 fil=0 sortie_ok=2 place=… programme=bon
//                 adresse=… taille=… crc=… nom=…   (programme=absent, ou abime : sa fiche ou
//                 son contrôle est faux ; adresse, taille, crc et nom si la fiche est lisible)
//   DEBUT adresse=… taille=… crc=… nom=…
//               → DEBUT ok       efface la fiche : le programme d'avant ne sera plus lancé
//   ECRIRE 0 <512 chiffres hexadécimaux>   (une page de 256 octets ; la dernière, plus courte)
//               → ECRIRE ok n=0  les pages dans l'ordre ; la même page redemandée (réponse
//                                perdue) est acceptée si elle est identique
//   FIN         → FIN ok crc=…   contrôle du programme écrit, puis écriture de sa fiche
//   LIRE 0      → LIRE n=0 <512 chiffres>   (pour garder une copie du programme d'avant)
//   LANCER      → LANCER ok      puis le programme démarre (seulement s'il est bon)
//   autre       → ERREUR chargeur
//   Un refus : « DEBUT refuse <pourquoi> », « ECRIRE refuse … »...
//
// Ce fichier ne touche à aucun matériel : il est essayé sur PC, avec une fausse flash.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "fiche.h"

#define CHARGEUR_VERSION 1
#define CHARGEUR_SECTEUR 4096u  // la flash s'efface par secteurs...
#define CHARGEUR_PAGE 256u      // ... et s'écrit par pages

// Le programme demande le chargeur en écrivant ce nombre dans le registre « scratch[0] » du
// chien de garde (et son inverse dans « scratch[1] »), qui survit au redémarrage.
#define CHARGEUR_MAGIE 0x43485247u  // « CHRG »

// La flash de la zone, vue du chargeur. Décalages depuis le début de la zone (la fiche).
typedef struct {
    const uint8_t *zone;   // lecture directe
    uint32_t taille_zone;  // fiche et programme
    bool (*effacer)(void *contexte, uint32_t decalage);  // un secteur
    bool (*ecrire)(void *contexte, uint32_t decalage, const uint8_t *page);  // une page
    void *contexte;
    uint32_t adresse_programme;  // l'adresse où le programme doit avoir été fabriqué
    unsigned broche_fil;         // dites au Pi, pour vérifier
    unsigned broche_ok;
} chargeur_flash_t;

typedef enum { PROGRAMME_BON, PROGRAMME_ABSENT, PROGRAMME_ABIME } programme_etat_t;

typedef struct {
    const chargeur_flash_t *flash;
    programme_etat_t etat;
    fiche_t fiche;     // celle du programme présent (si lisible), ou annoncée par DEBUT
    bool ouvert;       // DEBUT reçu, FIN pas encore
    uint32_t pages;    // pages écrites depuis DEBUT
    bool lancer;       // LANCER accepté : lancer le programme après la réponse
} chargeur_t;

// Place pour le programme dans la zone (après le secteur de la fiche).
uint32_t chargeur_place(const chargeur_flash_t *flash);

// Regarde le programme présent (fiche et contrôle).
programme_etat_t chargeur_examiner(const chargeur_flash_t *flash, fiche_t *fiche);

void chargeur_demarrer(chargeur_t *c, const chargeur_flash_t *flash);

// Répond à une question : écrit la trame de la réponse dans « reponse », rend sa longueur.
size_t chargeur_repondre(chargeur_t *c, const char *question, char *reponse, size_t taille);
