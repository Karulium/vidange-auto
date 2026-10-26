# Lien avec le logiciel de culture (Django)

Le logiciel de suivi des cultures de Karulium tourne sur un serveur Intel N97 (16 Go, toujours allumé),
dans un autre conteneur, joignable par le réseau local (câble ou wifi). Il est déjà chargé (swap utilisé) :
aucun calcul lourd dessus.

Sa base (apps) : Especes, Semences, Recettes, Traitements, Blocs, Recoltes, Mesures, Contaminations, Images ;
le lot d'inoculation est la table pivot.

**Explication complète de la base, écrite par Karulium : `docs/base-culture.md`** (ce que chaque table représente
dans le travail réel, comment elles sont reliées). La lire avant toute tâche qui touche au lien avec la culture,
aux données collectées (Pétri, bocaux, seaux) ou aux plans d'expériences.

## Principe

- La machine ne dépend jamais de ce logiciel pour tourner. Le Pi met chaque envoi dans une file et réessaie.
- Le lien se fait par le QR : le code d'un seau ou d'un bocal renvoie au lot d'inoculation existant.
- Dans le logiciel de culture, on ajoutera plus tard une app « machine » qui reçoit les cycles
  (fût, seaux, poids, dose de mycélium, durées, photos choisies, alarmes). Rien de l'existant n'est cassé.
- Dans l'autre sens, le Pi peut demander la recette ou le lot prévu (souche, dose).
- Liaison : API web interne protégée par une clé, réseau local seulement.

## Où est le code

Dépôt GitHub privé **`Karulium/Karulium`** (Karulium, 26/10/2026). Les sessions de ce dépôt ne le lisent
pas et n'y écrivent jamais : ce qu'il faut en savoir (version de Django, Django REST Framework, tables,
lots d'inoculation, QR) sera recopié ici avant la tâche 10.
