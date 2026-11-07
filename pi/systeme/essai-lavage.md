# Essai du lavage des seaux, des couvercles et des bocaux sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent que de **faux**
FluidNC, une **fausse** eau (faux flotteur), un **faux** vide, des seaux **imaginaires** (simulateur), un
**faux** retourneur de couvercles et une **fausse** caméra (repère du couvercle, photo du bac).

Cette procédure se fait une fois le fût de lavage monté (noyau, couronne, rampes, buse du jet d'air,
flotteur, pompe, vannes, thermoplongeur), la carte n° 3 et la carte n° 4 câblées, et la préhension
essayée (`essai-prehension.md`). Elle vérifie que les cartes font ce que le Pi attend, puis mesure les
chiffres marqués EXEMPLE (`pi/reglages/machine.yaml`, partie `lavage` ; `fluidnc/prehension.yaml`,
axes B et C ; `pi/reglages/fluidnc.yaml`). Compter une journée.

La sécurité des personnes est câblée (arrêt d'urgence, portes, panneau du poste). Les verrous du logiciel
ne protègent que la machine : garder la main sur l'arrêt d'urgence, les doigts loin des brosses et de la
tête. Le thermoplongeur ne doit **jamais** chauffer à sec : pendant tout l'essai, regarder le niveau d'eau
quand il est alimenté.

## Avant de commencer

- `fluidnc/mycelium_lavage.yaml` et `fluidnc/prehension.yaml` sont complétés avec les **vraies broches**
  (plan de câblage) et les vrais pas par degré du noyau et de la couronne, puis envoyés aux cartes (page
  web → « Mises à jour »). Tant qu'ils disent « EXEMPLE », ils sont refusés.
- `pi/reglages/fluidnc.yaml` dit sur quelle carte est chaque signal du lavage (`flotteur_lavage`,
  `eau_reseau_lavage`, `vanne_vidange_lavage`, `pompe_lavage`, `vanne_rampes_lavage`, `rincage_lavage`,
  `air_col_lavage`) et son numéro : recopier le plan de câblage. Fiches de l'Implantation du 07/11/2026
  (`sorties-carte-3.md`, `sorties-carte-4.md`) : carte n° 3, P0 et P1 pont en H du demi-tour, P2 relais de
  la pompe (fusible 8 A), P3 eau, P4 vanne à bille, P5 jet d'air du col ; P6 (verrou du plateau) et P7
  (vanne 3 voies) sont des EXEMPLES, et le rinçage est en P3 de la carte n° 4 (EXEMPLE). Le **chauffage**
  n'est sur aucune carte FluidNC : c'est le relais du Pi `relais_chauffage_lavage` (voie en EXEMPLE dans
  `docs/entrees-sorties.yaml`, à recopier de la fiche des relais du Pi quand elle existera).
- Le programme principal est arrêté (`sudo systemctl stop vidange`) : une seule liaison par carte.
- Prise d'origine des cartes n° 1, 3 et 4 faite (`$H`), sans alarme. La griffe est **en haut**.
- Le panneau long du poste du fût est **rabattu** (mode lavage), le fût de lavage en place, sa bonde
  raccordée, le robinet d'eau du réseau ouvert. Le thermoplongeur est réglé à 50 °C sur l'appareil.

Dans les commandes ci-dessous, `vidange-fluidnc` et `vidange-lavage` veulent dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc` (et de même pour l'autre).

## Étape 1 : les sorties et le flotteur (sans seau)

1. `vidange-lavage etat` : il dit le flotteur (fût vide : « bas »), la tête et le vide.
2. Une sortie à la fois, 3 secondes, en regardant ce qui se passe :
   - `vidange-lavage sortie eau_reseau_lavage 3` : l'eau du réseau coule dans le fût ;
   - `vidange-lavage sortie vanne_vidange_lavage 20` : la vanne à bille s'ouvre (mesurer le temps : il va
     dans `lavage → eau → vanne_vidange_s`), puis se referme quand la sortie s'éteint ;
   - `vidange-lavage sortie vanne_rampes_lavage 15` : la vanne 3 voies passe sur la voie des **rampes**
     (au repos : voie de la **bonde**). Mesurer le temps (`vanne_rampes_s`). Si c'est inversé, le dire dans
     la PR de correction (le code suppose « commandée = rampes ») ;
   - `vidange-lavage sortie rincage_lavage 3` : l'eau propre sort des rampes ;
   - `vidange-lavage sortie air_col_lavage 2` : l'air sort de la buse du col ;
   - la pompe (`pompe_lavage`) seulement avec de l'eau dans le fût et la vanne à bille ouverte (étape 2).
   Si une sortie en commande une autre : échanger les numéros dans `pi/reglages/fluidnc.yaml`.
3. Le chauffage (relais du Pi, qui alimente la commande du SSR) : `vidange-lavage sortie
   relais_chauffage_lavage 3` doit être **refusé** tant que le fût n'est pas rempli (« Chauffage refusé »).
   C'est voulu : le logiciel n'allume le chauffage que « flotteur haut » et « pompe arrêtée », sinon il
   attend et le dit dans le journal. **Ce n'est pas la sécurité** : elle est câblée (voir l'étape 2 bis).
4. Flotteur : le soulever à la main et lancer `vidange-lavage etat` : « haut » ; le lâcher : « bas ».

## Étape 2 : remplir, chauffer, vider

1. `vidange-lavage remplir` : la vanne à bille se ferme, l'eau coule jusqu'au flotteur haut, puis se coupe.
   Le temps est mesuré et **gardé** (`pi/donnees/lavage.json`) : les remplissages suivants sont refusés
   au-delà de ce temps + 20 %. Regarder que l'eau s'arrête **bien sous les poulies**. Si le premier
   remplissage a été faussé (robinet mal ouvert), effacer `pi/donnees/lavage.json` et recommencer.
2. Fût plein, flotteur haut : `vidange-lavage sortie relais_chauffage_lavage 5` : le relais statique alimente la
   prise (voyant de l'appareil). Le Pi ne le fait jamais pompe en marche ni flotteur bas.
2 bis. **La sécurité câblée du chauffage** (à faire avant tout chauffage prolongé, sans le Pi qui commande :
   `sudo systemctl stop vidange`, et le relais du Pi fermé à la main ou par `vidange-lavage sortie
   relais_chauffage_lavage 30` fût plein). Le flotteur alimente `relais_flotteur` (armoire), dont un
   contact est en série dans la commande du SSR ; son 2e contact recopie le flotteur sur `flotteur_lavage`
   (entrée de la carte n° 3). Vérifier, **fût rempli puis vidé peu à peu** :
   - flotteur haut : le SSR a sa commande (voyant de l'appareil) quand le relais du Pi est fermé ;
   - flotteur **bas** (baisser le niveau à la main) : le SSR perd sa commande **même relais du Pi fermé** ;
   - débrancher le fil du flotteur (ou le couper) : même résultat, le SSR n'a plus de commande ;
   - `vidange-lavage etat` : « flotteur : haut » ou « bas » suit le 2e contact. Si le 2e contact est
     inversé, le dire dans la PR de correction.
   Si l'un de ces essais chauffe quand même : **arrêter, couper le thermoplongeur, ne pas continuer**.
   La 2e barrière (thermostat de sécurité à réarmement manuel, demandée au Lavage) est à essayer avec la
   fiche du Lavage.
3. `vidange-lavage vider` : vanne 3 voies vers la bonde, vanne à bille ouverte, pompe jusqu'au flotteur bas,
   encore 60 s, puis arrêt et vanne fermée. Regarder qu'il ne reste presque plus d'eau. Mesurer la durée
   pour `lavage → eau → vidange_max_s` (prendre une bonne marge).
4. `vidange-lavage remplir` à nouveau (pour l'étape 4). La pompe vers les rampes (arrosage) se voit à
   l'étape 4.

## Étape 3 : les brosses et leur verrou

1. `vidange-lavage brosses` : la rotation du noyau, tête vide et en haut, doit être **refusée**
   (« Refusé, comme prévu »). C'est le verrou : noyau et couronne ne tournent jamais à vide.
2. Sens des brosses, **sans seau, mains loin** : `vidange-fluidnc console prehension`, puis
   `$J=G91 B360 F3600` (un tour du noyau en 6 s) et `$J=G91 C360 F3600` (un tour de la couronne). Ils
   doivent tourner dans le sens « en avant » de la fiche du module ; sinon, inverser le sens du pilote
   (câblage). Puis `$J=G91 A90 B360 F3600` : la tête et le noyau tournent **ensemble**. Ces commandes à la
   console n'ont pas de verrou : ne pas les refaire avec un seau.
3. Les alarmes des pilotes du noyau et de la couronne (`alarme_noyau_lavage`, `alarme_couronne_lavage`)
   doivent mettre la carte n° 4 en alarme (débrancher un moteur, pilote sous tension : alarme).

## Étape 4 : un seau lavé

1. Poser un seau **A** retourné (bord en bas) sur une table dans le couloir du seau retourné, par exemple
   axe de la tête en (1,3 ; 0,74). Mesurer la hauteur de la face de la tête quand elle touche le fond du
   seau : c'est `contact_z` (ex. 0,95).
2. `vidange-lavage laver seau_a 1.3 0.74 0.95` en regardant, main sur l'arrêt d'urgence :
   - la tête prend le seau, va en y 0,74, vers −x jusqu'au coude (0,45 ; 0,74), puis droit vers le fût ;
     **regarder la paroi côté stockage** : le seau doit passer au-dessus avec de la marge ;
   - elle tourne au départ de la passe 1 (−500°), descend dans les brosses (le seau écarte les brosses
     extérieures), puis lentement jusqu'à l'appui de 80 N. Si l'appui ne vient pas (« appui de 80 N sur le
     noyau pas atteint »), régler `lavage → brossage → face_contact_z` (face quand le fond du seau touche le
     noyau) et `course_appui_m` ;
   - arrosage, passe 1 (noyau 100 puis 200 tr/min, le seau tourne), la tête revient à 0, puis à +500°,
     passe 2 (couronne, le seau tourne dans l'autre sens, **sans remonter**), la tête revient à 0 ;
     rinçage, la pompe vide jusqu'au flotteur bas, la vanne 3 voies revient sur « rampes », l'eau du réseau
     remet le flotteur haut (quelques secondes) ; remontée, jet d'air (un tour en ≈ 4 s), égouttage,
     retour au coude, seau reposé.
   - **Cordon spiralé** : pendant les passes, la tête va jusqu'à ± 500°. Regarder le cordon du vide et des
     fils : s'il force ou frotte, arrêter et passer `prehension_a → course` à [-370, 370] et
     `depart_passe_deg` à 370 dans `machine.yaml` (en raccourcissant les tours des passes).
3. Regarder le seau : intérieur, fond, paroi, **bord** et **col** propres ? Sinon, régler les durées et les
   vitesses des passes (`brossage → passe_1`, `passe_2` ; les tours du seau doivent tenir dans la course
   de la tête, c'est vérifié au démarrage), le décalage du brossage par format (`decalage_brossage_m`,
   vers +x) et, pour le jet d'air, le décalage du centre du seau devant la buse, en relatif au centre du fût
   de lavage (`jet_decalage`, en m), et la hauteur du bord (`jet_bord_z`), par format.
4. Recommencer avec un seau B, C et D (`seau_b`...), en mesurant leur `contact_z`. Noter le temps donné
   (« Seau lavé en … s ») : la fiche estime 60 à 70 s.
5. Pendant un lavage, soulever le panneau du poste du fût **un peu** (sans l'ouvrir en grand) : la tête doit
   s'arrêter (« le panneau du poste du fût a bougé ») et l'eau se couper.
6. **Fuite ou siphon** : fût plein, pompe arrêtée, vanne à bille ouverte, ouvrir un instant la vidange à
   la main (ou soulever le flotteur puis le laisser retomber pendant un `vidange-lavage laver …`) : l'outil
   doit s'arrêter (« fuite ou siphon ») et la vanne à bille se fermer.
7. `vidange-lavage vider` à la fin.

## Étape 5 : les bocaux au lave-bocal

1. Fût **vidé** (fin de la série de seaux). Poser le lave-bocal sur l'anneau de rive du fût de lavage,
   ouvrir son robinet (vanne quart de tour). Mesurer la hauteur de son plateau (≈ 5 mm au-dessus de
   l'anneau) et l'écrire dans `lavage → lave_bocal → plateau_z`, avec son centre (`centre`).
2. Peser un bocal vide (page web, pesée de la préhension) et corriger `prehension → objets → bocal_vide`
   (`poids_n`).
3. Poser un bocal vide **retourné** sur une table (par exemple axe de la tête en (1,4 ; 0,75)), mesurer
   `contact_z` (face de la tête quand elle touche son fond), puis
   `vidange-lavage bocal bocal_vide 1.4 0.75 0.95` : la tête prend le bocal, l'appuie sur le plateau (l'eau
   doit jaillir dans le bocal), attend, remonte, égoutte au-dessus du fût, et le repose. Régler l'appui et le
   temps (`appui_n`, `duree_s`) : le bocal doit être propre et le rince-verre ne pas forcer.
4. Même chose avec une capsule (`vidange-lavage bocal capsule …`, tenue par les aimants).
5. `vidange-lavage vider` à la fin (la vidange évacue l'eau du rince-verre), puis enlever le lave-bocal.

## Étape 6 : les couvercles (après les tâches 22 et 34)

Le lavage des couvercles a besoin de la caméra du plafond (repère du couvercle, photo du bac : tâche 22)
et des barres du chariot de remplissage (retourneur : tâche 34). Tant qu'elles ne sont pas faites, on ne
peut l'essayer qu'au simulateur (`vidange-simulateur lavage_couvercles`). Quand elles le seront :

1. Coller le repère sur le dessus de chaque couvercle, près du bord. Vérifier le sens du repère : quand la
   tête tourne dans le sens +, l'angle vu par la caméra doit grandir (sinon `sens_repere: -1`).
2. Couvercle tenu face « dessous » vers le bas, descendre doucement au-dessus du noyau : noter la hauteur de
   la face quand le couvercle touche les brosses avec ≈ 15 N (`bas_dessous_z` par format = cette hauteur −
   l'épaisseur sous la face). Même chose couvercle retourné (`bas_dessus_z`, EXEMPLE aujourd'hui).
3. Retourneur : mesurer la hauteur du lâcher (`lacher_face_z`, au-dessus de 0,75), la face au contact d'un
   couvercle à plat dans le bac (`bac_contact_z`), et vérifier que le couvercle se retourne sur la tige.
4. Couper la barrière lumineuse avec la main pendant le mode couvercles : la machine doit se mettre en
   pause avec le message.

## Étape 7 : le simulateur avec les vrais chiffres

Une fois les chiffres réglés, `vidange-simulateur lavage` rejoue une série (remplissage, 3 seaux,
vidange) avec eux, `vidange-simulateur lavage_bocaux` et `vidange-simulateur lavage_couvercles` les
deux autres séries. Puis passer `exemple: false` dans la partie `lavage` de `machine.yaml`, et
`exemple: false` sur les lignes du lavage de `docs/entrees-sorties.yaml` devenues vraies.

## Si quelque chose ne va pas

Noter ce qui s'est passé (message de l'outil, photo, vidéo) et le mettre dans une PR de correction : une
nouvelle session corrige la tâche 21 (seaux) ou 21 bis (couvercles, bocaux) (phrase à copier dans
`docs/taches.md`).
