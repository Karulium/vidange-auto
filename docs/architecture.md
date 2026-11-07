# Architecture du logiciel

## Le matériel de commande

| Carte | Rôle | Ce qu'on écrit |
|---|---|---|
| Raspberry Pi 5 8 Go, SSD NVMe 1 To | Le chef : enchaîne les étapes, vision, registre, écrans, liens | Python (`pi/`) |
| 4 cartes ESP32 FluidNC 6 axes, pilotes externes | Axes : portique, chariot, mycélium/lavage, préhension. Reliées au Pi par USB série | Réglages seulement (`fluidnc/`) |
| 1 carte ESP32 n° 5 (boîte du spray ; un ESP32-S3, exemple) | Pompes, balances des 4 flacons, électrovannes, bras de la buse ; Modbus RTU sur son bus RS485 à elle (`rs485_spray`, table : `spray/README.md`) | Petit programme (`spray/`, tâche 39 bis) + côté Pi (`pi/vidange/spray/`) |
| RP2040 + LIS3DH | Détection des chocs sur le chariot Z | Petit programme (`accelerometre/`) |
| 3 RP2040 + HX711 (griffe, préhension, plateau du remplissage) | Pesées embarquées, 80 mesures/s, sur un bus RS485 à elles (Modbus RTU) | Petit programme (`pesee/`) + côté Pi |
| 2 ESP32-C3 (plateau du fût, boîte du poste du fût) | Pesée sans fil du fût (radio ESP-NOW) ; la boîte répond sur le bus des pesées comme une carte (tâche 17 bis) | Petit programme (`poste_fut_radio/`, tâche 17 ter) + côté Pi |
| Écran Nextion 4,3" (porte de l'armoire) | Tableau de bord sur place, relié au Pi par UART (GPIO 4/5) | Pages Nextion (`nextion/`) + côté Pi |
| ADS1115 (I2C) | Capteur de vide du venturi (voie A0) | Côté Pi |
| SHT31 (I2C 0x44, partagé avec l'ADS1115 en 0x48, GPIO 2/3) | Température et humidité de l'armoire | Côté Pi |
| Micro USB | Écoute des bruits anormaux | Côté Pi |
| Voyant + buzzer « attention » (sortie relais ou GPIO) | Prévenir sur place avant un mouvement lancé à distance ou une reprise | Côté Pi |
| Pile de l'horloge du Pi 5 | Heure juste sans réseau | Rien |
| 2 adaptateurs USB-RS485 (un par capteur) | 2 capteurs d'ozone ZE25-O3 en UART (`ozone_dedans`, `ozone_dehors`), pour informer seulement | Côté Pi |
| 2ᵉ adaptateur USB-RS485 | Bus des 3 cartes de pesée | Côté Pi |
| Cartes 8 relais, cartes d'entrées 24 V optocouplées | Sorties et entrées tout-ou-rien | Réglages + côté Pi |
| Caméras : plafond (Camera Module 3 Wide), tête de griffe (USB 5 Mpx), dosage (sur servo) | Vision, QR, photos | Côté Pi |
| Capteurs de tête : distance VL53L1X, thermomètre IR MLX90614 | Hauteur des bords, température | Côté Pi |

Moteurs : pilotes boucle fermée (alarme renvoyée), NEMA 23 à frein sur les axes verticaux.
Pas de pneumatique pour les axes.

## Le programme du Pi, en morceaux séparés

Chaque morceau peut planter sans faire tomber les autres.

1. **Liaison FluidNC** (une par carte) : envoie le G-code, lit positions, états et alarmes, gère la reprise.
2. **Chef d'orchestre** : chaque module est une liste d'étapes avec leurs conditions (« la griffe ne descend que si... »). Gère pause, reprise, alarmes, zones réservées entre axes, attente du « Go ».
3. **Vision** : caméras, QR, repères ArUco, repérage des bocaux et des seaux (OpenCV et NumPy seulement ; YOLO nano plus tard, quand il y aura des photos réelles pour l'entraîner).
4. **Registre** : base SQLite sur le Pi (fûts, seaux, bocaux, cycles, mesures, photos, alarmes, réglages appliqués).
5. **Écrans** : Nextion (simple : état, alarme et quoi faire, Pause, Go, compteurs) et page web (tout le reste : vidéos, photos, historique, réglages, pilotage manuel), ouverte depuis le téléphone ou un PC, sur place ou à distance par Tailscale.
6. **Liens extérieurs** : vers le logiciel de culture (Django, serveur N97), vers le PC de bureau (calculs lourds, seulement sur demande de Karulium), vers la copie de secours de la maison (tunnel chiffré, aucun port ouvert). Tout passe par une **file d'envoi** : la machine ne dépend jamais du réseau.
7. **Simulateur** : le même chef d'orchestre tourne contre une machine imaginaire (faux FluidNC, faux capteurs, durées réglables). C'est la base du jumeau numérique et des tests.
8. **Fiabilité** : chien de garde (systemd relance un programme figé ; les cartes sont surveillées par leur liaison), check-list de démarrage, reprise après coupure (carnet, retour en lieu sûr, Go), arrêt propre sur onduleur, bilan de chaque alarme, santé du Pi.
9. **Mises à jour**, machine à l'arrêt : cartes ESP32 par leur câble USB (copie de toute leur mémoire avant, vérification après, retour en arrière), programme du Pi depuis les versions acceptées sur `main`.

## Les fichiers de réglages

- `fluidnc/<carte>.yaml` : réglages FluidNC (pas par mm, courses, vitesses, accélérations, sens des fins de course).
- `pi/reglages/machine.yaml` : positions nommées, zones interdites, hauteurs de passage, durées, poids cibles.
- `docs/entrees-sorties.yaml` : chaque capteur, moteur, relais, avec sa carte, sa broche, son type de signal et son sens au repos.

Repère de la machine : x vers le stockage, y vers l'allée, z vers le haut, en mètres.

## Le jumeau numérique (plus tard)

Un solveur d'ordonnancement (OR-Tools, gratuit) calcule l'ordre des tâches le plus court qui respecte toutes les règles ; le simulateur vérifie un programme avant que le Pi l'envoie ; les vrais temps mesurés recalent les durées ; un geste qui ralentit donne une alerte d'usure. Pas d'apprentissage par renforcement.
