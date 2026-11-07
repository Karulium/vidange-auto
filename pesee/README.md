# Programme des cartes de pesée (RP2040 + HX711, bus RS485)

Trois cartes identiques (la carte du plateau a en plus un I2C, voir plus bas), chacune près de son HX711 : **griffe** (capteur 50 kg), **préhension**
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

Les registres 0 à 7 sont les mêmes sur les 3 cartes et ne changent jamais. La carte du plateau du
remplissage a en plus des registres 8 et suivants (voir « L'I2C du plateau du remplissage »).

La carte ne donne que la **mesure brute** : le poids en kilogrammes est calculé par le Pi, avec
l'étalonnage de `pi/reglages/pesees.yaml`. Changer l'étalonnage ne demande donc jamais de toucher
aux cartes.

Chaque carte entend aussi les questions aux autres cartes et leurs réponses : elle compte les
octets de ces réponses pour être prête tout de suite à la question suivante (le Pi ne laisse pas
de silence entre deux questions). Après une trame abîmée, elle attend un silence de 1,75 ms.

Côté Pi : `pi/vidange/pesees/` (le tour des questions, le poids en kg ou en newtons) et l'outil
`vidange-pesees` des essais.

## L'I2C du plateau du remplissage (tâche 40 bis)

Seule la carte du plateau du remplissage a un I2C (réglage par carte : `i2c → carte` dans
`pesees.yaml`). Les cartes de la griffe et de la préhension n'ont rien de plus : même programme,
mêmes 8 registres, et si on lit un registre 8 ou plus elles répondent « registre inconnu ».
Sur cet I2C (exemple : I2C0, GP4 pour SDA et GP5 pour SCL, 100 kHz) :

- la **PCA9685** (16 sorties PWM) : une voie par servo (escamotage de la tête du Micropore, lame
  du Micropore, signal du servo de la Fermeture des seaux). Le Pi demande un **angle** ; la carte
  en fait la **largeur d'impulsion** avec les réglages de la voie (angle et impulsion du plus petit
  et du plus grand côté) ;
- le **VL6180X** : capteur de distance (en mm) et son état.

| Registre | Contenu | Lecture | Écriture |
|---|---|---|---|
| 8 | distance du ToF, en mm (65 535 = pas de bonne mesure) | oui | non |
| 9 | état du ToF : 0 = bonne mesure, 1 à 15 = code de la puce (hors de portée...), 256 = pas encore de mesure, 512 = capteur muet | oui | non |
| 10 | âge de la dernière mesure du ToF, en ms (65 535 au plus) | oui | non |
| 11 | **compteur de démarrages** de la carte (change à chaque démarrage) | oui | non |
| 12 | **état de l'I2C** (bits : 1 = PCA9685 muette, 2 = ToF muet, 4 = aucun ordre du Pi depuis le démarrage, 8 = Pi silencieux depuis plus de 2 s, 16 = PCA9685 pas encore démarrée) | oui | non |
| 13 | transactions I2C restées sans réponse depuis le démarrage | oui | non |
| 14 | temps depuis le dernier ordre du Pi, en ms (65 535 au plus) | oui | non |
| 15 | nombre de voies de servo du programme de la carte | oui | non |
| 16, 17, 18... | **angle** de chaque voie, en dixièmes de degré (nombre signé ; `0x8000` = sortie coupée) | oui | **oui** (fonction 6 ou 16) |

L'ordre des voies (16, 17, 18...) est celui de `i2c → pca9685 → voies` dans `pesees.yaml`. Le Pi lit
les registres 8 à 15 + le nombre de voies d'un coup (une question à part de la pesée) et écrit les
angles en une trame (`Materiel.lire_boitier_chariot` et `ecrire_angles_chariot`).

Fonctionnement :

- **La PCA9685 démarre sorties coupées** : au démarrage la carte met la puce en veille, règle la
  fréquence, coupe TOUTES les sorties, puis la réveille. Un servo ne reçoit d'impulsion qu'après un
  ordre du Pi (registre 12, bit 4 : « aucun ordre depuis le démarrage »).
- **Un ordre** est une écriture acceptée. Un angle hors de la plage de sa voie refuse toute
  l'écriture (exception 3, rien ne bouge). Le Pi renvoie les angles au moins toutes les secondes,
  même sans les changer : la carte réécrit alors l'impulsion (le servo ne bouge pas), ce qui remet
  à l'angle une PCA9685 qui aurait perdu son alimentation sans que la carte le sache.
- **Plus de 2 s sans ordre du Pi** (`silence_pi_ms`) : la carte **garde les angles** (aucun
  mouvement, elle ne coupe ni ne recentre rien) et le dit (registre 12, bit 8).
- **Compteur de démarrages** : +1 après un redémarrage de la carte (chien de garde), un nombre au
  hasard après une mise sous tension (une mémoire du RP2040 qui survit au chien de garde mais pas
  à la coupure). Le Pi compare avec la valeur lue d'avant : **s'il a changé, il renvoie tous les
  angles**. Il ne faut donc pas chercher « +1 » mais « différent ».
- **Panne d'une puce** (débranchée, bus bloqué) : la carte le dit (registre 12), réessaie toutes
  les `reessai_ms`, et, si c'est la PCA9685, la remet en route et renvoie les angles au retour.
- **La pesée garde son rythme** : une seule courte transaction I2C (moins de 1 ms) à la fois, faite
  seulement quand ni une mesure du HX711 ni un octet du bus n'attendent ; chaque transaction est
  abandonnée au bout de `delai_transaction_us` (sous les 1,75 ms du silence de fin de trame). Les
  essais sur PC (`tests/essais_rythme.c`) comptent les mesures d'un HX711 à 80 par seconde avec
  l'I2C en route, capteur absent, puces absentes ou bus bloqué : aucune mesure perdue, 80 par
  seconde.
- Les gestes (escamoter la tête, couper le ruban, fermer un seau) ne sont **pas** ici : ils sont
  aux tâches 40 (Micropore) et 41 (Fermeture). La carte ne sait que mettre un servo à un angle et
  lire une distance.

Essai sur le vrai matériel : `essai-boitier-chariot.md`.

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
| `src/pca9685.c` | Pilote de la PCA9685 (servos) : démarrage sorties coupées, angle → impulsion (essayé sur PC) |
| `src/vl6180x.c` | Pilote du capteur de distance VL6180X, une courte transaction à la fois (essayé sur PC) |
| `src/plateau.c` | Le boîtier du chariot : registres 8 et suivants, ordres, silence du Pi (essayé sur PC) |
| `src/i2c_bus.h` | Le bus I2C vu par ces pilotes (le vrai dans `main.c`, un faux dans `tests/`) |
| `src/main.c` | Le RP2040 : broches, UART du bus, chien de garde, voyant, fenêtre USB |
| `tests/` | Les essais sur PC, avec un faux HX711 et des trames Modbus |
| `reglages.cmake` | Copie `pesees.yaml` et les adresses de `entrees-sorties.yaml` dans le programme |
| `essai-etabli.md` | **Procédure d'essai à l'établi**, pas à pas |
| `essai-boitier-chariot.md` | **Procédure d'essai de l'I2C** du plateau du remplissage (servos, ToF) |

Tous les chiffres (carte, broches, délais, et pour l'I2C : adresses, voies de la PCA9685, angles et
largeurs d'impulsion) sont dans
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

Les fichiers sont dans `pesee/build/`. Le fichier `pesee_plateau_remplissage.uf2` est le seul à
contenir l'I2C (`REGLAGE_AVEC_I2C`). Leur nom de version est le commit Git (« -modifie » s'il y
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
- **L'I2C sur la carte du plateau seulement**, choisi par un réglage (`i2c → carte`) et non par un
  autre programme : le même code sert aux 3 cartes, les deux autres n'en utilisent rien
  (`REGLAGE_AVEC_I2C` à 0) et gardent leur table de 8 registres.
- **Le Pi demande des angles, pas des impulsions** : la largeur d'impulsion de chaque servo est
  dans `pesees.yaml` ; changer de servo ne demande jamais de toucher au code.
- **Des transactions I2C courtes, une à la fois**, dans les creux de la boucle : l'I2C ne peut pas
  retarder la lecture du HX711 (la mesure prête ne reste que 12,5 ms).
- **Pas de mise à jour par le bus** (voir la PR, question 1) : il faudrait un chargeur adapté au
  RS485 (adresses, sens de l'émetteur-récepteur) et à 3 cartes, de la taille de la tâche 16.
  Pour l'instant, une mise à jour se fait par l'USB-C de la carte.
