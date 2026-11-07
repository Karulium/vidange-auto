# Essai des cartes du chariot et de la tête au démarrage (tâche 45 ter)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent que le faux matériel. Cet essai ne fait
**rien bouger** : au démarrage, le programme regarde seulement si chaque carte est là et répond. Il n'envoie
aucun ordre aux servos ni aux sorties. Il dure environ 30 minutes (une relance du programme par carte).

Ce que le programme construit au démarrage (« pièces ») et ce dont chacune a besoin :

| Pièce (check-list) | Ce qu'il faut |
|---|---|
| chariot (carte FluidNC et balance du plateau) | carte FluidNC « chariot » (USB), carte de pesée du plateau sur le bus des pesées |
| boîtier du chariot (PCA9685, ToF) | la même carte de pesée, avec la PCA9685 et le VL6180X sur son I2C |
| tête du micropore (servos, ToF) | le boîtier |
| bras de la fermeture (servo) | le boîtier |
| moteur d'avance du ruban du micropore | carte FluidNC de `machine.yaml → micropore → avance → carte` |
| tête de la Préhension | cartes FluidNC « portique » et « prehension », palier pesé de la préhension, capteur de vide |
| Lavage (eau du fût, brosses) | la tête, et les cartes FluidNC qui portent les signaux du lavage |
| carte du spray | carte ESP32 n° 5 sur son bus à elle (`rs485_spray`) |

Une pièce qui manque n'empêche jamais le programme de démarrer : la check-list dit laquelle et pourquoi, et les
postes qui en ont besoin sont « pas lancé : raison ». **La présence est regardée une seule fois, au démarrage** :
après avoir branché une carte, il faut relancer le programme.

À savoir : même avec toutes les cartes, **aucun lot ne part encore** sur la vraie machine. Restent : la griffe
(tâche 23), la pose du bocal de semence neuf (Mycélium), la lecture de la photo du plafond (entonnoir, bocaux
sales). C'est voulu : le programme le dit.

La sécurité (arrêt d'urgence, portes, store) reste câblée, comme d'habitude.

## Avant l'essai

Sur la vraie machine, les lignes `exemple: true` de `docs/entrees-sorties.yaml` et les réglages d'EXEMPLE
(`fluidnc.yaml`, `pesees.yaml`) sont refusés. Tant qu'ils y sont, chaque pièce dit « ligne ... en EXEMPLE :
interdit sur la vraie machine » : c'est la première chose qu'on doit voir. Pour aller plus loin, il faut d'abord
avoir fait les mises en service de chaque carte (numéros de série dans `fluidnc.yaml`, étalonnage des pesées,
`pesee/essai-etabli.md`, boîtier du chariot, `pesee/essai-boitier-chariot.md`, spray, `pi/systeme/essai-spray.md`)
et passé leurs lignes à `exemple: false`.

La commande pour lire les pièces après chaque démarrage :

```
journalctl -u vidange -b | grep -E "Pièce|cartes du chariot et de la tête"
```

## Étape 1 : tout débranché

1. Arrêt d'urgence enfoncé. Débrancher les câbles USB des cartes FluidNC « chariot », « portique »,
   « prehension », « mycelium_lavage », et les deux adaptateurs USB-RS485 (pesées, spray).
2. `vidange --verifier` doit dire « Réglages corrects ».
3. `sudo systemctl restart vidange`, attendre 30 secondes.
4. Lire les pièces (commande plus haut). Chaque pièce a une ligne « [attention] cartes du chariot et de la
   tête, <pièce> : ... ». On doit lire, selon la carte : « aucun port USB ne porte le numéro de série »
   (FluidNC), « carte de pesée ... » (adaptateur des pesées), « carte du spray ... ».
5. Le programme tourne quand même : l'écran de l'armoire répond, la page web aussi.

## Étape 2 : brancher une carte à la fois

Pour chaque ligne du tableau ci-dessous, dans l'ordre : brancher **seulement** ce qui est dit, relancer
(`sudo systemctl restart vidange`), attendre 30 secondes, lire les pièces, noter ce qui est écrit.

| N° | Brancher en plus | Pièce qui doit passer « construite » (plus de ligne « Pièce ... absente ») |
|---|---|---|
| 1 | adaptateur USB-RS485 du spray, carte du spray sous tension | carte du spray |
| 2 | adaptateur USB-RS485 des pesées, cartes de pesée sous tension | aucune encore (il manque les FluidNC) ; la ligne du boîtier ne doit plus parler de la carte de pesée, seulement si le boîtier n'est pas câblé |
| 3 | carte FluidNC « chariot » | chariot |
| 4 | câble du boîtier du chariot (PCA9685, ToF) | boîtier, tête du micropore, bras de la fermeture |
| 5 | carte FluidNC « mycelium_lavage » | moteur d'avance du ruban |
| 6 | cartes FluidNC « portique » et « prehension » | tête de la Préhension, Lavage |

À l'étape 4, les servos **ne doivent pas bouger** (le programme ne leur envoie rien au démarrage). S'ils bougent,
arrêter et noter.

## Étape 3 : la check-list et l'écran, tout branché

1. `journalctl -u vidange -b | grep "Mode seaux"` : les postes « qr_du_flanc », « micropore », « couvercle »,
   « fermeture » et « spray » ne doivent plus parler de cartes. Ils disent « attend « mycelium » (pas prêt) »,
   « pas de lot possible », ou la vision du micropore (`vision.yaml → inspection`) si elle est encore en EXEMPLE.
2. `journalctl -u vidange -b | grep "Mode bocaux"` : « entonnoir » dit « lecture de la photo du plafond ... pas
   écrite », « lavage_bocaux » dit « liste des bocaux sales ... pas écrite ».
3. Quand plus rien ne tourne, l'écran de l'armoire dit « Lot de seaux : seau vide pas prêt » et, dessous,
   pourquoi (le mycélium, plus les cartes).
4. Page web, check-list (ou `GET /api/checklist` avec la clé) : les mêmes lignes « cartes du chariot et de la
   tête » que dans le journal.

## Étape 4 : une carte qui tombe en panne au démarrage

1. Tout branché, débrancher seulement l'adaptateur USB-RS485 des pesées, relancer.
2. Chariot, boîtier, tête du micropore, bras de la fermeture, tête de la Préhension et Lavage disent « carte de
   pesée ... ». La carte du spray reste construite (elle a son bus à elle).
3. Rebrancher, relancer : tout revient.

## Si quelque chose ne va pas

- Le programme ne démarre pas : `journalctl -u vidange -b | tail -50`, et envoyer ces lignes.
- Une pièce reste absente avec « pas construite : ... » : c'est un réglage qui ne va pas (un signal qui manque
  dans `fluidnc.yaml`, par exemple). Envoyer la ligne.
- Un numéro de série pas trouvé alors que la carte est branchée : `ls -l /dev/serial/by-id/` et comparer avec
  `pi/reglages/fluidnc.yaml`.

## Après l'essai

Rien à remettre : l'essai ne fait rien bouger. Renvoyer les notes des étapes 1 à 4 dans la PR.
