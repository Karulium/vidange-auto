# Essai de la restauration d'un Pi neuf sur le vrai matériel

Testé sur le vrai matériel : **non** (seulement sur un PC et dans GitHub Actions, avec une fausse copie de secours
dans un dossier provisoire et de fausses commandes).

But : prouver qu'un Pi neuf revient à l'état de l'ancien en **moins d'une heure**, avec une seule commande. On
l'essaie sur un **Pi de rechange** ou sur une **carte SD neuve** : jamais sur le Pi qui commande la machine.
La machine n'a pas besoin de bouger (elle peut même être débranchée du Pi).

À faire une fois avant d'en avoir besoin, puis après chaque grosse évolution du logiciel. Noter l'heure de départ.

## 1. Avant l'essai, sur le vrai Pi

- [ ] La copie de secours part bien à la maison (`installation.md`, partie 9 ; `essai-envois.md`) :
      sur l'ordinateur de la maison, le dossier `sauvegardes-vidange/` contient `registre-AAAA-MM-JJ.sqlite`,
      `fichiers-AAAA-MM-JJ.tar.gz` (nouveau, tâche 25) et `photos/`. Si `fichiers-...` manque : lancer
      `vidange-registre sauvegarder` sur le vrai Pi puis attendre l'envoi.
- [ ] **Réglages changés sur le Pi** (tâche 25 bis) : sur le vrai Pi, `git -C /opt/vidange-auto status --short` liste
      les réglages changés (à la main ou depuis la page). Noter-les. Après `vidange-registre sauvegarder`,
      `tar tzf fichiers-AAAA-MM-JJ.tar.gz` (dans `/var/lib/vidange/sauvegardes/`) doit montrer ces mêmes
      fichiers sous `reglages/` (et aucun fichier de secrets).
- [ ] Les secrets (jetons) sont dans votre gestionnaire de mots de passe : la copie ne les contient pas.

## 2. Préparer le Pi de rechange

1. Installer Raspberry Pi OS **Bookworm 64 bits** sur une carte SD neuve (Raspberry Pi Imager), avec SSH activé et
   un compte à vous. Brancher au réseau, démarrer.
2. Installer Tailscale pour joindre la maison : `curl -fsSL https://tailscale.com/install.sh | sh`
   puis `sudo tailscale up` (ouvre un lien à copier dans le navigateur).
3. Copier le logiciel (le dépôt est privé : donner le nom GitHub et un jeton en lecture seule) :
   ```
   sudo apt update && sudo apt install -y git
   sudo git clone https://github.com/Karulium/vidange-auto.git /opt/vidange-auto
   ```
   Le jeton GitHub vient de votre gestionnaire de mots de passe.

## 3. Lancer la restauration (une seule commande)

À la maison, il faut qu'un compte SSH reçoive le Pi. La première fois, le script crée une clé pour le Pi neuf, l'affiche
et s'arrête (code 3) : l'ajouter dans `~/.ssh/authorized_keys` du compte de la maison, puis relancer la même commande.

```
sudo bash /opt/vidange-auto/pi/systeme/restaurer.sh --depuis vidange@maison:sauvegardes-vidange/
```
(Remplacer par le compte et le dossier de la maison, ceux de `programme.yaml` → `envois` → `secours` → `commande`.)
Variante sans réseau : copier le dossier de la copie de secours sur une clé USB, la monter, et
`... restaurer.sh --depuis /media/usb/sauvegardes-vidange`.

Si les photos sont très nombreuses (plusieurs Go), ajouter `--sans-photos` : tout le reste est prêt tout de suite,
et on remet les photos après, pendant que la machine travaille :
`sudo /opt/vidange-auto/pi/.venv/bin/vidange restaurer --depuis ... --photos-seulement`.

La commande affiche trois listes : **FAIT**, **PROBLÈMES** et **IL RESTE À FAIRE À LA MAIN**. Elle finit par le code
0 si tout va bien. Si elle dit de redémarrer le Pi (liaisons série activées), faire `sudo reboot` puis
`sudo systemctl status vidange`.

## 4. Ce qu'il reste à faire à la main (la commande vous le redit)

- [ ] Remplir `/etc/vidange/secrets.yaml` avec les secrets du gestionnaire de mots de passe (`jeton_culture`, et
      `jeton_github` si le dépôt est privé), puis `sudo systemctl restart vidange`.
- [ ] Tailscale : fait à l'étape 2 pour l'essai. Sur un vrai remplacement, c'est la même chose ; penser à retirer
      l'ancien Pi de la liste de Tailscale.
- [ ] Si la copie de secours n'avait pas de comptes : créer un compte (`essai-comptes.md`).
- [ ] Vérifier le matériel branché : noms des caméras USB (`ls /dev/v4l/by-id/`), cartes FluidNC (si les cartes sont
      neuves, leurs numéros de série changent : `essai-cartes-chariot-tete.md`).

## 5. Vérifier que le Pi neuf est comme l'ancien

- [ ] `sudo systemctl status vidange` → « active (running) ».
- [ ] `sudo -u vidange VIDANGE_SECRETS=/etc/vidange/secrets.yaml /opt/vidange-auto/pi/.venv/bin/vidange --verifier`
      → « Réglages corrects ».
- [ ] `sudo -u vidange VIDANGE_DONNEES=/var/lib/vidange /opt/vidange-auto/pi/.venv/bin/vidange-registre etat` → les
      mêmes nombres de lignes que sur l'ancien Pi, à la copie du jour près.
- [ ] Page web du Pi neuf : se connecter avec un compte de l'ancien Pi (même mot de passe) ; l'historique et les photos
      sont là ; les fichiers appris (`/var/lib/vidange/angles.json`...) aussi.
- [ ] **Réglages de l'ancien Pi** (tâche 25 bis) : la commande a écrit « réglages de l'ancien Pi remis : ... » dans
      FAIT ; `git -C /opt/vidange-auto status --short` sur le Pi neuf montre les mêmes fichiers changés que noté à
      l'étape 1 ; les vrais chiffres (course, positions...) sont là. Si un réglage est dans « IL RESTE À FAIRE À LA
      MAIN » (« PAS remis »), il est dans `/var/lib/vidange/reglages-mis-de-cote/` : recopier ses valeurs dans le
      fichier du dépôt, puis `vidange --verifier`.
- [ ] Le Pi neuf **propose le retour en lieu sûr et attend le Go** à l'écran : c'est normal, ne pas donner le Go si la
      machine n'est pas branchée dessus. (L'état d'un cycle en cours de l'ancien Pi n'est volontairement pas repris.)
- [ ] **Chrono** : de l'étape 2.1 (carte SD prête) à « active (running) » : moins d'une heure. Noter le temps ici : ____

## 6. Après l'essai

Éteindre le Pi de rechange (ou le garder prêt). **Ne jamais laisser deux Pi allumés qui envoient leur copie de secours
au même dossier** : ils s'écraseraient.

## En cas de problème

- « ce Pi a déjà un registre » : normal sur un Pi qui a déjà tourné ; `--ecraser` met l'ancien de côté (jamais perdu).
- « toutes les copies sont abîmées » ou « aucune copie » : regarder le dossier de la maison ; sans copie, rien à restaurer.
- rsync refusé : `tailscale status`, la clé SSH du compte `vidange` du Pi neuf est-elle dans `authorized_keys` de la maison ?
- Le script peut se relancer sans danger : ce qui est fait est sauté.
