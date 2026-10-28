// Le cœur du programme : décide si « OK » est donné, à partir des mesures du capteur.
//
// « OK » est donné seulement si TOUT va bien : réglages bons, capteur vérifié (autotest),
// mesures qui arrivent et qui vivent, et pas de choc en cours. Tout le reste coupe « OK »
// (sécurité positive). Ce fichier ne touche à aucun matériel : il est essayé sur PC.
//
// Choc : on retire de chaque mesure un « fond » lent (pente du capteur, pesanteur, dérive),
// puis on regarde la force des axes horizontaux. Au-dessus du seuil pendant au moins
// duree_min_ms : choc. « OK » revient maintien_ms après le dernier dépassement.
//
// Panne : capteur absent, autotest raté, lectures ratées, plus de mesure, mesure figée.
// Après reessai_ms, le programme principal revérifie le capteur (autotest compris) ;
// s'il passe, la panne est effacée.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "reglages.h"

// Les pannes, en bits (plusieurs à la fois possibles).
#define PANNE_REGLAGES 0x01u        // réglages faux : ne s'efface pas
#define PANNE_CAPTEUR 0x02u         // capteur absent ou qui n'est pas un LIS3DH
#define PANNE_AUTOTEST 0x04u        // autotest raté
#define PANNE_LECTURE 0x08u         // lectures I2C ratées de suite
#define PANNE_MESURE_ABSENTE 0x10u  // plus de mesure nouvelle
#define PANNE_MESURE_FIGEE 0x20u    // mêmes valeurs exactes trop longtemps

// Les derniers chocs, gardés pour le Pi (il les lit par le fil série).
#define HISTORIQUE_CHOCS 16

typedef struct {
    uint32_t numero;      // 1 pour le premier choc depuis le démarrage
    uint64_t t_debut_us;  // début du dépassement
    uint32_t duree_ms;    // du début du dépassement au dernier dépassement
    uint32_t pic_mg;      // le plus fort
    bool fini;            // false tant que le choc dure (le pic et la durée peuvent grandir)
} choc_t;

typedef struct {
    reglages_t reglages;
    uint32_t pannes;       // pannes en cours
    uint32_t pannes_vues;  // toutes celles vues depuis le démarrage (pour la console)
    bool pret;             // capteur vérifié, mesures attendues
    uint64_t t_reessai_us;
    // Mesures.
    bool fond_pret;
    float fond[3];
    uint64_t t_mesure_us;  // dernière mesure reçue (ou démarrage du capteur)
    int32_t precedente[3];
    uint64_t t_identique_us;  // depuis quand les mesures sont identiques
    uint32_t erreurs_suite;
    // Choc.
    uint32_t niveau_mg;  // force horizontale de la dernière mesure, fond retiré
    bool en_depassement;
    uint64_t t_depassement_us;  // début du dépassement en cours
    uint32_t pic_depassement_mg;
    bool en_choc;
    uint64_t t_dernier_us;  // dernier dépassement pendant le choc
    uint32_t chocs;         // nombre de chocs depuis le démarrage
    uint32_t pic_choc_mg;   // le plus fort du dernier choc
    choc_t historique[HISTORIQUE_CHOCS];  // le choc n est en historique[(n - 1) % HISTORIQUE_CHOCS]
} detecteur_t;

// Prépare le détecteur. Des réglages faux donnent la panne PANNE_REGLAGES (OK jamais donné).
void detecteur_demarrer(detecteur_t *d, const reglages_t *reglages);

// Change le seuil (console). Refusé (false) si le seuil n'est pas bon.
bool detecteur_changer_seuil(detecteur_t *d, uint32_t seuil_mg);

// Change tous les réglages (envoyés par le Pi). Refusé (false) s'ils ne sont pas bons.
// Une autre pleine échelle ou vitesse de mesure fait revérifier le capteur tout de suite
// (« OK » coupé le temps de l'autotest). Des réglages bons effacent la panne PANNE_REGLAGES.
bool detecteur_changer_reglages(detecteur_t *d, const reglages_t *reglages);

// Le choc n° « numero » s'il est encore dans l'historique (sinon false : trop vieux, ou pas
// encore arrivé).
bool detecteur_choc(const choc_t historique[HISTORIQUE_CHOCS], uint32_t chocs, uint32_t numero,
                    choc_t *choc);

// true quand le programme principal doit (re)vérifier le capteur.
bool detecteur_verification_due(const detecteur_t *d, uint64_t t_us);

// Résultat de la vérification du capteur : 0 si elle est bonne, sinon la panne.
void detecteur_verification_faite(detecteur_t *d, uint64_t t_us, uint32_t panne);

// Une mesure nouvelle (mg sur x, y, z).
void detecteur_mesure(detecteur_t *d, uint64_t t_us, const int32_t mg[3]);

// Une lecture I2C ratée.
void detecteur_erreur_lecture(detecteur_t *d, uint64_t t_us);

// À appeler à chaque tour, mesure ou pas : surveille l'arrivée des mesures.
void detecteur_surveiller(detecteur_t *d, uint64_t t_us);

// La sortie « OK ».
bool detecteur_ok(const detecteur_t *d);

// Le texte des pannes « pannes » (une à la fois, la plus importante d'abord).
const char *detecteur_texte_panne(uint32_t pannes);
