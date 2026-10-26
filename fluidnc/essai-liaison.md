# Essai de la liaison Pi ↔ carte FluidNC sur le vrai matériel

Les tests automatiques (GitHub Actions) n'utilisent qu'un **faux** FluidNC. Cette procédure vérifie
la liaison avec une vraie carte. Compter environ 30 minutes pour une carte, puis 5 minutes par carte de plus.

## Avant de commencer

- Le Pi est installé (voir `pi/systeme/installation.md`).
- La carte FluidNC a son programme et ses réglages, elle est alimentée.
- Pour les étapes où un axe bouge : les moteurs sont branchés, **l'axe est libre sur au moins 10 cm
  dans les deux sens**, personne dans la machine, l'arrêt d'urgence à portée de main.
  Les vitesses ci-dessous sont lentes exprès (300 mm/min = 5 mm par seconde).
- Arrêter le programme du Pi (un port USB ne s'ouvre qu'une fois) :

  ```
  sudo systemctl stop vidange
  ```

- Mettre à jour le programme du Pi (cette version ajoute la bibliothèque `pyserial` et la commande
  `vidange-fluidnc`) :

  ```
  cd /opt/vidange-auto && sudo -u vidange git pull
  cd pi && sudo -u vidange .venv/bin/pip install -e .
  ```

Dans les commandes ci-dessous, `vidange-fluidnc` veut dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc`
(et `vidange --verifier` : la commande de vérification de `pi/systeme/installation.md`).

## Étape 1 : lire le numéro de série de chaque carte

1. Brancher **une seule** carte FluidNC sur le Pi par USB.
2. Taper :

   ```
   vidange-fluidnc lister
   ```

   Exemple de réponse : `/dev/ttyACM0 : n° de série « 5A7B012345 », USB Single Serial → aucune carte de fluidnc.yaml`
3. Noter le numéro et le nom de la carte (portique, chariot, mycelium_lavage, prehension). Coller une étiquette
   sur la carte avec ce numéro.
4. Brancher la carte suivante (sans débrancher la première) et recommencer : chaque carte doit avoir
   **un numéro différent**.

**Si une carte affiche « AUCUN », ou si deux cartes ont le même numéro : s'arrêter là** et le signaler
(voir la question 1 de la PR) : la carte ne pourra pas être reconnue de façon sûre.

## Étape 2 : écrire les numéros dans les réglages

1. Ouvrir `/opt/vidange-auto/pi/reglages/fluidnc.yaml` et remplacer chaque `"EXEMPLE-..."` par le vrai numéro,
   **entre guillemets**. Quand les 4 numéros sont vrais, passer `exemple: true` à `exemple: false`.
2. Vérifier :

   ```
   vidange --verifier
   ```

   Attendu : `Réglages corrects`. Sinon le message dit quelle ligne corriger.
3. `vidange-fluidnc lister` doit maintenant afficher le nom de chaque carte au bout de sa ligne (`→ portique`...).
4. Les numéros de série ne sont pas secrets : les donner aussi dans la PR (ou à une session), pour qu'ils
   soient recopiés dans le dépôt.

## Étape 3 : se connecter et lire l'état

```
vidange-fluidnc console portique
```

(remplacer `portique` par la carte essayée). Attendu en moins de 5 secondes : une ligne comme
`au repos  X=0.000  Y=0.000  Z=0.000 mm  (0 ligne(s) en cours)`.

- Si c'est `en alarme (alarme 14 : position inconnue...)` : c'est normal si la carte demande une prise
  d'origine au démarrage. Taper `debloquer`. Attendu : `ok`, puis `etat` affiche `au repos`.
- Taper `etat` plusieurs fois : la réponse doit venir tout de suite.

## Étape 4 : un petit mouvement

Taper, une ligne à la fois :

```
G91
G1 X5 F300
fin
G1 X-5 F300
fin
G90
```

Attendu : l'axe X avance de 5 mm puis revient ; après chaque `fin`, la ligne affichée montre X augmenté de 5,
puis revenu. `G91` = mouvements relatifs, `G90` = retour aux positions absolues (à toujours remettre).

## Étape 5 : pause et reprise

```
G91
G1 X50 F300
pause
etat
reprise
fin
G1 X-50 F300
fin
G90
```

Taper `pause` dans les 5 secondes après `G1 X50 F300`. Attendu : l'axe s'arrête en douceur, `etat` affiche
`en pause` ; après `reprise`, il finit ses 50 mm puis revient.

## Étape 6 : beaucoup de lignes d'un coup (contrôle de flux)

1. Créer un fichier de 100 petits mouvements (10 cm aller, 10 cm retour) :

   ```
   (echo G91; for i in $(seq 50); do echo "G1 X2 F600"; done; for i in $(seq 50); do echo "G1 X-2 F600"; done; echo G90) > /tmp/essai.gcode
   ```

2. Dans la console : `fichier /tmp/essai.gcode`.

Attendu : l'axe fait l'aller-retour **sans à-coups ni arrêts**, puis `102 lignes envoyées en ... s, 0 échec(s)`.
Un « ÉCHEC » ou un mouvement saccadé : le signaler avec ce qu'affiche la console.

## Étape 7 : câble coupé, puis rebranché

1. Axe à l'arrêt, `etat` : noter les positions.
2. **Débrancher** le câble USB de la carte. Dans les 2 secondes, la console écrit
   `Liaison avec la carte « portique » coupée`. `etat` affiche `non connectée`.
3. Rebrancher le câble **sur une autre prise USB du Pi**. Dans les 5 secondes : `Carte « portique » connectée`.
4. `etat` : les positions doivent être **les mêmes qu'au point 1**.

Si les positions sont revenues à 0, ou si la carte est en alarme, ou si la console écrit
`La carte « portique » a (re)démarré` : la carte redémarre quand le Pi rouvre son port. **Le signaler** :
ça veut dire qu'une coupure du câble ferait perdre la position (prise d'origine à refaire).

5. Recommencer en débranchant **pendant** un mouvement (`G91`, `G1 X20 F300`, débrancher tout de suite,
   rebrancher). Attendu : la carte finit son mouvement seule ; après reconnexion, X a avancé de 20 mm.
   Remettre `G90`.

## Étape 8 (si les fins de course sont câblés) : alarme

1. Pendant que l'axe est à l'arrêt, appuyer à la main sur un fin de course de la carte.
2. Attendu (si FluidNC est réglé pour surveiller ce fin de course) : la console écrit
   `alarme 1 : fin de course matérielle touchée`, et `etat` affiche `en alarme`.
3. Relâcher le fin de course, taper `debloquer`. Attendu : `ok`, puis `etat` affiche `au repos`.
   Si `debloquer` ne répond pas, taper `reinit`, puis `debloquer`.

## Fin

1. Taper `quitter`.
2. Relancer le programme du Pi :

   ```
   sudo systemctl start vidange
   ```

## Quoi renvoyer

Pour chaque carte : son nom, son numéro de série, et pour chaque étape « OK » ou ce qui s'est passé
(copier ce qu'affiche la console). À recopier dans la PR ou dans une nouvelle session.
