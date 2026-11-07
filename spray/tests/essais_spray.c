// Essais de la carte du spray sans le matériel : les ordres du Pi par de vraies trames Modbus,
// le faux bras, le faux capteur, les fausses balances et pompes (monde.c).
#include <string.h>

#include "essai.h"
#include "monde.h"

static uint16_t r[SPRAY_NB_REGISTRES];

static uint16_t lire(monde_t *w, int registre) {
    monde_lire(w, r);
    return r[registre];
}

static bool bit(monde_t *w, uint16_t etat) {
    return (lire(w, 3) & etat) != 0;
}

// --------------------------------------------------------------- démarrage et origine

static void au_demarrage(void) {
    monde_t w;
    monde_init(&w);
    monde_lire(&w, r);
    VERIFIER(r[0] == 0x5350 && r[1] == 1 && r[2] == 7);
    VERIFIER(r[3] == (SPRAY_ETAT_BRAS_RANGE | SPRAY_ETAT_EXEMPLE));
    VERIFIER(r[4] == 0);
    VERIFIER(r[9] == 0xFFFF);  // le Pi n'a encore rien écrit
    // Flacon de 400 g : brut 1000 + 400 × 400 = 161 000 ; 4000 dixièmes de gramme.
    VERIFIER(r[10] == (161000 >> 16) && r[11] == (161000 & 0xFFFF));
    VERIFIER(r[18] == 4000 && r[21] == 4000);
    VERIFIER(r[22] == 0 && r[26] == DOSE_AUCUNE);
    // Le bras rangé ne bouge pas, même si le Pi se tait.
    monde_avancer(&w, 5000);
    VERIFIER(w.bras_reel == 0 && !bit(&w, SPRAY_ETAT_SILENCE_PI));
}

static void prise_d_origine(void) {
    monde_t w;
    monde_init(&w);
    // Bras écarté à la main avant le démarrage (≈ 20°) : la carte ne sait pas où il est.
    w.bras_reel = 178;
    monde_avancer(&w, 50);
    VERIFIER(!bit(&w, SPRAY_ETAT_BRAS_RANGE));
    w.battre_auto = true;
    VERIFIER(monde_ordre(&w, ORDRE_ORIGINE, 0, 0) == 0);
    VERIFIER(lire(&w, 6) == w.numero && r[7] == SUITE_EN_COURS);
    VERIFIER(monde_attendre(&w, 3, SPRAY_ETAT_ORIGINE_FAITE, SPRAY_ETAT_ORIGINE_FAITE, 3000));
    monde_avancer(&w, 50);
    monde_lire(&w, r);
    VERIFIER(r[3] & SPRAY_ETAT_BRAS_RANGE);
    VERIFIER(!(r[3] & SPRAY_ETAT_BRAS_BOUGE));
    VERIFIER(r[5] == 0 && r[7] == SUITE_FAIT);
    VERIFIER(w.bras_reel == w.zone_capteur_pas);  // arrêté au bord du capteur
    VERIFIER(w.pas_simultanes == 0);
}

static void origine_capteur_en_panne(void) {
    monde_t w;
    monde_init(&w);
    w.battre_auto = true;
    w.capteur_en_panne = true;
    monde_avancer(&w, 50);
    monde_ordre(&w, ORDRE_ORIGINE, 0, 0);
    VERIFIER(monde_attendre(&w, 7, 0xFFFF, SUITE_ECHOUE, 3000));
    monde_lire(&w, r);
    VERIFIER(r[4] & SPRAY_ERREUR_BRAS_PAS_RANGE);
    VERIFIER(!(r[3] & (SPRAY_ETAT_ORIGINE_FAITE | SPRAY_ETAT_BRAS_BOUGE)));
    // Il ne cherche pas plus loin que toute la course et le dépassement : 110° + 10°.
    VERIFIER(w.bras_reel == -(978 + 89));
    // Bras bloqué loin du capteur : il cherche au plus le temps maximum.
    monde_init(&w);
    w.battre_auto = true;
    w.bras_reel = 500;
    w.bras_bloque = true;
    w.r.bras_temps_max_ms = 1000;
    w.spray.r.bras_temps_max_ms = 1000;
    monde_avancer(&w, 50);
    monde_ordre(&w, ORDRE_ORIGINE, 0, 0);
    monde_avancer(&w, 900);
    VERIFIER(bit(&w, SPRAY_ETAT_BRAS_BOUGE));
    monde_avancer(&w, 200);
    VERIFIER(lire(&w, 7) == SUITE_ECHOUE && (r[4] & SPRAY_ERREUR_BRAS_PAS_RANGE));
}

// --------------------------------------------------------------- sortir

static void sortir_refuse(void) {
    monde_t w;
    monde_init(&w);
    // Sans origine.
    monde_battre(&w);
    monde_ordre(&w, ORDRE_SORTIR, 643, 0);
    VERIFIER(lire(&w, 7) == SUITE_REFUSE && r[8] == REFUS_PAS_D_ORIGINE);
    monde_ordre(&w, ORDRE_ORIGINE, 0, 0);
    monde_attendre(&w, 3, SPRAY_ETAT_ORIGINE_FAITE, SPRAY_ETAT_ORIGINE_FAITE, 3000);
    // Angle hors de la course (0, ou plus de 110°).
    monde_battre(&w);
    monde_ordre(&w, ORDRE_SORTIR, 0, 0);
    VERIFIER(lire(&w, 8) == REFUS_PARAMETRE);
    monde_ordre(&w, ORDRE_SORTIR, 1101, 0);
    VERIFIER(lire(&w, 8) == REFUS_PARAMETRE);
    // Pas de battement depuis plus de 2 s : le Pi n'est pas là.
    monde_avancer(&w, 2100);
    monde_ordre(&w, ORDRE_SORTIR, 643, 0);
    VERIFIER(lire(&w, 7) == SUITE_REFUSE && r[8] == REFUS_PAS_DE_BATTEMENT);
    VERIFIER(w.bras_reel == 0);
    // Un battement récent : accepté.
    monde_battre(&w);
    monde_ordre(&w, ORDRE_SORTIR, 643, 0);
    VERIFIER(lire(&w, 7) == SUITE_EN_COURS && r[8] == REFUS_AUCUN);
    // Déjà en train de bouger.
    monde_ordre(&w, ORDRE_SORTIR, 700, 0);
    VERIFIER(lire(&w, 8) == REFUS_OCCUPEE);
}

static void sortir_et_ranger(void) {
    monde_t w;
    monde_init(&w);
    uint64_t debut = w.t_us;
    VERIFIER(monde_sortir(&w, 643));
    monde_lire(&w, r);
    // À un pas près (0,11° par pas : 16 micro-pas, bras sur l'axe du moteur).
    VERIFIER(r[5] >= 642 && r[5] <= 645 && r[7] == SUITE_FAIT);
    VERIFIER(!(r[3] & (SPRAY_ETAT_BRAS_RANGE | SPRAY_ETAT_BRAS_BOUGE)));
    int32_t reel = monde_angle_reel(&w);
    VERIFIER(reel > 635 && reel < 650);
    // Origine et sortie en moins de 3 s chacune.
    VERIFIER(w.t_us - debut < 4000000);
    monde_ordre(&w, ORDRE_RANGER, 0, 0);
    VERIFIER(bit(&w, SPRAY_ETAT_BRAS_BOUGE) && r[7] == SUITE_EN_COURS);
    VERIFIER(monde_attendre(&w, 3, SPRAY_ETAT_BRAS_RANGE | SPRAY_ETAT_BRAS_BOUGE,
                            SPRAY_ETAT_BRAS_RANGE, 3000));
    VERIFIER(lire(&w, 5) == 0 && r[7] == SUITE_FAIT && r[4] == 0);
    VERIFIER(w.pas_simultanes == 0);
}

static void bras_bloque(void) {
    monde_t w;
    monde_init(&w);
    monde_ordre(&w, ORDRE_ORIGINE, 0, 0);
    monde_attendre(&w, 3, SPRAY_ETAT_ORIGINE_FAITE, SPRAY_ETAT_ORIGINE_FAITE, 3000);
    // Le moteur tourne mais le bras ne bouge pas (bloqué, accouplement) : le capteur le voit
    // encore à la fin.
    w.bras_bloque = true;
    w.battre_auto = true;
    monde_battre(&w);
    monde_ordre(&w, ORDRE_SORTIR, 643, 0);
    VERIFIER(monde_attendre(&w, 7, 0xFFFF, SUITE_ECHOUE, 3000));
    VERIFIER(lire(&w, 4) & SPRAY_ERREUR_BRAS_PAS_SORTI);
    VERIFIER(!(r[3] & SPRAY_ETAT_BRAS_SORTI));
}

static void ranger_capteur_en_panne(void) {
    monde_t w;
    monde_init(&w);
    VERIFIER(monde_sortir(&w, 643));
    w.capteur_en_panne = true;
    monde_ordre(&w, ORDRE_RANGER, 0, 0);
    // Il cherche le capteur jusqu'à −10°, pas plus loin.
    VERIFIER(monde_attendre(&w, 7, 0xFFFF, SUITE_ECHOUE, 3000));
    VERIFIER(lire(&w, 4) & SPRAY_ERREUR_BRAS_PAS_RANGE);
    VERIFIER(w.bras_reel == -89);
    VERIFIER(!(r[3] & SPRAY_ETAT_BRAS_RANGE));
    // Sortir est refusé tant que l'erreur n'est pas effacée.
    w.capteur_en_panne = false;
    monde_ordre(&w, ORDRE_SORTIR, 643, 0);
    VERIFIER(lire(&w, 8) == REFUS_ERREUR_BRAS);
    monde_ordre(&w, ORDRE_EFFACER, 0, 0);
    VERIFIER(lire(&w, 4) == 0 && r[7] == SUITE_FAIT);
}

static void bras_pousse(void) {
    monde_t w;
    monde_init(&w);
    monde_ordre(&w, ORDRE_ORIGINE, 0, 0);
    monde_attendre(&w, 3, SPRAY_ETAT_ORIGINE_FAITE, SPRAY_ETAT_ORIGINE_FAITE, 3000);
    monde_avancer(&w, 50);
    // Quelqu'un pousse le bras (sans ordre).
    w.bras_reel = 150;
    monde_avancer(&w, 50);
    VERIFIER(lire(&w, 4) & SPRAY_ERREUR_BRAS_POUSSE);
    VERIFIER(!(r[3] & SPRAY_ETAT_BRAS_RANGE));
    // Une mesure du capteur qui saute moins de 20 ms ne compte pas.
    monde_ordre(&w, ORDRE_EFFACER, 0, 0);
    w.bras_reel = 0;
    monde_avancer(&w, 50);
    VERIFIER(lire(&w, 4) == 0);
    w.bras_reel = 150;
    monde_avancer(&w, 10);
    w.bras_reel = 0;
    monde_avancer(&w, 50);
    VERIFIER(lire(&w, 4) == 0);
}

// --------------------------------------------------------------- le Pi se tait

static void silence_du_pi_bras_sorti(void) {
    monde_t w;
    monde_init(&w);
    VERIFIER(monde_sortir(&w, 724));
    // Le Pi se tait.
    w.battre_auto = false;
    monde_avancer(&w, 1900);
    VERIFIER(bit(&w, SPRAY_ETAT_BRAS_SORTI));
    VERIFIER(r[9] >= 1900 && r[9] < 2000);
    monde_avancer(&w, 200);
    VERIFIER(bit(&w, SPRAY_ETAT_SILENCE_PI));
    VERIFIER(monde_attendre(&w, 3, SPRAY_ETAT_BRAS_RANGE | SPRAY_ETAT_BRAS_BOUGE,
                            SPRAY_ETAT_BRAS_RANGE, 3000));
    VERIFIER(bit(&w, SPRAY_ETAT_SILENCE_PI));
    // Effacé par « effacer ».
    monde_ordre(&w, ORDRE_EFFACER, 0, 0);
    VERIFIER(!bit(&w, SPRAY_ETAT_SILENCE_PI));
}

static void silence_du_pi_pendant_un_spray(void) {
    monde_t w;
    monde_init(&w);
    VERIFIER(monde_sortir(&w, 643));
    monde_ordre(&w, ORDRE_SPRAY, 1, 100);
    monde_avancer(&w, 2000);  // la pompe tourne
    uint32_t pas = w.pas_pompes[0];
    VERIFIER(pas > 0 && bit(&w, SPRAY_ETAT_SPRAY_EN_COURS));
    w.battre_auto = false;
    monde_avancer(&w, 2100);
    // Pompe arrêtée, air coupé, dose interrompue, bras qui se range.
    spray_sorties_t s = spray_sorties(&w.spray);
    VERIFIER(!s.ev_buse && !s.ev_chasse);
    monde_lire(&w, r);
    VERIFIER(r[3] & SPRAY_ETAT_SILENCE_PI);
    VERIFIER(!(r[3] & SPRAY_ETAT_SPRAY_EN_COURS));
    VERIFIER(r[26] == DOSE_INTERROMPUE && r[27] == 1);
    VERIFIER(r[24] > 0 && r[24] < 100);
    pas = w.pas_pompes[0];
    monde_avancer(&w, 3000);
    VERIFIER(w.pas_pompes[0] == pas);
    VERIFIER(bit(&w, SPRAY_ETAT_BRAS_RANGE));
}

// --------------------------------------------------------------- les doses

static void une_dose(void) {
    monde_t w;
    monde_init(&w);
    VERIFIER(monde_sortir(&w, 643));
    uint64_t buse = w.buse_ms;
    VERIFIER(monde_ordre(&w, ORDRE_SPRAY, 2, 100) == 0);  // emplacement 2, 10,0 g
    monde_lire(&w, r);
    VERIFIER(r[3] & SPRAY_ETAT_SPRAY_EN_COURS);
    VERIFIER(r[22] == 2 && r[23] == 100 && r[26] == DOSE_EN_COURS && r[27] == 0);
    // 0,5 s d'air avant la pompe.
    monde_avancer(&w, 450);
    VERIFIER(w.pas_pompes[1] == 0 && spray_sorties(&w.spray).ev_buse);
    VERIFIER(monde_attendre(&w, 27, 0xFFFF, 1, 30000));
    monde_lire(&w, r);
    VERIFIER(r[26] == DOSE_ATTEINTE && r[7] == SUITE_FAIT);
    VERIFIER(!(r[3] & SPRAY_ETAT_SPRAY_EN_COURS));
    // ≈ 10 g perdus en ≈ 10 s (1 g/s), à 0,3 g près.
    VERIFIER(r[24] >= 100 && r[24] <= 103);
    VERIFIER(r[25] >= 9900 && r[25] <= 10500);
    VERIFIER(w.grammes[1] < 390.1 && w.grammes[1] > 389.6);
    // Seule la pompe 2 a tourné.
    VERIFIER(w.pas_pompes[0] == 0 && w.pas_pompes[2] == 0 && w.pas_pompes[3] == 0);
    // Chasse 4,5 s ; air de la buse : 0,5 + pompage + 4,5 + 1 s.
    VERIFIER(w.chasse_ms >= 4490 && w.chasse_ms <= 4510);
    uint64_t air = w.buse_ms - buse;
    uint64_t attendu = 6000u + r[25];
    VERIFIER(air + 20 >= attendu && air <= attendu + 30);
    // Le bras reste sorti (le Pi le range).
    VERIFIER(r[3] & SPRAY_ETAT_BRAS_SORTI);
}

static void dose_pas_atteinte(void) {
    monde_t w;
    monde_init(&w);
    VERIFIER(monde_sortir(&w, 643));
    w.tube_pince[0] = true;
    monde_ordre(&w, ORDRE_SPRAY, 1, 100);
    VERIFIER(monde_attendre(&w, 27, 0xFFFF, 1, 30000));
    monde_lire(&w, r);
    VERIFIER(r[26] == DOSE_TEMPS_MAX);
    VERIFIER(r[25] >= 14990 && r[25] <= 15010);
    VERIFIER((int16_t)r[24] < 5);
    // La chasse est faite quand même, puis la carte range le bras elle-même.
    VERIFIER(w.chasse_ms >= 4490);
    VERIFIER(monde_attendre(&w, 3, SPRAY_ETAT_BRAS_RANGE | SPRAY_ETAT_BRAS_BOUGE,
                            SPRAY_ETAT_BRAS_RANGE, 3000));
}

static void balance_perdue_pendant_la_dose(void) {
    monde_t w;
    monde_init(&w);
    VERIFIER(monde_sortir(&w, 643));
    monde_ordre(&w, ORDRE_SPRAY, 3, 100);
    monde_avancer(&w, 3000);
    w.balance_debranchee[2] = true;
    monde_avancer(&w, 200);
    uint32_t pas = w.pas_pompes[2];
    monde_avancer(&w, 500);
    // La pompe s'est arrêtée (on ne sait plus ce qui part).
    VERIFIER(w.pas_pompes[2] == pas);
    VERIFIER(lire(&w, 4) & 4);  // balance 3 muette
    VERIFIER(monde_attendre(&w, 27, 0xFFFF, 1, 10000));
    VERIFIER(lire(&w, 26) == DOSE_TEMPS_MAX && r[20] == 0);
    VERIFIER(monde_attendre(&w, 3, SPRAY_ETAT_BRAS_RANGE | SPRAY_ETAT_BRAS_BOUGE,
                            SPRAY_ETAT_BRAS_RANGE, 3000));
}

static void spray_refuse(void) {
    monde_t w;
    monde_init(&w);
    // Bras pas sorti.
    monde_ordre(&w, ORDRE_SPRAY, 1, 100);
    VERIFIER(lire(&w, 7) == SUITE_REFUSE && r[8] == REFUS_BRAS_PAS_SORTI);
    VERIFIER(monde_sortir(&w, 643));
    // Paramètres.
    monde_ordre(&w, ORDRE_SPRAY, 5, 100);
    VERIFIER(lire(&w, 8) == REFUS_PARAMETRE);
    monde_ordre(&w, ORDRE_SPRAY, 0, 100);
    VERIFIER(lire(&w, 8) == REFUS_PARAMETRE);
    monde_ordre(&w, ORDRE_SPRAY, 1, 0);
    VERIFIER(lire(&w, 8) == REFUS_PARAMETRE);
    // Balance muette.
    w.balance_debranchee[3] = true;
    monde_avancer(&w, 200);
    VERIFIER(lire(&w, 4) == 8 && r[21] == 0);
    monde_ordre(&w, ORDRE_SPRAY, 4, 100);
    VERIFIER(lire(&w, 8) == REFUS_BALANCE);
    // Balance instable (mesures qui sautent de ± 2 g).
    w.bruit_g[0] = 2.0;
    monde_avancer(&w, 200);
    VERIFIER(lire(&w, 4) == (8 | 16));
    monde_ordre(&w, ORDRE_SPRAY, 1, 100);
    VERIFIER(lire(&w, 8) == REFUS_BALANCE);
    // Déjà occupée.
    monde_ordre(&w, ORDRE_SPRAY, 2, 100);
    VERIFIER(lire(&w, 7) == SUITE_EN_COURS);
    monde_ordre(&w, ORDRE_SPRAY, 2, 100);
    VERIFIER(lire(&w, 8) == REFUS_OCCUPEE);
    monde_ordre(&w, ORDRE_NETTOYER, 0, 0);
    VERIFIER(lire(&w, 8) == REFUS_OCCUPEE);
    monde_ordre(&w, ORDRE_ORIGINE, 0, 0);
    VERIFIER(lire(&w, 8) == REFUS_OCCUPEE);
    VERIFIER(w.pas_pompes[0] == 0 && w.pas_pompes[3] == 0);
}

static void ranger_pendant_un_spray(void) {
    monde_t w;
    monde_init(&w);
    VERIFIER(monde_sortir(&w, 643));
    monde_ordre(&w, ORDRE_SPRAY, 1, 100);
    monde_avancer(&w, 3000);
    monde_ordre(&w, ORDRE_RANGER, 0, 0);
    // Pompe et air arrêtés d'abord.
    spray_sorties_t s = spray_sorties(&w.spray);
    VERIFIER(!s.ev_buse && !s.ev_chasse);
    monde_lire(&w, r);
    VERIFIER(r[26] == DOSE_INTERROMPUE && r[27] == 1 && r[7] == SUITE_EN_COURS);
    VERIFIER(monde_attendre(&w, 3, SPRAY_ETAT_BRAS_RANGE | SPRAY_ETAT_BRAS_BOUGE,
                            SPRAY_ETAT_BRAS_RANGE, 3000));
    VERIFIER(lire(&w, 7) == SUITE_FAIT);
}

static void arret_immediat(void) {
    monde_t w;
    monde_init(&w);
    VERIFIER(monde_sortir(&w, 643));
    monde_ordre(&w, ORDRE_AGITER, 60, 30);
    monde_ordre(&w, ORDRE_SPRAY, 1, 100);
    monde_avancer(&w, 3000);
    monde_ordre(&w, ORDRE_ARRET, 0, 0);
    spray_sorties_t s = spray_sorties(&w.spray);
    VERIFIER(!s.ev_buse && !s.ev_chasse && !s.pompe_nettoyage && s.agitateurs_pct == 0);
    monde_lire(&w, r);
    VERIFIER(r[3] & SPRAY_ETAT_ARRET_IMMEDIAT);
    VERIFIER(r[26] == DOSE_INTERROMPUE && r[28] == 0);
    // Le bras reste où il est (le Pi bat toujours).
    int32_t avant = w.bras_reel;
    monde_avancer(&w, 3000);
    VERIFIER(w.bras_reel == avant);
    // Le bit s'efface à l'ordre suivant.
    monde_ordre(&w, ORDRE_RANGER, 0, 0);
    VERIFIER(!bit(&w, SPRAY_ETAT_ARRET_IMMEDIAT));
    // Arrêt pendant que le bras sort : il s'arrête où il est, pas « sorti ».
    VERIFIER(monde_attendre(&w, 3, SPRAY_ETAT_BRAS_RANGE | SPRAY_ETAT_BRAS_BOUGE,
                            SPRAY_ETAT_BRAS_RANGE, 3000));
    monde_ordre(&w, ORDRE_SORTIR, 643, 0);
    monde_avancer(&w, 300);
    monde_ordre(&w, ORDRE_ARRET, 0, 0);
    avant = w.bras_reel;
    monde_avancer(&w, 500);
    VERIFIER(w.bras_reel == avant && avant > 0);
    VERIFIER(!(lire(&w, 3) & (SPRAY_ETAT_BRAS_SORTI | SPRAY_ETAT_BRAS_BOUGE)));
}

// --------------------------------------------------------------- nettoyage et agitateurs

static void nettoyage(void) {
    monde_t w;
    monde_init(&w);
    monde_ordre(&w, ORDRE_NETTOYER, 0, 0);
    VERIFIER(lire(&w, 8) == REFUS_BRAS_PAS_SORTI);
    VERIFIER(monde_sortir(&w, 643));
    uint64_t buse = w.buse_ms;
    monde_ordre(&w, ORDRE_NETTOYER, 0, 0);
    VERIFIER(bit(&w, SPRAY_ETAT_NETTOYAGE_EN_COURS));
    VERIFIER(monde_attendre(&w, 3, SPRAY_ETAT_NETTOYAGE_EN_COURS, 0, 30000));
    monde_lire(&w, r);
    VERIFIER(r[7] == SUITE_FAIT && r[27] == 0);  // pas une dose
    // Petite pompe 5 s, séchage 15 s, air coupé 1 s après.
    VERIFIER(w.nettoyage_ms >= 4990 && w.nettoyage_ms <= 5010);
    VERIFIER(w.chasse_ms >= 14990 && w.chasse_ms <= 15010);
    uint64_t air = w.buse_ms - buse;
    VERIFIER(air >= 20990 && air <= 21020);
    VERIFIER(w.pas_pompes[0] == 0);
}

static void agitateurs(void) {
    monde_t w;
    monde_init(&w);
    monde_ordre(&w, ORDRE_AGITER, 101, 30);
    VERIFIER(lire(&w, 8) == REFUS_PARAMETRE && r[28] == 0);
    monde_ordre(&w, ORDRE_AGITER, 60, 30);
    VERIFIER(lire(&w, 28) == 60 && (r[3] & SPRAY_ETAT_AGITATEURS) && r[7] == SUITE_FAIT);
    VERIFIER(spray_sorties(&w.spray).agitateurs_pct == 60);
    monde_avancer(&w, 29900);
    VERIFIER(lire(&w, 28) == 60);
    monde_avancer(&w, 200);
    VERIFIER(lire(&w, 28) == 0 && !(r[3] & SPRAY_ETAT_AGITATEURS));
    // Durée 0 : arrêt.
    monde_ordre(&w, ORDRE_AGITER, 60, 30);
    monde_ordre(&w, ORDRE_AGITER, 60, 0);
    VERIFIER(lire(&w, 28) == 0);
}

// --------------------------------------------------------------- les ordres

static void ordres_par_leur_numero(void) {
    monde_t w;
    monde_init(&w);
    monde_ordre(&w, 99, 0, 0);
    VERIFIER(lire(&w, 7) == SUITE_REFUSE && r[8] == REFUS_ORDRE_INCONNU);
    VERIFIER(r[6] == w.numero);
    VERIFIER(r[9] < 100);
    // Le même numéro une 2e fois : pas exécuté de nouveau.
    monde_ordre(&w, ORDRE_AGITER, 50, 10);
    VERIFIER(lire(&w, 28) == 50);
    monde_ordre(&w, ORDRE_AGITER, 50, 0);
    VERIFIER(lire(&w, 28) == 0);
    w.numero--;
    monde_ordre(&w, ORDRE_AGITER, 50, 10);
    VERIFIER(lire(&w, 28) == 0);
    // Un battement seul n'exécute rien.
    monde_battre(&w);
    VERIFIER(lire(&w, 6) == w.numero && r[28] == 0);
}

static void pilote_du_bras(void) {
    monde_t w;
    monde_init(&w);
    monde_ordre(&w, ORDRE_ORIGINE, 0, 0);
    monde_attendre(&w, 3, SPRAY_ETAT_ORIGINE_FAITE, SPRAY_ETAT_ORIGINE_FAITE, 3000);
    w.pilote_ok = false;
    monde_avancer(&w, 10);
    VERIFIER(lire(&w, 4) & SPRAY_ERREUR_PILOTE_BRAS);
    monde_battre(&w);
    monde_ordre(&w, ORDRE_SORTIR, 643, 0);
    VERIFIER(lire(&w, 8) == REFUS_ERREUR_BRAS);
    w.pilote_ok = true;
    monde_ordre(&w, ORDRE_EFFACER, 0, 0);
    monde_avancer(&w, 10);
    VERIFIER(lire(&w, 4) == 0);
    // Le pilote a redémarré (24 V coupé) : la prise d'origine est à refaire.
    spray_pilote_redemarre(&w.spray);
    VERIFIER(!bit(&w, SPRAY_ETAT_ORIGINE_FAITE));
}

void essais_spray(void) {
    printf("Carte du spray\n");
    LANCER(au_demarrage);
    LANCER(prise_d_origine);
    LANCER(origine_capteur_en_panne);
    LANCER(sortir_refuse);
    LANCER(sortir_et_ranger);
    LANCER(bras_bloque);
    LANCER(ranger_capteur_en_panne);
    LANCER(bras_pousse);
    LANCER(silence_du_pi_bras_sorti);
    LANCER(silence_du_pi_pendant_un_spray);
    LANCER(une_dose);
    LANCER(dose_pas_atteinte);
    LANCER(balance_perdue_pendant_la_dose);
    LANCER(spray_refuse);
    LANCER(ranger_pendant_un_spray);
    LANCER(arret_immediat);
    LANCER(nettoyage);
    LANCER(agitateurs);
    LANCER(ordres_par_leur_numero);
    LANCER(pilote_du_bras);
}
