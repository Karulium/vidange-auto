"""Lavage des bocaux et des capsules au lave-bocal (tâche 21 bis).

    bocaux = LavageBocaux(lavage)
    lavage.confirmer_lave_bocal(True)       # l'écran : Karulium l'a posé
    prehension.lancer(bocaux.geste_laver)   # la tête tient un bocal vide retourné ou une capsule

Le lave-bocal (un rince-verre de bar) est posé à la main sur l'anneau de rive du fût de lavage
avant la série, et enlevé après. La tête appuie le bocal retourné (ou la capsule, tenue par les
aimants) sur son plateau, qui projette de l'eau tant qu'on appuie. Pas d'électrovanne (vanne
quart de tour manuelle au robinet) : le Pi ne fait que la position, l'appui et la durée, puis
l'égouttage au-dessus du fût. La vidange automatique évacue l'eau (fin de série).

Le Pi ne sait pas si le lave-bocal est posé : l'écran demande de le confirmer avant une série de
bocaux (`Lavage.confirmer_lave_bocal`). Bocaux et seaux ne se lavent jamais en même temps.
"""

from vidange.chef import ErreurEtape
from vidange.journal import donner_journal
from vidange.lavage.lavage import QUOI_FAIRE, QUOI_FAIRE_LAVE_BOCAL, QUOI_FAIRE_PANNEAU, Lavage
from vidange.prehension.prehension import Geste
from vidange.prehension.tete import Pas
from vidange.reglages import OBJETS_LAVE_BOCAL

journal = donner_journal("lavage.bocaux")

QUOI_FAIRE_APPUI = (
    "L'appui sur le plateau du lave-bocal n'est pas venu : regarder la vidéo (lave-bocal posé, à "
    "sa place ? bocal bien tenu ?). Corriger, puis acquitter et donner le Go."
)


def _m(valeur: float) -> str:
    return f"{valeur:.3f}".rstrip("0").rstrip(".").replace(".", ",")


class LavageBocaux:
    def __init__(self, lavage: Lavage) -> None:
        assert lavage.reglages.lave_bocal is not None
        self.reglages = lavage.reglages.lave_bocal
        self.lavage = lavage
        self.prehension = lavage.prehension
        self.laves = 0

    def refus_mode(self) -> str | None:
        return self.lavage.refus_mode() or self.lavage.refus_fut("bocaux")

    def mode_permis(self) -> bool:
        return self.refus_mode() is None

    def geste_laver(self) -> Geste:
        """Appuyer l'objet tenu (bocal vide retourné, capsule) sur le plateau du lave-bocal,
        le temps du rinçage, puis l'égoutter au-dessus du fût."""
        r = self.reglages
        p = self.prehension
        objet = p.objet
        if objet is None or objet.sorte not in OBJETS_LAVE_BOCAL:
            raise ErreurEtape("lave-bocal : la tête ne tient ni bocal vide ni capsule", QUOI_FAIRE)
        refus = self.refus_mode()
        if refus is not None:
            quoi_faire = QUOI_FAIRE_LAVE_BOCAL if "lave-bocal" in refus else QUOI_FAIRE_PANNEAU
            raise ErreurEtape(f"lave-bocal refusé : {refus}", quoi_faire)
        journal.info("Lavage d'un(e) %s au lave-bocal", objet.sorte)
        yield from p.aller(*r.centre)
        appui_z = r.plateau_z + objet.dessous_m
        yield Pas("descendre au-dessus du lave-bocal", {"z": appui_z + r.approche_m})
        resultat = yield Pas(
            "appui sur le plateau du lave-bocal",
            {"z": appui_z - r.course_appui_m},
            vitesse="approche",
            appui_arret_n=r.appui_n,
        )
        assert resultat is not None and p.pose is not None
        if resultat.arret != "appui":
            raise ErreurEtape(
                f"lave-bocal : appui de {r.appui_n:g} N pas atteint (face descendue à "
                f"{_m(p.pose.z)} m)",
                QUOI_FAIRE_APPUI,
            )
        yield Pas("rinçage au lave-bocal", attente_s=r.duree_s)
        yield from p.monter()
        yield Pas("égoutter au-dessus du fût", attente_s=r.egouttage_s)
        self.laves += 1
        journal.info("Lavage : %s lavé(e) au lave-bocal", objet.sorte)
