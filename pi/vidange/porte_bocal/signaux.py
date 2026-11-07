"""Entrées et sorties tout-ou-rien d'une carte FluidNC, par leur nom.

    signaux = SignauxFluidnc(liaison, reglages.fluidnc.cartes["mycelium_lavage"])
    signaux.entree("verrou_plateau_engage")             # True, False, ou None (carte pas lue)
    signaux.sortie("electroaimant_verrou_plateau", True)

Les entrées arrivent avec l'état de la carte (« Pn: », lu toutes les periode_etat_s) ; les
sorties sont les « user_outputs » de FluidNC (M64 P<n> allume, M65 P<n> éteint, tout de suite).
Le nom de chaque signal (docs/entrees-sorties.yaml) donne sa lettre ou son numéro dans
fluidnc.yaml ; le code ne connaît que les noms.
"""

from collections.abc import Callable, Iterable
from typing import Protocol

from vidange.chef import ErreurEtape
from vidange.fluidnc import Liaison
from vidange.journal import donner_journal
from vidange.reglages import CarteFluidnc

journal = donner_journal("porte_bocal.signaux")


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


class DeuxSortiesExclusives:
    """Deux sorties qui ne sont jamais actives ensemble (les deux vannes de la ventouse, les deux
    sens du pont en H du demi-tour).

    `commander(nom, actif)` envoie l'ordre. Une sortie est comptée active dès qu'on demande de
    l'allumer, et jusqu'à ce que son extinction soit acceptée : si l'ordre d'extinction échoue,
    elle reste comptée active (prudence) et l'autre est refusée. Le refus (ErreurEtape, avec un
    « quoi faire ») protège la machine, jamais les personnes : la sécurité est câblée."""

    def __init__(
        self,
        commander: Callable[[str, bool], None],
        noms: tuple[str, str],
        refus: str,
        quoi_faire: str,
    ) -> None:
        """`refus` : phrase avec {nom} et {autre} ; `quoi_faire` : ce que Karulium doit faire."""
        self._commander = commander
        self._noms = noms
        self._refus = refus
        self._quoi_faire = quoi_faire
        self.ouvertes: set[str] = set()

    def commander(self, nom: str, actif: bool) -> None:
        if not actif:
            self._commander(nom, False)
            self.ouvertes.discard(nom)
            return
        autre = self._noms[1] if nom == self._noms[0] else self._noms[0]
        if autre in self.ouvertes:
            journal.error("« %s » pas allumée, « %s » est allumée", nom, autre)
            raise ErreurEtape(self._refus.format(nom=nom, autre=autre), self._quoi_faire)
        self.ouvertes.add(nom)
        self._commander(nom, True)
