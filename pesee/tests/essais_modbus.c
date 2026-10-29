// Essais du Modbus RTU côté carte : questions, réponses, et ce que la carte entend des autres.
#include "essai.h"
#include "modbus.h"

// Un octet toutes les 87 µs (115 200 bauds).
#define OCTET_US 87

static uint64_t heure_us = 1000000;

static void question(uint8_t *trame, uint8_t adresse, uint8_t fonction, uint16_t premier,
                     uint16_t nombre) {
    trame[0] = adresse;
    trame[1] = fonction;
    trame[2] = (uint8_t)(premier >> 8);
    trame[3] = (uint8_t)premier;
    trame[4] = (uint8_t)(nombre >> 8);
    trame[5] = (uint8_t)nombre;
    uint16_t crc = modbus_crc(trame, 6);
    trame[6] = (uint8_t)crc;
    trame[7] = (uint8_t)(crc >> 8);
}

// Envoie les octets à la carte ; rend le nombre de fois où elle a dit « question pour moi ».
static int recevoir(modbus_t *m, const uint8_t *octets, size_t n) {
    int pour_moi = 0;
    for (size_t i = 0; i < n; i++) {
        heure_us += OCTET_US;
        pour_moi += modbus_recevoir(m, octets[i], heure_us);
    }
    return pour_moi;
}

static const uint16_t table[8] = {0x0012, 0x3456, 7, 3, 0, 80, 0, 0x5053};

static void crc_connu(void) {
    // Exemple classique : 01 03 00 00 00 0A → contrôle C5 CD.
    uint8_t trame[6] = {0x01, 0x03, 0x00, 0x00, 0x00, 0x0A};
    VERIFIER(modbus_crc(trame, 6) == 0xCDC5);
}

static void lecture_des_registres(void) {
    modbus_t m;
    modbus_init(&m, 1);
    uint8_t q[8], r[MODBUS_REPONSE_MAX];
    question(q, 1, 4, 0, 8);
    VERIFIER(recevoir(&m, q, 8) == 1);
    size_t n = modbus_repondre(&m, table, 8, r);
    VERIFIER(n == 21);
    VERIFIER(r[0] == 1 && r[1] == 4 && r[2] == 16);
    VERIFIER(r[3] == 0x00 && r[4] == 0x12 && r[5] == 0x34 && r[6] == 0x56);
    VERIFIER(r[17] == 0x50 && r[18] == 0x53);
    uint16_t crc = modbus_crc(r, 19);
    VERIFIER(r[19] == (uint8_t)crc && r[20] == (uint8_t)(crc >> 8));
    // Fonction 3 : la même table ; un morceau seulement.
    question(q, 1, 3, 5, 1);
    VERIFIER(recevoir(&m, q, 8) == 1);
    n = modbus_repondre(&m, table, 8, r);
    VERIFIER(n == 7 && r[1] == 3 && r[2] == 2 && r[3] == 0 && r[4] == 80);
}

static void exceptions(void) {
    modbus_t m;
    modbus_init(&m, 1);
    uint8_t q[8], r[MODBUS_REPONSE_MAX];
    question(q, 1, 6, 0, 1);
    recevoir(&m, q, 8);
    VERIFIER(modbus_repondre(&m, table, 8, r) == 5 && r[1] == 0x86 && r[2] == 1);
    question(q, 1, 4, 4, 5);
    recevoir(&m, q, 8);
    VERIFIER(modbus_repondre(&m, table, 8, r) == 5 && r[1] == 0x84 && r[2] == 2);
    question(q, 1, 4, 0, 0);
    recevoir(&m, q, 8);
    VERIFIER(modbus_repondre(&m, table, 8, r) == 5 && r[2] == 3);
    uint16_t crc = modbus_crc(r, 3);
    VERIFIER(r[3] == (uint8_t)crc && r[4] == (uint8_t)(crc >> 8));
}

static void ignore_les_autres_cartes(void) {
    // Le Pi interroge la carte 2, elle répond, puis le Pi interroge la carte 1 sans attendre :
    // la carte 1 doit sauter la réponse de la carte 2 et entendre sa propre question.
    modbus_t carte1, carte2;
    modbus_init(&carte1, 1);
    modbus_init(&carte2, 2);
    uint8_t q2[8], q1[8], r2[MODBUS_REPONSE_MAX];
    question(q2, 2, 4, 0, 8);
    question(q1, 1, 4, 0, 8);
    VERIFIER(recevoir(&carte1, q2, 8) == 0);
    VERIFIER(recevoir(&carte2, q2, 8) == 1);
    size_t n = modbus_repondre(&carte2, table, 8, r2);
    heure_us += 300;
    // La réponse de la carte 2 commence comme une question juste pour la carte 1 ? Peu importe :
    // elle est comptée comme une réponse, jamais lue comme une question.
    VERIFIER(recevoir(&carte1, r2, n) == 0);
    heure_us += 500;
    VERIFIER(recevoir(&carte1, q1, 8) == 1);
    VERIFIER(carte1.trames_abimees == 0);
    // Même chose avec une exception de la carte 2 (5 octets).
    uint8_t q2f[8], e2[MODBUS_REPONSE_MAX];
    question(q2f, 2, 6, 0, 1);
    VERIFIER(recevoir(&carte1, q2f, 8) == 0);
    VERIFIER(recevoir(&carte2, q2f, 8) == 1);
    n = modbus_repondre(&carte2, table, 8, e2);
    VERIFIER(recevoir(&carte1, e2, n) == 0);
    VERIFIER(recevoir(&carte1, q1, 8) == 1);
}

static void carte_absente(void) {
    // Question à une carte absente : pas de réponse, puis un silence ; la question suivante
    // pour la carte 1 est entendue.
    modbus_t m;
    modbus_init(&m, 1);
    uint8_t q3[8], q1[8];
    question(q3, 3, 4, 0, 8);
    question(q1, 1, 4, 0, 8);
    recevoir(&m, q3, 8);
    heure_us += 20000;
    VERIFIER(recevoir(&m, q1, 8) == 1);
}

static void message_a_tous(void) {
    // Personne ne répond à l'adresse 0 : la question suivante vient tout de suite.
    modbus_t m;
    modbus_init(&m, 1);
    uint8_t q0[8], q1[8];
    question(q0, 0, 4, 0, 8);
    question(q1, 1, 4, 0, 8);
    VERIFIER(recevoir(&m, q0, 8) == 0);
    VERIFIER(recevoir(&m, q1, 8) == 1);
}

static void trame_abimee_puis_silence(void) {
    modbus_t m;
    modbus_init(&m, 1);
    uint8_t q[8];
    question(q, 1, 4, 0, 8);
    q[3] ^= 0x10;  // un parasite
    VERIFIER(recevoir(&m, q, 8) == 0);
    VERIFIER(m.trames_abimees == 1);
    question(q, 1, 4, 0, 8);
    // Sans silence, la carte attend encore la fin de la trame abîmée.
    VERIFIER(recevoir(&m, q, 8) == 0);
    heure_us += 2000;
    VERIFIER(recevoir(&m, q, 8) == 1);
    // Un morceau de trame, un silence, puis une question entière.
    VERIFIER(recevoir(&m, q, 3) == 0);
    heure_us += 2000;
    VERIFIER(recevoir(&m, q, 8) == 1);
    VERIFIER(m.trames_abimees == 1);
}

void essais_modbus(void) {
    printf("Modbus\n");
    LANCER(crc_connu);
    LANCER(lecture_des_registres);
    LANCER(exceptions);
    LANCER(ignore_les_autres_cartes);
    LANCER(carte_absente);
    LANCER(message_a_tous);
    LANCER(trame_abimee_puis_silence);
}
