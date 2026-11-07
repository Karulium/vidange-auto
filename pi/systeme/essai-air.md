# Essai de l'air comprimé sur le vrai matériel (tâche 42)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent qu'un faux relais. Cet essai dure
environ 30 minutes. Il faut le compresseur MB50 branché sur son contacteur, le bloc de traitement réglé, et la
carte de relais n° 2 câblée (signal `relais_compresseur`, EXEMPLE : broche K6 de `relais_2`).

La coupure de sécurité du compresseur (arrêt d'urgence, ozone, purge) est **câblée** : le Pi ne fait que la
commande normale. Pendant l'essai, l'arrêt d'urgence reste câblé comme d'habitude.

## Avant de commencer

1. Arrêter le programme principal : `sudo systemctl stop vidange`, puis le relancer à l'étape 1.
2. Vanne d'isolement du bloc **fermée**, cuve vide ou presque (ouvrir une purge si besoin).
3. Le temps à trouver est dans `pi/reglages/air.yaml` (`attente_mise_en_pression_s`, EXEMPLE 240 s). Après
   chaque changement : `vidange --verifier` doit dire « Réglages corrects ».

## Étape 1 : le relais ferme le compresseur

1. `sudo systemctl start vidange`. Dans la page web (ou `GET /api/air`) : « compresseur : oui, en pression :
   non, reste : environ 240 s ».
2. Écouter le contacteur : il doit avoir claqué. Le compresseur démarre et se remplit.
3. Si rien ne se passe : voir la ligne « Air » du journal (`journalctl -u vidange | grep Air`) et le câblage de
   `relais_compresseur`.

## Étape 2 : mesurer la mise en pression

1. Le compresseur est arrêté, cuve vide. Redémarrer le programme et chronométrer jusqu'à ce que le compresseur
   s'arrête tout seul (pressostat, 8 bar).
2. Noter le temps. Mettre dans `air.yaml` ce temps plus une petite marge, puis relancer.
3. Vérifier que, avant la fin de l'attente, un geste qui consomme de l'air (le spray d'un seau) est refusé
   avec la raison « air en mise en pression ».

## Étape 3 : la nuit UV-ozone coupe le compresseur

1. Suivre `essai-nettoyage.md` jusqu'à la nuit UV-ozone (départ tout de suite).
2. Dès le départ de la génération, le contacteur doit se couper. À la fin de la nuit, il se referme, et
   l'attente de mise en pression recommence.
3. Vérifier aussi **à la main** que la coupure câblée fonctionne sans le Pi (arrêt du programme pendant la
   nuit : le compresseur doit rester coupé par le câblage). Si ce n'est pas le cas, ne pas lancer de vraie nuit.

## Étape 4 : le rappel du bidon

1. Dans `air.yaml`, mettre `rappel_bidon_jours: 1`, puis changer la date de `donnees/air.json` pour la veille.
2. Relancer : la check-list doit dire « bidon de purge pas vidé depuis 1 jours ».
3. Appuyer sur « bidon vidé » (page web) : le rappel disparaît. Remettre `rappel_bidon_jours: 7`.

## À noter pour la PR

Le temps de mise en pression mesuré, et si le contacteur et la coupure câblée ont bien réagi.
