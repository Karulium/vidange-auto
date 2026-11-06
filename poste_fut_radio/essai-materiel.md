# Essai des 2 cartes ESP32-C3 du poste du fût sur le vrai matériel (tâche 17 ter)

**Testé sur le vrai matériel : non.** Les essais automatiques (GitHub Actions) n'utilisent que des
**faux** : un faux HX711, de fausses trames radio, des questions Modbus écrites à la main. Les deux
programmes sont fabriqués par GitHub, mais n'ont jamais tourné sur une vraie carte.

But : vérifier sur la table, avec les vraies cartes, que le plateau se réveille sur l'aimant,
envoie 2 trames par seconde, que la boîte du poste les reçoit et répond au Pi, que la radio coupée
se voit (« radio muette »), que le plateau se rendort 30 s après l'ouverture du reed, que la
tension de l'accu est juste, et que le bit « 5 V de la recharge présent » reste vrai accu plein.

Compter environ 2 h la première fois (sans attendre que l'accu se remplisse : étape 10). Rien ne
bouge : l'essai se fait sur la table, puis au poste. Ensuite, l'essai du poste complet (étalonnage,
« Prêt », alertes) est `pi/systeme/essai-poste-fut.md`.

La radio ne porte que la pesée : elle ne protège jamais personne, et la machine ne s'arrête jamais
quand elle se tait.

## Ce qu'il faut

- Les 2 cartes **ESP32-C3** (exemple des réglages : « ESP32-C3 SuperMini »). **Marquer** au feutre
  « PLATEAU » et « BOÎTE ».
- Pour le plateau : la carte HX711 et ses capteurs (ou un seul capteur pour commencer), le **reed**
  et l'**aimant** de la boîte du poste, l'accu 18650 avec sa carte de charge et sa protection, le
  récepteur de la recharge sans contact et son émetteur, la prise USB-C de secours.
- Résistances : 2 × 220 kΩ et un condensateur de 100 nF (accu) ; 2 × 10 kΩ et 2 × 15 kΩ (les deux
  5 V) ; 100 kΩ (reed, conseillé) ; 10 kΩ (DE/RE de la boîte).
- Pour la boîte : un émetteur-récepteur RS485 **3,3 V** (MAX3485, ou petite carte « TTL vers
  RS485 3,3 V » avec une broche DE/RE ; pas un MAX485 en 5 V), son alimentation 5 V.
- Le bus des pesées et son adaptateur USB-RS485 sur le Pi (`pesee/essai-etabli.md`, étape du bus).
- Un **voltmètre** (multimètre), un chronomètre (le téléphone), du papier d'aluminium.
- 2 câbles USB-C (données, pas seulement charge) et un PC avec **Chrome** ou **Edge**.

## 1. Récupérer les programmes

1. Sur GitHub, ouvrir la PR de la tâche 17 ter (ou la plus récente qui touche `poste_fut_radio/`),
   onglet **Checks** (Vérifications), puis la ligne **Tests**.
2. En bas de la page, partie **Artifacts**, cliquer sur **poste_fut_radio** : un fichier zip se
   télécharge. Le décompresser : il contient `plateau_fut-complet.bin` (pour la carte PLATEAU) et
   `boite_poste_fut-complet.bin` (pour la carte BOÎTE). Ne pas les mélanger.

Les deux fichiers viennent **du même** `pi/reglages/pesees.yaml` : ils ont les mêmes adresses
radio. Toujours charger les deux cartes avec des fichiers du **même** zip.

## 2. Brancher (cartes débranchées de l'USB)

Les numéros sont ceux de `pi/reglages/pesees.yaml` (section `poste_fut_radio`, carte d'exemple).
S'ils ne vont pas avec la carte achetée, le dire dans la PR : on change le fichier, GitHub refait
les programmes.

**Carte PLATEAU**

| Quoi | ESP32-C3 du plateau |
|---|---|
| HX711 : VCC et VDD | 3V3 (jamais le 5 V) |
| HX711 : GND | GND |
| HX711 : DT (DOUT) | GPIO 6 (`hx711_dt`) |
| HX711 : SCK | GPIO 7 (`hx711_sck`) |
| HX711 : RATE | à la masse (10 mesures par seconde ; c'est souvent déjà ainsi sur les petites cartes vertes) |
| Reed | entre GPIO 3 (`reed`) et GND ; une résistance de 100 kΩ entre GPIO 3 et 3V3 (conseillé) |
| Accu (+ après la protection) | 220 kΩ → GPIO 4 (`accu`) → 220 kΩ → GND ; 100 nF entre GPIO 4 et GND |
| 5 V du récepteur de la recharge sans contact | 10 kΩ → GPIO 5 (`recharge_5v`) → 15 kΩ → GND |
| 5 V de la prise USB-C de secours | 10 kΩ → GPIO 10 (`usb_5v`) → 15 kΩ → GND |

Jamais un 5 V directement sur une broche : toujours par son pont (10 kΩ et 15 kΩ donnent 3 V).

**Carte BOÎTE**

| Quoi | ESP32-C3 de la boîte |
|---|---|
| MAX3485 : VCC | 3V3 |
| MAX3485 : GND | GND, et le 0 V du bus des pesées |
| MAX3485 : DI (entrée des données) | GPIO 21 (`rs485_tx`) |
| MAX3485 : RO (sortie des données) | GPIO 20 (`rs485_rx`) |
| MAX3485 : DE et /RE (reliées ensemble) | GPIO 10 (`rs485_sens`), et 10 kΩ entre GPIO 10 et GND (bus en écoute pendant le démarrage) |
| MAX3485 : A et B | A et B du bus des pesées (A avec A, B avec B) |
| Alimentation | 5 V de l'alimentation de la boîte sur la broche 5V, 0 V sur GND |

## 3. Charger les programmes par l'USB (flasher)

Pour chaque carte, l'une après l'autre :

1. Tenir appuyé le bouton **BOOT** de la carte, brancher le câble USB au PC, lâcher le bouton
   (la carte attend un programme). Pour le plateau, c'est obligatoire : endormi, il ne répond
   pas à l'USB.
2. Dans Chrome, ouvrir <https://espressif.github.io/esptool-js/>. Cliquer **Connect**, choisir la
   carte (souvent « USB JTAG/serial debug unit »). La page dit « Chip is ESP32-C3 ».
3. Dans **Flash Address**, écrire `0x0`. Choisir le fichier de **cette** carte
   (`plateau_fut-complet.bin` pour PLATEAU, `boite_poste_fut-complet.bin` pour BOÎTE).
4. Cliquer **Program**. Attendre « Leaving... » (moins d'une minute).
5. Cliquer **Disconnect**, débrancher l'USB, le rebrancher (sans BOOT) : le programme démarre.

Autre façon, depuis le Pi (carte branchée en USB sur le Pi, bouton BOOT comme au point 1) :

```
sudo -u vidange /opt/vidange-auto/pi/.venv/bin/python -m esptool --chip esp32c3 write-flash 0x0 plateau_fut-complet.bin
```

**À noter dans la PR** : chaque carte a-t-elle pris son programme du premier coup ?

## 4. Ouvrir la fenêtre texte d'une carte

1. Dans Chrome, ouvrir <https://googlechromelabs.github.io/serial-terminal/>, cliquer **Connect**,
   choisir la carte.
2. Si rien ne s'écrit, appuyer une fois sur le bouton **RESET** (ou RST) de la carte : elle redit
   qui elle est.

On peut ouvrir les deux fenêtres en même temps (deux onglets), une par carte.

## 5. Appairer l'adresse radio

Il n'y a **rien à recopier** : les deux adresses sont écrites dans `pesees.yaml` (`poste_fut_radio →
radio`, exemple `02:50:46:00:00:01` pour le plateau et `02:50:46:00:00:02` pour la boîte), et chaque
carte prend la sienne. Il faut seulement vérifier que les deux cartes ont les **mêmes** réglages.

1. Fenêtre de la BOÎTE, au démarrage : « Adresse radio de la boîte 02:50:46:00:00:02 ; n'écoute que
   le plateau 02:50:46:00:00:01 ; canal 1. »
2. Fenêtre du PLATEAU (tenir l'aimant contre le reed pour qu'il reste éveillé), au démarrage :
   « Adresse radio du plateau 02:50:46:00:00:01, envoie à la boîte 02:50:46:00:00:02, canal 1, 8 dBm. »
3. Les deux adresses et le canal doivent être **les mêmes** dans les deux fenêtres. Sinon, les deux
   fichiers ne viennent pas du même zip : recharger les deux cartes (étape 3) avec le même zip.
4. Si la fenêtre de la boîte dit « trames d'une AUTRE adresse radio : ... » : le plateau parle, mais
   avec une autre adresse (programme d'un autre zip). Même remède.

**À noter dans la PR** : les deux lignes lues (adresses et canal), et la version (même commit sur
les deux cartes).

## 6. Plateau posé : réveil, trames, lecture par le Pi

1. Plateau **sans aimant** depuis plus de 30 s (il dort). Fenêtre de la BOÎTE : une ligne par
   seconde « RADIO MUETTE (rien du plateau depuis 2000 ms) | ... » ; son voyant **clignote**.
2. Approcher l'**aimant** du reed (ou pousser le plateau au fond du poste) : en 1 s environ, le
   plateau se réveille. Fenêtre de la BOÎTE : la ligne devient
   `brut 123456 | 2 trames/s | HX711 ok | reed fermé | accu 3950 mV 78 % | recharge 5 V oui | USB-C non | signal -55 dBm | 0 perdues | ...`
   et son voyant reste **allumé**. Le voyant du plateau fait **un éclair** toutes les 0,5 s.
3. Fenêtre du PLATEAU (ouverte en USB, plateau éveillé) :
   `brut 123456 | 10 mesures/s | HX711 ok | reed fermé (au poste) | ... | trames 2, reçues par la boîte 2, ratées 0`.
4. **Appuyer** sur le plateau (ou sur le capteur) : le « brut » change dans les deux fenêtres, puis
   revient sans appui. Débrancher le fil DT du HX711 : en moins d'une seconde, « HX711 MUET » ;
   le rebrancher : « HX711 ok ».
5. **Lecture par le Pi** : la boîte branchée sur le bus des pesées. Sur le Pi :

   ```
   sudo systemctl stop vidange
   ```

   ```
   sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-pesees lire
   ```

   La ligne de `pesee_fut` dit **2 mesures par seconde** (faites par la boîte), le même brut que la
   fenêtre de la boîte, 0 question sans réponse, 0 question abîmée. Ctrl+C. Puis :

   ```
   sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-pesee lire
   ```

   Une ligne par seconde avec le poids (faux tant que la pesée n'est pas étalonnée :
   `pi/systeme/essai-poste-fut.md`, étape 5), l'accu, la recharge, le signal radio, les trames
   perdues. Ctrl+C. Relancer le programme : `sudo systemctl start vidange`.

**À noter dans la PR** : mesures/s du plateau (10 attendu), trames/s de la boîte (2), le signal
(dBm) à 1 m, les trames perdues au bout de 5 min (elles ne doivent presque pas monter), les
questions abîmées (0 attendu).

## 7. Radio coupée : « radio muette »

1. Plateau éveillé (aimant), les deux fenêtres ouvertes, ou `vidange-pesee lire` sur le Pi.
2. **Couper la radio** : envelopper complètement la carte du plateau (ou toute la boîte du plateau)
   dans **deux couches de papier d'aluminium**, sans toucher ses broches ; ou, plus simple,
   débrancher l'accu du plateau (l'aimant reste en place).
3. Au bout de **2 s environ** : fenêtre de la BOÎTE « RADIO MUETTE », son voyant clignote ;
   `vidange-pesee lire` dit « pesée absente : radio du plateau muette ». La boîte **répond toujours**
   au Pi (pas de « ne répond pas »).
4. Enlever l'aluminium (ou rebrancher l'accu) : en 1 à 2 s, les trames reviennent seules, sans
   rien redémarrer.

**À noter dans la PR** : le temps entre la coupure et « RADIO MUETTE » (2 à 3 s attendus).
Si l'aluminium ne suffit pas à couper (les trames passent encore), le dire : c'est bon signe pour
la portée, et l'essai se fait en débranchant l'accu.

## 8. Reed ouvert : mise en sommeil après 30 s

1. Plateau éveillé, sa fenêtre ouverte (USB), aimant contre le reed.
2. **Retirer l'aimant** (ou sortir le plateau du poste) et lancer le chronomètre. La fenêtre du
   PLATEAU dit « reed ouvert | sommeil dans 29 s », puis 28, 27... Les trames continuent (la boîte
   montre « reed ouvert »).
3. À **30 s** : « Reed ouvert depuis 30 s : la carte s'endort ». La fenêtre se coupe (normal : la
   carte endormie n'a plus d'USB). 2 s plus tard, la BOÎTE dit « RADIO MUETTE ».
4. Remettre l'aimant avant 30 s, une autre fois : le compte s'arrête (pas de sommeil) ; le
   retirer de nouveau : il repart de 30.
5. Plateau endormi, remettre l'aimant : il se réveille en 1 s environ (la boîte reçoit de nouveau).
   Rouvrir sa fenêtre : « Démarrage : réveil par le reed (aimant du poste). »
6. Si un multimètre a un calibre mA : en série avec l'accu, le plateau endormi doit prendre
   **moins de 0,1 mA** ; éveillé, environ 40 à 90 mA.

**À noter dans la PR** : le temps mesuré au chronomètre (30 s attendues) ; le courant endormi et
éveillé, si mesuré ; la boîte a-t-elle compté des « perdues » au réveil ? (0 attendu.)

## 9. Mesure de la tension de l'accu

1. Plateau éveillé (aimant), sur son **accu seul** : ni câble USB du PC, ni USB-C de secours, ni
   recharge sans contact (sinon la tension mesurée n'est pas celle de l'accu au repos). On lit donc
   la tension dans la fenêtre de la **BOÎTE**.
2. Mesurer au **voltmètre** la tension de l'accu, entre son + (après la protection) et son −.
   Exemple : 3,912 V.
3. Lire « accu ... mV » dans la fenêtre de la BOÎTE (ou `vidange-pesee lire`). Exemple : 3 880 mV.
4. Écart de plus de 30 mV : corriger le pont. Nouveau `rapport_pont_accu` = ancien × voltmètre ÷ lu.
   Exemple : 2,0 × 3 912 ÷ 3 880 = **2,017**. L'écrire dans la PR (on le met dans `pesees.yaml`,
   GitHub refait le programme, recharger le PLATEAU).
5. Le % doit suivre la courbe : vers 3,9 V, environ 72 %.

**À noter dans la PR** : la tension au voltmètre, celle lue, le nouveau rapport si besoin.

## 10. Bit « recharge présent » avec l'accu plein

Le bit 1 (valeur 2) du registre 8 veut dire « **5 V de la recharge sans contact présent** », pas
« en charge ». Il doit rester vrai quand l'accu est plein.

1. Plateau au poste (aimant), émetteur de la recharge sans contact **branché** et face au
   récepteur. Fenêtre de la BOÎTE : « recharge 5 V oui ».
2. Laisser charger jusqu'à **accu plein** (voyant « plein » de la carte de charge, ou plus de
   4,15 V au voltmètre ; jusqu'à 6 h depuis un accu vide : on peut faire cette étape le
   lendemain, ou commencer avec un accu presque plein).
3. Accu plein : la fenêtre de la BOÎTE dit **toujours « recharge 5 V oui »**, et environ 100 %.
   `vidange-pesee lire` sur le Pi dit « recharge 5 V » (pas « PAS DE 5 V DE RECHARGE »).
4. Débrancher l'émetteur : en 1 s, « recharge 5 V non ». Le rebrancher : « oui ».
5. Brancher un chargeur sur la **prise USB-C de secours** : « USB-C oui » ; le débrancher : « non ».

**À noter dans la PR** : « recharge 5 V » accu plein (oui attendu), et l'USB-C.

## Si quelque chose ne va pas

- **Esptool ne trouve pas la carte** : autre câble USB (certains ne font que charger), refaire le
  bouton BOOT (tenir, brancher, lâcher).
- **Fenêtre texte vide** : bouton RESET ; plateau : tenir l'aimant contre le reed (endormi, il n'a
  pas d'USB).
- **Le plateau ne se réveille pas** : reed bien entre GPIO 3 et GND ? Aimant assez près (un reed ne
  ferme qu'à quelques mm) ? Accu chargé ?
- **« HX711 MUET » tout le temps** : fils DT et SCK inversés ? HX711 bien en 3,3 V ?
- **« 80 mesures/s » au lieu de 10** : la broche RATE du HX711 est au 3,3 V ; la mettre à la masse
  (ou passer `mesures_par_seconde_hx711` à 80 dans `pesees.yaml`, et le dire dans la PR).
- **Boîte « RADIO MUETTE » alors que le plateau dit « trames 2, reçues par la boîte 0 »** : les
  adresses ou le canal ne vont pas ensemble (étape 5).
- **« ratées » qui monte, signal sous −85 dBm** : rapprocher les cartes, ou monter `puissance_dbm`
  dans `pesees.yaml` (le dire dans la PR) ; certaines petites cartes ESP32-C3 émettent mal à
  pleine puissance : ne pas dépasser 15 sans essayer.
- **« questions abîmées » qui monte** : A et B inversés, 0 V du bus pas relié, terminaison de 120 Ω
  (voir `pesee/essai-etabli.md`).
- **« ATTENTION : la carte a redémarré par son chien de garde »** : le programme s'est figé : le
  noter dans la PR, avec ce qui se passait.
