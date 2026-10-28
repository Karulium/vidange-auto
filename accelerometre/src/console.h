// Fenêtre texte sur le câble USB du RP2040, pour les essais à l'établi :
// une ligne d'état régulière, et quelques commandes tapées au clavier.
// Ce fichier ne fait que lire les commandes et écrire les lignes : il est essayé sur PC.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    COMMANDE_VIDE = 0,
    COMMANDE_AIDE,
    COMMANDE_ETAT,         // « etat » : la ligne d'état tout de suite
    COMMANDE_SEUIL,        // « seuil » : montrer le seuil ; « seuil 2,5 » : le changer (en g)
    COMMANDE_ESSAI_CHIEN,  // « essai chien » : figer le programme pour essayer le chien de garde
    COMMANDE_INCONNUE,
} commande_t;

// Lit une ligne tapée. Pour « seuil 2,5 », seuil_mg reçoit 2500 (0 si pas de valeur ;
// COMMANDE_INCONNUE si la valeur est mal écrite).
commande_t console_lire(const char *ligne, uint32_t *seuil_mg);

// Ce que la console sait de la mesure (recopié par le programme de mesure).
typedef struct {
    bool ok;
    bool en_choc;
    uint32_t pannes;
    uint32_t pannes_vues;
    uint32_t niveau_max_mg;  // le plus fort depuis la ligne d'état précédente
    uint32_t chocs;
    uint32_t pic_choc_mg;
    uint32_t seuil_mg;
    uint32_t debordements;  // mesures perdues (lues trop tard)
    int16_t autotest_ecart[3];
    bool sortie_contredit;  // la broche « OK » ne suit pas ce qu'on lui commande
} etat_t;

// La ligne d'état, par exemple :
// « OK | max 0,08 g | seuil 1,50 g | chocs 0 »
// « COUPÉ : choc | max 3,20 g | seuil 1,50 g | chocs 1 (dernier 3,20 g) »
void console_ligne_etat(const etat_t *etat, char *texte, size_t taille);

// Le texte d'aide (liste des commandes).
const char *console_aide(void);
