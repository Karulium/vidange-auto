# Essai des cartes de pesée à l'établi (tâche 22 bis)

Testé sur le vrai matériel : **non** (seulement sur PC et dans GitHub Actions, avec des faux).

But : vérifier sur le vrai matériel qu'une carte RP2040 lit son HX711 **80 fois par seconde**,
répond au Pi sur le bus RS485, que les 3 cartes se partagent le bus sans se gêner, et que la
griffe est bien lue au moins 80 fois par seconde ; puis étalonner chaque pesée.

Compter environ 1 h 30 pour une carte (étapes 1 à 6), puis 30 min pour les 3 ensemble (étapes 7
et 8), et 15 min d'étalonnage par carte. Rien ne bouge : l'essai se fait sur la table.

Ces pesées protègent la machine (contact, choc, dose), jamais les personnes.

## Ce qu'il faut

- Les 3 cartes RP2040, 3 cartes HX711 et leurs capteurs (ou un seul capteur pour commencer).
- 3 émetteurs-récepteurs RS485 **3,3 V** (MAX3485, SP3485, ou petite carte toute faite « TTL vers
  RS485 3,3 V » avec une broche DE/RE). Pas un MAX485 en 5 V : sa sortie grillerait le RP2040.
- L'adaptateur USB-RS485 du bus des pesées (puce FT232 ou CP2102N), branché sur le Pi.
- 2 résistances de 120 Ω (terminaison aux deux bouts du bus), fils, plaque d'essai.
- Un poids connu par pesée (exemple : 5 kg pour la griffe, 100 g et 1 kg pour le plateau).
- Un câble USB et un PC avec le navigateur **Chrome** ou **Edge** (pour la fenêtre texte).

## 1. Récupérer les programmes

1. Sur GitHub, ouvrir la PR de la tâche 22 bis (ou la plus récente qui touche `pesee/`), onglet
   **Checks** (Vérifications), puis la ligne **Tests**.
2. En bas de la page, partie **Artifacts**, cliquer sur **pesee** : un fichier zip se télécharge.
   Le décompresser : il contient `pesee_griffe.uf2`, `pesee_prehension.uf2` et
   `pesee_plateau_remplissage.uf2`. **Un fichier par carte** (seule l'adresse change) : marquer
   chaque carte à son nom.

## 2. Régler le HX711 sur 80 mesures par seconde

Sur la carte HX711, la broche **RATE** (patte 15 de la puce) choisit la cadence : **au 3,3 V =
80 mesures par seconde**, à la masse = 10. Sur beaucoup de petites cartes vertes toutes faites,
elle est soudée à la masse (10 par seconde) : il faut alors couper la piste et la relier au 3,3 V
(souvent un pont « RATE » à changer, voir la notice de la carte). L'étape 4 dit si c'est bon.

## 3. Brancher une carte (carte débranchée de l'USB)

Les numéros de broches sont ceux de `pi/reglages/pesees.yaml` (exemple : carte « pico »). S'ils
ne vont pas avec la carte achetée, le dire dans la PR : on change le fichier, GitHub refait les
programmes.

| HX711 | RP2040 |
|---|---|
| VCC et VDD | 3V3 (jamais le 5 V : le DT grillerait la broche du RP2040) |
| GND | GND |
| DT (DOUT) | GPIO 2 (`hx711_dt`) |
| SCK | GPIO 3 (`hx711_sck`) |

| Émetteur-récepteur RS485 3,3 V | RP2040 |
|---|---|
| VCC | 3V3 |
| GND | GND |
| DI (entrée des données) | GPIO 0 (`rs485_tx`) |
| RO (sortie des données) | GPIO 1 (`rs485_rx`) |
| DE et /RE (reliées ensemble) | GPIO 6 (`rs485_sens`) |
| A et B | A et B de l'adaptateur USB-RS485 (A avec A, B avec B) |

Relier aussi le **0 V** de l'adaptateur USB-RS485 au GND de la carte (un bus RS485 a besoin d'un
0 V commun). Une résistance de 120 Ω entre A et B à chaque bout du bus.

## 4. Charger le programme et ouvrir la fenêtre texte

1. Tenir appuyé le bouton **BOOTSEL** de la carte, brancher l'USB, lâcher le bouton.
2. Un disque nommé **RPI-RP2** apparaît sur le PC. Y copier le fichier de **cette** carte
   (exemple : `pesee_griffe.uf2`). La carte redémarre seule (le disque disparaît).
3. Dans Chrome, ouvrir <https://googlechromelabs.github.io/serial-terminal/>, cliquer
   **Connect**, choisir la carte. On doit lire « Carte de pesée « pesee_griffe », adresse 1 sur le
   bus, 115200 bauds. », sa version, puis une ligne par seconde :
   `brut 123456 | 80 mesures/s | 0 questions du Pi | 0 trames abîmées | HX711 ok`.

**À noter dans la PR** : le nombre de mesures par seconde (80 attendu ; 10 = étape 2 à refaire).

## 5. Les essais de la carte seule

Cocher chaque ligne ; si un résultat est différent, noter ce qui s'affiche.

| # | Faire | Attendu |
|---|---|---|
| 1 | Ne rien toucher | Voyant allumé ; `80 mesures/s` ; `HX711 ok` ; « brut » qui bouge un peu (bruit) |
| 2 | Appuyer doucement sur le capteur | « brut » change franchement, puis revient |
| 3 | Débrancher le fil DT du HX711 | En moins d'une seconde : `HX711 MUET`, voyant qui clignote, `0 mesures/s` |
| 4 | Rebrancher le fil DT | `HX711 ok` revient seul, voyant allumé |
| 5 | Couper l'alimentation 3,3 V du HX711 seulement, puis la remettre | `HX711 MUET`, puis `ok` revient seul |

## 6. La carte et le Pi

1. Brancher l'adaptateur USB-RS485 sur le Pi et lire son numéro de série :
   `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc lister` (la commande liste
   tous les ports série USB). **Si le numéro est « AUCUN » : s'arrêter et le signaler** (il faut une
   puce FT232 ou CP2102N).
2. L'écrire dans `docs/entrees-sorties.yaml` (carte `rs485_pesee`, `numero_serie_usb`, entre
   guillemets).
3. Arrêter le programme du Pi (`sudo systemctl stop vidange`), puis taper
   `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-pesees lire`. Une ligne par carte et
   par seconde, par exemple :
   `pesee_griffe   brut 123456   3.086 kg  carte  80 mesures/s  vues par le Pi  80/s  sans réponse 0  trames abîmées 0`.
   Les cartes pas encore branchées disent « ne répond pas » : c'est normal.
4. Dans la fenêtre texte de la carte : « questions du Pi » est maintenant au-dessus de 100.

| # | Faire | Attendu |
|---|---|---|
| 6 | Laisser tourner 1 minute | « sans réponse 0 » et « trames abîmées 0 » sur toutes les lignes de la carte branchée |
| 7 | Débrancher le fil A du bus | La carte : « ne répond pas » ; le reste continue |
| 8 | Rebrancher le fil A | La carte répond de nouveau, seule |
| 9 | Débrancher le fil DT du HX711 | La ligne de la carte finit par `HX711 MUET` ; le poids : `ÉCHEC (... HX711 muet ...)` |
| 10 | Débrancher puis rebrancher l'adaptateur USB du Pi | Après quelques secondes en échec, les mesures reviennent seules |

## 7. Les 3 cartes sur le même bus

1. Charger dans chaque carte **son** fichier (étape 4) et vérifier son adresse dans la fenêtre
   texte (griffe 1, préhension 2, plateau 3).
2. Les brancher toutes les 3 sur le bus (A avec A, B avec B, 0 V commun), en ligne (pas en
   étoile), avec les 120 Ω aux deux bouts seulement.
3. `vidange-pesees lire` pendant 2 minutes.

| # | Attendu |
|---|---|
| 11 | Les 3 cartes répondent ; « sans réponse 0 » et « trames abîmées 0 » partout |
| 12 | **pesee_griffe : « vues par le Pi » à 78 ou plus** (80 = toutes les mesures de la carte) |
| 13 | Les 2 autres : 40 « vues par le Pi » ou plus |

**À noter dans la PR** : les « vues par le Pi » des 3 cartes. Si la griffe en a moins de 78 :
le dire (on changera l'ordre des questions, `tour` dans `pesees.yaml`).

## 8. Le câble de la machine

Refaire les essais n° 11 à 13 avec le vrai câble de 10 m (ses fils DT et SCK servent de A et B) et
la prise magnétique, puis en faisant tourner un moteur pas à pas à côté. Des « trames abîmées »
qui montent = parasites : vérifier le 0 V commun, le blindage, les 120 Ω.

## 9. Étalonner chaque pesée

Pour chaque carte (exemple avec la griffe ; remplacer le nom pour les autres) :

1. Rien de plus sur la pesée (griffe : godet vide, rien d'accroché) :
   `vidange-pesees zero pesee_griffe`. Recopier la ligne `zero_brut: ...` dans
   `pi/reglages/pesees.yaml`, partie `etalonnage → pesee_griffe`.
2. Poser (ou accrocher) le poids connu, exemple 5 kg :
   `vidange-pesees etalonner pesee_griffe 5`. Recopier la ligne `brut_par_kg: ...`.
3. `vidange-pesees lire` : le poids affiché doit être celui posé (± 1 %). Enlever le poids : 0
   (± 1 %). Le plateau du remplissage : poser 100 g, l'affichage doit monter de 0,100 kg (± 2 g).

Quand les 3 sont faites : passer `exemple: false` dans `pesees.yaml`, et enlever `exemple: true`
des lignes `rs485_pesee`, `pesee_griffe`, `pesee_prehension` et `pesee_plateau_remplissage` de
`docs/entrees-sorties.yaml`. Puis refaire les programmes (GitHub les refait à la PR) et les
recharger : la check-list du Pi dit « programme de la carte fait avec des réglages d'exemple »
tant que ce n'est pas fait.

## À la fin

Redémarrer le programme : `sudo systemctl start vidange`. La check-list de démarrage (page web)
doit montrer une ligne verte par carte : « répond, 80 mesures par seconde ».

Noter dans la PR (ou dire à la session suivante) les essais réussis, les « vues par le Pi » de
l'étape 7, et ce qui a été changé dans les fichiers.
