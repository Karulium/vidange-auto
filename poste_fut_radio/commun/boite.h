// Ce que fait la boîte du poste, sans le matériel (essayé sur PC avec de fausses trames) : garder
// la dernière trame du plateau, compter, dire « radio muette », et remplir les 13 registres que le
// Pi lit sur le bus des pesées (Modbus, fonction 3 ou 4).
//
// | Registre | Contenu |
// |---|---|
// | 0 et 1 | dernière mesure brute (moyenne faite par le plateau), signée, 32 bits, mot fort d'abord |
// | 2 | numéro de cette mesure (+1 à chaque trame reçue du plateau, repart à 0 après 65 535) |
// | 3 | âge de cette mesure en ms (depuis la dernière trame reçue ; 65 535 au plus, et avant la |
// |   | première trame) |
// | 4 | état : 1 = HX711 muet (dit par le plateau), 2 = réglages d'exemple, 4 = radio muette |
// |   | (rien reçu du plateau depuis radio_muette_ms) |
// | 5 | trames reçues pendant la dernière seconde (2 attendues) |
// | 6 | questions pour la boîte arrivées abîmées, depuis son démarrage |
// | 7 | signature 0x5046 (« PF ») : c'est la boîte du poste du fût |
// | 8 | plateau : 1 = reed fermé (au poste), 2 = 5 V de la recharge sans contact présent (vrai aussi |
// |   | accu plein), 4 = sur l'USB-C de secours |
// | 9 | tension de l'accu, en mV (dernière trame) |
// | 10 | niveau de l'accu, en % (calculé par le plateau) |
// | 11 | force du signal radio, en dBm + 200 (120 = −80 dBm) |
// | 12 | trames radio perdues (numéros sautés), depuis le démarrage de la boîte |
//
// Les registres 0 à 7 ont le même sens que pour une carte de pesée (pesee/src/mesures.h) ;
// le côté Pi : pi/vidange/materiel/carte_pesee.py.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "trame.h"

#define BOITE_REGISTRE_ETAT 4
#define BOITE_REGISTRE_PLATEAU 8
#define BOITE_NB_REGISTRES 13

#define BOITE_ETAT_HX711_MUET 1
#define BOITE_ETAT_EXEMPLE 2
#define BOITE_ETAT_RADIO_MUETTE 4
#define BOITE_PLATEAU_AU_POSTE 1
#define BOITE_PLATEAU_RECHARGE_PRESENTE 2
#define BOITE_PLATEAU_SUR_USB 4
#define BOITE_SIGNATURE 0x5046
// Registre 11 : force du signal en dBm + ce décalage.
#define BOITE_DECALAGE_SIGNAL_DBM 200

// Ce que la boîte fait d'une trame reçue par la radio.
typedef enum {
    BOITE_TRAME_PRISE,
    BOITE_TRAME_AUTRE_ADRESSE,  // d'une autre carte que le plateau : ignorée
    BOITE_TRAME_ABIMEE,         // pas une trame du plateau (taille, « PF », version, contrôle)
    BOITE_TRAME_EN_DOUBLE,      // même numéro que la précédente : ignorée
} boite_reception_t;

typedef struct {
    uint32_t radio_muette_ms;
    bool exemple;
    uint8_t adresse_plateau[6];
    bool une_trame;
    trame_t derniere;
    int8_t signal_dbm;
    uint64_t heure_us;  // de la dernière trame prise
    uint16_t numero;    // +1 à chaque trame prise
    uint16_t perdues;
    uint64_t debut_seconde_us;
    uint16_t compte;
    uint16_t par_seconde;
    // Pour la fenêtre USB (appairage, dépannage).
    uint32_t autre_adresse;
    uint8_t derniere_autre_adresse[6];
    uint32_t abimees;
} boite_t;

void boite_init(boite_t *b, uint32_t radio_muette_ms, bool exemple,
                const uint8_t adresse_plateau[6], uint64_t t_us);

// Une trame reçue par la radio, de l'adresse `adresse`, avec cette force de signal, à t_us.
boite_reception_t boite_recevoir(boite_t *b, const uint8_t adresse[6], const uint8_t *octets,
                                 size_t n, int8_t signal_dbm, uint64_t t_us);

// Le temps passe (trames par seconde) : à appeler souvent.
void boite_avancer(boite_t *b, uint64_t t_us);

bool boite_radio_muette(const boite_t *b, uint64_t t_us);

// Remplit les BOITE_NB_REGISTRES registres, à l'heure t_us.
void boite_registres(const boite_t *b, uint16_t questions_abimees, uint64_t t_us,
                     uint16_t *registres);

// Heure d'arrivée de l'octet i d'un paquet de n octets lu sur le bus à t_lecture_us : le pilote
// de l'UART rend les octets par paquets ; les octets d'un paquet sont arrivés à la suite, un
// toutes les 10 bits, le dernier juste avant la lecture. Sans cela, un long flux continu (les
// questions aux autres cartes et leurs réponses) coupé en deux paquets ressemblerait à un
// silence de fin de trame (pesee/src/modbus.h). L'heure rendue n'est jamais avant celle de
// l'octet précédent (*precedent_us, mis à jour) : le temps ne recule pas pour modbus_recevoir.
uint64_t boite_heure_octet(uint64_t t_lecture_us, size_t n, size_t i, uint32_t bauds,
                           uint64_t *precedent_us);
