"""Les pièces du mode seaux sur la machine (programme principal, tâche 45).

Ce qui manque aujourd'hui pour qu'un lot parte sur la machine est dit poste par poste (check-list,
écran, journal), sans rien inventer :
- seau vide : les cartes du chariot et de la tête (ChariotFluidnc, TeteFluidnc) seront construites
  ici avec la lecture du QR du flanc ;
- QR du flanc : il est lu par la caméra du micropore pendant que le plateau tourne le seau (fil
  Guidage caméra, 07/11/2026) ; cette lecture est dans la vision du micropore (tâche 40 ter), pas
  encore écrite : sans elle, le Remplissage refuse d'orienter l'anse ;
- spray : la carte du spray doit être ouverte (signal de docs/entrees-sorties.yaml) ;
- mycélium : la pose du bocal de semence neuf dans le porte-bocal par la préhension n'est pas écrite
  (case vide `nouveau_bocal` du Mycélium) ;
- micropore : la vision de sa caméra n'est pas écrite (tâche 40 ter) ;
- stockage : il faut le signal de la boucle du tiroir et des panneaux.
Les cases vides d'ORDRE_SEAU (griffe, couvercle, lavage) sont dites par le mode lui-même.
"""

from vidange.cycle.mode_seaux import Lot, PiecesRemplissage
from vidange.materiel import Materiel
from vidange.poste_fut import PosteFut
from vidange.spray.spray import Spray
from vidange.stockage.simulation import BOUCLE

QR_DU_FLANC = (
    "lecture du QR du flanc par la caméra du micropore pas écrite (tâche 40 ter) : le Remplissage "
    "ne peut pas orienter l'anse"
)
CARTES_DU_CHARIOT = (
    "cartes du chariot et de la tête pas encore branchées au mode seaux (avec la lecture du QR "
    "du flanc, tâche 40 ter)"
)
CARTE_SPRAY = "carte du spray pas ouverte (signal absent de docs/entrees-sorties.yaml ?)"
BOCAL_NEUF = (
    "pose du bocal de semence neuf dans le porte-bocal par la préhension pas écrite (case vide "
    "« nouveau_bocal » du Mycélium)"
)
VISION_MICROPORE = "vision de la caméra du micropore pas écrite (tâche 40 ter)"


class PiecesMachine:
    """`vraie_machine` : vrai matériel (le programme tourne sur le Pi) ; faux pour les essais avec
    un faux matériel (des réglages d'EXEMPLE y sont permis)."""

    def __init__(
        self,
        poste: PosteFut | None,
        materiel: Materiel | None,
        vraie_machine: bool,
        spray: Spray | None = None,
    ) -> None:
        self.poste = poste
        self.materiel = materiel
        self.vraie_machine = vraie_machine
        self.spray = spray

    def manque(self, poste: str) -> str | None:
        if poste == "fut" and self.poste is None:
            return "poste du fût pas suivi (entrées/sorties pas ouvertes)"
        if poste == "seau_vide":
            return CARTES_DU_CHARIOT
        if poste == "qr_du_flanc":
            return QR_DU_FLANC
        if poste == "spray" and self.spray is None:
            return CARTE_SPRAY
        if poste == "mycelium":
            return BOCAL_NEUF
        if poste == "micropore":
            return VISION_MICROPORE
        if poste == "stockage" and (
            self.materiel is None or BOUCLE not in self.materiel.branchements
        ):
            return f"pas de signal « {BOUCLE} » ouvert (entrées/sorties)"
        return None

    def remplissage(
        self, lot: Lot, avec_micropore: bool, avec_fermeture: bool, avec_spray: bool
    ) -> PiecesRemplissage:
        # Jamais appelé : les postes « seau_vide » et « qr_du_flanc » manquent toujours. Avec
        # eux, le Spray sera branché au chariot comme dans vidange.cycle.simulation.
        raise NotImplementedError(QR_DU_FLANC)
