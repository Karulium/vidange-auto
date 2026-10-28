#include <string.h>

#include "console.h"
#include "detecteur.h"
#include "essai.h"

static void commandes(void) {
    uint32_t mg;
    VERIFIER(console_lire("", &mg) == COMMANDE_VIDE);
    VERIFIER(console_lire("  \r\n", &mg) == COMMANDE_VIDE);
    VERIFIER(console_lire("aide", &mg) == COMMANDE_AIDE);
    VERIFIER(console_lire("ETAT\r", &mg) == COMMANDE_ETAT);
    VERIFIER(console_lire("seuil", &mg) == COMMANDE_SEUIL && mg == 0);
    VERIFIER(console_lire("seuil 2,5", &mg) == COMMANDE_SEUIL && mg == 2500);
    VERIFIER(console_lire("seuil 1.25 ", &mg) == COMMANDE_SEUIL && mg == 1250);
    VERIFIER(console_lire("seuil 3", &mg) == COMMANDE_SEUIL && mg == 3000);
    VERIFIER(console_lire("seuil ,5", &mg) == COMMANDE_SEUIL && mg == 500);
    VERIFIER(console_lire("seuil 0,0015", &mg) == COMMANDE_SEUIL && mg == 1);
    VERIFIER(console_lire("seuil deux", &mg) == COMMANDE_INCONNUE);
    VERIFIER(console_lire("seuil 2g", &mg) == COMMANDE_INCONNUE);
    VERIFIER(console_lire("seuil 99999999999", &mg) == COMMANDE_INCONNUE);
    VERIFIER(console_lire("seuils", &mg) == COMMANDE_INCONNUE);
    VERIFIER(console_lire("essai chien", &mg) == COMMANDE_ESSAI_CHIEN);
    VERIFIER(console_lire("essai", &mg) == COMMANDE_INCONNUE);
    VERIFIER(console_lire("n'importe quoi", &mg) == COMMANDE_INCONNUE);
}

static void lignes_d_etat(void) {
    char texte[200];
    etat_t etat = {.ok = true, .niveau_max_mg = 84, .seuil_mg = 1500};
    console_ligne_etat(&etat, texte, sizeof texte);
    VERIFIER(strcmp(texte, "OK | max 0,08 g | seuil 1,50 g | chocs 0") == 0);

    etat = (etat_t){.en_choc = true, .niveau_max_mg = 3204, .seuil_mg = 1500, .chocs = 1,
                    .pic_choc_mg = 3204};
    console_ligne_etat(&etat, texte, sizeof texte);
    VERIFIER(strcmp(texte, "COUPÉ : choc | max 3,20 g | seuil 1,50 g | chocs 1 (dernier 3,20 g)") ==
             0);

    etat = (etat_t){.pannes = PANNE_CAPTEUR, .seuil_mg = 1500, .debordements = 2,
                    .sortie_contredit = true};
    console_ligne_etat(&etat, texte, sizeof texte);
    VERIFIER(strstr(texte, "COUPÉ : panne (capteur absent)") == texte);
    VERIFIER(strstr(texte, "mesures perdues 2") != NULL);
    VERIFIER(strstr(texte, "la broche OK ne suit pas") != NULL);

    // Texte trop petit : coupé proprement.
    char court[10];
    console_ligne_etat(&etat, court, sizeof court);
    VERIFIER(strlen(court) == 9);
}

void essais_console(void) {
    LANCER(commandes);
    LANCER(lignes_d_etat);
}
