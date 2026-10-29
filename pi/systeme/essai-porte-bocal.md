# Essai du porte-bocal (et de l'origine de la manivelle) sur le vrai matériel

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent qu'un
**faux** FluidNC, un **faux** plateau, un **faux** bocal et un **faux** capteur de manivelle.

Cette procédure se fait **avant** celle du mycélium (`essai-mycelium.md`), une fois la carte FluidNC
n° 3 câblée : glissière X, manivelle A, mors Y (TMC2209), pont en H du JGY370, électroaimant du verrou,
contact « verrou engagé », capteur d'inclinaison, capteur de la manivelle. Elle vérifie que FluidNC fait
bien ce que le Pi attend, puis mesure les chiffres marqués EXEMPLE (`pi/reglages/machine.yaml`, parties
`porte_bocal` et `mycelium → manivelle → origine` ; `fluidnc/mycelium_lavage.yaml`). Compter une
demi-journée.

La sécurité des personnes est câblée (arrêt d'urgence, portes). Les verrous du logiciel ne protègent que
la machine : garder la main sur l'arrêt d'urgence, et les doigts loin des mors et du plateau.

## Avant de commencer

- `fluidnc/mycelium_lavage.yaml` est complété avec les **vraies broches** (plan de câblage), les vrais pas
  par mm, et envoyé à la carte (page web → « Mises à jour »). Tant qu'il dit « EXEMPLE », il est refusé.
- Le programme principal est arrêté (`sudo systemctl stop vidange`) : une seule liaison par carte.
- Le chariot de remplissage est **écarté** (y ≥ 0,375) et y reste : son module n'est pas écrit, l'outil
  ne peut pas le vérifier.
- Pas de bocal pour les étapes 1 à 3.

Dans les commandes ci-dessous, `vidange-fluidnc` et `vidange-porte-bocal` veulent dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-fluidnc` (et de même pour l'autre).

## Étape 1 : ce que FluidNC sait faire (console)

1. `vidange-fluidnc console mycelium_lavage`, puis `$H` : la glissière va au garage ; ni la manivelle
   ni les mors ne doivent bouger.
2. Envoyer `?` plusieurs fois en tournant la manivelle **à la main**, très lentement (moteur coupé ou
   pilote désactivé) : quand le contrepoids passe devant le capteur, la lettre `A` doit apparaître dans
   `Pn:` ; manivelle en haut (± 95°), elle doit disparaître. Si FluidNC refuse ensuite de bouger la
   manivelle tant que `A` est là : brancher le capteur sur `macro2_pin` à la place, mettre
   `origine_manivelle: "2"` dans `pi/reglages/fluidnc.yaml` (aucun changement du code).
3. Appuyer à la main sur le contact « verrou engagé » (ou doigt dans un trou) : la lettre `0` doit
   apparaître dans `Pn:`. Pencher le capteur d'inclinaison : la lettre `1` doit apparaître ou disparaître.
   Noter ce que dit le capteur **actionné** (bocal debout ou tête en bas) : c'est `inclinaison_actionne`
   dans `machine.yaml`.
4. `M64 P2` : l'électroaimant doit retirer le doigt (`0` disparaît). `M65 P2` : il le relâche.
5. Doigt retiré à la main, `M64 P0` puis tout de suite `M65 P0` : le plateau doit tourner un peu dans le
   sens « vers tête en bas ». Même chose avec `P1` : l'autre sens. Si les sens sont inversés, échanger les
   numéros `0` et `1` dans `pi/reglages/fluidnc.yaml` (sorties).
6. `$HY` : les mors doivent s'ouvrir jusqu'à leur fin de course ; `?` : `MPos` doit dire Y = 103. Si
   FluidNC refuse `$HY` (axe en « cycle: 0 »), mettre `cycle: 3` pour Y et le dire dans la PR de correction
   (il faudra alors empêcher `$H` de l'ouvrir bocal tête en bas).

## Étape 2 : origine de la manivelle

1. `vidange-porte-bocal origine` : la manivelle fait un peu plus d'un tour et demi, lentement (≈ 2 min à
   5 °/s), puis l'outil écrit `H = ...°` (angle du moteur « manivelle en haut »).
2. Relancer 3 fois : H doit revenir à ± 1° (à un nombre entier de tours près).
3. Manivelle à H (console : `$J=G53 A<H> F3600`) : elle doit être **pile en haut**. Sinon, mesurer l'écart
   et le mettre dans `mycelium → manivelle → origine → decalage_deg`.
4. Mesurer la largeur de la zone sans métal : dans le journal de l'outil, ou à la main (angles du moteur où
   `A` disparaît et réapparaît dans `Pn:` en tournant dans le même sens) : la mettre dans `largeur_zone_deg`
   (≈ 190).
5. Si l'outil dit « capteur manivelle » : regarder la distance du capteur au contrepoids (1,5 à 2 mm), et
   que la bielle reste à 14 mm au moins.

## Étape 3 : les mors, sans bocal

1. `vidange-porte-bocal ouvrir` : « Mors ouverts : écart 103.0 mm ». Mesurer au pied à coulisse : 103 mm
   entre les mors. Sinon, corriger `steps_per_mm` de Y.
2. `vidange-porte-bocal serrer` (sans bocal) : les mors se ferment jusqu'au bout de leur course, puis
   l'outil dit « bocal absent, cassé ou mal posé : mors arrêtés à 80.0 mm ». C'est voulu.

## Étape 4 : serrage d'un bocal

1. Bocal vide (Ø 95) posé debout, centré : `vidange-porte-bocal serrer`. Les mors doivent s'arrêter sur le
   bocal sans à-coup ; l'outil donne l'écart : **95 mm à ± 1 mm**.
   - Ils s'arrêtent avant le bocal : StallGuard trop sensible (augmenter `stallguard`, ou la vitesse
     `porte_bocal → palpage_m_s`, toujours au-dessus du minimum de StallGuard).
   - Ils forcent sur le bocal sans s'arrêter : moins sensible (baisser `stallguard`). **Arrêt d'urgence.**
2. Tirer le bocal à la main : il ne doit pas glisser. Sinon, monter `run_amps` / `hold_amps` (le courant de
   serrage) par petits pas, sans aller jusqu'à fissurer le verre.
3. Recommencer 10 fois : noter les écarts lus. Leur dispersion donne `tolerance_diametre_m` (3 mm dans
   l'exemple ; garder au moins 2 fois la dispersion).
4. Bocal posé de travers : le serrage doit soit le redresser (écart 95), soit donner l'alarme.

## Étape 5 : demi-tour

Agitateur **au demi-tour** (console : `$J=G53 X865 F3000`), bocal vide serré, chariot de remplissage écarté.

1. `vidange-porte-bocal tete-en-bas` : prise d'origine de la manivelle, manivelle en bas, le doigt se
   retire, le plateau tourne (≈ 2,3 s), le doigt frotte puis entre dans le trou suivant, le moteur
   s'arrête, manivelle en haut. L'outil dit « Bocal tête en bas ».
2. Mesurer le temps du demi-tour : `demi_tour → delai_max_s` = 2 fois ce temps au moins (4 s dans
   l'exemple). Si le doigt ne sort pas assez vite du trou, monter `relache_s` (0,5 s) ; s'il rate le trou
   suivant, la baisser.
3. `vidange-porte-bocal debout` : retour, dans l'autre sens.
4. Pannes, une à une : débrancher le contact « verrou engagé » pendant un demi-tour → arrêt du moteur et
   alarme au bout de `delai_max_s` ; débrancher le capteur d'inclinaison → alarme « capteur d'inclinaison ».
5. Agitateur au garage : `vidange-porte-bocal tete-en-bas` doit être **refusé** (« l'amener au
   demi-tour d'abord »).

## Ce qu'il faut renvoyer

Les chiffres mesurés (`decalage_deg`, `largeur_zone_deg`, `inclinaison_actionne`, `palpage_m_s`,
`tolerance_diametre_m`, `relache_s`, `delai_max_s`, et dans `fluidnc/mycelium_lavage.yaml` : `stallguard`,
`run_amps`, `hold_amps`, `steps_per_mm` de Y), et ce qui n'a pas marché à l'étape 1. Une session de
correction les met dans les réglages ; puis passer `porte_bocal → exemple` à `false`.
