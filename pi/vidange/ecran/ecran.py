"""L'écran de l'armoire : ce qu'il montre, ce que font ses boutons.

    ecran = Ecran(reglages.programme.ecran, liaison, chef, registre, bilans.acquitter, mode)
    ecran.demarrer(arret)      # un fil qui fait un tour tous les « periode_s »

Le Pi décide de tout : la page à montrer, ses textes et ses couleurs (voir pages.py et
nextion/pages.md). Un bouton n'envoie que son nom ; le Pi le comprend d'après la page qu'il
a lui-même demandée. Un bouton reçu alors que le Pi a déjà changé de page est ignoré.

Les ordres passent par le chef d'orchestre, comme ceux de la page web : l'écran ne commande
jamais un axe lui-même. Pause : tout de suite. Go, Reprise et changement de mode : après un
« Oui » (un appui de travers, avec des gants, ne fait rien bouger). La sécurité reste câblée.

Une nouvelle alarme fait venir la page d'alarme (quoi faire, en 2 lignes, avec « Suite »
si le texte est plus long). Les autres pages reviennent seules à la page d'état.

Pendant un pilotage à distance (tâche 12), le bandeau le dit, et la main est à l'armoire : le
premier appui sur n'importe quel bouton arrête le pilotage à distance (et ne fait rien d'autre).

Poste du fût (tâches 17 et 17 bis) : quand le plateau arrive au fond, la page « poste_fut » vient
seule (depuis la page d'état) : poids (ou « pesée absente »), accu et radio du plateau, gestes à
faire à la main, ce qui manque, bouton PRÊT. Elle repart seule quand le poste est prêt ou que le
plateau s'en va.

Lot (tâche 45 quater) : un lot proposé par la page web (« Lot de seaux », « Lot de bocaux ») est
montré sur la page d'état (« ATTEND LE GO ») ; le bouton GO, puis « Oui », le lance. Le Pi propose,
Karulium dit Go devant la machine. S'il ne peut pas partir, l'écran dit pourquoi.

Objet encore tenu à la ventouse au redémarrage (tâche 45 nonies) : le bandeau dit « OBJET ENCORE
TENU », la ligne d'information dit quoi faire, le bouton GO est éteint et un appui dit pourquoi.

Nettoyage (tâche 38) : page « nettoyage », depuis la page du mode (ENCEINTE) : état du store et de
ses verrous, purge, nuit UV-ozone, ozone dedans et dehors ; OUVRIR (libère les verrous) ou FERMER,
LUMIÈRE, NUIT (à l'heure réglée, puis MAINTENANT), PASSER OUTRE (la purge). Le Pi ne commande pas
le moteur du store.
"""

import threading
import time
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING

from vidange.chef import Chef, ErreurChef
from vidange.chef.chef import EtatChef, EtatModule
from vidange.distance import PiloteDistance
from vidange.ecran.liaison import LiaisonEcran
from vidange.ecran.pages import (
    ALARME,
    COMPTEURS,
    CONFIRMER,
    ETAT,
    MODE,
    NETTOYAGE,
    POSTE_FUT,
    Page,
)
from vidange.ecran.protocole import Appui, couleur_565, preparer_texte
from vidange.fiabilite.constats import lancer_boucle
from vidange.journal import donner_journal
from vidange.mode import MODES, ErreurMode, ModeMachine
from vidange.nettoyage import ErreurNettoyage, EtatNettoyage, Nettoyage
from vidange.nettoyage.nettoyage import ERREUR, FERME, INCONNU, OUVERT
from vidange.poste_fut import ABSENT, EN_PLACE, PRET, ErreurPoste, EtatPoste, PosteFut
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import FondTexte, ReglagesEcran

if TYPE_CHECKING:
    from vidange.cycle import Lancement, ModeBocaux, ModeNuit, ModeSeaux

journal = donner_journal("ecran")

QUI = "écran de l'armoire"
# Rappel des gestes à la main au poste du fût (version courte de vidange.poste_fut.GESTES).
GESTES_ECRAN = (
    "À la main : fût sur les cales, soupape enlevée, butées du fond, 2 freins, volet rabattu, "
    "panneau levé."
)
TITRES_STORE = {
    FERME: ("STORE FERMÉ", "marche"),
    OUVERT: ("STORE OUVERT", "pause"),
    INCONNU: ("STORE ?", "repos"),
}
TITRES_POSTE = {
    ABSENT: ("PLATEAU ABSENT", "repos"),
    EN_PLACE: ("EN PLACE, PAS PRÊT", "go"),
    PRET: ("PRÊT", "marche"),
}


def texte_pesee(poste: EtatPoste) -> str:
    """La ligne du poids du poste : substrat (ou pourquoi pas de poids), accu et radio."""
    if poste.pesee:
        morceaux = [poste.pesee[0].upper() + poste.pesee[1:]]
    elif poste.poids_net_kg is not None:
        morceaux = [f"Substrat : {poste.poids_net_kg:.1f} kg".replace(".", ",")]
    else:
        morceaux = []
    if poste.accu_pct is not None:
        morceaux.append(f"accu {poste.accu_pct} %" + (" : RECHARGER" if poste.accu else ""))
    if poste.signal_dbm is not None:
        morceaux.append(f"radio {poste.signal_dbm} dBm")
    return " · ".join(morceaux)


def _oui(ok: bool) -> str:
    return "oui" if ok else "non"


def ligne_nettoyage(etat: EtatNettoyage) -> str:
    """La ligne d'état de l'enceinte : la purge, la nuit UV-ozone, ou le ventilateur."""
    if etat.purge and etat.purge_depuis_s is not None:
        return (
            f"Purge {etat.purge_depuis_s / 60:.0f} min : durée {_oui(etat.purge_duree_ok)}, "
            f"particules {_oui(etat.purge_particules_ok)}, pression {_oui(etat.purge_pression_ok)}"
        )
    if etat.nuit is not None:
        texte = etat.nuit_libelle
        if etat.nuit_depuis_s is not None and etat.nuit != "fini":
            texte += f", {etat.nuit_depuis_s / 60:.0f} min"
        if etat.nuit_depart_prevu:
            texte += f" à {etat.nuit_depart_prevu[11:16]}"
        return texte
    if etat.mode == "uv_ozone":
        # Pas une condition de la nuit : seulement dit (« levé » est la position normale).
        return f"Panneau du poste : {etat.panneau}"
    return f"Ventilateur : {etat.ventilateur}"


def texte_enceinte(etat: EtatNettoyage) -> str:
    """Pour la page d'état : ce qui empêche la machine de bouger, ou une alerte forte."""
    if etat.fuite:
        return "FUITE D'OZONE dehors : générateur coupé, ne pas entrer."
    if etat.mode != "mais" and etat.store == OUVERT:
        return "Store ouvert : rien ne bouge tant qu'il n'est pas fermé."
    if etat.purge:
        return "Purge de l'enceinte en cours : pas de dosage ni de versement."
    if etat.nuit is not None and etat.nuit != "fini":
        return etat.nuit_libelle + "."
    return ""


def lisible(nom: str) -> str:
    """Un nom du programme (« lieu_sur ») tel qu'on l'écrit à l'écran."""
    return nom.replace("_", " ")


def couper(texte: str, longueur: int) -> str:
    texte = preparer_texte(texte)
    if len(texte) <= longueur:
        return texte
    return texte[: longueur - 3].rstrip() + "..."


def decouper(texte: str, longueur: int) -> list[str]:
    """Le texte en morceaux d'au plus `longueur` caractères, coupés entre les mots."""
    morceaux: list[str] = []
    ligne = ""
    for mot in preparer_texte(texte).split():
        while len(mot) > longueur:
            if ligne:
                morceaux.append(ligne)
                ligne = ""
            morceaux.append(mot[:longueur])
            mot = mot[longueur:]
        if not ligne:
            ligne = mot
        elif len(ligne) + 1 + len(mot) <= longueur:
            ligne += " " + mot
        else:
            morceaux.append(ligne)
            ligne = mot
    if ligne:
        morceaux.append(ligne)
    return morceaux or [""]


class _Composition:
    """Les valeurs d'une page : « objet.attribut » → valeur, textes coupés à leur longueur."""

    def __init__(self, page: Page, reglages: ReglagesEcran) -> None:
        self.page = page
        self.couleurs = reglages.couleurs
        self.valeurs: dict[str, str | int] = {}

    def mettre(self, objet: str, texte: str, couleur: str | None = None) -> None:
        self.valeurs[f"{objet}.txt"] = couper(texte, self.page.objet(objet).longueur)
        if couleur is not None:
            paire: FondTexte = getattr(self.couleurs, couleur)
            self.valeurs[f"{objet}.bco"] = couleur_565(paire.fond)
            self.valeurs[f"{objet}.pco"] = couleur_565(paire.texte)


class Ecran:
    def __init__(
        self,
        reglages: ReglagesEcran,
        liaison: LiaisonEcran,
        chef: Chef,
        registre: Registre,
        acquitter: Callable[[int, str], None],
        mode: ModeMachine,
        horloge: Callable[[], float] = time.monotonic,
        aujourdhui: Callable[[], date] = date.today,
        pilote: PiloteDistance | None = None,
        poste: PosteFut | None = None,
        nettoyage: Nettoyage | None = None,
        mode_seaux: "ModeSeaux | None" = None,
        mode_bocaux: "ModeBocaux | None" = None,
        mode_nuit: "ModeNuit | None" = None,
        lancement: "Lancement | None" = None,
    ) -> None:
        """`mode_seaux` : quand aucun cycle ne tourne, la page d'état dit si un lot de seaux peut
        partir, ou ce qui manque (tâche 45). `mode_bocaux` : de même pour un lot de bocaux (mode
        « production », si les seaux sont prêts) et pour laver les bocaux (mode « lavage »).
        `mode_nuit` : en mode « UV-ozone », la nuit peut partir ou ce qui manque (tâche 45 bis).
        `lancement` : le lot proposé par la page web, lancé par GO (tâche 45 quater)."""
        self.reglages = reglages
        self.liaison = liaison
        self.chef = chef
        self.registre = registre
        self.acquitter = acquitter
        self.mode = mode
        self.pilote = pilote
        self.poste = poste
        self.nettoyage = nettoyage
        self.mode_seaux = mode_seaux
        self.mode_bocaux = mode_bocaux
        self.mode_nuit = mode_nuit
        self.lancement = lancement
        self._etat_poste: EtatPoste | None = None
        self._horloge = horloge
        self._aujourdhui = aujourdhui
        self._page: Page = ETAT
        self._depuis = horloge()
        # Question en attente d'un « Oui » : (texte, ordre, argument, page où revenir).
        self._question: tuple[str, str, str, Page] | None = None
        self._message = ""
        self._message_jusqu_a = 0.0
        self._alarmes_vues: set[int] = set()
        self._alarme: int | None = None
        self._morceau = 0

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        return lancer_boucle("ecran", self.reglages.periode_s, self.tour, arret)

    @property
    def page(self) -> str:
        return self._page.nom

    # ------------------------------------------------------------ chaque tour

    def tour(self) -> None:
        for trame in self.liaison.tour():
            if isinstance(trame, Appui):
                self._depuis = self._horloge()
                if self.pilote is not None and self.pilote.actif:
                    # Priorité à l'armoire : l'appui reprend la main, sans rien faire d'autre.
                    journal.warning("Écran : appui pendant le pilotage à distance, il s'arrête")
                    self.pilote.reprendre_la_main(QUI)
                    self._dire("Pilotage à distance arrêté : la main est à l'armoire.")
                    continue
                try:
                    self.appuyer(trame.bouton)
                except (
                    ErreurChef,
                    ErreurRegistre,
                    ErreurMode,
                    ErreurPoste,
                    ErreurNettoyage,
                ) as erreur:
                    journal.warning("Écran : %s", erreur)
                    self._dire(str(erreur))
        alarmes = self.registre.alarmes_ouvertes()
        self._suivre_poste()
        self._suivre_alarmes(alarmes)
        self._revenir_seul()
        self.liaison.afficher(self._page, self.composer(alarmes))

    def _aller(self, page: Page) -> None:
        if page is not CONFIRMER:
            self._question = None
        self._page = page
        self._depuis = self._horloge()

    def _dire(self, message: str) -> None:
        self._message = message
        self._message_jusqu_a = self._horloge() + self.reglages.message_s

    def _message_actuel(self) -> str:
        return self._message if self._horloge() < self._message_jusqu_a else ""

    def _suivre_alarmes(self, alarmes: list[dict]) -> None:
        numeros = {alarme["id"] for alarme in alarmes}
        nouvelles = numeros - self._alarmes_vues
        self._alarmes_vues = numeros
        if nouvelles:
            journal.info("Écran : nouvelle alarme, page d'alarme")
            self._aller(ALARME)
            self._alarme, self._morceau = max(nouvelles), 0
        elif self._page is ALARME and not numeros:
            self._aller(ETAT)
        elif self._alarme not in numeros:
            self._alarme = min(numeros) if numeros else None
            self._morceau = 0

    def _suivre_poste(self) -> None:
        """Plateau arrivé : la page du poste vient (depuis la page d'état) ; prêt ou plateau
        parti : elle repart."""
        if self.poste is None:
            return
        avant = self._etat_poste.etat if self._etat_poste is not None else ABSENT
        self._etat_poste = self.poste.etat()
        apres = self._etat_poste.etat
        if apres == avant:
            return
        if apres == EN_PLACE and avant == ABSENT and self._page is ETAT:
            self._aller(POSTE_FUT)
        elif apres in (PRET, ABSENT) and self._page is POSTE_FUT:
            if apres == PRET:
                self._dire("Poste du fût prêt.")
            self._aller(ETAT)

    def _revenir_seul(self) -> None:
        """Retour à la page d'état sans appui (jamais depuis la page d'alarme)."""
        attente = self._horloge() - self._depuis
        if self._page is CONFIRMER and attente > self.reglages.confirmation_s:
            journal.info("Écran : question sans réponse, abandonnée")
            self._aller(ETAT)
        elif (
            self._page in (COMPTEURS, MODE, NETTOYAGE) and attente > self.reglages.retour_accueil_s
        ):
            self._aller(ETAT)

    # ------------------------------------------------------------ boutons

    def appuyer(self, bouton: str) -> None:
        """Un bouton touché, compris d'après la page que le Pi a demandée."""
        page = self._page
        if bouton not in page.boutons:
            journal.warning(
                "Écran : bouton « %s » reçu sur la page « %s » : ignoré "
                "(changement de page en cours, ou nom différent de nextion/pages.md)",
                bouton,
                page.nom,
            )
            return
        journal.info("Écran : bouton « %s » (page « %s »)", bouton, page.nom)
        if bouton == "b_retour":
            self._aller(ETAT)
        elif page is ETAT:
            self._appui_etat(bouton)
        elif page is ALARME:
            self._appui_alarme(bouton)
        elif page is MODE and bouton == "b_enceinte":
            if self.nettoyage is None:
                self._dire("Pas de nettoyage (machine.yaml → nettoyage).")
            else:
                self._aller(NETTOYAGE)
        elif page is MODE:
            self._choisir_mode(bouton.removeprefix("b_"))
        elif page is NETTOYAGE and self.nettoyage is not None:
            self._appui_nettoyage(bouton, self.nettoyage)
        elif page is CONFIRMER:
            self._repondre(bouton == "b_oui")
        elif page is POSTE_FUT and self.poste is not None:
            self.poste.appuyer_pret(QUI)

    def _appui_etat(self, bouton: str) -> None:
        if bouton == "b_bandeau":
            if self._alarme is not None:
                self._aller(ALARME)
        elif bouton == "b_pause":
            if self.chef.en_pause:
                self._demander("Reprendre la machine ? Les axes vont repartir.", "reprendre")
            else:
                journal.warning("Pause demandée à l'écran de l'armoire")
                self.chef.pause()
        elif bouton == "b_go":
            etat = self.chef.etat()
            if etat.go_empeche:
                self._dire(f"Go impossible : {etat.go_empeche}.")
                return
            if not etat.attendent_go:
                self._go_du_lot()
                return
            module = self._module(etat, etat.attendent_go[0])
            self._demander(
                f"Donner le Go à « {lisible(module.module)} » pour l'étape "
                f"« {lisible(module.etape)} » ?",
                "go",
                module.module,
            )
        elif bouton == "b_compteurs":
            self._aller(COMPTEURS)
        elif bouton == "b_mode":
            self._aller(MODE)

    def _go_du_lot(self) -> None:
        """GO sans module qui l'attend : le lot proposé par la page web, s'il y en a un."""
        proposition = None if self.lancement is None else self.lancement.proposition
        if proposition is None:
            self._dire("Aucun Go attendu.")
            return
        assert self.lancement is not None
        refus = self.lancement.refus_go()
        if refus is not None:
            self._dire(f"Lot impossible : {refus}.")
            return
        self._demander(
            f"Lancer le lot de {proposition.texte} ? La machine va bouger.",
            "lot",
            proposition.texte,
        )

    def _appui_alarme(self, bouton: str) -> None:
        alarmes = self.registre.alarmes_ouvertes()
        numeros = [alarme["id"] for alarme in alarmes]
        if self._alarme not in numeros:
            return
        if bouton == "b_suite":
            self._morceau += 1
        elif bouton == "b_suivante":
            self._alarme = numeros[(numeros.index(self._alarme) + 1) % len(numeros)]
            self._morceau = 0
        elif bouton == "b_repare":
            journal.info("Alarme n° %d acquittée à l'écran de l'armoire", self._alarme)
            self.acquitter(self._alarme, QUI)

    def _appui_nettoyage(self, bouton: str, nettoyage: Nettoyage) -> None:
        etat = nettoyage.etat()
        if bouton == "b_store":
            if etat.store == FERME and not etat.verrous_liberes:
                nettoyage.demander_ouverture(QUI)
            else:
                nettoyage.demander_fermeture(QUI)
            messages = nettoyage.etat().messages
            if messages:
                self._dire(messages[-1])
        elif bouton == "b_lumiere":
            nettoyage.eclairage(not etat.eclairage, QUI)
        elif bouton == "b_nuit":
            if etat.nuit == "attente_depart":
                self._demander("Départ de la nuit UV-ozone tout de suite ?", "nuit_maintenant")
            elif etat.refus_nuit is not None:
                self._dire(f"Nuit UV-ozone impossible : {etat.refus_nuit}.")
            else:
                heure = nettoyage.reglages.ozone.heure_depart
                self._demander(
                    f"Nuit UV-ozone à {heure} ? Personne dans l'enceinte, store fermé.", "nuit"
                )
        elif bouton == "b_outre":
            if not etat.purge:
                self._dire("Pas de purge en cours.")
            else:
                self._demander("Passer outre la purge (noté au journal) ?", "outre")

    def _choisir_mode(self, nouveau: str) -> None:
        if nouveau == self.mode.actuel:
            self._dire(f"Déjà en mode {MODES[nouveau]}.")
            return
        refus = self.mode.refus()
        if refus is not None:
            self._dire(f"Impossible : {refus}.")
            return
        self._demander(f"Passer en mode {MODES[nouveau]} ?", "mode", nouveau)

    def _demander(self, question: str, ordre: str, argument: str = "") -> None:
        retour = self._page
        self._aller(CONFIRMER)
        self._question = (question, ordre, argument, retour)

    def _repondre(self, oui: bool) -> None:
        if self._question is None:
            self._aller(ETAT)
            return
        _, ordre, argument, retour = self._question
        self._aller(retour)
        if not oui:
            return
        if ordre == "go":
            journal.info("Go pour « %s » donné à l'écran de l'armoire", argument)
            self.chef.donner_go(argument)
        elif ordre == "lot" and self.lancement is not None:
            journal.info("Go pour le lot de %s donné à l'écran de l'armoire", argument)
            self.lancement.go(QUI)
            self._dire(f"Lot de {argument} lancé.")
        elif ordre == "reprendre":
            journal.info("Reprise demandée à l'écran de l'armoire")
            self.chef.reprendre()
        elif ordre == "mode":
            self.mode.changer(argument, QUI)
        elif self.nettoyage is not None and ordre in ("nuit", "nuit_maintenant"):
            self.nettoyage.programmer_nuit(QUI, tout_de_suite=ordre == "nuit_maintenant")
        elif self.nettoyage is not None and ordre == "outre":
            self.nettoyage.passer_outre(QUI)

    # ------------------------------------------------------------ ce que montre chaque page

    @staticmethod
    def _module(etat: EtatChef, nom: str) -> EtatModule:
        return next(module for module in etat.modules if module.module == nom)

    def composer(self, alarmes: list[dict]) -> dict[str, str | int]:
        """Les valeurs de la page affichée."""
        page = _Composition(self._page, self.reglages)
        if self._page is ETAT:
            self._composer_etat(page, alarmes)
        elif self._page is ALARME:
            self._composer_alarme(page, alarmes)
        elif self._page is COMPTEURS:
            self._composer_compteurs(page)
        elif self._page is MODE:
            self._composer_mode(page)
        elif self._page is POSTE_FUT:
            self._composer_poste(page)
        elif self._page is NETTOYAGE:
            self._composer_nettoyage(page)
        else:
            self._composer_question(page)
        return page.valeurs

    def _composer_etat(self, page: _Composition, alarmes: list[dict]) -> None:
        etat = self.chef.etat()
        en_cours = [m for m in etat.modules if m.statut == "en_cours"]
        nombre_alarmes = len(alarmes) or len(etat.alarmes)
        # Un lot proposé par la page web, qui attend le GO de l'écran (tâche 45 quater).
        lot = None if self.lancement is None else self.lancement.texte_ecran()
        if self.pilote is not None and self.pilote.actif:
            page.mettre("b_bandeau", "À DISTANCE : TOUCHER = STOP", "distance")
        elif etat.go_empeche:
            page.mettre("b_bandeau", "OBJET ENCORE TENU : PAS DE GO", "alarme")
        elif nombre_alarmes:
            page.mettre("b_bandeau", f"ALARME ({nombre_alarmes}) : TOUCHER ICI", "alarme")
        elif etat.en_pause:
            page.mettre("b_bandeau", "EN PAUSE", "pause")
        elif etat.attendent_go or lot is not None:
            page.mettre("b_bandeau", "ATTEND LE GO", "go")
        elif en_cours:
            page.mettre("b_bandeau", "EN MARCHE", "marche")
        else:
            page.mettre("b_bandeau", "À L'ARRÊT", "repos")
        special = self.mode.actuel != "production"
        page.mettre("t_mode", f"Mode : {self.mode.libelle}", "mode" if special else "bouton")
        montre = (
            [self._module(etat, nom) for nom in etat.attendent_go]
            + en_cours
            + [m for m in etat.modules if m.statut == "alarme"]
        )
        # Mode seaux (tâche 45), quand rien ne tourne : quel poste manque, et pourquoi.
        seaux, pourquoi = "", ""
        if not montre:
            seaux, pourquoi = self._texte_des_postes()
        if montre:
            module = montre[0]
            page.mettre(
                "t_module",
                f"{lisible(module.module)}, étape {module.numero}/{module.nombre_etapes} : "
                f"{lisible(module.etape)}",
            )
            page.mettre("t_attend", f"Attend : {module.attend}" if module.attend else "")
        elif lot is not None:
            page.mettre("t_module", lot[0])
            page.mettre("t_attend", "Proposé depuis la page web")
            pourquoi = lot[1]
        else:
            page.mettre("t_module", "Aucun cycle en cours")
            page.mettre("t_attend", seaux)
        info = self._message_actuel()
        if not info and etat.go_empeche:
            info = f"{etat.go_empeche[:1].upper()}{etat.go_empeche[1:]}."
        if not info and self.pilote is not None and self.pilote.actif:
            info = "Pilotage à distance en cours. Toucher un bouton pour l'arrêter."
        poste = self._etat_poste
        if not info and poste is not None and poste.etat == EN_PLACE:
            info = "Poste du fût : chariot en place, pas prêt."
        if not info:
            info = pourquoi
        if not info and self.nettoyage is not None:
            info = texte_enceinte(self.nettoyage.etat())
        page.mettre("t_info", info)
        if etat.en_pause:
            page.mettre("b_pause", "REPRENDRE", "marche")
        else:
            page.mettre("b_pause", "PAUSE", "pause")
        go_possible = (etat.attendent_go or lot is not None) and not etat.go_empeche
        page.mettre("b_go", "GO", "go" if go_possible else "inactif")
        page.mettre("b_compteurs", "COMPTEURS", "bouton")
        page.mettre("b_mode", "MODE", "bouton")

    def _composer_alarme(self, page: _Composition, alarmes: list[dict]) -> None:
        numeros = [alarme["id"] for alarme in alarmes]
        if self._alarme not in numeros:
            page.mettre("t_bandeau", "PLUS D'ALARME", "repos")
            return
        rang = numeros.index(self._alarme)
        alarme = alarmes[rang]
        page.mettre(
            "t_bandeau",
            f"ALARME {rang + 1}/{len(alarmes)} : {lisible(alarme['module'])}",
            "alarme",
        )
        page.mettre("t_message", alarme["message"])
        morceaux = decouper(
            alarme["quoi_faire"] or "Voir le bilan sur la page web.",
            ALARME.objet("t_quoi").longueur,
        )
        self._morceau %= len(morceaux)
        page.mettre("t_quoi", morceaux[self._morceau])
        quand = alarme["quand"]
        texte = f"le {quand[8:10]}/{quand[5:7]} à {quand[11:16]}"
        if len(morceaux) > 1:
            texte = f"Suite {self._morceau + 1}/{len(morceaux)}, {texte}"
        page.mettre("t_suite", self._message_actuel() or texte)
        page.mettre("b_retour", "RETOUR", "bouton")
        page.mettre("b_suite", "SUITE", "bouton" if len(morceaux) > 1 else "inactif")
        page.mettre("b_suivante", "SUIVANTE", "bouton" if len(alarmes) > 1 else "inactif")
        page.mettre("b_repare", "RÉPARÉ", "marche")

    def _composer_compteurs(self, page: _Composition) -> None:
        jour = self._aujourdhui().isoformat()

        def compter(requete: str) -> int:
            return self.registre.lire(requete, (jour,))[0]["n"]

        seaux = compter("SELECT COUNT(*) AS n FROM seaux_du_cycle WHERE substr(quand, 1, 10) = ?")
        futs = compter(
            "SELECT COUNT(*) AS n FROM cycles WHERE issue = 'termine' AND substr(fin, 1, 10) = ?"
        )
        alarmes = compter("SELECT COUNT(*) AS n FROM alarmes WHERE substr(quand, 1, 10) = ?")
        en_cours = self.registre.lire(
            "SELECT (SELECT COUNT(*) FROM seaux_du_cycle s WHERE s.cycle_id = c.id) AS n "
            "FROM cycles c WHERE c.fin IS NULL ORDER BY c.id DESC LIMIT 1"
        )
        page.mettre("t_titre", "COMPTEURS", "repos")
        page.mettre("t_seaux_jour", f"Seaux remplis aujourd'hui : {seaux}")
        page.mettre("t_futs_jour", f"Fûts vidés aujourd'hui : {futs}")
        if en_cours:
            page.mettre("t_seaux_fut", f"Seaux du fût en cours : {en_cours[0]['n']}")
        else:
            page.mettre("t_seaux_fut", "Pas de fût en cours")
        page.mettre("t_alarmes_jour", f"Alarmes aujourd'hui : {alarmes}")
        page.mettre("b_retour", "RETOUR", "bouton")

    def _texte_des_postes(self) -> tuple[str, str]:
        """Ce que la page d'état dit quand rien ne tourne, selon le mode de la machine : lot de
        seaux (puis lot de bocaux s'il n'y a rien à dire sur les seaux), laver les bocaux, ou nuit
        UV-ozone. Les autres modes (maïs) : rien."""
        mode = self.mode.actuel
        if mode == "uv_ozone" and self.mode_nuit is not None:
            return self.mode_nuit.texte_ecran()
        if mode == "lavage" and self.mode_bocaux is not None:
            refus = self.mode_bocaux.refus_lavage()
            return (
                ("Lavage des bocaux : prêt", "")
                if refus is None
                else ("Lavage des bocaux : pas prêt", refus)
            )
        if mode != "production":
            return "", ""
        seaux, pourquoi = "", ""
        if self.mode_seaux is not None:
            seaux, pourquoi = self.mode_seaux.texte_ecran()
        if self.mode_bocaux is not None:
            bocaux, raison = self.mode_bocaux.texte_ecran()
            if not pourquoi:
                # Les seaux sont prêts (ou absents) : on dit aussi pour les bocaux.
                pourquoi = f"{bocaux} : {raison}" if raison else ""
                if not seaux:
                    seaux = bocaux
        return seaux, pourquoi

    def _composer_mode(self, page: _Composition) -> None:
        page.mettre("t_titre", f"MODE : {self.mode.libelle.upper()}", "mode")
        page.mettre("t_info", self._message_actuel())
        for mode, libelle in MODES.items():
            choisi = mode == self.mode.actuel
            page.mettre(f"b_{mode}", libelle.upper(), "mode" if choisi else "bouton")
        page.mettre("b_enceinte", "ENCEINTE", "bouton" if self.nettoyage is not None else "inactif")
        page.mettre("b_retour", "RETOUR", "bouton")

    def _composer_poste(self, page: _Composition) -> None:
        poste = self._etat_poste
        if poste is None:
            return
        titre, couleur = TITRES_POSTE[poste.etat]
        page.mettre("t_titre", titre, couleur)
        page.mettre("t_poids", texte_pesee(poste))
        page.mettre("t_gestes", "" if poste.etat == PRET else GESTES_ECRAN)
        manque = "Il manque : " + " ; ".join(poste.manque) + "." if poste.manque else ""
        page.mettre("t_manque", self._message_actuel() or manque)
        possible = poste.etat == EN_PLACE and not poste.manque
        page.mettre("b_pret", "PRÊT", "marche" if possible else "inactif")
        page.mettre("b_retour", "RETOUR", "bouton")

    def _composer_nettoyage(self, page: _Composition) -> None:
        if self.nettoyage is None:
            return
        etat = self.nettoyage.etat()
        titre, couleur = TITRES_STORE[etat.store]
        if etat.fuite:
            titre, couleur = "FUITE D'OZONE", "alarme"
        elif etat.nuit == ERREUR:
            titre, couleur = "NUIT EN ERREUR", "alarme"
        elif etat.verrous_liberes and etat.store == FERME:
            titre, couleur = "VERROUS LIBRES", "pause"
        page.mettre("t_titre", titre, couleur)
        page.mettre("t_etat", ligne_nettoyage(etat))
        page.mettre("t_ozone", f"Ozone dedans {etat.ozone_dedans} · dehors {etat.ozone_dehors}")
        dernier = etat.messages[-1] if etat.messages else ""
        page.mettre("t_info", self._message_actuel() or dernier)
        ouvrir = etat.store == FERME and not etat.verrous_liberes
        if ouvrir:
            page.mettre(
                "b_store", "OUVRIR", "bouton" if etat.refus_ouverture is None else "inactif"
            )
        else:
            page.mettre("b_store", "FERMER", "bouton")
        page.mettre("b_lumiere", "LUMIÈRE", "marche" if etat.eclairage else "bouton")
        if etat.nuit == "attente_depart":
            page.mettre("b_nuit", "MAINTENANT", "go")
        else:
            heure = self.nettoyage.reglages.ozone.heure_depart
            page.mettre(
                "b_nuit", f"NUIT {heure}", "bouton" if etat.refus_nuit is None else "inactif"
            )
        page.mettre(
            "b_outre",
            "PASSER OUTRE",
            "pause" if etat.purge_alerte else ("bouton" if etat.purge else "inactif"),
        )
        page.mettre("b_retour", "RETOUR", "bouton")

    def _composer_question(self, page: _Composition) -> None:
        page.mettre("t_titre", "À CONFIRMER", "go")
        page.mettre("t_question", self._question[0] if self._question else "")
        page.mettre("b_non", "NON", "repos")
        page.mettre("b_oui", "OUI", "marche")
