// Lance tous les essais des programmes du poste du fût, sur PC (sans ESP32-C3, HX711 ni radio).
#include "essai.h"

int essai_echecs = 0;

int main(void) {
    essais_trame();
    essais_accu();
    essais_plateau();
    essais_boite();
    essais_chaine();
    if (essai_echecs) {
        printf("%d échec(s)\n", essai_echecs);
        return 1;
    }
    printf("Tous les essais passent.\n");
    return 0;
}
