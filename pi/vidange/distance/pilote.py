"""Pilotage manuel à distance (tâche 12), depuis la page web, en cas de problème.

    pilote = PiloteDistance(reglages.programme.distance, reglages.machine, liaisons, chef,
                            materiel, cameras.age, registre)
    pilote.demarrer(arret)                       # un fil : tour() tous les « periode_s »
    pilote.activer(qui)                          # mode à distance : la machine se met en pause
    pilote.tenir(qui, "exemple_x", 1, "plafond", 1234)   # redit tant que le bouton est tenu
    pilote.lacher(qui)                           # bouton lâché : arrêt tout de suite
    pilote.quitter(qui)
    pilote.reprendre_la_main("écran de l'armoire")   # action sur place : l'armoire gagne

Garde-fous logiciels (docs/decisions.md, « Accès à distance ») :
- le mode à distance s'active exprès ; il met la machine en pause (le chef d'orchestre ne fait
  plus rien) et refuse de s'activer pendant un geste du cycle ;
- un seul axe à la fois, à la vitesse plafond de programme.yaml, sans sortir de sa course
  (machine.yaml) ;
- « homme mort » : le mouvement ne dure que tant que la page redit « je tiens » ; il s'arrête
  si le bouton est lâché, si la connexion se coupe (plus de nouvelles depuis « homme_mort_s »),
  ou si la vidéo se fige (l'image que la page affiche est trop vieille). Après un arrêt qui
  n'est pas un bouton lâché, rien ne repart avant que le bouton soit lâché puis repris ;
- le mouvement est fait de petits déplacements manuels (« $J= ») : la carte n'a jamais plus de
  « avance_s » de mouvement d'avance, et même un Pi figé ne laisse pas un axe partir loin ;
- le voyant-buzzer sur place s'allume « voyant_avant_s » avant le premier mouvement, et reste
  allumé pendant (et un peu après) ; sans voyant, pas de mouvement ;
- priorité à l'armoire : un appui sur l'écran, une pause sur place (bouton de la carte), une
  alarme de carte, ou la machine reprise d'une autre façon terminent le mode à distance ;
- chaque action est notée dans le registre (qui, quand, quoi).
La sécurité câblée (arrêt d'urgence, portes) reste au-dessus de tout, et coupe aussi ce pilotage.
"""

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from vidange.chef import Chef
from vidange.chef.axes import MM_PAR_M
from vidange.fiabilite.constats import lancer_boucle
from vidange.fluidnc import Commande, ErreurFluidnc, EtatCarte, Liaison, protocole
from vidange.journal import donner_journal
from vidange.materiel import Materiel
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import Machine, ReglagesDistance

journal = donner_journal("distance")

# Le voyant et buzzer « attention » de l'armoire (docs/entrees-sorties.yaml, fonction 49).
SIGNAL_VOYANT = "voyant_buzzer"
SYSTEME = "programme du Pi"
# Écart (mm) sous lequel une carte arrêtée est « arrivée » à sa cible : les positions sont
# données au millième de mm.
ARRIVEE_MM = 0.01


class ErreurDistance(Exception):
    """Ordre de pilotage à distance refusé (avec la raison, en clair)."""


@dataclass
class _Mouvement:
    """Le mouvement en cours : un axe, un sens, tant que la page redit « je tiens »."""

    axe: str
    sens: int
    carte: str
    lettre: str
    qui: str
    # Heure (horloge du pilote) du dernier « je tiens », et image vue sur la page à ce moment.
    signe: float
    camera: str
    numero: int
    # Heure où il peut partir : voyant allumé depuis assez longtemps.
    depart: float
    lance: bool = False
    # Dernière position envoyée à la carte (mm), et la ligne qui l'a envoyée.
    cible_mm: float | None = None
    commande: Commande | None = None


class PiloteDistance:
    def __init__(
        self,
        reglages: ReglagesDistance,
        machine: Machine,
        liaisons: Mapping[str, Liaison],
        chef: Chef,
        materiel: Materiel | None,
        age_image: Callable[[str, int], float | None],
        registre: Registre | None = None,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.reglages = reglages
        self.machine = machine
        self.liaisons = dict(liaisons)
        self.chef = chef
        self.materiel = materiel
        self.registre = registre
        self._age_image = age_image
        self._horloge = horloge
        # Les axes qu'on peut piloter : les axes droits (en mètres) qui ont une carte FluidNC
        # reliée. Les axes en degrés ne sont pas pilotés à distance : rotation des têtes, et
        # brosses du lavage (verrou du noyau et de la couronne : jamais sans objet tenu).
        self.axes = {
            nom: axe
            for nom, axe in machine.axes.items()
            if axe.carte is not None
            and axe.lettre is not None
            and axe.carte in self.liaisons
            and axe.unite == "m"
        }
        self._vitesse_mm_min = reglages.vitesse_max_m_s * MM_PAR_M * 60
        self._pas_mm = reglages.vitesse_max_m_s * MM_PAR_M * reglages.avance_s

        self._verrou = threading.RLock()
        self._actif = False
        self._qui = ""
        self._depuis = ""
        self._activite = 0.0
        self._mouvement: _Mouvement | None = None
        # Cartes dont l'arrêt n'est pas encore sûr → dernière ligne envoyée.
        self._a_arreter: dict[str, Commande | None] = {}
        self._dernier_mouvement: float | None = None
        # Arrêt imposé (connexion, vidéo...) : il faut lâcher le bouton avant de repartir.
        self._relacher = False
        self._voyant = False
        self._voyant_allume_a: float | None = None
        # Dernière chose à dire sur la page (raison d'un arrêt, bout de course...).
        self.message = ""

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        return lancer_boucle("distance", self.reglages.periode_s, self.tour, arret)

    @property
    def actif(self) -> bool:
        return self._actif

    # ------------------------------------------------------------ ordres

    def refus(self) -> str | None:
        """Pourquoi le mode à distance ne peut pas s'activer maintenant (None : il peut)."""
        if self.materiel is None or SIGNAL_VOYANT not in self.materiel.branchements:
            return f"pas de voyant-buzzer « {SIGNAL_VOYANT} » (docs/entrees-sorties.yaml)"
        if not self.axes:
            return "aucun axe avec une carte FluidNC dans machine.yaml"
        gestes = [
            f"« {m.module} » (étape « {m.etape} »)"
            for m in self.chef.etat().modules
            if m.statut == "en_cours" and m.phase == "fin"
        ]
        if gestes:
            return f"un geste du cycle est en cours : {', '.join(gestes)}"
        return None

    def activer(self, qui: str) -> None:
        with self._verrou:
            if self._actif:
                return
            refus = self.refus()
            if refus is not None:
                self._noter(qui, "refus", f"activation : {refus}")
                raise ErreurDistance(f"Mode à distance impossible : {refus}.")
            # Le chef ne fait plus rien tant que le mode à distance dure.
            self.chef.pause()
            self._actif = True
            self._qui = qui
            self._depuis = datetime.now().astimezone().isoformat(timespec="seconds")
            self._activite = self._horloge()
            self._relacher = False
            self.message = ""
            journal.warning("Pilotage à distance activé par %s : machine en pause", qui)
            self._noter(qui, "activer", "machine mise en pause")

    def quitter(self, qui: str, raison: str = "demandé") -> None:
        with self._verrou:
            self._finir(qui, "quitter", raison)

    def reprendre_la_main(self, qui: str) -> None:
        """Une action sur place (écran de l'armoire...) : le pilotage à distance s'arrête."""
        with self._verrou:
            self._finir(qui, "reprise_sur_place", f"la main est reprise sur place ({qui})")

    def tenir(self, qui: str, axe: str, sens: int, camera: str, numero: int) -> None:
        """« Je tiens le bouton » : lance le mouvement, ou le fait durer. `camera` et `numero` :
        l'image que la page affiche en ce moment (la vidéo doit être en direct)."""
        with self._verrou:
            if not self._actif:
                raise ErreurDistance("Le mode à distance n'est pas activé.")
            if axe not in self.axes:
                raise ErreurDistance(f"Axe « {axe} » inconnu, ou sans carte FluidNC reliée.")
            if sens not in (-1, 1):
                raise ErreurDistance("Sens : 1 ou -1.")
            if self._relacher:
                raise ErreurDistance(f"{self.message} Lâcher le bouton, puis appuyer de nouveau.")
            maintenant = self._horloge()
            age = self._age_image(camera, numero)
            if age is None or age > self.reglages.video_figee_s:
                self._arreter_mouvement("vidéo figée sur la page")
                raise ErreurDistance(
                    f"Vidéo figée ou absente (caméra « {camera} ») : pas de mouvement sans la "
                    "vidéo en direct."
                )
            self._activite = maintenant
            mouvement = self._mouvement
            if mouvement is not None and (mouvement.axe, mouvement.sens) == (axe, sens):
                mouvement.signe, mouvement.camera, mouvement.numero = maintenant, camera, numero
                return
            if mouvement is not None:
                self._arreter_mouvement("changement d'axe ou de sens", imposer=False)
            self._allumer_voyant(maintenant)
            assert self._voyant_allume_a is not None
            depart = max(maintenant, self._voyant_allume_a + self.reglages.voyant_avant_s)
            reglage = self.axes[axe]
            assert reglage.carte is not None and reglage.lettre is not None
            self._mouvement = _Mouvement(
                axe, sens, reglage.carte, reglage.lettre, qui, maintenant, camera, numero, depart
            )
            self.message = ""

    def lacher(self, qui: str) -> None:
        with self._verrou:
            self._arreter_mouvement("bouton lâché", imposer=False)
            self._relacher = False

    def arreter(self) -> None:
        """Arrêt du programme : plus de mouvement, voyant éteint."""
        with self._verrou:
            self._finir(SYSTEME, "quitter", "arrêt du programme")
            for carte in self._a_arreter:
                self._annuler(carte)
            self._a_arreter.clear()
            self._regler_voyant(False)

    # ------------------------------------------------------------ ce qu'on sait

    def etat(self) -> dict[str, Any]:
        """Pour la page web."""
        with self._verrou:
            maintenant = self._horloge()
            mouvement = self._mouvement
            axes = []
            for nom, axe in self.axes.items():
                assert axe.carte is not None and axe.lettre is not None
                etat_carte = self.liaisons[axe.carte].etat
                position = etat_carte.positions.get(axe.lettre)
                axes.append(
                    {
                        "nom": nom,
                        "carte": axe.carte,
                        "course": list(axe.course),
                        "position": None if position is None else round(position / MM_PAR_M, 4),
                        "etat_carte": self._decrire_carte(etat_carte),
                    }
                )
            return {
                "actif": self._actif,
                "qui": self._qui if self._actif else "",
                "depuis": self._depuis if self._actif else "",
                "refus": None if self._actif else self.refus(),
                "message": self.message,
                "voyant": self._voyant,
                "mouvement": None
                if mouvement is None
                else {
                    "axe": mouvement.axe,
                    "sens": mouvement.sens,
                    "lance": mouvement.lance,
                    "depart_dans_s": round(max(mouvement.depart - maintenant, 0), 1),
                },
                "vitesse_max_m_s": self.reglages.vitesse_max_m_s,
                "battement_s": self.reglages.battement_s,
                "axes": axes,
            }

    @staticmethod
    def _decrire_carte(etat: EtatCarte) -> str:
        if not etat.connectee:
            return "non connectée"
        if etat.en_alarme and etat.alarme is not None:
            return protocole.decrire_alarme(etat.alarme)
        return protocole.decrire_etat(etat.etat) if etat.etat else "état inconnu"

    # ------------------------------------------------------------ chaque tour

    def tour(self) -> None:
        with self._verrou:
            maintenant = self._horloge()
            self._confirmer_arrets()
            if self._actif:
                inactif_s = maintenant - self._activite
                if not self.chef.en_pause:
                    self._finir(SYSTEME, "quitter", "la machine a été reprise")
                elif self._mouvement is None and inactif_s > self.reglages.inactivite_max_min * 60:
                    raison = f"aucun mouvement depuis {self.reglages.inactivite_max_min:g} min"
                    self._finir(SYSTEME, "quitter", raison)
                elif self._mouvement is not None:
                    self._suivre(self._mouvement, maintenant)
            apres = self._dernier_mouvement
            self._regler_voyant(
                self._mouvement is not None
                or bool(self._a_arreter)
                or (
                    self._actif
                    and apres is not None
                    and maintenant - apres < self.reglages.voyant_apres_s
                )
            )

    def _suivre(self, m: _Mouvement, maintenant: float) -> None:
        if maintenant - m.signe > self.reglages.homme_mort_s:
            self._arreter_mouvement(
                f"plus de nouvelles de la page depuis {self.reglages.homme_mort_s:g} s "
                "(bouton lâché ou connexion coupée)"
            )
            return
        age = self._age_image(m.camera, m.numero)
        if age is None or age > self.reglages.video_figee_s:
            self._arreter_mouvement("vidéo figée sur la page")
            return
        liaison = self.liaisons[m.carte]
        etat = liaison.etat
        if not m.lance:
            self._lancer(m, liaison, etat, maintenant)
            return
        if not etat.connectee:
            self._arreter_mouvement(f"carte « {m.carte} » coupée")
            return
        if etat.en_alarme or (etat.etat or "").startswith(("Hold", "Door")):
            # Pause, porte ou arrêt sur place (ou alarme de la carte) : l'armoire reprend la main.
            self._finir(
                f"carte « {m.carte} »",
                "reprise_sur_place",
                f"carte « {m.carte} » {self._decrire_carte(etat)}",
            )
            return
        commande = m.commande
        if commande is not None and not commande.finie:
            return
        if commande is not None and commande.erreur is not None:
            self._arreter_mouvement(f"refusé par la carte « {m.carte} » : {commande.erreur}")
            return
        position = etat.positions.get(m.lettre)
        if position is None:
            self._arreter_mouvement(f"position de l'axe « {m.axe} » inconnue")
            return
        if (
            commande is not None
            and m.cible_mm is not None
            and etat.etat == "Idle"
            and etat.rapports_recus > commande.rapports_a_la_reponse
            and abs(m.cible_mm - position) > ARRIVEE_MM
        ):
            # Arrêtée avant sa cible sans qu'on le demande : pause sur place (sur FluidNC, une
            # pause annule le déplacement manuel).
            carte = f"carte « {m.carte} »"
            self._finir(carte, "reprise_sur_place", f"{carte} arrêtée sur place")
            return
        self._avancer(m, liaison, position)

    def _lancer(self, m: _Mouvement, liaison: Liaison, etat: EtatCarte, maintenant: float) -> None:
        if maintenant < m.depart or m.carte in self._a_arreter:
            return
        if (
            etat.connectee
            and (etat.etat or "").startswith("Hold")
            and etat.lignes_en_cours == 0
            and not etat.en_alarme
        ):
            # Carte figée par la pause de la machine, sans geste en cours (tous les gestes
            # finissent par une attente de leur fin) : on la remet au repos.
            self._reprendre_carte(m.carte, liaison)
            return
        if not (etat.connectee and etat.etat == "Idle" and etat.lignes_en_cours == 0):
            probleme = self._decrire_carte(etat)
            if etat.lignes_en_cours:
                probleme += f", un geste du cycle est en cours ({etat.lignes_en_cours} ligne(s))"
            self._arreter_mouvement(f"carte « {m.carte} » pas prête : {probleme}")
            return
        position = etat.positions.get(m.lettre)
        if position is None:
            self._arreter_mouvement(f"position de l'axe « {m.axe} » inconnue")
            return
        m.lance = True
        self._dernier_mouvement = maintenant
        sens = "+" if m.sens > 0 else "-"
        detail = f"{m.axe} vers {sens}, depuis {position / MM_PAR_M:.4f} m"
        journal.warning("Mouvement à distance (%s) : %s", m.qui, detail)
        self._noter(m.qui, "mouvement", detail)
        self._avancer(m, liaison, position)

    def _reprendre_carte(self, carte: str, liaison: Liaison) -> None:
        try:
            liaison.reprendre()
        except ErreurFluidnc as erreur:
            journal.error("Carte « %s » : %s", carte, erreur)

    def _avancer(self, m: _Mouvement, liaison: Liaison, position: float) -> None:
        """Donne à la carte un peu plus de mouvement, sans dépasser « avance_s » d'avance."""
        self._dernier_mouvement = self._horloge()
        if m.cible_mm is not None and (m.cible_mm - position) * m.sens > self._pas_mm / 2:
            return
        debut, fin = (borne * MM_PAR_M for borne in self.axes[m.axe].course)
        if m.sens > 0:
            cible = min(position + self._pas_mm, fin)
        else:
            cible = max(position - self._pas_mm, debut)
        depuis = position if m.cible_mm is None else m.cible_mm
        if (cible - depuis) * m.sens <= ARRIVEE_MM:
            self.message = f"axe « {m.axe} » au bout de sa course (machine.yaml)"
            return
        m.cible_mm = cible
        m.commande = liaison.deplacer_manuel({m.lettre: cible}, self._vitesse_mm_min)

    # ------------------------------------------------------------ arrêts

    def _arreter_mouvement(self, raison: str, imposer: bool = True) -> None:
        """Arrête le mouvement. `imposer` : arrêt qui ne vient pas de la page (connexion,
        vidéo, carte...) ; il faudra lâcher le bouton avant de repartir."""
        m = self._mouvement
        if m is None:
            return
        self._mouvement = None
        self._relacher = imposer
        self.message = f"Arrêt : {raison}."
        if not m.lance:
            return
        self._annuler(m.carte)
        self._a_arreter[m.carte] = m.commande
        self._dernier_mouvement = self._horloge()
        position = self.liaisons[m.carte].etat.positions.get(m.lettre)
        ou = "inconnue" if position is None else f"{position / MM_PAR_M:.4f} m"
        detail = f"{m.axe} arrêté : {raison} (position {ou})"
        journal.warning("Mouvement à distance arrêté : %s", detail)
        self._noter(m.qui, "arret", detail)

    def _annuler(self, carte: str) -> None:
        try:
            self.liaisons[carte].annuler_deplacement()
        except ErreurFluidnc as erreur:
            journal.debug("Carte « %s » : annulation impossible (%s)", carte, erreur)

    def _confirmer_arrets(self) -> None:
        """Une ligne partie juste avant l'annulation peut encore faire bouger l'axe : on
        réannule tant que la carte est en déplacement manuel ou n'a pas répondu."""
        for carte, commande in list(self._a_arreter.items()):
            etat = self.liaisons[carte].etat
            en_cours = commande is not None and not commande.finie
            if etat.connectee and (etat.etat == "Jog" or en_cours):
                self._annuler(carte)
            else:
                del self._a_arreter[carte]

    def _finir(self, qui: str, action: str, raison: str) -> None:
        """Fin du mode à distance ; la machine reste en pause (rien ne repart sans Go)."""
        if not self._actif:
            return
        self._arreter_mouvement(f"fin du mode à distance ({raison})")
        self._actif = False
        self.message = f"Mode à distance terminé : {raison}. La machine reste en pause."
        journal.warning("Pilotage à distance terminé (%s) : %s", qui, raison)
        self._noter(qui, action, raison)

    # ------------------------------------------------------------ voyant et registre

    def _allumer_voyant(self, maintenant: float) -> None:
        if self._voyant:
            return
        if self.materiel is None or SIGNAL_VOYANT not in self.materiel.branchements:
            raise ErreurDistance(
                f"Pas de voyant-buzzer « {SIGNAL_VOYANT} » : pas de mouvement à distance."
            )
        try:
            self.materiel.ecrire(SIGNAL_VOYANT, True)
        except Exception as erreur:
            raise ErreurDistance(
                f"Voyant-buzzer impossible à allumer ({erreur}) : pas de mouvement à distance."
            ) from None
        self._voyant = True
        self._voyant_allume_a = maintenant

    def _regler_voyant(self, voulu: bool) -> None:
        if voulu == self._voyant or self.materiel is None:
            return
        try:
            self.materiel.ecrire(SIGNAL_VOYANT, voulu)
        except Exception as erreur:
            journal.error("Voyant-buzzer : commande impossible (%s)", erreur)
            if voulu:
                self._arreter_mouvement("voyant-buzzer en panne")
            return
        self._voyant = voulu
        self._voyant_allume_a = self._horloge() if voulu else None

    def _noter(self, qui: str, action: str, detail: str) -> None:
        if self.registre is None:
            return
        try:
            self.registre.noter_action_distance(qui, action, detail)
        except ErreurRegistre as erreur:
            journal.error("Action à distance pas notée dans le registre : %s", erreur)
