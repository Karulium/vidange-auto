#include "liaison.h"

#include <stdio.h>
#include <string.h>

#include "fiche.h"

// ------------------------------------------------------------- réponses

typedef struct {
    char texte[LIAISON_LIGNE_MAX];
    size_t n;
    bool deborde;
} texte_t;

static void ajouter(texte_t *t, const char *morceau) {
    size_t n = strlen(morceau);
    if (t->n + n + 1 > sizeof t->texte) {
        t->deborde = true;
        return;
    }
    memcpy(t->texte + t->n, morceau, n + 1);
    t->n += n;
}

static void ajouter_nombre(texte_t *t, const char *nom, uint64_t valeur) {
    // Sans printf pour les nombres de 64 bits (pas toujours connus des petits printf).
    char chiffres[24];
    int i = (int)sizeof chiffres - 1;
    chiffres[i] = '\0';
    do {
        chiffres[--i] = (char)('0' + valeur % 10);
        valeur /= 10;
    } while (valeur > 0);
    ajouter(t, " ");
    ajouter(t, nom);
    ajouter(t, "=");
    ajouter(t, chiffres + i);
}

// L'ordre et les noms des réglages, comme dans pi/reglages/accelerometre.yaml.
typedef enum { NOMBRE_8, NOMBRE_16, NOMBRE_32, AXES } sorte_t;

typedef struct {
    const char *nom;
    size_t place;
    sorte_t sorte;
} champ_t;

static const champ_t CHAMPS[] = {
    {"pleine_echelle_g", offsetof(reglages_t, pleine_echelle_g), NOMBRE_8},
    {"mesures_par_seconde", offsetof(reglages_t, mesures_par_seconde), NOMBRE_16},
    {"axes", offsetof(reglages_t, axes), AXES},
    {"seuil_mg", offsetof(reglages_t, seuil_mg), NOMBRE_32},
    {"duree_min_ms", offsetof(reglages_t, duree_min_ms), NOMBRE_32},
    {"maintien_ms", offsetof(reglages_t, maintien_ms), NOMBRE_32},
    {"constante_fond_ms", offsetof(reglages_t, constante_fond_ms), NOMBRE_32},
    {"sans_mesure_ms", offsetof(reglages_t, sans_mesure_ms), NOMBRE_32},
    {"erreurs_lecture_max", offsetof(reglages_t, erreurs_lecture_max), NOMBRE_32},
    {"figee_ms", offsetof(reglages_t, figee_ms), NOMBRE_32},
    {"reessai_ms", offsetof(reglages_t, reessai_ms), NOMBRE_32},
};
#define NOMBRE_CHAMPS (sizeof CHAMPS / sizeof CHAMPS[0])
static const char NOMS_AXES[] = "xyz";

static void ajouter_reglages(texte_t *t, const reglages_t *r) {
    const uint8_t *octets = (const uint8_t *)r;
    for (size_t i = 0; i < NOMBRE_CHAMPS; i++) {
        const void *valeur = octets + CHAMPS[i].place;
        switch (CHAMPS[i].sorte) {
            case NOMBRE_8:
                ajouter_nombre(t, CHAMPS[i].nom, *(const uint8_t *)valeur);
                break;
            case NOMBRE_16:
                ajouter_nombre(t, CHAMPS[i].nom, *(const uint16_t *)valeur);
                break;
            case NOMBRE_32:
                ajouter_nombre(t, CHAMPS[i].nom, *(const uint32_t *)valeur);
                break;
            case AXES: {
                char axes[4];
                size_t n = 0;
                for (int axe = 0; axe < 3; axe++) {
                    if (r->axes & (1u << axe)) {
                        axes[n++] = NOMS_AXES[axe];
                    }
                }
                axes[n] = '\0';
                ajouter(t, " axes=");
                ajouter(t, axes);
                break;
            }
        }
    }
}

// Lit un nombre entier positif jusqu'au prochain blanc ; rend la suite, ou NULL.
static const char *lire_nombre(const char *texte, uint32_t *valeur) {
    uint64_t v = 0;
    const char *debut = texte;
    for (; *texte >= '0' && *texte <= '9'; texte++) {
        v = v * 10 + (uint64_t)(*texte - '0');
        if (v > UINT32_MAX) {
            return NULL;
        }
    }
    if (texte == debut || (*texte != ' ' && *texte != '\0')) {
        return NULL;
    }
    *valeur = (uint32_t)v;
    return texte;
}

// Lit « nom=valeur nom=valeur… » ; tous les réglages doivent y être, une fois chacun.
static bool lire_reglages(const char *texte, reglages_t *r, char *message, size_t taille) {
    uint8_t *octets = (uint8_t *)r;
    bool vus[NOMBRE_CHAMPS] = {false};
    while (*texte) {
        while (*texte == ' ') {
            texte++;
        }
        if (!*texte) {
            break;
        }
        const char *egal = strchr(texte, '=');
        const champ_t *champ = NULL;
        size_t numero = 0;
        for (; egal && numero < NOMBRE_CHAMPS; numero++) {
            size_t n = strlen(CHAMPS[numero].nom);
            if ((size_t)(egal - texte) == n && strncmp(texte, CHAMPS[numero].nom, n) == 0) {
                champ = &CHAMPS[numero];
                break;
            }
        }
        if (!champ || vus[numero]) {
            snprintf(message, taille, "réglage inconnu ou écrit deux fois");
            return false;
        }
        vus[numero] = true;
        texte = egal + 1;
        void *valeur = octets + champ->place;
        if (champ->sorte == AXES) {
            uint8_t axes = 0;
            for (; *texte && *texte != ' '; texte++) {
                const char *trouve = strchr(NOMS_AXES, *texte);
                if (!trouve || (axes & (1u << (trouve - NOMS_AXES)))) {
                    snprintf(message, taille, "axes : x, y ou z, une fois chacun");
                    return false;
                }
                axes |= (uint8_t)(1u << (trouve - NOMS_AXES));
            }
            *(uint8_t *)valeur = axes;
            continue;
        }
        uint32_t nombre;
        texte = lire_nombre(texte, &nombre);
        if (!texte || (champ->sorte == NOMBRE_8 && nombre > UINT8_MAX) ||
            (champ->sorte == NOMBRE_16 && nombre > UINT16_MAX)) {
            snprintf(message, taille, "%s : nombre mal écrit", champ->nom);
            return false;
        }
        if (champ->sorte == NOMBRE_8) {
            *(uint8_t *)valeur = (uint8_t)nombre;
        } else if (champ->sorte == NOMBRE_16) {
            *(uint16_t *)valeur = (uint16_t)nombre;
        } else {
            *(uint32_t *)valeur = nombre;
        }
    }
    for (size_t i = 0; i < NOMBRE_CHAMPS; i++) {
        if (!vus[i]) {
            snprintf(message, taille, "%s manque", CHAMPS[i].nom);
            return false;
        }
    }
    return true;
}

// Le mot « mot » au début de la question, suivi d'un blanc ou de la fin : rend la suite.
static const char *commande(const char *question, const char *mot) {
    size_t n = strlen(mot);
    if (strncmp(question, mot, n) != 0 || (question[n] != ' ' && question[n] != '\0')) {
        return NULL;
    }
    return question + n + (question[n] == ' ');
}

size_t liaison_repondre(const char *question, const liaison_programme_t *programme,
                        char *reponse, size_t taille) {
    texte_t t = {.n = 0};
    t.texte[0] = '\0';
    liaison_donnees_t d;
    const char *suite;
    if ((suite = commande(question, "ETAT")) && *suite == '\0') {
        programme->lire(programme->contexte, &d, true);
        ajouter(&t, "ETAT");
        ajouter_nombre(&t, "t_ms", d.t_ms);
        ajouter_nombre(&t, "ok", d.etat.ok);
        ajouter_nombre(&t, "choc", d.etat.en_choc);
        ajouter_nombre(&t, "pannes", d.etat.pannes);
        ajouter_nombre(&t, "vues", d.etat.pannes_vues);
        ajouter_nombre(&t, "max_mg", d.etat.niveau_max_mg);
        ajouter_nombre(&t, "chocs", d.etat.chocs);
        ajouter_nombre(&t, "perdues", d.etat.debordements);
        ajouter_nombre(&t, "chien", d.redemarre_par_chien);
        ajouter_nombre(&t, "contredit", d.etat.sortie_contredit);
    } else if ((suite = commande(question, "CHOC"))) {
        uint32_t numero;
        if (!lire_nombre(suite, &numero)) {
            ajouter(&t, "ERREUR numéro de choc mal écrit");
        } else {
            programme->lire(programme->contexte, &d, false);
            choc_t choc;
            ajouter(&t, "CHOC");
            ajouter_nombre(&t, "n", numero);
            if (detecteur_choc(d.historique, d.etat.chocs, numero, &choc)) {
                ajouter_nombre(&t, "t_ms", choc.t_debut_us / 1000);
                ajouter_nombre(&t, "duree_ms", choc.duree_ms);
                ajouter_nombre(&t, "pic_mg", choc.pic_mg);
                ajouter_nombre(&t, "fini", choc.fini);
            } else {
                ajouter(&t, " absent=1");
            }
        }
    } else if ((suite = commande(question, "REGLAGES")) && *suite == '\0') {
        programme->lire(programme->contexte, &d, false);
        ajouter(&t, "REGLAGES");
        ajouter_reglages(&t, &d.reglages);
    } else if ((suite = commande(question, "REGLER"))) {
        reglages_t r = {0};
        char message[96];
        if (lire_reglages(suite, &r, message, sizeof message) &&
            programme->regler(programme->contexte, &r, message, sizeof message)) {
            ajouter(&t, "REGLER ok");
        } else {
            ajouter(&t, "REGLER refuse ");
            ajouter(&t, message);
        }
    } else if ((suite = commande(question, "VERSION")) && *suite == '\0') {
        fiche_t fiche;
        if (programme->fiche && fiche_lire(programme->fiche, &fiche)) {
            char texte[80];
            snprintf(texte, sizeof texte, "VERSION nom=%s taille=%lu crc=%08lX", fiche.nom,
                     (unsigned long)fiche.taille, (unsigned long)fiche.crc);
            ajouter(&t, texte);
        } else {
            ajouter(&t, "VERSION fiche=absente");
        }
    } else if ((suite = commande(question, "CHARGEUR")) && *suite == '\0') {
        programme->vers_chargeur(programme->contexte);
        ajouter(&t, "CHARGEUR redemarre");
    } else {
        ajouter(&t, "ERREUR commande inconnue");
    }
    if (t.deborde) {
        return 0;
    }
    return liaison_trame(t.texte, reponse, taille);
}
