#include "chargeur_protocole.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "liaison_trame.h"

uint32_t chargeur_place(const chargeur_flash_t *flash) {
    return flash->taille_zone > CHARGEUR_SECTEUR ? flash->taille_zone - CHARGEUR_SECTEUR : 0;
}

programme_etat_t chargeur_examiner(const chargeur_flash_t *flash, fiche_t *fiche) {
    if (!fiche_lire(flash->zone, fiche)) {
        // Fiche effacée (que des 0xFF) : pas de programme. Sinon : abîmée.
        for (size_t i = 0; i < FICHE_TAILLE; i++) {
            if (flash->zone[i] != 0xFF) {
                return PROGRAMME_ABIME;
            }
        }
        return PROGRAMME_ABSENT;
    }
    if (fiche->adresse != flash->adresse_programme || fiche->taille == 0 ||
        fiche->taille > chargeur_place(flash) ||
        fiche_crc32(0, flash->zone + CHARGEUR_SECTEUR, fiche->taille) != fiche->crc) {
        return PROGRAMME_ABIME;
    }
    return PROGRAMME_BON;
}

void chargeur_demarrer(chargeur_t *c, const chargeur_flash_t *flash) {
    memset(c, 0, sizeof *c);
    c->flash = flash;
    c->etat = chargeur_examiner(flash, &c->fiche);
}

// ------------------------------------------------------------- lecture des questions

// Le mot « mot » au début de la question, suivi d'un blanc ou de la fin : rend la suite.
static const char *commande(const char *question, const char *mot) {
    size_t n = strlen(mot);
    if (strncmp(question, mot, n) != 0 || (question[n] != ' ' && question[n] != '\0')) {
        return NULL;
    }
    return question + n + (question[n] == ' ');
}

static int chiffre(char c, unsigned base) {
    int v = -1;
    if (c >= '0' && c <= '9') v = c - '0';
    if (c >= 'A' && c <= 'F') v = c - 'A' + 10;
    if (c >= 'a' && c <= 'f') v = c - 'a' + 10;
    return v >= 0 && (unsigned)v < base ? v : -1;
}

// Lit un nombre (base 10 ou 16) jusqu'au prochain blanc ; rend la suite, ou NULL.
static const char *lire_nombre(const char *texte, unsigned base, uint32_t *valeur) {
    uint64_t v = 0;
    const char *debut = texte;
    for (int c; (c = chiffre(*texte, base)) >= 0; texte++) {
        v = v * base + (uint64_t)c;
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

// La valeur de « nom=… » dans « texte » (jusqu'au prochain blanc), copiée dans « valeur ».
static bool champ(const char *texte, const char *nom, char *valeur, size_t taille) {
    size_t n = strlen(nom);
    for (const char *p = texte; *p;) {
        while (*p == ' ') {
            p++;
        }
        size_t longueur = strcspn(p, " ");
        if (longueur > n && strncmp(p, nom, n) == 0 && p[n] == '=') {
            size_t v = longueur - n - 1;
            if (v + 1 > taille) {
                return false;
            }
            memcpy(valeur, p + n + 1, v);
            valeur[v] = '\0';
            return true;
        }
        p += longueur;
    }
    return false;
}

static bool champ_nombre(const char *texte, const char *nom, unsigned base, uint32_t *valeur) {
    char v[12];
    return champ(texte, nom, v, sizeof v) && lire_nombre(v, base, valeur) != NULL;
}

// ------------------------------------------------------------- réponses

typedef struct {
    char *texte;
    size_t taille;
    size_t n;
    bool deborde;
} reponse_t;

static void ajouter(reponse_t *r, const char *format, ...) __attribute__((format(printf, 2, 3)));

static void ajouter(reponse_t *r, const char *format, ...) {
    va_list args;
    va_start(args, format);
    int n = vsnprintf(r->texte + r->n, r->taille - r->n, format, args);
    va_end(args);
    if (n < 0 || (size_t)n >= r->taille - r->n) {
        r->deborde = true;
        return;
    }
    r->n += (size_t)n;
}

static void ajouter_hexa(reponse_t *r, const uint8_t *octets, size_t n) {
    static const char CHIFFRES[] = "0123456789ABCDEF";
    if (r->n + 2 * n + 1 > r->taille) {
        r->deborde = true;
        return;
    }
    for (size_t i = 0; i < n; i++) {
        r->texte[r->n++] = CHIFFRES[octets[i] >> 4];
        r->texte[r->n++] = CHIFFRES[octets[i] & 0x0F];
    }
    r->texte[r->n] = '\0';
}

static const char *NOMS_ETATS[] = {"bon", "absent", "abime"};

static void repondre_chargeur(chargeur_t *c, reponse_t *r) {
    const chargeur_flash_t *f = c->flash;
    ajouter(r, "CHARGEUR pret version=%d fil=%u sortie_ok=%u place=%lu programme=%s",
            CHARGEUR_VERSION, f->broche_fil, f->broche_ok,
            (unsigned long)chargeur_place(f), NOMS_ETATS[c->etat]);
    fiche_t fiche;
    if (!c->ouvert && fiche_lire(f->zone, &fiche)) {
        ajouter(r, " adresse=%08lX taille=%lu crc=%08lX nom=%s", (unsigned long)fiche.adresse,
                (unsigned long)fiche.taille, (unsigned long)fiche.crc, fiche.nom);
    }
}

static void repondre_debut(chargeur_t *c, const char *suite, reponse_t *r) {
    fiche_t fiche = {0};
    if (!champ_nombre(suite, "adresse", 16, &fiche.adresse) ||
        !champ_nombre(suite, "taille", 10, &fiche.taille) ||
        !champ_nombre(suite, "crc", 16, &fiche.crc) ||
        !champ(suite, "nom", fiche.nom, sizeof fiche.nom) || !fiche_nom_valide(fiche.nom)) {
        ajouter(r, "DEBUT refuse il faut adresse, taille, crc et nom");
        return;
    }
    if (fiche.adresse != c->flash->adresse_programme) {
        ajouter(r, "DEBUT refuse programme fabriqué pour l'adresse %08lX, pas %08lX",
                (unsigned long)fiche.adresse, (unsigned long)c->flash->adresse_programme);
        return;
    }
    if (fiche.taille == 0 || fiche.taille > chargeur_place(c->flash)) {
        ajouter(r, "DEBUT refuse taille de 1 à %lu octets",
                (unsigned long)chargeur_place(c->flash));
        return;
    }
    // D'abord la fiche : un programme à moitié écrit ne sera jamais lancé.
    c->ouvert = false;
    if (!c->flash->effacer(c->flash->contexte, 0)) {
        c->etat = chargeur_examiner(c->flash, &c->fiche);
        ajouter(r, "DEBUT refuse effacement raté");
        return;
    }
    c->etat = PROGRAMME_ABSENT;
    c->fiche = fiche;
    c->ouvert = true;
    c->pages = 0;
    ajouter(r, "DEBUT ok");
}

static bool page_identique(const chargeur_t *c, uint32_t numero, const uint8_t *page) {
    return memcmp(c->flash->zone + CHARGEUR_SECTEUR + numero * CHARGEUR_PAGE, page,
                  CHARGEUR_PAGE) == 0;
}

static void repondre_ecrire(chargeur_t *c, const char *suite, reponse_t *r) {
    uint32_t numero;
    const char *hexa = suite ? lire_nombre(suite, 10, &numero) : NULL;
    if (!hexa || *hexa != ' ') {
        ajouter(r, "ECRIRE refuse numéro de page mal écrit");
        return;
    }
    hexa++;
    if (!c->ouvert) {
        ajouter(r, "ECRIRE refuse pas de DEBUT");
        return;
    }
    // Les octets de cette page (la dernière peut être plus courte).
    uint32_t debut = numero * CHARGEUR_PAGE;
    uint32_t attendus = 0;
    if (numero < (c->fiche.taille + CHARGEUR_PAGE - 1) / CHARGEUR_PAGE) {
        attendus = c->fiche.taille - debut < CHARGEUR_PAGE ? c->fiche.taille - debut
                                                           : CHARGEUR_PAGE;
    }
    uint8_t page[CHARGEUR_PAGE];
    memset(page, 0xFF, sizeof page);
    size_t n = strlen(hexa);
    if (attendus == 0 || n != 2 * attendus) {
        ajouter(r, "ECRIRE refuse page %lu : %lu octets attendus", (unsigned long)numero,
                (unsigned long)attendus);
        return;
    }
    for (size_t i = 0; i < attendus; i++) {
        int fort = chiffre(hexa[2 * i], 16);
        int faible = chiffre(hexa[2 * i + 1], 16);
        if (fort < 0 || faible < 0) {
            ajouter(r, "ECRIRE refuse chiffres hexadécimaux mal écrits");
            return;
        }
        page[i] = (uint8_t)(fort << 4 | faible);
    }
    if (numero + 1 == c->pages && page_identique(c, numero, page)) {
        ajouter(r, "ECRIRE ok n=%lu", (unsigned long)numero);  // redemandée : déjà écrite
        return;
    }
    if (numero != c->pages) {
        ajouter(r, "ECRIRE refuse page attendue %lu", (unsigned long)c->pages);
        return;
    }
    uint32_t decalage = CHARGEUR_SECTEUR + debut;
    bool bon = decalage % CHARGEUR_SECTEUR != 0 || c->flash->effacer(c->flash->contexte, decalage);
    bon = bon && c->flash->ecrire(c->flash->contexte, decalage, page);
    if (!bon || !page_identique(c, numero, page)) {
        ajouter(r, "ECRIRE refuse écriture ratée");
        return;
    }
    c->pages++;
    ajouter(r, "ECRIRE ok n=%lu", (unsigned long)numero);
}

static void repondre_fin(chargeur_t *c, reponse_t *r) {
    if (!c->ouvert) {
        ajouter(r, "FIN refuse pas de DEBUT");
        return;
    }
    if (c->pages * CHARGEUR_PAGE < c->fiche.taille) {
        ajouter(r, "FIN refuse il manque des pages (%lu écrites)", (unsigned long)c->pages);
        return;
    }
    uint32_t crc = fiche_crc32(0, c->flash->zone + CHARGEUR_SECTEUR, c->fiche.taille);
    if (crc != c->fiche.crc) {
        c->ouvert = false;
        ajouter(r, "FIN refuse contrôle faux (%08lX au lieu de %08lX)", (unsigned long)crc,
                (unsigned long)c->fiche.crc);
        return;
    }
    uint8_t page[CHARGEUR_PAGE];
    memset(page, 0xFF, sizeof page);
    fiche_ecrire(&c->fiche, page);
    c->ouvert = false;
    c->flash->ecrire(c->flash->contexte, 0, page);
    c->etat = chargeur_examiner(c->flash, &c->fiche);
    if (c->etat != PROGRAMME_BON) {
        ajouter(r, "FIN refuse fiche mal écrite");
        return;
    }
    ajouter(r, "FIN ok crc=%08lX", (unsigned long)crc);
}

static void repondre_lire(chargeur_t *c, const char *suite, reponse_t *r) {
    uint32_t numero;
    if (!lire_nombre(suite, 10, &numero)) {
        ajouter(r, "LIRE refuse numéro de page mal écrit");
        return;
    }
    if (numero >= chargeur_place(c->flash) / CHARGEUR_PAGE) {
        ajouter(r, "LIRE refuse page hors de la zone");
        return;
    }
    ajouter(r, "LIRE n=%lu ", (unsigned long)numero);
    ajouter_hexa(r, c->flash->zone + CHARGEUR_SECTEUR + numero * CHARGEUR_PAGE, CHARGEUR_PAGE);
}

size_t chargeur_repondre(chargeur_t *c, const char *question, char *reponse, size_t taille) {
    char texte[LIAISON_TRAME_MAX];
    reponse_t r = {texte, sizeof texte - 6, 0, false};  // 6 : place du contrôle
    texte[0] = '\0';
    const char *suite;
    if ((suite = commande(question, "CHARGEUR")) && *suite == '\0') {
        repondre_chargeur(c, &r);
    } else if ((suite = commande(question, "DEBUT"))) {
        repondre_debut(c, suite, &r);
    } else if ((suite = commande(question, "ECRIRE"))) {
        repondre_ecrire(c, suite, &r);
    } else if ((suite = commande(question, "FIN")) && *suite == '\0') {
        repondre_fin(c, &r);
    } else if ((suite = commande(question, "LIRE"))) {
        repondre_lire(c, suite, &r);
    } else if ((suite = commande(question, "LANCER")) && *suite == '\0') {
        if (c->etat == PROGRAMME_BON && !c->ouvert) {
            c->lancer = true;
            ajouter(&r, "LANCER ok");
        } else {
            ajouter(&r, "LANCER refuse pas de programme bon");
        }
    } else {
        ajouter(&r, "ERREUR chargeur");
    }
    if (r.deborde) {
        return 0;
    }
    return liaison_trame(texte, reponse, taille);
}
