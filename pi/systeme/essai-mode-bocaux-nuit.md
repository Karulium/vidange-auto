# Essai du mode bocaux et de la nuit UV-ozone sur la vraie machine (tâche 45 bis)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent que le faux matériel et le
simulateur. Cet essai ne fait **rien bouger** et **ne lance aucune nuit** : on démarre la machine à vide
et on lit ce que disent l'écran de l'armoire et la check-list. Il dure environ 10 minutes.

Ce qu'il faut savoir avant : aujourd'hui, **ni lot de bocaux ni nuit UV-ozone ne peuvent partir sur la
vraie machine**. C'est voulu. Le programme le dit, poste par poste, avec la raison :

- réglages d'EXEMPLE (`exemple: true` dans `pi/reglages/machine.yaml`) : interdits sur la vraie machine,
  y compris la partie `nettoyage` pour la nuit ;
- lot de bocaux : le versement de la griffe n'est pas écrit (tâche 23) ; la Préhension et la lecture de la
  photo du plafond ne sont pas branchées au programme principal ;
- lavage des bocaux : le Lavage n'est pas branché, la liste des bocaux sales (caméra du plafond) n'est pas
  écrite.

La chaîne UV-ozone (reeds du bas du store, porte du spray) et le store restent **câblés** : le Pi informe
et attend, il ne protège personne.

## Étape 1 : démarrer à vide, mode « production » (lot de bocaux)

1. Machine sous tension, arrêt d'urgence relâché, store fermé, rien dans le chariot ni sur le plateau.
2. `vidange --verifier` doit dire « Réglages corrects ».
3. `sudo systemctl restart vidange`.
4. `journalctl -u vidange -b | grep "Mode bocaux"` : quatre lignes (fut, entonnoir, versement,
   lavage_bocaux), chacune « prêt » ou « pas lancé : ... » avec la raison.
5. `journalctl -u vidange -b | grep "mode bocaux"` : les lignes de la check-list. On doit voir
   « [attention] mode bocaux : aucun lot de bocaux ne peut partir : ... » (jamais « bloquant »).
6. Sur l'écran de l'armoire, mode « Production », quand plus rien ne tourne : la page d'état parle d'abord
   des seaux ; si les seaux étaient prêts elle parlerait des bocaux (« Lot de bocaux : ... pas prêt »).
7. Passer l'écran en mode « Lavage » (bouton MODE, puis Oui) : la page d'état dit
   « Lavage des bocaux : pas prêt » et pourquoi. Revenir en « Production ».

## Étape 2 : nuit UV-ozone « à blanc » (on ne la lance pas)

1. Passer l'écran en mode « UV-ozone » (bouton MODE, puis Oui).
2. `journalctl -u vidange -b | grep "Nuit UV-ozone,"` : trois lignes (enceinte, ozone, purge).
3. Sur la page d'état : « Nuit UV-ozone : prête » si `nettoyage` n'est plus en EXEMPLE, sinon
   « Nuit UV-ozone : enceinte pas prêt » et la raison (valeurs d'EXEMPLE ou signal absent).
4. Page « Enceinte » de l'écran : le bouton « NUIT » est grisé tant qu'un poste manque ; appuyer dessus
   ne lance rien et le message dit « Nuit UV-ozone impossible : poste ... pas lancé : ... ».
5. Repasser en mode « Production ».
6. **Ne pas lancer de vraie nuit** pendant cet essai. La première vraie nuit se fait avec la procédure de
   `pi/systeme/essai-nettoyage.md`, quand les chiffres de la nuit sont mesurés.

## Étape 3 : la check-list depuis la page web

1. Ouvrir la page web, partie check-list (ou `GET /api/checklist` avec la clé).
2. Les lignes « mode bocaux » et « nuit UV-ozone » du journal doivent y être.

## Étape 4 : redémarrer pendant un mode (facultatif)

1. Mode « UV-ozone » choisi, `sudo systemctl restart vidange` : le mode est gardé (même écran après).
2. Aucune nuit ne démarre toute seule au redémarrage (règle 6 : Go de Karulium).

## Si quelque chose ne va pas

- Le programme ne démarre pas : `journalctl -u vidange -b | tail -50`, et envoyer ces lignes.
- Une ligne « reprise du cycle » bloquante parle d'un « lavage » : le carnet (`pi/donnees/etat-cycle.json`)
  garde une série de lavage de bocaux que le programme ne reprend pas. Regarder la machine, puis effacer
  ce fichier.

## Après l'essai

Rien à remettre : l'essai ne fait rien bouger. Renvoyer les notes des étapes 1 et 2 (une photo de l'écran
suffit) dans la PR.
