"""Pose du couvercle sur le seau plein (tâche 41 bis) : réglages vérifiés au démarrage, gestes de la
fiche au simulateur (prise, pose, cas d'erreur des étapes 3, 4, 6, 7, 10a, 10b, 12 et 13), poste
branché dans le cycle."""

import pytest

from vidange.couvercle.simulation import MondeCouvercle
from vidange.cycle import ModeSeaux, verifier_ordre
from vidange.cycle.simulation import PiecesSimulees, lot_du_simulateur
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.reglages import charger_reglages
from vidange.simulateur import Simulateur
from vidange.stockage import places

from .conftest import DOSSIER_PI
from .test_reglages import erreur_de, remplacer

LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
COUVERCLE = MACHINE.couvercle
assert COUVERCLE is not None


def deux_seaux(reglages=REGLAGES, **changements):
    """Les réglages du simulateur avec un lot de 2 seaux (sans prise double) : plus court."""
    cycle = reglages.simulateur.cycle.model_copy(
        update={"seaux": 2, "prises_doubles": [], **changements}
    )
    simule = reglages.simulateur.model_copy(update={"cycle": cycle})
    return reglages.model_copy(update={"simulateur": simule})


def jouer(regler=lambda monde, tete: None, reglages=None):
    """Le cycle du simulateur (2 seaux) avec une panne réglée avant le départ. Rend le planning, le
    monde des couvercles, la préhension et les gestes de la tête (texte, vitesse)."""
    reglages = reglages or deux_seaux()
    with Simulateur(reglages, LISTE, "cycle") as simulateur:
        pieces = PiecesSimulees(simulateur)
        mode = ModeSeaux(reglages, pieces, simulateur.chef)
        modules = mode.modules_du_lot(lot_du_simulateur(simulateur))
        tete = pieces.scenario.prehension.tete
        gestes = []
        executer = tete.executer

        def note(pas, cible, poids):
            gestes.append((pas.texte, pas.vitesse, cible.z))
            executer(pas, cible, poids)

        tete.executer = note
        regler(pieces.monde_couvercle, tete)
        planning = simulateur.jouer(modules)
        return planning, pieces.monde_couvercle, pieces.scenario, gestes, mode


def vide_refuse_a_la_pile(monde, tete, refus):
    """La ventouse refuse les `refus` premières impulsions faites à la pile des couvercles (le
    seau, lui, est pris normalement)."""
    original = tete.vanne
    fait = {"oui": False}

    def vanne(ouverte):
        pose = tete.position()
        if ouverte and not fait["oui"] and monde._pres(monde.pile, pose.x, pose.y):
            tete.vides_refuses = refus
            fait["oui"] = True
        original(ouverte)

    tete.vanne = vanne


# ---------------------------------------------------------------- réglages


def test_les_hauteurs_de_pose_sont_celles_de_la_fiche():
    # Z_pose = H_app + 0,459 − Hc : A, B, C 0,439 ; D 0,446 (course basse du plateau).
    assert COUVERCLE.exemple
    for format, attendu in (("seau_a", 0.439), ("seau_b", 0.439), ("seau_c", 0.439)):
        assert MACHINE.z_pose_couvercle(format) == pytest.approx(attendu)
    assert MACHINE.z_pose_couvercle("seau_d") == pytest.approx(0.446)
    pose = COUVERCLE.pose
    assert (pose.x, pose.y) == (0.925, 0.49)
    # Le couvercle est pris 1 cm hors d'axe (pile en y 0,84, outil en y 0,83) : il arrive à y 0,50.
    assert places.prise_y(MACHINE, MACHINE.stockage.piles.couvercles[1]) == pytest.approx(0.83)
    assert MACHINE.fermeture.chariot_y == 0.50
    # Vitesses : 80 mm/s en Z rapide, 20 mm/s à la pile, 10 mm/s à la pose.
    vitesses = MACHINE.prehension.vitesses
    assert (vitesses.z, vitesses.couvercle_pile, vitesses.couvercle_pose) == (0.08, 0.02, 0.01)
    assert MACHINE.prehension.vide.prise_kpa == -55 and MACHINE.prehension.vide.perte_kpa == -40
    assert COUVERCLE.formats["seau_c"].descente_lente_z == (0.67, 0.57)
    assert COUVERCLE.tolerance_kg("seau_a") == pytest.approx(0.13 * 0.30)


@pytest.mark.parametrize(
    ("ancien", "nouveau", "message"),
    [
        (
            "    x: 0.925\n    y: 0.49\n",
            "    x: 0.925\n    y: 0.50\n",
            "l'outil se pose à fermeture → chariot_y − 0.01",
        ),
        ("    x: 0.925\n    y: 0.49", "    x: 0.90\n    y: 0.49", "doit être l'axe du plateau"),
        ("    lache_kpa: -5\n    souffle_s", "    lache_kpa: -45\n    souffle_s", "lache_kpa"),
        ("    haut_sans_memoire_z: 0.90", "    haut_sans_memoire_z: 1.09", "haut sans mémoire"),
        ("    fenetre_m: 0.008", "    fenetre_m: 0.05", "fenetre_m doit être plus petit"),
        ("    couvercle_pose: 0.01", "    couvercle_pose: 0.5", "plus grande que la vitesse"),
        ("    seau_d: {masse_kg: 0.13}\n", "", "le format « seau_d » de la fermeture"),
        (
            "descente_lente_z: [0.67, 0.57]",
            "descente_lente_z: [0.67, 0.45]",
            "seau_c → descente_lente_z",
        ),
    ],
)
def test_un_reglage_du_couvercle_faux_empeche_de_demarrer(reglages, ancien, nouveau, message):
    remplacer(reglages / "machine.yaml", ancien, nouveau)
    assert message in erreur_de(reglages)


def test_sans_pile_de_couvercles_ni_objet_le_demarrage_refuse(reglages):
    remplacer(
        reglages / "machine.yaml", "    couvercle: {rayon_m: 0.14,", "    coucou: {rayon_m: 0.14,"
    )
    assert "il manque « couvercle »" in erreur_de(reglages)


# ---------------------------------------------------------------- le geste, de bout en bout


def test_un_couvercle_est_pris_pose_pese_puis_le_seau_est_ferme():
    planning, monde, scenario, gestes, mode = jouer()
    assert planning.fini, planning.probleme
    etapes = [ligne.etape for ligne in planning.lignes if ligne.module == "remplissage"]
    assert etapes.count("prendre_le_couvercle") == 2 and etapes.count("fermer_le_seau") == 2
    # Dans l'ordre de la fiche : le couvercle est posé avant d'être clipsé, la balance vérifie.
    couvercle = [e for e in etapes if e.endswith("_le_couvercle")]
    assert (
        couvercle
        == [
            "preparer_le_couvercle",
            "prendre_le_couvercle",
            "poser_le_couvercle",
            "controler_le_couvercle",
        ]
        * 2
    )
    assert etapes.index("poser_le_couvercle") < etapes.index("fermer_le_seau")
    assert scenario.fermeture.fermeture.fermes == ["S0301", "S0302"]
    # Un couvercle de moins sur la pile à chaque seau, aucun tombé, aucun encore tenu.
    assert (monde.nombre, monde.tenus, monde.tombes) == (22, 0, 0)
    assert monde.prises == [1, 1]
    assert mode.en_cours.pieces.plan.magasin.inventaire.couvercles == 22
    # Haut de la pile gardé : la face au contact de la dernière prise.
    fond = MACHINE.stockage.plateau_z
    assert mode.en_cours.pieces.couvercle.haut_pile_z == pytest.approx(fond + 23 * 0.009)


def test_les_vitesses_et_les_cotes_sont_celles_de_la_fiche():
    planning, monde, scenario, gestes, _ = jouer()
    assert planning.fini, planning.probleme
    zp = MACHINE.z_pose_couvercle("seau_a")
    par_texte = {}
    for texte, vitesse, z in gestes:
        par_texte.setdefault(texte, []).append((vitesse, z))
    # 2) descente rapide au-dessus de la pile, 3) approche lente à 20 mm/s.
    assert par_texte["descente rapide vers la pile des couvercles"][0] == (
        None,
        pytest.approx(0.93),
    )
    assert par_texte["approche lente de la pile des couvercles"][0][0] == "couvercle_pile"
    # 9) rapide jusqu'à Z_pose + 0,040, 10) lente à 10 mm/s jusqu'à Z_pose − 0,015.
    assert par_texte["descente rapide vers le seau"][0] == (None, pytest.approx(zp + 0.04))
    assert par_texte["approche lente du seau"][0] == ("couvercle_pose", pytest.approx(zp - 0.015))
    # 5) et 12) décollage et dégagement lents à 20 mm/s.
    assert par_texte["décollage lent du couvercle"][0][0] == "couvercle_pile"
    assert par_texte["dégagement lent"][0] == ("couvercle_pile", pytest.approx(zp + 0.005 - 0.0))
    assert par_texte["dégagement lent (suite)"][0][1] == pytest.approx(zp + 0.02, abs=0.002)
    # Pas de format C ici : pas de descente lente du passage près de la tête du micropore.
    assert not [t for t, _, _ in gestes if "tête du micropore" in t]


def test_la_deuxieme_prise_part_du_haut_garde_en_memoire():
    planning, monde, scenario, gestes, _ = jouer()
    assert planning.fini, planning.probleme
    rapides = [
        z for texte, _, z in gestes if texte == "descente rapide vers la pile des couvercles"
    ]
    fond = MACHINE.stockage.plateau_z
    # 1re prise : sans mémoire, haut prévu 0,90 (+ 3 cm) ; 2e : 3 cm au-dessus du contact noté.
    assert rapides[0] == pytest.approx(0.90 + 0.03)
    assert rapides[1] == pytest.approx(fond + 24 * 0.009 + 0.03)


def test_format_c_descente_lente_pres_de_la_tete_du_micropore():
    cycle = REGLAGES.simulateur.cycle
    piles = {nom: pile.model_copy(update={"format": "seau_c"}) for nom, pile in cycle.piles.items()}
    reglages = deux_seaux(format="seau_c", piles=piles)
    planning, monde, scenario, gestes, _ = jouer(reglages=reglages)
    assert planning.fini, planning.probleme
    lentes = [(v, z) for t, v, z in gestes if t.startswith("descente lente (passage")]
    # Face 0,67 → 0,57 à 10 mm/s, pour chacun des 2 seaux.
    assert lentes == [("couvercle_pose", pytest.approx(0.57))] * 2
    rapides = [z for t, _, z in gestes if t == "descente rapide vers le seau"]
    assert rapides[0] == pytest.approx(0.67)


# ---------------------------------------------------------------- cas d'erreur de la fiche


def test_etape_3_pile_vide():
    def regler(monde, tete):
        monde.nombre = 0

    planning, monde, *_ = jouer(regler)
    assert "alarme de « remplissage », étape « prendre_le_couvercle »" in planning.probleme
    assert "plus de couvercles" in planning.probleme
    assert "dire à l'écran combien" in planning.probleme
    # Rien n'est pris, le haut de la pile est oublié.
    assert monde.prises == []


def test_etape_3_pile_presque_vide_le_dernier_couvercle_est_pris():
    def regler(monde, tete):
        monde.nombre = 2

    planning, monde, *_ = jouer(regler)
    # 2 couvercles pour 2 seaux : le dernier (face = fond + 9 mm) est bien trouvé au contact.
    assert planning.fini, planning.probleme
    assert monde.nombre == 0


def test_etape_4_une_impulsion_ratee_puis_la_prise_reussit():
    def regler(monde, tete):
        vide_refuse_a_la_pile(monde, tete, 1)

    planning, monde, scenario, gestes, _ = jouer(regler)
    assert planning.fini, planning.probleme
    # La 2e impulsion a suffi : pas de nouvel essai.
    assert "remonter avant le nouvel essai" not in [t for t, _, _ in gestes]


def test_etape_4_vide_non_atteint_apres_deux_essais():
    def regler(monde, tete):
        vide_refuse_a_la_pile(monde, tete, 99)

    planning, monde, *_ = jouer(regler)
    assert "étape « prendre_le_couvercle »" in planning.probleme
    assert "vide de -55 kPa pas atteint au couvercle après 2 essais" in planning.probleme
    assert monde.tenus == 0 and monde.nombre == 24


def test_etape_4_un_nouvel_essai_remonte_de_5_mm_et_redescend_au_contact():
    def regler(monde, tete):
        # Les 2 impulsions du 1er essai échouent, le 2e essai réussit.
        vide_refuse_a_la_pile(monde, tete, 2)

    planning, monde, scenario, gestes, _ = jouer(regler)
    assert planning.fini, planning.probleme
    textes = [t for t, _, _ in gestes]
    assert textes.count("remonter avant le nouvel essai") == 1
    # Il redescend ensuite jusqu'au contact de la pile : 2 approches lentes pour la 1re prise.
    assert textes.count("approche lente de la pile des couvercles") == 3
    assert monde.prises == [1, 1]


def test_etape_6_deux_couvercles_colles_sont_reposes_puis_un_seul_est_pris():
    def regler(monde, tete):
        monde.colles = 1

    planning, monde, scenario, gestes, _ = jouer(regler)
    assert planning.fini, planning.probleme
    # La 1re prise ramène deux couvercles, reposés ; la prise refaite en ramène un seul.
    assert monde.prises[:2] == [2, 1]
    assert monde.nombre == 22
    # Les deux couvercles ont été reposés avant la 2e prise (remontée de 5 mm).
    assert "remonter avant la nouvelle prise" in [t for t, _, _ in gestes]


def test_etape_6_deux_couvercles_colles_au_deuxieme_essai_alerte():
    def regler(monde, tete):
        monde.colles = 2

    planning, monde, *_ = jouer(regler)
    assert "étape « prendre_le_couvercle »" in planning.probleme
    assert "deux couvercles collés" in planning.probleme
    assert "reposé(s) deux fois" in planning.probleme
    # Les couvercles sont revenus sur la pile (contact M8), aucun n'est perdu.
    assert monde.tenus == 0 and monde.nombre == 24


def test_etape_6_un_poids_qui_n_est_pas_celui_d_un_couvercle():
    def regler(monde, tete):
        monde.masse_kg = 0.05

    planning, *_ = jouer(regler)
    assert "couvercle pesé" in planning.probleme and "attendu" in planning.probleme


def test_etape_7_vide_perdu_en_route_arret_sur_place():
    def regler(monde, tete):
        executer = tete.executer

        def surveille(pas, cible, poids):
            if pas.texte == "trajet du couvercle":
                tete.pertes_de_vide = 1
            executer(pas, cible, poids)

        tete.executer = surveille

    planning, monde, scenario, *_ = jouer(regler)
    assert "étape « poser_le_couvercle »" in planning.probleme
    assert "couvercle lâché en route" in planning.probleme
    assert monde.tombes == 1 and scenario.prehension.objet is None


def test_etape_10a_contact_trop_tot_la_tete_remonte_avec_le_couvercle():
    def regler(monde, tete):
        monde.ecart_pose_m = 0.02

    planning, monde, scenario, *_ = jouer(regler)
    assert "étape « poser_le_couvercle »" in planning.probleme
    assert "couvercle mal posé" in planning.probleme
    assert "vérifier l'anse du seau" in planning.probleme
    # Remontée AVEC le couvercle, vide gardé : il est toujours tenu, pas posé, pas de fermeture.
    assert scenario.prehension.objet is not None and scenario.prehension.objet.sorte == "couvercle"
    assert monde.tenus == 1 and monde.sur_le_seau == 0
    assert scenario.prehension.tete.vide_kpa() < -40
    assert scenario.fermeture.fermeture.fermes == []
    assert scenario.prehension.pose.z > 0.8


def test_etape_10_un_contact_un_peu_haut_mais_dans_la_fenetre_est_accepte():
    def regler(monde, tete):
        monde.ecart_pose_m = 0.006

    planning, monde, *_ = jouer(regler)
    assert planning.fini, planning.probleme
    assert monde.sur_le_seau == 2


def test_etape_10b_pas_de_contact_pas_de_seau():
    def regler(monde, tete):
        monde.pas_de_seau = True

    planning, monde, scenario, *_ = jouer(regler)
    assert "étape « poser_le_couvercle »" in planning.probleme
    assert "pas de contact jusqu'à 0,424 m" in planning.probleme
    assert "pas de seau ou couvercle tombé" in planning.probleme
    # La tête a remonté en gardant le couvercle ; rien n'est posé.
    assert monde.tenus == 1 and monde.sur_le_seau == 0


def test_etape_11_vide_qui_ne_revient_pas_deux_souffles_puis_alerte():
    def regler(monde, tete):
        tete.vides_colles = 5

    planning, *_ = jouer(regler)
    assert "étape « poser_le_couvercle »" in planning.probleme
    assert "couvercle resté collé à la ventouse" in planning.probleme


def test_etape_12_le_m8_ne_retombe_pas_nouveau_souffle_puis_ca_passe():
    def regler(monde, tete):
        monde.m8_colle = 1

    planning, monde, *_ = jouer(regler)
    assert planning.fini, planning.probleme
    assert monde.m8_colle == 0


def test_etape_12_le_m8_ne_retombe_toujours_pas_alerte():
    def regler(monde, tete):
        monde.m8_colle = 3

    planning, *_ = jouer(regler)
    assert "étape « poser_le_couvercle »" in planning.probleme
    assert "resté collé à la ventouse" in planning.probleme


def test_etape_13_la_balance_ne_voit_pas_le_couvercle():
    def regler(monde, tete):
        monde.ne_tient_pas_sur_le_seau = True

    planning, monde, scenario, *_ = jouer(regler)
    assert "étape « controler_le_couvercle »" in planning.probleme
    assert "couvercle pas sur le seau" in planning.probleme
    assert monde.tombes == 1
    assert scenario.fermeture.fermeture.fermes == []


def test_etape_13_le_palier_pese_ne_revient_pas_a_vide():
    def regler(monde, tete):
        monde.palier_n = 3.0

    planning, *_ = jouer(regler)
    assert "étape « poser_le_couvercle »" in planning.probleme
    assert "le palier pesé lit 3.00 N" in planning.probleme


def test_la_fermeture_attend_que_la_prehension_ait_lache_et_soit_remontee():
    planning, monde, scenario, gestes, _ = jouer()
    assert planning.fini, planning.probleme
    remplissage = scenario.remplissage
    # Après le dernier seau : la tête ne tient rien et reste au-dessus de z 0,60.
    assert remplissage.prehension_degagee() is None
    assert COUVERCLE.pose.x == pytest.approx(0.925)
    lignes = [ligne for ligne in planning.lignes if ligne.module == "remplissage"]
    noms = [ligne.etape for ligne in lignes]
    poser = lignes.index(next(ligne for ligne in lignes if ligne.etape == "poser_le_couvercle"))
    fermer = noms.index("fermer_le_seau")
    assert poser < fermer
    # La fermeture ne commence qu'après la fin de la pose (tête remontée).
    assert lignes[fermer].debut >= lignes[poser].fin


# ---------------------------------------------------------------- dans le cycle


def test_le_poste_couvercle_est_lance_avec_la_fermeture_derriere():
    with Simulateur(REGLAGES, LISTE, "cycle") as simulateur:
        mode = ModeSeaux(REGLAGES, PiecesSimulees(simulateur), simulateur.chef)
    assert mode.etats["couvercle"].pret and mode.etats["fermeture"].pret
    assert mode.postes_lances.index("couvercle") < mode.postes_lances.index("fermeture")
    assert not mode.etats["couvercle"].poste.case_vide


def test_pas_de_couvercle_pas_de_fermeture_pas_de_couvercle_sans_fermeture():
    sans = REGLAGES.model_copy(update={"machine": MACHINE.model_copy(update={"couvercle": None})})
    with Simulateur(sans, LISTE, "cycle") as simulateur:
        mode = ModeSeaux(sans, PiecesSimulees(simulateur), simulateur.chef)
    assert mode.etats["couvercle"].raison == "machine.yaml n'a pas de partie « couvercle »"
    assert mode.etats["fermeture"].raison == "attend « couvercle » (pas prêt)"
    simule = REGLAGES.simulateur.model_copy(update={"fermeture": None})
    sans = REGLAGES.model_copy(update={"simulateur": simule})
    with Simulateur(sans, LISTE, "cycle") as simulateur:
        mode = ModeSeaux(sans, PiecesSimulees(simulateur), simulateur.chef)
    assert "n'a pas de fermeture" in mode.etats["fermeture"].raison
    assert mode.etats["couvercle"].raison == "attend « fermeture » (pas prêt)"


def test_sans_pile_imaginaire_le_poste_n_est_pas_lance():
    reglages = deux_seaux(couvercles=0)
    with Simulateur(reglages, LISTE, "cycle") as simulateur:
        mode = ModeSeaux(reglages, PiecesSimulees(simulateur), simulateur.chef)
    assert "pas de pile de couvercles" in mode.etats["couvercle"].raison
    assert not mode.etats["fermeture"].pret


def test_l_ordre_du_cycle_est_couvercle_puis_fermeture_puis_stockage():
    etapes = [
        "remplissage.preparer_le_couvercle",
        "remplissage.prendre_le_couvercle",
        "remplissage.poser_le_couvercle",
        "remplissage.controler_le_couvercle",
        "remplissage.fermer_le_seau",
        "remplissage.ranger",
    ]
    assert (
        verifier_ordre(
            ["remplissage.prendre_le_seau", *etapes], ["couvercle", "fermeture", "stockage"]
        )
        == []
    )
    # La fermeture avant la pose du couvercle est vue.
    mauvais = ["remplissage.prendre_le_seau", etapes[4], *etapes[:4], etapes[5]]
    probleme = verifier_ordre(mauvais, ["couvercle", "fermeture", "stockage"])
    assert len(probleme) == 1 and "ordre" in probleme[0]


def test_le_lot_de_20_seaux_passe_sans_alarme_avec_couvercle_et_fermeture():
    from vidange.cycle.simulation import jouer_cycle

    with Simulateur(REGLAGES, LISTE, "cycle") as simulateur:
        mode, planning, problemes = jouer_cycle(simulateur)
        monde: MondeCouvercle = simulateur_monde(mode)
    assert planning.probleme == ""
    assert problemes == []
    etapes = [ligne.etape for ligne in planning.lignes]
    assert etapes.count("poser_le_couvercle") == 20 and etapes.count("fermer_le_seau") == 20
    assert "couvercle" in mode.postes_lances and "fermeture" in mode.postes_lances
    assert monde.prises == [1] * 20 and monde.nombre == 4 and monde.tombes == 0


def simulateur_monde(mode):
    return mode.pieces.monde_couvercle
