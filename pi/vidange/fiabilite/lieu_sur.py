"""Retour en lieu sûr (fonction 3) : prises d'origine et positions sûres, dans l'ordre réglé.

Le module « lieu_sur » est fait des gestes de la liste « lieu_sur » de machine.yaml.
Il est **exclusif** : tant qu'il tourne, les autres modules attendent (après une coupure,
ils reprendront à leur étape, au bon seau, une fois les axes en lieu sûr). Il attend le Go
de Karulium avant son premier geste.

Après une mise sous tension, une carte FluidNC ne sait pas où sont ses axes (alarme 14) :
sa prise d'origine ($H) le lui rapprend. Une position sûre n'est demandée qu'une fois toutes
les cartes prêtes (connectées, sans alarme).

Le geste « portique: origine » fait la prise d'origine du portique dans son ordre (freins des Z
desserrés, les deux Z en haut, Y, puis X1 et X2 ensemble) ; « portique: garage » le gare
(vidange.portique). Une alarme d'un pilote du portique arrête alors le module.
"""

from collections.abc import Mapping
from dataclasses import replace

from vidange.chef import Axes, Condition, ErreurEtape, Etape, Module
from vidange.fluidnc import Commande, Liaison
from vidange.portique import Portique
from vidange.quoi_faire import ALARMES_FLUIDNC, CARTE_COUPEE
from vidange.reglages import CarteFluidnc, Machine

NOM = "lieu_sur"

QUOI_FAIRE_PRISE_ORIGINE = ALARMES_FLUIDNC[9]
QUOI_FAIRE_ALLER = (
    "Un axe n'est pas arrivé en lieu sûr : regarder ce qui le bloque et si sa carte est en "
    "alarme ; corriger, débloquer la carte, puis acquitter et donner le Go."
)


class _PriseOrigine:
    """La prise d'origine d'une carte, rejouable : chaque lancement renvoie « $H »."""

    def __init__(self, nom: str, liaison: Liaison) -> None:
        self.nom = nom
        self.liaison = liaison
        self.commande: Commande | None = None
        self.connectee = Condition(f"carte « {nom} » connectée", lambda: liaison.etat.connectee)
        self.finie = Condition(f"prise d'origine de « {nom} » finie", self._finie)

    def lancer(self) -> None:
        self.commande = self.liaison.prise_origine()
        self._finie()

    def _finie(self) -> bool:
        if self.commande is None:
            return False
        if self.commande.erreur is not None:
            quoi_faire = CARTE_COUPEE if not self.liaison.etat.connectee else ""
            raise ErreurEtape(
                f"prise d'origine de « {self.nom} » : {self.commande.erreur}",
                quoi_faire or QUOI_FAIRE_PRISE_ORIGINE,
            )
        return self.commande.finie


def module_lieu_sur(
    machine: Machine,
    liaisons: Mapping[str, Liaison],
    cartes: Mapping[str, CarteFluidnc] | None = None,
) -> Module | None:
    """Le module de retour en lieu sûr, ou None si machine.yaml n'a pas de « lieu_sur ».
    `cartes` (fluidnc.yaml → cartes) : demandées par un geste du portique."""
    if not machine.lieu_sur:
        return None
    axes = Axes(machine, liaisons)
    portique = None
    if any(geste.portique is not None for geste in machine.lieu_sur):
        if cartes is None:
            raise ValueError("lieu_sur : un geste du portique demande les cartes de fluidnc.yaml")
        portique = Portique(machine, cartes, liaisons)
    # Pendant un déplacement, toutes les cartes doivent rester connectées et sans alarme.
    arrives = Condition(axes.arrives.texte, lambda: axes.surveillance.test() and axes.arrive())
    etapes = []
    noms: set[str] = set()
    for numero, geste in enumerate(machine.lieu_sur, start=1):
        if geste.portique is not None:
            assert portique is not None
            gestes = (
                portique.etapes_origine()
                if geste.portique == "origine"
                else portique.etapes_garage()
            )
            for etape in gestes:
                nom = etape.nom if etape.nom not in noms else f"{etape.nom}_{numero}"
                noms.add(nom)
                # Le délai du geste vaut pour chacune de ses étapes qui en a un.
                delai = geste.delai if etape.delai_max is not None else None
                etapes.append(replace(etape, nom=nom, delai_max=delai, demande_go=not etapes))
            continue
        if geste.prise_origine is not None:
            nom = f"prise_origine_{geste.prise_origine}"
            prise = _PriseOrigine(geste.prise_origine, liaisons[geste.prise_origine])
            etape = dict(
                quoi_faire=QUOI_FAIRE_PRISE_ORIGINE,
                action=prise.lancer,
                fin=prise.finie,
                entree=(prise.connectee,),
            )
        else:
            position = geste.aller
            assert position is not None
            nom = f"aller_{position}"
            etape = dict(
                quoi_faire=QUOI_FAIRE_ALLER,
                action=lambda position=position: axes.aller(position),
                fin=arrives,
                entree=(axes.pretes,),
            )
        if nom in noms:
            nom = f"{nom}_{numero}"
        noms.add(nom)
        etapes.append(Etape(nom, delai_max=geste.delai, demande_go=numero == 1, **etape))
    return Module(
        nom=NOM,
        etapes=tuple(etapes),
        surveillances=() if portique is None else (portique.pas_d_alarme,),
        pauser=axes.pauser,
        reprendre=axes.reprendre,
        arreter=axes.pauser,
        exclusif=True,
    )
