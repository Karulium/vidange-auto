# Essai : la griffe dans les lots (tâche 45 sexies)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent que le faux matériel et la machine
imaginaire du simulateur. Faire d'abord les essais de la griffe seule (`pi/systeme/essai-griffe.md`), du poste du
fût (`pi/systeme/essai-poste-fut.md`), du versement dans un bocal (`pi/systeme/essai-versement-bocal.md`) et du
lancement d'un lot (`pi/systeme/essai-lot-machine.md`). Compter 1 h 30.

Ce que fait la tâche :

- au démarrage, le programme principal construit la griffe sur ses vraies cartes : le bras (carte FluidNC du
  portique), la pesée de la griffe (RS485) et le poste du fût. S'il en manque une, le journal dit
  « griffe : pas lancé : raison », et le programme démarre quand même (pas de lot de seaux ni de bocaux) ;
- **lot de seaux** : la griffe prend une dose dans le fût seulement quand un seau attend au vidage (étape
  « verser » du Remplissage) ; elle la porte au seau, la vide, tasse en faisant tourner le seau, et, à la
  dernière couche, essuie le bord. Pendant ce temps, la préhension (même pont, même chariot) attend ; quand la
  préhension bouge, la griffe attend en haut, garée ;
- **lot de bocaux** : le versement de la griffe dans le bocal où est l'entonnoir (tâche 43 bis) est branché ;
- quand la préhension bouge le pont ou le chariot, elle traîne la griffe avec elle : le programme vérifie, le long
  du trajet, que la griffe (en butée haute) reste dans ses zones permises, et refuse le geste sinon ;
- fût vide au milieu d'un lot : la griffe finit le seau commencé (tassement, essuyage), puis attend le « Prêt »
  d'un nouveau fût. Si ce seau n'a pas toutes ses couches, le Remplissage s'arrête sur une alarme : **finir ce seau
  à la main** (aucun geste n'est encore décidé pour ce cas).

La sécurité (arrêt d'urgence, portes, store, fins de course câblées) reste câblée, comme d'habitude. Rien ici ne
protège personne.

## Avant l'essai

1. Sur le PC : `cd pi && pytest -q tests/test_cycle_griffe.py tests/test_cycle_lot.py` : tout doit passer.
2. Sur le Pi : `vidange --verifier` doit dire « Réglages corrects ». Les parties encore en EXEMPLE
   (`exemple: true`) sont refusées sur la vraie machine : la griffe ne partira qu'une fois ses réglages mesurés
   (essai de la griffe) et `griffe → exemple` passé à false.
3. Vitesses du portique divisées par 4 pour tout l'essai (comme pour l'essai de la griffe).
4. Une personne à l'arrêt d'urgence pendant tous les gestes.

## Étape 1 : la griffe est construite au démarrage

1. Débrancher le câble RS485 de la pesée de la griffe. `sudo systemctl restart vidange`.
2. Dans le journal (`journalctl -u vidange -n 200`) : une ligne « griffe » dit « pas lancé » avec la raison
   (pesée de la griffe). **Le programme tourne quand même** : la page web répond.
3. Proposer un lot de seaux depuis la page web : il est refusé, la raison parle de la griffe.
4. Rebrancher la pesée, redémarrer. Le journal ne dit plus rien de la griffe ; « Mode seaux, griffe : prêt » et
   « Mode bocaux, versement : prêt » (si les autres pièces de ces postes sont là).

## Étape 2 : la préhension traîne la griffe (machine à vide)

1. Griffe en butée haute, au-dessus du fût. Avec l'outil de la préhension, demander un trajet qui va vers le
   stockage.
2. Regarder : la griffe suit le pont (c'est normal, même chariot) et reste en haut. Le trajet ne passe jamais au
   travers du fût : la préhension sort d'abord de l'isolation du fût, face en haut.
3. Demander un trajet qui amènerait la griffe dans une zone interdite (par exemple la porte du coffret du spray
   ouverte) : le geste doit être **refusé avant de bouger**, avec la raison de la griffe.

## Étape 3 : un lot de 1 seau, fût de substrat

1. Un fût plein sur le plateau, au fond ; bouton « Prêt » du poste du fût.
2. Un seau vide en stockage, son bocal de semence posé. Lancer depuis la page web un lot de 1 seau, Go à l'écran.
3. Regarder à chaque couche :
   - la griffe attend en haut tant que le seau n'est pas au vidage ;
   - quand le seau y est, elle descend dans le fût, racle si besoin, prend une dose, la porte au seau, la vide ;
   - le seau tourne pendant le tassement ; la griffe ne touche pas le bras du spray ni la caméra du dosage ;
   - le mycélium est versé entre les couches, la griffe attend en haut pendant ce temps ;
   - à la dernière couche, elle essuie le bord, puis reste en haut.
4. Le seau est fermé (couvercle, micropore) et rangé. Le lot finit ; le reste du fût attend le lot suivant.
5. Noter le temps d'une couche (journal : « Griffe : seau n° 1, couche … versée et tassée »). S'il dépasse
   souvent la moitié de `durees → remplissage_couche_griffe_max` (`pi/reglages/machine.yaml`, 30 min en EXEMPLE),
   le dire : on ajustera ce délai.

## Étape 4 : coupure au milieu d'un seau

1. Lot de 2 seaux. Pendant la 2e couche du 1er seau, couper le courant du Pi (pas de la machine).
2. Rallumer. Le retour en lieu sûr est proposé ; Go. Puis le lot se reprend : la griffe doit reprendre au même
   seau, à la couche suivante (le carnet garde le seau et les couches versées).

## Étape 5 : fût vide au milieu d'un lot

1. Mettre dans le fût à peine plus que pour 1 seau. Lancer un lot de 2 seaux.
2. Le 1er seau se remplit. Pendant le 2e, le fût se vide : la griffe finit le seau (tassement, essuyage), puis
   attend en haut le « Prêt » d'un nouveau fût. Le Remplissage s'arrête sur une alarme « fût vide pendant le
   seau » : c'est voulu.
3. Finir ce seau à la main, puis arrêter le lot. Dire à Claude comment vous voulez que la machine fasse ce cas
   (question de la PR).

## Étape 6 : un lot de bocaux

Faire l'étape 6 de `pi/systeme/essai-versement-bocal.md` (lot de 3 bocaux) depuis la page web, avec un fût de
maïs : le versement est maintenant lancé par le programme principal.

## Si quelque chose ne va pas

- Arrêt d'urgence, puis noter l'heure ; envoyer à Claude les 200 dernières lignes du journal
  (`journalctl -u vidange -n 200 > griffe.txt`).
- Un geste refusé « position de la griffe inconnue » : la carte du portique ne répond pas ; vérifier son câble.
