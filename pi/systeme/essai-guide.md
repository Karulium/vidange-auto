# Essai du mode guidé et du manuel sur le vrai Pi et le vrai écran (tâche 32)

Testé sur le vrai matériel : **non** (seulement avec un faux écran et de faux capteurs, sur un PC et dans
GitHub Actions).

À faire après l'installation (`installation.md`), l'essai des comptes (`essai-comptes.md`, avec les trois
comptes `moi`, `aide`, `invite`) et l'essai de l'écran (`essai-ecran.md`). **La machine n'a pas besoin de
bouger** : le guide n'envoie aucun ordre aux axes. Cocher chaque essai réussi.

Rappel : le guide ne protège personne. L'arrêt d'urgence et les portes restent câblés ; ne pas s'en passer
pour l'essai.

## 1. Ajouter la page et le bouton dans Nextion Editor (une seule fois)

Dans le projet Nextion, suivre `nextion/pages.md` :

- [ ] **Page 3 « mode »** : rétrécir `b_enceinte` (largeur 115) et ajouter le bouton `b_aide` (texte « AIDE »,
      x 123, y 182, 115 × 86, `txt_maxl` 10). Coller dans son évènement « Touch Press Event » :
      `prints "@b_aide",0` puis `printh FF FF FF`.
- [ ] **Page 8 « guide »** (nouvelle, après la page 7) : 5 textes (`t_titre`, `t_etape`, `t_texte`, `t_machine`,
      `t_info`) et 4 boutons (`b_gauche`, `b_droite`, `b_ok`, `b_retour`), aux positions et avec les
      `txt_maxl` du tableau de la page 8. Le code de chaque bouton est dans `pages.md`.
- [ ] Téléverser le projet dans l'écran, puis redémarrer le programme : `sudo systemctl restart vidange`.

## 2. Les réglages et le manuel

- [ ] `vidange --verifier` dit « Réglages corrects » et, dans les avertissements, « guide.yaml : travaux
      guidés d'EXEMPLE (3) ».
- [ ] `vidange manuel --verifier` dit « ... est à jour. » (sinon `vidange manuel` le réécrit).
- [ ] Ouvrir `docs/manuel.md` : relire les travaux. **Corriger `pi/reglages/guide.yaml`** là où une phrase ne
      correspond pas à la vraie machine (ils ont été écrits sans elle), puis retirer leur `exemple: true`,
      relancer `vidange manuel` et mettre le manuel à jour dans une PR.

## 3. Sur l'écran de l'armoire

- [ ] **Entrer** : page « mode » → le bouton `AIDE` est là → le toucher → la page « guide » dit « AIDE :
      CHOISIR », le titre du 1er travail et « 1 sur 3 ». `SUIVANT` et `PRÉCÉDENT` font défiler (et tourner).
- [ ] **Pas de code demandé** pour entrer ni pour avancer (comme pour la page d'état).
- [ ] **Suivre un travail** (« Mettre un fût au poste ») : `COMMENCER` → « Étape 1 sur 6 » et la phrase ;
      `FAIT` avance ; `PRÉCÉDENT` revient (éteint à l'étape 1) ; `ARRÊTER` abandonne et revient à la page
      d'état. Aucun axe ne bouge.
- [ ] **Un texte trop long est coupé** proprement (pas de débordement hors de l'écran). Sinon, diminuer
      `texte_max` dans `guide.yaml` ou agrandir `t_texte` dans Nextion Editor.
- [ ] **La machine regarde (étape 3, plateau du fût)** : plateau pas au fond → « La machine voit : non, étape
      pas faite » ; le pousser au fond → « oui, étape faite ». Appuyer sur `FAIT` même avec « non » est permis
      (le guide informe, il ne bloque rien) ; le désaccord est noté.
- [ ] **Fin** : à la dernière étape faite, « Les 6 étapes sont faites » et `FERMER`. Une note « Travail guidé
      ... terminé » est dans le carnet de bord de la page web.
- [ ] **Retour seul** : ne rien toucher pendant 1 minute (`retour_accueil_s`) → l'écran revient à la page d'état ;
      le travail reste en route (le retrouver par AIDE).
- [ ] **Alarme** : pendant un travail guidé, provoquer une alarme (selon `essai-ecran.md`) → la page d'alarme
      passe avant la page « guide ».

## 4. Sur la page web (téléphone)

- [ ] **aide (employé)** : onglet « Aide » → les 3 travaux, `Commencer` marche, puis `Fait`, `Étape précédente`,
      `Arrêter ce travail`. En dessous, le manuel : les sections (sécurité, rôles, modes, travaux, entretien,
      alarmes) s'ouvrent.
- [ ] **invite (visiteur)** : l'onglet « Aide » s'affiche et le manuel se lit, mais pas de bouton `Commencer` ;
      l'ordre envoyé à la main est refusé (« droit insuffisant »).
- [ ] **Les deux ensemble** : commencer le travail sur le téléphone → l'écran de l'armoire montre tout seul la
      page « guide » (depuis la page d'état) ; avancer sur l'écran → le téléphone suit (en 3 secondes).
- [ ] **Journal** : `tail -n 5 /var/lib/vidange/actions.jsonl` → les actions de `aide` (`/api/guide/...`).
