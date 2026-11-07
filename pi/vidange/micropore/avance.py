"""Le moteur d'avance du ruban (NEMA 11 sans codeur, carte FluidNC n° 3) : un axe relatif.

    avance = AvanceFluidnc(liaison_carte_3, reglages.machine.micropore.avance)
    avance.avancer(13, 20)     # 13 mm de ruban à 20 mm/s (négatif : recul), sans attendre
    avance.fini()              # vrai quand le mouvement est fini ; ErreurEtape s'il a échoué

Pas d'origine, pas de codeur : un pas perdu se voit seulement au contrôle de chaque morceau par
la caméra. Le Pi envoie « G91 G1 X13.000 F1200 » (mm, mm/min), remet « G90 » (les autres axes de
la carte sont commandés en positions absolues), puis « G4 P0 » : la réponse de cette dernière
ligne arrive quand le mouvement est fini.
"""

import time
from collections.abc import Callable
from typing import Protocol

from vidange.chef import ErreurEtape
from vidange.fluidnc import Commande, Liaison, protocole
from vidange.reglages import AvanceMicropore

QUOI_FAIRE_AVANCE = (
    "Le moteur d'avance du ruban du micropore n'a pas fini son mouvement : vérifier la carte n° 3 "
    "(alarme ?) et le ruban (coincé ?), puis acquitter et donner le Go."
)


class AvanceRuban(Protocol):
    def avancer(self, mm: float, vitesse_mm_s: float) -> None: ...

    def fini(self) -> bool: ...

    def arreter(self) -> None: ...


class AvanceFluidnc:
    def __init__(self, liaison: Liaison, reglages: AvanceMicropore) -> None:
        self.liaison = liaison
        self.lettre = reglages.lettre
        self._commandes: list[Commande] = []

    def avancer(self, mm: float, vitesse_mm_s: float) -> None:
        self._commandes = [
            self.liaison.envoyer(f"G91 G1 {self.lettre}{mm:.3f} F{vitesse_mm_s * 60:.0f}"),
            self.liaison.envoyer("G90"),
            self.liaison.envoyer(protocole.SYNCHRONISATION),
        ]
        self.fini()

    def fini(self) -> bool:
        for commande in self._commandes:
            if commande.erreur is not None:
                raise ErreurEtape(
                    f"micropore, avance du ruban, « {commande.ligne} » : {commande.erreur}",
                    QUOI_FAIRE_AVANCE,
                )
        return all(commande.finie for commande in self._commandes)

    def arreter(self) -> None:
        self.liaison.annuler_deplacement()


class AvanceSimulee:
    """Le moteur imaginaire : il met |mm| / vitesse secondes ; `ruban_mm` compte le ruban poussé."""

    def __init__(self, horloge: Callable[[], float] = time.monotonic) -> None:
        self._horloge = horloge
        self._fin = 0.0
        self.ruban_mm = 0.0
        self.mouvements: list[float] = []

    def avancer(self, mm: float, vitesse_mm_s: float) -> None:
        self._fin = self._horloge() + abs(mm) / vitesse_mm_s
        self.ruban_mm += mm
        self.mouvements.append(mm)

    def fini(self) -> bool:
        return self._horloge() >= self._fin - 1e-9

    def arreter(self) -> None:
        self._fin = self._horloge()
