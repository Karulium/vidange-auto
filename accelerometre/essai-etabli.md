# Essai de l'accéléromètre à l'établi (tâches 14 et 15)

Testé sur le vrai matériel : **non** (seulement sur PC et dans GitHub Actions, avec des faux).

But : vérifier sur le vrai matériel que le RP2040 coupe bien le signal « OK » sur un choc, sur
une panne du capteur, quand son programme se fige et sans courant ; puis choisir le seuil.
La **partie 2** (à la fin) essaie le fil série unique entre le RP2040 et le Pi (tâche 15).

Compter environ 1 h pour la partie 1, 45 min pour la partie 2. Rien ne bouge : l'essai se fait
sur la table, hors de la machine.

## Ce qu'il faut

- La carte RP2040 et le LIS3DH (carte toute faite, avec ses résistances de tirage I2C).
- 4 fils pour le LIS3DH, une plaque d'essai.
- Une LED et une résistance de 1 kΩ (ou un multimètre) pour voir la sortie « OK ».
- Une résistance de 10 kΩ (tirage de la sortie « OK » vers la masse).
- Un câble USB et un PC avec le navigateur **Chrome** ou **Edge** (pour la fenêtre texte).

## 1. Récupérer le programme

1. Sur GitHub, ouvrir la PR de la tâche 15 (ou la plus récente qui touche `accelerometre/`), onglet **Checks** (Vérifications), puis la ligne
   **Tests**.
2. En bas de la page, partie **Artifacts**, cliquer sur **accelerometre** : un fichier zip
   se télécharge. Le décompresser : il contient `accelerometre.uf2`.

## 2. Brancher (carte débranchée de l'USB)

Les numéros de broches sont ceux de `pi/reglages/accelerometre.yaml` (exemple : carte « pico »).
S'ils ne vont pas avec la carte achetée, le dire dans la PR : on change le fichier, GitHub refait
le programme.

| LIS3DH | RP2040 |
|---|---|
| VIN (ou 3V3) | 3V3 |
| GND | GND |
| SDA | GPIO 4 (`i2c_sda`) |
| SCL | GPIO 5 (`i2c_scl`) |
| SDO (s'il existe) | GND (adresse 0x18) |

Sortie « OK » (GPIO 2, `sortie_ok`) :
- GPIO 2 → résistance 1 kΩ → patte longue de la LED ; patte courte de la LED → GND ;
- GPIO 2 → résistance 10 kΩ → GND (tirage vers la masse).

## 3. Charger le programme

1. Tenir appuyé le bouton **BOOTSEL** de la carte, brancher l'USB, lâcher le bouton.
2. Un disque nommé **RPI-RP2** apparaît sur le PC. Y copier `accelerometre.uf2`.
3. La carte redémarre toute seule (le disque disparaît) : c'est normal.

## 4. Ouvrir la fenêtre texte

1. Dans Chrome, ouvrir <https://googlechromelabs.github.io/serial-terminal/>.
2. Cliquer **Connect**, choisir la carte (« Pico » ou le nom de la carte), vitesse sans
   importance.
3. Taper `aide` puis Entrée. On doit lire :
   - « Accéléromètre du chariot Z (RP2040 + LIS3DH) — réglages d'EXEMPLE » ;
   - « Autotest du capteur, écarts x y z : ... » avec 3 nombres **entre 17 et 360** ;
   - la liste des commandes.

Puis une ligne par seconde, par exemple : `OK | max 0,01 g | seuil 1,50 g | chocs 0`.

**À noter dans la PR** : les 3 écarts de l'autotest.

## 5. Les essais

Cocher chaque ligne ; si un résultat est différent, noter ce qui s'affiche.

| # | Faire | Attendu |
|---|---|---|
| 1 | Carte posée à plat, ne rien toucher | LED « OK » allumée ; `OK` ; « max » à moins de 0,05 g |
| 2 | Pencher doucement le LIS3DH (quelques secondes pour aller à 45°) | Toujours `OK` (le fond suit la pente) ; pas de choc compté |
| 3 | Donner un petit coup sec sur la table, à côté du LIS3DH | Si « max » dépasse le seuil : LED éteinte environ 0,5 s, `COUPÉ : choc`, `chocs 1 (dernier ...)` ; puis `OK` revient |
| 4 | Taper `seuil 0,3` puis faire le n° 3 | « Seuil changé » ; le petit coup suffit à couper « OK » |
| 5 | Taper `seuil 20` | « Seuil refusé » (plus que la pleine échelle de 8 g) |
| 6 | Remettre `seuil 1,5`, puis secouer le LIS3DH bien droit de haut en bas (axe z, vertical une fois monté) | Pas de choc compté avec `seuil 1,5` (seuls x et y comptent) |
| 7 | Débrancher le fil SDA du LIS3DH | LED qui clignote, `COUPÉ : panne (...)` en moins d'une seconde |
| 8 | Rebrancher le fil SDA | Au bout de 2 s environ : autotest refait, `OK` revient |
| 9 | Débrancher le fil VIN du LIS3DH, attendre 5 s, le rebrancher | Comme n° 7 puis n° 8 |
| 10 | Taper `essai chien` | LED éteinte un court instant, la carte redémarre (reconnecter la fenêtre texte avec **Connect**) ; on lit « ce démarrage vient du chien de garde » |
| 11 | Débrancher l'USB (plus de courant) | LED éteinte ; au multimètre, GPIO 2 à 0 V |
| 12 | Rebrancher l'USB | `OK` revient en moins d'une seconde |

## 6. Choisir le seuil (à faire plus tard, sur la machine)

Le seuil doit être au-dessus des secousses normales et en dessous d'un vrai choc.

1. Le LIS3DH monté sur le chariot Z, la fenêtre texte ouverte (câble USB jusqu'au PC).
2. Faire les mouvements normaux du chariot, aux vitesses du cycle, et noter le plus fort
   « max » lu.
3. Choisir un seuil environ 2 fois plus fort (exemple : « max » normal 0,4 g → seuil 0,8 g),
   l'essayer avec `seuil ...`, puis l'écrire dans `pi/reglages/accelerometre.yaml`
   (`seuil_g`) par une PR : GitHub refait le programme, le recharger (étapes 1 et 3).

## Résultat à donner dans la PR

- Les 12 essais : bons ou pas (et ce qui s'affiche si ce n'est pas bon).
- Les 3 écarts de l'autotest.
- La référence de la carte RP2040 et du LIS3DH achetés.

---

# Partie 2 : le fil série vers le Pi (tâche 15)

But : vérifier que le Pi lit l'état et les chocs du RP2040 par **un seul fil**, et qu'il lui
envoie ses réglages. Le Pi ne fait qu'enregistrer : la sortie « OK » marche sans lui.

Le Pi pose une question, le RP2040 répond ; ils ne parlent jamais en même temps. Côté Pi, la
sortie TX passe par une résistance de 1 kΩ, et l'entrée RX est sur le même fil.

## Ce qu'il faut en plus

- Le Raspberry Pi 5 avec le programme installé (`pi/systeme/installation.md`).
- Une résistance de 1 kΩ, 3 fils (et plus tard le vrai câble d'environ 10 m).
- Le montage de la partie 1, programme de la tâche 15 chargé (étapes 1 et 3).

## 7. Brancher (Pi éteint, RP2040 débranché)

Les broches sont celles de `pi/reglages/accelerometre.yaml` (`fil_serie`) et de
`docs/entrees-sorties.yaml` (`accelerometre_fil`).

| Pi 5 | | RP2040 |
|---|---|---|
| GPIO 14 (broche n° 8, TX du Pi) | → résistance **1 kΩ** → | le fil |
| GPIO 15 (broche n° 10, RX du Pi) | → directement → | le fil |
| le fil | → | GPIO 0 (`fil_serie`) |
| GND (broche n° 6) | → | GND |

Les deux bouts de la résistance côté fil et le GPIO 15 se rejoignent donc au même point, qui va
au GPIO 0 du RP2040. Tout est en 3,3 V : pas d'adaptateur. Pour cet essai, le RP2040 reste
alimenté par son USB (relié au PC pour la fenêtre texte, ou à un chargeur).

## 8. Préparer le Pi (une seule fois)

1. Allumer l'UART n° 0 du Pi 5 (celle des GPIO 14 et 15) : ajouter une ligne à la fin de
   `/boot/firmware/config.txt`, puis redémarrer le Pi :
   ```
   sudo nano /boot/firmware/config.txt        # ajouter : dtparam=uart0=on
   sudo reboot
   ls -l /dev/ttyAMA0                          # doit exister après le redémarrage
   ```
2. Arrêter le programme du Pi (un port série ne s'ouvre qu'une fois), et mettre le programme à
   jour (cette version ajoute la commande `vidange-accelerometre`) :
   ```
   sudo systemctl stop vidange
   cd /opt/vidange-auto && sudo -u vidange git pull
   cd pi && sudo -u vidange .venv/bin/pip install -e .
   ```

Dans les commandes ci-dessous, `vidange-accelerometre` veut dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-accelerometre`.

## 9. Les essais du fil

| # | Faire | Attendu |
|---|---|---|
| 13 | `vidange-accelerometre etat` | Une ligne `OK | max 0.01 g | chocs 0 | allumé depuis ... s`, puis la liste des réglages, sans crochets |
| 14 | `vidange-accelerometre suivre`, puis un petit coup sec à côté du LIS3DH (avec le seuil à 0,3 g : taper `seuil 0,3` dans la fenêtre texte avant) | Une ligne par seconde ; après le coup : `Accéléromètre : CHOC n° 1 de ... g pendant ... ms`. Ctrl-C pour finir |
| 15 | Donner 5 petits coups de suite, puis `vidange-accelerometre suivre` | Les 5 chocs s'affichent, chacun une fois |
| 16 | `vidange-accelerometre etat` (après avoir mis `seuil 0,3` à la fenêtre texte) | Dans la liste : `seuil_mg = 300  [1500]` (entre crochets : la valeur du Pi) |
| 17 | `vidange-accelerometre envoyer`, puis `vidange-accelerometre etat` | `REGLER ok`, puis `seuil_mg = 1500` sans crochets ; la fenêtre texte dit `seuil 1,50 g` |
| 18 | Débrancher le fil du GPIO 0, puis `vidange-accelerometre etat` | « Pas de réponse » ; la LED « OK » reste allumée (le RP2040 n'a pas besoin du Pi) |
| 19 | Rebrancher le fil, puis `vidange-accelerometre etat` | Ça répond de nouveau |
| 20 | Débrancher le fil SDA du LIS3DH, puis `vidange-accelerometre etat` | `COUPÉ : panne (...)` ; le rebrancher : `OK` revient |
| 21 | Lancer `vidange-accelerometre suivre`, débrancher l'USB du RP2040, attendre 3 s, le rebrancher | « pas de réponse », puis « il ne répond pas » ; au retour : « il répond », « le RP2040 a redémarré » |
| 22 | Relancer le programme : `sudo systemctl start vidange`, donner un coup sec (seuil à 0,3 g), puis `journalctl -u vidange -n 50 \| grep -i accél` | « Accéléromètre : port série ouvert », puis « CHOC n° 1 de ... g » ; s'il dit « réglages envoyés (seuil_mg 300 → 1500) », c'est normal (le Pi remet ses réglages) |

Si rien ne répond (n° 13) :
- vérifier la ligne `dtparam=uart0=on` et que `/dev/ttyAMA0` existe ;
- vérifier que la résistance est bien sur le **GPIO 14** (TX), et le GPIO 15 directement sur le fil ;
- vérifier la masse commune ;
- `vidange-accelerometre question ETAT` doit rendre une ligne qui commence par `ETAT t_ms=`.

## 10. Avec le vrai câble (plus tard, sur la machine)

Refaire les essais n° 13, 14 et 17 avec le câble d'environ 10 m, moteurs en marche, et laisser
`vidange-accelerometre suivre` tourner 10 minutes pendant les mouvements normaux : aucune ligne
« pas de réponse » ne doit apparaître. Le journal du programme dit aussi « il ne répond pas »
si le fil se coupe.

## Résultat à donner dans la PR (partie 2)

- Les essais n° 13 à 22 : bons ou pas (et ce qui s'affiche si ce n'est pas bon).
- Plus tard : l'essai avec le vrai câble (n° 10).
