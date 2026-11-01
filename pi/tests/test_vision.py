"""Vision (tâche 22) : réglages, QR et ArUco sur des images fabriquées, calibration, photos,
caméra du plafond (lave-bocal, 9 règles), caméra du dosage (servo, verrou) et ses branchements."""

from datetime import datetime

import pytest

from vidange.cameras import Image
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.griffe.regles import Contexte as ContexteGriffe
from vidange.griffe.regles import Pose as PoseGriffe
from vidange.griffe.regles import ReglesGriffe
from vidange.lavage.module import module_lavage
from vidange.lavage.simulation import lavage_du_simulateur
from vidange.mycelium import module_mycelium
from vidange.mycelium.simulation import mycelium_du_simulateur
from vidange.portique import places_photo
from vidange.registre import Registre
from vidange.reglages import charger_reglages
from vidange.simulateur import Simulateur
from vidange.vision import fabrique
from vidange.vision.aruco import chercher_reperes
from vidange.vision.calibration import (
    PoseCamera,
    calculer,
    charger,
    enregistrer,
    sans_calibration,
    vers_portique,
)
from vidange.vision.dosage import CameraDosage, FauxServo, impulsion_us
from vidange.vision.photo import (
    ErreurVision,
    Photographe,
    PhotoTropVieille,
    photo_depuis_image,
    verifier_age,
)
from vidange.vision.plafond import (
    BocalVu,
    CameraPlafond,
    ControleLaveBocal,
    DevinerTravail,
    FausseReconnaissance,
    Inventaire,
    SeauVu,
    choisir,
    faits,
)
from vidange.vision.qr import Vue, lire_avec_reprises, lire_codes, lire_vue, marquer_a_verifier

from .conftest import DOSSIER_PI
from .test_reglages import erreur_de, remplacer

REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
VISION = REGLAGES.vision
MACHINE = REGLAGES.machine
LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
DICO = VISION.aruco.dictionnaire
LAVE_BOCAL = VISION.aruco.lave_bocal


def scene(*objets):
    return fabrique.poser(fabrique.fond(800, 600), list(objets))


def qr(code: str):
    return fabrique.image_qr(code, 6)


# ---------------------------------------------------------------- réglages


def test_reglages_de_la_vision_du_depot():
    assert VISION.exemple and VISION.stabilisation_s == 0.3
    assert VISION.cameras["plafond"].position == (1.45, 0.50, 2.35)
    assert VISION.cameras["plafond"].champ_deg == (102, 67)
    assert VISION.plafond.photo_age_max_s == 5 and VISION.plafond.attente_s == 300
    assert [r.numero for r in VISION.plafond.regles] == list(range(1, 10))
    assert VISION.qr.lecture_tete.axes_z == 1.05
    assert VISION.aruco.taille_lave_bocal_m == 0.040
    camera = MACHINE.camera_dosage
    assert camera is not None
    assert (camera.angle_bocal_deg, camera.angle_seau_deg) == (0, 63)
    assert camera.signal in LISTE.signaux and LISTE.signaux[camera.signal].type == "pwm"
    assert impulsion_us(camera, 0) == 500 and impulsion_us(camera, 90) == 1500


def test_regles_du_plafond_verifiees(reglages):
    vision = reglages / "vision.yaml"
    remplacer(vision, "    - numero: 2\n", "    - numero: 3\n")
    remplacer(vision, "      travail: attendre\n", "      si: [doute]\n      travail: attendre\n")
    erreur = erreur_de(reglages)
    assert "la règle n° 3 est à la place n° 2" in erreur
    assert "la dernière (n° 9) doit être sans condition" in erreur
    remplacer(vision, "    - numero: 3\n", "    - numero: 2\n")
    remplacer(vision, "      si: [doute]\n      travail: attendre\n", "      travail: attendre\n")
    remplacer(vision, "si: [bocaux_sales, lave_bocal_pose]", "si: [bocaux_sale]")
    assert "condition inconnue bocaux_sale" in erreur_de(reglages)


def test_cameras_et_reperes_verifies(reglages):
    vision = reglages / "vision.yaml"
    remplacer(vision, "    video: dosage\n", "    video: dosage_2\n")
    assert "vision.yaml, cameras → dosage : vidéo « dosage_2 » absente de programme.yaml" in (
        erreur_de(reglages)
    )
    remplacer(vision, "    video: dosage_2\n", "    video: dosage\n")
    remplacer(vision, "calibrage_plafond: [0, 1, 2, 3]", "calibrage_plafond: [7, 60]")
    erreur = erreur_de(reglages)
    assert "un numéro de repère est pris deux fois" in erreur
    assert "repère n° 60 : le dictionnaire DICT_4X4_50 va de 0 à 49" in erreur


def test_servo_verifie(reglages):
    remplacer(reglages / "machine.yaml", "angle_seau_deg: 63", "angle_seau_deg: 200")
    assert "angle_seau_deg (200°) hors de impulsion → angles_deg" in erreur_de(reglages)


# ---------------------------------------------------------------- QR


def test_qr_droits_et_tournes_avec_leur_angle():
    for angle in (0, 30, -75, 135, 180):
        image = scene((qr("S1293"), (300, 300), angle), (qr("B327"), (620, 250), 10))
        codes = {c.code: c for c in lire_codes(image, VISION.qr)}
        assert set(codes) == {"S1293", "B327"}
        ecart = (codes["S1293"].angle_image_deg - angle + 180) % 360 - 180
        assert abs(ecart) < 2, (angle, codes["S1293"].angle_image_deg)
        assert codes["S1293"].centre == pytest.approx((300, 300), abs=3)


def test_qr_flou_lu_tres_flou_illisible():
    assert [
        c.code
        for c in lire_codes(fabrique.flouter(scene((qr("S12"), (300, 300), 20)), 3), VISION.qr)
    ] == ["S12"]
    assert lire_codes(fabrique.flouter(scene((qr("S12"), (300, 300), 20)), 10), VISION.qr) == []
    assert lire_codes(fabrique.fond(800, 600), VISION.qr) == []


def test_qr_d_une_autre_forme_ignore():
    image = scene((qr("bonjour"), (300, 300), 0), (qr("B4"), (600, 300), 0))
    assert [c.code for c in lire_codes(image, VISION.qr)] == ["B4"]


def test_place_et_angle_du_qr_dans_le_repere_du_portique():
    # 90° de champ sur 800 points : focale 400 points. Objectif à 1 m au-dessus du plan.
    calibration = sans_calibration((90, 73.74), (800, 600))
    assert calibration.matrice[0][0] == pytest.approx(400)
    image = scene((qr("S1"), (600, 300), 30))
    pose = PoseCamera(1.0, 2.0, 1.5, 0)
    (code,) = lire_vue(Vue(image, calibration, pose, z_plan=0.5), VISION.qr)
    # 200 points à droite = 0,5 m en +x ; angle à l'écran 30° = 30° dans le portique.
    assert code.position == pytest.approx((1.5, 2.0), abs=0.01)
    assert code.angle_deg == pytest.approx(30 + VISION.qr.angle_objet_deg, abs=2)
    # Caméra tournée de 90° : la droite de l'image est +y, le bas de l'image est +x.
    (code,) = lire_vue(Vue(image, calibration, PoseCamera(1.0, 2.0, 1.5, 90), 0.5), VISION.qr)
    assert code.position == pytest.approx((1.0, 2.5), abs=0.01)
    assert code.angle_deg == pytest.approx(120, abs=2)
    assert vers_portique([(400, 450)], calibration, pose, 0.5)[0] == pytest.approx((1.0, 1.625))


def test_qr_illisible_deuxieme_tour_puis_secours():
    flou = fabrique.flouter(scene((qr("B327"), (300, 300), 0)), 10)
    net = scene((qr("B327"), (300, 300), 0))
    demandes = []

    def photographier(images):
        def prendre(hauteur):
            demandes.append(hauteur)
            return Vue(images[len(demandes) - 1])

        return prendre

    lecture = lire_avec_reprises(photographier([flou, net, net]), VISION.qr)
    assert lecture.complete and lecture.photos == 2 and demandes == ["normale", "normale"]
    demandes.clear()
    lecture = lire_avec_reprises(photographier([flou, flou, net]), VISION.qr)
    assert lecture.complete and demandes == ["normale", "normale", "secours"]
    demandes.clear()
    lecture = lire_avec_reprises(photographier([flou, flou, flou]), VISION.qr)
    assert not lecture.complete and lecture.codes == [] and lecture.photos == 3


def test_paquet_de_qr_complete_d_une_photo_a_l_autre():
    premiere = scene((qr("S1"), (200, 300), 0), (qr("S2"), (600, 300), 0))
    deuxieme = scene((qr("S3"), (400, 300), 0))
    images = iter([premiere, deuxieme])
    lecture = lire_avec_reprises(lambda hauteur: Vue(next(images)), VISION.qr, attendus=3)
    assert lecture.complete and sorted(c.code for c in lecture.codes) == ["S1", "S2", "S3"]


def test_objet_marque_a_verifier_au_registre(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    marquer_a_verifier(registre, "bocal", "B327", "QR illisible")
    assert registre.trouver("bocal", "B327")["a_verifier"] == "QR illisible"


# ---------------------------------------------------------------- ArUco


def test_repere_du_lave_bocal_vu_absent_cache():
    repere = fabrique.image_aruco(DICO, LAVE_BOCAL, 120)
    vue = scene((repere, (400, 300), 25))
    assert set(chercher_reperes(vue, DICO)) == {LAVE_BOCAL}
    assert chercher_reperes(scene(), DICO) == {}
    assert chercher_reperes(fabrique.cacher(vue, (330, 230), (80, 140)), DICO) == {}


# ---------------------------------------------------------------- calibration


def test_calibration_retrouve_la_focale(tmp_path):
    vues = fabrique.vues_de_mire(VISION.calibration.colonnes, VISION.calibration.lignes)
    calibration = calculer(vues, VISION.calibration)
    assert calibration.matrice[0][0] == pytest.approx(800, rel=0.01)
    assert calibration.erreur_px < VISION.calibration.erreur_max_px
    enregistrer(calibration, tmp_path / "plafond.json")
    assert charger(tmp_path / "plafond.json") == calibration
    moitie = calibration.a_la_taille((640, 360))
    assert moitie.matrice[0][0] == pytest.approx(calibration.matrice[0][0] / 2)


def test_calibration_refusee_sans_assez_de_damiers():
    vues = [fabrique.fond(1280, 720)] * 12
    with pytest.raises(ErreurVision, match="damier trouvé sur 0 photos sur 12"):
        calculer(vues, VISION.calibration)


# ---------------------------------------------------------------- photos


class Horloge:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t

    def attendre(self, duree: float) -> None:
        self.t += duree


class SourceEssai:
    """Fausse vidéo : une image neuve à chaque lecture (ou figée)."""

    def __init__(self, horloge: Horloge, image=None) -> None:
        self.horloge = horloge
        self.figee = False
        self.numero = 0
        self.image = image if image is not None else scene((qr("S1293"), (400, 300), 0))
        self.vieille = Image(0, 0.0, datetime.now(), photo_depuis_image("x", self.image, 0).jpeg)

    def derniere(self, nom: str):
        if self.figee:
            return self.vieille
        self.numero += 1
        jpeg = photo_depuis_image(nom, self.image, 0).jpeg
        return Image(self.numero, self.horloge(), datetime.now(), jpeg)


def photographe(tmp_path=None, image=None, registre=None):
    horloge = Horloge()
    source = SourceEssai(horloge, image)
    dossier = None if tmp_path is None else tmp_path / "photos"
    return (
        Photographe(source, VISION, registre, dossier, horloge, horloge.attendre),
        source,
        horloge,
    )


def test_photo_de_mesure_apres_la_stabilisation():
    p, source, horloge = photographe()
    photo = p.mesure("plafond")
    assert photo.heure >= 100.3 and photo.camera == "plafond"
    assert [c.code for c in lire_codes(photo.image(), VISION.qr)] == ["S1293"]
    # Vidéo figée : pas de photo prise pendant un mouvement, erreur après delai_photo_s.
    source.figee = True
    with pytest.raises(ErreurVision, match="pas d'image depuis 3 s"):
        p.mesure("plafond")
    with pytest.raises(ErreurVision, match="sans vidéo"):
        p.mesure("micropore")


def test_photo_trop_vieille_refusee():
    p, _, horloge = photographe()
    photo = p.mesure("plafond")
    verifier_age(photo, 5, horloge)
    horloge.t += 5.1
    with pytest.raises(PhotoTropVieille, match="trop vieille"):
        verifier_age(photo, 5, horloge)


def test_photo_gardee_et_notee_au_registre(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    p, _, _ = photographe(registre=registre)
    chemin = p.enregistrer(p.mesure("dosage"), "essai", seau="S1293")
    assert chemin is not None and chemin.is_file()
    (ligne,) = registre.lire("SELECT camera, remarque, seau_id FROM photos")
    assert (ligne["camera"], ligne["remarque"]) == ("dosage", "essai")
    assert ligne["seau_id"] == registre.trouver("seau", "S1293")["id"]


# ---------------------------------------------------------------- plafond : les 9 règles


def regle(inventaire, lave_bocal_vu=False) -> int:
    return choisir(VISION.plafond.regles, faits(inventaire, lave_bocal_vu)).numero


PLEIN, PLEIN_MAIS = "plein_substrat", "plein_mais"
BOCAL_VIDE, BOCAL_SALE = BocalVu(vide=True, propre=True), BocalVu(vide=True, propre=False)
SEAU_VIDE, SEAU_SALE = SeauVu(plein=False, propre=True), SeauVu(plein=False, propre=False)


def test_chacune_des_9_regles():
    assert regle(Inventaire(inconnus=("caisse",))) == 1
    assert regle(Inventaire(mal_places=("seau sur le trajet du pont",))) == 1
    assert regle(Inventaire(fut_poste=PLEIN_MAIS, bocaux=(BOCAL_VIDE,))) == 2
    seaux = Inventaire(fut_poste=PLEIN, seaux=(SEAU_VIDE,), bocal_semence_pret=True)
    assert regle(seaux) == 3
    assert regle(Inventaire(fut_poste=PLEIN)) == 4
    assert regle(Inventaire(bocaux=(BOCAL_SALE,), fut_lavage="lave_bocal"), True) == 5
    assert regle(Inventaire(bocaux=(BOCAL_SALE,), fut_lavage="vide")) == 6
    assert regle(Inventaire(seaux=(SEAU_SALE,), fut_lavage="vide")) == 7
    assert regle(Inventaire(couvercles_sales=3, fut_lavage="vide")) == 7
    assert regle(Inventaire(seaux=(SEAU_SALE,), fut_lavage="lave_bocal"), True) == 8
    assert regle(Inventaire(fut_poste="vide", seaux=(SEAU_VIDE,), places_libres=4)) == 9


def test_ordre_des_regles_la_premiere_gagne():
    # Doute ou objet inconnu : avant tout le reste.
    tout = Inventaire(fut_poste=PLEIN_MAIS, bocaux=(BOCAL_VIDE, BOCAL_SALE), inconnus=("sac",))
    assert regle(tout) == 1
    assert regle(Inventaire(sur=False, fut_poste=PLEIN_MAIS, bocaux=(BOCAL_VIDE,))) == 1
    # Remplir les bocaux passe avant laver les bocaux sales.
    assert regle(Inventaire(fut_poste=PLEIN_MAIS, bocaux=(BOCAL_VIDE, BOCAL_SALE))) == 2
    # Bocaux vides et propres : pas de seaux (règle 3), même avec un fût de substrat.
    sans_semence = Inventaire(fut_poste=PLEIN, seaux=(SEAU_VIDE,))
    assert regle(sans_semence) == 4
    # Fût plein : « rien à remplir » passe avant les lavages.
    assert regle(Inventaire(fut_poste=PLEIN, seaux=(SEAU_SALE,), fut_lavage="vide")) == 4
    # Bocaux sales (5, 6) passent avant seaux sales (7, 8).
    assert regle(Inventaire(bocaux=(BOCAL_SALE,), seaux=(SEAU_SALE,), fut_lavage="vide")) == 6


def test_sans_reconnaissance_ou_en_desaccord_c_est_le_doute():
    assert regle(None) == 1
    # Le repère du lave-bocal vu, la reconnaissance dit le fût vide : doute.
    assert regle(Inventaire(bocaux=(BOCAL_SALE,), fut_lavage="vide"), lave_bocal_vu=True) == 1
    assert faits(None, True)["lave_bocal_pose"]


# ---------------------------------------------------------------- plafond : photos


def camera_plafond(image, inventaire=None, pont=2.495, controle=True, tmp_path=None):
    p, source, horloge = photographe(tmp_path, image)
    vision = VISION
    if controle != VISION.plafond.controle_lave_bocal:
        plafond = VISION.plafond.model_copy(update={"controle_lave_bocal": controle})
        vision = VISION.model_copy(update={"plafond": plafond})
    position = [pont]
    portique = REGLAGES.machine.portique
    camera = CameraPlafond(
        vision,
        p,
        FausseReconnaissance(inventaire),
        lambda: position[0],
        places_photo(REGLAGES.machine),
        portique.photo_tolerance_m,
        horloge,
    )
    return camera, position, horloge


def test_photo_du_plafond_pont_au_bout_oppose():
    # Fût et poste : pont à x 2,495 ; stockage : pont à x 0,233 (Portique, 01/11), à 5 mm près.
    camera, position, _ = camera_plafond(scene(), Inventaire())
    assert camera.refus_photo("fut_poste") is None
    assert "il faut x 0.233 m pour photographier « stockage »" in camera.refus_photo("stockage")
    position[0] = 0.236
    assert camera.refus_photo("stockage") is None
    assert "pont pas garé" in camera.refus_photo()
    position[0] = 2.489
    assert "pont pas garé" in camera.refus_photo("fut_poste")


LAVE_BOCAL_VU = scene((fabrique.image_aruco(DICO, LAVE_BOCAL, 120), (400, 300), 10))


def test_deviner_le_travail_propose_et_garde_la_photo_des_alertes(tmp_path):
    inventaire = Inventaire(bocaux=(BOCAL_SALE,), fut_lavage="lave_bocal")
    camera, position, _ = camera_plafond(LAVE_BOCAL_VU, inventaire, tmp_path=tmp_path)
    deviner = DevinerTravail(camera)
    proposition = deviner.regarder()
    assert (proposition.regle.numero, proposition.sorte) == (5, "proposer")
    assert proposition.travail == "laver_les_bocaux" and proposition.chemin is None
    # Rien de sûr : alerte, photo gardée.
    camera.reconnaissance = FausseReconnaissance(None)
    proposition = deviner.regarder()
    assert proposition.sorte == "alerte" and proposition.chemin.is_file()
    # Rien à faire : nouvelle photo dans 5 min.
    camera.reconnaissance = FausseReconnaissance(Inventaire())
    assert deviner.regarder().prochaine_photo_s == 300
    # Pont pas garé : pas de photo.
    position[0] = 1.2
    with pytest.raises(ErreurVision, match="pont pas garé"):
        deviner.regarder()
    position[0] = None
    with pytest.raises(ErreurVision, match="position du pont inconnue"):
        deviner.regarder()


def test_deviner_refuse_une_photo_trop_vieille():
    camera, _, horloge = camera_plafond(LAVE_BOCAL_VU, Inventaire())
    photo = camera.photo()
    horloge.t += 6
    with pytest.raises(PhotoTropVieille):
        DevinerTravail(camera).juger(photo)


def test_controle_du_lave_bocal():
    alertes = []
    vide = Inventaire(fut_lavage="vide")
    # Fût vu vide, écran d'accord : seaux permis.
    camera, position, _ = camera_plafond(scene(), vide)
    assert ControleLaveBocal(camera).refus(ecran_pose=False) is None
    # Fût vu vide mais l'écran dit le lave-bocal posé : doute.
    assert "l'écran dit le lave-bocal posé" in ControleLaveBocal(camera).refus(ecran_pose=True)
    # Repère vu : lave-bocal posé, seau, noyau et couronne interdits.
    camera, _, _ = camera_plafond(LAVE_BOCAL_VU, vide)
    assert "lave-bocal vu" in ControleLaveBocal(camera).refus(ecran_pose=True)
    assert "l'écran le dit enlevé" in ControleLaveBocal(camera).refus(ecran_pose=False)
    # Repère caché, reconnaissance pas sûre : doute, alerte avec la photo.
    cache = fabrique.cacher(LAVE_BOCAL_VU, (330, 230), (80, 140))
    camera, position, _ = camera_plafond(cache, None)
    controle = ControleLaveBocal(camera, alertes.append)
    refus = controle.refus(ecran_pose=False)
    assert "doute" in refus and "pas vu clairement" in refus and alertes == [refus]
    # « Vérifié » : le geste suivant passe, une seule fois.
    controle.marquer_verifie()
    assert controle.refus(ecran_pose=False) is None
    assert controle.refus(ecran_pose=False) is not None
    # Pont pas garé : doute.
    position[0] = 0.5
    assert "pont pas garé" in controle.refus(ecran_pose=False)
    # Contrôle pas actif (réglage du dépôt tant que la reconnaissance n'existe pas).
    camera, _, _ = camera_plafond(cache, None, controle=False)
    assert ControleLaveBocal(camera).refus(ecran_pose=False) is None


def test_lavage_refuse_si_la_camera_du_plafond_doute():
    def regler(lavage):
        lavage._controle_plafond = lambda pose: "caméra du plafond, doute : buée"

    with Simulateur(REGLAGES, LISTE, "lavage") as simulation:
        lavage = lavage_du_simulateur(simulation)
        regler(lavage)
        planning = simulation.jouer([module_lavage(lavage, REGLAGES.simulateur.lavage.seaux)])
    assert not planning.fini and "buée" in planning.probleme


# ---------------------------------------------------------------- caméra du dosage


class Verrous:
    def __init__(self) -> None:
        self.agitateur = self.griffe = self.prehension = True


def camera_dosage(tmp_path, registre=None, attendre=lambda s: None):
    p, source, horloge = photographe(tmp_path, registre=registre)
    servo, verrous = FauxServo(), Verrous()
    camera = CameraDosage(
        MACHINE,
        p,
        servo,
        lambda: verrous.agitateur,
        lambda: verrous.griffe,
        lambda: verrous.prehension,
        attendre=attendre,
        en_fond=False,
    )
    return camera, servo, verrous


def test_photo_du_seau_apres_la_dose_notee_avec_sa_dose(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    pivote_pendant = []
    camera, servo, _ = camera_dosage(tmp_path, registre, lambda s: pivote_pendant.append(0))
    assert camera.pivote()  # position inconnue avant d'être rangée
    assert camera.ranger() and not camera.pivote() and servo.angles == [0]
    camera.commencer_photo_seau("S1293", 2, "B327", 151.6)
    assert camera.photo_seau_finie() and not camera.pivote()
    assert servo.angles == [0, 63, 0] and camera.photos_du_seau == 1
    (ligne,) = registre.lire("SELECT camera, remarque, seau_id, bocal_id FROM photos")
    assert ligne["camera"] == "dosage"
    assert ligne["remarque"] == "seau S1293, couche 2 : 152 g de mycélium du bocal B327"
    assert ligne["bocal_id"] == registre.trouver("bocal", "B327")["id"]


def test_camera_du_dosage_ne_pivote_que_tout_le_monde_hors_de_la_boite(tmp_path):
    camera, servo, verrous = camera_dosage(tmp_path)
    for nom, texte in (
        ("agitateur", "agitateur du mycélium pas garé"),
        ("griffe", "griffe dans la boîte"),
        ("prehension", "préhension dans la boîte"),
    ):
        setattr(verrous, nom, False)
        assert texte in camera.refus_pivot()
        assert not camera.ranger()
        camera.photo_seau("S1", 1, "B1", 100)
        assert servo.angles == [] and camera.photos_du_seau == 0
        setattr(verrous, nom, True)
    assert camera.refus_pivot() is None


def test_servo_en_panne_la_camera_reste_dite_pivotee(tmp_path):
    camera, servo, _ = camera_dosage(tmp_path)
    assert camera.ranger()
    servo.en_panne = True
    camera.photo_seau("S1", 1, "B1", 100)
    assert camera.pivote() and camera.photos_du_seau == 0


def test_photo_d_alerte_du_dosage(tmp_path):
    camera, servo, _ = camera_dosage(tmp_path)
    camera.photo("saut de poids pendant l'agitation")
    assert servo.angles == []
    assert len(list((tmp_path / "photos").rglob("*-dosage.jpg"))) == 1


def test_griffe_et_camera_du_dosage():
    regles = ReglesGriffe(MACHINE)
    g = MACHINE.griffe
    assert g is not None
    # Au-dessus du seau du remplissage, bas de la tête sous le haut de la boîte : dedans.
    bas = 1.0 + g.bas_godet_sous_axes
    au_seau = PoseGriffe(0.925, 0.40, bas, 0, 0)
    assert regles.dans_boite_camera_dosage(au_seau.avec(y=0.30))
    # Au fût (y 0,57), ou tête au-dessus de 1,08 : dehors.
    assert not regles.dans_boite_camera_dosage(PoseGriffe(0.29, 0.57, bas, 0, 0))
    assert not regles.dans_boite_camera_dosage(au_seau.avec(y=0.30, z=1.09 + g.bas_godet_sous_axes))
    # Caméra qui pivote : la tête n'entre pas dans la boîte.
    dedans = au_seau.avec(y=0.30)
    refus = regles.refus_pose(dedans, ContexteGriffe(camera_dosage_pivote=True))
    assert refus is not None and "la caméra du dosage pivote" in refus
    assert "caméra du dosage" not in (regles.refus_pose(dedans, ContexteGriffe()) or "")


def test_mycelium_photographie_le_seau_apres_chaque_dose():
    class FausseCamera:
        def __init__(self) -> None:
            self.photos = []

        def commencer_photo_seau(self, seau, couche, bocal, grammes, cycle=None):
            self.photos.append((seau, couche, bocal, round(grammes)))

        def photo_seau_finie(self):
            return True

    camera = FausseCamera()
    with Simulateur(REGLAGES, LISTE, "dosage_mycelium") as simu:
        mycelium = mycelium_du_simulateur(simu, camera=camera)
        planning = simu.jouer([module_mycelium(mycelium)])
    assert planning.fini, planning.probleme
    assert [(s, c, b) for s, c, b, _ in camera.photos] == [
        (d.seau, d.couche, d.bocal) for d in mycelium.doses
    ]
    assert [g for *_, g in camera.photos] == [round(d.kg * 1000) for d in mycelium.doses]
    etapes = [ligne.etape for ligne in planning.lignes]
    assert etapes.count("photographier_le_seau") == len(mycelium.doses)
