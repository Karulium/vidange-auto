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

1. Tout fermé : tiroir rentré et verrouillé, P1 et P2 rabattus. Taper `vidange-es surveiller`.
   Attendu : `boucle_stockage` **actionné** (contact fermé).
2. Déverrouiller le tiroir sans le tirer. Attendu : `boucle_stockage` passe au **repos** en moins d'une seconde.
   Reverrouiller : actionné.
3. Tirer le tiroir de 5 cm, puis le rentrer sans le verrouiller : repos les deux fois. Le verrouiller : actionné.
4. Relever P1 (plateau vidé, tapis enlevé) : repos. Le rabattre : actionné. Même chose avec P2.
5. Si un des cas reste « actionné », le microrupteur est mal réglé ou court-circuité : le régler avant la suite.
6. Enlever `exemple: true` de la ligne `boucle_stockage` une fois la vraie broche écrite.

## Étape 2 : boucle ouverte, rien ne bouge

Le cycle de production complet ne se lance pas encore depuis l'écran (il viendra avec le solveur, tâche 23).
En attendant, regarder le comportement voulu sur le simulateur : `vidange-simulateur stockage` (14 seaux
rangés, « plus de place », le tiroir tiré puis remis, Go, le 15e seau rangé dans la file 1 vidée).

Quand le cycle se lancera depuis l'écran :

1. Lancer un remplissage (des seaux vides sur les piles), puis relever P1 **avant** le Go.
2. Attendu : l'écran dit qu'il attend « boucle du stockage fermée (tiroir rentré et verrouillé, P1 et P2
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
5. Noter la hauteur du haut du seau tenu quand la tête est en haut au-dessus de `pile_1` (y 0,84) : la
   règle du rail opérateur (question n° 1 de la PR de la tâche 35) en dépend.

## Étape 4 : places des piles et ordre de vidage

1. `vidange-stockage places seau_a` : la liste des places dans l'ordre de vidage (rangée y 0,84, puis 0,53,
   puis la bande 0,215, la pile la plus proche du chariot d'abord), les places de fin de lot calculées
   (pour A : x 1,2985 / 1,5755 / 1,8525 / 2,1295), la pile des couvercles.
2. Poser une pile à chaque place : elles ne doivent pas se toucher, et la dernière pile de fin de lot doit
   être à 10 cm au moins de la caméra du fond (hublot en x 2,50).
3. Mettre la tête au-dessus de chaque place (pilotage manuel de la page web) : son axe doit tomber au centre
   de la pile, à 5 mm près. Sinon corriger `stockage → piles → places` (ou `fin_de_lot → x_debut`).
4. Refaire avec `seau_b` (5 places de fin de lot, la 1re à x 1,29).

## Étape 5 : le tiroir

1. `vidange-stockage places seau_a` : les 3 files (y 0,215 / 0,500 / 0,785) et leur nombre de seaux.
2. Tiroir rentré et verrouillé, chariot du fût en place. Avec un seau A vide sur le plateau du chariot :
   `vidange-remplissage ranger seau_a file_1 --agitateur-au-garage --galet-range --micropore-rentre`.
   Attendu : le chariot va à y 0,215, plateau en bas, le pousseur pousse le seau dans la file ; la tôle du
   tiroir (0,176) est au plus 5 mm sous le plateau : le seau passe sans accrocher.
3. Recommencer jusqu'à remplir la file 1 (4 seaux A) : à chaque poussée la file avance d'environ 0,272 ; le
   premier seau ne touche jamais la butée de fond (x 2,612) en force. Noter l'effort ressenti (150 à 240 N
   pour une file de 6, à l'essai).
4. Même chose pour les files 2 et 3 (5 seaux chacune).
5. Seau C : poser la cale de 15 cm, ranger 16 seaux. **Noter combien de seaux tiennent dans chaque file** et
   corriger `stockage → tiroir → places → seau_c` (aujourd'hui 5 / 6 / 5, un EXEMPLE).
6. Vider le tiroir comme l'écran le demande (plateau vidé, P1 et P2 relevés, tiroir déverrouillé et tiré,
   seaux sortis, tout remis), puis confirmer à l'écran : l'inventaire des files repart à zéro.

## Étape 6 : bocaux et boîtes à capsules

1. Mode bocaux, tapis posé : poser un bocal aux places `bocal_0_0`, `bocal_1_0`, `bocal_8_10` (voir
   `vidange-stockage places`) ; les places doivent tomber dans le quinconce de 95 sans se toucher.
2. Écrire dans `stockage → bocaux → inspection` la vraie liste des places « suspects » et « séparation »
   (fichier du fil Stockage), puis vérifier qu'elles forment bien le coin du haut.
3. Boîtes à capsules en (2,52 ; 0,53) et (2,52 ; 0,80) : mesurer leur fond et leur dessus (0,498 et 0,739) et
   l'épaisseur d'une capsule (13 mm) ; corriger `stockage → boites` si besoin.

## À la fin

Passer `exemple: false` dans la partie `stockage` de `machine.yaml` quand tous les chiffres marqués EXEMPLE
ont été vérifiés. Lancer `vidange --verifier` : une erreur (piles qui se chevauchent, file trop longue pour
le tiroir...) dit laquelle.
