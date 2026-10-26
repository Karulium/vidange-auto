# Programme du Raspberry Pi 5 (le chef)

Paquet Python `vidange` (Python 3.11, comme Raspberry Pi OS Bookworm).
Pour l'instant : démarrage, réglages et liste des entrées/sorties vérifiés, journal, secrets, liaison avec les cartes FluidNC (et faux FluidNC), entrées/sorties du Pi par leur nom (et faux capteurs), chef d'orchestre (moteur d'étapes) avec un module d'exemple, registre (base SQLite) avec copie de secours quotidienne. Pas encore de vrai module de la machine.

## Ce qu'il y a ici

| Chemin | Rôle |
|---|---|
| `vidange/demarrage.py` | Démarrage : lit les réglages, met le journal en place, attend l'arrêt |
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
| `vidange/materiel/puces.py` | GPIO du Pi, bus I2C, PCF8574, MCP23017, ADS1115, SHT31 |
| `vidange/materiel/modbus.py` | Modbus RTU sur RS485 (transmetteurs d'ozone) |
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
| `reglages/machine.yaml` | Axes (et leur carte FluidNC), positions, zones, délais (pour l'instant : un **exemple** inventé) |
| `reglages/programme.yaml` | Réglages du programme lui-même (journal, chef d'orchestre, copie de secours du registre) |
| `reglages/fluidnc.yaml` | Cartes FluidNC (numéro de série USB) et réglages de leur liaison |
| `secrets.exemple.yaml` | Modèle **vide** du fichier de secrets |
| `systeme/vidange.service` | Service qui démarre avec le Pi et se relance s'il plante |
| `systeme/installation.md` | Installation sur le Pi, pas à pas |
| `systeme/essai-entrees-sorties.md` | Essai des entrées/sorties sur le vrai matériel, pas à pas |
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
