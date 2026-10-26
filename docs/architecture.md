# Architecture du logiciel

## Le matériel de commande

| Carte | Rôle | Ce qu'on écrit |
|---|---|---|
| Raspberry Pi 5 8 Go, SSD NVMe 1 To | Le chef : enchaîne les étapes, vision, registre, écrans, liens | Python (`pi/`) |
| 4 cartes ESP32 FluidNC 6 axes, pilotes externes | Axes : portique, chariot, mycélium/lavage, préhension. Reliées au Pi par USB série | Réglages seulement (`fluidnc/`) |
| 1 carte ESP32 (boîte du spray) | Pompes et flacons du spray | Petit programme C++ (`spray/`), plus tard |
| RP2040 + LIS3DH | Détection des chocs sur le chariot Z | Petit programme (`accelerometre/`) |
| Écran Nextion 4,3" (porte de l'armoire) | Tableau de bord sur place, relié au Pi par UART (GPIO 4/5) | Pages Nextion (`nextion/`) + côté Pi |
| ADS1115 (I2C) | Capteur de vide du venturi (voie A0) | Côté Pi |
| Adaptateur USB-RS485 | 2 transmetteurs d'ozone | Côté Pi |
| Cartes 8 relais, cartes d'entrées 24 V optocouplées | Sorties et entrées tout-ou-rien | Réglages + côté Pi |
| Caméras : plafond (Camera Module 3 Wide), tête de griffe (USB 5 Mpx), dosage (sur servo) | Vision, QR, photos | Côté Pi |
| Capteurs de tête : distance VL53L1X, thermomètre IR MLX90614 | Hauteur des bords, température | Côté Pi |

Moteurs : pilotes boucle fermée (alarme renvoyée), NEMA 23 à frein sur les axes verticaux.
Pas de pneumatique pour les axes.

## Le programme du Pi, en morceaux séparés

Chaque morceau peut planter sans faire tomber les autres.

1. **Liaison FluidNC** (une par carte) : envoie le G-code, lit positions, états et alarmes, gère la reprise.
2. **Chef d'orchestre** : chaque module est une liste d'étapes avec leurs conditions (« la griffe ne descend que si... »). Gère pause, reprise, alarmes, zones réservées entre axes, attente du « Go ».
3. **Vision** : caméras, QR, repérage des bocaux et des seaux (OpenCV, zxing-cpp, NumPy ; YOLO nano en option).
4. **Registre** : base SQLite sur le Pi (fûts, seaux, bocaux, cycles, mesures, photos, alarmes, réglages appliqués).
5. **Écrans** : Nextion (simple : état, alarme et quoi faire, Pause, Go, compteurs) et page web (tout le reste : vidéos, photos, historique, réglages, pilotage manuel), ouverte depuis le téléphone ou un PC, sur place ou à distance par Tailscale.
6. **Liens extérieurs** : vers le logiciel de culture (Django, serveur N97), vers le PC de bureau (calculs lourds, seulement sur demande de Karulium), vers la copie de secours de la maison (tunnel chiffré, aucun port ouvert). Tout passe par une **file d'envoi** : la machine ne dépend jamais du réseau.
7. **Simulateur** : le même chef d'orchestre tourne contre une machine imaginaire (faux FluidNC, faux capteurs, durées réglables). C'est la base du jumeau numérique et des tests.

## Les fichiers de réglages

- `fluidnc/<carte>.yaml` : réglages FluidNC (pas par mm, courses, vitesses, accélérations, sens des fins de course).
- `pi/reglages/machine.yaml` : positions nommées, zones interdites, hauteurs de passage, durées, poids cibles.
- `docs/entrees-sorties.yaml` : chaque capteur, moteur, relais, avec sa carte, sa broche, son type de signal et son sens au repos.

Repère de la machine : x vers le stockage, y vers l'allée, z vers le haut, en mètres.

## Le jumeau numérique (plus tard)

Un solveur d'ordonnancement (OR-Tools, gratuit) calcule l'ordre des tâches le plus court qui respecte toutes les règles ; le simulateur vérifie un programme avant que le Pi l'envoie ; les vrais temps mesurés recalent les durées ; un geste qui ralentit donne une alerte d'usure. Pas d'apprentissage par renforcement.
