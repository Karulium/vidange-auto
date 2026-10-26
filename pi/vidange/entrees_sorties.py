"""Liste des entrées/sorties de la machine (`docs/entrees-sorties.yaml`).

Chaque capteur, relais ou bus y a un nom, sa carte, sa broche, son type de signal,
sa tension, son état au repos et son module. Le code ne connaît que le nom.

Vérifié par les tests et au démarrage : broche utilisée deux fois, adresse en double
sur un bus, carte ou module inconnu, trop d'entrées ou de sorties sur une carte,
tension trop forte (surtout du 24 V sur une carte sans isolement). Toutes les erreurs
sont listées d'un coup, comme pour les réglages.
"""

from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from vidange.reglages import (
    ErreurReglages,
    Modele,
    Nom,
    lire_yaml,
    rediger,
    traduire_erreurs,
)

ENTREES = ("contact", "pnp", "npn", "mesure")
SORTIES = ("relais", "logique")
BUS = ("i2c", "serie")
# Types qui ont un état au repos (contact ouvert ou fermé).
AVEC_REPOS = ("contact", "pnp", "npn", "relais")

TypeSignal = Literal["contact", "pnp", "npn", "mesure", "relais", "logique", "i2c", "serie"]


class Carte(Modele):
    """Une carte où l'on branche des signaux."""

    exemple: bool = False
    description: str
    # Vide : broches à tout faire (GPIO du Pi), seul le double emploi est vérifié.
    entrees: int | None = Field(default=None, ge=0)
    sorties: int | None = Field(default=None, ge=0)
    tension_max: float = Field(gt=0)
    isolee: bool


class Signal(Modele):
    """Un capteur, un relais ou un bus."""

    exemple: bool = False
    description: str = ""
    carte: Nom
    broche: tuple[str, ...]
    type: TypeSignal
    tension: float = Field(gt=0)
    repos: Literal["ouvert", "ferme"] | None = None
    adresse: int | None = Field(default=None, ge=0)
    module: Nom

    @field_validator("broche", mode="before")
    @classmethod
    def _une_ou_plusieurs(cls, valeur: Any) -> tuple[str, ...]:
        """Une broche seule (E1) ou une liste ([GPIO2, GPIO3]), toujours rangée en liste."""
        if not isinstance(valeur, list):
            valeur = [valeur]
        if not valeur or not all(_est_une_broche(broche) for broche in valeur):
            raise ValueError(
                "doit être une broche (exemple : E1) ou une liste entre crochets "
                "(exemple : [GPIO2, GPIO3])"
            )
        return tuple(str(broche).strip() for broche in valeur)

    @model_validator(mode="after")
    def _verifier_champs(self) -> "Signal":
        erreurs: list[str] = []
        if self.type in AVEC_REPOS and self.repos is None:
            erreurs.append(
                f"un signal de type {self.type} doit dire son état au repos : "
                "« repos: ouvert » ou « repos: ferme »"
            )
        if self.type not in AVEC_REPOS and self.repos is not None:
            erreurs.append(f"« repos » n'a pas de sens pour un signal de type {self.type}")
        if self.type == "i2c" and self.adresse is None:
            erreurs.append("un signal i2c doit avoir son adresse (exemple : « adresse: 0x48 »)")
        if self.type not in BUS and self.adresse is not None:
            erreurs.append("« adresse » ne sert qu'aux bus (i2c, serie)")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


def _est_une_broche(broche: Any) -> bool:
    return isinstance(broche, str | int) and not isinstance(broche, bool) and str(broche).strip()


class EntreesSorties(Modele):
    """entrees-sorties.yaml en entier."""

    tension_max_sans_isolement: float = Field(gt=0)
    modules: list[Nom] = Field(min_length=1)
    cartes: dict[Nom, Carte] = Field(min_length=1)
    signaux: dict[Nom, Signal] = Field(default_factory=dict)

    def exemples(self) -> list[str]:
        """Noms des cartes et signaux encore marqués « exemple »."""
        return [
            nom for nom, ligne in [*self.cartes.items(), *self.signaux.items()] if ligne.exemple
        ]

    @model_validator(mode="after")
    def _verifier_ensemble(self) -> "EntreesSorties":
        erreurs: list[str] = []
        for nom, signal in self.signaux.items():
            if signal.module not in self.modules:
                erreurs.append(
                    f"signal « {nom} » : module inconnu « {signal.module} » "
                    f"(modules connus : {', '.join(self.modules)})"
                )
            if signal.carte not in self.cartes:
                erreurs.append(f"signal « {nom} » : carte inconnue « {signal.carte} »")
            else:
                erreurs.extend(self._verifier_tension(nom, signal))
        connus = {nom: s for nom, s in self.signaux.items() if s.carte in self.cartes}
        erreurs.extend(self._verifier_broches(connus))
        erreurs.extend(self._verifier_adresses(connus))
        erreurs.extend(self._verifier_nombres(connus))
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self

    def _verifier_tension(self, nom: str, signal: Signal) -> list[str]:
        carte = self.cartes[signal.carte]
        if not carte.isolee and signal.tension > self.tension_max_sans_isolement:
            return [
                f"signal « {nom} » : {signal.tension:g} V sur la carte « {signal.carte} » "
                "qui n'est pas isolée : la brancher sur une carte d'entrées optocouplées "
                "ou passer par un relais"
            ]
        if signal.tension > carte.tension_max:
            return [
                f"signal « {nom} » : {signal.tension:g} V, plus que les {carte.tension_max:g} V "
                f"acceptés par la carte « {signal.carte} »"
            ]
        return []

    @staticmethod
    def _verifier_broches(signaux: dict[str, Signal]) -> list[str]:
        """Une broche ne sert qu'à un signal, sauf un bus partagé (chacun son adresse)."""
        par_broche: dict[tuple[str, str], list[str]] = defaultdict(list)
        reperes: dict[tuple[str, str], str] = {}
        for nom, signal in signaux.items():
            for broche in signal.broche:
                # GPIO2 et gpio2 sont la même broche.
                cle = (signal.carte, broche.lower())
                par_broche[cle].append(nom)
                reperes.setdefault(cle, broche)
        erreurs = []
        for cle, noms in par_broche.items():
            if len(noms) < 2:
                continue
            types = {signaux[nom].type for nom in noms}
            bus_partage = len(types) == 1 and types <= set(BUS)
            if bus_partage and all(signaux[nom].adresse is not None for nom in noms):
                continue
            message = (
                f"carte « {cle[0]} », broche {reperes[cle]} : utilisée par plusieurs signaux "
                f"({', '.join(noms)})"
            )
            if bus_partage:
                message += " ; sur un bus partagé, chacun doit avoir son adresse"
            erreurs.append(message)
        return erreurs

    @staticmethod
    def _verifier_adresses(signaux: dict[str, Signal]) -> list[str]:
        """Sur un même bus (même carte, mêmes broches), deux appareils n'ont pas la même adresse."""
        par_adresse: dict[tuple[str, frozenset[str], int], list[str]] = defaultdict(list)
        for nom, signal in signaux.items():
            if signal.type in BUS and signal.adresse is not None:
                broches = frozenset(broche.lower() for broche in signal.broche)
                par_adresse[(signal.carte, broches, signal.adresse)].append(nom)
        erreurs = []
        for (carte, _, adresse), noms in par_adresse.items():
            if len(noms) > 1:
                bus = signaux[noms[0]]
                erreurs.append(
                    f"bus {bus.type} de la carte « {carte} » ({', '.join(bus.broche)}) : "
                    f"adresse 0x{adresse:02x} utilisée par plusieurs signaux ({', '.join(noms)})"
                )
        return erreurs

    def _verifier_nombres(self, signaux: dict[str, Signal]) -> list[str]:
        """Pas plus d'entrées ni de sorties branchées que la carte n'en a."""
        erreurs = []
        for nom_carte, carte in self.cartes.items():
            sur_la_carte = [s for s in signaux.values() if s.carte == nom_carte]
            for sorte, types, disponibles in (
                ("entrées", ENTREES, carte.entrees),
                ("sorties", SORTIES, carte.sorties),
            ):
                branchees = sum(1 for s in sur_la_carte if s.type in types)
                if disponibles is not None and branchees > disponibles:
                    erreurs.append(
                        f"carte « {nom_carte} » : {branchees} {sorte} branchées "
                        f"pour {disponibles} disponibles"
                    )
        return erreurs


def charger_entrees_sorties(chemin: Path) -> EntreesSorties:
    """Lit et vérifie la liste des entrées/sorties, ou lève ErreurReglages."""
    if not chemin.is_file():
        raise ErreurReglages(rediger([f"{chemin.name} : fichier manquant"], chemin.parent))
    try:
        return EntreesSorties.model_validate(lire_yaml(chemin))
    except ErreurReglages as erreur:
        raise ErreurReglages(rediger([str(erreur)], chemin.parent)) from None
    except ValidationError as erreur:
        raise ErreurReglages(
            rediger(traduire_erreurs(erreur, chemin.name), chemin.parent)
        ) from None
