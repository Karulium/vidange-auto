"""Les signaux du lavage, chacun sur la carte FluidNC où fluidnc.yaml le met (n° 3 ou n° 4).

    signaux = signaux_lavage(liaisons, reglages.fluidnc, materiel)
    signaux.entree("flotteur_lavage")
    signaux.sortie("pompe_lavage", True)

Le code ne connaît que les noms : le plan de câblage peut changer un signal de carte (FluidNC n'a
que 8 sorties « digital » par carte) en ne touchant qu'à fluidnc.yaml.

Le chauffage (`relais_chauffage_lavage`) n'est sur aucune carte FluidNC : c'est un relais du Pi
(docs/entrees-sorties.yaml). Sa sécurité (flotteur bas : plus de commande du SSR) est câblée.
"""

from collections.abc import Mapping
from typing import Protocol

from vidange.chef import ErreurEtape
from vidange.fluidnc import Liaison
from vidange.porte_bocal.signaux import SignauxFluidnc
from vidange.reglages import ENTREES_LAVAGE, RELAIS_CHAUFFAGE_LAVAGE, SORTIES_LAVAGE, Fluidnc


class RelaisDuPi(Protocol):
    def ecrire(self, nom: str, commande: bool) -> None: ...


class SignauxRepartis:
    def __init__(
        self, par_nom: Mapping[str, SignauxFluidnc], materiel: RelaisDuPi | None = None
    ) -> None:
        self._par_nom = dict(par_nom)
        self._materiel = materiel

    def entree(self, nom: str) -> bool | None:
        return self._par_nom[nom].entree(nom)

    def sortie(self, nom: str, actif: bool) -> None:
        if nom == RELAIS_CHAUFFAGE_LAVAGE:
            # Relais du Pi : True = commandé (le SSR a sa commande, si le flotteur câblé le permet).
            if self._materiel is None:
                raise ErreurEtape(
                    f"lavage : relais du chauffage « {nom} » pas relié au Pi",
                    "Le programme n'a pas la carte des relais du Pi : regarder la liste des "
                    "entrées-sorties et le journal.",
                )
            self._materiel.ecrire(nom, actif)
            return
        self._par_nom[nom].sortie(nom, actif)


def signaux_lavage(
    liaisons: Mapping[str, Liaison], fluidnc: Fluidnc, materiel: RelaisDuPi | None = None
) -> SignauxRepartis:
    """Erreur claire si un signal du lavage n'est sur aucune carte reliée."""
    par_nom = {}
    for quoi, noms in (("entrees", ENTREES_LAVAGE), ("sorties", SORTIES_LAVAGE)):
        for nom in noms:
            cartes = [carte for carte, r in fluidnc.cartes.items() if nom in getattr(r, quoi)]
            if len(cartes) != 1 or cartes[0] not in liaisons:
                raise ValueError(
                    f"fluidnc.yaml : « {nom} » (lavage) doit être dans les {quoi} d'une seule "
                    f"carte reliée (trouvé : {', '.join(cartes) or 'aucune'})"
                )
            carte = cartes[0]
            entrees, sorties = ((nom,), ()) if quoi == "entrees" else ((), (nom,))
            par_nom[nom] = SignauxFluidnc(liaisons[carte], fluidnc.cartes[carte], entrees, sorties)
    return SignauxRepartis(par_nom, materiel)
