// Les mesures de la carte et la table de registres que le Pi lit (Modbus, fonction 3 ou 4).
// Aucun matériel ici (essayé sur PC).
//
// | Registre | Contenu |
// |---|---|
// | 0 et 1 | dernière mesure brute du HX711 (nombre signé de 32 bits, le mot fort d'abord) |
// | 2 | numéro de cette mesure (+1 à chaque mesure, repart à 0 après 65 535) |
// | 3 | âge de cette mesure en ms (65 535 au plus) |
// | 4 | état : 1 = HX711 muet (débranché ?), 2 = programme fait avec des réglages d'exemple |
// | 5 | mesures faites pendant la dernière seconde (80 attendues) |
// | 6 | questions pour cette carte arrivées abîmées, depuis le démarrage (repart à 0 après 65 535) |
// | 7 | signature 0x5053 (« PS ») : c'est bien une carte de pesée |
//
// Le Pi lit les 8 d'un coup (pi/vidange/pesees/). La valeur en kilogrammes est calculée par le
// Pi (étalonnage dans pi/reglages/pesees.yaml) : la carte ne donne que la mesure brute.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define REGISTRE_BRUT_FORT 0
#define REGISTRE_BRUT_FAIBLE 1
#define REGISTRE_NUMERO 2
#define REGISTRE_AGE_MS 3
#define REGISTRE_ETAT 4
#define REGISTRE_PAR_SECONDE 5
#define REGISTRE_TRAMES_ABIMEES 6
#define REGISTRE_SIGNATURE 7
#define NB_REGISTRES 8

#define ETAT_HX711_MUET 1
#define ETAT_EXEMPLE 2
#define SIGNATURE 0x5053

typedef struct {
    uint32_t sans_mesure_ms;  // plus de mesure depuis ce temps : HX711 muet
    bool exemple;             // réglages d'exemple
    bool une_mesure;
    int32_t brut;
    uint16_t numero;
    uint64_t heure_us;        // de la dernière mesure
    uint64_t debut_seconde_us;
    uint16_t compte;          // mesures depuis debut_seconde_us
    uint16_t par_seconde;     // mesures pendant la dernière seconde complète
} mesures_t;

void mesures_init(mesures_t *m, uint32_t sans_mesure_ms, bool exemple, uint64_t t_us);

// Une mesure lue du HX711 à l'heure t_us.
void mesures_noter(mesures_t *m, int32_t brut, uint64_t t_us);

// Le temps passe (compte des mesures par seconde) : à appeler souvent.
void mesures_avancer(mesures_t *m, uint64_t t_us);

bool mesures_muet(const mesures_t *m, uint64_t t_us);

// Remplit la table des NB_REGISTRES registres, à l'heure t_us.
void mesures_registres(const mesures_t *m, uint16_t trames_abimees, uint64_t t_us,
                       uint16_t *registres);
