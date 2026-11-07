#include "spray.h"

// ---------------------------------------------------------------- petits outils

static bool ecoule(const spray_t *s, uint64_t depuis_us, uint32_t ms) {
    return s->maintenant_us - depuis_us >= (uint64_t)ms * 1000u;
}

// Dixièmes de degré → pas du moteur du bras (arrondi au plus proche).
static int32_t en_pas(const spray_t *s, int32_t dixiemes) {
    int64_t produit = (int64_t)dixiemes * s->r.bras_pas_par_tour;
    return (int32_t)(produit >= 0 ? (produit + 1800) / 3600 : -((-produit + 1800) / 3600));
}

int32_t spray_angle_dixiemes(const spray_t *s) {
    if (s->r.bras_pas_par_tour <= 0) {
        return 0;
    }
    int64_t produit = (int64_t)s->bras->position * 3600;
    int64_t n = s->r.bras_pas_par_tour;
    return (int32_t)(produit >= 0 ? (produit + n / 2) / n : -((-produit + n / 2) / n));
}

static bool occupee(const spray_t *s) {
    return s->geste != GESTE_AUCUN || s->mouvement != MOUVEMENT_AUCUN;
}

static const balance_t *balance(const spray_t *s, uint16_t emplacement) {
    return &s->balances[emplacement - 1];
}

void spray_init(spray_t *s, const spray_reglages_t *r, moteur_t *bras,
                moteur_t *pompes[SPRAY_NB_FLACONS], const balance_t *balances,
                uint16_t demarrages, uint64_t t_us) {
    *s = (spray_t){0};
    s->r = *r;
    s->bras = bras;
    for (int i = 0; i < SPRAY_NB_FLACONS; i++) {
        s->pompes[i] = pompes[i];
    }
    s->balances = balances;
    s->demarrages = demarrages;
    s->maintenant_us = t_us;
    // Le Pi a `silence_max` après le démarrage pour parler, avant que la carte ne range le bras.
    s->dernier_message_us = t_us;
    s->capteur_change_us = t_us;
    s->pilote_ok = true;
    s->phase = PHASE_FIN;
}

// ---------------------------------------------------------------- le bras

static void fin_mouvement(spray_t *s, uint16_t suite) {
    s->mouvement = MOUVEMENT_AUCUN;
    if (s->geste == GESTE_AUCUN) {
        s->suite = suite;
    }
}

static void commencer(spray_t *s, mouvement_t mouvement) {
    s->mouvement = mouvement;
    s->debut_mouvement_us = s->maintenant_us;
    s->sorti = false;
}

// Position pas connue : vers « rangé » jusqu'au capteur, au plus toute la course et le
// dépassement depuis là où il est (et au plus le temps maximum).
static void chercher_le_capteur(spray_t *s) {
    int32_t course = en_pas(s, s->r.course_dixiemes) + s->r.bras_depassement_pas;
    moteur_aller(s->bras, s->bras->position - course, true);
}

static void commencer_origine(spray_t *s) {
    commencer(s, MOUVEMENT_ORIGINE);
    chercher_le_capteur(s);
}

static void commencer_ranger(spray_t *s) {
    commencer(s, MOUVEMENT_RANGER);
    if (s->origine) {
        moteur_aller(s->bras, -s->r.bras_depassement_pas, true);
    } else {
        chercher_le_capteur(s);
    }
}

static void commencer_sortir(spray_t *s, int32_t dixiemes) {
    commencer(s, MOUVEMENT_SORTIR);
    s->cible_dixiemes = dixiemes;
    moteur_aller(s->bras, en_pas(s, dixiemes), false);
}

static void avancer_bras(spray_t *s) {
    moteur_t *bras = s->bras;
    switch (s->mouvement) {
    case MOUVEMENT_ORIGINE:
    case MOUVEMENT_RANGER:
        if (bras->capteur_atteint) {
            // Le capteur voit le bras : cet endroit est 0°.
            moteur_zero_au_capteur(bras);
            if (s->mouvement == MOUVEMENT_ORIGINE) {
                s->origine = true;
            }
            s->erreurs &= (uint16_t)~(SPRAY_ERREUR_BRAS_PAS_RANGE | SPRAY_ERREUR_BRAS_POUSSE);
            fin_mouvement(s, SUITE_FAIT);
        } else if (!moteur_bouge(bras) || ecoule(s, s->debut_mouvement_us, s->r.bras_temps_max_ms)) {
            moteur_arreter(bras);
            s->erreurs |= SPRAY_ERREUR_BRAS_PAS_RANGE;
            fin_mouvement(s, SUITE_ECHOUE);
        }
        break;
    case MOUVEMENT_SORTIR:
        if (!moteur_bouge(bras)) {
            // Tous les pas sont faits, mais le capteur voit encore le bras : il n'a pas bougé
            // (bloqué, moteur débranché).
            if (s->capteur && en_pas(s, s->cible_dixiemes) > s->r.bras_depassement_pas) {
                s->erreurs |= SPRAY_ERREUR_BRAS_PAS_SORTI;
                fin_mouvement(s, SUITE_ECHOUE);
            } else {
                s->sorti = true;
                fin_mouvement(s, SUITE_FAIT);
            }
        } else if (ecoule(s, s->debut_mouvement_us, s->r.bras_temps_max_ms)) {
            moteur_arreter(bras);
            s->erreurs |= SPRAY_ERREUR_BRAS_PAS_SORTI;
            fin_mouvement(s, SUITE_ECHOUE);
        }
        break;
    case MOUVEMENT_AUCUN:
        break;
    }
}

// ---------------------------------------------------------------- les gestes

static void arreter_pompes(spray_t *s) {
    for (int i = 0; i < SPRAY_NB_FLACONS; i++) {
        moteur_arreter(s->pompes[i]);
    }
}

static int32_t perdu(const spray_t *s) {
    return s->depart_dixiemes - balance_dixiemes(balance(s, s->dose.emplacement));
}

static void changer_de_phase(spray_t *s, phase_t phase) {
    s->phase = phase;
    s->debut_phase_us = s->maintenant_us;
}

// Fin d'un spray ou d'un nettoyage : `interruption` 0 (fini), ou le résultat d'une dose coupée.
static void finir_geste(spray_t *s, uint16_t interruption) {
    if (s->geste == GESTE_AUCUN) {
        return;
    }
    arreter_pompes(s);
    bool spray = s->geste == GESTE_SPRAY;
    if (spray) {
        spray_dose_t *dose = &s->dose;
        bool muette = balance_muette(balance(s, dose->emplacement), s->maintenant_us);
        if (interruption && dose->resultat == DOSE_EN_COURS) {
            dose->perdue = s->pompe_partie ? perdu(s) : 0;
            dose->duree_ms = s->pompe_partie
                                 ? (uint32_t)((s->maintenant_us - s->debut_pompe_us) / 1000u)
                                 : 0;
            dose->resultat = interruption;
        } else if (!interruption && !muette) {
            // Après la chasse, le flacon ne bouge plus : le poids perdu le plus juste.
            dose->perdue = perdu(s);
        }
        dose->numero++;
    }
    s->geste = GESTE_AUCUN;
    s->phase = PHASE_FIN;
    s->suite = interruption ? SUITE_ECHOUE : SUITE_FAIT;
    if (spray && !interruption && s->dose.resultat == DOSE_TEMPS_MAX) {
        // Dose pas atteinte : chasse faite, la carte range le bras elle-même.
        commencer_ranger(s);
    }
}

static void finir_pompe(spray_t *s, uint16_t resultat) {
    moteur_arreter(s->pompes[s->dose.emplacement - 1]);
    s->dose.perdue = perdu(s);
    s->dose.duree_ms = (uint32_t)((s->maintenant_us - s->debut_pompe_us) / 1000u);
    s->dose.resultat = resultat;
    changer_de_phase(s, PHASE_CHASSE);
}

static void avancer_geste(spray_t *s) {
    switch (s->phase) {
    case PHASE_AIR_AVANT:
        if (ecoule(s, s->debut_phase_us, s->r.air_avant_ms)) {
            changer_de_phase(s, PHASE_POMPE);
            s->debut_pompe_us = s->maintenant_us;
            s->pompe_partie = true;
            moteur_tourner(s->pompes[s->dose.emplacement - 1], 1, false);
        }
        break;
    case PHASE_POMPE:
        // Balance perdue pendant la dose : on ne sait plus ce qui part, la pompe s'arrête
        // (comme une dose pas atteinte : chasse, puis bras rangé).
        if (balance_muette(balance(s, s->dose.emplacement), s->maintenant_us)) {
            finir_pompe(s, DOSE_TEMPS_MAX);
        } else if (perdu(s) >= (int32_t)s->dose.demandee) {
            finir_pompe(s, DOSE_ATTEINTE);
        } else if (ecoule(s, s->debut_pompe_us, s->r.temps_max_pompage_ms)) {
            finir_pompe(s, DOSE_TEMPS_MAX);
        }
        break;
    case PHASE_POMPE_NETTOYAGE:
        if (ecoule(s, s->debut_phase_us, s->r.nettoyage_pompe_ms)) {
            changer_de_phase(s, PHASE_CHASSE);
        }
        break;
    case PHASE_CHASSE: {
        uint32_t duree = s->geste == GESTE_SPRAY ? s->r.chasse_ms : s->r.sechage_ms;
        if (ecoule(s, s->debut_phase_us, duree)) {
            changer_de_phase(s, PHASE_AIR_APRES);
        }
        break;
    }
    case PHASE_AIR_APRES:
        if (ecoule(s, s->debut_phase_us, s->r.air_apres_ms)) {
            finir_geste(s, 0);
        }
        break;
    case PHASE_FIN:
        break;
    }
}

// ---------------------------------------------------------------- le temps passe

void spray_avancer(spray_t *s, bool capteur, bool pilote_ok, uint64_t t_us) {
    s->maintenant_us = t_us;
    // Le capteur, filtré : il doit garder son nouvel état `filtre_capteur_ms` pour qu'on y croie.
    if (capteur != s->capteur_brut) {
        s->capteur_brut = capteur;
        s->capteur_change_us = t_us;
    }
    bool avant = s->capteur;
    if (s->capteur_brut != s->capteur && ecoule(s, s->capteur_change_us, s->r.filtre_capteur_ms)) {
        s->capteur = s->capteur_brut;
    }
    if (avant && !s->capteur && s->mouvement == MOUVEMENT_AUCUN) {
        s->erreurs |= SPRAY_ERREUR_BRAS_POUSSE;
    }
    s->pilote_ok = pilote_ok;
    if (!pilote_ok) {
        s->erreurs |= SPRAY_ERREUR_PILOTE_BRAS;
    }
    if (s->agitateurs_pct && t_us >= s->fin_agitation_us) {
        s->agitateurs_pct = 0;
    }
    // Le Pi se tait pendant un geste, ou bras pas rangé : pompe et air arrêtés, bras rangé.
    if (!s->silence && (s->geste != GESTE_AUCUN || !s->capteur) &&
        ecoule(s, s->dernier_message_us, s->r.silence_max_ms)) {
        s->silence = true;
        finir_geste(s, DOSE_INTERROMPUE);
        commencer_ranger(s);
    }
    avancer_bras(s);
    avancer_geste(s);
}

void spray_pilote_redemarre(spray_t *s) {
    s->origine = false;
}

// ---------------------------------------------------------------- les ordres

static uint16_t executer(spray_t *s, uint16_t code, uint16_t p1, uint16_t p2) {
    s->suite = SUITE_EN_COURS;
    s->refus = REFUS_AUCUN;
    s->arret = false;
    switch (code) {
    case ORDRE_ORIGINE:
        if (s->geste != GESTE_AUCUN) {
            return REFUS_OCCUPEE;
        }
        s->silence = false;
        commencer_origine(s);
        return REFUS_AUCUN;
    case ORDRE_SORTIR:
        if (!s->origine) {
            return REFUS_PAS_D_ORIGINE;
        }
        if (p1 == 0 || p1 > s->r.course_dixiemes) {
            return REFUS_PARAMETRE;
        }
        if (!s->battement_recu || ecoule(s, s->dernier_battement_us, s->r.silence_max_ms)) {
            return REFUS_PAS_DE_BATTEMENT;
        }
        if (occupee(s)) {
            return REFUS_OCCUPEE;
        }
        if (s->erreurs & (SPRAY_ERREUR_BRAS_PAS_RANGE | SPRAY_ERREUR_BRAS_POUSSE |
                          SPRAY_ERREUR_PILOTE_BRAS)) {
            return REFUS_ERREUR_BRAS;
        }
        s->silence = false;
        commencer_sortir(s, p1);
        return REFUS_AUCUN;
    case ORDRE_RANGER:
        // Jamais refusé : un spray en cours est interrompu (pompe et air arrêtés d'abord).
        finir_geste(s, DOSE_INTERROMPUE);
        commencer_ranger(s);
        s->suite = SUITE_EN_COURS;
        return REFUS_AUCUN;
    case ORDRE_SPRAY: {
        if (p1 < 1 || p1 > SPRAY_NB_FLACONS || p2 == 0) {
            return REFUS_PARAMETRE;
        }
        if (occupee(s)) {
            return REFUS_OCCUPEE;
        }
        if (!s->sorti) {
            return REFUS_BRAS_PAS_SORTI;
        }
        const balance_t *b = balance(s, p1);
        if (balance_muette(b, s->maintenant_us) || balance_instable(b)) {
            return REFUS_BALANCE;
        }
        s->geste = GESTE_SPRAY;
        changer_de_phase(s, PHASE_AIR_AVANT);
        s->pompe_partie = false;
        s->depart_dixiemes = balance_dixiemes(b);
        uint16_t numero = s->dose.numero;
        s->dose = (spray_dose_t){p1, p2, 0, 0, DOSE_EN_COURS, numero};
        return REFUS_AUCUN;
    }
    case ORDRE_NETTOYER:
        if (occupee(s)) {
            return REFUS_OCCUPEE;
        }
        if (!s->sorti) {
            return REFUS_BRAS_PAS_SORTI;
        }
        s->geste = GESTE_NETTOYAGE;
        changer_de_phase(s, PHASE_POMPE_NETTOYAGE);
        return REFUS_AUCUN;
    case ORDRE_AGITER:
        if (p1 > 100) {
            return REFUS_PARAMETRE;
        }
        s->agitateurs_pct = p2 ? (uint8_t)p1 : 0;
        s->fin_agitation_us = s->maintenant_us + (uint64_t)p2 * 1000000u;
        s->suite = SUITE_FAIT;
        return REFUS_AUCUN;
    case ORDRE_ARRET:
        // Pompes, air, petite pompe, agitateurs ; le bras s'arrête où il est.
        finir_geste(s, DOSE_INTERROMPUE);
        if (s->mouvement != MOUVEMENT_AUCUN) {
            moteur_arreter(s->bras);
            s->mouvement = MOUVEMENT_AUCUN;
        }
        s->agitateurs_pct = 0;
        s->arret = true;
        s->suite = SUITE_FAIT;
        return REFUS_AUCUN;
    case ORDRE_EFFACER:
        s->erreurs = 0;
        s->silence = false;
        s->suite = SUITE_FAIT;
        return REFUS_AUCUN;
    default:
        return REFUS_ORDRE_INCONNU;
    }
}

static void ecrire(spray_t *s, uint16_t premier, const uint16_t *valeurs, size_t n) {
    s->message_recu = true;
    s->dernier_message_us = s->maintenant_us;
    uint16_t ordre[4] = {0, 0, 0, 0};  // registres 101 à 104 de cette trame (0 s'ils n'y sont pas)
    bool numero = false;
    for (size_t i = 0; i < n; i++) {
        uint16_t registre = (uint16_t)(premier + i);
        if (registre == SPRAY_REGISTRE_BATTEMENT) {
            s->battement_recu = true;
            s->dernier_battement_us = s->maintenant_us;
        } else {
            ordre[registre - SPRAY_REGISTRE_ORDRE] = valeurs[i];
            numero = numero || registre == SPRAY_REGISTRE_NUMERO;
        }
    }
    // L'ordre n'est exécuté qu'au changement de son numéro, une seule fois.
    if (!numero || (s->numero_recu && ordre[3] == s->numero_ordre)) {
        return;
    }
    s->numero_recu = true;
    s->numero_ordre = ordre[3];
    uint16_t refus = executer(s, ordre[0], ordre[1], ordre[2]);
    if (refus) {
        s->suite = SUITE_REFUSE;
        s->refus = refus;
    }
}

// ---------------------------------------------------------------- le bus

static uint16_t etat(const spray_t *s) {
    uint16_t e = 0;
    e |= s->capteur ? SPRAY_ETAT_BRAS_RANGE : 0;
    e |= s->sorti && s->mouvement == MOUVEMENT_AUCUN ? SPRAY_ETAT_BRAS_SORTI : 0;
    e |= s->mouvement != MOUVEMENT_AUCUN || moteur_bouge(s->bras) ? SPRAY_ETAT_BRAS_BOUGE : 0;
    e |= s->origine ? SPRAY_ETAT_ORIGINE_FAITE : 0;
    e |= s->geste == GESTE_SPRAY ? SPRAY_ETAT_SPRAY_EN_COURS : 0;
    e |= s->geste == GESTE_NETTOYAGE ? SPRAY_ETAT_NETTOYAGE_EN_COURS : 0;
    e |= s->agitateurs_pct ? SPRAY_ETAT_AGITATEURS : 0;
    e |= s->r.exemple ? SPRAY_ETAT_EXEMPLE : 0;
    e |= s->silence ? SPRAY_ETAT_SILENCE_PI : 0;
    e |= s->arret ? SPRAY_ETAT_ARRET_IMMEDIAT : 0;
    return e;
}

void spray_registres(const spray_t *s, uint16_t trames_abimees, uint16_t *r) {
    for (int i = 0; i < SPRAY_NB_REGISTRES; i++) {
        r[i] = 0;
    }
    r[0] = SPRAY_SIGNATURE;
    r[1] = SPRAY_VERSION;
    r[2] = s->demarrages;
    r[3] = etat(s);
    uint16_t erreurs = s->erreurs & SPRAY_ERREURS_DU_BRAS;
    for (int i = 0; i < SPRAY_NB_FLACONS; i++) {
        const balance_t *b = &s->balances[i];
        bool muette = balance_muette(b, s->maintenant_us);
        if (muette) {
            erreurs |= (uint16_t)(1u << i);
        } else if (balance_instable(b)) {
            erreurs |= (uint16_t)(16u << i);
        }
        uint32_t brut = (uint32_t)balance_brut(b);
        r[10 + 2 * i] = (uint16_t)(brut >> 16);
        r[11 + 2 * i] = (uint16_t)(brut & 0xFFFF);
        r[18 + i] = muette ? 0 : (uint16_t)balance_dixiemes(b);
    }
    r[4] = erreurs;
    int32_t angle = spray_angle_dixiemes(s);
    r[5] = (uint16_t)(angle < 0 ? 0 : angle > 0xFFFF ? 0xFFFF : angle);
    r[6] = s->numero_ordre;
    r[7] = s->suite;
    r[8] = s->refus;
    uint64_t silence_ms = (s->maintenant_us - s->dernier_message_us) / 1000u;
    r[9] = !s->message_recu || silence_ms > 0xFFFF ? 0xFFFF : (uint16_t)silence_ms;
    r[22] = s->dose.emplacement;
    r[23] = s->dose.demandee;
    r[24] = (uint16_t)s->dose.perdue;
    r[25] = s->dose.duree_ms > 0xFFFF ? 0xFFFF : (uint16_t)s->dose.duree_ms;
    r[26] = s->dose.resultat;
    r[27] = s->dose.numero;
    r[28] = s->agitateurs_pct;
    r[29] = trames_abimees;
}

size_t spray_repondre(spray_t *s, const modbus_t *m, uint64_t t_us, uint8_t *reponse) {
    s->maintenant_us = t_us;
    uint8_t fonction = modbus_fonction(m);
    if (fonction == 4) {
        uint16_t registres[SPRAY_NB_REGISTRES];
        spray_registres(s, m->trames_abimees, registres);
        return modbus_repondre(m, registres, SPRAY_NB_REGISTRES, reponse);
    }
    if (fonction != 16) {
        // La fonction 3 aussi : la table ne se lit qu'en fonction 4 (spray/README.md).
        return modbus_exception(m, MODBUS_FONCTION_INCONNUE, reponse);
    }
    uint16_t premier = 0;
    uint16_t valeurs[MODBUS_REGISTRES_MAX];
    size_t n = modbus_lire_ecriture(m, &premier, valeurs, MODBUS_REGISTRES_MAX);
    if (n == 0) {
        return modbus_repondre_ecriture(m, MODBUS_NOMBRE_FAUX, reponse);
    }
    if (premier < SPRAY_REGISTRE_BATTEMENT || premier + n > SPRAY_REGISTRE_NUMERO + 1u) {
        return modbus_repondre_ecriture(m, MODBUS_REGISTRE_INCONNU, reponse);
    }
    ecrire(s, premier, valeurs, n);
    return modbus_repondre_ecriture(m, 0, reponse);
}

spray_sorties_t spray_sorties(const spray_t *s) {
    spray_sorties_t sorties = {0};
    sorties.agitateurs_pct = s->agitateurs_pct;
    switch (s->phase) {
    case PHASE_AIR_AVANT:
    case PHASE_POMPE:
    case PHASE_AIR_APRES:
        sorties.ev_buse = true;
        break;
    case PHASE_POMPE_NETTOYAGE:
        sorties.ev_buse = true;
        sorties.pompe_nettoyage = true;
        break;
    case PHASE_CHASSE:
        sorties.ev_buse = true;
        sorties.ev_chasse = true;
        break;
    case PHASE_FIN:
        break;
    }
    return sorties;
}

uint64_t spray_heure_octet(uint64_t t_lecture_us, size_t n, size_t i, uint32_t bauds,
                           uint64_t *precedent_us) {
    // 10 bits par octet (8N1).
    uint64_t octet_us = bauds ? 10000000ull / bauds : 0;
    uint64_t recul = (uint64_t)(n - 1 - i) * octet_us;
    uint64_t t = recul > t_lecture_us ? 0 : t_lecture_us - recul;
    if (t < *precedent_us) {
        t = *precedent_us;
    }
    *precedent_us = t;
    return t;
}
