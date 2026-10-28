// Programme du RP2040 de l'accéléromètre (chariot Z) : mesure des chocs et signal « OK ».
//
// Cœur 0 : la mesure et la sortie « OK », rien d'autre (il ne doit jamais attendre).
// Cœur 1 : la fenêtre texte sur l'USB (essais à l'établi). S'il se bloque, la mesure continue.
//
// Sécurité positive : la sortie « OK » est à 3,3 V seulement quand le détecteur le dit.
// Au démarrage, pendant un redémarrage par le chien de garde ou sans courant, la broche
// n'est pas commandée : une résistance de tirage vers la masse doit alors la tenir à 0 V
// (voir accelerometre/essai-etabli.md).
#include <stdio.h>

#include "console.h"
#include "detecteur.h"
#include "hardware/gpio.h"
#include "hardware/i2c.h"
#include "hardware/watchdog.h"
#include "lis3dh.h"
#include "pico/critical_section.h"
#include "pico/multicore.h"
#include "pico/stdio_usb.h"
#include "pico/stdlib.h"
#include "reglages.h"
#include "reglages_genere.h"

#define I2C (REGLAGE_BLOC_I2C ? i2c1 : i2c0)

// ------------------------------------------------- partagé entre les deux cœurs

static critical_section_t verrou;
static etat_t partage;               // écrit par le cœur 0, lu par le cœur 1
static uint32_t seuil_demande_mg;    // 0 : rien de demandé
static int seuil_reponse;            // 1 : accepté, -1 : refusé, 0 : pas encore lu
static volatile bool essai_chien;    // le cœur 1 demande de figer le cœur 0
static bool redemarre_par_chien;     // ce démarrage vient du chien de garde
static char message_reglages[96];   // réglages faux : pourquoi

// --------------------------------------------------------------- bus I2C

static int i2c_ecrire(void *contexte, uint8_t adresse, const uint8_t *octets, size_t n) {
    (void)contexte;
    int fait = i2c_write_timeout_us(I2C, adresse, octets, n, false, 1000 + 100 * n);
    return fait == (int)n ? 0 : -1;
}

static int i2c_lire(void *contexte, uint8_t adresse, uint8_t registre, uint8_t *octets,
                    size_t n) {
    (void)contexte;
    if (i2c_write_timeout_us(I2C, adresse, &registre, 1, true, 1000) != 1) {
        return -1;
    }
    int fait = i2c_read_timeout_us(I2C, adresse, octets, n, false, 1000 + 100 * n);
    return fait == (int)n ? 0 : -1;
}

static void attendre_ms(void *contexte, uint32_t ms) {
    (void)contexte;
    for (uint32_t i = 0; i < ms; i++) {
        watchdog_update();
        sleep_ms(1);
    }
    watchdog_update();
}

static const bus_i2c_t bus = {i2c_ecrire, i2c_lire, attendre_ms, NULL};

// Remet le bus en route : un appareil qui tient SDA à 0 est libéré par 9 coups d'horloge.
static void preparer_bus(void) {
    i2c_deinit(I2C);
    gpio_init(REGLAGE_BROCHE_I2C_SCL);
    gpio_set_dir(REGLAGE_BROCHE_I2C_SCL, GPIO_OUT);
    for (int i = 0; i < 9; i++) {
        gpio_put(REGLAGE_BROCHE_I2C_SCL, 0);
        sleep_us(5);
        gpio_put(REGLAGE_BROCHE_I2C_SCL, 1);
        sleep_us(5);
    }
    i2c_init(I2C, REGLAGE_FREQUENCE_I2C_HZ);
    gpio_set_function(REGLAGE_BROCHE_I2C_SDA, GPIO_FUNC_I2C);
    gpio_set_function(REGLAGE_BROCHE_I2C_SCL, GPIO_FUNC_I2C);
    gpio_pull_up(REGLAGE_BROCHE_I2C_SDA);
    gpio_pull_up(REGLAGE_BROCHE_I2C_SCL);
}

// ------------------------------------------------------------- voyant

static void allumer_voyant(bool ok, bool panne, uint64_t t_us) {
#if REGLAGE_BROCHE_VOYANT >= 0
    // Allumé : OK. Éteint : choc ou démarrage. Clignote (2 fois par seconde) : panne.
    bool allume = panne ? (t_us / 250000) % 2 == 0 : ok;
    gpio_put(REGLAGE_BROCHE_VOYANT, allume);
#else
    (void)ok;
    (void)panne;
    (void)t_us;
#endif
}

// -------------------------------------------------------------- cœur 1

static void afficher_etat(void) {
    etat_t copie;
    critical_section_enter_blocking(&verrou);
    copie = partage;
    partage.niveau_max_mg = 0;
    critical_section_exit(&verrou);
    char ligne[200];
    console_ligne_etat(&copie, ligne, sizeof ligne);
    printf("%s\n", ligne);
}

static void afficher_debut(void) {
    etat_t copie;
    critical_section_enter_blocking(&verrou);
    copie = partage;
    critical_section_exit(&verrou);
    printf("\nAccéléromètre du chariot Z (RP2040 + LIS3DH)%s\n",
           REGLAGE_EXEMPLE ? " — réglages d'EXEMPLE" : "");
    if (redemarre_par_chien) {
        printf("ATTENTION : ce démarrage vient du chien de garde (le programme s'était figé).\n");
    }
    if (message_reglages[0]) {
        printf("RÉGLAGES FAUX : %s. OK ne sera jamais donné.\n", message_reglages);
    }
    printf("Autotest du capteur, écarts x y z : %d %d %d (bon : de 17 à 360)\n",
           copie.autotest_ecart[0], copie.autotest_ecart[1], copie.autotest_ecart[2]);
    printf("Tapez « aide » pour la liste des commandes.\n");
}

static void traiter_ligne(const char *ligne) {
    uint32_t seuil_mg;
    switch (console_lire(ligne, &seuil_mg)) {
        case COMMANDE_VIDE:
            break;
        case COMMANDE_AIDE:
            afficher_debut();
            printf("%s", console_aide());
            break;
        case COMMANDE_ETAT:
            afficher_etat();
            break;
        case COMMANDE_SEUIL:
            if (seuil_mg) {
                critical_section_enter_blocking(&verrou);
                seuil_reponse = 0;
                seuil_demande_mg = seuil_mg;
                critical_section_exit(&verrou);
                int reponse = 0;
                // Le cœur 0 répond au tour suivant (au pire après une vérification du capteur).
                for (int i = 0; i < 1000 && reponse == 0; i++) {
                    sleep_ms(1);
                    critical_section_enter_blocking(&verrou);
                    reponse = seuil_reponse;
                    critical_section_exit(&verrou);
                }
                if (reponse > 0) {
                    printf("Seuil changé (jusqu'au prochain redémarrage).\n");
                } else if (reponse < 0) {
                    printf("Seuil refusé (plus que 0 et moins que la pleine échelle du "
                           "capteur).\n");
                } else {
                    printf("Pas de réponse du programme de mesure.\n");
                }
            }
            afficher_etat();
            break;
        case COMMANDE_ESSAI_CHIEN:
            printf("Le programme de mesure se fige : le chien de garde doit le redémarrer.\n");
            sleep_ms(50);
            essai_chien = true;
            break;
        case COMMANDE_INCONNUE:
            printf("Commande inconnue. Tapez « aide ».\n");
            break;
    }
}

static void coeur1(void) {
    stdio_init_all();
    char ligne[64];
    size_t n = 0;
    bool etait_branche = false;
    uint64_t prochain_us = time_us_64();
    for (;;) {
        // Quand une fenêtre texte s'ouvre sur le PC, on y redit qui on est.
        bool branche = stdio_usb_connected();
        if (branche && !etait_branche) {
            sleep_ms(200);
            afficher_debut();
        }
        etait_branche = branche;

        int c = getchar_timeout_us(10000);
        if (c == '\r' || c == '\n') {
            ligne[n] = '\0';
            n = 0;
            traiter_ligne(ligne);
        } else if (c >= 0 && n + 1 < sizeof ligne) {
            ligne[n++] = (char)c;
        }
        if (time_us_64() >= prochain_us) {
            prochain_us += REGLAGE_PERIODE_AFFICHAGE_MS * 1000ull;
            if (branche) {
                afficher_etat();
            }
        }
    }
}

// -------------------------------------------------------------- cœur 0

int main(void) {
    // D'abord la sortie « OK », coupée.
    gpio_init(REGLAGE_BROCHE_SORTIE_OK);
    gpio_put(REGLAGE_BROCHE_SORTIE_OK, 0);
    gpio_set_dir(REGLAGE_BROCHE_SORTIE_OK, GPIO_OUT);
#if REGLAGE_BROCHE_VOYANT >= 0
    gpio_init(REGLAGE_BROCHE_VOYANT);
    gpio_set_dir(REGLAGE_BROCHE_VOYANT, GPIO_OUT);
#endif
    // Seulement un vrai dépassement du chien de garde (pas le redémarrage après chargement).
    redemarre_par_chien = watchdog_enable_caused_reboot();
    watchdog_enable(REGLAGE_CHIEN_DE_GARDE_MS, true);

    reglages_t reglages = reglages_depart();
    reglages_verifier(&reglages, message_reglages, sizeof message_reglages);
    detecteur_t detecteur;
    detecteur_demarrer(&detecteur, &reglages);

    critical_section_init(&verrou);
    multicore_launch_core1(coeur1);

    lis3dh_t capteur = {0};
    uint32_t debordements = 0;
    bool ok = false;
    for (;;) {
        uint64_t t = time_us_64();
        if (detecteur_verification_due(&detecteur, t)) {
            ok = false;
            gpio_put(REGLAGE_BROCHE_SORTIE_OK, 0);
            preparer_bus();
            lis3dh_resultat_t r =
                lis3dh_demarrer(&capteur, &bus, REGLAGE_ADRESSE_LIS3DH,
                                reglages.pleine_echelle_g, reglages.mesures_par_seconde);
            uint32_t panne = 0;
            if (r == LIS3DH_ABSENT || r == LIS3DH_MAUVAISE_PUCE) {
                panne = PANNE_CAPTEUR;
            } else if (r == LIS3DH_AUTOTEST_RATE) {
                panne = PANNE_AUTOTEST;
            } else if (r != LIS3DH_BIEN) {
                panne = PANNE_LECTURE;
            }
            detecteur_verification_faite(&detecteur, time_us_64(), panne);
        } else if (detecteur.pret) {
            int32_t mg[3];
            bool nouvelle;
            bool debordement;
            if (lis3dh_lire(&capteur, mg, &nouvelle, &debordement) != LIS3DH_BIEN) {
                detecteur_erreur_lecture(&detecteur, t);
            } else if (nouvelle) {
                debordements += debordement;
                detecteur_mesure(&detecteur, t, mg);
            }
        }
        detecteur_surveiller(&detecteur, t);

        // Relire la broche (commandée au tour d'avant) : si elle ne suit pas, elle est en
        // court-circuit (dit à la console).
        bool contredit = gpio_get(REGLAGE_BROCHE_SORTIE_OK) != ok;
        ok = detecteur_ok(&detecteur);
        gpio_put(REGLAGE_BROCHE_SORTIE_OK, ok);
        allumer_voyant(ok, detecteur.pannes != 0, t);

        critical_section_enter_blocking(&verrou);
        partage.ok = ok;
        partage.en_choc = detecteur.en_choc;
        partage.pannes = detecteur.pannes;
        partage.pannes_vues = detecteur.pannes_vues;
        if (detecteur.niveau_mg > partage.niveau_max_mg) {
            partage.niveau_max_mg = detecteur.niveau_mg;
        }
        partage.chocs = detecteur.chocs;
        partage.pic_choc_mg = detecteur.pic_choc_mg;
        partage.seuil_mg = detecteur.reglages.seuil_mg;
        partage.debordements = debordements;
        partage.sortie_contredit = contredit;
        for (int axe = 0; axe < 3; axe++) {
            partage.autotest_ecart[axe] = capteur.autotest_ecart[axe];
        }
        if (seuil_demande_mg) {
            seuil_reponse = detecteur_changer_seuil(&detecteur, seuil_demande_mg) ? 1 : -1;
            seuil_demande_mg = 0;
        }
        critical_section_exit(&verrou);

        if (essai_chien) {
            for (;;) {
                tight_loop_contents();  // plus de watchdog_update : redémarrage attendu
            }
        }
        watchdog_update();
    }
}
