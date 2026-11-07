// Essais du boîtier du chariot sur la carte du plateau : registres, ordres, silence du Pi.
#include "essai.h"
#include "faux_i2c.h"
#include "modbus.h"
#include "plateau.h"

#define MS 1000ull

typedef struct {
    faux_i2c_t faux;
    plateau_t p;
    uint64_t t;
} monde_t;

static void monde_init(monde_t *m) {
    faux_i2c_init(&m->faux);
    plateau_config_t c = config_essai();
    i2c_bus_t bus = faux_i2c_bus(&m->faux);
    plateau_init(&m->p, &c, &bus, 7, 0);
    m->t = 0;
}

// Laisse tourner `duree_us` : la carte fait ses transactions quand elle a le temps.
static void tourner(monde_t *m, uint64_t duree_us) {
    uint64_t fin = m->t + duree_us;
    while (m->t < fin) {
        m->faux.horloge_us = m->t;
        plateau_pas(&m->p, m->t);
        m->t = m->faux.horloge_us + 20;
    }
}

static uint16_t lire(monde_t *m, unsigned registre) {
    uint16_t r[NB_REGISTRES_PLATEAU_MAX] = {0};
    plateau_registres(&m->p, m->t, r);
    return r[registre];
}

static uint8_t ordre(monde_t *m, unsigned voie, int16_t angle_dix) {
    uint16_t v = (uint16_t)angle_dix;
    return plateau_ecrire(&m->p, REGISTRE_ANGLES + voie, &v, 1, m->t);
}

static void angle_vers_impulsion(void) {
    monde_t m;
    monde_init(&m);
    // Voie 0 : 0 à 270°, 500 à 2500 µs → 135° = 1500 µs = 307 pas.
    VERIFIER(plateau_pas_pour_angle(&m.p, 0, 1350) == 307);
    VERIFIER(plateau_pas_pour_angle(&m.p, 0, 0) == 102);
    VERIFIER(plateau_pas_pour_angle(&m.p, 0, 2700) == 512);
    // Voie 1 : 0 à 180°, 500 à 2400 µs → 90° = 1450 µs = 297 pas.
    VERIFIER(plateau_pas_pour_angle(&m.p, 1, 900) == 297);
    // Voie 2 : −135 à +135°, 500 à 2500 µs → 0° = 1500 µs ; angle négatif.
    VERIFIER(plateau_pas_pour_angle(&m.p, 2, 0) == 307);
    VERIFIER(plateau_pas_pour_angle(&m.p, 2, -1350) == 102);
}

static void demarre_sorties_coupees(void) {
    monde_t m;
    monde_init(&m);
    tourner(&m, 300 * MS);
    for (unsigned c = 0; c < 16; c++) {
        VERIFIER(faux_pca_coupee(&m.faux, c));
    }
    // Pas d'ordre du Pi : aucune impulsion, et la carte le dit.
    VERIFIER(lire(&m, REGISTRE_I2C_ETAT) & I2C_AUCUN_ORDRE);
    VERIFIER(!(lire(&m, REGISTRE_I2C_ETAT) & I2C_PCA9685_DEMARRE_PAS));
    for (unsigned v = 0; v < 3; v++) {
        VERIFIER(lire(&m, REGISTRE_ANGLES + v) == 0x8000);
    }
    VERIFIER(lire(&m, REGISTRE_NB_VOIES) == 3);
    VERIFIER(plateau_nb_registres(&m.p) == 19);
}

static void un_ordre_bouge_le_servo(void) {
    monde_t m;
    monde_init(&m);
    tourner(&m, 50 * MS);
    VERIFIER(ordre(&m, 0, 1350) == 0);
    VERIFIER(ordre(&m, 2, -1350) == 0);
    tourner(&m, 50 * MS);
    VERIFIER(!faux_pca_coupee(&m.faux, 0) && faux_pca_fin(&m.faux, 0) == 307);
    VERIFIER(faux_pca_fin(&m.faux, 5) == 102 && !faux_pca_coupee(&m.faux, 5));
    VERIFIER(faux_pca_coupee(&m.faux, 1));  // la voie 1 n'a rien reçu
    VERIFIER(lire(&m, REGISTRE_ANGLES) == 1350);
    VERIFIER(lire(&m, REGISTRE_ANGLES + 2) == (uint16_t)-1350);
    VERIFIER(!(lire(&m, REGISTRE_I2C_ETAT) & I2C_AUCUN_ORDRE));
    // Sortie coupée sur demande.
    VERIFIER(ordre(&m, 0, ANGLE_COUPE) == 0);
    tourner(&m, 50 * MS);
    VERIFIER(faux_pca_coupee(&m.faux, 0));
}

static void ordre_refuse(void) {
    monde_t m;
    monde_init(&m);
    tourner(&m, 50 * MS);
    // Hors de la plage de la voie 1 (0 à 180°) : exception 3, et même une voie juste dans la même
    // écriture n'est pas prise.
    uint16_t v[2] = {900, 1801};
    VERIFIER(plateau_ecrire(&m.p, REGISTRE_ANGLES, v, 2, m.t) == MODBUS_NOMBRE_FAUX);
    tourner(&m, 50 * MS);
    VERIFIER(lire(&m, REGISTRE_ANGLES) == 0x8000 && faux_pca_coupee(&m.faux, 0));
    VERIFIER(lire(&m, REGISTRE_I2C_ETAT) & I2C_AUCUN_ORDRE);  // un refus n'est pas un ordre
    // Registres en lecture seule et registres qui n'existent pas.
    uint16_t un = 1;
    VERIFIER(plateau_ecrire(&m.p, 0, &un, 1, m.t) == MODBUS_REGISTRE_INCONNU);
    VERIFIER(plateau_ecrire(&m.p, REGISTRE_TOF_MM, &un, 1, m.t) == MODBUS_REGISTRE_INCONNU);
    VERIFIER(plateau_ecrire(&m.p, REGISTRE_NB_VOIES, &un, 1, m.t) == MODBUS_REGISTRE_INCONNU);
    VERIFIER(plateau_ecrire(&m.p, REGISTRE_ANGLES + 3, &un, 1, m.t) == MODBUS_REGISTRE_INCONNU);
    VERIFIER(plateau_ecrire(&m.p, REGISTRE_ANGLES + 2, v, 2, m.t) == MODBUS_REGISTRE_INCONNU);
}

static void plus_de_deux_secondes_sans_ordre(void) {
    monde_t m;
    monde_init(&m);
    tourner(&m, 50 * MS);
    VERIFIER(ordre(&m, 0, 1350) == 0);
    VERIFIER(ordre(&m, 1, 900) == 0);
    tourner(&m, 100 * MS);
    uint16_t avant0 = faux_pca_fin(&m.faux, 0), avant1 = faux_pca_fin(&m.faux, 1);
    VERIFIER(avant0 == 307 && avant1 == 297);
    VERIFIER(!(lire(&m, REGISTRE_I2C_ETAT) & I2C_PI_SILENCIEUX));
    // 1,9 s plus tard : pas encore.
    tourner(&m, 1900 * MS);
    VERIFIER(!(lire(&m, REGISTRE_I2C_ETAT) & I2C_PI_SILENCIEUX));
    // Après 2 s : la carte le dit, garde les angles, et ne touche plus aux servos.
    tourner(&m, 200 * MS);
    VERIFIER(lire(&m, REGISTRE_I2C_ETAT) & I2C_PI_SILENCIEUX);
    unsigned ecritures = m.faux.ecritures_pca;
    tourner(&m, 10000 * MS);
    VERIFIER(m.faux.ecritures_pca == ecritures);
    VERIFIER(faux_pca_fin(&m.faux, 0) == avant0 && faux_pca_fin(&m.faux, 1) == avant1);
    VERIFIER(!faux_pca_coupee(&m.faux, 0) && !faux_pca_coupee(&m.faux, 1));
    VERIFIER(lire(&m, REGISTRE_ANGLES) == 1350 && lire(&m, REGISTRE_ANGLES + 1) == 900);
    VERIFIER(lire(&m, REGISTRE_SILENCE_PI_MS) > 12000);
    // Un ordre du Pi, et tout reprend.
    VERIFIER(ordre(&m, 0, 1350) == 0);
    VERIFIER(!(lire(&m, REGISTRE_I2C_ETAT) & I2C_PI_SILENCIEUX));
    VERIFIER(lire(&m, REGISTRE_SILENCE_PI_MS) == 0);
}

static void le_tof_dans_les_registres(void) {
    monde_t m;
    monde_init(&m);
    VERIFIER(lire(&m, REGISTRE_TOF_ETAT) == TOF_ETAT_PAS_ENCORE);
    VERIFIER(lire(&m, REGISTRE_TOF_MM) == 0xFFFF && lire(&m, REGISTRE_TOF_AGE_MS) == 0xFFFF);
    m.faux.tof_distance = 63;
    tourner(&m, 300 * MS);
    VERIFIER(lire(&m, REGISTRE_TOF_MM) == 63);
    VERIFIER(lire(&m, REGISTRE_TOF_ETAT) == 0);
    VERIFIER(lire(&m, REGISTRE_TOF_AGE_MS) <= 80);  // une mesure toutes les 50 ms
    VERIFIER(lire(&m, REGISTRE_I2C_ECHECS) == 0);
    // Capteur débranché : plus de distance, état « muet », bit dans l'état de l'I2C.
    m.faux.tof_present = false;
    tourner(&m, 600 * MS);
    VERIFIER(lire(&m, REGISTRE_TOF_ETAT) == TOF_ETAT_MUET && lire(&m, REGISTRE_TOF_MM) == 0xFFFF);
    VERIFIER(lire(&m, REGISTRE_I2C_ETAT) & I2C_TOF_MUET);
    VERIFIER(lire(&m, REGISTRE_I2C_ECHECS) >= 1);
    // Les servos marchent quand même.
    VERIFIER(ordre(&m, 0, 1350) == 0);
    tourner(&m, 50 * MS);
    VERIFIER(faux_pca_fin(&m.faux, 0) == 307);
}

static void pca_debranchee_puis_de_retour(void) {
    monde_t m;
    monde_init(&m);
    m.faux.pca_presente = false;
    tourner(&m, 100 * MS);
    VERIFIER(lire(&m, REGISTRE_I2C_ETAT) & I2C_PCA9685_MUETTE);
    VERIFIER(ordre(&m, 0, 1350) == 0);  // l'ordre est gardé
    tourner(&m, 1000 * MS);
    // Pas de bus saturé : un essai toutes les 500 ms.
    VERIFIER(lire(&m, REGISTRE_I2C_ECHECS) <= 6);
    m.faux.pca_presente = true;
    tourner(&m, 1500 * MS);
    VERIFIER(!(lire(&m, REGISTRE_I2C_ETAT) & I2C_PCA9685_MUETTE));
    VERIFIER(!faux_pca_coupee(&m.faux, 0) && faux_pca_fin(&m.faux, 0) == 307);
    VERIFIER(faux_pca_coupee(&m.faux, 1));
}

static void pca_qui_perd_son_alimentation(void) {
    // La PCA9685 redémarre (alimentation coupée un instant) sans que la carte le sache : sa
    // première transaction ratée la remet en route, et les angles sont renvoyés.
    monde_t m;
    monde_init(&m);
    tourner(&m, 50 * MS);
    VERIFIER(ordre(&m, 0, 1350) == 0);
    tourner(&m, 50 * MS);
    VERIFIER(faux_pca_fin(&m.faux, 0) == 307);
    m.faux.pca_presente = false;
    VERIFIER(ordre(&m, 0, 1000) == 0);
    tourner(&m, 20 * MS);
    m.faux.pca_presente = true;
    faux_i2c_init(&m.faux);  // puce neuve
    m.faux.horloge_us = m.t;
    tourner(&m, 1500 * MS);
    VERIFIER(faux_pca_fin(&m.faux, 0) == plateau_pas_pour_angle(&m.p, 0, 1000));
}

static void compteur_de_demarrages(void) {
    monde_t m;
    monde_init(&m);
    VERIFIER(lire(&m, REGISTRE_DEMARRAGES) == 7);
    // Redémarrage par le chien de garde : +1. Mise sous tension : un nombre au hasard.
    VERIFIER(plateau_demarrages_suivant(true, 7, 999) == 8);
    VERIFIER(plateau_demarrages_suivant(true, 0xFFFF, 999) == 0);
    VERIFIER(plateau_demarrages_suivant(false, 7, 12345) == 12345);
    // Même nombre qu'avant : le Pi ne verrait rien changer, on évite.
    VERIFIER(plateau_demarrages_suivant(false, 5, 5) == 6);
}

void essais_plateau(void) {
    printf("Plateau (servos et distance)\n");
    LANCER(angle_vers_impulsion);
    LANCER(demarre_sorties_coupees);
    LANCER(un_ordre_bouge_le_servo);
    LANCER(ordre_refuse);
    LANCER(plus_de_deux_secondes_sans_ordre);
    LANCER(le_tof_dans_les_registres);
    LANCER(pca_debranchee_puis_de_retour);
    LANCER(pca_qui_perd_son_alimentation);
    LANCER(compteur_de_demarrages);
}
