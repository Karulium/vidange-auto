"""Accéléromètre du chariot Z (RP2040 + LIS3DH) : ce que le Pi fait pour son programme.

- `entete.py` : copie les réglages de `accelerometre.yaml` dans le programme du RP2040 quand
  on le fabrique (tâche 14).
- `liaison.py` : lit l'état et les chocs par le fil série unique, les note au registre, et
  envoie les réglages au RP2040 (tâche 15). `protocole.py` : les trames ; `faux.py` : un faux
  RP2040 pour les tests ; `outil.py` : l'outil « vidange-accelerometre » des essais à l'établi.
- `chargeur.py` : met le programme du RP2040 à jour par ce même fil, grâce à son chargeur
  (tâche 16) ; `fichier_programme.py` : le fichier du programme (fiche et contrôle), et la
  fabrication de accelerometre.bin et accelerometre-complet.uf2.

Rien n'est importé ici : `entete.py` et `fichier_programme.py` sont lancés par la fabrication du
programme du RP2040, où seuls pydantic et PyYAML sont installés.
"""
