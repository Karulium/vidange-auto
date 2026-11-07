// Le pilote TMC2209 du moteur du bras, par son UART (fil PDN_UART), sans matériel : les trames de
// la notice de Trinamic (Analog Devices), essayées sur PC.
//
// Écriture (8 octets) : 0x05, adresse (0 à 3), registre + 0x80, 4 octets de la valeur (le fort
// d'abord), contrôle CRC-8. Question (4 octets) : 0x05, adresse, registre, contrôle. Réponse du
// pilote (8 octets) : 0x05, 0xFF, registre, 4 octets, contrôle. Sur un seul fil, la carte entend
// aussi ce qu'elle envoie : tmc_chercher_reponse saute cet écho.
//
// Le pilote garde ses réglages tant qu'il a son 24 V. Après une coupure, il repart avec ceux de
// sa mémoire d'usine (et le bit « reset » de GSTAT) : la carte le voit et le règle de nouveau.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define TMC_GCONF 0x00
#define TMC_GSTAT 0x01
#define TMC_IFCNT 0x02
#define TMC_IOIN 0x06
#define TMC_IHOLD_IRUN 0x10
#define TMC_TPOWERDOWN 0x11
#define TMC_CHOPCONF 0x6C

#define TMC_ECRITURE 8
#define TMC_QUESTION 4
#define TMC_REPONSE 8

// GSTAT, bit 0 : le pilote a redémarré (coupure de son alimentation).
#define TMC_GSTAT_RESET 1u
// IOIN, octet fort : version de la puce (0x21 pour le TMC2209).
#define TMC_VERSION 0x21u

uint8_t tmc_crc(const uint8_t *octets, size_t n);

// Écrit dans `trame` (TMC_ECRITURE octets) l'écriture d'un registre.
void tmc_ecriture(uint8_t *trame, uint8_t adresse, uint8_t registre, uint32_t valeur);

// Écrit dans `trame` (TMC_QUESTION octets) la question pour lire un registre.
void tmc_question(uint8_t *trame, uint8_t adresse, uint8_t registre);

// Cherche dans les octets reçus la réponse juste pour ce registre (après l'écho éventuel).
bool tmc_chercher_reponse(const uint8_t *octets, size_t n, uint8_t registre, uint32_t *valeur);

// Les valeurs des registres pour le bras :
// - GCONF : courant réglé par l'UART (pas par le potentiomètre), micro-pas réglés par l'UART
//   (pas par MS1/MS2, qui donnent l'adresse), filtre des pas ;
uint32_t tmc_gconf(void);
// - IHOLD_IRUN : courant à l'arrêt et en marche (0 à 31), avec une descente douce à l'arrêt ;
uint32_t tmc_ihold_irun(uint8_t ihold, uint8_t irun);
// - CHOPCONF : réglages d'usine, sauf les micro-pas (1 à 256) et l'échelle du courant (VSENSE).
//   Rend 0 si le nombre de micro-pas n'existe pas.
uint32_t tmc_chopconf(uint16_t micro_pas, bool vsense);

// IOIN dit bien « TMC2209 ».
bool tmc_version_juste(uint32_t ioin);
