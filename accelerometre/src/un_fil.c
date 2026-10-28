#include "un_fil.h"

#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/irq.h"
#include "hardware/pio.h"
#include "pico/time.h"
#include "un_fil.pio.h"

#define PIO_FIL pio0
#define MACHINE_TX 0
#define MACHINE_RX 1
#define TAILLE_RESERVE 1024  // octets reçus en attente (une trame du chargeur, ou 4 du programme)

static unsigned debut_rx;  // place du programme de réception dans la mémoire PIO
static uint32_t temps_octet_us;
static volatile uint8_t reserve[TAILLE_RESERVE];
static volatile uint32_t tete;   // écrit par l'interruption
static volatile uint32_t queue;  // écrit par le lecteur
static volatile uint32_t perdus;

static void octets_recus(void) {
    while (!pio_sm_is_rx_fifo_empty(PIO_FIL, MACHINE_RX)) {
        uint8_t octet = (uint8_t)(pio_sm_get(PIO_FIL, MACHINE_RX) >> 24);
        uint32_t suivant = (tete + 1) % TAILLE_RESERVE;
        if (suivant == queue) {
            perdus++;
        } else {
            reserve[tete] = octet;
            tete = suivant;
        }
    }
}

static void ecouter(void) {
    pio_sm_clear_fifos(PIO_FIL, MACHINE_RX);
    pio_sm_restart(PIO_FIL, MACHINE_RX);
    pio_sm_exec(PIO_FIL, MACHINE_RX, pio_encode_jmp(debut_rx));
    pio_sm_set_enabled(PIO_FIL, MACHINE_RX, true);
}

void un_fil_demarrer(unsigned broche, uint32_t vitesse_bauds) {
    float diviseur = (float)clock_get_hz(clk_sys) / (8.0f * (float)vitesse_bauds);
    temps_octet_us = 10u * 1000000u / vitesse_bauds + 1;

    // Envoi : la broche vaut 1 quand elle est prise, mais reste en entrée au repos.
    unsigned debut_tx = pio_add_program(PIO_FIL, &un_fil_tx_program);
    pio_sm_set_pins_with_mask(PIO_FIL, MACHINE_TX, 1u << broche, 1u << broche);
    pio_sm_set_pindirs_with_mask(PIO_FIL, MACHINE_TX, 0, 1u << broche);
    pio_gpio_init(PIO_FIL, broche);
    gpio_pull_up(broche);
    pio_sm_config c = un_fil_tx_program_get_default_config(debut_tx);
    sm_config_set_out_pins(&c, broche, 1);
    sm_config_set_set_pins(&c, broche, 1);
    sm_config_set_sideset_pins(&c, broche);
    sm_config_set_out_shift(&c, true, false, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_TX);
    sm_config_set_clkdiv(&c, diviseur);
    pio_sm_init(PIO_FIL, MACHINE_TX, debut_tx, &c);
    pio_sm_set_enabled(PIO_FIL, MACHINE_TX, true);

    // Réception : lit la même broche, ne la commande jamais.
    debut_rx = pio_add_program(PIO_FIL, &un_fil_rx_program);
    c = un_fil_rx_program_get_default_config(debut_rx);
    sm_config_set_in_pins(&c, broche);
    sm_config_set_jmp_pin(&c, broche);
    sm_config_set_in_shift(&c, true, false, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv(&c, diviseur);
    pio_sm_init(PIO_FIL, MACHINE_RX, debut_rx, &c);

    pio_set_irq0_source_enabled(PIO_FIL, pio_get_rx_fifo_not_empty_interrupt_source(MACHINE_RX),
                                true);
    irq_set_exclusive_handler(PIO0_IRQ_0, octets_recus);
    irq_set_enabled(PIO0_IRQ_0, true);
    ecouter();
}

bool un_fil_lire(uint8_t *octet) {
    if (queue == tete) {
        return false;
    }
    *octet = reserve[queue];
    queue = (queue + 1) % TAILLE_RESERVE;
    return true;
}

void un_fil_envoyer(const char *octets, size_t n) {
    // Pendant l'envoi, on n'écoute pas (on s'entendrait soi-même).
    pio_sm_set_enabled(PIO_FIL, MACHINE_RX, false);
    for (size_t i = 0; i < n; i++) {
        pio_sm_put_blocking(PIO_FIL, MACHINE_TX, (uint8_t)octets[i]);
    }
    // Le dernier octet est parti de la réserve : attendre que la machine ait fini de
    // l'envoyer et soit revenue sur « pull » (fil rendu). Au plus le temps de 2 octets.
    while (!pio_sm_is_tx_fifo_empty(PIO_FIL, MACHINE_TX)) {
        tight_loop_contents();
    }
    uint32_t bloquee = 1u << (PIO_FDEBUG_TXSTALL_LSB + MACHINE_TX);
    PIO_FIL->fdebug = bloquee;
    absolute_time_t limite = make_timeout_time_us(2 * temps_octet_us);
    while (!(PIO_FIL->fdebug & bloquee) && !time_reached(limite)) {
        tight_loop_contents();
    }
    ecouter();
}

uint32_t un_fil_perdus(void) {
    return perdus;
}
