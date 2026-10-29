"""Ce que pesees.yaml et entrees-sorties.yaml disent des cartes de pesée doit aller ensemble.

Lu aussi par la fabrication du programme des cartes (entete.py), où seuls pydantic et PyYAML
sont installés : n'importer ici que les réglages et la liste des entrées/sorties.
"""

from vidange.entrees_sorties import CARTE_PESEE, EntreesSorties, LiaisonUsbSerie
from vidange.reglages import ReglagesPesees

# Octets d'une question (lecture de registres) et de sa réponse, 10 bits par octet.
OCTETS_ECHANGE = 8 + 5 + 2 * 8  # 8 registres (vidange.materiel.carte_pesee)
VITESSES_RP2040_MAX = 921600


def cartes_de_pesee(liste: EntreesSorties) -> dict[str, int]:
    """Les signaux de pesée du bus RS485 → leur adresse sur le bus."""
    return {
        nom: signal.adresse
        for nom, signal in liste.signaux.items()
        if signal.appareil == CARTE_PESEE and signal.adresse is not None
    }


def verifier_avec_liste(reglages: ReglagesPesees, liste: EntreesSorties) -> list[str]:
    """Ce que pesees.yaml et entrees-sorties.yaml disent des cartes doit aller ensemble."""
    erreurs = []
    cartes = cartes_de_pesee(liste)
    for nom in reglages.etalonnage:
        if nom not in cartes:
            erreurs.append(
                f"pesees.yaml : « {nom} » n'est pas une carte de pesée de entrees-sorties.yaml "
                "(signal avec « appareil: carte_pesee »)"
            )
    for nom in cartes:
        if nom not in reglages.etalonnage:
            erreurs.append(
                f"entrees-sorties.yaml : la carte de pesée « {nom} » n'est pas dans pesees.yaml "
                "(tour et etalonnage)"
            )
    bus = {liste.signaux[nom].carte for nom in cartes}
    if len(bus) > 1:
        erreurs.append(
            "entrees-sorties.yaml : les cartes de pesée doivent être sur un seul bus "
            f"(elles sont sur {', '.join(sorted(bus))})"
        )
    for nom_bus in bus:
        liaison = liste.cartes[nom_bus].liaison
        if not isinstance(liaison, LiaisonUsbSerie):
            erreurs.append(
                f"entrees-sorties.yaml, carte « {nom_bus} » : le bus des pesées doit être un "
                "adaptateur USB-RS485 (liaison usb_serie)"
            )
            continue
        if liaison.vitesse_bauds > VITESSES_RP2040_MAX:
            erreurs.append(
                f"entrees-sorties.yaml, carte « {nom_bus} » : {liaison.vitesse_bauds} bauds, "
                f"c'est trop pour les cartes de pesée (au plus {VITESSES_RP2040_MAX})"
            )
        echange_s = (
            OCTETS_ECHANGE * 10 / liaison.vitesse_bauds
            + reglages.programme.delai_avant_reponse_us / 1e6
        )
        if liaison.delai_reponse_s < 2 * echange_s:
            erreurs.append(
                f"entrees-sorties.yaml, carte « {nom_bus} » : delai_reponse_s "
                f"({liaison.delai_reponse_s} s) doit valoir au moins {2 * echange_s:.4f} s "
                "(deux fois le temps d'une question et de sa réponse)"
            )
    return erreurs
