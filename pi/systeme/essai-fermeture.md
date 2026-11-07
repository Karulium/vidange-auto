# Essai de la fermeture des seaux sur le vrai matériel (tâche 41)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent qu'un faux boîtier, un faux
couvercle et une fausse balance. Cet essai se fait **après la tâche 40 bis** (la carte de pesée du plateau a
son programme avec l'I2C et la PCA9685 : `pesee/essai-boitier-chariot.md`) et après l'essai du chariot de
remplissage (`essai-remplissage.md`, balance étalonnée). Compter 2 à 3 heures.

La fermeture ne protège personne. Le servo est faible (environ 15 N au rouleau) et il tourne **à vide** ; la
force qui ferme vient du **plateau**, limité par ses propres protections câblées (fin de course haut du
plateau dans la chaîne d'arrêt). Pendant tout l'essai, l'arrêt d'urgence reste câblé comme d'habitude. Garder
les mains **loin du bras, du rouleau et du couvercle** quand le plateau monte ou tourne.

Il faut : le bras monté sur le poteau du chariot (rouleaux de silicone en place), le servo DS3225 alimenté par
`bec_servo` (6,8 V) avec son signal sur la voie 2 de la PCA9685, un seau de chaque format (A, B, C, D) **avec
son couvercle**, un réglet, un feutre.

## Avant de commencer

1. Arrêter le programme principal : `sudo systemctl stop vidange`.
2. Dans les commandes ci-dessous, `vidange-fermeture` et `vidange-remplissage` veulent dire
   `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fermeture` (et de même pour l'autre).
3. Les chiffres à trouver sont dans `pi/reglages/machine.yaml`, partie `fermeture` (tous marqués EXEMPLE sauf
   ceux de la fiche). Après chaque changement : `vidange --verifier` doit dire « Réglages corrects ».
4. **Le plateau en bas d'abord.** Le bras ne tourne que plateau assez bas, et son tout premier ordre après une
   coupure se donne plateau tout en bas. Faire le zéro de la montée (prise d'origine de la carte du chariot,
   comme dans `essai-remplissage.md`), regarder le plateau en bas, puis ajouter `--plateau-bas` aux commandes
   du bras : sinon l'outil refuse.

## Étape 1 : le servo répond

1. `vidange-fermeture etat`. Attendu : « Servo : coupé (jamais ordonné depuis le démarrage de la carte) »,
   puis « Réglages : butée 200°, rangé 40°, travail 202.5° ».
2. Si « ne répond pas » : la carte du plateau n'a pas le programme de la tâche 40 bis. Le signaler.

## Étape 2 : étalonner le bras (butée, sens)

L'angle de l'axe du servo où le **doigt touche le plat des paliers** s'appelle la butée. C'est lui qui fixe
tout le reste : travail = butée + 2,5°, rangé = butée − 160°.

1. Plateau en bas. Dégager le bras de tout (pas de couvercle). Lancer `vidange-fermeture --plateau-bas servo
   150`. Le servo prend cet angle **tout de suite** (c'est le premier ordre, le bras part d'où il est).
2. **Regarder le bras de dessus.** Il doit tourner **en sens trigo** (inverse des aiguilles d'une montre) quand
   l'angle augmente. S'il tourne dans l'autre sens, mettre `sens_servo: -1` dans `fermeture → bras`
   (et chercher la butée dans l'autre sens, angles qui baissent).
3. Avancer par petits pas : `servo 170`, `servo 180`, `servo 190`, puis de 1° en 1° dès que le doigt s'approche
   du plat. S'arrêter **au premier contact** du doigt sur le plat (le servo ne grogne pas, le bras ne force
   pas). Noter l'angle : c'est la butée. Revenir 5° en arrière tout de suite.
4. L'écrire dans `fermeture → bras → butee_servo_deg`. `vidange --verifier` : « Réglages corrects ». Si
   « hors de la plage » : l'angle rangé (butée − 160) ou travail (butée + 2,5) sort des 0 à 270° du servo ;
   si la butée est en dessous de 160°, le montage du bras est à revoir (le dire dans la PR).
5. `vidange-fermeture --plateau-bas ranger` : le bras part en rampe (1 s environ) et finit **couché vers
   l'allée**. Est-ce bien l'endroit rangé, sans toucher le bac du retourneur ni rien d'autre ? Sinon, le dire.
6. `vidange-fermeture --plateau-bas travail` : le bras vient poser le doigt sur son plat, **sans forcer**
   (surcourse de 2,5° : le servo appuie un peu). Revenir avec `ranger`.
7. Le signal reste envoyé après la fin de l'outil (la carte garde l'angle) : le bras ne doit pas se relâcher.

## Étape 3 : la carte redémarre (bras au travail)

1. `vidange-fermeture --plateau-bas travail`, puis `etat` : noter « démarrages ».
2. Couper puis remettre l'alimentation de la carte du plateau. `etat` : « démarrages » a **changé** et le servo
   est « coupé ». Regarder le bras : tombe-t-il ou reste-t-il ? (Le dire dans la PR.)
3. `vidange-fermeture --plateau-bas ranger` : premier ordre « sans rampe » (c'est normal après un
   redémarrage). Le bras revient.

## Étape 4 : le sens horaire du plateau

1. Avec `vidange-remplissage` (sans seau) : `tourner -30`. **Regarder le plateau de dessus** : tourne-t-il dans
   le sens des aiguilles d'une montre ?
2. Si oui : `rotation → sens_horaire: -1` (valeur d'exemple) est bon. Si non (il tourne en trigo), mettre
   `sens_horaire: 1`. **Ce réglage est important** : le Pi refuse tout sens trigo pendant que le couvercle
   touche le rouleau, et ne tourne qu'en sens horaire pour clipser.
3. Remettre le plateau à son angle (`tourner 30` dans l'autre sens).

## Étape 5 : mesurer Hf et Hc sur chaque vrai seau

Les hauteurs de la fiche (Hf : A 0,201, B 0,251, C 0,214, D 0,194 ; Hc = Hf − 0,006) viennent de la
géométrie. Il faut les vérifier une fois sur chaque format.

1. Poser le seau (vide ou plein) sur le plateau, **son couvercle posé dessus à la main, pas clipsé**. Chariot
   au y de la fermeture (`fermeture → chariot_y`, 0,50 d'exemple), barres ouvertes, plateau en bas.
2. Bras **au travail** (`travail`). Garder la main sur l'arrêt d'urgence.
3. Monter le plateau par petits pas : `vidange-remplissage --manivelle-en-bas --micropore-rentre plateau
   0.185`, puis 0.190, 0.192…, en lisant la ligne « balance » de `etat` à chaque pas. Le couvercle touche le
   rouleau quand la balance **augmente** : noter la hauteur. C'est Hc.
4. Continuer de 1 mm en 1 mm : le couvercle s'enfonce de 6 mm environ et **se clipse** (un « clac »). Noter la
   hauteur du clic : c'est Hf. Ne pas dépasser la balance de 15 kg de plus (150 N).
5. Redescendre, ranger le bras. Écrire Hf dans `fermeture → formats → seau_… → hf_m`, et si l'enfoncement
   n'est pas de 6 mm, `montee → enfoncement_clip_m`. `vidange --verifier`.
6. Recommencer pour A, B, C et D.

## Étape 6 : la fermeture entière, un format après l'autre

1. Seau et couvercle comme à l'étape 5 (couvercle posé, pas clipsé). Réduire d'abord les efforts pour le
   premier essai : `montee → force_max_n: 60` (remettre 150 après).
2. Lancer :
   `vidange-remplissage --manivelle-en-bas --micropore-rentre --prehension-loin fermer seau_a`.
   (`--prehension-loin` = « je vois que la préhension a lâché le couvercle et qu'elle est remontée, ou partie
   ailleurs » : l'outil ne connaît pas la préhension, et sans cette phrase le bras reste rangé. Dans le vrai
   programme, c'est le logiciel qui le sait : il ne sort le bras que préhension lâchée et au-dessus de
   `fermeture → prehension_libre_z`. De même, le chariot ne roule pas tant que le bras n'est pas vu rangé.)
   L'outil fait comme le programme au démarrage : plateau tout en bas, bras rangé (sans rampe), puis plateau
   à l'approche, chariot au y de la fermeture, bras au travail, pesée, montée lente jusqu'au contact, montée
   jusqu'à Hf, **2 tours en sens horaire**, descente, bras rangé.
3. **Vérifier à la main que le bras ne touche rien** : plateau à l'approche, chariot au y de la fermeture, tourner
   le bras lentement (`vidange-fermeture --plateau-bas servo ...` par petits angles) et regarder qu'aucune pièce
   ne le touche. Il balaie un disque de rayon ≈ 0,15 m autour de son axe (repère du chariot x 0,09 ; y 0,293), à
   z 0,51-0,55 ; au y 0,50, le calcul du Remplissage (géométrie B1, pas un balayage de la Maquette) ne trouve
   rien de fixe dans cette zone : à confirmer à la main.
4. Regarder : le couvercle est-il clipsé **tout le tour** ? Si un coin reste ouvert, augmenter
   `rotation → tours` (2 d'exemple) ou ralentir `tr_min`.
5. Le journal et la sortie disent l'effort au clipsage (« couvercle clipsé à Hf, effort … N »). Noter-le : il
   permet de choisir `force_max_n` (au moins 1,5 fois cet effort, jamais plus de 200 N : refusé au démarrage).
6. Retirer le couvercle (de l'effort noté ci-dessus dépend la facilité) et recommencer pour B, C, D.

## Étape 7 : les erreurs, une par une

1. **Pas de couvercle** sur le seau : « pas de contact : bras pas au travail ou couvercle absent ». Le plateau
   redescend à l'approche, le bras se range. Le seau est marqué « fermeture à vérifier » au registre.
2. **Couvercle de travers** (un bord posé sur l'anse) : « couvercle mal posé … contact trop tôt ».
3. **Effort trop grand** : mettre temporairement `force_max_n: 20` et fermer : « couvercle bloqué », le plateau
   s'arrête et redescend. Remettre la bonne valeur.
4. Après chaque erreur, le bras est **rangé** et le plateau à l'approche. Si le message dit « le couvercle reste
   contre le rouleau », dégager le couvercle **à la main sans toucher au bras**, puis relancer.

## Étape 8 : fin

1. `vidange --verifier` : « Réglages corrects ».
2. Passer `fermeture → exemple` à `false` quand tous les chiffres marqués EXEMPLE ont été vus (butée, sens du
   servo, rampe, sens horaire, tours, efforts, y de la fermeture, Hf et Hc des 4 formats).

## Ce qui ne peut pas encore s'essayer

- **Le cycle complet** : la pose du couvercle sur le seau par la préhension n'est pas encore un geste du
  programme (elle viendra avec le solveur) et le programme principal ne branche pas encore le Remplissage
  (comme pour les tâches 34, 39 et 40). Ici, le couvercle est posé à la main.
- **Le mode couvercles** : le bras reste rangé et ne reçoit aucun ordre pendant tout le mode ; à vérifier au
  premier essai du mode couvercles (`essai-remplissage.md`) : à −40° le bras toucherait le bac du retourneur.
- **L'arrêt d'urgence** : s'il coupe le 24 V du chariot (donc le bec du servo), le bras se relâche. Au
  redémarrage, le programme refait : zéro de la montée, puis bras rangé, puis le reste. À essayer une fois
  quand l'Implantation aura dit ce que coupe l'arrêt.

Noter les chiffres trouvés et les remarques dans la PR, ou les donner à la prochaine session.
