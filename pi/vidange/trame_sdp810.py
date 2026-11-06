"""Trames du capteur de pression différentielle Sensirion SDP810-125Pa (bus I2C).

ATTENTION : écrit de mémoire d'après la fiche technique de Sensirion (famille SDP8xx), sans la
notice sous les yeux. Tous les nombres de ce fichier sont À VÉRIFIER sur la notice avant le premier
essai (voir pi/systeme/essai-capteurs-purge.md). Ce fichier ne contient que ce qui est fixé par la
puce ; ce qui dépend de la machine (adresse, sens du capteur) est dans `docs/entrees-sorties.yaml`.

- Mesure continue : on écrit la commande de démarrage (2 octets), puis on lit 9 octets à volonté :
    pression (2 octets, signée) + somme, température (2) + somme, facteur d'échelle (2) + somme.
  La pression en Pa = nombre signé ÷ facteur d'échelle (le capteur donne son propre facteur).
- Somme de contrôle : CRC-8, polynôme 0x31, départ 0xFF, sur chaque paire d'octets (comme le SHT31).
"""

# Adresse I2C d'usine du SDP810 (0x25) : c'est `adresse` dans docs/entrees-sorties.yaml.
# Démarrage de la mesure continue de la pression différentielle, moyennée entre deux lectures.
COMMANDE_DEMARRER = bytes([0x36, 0x15])
COMMANDE_ARRETER = bytes([0x3F, 0xF9])
# Temps à laisser au capteur après la commande de démarrage avant la 1re lecture (s).
ATTENTE_DEMARRAGE_S = 0.02
LONGUEUR_REPONSE = 9
# Temps à laisser entre la commande d'arrêt et celle de démarrage (s).
ATTENTE_ARRET_S = 0.002
