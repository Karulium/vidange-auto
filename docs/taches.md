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
  axes de la tête ; mât de la griffe = pont − 0,175 en x.

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
- [ ] **19. Mycélium (dosage)** — Modèle : Opus, effort moyen.
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
- [ ] 20. Porte-bocal
- [ ] 21. Lavage
- [ ] 22. Vision : caméra du plafond (9 règles), caméra de tête, QR, caméra du dosage
- [ ] 22 bis. Cartes de pesée RS485 (RP2040 + HX711) : griffe, préhension, plateau du remplissage — Modèle : Opus.
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

Avant chaque tâche, le projet recopie ici les gestes, positions et règles du module.

- [ ] 34. Remplissage
- [ ] 35. Stockage
- [ ] 36. Portique
- [ ] 37. Préhension
- [ ] 38. Nettoyage
- [ ] 39. Spray (et le programme de sa carte ESP32)
- [ ] 40. Micropore
- [ ] 41. Fermeture des seaux
- [ ] 42. Air comprimé
- [ ] 43. Entonnoir
- [ ] 44. App « machine » dans le logiciel de culture (avec l'accord de Karulium)
