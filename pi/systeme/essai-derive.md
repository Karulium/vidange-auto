# Essai sur la vraie machine : alarmes des pilotes et dérive de position (tâche 24)

Testé sur le vrai matériel : **non**. GitHub Actions ne teste que des faux (faux FluidNC qui lève une
ALM et qui glisse d'un nombre de mm donné). Cette procédure est à faire une fois, machine à l'arrêt,
avec quelqu'un à côté du bouton d'arrêt d'urgence. Les ALM protègent la machine, jamais les personnes.

## A. Régler le seuil d'erreur de suivi SUR LE PILOTE (une fois par pilote)

Le Pi ne lit jamais la position du codeur : c'est le pilote qui décide quand il « n'y arrive plus ».

1. Machine hors tension (arrêt d'urgence enfoncé). Ouvrir le réglage du pilote (interrupteurs ou
   logiciel du fabricant, selon le modèle ; pour le CL57T : le réglage « position error alarm »).
2. Mettre le seuil d'erreur de suivi. Pour la **rotation de la tête** (vissage du couvercle percé) :
   environ 2° pendant 0,2 s (valeurs de `bocal_neuf → cale` dans `pi/reglages/machine.yaml`, à titre
   d'exemple : le code ne les lit pas). Pour les autres axes : un seuil large (quelques mm) pour
   ne pas lever d'alarme dans une accélération normale.
3. Noter ce que vous avez réglé ici : `__________`.

## B. Essai d'une ALM, axe par axe

1. Lancer `vidange --verifier` : il doit dire « Réglages corrects » (la liste axe → alarme de
   `machine.yaml → pilotes` correspond à `fluidnc.yaml`).
2. Page web, état de la carte : repérer la lettre d'alarme de l'axe (`fluidnc.yaml → entrees →
   alarme_...`). Au repos, elle ne doit pas apparaître dans « Pn: ».
3. Pour chaque axe, lancer un petit geste de cet axe (pilotage manuel). Pendant qu'il bouge, **retenir
   l'axe à la main** (ou bloquer légèrement l'outil) jusqu'à ce que le pilote lève son voyant ALM.
4. Attendu : le geste s'arrête, la page web affiche « alarme du pilote : pilote de l'axe ... » avec
   le « quoi faire ». Pour les axes dont les alarmes sont câblées ensemble sur une même entrée
   (chariot de remplissage), la page dit « l'un des pilotes ... ».
5. Dégager, couper puis remettre le courant du pilote, acquitter, donner le Go.
6. Si une ALM ne se voit pas : regarder le câble et la lettre dans `fluidnc.yaml`.

## C. Remise à zéro de l'ALM de la rotation de la tête (vissage)

1. Dans `pi/reglages/machine.yaml → pilotes → remise_a_zero`, les lignes sont un **exemple** (`$MD` puis
   `$ME` : couper puis remettre l'enable du pilote). Vérifier dans la doc de FluidNC (ou en tapant ces
   lignes dans le terminal de la carte n° 4) qu'elles coupent bien le courant du moteur de la
   rotation puis le rendent. Si ce n'est pas le cas : changer les lignes, ou noter qu'il faut couper
   le courant du pilote à la main (question 1 de la PR).
2. Faire un vissage du couvercle percé sur un bocal neuf (procédure `essai-bocal-neuf.md`).
   Attendu : le moteur cale, le pilote lève ALM, le geste s'arrête **sans alarme du chef** (c'est voulu),
   puis le geste suivant remet l'ALM à zéro et repart. Si l'ALM ne retombe pas dans
   `delai_max_s`, la machine s'arrête et dit de couper puis remettre le courant du pilote.
3. Quand cela marche : passer `remise_a_zero → exemple` à `false`.

## D. Contrôle d'origine contre la dérive (désactivé par défaut)

La méthode : l'axe va 20 mm avant son fin de course d'origine (EXEMPLE), puis avance lentement vers lui ;
dès que le fin de course s'allume, le Pi lit la position que croit FluidNC. L'écart avec la position
attendue du capteur est la dérive. Elle suppose que FluidNC laisse l'axe **passer son fin de course
d'origine à la main**, ce qui peut être refusé par `soft_limits: true` de `fluidnc/portique.yaml`.
C'est pourquoi `derive → actif` est `false`.

1. Choisir un axe (exemple dans `machine.yaml → derive → axes → chariot_y`). Après une prise d'origine, lire
   dans la page web la position quand le fin de course s'allume en avançant à la main très lentement :
   c'est `position_capteur` (en m). Régler `sens`, `distance_depart` (plus grande que `seuil_arret`),
   `vitesse` (précision = vitesse × 0,2 s).
2. Essai à blanc : tester dans le terminal de la carte, axe libre, la ligne `$J=G53 G90 Y31 F120`
   (Y en mm). Si la carte répond « error » ou s'arrête au seuil de course : l'approche n'est pas
   possible tel quel (question 4 de la PR).
3. Si elle marche : passer `derive → actif` à `true`, lancer un lot de test. Le contrôle se fait avant les
   seaux (module « controle_origine », après le Go habituel).
4. Faire glisser la courroie volontairement de 3 mm (desserrer un peu, décaler l'axe à la main) :
   attendu, une alerte « dérive de position » dans le journal et la check-list, sans arrêt.
   Avec plus que `seuil_arret` : arrêt propre du module, avec « quoi faire ».
5. Puis passer `derive → exemple` à `false`.
