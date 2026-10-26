# Décisions déjà prises qui touchent le code

Copiées depuis le projet « Vidange automatique ». Une session ne les rediscute pas ;
si l'une pose problème, elle le dit dans sa PR.

## Générales

- Pi 5 seul chef ; sécurité câblée en dur (arrêt d'urgence en série : 2 boutons + portes, relais de sécurité, contacteurs ; les freins serrent sans courant).
- Synchronisation entre cartes : attente d'état + zones réservées.
- Chocs horizontaux : alarmes des pilotes boucle fermée vers l'ESP32 n° 1, et accéléromètre LIS3DH + RP2040 sur le chariot Z (signal « OK » en sécurité positive vers l'ESP32 n° 1, mesures vers le Pi en série 3,3 V 115 200). Le palier pesé ne sert qu'au vertical.
- QR lus par les caméras (plus de lecteur GM65). Registre SQLite sur le Pi.
- Apprentissage seulement dans un cadre fixé par Karulium : plafonds de vitesse, temps de nettoyage, poids cibles. La sécurité n'est jamais apprise. Chaque réglage changé est noté et annulable. Montée en vitesse par paliers (+5 % tous les 25 cycles, recul sur alerte).
- PC de bureau : calculs lourds seulement quand Karulium les lance (rien d'automatique, pas de réveil par le réseau). Le Pi signale quand un calcul est conseillé.
- Assistant vocal éventuel : jamais de commande des moteurs.
- UV et ozone : modes verrouillés par le Pi (en plus des sécurités câblées).

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

## Règles validées (modules figés)

1. **Caméra du plafond** : 9 règles « situation → travail » validées (tableau à recopier ici quand la tâche Vision arrive). Le Pi PROPOSE le travail et attend le « Go » de Karulium. Repère ArUco 40 mm sur le plateau du rince-verre du lave-bocal. Corrections après essais réels.
2. **Caméra du dosage** sur servo DS3225 : 0° = bocal, 63° = seau. Photo du seau après chaque godet, avec sa dose. Elle pivote SEULEMENT si l'agitateur est garé (bocal x ≤ 0,62) ET si griffe et préhension sont hors de la zone x < 1,10, y < 0,34, z 0,95 à 1,08. Elle remonte avant le retour de l'agitateur ou du godet.
3. **Porte du spray ouverte** : portique arrêté, griffe interdite en x < 0,50 et y < 0,33, ozone et UV coupés.
4. **Reed du panneau du poste du fût** : production seulement contact fermé ; lavage seulement contact ouvert.
5. **Mycélium / Remplissage** : quand l'agitateur roule, le chariot de remplissage reste à y ≥ 0,375.

## État des modules (26/10/2026)

- **Figés** (on peut coder leurs gestes) : Poste du fût, Lavage, Griffe (Transfert), Porte-bocal, Mycélium, Guidage caméra, écran Nextion.
- **Pas encore figés** (case vide seulement) : Remplissage, Stockage, Portique, Préhension, Nettoyage, Spray, Micropore, Fermeture des seaux, Air comprimé, Entonnoir.
- Références encore à choisir : fins de course du Remplissage, microrupteurs du Stockage.
