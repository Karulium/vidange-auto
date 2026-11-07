"""Écrit les réglages de la carte ESP32 n° 5 du spray pour son programme (en C, dossier spray/,
tâche 39 bis).

Lancé par CMake quand on fabrique le programme (`spray/reglages.cmake`) :

    python -m vidange.entete_spray <dossier des réglages> <entrees-sorties.yaml> <dossier de sortie>

Tous les réglages sont vérifiés comme au démarrage du Pi ; une erreur arrête la fabrication avec
le même message en français. Un fichier est écrit dans le dossier de sortie : `reglages_spray.h`
(machine.yaml → spray, pesees.yaml → balances_spray, l'adresse de la carte et la vitesse du bus).

Ce module est à part de vidange.spray : la fabrication n'installe que pydantic et PyYAML.
"""

import sys
from pathlib import Path

from vidange.entrees_sorties import (
    CARTE_SPRAY,
    EntreesSorties,
    LiaisonUsbSerie,
    charger_entrees_sorties,
)
from vidange.reglages import ErreurReglages, Reglages, charger_reglages, courants_tmc2209

NOM_FICHIER = "reglages_spray.h"


def carte_du_spray(reglages: Reglages, liste: EntreesSorties) -> tuple[str, int, int, bool]:
    """(nom du signal, adresse, vitesse du bus, exemple) de la carte du spray."""
    spray = reglages.machine.spray
    if spray is None:
        raise ErreurReglages("machine.yaml : il manque la partie « spray »")
    signal = liste.signaux.get(spray.signal)
    if signal is None or signal.appareil != CARTE_SPRAY or signal.adresse is None:
        raise ErreurReglages(
            f"entrees-sorties.yaml : « {spray.signal} » (machine.yaml → spray → signal) doit être "
            "un signal avec « appareil: carte_spray » et une « adresse »"
        )
    liaison = liste.cartes[signal.carte].liaison
    if not isinstance(liaison, LiaisonUsbSerie) or liaison.parite != "aucune":
        raise ErreurReglages(
            f"entrees-sorties.yaml : la carte « {signal.carte} » de « {spray.signal} » doit "
            "être un adaptateur USB-RS485 (liaison usb_serie) sans parité"
        )
    return spray.signal, signal.adresse, liaison.vitesse_bauds, signal.exemple


def _ms(secondes: float) -> int:
    return round(secondes * 1000)


def _tableau(valeurs) -> str:
    return "{" + ", ".join(str(v) for v in valeurs) + "}"


def rediger_entete(reglages: Reglages, liste: EntreesSorties) -> str:
    """Le contenu de reglages_spray.h."""
    nom, adresse, bauds, exemple_liste = carte_du_spray(reglages, liste)
    spray = reglages.machine.spray
    assert spray is not None
    carte = spray.carte
    if carte is None:
        raise ErreurReglages("machine.yaml : il manque « spray → carte » (programme de la carte)")
    balances = reglages.pesees.balances_spray
    if balances is None:
        raise ErreurReglages("pesees.yaml : il manque « balances_spray » (étalonnage)")
    broches = carte.broches
    moteur = carte.moteur_bras
    vsense, irun, ihold = courants_tmc2209(spray.bras.courant_a, moteur)
    pas_par_tour = moteur.pas_par_tour_bras
    pas_par_deg = pas_par_tour / 360
    valeurs: dict[str, object] = {
        # Le bus du spray.
        "ADRESSE": adresse,
        "NOM_SIGNAL": f'"{nom}"',
        "VITESSE_BAUDS": bauds,
        "DELAI_AVANT_REPONSE_US": carte.delai_avant_reponse_us,
        # Réglages d'exemple ici ou dans la liste des entrées/sorties : la carte le dit au Pi.
        "EXEMPLE": int(spray.exemple or reglages.pesees.exemple or exemple_liste),
        # Les broches (-1 : absente).
        "BROCHE_RS485_TX": broches.rs485_tx,
        "BROCHE_RS485_RX": broches.rs485_rx,
        "BROCHE_RS485_SENS": broches.rs485_sens,
        "BROCHE_PILOTE_BRAS_TX": broches.pilote_bras_tx,
        "BROCHE_PILOTE_BRAS_RX": broches.pilote_bras_rx,
        "BROCHE_BRAS_PAS": broches.bras_pas,
        "BROCHE_BRAS_SENS": broches.bras_sens,
        "BROCHE_ACTIVER_MOTEURS": broches.activer_moteurs,
        "BROCHES_POMPES_PAS": _tableau(broches.pompes_pas),
        "BROCHE_POMPES_SENS": -1 if broches.pompes_sens is None else broches.pompes_sens,
        "BROCHES_HX711_DT": _tableau(broches.hx711_dt),
        "BROCHES_HX711_SCK": _tableau(broches.hx711_sck),
        "BROCHE_BRAS_RANGE": broches.bras_spray_range,
        "BROCHE_EV_BUSE": broches.ev_buse_spray,
        "BROCHE_EV_CHASSE": broches.ev_chasse_spray,
        "BROCHE_AGITATEURS": broches.agitateurs_spray,
        "BROCHE_POMPE_NETTOYAGE": broches.pompe_nettoyage_spray,
        "BROCHE_VOYANT": -1 if broches.voyant is None else broches.voyant,
        "VOYANT_ACTIF_BAS": int(carte.voyant_actif_bas),
        # Le bras (angles en dixièmes de degré, pas du moteur après les micro-pas).
        "BRAS_COURSE_DIXIEMES": round(spray.bras.course_deg[1] * 10),
        "BRAS_PAS_PAR_TOUR": pas_par_tour,
        "BRAS_VITESSE_PAS_S": max(1, round(spray.bras.vitesse_deg_s * pas_par_deg)),
        "BRAS_ACCELERATION_PAS_S2": max(1, round(moteur.acceleration_deg_s2 * pas_par_deg)),
        "BRAS_DEPASSEMENT_PAS": round(moteur.depassement_max_deg * pas_par_deg),
        "BRAS_TEMPS_MAX_MS": _ms(spray.bras.temps_max_s),
        "BRAS_SENS_INVERSE": int(moteur.sens_inverse),
        "BRAS_FILTRE_CAPTEUR_MS": moteur.filtre_capteur_ms,
        # Le pilote TMC2209 du bras.
        "PILOTE_ADRESSE": moteur.adresse_uart,
        "PILOTE_VITESSE_BAUDS": moteur.vitesse_uart_bauds,
        "PILOTE_MICRO_PAS": moteur.micro_pas,
        "PILOTE_VSENSE": vsense,
        "PILOTE_IRUN": irun,
        "PILOTE_IHOLD": ihold,
        "PILOTE_LECTURE_MS": moteur.lecture_pilote_ms,
        # Les pompes.
        "POMPES_VITESSE_PAS_S": carte.pompes.vitesse_pas_s,
        "POMPES_ACCELERATION_PAS_S2": carte.pompes.acceleration_pas_s2,
        "POMPES_SENS_INVERSE": int(carte.pompes.sens_inverse),
        # Les gestes.
        "AIR_AVANT_MS": _ms(spray.dose.air_avant_s),
        "TEMPS_MAX_POMPAGE_MS": _ms(spray.dose.temps_max_pompage_s),
        "CHASSE_MS": _ms(spray.dose.chasse_s),
        "AIR_APRES_MS": _ms(spray.dose.air_apres_s),
        "NETTOYAGE_POMPE_MS": _ms(spray.nettoyage.pompe_s),
        "SECHAGE_MS": _ms(spray.nettoyage.sechage_s),
        "SILENCE_MAX_MS": _ms(spray.liaison.silence_max_s),
        "AGITATEURS_PWM_HZ": carte.agitateurs_pwm_hz,
        # Les balances (étalonnage : pesees.yaml → balances_spray).
        "BALANCES_MESURES_PAR_SECONDE": carte.balances.mesures_par_seconde,
        "BALANCES_MOYENNE_DE": carte.balances.moyenne_de,
        "BALANCES_SANS_MESURE_MS": carte.balances.sans_mesure_ms,
        "BALANCES_INSTABLE_DIXIEMES": max(1, round(carte.balances.instable_g * 10)),
        "BALANCES_ZERO_BRUT": _tableau(balances[n].zero_brut for n in range(1, 5)),
        "BALANCES_BRUT_PAR_KG": _tableau(
            f"{float(balances[n].brut_par_kg)!r}f" for n in range(1, 5)
        ),
        # Le programme.
        "PERIODE_PAS_US": carte.periode_pas_us,
        "CHIEN_DE_GARDE_MS": carte.chien_de_garde_ms,
        "PERIODE_AFFICHAGE_MS": carte.periode_affichage_ms,
    }
    lignes = [
        "// Écrit par vidange.entete_spray depuis pi/reglages/machine.yaml (spray),",
        "// pi/reglages/pesees.yaml (balances_spray) et docs/entrees-sorties.yaml. Ne pas",
        "// modifier : changer ces fichiers et refabriquer.",
        "#pragma once",
        "",
        *(f"#define REGLAGE_{cle} {valeur}" for cle, valeur in valeurs.items()),
        "",
    ]
    return "\n".join(lignes)


def ecrire(dossier_reglages: Path, chemin_liste: Path, dossier: Path) -> None:
    reglages = charger_reglages(dossier_reglages)
    liste = charger_entrees_sorties(chemin_liste)
    contenu = rediger_entete(reglages, liste)
    dossier.mkdir(parents=True, exist_ok=True)
    # On n'écrit que ce qui change : le programme n'est pas refait pour rien.
    chemin = dossier / NOM_FICHIER
    if not chemin.exists() or chemin.read_text(encoding="utf-8") != contenu:
        chemin.write_text(contenu, encoding="utf-8")


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    if len(arguments) != 3:
        print(
            "Utilisation : python -m vidange.entete_spray <dossier des réglages> "
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
