"""Bocal neuf de semence (tâche 19 quater) : réglages vérifiés au démarrage, geste de la fiche au
simulateur (les 20 étapes, les cas d'erreur 5a, 7, 8, 10, 11, 12, 17, 18), identité du bocal
recopiée au registre avant le dévissage, reprise après une alarme, Mycélium branché, cycle."""

import pytest

from vidange.bocal_neuf.bocal_neuf import (
    A_VERIFIER,
    CAPSULE_RANGEE,
    CAPSULE_TENUE,
    COUVERCLE_TENU,
    RIEN,
)
from vidange.bocal_neuf.simulation import PREFIXE_QR, bocal_neuf_du_simulateur
from vidange.chef import Condition, ErreurEtape, Etape, Module
from vidange.cycle import ModeSeaux
from vidange.cycle.machine import (
    BOCAL_NEUF,
    CARTES_PAS_CONSTRUITES,
    PIECES_DES_POSTES,
    PiecesMachine,
)
from vidange.cycle.simulation import PiecesSimulees, lot_du_simulateur
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.griffe.bras import G
from vidange.prehension.outil import main as outil
from vidange.registre import Registre
from vidange.reglages import charger_reglages
from vidange.remplissage.simulation import remplissage_du_simulateur
from vidange.simulateur import Simulateur
from vidange.stockage import places
from vidange.stockage.stockage import Stockage

from .conftest import DOSSIER_PI
from .test_reglages import erreur_de, remplacer

LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
NEUF = MACHINE.bocal_neuf
assert NEUF is not None
VARIETE = REGLAGES.simulateur.cycle.variete
PLACES = list(places.places_semence(MACHINE))
PREMIERE = PLACES[0]
# Les bocaux de semence posés au départ (simulateur.yaml, cycle → bocal_neuf).
BOCAUX_POSES = REGLAGES.simulateur.cycle.bocal_neuf.bocaux
CAPSULES = NEUF.boites.capsules
COUVERCLES = NEUF.boites.couvercles_perces
QUOI_FAIRE = "regarder, corriger, acquitter"


def sans_recharge(**changements):
    """Les réglages du simulateur, avec ces changements du lot du cycle (Karulium ne recharge
    jamais le stockage en milieu de lot : tâche 45 quater)."""
    cycle = REGLAGES.simulateur.cycle
    cycle = cycle.model_copy(update=changements)
    simule = REGLAGES.simulateur.model_copy(update={"cycle": cycle})
    return REGLAGES.model_copy(update={"simulateur": simule})


class Essai:
    """Ce que rend `jouer` : le planning et tout ce qu'il faut pour regarder ce qui s'est passé."""

    def __init__(self, planning, neuf, monde, stockage, scenario, textes, registre, erreurs):
        self.planning = planning
        self.neuf = neuf
        self.monde = monde
        self.stockage = stockage
        self.scenario = scenario
        self.textes = textes
        self.registre = registre
        self.erreurs = erreurs

    @property
    def inventaire(self):
        return self.stockage.inventaire

    @property
    def probleme(self):
        return self.planning.probleme


def jouer(
    regler=lambda monde, neuf: None, registre=None, corriger=None, variete=VARIETE, reprises=3
):
    """Le geste du bocal neuf seul sur la Préhension simulée (6 bocaux de la variété, boîte des
    capsules vide, 18 couvercles percés). `regler(monde, neuf)` : une panne avant le départ.
    `corriger(monde, neuf)` : ce que fait Karulium après une alarme ; le geste est alors relancé
    (le Go), et reprend à sa phase, au plus `reprises` fois."""
    with Simulateur(sans_recharge(), LISTE, "prehension") as simulateur:
        scenario = remplissage_du_simulateur(simulateur)
        stockage = Stockage(MACHINE, boucle_fermee=lambda: True)
        neuf, monde = bocal_neuf_du_simulateur(simulateur, scenario, stockage, registre=registre)
        prehension = scenario.prehension
        tete = prehension.tete
        textes: list[str] = []
        executer = tete.executer

        def note(pas, cible, poids):
            textes.append(pas.texte)
            executer(pas, cible, poids)

        tete.executer = note
        regler(monde, neuf)
        erreurs: list[str] = []

        def geste():
            while True:
                try:
                    yield from neuf.geste_nouveau_bocal(variete)
                    return
                except ErreurEtape as erreur:
                    erreurs.append(str(erreur))
                    if corriger is None or len(erreurs) > reprises:
                        raise
                    corriger(monde, neuf)

        module = Module(
            nom="bocal_neuf",
            etapes=(
                Etape(
                    "poser_le_bocal",
                    QUOI_FAIRE,
                    action=lambda: prehension.lancer(geste),
                    fin=Condition("geste fini", prehension.geste_fini),
                    delai_max="prehension_geste_max",
                    entree=(tete.pretes,),
                ),
            ),
            surveillances=(tete.surveillance,),
            pauser=prehension.pauser,
            reprendre=prehension.reprendre,
            arreter=prehension.arreter,
        )
        planning = simulateur.jouer([module])
        return Essai(planning, neuf, monde, stockage, scenario, textes, registre, erreurs)


@pytest.fixture
def registre(tmp_path):
    return Registre(tmp_path / "registre.sqlite", tmp_path / "photos")


# ---------------------------------------------------------------- réglages


def test_les_chiffres_de_la_fiche_sont_dans_machine_yaml():
    assert NEUF.exemple
    bocal = NEUF.bocal
    assert bocal.hauteur_m == 0.147
    assert (NEUF.devissage.angle_depart_deg, NEUF.vissage.angle_depart_deg) == (-270, 270)
    assert (NEUF.devissage.rotation_max_deg, NEUF.vissage.rotation_max_deg) == (360, 360)
    assert (NEUF.devissage.premier_essai_deg, NEUF.devissage.pas_essai_deg) == (120, 60)
    assert (NEUF.devissage.decollage_m, NEUF.vissage.levee_m) == (0.003, 0.005)
    assert (NEUF.cale.err_deg, NEUF.cale.duree_s) == (2, 0.2)
    assert NEUF.boites.remontee_m == 0.03 and NEUF.boites.fenetre_m == 0.008
    assert bocal.tolerance_pct == 30
    # ± 30 % de la masse, en newtons.
    assert bocal.tolerance_n(1.0) == pytest.approx(0.3 * G)
    # Le dessus de la capsule vient du stockage, pas d'un chiffre du code.
    assert NEUF.boites.capsules in MACHINE.stockage.boites.places


@pytest.mark.parametrize(
    ("ancien", "nouveau", "message"),
    [
        ("    angle_depart_deg: -270", "    angle_depart_deg: -600", "angle_depart_deg (-600°)"),
        (
            "    rotation_max_deg: 360\n    premier",
            "    rotation_max_deg: 900\n    premier",
            "sort",
        ),
        ("    premier_essai_deg: 120", "    premier_essai_deg: 400", "premier_essai_deg après"),
        ("    capsules: capsules_enlevees", "    capsules: boite_inconnue", "boite_inconnue"),
        (
            "    couvercles_perces: couvercles_perces\n    approche_m",
            "    couvercles_perces: capsules_enlevees\n    approche_m",
            "la même boîte",
        ),
    ],
)
def test_un_reglage_du_bocal_neuf_faux_empeche_de_demarrer(reglages, ancien, nouveau, message):
    remplacer(reglages / "machine.yaml", ancien, nouveau)
    assert message in erreur_de(reglages)


def test_une_vitesse_du_bocal_neuf_qui_manque_empeche_de_demarrer(reglages):
    texte = (reglages / "machine.yaml").read_text(encoding="utf-8")
    ligne = next(ligne for ligne in texte.splitlines() if ligne.strip().startswith("bocal_col:"))
    remplacer(reglages / "machine.yaml", ligne + "\n", "")
    assert "il manque prehension → vitesses → bocal_col" in erreur_de(reglages)


# ---------------------------------------------------------------- le geste, de bout en bout


def test_les_20_etapes_de_la_fiche_au_simulateur(registre):
    essai = jouer(registre=registre)
    assert essai.planning.fini, essai.probleme
    neuf, inventaire = essai.neuf, essai.inventaire
    bocal = neuf.bocal()
    assert (bocal.code, bocal.variete) == (f"{PREFIXE_QR}{PREMIERE}", VARIETE)
    # Le bocal a quitté sa place, la capsule est dans sa boîte, un couvercle percé en moins.
    assert PREMIERE not in inventaire.bocaux and len(inventaire.bocaux) == BOCAUX_POSES - 1
    assert inventaire.boites[CAPSULES] == 1 and inventaire.boites[COUVERCLES] == 17
    prehension = essai.scenario.prehension
    assert prehension.objet is None and neuf.phase == RIEN
    # Les mors se sont ouverts, approchés (Ø 98) puis serrés sur le bocal.
    assert prehension.porte_bocal.gestes[-3:] == ["ouvrir", "approcher", "serrer"]
    # Dans l'ordre de la fiche : dévissage, capsule, couvercle, vissage, bocal porté, pose.
    ordre = [
        "dévissage de la capsule",
        "remontée lente",
        "remontée lente du couvercle percé",
        "vissage du couvercle percé",
        "bocal soulevé de quelques mm",
        "le bocal part",
        "remonter avant le serrage",
    ]
    rang = [essai.textes.index(texte) for texte in ordre]
    assert rang == sorted(rang)
    # La tête repart en +y, hors de la zone du porte-bocal (étape 20).
    pose = prehension.tete.position()
    couloir = MACHINE.prehension.porte_bocal.couloir
    assert (pose.x, pose.y) == pytest.approx((MACHINE.prehension.porte_bocal.x, couloir.depart[1]))


def test_la_capsule_se_devisse_par_segments_avec_un_essai_de_decollage():
    essai = jouer()
    assert essai.planning.fini, essai.probleme
    # La capsule se libère à 200° (simulateur.yaml) : essais à 120°, 180° (elle tient : redescente,
    # appui repris) puis 240° (elle est libre).
    assert essai.textes.count("essai de décollage de la capsule") == 3
    assert essai.textes.count("la capsule tient : redescente") == 2
    assert essai.textes.count("dévissage de la capsule") == 3


def test_le_pi_recopie_l_identite_du_bocal_avant_de_devisser(registre):
    evenements = []
    original = registre.objet

    def objet(sorte, code, **champs):
        evenements.append(("registre", sorte, code, champs))
        return original(sorte, code, **champs)

    registre.objet = objet

    def regler(monde, neuf):
        executer = monde.tete.executer

        def note(pas, cible, poids):
            evenements.append(("mouvement", pas.texte))
            executer(pas, cible, poids)

        monde.tete.executer = note

    essai = jouer(regler, registre=registre)
    assert essai.planning.fini, essai.probleme
    # Le QR part avec la capsule : l'identité est au registre avant le premier mouvement.
    assert evenements[0] == ("registre", "bocal", f"{PREFIXE_QR}{PREMIERE}", {"variete": VARIETE})
    assert evenements[1][0] == "mouvement"
    assert registre.trouver("bocal", f"{PREFIXE_QR}{PREMIERE}")["variete"] == VARIETE


# ---------------------------------------------------------------- cas d'erreur de la fiche


def test_5a_la_capsule_ne_se_libere_jamais(registre):
    def regler(monde, neuf):
        monde.devisse_deg = None

    essai = jouer(regler, registre)
    assert "capsule pas dévissée sur la place semence_0_0" in essai.probleme
    assert "tient encore après 360° de dévissage" in essai.probleme
    # Le bocal reste à sa place, marqué ; la capsule est reposée ; la tête a remonté.
    assert essai.inventaire.bocaux[PREMIERE] == A_VERIFIER
    assert registre.trouver("bocal", f"{PREFIXE_QR}{PREMIERE}")["a_verifier"]
    prehension = essai.scenario.prehension
    assert prehension.objet is None and essai.neuf.phase == RIEN
    assert prehension.tete.position().z == pytest.approx(MACHINE.prehension.haut_z)
    assert essai.inventaire.boites[CAPSULES] == 0
    # Le bocal marqué n'est plus pris : le suivant l'est.
    assert essai.neuf._choisir_la_place(VARIETE) == PLACES[1]


def test_5a_le_moteur_cale_pendant_le_devissage():
    def regler(monde, neuf):
        monde.calage_devissage_deg = 50

    essai = jouer(regler)
    assert "le moteur cale après 50° de dévissage" in essai.probleme
    assert essai.inventaire.bocaux[PREMIERE] == A_VERIFIER


def test_pas_de_bocal_sur_la_place():
    def regler(monde, neuf):
        monde.places_vides.add(PREMIERE)

    essai = jouer(regler)
    assert "pas de contact" in essai.probleme and "pas de bocal" in essai.probleme
    assert essai.scenario.prehension.tete.position().z == pytest.approx(MACHINE.prehension.haut_z)


def test_contact_plus_haut_que_prevu():
    def regler(monde, neuf):
        monde.ecart_capsule_m = 0.05

    essai = jouer(regler)
    assert "plus haut que prévu" in essai.probleme


def test_qr_illisible_le_bocal_n_est_pas_pris(registre):
    def regler(monde, neuf):
        monde.qr_illisibles.add(PREMIERE)

    essai = jouer(regler, registre)
    assert f"QR illisible sur la place {PREMIERE}" in essai.probleme
    assert essai.inventaire.bocaux[PREMIERE] == A_VERIFIER
    # Aucun mouvement : le QR est lu avant tout.
    assert essai.textes == []
    assert essai.neuf._choisir_la_place(VARIETE) == PLACES[1]


def test_qr_d_une_autre_variete(registre):
    registre.objet("bocal", f"{PREFIXE_QR}{PREMIERE}", variete="shiitake")
    essai = jouer(registre=registre)
    assert "est celui d'un bocal « shiitake »" in essai.probleme
    assert essai.inventaire.bocaux[PREMIERE] == A_VERIFIER
    assert essai.textes == []


def test_plus_de_bocal_de_cette_variete():
    essai = jouer(variete="shiitake")
    assert "plus de bocal de semence « shiitake » au stockage" in essai.probleme
    assert essai.textes == []


def test_boite_des_capsules_pleine_ou_boite_des_couvercles_vide():
    def pleine(monde, neuf):
        monde.stockage.inventaire.changer_boite(CAPSULES, places.capacite_boite(MACHINE))

    assert "boîte des capsules est pleine" in jouer(pleine).probleme

    def vide(monde, neuf):
        monde.stockage.inventaire.changer_boite(COUVERCLES, 0)

    assert "boîte des couvercles percés est vide" in jouer(vide).probleme


def test_7_la_capsule_ne_touche_pas_la_boite_et_le_geste_reprend_apres_le_go():
    def regler(monde, neuf):
        monde.capsules_en_trop = 3

    def corriger(monde, neuf):
        # Karulium corrige le nombre de capsules à l'écran : le geste reprend à sa phase.
        assert neuf.phase == CAPSULE_TENUE
        assert neuf.prehension.objet is not None and neuf.prehension.objet.sorte == "capsule"
        monde.capsules_en_trop = 0

    essai = jouer(regler, corriger=corriger)
    assert essai.planning.fini, essai.probleme
    assert len(essai.erreurs) == 1 and "boîte des capsules" in essai.erreurs[0]
    # Le dévissage n'a pas été refait : un seul bocal pris.
    assert essai.textes.count("dévissage de la capsule") == 3
    assert PREMIERE not in essai.inventaire.bocaux
    assert len(essai.inventaire.bocaux) == BOCAUX_POSES - 1
    assert essai.inventaire.boites[CAPSULES] == 1


def test_8_deux_couvercles_colles_reposes_puis_un_seul_pris():
    def regler(monde, neuf):
        monde.colles = 1

    essai = jouer(regler)
    assert essai.planning.fini, essai.probleme
    assert essai.textes.count("couvercles reposés") == 1
    assert essai.inventaire.boites[COUVERCLES] == 17


def test_8_toujours_deux_couvercles_colles():
    def regler(monde, neuf):
        monde.colles = 5

    essai = jouer(regler)
    assert "deux couvercles percés collés" in essai.probleme
    assert essai.neuf.phase == CAPSULE_RANGEE


def test_8_aucun_couvercle_ne_vient():
    def regler(monde, neuf):
        monde.rien_au_levage = 1

    essai = jouer(regler)
    assert "plus de couvercles percés" in essai.probleme
    assert essai.inventaire.boites[COUVERCLES] == 0


def test_8_boite_des_couvercles_pas_a_la_hauteur_prevue():
    def regler(monde, neuf):
        monde.couvercles_en_trop = -4

    essai = jouer(regler)
    assert "boîte des couvercles percés : " in essai.probleme and "attendu à" in essai.probleme


def test_10_le_moteur_ne_cale_pas_le_couvercle_est_remis_dans_sa_boite():
    def regler(monde, neuf):
        monde.filets_sautes = 1

    essai = jouer(regler)
    assert "n'a pas calé après 360° de vissage" in essai.probleme
    assert "il est remis dans sa boîte" in essai.probleme
    assert essai.inventaire.boites[COUVERCLES] == 18
    assert essai.neuf.phase == CAPSULE_RANGEE
    assert essai.inventaire.bocaux[PREMIERE] == VARIETE


def test_10_apres_le_go_un_autre_couvercle_est_pris_et_visse():
    def regler(monde, neuf):
        monde.filets_sautes = 1

    def corriger(monde, neuf):
        assert neuf.phase == CAPSULE_RANGEE

    essai = jouer(regler, corriger=corriger)
    assert essai.planning.fini, essai.probleme
    assert len(essai.erreurs) == 1
    assert essai.inventaire.boites[COUVERCLES] == 17


def test_11_le_palier_ne_pese_que_le_couvercle():
    def regler(monde, neuf):
        monde.couvercle_pas_visse = True

    essai = jouer(regler)
    assert "pas vissé après 2 essais" in essai.probleme
    assert essai.inventaire.bocaux[PREMIERE] == VARIETE


def test_11_le_bocal_n_a_pas_le_poids_attendu():
    def regler(monde, neuf):
        monde.poids_leve_n = 2.0

    essai = jouer(regler)
    assert "le palier pèse 2.00 N avec le bocal soulevé" in essai.probleme
    assert essai.neuf.phase == COUVERCLE_TENU


def test_17_le_palier_ne_revient_pas_a_vide_apres_le_lacher():
    def regler(monde, neuf):
        monde.palier_n = 2.5

    essai = jouer(regler)
    assert "le palier pesé lit 2.50 N après le lâcher du bocal" in essai.probleme


def test_18_le_m8_voit_encore_le_bocal_apres_la_remontee():
    def regler(monde, neuf):
        monde.m8_voit_le_bocal = True

    essai = jouer(regler)
    assert "le M8 voit encore le bocal" in essai.probleme
    assert "pas de serrage" in essai.probleme


def test_le_porte_bocal_n_est_pas_vide_les_mors_s_ouvrent_et_on_appelle_karulium():
    def regler(monde, neuf):
        neuf._reprendre_le_vide = None
        monde.prehension.porte_bocal.etat = "serres"

    essai = jouer(regler)
    assert "le porte-bocal n'est pas vide" in essai.probleme
    assert essai.scenario.prehension.porte_bocal.gestes[-1] == "ouvrir"
    assert essai.textes == []


def test_le_bocal_vide_du_porte_bocal_est_repris_par_la_case_vide():
    def regler(monde, neuf):
        monde.prehension.porte_bocal.etat = "serres"

    essai = jouer(regler)
    assert essai.planning.fini, essai.probleme
    assert essai.monde.vides_repris == 1


def test_la_manivelle_doit_etre_en_bas():
    def regler(monde, neuf):
        monde.prehension._manivelle = lambda: "haut"

    essai = jouer(regler)
    assert "la manivelle du mycélium n'est pas vue en bas" in essai.probleme
    assert essai.textes == []


def test_origine_de_la_rotation_pas_faite():
    class Angle:
        en_rotation = False

        def lire(self, nom):
            return None

    def regler(monde, neuf):
        monde.prehension.garde = Angle()

    essai = jouer(regler)
    assert "origine de la rotation de la tête pas faite" in essai.probleme


def test_sans_lecture_de_l_erreur_du_codeur_rien_ne_bouge():
    def regler(monde, neuf):
        monde.tete.peut_detecter_le_calage = lambda: False

    essai = jouer(regler)
    assert "l'erreur du codeur de la rotation de la tête n'est pas lue" in essai.probleme
    assert "pas de mouvement" in essai.probleme
    assert essai.textes == [] and essai.inventaire.bocaux[PREMIERE] == VARIETE


def test_la_commande_bocal_neuf_attend_cinq_valeurs():
    with pytest.raises(SystemExit):
        outil(["bocal-neuf", "semence_0_0"])


def test_la_tete_doit_etre_libre():
    def regler(monde, neuf):
        monde.prehension.objet = monde.prehension.objet_par_nom("capsule")

    essai = jouer(regler)
    assert "la tête tient déjà un(e) capsule" in essai.probleme


def test_la_reprise_repart_du_debut_si_la_tete_ne_tient_pas_ce_qu_elle_devrait():
    def regler(monde, neuf):
        monde.capsules_en_trop = 3

    def corriger(monde, neuf):
        # La capsule est tombée pendant l'alarme : la phase ne correspond plus à la tête.
        neuf.prehension.objet = None
        monde.capsules_en_trop = 0

    essai = jouer(regler, corriger=corriger, reprises=1)
    assert len(essai.erreurs) == 2
    assert "il repart du début" in essai.erreurs[1]


# ---------------------------------------------------------------- le Mycélium et le cycle


def test_le_mycelium_lance_le_geste_au_changement_de_bocal():
    reglages = sans_recharge(seaux=2, prises_doubles=[])
    with Simulateur(reglages, LISTE, "cycle") as simulateur:
        pieces = PiecesSimulees(simulateur)
        mode = ModeSeaux(reglages, pieces, simulateur.chef)
        planning = simulateur.jouer(mode.modules_du_lot(lot_du_simulateur(simulateur)))
        assert planning.fini, planning.probleme
        monde = pieces.monde_bocal_neuf
        etapes = [ligne.etape for ligne in planning.lignes if ligne.module == "mycelium"]
        assert etapes.count("changer_de_bocal") == 2
        # Un bocal par seau : deux capsules rangées, le QR lu deux fois.
        inventaire = pieces.scenario.plan.magasin.inventaire
        assert inventaire.boites[CAPSULES] == 2
        assert len(monde.lectures_qr) == 2
        assert pieces.scenario.mycelium.plan.bocal.code.startswith(PREFIXE_QR)


def test_le_poste_mycelium_dit_ce_qui_manque_sur_la_machine():
    assert PIECES_DES_POSTES["mycelium"] == ("tete", "agitateur", "porte_bocal")
    pieces = PiecesMachine(None, None, vraie_machine=False)
    assert pieces.manque("mycelium") == CARTES_PAS_CONSTRUITES
    assert "QR du bocal" in BOCAL_NEUF and "codeur" in BOCAL_NEUF
