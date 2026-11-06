# Essai du Nettoyage sur la vraie enceinte (store, verrous, ventilateur, générateur à blanc)

**Testé sur le vrai matériel : non.** Les tests automatiques et le simulateur n'utilisent que des faux (faux store,
faux capteurs, fausse enceinte). Durée : environ 2 h 30, plus une nuit pour l'étape 8 (facultative).

**La sécurité est câblée et cet essai ne la remplace pas.** Le Pi ne commande pas le moteur du store : c'est
toujours toi qui tiens le bouton « monter » ou « descendre ». Le Pi libère ou remet seulement les verrous.

**Règles de l'essai :**
- **personne dans l'enceinte** dès qu'on parle de générateur d'ozone ou de lampe UV ;
- étapes 1 à 7 : **générateur à blanc** (débranché de sa prise, ou relais seulement écouté) : pas d'ozone ;
- l'enceinte est **vide** (pas de seau, de bocal ni de fût dedans) ;
- garder la **clé de dépannage** des verrous à la main pendant tout l'essai.

## Avant de commencer

1. Vérifier dans `docs/entrees-sorties.yaml` que les broches des signaux du Nettoyage sont les vraies (elles sont
   d'EXEMPLE : carte `relais_2`, entrée `E7` de `entrees_24v_1`). Les corriger d'après le plan de l'armoire.
   **Si la carte `relais_2` n'existe pas encore : s'arrêter là.**
2. Arrêter le programme : `sudo systemctl stop vidange`.
3. Taper `vidange --verifier`. Attendu : « Réglages corrects ». Sinon, recopier le message dans la PR.

## Étape 1 : le contact du store (`store_ferme`)

1. Taper `vidange-es surveiller store_ferme`.
2. Store en bas : attendu `actionné`. Tenir « monter » une seconde : attendu `repos` dès que la barre quitte le
   seuil. Redescendre : `actionné`.
3. Il est normal de voir `repos` / `actionné` plusieurs fois à l'arrivée en bas (le reed rebondit) : le programme
   attend 2 s stables (`stabilite_s`).
4. Soulever un seul bout de la barre basse à la main (store presque en bas) : attendu `repos` (les 2 reeds sont en
   série : un seul suffit).
5. Ctrl+C pour finir.

## Étape 2 : les verrous (`verrous_store`)

1. Store en bas. Essayer de monter : le store **ne doit pas** bouger (verrous fermés sans courant).
2. `vidange-es commander verrous_store oui` : clic du relais, les verrous s'ouvrent. Monter le store : il bouge.
3. Redescendre, puis `vidange-es commander verrous_store non` : les verrous se ferment. Essayer de monter :
   il ne bouge pas.
4. Clé de dépannage : verrous fermés, ouvrir à la clé, monter : il bouge. Refermer, remettre la clé.

## Étape 3 : ventilateur, éclairage

1. `vidange-es commander ventilateur_enceinte oui` : le moteur EC est alimenté. **Il reste à l'arrêt** tant que la
   consigne 0-10 V n'est pas branchée (convertisseur pas encore choisi) : c'est normal. Le noter.
2. Si un convertisseur provisoire est en place : vérifier avec un voltmètre 0 V, 5 V (normal) et 10 V (plein), et
   le bruit du ventilateur à chaque niveau. Noter la surpression lue sur un manomètre, store fermé, à 5 V et 10 V.
3. `vidange-es commander ventilateur_enceinte non`.
4. `vidange-es commander eclairage_enceinte oui` : les 2 rubans LED s'allument ensemble. Puis `non`.

## Étape 4 : générateur et lampe UV, à blanc

Générateur d'ozone **débranché de sa prise** (on écoute le relais et on mesure la prise avec un testeur).

1. Store en bas, porte du spray fermée. `vidange-es commander generateur_ozone oui` : la prise a du courant.
2. Tenir « monter » (verrous ouverts à la main avec `vidange-es commander verrous_store oui`) : dès que la barre
   quitte le seuil, la prise **n'a plus de courant** (chaîne câblée), même si le relais est commandé.
3. Redescendre. Ouvrir la porte du spray : plus de courant. Refermer.
4. Même chose avec `lampe_uv` (ballast) : courant seulement store en bas et porte du spray fermée.
5. Tout remettre à `non`. **Si une seule de ces coupures ne marche pas : s'arrêter, la chaîne câblée est à
   reprendre avant toute nuit UV-ozone.**

## Étape 5 : compresseur et ventilateur de l'armoire

1. `vidange-es commander relais_compresseur oui` : le compresseur est alimenté. Puis `non`.
2. `vidange-es commander coupure_ventilateur_armoire oui` : le ventilateur de l'armoire **s'arrête**. Puis `non` :
   il repart. Programme arrêté (relais au repos) : il tourne.

## Étape 6 : le programme, store et purge

1. `sudo systemctl start vidange`. Sur l'écran, page du mode, bouton « ENCEINTE » (la page web montre aussi la
   carte « Enceinte »).
2. Store en bas au démarrage : attendu « Store fermé » puis « purge » (ventilateur au plein).
3. Sans capteurs de particules et de pression (pas encore choisis), la purge ne finit pas seule : à **20 min**,
   alerte « Purge pas finie ». Attendu aussi pendant ce temps : un dosage du mycélium serait refusé (« purge en
   cours »).
4. Appuyer « PASSER OUTRE » et confirmer (« Oui ») : ventilateur au normal, « passé outre » noté au journal
   (`journalctl -u vidange | grep -i purge`).
5. Bouton « OUVRIR » : attendu « Verrous libérés ». Tenir « monter » : « Store ouvert ».
6. Bouton « FERMER », puis tenir « descendre » jusqu'en bas : 2 s après, « Store fermé », verrous remis (vérifier en
   essayant de monter), et une nouvelle purge part.
7. Pendant cette purge, appuyer « OUVRIR » : refusé, « purge en cours ». Passer outre pour la suite.
8. « OUVRIR », monter le store, puis « FERMER » **sans** redescendre : au bout de 60 s, alerte « Store mal
   fermé ». Redescendre : « mal fermé » disparaît à la fermeture ; acquitter l'alerte.

## Étape 7 : mode maïs

1. Choisir le mode « Maïs » (page du mode). Ouvrir le store : il reste ouvert, ventilateur coupé, pas de purge.
2. Fermer le store : pas de purge. Revenir au mode « Production » avant la suite.

## Étape 8 (facultative, avec Karulium) : une vraie nuit UV-ozone

**Seulement si l'étape 4 est bonne, les 2 capteurs d'ozone essayés (`pi/systeme/essai-ozone.md`), personne dans
l'enceinte ni dans le conteneur fermé, et un détecteur d'ozone à part dehors.**

1. Générateur rebranché. Store fermé, purge finie ou passée outre, porte du spray fermée, panneau long du poste du
   fût **levé** (réglage `panneau_poste_fut`).
2. Mode « UV-ozone ». Page « ENCEINTE », bouton « NUIT 22:00 » puis « MAINTENANT », confirmer (« Oui »).
3. Attendu : ventilateur de l'enceinte, compresseur et ventilateur de l'armoire coupés ; générateur 2 min ; l'ozone
   dedans monte (« ≥ 10 ppm » au plafond), puis redescend.
4. Pendant la nuit, « OUVRIR » est refusé. Ozone dehors au-dessus de 0,1 ppm : alerte « FUITE D'OZONE »,
   générateur coupé — **sortir, aérer, chercher la fuite**.
5. Fin : ozone dedans sous 0,1 ppm stable 15 min, « Nuit UV-ozone finie ». Le store reste verrouillé jusqu'à
   « OUVRIR ». Vérifier avec le détecteur à part avant d'entrer.
6. Couper le courant du Pi en pleine nuit (une fois) : au redémarrage, le générateur reste coupé et le Pi attend
   le retour sous 0,1 ppm. Il ne relance jamais la génération seul.

## Noter dans la PR

- Le résultat de chaque étape (bon / pas bon, et ce qui a été vu).
- Les temps réels : montée et descente du store, rebond du reed, surpression à 5 V et 10 V, temps de retour de
  l'ozone sous 0,1 ppm (étape 8). Ils servent à régler `machine.yaml → nettoyage` (valeurs d'EXEMPLE) et
  `simulateur.yaml → nettoyage`, puis à passer `exemple` à `false`.

- [ ] Store et reeds   - [ ] Verrous et clé   - [ ] Ventilateur et LED   - [ ] Chaîne câblée UV-ozone
- [ ] Compresseur et armoire   - [ ] Purge et passer outre   - [ ] Mode maïs   - [ ] Nuit UV-ozone (facultatif)
