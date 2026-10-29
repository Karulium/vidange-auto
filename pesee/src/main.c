// Programme du RP2040 d'une carte de pesée (griffe, préhension ou plateau du remplissage) :
// lit son HX711 et répond au Pi sur le bus RS485 des pesées (Modbus RTU).
//
// Cœur 0 : le HX711 et le bus RS485, rien d'autre (il ne doit jamais attendre).
// Cœur 1 : la fenêtre texte sur l'USB (essais à l'établi). S'il se bloque, la pesée continue.
//
// Le même programme sert aux 3 cartes ; seule l'adresse sur le bus change. Elle vient de
// docs/entrees-sorties.yaml (« adresse » de chaque signal de pesée) : un fichier .uf2 par carte
// (voir README.md).
//
// Le bus : un émetteur-récepteur RS485 3,3 V (MAX3485, SP3485...) dont les entrées DE et /RE sont
// reliées ensemble à la broche « rs485_sens » : à 1 pour parler, à 0 (repos) pour écouter. La
// carte ne parle que pour répondre à une question qui lui est adressée.
#include <stdio.h>

#include "hardware/gpio.h"
#include "hardware/sync.h"
#include "hardware/uart.h"
#include "hardware/watchdog.h"
#include "hx711.h"
#include "mesures.h"
#include "modbus.h"
#include "pico/critical_section.h"
#include "pico/multicore.h"
#include "pico/stdio_usb.h"
#include "pico/stdlib.h"
#include "reglages_genere.h"

#define UART (REGLAGE_BLOC_UART ? uart1 : uart0)

// ------------------------------------------------- partagé entre les deux cœurs

typedef struct {
    int32_t brut;
    uint16_t par_seconde;
    uint16_t trames_abimees;
    uint32_t questions;  // questions pour cette carte, depuis le démarrage
    bool muet;
} instantane_t;

static critical_section_t verrou;
static instantane_t partage;  // écrit par le cœur 0, lu par le cœur 1
static bool redemarre_par_chien;

// ------------------------------------------------------------------- HX711

static bool lire_dt(void *contexte) {
    (void)contexte;
    return gpio_get(REGLAGE_BROCHE_HX711_DT);
}

static void ecrire_sck(void *contexte, bool haut) {
    (void)contexte;
    gpio_put(REGLAGE_BROCHE_HX711_SCK, haut);
}

static void attendre_us(void *contexte, uint32_t us) {
    (void)contexte;
    busy_wait_us_32(us);
}

static const broches_hx711_t hx711 = {lire_dt, ecrire_sck, attendre_us, NULL};

// ------------------------------------------------------------------- RS485

static void envoyer(const uint8_t *octets, size_t n) {
    // Laisser l'adaptateur du Pi repasser en écoute après sa question.
    busy_wait_us_32(REGLAGE_DELAI_AVANT_REPONSE_US);
    gpio_put(REGLAGE_BROCHE_RS485_SENS, 1);
    uart_write_blocking(UART, octets, n);
    // Attendre que le dernier bit soit sorti avant de lâcher le bus.
    uart_tx_wait_blocking(UART);
    gpio_put(REGLAGE_BROCHE_RS485_SENS, 0);
    // Un émetteur-récepteur qui s'entend parler : l'écho est oublié.
    while (uart_is_readable(UART)) {
        (void)uart_getc(UART);
    }
}

// ------------------------------------------------------------------- voyant

static void allumer_voyant(bool muet, uint64_t t_us) {
#if REGLAGE_BROCHE_VOYANT >= 0
    // Allumé : le HX711 mesure. Clignote (2 fois par seconde) : HX711 muet.
    bool allume = muet ? (t_us / 250000) % 2 == 0 : true;
    gpio_put(REGLAGE_BROCHE_VOYANT, allume);
#else
    (void)muet;
    (void)t_us;
#endif
}

// -------------------------------------------------------------- cœur 1

static void afficher_debut(void) {
    printf("Carte de pesée « %s », adresse %d sur le bus, %d bauds.\n", REGLAGE_NOM,
           REGLAGE_ADRESSE, REGLAGE_VITESSE_BAUDS);
    printf("Version : %s.%s\n", REGLAGE_VERSION,
           REGLAGE_EXEMPLE ? " Réglages d'EXEMPLE (pi/reglages/pesees.yaml)." : "");
    if (redemarre_par_chien) {
        printf("ATTENTION : la carte a redémarré par son chien de garde (programme figé).\n");
    }
}

static void coeur1(void) {
    stdio_init_all();
    bool etait_branche = false;
    uint32_t questions_avant = 0;
    uint64_t prochain_us = time_us_64();
    for (;;) {
        // Quand une fenêtre texte s'ouvre sur le PC, on y redit qui on est.
        bool branche = stdio_usb_connected();
        if (branche && !etait_branche) {
            sleep_ms(200);
            afficher_debut();
        }
        etait_branche = branche;
        sleep_ms(10);
        if (time_us_64() < prochain_us) {
            continue;
        }
        prochain_us += REGLAGE_PERIODE_AFFICHAGE_MS * 1000ull;
        instantane_t copie;
        critical_section_enter_blocking(&verrou);
        copie = partage;
        critical_section_exit(&verrou);
        uint32_t questions = copie.questions - questions_avant;
        questions_avant = copie.questions;
        if (branche) {
            printf("brut %ld | %u mesures/s | %lu questions du Pi | %u trames abîmées | HX711 %s\n",
                   (long)copie.brut, copie.par_seconde, (unsigned long)questions,
                   copie.trames_abimees, copie.muet ? "MUET (débranché ?)" : "ok");
        }
    }
}

// -------------------------------------------------------------- cœur 0

int main(void) {
    // D'abord la ligne du bus en écoute, et SCK à 0 (à 1 trop longtemps, le HX711 s'endort).
    gpio_init(REGLAGE_BROCHE_RS485_SENS);
    gpio_put(REGLAGE_BROCHE_RS485_SENS, 0);
    gpio_set_dir(REGLAGE_BROCHE_RS485_SENS, GPIO_OUT);
    gpio_init(REGLAGE_BROCHE_HX711_SCK);
    gpio_put(REGLAGE_BROCHE_HX711_SCK, 0);
    gpio_set_dir(REGLAGE_BROCHE_HX711_SCK, GPIO_OUT);
    gpio_init(REGLAGE_BROCHE_HX711_DT);
    gpio_set_dir(REGLAGE_BROCHE_HX711_DT, GPIO_IN);
    // DT tiré au 3,3 V : HX711 absent = « pas prêt » (et non une mesure prête sans fin).
    gpio_pull_up(REGLAGE_BROCHE_HX711_DT);
#if REGLAGE_BROCHE_VOYANT >= 0
    gpio_init(REGLAGE_BROCHE_VOYANT);
    gpio_set_dir(REGLAGE_BROCHE_VOYANT, GPIO_OUT);
#endif
    uart_init(UART, REGLAGE_VITESSE_BAUDS);
    uart_set_format(UART, 8, 1, UART_PARITY_NONE);
    uart_set_fifo_enabled(UART, true);
    gpio_set_function(REGLAGE_BROCHE_RS485_TX, GPIO_FUNC_UART);
    gpio_set_function(REGLAGE_BROCHE_RS485_RX, GPIO_FUNC_UART);
    // Ligne RX tirée au repos (1) : un émetteur-récepteur en émission ne la laisse pas flotter.
    gpio_pull_up(REGLAGE_BROCHE_RS485_RX);

    redemarre_par_chien = watchdog_enable_caused_reboot();
    watchdog_enable(REGLAGE_CHIEN_DE_GARDE_MS, true);
    critical_section_init(&verrou);
    multicore_launch_core1(coeur1);

    mesures_t mesures;
    modbus_t bus;
    uint32_t questions = 0;
    mesures_init(&mesures, REGLAGE_SANS_MESURE_MS, REGLAGE_EXEMPLE, time_us_64());
    modbus_init(&bus, REGLAGE_ADRESSE);
    uint16_t registres[NB_REGISTRES];
    uint8_t reponse[MODBUS_REPONSE_MAX];

    for (;;) {
        watchdog_update();
        if (hx711_pret(&hx711)) {
            uint32_t interruptions = save_and_disable_interrupts();
            int32_t brut = hx711_lire(&hx711);
            restore_interrupts(interruptions);
            mesures_noter(&mesures, brut, time_us_64());
        }
        while (uart_is_readable(UART)) {
            uint8_t octet = (uint8_t)uart_getc(UART);
            uint64_t t_us = time_us_64();
            if (modbus_recevoir(&bus, octet, t_us)) {
                mesures_registres(&mesures, bus.trames_abimees, t_us, registres);
                size_t n = modbus_repondre(&bus, registres, NB_REGISTRES, reponse);
                envoyer(reponse, n);
                modbus_oublier(&bus);
                questions++;
            }
        }
        uint64_t t_us = time_us_64();
        mesures_avancer(&mesures, t_us);
        bool muet = mesures_muet(&mesures, t_us);
        allumer_voyant(muet, t_us);
        critical_section_enter_blocking(&verrou);
        partage.brut = mesures.brut;
        partage.par_seconde = mesures.par_seconde;
        partage.trames_abimees = bus.trames_abimees;
        partage.questions = questions;
        partage.muet = muet;
        critical_section_exit(&verrou);
    }
}
