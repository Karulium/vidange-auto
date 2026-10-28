#include "console.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>

#include "detecteur.h"

static const char *sauter_blancs(const char *texte) {
    while (*texte == ' ' || *texte == '\t') {
        texte++;
    }
    return texte;
}

// Le mot « mot » au début de « texte », suivi d'un blanc ou de la fin : rend la suite.
static const char *mot(const char *texte, const char *mot) {
    size_t n = strlen(mot);
    if (strncmp(texte, mot, n) != 0) {
        return NULL;
    }
    if (texte[n] != '\0' && texte[n] != ' ' && texte[n] != '\t') {
        return NULL;
    }
    return sauter_blancs(texte + n);
}

// Lit un nombre de g (« 2 », « 2,5 », « 2.50 ») en mg. false si mal écrit.
static bool lire_g(const char *texte, uint32_t *mg) {
    uint32_t entier = 0;
    uint32_t milliemes = 0;
    int chiffres = 0;
    int decimales = 0;
    for (; isdigit((unsigned char)*texte); texte++, chiffres++) {
        if (entier > 1000) {
            return false;
        }
        entier = entier * 10 + (uint32_t)(*texte - '0');
    }
    if (*texte == ',' || *texte == '.') {
        texte++;
        for (; isdigit((unsigned char)*texte); texte++, decimales++, chiffres++) {
            if (decimales < 3) {
                milliemes = milliemes * 10 + (uint32_t)(*texte - '0');
            }
        }
    }
    for (int d = decimales; d < 3; d++) {
        milliemes *= 10;
    }
    if (chiffres == 0 || *sauter_blancs(texte) != '\0') {
        return false;
    }
    *mg = entier * 1000 + milliemes;
    return true;
}

commande_t console_lire(const char *ligne, uint32_t *seuil_mg) {
    char propre[64];
    size_t n = 0;
    ligne = sauter_blancs(ligne);
    // En minuscules, sans le retour à la ligne ni les blancs de la fin.
    for (; *ligne && *ligne != '\r' && *ligne != '\n' && n + 1 < sizeof propre; ligne++) {
        propre[n++] = (char)tolower((unsigned char)*ligne);
    }
    while (n > 0 && (propre[n - 1] == ' ' || propre[n - 1] == '\t')) {
        n--;
    }
    propre[n] = '\0';
    *seuil_mg = 0;

    const char *suite;
    if (n == 0) {
        return COMMANDE_VIDE;
    }
    if (mot(propre, "aide") || mot(propre, "?")) {
        return COMMANDE_AIDE;
    }
    if ((suite = mot(propre, "etat")) && *suite == '\0') {
        return COMMANDE_ETAT;
    }
    if ((suite = mot(propre, "seuil"))) {
        if (*suite == '\0') {
            return COMMANDE_SEUIL;
        }
        return lire_g(suite, seuil_mg) ? COMMANDE_SEUIL : COMMANDE_INCONNUE;
    }
    if ((suite = mot(propre, "essai")) && (suite = mot(suite, "chien")) && *suite == '\0') {
        return COMMANDE_ESSAI_CHIEN;
    }
    return COMMANDE_INCONNUE;
}

// « 1,50 g » (mg arrondis au centième de g).
static void ecrire_g(char *texte, size_t taille, uint32_t mg) {
    uint32_t centiemes = (mg + 5) / 10;
    snprintf(texte, taille, "%lu,%02lu g", (unsigned long)(centiemes / 100),
             (unsigned long)(centiemes % 100));
}

void console_ligne_etat(const etat_t *etat, char *texte, size_t taille) {
    char max[16];
    char seuil[16];
    char pic[16];
    char debut[48];
    ecrire_g(max, sizeof max, etat->niveau_max_mg);
    ecrire_g(seuil, sizeof seuil, etat->seuil_mg);
    ecrire_g(pic, sizeof pic, etat->pic_choc_mg);
    if (etat->ok) {
        snprintf(debut, sizeof debut, "OK");
    } else if (etat->pannes) {
        snprintf(debut, sizeof debut, "COUPÉ : panne (%s)", detecteur_texte_panne(etat->pannes));
    } else if (etat->en_choc) {
        snprintf(debut, sizeof debut, "COUPÉ : choc");
    } else {
        snprintf(debut, sizeof debut, "COUPÉ : démarrage");
    }
    int n = snprintf(texte, taille, "%s | max %s | seuil %s | chocs %lu", debut, max, seuil,
                     (unsigned long)etat->chocs);
    if (etat->chocs > 0 && n >= 0 && (size_t)n < taille) {
        n += snprintf(texte + n, taille - (size_t)n, " (dernier %s)", pic);
    }
    if (etat->debordements > 0 && n >= 0 && (size_t)n < taille) {
        n += snprintf(texte + n, taille - (size_t)n, " | mesures perdues %lu",
                      (unsigned long)etat->debordements);
    }
    if (etat->sortie_contredit && n >= 0 && (size_t)n < taille) {
        snprintf(texte + n, taille - (size_t)n, " | ATTENTION : la broche OK ne suit pas");
    }
}

const char *console_aide(void) {
    return "Commandes :\n"
           "  etat          la ligne d'état tout de suite\n"
           "  seuil         montrer le seuil de choc\n"
           "  seuil 2,5     changer le seuil (en g), jusqu'au prochain redémarrage\n"
           "  essai chien   figer le programme : le chien de garde doit le redémarrer\n"
           "                (OK coupé un court instant)\n"
           "  aide          cette liste\n";
}
