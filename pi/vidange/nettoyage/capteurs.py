"""Capteurs de la purge et consigne 0-10 V du ventilateur : ce que le Nettoyage attend d'eux.

Pièces choisies le 06/11/2026 (tâche 38 ter) : particules SPS30 (`particules_dedans` et
`particules_dehors`), pression différentielle SDP810-125Pa (`pression_enceinte`), module
PWM → 0-10 V (`consigne_ventilateur`). Leurs pilotes sont dans `vidange/materiel/` ; ici, les
raccords au Matériel (`CapteurDuMateriel`, `ConsigneDuMateriel`) et des faux pour les tests et le
simulateur.

    dedans = FauxCapteur("particules_dedans", "µg/m³", 35.0)
    dedans.lire()          # 35.0 ; lève ErreurMateriel s'il est muet
    dedans.muet = True
    consigne = FausseConsigne()
    consigne.regler(10.0)  # volts

Sans capteur (None), ou capteur muet, en erreur, trame fausse : la condition de purge qui en
dépend n'est **jamais vraie** : la purge finit en alerte à 20 min (Karulium décide), jamais
« vraie par défaut ».
"""

from typing import Protocol

from vidange.entrees_sorties import EntreesSorties
from vidange.materiel.materiel import Materiel
from vidange.materiel.puces import ErreurMateriel
from vidange.reglages import Nettoyage as ReglagesNettoyage

# Noms de ces signaux dans docs/entrees-sorties.yaml.
PARTICULES_DEDANS = "particules_dedans"
PARTICULES_DEHORS = "particules_dehors"
PRESSION_ENCEINTE = "pression_enceinte"
CONSIGNE_VENTILATEUR = "consigne_ventilateur"


class CapteurMesure(Protocol):
    """Un capteur qui donne une valeur dans son unité (particules : µg/m³ ; pression : Pa)."""

    nom: str

    def lire(self) -> float:
        """La dernière mesure ; lève ErreurMateriel s'il ne répond pas (muet, débranché)."""
        ...


class Consigne(Protocol):
    """La sortie 0-10 V du moteur EC du ventilateur (il s'arrête sans signal)."""

    def regler(self, volts: float) -> None:
        """Lève ErreurMateriel si le convertisseur ne répond pas."""
        ...


class FauxCapteur:
    """Un faux capteur de particules ou de pression (tests, simulateur)."""

    def __init__(self, nom: str, unite: str, valeur: float | None = None) -> None:
        self.nom = nom
        self.unite = unite
        # None : pas encore de mesure (comme muet).
        self.valeur = valeur
        self.muet = False
        self.lectures = 0

    def lire(self) -> float:
        self.lectures += 1
        if self.muet or self.valeur is None:
            raise ErreurMateriel(f"{self.nom} : capteur muet")
        return self.valeur


class FausseConsigne:
    """Une fausse sortie 0-10 V : garde la dernière consigne et toutes celles reçues."""

    def __init__(self) -> None:
        self.volts: float | None = None
        self.reglees: list[float] = []
        self.en_panne = False

    def regler(self, volts: float) -> None:
        if self.en_panne:
            raise ErreurMateriel("consigne du ventilateur : convertisseur muet")
        self.volts = volts
        self.reglees.append(volts)


class CapteurDuMateriel:
    """Un vrai capteur de la purge (SPS30, SDP810), lu par son nom dans le Matériel.

    `lire` lève ErreurMateriel (CapteurMuet) s'il ne répond pas ou répond faux : jamais une
    valeur inventée."""

    def __init__(self, materiel: Materiel, nom: str) -> None:
        self.materiel = materiel
        self.nom = nom

    def lire(self) -> float:
        return self.materiel.mesurer(self.nom)


class ConsigneDuMateriel:
    """La vraie sortie 0-10 V (module PWM), réglée par son nom dans le Matériel."""

    def __init__(self, materiel: Materiel, nom: str = CONSIGNE_VENTILATEUR) -> None:
        self.materiel = materiel
        self.nom = nom

    def regler(self, volts: float) -> None:
        self.materiel.regler_consigne(self.nom, volts)


def capteurs_du_materiel(
    materiel: Materiel,
) -> tuple[CapteurMesure | None, CapteurMesure | None, CapteurMesure | None, Consigne | None]:
    """(particules dedans, particules dehors, pression, consigne) : ceux qui sont dans la liste
    des entrées/sorties, None pour les autres (ils restent « absents » pour le Nettoyage)."""

    def capteur(nom: str) -> CapteurMesure | None:
        return CapteurDuMateriel(materiel, nom) if nom in materiel.branchements else None

    consigne = (
        ConsigneDuMateriel(materiel) if CONSIGNE_VENTILATEUR in materiel.branchements else None
    )
    return (
        capteur(PARTICULES_DEDANS),
        capteur(PARTICULES_DEHORS),
        capteur(PRESSION_ENCEINTE),
        consigne,
    )


def verifier_avec_liste(reglages: ReglagesNettoyage, liste: EntreesSorties) -> list[str]:
    """Ce que machine.yaml (niveaux du ventilateur) et entrees-sorties.yaml (module 0-10 V)
    disent doit aller ensemble."""
    signal = liste.signaux.get(CONSIGNE_VENTILATEUR)
    if signal is None or signal.pwm is None:
        return []
    plein = signal.pwm.pleine_echelle_v
    if reglages.ventilateur.plein_v > plein:
        return [
            f"machine.yaml, nettoyage → ventilateur → plein_v ({reglages.ventilateur.plein_v:g} V) "
            f"dépasse la tension du module 0-10 V (entrees-sorties.yaml, {CONSIGNE_VENTILATEUR} → "
            f"pwm → pleine_echelle_v : {plein:g} V)"
        ]
    return []
