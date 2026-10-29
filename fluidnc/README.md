# Réglages des cartes ESP32 FluidNC

FluidNC est un programme déjà fait : on n'écrit ici que ses fichiers de réglages, un par carte.
4 cartes « 6 axes à pilotes externes », reliées au Pi par USB : portique, chariot, mycélium/lavage, préhension.
Les fichiers de réglages des cartes arrivent avec les tâches des modules (voir `docs/taches.md`).

Côté Pi, la liaison avec ces cartes est dans `pi/vidange/fluidnc/` ; chaque carte y est reconnue par le numéro
de série de son USB, écrit dans `pi/reglages/fluidnc.yaml`.
Essai de la liaison sur une vraie carte, pas à pas : [`essai-liaison.md`](essai-liaison.md).

Le Pi met à jour le programme et les réglages des cartes par leur câble USB (tâche 13, page web → « Mises à
jour ») : le fichier `fluidnc/<carte>.yaml` devient `config.yaml` dans la carte. Avant chaque changement, toute
la mémoire de la carte est copiée sur le Pi pour pouvoir revenir en arrière. Essai :
[`pi/systeme/essai-mises-a-jour.md`](../pi/systeme/essai-mises-a-jour.md).

**Un fichier marqué EXEMPLE n'est jamais envoyé à une carte** (tâche 19 bis) : tant que le mot `EXEMPLE`
(en majuscules) reste quelque part dans le fichier, en commentaire ou dans une valeur, l'envoi est refusé
et le message donne les lignes où il reste. Pour finir un fichier : mettre les vraies broches (plan de câblage),
les vrais pas par mm et les vitesses, puis enlever chaque mot `EXEMPLE`. Le simulateur et les tests, eux, peuvent
toujours se servir des fichiers d'exemple. (« exemple » en minuscules, comme « par exemple », ne bloque rien.)
