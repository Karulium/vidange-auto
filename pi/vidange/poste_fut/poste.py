"""Poste du fût : l'état du poste, le bouton « Prêt », son voyant, la pesée, le mode permis.

    poste = PosteFut(reglages.machine.poste_fut, materiel, registre)
    poste.demarrer(arret)                     # relit les signaux et pèse, en fond
    poste.etat()                              # EtatPoste : absent, en place, prêt ; poids...
    poste.appuyer_pret("page web")            # « Prêt » de l'écran ou de la page web
    poste.refus_lancement("production")       # pourquoi on ne peut pas lancer, ou None

Rien ne bouge seul au poste : Karulium roule le chariot au fond (2 butées d'angle), freine,
branche la prise de la pesée, enlève la soupape, rabat le grand volet, puis appuie sur « Prêt ».
Le Pi ne vérifie par capteur que le chariot (inductif de la butée) et la pesée ; les autres
gestes sont seulement rappelés à l'écran.

États : chariot absent ; chariot en place mais pas prêt ; prêt. « Prêt » = chariot en place
+ pesée qui répond avec un poids plausible + chariot stable depuis `stabilite_s` + appui sur
« Prêt » (bouton lumineux du poste, écran ou page web). Le voyant du bouton clignote tant que ce
n'est pas prêt. Si le chariot n'est plus vu, le poste n'est plus prêt : la surveillance
(`surveillance`) met en alarme le module qui travaille au fût (la griffe, tâche 18).

Au « Prêt », le cycle « vidange » du fût commence dans le registre, avec le poids du fût plein.
La griffe (tâche 18) dira chaque dose (`noter_dose`) et la fin (`finir_vidange`).

Rien ici ne protège personne : la sécurité est câblée. Le logiciel peut planter sans danger.
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal

from vidange.chef import Condition
from vidange.fiabilite.constats import lancer_boucle
from vidange.journal import donner_journal
from vidange.materiel import ErreurMateriel, Materiel
from vidange.poste_fut import regles
from vidange.poste_fut.pesee import SIGNAL as SIGNAL_PESEE
from vidange.poste_fut.pesee import ErreurPesee, Pesee
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import PosteFut as ReglagesPosteFut

journal = donner_journal("poste_fut")

CHARIOT = "chariot_fut_en_place"
PANNEAU = "reed_panneau_poste_fut"
BOUTON = "bouton_pret_fut"
VOYANT = "voyant_pret_fut"

ABSENT, EN_PLACE, PRET = "absent", "en_place", "pret"
LIBELLES = {
    ABSENT: "Chariot du fût absent",
    EN_PLACE: "Chariot en place, pas prêt",
    PRET: "Prêt",
}
# Rappel à l'écran avant le « Prêt » : rien de cela n'est vérifié par un capteur.
GESTES = (
    "Rouler le chariot jusqu'aux 2 butées du fond",
    "Freiner le chariot",
    "Brancher la prise magnétique de la pesée",
    "Enlever la soupape du couvercle (trou bouché)",
    "Rabattre le grand volet du dessus",
    "Appuyer sur « Prêt »",
)
QUOI_FAIRE_PERTE = (
    "Le chariot du fût n'est plus vu au fond du poste. Le pont doit sortir de la zone du "
    "chariot. Remettre le chariot contre les 2 butées, freiner, appuyer sur « Prêt », "
    "puis acquitter et donner le Go."
)
MODES_DU_PANNEAU = {"production": "Production refusée", "lavage": "Lavage refusé"}


class ErreurPoste(Exception):
    """« Prêt » refusé : le message dit ce qui manque."""


@dataclass(frozen=True)
class EtatPoste:
    etat: str
    libelle: str
    # Signaux lus (None : illisible).
    chariot: bool | None
    panneau_leve: bool | None
    # Chariot vu au fond, sans changement depuis `stabilite_s`.
    chariot_stable: bool
    # "" si la pesée répond, sinon son problème (« pesée débranchée »...).
    pesee: str
    poids_lu_kg: float | None
    poids_net_kg: float | None
    # Ce qui manque pour pouvoir appuyer sur « Prêt » (vide : c'est possible, ou déjà prêt).
    manque: tuple[str, ...]
    gestes: tuple[str, ...]
    # La vidange en cours (cycle du registre), poids du fût plein, somme des doses.
    cycle: int | None
    poids_plein_kg: float | None
    doses_kg: float
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


class PosteFut:
    def __init__(
        self,
        reglages: ReglagesPosteFut,
        materiel: Materiel,
        registre: Registre | None = None,
        horloge: Callable[[], float] = time.monotonic,
        griffe_hors_fut: Callable[[], bool] = lambda: True,
        lecture_directe: bool = False,
    ) -> None:
        """`griffe_hors_fut` : la pesée n'est lue que si la griffe n'est pas dans le fût
        (rendu par le module Griffe, tâche 18). `lecture_directe` : pas de fils en fond, chaque
        `etat()` relit les signaux et pèse quand c'est l'heure (simulateur, tests)."""
        self.reglages = reglages
        self.materiel = materiel
        self.registre = registre
        self.pesee = Pesee(reglages.pesee, materiel)
        self.griffe_hors_fut = griffe_hors_fut
        self._horloge = horloge
        self._lecture_directe = lecture_directe
        self._verrou = threading.RLock()
        self._chariot = _Suivi()
        self._panneau = _Suivi()
        self._bouton = False
        self._voyant: bool | None = None
        self._pret = False
        # Après une vidange finie : on attend que ce chariot (fût vide) s'en aille.
        self._attend_depart = False
        self._poids_lu: float | None = None
        self._probleme_pesee = "pas encore pesé"
        self._pese_a: float | None = None
        self._cycle: int | None = None
        self._fut: str | None = None
        self._poids_plein: float | None = None
        self._doses = 0.0
        self._ecart_signale = False
        self._messages: deque[str] = deque(maxlen=10)
        self._erreurs_vues: set[str] = set()

    # ------------------------------------------------------------ en fond

    def demarrer(self, arret: threading.Event) -> list[threading.Thread]:
        """Deux fils : les signaux (rapide), la pesée (une lecture prend jusqu'à 0,5 s)."""
        return [
            lancer_boucle("poste_fut", self.reglages.periode_s, self.observer, arret),
            lancer_boucle("pesee_fut", self.reglages.pesee.periode_s, self.peser, arret),
        ]

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
        """Relit les signaux du poste, le bouton « Prêt », et règle le voyant."""
        with self._verrou:
            maintenant = self._horloge()
            chariot = self._lire(CHARIOT)
            if self._chariot.voir(chariot, maintenant):
                journal.info("Poste du fût : chariot %s", _dire_chariot(chariot))
            if self._panneau.voir(self._lire(PANNEAU), maintenant):
                journal.info("Poste du fût : panneau %s", _dire_panneau(self._panneau.valeur))
            bouton = self._lire(BOUTON) is True
            appui, self._bouton = bouton and not self._bouton, bouton
            if appui:
                try:
                    self._appuyer("bouton du poste", None)
                except ErreurPoste as erreur:
                    journal.info("Poste du fût : %s", erreur)
                    self._dire(str(erreur))
            if self._pret and chariot is not True:
                self._pret = False
                journal.warning("Poste du fût : chariot plus vu, le poste n'est plus prêt")
                self._dire("Chariot du fût plus vu : le poste n'est plus prêt.")
            chariot_parti = chariot is False and self._chariot.stable(
                maintenant, self.reglages.stabilite_s
            )
            if chariot_parti:
                self._attend_depart = False
                if self._cycle is not None:
                    self._clore("abandonne", None, "fût retiré avant la fin de la vidange")
            if self._lecture_directe and self._pesee_due(maintenant):
                self.peser()
            self._allumer(maintenant)

    def _pesee_due(self, maintenant: float) -> bool:
        return self._pese_a is None or maintenant - self._pese_a >= self.reglages.pesee.periode_s

    def peser(self) -> None:
        """Une pesée, si la griffe n'est pas dans le fût. Sans réponse : « pesée débranchée »."""
        if not self.griffe_hors_fut():
            return
        try:
            poids = self.pesee.peser()
        except ErreurPesee as erreur:
            with self._verrou:
                self._poids_lu, self._probleme_pesee = None, str(erreur)
                self._pese_a = self._horloge()
            self._noter_erreur("pesee", str(erreur))
            return
        with self._verrou:
            self._poids_lu, self._probleme_pesee = poids, ""
            self._pese_a = self._horloge()
        if "pesee" in self._erreurs_vues:
            self._erreurs_vues.discard("pesee")
            journal.info("Poste du fût : la pesée répond de nouveau")

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
    def chariot_stable(self) -> bool:
        with self._verrou:
            return self._chariot.valeur is True and self._chariot.stable(
                self._horloge(), self.reglages.stabilite_s
            )

    @property
    def echange_en_cours(self) -> bool:
        """Chariot du fût absent ou en mouvement : les verrous du poste s'appliquent."""
        if self._lecture_directe:
            self.observer()
        return not self.chariot_stable

    def _manque(self) -> list[str]:
        manque = []
        if self._attend_depart:
            manque.append("sortir le chariot : ce fût est vide")
        if self._chariot.valeur is not True:
            manque.append("chariot du fût contre les 2 butées du fond")
        elif not self.chariot_stable:
            manque.append(f"chariot immobile depuis {self.reglages.stabilite_s:g} s")
        if self._probleme_pesee:
            if self._probleme_pesee == "pesée débranchée":
                manque.append("pesée qui répond : brancher la prise magnétique")
            else:
                manque.append(self._probleme_pesee)
        elif self._poids_lu is not None and not self.pesee.plausible(self._poids_lu):
            debut, fin = self.reglages.pesee.plausible_kg
            manque.append(
                f"poids plausible : {_kg(self._poids_lu)} kg lus, attendu entre "
                f"{debut:g} et {fin:g} kg"
            )
        return manque

    def etat(self) -> EtatPoste:
        if self._lecture_directe:
            self.observer()
        with self._verrou:
            if self._pret:
                etat = PRET
            elif self._chariot.valeur is True:
                etat = EN_PLACE
            else:
                etat = ABSENT
            poids = self._poids_lu
            return EtatPoste(
                etat=etat,
                libelle=LIBELLES[etat],
                chariot=self._chariot.valeur,
                panneau_leve=self._panneau.valeur,
                chariot_stable=self.chariot_stable,
                pesee=self._probleme_pesee,
                poids_lu_kg=poids,
                poids_net_kg=None if poids is None else self.pesee.net(poids),
                manque=() if self._pret else tuple(self._manque()),
                gestes=GESTES,
                cycle=self._cycle,
                poids_plein_kg=self._poids_plein,
                doses_kg=self._doses,
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
            net = self.pesee.net(self._poids_lu) if self._poids_lu is not None else None
            if self._cycle is not None:
                journal.warning("Poste du fût : prêt de nouveau (%s), la vidange continue", qui)
                self._dire("Prêt de nouveau : la vidange du fût continue.")
                return
            journal.info("Poste du fût : prêt (%s), poids du fût plein %s kg", qui, net)
            self._poids_plein, self._doses, self._fut = net, 0.0, fut
            self._ecart_signale = False
            self._dire(f"Prêt : fût de {_kg(net)} kg (substrat)." if net is not None else "Prêt.")
            if self.registre is None:
                return
            try:
                self._cycle = self.registre.commencer_cycle("vidange", fut=fut)
                if net is not None:
                    self._mesurer("poids_fut_plein", net)
            except ErreurRegistre as erreur:
                journal.error("Poste du fût : registre : %s", erreur)

    def _mesurer(self, nom: str, valeur: float) -> None:
        assert self.registre is not None
        self.registre.noter_mesure(
            nom, round(valeur, 3), "kg", capteur=SIGNAL_PESEE, cycle=self._cycle, fut=self._fut
        )

    # ------------------------------------------------------------ pendant la vidange

    def poids_restant_kg(self) -> float | None:
        """Substrat encore dans le fût (dernière pesée), ou None sans pesée."""
        with self._verrou:
            if self._poids_lu is None or self._probleme_pesee:
                return None
            return self.pesee.net(self._poids_lu)

    def noter_dose(self, kg: float) -> str | None:
        """Une dose prise par la griffe (appelé par la tâche 18, griffe sortie du fût).

        Rend un avertissement si la somme des doses ne suit pas la baisse de la pesée (au-delà
        de `ecart_doses_max_kg`) ; ce n'est jamais un arrêt."""
        with self._verrou:
            self._doses += kg
            restant = self.poids_restant_kg()
            if restant is not None and self.registre is not None and self._cycle is not None:
                try:
                    self._mesurer("poids_fut_restant", restant)
                except ErreurRegistre as erreur:
                    journal.error("Poste du fût : registre : %s", erreur)
            if restant is None or self._poids_plein is None:
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
        """Fût vide (dit par la tâche 18) : poids total vidé, alerte, fin du cycle."""
        with self._verrou:
            restant = self.poids_restant_kg()
            total = None
            if restant is not None and self._poids_plein is not None:
                total = self._poids_plein - restant
            if total is not None:
                poids = f"{_kg(total)} kg vidés"
            else:
                poids = f"{_kg(self._doses)} kg d'après les doses (pesée absente)"
            message = f"Fût vide : {nombre_seaux} seaux, {poids}. Sortir le chariot."
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
            "poste du fût prêt (chariot au fond, pesée, bouton « Prêt »)",
            lambda: self.etat().etat == PRET,
        )

    @property
    def condition_chariot_parti(self) -> Condition:
        return Condition("chariot du fût sorti du poste", self._chariot_parti)

    def _chariot_parti(self) -> bool:
        if self._lecture_directe:
            self.observer()
        with self._verrou:
            return (
                self._chariot.valeur is False
                and self._chariot.stable(self._horloge(), self.reglages.stabilite_s)
                and not self._attend_depart
            )

    @property
    def surveillance(self) -> Condition:
        """Pour le module qui travaille au fût : le chariot doit rester vu au fond."""
        return Condition(
            "chariot du fût en place", lambda: self.etat().chariot is True, QUOI_FAIRE_PERTE
        )

    def condition_mode(self, mode: str) -> Condition:
        return Condition(
            f"panneau du poste du fût dans la position du mode {mode}",
            lambda: self.refus_lancement(mode) is None,
        )


def _dire_chariot(valeur: bool | None) -> str:
    return {True: "au fond", False: "absent", None: "illisible"}[valeur]


def _dire_panneau(valeur: bool | None) -> str:
    return {True: "levé (production)", False: "pas levé (lavage)", None: "illisible"}[valeur]
