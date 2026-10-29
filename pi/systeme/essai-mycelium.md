# Essai du mycélium sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent qu'un
**faux** FluidNC, une **fausse** balance et un bocal, un porte-bocal et un chariot de remplissage
**imaginaires** (simulateur).

Cette procédure ne peut se faire qu'**après la tâche 20** (Porte-bocal : demi-tour du bocal), **la
tâche 22 bis** (carte de pesée RS485 du plateau du chariot de remplissage) et une fois la carte FluidNC
n° 3 câblée (glissière X, manivelle A). Elle sert à **mesurer les chiffres marqués EXEMPLE** dans
`pi/reglages/machine.yaml` (partie `mycelium`, et `mycelium_kg` des formats), puis à faire un premier
dosage lent, Karulium à côté de l'arrêt d'urgence. Compter une demi-journée.

La sécurité des personnes est câblée (arrêt d'urgence, portes). Les verrous du logiciel (agitateur et
chariot de remplissage, caméra du dosage) ne protègent que la machine : pendant les essais, garder la
main sur l'arrêt d'urgence.

## Avant de commencer

- Le fichier `fluidnc/mycelium_lavage.yaml` est complété avec les **vraies broches** (plan de câblage)
  et les **vrais pas par mm** (réglage des pilotes, poulie de la courroie GT2), puis envoyé à la carte
  (page web → « Mises à jour »). Tant qu'il dit « EXEMPLE », ne pas l'envoyer.
- La position machine de la carte est **dans le repère du portique** : X = position de l'agitateur
  (mm, 565 au garage, 925 au dosage). A = angle du moteur de la manivelle (°) : FluidNC ne sait pas
  où est le haut, c'est le Pi qui le trouve (prise d'origine de la manivelle, tâche 20 :
  `essai-porte-bocal.md`, étape 1). Ci-dessous, « H » = l'angle du moteur manivelle en haut que
  cette étape a donné.
- La bielle est dans le trou de **4 cm** pour commencer, et `course_agitation_m: 0.04` dans
  `machine.yaml` (le Pi ne voit pas le trou : c'est ce réglage qu'il croit).
- Pas de bocal dans le porte-bocal pour les étapes 1 et 2.

Dans les commandes ci-dessous, `vidange-fluidnc` veut dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc`.

## Étape 1 : prise d'origine et repère

1. Lancer la console de la carte : `vidange-fluidnc console mycelium_lavage`.
2. Envoyer `$H`. La glissière doit rouler vers le garage et s'arrêter sur son fin de course (la
   manivelle ne bouge pas : son origine est prise par le Pi). Envoyer `?` : `MPos` doit dire X = 565.
3. Faire la prise d'origine de la manivelle (`essai-porte-bocal.md`, étape 1) et noter H.
4. Manivelle en haut : `$J=G53 A<H> F3600` : elle doit être **pile en haut** (bocal au plus haut) ;
   sinon, corriger `manivelle → origine → decalage_deg`. Manivelle en bas : `$J=G53 A<H + 180> F3600`.
5. Glissière : `$J=G53 X865 F3000`. Mesurer au mètre : l'agitateur doit être **au demi-tour**
   (x 0,865 dans le repère du portique). Puis `$J=G53 X925 F3000` : le bocal doit être **au-dessus de
   l'axe du seau** (x 0,925), sans toucher le fin de course du dosage. Sinon, corriger les pas par mm.
6. Revenir au garage : `$J=G53 X565 F3000`.

## Étape 2 : les verrous, à vide

Le chariot de remplissage n'étant pas encore écrit (module Remplissage), ces verrous se vérifient
par les tests automatiques. Sur la machine, vérifier seulement à l'œil, en déplaçant à la main :

1. Chariot de remplissage à y 0,375 (ou plus) : l'agitateur roule sans rien toucher.
2. Agitateur au dosage, manivelle en bas : le chariot passe sous le bocal sans le toucher, jusqu'à
   y 0,155, plateau à 0,53 m (seau A) puis à 0,575 m (seau de 5 L).
3. Au garage, **bielle dans le trou de 7 cm**, bocal vide en place : faire tourner la manivelle à la
   main, très lentement, et regarder le fond du bocal : il doit passer **au-dessus de la marche du poste
   du fût** (z 0,88). Ne pas essayer le trou de 10 cm au garage : le fond toucherait la marche (c'est
   pourquoi le Pi refuse de tourner au garage avec `course_agitation_m: 0.10`).

## Étape 3 : la balance du plateau

1. Seau vide sur le plateau, chariot au dosage : lire la balance (outil de la tâche 22 bis). Noter la
   valeur.
2. Poser 100 g dans le seau : la balance doit monter de 100 g (± 2 g).
3. Faire tourner la manivelle sans bocal, à 120 tr/min (`$J=G53 A<H + 43380> F43200`), et regarder les
   lectures : elles bougent un peu (vibrations). L'écart le plus fort, multiplié par 3, est un bon
   départ pour `pesee → saut_kg` (0,3 kg dans l'exemple). Arrêter : `0x85` (bouton « Arrêt » de la
   console) puis `$J=G53 A<H + 180> F3600`.

## Étape 4 : premier dosage

1. Bocal plein dans le porte-bocal, seau A vide sur le plateau.
2. Lancer un dosage d'une couche depuis la page web (essai du module « mycelium »), vitesses de
   l'exemple. Regarder :
   - le chariot s'écarte, l'agitateur roule au demi-tour, manivelle en bas, le bocal se retourne,
     manivelle en haut, roule au dosage, manivelle en bas ;
   - le chariot revient, la casse du bloc (5 s, 200 tr/min), puis l'agitation ;
   - la manivelle s'arrête **pile en bas** quand la dose est atteinte ;
   - le chariot repart, manivelle en haut, roule au demi-tour, manivelle en bas, bocal remis
     debout, manivelle en haut, retour au garage.
3. Peser le seau sur une balance de cuisine : comparer à la dose notée dans le journal
   (« Mycélium : seau ..., couche 1 : ... g »). Si la dose dépasse souvent, augmenter
   `dose → arret_avant_kg` (grains qui tombent pendant l'arrêt).
4. Chercher la vitesse d'agitation : monter `vitesses → agitation_tr_min` par paliers (120, 160,
   200...) tant que les grains tombent mieux et que rien ne force. Noter le temps d'une couche.
5. Régler `dose → temps_max_s` à 2 fois le temps d'une couche normale.
6. Bocal presque vide : vérifier l'alarme « poids qui ne monte plus » au bout du temps maximal, et que
   le seau est marqué « pas bon » dans le registre.

## Étape 5 : un bocal pour 2 petits seaux

1. Deux seaux de 5 L, de la même variété : vérifier que le bocal reste dans le porte-bocal entre les
   deux (remis debout, retour au garage pendant que le chariot change de seau, nouveau demi-tour).
2. Vérifier que la casse du bloc ne se fait qu'au 1er seau.

## Ce qu'il faut renvoyer

Les chiffres mesurés (`saut_kg`, `agitation_tr_min`, `casse_tr_min`,
`casse_du_bloc_s`, `temps_max_s`, `arret_avant_kg`, `mycelium_kg` de chaque format), à mettre dans
`machine.yaml` par une session de correction ; puis passer `mycelium → exemple` à `false`.
