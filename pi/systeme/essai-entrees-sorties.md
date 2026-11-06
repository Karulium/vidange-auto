# Essai des entrées/sorties du Pi sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent que des
**faux** capteurs. Cette procédure vérifie chaque carte branchée au Pi : capteur d'ambiance SHT31,
convertisseur ADS1115 (vide du venturi), entrées 24 V, relais (voyant-buzzer), capteurs d'ozone (essai à part).
Compter environ 1 h la première fois. On peut faire les étapes séparément, au fil des branchements.

## Avant de commencer

- Le Pi est installé (voir `installation.md`).
- **Rien de dangereux sur les relais** : pour l'étape 5, seul le voyant-buzzer est branché sur la carte relais
  (ou rien du tout : on écoute le « clic » et on regarde la petite lumière du relais).
- Arrêter le programme du Pi (les broches ne se prennent qu'une fois) :

  ```
  sudo systemctl stop vidange
  ```

- Mettre à jour le programme du Pi (cette version ajoute les bibliothèques `smbus2` et `gpiod`
  et la commande `vidange-es`) :

  ```
  cd /opt/vidange-auto && sudo -u vidange git pull
  cd pi && sudo -u vidange .venv/bin/pip install -e .
  ```

Dans les commandes ci-dessous, `vidange-es` veut dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-es`.

## Étape 1 : activer l'I2C et vérifier les broches (une seule fois)

1. Activer le bus I2C, installer deux petits outils de contrôle, puis redémarrer :

   ```
   sudo raspi-config nonint do_i2c 0
   sudo apt install -y i2c-tools gpiod
   sudo reboot
   ```

2. Après le redémarrage : `ls /dev/i2c-1` doit répondre `/dev/i2c-1`.
3. Chercher les puces sur le bus (l'ADS1115, le SHT31 et la carte relais doivent être branchés et alimentés) :

   ```
   i2cdetect -y 1
   ```

   Le tableau doit montrer `44` (SHT31), `48` (ADS1115) et l'adresse de la puce de chaque carte branchée
   en I2C (souvent `20` à `27`). **Une adresse absente = puce mal branchée ou pas alimentée : s'arrêter et
   vérifier le câblage** (SDA sur GPIO2, SCL sur GPIO3, masse commune, 3,3 V).
4. Vérifier le nom du fichier des broches GPIO : `gpiodetect` doit montrer une ligne
   `gpiochip0 [pinctrl-rp1] (54 lines)`. Si le nom n'est pas `gpiochip0`, le noter : il faudra l'écrire dans
   `docs/entrees-sorties.yaml` (lignes `fichier: /dev/gpiochip0`).

## Étape 2 : écrire le vrai câblage dans la liste

Dans `docs/entrees-sorties.yaml`, pour chaque carte et chaque signal **vraiment** branché :
la broche, la liaison (GPIO ou I2C), le niveau actif, l'adresse. Enlever `exemple: true` sur les lignes devenues
vraies. Puis vérifier :

```
sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange --verifier
```

Doit finir par « Réglages corrects ». Sinon, le message dit quelle ligne corriger.

Pour voir tous les signaux d'un coup : `vidange-es lister`. Si une carte n'est pas encore branchée,
la commande s'arrête sur elle : donner alors seulement les signaux à essayer, par exemple
`vidange-es lister sht31_armoire`.

## Étape 3 : température et humidité de l'armoire (SHT31)

1. Taper `vidange-es lister sht31_armoire`.
   Attendu : `sht31_armoire (ambiance) : 29.5 °C, 70 %` (des valeurs proches d'un thermomètre posé à côté,
   à 1 °C et 5 % près).
2. Souffler doucement sur le capteur et recommencer : l'humidité monte nettement.
3. Débrancher le fil SDA du SHT31 et recommencer : attendu `ÉCHEC : signal « sht31_armoire » : puce I2C 0x44 :
   pas de réponse...`. Rebrancher : la mesure revient.

- [ ] SHT31 correct

## Étape 4 : vide du venturi (ADS1115, voie A0)

1. Venturi arrêté : `vidange-es lister vide_venturi`. Attendu : près de 0 kPa.
2. Mesurer au voltmètre la tension entre A0 et la masse de l'ADS1115. Avec la conversion de la liste
   (deux points « tension → valeur »), vérifier que la valeur affichée correspond à cette tension.
   **La tension ne doit jamais dépasser 3,3 V sur A0** (un capteur 0,5-4,5 V a besoin d'un pont diviseur).
3. Venturi en marche, ventouse bouchée avec la main : la valeur descend (vide plus fort). Relâcher : elle remonte.

- [ ] ADS1115 correct

## Étape 5 : entrées 24 V

1. Taper `vidange-es surveiller`. Chaque entrée s'affiche une fois au départ (normalement `repos`).
2. Actionner les capteurs **un par un, à la main** (fermer le panneau du poste du fût, ouvrir la porte du spray,
   appuyer sur la fin de course...). Chaque fois, une ligne doit apparaître :
   `10:42:07  reed_panneau_poste_fut : ACTIONNÉ`, puis `repos` quand on relâche.
3. Si un capteur affiche `ACTIONNÉ` au repos et `repos` quand on l'actionne : c'est l'inverse. Vérifier dans
   la liste `repos:` du signal (contact ouvert ou fermé au repos) ; si **tous** les signaux de la carte sont
   inversés, c'est `niveau_actif` de la carte (haut ↔ bas).
4. Si rien ne bouge : vérifier le 24 V de la carte d'entrées, puis la broche dans la liste.
5. Ctrl+C pour finir.

- [ ] Toutes les entrées branchées réagissent, dans le bon sens

## Étape 6 : relais (voyant-buzzer)

1. Taper `vidange-es commander voyant_buzzer oui`. Attendu : clic du relais, le voyant s'allume et le buzzer sonne.
2. Appuyer sur Entrée : le relais retombe, le voyant s'éteint.
3. Si le relais colle au départ et retombe avec `oui` : `niveau_actif` de la carte relais est faux (haut ↔ bas).
4. Pour chaque autre relais branché plus tard, même essai **seulement si ce qu'il commande est sans danger**.
5. Vérifier qu'au démarrage du Pi (avant tout programme) **aucun relais ne colle**. Sinon, le signaler :
   il faut changer la carte relais ou sa liaison, pour qu'un Pi qui redémarre ne commande rien.

- [ ] Relais correct, rien ne colle au démarrage

## Étape 7 : capteurs d'ozone ZE25-O3

Les 2 capteurs d'ozone ont leur propre procédure : `pi/systeme/essai-ozone.md`.

- [ ] Ozone fait (voir essai-ozone.md)

## À la fin

Redémarrer le programme : `sudo systemctl start vidange`. Noter dans la PR (ou dire à la session suivante)
les essais réussis et ce qui a été changé dans la liste.
