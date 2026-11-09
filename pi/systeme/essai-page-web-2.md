# Essai de la page web, 2ᵉ partie : statistiques, appli, réglages, carnet (tâche 28 bis)

Testé sur le vrai matériel : **non** (un vrai navigateur sur un PC, avec un faux chef d'orchestre ; GitHub Actions
ne fait pas l'essai du navigateur). À faire après `essai-page-web.md`. La machine n'a pas besoin de bouger.

## 1. Statistiques

- [ ] Onglet « Statistiques » : 5 graphiques (seaux faits, durée moyenne par seau, cycles, alarmes par module,
      temps de marche et d'arrêt). Boutons « Par jour / semaine / mois ». « Voir les chiffres » ouvre le tableau.
- [ ] Après quelques cycles, comparer un jour avec l'onglet « Historique » : même nombre de seaux et de cycles.
      Les chiffres viennent du registre, rien n'est estimé.

## 2. Carnet de bord

- [ ] Onglet « Carnet », avec un compte employé : écrire une note, la rattacher à un lot (n° de cycle de
      l'Historique), à un seau (code du QR, déjà vu par la machine) ou à une alarme (n°). L'auteur et la date
      sont mis tout seuls.
- [ ] Chercher un mot ou un nom d'auteur. Barrer la note (une raison est demandée) : elle reste lisible, barrée,
      avec qui l'a barrée et pourquoi. Il n'y a aucun bouton « supprimer », exprès.
- [ ] Avec un compte visiteur : on lit, on ne peut pas écrire.
- Les notes sont dans le registre : elles partent dans la copie de secours quotidienne.

## 3. Réglages (compte karulium seulement)

- [ ] Onglet « Réglages » (invisible pour un employé). Chaque réglage montre sa valeur, ses bornes, son aide.
- [ ] Taper une valeur hors bornes → « Refusé : hors des bornes ». Mettre le résumé du soir pendant les heures
      calmes → refusé, avec la raison. Rien n'est écrit dans ces cas.
- [ ] Changer « Fin des heures calmes » : message vert « Agit au prochain redémarrage ». La carte devient orange.
      Le fichier `/opt/vidange-auto/pi/reglages/programme.yaml` n'a qu'une ligne changée, commentaires gardés
      (`git -C /opt/vidange-auto diff`).
- [ ] « Revenir à ... » remet l'ancienne valeur. L'historique en bas de page montre chaque changement.
- [ ] `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange --verifier` : « Réglages corrects ».
- [ ] Pendant un cycle ou un lot (même en attente de Go) : les boutons sont grisés et la page dit pourquoi.
- [ ] **Pour que le changement agisse** : quand la machine est arrêtée, entre deux lots,
      `sudo systemctl restart vidange`. Jamais pendant un cycle. (Il n'y a pas de bouton « redémarrer » exprès.)
- [ ] Le journal des actions (`GET /api/actions`, ou le fichier `actions.jsonl` des données) montre : qui, quand,
      avant, après.

## 4. Installer la page comme une appli sur le téléphone

Le navigateur n'installe une appli (et n'accepte un service worker) qu'en **HTTPS**. Sur le Wi-Fi de l'atelier la
page est en `http://`, donc **sans** installation complète : elle marche exactement comme avant. Ce qui marche :

- **En http (Wi-Fi de l'atelier)** : rien ne change. Sur Android (Chrome) ou iPhone (Safari), « Ajouter à l'écran
  d'accueil » met un raccourci avec l'icône « seau ». Pas de service worker.
- **En HTTPS par Tailscale (recommandé)** : Tailscale peut donner une adresse HTTPS à la page, avec un vrai
  certificat, sans ouvrir aucun port sur la box :
  1. Sur le site d'administration Tailscale (login.tailscale.com), onglet « DNS » : activer « MagicDNS » et
     « HTTPS Certificates ».
  2. Sur le Pi : `sudo tailscale serve --bg 8080` (puis `tailscale serve status` donne l'adresse du genre
     `https://vidange.tail1234.ts.net`). `tailscale serve` n'est **pas** `funnel` : seule ta liste d'appareils
     Tailscale peut s'y connecter, jamais Internet.
  3. Sur le téléphone (Tailscale allumé), ouvrir cette adresse https, se connecter, puis : Android Chrome, menu ⋮ →
     « Installer l'application » ; iPhone Safari, bouton Partager → « Sur l'écran d'accueil ».
  4. Attention : par `tailscale serve`, la page voit toutes les connexions comme venant du Pi lui-même
     (127.0.0.1). Le blocage après 5 mots de passe ratés est alors commun à tous, et le journal n'indique plus
     l'adresse du téléphone. À vérifier à l'essai (à noter dans la PR de suite si gênant).
- [ ] **Ce qu'on vérifie** : l'appli s'ouvre depuis l'icône, en plein écran, avec l'icône seau.
- [ ] **Jamais un vieil état** : avec l'appli ouverte, couper le Wi-Fi du téléphone (mode avion + Tailscale coupé)
      et relancer l'appli : elle dit « Le Pi ne répond pas », elle n'affiche **aucune** alarme, photo ni état
      gardé. Rallumer : tout revient en direct.
- [ ] **Après une mise à jour du programme du Pi** : l'appli montre la nouvelle version de la page (le numéro du
      cache est fabriqué à partir du contenu de la page, il change tout seul à chaque modification). Si besoin :
      fermer complètement l'appli et la rouvrir.
- Ce que le service worker garde : seulement la page, son code, ses icônes. Jamais une réponse de l'API.

## Si ça ne va pas

- Page Réglages vide ou « pas de réglages modifiables » : le programme n'a pas démarré avec la nouvelle version ;
  `journalctl -u vidange -n 50`.
- Le programme refuse de démarrer après modification de `modifiables.yaml` : le message dit quelle ligne (une ligne
  qui vise un réglage de mouvement est une erreur voulue).
- Un réglage changé par erreur à la main dans le fichier : `git -C /opt/vidange-auto diff pi/reglages`.
- Après la remise en état d'un Pi neuf (`essai-restauration.md`), les réglages changés depuis la page ne reviennent
  pas (les réglages viennent de Git) : lire l'historique (page, ou table `reglages_appliques` du registre restauré)
  et les refaire.
