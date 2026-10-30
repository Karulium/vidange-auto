# Essai du chariot de remplissage sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent qu'un **faux**
FluidNC, une **fausse** balance, une **fausse** barrière et des seaux **imaginaires** (simulateur).

Cette procédure se fait une fois la carte FluidNC n° 2 câblée (avance, plateau, rotation, barres, pousseur,
fins de course, capteur Hall de la rotation, barrière lumineuse, alarmes ALM des pilotes), la carte de pesée du plateau étalonnée (`pesee/essai-etabli.md`), le
Mycélium essayé (`essai-mycelium.md`) et la préhension essayée (`essai-prehension.md`). Elle vérifie que la
carte fait ce que le Pi attend, puis mesure les chiffres marqués EXEMPLE (`pi/reglages/machine.yaml`, partie
`remplissage` et les 5 axes `remplissage_y`, `plateau_z`, `plateau_a`, `barres`, `pousseur` ;
`docs/entrees-sorties.yaml` ; `fluidnc/chariot.yaml`). Compter une journée.

La sécurité des personnes est câblée (arrêt d'urgence, portes). Les verrous du logiciel ne protègent que
la machine : garder la main sur l'arrêt d'urgence, et les doigts loin des barres et du pousseur.

## Avant de commencer

- `fluidnc/chariot.yaml` est complété avec les **vraies broches** (plan de câblage), les vrais pas par mm, et
  envoyé à la carte (page web → « Mises à jour »). Tant qu'il dit « EXEMPLE », il est refusé.
- Le programme principal est arrêté (`sudo systemctl stop vidange`) : une seule liaison par carte.
- Griffe et préhension en haut. La prise d'origine du plateau se fait **vers le bas** (fin de course bas) :
  elle ne monte pas.
- Pas de seau sur le plateau pour les étapes 1 à 3.

Dans les commandes ci-dessous, `vidange-fluidnc`, `vidange-pesees` et `vidange-remplissage` veulent dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc` (et de même pour les autres).
Les options `--agitateur-au-garage --galet-range --micropore-rentre` de `vidange-remplissage` disent qu'on a
**vu** l'agitateur au garage manivelle en haut, le bras du galet rangé et la tête du micropore rentrée (ces
modules ne sont pas encore écrits) : ne les mettre que si c'est vrai.

## Étape 1 : ce que la carte n° 2 sait faire (console)

1. `vidange-fluidnc console chariot`, puis `$H` : le plateau **descend** jusqu'à son fin de course bas ; la
   rotation tourne jusqu'au capteur Hall (moins d'un tour) ; les barres s'ouvrent jusqu'à leur origine côté
   mur ; le pousseur recule jusqu'à son fin de course côté fût ; puis le chariot va contre le tampon côté
   mur. `?` : `MPos` doit dire Y = 130, Z = 175, A = 0, B = 0, C = 0.
   - Plateau : mesurer le **dessus** du plateau au-dessus du sol de référence du portique : il doit être à
     0,175. Sinon, régler `mpos_mm` de Z dans `fluidnc/chariot.yaml`.
   - Fin de course haut (butée de sécurité) : appuyer dessus à la main, plateau à l'arrêt : la carte doit
     passer en alarme (limite dure). `$X` pour la débloquer. Il ne sert jamais d'origine.
   - Chariot : mesurer le y de l'**axe du plateau** dans le repère du portique, chariot contre le tampon : il
     doit être celui de `mpos_mm` de Y (130 mm = 0,130, EXEMPLE). Sinon, le régler.
2. Barres : mesurer, barres à l'origine, la distance de l'axe d'une barre à l'axe du plateau (hw) : la
   fiche dit ≈ 0,309. Écrire la valeur mesurée dans `machine.yaml → remplissage → barres → origine_hw_m`.
   `$J=G90 B-189.5 F2400` : les barres se ferment à hw = origine − 0,1895 ; mesurer, c'est le minimum
   (0,1195 attendu). Chronométrer l'ouverture complète (`$J=G90 B-4 F4800`) : la fiche dit ≈ 2,3 s.
3. Rotation : `$J=G91 A90 F3600` : le plateau tourne d'un **quart de tour exactement** (sens positif = sens
   inverse des aiguilles d'une montre vu d'en haut, comme les angles de la caméra). Sinon, inverser le sens
   du pilote. Un quart de tour faux : régler `steps_per_mm` de A (rapport 8 × pas par tour du pilote / 360).
   Refaire `$H` deux fois et marquer le plateau : il doit revenir au même angle (capteur Hall).
4. Pousseur : à l'origine (C = 0), il est **rentré** : la palette est en bout de rail côté fût, rien ne
   dépasse sur le plateau. `$J=G90 C325 F3000`, **plateau en bas, rien sur le plateau** : il va jusqu'au
   bout côté stockage ; mesurer, la palette doit être à ≈ +0,16 de l'axe du plateau. `$J=G90 C0 F3000`.
5. Barrière lumineuse : `?`, puis couper le faisceau avec la main : la lettre `0` doit apparaître dans
   `Pn:` ; disparaître quand on retire la main.
6. Alarme ALM du pilote des barres : débrancher le moteur des barres, pilote sous tension : la lettre `1`
   doit apparaître dans `Pn:`. Rebrancher (pilote hors tension), puis vérifier qu'elle disparaît. Faire de
   même pour les autres pilotes : leur alarme doit être vue comme prévu au câblage.

## Étape 2 : l'outil du Pi

1. `vidange-remplissage etat` : position des 5 axes (dans le repère du portique), barrière, alarme des
   barres (`False`), balance (≈ 0 kg à vide), et « pose permise : oui ». Comparer avec les mesures de l'étape 1.
2. `vidange-remplissage barriere` : couper le faisceau pendant les 10 s : la ligne doit passer à `True`.
   Poser un seau vide sur le plateau : la balance doit lire son poids (≈ 0,5 kg ; noter la vraie tare de
   chaque format dans `griffe → formats → tare_kg`).
3. Verrous (rien ne doit bouger quand c'est refusé ; l'outil dit pourquoi) :
   - sans `--galet-range` : `vidange-remplissage plateau 0.30` → **refusé** (bras du galet pas connu) ;
   - `vidange-remplissage --galet-range aller 0.25` avec le plateau en haut : le plateau **descend d'abord**,
     puis le chariot roule (anneaux du fût) ;
   - `vidange-remplissage --galet-range aller 0.5` sans `--agitateur-au-garage` → **refusé** (le chariot ne
     roule pas près du poste) ;
   - au poste, `vidange-remplissage --galet-range --agitateur-au-garage plateau 0.53` : les barres
     s'ouvrent d'abord (au-dessus de 0,515) ;
   - `vidange-remplissage --galet-range barres 0.20` avec le plateau à 0,53 : le plateau **descend** sous
     0,48 (joues de l'élévateur), les barres passent, et il reste à 0,48 (barres fermées : pas au-dessus
     de 0,515) ;
   - plateau à 0,25 : `vidange-remplissage --galet-range pousseur 0.325` : le plateau **descend d'abord**
     en bas, puis le pousseur sort (il ne sort que plateau ≤ 0,20). `vidange-remplissage pousseur 0` : il
     rentre.
4. Chariot du fût sorti (pas « en place ») : `vidange-remplissage --agitateur-au-garage aller 0.50` →
   **refusé** (« axe du plateau ≤ 0,475 ») ; `aller 0.47` → permis. Mesurer, chariot à y 0,47, où est son
   bout côté allée (le point le plus loin : renvoi d'angle et moteur de montée) : la fiche dit 0,396 de
   l'axe, `remplissage → verrous → bout_y_m` = 0,40. Il doit rester à y ≤ 0,875.

## Étape 3 : un seau vide posé à la main

1. `vidange-remplissage --galet-range --agitateur-au-garage pose seau_a` : chariot à y 0,50, barres **à
   l'approche** (hw 0,225), plateau **sous** la hauteur de pose (0,4625 − 0,05 pour le seau A). Si le plateau
   était au-dessus de 0,48, il doit descendre **avant** que les barres bougent (elles traversent les joues
   de l'élévateur, hw 0,235-0,255). Vérifier que les barres à 0,225 ne touchent aucun seau : c'est
   l'approche de tous les formats.
2. Poser à la main **un** seau A vide au centre du plateau, puis `vidange-remplissage --galet-range plateau
   0.4625` : la barrière doit rester **libre**. Redescendre (`plateau 0.4125`), poser un 2e seau emboîté
   dans le premier, remonter à 0,4625 : elle doit être **coupée** (sinon, régler `formats → seau_a →
   pose_plateau_z` pour que le bord d'un seul seau passe sous le faisceau, celui de deux au-dessus).
   Refaire pour chaque format (B : 0,5125, fiche). Mesurer aussi de combien le fond du seau du dessous
   dépasse sous celui du dessus (≈ 3 cm) : le plateau d'approche (`pose_seau → plateau_sous_pose_m`) doit
   être plus bas que ça.
3. Un seul seau : `vidange-remplissage --galet-range centrer seau_a` : les barres vont **en position** au
   contact du corps du seau sous le rebord (`formats → seau_a → centrage_hw_m` + `barres → jeu_centrage_m`),
   puis s'ouvrent : le plateau doit **descendre sous 0,48 avant** qu'elles passent au-delà de 0,235, puis
   remonter. Le seau doit être centré sans être écrasé. Régler `centrage_hw_m` (hw au contact) et le
   petit jeu. Si les barres forcent trop, le pilote lève ALM : l'outil dit « alarme du pilote des barres »
   et s'arrête ; c'est le comportement voulu (réduire `centrage_hw_m` d'un cran trop serré, ou augmenter le
   jeu).
4. `vidange-remplissage --galet-range --agitateur-au-garage poste seau_a` : le plateau descend, le chariot
   va au poste (y 0,135), le plateau remonte : le bord du seau doit être à **0,78** (0,775 pour le 5 L).

## Étape 4 : ranger un seau

1. Les places des files viennent du Stockage (tâche 35). En attendant, régler `rangement → files` pour une
   file réelle : `y` du chariot devant la file, `pousseur_m` (fin de la poussée vers le stockage, 0,325 au
   plus).
2. Seau au poste (étape 3), `vidange-remplissage --galet-range --agitateur-au-garage ranger seau_a file_1` :
   le plateau descend **en bas**, le chariot va à la file, le seau est pesé, le pousseur le pousse vers le
   stockage et rentre à son zéro. Le seau doit glisser droit, sans basculer. Il n'y a pas de poussée
   « plateau en haut » (bande du haut) : c'est voulu.

## Étape 5 : pose et prise double (avec la préhension)

L'ordre est celui du point 5 de la section « Remplissage » de `docs/decisions.md` (corrigé le 30/10 au
soir). À faire d'abord sur la maquette. **Main sur l'arrêt d'urgence.**

1. Simulateur sur un PC : `vidange-simulateur remplissage` doit aller au bout (2 seaux, le 1er avec une
   prise double).
2. Pose d'un seul seau A, avec la vraie préhension. Regarder chaque pas, dans cet ordre :
   - 1) avant la pose : barres à l'approche (hw 0,225), plateau sous 0,48 et sous la hauteur de pose ;
   - la tête descend avec le seau jusqu'à la hauteur de pose (lente sur les derniers cm) ; le seau ne
     touche ni les barres ni le plateau ;
   - 2) le plateau monte **lentement** jusqu'au contact du fond du seau : il doit s'arrêter dès que la
     balance le sent (`pose_seau → contact_kg`), sans soulever la tête. Noter la hauteur du contact
     (`vidange-remplissage etat`) : c'est la vraie hauteur de pose du format ;
   - 3) centrage : les barres serrent le seau (en position) ;
   - 4) barrière libre : la tête lâche le seau et remonte, puis les barres reviennent à l'approche, la
     balance lit un seul seau.
3. Prise double : deux seaux A emboîtés tenus par la tête (la barrière est coupée après le centrage). Le
   contact du plateau doit venir ≈ 3 cm plus bas qu'au point 2. Puis, dans cet ordre :
   - a) lâcher : chaque barre s'écarte de 1,5 cm ;
   - b) le plateau descend de 5 cm ;
   - c) la tête descend de 2,8 cm : la lèvre du seau du dessous arrive au niveau de la rainure des barres ;
   - d) les barres serrent sur la lèvre (entraxe = Ø haut + 6 mm) ;
   - e) le plateau monte lentement jusqu'au contact du fond du seau du dessous (la balance le sent) ;
   - f) la tête remonte avec le seau du haut ;
   - g) lâcher : les barres s'écartent de 1,5 cm ;
   - h) le plateau monte de 2,8 cm ;
   - i) la barrière doit être libre et la balance lire un seul seau ; puis centrage, la tête remonte avec le
     seau du dessus (à rendre au stockage) et les barres reviennent à l'approche.
   **Pendant toute la pose et la prise double, les barres restent sous 0,235** (elles ne traversent jamais
   les joues de l'élévateur plateau haut). Noter ce qui ne va pas, et mesurer les courses vraies
   (`prise_double → descente_plateau_m`, `descente_tete_m`, `tirage_m`, `remontee_plateau_m` ; `barres →
   lacher_m`, `jeu_rainure_m` ; `pose_seau → plateau_sous_pose_m`, `contact_kg`).
4. Force du tirage (f) : elle ne doit pas dépasser 35 N par barre (70 N lus par la tête) ; sinon la tête
   s'arrête et l'alarme le dit.
5. Refaire les points 2 et 3 avec des seaux B (pose à 0,5125, au-dessus des joues) : la prise double doit
   aller au bout, sans alarme.

## Étape 6 : modes couvercles et inspection, règle 9 de la préhension

1. `vidange-remplissage --galet-range --agitateur-au-garage couvercles` : chariot à y 0,50, plateau à 0,459,
   barres ouvertes ; le bac inox posé sur le plateau, la tige du retourneur sur sa barre. Puis
   `vidange-remplissage --galet-range barres 0.19` et `barres 0.30` : la tige ne touche rien. (Le lavage des
   couvercles avec le vrai chariot sera essayé quand les modules seront assemblés dans le programme.)
2. `vidange-remplissage --galet-range --agitateur-au-garage inspection` : plateau à 0,575, barres ouvertes,
   un arrêt de 45°.
3. Règle 9 (quand les modules seront assemblés dans le programme) : barres fermées (`barres 0.20`), mode
   des seaux, la tête de préhension au-dessus du plateau : sa descente sous 0,84 doit être **refusée**
   (même au mode manuel du téléphone). En mode couvercles, barres à 0,19, elle est permise (retourneur).

## Ce qu'il faut renvoyer

Les valeurs mesurées (origine des barres, hauteurs de pose, centrage et son jeu, bout du chariot, emprise
du chariot pour la règle 9 (`verrous → emprise_demi_x_m`, `emprise_mur_y_m`), approche et contact de la
pose (`pose_seau`), courses de la prise double,
files, vitesses, pas par tour des pilotes), à
écrire dans `machine.yaml` et `fluidnc/chariot.yaml` par une session de correction ; passer `exemple` à false
dans la partie `remplissage` quand tout est vrai.
