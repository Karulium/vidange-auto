"""Les pièces du mode seaux sur la machine (programme principal, tâche 45).

Ce qui manque aujourd'hui pour qu'un lot parte sur la machine est dit poste par poste (check-list,
écran, journal), sans rien inventer :
- seau vide et couvercle : les cartes du chariot et de la tête (ChariotFluidnc, TeteFluidnc) seront
  construites ici avec la vision du micropore ; le couvercle (vidange.couvercle, tâche 41 bis)
  sera construit avec elles, sur la même tête ;
- QR du flanc : il est lu par la caméra du micropore pendant que le plateau tourne le seau (fil
  Guidage caméra, 07/11/2026). La vision est écrite (vidange.vision.inspection, tâche 40 ter) ;
  elle n'est pas lancée sur la vraie machine tant que ses réglages sont des EXEMPLES
  (vision.yaml → inspection) ou que la caméra n'est pas déclarée ; elle a aussi besoin de l'angle
  du plateau, donc de la carte du chariot (le poste attend alors « seau_vide ») ;
- spray : la carte du spray doit être ouverte (signal de docs/entrees-sorties.yaml) ;
- mycélium : la pose du bocal de semence neuf dans le porte-bocal par la préhension n'est pas écrite
  (case vide `nouveau_bocal` du Mycélium) ;
- micropore : sa vision est écrite (tâche 40 ter, mêmes conditions que le QR du flanc) ; il lui
  manque la carte de la tête (servos, capteur de distance, moteur d'avance) ;
- stockage : il faut le signal de la boucle du tiroir et des panneaux.
Les cases vides d'ORDRE_SEAU (griffe, lavage) sont dites par le mode lui-même.

Mode bocaux et nuit UV-ozone (tâche 45 bis) :
- entonnoir : la Préhension (cartes de la tête, comme les seaux) n'est pas encore construite ici,
  et la lecture de la photo du plafond (l'entonnoir est-il sur le bocal ? où est le centre du col ?)
  n'est pas écrite : le module « entonnoir » ne part pas ;
- lavage des bocaux : le Lavage (Préhension, eau du fût de lavage) n'est pas construit ici non
  plus, et la liste des bocaux sales vient de la caméra du plafond (règle 7), pas écrite ;
- nuit UV-ozone : tout est là (le Nettoyage tourne déjà) ; elle ne manque que si le Nettoyage n'est
  pas construit ou si un signal de la nuit manque dans la liste des entrées/sorties.
"""

from collections.abc import Callable
from pathlib import Path

from vidange.cycle.mode_bocaux import LotBocaux, PiecesEntonnoir, PiecesLavageBocaux
from vidange.cycle.mode_seaux import Lot, PiecesRemplissage
from vidange.materiel import Materiel
from vidange.nettoyage.nettoyage import (
    GENERATEUR,
    LAMPE_UV,
    OZONE_DEDANS,
    OZONE_DEHORS,
    Nettoyage,
)
from vidange.poste_fut import PosteFut
from vidange.reglages import ReglagesVision
from vidange.spray.spray import Spray
from vidange.stockage.simulation import BOUCLE
from vidange.vision.inspection import NOM_ECARTS, EcartsAttaches, Regard, VisionInspection

VISION_ABSENTE = "vision.yaml pas donné aux pièces : la caméra du micropore ne peut pas lire"
INSPECTION_ABSENTE = "vision.yaml n'a pas de partie « inspection » (caméra du micropore)"
INSPECTION_EXEMPLE = (
    "valeurs d'EXEMPLE dans vision.yaml (inspection) : interdit sur la vraie machine"
)
CAMERA_ABSENTE = "caméra du micropore pas ouverte (photographe absent)"
CARTES_DU_CHARIOT = (
    "cartes du chariot et de la tête pas encore branchées au mode seaux (angle du plateau, tête "
    "du micropore)"
)
CARTE_DE_LA_TETE = (
    "carte de la tête du micropore (servos, capteur de distance, moteur d'avance) pas encore "
    "branchée au mode seaux"
)
CARTE_SPRAY = "carte du spray pas ouverte (signal absent de docs/entrees-sorties.yaml ?)"
BOCAL_NEUF = (
    "pose du bocal de semence neuf dans le porte-bocal par la préhension pas écrite (case vide "
    "« nouveau_bocal » du Mycélium)"
)
ENTONNOIR = (
    "Préhension (cartes de la tête) pas encore branchée au programme principal, et lecture de la "
    "photo du plafond (entonnoir sur le bocal, centre du col) pas écrite"
)
LAVAGE_DES_BOCAUX = (
    "Lavage (Préhension, eau du fût de lavage) pas encore branché au programme principal, et "
    "liste des bocaux sales (caméra du plafond, règle 7) pas écrite"
)
NETTOYAGE_ABSENT = "Nettoyage pas lancé (partie « nettoyage » de machine.yaml ou entrées/sorties)"
SIGNAUX_DE_LA_NUIT = (OZONE_DEDANS, OZONE_DEHORS, GENERATEUR, LAMPE_UV)


class PiecesMachine:
    """`vraie_machine` : vrai matériel (le programme tourne sur le Pi) ; faux pour les essais avec
    un faux matériel (des réglages d'EXEMPLE y sont permis)."""

    def __init__(
        self,
        poste: PosteFut | None,
        materiel: Materiel | None,
        vraie_machine: bool,
        spray: Spray | None = None,
        nettoyage: Nettoyage | None = None,
        vision: ReglagesVision | None = None,
        regard: Regard | None = None,
        donnees: Path | None = None,
    ) -> None:
        self.poste = poste
        self.materiel = materiel
        self.vraie_machine = vraie_machine
        self.spray = spray
        self.nettoyage = nettoyage
        self.vision = vision
        self.regard = regard
        self.donnees = donnees

    def manque_inspection(self) -> str | None:
        """Ce qui empêche la caméra du micropore de servir (QR du flanc, trous, morceaux)."""
        if self.vision is None:
            return VISION_ABSENTE
        inspection = self.vision.inspection
        if inspection is None:
            return INSPECTION_ABSENTE
        # Seule la partie « inspection » compte : le haut du fichier est celui des autres caméras.
        if self.vraie_machine and inspection.exemple:
            return INSPECTION_EXEMPLE
        if self.regard is None:
            return CAMERA_ABSENTE
        return None

    def vision_inspection(
        self,
        angle_plateau: Callable[[], float | None],
        rangees: Callable[[], list[float]],
    ) -> VisionInspection:
        """La vision du micropore, avec l'angle du plateau et les rangées de trous du seau sur le
        plateau (donnés par la carte du chariot, quand elle sera branchée)."""
        assert self.vision is not None and self.regard is not None
        fichier = None if self.donnees is None else self.donnees / NOM_ECARTS
        return VisionInspection(
            self.vision, self.regard, angle_plateau, rangees, EcartsAttaches(fichier)
        )

    def manque(self, poste: str) -> str | None:
        if poste == "fut" and self.poste is None:
            return "poste du fût pas suivi (entrées/sorties pas ouvertes)"
        if poste in ("seau_vide", "couvercle"):
            return CARTES_DU_CHARIOT
        if poste == "qr_du_flanc":
            return self.manque_inspection()
        if poste == "spray" and self.spray is None:
            return CARTE_SPRAY
        if poste == "mycelium":
            return BOCAL_NEUF
        if poste == "micropore":
            return self.manque_inspection() or CARTE_DE_LA_TETE
        if poste == "stockage" and (
            self.materiel is None or BOUCLE not in self.materiel.branchements
        ):
            return f"pas de signal « {BOUCLE} » ouvert (entrées/sorties)"
        if poste == "entonnoir":
            return ENTONNOIR
        if poste == "lavage_bocaux":
            return LAVAGE_DES_BOCAUX
        if poste in ("enceinte", "ozone", "purge"):
            return self._manque_nuit(poste)
        return None

    def _manque_nuit(self, poste: str) -> str | None:
        if self.nettoyage is None or self.materiel is None:
            return NETTOYAGE_ABSENT
        if poste == "ozone":
            absents = [s for s in SIGNAUX_DE_LA_NUIT if s not in self.materiel.branchements]
            if absents:
                return f"pas de signal « {absents[0]} » ouvert (entrées/sorties)"
        if poste == "purge":
            absents = [
                nom
                for nom, capteur in (
                    ("particules_dedans", self.nettoyage.particules_dedans),
                    ("particules_dehors", self.nettoyage.particules_dehors),
                    ("pression_enceinte", self.nettoyage.capteur_pression),
                    ("consigne_ventilateur", self.nettoyage.consigne),
                )
                if capteur is None
            ]
            if absents:
                return f"capteurs de la purge absents ({', '.join(absents)})"
        return None

    def remplissage(
        self,
        lot: Lot,
        avec_micropore: bool,
        avec_fermeture: bool,
        avec_spray: bool,
        avec_couvercle: bool,
    ) -> PiecesRemplissage:
        # Jamais appelé : le poste « seau_vide » manque toujours (cartes du chariot). Avec lui, la
        # vision (`vision_inspection`) et le Spray seront branchés au chariot comme dans
        # vidange.cycle.simulation.
        raise NotImplementedError(CARTES_DU_CHARIOT)

    def entonnoir(self, lot: LotBocaux) -> PiecesEntonnoir:
        # Jamais appelé : le poste « entonnoir » manque toujours (Préhension, photo du plafond).
        raise NotImplementedError(ENTONNOIR)

    def lavage_bocaux(self) -> PiecesLavageBocaux:
        # Jamais appelé : le poste « lavage_bocaux » manque toujours.
        raise NotImplementedError(LAVAGE_DES_BOCAUX)
