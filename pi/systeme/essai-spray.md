# Essai du spray sur le vrai matériel (carte ESP32 n° 5)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent qu'une fausse carte. Cet essai se
fait **après la tâche 39 bis** (programme de la carte n° 5 chargé dedans). Durée : environ 2 h.

Le spray ne protège personne. Pendant tout l'essai, l'arrêt d'urgence et le store restent câblés comme
d'habitude. L'outil `vidange-spray` **ne vérifie pas la règle 6** (plateau assez bas, barres ouvertes) :
c'est vous qui la vérifiez, à l'œil, avant chaque « sortir ».

Il faut : la boîte du spray montée et alimentée en 24 V, son câble `c_spray` branché, l'adaptateur USB-RS485
du spray branché au Pi, l'air comprimé réglé (0,3 à 0,5 bar à la buse, 0,5 bar à la chasse), un seau vide,
une balance de cuisine précise à 0,01 g, une masse connue d'environ 200 g, de l'eau (pas de culture pour
l'essai), un chronomètre.

## Avant de commencer

1. Arrêter le programme principal : `sudo systemctl stop vidange`.
2. Chariot de remplissage **plateau en bas, barres grandes ouvertes**, rien sur le plateau. Le vérifier à
   l'œil : c'est la règle 6.
3. Tous les essais se lancent ainsi (on écrit plus bas seulement la fin de la ligne) :
   `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-spray ...`

## Étape 1 : reconnaître l'adaptateur

1. Lire le numéro de série des adaptateurs : `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc lister`.
   Débrancher puis rebrancher celui du spray pour savoir lequel c'est. **Si le numéro est « AUCUN » :
   s'arrêter et le signaler.**
2. L'écrire dans `docs/entrees-sorties.yaml`, carte `rs485_spray`, ligne `numero_serie_usb`, entre guillemets.

## Étape 2 : la carte répond

1. Lancer `etat --secondes 5`. Attendu : 5 lignes « bras 0,0° (rangé) … flacons 1: … 2: … 3: … 4: … ».
2. Si « ne répond pas » : vérifier le 24 V de la boîte, les fils A et B (les inverser une fois), la
   résistance de 120 Ω aux deux bouts, l'adresse et la vitesse (`docs/entrees-sorties.yaml`, signal
   `carte_spray` et carte `rs485_spray`, les mêmes que dans le programme de la carte).
3. Si « pas la carte du spray » ou « table des registres n° … » : le programme de la carte ou du Pi n'est
   pas à jour. Le signaler.
4. Débrancher le câble `c_spray` : la ligne dit « ne répond pas ». Le rebrancher : elle revient.

## Étape 3 : prise d'origine et capteur du bras

1. Écarter un peu le bras à la main (machine arrêtée, 24 V coupé), remettre le 24 V.
2. Lancer `origine`. Attendu : le bras tourne lentement vers « rangé », s'arrête sur le capteur, « Fait. ».
3. Regarder le voyant du capteur inductif : allumé bras rangé. Lancer `etat --secondes 3` : « rangé ».
4. Pousser le bras à la main de quelques centimètres : la ligne dit « pas rangé » et « ERREURS : le capteur
   « bras rangé » a perdu le bras sans ordre ». Le remettre, puis lancer `effacer`, puis `origine`.

## Étape 4 : sortir et ranger le bras

1. Poser un seau vide de format A sur le plateau (plateau en bas, barres ouvertes : vérifier).
2. Lancer `sortir 64.3 --etabli` (angle du seau A, `machine.yaml → spray → bras → angles`). Chronométrer.
   Attendu : le bras pivote lentement, la buse arrive au-dessus du seau, à environ 3 cm du bord intérieur.
   **Rien ne touche** (bras, buse, seau, barres).
3. Lancer `ranger` : le bras revient sur le capteur, « Fait. ».
4. Refaire avec les autres formats posés : B `72.4`, C `59.4`, D `62.2`. Noter tout frottement.
5. Si le temps dépasse 3 s ou si la carte dit « ÉCHOUÉ » : régler `bras → vitesse_deg_s` ou `temps_max_s`
   (et refabriquer le programme de la carte, tâche 39 bis).

## Étape 5 : la carte s'arrête seule si le Pi se tait

1. Lancer `sortir 64.3 --etabli`. L'outil s'arrête à « Fait. » : plus personne ne bat.
2. Attendu : **au bout d'environ 2 s**, le bras se range tout seul.
3. Lancer `etat --secondes 3` : « rangé » et « ARRÊT SEULE (le Pi s'est tu) ». Puis `effacer`.

## Étape 6 : étalonner les 4 balances

Pour chaque emplacement N (1 à 4) :

1. Retirer le flacon de l'emplacement N. Lancer `zero N`. Recopier la ligne `zero_brut: …` dans
   `pi/reglages/pesees.yaml`, `balances_spray → N`.
2. Poser la masse connue (pesée à 0,01 g sur la balance de cuisine, par exemple 200,00 g). Lancer
   `etalonner N 200` (le poids exact, en grammes). Recopier la ligne `brut_par_kg: …`.
3. Après les 4 : refabriquer le programme de la carte (il recopie l'étalonnage, tâche 39 bis), le
   recharger, puis lancer `etat --secondes 3` avec la masse posée : le poids lu doit être à 0,2 g près.
4. Poser chaque flacon **vide** à sa place, lire son poids (`etat`) et l'écrire dans
   `pi/reglages/machine.yaml`, `spray → flacons → vide_g`.

## Étape 7 : une dose (avec de l'eau)

1. Remplir le flacon 1 d'eau (environ 300 g), le remettre, clipser le tube de pompe.
2. Peser le seau A vide sur la balance de cuisine, le poser sur le plateau (plateau en bas, barres
   ouvertes : vérifier).
3. Lancer `sortir 64.3 --etabli`, puis `dose 1 10 --etabli`.
4. Attendu : air de la buse (bruit), pompe, puis chasse de 4 à 5 s, air coupé 1 s après. La dernière ligne
   dit « atteinte (emplacement 1, ≈ 10,0 g perdus sur 10 g, … s) ».
5. Lancer `ranger`. Repeser le seau : il doit avoir pris environ 10 g (un peu moins : brouillard perdu).
   Noter : le poids perdu, le poids pris par le seau, la durée de pompage (le débit de la pompe).
6. Avec ce débit, régler `spray → dose → temps_max_pompage_s` (au moins 2 fois la durée d'une dose).
7. **Tube pincé** : pincer le tube de la pompe à la main, refaire les points 3 et 4. Attendu : au bout du
   temps maximum, « TEMPS MAX », la chasse se fait quand même, puis le bras se range tout seul.

## Étape 8 : nettoyage des tubes et agitateurs

1. Mettre de l'eau dans le flacon d'alcool (pas d'alcool pour l'essai). Seau vide sur le plateau.
2. Lancer `sortir 64.3 --etabli`, puis `nettoyer --etabli`. Attendu : petite pompe ≈ 5 s, chasse de séchage
   ≈ 15 s. Lancer `ranger`. Peser l'eau tombée dans le seau : environ 10 ml attendus. Sinon, régler
   `spray → nettoyage → pompe_s`.
3. Lancer `agiter 60 30` : les 4 barreaux aimantés tournent pendant 30 s, sans sauter. S'ils sautent,
   baisser `spray → agitateurs → vitesse_pct`.

## Étape 9 : avec le programme principal

1. Relancer le programme : `sudo systemctl start vidange`. La check-list de la page web dit « spray : carte du
   spray prête » (ou ce qui manque).
2. Changer une cartouche : ouvrir la porte de la boîte, retirer le flacon 1, en remettre un plus lourd d'au
   moins 50 g. Attendu : alerte « Nouvelle cartouche à l'emplacement 1 ? ».

## À la fin

- Écrire dans la PR (ou dire à Claude) : les valeurs recopiées, les temps mesurés, le débit, tout ce qui a
  frotté ou surpris.
- Quand vitesses, durées et tares sont réglées : passer `exemple: false` dans `machine.yaml → spray`.
