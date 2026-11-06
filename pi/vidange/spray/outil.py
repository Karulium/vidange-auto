"""Outil « vidange-spray » : parler à la carte ESP32 n° 5 du spray, pour les essais.

  vidange-spray etat [--secondes 10]          une ligne par seconde : bras, flacons, dose (Ctrl+C)
  vidange-spray origine                       prise d'origine du bras (vers « rangé », capteur)
  vidange-spray sortir 72.4 --etabli          le bras sort à cet angle (°)
  vidange-spray ranger                        le bras se range
  vidange-spray dose 1 5 --etabli             spray : emplacement 1, 5 g (le bras doit être sorti)
  vidange-spray nettoyer --etabli             nettoyage des tubes (le bras doit être sorti)
  vidange-spray agiter 60 30                  agitateurs à 60 % pendant 30 s (0 s : arrêt)
  vidange-spray arret                         arrêt immédiat (pompe, air, agitateurs, bras)
  vidange-spray effacer                       effacer les erreurs de la carte
  vidange-spray zero 1                        étalonnage, étape 1 : emplacement 1 sans flacon
  vidange-spray etalonner 1 200               étape 2 : une masse connue (ici 200 g) posée
  ... --faux                                  pareil, avec la fausse carte (pour essayer)

Pendant un ordre, l'outil bat (comme le programme principal) et montre l'état jusqu'à la fin.
« sortir », « dose » et « nettoyer » demandent --etabli : l'outil ne vérifie PAS la règle 6 du
chariot (plateau assez bas, barres ouvertes) ; à ne faire que carte et bras à l'établi, ou chariot
vérifié à la main. Les lignes d'étalonnage sont à recopier dans pi/reglages/pesees.yaml
(balances_spray) ; l'outil n'écrit jamais lui-même dans les réglages. Procédure complète :
pi/systeme/essai-spray.md.

À ne lancer que quand le programme principal est arrêté (l'adaptateur ne s'ouvre qu'une fois).
"""

import argparse
import sys
import time
from statistics import median

from vidange.demarrage import DOSSIER_PI, _chemin
from vidange.entrees_sorties import CARTE_SPRAY, charger_entrees_sorties
from vidange.journal import configurer_journal
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel
from vidange.materiel import carte_spray as table
from vidange.materiel.carte_spray import EtatSpray
from vidange.poste_fut.pesee import pente
from vidange.reglages import ErreurReglages, charger_reglages

DUREE_ETALONNAGE_S = 3.0
SUITES = {0: "aucun", 1: "en cours", 2: "fait", 3: "REFUSÉ", 4: "ÉCHOUÉ"}
DOSES = {0: "aucune", 1: "en cours", 2: "atteinte", 3: "TEMPS MAX", 4: "INTERROMPUE", 5: "REFUSÉE"}


def ligne(etat: EtatSpray) -> str:
    bras = "rangé" if etat.bras_range else ("sorti" if etat.bras_sorti else "pas rangé")
    if etat.bras_bouge:
        bras += ", bouge"
    flacons = "  ".join(
        f"{i + 1}: "
        + ("MUETTE" if f.muette else f"{f.grammes:6.1f} g" + (" ?" if f.instable else ""))
        for i, f in enumerate(etat.flacons)
    )
    dose = etat.dose
    texte = (
        f"bras {etat.angle_deg:5.1f}° ({bras}{', origine faite' if etat.origine_faite else ''})  "
        f"ordre n° {etat.numero_ordre} {SUITES.get(etat.suite_ordre, '?')}"
        + (f" ({etat.raison_du_refus})" if etat.refus else "")
        + f"  flacons {flacons}  dernière dose : {DOSES.get(dose.resultat, '?')}"
    )
    if dose.emplacement:
        texte += (
            f" (emplacement {dose.emplacement}, {dose.perdue_g:.1f} g perdus sur "
            f"{dose.demandee_g:g} g, {dose.duree_s:.1f} s)"
        )
    if etat.erreurs & 0xFF00:
        texte += "  ERREURS : " + ", ".join(etat.erreurs_du_bras())
    if etat.etat & table.ETAT_SILENCE_PI:
        texte += "  ARRÊT SEULE (le Pi s'est tu)"
    return texte


def main(arguments: list[str] | None = None, fabrique=None) -> int:
    lecteur = argparse.ArgumentParser(prog="vidange-spray", description=__doc__.split("\n")[0])
    lecteur.add_argument("--reglages", help="dossier des réglages (défaut : pi/reglages)")
    lecteur.add_argument(
        "--entrees-sorties", help="liste des entrées/sorties (défaut : docs/entrees-sorties.yaml)"
    )
    lecteur.add_argument("--faux", action="store_true", help="avec la fausse carte")
    lecteur.add_argument("--attente", type=float, default=30, help="suivi d'un ordre (s)")
    commandes = lecteur.add_subparsers(dest="commande", required=True)
    commandes.add_parser("etat", help="une ligne par seconde").add_argument(
        "--secondes", type=int, help="durée (défaut : sans fin)"
    )
    commandes.add_parser("origine", help="prise d'origine du bras")
    sortir = commandes.add_parser("sortir", help="le bras sort à cet angle")
    sortir.add_argument("angle", type=float)
    sortir.add_argument("--etabli", action="store_true", help="règle 6 vérifiée à la main")
    commandes.add_parser("ranger", help="le bras se range")
    dose = commandes.add_parser("dose", help="spray : emplacement, grammes")
    dose.add_argument("emplacement", type=int)
    dose.add_argument("grammes", type=float)
    dose.add_argument("--etabli", action="store_true", help="règle 6 vérifiée à la main")
    nettoyer = commandes.add_parser("nettoyer", help="nettoyage des tubes")
    nettoyer.add_argument("--etabli", action="store_true", help="règle 6 vérifiée à la main")
    agiter = commandes.add_parser("agiter", help="agitateurs : vitesse (%%), durée (s)")
    agiter.add_argument("pourcent", type=int)
    agiter.add_argument("secondes", type=int)
    commandes.add_parser("arret", help="arrêt immédiat")
    commandes.add_parser("effacer", help="effacer les erreurs")
    zero = commandes.add_parser("zero", help="étalonnage, étape 1 : sans flacon")
    zero.add_argument("emplacement", type=int)
    etalonner = commandes.add_parser("etalonner", help="étalonnage, étape 2 : masse connue")
    etalonner.add_argument("emplacement", type=int)
    etalonner.add_argument("grammes", type=float)
    options = lecteur.parse_args(arguments)
    configurer_journal()
    dossier = _chemin(options.reglages, "VIDANGE_REGLAGES", DOSSIER_PI / "reglages")
    chemin_liste = _chemin(
        options.entrees_sorties,
        "VIDANGE_ENTREES_SORTIES",
        DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml",
    )
    try:
        reglages = charger_reglages(dossier)
        liste = charger_entrees_sorties(chemin_liste)
    except ErreurReglages as erreur:
        print(erreur, file=sys.stderr)
        return 2
    spray = reglages.machine.spray
    if spray is None:
        print("machine.yaml n'a pas de partie « spray »", file=sys.stderr)
        return 2
    signal = liste.signaux.get(spray.signal)
    if signal is None or signal.appareil != CARTE_SPRAY:
        print(f"entrees-sorties.yaml : pas de signal « {spray.signal} » (appareil: carte_spray)")
        return 2
    if getattr(options, "etabli", True) is False:
        print(
            "ÉCHEC : ajouter --etabli. L'outil ne vérifie pas la règle 6 (plateau ≤ "
            "min(0,50 ; 0,68 − h), barres ouvertes à plus de 0,50 d'entraxe) : carte à l'établi, "
            "ou chariot vérifié à la main.",
            file=sys.stderr,
        )
        return 2
    for nom in ("emplacement",):
        if hasattr(options, nom) and not 1 <= getattr(options, nom) <= table.NB_FLACONS:
            print("ÉCHEC : emplacement de 1 à 4", file=sys.stderr)
            return 2
    if fabrique is None and options.faux:
        fabrique = FausseFabrique(liste)
        fabrique.carte_spray(spray.signal).appliquer(spray)
    with Materiel(liste, fabrique, seulement=[spray.signal]) as materiel:
        outil = _Outil(materiel, spray.signal, spray.liaison.battement_s)
        try:
            return outil.faire(options, reglages)
        except ErreurMateriel as erreur:
            print(f"ÉCHEC : {erreur}", file=sys.stderr)
            return 1


class _Outil:
    def __init__(self, materiel: Materiel, signal: str, battement_s: float) -> None:
        self.materiel = materiel
        self.signal = signal
        self.battement_s = battement_s
        self._battement = 0

    def lire(self) -> EtatSpray:
        return self.materiel.lire_spray(self.signal)

    def battre(self) -> None:
        self._battement = (self._battement + 1) & 0xFFFF
        self.materiel.ecrire_spray(self.signal, table.REGISTRE_BATTEMENT, [self._battement])

    def faire(self, options, reglages) -> int:
        commande = options.commande
        if commande == "etat":
            return self.suivre_etat(options.secondes)
        if commande in ("zero", "etalonner"):
            return self.etalonner(options, reglages)
        ordres = {
            "origine": (table.ORDRE_ORIGINE, 0, 0),
            "ranger": (table.ORDRE_RANGER, 0, 0),
            "arret": (table.ORDRE_ARRET, 0, 0),
            "effacer": (table.ORDRE_EFFACER, 0, 0),
            "nettoyer": (table.ORDRE_NETTOYER, 0, 0),
        }
        if commande == "sortir":
            code = (table.ORDRE_SORTIR, round(options.angle * 10), 0)
        elif commande == "dose":
            code = (table.ORDRE_SPRAY, options.emplacement, round(options.grammes * 10))
        elif commande == "agiter":
            code = (table.ORDRE_AGITER, options.pourcent, options.secondes)
        else:
            code = ordres[commande]
        return self.ordre(*code, attente_s=options.attente)

    def suivre_etat(self, secondes: int | None) -> int:
        try:
            while secondes is None or secondes > 0:
                try:
                    print(ligne(self.lire()))
                except ErreurMateriel as erreur:
                    print(f"ne répond pas : {erreur}")
                time.sleep(1)
                if secondes is not None:
                    secondes -= 1
        except KeyboardInterrupt:
            pass
        return 0

    def ordre(self, code: int, p1: int, p2: int, attente_s: float) -> int:
        etat = self.lire()
        numero = (etat.numero_ordre + 1) & 0xFFFF or 1
        self.battre()
        self.materiel.ecrire_spray(
            self.signal, table.REGISTRE_ORDRE, table.ordre(code, numero, p1, p2)
        )
        fin = time.monotonic() + attente_s
        vu = 0.0
        while time.monotonic() < fin:
            time.sleep(self.battement_s)
            self.battre()
            etat = self.lire()
            if time.monotonic() - vu >= 1:
                print(ligne(etat))
                vu = time.monotonic()
            if etat.numero_ordre != numero:
                continue
            if etat.suite_ordre == table.SUITE_REFUSE:
                print(f"ÉCHEC : ordre refusé par la carte ({etat.raison_du_refus})")
                return 1
            occupee = etat.bras_bouge or etat.spray_en_cours or etat.nettoyage_en_cours
            if etat.suite_ordre != table.SUITE_EN_COURS and not occupee:
                print(ligne(etat))
                if etat.suite_ordre == table.SUITE_ECHOUE:
                    print("ÉCHEC : ordre pas fini (voir les erreurs)")
                    return 1
                print("Fait.")
                return 0
        print(f"ÉCHEC : ordre pas fini au bout de {attente_s:g} s")
        return 1

    def etalonner(self, options, reglages) -> int:
        n = options.emplacement
        valeurs = []
        fin = time.monotonic() + DUREE_ETALONNAGE_S
        while time.monotonic() < fin:
            flacon = self.lire().flacons[n - 1]
            if not flacon.muette:
                valeurs.append(flacon.brut)
            time.sleep(0.1)
        if not valeurs:
            print(f"ÉCHEC : balance de l'emplacement {n} muette")
            return 1
        brut = round(median(valeurs))
        if options.commande == "zero":
            print(f"Zéro mesuré. Recopier dans pesees.yaml (balances_spray → {n}) :")
            print(f"    zero_brut: {brut}")
            return 0
        balances = reglages.pesees.balances_spray or {}
        if n not in balances:
            print("ÉCHEC : pesees.yaml n'a pas de « balances_spray » pour cet emplacement")
            return 1
        zero_brut = balances[n].zero_brut
        try:
            resultat = pente(zero_brut, brut, options.grammes / 1000)
        except ValueError as erreur:
            print(f"ÉCHEC : {erreur}", file=sys.stderr)
            return 1
        print(f"Mesure brute avec {options.grammes:g} g : {brut} (zéro : {zero_brut}).")
        print(f"Recopier dans pesees.yaml (balances_spray → {n}) :")
        print(f"    brut_par_kg: {resultat:.2f}")
        return 0


def lancer() -> None:
    sys.exit(main())
