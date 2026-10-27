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
  1. Ordinateur qui reçoit la copie de secours : **à confirmer par Karulium**. En attendant, `envois.secours.commande`
     reste vide (rien ne part, rien n'est perdu : les copies restent sur le SSD du Pi).
  2. Photos envoyées au logiciel de culture : décidé avec la tâche Vision (n° 22) ; pour l'instant seule leur
     description part avec le cycle.
  3. Dossier des photos envoyé chaque jour à la copie de secours : **oui** (`photos: true`).
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
