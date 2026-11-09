# Liste des tâches

Une tâche = une session sur claude.ai/code = une PR. On les fait dans l'ordre,
**strictement une session à la fois** (deux sessions en même temps se marchent dessus).

**Phrase à copier pour lancer une tâche** (remplacer N) :

> Lis CLAUDE.md, puis fais la tâche N de docs/taches.md, et seulement celle-là. Ouvre une PR à la fin.

**Phrase à copier pour corriger une PR** (remarques ou tests rouges ; ça compte comme la même tâche) :

> Lis CLAUDE.md, puis corrige la PR n° X selon mes remarques et les tests, rien d'autre.

« Modèle » = celui à choisir au lancement de la session, pour dépenser le moins possible.
Opus pour poser les bases et pour les tâches pointues ; Sonnet pour le reste.

## Partie 1 : la base, qui ne dépend pas de la mécanique

- [x] **1. Squelette du programme du Pi** — Modèle : Opus.
  Paquet Python `pi/vidange/` (Python 3.11), dépendances (`pyproject.toml`), tests (pytest), style (ruff),
  GitHub Actions qui lance tout à chaque PR. Chargement et vérification des fichiers de réglages
  (`pi/reglages/*.yaml`, pydantic) avec un exemple : une erreur arrête le démarrage avec un message clair en français.
  Journal (logs) commun. Fichier de secrets hors Git (modèle `secrets.exemple.yaml`, le vrai dans `.gitignore`).
  Service qui démarre avec le Pi et redémarre seul s'il plante (systemd). Pas encore de logique de machine.

- [x] **2. Liste des entrées/sorties** — Modèle : Sonnet.
  Format de `docs/entrees-sorties.yaml` (nom, carte, broche, type : contact / PNP / NPN / mesure / I2C / série,
  tension, sens au repos, module) et un vérificateur lancé par les tests : broche en double, carte inconnue,
  trop d'entrées sur une carte, tension 24 V sans isolement. Le contenu sera rempli depuis le projet :
  mettre seulement quelques lignes d'exemple marquées « exemple ».

- [x] **3. Liaison FluidNC + faux FluidNC** — Modèle : Sonnet.
  Client série vers une carte FluidNC : envoi de G-code avec contrôle de flux, lecture de l'état (`?`),
  positions, alarmes, déblocage, reprise après coupure du câble. **Chaque carte reconnue par le numéro de série
  de son USB** (jamais par l'ordre des ports), réglé dans les réglages. Un faux FluidNC pour les tests
  (positions qui avancent selon la vitesse, alarmes simulables).

- [x] **4. Entrées/sorties du Pi + faux capteurs** — Modèle : Sonnet.
  Cartes relais, entrées 24 V optocouplées, I2C (ADS1115 0x48, SHT31 0x44), RS485 des transmetteurs d'ozone,
  sortie du voyant-buzzer. Tout par les noms de `docs/entrees-sorties.yaml`. La façon dont relais et entrées 24 V
  sont reliés au Pi (GPIO direct ou I2C) n'est pas encore décidée : prévoir les deux derrière la même interface.
  Un faux de chaque capteur pour les tests et le simulateur.

- [x] **5. Chef d'orchestre** — Modèle : Opus.
  Moteur d'étapes : un module = une liste d'étapes avec conditions d'entrée, action, condition de fin, délai maximal.
  Zones réservées entre axes, pause, reprise, alarme avec message « quoi faire », attente du « Go » de Karulium.
  **L'état du cycle est noté en continu** (pour la reprise après coupure). Un module d'exemple sur le faux FluidNC.

- [x] **6. Registre SQLite** — Modèle : Sonnet.
  Tables : fûts, seaux, bocaux, boîtes de Pétri, cycles, étapes faites (avec durées), mesures, photos, alarmes,
  réglages appliqués (ancien / nouveau / qui / quand). **Les photos restent en fichiers sur le SSD ; la base garde
  seulement leur chemin.** Montées de version de la base. Copie de secours quotidienne.

- [x] **7. Fiabilité** — Modèle : Opus.
  Chien de garde Pi ↔ cartes (fonction 14), check-list de démarrage (12), reprise après coupure de courant (3),
  arrêt propre sur onduleur (4), bilan et « quoi faire » de chaque alarme (17, 18), santé de l'informatique (45).
  À faire avant que la vraie machine bouge.

- [x] **8. API du Pi et page web locale** — Modèle : Sonnet.
  API (FastAPI) sur le réseau local et Tailscale, protégée par une clé : état, alarmes, Go, Pause, historique, photos.
  Page web simple en français, lisible sur téléphone.

- [x] **9. Écran Nextion, côté Pi** — Modèle : Sonnet.
  Protocole série Nextion (envoi de valeurs, lecture des appuis). Pages : état, alarme + quoi faire, Pause, Go,
  compteurs, mode (production / lavage / UV-ozone), grands boutons, code couleur (46 à 48). Écrire dans
  `nextion/pages.md` chaque page, bouton par bouton (nom, position, taille), pour que Karulium la monte dans Nextion Editor.

- [x] **10. File d'envoi vers l'extérieur** — Modèle : Sonnet.
  File durable (dans SQLite) avec reprise, pour le logiciel de culture et la copie de secours.
  Écrire dans `docs/django.md` le format exact des données d'un cycle que l'app « machine » recevra.
  Ne pas toucher au dépôt Django.

- [x] **11. Simulateur de cycle (jumeau, version 0)** — Modèle : Sonnet.
  Rejouer un cycle complet du module d'exemple avec des durées réglables, sortir le planning (qui fait quoi, quand)
  et le temps total. Préparer la place pour le solveur OR-Tools.

- [x] **12. Accès à distance : vidéos et pilotage manuel** — Modèle : Opus.
  Suivre `docs/decisions.md` (partie « Accès à distance »). Vidéo en direct des caméras sur la page web,
  clips d'incidents, mode à distance avec homme mort, vitesse réduite, arrêt si connexion perdue ou vidéo figée,
  priorité à l'armoire, journal des actions, **voyant-buzzer sur place avant et pendant tout mouvement lancé
  à distance** (49). Tests avec le faux FluidNC (coupure de connexion simulée).

- [x] **13. Mises à jour des cartes ESP32 et du Pi** — Modèle : Sonnet.
  Mise à jour des ESP32 par USB depuis le Pi (esptool), envoi des réglages FluidNC, retour à l'ancienne version,
  vérification après mise à jour ; mise à jour du programme du Pi depuis `main`. Seulement machine à l'arrêt.
  Lancement depuis la page web.

- [x] **14. Accéléromètre (RP2040 + LIS3DH), partie 1 : mesure du choc et signal « OK »** — Modèle : Opus.
  Seuil réglable, sortie « OK » en sécurité positive (coupée sur choc ou panne). Livrer la procédure d'essai à l'établi.

- [x] **15. Accéléromètre, partie 2 : liaison série un seul fil (PIO)** — Modèle : Opus.
  Mesures vers le Pi, réglages vers le RP2040 (half-duplex, voir `docs/decisions.md`). Côté Pi : lecture et
  enregistrement des chocs. Procédure d'essai à l'établi.

- [x] **16. Accéléromètre, partie 3 : chargeur série et mise à jour depuis le Pi** — Modèle : Opus.
  Petit chargeur maison (le RP2040 n'en a pas d'origine), installé une fois à l'établi par USB ; mise à jour
  par la liaison un seul fil ; secours par USB-C. Procédure d'essai à l'établi.

## Partie 2 : les modules figés (après la partie 1)

Avant chaque tâche, le projet recopie ici les gestes, positions et règles du module.

- [x] **17. Poste du fût** — Modèle : Opus, effort moyen.
  Sources (recopiées ici le 28/10/2026) : fiche du module « Poste du fût », **validé définitivement le 23/10/2026**,
  et plan de commande v221 du projet mécanique. Les chiffres vont dans `pi/reglages/machine.yaml` et
  `docs/entrees-sorties.yaml`, jamais dans le code.

  *Ce qui est à la main (rien ne bouge seul au poste du fût).* Karulium roule le chariot jusqu'aux 2 butées
  d'angle du fond, freine, branche la prise magnétique de la pesée, enlève la soupape du couvercle (trou bouché),
  rabat le grand volet du dessus. Le retournement du fût (3 coups de 60° au cliquet, goupille, sangles) se fait
  **hors de la machine**, sous le pont roulant : dans la machine, le fût est toujours debout.

  *Signaux* (à ajouter à `docs/entrees-sorties.yaml`, marqués `exemple: true` tant que le plan de câblage
  n'est pas arrivé) :
  - `chariot_fut_en_place` : détecteur inductif M12, PNP, contact ouvert au repos, 24 V, dans la butée d'angle
    côté portique ; il voit le bout du châssis à 4 mm quand le chariot est au fond.
  - `reed_panneau_poste_fut` (existe déjà) : contact fermé = panneau long levé = **production permise** ;
    ouvert = rabattu ou entre les deux = production refusée, **lavage permis seulement contact ouvert**.
  - `pesee_fut` : une carte HX711 sur le chariot lit les 2 capteurs de pesage (150/200 kg chacun) ; elle pèse
    berceau + fût + contenu. Câble de 10 m à prise magnétique (alimentation, DT, SCK) jusqu'au Pi. La prise est
    souvent débranchée (≈ 800 fois par an, un oubli ne casse rien) : pas de réponse = « pesée débranchée »,
    jamais une erreur qui arrête le Pi.
  - `bouton_pret_fut` et son voyant : bouton lumineux « Prêt » (plan de commande). Il n'est pas encore dans la
    fiche du module : ligne d'exemple ; les boutons « Prêt » de l'écran et de la page web font la même chose.
  - Il n'y a **pas** de capteur de goupille ni de capteur du volet du dessus : ne pas les inventer.

  *États du poste* (affichés à l'écran et sur la page web) : chariot absent ; chariot en place mais pas prêt ;
  prêt. « Prêt » = chariot en place + pesée qui répond avec un poids plausible (bornes réglées) + signaux stables
  depuis 2 s + appui sur « Prêt ». Avant le « Prêt », l'écran rappelle les gestes à la main (liste ci-dessus) ;
  ce n'est qu'un rappel, rien n'est vérifié par capteur. Voyant du bouton : clignote tant que ce n'est pas prêt.
  Si un signal tombe pendant la vidange : le mouvement en cours s'arrête, le pont se retire hors de la zone du
  chariot, alerte. Un verrou du logiciel ne protège que la machine : la sécurité des personnes reste câblée.

  *Zones et positions* (repère du portique, en mètres) :
  - Centre du fût au poste (0,29 ; 0,57). Ouverture du dessus Ø 0,60 à z 1,07. Fût : Ø intérieur 0,565,
    profondeur intérieure 0,86, fond intérieur ≈ 0,1825, bord ≈ 1,0425 (le fond est trouvé au toucher par la
    griffe : tâche 18).
  - Chariot absent ou en mouvement : pont hors de x 0 à 0,80 (le chariot monte à 1,06, le chariot X du pont
    descend à 1,11). Tant que « chariot en place » manque, le chariot de remplissage reste au poste ou aux files
    1 et 2 (bout à y ≤ 0,875), jamais devant la 3e file, pour laisser passer le chariot du fût en biais.
    Le tiroir du bas du stockage reste rentré pendant l'échange du fût (Stockage pas figé : seulement une
    condition nommée, case vide).
  - Griffe : bas de la tête ≥ 1,13 quand elle passe au-dessus de la poignée du volet (x 0,50 à 0,63,
    y 1,005 à 1,015) ; volet relevé : pas de griffe au-dessus du fût (sans capteur du volet : volet considéré
    relevé en mode lavage, contact du panneau ouvert ; le dire dans la PR).
  - Préhension en lavage : pour passer la paroi côté stockage, fond du seau ≥ 0,84 et axe y ≤ 0,86.

  *Pesée* : zéro et étalonnage avec un poids connu (procédure pour Karulium) ; tare « berceau + fût vide » réglée ;
  poids net du substrat = mesure − tare. Lire seulement quand la griffe n'est pas dans le fût. Au « Prêt » : poids
  du fût plein dans le registre ; pendant la vidange : poids restant ; à la fin : poids total vidé (alerte « fût
  vide, nombre de seaux, poids total »). Contrôle : la somme des doses de la griffe doit suivre la baisse de la
  pesée ; un écart plus grand que le seuil réglé donne un avertissement, pas un arrêt. Les poids partent dans le
  cycle envoyé au logiciel de culture (`mesures[]`, objet `fut`, voir `docs/django.md`).
  Lecture du HX711 directement par le Pi : vérifier qu'elle reste fiable (impulsions d'horloge courtes, filtre
  des valeurs aberrantes) ; si ce n'est pas sûr, le dire dans les questions de la PR.

  *Mode production / lavage* : production seulement contact du panneau fermé, lavage seulement contact ouvert ;
  entre les deux, le Pi refuse de lancer l'un ou l'autre et dit pourquoi.

  Simulateur : faux chariot, faux panneau, fausse pesée, et un scénario « échange de fût ». Tests.
  Procédure d'essai sur le vrai matériel (inductif, reed, pesée et étalonnage, prise débranchée) ;
  « testé sur le vrai matériel : non ».
- [x] **18. Griffe (transfert fût vers seau)** — Modèle : Opus, effort élevé.
  Sources (recopiées ici le 28/10/2026) : fiche « Griffe sur mât » et fiche d'état du module, **gelé le
  25/10/2026**, plan de commande v221. Chiffres dans `pi/reglages/machine.yaml` (repère du portique, en mètres),
  jamais dans le code. Le Portique et le chariot de remplissage ne sont pas figés : leurs gestes restent des cases
  vides ; la griffe ne fait qu'utiliser des positions nommées et des zones.

  *La machine.* Un mât descend dans le fût (axe Z de la griffe, NEMA 23 à frein) ; il porte un godet de 3 L à
  2 coquilles (axe B, fermeture par vis à billes, NEMA 23 à frein, ouverture connue par le codeur) et tourne
  sur lui-même (axe A). Les 3 axes sont sur la carte FluidNC n° 1 (portique). Une pesée (capteur 50 kg + HX711)
  dans la suspension du mât mesure le poids pendu : poids de la prise, et contact (la charge baisse quand le
  godet appuie). Une raclette en silicone est fixée sur le côté de la tête. « Hauteur des axes » = hauteur des
  axes de la tête ; mât de la griffe = pont − 0,187 en x (Portique, 29/10).

  *Une couche (godet unique).*
  1. Tête au-dessus du fût, godet ouvert. Descente rapide jusqu'au dernier niveau connu + 3 cm (le capteur de
     distance de la tête peut donner le niveau), puis lente ; au contact (la charge baisse), arrêt, hauteur notée.
  2. Mâchouiller : le godet se ferme à moitié et se rouvre 3 à 5 fois (≈ 0,6 s par bouchée) ; entre deux bouchées,
     le mât l'enfonce d'≈ 5 mm, force limitée. Pas de mâchouillage pour le maïs.
  3. Prendre : le godet prend l'ouverture choisie pour la dose, s'enfonce d'1 cm et se ferme, en plongée (le mât
     descend encore pendant la fermeture).
  4. Le mât remonte de 5 cm et s'arrête 0,5 s : pesée de la prise ; le Pi note ouverture, enfoncement, nombre de
     bouchées, niveau, position dans le fût et poids. Trop léger : reprendre à côté sans faire le voyage. Trop
     lourd : s'entrouvrir au-dessus du fût jusqu'au bon poids. En remontant, la tête se tourne bras le long du pont
     avant de sortir du fût.
  5. Trajet vers le seau (voir les règles de trajet), tête bloquée bras le long du pont.
  6. Vidage : la tête descend à 2 cm au-dessus du bord (axes = haut du seau + 0,23, réglé par format), le godet
     s'ouvre en grand en tournant (±45° au plus, voir la rotation) : la couche tombe en couronne. Si le haut du seau
     dépasse 0,88, vidage tête bloquée, sans tourner.
  7. Tassement : godet refermé à vide, son fond descend sur la couche et appuie à quelques endroits (≈ 60 N) pendant
     que le seau tourne. Seau de 5 L : seulement la dernière couche (tête centrée, bas du godet au plus 8 cm sous
     le bord).
  8. À la dernière couche : essuyage du bord, raclette posée sur le bord du seau qui tourne, godet ouvert dehors
     (mât à R_haut + 11 cm de l'axe du seau, axes à haut + 0,196).
  9. Retour au fût. Dose par couche, nombre de prises (au plus 3 L par prise) et formats : table des formats.

  *Hygiène* (règle de Karulium) : la griffe ne touche **jamais une couche de mycélium découverte**. Elle tasse
  juste après avoir vidé le substrat, avant l'ajout du mycélium, et essuie le bord après la dernière couche de
  substrat.

  *Préparer une prise pendant les temps morts* (oui de Karulium) : pendant l'agitation du mycélium, le clipsage et
  la sortie du seau, la griffe prend et pèse la dose suivante, puis attend godet fermé, dans le fût, au-dessus du
  substrat. Seulement si la préhension n'a pas besoin du pont (les deux mâts sont sur le même chariot).

  *Apprendre les doses* : poids ≈ densité × volume pris ; volume tiré d'une table (ouverture, enfoncement) ;
  densité apprise sur les 5 à 10 dernières prises du fût ; corrections à part pour les prises près de la paroi ou
  du fond. Table par défaut pour les 10 à 20 premières prises. Tout est noté dans le registre (SQLite).

  *Fond du fût et passe de fond.* Fond trouvé au toucher, sans cote fixe : en fin de fût, descente lente ; quand la
  charge baisse de 30 à 50 N, le godet est en appui : arrêt, prise. Butée basse logicielle 3,5 cm sous le fond
  (secours). Poussée vers le bas limitée à 30 à 50 N pour ne pas marquer le fond. La passe de fond se lance quand
  la pesée du fût annonce les derniers kilos (tâche 17) : (1) prises en appui au fond, en spirale depuis le centre,
  le godet se ferme en gardant une légère poussée ; (2) une douzaine de prises le long de la paroi, joue du godet
  parallèle à la paroi, ouverture limitée à un cinquième ; (3) reste une bande de 3 à 4 cm ; (4) un tour de
  raclette en chasse-neige, godet fermé, lame inclinée de 20° par rapport au rayon ; (5) deux ou trois prises au
  centre. Côté −x, le mât ne va qu'à 0,17 de l'axe du fût : prises de paroi −x tête orientée vers la paroi.
  Fût vide : le mât arrive au fond sans prise utile ; dire `finir_vidange` au poste du fût.

  *Raclage de la paroi du fût* : godet ouvert, la tranche de la lame appuie d'≈ 8 mm contre la paroi ; la tête
  fait le tour en descendant et tourne pour garder le plan de la lame passant par l'axe du fût. Pas de collecteur
  tournant : un tour dans un sens, puis un tour dans l'autre. Pendant les prises, raclette orientée vers le
  centre du fût.

  *Règles de position* (plan de commande ; chiffres dans `machine.yaml`) :
  - Rotation de la tête : libre si axes ≤ 1,075 ; de 1,075 à 1,11, libre godet fermé et ±45° au plus godet
    ouvert ; au-dessus de 1,11, **orientation bloquée** (bras le long du pont, raclette côté fût), à 0° ou 180°.
    Le Pi choisit l'orientation avant de monter. Pas de rotation quand le pont est au-delà de x 2,0.
  - Godet **jamais au-delà de « fermé »** (le capot du boîtier de tête n'a que 4 mm de garde).
  - Course des axes 0,375 à 1,29 ; bas du godet en butée haute 1,087. Mât en y : 0,056 à 0,884 godet fermé,
    0,11 à 0,83 grand ouvert (en position haute, tête bloquée). Pont x ≥ 0,223.
  - Trajet fût ↔ poste de remplissage **jamais en diagonale** : aller d'abord en x, mât à y ≥ 0,36, puis en y
    seulement une fois le mât à x ≥ 0,86 ; retour dans l'ordre inverse.
  - Garage et glissière de l'agitateur du mycélium : volumes interdits à toute hauteur. Y minimum du mât, godet
    fermé / à moitié ouvert / grand ouvert : mât x 0,15-0,43 → y ≥ 0,23 / 0,24 / 0,28 ; x 0,43-0,77 →
    y ≥ 0,33 / 0,345 / 0,38 ; x 0,77-0,82 → y ≥ 0,24 / 0,24 / 0,27 ; x 0,82-0,85 → y ≥ 0,13 ; x 0,85-1,22 →
    y ≥ 0,10 / 0,105 / 0,14. Pendant le dosage, mât à x ≤ 0,78 ou y ≥ 0,40.
  - Boîtier de la caméra du bocal : mât x ≤ 0,96 tant que le bas de la tête est sous 1,08 et recouvre y 0,22-0,28.
  - Poste du fût (tâche 17) : bas de la tête ≥ 1,13 au-dessus de la poignée du volet ; pas au-dessus du fût en mode
    lavage. Bout côté fût : quand le mât est sous x ≈ 0,12, bas de la tête ≥ 0,85 hors du fût, ≥ 1,05 au-dessus de
    la paroi du fût.
  - Porte du coffret du spray ouverte : griffe interdite en x < 0,50 et y < 0,33.
  Une règle douteuse ou incomplète va dans les questions de la PR, sans inventer de chiffre.

  *Ce qui n'est pas dans cette tâche* : le demi-tour de la tête en mode lavage et en mode « couvercle dans le fût »
  (tâche 21), le bain et le garage UV des têtes (Nettoyage, pas figé : position nommée vide), le remplissage des
  bocaux par l'entonnoir (avec l'Entonnoir, pas figé), l'ordre des variétés dans un fût (tâche 23).

  *Capteur de force* : FluidNC ne sait pas lire un HX711. Choix du projet mécanique (28/10, voir
  `docs/decisions.md`) : une petite carte RP2040 près du HX711 de la griffe le lit et répond sur un bus RS485
  dédié aux pesées (`rs485_pesee`), que le Pi interroge. Côté Pi dans cette tâche : la lecture derrière une
  interface simple, testée avec une fausse pesée ; le programme de la carte RP2040 est une tâche à part
  (ajoutée en Partie 2). Contact : lecture rapide (80 mesures/s) pendant les descentes ; le Pi arrête la descente (feed hold) dès
  que la charge baisse. Choc (force inattendue pendant un trajet) : arrêt immédiat de Z et du pont, remontée
  lente, alerte avec photo.

  Lien avec la tâche 17 : lancer le module `poste_fut`, faire la vidange sous `poste.surveillance`, appeler
  `noter_dose` après chaque dose (griffe sortie du fût) et `finir_vidange` à la fin ; si l'alarme du poste se
  déclenche, sortir le pont de la zone du chariot.
  Simulateur : un cycle complet d'un fût (prises, couches, passe de fond, fût vide). Tests.
- [x] **18 bis. Griffe : marges de la tête** — Modèle : Opus, effort moyen.
  Les règles de position de la griffe (`pi/vidange/griffe/regles.py`) sont vérifiées sur le mât seul. Ajouter
  l'encombrement de la tête (`docs/decisions.md`, réponses de la PR n° 23 : 0,111 / 0,165 de chaque côté selon
  l'ouverture, rayon balayé 0,137, raclette à 0,111, bas du godet à 0,213 sous les axes) pour les règles où
  il compte : poignée du volet, boîtier de la caméra du bocal, bout côté fût, porte du spray, garage de
  l'agitateur. Vérifier l'essuyage du bord du seau (mât à +x du seau, axes à haut + 0,196) contre le boîtier de
  la caméra du bocal (x 1,045-1,085, y 0,22-0,28, z 0,982-1,062) ; s'il y a contact, le dire dans les questions
  de la PR avec une proposition. Tests.
- [x] **18 ter. Griffe : nouvelle table « Y minimum du mât » (agitateur fixe) et essuyage godet à moitié** — Modèle :
  Sonnet, effort moyen. **À faire après la tâche 19 ter.**
  Source : `docs/decisions.md`, « Griffe : table Y minimum du mât avec l'agitateur fixe » (02/11/2026), points 1 à
  6, et « Griffe : essuyage et Y minimum du mât » (01/11), points 1, 6 et 7. Dans `pi/reglages/machine.yaml`,
  remplacer `griffe → garage_glissiere` par deux tables, `y_min_mat → butee_haute` (6 bandes) et
  `y_min_mat → sous_butee` (4 bandes), plus `ouverture_fut → rayon_mat_max: [0.16, 0.135, 0.105]` et
  `ouverture_fut → z_min: 1.11` (point 3). Les bandes se chevauchent exprès : une pose est refusée par toute bande
  qui la contient. Retirer `permise_en_butee_haute` (`pi/vidange/reglages.py`, `BandeGriffe`) et adapter
  `pi/vidange/griffe/regles.py` : en butée haute la première table ; dessous la seconde ; mât à x < 0,78 et axes
  de 1,11 à la butée : seulement dans le cercle autour de `poste_fut → centre_fut` (tête tournée : point 4).
  Ajouter `essuyage → ouverture_godet: 0.5` (vérifié au démarrage : de 0 à moins de 1, car 1 = grand ouvert est
  refusé) et l'employer dans `geste_essuyer` (`pi/vidange/griffe/griffe.py`) à la place de « godet grand
  ouvert » ; corriger le commentaire « EN ATTENDANT » de `essuyage` (côté allée confirmé). Recopier aussi : boîte
  `griffe → camera_bocal` en x 0,997-1,091, z 0,975-1,068 et caméra du plafond en y 0,545 dans
  `pi/reglages/vision.yaml`. Tests : remplacer `test_bande_du_garage_permise_en_butee_haute_seulement` ; godet fermé,
  x 0,90 y 0,28 refusé en butée haute, x 0,60 y 0,28 permis ; x 0,90 y 0,31 permis en butée haute, refusé dessous ;
  x 1,05 y 0,39 refusé sous la butée, permis en butée haute ; x 0,50 y 0,60 à 1,15 refusé ; x 0,29 y 0,57 à 1,15 permis ;
  vidage en (0,925 ; 0,42) et essuyage des 4 formats sans refus. `vidange --verifier` et le simulateur passent.
- [x] **19. Mycélium (dosage)** — Modèle : Opus, effort moyen.
  Sources (recopiées ici le 28/10/2026) : fiche du module « Mycélium », **validé définitivement le 24/10/2026**
  (option B : tout le module relevé de 12 mm, garage à x 0,565), fiche des pièces v8 et plan de commande v221.
  Les chiffres vont dans `pi/reglages/machine.yaml` et `docs/entrees-sorties.yaml`, jamais dans le code.

  *Ce que fait le module.* Un « agitateur » porte le bocal de semence (mycélium en grains) sur une glissière
  horizontale au-dessus du poste de remplissage. Au dosage, le bocal est tête en bas au-dessus du seau ; une
  manivelle le secoue de haut en bas et les grains tombent par les trous du couvercle. La balance du chariot de
  remplissage pèse ce qui tombe : on arrête de secouer quand la dose est atteinte.

  *Moteurs et capteurs* (tous sur la carte 3 ; à ajouter à `docs/entrees-sorties.yaml` et `fluidnc/`, marqués
  `exemple: true` tant que le plan de câblage n'est pas arrivé) :
  - Glissière : NEMA 17 en boucle fermée (codeur 1000 lignes), courroie GT2. 2 fins de course, l'un au garage,
    l'autre au dosage ; les arrêts entre les deux (demi-tour) se font au codeur.
  - Manivelle : NEMA 34 à codeur, pilote HBS86H en 48 V. Elle fait monter et descendre le bocal. Le codeur sert à
    s'arrêter pile « manivelle en haut » ou « manivelle en bas ». Vitesse d'agitation : réglage (la fiche compte
    jusqu'à 300 tr/min ; valeur à trouver aux essais).
  - La course (4, 7 ou 10 cm) se choisit **à la main**, en mettant la bielle dans un des 3 trous de la manivelle.
    Le Pi ne la change pas : c'est un réglage déclaré (`course_agitation_m`) que Karulium tient à jour.
  - Le demi-tour du bocal (moteur JGY370 et son verrou) et les mors appartiennent au Porte-bocal (tâche 20) :
    ici, on les appelle derrière une interface simple (`retourner_tete_en_bas`, `remettre_debout`) avec un faux ;
    la tâche 20 la remplit.

  *Positions* (repère du portique, en mètres) :
  - Garage x 0,565 ; demi-tour x 0,865 ; dosage x 0,925 (axe du seau). Course de la glissière 0,36.
  - Au dosage, le seau est arrêté par le chariot de remplissage à y 0,155.
  - Axe de la manivelle z 0,762 (module relevé de 12 mm le 24/10).
  - Plateau du chariot pendant le dosage : min(0,78 − h ; 0,575), h lu dans la table des formats (bord du seau à
    0,78 m, 0,775 pour le 5 L). C'est le chariot (tâche du Remplissage) qui le règle ; ici on vérifie seulement
    qu'il est à cette hauteur avant de doser.

  *Déroulé d'un dosage* (pour chaque seau, après chaque couche versée et tassée par la griffe) :
  1. Le bocal attend au garage, manivelle en haut. Le chariot de remplissage s'écarte à y ≥ 0,375.
  2. L'agitateur roule jusqu'au demi-tour x 0,865 ; le bocal est retourné tête en bas (Porte-bocal).
  3. Il roule jusqu'au dosage x 0,925 ; manivelle en bas.
  4. Le chariot revient avec le seau à y 0,155, plateau à la hauteur du dosage.
  5. Agiter en lisant la balance du chariot ; arrêter quand la dose de la couche est atteinte (dose lue dans la
     table des formats ; tolérance et temps maximal : réglages). La manivelle s'arrête toujours pile en bas ou
     pile en haut, jamais entre les deux ; ici, en bas.
  6. Le chariot repart (vers la griffe ou le stockage). Puis manivelle en haut, retour au demi-tour, bocal remis
     debout (rien ne coule debout), retour au garage.
  Le plan de commande dit aussi : « l'agitateur remonte son bocal de 7 cm, quitte son garage ». Si la session
  trouve que cela contredit « manivelle en haut au garage », elle le dit dans les questions de la PR.

  *Verrous avec le chariot de remplissage* (règles du projet mécanique, 24/10 ; elles protègent la machine, pas
  les personnes) :
  - L'agitateur ne roule que si le chariot de remplissage est à y ≥ 0,375.
  - Le chariot de remplissage ne roule que si l'agitateur est au garage manivelle en haut, ou au dosage manivelle
    en bas. Ce verrou est une fonction que le module du chariot appellera (le chariot n'est pas fait ici).
  - Au garage, la manivelle ne tourne pas si la course déclarée est de 10 cm (le fond du bocal toucherait la
    marche du poste du fût à z 0,88) : 7 cm au plus au garage.
  - La caméra du dosage ne pivote vers le seau que si l'agitateur est garé (x ≤ 0,62) : règle déjà dans
    `docs/decisions.md`, à brancher ici sous forme de verrou.

  *Un bocal pour deux petits seaux* (décision de Karulium, 26/10) : pour les petits seaux, un bocal peut servir
  à 2 seaux au plus, de la **même variété**. Entre les deux, le bocal reste dans le porte-bocal : remis debout au
  demi-tour, retour au garage pendant que le chariot change de seau, puis nouveau demi-tour pour le 2e seau.
  La « casse du bloc » (agitation plus forte au début, pour casser le mycélium pris en bloc dans le bocal) ne se
  fait qu'au 1er seau ; sa durée est un réglage.

  *Surveillance pendant l'agitation* :
  - Saut de poids brutal sur la balance du chariot (lue à 80 mesures/s) = bocal ou couvercle cassé, ou bocal
    tombé : arrêt de la manivelle, alerte avec photo. Le seuil est un réglage.
  - Poids qui ne monte plus (bocal vide ou couvercle bouché) au bout du temps maximal : arrêt, alerte, le seau
    n'est pas rangé comme bon (le registre le marque).
  - Le registre reçoit, pour chaque seau : QR du bocal, dose réelle de chaque couche, variété.

  *Ce qui n'est pas dans cette tâche* : le demi-tour et les mors (tâche 20), la lecture des QR (tâche 22), la
  lecture de la balance du chariot par sa carte RS485 (tâche 22 bis : ici, une fausse pesée derrière la même
  interface que la griffe), le perçage des couvercles (sera choisi sur la machine réelle : rien à coder).

  Simulateur : un seau de format A dosé en 4 couches, puis 2 petits seaux B avec un seul bocal. Tests, dont les
  verrous avec le chariot et la casse du bocal.
- [x] **19 ter. Mycélium : agitateur fixe à x 0,925 (plus de glissière)** — Modèle : Opus, effort moyen.
  Sources : `docs/decisions.md`, « Agitateur du mycélium FIXE » (01/11/2026), recopiée de la fiche Mycélium v10
  (`mycelium/logiciel/mycelium-pour-logiciel.md` du projet mécanique) et des règles C1 à C4 du Remplissage. Les
  chiffres vont dans `pi/reglages/machine.yaml`, `docs/entrees-sorties.yaml` et `fluidnc/`, jamais dans le code.
  Ne pas toucher à la table `griffe → garage_glissiere` (tâche 18 ter, en attente de la nouvelle table).

  *Ce qui change.* L'agitateur ne bouge plus : bocal toujours en (0,925 ; 0,150), axe de la manivelle à z 0,762,
  centre du bocal à z 1,059 manivelle en haut. Plus de garage, de roulage, ni de positions « garage / demi-tour /
  dosage » séparées.
  1. **Retirer la glissière** : axe X de la carte n° 3 dans `fluidnc/mycelium_lavage.yaml`, `moteur_glissiere_agitateur`,
     `alarme_glissiere_agitateur`, `fdc_agitateur_garage`, `fdc_agitateur_dosage` dans `docs/entrees-sorties.yaml`,
     `mycelium → garage_x, demi_tour_x, dosage_x, tolerance_x_m, vitesses → glissiere_m_s` et leurs vérifications au
     démarrage. Remplacer par `mycelium → bocal: [0.925, 0.150]` (et garder `manivelle_z`). Les gestes « rouler » de
     l'agitateur et la prise d'origine de la glissière disparaissent ; celle de la manivelle reste (inchangée).
  2. **Manivelle** : EN HAUT pour la pose et la reprise du bocal par la préhension, et pour le demi-tour ; EN BAS
     (course du trou du maneton) dès que le chariot de remplissage est au poste, et comme position d'attente.
     Supprimer `course_max_garage_m` (plus de garage au-dessus de la marche).
  3. **Demi-tour du porte-bocal** : seulement manivelle en haut ET chariot de remplissage à y ≥ 0,40
     (`mycelium → chariot → y_ecarte_min`, gardé). Manivelle en bas : refusé.
  4. **Chariot de remplissage** (`pi/vidange/remplissage`, `pi/vidange/mycelium/regles.py`) : supprimer « l'agitateur
     ne roule que chariot à y ≥ 0,40 » et « le chariot ne roule que si l'agitateur est au garage ou au dosage ».
     Nouvelles règles : au poste (y 0,135) manivelle en bas et bord du seau ≤ 0,68 TOUJOURS ; le chariot roule entre
     0,135 et 0,42 plateau monté, manivelle en bas ; dosage inchangé (y 0,155, plateau min(0,78 − h ; 0,575)).
     Spray (verrou 6 de `remplissage → verrous`) : plateau ≤ min(0,50 ; 0,68 − h) (`spray_bord_max_z: 0.68` au lieu
     de 0,71).
  5. **Vidage par la griffe à y 0,42** : nouveau `remplissage → vidage_y: 0.42` (le chariot y amène le seau vide et
     il y attend, jamais au poste plateau haut) ; `griffe → seau_remplissage: [0.925, 0.42]` (mât). Ordre d'un seau :
     vidage par la griffe à y 0,42 → poste (y 0,135) : spray, micropore → dosage à y 0,155 (manivelle en bas, bocal
     tête en bas) → retour. Le demi-tour se fait chariot à y ≥ 0,40.
  6. **Préhension au porte-bocal** (`prehension → porte_bocal`) : en (0,925 ; 0,150), face au contact de la capsule à
     1,05 (approche à 1,10), manivelle en haut, chariot reculé ou au poste. Supprimer l'exception « zone du garage »
     (`zone_garage_m`, `course_manivelle_m`, `capsule_manivelle_haut_z` et la condition « griffe en butée haute ») :
     x 0,925 est hors de l'isolation du fût (x < 0,71). La tête ne passe jamais au-dessus du bocal sauf pour le poser
     ou le reprendre.
  7. **Caméra du dosage** : remplacer `mycelium → camera_x_max` (« agitateur garé ») par les conditions b) à e) du
     point 6 de la décision : pas de pivot pendant le demi-tour, demi-tour seulement boîtier à 0°, pas de pivot tête
     de griffe ou de préhension dans la boîte x < 1,10, y < 0,34, z 0,95-1,08 (boîte dans `machine.yaml`), boîtier à
     0° avant la pose et la reprise du bocal. Aucune condition sur la manivelle, le bocal ni le chariot. Test de
     chaque cas.
  Tests : chaque condition refusée (demi-tour manivelle en bas, demi-tour chariot à 0,39, chariot au poste manivelle
  en haut, bord 0,69 au poste, spray avec 0,68 − h dépassé, préhension sur le bocal manivelle en bas) ; un cycle
  complet d'un seau dans le simulateur, dans l'ordre du point 5. `vidange --verifier` passe.
- [x] **19 bis. Ne jamais envoyer à une carte un fichier FluidNC d'exemple** — Modèle : Sonnet, effort bas.
  L'envoi de `fluidnc/<carte>.yaml` à une carte est refusé si le fichier est marqué EXEMPLE, avec un message clair
  qui dit quoi faire. Le simulateur et les tests peuvent toujours s'en servir. Tests.
- [x] **20. Porte-bocal (mors et demi-tour du bocal)** — Modèle : Opus, effort moyen.
  Sources (recopiées ici le 29/10/2026) : fiche du module « Porte-bocal », **validé définitivement le 24/10/2026**
  (fiche des pièces v10c), plan de commande v221, page « Passage de l'agitateur » du Mycélium (24/10).
  Les chiffres vont dans `pi/reglages/machine.yaml`, `docs/entrees-sorties.yaml` et `fluidnc/`, jamais dans le code.

  *Ce que fait le module.* Le porte-bocal est la partie de l'agitateur du Mycélium qui tient le bocal de semence :
  2 mors qui serrent le bocal, et un plateau tournant qui le retourne d'un demi-tour (debout ↔ tête en bas).
  La tâche 19 l'appelle derrière l'interface `PorteBocal` (`retourner_tete_en_bas`, `remettre_debout`) avec
  un faux : cette tâche écrit le vrai.

  *Moteurs et capteurs* (tous sur la carte 3 ; à ajouter à `docs/entrees-sorties.yaml` et `fluidnc/`, marqués
  `exemple: true` tant que le plan de câblage n'est pas arrivé) :
  - Mors : NEMA 17 simple (17HS4401, sans codeur ni frein) sur un TMC2209 en UART, sa sortie DIAG (StallGuard)
    sur l'entrée « probe » de la carte 3. Une vis gauche-droite rapproche les 2 mors ensemble : le bocal reste
    centré. Le courant de serrage se règle sur le pilote à l'essai, pas dans le code.
  - Fin de course « mors ouverts » : c'est l'origine des mors, reprise à **chaque** ouverture.
  - Demi-tour : motoréducteur JGY370 24 V à courant continu (pas un pas à pas), par un pont en H de l'armoire
    (2 sorties de la carte : le sens du courant donne le sens). Environ 2,3 s pour un demi-tour. Il est
    irréversible : il tient seul sa position.
  - Verrou : électroaimant 24 V (1 sortie). Son doigt entre dans un des 2 trous du plateau et bloque le demi-tour ;
    il n'est retiré **que pendant** le demi-tour. Contact « verrou engagé » : le doigt est bien entré.
  - Capteur d'inclinaison : dit si le bocal est debout ou tête en bas.
  - Il n'y a **pas** de capteur de capsule (supprimé le 23/10) ni de capteur sur les mors : ne pas les inventer.

  *Serrer un bocal* (bocal droit Ø 95, capsule Ø 103 ; diamètres et tolérance dans `machine.yaml`) :
  1. Mors ouverts sur le fin de course (origine reprise).
  2. Palpage (G38.2) jusqu'à l'arrêt par StallGuard (DIAG). Vitesse de palpage au-dessus du minimum de StallGuard
     (4 mm de jeu par côté pour prendre de la vitesse avant le contact) : réglage.
  3. La position d'arrêt donne le diamètre du bocal à ≈ 1 mm près. Diamètre hors de la plage attendue = bocal
     absent, cassé ou mal posé : arrêt, alerte avec photo.
  Ouvrir : retour au fin de course « mors ouverts ». Qui pose et reprend le bocal (la Préhension, au garage
  x 0,565) n'est pas dans cette tâche : ici, seulement `serrer_bocal()` et `ouvrir_mors()`.

  *Faire un demi-tour* (dans un sens ou dans l'autre) :
  1. Conditions (verrous, ils protègent la machine) : agitateur arrêté à x 0,865 (demi-tour), **manivelle en bas**
     (page du Mycélium du 24/10 : « manivelle en bas comme pour le demi-tour »), bocal serré, chariot de remplissage
     à y ≥ 0,375.
  2. Retirer le doigt du verrou (électroaimant), lancer le JGY370 dans le bon sens.
  3. Relâcher l'électroaimant après un court temps (réglage), quand le plateau a quitté le trou : le doigt
     frotte, puis entre dans le trou suivant. S'arrêter quand le contact « verrou engagé » revient ; délai maximal : réglage. Pas de retour du
     contact dans le délai : arrêt du moteur, alerte.
  4. Vérifier le capteur d'inclinaison (debout ou tête en bas, comme demandé), sinon alerte.
  5. Après chaque retour debout, demander une photo de contrôle du bocal (contour, fissure, bocal qui a bougé dans
     les mors) : l'analyse est dans la tâche 22 ; ici, un point d'appel qui accepte la réponse « bon / douteux »
     (douteux = arrêt et alerte).

  *Origine de la manivelle (précision du 29/10, voir `docs/decisions.md`)* : le capteur `origine_manivelle` voit
  du métal quand la manivelle n'est **pas** en haut, et rien sur ≈ ± 95° autour du haut. Écrire la prise d'origine
  de la manivelle : un tour lent, position du moteur aux 2 bords de la zone sans métal (même sens de rotation),
  « en haut » = le milieu, plus un décalage réglé dans `machine.yaml`. Contrôle à chaque prise d'origine : largeur de
  la zone (≈ 190°, réglée) à ± 10° près et 2 bords au plus sur un tour, sinon arrêt et alerte « capteur manivelle ». Corriger la ligne `origine_manivelle` de
  `docs/entrees-sorties.yaml` et le code de la tâche 19 s'ils supposent l'inverse. Tests avec un faux capteur.

  *À corriger dans le Mycélium (tâche 19)* : le geste fait aujourd'hui le demi-tour manivelle en haut. Le corriger :
  au demi-tour, manivelle en bas, demi-tour, manivelle en haut, puis la glissière roule (elle ne roule que
  manivelle en haut). Brancher le vrai porte-bocal à la place du faux, et garder le faux pour les tests.

  *Ce qui n'est pas dans cette tâche* : la pose et la reprise du bocal par la Préhension, le retournement d'une
  capsule seule (variante pas adoptée par Karulium), l'agitation des bocaux désignés en mode bocaux (avec le
  Stockage), l'analyse des photos (tâche 22).

  Simulateur : le scénario `mycelium` de la tâche 19 avec le vrai porte-bocal sur le faux FluidNC (serrage,
  demi-tours, photo de contrôle). Tests, dont : bocal absent (diamètre hors plage), verrou qui ne revient pas,
  capteur d'inclinaison faux, demi-tour refusé manivelle en haut.
- [x] **21. Lavage des seaux (eau, bain, brossage)** — Modèle : Opus, effort moyen. **Après la tâche 37
  (Préhension)**, dont il appelle les gestes.
  Sources (recopiées ici le 29/10/2026) : fiche du module « Lavage », **validé définitivement le 25/10/2026**
  (fût de 44 cm), dossiers eau automatique, arrosage (validé 22/10, colliers 27/10), chauffage (22/10), jet d'air du
  col (14/10), plan de commande v221. Chiffres dans `pi/reglages/machine.yaml`, `docs/entrees-sorties.yaml` et
  `fluidnc/`, jamais dans le code. Les couvercles et les bocaux sont dans la tâche 21 bis.

  *Ce que fait le module.* Entre deux fûts de production, un fût de lavage (inox, Ø intérieur 0,45) vient au poste.
  Dedans : un noyau à brosses (intérieur du seau) et une couronne de brosses extérieures. La Préhension tient le
  seau retourné (bord en bas) par la ventouse et **ne le lâche jamais** ; elle le descend dans les brosses, il est
  brossé mouillé, rincé, soufflé, puis repart.
  Centre du fût de lavage (0,35 ; 0,65) : réglage à part (`centre_fut` de `machine.yaml` est celui du fût de
  production, (0,29 ; 0,57)).

  *Mode lavage* : seulement si le panneau du poste est « rabattu » (contact du panneau déjà lu, `docs/decisions.md`)
  et le mode « lavage » choisi ; un changement d'état du panneau pendant un mouvement ⇒ « feed hold » des cartes 1
  et 4 et alerte. Le fût de lavage lui-même n'est pas détecté.

  *Moteurs, entrées, sorties* (à ajouter, marqués `exemple: true` tant que le plan de câblage n'est pas arrivé) :
  - Carte 4 (avec la Préhension) : NEMA 23 du **noyau** et NEMA 23 de la **couronne**, avec les alarmes de leurs
    pilotes. La rotation de la tête de préhension est dans la même commande : elle suit le seau. **Pas de capteur
    d'origine** (le capteur Hall a été supprimé le 22/10) : la position de la couronne ne compte pas. La couronne
    ne tourne que dans un sens (« toujours en avant »).
  - Carte 3 (avec le Mycélium) : électrovanne d'eau du réseau (remplir), vanne à bille motorisée (vider, ≈ 15 s
    pour s'ouvrir), pompe à membrane, vanne 3 voies motorisée après la pompe (voie bonde / voie rampes),
    électrovanne de rinçage (eau du réseau dans les rampes), électrovanne d'air du jet du col, relais (SSR) de la
    prise du thermoplongeur ; entrée : flotteur (contact sec).
  - Aucun capteur « brosses fermées » : rien à attendre à ce sujet.

  *Eau du fût* :
  - Remplir : vanne à bille fermée, électrovanne d'eau ouverte jusqu'au flotteur haut. Temps maximal = temps du
    premier remplissage mesuré + 20 % (réglage) ; au-delà : fermer, alerte (l'eau monterait aux poulies).
  - Vider : vanne 3 voies vers la bonde, vanne à bille ouverte (attendre ≈ 15 s), pompe ; quand le flotteur
    retombe, continuer ≈ 60 s (réglage), arrêter la pompe, fermer la vanne.
  - Quand : par défaut, eau neuve au début de chaque série (un fût de production, ≈ 18 seaux) et vidange à la fin ;
    réglage. **Le fût est toujours vidé avant d'être échangé** : le Pi refuse de déclarer la série finie sans vidange.
  - Chauffage : le Pi n'alimente la prise du thermoplongeur (2 kW, thermostat réglé à 50 °C sur l'appareil) que
    flotteur haut et pompe arrêtée. Le thermostat de l'appareil règle la température ; le Pi ne la mesure pas.
  - Produit : percarbonate, mis à la main (pas de dosage par la machine).

  *Laver un seau* (la Préhension tient le seau retourné) :
  1. Aller au fût par le couloir du seau retourné : axe de la tête de (0,35 ; 0,65) en ligne droite jusqu'à
     (0,45 ; 0,74), puis vers +x à y 0,74 ; entrée par le même chemin à l'envers ; ventouse à 1,10 (butée haute)
     pendant tout le trajet. Passage de la paroi côté stockage : règles déjà dans `machine.yaml`
     (`lavage_paroi_*`).
  2. Descendre : le seau écarte lui-même les brosses extérieures.
  3. **Verrou du noyau et de la couronne** : ils ne tournent **jamais** sans seau (ou couvercle) posé dessus. Le Pi
     n'envoie leur rotation que si la préhension est à sa hauteur de travail au-dessus du fût et que le vide confirme
     un objet tenu (`tient_un_objet()` de la tâche 37) ; toute perte de vide arrête noyau et couronne. Le mode
     manuel du téléphone applique le même verrou.
  4. Arrosage pendant le brossage : pompe sur la voie des rampes (bain recyclé). On ne brosse jamais à sec.
  5. Passe 1, paroi et fond : noyau ≈ 5 s à 100 tr/min (centre du fond), puis ≈ 200 tr/min. Appui 80 N lu par le
     capteur de force de la préhension, tête décalée de façon fixe vers +x selon le format (tête x ≥ 0,35, jamais
     de cercle autour de l'axe) ; c'est le seau qui tourne dessous.
  6. Passe 2, le bord : brosses fermées, couronne en avant.
  7. Rinçage propre : électrovanne de rinçage ≈ 5 s (≈ 0,5 L) dans les rampes ; puis la pompe vide jusqu'au
     flotteur bas pour garder le même niveau.
  8. Remonter selon le vide (tâche 37 : −55 / −40 kPa, feed hold, 2 essais) ; retrait ≈ 35 N.
  9. Jet d'air du col : décaler le seau vers la buse et l'arrêter le bord à sa hauteur (A 11 mm, bord 0,711 ;
     B 17 mm, 0,698 ; C 0, 0,714 ; D 8 mm, 0,712 ; réglages par format, à ajuster à l'essai), ouvrir l'air, faire
     1 tour en ≈ 4 s, fermer, remonter. Égoutter au-dessus du fût.
  Durées des passes, vitesses de la couronne et du seau : réglages (estimation du plan : passe 1 ≈ 15-20 s,
  passe 2 ≈ 10-15 s, ≈ 60-70 s par seau).

  *Ce qui n'est pas dans cette tâche* : couvercles et bocaux (21 bis), la prise et la pose du seau sur les piles
  (Stockage), la photo de contrôle après lavage (« vue A », tâche 22), le bain et l'UV des têtes (Nettoyage).

  Simulateur : un scénario `lavage` : remplissage, 3 seaux lavés (A, B, C), vidange, avec faux flotteur et faux
  vide. Tests, dont : noyau refusé sans objet tenu, perte de vide pendant la rotation, remplissage trop long,
  chauffage refusé flotteur bas, série refusée sans vidange, panneau qui change pendant un mouvement.

- [x] **21 bis. Lavage des couvercles et des bocaux** — Modèle : Opus, effort moyen. Après la tâche 21.
  Mêmes sources. Le lave-bocal et le retourneur sont posés **à la main** avant leur série et enlevés après ;
  **D'abord**, corriger le lavage des seaux (tâche 21) selon `docs/decisions.md`, « Lavage des seaux », points 3,
  6 et 7 : eau du réseau jusqu'au flotteur haut après la pompe qui suit le rinçage ; vanne 3 voies remise sur
  « rampes » dès que la pompe s'arrête, et alerte « fuite ou siphon » si le flotteur retombe sans vidange ; jet
  d'air aux centres donnés par format (réglage `x, y` au lieu de `jet_decalage_m`, avec ses tests) ; rotation de
  la tête jusqu'à ± 500° (point 4) ; passe 2 sans remontée (point 5, déjà 0).
  bocaux et seaux ne se lavent jamais en même temps.

  *Couvercles de seau, dans le fût* :
  1. La tête amène le couvercle face vers le bas au-dessus du noyau, centre (0,35 ; 0,65) (pont à sa limite 0,223).
  2. Avant la pose, la tête tourne le couvercle pour mettre son repère (collé sur le dessus, près du bord) à ≈ 60°
     de −X côté +Y ; photo par la caméra du plafond.
  3. Descente : dessous du couvercle à z 0,638 (A), 0,637 (B), 0,640 (C et D), appui ≈ 15 N (jamais plus : si les
     dépôts sont secs, on allonge le temps). Plateau flottant déclenché au-dessus de 0,735 ⇒ arrêt et alerte.
  4. Noyau 100 tr/min ≈ 5 s. Pendant ce temps la tête décale le centre du couvercle dans la direction
     (+0,26 ; −0,97) de 21 mm (A), 0 (B), 21 mm (C), 23 mm (D), et le fait tourner lentement (10 à 20 tr/min).
  5. Pendant la rotation, la caméra du plafond compare l'angle du repère (quand il est visible) à l'angle commandé :
     écart > 10° = le couvercle glisse : arrêt du noyau, remontée de 2 mm, reprise ; alerte après 2 glissements.
     Vide surveillé (arrêt à −40 kPa). L'analyse d'image est dans la tâche 22 : ici, un point d'appel avec un faux.
  6. Fin : repère ramené à son angle de photo, arrêt du noyau, remontée, égouttage, 2e photo (repère à ± 10°,
     sinon alerte et couvercle « à vérifier »).

  *Retourneur de couvercles* (tige Ø 12 sur une barre du chariot de remplissage, x 0,9425 ; chariot en y 0,50,
  plateau fixe à 0,459 avec un bac inox) — pour laver les 2 faces :
  - Avant le mode couvercles, la caméra trouve le bac et la tige à ± 5 mm de leur place, sinon le mode ne démarre pas.
  - Séquence par couvercle : dessous lavé ; lâcher au-dessus de la tige (tête en (0,9675 ; 0,53), barres à 0,19 de
    l'axe) ; la tête remonte à ventouse 0,85 puis recule jusqu'à son axe à x ≤ 0,87 ; photo (couvercle dans le bac,
    à plat, face attendue, centre mesuré) ; ouverture des barres 0,19 → 0,30 avant que la tête descende sous 0,75 ;
    reprise au centre mesuré ; dessus lavé ; barres refermées à 0,19 quand la tête est au-dessus de 0,80 ;
    2e chute, photo, reprise par le dessus, rangement.
  - Photo pas bonne : pas retourné ⇒ nouvelle chute, alerte après 2 échecs ; hors du bac ou penché ⇒ arrêt, alerte.
  - Barrière lumineuse à 0,7315 : surveillée en continu dans ce mode ; coupée ⇒ pause avec message.
  Les barres et le chariot appartiennent au Remplissage (tâche 34) : ici, derrière une interface avec un faux.

  *Bocaux et capsules : lave-bocal* (posé à la main sur l'anneau de rive du fût de lavage) : la tête appuie le
  bocal retourné (ou la capsule, tenue par les aimants) sur le plateau d'un rince-verre de bar, qui projette de
  l'eau tant qu'on appuie. Pas d'électrovanne (vanne quart de tour manuelle au robinet). Le Pi ne fait que la
  position, l'appui et la durée (réglages : hauteur du plateau ≈ 5 mm au-dessus de l'anneau de rive, à mesurer sur
  le produit acheté ; appui et temps à l'essai), puis égouttage au-dessus du fût. La vidange automatique évacue
  l'eau. Le Pi ne sait pas si le lave-bocal est posé : l'écran demande de le confirmer avant une série de bocaux.

  *Ce qui n'est pas dans cette tâche* : la vue A après lavage et l'analyse des photos (tâche 22), le rangement des
  bocaux et des couvercles (Stockage).

  Simulateur : scénario `lavage_couvercles` (2 couvercles, avec retournement) et `lavage_bocaux` (3 bocaux).
  Tests, dont : couvercle qui glisse 2 fois, plateau flottant trop haut, mode refusé si le bac n'est pas trouvé,
  barrière coupée.
- [x] **37 bis. Préhension au porte-bocal : zone du garage** — Modèle : Sonnet, effort moyen. Appliquer les
  réponses du 29/10 (`docs/decisions.md`, section « Préhension », points 1 et 3) : `porte_bocal.y` à 0,150 dans
  `machine.yaml` ; exception à l'isolation du fût dans la petite zone du garage (± 5 mm, réglage) avec ses 3
  conditions (manivelle en bas, course déclarée 7 cm ; mors ouverts pour poser, serrés pour prendre ; griffe en
  butée haute) ; refus de passer la tête au-dessus du bocal au garage manivelle en haut ; la griffe peut être dans
  la bande `garage_glissiere` seulement en butée haute. Tests de chaque condition refusée.
- [x] **37 ter. Préhension : bocal de l'agitateur partout sur la glissière ; rinçage des couvercles** — Modèle : Sonnet, effort bas.
  Réponse à la PR n° 37 (`docs/decisions.md`, Préhension) : la zone interdite au-dessus du bocal (manivelle pas en
  bas) suit la position de l'agitateur (x du bocal = position de la glissière, y 0,150), du garage au dosage ; sans
  information sur l'agitateur, toute la glissière est interdite à la tête. Tests : agitateur au demi-tour et au
  dosage manivelle en haut, glissière inconnue.
  Dans la même session : rinçage propre des couvercles à la fin de chaque face, comme pour les seaux
  (`docs/decisions.md`, « Couvercles et bocaux au lavage », point 3), avec son test.
- [x] **22. Vision de base : caméras, QR, repères ArUco, caméra du dosage, caméra du plafond** — Modèle : Opus,
  effort moyen.
  Sources (recopiées ici le 30/10/2026) : fiche du module « Guidage caméra », **validé définitivement le 24/10/2026**,
  page « Caméra du plafond : deviner le travail » (tableau des 9 règles validé tel quel le 24/10), plan de commande
  v223, règles déjà dans `docs/decisions.md`. Les chiffres vont dans les fichiers de réglages, jamais dans le code.
  Bibliothèques : **OpenCV** (`opencv-python-headless`) et numpy, rien d'autre (pas de YOLO tant qu'il n'y a pas de
  photos réelles pour l'entraîner). Tout se teste avec des **images fabriquées** (QR et ArUco dessinés par OpenCV).

  *Ce qui existe* : `pi/vidange/cameras/` (tâche 12) lit le flux de chaque caméra (`programme.yaml`), sert la vidéo et
  garde les clips. Les modules déjà écrits appellent la vision par des **points d'appel avec un faux** : Mycélium
  (`photo(raison)`, QR du bocal), Porte-bocal (photo « bon / douteux »), Préhension (`anse_levee`,
  `camera_dosage_pivote`, `photo`), Lavage des couvercles (`VisionCouvercles`), Poste du fût (QR du fût). Cette tâche
  écrit les outils de vision et relie ceux qui ne demandent pas de photos réelles ; les autres gardent leur faux
  (tâche 22 ter).

  *Les caméras* (positions et modèles dans les réglages, marqués `exemple: true` jusqu'au montage) :
  - **Plafond** : Camera Module 3 Wide (102° × 67°) dans le toit, en (1,45 ; 0,50), objectif à ≈ 2,35 m ; voit toute
    la machine (≈ 1 mm par point). Photo seulement **pont garé au bout opposé** (sinon il cache la vue).
  - **Tête de griffe** : caméra USB ≥ 5 Mpx dans le boîtier de tête, qui voit par une fenêtre Ø 25 au centre du toit
    de la chape (le boîtier porte aussi un ToF VL53L1X, 2 LED et un thermomètre IR MLX90614, lus par une XIAO RP2040
    en USB : ici, seulement la caméra ; les capteurs ont une case vide).
  - **Dosage** : caméra Wide à filtre IR sur un servo DS3225 : **0° = bocal, 63° = seau**.
  - **Micropore** (lit aussi le QR du seau) et **vue A** (vers le haut, place A (2,50 ; 0,22)) : déclarées seulement,
    servies par les tâches qui s'en servent.
  - Toutes les photos de mesure se prennent **à l'arrêt, après 0,3 s de stabilisation**, LED de l'enceinte allumées
    (toujours les mêmes).

  *Calibration* : une fois par caméra, avec une mire en damier (OpenCV), pour corriger la déformation du grand angle.
  Un outil d'essai prend les photos et calcule le fichier de calibration ; les mesures s'en servent.

  *QR* (codes « S1293 », « B327 »... déjà utilisés par le registre) :
  - Caméra de tête, **godet grand ouvert, axes à 1,05**, lecture par paquets (≈ 9-10 photos pour 95 couvercles) ;
    une fonction rend les codes lus et leur position dans le repère du portique.
  - QR du bocal de semence relu de près juste avant que la préhension le prenne.
  - Le QR donne aussi **l'angle** de l'objet (repère d'angle, plan v181) : rendu avec le code.
  - QR illisible : deuxième tour, puis photo à une autre hauteur, sinon objet marqué « à vérifier » au registre.

  *Repères ArUco* : un repère de 40 mm sur le plateau du rince-verre du lave-bocal (et ceux du calibrage du plafond).
  Dictionnaire et numéros : réglages.

  *Caméra du dosage* : brancher le servo (sortie à déclarer, `exemple: true`) et le verrou **déjà dans
  `docs/decisions.md`** (pivote seulement agitateur garé, bocal x ≤ 0,62, et griffe et préhension hors de la boîte
  x < 1,10, y < 0,34, z 0,95-1,08 ; remonte avant le retour de l'agitateur ou du godet). Photo du seau **après
  chaque godet**, enregistrée avec sa dose au registre. Brancher le vrai point d'appel `photo(raison)` du Mycélium et
  `camera_dosage_pivote` de la Préhension.

  *Caméra du plafond* :
  1. **Lave-bocal** : juste avant chaque geste dangereux pour lui (lever un seau dans le fût de lavage, faire tourner
     noyau ou couronne), une photo de **moins de 5 s**, pont garé. Repère ArUco vu ⇒ lave-bocal posé (seau, noyau,
     couronne interdits) ; fût vide vu clairement ⇒ seaux permis ; doute (vue cachée, buée, objet inconnu) ⇒ rien ne
     bouge, alerte avec la photo, on attend le bouton « Vérifié ». La caméra et la confirmation à l'écran de la tâche
     21 bis doivent être d'accord ; sinon, doute.
  2. **Deviner le travail** : la photo devient une liste d'objets (fût du poste plein ou vide ; bocaux au stockage,
     avec ou sans capsule, propres ou sales ; seaux vides, pleins, avec ou sans couvercle ; places libres ; bocal de
     semence au garage ; fût de lavage vide, avec un seau, ou lave-bocal ; objet inconnu ou mal placé). Puis le
     tableau, dans l'ordre, le premier cas qui correspond gagne :
     1. objet inconnu, ou pièce mal placée sur un trajet ⇒ rien ne bouge, alerte avec la photo ;
     2. fût plein de maïs + bocaux vides et propres au stockage ⇒ remplir les bocaux ;
     3. fût plein + pas de bocaux vides + seaux vides propres + bocal de semence prêt ⇒ remplir les seaux et ajouter
        le mycélium ;
     4. fût plein mais rien de vide et propre où le mettre ⇒ alerte « rien à remplir » ;
     5. bocaux sales + lave-bocal posé ⇒ laver les bocaux ;
     6. bocaux sales + lave-bocal absent ⇒ demander de poser le lave-bocal ;
     7. seaux ou couvercles sales + lave-bocal absent ⇒ laver les seaux ;
     8. seaux sales + lave-bocal posé ⇒ demander de retirer le lave-bocal ;
     9. rien de tout cela ⇒ attendre, nouvelle photo toutes les 5 min (réglage).
     Le Pi **propose** le travail et attend le « Go » de Karulium (règle 6 de `CLAUDE.md`). Le tableau est dans un
     fichier de réglages (il sera corrigé après les premiers essais). La **reconnaissance** des objets demande une
     trentaine de photos réelles par situation : ici, une interface `Reconnaissance` et un faux ; le vrai viendra
     avec les photos. Sans reconnaissance sûre, c'est le cas 1 (doute).

  *Ce qui n'est pas dans cette tâche* : l'analyse d'images des points d'appel qui demandent des photos réelles
  (bocal « bon / douteux », anse levée, repère et bac des couvercles : tâche 22 ter), l'inspection après lavage
  (vues A et B, polarisation croisée, stéréophotométrie, speckle : plus tard), les capteurs ToF et IR de la tête.

  Simulateur et tests : QR lus sur des images fabriquées (droits, tournés, flous, illisibles), angle rendu par le QR,
  ArUco du lave-bocal vu / absent / caché, verrou du servo du dosage, les 9 règles du plafond (chacune, et leur
  ordre), photo trop vieille refusée. Outil d'essai pour la calibration et la lecture des QR, procédure pas à pas
  sur le vrai matériel ; « testé sur le vrai matériel : non ».
- [ ] 22 ter. Vision : analyses qui demandent des photos réelles (bocal « bon / douteux » au retour debout, anse
  levée, repère et bac des couvercles, alignement des seaux de la bande du haut y 0,215 ± 0,007). Règles à recopier
  quand les premières photos existeront.
- [x] **22 bis. Cartes de pesée RS485 (RP2040 + HX711) : griffe, préhension, plateau du remplissage** — Modèle : Opus.
  Programme C (Pico SDK, comme l'accéléromètre) : lecture du HX711 en 3,3 V, jusqu'à 80 mesures/s, réponse sur le
  bus RS485 `rs485_pesee` quand le Pi l'interroge (une adresse par carte, contrôle CRC), mise à jour depuis le Pi
  si c'est simple. Côté Pi : lecture des 3 cartes à tour de rôle, 115 200 bauds, adaptateur USB-RS485 reconnu par
  son numéro de série. Procédure d'essai à l'établi ; « testé sur le vrai matériel : non ».
- [x] **45. Programme principal : brancher les modules du mode seaux** — Modèle : Opus, effort élevé. **À faire
  avant la tâche 23.** Aujourd'hui `demarrage.py → preparer_chef` ne connaît que « lieu_sur » ; les modules existent
  (`module_echange_fut`, `module_griffe`, `module_remplissage`, `module_mycelium`, `module_spray`, Micropore,
  Fermeture, `module_prehension`, `module_lavage`, Stockage, Portique, Nettoyage, Air) mais ne sont joués que par le
  simulateur.
  - Construire les modules du **mode seaux** au démarrage, à partir du matériel (vrai ou faux) et des réglages, et
    les donner au chef (`reprendre_cycle`, puis `lancer`) ; leurs conditions (`chef.condition_permission("air")`,
    store, purge, préhension dégagée, bras rangé...) branchées comme le disent `docs/decisions.md` et les tâches.
  - Un module dont le matériel ou les réglages manquent (`exemple: true` interdit sur la vraie machine, case vide,
    geste pas encore écrit : pose du couvercle, tâche 41 bis ; vision du micropore, tâche 40 ter) n'est pas lancé,
    et l'écran et la check-list disent lequel et pourquoi. Jamais de geste inventé.
  - Un seul endroit qui dit l'ordre du cycle d'un seau (fût → griffe → remplissage, mycélium, spray, micropore,
    couvercle, fermeture → stockage, lavage des vides), lu par le chef et par le simulateur.
  - Simulateur : `vidange-simulateur cycle` joue un lot complet de seaux d'un format sur le faux matériel, avec le
    même code de démarrage que la vraie machine.
  - Le mode bocaux et la nuit UV-ozone ne sont pas dans cette tâche (tâche 45 bis).
  - Si la tâche est trop grosse : faire d'abord le branchement et le cycle simulé jusqu'au remplissage, et poser la
    question dans la PR.
  Tests : démarrage avec faux matériel ⇒ les modules attendus sont prêts ; un module sans réglage ⇒ pas lancé, avec
  la raison ; reprise après coupure au milieu d'un seau (carnet) ; lot complet simulé sans alarme.
- [x] **45 bis. Programme principal : mode bocaux et nuit UV-ozone** — Modèle : Sonnet. À faire après la 45 :
  même branchement pour `module_entonnoir`, `module_lavage_bocaux` et la nuit UV-ozone.
- [x] **45 ter. Programme principal : construire les vraies cartes du chariot et de la tête** — Modèle : Opus,
  effort moyen. Dans `pi/vidange/cycle/machine.py` (`PiecesMachine`), construire depuis `docs/entrees-sorties.yaml`
  et les réglages : carte du plateau du chariot (RP2040-Zero, pesée, PCA9685, ToF), tête de la Préhension, Lavage,
  cartes FluidNC, spray ; c'est ce qui bloque encore les postes « qr_du_flanc », « micropore », « couvercle »,
  « fermeture », « entonnoir » et « lavage » sur la vraie machine (PR 89 à 92). Chaque pièce absente ou en EXEMPLE ⇒
  poste « pas lancé : raison ». Pas de geste nouveau. Tests avec le faux matériel branché par le même chemin que le
  vrai ; procédure d'essai « démarrer la vraie machine et lire la check-list ».
- [x] **19 quater. Bocal neuf de semence pour le Mycélium** — Modèle : Sonnet, effort moyen. Le geste
  `nouveau_bocal` (prise d'un bocal de semence au stockage, ouverture de la capsule, pose sur le porte-bocal /
  l'agitateur) n'existe que dans le simulateur ; c'est lui qui bloque le cœur d'un lot sur la vraie machine (PR 93).
  Source, recopiée ici le 07/11/2026 : `prehension/logiciel/bocal-neuf-pour-logiciel.md` (fil Préhension, 20 étapes) :
  dévissage de la capsule sur la place du bocal au stockage (aimants, appui 80 N, sens trigo, contrôle au palier
  pesé) ; capsule dans la boîte (2,52 ; 0,53), couvercle percé pris dans la boîte (2,52 ; 0,80) ; vissage au calage du
  moteur ; couloir côté allée, méplats à ± 3° ; pose au M8 à `contact_capsule_bocal` ; mors à Ø 98, lâcher, remontée
  de 5 mm, puis serrage. Le Pi recopie l'identité du bocal AVANT le dévissage (le QR est sur la capsule). § 4.1
  ouvert (bocal qui tourne sur la tôle nue : tapis silicone, couple d'ouverture à mesurer) : l'étape 5a couvre
  l'échec. Ne pas inventer le geste. Construire aussi le Mycélium (agitateur, porte-bocal) dans `cycle/machine.py`
  et brancher `nouveau_bocal` dans le cycle. Tests : les cas d'erreur de la fiche et le lot simulé sans alarme.
- [x] **45 quater. Programme principal : le lot complet sur les vraies cartes** — Modèle : Opus, effort moyen. Après
  la 19 quater. Écrire `PiecesMachine.remplissage`, `entonnoir` et `lavage_bocaux` (PR 93), lancer les boucles de
  fond des pièces (balance, vide, battement des servos) avec le lot, et le bouton « Lot de seaux » / « Lot de
  bocaux » sur la page web puis le Go à l'écran (`docs/decisions.md`, PR 89, question 1).
- [x] **45 quinquies. Inventaire du stockage depuis la page web** — Modèle : Sonnet, effort bas. Saisir et corriger à la
  main ce que contient le stockage (bocaux de semence par variété et par place, capsules et couvercles percés dans les
  boîtes, piles de seaux vides par format, couvercles), avec le Go de Karulium avant d'écrire ; le lot (tâche 45
  quater, `refus_taille_lot`) lit ces nombres. Journal de chaque correction. Tests et procédure courte.
- [x] **45 sexies. Programme principal : construire la griffe et l'enchaîner (seaux et bocaux)** — Modèle : Opus,
  effort moyen. Le solveur (tâche 23) ne l'a pas fait : il ne fait que l'ordre de priorité. Aujourd'hui
  `Sources.griffe` et `Sources.versement_bocal` restent à None sur la vraie machine (`pi/vidange/cycle/machine.py`,
  textes `GRIFFE_DU_LOT` et `VERSEMENT_BOCAL`).
  1. Construire la griffe sur ses vraies cartes au démarrage (bras FluidNC, pesée RS485 de la griffe, poste du
     fût), comme les autres pièces : absente = « pas lancé : raison », jamais d'arrêt du démarrage.
  2. Enchaînement du mode seaux avec ce qui existe déjà : `seau_pret` (Remplissage : seau au poste, couche de
     mycélium d'avant versée), `pont_libre` (la Préhension n'a pas besoin du pont : les deux mâts sont sur le même
     chariot), la permission « verser » du Remplissage, `GriffeDuLot.partie()` et `versement_s`. Les zones et les
     règles du Portique (pont, mâts, garde du boîtier de la caméra du bocal) restent celles du chef.
  3. Mode bocaux : brancher `vidange.griffe.versement` (tâche 43 bis) comme `Sources.versement_bocal`.
  4. Corriger les textes qui renvoient à tort à la tâche 23 pour ces deux points.
  5. Si un geste ou une règle d'enchaînement manque dans `docs/decisions.md` (ne pas l'inventer) : garder la case
     vide, le dire dans la PR (« Questions pour Karulium »).
  Procédure d'essai sur le vrai matériel ; « testé sur le vrai matériel : non ».
- [x] **45 septies. Réponses des fils du 07/11 : bocaux refusés, zone du bras du spray, couvercle C** — Modèle : Opus,
  effort moyen. Trois corrections de règles déjà codées, d'après des fiches des modules (lire ces seuls fichiers dans
  `/mnt/project-files/`, montage réseau : ne jamais chercher dans tout le dossier).
  1. **Bocaux refusés par le versement (tâche 43 bis : 29 sur 122)** :
     - Griffe (`griffe/logiciel/reponses-07-11.md`) : aucune limite en y au-dessus des bocaux, ni à 20° ni à 35° ;
       la rangée 1 (y 0,06) passe (le « y ≥ 0,11 » était trop prudent). Seules limites : la course Y du portique
       (mât y ≥ 0,04, à vérifier dans les réglages du portique) et la garde du boîtier de la caméra du bocal.
     - Maquette (`griffe/logiciel/garde-camera-bocal-maquette.md`, maquette v45.120) : la bande de garde s'arrête à
       mât x 1,205 ; `bocal_0_0` et `bocal_2_0` (x 1,2075) sont permis. Garder la ligne « 1,15 – 1,204 » de la table
       « y minimum du mât », sans l'élargir d'1 cm.
     - Préhension (`prehension/logiciel/tete-basse-versement-bocaux.md`) : pour la dernière rangée (y 0,8224), tête de
       préhension basse pendant ces versements : face 0,90 (au plus 0,942), tête vide, descend seulement si la
       préhension est à x ≥ 1,20, descend avant que la griffe passe y 0,80 et remonte après son retour. Noms proposés :
       `prehension_face_basse_versement`, `prehension_x_min_tete_basse`, `griffe_y_max_tete_haute`.
     Résultat attendu : `vidange-entonnoir versement` ne refuse plus aucun des 122 bocaux pour ces raisons.
  2. **Zone du bras du spray** (fil Spray, 07/11/2026, EXEMPLE tant que la Maquette ne l'a pas balayée) : le bras ne
     sort et ne rentre que si aucune partie de la tête de la griffe, de la préhension ou de ce qu'elles tiennent n'est
     dans **x 0,66-0,95, y −0,03-0,24, z < 0,85**. C'est la zone qui fait foi, pas l'événement « griffe partie »
     (`GriffeDuLot.partie()`, tâche 45 sexies) ; outil traîné par le pont compris (enveloppe en butée haute et charge,
     voir decisions « La griffe dans les lots, réponses à la PR n° 99 », point 3).
  3. **Couvercle C** (`prehension/logiciel/pose-couvercle-pour-logiciel.md` § 5.1, jeux ≥ 10,3 mm contrôlés par la
     Maquette v45.120) : pour le format C seulement, outil en (0,925 ; 0,498) de la face 0,70 à 0,545, recentrage à
     y 0,49 à face constante 0,545 à 10 mm/s, puis descente droite jusqu'au contact. A, B et D descendent droit. Le
     recul du servo du micropore pour le couvercle C est **annulé** : l'enlever s'il est codé.
  Procédure d'essai sur le vrai matériel ; « testé sur le vrai matériel : non ».
- [x] **45 octies. Tête de la griffe à 0° en mode bocaux, verrou de la zone du spray, remontée du couvercle C** —
  Modèle : Opus, effort moyen. Suite de la 45 septies (PR n° 100) :
  1. **Défaut** : sur la machine imaginaire, un lot de 4 bocaux ou plus s'arrête au 4ᵉ bocal (« tête à −180°, il faut
     0° ») : la griffe ressort parfois du fût tête tournée (vient de la tâche 43 bis). Chaque prise du mode bocaux
     finit tête à 0°, dans le fût, avant la sortie. Rendre aux tests de lot leur taille normale (plus de limite à 3).
  2. **Verrou de la zone du bras du spray** pendant qu'il bouge : tant que le bras sort ou rentre, ni la griffe, ni la
     préhension, ni ce qu'elles tiennent, ni l'outil traîné par le pont (enveloppe en butée haute et charge) n'entrent
     dans `spray → bras → zone` (EXEMPLE). Par les zones du chef si c'est possible.
  3. **Couvercle C** (fil Préhension, 07/11/2026, § 5.1 de `prehension/logiciel/pose-couvercle-pour-logiciel.md`) :
     **toute** remontée avec le couvercle encore tenu (erreurs 10a, 10b, ou n'importe quel arrêt avant le lâcher)
     refait le chemin à l'envers : montée droite à 10 mm/s jusqu'à la face 0,545, décalage à y 0,498 à face
     constante, puis montée en haut. Après le lâcher, la tête seule remonte tout droit. Vérifier et compléter ce que
     la 45 septies a fait (elle couvre 10a et 10b).
  Procédure d'essai sur le vrai matériel ; « testé sur le vrai matériel : non ».
- [x] **45 nonies. Reprise après coupure avec un objet tenu, et bocal_0_1 posé par la machine** — Modèle : Opus,
  effort moyen. Deux réponses des fils du 07/11/2026 (à recopier dans `docs/decisions.md`) :
  1. **Objet tenu à la ventouse à la coupure** (fil Préhension) : les électrovannes « aspirer » et « souffler » sont
     normalement fermées et un clapet anti-retour garde le vide ; l'objet reste d'abord tenu puis peut tomber au bout
     d'un temps inconnu (sous la face 0,545, un couvercle C tomberait de travers sur le seau). Vaut pour tout objet à
     la ventouse (seau, couvercle, Pétri) ; un objet aux électroaimants (capsule, bocal par son couvercle percé) tombe
     tout de suite. À faire :
     - check-list de reprise : « vérifier la tête et le seau : enlever à la main l'objet tenu ou tombé avant le Go » ;
     - au redémarrage, **avant tout mouvement**, le Pi lit le capteur de vide de la préhension : plus bas que
       −20 kPa (réglage), quelque chose est encore tenu → l'écran et la page disent « objet encore tenu » et le Pi
       attend (pas de Go possible tant que c'est le cas) ;
     - **jamais** de « souffler » automatique au redémarrage.
  2. **bocal_0_1 posé par la machine** (Maquette, remesure du 07/11 : `griffe/logiciel/griffe-entrainee-entonnoir-
     maquette.md` et `griffe/logiciel/carte-griffe-butee-haute-bocaux.txt` dans `/mnt/project-files/`, lire ces seuls
     fichiers) : mât de la griffe = x bocal − 0,176, en butée haute (axes 1,265). Rectangles où le mât est libre :
     y ≥ 0,32 ; x ≥ 1,22 ; x ≥ 1,10 avec y ≤ 0,10 ; x 0,79-0,97 avec y 0,22-0,40. bocal_0_1 (mât 1,1415 ; 0,06) est
     libre, par le chemin : descendre en y dans x ≥ 1,22, puis aller en −x à y ≤ 0,10. Remplir
     `griffe → y_min_mat → exceptions_butee_haute` (tâche 45 octies) avec ces rectangles et ce chemin ; bocal_0_0,
     bocal_1_0 et bocal_2_0 restent posés à la main (contact ou moins de 1 cm).
  Procédure d'essai sur le vrai matériel ; « testé sur le vrai matériel : non ».
- [x] **45 decies. Vannes de la préhension fermées au démarrage, carte de la griffe en butée haute à 1,29** — Modèle :
  Opus, effort moyen. Réponses des fils du 07/11/2026 (à recopier dans `docs/decisions.md`) :
  1. **Vannes au démarrage** (fil Préhension) : après un plantage du Pi, « aspirer » peut rester ouverte (rien de
     matériel ne la coupe ; pas dangereux : venturi qui souffle, objet tenu). Au démarrage, fermer **les deux** vannes
     (« aspirer » et « souffler ») est sans risque (le clapet garde le vide), puis lire le vide (tâche 45 nonies).
     **Jamais ouvrir « souffler »** au démarrage. C'est une exception écrite à la règle « rien n'est commandé au
     démarrage » : seulement ces deux fermetures. Le chien de garde dans la carte des électrovannes (fermer
     « aspirer » seule si le Pi ne parle plus depuis ≈ 2 s) est un confort : le préparer seulement si le programme de
     cette carte est dans le dépôt, sinon le noter dans « ce qui reste ».
  2. **Carte de la griffe en butée haute refaite à 1,29** (Maquette, `griffe/logiciel/griffe-entrainee-entonnoir-
     maquette.md` et `griffe/logiciel/carte-griffe-butee-haute-bocaux.txt` dans `/mnt/project-files/`, lire ces seuls
     fichiers ; la carte à 1,265 utilisée par la 45 nonies est périmée) : mât de la griffe = x bocal − 0,176 ; un seul
     rectangle interdit, **x ≤ 1,07 avec y ≤ 0,11** (chariot de l'agitateur) ; partout ailleurs entre x 0,78-1,30 et
     y 0,04-0,40, libre à plus de 1 cm (caméra du dosage comprise). `bocal_0_0` reste posé à la main ; `bocal_0_1`,
     `bocal_1_0`, `bocal_2_0` et `bocal_2_1` sont posés par la machine. Refaire `exceptions_butee_haute` en
     conséquence (le chemin spécial de `bocal_0_1` n'est plus utile s'il ne passe plus par le rectangle interdit).
  3. Le Portique (`portique/logiciel/bras-traine.md`, corrigé) donne le bas du godet en butée haute vers 1,087 :
     vérifier contre le chiffre du dépôt et corriger si besoin.
  Procédure d'essai sur le vrai matériel ; « testé sur le vrai matériel : non ».
- [x] **45 undecies. Lâcher de la ventouse par « souffler » (2 électrovannes)** — Modèle : Opus, effort moyen.
  Réponses des fils du 07/11/2026 (à recopier dans `docs/decisions.md`, en corrigeant le point 2 de « Entonnoir,
  réponses à la PR n° 88 », qui est faux) :
  1. **Deux électrovannes** (fil Préhension, fiche achats/modules/prehension.json, étape 9) : `ev_aspirer` envoie l'air
     au venturi, `ev_souffler` remet la ventouse à l'air avec un peu d'air ; 2/2 24 V normalement fermées, plus un
     clapet anti-retour. Fermer « aspirer » ne lâche **rien** (le clapet garde le vide). **Lâcher = ouvrir
     `ev_souffler` ≈ 0,2 à 0,5 s, puis attendre que le vide remonte au-dessus de −5 kPa.** Vaut pour tous les lâchers
     de la ventouse (entonnoir, couvercle, seau, Pétri, et ce que d'autres modules prennent à la ventouse) : les
     trouver tous et les corriger.
  2. **Câblage** (Implantation, `implantation/logiciel/sorties-carte-4.md` dans `/mnt/project-files/`, lire ce seul
     fichier) : carte FluidNC n° 4, `ev_aspirer` (ex-`vanne_vide`) = sortie P0, `ev_souffler` = sortie P1 (M62/M64/M65
     P0 et P1), sorties auxiliaires 24 V n° 1 et 2, sur le 24 V coupé (fermées à l'arrêt d'urgence). P2 réservée au
     frein du Z de la préhension, P3 libre. Les numéros de GPIO viendront de la configuration de la carte achetée ;
     P0 et P1 ne changent pas.
  3. **Le logiciel empêche les deux vannes d'être ouvertes en même temps** (refus clair, vérifié aussi dans les tests).
  4. Le nom `vanne_souffler` attendu par la tâche 45 decies (fermeture au démarrage) devient la vraie vanne.
  Procédure d'essai sur le vrai matériel ; « testé sur le vrai matériel : non ».
- [x] **45 duodecies. Sorties des cartes n° 3 et n° 4, chauffage du lavage par un relais du Pi** — Modèle : Sonnet,
  effort moyen. Fiches de l'Implantation du 07/11/2026 (dans `/mnt/project-files/implantation/logiciel/`, lire ces
  seuls fichiers : `sorties-carte-3.md`, `sorties-carte-4.md`) ; à recopier dans `docs/decisions.md` :
  1. **Carte n° 4** : P0 `vanne_vide` (ev_aspirer), P1 `vanne_souffler`, P2 frein du Z de la préhension, P3 libre,
     **P4 électroaimants des capsules** (3 en parallèle, 24 V coupé). Le jet d'air du col et le chauffage ne sont
     **pas** sur cette carte (la tâche 45 undecies les y avait mis en P5 et P6 : les enlever).
  2. **Carte n° 3** (lavage) : P0 et P1 pont en H du demi-tour (**jamais les deux ensemble**, refus clair comme pour
     les deux vannes de la ventouse), P2 relais de la pompe de vidange, P3 électrovanne d'eau, P4 vanne à bille,
     P5 jet d'air du col. Vérifier ce que le dépôt a déjà pour cette carte et l'aligner.
  3. **Chauffage du lavage** (thermoplongeur 2 kW) : pas sur FluidNC ; commandé par le Pi par un relais qui pilote le
     SSR. Voie du relais du Pi en EXEMPLE (fiche future `relais-du-pi.md`). La sécurité est câblée : `relais_flotteur`
     (flotteur du fût de lavage) est en série dans la commande du SSR ; son 2ᵉ contact recopie le flotteur sur une
     entrée de la carte n° 3. Le logiciel n'allume le chauffage que si « flotteur haut » et « pompe arrêtée », sinon il
     attend et informe (jamais une protection logicielle présentée comme une sécurité).
  Vérifié au démarrage (sorties en double, sortie absente) ; procédure d'essai sur le vrai matériel ; « testé sur le
  vrai matériel : non ».
- [x] **45 tredecies. Relais du Pi et voyant-buzzer sur son propre relais** — Modèle : Sonnet, effort bas. Fiches de
  l'Implantation du 07/11/2026 (`/mnt/project-files/implantation/logiciel/relais-du-pi.md`, `sorties-carte-3.md`,
  `sorties-carte-4.md` ; lire ces seuls fichiers) ; à recopier dans `docs/decisions.md` :
  1. **Validé par l'Implantation** : carte n° 3 P6 verrou du plateau, P7 vanne 3 voies des rampes (carte n° 3 pleine,
     8/8) ; carte n° 4 P3 rinçage du lavage (P5 à P7 libres, P2 frein) ; modules de sorties 24 V à 4 voies dans les
     emplacements d'axe libres, rien à acheter ; chauffage `relais_2` K8 (24 V → K8 → contact de `relais_flotteur` →
     entrée du SSR). Les cartes à 8 relais sont en I2C PCF8574 aux adresses 0x20 et 0x21. Les numéros de GPIO des
     cartes FluidNC restent EXEMPLE jusqu'à la réception des cartes.
  2. **`voyant_buzzer` n'est pas sur `relais_1` K1** : il a son propre module relais à 1 voie (`relais_buzzer`), sur un
     GPIO direct du Pi, en 24 V **non coupé** (l'alarme sonne même si l'I2C ou une carte à relais tombe en panne ;
     choix du 26/10). Choisir le GPIO parmi les broches libres du dépôt, jamais 2, 3, 8, 9, 14, 15, 18, 19 ; il reste
     EXEMPLE tant que l'Implantation ne l'a pas écrit dans sa fiche. `relais_1` K1 redevient libre.
  3. Vérifier au démarrage qu'aucune voie de relais ni aucun GPIO n'est pris deux fois (existe peut-être déjà).
  Procédure d'essai sur le vrai matériel ; « testé sur le vrai matériel : non ».
- [x] **23. Solveur d'ordonnancement (OR-Tools) et vérification d'un programme avant envoi** — Modèle : Opus, effort
  moyen. Base : `pi/vidange/simulateur/solveur.py` (place prête), `simulateur/planning.py`, `chef/zones.py`,
  decisions « La fiabilité d'abord ». Bibliothèque : `ortools` (CP-SAT, gratuite, roues pour le Pi 5 en
  Python 3.11), ajoutée à `pi/pyproject.toml`.
  1. `ordonner(taches)` : une variable intervalle par tâche, « pas de chevauchement » par zone, « après » par
     module, temps total le plus court. Une tâche `demande_go` est un point d'arrêt : le solveur n'ordonne que ce
     qui vient avant le prochain Go (il ne décide jamais à la place de Karulium). Temps de calcul limité par un
     réglage (`solveur → temps_max_s`, EXEMPLE) ; pas de solution dans ce temps = on garde l'ordre normal du chef.
  2. Vérification avant envoi : le simulateur rejoue le programme trouvé ; la moindre zone tenue deux fois, règle
     refusée ou alerte = programme rejeté, ordre normal du chef, et le journal dit pourquoi.
  3. Jeu par le Pi : le programme ne change **que l'ordre de priorité** quand plusieurs modules attendent la même
     zone ; toutes les conditions, zones et refus du chef restent vérifiés comme avant (le programme ne peut rien
     autoriser de plus). Réglage `solveur → actif` (faux par défaut) ; recul automatique à l'ordre normal à la
     première alerte ou au premier écart de temps au-delà d'un seuil (EXEMPLE), noté au journal.
  4. Le gain (temps total avec et sans programme, sur un lot simulé de 18 seaux) est affiché par
     `vidange --simuler` ou équivalent, pour que Karulium voie si ça vaut la peine.
  Hors de la tâche : le versement de la griffe dans un bocal (case vide `verser(bocal)` de l'Entonnoir, fiche
  demandée à la Griffe) et la montée en vitesse (tâche 30).

## Partie 3 : fonctions en plus, voir `docs/fonctionnalites.md`

- [x] 24. Dérive de position : consigne contre pilotes boucle fermée (15). — Sonnet.
  Ce que la machine a vraiment (decisions.md, réponse Implantation du 30/10) : les pilotes boucle fermée n'ont que
  PUL, DIR, ENA et une sortie d'alarme **ALM** ; le Pi ne lit jamais la position du codeur. Le pilote rattrape
  seul ses pas ; s'il n'y arrive pas (erreur de suivi au-delà de son réglage, fait sur le pilote), il lève ALM.
  Les ALM arrivent dans « Pn: » de leur carte FluidNC (entrées `alarme_*` de `docs/entrees-sorties.yaml`).
  1. **Un seul endroit pour les alarmes des pilotes** : la liste « axe → son entrée `alarme_*` » se lit dans les
     réglages (aucun nom d'axe ni broche dans le code). Vérifiée au démarrage : un axe moteur boucle fermée de
     `fluidnc/*.yaml` sans entrée d'alarme, ou une entrée `alarme_*` qui ne correspond à aucun axe = erreur claire.
     Chaque geste qui fait bouger un axe s'arrête (arrêt de la carte, comme le portique aujourd'hui) et alerte
     avec un « quoi faire » si l'ALM d'un de ses axes se lève. Reprendre ce qui existe (portique, barres du
     remplissage) sans réécrire ce qui marche ; brancher les axes qui ne sont pas encore surveillés.
  2. **« Le moteur cale » de la tête** (bocal neuf, dévissage) : `erreur_codeur` est remplacé par l'ALM de la
     rotation de la tête (`alarme_rotation_tete`) ; le seuil (≈ 2° pendant 0,2 s) est un réglage du pilote, écrit
     dans la procédure d'essai, pas dans le code. Le geste ne refuse plus de partir sur la vraie machine pour cette
     raison (les autres raisons restent). Comment l'ALM se remet à zéro (coupure de ENA ? remise sous tension ?)
     dépend du pilote : à écrire comme EXEMPLE dans les réglages et en question.
  3. **Dérive après le moteur** (courroie ou pignon qui glisse : le codeur ne la voit pas) : contrôle d'origine
     d'un axe à des moments réglés (EXEMPLE : début de lot, tous les N seaux), qui mesure l'écart entre la position
     que croit FluidNC et son fin de course d'origine, puis le remet à jour. Écart au-delà d'un seuil (EXEMPLE) =
     alerte « dérive » au journal et sur la page ; au-delà d'un 2ᵉ seuil = arrêt propre. Choisir la façon de mesurer
     qui marche avec FluidNC tel qu'il est câblé (fins de course d'origine sur les cartes) ; si la seule bonne façon
     demande un changement de câblage ou de configuration FluidNC, la coder derrière `actif: faux` et poser la
     question avec ta recommandation. Le simulateur (faux FluidNC) sait glisser d'un nombre de mm donné, pour les
     tests.
  Hors de la tâche : la lecture des positions par la vision, la montée en vitesse (30).
- [x] 24 bis. Alarmes des pilotes regroupées par carte (réponse de l'Implantation du 09/11,
  `implantation/logiciel/alarmes-pilotes.md`, recopiée dans decisions.md). — Sonnet.
  1. **Une seule entrée « alarme » par carte FluidNC** : les ALM de tous les pilotes de la carte sont regroupés
     (en série si la sortie ALM est ouverte en alarme, sécurité positive à préférer ; en parallèle sinon : à
     vérifier à réception, donc le sens de l'entrée est un réglage). Dans `docs/entrees-sorties.yaml`, les entrées
     `alarme_*` par axe sont remplacées par `alarme_carte1` (fluidnc_portique : X1, X2, Y, Z griffe, rotation A et
     godet B de la griffe, 6 pilotes), `alarme_carte2` (fluidnc_chariot : avance, plateau Z, plateau A, pousseur,
     les 2 barres, 6 pilotes), `alarme_carte3` (fluidnc_mycelium_lavage : HBS86H de la manivelle ; les TMC2209
     n'ont pas d'ALM) et `alarme_carte4` (fluidnc_prehension : Z et rotation de la préhension, noyau, couronne,
     4 pilotes). Numéro d'entrée choisi par toi parmi les entrées libres de chaque carte (EXEMPLE).
  2. Section `pilotes` de `machine.yaml` : une alarme peut être partagée par tous les axes de sa carte (vérifié au
     démarrage : une alarme partagée par des axes de cartes différentes = erreur). La griffe sort de `sans_alarme`.
     Une ALM de carte arrête tous les modules qui ont un axe de cette carte en mouvement, et le « quoi faire » dit
     qu'on ne sait pas quel pilote : regarder les LED des pilotes de la carte. Les barres du remplissage gardent
     leur geste (arrêt du centrage) mais lisent `alarme_carte2`.
  3. Calage voulu de la rotation de la tête : pendant le pas `cale`, l'ALM de la carte 4 est attendue ; elle masque
     les 3 autres pilotes de la carte pendant ce pas (écrit dans decisions.md). Remise à zéro : `$MD` puis `$ME`
     d'abord (ENA est bien sur la sortie « disable »), puis, en 2ᵉ essai si l'ALM ne retombe pas, coupure 2 s du
     48 V du seul pilote de rotation de la préhension par `relais_1` K3 (relais à contact repos, réservé dans
     `relais-du-pi.md`), derrière un réglage (EXEMPLE, désactivé tant que l'essai n'est pas fait). Jamais couper K1
     (tous les moteurs). La procédure d'essai dit aussi d'essayer d'abord d'éviter l'alarme (seuil d'erreur du pilote
     ou courant limité pendant le vissage).
  Hors de la tâche : retrouver quel pilote est en alarme en comparant positions demandée et lue.

- [x] 25. Comptes (58) et restauration d'un Pi neuf depuis la sauvegarde (79). — Sonnet.
  Fait : comptes de la page web (3 rôles, `vidange compte`, journal des actions), archive quotidienne des fichiers
  hors Git, `restaurer.sh` et `vidange restaurer`. Choix et reste à faire : `docs/decisions.md`, « Comptes et
  restauration, tâche 25 ». Essais : `pi/systeme/essai-comptes.md`, `pi/systeme/essai-restauration.md`.
- [x] 26. Entretien : compteurs par axe, calendrier, pièces d'usure, page maintenance (40 à 44). — Sonnet.
  Fait : compteurs par axe (distance, mouvements, heures de marche) et par sortie tout-ou-rien (manœuvres), écrits
  par groupes sur le disque, pièces d'usure et calendrier (`pi/reglages/entretien.yaml`, toutes les limites sont des
  EXEMPLES), alerte « bientôt » / « à faire » (check-list et journal, jamais bloquante), onglet « Maintenance » de la
  page web avec le bouton « Fait ». La santé de l'informatique (45) existait déjà (`fiabilite/sante.py`, tâche 7).
  Choix et reste à faire : `docs/decisions.md`, « Entretien, tâche 26 ». Essai : `pi/systeme/essai-entretien.md`.
- [x] 27. Notifications sur le téléphone (ntfy), résumé du soir, escalade (60 à 63). — Sonnet.
  Fait : ntfy et Telegram (option) par la file d'envoi existante (sans réseau : les messages attendent), niveau par
  sorte d'alarme dans `programme.yaml`, heures calmes, fin de fût, nettoyage à faire, pièces d'usure « à faire »,
  résumé du soir, escalade (rappel puis 2ᵉ liste) et bouton « J'ai vu » sur la page. Choix et reste à faire :
  `docs/decisions.md`, « Notifications, tâche 27 ». Essai : `pi/systeme/essai-notifications.md`.
- [x] 28. Page web : vue 3D en direct et rejeu d'incident (54, 55). — Sonnet.
  Coupée en deux le 09/11 (trop grosse pour une session) : le reste est la 28 bis.
  1. Vue 3D en direct : boîtes simples (portique, pont, chariot, griffe, tête de préhension, chariot du
     remplissage, zones des modules) dessinées depuis les réglages (`machine.yaml`, `fluidnc/*.yaml`), jamais
     depuis des chiffres dans le code ; positions des axes lues comme la page les lit déjà (rapport d'état des
     cartes), rafraîchies plusieurs fois par seconde ; zones tenues en couleur. Le Pi tourne sans Internet : la
     bibliothèque 3D (par exemple three.js, licence MIT) est copiée dans le dépôt à une version fixe, pas chargée
     d'un site.
  2. Rejeu d'incident : pour une alarme du registre, rejouer en 3D les positions des 60 s avant et après (le
     « bilan après alarme », fonction 17) avec lecture, pause et curseur. Si ces positions ne sont pas encore
     gardées, les garder (fichier par alarme, taille bornée par un réglage, purge des plus vieux).
  Rôle « regarder » pour les deux (tâche 25).
  Fait : onglet « Vue 3D » (boîtes et zones dessinées depuis `vue3d.yaml` et `machine.yaml`, positions lues 5 fois
  par seconde, zones tenues en orange), three.js 0.160.0 copiée dans le dépôt, rejeu des 60 s avant et après chaque
  alarme (fichier par alarme dans `donnees/rejeux`, taille bornée, purge des plus vieux), bouton « Rejouer en 3D ».
  Choix et reste à faire : `docs/decisions.md`, « Vue 3D et rejeu, tâche 28 ». Essai : `pi/systeme/essai-vue-3d.md`.
- [ ] 28 bis. Page web : statistiques (57), appli installable (59), réglages avec garde-fous (56), carnet de
  bord (86). — Sonnet.
- [ ] 29. Écran : code pour les fonctions sensibles (50). — Sonnet.
- [ ] 30. Estimation de fin qui apprend (7), montée en vitesse réglable (69), essai d'un réglage dans le simulateur (68). — Sonnet.
- [ ] 31. Plans d'expériences : application d'un plan d'essais accepté par Karulium, seau par seau (6, 76). — Opus.
- [ ] 32. Mode guidé pour un employé et manuel tenu à jour (84, 85). — Sonnet.
- [ ] 33. Assistant en français, écoute des bruits, résumé de la semaine (71, 73, 74). — plus tard.

## Partie 4 : les autres modules, au fil des gels

Avant chaque tâche, le projet recopie ici les gestes, positions et règles du module. Les modules de cette partie
passent **avant le solveur (tâche 23)**, qui a besoin des gestes de tous les modules.

- [x] **34. Remplissage : le chariot des seaux (avance, plateau, rotation, barres, pousseur, balance)** — Modèle :
  Opus, effort moyen. **Fait avant le solveur (tâche 23)**, qui a besoin des gestes de tous les modules.
  Sources (recopiées ici le 30/10/2026) : fiche du module « Remplissage », **gelé le 27/10/2026**, fichier des positions
  interdites du chariot (`remplissage/fiche/regles-positions.md`, v3.44 à 3.46, règles 1 à 11), plan de commande v223.
  Les chiffres vont dans `pi/reglages/machine.yaml`, `docs/entrees-sorties.yaml` et `fluidnc/`, jamais dans le code.

  *Ce que fait le module.* Le chariot de remplissage roule en y entre le poste (sous la griffe) et le stockage. Il porte
  un plateau qui monte, descend et tourne, deux barres séparatrices qui tiennent ou centrent le seau, un pousseur qui
  range le seau plein sur sa file, et une balance. Il sert aussi au Mycélium (dosage), au Lavage (retourneur des
  couvercles) et à l'inspection des bocaux. Les modules déjà écrits l'appellent par des interfaces avec un faux
  (`ChariotRemplissage` du Mycélium, `Retourneur` du lavage des couvercles, verrous de la Préhension) : cette tâche
  écrit le vrai et garde les faux pour les tests.

  *Moteurs et capteurs* (carte 2 ; à ajouter, marqués `exemple: true` tant que le plan de câblage n'est pas arrivé) :
  - Avance (y), montée du plateau (avec frein, maintien réduit), rotation du plateau (axe rotatif FluidNC, rapport 40,
    8 000 pas par tour), pousseur (course 0,32, de −0,16 à +0,16), barres (vis T8 au pas de 8, ouverture complète
    ≈ 2,3 s). Le vérin du galet (fermeture) est sur cette carte mais appartient à la tâche 41.
  - Fins de course, dont le **fin de course haut** du plateau (coupe la montée vers 0,578) et l'**origine des barres**
    côté mur, actionnée par la plaque de barre à un écartement hw ≈ 0,309 (décalage réglé dans le Pi).
  - **Barrière lumineuse** sur la barre côté mur, à 0,7315 (entrée de la carte 2).
  - **Balance** 30 kg du plateau : lue par sa carte RS485 (`pesee_plateau_remplissage`, tâche 22 bis).

  *Positions* (repère du portique) : poste y 0,135 (la griffe verse) ; dosage du mycélium y 0,155 ; recul pendant le
  passage de l'agitateur y ≥ 0,375 ; pose du seau vide et du couvercle y 0,50 ; files de rangement : réglages (les places
  exactes viennent du Stockage, tâche 35 ; en lot C, arrêt à y 0,205 pour la bande du haut côté paroi). Plateau : course
  0,175 à **0,575 au plus, toujours** (règle 9, butée logicielle). Barres : écartement hw de 0,1195 à 0,305 (axe d'une
  barre à l'axe du plateau).

  *Règles de position* (verrous du logiciel : ils protègent la machine, pas les personnes) :
  1. Anneaux du fût : en y 0,14-0,41 et 0,59-0,86, plateau en bas (dessus ≤ 0,18) ; libre au poste et entre 0,41 et 0,59.
     Le plateau descend avant de quitter le poste et ne remonte qu'au poste. Les files 0,215 et 0,785 se font plateau en bas.
  2. Barres entre 0,235 et 0,255 (joues de l'élévateur) : seulement plateau ≤ 0,48.
  3. Plateau au-dessus de 0,515 : barres **ouvertes** seulement (hw ≥ 0,29). (Prise d'un seau B à 0,5125, barres à
     0,1195 : permise.)
  4. Pousseur : **rentré** dès que le plateau n'est pas en bas, et toujours rentré au-dessus de 0,20.
  5. Bras du galet (fermeture) : ne tourne que plateau ≤ 0,26 ; rangé il ne gêne rien (règle de la tâche 41, à vérifier
     ici comme verrou : plateau qui monte au-dessus de 0,26 seulement bras rangé).
  6. Spray : pendant le pivot du bras et la pulvérisation, plateau ≤ min(0,50 ; 0,71 − h) ; le bras ne bouge que barres
     ouvertes à plus de 0,50 d'entraxe (fonction de verrou pour la tâche 39).
  7. Chariot du fût pas « en place » : le chariot reste au poste ou aux files 1 et 2 (bout à y ≤ 0,875).
  8. Mycélium (déjà écrit côté Mycélium, à brancher ici) : le chariot ne roule vers le poste ou depuis le poste que si
     l'agitateur est au garage manivelle en haut, ou au dosage manivelle en bas ; ordre pour un seau : poste → recul
     y 0,375 → agitateur au dosage → poste… (fichier des positions, règle 11).
  9. Préhension : elle ne descend sous ≈ 0,84 au-dessus du chariot que barres ouvertes et tête du micropore rentrée
     (fonction à fournir à la Préhension).

  *Gestes* :
  - **Poser un seau vide** (avec la Préhension) : chariot à y 0,50, plateau monté ; la Préhension pose le seau ; la balance
    vérifie qu'il n'y en a **qu'un**. **Prise double** (faisceau de la barrière coupé après la pose) : la tête remonte de
    2 cm ; lâcher (barres + 1,5 cm chacune) ; la tête redescend de 4,8 cm ; barres serrées dans la rainure sous la jupe
    du seau du dessus (entraxe = Ø haut + 6 mm) ; le plateau monte toucher le fond du seau du dessous ; la tête remonte
    (≈ 2 cm de tirage) ; lâcher ; le plateau remonte de 2,8 cm. Contrôle : faisceau libre ET un seul seau sur la balance,
    sinon alarme. Efforts : séparation au plus 35 N par barre (capteur de force de la tête, sinon arrêt) ; centrage au
    courant réduit (≈ 30 N par barre).
  - **Ramener au poste** : plateau en bas, retour en y 0,135, plateau remonté.
  - **Orienter l'anse** : avant de serrer les barres, le plateau tourne le seau pour mettre les oreilles de l'anse à
    **45° (modulo 90°)** des barres, donc des files ; l'angle vient du QR du flanc (vision, tâche 22), corrigé par l'écart
    attaches/QR enregistré pour ce seau. Cet angle est gardé jusqu'à la poussée.
  - **Centrer** : barres au contact du corps sous le rebord, courant réduit.
  - **Tourner pendant le versement** de la griffe ; **arrêts pour le dosage** (plateau à min(0,78 − h ; 0,575), barres
    ouvertes, pousseur rentré).
  - **Ranger** : le plateau s'arrête à l'angle de l'anse, puis le pousseur pousse le seau sur sa file (bande du haut :
    plateau à 0,4985, plage 0,496-0,501 ; files du bas : plateau en bas). Le registre reçoit QR, poids, doses, variété
    et photo.
  - **Mode couvercles** (retourneur, tâche 21 bis) : chariot y 0,50, plateau fixe à 0,459, sans rotation ; barres
    0,19 ↔ 0,30 ; barrière surveillée en continu (coupée = pause avec message). Remplacer le faux `Retourneur`.
  - **Mode inspection des bocaux** : plateau fixe à 0,575, barres ouvertes, rotation libre par arrêts de 45° (la pose
    du bocal par la Préhension est vue par sa force et par la balance, qui doivent être d'accord).

  *Ce qui n'est pas dans cette tâche* : le bras du spray (39), la pose du micropore et son capteur VL6180X (40), le galet
  de fermeture (41), les places exactes des files (Stockage, 35), la lecture du QR (vision, tâche 22 : ici, on appelle
  sa fonction).

  Simulateur : un scénario `remplissage` : seau vide posé, prise double séparée, anse orientée, versements, dosage avec
  l'agitateur, rangement. Tests de chaque règle de position, prise double qui échoue (deux seaux sur la balance),
  barrière coupée, chariot du fût absent, ordre avec l'agitateur. Outil d'essai et procédure sur le vrai matériel.
- [x] **34 bis. Remplissage : corrections après la tâche 34** — Modèle : Opus, effort moyen. Même branche de travail
  que d'habitude (une PR). Tout vient des réponses à la PR n° 43, déjà dans `docs/decisions.md` (section
  « Remplissage », points 1 à 11) : les lire d'abord. Trois erreurs venaient des règles recopiées ici, pas du code.
  Les chiffres restent dans les réglages, marqués `exemple: true`.
  1. **Pousseur** : « rentré » = zéro au fin de course côté fût (`pousseur_rentre_m` à 0, plus « au milieu ») ; il
     pousse toujours vers le stockage, course 0,325. Rentré dès que le plateau n'est pas en bas, et il ne sort que
     plateau ≤ 0,20, partout (tête du micropore montée sur le chariot). Retirer la bande du haut (0,4985) et le
     « lot C y 0,205 » des réglages et des gestes ; le rangement se fait plateau en bas.
  2. **Capteurs d'origine** (à ajouter dans `docs/entrees-sorties.yaml` et `fluidnc/chariot.yaml`) : fin de course
     BAS de la montée = zéro de la montée (prise d'origine vers le bas, plateau en bas à 0,175) ; le fin de course
     haut reste une butée de sécurité (coupe vers 0,578) ; fin de course de l'avance (contre le tampon côté mur) ;
     fin de course du pousseur (côté fût) ; capteur Hall du zéro de rotation (un aimant par tour). Retirer
     l'avertissement « la prise d'origine fait monter le plateau ».
  3. **Rotation** : sans réducteur, pignon 15 dents sur roue 120, **rapport 8** (et non 40). Moteurs : avance,
     rotation et barres = NEMA 17 boucle fermée ; montée et pousseur = NEMA 23 boucle fermée à frein ; pilotes
     boucle fermée (PUL, DIR, ENA, sortie ALM). Pas par tour du pilote : exemple.
  4. **Centrage en position**, sans courant réduit : barres à `centrage_hw_m` du format + un petit jeu (réglage).
     Retirer la sortie « courant réduit » (le pilote n'en a pas). L'alarme ALM du pilote des barres arrête le geste
     et alerte (comme les autres alarmes de pilote).
  5. **Prise double** : refaire le geste dans l'ordre a) à h) du point 5 des décisions (le plateau ne bouge pas avant
     e). Courses en réglages. Mettre à jour le scénario du simulateur et la procédure d'essai.
  6. **Règle 7** : bout du chariot côté allée à 0,40 de l'axe (réglage) ; chariot du fût absent ⇒ axe à y ≤ 0,475.
  7. **Règle 9 dans la préhension** : sa descente sous ≈ 0,84 au-dessus du chariot est refusée si les barres ne sont
     pas ouvertes ou si la tête du micropore n'est pas rentrée, **sauf en mode couvercles** (retourneur, exception
     vérifiée par le Lavage le 25/10).
  Tests : chacun des 7 points (dont prise double dans le nouvel ordre, poussée refusée plateau > 0,20, file refusée
  au-delà de 0,475 sans chariot du fût, prise d'origine vers le bas, ALM des barres pendant le centrage, préhension
  refusée barres fermées hors mode couvercles). « Testé sur le vrai matériel : non ».
- [x] **34 ter. Remplissage : ordre de la pose et de la prise double** — Modèle : Sonnet, effort moyen. Refaire la
  pose d'un seau vide et la prise double dans l'ordre du point 5 de la section « Remplissage » de `docs/decisions.md`
  (corrigé le 30/10 au soir ; il remplace l'ordre a) à h) de la tâche 34 bis) : barres à l'approche (hw 0,225)
  plateau ≤ 0,48 AVANT la pose, plateau qui monte jusqu'au contact lu par la balance, centrage, puis prise double
  a) à i) (le plateau descend de 5 cm en b ; plus de montée de 2 cm de la tête). Courses en réglages (`exemple: true`).
  Les barres ne se rouvrent au-delà de 0,235 qu'après la descente du plateau ≤ 0,48. Mettre à jour le scénario du
  simulateur et la procédure d'essai. Tests : l'ordre exact de la pose et de a) à i), prise double d'un seau B
  réussie (plus d'alarme), hw toujours sous 0,235 pendant la prise double, contact lu par la balance.
- [x] **34 quater. Remplissage : deux moteurs de barres, agitateur à 0,40, fin de course haut câblé** — Modèle :
  Sonnet, effort moyen. D'après la section « Remplissage, changements du 31/10/2026 » de `docs/decisions.md`.
  1. Barres : un axe de plus sur la carte 2 (barre côté mur, barre côté allée), chacun avec son pilote boucle fermée
     (ALM) et son fin de course d'origine (décalages hw ≈ 0,309 et ≈ 0,306 dans les réglages). Les gestes commandent
     toujours les 2 ensemble (mêmes pas, sens inversé) ; le Pi refuse un écart entre les 2 barres plus grand qu'un
     réglage (exemple 1 mm). Règles 2, 3, 4 et 8 et alarmes ALM vérifiées pour chaque barre. Mettre à jour
     `fluidnc/chariot.yaml`, `docs/entrees-sorties.yaml` (`exemple: true`) et `pi/reglages/fluidnc.yaml`.
  2. Passage de l'agitateur : y ≥ 0,40 au lieu de 0,375, partout où c'est réglé (Mycélium et Remplissage) ; tests.
  3. Fin de course haut de la montée : retiré des entrées de la carte (il est en série dans l'arrêt) ; la butée
     logicielle 0,575 reste. Câbles capteurs : noter la répartition dans `docs/entrees-sorties.yaml`.
  Tests : 2 barres qui bougent ensemble, écart refusé, ALM d'une seule barre, agitateur refusé à y 0,39, permis à
  0,40. Procédure d'essai mise à jour ; « testé sur le vrai matériel : non ».
- [x] **35. Stockage : places, inventaire, prise sur les piles, rangement dans le tiroir** — Modèle : Opus, effort
  moyen. **Avant le solveur (tâche 23).**
  Sources (recopiées ici le 31/10/2026) : fiche du module « Stockage », **gelé le 27/10/2026**, et le fichier écrit
  pour le logiciel par le fil Stockage (`stockage/logiciel/stockage-pour-logiciel.md`, 31/10, repère du portique).
  Les chiffres vont dans `pi/reglages/machine.yaml` (section `stockage`) et `docs/entrees-sorties.yaml`, jamais
  dans le code ; le Pi **calcule** les places à partir de ces réglages (formules ci-dessous), vérifiées au démarrage.

  *Ce que fait le module.* Le Stockage est **passif** : aucun moteur, aucun vérin commandé (les 4 vérins à gaz des
  panneaux sont passifs). En haut, un plateau en tôle (dessus **0,496**, 2 panneaux relevables P1 x 1,155-1,870 et
  P2 x 1,880-2,595) porte les piles de seaux vides, ou les bocaux (avec un tapis silicone de 1 mm, bocal posé à
  0,497), les 2 boîtes à capsules et le hublot de la caméra du fond. En bas, un tiroir à 3 files reçoit les seaux
  pleins poussés par le chariot de remplissage. **Aucun capteur de présence** : le Pi tient l'**inventaire** de
  chaque place (registre), les caméras vérifient. Cette tâche écrit les places, l'inventaire, les règles de trajet
  au-dessus du Stockage et les gestes qui appellent la Préhension et le Remplissage (déjà écrits).

  *Entrée* (à ajouter, `exemple: true`) : **une seule** entrée de boucle de 3 microrupteurs NF en série, fermée si
  le tiroir est rentré ET verrouillé, ET P1 fermé, ET P2 fermé. Boucle ouverte ⇒ **aucun mouvement** du portique ni
  du chariot (le Pi attend et le dit à l'écran ; il ne sait pas lequel des trois est ouvert). Elle informe et fait
  attendre : ce n'est pas la sécurité des personnes (portes et arrêt d'urgence restent câblés).

  *Piles de seaux vides* (mode seaux, sans tapis) :
  - Places, centres (x ; y) : (1,30 ; 0,84), (1,61 ; 0,84), (1,96 ; 0,53), (1,96 ; 0,84), (2,27 ; 0,53), plus 4 à 5
    places de fin de lot sur la bande y 0,215, x choisis par le Pi : 1 cm entre piles, ≥ 10 cm de la caméra du fond.
    **Un format par pile.** Couvercles des seaux : une pile en (2,27-2,29 ; 0,84).
  - Seaux par pile : n = min(⌊(0,39 − h)/pas⌋ + 1 ; ⌊(0,645 − 2h)/pas⌋ + 1). Contrôle : A 5, B 7, C 5, D 3 (pas :
    A 30 mm, B 30, C 35, D 45, dans la table des formats). Bord du seau du haut d'une pile de k seaux =
    0,496 + h + (k − 1) × pas.
  - Prendre le seau du haut (Préhension) : cote attendue du bord ci-dessus, k tenu à jour par le Pi (l'écart de
    5 mm de la Préhension s'applique). Le seau **se sépare seul** de la pile (essais de Karulium) : pas de geste
    spécial. Anse rabattue côté y+. Ordre de vidage : rangée y 0,84, puis 0,53, puis 0,215 ; dans une rangée, la
    pile la plus proche du chariot d'abord ; sortie vers −x.

  *Seaux pleins : le tiroir* (tôle à **0,176**, au plus 5 mm sous le plateau du chariot en bas) :
  - Files sur l'axe y **0,215 / 0,500 / 0,785** ; entrée x 1,10, butée de fond x **2,612** ; poussés vers +x par le
    pousseur du chariot (règles du Remplissage : plateau en bas, pousseur ≤ 0,20 ; file 0,785 seulement chariot du
    fût en place). Avance d'environ 0,272 par seau (poussée au moins 0,18) ; le premier seau ne dépasse jamais la
    butée. Effort 150 à 240 N pour une file de 6 (réglage, à l'essai).
  - **5 seaux par file**, sauf la file y 0,215 avec A, B et D : **4** (dernière place vide sous la caméra du fond).
    Seau C : files en quinconce avec une cale de 15 cm, **16 par lot**. Capacité du tiroir : **14 (A, B, D) ou 16 (C)**.
  - **Bande du haut (seaux pleins sur le plateau du haut, y 0,215) : case vide.** Karulium veut les y pousser avec le
    pousseur du chariot (31/10), mais la tête du micropore, montée sur le chariot, gêne au-dessus de 0,40 ; le projet
    de la mécanique cherche la solution. Ici : prévoir ces places dans l'inventaire (désactivées par un réglage), sans
    geste. Elles viendront dans une tâche à part, avec leurs règles.
  - Rangement seulement boucle fermée (tiroir rentré et verrouillé). Oreilles de l'anse à 45° des files.
  - **Plus aucune place libre** avant la fin du fût : le Pi met le cycle en **pause** (substrat restant noté), invite à
    vider le tiroir, attend la boucle fermée, repart avec les files vides. Fin de lot : pareil, puis lot suivant.
  - Sortie (opérateur) : vider le plateau (bocaux, tapis), relever P1 et P2, déverrouiller et tirer le tiroir
    (0,50), sortir les seaux, tout remettre. Le Pi attend la boucle fermée et remet l'inventaire des files à zéro
    après confirmation à l'écran.

  *Bocaux* (mode bocaux, tapis posé ; avant de relever un panneau : plateau vidé, tapis enlevé) :
  - Quinconce de 95 : 9 rangées j = 0 à 8, y = 0,06 + 0,0953 j ; rangées paires 11 bocaux x = 1,2075 + 0,110 i ;
    impaires 10 bocaux x = 1,2625 + 0,110 i. Bocal posé à 0,497, haut de la capsule à **0,644**.
  - Bocaux de semence : 18 places 3 × 6, x = 1,21 + 0,108 i (i = 0 à 5), y 0,415 / 0,523 / 0,631.
  - Mode inspection (coin du haut) : 9 places « suspects », 6 places vides de séparation (liste exacte dans le fichier
    source, à recopier dans les réglages), 80 saines ; coin plein ⇒ arrêt et alerte.
  - Boîtes à capsules (2,52 ; 0,53) (capsules enlevées) et (2,52 ; 0,80) (couvercles percés) : fond ≈ 0,498, dessus
    0,739 ; hauteur de la pile = 0,498 + 0,013 × nombre de capsules (l'opérateur change la boîte).
  - Hublot de la caméra du fond (2,50 ; 0,22), affleurant : fond du bocal présenté à 0,70-0,73 ; pas de photo si
    l'entonnoir est sur le plateau.

  *Trajets au-dessus du Stockage* (verrous ; vérifier ce qui existe déjà dans la Préhension et la griffe) :
  - Griffe x ≤ **2,325** (butée logicielle).
  - Seau tenu : fond à **0,79 au moins** et jamais au-dessus d'une pile pleine (couloirs libérés par l'ordre de
    vidage) ; à la sortie d'une pile, fond ≥ 3 cm au-dessus de la lèvre restante. Haut du seau ≤ 1,155 axe à
    y ≤ 0,86, ≤ 1,10 au-delà (déjà dans la Préhension) ; ≤ 1,10 aussi tant que l'axe est à y > 0,82 (rail opérateur).
  - Boîtes à capsules : au-dessus de leur emprise (cercle Ø 0,12 agrandi du rayon de l'objet) seulement point le plus
    bas ≥ 0,76, sinon contourner.
  - Caméra du bocal : sortie de la rangée y 0,215 en longeant vers −x axe à x ≥ 1,29, fond ≥ 0,80, puis vers +y jusqu'à
    y ≥ 0,44 ; axe y ≥ 0,44 tant que x < 1,26 ; approches à vide par y ≥ 0,29 + rayon de l'objet (si x < 1,115 +
    rayon) ; entonnoir dans la colonne 1,2075 : axe x ≥ 1,205 si y < 0,38.
  - Boucle ouverte : aucun mouvement.

  *Ce qui n'est pas dans cette tâche* : la photo du fond (vision, tâche 22 ter), le remplissage des bocaux par la
  griffe et l'Entonnoir (43), le choix du travail (solveur, tâche 23). Points encore ouverts (réglages `exemple`) :
  écart tôle du tiroir / plateau pour le seau C (réglé aux pieds) ; sortie des seaux pleins par le store (Nettoyage).

  Simulateur : un scénario `stockage` : 2 piles de A prises dans l'ordre, 14 seaux rangés dans le tiroir (4 + 5 + 5),
  pause « plus de place », boucle ouverte puis refermée, reprise. Tests : nombre par pile pour A à D, cote du bord
  pour chaque k, ordre de vidage, capacité des files (C en quinconce), file 0,785 refusée sans chariot du fût, boucle
  ouverte ⇒ rien ne bouge, coin d'inspection plein, trajets refusés (boîtes, caméra du bocal, pile pleine).
  « Testé sur le vrai matériel : non » ; procédure d'essai (boucle des microrupteurs, cotes des piles, tiroir).
- [x] **35 bis. Bande du haut : seaux pleins poussés sur le plateau du Stockage** — Modèle : Sonnet, effort moyen.
  **Après la tâche 35.** D'après la section « Pousseur côté allée et bande du haut » de `docs/decisions.md` (31/10).
  1. Remplissage : retirer la règle des anneaux du fût (périmée) et « pousseur rentré au-dessus de 0,20 » ; nouvelle
     règle 12 : poussée à toute hauteur, barres ouvertes (hw ≥ 0,29) et bras de fermeture rangé, plusieurs seaux à la
     suite. Garder plateau ≤ 0,575 et l'agitateur immobile tant que le chariot est sous y 0,40.
  2. Stockage : activer les places de la bande du haut (réglages par format, `exemple: true`), avec leur fin de course
     logicielle (bord du couvercle à x ≤ 2,44) ; geste « ranger en haut » dans l'ordre a) à f) ; photo du plafond
     après chaque poussée (y 0,215 ± 0,007, sinon arrêt et alerte ; point d'appel avec un faux tant que la vision ne
     sait pas lire la photo) ; fin de lot tiroir d'abord, piles de fin de lot de la bande vidées en premier ;
     capacité A 18, B 20, C 16, D 18 ; la pause « plus de place » reste pour un fût plus gros.
  4. Corrections après la tâche 35 (section « Stockage, réponses à la PR n° 52 » de `docs/decisions.md`) : butée du
     tiroir à x 2,582 ; seau C à 4 par file (x donnés, cale de 15 cm sur la file y 0,50, course du pousseur −0,15),
     plus de quinconce dans le tiroir ; vraie liste du coin d'inspection ; règle du rail opérateur (haut > 1,11 ⇒ axe
     y + rayon du bord ≤ 0,995, sinon haut ≤ 1,10) à la place de « y > 0,82 » et de l'exception codée pour les piles.
  3. Mode couvercles (règle 14 de `docs/decisions.md`, 31/10) : chariot à y ≥ 0,515 pendant les deux demi-tours de la
     tête de la griffe, retour à y 0,50 seulement après. Test : demi-tour refusé chariot à 0,50.
  Tests : poussée à 0,4985 permise barres ouvertes et bras rangé, refusée sinon ; plateau hors de 0,496-0,501 refusé
  pour la bande du haut ; chariot à y 0,215 plateau haut permis (plus de règle des anneaux) ; places et capacité par
  format ; seau mal aligné à la photo ⇒ arrêt ; scénario du simulateur avec 18 seaux A. « Testé sur le vrai
  matériel : non ».
- [x] **35 ter. Stockage agrandi de 43 cm** — Modèle : Sonnet, effort moyen. **À faire après la tâche 36 bis.**
  Source : `docs/decisions.md`, « Stockage agrandi de 43 cm » (04/11/2026), points 1 à 6. Dans `pi/reglages/machine.yaml`
  (`stockage`) : 3 panneaux (`panneaux → p1, p2, p3`) ; tiroir `butee_x: 3.012`, `places` et `centres_x` de tous les
  formats et de toutes les files (la place sous la caméra du fond reste vide pour A et D sur la file 0,215 : le
  pousseur s'arrête au codeur sur la 2e place) ; cale de C inchangée ; bande du haut `bord_x_max: 2.87` et les places
  des 4 formats ; bocaux `paires: 14`, `impaires: 13` ; coin des suspects ; boîtes ; hublot (2,93 ; 0,22). Dans
  `docs/entrees-sorties.yaml` : la boucle du stockage devient 4 microrupteurs en série (tiroir + P1 + P2 + P3), une
  seule entrée (nom et description). Vérifié au démarrage : capacité A 26, B 28, C 22, D 23 ; aucune place hors
  du tiroir (1,10-3,012) ni de la bande (bord ≤ 2,87) ; coin des suspects dans le quinconce. Tests : reprendre ceux
  du stockage aux nouveaux chiffres, un lot plein de chaque format dans le simulateur. `vidange --verifier` passe.
- [ ] **35 quater. Places du stockage au pas du couvercle** — Modèle : Sonnet, effort bas. **À faire quand le fil
  Stockage aura corrigé `stockage/logiciel/places-agrandi-43.md`** (et après la mesure du couvercle A par Karulium).
  Deux couvercles voisins d'un même format sont à la même hauteur : ils se touchent bord à bord avant les seaux. Le
  pas des places (bande du haut et tiroir) est donc au moins le Ø du couvercle (A 0,28, C 0,315 au lieu de 0,272 et
  0,30). Recopier les nouvelles places dans `machine.yaml`, recalculer la capacité d'un lot (6 A par file du tiroir
  tant que le couvercle A n'est pas mesuré ≤ 0,276), et ajouter au contrôle du démarrage : pas ≥ Ø du couvercle,
  dernier bord de couvercle de la bande du haut ≤ 2,87, centre du seau du fond du tiroir ≤ butée − rayon du corps.
- [x] **36. Portique : axes du pont et des deux Z, prise d'origine, vitesses, garage, carte n° 1** — Modèle : Opus,
  effort moyen. **Avant le solveur (tâche 23).**
  Sources (recopiées ici le 01/11/2026) : fiche du module « Portique », **gelé le 28/10/2026**, et le fichier écrit
  pour le logiciel par le fil Portique (`portique/logiciel/portique-pour-logiciel.md`, 01/11, repère du portique).
  Déjà dans `docs/decisions.md` (ne pas refaire) : rails HGR15, mât de la griffe à pont − 0,187 et de la préhension
  à pont + 0,129 en x, butée logicielle du pont à 2,495. Les chiffres vont dans `pi/reglages/machine.yaml`,
  `docs/entrees-sorties.yaml` et `fluidnc/` (`exemple: true` tant que le câblage n'est pas arrivé), jamais dans le code.
  Les autres modules appellent déjà le portique : vérifier ce qui existe (tâches 3, 13, 37…) et ne compléter que ce
  qui manque ; ne pas réécrire ce qui marche.

  *Axes* (pilotes boucle fermée, même modèle partout, sortie d'alarme) :
  - **Pont X : deux moteurs X1 et X2** (un par rail, NEMA 17 boucle fermée, même consigne), courroie GT2 10 mm,
    poulie 20 dents : 40 mm par tour. Chacun a son fin de course côté fût : à la prise d'origine, chaque moteur
    s'arrête sur le sien (le pont se remet d'équerre). Carte n° 1, 2 sorties.
  - **Chariot Y** : NEMA 17 boucle fermée, GT2 : 40 mm par tour ; fin de course côté paroi (y bas). Carte n° 1.
  - **Z griffe** (carte 1) et **Z préhension** (carte 4) : NEMA 23 boucle fermée à frein 24 V, pignon module 1 de
    16 dents sur crémaillère : 50,27 mm par tour ; fin de course en haut de colonne. Freins à manque de courant
    (24 V coupé par l'arrêt d'urgence) : desserrer avant de bouger, serrer à l'arrêt long.
  - Pas par mm = impulsions par tour du pilote / mm par tour (exemple à 1 600 : X et Y 40, Z 31,83).
  - **Carte n° 1** : 6 axes (X1, X2, Y, Z griffe, A et B de la griffe) : écrire `fluidnc/portique.yaml` (EXEMPLE,
    comme `fluidnc/chariot.yaml`) avec la mise d'équerre (2 moteurs et 2 fins de course sur X).

  *Courses* (butées logicielles) :
  - Pont x **0,233 → 2,495** (0,233 au lieu de 0,223 : 1 cm de marge, plan de commande). Jamais sous 0,233.
  - **Chariot Y : centre de 0,08 à 0,87. Les deux mâts sont à y = centre − 0,040**, donc de 0,04 à **0,83**. Griffe en
    plus : mât ≥ 0,056 godet fermé, ≥ 0,11 godet ouvert (le « 0,884 » de la fiche Griffe ne limite plus rien : la
    course s'arrête à 0,83). Corriger `chariot_y` dans `machine.yaml` (aujourd'hui 0,056-0,884) et tout ce qui
    supposait le mât au centre du chariot.
  - Z griffe : centre de la plaque Z de 2,203 (haut, sur le fin de course) à 1,288 (course 0,915). Z préhension : de
    1,958 à 1,308 (course 0,650). Les hauteurs d'outil (axes de la griffe, face de la préhension) se déduisent avec
    les cotes déjà dans `machine.yaml` : vérifier que tout concorde.
  - Jamais au-dessus de l'origine Z (hauteur sous le pont roulant).

  *Prise d'origine* (ordre) : 1) Z griffe et Z préhension vers le haut (freins desserrés) jusqu'à leur fin de course,
  recul de quelques mm ; 2) Y vers la paroi ; 3) X1 et X2 ensemble vers le fût, chacun sur son fin de course, recul.
  En vitesse d'approche. Les cartes 2 à 4 gardent leurs propres origines.

  *Vitesses* (décidées le 28/10, réglages) : X et Y rapide 250 mm/s, approche 50 mm/s, accélération 1 m/s² à vide,
  **0,5 m/s² seau tenu** ; Z (les deux) 80 mm/s, approche 20 mm/s, 0,5 m/s². Photos à l'arrêt après 0,3 s.

  *Garage et places du pont* :
  - Photo du plafond : le pont au bout **opposé** à la zone photographiée : x 2,495 pour le fût et le poste, x 0,233
    pour le stockage ; les deux outils en haut. (La vision appelle déjà « pont garé » : brancher ces places.)
  - Garage de repos (arrêt, nuit, ozone) : les deux Z en haut, freins serrés, pont à x 2,495, chariot Y au centre
    0,50 (proposition du fil Portique, réglage).

  *Règles propres au portique* (verrous ; elles s'ajoutent à celles des autres modules) :
  - Griffe : pas de rotation de la tête pont au-delà de x 2,0 (le rail de la colonne gêne) ; au bout côté fût, tête
    en orientation bloquée (réglage : angle permis).
  - Préhension au-dessus de z 2,08 (centre de la plaque Z) : chariot à y ≤ 0,93 (plénum du Nettoyage) — vrai sur
    toute la course, à vérifier au démarrage.
  - Stockage, rangée de piles y 0,84 : la préhension prend avec son axe à y 0,83 (1 cm hors d'axe, accepté par le
    fil Stockage) ; le seau tenu garde son axe à 0,84 pour la règle du rail opérateur.

  *Capteurs* (à ajouter, `exemple: true`) : 5 fins de course NF (fil coupé = déclenché) : X1, X2, Y, Z griffe,
  Z préhension ; 5 alarmes de pilote ⇒ arrêt et alerte (laquelle) ; détecteur de chocs sur la colonne de la griffe
  (déjà écrit, tâches 14 et 15 : vérifier son entrée « OK » 24 V vers la carte n° 1 et l'orientation de ses axes : X vertical
  vers le haut, Y le long du pont, Z le long des rails). Les pesées restent à la Griffe et à la Préhension.

  *Ce qui reste ouvert* (réglages `exemple`) : impulsions par tour du pilote acheté ; places exactes des fins de
  course X et Y et butées mécaniques de Y (mesurées à la mise en service) ; seuil du détecteur de chocs.

  Simulateur et tests : prise d'origine dans l'ordre (X1 et X2 qui s'arrêtent chacun sur leur fin de course, pont de
  travers remis d'équerre sur le faux FluidNC), courses (pont sous 0,233 refusé, mât à 0,83 permis, 0,84 refusé),
  accélération réduite seau tenu, places de photo, garage de repos, rotation de la tête refusée au-delà de x 2,0,
  alarme d'un pilote. Outil d'essai et procédure sur le vrai matériel (sens des axes, équerre, fins de course) ;
  « testé sur le vrai matériel : non ».
- [x] **36 bis. Portique : corrections après la PR n° 56** — Modèle : Opus, effort moyen. **À faire après la tâche
  19 ter.** Source : `docs/decisions.md`, « Portique, réponses à la PR n° 56 » (03/11/2026), et ci-dessous (fils
  Griffe et Portique, 03/11). Repère des angles du logiciel partout : A = 0 bras le long du pont (axe y), raclette
  vers −x (côté fût), A positif = sens trigonométrique vu de dessus.
  1. **Hauteurs de pose vraies** (`remplissage → formats → pose_plateau_z`) : A 0,4675, B 0,5125, C 0,4925,
     D 0,4625 (remplacer les exemples, dont le 0,475 de A). Vérifié au démarrage : face à l'étape c) de la prise
     double (pose + 0,003 − 0,028) ≥ bas de la course de la face de la préhension, sinon erreur au démarrage.
  2. **Préhension +22 cm** (décision, point 8) : course de `prehension_z` (face 1,10 → 0,23) et de la plaque Z
     (`portique → plaques_z → prehension`, 1,308 → 2,178) ; prise double sur le chariot pour les 4 formats (ordre
     a) à i), plus de cas « sans séparation ») ; nouvelle règle : plaque Z de la préhension au-dessus de 2,02 →
     mât de la préhension à y ≤ 0,80 (vérifiée au démarrage et à chaque mouvement). Mât plus souple : face de la
     préhension sous `portique → tete_basse_z` (0,60, EXEMPLE), accélération X et Y multipliée par
     `portique → facteur_acceleration_tete_basse` (0,5, EXEMPLE), en plus de la règle « seau tenu ». Tests.
  3. **Bout côté fût** (`portique → bouts_bloques_griffe`) : une bande avec une condition de hauteur, `{pont_x:
     [0.233, 0.30], axes_z_max: 1.05, angles_deg: [180]}` (seul A = 180° : à 0° la raclette, à ± 90° les bras,
     en biais jusqu'à 0,143, touchent la traverse ; à 180° il reste 15 mm). Retirer la bande « x 2,0-2,495 :
     0° ou 180° » : au-delà de x 2,0, la règle reste seulement « pas de rotation » (`griffe → rotation →
     pont_x_max`). Tests : A = 0 refusé à pont 0,25 axes 1,0, permis à axes 1,06 ; A = 180 permis ; A = 90 permis
     à pont 2,2 (sans rotation).
  4. **Origines A et B de la griffe** (remplacer l'exemple de la PR n° 56) : 2 capteurs inductifs M12 PNP NO
     (actifs à +24 V quand ils voient le métal), `origine_godet_griffe` (actif godet « fermé ») et
     `origine_rotation_griffe` (actif pour A de −180° à 0°) dans `docs/entrees-sorties.yaml` (`exemple: true`,
     2 entrées 24 V actives hautes, sur le multiconducteur de la griffe). **B** : 2 mm vers l'ouvert, puis vers FERMÉ, lent, à courant réduit,
     jusqu'au capteur actif = « fermé nominal » (0) ; butées logicielles 0 à +36 mm ; blocage vu par le codeur
     avant le capteur : arrêt, alarme « godet bloqué, vider au-dessus d'un seau ». **A** : fanion de 180°,
     actionné pour A de −180° à 0, libre de 0 à +180° ; son état dit de quel côté de 0 est la tête ; tourner vers
     le bord, approche finale toujours en +, lente ; recherche limitée à 190° (sinon alarme), jamais au-delà de
     ± 180° ; origine = A 0. Ordre (`portique → origine`) : portique (Z, Y, X) ; B, Z en haut ; aller au point de
     recherche (0,86 ; 0,57) tête à 0° ou 180°, descendre les axes à 1,075, godet fermé ; A ; remonter. Si la
     dernière position connue de A n'était ni 0° ni 180° (coupure pendant une rotation en bas) : ne pas monter Z,
     alarme, tête remise à la main. Ce point (0,86 ; 0,57), axes 1,075, godet fermé, sert aussi à tous les
     demi-tours de la griffe hors du fût (`griffe → point_demi_tour`), à la place de tout autre point.
  5. **Pont jusqu'à x 0,223** (décision de Karulium du 03/11, point 6) : course de `pont_x`, `griffe → pont_x_min`,
     place de photo du stockage (`vision`), et tout ce qui disait 0,233 comme limite du pont.
     Bout côté fût : en plus de la bande du point 3, **pont de 0,223 à 0,233 : axes de la griffe ≥ 1,05
     obligatoires** (à 180° il ne resterait que 5 mm devant la traverse basse ; au-dessus, rotation libre), par
     exemple `{pont_x: [0.223, 0.233], axes_z_max: 1.05, angles_deg: []}` (aucun angle permis sous 1,05). Test. Places du lavage remises à x 0,352 (centre du fût de lavage) et décalage du brossage à
     0,002 ; jet d'air en relatif au centre : A (+2 ; −15,2), B (+2 ; −23), C (+2 ; 0), D (+2 ; −11,5) mm.
  6. **Rails X +0,43** (décision, point 9) : course du pont 0,223 → 2,925 (`pont_x`, `portique`), mât de la griffe
     x ≤ 2,738 (`stockage → trajets → griffe_x_max`, avant 2,325), préhension x ≤ 3,054, garage de repos et place
     de photo côté stockage à pont 2,925 (vision). Les places du stockage agrandi sont dans la tâche 35 ter.
  7. **Origine de la rotation de la tête de préhension** (décision « Origine de la rotation de la tête », 05/11) :
     `origine_rotation_tete` = capteur Hall sous la poulie de 60 dents (description à corriger). Prise d'origine
     de A (`fluidnc/prehension.yaml`) : approche finale lente, toujours dans le même sens ; la recherche ne doit
     jamais faire plus d'un peu plus d'un tour (le Hall voit l'aimant à chaque tour : une recherche longue
     tomberait sur le mauvais tour et vrillerait le cordon). Pour cela, le Pi **enregistre l'angle cumulé** de A
     (tours compris) dans un fichier à chaque arrêt (comme les autres états gardés au redémarrage) ; avant la prise
     d'origine, il ramène la tête près de 0, puis cherche le Hall. **Le tour vient du compte-tours** (décision,
     point 6) : nouveau signal `compte_tours_tete` (`docs/entrees-sorties.yaml`, `carte: ads1115`, `broche: A1`,
     `module: prehension`, conversion volts → degrés de la tête EXEMPLE : mi-course = 0°, rapport 3), précision
     ± 3°. L'angle enregistré sert de contrôle : écart de plus de `prehension → ecart_compte_tours_max_deg` (30,
     EXEMPLE) avec le compte-tours, ou compte-tours hors plage ⇒ pas de prise d'origine, l'écran demande « vérifier
     que le cordon n'est pas vrillé » et attend la confirmation (même chose après une coupure en pleine rotation). Nouveau réglage `prehension → angle_meplats_deg` (angle « méplats
     en face des mors en V » par rapport au Hall, EXEMPLE 0, à mesurer à la mise en service, procédure dans
     `pi/systeme/essai-prehension.md`). Pose et prise au porte-bocal : aller à la plus proche de
     `angle_meplats_deg + k × 120°` (dans ± 500°), donc au plus 60° de rotation, tolérance ± 3°. Tests : alignement
     depuis 0°, 59°, 61°, 490° ; angle enregistré relu après un redémarrage ; coupure ⇒ confirmation demandée ;
     tour pris au compte-tours à 370° ; compte-tours et angle enregistré en désaccord de 40° ⇒ confirmation demandée.
  8. **Couloir d'accès au bocal** (décision « Agitateur fixe, réponses à la PR n° 64 », point (c)) : remplacer le
     trajet d'accès « en ligne droite depuis n'importe quel point hors de la zone » par un réglage
     `prehension → porte_bocal → couloir: {depart: [0.925, 0.40], face_z: 1.10, demi_largeur_x_tete: 0.06,
     largeur_x_bocal: [-0.06, 0.04], demi_largeur_x_mors: 0.005}`. Seul trajet permis dans la zone : du départ à la
     verticale du bocal en −y (et retour en +y), face à 1,10, manivelle en bas, x dans la largeur permise (tête seule
     ou avec bocal). Avant de descendre sur le bocal : mors ouverts (fin de course) et axe de la tête à
     x ± 0,001 / y −0,001 +0,002 de la verticale (réglages `tolerance_pose_x_m`, `tolerance_pose_y_m`) ; vitesse
     lente sur les `descente_lente_pose_m: 0.023` derniers mètres (EXEMPLE de vitesse). Tests : bocal décalé de 2 mm
     en x ⇒ descente refusée ; arrivée côté mur refusée ; arrivée par +x refusée ; bocal tenu à x 0,925 + 0,05 refusé ;
     tête seule à x 0,925 + 0,05 acceptée ; trajet du départ à la verticale accepté.
  Tests de chaque point ; `vidange --verifier` et le simulateur passent.
- [x] **37. Préhension (ventouse, prises et poses)** — Modèle : Opus, effort moyen. **Se fait avant la tâche 21**
  (le Lavage a besoin de la Préhension, qui tient le seau pendant tout le lavage).
  Sources (recopiées ici le 29/10/2026) : fiche du module « Préhension », **validé définitivement le 27/10/2026**,
  plan de commande v221, rails HGR15 du Portique (29/10, déjà dans `docs/decisions.md`).
  Les chiffres vont dans `pi/reglages/machine.yaml`, `docs/entrees-sorties.yaml` et `fluidnc/`, jamais dans le code.

  *Ce que fait le module.* La tête de préhension pend sous le même pont que la griffe, sur son propre mât. Elle
  prend par une ventouse Ø 40 (vide fait par un venturi) les seaux vides, les couvercles, les bocaux et l'entonnoir,
  et tient les capsules par 3 électroaimants. Elle peut tourner sur elle-même (rotation) et visser une capsule.
  Cette tâche écrit les gestes de base de la tête ; les modules qui s'en servent (Stockage, Lavage, Remplissage,
  Entonnoir) les appelleront plus tard.

  *Position du mât* : axe de la préhension = **pont + 0,129** en x (rails HGR15, 29/10), même y que la griffe.
  À mettre dans `machine.yaml` (comme `decalage_mat_x` de la griffe). La course en x se déduit de celle du pont.

  *Moteurs et capteurs* (carte 4, sauf le vide ; à ajouter à `docs/entrees-sorties.yaml` et `fluidnc/`, marqués
  `exemple: true` tant que le plan de câblage n'est pas arrivé) :
  - Z préhension : pignon-crémaillère avec frein (maintien réduit à l'arrêt). « En haut » = face de la tête en
    butée haute à **1,10** ; course ≈ 0,67 (exemple, à confirmer au montage).
  - Rotation de la tête : maintien plein (≈ 3 N·m pendant le brossage du lavage et le vissage). Visser = sens
    horaire vu d'en haut ; aucun axe inversé dans FluidNC.
  - Vanne de vide (venturi) : 1 sortie. Électroaimants des capsules : 1 sortie (carte à confirmer au câblage).
  - Capteur de vide XGZP6847A lu par l'ADS1115 de l'armoire (entrée `capteur_vide`, déjà dans le fichier). Avec le
    capteur 5 V et le pont 10 k / 20 k : tension du capteur = 1,5 × tension lue ; vide (kPa) = −25 × (tension du
    capteur − 0,5) ; repères 0 kPa → 0,333 V lus, −40 → 1,40 V, −55 → 1,80 V, −100 → 3,00 V. Le capteur 3,3 V
    (préféré le 26/10) se branche sans pont : la conversion est un réglage du fichier, jamais dans le code.
    ≈ 100 lectures/s avec moyenne. **Zéro recalé à chaque démarrage, vanne de vide fermée.**
  - Capteur de force : palier pesé du mât (Phidgets 3135 50 kg + HX711), lu par sa carte RS485 (tâche 22 bis) ;
    ici, derrière la même interface de pesée que la griffe, avec un faux. Lecture = poids porté − poussée.
  - Contact de la tête : plateau flottant (course 3 mm, ≈ 10 N) vu par un inductif M8 du moyeu. Il sert aussi
    de contact « anse levée » du plan de commande (une seule entrée).
  - Alarmes des pilotes et fins de course de la préhension (origines comme dans `fluidnc/`).

  *Règles de mouvement* (verrous du logiciel : ils protègent la machine, pas les personnes) :
  1. XY sur la carte 1 puis Z sur la carte 4, **jamais les deux à la fois** : la tête est en haut (ou à l'arrêt
     en appui) avant tout déplacement du pont.
  2. Isolation du fût : axe de la tête sous **x 0,71** et panneau de la paroi pas vu « rabattu » ⇒ face à 1,10
     (le signal est le panneau, pas la présence du fût).
  3. Seau tenu avec son axe à **y > 0,86** (côté opérateur) : bord du seau ≤ 1,10. Au-dessus des piles (y ≤ 0,86) :
     bord ≤ 1,155.
  4. Boîtier de la caméra du bocal : la tête ne passe pas autour du boîtier tant que sa face est trop basse. À
     calculer depuis la boîte `camera_bocal` déjà dans `machine.yaml` + rayon de la tête 0,045 + 1 cm + rayon de
     l'objet tenu. Contrôle : la page donne x 0,99-1,16, y < 0,335, face sous 1,072 (bocal : x 0,98-1,17, y < 0,345).
  5. Caméra du dosage : la préhension donne sa position au verrou déjà écrit (pas dans la boîte x < 1,10, y < 0,34,
     z 0,95-1,08 pendant que la caméra pivote).
  6. Seau tenu : accélération réduite sur la carte 1 (l'anse balance) ; valeur en réglage.
  7. Choc : écart de plus de 15 N entre la force lue et le poids porté pendant plus de 50 ms, en trajet ⇒ arrêt de
     Z et du pont, remontée lente, alerte avec photo. Le capteur voit surtout le vertical : il ne remplace pas les
     zones interdites.

  *Prendre un objet* (seau, couvercle, bocal, entonnoir) :
  1. Tare tête en l'air. Descente ; lente sur les derniers cm (réglage).
  2. Contact de la tête : le Pi note la cote Z au déclenchement ; plus de 5 mm d'écart avec la cote attendue ⇒
     arrêt et alerte (cotes attendues : réglages, par objet).
  3. Vanne de vide ouverte ; attendre vide ≥ −55 kPa (délai maximal : réglage). Valeur de chaque prise écrite au
     journal (repère une ventouse usée).
  4. Levée lente (≈ 10 mm/s sur les 30 premiers mm, réglages), puis normale si le vide est ≥ −55 kPa, lente
     s'il est plus faible. Si le vide remonte au-dessus de **−40 kPa** pendant la levée : « feed hold » à la carte 4,
     redescendre, reposer, reprendre ; après 2 échecs, alerte.
  5. Confirmer la prise par le poids : seau vide ≈ 5 N, deux seaux emboîtés ≈ 10 N (reposer), couvercle ≈ 1 à
     1,5 N, bocal plein ≈ 10 N (poids estimés : réglages, à mesurer à la mise en route ; poids d'un seau vide
     pris dans la table des formats s'il y est). Une capsule seule (30 g) est trop légère : pas de contrôle.
  6. Seau vide : avant de descendre dedans, la caméra vérifie qu'aucune anse n'est levée (point d'appel, l'analyse
     est dans la tâche 22) ; le contact de la tête déclenché trop haut = anse levée : arrêt et alerte.
  Lâcher : vanne de vide fermée (et électroaimants coupés pour une capsule), puis remontée.
  La fonction `tient_un_objet()` (vide confirmé) sert au verrou du noyau du Lavage : sa rotation s'arrête à toute
  perte de vide. Le mode manuel du téléphone applique les mêmes verrous.

  *Visser ou dévisser une capsule Twist-Off* : rotation et Z ensemble sur la carte 4 (le porte-ventouse à ressort
  absorbe le décalage). Appui lu par le capteur de force : consigne 80 N, accepté 60 à 100 N, **au-delà de 150 N
  arrêt et alerte** (le pilote limite Z à 250 N). Angle de vissage : réglage.

  *Poser et reprendre le bocal dans le porte-bocal* (au garage de l'agitateur, x 0,565 ; validé le 24/10) :
  - Poser : mors grands ouverts, tête orientée à ±3°, bocal descendu à sa hauteur exacte (±0,5 mm), mors à
    « Ø 98 » à faible courant, lâcher, remonter d'au moins 5 mm, **puis** `serrer_bocal()` (tâche 20).
  - Reprendre : mors serrés, descente lente entre les mors, prise, `ouvrir_mors()`, remonter.
  - Jeu 1 mm au-dessus de la capsule et sous le fond. La tête ne tourne jamais entre les mors.
  Ajouter au porte-bocal la position « Ø 98 faible courant » si elle manque (sans changer le reste).

  *Ce qui n'est pas dans cette tâche* : la sortie d'une pile de seaux (Stockage), les gestes du lavage (couloir du
  seau retourné, couvercles sur le noyau, jet d'air, réservoir et rince-verre : tâche 21), la pose sur le chariot
  de remplissage et ses verrous (Remplissage), l'entonnoir (Entonnoir), l'analyse des photos (tâche 22).
  Ces modules appellent les gestes d'ici.

  Simulateur : un scénario `prehension` sur le faux FluidNC et les faux capteurs : prise d'un seau, d'un couvercle
  et d'un bocal, pose et reprise au porte-bocal, vissage. Tests, dont : vide qui lâche pendant la levée (feed hold,
  2 échecs ⇒ alerte), deux seaux pris, contact trop bas, choc, isolation du fût, XY refusé tête basse, vissage
  au-delà de 150 N, zéro du vide au démarrage.
- [x] **17 bis. Poste du fût : plateau de pesée sans fil (côté Pi)** — Modèle : Opus, effort moyen. **À faire après
  la tâche 35 ter.**
  Sources : `docs/decisions.md`, « Poste du fût : plateau de pesée sans fil » (05/11/2026), recopiée de
  `poste-fut-pour-logiciel.md` v10 du projet mécanique. Les chiffres vont dans `pi/reglages/` et
  `docs/entrees-sorties.yaml`, jamais dans le code. Ne pas écrire les programmes des ESP32-C3 (tâche 17 ter).

  *Gestes à la main* (le rappel de l'écran est à refaire) : fût posé debout sur le plateau entre les 4 cales,
  soupape enlevée, trou bouché ; plateau roulé et poussé contre les 2 butées d'angle du fond, 2 roulettes freinées ;
  grand volet rabattu, panneau long levé ; appui sur « Prêt ». Fin : volet relevé, freins desserrés, plateau sorti.
  Plus de prise à brancher, de goupille ni de sangles.
  1. **Signaux** (`docs/entrees-sorties.yaml`) : renommer `chariot_fut_en_place` en `plateau_fut_en_place` partout
     (code, réglages, simulateur, textes de l'écran : « chariot du fût » devient « plateau du fût »). `pesee_fut`
     n'est plus sur `GPIO20/21` : c'est un appareil du bus `rs485_pesee`, `adresse: 4`, avec un nouvel `appareil`
     (par exemple `boite_poste_fut`) pour que la fabrication du programme des cartes RP2040 ne le prenne pas. Le
     reed du plateau n'est **pas** un signal du Pi. Pas de capteur de volet ni de fût posé. Tout reste `exemple: true`.
  2. **Lecture** : réutiliser le code du bus des pesées (`pi/vidange/pesees/`) pour les registres 0 à 7 ;
     vérifier la signature **0x5046** (pas 0x5053) ; lire aussi les registres 8 à 12 (reed, recharge, USB-C de
     secours, tension en mV, %, signal en dBm + 200, trames perdues). Une ligne `pesee_fut` dans `tour:` de
     `pesees.yaml`, interrogée au plus une fois par seconde (réglage) pour ne pas ralentir la griffe (≥ 80 mesures
     par seconde, à vérifier dans un test). Retirer le code qui lit le HX711 directement par les GPIO s'il ne sert
     plus à rien d'autre.
  3. **Étalonnage** dans `pi/reglages/pesees.yaml → etalonnage → pesee_fut` (retirer `zero_brut` et `brut_par_kg` de
     `machine.yaml → poste_fut → pesee`). Tare plateau + boîtier + fût vide + couvercle ≈ 59,4 kg ; bornes
     plausibles ≈ 50 à 200 kg ; tout EXEMPLE (corrigé : zéro plateau vide, donc tare 33,4 kg et bornes 25 à 150 kg,
     `docs/decisions.md`, réponses à la PR n° 77). La boîte fait déjà la moyenne de 5 : le Pi ne refait pas une médiane
     de 5 lectures (1 par seconde, ce serait 5 s) ; garder seulement le rejet d'une valeur hors bornes. Mesure lue
     seulement griffe hors du fût, comme avant.
  4. **Pesée absente** : pas de réponse, registre 4 bit 2, ou âge (registre 3) > 2 s (réglage) ⇒ « pesée absente »,
     affichée, au journal, une alerte dans la file (une seule par absence, pas une par seconde). Jamais un arrêt.
     Elle revient seule. **« Prêt » n'exige plus la pesée** : plateau en place + signaux stables 2 s + appui. Au
     « Prêt » sans pesée : cycle commencé sans poids du fût plein ; seaux notés « sans pesée du fût » dans le
     registre et dans `mesures[]` (`docs/django.md` : le dire). Après `plateau_fut_en_place` vrai, si la pesée ne
     répond pas dans 5 s (réglage) : message « pesée absente » sur le poste (pas de refus).
  5. **Batterie** (`pesees.yaml`, EXEMPLES) : ≥ 3,6 V bon ; < 3,5 V alerte « recharger le plateau » ; < 3,3 V alerte
     forte « pesée bientôt absente » ; plateau au poste depuis plus de 10 min sans « recharge en cours » : alerte
     « recharge sans contact en panne ? ». Niveau en % et signal radio affichés à l'écran et sur la page web.
     Vérification au démarrage : seuils dans le bon ordre.
  6. Mettre à jour la procédure d'essai du poste (`pi/systeme/essai-poste-fut.md`) : tare plateau vide, masse
     connue ≈ 20 kg au centre, radio coupée (débrancher la boîte) ⇒ « pesée absente » sans arrêt.
  Simulateur : fausse boîte du poste (trames, radio muette, accu faible), scénario « échange de fût » repris avec le
  plateau. Tests : « Prêt » accepté sans pesée ; signature 0x5053 refusée pour `pesee_fut` ; mesure de 2,5 s ⇒
  absente ; une seule alerte pour une longue absence ; retour de la pesée sans redémarrer ; seuils de l'accu ;
  plateau 10 min sans recharge ⇒ alerte ; la griffe garde ses 80 mesures par seconde avec `pesee_fut` dans le tour.
  `vidange --verifier` passe.
- [x] **17 ter. Programmes des 2 ESP32-C3 du poste du fût (plateau et boîte du poste)** — Modèle : Opus, effort
  moyen. **À faire après la tâche 17 bis.** Vrai matériel : procédure d'essai pas à pas, « testé sur le vrai
  matériel : non ».
  Sources : la même décision que 17 bis, et `poste-fut-pour-logiciel.md` (programmes). Dans un dossier
  `poste_fut_radio/` à côté de `pesee/`, sur le même modèle (réglages copiés depuis `pesees.yaml` à la fabrication,
  tests sur PC avec faux HX711 et fausses trames, CI).
  - **Plateau** : dort, se réveille sur le reed ; lit le HX711 à 10 mesures par seconde (RATE à la masse), moyenne
    de 5, une trame ESP-NOW toutes les 0,5 s (brut, numéro, HX711 muet, tension et %, recharge, USB-C de secours) ;
    tension de l'accu par pont diviseur ; se rendort 30 s après l'ouverture du reed.
  - **Recharge** (tranché par Claude, réponses à la PR n° 77, `docs/decisions.md`) : le bit 1 (valeur 2) du
    registre 8 veut dire « **5 V de la recharge sans contact présent** », **pas** « en charge » : il reste vrai
    quand l'accu est plein (sinon l'alerte « recharge sans contact en panne ? » viendrait à chaque accu plein). Le
    plateau le met dans la trame, la boîte le recopie tel quel.
  - **Boîte du poste** : toujours alimentée ; reçoit les trames (seulement de l'adresse radio du plateau, dans les
    réglages, jamais dans le code) ; répond en Modbus RTU à 115 200 bauds, 8N1, registres 0 à 12 et signature
    0x5046 de 17 bis ; bit « radio muette » si rien depuis 2 s ; MAX3485 avec DE/RE. Reprendre le code Modbus de
    `pesee/src/modbus.c` si c'est possible.
  - Pas de Wi-Fi ni de réseau : ESP-NOW seulement (exception décidée par Karulium). Mise à jour par le câble USB,
    comme les autres cartes.
- [x] **38. Nettoyage : store, purge après fermeture, nuit UV-ozone, mode maïs** — Modèle : Opus, effort moyen.
  **À faire après la tâche 38 bis** (lecture des ZE25-O3 `ozone_dedans` et `ozone_dehors`). Source, recopiée ici le
  06/11/2026 : `nettoyage/logiciel/nettoyage-pour-logiciel.md` du projet mécanique (module Nettoyage gelé, lot validé
  par Karulium les 27/10, 31/10, 01/11 et 04/11). Positions : `nettoyage/logiciel/enceinte-04-11.yaml`. Elles vont
  dans `pi/reglages/machine.yaml → nettoyage` (figées) ; le code ne lit que leurs noms.
  *Sécurité câblée* (le Pi lit seulement, pour informer et attendre) :
  - `store_ferme` (2e contact) est dans la boucle d'arrêt du portique ;
  - la chaîne UV-ozone (reeds bas du store + `porte_spray` en série) alimente `generateur_ozone` et `lampe_uv` ;
  - les verrous du store sont fermés sans courant, avec une clé de dépannage ;
  - le moteur du store est en commande maintenue : 2 boutons câblés, fins de course dans le moteur. **Le Pi ne
    commande pas le moteur du store.**
  - L'alarme d'ozone câblée (« porte verrouillée tant que l'ozone dépasse 0,1 ppm ») n'a plus d'appareil choisi
    (question posée à Karulium) : **n'écrire aucun code qui la remplace.** Prévoir seulement une entrée facultative
    `ozone_securite_ok` (contact, pour informer), absente tant qu'elle n'est pas dans les réglages.
  1. **Signaux** (`docs/entrees-sorties.yaml`, tous `exemple: true`, broches plus tard avec l'Implantation) :
     - entrées : `store_ferme` (2 reeds en série, 24 V, fermé = store fermé) ;
     - sorties relais : `verrous_store` (sous tension = déverrouillé), `eclairage_enceinte` (2 rubans LED 12 V
       ensemble), `ventilateur_enceinte` (230 V), `generateur_ozone` (prise du VEVOR), `lampe_uv` (ballast) ;
     - sortie 0-10 V : `consigne_ventilateur` (moteur EC) ;
     - capteurs pas encore choisis, en **case vide** (interface + faux du simulateur, pas de pilote réel) :
       `particules_dedans`, `particules_dehors` (PMS5003 ou SPS30, UART), `pression_enceinte` (pression
       différentielle, Pa).
  2. **Store** :
     - Demande « ouvrir le store » (écran, page web) refusée si un cycle tourne, pendant la purge, ou en mode
       UV-ozone tant que l'ozone n'est pas fini (point 4). Sinon : `verrous_store` sous tension, et c'est affiché.
     - `store_ferme` faux ⇒ état « store ouvert » : aucun mouvement lancé, et c'est dit à l'écran.
     - `store_ferme` vrai stable 2 s (réglage) ⇒ verrous remis (hors tension), puis purge (point 3), sauf en mode
       maïs.
     - `store_ferme` encore faux 60 s (réglage) après une demande de fermeture, ou qui retombe pendant un cycle ⇒
       alerte « store mal fermé », pas d'ozone ni de purge.
  3. **Purge après fermeture** :
     - Au départ : `ventilateur_enceinte` en marche, consigne « plein ».
     - Pendant la purge : **interdits** le dosage de la semence, l'ouverture d'une capsule et le versement dans un
       seau ouvert. Les modules Mycélium et Remplissage demandent la permission au chef, qui la refuse avec la
       raison « purge en cours ». Le reste tourne ; l'UV des têtes est permis.
     - Fin de purge quand **toutes** ces conditions sont vraies :
       - au moins 7 min ;
       - `particules_dedans` ≤ 1,5 × `particules_dehors`, stable 1 min ;
       - `pression_enceinte` ≥ 8 Pa (5 Pa avec balais : réglage).
       Alors : consigne « normal ».
     - Pas finie après 20 min ⇒ alerte. Les gestes restent interdits ; Karulium décide à l'écran : continuer
       d'attendre ou passer outre. Passer outre est noté au journal.
     - Store rouvert pendant la purge ⇒ purge remise à zéro.
     - Un capteur de purge absent ou muet ⇒ cette condition n'est jamais vraie (donc alerte à 20 min), jamais
       « vraie par défaut ».
  4. **Nuit UV-ozone** (mode `uv_ozone`, qui existe déjà) :
     - Conditions de départ : `store_ferme`, verrous remis, `porte_spray` fermée, `reed_panneau_poste_fut` comme le
       demande le Poste du fût, aucun cycle. Sinon : refus, avec la raison.
     - Départ à l'heure réglée (EXEMPLE 22 h) ou tout de suite.
     - Le Pi coupe `ventilateur_enceinte`, le compresseur (`relais_compresseur`, module Air) et le ventilateur de
       l'armoire.
     - `generateur_ozone` marche pendant `t_generation` (EXEMPLE 2 min), puis s'arrête.
     - Attente de `t_contact` (EXEMPLE 2 h), avec `ozone_dedans` noté au journal. La valeur au plafond s'affiche
       « ≥ 10 ppm ».
     - Retour : `ozone_dedans` < 0,1 ppm stable 15 min. Alors le compresseur et les ventilateurs sont de nouveau
       permis. Le store reste verrouillé jusqu'à une demande d'ouverture, qui n'est permise qu'avec ozone < 0,1 ppm.
     - Erreurs :
       - pas sous 0,1 ppm après `t_max_retour` (EXEMPLE 6 h), ou capteur muet, ou mesure incohérente ⇒ alerte (file
         réseau), store verrouillé ; ouverture seulement par la clé de dépannage ;
       - `ozone_dehors` > 0,1 ppm à tout moment ⇒ alerte forte « fuite d'ozone » (écran, voyant et buzzer s'ils
         existent dans `entrees-sorties.yaml`, file) et `generateur_ozone` coupé ;
       - `store_ferme` qui tombe ou `porte_spray` ouverte pendant la nuit ⇒ générateur coupé (le câblage le coupe
         aussi), alerte.
     - Reprise après une coupure de courant en pleine nuit : le générateur reste coupé, et le Pi reprend à
       l'attente du retour (ozone < 0,1 ppm stable 15 min). Il ne relance jamais une génération seul.
  5. **Lampe UV des têtes** : `lampe_uv` permise seulement store fermé, pendant le garage UV du bain des têtes
     (5 + 5 min, figé). Brancher seulement le relais et sa permission ; le geste du bain reste celui de son module.
  6. **Mode maïs** : store ouvert, ventilateur coupé (la vapeur moisit le HEPA), pas de purge. Le portique lent par
     la clé relève du module Portique : ne pas le refaire.
  7. **Éclairage** : `eclairage_enceinte` allumé à la demande (écran) et pendant un cycle, éteint en mode UV-ozone.
  Réglages : tous les chiffres du § 3 de la source (`machine.yaml → nettoyage`). Ceux marqués « exemple » portent
  `exemple: true`. Vérification au démarrage : durées positives, `t_generation` < `t_contact` < `t_max_retour`,
  niveaux du ventilateur entre 0 et 10 V et croissants (arrêt < normal < plein).
  Simulateur : faux store (ouvrir, fermer, reed qui rebondit), faux capteurs de particules et de pression, scénarios
  « fermeture puis purge », « purge trop longue », « nuit UV-ozone complète » et « fuite d'ozone dehors ».
  Tests :
  - refus d'ouvrir pendant cycle, purge ou ozone ;
  - verrous remis après 2 s stables ;
  - purge finie seulement quand les 3 conditions sont vraies ;
  - dosage refusé pendant la purge ;
  - purge remise à zéro si le store se rouvre ;
  - capteur muet ⇒ jamais « fini » ;
  - nuit complète, générateur jamais relancé après une coupure ;
  - fuite dehors ⇒ générateur coupé ;
  - store ouvert pendant la nuit.
  `vidange --verifier` passe. Procédure d'essai pas à pas sur le vrai matériel (store, verrous, ventilateur,
  générateur à blanc, enceinte vide, personne dedans) ; « testé sur le vrai matériel : non ».
- [x] **38 bis. Capteurs d'ozone Winsen ZE25-O3 en UART (ozone_1 et ozone_2)** — Modèle : Sonnet, effort moyen.
  Sources (recopiées ici le 31/10/2026) : fiche du module « Nettoyage », de nouveau **gelé le 31/10/2026** (choix du
  ZE25-O3 validé par Karulium), plan d'implantation. Remplace la lecture Modbus de l'ozone (tâche 2 :
  `pi/vidange/materiel/modbus.py`, `transmetteur_modbus`).
  *Matériel* : 2 capteurs ZE25-O3 (0 à 10 ppm), chacun dans son boîtier IP65, alimentés en 5 V par le câble capteurs,
  avec un convertisseur TTL-RS485 automatique. **Deux liaisons séparées** : un adaptateur USB-RS485 par capteur
  (`ozone_1` dedans, `ozone_2` dehors), reconnu par son numéro de série comme les autres adaptateurs. Aucune adresse :
  le ZE25-O3 n'est pas un appareil Modbus.
  *Protocole* : celui de la notice Winsen du ZE25-O3 (vitesse, trames de 9 octets, somme de contrôle, mode « envoi
  automatique » ou « question-réponse ») : le recopier depuis la notice, dans les réglages s'il y a des chiffres, et
  le dire dans la PR. Trame à la somme fausse : ignorée et comptée ; plus de trame valable depuis un délai (réglage)
  ⇒ capteur « muet », affiché comme tel, alerte.
  *Valeurs* : en ppm pour l'écran, le journal et le mode UV/ozone. La nuit l'ozone dépasse 10 ppm : une valeur au
  plafond s'affiche « ≥ 10 ppm » (jamais « 10 »).
  *Sécurité* : elle reste câblée (indicateur de process sur la sortie analogique du capteur du dedans, 2 relais, store
  ouvert seulement relais du Pi ET les 2 seuils câblés : docs/decisions.md à compléter si absent). Le Pi lit l'ozone
  pour **informer et attendre**, jamais pour protéger.
  Mettre à jour `docs/entrees-sorties.yaml` (`exemple: true`), le faux capteur du simulateur et l'outil d'essai du
  matériel. Retirer le Modbus de l'ozone s'il ne sert plus à rien d'autre.
  Tests : trames bonnes, somme fausse, trame coupée, capteur muet, valeur au plafond, deux capteurs indépendants
  (l'un muet, l'autre lu). Procédure d'essai sur le vrai capteur ; « testé sur le vrai matériel : non ».
- [x] **38 ter. Pilotes réels des capteurs de la purge** — Modèle : Sonnet, effort moyen. Pièces choisies par le fil
  Nettoyage (06/11/2026) : 2 SPS30 (`particules_dedans` par convertisseur TTL-RS485 et son adaptateur USB-RS485,
  `particules_dehors` sur l'UART3 du Pi, GPIO 8/9 (EXEMPLE, Implantation 06/11) ; adaptateur `rs485_sps30` ; UART 115 200 bauds, protocole SHDLC de Sensirion), 1 SDP810-125Pa en I2C
  (`pression_enceinte`), module PWM → 0-10 V sur GPIO 19 pour `consigne_ventilateur`. Remplacer les cases vides de la tâche 38
  par les vrais pilotes (protocoles à vérifier sur les notices, dans la PR), avec faux et tests (trame fausse, capteur
  muet ⇒ condition de purge jamais vraie). Procédure d'essai ; « testé sur le vrai matériel : non ».
- [x] **39. Spray, côté Pi** — Modèle : Opus, effort moyen. À faire après la tâche 38.
  Source, recopiée ici le 06/11/2026 : `pulverisation/logiciel/spray-pour-logiciel.md` du projet mécanique. C'est la
  fiche v5.8 du module gelé ; elle donne les gestes a) à d), les signaux, les chiffres et le câblage. Choix
  électriques : `docs/decisions.md`, « Électronique du chariot et liaison du spray » (06/11/2026).
  1. **Liaison** : la carte ESP32 n° 5 est un esclave Modbus RTU sur son propre bus `rs485_spray`, avec son adaptateur
     USB-RS485 (reconnu par son numéro de série) et sa propre adresse. Écrire la **table des registres** dans
     `spray/README.md`, avec une signature propre : c'est la langue commune avec la tâche 39 bis.
     - Ordres : état, prise d'origine du bras, sortir à l'angle, ranger, spray (emplacement, dose en g), nettoyer,
       agitateurs (vitesse), arrêt immédiat.
     - Réponses : poids de chaque flacon (brut et en g), bras rangé (capteur), bras sorti, résultat de la dernière dose
       (poids perdu, durée, état), compteur de démarrages, erreurs.
     - Le Pi envoie un battement pendant un spray. La carte s'arrête seule (pompe, air, bras) si le Pi se tait plus de
       2 s (réglage).
  2. **Gestes du Pi** : a) un seau, b) nettoyage des tubes, c) changement de flacon, d) cas d'erreur, comme dans la
     source. Règle d'or : **tant que la carte n'a pas redit « bras rangé », `bras_spray_sorti` est vrai** (chariot
     immobile en hauteur et aux barres, seule la rotation du seau est permise), même si la carte se tait. Reprendre
     `remplissage/regles.py → refus_bras_spray` (règle 6). Une erreur du spray met le seau « sans spray » et
     l'écran propose de continuer sans spray ou d'attendre. Le spray ne protège personne.
  3. **Zone interdite à la griffe, porte du spray ouverte** : **x < 0,50 et y < 0,40**, et jamais au « Bain des
     têtes ». Ces chiffres viennent de la Maquette (31/10) et remplacent y < 0,33 dans `docs/decisions.md` (règle 3)
     et dans `PorteSprayGriffe` de `reglages.py`.
  4. **Points non décidés, tranchés ici** (niveau 1, à noter dans `docs/decisions.md`) :
     - un seul flacon par seau, l'emplacement par format venant des réglages (EXEMPLE : emplacement 1 pour tous), en
       attendant la règle du logiciel de culture ;
     - agitateurs 30 s avant chaque dose, puis 1 min toutes les 15 min (réglages) ;
     - « dose d'amorce » réglable (EXEMPLE 1 g), ajoutée à la première dose après un changement de flacon et notée à
       part dans le registre ;
     - pompage pendant la rotation du seau ; la chasse finit le travail.
  5. Réglages : tous les chiffres du § 3 de la source vont dans `machine.yaml → spray`, en EXEMPLE quand la source le
     dit. Étalonnage des 4 balances dans `pesees.yaml`.
     Vérification au démarrage : angles par format entre 0 et 110°, réserve > 0, temps positifs.
  Simulateur : fausse carte n° 5 (balances, bras, pompe, carte muette).
  Tests :
  - bras pas rangé ⇒ chariot immobile ;
  - carte muette ⇒ bras supposé sorti ;
  - règle 6 refusée ;
  - flacon presque vide ;
  - dose pas atteinte, dose trop forte ;
  - porte ouverte pendant un spray ;
  - nouvelle zone de la griffe ;
  - amorce ;
  - compteur des nettoyages.
  `vidange --verifier` passe.
- [x] **39 bis. Programme de la carte ESP32 n° 5 du spray** — Modèle : Opus, effort moyen. À faire après la tâche 39.
  Vrai matériel : procédure d'essai pas à pas, « testé sur le vrai matériel : non ».
  Dossier `spray/`, sur le modèle de `poste_fut_radio/` (ESP-IDF, code commun en C testé sur PC, CI qui fabrique le
  programme, réglages copiés depuis les réglages du Pi à la fabrication). Le Modbus vient de `pesee/src/modbus.c`
  et suit la table des registres de la tâche 39.
  - 4 pompes NEMA 17 sur TMC2209 en pas/direction : pompage jusqu'à la perte de poids demandée, avec un temps maximum.
  - Bras : NEMA 17 sur TMC2209 en UART, 1,2 A, lent ; origine sur `bras_spray_range` ; butée logicielle 0 à 110°.
  - `bras_spray_range` passe par un optocoupleur PC817 (logique inversée : bras rangé = GPIO à 0).
  - 4 HX711 (cellules de 1 kg).
  - Sorties MOSFET : `ev_buse_spray`, `ev_chasse_spray`, `agitateurs_spray` (PWM, une seule pour les 4),
    `pompe_nettoyage_spray`.
  - Sécurité de la machine : « sortir » refusé sans ordre récent du Pi ; arrêt seul (pompe, air, bras rangé) si le Pi
    se tait plus de 2 s pendant un spray.
  - Broches : EXEMPLES dans les réglages, en attendant l'Implantation.
  Tests sur PC avec faux HX711, faux capteur et faux moteur.
- [x] **40. Micropore, côté Pi** — Modèle : Opus, effort moyen. À faire après la tâche 39 bis.
  Source, recopiée ici le 06/11/2026 : `micropore/logiciel/micropore-pour-logiciel.md` du projet mécanique (module
  gelé le 28/10). Elle donne les gestes 1 a (pose : tour de repérage, approche, avance de 13 mm, appui vu au ToF,
  pose de 17 mm, tension, coupe, fin, contrôle à la caméra), 1 b (tête escamotée pendant le spray, l'inspection et
  tout mouvement du plateau) et 1 c (changer le rouleau, apprendre un format), puis les signaux, les chiffres
  (figé, exemple, appris) et la sécurité câblée.
  - **Matériel** :
    - `servo_escamotage_micropore` et `servo_lame_micropore` sont sur la PCA9685 ;
    - `tof_tete_micropore` est un VL6180X ;
    - les deux passent par la **carte de pesée RP2040 du plateau du remplissage**, avec des registres Modbus en plus
      (tâche 40 bis, `docs/decisions.md` du 06/11/2026) ;
    - `avance_micropore` : NEMA 11 sur la carte FluidNC n° 3 (vérifier dans `fluidnc/` ; si la source se trompe de
      numéro de carte, le dire dans la PR) ;
    - `camera_micropore` : caméra USB.
  - **Règle** : tête escamotée (ToF à la position escamotée) avant tout mouvement du plateau, sinon le plateau ne
    bouge pas. Après un redémarrage de la carte (compteur de démarrages), le Pi renvoie les angles des servos.
  - **Gestes appris** (angle d'approche, angle de contact, angle caméra → rouleau par format) : dans un fichier de
    réglages appris, jamais dans le code. Les modifications sont notées et annulables.
  - **Rangée du fond** : le Pi attend environ 4 kg sur la balance du chariot (réglage). Cette rangée se pose pendant
    le premier aller-retour de la griffe. Si l'ordre avec le Remplissage pose problème, le dire dans la PR.
  - Compteur de morceaux et alerte « rouleau bientôt vide ». Le seau est marqué « micropore à vérifier » dans le
    registre.
  - Ne pas inventer de capteur (pas de contact ni de détecteur de ruban vide en plus de la caméra et du compteur).
  - Les chiffres du § 3 de la source vont dans `machine.yaml → micropore`, avec la vérification au démarrage.
  Simulateur et tests : ToF qui ne voit pas l'escamotage, pas de contact, trou découvert puis nouvel essai, rangée
  trop haute (> 0,575), format inconnu, carte redémarrée.
- [x] **40 bis. Carte de pesée du plateau : I2C vers la PCA9685 et le VL6180X** — Modèle : Sonnet, effort moyen. À
  faire avant la tâche 40.
  Vrai matériel : procédure d'essai, « testé sur le vrai matériel : non ».
  Dans `pesee/`, pour la carte du plateau du remplissage seulement (réglage par carte), ajouter un I2C (EXEMPLE I2C0
  sur GP4/GP5, 100 kHz) avec :
  - la PCA9685 : une voie par servo (escamotage du micropore, lame du micropore, signal du servo de la fermeture),
    angle → largeur d'impulsion par des réglages ;
  - le VL6180X : distance en mm et état.
  Registres Modbus en plus, à ajouter à `pesee/README.md`, sans changer les registres 0 à 7 :
  - en écriture (fonction 6 ou 16) : angles des voies ;
  - en lecture : ToF, compteur de démarrages, état de l'I2C.
  Fonctionnement :
  - la PCA9685 démarre sorties coupées ;
  - plus de 2 s sans ordre du Pi : la carte garde les angles (aucun mouvement).
  La pesée garde son rythme : la vérifier dans un test.
  Côté Pi : lecture et écriture de ces registres dans `pi/vidange/materiel/carte_pesee.py`, avec le faux, plus les
  signaux dans `docs/entrees-sorties.yaml` (`exemple: true`).
- [x] **41. Fermeture des seaux** — Modèle : Sonnet, effort moyen. À faire après la tâche 40.
  Source, recopiée ici le 06/11/2026 : `fermeture-seaux/logiciel/fermeture-seaux-pour-logiciel.md` du projet
  mécanique (module gelé).
  - Le servo DS3225 tourne le bras à vide, entre rangé (−160°, sens horaire) et travail (sur sa butée, 2,5° au-delà).
    Il ne bouge que si le plateau est à 0,26 au plus.
  - C'est le plateau qui ferme : il monte jusqu'à Hf selon le format, sous surveillance de la pesée du chariot (F_max
    200 N au plus), puis il tourne en sens horaire. **Jamais de rotation trigo pendant le contact.**
  - Il n'y a aucun capteur sur le bras : c'est la pesée qui vérifie.
  - Rien n'est câblé en dur pour ce module.
  - Signal du servo : une voie de la PCA9685 (tâche 40 bis). Son + vient de `bec_servo`.
  - Au redémarrage : zéro de la montée d'abord, puis bras rangé.
  - Diamètre du couvercle dans la table des formats (A 0,28, B 0,23, C 0,315, D 0,28) et contrôle au démarrage de
    la bande du haut avec lui (`docs/decisions.md`, PR n° 54).
  - Hf, Hc et le nombre de tours : EXEMPLES, à vérifier au premier essai sur les 4 vrais seaux.
  - La position du chariot en y pendant la fermeture se trouve dans les fichiers du Remplissage. Si elle n'y est
    pas, la poser en réglage et le dire dans la PR.
  - Le vérin de l'ancien LISEZMOI du mode couvercles n'existe plus.
  Tests :
  - plateau trop haut ⇒ servo refusé ;
  - effort au-delà de F_max ⇒ arrêt et descente ;
  - rotation trigo refusée en contact ;
  - redémarrage dans le bon ordre.
- [x] **40 ter. Vision du micropore** — Modèle : Sonnet, effort moyen. La caméra de la tête du micropore (tâche 40) :
  lecture du QR du seau, position des trous, contrôle de chaque pièce posée, et l'angle caméra → rouleau (donné à la
  main par `--camera-rouleau` pour l'instant).
  Elle lit aussi le **QR du flanc** pour le Remplissage (`VisionSeau.lire_seau`, étape `orienter_l_anse`, plateau à
  `plateau_lecture_qr`, pendant un tour avant le serrage des barres ; `docs/decisions.md`, réponses à la PR n° 89). Règles de la fiche `micropore/logiciel/micropore-pour-logiciel.md`
  (§ vision). Tests sur des images fabriquées (OpenCV, comme la tâche 22) ; ce qui demande des photos réelles reste
  un faux (tâche 22 ter).
- [x] **41 bis. Pose du couvercle sur le seau plein** — Modèle : Sonnet, effort moyen. Source, recopiée ici le
  07/11/2026 : `prehension/logiciel/pose-couvercle-pour-logiciel.md` du projet mécanique (fil Préhension, qui porte ce
  geste). Relire la fiche telle qu'elle est (elle a changé au § 5 le 07/11).
  - Prise à la pile de couvercles du stockage (outil à y 0,83, contact M8, vide −55 kPa, contrôle « un seul couvercle »
    au palier pesé) ; pose avec l'outil en (0,925 ; 0,49), plateau du chariot déjà à H_app ; contact M8 attendu à la
    face 0,439 (0,446 pour D) ± 8 mm, sans appui (c'est la fermeture, tâche 41, qui clipse) ; souffler, puis contrôle
    sur la balance du chariot. Format C : descente à 10 mm/s de la face 0,67 à 0,57 (2,3 mm avec la tête du
    micropore escamotée, en attendant la réponse du Micropore).
  - Cas d'erreur : étapes 3, 4, 6, 7, 10a, 10b, 12 et 13 de la fiche. Anse relevée : pas de geste ni de signal
    (Remplissage, 07/11), c'est l'erreur 10a (contact trop tôt) ; le message dit « vérifier l'anse du seau ».
  - Brancher le poste « couvercle » dans l'ordre du cycle (`pi/vidange/cycle/ordre.py`, tâche 45) avant la
    fermeture, et la condition de la fermeture « préhension lâchée et remontée au-dessus de z 0,60 ».
  - Valeurs non figées de la fiche en EXEMPLE ; § 5 de la fiche (points ouverts) en questions dans la PR.
  Tests : les cas d'erreur de la fiche, et le lot simulé de la tâche 45 avec couvercle et fermeture, sans alarme.
- [x] **42. Air comprimé** — Modèle : Sonnet, effort bas. Source, recopiée ici le 06/11/2026 :
  `air/logiciel/air-comprime-pour-logiciel.md` du projet mécanique (module gelé le 28/10).
  - Un seul signal du Pi : `relais_compresseur`, une sortie relais vers un contacteur. Il est ouvert pendant l'ozone
    et la purge ; la coupure de sécurité est câblée.
  - Pas de capteur de pression de ligne : un manque d'air se voit chez la Préhension (vide non atteint).
  - Réglages dans `pi/reglages/air.yaml` : attente de mise en pression 240 s et rappel du bidon de purge tous les
    7 jours, tous deux en EXEMPLE.
  - Au démarrage, le Pi attend la mise en pression avant le premier geste qui a besoin d'air. Le rappel de purge du
    bidon s'affiche à l'écran.
  - Brancher la coupure du compresseur de la nuit UV-ozone (tâche 38) sur ce relais, si la tâche 38 ne l'a pas déjà
    fait.
  - Tests.
- [x] **43. Entonnoir à bocaux** — Modèle : Sonnet, effort moyen. Source, recopiée ici le 06/11/2026 :
  `entonnoir/logiciel/entonnoir-pour-logiciel.md` du projet mécanique (v3 du 28/10).
  - L'entonnoir n'a ni capteur ni moteur. La Préhension le prend par sa ventouse, par l'oreille, en x bocal + 0,140,
    aimants éteints.
  - Seuils du vide : lever à −55 kPa ; en tenue, alerte au-dessus de −40 kPa.
  - Levée de transport : 0,060.
  - Contrôle de la pose : par la hauteur au contact du M8.
  - Le Pi garde l'état `entonnoir_place` (un bocal, « hors machine » ou « inconnu »), et le conserve après une
    coupure.
  - Pose et enlèvement à la main, confirmés par Karulium. Pas de poste de repos.
  - Pas de photo au hublot tant que l'entonnoir est sur le plateau.
  - La griffe ne verse que dans le bocal noté `entonnoir_place`.
  - Pas de rotation de la tête en tenant l'entonnoir.
  - Les noms de signaux de la source sont **proposés** : utiliser les noms qui existent déjà dans le code de la
    Préhension (tâche 36 bis).
  - Les hauteurs « exemple » se mesurent sur l'entonnoir reçu.
  - Tests : les cas du § 5 de la source.
- [x] **43 bis. Versement de la griffe dans un bocal de semence (mode bocaux)** — Modèle : Opus, effort moyen.
  Source : `/mnt/project-files/griffe/logiciel/versement-bocal.md` (fil Griffe, 07/11/2026 ; lire ce seul fichier, et
  le résumer dans la PR). Remplit la case vide `verser(bocal)` de l'Entonnoir (`pi/vidange/entonnoir/module.py`)
  avec un geste de la griffe (`pi/vidange/griffe/`).
  - Figé (réglages sans `exemple`) : dose ≈ 300 g ; mât au-dessus du centre du col (caméra) à ≤ 0,05 ; tête à
    A = 0, aucune rotation pendant le versement ; axes des coquilles à 1,025 (plage 1,02-1,07) ; ouverture de fermé
    à 20° ; garde du boîtier de la caméra du bocal : mât à y 0,21-0,29 → mât à x ≥ 1,207 (règle vérifiée, pas un
    simple réglage) ; pesée à l'arrêt seulement (après 0,3 s, moyenne sur 0,5 s).
  - Proposé (réglages `exemple: true`) : tolérance 290-310 g (hors plage : retour au fût, revider ou 2e prise) ;
    vitesse d'ouverture, attente 1,5 s ; fin = poids revenu à la tare « godet vide » ± 10 g, stable 0,5 s ; dose
    versée enregistrée pour le bocal ; fermeture du godet seulement après une remontée de 2 cm.
  - Ce qui peut mal tourner (fiche § 3) : grains collés (secousses 15°↔25°, puis 35°, puis alerte, griffe immobile,
    jamais refermer au-dessus du bocal) ; entonnoir bouché (capteur de distance de la tête : surface plus haute
    que l'entonnoir vide moins un seuil → bocal « suspect », alerte, rien d'automatique) ; godet vide → nouvelle
    prise ; pesée instable (3 essais puis alerte).
  - Jamais de versement si `entonnoir_place` n'est pas ce bocal (`Entonnoir.refus_versement` existe déjà).
  - Vide (cases gardées réglables, EXEMPLE) : seuil du capteur de distance, tare « godet vide » (à mesurer à la mise
    en service et après chaque lavage : prévoir une étape de tare, pas un chiffre figé).
  Procédure d'essai sur le vrai matériel avec du maïs chaud ; « testé sur le vrai matériel : non ».
- [ ] 44. App « machine » dans le logiciel de culture (avec l'accord de Karulium)
