"""Écrit les réglages des 2 ESP32-C3 du poste du fût pour leurs programmes (en C, dossier
poste_fut_radio/, tâche 17 ter).

Lancé par CMake quand on fabrique un des deux programmes (`poste_fut_radio/reglages.cmake`) :

    python -m vidange.pesees.entete_radio <pesees.yaml> <entrees-sorties.yaml> <dossier de sortie>

Les deux fichiers sont vérifiés comme au démarrage du Pi ; une erreur arrête la fabrication avec
le même message en français. Un fichier est écrit dans le dossier de sortie :
`reglages_radio.h` (les réglages du plateau et de la boîte, l'adresse de la boîte sur le bus).
"""

import sys
from pathlib import Path

from vidange.entrees_sorties import (
    BOITE_POSTE_FUT,
    EntreesSorties,
    LiaisonUsbSerie,
    charger_entrees_sorties,
)
from vidange.pesees.entete import charger
from vidange.pesees.verification import verifier_avec_liste
from vidange.reglages import ErreurReglages, ReglagesPesees


def boite_du_poste(liste: EntreesSorties) -> str:
    """Le nom du signal de la boîte du poste du fût (appareil: boite_poste_fut)."""
    for nom, signal in liste.signaux.items():
        if signal.appareil == BOITE_POSTE_FUT and signal.adresse is not None:
            return nom
    raise ErreurReglages(
        "entrees-sorties.yaml : aucune boîte du poste du fût (signal avec « appareil: "
        "boite_poste_fut » et une « adresse »)"
    )


def octets_adresse(adresse: str) -> str:
    """« 02:50:46:00:00:01 » → « {0x02, 0x50, 0x46, 0x00, 0x00, 0x01} »."""
    return "{" + ", ".join(f"0x{octet}" for octet in adresse.split(":")) + "}"


def rediger_entete(reglages: ReglagesPesees, liste: EntreesSorties) -> str:
    """Le contenu de reglages_radio.h."""
    radio_fut = reglages.poste_fut_radio
    if radio_fut is None:
        raise ErreurReglages("pesees.yaml : il manque « poste_fut_radio »")
    nom = boite_du_poste(liste)
    signal = liste.signaux[nom]
    liaison = liste.cartes[signal.carte].liaison
    if not isinstance(liaison, LiaisonUsbSerie):
        raise ErreurReglages(
            f"entrees-sorties.yaml : la carte « {signal.carte} » de « {nom} » doit être un "
            "adaptateur USB-RS485 (liaison usb_serie)"
        )
    radio = radio_fut.radio
    plateau = radio_fut.plateau
    boite = radio_fut.boite
    courbe_mv = ", ".join(str(mv) for mv, _ in plateau.courbe_accu)
    courbe_pct = ", ".join(str(pct) for _, pct in plateau.courbe_accu)
    valeurs: dict[str, object] = {
        # Le bus des pesées (la boîte du poste).
        "ADRESSE": signal.adresse,
        "NOM_SIGNAL": f'"{nom}"',
        "VITESSE_BAUDS": liaison.vitesse_bauds,
        "DELAI_AVANT_REPONSE_US": reglages.programme.delai_avant_reponse_us,
        # Réglages d'exemple ici ou dans la liste des entrées/sorties : les cartes le disent.
        "EXEMPLE": int(reglages.exemple or signal.exemple),
        # La radio.
        "ADRESSE_PLATEAU": octets_adresse(radio.adresse_plateau),
        "ADRESSE_BOITE": octets_adresse(radio.adresse_boite),
        "ADRESSE_PLATEAU_TEXTE": f'"{radio.adresse_plateau}"',
        "ADRESSE_BOITE_TEXTE": f'"{radio.adresse_boite}"',
        "CANAL": radio.canal,
        "PUISSANCE_DBM": radio.puissance_dbm,
        # Le plateau.
        **_broches("PLATEAU", plateau.broches.model_dump()),
        "PLATEAU_VOYANT_ACTIF_BAS": int(plateau.voyant_actif_bas),
        "PLATEAU_MESURES_PAR_SECONDE": plateau.mesures_par_seconde_hx711,
        "PLATEAU_PERIODE_TRAME_MS": plateau.periode_trame_ms,
        "PLATEAU_MOYENNE_DE": plateau.moyenne_de,
        "PLATEAU_SANS_MESURE_MS": plateau.sans_mesure_ms,
        "PLATEAU_SOMMEIL_APRES_MS": round(plateau.sommeil_apres_s * 1000),
        "PLATEAU_RAPPORT_PONT_MILLIEMES": round(plateau.rapport_pont_accu * 1000),
        "PLATEAU_COURBE_POINTS": len(plateau.courbe_accu),
        "PLATEAU_COURBE_MV": "{" + courbe_mv + "}",
        "PLATEAU_COURBE_PCT": "{" + courbe_pct + "}",
        "PLATEAU_CHIEN_DE_GARDE_MS": plateau.chien_de_garde_ms,
        "PLATEAU_PERIODE_AFFICHAGE_MS": plateau.periode_affichage_ms,
        # La boîte du poste.
        **_broches("BOITE", boite.broches.model_dump()),
        "BOITE_VOYANT_ACTIF_BAS": int(boite.voyant_actif_bas),
        "BOITE_RADIO_MUETTE_MS": boite.radio_muette_ms,
        "BOITE_CHIEN_DE_GARDE_MS": boite.chien_de_garde_ms,
        "BOITE_PERIODE_AFFICHAGE_MS": boite.periode_affichage_ms,
    }
    lignes = [
        "// Écrit par vidange.pesees.entete_radio depuis pi/reglages/pesees.yaml",
        "// (poste_fut_radio) et docs/entrees-sorties.yaml. Ne pas modifier : changer ces",
        "// fichiers et refabriquer.",
        "#pragma once",
        "",
        *(f"#define REGLAGE_{cle} {valeur}" for cle, valeur in valeurs.items()),
        "",
    ]
    return "\n".join(lignes)


def _broches(carte: str, broches: dict[str, int | None]) -> dict[str, int]:
    """Les broches d'une carte ; une broche absente (null) vaut -1."""
    return {
        f"{carte}_BROCHE_{nom.upper()}": -1 if broche is None else broche
        for nom, broche in broches.items()
    }


def ecrire(chemin_reglages: Path, chemin_liste: Path, dossier: Path) -> None:
    reglages = charger(chemin_reglages)
    liste = charger_entrees_sorties(chemin_liste)
    erreurs = verifier_avec_liste(reglages, liste)
    if erreurs:
        lignes = "\n".join(f"  - {erreur}" for erreur in erreurs)
        raise ErreurReglages(f"Réglages des pesées qui ne vont pas ensemble :\n{lignes}")
    contenu = rediger_entete(reglages, liste)
    dossier.mkdir(parents=True, exist_ok=True)
    # On n'écrit que ce qui change : le programme n'est pas refait pour rien.
    chemin = dossier / "reglages_radio.h"
    if not chemin.exists() or chemin.read_text(encoding="utf-8") != contenu:
        chemin.write_text(contenu, encoding="utf-8")


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    if len(arguments) != 3:
        print(
            "Utilisation : python -m vidange.pesees.entete_radio <pesees.yaml> "
            "<entrees-sorties.yaml> <dossier>",
            file=sys.stderr,
        )
        return 2
    try:
        ecrire(Path(arguments[0]), Path(arguments[1]), Path(arguments[2]))
    except ErreurReglages as erreur:
        print(erreur, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
