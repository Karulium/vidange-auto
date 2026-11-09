# Essai de la vue 3D et du rejeu d'incident sur le vrai Pi

Testé sur le vrai matériel : **non** (seulement sur un PC et dans GitHub Actions : le test du navigateur
dessine la vue avec de fausses cartes). Les tailles et décalages des boîtes de `pi/reglages/vue3d.yaml` sont des
**EXEMPLES** tirés des commentaires de `machine.yaml` : cet essai sert à les comparer à la vraie machine.

**La vue 3D informe, elle ne protège pas.** Elle ne commande rien ; la sécurité des personnes est câblée
(arrêt d'urgence, portes, relais de sécurité). Ne jamais s'y fier pour savoir si on peut s'approcher.

À faire après l'installation (`installation.md`) et avec la machine à l'arrêt, portes fermées, sauf indication
contraire. Cocher chaque essai réussi.

## 1. La vue en direct

- [ ] Sur le téléphone ou le PC, ouvrir la page du Pi (`http://<adresse du Pi>:8080`), se connecter, toucher
      **« Vue 3D »**. La scène apparaît en quelques secondes : un sol, des boîtes colorées (pont, chariot, griffe,
      préhension, chariot du remplissage, fût) et des cadres de couleur (les zones). Une ligne de légende dit
      quelle couleur est quoi.
- [ ] Doigt (ou souris) : glisser fait tourner la vue, pincer (ou molette) zoome, deux doigts (ou clic droit) la
      déplace.
- [ ] La machine à l'arrêt, chaque boîte est **à la place de la vraie pièce** (à quelques centimètres près) :
      comparer au moins le pont, le chariot, la griffe et le plateau du remplissage. Si une boîte est mal placée
      ou mal dimensionnée, noter l'écart : on corrige `vue3d.yaml` (taille, `decalage`), pas le code.
- [ ] Bouger un axe avec le pilotage à distance (onglet « Vidéo », « mode à distance », procédure de
      `essai-distance.md`) : la boîte correspondante bouge dans la vue, dans le bon sens, à peu près en même temps
      que la vraie pièce (rafraîchi 5 fois par seconde, `rafraichir_s`).
- [ ] Si un axe tournant (griffe, préhension, plateau) tourne **dans le mauvais sens** sur le dessin : le noter
      (question à poser, le sens du dessin est à choisir une fois pour toutes).
- [ ] Une zone prise par un module change de couleur (orange) pendant que le module la tient, et la ligne
      au-dessus de la scène écrit « Zones tenues : <zone> (<module>) ». Elle redevient verte quand il la rend.
- [ ] Couper la connexion de la box (ou passer en mode avion sur le téléphone) : un message d'erreur apparaît au
      lieu de la scène figée sans rien dire ; il disparaît quand le réseau revient.

## 2. Le rejeu d'une alarme

- [ ] Provoquer une alarme sans danger (comme dans `essai-distance.md`, § 4 : débrancher le câble USB d'une carte
      FluidNC pendant qu'un module attend un Go, puis donner le Go). **Attendre une minute et quelques secondes** :
      le Pi garde la minute d'après avant d'écrire le rejeu.
- [ ] Dans `/var/lib/vidange/rejeux/` (dossier `donnees/rejeux`), un fichier `NNNNNNNN.json` porte le numéro de
      l'alarme (visible sur la page, dans la carte de l'alarme) ; il pèse de quelques dizaines à quelques centaines
      de Ko : `ls -l /var/lib/vidange/rejeux`.
- [ ] Page, onglet « Vue 3D », « Rejeu d'une alarme » : un bouton « N° … » pour cette alarme. Le toucher : la
      scène se met aux positions d'il y a 60 s. **Lecture** les rejoue (vitesses ×0,5 à ×4), **Pause** arrête,
      le curseur permet d'aller n'importe où ; le texte dit « 12,4 s avant l'alarme » / « à l'alarme » / « 8,0 s
      après l'alarme ».
- [ ] À « l'alarme », les boîtes sont là où étaient les vraies pièces quand l'alarme a sonné (les photos et le clip
      de l'onglet « Vidéo » aident à comparer).
- [ ] Dans l'onglet « État » (alarmes) ou « Voir les dernières alarmes », le bouton « Rejouer en 3D » ouvre
      directement le rejeu de cette alarme. Pour une alarme toute récente (moins d'une minute et demie), il dit
      « Rejeu impossible : pas de rejeu pour l'alarme n° … » : c'est normal, réessayer plus tard.
- [ ] Revenir « En direct » : les boîtes suivent de nouveau la machine.

## 3. La place prise

- [ ] Après quelques alarmes : `du -sh /var/lib/vidange/rejeux` reste très en dessous de `dossier_max_mo`
      (200 Mo). Quand le dossier dépasse cette limite, les plus vieux fichiers sont effacés (le journal dit
      « Rejeu … effacé (dossier plein) »).
- [ ] Le Pi ne ralentit pas : le chef et l'écran de l'armoire répondent comme avant (le relevé des positions
      est un petit fil à part ; s'il plante, la machine continue).

Si un essai rate : noter ce qui s'est passé, copier les dernières lignes du journal
(`journalctl -u vidange -n 100`) dans la PR, et remettre la machine en sécurité.
