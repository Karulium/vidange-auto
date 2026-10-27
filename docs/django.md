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

Dépôt GitHub privé **`Karulium/Karulium`**. Les sessions de ce dépôt-ci ne le lisent pas et n'y écrivent
jamais : ce qu'il faut en savoir est résumé ci-dessous (lu le 27/10/2026, commit `5004613`). L'app « machine »
ne sera écrite dans ce dépôt-là qu'avec l'accord de Karulium.

## Ce que contient le logiciel de culture (résumé)

- **Django 5.2**, **Django REST Framework 3.16** (authentification par jeton `TokenAuthentication` et par
  session), base **MySQL**, Celery + Redis, Channels. Heure : `America/Guadeloupe`, `USE_TZ = False` (dates
  « naïves », en heure locale) : le Pi envoie donc ses dates en heure locale de Guadeloupe.
- Attention : `DEFAULT_PERMISSION_CLASSES` est vide (tout est permis par défaut). Les vues de l'app « machine »
  devront exiger le jeton elles-mêmes (`permission_classes = [IsAuthenticated]`).
- Des API existent déjà (app `Blocs` : scan de position, notation des blocs…), sur le même modèle (`APIView`).

Tables utiles à la machine (nom de l'app · nom du modèle) :

| Modèle | Ce que c'est | Champs utiles |
|---|---|---|
| `Objets · Contenants_culture` (polymorphe) | un contenant physique réutilisable | `identifiant` ; affiché « S… » pour un seau, « B… » pour un bocal |
| `Objets · Seaux` | un seau physique | `type` : 0 Transparent 10 L, 1 Opaque 10 L, 2 Petit 5 L ; `date_achat`, `date_fin` |
| `Blocs · Blocs` | **une culture dans un seau** (un seau physique sert à plusieurs blocs successifs) | `contenant`, `date_fin`, photos, remarques, contaminations, positions, notations |
| `Semences · Semences` (polymorphe) | une semence : `Bocaux`, `Petris`, `Seringues`, `Slants`, `Erlenmeyers` | `identifiant`, `espece`, `recette`, `source` (semence mère), `date_inoculation`, `date_fin`, contaminations |
| `Semences · Bocaux` | un bocal de semence | + `date_colonisation`, `colonisation` |
| `Semences · Lot_inoculation` | **la table pivot** : des semences versées dans des blocs | `date`, `recette`, `semences` (plusieurs), `Blocs` (plusieurs, B majuscule), `quantite_semences` (g) |
| `Traitements · Traitements` (polymorphe) | un traitement (`Thermiques` = pasteurisation, `Lavage`, `Trempage`…) | `semences`, `blocs`, `recettes` (plusieurs) |
| `Mesures · Mesures` (polymorphe) | une mesure datée d'un instrument | `mesure`, `date`, `instrument` |
| `Features · Images`, `Remarques` | photos et remarques, accrochées à n'importe quel objet | |

Règle déjà présente : un lot d'inoculation ne contient qu'**une espèce** (sinon il affiche « Problème ! »). C'est
la même règle que la machine (un seau ne reçoit jamais deux variétés).

## Comment un cycle de la machine se range dans ces tables (proposition pour l'app « machine »)

- Chaque seau rempli = un **nouveau `Blocs`** dont le `contenant` est le seau lu par son QR.
- Les bocaux versés et les seaux remplis d'un même lot vont dans un **`Lot_inoculation`** (date, recette,
  semences, blocs, quantité totale). La table `doses_mycelium` du Pi donne le détail par seau ; un bocal peut
  servir à deux petits seaux, ce que le lot sait déjà représenter.
- Le fût vidé correspond au **traitement thermique** (pasteurisation) de son substrat : les nouveaux blocs y
  sont ajoutés.
- Les photos choisies vont dans `Images`, les poids et durées dans des mesures ou dans les tables propres à
  l'app « machine » ; le cycle complet (alarmes, durées) reste dans l'app « machine ».

## Points encore ouverts (ne bloquent pas la tâche 10)

1. Le contenu exact du QR collé sur un seau et sur un bocal (l'`identifiant` seul, ou « S » / « B » devant) :
   à vérifier sur une étiquette réelle.
2. Les formats de seaux de la machine (A Superlift, B 5 L, C large, D) ne correspondent pas un à un aux types
   du logiciel de culture (Transparent 10 L, Opaque 10 L, Petit 5 L) : la correspondance ira dans les réglages
   du Pi quand l'app « machine » sera écrite.
