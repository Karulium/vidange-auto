# Essai des notifications sur le téléphone (ntfy, Telegram) sur le vrai Pi

Testé sur le vrai matériel : **non** (seulement sur un PC et dans GitHub Actions, avec de faux serveurs ntfy et
Telegram). Les heures calmes, les délais d'escalade, l'heure du résumé et les niveaux de
`pi/reglages/programme.yaml` → `notifications` sont des **EXEMPLES**.

**Ces messages informent, ils ne protègent pas.** La sécurité des personnes est câblée (arrêt d'urgence, portes,
relais de sécurité) : ne jamais compter sur un message du téléphone pour s'arrêter ou arrêter la machine.

À faire après l'installation (`installation.md`). Dans les commandes, `vidange` veut dire :
```
sudo -u vidange VIDANGE_SECRETS=/etc/vidange/secrets.yaml /opt/vidange-auto/pi/.venv/bin/vidange
```
Cocher chaque essai réussi.

## 1. Installer ntfy sur le téléphone et choisir un sujet

- [ ] Installer l'application **ntfy** (gratuite, Android : Google Play ou F-Droid ; iPhone : App Store).
- [ ] Fabriquer un **sujet difficile à deviner** (qui le connaît lit tous les messages et peut en écrire) :
      `python3 -c 'import secrets; print(secrets.token_urlsafe(18))'` (au moins 16 caractères ; lettres, chiffres,
      `-` et `_`). Le noter dans un endroit sûr, pas dans un message ni dans Git.
- [ ] Dans l'appli ntfy : « + », écrire ce sujet, serveur `https://ntfy.sh` (ou le tien). Autoriser les
      notifications ; pour les urgents, autoriser aussi « ne pas déranger » (réglage de la chaîne dans l'appli).
- [ ] Sur le Pi, ouvrir `/etc/vidange/secrets.yaml` et remplir `ntfy_serveur: "https://ntfy.sh"` et
      `ntfy_sujet: "<le sujet>"`. Vérifier `chmod 600 /etc/vidange/secrets.yaml`.
- [ ] (En option) Telegram : créer un bot avec @BotFather (son jeton dans `telegram_jeton_bot`), lui écrire un
      message, relever le numéro de la conversation (`telegram_chat`).
- [ ] Relancer : `sudo systemctl restart vidange`, puis regarder la check-list : les lignes « envoi :
      notifications ntfy » (et Telegram) disent « rien en attente » (canal allumé). Un canal sans secret dit
      « éteint (...) ; ce n'est pas une erreur ».
- [ ] Un sujet trop court est refusé au démarrage avec un message clair : essayer avec `court`, constater, remettre.

## 2. Essai d'un message

- [ ] Régler le lien : dans `programme.yaml` → `notifications`, `lien_page` (adresse de la page sur le Wi-Fi de
      l'atelier) et `lien_tailscale` (adresse Tailscale du Pi). Relancer.
- [ ] Faire une petite alarme sans danger (par exemple débrancher le câble USB d'une carte à l'arrêt, ou une
      alarme d'essai du simulateur : `essai-fiabilite.md`). Dans les 30 secondes, le téléphone sonne : titre
      « URGENT : alarme <module> », le message, le « quoi faire » et le lien de la page.
- [ ] Toucher la notification : elle ouvre la page (Wi-Fi de l'atelier ou Tailscale actif sur le téléphone).
- [ ] Pour un message de niveau « info » ou « normal » : mettre `spray: normal` dans `niveaux`, relancer,
      refaire une alarme du spray : le message arrive avec une priorité plus douce.

## 3. Essai sans réseau

- [ ] Débrancher la box (ou couper Internet du Pi). Provoquer une alarme comme au 2. Rien n'arrive, c'est normal.
- [ ] Sur le Pi : `vidange-envois etat` montre le message « en attente » (destination ntfy) avec l'erreur
      « serveur injoignable ».
- [ ] La machine continue de tourner (aucune attente du réseau).
- [ ] Rebrancher. Au plus après 1 h (l'attente double à chaque essai raté, plafonnée à `attente_max_min`), ou tout
      de suite avec `vidange-envois essayer` : le message arrive **une seule fois**, marqué « (en retard) » s'il a
      attendu plus que `en_retard_apres_min`.

## 4. Essai de l'escalade

Mettre pour l'essai `rappel_apres_min: 2` et `renfort_apres_min: 4` dans `programme.yaml` (remettre ensuite).

- [ ] (En option) Pour la 2ᵉ liste : dans les secrets, `ntfy_sujets_renfort: ["<sujet d'une 2ᵉ personne>"]`
      (et/ou `telegram_chats_renfort`). Cette personne installe ntfy et s'abonne à ce sujet.
- [ ] Provoquer une alarme **urgente** et ne rien toucher : après 2 min, un message « RAPPEL URGENT » arrive en
      priorité haute ; après 4 min, la 2ᵉ liste reçoit « URGENT, personne n'a vu ».
- [ ] Refaire une alarme urgente, ouvrir la page (compte « produire » ou plus) et appuyer sur **J'ai vu** :
      plus aucun rappel ne part. L'alarme reste ouverte. Le geste est dans le journal des actions
      (`/api/actions`, compte « karulium »).
- [ ] Refaire une alarme urgente et l'acquitter : plus de rappel non plus.
- [ ] Remettre les vrais délais.

## 5. Heures calmes et résumé du soir

- [ ] Mettre `heures_calmes` autour de l'heure actuelle (exemple : début dans 1 min, fin dans 10 min). Provoquer
      une alarme de niveau « normal » : rien ne part ; une alarme urgente part. À la fin des heures calmes, la
      « normale » arrive (si elle n'a pas été effacée entre-temps).
- [ ] Mettre `resume_soir.heure` 2 minutes plus tard : le résumé arrive (seaux, fûts, alarmes, à faire demain),
      une seule fois ce jour-là. Remettre `19:00`.

## À noter pour la PR

Quels messages sont arrivés, après combien de secondes, si le message sans réseau est bien parti une seule fois,
si le son des urgents passe en « ne pas déranger », et ce qui a surpris.
