# Essai du micropore sur le vrai matériel (tâche 40)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent qu'un faux boîtier, une fausse tête et
une fausse caméra. Cet essai se fait **après la tâche 40 bis** : la carte de pesée du plateau du remplissage a
son programme avec l'I2C, la PCA9685 et le VL6180X sont câblés et ont été essayés seuls
(`pesee/essai-boitier-chariot.md`). Durée : environ 2 h 30.

Le micropore ne protège personne. La tête est petite et l'enceinte est fermée ; le verrou « tête escamotée »
protège seulement la tête et le seau. Pendant tout l'essai, l'arrêt d'urgence reste câblé comme d'habitude.
L'outil `vidange-micropore` **ne bouge jamais le plateau** : c'est `vidange-remplissage` qui le bouge, et
vous lui dites que la tête est escamotée (`--micropore-rentre`) seulement après l'avoir vue en arrière, à l'œil.

Il faut : la tête du micropore montée sur le chariot, ses 2 servos et son capteur de distance branchés au
boîtier du chariot, le moteur d'avance branché à la carte FluidNC n° 3, un rouleau de micropore, un seau vide
de chaque format (A, B, C, D), un réglet, un feutre, un rapporteur (ou une marque tous les 10° sur le plateau).

## Avant de commencer

1. Arrêter le programme principal : `sudo systemctl stop vidange`.
2. Rien sur le plateau du chariot. Ruban **pas encore passé** dans la tête.
3. Tous les essais se lancent ainsi (on écrit plus bas seulement la fin de la ligne) :
   `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-micropore ...`
4. Les gestes appris vont dans `/opt/vidange-auto/pi/donnees/micropore-appris.yaml`. **Ne pas l'écrire à
   la main** : l'outil le fait, et note chaque changement (quand, qui, avant, après). Ajouter `--qui gael`
   (par exemple) pour dire qui apprend ; sinon c'est « karulium ».

## Étape 1 : le boîtier répond

1. Lancer `etat`. Attendu : « ToF … mm (état 0)  démarrages N  servo_escamotage_micropore coupée,
   servo_lame_micropore coupée, servo_fermeture_seaux coupée », puis « Escamoté : pas appris ».
2. Si « ne répond pas » ou « registre inconnu » : la carte du plateau n'a pas le programme de la tâche 40 bis,
   ou pas le bon réglage. Le signaler.
3. Mettre la main devant le capteur de distance, relancer `etat` : la distance change. Si c'est toujours « pas
   de mesure » ou un état différent de 0 : vérifier le câble du capteur (tâche 40 bis).

## Étape 2 : l'angle « escamoté »

1. Lancer `servo 40`. La tête bouge, la ligne dit la distance du ToF. **Regarder la tête** : est-elle tout en
   arrière, sans forcer (le servo ne grogne pas) ?
2. Essayer quelques angles autour (`servo 35`, `servo 45`…) jusqu'à trouver le plus en arrière **sans
   forcer**. Si les angles montent et que la tête **recule**, le sens est à l'envers : dans
   `pi/reglages/machine.yaml`, partie `micropore → servos`, mettre `sens_avance: -1`.
3. Noter la distance lue tête en arrière. Si elle est loin de 77 mm, l'écrire dans `micropore → tof →
   escamotee_mm` (puis relancer `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange --verifier`).
4. Apprendre l'angle : `escamote 40` (avec l'angle trouvé). Attendu : « Escamoté appris : 40° (ToF 77 mm),
   changement n° 1 ». Si « pas vue escamotée » : rien n'est appris ; revoir le point 3.

## Étape 3 : les millimètres par degré

1. Sans rien devant la tête, lancer `servo` avec l'angle escamoté, puis l'angle + 10° (exemple : `servo 40`
   puis `servo 50`). Noter les 2 distances.
2. (première distance − deuxième) ÷ 10 = mm par degré. L'écrire dans `micropore → servos → mm_par_degre`
   s'il est loin de 0,785. Vérifier : `vidange --verifier`.
3. Aller doucement vers l'avant (`servo 60`, `servo 70`…) jusqu'à la butée de la glissière, sans forcer.
   Noter la distance : c'est `tof → butee_mm` (≈ 8 mm). Revenir : `escamote 40`.

## Étape 4 : le redémarrage de la carte

1. Lancer `servo 50` (tête un peu en avant), puis `etat` : noter le nombre « démarrages ».
2. Couper puis remettre l'alimentation de la carte du plateau (ou son bouton RESET).
3. Relancer `etat` : le nombre « démarrages » a **changé** et les servos disent « coupée ». C'est ce que le
   programme principal voit : il renvoie alors tout de suite les angles et ne croit le capteur de distance
   qu'une seconde plus tard (`servos → stabilisation_s`).
4. Regarder la tête pendant la coupure : si elle part toute seule (ressort, gravité), le dire : le programme
   la remet en arrière et relit le ToF avant de bouger le plateau, mais un morceau en cours sera refait.
5. Remettre la tête : `escamote 40` (cela note un 2e changement identique, ce n'est pas grave), ou
   `servo 40`.

## Étape 5 : la lame

1. Ruban **pas** passé. Lancer `lame` : la lame descend, puis remonte.
2. Si elle ne descend pas assez bas ou force en bas, changer `servos → lame_bas_deg` (38 d'exemple) ; si elle
   n'est pas bien en haut au repos, `servos → lame_repos_deg` (145). Les deux doivent rester dans la plage de
   la voie `servo_lame_micropore` de `pesees.yaml` (vérifié au démarrage). Recommencer jusqu'à une coupe nette.
3. Si la lame n'a pas le temps de descendre, augmenter `servos → lame_s` (0,16 s).

## Étape 6 : le moteur d'avance (carte FluidNC n° 3, lettre X)

1. Charger le réglage de la carte n° 3 mis à jour (`fluidnc/mycelium_lavage.yaml`, axe `x`) comme à la
   tâche 19 (`fluidnc/README.md`).
2. Passer le ruban dans la tête (presseur ouvert, ruban sous le pignon, presseur refermé). Faire un trait au
   feutre sur le ruban au ras de la lame.
3. Lancer `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc console mycelium_lavage`, puis
   taper `G91 G1 X13 F1200`, `G90`, `fin`. Le ruban sort de 13 mm : mesurer au réglet depuis la lame.
4. S'il sort d'une autre longueur : `steps_per_mm` de l'axe `x` × 13 ÷ (longueur mesurée), dans
   `fluidnc/mycelium_lavage.yaml`, recharger, recommencer. S'il **rentre**, inverser le sens du moteur
   (`direction_pin` : ajouter ou enlever `:low`).
5. `G91 G1 X-0.5 F1200` puis `G90` : le ruban recule d'un petit cran (la tension avant la coupe).
6. Taper `quitter`. Couper le bout sorti (`lame`).

## Étape 7 : apprendre un format de seau (à faire pour A, B, C et D)

1. Avec `vidange-remplissage` (procédure `essai-remplissage.md`), poser un seau vide du format sur le plateau,
   chariot au poste (y 0,135). Tête **vue escamotée à l'œil** avant chaque mouvement du plateau, et
   seulement alors l'option `--micropore-rentre`.
2. Monter le plateau pour que la rangée **du haut** soit devant le rouleau :
   `plateau` à (0,591 − hauteur de la rangée), la hauteur étant dans `micropore → formats → seau_… → rangees`.
   Exemple seau A : 0,591 − 0,19 = 0,401.
3. Marquer au feutre, sur la paroi, l'endroit en face du rouleau.
4. Tourner le plateau (`vidange-remplissage … tourner 10` plusieurs fois) jusqu'à voir la marque **au
   centre** de l'image de la caméra du micropore (`vidange-vision photo micropore /tmp/m.jpg`, regarder la
   photo). Additionner les degrés tournés : c'est l'angle caméra → rouleau (≈ 32° d'exemple). Retourner la
   marque devant le rouleau (même nombre de degrés, dans l'autre sens).
5. Lancer `apprendre seau_a --camera-rouleau 32` (avec le format et l'angle trouvé). **Depuis la tâche 40 ter**,
   l'option n'est plus obligatoire : sans elle, la vision donne l'angle (géométrie de `vision.yaml → inspection`,
   voir `vidange-vision rouleau seau_a`). Comparer avec l'angle mesuré aux points 3 et 4 : si l'écart dépasse 2°,
   garder l'option pour forcer la valeur mesurée, et le dire dans la PR (`essai-inspection.md`, étape 6). La tête avance d'un
   demi-degré à la fois (≈ 30 s), s'arrête quand le capteur ne voit plus la distance baisser, puis recule.
   Attendu : « seau_a appris (changement n° …) : contact à …° (ToF … mm), approche …°, appui …° ».
6. Si « butée sans toucher de paroi » : le seau n'est pas devant la tête (plateau trop bas ou trop haut, seau
   pas au centre). Si « gestes pas appris » : l'ordre des angles est faux (sens de l'avance : étape 2).
7. Vérifier à l'œil : `servo` à l'angle d'approche affiché : le rouleau est à ≈ 2 mm de la paroi. `servo` à
   l'angle d'appui : le rouleau appuie, le ressort est un peu écrasé. Revenir avec `escamote` (angle appris)
   ou `servo` (angle escamoté).
8. Une erreur ? `annuler` défait le dernier changement ; `historique` les montre tous.
9. Recommencer pour la rangée du fond **sans réapprendre** (même seau, même tête : le contact est le même au
   millimètre près). Si la tête ne touche pas la rangée du fond au même angle (seau très conique), le dire :
   on apprendra par rangée.

## Étape 8 : le compteur du rouleau

1. Rouleau neuf passé, presseur refermé : lancer `charger`. La lame coupe une fois, la ligne dit « compteur à
   300 morceaux. Changer aussi le morceau de lame ».
2. Le programme principal compte chaque coupe et alerte une fois sous 150 morceaux (`micropore → rouleau`).

## Étape 9 : `etat` final

1. Lancer `etat` : l'angle escamoté et les 4 formats sont listés, sans ligne « À REVOIR ».
2. `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange --verifier` : « Réglages corrects ».
3. Passer `micropore → exemple` à `false` quand tous les chiffres marqués EXEMPLE ont été vus (hauteurs et
   rayons des rangées mesurés sur les vrais seaux, distances du ToF, vitesses, sens de rotation).

## Ce qui ne peut pas encore s'essayer

- **La pose dans un vrai cycle** : le programme principal ne branche pas encore le Remplissage ni le
  micropore (comme pour les tâches 34 et 39). Quand ce sera fait, essayer d'abord un seau A vide en mode
  pas à pas : tour de repérage, puis pour chaque trou approche, avance, appui, pose, coupe, contrôle.
- **La caméra** : le repérage des trous et le contrôle des morceaux par l'image sont écrits (tâche 40 ter) ; ils
  s'essaient avec `essai-inspection.md`. Dans un vrai cycle, ils attendent les cartes du chariot et de la tête
  branchées au programme principal.
- **Le bouton « rouleau » à l'écran** (plateau en bas, barres serrées, tête escamotée) : à venir avec
  l'écran ; `charger` remet le compteur à neuf.

Noter les chiffres trouvés et les remarques dans la PR, ou les donner à la prochaine session.
