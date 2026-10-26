# Réglages des cartes ESP32 FluidNC

FluidNC est un programme déjà fait : on n'écrit ici que ses fichiers de réglages, un par carte.
4 cartes « 6 axes à pilotes externes », reliées au Pi par USB : portique, chariot, mycélium/lavage, préhension.
Les fichiers de réglages des cartes arrivent avec les tâches des modules (voir `docs/taches.md`).

Côté Pi, la liaison avec ces cartes est dans `pi/vidange/fluidnc/` ; chaque carte y est reconnue par le numéro
de série de son USB, écrit dans `pi/reglages/fluidnc.yaml`.
Essai de la liaison sur une vraie carte, pas à pas : [`essai-liaison.md`](essai-liaison.md).
