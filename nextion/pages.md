# Pages de l'écran Nextion (porte de l'armoire)

Écran : NX4827P043-011C, 4,3 pouces, **480 × 272 points**, posé à l'horizontale.
Ce fichier dit comment monter le projet dans **Nextion Editor** (gratuit, Windows).
Le Pi fait tout le reste : il choisit la page, écrit les textes et met les couleurs.
Dans l'éditeur, on ne dessine donc que des cases vides avec le bon **nom**.

Ce qui compte vraiment :

1. le **nom** de chaque page et de chaque objet (exactement comme ici, en minuscules) ;
2. l'**ordre** des pages (numéro 0 à 5) ;
3. le **code** de chaque bouton (deux lignes, plus bas) ;
4. **txt_maxl** (nombre de caractères) au moins égal à celui du tableau.

Les positions et les tailles sont une proposition : tu peux les ajuster à l'œil.
Le programme du Pi vérifie le reste (un test compare ce fichier avec `pi/vidange/ecran/pages.py`).

## Avant de commencer : le projet

- **Nouveau projet** : modèle NX4827P043_011 (série Intelligent), sens horizontal (90° ou 0°),
  codage des caractères **iso-8859-1** (pour les accents français).
- **Polices** (menu Outils → Générateur de polices, codage **iso-8859-1**, une police par taille,
  ajoutées dans cet ordre) :
  - police 0 : hauteur **20** (textes) ;
  - police 1 : hauteur **24** (boutons ordinaires) ;
  - police 2 : hauteur **32**, en gras si possible (bandeau, GO, OUI, NON).
- **Program.s** (onglet du programme de démarrage) : garder les lignes du projet neuf, en vérifiant :
  - `baud=115200` (la même vitesse que `vitesse_bauds` dans `pi/reglages/programme.yaml`) ;
  - `recmod=0` (l'écran comprend les ordres du Pi) ;
  - `printh 00 00 00 ff ff ff 88 ff ff ff` (l'écran dit au Pi qu'il vient de démarrer) ;
  - `page 0`.
- **Fond de chaque page** : blanc. Textes : fond blanc, écriture noire, sauf ce que le Pi colore.
- Pour chaque **texte** sur 2 lignes ou plus : `isbr` = 1 (retour à la ligne automatique).
- Pour chaque **bouton** : décocher « Send Component ID » (dans Touch Press et Touch Release).

## Le code de chaque bouton

Dans l'onglet **Touch Release Event** du bouton, écrire ces deux lignes, en remplaçant le nom
par celui du bouton (exemple pour `b_go`) :

```
prints "@b_go",0
printh FF FF FF
```

Le bouton envoie alors son nom au Pi quand on le relâche. Il ne change **jamais** de page
lui-même : c'est le Pi qui décide. Le code exact de chaque bouton est rappelé sous chaque page.

## Le code couleur (fonction 47)

Le Pi colore le bandeau du haut et certains boutons (réglable dans `programme.yaml`, partie
`ecran` → `couleurs`) :

| Couleur | Veut dire |
|---|---|
| vert | la machine travaille (et bouton « Oui », « Réparé », « Reprendre ») |
| jaune | elle attend ton Go (bouton GO actif, question « À confirmer ») |
| orange | en pause (et bouton « Pause ») |
| rouge | alarme |
| gris foncé | rien en cours |
| bleu | mode lavage ou UV-ozone ; mode choisi |
| violet | pilotage à distance en cours (bandeau) |
| gris clair | bouton ordinaire |
| gris pâle, écriture grise | bouton sans effet pour l'instant (GO sans Go attendu...) |

Les boutons mesurent au moins 114 × 84 points (environ 23 × 17 mm) : on les touche avec des gants
(fonction 46). Si un mot ne tient pas dans son bouton, prendre la police juste en dessous.

## Page 0 : « etat »

La page d'accueil. Le bandeau dit l'état de la machine dans sa couleur ; dessous, le mode, le module
en cours, ce qu'il attend, et les messages de l'écran (« Aucun Go attendu »...).

| Nom | Sorte | x | y | Largeur | Hauteur | Police | txt_maxl |
|---|---|---|---|---|---|---|---|
| `b_bandeau` | Bouton | 0 | 0 | 480 | 44 | 2 | 30 |
| `t_mode` | Texte | 4 | 46 | 472 | 24 | 0 | 40 |
| `t_module` | Texte | 4 | 70 | 472 | 44 | 0 | 80 |
| `t_attend` | Texte | 4 | 114 | 472 | 22 | 0 | 40 |
| `t_info` | Texte | 4 | 136 | 472 | 44 | 0 | 80 |
| `b_pause` | Bouton | 4 | 182 | 114 | 86 | 1 | 10 |
| `b_go` | Bouton | 122 | 182 | 114 | 86 | 2 | 10 |
| `b_compteurs` | Bouton | 240 | 182 | 114 | 86 | 1 | 10 |
| `b_mode` | Bouton | 358 | 182 | 118 | 86 | 1 | 10 |

- `b_bandeau` : « EN MARCHE » (vert), « ATTEND LE GO » (jaune), « EN PAUSE » (orange),
  « ALARME (2) : TOUCHER ICI » (rouge), « À L'ARRÊT » (gris), « À DISTANCE : TOUCHER = STOP » (violet,
  pendant un pilotage à distance). Le toucher montre les alarmes.
  Pendant un pilotage à distance, **n'importe quel bouton** de l'écran l'arrête (et ne fait rien d'autre) :
  la main est toujours à l'armoire.
  Texte centré.
- `t_module` (2 lignes) : « lieu sur, étape 1/3 : aller ».
- `b_pause` : « PAUSE » (tout de suite) ou « REPRENDRE » (demande « Oui »).
- `b_go` : donne le Go au module qui l'attend, après « Oui ».

Code des boutons :

```
prints "@b_bandeau",0
prints "@b_pause",0
prints "@b_go",0
prints "@b_compteurs",0
prints "@b_mode",0
```

(chacun suivi de `printh FF FF FF`).

## Page 1 : « alarme »

Arrive toute seule à chaque nouvelle alarme (fonction 48). Elle ne s'en va pas toute seule.

| Nom | Sorte | x | y | Largeur | Hauteur | Police | txt_maxl |
|---|---|---|---|---|---|---|---|
| `t_bandeau` | Texte | 0 | 0 | 480 | 44 | 2 | 30 |
| `t_message` | Texte | 4 | 46 | 472 | 44 | 0 | 80 |
| `t_quoi` | Texte | 4 | 92 | 472 | 50 | 0 | 80 |
| `t_suite` | Texte | 4 | 150 | 472 | 26 | 0 | 40 |
| `b_retour` | Bouton | 4 | 182 | 114 | 86 | 1 | 10 |
| `b_suite` | Bouton | 122 | 182 | 114 | 86 | 1 | 10 |
| `b_suivante` | Bouton | 240 | 182 | 114 | 86 | 1 | 10 |
| `b_repare` | Bouton | 358 | 182 | 118 | 86 | 1 | 10 |

- `t_bandeau` (rouge, centré) : « ALARME 1/2 : portique ».
- `t_message` (2 lignes) : ce qui s'est passé.
- `t_quoi` (2 lignes, écriture en gras ou en couleur foncée si tu veux) : quoi faire.
  Un texte plus long est coupé en morceaux : `b_suite` montre le morceau suivant.
- `t_suite` : « Suite 1/3, le 26/10 à 10:32 », ou un message de l'écran.
- `b_suivante` : l'alarme suivante, s'il y en a plusieurs.
- `b_repare` : « RÉPARÉ » : l'alarme est acquittée (notée au registre « par l'écran de l'armoire ») ;
  le module refera son étape après un nouveau Go.
- `b_retour` : revient à la page « etat ».

Code des boutons :

```
prints "@b_retour",0
prints "@b_suite",0
prints "@b_suivante",0
prints "@b_repare",0
```

(chacun suivi de `printh FF FF FF`).

## Page 2 : « compteurs »

Revient seule à la page « etat » au bout d'une minute sans appui (`retour_accueil_s`).

| Nom | Sorte | x | y | Largeur | Hauteur | Police | txt_maxl |
|---|---|---|---|---|---|---|---|
| `t_titre` | Texte | 0 | 0 | 480 | 44 | 2 | 30 |
| `t_seaux_jour` | Texte | 4 | 50 | 472 | 30 | 1 | 40 |
| `t_futs_jour` | Texte | 4 | 82 | 472 | 30 | 1 | 40 |
| `t_seaux_fut` | Texte | 4 | 114 | 472 | 30 | 1 | 40 |
| `t_alarmes_jour` | Texte | 4 | 146 | 472 | 30 | 1 | 40 |
| `b_retour` | Bouton | 4 | 182 | 472 | 86 | 2 | 10 |

Textes : « Seaux remplis aujourd'hui : 12 », « Fûts vidés aujourd'hui : 1 »,
« Seaux du fût en cours : 5 », « Alarmes aujourd'hui : 0 ».

Code du bouton :

```
prints "@b_retour",0
```

(suivi de `printh FF FF FF`).

## Page 3 : « mode »

Production, lavage ou UV-ozone. Le changement demande « Oui », et il est refusé pendant un cycle.
Revient seule à la page « etat » au bout d'une minute sans appui.

| Nom | Sorte | x | y | Largeur | Hauteur | Police | txt_maxl |
|---|---|---|---|---|---|---|---|
| `t_titre` | Texte | 0 | 0 | 480 | 44 | 2 | 30 |
| `t_info` | Texte | 4 | 46 | 472 | 44 | 0 | 80 |
| `b_production` | Bouton | 4 | 94 | 154 | 84 | 1 | 10 |
| `b_lavage` | Bouton | 163 | 94 | 154 | 84 | 1 | 10 |
| `b_uv_ozone` | Bouton | 322 | 94 | 154 | 84 | 1 | 10 |
| `b_retour` | Bouton | 4 | 182 | 472 | 86 | 2 | 10 |

- `t_titre` (bleu) : « MODE : PRODUCTION ».
- `t_info` (2 lignes) : « Impossible : pas pendant un cycle (lieu_sur). »
- Le bouton du mode actuel est en bleu.

Code des boutons :

```
prints "@b_production",0
prints "@b_lavage",0
prints "@b_uv_ozone",0
prints "@b_retour",0
```

(chacun suivi de `printh FF FF FF`).

## Page 4 : « confirmer »

La question avant un Go, une reprise ou un changement de mode : un appui de travers avec des gants
ne fait rien bouger. Sans réponse au bout de 15 s (`confirmation_s`), la question est abandonnée.

| Nom | Sorte | x | y | Largeur | Hauteur | Police | txt_maxl |
|---|---|---|---|---|---|---|---|
| `t_titre` | Texte | 0 | 0 | 480 | 44 | 2 | 30 |
| `t_question` | Texte | 4 | 50 | 472 | 126 | 1 | 120 |
| `b_non` | Bouton | 4 | 182 | 234 | 86 | 2 | 10 |
| `b_oui` | Bouton | 242 | 182 | 234 | 86 | 2 | 10 |

- `t_titre` (jaune) : « À CONFIRMER ».
- `t_question` (plusieurs lignes) : « Donner le Go à « lieu sur » pour l'étape « aller » ? »
- `b_non` (gris) à gauche, `b_oui` (vert) à droite, bien écartés.

Code des boutons :

```
prints "@b_non",0
prints "@b_oui",0
```

(chacun suivi de `printh FF FF FF`).

## Page 5 : « poste_fut »

Le poste du fût (tâches 17 et 17 bis). Arrive toute seule quand le plateau du fût arrive au fond
(depuis la page « etat »), et repart seule quand le poste est prêt ou que le plateau s'en va. Elle
dit le poids (ou « pesée absente »), l'accu et la radio du plateau, rappelle les gestes à faire à
la main (rien n'est vérifié par un capteur, sauf le plateau et le panneau), puis dit ce qui manque
pour « Prêt » (la pesée n'y entre pas).

| Nom | Sorte | x | y | Largeur | Hauteur | Police | txt_maxl |
|---|---|---|---|---|---|---|---|
| `t_titre` | Texte | 0 | 0 | 480 | 44 | 2 | 30 |
| `t_poids` | Texte | 4 | 46 | 472 | 22 | 0 | 60 |
| `t_gestes` | Texte | 4 | 68 | 472 | 44 | 0 | 100 |
| `t_manque` | Texte | 4 | 112 | 472 | 66 | 0 | 140 |
| `b_pret` | Bouton | 4 | 182 | 234 | 86 | 2 | 10 |
| `b_retour` | Bouton | 242 | 182 | 234 | 86 | 2 | 10 |

- `t_titre` : « PLATEAU ABSENT » (gris), « EN PLACE, PAS PRÊT » (jaune), « PRÊT » (vert). Texte centré.
- `t_poids` : « Substrat : 105,6 kg · accu 80 % · radio -60 dBm », ou « Pesée absente : radio du
  plateau muette » ; « accu 18 % : RECHARGER » quand l'accu est faible.
- `t_gestes` (2 lignes) : « À la main : fût sur les cales, soupape enlevée, butées du fond, 2 freins,
  volet rabattu, panneau levé. »
- `t_manque` (3 lignes) : ce qui manque pour « Prêt », ou la réponse au dernier appui.
- `b_pret` : « PRÊT » (vert quand l'appui est possible, gris pâle sinon). Fait comme le bouton
  lumineux du poste et le bouton de la page web.

Code des boutons :

```
prints "@b_pret",0
prints "@b_retour",0
```

(chacun suivi de `printh FF FF FF`).

## Envoyer le projet dans l'écran

1. Dans Nextion Editor : **Compile**, puis **File → TFT file output** : un fichier `.tft`.
2. Copier ce fichier seul sur une carte micro-SD (FAT32), écran éteint, carte dans l'écran.
3. Allumer : l'écran se met à jour (barre de progression), puis l'éteindre, retirer la carte, rallumer.

L'essai avec le Pi est dans `pi/systeme/essai-ecran.md`.
