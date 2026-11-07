# Essai : lancer un lot depuis la page web, Go à l'écran (tâche 45 quater)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent que le faux matériel. Cet essai se fait
**machine à vide** (pas de fût, pas de seau, pas de bocal sur le plateau ni dans la tête). Il dure environ 30
minutes.

Ce que fait la tâche :

- sur la page web, une carte « Lancer un lot » : **Lot de seaux** (format, nombre de seaux, variété de la
  semence) et **Lot de bocaux** (nombre de bocaux). Le bouton ne fait que **proposer** le lot : rien ne bouge ;
- sur l'écran de l'armoire, la page d'état dit « ATTEND LE GO » et « Lot de … : GO ? ». Le bouton **GO**, puis
  **Oui**, lance le lot. Le Pi propose, Karulium dit Go, devant la machine ;
- au Go, les boucles de fond des pièces partent (balance du chariot, balance de l'agitateur, boîtier du chariot,
  vide de la tête) ; elles s'arrêtent sur alarme et à la fin du lot ;
- un lot est refusé, avec la raison, si un poste n'est pas prêt, si un lot (ou le retour en lieu sûr) tourne déjà,
  si la machine n'est pas en mode « production », ou s'il a **plus de seaux que de bocaux de semence posés de sa
  variété, de places libres dans la boîte des capsules ou de couvercles percés** (18 au plus aujourd'hui, sans
  rechargement en milieu de lot).

**À savoir avant de commencer : aujourd'hui, sur la vraie machine, aucun lot ne part.** C'est voulu, il manque
encore (et le programme le dit à chaque refus) :

| Ce qui manque | Poste qui le dit |
|---|---|
| L'enchaînement de la griffe avec la préhension et le seau du chariot (tâche 23) | griffe, versement |
| La lecture du QR d'un bocal de semence par la caméra de la tête de la griffe | mycelium |
| L'erreur du codeur de la rotation de la tête (calage du moteur, carte n° 4) | mycelium |
| La lecture de la photo du plafond (bande du haut, entonnoir, bocaux sales) | stockage, entonnoir, lavage_bocaux |
| Le réglage vrai des parties encore en EXEMPLE (`exemple: true`) | chaque poste concerné |

Cet essai vérifie donc surtout que **le bouton et le Go refusent avec la bonne raison**, sans rien faire bouger.

La sécurité (arrêt d'urgence, portes, store) reste câblée, comme d'habitude. Rien ici ne protège personne.

## Avant l'essai

1. Machine à vide, arrêt d'urgence relâché, portes fermées.
2. `vidange --verifier` doit dire « Réglages corrects ».
3. `sudo systemctl restart vidange`, attendre 30 secondes.
4. Sur l'écran de l'armoire : s'il propose le « retour en lieu sûr », lui donner le Go (bouton GO, puis Oui) et
   attendre la fin. Tant qu'il tourne, un lot est refusé (« un lot est déjà en route (lieu_sur) »).
5. Mode « production » choisi (bouton MODE de l'écran).

Pour lire ce que fait le programme pendant l'essai :

```
journalctl -u vidange -f | grep -E "Lot|lot|boucle de fond"
```

## Étape 1 : la carte « Lancer un lot » sur la page web

1. Ouvrir la page web (téléphone ou PC), onglet « État ».
2. Sous « Enceinte », la carte « Lancer un lot » doit être là, avec :
   - la liste des formats (seau_a, seau_b...) ;
   - « Bocaux de semence posés : … » (sans doute « Aucun bocal de semence noté au stockage » : l'inventaire
     n'a pas encore de bocaux de semence, voir plus bas) ;
   - « Lot de seaux : « … » pas lancé : … » : **noter cette raison**, c'est le premier poste qui manque.

## Étape 2 : le bouton « Lot de seaux » refusé, avec la raison

1. Format « seau_a », 2 seaux, variété « pleurote_grise », toucher « Proposer le lot de seaux ».
2. La page doit dire « Refusé : lot de seaux refusé : « … » pas lancé : … », la même raison qu'à l'étape 1.
3. **Rien ne doit bouger.** Le journal dit « Lot de 2 seaux seau_a (pleurote_grise) demandé par la page web ».
4. Recommencer avec 19 seaux : si les postes étaient prêts, le refus parlerait des bocaux de semence (« 19 seaux
   « pleurote_grise » mais … bocaux de semence posés »). Aujourd'hui c'est d'abord le poste qui manque qui est
   dit.

## Étape 3 : refus pendant un autre travail

1. Mettre la machine en mode « lavage » (écran, MODE). Proposer un lot de seaux : la page doit dire « le mode
   « production » n'est pas choisi (mode actuel : lavage) » (ou d'abord le poste qui manque).
2. Remettre le mode « production ».

## Étape 4 : le bouton « Lot de bocaux »

1. 2 bocaux, toucher « Proposer le lot de bocaux ».
2. La page doit dire « Refusé : lot de bocaux refusé : « … » pas lancé : … » (le versement de la griffe, ou
   l'entonnoir et la photo du plafond).

## Étape 5 : l'écran sans lot proposé

1. Sur l'écran de l'armoire, page d'état, toucher GO : il doit dire « Aucun Go attendu. ».
2. La ligne du bas dit pourquoi un lot de seaux ne peut pas partir (comme avant cette tâche).

## Étape 6 (plus tard, quand les postes seront prêts) : le Go lance le lot

Cette étape ne pourra se faire qu'après la tâche 23 et les sources qui manquent. Elle est écrite pour ce jour-là :

1. Poser les bocaux de semence et les noter au stockage, boîte des capsules vide, couvercles percés dans leur
   boîte, seaux vides sur leurs piles.
2. Page web : proposer un lot de 2 seaux. La page dit « Lot de 2 seaux seau_a (…) proposé : donner le Go sur
   l'écran de l'armoire ». **Rien ne bouge.**
3. Écran : la page d'état dit « ATTEND LE GO » et « Lot de 2 seaux seau_a (…) : GO ? ». Toucher GO : la question
   « Lancer le lot de 2 seaux … ? La machine va bouger. » ; toucher Oui.
4. Le journal dit « Lot : boucle de fond « tete » lancée » (puis chariot, agitateur, tete_micropore,
   bras_fermeture) et « Go de la écran de l'armoire : lot de 2 seaux … lancé ». La page web dit « Boucles de
   fond du lot : … ».
5. Appuyer sur PAUSE, puis provoquer une alarme (par exemple ouvrir une porte) : le journal dit « Lot : boucles de
   fond arrêtées ». Après « RÉPARÉ » et le Go, elles repartent (la tête sans toucher sa vanne).
6. À la fin du lot (ou après l'avoir abandonné) : « Lot fini : plus de boucle de fond ».
7. Une proposition sans Go est oubliée au bout de 10 minutes (`programme.yaml → lot → proposition_max_s`).

## Ce qu'il faut renvoyer

Les raisons lues aux étapes 1 à 4 (copie de la page ou du journal) et, s'il y en a, tout ce qui a bougé alors que
rien ne devait bouger (cela ne doit jamais arriver avant un Go à l'écran).

## Si quelque chose ne va pas

- La carte « Lancer un lot » n'est pas sur la page : recharger la page (le téléphone garde parfois l'ancienne).
- « pas de lancement de lot » : le programme principal n'a pas démarré correctement ; `journalctl -u vidange -b |
  tail -50` et envoyer ces lignes.

## Après l'essai

Rien à remettre : sans Go, rien n'a bougé.
