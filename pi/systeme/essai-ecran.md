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

## En cas de problème

Envoyer à Claude (dans la PR ou une nouvelle session) les lignes du journal :
```
journalctl -u vidange --since "10 min ago" | grep -i "écran"
```
