# Essai des capteurs d'ozone ZE25-O3 sur le vrai capteur

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent qu'un faux capteur. Le protocole
(vitesse, trames de 9 octets, somme de contrôle) a été écrit de mémoire : **cet essai sert d'abord à le
vérifier sur la notice papier du ZE25-O3.** Durée : environ 45 min. Un capteur à la fois.

La sécurité ozone est câblée : cet essai ne la touche pas. Ne pas produire d'ozone pendant l'essai
(l'air de la pièce suffit : on doit lire environ 0 ppm).

## Avant de commencer

1. Arrêter le programme principal : `sudo systemctl stop vidange`.
2. Ouvrir la notice papier du ZE25-O3 et trouver : la vitesse (bauds), la longueur des trames (9 octets ?),
   le mode d'envoi (« envoi automatique » ou « question-réponse »), la position de la valeur dans la trame,
   et l'unité de la valeur (ppm × 0,01 ?). Les noter.

## Étape 1 : brancher un capteur

1. Brancher le capteur (5 V, convertisseur TTL-RS485) à son adaptateur USB-RS485, puis l'adaptateur au Pi.
2. Lire le numéro de série de l'adaptateur : `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc lister`.
   **Si le numéro est « AUCUN » : s'arrêter et le signaler.**
3. Écrire ce numéro dans `docs/entrees-sorties.yaml`, carte `rs485_ozone_dedans` (ou `rs485_ozone_dehors`),
   ligne `numero_serie_usb`, entre guillemets.

## Étape 2 : comparer avec la notice

Dans le même fichier, bloc `ozone:` du signal, corriger ce qui diffère de la notice :
`vitesse_bauds` (carte), `mode`, `position_valeur`, `pas_ppm`, `plafond_ppm`. En question-réponse, ajouter
`question:` (la trame de 9 octets de la notice, en hexadécimal). Au démarrage, le programme refuse une question
dont la somme de contrôle est fausse et le dit : c'est un bon contrôle de la copie.

## Étape 3 : lire

1. Taper `vidange-es lister ozone_dedans`.
2. Attendu : « 0,00 ppm » ou une valeur proche de 0 (si l'afficheur du capteur existe, la même valeur),
   et « (0 trames ignorées) » ou un petit nombre.
3. Si on lit « muet » : vérifier l'alimentation 5 V, le sens A/B du RS485, la vitesse, le mode. Si le nombre de
   trames ignorées monte sans cesse : la vitesse ou la somme de contrôle de la notice est différente. Le noter.

## Étape 4 : pannes

1. Débrancher le capteur : après `delai_muet_s` (5 s), `vidange-es lister ozone_dedans` répond « muet ». Rebrancher :
   la valeur revient.
2. Débrancher puis rebrancher l'adaptateur USB : après une ou deux lectures en échec, la valeur revient seule.
3. Faire la même chose avec le 2e capteur, puis lister les deux ensemble en débranchant un seul :
   l'un « muet », l'autre lu.

## Étape 5 (si possible, sans danger) : une vraie valeur

Avec un briquet piézo **sans flamme** ou la source d'essai de la notice, vérifier qu'une valeur monte.
Au plafond (10 ppm), on doit lire « ≥ 10 ppm », jamais « 10 ». Sinon, ne pas insister.

## Noter dans la PR

Les valeurs de la notice qui ont changé (bauds, positions, pas, question) et le résultat de chaque étape.
Redémarrer : `sudo systemctl start vidange`.

- [ ] Capteur dedans correct   - [ ] Capteur dehors correct   - [ ] Notice vérifiée
