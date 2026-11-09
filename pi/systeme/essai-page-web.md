# Essai de l'API et de la page web sur le vrai Pi

Testé sur le vrai matériel : **non** (seulement sur un PC et dans GitHub Actions, avec un faux chef
d'orchestre et un vrai navigateur à la taille d'un téléphone).

À faire après l'installation (`installation.md`, jusqu'à l'étape 8). La machine n'a pas besoin de bouger :
on regarde seulement la page. Cocher chaque essai réussi.

## Préparer

1. Sur le Pi, vérifier qu'il y a un compte (voir `installation.md`, étape 3, et `essai-comptes.md`) :
   ```
   sudo -u vidange VIDANGE_SECRETS=/etc/vidange/secrets.yaml /opt/vidange-auto/pi/.venv/bin/vidange compte liste
   sudo systemctl restart vidange
   journalctl -u vidange -n 50 | grep "API"
   ```
   Le journal doit dire « API et page web à l'écoute : http://0.0.0.0:8080 ».
2. Noter l'adresse du Pi sur le réseau local (`hostname -I`, la première) et son adresse Tailscale
   (`tailscale ip -4`).

## Essais

- [ ] **Page sur le téléphone, sur place** : téléphone sur le Wi-Fi de l'atelier, ouvrir
      `http://<adresse locale du Pi>:8080`. La page demande le nom et le mot de passe ; les taper → l'état de la machine
      s'affiche, l'heure en haut avance toute seule.
- [ ] **Mauvais mot de passe** : appuyer sur « se déconnecter », taper un mauvais mot de passe → « nom ou mot de
      passe faux ». Le journal du Pi dit « Connexion ratée » avec l'adresse du téléphone. Se reconnecter.
- [ ] **Pause depuis la page** : appuyer sur PAUSE → le bandeau devient orange « Machine en PAUSE », le bouton
      devient REPRENDRE ; le journal du Pi dit « Pause demandée par la page web (votre nom, adresse du téléphone) ».
      Appuyer sur REPRENDRE, confirmer.
- [ ] **Go depuis la page** : au démarrage, le retour en lieu sûr attend le Go. **Seulement si la machine est
      prête à bouger** (personne dedans, réglages réels, check-list sans ligne rouge) : appuyer sur
      « GO : lieu_sur », confirmer. Sinon, sauter cet essai.
- [ ] **Check-list** : onglet « Check-list » → la même liste que dans le journal au démarrage, avec les
      « quoi faire ».
- [ ] **Alarme** : provoquer une alarme connue (voir `essai-fiabilite.md`, par exemple débrancher une carte
      FluidNC pendant un geste) → le bandeau devient rouge, l'alarme s'affiche avec « Quoi faire ». Corriger,
      appuyer sur « J'ai corrigé : acquitter », confirmer → l'alarme disparaît, le module attend le Go.
- [ ] **Historique et photos** : onglets « Historique » et « Photos » → les cycles et photos du registre
      (vides tant que la machine n'a pas tourné : « Aucun cycle noté », « Aucune photo »).
- [ ] **À distance par Tailscale** : couper le Wi-Fi du téléphone (4G seulement), appli Tailscale allumée,
      ouvrir `http://<adresse Tailscale du Pi>:8080` → la même page.
- [ ] **Sans Tailscale, depuis Internet** : appli Tailscale éteinte, en 4G → la page ne s'ouvre pas
      (rien n'est ouvert sur la box).
- [ ] **Pi sans compte** : voir `essai-comptes.md` (la page est fermée et explique le premier compte).
