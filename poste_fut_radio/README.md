# Programmes des 2 ESP32-C3 du poste du fût (plateau de pesée et boîte du poste)

Le fût est pesé **sans fil** (choix de Karulium : « ne rien brancher », `docs/decisions.md`,
« Poste du fût : plateau de pesée sans fil ») :

```
4 capteurs → HX711 → ESP32-C3 du plateau ── radio ESP-NOW, ~1 m ──→ ESP32-C3 de la boîte du poste
                                                                        → MAX3485 → bus des pesées → Pi
```

La radio ne porte que la pesée, **jamais** un verrou ni une sécurité. Si elle se tait, la pesée
est « absente » : affichée, au journal, alerte, et **la machine ne s'arrête jamais pour ça**
(côté Pi : tâche 17 bis). Pas de Wi-Fi ni de réseau : ESP-NOW seulement, une liaison directe
entre les deux cartes.

## Le plateau (`plateau/`)

- Il **dort** tant qu'il est loin du poste (moins de 0,1 mA), et se **réveille sur le reed** :
  l'aimant de la boîte du poste le ferme quand le plateau est poussé au fond.
- Il lit le HX711 à **10 mesures par seconde** (broche RATE du HX711 à la masse), fait la
  **moyenne des 5 dernières**, et envoie **une trame radio toutes les 0,5 s** : mesure brute,
  numéro, HX711 muet, tension et % de l'accu, reed, 5 V de la recharge, USB-C de secours.
- **HX711 muet** : plus de mesure depuis 500 ms (`sans_mesure_ms`) ; la trame le dit, sans mesure.
- **Accu** : sa tension par un pont diviseur sur une entrée analogique, son % par la courbe de
  `pesees.yaml` (`courbe_accu`).
- **5 V de la recharge présent** (registre 8, bit 1, valeur 2) : le récepteur de la recharge sans
  contact donne son 5 V. Ce n'est **pas** « en charge » : il reste vrai accu plein (sinon le Pi
  dirait « recharge sans contact en panne ? » à chaque accu plein).
- Il **se rendort 30 s** après l'ouverture du reed (`sommeil_apres_s`). Le HX711 s'éteint aussi.
- Le numéro des trames continue après le sommeil : la boîte compte bien les trames perdues.
- Voyant de la carte : un éclair à chaque trame reçue par la boîte (accusé de réception radio).

## La boîte du poste (`boite/`)

- **Toujours alimentée** (24 V → 5 V). Elle reçoit les trames, **seulement** celles de l'adresse
  radio du plateau (`pesees.yaml`), et garde la dernière.
- Elle répond au Pi sur le **bus des pesées** comme une carte de pesée : **Modbus RTU**, 115 200
  bauds, 8N1, adresse 4 (`pesee_fut` dans `docs/entrees-sorties.yaml`), fonction 4 (ou 3),
  **registres 0 à 12**, signature **0x5046** (« PF »). Le code Modbus est celui des cartes
  RP2040 (`pesee/src/modbus.c`), pas une copie.
- **Radio muette** : rien reçu du plateau depuis 2 s (`radio_muette_ms`) → registre 4, valeur 4.
- Émetteur-récepteur RS485 **MAX3485** (3,3 V) : DE et /RE reliées ensemble, à 1 pour parler.
- Voyant : allumé = trames du plateau reçues ; clignote = radio muette.

| Registre | Contenu |
|---|---|
| 0 et 1 | dernière mesure brute (moyenne de 5 faite par le plateau), 32 bits signés, mot fort d'abord |
| 2 | numéro de cette mesure (+1 à chaque trame reçue) |
| 3 | âge de cette mesure, en ms (65 535 au plus, et avant la première trame) |
| 4 | état : 1 = HX711 muet (dit par le plateau) ; 2 = réglages d'exemple ; 4 = radio muette |
| 5 | trames reçues pendant la dernière seconde (2 attendues) |
| 6 | questions pour la boîte arrivées abîmées, depuis son démarrage |
| 7 | signature 0x5046 (« PF ») |
| 8 | plateau : 1 = reed fermé (au poste) ; 2 = 5 V de la recharge sans contact présent ; 4 = sur l'USB-C |
| 9 | tension de l'accu, en mV |
| 10 | niveau de l'accu, en % |
| 11 | force du signal radio, en dBm + 200 (120 = −80 dBm) |
| 12 | trames radio perdues (numéros sautés entre deux trames reçues à moins de 2 s), depuis le démarrage |

Côté Pi : `pi/vidange/materiel/carte_pesee.py` (même table), l'outil `vidange-pesee`.

## L'adresse radio (appairage)

Les deux adresses radio sont **écrites dans `pi/reglages/pesees.yaml`** (`poste_fut_radio →
radio`) et **chaque carte prend la sienne** au démarrage : il n'y a rien à relever sur les
cartes. Le plateau n'envoie qu'à l'adresse de la boîte ; la boîte n'écoute que celle du plateau.
Une carte changée : on y recharge le même programme, c'est tout. Pour changer d'adresses (un autre
appareil ESP-NOW tout près), changer les deux dans `pesees.yaml` et recharger **les deux** cartes.

## Les chiffres

Tous dans [`pi/reglages/pesees.yaml`](../pi/reglages/pesees.yaml), section `poste_fut_radio`
(broches, adresses radio, canal, puissance, cadences, délais, pont diviseur, courbe de l'accu),
plus l'adresse de la boîte et la vitesse du bus dans
[`docs/entrees-sorties.yaml`](../docs/entrees-sorties.yaml) (`pesee_fut`, `rs485_pesee`). Ils
sont **vérifiés** par le programme du Pi au démarrage et quand on fabrique les programmes (une
broche prise deux fois, une broche réservée de l'ESP32-C3, un reed qui ne peut pas réveiller la
carte, une courbe qui redescend...), puis copiés dans les programmes (`reglages_radio.h`). Les
changer = refabriquer et recharger les cartes.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `commun/trame.c` | La trame radio (15 octets, avec un contrôle) : écrire, relire (essayé sur PC) |
| `commun/plateau.c` | Le plateau sans le matériel : moyenne, trames, HX711 muet, sommeil (essayé sur PC) |
| `commun/boite.c` | La boîte sans le matériel : dernière trame, radio muette, trames perdues, registres (essayé sur PC) |
| `commun/accu.c` | Tension de l'accu par le pont, % par la courbe (essayé sur PC) |
| `plateau/main/main.c` | L'ESP32-C3 du plateau : HX711, reed, accu, radio, sommeil |
| `boite/main/main.c` | L'ESP32-C3 de la boîte : radio, UART du bus, MAX3485 |
| `tests/` | Les essais sur PC : faux HX711, fausses trames radio, questions Modbus |
| `reglages.cmake` | Copie `pesees.yaml` et l'adresse de `entrees-sorties.yaml` dans les programmes |
| `essai-materiel.md` | **Procédure d'essai sur le vrai matériel**, pas à pas |

Le HX711 et le Modbus viennent de `pesee/src/` (`hx711.c`, `modbus.c`).

## Fabriquer les programmes

GitHub Actions les fabrique à chaque PR : `plateau_fut-complet.bin` et
`boite_poste_fut-complet.bin`, un fichier par carte, à charger à l'adresse 0x0
(`essai-materiel.md`, étape 1).

Pour les fabriquer soi-même (Linux, avec Docker) :

```bash
docker run --rm -v "$PWD":/projet -w /projet espressif/idf:v5.5.4 bash -c 'pip install -q "pydantic>=2.5,<3" "PyYAML>=6.0,<7" && idf.py -C poste_fut_radio/plateau build && idf.py -C poste_fut_radio/boite build'
```

Essais sur PC (sans ESP32-C3) :

```bash
cmake -S poste_fut_radio/tests -B poste_fut_radio/build-essais && cmake --build poste_fut_radio/build-essais
```

```bash
ctest --test-dir poste_fut_radio/build-essais --output-on-failure
```

## Choix faits

- **ESP-IDF** (le cadre officiel d'Espressif, en C) plutôt qu'Arduino : il se fabrique avec CMake
  comme `pesee/`, dans une image Docker officielle à version figée (la même dans GitHub Actions et
  chez soi) ; il a tout ce qu'il faut sans bibliothèque en plus (ESP-NOW, sommeil profond réveillé
  par une broche, entrée analogique étalonnée, chien de garde). Ce qui se teste sur PC est en C
  pur dans `commun/`, sans rien d'ESP-IDF : les essais tournent avec le `gcc` du PC.
- **Les cartes prennent leur adresse radio des réglages** plutôt que d'y recopier celle d'usine :
  rien à relever, une carte changée se recharge sans toucher aux réglages.
- **Trame avec « PF », version et contrôle** : une trame d'un autre programme, ou abîmée, est
  refusée (et comptée dans la fenêtre USB), jamais lue comme une pesée.
- **Pas de chiffrement de la radio** : elle ne porte qu'une pesée, jamais une commande ; une clé
  serait un secret de plus à garder hors du dépôt.
- **Fenêtre USB dans une tâche à part** : si personne ne la lit, la pesée et le bus continuent.
- **Heure de chaque octet du bus** : le pilote de l'UART rend les octets par paquets ; la boîte
  recalcule l'heure d'arrivée de chacun, pour que le Modbus des cartes RP2040 (qui juge les fins
  de trame au silence) marche tel quel.
