// Essais de la boîte du poste sans le matériel : fausses trames radio, registres, radio muette,
// trames perdues, adresse radio, heure des octets du bus.
#include <string.h>

#include "boite.h"
#include "essai.h"
#include "modbus.h"

#define MS 1000ull
#define S 1000000ull

static const uint8_t plateau[6] = {0x02, 0x50, 0x46, 0x00, 0x00, 0x01};
static const uint8_t intrus[6] = {0x24, 0x6F, 0x28, 0x11, 0x22, 0x33};

static trame_t trame(uint16_t numero, int32_t brut) {
    trame_t t = {.numero = numero,
                 .brut = brut,
                 .au_poste = true,
                 .recharge_presente = true,
                 .accu_mv = 3950,
                 .accu_pct = 78};
    return t;
}

static boite_reception_t envoyer(boite_t *b, const uint8_t *adresse, const trame_t *t,
                                 int8_t signal, uint64_t t_us) {
    uint8_t octets[TRAME_TAILLE];
    trame_ecrire(t, octets);
    return boite_recevoir(b, adresse, octets, sizeof(octets), signal, t_us);
}

static void avant_la_premiere_trame(void) {
    boite_t b;
    boite_init(&b, 2000, false, plateau, 3 * S);
    uint16_t r[BOITE_NB_REGISTRES];
    boite_registres(&b, 0, 3 * S + 10 * MS, r);
    VERIFIER(r[3] == 65535);
    VERIFIER(r[4] == BOITE_ETAT_RADIO_MUETTE);
    VERIFIER(r[7] == 0x5046);
    VERIFIER(r[8] == 0 && r[9] == 0 && r[10] == 0 && r[11] == 0 && r[12] == 0);
}

static void registres_d_une_trame(void) {
    boite_t b;
    boite_init(&b, 2000, false, plateau, 0);
    trame_t t = trame(10, -300000);
    VERIFIER(envoyer(&b, plateau, &t, -58, 1 * S) == BOITE_TRAME_PRISE);
    uint16_t r[BOITE_NB_REGISTRES];
    boite_registres(&b, 3, 1 * S + 250 * MS, r);
    uint32_t brut = (uint32_t)r[0] << 16 | r[1];
    VERIFIER((int32_t)brut == -300000);
    VERIFIER(r[2] == 1);    // la boîte compte ses trames reçues, pas le numéro du plateau
    VERIFIER(r[3] == 250);  // âge en ms
    VERIFIER(r[4] == 0);
    VERIFIER(r[6] == 3);    // questions abîmées (Modbus)
    VERIFIER(r[7] == BOITE_SIGNATURE);
    VERIFIER(r[8] == (BOITE_PLATEAU_AU_POSTE | BOITE_PLATEAU_RECHARGE_PRESENTE));
    VERIFIER(r[9] == 3950 && r[10] == 78);
    VERIFIER(r[11] == 142);  // -58 dBm + 200
    VERIFIER(r[12] == 0);
}

static void recharge_presente_accu_plein(void) {
    // Le bit 1 (valeur 2) du registre 8 est recopié tel quel : « 5 V de la recharge présent »,
    // même accu plein (100 %) — sinon le Pi dirait « recharge sans contact en panne ? ».
    boite_t b;
    boite_init(&b, 2000, false, plateau, 0);
    trame_t t = trame(1, 0);
    t.accu_mv = 4200;
    t.accu_pct = 100;
    envoyer(&b, plateau, &t, -60, 1 * S);
    uint16_t r[BOITE_NB_REGISTRES];
    boite_registres(&b, 0, 1 * S, r);
    VERIFIER(r[8] & BOITE_PLATEAU_RECHARGE_PRESENTE);
    VERIFIER(r[10] == 100);
    // Plateau sur l'USB-C, sans la recharge sans contact.
    t = trame(2, 0);
    t.recharge_presente = false;
    t.sur_usb = true;
    t.au_poste = false;
    envoyer(&b, plateau, &t, -60, 1 * S + 500 * MS);
    boite_registres(&b, 0, 1 * S + 500 * MS, r);
    VERIFIER(r[8] == BOITE_PLATEAU_SUR_USB);
}

static void etat_hx711_muet_et_exemple(void) {
    boite_t b;
    boite_init(&b, 2000, false, plateau, 0);
    trame_t t = trame(1, 0);
    t.hx711_muet = true;
    t.exemple = true;
    envoyer(&b, plateau, &t, -60, 1 * S);
    uint16_t r[BOITE_NB_REGISTRES];
    boite_registres(&b, 0, 1 * S, r);
    VERIFIER(r[4] == (BOITE_ETAT_HX711_MUET | BOITE_ETAT_EXEMPLE));
    // Réglages d'exemple dans la boîte elle-même.
    boite_t c;
    boite_init(&c, 2000, true, plateau, 0);
    t = trame(1, 0);
    envoyer(&c, plateau, &t, -60, 1 * S);
    boite_registres(&c, 0, 1 * S, r);
    VERIFIER(r[4] == BOITE_ETAT_EXEMPLE);
}

static void radio_muette_apres_2_s(void) {
    boite_t b;
    boite_init(&b, 2000, false, plateau, 0);
    trame_t t = trame(1, 777);
    envoyer(&b, plateau, &t, -60, 1 * S);
    uint16_t r[BOITE_NB_REGISTRES];
    boite_registres(&b, 0, 3 * S, r);
    VERIFIER(!(r[4] & BOITE_ETAT_RADIO_MUETTE));  // 2 s pile : pas encore
    boite_registres(&b, 0, 3 * S + 1 * MS, r);
    VERIFIER(r[4] & BOITE_ETAT_RADIO_MUETTE);
    VERIFIER(r[3] == 2001);
    // La dernière mesure reste lisible (le Pi la refuse : radio muette).
    VERIFIER(r[1] == 777);
    // Très longtemps après : l'âge reste à 65 535.
    boite_registres(&b, 0, 100 * S, r);
    VERIFIER(r[3] == 65535);
    // Une trame revient : la pesée revient seule.
    t = trame(2, 778);
    envoyer(&b, plateau, &t, -60, 101 * S);
    boite_registres(&b, 0, 101 * S, r);
    VERIFIER(!(r[4] & BOITE_ETAT_RADIO_MUETTE) && r[1] == 778 && r[3] == 0);
}

static void seulement_l_adresse_du_plateau(void) {
    boite_t b;
    boite_init(&b, 2000, false, plateau, 0);
    trame_t t = trame(1, 555);
    VERIFIER(envoyer(&b, intrus, &t, -40, 1 * S) == BOITE_TRAME_AUTRE_ADRESSE);
    VERIFIER(b.autre_adresse == 1 && memcmp(b.derniere_autre_adresse, intrus, 6) == 0);
    uint16_t r[BOITE_NB_REGISTRES];
    boite_registres(&b, 0, 1 * S, r);
    VERIFIER(r[2] == 0 && (r[4] & BOITE_ETAT_RADIO_MUETTE) && r[1] == 0);
    VERIFIER(envoyer(&b, plateau, &t, -40, 1 * S) == BOITE_TRAME_PRISE);
}

static void trames_abimees_et_en_double(void) {
    boite_t b;
    boite_init(&b, 2000, false, plateau, 0);
    trame_t t = trame(1, 1);
    uint8_t octets[TRAME_TAILLE];
    trame_ecrire(&t, octets);
    octets[6] ^= 1;
    VERIFIER(boite_recevoir(&b, plateau, octets, sizeof(octets), -60, 1 * S) ==
             BOITE_TRAME_ABIMEE);
    VERIFIER(boite_recevoir(&b, plateau, octets, 3, -60, 1 * S) == BOITE_TRAME_ABIMEE);
    VERIFIER(b.abimees == 2 && !b.une_trame);
    VERIFIER(envoyer(&b, plateau, &t, -60, 1 * S) == BOITE_TRAME_PRISE);
    // La même trame deux fois (la radio la répète si l'accusé de réception s'est perdu).
    VERIFIER(envoyer(&b, plateau, &t, -60, 1 * S + 5 * MS) == BOITE_TRAME_EN_DOUBLE);
    VERIFIER(b.numero == 1 && b.perdues == 0);
}

static void trames_perdues(void) {
    boite_t b;
    boite_init(&b, 2000, false, plateau, 0);
    trame_t t = trame(100, 0);
    envoyer(&b, plateau, &t, -60, 1 * S);
    t = trame(101, 0);
    envoyer(&b, plateau, &t, -60, 1 * S + 500 * MS);
    // 102 et 103 perdues.
    t = trame(104, 0);
    envoyer(&b, plateau, &t, -60, 3 * S);
    VERIFIER(b.perdues == 2);
    // Passage de 65 535 à 0 : rien de perdu.
    t = trame(65535, 0);
    boite_t c;
    boite_init(&c, 2000, false, plateau, 0);
    envoyer(&c, plateau, &t, -60, 1 * S);
    t = trame(0, 0);
    envoyer(&c, plateau, &t, -60, 1 * S + 500 * MS);
    VERIFIER(c.perdues == 0 && c.numero == 2);
    // Après un long silence (plateau endormi, ou trop loin) : la radio muette l'a dit, les
    // numéros sautés ne comptent pas.
    t = trame(110, 0);
    envoyer(&b, plateau, &t, -60, 60 * S);
    VERIFIER(b.perdues == 2);
    // Plateau rallumé (accu changé) : son numéro repart de 1, en arrière : rien de compté.
    t = trame(1, 0);
    envoyer(&b, plateau, &t, -60, 60 * S + 500 * MS);
    VERIFIER(b.perdues == 2 && b.derniere.numero == 1);
    uint16_t r[BOITE_NB_REGISTRES];
    boite_registres(&b, 0, 60 * S + 500 * MS, r);
    VERIFIER(r[12] == 2);
}

static void trames_par_seconde(void) {
    boite_t b;
    boite_init(&b, 2000, false, plateau, 0);
    uint16_t numero = 1;
    for (uint64_t t_us = 250 * MS; t_us < 5 * S; t_us += 500 * MS) {
        trame_t t = trame(numero++, 0);
        envoyer(&b, plateau, &t, -60, t_us);
        boite_avancer(&b, t_us + 1 * MS);
    }
    uint16_t r[BOITE_NB_REGISTRES];
    boite_registres(&b, 0, 5 * S, r);
    VERIFIER(r[5] == 2);
    // Plus rien : 0 par seconde.
    boite_avancer(&b, 6 * S + 1 * MS);
    boite_avancer(&b, 7 * S + 2 * MS);
    boite_registres(&b, 0, 7 * S + 2 * MS, r);
    VERIFIER(r[5] == 0);
}

static void signal_borne(void) {
    boite_t b;
    boite_init(&b, 2000, false, plateau, 0);
    trame_t t = trame(1, 0);
    envoyer(&b, plateau, &t, -100, 1 * S);
    uint16_t r[BOITE_NB_REGISTRES];
    boite_registres(&b, 0, 1 * S, r);
    VERIFIER(r[11] == 100);  // -100 dBm
}

static void heure_des_octets_du_bus(void) {
    // 115 200 bauds : un octet toutes les 86 µs. Un paquet de 4 octets lu à 10 000 µs.
    uint64_t precedent = 0;
    VERIFIER(boite_heure_octet(10000, 4, 0, 115200, &precedent) == 10000 - 3 * 86);
    VERIFIER(boite_heure_octet(10000, 4, 3, 115200, &precedent) == 10000);
    // Le temps ne recule jamais.
    VERIFIER(boite_heure_octet(9000, 2, 0, 115200, &precedent) == 10000);
}

// Le Pi pose ses questions sans silence (questions aux autres cartes, leurs réponses, puis la
// question à la boîte) ; le pilote de l'UART coupe ce flux continu en paquets de 120 octets au
// plus. Avec l'heure de chaque octet, la question à la boîte est entendue.
static void flux_continu_en_paquets(void) {
    modbus_t m;
    modbus_init(&m, 4);
    uint8_t flux[400];
    size_t n = 0;
    // Deux tours de questions et réponses des cartes 1, 2, 1, 3 (8 octets + 21 octets chacune) :
    // 232 octets, puis la question à la boîte : 2 paquets pleins.
    uint8_t cartes[] = {1, 2, 1, 3, 1, 2, 1, 3};
    for (size_t c = 0; c < sizeof(cartes); c++) {
        uint8_t *q = &flux[n];
        q[0] = cartes[c];
        q[1] = 4;
        q[2] = 0;
        q[3] = 0;
        q[4] = 0;
        q[5] = 8;
        uint16_t crc = modbus_crc(q, 6);
        q[6] = (uint8_t)crc;
        q[7] = (uint8_t)(crc >> 8);
        n += 8;
        uint8_t *r = &flux[n];
        r[0] = cartes[c];
        r[1] = 4;
        r[2] = 16;
        for (int i = 0; i < 16; i++) {
            r[3 + i] = (uint8_t)(0x11 * i);
        }
        crc = modbus_crc(r, 19);
        r[19] = (uint8_t)crc;
        r[20] = (uint8_t)(crc >> 8);
        n += 21;
    }
    uint8_t *q = &flux[n];
    q[0] = 4;
    q[1] = 4;
    q[2] = 0;
    q[3] = 0;
    q[4] = 0;
    q[5] = 13;
    uint16_t crc = modbus_crc(q, 6);
    q[6] = (uint8_t)crc;
    q[7] = (uint8_t)(crc >> 8);
    n += 8;
    // Paquets de 120 octets, chacun lu juste après son dernier octet (+ 30 µs).
    uint64_t precedent = 0;
    int pour_moi = 0;
    for (size_t debut = 0; debut < n; debut += 120) {
        size_t taille = n - debut < 120 ? n - debut : 120;
        uint64_t t_lecture = 1000000 + (debut + taille) * 86 + 30;
        for (size_t i = 0; i < taille; i++) {
            uint64_t t = boite_heure_octet(t_lecture, taille, i, 115200, &precedent);
            pour_moi += modbus_recevoir(&m, flux[debut + i], t);
        }
    }
    VERIFIER(pour_moi == 1);
    VERIFIER(m.trames_abimees == 0);
    // Sans l'heure de chaque octet (tous à l'heure de la lecture), la coupure entre deux paquets
    // ressemble à un silence : la boîte perd le fil.
    modbus_t sans;
    modbus_init(&sans, 4);
    pour_moi = 0;
    for (size_t debut = 0; debut < n; debut += 120) {
        size_t taille = n - debut < 120 ? n - debut : 120;
        uint64_t t_lecture = 1000000 + (debut + taille) * 86 + 30;
        for (size_t i = 0; i < taille; i++) {
            pour_moi += modbus_recevoir(&sans, flux[debut + i], t_lecture);
        }
    }
    VERIFIER(pour_moi == 0);
}

void essais_boite(void) {
    printf("Boîte du poste\n");
    LANCER(avant_la_premiere_trame);
    LANCER(registres_d_une_trame);
    LANCER(recharge_presente_accu_plein);
    LANCER(etat_hx711_muet_et_exemple);
    LANCER(radio_muette_apres_2_s);
    LANCER(seulement_l_adresse_du_plateau);
    LANCER(trames_abimees_et_en_double);
    LANCER(trames_perdues);
    LANCER(trames_par_seconde);
    LANCER(signal_borne);
    LANCER(heure_des_octets_du_bus);
    LANCER(flux_continu_en_paquets);
}
