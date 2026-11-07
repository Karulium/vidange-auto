# Essai du mode seaux sur la vraie machine (tâche 45)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent que le faux matériel et le
simulateur. Cet essai ne fait **rien bouger** : on démarre la machine à vide et on lit ce que disent
l'écran de l'armoire et la check-list. Il dure environ 10 minutes.

Ce qu'il faut savoir avant : aujourd'hui, **aucun lot de seaux ne peut partir sur la vraie machine**.
C'est voulu. Le programme le dit, poste par poste, avec la raison :

- réglages d'EXEMPLE (`exemple: true` dans `pi/reglages/machine.yaml`) : interdits sur la vraie machine ;
- gestes pas encore écrits : lavage lancé après le lot (la griffe est enchaînée au lot depuis la tâche 45 sexies :
  `pi/systeme/essai-griffe-du-lot.md`) ;
- ce qui manque sur la machine : les cartes du chariot et de la tête, si elles ne sont pas branchées ou encore en
  EXEMPLE (elles sont construites au démarrage depuis la tâche 45 ter : `pi/systeme/essai-cartes-chariot-tete.md` ;
  la vision de la caméra du micropore, elle, est écrite : tâche 40 ter, `pi/systeme/essai-inspection.md` ; elle attend
  `vision.yaml → inspection → exemple: false`), pose du bocal de semence neuf par la préhension ; le spray, si sa
  carte n'est pas ouverte.

La sécurité (arrêt d'urgence, portes, store) reste câblée, comme d'habitude.

## Étape 1 : démarrer

1. Machine sous tension, arrêt d'urgence relâché, rien dans le chariot de remplissage.
2. `vidange --verifier` doit dire « Réglages corrects ».
3. `sudo systemctl restart vidange`.

## Étape 2 : lire le journal

1. `journalctl -u vidange -b | grep "Mode seaux"` : une ligne par poste du cycle d'un seau, dans
   l'ordre (fut, seau_vide, qr_du_flanc, au_poste, spray, micropore, griffe, mycelium, couvercle, fermeture,
   stockage, lavage),
   chacune « prêt » ou « pas lancé : ... » avec la raison.
2. `journalctl -u vidange -b | grep "mode seaux"` : les lignes de la check-list. On doit voir
   « [bloquant] mode seaux : aucun lot de seaux ne peut partir : ... » et, pour chaque poste qui manque,
   une ligne « [attention] mode seaux, <poste> : pas lancé : ... ».
3. Noter toute ligne qui ne correspond pas à la liste du début de cette page.

## Étape 3 : lire l'écran de l'armoire

1. Au démarrage, le retour en lieu sûr est proposé (« ATTEND LE GO ») : faire comme d'habitude (Go, ou
   regarder la machine).
2. Quand plus rien ne tourne, la page d'état dit « Aucun cycle en cours », puis
   « Lot de seaux : <poste> pas prêt » et, sur la ligne du dessous, pourquoi.
3. Noter le texte vu (une photo de l'écran suffit).

## Étape 4 : la check-list depuis la page web

1. Ouvrir la page web, partie check-list (ou `GET /api/checklist` avec la clé).
2. Les mêmes lignes « mode seaux » que dans le journal doivent y être.

## Si quelque chose ne va pas

- Le programme ne démarre pas : `journalctl -u vidange -b | tail -50`, et envoyer ces lignes.
- Une ligne « reprise du cycle » bloquante : le carnet (`pi/donnees/etat-cycle.json`) parle d'un lot que le
  programme ne peut pas reprendre. Regarder la machine, puis effacer ce fichier.

## Après l'essai

Rien à remettre : l'essai ne fait rien bouger. Renvoyer les notes des étapes 2 et 3 dans la PR.
