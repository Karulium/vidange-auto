"""Le Spray, côté Pi (fiche v5.8 du 01/11/2026, module gelé ; tâche 39).

La carte ESP32 n° 5 fait le travail fin (pompe jusqu'au poids perdu, électrovannes, bras) ; le Pi
lui donne des ordres et lit ses réponses en Modbus (table : spray/README.md,
vidange.materiel.carte_spray), puis décide.

    spray = Spray(reglages.machine, materiel, registre, refus_chariot=remplissage.refus_bras_spray)
    spray.observer()             # en fond : lit la carte, bat, agitateurs, porte du spray
    spray.bras_spray_sorti()     # pour le Remplissage : True tant que la carte n'a pas redit
                                 # « bras rangé » (carte muette comprise)
    spray.preparer("S1293", "seau_a")  # flacon, dose, réserve ; agitateurs avant la dose
    spray.sortir() ; spray.bras_sorti()
    spray.pulveriser() ; spray.pulverisation_finie()
    spray.ranger() ; spray.bras_range()
    spray.noter()                # registre du seau : emplacement, dose, poids perdu, amorce
    spray.nettoyer() ; spray.nettoyage_fini()   # nettoyage des tubes (fin de journée)
    spray.confirmer_cartouche(2) # nouvelle cartouche à l'emplacement 2 : amorce au 1er seau
    spray.continuer_sans_spray() # choix de Karulium après une erreur du spray

Les gestes du chef sont dans vidange.spray.module (un seau, le nettoyage des tubes).

Règle d'or : **tant que la carte n'a pas redit « bras rangé », le bras est supposé sorti**
(`bras_spray_sorti`) : le chariot de remplissage ne bouge ni en hauteur, ni ses barres, ni en y ;
seule la rotation du seau est permise (vidange.remplissage.regles). C'est vrai aussi quand la
carte se tait, et entre l'envoi d'un « sortir » et la réponse de la carte.

Une erreur du spray (carte muette, balance muette, flacon presque vide, cartouche pas confirmée)
met le seau « sans spray » : l'écran propose de continuer sans spray (`continuer_sans_spray`) ou
d'attendre (réparer, puis acquitter). Une dose pas atteinte, trop forte ou interrompue est notée
et alertée, le cycle continue. Seul un bras pas rangé arrête tout (le chariot ne peut plus bouger).

Le spray ne protège personne, et rien ici ne le fait : arrêt d'urgence, store et porte de la boîte
(chaîne UV-ozone) sont câblés. La règle du bras (règle 6) protège la machine.
"""

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from vidange.chef import ErreurEtape
from vidange.entrees_sorties import CARTE_SPRAY, EntreesSorties
from vidange.fiabilite.constats import Constat, lancer_boucle
from vidange.journal import donner_journal
from vidange.materiel import ErreurMateriel, Materiel
from vidange.materiel import carte_spray as table
from vidange.materiel.carte_spray import EtatSpray
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import Machine
from vidange.reglages import Spray as ReglagesSpray

journal = donner_journal("spray")

MODULE = "spray"
SUJET = "spray"
# Geste protégé du chef : pas de spray de culture dans un seau ouvert pendant la purge.
GESTE = "spray_seau"

QUOI_FAIRE = (
    "Regarder la boîte du spray et son bras sur le chariot. Pour continuer sans spray : bouton "
    "« Sans spray », puis acquitter et donner le Go (le seau sera noté « sans spray »). Pour "
    "attendre : régler le problème, puis acquitter et donner le Go."
)
QUOI_FAIRE_BRAS = (
    "Bras du spray pas rangé : regarder sur place (bras bloqué, capteur « bras rangé » sale ou "
    "débranché). Le chariot de remplissage reste immobile tant que la carte ne voit pas le bras "
    "rangé. Ranger le bras à la main si besoin, puis acquitter et donner le Go."
)
QUOI_FAIRE_CARTE = (
    "Carte du spray muette : vérifier son alimentation 24 V, le câble c_spray et l'adaptateur "
    "USB-RS485. Le bras est supposé sorti : le chariot de remplissage reste immobile."
)

Issue = Literal["faite", "trop_forte", "incomplete", "interrompue", "sans_spray"]
TEXTES_ISSUE = {
    "faite": "dose faite",
    "trop_forte": "dose trop forte",
    "incomplete": "dose incomplète",
    "interrompue": "spray interrompu",
    "sans_spray": "sans spray",
}


# Signal de la porte de la boîte (contact 24 V lu par le Pi : informe et fait attendre).
PORTE = "porte_spray"


def verifier_avec_liste(reglages: ReglagesSpray, liste: EntreesSorties) -> list[str]:
    """Au démarrage : le signal de la carte du spray existe, avec « appareil: carte_spray »."""
    signal = liste.signaux.get(reglages.signal)
    if signal is None or signal.appareil != CARTE_SPRAY:
        return [
            f"machine.yaml → spray → signal : « {reglages.signal} » doit être dans "
            "entrees-sorties.yaml, avec « appareil: carte_spray »"
        ]
    return []


class ErreurSpray(ErreurEtape):
    """Une erreur du spray : le module part en alarme avec ce message."""

    def __init__(self, message: str, quoi_faire: str = QUOI_FAIRE) -> None:
        super().__init__(f"spray : {message}", quoi_faire)


@dataclass(frozen=True)
class DoseSeau:
    """Ce qui est prévu pour un seau."""

    seau: str | None
    format: str
    emplacement: int
    dose_g: float
    # Amorce après un changement de cartouche (0 sinon), ajoutée à la dose, notée à part.
    amorce_g: float = 0.0

    @property
    def total_g(self) -> float:
        return self.dose_g + self.amorce_g


@dataclass(frozen=True)
class ConsigneSpray:
    """Ce qu'un plan d'essais demande pour un seau (tâche 31) : une autre dose (`dose_g`), ou pas
    de spray (`sans_spray` : la raison notée). Rien : la dose normale du format."""

    dose_g: float | None = None
    sans_spray: str | None = None


@dataclass(frozen=True)
class ResultatSpray:
    seau: str | None
    dose: DoseSeau | None
    issue: Issue
    perdue_g: float = 0.0
    duree_s: float = 0.0
    raison: str = ""

    @property
    def texte(self) -> str:
        texte = TEXTES_ISSUE[self.issue]
        return f"{texte} ({self.raison})" if self.raison else texte


class Spray:
    def __init__(
        self,
        machine: Machine,
        materiel: Materiel,
        registre: Registre | None = None,
        fichier: Path | None = None,
        horloge: Callable[[], float] = time.monotonic,
        # Règle 6 du Remplissage (plateau assez bas, barres ouvertes) :
        # Remplissage.refus_bras_spray.
        refus_chariot: Callable[[], str | None] = lambda: "chariot de remplissage pas branché",
        # Porte de la boîte du spray ouverte (signal porte_spray ; None : illisible).
        porte_ouverte: Callable[[], bool | None] = lambda: False,
        # Le seau tourne de tant de degrés (Remplissage.tourner_pour_spray).
        tourner_seau: Callable[[float], object] = lambda degres: None,
        # Chef.permission(GESTE) : None = permis (pas de purge en cours).
        permission: Callable[[str], str | None] = lambda geste: None,
        # Culture de cet emplacement connue (lien QR de la cartouche ↔ emplacement fait par le
        # logiciel de culture ; case vide en attendant : toujours connue).
        culture_connue: Callable[[int], bool] = lambda emplacement: True,
    ) -> None:
        assert machine.spray is not None
        self.reglages = machine.spray
        self.durees = machine.durees
        self.materiel = materiel
        self.registre = registre
        self.signal = machine.spray.signal
        self._fichier = fichier
        self._horloge = horloge
        self._refus_chariot = refus_chariot
        self._porte_ouverte = porte_ouverte
        self._tourner_seau = tourner_seau
        self._permission = permission
        self._culture_connue = culture_connue
        self._verrou = threading.RLock()
        # Dernière lecture réussie de la carte, et quand.
        self.etat: EtatSpray | None = None
        self._lu_a: float | None = None
        self.erreur: str | None = "carte du spray pas encore lue"
        self._demarrages: int | None = None
        self._poids_avant: list[float | None] = [None] * table.NB_FLACONS
        # Ordres : dernier numéro envoyé, son code, et s'il faut attendre que la carte l'ait vu.
        self._numero = 0
        self._ordre_code = 0
        self._ordre_vu = True
        # Un « sortir » envoyé, pas encore vu par la carte : le bras est peut-être en route.
        self._sortie_en_route = False
        self._battement = 0
        self._battu_a = -1e9
        # Geste en cours (le Pi bat pendant ce temps).
        self.geste: str | None = None
        self.dose: DoseSeau | None = None
        self.resultat: ResultatSpray | None = None
        self._numero_dose_avant: int | None = None
        self._angle_demande: float | None = None
        self._ranger_essais = 0
        self._ranger_depuis = 0.0
        self._agitation_depuis: float | None = None
        self._agite_a = -1e9
        self._interruption: str | None = None
        self._sans_spray = False
        self.messages: list[str] = []
        # Gardé dans le fichier (reprise après coupure) : cartouches à confirmer, amorces dues,
        # nettoyages depuis le dernier plein d'alcool.
        self.a_confirmer: set[int] = set()
        self.amorces: set[int] = set()
        self.nettoyages = 0
        self._charger()

    # ------------------------------------------------------------ fichier

    def _charger(self) -> None:
        if self._fichier is None or not self._fichier.exists():
            return
        try:
            donnees = json.loads(self._fichier.read_text(encoding="utf-8"))
            self.a_confirmer = {int(n) for n in donnees.get("a_confirmer", [])}
            self.amorces = {int(n) for n in donnees.get("amorces", [])}
            self.nettoyages = int(donnees.get("nettoyages", 0))
        except (OSError, ValueError, TypeError, AttributeError) as erreur:
            journal.error(
                "Spray : fichier %s illisible (%s) : repris à zéro", self._fichier, erreur
            )

    def _sauver(self) -> None:
        if self._fichier is None:
            return
        donnees = {
            "a_confirmer": sorted(self.a_confirmer),
            "amorces": sorted(self.amorces),
            "nettoyages": self.nettoyages,
        }
        try:
            self._fichier.parent.mkdir(parents=True, exist_ok=True)
            provisoire = self._fichier.with_suffix(".tmp")
            provisoire.write_text(json.dumps(donnees), encoding="utf-8")
            os.replace(provisoire, self._fichier)
        except OSError as erreur:
            journal.error("Spray : fichier %s impossible à écrire (%s)", self._fichier, erreur)

    # ------------------------------------------------------------ lire la carte

    def lire(self) -> EtatSpray | None:
        """Une lecture de la carte. None si elle ne répond pas (l'erreur est dans `erreur`)."""
        with self._verrou:
            try:
                etat = self.materiel.lire_spray(self.signal)
            except ErreurMateriel as erreur:
                if self.erreur != str(erreur):
                    journal.warning("Spray : %s", erreur)
                self.erreur = str(erreur)
                return None
            self.erreur = None
            if self._demarrages is not None and etat.demarrages != self._demarrages:
                self._dire(
                    "La carte du spray a redémarré : prise d'origine du bras à refaire.", True
                )
            self._demarrages = etat.demarrages
            if not self._ordre_vu and etat.numero_ordre == self._numero:
                self._ordre_vu = True
                self._sortie_en_route = False
            if self._numero == 0:
                self._numero = etat.numero_ordre
            self._suivre_flacons(etat)
            if (
                self.etat is not None
                and etat.erreurs & table.ERREUR_BRAS_POUSSE
                and not self.etat.erreurs & table.ERREUR_BRAS_POUSSE
            ):
                self._dire("Bras du spray poussé (capteur « bras rangé » perdu sans ordre).", True)
            self.etat = etat
            self._lu_a = self._horloge()
            return etat

    def muette(self) -> bool:
        """Pas de lecture réussie depuis liaison → muette_s."""
        with self._verrou:
            if self._lu_a is None:
                return True
            return self._horloge() - self._lu_a > self.reglages.liaison.muette_s

    def brancher_chariot(
        self, refus_chariot: Callable[[], str | None], tourner_seau: Callable[[float], object]
    ) -> None:
        """Le chariot du lot (programme principal, tâche 45 quater) : le Spray est construit au
        démarrage, le Remplissage avec le lot (Remplissage.refus_bras_spray et
        tourner_pour_spray)."""
        with self._verrou:
            self._refus_chariot = refus_chariot
            self._tourner_seau = tourner_seau

    def bras_spray_sorti(self) -> bool:
        """Pour le Remplissage : False seulement quand la carte vient de dire « bras rangé »
        (capteur), bras arrêté, et qu'aucun « sortir » n'est en route. Carte muette : True."""
        with self._verrou:
            etat = self.etat
            if etat is None or self.muette() or self._sortie_en_route:
                return True
            return not (etat.bras_range and not etat.bras_bouge)

    def _suivre_flacons(self, etat: EtatSpray) -> None:
        """Le poids d'un emplacement monte beaucoup : nouvelle cartouche ? (à confirmer)."""
        seuil = self.reglages.flacons.changement_min_g
        for i, flacon in enumerate(etat.flacons):
            if flacon.muette or flacon.instable:
                continue
            avant = self._poids_avant[i]
            n = i + 1
            if avant is not None and flacon.grammes - avant >= seuil and n not in self.a_confirmer:
                self.a_confirmer.add(n)
                self._sauver()
                self._dire(
                    f"Nouvelle cartouche à l'emplacement {n} ? (+{flacon.grammes - avant:.0f} g) "
                    "À confirmer à l'écran.",
                    True,
                )
            self._poids_avant[i] = flacon.grammes

    # ------------------------------------------------------------ ordres

    def _ecrire(self, registre: int, valeurs: list[int]) -> None:
        try:
            self.materiel.ecrire_spray(self.signal, registre, valeurs)
        except ErreurMateriel as erreur:
            self.erreur = str(erreur)
            raise ErreurSpray(f"carte muette ({erreur})", QUOI_FAIRE_CARTE) from None

    def battre(self) -> None:
        """Un battement (la carte s'arrête seule si le Pi se tait plus de silence_max_s)."""
        with self._verrou:
            self._battement = (self._battement + 1) & 0xFFFF
            self._ecrire(table.REGISTRE_BATTEMENT, [self._battement])
            self._battu_a = self._horloge()

    def _ordre(self, code: int, parametre_1: int = 0, parametre_2: int = 0) -> None:
        with self._verrou:
            self._numero = (self._numero + 1) & 0xFFFF or 1
            self._ordre_code = code
            self._ordre_vu = False
            if code == table.ORDRE_SORTIR:
                self._sortie_en_route = True
            self._ecrire(
                table.REGISTRE_ORDRE, table.ordre(code, self._numero, parametre_1, parametre_2)
            )
            journal.debug(
                "Spray : ordre %d (%d, %d) n° %d", code, parametre_1, parametre_2, self._numero
            )

    def _etat_frais(self) -> EtatSpray:
        etat = self.lire()
        if etat is None:
            if self.muette():
                raise ErreurSpray(f"carte muette ({self.erreur})", QUOI_FAIRE_CARTE)
            assert self.etat is not None
            return self.etat
        return etat

    def _refus_de_l_ordre(self, etat: EtatSpray) -> str | None:
        """La carte a refusé notre dernier ordre : pourquoi."""
        if etat.numero_ordre == self._numero and etat.suite_ordre == table.SUITE_REFUSE:
            return etat.raison_du_refus
        return None

    # ------------------------------------------------------------ en fond

    def demarrer(self, arret: threading.Event) -> list[threading.Thread]:
        return [lancer_boucle(MODULE, self.reglages.liaison.battement_s / 2, self.observer, arret)]

    def observer(self) -> None:
        """En fond : lit la carte, bat pendant un geste (ou bras pas rangé), agitateurs toutes les
        periode_s, porte de la boîte ouverte pendant un spray ⇒ arrêt immédiat."""
        with self._verrou:
            etat = self.lire()
            if etat is None:
                return
            maintenant = self._horloge()
            actif = (
                self.geste is not None
                or not etat.bras_range
                or etat.bras_bouge
                or etat.spray_en_cours
                or etat.nettoyage_en_cours
            )
            try:
                if actif and maintenant - self._battu_a >= self.reglages.liaison.battement_s:
                    self.battre()
                if (etat.spray_en_cours or etat.nettoyage_en_cours) and self._porte_ouverte():
                    if self._interruption is None:
                        self._interruption = "porte du spray ouverte"
                        self._ordre(table.ORDRE_ARRET)
                        self._dire(
                            "Porte du spray ouverte pendant un spray : pompe et air arrêtés."
                        )
                agitateurs = self.reglages.agitateurs
                if (
                    self.geste is None
                    and maintenant - self._agite_a >= agitateurs.periode_s
                    and not etat.spray_en_cours
                ):
                    self._ordre(
                        table.ORDRE_AGITER, agitateurs.vitesse_pct, round(agitateurs.duree_s)
                    )
                    self._agite_a = maintenant
            except ErreurSpray as erreur:
                journal.warning("%s", erreur)

    # ------------------------------------------------------------ prêt ?

    def refus_carte(self, origine: bool = True) -> str | None:
        """La carte répond, avec la bonne table ; origine du bras faite ; pas d'erreur du bras."""
        with self._verrou:
            if self.muette():
                return f"carte du spray muette ({self.erreur})"
            assert self.etat is not None
            if origine and not self.etat.origine_faite:
                return "prise d'origine du bras du spray pas faite"
            erreurs = self.etat.erreurs_du_bras()
            if erreurs:
                return "bras du spray : " + ", ".join(erreurs)
            return None

    def carte_repond(self) -> bool:
        self.lire()
        return not self.muette()

    def lancer_origine(self) -> None:
        """Démarrage (geste a 0) : le bras tourne vers « rangé » jusqu'au capteur (0°)."""
        with self._verrou:
            etat = self._etat_frais()
            self.geste = "origine"
            if etat.erreurs & 0xFF00:
                self._ordre(table.ORDRE_EFFACER)
            self.battre()
            self._ordre(table.ORDRE_ORIGINE)

    def origine_faite(self) -> bool:
        with self._verrou:
            etat = self._etat_frais()
            refus = self._refus_de_l_ordre(etat)
            if refus is not None:
                raise ErreurSpray(f"prise d'origine refusée par la carte ({refus})")
            if not self._ordre_vu or etat.bras_bouge:
                return False
            if etat.erreurs & table.ERREUR_BRAS_PAS_RANGE or not etat.bras_range:
                raise ErreurSpray("bras pas vu rangé à la prise d'origine", QUOI_FAIRE_BRAS)
            muettes = [str(i + 1) for i, f in enumerate(etat.flacons) if f.muette]
            if muettes:
                self._dire(f"Balances du spray muettes : {', '.join(muettes)}.", True)
            self.geste = None
            return etat.origine_faite

    # ------------------------------------------------------------ un seau : a)

    def continuer_sans_spray(self) -> None:
        """Choix de Karulium à l'écran après une erreur : le seau en cours sera « sans spray »."""
        with self._verrou:
            self._sans_spray = True

    def confirmer_cartouche(self, emplacement: int) -> None:
        """Karulium confirme la nouvelle cartouche : l'emplacement resservira, avec une amorce
        à sa première dose."""
        with self._verrou:
            self.a_confirmer.discard(emplacement)
            if self.reglages.dose.amorce_g > 0:
                self.amorces.add(emplacement)
            self._sauver()
            self._dire(f"Cartouche de l'emplacement {emplacement} confirmée.")

    def refus_dose(
        self, format: str, dose_g: float | None = None
    ) -> tuple[DoseSeau | None, str | None]:
        """La dose de ce format (ou `dose_g`, celle d'un plan d'essais), et pourquoi elle est
        impossible (ou None)."""
        reglages = self.reglages
        if format not in reglages.dose.par_format_g:
            return None, f"format de seau inconnu du spray « {format} »"
        n = reglages.dose.emplacement_par_format[format]
        dose = DoseSeau(
            None,
            format,
            n,
            reglages.dose.par_format_g[format] if dose_g is None else dose_g,
            reglages.dose.amorce_g if n in self.amorces else 0.0,
        )
        refus = self.refus_carte()
        if refus is not None:
            return dose, refus
        assert self.etat is not None
        flacon = self.etat.flacons[n - 1]
        if flacon.muette:
            return dose, f"balance de l'emplacement {n} muette"
        if flacon.instable:
            return dose, f"balance de l'emplacement {n} instable"
        if n in self.a_confirmer:
            return dose, f"nouvelle cartouche à l'emplacement {n} pas encore confirmée"
        if not self._culture_connue(n):
            return dose, f"culture de l'emplacement {n} inconnue (QR de la cartouche pas relié)"
        plancher = reglages.flacons.vide_g[n] + reglages.flacons.reserve_g
        if flacon.grammes - dose.total_g < plancher:
            self._dire(f"Cartouche {n} à changer (presque vide : {flacon.grammes:.0f} g).", True)
            return dose, f"cartouche {n} presque vide ({flacon.grammes:.0f} g) : la changer"
        return dose, None

    def preparer(
        self, seau: str | None, format: str, consigne: ConsigneSpray | None = None
    ) -> DoseSeau | None:
        """Étape 1 : emplacement, dose, réserve du flacon ; agitateurs avant la dose. Lève
        ErreurSpray si la dose est impossible (l'écran propose « sans spray » ou d'attendre) ;
        rend None si Karulium a choisi « sans spray » (le seau est noté ainsi). `consigne` : ce
        que demande un plan d'essais accepté (une autre dose, ou pas de spray)."""
        with self._verrou:
            self.resultat, self.dose, self._interruption = None, None, None
            self._agitation_depuis = None
            if consigne is not None and consigne.sans_spray is not None:
                self._sans_spray = False
                self.resultat = ResultatSpray(seau, None, "sans_spray", raison=consigne.sans_spray)
                return None
            self.lire()
            dose_g = None if consigne is None else consigne.dose_g
            dose, refus = self.refus_dose(format, dose_g)
            if refus is None:
                refus = self._permission(GESTE)
            if self._sans_spray:
                self._sans_spray = False
                self.resultat = ResultatSpray(
                    seau, dose, "sans_spray", raison=refus or "choix de Karulium"
                )
                return None
            if refus is not None:
                raise ErreurSpray(f"pas de dose pour le seau {seau or '?'} : {refus}")
            assert dose is not None and self.etat is not None
            self.dose = DoseSeau(seau, format, dose.emplacement, dose.dose_g, dose.amorce_g)
            flacon = self.etat.flacons[dose.emplacement - 1]
            reste = flacon.grammes - self.reglages.flacons.vide_g[dose.emplacement]
            reste -= self.reglages.flacons.reserve_g
            if reste / dose.dose_g < self.reglages.flacons.alerte_doses_restantes + 1:
                self._dire(f"Cartouche {dose.emplacement} bientôt vide ({flacon.grammes:.0f} g).")
            agitateurs = self.reglages.agitateurs
            duree = agitateurs.avant_dose_s + self.durees.get("spray_dose_max", 60)
            self._ordre(table.ORDRE_AGITER, agitateurs.vitesse_pct, round(duree))
            self._agitation_depuis = self._agite_a = self._horloge()
            return self.dose

    def agitation_faite(self) -> bool:
        """Les agitateurs ont tourné avant_dose_s avant la dose."""
        with self._verrou:
            debut = self._agitation_depuis
            if debut is None:
                return True
            return self._horloge() - debut >= self.reglages.agitateurs.avant_dose_s

    def refus_sortie(self) -> str | None:
        """Le bras peut-il sortir ? Carte prête, bras rangé, porte fermée, pas de purge, et la
        règle 6 du Remplissage (plateau assez bas, barres ouvertes)."""
        with self._verrou:
            refus = self.refus_carte()
            if refus is not None:
                return refus
            if self.bras_spray_sorti():
                return "bras du spray pas vu rangé"
            porte = self._porte_ouverte()
            if porte is None:
                return "porte du spray illisible"
            if porte:
                return "porte du spray ouverte"
            refus = self._permission(GESTE)
            if refus is not None:
                return refus
            return self._refus_chariot()

    def angle_du_format(self, format: str) -> float:
        return self.reglages.bras.angles[format]

    def sortir(self, format: str | None = None) -> None:
        """Étape 2 : ordre « sortir à l'angle du format ». Jamais sans la règle 6."""
        with self._verrou:
            format = format or (self.dose.format if self.dose is not None else None)
            if format is None:
                raise ErreurSpray("format du seau inconnu : le bras ne sort pas")
            self.lire()
            refus = self.refus_sortie()
            if refus is not None:
                raise ErreurSpray(f"le bras ne sort pas : {refus}")
            angle = self.angle_du_format(format)
            self.geste = "sortir"
            self._angle_demande = angle
            self.battre()
            self._ordre(table.ORDRE_SORTIR, round(angle * 10))

    def bras_sorti(self) -> bool:
        """Fin de l'étape 2 : la carte dit « bras sorti » à l'angle demandé."""
        with self._verrou:
            etat = self._etat_frais()
            refus = self._refus_de_l_ordre(etat)
            if refus is not None:
                raise ErreurSpray(f"sortie du bras refusée par la carte ({refus})")
            if not self._ordre_vu:
                return False
            if etat.erreurs & table.ERREUR_BRAS_PAS_SORTI:
                raise ErreurSpray("le bras n'est pas arrivé à son angle (bloqué ?)")
            if etat.bras_bouge or not etat.bras_sorti:
                return False
            assert self._angle_demande is not None
            if abs(etat.angle_deg - self._angle_demande) > self.reglages.bras.tolerance_deg:
                raise ErreurSpray(f"bras à {etat.angle_deg:g}° au lieu de {self._angle_demande:g}°")
            return True

    def pulveriser(self) -> None:
        """Étape 3 : ordre « spray emplacement N, dose D g » ; le seau tourne en même temps."""
        with self._verrou:
            dose = self.dose
            if dose is None:
                raise ErreurSpray("pas de dose préparée")
            etat = self._etat_frais()
            if self._porte_ouverte():
                raise ErreurSpray("porte du spray ouverte : pas de spray")
            self.geste = "spray"
            self._interruption = None
            self._numero_dose_avant = etat.dose.numero
            self.battre()
            self._ordre(table.ORDRE_SPRAY, dose.emplacement, round(dose.total_g * 10))
            self._tourner_seau(self.reglages.dose.rotation_seau_deg)

    def pulverisation_finie(self) -> bool:
        """Fin de l'étape 3 : la carte a fini la dose (chasse comprise) ; le résultat est classé
        (faite, trop forte, incomplète, interrompue) et alerté si besoin, sans arrêter le
        cycle. Porte ouverte : arrêt immédiat. Carte muette : alarme."""
        self.observer()
        with self._verrou:
            etat = self._etat_frais()
            refus = self._refus_de_l_ordre(etat)
            if refus is not None:
                raise ErreurSpray(f"spray refusé par la carte ({refus})")
            if not self._ordre_vu or etat.dose.numero == self._numero_dose_avant:
                return False
            if etat.spray_en_cours:
                return False
            self.resultat = self._classer(etat)
            if self.resultat.issue != "faite":
                self._dire(
                    f"Seau {self.dose.seau if self.dose else '?'} : {self.resultat.texte}.", True
                )
            self.geste = None
            return True

    def _classer(self, etat: EtatSpray) -> ResultatSpray:
        dose = self.dose
        assert dose is not None
        perdue, duree = etat.dose.perdue_g, etat.dose.duree_s
        if self._interruption is not None or etat.dose.resultat == table.DOSE_INTERROMPUE:
            raison = self._interruption or "arrêt de la carte (silence du Pi ?)"
            return ResultatSpray(dose.seau, dose, "interrompue", perdue, duree, raison)
        if etat.dose.resultat == table.DOSE_TEMPS_MAX:
            raison = f"{perdue:.1f} g sur {dose.total_g:g} g en {duree:.1f} s (tube pincé, pompe ?)"
            return ResultatSpray(dose.seau, dose, "incomplete", perdue, duree, raison)
        if etat.dose.resultat == table.DOSE_REFUSEE:
            return ResultatSpray(
                dose.seau, dose, "sans_spray", 0.0, 0.0, "dose refusée par la carte"
            )
        if perdue > dose.total_g + self.reglages.dose.tolerance_trop_forte_g:
            raison = f"{perdue:.1f} g pour {dose.total_g:g} g demandés"
            return ResultatSpray(dose.seau, dose, "trop_forte", perdue, duree, raison)
        return ResultatSpray(dose.seau, dose, "faite", perdue, duree)

    def ranger(self) -> None:
        """Étape 4 : ordre « ranger »."""
        with self._verrou:
            self.geste = "ranger"
            self._ranger_essais = 1
            self._ranger_depuis = self._horloge()
            self.battre()
            self._ordre(table.ORDRE_RANGER)

    def bras_range(self) -> bool:
        """Fin de l'étape 4 : la carte dit « bras rangé » (capteur). Un seul nouvel essai
        automatique ; ensuite alarme forte (le chariot reste immobile)."""
        with self._verrou:
            etat = self._etat_frais()
            if self._ordre_vu and etat.bras_range and not etat.bras_bouge:
                self.geste = None
                return True
            delai = self.reglages.bras.temps_max_s + 2 * self.reglages.liaison.battement_s
            rate = bool(etat.erreurs & table.ERREUR_BRAS_PAS_RANGE)
            rate = rate or self._refus_de_l_ordre(etat) is not None
            if rate or self._horloge() - self._ranger_depuis > delai:
                if self._ranger_essais >= 2:
                    raise ErreurSpray("bras du spray pas rangé", QUOI_FAIRE_BRAS)
                self._ranger_essais += 1
                self._ranger_depuis = self._horloge()
                journal.warning("Spray : bras pas rangé, nouvel essai (un seul)")
                self._ordre(table.ORDRE_EFFACER)
                self._ordre(table.ORDRE_RANGER)
            return False

    def noter(self) -> ResultatSpray | None:
        """Étape 5 : le registre du seau (emplacement, dose demandée, poids perdu, amorce à part,
        durée) ; une amorce faite n'est plus due."""
        with self._verrou:
            resultat = self.resultat
            if resultat is None:
                return None
            dose = resultat.dose
            if dose is not None and resultat.issue in ("faite", "trop_forte", "incomplete"):
                if dose.amorce_g and dose.emplacement in self.amorces:
                    self.amorces.discard(dose.emplacement)
                    self._sauver()
            if self.registre is not None and resultat.seau is not None:
                try:
                    self._noter_registre(resultat)
                except ErreurRegistre as erreur:
                    journal.error("Spray : registre : %s", erreur)
            self.dose = None
            return resultat

    def _noter_registre(self, resultat: ResultatSpray) -> None:
        assert self.registre is not None
        seau, dose = resultat.seau, resultat.dose
        capteur = self.signal
        if dose is not None:
            self.registre.noter_mesure(
                "spray_emplacement", dose.emplacement, "", capteur=capteur, seau=seau
            )
            self.registre.noter_mesure(
                "spray_dose_demandee", dose.dose_g, "g", capteur=capteur, seau=seau
            )
        donne = resultat.perdue_g
        if dose is not None and dose.amorce_g and resultat.issue != "sans_spray":
            amorce = min(dose.amorce_g, max(donne, 0.0))
            self.registre.noter_mesure("spray_amorce", amorce, "g", capteur=capteur, seau=seau)
            donne -= amorce
        self.registre.noter_mesure("spray_dose", donne, "g", capteur=capteur, seau=seau)
        if resultat.duree_s:
            self.registre.noter_mesure(
                "spray_duree", resultat.duree_s, "s", capteur=capteur, seau=seau
            )
        if resultat.issue != "faite":
            self.registre.noter_alarme(
                MODULE, f"Seau {seau} : {resultat.texte}.", QUOI_FAIRE, etape="noter"
            )

    def arreter(self) -> None:
        """Arrêt du module (alarme, abandon) : arrêt immédiat de la carte (pompe, air,
        agitateurs ; le bras s'arrête où il est). Il reste « sorti » tant qu'il n'est pas vu
        rangé."""
        with self._verrou:
            self.geste = None
            try:
                self._ordre(table.ORDRE_ARRET)
            except ErreurSpray as erreur:
                journal.warning("%s", erreur)

    # ------------------------------------------------------------ nettoyage des tubes : b)

    def nettoyer(self) -> None:
        """Ordre « nettoyer » : la petite pompe envoie l'alcool, la chasse sèche la ligne."""
        with self._verrou:
            etat = self._etat_frais()
            if not etat.bras_sorti:
                raise ErreurSpray("nettoyage : le bras n'est pas sorti au-dessus du seau vide")
            self.geste = "nettoyage"
            self._numero_dose_avant = None
            self.battre()
            self._ordre(table.ORDRE_NETTOYER)

    def nettoyage_fini(self) -> bool:
        self.observer()
        with self._verrou:
            etat = self._etat_frais()
            refus = self._refus_de_l_ordre(etat)
            if refus is not None:
                raise ErreurSpray(f"nettoyage refusé par la carte ({refus})")
            if not self._ordre_vu or etat.nettoyage_en_cours:
                return False
            if etat.suite_ordre != table.SUITE_FAIT or self._interruption is not None:
                raise ErreurSpray(f"nettoyage interrompu ({self._interruption or 'carte'})")
            self.geste = None
            self.nettoyages += 1
            self._sauver()
            restants = self.nettoyages_restants()
            if restants <= self.reglages.nettoyage.alerte_nettoyages_restants:
                self._dire(
                    f"Alcool du nettoyage presque vide : {restants} nettoyages restants.", True
                )
            return True

    def nettoyages_restants(self) -> int:
        n = self.reglages.nettoyage
        return int(n.flacon_alcool_ml // n.alcool_par_nettoyage_ml) - self.nettoyages

    def alcool_rempli(self) -> None:
        """Karulium a refait le plein du flacon d'alcool."""
        with self._verrou:
            self.nettoyages = 0
            self._sauver()

    # ------------------------------------------------------------ messages

    def _dire(self, message: str, alerte: bool = False) -> None:
        if alerte:
            journal.warning("Spray : %s", message)
        else:
            journal.info("Spray : %s", message)
        self.messages.append(message)
        del self.messages[:-50]
        if alerte and self.registre is not None:
            try:
                self.registre.noter_alarme(MODULE, message, QUOI_FAIRE)
            except ErreurRegistre as erreur:
                journal.error("Spray : registre : %s", erreur)

    def en_dict(self) -> dict[str, Any]:
        """Pour la page web et l'API : ce que dit la carte, et ce qui attend Karulium."""
        with self._verrou:
            etat = self.etat
            return {
                "carte": None if self.muette() else "répond",
                "erreur": self.erreur,
                "bras_spray_sorti": self.bras_spray_sorti(),
                "angle_deg": None if etat is None else etat.angle_deg,
                "origine_faite": None if etat is None else etat.origine_faite,
                "flacons_g": None
                if etat is None
                else [None if f.muette else f.grammes for f in etat.flacons],
                "geste": self.geste,
                "a_confirmer": sorted(self.a_confirmer),
                "amorces": sorted(self.amorces),
                "nettoyages_restants": self.nettoyages_restants(),
                "dernier_resultat": None if self.resultat is None else self.resultat.texte,
                "messages": self.messages[-10:],
            }

    def constats(self) -> list[Constat]:
        """Pour la check-list de démarrage. Jamais bloquant : le spray ne protège personne."""
        self.lire()
        refus = self.refus_carte(origine=False)
        if refus is not None:
            return [Constat(SUJET, "attention", refus, QUOI_FAIRE_CARTE)]
        constats = []
        assert self.etat is not None
        if self.etat.exemple:
            constats.append(
                Constat(
                    SUJET, "attention", "programme de la carte fait avec des réglages d'exemple"
                )
            )
        muettes = [str(i + 1) for i, f in enumerate(self.etat.flacons) if f.muette]
        if muettes:
            constats.append(Constat(SUJET, "attention", f"balances muettes : {', '.join(muettes)}"))
        if self.a_confirmer:
            liste = ", ".join(str(n) for n in sorted(self.a_confirmer))
            constats.append(Constat(SUJET, "attention", f"cartouches à confirmer : {liste}"))
        return constats or [Constat(SUJET, "ok", "carte du spray prête")]
