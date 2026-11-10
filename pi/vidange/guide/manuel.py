"""Le manuel d'utilisation tenu à jour (fonction 85, tâche 32).

Il n'est pas écrit à la main : il est **fabriqué à partir de ce que le programme sait vraiment**
(les modes, les travaux guidés de guide.yaml, les pièces d'usure d'entretien.yaml, les « quoi
faire » des alarmes de quoi_faire.py). Quand un réglage ou un texte change, le manuel change
avec lui : un test refuse que `docs/manuel.md` ne soit plus la copie fidèle (commande :
`vidange manuel`).

Deux formes : des sections (pour la page web, onglet « Aide ») et du Markdown (pour imprimer ou
relire : `docs/manuel.md`). Les chiffres viennent des réglages, jamais d'ici.
"""

from dataclasses import dataclass

from vidange import quoi_faire
from vidange.fluidnc.protocole import ALARMES
from vidange.mode import MODES
from vidange.reglages import Reglages


@dataclass(frozen=True)
class Section:
    cle: str
    titre: str
    # Chaque ligne est un petit paragraphe, ou un point de liste (« - » ou « 1. »).
    lignes: tuple[str, ...]

    def en_dict(self) -> dict[str, object]:
        return {"cle": self.cle, "titre": self.titre, "lignes": list(self.lignes)}


# Les trois rôles de la page web (tâche 25). Texte seulement : aucun chiffre de la machine.
LIGNES_ROLES = (
    "- **Visiteur** : regarde (état, historique, photos, caméras), ne commande rien.",
    "- **Employé** : regarde et produit : Pause, Reprise, Go, lots, nettoyage, poste du fût, "
    "carnet de bord, acquitter une alarme, et suivre un travail guidé (onglet « Aide » ou page "
    "« guide » de l'écran).",
    "- **Karulium** : tout, y compris les réglages, les mises à jour, la maintenance (bouton "
    "« Fait ») et le pilotage à distance.",
)

LIGNES_SECURITE = (
    "La sécurité des personnes est câblée : arrêt d'urgence, portes, fins de course de sécurité, "
    "freins. Le logiciel (et ce guide) ne la remplace pas. En cas de doute, appuyer sur l'arrêt "
    "d'urgence, puis demander à Karulium.",
    "Le guide ne fait bouger aucun axe : il explique, la personne fait les gestes à la main, "
    "machine à l'arrêt, puis dit « Fait ».",
)


def _section_travaux(reglages: Reglages) -> Section:
    lignes: list[str] = []
    for nom, travail in reglages.guide.travaux.items():
        exemple = (
            " (exemple à relire sur place)" if travail.exemple or reglages.guide.exemple else ""
        )
        lignes.append(f"**{travail.titre}** (`{nom}`){exemple}. Quand : {travail.quand}")
        for numero, etape in enumerate(travail.etapes, start=1):
            suite = f" (la machine regarde : `{etape.signal}`)" if etape.signal else ""
            lignes.append(f"{numero}. {etape.texte}{suite}")
    return Section("travaux", "Les travaux guidés", tuple(lignes))


def _section_entretien(reglages: Reglages) -> Section:
    lignes = []
    for nom, piece in reglages.entretien.pieces.items():
        exemple = " (limite d'exemple)" if piece.exemple or reglages.entretien.exemple else ""
        lignes.append(
            f"- **{piece.description}** (`{nom}`) : tous les {piece.limite:g} "
            f"({piece.compteur.genre}){exemple}. À faire : {piece.a_faire}"
        )
    return Section("entretien", "L'entretien", tuple(lignes))


def _section_alarmes() -> Section:
    lignes = ["Chaque alarme dit ce qui s'est passé et quoi faire ; en voici le catalogue."]
    for numero, quoi in quoi_faire.ALARMES_FLUIDNC.items():
        lignes.append(
            f"- **Alarme {numero} d'une carte, {ALARMES.get(numero, 'inconnue')}** : {quoi}"
        )
    autres = (
        ("Carte coupée", quoi_faire.CARTE_COUPEE),
        ("Carte redémarrée", quoi_faire.CARTE_REDEMARREE),
        ("Ordre refusé par une carte", quoi_faire.LIGNE_REFUSEE),
        ("Capteur muet", quoi_faire.CAPTEUR_MUET),
        ("Erreur imprévue du programme", quoi_faire.ERREUR_PROGRAMME),
        ("Reprise après coupure de courant", quoi_faire.COUPURE_COURANT),
        ("Reprise après plantage du programme", quoi_faire.PLANTAGE),
    )
    lignes += [f"- **{titre}** : {quoi}" for titre, quoi in autres]
    return Section("alarmes", "Les alarmes : quoi faire", tuple(lignes))


def sections(reglages: Reglages) -> list[Section]:
    """Toutes les sections du manuel, dans l'ordre de lecture."""
    modes = tuple(f"- **{libelle}** (`{cle}`)" for cle, libelle in MODES.items())
    return [
        Section("securite", "Avant tout : la sécurité", LIGNES_SECURITE),
        Section("roles", "Qui peut faire quoi", LIGNES_ROLES),
        Section(
            "modes",
            "Les modes de la machine",
            (
                "On change de mode machine au repos, depuis l'écran (page « mode », avec le code) "
                "ou la page web.",
                *modes,
            ),
        ),
        _section_travaux(reglages),
        _section_entretien(reglages),
        _section_alarmes(),
    ]


def en_markdown(reglages: Reglages) -> str:
    """Le manuel en Markdown : la copie qu'on garde dans docs/manuel.md et qu'on peut imprimer."""
    morceaux = [
        "# Manuel d'utilisation",
        "",
        "*Fichier fabriqué par `vidange manuel` à partir des réglages et des textes du programme : "
        "ne pas le modifier à la main (un test vérifie qu'il est à jour).*",
        "",
    ]
    for section in sections(reglages):
        morceaux += [f"## {section.titre}", ""]
        apres_liste = False
        for ligne in section.lignes:
            liste = ligne.startswith("- ") or ligne[:1].isdigit()
            if apres_liste and not liste:
                morceaux.append("")
            morceaux.append(ligne)
            if not liste:
                morceaux.append("")
            apres_liste = liste
        if apres_liste:
            morceaux.append("")
    return "\n".join(morceaux).rstrip() + "\n"
