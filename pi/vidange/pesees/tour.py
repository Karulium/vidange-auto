"""Les cartes de pesée du bus RS485, interrogées à tour de rôle par le Pi.

    tour = TourPesees(reglages.pesees, materiel)
    tour.demarrer(arret)                       # interroge les cartes en fond, sans fin
    pesee = tour.capteur("pesee_griffe")       # pour BrasFluidnc, AgitateurFluidnc...
    pesee.lire_n()                             # charge en newtons (CapteurForce)
    pesee.lire_kg()                            # ou en kilogrammes

Le Pi pose ses questions dans l'ordre de `tour` (pi/reglages/pesees.yaml), sans pause : une
carte qui y revient deux fois est lue deux fois plus souvent (la griffe, 80 mesures par
seconde). Chaque carte mesure seule, 80 fois par seconde ; le Pi garde sa dernière mesure.
Ceux qui lisent une pesée ont toujours la dernière, ou une erreur si elle est trop vieille
(`age_max_ms`) ou si le HX711 de la carte est muet : jamais une vieille valeur prise pour bonne.

Une carte muette ne fait pas attendre les autres : elle coûte le délai de l'adaptateur
(`delai_reponse_s` de rs485_pesee dans entrees-sorties.yaml) à chaque tour.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from vidange.fiabilite.constats import Constat
from vidange.griffe.bras import G
from vidange.journal import donner_journal
from vidange.materiel import ErreurMateriel, Materiel, PeseeMuette
from vidange.materiel.carte_pesee import MesureCarte
from vidange.reglages import ReglagesPesees

journal = donner_journal("pesees")

QUOI_FAIRE_MUETTE = (
    "Vérifier le câble du bus des pesées (A, B, 0 V) jusqu'à cette carte, son alimentation, et "
    "l'adaptateur USB-RS485 du Pi (pesee/essai-etabli.md)."
)
QUOI_FAIRE_HX711 = (
    "La carte répond mais son HX711 ne mesure plus : vérifier le capteur et ses fils jusqu'au "
    "HX711, et son alimentation 3,3 V."
)


@dataclass
class EtatCarte:
    """Ce que le Pi sait d'une carte, depuis le démarrage."""

    # Dernière réponse : (heure du Pi, mesure).
    derniere: tuple[float, MesureCarte] | None = None
    questions: int = 0
    reponses: int = 0
    # Mesures différentes vues par le Pi (numéro changé depuis la réponse d'avant) : à comparer
    # aux mesures faites par la carte (80 par seconde).
    mesures_vues: int = 0
    erreur: str = ""
    # La carte est-elle dite muette au journal (pour ne l'écrire qu'une fois) ?
    muette: bool = False


class CapteurPesee:
    """Une pesée du bus, en kilogrammes ou en newtons (l'interface CapteurForce)."""

    def __init__(self, tour: "TourPesees", nom: str) -> None:
        self.tour = tour
        self.nom = nom
        self.etalonnage = tour.reglages.etalonnage[nom]

    def lire_brut(self) -> int:
        """La dernière mesure brute ; ErreurMateriel si elle est trop vieille ou absente."""
        etat = self.tour.etats[self.nom]
        derniere = etat.derniere
        if derniere is None:
            raise ErreurMateriel(f"pesée « {self.nom} » muette : aucune réponse de sa carte")
        heure, mesure = derniere
        if mesure.hx711_muet:
            raise PeseeMuette(f"pesée « {self.nom} » : HX711 muet (débranché ?)")
        age_s = self.tour.horloge() - heure + mesure.age_ms / 1000
        if age_s * 1000 > self.tour.reglages.age_max_ms:
            raise ErreurMateriel(
                f"pesée « {self.nom} » muette : dernière mesure vieille de {age_s:.2f} s"
            )
        return mesure.brut

    def lire_kg(self) -> float:
        etalonnage = self.etalonnage
        return (self.lire_brut() - etalonnage.zero_brut) / etalonnage.brut_par_kg

    def lire_n(self) -> float:
        return self.lire_kg() * G


class TourPesees:
    def __init__(
        self,
        reglages: ReglagesPesees,
        materiel: Materiel,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.reglages = reglages
        self.materiel = materiel
        self.horloge = horloge
        self.etats = {nom: EtatCarte() for nom in reglages.tour}
        self._verrou = threading.Lock()

    def capteur(self, nom: str) -> CapteurPesee:
        if nom not in self.etats:
            raise KeyError(f"pesée inconnue « {nom} » (absente de « tour » dans pesees.yaml)")
        return CapteurPesee(self, nom)

    # ------------------------------------------------------------ les questions

    def interroger(self, nom: str) -> bool:
        """Une question à une carte. Vrai si elle a répondu."""
        etat = self.etats[nom]
        etat.questions += 1
        try:
            mesure = self.materiel.lire_carte_pesee(nom)
        except ErreurMateriel as erreur:
            etat.erreur = str(erreur)
            if not etat.muette:
                etat.muette = True
                journal.warning("Carte de pesée muette : %s", erreur)
            return False
        heure = self.horloge()
        if etat.derniere is not None and mesure.numero != etat.derniere[1].numero:
            etat.mesures_vues += 1
        etat.derniere = (heure, mesure)
        etat.reponses += 1
        etat.erreur = ""
        if etat.muette:
            etat.muette = False
            journal.info("Carte de pesée « %s » : elle répond de nouveau.", nom)
        return True

    def faire_un_tour(self) -> bool:
        """Une question à chaque carte de `tour`. Vrai si au moins une a répondu."""
        with self._verrou:
            reponses = [self.interroger(nom) for nom in self.reglages.tour]
        return any(reponses)

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        """Interroge les cartes en fond, jusqu'à `arret`."""

        def boucle() -> None:
            while True:
                try:
                    une_repond = self.faire_un_tour()
                except Exception:
                    journal.exception("Erreur pendant le tour des pesées")
                    une_repond = False
                attente_s = (
                    self.reglages.pause_entre_tours_ms / 1000
                    if une_repond
                    else self.reglages.reconnexion_s
                )
                if arret.wait(attente_s):
                    return

        fil = threading.Thread(target=boucle, name="pesees", daemon=True)
        fil.start()
        return fil

    # ------------------------------------------------------------ check-list

    def constats(self) -> list[Constat]:
        """Pour la check-list (jamais bloquant : chaque module refuse de bouger sans sa pesée)."""
        constats = []
        for nom, etat in self.etats.items():
            sujet = f"pesée {nom}"
            if etat.derniere is None or etat.erreur:
                texte = etat.erreur or "pas encore de réponse"
                constats.append(Constat(sujet, "attention", texte, QUOI_FAIRE_MUETTE))
                continue
            mesure = etat.derniere[1]
            if mesure.hx711_muet:
                constats.append(Constat(sujet, "attention", "HX711 muet", QUOI_FAIRE_HX711))
            elif mesure.exemple:
                constats.append(
                    Constat(
                        sujet,
                        "attention",
                        "programme de la carte fait avec des réglages d'exemple",
                        "Refaire le programme avec les vrais pesees.yaml et entrees-sorties.yaml "
                        "(pesee/README.md), puis le recharger dans la carte.",
                    )
                )
            else:
                texte = f"répond, {mesure.par_seconde} mesures par seconde"
                constats.append(Constat(sujet, "ok", texte))
        if self.reglages.exemple:
            constats.append(
                Constat(
                    "pesees.yaml",
                    "attention",
                    "étalonnage d'exemple : les poids lus sont faux",
                    "Étalonner chaque carte (pesee/essai-etabli.md), puis passer « exemple » à "
                    "false.",
                )
            )
        return constats
