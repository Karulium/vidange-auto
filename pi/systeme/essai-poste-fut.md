# Essai du poste du fût sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent que des
**faux** capteurs et une **fausse** carte de pesée. Cette procédure vérifie, au poste du fût :
le détecteur du chariot (inductif M12), le contact du panneau (reed), le bouton « Prêt » et son voyant,
la pesée (carte HX711 et ses 2 capteurs), son étalonnage, et la prise débranchée.
Compter environ 1 h 30 la première fois (dont 30 min pour l'étalonnage).

Rien ne bouge seul au poste du fût : cet essai ne fait bouger aucun moteur.

## Avant de commencer

- Le Pi est installé (voir `installation.md`) et l'essai des entrées/sorties est fait
  (`essai-entrees-sorties.md`, au moins l'étape 1 : I2C et broches GPIO).
- Les lignes du poste sont remplies dans `docs/entrees-sorties.yaml` d'après le plan de câblage
  (carte, broche, sens au repos) : `chariot_fut_en_place`, `reed_panneau_poste_fut`, `bouton_pret_fut`,
  `voyant_pret_fut`, `pesee_fut`. Tant qu'elles portent `exemple: true`, ce sont des exemples.
- **Carte HX711 alimentée en 3,3 V** (pas en 5 V) : sinon son fil DT envoie 5 V dans la broche du Pi,
  qui grille.
- Arrêter le programme du Pi (les broches ne se prennent qu'une fois) :

  ```
  sudo systemctl stop vidange
  ```

- Mettre à jour le programme du Pi (cette version ajoute la commande `vidange-pesee`) :

  ```
  cd /opt/vidange-auto && sudo -u vidange git pull
  cd pi && sudo -u vidange .venv/bin/pip install -e .
  ```

Dans les commandes ci-dessous, `vidange-es` veut dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-es`, et `vidange-pesee` veut dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-pesee`.

## Étape 1 : le détecteur du chariot

1. Chariot du fût **hors** du poste. Lancer :

   ```
   vidange-es surveiller chariot_fut_en_place reed_panneau_poste_fut bouton_pret_fut
   ```

2. Rouler le chariot jusqu'aux 2 butées d'angle du fond. Quand le bout du châssis arrive à environ 4 mm
   du détecteur (butée côté portique), l'écran doit afficher `chariot_fut_en_place : ACTIONNÉ`.
   La petite lumière du détecteur s'allume aussi.
3. Reculer le chariot de 2 cm : `chariot_fut_en_place : repos`. Le remettre au fond : `ACTIONNÉ`.
4. **Si c'est à l'envers** (actionné chariot absent) : la ligne `repos:` du signal est fausse dans
   `docs/entrees-sorties.yaml` (`ouvert` ↔ `ferme`). **Si rien ne change** : câblage du détecteur
   (marron +24 V, bleu 0 V, noir signal) ou distance trop grande (le régler à 3-4 mm).

## Étape 2 : le contact du panneau

1. Toujours avec `vidange-es surveiller` : lever le panneau long jusqu'en haut.
   `reed_panneau_poste_fut : ACTIONNÉ` (contact fermé = panneau levé = production permise).
2. Le rabattre : `repos`. Le laisser à mi-course : `repos` aussi (le Pi ne sait pas distinguer
   « rabattu » de « entre les deux » avec un seul contact).
3. Si c'est à l'envers : corriger `repos:` dans `docs/entrees-sorties.yaml`.

## Étape 3 : le bouton « Prêt » et son voyant

1. Toujours avec `vidange-es surveiller` : appuyer sur le bouton lumineux « Prêt ».
   `bouton_pret_fut : ACTIONNÉ`, puis `repos` en le relâchant. Arrêter avec Ctrl+C.
2. Allumer puis éteindre le voyant du bouton :

   ```
   vidange-es commander voyant_pret_fut oui
   vidange-es commander voyant_pret_fut non
   ```

   Le voyant du bouton s'allume, puis s'éteint.

## Étape 4 : la pesée répond

1. Chariot au fond, **prise magnétique de la pesée branchée**. Lancer :

   ```
   vidange-pesee lire
   ```

   Une ligne par seconde, par exemple `poids lu   1234.56 kg   substrat   1194.56 kg`. Les chiffres
   sont faux tant que la pesée n'est pas étalonnée (étape 5) : on regarde seulement qu'**ils changent
   quand on appuie** sur le berceau, et qu'ils restent **stables** (à quelques dixièmes près) sans y toucher.
2. Ctrl+C pour finir.
3. **Si « ÉCHEC : pesée débranchée »** alors que la prise est branchée : la carte HX711 ne dit jamais
   « mesure prête ». Vérifier l'alimentation de la carte (3,3 V), les fils DT et SCK (DT sur la 1ʳᵉ
   broche de `pesee_fut`, SCK sur la 2ᵉ), et la prise magnétique (contacts propres).
4. **Si « ÉCHEC : lectures de la pesée trop dispersées »** sans toucher au chariot : parasites sur le
   câble de 10 m. Le noter dans la PR (voir « Ce qu'on surveille » plus bas).

## Étape 5 : l'étalonnage (zéro, poids connu, tare)

Il faut un **poids connu** d'au moins 20 kg (sac pesé sur une balance juste, ou poids en fonte).
Chaque commande lit environ 30 mesures (3 à 4 s) et affiche **la ligne à recopier** dans
`pi/reglages/machine.yaml`, partie `poste_fut` → `pesee`. L'outil n'écrit jamais lui-même dans les
réglages. Après chaque recopie, sauvegarder le fichier avant la commande suivante.

1. **Zéro** : chariot au fond, **rien sur le berceau** (ni fût, ni outil). Ne pas toucher au chariot.

   ```
   vidange-pesee zero
   ```

   Recopier la ligne `zero_brut: ...`.
2. **Poids connu** : poser le poids connu au milieu du berceau (exemple : 20 kg).

   ```
   vidange-pesee etalonner 20
   ```

   Recopier la ligne `brut_par_kg: ...`. Retirer le poids.
3. **Vérifier** : reposer le poids, lancer `vidange-pesee lire` : le poids lu doit être le poids connu
   (à 0,2 kg près). Le poser à un autre endroit du berceau : même résultat (sinon, un capteur de pesage
   est mal fixé). Ctrl+C.
4. **Tare** (berceau + fût vide) : poser un **fût vide** sur le berceau, couvercle compris.

   ```
   vidange-pesee tare
   ```

   Recopier la ligne `tare_kg: ...`.
5. Vérifier `plausible_kg` (poids lu permis au « Prêt », berceau + fût + contenu) : par défaut 20 à
   400 kg. L'ajuster si besoin (un fût plein ne doit jamais être en dehors).
6. Dans la même partie, passer `exemple: true` à `exemple: false`. Vérifier les réglages :

   ```
   sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange --verifier
   ```

   Il doit répondre « Réglages corrects ». Le changement de réglages part ensuite dans une PR
   (comme d'habitude), pour que `main` garde les bons chiffres.

## Étape 6 : le poste complet, avec le programme

1. Relancer le programme : `sudo systemctl start vidange`. Ouvrir la page web (téléphone).
2. **Chariot absent** : la page web montre « Poste du fût — Chariot du fût absent ». Le voyant du bouton
   **clignote** (0,5 s allumé, 0,5 s éteint).
3. Rouler un chariot avec un fût plein au fond, **sans brancher la pesée**. L'écran de l'armoire passe
   tout seul sur la page du poste : « EN PLACE, PAS PRÊT », les gestes à faire, et « Il manque : pesée
   qui répond : brancher la prise magnétique ». Appuyer sur le bouton « Prêt » : rien ne change
   (refusé) ; la page web dit pourquoi.
4. Brancher la prise, attendre 2 s : « Substrat : ... kg » (environ le poids du substrat), et plus rien
   ne manque. Appuyer sur « Prêt » (bouton du poste, ou écran, ou page web) : « PRÊT », le voyant reste
   **allumé fixe**, l'écran revient sur la page d'état. Dans l'historique de la page web, un cycle
   « vidange » commence, avec la mesure `poids_fut_plein`.
5. **Prise débranchée** : débrancher la prise magnétique. Le poste reste « Prêt » (un oubli ne casse rien),
   la page web dit « Pesée : pesée débranchée ». Le programme ne s'arrête pas. Rebrancher : le poids revient
   en 1 à 2 s.
6. **Chariot qui bouge** : desserrer le frein et reculer le chariot de 2 cm. Le poste n'est plus prêt,
   le voyant clignote de nouveau. Le remettre au fond, attendre 2 s, appuyer sur « Prêt » :
   « Prêt de nouveau : la vidange du fût continue » (même cycle).
7. **Chariot retiré** : sortir le chariot. Au bout de 2 s, la vidange commencée est close
   (« fût retiré avant la fin de la vidange », cycle « abandonné » dans l'historique). C'est normal pour
   cet essai : la vraie vidange (gestes de la griffe) viendra avec la tâche 18.

## Étape 7 : le panneau et le mode

1. Panneau levé (contact fermé), attendre 2 s : passer en mode **Lavage** à l'écran (MODE → LAVAGE → OUI) ;
   le lancement d'un lavage sera refusé par le Pi avec « Lavage refusé : le panneau long du poste du fût
   est levé. Le rabattre. » (visible quand le module Lavage sera écrit, tâche 21).
2. Panneau rabattu : c'est la production qui sera refusée (« n'est pas levé »).
3. Juste après avoir bougé le panneau : les deux sont refusés pendant 2 s (« vient de bouger »).

## Ce qu'on surveille pendant les premiers jours

- Le journal (`journalctl -u vidange -f`) : une lecture de la pesée interrompue par Linux (impulsion
  d'horloge trop longue) est refaite sans rien dire. Si les lignes `Poste du fût : lectures de la pesée
  interrompues par Linux` ou `lectures trop dispersées` reviennent souvent : le dire dans une PR. La
  solution serait de faire lire la carte HX711 par le pilote de Linux (voir la question n° 1 de la PR
  de la tâche 17).
- Le poids affiché quand rien ne bouge : s'il dérive de plus de 1 kg en une journée (chaleur), refaire
  le zéro, et le noter.

## Si quelque chose ne va pas

- Recopier le message affiché (ou une photo de l'écran) dans une PR ou une discussion : il dit quel signal
  et quoi vérifier.
- Remettre le programme en route dans tous les cas : `sudo systemctl start vidange`.
