# Essai de la fiabilité sur le vrai matériel (tâche 7)

**Testé sur le vrai matériel : non.** Les tests automatiques (GitHub Actions) n'utilisent qu'un **faux**
FluidNC et de **faux** capteurs. Cette procédure vérifie sur le vrai Pi : le chien de garde (programme figé,
Pi figé), la reconnaissance d'une coupure de courant, la santé du Pi, les cartes FluidNC débranchées, et
l'onduleur (quand il sera branché). Compter environ 1 h. **Aucun axe ne bouge pendant cet essai.**

Cocher chaque essai réussi. Si un résultat ne correspond pas, copier les dernières lignes du journal
(`journalctl -u vidange -n 50`) dans la PR ou dans une nouvelle tâche.

## Avant de commencer

- Le Pi est installé (`installation.md`), **y compris les étapes 6 et 7** (droit d'éteindre le Pi et
  chien de garde matériel), et le service a été réinstallé avec ce nouveau `vidange.service`
  (`sudo cp ... && sudo systemctl daemon-reload`, comme à l'étape 5).
- Moteurs **hors tension** (arrêt d'urgence enfoncé) : rien ne doit bouger.
- Dans les commandes ci-dessous, `vidange-registre` veut dire
  `sudo -u vidange /opt/vidange-auto/pi/.venv/bin/vidange-registre --donnees /var/lib/vidange`.

## 1. Démarrage et check-list

- [ ] `sudo systemctl restart vidange`, puis `systemctl status vidange` → « active (running) ».
      (Le service ne passe « active » qu'une fois que le programme a dit « prêt » à systemd.)
- [ ] `journalctl -u vidange -n 60` montre « Passage précédent : arrêt propre ... »,
      « Retour en lieu sûr proposé : il attend le Go », puis « Check-list de démarrage » avec la liste des
      points bloquants. Tant que les réglages sont des exemples, il y en a plusieurs : c'est normal.

## 2. Chien de garde : programme figé

- [ ] Figer le programme (sans l'arrêter) :
      ```
      sudo kill -STOP $(systemctl show -p MainPID --value vidange)
      ```
      Attendre 30 s. `journalctl -u vidange -n 20` montre « Watchdog timeout » puis un nouveau démarrage ;
      `systemctl status vidange` → de nouveau « active (running) » (avec un autre numéro de PID).
- [ ] Le journal du nouveau démarrage dit « Passage précédent : le programme a planté ».
- [ ] `vidange-registre etat` : la table `alarmes` a une ligne de plus (alarme « programme », à acquitter).

## 3. Chien de garde matériel : Pi figé (facultatif)

Cet essai fait planter tout le Pi exprès. Le faire machine à l'arrêt, après avoir vérifié l'étape 7 de
l'installation.

- [ ] `systemctl show -p RuntimeWatchdogUSec` → `RuntimeWatchdogUSec=14s`.
- [ ] `sudo sh -c 'echo c > /proc/sysrq-trigger'` : le Pi se fige (plus d'écran, plus de SSH).
      Dans les 20 s, il redémarre tout seul.
- [ ] Après le redémarrage, le journal dit « Passage précédent : le Pi s'est arrêté net, coupure de
      courant ? », et une alarme « alimentation » est ajoutée au registre.

## 4. Coupure de courant (sans onduleur)

- [ ] Programme en marche, débrancher l'alimentation du Pi pendant 10 s, puis la rebrancher.
- [ ] Après le redémarrage : « Passage précédent : le Pi s'est arrêté net, coupure de courant ? »,
      et une alarme « alimentation » de plus dans le registre.
- [ ] `ls /var/lib/vidange` montre toujours `etat-cycle.json` et `registre.sqlite` ;
      `vidange-registre etat` lit la base sans erreur.

## 4 bis. Reprise avec un objet encore tenu à la ventouse (tâche 45 nonies)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent qu'un faux capteur de vide. Il faut
le vrai capteur de vide branché (`vide_venturi` sans `exemple` dans `docs/entrees-sorties.yaml`) et l'air
comprimé. Fil Préhension (07/11) : sans courant, les électrovannes « aspirer » et « souffler » restent
fermées et le clapet anti-retour garde le vide ; l'objet tenu à la ventouse reste d'abord tenu, puis peut
tomber. Ce test ne protège que la machine et le seau : **la sécurité des personnes reste câblée**.

- [ ] Programme arrêté (`sudo systemctl stop vidange`), moteurs hors tension. Tenir à la main un **seau
      vide** (ou un couvercle) contre la ventouse et lancer `vidange-prehension vide` (vanne ouverte 5 s, puis
      refermée ; voir `essai-prehension.md`). Le seau reste tenu après la fermeture de la vanne. Noter
      combien de temps il tient (chronomètre) : c'est le temps inconnu du fil Préhension.
- [ ] Pendant qu'il est tenu, `sudo systemctl start vidange`. Le journal dit « Reprise : objet encore tenu
      à la ventouse (vide … kPa, plus bas que -20) : pas de Go tant qu'il n'est pas enlevé à la main ».
- [ ] L'écran de l'armoire dit « OBJET ENCORE TENU : PAS DE GO », la ligne du bas « Objet encore tenu à la
      ventouse (vide … kPa) : l'enlever à la main. » ; le bouton GO est éteint, un appui dit « Go
      impossible : … ». La page web dit la même chose en haut, sans bouton GO. La check-list (page web) a un
      point **bloquant** « objet tenu à la ventouse ».
- [ ] **Rien n'a bougé, rien n'a soufflé** (écouter : pas de souffle à la ventouse ; aucune prise d'origine).
- [ ] Enlever le seau à la main (décoller un bord). Dans la seconde (`fiabilite → objet_tenu → periode_s`), le
      journal dit « la ventouse ne tient plus rien … : Go permis », l'écran revient à « ATTEND LE GO ».
- [ ] Recommencer avec le seau tenu, puis couper l'alimentation de toute l'armoire 10 s (pas seulement le
      Pi). Au retour : même chose. L'alarme « alimentation » dit quoi faire, avec la ligne « vérifier la tête
      et le seau : enlever à la main l'objet tenu ou tombé avant le Go ».
- [ ] Avec une **capsule** aux électroaimants : à la coupure, elle doit tomber tout de suite (fil
      Préhension). Le dire si elle reste.
- [ ] Débrancher le capteur de vide, redémarrer : pas d'attente, mais la check-list dit « capteur de vide
      illisible … » en « attention », avec « vérifier la tête de préhension et le seau ».

## 4 ter. Vannes de la ventouse fermées au démarrage (tâche 45 decies)

**Testé sur le vrai matériel : non.** Les tests automatiques n'utilisent qu'une fausse carte FluidNC. Il faut la
carte de la préhension branchée, sa vanne `vanne_vide` (« aspirer ») câblée sans `exemple` dans
`docs/entrees-sorties.yaml` et dans `pi/reglages/fluidnc.yaml`, et l'air comprimé. Fil Préhension (07/11) :
après un plantage du Pi, « aspirer » peut rester ouverte (rien de matériel ne la coupe ; pas dangereux : le
venturi souffle). Au démarrage, le Pi **ferme** « aspirer » (et « souffler » le jour où elle sera câblée),
**puis** lit le vide. C'est la seule commande du démarrage : il n'ouvre jamais rien et ne bouge rien. Ce test ne
protège que la machine : **la sécurité des personnes reste câblée**.

- [ ] Programme arrêté (`sudo systemctl stop vidange`), moteurs hors tension, rien contre la ventouse. Ouvrir
      la vanne « aspirer » à la main depuis la console de la carte de la préhension (`M64 P<numéro de
      vanne_vide dans fluidnc.yaml>`) : le venturi souffle (on l'entend). Laisser la carte sous tension et
      sans la débrancher : c'est l'état d'après un plantage du Pi.
- [ ] `sudo systemctl start vidange`. Dans les 5 s (`fiabilite → objet_tenu → attente_vannes_s`), le venturi
      **s'arrête de souffler**. Le journal dit « Démarrage : vannes de la ventouse fermées (vanne_vide) ;
      rien d'autre n'est commandé ». La check-list (page web) a un point **ok** « vannes de la ventouse :
      fermées au démarrage ».
- [ ] **Rien n'a bougé, rien n'a soufflé** pour lâcher (aucune prise d'origine, aucun mouvement) ; le
      retour en lieu sûr attend le Go comme d'habitude.
- [ ] Recommencer avec un **seau vide tenu à la main** contre la ventouse pendant que « aspirer » est
      ouverte, puis lâcher le seau (il reste tenu), puis `sudo systemctl start vidange` : la vanne se
      ferme, le seau **reste tenu** (le clapet garde le vide), puis le § 4 bis se déroule (« objet encore
      tenu », pas de Go). Enlever le seau à la main.
- [ ] Carte de la préhension débranchée (câble USB), redémarrer : pas d'attente longue, la check-list dit
      « vannes de la ventouse » en **attention** (« vanne_vide pas fermée(s) : … »), avec « ne jamais ouvrir
      « souffler » pour lâcher un objet à la reprise : l'enlever à la main ».
- [ ] Mesurer le temps entre le lancement et la fermeture (journal). S'il faut plus de 5 s à la carte pour se
      connecter, le dire à Claude (réglage `attente_vannes_s`).
- [ ] Dire à Claude si la carte de la préhension redémarre quand le Pi ouvre son port USB (ses sorties se
      coupent alors toutes seules) et si elle démarre en alarme (FluidNC refuse alors « M65 » : la
      check-list le dit en attention).

## 5. Santé du Pi

- [ ] Comparer avec le Pi lui-même : `vcgencmd measure_temp` (température) et `vcgencmd get_throttled`
      (doit dire `throttled=0x0` ; sinon l'alimentation est trop faible et le journal le dit :
      « Santé du Pi, alimentation du Pi : tension trop faible »).
- [ ] Attendre 10 min : `vidange-registre etat` montre que la table `mesures` grandit
      (3 mesures toutes les 5 min : température, disque libre, mémoire libre).

## 6. Cartes FluidNC (quand leurs vrais numéros de série sont dans `fluidnc.yaml`)

- [ ] Toutes les cartes branchées et allumées : la check-list du journal ne cite plus de
      « carte ... pas connectée ». Juste après la mise sous tension, une carte est « en alarme »
      (prise d'origine à faire) : c'est normal.
- [ ] Débrancher le câble USB d'une carte : le journal dit « Liaison avec la carte « ... » coupée ».
      Le rebrancher : « Carte « ... » connectée ».
- [ ] Appuyer sur le bouton de redémarrage (EN/RST) de la carte : le journal dit « La carte « ... » a
      redémarré toute seule (1 fois ...) ».

Le retour en lieu sûr (prises d'origine, Go de Karulium) se fera sur la vraie machine quand la page web
ou l'écran sauront donner le Go (tâches 8 et 9), et quand `lieu_sur` de `machine.yaml` sera rempli avec
les vrais modules : **ne pas le lancer avec les valeurs d'exemple**.

## 7. Onduleur (quand il est branché et son signal dans la liste)

Le signal `onduleur_sur_batterie` de `docs/entrees-sorties.yaml` doit être vrai (broche juste,
`exemple` enlevé). Vérifier d'abord, programme arrêté (`sudo systemctl stop vidange`), avec
`vidange-es surveiller onduleur_sur_batterie` (voir `essai-entrees-sorties.md`) que l'entrée passe à
« actionnée » quand on débranche le secteur. Puis `sudo systemctl start vidange`.

- [ ] Débrancher le secteur 20 s, puis le rebrancher : le journal dit « Courant coupé : le Pi tient sur
      l'onduleur. Machine en pause », puis « Courant revenu après 20 s. La machine reste en pause ».
- [ ] Débrancher le secteur plus longtemps que `delai_avant_arret_s` (60 s) : le journal dit « arrêt
      propre du programme, puis du Pi », et le Pi s'éteint (voyant vert éteint).
- [ ] Rebrancher le secteur (et rallumer le Pi s'il ne repart pas seul) : le journal dit
      « Passage précédent : arrêt propre le ... (onduleur) », sans alarme « alimentation ».
