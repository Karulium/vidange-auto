# Essai des comptes de la page web sur le vrai Pi

Testé sur le vrai matériel : **non** (seulement sur un PC et dans GitHub Actions, avec de faux comptes).

À faire après l'installation (`installation.md`, jusqu'à l'étape 8). La machine n'a pas besoin de bouger :
on regarde seulement qui a le droit de faire quoi. Cocher chaque essai réussi. Dans les commandes ci-dessous,
`vidange` veut dire :
```
sudo -u vidange VIDANGE_SECRETS=/etc/vidange/secrets.yaml /opt/vidange-auto/pi/.venv/bin/vidange
```

## Préparer

- [ ] **Pas de compte, page fermée** : si `... compte liste` dit « Aucun compte », ouvrir la page sur le téléphone →
      elle explique la commande du premier compte (pas de formulaire). Dans le journal (`journalctl -u vidange -n 80`),
      la check-list dit « API et page web : ... aucun compte : la page est fermée ».
- [ ] **Premier compte** : `vidange compte ajouter moi --role karulium` (taper un mot de passe de 10 caractères
      ou plus, deux fois). Recharger la page **sans redémarrer** : le formulaire de connexion apparaît.
- [ ] **Les deux autres** : `vidange compte ajouter aide --role employe` et `vidange compte ajouter invite --role visiteur`.
      `vidange compte liste` montre les trois noms et leur rôle, jamais un mot de passe.
- [ ] **Le fichier est privé** : `ls -l /etc/vidange/comptes.yaml` → `-rw-------` et propriétaire `vidange` ;
      `sudo cat /etc/vidange/comptes.yaml` ne montre que des `scrypt$...` (rien de lisible).

## Les trois rôles (sur le téléphone, un compte après l'autre ; « se déconnecter » en bas de la page)

- [ ] **invite (visiteur)** : se connecter. L'état, la check-list, l'historique, les photos s'affichent. Appuyer sur
      PAUSE → message « Refusé : droit insuffisant ... ». La machine ne se met pas en pause.
- [ ] **aide (employé)** : PAUSE puis REPRENDRE marchent. Onglet « Mises à jour » : « Chercher une nouvelle version »
      → refusé (droit insuffisant). Le pilotage à distance (« en cas de problème ») est refusé aussi.
- [ ] **moi (karulium)** : tout marche, y compris l'onglet « Mises à jour » (ne rien installer pour l'essai : « Chercher »
      suffit).
- [ ] **Mauvais mot de passe** : 3 fois de suite sur le même téléphone → après 5 essais ratés (réglage
      `connexions_ratees_max`), « trop d'essais ratés : réessayer dans ... secondes ». Un autre téléphone n'est pas gêné.
      Au bout de 5 minutes (`blocage_s`), ça remarche.

## Journal de qui a fait quoi

- [ ] Après les essais ci-dessus : `tail -n 20 /var/lib/vidange/actions.jsonl` → une ligne par action « produire » ou
      « régler » (PAUSE de `aide`, etc.) et par connexion, avec le nom, le rôle, l'adresse et l'heure. Les refus de
      `invite` n'y sont pas (ils sont dans `journalctl -u vidange | grep "Droit insuffisant"`).
- [ ] Le même journal se lit sur la page : `http://<adresse du Pi>:8080/api/actions` (une fois connecté en `moi`).

## Changer et supprimer

- [ ] `vidange compte changer aide --mot-de-passe` : le téléphone resté connecté sous `aide` est déconnecté tout de suite
      (la page redemande le mot de passe).
- [ ] `vidange compte changer aide --role visiteur` : même chose, et `aide` ne peut plus appuyer sur PAUSE.
- [ ] `vidange compte supprimer invite` : il ne peut plus se connecter.
- [ ] `vidange compte supprimer moi` → refusé : « dernier compte karulium » (plus personne ne pourrait régler la machine).
- [ ] **Redémarrer le service** (`sudo systemctl restart vidange`) : les comptes sont toujours là ; les téléphones
      restés connectés le sont toujours (le cookie vaut `session_h` heures).

## Ce que ces comptes ne font pas

L'écran Nextion de l'armoire n'a pas de comptes (on est devant la machine). Le code pour les fonctions sensibles de
l'écran viendra à la tâche 29.
