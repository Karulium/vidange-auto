# Programme du Raspberry Pi 5 (le chef)

Paquet Python `vidange` (Python 3.11, comme Raspberry Pi OS Bookworm).
Pour l'instant : démarrage, réglages et liste des entrées/sorties vérifiés, journal, secrets, liaison avec les cartes FluidNC (et faux FluidNC), entrées/sorties du Pi par leur nom (et faux capteurs), chef d'orchestre (moteur d'étapes) avec un module d'exemple, registre (base SQLite) avec copie de secours quotidienne, fiabilité (chien de garde, check-list de démarrage,
reprise après coupure et retour en lieu sûr, arrêt propre sur onduleur, bilan de chaque alarme, santé du Pi),
API et page web locale (état, alarmes, Go, Pause, historique, photos), simulateur de cycle (jumeau, version 0),
vidéos des caméras (en direct et clips des alarmes) et pilotage manuel à distance avec ses garde-fous,
mises à jour des cartes ESP32 (par USB) et du programme du Pi (depuis `main`), lancées depuis la page web.
Pas encore de vrai module de la machine.

## Ce qu'il y a ici

| Chemin | Rôle |
|---|---|
| `vidange/demarrage.py` | Démarrage : réglages, journal, registre, matériel, cartes, chef, surveillance ; arrêt propre |
| `vidange/reglages.py` | Lecture et vérification des fichiers de `reglages/` |
| `vidange/entrees_sorties.py` | Lecture et vérification de `docs/entrees-sorties.yaml` (cartes, broches, tensions) |
| `vidange/journal.py` | Journal (logs) commun : `donner_journal("nom")` |
| `vidange/fichier_secrets.py` | Lecture du fichier de secrets (hors Git) |
| `vidange/fluidnc/liaison.py` | Liaison série avec une carte FluidNC : G-code avec contrôle de flux, état, alarmes, reconnexion |
| `vidange/fluidnc/ports.py` | Trouve le port USB d'une carte par son numéro de série |
| `vidange/fluidnc/protocole.py` | Lecture des messages de FluidNC (états, alarmes, erreurs en clair) |
| `vidange/fluidnc/faux.py` | Faux FluidNC pour les tests et le simulateur |
| `vidange/fluidnc/outil.py` | Commande `vidange-fluidnc` (lister les ports, console) pour les essais |
| `vidange/materiel/materiel.py` | Entrées/sorties du Pi par leur nom : lire, commander, mesurer |
| `vidange/materiel/puces.py` | GPIO du Pi, bus I2C, PCF8574, MCP23017, ADS1115, SHT31, carte de pesée HX711 |
| `vidange/materiel/modbus.py` | Modbus RTU sur RS485 (transmetteurs d'ozone, cartes de pesée) |
| `vidange/materiel/carte_pesee.py` | Table des registres d'une carte de pesée RP2040 + HX711 du bus RS485 |
| `vidange/pesees/` | Cartes de pesée du bus RS485 lues à tour de rôle ; commande `vidange-pesees` (essais) |
| `vidange/materiel/faux.py` | Faux capteurs et fausses cartes pour les tests et le simulateur |
| `vidange/materiel/outil.py` | Commande `vidange-es` (lister, surveiller, commander) pour les essais |
| `vidange/chef/chef.py` | Chef d'orchestre : fait avancer les modules, pause, reprise, alarmes, Go, carnet |
| `vidange/chef/etapes.py` | Ce qui décrit un module : étapes, conditions, actions |
| `vidange/chef/zones.py` | Zones réservées entre modules |
| `vidange/chef/carnet.py` | Carnet de l'état du cycle (pour la reprise après coupure) |
| `vidange/chef/axes.py` | Envoie les axes à des positions nommées de `machine.yaml` |
| `vidange/chef/exemple.py` | Module d'**exemple** (montre comment écrire un module) |
| `vidange/registre/base.py` | Registre : base SQLite (fûts, seaux, bocaux, Pétri, cycles, étapes, mesures, photos, alarmes, réglages) |
| `vidange/registre/montees.py` | Tables de la base et leurs montées de version |
| `vidange/registre/sauvegarde.py` | Copie de secours quotidienne de la base |
| `vidange/registre/outil.py` | Commande `vidange-registre` (état de la base, copie à la main) |
| `vidange/simulateur/` | Simulateur de cycle : le vrai chef sur une machine imaginaire, planning et temps total ; commande `vidange-simulateur` |
| `vidange/envois/` | File d'envoi : cycles vers le logiciel de culture, copies vers la maison ; commande `vidange-envois` |
| `vidange/quoi_faire.py` | **Catalogue des « quoi faire »** de chaque alarme (cartes FluidNC, câble, capteur muet...) |
| `vidange/fiabilite/chien_de_garde.py` | Chien de garde : surveille les cartes et le chef, dit « je vis » à systemd, battement |
| `vidange/fiabilite/checklist.py` | Check-list de démarrage : tout ce qui empêche de lancer la production |
| `vidange/fiabilite/marche.py` | Reconnaît comment s'est fini le passage précédent (propre, plantage, coupure) |
| `vidange/fiabilite/lieu_sur.py` | Module « lieu_sur » : prises d'origine et positions sûres (liste de `machine.yaml`) |
| `vidange/fiabilite/onduleur.py` | Arrêt propre sur onduleur |
| `vidange/fiabilite/bilans.py` | Bilan de chaque alarme (fichier JSON) et alarme dans le registre ; acquittement |
| `vidange/fiabilite/sante.py` | Santé du Pi : température, alimentation, disque, mémoire, heure, copie de secours |
| `vidange/api/app.py` | API du Pi (FastAPI) : état, check-list, alarmes, Go, Pause, historique, photos ; clé, réseaux autorisés |
| `vidange/api/serveur.py` | Serveur web de l'API (uvicorn) dans un fil à part |
| `vidange/api/page/index.html` | La page web en français, lisible sur téléphone (une seule page, rien à télécharger d'Internet) |
| `vidange/ecran/` | Écran Nextion de l'armoire : protocole série, liaison, pages et boutons, faux écran pour les tests |
| `vidange/cameras/` | Caméras : vidéo lue depuis une commande (MJPEG), mémoire tournante, clips des alarmes, fausse caméra |
| `vidange/distance/` | Pilotage manuel à distance : homme mort, vitesse plafond, voyant-buzzer, priorité à l'armoire, journal |
| `vidange/mises_a_jour/` | Mises à jour : cartes ESP32 (esptool, console FluidNC, copies de la mémoire), programme du Pi (git), fausse carte ; commande `vidange-maj` |
| `vidange/accelerometre/` | Accéléromètre du chariot Z : copie de `accelerometre.yaml` dans le programme du RP2040 (`accelerometre/`) ; liaison par le fil série unique (chocs notés au registre, réglages envoyés), mise à jour de son programme par ce fil (chargeur, `fichier_programme.py`), faux RP2040 ; commande `vidange-accelerometre` |
| `vidange/mode.py` | Mode de la machine (production, lavage, UV-ozone), gardé dans un fichier, changé machine au repos |
| `vidange/griffe/` | Griffe sur mât : règles de position (`regles.py`), doses apprises (`doses.py`), bras sur la carte du portique et sa pesée (`bras.py`), gestes (`griffe.py`), module « griffe » (`module.py`), griffe du simulateur (`simulation.py`) |
| `vidange/porte_bocal/` | Porte-bocal (carte n° 3) : mors (serrage par palpage, ouverture), demi-tour du bocal (pont en H, verrou, inclinaison, photo de contrôle), signaux de la carte par leur nom (`signaux.py`), faux plateau et faux bocal (`faux.py`) ; commande `vidange-porte-bocal` |
| `vidange/prehension/` | Préhension (cartes n° 1 et n° 4) : règles de mouvement (`regles.py`), tête sur ses deux cartes avec le vide et la force (`tete.py`), gestes : prendre, poser, porte-bocal, visser (`prehension.py`), scénario du simulateur (`module.py`, `simulation.py`) ; commande `vidange-prehension` |
| `vidange/lavage/` | Lavage des seaux (cartes n° 1, 3 et 4) : eau du fût de lavage, chauffage, jet d'air (`eau.py`), signaux répartis sur les cartes (`signaux.py`), verrou du noyau et gestes du lavage d'un seau (`lavage.py`), scénario du simulateur (`module.py`, `simulation.py`) ; commande `vidange-lavage` |
| `vidange/poste_fut/` | Poste du fût : état (absent, en place, prêt), bouton « Prêt » et voyant, pesée (HX711), mode permis par le panneau, verrous pour les autres modules, module « poste_fut » ; commande `vidange-pesee` (étalonnage) |
| `reglages/machine.yaml` | Axes (et leur carte FluidNC), positions, zones, délais (pour l'instant : un **exemple** inventé) ; poste du fût (chiffres **vrais**, pesée à étalonner) |
| `reglages/programme.yaml` | Réglages du programme lui-même (journal, chef d'orchestre, registre, fiabilité, API, écran, caméras, pilotage à distance, mises à jour) |
| `reglages/fluidnc.yaml` | Cartes FluidNC (numéro de série USB) et réglages de leur liaison |
| `reglages/simulateur.yaml` | Machine imaginaire du simulateur : vitesses des axes, délai du Go, capteurs qui changent (**exemple**) |
| `reglages/accelerometre.yaml` | Accéléromètre (RP2040 + LIS3DH) : carte, broches, seuil de choc, pannes, fil série vers le Pi, chargeur (**exemple**) |
| `secrets.exemple.yaml` | Modèle **vide** du fichier de secrets |
| `systeme/vidange.service` | Service qui démarre avec le Pi et se relance s'il plante |
| `systeme/installation.md` | Installation sur le Pi, pas à pas |
| `systeme/essai-entrees-sorties.md` | Essai des entrées/sorties sur le vrai matériel, pas à pas |
| `systeme/essai-fiabilite.md` | Essai de la fiabilité sur le vrai matériel (coupures, chien de garde...), pas à pas |
| `systeme/essai-page-web.md` | Essai de la page web sur le vrai Pi (téléphone, Tailscale), pas à pas |
| `systeme/essai-distance.md` | Essai des caméras et du pilotage à distance sur le vrai Pi, pas à pas |
| `systeme/essai-ecran.md` | Essai de l'écran Nextion sur le vrai Pi (câblage, UART, chaque page), pas à pas |
| `systeme/essai-prehension.md` | Essai de la préhension sur le vrai matériel (carte n° 4, vide, force, prises, porte-bocal, vissage), pas à pas |
| `systeme/essai-lavage.md` | Essai du lavage des seaux sur le vrai matériel (eau, flotteur, chauffage, brosses, verrou, un seau lavé), pas à pas |
| `systeme/essai-poste-fut.md` | Essai du poste du fût sur le vrai matériel (chariot, panneau, bouton, pesée et étalonnage), pas à pas |
| `tests/` | Tests (pytest) |

## Essayer sur un PC

```
cd pi
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/vidange --verifier     # vérifie les réglages et s'arrête
.venv/bin/pytest                 # tests
.venv/bin/ruff check . && .venv/bin/ruff format --check .   # style
```

`vidange` sans `--verifier` démarre et attend (Ctrl+C pour arrêter). Le journal va dans `pi/donnees/journal/`.

Pour jouer avec un faux FluidNC : `.venv/bin/vidange-fluidnc console portique --faux`
(taper `G1 X10 F600`, `fin`, `etat`...). Sur la vraie carte : voir `fluidnc/essai-liaison.md`.

## Liaison FluidNC, pour le chef d'orchestre

```python
from vidange.fluidnc import Liaison

with Liaison("portique", reglages.fluidnc) as portique:  # se connecte et se reconnecte seule
    portique.attendre_connexion(10)
    portique.envoyer("G1 X100 F3000")  # rend une Commande ; .attendre(s) lève une erreur si refusée
    etat = portique.attendre_fin_mouvements(60)  # état après la fin : etat.positions["X"]...
```

- « ok » d'une ligne = la carte l'a prise, pas « mouvement fini » (pour ça : `attendre_fin_mouvements`).
- Après une coupure du câble, un redémarrage de la carte ou une réinitialisation, **rien n'est renvoyé tout
  seul** : les lignes en cours finissent en échec (« perdue », « annulée ») ; c'est au chef d'orchestre de décider.
- Une alarme fait échouer toutes les lignes en cours et annule celles pas encore parties.
- Positions en mm, par lettre d'axe de la carte (X, Y, Z, A, B, C), dans le repère machine de FluidNC.

## Ajouter un fichier de réglages

1. Écrire son modèle dans `vidange/reglages.py` (classe qui hérite de `Modele`).
2. L'ajouter à `FICHIERS` et à `Reglages`.
3. Mettre le fichier dans `reglages/` et des tests dans `tests/test_reglages.py`.

## Codes de sortie

- `0` : arrêt normal.
- `1` : plantage imprévu (systemd relance le programme 5 s après).
- `2` : réglages faux (systemd ne relance pas : corriger les réglages, puis relancer le service).
- `3` : base du registre abîmée (systemd ne relance pas : voir « Registre » plus bas).
- Programme figé : il ne dit plus « je vis » ; systemd l'arrête et le relance au bout de `WatchdogSec`.

## Entrées/sorties du Pi, pour le chef d'orchestre

```python
from vidange.materiel import Materiel

with Materiel(liste) as materiel:  # liste = charger_entrees_sorties(...)
    materiel.lire("reed_panneau_poste_fut")  # True = capteur actionné
    materiel.ecrire("voyant_buzzer", True)  # True = relais commandé
    materiel.mesurer("vide_venturi")  # dans l'unité de la liste (kPa...)
    materiel.ambiance("sht31_armoire")  # .temperature_c, .humidite_pct
    materiel.mesurer("ozone_1")  # ppm, par RS485
```

- Le code ne pense jamais en niveaux électriques : « actionné » et « commandé » tiennent compte du sens
  du contact (`repos`) et de la carte (`niveau_actif`), écrits dans `docs/entrees-sorties.yaml`.
- Relais et entrées 24 V peuvent être reliés au Pi par GPIO direct ou par une puce I2C (PCF8574, MCP23017) :
  seule la liste change, pas le code.
- Au départ et à la fermeture, toutes les sorties sont **au repos**.
- Une puce qui ne répond pas lève `ErreurMateriel` (avec le nom du signal) ; le reste continue.
- Faux matériel : `Materiel(liste, FausseFabrique(liste))`, puis `faux.actionner(...)`, `faux.regler(...)`,
  `faux.commande(...)`, `faux.debrancher(...)`. Essai rapide : `.venv/bin/vidange-es --faux lister`.

## Chef d'orchestre, pour écrire un module

Un module = une liste d'étapes. Chaque étape : (1) attend le Go de Karulium si elle le demande,
(2) attend ses conditions d'entrée et réserve ses zones, (3) lance son action une fois, sans attendre,
(4) attend sa condition de fin au plus son délai maximal, (5) libère ses zones. Modèle : `vidange/chef/exemple.py`.

```python
from vidange.chef import Axes, Carnet, Chef, Condition, Etape, Module

axes = Axes(reglages.machine, {"portique": liaison_portique})
module = Module(
    nom="griffe",
    etapes=(
        Etape(
            "descendre",
            "Regarder si la griffe touche quelque chose, puis acquitter et donner le Go.",
            action=lambda: axes.aller("griffe_basse"),  # nom de position de machine.yaml
            fin=axes.arrives,
            delai_max="griffe_descente_max",  # nom dans machine.yaml → durees
            entree=(Condition("seau en place", lambda: materiel.lire("seau_present")),),
            reserver=("zone_seau",),  # nom dans machine.yaml → zones
            demande_go=True,
        ),
    ),
    surveillances=(axes.surveillance,),  # vérifiées pendant les gestes
    pauser=axes.pauser,
    reprendre=axes.reprendre,
    arreter=axes.pauser,
)
chef = Chef(reglages.machine, reglages.programme.chef, Carnet(donnees / "etat-cycle.json"))
chef.lancer(module)  # refuse un délai ou une zone inconnus de machine.yaml
chef.demarrer()  # puis : chef.donner_go("griffe"), chef.pause(), chef.reprendre(),
# chef.acquitter("griffe"), chef.abandonner("griffe"), chef.etat()
```

- **Une action doit être rejouable** (aller à une position absolue, pas « avancer de 10 cm ») : après une alarme
  ou une coupure, l'étape est refaite depuis le début.
- Conditions et actions doivent être **rapides** (lire un capteur, envoyer une ligne) : jamais d'attente dedans.
- Une erreur dans une condition ou une action (capteur muet, ligne refusée, `ErreurEtape`) met le module en
  **alarme** avec le « quoi faire » de l'étape. Une alarme arrête le module (`arreter`) et, si
  `alarme_pause_tout: true` (programme.yaml), met toute la machine en pause.
- Après une alarme : `acquitter`, puis **Go** obligatoire, puis l'étape est refaite.
- Le temps d'une pause ne compte pas dans les délais.
- Plusieurs modules tournent ensemble ; un module qui veut une zone tenue par un autre attend
  (« zone « x » libre (tenue par « y ») »). Une zone reste tenue jusqu'à `liberer` ou la fin du module.
- L'état est noté dans `donnees/etat-cycle.json` à chaque changement (fichier jamais à moitié écrit).
  Après une coupure : `chef.reprendre_cycle([modules])` remet chaque module à son étape, en attente du Go.
- Le zéro des axes de `machine.yaml` est le zéro machine de leur carte FluidNC (mètres × 1000 = mm).
- **Reprise au bon seau** : `chef.memoriser("griffe", seau="S1293", cycle=12)` garde ces valeurs dans le carnet ;
  après une coupure, `chef.memoire("griffe")` les rend. Par convention, `cycle` = numéro du cycle du registre
  (le bilan d'une alarme le note avec elle).
- `ErreurEtape("message", quoi_faire)` : quand on connaît la cause exacte, son « quoi faire » remplace celui de
  l'étape. Les « quoi faire » communs sont dans `vidange/quoi_faire.py`.
- Un module `exclusif=True` (comme « lieu_sur ») passe avant tous les autres : tant qu'il tourne, les autres
  attendent (« fin de « lieu_sur » ») et un Go qui leur est donné est refusé.

## Simulateur de cycle (tâche 11)

Le **vrai** chef d'orchestre rejoue un module sur une machine imaginaire, en temps simulé (une heure de cycle
en une fraction de seconde), et sort le planning : chaque étape, quand elle commence, combien elle attend
(Go, conditions, zones), quand son geste part et finit, ce qui bouge ; puis le temps total.

```
.venv/bin/vidange-simulateur exemple                 # planning du module d'exemple
.venv/bin/vidange-simulateur exemple --delai-go 0    # si Karulium donnait le Go tout de suite
.venv/bin/vidange-simulateur exemple --json p.json   # planning aussi en JSON
.venv/bin/vidange-simulateur poste_fut               # échange d'un fût (scénario « echange_fut »)
.venv/bin/vidange-simulateur griffe                  # vidange d'un fût par la griffe (« vidange_fut »)
.venv/bin/vidange-simulateur mycelium                # dosage du mycélium (« dosage_mycelium »)
.venv/bin/vidange-simulateur prehension              # gestes de la préhension (« prehension »)
.venv/bin/vidange-simulateur lavage                  # 3 seaux lavés, eau comprise (« lavage »)
```

- **Durées réglables** dans `reglages/simulateur.yaml` : vitesse et accélération de chaque axe (un déplacement
  dure autant que l'axe le plus long à arriver), temps avant le Go de Karulium, capteurs actionnés au départ et
  capteurs qui changent « N s après le début de telle étape » (« Karulium ferme le panneau »...).
- Une alarme (délai dépassé, position inconnue...) ou un blocage (rien ne bouge jusqu'à `duree_max_s`) arrête
  la simulation ; le planning dit pourquoi (code de sortie 1).
- Plusieurs modules peuvent être rejoués ensemble : ils se partagent zones et cartes comme sur la machine.
- **Scénarios** nommés (`scenarios:` dans `simulateur.yaml`) : leurs capteurs et événements remplacent ceux
  du haut du fichier (`--scenario nom`). Un événement peut aussi régler la fausse pesée (`pesee: pesee_fut`,
  `kg: 165` ou `debranchee: true`). Le module `poste_fut` joue le scénario `echange_fut` par défaut.
- Un module reçoit des axes imaginaires (`simulateur.axes()`) à la place des vrais `Axes`, avec les mêmes noms ;
  son code ne change pas. Pour qu'un nouveau module soit simulable, l'ajouter à `MODULES` dans
  `vidange/simulateur/outil.py`.
- **Place pour le solveur OR-Tools** (tâche 23) : `vidange/simulateur/solveur.py` tire du planning les tâches
  (durée du geste, zones tenues, étape d'avant, Go demandé) ; `ordonner()` est à écrire.

## Fiabilité (tâche 7)

- **Au démarrage**, le programme dit comment s'est fini le passage précédent (`donnees/etat-programme.json`) :
  arrêt propre, plantage (le programme a été relancé) ou coupure (le Pi a redémarré). Plantage et coupure
  sont notés comme une alarme dans le registre, à acquitter.
- **Reprise** : les modules du carnet reprennent à leur étape, avec leur mémoire. Le module « lieu_sur »
  (prises d'origine et positions sûres, liste `lieu_sur` de `machine.yaml`) est proposé à chaque démarrage :
  il attend le Go, et passe avant les modules repris. Ensuite seulement, chaque module attend son Go.
- **Check-list de démarrage** : écrite au journal à chaque démarrage. Bloquant : réglages d'exemple,
  entrée/sortie illisible ou pas dans son état `au_demarrage`, carte FluidNC absente ou en alarme, module en
  alarme, disque presque plein, courant coupé. La page web et l'écran la referont avant chaque lancement.
- **Chien de garde** : toutes les 2 s, si le chef d'orchestre tourne, « je vis » à systemd (et battement de
  `battement_pi` s'il existe). Les cartes FluidNC sont surveillées par leur liaison (muette, débranchée,
  redémarrée toute seule).
- **Onduleur** : `onduleur_sur_batterie` actionné → pause tout de suite ; après `delai_avant_arret_s`, arrêt
  propre puis extinction du Pi (`commande_arret`). Courant revenu avant : la machine reste en pause.
- **Bilan de chaque alarme** : `donnees/bilans/AAAA-MM-JJ/HHMMSS-module.json` (alarme, quoi faire, modules,
  cartes et positions, entrées, sorties, mesures, santé, fin du journal) ; le registre garde son chemin.
  Le clip vidéo viendra avec la tâche 12 (`bilans.collecteurs`). Acquitter : `bilans.acquitter(numero, qui)`.
- **Santé du Pi** : toutes les 5 min, notée dans le registre (mesures `temperature_pi`, `disque_libre`,
  `memoire_libre`) ; un changement de niveau est écrit au journal. Seuils dans `programme.yaml` → `fiabilite`.

## Registre (base SQLite)

Dans le dossier des données (`/var/lib/vidange` sur le Pi, `pi/donnees` sur un PC) :

- `registre.sqlite` : la base. Tables : `futs`, `seaux`, `bocaux`, `petris` (reconnus par le code de leur QR),
  `cycles`, `seaux_du_cycle` (seaux remplis), `doses_mycelium` (doses de chaque bocal versées dans un seau), `etapes_faites` (avec durées),
  `mesures`, `photos`, `alarmes`, `reglages_appliques` (ancien / nouveau / qui / quand).
- `photos/` : les fichiers des photos. **La base ne garde que leur chemin** (relatif à ce dossier).
- `sauvegardes/registre-AAAA-MM-JJ.sqlite` : une copie complète et vérifiée par jour, à partir de
  l'heure réglée dans `programme.yaml` (→ `registre`) ; on garde les dernières (nombre réglé).

```python
from vidange.registre import ouvrir_registre

registre = ouvrir_registre(donnees)  # crée la base, ou la monte à la dernière version
cycle = registre.commencer_cycle("vidange", fut="F3")
registre.ajouter_seau(cycle, "S1293", bocal="B327")  # un code jamais vu est ajouté tout seul
registre.noter_etape(cycle, "verser", debut, duree_s=32.5)
registre.noter_mesure("poids_seau", 6.2, "kg", capteur="balance", cycle=cycle, seau="S1293")
registre.noter_photo(donnees / "photos" / "2026-10-26" / "dose.jpg", camera="dosage", seau="S1293")
registre.noter_alarme("griffe", "Délai dépassé", quoi_faire="...", cycle=cycle)
registre.noter_reglage("karulium", "machine.yaml", "durees.vidange_max", 30, 35)
registre.finir_cycle(cycle)
registre.lire("SELECT * FROM cycles WHERE fin IS NULL")  # pour les écrans et l'API
```

- **Montées de version** : la base porte son numéro de version. Pour la changer, ajouter une montée à la fin
  de `montees.py` (jamais modifier une montée déjà livrée). Avant une montée, une copie de l'ancienne base est
  faite à côté (`registre-avant-version-N.sqlite`). Une montée ratée laisse la base comme avant.
- **Base abîmée** : le programme ne démarre pas (code 3, systemd ne le relance pas) et le journal dit quoi faire :
  arrêter le service, mettre `registre.sqlite` de côté, copier la dernière copie de `sauvegardes/` à sa place
  sous le nom `registre.sqlite`, relancer.
- `vidange-registre etat` : version et nombre de lignes de chaque table ; `vidange-registre sauvegarder` :
  copie tout de suite (par exemple avant une mise à jour). Peut tourner pendant que le programme tourne.

## File d'envoi vers l'extérieur (tâche 10)

Tout ce qui doit partir du Pi attend dans la table `envois` du registre (elle survit aux coupures), et un fil
(le « facteur », `vidange/envois/facteur.py`) l'envoie dès que le destinataire répond. La machine n'attend jamais.

- **Logiciel de culture** : chaque cycle fini (`registre.finir_cycle`) entre dans la file, dans la même écriture.
  Il part en JSON (`POST`, jeton `jeton_culture` du fichier de secrets) vers `envois.culture.adresse`. Format
  exact et réponses attendues : `docs/django.md`. Adresse vide (l'app « machine » n'existe pas encore) : les
  cycles attendent.
- **Copie de secours de la maison** : chaque copie quotidienne de la base (et le dossier des photos) entre dans
  la file, et part par la commande `envois.secours.commande` (rsync par Tailscale, voir
  `systeme/installation.md`). Une copie plus récente remplace celle qui attendait encore.
- Un envoi raté (réseau, serveur éteint) : nouvel essai après 1 min, puis 2, 4... sans dépasser 1 h. Un envoi
  refusé (données fausses, réponse 400) est mis de côté ; les suivants partent. La check-list le signale.
- Chaque envoi a une **clé** (UUID) qui ne change pas d'un essai à l'autre : un envoi fait deux fois (coupure
  pendant l'envoi) est reconnu par le destinataire.
- `vidange-envois etat` (ce qui attend, les erreurs), `vidange-envois montrer <n° de cycle>` (le JSON envoyé),
  `vidange-envois renvoyer <n° d'envoi>`, `vidange-envois essayer` (une tournée tout de suite).

## API et page web (tâche 8)

La page web s'ouvre sur `http://<adresse du Pi>:8080` (port dans `programme.yaml` → `api`), sur place ou par
Tailscale (voir `systeme/installation.md`). Sur un PC : mettre une clé dans `pi/secrets.yaml`, lancer
`.venv/bin/vidange`, puis ouvrir `http://127.0.0.1:8080`.

- **Clé** : `cle_api` du fichier de secrets (au moins 16 caractères). Sans clé, l'API ne démarre pas (la machine,
  elle, tourne : la check-list le signale). Chaque appel `/api/...` envoie `Authorization: Bearer <clé>`.
- **Réseaux autorisés** : `reseaux_autorises` (réseau local, Tailscale) ; toute autre adresse est refusée (403),
  même avec la clé, même pour la page.
- Les ordres passent par le chef d'orchestre, comme ceux de l'écran ; un ordre impossible est refusé (409) avec
  la raison en clair. Chaque ordre est noté au journal avec l'adresse d'où il vient.
- Pas de pages de documentation automatiques (`/docs`) : elles montreraient l'API sans clé.

| Adresse | Rôle |
|---|---|
| `GET /` | La page web (sans clé : elle demande la clé, puis la garde dans le téléphone) |
| `GET /api/etat` | Pause ou pas, chaque module (étape, ce qu'il attend, zones, alarme), Go attendus, alarmes ouvertes |
| `GET /api/checklist` | La check-list refaite maintenant : `prete`, constats et « quoi faire » |
| `POST /api/pause`, `POST /api/reprendre` | Pause et reprise de toute la machine |
| `POST /api/go/{module}` | Le Go de Karulium à un module qui l'attend |
| `GET /api/alarmes` | Alarmes ouvertes ; `?toutes=true` : les dernières, même acquittées (`limite`, `avant`) |
| `POST /api/alarmes/{n}/acquitter` | Acquitte l'alarme n (et le module, s'il est en alarme : il attend alors le Go) |
| `GET /api/historique` | Derniers cycles (`limite`, `avant` pour la page suivante) |
| `GET /api/historique/{cycle}` | Tout d'un cycle : seaux et doses de mycélium, étapes, mesures, photos, alarmes |
| `GET /api/photos` | Dernières photos (`cycle`, `seau`, `limite`, `avant`) |
| `GET /api/photos/{n}` | Le fichier de la photo n |

Au plus `lignes_max` lignes par réponse ; `avant=<numéro>` donne la page suivante.

## Poste du fût (tâche 17)

Rien ne bouge seul au poste : `PosteFut` (`vidange/poste_fut/poste.py`) relit en fond le détecteur du chariot,
le contact du panneau et le bouton « Prêt », pèse le chariot (carte HX711 lue par 2 broches du Pi), et règle
le voyant du bouton (clignote tant que ce n'est pas prêt).

```python
poste = PosteFut(reglages.machine.poste_fut, materiel, registre)
poste.etat()  # absent / en_place / pret, ce qui manque, poids, messages
poste.appuyer_pret("page web")  # comme le bouton du poste (ErreurPoste : ce qui manque)
poste.refus_lancement("production")  # panneau levé ? (None : permis)
poste.surveillance  # Condition « chariot du fût en place » pour la griffe
poste.noter_dose(kg)
poste.finir_vidange(nombre_seaux)  # appelés par la griffe (tâche 18)
poste.refus_pont(x)
poste.refus_remplissage(y_bout)
poste.refus_griffe(x, y, z, mode)
```

- **Prêt** = chariot au fond + chariot immobile depuis `stabilite_s` + pesée qui répond avec un poids
  plausible + appui sur « Prêt ». Au « Prêt », le cycle `vidange` commence dans le registre avec le poids du
  fût plein ; chariot retiré avant `finir_vidange` : cycle abandonné.
- **Pesée** : médiane de plusieurs lectures, lectures aberrantes jetées, lecture interrompue par Linux refaite ;
  pas de réponse = « pesée débranchée », jamais une erreur qui arrête le Pi. Étalonnage :
  `vidange-pesee zero | etalonner 20 | tare` (voir `systeme/essai-poste-fut.md`).
- **Verrous** (`vidange/poste_fut/regles.py`) : pour le pont, le chariot de remplissage, la griffe et la
  préhension en lavage ; ils rendent la raison du refus. Ils ne protègent que la machine.
- Page web (`/api/poste-fut`, bouton PRÊT) et écran (page `poste_fut`, qui vient seule à l'arrivée du chariot).

## Griffe (tâche 18)

La griffe vide le fût dans les seaux, couche par couche, comme dans la fiche « Griffe sur mât » (module gelé
le 25/10/2026). Tous les chiffres sont dans `reglages/machine.yaml` (partie `griffe` et axes `pont_x`,
`chariot_y`, `griffe_z`, `griffe_a`, `griffe_b`) ; ceux marqués EXEMPLE sont à mesurer
(`systeme/essai-griffe.md`).

```python
bras = BrasFluidnc(reglages.machine, liaison_portique, pesees.capteur("pesee_griffe"))
bras.demarrer(arret)  # lit la pesée 80 fois par seconde
griffe = Griffe(reglages.machine, bras, poste, registre)
chef.lancer(module_griffe(griffe, seau_pret=..., pont_libre=...))
```

- **Un geste = une suite de pas** (déplacements manuels `$J=` vers des positions absolues : rejouables,
  arrêtables tout de suite sans perdre la position). Chaque pas est **vérifié point par point** avant de
  partir (`ReglesGriffe` : rotation selon la hauteur, godet jamais au-delà de « fermé », garage et glissière,
  dosage, caméra du bocal, poste du fût, porte du spray, trajet jamais en diagonale) ; un pas refusé met le
  module en alarme sans bouger.
- **Contact** : le fil de la pesée arrête la descente dès que la charge baisse ; **choc** pendant un trajet :
  arrêt, alarme, remontée lente au Go suivant ; pesée muette : arrêt.
- **Doses** : densité apprise sur les dernières prises du fût, corrections à part près de la paroi et au fond ;
  chaque prise est notée dans le registre (table `prises_griffe`).
- **Passe de fond** quand la pesée du fût annonce les derniers kilos : raclage, spirale au fond, paroi,
  chasse-neige, centre ; puis `finir_vidange` au poste du fût.
- Le chef sait maintenant **choisir l'étape suivante** (`Etape(ensuite=...)`) : prise, seau, prise...
- Cases vides des modules pas écrits : `seau_pret`, `pont_libre`, `tourner_seau`, `couche_finie`,
  `seau_fini`, `prochain_format`, `machouiller` (faux pour le maïs), `dosage_en_cours`, `porte_spray_ouverte`.


## Mycélium (tâche 19)

L'agitateur porte le bocal de semence sur sa glissière ; tête en bas au-dessus du seau, la manivelle le
secoue et la balance du chariot de remplissage pèse ce qui tombe (module validé le 24/10/2026). Tous les
chiffres sont dans `reglages/machine.yaml` (partie `mycelium`, axes `agitateur_x` et `manivelle`, et
`hauteur`, `mycelium_kg`, `seaux_par_bocal` des formats) ; ceux marqués EXEMPLE sont à mesurer
(`systeme/essai-mycelium.md`).

```python
carte = reglages.fluidnc.cartes["mycelium_lavage"]
agitateur = AgitateurFluidnc(
    reglages.machine, liaison_mycelium_lavage, pesees.capteur("pesee_plateau_remplissage"), carte
)
agitateur.demarrer(arret)  # lit la balance 80 fois par seconde (et le capteur de la manivelle)
porte_bocal = PorteBocalFluidnc(
    reglages.machine,
    liaison_mycelium_lavage,
    signaux_porte_bocal(liaison_mycelium_lavage, carte),
    photo=photo,
    controle=controle_du_bocal,  # tâche 22
)
mycelium = Mycelium(reglages.machine, agitateur, porte_bocal, chariot, nouveau_bocal, registre)
porte_bocal.verrou = mycelium.refus_demi_tour
chef.lancer(module_mycelium(mycelium))
mycelium.demander(Demande("S1293", "seau_a", couche=1, variete="pleurote_grise", cycle=cycle))
```

- **Origine de la manivelle** (tâche 20) : le capteur voit du métal quand la manivelle n'est **pas** en haut ;
  le Pi fait un tour lent et prend le milieu de la zone sans métal (+ décalage), contrôle sa largeur (± 10°)
  et le nombre de bords, sinon alarme « capteur manivelle ». Faite au début, et refaite si la carte redémarre.
- **Une couche** : chariot écarté, au demi-tour manivelle en bas, bocal tête en bas, manivelle en haut,
  dosage, manivelle en bas, seau sous le bocal (plateau à la hauteur du dosage), casse du bloc (1re agitation
  d'un bocal), agitation jusqu'à la dose, arrêt **pile en bas**, chariot qui repart, manivelle en haut,
  demi-tour (manivelle en bas, bocal debout, photo de contrôle, manivelle en haut), garage.
- **Changement de bocal** : mors ouverts, bocal neuf posé (Préhension, case vide), serré (palpage : diamètre
  hors plage = bocal absent, cassé ou mal posé → alarme avec photo).
- **Verrous** (`ReglesMycelium`) : l'agitateur ne roule que chariot écarté (y ≥ 0,375) et manivelle en haut ;
  `mycelium.refus_chariot()` dit au chariot de remplissage s'il peut rouler (agitateur au garage manivelle en
  haut, ou au dosage manivelle en bas) ; au garage, pas de rotation avec la course de 10 cm ;
  `mycelium.camera_peut_pivoter()` pour la caméra du dosage ; `mycelium.dosage_en_cours()` pour la griffe.
- **Surveillance** : saut de poids (bocal cassé ou tombé) → arrêt, alarme, photo ; poids qui ne monte plus au
  bout du temps maximal → alarme ; dans les deux cas le seau est marqué « pas bon » (`seaux.defaut`).
- **Registre** : chaque dose avec sa couche (`doses_mycelium.couche`) et son bocal, la variété du bocal
  (`bocaux.variete`).
- **Un bocal pour 2 petits seaux** de la même variété (`seaux_par_bocal: 2`), casse du bloc au 1er seau.
- La manivelle tourne dans le sens qui la ramène vers 0 : le nombre de degrés ne grandit pas sans fin.
- Cases vides : `ChariotRemplissage` (Remplissage), `nouveau_bocal(variete)` (Préhension, QR),
  `photo(raison)` et `controle()` du porte-bocal (Vision).
- **Porte-bocal** (`vidange/porte_bocal/`, tâche 20) : `vidange-porte-bocal etat | origine | ouvrir | serrer |
  tete-en-bas | debout` pour l'essayer sur la carte (`systeme/essai-porte-bocal.md`).

## Préhension (tâche 37)

La tête pend sous le même pont que la griffe, sur son propre mât (axe = pont + 0,129 en x) : ventouse Ø 40
(venturi) pour les seaux vides, couvercles, bocaux et l'entonnoir ; 3 électroaimants pour les capsules ;
rotation (vissage). Module validé le 27/10/2026. Les chiffres sont dans `reglages/machine.yaml` (partie
`prehension`, axes `prehension_z` et `prehension_a`) ; ceux marqués EXEMPLE sont à mesurer
(`systeme/essai-prehension.md`).

```python
carte = reglages.fluidnc.cartes["prehension"]
tete = TeteFluidnc(
    reglages.machine,
    liaison_portique,
    liaison_prehension,
    signaux_prehension(liaison_prehension, carte),
    pesees.capteur("pesee_prehension"),
    CapteurVide(reglages.machine.prehension.vide, lambda: materiel.mesurer("vide_venturi")),
)
tete.demarrer(
    arret
)  # zéro du vide recalé (vanne fermée), puis vide et force ≈ 100 fois par seconde
prehension = Prehension(
    reglages.machine,
    tete,
    porte_bocal,
    panneau_rabattu=poste.panneau_vu_rabattu,
    echange_fut=lambda: poste.echange_en_cours,
)
# Dans l'étape d'un module (Stockage, Lavage...) :
Etape(
    "prendre_un_seau",
    QUOI_FAIRE,
    action=lambda: prehension.lancer(lambda: prehension.geste_prendre("seau", x, y, z, "seau_a")),
    fin=Condition("geste de la préhension fini", prehension.geste_fini),
    delai_max="prehension_geste_max",
)
```

- **Gestes** : `geste_prendre(objet, x, y, contact_z, format)`, `geste_poser(x, y, contact_z)`,
  `geste_poser_bocal()`, `geste_reprendre_bocal()`, `geste_visser(x, y, contact_z, devisser=False)`,
  `geste_aller(x, y)`. `contact_z` = cote de la face de la tête quand elle touche l'objet.
- **Règles** (`regles.py`) : pont puis tête, jamais ensemble, tête en haut avant de bouger le pont ;
  isolation du fût (sous x 0,71, panneau pas vu rabattu ⇒ face en haut) ; bord du seau tenu ; boîtier de la
  caméra du bocal ; boîte de la caméra du dosage ; pas de rotation entre les mors.
- **Prise** : descente au contact (palpage de FluidNC), cote à ± 5 mm, vide −55 kPa, levée lente puis
  normale ; vide au-dessus de −40 kPa pendant la levée → arrêt, reposer, reprendre, alerte au 2ᵉ échec ;
  poids contrôlé (deux seaux emboîtés : reposés).
- **Choc** en trajet (> 15 N d'écart pendant > 50 ms) : arrêt du pont et de la tête, remontée lente, photo.
- `tient_un_objet()` (verrou du noyau du Lavage), `hors_boite_camera_dosage()` (verrou de la caméra du
  dosage), `refus_manuel(pose)` (mode manuel du téléphone).
- **Porte-bocal** : `approcher_mors()` (« Ø 98 » à faible courant) ajouté pour la pose du bocal.
- Essai sur la machine : `vidange-prehension etat | vide | prendre-poser | porte-bocal | visser`.

## Lavage des seaux (tâche 21)

Entre deux fûts de production, un fût de lavage (inox, Ø 0,45) vient au poste : noyau à brosses (dans le
seau), couronne de brosses extérieures, eau chauffée. La Préhension tient le seau retourné et ne le lâche
jamais. Module validé le 25/10/2026. Chiffres : `reglages/machine.yaml` (partie `lavage`, axes
`lavage_noyau` et `lavage_couronne` sur la carte de la tête) ; ceux marqués EXEMPLE sont à mesurer
(`systeme/essai-lavage.md`).

```python
eau = EauLavage(
    reglages.machine.lavage,
    signaux_lavage(liaisons, reglages.fluidnc),
    fichier=donnees / "lavage.json",
)
lavage = Lavage(
    reglages.machine,
    prehension,
    eau,
    mode=lambda: mode.actuel,
    refus_panneau=lambda: poste.refus_lancement("lavage"),
    panneau_rabattu=poste.panneau_vu_rabattu,
)
prehension.lancer(lambda: lavage.geste_laver_seau("seau_a"))  # la tête tient le seau retourné
```

- **Gestes** : `geste_remplir()`, `geste_laver_seau(format)`, `geste_vider()` ; `finir_serie()` refuse tant
  que le fût n'est pas vidé. `eau_a_changer()` après `seaux_max_par_eau` seaux.
- **Laver un seau** : couloir du seau retourné (y 0,74, coude (0,45 ; 0,74)), descente, appui 80 N, arrosage,
  passe 1 (noyau), passe 2 (couronne en avant), rinçage, remontée selon le vide (2 essais), jet d'air du col
  (un tour), égouttage, retour au coude. Noyau, couronne et rotation de la tête dans le même déplacement.
- **Verrou du noyau et de la couronne** (`refus_brosses`, branché sur la préhension) : jamais sans objet
  tenu (vide), tête au-dessus du fût à sa hauteur de travail ; toute perte de vide les arrête. Le pilotage à
  distance ne pilote pas les axes en degrés.
- **Eau** : remplissage borné (premier temps mesuré + 20 %), vidange jusqu'au flotteur bas + 60 s, chauffage
  seulement flotteur haut et pompe arrêtée ; pause : eau, pompe et air coupés, rallumés à la reprise.
- **Mode** : lavage seulement mode « lavage » et panneau du poste rabattu ; panneau qui bouge pendant un
  geste : alarme, la tête et le pont s'arrêtent.
- Essai sur la machine : `vidange-lavage etat | sortie NOM S | remplir | vider | brosses | laver FORMAT x y z`.

## Cartes de pesée du bus RS485 (tâche 22 bis)

Trois cartes RP2040 + HX711 (griffe, préhension, plateau du remplissage) sur un bus RS485 à elles
(adaptateur `rs485_pesee`), lues en Modbus RTU. Leur programme est dans `../pesee/` ; leurs adresses
dans `docs/entrees-sorties.yaml` ; l'ordre des questions et l'étalonnage dans `reglages/pesees.yaml`.

```python
pesees = TourPesees(reglages.pesees, materiel)  # lancé au démarrage du Pi
pesees.demarrer(arret)  # questions sans fin, à tour de rôle
pesees.capteur("pesee_griffe").lire_n()  # newtons (CapteurForce) ; lire_kg() en kg
```

- Chaque carte mesure seule, 80 fois par seconde ; le Pi garde sa dernière mesure. Une mesure plus vieille
  que `age_max_ms`, ou un HX711 muet, lève une erreur : jamais une vieille valeur prise pour bonne.
- La griffe revient deux fois par tour (`tour`) : elle est lue plus de 80 fois par seconde.
- Check-list : une ligne par carte (répond, mesures par seconde, HX711 muet), jamais bloquante.
- `vidange-pesees lire | zero <carte> | etalonner <carte> <kg>` pour les essais
  (`../pesee/essai-etabli.md`).
