# Essai du portique sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent que de **faux**
FluidNC : un faux pont « de travers » est remis d'équerre par sa prise d'origine, mais rien ne prouve que la
vraie carte n° 1 fasse pareil. C'est le but de cette procédure.

Elle se fait une fois la carte FluidNC n° 1 câblée (pont X1 et X2, chariot Y, Z de la griffe, leurs fins de
course, alarmes des pilotes, frein du Z, les 2 capteurs d'origine de la griffe : godet et fanion de la
rotation) et le Z de la préhension câblé sur la carte n° 4 (fin de course, alarme, frein ; pour l'étape 5, le
Hall de la rotation de la tête et le compte-tours sur l'ADS1115). Elle vérifie le sens des axes, la mise d'équerre, les fins de course, les freins et les
alarmes, puis mesure les chiffres marqués EXEMPLE (`fluidnc/portique.yaml`, `pi/reglages/machine.yaml` partie
`portique`, `docs/entrees-sorties.yaml`). Compter une demi-journée, à deux de préférence.

La sécurité des personnes est câblée (arrêt d'urgence, portes, relais de sécurité ; les freins des Z serrent
sans courant). Le logiciel ne protège que la machine : **garder la main sur l'arrêt d'urgence** pendant
chaque mouvement, personne sous les outils.

## Avant de commencer

- `fluidnc/portique.yaml` est complété avec les **vraies broches** (plan de câblage), les vrais pas par mm
  (impulsions par tour du pilote acheté : pas par mm = impulsions par tour / 40 en X et Y, / 50,27 en Z) et
  envoyé à la carte (page web → « Mises à jour »). Tant qu'il dit « EXEMPLE », il est refusé. Même chose pour
  les ajouts du Z de la préhension dans `fluidnc/prehension.yaml` (pignon de 16 dents, course 870 mm, frein
  sur `digital2`, alarme sur `macro0`).
- Le programme principal est arrêté (`sudo systemctl stop vidange`) : une seule liaison par carte.
- Courroies du pont tendues, rien sur les rails, les deux outils **en haut** à la main si possible.

Dans les commandes ci-dessous, `vidange-fluidnc` et `vidange-portique` veulent dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc` (et de même pour l'autre).

## Étape 1 : les entrées, sans rien bouger

1. `vidange-portique etat` : les 4 positions s'affichent (« inconnue » avant la prise d'origine), aucun
   pilote en alarme.
2. Fins de course **NF** (fil coupé = déclenché) : `vidange-fluidnc console portique`, puis `?` plusieurs fois
   en appuyant à la main sur chaque fin de course : la lettre de l'axe (X pour X1 **et** pour X2, Y, Z)
   apparaît dans `Pn:` quand on appuie, et disparaît quand on lâche. Débrancher un fin de course : la lettre
   doit apparaître aussi (fil coupé = déclenché). Sinon : corriger `:low` dans `fluidnc/portique.yaml`.
   Faire de même pour le Z de la préhension (`vidange-fluidnc console prehension`, lettre Z).
3. Alarmes des pilotes : débrancher le câble moteur d'un pilote (courant coupé !) puis le remettre sous
   tension : son voyant d'alarme s'allume, et `vidange-portique etat` doit dire lequel (« moteur X1 du
   pont », « moteur X2 du pont », « chariot Y », « Z de la griffe », « Z de la préhension »). Si le nom est
   faux, échanger les lettres dans `pi/reglages/fluidnc.yaml` (cartes → portique → entrees).
4. Détecteur de chocs : débrancher le câble de l'accéléromètre : la carte n° 1 doit passer en **alarme**
   (`?` → `Alarm`). Rebrancher, attendre l'autotest, `$X`.

## Étape 2 : le sens de chaque axe (petits pas)

Toujours à la console de la carte n° 1, après `$X` (déblocage, pas encore d'origine) :

1. Frein du Z de la griffe : `M64 P0` → on entend le frein se desserrer ; `M65 P0` → il serre. Même chose
   sur la carte n° 4 avec `M64 P2` / `M65 P2` (P2 depuis la tâche 45 undecies : P0 et P1 sont les vannes
   de la ventouse). **Ne jamais desserrer un frein outil en bas sans tenir
   l'outil** : il pourrait descendre.
2. `M64 P0`, puis `$J=G91 Z-10 F600` : le Z de la griffe doit **descendre** de 10 mm. Sinon, inverser son
   sens (`direction_pin: ...:low`). `$J=G91 Z10 F600` pour remonter.
3. `$J=G91 Y10 F600` : le chariot doit aller **vers l'allée** (y grandit).
4. `$J=G91 X10 F600` : le pont doit aller **vers le stockage** (x grandit), **les deux côtés ensemble**.
   Si un côté part à l'envers, inverser le sens de ce moteur seul (motor0 = X1, motor1 = X2). Si un seul côté
   bouge : câble ou pilote de l'autre.
5. Carte n° 4 : `$X`, `M64 P2`, `$J=G91 Z-10 F600` : la face de la préhension descend.

## Étape 3 : la prise d'origine dans l'ordre, et l'équerre

1. Mettre le pont **un peu de travers** exprès : moteurs coupés, pousser un côté de 2 à 3 mm (mesurer
   l'écart entre chaque bout du pont et sa butée côté fût, au réglet).
2. Tête de la griffe remise **à la main** bras le long du pont (A = 0°, raclette côté fût), cordon de la
   préhension droit. `vidange-portique origine --confirmer` (la première fois, aucun angle n'est encore
   enregistré : `--confirmer` dit que vous avez regardé). Il desserre les freins, puis fait **dans cet
   ordre** : les deux Z montent jusqu'à leur fin de course (et reculent de quelques mm) ; puis le chariot va
   vers la paroi ; puis le pont va vers le fût, **chaque moteur s'arrêtant sur son propre fin de course** ;
   puis le godet se ferme lentement sur son capteur ; puis la griffe va au point de recherche (mât à x 0,86,
   y 0,57), descend ses axes à 1,075 et cherche son fanion (étape 6) ; enfin la tête de préhension cherche
   son Hall. Rien ne doit partir en Y ou en X avant que les deux Z soient en haut.
3. Après : remesurer les deux bouts du pont. L'écart doit avoir disparu (± 0,5 mm). Sinon : les deux fins de
   course ne sont pas à la même place ; régler l'un des deux (ou `pulloff_mm` d'un moteur).
4. Mesurer au mètre, dans le repère du portique, où sont, juste après « $HX » (`vidange-fluidnc console
   portique`, `$HZ`, `$HY`, `$HX`) : le pont (doit être x 0,223), les mâts (y 0,04, donc centre du chariot à
   0,08), les axes de la tête de la griffe (1,29), la face de la préhension (1,10).
   Sinon, régler `mpos_mm` de l'axe dans `fluidnc/portique.yaml` (et `fluidnc/prehension.yaml`).
5. Repérer les **butées mécaniques** de Y (côté paroi et côté allée) : avancer à petits pas
   (`$J=G91 Y5 F600`) jusqu'à 1 cm de chacune et noter la position (`?`) : la course de `chariot_y` dans
   `machine.yaml` (0,04 à 0,83) doit rester en dedans.

## Étape 4 : courses, garage, photo

1. `vidange-fluidnc console portique`, `$J=G53 X200 F3000` doit être **refusé** (sous 223 mm) ; de même
   `$J=G53 X2930 F3000` (au-delà de 2 925), `$J=G53 Y840 F3000` (au-delà de 830) et `$J=G53 Z1300 F600`
   (au-dessus de l'origine).
2. `vidange-portique photo stockage` : les deux outils montent, puis le pont va à x 0,223 et attend 0,3 s.
   Prendre une photo du plafond (`vidange-vision photo plafond plafond.jpg`) : le pont ne doit pas cacher le stockage.
3. `vidange-portique photo fut_poste` : pont à x 2,925 ; photo : le fût et le poste sont bien visibles.
4. `vidange-portique garage` : outils en haut, pont à 2,925, chariot au centre (0,50, mâts à 0,46), puis
   les freins **serrent** (on les entend).
5. Accélération seau tenu : `vidange-fluidnc console portique`, `$/axes/x/acceleration_mm_per_sec2=500`,
   un aller-retour de 50 cm (`$J=G91 X500 F15000`, puis `X-500`) : plus doux qu'à 1000. Remettre 1000.
   Tête basse (face sous 0,60) : même essai à 250 (`× 0,5`, `portique → facteur_acceleration_tete_basse`),
   face de la préhension à 0,55, en regardant le mât : il ne doit pas osciller à l'arrêt. Sinon, baisser le
   facteur ou monter `tete_basse_z`.
6. Chaîne Z de la préhension : préhension en haut (plaque au-dessus de 2,02), avancer le chariot à la main
   vers l'allée (`$J=G53 Y800 F600`) : mesurer l'écart entre le brin de la chaîne et le plénum du
   Nettoyage. Il doit rester de la place à y 0,80 (sinon : baisser `chaine_prehension → mat_y_max`).

## Étape 5 : le godet et la rotation de la griffe (capteurs d'origine)

Les 2 capteurs inductifs M12 (PNP NO, voyant sur le capteur) sont sur le multiconducteur de la griffe.

1. **Lettres de « Pn: »** : `vidange-fluidnc console portique`, `?` plusieurs fois. Godet **fermé** (B à son
   capteur) : la lettre B apparaît. Tête à **+90°** (fanion libre) : la lettre A apparaît ; à **−90°**
   (fanion devant le capteur) : elle disparaît. Si c'est l'inverse pour A, changer `:low` de son
   `limit_pos_pin` dans `fluidnc/portique.yaml` (la broche est inversée exprès : A = fanion LIBRE).
2. **Godet** (`$HB`, tête en haut, **godet vide**) : il part lentement vers fermé et s'arrête sur son
   capteur ; s'il était déjà sur le capteur, il recule d'abord de 2 mm vers l'ouvert. Après `G90 G0 B0`,
   mesurer l'écart godet / capot : il doit rester les 4 mm de garde. Sinon régler `mpos_mm` de B.
   Bloquer le godet à la main (gant, moteur en courant réduit, **arrêt d'urgence en main**) pendant `$HB` :
   la recherche doit finir en alarme, et l'outil dire « godet bloqué : vider au-dessus d'un seau ».
3. **Rotation** : `vidange-portique origine` (étape 3) amène la griffe au point de recherche (mât x 0,86 ;
   y 0,57), axes à 1,075, godet fermé. Partir de la tête à 180° (noter l'angle avant, au besoin à la main) :
   la tête tourne en − (elle passe par 0, jamais au-delà de −180°), s'arrête au fanion, puis « $HA » revient
   lentement en + jusqu'au bord. Après `G90 G0 A0` : bras **le long du pont**, raclette côté fût (à 1° près).
   Sinon régler `mpos_mm` de A. Recommencer depuis 0° et depuis −90° : la tête ne doit jamais faire plus d'un
   demi-tour.
4. **Coupure en pleine rotation** : tête à 0°, faire tourner A (`$J=G91 A90 F600`) et couper le courant
   pendant la rotation. Remettre le courant, `vidange-portique origine` (sans `--confirmer`) : il doit
   refuser (« coupure pendant une rotation de la griffe : Z ne monte pas ») **sans bouger Z**.
5. **Demi-tour hors du fût** : seulement au point (0,86 ; 0,57), axes à 1,075, godet fermé (la griffe le
   refuse ailleurs). Faire un demi-tour à ce point et regarder qu'il ne touche rien.

## Étape 6 : ce qu'on note

- Les impulsions par tour réglées sur les pilotes (et donc les pas par mm), les places mesurées des fins de
  course (`mpos_mm`, aussi pour A et B de la griffe), les butées de Y, le seuil du détecteur de chocs, le
  facteur d'accélération tête basse, et si l'alarme du pilote du godet est câblée (question de la PR).
- Les recopier dans `fluidnc/portique.yaml` et `pi/reglages/machine.yaml`, enlever « EXEMPLE » de ce qui est
  devenu vrai, et ouvrir une PR de correction (ou les donner à une session : « Lis CLAUDE.md, puis corrige la
  PR n° X selon mes remarques et les tests, rien d'autre. »).
