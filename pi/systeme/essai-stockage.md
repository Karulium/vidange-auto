# Essai du Stockage sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent qu'une **fausse**
boucle du stockage et des piles **imaginaires** (simulateur, scénario « stockage »).

Le Stockage est passif (aucun moteur) et n'a aucun capteur de présence : le Pi **calcule** les places à
partir de `pi/reglages/machine.yaml` (partie `stockage`) et tient l'inventaire. Cet essai vérifie la seule
entrée (la boucle des 3 microrupteurs), puis que les places et les cotes calculées sont celles de la vraie
machine. Compter une demi-journée.

À faire une fois la préhension essayée (`essai-prehension.md`) et le chariot de remplissage essayé
(`essai-remplissage.md`). La sécurité des personnes est câblée (arrêt d'urgence, portes) : la boucle du
stockage **informe et fait attendre**, elle ne protège personne. Garder la main sur l'arrêt d'urgence.

Dans les commandes ci-dessous, `vidange-es`, `vidange-stockage`, `vidange-prehension` et `vidange-remplissage`
veulent dire `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-es` (et de même pour les autres).
Le programme principal est arrêté (`sudo systemctl stop vidange`) : une seule liaison par carte.

## Étape 1 : la boucle des 3 microrupteurs

La boucle (3 microrupteurs **NF** en série : tiroir rentré ET verrouillé, P1 fermé, P2 fermé) arrive sur une
entrée 24 V optocouplée. Sa vraie broche est à écrire dans `docs/entrees-sorties.yaml` (signal
`boucle_stockage`, aujourd'hui « exemple » sur E6 de la carte `entrees_24v_1`).

1. Tout fermé : tiroir rentré et verrouillé, P1, P2 et P3 rabattus. Taper `vidange-es surveiller`.
   Attendu : `boucle_stockage` **actionné** (contact fermé).
2. Déverrouiller le tiroir sans le tirer. Attendu : `boucle_stockage` passe au **repos** en moins d'une seconde.
   Reverrouiller : actionné.
3. Tirer le tiroir de 5 cm, puis le rentrer sans le verrouiller : repos les deux fois. Le verrouiller : actionné.
4. Relever P1 (plateau vidé, tapis enlevé) : repos. Le rabattre : actionné. Même chose avec P2.
5. Si un des cas reste « actionné », le microrupteur est mal réglé ou court-circuité : le régler avant la suite.
6. Enlever `exemple: true` de la ligne `boucle_stockage` une fois la vraie broche écrite.

## Étape 2 : boucle ouverte, rien ne bouge

Le cycle de production complet ne se lance pas encore depuis l'écran (il viendra avec le solveur, tâche 23).
En attendant, regarder le comportement voulu sur le simulateur : `vidange-simulateur stockage` (le lot
de 26 seaux A : 20 au tiroir puis 6 sur la bande du haut, chacun suivi de sa photo ; « plus de place »,
le tiroir tiré puis remis, Go, les seaux suivants rangés dans la file 1 vidée).

Quand le cycle se lancera depuis l'écran :

1. Lancer un remplissage (des seaux vides sur les piles), puis relever P1 **avant** le Go.
2. Attendu : l'écran dit qu'il attend « boucle du stockage fermée (tiroir rentré et verrouillé, P1, P2 et P3
   fermés) » ; ni le portique ni le chariot ne bougent.
3. Rabattre P1 : le cycle part.
4. Pendant un geste (la tête qui va vers une pile), déverrouiller le tiroir : le geste s'arrête, alarme « plus
   tenu : boucle du stockage fermée ». Reverrouiller, acquitter, Go : le geste reprend depuis son début.

## Étape 3 : cotes des piles

1. `vidange-stockage piles seau_a` (puis `seau_b`, `seau_c`, `seau_d`) : le nombre de seaux par pile et, pour
   chaque nombre k de seaux, le bord du seau du haut (repère du portique, en m) et la cote de la face de la
   tête au contact.
2. Pour chaque format : faire une pile de 1 seau sur la place `pile_1`, mesurer au mètre la hauteur du bord
   au-dessus de la tôle du plateau ; ajouter les seaux un par un et mesurer à chaque fois. Attendu : bord =
   0,496 + h + (k − 1) × pas, à 3 mm près.
3. Si le pas mesuré est autre : corriger `pas_pile_m` du format dans `machine.yaml` (partie `griffe` →
   `formats`). Si la hauteur h est autre : corriger `hauteur` (elle sert aussi au Mycélium).
4. Prise du seau du haut d'une pile pleine de A (5 seaux), avec la préhension (cotes données par
   `vidange-stockage piles seau_a`, ligne « 5 seau(x) ») :
   `vidange-prehension prendre-poser seau 1.30 0.84 0.621  1.30 0.84 0.621 --format seau_a`.
   Attendu : contact à moins de 5 mm de la cote annoncée, le seau du haut **se sépare seul** de la pile,
   il remonte sans toucher la pile, puis il est reposé. Recommencer avec une pile pleine de chaque format.
5. Rail opérateur (réponses à la PR n° 52) : tête en haut au-dessus de `pile_1` (y 0,84), seau A tenu :
   le haut du seau passe sous le chariot du rail opérateur (y 1,005 à 1,135, au-dessus de 1,11) sans le
   toucher. Le Pi refuse un seau tenu dont le haut dépasse 1,10 si son axe y + son rayon dépasse 0,995.

## Étape 4 : places des piles et ordre de vidage

1. `vidange-stockage places seau_a` : la liste des places dans l'ordre de vidage (la bande 0,215 d'abord,
   pour la libérer, puis la rangée y 0,84, puis 0,53, la pile la plus proche du chariot d'abord), les places de fin de lot calculées
   (pour A : x 1,2985 / 1,5755 / 1,8525 / 2,1295), la pile des couvercles.
2. Poser une pile à chaque place : elles ne doivent pas se toucher, et la dernière pile de fin de lot doit
   être à 10 cm au moins de la caméra du fond (hublot en x 2,50).
3. Mettre la tête au-dessus de chaque place (pilotage manuel de la page web) : son axe doit tomber au centre
   de la pile, à 5 mm près. Sinon corriger `stockage → piles → places` (ou `fin_de_lot → x_debut`).
4. Refaire avec `seau_b` (5 places de fin de lot, la 1re à x 1,29).

## Étape 5 : le tiroir

1. `vidange-stockage places seau_a` : les 3 files (y 0,215 / 0,500 / 0,785) et leur nombre de seaux.
2. Tiroir rentré et verrouillé, plateau du fût en place. Avec un seau A vide sur le plateau du chariot :
   `vidange-remplissage ranger seau_a file_1 --agitateur-au-garage --galet-range --micropore-rentre`.
   Attendu : le chariot va à y 0,215, plateau en bas, le pousseur pousse le seau dans la file ; la tôle du
   tiroir (0,176) est au plus 5 mm sous le plateau : le seau passe sans accrocher.
3. Recommencer jusqu'à remplir la file 1 (6 seaux A ; la place sous la caméra du fond, x 2,8785, reste vide) : à chaque poussée la file avance d'environ 0,272 ; le
   premier seau ne touche jamais la butée de fond (face d'appui à x **3,012**) en force. Noter l'effort
   ressenti (150 à 240 N pour une file de 6, à l'essai).
4. Même chose pour les files 2 et 3 (7 seaux A chacune, la première place à x 2,8785).
5. Seau B : 7 seaux dans **chaque** file (21 au tiroir) ; centres attendus de 2,897 à 1,487. Seau D : 5
   (file 0,215, place sous la caméra du fond vide) puis 6 et 6 (de 2,872 à 1,472).
6. Seau C : files 0,215 et 0,785 à 6 seaux, file 0,50 à 5 (cale de 15 cm contre la butée de la file
   y 0,50 : sa course de pousseur est plus courte de 0,15, `vidange-remplissage ... pousseur 0.175`
   pour voir). Centres attendus : files 0,215 et 0,785 à x 2,862 / 2,562 / 2,262 / 1,962 / 1,662 /
   1,362 ; file 0,50 à 2,712 / 2,412 / 2,112 / 1,812 / 1,512. Les mesurer au mètre.
7. Vider le tiroir comme l'écran le demande (plateau vidé, P1, P2 et P3 relevés, tiroir déverrouillé et tiré,
   seaux sortis, tout remis), puis confirmer à l'écran : l'inventaire des files repart à zéro.

## Étape 5 bis : la bande du haut (seaux pleins sur le plateau, tâche 35 bis)

1. `vidange-stockage places seau_a` : « Bande du haut y 0,215 : 6 places (centres x 2,73, 2,458, 2,186,
   1,914, 1,642, 1,37) » et « Capacité d'un lot : 26 seaux ». Mêmes lignes pour B (7 places, lot de 28),
   C (5, lot de 22), D (6, lot de 23).
2. Bande vide (pas de pile de fin de lot dessus), tapis enlevé. Seau A plein sur le plateau du chariot :
   `vidange-remplissage --galet-range --agitateur-au-garage ranger seau_a bande_haut` (voir
   `essai-remplissage.md`, étape 4). Attendu : le seau entre par le bord de P1 (x 1,155) et s'arrête vers
   x 1,37.
3. Recommencer jusqu'à 6 seaux : à chaque poussée, les seaux avancent d'une place (contact des rebords).
   Avec 6 seaux, **mesurer** le bord du seau du bout : il doit rester à x ≤ **2,87** (jamais sur le hublot,
   verre de x 2,88 à 2,98). Mesurer aussi l'axe de chaque seau en y : 0,215 à **7 mm** près. Noter les vrais centres et
   corriger `stockage → bande_haut → places` si besoin (`vidange --verifier` refuse un seau qui dépasse
   2,87). Régler `remplissage → rangement → bande_haut → pousseur_m` pour que le seau poussé arrive à sa
   place.
4. La photo du plafond après chaque poussée n'est pas encore lue par la vision (un faux répond les places
   attendues, le journal le dit) : quand la vision saura la lire, décaler un seau de 1 cm en y à la main ;
   le Pi doit s'arrêter avec l'alerte « seau de la bande du haut ... de sa ligne ».
5. Vider : les seaux de la bande partent avec ceux du tiroir (étape 5, point 7).

## Étape 6 : bocaux et boîtes à capsules

1. Mode bocaux, tapis posé : poser un bocal aux places `bocal_0_0`, `bocal_1_0`, `bocal_8_10` (voir
   `vidange-stockage places`) ; les places doivent tomber dans le quinconce de 95 sans se toucher.
2. Coin d'inspection (liste du fil Stockage, côté x grand) : poser un bocal aux places suspects
   `bocal_8_8` à `bocal_8_10`, `bocal_7_7` à `bocal_7_9`, `bocal_6_8` à `bocal_6_10` ; les places de
   séparation (`bocal_5_7` à `bocal_5_9`, `bocal_6_7`, `bocal_7_6`, `bocal_8_7`) restent vides. Vérifier
   qu'elles forment bien le coin du haut.
3. Boîtes à capsules en (2,52 ; 0,53) et (2,52 ; 0,80) : mesurer leur fond et leur dessus (0,498 et 0,739) et
   l'épaisseur d'une capsule (13 mm) ; corriger `stockage → boites` si besoin.

## À la fin

Passer `exemple: false` dans la partie `stockage` de `machine.yaml` quand tous les chiffres marqués EXEMPLE
ont été vérifiés. Lancer `vidange --verifier` : une erreur (piles qui se chevauchent, file trop longue pour
le tiroir...) dit laquelle.

## Étape 7 : le stockage agrandi de 43 cm (tâche 35 ter)

Testé sur le vrai matériel : non. À faire quand les 3 panneaux et le tiroir agrandi sont montés.

1. Boucle : fermer tiroir, P1, P2, P3 ; `vidange-es surveiller` doit voir la boucle fermée. Ouvrir P3 seul
   (microrupteur à x 2,765) : elle s'ouvre ; idem pour P2 (x 2,1375), P1 (x 1,510) et le tiroir.
2. Tiroir : butée à x 3,012 (face d'appui). Remplir une file de A : la première place (x 2,8785) sur les files
   0,50 et 0,785 ; sur la file 0,215, le pousseur s'arrête au codeur sur la 2e place (x 2,6065) et la place
   sous la caméra du fond reste vide. Même chose pour D (x 2,872 / 2,592). Mesurer les centres au mètre.
3. Capacité du lot : A 26, B 28, C 22, D 23 ; `vidange-stockage places seau_a` (et b, c, d).
4. Bocaux : 14 par rangée paire (x 1,2075 à 2,6375), 13 par rangée impaire : 122 places. Coin des suspects :
   [8,13] à x 2,6375 doit être à la portée de la griffe (x ≤ 2,738).
5. Boîtes à capsules en (2,95 ; 0,53) et (2,95 ; 0,80), hublot en (2,93 ; 0,22).
