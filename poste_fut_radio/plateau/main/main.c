// Programme de l'ESP32-C3 du plateau de pesée du poste du fût : lit le HX711 (4 capteurs en
// parallèle), fait la moyenne, et envoie 2 trames par seconde à la boîte du poste par la radio
// ESP-NOW (sans Wi-Fi ni réseau). Dort plateau sorti, se réveille sur le reed (l'aimant de la
// boîte du poste).
//
// Tous les chiffres viennent de pi/reglages/pesees.yaml (poste_fut_radio), copiés dans
// reglages_radio.h à la fabrication. Ce que fait le programme sans le matériel (moyenne, trame,
// HX711 muet, sommeil) est dans ../commun (essayé sur PC).
//
// Branchement (numéros de broches : pesees.yaml) :
// - HX711 : DT et SCK. SCK reste à 1 pendant le sommeil : le HX711 s'éteint lui aussi.
// - Reed entre sa broche et le 0 V (pull-up de l'ESP32-C3) : fermé = au poste = 0.
// - Accu : pont diviseur sur une entrée analogique (ADC1).
// - 5 V de la recharge sans contact, 5 V de l'USB-C de secours : chacun par un pont diviseur,
//   1 = présent.
#include <stdio.h>
#include <string.h>

#include "accu.h"
#include "driver/gpio.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_app_desc.h"
#include "esp_attr.h"
#include "esp_event.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_rom_sys.h"
#include "esp_sleep.h"
#include "esp_system.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "hx711.h"
#include "nvs_flash.h"
#include "plateau.h"
#include "reglages_radio.h"
#include "trame.h"

// La boucle regarde le HX711 et le reed toutes les ... ms (10 mesures par seconde : une toutes
// les 100 ms ; la mesure attend d'être lue).
#define BOUCLE_MS 5
// Lectures de l'entrée analogique de l'accu, moyennées, pour chaque trame.
#define LECTURES_ACCU 8
// Le voyant s'allume ce temps (µs) à chaque trame reçue par la boîte.
#define ECLAIR_US 30000

static const uint8_t adresse_plateau[6] = REGLAGE_ADRESSE_PLATEAU;
static const uint8_t adresse_boite[6] = REGLAGE_ADRESSE_BOITE;
static const uint16_t courbe_mv[REGLAGE_PLATEAU_COURBE_POINTS] = REGLAGE_PLATEAU_COURBE_MV;
static const uint8_t courbe_pct[REGLAGE_PLATEAU_COURBE_POINTS] = REGLAGE_PLATEAU_COURBE_PCT;
static const courbe_accu_t courbe = {courbe_mv, courbe_pct, REGLAGE_PLATEAU_COURBE_POINTS};

// Gardé pendant le sommeil : le numéro des trames continue au réveil.
static RTC_DATA_ATTR uint16_t numero_avant_sommeil;

// ------------------------------------------------- partagé avec la fenêtre USB

typedef struct {
    int32_t brut;
    uint16_t par_seconde;
    bool muet;
    bool au_poste;
    bool recharge;
    bool usb;
    uint16_t accu_mv;
    uint8_t accu_pct;
    uint32_t trames;
    uint32_t reponses;  // trames dont la boîte a accusé réception
    uint32_t ratees;
    uint32_t sommeil_dans_s;
} instantane_t;

static portMUX_TYPE verrou = portMUX_INITIALIZER_UNLOCKED;
static instantane_t partage;
static volatile uint32_t trames_recues;  // par la boîte (accusé de réception radio)
static volatile uint32_t trames_ratees;
static volatile uint64_t dernier_accuse_us;

// ------------------------------------------------------------------- HX711

static bool lire_dt(void *contexte) {
    (void)contexte;
    return gpio_get_level(REGLAGE_PLATEAU_BROCHE_HX711_DT);
}

static void ecrire_sck(void *contexte, bool haut) {
    (void)contexte;
    gpio_set_level(REGLAGE_PLATEAU_BROCHE_HX711_SCK, haut);
}

static void attendre_us(void *contexte, uint32_t us) {
    (void)contexte;
    esp_rom_delay_us(us);
}

static const broches_hx711_t hx711 = {lire_dt, ecrire_sck, attendre_us, NULL};
static portMUX_TYPE verrou_hx711 = portMUX_INITIALIZER_UNLOCKED;

static int32_t lire_hx711(void) {
    // SCK ne doit jamais rester à 1 plus de 60 µs : pas d'interruption pendant la lecture.
    portENTER_CRITICAL(&verrou_hx711);
    int32_t brut = hx711_lire(&hx711);
    portEXIT_CRITICAL(&verrou_hx711);
    return brut;
}

// -------------------------------------------------------------------- accu

static adc_oneshot_unit_handle_t adc;
static adc_channel_t voie_accu;
static adc_cali_handle_t etalonnage_adc;
static bool adc_etalonne;

static void preparer_accu(void) {
    adc_unit_t unite;
    ESP_ERROR_CHECK(adc_oneshot_io_to_channel(REGLAGE_PLATEAU_BROCHE_ACCU, &unite, &voie_accu));
    adc_oneshot_unit_init_cfg_t config_unite = {.unit_id = unite};
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&config_unite, &adc));
    adc_oneshot_chan_cfg_t config_voie = {.atten = ADC_ATTEN_DB_12,
                                          .bitwidth = ADC_BITWIDTH_DEFAULT};
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc, voie_accu, &config_voie));
    // Étalonnage de l'usine (écrit dans la puce) : la tension en mV.
    adc_cali_curve_fitting_config_t config_etalonnage = {
        .unit_id = unite, .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT};
    adc_etalonne =
        adc_cali_create_scheme_curve_fitting(&config_etalonnage, &etalonnage_adc) == ESP_OK;
}

static uint16_t lire_accu_mv(void) {
    uint32_t somme = 0;
    int lues = 0;
    for (int i = 0; i < LECTURES_ACCU; i++) {
        int brut = 0;
        int mv = 0;
        if (adc_oneshot_read(adc, voie_accu, &brut) != ESP_OK) {
            continue;
        }
        if (adc_etalonne) {
            adc_cali_raw_to_voltage(etalonnage_adc, brut, &mv);
        } else {
            // Sans étalonnage d'usine : environ 2 500 mV pour 4 095.
            mv = brut * 2500 / 4095;
        }
        somme += (uint32_t)mv;
        lues++;
    }
    if (lues == 0) {
        return 0;
    }
    return accu_tension_mv(somme / (uint32_t)lues, REGLAGE_PLATEAU_RAPPORT_PONT_MILLIEMES);
}

// ------------------------------------------------------------------- radio

static void apres_envoi(const esp_now_send_info_t *info, esp_now_send_status_t statut) {
    (void)info;
    if (statut == ESP_NOW_SEND_SUCCESS) {
        trames_recues++;
        dernier_accuse_us = (uint64_t)esp_timer_get_time();
    } else {
        trames_ratees++;
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
    ESP_ERROR_CHECK(esp_wifi_set_mac(WIFI_IF_STA, adresse_plateau));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_channel(REGLAGE_CANAL, WIFI_SECOND_CHAN_NONE));
    // En quarts de dBm.
    ESP_ERROR_CHECK(esp_wifi_set_max_tx_power(REGLAGE_PUISSANCE_DBM * 4));
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_register_send_cb(apres_envoi));
    esp_now_peer_info_t boite = {0};
    memcpy(boite.peer_addr, adresse_boite, 6);
    boite.channel = REGLAGE_CANAL;
    boite.ifidx = WIFI_IF_STA;
    boite.encrypt = false;
    ESP_ERROR_CHECK(esp_now_add_peer(&boite));
}

// ----------------------------------------------------------- entrées et voyant

static void preparer_broches(void) {
    // SCK à 0 : le HX711 se rallume (il était éteint pendant le sommeil, SCK à 1).
    gpio_hold_dis(REGLAGE_PLATEAU_BROCHE_HX711_SCK);
    gpio_reset_pin(REGLAGE_PLATEAU_BROCHE_HX711_SCK);
    gpio_set_direction(REGLAGE_PLATEAU_BROCHE_HX711_SCK, GPIO_MODE_OUTPUT);
    gpio_set_level(REGLAGE_PLATEAU_BROCHE_HX711_SCK, 0);
    gpio_reset_pin(REGLAGE_PLATEAU_BROCHE_HX711_DT);
    gpio_set_direction(REGLAGE_PLATEAU_BROCHE_HX711_DT, GPIO_MODE_INPUT);
    // DT tiré au 3,3 V : HX711 absent = « pas prêt » (et non une mesure prête sans fin).
    gpio_pullup_en(REGLAGE_PLATEAU_BROCHE_HX711_DT);
    gpio_reset_pin(REGLAGE_PLATEAU_BROCHE_REED);
    gpio_set_direction(REGLAGE_PLATEAU_BROCHE_REED, GPIO_MODE_INPUT);
    gpio_pullup_en(REGLAGE_PLATEAU_BROCHE_REED);
    gpio_reset_pin(REGLAGE_PLATEAU_BROCHE_RECHARGE_5V);
    gpio_set_direction(REGLAGE_PLATEAU_BROCHE_RECHARGE_5V, GPIO_MODE_INPUT);
    gpio_pulldown_en(REGLAGE_PLATEAU_BROCHE_RECHARGE_5V);
    gpio_reset_pin(REGLAGE_PLATEAU_BROCHE_USB_5V);
    gpio_set_direction(REGLAGE_PLATEAU_BROCHE_USB_5V, GPIO_MODE_INPUT);
    gpio_pulldown_en(REGLAGE_PLATEAU_BROCHE_USB_5V);
#if REGLAGE_PLATEAU_BROCHE_VOYANT >= 0
    gpio_reset_pin(REGLAGE_PLATEAU_BROCHE_VOYANT);
    gpio_set_direction(REGLAGE_PLATEAU_BROCHE_VOYANT, GPIO_MODE_OUTPUT);
#endif
}

static bool reed_ferme(void) {
    return gpio_get_level(REGLAGE_PLATEAU_BROCHE_REED) == 0;
}

static void allumer_voyant(bool allume) {
#if REGLAGE_PLATEAU_BROCHE_VOYANT >= 0
    gpio_set_level(REGLAGE_PLATEAU_BROCHE_VOYANT, allume != REGLAGE_PLATEAU_VOYANT_ACTIF_BAS);
#else
    (void)allume;
#endif
}

static void dormir(uint16_t numero) {
    printf("Reed ouvert depuis %d s : la carte s'endort (réveil par l'aimant du poste).\n",
           REGLAGE_PLATEAU_SOMMEIL_APRES_MS / 1000);
    numero_avant_sommeil = numero;
    esp_now_deinit();
    esp_wifi_stop();
    allumer_voyant(false);
    // SCK à 1 plus de 60 µs : le HX711 s'éteint, et reste éteint pendant le sommeil.
    gpio_set_level(REGLAGE_PLATEAU_BROCHE_HX711_SCK, 1);
    gpio_hold_en(REGLAGE_PLATEAU_BROCHE_HX711_SCK);
#if !SOC_GPIO_SUPPORT_HOLD_SINGLE_IO_IN_DSLP
    gpio_deep_sleep_hold_en();
#endif
    ESP_ERROR_CHECK(esp_deep_sleep_enable_gpio_wakeup(1ULL << REGLAGE_PLATEAU_BROCHE_REED,
                                                      ESP_GPIO_WAKEUP_GPIO_LOW));
    esp_deep_sleep_start();
}

// ------------------------------------------------------------- fenêtre USB

static void afficher(void *argument) {
    (void)argument;
    const esp_app_desc_t *programme = esp_app_get_description();
    printf("Plateau de pesée du poste du fût, version %s.%s\n", programme->version,
           REGLAGE_EXEMPLE ? " Réglages d'EXEMPLE (pi/reglages/pesees.yaml)." : "");
    printf("Adresse radio du plateau %s, envoie à la boîte %s, canal %d, %d dBm.\n",
           REGLAGE_ADRESSE_PLATEAU_TEXTE, REGLAGE_ADRESSE_BOITE_TEXTE, REGLAGE_CANAL,
           REGLAGE_PUISSANCE_DBM);
    esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
    printf("Démarrage : %s.\n", cause == ESP_SLEEP_WAKEUP_GPIO
                                     ? "réveil par le reed (aimant du poste)"
                                     : "mise sous tension");
    if (esp_reset_reason() == ESP_RST_TASK_WDT) {
        printf("ATTENTION : la carte a redémarré par son chien de garde (programme figé).\n");
    }
    uint32_t trames_avant = 0, reponses_avant = 0, ratees_avant = 0;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(REGLAGE_PLATEAU_PERIODE_AFFICHAGE_MS));
        instantane_t c;
        portENTER_CRITICAL(&verrou);
        c = partage;
        portEXIT_CRITICAL(&verrou);
        printf("brut %ld | %u mesures/s | HX711 %s | reed %s | accu %u mV %u %% | recharge 5 V "
               "%s | USB-C %s | trames %lu, reçues par la boîte %lu, ratées %lu",
               (long)c.brut, c.par_seconde, c.muet ? "MUET (débranché ?)" : "ok",
               c.au_poste ? "fermé (au poste)" : "ouvert", c.accu_mv, c.accu_pct,
               c.recharge ? "oui" : "non", c.usb ? "oui" : "non",
               (unsigned long)(c.trames - trames_avant),
               (unsigned long)(c.reponses - reponses_avant),
               (unsigned long)(c.ratees - ratees_avant));
        if (!c.au_poste) {
            printf(" | sommeil dans %lu s", (unsigned long)c.sommeil_dans_s);
        }
        printf("\n");
        trames_avant = c.trames;
        reponses_avant = c.reponses;
        ratees_avant = c.ratees;
    }
}

// --------------------------------------------------------------- programme

void app_main(void) {
    preparer_broches();
    allumer_voyant(false);
    preparer_accu();
    preparer_radio();

    esp_task_wdt_config_t chien = {
        .timeout_ms = REGLAGE_PLATEAU_CHIEN_DE_GARDE_MS,
        .idle_core_mask = 0,
        .trigger_panic = true,
    };
    ESP_ERROR_CHECK(esp_task_wdt_reconfigure(&chien));
    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));
    // La fenêtre USB à part, moins pressée : si elle attend, la pesée continue.
    xTaskCreate(afficher, "affichage", 4096, NULL, tskIDLE_PRIORITY + 1, NULL);

    const reglages_plateau_t reglages = {
        .moyenne_de = REGLAGE_PLATEAU_MOYENNE_DE,
        .periode_trame_ms = REGLAGE_PLATEAU_PERIODE_TRAME_MS,
        .sans_mesure_ms = REGLAGE_PLATEAU_SANS_MESURE_MS,
        .sommeil_apres_ms = REGLAGE_PLATEAU_SOMMEIL_APRES_MS,
        .exemple = REGLAGE_EXEMPLE,
    };
    plateau_t plateau;
    plateau_init(&plateau, &reglages, numero_avant_sommeil, reed_ferme(),
                 (uint64_t)esp_timer_get_time());
    entrees_plateau_t entrees = {0};
    uint32_t trames = 0;
    int32_t dernier_brut = 0;

    for (;;) {
        esp_task_wdt_reset();
        if (hx711_pret(&hx711)) {
            dernier_brut = lire_hx711();
            plateau_noter_mesure(&plateau, dernier_brut, (uint64_t)esp_timer_get_time());
        }
        uint64_t t_us = (uint64_t)esp_timer_get_time();
        plateau_noter_reed(&plateau, reed_ferme(), t_us);
        if (plateau_trame_due(&plateau, t_us)) {
            entrees.au_poste = reed_ferme();
            entrees.recharge_presente = gpio_get_level(REGLAGE_PLATEAU_BROCHE_RECHARGE_5V);
            entrees.sur_usb = gpio_get_level(REGLAGE_PLATEAU_BROCHE_USB_5V);
            entrees.accu_mv = lire_accu_mv();
            entrees.accu_pct = accu_pourcentage(&courbe, entrees.accu_mv);
            trame_t trame;
            uint8_t octets[TRAME_TAILLE];
            plateau_faire_trame(&plateau, &entrees, t_us, &trame);
            trame_ecrire(&trame, octets);
            if (esp_now_send(adresse_boite, octets, sizeof(octets)) == ESP_OK) {
                trames++;
            } else {
                trames_ratees++;
            }
        }
        allumer_voyant(t_us - dernier_accuse_us < ECLAIR_US && dernier_accuse_us != 0);
        bool muet = plateau_hx711_muet(&plateau, t_us);
        uint64_t ouvert_us = t_us - plateau.reed_ouvert_depuis_us;
        uint64_t sommeil_us = (uint64_t)REGLAGE_PLATEAU_SOMMEIL_APRES_MS * 1000;
        portENTER_CRITICAL(&verrou);
        partage.brut = dernier_brut;
        partage.par_seconde = plateau.par_seconde;
        partage.muet = muet;
        partage.au_poste = plateau.reed_ferme;
        partage.recharge = entrees.recharge_presente;
        partage.usb = entrees.sur_usb;
        partage.accu_mv = entrees.accu_mv;
        partage.accu_pct = entrees.accu_pct;
        partage.trames = trames;
        partage.reponses = trames_recues;
        partage.ratees = trames_ratees;
        partage.sommeil_dans_s =
            ouvert_us >= sommeil_us ? 0 : (uint32_t)((sommeil_us - ouvert_us) / 1000000);
        portEXIT_CRITICAL(&verrou);
        if (plateau_dormir(&plateau, t_us)) {
            dormir(plateau.numero);
        }
        vTaskDelay(pdMS_TO_TICKS(BOUCLE_MS));
    }
}
