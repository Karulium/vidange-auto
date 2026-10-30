# Essai de la préhension sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent que de **faux**
FluidNC, une **fausse** pesée, un **faux** capteur de vide et des objets **imaginaires** (simulateur).

Cette procédure se fait une fois la carte FluidNC n° 4 câblée (Z de la tête, rotation, contact de la tête,
vanne du venturi, électroaimants), le portique essayé (`essai-griffe.md`, étape 1 : repère du pont et du
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
- Prise d'origine des cartes n° 1 et n° 4 faite (`$H`), sans alarme.
- La griffe est **en haut** (son mât est sur le même pont : elle se déplace avec la préhension).

Dans les commandes ci-dessous, `vidange-fluidnc`, `vidange-es`, `vidange-pesees` et `vidange-prehension`
veulent dire `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc` (et de même pour les autres).

## Étape 1 : ce que la carte n° 4 sait faire (console)

1. `vidange-fluidnc console prehension`, puis `$H` : la tête monte en butée haute ; `?` : `MPos` doit dire
   Z = 1100 (la **face** de la tête à 1,10 m). Mesurer au mètre la hauteur de la face au-dessus du sol de
   référence du portique : si elle n'est pas 1,10, régler `mpos_mm` de Z dans `fluidnc/prehension.yaml`.
2. `$J=G91 A10 F600` : la tête doit tourner de 10° dans le **sens des aiguilles d'une montre, vue d'en
   haut** (sens du vissage). Sinon : inverser le câblage du sens du pilote (la fiche dit « aucun axe inversé
   dans FluidNC »), ou, à défaut, le signaler dans la PR de correction.
3. Appuyer à la main sous le plateau de la tête (≈ 1 kg suffit, course 3 mm) en envoyant `?` : la lettre
   `P` doit apparaître dans `Pn:`, et disparaître quand on lâche.
4. Palpage : main sous la tête, `G91 G38.3 Z-20 F300` puis `G90` : la tête descend lentement et **s'arrête
   tout de suite** quand on appuie sur le plateau.
5. `M64 P0` : la vanne du venturi s'ouvre (on entend l'air) ; `M65 P0` : elle se ferme. `M64 P1` : les
   électroaimants tiennent une capsule ; `M65 P1` : ils la lâchent. Si c'est inversé, échanger les numéros
   dans `pi/reglages/fluidnc.yaml` (sorties).
6. Console du portique (`vidange-fluidnc console portique`) : `$/axes/x/acceleration_mm_per_sec2=150`
   doit répondre `ok` (accélération réduite quand la tête tient un seau). Remettre ensuite la valeur de
   `fluidnc/` (et recopier cette valeur normale dans `prehension → acceleration → normale_mm_s2`).

## Étape 2 : le capteur de vide

1. Vanne fermée : `vidange-es lister vide_venturi` doit dire ≈ 0 kPa. Au-delà de ± 5 kPa, la conversion de
   `docs/entrees-sorties.yaml` n'est pas celle du capteur : y mettre les 2 points de la notice du capteur
   **3,3 V** (tension → kPa), par exemple « 0 kPa → … V » et « −100 kPa → … V ».
2. Ventouse posée sur une vitre propre : `vidange-prehension vide` (vanne ouverte 5 s) : le vide doit
   descendre sous −55 kPa en moins de 3 s (`vide → delai_prise_s`), vers −70 à −85 kPa. Si possible,
   comparer une fois avec un manomètre.
3. `vidange-prehension etat` deux ou trois fois de suite : le zéro (recalé à chaque lancement, vanne fermée)
   doit rester à moins de ± 5 kPa.

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
   contact, ouvre la vanne, lève lentement, pèse, va poser le seau et remonte. L'outil écrit le vide et le
   poids de la prise.
2. Refaire avec une cote fausse de 1 cm (0.59) : l'outil doit s'arrêter (« contact à … attendu à … »).
3. Mettre deux seaux emboîtés : l'outil doit les reposer et dire « deux seaux emboîtés pris ».
4. Pendant une levée, couper l'air du venturi (ou glisser une cale sous la lèvre) : la tête doit s'arrêter,
   redescendre, reposer, reprendre ; au 2ᵉ échec, s'arrêter avec l'alerte.
5. Même chose avec un couvercle (`prendre-poser couvercle ...`).

## Étape 6 : le porte-bocal

1. Régler dans `prehension → porte_bocal` la position du bocal au garage (x 0,565, y 0,150 : à vérifier) et
   `face_z` : face de la tête quand le bocal est à sa hauteur exacte entre les mors (1 mm de jeu sous le
   fond et au-dessus de la capsule ; ≈ 1,0625 manivelle en bas). Régler `orientation_deg` pour que les
   méplats soient en face des mors.
2. Agitateur au garage, **manivelle en bas**, bielle dans le trou de 7 cm (`mycelium → course_agitation_m`
   à 0.07) ; griffe en **butée haute**. Le panneau du poste du fût peut rester levé : dans la petite zone
   du garage (± 5 mm autour du bocal), la tête a le droit de descendre (seule exception à l'isolation du fût).
3. `vidange-prehension porte-bocal 1.4 0.75 0.95 --manivelle-en-bas` (place d'un bocal plein, avec vos
   cotes ; `--manivelle-en-bas` dit que vous avez vu la manivelle en bas) : le bocal est pris, posé (mors
   ouverts, mors approchés à « Ø 98 » à faible courant, lâché, remontée de 5 mm, serrage), repris (mors
   serrés pour descendre, puis ouverts) et reposé. Regarder que les mors ne touchent pas le bocal pendant la
   descente.
4. Contrôles des verrous (chacun doit s'arrêter **avant** que la tête descende au porte-bocal) :
   - sans `--manivelle-en-bas` : « position de l'agitateur du mycélium inconnue : la tête ne passe pas
     au-dessus de sa glissière » (l'outil ne lit pas l'agitateur : sans cette option, toute la glissière,
     du garage au dosage, est interdite à la tête) ;
   - griffe descendue de 2 cm (`G90 G1 Z1270 F300` à la console de la carte n° 1) : « il faut la griffe en butée
     haute » ; la remonter ensuite (`G90 G1 Z1290 F300`).
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
fluidnc/prehension.yaml), et ce qui ne s'est pas passé comme écrit ici. Quand tout est vrai, passer
`prehension → exemple` à `false`.
