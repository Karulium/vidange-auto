// Lance tous les essais du programme des cartes de pesée, sur PC (sans RP2040 ni HX711).
#include "essai.h"

int essai_echecs = 0;

int main(void) {
    essais_hx711();
    essais_modbus();
    essais_mesures();
    essais_pca9685();
    essais_vl6180x();
    essais_plateau();
    essais_rythme();
    if (essai_echecs) {
        printf("%d échec(s)\n", essai_echecs);
        return 1;
    }
    printf("Tous les essais passent.\n");
    return 0;
}
