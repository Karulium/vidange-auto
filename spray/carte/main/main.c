// Programme de la carte ESP32 n° 5 du spray (ESP32-S3) : 4 pompes et le bras (moteurs pas à pas
// sur TMC2209), 4 balances (HX711), 2 électrovannes, la petite pompe du nettoyage, les
// agitateurs (PWM), le capteur « bras rangé » (par un PC817). Elle répond au Pi sur son bus RS485
// à elle (rs485_spray) en Modbus RTU : la table est dans ../../README.md.
//
// Tous les chiffres viennent de pi/reglages/machine.yaml (spray), de pesees.yaml (balances_spray)
// et de docs/entrees-sorties.yaml (adresse de carte_spray, vitesse du bus), copiés dans
// reglages_spray.h à la fabrication. Ce que fait la carte sans le matériel (ordres, gestes, bras,
// silence du Pi, registres, générateur de pas, balances, trames du TMC2209, Modbus) est dans
// ../../commun et ../../../pesee/src (essayé sur PC).
//
// Le spray ne protège personne. Au démarrage, toutes les sorties sont éteintes (une résistance
// de 10 kΩ vers le 0 V sur chaque grille de MOSFET les garde éteintes pendant le démarrage).
//
// Les cœurs : le générateur de pas (minuterie toutes les REGLAGE_PERIODE_PAS_US) tourne sur le
// cœur 1, seul ; la boucle principale (bus, balances, gestes), le pilote du bras et la fenêtre
// USB sur le cœur 0. Les moteurs sont partagés sous un verrou.
#include <stdio.h>
#include <string.h>

#include "balance.h"
#include "driver/gpio.h"
#include "driver/gptimer.h"
#include "driver/ledc.h"
#include "driver/uart.h"
#include "esp_app_desc.h"
#include "esp_rom_sys.h"
#include "esp_system.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "hx711.h"
#include "modbus.h"
#include "moteur.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "reglages_spray.h"
#include "spray.h"
#include "tmc2209.h"

#define UART_BUS UART_NUM_1
#define UART_PILOTE UART_NUM_2
// Tailles des tampons du pilote de l'UART et de sa file d'événements.
#define TAMPON_UART 1024
#define FILE_UART 32
// Le pilote de l'UART rend les octets reçus après un silence de 2 caractères : assez court pour
// répondre vite, la vraie fin de trame est jugée par modbus.c.
#define SILENCE_UART_CARACTERES 2
// Sans octet, la boucle tourne quand même toutes les ms (gestes, balances, chien de garde).
#define ATTENTE_MAX_MS 1
// Attente d'une réponse du pilote du bras (ms).
#define ATTENTE_PILOTE_MS 10
// PWM des agitateurs : 10 bits.
#define RESOLUTION_PWM LEDC_TIMER_10_BIT
#define PWM_MAX 1023
// Clignotement du voyant quand le Pi se tait (µs par demi-période).
#define CLIGNOTEMENT_US 250000

static const int broches_pompes[SPRAY_NB_FLACONS] = REGLAGE_BROCHES_POMPES_PAS;
static const int broches_dt[SPRAY_NB_FLACONS] = REGLAGE_BROCHES_HX711_DT;
static const int broches_sck[SPRAY_NB_FLACONS] = REGLAGE_BROCHES_HX711_SCK;
static const int32_t zero_brut[SPRAY_NB_FLACONS] = REGLAGE_BALANCES_ZERO_BRUT;
static const float brut_par_kg[SPRAY_NB_FLACONS] = REGLAGE_BALANCES_BRUT_PAR_KG;

// Les moteurs, partagés entre la minuterie des pas (cœur 1) et la boucle (cœur 0).
static portMUX_TYPE verrou_moteurs = portMUX_INITIALIZER_UNLOCKED;
static moteur_t bras;
static moteur_t pompes[SPRAY_NB_FLACONS];
static spray_t spray;
static balance_t balances[SPRAY_NB_FLACONS];

// Le pilote du bras (tâche à part).
static volatile bool pilote_ok = true;
static volatile bool pilote_redemarre = false;

static QueueHandle_t file_uart;

// ------------------------------------------------------------ générateur de pas

static bool capteur_voit_le_bras(void) {
    // PC817 : bras rangé = broche à 0. Fil coupé = tirée à 1 = « pas rangé » (le Pi attend).
    return gpio_get_level(REGLAGE_BROCHE_BRAS_RANGE) == 0;
}

static bool au_tour(gptimer_handle_t minuterie, const gptimer_alarm_event_data_t *evenement,
                    void *contexte) {
    (void)minuterie;
    (void)evenement;
    (void)contexte;
    portENTER_CRITICAL_ISR(&verrou_moteurs);
    // Redescendre les impulsions du tour précédent.
    if (bras.impulsion) {
        gpio_set_level(REGLAGE_BROCHE_BRAS_PAS, 0);
    }
    for (int i = 0; i < SPRAY_NB_FLACONS; i++) {
        if (pompes[i].impulsion) {
            gpio_set_level(broches_pompes[i], 0);
        }
    }
    int pas = moteur_tick(&bras, capteur_voit_le_bras());
    if (pas) {
        // Sens d'abord (la notice du TMC2209 demande 20 ns avant le pas).
        gpio_set_level(REGLAGE_BROCHE_BRAS_SENS, (pas > 0) != REGLAGE_BRAS_SENS_INVERSE);
        gpio_set_level(REGLAGE_BROCHE_BRAS_PAS, 1);
    }
    for (int i = 0; i < SPRAY_NB_FLACONS; i++) {
        if (moteur_tick(&pompes[i], false)) {
            gpio_set_level(broches_pompes[i], 1);
        }
    }
    portEXIT_CRITICAL_ISR(&verrou_moteurs);
    return false;
}

// Lancée sur le cœur 1 : l'interruption de la minuterie y est attachée.
static void lancer_les_pas(void *argument) {
    (void)argument;
    gptimer_handle_t minuterie = NULL;
    gptimer_config_t config = {
        .clk_src = GPTIMER_CLK_SRC_DEFAULT,
        .direction = GPTIMER_COUNT_UP,
        .resolution_hz = 1000000,
    };
    ESP_ERROR_CHECK(gptimer_new_timer(&config, &minuterie));
    gptimer_event_callbacks_t rappels = {.on_alarm = au_tour};
    ESP_ERROR_CHECK(gptimer_register_event_callbacks(minuterie, &rappels, NULL));
    ESP_ERROR_CHECK(gptimer_enable(minuterie));
    gptimer_alarm_config_t alarme = {
        .alarm_count = REGLAGE_PERIODE_PAS_US,
        .reload_count = 0,
        .flags.auto_reload_on_alarm = true,
    };
    ESP_ERROR_CHECK(gptimer_set_alarm_action(minuterie, &alarme));
    ESP_ERROR_CHECK(gptimer_start(minuterie));
    vTaskDelete(NULL);
}

// ------------------------------------------------------------ HX711

static bool lire_dt(void *contexte) {
    return gpio_get_level(broches_dt[(intptr_t)contexte]);
}

static void ecrire_sck(void *contexte, bool haut) {
    gpio_set_level(broches_sck[(intptr_t)contexte], haut);
}

static void attendre_us(void *contexte, uint32_t us) {
    (void)contexte;
    esp_rom_delay_us(us);
}

static portMUX_TYPE verrou_hx711 = portMUX_INITIALIZER_UNLOCKED;

static void lire_les_balances(uint64_t t_us) {
    for (intptr_t i = 0; i < SPRAY_NB_FLACONS; i++) {
        broches_hx711_t broches = {lire_dt, ecrire_sck, attendre_us, (void *)i};
        if (!hx711_pret(&broches)) {
            continue;
        }
        // SCK ne doit jamais rester à 1 plus de 60 µs : pas d'interruption pendant la lecture
        // (environ 50 µs ; la minuterie des pas est sur l'autre cœur).
        portENTER_CRITICAL(&verrou_hx711);
        int32_t brut = hx711_lire(&broches);
        portEXIT_CRITICAL(&verrou_hx711);
        balance_mesure(&balances[i], brut, t_us);
    }
}

// ------------------------------------------------------------ pilote TMC2209 du bras

// Envoie une trame au pilote ; s'il faut une réponse (registre >= 0), la cherche après l'écho.
static bool echanger(const uint8_t *trame, size_t n, int registre, uint32_t *valeur) {
    uart_flush_input(UART_PILOTE);
    uart_write_bytes(UART_PILOTE, trame, n);
    uart_wait_tx_done(UART_PILOTE, pdMS_TO_TICKS(ATTENTE_PILOTE_MS));
    if (registre < 0) {
        // Le pilote ne répond pas à une écriture : un petit silence avant la trame suivante.
        vTaskDelay(pdMS_TO_TICKS(1));
        return true;
    }
    uint8_t recus[4 * TMC_REPONSE];
    int lus = uart_read_bytes(UART_PILOTE, recus, sizeof(recus), pdMS_TO_TICKS(ATTENTE_PILOTE_MS));
    return lus > 0 && tmc_chercher_reponse(recus, (size_t)lus, (uint8_t)registre, valeur);
}

static bool lire_pilote(uint8_t registre, uint32_t *valeur) {
    uint8_t q[TMC_QUESTION];
    tmc_question(q, REGLAGE_PILOTE_ADRESSE, registre);
    return echanger(q, sizeof(q), registre, valeur);
}

static void ecrire_pilote(uint8_t registre, uint32_t valeur) {
    uint8_t t[TMC_ECRITURE];
    tmc_ecriture(t, REGLAGE_PILOTE_ADRESSE, registre, valeur);
    echanger(t, sizeof(t), -1, NULL);
}

// Règle le pilote (courant, micro-pas) ; vrai s'il a tout reçu (son compteur d'écritures).
static bool regler_pilote(void) {
    uint32_t version = 0, avant = 0, apres = 0;
    if (!lire_pilote(TMC_IOIN, &version) || !tmc_version_juste(version)) {
        return false;
    }
    if (!lire_pilote(TMC_IFCNT, &avant)) {
        return false;
    }
    ecrire_pilote(TMC_GCONF, tmc_gconf());
    ecrire_pilote(TMC_CHOPCONF, tmc_chopconf(REGLAGE_PILOTE_MICRO_PAS, REGLAGE_PILOTE_VSENSE));
    ecrire_pilote(TMC_IHOLD_IRUN, tmc_ihold_irun(REGLAGE_PILOTE_IHOLD, REGLAGE_PILOTE_IRUN));
    // Effacer les bits de GSTAT (dont « reset »), pour voir le prochain redémarrage du pilote.
    ecrire_pilote(TMC_GSTAT, 7);
    if (!lire_pilote(TMC_IFCNT, &apres)) {
        return false;
    }
    return ((apres - avant) & 0xFF) == 4;
}

static void preparer_pilote(void) {
    uart_config_t config = {
        .baud_rate = REGLAGE_PILOTE_VITESSE_BAUDS,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(UART_PILOTE, 256, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(UART_PILOTE, &config));
    ESP_ERROR_CHECK(uart_set_pin(UART_PILOTE, REGLAGE_BROCHE_PILOTE_BRAS_TX,
                                 REGLAGE_BROCHE_PILOTE_BRAS_RX, UART_PIN_NO_CHANGE,
                                 UART_PIN_NO_CHANGE));
    gpio_pullup_en(REGLAGE_BROCHE_PILOTE_BRAS_RX);
}

// Tâche à part : relit le pilote ; s'il a redémarré (24 V coupé), le règle de nouveau.
static void surveiller_pilote(void *argument) {
    (void)argument;
    bool regle = pilote_ok;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(REGLAGE_PILOTE_LECTURE_MS));
        uint32_t gstat = 0;
        if (!regle) {
            regle = regler_pilote();
            pilote_ok = regle;
            // Le pilote n'a pas répondu un moment (24 V coupé, fil débranché) : des pas ont pu
            // se perdre. La prise d'origine est à refaire.
            if (regle) {
                pilote_redemarre = true;
            }
            continue;
        }
        if (!lire_pilote(TMC_GSTAT, &gstat)) {
            pilote_ok = regle = false;
        } else if (gstat & TMC_GSTAT_RESET) {
            pilote_redemarre = true;
            pilote_ok = regle = regler_pilote();
        }
    }
}

// ------------------------------------------------------------ RS485

static void preparer_bus(void) {
    // D'abord la ligne du bus en écoute.
    gpio_reset_pin(REGLAGE_BROCHE_RS485_SENS);
    gpio_set_direction(REGLAGE_BROCHE_RS485_SENS, GPIO_MODE_OUTPUT);
    gpio_set_level(REGLAGE_BROCHE_RS485_SENS, 0);
    uart_config_t config = {
        .baud_rate = REGLAGE_VITESSE_BAUDS,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(UART_BUS, TAMPON_UART, 0, FILE_UART, &file_uart, 0));
    ESP_ERROR_CHECK(uart_param_config(UART_BUS, &config));
    ESP_ERROR_CHECK(uart_set_pin(UART_BUS, REGLAGE_BROCHE_RS485_TX, REGLAGE_BROCHE_RS485_RX,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    // Ligne RX tirée au repos (1) : l'émetteur-récepteur en émission ne la laisse pas flotter.
    gpio_pullup_en(REGLAGE_BROCHE_RS485_RX);
    ESP_ERROR_CHECK(uart_set_rx_timeout(UART_BUS, SILENCE_UART_CARACTERES));
}

static void envoyer(const uint8_t *octets, size_t n) {
    // Laisser l'adaptateur du Pi repasser en écoute après sa question.
    esp_rom_delay_us(REGLAGE_DELAI_AVANT_REPONSE_US);
    gpio_set_level(REGLAGE_BROCHE_RS485_SENS, 1);
    uart_write_bytes(UART_BUS, octets, n);
    // Attendre que le dernier bit soit sorti avant de lâcher le bus (10 bits par octet).
    uart_wait_tx_done(UART_BUS, pdMS_TO_TICKS(10 + n * 10000 / REGLAGE_VITESSE_BAUDS));
    gpio_set_level(REGLAGE_BROCHE_RS485_SENS, 0);
    // Un émetteur-récepteur qui s'entend parler : l'écho est oublié.
    uart_flush_input(UART_BUS);
}

// ------------------------------------------------------------ sorties

static void sortie(int broche, int niveau) {
    gpio_reset_pin(broche);
    gpio_pullup_dis(broche);
    gpio_set_level(broche, niveau);
    gpio_set_direction(broche, GPIO_MODE_OUTPUT);
    gpio_set_level(broche, niveau);
}

static void eteindre_tout(void) {
    // Les sorties MOSFET éteintes, les pilotes des moteurs coupés (EN à 1), les pas à 0.
    sortie(REGLAGE_BROCHE_EV_BUSE, 0);
    sortie(REGLAGE_BROCHE_EV_CHASSE, 0);
    sortie(REGLAGE_BROCHE_POMPE_NETTOYAGE, 0);
    sortie(REGLAGE_BROCHE_AGITATEURS, 0);
    sortie(REGLAGE_BROCHE_ACTIVER_MOTEURS, 1);
    sortie(REGLAGE_BROCHE_BRAS_PAS, 0);
    sortie(REGLAGE_BROCHE_BRAS_SENS, 0);
    for (int i = 0; i < SPRAY_NB_FLACONS; i++) {
        sortie(broches_pompes[i], 0);
        sortie(broches_sck[i], 0);  // SCK à 0 : le HX711 mesure
        gpio_reset_pin(broches_dt[i]);
        gpio_set_direction(broches_dt[i], GPIO_MODE_INPUT);
        // HX711 débranché : DT tirée à 1 = jamais prêt = balance muette.
        gpio_pullup_en(broches_dt[i]);
    }
#if REGLAGE_BROCHE_POMPES_SENS >= 0
    // Les pompes ne tournent que dans un sens.
    sortie(REGLAGE_BROCHE_POMPES_SENS, !REGLAGE_POMPES_SENS_INVERSE);
#endif
#if REGLAGE_BROCHE_VOYANT >= 0
    sortie(REGLAGE_BROCHE_VOYANT, REGLAGE_VOYANT_ACTIF_BAS);
#endif
    gpio_reset_pin(REGLAGE_BROCHE_BRAS_RANGE);
    gpio_set_direction(REGLAGE_BROCHE_BRAS_RANGE, GPIO_MODE_INPUT);
    // Le PC817 a sa résistance de 10 kΩ vers le 3,3 V ; celle de la puce en plus ne gêne pas.
    gpio_pullup_en(REGLAGE_BROCHE_BRAS_RANGE);
}

static void preparer_agitateurs(void) {
    ledc_timer_config_t minuterie = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = RESOLUTION_PWM,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = REGLAGE_AGITATEURS_PWM_HZ,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&minuterie));
    ledc_channel_config_t voie = {
        .gpio_num = REGLAGE_BROCHE_AGITATEURS,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0,
        .timer_sel = LEDC_TIMER_0,
        .duty = 0,
        .hpoint = 0,
    };
    ESP_ERROR_CHECK(ledc_channel_config(&voie));
}

static void appliquer(const spray_sorties_t *s, uint8_t *agitateurs_avant) {
    gpio_set_level(REGLAGE_BROCHE_EV_BUSE, s->ev_buse);
    gpio_set_level(REGLAGE_BROCHE_EV_CHASSE, s->ev_chasse);
    gpio_set_level(REGLAGE_BROCHE_POMPE_NETTOYAGE, s->pompe_nettoyage);
    if (s->agitateurs_pct != *agitateurs_avant) {
        *agitateurs_avant = s->agitateurs_pct;
        ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, (uint32_t)s->agitateurs_pct * PWM_MAX / 100);
        ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
    }
}

static void allumer_voyant(uint64_t t_us) {
#if REGLAGE_BROCHE_VOYANT >= 0
    // Allumé : le Pi parle. Clignote : le Pi se tait (ou ne s'est jamais annoncé).
    bool muet = !spray.message_recu ||
                t_us - spray.dernier_message_us > (uint64_t)REGLAGE_SILENCE_MAX_MS * 1000u;
    bool allume = muet ? (t_us / CLIGNOTEMENT_US) % 2 == 0 : true;
    gpio_set_level(REGLAGE_BROCHE_VOYANT, allume != REGLAGE_VOYANT_ACTIF_BAS);
#else
    (void)t_us;
#endif
}

// ------------------------------------------------------------ compteur de démarrages

static uint16_t compter_le_demarrage(void) {
    esp_err_t erreur = nvs_flash_init();
    if (erreur == ESP_ERR_NVS_NO_FREE_PAGES || erreur == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        erreur = nvs_flash_init();
    }
    ESP_ERROR_CHECK(erreur);
    nvs_handle_t memoire;
    uint16_t demarrages = 0;
    if (nvs_open("spray", NVS_READWRITE, &memoire) == ESP_OK) {
        nvs_get_u16(memoire, "demarrages", &demarrages);
        demarrages++;
        nvs_set_u16(memoire, "demarrages", demarrages);
        nvs_commit(memoire);
        nvs_close(memoire);
    }
    return demarrages;
}

// ------------------------------------------------------------ fenêtre USB

// « -12,3 » : des dixièmes en texte.
static const char *en_texte(char *texte, size_t n, int32_t dixiemes) {
    int32_t positif = dixiemes < 0 ? -dixiemes : dixiemes;
    snprintf(texte, n, "%s%ld,%ld", dixiemes < 0 ? "-" : "", (long)(positif / 10),
             (long)(positif % 10));
    return texte;
}

static const char *suites[] = {"aucun", "en cours", "fait", "REFUSÉ", "ÉCHOUÉ"};
static const char *resultats[] = {"aucune", "en cours", "atteinte", "TEMPS MAX", "INTERROMPUE",
                                  "refusée"};

static void afficher(void *argument) {
    (void)argument;
    const esp_app_desc_t *programme = esp_app_get_description();
    printf("Carte du spray « %s », adresse %d sur le bus rs485_spray, %d bauds.\n",
           REGLAGE_NOM_SIGNAL, REGLAGE_ADRESSE, REGLAGE_VITESSE_BAUDS);
    printf("Version %s.%s\n", programme->version,
           REGLAGE_EXEMPLE ? " Réglages d'EXEMPLE (pi/reglages/machine.yaml → spray)." : "");
    printf("Démarrage n° %u.\n", spray.demarrages);
    if (esp_reset_reason() == ESP_RST_TASK_WDT) {
        printf("ATTENTION : la carte a redémarré par son chien de garde (programme figé).\n");
    }
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(REGLAGE_PERIODE_AFFICHAGE_MS));
        uint16_t r[SPRAY_NB_REGISTRES];
        bool capteur_brut;
        portENTER_CRITICAL(&verrou_moteurs);
        spray_registres(&spray, 0, r);
        capteur_brut = spray.capteur_brut;
        portEXIT_CRITICAL(&verrou_moteurs);
        char a[16], b[16];
        printf("bras %s° %s%s%s%s | capteur %s | pilote %s |", en_texte(a, sizeof(a), r[5]),
               (r[3] & SPRAY_ETAT_BRAS_RANGE) ? "rangé" : "pas rangé",
               (r[3] & SPRAY_ETAT_BRAS_SORTI) ? ", sorti" : "",
               (r[3] & SPRAY_ETAT_BRAS_BOUGE) ? ", bouge" : "",
               (r[3] & SPRAY_ETAT_ORIGINE_FAITE) ? "" : ", origine à faire",
               capteur_brut ? "voit le bras" : "ne voit rien", pilote_ok ? "ok" : "MUET");
        for (int i = 0; i < SPRAY_NB_FLACONS; i++) {
            int32_t brut = (int32_t)((uint32_t)r[10 + 2 * i] << 16 | r[11 + 2 * i]);
            if (r[4] & (1u << i)) {
                printf(" %d: MUETTE", i + 1);
            } else {
                printf(" %d: %s g (brut %ld)%s", i + 1, en_texte(a, sizeof(a), (int16_t)r[18 + i]),
                       (long)brut, (r[4] & (16u << i)) ? " INSTABLE" : "");
            }
        }
        printf(" | ordre n° %u %s", r[6], r[7] < 5 ? suites[r[7]] : "?");
        if (r[7] == SUITE_REFUSE) {
            printf(" (raison %u)", r[8]);
        }
        if (r[22]) {
            printf(" | dose %u : %s g sur %s g en %u ms, %s", r[22],
                   en_texte(a, sizeof(a), (int16_t)r[24]), en_texte(b, sizeof(b), r[23]), r[25],
                   r[26] < 6 ? resultats[r[26]] : "?");
        }
        if (r[3] & SPRAY_ETAT_SPRAY_EN_COURS) {
            printf(" | SPRAY");
        }
        if (r[3] & SPRAY_ETAT_NETTOYAGE_EN_COURS) {
            printf(" | NETTOYAGE");
        }
        if (r[28]) {
            printf(" | agitateurs %u %%", r[28]);
        }
        printf(" | Pi : %s", r[9] == 0xFFFF ? "jamais entendu" : "");
        if (r[9] != 0xFFFF) {
            printf("il y a %u ms", r[9]);
        }
        if (r[3] & SPRAY_ETAT_SILENCE_PI) {
            printf(" | ARRÊT SEULE (le Pi s'est tu)");
        }
        if (r[3] & SPRAY_ETAT_ARRET_IMMEDIAT) {
            printf(" | ARRÊT IMMÉDIAT");
        }
        if (r[4] & SPRAY_ERREURS_DU_BRAS) {
            printf(" | ERREURS 0x%04X", r[4] & SPRAY_ERREURS_DU_BRAS);
        }
        printf("\n");
    }
}

// ------------------------------------------------------------ programme

void app_main(void) {
    // D'abord tout éteint.
    eteindre_tout();
    uint16_t demarrages = compter_le_demarrage();
    preparer_agitateurs();
    preparer_bus();
    preparer_pilote();

    uint64_t t0 = (uint64_t)esp_timer_get_time();
    for (int i = 0; i < SPRAY_NB_FLACONS; i++) {
        balance_init(&balances[i], zero_brut[i], brut_par_kg[i], REGLAGE_BALANCES_MOYENNE_DE,
                     REGLAGE_BALANCES_SANS_MESURE_MS, REGLAGE_BALANCES_INSTABLE_DIXIEMES);
        moteur_init(&pompes[i], REGLAGE_POMPES_VITESSE_PAS_S, REGLAGE_POMPES_ACCELERATION_PAS_S2,
                    REGLAGE_PERIODE_PAS_US);
    }
    moteur_init(&bras, REGLAGE_BRAS_VITESSE_PAS_S, REGLAGE_BRAS_ACCELERATION_PAS_S2,
                REGLAGE_PERIODE_PAS_US);
    spray_reglages_t reglages = {
        .exemple = REGLAGE_EXEMPLE,
        .course_dixiemes = REGLAGE_BRAS_COURSE_DIXIEMES,
        .bras_pas_par_tour = REGLAGE_BRAS_PAS_PAR_TOUR,
        .bras_depassement_pas = REGLAGE_BRAS_DEPASSEMENT_PAS,
        .bras_temps_max_ms = REGLAGE_BRAS_TEMPS_MAX_MS,
        .filtre_capteur_ms = REGLAGE_BRAS_FILTRE_CAPTEUR_MS,
        .air_avant_ms = REGLAGE_AIR_AVANT_MS,
        .temps_max_pompage_ms = REGLAGE_TEMPS_MAX_POMPAGE_MS,
        .chasse_ms = REGLAGE_CHASSE_MS,
        .air_apres_ms = REGLAGE_AIR_APRES_MS,
        .nettoyage_pompe_ms = REGLAGE_NETTOYAGE_POMPE_MS,
        .sechage_ms = REGLAGE_SECHAGE_MS,
        .silence_max_ms = REGLAGE_SILENCE_MAX_MS,
    };
    moteur_t *pointeurs_pompes[SPRAY_NB_FLACONS];
    for (int i = 0; i < SPRAY_NB_FLACONS; i++) {
        pointeurs_pompes[i] = &pompes[i];
    }
    spray_init(&spray, &reglages, &bras, pointeurs_pompes, balances, demarrages, t0);

    // Le pilote du bras réglé (courant, micro-pas), puis les 5 pilotes alimentés.
    pilote_ok = regler_pilote();
    gpio_set_level(REGLAGE_BROCHE_ACTIVER_MOTEURS, 0);

    esp_task_wdt_config_t chien = {
        .timeout_ms = REGLAGE_CHIEN_DE_GARDE_MS,
        .idle_core_mask = 0,
        .trigger_panic = true,
    };
    ESP_ERROR_CHECK(esp_task_wdt_reconfigure(&chien));
    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));
    // Le générateur de pas seul sur le cœur 1.
    xTaskCreatePinnedToCore(lancer_les_pas, "pas", 4096, NULL, configMAX_PRIORITIES - 2, NULL, 1);
    // La boucle avant le reste ; le pilote et la fenêtre USB à part, moins pressés.
    vTaskPrioritySet(NULL, configMAX_PRIORITIES - 5);
    xTaskCreatePinnedToCore(surveiller_pilote, "pilote", 4096, NULL, tskIDLE_PRIORITY + 2, NULL,
                            0);
    xTaskCreatePinnedToCore(afficher, "affichage", 4096, NULL, tskIDLE_PRIORITY + 1, NULL, 0);

    // La boucle calcule en virgule flottante sous le verrou des moteurs (poids des balances) :
    // une première fois ici, hors du verrou, pour que le cœur prépare sa virgule flottante.
    volatile float echauffement = 1.0f;
    echauffement = echauffement * 2.0f;

    modbus_t bus;
    modbus_init(&bus, REGLAGE_ADRESSE);
    uint8_t reponse[MODBUS_REPONSE_MAX];
    uint8_t recus[TAMPON_UART];
    uint64_t dernier_octet_us = 0;
    uint8_t agitateurs = 0;

    for (;;) {
        esp_task_wdt_reset();
        uart_event_t evenement;
        if (xQueueReceive(file_uart, &evenement, pdMS_TO_TICKS(ATTENTE_MAX_MS)) == pdTRUE) {
            if (evenement.type == UART_DATA) {
                size_t a_lire = evenement.size < sizeof(recus) ? evenement.size : sizeof(recus);
                int n = uart_read_bytes(UART_BUS, recus, a_lire, 0);
                uint64_t t_lecture = (uint64_t)esp_timer_get_time();
                for (int i = 0; i < n; i++) {
                    uint64_t t_us = spray_heure_octet(t_lecture, (size_t)n, (size_t)i,
                                                      REGLAGE_VITESSE_BAUDS, &dernier_octet_us);
                    if (modbus_recevoir(&bus, recus[i], t_us)) {
                        uint64_t maintenant = (uint64_t)esp_timer_get_time();
                        portENTER_CRITICAL(&verrou_moteurs);
                        size_t taille = spray_repondre(&spray, &bus, maintenant, reponse);
                        portEXIT_CRITICAL(&verrou_moteurs);
                        envoyer(reponse, taille);
                        modbus_oublier(&bus);
                    }
                }
            } else if (evenement.type == UART_FIFO_OVF || evenement.type == UART_BUFFER_FULL) {
                // Trop d'octets d'un coup : tout oublier, la question suivante sera entendue.
                uart_flush_input(UART_BUS);
                xQueueReset(file_uart);
                modbus_oublier(&bus);
            }
        }
        uint64_t t_us = (uint64_t)esp_timer_get_time();
        lire_les_balances(t_us);
        bool capteur = capteur_voit_le_bras();
        bool redemarre = pilote_redemarre;
        pilote_redemarre = false;
        portENTER_CRITICAL(&verrou_moteurs);
        if (redemarre) {
            spray_pilote_redemarre(&spray);
        }
        spray_avancer(&spray, capteur, pilote_ok, t_us);
        spray_sorties_t sorties = spray_sorties(&spray);
        portEXIT_CRITICAL(&verrou_moteurs);
        appliquer(&sorties, &agitateurs);
        allumer_voyant(t_us);
    }
}
