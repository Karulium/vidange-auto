# Essai du bocal neuf de semence sur le vrai matériel (tâche 19 quater)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent qu'une fausse tête, de faux bocaux, de fausses
boîtes et un faux porte-bocal. Cet essai se fait **après** l'essai de la préhension (`essai-prehension.md` : vide,
pesée étalonnée, rotation de la tête), celui du porte-bocal (`essai-porte-bocal.md` : mors, `contact_capsule_bocal`,
méplats) et celui du stockage (`essai-stockage.md`). Compter une demi-journée.

Le geste ne protège personne : l'appui, le M8, les pesées et le calage du moteur ne servent qu'à la machine.
L'arrêt d'urgence reste câblé comme d'habitude. Pendant que la tête descend ou tourne, gardez les mains **loin de la
tête, des bocaux, des boîtes et du porte-bocal**.

**Mise à jour (tâche 24) : le calage est maintenant l'ALM du pilote de la rotation (`alarme_rotation_tete`), plus l'erreur du codeur ; voir `essai-derive.md` pour le réglage du pilote et la remise à zéro de l'ALM. Le paragraphe qui suit est l'ancienne situation.**

**Ce que cet essai ne peut pas faire tout de suite.** Le Pi ne sait pas encore lire l'erreur du codeur de la rotation
de la tête (c'est elle qui dit « le moteur cale »). Tant que cette lecture n'est pas branchée, la commande
`vidange-prehension bocal-neuf` **refuse de partir, avant tout mouvement,** avec le message « l'erreur du codeur de
la rotation de la tête n'est pas lue, le calage du moteur ne peut pas être vu : pas de mouvement ». C'est voulu : sans
cette lecture, une capsule coincée ferait forcer le moteur. L'étape 0 ci-dessous le vérifie. Les étapes 1 à 3 se font
déjà avec les outils qui existent ; les étapes 4 à 8 attendent la réponse à la question 1 de la PR.

Il faut : 3 bocaux de semence stérilisés (capsule fermée, QR collé sur la capsule), 5 couvercles percés, 3 capsules
vides, une balance de cuisine, un dynamomètre à couple (ou clé dynamométrique) pour le couple d'ouverture, un
réglet, un feutre.

## Avant de commencer

1. Arrêter le programme principal : `sudo systemctl stop vidange`.
2. Dans les commandes ci-dessous, `vidange-prehension` veut dire
   `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-prehension`.
3. Les chiffres à trouver sont dans `pi/reglages/machine.yaml`, partie `bocal_neuf` (tous marqués EXEMPLE sauf ceux
   de la fiche) et `prehension → vitesses` (`bocal_levee`, `bocal_col`, `bocal_appui`). Après chaque changement :
   `vidange --verifier` doit dire « Réglages corrects ».
4. La **manivelle du mycélium doit être en bas** et arrêtée (on le dit à la commande par `--manivelle-en-bas`), la
   caméra du dosage à 0°, le chariot de remplissage reculé ou au poste.

## Étape 0 : la commande dit non, comme prévu

1. Poser un bocal sur la **première place de semence** (`semence_0_0`, x 1,21 ; y 0,415).
2. `vidange-prehension bocal-neuf semence_0_0 pleurote_grise SEM-0001 0 12 --manivelle-en-bas`
   (place, variété, QR lu à la main, capsules déjà dans leur boîte, couvercles percés dans la leur).
3. Attendu aujourd'hui : « ÉCHEC : … l'erreur du codeur de la rotation … n'est pas lue … pas de mouvement ». **La tête
   ne bouge pas du tout.** Si elle bouge, **arrêt d'urgence** et le dire dans la PR.

## Étape 1 : peser (fiche, § 4 point 3)

1. Peser sur la balance de cuisine : une **capsule vide**, un **couvercle percé**, un **bocal plein de semence
   fermé** (avec sa capsule). Écrire les masses dans `bocal_neuf → bocal` : `m_capsule_kg`, `m_couv_perce_kg`,
   `m_bocal_plein_kg` (en kg : 0,025 pour 25 g). Le dernier doit être le bocal **sans** capsule : le Pi pèse le bocal
   vissé d'un couvercle percé, soulevé.
2. `tolerance_pct` (30 % d'exemple) : à resserrer quand les pesées de l'étape 5 sont stables. Le palier pesé voit
   mal moins de 20 à 30 g : si la capsule est trop légère pour être vue, le dire dans la PR (question 3).

## Étape 2 : le couple d'ouverture (fiche, § 4 point 1)

1. Avec le dynamomètre, ouvrir à la main un bocal de semence **posé sur la tôle inox** : noter le couple (N·m).
   La tête donne au plus ≈ 5 N·m ; avec un tapis silicone de 1 mm la retenue est ≈ 3 N·m à 80 N.
2. Refaire sur 3 bocaux. Si le couple dépasse 3 N·m, **le bocal tournera sur la tôle** : le geste s'arrêtera avec
   « capsule pas dévissée » (étape 5a). Le dire dans la PR (question 2).
3. Coller le tapis silicone de 1 mm sous les 18 places de semence (choix de la Préhension), puis remesurer la cote
   du dessus de la capsule : `stockage → bocaux → capsule_haut_z` (0,644 d'exemple, tapis compris).

## Étape 3 : cotes à mesurer à la main

1. **Le dessus de la capsule** (`capsule_haut_z`), au réglet, sur une place.
2. **Les deux boîtes** (x 2,95 ; y 0,53 pour les capsules, y 0,80 pour les couvercles percés) : fond 0,498, dessus
   0,739, épaisseur 13 mm par pièce (`stockage → boites`). Mettre 3 pièces dans chaque boîte et vérifier la hauteur
   de la pile.
3. **Le haut de la pile du porte-bocal** : `contact_capsule_bocal` (essai du porte-bocal).
4. `angle_meplats` (fiche, § 4 point 4) : mesuré à l'essai du porte-bocal.

## Étape 4 : dévisser la capsule (étapes 1 à 6) : après la question 1

1. Bocal sur `semence_0_0`, QR lu à la main. Lancer la commande de l'étape 0.
2. Regarder, **à la vidéo** (garder la main près de l'arrêt d'urgence) :
   - la tête va sur le bocal, tourne à **−270°** en l'air (cordon ± 500°), descend vite jusqu'à 3 cm de la capsule
     puis lentement (`bocal_col`) jusqu'au contact M8 ;
   - les aimants s'allument, la tête appuie à **80 N** (2 mm/s, palier pesé) ;
   - elle tourne **par segments** (trigo, positif) : 120°, puis tous les 60° au plus jusqu'à 360° ; après chaque
     segment, la poussée est relâchée par petits pas de 0,5 mm, la tête monte de **3 mm** et le palier pèse : **la
     capsule seule** (libre) ou **la capsule + le bocal** (elle tient encore : la tête redescend et reprend l'appui) ;
   - capsule libre : elle monte de 3 cm lentement puis en haut.
3. Noter : combien de degrés pour libérer la capsule, la poussée lue, le palier à chaque essai. Ces nombres
   remplacent les EXEMPLES de `bocal_neuf → devissage` (`relache_*`, `decollage_m`).
4. **Erreurs à provoquer** (une par une, bocal à chaque fois remis à la main) :
   - bocal enlevé : « pas de contact … pas de bocal » ;
   - QR caché : « QR illisible » (rien ne bouge, la place est marquée « à vérifier ») ;
   - capsule très serrée (la serrer à la clé) : « capsule pas dévissée … » : la tête repose la capsule dessus, les
     aimants coupés, remonte ; le bocal reste, marqué dans l'inventaire et le registre.

## Étape 5 : la capsule, le couvercle percé, le vissage (étapes 7 à 11)

1. La capsule va dans la boîte (x 2,95 ; y 0,53) : contact M8 à la hauteur prévue (± 8 mm), aimants coupés, attente
   0,3 s, remontée lente de 3 cm. Le Pi compte une capsule de plus.
2. Un couvercle percé est pris dans l'autre boîte : le palier doit en lire **un seul** (deux collés : reposés et
   repris, puis alerte).
3. Retour sur le bocal : tête à **+270°**, appui 80 N, rotation **horaire** (négative) jusqu'au **calage du moteur**
   (erreur du codeur > 2° pendant 0,2 s). La face doit finir à la cote du dessus de la capsule ± 2 mm.
4. Le bocal est soulevé de 5 mm : le palier doit lire **le bocal plein** (± `tolerance_pct`).
5. **Erreurs à provoquer** : boîte des capsules pleine ou mal comptée (« la capsule ne touche pas la boîte… ») ;
   couvercle posé de travers (le moteur ne cale pas : « couvercle percé pas vissé », il est remis dans sa boîte).

## Étape 6 : le porter et le poser (étapes 12 à 19)

1. Le bocal monte (3 cm lents, puis en haut) : le palier pesé est surveillé pendant le trajet (une chute de la
   charge = alerte).
2. Il passe par le couloir côté allée, tête sur les méplats (± 3°), descend jusqu'au contact de la capsule
   (`contact_capsule_bocal`), les mors passent à **Ø 98** à faible courant, la tête lâche, le palier doit revenir à
   vide (± 0,3 N), elle remonte de 5 mm (le M8 doit être retombé), puis les mors serrent le bocal.
3. La tête repart en +y jusqu'à y 0,40 (hors de la zone du porte-bocal) : seulement alors la manivelle peut
   remonter.
4. **Erreurs à provoquer** : coller un peu de ruban sur la tête (palier qui ne revient pas à vide) ;
   le M8 qui reste actif après la remontée.

## Étape 7 : le bocal vide du porte-bocal

La reprise du bocal vide par la tête n'est pas écrite (fiche, § 4 point 5). Si un bocal est encore dans le
porte-bocal au départ du geste, **les mors s'ouvrent et la machine demande de l'enlever à la main** : le vérifier.

## Étape 8 : dans un lot

Le poste « mycelium » reste « pas lancé » sur la vraie machine (le journal en dit la raison : le QR du bocal et
l'erreur du codeur ne sont pas branchés). Quand ils le seront (tâche 45 quater et suivante) et que tous les chiffres
EXEMPLE auront été vus, passer `bocal_neuf → exemple` à `false`, puis `vidange --verifier`.

Noter les chiffres trouvés et les remarques dans la PR, ou les donner à la prochaine session.
