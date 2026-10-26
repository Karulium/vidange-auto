# Lien avec le logiciel de culture (Django)

Le logiciel de suivi des cultures de Karulium tourne sur un serveur Intel N97 (16 Go, toujours allumé),
dans un autre conteneur, joignable par le réseau local (câble ou wifi). Il est déjà chargé (swap utilisé) :
aucun calcul lourd dessus.

Sa base (apps) : Especes, Semences, Recettes, Traitements, Blocs, Recoltes, Mesures, Contaminations, Images ;
le lot d'inoculation est la table pivot.

## Principe

- La machine ne dépend jamais de ce logiciel pour tourner. Le Pi met chaque envoi dans une file et réessaie.
- Le lien se fait par le QR : le code d'un seau ou d'un bocal renvoie au lot d'inoculation existant.
- Dans le logiciel de culture, on ajoutera plus tard une app « machine » qui reçoit les cycles
  (fût, seaux, poids, dose de mycélium, durées, photos choisies, alarmes). Rien de l'existant n'est cassé.
- Dans l'autre sens, le Pi peut demander la recette ou le lot prévu (souche, dose).
- Liaison : API web interne protégée par une clé, réseau local seulement.

## À demander à Karulium avant d'écrire l'app « machine »

Où est le code (dépôt GitHub ?), version de Django, présence de Django REST Framework.
