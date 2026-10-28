# Essai des mises à jour sur le vrai matériel (tâche 13)

Testé sur le vrai matériel : **non** (seulement sur un PC et dans GitHub Actions : une fausse carte ESP32 qui
imite esptool et la console de FluidNC, et un vrai dépôt Git d'essai pour le programme du Pi).

À faire après `installation.md` et `essai-page-web.md`. Cocher chaque essai réussi.

**Sécurité** : une mise à jour ne fait bouger aucun axe. Elle ne part que machine à l'arrêt, met la machine en
pause, et la laisse en pause après. L'arrêt d'urgence et les portes restent câblés et passent avant tout.

## Ce qu'il faut savoir avant

- **Une copie avant chaque changement.** Avant d'écrire quoi que ce soit dans une carte, le Pi copie TOUTE sa
  mémoire (programme + réglages, 4 à 16 Mo, une minute ou plus). « Revenir à cette copie » remet la carte
  exactement comme elle était. Les 5 dernières copies de chaque carte sont gardées
  (`/var/lib/vidange/mises-a-jour/copies/<carte>/`).
- **Vérification après chaque changement.** La carte doit redémarrer, répondre, et ses messages de démarrage
  ne doivent pas contenir d'erreur (`[MSG:ERR...]`). Pour des réglages, le Pi les relit dans la carte. Si ça
  rate, le Pi remet tout seul la copie faite juste avant.
- **Première installation de FluidNC** : à faire une fois par carte, à l'établi, avec l'installeur officiel de
  FluidNC (il écrit aussi la table de la mémoire). Le Pi, lui, ne fait que les mises à jour : il écrit le
  programme à l'adresse `0x10000` (`programme.yaml` → `mises_a_jour` → `cartes`).
- **Le programme d'une carte** : sur la page des versions de FluidNC (GitHub, « FluidNC releases »), prendre
  le fichier `firmware.bin` de la version voulue, pour les cartes « wifi » ou « noradio » selon ce qui est
  déjà dans la carte (à noter lors de la première installation), et le renommer avec sa version
  (exemple : `fluidnc-3.9.5-noradio.bin`). Toutes les cartes avec la même version, de préférence.
- **Les réglages d'une carte** : le fichier `fluidnc/<carte>.yaml` du dépôt (exemple : `fluidnc/portique.yaml`),
  qui devient `config.yaml` dans la carte. Ces fichiers arrivent avec les tâches des modules ; tant qu'il
  n'y en a pas, le bouton « Envoyer ses réglages » reste grisé.

## 1. Préparer le Pi

1. Mettre le programme à jour à la main une dernière fois (il apporte esptool) :
   ```
   sudo systemctl stop vidange
   cd /opt/vidange-auto && sudo -u vidange git pull
   sudo -u vidange pi/.venv/bin/pip install -e pi
   ```
2. Remettre le service, qui sait maintenant redémarrer après une mise à jour (code 4) :
   ```
   sudo cp /opt/vidange-auto/pi/systeme/vidange.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl start vidange
   ```
3. Si le dépôt GitHub est **privé** : fabriquer un jeton en lecture seule (GitHub → Settings → Developer
   settings → Fine-grained tokens → accès au seul dépôt `vidange-auto`, droit « Contents : Read-only ») et le
   mettre dans `/etc/vidange/secrets.yaml`, ligne `jeton_github: "..."`. Puis `sudo systemctl restart vidange`.

## 2. Une carte FluidNC de rechange, à l'établi

Avec une carte qui n'est pas dans la machine, branchée en USB sur le Pi, et son numéro de série recopié dans
`fluidnc.yaml` à la place d'une des cartes (voir `fluidnc/essai-liaison.md`). Programme arrêté pour les
essais à la main :
```
sudo systemctl stop vidange
cd /opt/vidange-auto/pi
sudo -u vidange .venv/bin/vidange-maj version portique        # doit afficher la version de FluidNC
sudo -u vidange .venv/bin/vidange-maj copies portique
```

- [ ] **Version lue** : `vidange-maj version portique` affiche par exemple `3.9.5 FluidNC v3.9.5`.
      Si « la carte ne répond pas » : vérifier `vitesse_bauds` de `fluidnc.yaml` (115200 d'habitude).
- [ ] **Écrire un programme** (la même version que celle déjà dans la carte, pour commencer) :
      ```
      sudo -u vidange .venv/bin/vidange-maj programme portique /chemin/fluidnc-3.9.5-noradio.bin
      ```
      Les étapes s'affichent : lecture de la version, copie de la mémoire (une minute ou plus), écriture,
      vérification. Doit finir par « Réussi ». Si l'écriture rate : essayer `vitesse_bauds: 460800` dans
      `programme.yaml` → `mises_a_jour` → `cartes`.
- [ ] **Copie gardée** : `vidange-maj copies portique` montre la copie « avant le programme ... ».
- [ ] **Revenir** : `sudo -u vidange .venv/bin/vidange-maj revenir portique` → « Réussi », et la carte répond.
- [ ] **Programme cassé = retour tout seul** : écrire un fichier qui n'est pas FluidNC mais commence bien
      (exemple : le `bootloader.bin` de FluidNC). Le Pi doit dire « ... L'ancienne version est remise, la
      carte répond », et `vidange-maj version portique` redonne la bonne version.
- [ ] **Réglages** (quand un fichier `fluidnc/<carte>.yaml` existe, ou avec un fichier d'essai copié sous ce
      nom) : `sudo -u vidange .venv/bin/vidange-maj reglages portique` → « Réussi ». Ceci essaie à la fois
      l'envoi par XMODEM (`$Xmodem/Receive=`), la relecture (`$LocalFS/Show=`), le redémarrage (`$Bye`) et
      les messages de démarrage (`$SS`). Si une de ces commandes est refusée (FluidNC trop ancien), le dire
      dans une PR avec la version de FluidNC.
- [ ] **Réglages faux = retour tout seul** : envoyer un fichier de réglages avec une faute (exemple : une
      broche qui n'existe pas). Le Pi doit remettre la copie et dire l'erreur de la carte.

Remettre le vrai numéro de série dans `fluidnc.yaml`, puis `sudo systemctl start vidange`.

## 3. Depuis la page web

Page web → onglet « **Mises à jour** ».

- [ ] **Refus pendant un cycle** : pendant un cycle (ou une alarme, ou le pilotage à distance), la page dit
      « Mises à jour impossibles maintenant : ... » et les boutons sont grisés.
- [ ] **Machine à l'arrêt** : la page dit « Machine à l'arrêt : les mises à jour sont possibles ». (Au démarrage,
      le retour en lieu sûr qui attend son Go ne gêne pas : il n'a encore rien bougé.)
- [ ] **Envoyer un programme au Pi** : choisir le fichier `.bin` sur le téléphone ou le PC → « Envoyer au Pi ».
      Il apparaît dans la liste de chaque carte.
- [ ] **Écrire dans une carte** : choisir le programme → « Écrire ce programme » → OUI. Les étapes défilent en
      haut ; la machine passe en pause ; à la fin, « Réussi » et la nouvelle version. Le bandeau de la page
      montre « MISE À JOUR en cours » pendant ce temps (l'écran de l'armoire, lui, montre seulement la pause).
- [ ] **Pendant la mise à jour** : Go et Reprendre sont refusés sur la page (« une mise à jour est en cours »).
- [ ] **Après** : la check-list montre la carte connectée ; la machine reste en pause (REPRENDRE quand on veut).
- [ ] **Revenir à une copie** depuis la page : « Revenir à cette copie » → la carte retrouve sa version d'avant.
- [ ] **Registre** : `sudo -u vidange .venv/bin/vidange-registre etat` → la table `reglages_appliques` a une
      ligne de plus par changement (qui, quand, ancienne et nouvelle version).

## 4. Le programme du Pi

- [ ] **Chercher** : « Chercher une nouvelle version » → la liste des PR acceptées sur `main` depuis la version
      du Pi (ou « Le programme est à jour »). Si « Authentication failed » : dépôt privé, voir le jeton (partie 1).
- [ ] **Installer** (quand une PR vient d'être acceptée) : « Installer » → OUI. Quelques minutes
      (téléchargement, installation, vérification des réglages avec le nouveau programme), puis « Le programme
      redémarre ». La page revient seule après environ 1 minute ; la version affichée en bas a changé.
      `journalctl -u vidange -n 30` montre « Redémarrage du programme (nouvelle version) » puis un démarrage.
- [ ] **Réglages changés sur le Pi gardés** : avant l'essai, changer une valeur dans
      `/opt/vidange-auto/pi/reglages/programme.yaml` (exemple : `rafraichir_s: 3`). Après la mise à jour, la
      valeur est toujours là.
- [ ] **Revenir** : « Revenir à la version d'avant » → même déroulé, la version d'avant revient.
- [ ] **Sans Internet** : couper Internet, « Chercher » → la page dit que le téléchargement a raté ; la machine
      continue de tourner normalement.

## L'accéléromètre (tâche 16)

Son programme se met à jour depuis la même page (partie « Accéléromètre »), par son fil série :
voir `accelerometre/essai-etabli.md`, partie 3.

## Secours

**Une carte ne répond plus du tout** (même après « Revenir ») :
1. `sudo systemctl stop vidange`
2. `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-maj copies <carte>` puis
   `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-maj revenir <carte> --copie <nom>` avec une
   copie plus ancienne.
3. Si esptool ne trouve plus la carte : la débrancher, maintenir son bouton BOOT, la rebrancher, relâcher,
   et recommencer 2. En dernier recours : la réinstaller à l'établi avec l'installeur officiel de FluidNC,
   puis lui renvoyer ses réglages (`vidange-maj reglages <carte>`).

**Le programme du Pi ne démarre plus après une mise à jour** (normalement impossible : les réglages sont
vérifiés avec le nouveau programme avant de redémarrer) :
```
sudo systemctl stop vidange
sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-maj pi revenir
sudo systemctl start vidange
```
Si même cette commande ne marche plus : `cd /opt/vidange-auto && sudo -u vidange git log --oneline -5`, puis
`sudo -u vidange git reset --keep <version d'avant>` et `sudo -u vidange pi/.venv/bin/pip install -e pi`.
