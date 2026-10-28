// Liaison série avec le Pi sur un seul fil (half-duplex) : le protocole.
//
// Le Pi pose une question, le RP2040 répond ; le RP2040 ne parle jamais sans question.
// Ainsi les deux ne parlent jamais en même temps sur le fil.
//
// Une trame = une ligne de texte, avec à la fin un « * », le contrôle CRC-16 du texte
// (4 chiffres hexadécimaux) et un retour à la ligne :
//   « ETAT*F09B\n »
// Une question au CRC faux (fil abîmé, parasite) est oubliée sans réponse : le Pi redemande.
//
// Questions du Pi et réponses (temps en ms depuis le démarrage du RP2040, forces en mg) :
//   ETAT        → ETAT t_ms=… ok=1 choc=0 pannes=0 vues=0 max_mg=… chocs=… perdues=… chien=0
//                 contredit=0     (max_mg : le plus fort depuis la question ETAT d'avant)
//   CHOC 12     → CHOC n=12 t_ms=… duree_ms=… pic_mg=… fini=1
//                 CHOC n=12 absent=1   (trop vieux ou pas encore arrivé)
//   REGLAGES    → REGLAGES pleine_echelle_g=8 mesures_par_seconde=400 axes=yz seuil_mg=1500 …
//   REGLER pleine_echelle_g=8 … (tous les réglages de REGLAGES)
//               → REGLER ok        ou    REGLER refuse <pourquoi>
//   autre       → ERREUR commande inconnue
//
// Ce fichier ne touche à aucun matériel : il est essayé sur PC (et le Pi a le même en Python,
// pi/vidange/accelerometre/protocole.py).
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "console.h"
#include "detecteur.h"
#include "reglages.h"

// Plus longue trame (texte, contrôle et fin de ligne compris).
#define LIAISON_LIGNE_MAX 256

// Contrôle CRC-16 (CCITT : polynôme 0x1021, départ 0xFFFF) du texte.
uint16_t liaison_crc(const char *texte, size_t n);

// Écrit la trame du texte (texte, « * », contrôle, « \n »). Rend sa longueur (0 : trop longue).
size_t liaison_trame(const char *texte, char *trame, size_t taille);

// Assemble les octets reçus en lignes.
typedef struct {
    char texte[LIAISON_LIGNE_MAX];
    size_t n;
    bool trop_longue;
    uint32_t refusees;  // lignes oubliées (CRC faux, mal formées, trop longues)
} liaison_lecteur_t;

// Ajoute un octet reçu. Rend true quand une question complète, au contrôle bon, est prête :
// son texte (sans le contrôle) est alors dans « question ».
bool liaison_recevoir(liaison_lecteur_t *l, uint8_t octet, char *question, size_t taille);

// Ce que le Pi peut savoir.
typedef struct {
    etat_t etat;
    uint64_t t_ms;  // temps depuis le démarrage du RP2040
    bool redemarre_par_chien;
    reglages_t reglages;
    choc_t historique[HISTORIQUE_CHOCS];
} liaison_donnees_t;

// Le programme, vu de la liaison.
typedef struct {
    // Copie ce que le Pi peut savoir. remettre_max : la question ETAT remet le « plus fort
    // depuis la question d'avant » à zéro.
    void (*lire)(void *contexte, liaison_donnees_t *donnees, bool remettre_max);
    // Applique les réglages envoyés par le Pi. false (et « message ») s'ils sont refusés.
    bool (*regler)(void *contexte, const reglages_t *reglages, char *message, size_t taille);
    void *contexte;
} liaison_programme_t;

// Répond à une question : écrit la trame de la réponse dans « reponse », rend sa longueur.
size_t liaison_repondre(const char *question, const liaison_programme_t *programme,
                        char *reponse, size_t taille);
