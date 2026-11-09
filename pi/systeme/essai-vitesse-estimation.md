# Essai de l'estimation de fin, de la montée en vitesse et de l'essai d'un réglage (tâche 30)

Testé sur le vrai matériel : **non**. GitHub Actions ne teste que des faux (faux chef, faux simulateur, faux
registre). Cette procédure est à faire sur le vrai Pi, puis sur la vraie machine, dans cet ordre. Les parties 1 et 3
ne font bouger aucun moteur ; la partie 2 se fait **à vide d'abord**, avec quelqu'un devant la machine et la main sur
l'arrêt d'urgence (qui reste câblé en dur : le logiciel ne protège personne).

Commandes sur le Pi (`cd /opt/vidange-auto/pi`, venv activé) ; `donnees/` est le dossier de données du programme.

## 1. Essai d'un réglage dans le simulateur (fonction 68), sans machine

1. Essayer un réglage permis :
   `vidange simuler --essayer machine.yaml=griffe.vitesses.pont_x=0.2`
   (une minute environ ; le simulateur rejoue deux lots). Attendu : un tableau « Lot normal / Lot avec l'essai /
   Écart » (durée totale, alertes, refus du chef) et un verdict. Cocher : [ ] le tableau s'affiche.
2. Plusieurs réglages à la fois (la commande se répète) : ajouter
   `--essayer simulateur.yaml=axes.pont_x.vitesse=0.2` (le simulateur n'ira jamais plus vite que son propre axe).
   [ ] Les deux réglages sont listés avec leur valeur d'avant.
3. Un réglage que le démarrage refuserait (rail plus court que la course) :
   `vidange simuler --essayer machine.yaml=axes.pont_x.longueur_rail=0.5`
   Attendu : « Essai impossible : réglage refusé, comme le ferait le démarrage du programme » avec la raison.
   [ ] Refusé.
4. Vérifier qu'aucun vrai fichier n'a bougé : `git -C /opt/vidange-auto status --short` ne doit rien montrer de plus
   qu'avant. [ ] Rien de changé.
5. Page web, onglet « Réglages » (compte karulium), bloc « Essai d'un réglage dans le simulateur » : écrire une
   ligne `machine.yaml=griffe.vitesses.pont_x=0.2`, « Lancer l'essai », puis « Voir où il en est » jusqu'au
   résultat. [ ] Même tableau que la commande. [ ] Pendant un lot, le bouton est refusé (« un lot tourne »).

## 2. Montée en vitesse (fonction 69), sur la machine

La montée est **fausse par défaut** (`programme.yaml → montee_vitesse → actif: false`). Les plafonds y sont des
EXEMPLES : les fixer d'abord, vitesse par vitesse, d'après ce que la mécanique supporte (rien ne monte au-dessus).

1. Avant de l'activer : [ ] `vidange vitesse` dit « Montée en vitesse : pas active. ». [ ] La page, onglet
   « Réglages », bloc « Montée en vitesse », dit « Pas active ».
2. Régler les plafonds dans `programme.yaml → montee_vitesse → vitesses` (chemin dans `machine.yaml` → plafond,
   en m/s). Un plafond au-dessous de la vitesse de départ, un chemin qui n'existe pas ou une vitesse d'approche ou
   de contact (`descente_lente`, `approche`, `plongee`...) : [ ] `vidange --verifier` refuse avec une phrase claire.
3. Mettre `cycles_par_palier` à **2** et `paliers_max` à **2** pour l'essai (on remettra 25 et 4 après).
   Mettre `actif: true`, redémarrer le programme (machine arrêtée, aucun lot).
   [ ] Le journal dit « Montée en vitesse : palier 0 sur 2 ». [ ] `vidange vitesse` aussi.
4. Lancer un petit lot de seaux (2 seaux) **à vide**, quelqu'un devant la machine. À chaque seau rangé, le compte
   monte ; au 2ᵉ : [ ] le journal dit « palier 0 → 1 », la page et `vidange vitesse` aussi, avec « le palier voulu
   agira au prochain démarrage ». [ ] `GET /api/actions` (ou le journal des actions) note le changement.
5. Redémarrer le programme (machine arrêtée). Relancer un lot de 2 seaux : [ ] les gestes du pont et du chariot
   vont un peu plus vite (+5 %, filmer ou chronométrer un trajet), jamais plus que le plafond. [ ] Aucun seuil,
   aucune zone, aucune position n'a changé : `git -C /opt/vidange-auto status --short` ne montre rien.
6. Recul : provoquer une alarme pendant un geste (ouvrir une porte sur une machine à vide arrête déjà par le câblage ;
   sinon, débrancher une pesée d'essai). [ ] Le journal dit « recul : alarme de ... », palier 1 → 0. Ce recul agit
   aussi au prochain démarrage.
7. Annuler : `vidange vitesse annuler` (ou le bouton « Annuler le dernier changement » de la page, compte karulium).
   [ ] Le palier d'avant revient, c'est noté (journal, registre, journal des actions). [ ] Une 2ᵉ annulation de suite
   est refusée (« une annulation ne s'annule pas »).
8. Remettre `cycles_par_palier: 25`, `paliers_max: 4`, et `actif` à `true` seulement si Karulium est sûr.
9. Si une vitesse montée donne un bruit, un choc ou une alerte : `actif: false`, redémarrer, et le dire à Claude.

## 3. Estimation de fin (fonction 7)

1. Lancer un lot de seaux (page web, puis Go à l'écran). [ ] Sur la page (carte « Lancer un lot ») et sur l'écran
   de l'armoire (ligne d'information, quand rien d'autre n'y est dit) : « Fin du lot : environ ... (entre ... et ...),
   vers hh:mm », avec « d'après le simulateur seulement » au tout début.
2. Pendant le lot : [ ] l'avancement monte, la fin estimée se déplace peu. Le calcul du simulateur prend quelques
   secondes au début : la page dit « calcul de l'estimation en cours » d'abord.
3. Après plusieurs lots du même format : [ ] le texte dit « corrigée par N geste(s) appris » et la fin estimée se
   rapproche de la vraie fin (noter l'écart estimé / vrai pour chaque lot). Les durées vraies sont dans le registre :
   `vidange-registre` (table `durees_gestes`).
4. Un autre format de seau repart sans apprentissage (l'estimation est par format).
5. Pauses et attentes du Go ne sont pas prévues : elles s'ajoutent à la fin estimée. [ ] Le texte le dit.
6. Les réglages du simulateur sont des EXEMPLES tant qu'ils ne sont pas recalés : la page le dit. L'estimation n'est
   qu'une information, jamais un réglage.

## Ce qui n'est pas vérifié par les tests

- Le vrai effet d'une vitesse plus haute sur la mécanique (bruit, vibrations, chocs, dérive) : seul l'essai à vide
  le dit. Les vitesses montées sont celles du Pi (`machine.yaml`) ; les vitesses de FluidNC (`fluidnc/*.yaml`) et les
  vitesses d'agitation du mélange ne bougent pas.
- La précision de l'estimation sur de vrais lots (le simulateur n'est pas encore recalé sur la vraie machine).
