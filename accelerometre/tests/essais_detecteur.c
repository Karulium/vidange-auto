#include "detecteur.h"
#include "essai.h"

// Réglages fixes pour ces essais (indépendants de accelerometre.yaml).
static reglages_t reglages_essai(void) {
    reglages_t r = {
        .pleine_echelle_g = 8,
        .mesures_par_seconde = 400,
        .axes = AXE_X | AXE_Y,
        .seuil_mg = 1500,
        .duree_min_ms = 5,
        .maintien_ms = 500,
        .constante_fond_ms = 2000,
        .sans_mesure_ms = 50,
        .erreurs_lecture_max = 3,
        .figee_ms = 1000,
        .reessai_ms = 2000,
    };
    return r;
}

#define PERIODE_US 2500  // 400 mesures par seconde

// Un capteur au repos : un peu de bruit (comme un vrai), pesanteur sur z.
typedef struct {
    detecteur_t d;
    uint64_t t;
    uint32_t bruit;
    int32_t mg[3];
} banc_t;

static void banc_demarrer(banc_t *b, reglages_t r) {
    detecteur_demarrer(&b->d, &r);
    b->t = 1000000;
    b->bruit = 1;
    b->mg[0] = 0;
    b->mg[1] = 0;
    b->mg[2] = 1000;
    if (detecteur_verification_due(&b->d, b->t)) {
        detecteur_verification_faite(&b->d, b->t, 0);
    }
}

// « ms » millisecondes de mesures ; rend le nombre de mesures où OK était donné.
static int banc_mesurer(banc_t *b, uint32_t ms, bool avec_bruit) {
    int ok = 0;
    for (uint32_t i = 0; i < ms * 1000 / PERIODE_US; i++) {
        b->t += PERIODE_US;
        int32_t mesure[3];
        for (int axe = 0; axe < 3; axe++) {
            b->bruit = b->bruit * 1103515245u + 12345u;
            mesure[axe] = b->mg[axe] + (avec_bruit ? (int32_t)((b->bruit >> 16) % 3) * 4 - 4 : 0);
        }
        detecteur_mesure(&b->d, b->t, mesure);
        detecteur_surveiller(&b->d, b->t);
        ok += detecteur_ok(&b->d);
    }
    return ok;
}

static void ok_au_repos(void) {
    banc_t b;
    banc_demarrer(&b, reglages_essai());
    VERIFIER(!detecteur_ok(&b.d));  // pas encore de mesure
    banc_mesurer(&b, 10, true);
    VERIFIER(detecteur_ok(&b.d));
    VERIFIER(banc_mesurer(&b, 5000, true) == 2000);
    VERIFIER(b.d.chocs == 0);
}

static void pas_de_ok_avant_la_verification_du_capteur(void) {
    detecteur_t d;
    reglages_t r = reglages_essai();
    detecteur_demarrer(&d, &r);
    VERIFIER(detecteur_verification_due(&d, 0));
    int32_t mg[3] = {0, 0, 1000};
    detecteur_mesure(&d, 1000, mg);
    detecteur_mesure(&d, 3500, mg);
    VERIFIER(!detecteur_ok(&d));
}

static void choc_coupe_ok_puis_ok_revient(void) {
    banc_t b;
    banc_demarrer(&b, reglages_essai());
    banc_mesurer(&b, 100, true);
    b.mg[0] = 2500;  // choc de 2,5 g sur x pendant 20 ms
    banc_mesurer(&b, 20, true);
    VERIFIER(!detecteur_ok(&b.d));
    VERIFIER(b.d.en_choc);
    VERIFIER(b.d.chocs == 1);
    VERIFIER(b.d.pic_choc_mg >= 2490 && b.d.pic_choc_mg <= 2510);
    b.mg[0] = 0;
    // OK reste coupé pendant le maintien (500 ms) après le dernier dépassement...
    VERIFIER(banc_mesurer(&b, 495, true) == 0);
    // ... puis revient.
    banc_mesurer(&b, 10, true);
    VERIFIER(detecteur_ok(&b.d));
    VERIFIER(b.d.chocs == 1);
}

static void choc_en_diagonale(void) {
    banc_t b;
    banc_demarrer(&b, reglages_essai());
    banc_mesurer(&b, 100, true);
    // 1,2 g sur x et 1,2 g sur y : 1,7 g à l'horizontale, au-dessus du seuil.
    b.mg[0] = 1200;
    b.mg[1] = 1200;
    banc_mesurer(&b, 20, true);
    VERIFIER(b.d.chocs == 1);
}

static void pic_trop_court_ignore(void) {
    banc_t b;
    banc_demarrer(&b, reglages_essai());
    banc_mesurer(&b, 100, true);
    b.mg[1] = 3000;  // 2 mesures, à 2,5 ms l'une de l'autre : moins que duree_min_ms
    banc_mesurer(&b, 5, true);
    b.mg[1] = 0;
    VERIFIER(banc_mesurer(&b, 100, true) == 40);
    VERIFIER(b.d.chocs == 0);
}

static void duree_min_nulle_une_mesure_suffit(void) {
    reglages_t r = reglages_essai();
    r.duree_min_ms = 0;
    banc_t b;
    banc_demarrer(&b, r);
    banc_mesurer(&b, 100, true);
    b.mg[1] = 3000;
    banc_mesurer(&b, 3, true);  // une seule mesure
    VERIFIER(b.d.chocs == 1);
}

static void axe_vertical_ignore(void) {
    banc_t b;
    banc_demarrer(&b, reglages_essai());
    banc_mesurer(&b, 100, true);
    b.mg[2] = 4000;  // secousse verticale (axes : x et y seulement)
    VERIFIER(banc_mesurer(&b, 50, true) == 20);
    VERIFIER(b.d.chocs == 0);
}

static void pente_du_capteur_pas_un_choc(void) {
    banc_t b;
    banc_demarrer(&b, reglages_essai());
    // Capteur monté penché : la pesanteur donne 0,5 g sur x dès le départ.
    b.mg[0] = 500;
    banc_mesurer(&b, 100, true);
    VERIFIER(detecteur_ok(&b.d));
    // Puis une dérive lente (1 g en 20 s) : le fond la suit.
    for (int i = 0; i < 100; i++) {
        b.mg[0] += 10;
        banc_mesurer(&b, 200, true);
    }
    VERIFIER(b.d.chocs == 0);
    VERIFIER(detecteur_ok(&b.d));
}

static void capteur_tordu_ok_reste_coupe(void) {
    banc_t b;
    banc_demarrer(&b, reglages_essai());
    banc_mesurer(&b, 100, true);
    // Le support se tord : 2 g d'un coup et pour de bon. Le fond ne suit pas pendant un
    // dépassement : OK reste coupé (il faut aller voir). Seules les 2 premières mesures
    // (moins de duree_min_ms) gardent OK.
    b.mg[0] = 2000;
    VERIFIER(banc_mesurer(&b, 10000, true) == 2);
    VERIFIER(!detecteur_ok(&b.d));
    VERIFIER(b.d.chocs == 1);
}

static void plus_de_mesure_panne_puis_reessai(void) {
    banc_t b;
    banc_demarrer(&b, reglages_essai());
    banc_mesurer(&b, 100, true);
    VERIFIER(detecteur_ok(&b.d));
    detecteur_surveiller(&b.d, b.t + 50000);  // 50 ms : encore bon
    VERIFIER(detecteur_ok(&b.d));
    detecteur_surveiller(&b.d, b.t + 51000);
    VERIFIER(!detecteur_ok(&b.d));
    VERIFIER(b.d.pannes == PANNE_MESURE_ABSENTE);
    // Revérification seulement après reessai_ms.
    VERIFIER(!detecteur_verification_due(&b.d, b.t + 51000 + 1999000));
    VERIFIER(detecteur_verification_due(&b.d, b.t + 51000 + 2000000));
    b.t += 51000 + 2000000;
    detecteur_verification_faite(&b.d, b.t, 0);
    VERIFIER(b.d.pannes == 0);
    VERIFIER(b.d.pannes_vues == PANNE_MESURE_ABSENTE);
    banc_mesurer(&b, 10, true);
    VERIFIER(detecteur_ok(&b.d));
}

static void heure_d_avant_la_verification(void) {
    // Le programme principal prend l'heure, puis vérifie le capteur (quelques centaines de
    // ms) : cette heure, plus vieille que la vérification, ne doit pas faire une panne.
    detecteur_t d;
    reglages_t r = reglages_essai();
    detecteur_demarrer(&d, &r);
    detecteur_verification_faite(&d, 5000000, 0);
    detecteur_surveiller(&d, 4700000);
    VERIFIER(d.pannes == 0);
    int32_t mg[3] = {0, 0, 1000};
    detecteur_mesure(&d, 4700000, mg);
    detecteur_surveiller(&d, 5002500);
    VERIFIER(d.pannes == 0);
    VERIFIER(detecteur_ok(&d));
}

static void mesure_figee_panne(void) {
    banc_t b;
    banc_demarrer(&b, reglages_essai());
    banc_mesurer(&b, 100, true);
    VERIFIER(banc_mesurer(&b, 990, false) > 0);
    banc_mesurer(&b, 20, false);
    VERIFIER(!detecteur_ok(&b.d));
    VERIFIER(b.d.pannes == PANNE_MESURE_FIGEE);
}

static void lectures_ratees(void) {
    banc_t b;
    banc_demarrer(&b, reglages_essai());
    banc_mesurer(&b, 100, true);
    // Deux ratées puis une bonne : rien.
    detecteur_erreur_lecture(&b.d, b.t);
    detecteur_erreur_lecture(&b.d, b.t);
    banc_mesurer(&b, 3, true);
    detecteur_erreur_lecture(&b.d, b.t);
    detecteur_erreur_lecture(&b.d, b.t);
    VERIFIER(detecteur_ok(&b.d));
    detecteur_erreur_lecture(&b.d, b.t);
    VERIFIER(!detecteur_ok(&b.d));
    VERIFIER(b.d.pannes == PANNE_LECTURE);
}

static void autotest_rate_puis_reussi(void) {
    detecteur_t d;
    reglages_t r = reglages_essai();
    detecteur_demarrer(&d, &r);
    detecteur_verification_faite(&d, 0, PANNE_AUTOTEST);
    VERIFIER(!detecteur_ok(&d));
    VERIFIER(!detecteur_verification_due(&d, 1000000));
    VERIFIER(detecteur_verification_due(&d, 2000000));
    detecteur_verification_faite(&d, 2000000, 0);
    VERIFIER(d.pret);
    VERIFIER(d.pannes == 0);
}

static void reglages_faux_jamais_ok(void) {
    reglages_t r = reglages_essai();
    r.seuil_mg = 9000;  // plus que la pleine échelle
    banc_t b;
    banc_demarrer(&b, r);
    VERIFIER(b.d.pannes == PANNE_REGLAGES);
    VERIFIER(!detecteur_verification_due(&b.d, b.t + 100000000));
    VERIFIER(banc_mesurer(&b, 100, true) == 0);
}

static void changer_le_seuil(void) {
    banc_t b;
    banc_demarrer(&b, reglages_essai());
    VERIFIER(!detecteur_changer_seuil(&b.d, 0));
    VERIFIER(!detecteur_changer_seuil(&b.d, 8000));
    VERIFIER(b.d.reglages.seuil_mg == 1500);
    VERIFIER(detecteur_changer_seuil(&b.d, 3000));
    banc_mesurer(&b, 100, true);
    b.mg[0] = 2500;
    banc_mesurer(&b, 20, true);
    VERIFIER(b.d.chocs == 0);
}

static void historique_des_chocs(void) {
    banc_t b;
    banc_demarrer(&b, reglages_essai());
    banc_mesurer(&b, 100, true);
    choc_t choc;
    VERIFIER(!detecteur_choc(b.d.historique, b.d.chocs, 1, &choc));  // pas encore arrivé
    b.mg[1] = 3000;  // choc de 3 g sur y pendant 20 ms
    banc_mesurer(&b, 20, true);
    VERIFIER(detecteur_choc(b.d.historique, b.d.chocs, 1, &choc));
    VERIFIER(choc.numero == 1 && !choc.fini);
    VERIFIER(choc.pic_mg >= 2990 && choc.pic_mg <= 3010);
    VERIFIER(choc.duree_ms >= 17 && choc.duree_ms <= 20);
    VERIFIER(choc.t_debut_us > 1000000);
    b.mg[1] = 0;
    banc_mesurer(&b, 600, true);
    VERIFIER(detecteur_choc(b.d.historique, b.d.chocs, 1, &choc) && choc.fini);
    VERIFIER(choc.duree_ms >= 17 && choc.duree_ms <= 20);  // la durée du dépassement
    VERIFIER(!detecteur_choc(b.d.historique, b.d.chocs, 0, &choc));
    VERIFIER(!detecteur_choc(b.d.historique, b.d.chocs, 2, &choc));
    // 19 chocs de plus : seuls les 16 derniers restent.
    for (int i = 0; i < 19; i++) {
        b.mg[1] = 2000;
        banc_mesurer(&b, 20, true);
        b.mg[1] = 0;
        banc_mesurer(&b, 600, true);
    }
    VERIFIER(b.d.chocs == 20);
    VERIFIER(!detecteur_choc(b.d.historique, b.d.chocs, 4, &choc));
    VERIFIER(detecteur_choc(b.d.historique, b.d.chocs, 5, &choc) && choc.numero == 5);
    VERIFIER(detecteur_choc(b.d.historique, b.d.chocs, 20, &choc) && choc.fini);
}

static void panne_pendant_un_choc(void) {
    banc_t b;
    banc_demarrer(&b, reglages_essai());
    banc_mesurer(&b, 100, true);
    b.mg[0] = 2500;
    banc_mesurer(&b, 20, true);
    VERIFIER(b.d.en_choc);
    detecteur_verification_faite(&b.d, b.t, PANNE_CAPTEUR);
    choc_t choc;
    VERIFIER(!b.d.en_choc);
    VERIFIER(detecteur_choc(b.d.historique, b.d.chocs, 1, &choc) && choc.fini);
}

static void changer_les_reglages(void) {
    banc_t b;
    banc_demarrer(&b, reglages_essai());
    banc_mesurer(&b, 100, true);
    VERIFIER(detecteur_ok(&b.d));
    // Un autre seuil et un autre maintien : la mesure continue, OK reste donné.
    reglages_t r = reglages_essai();
    r.seuil_mg = 2000;
    r.maintien_ms = 800;
    VERIFIER(detecteur_changer_reglages(&b.d, &r));
    VERIFIER(b.d.reglages.seuil_mg == 2000 && b.d.reglages.maintien_ms == 800);
    VERIFIER(detecteur_ok(&b.d));
    VERIFIER(!detecteur_verification_due(&b.d, b.t));
    // Des réglages faux : refusés, rien ne change.
    r.seuil_mg = 9000;
    VERIFIER(!detecteur_changer_reglages(&b.d, &r));
    VERIFIER(b.d.reglages.seuil_mg == 2000);
    // Une autre pleine échelle : le capteur est revérifié tout de suite.
    r = reglages_essai();
    r.pleine_echelle_g = 16;
    VERIFIER(detecteur_changer_reglages(&b.d, &r));
    VERIFIER(!detecteur_ok(&b.d));
    VERIFIER(detecteur_verification_due(&b.d, b.t));
    detecteur_verification_faite(&b.d, b.t, 0);
    banc_mesurer(&b, 10, true);
    VERIFIER(detecteur_ok(&b.d));
}

static void le_pi_corrige_des_reglages_faux(void) {
    reglages_t r = reglages_essai();
    r.seuil_mg = 9000;
    banc_t b;
    banc_demarrer(&b, r);
    VERIFIER(b.d.pannes == PANNE_REGLAGES);
    r.seuil_mg = 1500;
    VERIFIER(detecteur_changer_reglages(&b.d, &r));
    VERIFIER(b.d.pannes == 0);
    VERIFIER(detecteur_verification_due(&b.d, b.t));
    detecteur_verification_faite(&b.d, b.t, 0);
    banc_mesurer(&b, 10, true);
    VERIFIER(detecteur_ok(&b.d));
}

void essais_detecteur(void) {
    LANCER(ok_au_repos);
    LANCER(pas_de_ok_avant_la_verification_du_capteur);
    LANCER(choc_coupe_ok_puis_ok_revient);
    LANCER(choc_en_diagonale);
    LANCER(pic_trop_court_ignore);
    LANCER(duree_min_nulle_une_mesure_suffit);
    LANCER(axe_vertical_ignore);
    LANCER(pente_du_capteur_pas_un_choc);
    LANCER(capteur_tordu_ok_reste_coupe);
    LANCER(plus_de_mesure_panne_puis_reessai);
    LANCER(heure_d_avant_la_verification);
    LANCER(mesure_figee_panne);
    LANCER(lectures_ratees);
    LANCER(autotest_rate_puis_reussi);
    LANCER(reglages_faux_jamais_ok);
    LANCER(changer_le_seuil);
    LANCER(historique_des_chocs);
    LANCER(panne_pendant_un_choc);
    LANCER(changer_les_reglages);
    LANCER(le_pi_corrige_des_reglages_faux);
}
