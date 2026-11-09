# Installer le programme sur le Raspberry Pi 5

Testé sur le vrai Pi : **non** (seulement sur un PC et dans GitHub Actions).
Chaque commande se tape dans un terminal du Pi (ou par SSH). Ce qui suit `#` est une explication.

## 1. Préparer le Pi (une seule fois)

1. Le Pi tourne sous Raspberry Pi OS Bookworm (64 bits). Vérifier la version de Python :
   ```
   python3 --version        # doit afficher Python 3.11.x
   ```
2. Installer Git et de quoi créer un environnement Python :
   ```
   sudo apt update
   sudo apt install -y git python3-venv
   ```
3. Créer le compte `vidange` qui fera tourner le programme (sans mot de passe, sans connexion) :
   ```
   sudo useradd --system --create-home --shell /usr/sbin/nologin vidange
   sudo usermod -aG dialout,gpio,i2c,video vidange   # ports série, GPIO, I2C et caméras
   ```
4. Activer le bus I2C (capteurs de l'armoire) :
   ```
   sudo raspi-config nonint do_i2c 0
   ```
5. Activer les deux liaisons série du Pi (écran Nextion sur GPIO 4/5, fil de l'accéléromètre sur GPIO 14/15) :
   ajouter ces deux lignes à la fin de `/boot/firmware/config.txt`, puis redémarrer le Pi :
   ```
   dtoverlay=uart2-pi5
   dtparam=uart0=on
   ```
   Après le redémarrage, `ls /dev/ttyAMA0 /dev/ttyAMA2` doit montrer les deux.

## 2. Copier le programme

Si le dépôt GitHub est privé, Git demande un nom et un mot de passe : donner le nom GitHub
et un « jeton » (GitHub → Settings → Developer settings → Personal access tokens), jamais le vrai mot de passe.

```
sudo git clone https://github.com/Karulium/vidange-auto.git /opt/vidange-auto
sudo chown -R vidange:vidange /opt/vidange-auto
cd /opt/vidange-auto/pi
sudo -u vidange python3 -m venv .venv
sudo -u vidange .venv/bin/pip install -e .
```

## 3. Mettre le fichier de secrets

```
sudo mkdir -p /etc/vidange
sudo chown vidange:vidange /etc/vidange      # le compte vidange y écrira aussi les comptes de la page web
sudo cp /opt/vidange-auto/pi/secrets.exemple.yaml /etc/vidange/secrets.yaml
sudo nano /etc/vidange/secrets.yaml          # remplir les valeurs, Ctrl+O pour enregistrer, Ctrl+X pour sortir
sudo chown vidange:vidange /etc/vidange/secrets.yaml
sudo chmod 600 /etc/vidange/secrets.yaml     # lisible seulement par le compte vidange
```
Garder les secrets (jetons) dans le gestionnaire de mots de passe : la copie de secours ne les contient
**pas** (voir l'étape 12).

### Les comptes de la page web

Chaque personne a un nom et un mot de passe, et un rôle : `karulium` (tous les droits), `employe` (regarder et
produire : Go, lots, boutons de production, mais pas les réglages ni les mises à jour), `visiteur` (regarder
seulement). Créer d'abord le compte de Karulium (la commande demande le mot de passe, il ne s'affiche pas ;
au moins 10 caractères) :
```
sudo -u vidange VIDANGE_SECRETS=/etc/vidange/secrets.yaml /opt/vidange-auto/pi/.venv/bin/vidange compte ajouter moi --role karulium
```
Puis les autres : `... vidange compte ajouter NOM --role employe` (ou `visiteur`). `compte liste` montre les comptes,
`compte changer NOM --mot-de-passe` (ou `--role ROLE`) change l'un ou l'autre, `compte supprimer NOM` retire un
compte. Pas besoin de redémarrer : le programme relit le fichier `/etc/vidange/comptes.yaml`. Tant qu'il n'y a
aucun compte, la page web est fermée et explique cette commande. Essai : `essai-comptes.md`.

**Code de l'écran de l'armoire** (changer de mode, store, nuit UV-ozone, passer outre la purge) : 4 chiffres
(`programme.yaml` → `ecran` → `code` → `longueur`), gardé haché dans `/etc/vidange/code_ecran.yaml`. Sans lui, ces
fonctions sont refusées à l'écran (la machine, elle, tourne). Il évite les fausses manoeuvres ; il ne protège pas
les personnes (arrêt d'urgence et portes sont câblés).
```
sudo -u vidange VIDANGE_SECRETS=/etc/vidange/secrets.yaml /opt/vidange-auto/pi/.venv/bin/vidange code-ecran
```
Essai : `essai-ecran.md`.

## 4. Vérifier les réglages

```
sudo -u vidange VIDANGE_SECRETS=/etc/vidange/secrets.yaml /opt/vidange-auto/pi/.venv/bin/vidange --verifier
```
Doit finir par « Réglages corrects ». Sinon, le message dit quel fichier et quelle ligne corriger.

## 5. Installer le service (démarrage avec le Pi)

```
sudo cp /opt/vidange-auto/pi/systeme/vidange.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vidange       # démarre maintenant et à chaque démarrage du Pi
systemctl status vidange                  # doit dire « active (running) »
```

Voir le journal en direct (Ctrl+C pour quitter) :
```
journalctl -u vidange -f
```
Le journal est aussi gardé dans `/var/lib/vidange/journal/vidange.log`.

## 6. Donner au programme le droit d'éteindre le Pi (onduleur)

Quand l'onduleur dit que le courant est coupé depuis trop longtemps, le programme s'arrête proprement puis
éteint le Pi. Le compte `vidange` a le droit de lancer **seulement** cette commande-là :
```
echo 'vidange ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff' | sudo tee /etc/sudoers.d/vidange-extinction
sudo chmod 440 /etc/sudoers.d/vidange-extinction
sudo visudo -c          # doit dire « parsed OK » pour chaque fichier
```

## 7. Chien de garde matériel du Pi

Si tout le Pi se fige (pas seulement le programme), sa puce « chien de garde » le redémarre. On demande
à systemd de l'utiliser (le Pi 5 accepte au plus 15 s) :
```
sudo mkdir -p /etc/systemd/system.conf.d
printf '[Manager]\nRuntimeWatchdogSec=14\n' | sudo tee /etc/systemd/system.conf.d/chien-de-garde.conf
sudo systemctl daemon-reexec
systemctl show -p RuntimeWatchdogUSec        # doit dire RuntimeWatchdogUSec=14s
```

Le chien de garde du programme lui-même est déjà dans `vidange.service` (`WatchdogSec`) : si le programme
se fige, systemd le relance.

## 8. Page web : sur place et à distance (Tailscale)

La page web est servie par le programme lui-même, sur le port réglé dans `programme.yaml` (→ `api`, 8080).
- **Sur place** (même réseau que le Pi) : ouvrir `http://<adresse du Pi>:8080` (l'adresse du Pi se lit
  avec `hostname -I`).
- **À distance** : par Tailscale, comme pour le serveur de culture. Aucun port n'est ouvert sur la box.
  Installer Tailscale sur le Pi (une seule fois), puis le relier au compte Tailscale de Karulium :
  ```
  curl -fsSL https://tailscale.com/install.sh | sh
  sudo tailscale up            # ouvre un lien à copier dans le navigateur pour accepter le Pi
  tailscale ip -4              # l'adresse Tailscale du Pi (100.x.y.z)
  ```
  Sur le téléphone (avec l'appli Tailscale allumée) : `http://<adresse Tailscale du Pi>:8080`.
- La page demande le nom et le mot de passe d'un compte (voir « Les comptes de la page web », étape 3).
- Seuls le réseau local et Tailscale sont acceptés (`reseaux_autorises` dans `programme.yaml`) ; toute autre
  adresse est refusée, même connecté. Sur le Wi-Fi de l'atelier, le mot de passe voyage en clair (http) ;
  par Tailscale, tout est chiffré.

## 9. Envois vers l'extérieur : copie de secours à la maison, logiciel de culture

Tant que ces réglages sont vides, rien ne part et rien ne se perd : tout attend dans la file du Pi.

**Copie de secours à la maison** (par Tailscale, aucun port ouvert). Il faut à la maison un ordinateur toujours
allumé (ou souvent), relié à Tailscale, avec SSH et rsync (Linux, Mac, NAS ; sous Windows : WSL). Exemple avec
un compte `vidange` sur la machine `maison` :
```
# Sur le Pi, une seule fois : une clé SSH pour le compte du programme (sans mot de passe).
sudo -u vidange ssh-keygen -t ed25519 -N "" -f /home/vidange/.ssh/id_ed25519
sudo cat /home/vidange/.ssh/id_ed25519.pub     # à copier dans ~/.ssh/authorized_keys du compte vidange à la maison
# Premier essai (accepter l'empreinte de la maison en tapant « yes ») :
sudo -u vidange ssh vidange@maison mkdir -p sauvegardes-vidange
sudo apt install rsync
```
Puis dans `/opt/vidange-auto/pi/reglages/programme.yaml`, partie `envois` → `secours` :
```
    commande: [rsync, -a, --partial, --timeout=60, "{chemin}", "vidange@maison:sauvegardes-vidange/"]
```
rsync n'efface jamais rien à la maison, et n'envoie que les photos nouvelles.

**Logiciel de culture** (quand l'app « machine » existera, tâche 44) : mettre son adresse dans
`programme.yaml` (`envois` → `culture` → `adresse`) et son jeton dans `/etc/vidange/secrets.yaml`
(`jeton_culture`), puis `sudo systemctl restart vidange`.

Essai : voir `essai-envois.md`.

## 9 bis. Caméras (vidéo en direct, clips des alarmes, pilotage à distance)

La caméra du plafond se lit avec `rpicam-vid` (déjà dans Raspberry Pi OS), les caméras USB avec `ffmpeg` :
```
sudo apt install -y ffmpeg
ls /dev/v4l/by-id/          # le nom de chaque caméra USB, à recopier dans programme.yaml
```
Les commandes sont dans `programme.yaml` (`cameras` → `liste`). Essai pas à pas : voir `essai-distance.md`.

## 10. Essais à faire sur le vrai Pi

Essai des capteurs et des relais : voir `essai-entrees-sorties.md`.
Essai de la fiabilité (programme figé, coupure de courant, onduleur...) : voir `essai-fiabilite.md`.
Essai de la page web (téléphone, Tailscale) : voir `essai-page-web.md`.
Essai des comptes de la page web (rôles, journal des actions) : voir `essai-comptes.md`.
Essai de la restauration d'un Pi neuf depuis la copie de secours : voir `essai-restauration.md`.
Essai de l'écran de l'armoire (câblage, UART n° 2 du Pi 5) : voir `essai-ecran.md`.
Essai de la file d'envoi (copie à la maison, coupure du réseau) : voir `essai-envois.md`.
Essai des caméras et du pilotage à distance (voyant-buzzer, homme mort) : voir `essai-distance.md`.
Essai des mises à jour (cartes ESP32, programme du Pi) : voir `essai-mises-a-jour.md`.

Cocher chaque essai réussi.

- [ ] **Démarrage avec le Pi** : `sudo reboot`, attendre, puis `systemctl status vidange` → « active (running) ».
- [ ] **Relance après un plantage** : `sudo systemctl kill -s KILL vidange`, attendre 10 s,
      `systemctl status vidange` → de nouveau « active (running) », et le journal montre un nouveau démarrage.
- [ ] **Réglages faux = pas de relance en boucle** : dans `/opt/vidange-auto/pi/reglages/programme.yaml`,
      remplacer `niveau: info` par `niveau: bavard`, puis `sudo systemctl restart vidange`.
      `systemctl status vidange` → « failed », et `journalctl -u vidange -n 20` montre le message en français
      qui désigne `programme.yaml, journal → niveau`. Remettre `niveau: info`, puis `sudo systemctl restart vidange`.
- [ ] **Arrêt propre** : `sudo systemctl stop vidange`, le journal finit par « Arrêt demandé : arrêt propre. »
- [ ] **Sans réseau** : débrancher le réseau, redémarrer le Pi : le service démarre quand même.

## 11. Mises à jour (cartes ESP32 et programme du Pi)

Elles se lancent depuis la page web, onglet « Mises à jour », seulement machine à l'arrêt : le programme du
Pi depuis les versions acceptées sur `main`, le programme et les réglages des cartes FluidNC par leur câble
USB. Si le dépôt GitHub est privé, mettre un jeton en lecture seule dans `jeton_github` du fichier de secrets.
Essai pas à pas et secours : voir `essai-mises-a-jour.md`.

À la main (programme arrêté), la même chose existe en ligne de commande : `vidange-maj` (voir son aide :
`/opt/vidange-auto/pi/.venv/bin/vidange-maj --help`).

## 12. Remettre un Pi neuf en état (carte SD abîmée, Pi remplacé)

Une seule commande, en moins d'une heure : `sudo bash /opt/vidange-auto/pi/systeme/restaurer.sh --depuis vidange@maison:sauvegardes-vidange/`.
Elle refait les étapes 1 à 7 ci-dessus, va chercher la copie de secours à la maison, remet le registre, les
fichiers appris, les comptes de la page web et les photos, vérifie les réglages, lance le service et dit en
français ce qui reste à faire à la main (secrets, Tailscale). Les **réglages** (`pi/reglages`, `fluidnc/`,
`docs/entrees-sorties.yaml`) reviennent avec le logiciel (Git), pas avec la copie de secours.

La copie de secours contient : le registre (une copie par jour), l'archive des petits fichiers hors Git et des
comptes (`fichiers-AAAA-MM-JJ.tar.gz`) et les photos. Elle ne contient **jamais** le fichier de secrets.
Pas à pas, avec l'essai sur un Pi de rechange : `essai-restauration.md`.
