# Essai du chariot de remplissage sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent qu'un **faux**
FluidNC, une **fausse** balance, une **fausse** barrière et des seaux **imaginaires** (simulateur).

Cette procédure se fait une fois la carte FluidNC n° 2 câblée (avance, plateau, rotation, barres, pousseur,
fins de course, barrière lumineuse), la carte de pesée du plateau étalonnée (`pesee/essai-etabli.md`), le
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
- **Rien au-dessus du plateau** : la prise d'origine fait **monter** le plateau jusqu'à son fin de course
  haut (≈ 0,578). Griffe et préhension en haut, agitateur du mycélium au garage manivelle en haut.
- Pas de seau sur le plateau pour les étapes 1 à 3.

Dans les commandes ci-dessous, `vidange-fluidnc`, `vidange-pesees` et `vidange-remplissage` veulent dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc` (et de même pour les autres).
Les options `--agitateur-au-garage --galet-range --micropore-rentre` de `vidange-remplissage` disent qu'on a
**vu** l'agitateur au garage manivelle en haut, le bras du galet rangé et la tête du micropore rentrée (ces
modules ne sont pas encore écrits) : ne les mettre que si c'est vrai.

## Étape 1 : ce que la carte n° 2 sait faire (console)

1. `vidange-fluidnc console chariot`, puis `$H` : le plateau monte jusqu'à son fin de course haut, puis
   redescend de 3 mm ; les barres s'ouvrent jusqu'à leur origine côté mur ; le pousseur va à son origine ;
   puis le chariot va à son origine en y. `?` : `MPos` doit dire Y = 130, Z = 575, B = 0, C = 0.
   - Plateau : mesurer le **dessus** du plateau au-dessus du sol de référence du portique : il doit être à
     0,575. Sinon, régler `mpos_mm` de Z dans `fluidnc/chariot.yaml`.
   - Chariot : mesurer le y de l'**axe du plateau** dans le repère du portique : il doit être celui de
     `mpos_mm` de Y (130 mm = 0,130). Sinon, le régler.
2. Barres : mesurer, barres à l'origine, la distance de l'axe d'une barre à l'axe du plateau (hw) : la
   fiche dit ≈ 0,309. Écrire la valeur mesurée dans `machine.yaml → remplissage → barres → origine_hw_m`.
   `$J=G90 B-189.5 F2400` : les barres se ferment à hw = origine − 0,1895 ; mesurer, c'est le minimum
   (0,1195 attendu). Chronométrer l'ouverture complète (`$J=G90 B-4 F4800`) : la fiche dit ≈ 2,3 s.
3. `$J=G91 A90 F3600` : le plateau tourne d'un quart de tour (sens positif = sens inverse des aiguilles
   d'une montre vu d'en haut, comme les angles de la caméra). Sinon, inverser le sens du pilote.
4. Pousseur : `$J=G90 C160 F3000` : il va au milieu de sa course. Vérifier que c'est bien « rentré » (rien
   ne dépasse sur le plateau). Sinon, mesurer la position rentrée et la mettre dans
   `remplissage → pousseur_rentre_m` (et répondre à la question de la PR de la tâche 34).
5. Barrière lumineuse : `?`, puis couper le faisceau avec la main : la lettre `0` doit apparaître dans
   `Pn:` ; disparaître quand on retire la main.
6. Courant réduit : `M64 P0`, puis pousser les barres à la main : elles doivent céder plus facilement
   (≈ 30 N par barre au lieu du plein couple). `M65 P0` : retour au plein courant.

## Étape 2 : l'outil du Pi

1. `vidange-remplissage etat` : position des 5 axes (dans le repère du portique), barrière, balance (≈ 0 kg
   à vide), et « pose permise : oui ». Comparer avec les mesures de l'étape 1.
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
     de 0,515).
4. Chariot du fût sorti (pas « en place ») : `vidange-remplissage aller 0.85` → **refusé** (le bout du
   chariot passerait devant la 3e file). Mesurer, chariot à y 0,785, où est son bout côté allée :
   `remplissage → verrous → bout_y_m` = bout − 0,785 (0,09 en exemple).

## Étape 3 : un seau vide posé à la main

1. `vidange-remplissage --galet-range --agitateur-au-garage pose seau_a` : barres ouvertes, chariot à y 0,50,
   plateau à la hauteur de pose du seau A.
2. Poser à la main **un** seau A vide au centre du plateau : la barrière doit rester **libre**. En poser un
   2e emboîté dans le premier : elle doit être **coupée** (sinon, régler `formats → seau_a → pose_plateau_z`
   pour que le bord d'un seul seau passe sous le faisceau, celui de deux au-dessus). Refaire pour chaque
   format (B : 0,5125, fiche).
3. Un seul seau : `vidange-remplissage --galet-range centrer seau_a` : les barres viennent au contact du
   corps du seau sous le rebord, au courant réduit, puis s'ouvrent. Le seau doit être centré sans être
   écrasé. Régler `formats → seau_a → centrage_hw_m` (hw au contact).
4. `vidange-remplissage --galet-range --agitateur-au-garage poste seau_a` : le plateau descend, le chariot
   va au poste (y 0,135), le plateau remonte : le bord du seau doit être à **0,78** (0,775 pour le 5 L).

## Étape 4 : ranger un seau

1. Les places des files viennent du Stockage (tâche 35). En attendant, régler `rangement → files` pour une
   file réelle : `y` du chariot devant la file, `pousseur_m` (fin de la poussée, du bon côté).
2. Seau au poste (étape 3), `vidange-remplissage --galet-range --agitateur-au-garage ranger seau_a file_1` :
   le plateau descend, le chariot va à la file, le seau est pesé, le pousseur le pousse sur la file et
   rentre. Le seau doit glisser droit, sans basculer.

## Étape 5 : prise double et séparation (avec la préhension)

À faire avec le projet mécanique sous les yeux : l'ordre des gestes de la fiche est suivi à la lettre, mais
il reste une question (voir la PR de la tâche 34). **Main sur l'arrêt d'urgence.**

1. Simulateur sur un PC : `vidange-simulateur remplissage` doit aller au bout (2 seaux, le 1er avec une
   prise double).
2. Sur la machine, avec la vraie préhension et deux seaux emboîtés : regarder chaque pas (la tête remonte de
   2 cm, barres + 1,5 cm, la tête redescend de 4,8 cm, barres dans la rainure, le plateau monte au contact,
   tirage de 2 cm, barres + 1,5 cm, le plateau remonte de 2,8 cm). Noter ce qui ne va pas.
3. Force du tirage : elle ne doit pas dépasser 35 N par barre (70 N lus par la tête) ; sinon la tête
   s'arrête et l'alarme le dit.

## Étape 6 : modes couvercles et inspection

1. `vidange-remplissage --galet-range --agitateur-au-garage couvercles` : chariot à y 0,50, plateau à 0,459,
   barres ouvertes ; le bac inox posé sur le plateau, la tige du retourneur sur sa barre. Puis
   `vidange-remplissage --galet-range barres 0.19` et `barres 0.30` : la tige ne touche rien. (Le lavage des
   couvercles avec le vrai chariot sera essayé quand les modules seront assemblés dans le programme.)
2. `vidange-remplissage --galet-range --agitateur-au-garage inspection` : plateau à 0,575, barres ouvertes,
   un arrêt de 45°.

## Ce qu'il faut renvoyer

Les valeurs mesurées (origine des barres, hauteurs de pose, centrage, bout du chariot, files, vitesses), à
écrire dans `machine.yaml` et `fluidnc/chariot.yaml` par une session de correction ; passer `exemple` à false
dans la partie `remplissage` quand tout est vrai.
