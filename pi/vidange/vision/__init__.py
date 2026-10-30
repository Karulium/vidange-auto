"""Vision (tâche 22) : photos de mesure, calibration, QR, repères ArUco, caméra du dosage sur
son servo, caméra du plafond (contrôle du lave-bocal, deviner le travail).

OpenCV et numpy seulement. Réglages : pi/reglages/vision.yaml (et machine.yaml → camera_dosage).
Les analyses qui demandent des photos réelles (bocal « bon / douteux », anse levée, repère et
bac des couvercles, reconnaissance des objets du plafond) gardent leur faux : tâche 22 ter.
"""

from vidange.vision.photo import ErreurVision, Photo, Photographe, PhotoTropVieille

__all__ = ["ErreurVision", "Photo", "PhotoTropVieille", "Photographe"]
