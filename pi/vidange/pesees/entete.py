"""Écrit les réglages des cartes de pesée pour leur programme (en C, dossier pesee/).

Lancé par CMake quand on fabrique le programme (`pesee/reglages.cmake`) :

    python -m vidange.pesees.entete <pesees.yaml> <entrees-sorties.yaml> <dossier de sortie>

Les deux fichiers sont vérifiés comme au démarrage du Pi ; une erreur arrête la fabrication
avec le même message en français. Deux fichiers sont écrits dans le dossier de sortie :
`reglages_genere.h` (les valeurs communes aux cartes) et `reglages_genere.cmake` (la carte pour
le Pico SDK, et la liste des cartes avec leur adresse : un programme par carte).
"""

import sys
from pathlib import Path

from pydantic import ValidationError

from vidange.entrees_sorties import EntreesSorties, LiaisonUsbSerie, charger_entrees_sorties
from vidange.pesees.verification import cartes_de_pesee, verifier_avec_liste
from vidange.reglages import (
    ErreurReglages,
    ReglagesPesees,
    lire_yaml,
    traduire_erreurs,
)


def charger(chemin: Path) -> ReglagesPesees:
    """Lit et vérifie pesees.yaml, ou lève ErreurReglages."""
    try:
        return ReglagesPesees.model_validate(lire_yaml(chemin))
    except ValidationError as erreur:
        lignes = "\n".join(f"  - {ligne}" for ligne in traduire_erreurs(erreur, chemin.name))
        raise ErreurReglages(f"Réglages faux dans {chemin} :\n{lignes}") from None


def vitesse_du_bus(liste: EntreesSorties) -> int:
    for nom in cartes_de_pesee(liste):
        liaison = liste.cartes[liste.signaux[nom].carte].liaison
        if isinstance(liaison, LiaisonUsbSerie):
            return liaison.vitesse_bauds
    raise ErreurReglages("entrees-sorties.yaml : aucune carte de pesée (appareil: carte_pesee)")


def rediger_entete(reglages: ReglagesPesees, liste: EntreesSorties) -> str:
    """Le contenu de reglages_genere.h."""
    broches = reglages.broches
    programme = reglages.programme
    valeurs = {
        "BROCHE_HX711_DT": broches.hx711_dt,
        "BROCHE_HX711_SCK": broches.hx711_sck,
        "BROCHE_RS485_TX": broches.rs485_tx,
        "BROCHE_RS485_RX": broches.rs485_rx,
        "BROCHE_RS485_SENS": broches.rs485_sens,
        "BROCHE_VOYANT": -1 if broches.voyant is None else broches.voyant,
        "BLOC_UART": broches.bloc_uart,
        "VITESSE_BAUDS": vitesse_du_bus(liste),
        "SANS_MESURE_MS": programme.sans_mesure_ms,
        "DELAI_AVANT_REPONSE_US": programme.delai_avant_reponse_us,
        "CHIEN_DE_GARDE_MS": programme.chien_de_garde_ms,
        "PERIODE_AFFICHAGE_MS": programme.periode_affichage_ms,
        # Réglages d'exemple ici ou dans la liste des entrées/sorties : la carte le dit au Pi.
        "EXEMPLE": int(
            reglages.exemple or any(liste.signaux[n].exemple for n in cartes_de_pesee(liste))
        ),
    }
    lignes = [
        "// Écrit par vidange.pesees.entete depuis pi/reglages/pesees.yaml et",
        "// docs/entrees-sorties.yaml. Ne pas modifier : changer ces fichiers et refabriquer.",
        "#pragma once",
        "",
        *(f"#define REGLAGE_{nom} {valeur}" for nom, valeur in valeurs.items()),
        "",
        *_lignes_i2c(reglages),
    ]
    return "\n".join(lignes)


def _lignes_i2c(reglages: ReglagesPesees) -> list[str]:
    """L'I2C de la seule carte qui en a (le programme des autres cartes ne s'en sert pas)."""
    i2c = reglages.i2c
    if i2c is None:
        return []
    pca = i2c.pca9685
    tof = i2c.vl6180x
    voies = ", \\\n".join(
        f"    {{.canal = {v.canal}, .angle_min_dix = {v.angle_min_dix}, "
        f".angle_max_dix = {v.angle_max_dix}, .impulsion_min_us = {v.impulsion_min_us}, "
        f".impulsion_max_us = {v.impulsion_max_us}}}"
        for v in pca.voies.values()
    )
    valeurs = {
        "I2C_BROCHE_SDA": i2c.broches.sda,
        "I2C_BROCHE_SCL": i2c.broches.scl,
        "I2C_BLOC": i2c.broches.bloc_i2c,
        "I2C_FREQUENCE_HZ": i2c.frequence_hz,
        "I2C_DELAI_TRANSACTION_US": i2c.delai_transaction_us,
    }
    return [
        "// L'I2C de la carte du plateau du remplissage (REGLAGE_AVEC_I2C = 1 pour elle seule).",
        *(f"#define REGLAGE_{nom} {valeur}" for nom, valeur in valeurs.items()),
        "#define REGLAGE_I2C_CONFIG { \\",
        f"    .pca = {{.adresse = {pca.adresse}, .frequence_hz = {pca.frequence_pwm_hz}, "
        f".horloge_hz = {pca.horloge_hz}}}, \\",
        f"    .pca_reveil_us = {pca.reveil_us}, \\",
        f"    .tof = {{.adresse = {tof.adresse}, .periode_ms = {tof.periode_ms}, "
        f".sondage_ms = {tof.sondage_ms}, .delai_max_ms = {tof.delai_max_ms}, "
        f".reessai_ms = {i2c.reessai_ms}}}, \\",
        f"    .silence_pi_ms = {i2c.silence_pi_ms}, \\",
        f"    .reessai_ms = {i2c.reessai_ms}, \\",
        f"    .nb_voies = {len(pca.voies)}, \\",
        "    .voies = { \\",
        voies + " \\",
        "    } \\",
        "}",
        "",
    ]


def rediger_cmake(reglages: ReglagesPesees, liste: EntreesSorties) -> str:
    """Le contenu de reglages_genere.cmake (lu avant le Pico SDK)."""
    cartes = ";".join(f"{nom};{adresse}" for nom, adresse in cartes_de_pesee(liste).items())
    carte_i2c = "" if reglages.i2c is None else reglages.i2c.carte
    return (
        "# Écrit par vidange.pesees.entete depuis pi/reglages/pesees.yaml et\n"
        "# docs/entrees-sorties.yaml.\n"
        f'set(PICO_BOARD "{reglages.carte}")\n'
        "# Chaque carte de pesée et son adresse sur le bus (un programme par carte).\n"
        f'set(CARTES_PESEE "{cartes}")\n'
        "# La seule carte qui a l'I2C (servos et capteur de distance) ; vide : aucune.\n"
        f'set(CARTE_PESEE_I2C "{carte_i2c}")\n'
    )


def ecrire(chemin_reglages: Path, chemin_liste: Path, dossier: Path) -> None:
    reglages = charger(chemin_reglages)
    liste = charger_entrees_sorties(chemin_liste)
    erreurs = verifier_avec_liste(reglages, liste)
    if erreurs:
        lignes = "\n".join(f"  - {erreur}" for erreur in erreurs)
        raise ErreurReglages(f"Réglages des pesées qui ne vont pas ensemble :\n{lignes}")
    dossier.mkdir(parents=True, exist_ok=True)
    # On n'écrit que ce qui change : le programme n'est pas refait pour rien.
    for nom, contenu in (
        ("reglages_genere.h", rediger_entete(reglages, liste)),
        ("reglages_genere.cmake", rediger_cmake(reglages, liste)),
    ):
        chemin = dossier / nom
        if not chemin.exists() or chemin.read_text(encoding="utf-8") != contenu:
            chemin.write_text(contenu, encoding="utf-8")


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    if len(arguments) != 3:
        print(
            "Utilisation : python -m vidange.pesees.entete <pesees.yaml> "
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
