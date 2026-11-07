"""Air comprimé : le seul signal du Pi est `relais_compresseur` (tâche 42).

    air = Air(reglages.air, materiel, donnees / "air.json", air_permis=lambda: nettoyage.air_permis)
    air.demarrer(arret)                    # commande le relais en fond
    chef.interdire(air.refus_geste)        # pas de geste « à l'air » avant la mise en pression

Le relais est fermé (compresseur autorisé) tant que le Nettoyage le permet (`air_permis` : pas de
nuit UV-ozone) ; il est ouvert sinon. À chaque fermeture, le Pi attend
`attente_mise_en_pression_s` avant de laisser partir un geste qui consomme de l'air : il n'y a pas
de capteur de pression sur la ligne. Un manque d'air se voit chez les consommateurs (vide non
atteint de la Préhension) : l'opérateur valide, rien ne repart seul. Le pressostat du MB50 gère les
démarrages du moteur.

Rappel de vider le bidon de purge : tous les `rappel_bidon_jours`, dans la check-list ; l'opérateur
dit « bidon vidé » (page web). La date est gardée dans un fichier.

La sécurité est câblée (arrêt d'urgence, coupure pendant l'ozone et la purge, pressostat, soupape) :
le relais du Pi n'est que la commande normale. Le logiciel peut planter sans danger.
"""

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from vidange.chef.chef import GESTES_PROTEGES
from vidange.fiabilite.constats import Constat, lancer_boucle
from vidange.journal import donner_journal
from vidange.materiel import ErreurMateriel, Materiel
from vidange.reglages import ReglagesAir

journal = donner_journal("air")

MODULE = "air"
SUJET = "air comprimé"
COMPRESSEUR = "relais_compresseur"
# Gestes du chef qui consomment de l'air : refusés tant que la cuve n'est pas en pression.
# « air » : à demander par la Préhension (venturi), le Lavage (jet) et tout futur consommateur.
GESTES_A_L_AIR = ("air", "spray_seau")

QUOI_FAIRE_AIR = (
    "Vérifier l'air : compresseur sous tension, vanne d'isolement du bloc ouverte, soufflette "
    "en cours (elle vide la cuve) ? Puis acquitter et donner le Go."
)


@dataclass(frozen=True)
class EtatAir:
    # Ce que le Pi commande sur le relais (True = compresseur autorisé).
    compresseur: bool
    # La cuve a eu le temps de se remplir depuis la fermeture du relais.
    en_pression: bool
    # Secondes qu'il reste à attendre (0 si en pression ou si le relais est ouvert).
    reste_s: float
    # Date du dernier « bidon vidé » (ISO), jours depuis, et rappel à faire.
    bidon_vide_le: str | None
    bidon_jours: int
    bidon_a_vider: bool

    def en_dict(self) -> dict:
        return asdict(self)


class Air:
    def __init__(
        self,
        reglages: ReglagesAir,
        materiel: Materiel,
        fichier: Path | None = None,
        air_permis: Callable[[], bool] = lambda: True,
        horloge: Callable[[], float] = time.monotonic,
        maintenant: Callable[[], datetime] = datetime.now,
    ) -> None:
        """`air_permis` : le compresseur peut-il tourner ? (Nettoyage.air_permis). `fichier` : où
        garder la date du dernier bidon vidé (None : nulle part)."""
        self.reglages = reglages
        self.materiel = materiel
        self.fichier = fichier
        self._air_permis = air_permis
        self._horloge = horloge
        self._maintenant = maintenant
        self._verrou = threading.RLock()
        self._commande: bool | None = None
        self._ferme_depuis: float | None = None
        self._erreur_vue = False
        self._bidon: datetime | None = None
        self._lire_bidon()

    # ------------------------------------------------------------ en fond

    def demarrer(self, arret: threading.Event) -> list[threading.Thread]:
        return [lancer_boucle(MODULE, self.reglages.periode_s, self.avancer, arret)]

    def avancer(self) -> None:
        """Ferme le relais quand l'air est permis, l'ouvre sinon ; compte l'attente."""
        voulu = bool(self._air_permis())
        with self._verrou:
            if self._commande is voulu:
                return
            if COMPRESSEUR not in self.materiel.branchements:
                self._noter_erreur(f"signal « {COMPRESSEUR} » absent de la liste : pas commandé")
                return
            try:
                self.materiel.ecrire(COMPRESSEUR, voulu)
            except (ErreurMateriel, KeyError) as erreur:
                self._noter_erreur(str(erreur))
                return
            self._erreur_vue = False
            self._commande = voulu
            # Chaque fermeture relance l'attente (coupure du Pi, nuit UV-ozone : cuve à refaire).
            self._ferme_depuis = self._horloge() if voulu else None
            journal.info(
                "Air : compresseur %s",
                "autorisé (attente de mise en pression)" if voulu else "coupé",
            )

    def _noter_erreur(self, message: str) -> None:
        if not self._erreur_vue:
            journal.error("Air : %s", message)
            self._erreur_vue = True

    # ------------------------------------------------------------ permissions

    def reste_s(self) -> float:
        with self._verrou:
            if self._ferme_depuis is None:
                return 0.0
            ecoule = self._horloge() - self._ferme_depuis
            return max(self.reglages.attente_mise_en_pression_s - ecoule, 0.0)

    def en_pression(self) -> bool:
        with self._verrou:
            return self._commande is True and self.reste_s() <= 0

    def refus_geste(self, geste: str) -> str | None:
        """Pour `Chef.interdire` : pourquoi un geste « à l'air » est interdit (ou None)."""
        if geste not in GESTES_A_L_AIR:
            return None
        with self._verrou:
            if self._commande is not True:
                return "compresseur coupé (relais ouvert)"
            if self.reste_s() > 0:
                return f"air en mise en pression (encore {self.reste_s():.0f} s)"
        return None

    # ------------------------------------------------------------ le bidon de purge

    def _jours_depuis_bidon(self) -> int:
        if self._bidon is None:
            return 0
        return max((self._maintenant() - self._bidon).days, 0)

    def bidon_a_vider(self) -> bool:
        with self._verrou:
            return self._jours_depuis_bidon() >= self.reglages.rappel_bidon_jours

    def bidon_vide(self, qui: str = "écran") -> None:
        """L'opérateur a vidé le bidon : le rappel repart de zéro."""
        with self._verrou:
            self._bidon = self._maintenant()
            self._ecrire_bidon()
        journal.info("Air : bidon de purge vidé (%s)", qui)

    def _lire_bidon(self) -> None:
        """Premier démarrage (ou fichier illisible) : on compte à partir d'aujourd'hui."""
        if self.fichier is not None and self.fichier.exists():
            try:
                donnees = json.loads(self.fichier.read_text(encoding="utf-8"))
                self._bidon = datetime.fromisoformat(donnees["bidon_vide_le"])
                return
            except (OSError, ValueError, KeyError, TypeError) as erreur:
                journal.error(
                    "Air : fichier du bidon illisible (%s) : repart d'aujourd'hui", erreur
                )
        self._bidon = self._maintenant()
        self._ecrire_bidon()

    def _ecrire_bidon(self) -> None:
        if self.fichier is None or self._bidon is None:
            return
        try:
            self.fichier.parent.mkdir(parents=True, exist_ok=True)
            provisoire = self.fichier.with_suffix(".tmp")
            provisoire.write_text(
                json.dumps({"bidon_vide_le": self._bidon.isoformat()}), encoding="utf-8"
            )
            os.replace(provisoire, self.fichier)
        except OSError as erreur:
            journal.error("Air : date du bidon pas gardée dans %s : %s", self.fichier, erreur)

    # ------------------------------------------------------------ état et check-list

    def etat(self) -> EtatAir:
        with self._verrou:
            return EtatAir(
                compresseur=self._commande is True,
                en_pression=self.en_pression(),
                reste_s=round(self.reste_s(), 1),
                bidon_vide_le=None if self._bidon is None else self._bidon.isoformat(),
                bidon_jours=self._jours_depuis_bidon(),
                bidon_a_vider=self.bidon_a_vider(),
            )

    def constats(self) -> list[Constat]:
        """Pour la check-list de démarrage. Jamais bloquant : le réseau d'air est passif."""
        etat = self.etat()
        if etat.bidon_a_vider:
            return [
                Constat(
                    SUJET,
                    "attention",
                    f"bidon de purge pas vidé depuis {etat.bidon_jours} jours "
                    f"(rappel tous les {self.reglages.rappel_bidon_jours} jours)",
                    "Vider le bidon de 2 L au sol sous le bloc de traitement, puis appuyer sur "
                    "« bidon vidé » (page web, Air).",
                )
            ]
        return [Constat(SUJET, "ok", "rien à signaler")]


assert all(geste in GESTES_PROTEGES for geste in GESTES_A_L_AIR)
