# Essai de la caméra du micropore sur le vrai matériel (tâche 40 ter)

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent que des **images
fabriquées** par OpenCV : QR droits, tournés, flous, cachés, trous, morceau posé, absent, décalé, de travers, trop
court. Aucune vraie photo n'a encore été vue par le programme. Cet essai sert à régler les chiffres marqués EXEMPLE
dans `pi/reglages/vision.yaml → inspection` sur la vraie caméra. Compter environ 2 heures.

La caméra du micropore (`cam_inspection` du projet mécanique) ne protège personne : elle lit, elle ne commande
rien. L'arrêt d'urgence reste câblé comme d'habitude.

Ce que la caméra fait, en trois mots :
- **QR du flanc** : le plateau tourne le seau, la caméra lit le QR en bas du flanc, et on en tire l'angle des
  oreilles de l'anse (pour les mettre à 45° des barres) ;
- **trous** : au tour de repérage du micropore, la caméra trouve les trous et l'angle du plateau où chacun passe
  devant elle ;
- **morceau posé** : après chaque pose, la caméra dit si le trou est couvert (couvert, découvert, de travers, mal
  coupé).

Ce qui n'est pas lu par la caméra tant qu'il n'y a pas de vraies photos (tâche 22 ter) : les **attaches de
l'anse** (on note à la main l'écart attaches/QR de chaque seau, étape 5) et le **diamètre du bord du seau**.

Il faut : la caméra montée sur le chariot et branchée en USB, un seau vide de chaque format avec son **QR collé en
bas du flanc**, un feutre, un réglet, un morceau de micropore.

## Avant de commencer

1. Arrêter le programme principal : `sudo systemctl stop vidange`.
2. Dans les commandes ci-dessous, `vidange-vision` veut dire
   `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-vision`. On peut ajouter `--faux` à toute commande
   pour voir ce que l'outil dit **sans caméra** (images fabriquées).
3. Le plateau se tourne avec `vidange-remplissage` (procédure `essai-remplissage.md`), tête du micropore
   **vue escamotée à l'œil** avant chaque mouvement du plateau.

## Étape 1 : la caméra donne une image

1. `ls /dev/v4l/by-id/` : écrire le nom de la caméra du micropore dans `pi/reglages/programme.yaml → cameras →
   liste → micropore → commande` (à la place de `usb-EXEMPLE-MICROPORE-video-index0`), jamais `/dev/video0`.
2. `vidange-vision photo micropore /tmp/m.jpg`, copier la photo sur un PC et la regarder : nette, QR lisible à
   l'œil ? Si le flou revient, régler la mise au point de la caméra (autofocus USB) puis refaire la photo.
3. Les lumières de la caméra (LED blanches, etc.) viennent de la carte de lumières du chariot : **le programme ne
   les commande pas encore** (question 4 de la PR). Les allumer comme on peut, pour avoir une photo nette.

## Étape 2 : la taille d'un point sur la paroi

1. Seau sur le plateau, le réglet collé contre la paroi à l'endroit où l'on verra les trous. `vidange-vision
   photo micropore /tmp/r.jpg`.
2. Sur la photo : compter combien de points (pixels) font 50 mm de réglet. Taille d'un point = 50 ÷ ce nombre
   (exemple : 100 points pour 50 mm, donc 0,5 mm). L'écrire dans `inspection → echelle_mm_par_point`.
3. `vidange --verifier` doit dire « Réglages corrects ».

## Étape 3 : lire le QR du flanc

1. Seau avec QR sur le plateau, plateau à la hauteur `remplissage → plateau_lecture_qr`. Tourner le plateau par
   petits pas (`vidange-remplissage … tourner 10`).
2. À chaque pas : `vidange-vision flanc`. La ligne « QR S1293 : +120 points du centre » dit où est le QR dans
   l'image. Quand il est à moins de `centre_tolerance_px` du centre, la ligne ajoute « AU CENTRE ».
3. Vérifier : le QR est lu (code juste) sur plusieurs pas de suite, pas seulement au centre. S'il n'est lu que
   dans un coin de l'image, voir la photo : trop petit ? trop flou ? Le dire dans la PR avec la photo.
4. Essayer un QR sale, un QR mouillé, un QR à moitié caché : la caméra doit **ne rien lire** plutôt qu'un mauvais
   code. Dans le cycle, un QR pas lu après un tour complet arrête le Pi avec l'alerte « QR du flanc du seau pas
   lu » et l'écran dit de mettre ce seau de côté à la main.

## Étape 4 : trouver les trous

1. Seau à trous (ou seau d'essai percé) sur le plateau. `vidange-vision flanc` : chaque trou donne une ligne
   « trou : … points du centre, à … de haut, Ø … points ».
2. Contrôler le diamètre : Ø en points × taille d'un point doit faire ≈ 10 mm. Sinon corriger
   `inspection → trous → diametre_mm` (le vrai diamètre) ou `tolerance_diametre`.
3. Une tache qui n'est pas un trou (vis, reflet) ne doit pas être comptée ; un vrai trou ne doit pas manquer.
   Sinon régler `trous → contraste_min` (écart de gris avec la paroi) et `circularite_min`.
4. Une seule rangée par image : la caméra est fixe, à `objectif_z_m` (0,600, EXEMPLE), à environ 5 cm de la
   paroi, et ne voit qu'à ±3,5 cm (±2,5 cm utiles, `vue_utile_m`). Le Micropore fait donc **un tour de repérage
   par rangée**, plateau à `objectif_z_m` − hauteur de la rangée, juste avant de poser cette rangée (rangée du
   haut : au poste, seau vide ; rangée du fond : au vidage, une fois le poids minimum atteint). Mettre à la
   main le plateau à cette hauteur (`vidange-remplissage`) et vérifier que la rangée est au milieu de l'image
   et que ses trous restent dans l'image ; sinon corriger `objectif_z_m` ou la hauteur de rangée.
5. `trous → suivi_max_y_px` : écart de hauteur (en points) toléré pour qu'un même trou soit suivi d'une image
   à l'autre. À régler si un trou est compté deux fois ou perdu.

## Étape 5 : l'écart attaches de l'anse / QR (par seau)

Il sert à corriger l'angle des oreilles de l'anse : le QR donne l'angle, les attaches sont ailleurs sur le seau.

1. Tourner le plateau jusqu'à ce que le QR soit **AU CENTRE** (`vidange-vision flanc`) : noter l'angle du plateau
   (`vidange-remplissage … etat`), appelons-le A1.
2. Tourner jusqu'à ce qu'une des deux attaches de l'anse soit au centre de l'image : angle A2.
3. Écart = A2 − A1 (en degrés, entre −90 et 90 : les deux attaches sont à 180° l'une de l'autre).
4. `vidange-vision ecart S1293 12.5` (le code du seau, puis l'écart). `vidange-vision ecart S1293` le relit.
5. Si **tous les QR sont collés au même endroit par rapport aux attaches**, mesurer sur 3 seaux ; si l'écart est le
   même, l'écrire une fois dans `inspection → flanc → ecart_attaches_defaut_deg` (il sert à tout seau dont l'écart
   n'est pas enregistré). Sinon, un écart par seau avec la commande ci-dessus (question 1 de la PR).

## Étape 6 : l'angle caméra → rouleau

1. `vidange-vision rouleau seau_a` : l'angle que donne la vision (≈ 31,8° d'exemple) pour chaque rangée.
2. Mesurer le vrai (procédure `essai-micropore.md`, étape 7, points 3 et 4) : marque au feutre en face du
   rouleau, tourner le plateau jusqu'à la voir au centre de l'image, compter les degrés.
3. Si les deux angles sont à moins de 2° : tout va bien, `vidange-micropore apprendre seau_a` (sans
   `--camera-rouleau`) apprend l'angle de la vision.
4. Sinon : la géométrie de `inspection → geometrie` est fausse. Vérifier `rouleau_azimut_deg` (le rouleau est
   côté −y de l'axe du plateau : −90°), et si la caméra ne vise pas l'axe du plateau, écrire `cap_deg` (la
   direction qu'elle regarde). En attendant, forcer : `apprendre seau_a --camera-rouleau 34` (la valeur mesurée).

## Étape 7 : le contrôle d'un morceau

1. Coller à la main un morceau de micropore de 30 × 25 mm sur un trou, plateau arrêté, le trou **au centre de
   l'image** (en largeur). Noter la hauteur du trou dans l'image (la ligne « trou : … à 360 de haut » de
   `vidange-vision flanc` la donne).
2. `vidange-vision piece --y 360` (la hauteur du trou). Attendu : « Trou COUVERT ».
3. Refaire en cachant mal : morceau décalé d'un centimètre, morceau de travers (20°), morceau coupé trop court,
   pas de morceau. Chaque fois : « Trou PAS couvert : … » avec la raison. Sinon, régler `inspection → piece`
   (`tolerance_taille`, `inclinaison_max_deg`, `marge_mm`).
4. Dans le cycle : trou pas couvert, un nouvel essai sur ce trou, puis alerte et seau « micropore à vérifier ».

## Étape 8 : finir

1. Quand tous les chiffres EXEMPLE ont été vus, passer `vision.yaml → inspection → exemple` à `false`, puis
   `vidange --verifier`.
2. Alors, sur la vraie machine, les postes « qr_du_flanc » et « micropore » ne manquent plus que pour **ce qui
   reste** : les cartes du chariot et de la tête, branchées au programme principal (journal et check-list
   le disent : « attend seau_vide » et « carte de la tête du micropore pas encore branchée »).

## Ce qui ne peut pas encore s'essayer

- **Le tour complet dans le cycle** : le programme principal ne branche pas encore les cartes du chariot et de la
  tête ; les tests jouent le tour avec des images fabriquées.
- **La vitesse du tour** (plateau qui tourne le seau devant la caméra) : elle n'est pas réglée ici. La caméra
  filme à 5 images par seconde (`programme.yaml → cameras`) ; le QR doit être lu sur au moins 2 images différentes,
  donc le tour ne doit pas être trop rapide. À mesurer au premier essai du cycle.
- **L'attaches de l'anse vues par la caméra** et le **jugement « bien collé »** : il faut de vraies photos
  (tâche 22 ter).

Noter les chiffres trouvés et les remarques dans la PR, ou les donner à la prochaine session.
