"""Outil « vidange-vision » : essayer les caméras, la calibration, les QR, les repères ArUco et le
servo de la caméra du dosage.

  vidange-vision fabriquer DOSSIER      mire en damier, repères ArUco et un QR, à imprimer (PNG)
  vidange-vision photo CAMERA FICHIER   une photo de mesure (0,3 s de stabilisation), en JPEG
  vidange-vision calibrer CAMERA        photos de la mire (la bouger entre deux), calibration
  vidange-vision calibrer CAMERA --images DOSSIER   calibration d'après des photos déjà prises
  vidange-vision qr CAMERA              QR lus : code, centre (points), angle
  vidange-vision aruco CAMERA           repères ArUco vus
  vidange-vision plafond                ce que dirait la caméra du plafond (lave-bocal, règle)
  vidange-vision flanc [CAMERA]         caméra du micropore : QR du flanc et trous vus (écart au
                                        centre de l'image, en points)
  vidange-vision piece [CAMERA] [--y Y] le morceau posé sur le trou au centre de l'image : couvert ?
  vidange-vision rouleau FORMAT         angle caméra → rouleau que donne la vision pour ce format
  vidange-vision ecart CODE [DEGRES]    écart attaches de l'anse / QR d'un seau : voir ou noter
  vidange-vision servo bocal|seau|ANGLE caméra du dosage tournée (SANS verrou : voir plus bas)
  ... --image FICHIER                   lire une photo déjà prise au lieu de la caméra
  ... --faux                            images fabriquées au lieu de la caméra (essai de l'outil)

À ne lancer que programme principal arrêté (une seule commande par caméra). La commande
« servo » ne vérifie pas le verrou de la caméra du dosage : avant, mettre l'agitateur au garage
et la griffe et la préhension loin de la boîte (x < 1,10, y < 0,34, z 0,95-1,08).
Procédure complète : pi/systeme/essai-vision.md.
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

from vidange.cameras import Camera, Image
from vidange.cameras.camera import FluxCommande
from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.journal import configurer_journal
from vidange.portique import places_photo
from vidange.registre import DOSSIER_PHOTOS
from vidange.reglages import ErreurReglages, Reglages, charger_reglages
from vidange.vision import fabrique
from vidange.vision.aruco import chercher_reperes
from vidange.vision.calibration import calculer, enregistrer, trouver_damier
from vidange.vision.dosage import FauxServo, ServoPwm
from vidange.vision.inspection import (
    NOM_ECARTS,
    EcartsAttaches,
    angle_camera_rouleau,
    controler_morceau_image,
    lire_flanc,
)
from vidange.vision.photo import ErreurVision, Photographe, photo_depuis_image
from vidange.vision.plafond import (
    CameraPlafond,
    ControleLaveBocal,
    DevinerTravail,
    FausseReconnaissance,
)
from vidange.vision.qr import lire_codes

# Attente de la première image d'une caméra qu'on vient de lancer (s).
DEMARRAGE_S = 10


class SourceFabriquee:
    """Fausse caméra : une scène fabriquée (QR, repère du lave-bocal), mire pour calibrer."""

    def __init__(self, reglages: Reglages) -> None:
        vision = reglages.vision
        self.scene = fabrique.poser(
            fabrique.fond(1280, 720),
            [
                (fabrique.image_qr("S1293", 6), (400, 360), 25),
                (fabrique.image_qr("B327", 6), (850, 300), -10),
                (fabrique.image_aruco(vision.aruco.dictionnaire, vision.aruco.lave_bocal, 120),
                 (1050, 520), 0),
            ],
        )  # fmt: skip
        # Le flanc d'un seau (caméra du micropore) : un QR un peu à droite du centre, deux trous,
        # et un morceau posé sur un troisième trou au centre de l'image.
        self.flanc = fabrique.scene_flanc(
            0.0,
            qr=("S1293", 15.0, 200),
            trous=[(-30.0, 150), (45.0, 560), (0.0, 360)],
            pieces=[(0.0, 360, 60, 50, 2)],
        )
        self.mires = fabrique.vues_de_mire(vision.calibration.colonnes, vision.calibration.lignes)
        self.numero = 0
        self.mire = False

    def derniere(self, nom: str) -> Image:
        self.numero += 1
        image = self.mires[self.numero % len(self.mires)] if self.mire else self.scene
        if nom == "micropore":
            image = self.flanc
        jpeg = cv2.imencode(".jpg", image)[1].tobytes()
        return Image(self.numero, time.monotonic(), datetime.now(), jpeg)


class SourceCamera:
    """La vraie caméra, lancée seule par sa commande de programme.yaml."""

    def __init__(self, reglages: Reglages, video: str) -> None:
        cameras = reglages.programme.cameras
        if video not in cameras.liste:
            raise ErreurVision(f"vidéo « {video} » absente de programme.yaml (cameras → liste)")
        reglage = cameras.liste[video]
        self.camera = Camera(
            video,
            reglage.description,
            lambda: FluxCommande(reglage.commande, lambda texte: print(f"  caméra : {texte}")),
            cameras,
        )
        self.camera.demarrer()
        # Une caméra met quelques secondes à envoyer sa première image.
        fin = time.monotonic() + DEMARRAGE_S
        while self.camera.derniere() is None and time.monotonic() < fin:
            time.sleep(0.1)

    def derniere(self, nom: str) -> Image | None:
        return self.camera.derniere()

    def arreter(self) -> None:
        self.camera.arreter()


def _image(options: argparse.Namespace, photographe: Photographe | None, camera: str):
    if options.image:
        image = cv2.imread(options.image, cv2.IMREAD_COLOR)
        if image is None:
            raise ErreurVision(f"image illisible : {options.image}")
        return image
    assert photographe is not None
    return photographe.mesure(camera).image()


def _fabriquer(reglages: Reglages, dossier: Path) -> None:
    vision = reglages.vision
    dossier.mkdir(parents=True, exist_ok=True)
    c = vision.calibration
    cv2.imwrite(str(dossier / "mire-damier.png"), fabrique.image_damier(c.colonnes, c.lignes, 100))
    print(
        f"mire-damier.png : {c.colonnes} × {c.lignes} coins intérieurs ; imprimer à 100 %, puis "
        f"mesurer une case : elle doit faire {c.case_m * 1000:g} mm (sinon, corriger case_m)"
    )
    a = vision.aruco
    for nom, numero in [("lave-bocal", a.lave_bocal)] + [
        ("plafond", n) for n in a.calibrage_plafond
    ]:
        fichier = f"aruco-{nom}-{numero}.png"
        cv2.imwrite(str(dossier / fichier), fabrique.image_aruco(a.dictionnaire, numero, 400, 80))
        print(f"{fichier} : repère n° {numero} ({a.dictionnaire})")
    print(
        f"  le repère du lave-bocal fait {a.taille_lave_bocal_m * 1000:g} mm de côté (carré noir "
        "seulement, sans la marge blanche)"
    )
    cv2.imwrite(str(dossier / "qr-S1293.png"), fabrique.image_qr("S1293", 20))
    print("qr-S1293.png : un QR d'essai (code S1293)")


def _calibrer(options, reglages: Reglages, photographe, donnees: Path) -> int:
    vision = reglages.vision
    camera = vision.cameras.get(options.camera)
    if camera is None or camera.calibration is None:
        print(f"Caméra « {options.camera} » sans fichier de calibration (vision.yaml)")
        return 1
    c = vision.calibration
    images = []
    if options.images:
        for chemin in sorted(Path(options.images).glob("*.jpg")):
            image = cv2.imread(str(chemin), cv2.IMREAD_COLOR)
            if image is not None:
                images.append(image)
        print(f"{len(images)} photos lues dans {options.images}")
    else:
        if options.faux:
            photographe.cameras.mire = True
        for numero in range(1, c.photos + 1):
            image = photographe.mesure(options.camera).image()
            vu = trouver_damier(image, c.colonnes, c.lignes) is not None
            print(f"photo {numero}/{c.photos} : damier {'trouvé' if vu else 'PAS trouvé'}")
            images.append(image)
            if numero < c.photos and not options.faux:
                time.sleep(c.attente_entre_s)
    calibration = calculer(images, c)
    chemin = donnees / c.dossier / camera.calibration
    enregistrer(calibration, chemin)
    fx, fy = calibration.matrice[0][0], calibration.matrice[1][1]
    print(
        f"Calibration enregistrée : {chemin} (erreur moyenne {calibration.erreur_px:.2f} points, "
        f"focale {fx:.0f} × {fy:.0f} points)"
    )
    return 0


def _plafond(options, reglages: Reglages, photographe) -> int:
    vision = reglages.vision
    if options.image:
        photo = photo_depuis_image("plafond", _image(options, None, "plafond"), time.monotonic())
    else:
        photo = photographe.mesure("plafond")
    # L'outil ne lit pas la position du pont : le garer soi-même au bout opposé (x 2,925).
    places = places_photo(reglages.machine)
    tolerance = reglages.machine.portique.photo_tolerance_m if reglages.machine.portique else 0
    plafond = CameraPlafond(
        vision, photographe, FausseReconnaissance(), lambda: places["fut_poste"], places, tolerance
    )
    vu = plafond.lave_bocal_vu(photo.image())
    print(f"Repère du lave-bocal (n° {vision.aruco.lave_bocal}) : {'VU' if vu else 'pas vu'}")
    verdict, raison = ControleLaveBocal(plafond).verdict(photo)
    print(f"Contrôle du lave-bocal : {verdict} ({raison})")
    proposition = DevinerTravail(plafond).juger(photo)
    print(
        f"Deviner le travail : règle n° {proposition.regle.numero} : {proposition.message} "
        "(la reconnaissance des objets n'est pas encore écrite : doute)"
    )
    return 0


def _inspection(reglages: Reglages):
    inspection = reglages.vision.inspection
    if inspection is None:
        raise ErreurVision("vision.yaml n'a pas de partie « inspection » (caméra du micropore)")
    return inspection


def _flanc(options, reglages: Reglages, photographe) -> int:
    inspection = _inspection(reglages)
    image = _image(options, photographe, options.camera)
    qrs, trous = lire_flanc(image, reglages.vision)
    tolerance = inspection.flanc.centre_tolerance_px
    for qr in qrs:
        centre = "AU CENTRE" if abs(qr.x_px) <= tolerance else "tourner le plateau"
        print(f"QR {qr.code} : {qr.x_px:+.0f} points du centre, à {qr.y_px:.0f} de haut ({centre})")
    for trou in trous:
        centre = "AU CENTRE" if abs(trou.x_px) <= tolerance else "tourner le plateau"
        print(
            f"trou : {trou.x_px:+.0f} points du centre, à {trou.y_px:.0f} de haut, Ø "
            f"{trou.diametre_px:.0f} points ({centre})"
        )
    print(f"{len(qrs)} QR et {len(trous)} trou(s) vus")
    return 0


def _piece(options, reglages: Reglages, photographe) -> int:
    inspection = _inspection(reglages)
    image = _image(options, photographe, options.camera)
    hauteur, largeur = image.shape[:2]
    y = hauteur / 2 if options.y is None else options.y
    verdict = controler_morceau_image(image, (largeur / 2, y), inspection)
    print("Trou COUVERT" if verdict.couvert else f"Trou PAS couvert : {verdict.raison}")
    return 0 if verdict.couvert else 1


def _rouleau(options, reglages: Reglages) -> int:
    inspection = _inspection(reglages)
    micropore = reglages.machine.micropore
    if micropore is None or options.format not in micropore.formats:
        formats = ", ".join(micropore.formats) if micropore else "aucun"
        print(f"format inconnu « {options.format} » (formats : {formats})")
        return 2
    for numero, rangee in enumerate(micropore.formats[options.format].rangees, start=1):
        angle = angle_camera_rouleau(inspection, rangee.rayon_paroi_m)
        print(f"rangée {numero} (rayon {rangee.rayon_paroi_m * 100:g} cm) : {angle:.1f}°")
    return 0


def _ecart(options, donnees: Path) -> int:
    ecarts = EcartsAttaches(donnees / NOM_ECARTS)
    if ecarts.erreur is not None:
        print(f"Erreur : {ecarts.erreur}")
        return 1
    if options.degres is None:
        for code, ecart in sorted(ecarts.tous().items()):
            print(f"{code} : {ecart:.1f}°")
        connu = ecarts.ecart(options.code)
        print(f"{options.code} : " + ("écart pas enregistré" if connu is None else f"{connu:.1f}°"))
        return 0
    ecarts.noter(options.code, options.degres, "karulium")
    print(f"{options.code} : écart noté, {ecarts.ecart(options.code):.1f}°")
    return 0


def _servo(options, reglages: Reglages) -> int:
    reglage = reglages.machine.camera_dosage
    if reglage is None:
        print("Pas de camera_dosage dans machine.yaml")
        return 1
    if options.cible in ("bocal", "seau"):
        angle = reglage.angle_bocal_deg if options.cible == "bocal" else reglage.angle_seau_deg
    else:
        try:
            angle = float(options.cible.replace(",", "."))
        except ValueError:
            print(f"« {options.cible} » : bocal, seau ou un angle en degrés")
            return 1
    servo = FauxServo() if options.faux else ServoPwm(reglage)
    servo.tourner(angle)
    print(f"Caméra du dosage tournée à {angle:g}° (servo : il ne dit pas où il est, regarder)")
    return 0


def lancer() -> None:
    lecteur = argparse.ArgumentParser(prog="vidange-vision", description=__doc__.split("\n")[0])
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument("--donnees", help="dossier des données (défaut : pi/donnees)")
    lecteur.add_argument("--faux", action="store_true", help="images fabriquées, faux servo")
    lecteur.add_argument("--image", help="lire cette photo au lieu de la caméra")
    commandes = lecteur.add_subparsers(dest="commande", required=True)
    commande = commandes.add_parser("fabriquer", help="mire, repères et QR à imprimer")
    commande.add_argument("dossier")
    commande = commandes.add_parser("photo", help="une photo de mesure")
    commande.add_argument("camera")
    commande.add_argument("fichier")
    commande = commandes.add_parser("calibrer", help="calibration d'une caméra (mire en damier)")
    commande.add_argument("camera")
    commande.add_argument("--images", help="dossier de photos de la mire déjà prises (*.jpg)")
    for nom in ("qr", "aruco"):
        commandes.add_parser(nom, help=f"{nom} lus").add_argument("camera")
    commandes.add_parser("plafond", help="ce que dirait la caméra du plafond")
    commande = commandes.add_parser(
        "flanc", help="QR du flanc et trous vus par la caméra du micropore"
    )
    commande.add_argument("camera", nargs="?", default="micropore")
    commande = commandes.add_parser(
        "piece", help="le morceau posé sur le trou au centre est-il couvert ?"
    )
    commande.add_argument("camera", nargs="?", default="micropore")
    commande.add_argument("--y", type=float, help="hauteur du trou dans l'image (points)")
    commande = commandes.add_parser("rouleau", help="angle caméra → rouleau donné par la vision")
    commande.add_argument("format")
    commande = commandes.add_parser("ecart", help="écart attaches de l'anse / QR d'un seau")
    commande.add_argument("code")
    commande.add_argument("degres", nargs="?", type=float, help="l'écart à noter (°)")
    commande = commandes.add_parser("servo", help="tourner la caméra du dosage (sans verrou)")
    commande.add_argument("cible", help="bocal, seau ou un angle (°)")
    options = lecteur.parse_args()

    configurer_journal()
    try:
        reglages = charger_reglages(
            _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
        )
    except ErreurReglages as erreur:
        print(erreur, file=sys.stderr)
        sys.exit(2)
    donnees = _chemin(options.donnees, "VIDANGE_DONNEES", DOSSIER_PI / "donnees")
    if options.commande == "fabriquer":
        _fabriquer(reglages, Path(options.dossier))
        return
    if options.commande == "servo":
        sys.exit(_servo(options, reglages))
    if options.commande == "ecart":
        sys.exit(_ecart(options, donnees))
    if options.commande == "rouleau":
        try:
            sys.exit(_rouleau(options, reglages))
        except ErreurVision as erreur:
            print(f"Erreur : {erreur}", file=sys.stderr)
            sys.exit(1)

    camera = getattr(options, "camera", "plafond")
    source = None
    photographe = None
    try:
        if options.faux:
            source = SourceFabriquee(reglages)
        elif not options.image and not getattr(options, "images", None):
            reglage = reglages.vision.cameras.get(camera)
            video = None if reglage is None else reglage.video
            if video is None:
                raise ErreurVision(f"caméra « {camera} » sans vidéo (vision.yaml → cameras)")
            source = SourceCamera(reglages, video)
        if source is not None:
            photographe = Photographe(
                source, reglages.vision, dossier_photos=donnees / DOSSIER_PHOTOS
            )
        sys.exit(_commande(options, reglages, photographe, donnees))
    except ErreurVision as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        sys.exit(1)
    finally:
        if isinstance(source, SourceCamera):
            source.arreter()


def _commande(options, reglages: Reglages, photographe, donnees: Path) -> int:
    vision = reglages.vision
    if options.commande == "photo":
        photo = photographe.mesure(options.camera)
        Path(options.fichier).write_bytes(photo.jpeg)
        hauteur, largeur = photo.image().shape[:2]
        print(f"Photo enregistrée : {options.fichier} ({largeur} × {hauteur} points)")
        return 0
    if options.commande == "calibrer":
        return _calibrer(options, reglages, photographe, donnees)
    if options.commande == "qr":
        codes = lire_codes(_image(options, photographe, options.camera), vision.qr)
        for code in codes:
            x, y = code.centre
            angle = code.angle_image_deg
            print(f"{code.code} : centre ({x:.0f} ; {y:.0f}) points, angle {angle:.1f}°")
        print(f"{len(codes)} QR lu(s)")
        return 0
    if options.commande == "aruco":
        reperes = chercher_reperes(
            _image(options, photographe, options.camera), vision.aruco.dictionnaire
        )
        for numero, repere in sorted(reperes.items()):
            x, y = repere.centre
            cote = repere.cote_px
            print(f"repère n° {numero} : centre ({x:.0f} ; {y:.0f}), côté {cote:.0f} points")
        print(f"{len(reperes)} repère(s) vu(s) ({vision.aruco.dictionnaire})")
        return 0
    if options.commande == "plafond":
        return _plafond(options, reglages, photographe)
    if options.commande == "flanc":
        return _flanc(options, reglages, photographe)
    if options.commande == "piece":
        return _piece(options, reglages, photographe)
    raise AssertionError(options.commande)
