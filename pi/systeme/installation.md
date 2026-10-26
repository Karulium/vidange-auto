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
   sudo usermod -aG dialout,gpio,i2c vidange   # accès aux ports série, GPIO et I2C (tâches suivantes)
   ```
4. Activer le bus I2C (capteurs de l'armoire) :
   ```
   sudo raspi-config nonint do_i2c 0
   ```

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
sudo cp /opt/vidange-auto/pi/secrets.exemple.yaml /etc/vidange/secrets.yaml
sudo nano /etc/vidange/secrets.yaml          # remplir les valeurs, Ctrl+O pour enregistrer, Ctrl+X pour sortir
sudo chown vidange:vidange /etc/vidange/secrets.yaml
sudo chmod 600 /etc/vidange/secrets.yaml     # lisible seulement par le compte vidange
```

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

## 6. Essais à faire sur le vrai Pi

Essai des capteurs et des relais : voir `essai-entrees-sorties.md`.

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

## Mettre à jour plus tard (en attendant la tâche 13)

```
sudo systemctl stop vidange
cd /opt/vidange-auto && sudo -u vidange git pull
sudo -u vidange pi/.venv/bin/pip install -e pi
sudo systemctl start vidange
```
