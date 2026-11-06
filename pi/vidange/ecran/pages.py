"""Les pages de l'écran Nextion, telles que Karulium les monte dans Nextion Editor.

Ce fichier et nextion/pages.md disent la même chose (un test le vérifie) : le nom et le
numéro de chaque page, le nom de chaque objet et le nombre de caractères qu'il peut afficher
(« txt_maxl » dans Nextion Editor). Les positions et les tailles ne sont que dans pages.md :
le Pi n'en a pas besoin.

Le Pi décide de tout : quelle page montrer, ce qu'elle affiche et en quelle couleur. Les
boutons ne font qu'envoyer leur nom (« @go ») ; ils ne changent jamais de page eux-mêmes.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Objet:
    nom: str
    sorte: Literal["texte", "bouton"]
    # Nombre de caractères au plus (txt_maxl) : un texte plus long est coupé par le Pi.
    longueur: int


@dataclass(frozen=True)
class Page:
    nom: str
    # Numéro de la page dans Nextion Editor : les pages doivent y être créées dans cet ordre.
    numero: int
    objets: tuple[Objet, ...]

    def objet(self, nom: str) -> Objet:
        for objet in self.objets:
            if objet.nom == nom:
                return objet
        raise KeyError(f"pas d'objet « {nom} » sur la page « {self.nom} »")

    @property
    def boutons(self) -> list[str]:
        return [objet.nom for objet in self.objets if objet.sorte == "bouton"]


def _texte(nom: str, longueur: int) -> Objet:
    return Objet(nom, "texte", longueur)


def _bouton(nom: str, longueur: int) -> Objet:
    return Objet(nom, "bouton", longueur)


ETAT = Page(
    "etat",
    0,
    (
        _bouton("b_bandeau", 30),
        _texte("t_mode", 40),
        _texte("t_module", 80),
        _texte("t_attend", 40),
        _texte("t_info", 80),
        _bouton("b_pause", 10),
        _bouton("b_go", 10),
        _bouton("b_compteurs", 10),
        _bouton("b_mode", 10),
    ),
)

ALARME = Page(
    "alarme",
    1,
    (
        _texte("t_bandeau", 30),
        _texte("t_message", 80),
        _texte("t_quoi", 80),
        _texte("t_suite", 40),
        _bouton("b_retour", 10),
        _bouton("b_suite", 10),
        _bouton("b_suivante", 10),
        _bouton("b_repare", 10),
    ),
)

COMPTEURS = Page(
    "compteurs",
    2,
    (
        _texte("t_titre", 30),
        _texte("t_seaux_jour", 40),
        _texte("t_futs_jour", 40),
        _texte("t_seaux_fut", 40),
        _texte("t_alarmes_jour", 40),
        _bouton("b_retour", 10),
    ),
)

MODE = Page(
    "mode",
    3,
    (
        _texte("t_titre", 30),
        _texte("t_info", 80),
        _bouton("b_production", 10),
        _bouton("b_lavage", 10),
        _bouton("b_uv_ozone", 10),
        _bouton("b_retour", 10),
    ),
)

CONFIRMER = Page(
    "confirmer",
    4,
    (
        _texte("t_titre", 30),
        _texte("t_question", 120),
        _bouton("b_non", 10),
        _bouton("b_oui", 10),
    ),
)

POSTE_FUT = Page(
    "poste_fut",
    5,
    (
        _texte("t_titre", 30),
        _texte("t_poids", 60),
        _texte("t_gestes", 100),
        _texte("t_manque", 140),
        _bouton("b_pret", 10),
        _bouton("b_retour", 10),
    ),
)

PAGES: dict[str, Page] = {
    page.nom: page for page in (ETAT, ALARME, COMPTEURS, MODE, CONFIRMER, POSTE_FUT)
}
