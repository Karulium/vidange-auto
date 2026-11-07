"""Le module « entonnoir » du chef : un lot de bocaux remplis l'un après l'autre.

    module_entonnoir(entonnoir, prehension, bocaux, verser=..., versement_fini=..., air=...)

    demander_la_pose        Go de Karulium : il pose l'entonnoir sur le premier bocal (geste 1)
    controler_la_camera     la caméra voit l'entonnoir sur ce bocal (geste 2)
    verser                  la griffe verse, seulement dans le bocal noté entonnoir_place (3, 12)
    lire_le_col_suivant     le centre du col du bocal suivant (geste 4)
    prendre_l_entonnoir     la Préhension le prend par l'oreille (gestes 5 à 8)
    poser_sur_le_bocal      transport, pose, contrôle, lâcher (gestes 8 à 11)
    enlever_a_la_main       Go de Karulium : il l'enlève avant de fermer les bocaux (geste 13)

Les gestes se répètent (verser, lire, prendre, poser) jusqu'au dernier bocal. Quand l'entonnoir
est perdu (absent, introuvable, vide perdu), son étape part en alarme ; après « acquitter » et le
Go, elle ne fait plus rien et le module revient à `demander_la_pose` : le geste 1 recommence, sur
le bocal à remplir. Le versement est le geste de la griffe (`versement` : vidange.griffe.versement,
tâche 43 bis) ; sans lui, `verser(bocal)` et `versement_fini()` (un faux dans le simulateur).
Refait après une alarme, le versement d'un bocal commencé CONTINUE (jamais une 2e dose).
`photo` : les étapes du Portique qui garent le pont pour la photo du plafond
(`portique.etapes_photo("stockage")`), placées avant chaque lecture de la caméra.
"""

from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from vidange.chef import Condition, ErreurEtape, Etape, Module
from vidange.entonnoir.entonnoir import (
    QUOI_FAIRE_DEMANDE,
    QUOI_FAIRE_ENLEVER,
    Entonnoir,
)
from vidange.prehension.prehension import Prehension

DELAI_GESTE = "prehension_geste_max"
DELAI_VERSEMENT = "entonnoir_versement_max"

QUOI_FAIRE = (
    "Regarder la vidéo de la préhension et la photo du plafond : où est l'entonnoir ? Corriger à "
    "la main si besoin, puis acquitter et donner le Go : l'étape est refaite."
)
QUOI_FAIRE_VERSER = (
    "Le versement dans le bocal ne s'est pas passé comme prévu : regarder la vidéo de la griffe. "
    "Corriger, puis acquitter et donner le Go."
)


class VersementDuBocal(Protocol):
    """Le versement de la griffe (vidange.griffe.versement.Versement)."""

    # Conditions avant de verser (cartes prêtes, poste du fût prêt...).
    entree: tuple[Condition, ...]

    def verser(self, bocal: str) -> object: ...

    def fini(self) -> bool: ...

    def commence(self, bocal: str) -> bool:
        """Le versement de ce bocal a déjà commencé : le refaire, c'est le continuer."""
        ...

    def pauser(self) -> None: ...

    def reprendre(self) -> None: ...

    def arreter(self) -> None: ...


def module_entonnoir(
    entonnoir: Entonnoir,
    prehension: Prehension,
    bocaux: list[str],
    verser: Callable[[str], object] = lambda bocal: None,
    versement_fini: Callable[[], bool] = lambda: True,
    air: Condition | None = None,
    photo: tuple[Etape, ...] = (),
    versement: VersementDuBocal | None = None,
) -> Module:
    entonnoir.demarrer_lot(bocaux)
    if versement is not None:
        verser, versement_fini = versement.verser, versement.fini
    tete = prehension.tete
    fin_geste = Condition("geste de la préhension fini", prehension.geste_fini)

    def a_redemander() -> str | None:
        return None if entonnoir.connue() else "demander_la_pose"

    def verser_ici() -> None:
        bocal = entonnoir.place
        if versement is not None and versement.commence(bocal):
            # Refait après une alarme ou une coupure : le même versement continue.
            versement.verser(bocal)
            return
        refus = entonnoir.refus_versement(bocal)
        if refus is not None:
            raise ErreurEtape(f"entonnoir : {refus}", QUOI_FAIRE_VERSER)
        entonnoir.noter_verse(bocal)
        verser(bocal)

    def prendre() -> None:
        if entonnoir.connue() and not entonnoir.tenu:
            prehension.lancer(lambda: entonnoir.geste_prendre(prehension))

    def poser() -> None:
        if entonnoir.tenu:
            assert entonnoir.prochain is not None
            bocal, centre = entonnoir.prochain, entonnoir.centre
            prehension.lancer(lambda: entonnoir.geste_poser(prehension, bocal, centre))

    def apres_pose() -> str | None:
        if not entonnoir.connue():
            return "demander_la_pose"
        return debut_col if entonnoir.pose_ratee else "verser"

    photo_col = tuple(replace(etape, nom=f"{etape.nom}_col") for etape in photo)
    debut_col = photo_col[0].nom if photo_col else "lire_le_col_suivant"

    etapes = (
        Etape(
            "demander_la_pose",
            QUOI_FAIRE_DEMANDE,
            action=entonnoir.demander_la_pose,
            demande_go=True,
        ),
        *photo,
        Etape(
            "controler_la_camera",
            QUOI_FAIRE,
            action=entonnoir.controler_la_camera,
            ensuite=a_redemander,
        ),
        Etape(
            "verser",
            QUOI_FAIRE_VERSER,
            action=verser_ici,
            fin=Condition("versement de la griffe fini", versement_fini),
            delai_max=DELAI_VERSEMENT,
            entree=(entonnoir.verse_permis, *(versement.entree if versement else ())),
        ),
        *photo_col,
        Etape(
            "lire_le_col_suivant",
            QUOI_FAIRE,
            action=entonnoir.passer_au_suivant,
            ensuite=lambda: None if entonnoir.prochain is not None else "enlever_a_la_main",
        ),
        Etape(
            "prendre_l_entonnoir",
            QUOI_FAIRE,
            action=prendre,
            fin=fin_geste,
            delai_max=DELAI_GESTE,
            entree=(tete.pretes, air) if air is not None else (tete.pretes,),
            ensuite=a_redemander,
        ),
        Etape(
            "poser_sur_le_bocal",
            QUOI_FAIRE,
            action=poser,
            fin=fin_geste,
            delai_max=DELAI_GESTE,
            entree=(tete.pretes,),
            ensuite=apres_pose,
        ),
        Etape(
            "enlever_a_la_main",
            QUOI_FAIRE_ENLEVER,
            action=entonnoir.enlever_a_la_main,
            demande_go=True,
        ),
    )

    def pauser() -> None:
        prehension.pauser()
        if versement is not None:
            versement.pauser()

    def reprendre() -> None:
        prehension.reprendre()
        if versement is not None:
            versement.reprendre()

    def arreter() -> None:
        prehension.arreter()
        if versement is not None:
            versement.arreter()

    return Module(
        nom="entonnoir",
        etapes=etapes,
        surveillances=(tete.surveillance,),
        pauser=pauser,
        reprendre=reprendre,
        arreter=arreter,
    )
