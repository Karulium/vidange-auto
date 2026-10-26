# Liste des tâches

Une tâche = une session sur claude.ai/code = une PR. On les fait dans l'ordre.

**Phrase à copier pour lancer une tâche** (remplacer N) :

> Lis CLAUDE.md, puis fais la tâche N de docs/taches.md, et seulement celle-là. Ouvre une PR à la fin.

« Modèle » = celui à choisir au lancement de la session, pour dépenser le moins possible.
Opus pour poser les bases ; Sonnet pour le reste.

## Partie 1 : la base, qui ne dépend pas de la mécanique (avant le 4/11 si possible)

- [ ] **1. Squelette du programme du Pi** — Modèle : Opus.
  Paquet Python `pi/vidange/` (Python 3.11), gestion des dépendances (`pyproject.toml`), tests (pytest),
  vérification du style (ruff), et GitHub Actions qui lance tout à chaque PR.
  Chargement et vérification des fichiers de réglages (`pi/reglages/*.yaml`) avec un exemple
  (pydantic) : une erreur arrête le démarrage avec un message clair en français.
  Journal (logs) commun. Pas encore de logique de machine.

- [ ] **2. Liste des entrées/sorties** — Modèle : Sonnet.
  Format de `docs/entrees-sorties.yaml` (nom, carte, broche, type : contact / PNP / NPN / mesure / I2C / série,
  tension, sens au repos, module) et un vérificateur lancé par les tests : broche en double, carte inconnue,
  trop d'entrées sur une carte, tension 24 V sans isolement. Le contenu sera rempli depuis le projet :
  mettre seulement quelques lignes d'exemple marquées « exemple ».

- [ ] **3. Liaison FluidNC + faux FluidNC** — Modèle : Sonnet.
  Client série vers une carte FluidNC : envoi de G-code avec contrôle de flux, lecture de l'état (`?`),
  positions, alarmes, déblocage, reprise après coupure du câble. Un faux FluidNC pour les tests
  (positions qui avancent selon la vitesse, alarmes simulables).

- [ ] **4. Chef d'orchestre** — Modèle : Opus.
  Moteur d'étapes : un module = une liste d'étapes avec conditions d'entrée, action, condition de fin, délai maximal.
  Zones réservées entre axes (une zone tenue par un axe est interdite aux autres), pause, reprise,
  alarme avec message « quoi faire », attente du « Go » de Karulium. Un module d'exemple qui tourne sur le faux FluidNC.

- [ ] **5. Registre SQLite** — Modèle : Sonnet.
  Tables : fûts, seaux, bocaux, cycles, étapes faites (avec durées), mesures, photos, alarmes, réglages appliqués
  (ancien / nouveau / qui / quand). Montées de version de la base. Copie de secours quotidienne.

- [ ] **6. API du Pi et page web locale** — Modèle : Sonnet.
  API (FastAPI) sur le réseau local, protégée par une clé : état, alarmes, Go, Pause, historique, photos.
  Page web simple en français, lisible sur téléphone.

- [ ] **7. Écran Nextion, côté Pi** — Modèle : Sonnet.
  Protocole série Nextion (envoi de valeurs, lecture des appuis). Pages : état, alarme + quoi faire, Pause, Go,
  compteurs, mode (production / lavage / UV-ozone). Écrire dans `nextion/pages.md` la description de chaque page,
  bouton par bouton (nom, position, taille), pour que Karulium la monte dans Nextion Editor.

- [ ] **8. File d'envoi vers l'extérieur** — Modèle : Sonnet.
  File durable (dans SQLite) avec reprise, pour le logiciel de culture et la copie de secours.
  Écrire dans `docs/django.md` le format exact des données d'un cycle que l'app « machine » recevra.
  Ne pas toucher au dépôt Django.

- [ ] **9. Simulateur de cycle (jumeau, version 0)** — Modèle : Sonnet.
  Rejouer un cycle complet du module d'exemple avec des durées réglables, sortir le planning (qui fait quoi, quand)
  et le temps total. Préparer la place pour le solveur OR-Tools (tâche plus tard).

- [ ] **10. Programme de l'accéléromètre (RP2040 + LIS3DH)** — Modèle : Sonnet.
  Seuil de choc réglable, sortie « OK » en sécurité positive (coupée sur choc ou panne), envoi des mesures et réception des réglages
  sur une liaison série half-duplex à un seul fil (PIO), chargeur série pour les mises à jour (voir `docs/decisions.md`).
  Côté Pi : lecture et enregistrement des chocs.

- [ ] **11. Accès à distance : vidéos et pilotage manuel** — Modèle : Opus.
  Suivre `docs/decisions.md` (partie « Accès à distance »). Vidéo en direct des caméras sur la page web,
  clips d'incidents, mode à distance avec homme mort, vitesse réduite, arrêt si connexion perdue ou vidéo figée,
  priorité à l'armoire, journal des actions. Tests avec le faux FluidNC (coupure de connexion simulée).

- [ ] **12. Mises à jour des cartes et du Pi** — Modèle : Sonnet.
  Mise à jour des ESP32 par USB depuis le Pi (esptool), envoi des réglages FluidNC, retour à l'ancienne version,
  vérification après mise à jour ; RP2040 par sa liaison série half-duplex (chargeur série) ; mise à jour du programme du Pi depuis `main`.
  Seulement machine à l'arrêt. Lancement depuis la page web.

## Partie 2 : les modules figés (après la partie 1)

Avant chaque tâche, le projet recopie ici les gestes, positions et règles du module.

- [ ] 13. Poste du fût
- [ ] 14. Griffe (transfert fût vers seau)
- [ ] 15. Mycélium (dosage)
- [ ] 16. Porte-bocal
- [ ] 17. Lavage
- [ ] 18. Vision : caméra du plafond (9 règles), caméra de tête, QR, caméra du dosage
- [ ] 19. Solveur d'ordonnancement (OR-Tools) et vérification d'un programme avant envoi

## Partie 4 : fonctions en plus (après la base), voir `docs/fonctionnalites.md`

- [ ] 20. Fiabilité : chien de garde Pi ↔ cartes (14), dérive de position (15), bilan et « quoi faire » des alarmes (17, 18),
  check-list de démarrage (12), reprise après coupure et onduleur (3, 4), santé de l'informatique (45). — Sonnet.
- [ ] 21. Entretien : compteurs par axe, calendrier, pièces d'usure, page maintenance (40, 41, 43, 44). — Sonnet.
- [ ] 22. Notifications sur le téléphone (ntfy), résumé du soir, escalade (60 à 63). — Sonnet.
- [ ] 23. Page web : vue 3D en direct et rejeu d'incident (54, 55), statistiques (57), appli installable (59),
  réglages avec garde-fous (56), carnet de bord (86). — Sonnet.
- [ ] 24. Écran : code pour les fonctions sensibles (50), voyant et buzzer (49). — Sonnet.
- [ ] 25. Estimation de fin qui apprend (7), montée en vitesse réglable (69), essai d'un réglage dans le simulateur (68). — Sonnet.
- [ ] 26. Plans d'expériences : application d'un plan d'essais accepté par Karulium, seau par seau (6, 76). — Opus.
- [ ] 27. Assistant en français, écoute des bruits, résumé de la semaine (71, 73, 74). — plus tard.
- [ ] 28. Mode guidé pour un employé et manuel tenu à jour (84, 85). — Sonnet.

## Partie 3 : les autres modules, au fil des gels

Remplissage, Stockage, Portique, Préhension, Nettoyage, Spray (et son programme ESP32), Micropore,
Fermeture des seaux, Air comprimé, Entonnoir. Puis l'app « machine » dans le logiciel de culture,
avec l'accord de Karulium.
