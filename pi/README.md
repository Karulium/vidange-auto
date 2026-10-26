# Programme du Raspberry Pi 5 (le chef)

Paquet Python `vidange` (Python 3.11, comme Raspberry Pi OS Bookworm).
Pour l'instant : démarrage, réglages vérifiés, journal, secrets. Pas encore de logique de machine.

## Ce qu'il y a ici

| Chemin | Rôle |
|---|---|
| `vidange/demarrage.py` | Démarrage : lit les réglages, met le journal en place, attend l'arrêt |
| `vidange/reglages.py` | Lecture et vérification des fichiers de `reglages/` |
| `vidange/journal.py` | Journal (logs) commun : `donner_journal("nom")` |
| `vidange/fichier_secrets.py` | Lecture du fichier de secrets (hors Git) |
| `reglages/machine.yaml` | Axes, positions, zones (pour l'instant : un **exemple** inventé) |
| `reglages/programme.yaml` | Réglages du programme lui-même (journal) |
| `secrets.exemple.yaml` | Modèle **vide** du fichier de secrets |
| `systeme/vidange.service` | Service qui démarre avec le Pi et se relance s'il plante |
| `systeme/installation.md` | Installation sur le Pi, pas à pas |
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

## Ajouter un fichier de réglages

1. Écrire son modèle dans `vidange/reglages.py` (classe qui hérite de `Modele`).
2. L'ajouter à `FICHIERS` et à `Reglages`.
3. Mettre le fichier dans `reglages/` et des tests dans `tests/test_reglages.py`.

## Codes de sortie

- `0` : arrêt normal.
- `1` : plantage imprévu (systemd relance le programme 5 s après).
- `2` : réglages faux (systemd ne relance pas : corriger les réglages, puis relancer le service).
