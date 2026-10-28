// Essais du chargeur (fiche du programme et questions du Pi), avec une fausse flash.
#include <stdlib.h>
#include <string.h>

#include "chargeur_protocole.h"
#include "essai.h"
#include "fiche.h"
#include "liaison_trame.h"

#define TAILLE_ZONE (16 * 1024)
#define ADRESSE 0x10009000u

// Une fausse flash : effacer met des 0xFF, écrire ne peut que passer des 1 à 0 (comme la vraie).
typedef struct {
    uint8_t octets[TAILLE_ZONE];
    int effacements;
    bool panne;
} fausse_flash_t;

static bool faux_effacer(void *contexte, uint32_t decalage) {
    fausse_flash_t *f = contexte;
    VERIFIER(decalage % CHARGEUR_SECTEUR == 0 && decalage < TAILLE_ZONE);
    if (f->panne) {
        return false;
    }
    memset(f->octets + decalage, 0xFF, CHARGEUR_SECTEUR);
    f->effacements++;
    return true;
}

static bool faux_ecrire(void *contexte, uint32_t decalage, const uint8_t *page) {
    fausse_flash_t *f = contexte;
    VERIFIER(decalage % CHARGEUR_PAGE == 0 && decalage < TAILLE_ZONE);
    for (uint32_t i = 0; i < CHARGEUR_PAGE; i++) {
        f->octets[decalage + i] &= page[i];
    }
    return true;
}

static fausse_flash_t flash;
static chargeur_flash_t vue;
static chargeur_t chargeur;

static void preparer(uint8_t remplissage) {
    memset(&flash, 0, sizeof flash);
    memset(flash.octets, remplissage, sizeof flash.octets);
    vue = (chargeur_flash_t){
        .zone = flash.octets,
        .taille_zone = TAILLE_ZONE,
        .effacer = faux_effacer,
        .ecrire = faux_ecrire,
        .contexte = &flash,
        .adresse_programme = ADRESSE,
        .broche_fil = 0,
        .broche_ok = 2,
    };
    chargeur_demarrer(&chargeur, &vue);
}

// Rend le texte de la réponse à « question » (sans le contrôle), après avoir vérifié la trame.
static const char *repondre(const char *question) {
    static char texte[LIAISON_TRAME_MAX];
    char trame[LIAISON_TRAME_MAX + 1];
    size_t n = chargeur_repondre(&chargeur, question, trame, sizeof trame);
    texte[0] = '\0';
    VERIFIER(n > 6 && trame[n - 1] == '\n' && strlen(trame) == n);
    liaison_lecteur_t lecteur = {0};
    bool pret = false;
    for (size_t i = 0; i < n; i++) {
        pret = liaison_recevoir(&lecteur, (uint8_t)trame[i], texte, sizeof texte);
    }
    VERIFIER(pret);
    return texte;
}

static bool commence(const char *texte, const char *debut) {
    bool bon = strncmp(texte, debut, strlen(debut)) == 0;
    if (!bon) {
        printf("    réponse : %s\n", texte);
    }
    return bon;
}

// Un faux programme de « taille » octets.
static uint8_t *faux_programme(uint32_t taille) {
    uint8_t *p = malloc(taille);
    for (uint32_t i = 0; i < taille; i++) {
        p[i] = (uint8_t)(i * 7 + i / 256);
    }
    return p;
}

static const char *question_ecrire(uint32_t numero, const uint8_t *programme, uint32_t taille) {
    static char question[LIAISON_TRAME_MAX];
    int n = snprintf(question, sizeof question, "ECRIRE %u ", (unsigned)numero);
    uint32_t debut = numero * CHARGEUR_PAGE;
    for (uint32_t i = debut; i < taille && i < debut + CHARGEUR_PAGE; i++) {
        n += snprintf(question + n, sizeof question - (size_t)n, "%02X", programme[i]);
    }
    return question;
}

static const char *question_debut(uint32_t adresse, uint32_t taille, uint32_t crc) {
    static char question[128];
    snprintf(question, sizeof question, "DEBUT adresse=%08X taille=%u crc=%08X nom=essai-1.2",
             (unsigned)adresse, (unsigned)taille, (unsigned)crc);
    return question;
}

// Envoie tout le programme ; rend la réponse à FIN.
static const char *envoyer(const uint8_t *programme, uint32_t taille, uint32_t crc) {
    VERIFIER(strcmp(repondre(question_debut(ADRESSE, taille, crc)), "DEBUT ok") == 0);
    for (uint32_t page = 0; page * CHARGEUR_PAGE < taille; page++) {
        char attendu[32];
        snprintf(attendu, sizeof attendu, "ECRIRE ok n=%u", (unsigned)page);
        VERIFIER(strcmp(repondre(question_ecrire(page, programme, taille)), attendu) == 0);
    }
    return repondre("FIN");
}

static void controle_et_fiche(void) {
    // Valeur connue du CRC-32 (zlib.crc32 de Python donne la même).
    VERIFIER(fiche_crc32(0, (const uint8_t *)"123456789", 9) == 0xCBF43926u);
    VERIFIER(fiche_crc32(fiche_crc32(0, (const uint8_t *)"1234", 4), (const uint8_t *)"56789",
                         5) == 0xCBF43926u);
    fiche_t fiche = {.adresse = ADRESSE, .taille = 1234, .crc = 0xDEADBEEF, .nom = "3f2a9c1"};
    uint8_t octets[FICHE_TAILLE];
    fiche_ecrire(&fiche, octets);
    VERIFIER(memcmp(octets, "ACCL", 4) == 0);
    // Même fiche, même contrôle que fichier_programme.py (test_accelerometre_chargeur.py).
    uint32_t controle = (uint32_t)octets[252] | (uint32_t)octets[253] << 8 |
                        (uint32_t)octets[254] << 16 | (uint32_t)octets[255] << 24;
    VERIFIER(controle == 0x6A3F9EB5u);
    fiche_t relue;
    VERIFIER(fiche_lire(octets, &relue));
    VERIFIER(relue.adresse == ADRESSE && relue.taille == 1234 && relue.crc == 0xDEADBEEF &&
             strcmp(relue.nom, "3f2a9c1") == 0);
    octets[13] ^= 0x40;
    VERIFIER(!fiche_lire(octets, &relue));  // contrôle de la fiche faux

    VERIFIER(fiche_nom_valide("v1.2_essai+3-a"));
    VERIFIER(!fiche_nom_valide(""));
    VERIFIER(!fiche_nom_valide("avec espace"));
    VERIFIER(!fiche_nom_valide("é"));
    VERIFIER(fiche_nom_valide("0123456789012345678901234567890"));    // 31
    VERIFIER(!fiche_nom_valide("01234567890123456789012345678901"));  // 32
}

static void sans_programme(void) {
    preparer(0xFF);
    VERIFIER(chargeur.etat == PROGRAMME_ABSENT);
    VERIFIER(strcmp(repondre("CHARGEUR"),
                    "CHARGEUR pret version=1 fil=0 sortie_ok=2 place=12288 programme=absent") == 0);
    VERIFIER(strcmp(repondre("LANCER"), "LANCER refuse pas de programme bon") == 0);
    VERIFIER(!chargeur.lancer);
    VERIFIER(strcmp(repondre("ETAT"), "ERREUR chargeur") == 0);
    VERIFIER(strcmp(repondre("CHARGEUR x"), "ERREUR chargeur") == 0);

    preparer(0x00);  // ni fiche ni flash effacée
    VERIFIER(chargeur.etat == PROGRAMME_ABIME);
}

static void mise_a_jour_complete(void) {
    preparer(0x00);  // flash sale : chaque secteur doit être effacé avant d'être écrit
    uint32_t taille = 5000;  // 2 secteurs, la dernière page incomplète
    uint8_t *programme = faux_programme(taille);
    uint32_t crc = fiche_crc32(0, programme, taille);
    char attendu[64];
    snprintf(attendu, sizeof attendu, "FIN ok crc=%08X", (unsigned)crc);
    VERIFIER(strcmp(envoyer(programme, taille, crc), attendu) == 0);
    VERIFIER(flash.effacements == 3);  // la fiche et 2 secteurs du programme
    VERIFIER(chargeur.etat == PROGRAMME_BON);
    VERIFIER(memcmp(flash.octets + CHARGEUR_SECTEUR, programme, taille) == 0);
    VERIFIER(flash.octets[CHARGEUR_SECTEUR + taille] == 0xFF);  // fin de la dernière page

    char reponse[160];
    snprintf(reponse, sizeof reponse,
             "CHARGEUR pret version=1 fil=0 sortie_ok=2 place=12288 programme=bon "
             "adresse=10009000 taille=5000 "
             "crc=%08X nom=essai-1.2",
             (unsigned)crc);
    VERIFIER(strcmp(repondre("CHARGEUR"), reponse) == 0);

    // Relu tel quel (copie du programme d'avant).
    const char *lu = repondre("LIRE 1");
    VERIFIER(commence(lu, "LIRE n=1 ") && strlen(lu) == 9 + 512);
    VERIFIER(strncmp(lu + 9, question_ecrire(1, programme, taille) + 9, 512) == 0);
    VERIFIER(commence(repondre("LIRE 48"), "LIRE refuse page hors de la zone"));
    VERIFIER(commence(repondre("LIRE x"), "LIRE refuse numéro"));

    // Au redémarrage, le chargeur le trouve bon.
    chargeur_demarrer(&chargeur, &vue);
    VERIFIER(chargeur.etat == PROGRAMME_BON && strcmp(chargeur.fiche.nom, "essai-1.2") == 0);
    VERIFIER(strcmp(repondre("LANCER"), "LANCER ok") == 0);
    VERIFIER(chargeur.lancer);

    // Un DEBUT efface la fiche : le programme d'avant n'est plus lancé.
    chargeur_demarrer(&chargeur, &vue);
    VERIFIER(strcmp(repondre(question_debut(ADRESSE, taille, crc)), "DEBUT ok") == 0);
    VERIFIER(strcmp(repondre("LANCER"), "LANCER refuse pas de programme bon") == 0);
    chargeur_demarrer(&chargeur, &vue);
    VERIFIER(chargeur.etat == PROGRAMME_ABSENT);
    free(programme);
}

static void pages_redemandees_ou_dans_le_desordre(void) {
    preparer(0xFF);
    uint32_t taille = 700;
    uint8_t *programme = faux_programme(taille);
    uint32_t crc = fiche_crc32(0, programme, taille);
    VERIFIER(commence(repondre(question_ecrire(0, programme, taille)), "ECRIRE refuse pas de DEBUT"));
    VERIFIER(strcmp(repondre(question_debut(ADRESSE, taille, crc)), "DEBUT ok") == 0);
    VERIFIER(strcmp(repondre(question_ecrire(0, programme, taille)), "ECRIRE ok n=0") == 0);
    // Réponse perdue : la même page redemandée est acceptée sans rien réécrire.
    VERIFIER(strcmp(repondre(question_ecrire(0, programme, taille)), "ECRIRE ok n=0") == 0);
    VERIFIER(chargeur.pages == 1);
    // Une autre page 0, ou une page sautée : refusées.
    programme[3] ^= 0xFF;
    VERIFIER(commence(repondre(question_ecrire(0, programme, taille)),
                      "ECRIRE refuse page attendue 1"));
    programme[3] ^= 0xFF;
    VERIFIER(commence(repondre(question_ecrire(2, programme, taille)),
                      "ECRIRE refuse page attendue 1"));
    // Page de la mauvaise longueur, chiffres faux, au-delà de la taille annoncée.
    VERIFIER(commence(repondre("ECRIRE 1 00FF"), "ECRIRE refuse page 1 : 256 octets attendus"));
    VERIFIER(commence(repondre("ECRIRE 3 00"), "ECRIRE refuse page 3 : 0 octets attendus"));
    char question[LIAISON_TRAME_MAX];
    snprintf(question, sizeof question, "%s", question_ecrire(1, programme, taille));
    question[20] = 'G';
    VERIFIER(commence(repondre(question), "ECRIRE refuse chiffres hexadécimaux"));
    VERIFIER(commence(repondre("ECRIRE"), "ECRIRE refuse numéro de page"));
    // FIN trop tôt.
    VERIFIER(commence(repondre("FIN"), "FIN refuse il manque des pages (1 écrites)"));
    VERIFIER(strcmp(repondre(question_ecrire(1, programme, taille)), "ECRIRE ok n=1") == 0);
    VERIFIER(strcmp(repondre(question_ecrire(2, programme, taille)), "ECRIRE ok n=2") == 0);
    VERIFIER(commence(repondre("FIN"), "FIN ok"));
    VERIFIER(commence(repondre("FIN"), "FIN refuse pas de DEBUT"));
    free(programme);
}

static void refus(void) {
    preparer(0xFF);
    uint32_t taille = 600;
    uint8_t *programme = faux_programme(taille);
    uint32_t crc = fiche_crc32(0, programme, taille);
    // Fabriqué pour une autre adresse (sans chargeur, par exemple).
    VERIFIER(commence(repondre(question_debut(0x10000000, taille, crc)),
                      "DEBUT refuse programme fabriqué pour l'adresse 10000000, pas 10009000"));
    VERIFIER(commence(repondre(question_debut(ADRESSE, 12289, crc)),
                      "DEBUT refuse taille de 1 à 12288 octets"));
    VERIFIER(commence(repondre(question_debut(ADRESSE, 0, crc)), "DEBUT refuse taille"));
    VERIFIER(commence(repondre("DEBUT adresse=10009000 taille=600 crc=1"),
                      "DEBUT refuse il faut adresse, taille, crc et nom"));
    VERIFIER(commence(repondre("DEBUT adresse=10009000 taille=600 crc=1 nom=é"),
                      "DEBUT refuse il faut"));
    VERIFIER(flash.effacements == 0);  // rien n'a été touché

    // Contrôle faux à la fin : pas de fiche, rien n'est lancé.
    VERIFIER(commence(envoyer(programme, taille, crc ^ 1), "FIN refuse contrôle faux"));
    VERIFIER(chargeur.etat == PROGRAMME_ABSENT);
    VERIFIER(strcmp(repondre("LANCER"), "LANCER refuse pas de programme bon") == 0);

    // Effacement raté.
    flash.panne = true;
    VERIFIER(commence(repondre(question_debut(ADRESSE, taille, crc)),
                      "DEBUT refuse effacement raté"));
    free(programme);
}

static void programme_abime(void) {
    preparer(0xFF);
    uint32_t taille = 300;
    uint8_t *programme = faux_programme(taille);
    uint32_t crc = fiche_crc32(0, programme, taille);
    VERIFIER(commence(envoyer(programme, taille, crc), "FIN ok"));
    flash.octets[CHARGEUR_SECTEUR + 10] ^= 0x01;  // un bit perdu dans le programme
    chargeur_demarrer(&chargeur, &vue);
    VERIFIER(chargeur.etat == PROGRAMME_ABIME);
    VERIFIER(commence(repondre("CHARGEUR"),
                      "CHARGEUR pret version=1 fil=0 sortie_ok=2 place=12288 programme=abime "
                      "adresse=10009000 taille=300"));
    VERIFIER(strcmp(repondre("LANCER"), "LANCER refuse pas de programme bon") == 0);
    free(programme);
}

void essais_chargeur(void) {
    LANCER(controle_et_fiche);
    LANCER(sans_programme);
    LANCER(mise_a_jour_complete);
    LANCER(pages_redemandees_ou_dans_le_desordre);
    LANCER(refus);
    LANCER(programme_abime);
}
