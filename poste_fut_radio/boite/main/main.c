// Programme de l'ESP32-C3 de la boîte du poste du fût : reçoit par la radio ESP-NOW (sans Wi-Fi
// ni réseau) les trames du plateau de pesée, et répond au Pi sur le bus RS485 des pesées en
// Modbus RTU, comme une carte de pesée (registres 0 à 12, signature 0x5046 : commun/boite.h).
// Toujours alimentée (24 V → 5 V).
//
// Tous les chiffres viennent de pi/reglages/pesees.yaml (poste_fut_radio) et de
// docs/entrees-sorties.yaml (adresse de pesee_fut, vitesse du bus), copiés dans reglages_radio.h
// à la fabrication. Ce que fait le programme sans le matériel (registres, radio muette, trames
// perdues, Modbus) est dans ../commun et ../../pesee/src/modbus.c (essayé sur PC).
//
// Le bus : un émetteur-récepteur RS485 3,3 V (MAX3485) dont DE et /RE, reliées ensemble, vont à
// la broche « rs485_sens » : 1 pour parler, 0 (repos) pour écouter. La boîte ne parle que pour
// répondre à une question qui lui est adressée. Elle n'écoute que l'adresse radio du plateau.
#include <stdio.h>
#include <string.h>

#include "boite.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_app_desc.h"
#include "esp_event.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_rom_sys.h"
#include "esp_system.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "modbus.h"
#include "nvs_flash.h"
#include "reglages_radio.h"

#define UART UART_NUM_1
// Tailles des tampons du pilote de l'UART, et des files d'attente (octets, événements, trames).
#define TAMPON_UART 1024
#define FILE_UART 32
#define FILE_RADIO 8
// Le pilote de l'UART rend les octets reçus après un silence de 2 caractères (ou 120 octets) :
// assez court pour répondre vite, la vraie fin de trame est jugée par modbus.c.
#define SILENCE_UART_CARACTERES 2
// Sans octet ni trame, la boucle tourne quand même toutes les ... ms (chien de garde, voyant).
#define ATTENTE_MAX_MS 10
// Clignotement du voyant quand la radio est muette (µs par demi-période).
#define CLIGNOTEMENT_US 250000

static const uint8_t adresse_plateau[6] = REGLAGE_ADRESSE_PLATEAU;
static const uint8_t adresse_boite[6] = REGLAGE_ADRESSE_BOITE;

// Une trame radio reçue, mise en file par la tâche de la radio pour la boucle principale.
typedef struct {
    uint8_t adresse[6];
    uint8_t octets[TRAME_TAILLE + 1];  // + 1 : une trame trop longue reste reconnue comme telle
    size_t n;
    int8_t signal_dbm;
    uint64_t t_us;
} paquet_radio_t;

static QueueHandle_t file_radio;
static QueueHandle_t file_uart;

// ------------------------------------------------- partagé avec la fenêtre USB

typedef struct {
    int32_t brut;
    uint16_t par_seconde;
    bool muette;
    bool hx711_muet;
    uint16_t plateau;
    uint16_t accu_mv;
    uint16_t accu_pct;
    int signal_dbm;
    uint16_t perdues;
    uint32_t questions;
    uint16_t questions_abimees;
    uint32_t autre_adresse;
    uint8_t derniere_autre_adresse[6];
    uint32_t abimees;
    uint32_t file_pleine;
} instantane_t;

static portMUX_TYPE verrou = portMUX_INITIALIZER_UNLOCKED;
static instantane_t partage;
static volatile uint32_t radio_file_pleine;

// ------------------------------------------------------------------- radio

static void a_la_reception(const esp_now_recv_info_t *info, const uint8_t *octets, int n) {
    paquet_radio_t paquet;
    memcpy(paquet.adresse, info->src_addr, 6);
    paquet.n = n < 0 ? 0 : (size_t)n;
    if (paquet.n > sizeof(paquet.octets)) {
        paquet.n = sizeof(paquet.octets);
    }
    memcpy(paquet.octets, octets, paquet.n);
    paquet.signal_dbm = info->rx_ctrl ? (int8_t)info->rx_ctrl->rssi : 0;
    paquet.t_us = (uint64_t)esp_timer_get_time();
    if (xQueueSend(file_radio, &paquet, 0) != pdTRUE) {
        radio_file_pleine++;
    }
}

static void preparer_radio(void) {
    esp_err_t erreur = nvs_flash_init();
    if (erreur == ESP_ERR_NVS_NO_FREE_PAGES || erreur == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        erreur = nvs_flash_init();
    }
    ESP_ERROR_CHECK(erreur);
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    wifi_init_config_t config = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&config));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    // La carte prend l'adresse radio écrite dans les réglages.
    ESP_ERROR_CHECK(esp_wifi_set_mac(WIFI_IF_STA, adresse_boite));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_channel(REGLAGE_CANAL, WIFI_SECOND_CHAN_NONE));
    // En quarts de dBm (la boîte n'envoie que les accusés de réception).
    ESP_ERROR_CHECK(esp_wifi_set_max_tx_power(REGLAGE_PUISSANCE_DBM * 4));
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_register_recv_cb(a_la_reception));
}

// ------------------------------------------------------------------- RS485

static void preparer_bus(void) {
    // D'abord la ligne du bus en écoute.
    gpio_reset_pin(REGLAGE_BOITE_BROCHE_RS485_SENS);
    gpio_set_direction(REGLAGE_BOITE_BROCHE_RS485_SENS, GPIO_MODE_OUTPUT);
    gpio_set_level(REGLAGE_BOITE_BROCHE_RS485_SENS, 0);
    uart_config_t config = {
        .baud_rate = REGLAGE_VITESSE_BAUDS,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(UART, TAMPON_UART, 0, FILE_UART, &file_uart, 0));
    ESP_ERROR_CHECK(uart_param_config(UART, &config));
    ESP_ERROR_CHECK(uart_set_pin(UART, REGLAGE_BOITE_BROCHE_RS485_TX, REGLAGE_BOITE_BROCHE_RS485_RX,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    // Ligne RX tirée au repos (1) : l'émetteur-récepteur en émission ne la laisse pas flotter.
    gpio_pullup_en(REGLAGE_BOITE_BROCHE_RS485_RX);
    ESP_ERROR_CHECK(uart_set_rx_timeout(UART, SILENCE_UART_CARACTERES));
}

static void envoyer(const uint8_t *octets, size_t n) {
    // Laisser l'adaptateur du Pi repasser en écoute après sa question.
    esp_rom_delay_us(REGLAGE_DELAI_AVANT_REPONSE_US);
    gpio_set_level(REGLAGE_BOITE_BROCHE_RS485_SENS, 1);
    uart_write_bytes(UART, octets, n);
    // Attendre que le dernier bit soit sorti avant de lâcher le bus (10 bits par octet).
    uart_wait_tx_done(UART, pdMS_TO_TICKS(ATTENTE_MAX_MS + n * 10000 / REGLAGE_VITESSE_BAUDS));
    gpio_set_level(REGLAGE_BOITE_BROCHE_RS485_SENS, 0);
    // Un émetteur-récepteur qui s'entend parler : l'écho est oublié.
    uart_flush_input(UART);
}

// ------------------------------------------------------------------- voyant

static void allumer_voyant(bool muette, uint64_t t_us) {
#if REGLAGE_BOITE_BROCHE_VOYANT >= 0
    // Allumé : trames du plateau reçues. Clignote : radio muette.
    bool allume = muette ? (t_us / CLIGNOTEMENT_US) % 2 == 0 : true;
    gpio_set_level(REGLAGE_BOITE_BROCHE_VOYANT, allume != REGLAGE_BOITE_VOYANT_ACTIF_BAS);
#else
    (void)muette;
    (void)t_us;
#endif
}

// ------------------------------------------------------------- fenêtre USB

static void afficher(void *argument) {
    (void)argument;
    const esp_app_desc_t *programme = esp_app_get_description();
    printf("Boîte du poste du fût « %s », adresse %d sur le bus des pesées, %d bauds.\n",
           REGLAGE_NOM_SIGNAL, REGLAGE_ADRESSE, REGLAGE_VITESSE_BAUDS);
    printf("Version %s.%s\n", programme->version,
           REGLAGE_EXEMPLE ? " Réglages d'EXEMPLE (pi/reglages/pesees.yaml)." : "");
    printf("Adresse radio de la boîte %s ; n'écoute que le plateau %s ; canal %d.\n",
           REGLAGE_ADRESSE_BOITE_TEXTE, REGLAGE_ADRESSE_PLATEAU_TEXTE, REGLAGE_CANAL);
    if (esp_reset_reason() == ESP_RST_TASK_WDT) {
        printf("ATTENTION : la carte a redémarré par son chien de garde (programme figé).\n");
    }
    uint32_t questions_avant = 0, autre_avant = 0;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(REGLAGE_BOITE_PERIODE_AFFICHAGE_MS));
        instantane_t c;
        portENTER_CRITICAL(&verrou);
        c = partage;
        portEXIT_CRITICAL(&verrou);
        if (c.muette) {
            printf("RADIO MUETTE (rien du plateau depuis %d ms)", REGLAGE_BOITE_RADIO_MUETTE_MS);
        } else {
            printf("brut %ld | %u trames/s | HX711 %s | reed %s | accu %u mV %u %% | recharge "
                   "5 V %s | USB-C %s | signal %d dBm",
                   (long)c.brut, c.par_seconde, c.hx711_muet ? "MUET" : "ok",
                   (c.plateau & BOITE_PLATEAU_AU_POSTE) ? "fermé" : "ouvert", c.accu_mv,
                   c.accu_pct, (c.plateau & BOITE_PLATEAU_RECHARGE_PRESENTE) ? "oui" : "non",
                   (c.plateau & BOITE_PLATEAU_SUR_USB) ? "oui" : "non", c.signal_dbm);
        }
        printf(" | %u perdues | %lu questions du Pi | %u questions abîmées",
               c.perdues, (unsigned long)(c.questions - questions_avant), c.questions_abimees);
        if (c.autre_adresse != autre_avant) {
            const uint8_t *a = c.derniere_autre_adresse;
            printf(" | trames d'une AUTRE adresse radio : %02X:%02X:%02X:%02X:%02X:%02X", a[0],
                   a[1], a[2], a[3], a[4], a[5]);
        }
        if (c.abimees) {
            printf(" | %lu trames radio abîmées", (unsigned long)c.abimees);
        }
        if (c.file_pleine) {
            printf(" | %lu trames radio jetées (file pleine)", (unsigned long)c.file_pleine);
        }
        printf("\n");
        questions_avant = c.questions;
        autre_avant = c.autre_adresse;
    }
}

// --------------------------------------------------------------- programme

void app_main(void) {
#if REGLAGE_BOITE_BROCHE_VOYANT >= 0
    gpio_reset_pin(REGLAGE_BOITE_BROCHE_VOYANT);
    gpio_set_direction(REGLAGE_BOITE_BROCHE_VOYANT, GPIO_MODE_OUTPUT);
#endif
    file_radio = xQueueCreate(FILE_RADIO, sizeof(paquet_radio_t));
    preparer_bus();
    preparer_radio();

    esp_task_wdt_config_t chien = {
        .timeout_ms = REGLAGE_BOITE_CHIEN_DE_GARDE_MS,
        .idle_core_mask = 0,
        .trigger_panic = true,
    };
    ESP_ERROR_CHECK(esp_task_wdt_reconfigure(&chien));
    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));
    // Le bus avant tout le reste, sauf la radio (priorité 23) et les minuteries d'ESP-IDF (22).
    vTaskPrioritySet(NULL, configMAX_PRIORITIES - 5);
    // La fenêtre USB à part, moins pressée : si elle attend, le bus continue.
    xTaskCreate(afficher, "affichage", 4096, NULL, tskIDLE_PRIORITY + 1, NULL);

    boite_t boite;
    modbus_t bus;
    boite_init(&boite, REGLAGE_BOITE_RADIO_MUETTE_MS, REGLAGE_EXEMPLE, adresse_plateau,
               (uint64_t)esp_timer_get_time());
    modbus_init(&bus, REGLAGE_ADRESSE);
    uint16_t registres[BOITE_NB_REGISTRES];
    uint8_t reponse[MODBUS_REPONSE_MAX];
    uint8_t recus[TAMPON_UART];
    uint64_t dernier_octet_us = 0;
    uint32_t questions = 0;

    for (;;) {
        esp_task_wdt_reset();
        uart_event_t evenement;
        if (xQueueReceive(file_uart, &evenement, pdMS_TO_TICKS(ATTENTE_MAX_MS)) == pdTRUE) {
            if (evenement.type == UART_DATA) {
                size_t a_lire = evenement.size < sizeof(recus) ? evenement.size : sizeof(recus);
                int n = uart_read_bytes(UART, recus, a_lire, 0);
                uint64_t t_lecture = (uint64_t)esp_timer_get_time();
                for (int i = 0; i < n; i++) {
                    uint64_t t_us = boite_heure_octet(t_lecture, (size_t)n, (size_t)i,
                                                      REGLAGE_VITESSE_BAUDS, &dernier_octet_us);
                    if (modbus_recevoir(&bus, recus[i], t_us)) {
                        uint64_t maintenant = (uint64_t)esp_timer_get_time();
                        boite_registres(&boite, bus.trames_abimees, maintenant, registres);
                        size_t taille = modbus_repondre(&bus, registres, BOITE_NB_REGISTRES,
                                                        reponse);
                        envoyer(reponse, taille);
                        modbus_oublier(&bus);
                        questions++;
                    }
                }
            } else if (evenement.type == UART_FIFO_OVF || evenement.type == UART_BUFFER_FULL) {
                // Trop d'octets d'un coup : tout oublier, la question suivante sera entendue.
                uart_flush_input(UART);
                xQueueReset(file_uart);
                modbus_oublier(&bus);
            }
        }
        paquet_radio_t paquet;
        while (xQueueReceive(file_radio, &paquet, 0) == pdTRUE) {
            boite_recevoir(&boite, paquet.adresse, paquet.octets, paquet.n, paquet.signal_dbm,
                           paquet.t_us);
        }
        uint64_t t_us = (uint64_t)esp_timer_get_time();
        boite_avancer(&boite, t_us);
        bool muette = boite_radio_muette(&boite, t_us);
        allumer_voyant(muette, t_us);
        portENTER_CRITICAL(&verrou);
        partage.brut = boite.derniere.brut;
        partage.par_seconde = boite.par_seconde;
        partage.muette = muette;
        partage.hx711_muet = boite.derniere.hx711_muet;
        partage.plateau = 0;
        partage.plateau |= boite.derniere.au_poste ? BOITE_PLATEAU_AU_POSTE : 0;
        partage.plateau |= boite.derniere.recharge_presente ? BOITE_PLATEAU_RECHARGE_PRESENTE : 0;
        partage.plateau |= boite.derniere.sur_usb ? BOITE_PLATEAU_SUR_USB : 0;
        partage.accu_mv = boite.derniere.accu_mv;
        partage.accu_pct = boite.derniere.accu_pct;
        partage.signal_dbm = boite.signal_dbm;
        partage.perdues = boite.perdues;
        partage.questions = questions;
        partage.questions_abimees = bus.trames_abimees;
        partage.autre_adresse = boite.autre_adresse;
        memcpy(partage.derniere_autre_adresse, boite.derniere_autre_adresse, 6);
        partage.abimees = boite.abimees;
        partage.file_pleine = radio_file_pleine;
        portEXIT_CRITICAL(&verrou);
    }
}
