# Essai de la griffe sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent qu'un
**faux** FluidNC, une **fausse** pesée de la griffe et un fût **imaginaire** (simulateur).

Cette procédure ne peut se faire qu'**après la tâche 22 bis** (carte de pesée RS485 de la griffe) et une
fois le portique câblé (carte FluidNC n° 1 avec ses 5 axes : pont X, chariot Y, griffe Z, rotation A,
godet B). Elle sert à **mesurer les chiffres marqués EXEMPLE** dans `pi/reglages/machine.yaml`
(partie `griffe`), puis à faire une première vidange lente, Karulium à côté de l'arrêt d'urgence.
Compter une journée.

La sécurité des personnes est câblée (arrêt d'urgence, portes). Les règles de position du logiciel
ne protègent que la machine : pendant les essais, garder la main sur l'arrêt d'urgence.

## Avant de commencer

- Le poste du fût est essayé (`essai-poste-fut.md`).
- Les réglages FluidNC de la carte du portique sont faits pour que **la position machine soit dans le
  repère du portique** : X = position du pont (mm), Y = position du mât en y (mm), Z = **hauteur des axes
  de la tête** (mm, 1 290 en butée haute), A = rotation de la tête (°, 0 = bras le long du pont),
  B = vis du godet (mm, **0 = fermé**, jamais en dessous).
- Prise d'origine faite (`$H`), carte sans alarme.

Dans les commandes ci-dessous, `vidange-fluidnc` veut dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc`.

## Étape 1 : vérifier le repère

1. Lancer la console de la carte : `vidange-fluidnc console portique`.
2. Envoyer `?` : la carte répond avec ses positions (`MPos:...`).
3. Déplacer le pont lentement : `$J=G53 X600 F600`. Mesurer au mètre la position du mât de la griffe :
   elle doit être **600 − 175 = 425 mm**. Sinon, noter l'écart (`decalage_mat_x`).
4. Monter la tête en butée haute : `$J=G53 Z1290 F300`. Mesurer la hauteur du **bas du godet fermé** :
   elle doit être **1 087 mm** (`bas_godet_sous_axes` = 1 290 − 1 087 = 203 mm).
5. Godet : `$J=G53 B0 F300` (fermé), puis grand ouvert à la main par petits pas (`$J=G91 B1 F300`)
   jusqu'à la vraie ouverture maximale. Noter la valeur de B : c'est la fin de la course de `griffe_b`
   dans `machine.yaml` (30 mm dans l'exemple).
6. Rotation : `$J=G53 A0 F600`, vérifier que le bras est le long du pont et noter de quel côté est la
   raclette (`raclette_angle_deg` : 180 si elle regarde vers le fût, vers −x).
7. Noter jusqu'où la tête peut tourner dans chaque sens sans tirer sur les câbles (course de `griffe_a`).

## Étape 2 : la pesée de la griffe

1. Godet vide, tête en haut : lire la charge (outil de la tâche 22 bis). Noter la valeur : c'est la
   charge pendue à vide.
2. Descendre lentement le godet ouvert sur un bac de substrat : la charge doit **baisser** quand le godet
   touche. Noter de combien elle baisse au premier contact franc : régler `descente → seuil_contact_n`
   un peu au-dessus du bruit de la mesure (exemple : 15 N).
3. Appuyer le godet fermé sur un fond dur : vérifier que 30 à 50 N de baisse correspondent à un appui
   léger qui ne marque pas le fond (`fond → seuil_appui_n`, `force_max_n`).

## Étape 3 : la table des volumes

Pour chaque ouverture de la table (0,2 ; 0,4 ; 0,6 ; 0,8 ; 1) et chaque enfoncement (0 ; 2 ; 4 cm) :

1. Prendre du substrat dans un bac plat de hauteur connue, avec ce réglage.
2. Peser la prise ; diviser par la densité du substrat du bac (pesée d'un seau de 10 L plein) :
   c'est le volume pris.
3. Remplir la ligne de `volumes → litres`. Le volume doit grandir avec l'ouverture (vérifié au démarrage).

## Étape 4 : formats des seaux et poste de remplissage

1. Pour chaque format de seau, mesurer au poste de remplissage : la hauteur du haut du seau (`haut_z`) et
   son rayon en haut (`rayon_haut`). Recevoir du projet mécanique la dose par couche et le nombre de couches.
2. Mesurer la position du mât quand le godet est centré sur le seau (`seau_remplissage`).
3. Lancer `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange --verifier` : il dit si une hauteur
   sort de la course.

## Étape 5 : une vidange lente

1. Dans `machine.yaml`, diviser toutes les `vitesses` par 4 pour ce premier essai.
2. Rejouer d'abord sur le PC : `vidange-simulateur griffe` (le cycle doit aller au bout).
3. Fût au poste, « Prêt », Karulium à l'arrêt d'urgence. Regarder chaque geste : descente au contact,
   bouchées, prise, pesée, trajet (d'abord en x, puis en y), vidage en couronne, tassement, essuyage.
4. Pendant l'essuyage et le vidage, regarder le jeu entre la tête et le boîtier de la caméra du bocal
   (au moins 1 cm) ; s'il est plus petit, arrêter et le dire (réglages `griffe → tete`, `camera_bocal`).
5. Vérifier dans le journal que la somme des doses suit la pesée du fût (pas d'avertissement « écart »).
6. Essayer un choc, **machine fermée, personne dedans** : poser un carton vide sur le trajet du godet,
   vitesses lentes. Au contact, la griffe doit s'arrêter, alarme ; enlever le carton, acquitter, Go :
   elle remonte d'abord lentement.
7. Essayer la perte du chariot **sans bouger le chariot** : pendant une prise, débrancher la prise du
   détecteur du chariot (M12). Alarme : la griffe remonte et le pont sort de la zone du chariot.
   Rebrancher, « Prêt », acquitter, Go.
8. Quand tout est bon : remettre les vitesses, passer `griffe → exemple` à `false`.
