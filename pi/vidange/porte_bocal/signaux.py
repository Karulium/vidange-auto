"""Entrées et sorties tout-ou-rien d'une carte FluidNC, par leur nom.

    signaux = SignauxFluidnc(liaison, reglages.fluidnc.cartes["mycelium_lavage"])
    signaux.entree("verrou_plateau_engage")             # True, False, ou None (carte pas lue)
    signaux.sortie("electroaimant_verrou_plateau", True)

Les entrées arrivent avec l'état de la carte (« Pn: », lu toutes les periode_etat_s) ; les
sorties sont les « user_outputs » de FluidNC (M64 P<n> allume, M65 P<n> éteint, tout de suite).
Le nom de chaque signal (docs/entrees-sorties.yaml) donne sa lettre ou son numéro dans
fluidnc.yaml ; le code ne connaît que les noms.
"""

from collections.abc import Iterable
from typing import Protocol

from vidange.chef import ErreurEtape
from vidange.fluidnc import Liaison
from vidange.reglages import CarteFluidnc


class Signaux(Protocol):
    def entree(self, nom: str) -> bool | None:
        """Vrai si l'entrée est actionnée ; None si la carte n'est pas lue."""
        ...

    def sortie(self, nom: str, actif: bool) -> None: ...


class SignauxFluidnc:
    def __init__(
        self,
        liaison: Liaison,
        carte: CarteFluidnc,
        entrees: Iterable[str] = (),
        sorties: Iterable[str] = (),
    ) -> None:
        """`entrees`, `sorties` : les noms dont on aura besoin (vérifiés tout de suite)."""
        manquent = [f"entrees → {nom}" for nom in entrees if nom not in carte.entrees]
        manquent += [f"sorties → {nom}" for nom in sorties if nom not in carte.sorties]
        if manquent:
            raise ValueError(
                f"fluidnc.yaml, carte « {liaison.nom} » : il manque {', '.join(manquent)}"
            )
        self.liaison = liaison
        self.carte = carte

    def entree(self, nom: str) -> bool | None:
        etat = self.liaison.etat
        if not etat.connectee or etat.etat is None:
            return None
        return self.carte.entrees[nom] in etat.entrees_actives

    def sortie(self, nom: str, actif: bool) -> None:
        commande = self.liaison.envoyer(f"M{64 if actif else 65} P{self.carte.sorties[nom]}")
        if commande.finie and commande.erreur is not None:
            raise ErreurEtape(
                f"sortie « {nom} » de la carte « {self.liaison.nom} » : {commande.erreur}"
            )
