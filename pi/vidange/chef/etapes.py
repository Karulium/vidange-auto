"""Ce qui décrit un module : ses étapes, leurs conditions, leurs actions.

Un module = une liste d'étapes, faites dans l'ordre. Chaque étape :
1. attend le « Go » de Karulium, si elle le demande (règle 6 : le Pi propose, Karulium décide) ;
2. attend ses conditions d'entrée (« la griffe ne descend que si... »), puis réserve ses zones ;
3. lance son action, une seule fois et sans attendre (envoyer du G-code, commander un relais) ;
4. attend sa condition de fin, au plus son délai maximal (un nom de `durees` dans machine.yaml) ;
5. libère les zones qu'elle doit libérer.

Une action doit être **rejouable** : après une alarme ou une coupure de courant, l'étape est
refaite depuis le début (après le Go). « Aller à la position X » est rejouable ;
« avancer de 10 cm » ne l'est pas.

Rien ici ne protège personne : la sécurité est câblée. Les conditions servent à ne pas abîmer
la machine et à attendre le bon moment.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

_NOM = re.compile(r"^[a-z][a-z0-9_]*$")


class ErreurChef(Exception):
    """Module mal décrit, ou ordre impossible (Go à un module qui n'en attend pas...)."""


class ErreurEtape(Exception):
    """Un geste a échoué : le module part en alarme avec ce message."""


@dataclass(frozen=True)
class Condition:
    """Une chose à vérifier, avec son texte en français pour l'écran.

    `test` rend True quand la condition est remplie. S'il lève une erreur (capteur muet...),
    le module part en alarme avec le message de l'erreur.
    """

    # Ce qu'on attend, dit simplement : « griffe hors de la zone du dosage ».
    texte: str
    test: Callable[[], bool]
    # Pour une surveillance : quoi faire si elle n'est plus tenue (sinon celui du module).
    quoi_faire: str = ""


@dataclass(frozen=True)
class Etape:
    nom: str
    # Message affiché si l'étape part en alarme : quoi regarder, quoi faire.
    quoi_faire: str
    # Lancée une fois, sans attendre. None : rien à faire (étape d'attente ou de Go seul).
    action: Callable[[], object] | None = None
    # Quand l'étape est finie. None : finie dès l'action lancée.
    fin: Condition | None = None
    # Nom du délai maximal entre l'action et la fin (machine.yaml → durees).
    delai_max: str | None = None
    # Toutes vraies avant l'action. Tant qu'il en manque une, le module attend (sans délai,
    # sauf `attente_entree_max`).
    entree: tuple[Condition, ...] = ()
    # Nom du délai maximal d'attente des conditions d'entrée et des zones (machine.yaml → durees).
    attente_entree_max: str | None = None
    # Zones (machine.yaml → zones) prises avant l'action ; le module les garde jusqu'à `liberer`
    # (dans cette étape ou une suivante), ou jusqu'à sa fin.
    reserver: tuple[str, ...] = ()
    liberer: tuple[str, ...] = ()
    # Attendre le « Go » de Karulium avant de commencer l'étape.
    demande_go: bool = False


@dataclass(frozen=True)
class Module:
    nom: str
    etapes: tuple[Etape, ...]
    # Vérifiées pendant les gestes (entre l'action et la fin d'une étape) :
    # si l'une n'est plus tenue, alarme (exemple : « carte du portique sans alarme »).
    surveillances: tuple[Condition, ...] = ()
    # Appelés par le chef : pause et reprise (Pause de Karulium), arrêt (alarme, abandon).
    # L'arrêt doit stopper les gestes ; la reprise ne doit relancer que ce que la pause a figé.
    pauser: Callable[[], object] | None = None
    reprendre: Callable[[], object] | None = None
    arreter: Callable[[], object] | None = None

    def __post_init__(self) -> None:
        erreurs = []
        if not _NOM.match(self.nom):
            erreurs.append("nom à écrire en minuscules, sans accent ni espace")
        if not self.etapes:
            erreurs.append("aucune étape")
        vus: set[str] = set()
        for etape in self.etapes:
            if not _NOM.match(etape.nom):
                erreurs.append(f"étape « {etape.nom} » : nom en minuscules, sans accent ni espace")
            if etape.nom in vus:
                erreurs.append(f"étape « {etape.nom} » écrite deux fois")
            vus.add(etape.nom)
            if etape.fin is not None and etape.delai_max is None:
                erreurs.append(f"étape « {etape.nom} » : une condition de fin demande un délai_max")
            if not etape.quoi_faire.strip():
                erreurs.append(f"étape « {etape.nom} » : « quoi faire » vide")
        if erreurs:
            raise ErreurChef(f"module « {self.nom} » mal décrit : " + " ; ".join(erreurs))

    def numero(self, nom_etape: str) -> int:
        for numero, etape in enumerate(self.etapes):
            if etape.nom == nom_etape:
                return numero
        raise ErreurChef(f"module « {self.nom} » : pas d'étape « {nom_etape} »")
