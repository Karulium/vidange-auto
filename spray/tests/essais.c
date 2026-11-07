// Lance tous les essais du programme de la carte du spray, sur PC (sans ESP32-S3, moteurs,
// HX711 ni capteur : des faux).
#include "essai.h"

int essai_echecs = 0;

int main(void) {
    essais_moteur();
    essais_balance();
    essais_tmc2209();
    essais_spray();
    essais_bus();
    if (essai_echecs) {
        printf("%d échec(s)\n", essai_echecs);
        return 1;
    }
    printf("Tous les essais passent.\n");
    return 0;
}
