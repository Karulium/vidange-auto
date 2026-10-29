"""Le porte-bocal de l'agitateur du Mycélium (module validé le 24/10/2026) : 2 mors qui serrent le
bocal, et un plateau qui le retourne d'un demi-tour (debout ↔ tête en bas). Tout est sur la carte
FluidNC n° 3.

    porte_bocal = PorteBocalFluidnc(reglages.machine, liaison, signaux, photo=..., controle=...)
    porte_bocal.serrer_bocal()          # chaque geste part sans attendre...
    porte_bocal.fini()                  # ...vrai quand il est fini ; ErreurEtape s'il a échoué
    porte_bocal.retourner_tete_en_bas()
    porte_bocal.remettre_debout()
    porte_bocal.ouvrir_mors()
    porte_bocal.approcher_mors()        # « Ø 98 » à faible courant (pose par la préhension)

Les mors (NEMA 17 sur TMC2209, vis gauche-droite) sont l'axe « mors » de machine.yaml : sa
position est l'écart entre les 2 mors.
- Ouvrir : prise d'origine de cet axe seul sur le fin de course « mors ouverts » (« $HY »), à
  chaque ouverture.
- Serrer : mors ouverts, puis palpage (« G38.3 ») jusqu'à l'arrêt par StallGuard (sortie DIAG
  du pilote sur l'entrée « probe »). L'écart à l'arrêt est le diamètre du bocal ; hors de la
  plage attendue, le bocal est absent, cassé ou mal posé : alerte avec photo. Le courant de
  serrage se règle sur le pilote (fluidnc/), pas ici.
- Approcher (pour la préhension, qui pose le bocal) : mors ouverts, puis à « Ø 98 » avec un
  courant faible : ils guident le bocal sans le serrer, et cèdent s'il les touche. Le courant de
  serrage est remis avant le geste des mors suivant.
- Les mors ne bougent jamais bocal tête en bas (il tomberait).

Le demi-tour (motoréducteur JGY370 par un pont en H : le sens du courant donne le sens) :
1. conditions : celles de l'agitateur (`verrou`, donné par le Mycélium : au demi-tour,
   manivelle en bas, chariot de remplissage écarté) et bocal serré ;
2. le doigt du verrou est retiré (électroaimant) et le moteur part dans le bon sens ;
3. le doigt est relâché après `relache_s` : il frotte, puis entre dans le trou suivant ; le
   moteur s'arrête quand le contact « verrou engagé » revient (sinon, au bout de
   `delai_max_s` : arrêt, alerte) ;
4. le capteur d'inclinaison doit dire ce qui était demandé ;
5. après chaque retour debout, photo de contrôle du bocal (`controle()`, analysée par la vision,
   tâche 22) : « douteux » = arrêt et alerte.
Un geste est rejouable : déjà dans la bonne position, verrou engagé, il ne fait que vérifier.
Ces verrous ne protègent que la MACHINE : la sécurité des personnes reste câblée.
"""

import time
from collections.abc import Callable
from typing import Literal

from vidange.chef import ErreurEtape
from vidange.fluidnc import Commande, Liaison
from vidange.griffe.bras import MM_PAR_M
from vidange.journal import donner_journal
from vidange.porte_bocal.signaux import Signaux, SignauxFluidnc
from vidange.reglages import CarteFluidnc, Machine

journal = donner_journal("porte_bocal")

Sens = Literal["tete_en_bas", "debout"]

# Noms des signaux (docs/entrees-sorties.yaml, fluidnc.yaml).
VERROU = "verrou_plateau_engage"
INCLINAISON = "inclinaison_bocal"
AIMANT = "electroaimant_verrou_plateau"
MOTEUR = {"tete_en_bas": "demi_tour_vers_tete_en_bas", "debout": "demi_tour_vers_debout"}
ENTREES = (VERROU, INCLINAISON)
SORTIES = (AIMANT, *MOTEUR.values())

QUOI_FAIRE_MORS = (
    "Regarder la vidéo du porte-bocal : les mors sont-ils bloqués ? Vérifier la carte n° 3 et "
    "le fin de course « mors ouverts », puis acquitter et donner le Go : le geste est refait."
)
QUOI_FAIRE_BOCAL = (
    "Regarder la photo du porte-bocal : bocal absent, cassé ou mal posé ? Remettre un bocal bien "
    "droit entre les mors (ou le retirer s'il est cassé), puis acquitter et donner le Go : le "
    "serrage est refait."
)
QUOI_FAIRE_VERROU = (
    "Le plateau du demi-tour ne s'est pas verrouillé : regarder la vidéo (plateau ou bocal "
    "bloqué, doigt du verrou coincé, contact « verrou engagé » débranché ?). Remettre le plateau "
    "en place s'il le faut, puis acquitter et donner le Go : le demi-tour est refait."
)
QUOI_FAIRE_INCLINAISON = (
    "Le capteur d'inclinaison ne dit pas ce qui était demandé : regarder le bocal (a-t-il "
    "tourné ?) et le capteur (réglé, branché ?). Corriger, puis acquitter et donner le Go."
)
QUOI_FAIRE_PHOTO = (
    "La photo de contrôle du bocal est douteuse (fissure, contour, bocal qui a bougé dans les "
    "mors) : la regarder sur la page web, changer le bocal s'il le faut, puis acquitter et "
    "donner le Go : le contrôle est refait."
)


def signaux_porte_bocal(liaison: Liaison, carte: CarteFluidnc) -> SignauxFluidnc:
    """Les signaux du porte-bocal sur sa carte (erreur claire s'il en manque dans fluidnc.yaml)."""
    return SignauxFluidnc(liaison, carte, ENTREES, SORTIES)


def _dire(tete_en_bas: bool) -> str:
    return "tête en bas" if tete_en_bas else "debout"


class PorteBocalFluidnc:
    def __init__(
        self,
        machine: Machine,
        liaison: Liaison,
        signaux: Signaux,
        horloge: Callable[[], float] = time.monotonic,
        photo: Callable[[str], object] = lambda raison: None,
        controle: Callable[[], str] = lambda: "bon",
        verrou: Callable[[], str | None] = lambda: None,
    ) -> None:
        """`photo(raison)` : photo notée avec une alerte. `controle()` : photo de contrôle du
        bocal après un retour debout, « bon » ou « douteux » (vision, tâche 22). `verrou()` :
        pourquoi l'agitateur interdit le demi-tour, ou None (Mycelium.refus_demi_tour)."""
        assert machine.porte_bocal is not None
        self.reglages = machine.porte_bocal
        self.liaison = liaison
        self.signaux = signaux
        self.verrou = verrou
        self._horloge = horloge
        self._photo = photo
        self._controle = controle
        mors = machine.axes["mors"]
        self._lettre = mors.lettre
        self._ferme, self._ouvert = mors.course
        self._geste: Literal["ouvrir", "serrer", "approcher", "demi_tour"] | None = None
        # Courant faible des mors (approche) pas encore remis à celui du serrage.
        self._courant_faible = False
        self._commandes: list[Commande] = []
        # Demi-tour en cours : sens voulu, départ, doigt sorti du trou, arrêt du moteur.
        self._voulu: Sens = "debout"
        self._depart = 0.0
        self._aimant = False
        self._degage = False
        self._arret: float | None = None

    # ------------------------------------------------------------ ce que disent les capteurs

    def diametre(self) -> float | None:
        """L'écart entre les mors (m), lu sur la carte."""
        valeur = self.liaison.etat.positions.get(self._lettre)
        return None if valeur is None else valeur / MM_PAR_M

    def serre(self) -> bool:
        """Un bocal est serré : mors arrêtés sur un diamètre dans la plage attendue."""
        diametre = self.diametre()
        return (
            self.liaison.etat.au_repos
            and diametre is not None
            and abs(diametre - self.reglages.diametre_bocal_m) <= self.reglages.tolerance_diametre_m
        )

    def ouverts(self) -> bool:
        """Mors arrêtés grands ouverts (sur leur fin de course)."""
        diametre = self.diametre()
        return (
            self.liaison.etat.au_repos
            and diametre is not None
            and diametre >= self._ouvert - self.reglages.tolerance_diametre_m
        )

    def _entree(self, nom: str) -> bool:
        valeur = self.signaux.entree(nom)
        if valeur is None:
            raise ErreurEtape(
                f"porte-bocal : entrée « {nom} » pas lue (carte « {self.liaison.nom} » muette ?)"
            )
        return valeur

    def tete_en_bas(self) -> bool:
        """Ce que dit le capteur d'inclinaison."""
        actionne = self._entree(INCLINAISON)
        return actionne == (self.reglages.inclinaison_actionne == "tete_en_bas")

    # ------------------------------------------------------------ les mors

    def ouvrir_mors(self) -> None:
        """Mors ouverts sur leur fin de course (origine reprise)."""
        self._mors("ouvrir", [*self._courant_serrage(), f"$H{self._lettre}"])

    def approcher_mors(self) -> None:
        """Mors ouverts, puis à « Ø 98 » à faible courant (pose du bocal par la préhension)."""
        approche = self.reglages.approche
        if approche is None:
            raise ErreurEtape("porte-bocal : pas d'« approche » dans machine.yaml")
        ecart = approche.ecart_m * MM_PAR_M
        f = 2 * self.reglages.palpage_m_s * 60 * MM_PAR_M
        self._mors(
            "approcher",
            [
                f"$H{self._lettre}",
                self._ligne_courant(approche.courant_faible_a),
                f"G90 G1 {self._lettre}{ecart:.3f} F{f:.0f}",
            ],
        )
        self._courant_faible = True

    def _ligne_courant(self, amperes: float) -> str:
        return f"$/axes/{(self._lettre or '').lower()}/motor0/tmc_2209/run_amps={amperes:g}"

    def _courant_serrage(self) -> list[str]:
        """Après une approche, le courant du serrage est remis (avant tout autre geste)."""
        approche = self.reglages.approche
        if not self._courant_faible or approche is None:
            return []
        self._courant_faible = False
        return [self._ligne_courant(approche.courant_serrage_a)]

    def serrer_bocal(self) -> None:
        """Mors ouverts, puis palpage jusqu'au bocal (arrêt par StallGuard)."""
        course = (self._ouvert - self._ferme) * MM_PAR_M
        # Les 2 mors avancent ensemble : l'écart se ferme 2 fois plus vite que chaque mors.
        f = 2 * self.reglages.palpage_m_s * 60 * MM_PAR_M
        self._mors(
            "serrer",
            [
                *self._courant_serrage(),
                f"$H{self._lettre}",
                f"G91 G38.3 {self._lettre}-{course:.3f} F{f:.0f}",
                "G90",
            ],
        )

    def _mors(self, geste: Literal["ouvrir", "serrer", "approcher"], lignes: list[str]) -> None:
        if self.tete_en_bas():
            raise ErreurEtape("mors refusés : le bocal est tête en bas (il tomberait)")
        textes = {"ouvrir": "ouverture des mors", "serrer": "serrage", "approcher": "approche"}
        journal.info("Porte-bocal : %s", textes[geste])
        self._geste = geste
        self._commandes = [self.liaison.envoyer(ligne) for ligne in lignes]

    def _mors_fini(self) -> bool:
        etat = self.liaison.etat
        if not all(commande.finie for commande in self._commandes):
            return False
        for commande in self._commandes:
            if commande.erreur is not None:
                self._geste = None
                raise ErreurEtape(
                    f"mors, « {commande.ligne} » : {commande.erreur}", QUOI_FAIRE_MORS
                )
        deja = max(commande.rapports_a_la_reponse for commande in self._commandes)
        if etat.rapports_recus <= deja or not etat.au_repos:
            return False
        geste, self._geste = self._geste, None
        if geste == "serrer" and not self.serre():
            diametre = self.diametre()
            voulu, tolerance = self.reglages.diametre_bocal_m, self.reglages.tolerance_diametre_m
            lu = "inconnu" if diametre is None else f"{diametre * MM_PAR_M:.1f} mm"
            raison = (
                f"bocal absent, cassé ou mal posé : mors arrêtés à {lu}, attendu "
                f"{voulu * MM_PAR_M:.0f} ± {tolerance * MM_PAR_M:.0f} mm"
            )
            self._photo(raison)
            raise ErreurEtape(f"porte-bocal : {raison}", QUOI_FAIRE_BOCAL)
        if geste == "serrer":
            journal.info("Porte-bocal : bocal serré (%.1f mm)", (self.diametre() or 0) * MM_PAR_M)
        return True

    # ------------------------------------------------------------ le demi-tour

    def retourner_tete_en_bas(self) -> None:
        self._demi_tour("tete_en_bas")

    def remettre_debout(self) -> None:
        self._demi_tour("debout")

    def _demi_tour(self, sens: Sens) -> None:
        refus = self.verrou()
        if refus is not None:
            raise ErreurEtape(f"demi-tour du bocal refusé : {refus}")
        if not self.serre():
            raise ErreurEtape("demi-tour du bocal refusé : bocal pas serré", QUOI_FAIRE_BOCAL)
        engage = self._entree(VERROU)
        tete_en_bas = self.tete_en_bas()
        self._voulu, self._geste = sens, "demi_tour"
        if engage and tete_en_bas == (sens == "tete_en_bas"):
            # Déjà fait (geste refait après une alarme) : seulement les vérifications.
            self._arret = self._horloge() - self.reglages.demi_tour.attente_inclinaison_s
            return
        if not engage:
            self._geste = None
            raise ErreurEtape(
                f"porte-bocal : verrou du plateau pas engagé avant le demi-tour (bocal "
                f"{_dire(tete_en_bas)})",
                QUOI_FAIRE_VERROU,
            )
        journal.info("Porte-bocal : demi-tour, bocal %s", _dire(sens == "tete_en_bas"))
        autre: Sens = "debout" if sens == "tete_en_bas" else "tete_en_bas"
        self.signaux.sortie(MOTEUR[autre], False)
        self.signaux.sortie(AIMANT, True)
        self.signaux.sortie(MOTEUR[sens], True)
        self._depart, self._aimant, self._degage, self._arret = self._horloge(), True, False, None

    def _couper(self) -> None:
        """Moteur et électroaimant coupés (même si la carte refuse une des lignes)."""
        for nom in (*MOTEUR.values(), AIMANT):
            try:
                self.signaux.sortie(nom, False)
            except ErreurEtape as erreur:
                journal.error("Porte-bocal : %s", erreur)
        self._aimant = False

    def _demi_tour_fini(self) -> bool:
        reglages = self.reglages.demi_tour
        maintenant = self._horloge()
        if self._arret is None:
            if self._aimant and maintenant - self._depart >= reglages.relache_s:
                self.signaux.sortie(AIMANT, False)
                self._aimant = False
            try:
                engage = self._entree(VERROU)
            except ErreurEtape:
                self._geste = None
                self._couper()
                raise
            if not engage:
                self._degage = True
            elif self._degage and not self._aimant:
                self._couper()
                self._arret = maintenant
            if self._arret is None:
                if maintenant - self._depart <= reglages.delai_max_s:
                    return False
                self._geste = None
                self._couper()
                if self._degage:
                    texte = f"le verrou du plateau n'est pas revenu en {reglages.delai_max_s:g} s"
                else:
                    texte = "le doigt du verrou n'est jamais sorti de son trou (électroaimant ?)"
                raise ErreurEtape(f"demi-tour du bocal : {texte}", QUOI_FAIRE_VERROU)
        if maintenant - self._arret < reglages.attente_inclinaison_s:
            return False
        self._geste = None
        voulu = self._voulu == "tete_en_bas"
        lu = self.tete_en_bas()
        if lu != voulu:
            raise ErreurEtape(
                f"capteur d'inclinaison : bocal {_dire(lu)}, il devait être {_dire(voulu)}",
                QUOI_FAIRE_INCLINAISON,
            )
        if not voulu and self._controle() != "bon":
            self._photo("photo de contrôle du bocal douteuse")
            raise ErreurEtape("porte-bocal : photo de contrôle du bocal douteuse", QUOI_FAIRE_PHOTO)
        return True

    # ------------------------------------------------------------ déroulé

    def fini(self) -> bool:
        """Vrai quand le geste est fini ; ErreurEtape s'il a échoué."""
        if self._geste is None:
            return True
        if self._geste == "demi_tour":
            return self._demi_tour_fini()
        return self._mors_fini()

    def arreter(self) -> None:
        """Arrêt du module : un demi-tour en cours est coupé (moteur, électroaimant)."""
        if self._geste == "demi_tour" and self._arret is None:
            self._couper()
        self._geste = None
