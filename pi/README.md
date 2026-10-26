# Programme du Raspberry Pi 5 (le chef)

Paquet Python `vidange` (Python 3.11, comme Raspberry Pi OS Bookworm).
Pour l'instant : démarrage, réglages et liste des entrées/sorties vérifiés, journal, secrets, liaison avec les cartes FluidNC (et faux FluidNC), entrées/sorties du Pi par leur nom (et faux capteurs). Pas encore de logique de machine.

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
| `reglages/machine.yaml` | Axes, positions, zones (pour l'instant : un **exemple** inventé) |
| `reglages/programme.yaml` | Réglages du programme lui-même (journal) |
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
