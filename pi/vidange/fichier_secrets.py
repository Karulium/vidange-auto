"""Fichier de secrets (clé de l'API, mots de passe...), toujours hors de Git.

Le dépôt ne contient que le modèle vide `pi/secrets.exemple.yaml`. Le vrai fichier
s'appelle `secrets.yaml` : Git l'ignore. Sur le Pi, il est dans /etc/vidange/
(voir `pi/systeme/installation.md`), lisible seulement par le compte du programme.
"""

import re
from pathlib import Path

from pydantic import Field, SecretStr, ValidationError, field_validator

from vidange.journal import donner_journal
from vidange.reglages import ErreurReglages, Modele, lire_yaml, rediger, traduire_erreurs

journal = donner_journal("secrets")

# Une clé plus courte se devine trop vite.
LONGUEUR_MIN_CLE = 16
# Un sujet ntfy se devine d'autant plus vite qu'il est court : qui le connaît lit les messages.
LONGUEUR_MIN_SUJET = 16
_SUJET_NTFY = re.compile(r"^[A-Za-z0-9_-]+$")


class Secrets(Modele):
    """Les secrets connus. Chaque tâche qui a besoin d'un secret l'ajoute ici et dans le modèle."""

    # OBSOLÈTE depuis la tâche 25 : la page web et l'API demandent maintenant un nom et un mot de
    # passe (comptes.yaml, commande « vidange compte »). Ce champ est encore permis pour ne pas
    # casser un ancien fichier, mais il ne sert plus à rien. SecretStr : jamais écrite au journal.
    cle_api: SecretStr | None = Field(default=None)
    # Jeton du logiciel de culture (Django REST Framework, « Token ») pour lui envoyer les cycles.
    jeton_culture: SecretStr | None = Field(default=None)
    # Jeton GitHub en lecture seule, pour la mise à jour du programme du Pi (tâche 13) quand le
    # dépôt est privé.
    jeton_github: SecretStr | None = Field(default=None)

    # Notifications sur le téléphone (tâche 27). Sans « ntfy_serveur » et « ntfy_sujet », ntfy est
    # éteint ; sans « telegram_jeton_bot » et « telegram_chat », Telegram est éteint. Ce n'est
    # pas une erreur : la check-list le dit. Le sujet ntfy est un secret : qui le connaît lit
    # tous les messages (et peut en écrire).
    ntfy_serveur: str | None = Field(default=None)
    ntfy_sujet: SecretStr | None = Field(default=None)
    # Jeton d'accès (seulement pour un serveur ntfy protégé par mot de passe).
    ntfy_jeton: SecretStr | None = Field(default=None)
    # 2ᵉ liste de destinataires (escalade) : d'autres sujets ntfy, d'autres conversations Telegram.
    ntfy_sujets_renfort: list[SecretStr] = Field(default_factory=list)
    telegram_jeton_bot: SecretStr | None = Field(default=None)
    telegram_chat: SecretStr | None = Field(default=None)
    telegram_chats_renfort: list[SecretStr] = Field(default_factory=list)

    @field_validator("*", mode="before")
    @classmethod
    def _vide_veut_dire_absent(cls, valeur: object) -> object:
        return None if valeur == "" else valeur

    @field_validator("ntfy_sujets_renfort", "telegram_chats_renfort", mode="before")
    @classmethod
    def _liste_sans_vides(cls, valeur: object) -> object:
        if valeur is None:
            return []
        if isinstance(valeur, list):
            return [element for element in valeur if element != ""]
        return valeur

    @field_validator("ntfy_serveur")
    @classmethod
    def _serveur_ntfy(cls, serveur: str | None) -> str | None:
        if serveur is not None and not serveur.startswith(("http://", "https://")):
            raise ValueError(
                f"« {serveur} » : l'adresse du serveur ntfy doit commencer par http:// ou https://"
            )
        return serveur.rstrip("/") if serveur else serveur

    @field_validator("ntfy_sujet", "ntfy_sujets_renfort")
    @classmethod
    def _sujet_ntfy(cls, valeur: SecretStr | list[SecretStr] | None):
        sujets = valeur if isinstance(valeur, list) else [] if valeur is None else [valeur]
        for sujet in sujets:
            texte = sujet.get_secret_value()
            if len(texte) < LONGUEUR_MIN_SUJET or not _SUJET_NTFY.match(texte):
                raise ValueError(
                    f"sujet ntfy trop facile à deviner ou mal écrit : au moins "
                    f"{LONGUEUR_MIN_SUJET} caractères, lettres, chiffres, « - » et « _ » "
                    "seulement. "
                    "En fabriquer un avec "
                    "« python3 -c 'import secrets; print(secrets.token_urlsafe(18))' »"
                )
        return valeur

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
