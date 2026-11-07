# Essai de la pose du couvercle sur le vrai matériel (tâche 41 bis)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent qu'une fausse tête, une fausse pile de
couvercles, un faux seau et une fausse balance. Cet essai se fait **après** l'essai de la préhension
(`essai-prehension.md`, vide et pesée étalonnés), celui du chariot de remplissage (`essai-remplissage.md`,
balance étalonnée) et celui de la fermeture (`essai-fermeture.md`, Hf et Hc mesurés). Compter 2 heures.

Le geste ne protège personne : le vide, le contact M8 et les pesées ne servent qu'à la machine. L'arrêt d'urgence
reste câblé comme d'habitude. Pendant que la tête descend, gardez les mains **loin de la tête, de la pile et du
seau**.

Il faut : une pile de couvercles propres sur la place des couvercles du stockage (x 2,27 à 2,29 ; y 0,84), un
seau plein de chaque format (A, B, C, D), un réglet, un feutre, une balance de cuisine (pour peser les couvercles).

## Avant de commencer

1. Arrêter le programme principal : `sudo systemctl stop vidange`.
2. Dans les commandes ci-dessous, `vidange-prehension` et `vidange-remplissage` veulent dire
   `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-prehension` (et de même pour l'autre).
3. Les chiffres à trouver sont dans `pi/reglages/machine.yaml`, partie `couvercle` (tous marqués EXEMPLE sauf ceux de
   la fiche), et `prehension → vitesses` (`couvercle_pile`, `couvercle_pose`). Après chaque changement :
   `vidange --verifier` doit dire « Réglages corrects ».
4. L'anse du seau plein doit être **rabattue vers le bas, côté y+** (règle du Stockage). Une anse relevée donne
   l'erreur « couvercle mal posé » : c'est voulu.

## Étape 1 : peser les couvercles

1. Peser **chaque format** de couvercle sur la balance de cuisine (3 couvercles, faire la moyenne). Écrire la masse
   dans `couvercle → formats → seau_… → masse_kg` (en kg : 0,13 pour 130 g).
2. Peser aussi **deux couvercles empilés** et noter la différence avec un seul : la tête doit voir ces ≈ 130 g de
   plus (voir l'étape 3). Si la tête ne voit pas cette différence, le dire dans la PR (point 3 de la fiche, § 5).
3. `couvercle → tolerance_pct` est à 30 % d'exemple : on le resserre à l'étape 3 si la pesée est stable.

## Étape 2 : la pile et le contact M8

1. Mettre une pile de 5 couvercles. Mesurer au réglet **la hauteur de la tôle du stockage** (0,496 m dans
   `stockage → plateau_z`) et **l'épaisseur du dernier couvercle** (9 mm d'exemple, `couvercle → pile →
   epaisseur_dernier_m`).
2. Mesurer le **pas d'empilage** (hauteur de la pile de 5 moins hauteur d'un seul, divisé par 4). Le Pi n'en a pas
   besoin (il trouve le haut de la pile au contact), mais c'est utile pour la suite.
3. `vidange-prehension etat` : la tête est en haut, le contact vaut « False ».

## Étape 3 : prendre un couvercle (étapes 1 à 6 de la fiche)

Le chariot de remplissage n'a pas besoin d'être préparé pour cette étape : le Pi ne fait que la prise.

1. Lancer `vidange-prehension couvercle seau_a` **avec un seau A plein sur le plateau** (voir l'étape 4 pour le
   chariot ; pour cette étape seule, on peut couper la commande dès que « Couvercle pris » s'affiche).
2. Regarder : la tête va au-dessus de la pile (**outil en y 0,83**, 1 cm de côté vers le mur), descend vite
   jusqu'à 3 cm au-dessus du haut prévu, puis lentement (20 mm/s) jusqu'au contact. Le **contact M8** arrive
   ≈ 3 mm après que la lèvre a touché.
3. La commande dit : « Couvercle pris : vide … kPa, poids … N ». Le vide doit être **−55 kPa ou plus bas**.
   Le poids doit être celui d'**un seul** couvercle (masse × 9,81).
4. Refaire la prise 3 fois. Noter le vide et le poids : choisir `tolerance_pct` pour que ces 3 poids soient bien
   dedans, et que deux couvercles empilés soient **dehors**.
5. **Erreurs à provoquer :**
   - Pile vide (ou plus qu'un couvercle sur la tôle) : « plus de couvercles », la tête remonte.
   - Ventouse bouchée avec un doigt de gant : « vide … pas atteint au couvercle après 2 essais ».
   - Coller deux couvercles avec un peu d'eau : « deux couvercles collés ». La tête les repose sur la pile,
     souffle, et refait la prise ; au 2ᵉ échec elle s'arrête avec l'alerte.

## Étape 4 : poser le couvercle sur le seau plein (étapes 7 à 14)

1. Poser à la main un seau A **plein**, anse rabattue, sur le plateau. Préparer le chariot comme le programme :
   `vidange-remplissage --manivelle-en-bas --micropore-rentre --galet-range couvercle-preparer seau_a`.
   Attendu : barres ouvertes, plateau à **H_app** (A 0,175), chariot à **y 0,50**, puis la ligne « P0 : … kg ».
2. Lancer `vidange-prehension couvercle seau_a`. Regarder :
   - la tête emporte le couvercle (le vide est surveillé : s'il passe au-dessus de −40 kPa, arrêt sur place) ;
   - elle s'arrête au-dessus du seau, **outil en (0,925 ; 0,49)** : le couvercle doit arriver **centré** sur le seau ;
   - descente vite jusqu'à `Z_pose + 0,040`, puis **10 mm/s** jusqu'au contact : la jupe du couvercle touche le
     bord du seau. **La tête n'appuie pas** ;
   - « souffler » un court instant, puis la tête se dégage lentement (20 mm/s, 2 cm) et remonte.
3. La commande dit « Couvercle posé sur le seau (sans appuyer) ». **Le couvercle est posé, pas clipsé.**
4. **Mesurer `Z_pose`** : dans le journal (`journalctl -u vidange` ou la sortie), la ligne « Couvercle : contact à
   la pose à … m (attendu 0,439 m) ». Si l'écart dépasse 8 mm, noter la vraie valeur et la dire dans la PR
   (`Hc` du couvercle est peut-être à revoir : `essai-fermeture.md`, étape 5).
5. Contrôle balance : `vidange-remplissage --manivelle-en-bas --micropore-rentre --galet-range
   couvercle-controler seau_a`. L'outil prend P0 tout de suite, puis attend 20 s : posez le couvercle **à la main**
   sur le seau pendant ces 20 s. Attendu : « Balance : P − P0 = +0,1… kg » (un couvercle).
6. Recommencer pour B et D (changer le seau et le format) : ils descendent **droit**, outil en (0,925 ; 0,49).
7. **Format C : descente décalée** (tâche 45 septies, fiche § 5.1 ; **testé sur le vrai matériel : non**). Le
   recul du servo du micropore est **annulé** : rien à faire sur le micropore, sa tête reste escamotée comme
   d'habitude. Seau C plein au poste, couvercle C tenu, vitesses divisées par 2 :
   - l'outil arrive en **(0,925 ; 0,498)**, 8 mm vers l'allée (vérifier avec `vidange-prehension etat`) ;
   - il descend jusqu'à la face **0,545**. Filmer le côté mur : entre les faces 0,65 et 0,58, le bord du
     couvercle doit passer à **au moins 8 mm** de la **plaque fixe du micropore** (bord à r 160 de l'axe du
     seau) et du bout de son rail (Maquette : 10,3 mm à la plaque, 13,5 mm au rail, 12,8 mm au rouleau) ;
   - à la face 0,545 (tout le couvercle, jupe comprise, sous la plaque du micropore, bas à 0,56), l'outil
     revient à **y 0,49**, sans changer de hauteur, à 10 mm/s (≈ 0,8 s) ;
   - puis descente normale : rapide jusqu'à 0,479, lente jusqu'au contact vers 0,439. La jupe doit recouvrir
     le bord du seau.
   Moins de 5 mm de jeu, ou si ça touche : **arrêt d'urgence**, le dire dans la PR. Refaire avec un seau C dont
   l'anse est relevée (erreur 10a) : la tête remonte **avec** le couvercle par le même chemin à l'envers
   (0,545, retour à y 0,498, puis en haut) ; regarder le même jeu à la remontée.

8. **Format C : toute remontée avec le couvercle encore tenu** (tâche 45 octies, fil Préhension du 07/11,
   § 5.1 ; **testé sur le vrai matériel : non**). Même installation qu'au point 7, vitesses divisées par 2 :
   - **erreur 10a** (anse relevée) ou **10b** (plateau vide) : la tête remonte **tout droit à 10 mm/s** jusqu'à la
     face 0,545 (de 0,44 à 0,545 : ≈ 10 s), puis va à **y 0,498** sans changer de hauteur, puis monte en haut ;
   - **arrêt avant le lâcher** : si une alarme arrête la tête pendant l'approche lente (sous 0,545, à y 0,49),
     couvercle encore tenu, la pose refaite après l'acquittement et le Go **commence** par le même chemin à
     l'envers (0,545 à 10 mm/s, y 0,498, puis en haut), jamais par une montée droite à y 0,49. Ne pas
     provoquer l'alarme en coupant l'air ou une carte (le couvercle tomberait) : regarder ce cas quand il
     arrive, ou demander à Claude une façon sûre de le faire ;
   - **choc** : ne pas en provoquer exprès (personne à côté de la tête qui bouge). Sur la machine imaginaire,
     la remontée lente d'après un choc s'arrête à la face 0,545 au plus quand le couvercle C est tenu sous
     0,545 à y 0,49 ;
   - **après le lâcher** (couvercle posé) : la tête seule remonte tout droit, comme pour A, B et D.
   À chaque remontée, filmer le côté mur : au moins 8 mm entre le couvercle et la plaque fixe du micropore.

## Étape 5 : les erreurs, une par une (seau A)

1. **Anse relevée** (relever l'anse du seau plein avant l'étape 4) : « couvercle mal posé … vérifier l'anse du
   seau ». La tête remonte **avec** le couvercle (elle ne le lâche pas). Rabattre l'anse, acquitter, donner le Go.
2. **Pas de seau** (plateau vide) : « pas de contact … pas de seau ou couvercle tombé ».
3. **Couvercle collé à la ventouse** (mettre un peu de ruban adhésif double face sur la ventouse) : au dégagement,
   « le M8 voit encore le couvercle … resté collé à la ventouse ».
4. **Balance** : retirer le couvercle à la main juste après la pose : « couvercle pas sur le seau ».
5. **Couvercle lâché en route** : couper l'air (vanne d'isolement) pendant le trajet : arrêt sur place,
   « couvercle lâché en route ».
6. Remettre tout comme avant (air ouvert, ruban retiré).

## Étape 6 : le cycle entier, un seau

1. Le programme principal ne lance rien tout seul (règle 6) et le poste « couvercle » n'est « pas lancé » tant
   que `couvercle → exemple` est à `true` sur la vraie machine : le journal le dit.
2. Quand tous les chiffres EXEMPLE ont été vus (masses, tolérance, fenêtre du contact, haut de la pile, durées du
   vide, vitesses), passer `couvercle → exemple` à `false`, puis `vidange --verifier`.
3. Après un lot : un couvercle posé, **la fermeture clipse juste après** (la tête ne tient rien et est remontée
   au-dessus de z 0,60 : sinon le bras de fermeture ne sort pas).

## Ce qui ne peut pas encore s'essayer

- **Le cycle complet** : il manque encore les cartes de la griffe (enchaînée au lot depuis la tâche 45 sexies), les cartes du chariot et de la tête branchées au
  programme principal (la lecture du QR du flanc est écrite : tâche 40 ter). Ici, le chariot et la tête se commandent avec
  leurs outils.
- **Les impulsions du venturi pendant le trajet** (fiche, étape 7 : « nouvelle impulsion si le vide passe
  au-dessus de −50 kPa ») : le Pi garde la vanne de vide ouverte pendant tout le trajet (question 2 de la PR).

Noter les chiffres trouvés et les remarques dans la PR, ou les donner à la prochaine session.
