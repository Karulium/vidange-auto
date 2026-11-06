"""Cases vides du Nettoyage : capteurs de particules et de pression, consigne 0-10 V du ventilateur.

Leurs références ne sont pas encore choisies (particules : PMS5003 ou SPS30, en UART ; pression
différentielle enceinte / conteneur ; convertisseur de la consigne 0-10 V). Ici, seulement ce que
le Nettoyage attend d'eux, et des faux pour les tests et le simulateur. **Pas de pilote réel** :
il viendra quand la pièce sera choisie (et son signal ajouté à docs/entrees-sorties.yaml).

    dedans = FauxCapteur("particules_dedans", "µg/m³", 35.0)
    dedans.lire()          # 35.0 ; lève ErreurMateriel s'il est muet
    dedans.muet = True
    consigne = FausseConsigne()
    consigne.regler(10.0)  # volts

Sans capteur (None), la condition de purge qui en dépend n'est **jamais vraie** : la purge
finit en alerte à 20 min (Karulium décide), jamais « vraie par défaut ».
"""

from typing import Protocol

from vidange.materiel.puces import ErreurMateriel


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
