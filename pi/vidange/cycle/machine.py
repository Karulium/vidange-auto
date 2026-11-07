"""Les pièces du mode seaux sur la machine (programme principal, tâche 45).

Ce qui manque aujourd'hui pour qu'un lot parte sur la machine est dit poste par poste (check-list,
écran, journal), sans rien inventer :
- seau vide : la lecture du QR du flanc du seau par une caméra (angle de l'anse) n'est pas écrite :
  sans elle, le Remplissage refuse d'orienter l'anse. Les cartes du chariot et de la tête
  (ChariotFluidnc, TeteFluidnc) seront construites ici avec elle ;
- mycélium : la pose du bocal de semence neuf dans le porte-bocal par la préhension n'est pas écrite
  (case vide `nouveau_bocal` du Mycélium) ;
- micropore : la vision de sa caméra n'est pas écrite (tâche 40 ter) ;
- stockage : il faut le signal de la boucle du tiroir et des panneaux.
Les cases vides d'ORDRE_SEAU (griffe, spray, couvercle, lavage) sont dites par le mode lui-même.
"""

from vidange.cycle.mode_seaux import Lot, PiecesRemplissage
from vidange.materiel import Materiel
from vidange.poste_fut import PosteFut
from vidange.stockage.simulation import BOUCLE

QR_DU_FLANC = (
    "lecture du QR du flanc du seau (angle de l'anse) par une caméra pas écrite : le Remplissage "
    "ne peut pas orienter l'anse"
)
BOCAL_NEUF = (
    "pose du bocal de semence neuf dans le porte-bocal par la préhension pas écrite (case vide "
    "« nouveau_bocal » du Mycélium)"
)
VISION_MICROPORE = "vision de la caméra du micropore pas écrite (tâche 40 ter)"


class PiecesMachine:
    """`vraie_machine` : vrai matériel (le programme tourne sur le Pi) ; faux pour les essais avec
    un faux matériel (des réglages d'EXEMPLE y sont permis)."""

    def __init__(
        self, poste: PosteFut | None, materiel: Materiel | None, vraie_machine: bool
    ) -> None:
        self.poste = poste
        self.materiel = materiel
        self.vraie_machine = vraie_machine

    def manque(self, poste: str) -> str | None:
        if poste == "fut" and self.poste is None:
            return "poste du fût pas suivi (entrées/sorties pas ouvertes)"
        if poste == "seau_vide":
            return QR_DU_FLANC
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
        self, lot: Lot, avec_micropore: bool, avec_fermeture: bool
    ) -> PiecesRemplissage:
        # Jamais appelé : le poste « seau_vide » manque toujours (voir QR_DU_FLANC).
        raise NotImplementedError(QR_DU_FLANC)
