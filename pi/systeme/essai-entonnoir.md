# Essai de l'entonnoir à bocaux sur le vrai matériel (tâche 43)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent qu'une tête imaginaire, un faux
entonnoir et une fausse caméra. Cet essai se fait **après l'essai de la préhension** (`essai-prehension.md` :
ventouse, vide à −55 kPa, contact de la tête, rotation) et après la mise en pression de l'air
(`essai-air.md`). Compter 2 heures.

L'entonnoir ne protège personne et ne fait mal à personne : 0,9 kg au plus, tenu à 6 cm au-dessus des
bocaux. Il peut tomber (si le vide se perd) : **ne jamais passer la main sous la tête** quand elle bouge.
L'arrêt d'urgence reste câblé comme d'habitude.

Il faut : l'entonnoir du commerce avec sa douille coupée à Ø 70 et son oreille soudée à plat (80 × 80, côté
opposé à la tuyauterie), au moins **4 bocaux vides** posés en quinconce sur le tapis du stockage (les 4 premiers
de la 1re rangée suffisent), un mètre, un réglet, un pied à coulisse, un feutre.

## Avant de commencer

1. Arrêter le programme principal : `sudo systemctl stop vidange`.
2. Dans les commandes ci-dessous, `vidange-entonnoir` et `vidange-prehension` veulent dire
   `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-entonnoir` (et de même pour l'autre).
3. Les chiffres à trouver sont dans `pi/reglages/machine.yaml`, partie `entonnoir` (tous marqués EXEMPLE sauf
   ceux de la fiche). Après chaque changement : `vidange --verifier` doit dire « Réglages corrects ».
4. L'air est en pression (le venturi en a besoin). Les électroaimants de la tête sont **éteints** pendant tout
   l'essai : l'inox ne colle pas, l'outil ne les allume pas.

## Étape 1 : les places que le Pi calcule

1. `vidange-entonnoir places`. Attendu (quinconce du Stockage) :
   `bocal_0_0 … tête x 1,3475 y 0,06, pont x 1,2185`.
2. Poser l'entonnoir sur le bocal de la rangée 1, place 1, **oreille vers le fond du stockage (côté +x)**,
   la douille bien dans le col. Mesurer avec le mètre : l'oreille est-elle à **14 cm** du centre du bocal
   (en x) ? Noter l'écart. Si ce n'est pas 14 cm à 5 mm près, le dire (le décalage est dans la fiche).
3. `vidange-entonnoir hauteurs` : lire les cotes de contrôle (haut de l'oreille, pointe, transport).

## Étape 2 : mesurer l'entonnoir posé

C'est ce qui remplace les chiffres EXEMPLE (hauteurs de la pièce reçue, après la coupe et la soudure).

1. Entonnoir posé sur le premier bocal, bien enfoncé. Mesurer au réglet, depuis le tapis (qui est à
   z 0,497), la hauteur du **dessus de l'oreille** : noter `oreille_z = 0,497 + la hauteur`. De même la
   **pointe** (bas de la douille) : `pointe_z` ; et le **haut du cône** : `cone_haut_z`.
2. Les écrire dans `machine.yaml → entonnoir` (`oreille_z`, `pointe_z`, `cone_haut_z`). Dans
   `prehension → objets → entonnoir`, mettre `dessous_m` = `oreille_z − pointe_z`.
3. Peser l'entonnoir avec son oreille (balance de cuisine) : `poids_n` = kg × 9,81 (au plus 0,9 kg).
4. `vidange --verifier` : « Réglages corrects ». Si « en transport la pointe n'est qu'à … mm » : la pointe est
   trop basse pour passer à plus de 4 cm au-dessus des cols voisins avec 6 cm de levée ; le dire.

## Étape 3 : prendre et poser (les vrais gestes)

1. Entonnoir posé à la main sur `bocal_0_0`, oreille vers +x. Les autres bocaux sont vides et à leur place.
2. `vidange-prehension entonnoir bocal_0_0 bocal_0_1`. **Rester debout devant, la main sur l'arrêt
   d'urgence.** La tête doit : monter, aller au-dessus de l'oreille, descendre vite puis lentement, toucher
   (le M8 du moyeu s'allume), aspirer, lever de 6 cm, rouler jusqu'au bocal voisin **à cette hauteur**, descendre
   lentement, toucher le col, souffler, remonter de 3 cm, puis monter en haut.
3. Le programme écrit « Entonnoir pris : vide … kPa, poids … N » puis « Entonnoir posé sur bocal_0_1 ».
   Noter le vide (≤ −55 kPa attendu) et le poids.
4. Regarder : l'entonnoir est-il **bien entré dans le col** de `bocal_0_1`, la douille au fond, le cône posé
   sur le verre ? Sinon, le dire (« pas entré », avec une photo).
5. Pendant le transport, mesurer à l'œil la garde entre la pointe et les cols voisins : au moins 4 cm.
6. Refaire dans l'autre sens, puis sur la rangée 2 (`bocal_1_0`), puis sur le dernier bocal d'une rangée
   (`bocal_0_13`, tête en x 2,7775 : la tête ne doit rien toucher).
7. Relever le **contact** donné à la prise et à la pose (le journal dit « contact à … m ») : à
   l'entonnoir bien posé, il doit valoir `oreille_z` à 5 mm près. Sinon, corriger `oreille_z` avec la valeur lue
   (la face de la ventouse au contact) et recommencer.

## Étape 4 : les erreurs, une par une

Pour chacune, relancer `vidange-prehension entonnoir …` après la mise en situation. La tête doit remonter
**en haut** et le message doit être clair.

1. **Entonnoir absent** : ne pas poser d'entonnoir. Attendu : « entonnoir absent sur le bocal rangée 1,
   place 1 » (la tête descend jusqu'à 15 mm sous l'attendu sans toucher).
2. **Mal posé** : poser l'entonnoir **de travers** (une pointe sur le bord du verre, oreille plus haute de
   plus de 1 cm). Attendu : « entonnoir mal posé ».
3. **Vide pas atteint** : poser un morceau de scotch sur la ventouse ou la salir. Attendu : un nouvel essai
   (la tête remonte de 5 mm et redescend), puis « la ventouse ne prend pas l'entonnoir ».
4. **Vide perdu en transport** : tenir l'entonnoir avec le vide, puis, en roulant, **détacher le tuyau de
   vide** (programme à l'arrêt de l'air). Attendu : arrêt du pont, tête en haut, « vide perdu en tenant
   l'entonnoir ». **Ne pas mettre la main sous la tête** : l'entonnoir tombe peut-être.
5. **Entonnoir collé au lâcher** : très difficile à provoquer ; si ça arrive, noter le vide lu.

Après chaque erreur : `vidange-entonnoir etat` dit où le Pi croit que l'entonnoir est (`inconnu` après
absent ou vide perdu). `vidange-entonnoir noter hors_machine` le remet à zéro entre deux essais.

## Étape 5 : la coupure de courant

1. Faire prendre l'entonnoir (étape 3), puis, **pendant qu'il est levé**, couper l'alimentation 24 V des
   électrovannes (le Pi reste allumé).
2. Attendu : le vide tombe (électrovannes normalement fermées), l'entonnoir peut tomber sur les bocaux ou
   rester posé de travers : **photographier**.
3. Redémarrer le programme principal : le journal dit « Entonnoir : coupure pendant qu'il était tenu :
   place inconnue ». `vidange-entonnoir etat` : `inconnu`.

## Étape 6 : fin

1. `vidange --verifier` : « Réglages corrects ».
2. Passer `entonnoir → exemple` à `false` quand tous les chiffres marqués EXEMPLE ont été vus (hauteurs,
   seuils de contrôle, délais du vide, remontée du lâcher).

## Ce qu'il faut renvoyer

Les hauteurs mesurées (oreille, pointe, cône), le poids de l'entonnoir, le vide à la prise, les contacts lus à
la prise et à la pose, l'écart des 14 cm, la garde en transport, et ce qui s'est passé à chaque erreur
(avec les photos).

## Ce qui ne peut pas encore s'essayer

- **Le lot complet** (pose à la main avec le Go, caméra du plafond, versement de la griffe, bocal suivant) : le
  programme principal ne branche pas encore l'Entonnoir (comme pour les tâches 34 à 41), la lecture de la photo
  du plafond n'est pas écrite (un faux répond les places attendues) et le versement de la griffe dans les bocaux
  n'est pas un geste du programme. Le lot complet se joue seulement au simulateur : `vidange-simulateur
  entonnoir`.
- **La reprise d'un lot après une coupure** : seul l'endroit de l'entonnoir est gardé.
