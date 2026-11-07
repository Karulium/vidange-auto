# Essai du versement de la griffe dans un bocal, avec du maïs chaud (tâche 43 bis)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent qu'une griffe imaginaire, un faux fût
et une fausse pesée. **Le geste n'a jamais été essayé avec du vrai maïs** : tout ce qui touche à la façon dont
les grains coulent (vitesse, attente, secousses, plage de la dose) est à régler ici.

Cet essai se fait **après** l'essai de la griffe (`essai-griffe.md` : repère, pesée de la griffe, butée haute,
origine du godet) et l'essai de l'entonnoir (`essai-entonnoir.md` : hauteurs de l'entonnoir posé). Compter une
demi-journée. Deux personnes : une à l'arrêt d'urgence, une qui regarde le godet et l'entonnoir.

La griffe ne protège personne : l'arrêt d'urgence et les portes restent câblés comme d'habitude. **Ne jamais
mettre la main sous le godet** quand la tête bouge, ni entre les coquilles. Le maïs est chaud : gants.

Il faut : un fût (ou un seau) de **maïs cuit, chaud, hydraté**, comme pour un vrai lot ; l'entonnoir ; 3 bocaux
vides à leur place sur le tapis du stockage : `bocal_1_2`, `bocal_1_3` et `bocal_2_1` (rangée 2, places 3 et 4 ;
rangée 3, place 2) ; une balance de cuisine (au gramme), un réglet, un mètre, un feutre, un téléphone pour
filmer.

## Avant de commencer

1. Arrêter le programme principal : `sudo systemctl stop vidange`.
2. Dans les commandes, `vidange-fluidnc`, `vidange-pesees` et `vidange-entonnoir` veulent dire
   `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc` (et de même pour les autres).
3. Les chiffres à régler sont dans `pi/reglages/machine.yaml`, partie `griffe → versement_bocal`. Ceux de la
   partie elle-même sont **figés** (fiche du 07/11) ; ceux des sous-parties `dose`, `ouverture`, `secousses`,
   `fin`, `godet`, `bouchage` sont marqués `exemple: true`. Après chaque changement :
   `vidange --verifier` doit dire « Réglages corrects ».
4. `vidange-entonnoir versement` : le Pi redit ses chiffres (dose, hauteur, ouvertures) et la **liste des
   bocaux où la griffe ne peut pas verser** avec les règles d'aujourd'hui (voir les questions de la PR).
   Vérifier que les 3 bocaux de l'essai n'y sont pas.

## Étape 1 : la position de la vis pour chaque angle du godet

C'est la table `godet` (EXEMPLE) : pour chaque angle des coquilles, la valeur de B (0 = fermé, 1 = grand
ouvert ; B est en mm sur la carte, de 0 à 36).

1. `vidange-fluidnc console portique`. Tête en haut, hors de tout : `$J=G53 Z1290 F300`, `$J=G53 A0 F600`.
2. Godet fermé : `$J=G53 B0 F300`.
3. Ouvrir par petits pas (`$J=G91 B1 F300`) et mesurer l'angle d'une coquille (rapporteur ou téléphone à
   plat) : noter la valeur de B à **15°, 20°, 25° et 35°**.
4. Dans `godet → b`, écrire B ÷ 36 pour chaque angle (exemple : 10 mm à 20° → 0,28). Vérifier que 35° est
   bien « grand ouvert » (B = 36) ; sinon le dire.
5. À 20°, mesurer la fente entre les dents : attendu environ 8 cm le long du pont et 10 cm en travers.

## Étape 2 : la tare « godet vide » et la hauteur

La tare n'est pas un réglage : le Pi la pèse à chaque prise, godet ouvert et vide, juste avant d'entrer dans le
maïs. Il faut vérifier qu'elle ne change pas avec la hauteur (câbles et chaîne qui tirent).

1. Godet vide et **sec**, fermé, tête en haut (Z1290) : `vidange-pesees lire`, noter la charge de la griffe.
2. Descendre à `$J=G53 Z1025 F300` (hors des bocaux), attendre 2 s, relire. Puis Z900, relire.
3. Les trois valeurs doivent être à **10 g près** (0,1 N). Sinon, arrêter et le dire : la tare devra être prise
   à la hauteur du versement.
4. Mouiller le godet (comme après un lavage), relire en haut : noter de combien il est plus lourd. (Le Pi
   repèse la tare à chaque prise : rien à régler, c'est pour savoir.)
5. Lire 10 fois de suite, tête immobile : l'écart entre la plus petite et la plus grande valeur doit rester
   sous ±3 g (bruit attendu, fiche). Plus de 10 g : le dire (réglages `fin → ecart_kg`).

## Étape 3 : au-dessus de l'entonnoir, sans maïs

1. Poser l'entonnoir à la main sur `bocal_2_1` (rangée 3, place 2), oreille vers le fond (+x).
2. Mât au-dessus du col : le pont est à **x du bocal + 0,187**. Pour `bocal_2_1` (x 1,3175 ; y 0,2506) :
   `$J=G53 X1504.5 F600`, puis `$J=G53 Y250.6 F600`, tête en haut, A = 0.
3. Descendre lentement : `$J=G53 Z1025 F300`. Regarder : le bas des dents doit être **2,7 cm au-dessus du
   haut du cône**. Mesurer au réglet et noter.
4. Regarder le jeu entre la raclette (côté −x) et le **boîtier de la caméra du bocal** : au moins 5 mm. Moins :
   arrêter, remonter, le dire.
5. Ouvrir à 20° (valeur de l'étape 1, à 10 mm/s : `F600`). Les dents ne doivent pas toucher le cône.
   Grand ouvert (35°) : idem. Refermer, remonter : `$J=G53 Z1290 F300`.
6. Capteur de distance de la tête (VL53L1X) : il n'est pas encore lu par le Pi. Mesurer au mètre la distance
   du capteur à la pointe de l'entonnoir vide, axes à 1,025, et l'écrire dans `bouchage → distance_vide_m`.

## Étape 4 : un versement à la main, avec du maïs chaud

1. Peser à la balance environ **300 g** de maïs chaud. Godet ouvert en haut, le verser à la main dans le godet,
   le refermer (`$J=G53 B0 F300`). `vidange-pesees lire` : la charge a-t-elle monté de 300 g (2,94 N) ? Noter.
2. Aller au-dessus de `bocal_2_1` comme à l'étape 3, descendre à Z1025.
3. Ouvrir à 20° **à 10 mm/s** (`F600`), filmer. Attendre 1,5 s. Lire la pesée. Combien reste-t-il dans le
   godet ? Combien de temps les grains mettent-ils à tomber ?
4. S'il en reste : 3 aller-retour entre 15° et 25° à 30 mm/s (`F1800`), attendre 1 s, relire ; puis 35°,
   attendre 1 s, relire. Noter ce qui a marché.
5. Remonter de 2 cm (`$J=G53 Z1045 F300`), **puis seulement** refermer le godet.
6. Regarder l'entonnoir : tout le maïs est-il descendu dans le bocal ? Peser le bocal (moins son poids vide) :
   on doit retrouver la dose à 10 g près.
7. Recommencer 5 fois. Régler d'après ce qu'on a vu : `ouverture → vitesse_m_s`, `ouverture → attente_s`,
   `secousses` (angles, vitesse, nombre), `fin → ecart_tare_kg`.

## Étape 5 : la prise d'une dose dans le fût

1. Fût de maïs chaud au poste, « Prêt ». Dans `machine.yaml`, diviser les `vitesses` de la griffe par 4.
2. Faire 10 prises à la console (descente au contact, ouverture, prise, remontée) comme dans
   `essai-griffe.md`, en visant peu (godet à peine ouvert). Peser chaque prise (`vidange-pesees lire`, en haut).
3. Noter combien de prises tombent entre 290 et 310 g. Si c'est moins d'une sur deux, la plage est trop
   étroite pour ce godet : dire à Claude quelle plage est acceptable pour les bocaux (`dose → plage_kg`).

## Étape 6 : un lot de 3 bocaux

Le geste automatique est écrit (`vidange/griffe/versement.py`) et, depuis la tâche 45 sexies, le programme
principal le construit sur la griffe des cartes (poste « versement » du mode bocaux). Le lot ne part que si les
autres postes du mode bocaux sont prêts (l'écran dit « pas lancé : raison » sinon). Pour l'essayer :

1. Rejouer d'abord sur le PC : `pytest -q pi/tests/test_versement_bocal.py` (tout doit passer).
2. Lot `bocal_1_2`, `bocal_1_3`, `bocal_2_1`, vitesses divisées par 4, Karulium à l'arrêt d'urgence.
3. Regarder à chaque bocal : prise, pesée en haut (la tête s'arrête un peu plus d'une seconde), trajet,
   descente, ouverture lente, attente, pesée, remontée de 2 cm, fermeture, remontée.
4. Journal (`journalctl -u vidange`) : une ligne « … kg versés dans le bocal … » par bocal. Peser les bocaux à
   la main : à 10 g près de ce que dit le journal.
5. Essayer les alertes, une à une :
   - **grains collés** : mettre une poignée de maïs collant (froid, tassé) dans le godet. La griffe doit secouer,
     ouvrir en grand, puis s'arrêter **godet ouvert** au-dessus de l'entonnoir, sans le refermer. Faire tomber
     les grains à la main, acquitter, Go : elle repèse et finit, **sans reprendre de dose** ;
   - **entonnoir bouché** : boucher la douille avec un bouchon de papier. Après le versement : alerte
     « entonnoir bouché », le bocal est noté « suspect » ; rien d'automatique. Déboucher, acquitter, Go : le lot
     continue ;
   - **coupure** pendant que le godet est ouvert : couper le courant de l'armoire. Au redémarrage et au Go, la
     griffe ne doit **jamais** reprendre une dose pour ce bocal.
6. Quand tout est bon : remettre les vitesses, passer à `false` le `exemple` des sous-parties réglées.

## Ce qu'il faut renvoyer à Claude

Les valeurs de B (étape 1), les 3 charges de l'étape 2, la hauteur des dents et le jeu au boîtier (étape 3), ce
qui reste dans le godet et ce qui a marché (étape 4), le nombre de prises dans la plage (étape 5), les vidéos.
