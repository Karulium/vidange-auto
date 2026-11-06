# Essai du poste du fût sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent que des
**faux** capteurs et une **fausse** boîte du poste. Cette procédure vérifie, au poste du fût :
le détecteur du plateau (inductif M12), le contact du panneau (reed), le bouton « Prêt » et son voyant,
la pesée sans fil (plateau → radio → boîte du poste → bus des pesées), son étalonnage, l'accu du plateau,
et la radio coupée (« pesée absente », sans arrêt).
Compter environ 1 h 30 la première fois (dont 30 min pour l'étalonnage).

Rien ne bouge seul au poste du fût : cet essai ne fait bouger aucun moteur.

## Avant de commencer

- Le Pi est installé (voir `installation.md`) et l'essai des entrées/sorties est fait
  (`essai-entrees-sorties.md`, au moins l'étape 1 : I2C et broches GPIO).
- Le bus des pesées marche (`pesee/essai-etabli.md`, étape du bus : adaptateur `rs485_pesee`).
- Les **2 ESP32-C3** (plateau et boîte du poste) ont leur programme (tâche 17 ter) ; la boîte du poste
  est branchée sur le bus des pesées (A, B, 0 V) et alimentée ; l'accu du plateau est chargé (USB-C de
  secours si besoin).
- Les lignes du poste sont remplies dans `docs/entrees-sorties.yaml` d'après le plan de câblage
  (carte, broche, sens au repos ; adresse de la boîte) : `plateau_fut_en_place`, `reed_panneau_poste_fut`,
  `bouton_pret_fut`, `voyant_pret_fut`, `pesee_fut` (adresse 4 par défaut). Tant qu'elles portent
  `exemple: true`, ce sont des exemples.
- Arrêter le programme du Pi (l'adaptateur du bus des pesées ne s'ouvre qu'une fois) :

  ```
  sudo systemctl stop vidange
  ```

- Mettre à jour le programme du Pi (cette version lit la pesée sans fil) :

  ```
  cd /opt/vidange-auto && sudo -u vidange git pull
  cd pi && sudo -u vidange .venv/bin/pip install -e .
  ```

Dans les commandes ci-dessous, `vidange-es` veut dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-es`, et `vidange-pesee` veut dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-pesee`.

## Étape 1 : le détecteur du plateau

1. Plateau du fût **hors** du poste. Lancer :

   ```
   vidange-es surveiller plateau_fut_en_place reed_panneau_poste_fut bouton_pret_fut
   ```

2. Rouler le plateau sous le portique et le pousser droit contre les 2 butées d'angle du fond. Quand le
   bord du plateau arrive à environ 4 mm du détecteur (aile arrière de la butée côté portique), l'écran
   doit afficher `plateau_fut_en_place : ACTIONNÉ`. La petite lumière du détecteur s'allume aussi.
3. Reculer le plateau de 2 cm : `plateau_fut_en_place : repos`. Le remettre au fond : `ACTIONNÉ`.
4. **Si c'est à l'envers** (actionné plateau absent) : la ligne `repos:` du signal est fausse dans
   `docs/entrees-sorties.yaml` (`ouvert` ↔ `ferme`). **Si rien ne change** : câblage du détecteur
   (marron +24 V, bleu 0 V, noir signal) ou distance trop grande (le régler à 3-4 mm).

## Étape 3 : le bouton « Prêt » et son voyant

1. Toujours avec `vidange-es surveiller` : appuyer sur le bouton lumineux « Prêt ».
   `bouton_pret_fut : ACTIONNÉ`, puis `repos` en le relâchant. Arrêter avec Ctrl+C.
2. Allumer puis éteindre le voyant du bouton :

   ```
   vidange-es commander voyant_pret_fut oui
   vidange-es commander voyant_pret_fut non
   ```

   Le voyant du bouton s'allume, puis s'éteint.

## Étape 4 : la pesée répond (radio du plateau)

1. Plateau **au fond** (l'aimant de la boîte du poste réveille la carte du plateau). Lancer :

   ```
   vidange-pesee lire
   ```

   Une ligne par seconde, par exemple
   `poids lu    63.20 kg   substrat     3.80 kg   accu 3.95 V  84 % en recharge   radio -58 dBm, 0 trames perdues`.
   Les poids sont faux tant que la pesée n'est pas étalonnée (étape 5) : on regarde seulement qu'**ils
   changent quand on appuie** sur le plateau, et qu'ils restent **stables** (à quelques dixièmes près) sans
   y toucher. Avant l'étalonnage, la ligne peut dire `ÉCHEC : poids rejeté` : c'est normal.
2. Regarder aussi : `en recharge` (la recharge sans contact marche), le **signal radio** (au-dessus de
   −80 dBm, c'est bon), et les **trames perdues** (elles ne doivent presque pas monter).
3. Ctrl+C pour finir.
4. **Si « ÉCHEC : pesée absente : la boîte du poste ne répond pas »** : la boîte n'est pas vue sur le bus.
   Vérifier son alimentation, les fils A et B du bus jusqu'à elle, et son adresse (4 par défaut, la même que
   `pesee_fut` dans `docs/entrees-sorties.yaml`). `vidange-pesees lire` montre toutes les pesées du bus.
   Si le journal dit « signature 0x5053 » : c'est une carte de pesée RP2040 qui a cette adresse.
5. **Si « ÉCHEC : pesée absente : radio du plateau muette »** : la boîte répond mais n'entend pas le
   plateau. Plateau bien au fond ? Accu chargé (brancher l'USB-C de secours) ? Voyant de la carte du
   plateau ? Adresse radio du plateau bien recopiée dans les réglages de la boîte (tâche 17 ter) ?
6. **Si « PAS EN RECHARGE »** plateau au fond : les bobines de la recharge sans contact ne sont pas face à
   face, ou le récepteur est en panne. Le noter.

## Étape 5 : l'étalonnage (zéro, poids connu, tare)

Il faut un **poids connu** d'environ 20 kg (sac pesé sur une balance juste, ou poids en fonte).
Chaque commande lit les mesures pendant environ 3 s et affiche **la ligne à recopier**. L'outil n'écrit
jamais lui-même dans les réglages. Après chaque recopie, sauvegarder le fichier avant la commande suivante.

1. **Zéro (tare du plateau vide)** : plateau au fond, **rien sur le plateau** (ni fût, ni outil). Ne pas
   toucher au plateau.

   ```
   vidange-pesee zero
   ```

   Recopier la ligne `zero_brut: ...` dans `pi/reglages/pesees.yaml`, partie `etalonnage` → `pesee_fut`.
2. **Poids connu** : poser le poids connu **au centre** du plateau (exemple : 20 kg).

   ```
   vidange-pesee etalonner 20
   ```

   Recopier la ligne `brut_par_kg: ...` au même endroit. Retirer le poids.
3. **Vérifier** : reposer le poids au centre, lancer `vidange-pesee lire` : le poids lu doit être le poids
   connu (à 0,2 kg près). Le poser près de chaque coin : même résultat (sinon, un des 4 capteurs est mal
   fixé ou mal câblé). Ctrl+C.
4. **Tare (fût vide)** : poser un **fût vide** sur le plateau, entre les 4 cales, couvercle compris.

   ```
   vidange-pesee tare
   ```

   Recopier la ligne `tare_kg: ...` dans `pi/reglages/machine.yaml`, partie `poste_fut` → `pesee`.
   Attention : avec le zéro fait plateau vide, le poids lu ne compte plus le plateau ni le boîtier ;
   la tare sera donc d'environ 33 kg (fût 29,5 kg + couvercle 3,9 kg), pas 59,4 kg (voir la question de
   la PR de la tâche 17 bis).
5. Régler `plausible_kg` (même partie) : poids lu permis, du fût vide (tare) au fût plein. Une valeur hors
   de ces bornes est **rejetée** (pas de poids) : la borne basse doit rester **sous la tare** (sinon, à la
   fin de la vidange, le fût presque vide serait « rejeté »), la borne haute au-dessus d'un fût plein.
6. Dans `machine.yaml` (`poste_fut` → `pesee`), passer `exemple: true` à `exemple: false`. Vérifier les
   réglages :

   ```
   sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange --verifier
   ```

   Il doit répondre « Réglages corrects ». Le changement de réglages part ensuite dans une PR
   (comme d'habitude), pour que `main` garde les bons chiffres.

## Étape 6 : le poste complet, avec le programme

1. Relancer le programme : `sudo systemctl start vidange`. Ouvrir la page web (téléphone).
2. **Plateau absent** : la page web montre « Poste du fût — Plateau du fût absent ». Le voyant du bouton
   **clignote** (0,5 s allumé, 0,5 s éteint).
3. Poser un fût plein debout sur le plateau, entre les 4 cales, soupape enlevée (trou bouché). Pousser le
   plateau contre les 2 butées du fond, freiner 2 roulettes. L'écran de l'armoire passe tout seul sur la
   page du poste : « EN PLACE, PAS PRÊT », la ligne du poids (« Substrat : ... kg · accu ... % · radio
   ... dBm »), les gestes à faire, puis plus rien ne manque au bout de 2 s.
4. Rabattre le grand volet, lever le panneau long. Appuyer sur « Prêt » (bouton du poste, ou écran, ou
   page web) : « PRÊT », le voyant reste **allumé fixe**, l'écran revient sur la page d'état. Dans
   l'historique de la page web, un cycle « vidange » commence, avec la mesure `poids_fut_plein`.
5. **Radio coupée** : débrancher l'alimentation de la **boîte du poste** (ou de la carte du plateau).
   Le poste **reste « Prêt »**, rien ne s'arrête. Au bout de 2 à 3 s, la page web dit « pesée absente : ... »
   et une **seule** alerte « Pesée du fût absente » apparaît (écran de l'armoire et page web), même si on
   attend plusieurs minutes. Rebrancher : le poids revient seul en 1 à 2 s, sans redémarrer le programme
   (« La pesée du fût répond de nouveau »). Acquitter l'alerte.
6. **« Prêt » sans pesée** : sortir le plateau (2 s), boîte du poste toujours débranchée, remettre le plateau
   au fond. Au bout de 5 s : « pesée absente » et une alerte. Appuyer sur « Prêt » : il est **accepté**
   (« Prêt, sans pesée du fût »), le cycle commence avec la mesure `sans_pesee_fut` au lieu de
   `poids_fut_plein`. Rebrancher la boîte.
7. **Plateau qui bouge** : desserrer les freins et reculer le plateau de 2 cm. Le poste n'est plus prêt,
   le voyant clignote de nouveau. Le remettre au fond, attendre 2 s, appuyer sur « Prêt » :
   « Prêt de nouveau : la vidange du fût continue » (même cycle).
8. **Plateau retiré** : relever le volet, desserrer les freins, sortir le plateau. Au bout de 2 s, la vidange
   commencée est close (« fût retiré avant la fin de la vidange », cycle « abandonné » dans l'historique).
   C'est normal pour cet essai. Environ 30 s plus tard, la carte du plateau se rendort : la page web dit
   « radio du plateau muette » (pas d'alerte : le plateau n'est pas au poste).

## Étape 6 bis : l'accu du plateau

1. Plateau au poste : la page web montre « Plateau : accu ... % (... V, en recharge) · radio ... dBm ».
2. **Accu faible** (seulement si un accu presque vide est sous la main, sinon passer cette étape et la
   noter « pas faite ») : mettre cet accu dans le plateau, émetteur de la recharge sans contact débranché.
   Sous 3,5 V, une alerte « Accu du plateau faible : recharger le plateau » ; sous 3,3 V, « pesée bientôt
   absente ». Rien ne s'arrête. Remettre le bon accu.
3. **Recharge en panne** : plateau au poste, débrancher le câble de l'émetteur de la recharge sans contact.
   Au bout de 10 min, une alerte « recharge sans contact en panne ? ». La rebrancher.
   À noter : si la carte du plateau dit « pas en recharge » quand l'accu est **plein**, cette alerte
   viendra aussi accu plein (voir la question de la PR de la tâche 17 bis).

## Étape 7 : le panneau et le mode

1. Panneau levé (contact fermé), attendre 2 s : passer en mode **Lavage** à l'écran (MODE → LAVAGE → OUI) ;
   le lancement d'un lavage sera refusé par le Pi avec « Lavage refusé : le panneau long du poste du fût
   est levé. Le rabattre. » (visible quand le module Lavage sera écrit, tâche 21).
2. Panneau rabattu : c'est la production qui sera refusée (« n'est pas levé »).
3. Juste après avoir bougé le panneau : les deux sont refusés pendant 2 s (« vient de bouger »).

## Ce qu'on surveille pendant les premiers jours

- Le journal (`journalctl -u vidange -f`) : les lignes `Pesée du fût absente` et `Carte de pesée muette`
  (boîte du poste). Si la radio se tait souvent plateau au fond : le dire dans une PR (signal radio, trames
  perdues de `vidange-pesee lire`).
- Le poids affiché quand rien ne bouge : s'il dérive de plus de 1 kg en une journée (chaleur), refaire
  le zéro, et le noter.
- La tension de l'accu à la fin de chaque vidange : elle doit remonter (recharge sans contact).

## Si quelque chose ne va pas

- Recopier le message affiché (ou une photo de l'écran) dans une PR ou une discussion : il dit quel signal
  et quoi vérifier.
- Remettre le programme en route dans tous les cas : `sudo systemctl start vidange`.
