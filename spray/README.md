# Carte ESP32 n° 5 du spray : la table des registres

La carte n° 5, dans la boîte du spray, fait le travail fin : elle pompe jusqu'à ce que le flacon ait
perdu le poids demandé, ouvre les électrovannes, fait pivoter le bras de la buse. Le Pi lui donne des
ordres et lit ses réponses. **Ce fichier est la langue commune** entre le programme de la carte
(tâche 39 bis, dans ce dossier) et le programme du Pi (tâche 39 : `pi/vidange/materiel/carte_spray.py`
pour la table, `pi/vidange/spray/` pour les gestes). Un changement se fait **des deux côtés en même
temps**, et augmente le numéro de version (registre 1).

Le spray **ne protège personne**. L'arrêt d'urgence, le store et la porte de la boîte (chaîne UV-ozone)
sont câblés. Les refus de la carte et du Pi protègent la **machine** (le bras, la buse).

## Le bus

- **Modbus RTU** sur RS485, sur **le bus `rs485_spray`, à la carte seule** : son propre adaptateur
  USB-RS485 dans l'armoire (reconnu par son numéro de série), câble `c_spray` (paire torsadée A/B + 0 V,
  120 Ω aux 2 bouts, polarisation de repos sur l'adaptateur). Une panne du spray ne coupe pas les pesées.
- Côté carte : MAX3485 en 3,3 V, DE et /RE reliées.
- **Adresse 1, 115 200 bauds, 8 bits, sans parité, 1 bit d'arrêt** (EXEMPLES, dans
  `docs/entrees-sorties.yaml` : carte `rs485_spray`, signal `carte_spray`). L'adresse et la vitesse
  sont copiées dans le programme quand on le fabrique.
- Deux fonctions seulement : **4** (lire les registres d'entrée 0 à 29, d'un coup) et **16** (écrire
  les registres 100 à 104). Toute autre fonction : exception 1. Un registre hors de ces plages :
  exception 2. Le Pi pose ses questions environ 4 fois par seconde ; une réponse de lecture fait
  65 octets (≈ 6 ms).

## Lecture : registres 0 à 29 (fonction 4)

| Registre | Contenu |
|---|---|
| 0 | signature **0x5350** (« SP ») : c'est bien la carte du spray |
| 1 | version de la table : **1** |
| 2 | compteur de démarrages (+1 à chaque démarrage, gardé dans la mémoire flash) |
| 3 | **état** (bits, ci-dessous) |
| 4 | **erreurs** (bits, ci-dessous) |
| 5 | angle du bras, en dixièmes de degré (0 = rangé, 1100 = 110°) |
| 6 | numéro du dernier ordre reçu (copie du registre 104) |
| 7 | suite de ce dernier ordre : 0 aucun, 1 en cours, 2 fait, 3 refusé, 4 échoué (voir les erreurs) |
| 8 | raison du refus (ci-dessous), 0 sinon |
| 9 | temps depuis le dernier message du Pi (n'importe quelle écriture), en ms, 65 535 au plus |
| 10 et 11 | mesure brute de la balance 1 (nombre signé de 32 bits, le mot fort d'abord) |
| 12 et 13 | mesure brute de la balance 2 |
| 14 et 15 | mesure brute de la balance 3 |
| 16 et 17 | mesure brute de la balance 4 |
| 18 à 21 | poids des flacons 1 à 4, en **dixièmes de gramme** (signé ; 0 si la balance est muette) |
| 22 | dernière dose : emplacement (1 à 4 ; 0 = aucune dose depuis le démarrage) |
| 23 | dernière dose : poids demandé, en dixièmes de gramme |
| 24 | dernière dose : poids perdu par le flacon, en dixièmes de gramme (signé) |
| 25 | dernière dose : durée du pompage, en ms |
| 26 | dernière dose : résultat : 0 aucune, 1 en cours, 2 atteinte, 3 temps maximum dépassé, 4 interrompue (arrêt immédiat, « ranger », silence du Pi), 5 refusée |
| 27 | numéro de la dernière dose finie (+1 à la fin de chaque dose, chasse comprise) |
| 28 | vitesse des agitateurs en ce moment, en % |
| 29 | questions pour cette carte arrivées abîmées, depuis son démarrage |

**État (registre 3)**

| Bit | Valeur | Vrai quand |
|---|---|---|
| 0 | 1 | le capteur `bras_spray_range` voit le bras (GPIO à 0, logique inversée par le PC817) |
| 1 | 2 | le bras est **arrêté à l'angle** demandé par « sortir » |
| 2 | 4 | le bras bouge |
| 3 | 8 | la prise d'origine du bras est faite depuis le démarrage |
| 4 | 16 | un spray est en cours (de l'ouverture de l'air de la buse à sa fermeture) |
| 5 | 32 | un nettoyage est en cours |
| 6 | 64 | les agitateurs tournent |
| 7 | 128 | programme fabriqué avec des réglages d'EXEMPLE |
| 8 | 256 | la carte s'est arrêtée seule : le Pi s'est tu plus de `silence_max_s` |
| 9 | 512 | arrêt immédiat reçu (jusqu'à l'ordre suivant) |

**Erreurs (registre 4)**

| Bit | Valeur | Erreur | Effacée par |
|---|---|---|---|
| 0 à 3 | 1, 2, 4, 8 | balance 1, 2, 3 ou 4 muette (HX711 sans mesure) | elle-même (en direct) |
| 4 à 7 | 16, 32, 64, 128 | balance 1, 2, 3 ou 4 instable (mesures qui sautent) | elle-même (en direct) |
| 8 | 256 | bras pas vu rangé dans le temps maximum (« ranger », origine) | « effacer », ou capteur revu |
| 9 | 512 | bras pas arrivé à son angle dans le temps maximum | « effacer » |
| 10 | 1024 | le capteur a perdu le bras **sans ordre** (bras poussé ?) | « effacer », ou origine |
| 11 | 2048 | le pilote TMC2209 du bras ne répond pas (UART) | « effacer » |

**Raisons de refus (registre 8)** : 1 ordre inconnu ; 2 paramètre hors des limites ; 3 prise d'origine
pas faite ; 4 pas de battement récent du Pi ; 5 la carte fait déjà un geste ; 6 balance du flacon muette
ou instable ; 7 bras pas sorti ; 8 erreur du bras pas effacée.

## Écriture : registres 100 à 104 (fonction 16)

| Registre | Contenu |
|---|---|
| 100 | **battement** : le Pi y écrit un nombre qui change |
| 101 | code de l'ordre |
| 102 | paramètre 1 |
| 103 | paramètre 2 |
| 104 | **numéro de l'ordre** : la carte exécute l'ordre quand ce numéro change |

Un ordre s'écrit **en une seule trame**, registres 101 à 104 (le numéro en dernier). La carte ne
l'exécute qu'une fois, au moment où il arrive : jamais un ordre resté dans les registres après un
redémarrage. Le Pi prend comme numéro celui du registre 6, plus 1.

| Code | Ordre | Paramètre 1 | Paramètre 2 | Refusé si |
|---|---|---|---|---|
| 1 | prise d'origine du bras : vers « rangé » jusqu'au capteur, cet endroit devient 0° | — | — | un spray ou un nettoyage est en cours (5) |
| 2 | sortir à l'angle | angle, en dixièmes de degré (1 à 1100) | — | pas d'origine (3) ; angle hors de 0-110° (2) ; pas de battement depuis `silence_max_s` (4) ; occupée (5) ; erreur du bras (8) |
| 3 | ranger le bras | — | — | jamais (un spray en cours est interrompu : pompe et air arrêtés d'abord) |
| 4 | spray | emplacement (1 à 4) | dose en dixièmes de gramme | paramètres (2) ; occupée (5) ; bras pas sorti (7) ; balance muette ou instable (6) |
| 5 | nettoyer les tubes | — | — | occupée (5) ; bras pas sorti (7) |
| 6 | agitateurs | vitesse en % (0 à 100) | durée en s (0 = arrêt) | vitesse > 100 (2) |
| 7 | arrêt immédiat : pompes, air, petite pompe, agitateurs ; le bras s'arrête où il est | — | — | jamais |
| 8 | effacer les erreurs (bits 8 à 11) et le bit « arrêt seule » | — | — | jamais |

« État » n'est pas un ordre : c'est la lecture des registres 0 à 29.

## Ce que fait la carte

- **Spray** (ordre 4) : air de la buse ouvert (`ev_buse_spray`), attente `air_avant_s` (0,5 s), pompe de
  l'emplacement jusqu'à ce que le flacon ait perdu la dose demandée, au plus `temps_max_pompage_s` (15 s) ;
  puis chasse (`ev_chasse_spray`) pendant `chasse_s` (4,5 s) ; air de la buse fermé `air_apres_s` (1 s)
  après la fin de la chasse. Résultat et numéro de dose (registres 22 à 27) à la fin.
- **Dose pas atteinte** au temps maximum : pompe arrêtée, chasse quand même, résultat 3, puis la carte
  **range le bras elle-même**. Pareil si la balance du flacon devient muette pendant la dose (on ne
  sait plus ce qui part) : le bit de la balance muette (registre 4) dit pourquoi.
- **Poids perdu** (registre 24) : relu à la fin du geste, après la chasse, quand le flacon ne bouge
  plus (la pompe, elle, s'arrête dès que la balance a vu la dose).
- **Nettoyage** (ordre 5) : air de la buse ouvert, `pompe_nettoyage_spray` pendant `nettoyage → pompe_s`
  (5 s), chasse de séchage `sechage_s` (15 s), air fermé 1 s après.
- **Bras** : NEMA 17 sur TMC2209 en UART (1,2 A), lent (`bras → vitesse_deg_s`), butée logicielle 0 à
  110°. Pas arrivé dans `bras → temps_max_s` : il s'arrête, erreur 256 ou 512, suite « échoué ».
  Le capteur perd le bras alors qu'aucun ordre ne le fait bouger : erreur 1024.
- **Le Pi se tait** plus de `liaison → silence_max_s` (2 s) pendant un spray, un nettoyage ou bras pas
  rangé : la carte arrête pompe et air, range le bras, met le bit 256 de l'état. Le Pi bat toutes les
  `liaison → battement_s` (0,5 s) pendant ses gestes.
- **Balances** : chaque HX711 en continu ; poids en grammes avec l'étalonnage de `pi/reglages/pesees.yaml`
  (`balances_spray`), copié à la fabrication. Le Pi garde la mesure brute pour l'étalonnage.
- **Agitateurs** : une seule sortie PWM pour les 4 (`agitateurs_spray`), à la vitesse et pour la durée
  demandées ; arrêtés seuls à la fin de la durée.

Les réglages de la carte (durées, vitesse et temps maximum du bras, silence du Pi, étalonnage des
balances) viennent de `pi/reglages/machine.yaml` (partie `spray`) et de `pesees.yaml` : la tâche 39 bis
les copie dans le programme quand on le fabrique, comme pour les cartes de pesée.

## Le programme de la carte (tâche 39 bis)

La carte est un **ESP32-S3** (exemple des réglages : « ESP32-S3-DevKitC-1 », module N8), avec un
MAX3485 pour le bus, 5 pilotes TMC2209 (le bras en UART, les 4 pompes en pas/direction), 4 HX711,
un PC817 pour le capteur et 4 sorties MOSFET. Programme : **ESP-IDF**, comme `poste_fut_radio/`.

- **Générateur de pas** : une minuterie toutes les `carte → periode_pas_us` (50 µs), seule sur le
  2ᵉ cœur, avance les 5 moteurs (rampe d'accélération, arrêt juste sur la cible, au plus un pas
  tous les 2 tours). Pour l'origine et « ranger », le bras s'arrête net au tour où le capteur le
  voit, et cet endroit devient 0°. « Ranger » cherche le capteur jusqu'à
  `moteur_bras → depassement_max_deg` sous 0° (10°), pas plus loin ; l'origine (position pas
  encore connue) au plus toute la course et ce dépassement (120°) depuis là où il est. Et jamais
  plus que `bras → temps_max_s`.
- **Bras bloqué** : le moteur n'a pas de codeur. Si tous les pas de « sortir » sont faits mais que
  le capteur voit encore le bras, c'est l'erreur 512 (bras pas arrivé).
- **Pilote du bras** : réglé par son UART au démarrage (courant `bras → courant_a`, micro-pas,
  courant à l'arrêt), relu toutes les `lecture_pilote_ms`. Pas de réponse : erreur 2048 (« sortir »
  refusé ; « ranger » et l'origine restent permis). Pilote redémarré (son 24 V coupé) : il est
  réglé de nouveau et la prise d'origine est à refaire (bit « origine faite » éteint).
- **Capteur** : filtré `filtre_capteur_ms` (20 ms) pour « bras poussé » ; fil coupé = broche tirée
  à 1 = « pas rangé » (le Pi attend : c'est le côté sûr).
- **Balances** : HX711 à 80 mesures par seconde (broche RATE au 3,3 V), poids = moyenne des
  `moyenne_de` (8) dernières ; instable si elles s'écartent de plus de `instable_g` (3 g).
- **Au démarrage** : tout éteint, compteur de démarrages +1 (mémoire flash), pilotes alimentés
  après le réglage du bras. Le Pi a `silence_max_s` pour parler : sinon, si le bras n'est pas
  rangé, la carte le range seule (sans origine, elle cherche le capteur, au plus le temps maximum).
- **Fenêtre USB** (essais) : une ligne d'état par seconde (bras, capteur, pilote, 4 balances,
  dernier ordre, dernière dose, silence du Pi).

### Les chiffres

Tous dans [`pi/reglages/machine.yaml`](../pi/reglages/machine.yaml), partie `spray` (bras, dose,
nettoyage, liaison → silence_max_s, et `spray → carte` : broches, moteur du bras, pompes,
balances, PWM des agitateurs), plus l'étalonnage des balances (`pesees.yaml → balances_spray`) et
l'adresse et la vitesse du bus (`docs/entrees-sorties.yaml` : `carte_spray`, `rs485_spray`). Ils
sont **vérifiés** au démarrage du Pi et quand on fabrique le programme (broche prise deux fois,
broche réservée de l'ESP32-S3, micro-pas impossibles, courant que le pilote ne peut pas donner,
vitesse plus grande que le générateur de pas, bras qui n'a pas le temps de faire sa course...), puis
copiés dans le programme (`reglages_spray.h`). Les changer = refabriquer et recharger la carte.

### Les fichiers

| Fichier | Rôle |
|---|---|
| `commun/spray.c` | La carte sans le matériel : ordres, refus, gestes, bras, silence du Pi, registres (essayé sur PC) |
| `commun/moteur.c` | Le générateur de pas d'un moteur : rampe, cible, arrêt sur le capteur (essayé sur PC) |
| `commun/balance.c` | Une balance : moyenne, poids, muette, instable (essayé sur PC) |
| `commun/tmc2209.c` | Les trames du pilote TMC2209 du bras (essayé sur PC) |
| `carte/main/main.c` | L'ESP32-S3 : broches, minuterie des pas, HX711, UART du bus et du pilote, PWM, fenêtre USB |
| `tests/` | Les essais sur PC : faux moteurs et faux bras, faux capteur, faux HX711, questions Modbus |
| `reglages.cmake` | Copie les réglages du Pi dans le programme (`vidange.entete_spray`) |
| `essai-materiel.md` | **Procédure d'essai sur le vrai matériel**, pas à pas |

Le HX711 et le Modbus viennent de `pesee/src/` (`hx711.c`, `modbus.c`, qui sait maintenant aussi
l'écriture de registres, fonction 16) ; le faux HX711 de `poste_fut_radio/tests/`.

### Fabriquer le programme

GitHub Actions le fabrique quand le spray change (ligne `spray` des Tests) :
`carte_spray-complet.bin`, à charger à l'adresse 0x0 (`essai-materiel.md`, étape 1).

Pour le fabriquer soi-même (Linux, avec Docker) :

```bash
docker run --rm -v "$PWD":/projet -w /projet espressif/idf:v5.5.4 bash -c 'pip install -q "pydantic>=2.5,<3" "PyYAML>=6.0,<7" && idf.py -C spray/carte build'
```

Essais sur PC (sans la carte) :

```bash
cmake -S spray/tests -B spray/build-essais && cmake --build spray/build-essais
```

```bash
ctest --test-dir spray/build-essais --output-on-failure
```

### Choix faits

- **ESP32-S3** plutôt que l'ESP32 des cartes FluidNC : il faut 25 broches (5 moteurs, 4 HX711 avec
  chacun sa SCK, bus, UART du pilote, capteur, 4 sorties) ; l'ESP32 n'en a pas assez de libres.
  L'ESP32-S3 a aussi un USB à lui (mises à jour par le Pi, numéro de série).
- **Une SCK par HX711** : 4 HX711 sur une seule SCK seraient lus en même temps, mais ils ne sont
  jamais prêts au même instant.
- **Sens des pompes câblé en dur** (`pompes_sens: null`) : une pompe péristaltique ne tourne que
  dans un sens ; une broche gagnée. Une broche peut être donnée si le câblage le demande.
- **Un seul EN pour les 5 pilotes** : ils sont alimentés dès le démarrage (le bras tient sa place,
  courant réduit à l'arrêt).
- **Générateur de pas maison** plutôt qu'une bibliothèque : une centaine de lignes en nombres
  entiers, essayées sur PC, les mêmes pour le bras et les pompes.

## Ce que fait le Pi (`pi/vidange/spray/`)

- Il lit la carte en fond (4 fois par seconde), bat pendant ses gestes, lance les agitateurs 30 s avant
  chaque dose puis 1 min toutes les 15 min, et envoie l'arrêt immédiat si la porte de la boîte s'ouvre
  pendant un spray.
- **Règle d'or** : tant que la carte n'a pas redit « bras rangé » (bit 0 de l'état, bras arrêté),
  `bras_spray_sorti` est vrai, **même si la carte se tait** : le chariot de remplissage ne bouge ni en
  hauteur, ni ses barres, ni en y ; seule la rotation du seau est permise.
- Il ne demande « sortir » qu'avec la règle 6 du Remplissage (plateau ≤ min(0,50 ; 0,68 − h), barres à
  plus de 0,50 d'entraxe), la porte fermée et pas de purge.
- Il choisit l'emplacement et la dose, vérifie la réserve du flacon, classe le résultat (faite, trop
  forte, incomplète, interrompue) et le note dans le registre du seau.

## Essais

Outil `vidange-spray` (sur le Pi, programme principal arrêté) : `etat`, `origine`, `sortir`, `ranger`,
`dose`, `nettoyer`, `agiter`, `arret`, `effacer`, `zero`, `etalonner` ; `--faux` pour essayer avec la
fausse carte. Procédure pas à pas : [`pi/systeme/essai-spray.md`](../pi/systeme/essai-spray.md).
