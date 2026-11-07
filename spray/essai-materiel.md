# Essai de la carte ESP32 n° 5 du spray sur le vrai matériel (tâche 39 bis)

**Testé sur le vrai matériel : non.** Les essais automatiques (GitHub Actions) n'utilisent que des
**faux** : faux moteurs, faux bras, faux capteur, faux HX711, questions Modbus écrites à la main. Le
programme est fabriqué par GitHub, mais n'a jamais tourné sur une vraie carte.

But : vérifier **sur la table**, carte par carte, que le programme démarre tout éteint, voit le
capteur du bras, règle le pilote du bras, lit les 4 balances, fait tourner le bras et les pompes,
allume les électrovannes et les agitateurs, et répond au Pi. Ensuite, l'essai du spray monté dans la
machine (angles au-dessus des seaux, doses, étalonnage) est `pi/systeme/essai-spray.md`.

Compter environ 3 h la première fois. Le spray ne protège personne : pendant l'essai, garder les
doigts loin du bras quand il est alimenté, et couper le 24 V pour tout branchement.

## Ce qu'il faut

- La carte **ESP32-S3** (exemple des réglages : « ESP32-S3-DevKitC-1 », module N8, 3,3 V).
  **La marquer** « SPRAY » au feutre.
- Un émetteur-récepteur RS485 **3,3 V** (MAX3485, ou petite carte « TTL vers RS485 3,3 V » avec une
  broche DE/RE ; pas un MAX485 en 5 V), l'adaptateur USB-RS485 du spray (`rs485_spray`), un bout
  de câble à paire torsadée, 2 résistances de 120 Ω.
- 5 cartes de pilote **TMC2209** (bras + 4 pompes), le moteur du bras (17HS4401) et les 4 moteurs des
  pompes, l'alimentation 24 V de la boîte.
- Le capteur inductif du bras, le **PC817**, une résistance de **2,2 kΩ ½ W** et une de **10 kΩ**.
- Les 4 cellules de 1 kg avec leur **HX711** (broche RATE au 3,3 V : 80 mesures par seconde).
- Les 4 sorties MOSFET (électrovanne de la buse, électrovanne de la chasse, agitateurs, petite pompe
  du nettoyage), chacune avec **10 kΩ entre sa grille (la broche de l'ESP32) et le 0 V**.
- Une résistance de **1 kΩ** (UART du pilote du bras), 10 kΩ pour DE/RE du MAX3485, 10 kΩ pour EN
  des pilotes.
- Un multimètre, un rapporteur (pour l'angle du bras), une masse connue d'environ 200 g, un PC avec
  **Chrome** ou **Edge**, un câble USB-C de données.

## 1. Récupérer le programme

1. Sur GitHub, ouvrir la PR de la tâche 39 bis (ou la plus récente qui touche `spray/`), onglet
   **Checks** (Vérifications), puis la ligne **Tests**.
2. En bas de la page, partie **Artifacts**, cliquer sur **spray** : un zip se télécharge. Le
   décompresser : il contient `carte_spray-complet.bin`.

Si la ligne **spray** dit « sauté » (rien du spray n'a changé dans cette PR), prendre le zip d'une
PR plus ancienne qui touche `spray/`.

## 2. Brancher (24 V coupé, USB débranché)

Les numéros sont ceux de `pi/reglages/machine.yaml`, `spray → carte → broches` (EXEMPLES). S'ils ne
vont pas avec la carte achetée ou avec le plan de câblage (Implantation), le dire dans la PR : on
change le fichier, GitHub refait le programme. **Masse commune** : le 0 V du 24 V, le GND de
l'ESP32-S3, des pilotes, des HX711 et du MAX3485 sont reliés.

| Quoi | ESP32-S3 |
|---|---|
| Alimentation de la carte | 5 V du convertisseur 24 V → 5 V sur la broche 5V, 0 V sur GND |
| MAX3485 : VCC / GND | 3V3 / GND (et le 0 V du câble `c_spray`) |
| MAX3485 : DI / RO | GPIO 17 (`rs485_tx`) / GPIO 18 (`rs485_rx`) |
| MAX3485 : DE et /RE reliées | GPIO 16 (`rs485_sens`), et 10 kΩ vers GND |
| MAX3485 : A et B | A et B du câble vers l'adaptateur USB-RS485 du Pi (120 Ω aux 2 bouts) |
| 5 pilotes TMC2209 : VIO / GND | 3V3 / GND ; VM au 24 V |
| 5 pilotes : EN, reliés ensemble | GPIO 21 (`activer_moteurs`), et 10 kΩ vers 3V3 (moteurs coupés pendant le démarrage) |
| Pilote du **bras** : STEP / DIR | GPIO 13 (`bras_pas`) / GPIO 14 (`bras_sens`) |
| Pilote du bras : PDN_UART | GPIO 12 (`pilote_bras_rx`) **direct**, et GPIO 11 (`pilote_bras_tx`) **par 1 kΩ** |
| Pilote du bras : MS1 et MS2 | à GND (adresse 0) |
| Pilotes des **pompes 1 à 4** : STEP | GPIO 4, 5, 6, 7 (`pompes_pas`) |
| Pilotes des pompes : DIR | au 3V3 (sens câblé en dur ; à GND si la pompe tourne à l'envers) |
| Pilotes des pompes : MS1 et MS2 | à GND (1/8 de pas) |
| HX711 n° 1 à 4 : DT | GPIO 1, 2, 9, 10 (`hx711_dt`) |
| HX711 n° 1 à 4 : SCK | GPIO 38, 39, 40, 41 (`hx711_sck`) |
| HX711 : VCC / GND / RATE | 3V3 / GND / 3V3 |
| PC817 côté 24 V | sortie du capteur → 2,2 kΩ ½ W → anode (1) ; cathode (2) → 0 V |
| PC817 côté carte | collecteur (4) → GPIO 42 (`bras_spray_range`) et 10 kΩ vers 3V3 ; émetteur (3) → GND |
| MOSFET de l'électrovanne de la buse | GPIO 47 (`ev_buse_spray`) |
| MOSFET de l'électrovanne de la chasse | GPIO 8 (`ev_chasse_spray`) |
| MOSFET des agitateurs (PWM) | GPIO 15 (`agitateurs_spray`) |
| MOSFET de la petite pompe du nettoyage | GPIO 48 (`pompe_nettoyage_spray`) |

Notes :

- Sur certaines cartes TMC2209, la broche PDN_UART n'est reliée qu'après un **pont à souder** (voir
  la notice de la carte achetée). Le dire dans la PR si c'est le cas.
- Le courant des **pompes** se règle sur chaque pilote, avec son petit potentiomètre (tension VREF,
  formule sur la notice de la carte), d'après le courant du moteur de la pompe. Celui du **bras**
  est réglé par le programme (1,2 A, `bras → courant_a`) : son potentiomètre ne sert pas.
- Sur la carte DevKitC-1, la broche 48 est aussi reliée à la petite LED de couleur de la carte :
  elle peut s'allumer avec la petite pompe. Ce n'est pas grave.

**À noter dans la PR** : la carte achetée (nom exact), les broches changées s'il y en a, le
modèle des cartes TMC2209.

## 3. Charger le programme (flasher)

1. Tenir appuyé le bouton **BOOT** de la carte, brancher le câble USB au PC sur le port marqué
   **USB** (pas « UART »), lâcher le bouton.
2. Dans Chrome, ouvrir <https://espressif.github.io/esptool-js/>. Cliquer **Connect**, choisir la
   carte (souvent « USB JTAG/serial debug unit »). La page dit « Chip is ESP32-S3 ».
3. Dans **Flash Address**, écrire `0x0`. Choisir `carte_spray-complet.bin`.
4. Cliquer **Program**. Attendre « Leaving... » (moins d'une minute).
5. Cliquer **Disconnect**, débrancher l'USB, le rebrancher (sans BOOT) : le programme démarre.

Autre façon, depuis le Pi (carte branchée en USB sur le Pi, bouton BOOT comme au point 1) :

```
sudo -u vidange /opt/vidange-auto/pi/.venv/bin/python -m esptool --chip esp32s3 write-flash 0x0 carte_spray-complet.bin
```

## 4. La fenêtre texte de la carte

1. Dans Chrome, ouvrir <https://googlechromelabs.github.io/serial-terminal/>, cliquer **Connect**,
   choisir la carte. Si rien ne s'écrit, appuyer une fois sur **RESET** (ou RST).
2. Au démarrage, attendu :
   « Carte du spray « carte_spray », adresse 1 sur le bus rs485_spray, 115200 bauds. »,
   « Version ... Réglages d'EXEMPLE ... », « Démarrage n° 1. »
3. Puis une ligne par seconde, par exemple :
   `bras 0,0° rangé, origine à faire | capteur voit le bras | pilote ok | 1: 412,3 g (brut ...) 2: ... | ordre n° 0 aucun | Pi : jamais entendu`
4. Appuyer sur **RESET** : « Démarrage n° 2. » (le compteur est gardé, le Pi s'en sert pour voir
   que la carte a redémarré).

**À noter dans la PR** : la version lue, et si le compteur monte bien.

## 5. Tout est éteint au démarrage

1. 24 V branché, multimètre sur l'électrovanne de la buse (ou écouter : elle claque quand elle
   s'ouvre).
2. Appuyer sur **RESET** plusieurs fois : **aucune** électrovanne ne claque, la petite pompe et les
   agitateurs ne bougent pas, aucun moteur ne bouge. (C'est le rôle des 10 kΩ des grilles.)
3. Pendant RESET tenu appuyé, l'arbre du moteur du bras tourne librement à la main (pilotes coupés) ;
   relâché, il se tient (pilotes alimentés, courant réduit à l'arrêt).

## 6. Le capteur du bras (PC817)

1. Bras contre le capteur (rangé) : la ligne dit « capteur voit le bras », et « rangé ».
2. Écarter le bras à la main : « ne voit rien », « pas rangé ». Le remettre : « voit le bras ».
3. Débrancher le fil du capteur : « ne voit rien » (fil coupé = pas rangé : c'est le côté sûr).
4. Avec le multimètre sur GPIO 42 : bras rangé ≈ 0 V, bras écarté ≈ 3,3 V (logique inversée par le
   PC817).

## 7. Le pilote du bras

1. La ligne dit « pilote ok ». Sinon : vérifier VIO, la 1 kΩ, le pont à souder de PDN_UART, MS1 et
   MS2 à GND.
2. Débrancher le fil PDN_UART : en 1 à 2 s, « pilote MUET » et « ERREURS 0x0800 ». Le rebrancher :
   « pilote ok » revient seul (les erreurs restent jusqu'à « effacer », étape 9).
3. Couper le 24 V (l'USB reste branché) : « pilote MUET ». Le remettre : en 1 à 2 s, « pilote ok » et
   « origine à faire » (le pilote a perdu ses réglages et peut-être des pas ; la carte l'a réglé de
   nouveau).

## 8. Les 4 balances

1. Chaque emplacement montre un poids (faux tant qu'il n'est pas étalonné) et un brut.
2. Appuyer sur une cellule : le brut change, puis revient.
3. Secouer un flacon posé : « INSTABLE » pendant le mouvement, puis plus rien.
4. Débrancher le fil DT d'un HX711 : en moins d'une seconde, « n: MUETTE ». Le rebrancher : le poids
   revient.

## 9. Avec le Pi : la carte répond

Brancher A et B à l'adaptateur USB-RS485 du spray sur le Pi, puis suivre
`pi/systeme/essai-spray.md`, **étapes 1 et 2** (reconnaître l'adaptateur, la carte répond). Dans la
fenêtre de la carte, « Pi : il y a ... ms » apparaît dès qu'un ordre arrive ; le compteur
« questions abîmées » de `etat` reste à 0.

Puis, sur le Pi (toujours `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-spray ...`) :

1. `effacer` : « Fait. », les ERREURS disparaissent de la fenêtre.

## 10. Le bras : origine, sortir, ranger

**Bras libre de bouger sur la table** (rien dans son chemin sur 110°).

1. Écarter le bras d'environ 30° à la main. Lancer `origine`. Attendu : il tourne lentement vers le
   capteur, s'arrête dessus, « Fait. ». S'il part dans **l'autre sens** : `arret` tout de suite, puis
   passer `spray → carte → moteur_bras → sens_inverse` à `true` (refabriquer, recharger).
2. Lancer `sortir 90 --etabli`. Mesurer l'angle au rapporteur : **90°**, à 1° près. S'il fait 45° ou
   180° (au rapporteur, ou il cogne) : `arret`, les micro-pas ou le rapport ne vont pas
   (`moteur_bras → micro_pas`, `rapport`) : le dire dans la PR.
3. Attendre sans rien faire : **au bout d'environ 2 s**, le bras se range seul (l'outil ne bat plus).
   La fenêtre dit « ARRÊT SEULE (le Pi s'est tu) ». Puis `effacer`.
4. Lancer `sortir 110 --etabli` : il s'arrête à 110°, pas plus (butée du programme). Il se range seul
   2 s après. `sortir 111 --etabli` : « ordre refusé par la carte (paramètre hors des limites) ».
5. **Bras bloqué** : tenir le bras à la main contre le capteur et lancer `sortir 64.3 --etabli` : le
   moteur saute des pas, puis « ÉCHOUÉ » et « bras pas arrivé à son angle » (fenêtre de la carte :
   « ERREURS 0x0200 »). Lâcher, `effacer`, `origine`.
6. **Capteur absent** (seulement sur la table, bras pas encore monté sur sa poutre : il va passer
   « rangé ») : débrancher le fil du capteur, lancer `origine` : le bras tourne vers « rangé », passe
   le capteur et s'arrête après environ 120° (toute la course et 10°), « ÉCHOUÉ » et « bras pas
   rangé dans le temps maximum » (fenêtre de la carte : « ERREURS 0x0100 »). Rebrancher, `effacer`,
   `origine`.

**À noter dans la PR** : le sens, l'angle mesuré pour 90°, le temps pour sortir à 90° (environ 1,5 s
attendues), tout bruit ou à-coup du moteur.

## 11. Les pompes, les électrovannes, la petite pompe

Une pompe sans tube clipsé suffit pour voir qu'elle tourne. Pas de liquide pour cette étape.

1. Lancer `dose 1 5 --angle 64.3 --etabli`. Attendu dans l'ordre : le bras sort ; l'électrovanne de
   la buse claque ; 0,5 s après, la **pompe 1** tourne ; comme le flacon ne perd pas de poids, elle
   s'arrête au bout de **15 s** ; la chasse claque pendant 4,5 s ; la buse se ferme 1 s après ; puis
   le bras se range seul ; la ligne dit « TEMPS MAX ».
2. Pompe qui tourne **à l'envers** (elle aspire au lieu d'envoyer) : couper le 24 V et mettre le DIR
   de son pilote à GND (au lieu du 3V3).
3. Refaire avec les emplacements 2, 3 et 4 : seule la pompe de cet emplacement tourne.
4. Pendant une dose, lancer `arret` dans une 2ᵉ fenêtre : pompe, buse et chasse s'arrêtent tout de
   suite, le bras reste où il est, la fenêtre de la carte dit « ARRÊT IMMÉDIAT ». La 1re fenêtre finit par dire
   « ÉCHEC : ordre pas fini » : c'est normal. 2 s après, le bras se range seul.
5. `nettoyer --angle 64.3 --etabli` : buse ouverte, petite pompe 5 s, chasse 15 s, buse fermée 1 s
   après, bras rangé seul ensuite.
6. `agiter 60 10` : les agitateurs tournent 10 s, puis s'arrêtent seuls. `agiter 100 5` : plus vite.

## 12. Une vraie dose, avec de l'eau

Suivre `pi/systeme/essai-spray.md`, **étape 6** (étalonner les 4 balances, refabriquer, recharger)
puis **étape 7** (une dose d'eau). C'est là que se mesure le débit des pompes.

## À la fin

- Écrire dans la PR (ou dire à Claude) : la carte achetée, les broches changées, ce qui a marché du
  premier coup ou pas, les temps mesurés, l'angle mesuré pour 90°, le sens des moteurs, tout ce qui a
  surpris.
- Quand broches, sens et vitesses sont justes, et après `pi/systeme/essai-spray.md` : passer
  `exemple: false` dans `machine.yaml → spray`.
