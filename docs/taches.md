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

- [ ] **15. Accéléromètre, partie 2 : liaison série un seul fil (PIO)** — Modèle : Opus.
  Mesures vers le Pi, réglages vers le RP2040 (half-duplex, voir `docs/decisions.md`). Côté Pi : lecture et
  enregistrement des chocs. Procédure d'essai à l'établi.

- [ ] **16. Accéléromètre, partie 3 : chargeur série et mise à jour depuis le Pi** — Modèle : Opus.
  Petit chargeur maison (le RP2040 n'en a pas d'origine), installé une fois à l'établi par USB ; mise à jour
  par la liaison un seul fil ; secours par USB-C. Procédure d'essai à l'établi.

## Partie 2 : les modules figés (après la partie 1)

Avant chaque tâche, le projet recopie ici les gestes, positions et règles du module.

- [ ] 17. Poste du fût
- [ ] 18. Griffe (transfert fût vers seau)
- [ ] 19. Mycélium (dosage)
- [ ] 20. Porte-bocal
- [ ] 21. Lavage
- [ ] 22. Vision : caméra du plafond (9 règles), caméra de tête, QR, caméra du dosage
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
