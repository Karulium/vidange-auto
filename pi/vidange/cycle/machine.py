"""Les pièces du mode seaux sur la machine (programme principal, tâche 45).

Ce qui manque aujourd'hui pour qu'un lot parte sur la machine est dit poste par poste (check-list,
écran, journal), sans rien inventer :
- seau vide et couvercle : les cartes du chariot et de la tête (ChariotFluidnc, TeteFluidnc) seront
  construites ici avec la lecture du QR du flanc ; le couvercle (vidange.couvercle, tâche 41 bis)
  sera construit avec elles, sur la même tête ;
- QR du flanc : il est lu par la caméra du micropore pendant que le plateau tourne le seau (fil
  Guidage caméra, 07/11/2026) ; cette lecture est dans la vision du micropore (tâche 40 ter), pas
  encore écrite : sans elle, le Remplissage refuse d'orienter l'anse ;
- spray : la carte du spray doit être ouverte (signal de docs/entrees-sorties.yaml) ;
- mycélium : la pose du bocal de semence neuf dans le porte-bocal par la préhension n'est pas écrite
  (case vide `nouveau_bocal` du Mycélium) ;
- micropore : la vision de sa caméra n'est pas écrite (tâche 40 ter) ;
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
    ) -> None:
        self.poste = poste
        self.materiel = materiel
        self.vraie_machine = vraie_machine
        self.spray = spray
        self.nettoyage = nettoyage

    def manque(self, poste: str) -> str | None:
        if poste == "fut" and self.poste is None:
            return "poste du fût pas suivi (entrées/sorties pas ouvertes)"
        if poste in ("seau_vide", "couvercle"):
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
        # Jamais appelé : les postes « seau_vide » et « qr_du_flanc » manquent toujours. Avec
        # eux, le Spray sera branché au chariot comme dans vidange.cycle.simulation.
        raise NotImplementedError(QR_DU_FLANC)

    def entonnoir(self, lot: LotBocaux) -> PiecesEntonnoir:
        # Jamais appelé : le poste « entonnoir » manque toujours (Préhension, photo du plafond).
        raise NotImplementedError(ENTONNOIR)

    def lavage_bocaux(self) -> PiecesLavageBocaux:
        # Jamais appelé : le poste « lavage_bocaux » manque toujours.
        raise NotImplementedError(LAVAGE_DES_BOCAUX)
