"""Ce que guide.yaml cite doit exister (tâche 32) : les signaux, et la place sur l'écran."""

from vidange.entrees_sorties import ENTREES, EntreesSorties
from vidange.reglages import ReglagesGuide


def verifier_avec_liste(reglages: ReglagesGuide, liste: EntreesSorties) -> list[str]:
    """Un signal cité par une étape est une entrée de docs/entrees-sorties.yaml ; les textes
    tiennent dans la page « guide » de l'écran. Rend les erreurs, en français."""
    from vidange.ecran.pages import PAGES

    erreurs = []
    page = PAGES["guide"]
    for objet, limite, nom in (
        ("t_texte", reglages.texte_max, "texte_max"),
        ("t_titre", reglages.titre_max, "titre_max"),
    ):
        place = page.objet(objet).longueur
        if limite > place:
            erreurs.append(
                f"guide.yaml, {nom} ({limite}) : plus long que l'objet « {objet} » de la page "
                f"« guide » de l'écran ({place} signes, nextion/pages.md)"
            )
    entrees = {nom for nom, signal in liste.signaux.items() if signal.type in ENTREES}
    for nom, travail in reglages.travaux.items():
        for numero, etape in enumerate(travail.etapes, start=1):
            if etape.signal is not None and etape.signal not in entrees:
                erreurs.append(
                    f"guide.yaml, travaux → {nom} → étape {numero} → signal : « {etape.signal} » "
                    "n'est pas une entrée (contact, pnp, npn, mesure) de docs/entrees-sorties.yaml"
                )
    return erreurs
