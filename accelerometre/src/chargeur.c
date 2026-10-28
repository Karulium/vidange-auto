// Le chargeur du RP2040 (tâche 16) : il démarre avant le programme, au début de la flash.
//
// Installé une fois à l'établi par l'USB (avec le programme : accelerometre-complet.uf2), il
// n'est jamais réécrit par le fil. Il permet au Pi de mettre le programme à jour par le fil
// série unique, sans démonter le boîtier (questions et réponses : chargeur_protocole.h).
//
// Au démarrage :
// - si le programme a demandé le chargeur (le Pi lui a envoyé CHARGEUR), ou si le programme
//   est absent ou abîmé : il reste dans le chargeur ;
// - sinon il écoute le fil un court instant (« attente_demarrage_ms ») : un Pi qui envoie
//   CHARGEUR à ce moment le garde (secours si le programme ne répond plus), sinon il lance le
//   programme.
// Dans le chargeur, si le programme est bon et que le Pi ne dit plus rien pendant
// « abandon_s », il lance le programme.
//
// Sécurité positive : la sortie « OK » reste à 0 V tout le temps du chargeur. Le voyant
// clignote vite.
#include <string.h>

#include "chargeur_protocole.h"
#include "hardware/flash.h"
#include "hardware/gpio.h"
#include "hardware/resets.h"
#include "hardware/structs/nvic.h"
#include "hardware/structs/scb.h"
#include "hardware/structs/systick.h"
#include "hardware/sync.h"
#include "hardware/watchdog.h"
#include "liaison_trame.h"
#include "pico/stdlib.h"
#include "reglages_genere.h"
#include "un_fil.h"

// Début de la zone (la fiche, puis le programme) depuis le début de la flash.
#define DECALAGE_ZONE (PLAN_ADRESSE_FICHE - XIP_BASE)

static bool effacer(void *contexte, uint32_t decalage) {
    (void)contexte;
    watchdog_update();
    uint32_t etat = save_and_disable_interrupts();
    flash_range_erase(DECALAGE_ZONE + decalage, CHARGEUR_SECTEUR);
    restore_interrupts(etat);
    watchdog_update();
    return true;
}

static bool ecrire(void *contexte, uint32_t decalage, const uint8_t *page) {
    (void)contexte;
    uint32_t etat = save_and_disable_interrupts();
    flash_range_program(DECALAGE_ZONE + decalage, page, CHARGEUR_PAGE);
    restore_interrupts(etat);
    return true;
}

static const chargeur_flash_t flash = {
    .zone = (const uint8_t *)PLAN_ADRESSE_FICHE,
    .taille_zone = PICO_FLASH_SIZE_BYTES - DECALAGE_ZONE,
    .effacer = effacer,
    .ecrire = ecrire,
    .contexte = NULL,
    .adresse_programme = PLAN_ADRESSE_PROGRAMME,
    .broche_fil = REGLAGE_BROCHE_FIL_SERIE,
    .broche_ok = REGLAGE_BROCHE_SORTIE_OK,
};

static chargeur_t chargeur;
static liaison_lecteur_t lecteur;

// Une question complète du Pi, s'il y en a une.
static bool question_recue(char *question, size_t taille) {
    uint8_t octet;
    while (un_fil_lire(&octet)) {
        if (liaison_recevoir(&lecteur, octet, question, taille)) {
            return true;
        }
    }
    return false;
}

// Répond ; rend false si la question n'était pas pour le chargeur.
static bool repondre(const char *question) {
    static char reponse[LIAISON_TRAME_MAX + 1];
    size_t n = chargeur_repondre(&chargeur, question, reponse, sizeof reponse);
    if (n > 0) {
        un_fil_envoyer(reponse, n);
    }
    return n > 0 && strncmp(reponse, "ERREUR", 6) != 0;
}

// Lance le programme comme s'il démarrait seul : il remet lui-même en route horloges et
// périphériques (le Pico SDK le fait à chaque démarrage).
static void __attribute__((noreturn)) lancer_programme(uint32_t chien) {
    // Le programme sait ainsi si le démarrage vient d'un vrai dépassement du chien de garde
    // (watchdog_enable_caused_reboot) : on lui rend ce qu'on a trouvé en démarrant.
    watchdog_hw->scratch[4] = chien;
    gpio_put(REGLAGE_BROCHE_SORTIE_OK, 0);
    systick_hw->csr = 0;
    nvic_hw->icer = 0xFFFFFFFFu;
    nvic_hw->icpr = 0xFFFFFFFFu;
    reset_block(RESETS_RESET_PIO0_BITS);  // rend le fil
    // Le programme garde la copie de boot2 du Pico SDK (256 octets) avant ses vecteurs.
    const uint32_t *vecteurs = (const uint32_t *)(PLAN_ADRESSE_PROGRAMME + 0x100);
    scb_hw->vtor = (uintptr_t)vecteurs;
    __asm volatile("msr msp, %0\n"
                   "bx %1\n"
                   :
                   : "r"(vecteurs[0]), "r"(vecteurs[1]));
    __builtin_unreachable();
}

int main(void) {
    // D'abord la sortie « OK », coupée.
    gpio_init(REGLAGE_BROCHE_SORTIE_OK);
    gpio_put(REGLAGE_BROCHE_SORTIE_OK, 0);
    gpio_set_dir(REGLAGE_BROCHE_SORTIE_OK, GPIO_OUT);
#if REGLAGE_BROCHE_VOYANT >= 0
    gpio_init(REGLAGE_BROCHE_VOYANT);
    gpio_set_dir(REGLAGE_BROCHE_VOYANT, GPIO_OUT);
#endif
    // Le programme a-t-il demandé le chargeur ? (une seule fois)
    bool demande = watchdog_hw->scratch[0] == CHARGEUR_MAGIE &&
                   watchdog_hw->scratch[1] == ~CHARGEUR_MAGIE;
    watchdog_hw->scratch[0] = 0;
    watchdog_hw->scratch[1] = 0;
    uint32_t chien = watchdog_hw->scratch[4];
    watchdog_enable(REGLAGE_CHARGEUR_CHIEN_DE_GARDE_MS, true);

    chargeur_demarrer(&chargeur, &flash);
    un_fil_demarrer(REGLAGE_BROCHE_FIL_SERIE, REGLAGE_VITESSE_FIL_BAUDS);
    static char question[LIAISON_TRAME_MAX];

    if (!demande && chargeur.etat == PROGRAMME_BON) {
        absolute_time_t fin = make_timeout_time_ms(REGLAGE_CHARGEUR_ATTENTE_DEMARRAGE_MS);
        bool garde = false;
        while (!garde && !time_reached(fin)) {
            watchdog_update();
            if (question_recue(question, sizeof question) && strcmp(question, "CHARGEUR") == 0) {
                garde = repondre(question);
            }
        }
        if (!garde) {
            lancer_programme(chien);
        }
    }

    uint64_t derniere_us = time_us_64();
    for (;;) {
        watchdog_update();
        uint64_t t = time_us_64();
#if REGLAGE_BROCHE_VOYANT >= 0
        gpio_put(REGLAGE_BROCHE_VOYANT, (t / 62500) % 2);  // 8 fois par seconde
#endif
        if (question_recue(question, sizeof question) && repondre(question)) {
            derniere_us = t;
            if (chargeur.lancer) {
                lancer_programme(chien);
            }
        }
        if (chargeur.etat == PROGRAMME_BON && !chargeur.ouvert &&
            t - derniere_us > REGLAGE_CHARGEUR_ABANDON_S * 1000000ull) {
            lancer_programme(chien);
        }
    }
}
