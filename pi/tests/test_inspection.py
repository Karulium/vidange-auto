"""Vision du micropore (tâche 40 ter) : QR du flanc, trous et morceaux posés, lus sur des images
fabriquées par OpenCV (QR droits, tournés, flous, illisibles, cachés ; trous ; morceau posé,
absent, décalé, de travers, mal coupé), angle caméra → rouleau, branchement au Remplissage."""

import math
import sys
import time

import pytest

from vidange.reglages import charger_reglages
from vidange.vision import fabrique
from vidange.vision.inspection import (
    EcartsAttaches,
    FausseReconnaissanceAttaches,
    VisionInspection,
    angle_camera_rouleau,
    azimut_au_centre,
    controler_morceau_image,
    trouver_trous,
)
from vidange.vision.photo import ErreurVision, photo_depuis_image

from .conftest import DOSSIER_PI

REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
INSPECTION = REGLAGES.vision.inspection
GEOMETRIE = INSPECTION.geometrie
# La caméra vue de l'axe du plateau (fiche : −122°).
AZIMUT = math.degrees(math.atan2(-0.153, -0.095))
CODE = "S1293"
PAS = 10


def proche(a: float, b: float, ecart: float = 1.0) -> bool:
    return abs((a - b + 180) % 360 - 180) <= ecart


class Plateau:
    def __init__(self, angle: float = 0.0) -> None:
        self.a = angle

    def __call__(self) -> float:
        return self.a


class FauxRegard:
    """Les images de la caméra : `fabriquer()` rend celle que verrait la caméra maintenant."""

    def __init__(self, fabriquer, en_panne: bool = False) -> None:
        self.fabriquer = fabriquer
        self.en_panne = en_panne
        self.numero = 0

    def _photo(self):
        if self.en_panne:
            raise ErreurVision("caméra « micropore » : pas d'image depuis 3 s (caméra en panne ?)")
        self.numero += 1
        return photo_depuis_image("micropore", self.fabriquer(), float(self.numero))

    def mesure(self, nom):
        return self._photo()

    def derniere(self, nom):
        return self._photo()


def vision(plateau, fabriquer, **options) -> VisionInspection:
    return VisionInspection(REGLAGES.vision, FauxRegard(fabriquer), plateau, **options)


def tour(vue: VisionInspection, plateau: Plateau, fabriquer, debut=0, fin=360) -> None:
    """Le plateau tourne de `debut` à `fin` (°), une image tous les 10°."""
    for angle in range(debut, fin + 1, PAS):
        plateau.a = angle
        vue.analyser(angle, fabriquer())


# ------------------------------------------------------------------ la géométrie


def test_la_camera_vue_de_l_axe_du_plateau_est_a_moins_122_degres():
    assert azimut_au_centre(GEOMETRIE, 0.12) == pytest.approx(AZIMUT)
    assert -122.5 < AZIMUT < -121.5


def test_angle_camera_rouleau_est_celui_de_l_exemple_du_simulateur():
    # Rouleau à −90°, caméra à −121,8° : le plateau tourne de ≈ 32° (simulateur.yaml : 32).
    assert angle_camera_rouleau(INSPECTION, 0.129) == pytest.approx(31.84, abs=0.02)
    assert angle_camera_rouleau(INSPECTION, 0.102) == pytest.approx(31.84, abs=0.02)


def test_camera_qui_ne_vise_pas_l_axe_angle_camera_rouleau_par_format():
    geometrie = GEOMETRIE.model_copy(update={"cap_deg": 70})
    inspection = INSPECTION.model_copy(update={"geometrie": geometrie})
    petit, grand = azimut_au_centre(geometrie, 0.10), azimut_au_centre(geometrie, 0.14)
    assert petit != pytest.approx(grand)
    # Le point vu est bien sur la paroi du seau, sur le rayon de la caméra.
    for rayon, azimut in ((0.10, petit), (0.14, grand)):
        x, y = rayon * math.cos(math.radians(azimut)), rayon * math.sin(math.radians(azimut))
        px, py = GEOMETRIE.decalage_m
        direction = math.atan2(y - py, x - px)
        assert proche(math.degrees(direction), 70, 0.01)
    assert angle_camera_rouleau(inspection, 0.10) != pytest.approx(
        angle_camera_rouleau(inspection, 0.14)
    )
    # Rayon que la caméra ne peut pas voir (plus petit que l'écart à la ligne visée) : erreur.
    with pytest.raises(ErreurVision, match="ne voit pas la paroi"):
        azimut_au_centre(GEOMETRIE.model_copy(update={"cap_deg": -30}), 0.05)


# ------------------------------------------------------------------ le QR du flanc


def flanc(plateau: Plateau, a_qr: float = 130, inclinaison=0.0, flou=0, cache=False):
    def fabriquer():
        image = fabrique.scene_flanc(
            plateau.a, qr=(CODE, a_qr, 360), qr_inclinaison=inclinaison, case_qr=6
        )
        if cache:
            x = round(640 + 8 * ((a_qr - plateau.a + 180) % 360 - 180))
            image = fabrique.cacher(image, (x - 10, 260), (110, 200))
        return fabrique.flouter(image, flou) if flou else image

    return fabriquer


def lire_apres_un_tour(a_qr=130, ecart=None, **options):
    plateau = Plateau()
    fabriquer = flanc(plateau, a_qr, **options)
    ecarts = EcartsAttaches()
    if ecart is not None:
        ecarts.noter(CODE, ecart, "essai")
    vue = vision(plateau, fabriquer, ecarts=ecarts)
    tour(vue, plateau, fabriquer)
    plateau.a = 360
    return vue.lire_seau(), vue


def test_qr_droit_lu_pendant_le_tour_donne_l_angle_des_oreilles():
    lu, _ = lire_apres_un_tour(130)
    assert lu is not None
    code, oreilles = lu
    assert code == CODE
    # Le QR est au centre à 130° du plateau ; le plateau est maintenant à 360° : le QR a tourné
    # de 230° depuis l'azimut de la caméra. Écart attaches/QR du réglage (0°).
    assert proche(oreilles, AZIMUT + 230, 0.5)


def test_l_ecart_attaches_qr_du_seau_corrige_les_oreilles():
    lu, _ = lire_apres_un_tour(130, ecart=20)
    assert lu is not None and proche(lu[1], AZIMUT + 230 + 20, 0.5)


@pytest.mark.parametrize("inclinaison", [30, -45, 90])
def test_qr_tourne_est_lu_et_donne_le_meme_angle(inclinaison):
    lu, _ = lire_apres_un_tour(200, inclinaison=inclinaison)
    assert lu is not None and lu[0] == CODE
    assert proche(lu[1], AZIMUT + 160, 0.5)


def test_qr_vu_au_debut_et_a_la_fin_du_tour_est_un_seul_qr():
    """Le tour commence quand le QR passe devant la caméra : il y repasse à la fin du tour (deux
    passages, à 360° d'écart). L'angle trouvé est le même, au tour près."""
    lu, _ = lire_apres_un_tour(0)
    assert lu is not None and proche(lu[1], AZIMUT + 360, 0.7)
    lu, _ = lire_apres_un_tour(358)
    assert lu is not None and proche(lu[1], AZIMUT + 2, 0.7)


def test_qr_un_peu_flou_est_lu():
    lu, _ = lire_apres_un_tour(130, flou=2)
    assert lu is not None and proche(lu[1], AZIMUT + 230, 0.7)


def test_qr_trop_flou_n_est_pas_lu():
    lu, _ = lire_apres_un_tour(130, flou=14)
    assert lu is None


def test_qr_a_moitie_cache_n_est_pas_lu():
    lu, _ = lire_apres_un_tour(130, cache=True)
    assert lu is None


def test_pas_de_qr_sur_le_flanc():
    plateau = Plateau()
    fabriquer = lambda: fabrique.scene_flanc(plateau.a)  # noqa: E731
    vue = vision(plateau, fabriquer)
    tour(vue, plateau, fabriquer)
    assert vue.lire_seau() is None


def test_le_sens_de_defilement_dans_l_image_ne_change_rien():
    plateau = Plateau()
    fabriquer = lambda: fabrique.scene_flanc(  # noqa: E731
        plateau.a, qr=(CODE, 130, 360), points_par_degre=-6.0
    )
    vue = vision(plateau, fabriquer)
    tour(vue, plateau, fabriquer)
    plateau.a = 360
    lu = vue.lire_seau()
    assert lu is not None and proche(lu[1], AZIMUT + 230, 0.5)


def test_une_seule_lecture_ne_compte_que_si_le_qr_est_au_centre():
    # Plateau à l'arrêt, QR à 60 points du centre (> centre_tolerance_px) : pas lu.
    plateau = Plateau(100)
    vue = vision(plateau, flanc(plateau, 100 + 60 / 8))
    assert vue.lire_seau() is None
    # QR au centre : lu tout de suite, sans tour.
    plateau = Plateau(100)
    vue = vision(plateau, flanc(plateau, 100 + 10 / 8))
    lu = vue.lire_seau()
    assert lu is not None and proche(lu[1], AZIMUT, 0.5)


def test_deux_qr_a_egalite_aucun_n_est_retenu():
    plateau = Plateau()

    def fabriquer():
        scene = fabrique.scene_flanc(plateau.a, qr=(CODE, 130, 200))
        x = round(640 + 8 * ((130 - plateau.a + 180) % 360 - 180))
        return fabrique.poser(scene, [(fabrique.image_qr("S9999", 6), (x, 520), 0)])

    vue = vision(plateau, fabriquer)
    tour(vue, plateau, fabriquer, 80, 180)
    assert vue.lire_seau() is None


def test_camera_en_panne_ou_angle_du_plateau_inconnu_ne_lit_rien():
    plateau = Plateau(100)
    fabriquer = flanc(plateau, 100)
    vue = VisionInspection(REGLAGES.vision, FauxRegard(fabriquer, en_panne=True), plateau)
    assert vue.lire_seau() is None
    inconnu = VisionInspection(REGLAGES.vision, FauxRegard(fabriquer), lambda: None)
    assert inconnu.lire_seau() is None


# ------------------------------------------------------------------ l'écart attaches / QR


def test_ecarts_gardes_dans_un_fichier_et_relus(tmp_path):
    fichier = tmp_path / "donnees" / "ecarts-attaches.json"
    ecarts = EcartsAttaches(fichier)
    assert ecarts.ecart(CODE) is None
    ecarts.noter(CODE, 100, "karulium")  # 100° et −80° sont la même paire d'oreilles
    relu = EcartsAttaches(fichier)
    assert relu.ecart(CODE) == pytest.approx(-80)
    assert relu.tous() == {CODE: pytest.approx(-80)}
    assert not list(fichier.parent.glob("*.provisoire"))


def test_fichier_des_ecarts_abime(tmp_path):
    fichier = tmp_path / "ecarts-attaches.json"
    fichier.write_text("{pas du json", encoding="utf-8")
    ecarts = EcartsAttaches(fichier)
    assert ecarts.erreur is not None and "illisible" in ecarts.erreur
    assert ecarts.ecart(CODE) is None


def test_les_attaches_vues_au_premier_passage_fixent_l_ecart_du_seau():
    plateau = Plateau()
    fabriquer = flanc(plateau, 130)
    ecarts = EcartsAttaches()
    # Le (faux) détecteur voit une attache à 145° du plateau, le QR passe au centre à 130°.
    vue = vision(plateau, fabriquer, ecarts=ecarts, attaches=FausseReconnaissanceAttaches([145.0]))
    tour(vue, plateau, fabriquer)
    plateau.a = 360
    lu = vue.lire_seau()
    assert ecarts.ecart(CODE) == pytest.approx(15, abs=0.5)
    assert lu is not None and proche(lu[1], AZIMUT + 230 + 15, 0.7)


def test_sans_reconnaissance_des_attaches_c_est_le_reglage_qui_sert():
    lu, _ = lire_apres_un_tour(130)
    assert lu is not None
    oreilles = lu[1]
    defaut = INSPECTION.flanc.ecart_attaches_defaut_deg
    assert proche(oreilles, AZIMUT + 230 + defaut, 0.5)


# ------------------------------------------------------------------ les trous


HAUT = [20, 110, 200, 290]
FOND = [65, 155, 245, 335]


def trous_du_seau(plateau, trous=HAUT, y=200):
    """Une seule rangée de trous dans l'image (la caméra fixe n'en voit qu'une à la fois)."""

    def fabriquer():
        return fabrique.scene_flanc(plateau.a, qr=(CODE, 160, 360), trous=[(a, y) for a in trous])

    return fabriquer


def repere(trous=HAUT, rangee=0, fin=360, y=200, **options):
    plateau = Plateau()
    fabriquer = trous_du_seau(plateau, trous, y)
    vue = vision(plateau, fabriquer, **options)
    vue.commencer_tour = lambda: None  # le tour est joué image par image, sans fil
    tour(vue, plateau, fabriquer, 0, fin)
    return vue.finir_tour(rangee), vue


def assert_angles(lus, attendus, ecart=1.0):
    assert len(lus) == len(attendus), lus
    for lu, attendu in zip(sorted(lus), sorted(attendus), strict=True):
        assert proche(lu, attendu, ecart), (lus, attendus)


def test_les_trous_et_le_qr_sont_repares_au_tour():
    reperage, _ = repere()
    assert reperage is not None and reperage.code == CODE
    assert list(reperage.trous) == [0]
    assert_angles(reperage.trous[0], HAUT)
    assert reperage.diametre_bord_m is None and reperage.attaches_deg == []


def test_chaque_tour_rend_les_trous_de_sa_rangee():
    reperage, _ = repere(FOND, rangee=1)
    assert list(reperage.trous) == [1]
    assert_angles(reperage.trous[1], FOND)


def test_le_plateau_du_reperage_est_la_lentille_moins_la_hauteur_de_la_rangee():
    vue = vision(Plateau(), lambda: fabrique.fond(1280, 720))
    for hauteur in (0.19, 0.07):
        assert vue.plateau_z_repere(hauteur) == GEOMETRIE.objectif_z_m - hauteur


def test_un_trou_cache_est_un_trou_en_moins():
    reperage, _ = repere([20, 110, 290])
    assert_angles(reperage.trous[0], [20, 110, 290])


def test_un_tour_plus_long_que_360_ne_compte_pas_un_trou_deux_fois():
    reperage, _ = repere(fin=420)
    assert_angles(reperage.trous[0], HAUT)


def test_une_rangee_pas_vue_laisse_sa_liste_vide():
    reperage, _ = repere([])
    assert reperage is not None and reperage.trous[0] == []


def test_rien_de_lisible_au_tour_de_reperage():
    plateau = Plateau()
    fabriquer = lambda: fabrique.fond(1280, 720)  # noqa: E731
    vue = vision(plateau, fabriquer)
    tour(vue, plateau, fabriquer)
    assert vue.finir_tour(0) is None


def test_une_tache_qui_n_est_pas_un_trou_est_ignoree():
    image = fabrique.scene_flanc(0.0, trous=[(0.0, 360)])
    # Une tache trop grande, et un petit rectangle : ni l'une ni l'autre n'est un trou.
    image = fabrique.poser(image, [(fabrique.fond(120, 120, 20)[:, :, 0], (300, 200), 0)])
    image[500:520, 900:960] = 30
    trous = trouver_trous(image, INSPECTION, [])
    assert len(trous) == 1 and abs(trous[0].x_px) < 2 and abs(trous[0].y_px - 360) < 2


def test_le_fil_de_la_camera_regarde_pendant_que_le_plateau_tourne():
    plateau = Plateau()
    fabriquer_images = trous_du_seau(plateau)

    class RegardQuiTourne(FauxRegard):
        def derniere(self, nom):
            plateau.a = min(360, plateau.a + PAS)
            return super().derniere(nom)

    vue = VisionInspection(REGLAGES.vision, RegardQuiTourne(fabriquer_images), plateau)
    vue.commencer_tour()
    fin = time.monotonic() + 30
    while plateau.a < 360 and time.monotonic() < fin:
        time.sleep(0.01)
    reperage = vue.finir_tour(0)
    assert reperage is not None and reperage.code == CODE
    assert_angles(reperage.trous[0], HAUT)
    # Arrêté : plus d'image regardée.
    vu = vue.regard.numero
    time.sleep(0.1)
    assert vue.regard.numero == vu


# ------------------------------------------------------------------ le contrôle d'un morceau


def verdict(pieces, trou=(0.0, 360)):
    image = fabrique.scene_flanc(0.0, trous=[trou], pieces=pieces)
    return controler_morceau_image(image, (640, trou[1]), INSPECTION)


def test_morceau_pose_sur_le_trou_est_couvert():
    assert verdict([(0.0, 360, 60, 50, 0)]).couvert
    assert verdict([(0.0, 360, 60, 50, 4)]).couvert
    # Un peu décalé mais le trou reste couvert avec sa marge.
    assert verdict([(1.0, 360, 60, 50, 0)]).couvert


def test_trou_decouvert_sans_morceau():
    resultat = verdict([])
    assert not resultat.couvert and "pas de morceau" in resultat.raison


def test_morceau_decale_qui_laisse_voir_le_trou():
    resultat = verdict([(3.0, 360, 60, 50, 0)])  # 24 points à droite
    assert not resultat.couvert and "décalé" in resultat.raison
    # 30 points plus bas : le trou dépasse en haut du morceau (la raison dite peut varier,
    # le verdict non).
    assert not verdict([(0.0, 390, 60, 50, 0)]).couvert


def test_morceau_de_travers():
    resultat = verdict([(0.0, 360, 60, 50, 25)])
    assert not resultat.couvert and "de travers" in resultat.raison


def test_morceau_mal_coupe():
    court = verdict([(0.0, 360, 40, 50, 0)])
    assert not court.couvert and "mal coupé" in court.raison
    etroit = verdict([(0.0, 360, 60, 30, 0)])
    assert not etroit.couvert and "mal coupé" in etroit.raison


def test_trou_hors_de_l_image():
    image = fabrique.scene_flanc(0.0)
    assert not controler_morceau_image(image, (640, 5000), INSPECTION).couvert


def test_controle_par_la_vision_utilise_la_hauteur_de_la_rangee_reperee():
    reperage, vue = repere(FOND, rangee=1, y=520)
    assert reperage is not None
    plateau = Plateau(155)

    def avec_morceau():
        return fabrique.scene_flanc(
            plateau.a,
            trous=[(a, 520) for a in FOND],
            pieces=[(155, 520, 60, 50, 0)],
        )

    vue.regard.fabriquer = avec_morceau
    assert vue.controler_morceau(1, 155) is True
    # Une rangée pas repérée : le centre de l'image, là, pas de morceau.
    assert vue.controler_morceau(0, 155) is False
    assert vue.dernier_verdict is not None and not vue.dernier_verdict.couvert
    vue.regard.en_panne = True
    assert vue.controler_morceau(1, 155) is None


# ------------------------------------------------------------------ branché au Remplissage


def test_le_remplissage_oriente_l_anse_avec_la_vraie_vision():
    """Le Remplissage joue `orienter_l_anse` avec la vraie vision sur des images fabriquées : le
    QR n'est pas lu à l'arrêt, le plateau fait son tour, le QR est lu, l'anse est orientée à
    45° (modulo 90°) des barres."""
    from vidange.entrees_sorties import charger_entrees_sorties
    from vidange.mycelium import module_mycelium
    from vidange.remplissage.module import module_remplissage
    from vidange.remplissage.simulation import remplissage_du_simulateur
    from vidange.simulateur import Simulateur

    liste = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
    A_QR = 137.0  # angle du QR sur le plateau du seau
    ECART = 12.0
    arrivees = []
    with Simulateur(REGLAGES, liste, "remplissage") as simulation:
        scenario = remplissage_du_simulateur(simulation)
        chariot, remplissage = scenario.chariot, scenario.remplissage

        def angle():
            return chariot.position().a

        def image():
            return fabrique.scene_flanc(angle(), qr=(remplissage.seau.code, A_QR, 360))

        class VisionDeTest(VisionInspection):
            """Le fil de la caméra est remplacé par les images du tour, jouées d'un coup."""

            lectures = 0

            def commencer_lecture(self):
                self._echantillons = []

            def finir_lecture(self):
                pass

            def lire_seau(self):
                type(self).lectures += 1
                if type(self).lectures % 2 == 0:
                    a0 = angle() - 360
                    for pas in range(0, 361, PAS):
                        self.analyser(
                            a0 + pas,
                            fabrique.scene_flanc(a0 + pas, qr=(remplissage.seau.code, A_QR, 360)),
                        )
                return super().lire_seau()

        ecarts = EcartsAttaches()
        for seau in scenario.plan.seaux:
            ecarts.noter(seau.seau, ECART, "essai")
        remplissage.vision = VisionDeTest(REGLAGES.vision, FauxRegard(image), angle, ecarts=ecarts)
        centrer = remplissage.geste_centrer

        def noter_puis_centrer():
            seau = remplissage.seau
            arrivees.append((seau.code, seau.angle_anse))
            return centrer()

        remplissage.geste_centrer = noter_puis_centrer
        planning = simulation.jouer(
            [
                module_remplissage(
                    remplissage, scenario.prehension, scenario.mycelium, scenario.plan
                ),
                module_mycelium(scenario.mycelium),
            ]
        )
    assert planning.fini, planning.probleme
    assert [code for code, _ in arrivees] == ["S0101", "S0102"]
    machine = REGLAGES.machine.remplissage
    voulu = machine.barres_direction_deg + machine.anse_deg
    for _, plateau_final in arrivees:
        # Oreilles de l'anse à l'angle final du plateau : azimut du QR + écart du seau.
        oreilles = AZIMUT + (plateau_final - A_QR) + ECART
        assert abs((voulu - oreilles + 45) % 90 - 45) < 1.0, (plateau_final, oreilles, voulu)


# ------------------------------------------------------------------ l'outil


def lancer_vision(monkeypatch, capsys, *arguments, donnees=None):
    from vidange.vision.outil import lancer

    suite = ["--reglages", str(DOSSIER_PI / "reglages")]
    if donnees is not None:
        suite += ["--donnees", str(donnees)]
    monkeypatch.setattr(sys, "argv", ["vidange-vision", *suite, *arguments])
    with pytest.raises(SystemExit) as sortie:
        lancer()
    return sortie.value.code, capsys.readouterr().out


def test_outil_flanc_et_piece_avec_les_images_fabriquees(monkeypatch, capsys, tmp_path):
    code, sortie = lancer_vision(monkeypatch, capsys, "--faux", "flanc", donnees=tmp_path)
    assert code == 0
    assert "QR S1293" in sortie and "2 trou(s)" in sortie and "tourner le plateau" in sortie
    code, sortie = lancer_vision(
        monkeypatch, capsys, "--faux", "piece", "--y", "360", donnees=tmp_path
    )
    assert code == 0 and "COUVERT" in sortie


def test_outil_ecart_et_rouleau(monkeypatch, capsys, tmp_path):
    code, sortie = lancer_vision(monkeypatch, capsys, "ecart", CODE, "25", donnees=tmp_path)
    assert code == 0 and "25.0°" in sortie
    code, sortie = lancer_vision(monkeypatch, capsys, "ecart", CODE, donnees=tmp_path)
    assert code == 0 and f"{CODE} : 25.0°" in sortie
    code, sortie = lancer_vision(monkeypatch, capsys, "rouleau", "seau_a", donnees=tmp_path)
    assert code == 0 and "31.8°" in sortie
    code, _ = lancer_vision(monkeypatch, capsys, "rouleau", "seau_z", donnees=tmp_path)
    assert code == 2
