# Essai des caméras et du pilotage à distance sur le vrai Pi (tâche 12)

Testé sur le vrai matériel : **non** (seulement sur un PC et dans GitHub Actions : faux FluidNC, faux voyant,
fausses caméras, et une vidéo d'essai de `ffmpeg` dans un vrai navigateur à la taille d'un téléphone).

À faire après `installation.md` (jusqu'à l'étape 9 bis) et `essai-page-web.md`. Cocher chaque essai réussi.

**Sécurité** : ce pilotage n'est qu'un confort. L'arrêt d'urgence et les portes restent câblés et passent avant
tout. Pour les essais qui font bouger un axe : quelqu'un **sur place**, la main près de l'arrêt d'urgence, et
personne dans la machine. Faire les premiers essais avec un axe libre sur toute sa course.

## 1. Les caméras, une par une

1. Caméra du plafond (prise caméra du Pi) : essai sans le programme (programme arrêté, elle ne se partage pas) :
   ```
   sudo systemctl stop vidange
   rpicam-hello --list-cameras          # la caméra doit apparaître (n° 0)
   rpicam-vid --camera 0 --nopreview --timeout 3000 --codec mjpeg --width 1280 --height 720 \
              --framerate 5 --output /tmp/essai.mjpeg
   ls -l /tmp/essai.mjpeg               # quelques centaines de Ko : la caméra filme
   ```
2. Caméras USB : brancher la caméra de la tête de griffe seule, puis :
   ```
   ls /dev/v4l/by-id/                   # noter le nom qui finit par « -video-index0 »
   ffmpeg -f v4l2 -list_formats all -i /dev/v4l/by-id/<ce nom>   # elle doit proposer « mjpeg »
   ```
   Recopier ce nom dans `/opt/vidange-auto/pi/reglages/programme.yaml`, partie `cameras` → `liste` →
   `tete_griffe` → `commande`, à la place de `/dev/v4l/by-id/usb-EXEMPLE-TETE-video-index0`. Si la taille
   `1280x720` n'est pas dans la liste, prendre une taille proposée. Pareil pour la caméra du dosage.
3. Quand les trois commandes sont justes, passer `exemple: true` à `exemple: false` (partie `cameras`), puis :
   ```
   sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange --verifier
   sudo systemctl start vidange
   ```

- [ ] **Vidéo en direct** : sur le téléphone, page web → onglet « Vidéo ». L'image de la caméra du plafond
      s'affiche et bouge (environ 4 images par seconde) ; « En direct · image n° ... » avance.
- [ ] **Chaque caméra** : toucher le nom de chaque caméra → son image s'affiche.
- [ ] **Par Tailscale** : même essai en 4G (Wi-Fi coupé, Tailscale allumé). La vidéo reste fluide ; sinon,
      baisser `page_images_par_s` ou la taille d'image dans `programme.yaml`.
- [ ] **Caméra débranchée** : débrancher une caméra USB. Après quelques secondes, onglet « Check-list » →
      « caméra ... : aucune image depuis ... » (attention). Le journal dit « Caméra ... arrêtée : relance ».
      Rebrancher : la vidéo revient seule en moins de 10 s.
- [ ] **Charge du Pi** : `top` pendant 1 minute : le programme `vidange` et les commandes `rpicam-vid` /
      `ffmpeg` ensemble restent sous 100 % (un cœur sur quatre). Noter le chiffre dans la PR.

## 2. Le voyant-buzzer

Il est relié au signal `voyant_buzzer` de `docs/entrees-sorties.yaml` (pour l'instant un **exemple** : relais K1
de la carte relais n° 1). Le vérifier d'abord seul (programme arrêté) :
```
sudo systemctl stop vidange
sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-es commander voyant_buzzer oui   # sonne et s'allume
sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-es commander voyant_buzzer non
sudo systemctl start vidange
```
- [ ] Le voyant s'allume et le buzzer sonne, puis s'arrêtent.

## 3. Le pilotage à distance

Préparer : la machine à l'arrêt ou en attente d'un Go (pas en plein geste), les cartes FluidNC branchées et
avec leur prise d'origine faite, les vrais axes dans `machine.yaml`.

- [ ] **Activer** : onglet « Vidéo » → « Activer le mode à distance » → confirmer. La page dit « Mode à
      distance ACTIF » ; le bandeau de la page devient bleu « PILOTAGE À DISTANCE » ; **l'écran de l'armoire**
      affiche en violet « À DISTANCE : TOUCHER = STOP ». La machine est en pause.
- [ ] **Refus pendant un geste** : pendant qu'un axe bouge pour le cycle, essayer d'activer → refusé
      (« un geste du cycle est en cours »).
- [ ] **Voyant avant le mouvement** : tenir le bouton « + ▶ » d'un axe. Le voyant et le buzzer partent
      **tout de suite** sur place ; l'axe ne part qu'après 3 s (`voyant_avant_s`), lentement (au plus
      2 cm/s, `vitesse_max_m_s`). La position affichée avance.
- [ ] **Homme mort, bouton lâché** : lâcher le bouton → l'axe s'arrête aussitôt (moins de 1 cm).
- [ ] **Appuis rapprochés** : rappuyer dans les 10 s → l'axe repart sans attendre (le voyant est encore allumé).
      Le voyant s'éteint 10 s après le dernier mouvement (`voyant_apres_s`).
- [ ] **Bout de course** : tenir jusqu'au bout de la course de `machine.yaml` → l'axe s'arrête de lui-même,
      la page dit « au bout de sa course ».
- [ ] **Connexion coupée** : tenir le bouton et, pendant le mouvement, couper le Wi-Fi et la 4G du téléphone
      (mode avion) → l'axe s'arrête en moins d'une seconde (`homme_mort_s`). Remettre le réseau : rien ne
      repart tout seul ; il faut lâcher puis rappuyer.
- [ ] **Vidéo figée** : tenir le bouton et, pendant le mouvement, débrancher la caméra regardée → l'axe
      s'arrête (« vidéo figée sur la page »). Rebrancher.
- [ ] **Page fermée** : tenir le bouton et passer à une autre appli du téléphone → l'axe s'arrête.
- [ ] **Priorité à l'armoire, écran** : pendant le mode à distance, toucher n'importe quel bouton de l'écran de
      l'armoire → l'écran dit « Pilotage à distance arrêté : la main est à l'armoire. », la page dit « Mode à
      distance terminé » ; la machine reste en pause.
- [ ] **Priorité à l'armoire, pause** : refaire « Activer », tenir un bouton, et pendant le mouvement appuyer
      sur le bouton Pause câblé sur la carte FluidNC → l'axe s'arrête, le mode à distance se termine
      (« reprise sur place »).
- [ ] **Arrêt d'urgence** : refaire « Activer », tenir un bouton, et appuyer sur l'arrêt d'urgence → tout
      s'arrête (câblage) ; le mode à distance se termine. Réarmer comme d'habitude (prise d'origine si besoin).
- [ ] **Go refusé pendant le pilotage** : mode actif, toucher un Go sur la page → « Go refusé : quitter
      d'abord le pilotage à distance ».
- [ ] **Fin seule** : activer, ne rien toucher pendant 15 min (`inactivite_max_min`) → le mode se termine seul.
- [ ] **Journal** : en bas de l'onglet « Vidéo », « Journal du pilotage à distance » montre chaque action :
      qui (adresse du téléphone), quand, quoi (activer, mouvement, arrêt et sa raison, reprise sur place).

## 4. Clip d'une alarme

- [ ] Provoquer une alarme sans danger (par exemple : débrancher le câble USB d'une carte FluidNC pendant
      qu'un module attend un Go, puis donner le Go). Dans l'onglet « Vidéo », « Clips des alarmes » montre un
      nouveau clip à l'heure de l'alarme ; « Revoir » → « Lire » rejoue les 60 s d'avant, caméra par caméra.
- [ ] Le fichier de bilan de l'alarme (`/var/lib/vidange/bilans/...`) contient
      `"clip_video": "clips/AAAA-MM-JJ/HHMMSS"` ; le fichier `plafond.mjpeg` de ce dossier s'ouvre avec VLC.

Si un essai rate : noter ce qui s'est passé, copier les dernières lignes du journal
(`journalctl -u vidange -n 100`) dans la PR, et remettre la machine en sécurité.
