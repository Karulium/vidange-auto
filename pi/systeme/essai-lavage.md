# Essai du lavage des seaux sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent que de **faux**
FluidNC, une **fausse** eau (faux flotteur), un **faux** vide et des seaux **imaginaires** (simulateur).

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
  `air_col_lavage`, `chauffage_lavage`) et son numéro : recopier le plan de câblage.
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
3. Le chauffage : `vidange-lavage sortie chauffage_lavage 3` doit être **refusé** tant que le fût n'est pas
   rempli (« Chauffage refusé »). C'est voulu.
4. Flotteur : le soulever à la main et lancer `vidange-lavage etat` : « haut » ; le lâcher : « bas ».

## Étape 2 : remplir, chauffer, vider

1. `vidange-lavage remplir` : la vanne à bille se ferme, l'eau coule jusqu'au flotteur haut, puis se coupe.
   Le temps est mesuré et **gardé** (`pi/donnees/lavage.json`) : les remplissages suivants sont refusés
   au-delà de ce temps + 20 %. Regarder que l'eau s'arrête **bien sous les poulies**. Si le premier
   remplissage a été faussé (robinet mal ouvert), effacer `pi/donnees/lavage.json` et recommencer.
2. Fût plein, flotteur haut : `vidange-lavage sortie chauffage_lavage 5` : le relais statique alimente la
   prise (voyant de l'appareil). Le Pi ne le fait jamais pompe en marche ni flotteur bas.
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
   - elle tourne au départ des tours du seau (−350°), descend dans les brosses (le seau écarte les brosses
     extérieures), puis lentement jusqu'à l'appui de 80 N. Si l'appui ne vient pas (« appui de 80 N sur le
     noyau pas atteint »), régler `lavage → brossage → face_contact_z` (face quand le fond du seau touche le
     noyau) et `course_appui_m` ;
   - arrosage, passe 1 (noyau 100 puis 200 tr/min, le seau tourne), passe 2 (couronne, le seau tourne dans
     l'autre sens), rinçage, la pompe remet le niveau, remontée, jet d'air (un tour en ≈ 4 s), égouttage,
     retour au coude, seau reposé.
3. Regarder le seau : intérieur, fond, paroi, **bord** et **col** propres ? Sinon, régler les durées et les
   vitesses des passes (`brossage → passe_1`, `passe_2` ; les tours du seau doivent tenir dans la course
   de la tête, c'est vérifié au démarrage), le décalage du brossage par format (`decalage_brossage_m`,
   vers +x), la remontée avant la passe 2 (`remontee_passe_2_m`) et, pour le jet d'air, le décalage vers la
   buse et la hauteur du bord (`jet_decalage_m`, `jet_bord_z`).
4. Recommencer avec un seau B, C et D (`seau_b`...), en mesurant leur `contact_z`. Noter le temps donné
   (« Seau lavé en … s ») : la fiche estime 60 à 70 s.
5. Pendant un lavage, soulever le panneau du poste du fût **un peu** (sans l'ouvrir en grand) : la tête doit
   s'arrêter (« le panneau du poste du fût a bougé ») et l'eau se couper.
6. `vidange-lavage vider` à la fin.

## Étape 5 : le simulateur avec les vrais chiffres

Une fois les chiffres réglés, `vidange-simulateur lavage` rejoue une série (remplissage, 3 seaux,
vidange) avec eux. Puis passer `exemple: false` dans la partie `lavage` de `machine.yaml`, et
`exemple: false` sur les lignes du lavage de `docs/entrees-sorties.yaml` devenues vraies.

## Si quelque chose ne va pas

Noter ce qui s'est passé (message de l'outil, photo, vidéo) et le mettre dans une PR de correction : une
nouvelle session corrige la tâche 21 (phrase à copier dans `docs/taches.md`).
