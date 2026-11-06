# Essai des capteurs de la purge sur le vrai matériel (tâche 38 ter)

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent que de **faux**
capteurs. Le protocole du SPS30 (trames SHDLC), celui du SDP810 (commandes, somme de contrôle) et la sortie
PWM ont été **écrits de mémoire, sans les notices** : **cet essai sert d'abord à les vérifier sur les notices
papier** (fichiers `pi/vidange/trame_sps30.py` et `pi/vidange/trame_sdp810.py`). Durée : environ 2 heures. Un
capteur à la fois.

La sécurité est câblée : cet essai ne la touche pas. Le Pi lit ces capteurs seulement pour savoir quand la
purge est finie. Un capteur qui se tait ne rend jamais la purge « finie » : elle finit en alerte à 20 min.

## Ce qu'il faut avoir

- Les 2 SPS30 (5 V), un convertisseur TTL-RS485 et son adaptateur USB-RS485 (pour celui du dedans).
- Le SDP810-125Pa (3,3 V, I2C) avec ses deux tuyaux, et une petite seringue ou une pipette pour souffler dedans.
- Le module PWM → 0-10 V, et un **voltmètre**.
- Les notices papier des trois pièces.

## Avant de commencer

1. Arrêter le programme principal : `sudo systemctl stop vidange`.
2. Dans les commandes ci-dessous, `vidange-es` veut dire `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-es`.
3. Ouvrir la notice du **SPS30** et noter : la vitesse en bauds de l'interface série (115 200 ?), la commande
   « Start Measurement » (0x00, données 01 03 ?), la commande « Read Measured Values » (0x03 ?), l'ordre des 10
   nombres de la réponse (masse PM1.0, PM2.5, PM4.0, PM10 en premier ?) et la façon de compter la somme de
   contrôle. Comparer avec le début de `pi/vidange/trame_sps30.py`. **Écrire dans la PR tout ce qui diffère.**
4. Ouvrir la notice du **SDP810** et noter : l'adresse I2C (0x25 ?), la commande de mesure continue de la
   pression différentielle (0x3615 ?), la commande d'arrêt (0x3FF9 ?), la forme de la réponse (9 octets : pression,
   température, facteur d'échelle, chacun avec sa somme de contrôle ?). Comparer avec `pi/vidange/trame_sdp810.py`.
5. Ouvrir la notice du **module PWM → 0-10 V** et noter : la fréquence demandée pour le signal PWM et la tension
   obtenue à 100 %. Comparer avec `docs/entrees-sorties.yaml`, signal `consigne_ventilateur`, bloc `pwm:`
   (`periode_us`, `pleine_echelle_v`).

## Étape 1 : le SPS30 du dedans (convertisseur RS485)

1. Brancher le SPS30 (5 V, TX/RX vers le convertisseur TTL-RS485), puis l'adaptateur USB-RS485 au Pi.
2. Lire le numéro de série de l'adaptateur : `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc lister`.
   **Si le numéro est « AUCUN » : s'arrêter et le signaler.**
3. L'écrire dans `docs/entrees-sorties.yaml`, carte `rs485_sps30`, ligne `numero_serie_usb`, entre guillemets.
   Vérifier `vitesse_bauds` (notice).
4. Taper `vidange-es lister particules_dedans`. Attendre 10 à 20 secondes après la mise sous tension (le
   ventilateur du capteur démarre).
5. Attendu : une valeur en µg/m³ (quelques unités à quelques dizaines dans un atelier). Souffler doucement de la
   poussière ou de la fumée d'encens près de l'entrée d'air : la valeur doit **monter** en quelques secondes, puis
   redescendre.
6. Si on lit « ÉCHEC : muet » : vérifier l'alimentation 5 V, TX/RX non croisés (essayer de les croiser), A/B du
   RS485, la vitesse. Si ça ne marche toujours pas : noter la vitesse et la trame de la notice dans la PR.
7. Si le convertisseur renvoie ce qu'on lui écrit (écho), ce n'est pas grave : le programme l'ignore.

## Étape 2 : le SPS30 du dehors (UART3 du Pi, GPIO 8 et 9)

1. Éteindre le Pi. Brancher le SPS30 : TX du capteur → GPIO9 (RX du Pi), RX du capteur → GPIO8 (TX du Pi), 5 V et
   masse. Le Pi parle en 3,3 V, comme le SPS30.
2. Dans `/boot/firmware/config.txt`, ajouter la ligne `dtoverlay=uart3-pi5`, puis redémarrer le Pi.
3. `ls /dev/ttyAMA*` : vérifier que `/dev/ttyAMA3` existe (c'est le fichier écrit dans
   `entrees-sorties.yaml`, signal `particules_dehors`, ligne `fichier`). Sinon, noter la liste et écrire le bon nom.
4. Arrêter le programme (`sudo systemctl stop vidange`), puis `vidange-es lister particules_dehors`.
5. Attendu : une valeur du même ordre que le capteur du dedans, quand les deux sont au même endroit.
6. Comparer les deux capteurs côte à côte, au même endroit : ils doivent donner presque la même valeur.

## Étape 3 : les pannes des SPS30

1. Débrancher le capteur : après `delai_muet_s` (5 s), `vidange-es lister particules_dedans` répond « ÉCHEC :
   muet ». Rebrancher : la valeur revient d'elle-même (le programme redémarre la mesure du capteur).
2. Débrancher puis rebrancher l'adaptateur USB : la valeur revient après une ou deux lectures en échec.
3. Éteindre puis rallumer le capteur seul, programme laissé en route : la valeur revient.
4. Faire la même chose avec le 2e capteur, puis `vidange-es lister particules_dedans particules_dehors` en
   débranchant un seul : l'un en échec, l'autre lu.

## Étape 4 : le SDP810 (pression)

1. Éteindre le Pi. Brancher le SDP810 sur l'I2C (SDA = GPIO2, SCL = GPIO3, 3,3 V, masse), comme le SHT31.
2. Rallumer, puis `sudo i2cdetect -y 1` : on doit voir **25** (l'adresse 0x25) en plus des autres.
   Si l'adresse est autre : la noter et l'écrire dans `entrees-sorties.yaml`, signal `pression_enceinte`.
3. `vidange-es lister pression_enceinte` : on lit environ **0 Pa** (entre −1 et +1) avec les deux tuyaux à l'air libre.
4. Souffler **doucement** dans le tuyau marqué **P** avec la seringue : la valeur doit devenir **positive** (jusqu'à
   quelques dizaines de Pa), puis revenir à 0. Souffler dans le tuyau **N** : elle devient négative.
5. Si c'est l'inverse de ce que la machine doit donner (enceinte plus haute que le conteneur = positif) : ne pas
   rebrancher, mettre `inverser: true` dans le bloc `pression:` du signal `pression_enceinte`.
6. Débrancher le capteur : `vidange-es lister pression_enceinte` répond « ÉCHEC ». Rebrancher : la valeur revient.
7. Ne jamais dépasser 125 Pa en soufflant.
8. Plus tard, sur la machine : tuyau P dans l'enceinte, tuyau N dans le conteneur (côté filtre). Fermer le store,
   mettre le ventilateur en marche (étape 5) : la valeur doit monter vers la surpression normale
   (`machine.yaml → nettoyage → purge → pression_normale_pa`).

## Étape 5 : la consigne 0-10 V du ventilateur

**Le moteur du ventilateur n'est pas branché pour cette étape** : on mesure seulement la sortie du module avec le
voltmètre.

1. Éteindre le Pi. Brancher le module PWM → 0-10 V : entrée PWM sur GPIO19 (3,3 V), alimentation selon sa notice,
   masse commune avec le Pi.
2. Dans `/boot/firmware/config.txt`, ajouter `dtoverlay=pwm-2chan,pin=18,func=3,pin2=19,func2=3` (le canal 2 est
   le servo de la caméra du dosage, le canal 3 est cette consigne), puis redémarrer.
3. `ls /sys/class/pwm/` : noter le nom de la puce (`pwmchip0`, `pwmchip2`...) et vérifier `fichier` et `canal` dans
   `entrees-sorties.yaml`, signal `consigne_ventilateur`, bloc `pwm:`. Si le canal de GPIO19 n'est pas 3, le corriger.
   **Vérifier aussi que le servo de la caméra du dosage (période de 20 ms) et cette consigne (période du module)
   marchent ensemble : régler l'un, puis l'autre, et revoir le premier.** Si l'un dérègle l'autre : le noter dans la
   PR (question 1).
4. Voltmètre sur la sortie 0-10 V du module. Programme arrêté, taper : `vidange-es consigne consigne_ventilateur 5`.
   Attendu : environ **5 V**. Appuyer sur Entrée : la tension revient à **0 V**.
5. Refaire avec `0`, `2.5`, `10`. Noter les tensions lues. Si elles ne suivent pas (par exemple 10 donne 9,2 V),
   écrire dans la PR ce qui est lu : c'est `pleine_echelle_v` ou la période du module qui est à corriger.
6. `vidange-es consigne consigne_ventilateur 11` doit répondre « ÉCHEC : hors de 0 à 10 V » et ne rien changer.
7. Sans le programme (Pi éteint ou programme arrêté), le module doit rendre 0 V, ou bien le relais
   `ventilateur_enceinte` coupe le moteur : vérifier que la tension ne reste pas à une valeur au repos non nulle
   si le Pi s'arrête en pleine consigne (arrêter le programme avec `kill -9` pendant la consigne à 5 V et lire le
   voltmètre ; noter le résultat).

## Étape 6 : tout ensemble, avec le programme principal

1. Redémarrer : `sudo systemctl start vidange`, puis `vidange --verifier` doit dire « Réglages corrects ».
2. Sur la page « Enceinte » : les trois capteurs de la purge ne sont plus signalés « pas encore branchés ».
3. Fermer le store : la purge démarre. Noter les valeurs de particules et de pression, et la durée de la purge
   (elle doit finir sans alerte si l'air est propre et la surpression atteinte).
4. Débrancher le SPS30 du dehors en pleine purge : elle doit finir en **alerte à 20 min** (jamais « finie »), avec
   le message sur l'écran. Rebrancher.

## Noter dans la PR

Les valeurs des notices qui ont changé (bauds, commandes, ordre des nombres, adresse, période du PWM, tension à
100 %), les tensions lues à l'étape 5, et le résultat de chaque étape.

- [ ] SPS30 dedans correct   - [ ] SPS30 dehors correct   - [ ] SDP810 correct (signe vérifié)
- [ ] Consigne 0-10 V correcte   - [ ] Notices vérifiées   - [ ] Purge essayée sur la machine
