"""Accéléromètre du chariot Z (RP2040 + LIS3DH) : ce que le Pi fait pour son programme.

- `entete.py` : copie les réglages de `accelerometre.yaml` dans le programme du RP2040 quand
  on le fabrique (tâche 14).
- `liaison.py` : lit l'état et les chocs par le fil série unique, les note au registre, et
  envoie les réglages au RP2040 (tâche 15). `protocole.py` : les trames ; `faux.py` : un faux
  RP2040 pour les tests ; `outil.py` : l'outil « vidange-accelerometre » des essais à l'établi.

Rien n'est importé ici : `entete.py` est lancé par la fabrication du programme du RP2040, où
seuls pydantic et PyYAML sont installés.
"""
