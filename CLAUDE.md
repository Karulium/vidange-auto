# Consignes pour toutes les sessions de ce dépôt

Ce dépôt contient le logiciel de la machine « Vidange automatique » de Karulium :
une machine qui vide un fût de substrat dans des seaux, ajoute le mycélium,
lave et range, en Guadeloupe. La mécanique est conçue ailleurs (projet Claude
« Vidange automatique ») ; ici, on ne fait que le logiciel.

## Parler à Karulium

- **Toujours en français**, avec des mots simples. Il n'est pas informaticien.
- Donner des avis honnêtes. S'il y a un vrai choix à faire, expliquer les termes,
  donner les options (avantages, inconvénients, coût) et une recommandation.
- Les questions techniques que tu peux trancher, tranche-les toi-même et explique
  ton choix dans la PR.

## Règle n° 1 : dépenser le moins de crédits possible

- Fais **une seule tâche** de `docs/taches.md` par session, rien de plus.
- Ne relis pas tout le dépôt : lis ce fichier, `docs/architecture.md`,
  `docs/decisions.md`, puis seulement les fichiers de ta tâche.
- Ne réécris pas une partie qui marche et qui n'est pas dans ta tâche.
- Si la tâche est floue ou trop grosse, arrête-toi et pose la question dans la PR
  au lieu de deviner longtemps.
- Tu ne peux pas joindre le projet Claude où la mécanique se décide. Tes questions vont dans la
  description de la PR, sous un titre « Questions pour Karulium », numérotées, chacune avec ta
  recommandation. Continue le reste de la tâche avec ta recommandation en attendant.

## Façon de travailler sur GitHub

- `main` = ce que Karulium a accepté. On ne pousse jamais directement sur `main`.
- Une tâche = une branche = une PR. Nom de branche : `tache-<numéro>-<mot>`
  (exemple : `tache-03-fluidnc`).
- La description de la PR, en français simple, dit : ce que la tâche apporte,
  comment c'est testé, les choix faits, et ce qui reste à faire.
- Une PR doit avoir ses tests au vert (GitHub Actions) avant d'être proposée.
- À la fin de la tâche, coche-la dans `docs/taches.md` dans la même PR.
- Ne touche **jamais** au dépôt du logiciel de culture de Karulium (Django).
  Ici, on écrit seulement ce dont il aura besoin (`docs/django.md`).

## Règles du code

1. **La sécurité n'est jamais dans le logiciel.** Arrêt d'urgence, portes,
   fins de course de sécurité, freins, choc : tout est câblé en dur (relais de
   sécurité). Le logiciel peut planter sans danger. Il lit ces signaux pour
   informer et pour attendre, jamais pour protéger.
2. **Aucun chiffre de la machine dans le code.** Positions, courses, vitesses,
   durées, zones, poids, broches : tout est dans les fichiers de réglages
   (`pi/reglages/`, `fluidnc/`, `docs/entrees-sorties.yaml`). Le code dit
   « fin de course stockage haut », jamais « broche 17 ».
3. **Les réglages sont vérifiés au démarrage** : une erreur (course plus longue
   que le rail, zone qui se chevauche, broche en double) empêche de démarrer et
   dit clairement laquelle.
4. **Le Pi 5 est le seul chef.** Les PC de Karulium (bureau, serveur de culture,
   maison) ne sont jamais dans la boucle de commande. La machine doit tourner
   sans réseau ; ce qui doit partir ailleurs attend dans une file.
5. **Tout se teste sans la machine** : chaque partie a des tests, et le
   simulateur (faux FluidNC, faux capteurs) permet de rejouer un cycle.
6. Le Pi **propose** les travaux décidés par la vision et attend le « Go » de
   Karulium (règle validée), sauf ce qui est écrit autrement dans `docs/decisions.md`.
7. Noms du code en français simple sans accents (`seau`, `fut`, `griffe`), pour
   que Karulium s'y retrouve ; commentaires et docs en français.
8. Python 3.11 sur le Pi (Raspberry Pi OS Bookworm). Peu de bibliothèques, connues
   et gratuites. Pas de ROS.

## Ce que tu ne sais pas

La mécanique de certains modules n'est pas encore figée (voir `docs/decisions.md`).
Pour eux, on prépare seulement une « case vide » : ne pas inventer leurs gestes.
