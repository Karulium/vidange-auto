# Programme des cartes de pesée (RP2040 + HX711, bus RS485)

Trois cartes identiques, chacune près de son HX711 : **griffe** (capteur 50 kg), **préhension**
(palier pesé du mât, Phidgets 3135 50 kg) et **plateau du remplissage** (balance du chariot).
Chaque carte lit son HX711 en continu, **80 fois par seconde**, et répond au Pi sur le **bus RS485
des pesées** quand il l'interroge. Les fils DT et SCK des anciens câbles deviennent A et B du bus.

Ces pesées protègent la **machine** (contact, choc, dose), jamais les personnes : la sécurité des
personnes est câblée en dur.

## Ce qu'il fait

- Il lit le HX711 (alimenté en 3,3 V) dès qu'une mesure est prête : 24 bits, voie A, gain 128.
  La cadence se choisit **sur la carte HX711**, par sa broche RATE : RATE au 3,3 V = 80 mesures
  par seconde ; RATE à la masse = 10 (beaucoup de cartes HX711 vendues toutes faites sont à 10 :
  voir `essai-etabli.md`).
- Il garde la dernière mesure, son numéro, son heure, et compte les mesures de chaque seconde.
- **HX711 muet** : plus de mesure depuis 100 ms (`sans_mesure_ms`) : capteur ou HX711 débranché.
  La carte le dit au Pi (et son voyant clignote) ; le Pi refuse alors la pesée.
- Il ne parle sur le bus **que pour répondre** à une question qui lui est adressée.
- **Chien de garde** : programme figé plus de 0,1 s = la carte redémarre seule.
- Sur le câble USB, une fenêtre texte montre une ligne par seconde : mesure brute, mesures par
  seconde, questions du Pi, trames abîmées, état du HX711.
- Le voyant de la carte : allumé = le HX711 mesure ; clignote = HX711 muet.

## Le bus : Modbus RTU

Le Pi interroge les 3 cartes à tour de rôle, à 115 200 bauds (8 bits, sans parité, 1 bit d'arrêt),
en **Modbus RTU** : la langue la plus courante des appareils RS485, déjà parlée par le Pi pour les
transmetteurs d'ozone. Une question (8 octets) et sa réponse (21 octets) tiennent en moins de 3 ms.
N'importe quel outil Modbus (sur PC : QModMaster, mbpoll...) peut lire une carte pour un essai.

Une seule question : **lire les registres** (fonction 4, ou 3 : même table), de 0 à 7 :

| Registre | Contenu |
|---|---|
| 0 et 1 | dernière mesure brute du HX711 (nombre signé de 32 bits, le mot fort d'abord) |
| 2 | numéro de cette mesure (+1 à chaque mesure) |
| 3 | âge de cette mesure, en ms |
| 4 | état : 1 = HX711 muet, 2 = programme fait avec des réglages d'exemple |
| 5 | mesures faites pendant la dernière seconde (80 attendues) |
| 6 | questions pour cette carte arrivées abîmées, depuis son démarrage |
| 7 | signature 0x5053 (« PS ») : c'est bien une carte de pesée |

La carte ne donne que la **mesure brute** : le poids en kilogrammes est calculé par le Pi, avec
l'étalonnage de `pi/reglages/pesees.yaml`. Changer l'étalonnage ne demande donc jamais de toucher
aux cartes.

Chaque carte entend aussi les questions aux autres cartes et leurs réponses : elle compte les
octets de ces réponses pour être prête tout de suite à la question suivante (le Pi ne laisse pas
de silence entre deux questions). Après une trame abîmée, elle attend un silence de 1,75 ms.

Côté Pi : `pi/vidange/pesees/` (le tour des questions, le poids en kg ou en newtons) et l'outil
`vidange-pesees` des essais.

## Une adresse par carte

Le même programme sert aux 3 cartes ; seule leur **adresse sur le bus** change. Elle est écrite
dans `docs/entrees-sorties.yaml` (champ `adresse` des signaux `pesee_griffe`,
`pesee_prehension`, `pesee_plateau_remplissage`) et copiée dans le programme quand on le
fabrique : **un fichier par carte**, à son nom (`pesee_griffe.uf2`...). Charger le mauvais fichier
dans une carte = deux cartes à la même adresse : le Pi verrait des réponses abîmées. Marquer
chaque carte à son nom.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `src/hx711.c` | Lecture du HX711 par ses deux broches (aucun matériel, essayé sur PC) |
| `src/modbus.c` | Modbus RTU côté carte : reconnaître une question, écrire la réponse (essayé sur PC) |
| `src/mesures.c` | Dernière mesure, mesures par seconde, HX711 muet, table des registres (essayé sur PC) |
| `src/main.c` | Le RP2040 : broches, UART du bus, chien de garde, voyant, fenêtre USB |
| `tests/` | Les essais sur PC, avec un faux HX711 et des trames Modbus |
| `reglages.cmake` | Copie `pesees.yaml` et les adresses de `entrees-sorties.yaml` dans le programme |
| `essai-etabli.md` | **Procédure d'essai à l'établi**, pas à pas |

Tous les chiffres (carte, broches, délais) sont dans
[`pi/reglages/pesees.yaml`](../pi/reglages/pesees.yaml), vérifiés par le programme du Pi au
démarrage et quand on fabrique le programme. Les adresses et la vitesse du bus sont dans
[`docs/entrees-sorties.yaml`](../docs/entrees-sorties.yaml) (carte `rs485_pesee`).

## Fabriquer le programme

GitHub Actions le fabrique à chaque PR ; les 3 fichiers `.uf2` se téléchargent depuis la page de
la vérification (voir `essai-etabli.md`, étape 1).

Pour les fabriquer soi-même (Linux) :

```bash
sudo apt install cmake gcc-arm-none-eabi libnewlib-arm-none-eabi python3-pydantic python3-yaml
```

```bash
git clone --depth 1 -b 2.1.1 https://github.com/raspberrypi/pico-sdk.git ~/pico-sdk
```

```bash
git -C ~/pico-sdk submodule update --init --depth 1 lib/tinyusb
```

```bash
cmake -S pesee -B pesee/build -DPICO_SDK_PATH=$HOME/pico-sdk && cmake --build pesee/build
```

Les fichiers sont dans `pesee/build/`. Leur nom de version est le commit Git (« -modifie » s'il y
avait des changements pas encore enregistrés) ; la carte le dit dans sa fenêtre USB.

Essais sur PC (sans RP2040) :

```bash
cmake -S pesee/tests -B pesee/build-essais && cmake --build pesee/build-essais
```

```bash
ctest --test-dir pesee/build-essais --output-on-failure
```

## Choix faits

- **Modbus RTU** plutôt qu'une langue maison : le décodeur côté Pi existait déjà (ozone), les
  trames sont courtes (la griffe tient ses 80 mesures par seconde avec les deux autres cartes sur
  le même bus), et un outil Modbus du commerce peut lire une carte pour un dépannage.
- **La carte mesure seule** et le Pi lit la dernière mesure : la cadence du HX711 ne dépend pas du
  Pi, et une question n'attend jamais une mesure (réponse immédiate). Le numéro et l'âge de la
  mesure disent au Pi si elle est fraîche.
- **Le poids est calculé par le Pi** : l'étalonnage se change dans `pesees.yaml`, sans recharger
  les cartes.
- **Un programme par carte** (adresse écrite dedans) plutôt que des cavaliers d'adresse : rien à
  souder, et l'adresse vient de la même liste que celle du Pi (pas de double saisie).
- **C avec le Pico SDK**, comme l'accéléromètre. Un cœur pour le HX711 et le bus ; l'autre pour la
  fenêtre USB, qui ne peut donc jamais retarder une réponse.
- **Pas de mise à jour par le bus** (voir la PR, question 1) : il faudrait un chargeur adapté au
  RS485 (adresses, sens de l'émetteur-récepteur) et à 3 cartes, de la taille de la tâche 16.
  Pour l'instant, une mise à jour se fait par l'USB-C de la carte.
