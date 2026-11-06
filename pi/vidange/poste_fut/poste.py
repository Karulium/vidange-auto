"""Poste du fût : l'état du poste, le bouton « Prêt », son voyant, la pesée, le mode permis.

    poste = PosteFut(reglages.machine.poste_fut, materiel, registre, pesees=tour)
    poste.demarrer(arret)                     # relit les signaux et la pesée, en fond
    poste.etat()                              # EtatPoste : absent, en place, prêt ; poids...
    poste.appuyer_pret("page web")            # « Prêt » de l'écran ou de la page web
    poste.refus_lancement("production")       # pourquoi on ne peut pas lancer, ou None

Rien ne bouge seul au poste (tâche 17 bis) : le fût est posé debout sur le plateau entre les 4
cales, soupape enlevée et trou bouché ; Karulium roule le plateau contre les 2 butées d'angle du
fond, freine 2 roulettes, rabat le grand volet, lève le panneau long, puis appuie sur « Prêt ».
À la fin : volet relevé, freins desserrés, plateau sorti. Le Pi ne vérifie par capteur que le
plateau (inductif de la butée) et le panneau ; les autres gestes sont seulement rappelés.

États : plateau absent ; plateau en place mais pas prêt ; prêt. « Prêt » = plateau en place
+ plateau stable depuis `stabilite_s` + appui sur « Prêt » (bouton lumineux du poste, écran ou
page web). **La pesée n'entre pas dans « Prêt »** (décision du 05/11/2026). Le voyant du bouton
clignote tant que ce n'est pas prêt. Si le plateau n'est plus vu, le poste n'est plus prêt : la
surveillance (`surveillance`) met en alarme le module qui travaille au fût (la griffe).

La pesée du plateau est sans fil (boîte du poste sur le bus des pesées, `pesees`, un
TourPesees) : le poids est lu seulement griffe hors du fût. Plateau en place depuis
`delai_apres_plateau_s` et pas de poids ⇒ « pesée absente » : affichée, au journal, et une
alerte (une seule par absence) ; elle revient seule. **Jamais un refus ni un arrêt** : la griffe
trouve le fond au toucher. L'accu du plateau est surveillé (seuils de pesees.yaml,
`accu_plateau_fut`) : alertes « recharger le plateau », « pesée bientôt absente », « recharge
sans contact en panne ? ».

Au « Prêt », le cycle « vidange » du fût commence dans le registre, avec le poids du fût plein ;
sans pesée, il commence quand même, noté « sans pesée du fût » (mesure `sans_pesee_fut`). La
griffe (tâche 18) dit chaque dose (`noter_dose`) et la fin (`finir_vidange`).

Les alertes sont des alarmes du registre (à acquitter) : elles s'affichent à l'écran et sur la
page web, et partent avec le cycle. Elles n'arrêtent rien.

Rien ici ne protège personne : la sécurité est câblée. Le logiciel peut planter sans danger.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal

from vidange.chef import Condition
from vidange.fiabilite.constats import lancer_boucle
from vidange.journal import donner_journal
from vidange.materiel import ErreurMateriel, Materiel
from vidange.materiel.carte_pesee import Plateau
from vidange.poste_fut import regles
from vidange.poste_fut.pesee import SIGNAL as SIGNAL_PESEE
from vidange.poste_fut.pesee import PeseePlateau
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import PosteFut as ReglagesPosteFut

if TYPE_CHECKING:
    # Seulement pour les types : vidange.pesees importe la griffe, qui importe le poste du fût.
    from vidange.pesees.tour import TourPesees

journal = donner_journal("poste_fut")

PLATEAU = "plateau_fut_en_place"
PANNEAU = "reed_panneau_poste_fut"
BOUTON = "bouton_pret_fut"
VOYANT = "voyant_pret_fut"
MODULE = "poste_fut"

ABSENT, EN_PLACE, PRET = "absent", "en_place", "pret"
LIBELLES = {
    ABSENT: "Plateau du fût absent",
    EN_PLACE: "Plateau en place, pas prêt",
    PRET: "Prêt",
}
# Rappel à l'écran avant le « Prêt » : rien de cela n'est vérifié par un capteur.
GESTES = (
    "Poser le fût debout sur le plateau, entre les 4 cales",
    "Enlever la soupape du couvercle (trou bouché)",
    "Pousser le plateau contre les 2 butées d'angle du fond",
    "Freiner 2 roulettes",
    "Rabattre le grand volet, lever le panneau long",
    "Appuyer sur « Prêt »",
)
QUOI_FAIRE_PERTE = (
    "Le plateau du fût n'est plus vu au fond du poste. Le pont doit sortir de la zone du "
    "plateau. Remettre le plateau contre les 2 butées, freiner, appuyer sur « Prêt », "
    "puis acquitter et donner le Go."
)
QUOI_FAIRE_ABSENTE = (
    "Rien ne s'arrête : la vidange continue, la griffe trouve le fond au toucher, et les seaux "
    "sont notés « sans pesée du fût ». Regarder l'accu du plateau (le recharger par l'USB-C de "
    "secours), que le plateau est bien au fond, et la boîte du poste (pi/systeme/"
    "essai-poste-fut.md). La pesée revient seule."
)
QUOI_FAIRE_ACCU = (
    "Laisser le plateau au poste (recharge sans contact) ou le brancher sur l'USB-C de secours. "
    "Rien ne s'arrête ; accu vide, la pesée sera absente."
)
QUOI_FAIRE_RECHARGE = (
    "Le plateau est au poste mais ne se recharge pas : vérifier qu'il est bien poussé au fond "
    "(bobines face à face), le récepteur de la recharge sans contact et son câble ; en attendant, "
    "recharger par l'USB-C de secours."
)
MODES_DU_PANNEAU = {"production": "Production refusée", "lavage": "Lavage refusé"}
# Niveaux de l'accu du plateau (le plus grave à la fin).
ACCU_BON, ACCU_MOYEN, ACCU_RECHARGER, ACCU_BIENTOT_VIDE = range(4)
TEXTES_ACCU = {
    ACCU_BON: "",
    ACCU_MOYEN: "",
    ACCU_RECHARGER: "recharger le plateau",
    ACCU_BIENTOT_VIDE: "pesée bientôt absente : recharger le plateau",
}


class ErreurPoste(Exception):
    """« Prêt » refusé : le message dit ce qui manque."""


@dataclass(frozen=True)
class EtatPoste:
    etat: str
    libelle: str
    # Signaux lus (None : illisible).
    plateau: bool | None
    panneau_leve: bool | None
    # Plateau vu au fond, sans changement depuis `stabilite_s`.
    plateau_stable: bool
    # "" si la pesée donne un poids, sinon pourquoi pas (« pesée absente : ... »).
    pesee: str
    # La pesée est-elle « absente » (plateau en place depuis assez longtemps, pas de poids) ?
    pesee_absente: bool
    poids_lu_kg: float | None
    poids_net_kg: float | None
    # Accu et radio du plateau (dernière trame ; None si la radio ne parle pas).
    accu_v: float | None
    accu_pct: int | None
    en_recharge: bool | None
    signal_dbm: int | None
    # "" si l'accu va bien, sinon l'alerte en cours (« recharger le plateau »...).
    accu: str
    # Ce qui manque pour pouvoir appuyer sur « Prêt » (vide : c'est possible, ou déjà prêt).
    manque: tuple[str, ...]
    gestes: tuple[str, ...]
    # La vidange en cours (cycle du registre), poids du fût plein, somme des doses.
    cycle: int | None
    poids_plein_kg: float | None
    doses_kg: float
    # Le cycle a commencé sans pesée, ou une dose a été prise sans pesée.
    sans_pesee: bool
    # Derniers messages du poste (Prêt refusé, fût vide...), du plus ancien au plus récent.
    messages: tuple[str, ...]
    exemple_pesee: bool

    def en_dict(self) -> dict:
        return asdict(self)


class _Suivi:
    """Un signal, et depuis quand il n'a pas changé."""

    def __init__(self) -> None:
        self.valeur: bool | None = None
        self.depuis = 0.0

    def voir(self, valeur: bool | None, maintenant: float) -> bool:
        """Rend True si la valeur a changé."""
        if valeur == self.valeur:
            return False
        self.valeur, self.depuis = valeur, maintenant
        return True

    def stable(self, maintenant: float, duree: float) -> bool:
        return self.valeur is not None and maintenant - self.depuis >= duree


def _kg(valeur: float) -> str:
    return f"{valeur:.1f}".replace(".", ",")


def _v(millivolts: int) -> str:
    return f"{millivolts / 1000:.2f}".replace(".", ",")


class PosteFut:
    def __init__(
        self,
        reglages: ReglagesPosteFut,
        materiel: Materiel,
        registre: Registre | None = None,
        horloge: Callable[[], float] = time.monotonic,
        griffe_hors_fut: Callable[[], bool] = lambda: True,
        lecture_directe: bool = False,
        pesees: "TourPesees | None" = None,
    ) -> None:
        """`griffe_hors_fut` : la pesée n'est lue que si la griffe n'est pas dans le fût
        (rendu par le module Griffe). `lecture_directe` : pas de fil en fond, chaque `etat()`
        relit les signaux et interroge la pesée quand c'est l'heure (simulateur, tests).
        `pesees` : le tour des pesées du bus (sans lui, ou sans pesee_fut dans son tour : pas
        de pesée du fût, jamais d'alerte de pesée ; outils d'essai des autres modules)."""
        self.reglages = reglages
        self.materiel = materiel
        self.registre = registre
        if pesees is not None and SIGNAL_PESEE not in pesees.etats:
            pesees = None
        self.pesees = pesees
        self.pesee = None if pesees is None else PeseePlateau(reglages.pesee, pesees)
        self.griffe_hors_fut = griffe_hors_fut
        self._horloge = horloge
        self._lecture_directe = lecture_directe
        self._verrou = threading.RLock()
        self._plateau = _Suivi()
        self._panneau = _Suivi()
        self._bouton = False
        self._voyant: bool | None = None
        self._pret = False
        # Après une vidange finie : on attend que ce plateau (fût vide) s'en aille.
        self._attend_depart = False
        self._poids_lu: float | None = None
        self._probleme_pesee = "pas de pesée du fût" if pesees is None else "pas encore lue"
        self._infos_plateau: Plateau | None = None
        self._absence_signalee = False
        self._accu_signale = ACCU_BON
        # Plateau en place : dernière fois qu'on l'a vu en recharge (ou son arrivée).
        self._recharge_vue_a: float | None = None
        self._recharge_signalee = False
        self._cycle: int | None = None
        self._fut: str | None = None
        self._poids_plein: float | None = None
        self._doses = 0.0
        self._sans_pesee = False
        self._seaux_sans_pesee: set[str] = set()
        self._ecart_signale = False
        self._messages: deque[str] = deque(maxlen=10)
        self._erreurs_vues: set[str] = set()

    # ------------------------------------------------------------ en fond

    def demarrer(self, arret: threading.Event) -> list[threading.Thread]:
        """Un fil : les signaux, le bouton, le voyant et la pesée (lue dans le tour des pesées,
        qui tourne de son côté)."""
        return [lancer_boucle("poste_fut", self.reglages.periode_s, self.observer, arret)]

    def _noter_erreur(self, cle: str, message: str) -> None:
        """Une panne de signal n'est notée qu'une fois au journal (pas à chaque tour)."""
        if cle not in self._erreurs_vues:
            self._erreurs_vues.add(cle)
            journal.warning("Poste du fût : %s", message)

    def _lire(self, nom: str) -> bool | None:
        try:
            valeur = self.materiel.lire(nom)
        except (ErreurMateriel, KeyError) as erreur:
            self._noter_erreur(nom, str(erreur))
            return None
        self._erreurs_vues.discard(nom)
        return valeur

    def observer(self) -> None:
        """Relit les signaux du poste, le bouton « Prêt », la pesée, et règle le voyant."""
        with self._verrou:
            maintenant = self._horloge()
            plateau = self._lire(PLATEAU)
            if self._plateau.voir(plateau, maintenant):
                journal.info("Poste du fût : plateau %s", _dire_plateau(plateau))
                if plateau is not True:
                    # Plateau parti : la prochaine absence de la pesée sera une nouvelle absence.
                    self._absence_signalee = False
                    self._recharge_signalee = False
                    self._recharge_vue_a = None
                else:
                    self._recharge_vue_a = maintenant
            if self._panneau.voir(self._lire(PANNEAU), maintenant):
                journal.info("Poste du fût : panneau %s", _dire_panneau(self._panneau.valeur))
            bouton = self._lire(BOUTON) is True
            appui, self._bouton = bouton and not self._bouton, bouton
            self._suivre_pesee(maintenant)
            if appui:
                try:
                    self._appuyer("bouton du poste", None)
                except ErreurPoste as erreur:
                    journal.info("Poste du fût : %s", erreur)
                    self._dire(str(erreur))
            if self._pret and plateau is not True:
                self._pret = False
                journal.warning("Poste du fût : plateau plus vu, le poste n'est plus prêt")
                self._dire("Plateau du fût plus vu : le poste n'est plus prêt.")
            plateau_parti = plateau is False and self._plateau.stable(
                maintenant, self.reglages.stabilite_s
            )
            if plateau_parti:
                self._attend_depart = False
                if self._cycle is not None:
                    self._clore("abandonne", None, "fût retiré avant la fin de la vidange")
            self._allumer(maintenant)

    # ------------------------------------------------------------ la pesée

    def _suivre_pesee(self, maintenant: float) -> None:
        """Lit la pesée (griffe hors du fût), puis l'absence et l'accu du plateau."""
        if self.pesee is None:
            return
        if self._lecture_directe:
            self.pesee.tour.interroger_si_du(self.pesee.signal)
        if self.griffe_hors_fut():
            lecture = self.pesee.lire()
            self._poids_lu, self._probleme_pesee = lecture.poids_lu_kg, lecture.probleme
            self._infos_plateau = lecture.plateau
        absente = self._pesee_absente(maintenant)
        if absente and not self._absence_signalee:
            self._absence_signalee = True
            self._alerter(
                f"Pesée du fût absente ({self._probleme_pesee.removeprefix('pesée absente : ')}) "
                ": la vidange continue sans les kilos restants.",
                QUOI_FAIRE_ABSENTE,
            )
        elif self._poids_lu is not None and self._absence_signalee:
            self._absence_signalee = False
            journal.info("Poste du fût : la pesée répond de nouveau")
            self._dire("La pesée du fût répond de nouveau.")
        self._suivre_accu(maintenant)

    def _pesee_absente(self, maintenant: float) -> bool:
        """Plateau en place depuis `delai_apres_plateau_s`, et pas de poids."""
        if self.pesee is None or self._poids_lu is not None or self._plateau.valeur is not True:
            return False
        return maintenant - self._plateau.depuis >= self.reglages.pesee.delai_apres_plateau_s

    def _niveau_accu(self) -> int | None:
        infos = self._infos_plateau
        if infos is None or self.pesees is None or self.pesees.reglages.accu_plateau_fut is None:
            return None
        seuils = self.pesees.reglages.accu_plateau_fut
        volts = infos.accu_mv / 1000
        if volts < seuils.bientot_absente_v:
            return ACCU_BIENTOT_VIDE
        if volts < seuils.recharger_v:
            return ACCU_RECHARGER
        return ACCU_BON if volts >= seuils.bon_v else ACCU_MOYEN

    def _suivre_accu(self, maintenant: float) -> None:
        """Alertes de l'accu (une par seuil franchi ; de nouveau après être revenu « bon »), et
        de la recharge sans contact (plateau au poste trop longtemps sans recharge)."""
        infos, niveau = self._infos_plateau, self._niveau_accu()
        if infos is None or niveau is None or self.pesees is None:
            return
        seuils = self.pesees.reglages.accu_plateau_fut
        assert seuils is not None
        if niveau == ACCU_BON:
            self._accu_signale = ACCU_BON
        elif niveau > self._accu_signale and niveau >= ACCU_RECHARGER:
            self._accu_signale = niveau
            etat = f"{_v(infos.accu_mv)} V, {infos.accu_pct} %"
            if niveau == ACCU_BIENTOT_VIDE:
                message = f"Accu du plateau presque vide ({etat}) : pesée bientôt absente."
            else:
                message = f"Accu du plateau faible ({etat}) : recharger le plateau."
            self._alerter(message, QUOI_FAIRE_ACCU)
        if self._plateau.valeur is not True:
            return
        if infos.en_recharge:
            self._recharge_vue_a = maintenant
        depuis = self._recharge_vue_a if self._recharge_vue_a is not None else maintenant
        if maintenant - depuis > seuils.sans_recharge_max_s and not self._recharge_signalee:
            self._recharge_signalee = True
            minutes = math.floor(seuils.sans_recharge_max_s / 60)
            self._alerter(
                f"Plateau au poste depuis plus de {minutes} min sans recharge : recharge sans "
                "contact en panne ?",
                QUOI_FAIRE_RECHARGE,
            )
        elif infos.en_recharge:
            self._recharge_signalee = False

    def _alerter(self, message: str, quoi_faire: str) -> None:
        """Une alerte qui n'arrête rien : journal, messages du poste, alarme du registre (écran,
        page web, et envoi avec le cycle)."""
        journal.warning("Poste du fût : %s", message)
        self._dire(message)
        if self.registre is None:
            return
        try:
            self.registre.noter_alarme(MODULE, message, quoi_faire, cycle=self._cycle)
        except ErreurRegistre as erreur:
            journal.error("Poste du fût : registre : %s", erreur)

    def _allumer(self, maintenant: float) -> None:
        """Voyant du bouton : allumé quand c'est prêt, clignotant sinon."""
        demi = self.reglages.clignotement_s
        voulu = self._pret or int(maintenant / demi) % 2 == 0
        if voulu == self._voyant:
            return
        try:
            self.materiel.ecrire(VOYANT, voulu)
        except (ErreurMateriel, KeyError) as erreur:
            self._noter_erreur(VOYANT, str(erreur))
            return
        self._voyant = voulu

    def _dire(self, message: str) -> None:
        self._messages.append(message)

    # ------------------------------------------------------------ état

    @property
    def plateau_stable(self) -> bool:
        with self._verrou:
            return self._plateau.valeur is True and self._plateau.stable(
                self._horloge(), self.reglages.stabilite_s
            )

    @property
    def echange_en_cours(self) -> bool:
        """Plateau du fût absent ou en mouvement : les verrous du poste s'appliquent."""
        if self._lecture_directe:
            self.observer()
        return not self.plateau_stable

    def _manque(self) -> list[str]:
        """Ce qui manque pour « Prêt ». La pesée n'y est jamais (décision du 05/11/2026)."""
        manque = []
        if self._attend_depart:
            manque.append("sortir le plateau : ce fût est vide")
        if self._plateau.valeur is not True:
            manque.append("plateau du fût contre les 2 butées du fond")
        elif not self.plateau_stable:
            manque.append(f"plateau immobile depuis {self.reglages.stabilite_s:g} s")
        return manque

    def etat(self) -> EtatPoste:
        if self._lecture_directe:
            self.observer()
        with self._verrou:
            maintenant = self._horloge()
            if self._pret:
                etat = PRET
            elif self._plateau.valeur is True:
                etat = EN_PLACE
            else:
                etat = ABSENT
            poids = self._poids_lu
            infos = self._infos_plateau
            niveau = self._niveau_accu()
            return EtatPoste(
                etat=etat,
                libelle=LIBELLES[etat],
                plateau=self._plateau.valeur,
                panneau_leve=self._panneau.valeur,
                plateau_stable=self.plateau_stable,
                pesee=self._probleme_pesee,
                pesee_absente=self._pesee_absente(maintenant),
                poids_lu_kg=poids,
                poids_net_kg=None if poids is None or self.pesee is None else self.pesee.net(poids),
                accu_v=None if infos is None else infos.accu_mv / 1000,
                accu_pct=None if infos is None else infos.accu_pct,
                en_recharge=None if infos is None else infos.en_recharge,
                signal_dbm=None if infos is None else infos.signal_dbm,
                accu="" if niveau is None else TEXTES_ACCU[niveau],
                manque=() if self._pret else tuple(self._manque()),
                gestes=GESTES,
                cycle=self._cycle,
                poids_plein_kg=self._poids_plein,
                doses_kg=self._doses,
                sans_pesee=self._sans_pesee,
                messages=tuple(self._messages),
                exemple_pesee=self.reglages.pesee.exemple,
            )

    # ------------------------------------------------------------ « Prêt »

    def appuyer_pret(self, qui: str, fut: str | None = None) -> None:
        """Le bouton « Prêt » (poste, écran ou page web). `fut` : code du QR du fût, s'il est
        connu (lu par la vision, tâche 22). Lève ErreurPoste avec ce qui manque."""
        if self._lecture_directe:
            self.observer()
        self._appuyer(qui, fut)

    def _appuyer(self, qui: str, fut: str | None) -> None:
        with self._verrou:
            if self._pret:
                return
            manque = self._manque()
            if manque:
                raise ErreurPoste("« Prêt » refusé, il manque : " + " ; ".join(manque) + ".")
            self._pret = True
            net = self.poids_restant_kg()
            if self._cycle is not None:
                journal.warning("Poste du fût : prêt de nouveau (%s), la vidange continue", qui)
                self._dire("Prêt de nouveau : la vidange du fût continue.")
                return
            self._poids_plein, self._doses, self._fut = net, 0.0, fut
            self._ecart_signale = False
            self._sans_pesee = net is None
            self._seaux_sans_pesee = set()
            if net is not None:
                journal.info("Poste du fût : prêt (%s), poids du fût plein %s kg", qui, net)
                self._dire(f"Prêt : fût de {_kg(net)} kg (substrat).")
            else:
                journal.warning(
                    "Poste du fût : prêt (%s) sans pesée du fût (%s) : la vidange commence "
                    "sans poids du fût plein",
                    qui,
                    self._probleme_pesee,
                )
                self._dire("Prêt, sans pesée du fût : la vidange commence sans le poids du fût.")
            if self.registre is None:
                return
            try:
                self._cycle = self.registre.commencer_cycle("vidange", fut=fut)
                if net is not None:
                    self._mesurer("poids_fut_plein", net)
                else:
                    self._noter_sans_pesee(None)
            except ErreurRegistre as erreur:
                journal.error("Poste du fût : registre : %s", erreur)

    def _mesurer(self, nom: str, valeur: float) -> None:
        assert self.registre is not None
        self.registre.noter_mesure(
            nom, round(valeur, 3), "kg", capteur=SIGNAL_PESEE, cycle=self._cycle, fut=self._fut
        )

    def _noter_sans_pesee(self, seau: str | None) -> None:
        """Mesure `sans_pesee_fut` (valeur 1) : au « Prêt » (objet : le fût), ou pour une dose
        prise sans pesée (objet : le seau, une fois par seau s'il est connu)."""
        assert self.registre is not None
        self.registre.noter_mesure(
            "sans_pesee_fut",
            1,
            "",
            capteur=SIGNAL_PESEE,
            cycle=self._cycle,
            fut=self._fut if seau is None else None,
            seau=seau,
        )

    # ------------------------------------------------------------ pendant la vidange

    def poids_restant_kg(self) -> float | None:
        """Substrat encore dans le fût (dernière pesée), ou None sans pesée."""
        with self._verrou:
            if self._poids_lu is None or self.pesee is None:
                return None
            return self.pesee.net(self._poids_lu)

    def noter_dose(self, kg: float, seau: str | None = None) -> str | None:
        """Une dose prise par la griffe (appelé par la griffe, sortie du fût). `seau` : le
        code du seau qu'elle remplit, s'il est connu.

        Sans pesée : le seau est noté « sans pesée du fût ». Rend un avertissement si la somme
        des doses ne suit pas la baisse de la pesée (au-delà de `ecart_doses_max_kg`) ; ce
        n'est jamais un arrêt."""
        with self._verrou:
            self._doses += kg
            restant = self.poids_restant_kg()
            if self.registre is not None and self._cycle is not None:
                try:
                    if restant is not None:
                        self._mesurer("poids_fut_restant", restant)
                    elif seau is None or seau not in self._seaux_sans_pesee:
                        self._noter_sans_pesee(seau)
                except ErreurRegistre as erreur:
                    journal.error("Poste du fût : registre : %s", erreur)
            if restant is None:
                self._sans_pesee = True
                if seau is not None:
                    self._seaux_sans_pesee.add(seau)
                return None
            if self._poids_plein is None:
                return None
            baisse = self._poids_plein - restant
            ecart = abs(baisse - self._doses)
            if ecart <= self.reglages.pesee.ecart_doses_max_kg:
                self._ecart_signale = False
                return None
            message = (
                f"Avertissement : la griffe a pris {_kg(self._doses)} kg mais la pesée a baissé "
                f"de {_kg(baisse)} kg (écart {_kg(ecart)} kg). Regarder la pesée et la griffe."
            )
            if not self._ecart_signale:
                self._ecart_signale = True
                journal.warning("Poste du fût : %s", message)
                self._dire(message)
            return message

    def finir_vidange(self, nombre_seaux: int) -> str:
        """Fût vide (dit par la griffe) : poids total vidé, alerte, fin du cycle."""
        with self._verrou:
            restant = self.poids_restant_kg()
            total = None
            if restant is not None and self._poids_plein is not None:
                total = self._poids_plein - restant
            if total is not None:
                poids = f"{_kg(total)} kg vidés"
            else:
                poids = f"{_kg(self._doses)} kg d'après les doses (pesée absente)"
            message = (
                f"Fût vide : {nombre_seaux} seaux, {poids}. Relever le volet, desserrer les "
                "freins, sortir le plateau."
            )
            self._clore("termine", total, message)
            self._pret = False
            self._attend_depart = True
            return message

    def _clore(
        self, issue: Literal["termine", "abandonne"], total: float | None, message: str
    ) -> None:
        journal.warning("Poste du fût : %s", message)
        self._dire(message)
        if self.registre is not None and self._cycle is not None:
            try:
                restant = self.poids_restant_kg()
                if restant is not None:
                    self._mesurer("poids_fut_restant", restant)
                if total is not None:
                    self._mesurer("poids_fut_vide_total", total)
                self.registre.finir_cycle(self._cycle, issue)
            except ErreurRegistre as erreur:
                journal.error("Poste du fût : registre : %s", erreur)
        self._cycle = None

    # ------------------------------------------------------------ mode et verrous

    def refus_lancement(self, mode: str) -> str | None:
        """Production seulement contact du panneau fermé (panneau levé), lavage seulement
        contact ouvert ; contact illisible ou qui vient de bouger : ni l'un ni l'autre."""
        if mode not in MODES_DU_PANNEAU:
            return None
        if self._lecture_directe:
            self.observer()
        with self._verrou:
            refus = MODES_DU_PANNEAU[mode]
            leve = self._panneau.valeur
            if leve is None:
                return f"{refus} : contact du panneau du poste du fût illisible (voir le journal)"
            if not self._panneau.stable(self._horloge(), self.reglages.stabilite_s):
                return (
                    f"{refus} : le panneau du poste du fût vient de bouger, attendre "
                    f"{self.reglages.stabilite_s:g} s"
                )
            if mode == "production" and not leve:
                return (
                    f"{refus} : le panneau long du poste du fût n'est pas levé "
                    "(contact ouvert : rabattu ou entre les deux). Le lever jusqu'en haut."
                )
            if mode == "lavage" and leve:
                return f"{refus} : le panneau long du poste du fût est levé. Le rabattre."
            return None

    def volet_considere_releve(self, mode: str) -> bool:
        """Pas de capteur du volet du dessus : il est considéré relevé en mode lavage,
        contact du panneau ouvert."""
        with self._verrou:
            return mode == "lavage" and self._panneau.valeur is False

    def panneau_vu_rabattu(self) -> bool:
        """Pour l'isolation du fût (préhension) : contact du panneau ouvert et stable. Un contact
        illisible ou qui vient de bouger n'est pas « vu rabattu »."""
        if self._lecture_directe:
            self.observer()
        with self._verrou:
            return self._panneau.valeur is False and self._panneau.stable(
                self._horloge(), self.reglages.stabilite_s
            )

    def refus_pont(self, x: float) -> str | None:
        return regles.refus_pont(self.reglages, self.echange_en_cours, x)

    def refus_remplissage(self, y_bout: float) -> str | None:
        return regles.refus_remplissage(self.reglages, self.echange_en_cours, y_bout)

    def refus_griffe(self, x: float, y: float, bas_tete_z: float, mode: str) -> str | None:
        releve = self.volet_considere_releve(mode)
        return regles.refus_griffe(self.reglages, x, y, bas_tete_z, releve)

    def refus_passage_paroi_lavage(self, fond_seau_z: float, axe_y: float) -> str | None:
        return regles.refus_passage_paroi_lavage(self.reglages, fond_seau_z, axe_y)

    @property
    def tiroir_stockage_doit_rester_rentre(self) -> bool:
        """Le tiroir du bas du stockage reste rentré pendant l'échange du fût. Le Stockage
        n'est pas figé : seulement cette condition nommée (case vide), qu'il lira."""
        return self.echange_en_cours

    # ------------------------------------------------------------ conditions du chef

    @property
    def condition_pret(self) -> Condition:
        return Condition(
            "poste du fût prêt (plateau au fond, bouton « Prêt »)",
            lambda: self.etat().etat == PRET,
        )

    @property
    def condition_plateau_parti(self) -> Condition:
        return Condition("plateau du fût sorti du poste", self._plateau_parti)

    def _plateau_parti(self) -> bool:
        if self._lecture_directe:
            self.observer()
        with self._verrou:
            return (
                self._plateau.valeur is False
                and self._plateau.stable(self._horloge(), self.reglages.stabilite_s)
                and not self._attend_depart
            )

    @property
    def surveillance(self) -> Condition:
        """Pour le module qui travaille au fût : le plateau doit rester vu au fond."""
        return Condition(
            "plateau du fût en place", lambda: self.etat().plateau is True, QUOI_FAIRE_PERTE
        )

    def condition_mode(self, mode: str) -> Condition:
        return Condition(
            f"panneau du poste du fût dans la position du mode {mode}",
            lambda: self.refus_lancement(mode) is None,
        )


def _dire_plateau(valeur: bool | None) -> str:
    return {True: "au fond", False: "absent", None: "illisible"}[valeur]


def _dire_panneau(valeur: bool | None) -> str:
    return {True: "levé (production)", False: "pas levé (lavage)", None: "illisible"}[valeur]
