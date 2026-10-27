# Essai de la file d'envoi sur le vrai Pi

Testé sur le vrai matériel : **non** (seulement sur un PC et dans GitHub Actions, avec un faux logiciel de
culture — un petit serveur web local — et une fausse copie de secours qui copie dans un dossier).

À faire après l'installation (`installation.md`, jusqu'à l'étape 9). La machine n'a pas besoin de bouger.
Cocher chaque essai réussi.

Dans les commandes ci-dessous, `vidange-envois` veut dire
`sudo -u vidange VIDANGE_SECRETS=/etc/vidange/secrets.yaml /opt/vidange-auto/pi/.venv/bin/vidange-envois --donnees /var/lib/vidange`,
et `vidange-registre` veut dire
`sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-registre --donnees /var/lib/vidange`.

## Copie de secours à la maison

- [ ] **Réglage lu** : après avoir mis la commande rsync dans `programme.yaml` (installation, étape 9),
      `sudo systemctl restart vidange`, puis `journalctl -u vidange -n 80 | grep -i "envoi"` : plus de ligne
      « Envoi « copie de secours (maison) » pas encore réglé ».
- [ ] **Copie envoyée** : `vidange-registre sauvegarder`, puis `vidange-envois essayer`.
      La réponse dit « 2 envoi(s) réussi(s) » (la base et le dossier des photos). À la maison, le dossier
      `sauvegardes-vidange` contient `registre-AAAA-MM-JJ.sqlite` et un dossier `photos`.
- [ ] **Maison injoignable** : éteindre l'ordinateur de la maison (ou couper Tailscale sur le Pi :
      `sudo tailscale down`). `vidange-registre sauvegarder`, puis `vidange-envois essayer` :
      « 0 envoi(s) réussi(s) », et `vidange-envois etat` montre l'envoi en attente avec l'erreur de rsync.
      La machine, elle, tourne normalement (`systemctl status vidange` → « active (running) »).
- [ ] **Retour du réseau** : rallumer la maison (ou `sudo tailscale up`), puis `vidange-envois essayer` :
      `vidange-envois etat` → « 0 en attente » ; la copie est arrivée à la maison. (Sans rien faire, le programme
      réessaie de lui-même : au plus tard une heure après.)
- [ ] **Coupure de courant pendant l'attente** : maison injoignable, `vidange-registre sauvegarder`, puis couper
      le courant du Pi et le rallumer. `vidange-envois etat` montre toujours l'envoi en attente ; il part
      quand la maison revient.
- [ ] **Le lendemain** : sans rien faire, la copie du jour (après 3 h du matin) arrive à la maison.

## Logiciel de culture (quand l'app « machine » existera)

- [ ] `vidange-envois montrer <n° d'un cycle>` affiche le JSON d'un cycle (format de `docs/django.md`).
- [ ] Après avoir réglé l'adresse et le jeton (installation, étape 9) : `vidange-envois essayer` → les cycles
      en attente partent ; ils apparaissent dans le logiciel de culture.
- [ ] Jeton faux : l'envoi reste en attente, `vidange-envois etat` montre « répond 401 » ; avec le bon jeton,
      il part.
