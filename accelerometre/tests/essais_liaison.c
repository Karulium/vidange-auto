#include <string.h>

#include "essai.h"
#include "fiche.h"
#include "liaison.h"

// Un faux programme : ce que la liaison lit, et les réglages qu'elle lui envoie.
typedef struct {
    liaison_donnees_t donnees;
    int lectures_remise;  // lectures avec remise à zéro du « plus fort »
    int reglages_recus;
    reglages_t recus;
    bool refuser;
    int vers_chargeur;
} faux_programme_t;

static void faux_lire(void *contexte, liaison_donnees_t *donnees, bool remettre_max) {
    faux_programme_t *p = contexte;
    *donnees = p->donnees;
    p->lectures_remise += remettre_max;
}

static bool faux_regler(void *contexte, const reglages_t *r, char *message, size_t taille) {
    faux_programme_t *p = contexte;
    if (p->refuser) {
        snprintf(message, taille, "refusés pour l'essai");
        return false;
    }
    p->reglages_recus++;
    p->recus = *r;
    return true;
}

static void faux_vers_chargeur(void *contexte) {
    faux_programme_t *p = contexte;
    p->vers_chargeur++;
}

static reglages_t reglages_essai(void) {
    reglages_t r = {
        .pleine_echelle_g = 8,
        .mesures_par_seconde = 400,
        .axes = AXE_Y | AXE_Z,
        .seuil_mg = 1500,
        .duree_min_ms = 5,
        .maintien_ms = 500,
        .constante_fond_ms = 2000,
        .sans_mesure_ms = 50,
        .erreurs_lecture_max = 3,
        .figee_ms = 1000,
        .reessai_ms = 2000,
    };
    return r;
}

static void faux_preparer(faux_programme_t *p, liaison_programme_t *programme) {
    memset(p, 0, sizeof *p);
    p->donnees.reglages = reglages_essai();
    *programme = (liaison_programme_t){
        .lire = faux_lire,
        .regler = faux_regler,
        .vers_chargeur = faux_vers_chargeur,
        .contexte = p,
        .fiche = NULL,
    };
}

// Rend le texte de la réponse à « question » (sans le contrôle), après avoir vérifié la trame.
static const char *repondre(const liaison_programme_t *programme, const char *question) {
    static char texte[LIAISON_LIGNE_MAX];
    char trame[LIAISON_LIGNE_MAX + 1];
    size_t n = liaison_repondre(question, programme, trame, sizeof trame);
    texte[0] = '\0';
    VERIFIER(n > 6 && trame[n - 1] == '\n' && strlen(trame) == n);
    if (n <= 6) {
        return texte;
    }
    liaison_lecteur_t lecteur = {0};
    bool pret = false;
    for (size_t i = 0; i < n; i++) {
        pret = liaison_recevoir(&lecteur, (uint8_t)trame[i], texte, sizeof texte);
    }
    VERIFIER(pret);
    return texte;
}

static void controle_et_trames(void) {
    // Valeur connue du CRC-16 CCITT (départ 0xFFFF), la même que dans les tests du Pi.
    VERIFIER(liaison_crc("123456789", 9) == 0x29B1);
    char trame[LIAISON_LIGNE_MAX + 1];
    VERIFIER(liaison_trame("ETAT", trame, sizeof trame) == 10);
    char attendu[16];
    snprintf(attendu, sizeof attendu, "ETAT*%04X\n", liaison_crc("ETAT", 4));
    VERIFIER(strcmp(trame, attendu) == 0);
    VERIFIER(liaison_trame("ETAT", trame, 8) == 0);  // pas la place
    char long_texte[LIAISON_TRAME_MAX];
    memset(long_texte, 'x', sizeof long_texte - 1);
    long_texte[sizeof long_texte - 1] = '\0';
    char grande[2 * LIAISON_TRAME_MAX];
    VERIFIER(liaison_trame(long_texte, grande, sizeof grande) == 0);  // trop longue
}

static int recevoir_texte(liaison_lecteur_t *l, const char *octets, char *question) {
    int pretes = 0;
    for (; *octets; octets++) {
        pretes += liaison_recevoir(l, (uint8_t)*octets, question, LIAISON_LIGNE_MAX);
    }
    return pretes;
}

static void reception_des_questions(void) {
    liaison_lecteur_t l = {0};
    char question[LIAISON_LIGNE_MAX];
    char trame[LIAISON_LIGNE_MAX + 1];
    liaison_trame("CHOC 3", trame, sizeof trame);
    VERIFIER(recevoir_texte(&l, trame, question) == 1 && strcmp(question, "CHOC 3") == 0);
    // Avec « \r\n » à la fin.
    trame[strlen(trame) - 1] = '\0';
    strcat(trame, "\r\n");
    VERIFIER(recevoir_texte(&l, trame, question) == 1 && strcmp(question, "CHOC 3") == 0);
    // Contrôle faux, mal formée, ligne vide : oubliées.
    VERIFIER(recevoir_texte(&l, "CHOC 4*0000\n", question) == 0);
    VERIFIER(recevoir_texte(&l, "CHOC 4\n", question) == 0);
    VERIFIER(recevoir_texte(&l, "CHOC 4*12G4\n", question) == 0);
    VERIFIER(recevoir_texte(&l, "\n\n", question) == 0);
    VERIFIER(l.refusees == 3);
    // Trop longue : oubliée, et la suivante est bien lue.
    for (int i = 0; i < LIAISON_TRAME_MAX + 10; i++) {
        liaison_recevoir(&l, 'x', question, sizeof question);
    }
    VERIFIER(!liaison_recevoir(&l, '\n', question, sizeof question));
    liaison_trame("ETAT", trame, sizeof trame);
    VERIFIER(recevoir_texte(&l, trame, question) == 1 && strcmp(question, "ETAT") == 0);
}

static void reponse_etat(void) {
    faux_programme_t p;
    liaison_programme_t programme;
    faux_preparer(&p, &programme);
    p.donnees.t_ms = 5000000000ull;  // plus de 49 jours : 64 bits
    p.donnees.etat = (etat_t){.ok = true, .niveau_max_mg = 84, .chocs = 2, .pannes_vues = 0x10};
    p.donnees.redemarre_par_chien = true;
    VERIFIER(strcmp(repondre(&programme, "ETAT"),
                    "ETAT t_ms=5000000000 ok=1 choc=0 pannes=0 vues=16 max_mg=84 chocs=2 "
                    "perdues=0 chien=1 contredit=0") == 0);
    VERIFIER(p.lectures_remise == 1);
    VERIFIER(strcmp(repondre(&programme, "ETAT 2"), "ERREUR commande inconnue") == 0);
}

static void reponse_choc(void) {
    faux_programme_t p;
    liaison_programme_t programme;
    faux_preparer(&p, &programme);
    p.donnees.etat.chocs = 3;
    p.donnees.historique[2] =
        (choc_t){.numero = 3, .t_debut_us = 7250000, .duree_ms = 12, .pic_mg = 3200, .fini = true};
    VERIFIER(strcmp(repondre(&programme, "CHOC 3"),
                    "CHOC n=3 t_ms=7250 duree_ms=12 pic_mg=3200 fini=1") == 0);
    VERIFIER(strcmp(repondre(&programme, "CHOC 1"), "CHOC n=1 absent=1") == 0);
    VERIFIER(strcmp(repondre(&programme, "CHOC 4"), "CHOC n=4 absent=1") == 0);
    VERIFIER(strcmp(repondre(&programme, "CHOC trois"), "ERREUR numéro de choc mal écrit") == 0);
    VERIFIER(strcmp(repondre(&programme, "CHOC"), "ERREUR numéro de choc mal écrit") == 0);
    VERIFIER(p.lectures_remise == 0);
}

static const char *REGLAGES_ESSAI =
    "pleine_echelle_g=8 mesures_par_seconde=400 axes=yz seuil_mg=1500 duree_min_ms=5 "
    "maintien_ms=500 constante_fond_ms=2000 sans_mesure_ms=50 erreurs_lecture_max=3 "
    "figee_ms=1000 reessai_ms=2000";

static void reponse_reglages_et_regler(void) {
    faux_programme_t p;
    liaison_programme_t programme;
    faux_preparer(&p, &programme);
    char attendu[LIAISON_LIGNE_MAX];
    snprintf(attendu, sizeof attendu, "REGLAGES %s", REGLAGES_ESSAI);
    VERIFIER(strcmp(repondre(&programme, "REGLAGES"), attendu) == 0);

    // Ce que REGLAGES écrit, REGLER le relit à l'identique.
    char question[LIAISON_LIGNE_MAX];
    snprintf(question, sizeof question, "REGLER %s", REGLAGES_ESSAI);
    VERIFIER(strcmp(repondre(&programme, question), "REGLER ok") == 0);
    reglages_t r = reglages_essai();
    VERIFIER(p.reglages_recus == 1 && memcmp(&p.recus, &r, sizeof r) == 0);

    VERIFIER(strcmp(repondre(&programme,
                             "REGLER axes=zx pleine_echelle_g=16 mesures_par_seconde=1344 "
                             "seuil_mg=4000 duree_min_ms=0 maintien_ms=10 constante_fond_ms=100 "
                             "sans_mesure_ms=10 erreurs_lecture_max=1 figee_ms=100 "
                             "reessai_ms=100"),
                    "REGLER ok") == 0);
    VERIFIER(p.recus.axes == (AXE_X | AXE_Z) && p.recus.pleine_echelle_g == 16 &&
             p.recus.mesures_par_seconde == 1344 && p.recus.seuil_mg == 4000);

    p.refuser = true;
    VERIFIER(strcmp(repondre(&programme, question), "REGLER refuse refusés pour l'essai") == 0);
}

static void regler_mal_ecrit(void) {
    faux_programme_t p;
    liaison_programme_t programme;
    faux_preparer(&p, &programme);
    VERIFIER(strcmp(repondre(&programme, "REGLER seuil_mg=1500"),
                    "REGLER refuse pleine_echelle_g manque") == 0);
    VERIFIER(strcmp(repondre(&programme, "REGLER seuil_mg=1500 seuil_mg=1500"),
                    "REGLER refuse réglage inconnu ou écrit deux fois") == 0);
    VERIFIER(strcmp(repondre(&programme, "REGLER vitesse=3"),
                    "REGLER refuse réglage inconnu ou écrit deux fois") == 0);
    VERIFIER(strcmp(repondre(&programme, "REGLER seuil_mg=1,5"),
                    "REGLER refuse seuil_mg : nombre mal écrit") == 0);
    VERIFIER(strcmp(repondre(&programme, "REGLER pleine_echelle_g=300"),
                    "REGLER refuse pleine_echelle_g : nombre mal écrit") == 0);
    VERIFIER(strcmp(repondre(&programme, "REGLER seuil_mg=99999999999"),
                    "REGLER refuse seuil_mg : nombre mal écrit") == 0);
    VERIFIER(strcmp(repondre(&programme, "REGLER axes=yy"),
                    "REGLER refuse axes : x, y ou z, une fois chacun") == 0);
    VERIFIER(strcmp(repondre(&programme, "REGLER axes=w"),
                    "REGLER refuse axes : x, y ou z, une fois chacun") == 0);
    VERIFIER(p.reglages_recus == 0);
}

static void reponse_version_et_chargeur(void) {
    faux_programme_t p;
    liaison_programme_t programme;
    faux_preparer(&p, &programme);
    VERIFIER(strcmp(repondre(&programme, "VERSION"), "VERSION fiche=absente") == 0);
    uint8_t octets[FICHE_TAILLE];
    fiche_t fiche = {.adresse = 0x10009000, .taille = 51828, .crc = 0xAC5112A5, .nom = "574befc"};
    fiche_ecrire(&fiche, octets);
    programme.fiche = octets;
    VERIFIER(strcmp(repondre(&programme, "VERSION"),
                    "VERSION nom=574befc taille=51828 crc=AC5112A5") == 0);
    octets[30] ^= 1;  // fiche abîmée
    VERIFIER(strcmp(repondre(&programme, "VERSION"), "VERSION fiche=absente") == 0);

    VERIFIER(p.vers_chargeur == 0);
    VERIFIER(strcmp(repondre(&programme, "CHARGEUR"), "CHARGEUR redemarre") == 0);
    VERIFIER(p.vers_chargeur == 1);
    VERIFIER(strcmp(repondre(&programme, "CHARGEUR 2"), "ERREUR commande inconnue") == 0);
    VERIFIER(p.vers_chargeur == 1);
}

void essais_liaison(void) {
    LANCER(controle_et_trames);
    LANCER(reception_des_questions);
    LANCER(reponse_etat);
    LANCER(reponse_choc);
    LANCER(reponse_reglages_et_regler);
    LANCER(regler_mal_ecrit);
    LANCER(reponse_version_et_chargeur);
}
