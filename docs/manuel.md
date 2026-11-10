# Manuel d'utilisation

*Fichier fabriqué par `vidange manuel` à partir des réglages et des textes du programme : ne pas le modifier à la main (un test vérifie qu'il est à jour).*

## Avant tout : la sécurité

La sécurité des personnes est câblée : arrêt d'urgence, portes, fins de course de sécurité, freins. Le logiciel (et ce guide) ne la remplace pas. En cas de doute, appuyer sur l'arrêt d'urgence, puis demander à Karulium.

Le guide ne fait bouger aucun axe : il explique, la personne fait les gestes à la main, machine à l'arrêt, puis dit « Fait ».

## Qui peut faire quoi

- **Visiteur** : regarde (état, historique, photos, caméras), ne commande rien.
- **Employé** : regarde et produit : Pause, Reprise, Go, lots, nettoyage, poste du fût, carnet de bord, acquitter une alarme, et suivre un travail guidé (onglet « Aide » ou page « guide » de l'écran).
- **Karulium** : tout, y compris les réglages, les mises à jour, la maintenance (bouton « Fait ») et le pilotage à distance.

## Les modes de la machine

On change de mode machine au repos, depuis l'écran (page « mode », avec le code) ou la page web.

- **Production** (`production`)
- **Lavage** (`lavage`)
- **UV-ozone** (`uv_ozone`)
- **Maïs** (`mais`)

## Les travaux guidés

**Mettre un fût au poste** (`changer_fut`) (exemple à relire sur place). Quand : Quand le fût en cours est vide et qu'un nouveau fût attend à côté du poste.

1. Machine à l'arrêt et plateau du fût sorti. Poser le fût debout sur le plateau, entre les 4 cales.
2. Enlever la soupape du couvercle (trou bouché).
3. Pousser le plateau contre les 2 butées d'angle du fond. (la machine regarde : `plateau_fut_en_place`)
4. Freiner les 2 roulettes.
5. Rabattre le grand volet, lever le panneau long. (la machine regarde : `reed_panneau_poste_fut`)
6. Appuyer sur PRÊT (écran ou page web) quand tout est fait.

**Vider le bidon de purge** (`vider_bidon_purge`) (exemple à relire sur place). Quand : Quand le rappel « vider le bidon de purge » apparaît (réglage rappel_bidon_jours de air.yaml).

1. Machine à l'arrêt. Sortir le bidon de purge de l'air comprimé, posé au sol.
2. Le vider à l'endroit prévu pour les liquides de l'atelier, puis le remettre en place.
3. Prévenir Karulium que le bidon est vidé : le rappel doit repartir de zéro.

**Reprendre après une coupure** (`reprise_apres_coupure`) (exemple à relire sur place). Quand : Quand l'écran dit que le programme a redémarré en plein cycle (coupure de courant ou plantage).

1. Regarder la machine (seau en cours, axes) sans rien déplacer qui soit coincé.
2. Enlever à la main l'objet tenu ou tombé (tête, seau) avant le Go.
3. Lancer « lieu sûr » depuis l'écran (prise d'origine des axes).
4. Quand la check-list est verte, donner le Go pour reprendre.

## L'entretien

- **Rails et transmission du pont du portique (axe X, deux moteurs)** (`pont_x`) : tous les 20000 (distance) (limite d'exemple). À faire : Contrôler l'état et le jeu des rails et de la transmission du pont (les deux côtés), nettoyer et graisser comme le dit la fiche mécanique, puis cliquer « Fait ».
- **Rail et transmission du chariot du portique (axe Y)** (`chariot_y`) : tous les 20000 (distance) (limite d'exemple). À faire : Contrôler l'état et le jeu du rail et de la transmission du chariot, nettoyer et graisser comme le dit la fiche mécanique, puis cliquer « Fait ».
- **Pignon et crémaillère du Z de la griffe** (`griffe_z`) : tous les 10000 (distance) (limite d'exemple). À faire : Contrôler la crémaillère et le pignon (usure, propreté, jeu), nettoyer et graisser comme le dit la fiche mécanique, puis cliquer « Fait ».
- **Vis à billes du godet de la griffe** (`griffe_b`) : tous les 2000 (distance) (limite d'exemple). À faire : Contrôler la vis à billes du godet (jeu, propreté, graisse), nettoyer et graisser comme le dit la fiche mécanique, puis cliquer « Fait ».
- **Rail et transmission du Z de la préhension** (`prehension_z`) : tous les 10000 (distance) (limite d'exemple). À faire : Contrôler le guidage et la transmission du Z de la préhension, nettoyer et graisser comme le dit la fiche mécanique, puis cliquer « Fait ».
- **Rail et transmission de l'avance du chariot de remplissage** (`remplissage_y`) : tous les 10000 (distance) (limite d'exemple). À faire : Contrôler le rail et la transmission de l'avance du chariot de remplissage, nettoyer et graisser comme le dit la fiche mécanique, puis cliquer « Fait ».
- **Guidage et transmission du Z du plateau du remplissage** (`plateau_z`) : tous les 5000 (distance) (limite d'exemple). À faire : Contrôler le guidage et la transmission du Z du plateau, nettoyer et graisser comme le dit la fiche mécanique, puis cliquer « Fait ».
- **Rotation du noyau du lavage (heures de marche)** (`lavage_noyau`) : tous les 500 (heures) (limite d'exemple). À faire : Contrôler la rotation du noyau du lavage (jeu, bruit, étanchéité) comme le dit la fiche mécanique, puis cliquer « Fait ».
- **Frein du Z de la griffe** (`frein_griffe_z`) : tous les 200000 (manoeuvres) (limite d'exemple). À faire : Contrôler le frein du Z de la griffe (il doit tenir l'axe à l'arrêt, sans traîner), puis cliquer « Fait ». Si le frein est changé : « Fait » aussi.
- **Frein du Z de la préhension** (`frein_prehension_z`) : tous les 200000 (manoeuvres) (limite d'exemple). À faire : Contrôler le frein du Z de la préhension (il doit tenir l'axe à l'arrêt, sans traîner), puis cliquer « Fait ». Si le frein est changé : « Fait » aussi.
- **Électrovanne « aspirer » de la ventouse** (`vanne_vide`) : tous les 500000 (manoeuvres) (limite d'exemple). À faire : Contrôler l'électrovanne « aspirer » (fuite, bruit, temps de réponse du vide), la changer si besoin, puis cliquer « Fait ».
- **Électrovanne « souffler » de la ventouse** (`vanne_souffler`) : tous les 500000 (manoeuvres) (limite d'exemple). À faire : Contrôler l'électrovanne « souffler » (fuite, bruit, objet qui se lâche bien), la changer si besoin, puis cliquer « Fait ».
- **Électroaimants de la capsule (préhension)** (`electroaimants_capsule`) : tous les 200000 (manoeuvres) (limite d'exemple). À faire : Contrôler les électroaimants (tenue de la capsule, échauffement, câble), puis cliquer « Fait ».
- **Électroaimant du verrou du plateau du porte-bocal** (`electroaimant_verrou_plateau`) : tous les 200000 (manoeuvres) (limite d'exemple). À faire : Contrôler l'électroaimant et le verrou du plateau (tenue, jeu), puis cliquer « Fait ».
- **Relais du compresseur** (`relais_compresseur`) : tous les 100000 (manoeuvres) (limite d'exemple). À faire : Contrôler le relais du compresseur (contacts, échauffement), le changer si besoin, puis cliquer « Fait ».
- **Contrôle du lavage (rampes, buses, vannes) selon le nombre de seaux** (`controle_lavage`) : tous les 1000 (seaux) (limite d'exemple). À faire : Contrôler les rampes, les buses et les vannes du lavage (bouchage, fuite, jets), puis cliquer « Fait ».
- **Tour général de la machine (vis, câbles, propreté)** (`tour_general`) : tous les 90 (jours) (limite d'exemple). À faire : Faire le tour de la machine : vis et fixations, câbles et chaînes porte-câbles, fins de course, propreté, puis cliquer « Fait ».

## Les alarmes : quoi faire

Chaque alarme dit ce qui s'est passé et quoi faire ; en voici le catalogue.

- **Alarme 1 d'une carte, fin de course matérielle touchée** : Un axe a touché un fin de course : chercher pourquoi (obstacle, axe qui a glissé, position mal réglée). Dégager l'axe sans desserrer le frein d'un axe vertical, débloquer la carte, lancer « lieu sûr » depuis l'écran (prise d'origine des axes), puis acquitter.
- **Alarme 2 d'une carte, mouvement demandé hors des limites logicielles** : Le programme a demandé une position hors de la course permise : erreur de réglage (machine.yaml ou réglages FluidNC). Noter l'étape et le message, faire corriger le réglage ; débloquer la carte, puis acquitter.
- **Alarme 3 d'une carte, réinitialisation pendant un mouvement : position perdue** : La carte a été réinitialisée pendant un mouvement : elle ne sait plus où sont ses axes. Débloquer la carte, lancer « lieu sûr » depuis l'écran (prise d'origine des axes), puis acquitter.
- **Alarme 4 d'une carte, palpeur : déjà touché au départ** : Palpeur déjà touché au départ : vérifier le palpeur et son câble, puis acquitter.
- **Alarme 5 d'une carte, palpeur : rien touché** : Le palpeur n'a rien touché : vérifier la pièce, le palpeur et son câble, puis acquitter.
- **Alarme 6 d'une carte, prise d'origine interrompue par une réinitialisation** : La prise d'origine a échoué : vérifier le fin de course de l'axe (câble, voyant, saleté) et que rien ne bloque l'axe, débloquer la carte, puis relancer « lieu sûr ».
- **Alarme 7 d'une carte, prise d'origine interrompue par l'ouverture d'une porte** : La prise d'origine a échoué : vérifier le fin de course de l'axe (câble, voyant, saleté) et que rien ne bloque l'axe, débloquer la carte, puis relancer « lieu sûr ».
- **Alarme 8 d'une carte, prise d'origine : le fin de course ne se libère pas** : La prise d'origine a échoué : vérifier le fin de course de l'axe (câble, voyant, saleté) et que rien ne bloque l'axe, débloquer la carte, puis relancer « lieu sûr ».
- **Alarme 9 d'une carte, prise d'origine : fin de course jamais atteint** : La prise d'origine a échoué : vérifier le fin de course de l'axe (câble, voyant, saleté) et que rien ne bloque l'axe, débloquer la carte, puis relancer « lieu sûr ».
- **Alarme 10 d'une carte, commande de broche (moteur d'outil) en défaut** : Commande de moteur d'outil en défaut : vérifier le pilote et son câble.
- **Alarme 11 d'une carte, une entrée de commande est active au démarrage** : Une entrée de commande de la carte (pause, arrêt, porte) est active à son démarrage : vérifier le bouton ou le capteur et son câble, puis débloquer la carte.
- **Alarme 12 d'une carte, prise d'origine : fin de course ambigu** : La prise d'origine a échoué : vérifier le fin de course de l'axe (câble, voyant, saleté) et que rien ne bloque l'axe, débloquer la carte, puis relancer « lieu sûr ».
- **Alarme 13 d'une carte, arrêt dur** : Arrêt dur de la carte (arrêt d'urgence, défaut d'un pilote) : remettre la sécurité en état, regarder le voyant des pilotes, débloquer la carte, lancer « lieu sûr » depuis l'écran (prise d'origine des axes).
- **Alarme 14 d'une carte, position inconnue : prise d'origine à faire** : La carte ne connaît pas la position de ses axes (mise sous tension) : lancer « lieu sûr » depuis l'écran (prise d'origine des axes).
- **Alarme 15 d'une carte, erreur au démarrage de la carte** : La carte a une erreur à son démarrage : lire son message (commande vidange-fluidnc), vérifier son fichier de réglages, puis la redémarrer.
- **Alarme 16 d'une carte, carte d'extension réinitialisée** : Une carte d'extension a redémarré : vérifier son alimentation et ses câbles.
- **Carte coupée** : La liaison USB avec la carte est coupée : vérifier son câble USB et son alimentation. Elle se reconnecte seule. Si elle a redémarré, lancer « lieu sûr » depuis l'écran (prise d'origine des axes). Puis acquitter.
- **Carte redémarrée** : La carte a redémarré toute seule (alimentation, parasite, câble USB) : vérifier son alimentation et ses câbles, lancer « lieu sûr » depuis l'écran (prise d'origine des axes), puis acquitter.
- **Ordre refusé par une carte** : La carte a refusé un ordre : erreur du programme ou d'un réglage. Noter le message et l'étape, faire corriger ; débloquer la carte si elle est en alarme, puis acquitter.
- **Capteur muet** : Un capteur ou une carte d'entrées/sorties ne répond pas (son nom est dans le message) : vérifier son câble et son alimentation, puis acquitter.
- **Erreur imprévue du programme** : Erreur imprévue du programme : noter le message (il est aussi dans le journal) et le signaler pour correction. Vérifier la machine, puis acquitter.
- **Reprise après coupure de courant** : Le Pi s'est arrêté net (coupure de courant ?) en plein cycle. Regarder la machine (seau en cours, axes), vérifier la tête et le seau : enlever à la main l'objet tenu ou tombé avant le Go, lancer « lieu sûr » depuis l'écran (prise d'origine des axes), puis donner le Go pour reprendre.
- **Reprise après plantage du programme** : Le programme du Pi a planté puis a été relancé. Regarder la machine et le journal, vérifier la tête et le seau : enlever à la main l'objet tenu ou tombé avant le Go, puis donner le Go pour reprendre ; signaler le plantage pour correction.
