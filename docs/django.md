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

## Points encore ouverts

1. Le contenu exact du QR collé sur un seau et sur un bocal (l'`identifiant` seul, ou « S » / « B » devant) :
   à vérifier sur une étiquette réelle.
2. Les formats de seaux de la machine (A Superlift, B 5 L, C large, D) ne correspondent pas un à un aux types
   du logiciel de culture (Transparent 10 L, Opaque 10 L, Petit 5 L) : la correspondance ira dans les réglages
   du Pi quand l'app « machine » sera écrite.

## Format exact d'un cycle envoyé par le Pi (tâche 10, format n° 1)

Ce que l'app « machine » recevra. Le code qui fabrique ces données est `pi/vidange/envois/cycle.py` ; un test
vérifie que l'exemple ci-dessous a exactement les mêmes champs que ce que le Pi envoie (si l'un change, l'autre
doit changer dans la même PR).

### Comment le Pi envoie

- **Quand** : chaque cycle fini (vidange d'un fût, lavage...) entre dans la **file d'envoi** du Pi (table
  `envois` du registre, dans la même écriture que la fin du cycle). Le Pi l'envoie dès que le logiciel de culture
  répond ; s'il ne répond pas, il réessaie (1 min, 2, 4... puis toutes les heures), même après une coupure de
  courant. La machine n'attend jamais cet envoi.
- **Requête** : `POST` en JSON (UTF-8) vers l'adresse réglée dans `pi/reglages/programme.yaml`
  (`envois.culture.adresse`, exemple `http://192.168.1.20:8000/machine/api/cycles/`, avec le `/` final : Django
  ne suit pas une redirection de `POST`).
- **En-têtes** : `Content-Type: application/json; charset=utf-8` et `Authorization: Token <jeton>`. Le jeton est
  celui d'un compte « machine » du logiciel de culture (Django REST Framework, `TokenAuthentication`) ; côté Pi, il
  est dans le fichier de secrets (`jeton_culture`), jamais dans Git.
- **Réponses attendues de l'app « machine »** :
  | Réponse | Ce que le Pi en fait |
  |---|---|
  | `200` ou `201` | reçu : le cycle sort de la file |
  | `400` ou `422` (avec un message en JSON) | **données refusées** : mis de côté, signalé dans la check-list ; Karulium corrige, puis `vidange-envois renvoyer <n°>` |
  | tout le reste (`401`, `403`, `404`, `500`, pas de réponse en 10 s...) | réessayé plus tard (le jeton, l'adresse ou le serveur se réparent sans toucher aux données) |
- **Le même cycle peut arriver deux fois** (coupure pendant un envoi, Pi remis en état depuis une copie, envoi
  relancé à la main) : il porte toujours la même `cle`. L'app « machine » doit le reconnaître : si la `cle` est
  déjà connue, **remplacer** le cycle reçu avant (ou ne rien faire) et répondre `200`. Ne jamais se fier au
  `numero` seul : après une remise en état du Pi, un numéro peut revenir.
- Un cycle peut être envoyé une 2ᵉ fois, plus complet (alarme acquittée entre-temps, par exemple) : c'est
  pourquoi on remplace plutôt que d'ignorer.

### Les données

```json
{
  "format": 1,
  "cle": "6f1c2a4e-0b7d-4a51-9d1e-3c8f2b7a9e10",
  "machine": "vidange-1",
  "cycle": {
    "numero": 42,
    "module": "vidange",
    "debut": "2026-10-27T08:00:00",
    "fin": "2026-10-27T08:15:00",
    "issue": "termine",
    "fut": "F3",
    "remarque": null
  },
  "seaux": [
    {
      "seau": "S1293",
      "type_seau": "opaque_10l",
      "quand": "2026-10-27T08:05:00",
      "defaut": null,
      "doses": [
        {"bocal": "B327", "quantite_g": 120.0, "couche": 1, "quand": "2026-10-27T08:05:00"},
        {"bocal": "B328", "quantite_g": null, "couche": null, "quand": "2026-10-27T08:05:30"}
      ]
    }
  ],
  "bocaux": ["B327", "B328"],
  "etapes": [
    {"etape": "descendre", "debut": "2026-10-27T08:04:48", "fin": "2026-10-27T08:05:00",
     "duree_s": 12.4, "issue": "faite"}
  ],
  "mesures": [
    {"nom": "poids_seau", "valeur": 6.2, "unite": "kg", "capteur": "balance",
     "quand": "2026-10-27T08:05:00", "fut": null, "seau": "S1293", "bocal": null, "petri": null}
  ],
  "photos": [
    {"numero": 7, "quand": "2026-10-27T08:05:10", "camera": "dosage", "fichier": "2026-10-27/dose.jpg",
     "remarque": null, "fut": null, "seau": "S1293", "bocal": "B327", "petri": null}
  ],
  "alarmes": [
    {"numero": 3, "quand": "2026-10-27T08:07:00", "module": "vidange", "etape": "descendre",
     "message": "fût coincé", "quoi_faire": "Dégager le fût.", "acquittee_le": "2026-10-27T08:09:00",
     "acquittee_par": "karulium"}
  ]
}
```

Règles communes :

- **Heures** : heure locale de Guadeloupe, **sans fuseau**, à la seconde (`2026-10-27T08:05:00`), comme le
  logiciel de culture les range (`USE_TZ = False`). Le fuseau est réglé dans `programme.yaml`
  (`envois.culture.fuseau_horaire`).
- **Codes** des fûts, seaux, bocaux et Pétri : le texte lu dans leur QR, tel quel (voir « Points encore
  ouverts », n° 1).
- Un champ sans valeur vaut `null` ; une liste vide vaut `[]`. Tous les champs sont toujours présents.
- `format` : numéro du format. Il ne change que si le format change d'une façon que l'app doit savoir ; l'app
  doit refuser (`400`) un format qu'elle ne connaît pas.

Les champs :

| Champ | Ce que c'est |
|---|---|
| `cle` | identifiant unique de l'envoi (UUID) : la clé à garder pour reconnaître un cycle déjà reçu |
| `machine` | nom de la machine (`envois.culture.machine`), s'il y en a un jour plusieurs |
| `cycle.numero` | numéro du cycle dans le registre du Pi (pour en parler, pas comme clé) |
| `cycle.module` | le module du cycle : `vidange` (un fût vidé dans des seaux), `lavage`... Seuls les cycles avec des `seaux` créent des blocs |
| `cycle.debut`, `cycle.fin` | début et fin du cycle |
| `cycle.issue` | `termine` (fini normalement) ou `abandonne` (arrêté en route : les seaux déjà remplis sont quand même listés) |
| `cycle.fut` | code du fût vidé (ou `null`) : son substrat et son traitement thermique |
| `seaux[]` | chaque seau rempli, dans l'ordre : `seau` (code du QR), `type_seau` (nom du format dans `machine.yaml`, ou `null` s'il n'est pas connu), `quand` (fin du remplissage) |
| `seaux[].defaut` | `null` si le seau est bon ; sinon, pourquoi il ne l'est pas (exemple : « poids qui ne monte plus : 40 g sur 150 g », bocal vide ou couvercle bouché ; « saut de poids pendant l'agitation », bocal cassé). L'app ne doit pas le compter comme un bloc normal (tâche 19, mycélium) |
| `seaux[].doses[]` | le mycélium versé dans ce seau : `bocal` (code du QR), `quantite_g` (grammes si pesés, sinon `null`), `couche` (numéro de la couche de substrat sur laquelle il est versé, 1 = celle du fond, ou `null`), `quand`. Plusieurs doses et plusieurs bocaux possibles ; un bocal peut servir à deux petits seaux |
| `bocaux` | les codes de tous les bocaux versés pendant le cycle, sans doublon, dans l'ordre d'usage : les `semences` du lot d'inoculation |
| `etapes[]` | chaque geste fait : `etape` (son nom), `debut`, `fin`, `duree_s` (secondes, sans les pauses), `issue` (`faite`, `alarme`, `abandonnee`) |
| `mesures[]` | chaque mesure du cycle : `nom` (exemple `poids_seau`), `valeur`, `unite` (`kg`, `g`, `°C`...), `capteur` (nom dans la liste des entrées/sorties), `quand`, et l'objet mesuré (`fut`, `seau`, `bocal` ou `petri`, les autres à `null`) |
| `photos[]` | les photos prises pendant le cycle : `numero` (sur le Pi), `quand`, `camera`, `fichier` (chemin sur le Pi, relatif au dossier des photos), `remarque`, et l'objet photographié. **Seulement leur description pour l'instant** : l'envoi des fichiers des photos choisies viendra plus tard (question n° 2 de la PR de la tâche 10) |
| `alarmes[]` | les alarmes du cycle : `numero` (sur le Pi), `quand`, `module`, `etape`, `message`, `quoi_faire`, `acquittee_le`, `acquittee_par` (`null` si pas encore acquittée) |

### Les poids du fût (tâche 17, poste du fût)

Un cycle `vidange` commence quand Karulium appuie sur « Prêt » au poste du fût. La pesée du plateau du
fût (sans fil depuis la tâche 17 bis) y ajoute ces `mesures` (`capteur` : `pesee_fut`, objet : `fut`, le
code du fût s'il est connu, sinon `null`, sauf indiqué) :

| `nom` | Ce que c'est |
|---|---|
| `poids_fut_plein` | `kg` : substrat dans le fût au « Prêt » (poids lu − tare du fût vide et de son couvercle) ; absent si la pesée était absente au « Prêt » |
| `poids_fut_restant` | `kg` : substrat encore dans le fût, après chaque dose de la griffe, et à la fin (seulement quand la pesée répond) |
| `poids_fut_vide_total` | `kg` : substrat sorti du fût pendant le cycle (plein − restant) ; absent si la pesée était absente au « Prêt » ou à la fin |
| `sans_pesee_fut` | valeur `1`, `unite` vide : **« sans pesée du fût »**. Au « Prêt » sans pesée (objet : `fut`) : le cycle a commencé sans poids du fût plein. Pendant la vidange (objet : `seau`, une ligne par seau) : ce seau a été rempli pendant que la pesée était absente ; tant que la griffe ne connaît pas le code du seau, l'objet est le `fut` et il y a une ligne par dose de la griffe |

La pesée du fût est sans fil : si sa radio se tait, la machine ne s'arrête pas (la griffe trouve le fond au
toucher), les seaux sont seulement notés `sans_pesee_fut`. L'app ne doit pas refuser un cycle sans
`poids_fut_plein`. Les alertes du poste (pesée absente, accu du plateau faible, recharge en panne) sont dans
`alarmes[]` du cycle (module `poste_fut`).

Un cycle `vidange` peut finir `abandonne` si le plateau est retiré avant la fin (fût pas vide).
L'app peut s'en servir pour le rendement d'un fût (seaux faits, poids vidé) ; rien n'est obligatoire.

### Les cycles du Nettoyage (tâche 38)

Le Pi envoie aussi des cycles `nettoyage`, **sans `seaux`** (donc sans blocs) :

- une **nuit UV-ozone** : `cycle.remarque` « nuit UV-ozone » ; `issue` `termine` (ozone revenu sous 0,1 ppm) ou
  `abandonne` (erreur : pas revenu à temps, capteur muet, mesure incohérente) ; `mesures[]` avec
  `nom` = `ozone_dedans`, `unite` = `ppm`, `capteur` = `ozone_dedans` (une valeur par minute, réglage
  `journal_s`) ; `alarmes[]` du module `nettoyage` (store ouvert pendant la nuit, erreurs) ;
- une **fuite d'ozone dehors** : un petit cycle à part, `abandonne`, avec une seule alarme « FUITE D'OZONE... »,
  envoyé tout de suite pour qu'elle arrive vite (pas à la fin de la nuit).

L'app peut les garder dans les tables de la machine (historique de désinfection de l'enceinte) et prévenir
Karulium pour une fuite ; rien n'est obligatoire.

### Ce que l'app « machine » en fera (rappel, voir plus haut)

- Chaque élément de `seaux` → un nouveau `Blocs` dont le `contenant` est le seau du QR.
- `bocaux` + les blocs créés → un `Lot_inoculation` (`date` = `cycle.fin`, `semences` = les bocaux, `Blocs` = les
  blocs, `quantite_semences` = la somme des `quantite_g` si toutes sont connues). La règle « une seule espèce par
  lot » s'applique : si les bocaux sont de deux espèces, répondre `400` avec un message clair.
- Les mesures de poids (`poids_seau`) → la première pesée de chaque bloc. Le reste (étapes, alarmes) se garde
  dans les tables de l'app « machine ».
- Un seau ou un bocal inconnu du logiciel de culture → `400` avec le code en cause (le Pi met le cycle de côté,
  Karulium corrige, puis le renvoie).
