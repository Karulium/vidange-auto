"""Les cartes de pesée RP2040 + HX711 du bus RS485 des pesées (programme des cartes : pesee/).

- `tour.py` : le Pi interroge les cartes à tour de rôle et donne le poids (TourPesees) ;
- `verification.py` : pesees.yaml et entrees-sorties.yaml vont ensemble ;
- `entete.py` : copie les réglages dans le programme des cartes quand on le fabrique ;
- `outil.py` : l'outil « vidange-pesees » des essais à l'établi.

Rien n'est importé ici : `entete.py` est lancé par la fabrication du programme des cartes, où
seuls pydantic et PyYAML sont installés.
"""
