// Modbus RTU, côté carte (esclave) : le Pi pose une question, la carte à cette adresse répond.
// Aucun matériel ici (essayé sur PC) : main.c donne les octets reçus et envoie la réponse.
//
// La lecture de registres (fonction 3 ou 4, les deux lisent la même table : voir mesures.h) :
// ces questions font 8 octets : adresse, fonction, premier registre (2 octets), nombre
// (2 octets), contrôle CRC-16 (2 octets, le faible d'abord). Les cartes de pesée ne font que ça.
// L'écriture de registres (fonction 16), pour la carte du spray (spray/README.md) : adresse,
// fonction, premier registre, nombre, nombre d'octets, les valeurs (2 octets chacune), contrôle.
// La carte qui écrit lit la question par modbus_lire_ecriture et répond par
// modbus_repondre_ecriture ; modbus_repondre la refuse (exception 1).
//
// Fin d'une trame : une question est traitée dès son dernier octet si le contrôle est juste (pas
// besoin d'attendre le silence de fin de trame : la réponse part plus vite). La carte entend
// aussi les questions aux autres cartes et leurs réponses : après une question juste pour une
// autre adresse, elle compte les octets de la réponse (sa longueur est dans son 3e octet), pour
// être prête à la question suivante, que le Pi pose sans attendre. Un silence plus long que
// MODBUS_SILENCE_US remet tout à zéro (trame abîmée, carte absente).
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Silence de fin de trame : 3,5 caractères, fixé à 1,75 ms au-delà de 19 200 bauds.
#define MODBUS_SILENCE_US 1750
#define MODBUS_QUESTION 8
// Plus longue question : une écriture de 123 registres (le maximum de Modbus), 255 octets.
#define MODBUS_TRAME_MAX 256
// Plus longue réponse : 125 registres (le maximum de Modbus).
#define MODBUS_REGISTRES_MAX 125
#define MODBUS_REPONSE_MAX (5 + 2 * MODBUS_REGISTRES_MAX)

// Codes d'exception renvoyés au Pi.
#define MODBUS_FONCTION_INCONNUE 1
#define MODBUS_REGISTRE_INCONNU 2
#define MODBUS_NOMBRE_FAUX 3

typedef struct {
    uint8_t adresse;  // de 1 à 247 ; 0 = message à tous, auquel personne ne répond
    uint8_t trame[MODBUS_TRAME_MAX];
    size_t n;               // octets reçus de la trame en cours
    size_t longueur;        // longueur de la dernière question complète
    bool reponse_attendue;  // la trame en cours est la réponse d'une autre carte
    bool perdu;             // trame incomprise : attendre un silence
    uint64_t dernier_octet_us;
    // Questions pour cette carte arrivées abîmées (contrôle faux) : un câble ou une
    // terminaison du bus à vérifier.
    uint16_t trames_abimees;
} modbus_t;

uint16_t modbus_crc(const uint8_t *octets, size_t n);

void modbus_init(modbus_t *m, uint8_t adresse);

// Oublie ce qui a été reçu (après une réponse : un écho éventuel ne compte pas).
void modbus_oublier(modbus_t *m);

// Range un octet reçu à l'heure t_us. Vrai quand une question juste, pour cette carte, est
// complète : la réponse se fait alors par modbus_repondre.
bool modbus_recevoir(modbus_t *m, uint8_t octet, uint64_t t_us);

// Écrit dans `reponse` (MODBUS_REPONSE_MAX octets) la réponse à la dernière question complète,
// avec la table de `nb` registres : les registres demandés, ou une exception. Rend sa taille.
size_t modbus_repondre(const modbus_t *m, const uint16_t *registres, size_t nb,
                       uint8_t *reponse);

// La fonction de la dernière question complète (3, 4, 16...).
uint8_t modbus_fonction(const modbus_t *m);

// Une exception (code MODBUS_...) en réponse à la dernière question. Rend sa taille (5).
size_t modbus_exception(const modbus_t *m, uint8_t code, uint8_t *reponse);

// La dernière question complète est une écriture (fonction 16) : son premier registre et ses
// valeurs (au plus `max`). Rend le nombre de registres, 0 si la question est mal faite (nombre
// nul, trop grand, ou qui ne va pas avec le nombre d'octets).
size_t modbus_lire_ecriture(const modbus_t *m, uint16_t *premier, uint16_t *valeurs, size_t max);

// Répond à une écriture : l'accusé (adresse, fonction, premier registre, nombre), ou
// l'exception `code` s'il n'est pas 0. Rend sa taille.
size_t modbus_repondre_ecriture(const modbus_t *m, uint8_t code, uint8_t *reponse);
