# Essai sur la vraie machine : alarmes des pilotes et dérive de position (tâches 24 et 24 bis)

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

## B. Câblage et essai des ALM, carte par carte (tâche 24 bis)

Depuis la tâche 24 bis, il y a **une seule entrée « alarme » par carte FluidNC** : les ALM de tous les
pilotes de la carte sont regroupés (réponse de l'Implantation du 09/11/2026).

| Carte | Entrée | Pilotes regroupés |
|---|---|---|
| 1 (portique) | `alarme_carte1` | X1, X2, Y, Z de la griffe, rotation A et godet B de la griffe : 6 |
| 2 (chariot) | `alarme_carte2` | avance, montée du plateau, rotation du plateau, pousseur, barre 1, barre 2 : 6 |
| 3 (mycélium, lavage) | `alarme_carte3` | le HBS86H de la manivelle (les TMC2209 n'ont pas d'ALM) : 1 |
| 4 (préhension) | `alarme_carte4` | Z de la préhension, rotation de la tête, noyau, couronne : 4 |

Le Pi sait **qu'un** pilote de la carte est en alarme, **pas lequel**. Pour le trouver : regarder les
voyants des pilotes de la carte (ou comparer la position demandée et la position lue, axe par axe).

### B.1. Comment la sortie ALM du pilote se comporte (à vérifier à la réception du pilote)

1. Machine hors tension. Avec un multimètre en continuité, sur la sortie ALM (optocoupleur) d'un pilote :
   - **ouverte en alarme** (conduit au repos) : monter les ALM de la carte **en série** (une alarme ou un
     fil coupé ouvre la boucle : sécurité positive, à préférer) ;
   - **conduit en alarme** : monter les ALM **en parallèle** (OU câblé ; un fil coupé ne se voit pas).
2. Noter le résultat ici : `__________`.
3. Régler le sens de la broche dans `fluidnc/<carte>.yaml` (`control → macroN_pin`) : avec `:low` si
   l'entrée est tirée vers le bas quand l'alarme est levée (montage en parallèle), sans `:low` dans
   le cas contraire (montage en série). Dans les deux cas, FluidNC doit montrer la lettre dans `Pn:`
   **quand une alarme est levée** et pas au repos. Si c'est l'inverse : changer `:low`.
   Si le sens change, mettre à jour aussi `repos` du signal dans `docs/entrees-sorties.yaml`.

### B.2. Essai d'une ALM, pilote par pilote

1. Lancer `vidange --verifier` : il doit dire « Réglages corrects » (la liste axe → alarme de
   `machine.yaml → pilotes` correspond à `fluidnc.yaml` ; un axe d'une autre carte sur la même entrée serait
   refusé).
2. Page web, état de la carte : repérer la lettre de l'alarme de la carte (`fluidnc.yaml → entrees →
   alarme_carteN`). Au repos, elle ne doit pas apparaître dans « Pn: ».
3. Pour chaque pilote de la carte (6 pour les cartes 1 et 2, 1 pour la 3, 4 pour la 4), lancer un petit
   geste de son axe (pilotage manuel). Pendant qu'il bouge, **retenir l'axe à la main** (ou bloquer
   légèrement l'outil) jusqu'à ce que le pilote lève son voyant ALM.
4. Attendu : le geste s'arrête, la page web affiche « alarme du pilote : un pilote de la carte ... (on ne
   sait pas lequel, regarder les voyants des pilotes) » avec le « quoi faire ». **Tous** les modules qui
   ont un axe de cette carte et qui sont en mouvement s'arrêtent (c'est voulu). Le voyant du pilote
   concerné est allumé : c'est lui qui dit lequel. Recommencer avec chaque pilote de la carte : la lettre
   de la carte est toujours la même.
5. Débrancher un fil d'ALM de la chaîne (câble coupé) : en série, la carte doit passer en alarme (sécurité
   positive) ; en parallèle, rien ne se voit (c'est le défaut de ce montage, à savoir).
6. Dégager, couper puis remettre le courant du pilote, acquitter, donner le Go.
7. Si une ALM ne se voit pas : regarder le câble, le sens (`:low`) et la lettre dans `fluidnc.yaml`.

## C. Remise à zéro de l'ALM de la rotation de la tête (vissage)

Pendant le pas « cale » (vissage du couvercle percé), le moteur de la rotation cale **exprès** : le pilote
lève son ALM, donc l'entrée `alarme_carte4`. Cette alarme est **attendue** : pendant ce pas, elle ne met pas
la machine en alarme, et elle **masque aussi les 3 autres pilotes de la carte n° 4** (Z de la préhension,
noyau, couronne), qu'on ne peut pas séparer. Une vraie alarme d'un de ces 3 pilotes pendant le vissage ne
serait donc pas vue tout de suite : elle l'est dès le pas suivant (après la remise à zéro, si elle est
toujours là, la machine s'arrête).

1. **Essayer d'abord d'éviter l'alarme** : si le pilote le permet, régler son seuil d'erreur de position
   (partie A) assez large pour que le calage voulu ne l'atteigne pas, ou limiter son courant pendant le
   vissage. Si l'alarme n'est plus levée, le pas « cale » ne s'arrête plus par l'ALM : à revoir avec
   Claude (le vissage se termine alors autrement).
2. **1er essai de la remise à zéro : `$MD` puis `$ME`.** ENA de chaque pilote est câblé sur la sortie
   « disable » de sa carte FluidNC (Implantation, 09/11/2026), donc ces lignes (réglage `pilotes →
   remise_a_zero → lignes`, un exemple) coupent puis rendent l'enable. Les essayer dans le terminal de la
   carte n° 4 (`vidange-fluidnc console prehension`) après avoir fait caler le moteur : le voyant ALM doit
   s'éteindre et la lettre de `alarme_carte4` disparaître de « Pn: ». **Attention : `$MD` coupe le courant
   de TOUS les moteurs de la carte n° 4**, dont le Z de la préhension (son frein à manque de courant
   le tient) : le faire tête basse libre de tout, quelqu'un au bouton d'arrêt d'urgence.
3. **Beaucoup de pilotes du commerce n'effacent leur ALM qu'en coupant leur alimentation.** Si le voyant
   reste allumé après `$MD` puis `$ME` : noter `__________` et passer au point 4.
4. **2e essai : couper 2 s le +48 V du SEUL pilote de la rotation de la tête**, par `relais_1` K3
   (signal `reset_pilote_rotation_prehension`, réservé par l'Implantation). Matériel à monter : un relais DIN à
   contact **repos** (fermé au repos) dans le +48 V de ce pilote, bobine commandée par K3 (24 V) ; commandé =
   coupé. **Jamais K1** (il couperait tous les moteurs de la machine). L'angle de la tête est retrouvé par le
   capteur Hall et le potentiomètre 10 tours. Une fois monté, l'essayer à la main (machine à l'arrêt, sans
   mouvement) : K3 commandé, le pilote de la rotation s'éteint ; K3 relâché, il se rallume sans alarme.
   Puis, dans `machine.yaml → pilotes → remise_a_zero → coupure`, passer `actif` à `true` (régler au
   besoin `duree_s`, 2 s, et `attente_retour_s`) : le Pi ne coupe le courant que si les lignes du point 2 n'ont
   pas suffi.
5. Faire un vrai vissage du couvercle percé sur un bocal neuf (procédure `essai-bocal-neuf.md`).
   Attendu : le moteur cale, le pilote lève ALM, le geste s'arrête **sans alarme du chef** (c'est voulu),
   puis le geste suivant remet l'ALM à zéro (point 2, puis 4 si activé) et repart. Si l'ALM ne retombe pas
   dans `delai_max_s` (même après la coupure du courant), la machine s'arrête et dit de couper puis remettre
   le courant du pilote à la main.
6. Quand cela marche : passer `remise_a_zero → exemple` à `false`.

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
