# Essai de la vision sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent que des **images
fabriquées** par OpenCV (QR, repères ArUco, mire en damier dessinés), une **fausse** caméra et un **faux**
servo.

Cette procédure vérifie les caméras, la calibration, la lecture des QR, le repère du lave-bocal et le servo de
la caméra du dosage, puis mesure les chiffres marqués EXEMPLE (`pi/reglages/vision.yaml`,
`pi/reglages/machine.yaml → camera_dosage`, `pi/reglages/programme.yaml → cameras`). Compter une journée, en
plusieurs fois (chaque caméra une fois montée).

La sécurité des personnes est câblée (arrêt d'urgence, portes). Les verrous du logiciel ne protègent que la
machine : garder la main sur l'arrêt d'urgence.

## Avant de commencer

- Le programme principal est arrêté (`sudo systemctl stop vidange`) : une seule commande par caméra.
- Les LED de l'enceinte sont allumées (toujours les mêmes, pour toutes les photos de mesure).
- Dans les commandes ci-dessous, `vidange-vision` veut dire
  `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-vision`.
- Essai de l'outil sans caméra (pour voir ce qu'il dit) : ajouter `--faux` à n'importe quelle commande.

## Étape 1 : imprimer la mire, les repères et un QR

1. `vidange-vision fabriquer /tmp/vision`, puis copier le dossier sur un PC (clé USB ou `scp`).
2. Imprimer `mire-damier.png` à **100 %** (sans « ajuster à la page »), la coller bien à plat sur un carton
   rigide. Mesurer une case à la règle : elle doit faire 25 mm. Sinon, écrire la vraie taille dans
   `vision.yaml → calibration → case_m` (en mètres : 0,0248 pour 24,8 mm).
3. Imprimer `aruco-lave-bocal-7.png` de sorte que le **carré noir** fasse 40 mm de côté ; le coller au centre
   du plateau du rince-verre (protégé de l'eau : plastifié ou sous un film transparent).
4. Imprimer `qr-S1293.png` (un QR d'essai) et quelques vraies étiquettes de couvercles et de bocaux.

## Étape 2 : chaque caméra donne une image

Pour chaque caméra (`plafond`, `tete_griffe`, `dosage`) :

1. Trouver le nom stable de la caméra USB : `ls /dev/v4l/by-id/` ; l'écrire dans sa commande
   (`programme.yaml → cameras → liste`), jamais `/dev/video0`. Caméra du plafond : `rpicam-hello --list-cameras`.
2. `vidange-vision photo plafond /tmp/plafond.jpg`, puis ouvrir la photo (copiée sur un PC) : nette, bien
   éclairée, toute la zone voulue dans l'image ?
3. Si l'image est trop petite pour lire un QR (étape 4), augmenter `--width/--height` (ou `-video_size`) dans
   la commande : la caméra de tête a ≥ 5 Mpx.
4. Quand les 3 caméras marchent : `programme.yaml → cameras → exemple: false`.

## Étape 3 : calibration (une fois par caméra)

1. `vidange-vision calibrer tete_griffe` : l'outil prend 15 photos, une toutes les 2 s. Entre deux photos,
   bouger la mire : au centre, dans chaque coin, penchée à gauche, à droite, en avant, en arrière, plus près,
   plus loin. Toute la mire doit être dans l'image.
2. Il dit « damier trouvé » ou « PAS trouvé » pour chaque photo. Il en faut 10 trouvées ; l'erreur moyenne
   doit rester sous 1 point. Sinon, recommencer (mire plus éclairée, moins de reflets, bien à plat).
3. Le fichier est écrit dans `pi/donnees/calibration/` (par exemple `tete_griffe.json`).
4. Pour la caméra du plafond (à 2,35 m), utiliser une mire plus grande : imprimer `mire-damier.png` en A3
   ou plus, mesurer une case et corriger `case_m` le temps de cette calibration.
5. Variante : prendre les photos soi-même (`vidange-vision photo ...` en bougeant la mire), les mettre dans un
   dossier, puis `vidange-vision calibrer plafond --images DOSSIER`.

## Étape 4 : lecture des QR par la caméra de tête

1. Poser 10 couvercles étiquetés sur une pile, et le QR d'essai.
2. Mettre la griffe au-dessus, **godet grand ouvert, axes à 1,05** (`vision.yaml → qr → lecture_tete`), avec
   `vidange-fluidnc console portique` (vitesse lente).
3. `vidange-vision qr tete_griffe` : chaque code lu, son centre et son angle. Tous les QR visibles doivent être
   lus. Tourner un couvercle de 90° : son angle doit changer de 90° (au signe près).
4. Combien de couvercles une photo couvre-t-elle ? (la fiche dit ≈ 9-10 photos pour 95 couvercles.)
5. Si des QR restent illisibles : essayer `autre_axes_z` (plus haut ou plus bas) et l'écrire dans
   `vision.yaml`. Noter aussi l'angle du repère d'angle par rapport au QR (plan v181) : `angle_objet_deg`.
6. Mesurer où est l'objectif par rapport à l'axe du mât (`cameras → tete_griffe → tete`) et l'angle du haut de
   l'image avec l'axe x du portique, tête à 0° (`orientation_deg`). Vérification : poser un QR à une place
   connue (mesurée au mètre), le lire ; l'écart doit rester sous 5 mm (à demander à Claude : un petit essai de
   `lire_vue` avec la position de la tête).

## Étape 5 : repère du lave-bocal vu par le plafond

1. Garer le pont **au bout opposé** (côté stockage, x ≥ 2,30 : `vision.yaml → plafond → pont_gare_x_min`) ;
   s'il cache encore la vue, augmenter ce chiffre.
2. Lave-bocal posé : `vidange-vision aruco plafond` doit dire « repère n° 7 ». Le côté du repère en points
   donne l'échelle (40 mm).
3. Cacher la moitié du repère avec la main : il ne doit plus être vu. Buée (vaporisateur d'eau sur le
   plateau) : noter s'il est encore vu.
4. Lave-bocal enlevé : `vidange-vision plafond` doit dire « pas vu » et « doute » (la reconnaissance du fût
   vide demande des photos réelles : tâche 22 ter). C'est pourquoi `controle_lave_bocal` reste à `false`.
5. Garder une trentaine de photos de chaque situation (`vidange-vision photo plafond ...`) : lave-bocal posé,
   fût vide, fût avec un seau, buée, objet inconnu. Elles serviront à la reconnaissance (tâche 22 ter).

## Étape 6 : servo de la caméra du dosage

1. Câblage : signal du servo sur **GPIO18** du Pi (broche 12), servo alimenté à part en 5 à 6,8 V (pas par le
   Pi), masse du servo reliée à une masse du Pi.
2. Dans `/boot/firmware/config.txt`, ajouter `dtoverlay=pwm,pin=18,func=3`, redémarrer le Pi.
   `pinctrl get 18` doit dire `PWM0_CHAN2` (sinon, chercher la bonne fonction pour le Pi 5 et corriger la
   ligne). `ls /sys/class/pwm/` : noter le nom de la puce (`pwmchip0` ou `pwmchip2`...) et l'écrire dans
   `machine.yaml → camera_dosage → pwm → fichier` (canal 2 pour GPIO18).
3. **Avant de tourner le servo** : agitateur au garage, griffe et préhension loin de la boîte (x < 1,10,
   y < 0,34, z 0,95-1,08). L'outil ne vérifie pas ce verrou.
4. `vidange-vision servo bocal`, puis `vidange-vision servo seau` : la caméra doit viser le bocal, puis le seau.
   Si l'angle n'est pas bon, essayer `vidange-vision servo 60`, `65`... et corriger `angle_seau_deg` (ou
   `impulsion` si le servo est la version 270°).
5. Chronométrer un aller : `pivot_s` doit être un peu plus long (marge de 0,2 s).
6. `vidange-vision photo dosage /tmp/seau.jpg` caméra vers le seau : le seau est-il bien dans l'image ?
7. Quand tout est vrai : `machine.yaml → camera_dosage → exemple: false`, `vision.yaml → exemple: false`.

## Ce qui n'est pas essayé ici

- La reconnaissance des objets du plafond (fût plein ou vide, bocaux sales...), le bocal « bon / douteux »,
  l'anse levée, le repère et le bac des couvercles : il faut d'abord des photos réelles (tâche 22 ter).
- Le bouton « Vérifié » à l'écran et la page des propositions du plafond : à brancher avec l'écran et la page
  web (voir la PR de la tâche 22).
