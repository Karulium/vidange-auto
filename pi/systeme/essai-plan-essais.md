# Essai des plans d'essais seau par seau (tâche 31, fonctions 6 et 76)

Testé sur le vrai matériel : **non**. GitHub Actions ne teste que des faux (faux registre, simulateur, fausse carte
du spray, faux matériel du lot). Cette procédure est à faire sur le vrai Pi, puis sur la vraie machine, dans cet
ordre. Les parties 1 à 3 ne font bouger aucun moteur. La partie 4 se fait avec quelqu'un devant la machine et la
main sur l'arrêt d'urgence (qui reste câblé en dur : le logiciel ne protège personne).

Commandes sur le Pi (`cd /opt/vidange-auto/pi`, venv activé). Le plan d'exemple est
`systeme/plan-essais-exemple.yaml` (6 seaux `seau_a`, `pleurote_grise`) : le copier pour l'essai.

## 0. Avant : fixer les bornes

Les bornes de `reglages/essais.yaml` sont des EXEMPLES (`exemple: true`).

1. Peser le mycélium d'un bocal plein (sans le bocal). Pour chaque format : `max` du mycélium × nombre de couches ×
   `seaux_par_bocal` (`machine.yaml → griffe → formats`) doit rester sous ce poids, sinon la machine s'arrêtera
   avec « poids qui ne monte plus » (bocal vide). Corriger `max` si besoin.
2. Mesurer la dose de spray la plus forte que la pompe donne en moins de `spray → dose → temps_max_pompage_s` :
   `max` de `spray_g` doit rester dessous.
3. Écrire les bornes voulues, puis `exemple: false`. [ ] `vidange --verifier` dit « Réglages corrects ».
4. Mettre une borne impossible (exemple `min: 300` sur `mycelium_g`, plus grand que `max`) :
   [ ] `vidange --verifier` refuse et dit laquelle. Remettre la bonne valeur.

## 1. Le plan, sans machine

1. `vidange plan verifier systeme/plan-essais-exemple.yaml`
   [ ] « Plan correct », et un tableau seau par seau ; « * » = réglage normal de `machine.yaml`.
2. Copier le fichier, mettre une dose hors des bornes (`mycelium_g: 1000`), une variable inconnue
   (`temperature: 30`) et un seau n° 9 : `vidange plan verifier copie.yaml`.
   [ ] Refusé, avec les trois erreurs dites en une fois, en français.
3. `vidange plan essayer systeme/plan-essais-exemple.yaml` (une ou deux minutes : le simulateur rejoue le lot normal
   puis le lot avec le plan). [ ] Tableau « normal / avec le plan », le mycélium versé par seau (g par couche) et
   un verdict « va au bout ». Rien n'est écrit dans les vrais fichiers : [ ] `git -C /opt/vidange-auto status
   --short` ne montre rien de plus qu'avant.

## 2. Proposer, accepter, retirer (page web)

1. `vidange plan charger systeme/plan-essais-exemple.yaml` [ ] « Plan chargé : n° ... Il n'est qu'une
   PROPOSITION ». `vidange plan` le liste « chargé, pas encore accepté ».
2. Page web, compte d'un **aide** (rôle « produire ») : [ ] l'onglet « Réglages » est réservé, rien ne s'accepte.
3. Compte **karulium**, onglet « Réglages », bloc « Plans d'essais » : [ ] la liste des variables permises et leurs
   bornes ; [ ] la carte du plan avec son tableau (les valeurs normales en gris, « (normal) »).
4. Charger un 2ᵉ plan depuis la page (coller le texte ou choisir le fichier, « Charger le plan »).
   [ ] Il apparaît comme proposition. Un plan faux collé : [ ] « Refusé : ... » avec les erreurs.
5. « Accepter » le 1er plan, confirmer. [ ] État « accepté : attend son lot ». « Accepter » le 2ᵉ :
   [ ] refusé (« un seul plan accepté à la fois »). Retirer le 2ᵉ.
6. « Essayer au simulateur » sur la carte du plan : [ ] le résultat s'affiche dans « Essai d'un réglage dans le
   simulateur » (bouton « Voir où il en est »).

## 3. Le lot proposé montre le plan (avant le Go)

1. Onglet « État », bouton « Lot de seaux » : 5 seaux `seau_a`, `pleurote_grise`.
   [ ] Pas de plan sur la carte du lot (il vise 6 seaux) ; une ligne grise dit qu'un plan accepté attend son lot.
   « Annuler » le lot proposé.
2. Même chose avec **6** seaux : [ ] la carte du lot proposé dit « Avec plan d'essais n° ... » et montre le
   tableau seau par seau ; [ ] l'écran de l'armoire dit « Avec plan d'essais : ... Toucher GO pour lancer le lot ».
3. Retirer le plan (onglet « Réglages ») sans annuler le lot : [ ] la carte du lot ne montre plus le plan ; ne pas
   donner le Go, annuler le lot. Recharger et réaccepter le plan pour la partie 4.

## 4. Un vrai lot avec le plan (sur la machine)

À faire d'abord avec un plan simple (2 seaux, `mycelium_g` seulement), puis avec l'exemple.

1. Proposer le lot visé, lire le tableau, Go à l'écran. [ ] `vidange plan` dit « lancé avec un lot » ; le bouton
   « Retirer » a disparu.
2. Pendant le lot, regarder la dose à chaque couche (balance du chariot) :
   [ ] les seaux du plan reçoivent leur dose (± la tolérance du mycélium), les seaux non cités la dose normale.
3. Seau « sans spray » du plan : [ ] le bras du spray ne sort pas pour ce seau, le seau suivant est sprayé
   normalement. Seau avec une autre dose de spray : [ ] le flacon perd à peu près cette dose.
4. Fin du lot : `vidange plan montrer N` [ ] chaque valeur vraiment appliquée, seau par seau (couche, poids
   mesuré, « plan » ou « réglage normal »). Même chose dans la carte du plan (« Valeurs vraiment appliquées »).
5. Coupure de courant pendant le lot (débrancher le Pi entre deux seaux, machine à l'arrêt) puis reprise :
   [ ] les seaux suivants gardent leurs valeurs du plan ; dire à Claude si ce n'est pas le cas.
6. Logiciel de culture : quand l'app « machine » existe et `envois.culture.adresse_essais` est réglée,
   [ ] le plan arrive (format dans `docs/django.md`, « Les plans d'essais appliqués ») ; sans réseau, il attend
   dans la file (`vidange-envois`) sans gêner la machine.

Si une valeur n'est pas appliquée comme dans le tableau, ou si la machine s'arrête (bocal vide, spray refusé) :
noter le n° du plan et du seau, `vidange plan montrer N`, et le dire à Claude.
