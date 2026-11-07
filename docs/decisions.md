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
- **Agitateur du mycélium FIXE à x 0,925** (choix de Karulium, 01/11/2026 ; vérifié sur la maquette v45.110,
  `maquette/agitateur-fixe-01-11/resultat.md`). La glissière de l'agitateur disparaît (rails, NEMA 17 et son
  driver, courroie, 2 fins de course, 2 câbles) : l'agitateur, son bocal et le porte-bocal restent toujours au-dessus
  du poste (x 0,925 ; y 0,150). Le module Mycélium est **rouvert** (support) : le logiciel attend sa nouvelle fiche
  avant de changer ses gestes. Règles déjà connues :
  1. La griffe **vide le seau à y 0,42** (chariot de remplissage à cy 0,285), plus au poste ; le seau vide attend à
     y 0,42.
  2. Au poste (y 0,135) : **manivelle en bas**, bord du seau **≤ 0,68 toujours** (Remplissage, règle C2 : à 0,70 ça
     touche, à 0,68 il reste plus de 2 cm). Spray : plateau ≤ min(0,50 ; 0,68 − h) au lieu de 0,71 − h.
  3. **Demi-tour du bocal seulement manivelle en haut et chariot à y ≥ 0,40.**
  4. La règle « l'agitateur roule » (verrou du chariot pendant que l'agitateur roule) est **supprimée** ; le garage
     à x 0,565 et le demi-tour à 0,865 aussi. La préhension pose et reprend le bocal en (0,925 ; 0,150), axes à 1,05
     et 1,10, chariot reculé ou au poste : aucun contact.
  6. Caméra du dosage (fil Guidage caméra, `guidage-camera/logiciel/pivot-camera-dosage.md`, 01/11 23:39 ; remplace
     sa première version « manivelle en haut seulement ») : le servo pivote le boîtier de 0° (bocal) à 63° (seau),
     volume balayé x 0,992-1,091, y 0,202-0,277, z 0,975-1,068.
     a) manivelle (haut, bas, à-coups), bocal (debout, tête en bas) et chariot de remplissage : **aucune condition** ;
     b) pivot **interdit pendant le demi-tour** du porte-bocal (du déverrouillage au contact « verrou engagé ») ;
     c) le demi-tour **ne démarre que boîtier à 0°** ;
     d) pivot interdit si une partie de la tête de la griffe ou de la préhension (ou de l'objet tenu) est dans
        **x < 1,10, y < 0,34, z 0,95-1,08** ;
     e) boîtier **remis à 0° avant toute pose ou reprise du bocal** par la préhension.
     La condition « agitateur garé » (`mycelium → camera_x_max`) disparaît. a) est confirmé par un balayage
     de la Maquette (02/11). Prendre la photo du seau **bras du spray rangé** (plan de commande v234).
  7. Fiche du Mycélium v10 (01/11) : bocal toujours en (0,925 ; 0,150), axe de la manivelle z 0,762, centre du bocal
     z 1,059 manivelle en haut. Manivelle EN HAUT pour la pose et la reprise du bocal et pour le demi-tour ; EN BAS
     dès que le chariot est au poste (attente). Préhension : face au contact de la capsule à 1,05, approche à 1,10,
     manivelle en haut, chariot reculé ou au poste. Retirés de la carte n° 3 : NEMA 17 de la glissière, son pilote,
     ses 2 fins de course. La griffe vide avec le mât en (0,925 ; 0,42).
  5. Conséquence : la table « Y minimum du mât » du 01/11 ci-dessous (faite avec l'agitateur garé à 0,565) est
     **périmée** ; une nouvelle table, agitateur fixe à 0,925, est demandée au projet mécanique. Les points 1 (essuyage),
     6 (boîtier de la caméra du dosage) et 7 (caméra du plafond) de cette section restent bons.
- **Agitateur fixe, réponses à la PR n° 64** (tâche 19 ter, 05/11/2026, niveau 1, fil logiciel) :
  1. Prise d'origine de la manivelle après une coupure, chariot de remplissage au poste : on garde la règle
     prudente (prise d'origine seulement chariot à y ≥ 0,40). Après une coupure, chariot au poste : l'écran dit de
     reculer le chariot à la main, puis on donne le Go. C'est rare, et on ne devine jamais la position de la
     manivelle.
  2. **Pose et reprise du bocal MANIVELLE EN BAS** (Maquette, 05/11, `mycelium/logiciel/hauteur-bocal-tete-en-bas.md`) :
     « manivelle en haut » dans la fiche v10 et dans la décision du 01/11 était une **erreur de recopie** (manivelle
     en haut, la capsule est à 1,147 : la face de la préhension, au plus à 1,10, ne l'atteint pas). La maquette a
     validé la pose manivelle en bas, chariot de remplissage reculé (y 0,40) **ou au poste** (y 0,135). On ne remonte
     pas la manivelle après la pose, sauf pour un demi-tour. Ordre : pose (manivelle en bas) → la tête s'en va →
     chariot à y ≥ 0,40 → manivelle en haut → demi-tour → manivelle en bas → dosage. Au retour : chariot à
     y ≥ 0,40 → manivelle en haut → bocal remis debout → manivelle en bas → reprise. Demi-tour inchangé (manivelle en
     haut, chariot à y ≥ 0,40, caméra à 0°, tête de préhension hors de la zone du point 3).
     Hauteur de contact de la capsule (fiche Mycélium v10b, 05/11, d'accord avec la maquette) : manivelle en bas, elle
     dépend du trou du maneton : **1,047 / 1,077 / 1,108 pour une course de 10 / 7 / 4 cm** (manivelle en haut :
     1,147, jamais atteinte). Réglage `prehension → porte_bocal → contact_capsule_z: {0.10: 1.047, 0.07: 1.077,
     0.04: 1.108}`, choisi avec `mycelium → course_agitation_m` (vérifié au démarrage : la course réglée doit être
     dans la table) ; arrêt sur le contact de la tête comme pour les autres prises. La face de la préhension monte au
     plus à 1,10 : approche à 1,10. **Course de 4 cm (contact 1,108) : pose impossible** ; le démarrage refuse une
     course dont le contact dépasse la face haute moins 1 cm. Réponse du fil Mycélium (05/11, niveau 1) : la course
     de 4 cm ne sert pas au cycle automatique (le trou reste dans la manivelle, le logiciel le refuse) ; **course par
     défaut 10 cm** (`mycelium → course_agitation_m: 0.10`, saisie par l'opérateur quand il change le maneton de
     trou ; la machine ne la détecte pas) ; 7 cm reste accepté.
  3. Hauteur du porte-bocal (Maquette, 05/11, v45.117) : **l'hypothèse « rien au-dessus de 1,05 » est fausse**.
     Plus haut point : 1,070 manivelle en bas, 1,170 manivelle en haut, **1,208 pendant le demi-tour** ; support fixe
     de la glissière verticale jusqu'à 1,167 (x 0,84-1,01, y −0,027-0,016) ; boîtier de la caméra du dosage jusqu'à
     1,065 (x 1,04-1,08, y 0,20-0,26). Règle : nouvelle zone `prehension → zone_porte_bocal: {x: [0.79, 1.08],
     y: [-0.03, 0.27], z_haut: 1.21}`. Tête plus objet tenu (rayon de la tête + 1 cm + rayon de l'objet) jamais dans
     ce rectangle plus bas que `z_haut` + la marge ; la face montant au plus à 1,10, les trajets le **contournent**.
     Seule exception : descente et remontée verticales en (0,925 ; 0,150) pour poser ou reprendre le bocal. Remplace
     la règle « au-dessus du bocal, plus bas que la capsule ».
  **Les points 2 et 3 sont à corriger dans la PR n° 64 elle-même** (session de correction, même branche). Tests à
  ajouter : pose manivelle en haut refusée ; pose chariot au poste acceptée (manivelle en bas) ; ordre complet d'un
  cycle dans le simulateur avec la pose en bas ; trajet en ligne droite à travers la zone refusé ; trajet qui la frôle
  à 1 cm près accepté.
  Réponses à la correction (06/11, niveau 1) : (a) en attendant la Maquette, on garde le seul trajet d'accès écrit
  par la session : en ligne droite d'un point hors de la zone à la verticale du bocal (ou retour), face en haut,
  manivelle arrêtée en bas. Un « couloir d'accès » (départ, direction, largeur, tête seule et avec bocal) est demandé
  à la Maquette le 06/11 ; il ira dans une tâche suivante comme réglage, tout autre trajet refusé. (b) Dans la zone
  du porte-bocal, on garde la **somme** rayon de la tête + 1 cm + rayon de l'objet (plus prudent).
  (c) **Couloir d'accès au bocal** (Maquette, 06/11, `mycelium/logiciel/acces-porte-bocal.md`) : un seul couloir,
     **côté allée** : départ en (0,925 ; 0,40), face à 1,10, trajet en −y jusqu'à y 0,150, puis descente jusqu'au
     contact de la capsule (et le même chemin au retour). Côté mur : moteur du demi-tour et support de la glissière ;
     côtés en x : plaques des mors et pièces en V : interdits. Largeur : tête seule x 0,925 ± 0,06 ; avec un bocal
     −0,06 / +0,04 jusqu'à l'entrée des mors (caméra du dosage côté +x), puis ± 0,005 dans le porte-bocal. Le
     chariot de remplissage ne gêne pas (au poste ou reculé). Réserve **levée** (fil Porte-bocal, CAO v10f, 06/11) :
     mors ouverts de 20 mm chacun (fin de course), le bocal passe capsule à 1,10 avec au moins 9 mm de jeu ; sur les
     **23 derniers mm de la descente** (capsule sous ≈ 1,07), il ne reste que 1,3 mm de jeu : bocal centré à
     **x ± 1 mm et y −1 / +2 mm**, descente verticale et lente. Ordre : mors ouverts (fin de course), couloir côté
     allée à 1,10, descente verticale centrée, serrage. Côté logiciel : tâche 36 bis, point 8.
- **Griffe : table « Y minimum du mât » avec l'agitateur fixe** (Maquette v45.111, 02/11/2026,
  `maquette/table-y-min-mat-griffe-v45.111.md` ; remplace les points 2 et 3 de la section du 01/11 ci-dessous).
  y du mât = repère du portique. Godet fermé / à moitié ouvert / grand ouvert, tête bras le long du pont. Bandes de x
  élargies d'1 cm de chaque côté par le fil logiciel (grille de 1 cm : à la limite, la plus stricte compte) :
  1. **Axes en butée haute** :
     - x 0,15-0,69 : 0 / 0,015 / 0,055 (rail du portique, coffret du spray) ;
     - x 0,68-0,78 : 0,015 / 0,075 / 0,10 (tube haut du support fixe de l'agitateur) ;
     - x 0,77-1,06 : 0,295 / 0,33 / 0,365 (porte-bocal et bocal) ;
     - x 1,05-1,12 : 0,215 / 0,225 / 0,26 ;
     - x 1,11-1,17 : 0,11 / 0,11 / 0,11 ;
     - x 1,16-1,22 : 0 / 0,015 / 0,055.
  2. **Axes sous la butée haute** (table calculée à 1,11 et 1,20, appliquée à toute hauteur sous la butée) :
     - x 0,77-0,99 : 0,325 / 0,335 / 0,37 ;
     - x 0,98-1,15 : 0,395 / 0,42 / 0,455 (caméra du dosage) ;
     - x 1,14-1,21 : 0,30 / 0,30 / 0,30 ;
     - x 1,20-1,22 : 0 / 0,015 / 0,055.
  3. **Mât à x < 0,78, axes entre 1,11 et la butée haute** (la tête passe dans l'ouverture du poste du fût) : permis
     seulement le mât à au plus **0,16 / 0,135 / 0,105** de l'axe du fût (cercle inscrit dans les zones libres de la
     Maquette, `w_free.json`). Ailleurs, interdit (la zone libre « y ≥ 0,955 » est hors de la course du mât, 0,83).
     Sous 1,11, ce sont les règles du fût (mât à 0,197 au plus, 0,17 côté −x). Exemple : x 0,50, y 0,60 à 1,15 :
     interdit.
  4. Tête tournée : comme avant (godet fermé, « fermé » + rayon balayé − demi-longueur fermé, ou rayon du cercle
     « fermé » moins la même différence ; godet ouvert, « grand ouvert »).
  5. Vidage : mât en (0,925 ; 0,42), hors de toutes ces limites. Essuyage du seau à y 0,42 (bord 0,78, axes au
     bord + 0,196) : côté allée godet fermé ou à moitié, bon pour les 4 formats (grand ouvert touche le moteur des
     barres). Côté +x serait possible maintenant ; on garde le côté allée (`direction_deg: 90`).
  6. Plus de bande « permise en butée haute » : le porte-bocal n'est plus à 0,565.
- **Griffe, réponses à la PR n° 74** (tâche 18 ter, 06/11/2026, niveau 1, fil logiciel) :
  1. Le cercle de l'ouverture du fût (`ouverture_fut`) vaut pour les axes **de 1,11 jusque sous la butée haute**
     (comme la table « sous la butée », valable de 1,11 à 1,20) ; en butée haute, c'est la table `butee_haute`.
  2. Les prises loin de l'axe (passe de fond, paroi à 0,197) passent par le centre : descente au centre, déplacement
     sur le côté dans le fût, retour au centre avant de remonter. On garde ; l'ouverture n'est pas agrandie.
  3. Partie étroite de la tête (≤ 0,117 le long des bras), réponse du fil Griffe (06/11, griffe.json) : godet
     FERMÉ, toute la tête (0,09 sous les axes : juste) ; godet GRAND OUVERT, seulement de +0,03 à −0,03 (0,127 à
     −0,045, 0,135 à −0,060, 0,148 à −0,075, 0,165 de −0,090 à −0,105). Donc 0,09 godet fermé, 0,03 godet ouvert.
     Vidage dans le seau du remplissage (mât (0,925 ; 0,42)) : **tête à A = 0 ou 180°** (17 à 23 mm de jeu avec le
     boîtier de la caméra du bocal) et **jamais de rotation godet ouvert au-dessus du seau** (à ±45° ou ±135°, godet
     ouvert, elle touche le boîtier pour les seaux A et D). `camera_bocal → bas_z_max` 1,07 : gardé.
  4. Rayons des cercles de prise 0 / 0,05 / 0,10 (choix du logiciel, EXEMPLE) : gardés jusqu'aux essais.
- **Griffe : essuyage et « Y minimum du mât »** (contrôle de la maquette v45.104 du projet mécanique, 01/11/2026 ;
  tranché par le fil logiciel, niveau 1) :
  1. Essuyage du bord du seau **côté allée confirmé** (`essuyage → direction_deg: 90`), mais **godet fermé ou à
     moitié ouvert, jamais grand ouvert** : grand ouvert, les coquilles touchent le moteur des barres du
     Remplissage (4 formats). On l'essuie **godet à moitié ouvert** (`essuyage → ouverture_godet: 0.5`), le plus
     proche du « godet ouvert dehors » de la fiche. Côté +x est impossible (caméra du dosage, même godet fermé).
  2. La table `garage_glissiere` est **remplacée** (agitateur garé à x 0,565 ; l'ancienne était faite avec le garage
     à 0,615). y minimum du mât, godet fermé / à moitié ouvert / grand ouvert, tête bras le long du pont :
     - x 0,15-0,395 : 0,00 / 0,05 / 0,07 (glissière du Mycélium) ;
     - x 0,395-0,44 : 0,20 / 0,215 / 0,25 ;
     - x 0,44-0,695 : 0,31 / 0,33 / 0,365 (bocal et porte-bocal de l'agitateur garé) ;
     - x 0,695-0,755 : 0,20 / 0,215 / 0,25 ;
     - x 0,755-0,78 : 0,11 / 0,11 / 0,11 ;
     - x 0,78-0,99 : 0,10 / 0,10 / 0,13 ;
     - x 0,99-1,145 : 0,395 / 0,42 / 0,455, **seulement sous la butée haute** (caméra du dosage : boîtier,
       profilé, câble HDMI ; en butée haute la tête passe au-dessus) ;
     - x 1,145-1,205 : 0,30 / 0,30 / 0,30 ;
     - x 1,205-1,22 : 0,00 / 0,015 / 0,055.
     La table a été calculée en butée haute (1,29) pour x < 0,78 et de 1,11 à 1,29 pour x ≥ 0,78. Choix : elle
     compte **à toute hauteur**, sauf la ligne x 0,99-1,145. La griffe ne descend sous la butée haute pour
     x < 0,78 qu'au lave-bocal (0,35 ; 0,65), loin de toutes ces valeurs. Tête tournée : la règle d'avant reste
     (godet fermé, « fermé » + rayon balayé − demi-longueur fermé ; godet ouvert, « grand ouvert »).
  3. **Fin de « permise en butée haute »** (réponse 3 de la PR n° 37 du 29/10) : la nouvelle table compte aussi en
     butée haute. La préhension au porte-bocal (mât de la griffe en 0,249 ; 0,150) reste permise (0,150 ≥ 0,07).
  4. Pas de verrou agitateur ↔ rince-verre (la tête au lave-bocal est loin de l'agitateur garé). Le logiciel n'en
     avait pas : rien à retirer.
  5. Limite connue : la table ne tient pas compte des pièces qui bougent (chariot de remplissage au poste, plateau
     au vidage) ; leurs règles restent celles de leurs modules.
  6. Plan de commande v230 (01/11/2026) : le boîtier de la caméra du dosage (« caméra du bocal » dans
     `griffe → camera_bocal`) est en PETG ; avec le balayage de son pivot, il occupe **x 0,997-1,091** et
     **z 0,975-1,068** (y 0,22-0,28 inchangé). Ces cotes remplacent x 1,045-1,085 et z 0,982-1,062 (`z_bas`,
     `z_haut`).
  7. Caméra du plafond : objectif en **(1,45 ; 0,545)** (`vision.yaml → cameras → plafond → position`, au lieu de
     0,50), toujours à ≈ 2,35 de haut.
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
- **Réponses aux questions de la PR n° 30** (tâche 20, Porte-bocal ; tranchées par le fil logiciel, niveau 1) :
  1. Photo de contrôle après le retour debout : le point d'appel reste où il est ; la tâche 22 (Vision) choisit la
     caméra. Le plan de commande demande un contrôle « quand le bocal revient debout, puis au garage » : si aucune
     caméra ne voit le bocal au demi-tour, le contrôle se fait au garage (la caméra du dosage peut alors pivoter).
  2. Sens du capteur d'inclinaison : `inclinaison_actionne: tete_en_bas` gardé, à vérifier au montage (étape 1 de
     l'essai) ; on change le réglage, pas le code.
  3. Redémarrage avec un bocal tête en bas : **les mors restent serrés hors tension** (projet mécanique, 29/10) :
     vis T8 gauche-droite au pas de 2 mm, inox avec écrous laiton, irréversible (hélice ≈ 4,5° sous l'angle de
     frottement ≈ 8 à 11°) ; le demi-tour (JGY370 à vis sans fin) est irréversible aussi. Ne pas confondre avec la
     T8 au pas de 8 mm du Remplissage. Au redémarrage, le Pi ne touche pas aux mors : il signale le bocal tête en
     bas et attend le Go de Karulium avant de le remettre debout. Le pas de 2 mm est un réglage
     (`fluidnc/`, pas par mm) : à vérifier au montage.
- **Origine de la manivelle** (projet mécanique, validé par Karulium le 29/10/2026, fiche des pièces v9) : le signal
  `origine_manivelle` est un capteur inductif M8 PNP sur la carte 3. Il voit du métal quand la manivelle **n'est pas**
  en haut (le contrepoids passe devant lui) et ne voit rien sur environ ± 95° autour du haut. Prise d'origine :
  un tour lent, noter la position du moteur au bord d'entrée et au bord de sortie de la zone sans métal, dans le
  même sens de rotation ; « manivelle en haut » = le milieu de cette zone, plus un décalage fixe (hystérésis du
  capteur) réglé une fois sur la machine (`machine.yaml`). Précision attendue ≈ 0,5°. À chaque prise d'origine, vérifier la
  largeur de la zone sans métal (≈ 190°, mesurée une fois sur la machine et enregistrée) : écart de plus de ± 10°,
  ou plus de 2 bords sur un tour → arrêt et alerte « capteur manivelle » (capteur déréglé, pièce desserrée ou
  métal étranger). La bielle reste à ≥ 14 mm du capteur (portée 1,5 à 2 mm) : pas de faux signal attendu. Les règles de mouvement ne
  changent pas (manivelle en haut au garage et pendant le roulage ; chariot de remplissage seulement agitateur
  au garage manivelle en haut, ou au dosage manivelle en bas).
- **Rails du portique HGR15** (Portique, validé le 29/10/2026) : mât de la griffe à **pont − 0,187** en x (− 0,175
  avant), mât de la préhension à **pont + 0,129** (+ 0,117 avant), butée du pont côté stockage à **2,495**. Les deux
  premiers chiffres sont dans `pi/reglages/machine.yaml` ; celui de la préhension y ira avec sa tâche.
- **Cartes de pesée RS485** (réponses à la PR n° 33, tâche 22 bis, 29/10/2026) :
  1. Pas de mise à jour des cartes de pesée par le bus pour l'instant : elle se fait par le câble USB-C de la
     carte. Le boîtier de chaque carte (griffe, préhension, plateau) doit laisser la prise USB-C accessible sans
     démonter la tête. Si une carte se révèle difficile d'accès au montage, on ajoutera une tâche « 22 ter » qui
     reprend le chargeur de l'accéléromètre (tâche 16).
  2. Carte **Waveshare RP2040-Zero** (comme l'accéléromètre) et module RS485 **en 3,3 V** avec broche DE/RE
     (MAX3485 ou SP3485) ; jamais un MAX485 en 5 V ni un module à sens automatique. Résistance de 120 Ω à chaque
     bout du bus, 0 V commun dans le câble. Les broches de `pi/reglages/pesees.yaml` passent à la RP2040-Zero au
     montage (exemples d'ici là).
  3. Cartes HX711 à **80 mesures/s** : broche RATE accessible (pont « RATE » type SparkFun) ou piste à couper ;
     contrôle à l'étape 4 de `pesee/essai-etabli.md`.
- **Préhension** (réponses à la PR n° 34, tâche 37, 29/10/2026) :
  1. Isolation du fût et porte-bocal (réponse du projet mécanique, Préhension, 29/10/2026) : le bocal au garage
     est en **x 0,565, y 0,150** (et non 0,155), au-dessus de la marche, hors de l'enceinte du fût ; capsule à
     1,1325 manivelle en haut, ≈ 1,0625 manivelle en bas (course 7 cm). La règle « face à 1,10 sous x 0,71 » ne
     s'applique pas dans une **petite zone** autour du garage : axe de la tête à x 0,565 ± 5 mm et y 0,150 ± 5 mm
     (pas tout y < 0,215 : entre y 0,16 et 0,215 la tête toucherait la paroi haute). Dans cette zone, la tête
     arrive à 1,10 et descend à la verticale, seulement si : (a) agitateur au garage **manivelle en bas** (course
     déclarée 7 cm) ; (b) mors ouverts pour poser, serrés pour prendre ; (c) griffe en butée haute. Manivelle en
     haut, la capsule (1,1325) dépasse la butée haute de la tête (1,10) : la tête ne passe jamais au-dessus du
     bocal au garage dans ce cas.
  2. Boîtier de la caméra du bocal : on garde le calcul depuis la boîte de `machine.yaml` (x 1,045-1,085,
     bord limité à 1,085 par la raclette de la griffe dans le plan de commande), soit x 0,99-1,14. Le « 1,16 » de
     la fiche venait d'un boîtier plus large.
  3. Griffe et préhension sur le même pont (réponse du projet mécanique, 29/10/2026) : quand la préhension est
     au porte-bocal, le mât de la griffe est en x 0,249, y 0,150. Pas de collision si la griffe est **en butée
     haute** (bas du godet à 1,087 ; rien du Mycélium ne dépasse 1,0 sous son encombrement, la paroi haute et le
     volet sont dessous). La bande x 0,15-0,43 sous y 0,23 (`garage_glissiere`) reste interdite à la griffe,
     **sauf en butée haute**.
  Réponse à la PR n° 37 (tâche 37 bis, 29/10/2026) : manivelle en haut, la capsule du bocal est à 1,1325 partout le
  long de la glissière, plus haut que la butée haute de la tête (1,10). L'interdiction « pas de tête au-dessus du
  bocal manivelle pas en bas » **suit la position de l'agitateur** (bocal en x = position de l'agitateur, y 0,150),
  pas seulement au garage (tâche 37 ter). Sans information sur l'agitateur, toute la glissière est interdite.
  4. Mode manuel : la décision de la PR n° 14 reste (le pilotage à distance « en cas de problème » ne vérifie pas
     les règles), **sauf** le verrou du noyau et de la couronne du lavage (jamais de rotation sans objet tenu),
     qui sera appliqué aussi en pilotage à distance (tâche 21). `refus_manuel()` servira au mode guidé (tâche 32).
  5. Capteur de vide 3,3 V : sa conversion (2 points tension → kPa) est relevée sur la notice du capteur acheté
     ou mesurée à l'étape 2 de l'essai ; c'est un réglage.
- **Lavage des seaux** (réponses à la PR n° 36, tâche 21, 29/10/2026) :
  1. Centre du fût de lavage (x 0,35) hors de portée de 2 mm (tête à x ≥ 0,352, rails HGR15, tête gelée) : on
     garde x 0,352. Le Lavage confirme (29/10) : 2 mm sans effet ; le fût et la buse ne bougent pas. Couvercle B
     et seau C : (0,352 ; 0,65).
  2. Jet d'air et chauffage sur la carte 4 (la carte 3 n'a plus de sortie libre) : d'accord ; transmis au plan
     de câblage. Le code ne connaît que les noms.
     **Remplacé** le 07/11/2026 (tâche 45 duodecies) : jet d'air sur la carte n° 3, chauffage sur un relais du Pi.
  3. Chauffage entre deux seaux : après la pompe qui suit le rinçage, le Pi remet quelques secondes d'eau du
     réseau jusqu'au flotteur haut (délai maximal : réglage), pour que le bain reste chauffé. La règle « chauffer
     seulement flotteur haut et pompe arrêtée » ne change pas.
  4. Rotation de la tête (réponse de la Préhension, 29/10/2026) : la limite de conception est ± 1,5 tour (± 540°,
     cordon spiralé CDC-CORDON, seul passage du vide et des fils). Le logiciel monte à **± 500°** (40° de marge,
     ≈ 2,8 tours par aller-retour), retour à 0 sur le capteur d'origine à chaque fin de passe, jamais deux passes
     de suite dans le même sens. À confirmer à la mise en service avec le cordon reçu ; s'il force, retour à ± 370°.
  5. Passe 2 (réponse du Lavage, 29/10/2026) : **pas de remontée** (0 pour tous les formats). Le seau reste posé
     sur son bord (appuis à 0,370) pendant tout le lavage ; les brosses extérieures frottent paroi et bord en même
     temps. Les phases des passes peuvent rester séparées ou être fusionnées en une seule rotation, seau posé. Le
     seau ne remonte qu'à la fin, pour le jet d'air. (Le texte « brosse de fond tenue par la tête » du plan de
     commande est antérieur à la version gelée.)
  6. Vanne à bille ouverte pendant la série : oui, **à condition** que la vanne 3 voies revienne sur « rampes »
     dès que la pompe s'arrête (pas de siphon vers la bonde). Pompe arrêtée, si le flotteur retombe sans
     vidange demandée : alerte « fuite ou siphon », vanne à bille fermée.
  7. Jet d'air du col (réponse du Lavage, 29/10/2026) : x reste à 0,352 et le seau est décalé en −y pour retrouver
     la distance du dessin entre le centre du seau et le bout de la buse (0,2509 ; 0,5084). **Centres du seau** :
     A (0,352 ; 0,6348), B (0,352 ; 0,6270), C (0,352 ; 0,650), D (0,352 ; 0,6385) ; bords inchangés (0,711 /
     0,698 / 0,714 / 0,712). Jeu ≥ 26 mm avec l'anneau de rive. Réglages par format (centre x, y), ajustés à
     l'essai. La règle « x ≥ 0,340 » de la fiche du jet d'air est périmée.
- **Couvercles et bocaux au lavage** (réponses à la PR n° 38, tâche 21 bis, 30/10/2026) :
  1. Décalage du couvercle (A 21 mm, B 0, C 21, D 23) fait **avant** la descente, gardé pendant les 5 s du noyau :
     la règle de la préhension (pas de pont tête basse) reste sans exception. Même position que la fiche.
  2. Face « dessus » (repère caché) : pas d'orientation ni de contrôle de glissement, vide surveillé ; hauteur
     d'appui `bas_dessus_z` mesurée à l'essai (étape 6).
  3. Couvercles : bain par les rampes pendant le brossage **et rinçage propre** à la fin de chaque face, comme pour
     les seaux (tâche 37 ter).
  4. Barrière lumineuse à 0,7315 : câblée avec les barres, dans le Remplissage (tâche 34).
  5. Retour à 0 de la rotation : pas de relecture du capteur d'origine à chaque passe pour l'instant ; à ajouter si
     la mise en service montre une dérive.
  6. Hauteur du lâcher au-dessus de la tige et contact dans le bac : EXEMPLES (0,78 et 0,49), mesurés à l'essai.
- **Vision de base** (réponses à la PR n° 41, tâche 22, 30/10/2026) :
  1. Règle 4 du plafond : tout fût plein que les règles 2 et 3 n'ont pas pris donne l'alerte « rien à remplir »
     (jamais d'attente silencieuse, la fiabilité d'abord).
  2. Contrôle du lave-bocal par le plafond : **désactivé** (`controle_lave_bocal: false`) jusqu'à ce que la
     reconnaissance du fût vide marche (tâche 22 ter). Ensuite : une photo pont garé **au début de chaque série** de
     seaux, et à nouveau **après toute pause, porte ouverte ou arrêt** (quelqu'un a pu intervenir), en plus de la
     confirmation à l'écran ; pas de garage du pont avant chaque seau.
  3. Servo de la caméra du dosage sur la sortie PWM matérielle du Pi (**GPIO 18**), servo alimenté à part (5 à
     6,8 V, régulateur de la fiche), 0 V commun ; signal en paire torsadée avec le 0 V. Transmis au plan de câblage.
- **Remplissage** (réponses à la PR n° 43, tâche 34, 30/10/2026) :
  1. Dosage à y 0,155, plateau haut : **permis**. C'est la règle 11 du fichier des positions, vérifiée sur volumes
     réels par le fil Mycélium (24/10). La zone libre du poste va de y 0,13 à 0,16, comme dans la PR.
  2. et 3. **Pas de poussée en bande du haut** (réponse du fil Remplissage, 30/10) : la tête du micropore est montée
     SUR le chariot, donc au-dessus du plateau à toutes les places en y. Le pousseur ne sort que **plateau ≤ 0,20**
     (règle 9), partout. Les valeurs « 0,4985 » et « lot C, y 0,205 » ne viennent pas de la fiche Remplissage : on
     les retire. Les règles s'additionnent, la plus stricte s'applique. Un arrêt à y 0,205 reste permis pousseur
     rentré. Les places des files viennent du Stockage (tâche 35).
  4. **Pousseur (correction d'une erreur de recopie, confirmé par le fil Remplissage)** : son zéro est le fin de
     course **en bout de rail côté fût**, et c'est la position « rentré ». Il pousse **toujours vers le stockage**,
     course 0,325 : la palette va de −0,165 (rentré) à +0,16 de l'axe du plateau. Il n'est pas rentré « au milieu ».
  5. **Ordre de la pose et de la prise double** (fil Remplissage, corrigé le 30/10 au soir après les questions de la
     PR n° 45 ; remplace l'ordre de la page Barres séparatrices v4, qui faisait descendre la tête avec le plateau
     collé au seau). Les barres ne traversent la zone hw 0,235-0,255 que plateau ≤ 0,48, dans les deux sens.
     - Pose simple : 1) plateau ≤ 0,48, barres à l'approche hw 0,225 ; 2) le plateau monte jusqu'au contact (balance),
       B ≈ 0,5125 ; 3) centrage : les barres serrent sur le seau (en position, point 6) ; 4) faisceau libre = seau
       seul, coupé = prise double. Les barres ne se rouvrent au-delà de 0,235 qu'après la descente du plateau ≤ 0,48.
     - Prise double (barres déjà serrées, centrage fait ; contact Hc ≈ 3 cm plus bas qu'un seau seul, B ≈ 0,4825) :
       a) lâcher (+1,5 cm par barre) ; b) le plateau descend de 5 cm (Hc − 0,05) ; c) la tête descend de 2,8 cm (lèvre
       du seau du dessous au niveau de la rainure des barres) ; d) les barres serrent sur la lèvre (entraxe = Ø haut
       + 6 mm) ; e) le plateau monte jusqu'au contact du fond (≈ Hc − 0,028) ; f) la tête remonte avec le seau du haut
       (≤ 35 N par barre, sinon alarme) ; g) lâcher ; h) le plateau monte de 2,8 cm ; i) contrôle : faisceau libre et
       un seul seau sur la balance, sinon alarme ; puis centrage et suite comme un seau seul. Pendant toute la prise
       double, hw reste sous 0,235 : aucune traversée de la zone. Courses en réglages, à vérifier sur la maquette.
     - Réponses à la PR n° 45 : (1) la prise double d'un seau B n'est plus bloquée, puisque les barres traversent la
       zone avant la pose ; (2) oui, au départ de la prise double les barres sont déjà serrées (c'est pourquoi le
       premier geste est « lâcher »). À faire dans la tâche 34 ter.
  6. **Pas de courant réduit** (réponse du fil Implantation, 30/10) : le pilote boucle fermée de tous les axes
     (CL57T V4.1 ou équivalent) n'a que PUL, DIR, ENA et une sortie d'alarme ALM ; le courant se règle une fois pour
     toutes. Le centrage se fait donc **en position** (`centrage_hw_m` du format + un petit jeu en réglage). La
     sortie « courant réduit » est retirée. Si les barres forcent trop, le pilote lève **ALM** : le Pi la lit (comme
     les autres alarmes de pilote) pour arrêter le geste et alerter.
  7. Hauteurs de pose des seaux A, C et D : exemples, mesurées à l'essai (étape 3 de la procédure).
  8. **Bout du chariot côté allée : 0,40 de l'axe du plateau** (fil Remplissage ; point le plus loin 0,396, renvoi
     d'angle et moteur de montée). Chariot du fût absent : axe du plateau à y ≤ 0,875 − 0,40 = **0,475**. Cette règle
     est plus stricte que « poste ou files 1 et 2 » : elle gagne (une file au-delà est refusée tant que le chariot du
     fût n'est pas en place).
  9. Retourneur des couvercles : **oui, c'est une exception** à la règle 9 (descente de la préhension barres
     ouvertes). Elle a été vérifiée par le fil Lavage le 25/10 (aucun contact, plateau 0,459, barres 0,19 à 0,30).
     Dans tous les autres cas, la règle 9 est branchée dans la préhension (tâche 34 bis).
  10. **Capteurs d'origine (correction d'une erreur de recopie, fiche du 28/10)** : la fiche a aussi un **fin de
      course bas de la montée** (zéro de la montée, plateau en bas), un fin de course de l'avance (contre le tampon
      côté mur), un fin de course du pousseur (côté fût) et un **capteur Hall du zéro de rotation** (un aimant passe
      une fois par tour). La prise d'origine de la montée se fait donc **vers le bas**, sans danger. Le fin de course
      haut reste une butée de sécurité (il coupe vers 0,578). Il n'y a plus de condition sur l'agitateur pour la prise
      d'origine.
  11. **Moteurs (correction d'une erreur de recopie, fiche du 28/10)** : l'avance, la rotation et les barres ont un
      seul modèle, un NEMA 17 boucle fermée (17HS19-2004-ME1K ou équivalent). La rotation est **sans réducteur** :
      pignon 15 dents sur une roue de 120 dents, **rapport 8** (et non 40). Montée et pousseur : NEMA 23 boucle fermée
      à frein.
- **Remplissage, changements du 31/10/2026** (fil Remplissage, décisions de Karulium sur les pièces introuvables,
  « se baser sur du standard ») :
  1. **Deux barres, deux vis, deux moteurs** : la vis à deux sens n'existe pas en standard. Chaque barre a sa vis T8
     simple, son NEMA 17 boucle fermée (pilote avec ALM) et son fin de course d'origine, montés en miroir. Le Pi
     commande les 2 moteurs **ensemble** (mêmes pas, sens inversé) pour garder le seau centré. Zéro de chaque barre
     sur son fin de course : côté mur hw ≈ 0,309, côté allée hw ≈ 0,306 (décalages réglés dans le Pi). Les règles 2,
     3, 4 et 8 valent pour chaque barre ; l'effort (≈ 30 N au centrage, 35 N à la séparation) et l'alarme ALM se
     surveillent **barre par barre**.
  2. **Agitateur du Mycélium** : il ne roule entre son garage et le dosage que si le chariot est à **y ≥ 0,40** (le
     moteur de la barre côté mur touche un support SK12 à 0,375). L'ordre pour un seau devient : poste → recul à
     y 0,40 → agitateur au dosage → poste → dosage → recul à y 0,40 → agitateur au garage → poste.
  3. **Fin de course haut de la montée : en série dans l'arrêt** (câblé en dur, comme une sécurité de la machine). Ce
     n'est plus une entrée de la carte : le Pi ne le lit pas. La butée logicielle à 0,575 reste.
  4. Câbles capteurs (bornier du boîtier) : câble 1 = 24 V, 0 V, avance, montée bas, barre mur, barre allée, et les
     2 fils du fin de course haut ; câble 2 = 24 V, 0 V, Hall, pousseur, RS485 A et B, barrière, 1 fil libre.
  5. La règle 7 ne change pas (bout côté allée à 0,40 de l'axe du plateau).
- **Remplissage, réponses à la PR n° 46** (tâche 34 ter, 31/10/2026) : (1) après la pose d'un seau seul, les barres
  reviennent à l'approche (0,225) quand la tête est partie, le plateau oriente l'anse, puis « centrer » serre : **gardé**
  (les oreilles de l'anse ne frottent pas pendant la rotation). (2) Montée lente avant le contact : on garde les
  réglages actuels ; `plateau_sous_pose_m` et la vitesse `contact` se règlent sur la maquette.
- **Pousseur côté allée et bande du haut** (Karulium 31/10/2026 15:37 ; fils Remplissage et Stockage, règles 12 et 13 de
  `remplissage/fiche/regles-positions.md`, section 1.3 de `stockage/logiciel/stockage-pour-logiciel.md`) :
  1. Le pousseur est monté en miroir côté allée (même course 0,325, même zéro côté fût, même sens vers le stockage ;
     palette de x −0,12 à +0,20 par rapport à l'axe du plateau). Il ne passe plus sous la tête du micropore.
  2. Règle 9 : il ne reste que « plateau ≤ 0,575 ». **« Pousseur rentré au-dessus de 0,20 » est supprimé.**
  3. Règle 12 : poussée permise **à toute hauteur** du plateau, barres **ouvertes** (hw ≥ 0,29) et bras de fermeture
     **rangé** ; plusieurs seaux peuvent être poussés à la suite.
  4. **L'ancienne règle des anneaux du fût est périmée et supprimée** (plateau ≤ 0,18 en y 0,14-0,41 et 0,59-0,86 :
     note de la maquette v3.13). Une tôle fixe à x 0,655 sépare le fût du chariot ; vérifié fût présent ou absent,
     panneau levé ou rabattu. Ce qui reste : bras rangé, barres ouvertes, plateau ≤ 0,575, et l'agitateur du
     Mycélium immobile tant que le chariot est sous y 0,40.
  5. **Bande du haut** (plateau du Stockage, y 0,215) : plateau du chariot à **0,4985** (plage 0,496-0,501 : jamais plus
     bas que la tôle à 0,496, au plus 5 mm plus haut). Ordre : a) seau fermé, bras rangé ; b) barres ouvertes (elles
     traversent 0,235-0,255 plateau ≤ 0,48) ; c) chariot à y 0,215 ; d) plateau à 0,4985 ; e) poussée ; f) pousseur
     rentré, plateau redescendu. Entrée au bord de P1, x 1,155 ; pas de butée : fin de course logicielle, bord du
     couvercle à x ≤ 2,44 (jamais sur le hublot). Places : A 4 (centres 2,30 / 2,028 / 1,756 / 1,484), B 5 (pas 0,235,
     de 2,32 à 1,38), C 4 (pas 0,30, de 2,28 à 1,38), D 4 (pas 0,28, de 2,30 à 1,46) ; pas réel = contact des rebords,
     recalé à la caméra. Pas de guidage en y : photo du plafond après chaque poussée, y 0,215 ± 0,007, sinon arrêt et
     alerte. Fin de lot : le tiroir d'abord ; les piles de fin de lot de la bande sont vidées en premier pour la
     libérer. **Capacité d'un lot : A 18, B 20, C 16, D 18** (corrigée le 01/11, voir « Stockage, réponses à la PR
     n° 52 » ; D : une pile de fin de lot de 3 sur la bande).
- **Mode couvercles, règle 14 du chariot** (fil Remplissage, contrôle de la maquette v45.98, 31/10/2026) :
  14. Pendant les deux demi-tours de la tête de la griffe (axe y 0,68, axes à 1,075), le chariot est à **y ≥ 0,515** ;
      il ne revient à y 0,50 qu'après (sinon la raclette touche le moteur de la barre côté allée). Contrôlé sur la
      maquette v45.99.
  15. **Retirée** (31/10, 17:12) : la maquette avait dessiné le bac du retourneur en double ; le vrai bac est posé sur le
      plateau et le suit, donc aucune condition.
- **Stockage, réponses à la PR n° 52** (tâche 35, fil Stockage, 01/11/2026 ; détail dans
  `stockage/logiciel/stockage-pour-logiciel.md`) :
  1. **Rail opérateur** : c'est le rail X du portique côté allée (axe y 1,10, sur toute la longueur du stockage). Son
     chariot suit le pont (même x que la préhension) et occupe y 1,005 à 1,135 au-dessus de z 1,11. Règle exacte : si
     le haut du seau tenu dépasse 1,11, il faut **axe y + rayon du bord ≤ 0,995** ; sinon haut ≤ 1,10. Rangée y 0,84 :
     0,84 + 0,15 = 0,99, donc limite 1,155 au-dessus de ces piles pour tous les formats. La règle « y > 0,82 » est
     remplacée. (La tête de préhension, rayon 0,045, ne dépasse jamais le bord d'un seau vers +y.)
  2. **Butée du tiroir : face d'appui à x 2,582** (et non 2,612 ; barre 2,582-2,612), longueur utile 1,482. Seau C :
     **4 par file**, 12 en bas (pas de quinconce) : files y 0,215 et 0,785 centres 2,432 / 2,132 / 1,832 / 1,532 ; file
     y 0,50 centres 2,282 / 1,982 / 1,682 / 1,382, avec la cale de 15 cm posée par l'opérateur contre la butée (course
     du pousseur de cette file plus courte de 0,15). Les x de A, B et D sont dans le fichier source.
     **Capacités d'un lot corrigées : A 18 (14 + 4), B 20 (15 + 5), C 16 (12 + 4), D 18 (14 + 4).**
  3. **Coin d'inspection** (places [rangée j, rang i] du quinconce) : suspects [8,8] [8,9] [8,10] [7,7] [7,8] [7,9]
     [6,8] [6,9] [6,10] ; séparation [5,7] [5,8] [5,9] [6,7] [7,6] [8,7] (côté x grand, et non x petit).
  4. Places de fin de lot : bord de la 1re pile à x 1,165 (1 cm du bord de P1) : **gardé**.
  5. Les 18 bocaux de semence (3 × 6) font partie du **mode seaux** (un bocal par seau) : ils partagent le plateau
     avec les piles de vides, la bande des pleins et les boîtes, jamais avec le quinconce de 95 (mode bocaux).
- **Bande du haut, réponses à la PR n° 54** (tâche 35 bis, 01/11/2026) :
  1. Seau B au tiroir : **5 + 5 + 5** (centres 2,467 / 2,232 / 1,997 / 1,762 / 1,527, sans exclusion) : juste, d'après
     le fichier du fil Stockage.
  2. Diamètres des couvercles (fichier du fil Stockage) : **A 0,28, B 0,23, C 0,315, D 0,28**. Avec eux, toutes les
     places de la bande du haut gardent le bord à x ≤ 2,44 (D : 2,30 + 0,14 = 2,44 ; C : 2,28 + 0,1575 = 2,4375). Le
     contrôle au démarrage utilisera le diamètre du couvercle (à ajouter à la table des formats avec la tâche 41,
     Fermeture des seaux, qui s'occupe des couvercles).
  3. Photo de contrôle de la bande du haut : le faux « bien placé » reste tant que les réglages sont en
     `exemple: true` (on regarde à l'œil pendant les essais) ; la vraie lecture vient avec la tâche 22 ter.
- **Stockage agrandi de 43 cm** (validé par Karulium le 04/11/2026, 17:58 ; fil Stockage,
  `stockage/logiciel/stockage-pour-logiciel.md` (encadré du début) et `places-agrandi-43.md`). Le stockage commence
  toujours à x 1,10 ; tout ce qui était au bout avance de +0,43.
  1. Plateau du haut : **3 panneaux** P1 x 1,155-1,770, P2 1,7825-2,3975, P3 2,410-3,025 ; microrupteurs à x 1,510 /
     2,1375 / 2,765 ; **4 contacts en série** (tiroir + 3 panneaux) sur une seule entrée. Tapis jusqu'à x 2,8585.
  2. Tiroir : tôle x 1,10-3,04, **butée (face d'appui) x 3,012**. Places (centres x) :
     - A : file 0,215 : 2,6065 / 2,3345 / 2,0625 / 1,7905 / 1,5185 / 1,2465 (place 2,8785 vide, sous la caméra du
       fond) ; files 0,50 et 0,785 : 2,8785 / 2,6065 / 2,3345 / 2,0625 / 1,7905 / 1,5185 / 1,2465 ;
     - B : les 3 files : 2,897 / 2,662 / 2,427 / 2,192 / 1,957 / 1,722 / 1,487 (7 par file) ;
     - C : files 0,215 et 0,785 : 2,862 / 2,562 / 2,262 / 1,962 / 1,662 / 1,362 ; file 0,50 (cale de 15 cm) :
       2,712 / 2,412 / 2,112 / 1,812 / 1,512 ;
     - D : file 0,215 : 2,592 / 2,312 / 2,032 / 1,752 / 1,472 (place 2,872 vide) ; files 0,50 et 0,785 : 2,872 /
       2,592 / 2,312 / 2,032 / 1,752 / 1,472.
  3. Bande du haut (y 0,215), **bord du couvercle ≤ 2,87** (hublot x 2,88-2,98) : A 2,73 / 2,458 / 2,186 / 1,914 /
     1,642 / 1,37 ; B 2,755 / 2,52 / 2,285 / 2,05 / 1,815 / 1,58 / 1,345 ; C 2,7125 / 2,4125 / 2,1125 / 1,8125 /
     1,5125 ; D 2,73 / 2,45 / 2,17 / 1,89 / 1,61 / 1,33.
  4. Capacité d'un lot : **A 26, B 28, C 22, D 23** (tiroir + bande du haut).
  5. Bocaux : rangées paires **14** (x 1,2075 → 2,6375), impaires **13** (x 1,2625 → 2,5825) : **122 places**. Coin des
     suspects (fil logiciel, accepté par le Stockage) : même forme, 3 places vers le bout : suspects [8,11] [8,12]
     [8,13] [7,10] [7,11] [7,12] [6,11] [6,12] [6,13] ; séparation [5,10] [5,11] [5,12] [6,10] [7,9] [8,10].
  6. Boîtes à capsules en **(2,95 ; 0,53)** et **(2,95 ; 0,80)** ; hublot en **(2,93 ; 0,22)**, boîtier x 2,87-2,99.
     Mât de la griffe à x ≤ 2,738 (Portique). Piles de vides, couvercles, semence, caméra du bocal : inchangés.
- **Portique, réponses à la PR n° 56** (tâche 36, 03/11/2026 ; fils Lavage, Remplissage, Portique, Griffe) :
  1. Lavage : **12 mm ne conviennent pas** (fil Lavage) : la tête doit être au centre du fût de lavage à ± 2 mm
     (brosses coaxiales au seau ; à 12 mm, le seau B n'est plus brossé d'un côté et le seau C bloque). C'est un
     choix mécanique (déplacer le poste de +12 mm, ou regagner 10 mm au Portique et à la Préhension), remonté par le
     fil Lavage. En attendant : places du lavage **relatives au centre du fût de lavage** (seau posé centré ; jet
     d'air A (+2 ; −15,2), B (+2 ; −23), C (+2 ; 0), D (+2 ; −11,5) en mm). Le 0,362 de la PR reste provisoire : le
     lavage n'est pas utilisable tant que ce point n'est pas réglé.
  2. Prise double (fil Remplissage, avec la Préhension, 03/11) : hauteurs de pose **vraies** (dessus du plateau),
     H = 0,6875 − (h − col) : **A 0,4675, B 0,5125, C 0,4925, D 0,4625** ; face de la ventouse à la pose = H + 0,003.
     L'étape c) met la face à H − 0,025, jamais sous 0,45 : B et C passent, **A et D non**. Règle : prise double
     d'un seau **A ou D** → la préhension repose les 2 seaux emboîtés sur une place libre et refait le dégerbage,
     **sans séparation sur le chariot** ; B et C gardent l'ordre a) à i). Pas de course en plus (la Préhension :
     changer rail, crémaillère et chaîne Z).
  3. « Au bout côté fût » (fil Portique) : règle à part de celle de x 2,0. **Pont entre 0,233 et 0,30 et axes de la
     tête sous 1,05 : tête à A = 180° seulement** (réponse du fil Portique : à 0° la raclette, à ± 90° les bras,
     en biais jusqu'à 0,143, touchent la traverse ; à 180° il reste 15 mm). Hors de là, rotation libre (règle des axes ≤ 1,075 godet ouvert, ≤ 1,11 fermé). Au-delà
     de x 2,0 : pas de rotation, **sans** limite d'angle (le « 0° ou 180° seulement » de la PR est retiré).
  4. Origines A et B de la griffe (fil Griffe, niveau 1) : 2 capteurs (voir point 7). **B** : origine
     « fermé nominal », recherche 2 mm vers l'ouvert puis **vers fermé**, lente, à courant réduit (jamais ouvrir :
     le godet peut être plein) ; butées logicielles 0 à +36 mm ; blocage avant l'interrupteur : arrêt, alarme
     « godet bloqué, vider au-dessus d'un seau ». **A** : fanion de 180° (actionné de −180° à 0°, libre de 0° à
     +180°), approche finale toujours en +, recherche limitée à 190°, jamais au-delà de ± 180° ; godet fermé ;
     axes ≤ 1,11. Ordre : portique (Z, Y, X), puis B (Z en haut), puis aller au point de recherche de A, tête à un
     angle de bras « le long d'un axe », descendre, puis A. Si la dernière position connue de A n'était pas un de
     ces angles (coupure pendant une rotation en bas) : ne pas monter Z, alarme, tête remise à la main. Point de
     recherche (réponse du fil Griffe, 03/11) : **(0,86 ; 0,57), axes 1,075, godet fermé** (aussi pour tous les
     demi-tours de la griffe hors du fût) ; le point (0,708 ; 0,74) est abandonné (interdit par la table v45.111).
     Repère des angles : celui du logiciel (A = 0 bras le long du pont, raclette vers −x) ; origine de A = 0. Entrées : à confirmer après la validation du matériel (`exemple: true`).
  5. Garage du chariot : **centre du chariot à 0,50** (mâts à 0,46), comme dans la PR.
  6. **Décision de Karulium (03/11, 22:50)** : le pont va jusqu'à **x ≥ 0,223** (butée logicielle, limite accordée le
     08/10), au lieu de 0,233. La tête de préhension atteint ainsi **x 0,352**, dans l'axe des brosses du Lavage :
     le point 1 est réglé, places du lavage à nouveau à 0,352 (et relatives au centre du fût de lavage). Le poste
     du fût ne bouge pas, aucune pièce ne change. Fins de course X placés au montage pour déclencher vers 0,20,
     avant la butée mécanique (≈ 0,12). La Maquette a vérifié la griffe à cette limite : aucun contact.
     Bout côté fût (fil Portique, 03/11) : **pont sous 0,233 → axes de la griffe ≥ 1,05 obligatoires** (à 180° il ne
     resterait que 5 mm devant la traverse basse) ; de 0,233 à 0,30, axes sous 1,05 : A = 180° seulement (point 3).
  7. Correction du fil Griffe (03/11) : les origines A et B sont **2 capteurs inductifs M12, portée 4 mm, PNP, NO**,
     10-30 V sur le +24 V du câble, signal à +24 V quand ils voient le métal (2 entrées 24 V actives hautes) :
     B actif quand la fourchette arrive à « fermé » ; A actif quand il voit le fanion (A de −180° à 0°). Le principe
     et les sens ne changent pas. **Validé par Karulium le 05/11 (01:22)** ; numéros des entrées à choisir avec
     l'Implantation. La Maquette confirme le point (0,86 ; 0,57) sur la v45.112 (un tour complet libre).
  8. **Préhension +22 cm** (validée par Karulium le 04/11, 17:59) : mât et colonne allongés de 22 cm, plaque Z de la
     préhension de **2,178 à 1,308 (course 0,870)** ; face de la ventouse de **1,10 à 0,23** (0,21 au tout bout du
     rail). Nouvelle règle (Portique) : plaque Z de la préhension **au-dessus de z 2,02 → mât de la préhension à
     y ≤ 0,80** (sinon le brin de la chaîne Z touche le plénum du Nettoyage). Conséquence (fil Remplissage) : la
     prise double se fait de nouveau **sur le chariot pour les 4 formats** (ordre a) à i)) ; la règle « A et D :
     reposer les 2 seaux et refaire le dégerbage » du point 2 est **retirée**.
     Préhension (05/11) : la lèvre va de 0,21 à 1,10 ; on garde **0,23** comme bas de course (0,21 = tout bout du
     rail, sur la butée). Le mât est plus souple en travers (≈ 4 mm pour 20 N) : **accélérations et freinages plus
     doux en X et Y quand la tête est basse** (choix du fil logiciel, niveau 1 : face sous 0,60 → accélération X et Y
     divisée par 2, EXEMPLE à régler aux essais). Rotation inchangée (± 500°).
  9. **Rails X +0,43** (validés par Karulium le 04/11, 18:26, avec le stockage agrandi) : pont de **0,223 à 2,925**
     (remplace 2,495) ; mât de la griffe à **x ≤ 2,738** (au-dessus du stockage), préhension à **x ≤ 3,054** ; garage
     de repos et place de photo côté stockage : **pont à 2,925**. La caméra du plafond reste en (1,45 ; 0,545) tant
     que le fil Guidage caméra ne dit pas autre chose.
  Ces corrections vont dans la tâche 36 bis.
- **Poste du fût : plateau de pesée sans fil** (validé par Karulium le 05/11/2026, 01:26 ; fil Poste du fût,
  `poste-fut-pour-logiciel.md` v10 du 05/11) : le chariot retourneur disparaît (rochet, cliquet, goupille, sangles,
  prise magnétique, HX711 relié au Pi). Le fût arrive debout sur un **plateau à 4 roulettes** ; le retournement se
  fait dans le culbuteur du pasteurisateur, hors de la machine. Centre du fût, enceinte, volet, panneau et « Prêt »
  ne changent pas.
  1. `chariot_fut_en_place` devient **`plateau_fut_en_place`** (même inductif M12 PNP dans la butée d'angle, il voit
     le bord du plateau). Même règle de zone pour le pont. Il reste câblé en 24 V : il marche sans la radio.
  2. **Radio ESP-NOW entre deux ESP32-C3** (plateau → boîte du poste), sans Wi-Fi ni réseau : c'est le choix de
     Karulium (« ne rien brancher »), une **exception** à la règle « rien sans fil » des cartes de pesée. Elle ne
     porte que la pesée, jamais un verrou ni une sécurité.
  3. La boîte du poste est un esclave **Modbus RTU** du bus `rs485_pesee` (adresse 4, EXEMPLE), registres 0 à 7 du
     même sens que `pesee/README.md`, signature **0x5046** ; registres 8 à 12 en plus (reed du plateau, recharge,
     tension et % de l'accu, signal radio, trames perdues). 2 mesures par seconde (moyenne de 5) ; précision voulue
     ± 0,2 kg fût immobile. 4 capteurs de 150 kg en parallèle sur **un seul HX711**. Étalonnage sur le Pi
     (`pesees.yaml`).
  4. **La pesée n'entre plus dans « Prêt »** : « Prêt » = plateau en place + signaux stables 2 s + appui. Radio muette
     (pas de réponse, bit « radio muette », ou mesure de plus de 2 s) ⇒ pesée « absente » : affichée, au journal,
     alerte ; **la machine ne s'arrête jamais pour ça** (la griffe trouve le fond au toucher) ; le seau est noté
     « sans pesée du fût » ; la pesée revient seule.
  5. Batterie (accu 18650, recharge sans contact au poste) : alerte « recharger le plateau » sous 3,5 V, alerte forte
     sous 3,3 V, alerte « recharge en panne » si plateau au poste depuis 10 min sans recharge (seuils : réglages,
     EXEMPLES).
  Les numéros d'entrées viendront de l'Implantation. Côté Pi : tâche 17 bis ; programmes des 2 ESP32-C3 : 17 ter.
- **Plateau de pesée, réponses à la PR n° 77** (tâche 17 bis, 06/11/2026, niveau 1, tranché par Claude) :
  1. **Tare** : le zéro est fait **plateau vide** (`pesees.yaml`), donc le poids lu = fût vide (29,5 kg) + couvercle
     (3,9 kg) + substrat (96 kg au plus). `machine.yaml → poste_fut → pesee` : **tare 33,4 kg**, bornes plausibles
     **25 à 150 kg** (EXEMPLES). Simulateur : `vidange_fut` lit 93,4 kg (60 kg de substrat), `echange_fut` lit 36 kg
     pour le fût vide puis 129 kg pour le fût plein. À l'essai : mesurer la vraie tare (fût vide + couvercle sur le
     plateau taré), puis régler les bornes.
  2. **Bit 1 (valeur 2) du registre 8** de la boîte du poste : « **5 V de la recharge sans contact présent** », pas
     « en charge » : il reste vrai accu plein, donc un accu plein ne déclenche pas l'alerte « recharge sans contact en
     panne ? » (code : `recharge_presente`). À faire ainsi dans le programme du plateau (tâche 17 ter).
  3. **Alertes du poste** (pesée absente, accu faible, recharge en panne) : des **alarmes du registre** (écran, page
     web, envoi avec le cycle), **pour information seulement**. Elles ne bloquent jamais le cycle : ni le « Prêt », ni
     la vidange, ni le seau suivant n'attendent leur acquittement (la pesée n'arrête jamais la machine). Vérifié dans
     le code (le chef ne lit pas les alarmes du registre ; la check-list les dit « attention », jamais « bloquant ») et
     par deux tests (`test_alarmes_du_poste_ne_bloquent_jamais`, `test_alarmes_du_poste_ne_bloquent_pas_la_vidange`).
- **Cartes radio du poste du fût, réponses à la PR n° 78** (tâche 17 ter, 06/11/2026, niveau 1, tranché par Claude) :
  1. **Carte** : ESP32-C3 SuperMini pour le plateau et pour la boîte (petite, peu chère, USB-C, voyant sur GPIO8).
     Une autre carte ESP32-C3 ne change que `pesees.yaml → poste_fut_radio`.
  2. **Consommation** : radio allumée sans économie d'énergie (≈ 70 à 90 mA au lieu de 40 mA). Gardé : ça ne
     compte que si la recharge sans contact est en panne (≈ 15 à 25 fûts au lieu de 30 à 50). À mesurer à l'essai ;
     économie d'énergie de la radio seulement si c'est utile.
  3. **Petits composants** (pont diviseur 2 × 220 kΩ + 100 nF pour l'accu, 10 kΩ + 15 kΩ pour chaque détection de
     5 V, tirage 100 kΩ du reed, 10 kΩ de DE/RE vers le 0 V) : acceptés, à mettre dans le plan de câblage du poste
     du fût (demandé au fil mécanique). Broches et valeurs : `pesees.yaml`, EXEMPLES.
  4. **Puissance radio** 8 dBm (≈ 1 m entre plateau et boîte) : gardée ; à monter seulement si l'essai montre des
     trames perdues ou un signal sous −85 dBm. Pas de chiffrement (une clé serait un secret de plus pour une pesée).
- **Électronique du chariot et liaison du spray** (06/11/2026, niveau 1, fil logiciel, d'accord : Guidage caméra / plan de
  commande) :
  1. **PCA9685 et ToF VL6180X du boîtier du chariot** : commandés par la **carte de pesée RP2040-Zero du plateau du
     remplissage** (bus `rs485_pesee`, Modbus), par un I2C en plus (exemple I2C0 sur GP4/GP5, 100 kHz). Le Pi écrit les
     angles des servos et lit le ToF par des registres Modbus en plus. La PCA9685 démarre sorties coupées : le Pi renvoie
     les angles après chaque redémarrage de la carte, vu par un registre « compteur de démarrages ». Plus de 2 s sans
     ordre du Pi : la carte garde les angles (aucun mouvement).
  2. **Servo DS3225 de la Fermeture des seaux** : seulement son SIGNAL sur un canal libre de cette PCA9685 ; son + vient de
     `bec_servo` (24 V → 6,8 V 5 A), masse commune. Le BEC 6 V 3 A de la PCA9685 reste pour le Micropore (DS3225
     d'escamotage + MG90S de lame). `cable_servo` (12 m depuis l'armoire) n'est plus utile.
  3. **Carte ESP32 n° 5 du spray** : Modbus RTU sur RS485 (MAX3485), sur **son propre bus `rs485_spray`** et son
     adaptateur USB-RS485 (une panne du spray ne coupe pas les pesées) ; paire torsadée A/B + 0 V, 120 Ω aux 2 bouts,
     polarisation de repos sur l'adaptateur. L'USB de la carte : mises à jour seulement, machine à l'arrêt.
  4. **Capteur 24 V `bras_spray_range` sur l'ESP32** : optocoupleur PC817 (2,2 kΩ ½ W côté 24 V, ≈ 10 mA ; collecteur
     vers le GPIO avec 10 kΩ de tirage au 3,3 V, émetteur au 0 V). Logique inversée : bras rangé = GPIO à 0.
- **Portique, réponses à la PR n° 75** (tâche 36 bis, 06/11/2026, niveau 1, fil logiciel) :
  1. Le pilote boucle fermée du godet ne laisse pas FluidNC baisser son courant : prise d'origine du godet **lente**,
     et les sorties d'alarme des pilotes A et B de la griffe vont **en parallèle sur l'entrée libre E12 de la carte
     n° 1** (E10 et E11 servent aux origines), signal « alarme A ou B » (EXEMPLE). Le fil Portique est d'accord
     (06/11) ; à vérifier sur la notice des pilotes : sorties à collecteur ouvert, même sens actif.
  2. Longueur du rail du pont : 3,0 m en EXEMPLE (la course 0,223 → 2,925 doit y tenir), à mesurer à la mise en
     service.
  3. Accélération X/Y divisée par 2 tête basse (face sous 0,60) : gardée jusqu'aux essais.
  4. Recherche du Hall de la tête de préhension limitée à **60°** (au lieu d'« un peu plus d'un tour ») : accepté ;
     le compte-tours donne déjà le tour à ± 3°, et la tête ne peut pas tomber sur l'aimant du tour suivant.
- **Stockage agrandi, réponses à la PR n° 76** (tâche 35 ter, 06/11/2026, niveau 1, fil logiciel) : (1) 5 places de
  piles de fin de lot pour A, C et D (au lieu de 4), conséquence du hublot reculé en (2,93 ; 0,22), avec la même
  règle (bord ≤ 2,87, marge du hublot) : **confirmées par le fil Stockage (06/11)**, avec une condition en plus :
  l'axe de chaque pile à **x ≥ 1,29** (règle de la caméra du bocal pour la rangée y 0,215 ; ex. C : 1,29 / 1,60 /
  1,91 / 2,22 / 2,53). (2) Pousseur : poussée ≈ 0,3 × poids, 7 seaux pleins ≈ 175 à 280 N (350 N avec 7 seaux de
  10 kg), NEMA 23 ≈ 480 N : force et vitesse inchangées ; **seuil de blocage vers 400 N** (EXEMPLE), effort réel
  mesuré à l'essai.
- **La fiabilité d'abord** (Karulium, 28/10/2026) : quand rapidité et fiabilité s'opposent, on choisit la
  fiabilité. Un gain de vitesse (ordonnancement, trajets, montée en vitesse par paliers de +5 % tous les 25 cycles)
  n'est gardé que s'il ne crée **aucune alerte ni aucun écart** ; au moindre doute, retour au réglage sûr
  (recul sur alerte). Vaut pour le solveur (tâche 23 : OR-Tools CP-SAT, cycles calculés à l'avance puis joués par
  le Pi) et pour la montée en vitesse (tâche 30).
- **Préhension figée** (27/10/2026) : capteur inductif M8 24 V ; capteur de vide sur l'ADS1115 **en 3,3 V**
  (pas de pont diviseur) ; pour poser ou prendre un bocal sur le porte-bocal, la tête est orientée à ± 3°
  (grâce aux méplats) et ne tourne pas entre les mors.
- **Origine de la rotation de la tête de préhension** (fil Préhension, 05/11/2026, niveau 1, après une question de
  Karulium) : l'origine `origine_rotation_tete` est le **capteur Hall sous la poulie de 60 dents**.
  1. Recherche du Hall **toujours lente et toujours dans le même sens** (répétabilité meilleure que 1°).
  2. Une constante réglée à la mise en service : l'angle « méplats en face des mors en V » par rapport au Hall.
  3. Pose ou prise au porte-bocal (± 3°, règle ci-dessus) : la tête va sur la **plus proche des 3 positions des
     méplats** (elles se répètent tous les 120°) : jamais plus de 60° de rotation pour s'aligner.
  4. L'**angle cumulé** de la tête (tours compris) est enregistré à chaque arrêt, pour rester dans ± 500° (cordon
     spiralé).
  5. Après une coupure en pleine rotation : avant de chercher le Hall, l'écran demande à l'opérateur de vérifier
     que le cordon n'est pas vrillé.
  6. **Compte-tours** (validé par Karulium le 05/11, 12:37) : un potentiomètre multitour, entraîné au rapport 3
     (± 1,5 tour de la tête = ± 4,5 tours du potentiomètre), lu sur la **voie A1 de l'ADS1115** (`compte_tours_tete`).
     Tête à 0° = potentiomètre à mi-course. Au démarrage, le **tour** vient du potentiomètre (± 3°), puis l'angle
     fin vient du Hall ; la recherche du Hall reste limitée à un peu plus d'un tour. L'angle enregistré (point 4)
     sert alors de contrôle : écart de plus de 30° (réglage) avec le potentiomètre, ou potentiomètre hors de sa
     plage ⇒ pas de prise d'origine, l'écran demande de vérifier le cordon (point 5).
  Côté logiciel : tâche 36 bis, point 7.

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

1. **Caméra du plafond** : 9 règles « situation → travail » validées le 24/10/2026 (dans
   `pi/reglages/vision.yaml`, tâche 22). Le Pi PROPOSE le travail et attend le « Go » de Karulium. Repère ArUco
   40 mm sur le plateau du rince-verre du lave-bocal. Corrections après essais réels. Dans l'ordre, la première
   qui correspond gagne :
   1. objet inconnu, ou pièce mal placée sur un trajet ⇒ rien ne bouge, alerte avec la photo ;
   2. fût plein de maïs + bocaux vides et propres au stockage ⇒ remplir les bocaux ;
   3. fût plein + pas de bocaux vides + seaux vides propres + bocal de semence prêt ⇒ remplir les seaux et
      ajouter le mycélium ;
   4. fût plein mais rien de vide et propre où le mettre ⇒ alerte « rien à remplir » ;
   5. bocaux sales + lave-bocal posé ⇒ laver les bocaux ;
   6. bocaux sales + lave-bocal absent ⇒ demander de poser le lave-bocal ;
   7. seaux ou couvercles sales + lave-bocal absent ⇒ laver les seaux ;
   8. seaux sales + lave-bocal posé ⇒ demander de retirer le lave-bocal ;
   9. rien de tout cela ⇒ attendre, nouvelle photo toutes les 5 min.
   Photo seulement pont garé au bout opposé, refusée si elle a plus de 5 s ; sans reconnaissance sûre : cas 1.
   Lave-bocal, avant chaque geste dangereux pour lui (seau dans le fût de lavage, noyau, couronne) : repère vu
   ⇒ posé (seau, noyau, couronne interdits) ; fût vide vu clairement ⇒ seaux permis ; doute ⇒ rien ne bouge,
   alerte avec la photo, bouton « Vérifié ». Caméra et confirmation à l'écran d'accord, sinon doute.
2. **Caméra du dosage** sur servo DS3225 : 0° = bocal, 63° = seau. Photo du seau après chaque godet, avec sa dose. Elle pivote SEULEMENT si l'agitateur est garé (bocal x ≤ 0,62) ET si griffe et préhension sont hors de la zone x < 1,10, y < 0,34, z 0,95 à 1,08. Elle remonte avant le retour de l'agitateur ou du godet.
3. **Porte du spray ouverte** : portique arrêté, griffe interdite en x < 0,50 et y < 0,40 (y < 0,33 avant le 31/10 ; boîte du spray de 200 de profondeur, Maquette) et jamais au « Bain des têtes », ozone et UV coupés.
4. **Reed du panneau du poste du fût** : production seulement contact fermé ; lavage seulement contact ouvert.
5. **Mycélium / Remplissage** : quand l'agitateur roule, le chariot de remplissage reste à y ≥ **0,40** (31/10/2026 ; avant : 0,375).

## État des modules (26/10/2026)

- **Figés** (on peut coder leurs gestes) : Poste du fût, Lavage, Griffe (Transfert), Porte-bocal, Mycélium, Guidage caméra, Préhension, écran Nextion, Portique (gelé le 28/10/2026, tâche 36), Nettoyage (gelé le 28/10/2026, regelé le 04/11/2026, tâche 38 : store, purge, nuit UV-ozone, mode maïs).
- **Pas encore figés** (case vide seulement) : Remplissage, Stockage, Micropore, Fermeture des seaux, Air comprimé, Entonnoir.
- **Spray** : gelé (fiche v5.8 du 01/11/2026) ; côté Pi fait à la tâche 39 (voir « Spray, côté Pi » plus bas).
- Références encore à choisir : fins de course du Remplissage, microrupteurs du Stockage.

## Capteurs d'ozone ZE25-O3 (tâche 38 bis, 06/11/2026)

- Les capteurs d'ozone sont des **Winsen ZE25-O3 en UART**, plus des transmetteurs Modbus. Signaux :
  `ozone_dedans` et `ozone_dehors` (anciens `ozone_1` et `ozone_2`, renommés sur demande du fil Nettoyage).
  Une liaison USB-RS485 par capteur (cartes `rs485_ozone_dedans`, `rs485_ozone_dehors`), reconnue par son numéro
  de série ; aucune adresse. Le Modbus reste pour les cartes de pesée seulement.
- Protocole écrit de mémoire (9600 bauds, trames de 9 octets, début 0xFF, somme de contrôle) : **à vérifier sur la
  notice papier**. Les chiffres du capteur sont dans `docs/entrees-sorties.yaml` (bloc `ozone:`, `exemple: true`).
- Trame à la somme fausse : ignorée et comptée. Pas de trame valable depuis `delai_muet_s` : capteur « muet »
  (alerte). Valeur au plafond : affichée « ≥ 10 ppm », jamais « 10 ».
- **La sécurité ozone reste câblée.** Son appareil n'est pas encore choisi (question posée à Karulium). Le Pi lit
  l'ozone pour informer et attendre ; aucun code ne la remplace ni ne la simule.
- **Réponses à la PR n° 79** (06/11/2026, niveau 1, tranché par Claude) :
  1. Vitesse, mode d'envoi, position de la valeur et unité : vérifiés sur la notice papier à l'étape 2 de la
     procédure d'essai (`pi/systeme/essai-ozone.md`), puis corrigés dans `entrees-sorties.yaml` si besoin. La fiche
     du module Nettoyage (06/11) confirme 9600 8N1 et ppm = valeur × 0,01.
  2. Mode **envoi automatique** (une trame par seconde, rien à demander) ; question-réponse gardé en réglage.
  3. Capteur « muet » après **5 s** sans trame valable (EXEMPLE, à régler à l'essai).

## Nettoyage : store, purge, nuit UV-ozone, mode maïs (tâche 38, 06/11/2026)

Source : fiche `nettoyage/logiciel/nettoyage-pour-logiciel.md` du projet mécanique (module gelé le 28/10/2026,
regelé le 04/11/2026 ; lot validé par Karulium les 27/10, 31/10, 01/11 et 04/11). Positions de l'enceinte
(`enceinte-04-11.yaml`) et chiffres : `pi/reglages/machine.yaml → nettoyage` ; code : `pi/vidange/nettoyage/`.

- **Sécurité câblée, le Pi lit et attend.** `store_ferme` (2e contact) dans la boucle d'arrêt du portique ; chaîne
  UV-ozone (reeds du bas du store + porte du spray en série) devant `generateur_ozone` et `lampe_uv` ; verrous du
  store fermés sans courant, clé de dépannage. **Le Pi ne commande pas le moteur du store** (commande maintenue :
  2 boutons câblés, fins de course dans le moteur). L'alarme d'ozone câblée n'a pas encore d'appareil : aucun code
  ne la remplace ; son contact `ozone_securite_ok`, s'il est un jour dans la liste, est seulement affiché.
- **Purge** : chiffres figés (7 min au moins ; particules dedans ≤ 1,5 × dehors stable 1 min ; surpression ≥ 8 Pa,
  5 Pa avec balais ; alerte à 20 min). Pendant la purge, le chef refuse le dosage de la semence, l'ouverture d'une
  capsule et le versement dans un seau ouvert (« purge en cours ») : `Chef.permission(geste)`. Capteur de purge
  absent ou muet : condition jamais vraie (alerte à 20 min, Karulium attend ou passe outre, noté au journal).
- **Nuit UV-ozone** : seuils figés (ouverture et retour sous 0,1 ppm stable 15 min, fuite dehors > 0,1 ppm).
  Durées d'EXEMPLE (génération 2 min, contact 2 h compté depuis le départ, retour au plus 6 h depuis le départ,
  départ 22 h). Après une coupure : générateur coupé, reprise à l'attente du retour, jamais de génération seule.
  Nuit en erreur : store verrouillé ; seule la clé l'ouvre ; la nuit est close quand le store est refermé.
- **Choix de la tâche 38 (tranchés par Claude, en attente des réponses de Karulium, PR de la tâche 38)** :
  rien ne commence store ouvert (condition générale du chef, sauf en mode maïs) ; store ouvert pendant un cycle :
  alerte « store mal fermé » et pause ; purge aussi au démarrage du Pi si le store est déjà fermé ; verrous
  libérés et store pas ouvert au bout de `deverrouille_max_s` (60 s, EXEMPLE) : verrous remis ; une nuit prévue
  est annulée par un redémarrage ; « mesure incohérente » = l'ozone dedans n'a jamais atteint `attendu_min_ppm`
  (1 ppm, EXEMPLE) pendant la génération ; le Pi coupe aussi le compresseur (`relais_compresseur`) et le
  ventilateur de l'armoire (`coupure_ventilateur_armoire`, contact fermé au repos) pendant la nuit ; mode « maïs »
  ajouté aux modes ; une fuite part tout de suite par la file d'envoi (cycle « nettoyage » à elle).
- **Cases vides** (tâche 38 ; remplacées par de vrais pilotes à la tâche 38 ter, voir plus bas) : capteurs de
  particules, pression différentielle, convertisseur de la consigne 0-10 V du ventilateur
  (`vidange/nettoyage/capteurs.py`).
- **Réponses à la PR n° 80** (06/11/2026, niveau 1, tranché par Claude) :
  1. Consigne 0-10 V du ventilateur : module PWM → 0-10 V sur une GPIO du Pi (EXEMPLE GPIO19), plutôt qu'une carte
     GP8403 en I2C ; choix signalé au fil Nettoyage (pièce à ajouter à sa fiche).
  2. Capteurs de la purge : restent en case vide. Recommandation SPS30 (particules) et SDP810-125Pa (pression)
     transmise au fil Nettoyage, à qui revient le choix des pièces.
  3. Alarme d'ozone câblée : question posée à Karulium par le fil Nettoyage ; si elle a un contact sec, le Pi le lit
     seulement pour l'afficher (`ozone_securite_ok`).
  4. Panneau long du poste du fût pendant la nuit : pas une condition de départ ; les deux positions sont acceptées
     et notées au journal, « levé » (contact fermé) est la position normale ; jamais exiger « rabattu » (avec un fût,
     il ne peut pas se rabattre). Réponse du fil Poste du fût, 06/11.
  5. Store ouvert pendant un cycle : pause de toute la machine (le portique est déjà arrêté par le câblage). Oui.
  6. Pi qui démarre store déjà fermé : purge lancée. Oui.
  7. Compresseur et ventilateur de l'armoire coupés par le Pi pendant la nuit (pas une sécurité de personne). Oui.
  8. Verrous remis 60 s après une libération si le store n'a pas été levé. Oui.
  9. « Mesure incohérente » = `ozone_dedans` jamais monté à 1 ppm pendant la génération (générateur ou capteur en
     panne). Oui.

- **Pilotes réels des capteurs de la purge (tâche 38 ter, 06/11/2026, niveau 1, tranché par Claude)** :
  pièces choisies par le fil Nettoyage : 2 SPS30 (particules), 1 SDP810-125Pa (pression), module PWM → 0-10 V.
  - `particules_dedans` : SPS30 par convertisseur TTL-RS485 et l'adaptateur `rs485_sps30` ; `particules_dehors` :
    SPS30 sur l'UART3 du Pi (GPIO 8/9, `/dev/ttyAMA3`, `dtoverlay=uart3-pi5`). 115 200 bauds, protocole SHDLC
    (`vidange/trame_sps30.py`). Grandeur lue : PM2.5 en masse (µg/m³), réglable (`particules → grandeur`).
  - `pression_enceinte` : SDP810-125Pa en I2C, adresse 0x25, mesure continue (`vidange/trame_sdp810.py`), en Pa,
    positive si l'enceinte est plus haute que le conteneur (`pression → inverser` si les tuyaux sont à l'envers).
  - `consigne_ventilateur` : sortie PWM matérielle GPIO19 (canal 3, EXEMPLE) vers le module 0-10 V ; période et
    tension à 100 % dans `entrees-sorties.yaml → pwm` (EXEMPLES). Le Pi remet 0 V à la fermeture du matériel.
    Au démarrage, `plein_v` doit rester dans la pleine échelle du module (sinon le programme ne démarre pas).
  - **Capteur muet, en erreur ou à la trame fausse : jamais une valeur.** `lire` lève une erreur, le Nettoyage
    compte la mesure absente, la condition de purge n'est pas vraie, la purge finit en alerte à 20 min. Une
    mesure plus vieille que `delai_muet_s` est « muette » (même règle que l'ozone).
  - Tous les chiffres des protocoles (commandes, octets, échelles) sont écrits de mémoire : à vérifier sur les
    notices (`pi/systeme/essai-capteurs-purge.md`). Testé sur le vrai matériel : non.
- **Réponses à la PR n° 81** (06/11/2026, niveau 1, tranché par Claude) :
  1. PWM du servo de la caméra (GPIO18, 20 ms) et de la consigne (GPIO19, 1 ms) sur la même puce RP1 : gardé. Les
     canaux du PWM du RP1 ont chacun leur période ; à vérifier à l'étape 5 de la procédure. Si l'un dérègle l'autre :
     consigne sur un module I2C GP8403.
  2. Grandeur des particules : PM2.5 en masse (réglable) ; le seuil est un rapport dedans / dehors.
  3. Sens des tubes du SDP810 : P dans l'enceinte, N dans le conteneur ; vérifié à l'étape 4, `inverser: true` sinon.
  4. Un adaptateur ou une UART par SPS30 (même adresse SHDLC 0) : règle gardée.

## Spray, côté Pi (tâche 39, 06/11/2026)

Source : fiche `pulverisation/logiciel/spray-pour-logiciel.md` du projet mécanique (v5.8 du 01/11, module
gelé). Chiffres : `pi/reglages/machine.yaml → spray` (EXEMPLES marqués) et `pesees.yaml → balances_spray` ;
code : `pi/vidange/spray/` ; table des registres (langue commune avec la tâche 39 bis) : `spray/README.md`.

- **Liaison** : carte ESP32 n° 5 esclave Modbus RTU, seule sur le bus `rs485_spray` (signal `carte_spray`,
  adresse 1, 115 200 bauds : EXEMPLES). Lecture des registres 0 à 29 (fonction 4), ordres et battement
  dans les registres 100 à 104 (fonction 16) ; un ordre n'est exécuté qu'au changement de son numéro.
  Signature 0x5350, version de table 1.
- **Règle d'or** : tant que la carte n'a pas redit « bras rangé » (capteur vu, bras arrêté), `bras_spray_sorti`
  est vrai, carte muette comprise (plus de réponse depuis `liaison → muette_s`) et dès l'envoi d'un
  « sortir ». Le chariot de remplissage ne bouge alors ni en hauteur, ni ses barres, ni en y, ni son
  pousseur ; seule la rotation du seau est permise (règle 6, `remplissage/regles.py`).
- La carte s'arrête seule (pompe, air, bras rangé) si le Pi se tait plus de `silence_max_s` (2 s) ; le Pi bat
  toutes les `battement_s` (0,5 s) pendant ses gestes ; la carte refuse « sortir » sans battement récent.
- **Zone interdite à la griffe porte du spray ouverte : x < 0,50 et y < 0,40** (Maquette du 31/10) ; « jamais au
  Bain des têtes » sera branché avec le geste du bain des têtes (pas encore écrit).
- Le spray de culture dans le seau ouvert est un **geste protégé du chef** (`spray_seau`) : refusé pendant la
  purge, comme le versement.
- **Points non décidés, tranchés par Claude (niveau 1)** :
  1. un seul flacon par seau ; l'emplacement de chaque format vient des réglages (EXEMPLE : emplacement 1
     pour tous), en attendant la règle du logiciel de culture ;
  2. agitateurs 30 s avant chaque dose, puis 1 min toutes les 15 min (réglages) ;
  3. « dose d'amorce » réglable (EXEMPLE 1 g), ajoutée à la première dose après un changement de cartouche,
     notée à part dans le registre (`spray_amorce`) ;
  4. pompage pendant la rotation du seau (≈ 200°) ; la chasse finit le travail ;
  5. nouvelle cartouche reconnue quand le poids d'un emplacement monte d'au moins `changement_min_g`
     (EXEMPLE 50 g) : l'emplacement ne sert plus tant que Karulium ne l'a pas confirmée
     (`POST /api/spray/cartouche`) ;
  6. dose par format proportionnelle au volume (EXEMPLES : A 11 g, B 5 g, C 10 g, D 10 g) ;
  7. alerte « cartouche bientôt vide » sous 5 doses ; pas de dose sous « flacon vide + 20 g » ;
  8. alerte « alcool à remettre » à 3 nettoyages restants (≈ 25 par plein de 250 ml).
- Une erreur avant la sortie du bras met le module en alarme : « Sans spray » (le seau est noté sans spray)
  ou attendre. Dose incomplète, trop forte (+ 1 g) ou interrompue : notée et alertée, le cycle continue.
  Bras pas rangé : un seul nouvel essai automatique, puis alarme forte.
- Testé sur le vrai matériel : non (procédure `pi/systeme/essai-spray.md`, après la tâche 39 bis).
- **Spray, réponses à la PR n° 82** (tâche 39, 06/11/2026, niveau 1, tranché par Claude) :
  1. Erreur du spray : la machine s'arrête et l'écran propose « Sans spray » ou « Attendre » (comme la fiche du module).
  2. Amorce : 1 g (EXEMPLE) ajouté à la première dose après un changement de flacon, noté à part ; pas de seau perdu.
  3. Bouton « Cartouche N confirmée » en attendant le lien QR du logiciel de culture : suffisant.
  4. Doses ≈ 1 g par litre de seau (A 11, B 5, C 10, D 10 g ; Karulium 25/09 : ≈ 10 ml pour 10 L) : EXEMPLES, réglés
     aux essais.

## Carte ESP32 n° 5 du spray, programme (tâche 39 bis, 06/11/2026)

Code : `spray/` (ESP-IDF, comme `poste_fut_radio/`) ; chiffres : `machine.yaml → spray → carte` (tous
EXEMPLES) ; table des registres inchangée (version 1, `spray/README.md`). Testé sur le vrai matériel :
non (procédure `spray/essai-materiel.md`, puis `pi/systeme/essai-spray.md`).

- **Points tranchés par Claude (niveau 1), en attendant les réponses de Karulium (PR de la tâche 39 bis)** :
  1. **ESP32-S3** (exemple : ESP32-S3-DevKitC-1, module N8) : il faut 25 broches, un ESP32 n'en a
     pas assez de libres. Broches : EXEMPLES jusqu'à l'Implantation.
  2. Une SCK par HX711 ; sens des 4 pompes câblé en dur (`pompes_sens: null`) ; un seul EN pour les
     5 pilotes TMC2209 (10 kΩ vers le 3,3 V), 10 kΩ vers le 0 V sur chaque grille de MOSFET.
  3. Bras : 200 pas × 16 micro-pas, bras sur l'axe du moteur (`rapport: 1`), 180 °/s² ; « ranger »
     cherche le capteur jusqu'à −10° ; l'origine au plus 120° depuis là où il est (et 3 s).
  4. Bras bloqué : tous les pas faits mais capteur qui voit encore le bras ⇒ erreur 512.
  5. Pilote du bras muet puis revenu, ou redémarré (24 V coupé) ⇒ réglé de nouveau, origine à refaire.
  6. Balance muette pendant une dose ⇒ pompe arrêtée, comme le temps maximum (résultat 3, chasse,
     bras rangé). Poids perdu relu après la chasse.
  7. Le Pi a `silence_max_s` après le démarrage de la carte pour parler ; sinon, bras pas rangé ⇒ la
     carte le range seule.
  8. Modbus : `pesee/src/modbus.c` sait aussi la fonction 16 (écriture) ; les cartes de pesée la
     refusent (exception 1) comme avant.
  9. Outil `vidange-spray` : `dose` et `nettoyer` prennent `--angle` (le bras sort dans la même
     commande ; entre deux commandes, la carte range le bras au bout de 2 s).
- **Carte du spray, réponses à la PR n° 83** (tâche 39 bis, 07/11/2026, niveau 1, tranché par Claude) :
  1. Carte **ESP32-S3-DevKitC-1 N8** (environ 25 broches nécessaires) au lieu d'un ESP32 simple ; signalé au fil Spray
     (fiche et achats).
  2. Bras directement sur l'axe du moteur (`rapport: 1`, EXEMPLE) ; question posée au fil Spray.
  3. Sens des pompes câblé en dur, courant réglé par la vis du pilote (`pompes_sens: null`).
  4. Au démarrage, Pi muet 2 s et bras pas rangé : la carte le range seule, lentement (le bras ne doit pas rester
     au-dessus du seau ; le chariot ne bouge pas tant que le Pi n'a pas lu « bras rangé »).
  5. Balance muette pendant une dose : pompe arrêtée (on ne pompe jamais à l'aveugle).
  6. Balances : 80 mesures/s, moyenne de 8, « instable » au-delà de 3 g (EXEMPLES, étape 8 de la procédure).
  7. Agitateurs : PWM à 1000 Hz (jusqu'à 40 kHz si le moteur siffle).
  8. Le 24 V de la boîte du spray suit l'arrêt d'urgence (à confirmer par l'Implantation) : la carte voit le pilote
     redémarré et demande une nouvelle prise d'origine.
  9. Un seul fil EN pour les 5 pilotes, 10 kΩ vers le 3,3 V (moteurs coupés pendant le démarrage de la carte).
- **Servos et ToF du chariot, réponses à la PR n° 84** (tâche 40 bis, 07/11/2026, niveau 1, tranché par Claude) :
  1. Les registres donnent l'angle de l'axe du servo (0 à 270° pour un DS3225), pas celui du bras ; la conversion se
     fait dans les tâches 40 (Micropore) et 41 (Fermeture).
  2. Au redémarrage de la carte, la PCA9685 coupe les servos jusqu'au prochain ordre du Pi (≤ 1 s) : les gestes du
     Micropore et de la Fermeture doivent le supporter (pour le Micropore : ToF relu avant tout mouvement du plateau).
  3. Renvoi des angles chaque seconde (≈ 7 ms par seconde sur le bus des pesées) : accepté, mesuré à l'étape 21 de
     l'essai.
  4. Compteur de démarrages au hasard après une coupure de courant (pas d'écriture en flash) : le Pi cherche
     « différent », pas « +1 ».
  À savoir : la carte du plateau est une RP2040-Zero (Guidage caméra, 06/11) ; son voyant n'est pas GP25 (Pico) :
  mettre `voyant: null` (ou la broche de sa LED) pour cette carte à la mise en service.
- **Micropore côté Pi, réponses à la PR n° 85** (tâche 40, 07/11/2026, niveau 1, tranché par Claude) :
  1. La rangée du bas se pose à la position de vidage (y 0,42), quand le seau contient 4 kg de substrat (1,5 kg pour
     le format B) : gardé (EXEMPLE, à revoir à l'essai).
  2. Moteur d'avance du ruban : lettre X de la carte n° 3 (`mycelium_lavage`) ; à confirmer au câblage (Implantation).
  3. Attaches de l'anse : vues mais pas évitées, galet à 2 mm de la paroi pendant la rotation. À vérifier sur un vrai
     seau à l'essai ; si elles dépassent de plus de 2 mm, la tête est rentrée à chaque rotation (petite tâche à part).
  4. Seau de format inconnu ou pas appris : rempli sans micropore, avec une alerte (le cycle continue) : gardé.
  5. « Pas de contact » si le ToF baisse de plus de 3 mm entre l'approche et l'appui : gardé (EXEMPLE), revu à l'essai.
  6. Durée simulée ≈ 37 s au poste et ≈ 30 s pour la rangée du bas (15 s estimées par la mécanique) : accepté, mesuré
     à l'essai ; la cadence sera recalculée avec la vraie mesure.
  7. Le 6 V des servos suit l'arrêt d'urgence (Implantation, 07/11) : le BEC 6 V (borne V+ de la PCA9685) est sur le
     24 V coupé par K1/K2 ; la logique (RP2040, VCC de la PCA9685, ToF) reste sur le 24 V de commande. Le câble du
     chariot porte donc les 2 alimentations. Le logiciel ne suppose rien : il relit le ToF avant tout mouvement du
     plateau.
  8. Contact appris une fois par format (pas par rangée) : gardé, vérifié à l'essai.
  À faire plus tard : vision de la caméra du micropore (QR, trous, contrôle de chaque pièce), branchement dans le
  programme principal, bouton « rouleau » à l'écran et dans l'API.
- **Fermeture des seaux, côté Pi** (tâche 41, 07/11/2026, niveau 1, tranché par Claude ; les questions de la PR sont
  encore ouvertes) :
  1. Le bras est tourné par le servo de la PCA9685 (`servo_fermeture_seaux`), angles de l'AXE du servo. Étalonnage
     (`fermeture → bras → butee_servo_deg`) : angle où le doigt touche le plat ; travail = butée + surcourse,
     rangé = butée − 160° (EXEMPLES, à étalonner à la mise en service).
  2. Le bras est « rangé » pour le Pi seulement s'il l'a ordonné, que l'attente (0,5 s) est passée et que la carte
     du plateau est vivante et n'a pas redémarré depuis `stabilisation_s` ; jamais ordonné depuis le démarrage du
     Pi : « inconnu », le plateau ne monte pas au-dessus de la limite du bras (règle 5). Le premier ordre se donne
     sans rampe, plateau en bas (zéro de la montée d'abord).
  3. Nouvelle règle 11 du chariot : pas de rotation trigo du plateau tant que le couvercle touche le rouleau
     (`fermeture → rotation → sens_horaire` donne le signe de l'angle de l'axe A).
  4. Position du chariot pendant la fermeture : pas trouvée dans les fichiers du Remplissage, posée en réglage
     (`fermeture → chariot_y`, EXEMPLE 0,50 comme la pose du couvercle).
  5. Diamètre du couvercle dans la table des formats (`griffe → formats → diametre_couvercle`) ; le contrôle de la
     bande du haut vérifie le bord du couvercle du 1er seau (≤ `bord_x_max`).
  6. Une erreur de fermeture (pas de contact, contact trop tôt, couvercle bloqué, carte redémarrée) n'arrête pas le
     cycle : retour à l'approche, bras rangé, alerte et seau « fermeture à vérifier ». Seul « le couvercle reste
     contre le rouleau » met le module en alarme (le bras ne bouge pas).
- **Fermeture des seaux, réponses à la PR n° 86** (tâche 41, 07/11/2026, niveau 1, tranché par Claude) :
  1. Chariot en y 0,50 pendant la fermeture (EXEMPLE, comme la pose du couvercle) : gardé ; demandé au fil
     Remplissage (07/11) si la place est bonne et si le bras ne gêne rien.
  2. Fermeture ratée : le cycle continue, seau marqué « fermeture à vérifier » (pour ne pas bloquer la machine la
     nuit) : gardé.
  3. Pose du couvercle sur le seau plein par la préhension : ce geste n'existe pas encore dans le code. Il devient la
     tâche 41 bis (à écrire depuis la fiche du module qui le fait, avant le premier cycle complet).
  4. Bande du haut et tiroir : pas des places A 0,272 (couvercle 0,28) et C 0,30 (couvercle 0,315), soit 8 et 15 mm
     de recouvrement vus de dessus. Réponse du fil Stockage (07/11) : impossible, les couvercles voisins sont à la même
     hauteur et se touchent bord à bord ; le vrai pas est le Ø du couvercle (A 0,28, C 0,315, D 0,28, B le sien).
     Les pas 0,272 et 0,30 étaient faux. Avec un couvercle A de 0,28, le 7e seau A d'une file du tiroir manque
     d'environ 2,4 cm : compter 6 A par file tant que Karulium n'a pas mesuré le couvercle A (≤ 0,276 pour 7).
     Correction des places et contrôle au démarrage : tâche 35 quater.
  5. Réponse du fil Remplissage (07/11) : `fermeture → chariot_y` 0,50 est FIGÉ (règle 1 de
     remplissage/fiche/regles-positions.md : c'est là que la préhension pose le couvercle). Deux conditions
     entrent dans le logiciel (un test chacune, tâche 41) : a) le bras ne quitte le rangé que si la préhension a
     lâché le couvercle ET est remontée au-dessus de z 0,60 (`fermeture → prehension_libre_z`, figé), ou est
     partie ailleurs ; si la préhension n'est pas connue, il reste rangé par prudence ; b) le chariot (chariot_y)
     ne roule jamais quand le bras n'est pas vu rangé (refus avec la raison). La rotation du bras seulement
     plateau ≤ 0,26 (c) était déjà faite. Pour info : le bras balaie un disque de rayon ≈ 0,15 autour de son axe
     (repère du chariot x 0,09 ; y 0,293), à z 0,51-0,55 ; à Y 0,50 rien de fixe dans cette zone (calcul du
     Remplissage sur la géométrie B1, pas un balayage de la Maquette) : à vérifier à la main à l'essai.

## Pose du couvercle sur le seau plein (tâche 41 bis, 07/11/2026)

Source : `prehension/logiciel/pose-couvercle-pour-logiciel.md` (fil Préhension, module gelé le 27/10). Code :
`pi/vidange/couvercle/`, étapes dans `pi/vidange/remplissage/module.py`, réglages `machine.yaml → couvercle` (EXEMPLE) ;
essai : `pi/systeme/essai-couvercle.md` (testé sur le vrai matériel : non). Les points ouverts de la PR sont des
questions à Karulium ; en attendant, les choix ci-dessous sont ceux de Claude (niveau 1).

- **Le poste « couvercle » est branché dans `ORDRE_SEAU`** (quatre étapes du Remplissage : `preparer_le_couvercle`,
  `prendre_le_couvercle`, `poser_le_couvercle`, `controler_le_couvercle`), juste avant la fermeture. La condition de
  la fermeture « préhension lâchée et remontée au-dessus de z 0,60 » (`fermeture → prehension_libre_z`, PR n° 86) est
  déjà dans `Remplissage.prehension_degagee` : un test vérifie que la fermeture ne part qu'après la fin de la pose.
- **Pas de couvercle sans fermeture, ni de fermeture sans couvercle** : un couvercle posé et pas clipsé ne tient
  pas sur le seau ; si l'un des deux n'est pas prêt, l'autre est « pas lancé : attend … » (choix de Claude).
- **Z_pose est calculé** : `H_app + dessus_pose_z (0,459) − Hc`, à partir de `fermeture` ; il donne le tableau de la
  fiche (A, B, C 0,439 ; D 0,446). L'axe de l'outil à la pose (0,925 ; 0,49) est dans le fichier de réglages, et le
  démarrage vérifie qu'il est cohérent (x = axe du plateau ; y = `fermeture → chariot_y` − 1 cm, la prise hors d'axe
  de la pile).
- **La masse du couvercle (`m_c`) et sa tolérance** servent deux fois : au contrôle « un seul couvercle » (palier pesé,
  étape 6) et à la balance du chariot (étape 13, `P − P0`). Masses en EXEMPLE (A 0,13 ; B 0,10 ; C 0,16 ; D 0,13 kg),
  tolérance 30 %.
- **Aspirer / souffler** : ~~la tête n'a qu'une vanne de vide (`vanne_vide`)~~ (remplacé par la tâche 45
  undecies : deux vannes, « souffler » est la vraie vanne `vanne_souffler`) : « aspirer par impulsions » = vanne
  ouverte `impulsion_s` (1 s) au plus deux fois ; « souffler » = ~~vanne fermée pendant `souffle_s` (0,2 s)~~
  « aspirer » fermée puis `vanne_souffler` ouverte `prehension → vide → souffle_s`, comme l'Entonnoir. Pendant le trajet, la vanne reste ouverte (pas de nouvelle impulsion à −50 kPa) ; arrêt sur place au-dessus
  de −40 kPa.
- **Contact M8 lu à l'arrêt** : `Tete.contact_tete()` (nouveau) lit le M8 en dehors d'une descente au contact ; il sert
  au dégagement (étape 12 : le M8 doit retomber dans les 5 premiers mm, sinon « souffler » une fois de plus, puis alerte).
- **Contact à la pose plus bas que la fenêtre** (au-dessous de Z_pose − 8 mm, mais au-dessus de Z_pose − 15 mm) : la
  fiche n'en dit rien ; le couvercle est considéré posé et le Pi l'écrit au journal.
- **Pas de mémoire sur coupure** pour le haut de la pile : après un redémarrage, la prochaine prise repart du « haut sans
  mémoire » (0,90).
- **Les cartes du chariot et de la tête ne sont pas encore branchées au programme principal** : sur la vraie machine le
  poste est « pas lancé » (cartes du chariot, comme le seau vide ; EXEMPLE interdit), même règle que la tâche 45. Dans le
  simulateur, le lot de 20 seaux passe avec couvercle et fermeture (pile imaginaire `simulateur.yaml → cycle →
  couvercles`).

## Air comprimé (tâche 42, 07/11/2026)

Source : fiche `air/logiciel/air-comprime-pour-logiciel.md` du projet mécanique (module gelé le 28/10/2026).
Réglages : `pi/reglages/air.yaml` (tout en EXEMPLE : attente de mise en pression 240 s, rappel du bidon 7 jours) ;
code : `pi/vidange/air/`.

- **Un seul signal du Pi : `relais_compresseur`.** Fermé = compresseur autorisé (son pressostat décide ensuite).
  Le Pi le ferme quand `Nettoyage.air_permis` est vrai (pas de nuit UV-ozone) et l'ouvre sinon. La coupure de
  sécurité (arrêt d'urgence, ozone, purge) est câblée. Les pressions (4,5 bar, 0,5 bar, 8 bar) sont réglées à la
  main : le Pi ne les connaît pas.
- **Pas de capteur de pression de ligne.** Après chaque fermeture du relais (démarrage, fin de nuit UV-ozone), le
  Pi attend `attente_mise_en_pression_s` avant les gestes qui consomment de l'air : geste protégé `air` du chef
  (`Chef.permission("air")`) et `spray_seau`. Un manque d'air se voit chez les consommateurs : le « quoi faire » de
  la Préhension (vide perdu ou capteur muet) dit maintenant aussi « vérifier l'air ».
- **Rappel du bidon de purge** : dans la check-list (attention) et `GET /api/air` ; « bidon vidé »
  (`POST /api/air/bidon_vide`) remet le compte à zéro ; la date est gardée dans `donnees/air.json`.
- Choix de la tâche 42 (tranchés par Claude) : l'attente recommence après chaque coupure du compresseur, même
  courte ; pas de « fin de journée » automatique (le Pi ne connaît pas l'heure de fin) ; le Pi n'ouvre pas le
  relais sur un manque d'air.

### Air comprimé, réponses à la PR n° 87 (07/11/2026, niveau 1, tranché par Claude)

1. La Préhension (venturi) et le Lavage (jet d'air du col) attendent aussi la mise en pression : `module_prehension`
   et `module_lavage` prennent une condition `air` (sur la machine : `chef.condition_permission("air")`), ajoutée
   à l'entrée des étapes qui prennent un objet par le venturi (« prendre_* », « reprendre_au_porte_bocal ») et au
   jet d'air (« laver_le_seau »).
2. Oui : nouvelle attente (`attente_mise_en_pression_s`) après une nuit UV-ozone, comme après toute coupure du
   compresseur (test : `test_apres_la_nuit_uv_ozone_le_compresseur_est_referme`).
3. Non : pas de rappel de fin de journée.


## Entonnoir à bocaux (tâche 43, 07/11/2026)

Source : `entonnoir/logiciel/entonnoir-pour-logiciel.md` du projet mécanique (fiche v3 du 28/10, écrite le
06/11). Réglages : `pi/reglages/machine.yaml`, partie `entonnoir` (hauteurs de l'entonnoir posé, seuils de
contrôle, du vide et délais en EXEMPLE ; décalage de l'oreille, levée, bord du col, garde, précision de la
caméra en chiffres de la fiche) et objet `entonnoir` dans `prehension → objets` ; code : `pi/vidange/entonnoir/`.

- **Aucun signal propre à l'entonnoir.** Il emploie ceux de la Préhension, sous leurs noms du code (pas ceux
  que la fiche proposait) : `vanne_vide` (`ev_aspirer`), `contact_tete` (`contact_ventouse`), `vide_venturi`
  (`vide_prehension`), `electroaimants_capsule` (`aimants_prehension`, éteints). Rien n'est ajouté à
  `docs/entrees-sorties.yaml`.
- **`entonnoir_place`** : un nom de bocal, `hors_machine` ou `inconnu`, plus « tenu par la tête ». Gardé dans
  `donnees/entonnoir.json` (réécrit d'un coup à chaque changement). Après une coupure : gardé tel quel, sauf
  s'il était tenu, alors `inconnu` (les électrovannes NF lâchent le vide), avec une photo du plafond. Première
  mise en route : `hors_machine` ; fichier illisible : `inconnu`.
- **Pose et enlèvement à la main = le Go de Karulium** (étapes `demander_la_pose` et `enlever_a_la_main`, qui
  demandent le Go) : pas de bouton à part. Sans ce Go, la griffe ne verse dans aucun bocal
  (`Entonnoir.refus_versement`, et la condition d'entrée de l'étape `verser`). Quand l'entonnoir est perdu
  (absent, introuvable à la caméra, vide perdu), l'étape part en alarme ; après « acquitter » et le Go, elle ne
  fait plus rien et le module revient à `demander_la_pose` : le geste 1 recommence sur le bocal à remplir.
- **Pas de photo du fond au hublot** tant que `Entonnoir.sur_le_plateau()` (sur un bocal, tenu, ou inconnu) : à
  passer en argument à `ReglesStockage.refus_photo_du_fond`.
- **Gestes** (`geste_prendre`, `geste_poser`) : aimants éteints, ventouse en x bocal + 0,140, descente
  rapide jusqu'à 2 cm au-dessus de l'oreille puis vitesse d'approche, contact trop bas de 15 mm = absent, trop
  haut de 10 mm = mal posé ; vide −55 kPa en 2 s, un seul nouvel essai (souffle, remonter 5 mm) ; levée de
  0,060 ; transport à cette hauteur avec le vide surveillé (−40 kPa : arrêt, tête en haut, photo, alerte,
  `inconnu`) ; pose en vitesse d'approche, posé à ± 5 mm, sinon relever et réessayer une fois, puis le remettre
  sur le bocal d'où il vient et marquer le bocal visé « suspect » (le lot continue) ; lâcher, vide revenu
  au-dessus de −5 kPa (un deuxième souffle, puis alerte), remontée de 0,030 en vitesse d'approche puis en
  rapide. Le centre du col vient de la caméra (± 5 mm ; le cône en capte 9,5).
- **Règles ajoutées à la Préhension** : la tête ne tourne jamais en tenant l'entonnoir ; l'entonnoir roule à
  `oreille_z + levee_m` (exception à la règle « pont jamais tête basse », voulue par la fiche, limitée à cet
  objet) ; accélération « en charge » (0,5 m/s²) comme pour un seau ; son axe est à 0,140 m en −x de la tête
  (`Objet.decalage_x_m`), et les règles du Stockage (boîtier de la caméra du bocal : axe de l'entonnoir à
  x ≥ 1,205 si y < 0,38 ; boîtes à capsules : jamais au-dessus) s'appliquent à son axe, pas à celui de la tête.
- **Réglages vérifiés au démarrage** : pointe sous l'oreille, garde d'au moins 4 cm sur les cols voisins en
  transport, précision de la caméra ≤ capture du cône, seuil de lâcher au-dessus de celui de la perte,
  hauteurs dans la course de la tête, ventouse atteignant l'oreille de chacun des 122 bocaux.
- **Choix de la tâche 43 (tranchés par Claude)** : ordre de remplissage en serpentin (rangée par rangée, les
  voisins à la suite, une rangée dans un sens et la suivante dans l'autre) ; l'entonnoir ne va jamais au coin
  des suspects ni sur les places de séparation (lot refusé) ; son poids est pesé (pour la détection de choc)
  mais pas contrôlé ; la lecture de la photo du plafond n'est pas écrite : un faux répond les places attendues
  et le dit dans le journal.
- **Pas fait** : le vrai versement de la griffe (case vide `verser(bocal)` du module), le branchement dans le
  programme principal (comme les tâches 34 à 41), l'inventaire du Stockage (bocaux remplis) et la reprise d'un
  lot après une coupure : seul `entonnoir_place` est gardé.
- **Entonnoir, réponses à la PR n° 88** (tâche 43, 07/11/2026, niveau 1, tranché par Claude) :
  1. Pont qui roule tête basse en tenant l'entonnoir (levée 0,060 au-dessus de la pose, garde de 4 cm sur les cols
     voisins) : exception gardée, car c'est le geste figé de la fiche de l'Entonnoir, et limitée à cet objet.
  2. ~~Pas de vanne `ev_souffler` : lâcher en fermant la vanne du vide (deuxième essai, puis alerte).~~ **Faux,
     remplacé** (fil Préhension, 07/11/2026, tâche 45 undecies) : il y a deux électrovannes et un clapet
     anti-retour ; fermer « aspirer » ne lâche rien. Lâcher = « souffler » ≈ 0,2 à 0,5 s, puis vide revenu
     au-dessus de −5 kPa (deuxième souffle, puis alerte). Voir « Lâcher de la ventouse par « souffler » ».
  3. Deuxième essai de pose avec le même centre (pas de nouvelle photo possible, l'entonnoir est dans la tête) :
     gardé.
  4. Bocaux « suspects » (pose ratée deux fois) : le lot continue ; à la fin du lot, leur liste s'affiche et
     Karulium les vérifie à la main. Le rangement à part viendra avec l'inventaire des bocaux.
  5. Reprise d'un lot après une coupure : seul `entonnoir_place` est gardé pour l'instant ; la reprise se fera avec
     l'inventaire des bocaux remplis (à prévoir quand le programme principal branchera le mode bocaux).

## Versement de la griffe dans un bocal (tâche 43 bis, 07/11/2026)

Source : fiche du fil Griffe `griffe/logiciel/versement-bocal.md` (07/11). Code : `pi/vidange/griffe/versement.py`
(`Versement`, branché dans `module_entonnoir(..., versement=...)`) ; réglages : `machine.yaml → griffe →
versement_bocal` ; outil : `vidange-entonnoir versement` ; essai : `pi/systeme/essai-versement-bocal.md` (testé
sur le vrai matériel : non). Le geste n'a jamais été essayé avec du vrai maïs.

- **Figés** (sans `exemple`) : dose ≈ 300 g ; mât au-dessus du centre du col (caméra) à 0,05 au plus ; tête à
  A = 0, aucune rotation ; axes des coquilles à 1,025 (plage 1,02-1,07) ; ouverture de fermé à 20° ; garde du
  boîtier de la caméra du bocal (mât à y 0,21-0,29 → x ≥ 1,207) ; pesée à l'arrêt seulement (après 0,3 s,
  moyenne sur 0,5 s). **Proposés** (EXEMPLE) : `dose` (290-310 g, 6 prises au plus), `ouverture` (10 mm/s,
  1,5 s, remontée de 2 cm avant de fermer), `secousses` (3 aller-retour 15°↔25° à 30 mm/s, puis 35°), `fin`
  (tare ± 10 g stable 0,5 s ; pesée instable : 10 g entre 2 lectures à 0,3 s, 3 essais). **Vides** (EXEMPLE, à
  mesurer) : `godet` (position de la vis pour chaque angle) et `bouchage` (distance du capteur au cône vide,
  marge 2 cm).
- **Garde du boîtier de la caméra du bocal** : règle de la griffe (`ReglesGriffe`, chaque pose), pour le mât de
  x 0,997 (début du boîtier) à 1,207 dans la bande y ; vérifiée au démarrage (bande qui couvre le boîtier,
  raclette hors du boîtier, chaque bocal de la bande à x ≥ 1,207).
- **Tare « godet vide »** (choix de Claude) : pas de chiffre ni de fichier ; elle est **pesée à chaque prise**,
  godet ouvert et vide au-dessus du maïs, à l'arrêt. Elle est donc refaite à la mise en service et après chaque
  lavage, sans étape à part. L'essai vérifie qu'elle ne change pas avec la hauteur (chaîne, câbles).
- **Prise d'une dose** (`Griffe.geste_prendre(dose)`) : maïs, sans mâchouiller ni s'entrouvrir ; pesée à l'arrêt
  dans le fût ; hors de la plage (trop léger OU trop lourd), la prise est rendue au fût et refaite à côté ; tant
  que la densité du fût n'est pas apprise, la griffe corrige la dose visée d'après la dernière pesée (sinon
  6 prises ne suffisent pas). Contact au fond avec moins de `prise → utile_min_kg` : fût vide (pas de passe de
  fond en mode bocaux), alerte, le poste du fût dit « Fût vide : N bocaux ».
- **Jamais une 2e dose** : la phase « ouvert » (godet ouvert au-dessus du bocal) et « fait » sont gardées dans
  `donnees/versement.json`. Refait après une alarme ou une coupure, le versement d'un bocal commencé continue
  (repesée, puis fin) ; avant l'ouverture, il recommence par une prise (ce qui reste retombe au fût). Coupure en
  plein versement d'un autre bocal : ce bocal est noté « suspect », alerte, puis Go.
- **Alertes** (le module de l'entonnoir part en alarme, Go de Karulium) : grains collés (griffe immobile, godet
  ouvert, jamais refermé au-dessus du bocal), entonnoir bouché (bocal « suspect », griffe remontée godet vide
  fermé ; au Go, le lot continue), pesée instable, dose impossible, fût vide, bocal refusé par les règles (avant
  toute prise). Pause et alarme du module arrêtent aussi la griffe (sans la retirer : son godet reste tel quel).
- **Pas fait** : la lecture du capteur de distance de la tête (VL53L1X, case vide
  `distance_m`, sans lui le bouchage n'est pas vérifié et le journal le dit) ; la dose versée est notée au
  registre sans le code du bocal (mesure « dose_bocal »), en attendant l'inventaire des bocaux remplis. Le
  branchement dans le programme principal est fait par la tâche 45 sexies (pas par le solveur, tâche 23).
- **Versement dans un bocal, réponses à la PR n° 98** (tâche 43 bis, 07/11/2026, niveau 1, tranché par Claude) :
  1. Rangée 1 (y 0,06), godet ouvert permis seulement à y ≥ 0,11 : question posée au fil Griffe (limite à 20° et à
     35°) ; d'ici sa réponse, aucun bocal de la rangée 1 n'est rempli (refus avant toute prise).
  2. `bocal_0_0` et `bocal_2_0` (x 1,2075) : question posée à la Maquette (la bande de garde peut-elle s'arrêter à
     1,205 ?) ; d'ici sa réponse, refusés.
  3. Prise trop légère : la prise est rendue au fût et refaite (pas de « 2e prise complète » tant que le fil Griffe
     n'a pas décrit ce geste). Gardé.
  4. Plage 290-310 g : gardée pour l'essai ; élargie (par exemple 280-320 g) si moins d'une prise sur deux y tombe.
  5. Dernière rangée (y 0,8224) avec la préhension tête en haut : question posée au fil Préhension (préhension tête
     basse, face ≤ 0,942, pendant ces versements ?) ; d'ici sa réponse, refusés quand la préhension est en haut.
  Tant que ces trois réponses manquent, 29 bocaux sur 122 ne sont pas remplis par la griffe
  (`vidange-entonnoir versement` donne la liste).

## Programme principal, mode seaux (tâche 45, 07/11/2026)

Code : `pi/vidange/cycle/` ; lot du simulateur : `pi/reglages/simulateur.yaml → cycle` (EXEMPLE) ; essai :
`pi/systeme/essai-mode-seaux.md` (testé sur le vrai matériel : non).

- **L'ordre du cycle d'un seau est écrit à un seul endroit** (`vidange/cycle/ordre.py`, `ORDRE_SEAU`). Ordre
  corrigé le 07/11/2026 (section suivante) : fût, seau vide posé, QR du flanc, centrage et seau vide au poste, spray,
  rangées du haut du micropore, griffe, mycélium, couvercle, fermeture, stockage, lavage des vides. Le démarrage le lit
  (quels postes sont prêts, check-list, écran) ; le simulateur le lit (`vidange-simulateur cycle` vérifie que chaque
  seau du lot passe par ces postes, dans cet ordre).
- **Même code pour la machine et le simulateur** (`ModeSeaux`) ; seules les « pièces » (ce qui touche le matériel)
  changent : `PiecesMachine` au démarrage, `PiecesSimulees` dans le simulateur.
- **Un poste n'est pas lancé, avec la raison** (journal, check-list « mode seaux », écran quand rien ne tourne) : geste
  pas écrit (case vide), partie absente de machine.yaml, EXEMPLE sur la vraie machine, matériel ou vision qui manque,
  poste dont il a besoin pas prêt. Jamais de geste inventé.
- **Choix de la tâche 45 (tranchés par Claude, en attendant les réponses de Karulium, PR de la tâche 45)** :
  1. Cases vides d'`ORDRE_SEAU` : la griffe (son enchaînement avec la préhension sur le même pont et avec le seau du
     chariot est écrit par la tâche 45 sexies, pas par le solveur ; dans le lot simulé, chaque versement reste une rotation du seau),
     le spray (à quel passage au poste il dose n'est écrit nulle part ; **réponse du 07/11 : section suivante**), le
     couvercle (tâche 41 bis, donc pas de
     fermeture), le lavage des vides (travail à part, règle 7 du plafond).
  2. Sur la vraie machine, il manque aussi : la lecture du QR du flanc du seau par une caméra (le Remplissage refuse
     d'orienter l'anse sans elle), la pose du bocal de semence neuf par la préhension (case vide `nouveau_bocal` du
     Mycélium), la vision du micropore (tâche 40 ter). Les cartes du chariot et de la tête seront construites dans
     `vidange/cycle/machine.py` avec la lecture du QR.
  3. Le « cœur » d'un lot (seau vide, mycélium, stockage) va ensemble. Sur la vraie machine, un lot ne part pas sans
     les postes obligatoires (fût, seau vide, griffe, mycélium, couvercle, fermeture, stockage) ; le simulateur saute
     ceux qui manquent et le dit.
  4. Rien n'est lancé tout seul au démarrage (règle 6) : le lot est lancé par `ModeSeaux.lancer_lot`, après le Go de
     Karulium (pas encore de bouton : question de la PR).
  5. Le lot (seaux, seau en cours, couche, seau sur le plateau) est noté dans le carnet du chef après chaque étape du
     Remplissage ; après une coupure il est reconstruit et repris à son étape, après le Go. L'état du bocal dans
     l'agitateur n'est pas repris (le Mycélium ne le note pas encore).
  6. Le Remplissage attend l'air comprimé (`chef.condition_permission("air")`) avant de prendre un seau par le
     venturi, comme la Préhension et le Lavage (PR n° 87).

## Programme principal, réponses à la PR n° 89 (07/11/2026)

Réponses des fils mécaniques (Spray, Micropore, Guidage caméra) et de Karulium, recopiées ici. Code :
`pi/vidange/cycle/ordre.py` (l'ordre, un seul endroit), `pi/vidange/remplissage/module.py` (étapes
`aller_au_poste`, `spray_*`, `micropore_rangee_du_haut`), `pi/vidange/cycle/simulation.py`.

- **Spray** (fil Spray, `pulverisation/logiciel/spray-pour-logiciel.md` § 1 a), mise à jour du 07/11) : **une seule
  fois par seau, sur le seau VIDE**, au poste (y 0,135), avant la 1re couche, pendant le 1er aller-retour de la griffe
  (exigence de Karulium du 25/09 : « spray automatique dès le début »). Ordre :
  1. seau vide au poste, QR lu et seau orienté ;
  2. la griffe part chercher sa 1re prise ;
  3. plateau ≤ min(0,50 ; 0,68 − h) et barres ouvertes à plus de 0,50 d'entraxe (règle 6) ;
  4. le bras sort ;
  5. spray, le seau tourne d'environ 200° ;
  6. le bras se range (le Pi attend « bras rangé ») ;
  7. pose de la rangée du HAUT du micropore, dans le même aller-retour.

  Ensuite les couches de substrat et de mycélium, puis le couvercle et la fermeture. Le spray est branché dans le cycle
  (simulateur et machine) avec la même règle que les autres postes : « pas lancé : raison » s'il manque quelque chose.
- **Micropore** (fil Micropore) : c'est ce que fait déjà la tâche 40. Rangée du haut sur le seau vide au poste, après le
  spray ; rangée du bas quand le seau a assez de poids. Ce poids reste un réglage, sous le nom qu'il a depuis la tâche
  40 : `micropore → fond_poids_min_kg` (global, EXEMPLE 4 kg) et `micropore → formats → <format> → fond_poids_min_kg`
  (1,5 kg pour seau_b) ; il peut passer à 0 après l'essai, sans changer le code. Plateau arrêté et tête escamotée à
  chaque mouvement du plateau (tâche 40, inchangé).
- **QR du flanc** (fil Guidage caméra) : lu par la caméra du micropore (`cam_inspection`, sur une équerre du chariot ;
  pas de lecteur QR à part, le GM65 est retiré). Le QR est en bas du flanc.
  - Moment : seau vide posé sur le plateau à y 0,50, plateau monté à `remplissage → plateau_lecture_qr` (EXEMPLE,
    valeur à venir du fil Micropore), le plateau fait tourner le seau et la caméra lit pendant la rotation, AVANT le
    serrage des barres.
  - Puis le format du seau est chargé et le seau tourné pour mettre les oreilles de l'anse à 45° (modulo 90°) de l'axe
    x des barres. L'angle est lu sur le QR, corrigé par l'écart attaches/QR enregistré pour ce seau, et gardé jusqu'à la
    poussée ; le même QR sert de repère d'angle du micropore.
  - Lecture ratée après un tour complet : seau mis de côté et alerte, comme un format inconnu.
  - La lecture elle-même est dans la tâche 40 ter (vision du micropore). Ici l'étape existe dans l'ordre, avec une
    fausse caméra dans le simulateur ; sur la machine, le poste « qr_du_flanc » n'est pas lancé tant que la 40 ter
    manque.
- **Ordre corrigé** dans `ORDRE_SEAU` et dans le simulateur. Le lot simulé de 20 seaux passe sans alarme ; le test
  d'ordre vérifie : QR avant le serrage des barres, spray avant la 1re couche, rangée du haut après le spray et avant la
  1re couche, rangée du bas après le poids mini.
- **Question 1 de la PR (lancer un lot)** : acceptée au niveau 1 : bouton « Lot de seaux » sur la page web (format et
  nombre de seaux), puis Go sur l'écran de l'armoire. Pas encore codé (reste à faire).
- **Question 3 de la PR (lot sans micropore ou sans spray)** : posée à Karulium, **en attente**. D'ici là, sur la vraie
  machine, le lot ne part pas sans eux (le plus prudent : spray et micropore sont « obligatoires » dans `ORDRE_SEAU`),
  et il ne part **jamais** sans couvercle ni fermeture.
- **Choix de Claude (tâche 45, correction)** :
  1. « Mis de côté » après un QR pas lu : aucun geste ni place n'est écrit pour poser un seau de côté. Le Pi s'arrête
     en alarme avec l'alerte (« QR du flanc du seau pas lu après un tour complet ») et l'écran dit de mettre ce seau de
     côté à la main, comme pour un format inconnu. Le geste automatique sera écrit quand la place sera donnée.
  2. La lecture « pendant la rotation » : le plateau lit d'abord le QR là où il est ; s'il n'est pas lu, il fait un
     tour complet et relit (la caméra lit pendant ce tour ; la vraie lecture continue est la 40 ter).
  3. La griffe « partie du poste » (condition de la sortie du bras) : dans le simulateur il n'y a pas de griffe au
     poste, elle est vue partie ; sur la machine, c'est le mât de la griffe hors du seau du vidage (tâche 45 sexies).
- **Pose du couvercle, réponses à la PR n° 90** (tâche 41 bis, 07/11/2026, niveau 1, tranché par Claude) :
  1. Couvercle C à 2,3 mm de la tête du micropore escamotée : la Préhension a demandé au Micropore de reculer de 1 cm
     (07/11). En attendant, descente lente du C de la face 0,67 à 0,57 (fiche) ; à corriger dans les réglages à la
     réponse.
  2. Une seule vanne de vide : vanne ouverte pendant le trajet, arrêt sur place si le vide remonte au-dessus de
     −40 kPa. La relance à −50 kPa ne sera ajoutée que si le vide baisse à l'essai.
  3. Masses des couvercles (A 0,13, B 0,10, C 0,16, D 0,13 kg) et diamètre du B : EXEMPLES, à peser et mesurer par
     Karulium (avec le diamètre du couvercle A demandé par le Stockage le 07/11). Si le palier pesé ne voit pas un
     couvercle de plus, le contrôle passera à la caméra du plafond.
  4. Sens du couvercle : on suppose qu'il n'en a pas ; à vérifier à l'essai. S'il en a un, petite tâche à part
     pour l'angle de pose.
  5. Contact à 8-15 mm sous Z_pose (cas absent de la fiche) : accepté et noté au journal ; Hc revu à l'essai.
  6. Jamais de couvercle sans fermeture, ni de fermeture sans couvercle : oui.

## Programme principal, mode bocaux et nuit UV-ozone (tâche 45 bis, 07/11/2026)

Code : `pi/vidange/cycle/` (`mode_bocaux.py`, `mode_nuit.py`, `postes.py`, `ordre.py` → `ORDRE_BOCAUX` et `ORDRE_NUIT`) ;
simulateur : `vidange-simulateur cycle --lot bocaux|lavage_bocaux|nuit|tout` ; essai :
`pi/systeme/essai-mode-bocaux-nuit.md` (testé sur le vrai matériel : non). Aucun chiffre nouveau : tout ce que le
code lit est déjà dans `machine.yaml` (`entonnoir`, `lavage → lave_bocal`, `nettoyage`) et `simulateur.yaml`.

- **Même méthode que le mode seaux** : chaque poste est « prêt » ou « pas lancé : raison » (journal, check-list,
  écran), avec la même vérification (`postes.py → etat_du_poste` : geste pas écrit, partie absente de machine.yaml,
  EXEMPLE sur la vraie machine, matériel qui manque). On ne réécrit aucun module : `module_entonnoir`,
  `module_lavage_bocaux` et le Nettoyage sont ceux des tâches 43, 21 bis et 38, branchés.
- **Un seul mode, un seul lot à la fois (choix de Claude)** : on réutilise `ModeMachine` (mode.py), sans nouveau
  mode (le bouton « Bocaux » demanderait de changer le projet Nextion). Un lot de seaux ou de bocaux part en mode
  « production », laver les bocaux en mode « lavage » (c'est déjà ce que demande `Lavage.refus_mode`), la nuit en
  mode « UV-ozone ». Pas de lot si un autre lot est en route (`postes.py → refus_lancement`) ; pas de changement de
  mode pendant un lot (déjà vrai : `ModeMachine.refus`).
- **Lot de bocaux** : postes `fut`, `entonnoir` (cœur), `versement`, `lavage_bocaux`. `versement` est
  construit sur la griffe des cartes depuis la tâche 45 sexies (`vidange.griffe.versement`) ; le simulateur joue le
  versement en faux (`verse_s`). Sur la
  machine, l'entonnoir manque aussi parce que la Préhension (cartes de la tête) n'est pas construite par le
  programme principal et que la lecture de la photo du plafond n'est pas écrite.
- **Lavage des bocaux** : poste à part (il n'a pas besoin de la griffe). Sur la machine il manque : Lavage et
  Préhension pas construits, liste des bocaux sales (caméra du plafond, règle 7) pas écrite. Le simulateur le joue
  avec les bocaux de `simulateur.yaml → lavage`.
- **Reprise d'un lot de bocaux après une coupure** (réponse au point 5 de la PR n° 88) : le lot est noté dans le
  carnet du chef après chaque étape (bocal où est l'entonnoir, bocaux restants et versés, centre du col) ; il est
  repris à son étape après le Go. `entonnoir_place` reste dans son fichier. **Pas repris** : une série de lavage de
  bocaux (le carnet la signale alors comme module inconnu : regarder la machine, puis effacer le carnet).
- **Nuit UV-ozone** : le Nettoyage la mène déjà (tâche 38). Postes `enceinte` et `ozone` (cœur : sans eux, la nuit
  est refusée) et `purge` (capteurs de la purge : jamais bloquant, la purge finit en alerte). Le poste ajoute une
  raison de refus au Nettoyage (`refus_nuit_en_plus`) : le bouton « NUIT » de l'écran, la page web et le
  simulateur la voient. **Sur la vraie machine, tant que `nettoyage` est en EXEMPLE, la nuit est refusée** (règle 2
  du dépôt). Une nuit déjà partie n'est jamais touchée. Après une coupure en pleine nuit : générateur coupé, attente
  du retour sous le seuil, **jamais relancé seul** (déjà le cas, maintenant dit dans la check-list).
- **Check-list** : « mode bocaux » et « nuit UV-ozone » sont des lignes « attention », jamais « bloquant » : les
  seaux ne dépendent pas d'eux (le mode seaux, lui, reste bloquant comme avant).
- **Écran** : quand rien ne tourne, la page d'état dit ce qui manque selon le mode : production (seaux d'abord, puis
  bocaux), lavage (bocaux), UV-ozone (nuit). Les seaux ne s'affichent plus en mode lavage, UV-ozone ou maïs.
- **Sécurité** : rien ne change. La chaîne UV-ozone, le store et les portes restent câblés ; le Pi n'a ajouté aucune
  commande, seulement des refus.

- **Mode bocaux et nuit UV-ozone, réponses à la PR n° 91** (tâche 45 bis, 07/11/2026, niveau 1, tranché par Claude) :
  1. Pas de mode « Bocaux » en plus à l'écran pour l'instant (le lot de bocaux part en mode « production »).
  2. La nuit UV-ozone reste refusée tant que `nettoyage` est en EXEMPLE : on valide d'abord ses réglages pendant
     l'essai du Nettoyage (générateur à blanc), puis on enlève `exemple: true`.
  3. Pas de lot de bocaux sans le versement de la griffe : on attend son geste. Écrit par la tâche 43 bis,
     branché au programme principal par la tâche 45 sexies.

## Vision du micropore (tâche 40 ter, 07/11/2026)

Code : `pi/vidange/vision/inspection.py` ; réglages : `pi/reglages/vision.yaml → inspection` (EXEMPLES,
`exemple: true`) ; vidéo : `programme.yaml → cameras → liste → micropore` (commande d'EXEMPLE) ; outils :
`vidange-vision flanc|piece|rouleau|ecart` ; essai : `pi/systeme/essai-inspection.md` (testé sur le vrai matériel :
non). Source : `micropore/logiciel/micropore-pour-logiciel.md` (§ 1 a, gestes 0 et 11) et le fil Guidage caméra
(PR n° 89, section « Programme principal, réponses à la PR n° 89 »).

- **Une seule vision pour deux modules.** La caméra `cam_inspection` du projet mécanique garde son nom `micropore`
  dans le code (`vision.yaml → cameras → micropore`, `machine.yaml → micropore → camera`) : la renommer aurait
  touché trois fichiers pour rien.
  - Le Remplissage (`VisionSeau`) lit le QR du flanc **pendant que le plateau tourne le seau** : il appelle
    `commencer_lecture`, lit à l'arrêt (`lire_seau`), fait faire un tour complet s'il n'a rien lu, relit, puis
    `finir_lecture` (même quand le geste est arrêté par une alarme). Pas lu après un tour complet : alerte, comme
    un format inconnu (inchangé).
  - Le Micropore (`VisionMicropore`) : tour de repérage (QR, trous), puis contrôle de chaque morceau.
- **Comment l'angle est trouvé.** Un fil regarde la vidéo pendant la rotation et note, pour chaque image, l'angle du
  plateau et où est le QR (ou un trou) dans l'image. Le QR passe au centre de l'image à l'angle `a_c` du plateau
  (droite « position dans l'image en fonction de l'angle », donc aucune échelle à connaître). Au centre de l'image,
  le QR est à l'azimut de la caméra vu de l'axe du plateau (−122°, fiche, figé). Oreilles de l'anse = azimut de la
  caméra + (angle du plateau maintenant − `a_c`) + écart attaches/QR du seau. Les passages successifs du même QR
  (début et fin du tour) sont séparés (`ecart_passage_deg`).
- **Une lecture seule ne compte que si le QR est au centre** (`centre_tolerance_px`) : sinon on a besoin d'au moins
  deux lectures à des angles différents.
- **Angle caméra → rouleau** = azimut du rouleau (−90°, côté −y de l'axe : la tête vient du mur, EXEMPLE) moins
  azimut de la caméra, soit ≈ 31,8° (le simulateur en avait déjà mis 32). Si la caméra ne vise pas l'axe du plateau
  (`cap_deg`), il dépend du rayon de la paroi, donc du format. `vidange-micropore apprendre` l'utilise quand
  `--camera-rouleau` n'est pas donné ; l'option force toujours.
- **Les trous** : taches rondes de la taille d'un trou (Ø ≈ 1 cm, `echelle_mm_par_point`) suivies d'une image à
  l'autre ; l'angle du plateau où chacune passe au centre. Les rangées sont reconnues à la hauteur des trous dans
  l'image (la rangée la plus haute du seau est la plus haute de l'image, `haut_en_haut`).
- **Le morceau posé** (geste 11) : « couvert » veut dire un morceau de la bonne taille (30 × 25 mm ± 25 %), droit
  (au plus 10° de l'horizontale), qui recouvre le trou avec 2 mm de marge. Découvert, de travers, mal coupé ou
  décalé : pas couvert (un nouvel essai, puis alerte, comme la fiche).
- **Écart attaches/QR d'un seau** : fichier `donnees/ecarts-attaches.json` (`vidange-vision ecart CODE DEGRES`), sinon
  `flanc → ecart_attaches_defaut_deg` (EXEMPLE 0). Le journal dit quand le réglage sert.
- **Reste un faux avec son interface (comme la tâche 22 ter)** : la reconnaissance des **attaches de l'anse**
  (`ReconnaissanceAttaches`, faux `FausseReconnaissanceAttaches` : elle ne trouve rien), qui donnerait l'écart au
  premier passage ; le **diamètre du bord du seau** (`Reperage.diametre_bord_m` reste vide : le Micropore refuse déjà
  un format dont le bord dépasse 29,5 cm d'après `machine.yaml`) ; le jugement « bien collé » (pas dans la fiche).
- **Sur la vraie machine** : « qr_du_flanc » et « micropore » ne sont plus « pas écrits ». Ils attendent
  `inspection → exemple: false` (seule cette partie compte : le haut de `vision.yaml` est celui des autres caméras),
  la caméra ouverte, puis le reste : cartes du chariot (angle du plateau : le QR du flanc attend « seau_vide ») et de
  la tête (le micropore). Le journal et l'écran le disent.
- **Choix de Claude (tâche 40 ter, en attendant les réponses de Karulium)** :
  1. Un trou vu sur une seule image n'est pas compté (on ne peut pas dire où il est au centre) ; un trou coupé par le
     bord de l'image non plus.
  2. Les lumières de la caméra (carte du fil Guidage caméra, éteintes après 2 s sans ordre) ne sont pas commandées ici.
  3. L'angle du plateau est celui que lit la carte du chariot au moment où l'image est regardée ; le retard de
     l'image n'est pas corrigé (à mesurer à l'essai).
- **Vision du micropore, réponses à la PR n° 92** (tâche 40 ter, 07/11/2026, niveau 1, tranché par Claude) :
  1. Écart attaches de l'anse / QR : une seule valeur dans les réglages (`ecart_attaches_defaut_deg`) tant que les
     QR sont collés de la même façon sur tous les seaux ; sinon `vidange-vision ecart` seau par seau. La
     reconnaissance des attaches par la caméra viendra avec les photos réelles (tâche 22 ter).
  2. Visée de la caméra (axe du plateau) et rouleau à −90° : supposés ; mesurés à la main une fois par format à
     l'essai (essai-micropore.md, étape 7), forcés avec `--camera-rouleau` si l'écart dépasse 2°.
  3. La caméra voit-elle les deux rangées de trous à la hauteur du poste ? Non : réponse du fil Micropore (07/11),
     une seule rangée par image (voir le point 7).
  4. Lumières de la caméra : petite tâche à part quand les ordres de la carte de lumières seront écrits (Guidage
     caméra).
  5. Pas de jugement « bien collé » (plis, bulles) pour l'instant ; à revoir après les premières photos réelles.
  6. Pas de mesure du diamètre du bord à la caméra : le format vient de `machine.yaml`.
  7. Réponses du fil Micropore (07/11), appliquées sur la même branche :
     - **Une seule rangée de trous par image.** Caméra fixe sur le plateau, objectif à z 0,600, à environ 5 cm de
       la paroi, voit ±3,5 cm (±2,5 cm utiles), rangées à 10–17 cm l'une de l'autre. Donc **un tour de repérage
       par rangée**, plateau à « 0,600 − hauteur de la rangée », juste avant de poser cette rangée à la même
       station (rangée du haut : au poste, seau vide ; rangée du fond : une fois le poids minimum atteint). Le
       z de l'objectif et les autres chiffres sont dans `vision.yaml → inspection → geometrie` (EXEMPLE). La
       reconnaissance de « deux rangées dans une image » est supprimée.
     - **QR du flanc** : `plateau_lecture_qr` = 0,600 − hauteur du centre de l'étiquette (14 cm du fond pour
       tous les formats) = 0,46 (EXEMPLE). **Pas lu au poste** (règle C2 : bord ≤ 0,68 ; trois formats sur
       quatre la touchent). Lu avant le poste, là où rien n'est au-dessus du seau : le cycle le lisait déjà à
       y 0,50 (pose du seau) ; aucune règle de positions n'y limite la hauteur, la limite du fil Micropore
       (0,75 − hauteur) est dans `lecture_qr_bord_max_z` (le bord le plus haut : 0,46 + 0,265 = 0,725). Gardé :
       `lecture_qr_y: 0.50` (réglage ; peut être mis à la position de vidage).
     - **Contrôle au démarrage** : `plateau_lecture_qr` + hauteur du seau (chaque format) ≤ limite de hauteur
       de la position de lecture (0,68 si c'est le poste, sinon `lecture_qr_bord_max_z`) ; erreur claire sinon.
       Aussi : `plateau_lecture_qr` = `objectif_z_m` − `etiquette_hauteur_m`.

## Programme principal, cartes du chariot et de la tête (tâche 45 ter, 07/11/2026)

Code : `pi/vidange/cycle/machine.py` (`construire_cartes`, `CartesMachine`, `PiecesMachine`), branché dans
`pi/vidange/demarrage.py` ; essai : `pi/systeme/essai-cartes-chariot-tete.md` (testé sur le vrai matériel : non).
Aucun chiffre nouveau : tout vient de `docs/entrees-sorties.yaml`, `fluidnc.yaml`, `pesees.yaml` et `machine.yaml`.

- **Construites une fois, au démarrage**, comme le font les outils d'essai (`vidange-remplissage`,
  `vidange-prehension`, `vidange-micropore`, `vidange-lavage`), sur les liaisons et le bus des pesées du
  programme (une seule liaison par carte) : chariot (`ChariotFluidnc` et la balance de la carte du plateau),
  boîtier du chariot (PCA9685 et ToF lus par la carte du plateau), tête du micropore (`TeteMicropore`), bras de la
  fermeture (`BrasFermeture`), moteur d'avance du ruban (`AvanceFluidnc`), tête de la Préhension
  (`TeteFluidnc` et `Prehension`), Lavage (`Lavage` et `EauLavage`) ; la carte du spray est seulement regardée
  (le Spray est déjà construit par le démarrage).
- **Une pièce absente n'arrête jamais le démarrage** : elle n'est pas construite et les postes qui en ont besoin
  disent « pas lancé : raison » (journal, check-list « cartes du chariot et de la tête », écran). Absente veut
  dire : signal absent de la liste ; sur la vraie machine, ligne `exemple: true` (le signal ou sa carte),
  `fluidnc.yaml` ou `pesees.yaml` en EXEMPLE, programme d'une carte de pesée ou du spray fait avec des réglages
  d'EXEMPLE ; carte FluidNC dont le numéro de série USB n'est sur aucun port ; carte du bus qui ne répond pas
  (adaptateur débranché, carte muette, HX711 muet, PCA9685 ou ToF muet) ; réglage qui ne va pas (signal
  absent de `fluidnc.yaml`...).
- **Postes et pièces** : seau_vide et couvercle → chariot, tête ; qr_du_flanc → (vision) chariot ; micropore →
  (vision) chariot, tête du micropore, moteur d'avance ; fermeture → chariot, bras ; spray → carte du spray ;
  entonnoir → tête ; lavage_bocaux → tête, Lavage.
- **Choix de Claude (tâche 45 ter, en attendant les réponses de Karulium)** :
  1. La présence est regardée **une seule fois, au démarrage** (les états des postes sont calculés à ce
     moment-là, comme avant) : une carte branchée après demande de relancer le programme. Une carte qui tombe
     pendant un lot est vue par les conditions du chef (« carte connectée et sans alarme »), comme avant.
  2. **Rien n'est commandé au démarrage** : aucun ordre aux servos, aucune sortie FluidNC, pas de recalage du
     zéro du vide. Les boucles en fond de ces pièces (balance, vide, battement des servos) partiront avec le
     lot, quand `PiecesMachine.remplissage` sera écrit.
  3. Sans le Mycélium (pas construit ici), la manivelle est inconnue pour la Préhension : la tête ne va jamais
     dans la zone du porte-bocal. Les angles gardés de la tête sont le même fichier (et le même objet) que
     ceux du retour en lieu sûr.
  4. `PiecesMachine.remplissage`, `entonnoir` et `lavage_bocaux` restent non écrits : ils ne sont jamais
     appelés tant que le mycélium (bocal neuf), la griffe et la photo du plafond manquent. Avec les cartes
     là, il restera à y assembler le Mycélium (agitateur, porte-bocal), le Stockage, le Micropore, la
     Fermeture, le Couvercle et le Spray, comme dans `vidange.cycle.simulation`.
- **Cartes du chariot et de la tête, réponses à la PR n° 93** (tâche 45 ter, 07/11/2026, niveau 1, tranché par Claude) :
  1. Le lot complet sur les vraies cartes (`PiecesMachine.remplissage`, `entonnoir`, `lavage_bocaux`) : tâche 45 quater,
     juste après le geste du bocal neuf de semence (tâche 19 quater), avant la tâche 23.
  2. Une carte branchée après le démarrage ne compte qu'après une relance du programme : gardé ; un bouton
     « relire les cartes » sur la page web viendra peut-être plus tard.
  3. Une carte du spray programmée avec des réglages d'EXEMPLE bloque le poste spray sur la vraie machine : gardé.

## Bocal neuf de semence (tâche 19 quater, 07/11/2026)

Code : `pi/vidange/bocal_neuf/` (`BocalNeuf`), `pi/vidange/mycelium/` (étape « changer_de_bocal » branchée),
`pi/vidange/prehension/` (pas `cale`, `geste_poser_bocal` complété), `pi/vidange/cycle/machine.py` (agitateur et
porte-bocal construits) ; essai : `pi/systeme/essai-bocal-neuf.md` (testé sur le vrai matériel : non). Source : la
fiche `prehension/logiciel/bocal-neuf-pour-logiciel.md` du 07/11/2026, recopiée dans `docs/taches.md`. Les chiffres
sont dans `pi/reglages/machine.yaml` (partie `bocal_neuf`, `exemple: true`) ; seuls ceux de la fiche ne sont pas des
exemples (hauteur du bocal, angles, 360° au plus, essai à 120° puis tous les 60°, 3 mm, 5 mm, 0,3 s, 3 cm, ± 8 mm,
± 3 mm, ± 2 mm, ± 30 g, erreur du codeur 2° pendant 0,2 s).

- **Le geste est à la Préhension** : le Mycélium ne fait que le lancer (manivelle en bas) et attendre sa fin
  (`Pas(bocal_neuf=True)`, interface `PoseBocalNeuf`). Sans lui (essais, anciens scénarios), `nouveau_bocal` rend
  tout de suite un bocal, comme avant.
- **Six phases, reprenables** : dévissage, capsule rangée, couvercle percé pris, vissage, pose, départ. Une alarme au
  milieu garde la phase en mémoire du programme ; après le Go, le geste reprend là où il s'est arrêté si la tête
  tient ce que la phase attend, sinon il repart du début (avec un message). Une coupure du programme n'est pas
  reprise (le bocal et la capsule sont alors à regarder à la main).
- **Le QR part avec la capsule** : le Pi lit le QR juste avant la prise (2ᵉ lecture) et le recopie au registre
  AVANT le premier mouvement. QR illisible ou d'une autre variété : le bocal n'est pas pris, sa place est marquée
  « à vérifier » (inventaire et registre) ; un autre bocal de la variété est pris après le Go.
- **Échec du dévissage (étape 5a)** : capsule qui tient encore à 360°, moteur qui cale, poussée qui ne se tient
  pas, palier incohérent : la capsule est reposée (aimants coupés), la tête remonte, le bocal reste marqué.
- **Le calage du moteur** vient de l'erreur du codeur de la rotation (`TeteFluidnc(erreur_codeur=...)`). La
  machine n'a pas encore cette lecture : sans elle, le geste refuse de partir (aucun mouvement) et le poste
  « mycelium » est « pas lancé : raison » sur la vraie machine (aussi : QR du bocal par la caméra de la tête de la
  griffe, pas branchée).
- **Choix de Claude (en attendant les réponses de Karulium)** :
  1. Le bocal vide du porte-bocal n'est pas repris (fiche, § 4 point 5, pas écrite) : les mors s'ouvrent et la
     machine demande de l'enlever à la main (case vide `reprendre_le_vide`).
  2. Un lot de 20 seaux demande 20 bocaux (un bocal par seau A) : plus que les 18 places de semence et que les 18
     capsules de la boîte. Au simulateur, Karulium « recharge » entre deux bocaux (`cycle → bocal_neuf →
     reapprovisionne`). Sur la machine, il faudra une pause de rechargement en milieu de lot.
     *Remplacé par la tâche 45 quater* : plus de rechargement ; un lot a au plus autant de seaux que de bocaux de
     semence posés de sa variété, de places libres dans la boîte des capsules et de couvercles percés (18).
  3. Le lot simulé complet dure maintenant ≈ 3 h 50 (≈ 2 min 45 de plus par seau) : `duree_max_s` du simulateur est
     passé de 14400 à 21600 s.
  4. Le Pi ne commande jamais le couple de serrage C_vis (≈ 1,5 N·m) : il se règle sur le pilote, à la main.
- **Cartes du Mycélium dans `cycle/machine.py`** : « agitateur » (`AgitateurFluidnc` sur la carte
  `mycelium_lavage`, balance du plateau) et « porte_bocal » (`PorteBocalFluidnc`), construits comme les autres
  pièces ; la Préhension voit le porte-bocal et la manivelle (zone du porte-bocal). Absents ou en EXEMPLE sur la
  vraie machine : le poste « mycelium » dit pourquoi.
- **Bocal neuf, réponses à la PR n° 94** (tâche 19 quater, 07/11/2026, niveau 1, tranché par Claude sauf le point 5) :
  1. « Le moteur cale » : lire l'erreur de suivi du pilote en boucle fermée de la rotation (carte n° 4), avec la
     tâche 24 (dérive de position) ou la 45 quater si elle arrive avant. D'ici là, le geste refuse de partir sur la
     vraie machine.
  2. Bocal qui tourne sur la tôle pendant le dévissage : tapis silicone de 1 mm sous les 18 places (la Préhension le
     fait ajouter, 07/11) ; couple d'ouverture d'un vrai bocal stérilisé à mesurer par Karulium.
  3. Masses (capsule, couvercle percé, bocal plein) et résolution du palier pesé : à peser par Karulium ; si une
     capsule est trop légère pour le palier, l'étape 5 passera au couple.
  4. Reprise du bocal vide : tâche à part ; d'ici là, les mors s'ouvrent et la machine demande de l'enlever à la
     main.
  5. Lot de 20 seaux pour 18 bocaux de semence et 18 capsules : question de capacité posée à Karulium (07/11) ;
     recommandation : 18 seaux au plus par lot, sans pause.
  6. Tenue d'un bocal plein par les 3 électroaimants au choc du transport : à voir au premier essai.

## Programme principal, le lot sur les vraies cartes (tâche 45 quater, 07/11/2026)

- **Le lot se lance en deux temps (règle 6)** : la page web (onglet « État », carte « Lancer un lot ») PROPOSE un
  « Lot de seaux » (format, nombre, variété de la semence) ou un « Lot de bocaux » (nombre) ; rien ne bouge. Le lot
  part au Go de Karulium sur l'écran de l'armoire (page d'état « ATTEND LE GO », bouton GO puis « Oui »). Pas de Go
  de lot par l'API. Une seule proposition à la fois, oubliée après `programme.yaml → lot → proposition_max_s`.
- **Refus avec la raison**, au bouton et de nouveau au Go : mode autre que « production », un lot (ou le retour en
  lieu sûr) déjà en route, un poste « pas lancé : raison », format inconnu, et la taille du lot.
- **Taille du lot, un seul endroit** (`refus_taille_lot`, `vidange/cycle/mode_seaux.py`) : au plus autant de seaux
  que de bocaux de semence posés de leur variété, de places libres dans la boîte des capsules et de couvercles
  percés (18 aujourd'hui). Pas de pause de rechargement : si on la veut un jour, c'est là qu'elle s'ajoute (une
  pause avec Go). Le simulateur suit la même règle (lot de 18, plus de « rechargement par Karulium »).
- **Seaux sans nom d'avance** : les seaux d'un lot lancé depuis la page web prennent le QR lu sur leur flanc.
- **`PiecesMachine.remplissage`** assemble le Remplissage, le spray, le Micropore, la Fermeture, le Mycélium, le
  bocal neuf, le couvercle et le plan à partir des vraies cartes. Il reste « pas lancé : raison » tant que manquent
  les cartes de la griffe (enchaînée depuis la tâche 45 sexies), le QR du bocal par la caméra de la tête de la griffe, l'erreur du codeur
  de la rotation de la tête (carte n° 4) ou une carte en EXEMPLE. **`entonnoir`** et **`lavage_bocaux`** attendent la
  photo du plafond (bande du haut, entonnoir, bocaux sales) et le versement de la griffe. Le stockage aussi : sur la
  vraie machine, pas de lot sans la photo de la bande.
- **Boucles de fond du lot** (`FondDuLot`, `vidange/cycle/machine.py`) : au Go, la balance du chariot, la balance de
  l'agitateur, le boîtier du chariot (battement des servos), le bras de fermeture et la tête (vide) partent juste
  avant le lot ; si elles ne partent pas, le lot n'est pas lancé. Elles s'arrêtent sur alarme et à la fin du lot, et
  repartent après « RÉPARÉ » et le Go. La tête coupe vanne et aimants et recale le zéro du vide seulement au premier
  départ ; ensuite elle ne relance que sa surveillance (un objet tenu n'est pas lâché). Après une reprise du carnet,
  rien n'est commandé avant le Go. Périodes dans `programme.yaml → lot` (vérifiées : plus courtes que le battement
  des servos).
- **Questions posées à Karulium (PR de la tâche 45 quater)**, avec la recommandation de Claude appliquée en
  attendant : 18 seaux au plus par lot, sans pause ; saisie de l'inventaire du stockage (bocaux de semence, boîtes)
  depuis la page web dans une tâche à part ; variété demandée dans le formulaire ; stockage bloqué sans photo de la
  bande ; vanne coupée au premier départ du lot.
- **Lot sur les vraies cartes, réponses à la PR n° 95** (tâche 45 quater, 07/11/2026, niveau 1, tranché par Claude sauf le point 1) :
  1. Taille du lot (18 au plus sans pause, ou pause de rechargement avec Go) : question posée à Karulium (07/11) ;
     d'ici sa réponse, 18 au plus sans pause (code : `refus_taille_lot`, un seul endroit).
  2. Saisie de l'inventaire du stockage (bocaux de semence, boîtes, piles de seaux) depuis la page web : tâche 45
     quinquies.
     Faite (PR de la tâche 45 quinquies) : la page propose la correction (avant → après), un second bouton « Confirmer
     (Go) » de la page l'écrit (pas l'écran de l'armoire : des nombres corrigés ne font bouger aucune machine) ;
     refusée pendant un lot ; journal avant/après ; `refus_taille_lot` lit l'inventaire corrigé.
  3. Variété dans le formulaire du lot : gardée.
  4. Stockage bloqué sur la vraie machine tant que la photo de la bande du haut n'est pas lue (tâche 22 ter) : gardé.
  5. Vanne de la tête coupée au premier départ du lot (machine à vide, mesure du vide recalée) : gardé.

## Solveur d'ordonnancement (tâche 23, 07/11/2026)

Choix tranchés par Claude (PR de la tâche 23), en attendant les réponses de Karulium :
1. **Ce que le chef reçoit** : pour chaque zone tenue par plusieurs modules, l'ordre de passage et l'heure prévue
   (`vidange/chef/programme.py`). Il ne s'en sert que pour choisir qui passe le premier quand plusieurs modules
   attendent la même zone ; un module pas prêt laisse passer les autres (le programme ne bloque personne et
   n'autorise rien de plus). Seulement si `solveur → actif` (faux par défaut) ; pas noté dans le carnet : après
   une coupure, ordre normal.
2. **Recul à l'ordre normal**, noté au journal : première alarme, module qui prend une zone hors de son tour,
   passage plus tôt ou plus tard que prévu de plus de `solveur → ecart_max_s` (EXEMPLE 30 s).
3. **Tâches** : tirées d'un lot joué dans l'ordre normal ; ce qu'une étape a attendu (condition) est gardé : la fin
   d'une tâche d'un autre module finie au même instant, sinon le même temps d'attente. Une zone est tenue sans
   trou d'une étape à la dernière qui la tient encore. Le Go est un point d'arrêt.
4. **Vérification** : le simulateur rejoue le programme ; rejeté si le cycle s'arrête, si le chef quitte le
   programme, si une zone est tenue deux fois, si les étapes faites ne sont pas les mêmes, si l'ordre du cycle
   d'un seau n'est pas suivi, ou s'il est plus long que l'ordre normal.
5. **Gain sur le lot simulé de 18 seaux : 0 s.** Le Remplissage et le Mycélium s'y suivent par des conditions,
   aucune zone n'y est partagée ; le solveur servira quand la griffe et la préhension (même pont) seront écrites.
   `vidange-simulateur cycle --solveur` le montre.
6. **Sur la vraie machine, aucun programme n'est encore calculé** (question n° 1 de la PR) : le chef sait le jouer,
   le programme principal ne le lui donne pas encore.
- **Solveur, réponses à la PR n° 97** (tâche 23, 07/11/2026, niveau 1, tranché par Claude) :
  1. Calcul du programme sur la vraie machine : rien n'est branché tant que le gain est nul. Quand la griffe et la
     préhension (même pont) seront écrites, le Pi le calculera pendant que la proposition de lot attend le Go, et ne
     s'en servira que si `solveur → actif` est vrai et le programme accepté par le rejeu.
  2. `solveur → ecart_max_s` : 30 s (EXEMPLE) pour les premiers lots, resserré quand les durées seront recalées sur
     les vrais temps.
  3. Une Pause pendant un programme : retour à l'ordre normal du chef (gardé, simple et sûr).

## Programme principal, la griffe dans les lots (tâche 45 sexies, 07/11/2026)

- **Construite au démarrage** comme les autres pièces (`PiecesMachine`, pièce « griffe ») : bras FluidNC sur la
  carte du portique, pesée RS485 de la griffe, poste du fût. Une absente dit « griffe : pas lancé : raison » ; le
  démarrage continue. `Sources.griffe` et `Sources.versement_bocal` à None veulent dire maintenant « la vraie »
  (un faux ne sert qu'aux essais). Postes : `griffe` (seaux) demande griffe, tête et chariot ; `versement`
  (bocaux) demande griffe et tête. La boucle de fond du bras part au Go avec les autres.
- **Mode seaux** (`vidange/cycle/griffe_du_lot.py`, `GriffeDuSeau`) : module « griffe » du lot à côté du
  Remplissage et du Mycélium. L'étape « verser » du Remplissage dit à la griffe quelle couche le seau attend et
  finit quand elle est versée et tassée (seau arrêté) ; délai `durees → remplissage_couche_griffe_max` (EXEMPLE
  1800 s). Le Mycélium et les gestes de la tête du Remplissage attendent la griffe garée. Le carnet garde le seau
  en cours et les couches versées (reprise après coupure).
- **Mode bocaux** : `vidange.griffe.versement` (tâche 43 bis) branché comme versement du lot, sur la griffe des
  cartes (maïs, sans mâchouiller), fichier `donnees/versement.json`.
- Les zones et les règles du Portique restent celles du chef et des règles de chaque bras : rien de nouveau n'est
  inventé, seulement vérifié aussi quand un bras traîne l'autre.
- **Choix de Claude (PR de la tâche 45 sexies)**, en attendant les réponses de Karulium :
  1. La griffe ne descend dans le fût (raclage, prise) que quand un seau l'attend au vidage : sinon, griffe dans
     le fût avec sa dose et Préhension qui a besoin du pont, chacun attend l'autre (ou le mât est traîné dans le
     fût). On perd la prise « d'avance » pendant le spray et le dosage du mycélium.
  2. Pont partagé : un pas de la Préhension qui bouge le pont ou le chariot traîne la griffe (en butée haute) ;
     les règles de **position** de la griffe sont vérifiées le long du trajet (pas ses règles de trajet). Un pas
     de la griffe qui bouge le pont fait vérifier toutes les règles de mouvement de la tête de préhension.
     Position inconnue : refusé. Un pas refusé ne part pas (alarme).
  3. Fût vide en plein lot : la griffe finit le seau commencé (tassement, essuyage), puis attend le « Prêt » d'un
     nouveau fût et continue au seau suivant. Un seau qui n'a pas toutes ses couches arrête l'étape « verser » sur
     une alarme (case vide : question n° 2). Dernier seau du lot plein, fût pas vide : le module finit.
  4. « Griffe partie du poste » (sortie du bras du spray, pose du couvercle) = le mât de la griffe hors du seau du
     vidage (`griffe → vidage → zone_seau_m`), pas « au-dessus du fût » : la Préhension traîne la griffe loin du
     fût quand elle prend ou pose un seau.
  5. La Préhension, avant de descendre à sa hauteur de trajet, sort d'abord de l'isolation du fût face en haut
     (nouveau pas « sortir de l'isolation du fût, face en haut ») : sinon, traînée au-dessus du fût par la griffe,
     elle descendait dans l'isolation.
- **Restent des cases vides** : ce qu'on fait d'un seau commencé quand le fût se vide ; le capteur de distance de
  la tête de la griffe (VL53L1X, bouchage de l'entonnoir) ; le QR du bocal par la caméra de la tête ; l'erreur du
  codeur de la rotation de la tête ; la photo du plafond ; le lavage lancé après le lot.
- **La griffe dans les lots, réponses à la PR n° 99** (tâche 45 sexies, 07/11/2026, niveau 1, tranché par Claude) :
  1. Dose « d'avance » pendant le spray ou le dosage : non pour l'instant (la fiabilité d'abord) ; à revoir avec le
     solveur quand les vrais temps seront mesurés.
  2. Seau commencé quand le fût se vide : alarme, le seau est fini à la main (gardé) ; question posée à Karulium
     (07/11) : le finir avec le fût suivant ?
  3. Vérification des zones de l'outil traîné par le pont, même en butée haute : gardée, confirmée par le fil Portique
     (07/11/2026, `portique/logiciel/bras-traine.md`) : « butée haute = aucune collision » ne vaut que pour les pièces
     du portique ; l'outil traîné garde ses zones avec son enveloppe en butée haute (points bas ≈ 1,065 griffe,
     ≈ 1,10 préhension) et sa charge (seau pendu à la préhension ≈ 0,83), et ses propres règles (préhension traînée
     en haut : mât à y ≤ 0,80). Le refus de la préhension au-dessus du porte-bocal est juste.
  4. « Griffe partie du poste » ne suffit pas (fil Spray, 07/11/2026) : le bras du spray ne sort et ne rentre que si
     aucune partie de la tête de la griffe, de la préhension ou de ce qu'elles tiennent n'est dans la zone
     **x 0,66-0,95, y −0,03-0,24, z < 0,85** (EXEMPLE, à vérifier par un balayage de la Maquette). C'est la zone qui
     fait foi, pas le moment. À coder dans une tâche suivante (45 septies) ; d'ici là, sur la vraie machine, aucun
     lot ne part (réglages de la griffe en EXEMPLE).
  5. Délai d'une couche `durees → remplissage_couche_griffe_max` : 30 min (EXEMPLE) pour les premiers essais.

## Réponses des fils du 07/11 : bocaux, zone du bras du spray, couvercle C (tâche 45 septies, 07/11/2026)

Sources (recopiées) : `griffe/logiciel/reponses-07-11.md`, `griffe/logiciel/garde-camera-bocal-maquette.md`
(Maquette v45.120), `prehension/logiciel/tete-basse-versement-bocaux.md`, `prehension/logiciel/
pose-couvercle-pour-logiciel.md` § 5.1, fil Spray (07/11, déjà recopié dans « La griffe dans les lots, réponses à
la PR n° 99 », point 4). Code : `pi/vidange/griffe/` (règles, versement), `pi/vidange/spray/zone.py`,
`pi/vidange/couvercle/couvercle.py` ; réglages `machine.yaml` ; essais : `essai-versement-bocal.md` (étape 7),
`essai-spray.md` (étape 10), `essai-couvercle.md` (étape 4, point 7). Testé sur le vrai matériel : non.

- **Godet ouvert au-dessus des bocaux (fil Griffe)** : aucune limite en y propre à la griffe, ni à 20° ni à 35° ;
  la rangée 1 (mât y 0,06) passe. Le « y ≥ 0,11 » n'était qu'un cylindre prudent de rayon 0,174 autour du mât.
  Tête à A = 0, mât en y 0,06 : à 35°, les joues des coquilles vont à y −0,105 (z 0,83-0,94), 14,5 cm du mur du
  conteneur (y −0,25) ; haut de la chape et goupilles à y −0,028 (z 1,10-1,19), 2,7 cm des pièces du pont côté mur
  (y ≤ −0,055, jamais sous z 1,118). Seules limites : la course du chariot Y (mât y ≥ 0,04, Portique 14/10, **à
  revérifier** depuis les rails HGR15) et la garde du boîtier de la caméra du bocal. Réglage :
  `griffe → godet_ouvert_sans_y_min: [1.10, 2.70]` (mât au-dessus du stockage, comme la fiche) ; ailleurs, le
  0,11 reste (aucun versement godet ouvert sous y 0,11 hors du stockage).
- **Garde du boîtier de la caméra du bocal (Maquette v45.120)** : la bande s'arrête à **mât x 1,205** (avant :
  1,207) : 9 mm de jeu à 1,205, 11,5 mm pour la colonne x 1,2075, de la butée haute au versement, godet fermé ou
  ouvert (le plus proche : le support du servo de la caméra, x 1,085). Valable tête à A = 0 seulement. La ligne
  « 1,15 – 1,20 » de la table « y minimum du mât » (sous la butée haute) devient **1,15 – 1,204**, sans
  l'élargir d'1 cm : `bocal_0_0` et `bocal_2_0` sont permis.
- **Dernière rangée (y 0,8224), tête de préhension basse (fil Préhension)** : oui, avec 3 conditions : 1) la tête
  de préhension ne porte rien (aimants coupés, vide à l'air) ; 2) elle ne descend et ne remonte qu'au-dessus du
  plateau du haut, **préhension à x ≥ 1,20** (figé) ; ailleurs elle reste à 1,10 ; 3) elle descend à la face
  **0,90** (au plus 0,942 ; 0,90 proposé, EXEMPLE) **avant** que le mât de la griffe passe y 0,80, et remonte
  **après** son retour à y ≤ 0,80. Pendant ce temps le pont peut rouler en x (30 cm au-dessus des capsules).
  Vitesses du Portique (Z 80 mm/s). Réglages : `griffe → versement_bocal → tete_basse`
  (`prehension_face_basse_versement`, `prehension_x_min_tete_basse`) ; « griffe_y_max_tete_haute » (0,80) est
  `portique → chaine_prehension → mat_y_max`, pas recopié. Vérifié au démarrage pour chaque bocal de la rangée.
- **Choix de Claude pour la tête basse (tâche 45 septies)** : c'est le versement qui commande la tête de
  préhension (même pont) : la griffe, avec sa dose, va au-dessus du col à y 0,80, la tête descend, puis la griffe
  avance jusqu'au col ; après le versement, la griffe revient à y 0,80 en butée haute, puis la tête remonte. Avant
  d'aller au fût, le versement remonte aussi une tête de préhension laissée plus bas que 1,10 (la Préhension,
  au-delà de y 0,80, s'arrête à 0,942). Tête qui tient un objet, qui bouge, ou sous x 1,20 : alarme, rien ne bouge.
  Traînée par le pont, la tête basse du versement n'a que ses règles de position (et x ≥ 1,20) ; toute autre tête
  basse garde la règle « tête en haut avant de bouger le pont ».
- Résultat : `vidange-entonnoir versement` ne refuse plus **aucun** des 122 bocaux (29 avant). Il dit aussi les
  bocaux où la Préhension ne peut pas **poser l'entonnoir** parce que la griffe, traînée en butée haute, irait
  au-dessus de l'agitateur (table « y minimum du mât » en butée haute) : `bocal_0_0`, `bocal_0_1`, `bocal_1_0`,
  `bocal_2_0` (question à Karulium, PR de la tâche 45 septies).
- **Zone du bras du spray (fil Spray)** : le bras ne sort **et ne rentre** que si aucune partie de la tête de la
  griffe, de la préhension ou de ce qu'elles tiennent n'est dans **x 0,66-0,95, y −0,03-0,24, z < 0,85**
  (`spray → bras → zone`, EXEMPLE tant que la Maquette ne l'a pas balayée). C'est la zone qui fait foi :
  « griffe partie » (`GriffeDuLot.partie()`) ne sert plus au spray (il reste pour la pose du couvercle). Code :
  `vidange.spray.zone.ZoneDuBras`, condition d'entrée de « sortir le bras » et de « ranger le bras » (seau et
  nettoyage des tubes). Chaque outil est regardé là où il est (traîné ou non) : griffe = son encombrement depuis
  le bas du godet ; préhension = la tête (face) et l'objet tenu (bas = face − ce qui pend, axe décalé pour
  l'entonnoir). Position inconnue : pas libre. Pas fait : un verrou qui empêcherait la griffe ou la préhension
  d'entrer dans la zone **pendant** que le bras bouge (question à Karulium).
- **Couvercle C (fiche de la pose, § 5.1 ; Maquette v45.120 : au moins 10,3 mm partout)** : ce qui limitait (2,3 mm)
  est la plaque FIXE du micropore (bord à r 160 de l'axe du seau) et le bout de son rail (r 164), pas sa tête
  mobile. **Le recul du servo du micropore est annulé** (le oui de Karulium du 07/11 13:44 est sans objet ; il
  n'avait pas été codé, rien à enlever). Format C seulement : outil en **(0,925 ; 0,498)** de la face 0,70 à
  **0,545**, puis retour à **y 0,49** à face constante à **10 mm/s**, puis descente normale jusqu'au contact
  (plaque 10,3 mm, rouleau 12,8, rail 13,5, côté allée rien à moins de 4,8 cm ; au recentrage et ensuite :
  15,2 mm). A, B et D descendent droit. Réglage : `couvercle → formats → seau_c → descente_decalee` (remplace la
  descente lente 0,67 → 0,57). Le seul pas du pont permis tête basse avec un couvercle est ce recentrage (règles
  de la préhension).
- **Choix de Claude pour le couvercle C (tâche 45 septies)** : la tête qui remonte **avec** le couvercle C (erreurs
  10a et 10b) refait le même chemin à l'envers (face 0,545, retour à y 0,498, puis en haut) : la remontée droite
  repasserait à 2,3 mm de la plaque du micropore (question à Karulium).
- **Réponses à la PR n° 100** (tâche 45 septies, 07/11/2026, niveau 1, tranché par Claude) :
  1. Entonnoir sur `bocal_0_0`, `bocal_0_1`, `bocal_1_0`, `bocal_2_0` (griffe traînée au-dessus de l'agitateur) :
     question posée à la Maquette ; d'ici sa réponse, Karulium y pose l'entonnoir à la main.
  2. Tête à −180° au 4ᵉ bocal : corrigé par la tâche 45 octies (chaque prise du mode bocaux finit tête à 0°, dans le
     fût) ; d'ici là, lots de 3 bocaux au plus.
  3. Verrou de la zone du bras du spray pendant qu'il bouge (griffe et préhension n'y entrent pas) : fait dans la
     tâche 45 octies, sans attendre la Maquette (seuls les chiffres de la zone sont EXEMPLE).
  4. Remontée du couvercle C avec la tête : chemin décalé à l'envers, confirmé par le fil Préhension (07/11/2026) pour
     toute remontée avec le couvercle encore tenu ; après le lâcher, la tête seule remonte tout droit (tâche 45 octies).
  5. Décalage du mât de la griffe (dépôt −0,187, fiches de la Maquette et de la Préhension 0,175) : signalé à la
     Maquette.

## Tête à 0° en mode bocaux, verrou de la zone du spray, couvercle C (tâche 45 octies, 07/11/2026)

Code : `pi/vidange/griffe/` (griffe, versement, règles), `pi/vidange/spray/zone.py`, `pi/vidange/prehension/
prehension.py`, `pi/vidange/couvercle/couvercle.py`, `pi/vidange/cycle/` (machine, simulation) ; réglages
`machine.yaml` ; essais : `essai-versement-bocal.md` (étape 8), `essai-spray.md` (étape 11), `essai-couvercle.md`
(étape 4, point 8). Testé sur le vrai matériel : non.

- **Défaut de la tête à −180° (cause)** : à chaque prise, la griffe tourne sa raclette vers le centre du fût
  (angle qui dépend du point de prise) ; en remontant, elle se mettait « bras le long du pont » à l'orientation
  bloquée la PLUS PROCHE (0° ou ±180°, `_vers_le_haut`). Une prise à −100° sortait donc à −180°, et le versement
  (tête à A = 0, fiche) refusait. Ça dépendait du point de prise, d'où le 4e bocal. **Corrigé** : en mode bocaux,
  chaque prise finit tête à `versement_bocal → a_deg` (0°), godet fermé, **dans le fût** (où les demi-tours sont
  permis), avant la sortie (`Griffe._tete_a_dans_le_fut`) ; si la tête ne peut pas tourner là où elle est, elle va
  d'abord au centre du fût. Hors du fût avec un autre angle : alarme, jamais de sortie tournée. Les tests de lot
  sont revenus à 8 bocaux (plus de limite à 3). Le mode seaux ne change pas.
- **Verrou de la zone du bras du spray (choix de Claude)** : tant que la carte ne voit pas le bras **rangé et
  arrêté** (`not Spray.bras_spray_sorti()` : il sort, il est sorti pour la dose, il rentre, ordre en route, carte
  muette), aucun pas de la griffe ou de la préhension n'**entre** dans `spray → bras → zone` : la tête, ce qu'elle
  tient, et l'outil traîné par le pont (enveloppe en butée haute, charge), vérifiés le long du pas. Le pas
  **attend** (il ne part pas) puis part tout seul ; au-delà de `zone → attente_max_s` (120 s, EXEMPLE, au moins
  2 × `temps_max_s`, vérifié au démarrage) : alarme. Un outil déjà dans la zone peut en sortir. Et l'inverse : un
  pas déjà parti qui va dans la zone la rend occupée pour le bras (« sortir » et « ranger » attendent). Pause : rien
  ne part, le temps ne compte pas.
- **Pas par les zones du chef** : un module tient une zone du chef pour toute une étape ; les étapes de la griffe
  (une couche) et de la préhension (un geste) ne passent dans la zone du bras que quelques secondes, et la question
  est géométrique (encombrement, charge, outil traîné). Les réserver bloquerait le spray pendant des étapes
  entières.
- **Couvercle C, toute remontée avant le lâcher (fil Préhension, 07/11/2026, fiche § 5.1)** : « montée droite à
  10 mm/s jusqu'à la face 0,545, décalage à y 0,498 à face constante, puis montée en haut ; après le lâcher, la
  tête seule remonte tout droit ». Ce que la 45 septies faisait pour 10a et 10b, avec en plus : la montée jusqu'à
  0,545 est à 10 mm/s (`descente_decalee → vitesse_m_s`) ; une **pose refaite** après une alarme ou une coupure,
  couvercle C encore tenu dans le chemin décalé, commence par ce chemin à l'envers (avant, elle montait droit) ;
  la **remontée lente après un choc** ne dépasse pas la face 0,545 tant que l'outil n'est pas revenu à y 0,498
  (`Prehension.remontee_droite_max_z`, donné par la pose et remis à rien au lâcher).
- **Réponse de la Maquette (07/11/2026 15:36, `griffe/logiciel/griffe-entrainee-entonnoir-maquette.md`)** :
  1. L'écart du dépôt est juste : griffe = pont − 0,187, préhension = pont + 0,129 (préhension = griffe + 0,316) ;
     rien à changer dans le code ; la table « y minimum du mât » est en x du mât de la griffe. La fiche
     `tete-basse-versement-bocaux.md` de la Préhension mélange 0,175 et 0,129 : à corriger par la Préhension.
  2. Pose de l'entonnoir, griffe traînée en butée haute (axes 1,265) : `bocal_0_0` et `bocal_0_1` CONTACT avec la
     plaque du chariot de l'agitateur, `bocal_1_0` 4 mm de l'écrou M6 du porte-bocal : ces 3 restent posés à la
     main. `bocal_2_0` : « libre, plus de 1 cm ».
- **Choix de Claude pour `bocal_2_0` (tâche 45 octies)** : la Maquette a placé le mât de la griffe à x bocal −
  0,316 (0,8915) ; or la ventouse tient l'**oreille** de l'entonnoir à x bocal + 0,140 (figé), donc le mât de la
  griffe est à x bocal + 0,140 − 0,316 = **1,0315** pour `bocal_2_0`, 14 cm plus loin. La mesure n'est pas à la
  bonne place : **pas d'exception pour l'instant**, `bocal_2_0` reste posé à la main (question à la Maquette, PR
  de la 45 octies). Le moyen est prêt : `griffe → y_min_mat → exceptions_butee_haute` (vide), une zone du mât par
  bocal, figée d'après la mesure, qui doit couvrir la pose finale et le chemin d'approche ; elle ne vaut qu'en
  butée haute, godet fermé, bras le long du pont. Le démarrage refuse une exception dont la zone ne contient pas le
  vrai mât pour ce bocal (`Machine.mat_griffe_entonnoir`), ou qui contient celui d'un autre bocal.
- **Réponses à la PR n° 101** (tâche 45 octies, 07/11/2026, niveau 1, tranché par Claude) :
  1. `bocal_2_0` : la mesure de la Maquette mettait le mât de la griffe à x bocal − 0,316 (tête de préhension au-dessus
     du bocal), alors que la tête est à x bocal + 0,140 pour tenir l'oreille de l'entonnoir : le vrai mât est à
     (1,0315 ; 0,2506). Remesure demandée à la Maquette (en butée haute, avec le chemin d'approche, rectangle
     « libre ») ; d'ici là, `exceptions_butee_haute` reste vide et Karulium pose l'entonnoir à la main.
  2. Verrou de la zone du spray aussi pendant la dose (bras sorti et immobile) : oui (c'est déjà le cas : le verrou
     tient tant que le bras n'est pas vu rangé et arrêté).
  3. Coupure avec le couvercle C tenu sous la face 0,545 : question posée au fil Préhension (la ventouse garde-t-elle
     le couvercle sans courant ?). D'ici sa réponse, ligne de la check-list de reprise : enlever le couvercle à la main
     avant le Go s'il est encore tenu.

## Reprise avec un objet tenu, bocal_0_1 posé par la machine (tâche 45 nonies, 07/11/2026)

Code : `pi/vidange/fiabilite/objet_tenu.py`, `pi/vidange/chef/chef.py` (`empecher_go`), `pi/vidange/demarrage.py`,
`pi/vidange/ecran/ecran.py`, page web, `pi/vidange/quoi_faire.py` ; `pi/vidange/griffe/regles.py`
(`passages_exception`), `pi/vidange/griffe/griffe.py` (`_chemin`), `pi/vidange/cycle/griffe_du_lot.py`
(`chemin_pont`), `pi/vidange/prehension/prehension.py`, `pi/vidange/entonnoir/` ; réglages `machine.yaml`,
`programme.yaml` ; essais : `essai-fiabilite.md` (§ 4 bis), `essai-versement-bocal.md` (étape 9). Testé sur le
vrai matériel : non.

- **Réponse du fil Préhension (07/11/2026), objet tenu à la ventouse à la coupure** : les électrovannes
  « aspirer » et « souffler » sont normalement fermées et un clapet anti-retour garde le vide ; l'objet reste
  d'abord tenu puis peut tomber au bout d'un temps inconnu (sous la face 0,545, un couvercle C tomberait de travers
  sur le seau). Vaut pour tout objet à la ventouse (seau, couvercle, Pétri) ; un objet aux électroaimants (capsule,
  bocal par son couvercle percé) tombe tout de suite. Donc :
  1. check-list de reprise (« quoi faire » des alarmes de coupure et de plantage) : « vérifier la tête et le seau :
     enlever à la main l'objet tenu ou tombé avant le Go » (remplace la ligne provisoire de la PR n° 101, point 3) ;
  2. au redémarrage, **avant tout mouvement**, le Pi lit le capteur de vide : plus bas que
     `prehension → vide → tenu_au_demarrage_kpa` (**−20 kPa**, chiffre du fil, figé) = objet encore tenu →
     l'écran et la page disent « objet encore tenu », et **aucun Go** n'est accepté tant que c'est le cas ;
  3. **jamais** de « souffler » automatique au redémarrage (rien n'est commandé : la vanne n'est pas touchée).
- **Choix de Claude (objet tenu)** :
  - Lecture **brute** (moyenne de `zero_lectures` lectures) : le zéro du capteur n'est recalé qu'au départ d'un
    lot, et il est à ± `zero_ecart_max_kpa` de 0. Vérifié au démarrage : `perte_kpa` ≤ seuil < −`zero_ecart_max_kpa`
    (un vide qui tient encore l'objet ne passe pas ; un zéro décalé ne bloque pas le Go).
  - Le chef refuse **tout** Go (`Chef.empecher_go`, raison dans `EtatChef.go_empeche`) : retour en lieu sûr,
    reprise du cycle, lot (`Lancement.refus_go`) ; le pilotage à distance aussi (c'est un mouvement).
  - Relu tous les `fiabilite → objet_tenu → periode_s` (1 s) jusqu'à ce que le vide remonte au-dessus du seuil ;
    ensuite plus jamais pendant cette marche (la ventouse tient des objets en travail : ce n'est plus une reprise).
  - Vérifié à **chaque** démarrage (coupure, plantage, arrêt propre en plein geste) : sans danger quand rien n'est
    tenu.
  - Capteur absent, en EXEMPLE sur la vraie machine, entrées/sorties fermées ou illisible : pas d'attente (le Pi ne
    sait pas), mais la check-list le dit en « attention » (« vérifier la tête à la main ») — question à Karulium.
  - Objet tenu : point **bloquant** de la check-list. Écran : bandeau « OBJET ENCORE TENU : PAS DE GO », GO éteint.
  - Cette attente protège la machine et le seau, jamais les personnes (sécurité câblée).
- **Réponse de la Maquette (07/11/2026, remesure v45.121, `griffe/logiciel/griffe-entrainee-entonnoir-maquette.md`
  et `carte-griffe-butee-haute-bocaux.txt`)** : mât de la griffe = x bocal − 0,176 (la ventouse tient l'oreille à
  x bocal + 0,140), même y, griffe en butée haute (axes 1,265, point bas ≈ 1,065), godet fermé, tête à A = 0.
  `bocal_0_0` (1,0315 ; 0,06) contact ; `bocal_0_1` (1,1415 ; 0,06) **libre** ; `bocal_1_0` (1,0865 ; 0,1553) moins
  de 1 cm ; `bocal_2_0` (1,0315 ; 0,2506) contact (couvercle du boîtier de la caméra du dosage). Rectangles libres
  (x 0,79-1,30, y 0,04-0,40) : R1 y ≥ 0,32 ; R2 x ≥ 1,22 ; R3 x ≥ 1,10 et y ≤ 0,10 ; R4 x 0,79-0,97 et y 0,22-0,40.
  Interdit : x 0,79-1,09 pour y ≤ 0,16 ; x 0,98-1,21 pour y 0,17-0,31 (caméra du dosage). Chemin pour `bocal_0_1` :
  arriver par R1 ou R2, descendre en y dans R2 jusqu'à y ≤ 0,10, puis en −x dans R3. Pose à la main pour
  `bocal_0_0`, `bocal_1_0`, `bocal_2_0`.
- **Choix de Claude (bocal_0_1)** :
  - `griffe → y_min_mat → exceptions_butee_haute` : une entrée `bocal_0_1`, zone **R3** (x 1,10-1,30, y 0,04-0,10 ;
    la table n'y compte pas, en butée haute, godet fermé, bras le long du pont), `entree_x: 1.22` (bord de R2),
    `libres` R1 à R4 (pour vérifier le chemin), source v45.121. Seule R3 lève la table : R1 et R2 sont déjà permis
    par elle, et R4 n'est pas sur le chemin (mesuré en mode bocaux : on ne l'ouvre pas à tout).
  - Le chemin : tout trajet du pont qui entre dans la zone ou en sort, là où la table seule refuserait le mât
    (`exception_requise`), passe par (1,22 ; y du départ), puis (1,22 ; y de l'arrivée) : en x seulement dans la
    zone, en y seulement à x 1,22. Pour la Préhension (pont traîné : `chemin_pont`, posé par `brancher_pont`), pour
    l'entonnoir tenu (`_transport`) et pour la griffe elle-même (sa sortie vers le fût, puis son trajet habituel).
  - Démarrage : la règle « aucun autre bocal dans la zone » devient « aucun autre bocal **que la table refuse** » :
    R3 contient le mât de `bocal_0_2` (1,2515 ; 0,06), déjà permis. Et : `entree_x` dans la zone, la ligne x =
    `entree_x` sur la hauteur de la zone dans un rectangle libre (R2).
  - `vidange-entonnoir versement` : 3 bocaux posés à la main (`bocal_0_0`, `bocal_1_0`, `bocal_2_0`), 1 posé par
    la machine grâce au chemin (`bocal_0_1`).
- **Écarts vus dans la remesure (questions à Karulium, PR de la 45 nonies)** : la Maquette met la butée haute à
  axes 1,265 (bas ≈ 1,065) ; le dépôt a 1,29 (bas du godet 1,077). Sa carte met aussi le mât de `bocal_2_1`
  (1,1415 ; 0,2506) dans le carré « contact » de la caméra du dosage, que la table du dépôt (v45.111) permet en
  butée haute. Rien de changé tant que ce n'est pas tranché.
- **Réponses à la PR n° 102** (tâche 45 nonies, 07/11/2026, niveau 1, tranché par Claude) :
  1. Capteur de vide muet ou absent au démarrage : pas de refus du Go ; la check-list dit « attention, vérifier la
     tête à la main » (gardé).
  2. Vanne « aspirer » restée ouverte après un plantage du programme : question posée au fil Préhension ; d'ici sa
     réponse, rien n'est commandé au démarrage (jamais « souffler »).
  3. et 4. Hauteur de la butée haute (Maquette 1,265, bas ≈ 1,065 ; dépôt 1,29, bas du godet 1,077) et `bocal_2_1`
     (mât (1,1415 ; 0,2506) dans le carré « contact » de la caméra du dosage sur la carte de la Maquette) : question
     posée à la Maquette (refaire la carte à 1,29). Mesurer plus bas est prudent pour les contacts : `bocal_0_1`
     reste permis ; rien n'est changé pour `bocal_2_1` d'ici sa réponse (l'étape 9 de l'essai mesure ce jeu).
  5. Après l'enlèvement de l'objet à la main, le geste repris part en alarme ou refait sa prise : suffisant pour
     l'instant.

## Vannes de la ventouse fermées au démarrage, carte de la griffe en butée haute à 1,29 (tâche 45 decies, 07/11/2026)

Code : `pi/vidange/fiabilite/objet_tenu.py` (`VannesAuDemarrage`), `pi/vidange/demarrage.py`, `pi/vidange/reglages.py`
(vérification des exceptions) ; réglages `machine.yaml` (`griffe → y_min_mat → exceptions_butee_haute`, commentaires
du bas du godet), `programme.yaml` (`fiabilite → objet_tenu → attente_vannes_s`) ; essais : `essai-fiabilite.md`
(§ 4 ter), `essai-versement-bocal.md` (étape 10). Testé sur le vrai matériel : non.

- **Réponse du fil Préhension (07/11/2026), vannes au démarrage** : après un plantage du Pi, « aspirer » peut rester
  ouverte (rien de matériel ne la coupe ; pas dangereux : le venturi souffle, l'objet reste tenu). Au démarrage,
  fermer **les deux** vannes (« aspirer » et « souffler ») est sans risque (le clapet garde le vide), puis lire le
  vide (tâche 45 nonies). **Jamais ouvrir « souffler »** au démarrage. C'est une **exception écrite** à la règle
  « rien n'est commandé au démarrage » : seulement ces deux fermetures. Le chien de garde dans la carte des
  électrovannes (fermer « aspirer » seule si le Pi ne parle plus depuis ≈ 2 s) est un confort.
- **Choix de Claude (vannes)** :
  - Les vannes sont des sorties de la carte FluidNC de la préhension (`fluidnc.yaml → cartes → … → sorties`) : le Pi
    envoie « M65 » (sortie coupée) pour chaque vanne de la ventouse qui y est déclarée, une fois, liaisons lancées,
    **avant** la lecture du vide et avant le chef (donc avant tout Go et tout mouvement). Jamais « M64 ».
  - Le dépôt n'a qu'une vanne, `vanne_vide` (« aspirer » ; réponse à la PR n° 88 : pas de `ev_souffler`, « souffler »
    = vanne fermée ; **remplacé** : `vanne_souffler` est câblée en P1 depuis la tâche 45 undecies). Le code ferme
    aussi `vanne_souffler` **le jour où elle sera câblée** (même nom dans
    `docs/entrees-sorties.yaml` et `fluidnc.yaml`) : question à Karulium (PR de la 45 decies).
  - Attente au plus `fiabilite → objet_tenu → attente_vannes_s` (5 s, EXEMPLE) que la carte se connecte, puis sa
    réponse à chaque ordre. Carte absente, muette, en alarme (FluidNC refuse « M65 » ; le Pi ne la débloque pas),
    ou ligne en EXEMPLE sur la vraie machine : rien n'attend plus, la check-list dit « vannes de la ventouse » en
    **attention** (la vanne est refermée au premier départ de la tête de préhension, avec le lot, comme avant).
    Pas de refus du Go : le Go n'ouvre rien tout seul.
  - Les électroaimants des capsules ne sont **pas** touchés (seulement les deux fermetures de vannes).
  - Chien de garde de la carte des électrovannes : son programme n'est pas dans le dépôt (les vannes sont sur la
    carte FluidNC de la préhension, réglages seulement) : rien préparé, noté dans « ce qui reste » de la PR.
- **Réponse de la Maquette (07/11/2026 17 h, carte refaite à axes 1,29, v45.121,
  `griffe/logiciel/griffe-entrainee-entonnoir-maquette.md` et `carte-griffe-butee-haute-bocaux.txt`)** : la butée
  haute juste est **axes 1,29** (bas du godet fermé ≈ 1,087), la valeur du dépôt ; la carte à 1,265 utilisée par la
  45 nonies est périmée. Mât de la griffe = x bocal − 0,176, même y, godet fermé, tête à 0°, mode bocaux, union de
  toutes les poses du cycle. De x 0,78 à 1,30 et y 0,04 à 0,40, **un seul rectangle interdit : x ≤ 1,07 et
  y ≤ 0,11** (chariot de l'agitateur) ; partout ailleurs, le mât est libre à plus de 1 cm (caméra du dosage
  comprise). `bocal_0_0` (1,0315 ; 0,06) contact : posé à la main ; `bocal_0_1` (1,1415 ; 0,06), `bocal_1_0`
  (1,0865 ; 0,1553), `bocal_2_0` (1,0315 ; 0,2506) et `bocal_2_1` (1,1415 ; 0,2506) libres.
- **Réponse du fil Portique (07/11/2026, `portique/logiciel/bras-traine.md`, corrigé)** : bas du godet en butée haute
  ≈ **1,087**. Vérifié : c'est le bas du godet **fermé** (0,203 sous les axes à 1,29) ; le dépôt compte 0,213 partout
  (le plus bas, à 20°), soit **1,077**, 1 cm plus bas par prudence. Rien à changer (commentaires de `machine.yaml`
  mis à jour). Les « 1,265 / 1,065 » des 45 nonies venaient d'avant le raccourcissement du mât (23/10).
- **Choix de Claude (carte à 1,29)** :
  - Le rectangle interdit est compté jusqu'à **x 1,08** (la carte y met « n », moins de 1 cm) : x ≤ 1,08 et
    y ≤ 0,11. Libres de la mesure : au-dessus, x 0,78-1,30 et y 0,12-0,40 ; à droite, x 1,09-1,30 et y 0,04-0,40.
  - On garde le moyen des tâches 45 octies et 45 nonies (une zone par bocal, figée, où la table « butée haute » ne
    compte pas) plutôt que d'ouvrir toute la carte : la table v45.111 vaut aussi hors du mode bocaux, et la mesure
    est celle du mode bocaux. Trois zones, une par rangée, du mât du bocal jusqu'à x 1,30 :
    `bocal_0_1` x 1,09-1,30, y 0,04-0,11 ; `bocal_1_0` x 1,08-1,30, y 0,12-0,20 ; `bocal_2_0` x 1,02-1,30,
    y 0,21-0,29. Aucune ne touche le rectangle interdit. `bocal_2_1` n'en a pas besoin (la table le permet).
  - Le chemin est **gardé**, le même pour toutes (`entree_x` 1,22, où la table permet tout y) : la table seule
    refuse encore une partie de la carte libre, et un trajet tout droit d'ailleurs vers `bocal_0_1` passerait au-
    dessus du chariot de l'agitateur (x ≤ 1,08, y ≤ 0,11). Il ne passe plus près de la caméra du dosage.
  - Démarrage, en plus : chaque zone doit être tout entière dans un rectangle libre de la mesure, et toutes les
    zones ont le même `entree_x` (sinon le trajet d'une zone à l'autre irait en diagonale).
  - `vidange-entonnoir versement` : 1 bocal posé à la main (`bocal_0_0`), 3 posés par la machine grâce au chemin
    (`bocal_0_1`, `bocal_1_0`, `bocal_2_0`) ; `bocal_2_1` par la table. Question 4 de la PR n° 102 (`bocal_2_1`
    dans le carré « contact » de la carte à 1,265) : réglée, il est libre à 1,29.
- **Réponses à la PR n° 103** (tâche 45 decies, 07/11/2026, niveau 1, tranché par Claude) :
  1. Deuxième vanne « souffler » : question posée au fil Préhension ; si elle existe, elle est câblée sous le nom
     `vanne_souffler` et fermée au démarrage sans changer le code.
  2. Chien de garde de 2 s : pas pour l'instant (confort, le Pi ferme la vanne à chaque démarrage) ; à revoir si les
     vannes passent sur une carte à programme.
  3. Attente de 5 s de la carte au démarrage (`fiabilite → objet_tenu → attente_vannes_s`, EXEMPLE) : gardée, mesurée
     à l'essai (§ 4 ter).

## Lâcher de la ventouse par « souffler », 2 électrovannes (tâche 45 undecies, 07/11/2026)

Code : `pi/vidange/prehension/tete.py` (`DeuxVannes`, `SOUFFLER`, `TeteFluidnc.souffler`),
`pi/vidange/prehension/prehension.py` (`souffler`, `lacher_ventouse`), `couvercle/couvercle.py`,
`entonnoir/entonnoir.py`, simulations (`prehension`, `couvercle`, `entonnoir`, `remplissage`),
`prehension/outil.py` (`vidange-prehension vide [--sans-souffler]`) ; réglages `machine.yaml`
(`prehension → vide → souffle_s, lache_kpa, delai_lacher_s`), `fluidnc.yaml` et `fluidnc/prehension.yaml`
(sorties de la carte n° 4), `docs/entrees-sorties.yaml` (`vanne_souffler`) ; essais : `essai-prehension.md`
(étape 1 point 5, étape 2 bis, étape 5), `essai-fiabilite.md` (§ 4 bis, § 4 ter), `essai-couvercle.md`,
`essai-entonnoir.md`. Testé sur le vrai matériel : non.

- **Réponses des fils (07/11/2026)** :
  1. **Deux électrovannes** (fil Préhension, fiche `achats/modules/prehension.json`, étape 9) : `ev_aspirer`
     envoie l'air au venturi, `ev_souffler` remet la ventouse à l'air avec un peu d'air ; 2/2 24 V normalement
     fermées, plus un clapet anti-retour. Fermer « aspirer » ne lâche **rien** (le clapet garde le vide).
     **Lâcher = ouvrir `ev_souffler` ≈ 0,2 à 0,5 s, puis attendre que le vide remonte au-dessus de −5 kPa.**
     Vaut pour tous les lâchers de la ventouse (entonnoir, couvercle, seau, Pétri, et ce que d'autres modules
     prennent à la ventouse). Remplace le point 2 de « Entonnoir, réponses à la PR n° 88 ».
  2. **Câblage** (Implantation, `implantation/logiciel/sorties-carte-4.md`) : carte FluidNC n° 4 (6 axes,
     type « 6-Pack »), `ev_aspirer` (ex-`vanne_vide`) = sortie **P0**, `ev_souffler` = sortie **P1** (M62/M64/
     M65 P0 et P1), sorties auxiliaires 24 V n° 1 et 2, sur le **24 V coupé** (K2 : fermées à l'arrêt
     d'urgence) ; diode de roue libre sur chaque bobine si la sortie n'en a pas, ≤ 0,5 A par vanne. **P2**
     réservée au frein du Z de la préhension (si la Préhension le commande par la carte : sortie n° 3 ou module
     de sortie), **P3** libre. Les numéros de GPIO viendront de la configuration de la carte achetée ; P0 et P1
     ne changent pas.
  3. **Le logiciel empêche les deux vannes d'être ouvertes en même temps** (refus clair, vérifié aussi dans les
     tests ; l'Implantation dit « ferme l'une avant d'ouvrir l'autre »).
  4. Le nom `vanne_souffler` attendu par la tâche 45 decies (fermeture au démarrage) devient la vraie vanne.
- **Choix de Claude** :
  - **Noms** : on garde les noms du code `vanne_vide` (« aspirer », `ev_aspirer` de la fiche) et
    `vanne_souffler` (« souffler », `ev_souffler`), comme la tâche 43 l'avait fait pour les autres signaux de la
    Préhension : renommer `vanne_vide` toucherait beaucoup de fichiers sans rien changer à la machine. Les
    commentaires de `fluidnc.yaml` et `docs/entrees-sorties.yaml` donnent les deux noms.
  - **Sorties de la carte n° 4** (`fluidnc.yaml`) : `vanne_vide` 0, `vanne_souffler` 1, `frein_prehension_z` 2
    (était 4, EXEMPLE), 3 libre ; les électroaimants des capsules (étaient en 1), le jet d'air du col et le
    chauffage du lavage passent en 4, 5 et 6 (EXEMPLE : la fiche de l'Implantation n'en parle pas, question à
    Karulium). `fluidnc/prehension.yaml` suit (broches en EXEMPLE). `vanne_souffler` est ajoutée à
    `docs/entrees-sorties.yaml` (repère S14, EXEMPLE) et aux sorties exigées de la carte de la préhension
    (`SORTIES_PREHENSION`) : sans elle, `vidange --verifier` refuse.
  - **Un seul lâcher pour tous les objets** : `Prehension.lacher_ventouse(quoi)` = `souffler()` (« aspirer »
    fermée **d'abord**, « souffler » ouverte `prehension → vide → souffle_s`, refermée), puis attente du vide
    au-dessus de `lache_kpa` au plus `delai_lacher_s` ; sinon un nouveau souffle, puis alarme « `quoi` resté
    collé à la ventouse » (comme le couvercle et l'entonnoir le faisaient déjà). Réglages : `souffle_s` 0,3 s
    (EXEMPLE, entre 0,2 et 0,5 du fil), `lache_kpa` −5 (fil), `delai_lacher_s` 2 s (EXEMPLE). Vérifié au
    démarrage : `lache_kpa` au-dessus de `perte_kpa`. Les réglages du lâcher propres au couvercle
    (`lache_kpa`, `souffle_s`, `delai_lacher_s`) et à l'entonnoir (`lache_kpa`, `delai_lacher_s`) sont
    **enlevés** : un seul jeu, dans `prehension → vide`. `relache_s` reste pour les électroaimants (capsule,
    couvercle percé) et la pause entre deux impulsions du couvercle.
  - **Lâchers corrigés** (tous passaient par « vanne fermée ») : Préhension `_relacher` (pose d'un objet,
    reposer après un vide perdu à la levée, reposer après un mauvais poids ; donc aussi le Stockage, le Lavage,
    le Remplissage, le retourneur de couvercles, qui lâchent par la Préhension) ; Couvercle : lâcher sur le
    seau (étape 11), nouveau souffle du dégagement (étape 12), souffle après les impulsions ratées (étape 4),
    couvercles reposés sur la pile (étape 6) ; Entonnoir : lâcher sur le col (geste 11), souffle avant le
    nouvel essai de prise. Ce qui reste une **fermeture** d'« aspirer » (pas un lâcher) : la pause entre deux
    impulsions, l'arrêt après un vide perdu en route (l'objet est déjà tombé), le démarrage. Les objets aux
    électroaimants (capsule, couvercle percé du bocal neuf) ne changent pas.
  - **Jamais les deux ouvertes** : `DeuxVannes` (dans `tete.py`, employé par la vraie tête et par la tête du
    simulateur) refuse d'ouvrir l'une tant que l'autre est ouverte, ou peut-être ouverte (ordre de fermeture
    refusé par la carte) : `ErreurEtape` avec un « quoi faire », le module part en alarme. Une alarme (et le
    départ du geste suivant) referme « souffler » si un souffle était en cours. Ce refus protège la machine
    (l'air, le geste), jamais les personnes.
  - **Démarrage** : inchangé (tâche 45 decies) ; il ferme maintenant les deux vannes, puisque `vanne_souffler`
    est déclarée. Jamais « souffler » ouverte au démarrage. Le premier départ de la tête ferme aussi les deux.
  - **Simulateur** : le vide vient à l'ouverture d'« aspirer », **reste** à sa fermeture (clapet) et part à
    l'ouverture de « souffler » (`vides_colles` : tant de souffles sans effet) ; les faux mondes du couvercle,
    de l'entonnoir et du remplissage lâchent l'objet au souffle.
  - **Outil** : `vidange-prehension vide` = « aspirer » 5 s, fermée 2 s (le clapet doit garder le vide), puis
    le lâcher (souffle, vide revenu au-dessus de −5 kPa) ; `--sans-souffler` garde l'objet tenu (essai de la
    reprise, § 4 bis).

- **Réponses à la PR n° 104** (tâche 45 undecies, 07/11/2026, niveau 1, tranché par Claude) :
  1. Électroaimants des capsules, jet d'air du col et chauffage du lavage sur la carte n° 4 en P4, P5, P6 (EXEMPLE) :
     gardés là ; question posée à l'Implantation (à ajouter à `implantation/logiciel/sorties-carte-4.md`).
     **Remplacé** par la fiche du 07/11 (tâche 45 duodecies, plus bas) : électroaimants en P4 (confirmé), jet
     d'air du col sur la carte n° 3 (P5), chauffage sur un relais du Pi.
  2. Durée du souffle `prehension → vide → souffle_s` 0,3 s (EXEMPLE) : réglée à l'essai (étape 2 bis) au plus court
     qui lâche toujours le seau, le couvercle et l'entonnoir, plus 0,1 s de marge.
  3. Objet resté collé à la ventouse après deux souffles : alarme, pour tous les objets (gardé).

## Sorties des cartes n° 3 et n° 4, chauffage du lavage par un relais du Pi (tâche 45 duodecies, 07/11/2026)

Fiches de l'Implantation du 07/11/2026 (`implantation/logiciel/sorties-carte-3.md` et `sorties-carte-4.md`),
recopiées ici. Fichiers : `pi/reglages/fluidnc.yaml`, `fluidnc/mycelium_lavage.yaml`, `fluidnc/prehension.yaml`,
`docs/entrees-sorties.yaml` ; essais : `essai-lavage.md`, `essai-porte-bocal.md`, `essai-prehension.md`.

- **Fiche carte n° 3** (axes : agitateur NEMA 34, mors du porte-bocal ; modules de sortie 24 V dans les emplacements
  libres). Tout sur le **24 V coupé** (sauf l'alimentation permanente de la vanne à bille si son modèle en demande
  une). Numéros P définitifs, gpio à remplir à la réception de la carte :
  P0 pont en H du demi-tour (JGY370), sens 1 (jamais avec P1) ; P1 sens 2 (jamais avec P0) ; P2 relais de la pompe
  de vidange du lavage (`relais_pompe`, fusible 8 A) ; P3 électrovanne d'eau du lavage ; P4 vanne à bille motorisée
  du lavage (fil de commande ouvrir/fermer) ; **P5 électrovanne du jet d'air du col des seaux** (`jet_col`, 24 V,
  ≈ 5-8 W, diode de roue libre).
- **Fiche carte n° 4** (carte 6 axes « 6-Pack » CDC-ESP32-FLUIDNC ; 4 axes : Z préhension, rotation préhension,
  noyau, couronne du lavage) : P0 `ev_aspirer` (électrovanne 2/2 NF 24 V, vers le venturi ; sortie auxiliaire n° 1) ;
  P1 `ev_souffler` (remise à l'air, lâcher ; sortie auxiliaire n° 2) ; P2 réservée au frein du Z de la préhension ;
  P3 libre ; **P4 `electroaimants`** : les 3 électroaimants 24 V de la tête (capsules) en parallèle sur une seule
  sortie (module MOSFET ≥ 3 A dans l'emplacement libre n° 4, voie 1, diode de roue libre, 24 V coupé), **jamais
  commandés séparément**. Les 2 électrovannes sont sur le 24 V coupé (fermées à l'arrêt d'urgence), ≤ 0,5 A par
  vanne, diode de roue libre ; **jamais ouvertes ensemble** (le logiciel interdit : il ferme l'une avant d'ouvrir
  l'autre). **Le jet d'air du col et le chauffage ne sont PAS sur la carte n° 4.**
- **Chauffage du lavage** (thermoplongeur 2 kW, 230 V) : PAS sur FluidNC. Le **Pi** commande un relais qui alimente
  l'entrée du SSR de Karulium. **Sécurité câblée** contre le chauffage à sec : le flotteur alimente `relais_flotteur`
  (armoire), dont un contact est en série avec la commande du SSR (flotteur bas, fil coupé ou flotteur débranché :
  plus de commande, quoi que fasse le Pi) ; son 2e contact recopie le flotteur sur une entrée de la carte n° 3, que
  le logiciel lit. Le logiciel attend « flotteur haut » et « pompe arrêtée », puis informe : il n'est pas la
  sécurité. 2e barrière demandée au Lavage : thermostat de sécurité à réarmement manuel. La voie du relais viendra
  de la fiche à venir `implantation/logiciel/relais-du-pi.md`.
- **Choix de Claude** :
  - **Carte n° 3** (`fluidnc.yaml`) : `demi_tour_vers_tete_en_bas` 0, `demi_tour_vers_debout` 1, `pompe_lavage` 2
    (était 5), `eau_reseau_lavage` 3, `vanne_vidange_lavage` 4 (la « vanne à bille »), `air_col_lavage` 5 (était sur
    la carte n° 4). Le dépôt avait déjà, sur cette carte, le verrou du plateau (P2), la vanne 3 voies (P6) et le
    rinçage (P7) que la fiche ne cite pas : **EXEMPLES** `electroaimant_verrou_plateau` 6 et `vanne_rampes_lavage`
    7. FluidNC n'a que 8 sorties « digital » : le **rinçage passe sur la carte n° 4, P3** (libre dans la fiche,
    EXEMPLE ; le lavage accepte déjà un signal sur l'une ou l'autre carte). Question 1 ci-dessous.
  - **Carte n° 4** : `vanne_vide` 0, `vanne_souffler` 1, `frein_prehension_z` 2, `rincage_lavage` 3 (EXEMPLE),
    `electroaimants_capsule` 4. Le jet d'air (P5) et le chauffage (P6) en sont **enlevés**, y compris dans
    `fluidnc/prehension.yaml`. Le code garde ses noms (`vanne_vide` = `ev_aspirer`, etc., voir la tâche 45
    undecies).
  - **Pont en H** : `DeuxVannes` (ventouse) est refaite sur une classe commune, `DeuxSortiesExclusives`
    (`porte_bocal/signaux.py`), que le porte-bocal emploie pour les deux sens du demi-tour : refuser d'allumer un
    sens tant que l'autre est allumé, ou peut-être allumé (ordre d'extinction refusé par la carte) ; `ErreurEtape`
    avec un « quoi faire ». Le démarrage d'un demi-tour éteint déjà l'autre sens d'abord. Ce refus protège le
    pont, jamais les personnes.
  - **Chauffage** : signal `relais_chauffage_lavage` (relais du Pi, `relais_2` K8, 24 V, EXEMPLE) dans
    `docs/entrees-sorties.yaml`, qui remplace `chauffage_lavage` (sortie de la carte n° 4). Le lavage l'écrit par le
    `Materiel` du Pi (`signaux_lavage(liaisons, fluidnc, materiel)`) ; au repos ou à l'arrêt du programme le relais
    retombe (mise au repos des sorties du Pi). `EauLavage.surveiller()` ferme le relais seulement fût rempli,
    flotteur haut stable et pompe arrêtée (et pas en pause) ; sinon il garde la raison dans `chauffage_attend`
    et la met au journal (« chauffage en attente (…) »). `flotteur_lavage` est le 2e contact de `relais_flotteur` :
    sa description le dit. `relais_flotteur` lui-même est câblé, il n'a pas de signal du Pi.
  - **Vérifié au démarrage** (`vidange --verifier`) : deux sorties de même numéro sur une carte (déjà), un signal du
    lavage ou du porte-bocal absent ou sur deux cartes, les deux sorties du pont en H sur deux cartes, et le
    chauffage mis par erreur parmi les sorties d'une carte FluidNC. Au lancement de la machine, `relais_chauffage_lavage`
    absent de la liste ou en EXEMPLE sur la vraie machine : le lavage reste « absent ».
  - **Essais** : `essai-lavage.md` (étape 2 bis : la sécurité câblée du chauffage), `essai-porte-bocal.md`
    (`M64 P6` pour le verrou, pont en H P0 et P1 ; **P2 est maintenant la pompe**), `essai-prehension.md`.
    Testé sur le vrai matériel : non.
- **Questions pour Karulium / Implantation** (recommandations ; voir la PR) :
  1. La carte n° 3 n'a que 8 sorties « digital » : la fiche en donne 6 (P0 à P5), mais le verrou du plateau, la vanne
     3 voies et le rinçage en demandent 3 de plus. Recommandation : verrou P6 et vanne 3 voies P7 sur la carte n° 3,
     rinçage P3 de la carte n° 4 (en place). À confirmer par l'Implantation (ou une 2e carte de sortie).
  2. Voie du relais du chauffage (`relais_2` K8 en EXEMPLE) et 24 V ou autre tension pour la commande du SSR :
     à donner dans `relais-du-pi.md`.
- **Réponses à la PR n° 105** (tâche 45 duodecies, 07/11/2026, niveau 1, tranché par Claude) :
  1. Sorties en plus des fiches (verrou du plateau P6 et vanne des rampes P7 sur la carte n° 3, rinçage P3 de la carte
     n° 4, EXEMPLE) : gardées ; question posée à l'Implantation (à confirmer dans ses fiches, ou module de sorties).
  2. Relais du chauffage `relais_chauffage_lavage` sur `relais_2` voie K8, 24 V (EXEMPLE) : gardé jusqu'à la fiche
     `implantation/logiciel/relais-du-pi.md`.

## Relais du Pi et voyant-buzzer sur son propre relais (tâche 45 tredecies, 07/11/2026)

Fiches de l'Implantation du 07/11/2026 (`implantation/logiciel/relais-du-pi.md`, `sorties-carte-3.md`,
`sorties-carte-4.md`), recopiées ici. Fichiers : `docs/entrees-sorties.yaml`, `pi/vidange/entrees_sorties.py`,
`pi/systeme/essai-entrees-sorties.md`.

- **Relais du Pi** : 2 cartes de 8 relais en I2C (PCF8574, adresses 0x20 = `relais_1`, 0x21 = `relais_2`), contacts
  10 A 250 V. `relais_1` K1 : libre (pas le voyant-buzzer) ; K2 `voyant_pret_fut` (voyant du bouton « Prêt », 24 V) ;
  K3 à K8 libres. `relais_2` : K1 `verrous_store` (commandé = sous tension = déverrouillé ; contact EN SÉRIE avec AL1
  et AL2 de l'indicateur d'ozone, sécurité câblée) ; K2 `eclairage_enceinte` (12 V, 2 rubans LED) ; K3
  `ventilateur_enceinte` (par `relais_230`, moteur EC) ; K4 `generateur_ozone` et K5 `lampe_uv` (par `relais_230`,
  derrière la chaîne câblée, contact de porte, etc.) ; K6 `relais_compresseur` (commandé = alimenté ; commande la
  BOBINE du contacteur `contacteur_comp` ≥ 16 A AC-3, jamais le moteur) ; K7 `coupure_ventilateur_armoire` (câblé sur
  le contact REPOS : commandé = coupé ; Pi éteint ou planté = ventilateur en marche) ; K8 `relais_chauffage_lavage`
  (24 V → K8 → contact 1 de `relais_flotteur` → entrée du SSR ; flotteur bas = SSR sans commande, sécurité câblée).
  Le dépôt avait déjà exactement ces voies : rien n'a changé pour `relais_2`.
- **`voyant_buzzer`** : PAS sur `relais_1` K1. Son propre module relais 1 voie (`relais_buzzer`), sur un GPIO direct du
  Pi, en 24 V non coupé (choix du fil IA, 26/10) : l'alarme marche même si le bus I2C ou une carte relais tombe en
  panne. Le numéro du GPIO est choisi par le logiciel parmi les broches libres (pas 8, 9, 14, 15, 18, 19, ni 2/3).
- **Fiches cartes 3 et 4** : validé par l'Implantation, voir plus haut (tâche 45 duodecies) : carte n° 3 pleine 8/8
  (P6 verrou du plateau, P7 vanne 3 voies des rampes) ; carte n° 4 P3 rinçage du lavage, P5 à P7 libres, P2 frein ;
  modules de sorties 24 V à 4 voies dans les emplacements d'axe libres, rien à acheter. Les numéros gpio des cartes
  FluidNC restent EXEMPLE jusqu'à la réception des cartes.
- **Choix de Claude** :
  - Nouvelle carte `relais_buzzer` dans `entrees-sorties.yaml` (1 sortie, 24 V, isolée, liaison `gpio`, repère
    K1 → **GPIO23**, `niveau_actif: bas`, EXEMPLE) ; `voyant_buzzer` y est branché. GPIO23 : libre dans tout le dépôt
    (les cartes d'entrées prennent 16, 17, 20, 22, 25, 26, 27 ; le Pi lui-même 6 et 12 ; bus et PWM 2 à 5, 8, 9, 14,
    15, 18, 19). Un GPIO direct, sans I2C ; le code ne connaît que le nom `voyant_buzzer`.
  - `relais_1` K1 est libre ; la carte `relais_1` garde `voyant_pret_fut` (K2) seulement.
  - **Vérifié au démarrage** : une voie de relais ou un GPIO pris deux fois était déjà refusé (voie de la même carte,
    ou GPIO d'une autre carte comme `relais_buzzer/K1` contre `entrees_24v_1/E1`). Nouveau : la liste
    `gpio_reserves` (au début de `entrees-sorties.yaml` : GPIO2 à 5, 8, 9, 14, 15, 18, 19) ; une carte de GPIO direct
    ou un signal tout-ou-rien du Pi sur l'une de ces broches empêche de démarrer, avec le nom de la carte et du
    repère. Le chiffre est dans le fichier de réglages, pas dans le code.
  - **Essai** : `pi/systeme/essai-entrees-sorties.md`, étape 6 (GPIO, 24 V non coupé même à l'arrêt d'urgence, panne
    simulée de l'I2C, un relais I2C après l'autre). Testé sur le vrai matériel : non.
- **Questions pour Karulium / Implantation** (recommandations ; voir la PR) :
  1. GPIO23 pour le module `relais_buzzer` : l'Implantation doit l'écrire dans sa fiche (ou donner le sien).
     Recommandation : GPIO23, `niveau_actif: bas` (la plupart des modules 1 voie du commerce s'activent à l'état bas).
  2. Le module `relais_buzzer` est alimenté en 24 V non coupé ; son GPIO du Pi est en 3,3 V. Recommandation : un module
     à optocoupleur (isolation du Pi), sinon un transistor ; à préciser sur la fiche.
- **Réponses à la PR n° 106** (tâche 45 tredecies, 07/11/2026, niveau 1, tranché par Claude) :
  1. `relais_buzzer` sur GPIO23, en **actif haut** (réponse de l'Implantation du 07/11, écrite dans
     `implantation/logiciel/relais-du-pi.md`) : au démarrage, GPIO23 est une entrée tirée vers le bas ; un module
     actif bas ferait sonner l'alarme à chaque démarrage du Pi. Corrigé dans `docs/entrees-sorties.yaml`.
  2. Module du voyant-buzzer : relais 1 voie à **optocoupleur**, entrée 3,3 V, cavalier H/L sur H (Implantation).
