# Décisions déjà prises qui touchent le code

Copiées depuis le projet « Vidange automatique ». Une session ne les rediscute pas ;
si l'une pose problème, elle le dit dans sa PR.

## Générales

- Pi 5 seul chef ; sécurité câblée en dur (arrêt d'urgence en série : 2 boutons + portes, relais de sécurité, contacteurs ; les freins serrent sans courant).
- Synchronisation entre cartes : attente d'état + zones réservées.
- Chocs horizontaux : alarmes des pilotes boucle fermée vers l'ESP32 n° 1, et accéléromètre LIS3DH + RP2040 sur le chariot Z (signal « OK » en sécurité positive vers l'ESP32 n° 1, mesures vers le Pi en série 3,3 V 115 200). Le palier pesé ne sert qu'au vertical.
- QR lus par les caméras (plus de lecteur GM65). Registre SQLite sur le Pi.
- Apprentissage seulement dans un cadre fixé par Karulium : plafonds de vitesse, temps de nettoyage, poids cibles. La sécurité n'est jamais apprise. Chaque réglage changé est noté et annulable. Montée en vitesse par paliers réglables (exemple : +5 % tous les 25 cycles), recul sur alerte.
- PC de bureau : calculs lourds seulement quand Karulium les lance (rien d'automatique, pas de réveil par le réseau). Le Pi signale quand un calcul est conseillé.
- Assistant vocal éventuel : jamais de commande des moteurs.
- UV et ozone : modes verrouillés par le Pi (en plus des sécurités câblées).
- **Ozone et ouverture de l'enceinte : sans danger par le câblage.** L'ozone se fait la nuit, personne présent.
  Un capteur de sécurité 0-1 ppm avec un indicateur à seuil en sécurité positive bloque les stores, et la porte
  reste verrouillée tant que l'ozone dépasse 0,1 ppm (alarme ozone câblée). Le logiciel affiche la mesure
  (RS485) mais ne protège pas : c'est pourquoi la fonction 38 (attendre la valeur avant d'ouvrir) n'est pas utile.
- **Tare des seaux par type de seau** (dans `machine.yaml`), pas une tare unique : le logiciel de culture utilise
  aujourd'hui 268 g pour tous, même les petits 5 L.
- Liaison des cartes relais et des entrées 24 V au Pi (GPIO direct ou I2C) : **pas encore décidée**.
- **Capteur de vide du venturi** (réponse à la PR n° 3, question 1) : module `prehension`. La ventouse Ø 40 est sur
  la tête de préhension (elle prend l'entonnoir, et les seaux mouillés au lavage) ; le capteur est lu par l'ADS1115.
- **Entrées des cartes FluidNC** (PR n° 3, question 2) : le cahier des charges d'achat de la carte exige des entrées
  24 V **isolées par optocoupleurs** (au moins 6 fins de course + alarmes des pilotes + arrêt/pause), et des sorties
  5 V vers les pilotes externes. Dans la liste des entrées/sorties : `isolee: true` pour les 4 cartes FluidNC.
- **Numéro de série USB des cartes FluidNC** (PR n° 4, question 1) : option A retenue. Les 4 cartes doivent avoir
  une puce USB avec un **numéro de série unique** (CP2102N, FT232, CH9102/CH343, ou USB intégré d'un ESP32-S3 ;
  pas de CH340 ni de CP2102 au numéro commun). Exigence ajoutée au cahier des charges d'achat de la carte.
  Si une carte reçue n'en a pas, on fera la reconnaissance par prise USB (option B) dans une petite tâche à part.
- **Réponses aux questions de la PR n° 5** (26/10/2026) :
  1. Relais et entrées 24 V : GPIO direct ou MCP23017, **décidé au remplissage de la vraie liste** :
     15 signaux du Pi ou moins → GPIO direct ; plus → MCP23017. Le code fait déjà les deux.
  2. Adaptateur USB-RS485 : **puce à numéro de série unique** (FT232 ou CP2102N, pas de CH340), même règle que
     les cartes FluidNC. Exigence ajoutée aux achats.
  3. Capteur d'ozone : sa référence n'est pas encore choisie (module Nettoyage, pas figé). Exigence ajoutée :
     **Modbus RTU avec la table de ses registres dans la notice** (vitesse, registre, échelle) ; les valeurs de
     la liste restent des exemples d'ici là. Le nombre de capteurs (1 ou 2) est à confirmer par le module Nettoyage.
  4. Capteur de vide du venturi : référence pas encore choisie (module Air comprimé). Si sa sortie dépasse 3,3 V
     (par exemple 0,5-4,5 V), **pont diviseur 10 kΩ / 20 kΩ** avant l'ADS1115, comme dans l'exemple de la liste.
- **Alarme d'un module : toute la machine s'arrête** (choix de Karulium, 26/10/2026, PR n° 6) :
  `alarme_pause_tout: true` dans `programme.yaml`. On pourra changer plus tard.
- **Réponses aux questions de la PR n° 7** (registre) :
  1. Copie quotidienne sur le même SSD pour l'instant ; la copie hors de la machine viendra avec la tâche 10.
  2. **Un seau peut recevoir plusieurs doses de mycélium, de plusieurs bocaux** (table `doses_mycelium`, avec la
     quantité si elle est pesée) : la machine verse par godets, un bocal peut finir en cours de seau, et les plans
     d'essais feront varier la dose. Dans le logiciel de culture, un lot d'inoculation réunit plusieurs bocaux et
     plusieurs seaux.
  3. 30 copies gardées, réglable dans `programme.yaml`.
- **Petits seaux : un bocal de mycélium peut servir à 2 seaux au plus** (Karulium, 26/10/2026). Le registre le
  permet déjà (une dose = un seau + un bocal). Les gestes du module Mycélium en tiendront compte (le bocal reste
  dans l'agitateur entre les deux seaux, qui passent l'un après l'autre).
- **Réponses aux questions de la PR n° 8** (fiabilité) :
  1. **Onduleur** : Karulium a déjà choisi (08/10/2026, projet mécanique) un **onduleur 230 V** (« niveau 2 »,
     environ 120 €), posé sur une étagère sous l'armoire ; il garde l'armoire alimentée. Le signal
     `onduleur_sur_batterie` ne vient pas de l'onduleur lui-même mais d'un **petit relais 230 V branché AVANT
     l'onduleur** (sur le secteur) : son contact est fermé tant que le secteur est là. Aucun ajout au code, et
     ça marche avec n'importe quel onduleur. Un fil coupé se voit comme une coupure (pause, puis arrêt propre) :
     c'est le côté prudent. Lecture de la batterie par USB (NUT) : peut-être plus tard, pas nécessaire.
  2. **Relais « chien de garde » vers les cartes** : pas pour l'instant (aucun risque pour les personnes, la
     sécurité est câblée). On en reparle quand on comptera les entrées des cartes ; `battement_pi` est prêt.
  3. **Lieu sûr proposé à chaque démarrage** : oui (il attend toujours le Go).
- **Réponse à la question de la PR n° 9** (API et page web) : **option A** pour l'instant. La page est
  joignable depuis le réseau local (en clair, http, protégé par le mot de passe du Wi-Fi de l'atelier) et par
  Tailscale (chiffré) ; elle marche sans Internet. Si d'autres personnes utilisent ce Wi-Fi : passer à « Tailscale
  seulement » en retirant les réseaux locaux de `reseaux_autorises` (`programme.yaml`), sans toucher au code.
- **Réponses aux questions de la PR n° 10** (écran Nextion) :
  1. Acquitter une alarme depuis l'écran (bouton RÉPARÉ) **sans code** pour l'instant : acquitter ne fait rien
     bouger, le module attend ensuite un Go confirmé par OUI. Le code des fonctions sensibles viendra à la tâche 29.
  2. Le **mode** (production / lavage / UV-ozone) est seulement affiché, gardé et refusé pendant un cycle. Les
     modules (Poste du fût, Lavage, Nettoyage) le liront quand on écrira leurs gestes. La sécurité UV et ozone
     reste câblée.
- **Réponses aux questions de la PR n° 12** (file d'envoi) :
  1. Ordinateur qui reçoit la copie de secours : **le serveur de culture N97** (Linux, déjà sur Tailscale ;
     choix de Karulium, 27/10/2026), par rsync. `envois.secours.commande` sera remplie à l'installation du Pi
     (nom Tailscale du N97, compte) ; vérifier alors la place libre sur son disque.
  2. Photos envoyées au logiciel de culture : décidé avec la tâche Vision (n° 22) ; pour l'instant seule leur
     description part avec le cycle.
  3. Dossier des photos envoyé chaque jour à la copie de secours : **oui** (`photos: true`).
- **Réponses aux questions de la PR n° 14** (accès à distance), recommandations suivies :
  1. Débloquer une carte en alarme (`$X`) : **jamais à distance**, seulement sur place.
  2. Une carte qui garde la fin d'un geste du cycle figé en pause : le pilotage à distance **refuse** de la bouger
     (un bouton « oublier le geste » pourra venir après les essais réels).
  3. **Un seul plafond de vitesse** (2 cm/s) pour tous les axes au début, à ajuster aux essais.
  4. Pendant le pilotage manuel « en cas de problème », les zones réservées et les règles validées ne sont **pas**
     vérifiées : c'est Karulium qui regarde la vidéo (vitesse plafond, homme mort, voyant-buzzer, sécurité câblée).
- **Prise d'origine obligatoire à la mise sous tension** : les réglages de chaque carte FluidNC (dossier `fluidnc/`)
  gardent `start: must_home: true`. Une carte qui n'a pas fait sa prise d'origine reste en alarme : aucun
  déplacement manuel à distance ne peut partir d'une position fausse (et `$X` est interdit à distance).
- **Réponses aux questions de la PR n° 15** (mises à jour) :
  1. Le dépôt est privé : le Pi recevra un **jeton GitHub en lecture seule, limité à ce dépôt** (`jeton_github`
     dans le fichier de secrets, jamais dans Git), créé avec Karulium à l'installation du Pi.
  2. Pas de vérification des tests GitHub avant d'installer `main` pour l'instant (`main` ne reçoit que des PR au
     vert, et le Pi revérifie ses réglages avant de redémarrer).
  3. **Même version de FluidNC sur les 4 cartes**, variante **« noradio »** (les cartes parlent au Pi par USB ;
     pas de Wi-Fi ouvert sur la machine). La version est notée à la première installation.
- **Réponses aux questions de la PR n° 16** (accéléromètre, partie 1) :
  1. Carte : **Waveshare RP2040-Zero** (déjà choisie par Karulium le 13/10, projet mécanique). À l'essai à l'établi,
     mettre `carte: waveshare_rp2040_zero` et `voyant: null` dans `pi/reglages/accelerometre.yaml`.
  2. Signal « OK » vers l'ESP32 n° 1 (réponse du fil Portique, 28/10/2026) : dans le boîtier, un optocoupleur
     PC817 (sa LED sur la sortie du RP2040 par 220 Ω, son transistor entre le +24 V et le fil OK) ; à l'entrée de
     l'armoire, 4,7 kΩ entre OK et 0 V. **24 V sur le fil = OK** ; carte éteinte, en redémarrage ou fil coupé =
     « pas OK ». Sortie du RP2040 à 1 quand tout va bien, à 0 sur un choc (c'est ce que fait le programme).
     Le boîtier est alimenté en 24 V (abaisseur 24 → 5 V type MP1584 dedans) ; câble à 4 fils : +24 V, 0 V, OK,
     série.
  3. Orientation (fil Portique) : carte à plat contre la face intérieure de la colonne de la griffe, flèche X du
     LIS3DH vers le haut. X vertical ; Y horizontal le long du pont ; Z horizontal le long des rails. Donc
     **`axes: [y, z]`** (le signe ne compte pas : seule la force horizontale est comparée au seuil).
  4. « OK » revient tout seul après une panne quand l'autotest réussit, et 0,5 s après un choc : oui (la coupure met
     FluidNC en alarme, une action est de toute façon nécessaire pour repartir).
- **Réponse à la question de la PR n° 17** (accéléromètre, partie 2) : le fil série de l'accéléromètre arrive sur le
  Pi en **GPIO 14 (broche n° 8, par 1 kΩ) et GPIO 15 (broche n° 10)**, reliées au même conducteur (UART n° 0,
  `/dev/ttyAMA0`). Gardé, et transmis au projet mécanique pour le plan de câblage de l'armoire.
- **Réponses aux questions de la PR n° 18** (accéléromètre, partie 3), recommandations suivies :
  1. Après une mise à jour de l'accéléromètre, la carte FluidNC n° 1 est en alarme (« OK » coupé pendant la mise à
     jour) et se débloque **sur place** : accepté (mises à jour rares, machine à l'arrêt ; pas de `$X` à distance).
  2. Le chargeur relance seul un programme bon si le Pi ne dit plus rien pendant **60 s** (`chargeur → abandon_s`).
  3. Le RP2040 attend **0,3 s** à chaque démarrage avant de lancer le programme (`chargeur → attente_demarrage_ms`).
- **Réponses aux questions de la PR n° 20** (Poste du fût), recommandations suivies :
  1. Pesée : **lecture directe du HX711 par le Pi** gardée ; on regarde le journal des lectures refaites pendant les
     premiers jours. Passage au pilote de Linux (overlay) seulement si l'essai montre des lectures souvent
     interrompues.
  2. Câble de 10 m et prise magnétique de la pesée : 4 contacts utilisés (3,3 V, 0 V, DT, SCK), carte HX711
     **alimentée en 3,3 V** (sinon la broche du Pi grille), câble blindé, blindage au 0 V côté armoire seulement.
     Transmis au projet mécanique pour le plan de câblage.
  3. Panneau du poste : **un seul contact** gardé (contact ouvert et stable = lavage permis) ; un 2ᵉ contact
     « panneau rabattu » seulement si le projet mécanique le juge utile.
  4. Poids plausible au « Prêt » : 20 à 400 kg (berceau + fût + contenu), à resserrer après les premières pesées.
- **Lecture des pesées embarquées** (projet mécanique, fil Implantation, 28/10/2026) : FluidNC ne lit pas le
  HX711. Une carte RP2040 près de chaque HX711 embarqué (griffe, préhension, plateau du remplissage) lit le HX711
  en 3,3 V et répond sur un **bus RS485 dédié aux pesées**, relié au Pi par un 2ᵉ adaptateur USB-RS485
  (`rs485_pesee`, FT232 ou CP2102N, reconnu par son numéro de série), séparé du Modbus des transmetteurs d'ozone.
  Les fils DT et SCK des câbles deviennent A et B du bus. Le Pi interroge les 3 cartes à tour de rôle, à
  115 200 bauds ; protocole libre (au choix du logiciel). La griffe doit tenir 80 mesures/s. La pesée du chariot
  du fût reste en direct sur 2 GPIO du Pi (tâche 17). Cahier CDC-PESEE-485 du projet mécanique.
- **Réponses aux questions de la PR n° 23** (Griffe) :
  1. Table des formats : les 4 formats mesurés par Karulium (5/10/2026) sont mis dans `machine.yaml` :
     A Superlift 10,8 L (Ø haut 267, Ø bas 229, h 250 mm, la grande majorité), B 5 L (230 / 190 / 200),
     C 10 L large et bas (295 / 255 / 235), D 10 L haut (275 / 240 / 265). Bord du seau au poste de
     remplissage à 0,78 (0,775 pour le 5 L), comme au dosage du mycélium, pour que le plateau ne bouge pas
     entre la griffe et le mycélium (à revoir au gel du Remplissage). Couches (4, et 2 pour le 5 L) et dose par
     couche : exemples, à régler aux essais avec le poids visé par seau. Poste de vidage : mât en
     (0,925 ; 0,14) (Transfert, 7/10).
  2. « Trop léger » : rendre la prise au fût et reprendre juste à côté, 2 fois au plus, puis porter ce qu'il y a :
     gardé.
  3. Prises le long de la paroi (passe de fond) : elles partent au seau pour l'instant (le plus sûr, « la
     fiabilité d'abord ») ; les lâcher au centre du fût sera un essai plus tard.
  4. Raclage de la paroi : une fois, au début de la passe de fond, aller en descendant puis retour en remontant,
     à partir de 1,075 d'axes : gardé pour les premiers essais.
  5. Encombrement de la tête (fiche de la griffe) : bras le long du pont, la tête fait 0,111 de chaque côté du
     mât godet fermé, 0,165 grand ouvert ; rayon balayé en tournant 0,137 ; raclette à 0,111 du mât ; pointes
     des dents à ±0,105 et joues à ±0,136 à 20° d'ouverture. À ajouter comme marges (tâche 18 bis).
  6. Bas du godet sous les axes (STEP de la tête) : 0,203 fermé, 0,211 à 10°, 0,213 à 20° (le plus bas),
     0,204 grand ouvert (35°). Prendre 0,213 partout par prudence (tâche 18 bis).
  7. Dans le fût : mât au plus à 0,197 de l'axe (prises le long de la paroi, fiche), 0,17 côté −x.
  8. Seau commencé quand le fût est vide : gardé tel quel et signalé ; le Remplissage décidera à son gel.
  9. Raclette côté fût (vers −x) quand la tête est bloquée en haut, essuyage du bord côté stockage (mât à +x du
     seau) : confirmé par la fiche ; l'angle exact de A se mesure à l'essai (étape 1).
- **Réponses aux questions de la PR n° 24** (marges de la tête de griffe) :
  1. Essuyage du bord du seau : **côté allée** (mât à +y du seau, tête tournée d'un quart de tour,
     `essuyage → direction_deg: 90`), car à +x la tête toucherait le boîtier de la caméra du bocal (seaux A et B).
     Le seau tourne, donc tout le bord est essuyé. Demandé au projet mécanique de le vérifier sur la maquette 3D ;
     si la 3D donne raison à l'essuyage à +x, remettre `direction_deg: 0`.
  2. Largeur de la tête en travers du bras (réponse du projet mécanique, griffe.json du 28/10) : **pas
     symétrique**, 0,111 côté raclette (la lame fixe) et **0,086** de l'autre côté (bouts des goupilles), la même
     godet fermé ou ouvert. Rayon balayé autour du mât : **0,139** godet fermé, **0,174** godet grand ouvert
     (joues des coquilles, 9 à 12 cm sous les axes). Modèle gardé : rectangle ± 0,086 en travers et ± 0,111 /
     ± 0,165 le long du bras, plus la lame de la raclette à 0,111. Partie haute de la tête (au-dessus des axes et
     jusqu'à 3 cm sous eux) : 0,117 au plus le long du bras ; quand seule elle arrive à la hauteur du boîtier de
     la caméra du bocal (bas à z 0,982), c'est elle seule qui compte. Avec la cote de 0,086, le mât reste à
     x ≤ 0,959 devant le boîtier (la fiche disait 0,96). L'essuyage côté allée passe pour les 4 formats.
- **Réponses aux questions de la PR n° 26** (tâche 19, Mycélium ; tranchées par le fil logiciel, niveau 1) :
  1. Origine de la manivelle : **capteur inductif M8 « manivelle en haut »** (`origine_manivelle`, carte 3), même
     famille que les fins de course de la glissière (quelques euros). Sans lui, après une coupure, la carte ne sait
     pas où est le haut. Demandé au projet mécanique de l'ajouter à la fiche et à la liste d'achats.
  2. « L'agitateur remonte son bocal de 7 cm, quitte son garage » (plan de commande) : on suit la **fiche du
     24/10** (manivelle en haut au garage et pendant les trajets). Le plan de commande sera corrigé.
  3. Au dosage, la manivelle descend avant l'arrivée du seau et remonte après son départ (le verrou du chariot
     l'impose : il ne roule qu'agitateur au dosage manivelle en bas) : **gardé, à vitesse lente**
     (`placement_tr_min`) ; regarder à l'essai si des grains tombent à côté.
  4. La manivelle tourne **dans les deux sens** (retour vers 0°) : accepté. La bielle fait le même mouvement dans les
     deux sens, la manivelle tient par clavette et bague d'arrêt (pas de filetage qui se dévisse) ; le bocal est
     tenu par les mors.
  5. Fichier FluidNC marqué EXEMPLE envoyé à une carte : **tâche 19 bis** ajoutée (refuser l'envoi).
- **Origine de la manivelle** (projet mécanique, validé par Karulium le 29/10/2026, fiche des pièces v9) : le signal
  `origine_manivelle` est un capteur inductif M8 PNP sur la carte 3. Il voit du métal quand la manivelle **n'est pas**
  en haut (le contrepoids passe devant lui) et ne voit rien sur environ ± 95° autour du haut. Prise d'origine :
  un tour lent, noter la position du moteur au bord d'entrée et au bord de sortie de la zone sans métal, dans le
  même sens de rotation ; « manivelle en haut » = le milieu de cette zone, plus un décalage fixe (hystérésis du
  capteur) réglé une fois sur la machine (`machine.yaml`). Précision attendue ≈ 0,5°. Les règles de mouvement ne
  changent pas (manivelle en haut au garage et pendant le roulage ; chariot de remplissage seulement agitateur
  au garage manivelle en haut, ou au dosage manivelle en bas).
- **La fiabilité d'abord** (Karulium, 28/10/2026) : quand rapidité et fiabilité s'opposent, on choisit la
  fiabilité. Un gain de vitesse (ordonnancement, trajets, montée en vitesse par paliers de +5 % tous les 25 cycles)
  n'est gardé que s'il ne crée **aucune alerte ni aucun écart** ; au moindre doute, retour au réglage sûr
  (recul sur alerte). Vaut pour le solveur (tâche 23 : OR-Tools CP-SAT, cycles calculés à l'avance puis joués par
  le Pi) et pour la montée en vitesse (tâche 30).
- **Préhension figée** (27/10/2026) : capteur inductif M8 24 V ; capteur de vide sur l'ADS1115 **en 3,3 V**
  (pas de pont diviseur) ; pour poser ou prendre un bocal sur le porte-bocal, la tête est orientée à ± 3°
  (grâce aux méplats) et ne tourne pas entre les mors.

## Accès à distance et mises à jour (Karulium, 26/10/2026)

- **Accès à distance par Tailscale** (Karulium l'utilise déjà pour son serveur). Aucun port ouvert sur la box.
  L'API et la page web du Pi ne sont joignables que par le réseau local et Tailscale, avec une clé.
- **Vidéos à distance** : voir les caméras en direct sur la page web, et revoir les clips d'incidents
  (mémoire tournante de 60 s gardée à chaque alarme).
- **Pilotage manuel à distance, en cas de problème : OUI** (choix de Karulium). Garde-fous logiciels prévus :
  - un « mode à distance » qu'on active exprès, avec la vidéo en direct affichée pendant tout le pilotage ;
  - vitesse réduite (plafond dans les réglages) ;
  - « homme mort » : le mouvement ne dure que tant que le bouton est tenu ; il s'arrête si on lâche,
    si la connexion se coupe ou si la vidéo se fige ;
  - l'écran de l'armoire affiche « pilotage à distance en cours » ; une action sur place (Pause, arrêt) reprend
    toujours la main ;
  - chaque action à distance est notée dans le registre (qui, quand, quoi).
  La sécurité câblée (arrêt d'urgence, portes) reste au-dessus de tout et coupe aussi le pilotage à distance.
- **Mises à jour des cartes par le Pi** (pas de wifi sur les cartes) : le Pi met à jour les ESP32 par leur câble USB
  (programme FluidNC et ses réglages, programme du spray), seulement machine à l'arrêt, en gardant l'ancienne
  version pour revenir en arrière, et en vérifiant la carte après la mise à jour. Le RP2040 de l'accéléromètre
  est mis à jour par son fil série existant, rendu bidirectionnel sur un seul fil (half-duplex : PIO côté RP2040 ;
  côté Pi, TX par une résistance de 1 kΩ et RX sur le même fil), grâce à un chargeur série installé une fois à
  l'établi par USB. Pas de SWD (≈ 10 m de câble près des moteurs, plus de conducteur libre). Secours : USB-C,
  boîtier démonté. Câblage inchangé (4 conducteurs).
- **Mise à jour du programme du Pi lui-même** : depuis GitHub (versions acceptées sur `main`), machine à l'arrêt,
  retour possible à la version d'avant.

## Fonctionnalités

La liste des fonctions retenues, déjà faites ailleurs ou refusées est dans `docs/fonctionnalites.md`.

## Règles validées (modules figés)

Les chiffres ci-dessous vont dans `pi/reglages/machine.yaml`, jamais dans le code.

1. **Caméra du plafond** : 9 règles « situation → travail » validées (tableau à recopier ici quand la tâche Vision arrive). Le Pi PROPOSE le travail et attend le « Go » de Karulium. Repère ArUco 40 mm sur le plateau du rince-verre du lave-bocal. Corrections après essais réels.
2. **Caméra du dosage** sur servo DS3225 : 0° = bocal, 63° = seau. Photo du seau après chaque godet, avec sa dose. Elle pivote SEULEMENT si l'agitateur est garé (bocal x ≤ 0,62) ET si griffe et préhension sont hors de la zone x < 1,10, y < 0,34, z 0,95 à 1,08. Elle remonte avant le retour de l'agitateur ou du godet.
3. **Porte du spray ouverte** : portique arrêté, griffe interdite en x < 0,50 et y < 0,33, ozone et UV coupés.
4. **Reed du panneau du poste du fût** : production seulement contact fermé ; lavage seulement contact ouvert.
5. **Mycélium / Remplissage** : quand l'agitateur roule, le chariot de remplissage reste à y ≥ 0,375.

## État des modules (26/10/2026)

- **Figés** (on peut coder leurs gestes) : Poste du fût, Lavage, Griffe (Transfert), Porte-bocal, Mycélium, Guidage caméra, Préhension, écran Nextion.
- **Pas encore figés** (case vide seulement) : Remplissage, Stockage, Portique, Nettoyage, Spray, Micropore, Fermeture des seaux, Air comprimé, Entonnoir.
- Références encore à choisir : fins de course du Remplissage, microrupteurs du Stockage.
