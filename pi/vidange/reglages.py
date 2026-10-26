"""Chargement et vérification des fichiers de réglages (`pi/reglages/*.yaml`).

Chaque fichier a son modèle ci-dessous. Au démarrage, tout est vérifié ; la moindre
erreur arrête le programme avec un message en français qui dit quel fichier,
quel réglage, et ce qui ne va pas. Toutes les erreurs sont listées d'un coup.
"""

from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)


class ErreurReglages(Exception):
    """Réglages faux : le programme ne doit pas démarrer."""


class Modele(BaseModel):
    """Base de tous les réglages : un nom inconnu est une erreur (faute de frappe)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# Noms des axes, positions, zones : minuscules sans accent, comme dans le code.
Nom = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
Intervalle = tuple[float, float]


# ---------------------------------------------------------------- machine.yaml


class Axe(Modele):
    """Un axe : longueur de son rail et course permise, en mètres."""

    longueur_rail: float = Field(gt=0)
    course: Intervalle

    @model_validator(mode="after")
    def _verifier_course(self) -> "Axe":
        debut, fin = self.course
        if debut >= fin:
            raise ValueError(
                f"la course doit aller du plus petit au plus grand ({debut:g} puis {fin:g})"
            )
        if debut < 0 or fin > self.longueur_rail:
            raise ValueError(
                f"la course ({debut:g} à {fin:g} m) sort du rail (0 à {self.longueur_rail:g} m)"
            )
        return self


class Machine(Modele):
    """machine.yaml : axes, positions nommées, zones réservées."""

    # Vrai tant que le fichier contient des valeurs inventées : le programme le signale.
    exemple: bool = False
    axes: dict[Nom, Axe] = Field(min_length=1)
    # Une position donne une valeur (m) pour un ou plusieurs axes.
    positions: dict[Nom, dict[Nom, float]] = Field(default_factory=dict)
    # Une zone donne un intervalle (m) pour un ou plusieurs axes ;
    # un axe non cité veut dire « toute sa course ».
    zones: dict[Nom, Annotated[dict[Nom, Intervalle], Field(min_length=1)]] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def _verifier_positions_et_zones(self) -> "Machine":
        erreurs: list[str] = []
        for nom, valeurs in self.positions.items():
            for axe, valeur in valeurs.items():
                if axe not in self.axes:
                    erreurs.append(f"position « {nom} » : axe inconnu « {axe} »")
                    continue
                debut, fin = self.axes[axe].course
                if not debut <= valeur <= fin:
                    erreurs.append(
                        f"position « {nom} » : {axe} = {valeur:g} m sort de la course "
                        f"({debut:g} à {fin:g} m)"
                    )
        zones_correctes = []
        for nom, intervalles in self.zones.items():
            correcte = True
            for axe, (debut, fin) in intervalles.items():
                if axe not in self.axes:
                    erreurs.append(f"zone « {nom} » : axe inconnu « {axe} »")
                    correcte = False
                    continue
                course_debut, course_fin = self.axes[axe].course
                if debut >= fin:
                    erreurs.append(
                        f"zone « {nom} » : sur {axe}, aller du plus petit au plus grand "
                        f"({debut:g} puis {fin:g})"
                    )
                    correcte = False
                elif debut < course_debut or fin > course_fin:
                    erreurs.append(
                        f"zone « {nom} » : sur {axe}, {debut:g} à {fin:g} m sort de la course "
                        f"({course_debut:g} à {course_fin:g} m)"
                    )
                    correcte = False
            if correcte:
                zones_correctes.append(nom)
        for i, nom_a in enumerate(zones_correctes):
            for nom_b in zones_correctes[i + 1 :]:
                if self._se_chevauchent(nom_a, nom_b):
                    erreurs.append(f"les zones « {nom_a} » et « {nom_b} » se chevauchent")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self

    def _se_chevauchent(self, nom_a: str, nom_b: str) -> bool:
        """Deux zones se chevauchent si elles se recouvrent sur tous les axes à la fois."""
        zone_a, zone_b = self.zones[nom_a], self.zones[nom_b]
        for axe in zone_a.keys() | zone_b.keys():
            debut_a, fin_a = zone_a.get(axe, self.axes[axe].course)
            debut_b, fin_b = zone_b.get(axe, self.axes[axe].course)
            # Deux zones qui se touchent juste au bord ne se chevauchent pas.
            if max(debut_a, debut_b) >= min(fin_a, fin_b):
                return False
        return True


# -------------------------------------------------------------- programme.yaml


class Journal(Modele):
    niveau: Literal["detail", "info", "avertissement", "erreur"]
    taille_fichier_mo: float = Field(gt=0)
    nombre_fichiers: int = Field(ge=1)


class Programme(Modele):
    """programme.yaml : réglages du programme lui-même (pas de la machine)."""

    journal: Journal


# --------------------------------------------------------------- l'ensemble


class Reglages(Modele):
    machine: Machine
    programme: Programme


# Nom du fichier → (nom dans Reglages, modèle). Ajouter ici chaque nouveau fichier.
FICHIERS: dict[str, tuple[str, type[Modele]]] = {
    "machine.yaml": ("machine", Machine),
    "programme.yaml": ("programme", Programme),
}


def charger_reglages(dossier: Path) -> Reglages:
    """Lit et vérifie tous les fichiers de réglages, ou lève ErreurReglages."""
    if not dossier.is_dir():
        raise ErreurReglages(f"Le dossier des réglages n'existe pas : {dossier}")
    erreurs: list[str] = []
    for chemin in sorted([*dossier.glob("*.yaml"), *dossier.glob("*.yml")]):
        if chemin.name not in FICHIERS:
            erreurs.append(
                f"{chemin.name} : fichier inconnu (fichiers attendus : {', '.join(FICHIERS)})"
            )
    valeurs: dict[str, Modele] = {}
    for nom_fichier, (cle, modele) in FICHIERS.items():
        chemin = dossier / nom_fichier
        if not chemin.exists():
            erreurs.append(f"{nom_fichier} : fichier manquant")
            continue
        try:
            valeurs[cle] = modele.model_validate(lire_yaml(chemin))
        except ErreurReglages as erreur:
            erreurs.append(str(erreur))
        except ValidationError as erreur:
            erreurs.extend(traduire_erreurs(erreur, nom_fichier))
    if erreurs:
        raise ErreurReglages(rediger(erreurs, dossier))
    return Reglages.model_validate(valeurs)


def rediger(erreurs: list[str], dossier: Path) -> str:
    lignes = "\n".join(f"  - {erreur}" for erreur in erreurs)
    return f"Réglages faux dans {dossier}, le programme ne démarre pas :\n{lignes}"


# ------------------------------------------------------ lecture des fichiers


class _LecteurStrict(yaml.SafeLoader):
    """Lecteur YAML qui refuse un nom écrit deux fois (YAML garderait le second sans rien dire)."""


def _construire_dict(lecteur: _LecteurStrict, noeud: yaml.MappingNode) -> dict[Any, Any]:
    resultat: dict[Any, Any] = {}
    for noeud_cle, noeud_valeur in noeud.value:
        cle = lecteur.construct_object(noeud_cle, deep=True)
        if cle in resultat:
            raise yaml.constructor.ConstructorError(
                None, None, f"« {cle} » est écrit deux fois", noeud_cle.start_mark
            )
        resultat[cle] = lecteur.construct_object(noeud_valeur, deep=True)
    return resultat


_LecteurStrict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construire_dict)


def lire_yaml(chemin: Path) -> dict[str, Any]:
    """Lit un fichier YAML qui doit contenir une liste de « nom: valeur »."""
    try:
        with chemin.open(encoding="utf-8") as fichier:
            donnees = yaml.load(fichier, Loader=_LecteurStrict)
    except yaml.YAMLError as erreur:
        repere = getattr(erreur, "problem_mark", None)
        ligne = f", ligne {repere.line + 1}" if repere is not None else ""
        probleme = getattr(erreur, "problem", None) or str(erreur)
        raise ErreurReglages(f"{chemin.name}{ligne} : fichier mal écrit ({probleme})") from None
    except UnicodeDecodeError:
        raise ErreurReglages(f"{chemin.name} : fichier non enregistré en UTF-8") from None
    if donnees is None:
        raise ErreurReglages(f"{chemin.name} : fichier vide")
    if not isinstance(donnees, dict):
        raise ErreurReglages(f"{chemin.name} : le fichier doit être une liste de « nom: valeur »")
    return donnees


# ---------------------------------------------- erreurs de pydantic en français

_MESSAGES = {
    "missing": "manque",
    "extra_forbidden": "nom inconnu (faute de frappe ?)",
    "float_parsing": "doit être un nombre",
    "float_type": "doit être un nombre",
    "int_parsing": "doit être un nombre entier",
    "int_type": "doit être un nombre entier",
    "int_from_float": "doit être un nombre entier",
    "bool_parsing": "doit être « true » (oui) ou « false » (non)",
    "bool_type": "doit être « true » (oui) ou « false » (non)",
    "string_type": "doit être un texte",
    "dict_type": "doit être une liste de « nom: valeur »",
    "model_type": "doit être une liste de « nom: valeur »",
    "tuple_type": "doit être deux nombres entre crochets, par exemple [0.0, 1.0]",
    "string_pattern_mismatch": "nom à écrire en minuscules, sans accent ni espace (a-z, 0-9, _)",
}


def _message(detail: dict[str, Any]) -> str:
    sorte = detail["type"]
    contexte = detail.get("ctx", {})
    if sorte in _MESSAGES:
        return _MESSAGES[sorte]
    if sorte in ("too_short", "too_long") and detail["loc"] and detail["loc"][-1] == "course":
        return "doit être deux nombres entre crochets, par exemple [0.0, 1.0]"
    if sorte == "too_short":
        return "ne doit pas être vide" if contexte.get("min_length") == 1 else "trop court"
    if sorte == "too_long":
        return "trop d'éléments"
    if sorte == "greater_than":
        return f"doit être plus grand que {contexte['gt']}"
    if sorte == "greater_than_equal":
        return f"doit valoir au moins {contexte['ge']}"
    if sorte == "less_than":
        return f"doit être plus petit que {contexte['lt']}"
    if sorte == "less_than_equal":
        return f"doit valoir au plus {contexte['le']}"
    if sorte == "literal_error":
        return f"doit être l'un de : {contexte['expected']}"
    if sorte == "value_error":
        return str(contexte["error"])
    return detail["msg"]


def traduire_erreurs(erreur: ValidationError, nom_fichier: str) -> list[str]:
    """Une ligne en français par erreur : « fichier, endroit : ce qui ne va pas »."""
    lignes = []
    for detail in erreur.errors():
        # « [key] » : pydantic signale que l'erreur est dans le nom lui-même.
        endroit = " → ".join(str(morceau) for morceau in detail["loc"] if morceau != "[key]")
        debut = f"{nom_fichier}, {endroit}" if endroit else nom_fichier
        for ligne in _message(detail).split("\n"):
            lignes.append(f"{debut} : {ligne}")
    return lignes
