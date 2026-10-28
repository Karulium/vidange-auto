// Le fil série unique vers le Pi (half-duplex), avec deux machines PIO du RP2040.
// Les octets reçus sont rangés par une interruption (rien n'est perdu si le programme est
// occupé) ; l'envoi attend la fin du dernier octet puis rend le fil.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Prépare le fil (broche, vitesse). À appeler sur le cœur qui lira les octets.
void un_fil_demarrer(unsigned broche, uint32_t vitesse_bauds);

// Un octet reçu, s'il y en a un.
bool un_fil_lire(uint8_t *octet);

// Envoie les octets : prend le fil, envoie, attend la fin, rend le fil et réécoute.
void un_fil_envoyer(const char *octets, size_t n);

// Octets perdus (reçus quand la réserve était pleine) depuis le démarrage.
uint32_t un_fil_perdus(void);
