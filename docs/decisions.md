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
- **Pas encore figés** (case vide seulement) : Remplissage, Stockage, Spray, Micropore, Fermeture des seaux, Air comprimé, Entonnoir.
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
- **Cases vides** (pièces pas choisies, pas de pilote réel) : capteurs de particules (PMS5003 ou SPS30, UART),
  pression différentielle, convertisseur de la consigne 0-10 V du ventilateur (`vidange/nettoyage/capteurs.py`).
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
