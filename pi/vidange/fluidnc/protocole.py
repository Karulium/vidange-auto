"""Ce que disent les cartes FluidNC, et les commandes spéciales qu'on leur envoie.

FluidNC parle comme Grbl :
- chaque ligne envoyée reçoit « ok » ou « error:N » quand la carte l'a prise ;
- « ? » demande l'état, qui revient comme « <Idle|MPos:1.000,2.000,3.000|FS:0,0> » ;
- « ALARM:N » arrive quand la carte se met en alarme ;
- « [MSG:...] » et autres lignes entre crochets sont des informations ;
- « Grbl ... » est le message de bienvenue, envoyé quand la carte (re)démarre.
Les positions de FluidNC sont en millimètres.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

# Commandes « temps réel » : un seul caractère, traité tout de suite par la carte,
# sans passer par la file des lignes et sans réponse « ok ».
DEMANDE_ETAT = b"?"
PAUSE = b"!"
REPRISE = b"~"
REINITIALISATION = b"\x18"  # Ctrl-X : vide les files de la carte.
CARACTERES_TEMPS_REEL = frozenset("?!~\x18")

# Lignes de commande de FluidNC.
DEBLOCAGE = "$X"
PRISE_ORIGINE = "$H"
# « Attendre 0 s » : la carte ne répond « ok » qu'une fois tous les mouvements d'avant finis.
SYNCHRONISATION = "G4 P0"

# Ordre des axes dans les positions envoyées par FluidNC (jusqu'à 6 axes).
LETTRES_AXES = "XYZABC"

# Alarmes de FluidNC (d'après sa documentation), en clair.
ALARMES = {
    1: "fin de course matérielle touchée",
    2: "mouvement demandé hors des limites logicielles",
    3: "réinitialisation pendant un mouvement : position perdue",
    4: "palpeur : déjà touché au départ",
    5: "palpeur : rien touché",
    6: "prise d'origine interrompue par une réinitialisation",
    7: "prise d'origine interrompue par l'ouverture d'une porte",
    8: "prise d'origine : le fin de course ne se libère pas",
    9: "prise d'origine : fin de course jamais atteint",
    10: "commande de broche (moteur d'outil) en défaut",
    11: "une entrée de commande est active au démarrage",
    12: "prise d'origine : fin de course ambigu",
    13: "arrêt dur",
    14: "position inconnue : prise d'origine à faire",
    15: "erreur au démarrage de la carte",
    16: "carte d'extension réinitialisée",
}

# Erreurs les plus utiles à reconnaître (« error:N » en réponse à une ligne).
ERREURS = {
    1: "lettre de commande attendue",
    2: "nombre mal écrit",
    3: "commande « $ » inconnue",
    8: "commande refusée tant que la carte n'est pas au repos",
    9: "G-code refusé : carte en alarme ou bloquée",
    15: "déplacement hors des limites logicielles",
    20: "commande G-code inconnue ou interdite",
    22: "vitesse d'avance (F) jamais donnée",
}

# États de FluidNC, en clair (pour le journal).
ETATS = {
    "Idle": "au repos",
    "Run": "en mouvement",
    "Hold": "en pause",
    "Jog": "en déplacement manuel",
    "Alarm": "en alarme",
    "Door": "porte ouverte",
    "Check": "en vérification de G-code",
    "Home": "en prise d'origine",
    "Sleep": "en veille",
}


def decrire_alarme(numero: int) -> str:
    return f"alarme {numero} : {ALARMES.get(numero, 'inconnue (voir la documentation FluidNC)')}"


def decrire_erreur(numero: int) -> str:
    return f"erreur {numero} : {ERREURS.get(numero, 'voir la documentation FluidNC')}"


def decrire_etat(etat: str) -> str:
    principal = etat.split(":")[0]
    return ETATS.get(principal, etat)


@dataclass(frozen=True)
class RapportEtat:
    """Réponse à « ? »."""

    # État de FluidNC tel quel : « Idle », « Run », « Hold:0 », « Alarm »...
    etat: str
    # Positions en mm, par lettre d'axe. Repère « machine » (MPos) normalement.
    positions: dict[str, float]
    repere: Literal["machine", "travail"]
    # Vitesse d'avance en cours (mm/min), si la carte la donne.
    vitesse: float | None = None
    # Décalage entre repère machine et repère de travail (WCO), quand la carte l'envoie.
    decalage: dict[str, float] | None = None
    # Entrées actives (« Pn: »), par exemple « XP » : fin de course X et palpeur.
    entrees_actives: str = ""
    # Le reste, tel quel (« Ov: », « Bf: »...).
    autres: dict[str, str] = field(default_factory=dict)


def _nombres_par_axe(texte: str) -> dict[str, float]:
    valeurs = [float(morceau) for morceau in texte.split(",")]
    if len(valeurs) > len(LETTRES_AXES):
        raise ValueError("trop d'axes")
    return dict(zip(LETTRES_AXES, valeurs, strict=False))


def lire_rapport_etat(ligne: str) -> RapportEtat | None:
    """Lit « <Idle|MPos:...|FS:...> ». Rend None si la ligne n'en est pas un ou est abîmée."""
    if not (ligne.startswith("<") and ligne.endswith(">")):
        return None
    morceaux = ligne[1:-1].split("|")
    etat = morceaux[0]
    positions: dict[str, float] | None = None
    repere: Literal["machine", "travail"] = "machine"
    vitesse = None
    decalage = None
    entrees = ""
    autres: dict[str, str] = {}
    try:
        for morceau in morceaux[1:]:
            cle, _, valeur = morceau.partition(":")
            if cle == "MPos":
                positions = _nombres_par_axe(valeur)
            elif cle == "WPos":
                positions = _nombres_par_axe(valeur)
                repere = "travail"
            elif cle == "WCO":
                decalage = _nombres_par_axe(valeur)
            elif cle in ("FS", "F"):
                vitesse = float(valeur.split(",")[0])
            elif cle == "Pn":
                entrees = valeur
            else:
                autres[cle] = valeur
    except ValueError:
        return None
    if not etat or positions is None:
        return None
    return RapportEtat(etat, positions, repere, vitesse, decalage, entrees, autres)


_ERREUR = re.compile(r"^error:(\d+)$")
_ALARME = re.compile(r"^ALARM:(\d+)$")

SorteLigne = Literal["ok", "erreur", "alarme", "etat", "bienvenue", "message", "autre"]


def classer_ligne(ligne: str) -> tuple[SorteLigne, int | None]:
    """Dit ce qu'est une ligne reçue, avec son numéro pour une erreur ou une alarme."""
    if ligne == "ok":
        return "ok", None
    if trouve := _ERREUR.match(ligne):
        return "erreur", int(trouve.group(1))
    if trouve := _ALARME.match(ligne):
        return "alarme", int(trouve.group(1))
    if ligne.startswith("<"):
        return "etat", None
    if ligne.startswith("Grbl "):
        return "bienvenue", None
    if ligne.startswith("["):
        return "message", None
    return "autre", None
