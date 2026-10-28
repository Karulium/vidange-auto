# Programme du RP2040 (accéléromètre LIS3DH)

Détecte les chocs horizontaux sur le chariot Z et coupe un signal « OK » vers l'ESP32 n° 1.
Plus tard (tâche 15), il enverra aussi ses mesures au Pi par un fil série (3,3 V, 115 200).

**Le signal « OK » protège la machine (les chocs), jamais les personnes** : la sécurité des
personnes est câblée en dur (arrêt d'urgence, portes, relais de sécurité).

## Ce qu'il fait

- Il lit le LIS3DH par I2C, 400 fois par seconde (réglable), en haute résolution.
- Il retire de chaque mesure un « fond » lent (la pente du capteur, la pesanteur, une dérive),
  puis regarde la force sur les axes horizontaux.
- **Choc** : cette force dépasse le seuil (par exemple 1,5 g) pendant au moins quelques
  millisecondes. « OK » est alors coupé, et reste coupé au moins 0,5 s après le dernier
  dépassement (pour que l'ESP32 le voie à coup sûr). Si la force ne redescend pas (support
  tordu, capteur décroché), « OK » reste coupé : il faut aller voir.
- **Sécurité positive** : la sortie est à 3,3 V seulement quand tout va bien. Elle est à 0 V :
  - au démarrage, tant que le capteur n'a pas passé son **autotest** (une force interne doit
    faire bouger la mesure de chaque axe : un capteur cassé ou décollé ne passe pas) ;
  - sur un choc ;
  - sur une panne : capteur absent, lectures I2C ratées, plus de mesure, mesure figée
    (un vrai capteur a toujours un peu de bruit), réglages faux ;
  - si le programme se fige : le **chien de garde** du RP2040 le redémarre en 0,1 s ;
  - sans courant, ou si le fil est coupé (grâce à une résistance de tirage vers la masse,
    voir la question n° 2 de la PR).
- Après une panne, il revérifie le capteur toutes les 2 s (autotest compris) ; « OK » revient
  seulement si le capteur passe.
- Le petit voyant de la carte : allumé = OK, éteint = choc ou démarrage, clignote = panne.
- Sur le câble USB, une fenêtre texte montre une ligne d'état par seconde (le plus fort niveau
  mesuré, le seuil, le nombre de chocs) et permet de changer le seuil pour les essais.

Tous les chiffres (carte, broches, seuil, durées) sont dans
[`pi/reglages/accelerometre.yaml`](../pi/reglages/accelerometre.yaml), vérifiés par le programme
du Pi au démarrage et quand on fabrique le programme du RP2040.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `src/detecteur.c` | Le cœur : chocs, pannes, décision « OK » (aucun matériel, essayé sur PC) |
| `src/lis3dh.c` | Le capteur : reconnaissance, autotest, réglages, lecture des mesures |
| `src/reglages.c` | Les réglages de départ et leur vérification |
| `src/console.c` | La fenêtre texte par l'USB : commandes et ligne d'état |
| `src/main.c` | Le RP2040 : broches, bus I2C, chien de garde, les deux cœurs |
| `tests/` | Les essais sur PC, avec un faux LIS3DH |
| `reglages.cmake` | Copie `accelerometre.yaml` dans le programme (`reglages_genere.h`) |
| `essai-etabli.md` | **Procédure d'essai à l'établi**, pas à pas |

## Fabriquer le programme

GitHub Actions le fabrique à chaque PR : le fichier `accelerometre.uf2` se télécharge depuis la
page de la vérification (voir `essai-etabli.md`, étape 1). Pour le fabriquer soi-même (Linux) :

```bash
sudo apt install cmake gcc-arm-none-eabi libnewlib-arm-none-eabi python3-pydantic python3-yaml
git clone --depth 1 -b 2.1.1 https://github.com/raspberrypi/pico-sdk.git ~/pico-sdk
git -C ~/pico-sdk submodule update --init --depth 1 lib/tinyusb
cmake -S accelerometre -B accelerometre/build -DPICO_SDK_PATH=$HOME/pico-sdk
cmake --build accelerometre/build
```

Le programme est `accelerometre/build/accelerometre.uf2`.

Essais sur PC (sans RP2040) :

```bash
cmake -S accelerometre/tests -B accelerometre/build-essais
cmake --build accelerometre/build-essais
ctest --test-dir accelerometre/build-essais --output-on-failure
```

## Choix faits

- **C avec le Pico SDK** de Raspberry Pi (gratuit, officiel) plutôt que MicroPython : temps de
  mesure régulier, chien de garde sûr, et le petit chargeur maison de la tâche 16 en a besoin.
- La mesure et la sortie « OK » tournent seules sur un cœur du RP2040 ; la fenêtre USB sur
  l'autre : si l'USB se bloque, la mesure continue.
- Pas de passe-haut dans la puce : le fond lent est calculé dans le programme, ce qui permet de
  le geler pendant un choc (le choc ne s'y fond pas).
- Le seuil changé à la console ne dure que jusqu'au redémarrage : la vraie valeur est celle de
  `accelerometre.yaml` (plus tard, le Pi l'enverra par le fil série, tâche 15).
