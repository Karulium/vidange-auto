# Essai de l'I2C du plateau du remplissage : servos et capteur de distance (tâche 40 bis)

Testé sur le vrai matériel : **non** (seulement sur PC et dans GitHub Actions, avec des faux).

But : vérifier sur le vrai matériel que la carte de pesée du plateau du remplissage

- met un servo à l'angle demandé par le Pi (PCA9685) ;
- lit la distance du capteur VL6180X ;
- démarre **servos coupés** (ils ne bougent pas tout seuls) ;
- **garde les angles** quand le Pi se tait plus de 2 secondes ;
- dit au Pi qu'elle a redémarré ;
- **continue de peser 80 fois par seconde** pendant tout ça.

Compter environ 1 h 30. Rien n'est monté sur la machine : tout se fait sur la table, **servos
détachés de tout mécanisme** (un servo DS3225 est très fort : il ne doit rien pousser, ni vos
doigts ni une butée).

Cette procédure ne touche ni au Micropore ni à la Fermeture des seaux (tâches 40 et 41) : ici on
vérifie seulement « un angle demandé = un angle obtenu » et « une distance lue ».

## Ce qu'il faut

- La carte du plateau du remplissage déjà essayée à l'établi (`essai-etabli.md`, jusqu'à l'étape
  7 au moins), avec son HX711 et le bus RS485 qui marchent.
- Une carte **PCA9685** (16 voies, I2C) et un capteur **VL6180X** sur sa petite carte (I2C).
- Un servo de chaque sorte si vous les avez (MG90S et DS3225). Sinon, un seul servo suffit : on
  l'essaie sur chacune des trois voies à tour de rôle.
- Une alimentation pour les servos : **5 à 6 V, au moins 3 A** (un chargeur de PC vers 5 V, ou le
  BEC de la machine). **Jamais** l'alimentation du RP2040 : un servo qui démarre ferait redémarrer
  la carte.
- Si vos petites cartes n'ont pas de résistances de tirage : 2 résistances de **4,7 kΩ** (une de
  SDA vers le 3,3 V, une de SCL vers le 3,3 V). La plupart des cartes PCA9685 et VL6180X vendues
  toutes faites en ont déjà : dans ce cas ne rien ajouter.
- Un rapporteur ou un angle imprimé (pour lire l'angle du servo), une règle (pour la distance),
  un objet plat (une carte plastique).
- Un PC avec **Chrome** ou **Edge** (fenêtre texte de la carte) et le Pi avec l'adaptateur
  USB-RS485 du bus des pesées déjà branché.

## 1. Récupérer le programme

1. Sur GitHub, ouvrir la PR de la tâche 40 bis, onglet **Checks**, ligne **Tests**.
2. En bas, partie **Artifacts**, cliquer sur **pesee** : un zip se télécharge. Le décompresser.
3. Le fichier à utiliser est **`pesee_plateau_remplissage.uf2`** (les deux autres cartes n'ont pas
   l'I2C et ne changent pas).

## 2. Câbler (carte débranchée de l'USB et du bus)

Les noms exacts des broches dépendent de votre carte RP2040. Les numéros ci-dessous sont ceux
d'EXEMPLE de `pi/reglages/pesees.yaml` (`i2c → broches`) ; s'ils ont été changés, prendre ceux du
fichier.

| De | Vers |
|---|---|
| RP2040 **GP4** | **SDA** de la PCA9685 et **SDA** du VL6180X (les deux sur le même fil) |
| RP2040 **GP5** | **SCL** de la PCA9685 et **SCL** du VL6180X |
| RP2040 **3,3 V** | **VCC** (logique) de la PCA9685 et **VIN** du VL6180X |
| RP2040 **0 V** | **GND** de la PCA9685 et du VL6180X |
| Alimentation des servos **+** | borne **V+** de la PCA9685 (pas le VCC !) |
| Alimentation des servos **0 V** | borne **GND** de la PCA9685 **et** 0 V du RP2040 (masse commune) |
| Servo n° 1 | voie **0** de la PCA9685 (fil marron/noir côté bord de la carte) |
| Servo n° 2 | voie **1** |
| Servo n° 3 | voie **2** |

Vérifier deux fois : le **+ des servos ne doit jamais toucher le 3,3 V**. Les voies 0, 1 et 2
sont celles de `pesees.yaml` (`servo_escamotage_micropore`, `servo_lame_micropore`,
`servo_fermeture_seaux`).

## 3. Charger le programme

1. Débrancher la carte, appuyer sur le bouton **BOOTSEL**, brancher l'USB sans lâcher, puis lâcher :
   un disque « RPI-RP2 » apparaît.
2. Copier `pesee_plateau_remplissage.uf2` dessus. La carte redémarre seule.
3. Ouvrir la fenêtre texte de la carte (comme à l'étape 4 de `essai-etabli.md`). Elle dit
   « Carte de pesée « pesee_plateau_remplissage », adresse 3 sur le bus ».
4. Alimenter les servos.

| # | Faire | Attendu |
|---|---|---|
| 1 | Allumer l'alimentation des servos après la carte | **Aucun servo ne bouge.** Chacun est libre : on peut tourner son axe à la main sans résistance |
| 2 | Éteindre puis rallumer l'alimentation des servos, carte allumée | Toujours aucun mouvement |

**Si un servo bouge ou durcit tout seul : tout éteindre et le dire** (la PCA9685 ne démarre pas
sorties coupées, ou un fil est mal branché).

## 4. Lire l'état avec le Pi

Brancher la carte sur le bus RS485 (A avec A, B avec B, 0 V commun). Sur le Pi, arrêter le
programme principal (`sudo systemctl stop vidange`), puis :

`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-pesees chariot`

Une ligne par seconde (Ctrl+C pour arrêter).

| # | Attendu |
|---|---|
| 3 | La ligne dit `distance … mm`, `démarrages …` (un nombre), `échecs I2C 0` et **`aucun ordre depuis le démarrage`** |
| 4 | Les trois servos disent `coupée` |

Noter le nombre `démarrages` : _____ . Débrancher puis rebrancher l'USB de la carte (elle
redémarre) : le nombre **doit avoir changé** (pas forcément de +1).

## 5. Le capteur de distance

Tenir la carte plastique devant le capteur, à 2 cm, 5 cm et 8 cm (mesurés à la règle), pendant que
`vidange-pesees chariot` tourne.

| # | Faire | Attendu |
|---|---|---|
| 5 | Carte à 2 cm | environ 20 mm (à 5 mm près) |
| 6 | Carte à 5 cm | environ 50 mm |
| 7 | Carte à 8 cm | environ 80 mm |
| 8 | Rien devant le capteur (le dégager de 30 cm) | Plus de bonne distance : `pas de mesure (état …)` ou une valeur fixe tout en haut. **Noter ce qu'on voit** : _____ |
| 9 | Débrancher le fil SDA du VL6180X | Au bout de 1 à 2 s : `ToF MUET` ; la ligne ne s'arrête pas |
| 10 | Rebrancher SDA | Au bout de 1 à 2 s la distance revient seule |

Écrire ici les distances lues aux 3 distances : _____ / _____ / _____ mm. Le VL6180X ne voit pas
plus loin qu'environ 10 cm.

## 6. Un servo à un angle

**Le servo doit être libre de tout mécanisme.** Commencer par un servo seul, au milieu de sa plage.

1. Taper : `vidange-pesees servo servo_lame_micropore 90`. Réponse attendue :
   `servo_lame_micropore : 90° (ordre envoyé)`.
2. Le servo se met à 90° (milieu de sa course de 0 à 180°). Le lire au rapporteur : _____ °.
3. Essayer 45, puis 135, puis 0, puis 180 : à chaque fois, lire l'angle réel.

| # | Faire | Attendu |
|---|---|---|
| 11 | Ordre à 90° | Le servo va à 90° (à 5° près pour un MG90S ; un servo bon marché a un jeu) |
| 12 | Ordre à 0° puis 180° | Le servo va à chaque bout **sans forcer ni siffler** (s'il force ou siffle : arrêter, `servo … coupe`, et noter que les impulsions de `pesees.yaml` sont trop larges) |
| 13 | `vidange-pesees servo servo_lame_micropore 181` | **Refusé par l'outil** : « hors de sa plage », le servo ne bouge pas |
| 14 | `vidange-pesees servo servo_lame_micropore coupe` | Le servo devient libre |
| 15 | Refaire les étapes 1 à 3 sur la voie 0 (`servo_escamotage_micropore`, 0 à 270°) puis la voie 2 (`servo_fermeture_seaux`) | Même résultat sur chaque voie |

Noter pour chaque servo l'angle réel aux deux bouts si ce n'est pas celui demandé : ces écarts
servent à corriger `angle_min_deg`, `angle_max_deg`, `impulsion_min_us` et `impulsion_max_us` dans
`pi/reglages/pesees.yaml` (la tâche 40 s'en servira, il faudra refabriquer le programme de la
carte après). Ne rien corriger à la main sur la carte.

## 7. Le Pi se tait : les angles sont gardés

1. Mettre un servo à 90° (`servo servo_lame_micropore 90`).
2. Lancer `vidange-pesees chariot` : la ligne dit `dernier ordre il y a … ms` et ce nombre monte.
3. Après 2 secondes : la ligne dit **`PI SILENCIEUX (angles gardés)`**.

| # | Attendu |
|---|---|
| 16 | **Le servo ne bouge pas du tout** pendant au moins 30 s de silence (il reste à 90°, il ne se détend pas, il ne revient pas au milieu) |
| 17 | Un nouvel ordre (`servo servo_lame_micropore 60`) fait repartir : `PI SILENCIEUX` disparaît, le servo va à 60° |

## 8. La carte redémarre : le Pi s'en aperçoit

1. Servo à 90°. Noter `démarrages` : _____ .
2. Débrancher puis rebrancher **l'USB (ou l'alimentation) de la carte** sans toucher aux servos.

| # | Attendu |
|---|---|
| 18 | Le servo devient libre (sortie coupée par la PCA9685 au démarrage) |
| 19 | `démarrages` a **changé** ; la ligne redit `aucun ordre depuis le démarrage` |
| 20 | Un ordre (`servo … 90`) remet le servo à 90° |

À la machine, c'est le programme du Pi qui, voyant le nombre changer, renverra tous les angles.

## 9. La pesée garde son rythme avec l'I2C

L'outil ne peut pas lire l'état de l'I2C et la pesée en même temps (l'adaptateur ne s'ouvre qu'une
fois), mais l'I2C continue de travailler seul : le capteur mesure toujours et les servos gardent
leurs angles.

1. Mettre deux servos à un angle (`servo … 90`), le capteur de distance devant la carte plastique.
2. Poser un poids connu sur le capteur de pesée de la carte (ou le laisser à vide).
3. `vidange-pesees lire --secondes 120`.

| # | Attendu |
|---|---|
| 21 | La ligne `pesee_plateau_remplissage` dit **`carte 80 mesures/s`** (jamais moins de 78), « sans réponse 0 », « trames abîmées 0 » |
| 22 | Dans la fenêtre texte de la carte, « mesures/s » est à 80 aussi |
| 23 | Les autres cartes du bus (griffe, préhension) ne sont pas ralenties : leurs « vues par le Pi » sont les mêmes qu'à l'étape 12 de `essai-etabli.md` |
| 24 | Pendant que ça tourne, débrancher le fil SDA (puis le rebrancher) : **les mesures restent à 80 par seconde** |

## 10. Noter et rendre compte

Recopier dans la PR : les distances lues (étape 5 à 8), l'angle réel des 3 servos aux bouts (étape
11 à 15), si le servo reste bien en place en silence (16), si le compteur de démarrages change (19),
et les « mesures/s » (21 à 24). Une case qui ne passe pas = la noter avec ce qu'on a vu, sans rien
bricoler.
