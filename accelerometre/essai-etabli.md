# Essai de l'accéléromètre à l'établi (tâche 14)

But : vérifier sur le vrai matériel que le RP2040 coupe bien le signal « OK » sur un choc, sur
une panne du capteur, quand son programme se fige et sans courant ; puis choisir le seuil.

Compter environ 1 h. Rien ne bouge : l'essai se fait sur la table, hors de la machine.

## Ce qu'il faut

- La carte RP2040 et le LIS3DH (carte toute faite, avec ses résistances de tirage I2C).
- 4 fils pour le LIS3DH, une plaque d'essai.
- Une LED et une résistance de 1 kΩ (ou un multimètre) pour voir la sortie « OK ».
- Une résistance de 10 kΩ (tirage de la sortie « OK » vers la masse).
- Un câble USB et un PC avec le navigateur **Chrome** ou **Edge** (pour la fenêtre texte).

## 1. Récupérer le programme

1. Sur GitHub, ouvrir la PR de la tâche 14, onglet **Checks** (Vérifications), puis la ligne
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
