# Essai de l'entretien (compteurs, pièces d'usure, page « Maintenance ») sur le vrai Pi

Testé sur le vrai matériel : **non** (seulement sur un PC et dans GitHub Actions, avec de fausses cartes et de
faux compteurs). Toutes les limites d'usure de `pi/reglages/entretien.yaml` sont des **EXEMPLES** : personne ne
connaît encore les vraies durées de vie. Cet essai vérifie que les compteurs bougent comme la machine, que la
page les montre, et que l'alerte et le bouton « Fait » marchent. Il ne dit rien de l'usure réelle.

À faire après l'installation (`installation.md`) et l'essai des comptes (`essai-comptes.md`). La page web demande
un compte ; le bouton « Fait » demande le rôle « karulium ». Dans les commandes, `vidange` veut dire :
```
sudo -u vidange VIDANGE_SECRETS=/etc/vidange/secrets.yaml /opt/vidange-auto/pi/.venv/bin/vidange
```
Les compteurs sont dans `/var/lib/vidange/entretien.json` (le dossier des données, avec le registre).
Cocher chaque essai réussi.

## 1. Les réglages sont lus

- [ ] `vidange --verifier` dit « Réglages corrects » et une ligne « entretien.yaml : limites d'usure
      d'EXEMPLE ». C'est normal tant que les limites ne sont pas vraies.
- [ ] **Une faute est refusée** : dans `entretien.yaml`, remplacer `de: pont_x}` par `de: pont_z}` (un axe qui
      n'existe pas) : `vidange --verifier` s'arrête en disant « entretien.yaml, pieces → pont_x ... l'axe « pont_z »
      n'est pas dans machine.yaml ». Remettre `pont_x`.

## 2. Les axes bougent, les compteurs suivent

La machine doit pouvoir bouger sans danger (rien dans l'axe, arrêt d'urgence à portée de main).

- [ ] Ouvrir la page, onglet **Maintenance**, tableau « Compteurs des axes ». Noter la ligne `pont_x`
      (distance, mouvements, heures de marche).
- [ ] Faire bouger le pont de **0,5 m environ** (pilotage à distance, ou un petit geste depuis l'écran). Revenir
      sur l'onglet (ou le quitter puis le rouvrir) : la distance de `pont_x` a augmenté d'**environ 0,5 m** (à
      quelques % près), les mouvements de 1 (ou 2 aller-retour), les heures de quelques secondes.
- [ ] Comparer avec ce que le pilotage à distance a fait : si l'écart dépasse **10 %**, noter les deux nombres
      pour la PR (le seuil `seuil_mouvement_mm` ou la période d'état des cartes est peut-être à revoir).
- [ ] Un axe qui n'a pas bougé (par exemple `chariot_y`) garde ses nombres.
- [ ] Un axe tournant (`griffe_a`) : sa distance est en degrés (« ° »).

## 3. Les sorties comptent leurs manœuvres

- [ ] Tableau « Manœuvres des sorties » : noter `vanne_vide`.
- [ ] Faire une prise de la ventouse (un geste qui aspire, par exemple depuis la préhension) : `vanne_vide`
      augmente d'**1 par aspiration**, pas plus (redemander « allumé » à une sortie déjà allumée ne compte pas).
- [ ] Un relais du Pi : `relais_compresseur` compte 1 à chaque fois que le compresseur est (re)autorisé.

## 4. Les compteurs survivent à un arrêt

- [ ] Attendre 5 minutes (`ecriture_periode_s`), ou arrêter le programme proprement :
      `sudo systemctl stop vidange`. Le fichier `/var/lib/vidange/entretien.json` existe et contient les nombres notés
      (`sudo cat /var/lib/vidange/entretien.json`).
- [ ] `sudo systemctl start vidange` : les compteurs de la page sont les mêmes qu'avant l'arrêt.
- [ ] **Pas d'écriture à chaque geste** : pendant que la machine bouge, la date du fichier
      (`ls -l --time-style=full-iso`) ne change pas plus d'une fois toutes les 5 minutes.
- [ ] **Coupure de courant** : couper le courant du Pi **sans** l'arrêter, quelques minutes après un mouvement.
      Au retour, les compteurs ont perdu au plus les 5 dernières minutes (c'est voulu). Noter ce qui manque.
- [ ] **La copie de secours** : après la copie du jour (`essai-restauration.md`), l'archive
      `fichiers-AAAA-MM-JJ.tar.gz` contient `donnees/entretien.json` (le dossier s'appelle `donnees` dans l'archive).

## 5. L'alerte « bientôt » puis « à faire »

On triche avec le calendrier : le « tour général » (90 jours d'exemple).

- [ ] Dans la page, la pièce « Tour général de la machine » est « en bon état » (0 %).
- [ ] Arrêter le programme. Dans `/var/lib/vidange/entretien.json`, section `departs` → `tour_general` → `date`, mettre une
      date de **il y a 85 jours** (format `2026-08-15T08:00:00-04:00`). Relancer.
- [ ] La page dit « BIENTÔT À FAIRE » (carte orange) avec « Quoi faire » ; la check-list (onglet Check-list) a
      une ligne « entretien : Tour général de la machine » en **attention** (jamais en rouge) ; le journal
      (`journalctl -u vidange | grep Entretien`) a une ligne « Entretien bientôt à faire » (une seule, même après
      plusieurs minutes).
- [ ] Même chose avec une date d'il y a **100 jours** : « À FAIRE » (carte rouge), journal « Entretien À FAIRE ».
- [ ] **La machine n'est jamais arrêtée par cette alerte** : la check-list dit toujours que la production peut
      être lancée (si rien d'autre n'est rouge), le Go se donne comme d'habitude.

## 6. Le bouton « Fait »

- [ ] Avec le compte **invite** et le compte **aide** : le bouton « Fait » est grisé ; si on force l'appel, la page
      dit « droit insuffisant ».
- [ ] Avec le compte **karulium** : appuyer sur « Fait » du tour général, confirmer. La pièce repasse « en bon
      état » à 0 % avec « fait par karulium » et l'heure.
- [ ] Le compteur à vie des axes n'a **pas** été remis à zéro (seule la pièce repart de zéro).
- [ ] Le journal des actions (`GET /api/actions`, ou la page de Karulium) a une ligne avec le nom, le rôle, et
      `/api/entretien/tour_general/fait`. Le registre a une ligne notée « entretien fait : Tour général de la
      machine » (`sqlite3 /var/lib/vidange/registre.sqlite "select quand, qui, reglage, raison from reglages_appliques order by id desc limit 3"`).
- [ ] Redémarrer : la pièce reste à 0 % « fait par karulium ».

## À noter pour la PR

Les écarts de la section 2 (distance comptée contre distance réelle), ce qui a manqué après la coupure (section 4),
et tout ce qui a surpris. Les **vraies limites** viendront ensuite : `entretien.yaml` ne devient juste que quand
Karulium (ou les fiches des fournisseurs) donne les vraies durées de vie.
