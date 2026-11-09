# Essai de l'écran Nextion de l'armoire avec le vrai Pi

Testé sur le vrai matériel : **non** (seulement avec un faux écran, sur un PC et dans GitHub Actions).

À faire après l'installation (`installation.md`) et après avoir monté les pages dans Nextion Editor
(`nextion/pages.md`). La machine n'a pas besoin de bouger. Cocher chaque essai réussi.

## Préparer

1. **Câbler l'écran** (Pi éteint) :
   - fil TX de l'écran → **GPIO5** du Pi (broche n° 29, RX du Pi) ;
   - fil RX de l'écran → **GPIO4** du Pi (broche n° 7, TX du Pi) ;
   - masse (GND) de l'écran → une masse du Pi (broche n° 9 par exemple) ;
   - +5 V de l'écran → l'alimentation 5 V de l'armoire (pas la broche 5 V du Pi si possible : l'écran
     peut tirer jusqu'à 0,5 A). Les masses de l'alimentation et du Pi doivent être reliées.
   Les signaux de l'écran sont en 3,3 V : pas besoin d'adaptateur.
2. **Allumer l'UART n° 2 du Pi 5** (celle des GPIO 4 et 5) : ajouter cette ligne à la fin de
   `/boot/firmware/config.txt`, puis redémarrer le Pi :
   ```
   sudo nano /boot/firmware/config.txt        # ajouter : dtoverlay=uart2-pi5
   sudo reboot
   ls -l /dev/ttyAMA2                          # doit exister après le redémarrage
   ```
3. Vérifier que `docs/entrees-sorties.yaml` dit bien `fichier: /dev/ttyAMA2` pour `ecran_nextion`, et que
   `vitesse_bauds` (dans `pi/reglages/programme.yaml`, partie `ecran`) est la même que `baud=` dans Program.s
   du projet Nextion (115200 conseillé).
4. Relancer le programme et lire le journal :
   ```
   sudo systemctl restart vidange
   journalctl -u vidange -n 80 | grep -i "écran"
   ```
   Le journal doit dire « Écran : port série ouvert » puis « Écran : il répond ».
   S'il dit « il ne répond pas » : vérifier la vitesse (étape 3), puis inverser TX et RX (étape 1).

## Essais

- [ ] **Page d'état** : l'écran montre la page « etat ». Au démarrage, le retour en lieu sûr attend le Go :
      bandeau **jaune** « ATTEND LE GO », bouton GO jaune, « Mode : Production ».
- [ ] **Accents** : « À L'ARRÊT », « étape », « Fûts » s'affichent bien. Sinon : régénérer les polices en
      iso-8859-1 (`nextion/pages.md`).
- [ ] **Avec des gants** : chaque bouton se touche facilement avec les gants de l'atelier.
- [ ] **Go avec confirmation** : appuyer sur GO → page « À CONFIRMER » avec la question. Appuyer sur NON →
      retour à l'état, rien ne bouge. Appuyer sur GO puis ne rien toucher pendant 15 s → retour à l'état tout
      seul. (Ne pas répondre OUI si la machine n'est pas prête à bouger.)
- [ ] **Pause** : appuyer sur PAUSE → bandeau **orange** « EN PAUSE », bouton REPRENDRE vert ; le journal dit
      « Pause demandée à l'écran de l'armoire ». La page web montre aussi la pause. REPRENDRE demande OUI.
- [ ] **Alarme** : provoquer une alarme sans danger (par exemple débrancher le câble USB d'une carte FluidNC
      pendant qu'elle attend). La page **rouge** « ALARME » arrive toute seule, avec « quoi faire ».
      Si le texte est long, SUITE montre la suite. RETOUR → bandeau rouge « ALARME (1) : TOUCHER ICI » ;
      le toucher ramène l'alarme. Rebrancher, puis RÉPARÉ → l'alarme disparaît (la page web la montre
      « acquittée par l'écran de l'armoire »).
- [ ] **Compteurs** : COMPTEURS montre les quatre lignes ; sans appui, retour à l'état au bout d'une minute.
- [ ] **Mode** : MODE → le bouton PRODUCTION est bleu. Pendant le retour en lieu sûr, LAVAGE est refusé
      (« Impossible : pas pendant un cycle »). Une fois le lieu sûr fini (ou abandonné), LAVAGE → OUI →
      bandeau « MODE : LAVAGE » ; sur la page d'état, « Mode : Lavage » sur fond bleu. Remettre PRODUCTION.
- [ ] **Écran éteint puis rallumé** : couper le 5 V de l'écran 10 s. Le journal dit « il ne répond pas ».
      Rallumer : en quelques secondes, l'écran remontre la bonne page avec les bonnes valeurs.
- [ ] **Câble débranché** : débrancher le fil TX de l'écran. La machine continue (la page web marche) ;
      la check-list du journal (ou de la page web) dit « écran de l'armoire : il ne répond pas ».
      Rebrancher : tout revient seul.
- [ ] **Objet mal nommé** (facultatif) : renommer un texte dans Nextion Editor (exemple `t_mode` → `t_mod`),
      envoyer le projet : le journal dit « objet inconnu sur la page « etat » : comparer la page avec
      nextion/pages.md ». Remettre le bon nom.

## Code des fonctions sensibles (tâche 29)

Ce code **évite les fausses manoeuvres**. Il **ne protège pas les personnes** : l'arrêt d'urgence, les portes
et les fins de course de sécurité sont câblés en dur, le logiciel n'y est pour rien.

**1. Ajouter la page « code » dans Nextion Editor** (nouvelle page, numéro **7**, après « nettoyage ») :
tout est décrit dans `nextion/pages.md`, « Page 7 : « code » ». En résumé, il faut créer, avec exactement ces noms :
- 3 textes : `t_titre`, `t_saisie`, `t_info` ;
- 12 boutons : `b_0`, `b_1`, `b_2`, `b_3`, `b_4`, `b_5`, `b_6`, `b_7`, `b_8`, `b_9`, `b_effacer`, `b_retour` ;
- dans « Touch Release Event » de chaque bouton, les deux lignes habituelles (`prints "@b_5",0` puis
  `printh FF FF FF`, avec le nom du bouton) ;
- les autres pages ne changent pas. Compiler, copier le `.tft` sur la carte micro-SD, mettre à jour l'écran.

**2. Régler le code** (sur le Pi, avec le compte du programme ; la commande le demande deux fois, il ne
s'affiche pas) :
```
sudo -u vidange VIDANGE_SECRETS=/etc/vidange/secrets.yaml /opt/vidange-auto/pi/.venv/bin/vidange code-ecran
```

**Essais** (la machine n'a pas besoin de bouger ; ne pas répondre OUI à une question si la machine n'est pas prête) :
- [ ] **Sans code réglé** (avant l'étape 2, ou après `vidange code-ecran --retirer`) : MODE → LAVAGE :
      l'écran reste sur la page du mode et dit « Code de l'écran pas réglé : lancer « vidange code-ecran »... ».
      La check-list (page web ou journal) dit « code de l'écran : pas réglé » (attention, pas bloquant).
- [ ] **Clavier** : après avoir réglé le code (et abandonné le module d'essai ou fini le lieu sûr), MODE → LAVAGE :
      la page « CODE » arrive, avec `----` en haut. Chaque chiffre touché ajoute un `*`. EFFACER enlève le
      dernier. Les chiffres se touchent facilement avec les gants.
- [ ] **Code juste** : les 4 chiffres tapés, la page du mode revient avec la question « Passer en mode Lavage ? »
      (pas de bouton OK à toucher). NON pour finir. Le journal dit « code juste pour « changer_mode » ».
- [ ] **Code faux** : taper un mauvais code : « Code faux. Encore 2 essai(s). ». Taper 3 mauvais codes de suite :
      retour à la page du mode avec « Trop de codes faux : attendre 60 s. ». Pendant ces 60 s, même le bon code
      est refusé ; après, il passe.
- [ ] **Le code reste valable un court moment** : taper le bon code, répondre NON, retoucher LAVAGE dans les
      30 s : pas de nouveau code (la question vient tout de suite). Attendre plus de 30 s : le code est
      redemandé.
- [ ] **Sans toucher** : sur la page « CODE », ne rien toucher 15 s : retour à la page d'état. RETOUR : retour
      tout de suite.
- [ ] **Enceinte** : MODE → ENCEINTE : OUVRIR (ou FERMER), NUIT et PASSER OUTRE demandent le code (s'il n'est pas
      déjà valable) ; LUMIÈRE n'en demande jamais.
- [ ] **Ce qui ne demande jamais de code** : PAUSE, REPRENDRE (avec OUI), GO (avec OUI), COMPTEURS, RÉPARÉ, PRÊT du
      poste du fût.
- [ ] **Journal des actions** : après un changement de mode réussi, sur le téléphone ou le PC (compte `karulium`),
      la page web, ou sur le Pi :
      `tail -3 /opt/vidange-auto/pi/donnees/actions.jsonl` : une ligne `"qui": "écran"`, `"chemin":
      "ecran/changer_mode"`, `"detail": "lavage"`. Jamais le code, jamais un nom de personne.
- [ ] **Changer le code** : relancer `vidange code-ecran` avec un autre code, sans redémarrer : l'ancien code est
      refusé, le nouveau passe.
- [ ] **Sauvegarde** : le fichier `/etc/vidange/code_ecran.yaml` n'est pas dans la copie quotidienne (comme
      `secrets.yaml`) : après la restauration d'un Pi neuf, refaire `vidange code-ecran`.

## En cas de problème

Envoyer à Claude (dans la PR ou une nouvelle session) les lignes du journal :
```
journalctl -u vidange --since "10 min ago" | grep -i "écran"
```
