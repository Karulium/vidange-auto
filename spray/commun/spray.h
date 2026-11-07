// La carte ESP32 n° 5 du spray sans le matériel : ordres du Pi, refus, gestes (spray, nettoyage),
// bras, silence du Pi, et la table des registres de ../README.md (la langue commune avec le Pi :
// pi/vidange/materiel/carte_spray.py). Essayée sur PC (tests/), avec de faux moteurs, de fausses
// balances et un faux capteur.
//
// La carte (carte/main/main.c) appelle :
// - spray_avancer souvent (toutes les ms environ) : le temps passe, les gestes avancent ;
// - spray_repondre à chaque question Modbus complète pour elle ;
// - spray_sorties, puis allume ou éteint ses sorties (électrovannes, petite pompe, agitateurs).
// Les 5 moteurs (bras et 4 pompes) sont commandés ici, et avancés par la minuterie des pas
// (moteur_tick) : la carte prend le même verrou pour les deux.
//
// Le spray ne protège personne. Les refus et l'arrêt seul quand le Pi se tait protègent la
// machine (le bras, la buse).
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "balance.h"
#include "modbus.h"
#include "moteur.h"

#define SPRAY_NB_FLACONS 4
#define SPRAY_NB_REGISTRES 30
#define SPRAY_SIGNATURE 0x5350
#define SPRAY_VERSION 1
// Registres écrits par le Pi (fonction 16).
#define SPRAY_REGISTRE_BATTEMENT 100
#define SPRAY_REGISTRE_ORDRE 101
#define SPRAY_REGISTRE_NUMERO 104

// Registre 3 : état.
#define SPRAY_ETAT_BRAS_RANGE 1u
#define SPRAY_ETAT_BRAS_SORTI 2u
#define SPRAY_ETAT_BRAS_BOUGE 4u
#define SPRAY_ETAT_ORIGINE_FAITE 8u
#define SPRAY_ETAT_SPRAY_EN_COURS 16u
#define SPRAY_ETAT_NETTOYAGE_EN_COURS 32u
#define SPRAY_ETAT_AGITATEURS 64u
#define SPRAY_ETAT_EXEMPLE 128u
#define SPRAY_ETAT_SILENCE_PI 256u
#define SPRAY_ETAT_ARRET_IMMEDIAT 512u

// Registre 4 : erreurs. Bits 0 à 7 : balances muettes (1 << n) et instables (16 << n), en direct.
#define SPRAY_ERREUR_BRAS_PAS_RANGE 256u
#define SPRAY_ERREUR_BRAS_PAS_SORTI 512u
#define SPRAY_ERREUR_BRAS_POUSSE 1024u
#define SPRAY_ERREUR_PILOTE_BRAS 2048u
#define SPRAY_ERREURS_DU_BRAS 0xFF00u

// Registre 7 : suite du dernier ordre.
enum { SUITE_AUCUN, SUITE_EN_COURS, SUITE_FAIT, SUITE_REFUSE, SUITE_ECHOUE };

// Registre 8 : raison du refus.
enum {
    REFUS_AUCUN,
    REFUS_ORDRE_INCONNU,
    REFUS_PARAMETRE,
    REFUS_PAS_D_ORIGINE,
    REFUS_PAS_DE_BATTEMENT,
    REFUS_OCCUPEE,
    REFUS_BALANCE,
    REFUS_BRAS_PAS_SORTI,
    REFUS_ERREUR_BRAS,
};

// Registre 101 : les ordres.
enum {
    ORDRE_ORIGINE = 1,
    ORDRE_SORTIR,
    ORDRE_RANGER,
    ORDRE_SPRAY,
    ORDRE_NETTOYER,
    ORDRE_AGITER,
    ORDRE_ARRET,
    ORDRE_EFFACER,
};

// Registre 26 : résultat de la dernière dose.
enum {
    DOSE_AUCUNE,
    DOSE_EN_COURS,
    DOSE_ATTEINTE,
    DOSE_TEMPS_MAX,
    DOSE_INTERROMPUE,
    DOSE_REFUSEE,
};

// Les réglages (machine.yaml → spray, copiés à la fabrication), en unités de la carte.
typedef struct {
    bool exemple;
    uint16_t course_dixiemes;      // butée logicielle (1100 = 110°)
    int32_t bras_pas_par_tour;     // pas du moteur (micro-pas compris) par tour du bras
    int32_t bras_depassement_pas;  // « ranger » cherche le capteur jusqu'à −depassement
    uint32_t bras_temps_max_ms;
    uint32_t filtre_capteur_ms;
    uint32_t air_avant_ms;
    uint32_t temps_max_pompage_ms;
    uint32_t chasse_ms;
    uint32_t air_apres_ms;
    uint32_t nettoyage_pompe_ms;
    uint32_t sechage_ms;
    uint32_t silence_max_ms;
} spray_reglages_t;

// Ce que la carte allume (les pompes et le bras sont des moteurs, commandés directement).
typedef struct {
    bool ev_buse;
    bool ev_chasse;
    bool pompe_nettoyage;
    uint8_t agitateurs_pct;
} spray_sorties_t;

typedef enum { MOUVEMENT_AUCUN, MOUVEMENT_ORIGINE, MOUVEMENT_SORTIR, MOUVEMENT_RANGER } mouvement_t;
typedef enum { GESTE_AUCUN, GESTE_SPRAY, GESTE_NETTOYAGE } geste_t;
typedef enum {
    PHASE_AIR_AVANT,
    PHASE_POMPE,
    PHASE_POMPE_NETTOYAGE,
    PHASE_CHASSE,
    PHASE_AIR_APRES,
    PHASE_FIN,
} phase_t;

typedef struct {
    uint16_t emplacement;  // 1 à 4 ; 0 : aucune
    uint16_t demandee;     // dixièmes de gramme
    int32_t perdue;        // dixièmes de gramme
    uint32_t duree_ms;
    uint16_t resultat;
    uint16_t numero;
} spray_dose_t;

typedef struct {
    spray_reglages_t r;
    moteur_t *bras;
    moteur_t *pompes[SPRAY_NB_FLACONS];
    const balance_t *balances;  // les 4 balances
    uint16_t demarrages;
    uint64_t maintenant_us;
    // Le Pi.
    bool message_recu;  // le Pi a écrit au moins une fois depuis le démarrage
    uint64_t dernier_message_us;
    bool battement_recu;
    uint64_t dernier_battement_us;
    bool numero_recu;
    uint16_t numero_ordre;
    uint16_t suite;
    uint16_t refus;
    bool silence;  // arrêtée seule : le Pi s'est tu
    bool arret;    // arrêt immédiat reçu
    // Le capteur du bras rangé (filtré) et le pilote.
    bool capteur;
    bool capteur_brut;
    uint64_t capteur_change_us;
    bool pilote_ok;
    // Le bras.
    bool origine;
    uint16_t erreurs;  // bits 8 à 11
    mouvement_t mouvement;
    uint64_t debut_mouvement_us;
    bool sorti;
    int32_t cible_dixiemes;
    // Le geste en cours.
    geste_t geste;
    phase_t phase;
    uint64_t debut_phase_us;
    uint64_t debut_pompe_us;
    bool pompe_partie;
    int32_t depart_dixiemes;
    spray_dose_t dose;
    // Les agitateurs.
    uint8_t agitateurs_pct;
    uint64_t fin_agitation_us;
} spray_t;

void spray_init(spray_t *s, const spray_reglages_t *r, moteur_t *bras,
                moteur_t *pompes[SPRAY_NB_FLACONS], const balance_t *balances,
                uint16_t demarrages, uint64_t t_us);

// Le temps passe jusqu'à t_us. `capteur` : le capteur voit le bras (broche à 0 derrière le
// PC817 : déjà inversé). `pilote_ok` : le pilote du bras répond sur son UART.
void spray_avancer(spray_t *s, bool capteur, bool pilote_ok, uint64_t t_us);

// Le pilote du bras a redémarré (coupure de son 24 V) : ses pas ne sont plus sûrs, la prise
// d'origine est à refaire.
void spray_pilote_redemarre(spray_t *s);

// Les 30 registres de lecture.
void spray_registres(const spray_t *s, uint16_t trames_abimees, uint16_t *registres);

// Répond à la question complète de `m` (fonction 4 : lecture des registres 0 à 29 ; fonction
// 16 : écriture des registres 100 à 104 ; les autres : exception 1). Rend la taille de la
// réponse (au plus MODBUS_REPONSE_MAX).
size_t spray_repondre(spray_t *s, const modbus_t *m, uint64_t t_us, uint8_t *reponse);

spray_sorties_t spray_sorties(const spray_t *s);

// Angle du bras en dixièmes de degré (d'après les pas comptés, 0 au capteur).
int32_t spray_angle_dixiemes(const spray_t *s);

// Heure d'arrivée de l'octet n° i d'un paquet de n octets lu à t_lecture_us (le pilote de l'UART
// les rend par paquets) : chacun 10 bits plus tôt que le suivant, jamais avant le précédent.
uint64_t spray_heure_octet(uint64_t t_lecture_us, size_t n, size_t i, uint32_t bauds,
                           uint64_t *precedent_us);
