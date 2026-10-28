"""Écrit les réglages de l'accéléromètre pour le programme du RP2040 (en C).

Lancé par CMake quand on fabrique le programme (`accelerometre/reglages.cmake`) :

    python -m vidange.accelerometre.entete <accelerometre.yaml> <dossier de sortie>

Le fichier est vérifié comme au démarrage du Pi ; une erreur arrête la fabrication avec
le même message en français. Deux fichiers sont écrits dans le dossier de sortie :
`reglages_genere.h` (les valeurs) et `reglages_genere.cmake` (la carte, pour le Pico SDK).
"""

import sys
from pathlib import Path

from pydantic import ValidationError

from vidange.reglages import (
    ErreurReglages,
    ReglagesAccelerometre,
    lire_yaml,
    traduire_erreurs,
)

# Bits des axes, comme dans accelerometre/src/reglages.h.
_BITS_AXES = {"x": 1, "y": 2, "z": 4}


def charger(chemin: Path) -> ReglagesAccelerometre:
    """Lit et vérifie accelerometre.yaml, ou lève ErreurReglages."""
    try:
        return ReglagesAccelerometre.model_validate(lire_yaml(chemin))
    except ValidationError as erreur:
        lignes = "\n".join(f"  - {ligne}" for ligne in traduire_erreurs(erreur, chemin.name))
        raise ErreurReglages(f"Réglages faux dans {chemin} :\n{lignes}") from None


def rediger_entete(reglages: ReglagesAccelerometre) -> str:
    """Le contenu de reglages_genere.h."""
    broches = reglages.broches
    capteur = reglages.capteur
    choc = reglages.choc
    panne = reglages.panne
    valeurs = {
        "BROCHE_I2C_SDA": broches.i2c_sda,
        "BROCHE_I2C_SCL": broches.i2c_scl,
        "BLOC_I2C": broches.bloc_i2c,
        "BROCHE_SORTIE_OK": broches.sortie_ok,
        "BROCHE_FIL_SERIE": broches.fil_serie,
        "BROCHE_VOYANT": -1 if broches.voyant is None else broches.voyant,
        "ADRESSE_LIS3DH": f"0x{capteur.adresse_i2c:02X}",
        "FREQUENCE_I2C_HZ": capteur.frequence_i2c_hz,
        "PLEINE_ECHELLE_G": capteur.pleine_echelle_g,
        "MESURES_PAR_SECONDE": capteur.mesures_par_seconde,
        "AXES": sum(_BITS_AXES[axe] for axe in capteur.axes),
        "SEUIL_MG": round(choc.seuil_g * 1000),
        "DUREE_MIN_MS": choc.duree_min_ms,
        "MAINTIEN_MS": choc.maintien_ms,
        "CONSTANTE_FOND_MS": choc.constante_fond_ms,
        "SANS_MESURE_MS": panne.sans_mesure_ms,
        "ERREURS_LECTURE_MAX": panne.erreurs_lecture_max,
        "FIGEE_MS": panne.figee_ms,
        "REESSAI_MS": panne.reessai_ms,
        "CHIEN_DE_GARDE_MS": panne.chien_de_garde_ms,
        "PERIODE_AFFICHAGE_MS": reglages.console.periode_affichage_ms,
        "VITESSE_FIL_BAUDS": reglages.liaison.vitesse_bauds,
        "EXEMPLE": int(reglages.exemple),
    }
    lignes = [
        "// Écrit par vidange.accelerometre.entete depuis pi/reglages/accelerometre.yaml.",
        "// Ne pas modifier : changer accelerometre.yaml et refabriquer le programme.",
        "#pragma once",
        "",
        *(f"#define REGLAGE_{nom} {valeur}" for nom, valeur in valeurs.items()),
        "",
    ]
    return "\n".join(lignes)


def rediger_cmake(reglages: ReglagesAccelerometre) -> str:
    """Le contenu de reglages_genere.cmake (lu avant le Pico SDK)."""
    return (
        "# Écrit par vidange.accelerometre.entete depuis pi/reglages/accelerometre.yaml.\n"
        f'set(PICO_BOARD "{reglages.carte}")\n'
    )


def ecrire(chemin_reglages: Path, dossier: Path) -> None:
    reglages = charger(chemin_reglages)
    dossier.mkdir(parents=True, exist_ok=True)
    # On n'écrit que ce qui change : le programme n'est pas refait pour rien.
    for nom, contenu in (
        ("reglages_genere.h", rediger_entete(reglages)),
        ("reglages_genere.cmake", rediger_cmake(reglages)),
    ):
        chemin = dossier / nom
        if not chemin.exists() or chemin.read_text(encoding="utf-8") != contenu:
            chemin.write_text(contenu, encoding="utf-8")


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    if len(arguments) != 2:
        print(
            "Utilisation : python -m vidange.accelerometre.entete <accelerometre.yaml> <dossier>",
            file=sys.stderr,
        )
        return 2
    try:
        ecrire(Path(arguments[0]), Path(arguments[1]))
    except ErreurReglages as erreur:
        print(erreur, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
