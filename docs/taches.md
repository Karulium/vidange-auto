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
  levée, repère et bac des couvercles). Règles à recopier quand les premières photos existeront.
- [x] **22 bis. Cartes de pesée RS485 (RP2040 + HX711) : griffe, préhension, plateau du remplissage** — Modèle : Opus.
  Programme C (Pico SDK, comme l'accéléromètre) : lecture du HX711 en 3,3 V, jusqu'à 80 mesures/s, réponse sur le
  bus RS485 `rs485_pesee` quand le Pi l'interroge (une adresse par carte, contrôle CRC), mise à jour depuis le Pi
  si c'est simple. Côté Pi : lecture des 3 cartes à tour de rôle, 115 200 bauds, adaptateur USB-RS485 reconnu par
  son numéro de série. Procédure d'essai à l'établi ; « testé sur le vrai matériel : non ».
- [ ] 23. Solveur d'ordonnancement (OR-Tools) et vérification d'un programme avant envoi

## Partie 3 : fonctions en plus, voir `docs/fonctionnalites.md`

- [ ] 24. Dérive de position : consigne contre pilotes boucle fermée (15). — Sonnet.
- [ ] 25. Comptes (58) et restauration d'un Pi neuf depuis la sauvegarde (79). — Sonnet.
- [ ] 26. Entretien : compteurs par axe, calendrier, pièces d'usure, page maintenance (40 à 44). — Sonnet.
- [ ] 27. Notifications sur le téléphone (ntfy), résumé du soir, escalade (60 à 63). — Sonnet.
- [ ] 28. Page web : vue 3D en direct et rejeu d'incident (54, 55), statistiques (57), appli installable (59),
  réglages avec garde-fous (56), carnet de bord (86). — Sonnet.
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
- [ ] **35. Stockage : places, inventaire, prise sur les piles, rangement dans le tiroir** — Modèle : Opus, effort
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
    Seau C : files en quinconce avec une cale de 15 cm, **16 par lot**. Capacité d'un lot : **14 (A, B, D) ou 16 (C)**.
    Le plateau du haut ne reçoit **aucun** seau plein (personne ne peut les y poser).
  - Rangement seulement boucle fermée (tiroir rentré et verrouillé). Oreilles de l'anse à 45° des files.
  - **Tiroir plein** avant la fin du fût : le Pi met le cycle en **pause** (substrat restant noté), invite à vider le
    tiroir, attend la boucle fermée, repart avec les files vides (choix recommandé à Karulium le 31/10 : à recopier
    dans `docs/decisions.md` avec sa réponse). Fin de lot : pareil, puis lot suivant.
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
  pause « tiroir plein », boucle ouverte puis refermée, reprise. Tests : nombre par pile pour A à D, cote du bord
  pour chaque k, ordre de vidage, capacité des files (C en quinconce), file 0,785 refusée sans chariot du fût, boucle
  ouverte ⇒ rien ne bouge, coin d'inspection plein, trajets refusés (boîtes, caméra du bocal, pile pleine).
  « Testé sur le vrai matériel : non » ; procédure d'essai (boucle des microrupteurs, cotes des piles, tiroir).
- [ ] 36. Portique
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
- [ ] 38. Nettoyage
- [ ] **38 bis. Capteurs d'ozone Winsen ZE25-O3 en UART (ozone_1 et ozone_2)** — Modèle : Sonnet, effort moyen.
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
- [ ] 39. Spray (et le programme de sa carte ESP32)
- [ ] 40. Micropore
- [ ] 41. Fermeture des seaux
- [ ] 42. Air comprimé
- [ ] 43. Entonnoir
- [ ] 44. App « machine » dans le logiciel de culture (avec l'accord de Karulium)
