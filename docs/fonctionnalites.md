# Fonctionnalités retenues par Karulium (26/10/2026)

Numéros de la liste d'idées (document « Idées pour le logiciel de la machine »).
Les fonctions sont rangées par tâche dans `docs/taches.md`.

## Retenues

- **Production** : 1 cycle complet ; 2 mode pas à pas ; 3 reprise après coupure de courant (état noté sans cesse,
  retour des axes en lieu sûr, reprise au bon seau) ; 4 arrêt propre sur onduleur ; 7 estimation de fin en direct,
  **qui s'améliore avec les cycles précédents** ; 8 pause à la fin du seau en cours ; 10 mode à vide.
- **Fiabilité** : 12 check-list de démarrage ; 13 programme vérifié par le simulateur avant envoi ; 14 surveillance
  mutuelle Pi ↔ cartes (chien de garde) ; 15 dérive de position (consigne contre pilotes boucle fermée) ;
  16 photo avant/après chaque geste ; 17 bilan après chaque alarme (clip 60 s, positions, capteurs) ;
  18 « quoi faire » pour chaque alarme ; 19 température et humidité de l'armoire (capteur à ajouter).
- **Vision et qualité** : 21 hauteur de remplissage de chaque seau ; 22 contrôle des bocaux de mycélium avant usage ;
  23 contrôle du micropore et du couvercle ; 24 QR illisible → alerte et mise de côté, **pour les seaux, les bocaux
  et les boîtes de Pétri** ; 27 température du substrat à chaque seau ; 28 réentraînement de la vision (sur le PC,
  lancé par Karulium, installé après son accord).
- **Traçabilité** : 29 fiche complète de chaque seau ; 31 envoi automatique vers le logiciel de culture ;
  33 historique des réglages ; 75 **le maximum de données pour chaque Pétri, bocal et seau**.
- **Hygiène** : 35 journal d'hygiène ; 39 lien entre nettoyages et contaminations (avec les données Django).
- **Entretien** : 40 compteurs par axe ; 41 calendrier d'entretien ; 42 alerte d'usure ; 43 page maintenance ;
  44 liste des pièces d'usure ; 45 santé de l'informatique.
- **Écran de l'armoire** : 46 grands boutons utilisables avec des gants ; 47 code couleur ; 48 alarme et « quoi faire »
  en 2 lignes ; 49 voyant et buzzer « attention » (à ajouter) ; 50 code pour les fonctions sensibles.
- **Page web et téléphone** : 51 tableau de bord ; 52 vidéos en direct et clips ; 53 pilotage manuel à distance ;
  54 vue 3D en direct ; 55 rejouer un incident en 3D ; 56 réglages modifiables avec garde-fous ; 57 statistiques ;
  59 installable comme une appli (PWA).
- **Notifications** : 60 alertes sur le téléphone ; 61 fin de fût, nettoyage à faire, calcul conseillé ;
  62 résumé du soir ; 63 escalade si une alarme urgente n'est pas vue.
- **Jumeau et optimisation** : 66 simulateur ; 67 solveur d'ordonnancement ; 68 essayer un réglage dans le simulateur ;
  69 montée en vitesse progressive (**pas et nombre de cycles réglables**, pas forcément 25) ; 70 calage sur les vrais temps.
- **IA** : 71 assistant en français (répond, ne commande jamais les moteurs) ; 73 écoute des bruits anormaux
  (micro à ajouter) ; 74 résumé de la semaine.
- **Culture** : 76 essais choisis, et plus largement **des plans d'expériences automatiques** pour diversifier
  au maximum les essais (voir plus bas).
- **Informatique** : 78 sauvegarde automatique ; 80 Tailscale à droits limités ; 81 mise à jour avec retour arrière ;
  82 journal des changements en français ; 83 heure juste (pile de l'horloge du Pi 5, à ajouter).
- **Aide** : 84 mode guidé pour un employé ; 85 manuel d'utilisation tenu à jour ; 86 carnet de bord.

## Déjà faites dans le logiciel de culture (ne pas refaire ici)

25 galerie par lot ; 26 photos pendant l'incubation ; 30 scanner un QR avec le téléphone ; 32 rapport en PDF.
La machine envoie seulement ses données au logiciel de culture, qui s'occupe de les montrer.

## Refusées

5 planning des fûts ; 9 vidange partielle ; 11 mode démo ; 20 mode cyclone ; 34 rappel de lot (un bocal = un seau
en général) ; 36 refus de produire sans nettoyage ; 37 rappels de produits ; 38 attente de la valeur d'ozone avant
d'ouvrir ; 64 compteur de consommables ; 65 prévision des besoins ; 72 détection de personne ; 77 étiquette imprimée.

## À préciser avec Karulium

- **6 et 76, plans d'expériences** : il veut diversifier un maximum les essais. Proposition : le PC de bureau
  prépare un plan d'essais (quels réglages sur quels seaux d'un lot : dose, température, temps...), dans des limites
  fixées par Karulium ; il l'accepte ; la machine l'applique seau par seau et note tout ; les résultats reviennent
  du logiciel de culture.
- **58, comptes** et **79, restauration** : expliqués à nouveau, en attente de sa réponse.
