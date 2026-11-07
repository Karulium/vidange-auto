// Essais du bus de la carte du spray : fonctions permises, registres permis, réponses.
#include "essai.h"
#include "monde.h"

static void lecture_de_la_table(void) {
    monde_t w;
    monde_init(&w);
    uint8_t q[8], rep[MODBUS_REPONSE_MAX];
    monde_trame_lecture(q, 1, 4, 0, 30);
    size_t n = monde_question(&w, q, 8, rep);
    // 65 octets (≈ 6 ms à 115 200 bauds).
    VERIFIER(n == 65 && rep[0] == 1 && rep[1] == 4 && rep[2] == 60);
    VERIFIER(rep[3] == 0x53 && rep[4] == 0x50);
    uint16_t crc = modbus_crc(rep, 63);
    VERIFIER(rep[63] == (uint8_t)crc && rep[64] == (uint8_t)(crc >> 8));
    // Un morceau seulement.
    monde_trame_lecture(q, 1, 4, 2, 1);
    n = monde_question(&w, q, 8, rep);
    VERIFIER(n == 7 && rep[3] == 0 && rep[4] == 7);
    // Au-delà du registre 29 : exception 2.
    monde_trame_lecture(q, 1, 4, 0, 31);
    n = monde_question(&w, q, 8, rep);
    VERIFIER(n == 5 && rep[1] == 0x84 && rep[2] == 2);
}

static void fonctions_refusees(void) {
    monde_t w;
    monde_init(&w);
    uint8_t q[8], rep[MODBUS_REPONSE_MAX];
    // Fonction 3 : la table ne se lit qu'en fonction 4.
    monde_trame_lecture(q, 1, 3, 0, 30);
    VERIFIER(monde_question(&w, q, 8, rep) == 5 && rep[1] == 0x83 && rep[2] == 1);
    monde_trame_lecture(q, 1, 6, 100, 1);
    VERIFIER(monde_question(&w, q, 8, rep) == 5 && rep[1] == 0x86 && rep[2] == 1);
    // Une autre adresse : pas de réponse.
    monde_trame_lecture(q, 2, 4, 0, 30);
    VERIFIER(monde_question(&w, q, 8, rep) == 0);
}

static void ecritures(void) {
    monde_t w;
    monde_init(&w);
    uint8_t q[MODBUS_TRAME_MAX], rep[MODBUS_REPONSE_MAX];
    uint16_t v[6] = {1, 6, 40, 5, 1, 0};
    // Registres 100 à 104 d'un coup : accusé de 8 octets, et l'ordre est exécuté.
    size_t n = monde_trame_ecriture(q, 1, 100, v, 5);
    VERIFIER(monde_question(&w, q, n, rep) == 8);
    VERIFIER(rep[1] == 16 && rep[3] == 100 && rep[5] == 5);
    uint16_t r[SPRAY_NB_REGISTRES];
    monde_lire(&w, r);
    VERIFIER(r[28] == 40 && r[6] == 1);
    // Hors de 100 à 104 : exception 2, rien n'est fait.
    n = monde_trame_ecriture(q, 1, 99, v, 2);
    VERIFIER(monde_question(&w, q, n, rep) == 5 && rep[1] == 0x90 && rep[2] == 2);
    n = monde_trame_ecriture(q, 1, 104, v, 2);
    VERIFIER(monde_question(&w, q, n, rep) == 5 && rep[2] == 2);
    n = monde_trame_ecriture(q, 1, 0, v, 1);
    VERIFIER(monde_question(&w, q, n, rep) == 5 && rep[2] == 2);
    monde_lire(&w, r);
    VERIFIER(r[6] == 1);
}

static void heure_des_octets(void) {
    // 3 octets lus d'un coup à 10 000 µs, 115 200 bauds (86 µs par octet).
    uint64_t precedent = 0;
    VERIFIER(spray_heure_octet(10000, 3, 0, 115200, &precedent) == 10000 - 2 * 86);
    VERIFIER(spray_heure_octet(10000, 3, 1, 115200, &precedent) == 10000 - 86);
    VERIFIER(spray_heure_octet(10000, 3, 2, 115200, &precedent) == 10000);
    // Jamais avant le précédent.
    VERIFIER(spray_heure_octet(9000, 1, 0, 115200, &precedent) == 10000);
}

void essais_bus(void) {
    printf("Bus du spray\n");
    LANCER(lecture_de_la_table);
    LANCER(fonctions_refusees);
    LANCER(ecritures);
    LANCER(heure_des_octets);
}
