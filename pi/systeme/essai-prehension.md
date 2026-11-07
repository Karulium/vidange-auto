# Essai de la préhension sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent que de **faux**
FluidNC, une **fausse** pesée, un **faux** capteur de vide et des objets **imaginaires** (simulateur).

Cette procédure se fait une fois la carte FluidNC n° 4 câblée (Z de la tête, rotation, contact de la tête,
les deux électrovannes de la ventouse « aspirer » et « souffler », électroaimants), le portique essayé (`essai-griffe.md`, étape 1 : repère du pont et du
chariot), la carte de pesée de la préhension étalonnée (`pesee/essai-etabli.md`) et le porte-bocal essayé
(`essai-porte-bocal.md`). Elle vérifie que les cartes font ce que le Pi attend, puis mesure les chiffres
marqués EXEMPLE (`pi/reglages/machine.yaml`, partie `prehension` ; `docs/entrees-sorties.yaml`,
`vide_venturi` ; `fluidnc/prehension.yaml`). Compter une journée.

La sécurité des personnes est câblée (arrêt d'urgence, portes). Les verrous du logiciel ne protègent que
la machine : garder la main sur l'arrêt d'urgence, et les doigts loin de la tête.

## Avant de commencer

- `fluidnc/prehension.yaml` est complété avec les **vraies broches** (plan de câblage), les vrais pas par
  mm, et envoyé à la carte (page web → « Mises à jour »). Tant qu'il dit « EXEMPLE », il est refusé.
- Le programme principal est arrêté (`sudo systemctl stop vidange`) : une seule liaison par carte.
- Prise d'origine du portique faite (`vidange-portique origine`, `essai-portique.md`), sans alarme : elle
  fait aussi celle de la rotation de la tête (Hall), étape 1 bis ci-dessous.
- La griffe est **en haut** (son mât est sur le même pont : elle se déplace avec la préhension).

Dans les commandes ci-dessous, `vidange-fluidnc`, `vidange-es`, `vidange-pesees` et `vidange-prehension`
veulent dire `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc` (et de même pour les autres).

## Étape 1 : ce que la carte n° 4 sait faire (console)

1. `vidange-fluidnc console prehension`, puis `$HZ` : la tête monte en butée haute ; `?` : `MPos` doit dire
   Z = 1100 (la **face** de la tête à 1,10 m). Mesurer au mètre la hauteur de la face au-dessus du sol de
   référence du portique : si elle n'est pas 1,10, régler `mpos_mm` de Z dans `fluidnc/prehension.yaml`.
2. `$J=G91 A10 F600` : la tête doit tourner de 10° dans le **sens des aiguilles d'une montre, vue d'en
   haut** (sens du vissage). Sinon : inverser le câblage du sens du pilote (la fiche dit « aucun axe inversé
   dans FluidNC »), ou, à défaut, le signaler dans la PR de correction.
3. Appuyer à la main sous le plateau de la tête (≈ 1 kg suffit, course 3 mm) en envoyant `?` : la lettre
   `P` doit apparaître dans `Pn:`, et disparaître quand on lâche.
4. Palpage : main sous la tête, `G91 G38.3 Z-20 F300` puis `G90` : la tête descend lentement et **s'arrête
   tout de suite** quand on appuie sur le plateau.
5. Les deux électrovannes (tâche 45 undecies ; Implantation, `sorties-carte-4.md` : sorties auxiliaires
   24 V n° 1 et 2 de la carte, sur le 24 V coupé). **Dans la console, rien n'empêche d'ouvrir les deux : ne
   jamais envoyer `M64 P0` et `M64 P1` sans `M65` de l'autre entre les deux** (le programme, lui, refuse).
   - `M64 P0` : « aspirer » s'ouvre, le venturi souffle (on l'entend) ; `M65 P0` : il s'arrête.
   - `M64 P1` : « souffler » s'ouvre, un petit souffle sort de la ventouse ; `M65 P1` : il s'arrête.
   - `M64 P0`, puis appuyer sur l'arrêt d'urgence : le venturi doit **s'arrêter tout de suite** (24 V
     coupé). Réarmer, `M65 P0`. Même chose avec `M64 P1`.
   - `M64 P4` : les électroaimants tiennent une capsule ; `M65 P4` : ils la lâchent (P4 : EXEMPLE, la
     fiche de l'Implantation ne dit pas où ils sont câblés).
   Si une vanne est inversée (P0 souffle à la ventouse), le câblage est faux : P0 et P1 ne changent pas
   (fiche), c'est le fil qu'il faut échanger.
6. Console du portique (`vidange-fluidnc console portique`) : `$/axes/x/acceleration_mm_per_sec2=150`
   doit répondre `ok` (accélération réduite quand la tête tient un seau). Remettre ensuite la valeur de
   `fluidnc/` (et recopier cette valeur normale dans `prehension → acceleration → normale_mm_s2`).

## Étape 1 bis : l'origine de la rotation (Hall) et le compte-tours

Le Hall sous la poulie de 60 dents voit l'aimant **à chaque tour** : le tour vient du compte-tours
(potentiomètre multitour au rapport 3, voie A1 de l'ADS1115, `compte_tours_tete`). Le Pi garde l'angle de
la tête (tours compris) dans `pi/donnees/angles.json` à chaque arrêt.

1. **Hall** : console de la carte n° 4, tourner à petits pas (`$J=G91 A5 F300`) en envoyant `?` : la lettre A
   apparaît dans `Pn:` une fois par tour, sur quelques degrés. Sinon : `:low` de `limit_pos_pin` de A dans
   `fluidnc/prehension.yaml`.
2. **Compte-tours** : cordon droit, tête près de 0° ; `vidange-es lister` : `compte_tours_tete` doit dire ≈ 0°.
   Tourner d'un tour (`$J=G91 A360 F1800`) : la lecture doit gagner ≈ 360° (± 3°). Sinon, régler
   `conversion` de `compte_tours_tete` dans `docs/entrees-sorties.yaml` (deux points tension → degrés de la
   tête ; mi-course = 0°). Revenir (`$J=G91 A-360 F1800`).
3. **Prise d'origine** : `vidange-portique origine --confirmer` (la première fois, aucun angle enregistré).
   La tête revient d'après le compte-tours à 20° avant le Hall, puis le cherche lentement **en +**, sur
   60° au plus. Recommencer en partant d'un tour plus loin (tête à +370°) : elle doit revenir de 390° en −,
   puis trouver le Hall en + ; le cordon ne doit jamais se vriller.
4. **Contrôle** : tourner la tête à la main de 45° (courant coupé), puis `vidange-portique origine` (sans
   `--confirmer`) : il doit refuser (« compte-tours … et angle enregistré … en désaccord … ») et demander de
   vérifier le cordon. Débrancher le potentiomètre : « compte-tours … hors de sa plage » ou « illisible ».
5. **Méplats** : après la prise d'origine, `$J=G53 A0 F600` puis regarder le bocal dans le porte-bocal :
   ses méplats sont-ils en face des mors en V ? Sinon, tourner à petits pas jusqu'à ce qu'ils le soient, lire
   l'angle (`?`, `MPos` de A) et le recopier dans `prehension → angle_meplats_deg` (machine.yaml). La pose
   ira ensuite à la plus proche de cet angle + k × 120° (au plus 60° de rotation, ± 3°).

## Étape 2 : le capteur de vide

1. Vanne fermée : `vidange-es lister vide_venturi` doit dire ≈ 0 kPa. Au-delà de ± 5 kPa, la conversion de
   `docs/entrees-sorties.yaml` n'est pas celle du capteur : y mettre les 2 points de la notice du capteur
   **3,3 V** (tension → kPa), par exemple « 0 kPa → … V » et « −100 kPa → … V ».
2. Ventouse posée sur une vitre propre : `vidange-prehension vide` (« aspirer » ouverte 5 s) : le vide
   doit descendre sous −55 kPa en moins de 3 s (`vide → delai_prise_s`), vers −70 à −85 kPa. Si possible,
   comparer une fois avec un manomètre. La suite de la commande est l'étape 2 bis.
3. `vidange-prehension etat` deux ou trois fois de suite : le zéro (recalé à chaque lancement, vanne fermée)
   doit rester à moins de ± 5 kPa.

## Étape 2 bis : le lâcher par « souffler » (tâche 45 undecies)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent qu'une fausse carte et un faux
vide. Fil Préhension (07/11/2026) : fermer « aspirer » ne lâche **rien** (le clapet anti-retour garde le
vide) ; le lâcher, c'est « aspirer » fermée, puis « souffler » ouverte ≈ 0,2 à 0,5 s
(`prehension → vide → souffle_s`, EXEMPLE 0,3 s), puis attendre que le vide remonte au-dessus de −5 kPa
(`lache_kpa`, au plus `delai_lacher_s`, EXEMPLE 2 s). Le Pi n'ouvre jamais les deux vannes en même temps.

1. Toujours `vidange-prehension vide` sur la vitre. Après les 5 s d'« aspirer », la commande ferme
   « aspirer » et lit le vide 2 s : il doit **rester** sous −50 kPa (lignes « « aspirer » fermée (le
   clapet garde le vide) »). S'il remonte vite, le clapet fuit : le dire dans la PR.
2. Puis elle ouvre « souffler » `souffle_s` et la referme. Elle doit écrire « « souffler » 0.3 s : lâché,
   vide … kPa » et la vitre doit se décoller **toute seule**.
3. Réglage de `souffle_s` : refaire avec 0,2, puis 0,5 (machine.yaml). Garder **le plus court qui lâche à
   chaque fois** (vitre, puis seau vide, couvercle et entonnoir tenus à la main), plus 0,1 s de marge. Noter
   le temps que met le vide pour passer au-dessus de −5 kPa : `delai_lacher_s` doit le couvrir largement.
4. `vidange-prehension vide --sans-souffler` avec un seau vide tenu à la main contre la ventouse : à la fin,
   le seau **reste tenu** (pas de souffle). L'enlever à la main.
5. Pincer le tuyau de « souffler » (ou la ventouse sur une vitre mouillée qui colle) et relancer
   `vidange-prehension vide` : la commande doit dire « pas revenu au-dessus de -5 kPa » et rendre une
   erreur. Dans un geste (étape 5), le programme souffle une deuxième fois, puis s'arrête avec l'alerte
   « … resté collé à la ventouse ».

## Étape 3 : la force

1. `vidange-prehension etat`, tête en l'air, rien de tenu : la force doit être ≈ 0 N (la tare est faite au
   début de chaque prise ; ici on lit l'écart au zéro de l'étalonnage).
2. Accrocher un poids connu de 1 kg sous la ventouse : la force doit monter d'≈ 9,8 N.
3. Pousser le plateau vers le haut : la force doit **baisser** (lecture = poids porté − poussée).

## Étape 4 : les objets et leurs poids

Peser à la balance, puis mettre dans `prehension → objets` (et `griffe → formats → <format> → tare_kg` pour
les seaux) : seau vide de chaque format, couvercle, bocal plein, capsule. Mesurer aussi, pour chaque objet,
ce qui dépasse au-dessus et au-dessous de la face de la tête quand elle le tient (`dessus_m`, `dessous_m`)
et son rayon. La tolérance (`tolerance_n`) doit laisser passer un objet seul, et refuser deux seaux
emboîtés.

## Étape 5 : une prise et une pose

Choisir une place libre loin du fût et des caméras (x > 1,2), mesurer la cote de la face quand elle touche
le fond intérieur d'un seau vide posé là (contact_z), et une deuxième place pour le poser.

1. `vidange-prehension prendre-poser seau 1.6 0.6 0.60  1.9 0.6 0.60 --format seau_a` (avec vos cotes) :
   la tête monte, le pont va au-dessus du seau, la tête descend (lente sur les 3 derniers cm), s'arrête au
   contact, ouvre « aspirer », lève lentement, pèse, va poser le seau, ferme « aspirer », **souffle** (on
   entend le petit souffle), attend que le vide revienne au-dessus de −5 kPa et remonte. L'outil écrit le
   vide et le poids de la prise. Si le seau remonte avec la tête, le lâcher ne marche pas : arrêt d'urgence.
2. Refaire avec une cote fausse de 1 cm (0.59) : l'outil doit s'arrêter (« contact à … attendu à … »).
3. Mettre deux seaux emboîtés : l'outil doit les reposer et dire « deux seaux emboîtés pris ».
4. Pendant une levée, couper l'air du venturi (ou glisser une cale sous la lèvre) : la tête doit s'arrêter,
   redescendre, reposer, reprendre ; au 2ᵉ échec, s'arrêter avec l'alerte.
5. Même chose avec un couvercle (`prendre-poser couvercle ...`).
6. Pincer le tuyau de « souffler » pendant une pose : la tête doit souffler une deuxième fois, puis
   s'arrêter avec l'alerte « seau resté collé à la ventouse » sans remonter. Enlever le seau à la main.

## Étape 6 : le porte-bocal

1. Vérifier dans `prehension → porte_bocal` la position du bocal (agitateur fixe : x 0,925, y 0,150, le
   même que `mycelium → bocal`) et `contact_capsule_z` : face de la tête au contact de la capsule
   **manivelle en bas**, selon le trou du maneton (1,047 / 1,077 / 1,108 pour 10 / 7 / 4 cm, fiche
   Mycélium v10b). `mycelium → course_agitation_m` doit dire le trou où est vraiment la bielle (10 cm
   par défaut ; 4 cm est refusé au démarrage : la tête ne peut pas poser le bocal). Les méplats :
   étape 1 bis, point 5 (`angle_meplats_deg`).
2. **Manivelle en bas**, caméra du dosage à 0° (vers le bocal). Le chariot de remplissage peut être
   reculé (y 0,40) ou au poste (y 0,135). Le panneau du poste du fût peut rester levé : x 0,925 est hors
   de l'isolation du fût.
3. `vidange-prehension porte-bocal 1.0 0.75 0.95 --manivelle-en-bas` (place d'un bocal plein, avec vos
   cotes ; `--manivelle-en-bas` dit que vous avez vu la manivelle en bas, arrêtée, et la caméra à 0°).
   La tête contourne la **zone du porte-bocal** (`prehension → zone_porte_bocal` : x 0,79-1,08,
   y −0,03-0,27) : elle y entre seulement par le **couloir** (`porte_bocal → couloir`) : du départ
   (0,925 ; 0,40) en −y jusqu'à la verticale du bocal, face en haut (1,10), x à la largeur permise ; avant de
   descendre, mors ouverts et axe de la tête à 1 mm près en x (−1 / +2 mm en y) ; les 23 derniers mm de la
   pose sont lents (`vitesses → pose_bocal`). Regarder que ce trajet ne passe ni au-dessus du support de
   la glissière verticale (y ≈ 0), ni près du boîtier de la caméra du bocal (x 0,99-1,16, y < 0,335), et
   que le bocal entre dans les mors en V sans frotter (1,3 mm de jeu). Le bocal est pris, posé (mors
   ouverts, mors approchés à « Ø 98 » à faible courant, lâché, remontée de 5 mm, serrage), repris (mors
   serrés pour descendre, arrêt sur le contact de la capsule, puis mors ouverts) et reposé.
   Regarder **pendant le trajet d'arrivée** que le bas du bocal tenu (≈ 0,93) ne touche rien du
   porte-bocal (haut à 1,07 manivelle en bas), puis que les mors ne touchent pas le bocal pendant la
   descente. Au moindre doute : arrêt d'urgence, et le noter (question de la PR de la tâche 19 ter).
4. Contrôles des verrous (chacun doit s'arrêter **avant** que la tête entre dans la zone) :
   - sans `--manivelle-en-bas` : « zone du porte-bocal ... manivelle du mycélium en bas (manivelle qui
     bouge, demi-tour, ou position inconnue) » (l'outil ne lit pas l'agitateur : sans cette option, la
     zone est interdite) ;
   - programme principal : manivelle en haut, la tête ne va pas à la verticale du bocal ; et tant que la
     tête est dans la zone, le Mycélium ne tourne pas la manivelle et ne retourne pas le bocal (« la tête
     de préhension est dans la zone du porte-bocal »).
5. Vérifier à la console de la carte n° 3, juste après l'approche, que le courant faible est bien pris par
   le pilote (`$/axes/y/motor0/tmc_2209/run_amps` doit répondre la valeur faible) et que le serrage est
   ensuite aussi ferme qu'avant (`essai-porte-bocal.md`, étape 4).

## Étape 7 : le vissage

1. Une capsule posée à plat (place 1), un bocal ouvert sous la tête (place 2), mesurer les deux contact_z.
2. `vidange-prehension visser 1.5 0.5 0.85  1.7 0.5 0.90` : la capsule est prise (électroaimants), posée sur
   le bocal, appuyée à ≈ 80 N, vissée (rotation et Z ensemble), lâchée. Contrôler à la main que la capsule
   est fermée ; ajuster `vissage → angle_deg` et `descente_m`.
3. Mettre un bocal dont la capsule force (filet abîmé) : au-delà de 150 N, la tête doit s'arrêter avec
   l'alerte.

## Ce qu'il faut renvoyer

Dans la PR de correction de la tâche 37 : les chiffres mesurés (machine.yaml, entrees-sorties.yaml,
fluidnc/prehension.yaml), et ce qui ne s'est pas passé comme écrit ici. Pour le lâcher (tâche 45
undecies) : `souffle_s` et `delai_lacher_s` retenus, le temps que le clapet garde le vide, et les vrais
numéros de broche de P0 et P1 (fichier de configuration de la carte achetée). Quand tout est vrai, passer
`prehension → exemple` à `false`.
