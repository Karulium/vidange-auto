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

# Une clé plus courte se devine trop vite.
LONGUEUR_MIN_CLE = 16


class Secrets(Modele):
    """Les secrets connus. Chaque tâche qui a besoin d'un secret l'ajoute ici et dans le modèle."""

    # Clé que l'API du Pi demandera (tâche 8). SecretStr : jamais écrite dans le journal.
    cle_api: SecretStr | None = Field(default=None)

    @field_validator("*", mode="before")
    @classmethod
    def _vide_veut_dire_absent(cls, valeur: object) -> object:
        return None if valeur == "" else valeur

    @field_validator("cle_api")
    @classmethod
    def _cle_assez_longue(cls, cle: SecretStr | None) -> SecretStr | None:
        if cle is not None and len(cle.get_secret_value()) < LONGUEUR_MIN_CLE:
            raise ValueError(
                f"clé trop courte : au moins {LONGUEUR_MIN_CLE} caractères. En fabriquer une avec "
                "« python3 -c 'import secrets; print(secrets.token_urlsafe(24))' »"
            )
        return cle


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
