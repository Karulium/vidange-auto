"""Fichier de secrets (clé de l'API, mots de passe...), toujours hors de Git.

Le dépôt ne contient que le modèle vide `pi/secrets.exemple.yaml`. Le vrai fichier
s'appelle `secrets.yaml` : Git l'ignore. Sur le Pi, il est dans /etc/vidange/
(voir `pi/systeme/installation.md`), lisible seulement par le compte du programme.
"""

from pathlib import Path

from pydantic import Field, SecretStr, ValidationError, field_validator

from vidange.journal import donner_journal
from vidange.reglages import ErreurReglages, Modele, lire_yaml, rediger, traduire_erreurs

journal = donner_journal("secrets")


class Secrets(Modele):
    """Les secrets connus. Chaque tâche qui a besoin d'un secret l'ajoute ici et dans le modèle."""

    # Clé que l'API du Pi demandera (tâche 8). SecretStr : jamais écrite dans le journal.
    cle_api: SecretStr | None = Field(default=None)

    @field_validator("*", mode="before")
    @classmethod
    def _vide_veut_dire_absent(cls, valeur: object) -> object:
        return None if valeur == "" else valeur


def charger_secrets(chemin: Path) -> Secrets:
    """Lit le fichier de secrets. S'il n'existe pas, les secrets sont vides (pour l'instant)."""
    if not chemin.exists():
        journal.warning(
            "Pas de fichier de secrets (%s) : copier secrets.exemple.yaml et le remplir.", chemin
        )
        return Secrets()
    if chemin.stat().st_mode & 0o077:
        journal.warning(
            "Le fichier de secrets %s est lisible par d'autres comptes : faire « chmod 600 %s ».",
            chemin,
            chemin,
        )
    try:
        return Secrets.model_validate(lire_yaml(chemin))
    except ErreurReglages as erreur:
        raise ErreurReglages(rediger([str(erreur)], chemin.parent)) from None
    except ValidationError as erreur:
        raise ErreurReglages(
            rediger(traduire_erreurs(erreur, chemin.name), chemin.parent)
        ) from None
