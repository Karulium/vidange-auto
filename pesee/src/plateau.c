#include "plateau.h"

#include "modbus.h"

uint16_t plateau_demarrages_suivant(bool memoire_bonne, uint16_t ancien, uint16_t hasard) {
    uint16_t suivant = memoire_bonne ? (uint16_t)(ancien + 1) : hasard;
    return suivant == ancien ? (uint16_t)(suivant + 1) : suivant;
}

void plateau_init(plateau_t *p, const plateau_config_t *config, const i2c_bus_t *bus,
                  uint16_t demarrages, uint64_t t_us) {
    p->config = *config;
    p->bus = *bus;
    p->demarrages = demarrages;
    for (size_t i = 0; i < PLATEAU_VOIES_MAX; i++) {
        p->angles[i] = ANGLE_COUPE;
    }
    p->a_ecrire = 0;
    p->pca_prete = false;
    p->pca_muette = false;
    p->etape_pca = 0;
    p->pca_libre_us = t_us;
    p->un_ordre = false;
    p->dernier_ordre_us = t_us;
    p->echecs = 0;
    vl6180x_init(&p->tof, &p->config.tof, t_us);
}

uint16_t plateau_pas_pour_angle(const plateau_t *p, size_t voie, int16_t angle_dix) {
    const voie_config_t *v = &p->config.voies[voie];
    int64_t etendue = (int64_t)v->angle_max_dix - v->angle_min_dix;
    int64_t largeur = (int64_t)v->impulsion_max_us - v->impulsion_min_us;
    int64_t decalage = (int64_t)angle_dix - v->angle_min_dix;
    // Arrondi au plus proche (décalage et largeur positifs).
    int64_t impulsion = v->impulsion_min_us + (2 * decalage * largeur + etendue) / (2 * etendue);
    return pca9685_pas(&p->config.pca, (uint32_t)impulsion);
}

static void panne_pca(plateau_t *p, uint64_t t_us) {
    p->echecs++;
    p->pca_muette = true;
    p->pca_prete = false;
    p->etape_pca = 0;
    p->pca_libre_us = t_us + (uint64_t)p->config.reessai_ms * 1000;
}

// Une transaction avec la PCA9685, si elle a quelque chose à faire et que c'est l'heure.
static bool pas_pca(plateau_t *p, uint64_t t_us) {
    if (t_us < p->pca_libre_us) {
        return false;
    }
    const i2c_bus_t *bus = &p->bus;
    const pca9685_config_t *pca = &p->config.pca;
    if (!p->pca_prete) {
        if (!pca9685_etape_demarrage(bus, pca, p->etape_pca)) {
            panne_pca(p, t_us);
            return true;
        }
        p->pca_muette = false;
        if (++p->etape_pca >= PCA9685_ETAPES_DEMARRAGE) {
            p->pca_prete = true;
            p->pca_libre_us = t_us + p->config.pca_reveil_us;
            // La puce vient de tout couper : toute voie avec un angle est à renvoyer.
            p->a_ecrire = 0;
            for (size_t i = 0; i < p->config.nb_voies; i++) {
                if (p->angles[i] != ANGLE_COUPE) {
                    p->a_ecrire |= (uint16_t)(1u << i);
                }
            }
        }
        return true;
    }
    for (size_t i = 0; i < p->config.nb_voies; i++) {
        if (!(p->a_ecrire & (1u << i))) {
            continue;
        }
        unsigned canal = p->config.voies[i].canal;
        bool ok = p->angles[i] == ANGLE_COUPE
                      ? pca9685_couper(bus, pca, canal)
                      : pca9685_regler(bus, pca, canal, plateau_pas_pour_angle(p, i, p->angles[i]));
        if (!ok) {
            panne_pca(p, t_us);
        } else {
            p->a_ecrire &= (uint16_t)~(1u << i);
        }
        return true;
    }
    return false;
}

void plateau_pas(plateau_t *p, uint64_t t_us) {
    // Les servos d'abord (un ordre du Pi ne doit pas attendre le capteur), puis le capteur.
    if (pas_pca(p, t_us)) {
        return;
    }
    vl6180x_pas(&p->tof, &p->bus, t_us);
}

size_t plateau_nb_registres(const plateau_t *p) {
    return REGISTRE_ANGLES + p->config.nb_voies;
}

static uint16_t en_ms(uint64_t us) {
    uint64_t ms = us / 1000;
    return ms > UINT16_MAX ? UINT16_MAX : (uint16_t)ms;
}

void plateau_registres(const plateau_t *p, uint64_t t_us, uint16_t *registres) {
    uint64_t silence_us = t_us - p->dernier_ordre_us;
    uint16_t etat = 0;
    if (p->pca_muette) {
        etat |= I2C_PCA9685_MUETTE;
    }
    if (p->tof.muet) {
        etat |= I2C_TOF_MUET;
    }
    if (!p->un_ordre) {
        etat |= I2C_AUCUN_ORDRE;
    } else if (silence_us > (uint64_t)p->config.silence_pi_ms * 1000) {
        etat |= I2C_PI_SILENCIEUX;
    }
    if (!p->pca_prete) {
        etat |= I2C_PCA9685_DEMARRE_PAS;
    }
    registres[REGISTRE_TOF_MM] = vl6180x_distance(&p->tof);
    registres[REGISTRE_TOF_ETAT] = vl6180x_etat(&p->tof);
    registres[REGISTRE_TOF_AGE_MS] = p->tof.une_mesure ? en_ms(t_us - p->tof.heure_us) : UINT16_MAX;
    registres[REGISTRE_DEMARRAGES] = p->demarrages;
    registres[REGISTRE_I2C_ETAT] = etat;
    registres[REGISTRE_I2C_ECHECS] = (uint16_t)(p->echecs + p->tof.echecs);
    registres[REGISTRE_SILENCE_PI_MS] = en_ms(silence_us);
    registres[REGISTRE_NB_VOIES] = (uint16_t)p->config.nb_voies;
    for (size_t i = 0; i < p->config.nb_voies; i++) {
        registres[REGISTRE_ANGLES + i] = (uint16_t)p->angles[i];
    }
}

uint8_t plateau_ecrire(plateau_t *p, uint16_t premier, const uint16_t *valeurs, size_t n,
                       uint64_t t_us) {
    if (premier < REGISTRE_ANGLES || (size_t)premier + n > REGISTRE_ANGLES + p->config.nb_voies) {
        return MODBUS_REGISTRE_INCONNU;
    }
    size_t debut = premier - REGISTRE_ANGLES;
    // Tout est vérifié avant de changer quoi que ce soit.
    for (size_t i = 0; i < n; i++) {
        int16_t angle = (int16_t)valeurs[i];
        const voie_config_t *v = &p->config.voies[debut + i];
        if (angle != ANGLE_COUPE && (angle < v->angle_min_dix || angle > v->angle_max_dix)) {
            return MODBUS_NOMBRE_FAUX;
        }
    }
    for (size_t i = 0; i < n; i++) {
        int16_t angle = (int16_t)valeurs[i];
        // Même un angle inchangé est réécrit dans la puce : si elle a perdu son alimentation
        // sans que la carte le sache, le prochain ordre du Pi la remet à l'angle.
        p->angles[debut + i] = angle;
        p->a_ecrire |= (uint16_t)(1u << (debut + i));
    }
    p->un_ordre = true;
    p->dernier_ordre_us = t_us;
    return 0;
}
