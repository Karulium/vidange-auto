// Lance tous les essais du programme de l'accéléromètre, sur PC (sans RP2040 ni capteur).
#include "essai.h"

int essai_echecs = 0;

int main(void) {
    essais_reglages();
    essais_lis3dh();
    essais_detecteur();
    essais_console();
    essais_liaison();
    if (essai_echecs) {
        printf("%d échec(s)\n", essai_echecs);
        return 1;
    }
    printf("Tous les essais passent.\n");
    return 0;
}
