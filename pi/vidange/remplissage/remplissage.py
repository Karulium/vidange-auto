"""Le Remplissage : le chariot des seaux (module gelé le 27/10/2026).

    remplissage = Remplissage(reglages.machine, chariot, registre, vision=..., ...)
    remplissage.lancer(lambda: remplissage.geste_aller_a_la_pose("seau_a"))
    remplissage.geste_fini()                 # condition de fin d'une étape du chef
    prehension.lancer(lambda: remplissage.geste_poser_seau(prehension, "seau_a", "S1293"))

Le chariot roule en y entre le poste (sous la griffe) et le stockage. Il porte un plateau qui
monte, descend et tourne, deux barres qui tiennent ou centrent le seau, un pousseur qui range le
seau plein sur sa file, et une balance. Les gestes :
- poser un seau vide (avec la Préhension), dans l'ordre du point 5 de docs/decisions.md
  (Remplissage, corrigé le 30/10 au soir) : 1) chariot à y 0,50, barres à l'approche (hw 0,225)
  plateau ≤ 0,48, avant la pose ; la tête descend, le seau tenu ; 2) le plateau monte jusqu'au
  contact du fond, lu par la balance ; 3) centrage (barres en position) ; 4) barrière lumineuse
  libre : seau seul, la tête le lâche, les barres reviennent à l'approche, la balance vérifie
  qu'il n'y en a qu'un. Barrière coupée : prise double, les deux seaux sont séparés dans l'ordre
  a) à i) (la tête garde le seau du dessus, à rendre au stockage) ; à la fin, barrière libre ET
  un seul seau, sinon alarme. Pendant toute la pose, les barres restent sous les joues de
  l'élévateur (hw < 0,235) : elles ne s'ouvrent plus loin qu'après la descente du plateau ≤ 0,48 ;
- orienter l'anse : la caméra lit le QR du flanc (angle des oreilles de l'anse, corrigé de
  l'écart attaches/QR du seau) ; le plateau tourne pour les mettre à 45° (modulo 90°) des
  barres. Cet angle est gardé jusqu'à la poussée ;
- centrer : barres en position au contact du corps sous le rebord (+ un petit jeu), puis
  ouvertes ; l'alarme ALM du pilote d'une des 2 barres (elle force) arrête le geste et alerte ;
- ramener au vidage : y 0,42, plateau à la hauteur du vidage (bord du seau à 0,78) : la griffe
  vide le seau là (agitateur du mycélium fixe au-dessus du poste, 01/11/2026), jamais au poste
  plateau haut ; plus de descente du plateau pour rouler (règle des anneaux supprimée, 31/10) ;
- tourner pendant le versement de la griffe (`tourner_seau`) ;
- dosage du mycélium : le Mycélium mène le chariot (`ecarter`, `amener_au_dosage`) : du vidage
  au poste (y 0,135, bord du seau ≤ 0,68 : spray et micropore, tâches 39 et 40), puis au dosage
  (y 0,155, plateau à min(0,78 − h ; 0,575)), puis retour au vidage ;
- ranger : le plateau revient à l'angle de l'anse, va à la file plateau en bas, le pousseur pousse
  le seau vers le stockage ; le registre reçoit son poids (les doses et la variété viennent du
  Mycélium) et une photo ;
- ranger en haut (bande du haut du Stockage, tâche 35 bis), dans l'ordre a) à f) : a) bras de
  fermeture rangé ; b) barres ouvertes (elles traversent les joues plateau ≤ 0,48) ; c) chariot à
  y 0,215 ; d) plateau à 0,4985 (jamais hors de 0,496-0,501 pendant la poussée) ; e) poussée ;
  f) pousseur rentré, plateau redescendu. Le Stockage vérifie ensuite la photo du plafond ;
- mode couvercles (retourneur du lavage) et mode inspection des bocaux. Règle 14 : pendant les
  deux demi-tours de la tête de la griffe, le chariot est à y ≥ 0,515 (`geste_degager_griffe`,
  verrou branché dans la griffe par `brancher_griffe`) ; il ne revient à y 0,50 qu'après
  (`geste_revenir_au_retourneur`).

La règle 9 est branchée dans la préhension (`refus_prehension`, par module_remplissage) : sa tête
ne descend sous ≈ 0,84 au-dessus du chariot que barres ouvertes et tête du micropore rentrée, sauf
en mode couvercles (retourneur) et pendant la pose d'un seau vide (barres à l'approche ou serrées
par le geste du chariot lui-même ; le micropore est toujours vérifié).

Chaque pas est vérifié avant de partir (vidange.remplissage.regles) : un pas refusé met le module
en alarme, il ne bouge pas. Les gestes passent d'eux-mêmes par les bons détours (barres ouvertes
avant de monter au-dessus de 0,515 ou de pousser, plateau sous 0,48 pour traverser les joues...).

Les modules pas encore écrits sont des cases vides, derrière des fonctions simples (valeurs
prudentes par défaut) : bras du galet (tâche 41), bras du spray (39), caméra (QR du flanc :
`VisionSeau`, tâche 22 ter). Le Micropore (tâche 40) se branche par `brancher_micropore` : le
plateau ne monte ni ne descend que tête vue escamotée au ToF (règle 10), et ses gestes se jouent
au poste et au vidage (vidange.micropore). Sans lui, `micropore_rentre` dit ce qu'on a vu
(None : pas connu, le plateau ne bouge pas en hauteur).

Ces verrous ne protègent que la MACHINE : la sécurité des personnes reste câblée.
"""

import time
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from vidange.chef import ErreurEtape
from vidange.journal import donner_journal
from vidange.mycelium.regles import EtatChariot
from vidange.prehension.prehension import Attente, Prehension
from vidange.prehension.prehension import Geste as GestePrehension
from vidange.prehension.regles import Pose as PosePrehension
from vidange.prehension.tete import Pas as PasTete
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import FormatSeau, Machine
from vidange.remplissage.chariot import Chariot, Pas, Resultat
from vidange.remplissage.regles import Contexte, Pose, ReglesRemplissage

if TYPE_CHECKING:
    from vidange.griffe.griffe import Griffe
    from vidange.griffe.regles import Pose as PoseGriffe

journal = donner_journal("remplissage")

Geste = Generator[Pas, Resultat, None]
Mode = Literal["seaux", "couvercles", "inspection"]

QUOI_FAIRE = (
    "Regarder la vidéo du chariot de remplissage : est-il bloqué, le seau mal posé ? Corriger, "
    "puis acquitter et donner le Go : le geste est refait depuis le début."
)
QUOI_FAIRE_DOUBLE = (
    "Deux seaux emboîtés sont restés sur le plateau (ou la barrière lumineuse est encore coupée) : "
    "les séparer à la main, en rendre un au stockage, puis acquitter et donner le Go."
)
QUOI_FAIRE_SEPARATION = (
    "Les deux seaux emboîtés ne se séparent pas (plus de 35 N par barre) : la tête s'est arrêtée. "
    "Les séparer à la main, puis acquitter et donner le Go."
)
QUOI_FAIRE_QR = (
    "La caméra ne lit pas le QR du flanc du seau (ou lit un autre seau) : regarder la vidéo (QR "
    "sale, tourné vers le mur, mauvais seau ?). Corriger, puis acquitter et donner le Go."
)
QUOI_FAIRE_BARRIERE = (
    "La barrière lumineuse du chariot ne répond pas : vérifier son câble et la carte n° 2, puis "
    "acquitter et donner le Go."
)
QUOI_FAIRE_ALARME_BARRES = (
    "Le pilote d'une barre est en alarme (ALM) : elle force (seau mal centré, coincé, barre "
    "bloquée ?). Regarder la vidéo, dégager, vérifier le réglage du centrage du format, puis "
    "acquitter et donner le Go."
)
QUOI_FAIRE_BOCAL = (
    "La tête et la balance ne sont pas d'accord sur le poids du bocal posé : regarder la vidéo "
    "(bocal de travers, posé à côté ?). Corriger, puis acquitter et donner le Go."
)
QUOI_FAIRE_PURGE = (
    "Le versement dans le seau ouvert attend la fin de la purge de l'enceinte (store refermé) : "
    "attendre qu'elle finisse (page MODE, ENCEINTE), puis acquitter et donner le Go."
)
# Le geste protégé du chef (vidange.chef.chef.GESTES_PROTEGES) que demande le Remplissage.
VERSEMENT = "versement_seau_ouvert"
# Geste protégé du spray (vidange.spray) : la rotation du seau pendant la dose.
SPRAY = "spray_seau"

# Écart sous lequel deux positions sont égales (m ou °).
_EGAL = 1e-6


class VisionSeau(Protocol):
    """Ce que le Remplissage demande à la caméra (Vision : QR du flanc, tâche 22)."""

    def lire_seau(self) -> tuple[str, float] | None:
        """QR du seau sur le plateau, et angle des oreilles de son anse (° depuis +x, vue de
        dessus), déjà corrigé de l'écart attaches/QR enregistré pour ce seau ; None : pas lu."""
        ...


@dataclass
class SeauPlateau:
    """Le seau sur le plateau."""

    format: str
    # QR attendu (ou lu), cycle du registre.
    code: str | None = None
    cycle: int | None = None
    # Angle du plateau où les oreilles de l'anse sont à 45° des barres (None : pas orientée).
    angle_anse: float | None = None


def _m(valeur: float) -> str:
    return f"{valeur:.4f}".rstrip("0").rstrip(".").replace(".", ",")


class Remplissage:
    def __init__(
        self,
        machine: Machine,
        chariot: Chariot,
        registre: Registre | None = None,
        horloge: Callable[[], float] = time.monotonic,
        # Cases vides des autres modules (valeurs prudentes par défaut) :
        plateau_fut_en_place: Callable[[], bool] = lambda: False,
        refus_mycelium: Callable[[], str | None] = lambda: "agitateur du mycélium pas connu",
        bras_galet_range: Callable[[], bool | None] = lambda: None,
        bras_spray_sorti: Callable[[], bool] = lambda: False,
        micropore_rentre: Callable[[], bool | None] = lambda: None,
        vision: VisionSeau | None = None,
        photo: Callable[[str], object] = lambda raison: None,
        permission: Callable[[str], str | None] = lambda geste: None,
    ) -> None:
        """`plateau_fut_en_place` : PosteFut (plateau du fût au fond). `refus_mycelium` :
        Mycelium.refus_chariot (le chariot peut-il rouler près du poste ?). `bras_galet_range`,
        `bras_spray_sorti`, `micropore_rentre` : modules pas encore écrits (tâches 41, 39, 40).
        `vision` : QR du flanc et angle de l'anse. `photo(raison)` : photo notée au registre.
        `permission(geste)` : Chef.permission, demandée avant le versement dans le seau ouvert
        (« versement_seau_ouvert ») ; None = permis."""
        assert machine.remplissage is not None and machine.griffe is not None
        self.reglages = machine.remplissage
        self.formats = machine.griffe.formats
        self.course_a = machine.axes["plateau_a"].course
        self.course_z = machine.axes["plateau_z"].course
        self.durees = machine.durees
        self.retourneur = (
            None
            if machine.lavage is None or machine.lavage.couvercles is None
            else machine.lavage.couvercles.retourneur
        )
        self.regles = ReglesRemplissage(machine)
        self.chariot = chariot
        self.registre = registre
        self._horloge = horloge
        self._plateau_fut = plateau_fut_en_place
        self._refus_mycelium = refus_mycelium
        self._bras_galet = bras_galet_range
        self._bras_spray = bras_spray_sorti
        self._micropore = micropore_rentre
        self.vision = vision
        self._photo = photo
        self._permission = permission
        self.seau: SeauPlateau | None = None
        # Après une prise double : la tête tient le seau du dessus (à rendre au stockage).
        self.seau_du_dessus = False
        self.mode: Mode = "seaux"
        self.pose: Pose | None = None
        self.resultat: Resultat | None = None
        self.derniere_pesee_kg: float | None = None
        self._geste: Geste | None = None
        self._pas: Pas | None = None
        self._rotation = False
        # Pose d'un seau vide en cours : la tête descend barres à l'approche (règle 9).
        self._pose_en_cours = False
        # La tête de la griffe tourne-t-elle (règle 14, mode couvercles) ? Branché par
        # brancher_griffe ; sans griffe : non.
        self._griffe_tourne: Callable[[], bool] = lambda: False
        # Le Micropore (tâche 40, brancher_micropore) : ses gestes au poste et au vidage, ce qu'il
        # fait quand le seau est rangé et à l'arrêt du module.
        self.micropore_branche = False
        self._au_poste: Callable[[], Geste] | None = None
        self._au_vidage: Callable[[], Geste] | None = None
        self._fin_du_seau: Callable[[SeauPlateau], None] | None = None
        self._a_l_arret: list[Callable[[], None]] = []

    # ------------------------------------------------------------ état

    def contexte(self) -> Contexte:
        seau = self.seau
        hauteur = None if seau is None else self.formats[seau.format].hauteur
        return Contexte(
            plateau_fut_en_place=self._plateau_fut(),
            refus_mycelium=self._refus_mycelium(),
            bras_galet_range=self._bras_galet(),
            bras_spray_sorti=self._bras_spray(),
            hauteur_seau=hauteur,
            micropore_escamote=self._micropore(),
        )

    def position(self) -> Pose:
        return self.chariot.position()

    def libre(self) -> bool:
        """Aucun geste en cours (le chariot peut recevoir un autre geste)."""
        self.geste_fini()
        return self._geste is None

    def format(self, nom: str) -> FormatSeau:
        seau = self.formats.get(nom)
        if seau is None:
            raise ErreurEtape(f"remplissage : format de seau inconnu « {nom} »")
        return seau

    def plateau_au_vidage(self, format: str) -> float:
        """Plateau au vidage par la griffe : bord du seau à haut_z (0,78), 0,575 au plus."""
        seau = self.format(format)
        assert seau.hauteur is not None
        return min(seau.haut_z - seau.hauteur, self.course_z[1])

    def plateau_au_poste(self, format: str) -> float:
        """Plateau au poste (sous le bocal du mycélium) : bord du seau à haut_z, mais jamais
        au-dessus de verrous → poste_bord_max_z (0,68) ; 0,575 au plus."""
        seau = self.format(format)
        assert seau.hauteur is not None
        bord = min(seau.haut_z, self.reglages.verrous.poste_bord_max_z)
        return min(bord - seau.hauteur, self.course_z[1])

    def plateau_approche(self, format: str) -> float:
        """Plateau avant la pose : sous la hauteur de pose (et sous le contact d'une prise
        double), pas au-dessus des joues de l'élévateur (0,48)."""
        reglages = self.reglages
        return min(
            reglages.verrous.joues_plateau_max_z,
            reglages.formats[format].pose_plateau_z - reglages.pose_seau.plateau_sous_pose_m,
        )

    def poids_un_seau(self, format: str) -> float:
        tare = self.format(format).tare_kg
        return tare if tare is not None else self.reglages.pesee.seau_vide_kg

    # ------------------------------------------------------------ déroulé d'un geste

    def lancer(self, geste: Callable[[], Geste]) -> None:
        """Action d'une étape : le geste part depuis là où est le chariot."""
        if self._geste is not None:
            texte = "un geste" if self._pas is None else f"« {self._pas.texte} »"
            raise ErreurEtape(f"le chariot de remplissage fait déjà {texte}", QUOI_FAIRE)
        self._rotation = False
        self.pose = self.chariot.position()
        self._geste = geste()
        self._pas = None
        self._suivant(None)

    def _suivant(self, resultat: Resultat | None) -> None:
        assert self._geste is not None
        try:
            pas = next(self._geste) if resultat is None else self._geste.send(resultat)
        except StopIteration:
            self._geste = self._pas = None
            return
        except ErreurEtape:
            self._geste = self._pas = None
            raise
        self._envoyer(pas)

    def _envoyer(self, pas: Pas) -> None:
        assert self.pose is not None
        self._pas = pas
        cible = self.pose.avec(**pas.cibles)
        if pas.cibles:
            refus = self.regles.refus_mouvement(self.pose, cible, self.contexte())
            if refus is None:
                refus = self._refus_regle_14(cible)
            if refus is not None:
                self._geste = self._pas = None
                raise ErreurEtape(f"remplissage, « {pas.texte} » refusé : {refus}", QUOI_FAIRE)
        journal.debug("Remplissage : %s", pas.texte)
        self.chariot.executer(pas, cible)

    def geste_fini(self) -> bool:
        """Condition de fin des étapes : fait partir les pas l'un après l'autre."""
        while self._geste is not None:
            pas = self._pas
            alarmes = self.chariot.alarmes_barres() if pas is not None else []
            if pas is not None and "barres" in pas.cibles and alarmes:
                self.arreter()
                barres = " et ".join(f"de la barre {barre}" for barre in alarmes)
                self._photo(f"alarme du pilote {barres}")
                raise ErreurEtape(
                    f"remplissage : alarme du pilote {barres} pendant « {pas.texte} » "
                    f"({'elles forcent' if len(alarmes) > 1 else 'elle force'})",
                    QUOI_FAIRE_ALARME_BARRES,
                )
            if not self.chariot.fini():
                return False
            resultat = self.chariot.resultat()
            self.pose, self.resultat = resultat.pose, resultat
            if resultat.poids_kg is not None:
                self.derniere_pesee_kg = resultat.poids_kg
            self._suivant(resultat)
        return True

    def pauser(self) -> None:
        self.chariot.pauser()

    def reprendre(self) -> None:
        self.chariot.reprendre()

    def arreter(self) -> None:
        self._geste = self._pas = None
        self._rotation = False
        self._pose_en_cours = False
        self.chariot.arreter()
        for arreter in self._a_l_arret:
            arreter()

    def _dans_prehension(self, texte: str, geste: Callable[[], Geste]) -> GestePrehension:
        """Un geste du chariot au milieu d'un geste de la préhension : elle l'attend."""
        self.lancer(geste)
        delai = self.durees["remplissage_geste_max"]
        yield Attente(
            f"chariot de remplissage : {texte}",
            self.geste_fini,
            delai,
            f"chariot de remplissage : « {texte} » pas fini en {delai:g} s",
            QUOI_FAIRE,
        )

    # ------------------------------------------------------------ morceaux de gestes

    def _pose(self) -> Pose:
        assert self.pose is not None
        return self.pose

    def _plateau_en_bas(self) -> Geste:
        if not self.regles.en_bas(self._pose()):
            yield Pas("plateau en bas", {"z": self.course_z[0]})

    def _pousseur_rentre(self) -> Geste:
        # Règle 12 : le pousseur rentre à toute hauteur du plateau.
        if not self.regles.pousseur_rentre(self._pose()):
            yield Pas("pousseur rentré", {"pousseur": self.reglages.pousseur_rentre_m})

    def _barres(
        self, hw: float, texte: str = "barres", centrage: bool = False, plateau_fixe: bool = False
    ) -> Geste:
        """Barres à hw ; le plateau descend d'abord s'il le faut (joues de l'élévateur, barres
        fermées au-dessus de 0,515), puis remonte où il était si c'est permis. `centrage` : à la
        vitesse lente du centrage. `plateau_fixe` : le plateau ne bouge pas (prise double) ; un
        pas que les verrous refusent met le module en alarme."""
        pose = self._pose()
        if abs(pose.barres - hw) <= _EGAL and abs(pose.barre_allee - hw) <= _EGAL:
            return
        if plateau_fixe:
            yield Pas(texte, {"barres": hw}, vitesse="centrage" if centrage else None)
            return
        v = self.reglages.verrous
        bas = min(pose.barres, pose.barre_allee, hw)
        haut = max(pose.barres, pose.barre_allee, hw)
        plafond = pose.z
        if bas <= v.joues_barres[1] + _EGAL and haut >= v.joues_barres[0] - _EGAL:
            plafond = min(plafond, v.joues_plateau_max_z)
        if hw < v.barres_ouvertes_min - _EGAL:
            plafond = min(plafond, v.barres_ouvertes_au_dessus_z)
        z = pose.z
        if plafond < z - _EGAL:
            yield Pas("plateau plus bas, pour bouger les barres", {"z": plafond})
        if centrage:
            yield Pas(texte, {"barres": hw}, vitesse="centrage")
        else:
            yield Pas(texte, {"barres": hw})
        if plafond < z - _EGAL:
            remonte = self._pose().avec(z=z)
            if self.regles.refus_pose(remonte, self.contexte()) is None:
                yield Pas("plateau remonté", {"z": z})

    def _barres_ouvertes(self) -> Geste:
        if not self.regles.barres_ouvertes(self._pose()):
            yield from self._barres(self.reglages.barres.ouvertes_m, "barres ouvertes")

    def _plateau(self, z: float, texte: str) -> Geste:
        """Plateau à z ; pousseur rentré et barres ouvertes d'abord s'il le faut."""
        pose = self._pose()
        if abs(pose.z - z) <= _EGAL:
            return
        v = self.reglages.verrous
        if z > pose.z:
            if z > self.reglages.plateau_en_bas_z:
                yield from self._pousseur_rentre()
            ouvrir = z > v.barres_ouvertes_au_dessus_z + _EGAL or (
                z > v.joues_plateau_max_z + _EGAL and self.regles.une_barre_dans_les_joues(pose)
            )
            if ouvrir:
                yield from self._barres_ouvertes()
        yield Pas(texte, {"z": z})

    def _rouler(self, y: float, texte: str) -> Geste:
        """Rouler jusqu'à y ; le plateau descend d'abord si le trajet le demande."""
        pose = self._pose()
        if abs(pose.y - y) <= self.reglages.tolerance_y_m:
            return
        if self.regles.refus_mouvement(pose, pose.avec(y=y), self.contexte()) is not None:
            yield from self._plateau_en_bas()
        yield Pas(texte, {"y": y})

    def _a_la_place(self, y: float, texte: str) -> Geste:
        """Pousseur rentré, plateau en bas si le trajet le demande, puis rouler."""
        yield from self._pousseur_rentre()
        yield from self._rouler(y, texte)

    def _peser(self, texte: str) -> Geste:
        yield Pas(texte, pesee=True)

    def _orienter(self, angle: float, texte: str) -> Geste:
        pose = self._pose()
        debut, fin = self.course_a
        if not debut <= angle <= fin:
            angle -= 360 * round((angle - (debut + fin) / 2) / 360)
        if abs(pose.a - angle) > self.reglages.tolerance_deg:
            yield Pas(texte, {"a": angle})

    # ------------------------------------------------------------ pour le Mycélium

    def etat(self) -> EtatChariot | None:
        """Où est le chariot (ChariotRemplissage du Mycélium) ; fait avancer le geste."""
        immobile = self.geste_fini() and not self._rotation
        try:
            pose = self.chariot.position()
        except ErreurEtape:
            return None
        y = pose.y
        if not immobile and self.pose is not None:
            # En route : le y le plus près du poste (départ ou position lue), par prudence.
            y = min(y, self.pose.y)
        return EtatChariot(y=y, plateau_z=pose.z, immobile=immobile)

    def ecarter(self) -> None:
        """Le recul pour le demi-tour du bocal (y ≥ 0,40) : au vidage (y 0,42), plateau où il
        est."""
        self.lancer(self.geste_ecarter)

    def amener_au_dosage(self, plateau_z: float) -> None:
        self.lancer(lambda: self.geste_au_dosage(plateau_z))

    def geste_ecarter(self) -> Geste:
        pose = self._pose()
        if pose.y < self.reglages.ecarte_y - self.reglages.tolerance_y_m:
            yield from self._a_la_place(self.reglages.vidage_y, "retour au vidage")

    def geste_au_dosage(self, plateau_z: float) -> Geste:
        """Le seau au poste (y 0,135, bord du seau ≤ 0,68 : spray et micropore, tâches 39 et 40,
        cases vides), puis au dosage : y 0,155, plateau à min(0,78 − h ; 0,575), barres
        ouvertes, pousseur rentré."""
        yield from self._barres_ouvertes()
        yield from self._pousseur_rentre()
        if self.seau is not None:
            poste = self.plateau_au_poste(self.seau.format)
            if self._pose().z > poste:
                yield Pas("plateau à la hauteur du poste", {"z": poste})
            yield from self._rouler(self.reglages.poste_y, "seau au poste (spray, micropore)")
            if self._au_poste is not None:
                # Micropore (tâche 40) : tour de repérage et rangées du haut, au premier passage.
                yield from self._au_poste()
        yield from self._a_la_place(self.reglages.dosage_y, "seau sous le bocal du mycélium")
        yield from self._plateau(plateau_z, "plateau à la hauteur du dosage")

    # ------------------------------------------------------------ pour la Griffe

    def seau_au_vidage(self) -> bool:
        """Un seau au vidage (y 0,42), plateau à sa hauteur, rien en cours : la griffe peut
        verser."""
        if not self.libre() or self.seau is None or self.pose is None:
            return False
        pose = self.chariot.position()
        return (
            self.regles.a(pose.y, self.reglages.vidage_y)
            and abs(pose.z - self.plateau_au_vidage(self.seau.format)) <= self.reglages.tolerance_m
        )

    def tourner_seau(self, tourne: bool) -> None:
        """Le seau tourne pendant le versement de la griffe (sans fin, jusqu'à l'arrêt)."""
        if not tourne:
            if self._rotation:
                self.arreter()
            return
        refus = self.refus_versement()
        if refus is not None:
            raise ErreurEtape(f"remplissage : versement refusé : {refus}", QUOI_FAIRE_PURGE)
        if self.mode != "seaux":
            raise ErreurEtape(f"remplissage : pas de rotation en mode « {self.mode} »")
        pose = self.chariot.position()
        debut, fin = self.course_a
        # Vers le bout de la course le plus loin : le Pi revient près de 0 entre deux seaux.
        cible = fin if fin - pose.a >= pose.a - debut else debut

        def tourner() -> Geste:
            yield Pas("le seau tourne (versement)", {"a": cible})

        self.lancer(tourner)
        self._rotation = True

    def refus_versement(self) -> str | None:
        """Le chef permet-il le versement dans le seau ouvert (purge du Nettoyage) ?"""
        return self._permission(VERSEMENT)

    def versement_permis(self) -> bool:
        return self.refus_versement() is None

    def geste_tourner(self, duree_s: float) -> Geste:
        """Le seau tourne pendant tant de secondes (versement du simulateur, essais)."""
        refus = self.refus_versement()
        if refus is not None:
            raise ErreurEtape(f"remplissage : versement refusé : {refus}", QUOI_FAIRE_PURGE)
        pose = self._pose()
        tour = self.reglages.vitesses.rotation * duree_s
        sens = -1 if pose.a > 0 else 1
        yield from self._orienter(pose.a + sens * tour, "le seau tourne (versement)")

    def tourner_pour_spray(self, degres: float) -> None:
        """Pour le spray (tâche 39) : le seau tourne de `degres` pendant la dose (le bras est
        sorti : seule la rotation est permise). Pas pendant la purge (permission du chef)."""
        refus = self._permission(SPRAY)
        if refus is not None:
            raise ErreurEtape(f"remplissage : spray refusé : {refus}", QUOI_FAIRE_PURGE)
        pose = self.chariot.position()
        debut, fin = self.course_a
        sens = 1 if pose.a + degres <= fin else -1

        def tourner() -> Geste:
            yield from self._orienter(pose.a + sens * degres, "le seau tourne (spray)")

        self.lancer(tourner)

    # ------------------------------------------------------------ pour le Lavage (retourneur)

    def regler_barres(self, ecart_m: float) -> None:
        if self.mode != "couvercles":
            raise ErreurEtape("remplissage : barres du retourneur hors du mode couvercles")
        self.lancer(lambda: self._barres(ecart_m, "barres du retourneur"))

    def ecart_barres(self) -> float | None:
        if not self.libre():
            return None
        return self.chariot.position().barres

    def chariot_en_place(self) -> bool:
        """Mode couvercles : chariot à y 0,50, plateau fixe à 0,459, arrêté."""
        if self.mode != "couvercles" or not self.libre():
            return False
        pose = self.chariot.position()
        reglage = self.reglages.couvercles
        return (
            self.regles.a(pose.y, reglage.y)
            and abs(pose.z - reglage.plateau_z) <= self.reglages.tolerance_m
        )

    def barriere_coupee(self) -> bool | None:
        return self.chariot.barriere_coupee()

    # ------------------------------------------------------------ règle 14 (mode couvercles)

    def _refus_regle_14(self, cible: Pose) -> str | None:
        """Le chariot ne revient sous y 0,515 qu'après les demi-tours de la tête de la griffe."""
        y_min = self.reglages.couvercles.y_demi_tour_griffe_min
        if self.mode != "couvercles" or cible.y >= y_min - self.reglages.tolerance_y_m:
            return None
        if self._griffe_tourne():
            return (
                f"règle 14 : la tête de la griffe tourne, le chariot reste à y ≥ {_m(y_min)} "
                "jusqu'à la fin de ses demi-tours"
            )
        return None

    def refus_demi_tour_griffe(self) -> str | None:
        """Règle 14 : en mode couvercles, la tête de la griffe ne tourne que chariot arrêté à
        y ≥ 0,515 (sinon la raclette touche le moteur de la barre côté allée)."""
        if self.mode != "couvercles":
            return None
        y_min = self.reglages.couvercles.y_demi_tour_griffe_min
        if not self.libre():
            return f"règle 14 : le chariot de remplissage bouge (il doit être à y ≥ {_m(y_min)})"
        y = self.chariot.position().y
        if y < y_min - self.reglages.tolerance_y_m:
            return (
                f"règle 14 : chariot de remplissage à y {_m(y)}, il doit être à y ≥ {_m(y_min)} "
                "pendant les demi-tours de la tête de la griffe"
            )
        return None

    def geste_degager_griffe(self) -> Geste:
        """Mode couvercles : le chariot recule à y 0,515 (plateau fixe) avant les deux demi-tours
        de la tête de la griffe."""
        if self.mode != "couvercles":
            raise ErreurEtape("remplissage : pas en mode couvercles")
        y = self.reglages.couvercles.y_demi_tour_griffe_min
        yield from self._a_la_place(y, "chariot écarté pour les demi-tours de la griffe")

    def geste_revenir_au_retourneur(self) -> Geste:
        """Mode couvercles : retour à y 0,50, seulement après les demi-tours de la griffe."""
        if self.mode != "couvercles":
            raise ErreurEtape("remplissage : pas en mode couvercles")
        yield from self._a_la_place(self.reglages.couvercles.y, "chariot au retourneur")

    def brancher_griffe(self, griffe: "Griffe") -> None:
        """La griffe applique la règle 14 à chacun de ses pas qui tourne la tête ; le chariot ne
        revient au retourneur qu'une fois la tête arrêtée."""
        self._griffe_tourne = griffe.tete_tourne

        def refus(depart: "PoseGriffe", arrivee: "PoseGriffe") -> str | None:
            if abs(arrivee.a - depart.a) <= _EGAL:
                return None
            return self.refus_demi_tour_griffe()

        griffe.verrou_chariot = refus

    # ------------------------------------------------------------ pour les autres modules

    def place_permise(self, y: float) -> bool:
        """Le chariot peut-il aller en y (règle 7) : plateau du fût en place, ou bout du chariot
        côté allée assez loin de la 3e file (axe du plateau ≤ 0,475) ?"""
        if self._plateau_fut():
            return True
        bout_max = self.regles.bout_max_y
        return y + self.reglages.verrous.bout_y_m <= bout_max + _EGAL

    def refus_bras_galet(self) -> str | None:
        """Pour la fermeture (tâche 41) : le bras du galet ne tourne que plateau ≤ 0,26."""
        return self.regles.refus_bras_galet(self.chariot.position())

    def refus_bras_spray(self) -> str | None:
        """Pour le spray (tâche 39) : pivot du bras seulement plateau assez bas, barres
        ouvertes."""
        return self.regles.refus_bras_spray(self.chariot.position(), self.contexte().hauteur_seau)

    def refus_descente_prehension(self) -> str | None:
        """Pour la préhension : descendre sous 0,84 au-dessus du chariot ?"""
        if not self.libre():
            return "le chariot de remplissage bouge"
        return self.regles.refus_descente_prehension(self.chariot.position(), self._micropore())

    def refus_prehension(self, depart: PosePrehension, arrivee: PosePrehension) -> str | None:
        """Verrou de la préhension (`Prehension.verrou_chariot`, règle 9) : sa face ne descend
        sous ≈ 0,84 au-dessus du chariot que barres ouvertes et tête du micropore rentrée. Sauf en
        mode couvercles (retourneur : vérifié par le fil Lavage le 25/10) et pendant la pose d'un
        seau vide (barres à l'approche ou serrées par le geste du chariot lui-même, décisions,
        Remplissage, point 5) : là, seul le micropore est vérifié."""
        v = self.reglages.verrous
        if arrivee.z >= depart.z - _EGAL or arrivee.z >= v.prehension_libre_z - _EGAL:
            return None
        if self.mode == "couvercles":
            return None
        if self._pose_en_cours:
            return self.regles.refus_micropore(self._micropore())
        if not self.libre():
            if self.regles.au_dessus_du_chariot(arrivee.x, arrivee.y, None):
                return (
                    f"descente sous {_m(v.prehension_libre_z)} au-dessus du chariot de "
                    "remplissage refusée : il bouge"
                )
            return None
        pose = self.chariot.position()
        if not self.regles.au_dessus_du_chariot(arrivee.x, arrivee.y, pose):
            return None
        return self.regles.refus_descente_prehension(pose, self._micropore())

    def brancher_micropore(
        self,
        escamotee: Callable[[], bool | None],
        au_poste: Callable[[], Geste],
        au_vidage: Callable[[], Geste],
        fin_du_seau: Callable[[SeauPlateau], None],
        arreter: Callable[[], None],
    ) -> None:
        """Le Micropore (tâche 40) : tête vue escamotée (règles 9 et 10), ses gestes au poste
        (après le trajet vers le poste, avant le dosage) et au vidage (avant la hauteur du
        vidage), le seau rangé, l'arrêt."""
        self._micropore = escamotee
        self._au_poste, self._au_vidage, self._fin_du_seau = au_poste, au_vidage, fin_du_seau
        self._a_l_arret.append(arreter)
        self.micropore_branche = True

    def brancher_prehension(self, prehension: Prehension) -> None:
        """La préhension applique la règle 9 à chacun de ses pas (et en mode manuel)."""
        prehension.verrou_chariot = self.refus_prehension

    # ------------------------------------------------------------ les gestes des seaux

    def geste_aller_a_la_pose(self, format: str) -> Geste:
        """Pose 1) : chariot à y 0,50, pousseur rentré, barres à l'approche (hw 0,225) plateau
        ≤ 0,48, puis plateau d'approche, sous la hauteur de pose (décisions, Remplissage, point 5).
        Les barres traversent les joues de l'élévateur ici, avant la pose."""
        reglage = self.reglages.formats.get(format)
        if reglage is None:
            raise ErreurEtape(f"remplissage : format de seau inconnu « {format} »")
        if self.seau is not None:
            raise ErreurEtape("remplissage : il y a déjà un seau sur le plateau", QUOI_FAIRE)
        self.mode = "seaux"
        yield from self._a_la_place(self.reglages.pose_y, "chariot à la pose du seau vide")
        yield from self._barres(
            self.reglages.pose_seau.barres_approche_hw_m, "pose 1) : barres à l'approche"
        )
        yield from self._plateau(self.plateau_approche(format), "pose 1) : plateau d'approche")

    def geste_poser_seau(
        self, prehension: Prehension, format: str, code: str | None = None, cycle: int | None = None
    ) -> GestePrehension:
        """Joué par la préhension, qui tient un seau vide : le poser sur le plateau (décisions,
        Remplissage, point 5). La tête descend, le seau tenu ; 2) le plateau monte jusqu'au
        contact (balance) ; 3) centrage ; 4) barrière libre : seau seul ; coupée : prise double,
        les deux seaux sont séparés (la tête garde celui du dessus). Le plateau et les barres ne
        bougent que par ce geste ; les barres restent sous les joues de l'élévateur."""
        reglages = self.reglages
        reglage = reglages.formats[format]
        if not self.libre():
            raise ErreurEtape("remplissage : le chariot bouge, pas de pose", QUOI_FAIRE)
        pose = self.chariot.position()
        self.pose = pose
        approche = reglages.pose_seau.barres_approche_hw_m
        place = (
            self.regles.a(pose.y, reglages.pose_y)
            and abs(pose.z - self.plateau_approche(format)) <= reglages.tolerance_m
            and abs(pose.barres - approche) <= reglages.tolerance_m
            and abs(pose.barre_allee - approche) <= reglages.tolerance_m
        )
        if not place:
            raise ErreurEtape(
                "remplissage : chariot pas prêt pour la pose du seau vide (y 0,50, barres à "
                "l'approche, plateau d'approche)",
                QUOI_FAIRE,
            )
        refus = self.regles.refus_micropore(self._micropore())
        if refus is not None:
            raise ErreurEtape(f"remplissage : {refus}", QUOI_FAIRE)
        yield from prehension.aller(reglages.axe_x, pose.y)
        self._pose_en_cours = True
        try:
            # Fond d'un seul seau à la hauteur de pose : le plateau monte le chercher.
            yield from self._descendre_tete(
                prehension, reglage.pose_plateau_z + reglages.face_au_dessus_plateau_m
            )
            haut = reglage.pose_plateau_z + reglages.pose_seau.contact_au_dessus_m
            yield from self._dans_prehension(
                "pose 2) : plateau au contact",
                lambda: self._toucher(
                    "pose 2) : le plateau monte jusqu'au contact du seau",
                    haut,
                    "le plateau n'a pas touché le seau tenu par la tête",
                    QUOI_FAIRE,
                ),
            )
            self.seau = SeauPlateau(format, code, cycle)
            yield from self._barres_pose(self._centrage(format), "pose 3) : centrage")
            double = self._barriere()
            if double:
                journal.warning("Remplissage : barrière coupée après la pose : prise double")
                yield from self._separer(prehension, format)
            else:
                yield from prehension.lacher()
                yield from prehension.monter()
        finally:
            self._pose_en_cours = False
        # La tête est partie : les barres lâchent le seau (sans traverser les joues), l'anse
        # sera orientée avant le centrage suivant.
        yield from self._barres_pose(
            approche, "pose : barres à l'approche (lâcher)", centrage=False
        )
        if double:
            return
        yield from self._dans_prehension("pesée du seau", lambda: self._peser("pesée"))
        self._un_seul_seau(format)
        journal.info("Remplissage : seau vide posé (%s)", code or format)

    def _centrage(self, format: str) -> float:
        return self.reglages.formats[format].centrage_hw_m + self.reglages.barres.jeu_centrage_m

    def _barres_pose(self, hw: float, texte: str, centrage: bool = True) -> GestePrehension:
        """Barres à hw pendant la pose, plateau fixe (sous les joues : un pas refusé par les
        verrous met le module en alarme)."""
        return self._dans_prehension(
            texte, lambda: self._barres(hw, texte, centrage=centrage, plateau_fixe=True)
        )

    def _descendre_tete(self, prehension: Prehension, z: float) -> GestePrehension:
        """La tête descend, le seau tenu, jusqu'à ce que sa face soit à z (rien dessous : le
        plateau est plus bas) ; lente sur les derniers cm, arrêt sur un choc."""
        assert prehension.pose is not None
        approche = z + prehension.reglages.descente.approche_m
        if prehension.pose.z > approche + _EGAL:
            yield PasTete("pose : la tête descend avec le seau", {"z": approche}, choc=True)
        yield PasTete(
            "pose : la tête à la hauteur de pose", {"z": z}, vitesse="approche", choc=True
        )

    def _barriere(self) -> bool:
        coupee = self.chariot.barriere_coupee()
        if coupee is None:
            raise ErreurEtape("barrière lumineuse du chariot pas lue", QUOI_FAIRE_BARRIERE)
        return coupee

    def _un_seul_seau(self, format: str) -> None:
        poids = self.derniere_pesee_kg
        un = self.poids_un_seau(format)
        if poids is None or poids > self.reglages.pesee.seuil_deux_seaux * un:
            lu = "pas de pesée" if poids is None else f"{poids:.2f} kg"
            self._photo("deux seaux sur le plateau")
            raise ErreurEtape(
                f"remplissage : plus d'un seau sur la balance ({lu}, un seau ≈ {un:g} kg)",
                QUOI_FAIRE_DOUBLE,
            )

    def _separer(self, prehension: Prehension, format: str) -> GestePrehension:
        """Prise double (décisions, Remplissage, point 5, corrigé le 30/10 au soir) : la tête
        tient les deux seaux emboîtés, le plateau est au contact du seau du dessous (Hc), les
        barres déjà serrées au centrage. a) lâcher : chaque barre s'écarte de 1,5 cm ; b) le
        plateau descend de 5 cm ; c) la tête descend de 2,8 cm (lèvre du seau du dessous au
        niveau de la rainure des barres) ; d) les barres serrent sur la lèvre (entraxe = Ø haut
        + 6 mm) ; e) le plateau monte jusqu'au contact du fond (balance) ; f) la tête remonte avec
        le seau du haut (au plus 35 N par barre) ; g) lâcher ; h) le plateau monte de 2,8 cm ;
        i) contrôle : barrière libre ET un seul seau sur la balance ; puis centrage, comme un seau
        seul. Les barres restent sous les joues de l'élévateur (hw < 0,235) tout du long."""
        reglages = self.reglages
        double, barres = reglages.prise_double, reglages.barres
        seau = self.format(format)
        levre = max(seau.rayon_haut + barres.jeu_rainure_m / 2, self.regles.courses["barres"][0])

        def tete(texte: str, dz: float, **options: object) -> PasTete:
            assert prehension.pose is not None
            return PasTete(texte, {"z": prehension.pose.z + dz}, **options)  # type: ignore[arg-type]

        def plateau_de(texte: str, dz: float, pesee: bool = False) -> GestePrehension:
            def geste() -> Geste:
                yield Pas(texte, {"z": self._pose().z + dz})
                if pesee:
                    yield from self._peser("pesée")

            return self._dans_prehension(texte, geste)

        def lacher(texte: str) -> GestePrehension:
            return self._barres_pose(self._pose().barres + barres.lacher_m, texte, centrage=False)

        yield from lacher("prise double a) : lâcher (barres)")
        yield from plateau_de("prise double b) : le plateau descend", -double.descente_plateau_m)
        yield tete(
            "prise double c) : la tête descend",
            -double.descente_tete_m,
            vitesse="approche",
            choc=True,
        )
        yield from self._barres_pose(
            levre, "prise double d) : barres serrées sur la lèvre du seau du dessous"
        )
        haut = self._pose().z + double.toucher_max_m
        yield from self._dans_prehension(
            "prise double e) : plateau au contact",
            lambda: self._toucher(
                "prise double e) : le plateau monte jusqu'au contact du fond du seau du dessous",
                haut,
                "le plateau n'a pas touché le seau du dessous",
                QUOI_FAIRE_DOUBLE,
            ),
        )
        resultat = yield tete(
            "prise double f) : la tête remonte avec le seau du haut",
            double.tirage_m,
            vitesse="levee_lente",
            traction_max_n=2 * double.traction_max_par_barre_n,
        )
        if resultat is not None and resultat.arret == "traction":
            self._photo("seaux emboîtés qui ne se séparent pas")
            raise ErreurEtape(
                f"remplissage : les seaux ne se séparent pas (plus de "
                f"{double.traction_max_par_barre_n:g} N par barre)",
                QUOI_FAIRE_SEPARATION,
            )
        yield from lacher("prise double g) : lâcher (barres)")
        yield from plateau_de(
            "prise double h) : le plateau monte", double.remontee_plateau_m, pesee=True
        )
        if self._barriere():
            self._photo("barrière encore coupée après la séparation")
            raise ErreurEtape(
                "remplissage : barrière lumineuse encore coupée après la séparation",
                QUOI_FAIRE_DOUBLE,
            )
        self._un_seul_seau(format)
        yield from self._barres_pose(self._centrage(format), "prise double : centrage")
        self.seau_du_dessus = True
        journal.info("Remplissage : prise double séparée ; la tête garde le seau du dessus")
        yield from prehension.monter()

    def _toucher(self, texte: str, haut: float, manque: str, quoi_faire: str) -> Geste:
        """Le plateau monte lentement, au plus jusqu'à haut, et s'arrête au contact du fond d'un
        seau : la balance gagne pose_seau → contact_kg."""
        v = self.reglages.verrous
        pose = self._pose()
        haut = min(haut, self.course_z[1])
        # Sans dépasser ce que permettent les barres (fermées : sous 0,515 ; joues : 0,48).
        if not self.regles.barres_ouvertes(pose):
            haut = min(haut, v.barres_ouvertes_au_dessus_z)
        if self.regles.une_barre_dans_les_joues(pose):
            haut = min(haut, v.joues_plateau_max_z)
        resultat = yield Pas(
            texte, {"z": haut}, vitesse="contact", contact_kg=self.reglages.pose_seau.contact_kg
        )
        if not resultat.contact:
            raise ErreurEtape(
                f"remplissage : {manque} (plateau monté jusqu'à {_m(haut)} m)", quoi_faire
            )
        journal.info("Remplissage : contact du plateau à %.4f m (%s)", resultat.pose.z, texte)

    def seau_rendu(self) -> None:
        """Le seau du dessus (prise double) est rendu au stockage par la préhension."""
        self.seau_du_dessus = False

    def geste_orienter_anse(self) -> Geste:
        """Le plateau tourne le seau : oreilles de l'anse à 45° (modulo 90°) des barres."""
        seau = self.seau
        if seau is None:
            raise ErreurEtape("remplissage : pas de seau sur le plateau")
        if self.vision is None:
            raise ErreurEtape("remplissage : pas de caméra pour le QR du flanc", QUOI_FAIRE_QR)
        lu = self.vision.lire_seau()
        if lu is None:
            raise ErreurEtape("remplissage : QR du flanc du seau pas lu", QUOI_FAIRE_QR)
        code, oreilles = lu
        if seau.code is not None and code != seau.code:
            raise ErreurEtape(
                f"remplissage : QR lu {code}, le seau attendu est {seau.code}", QUOI_FAIRE_QR
            )
        reglages = self.reglages
        voulu = reglages.barres_direction_deg + reglages.anse_deg
        ecart = (voulu - oreilles + 45) % 90 - 45
        pose = self._pose()
        yield from self._orienter(pose.a + ecart, "orienter l'anse")
        seau.code, seau.angle_anse = code, self._pose().a
        journal.info(
            "Remplissage : seau %s, anse orientée (plateau à %.1f°)", code, seau.angle_anse
        )

    def geste_centrer(self) -> Geste:
        """Barres en position au contact du corps sous le rebord (+ le jeu du centrage), puis
        ouvertes. Si une barre force, l'alarme ALM de son pilote arrête le geste (geste_fini)."""
        seau = self.seau
        if seau is None or seau.angle_anse is None:
            raise ErreurEtape("remplissage : l'anse est orientée avant de serrer les barres")
        hw = self.reglages.formats[seau.format].centrage_hw_m + self.reglages.barres.jeu_centrage_m
        yield from self._barres(hw, "centrer le seau (barres au contact)", centrage=True)
        yield from self._barres_ouvertes()

    def geste_ramener_au_vidage(self) -> Geste:
        """Retour en y 0,42 (vidage par la griffe), plateau à la hauteur du vidage (bord du seau à
        0,78)."""
        seau = self.seau
        if seau is None:
            raise ErreurEtape("remplissage : pas de seau sur le plateau")
        yield from self._barres_ouvertes()
        yield from self._a_la_place(self.reglages.vidage_y, "retour au vidage")
        if self._au_vidage is not None:
            # Micropore (tâche 40) : la rangée du fond, quand le seau pèse assez.
            yield from self._au_vidage()
        yield from self._plateau(
            self.plateau_au_vidage(seau.format), "plateau à la hauteur du vidage"
        )

    def _seau_a_ranger(self) -> SeauPlateau:
        seau = self.seau
        if seau is None or seau.angle_anse is None:
            raise ErreurEtape("remplissage : pas de seau orienté sur le plateau")
        return seau

    def _anse_a_son_angle(self, seau: SeauPlateau) -> Geste:
        assert seau.angle_anse is not None
        pose = self._pose()
        yield from self._orienter(
            self.regles.angle_proche(pose.a, seau.angle_anse, 90), "anse à son angle"
        )

    def geste_ranger(self, file: str, pousseur_m: float | None = None) -> Geste:
        """Le plateau revient à l'angle de l'anse, va à la file, plateau en bas (tôle du tiroir),
        barres ouvertes (règle 12), le pousseur pousse le seau vers le stockage. `pousseur_m` :
        course plus courte (cale du Stockage) ; None : celle de la file."""
        place = self.reglages.rangement.files.get(file)
        if place is None:
            raise ErreurEtape(f"remplissage : file inconnue « {file} »")
        seau = self._seau_a_ranger()
        course = place.pousseur_m if pousseur_m is None else pousseur_m
        yield from self._anse_a_son_angle(seau)
        yield from self._barres_ouvertes()
        yield from self._a_la_place(place.y, f"chariot à la {file}")
        yield from self._plateau_en_bas()
        yield from self._peser("pesée du seau plein")
        self._noter(seau, file)
        yield Pas("le pousseur pousse le seau", {"pousseur": course})
        self.seau = None
        yield Pas("pousseur rentré", {"pousseur": self.reglages.pousseur_rentre_m})

    def refus_poussee_bande(self, pose: Pose) -> str | None:
        """Pousser sur la bande du haut : chariot à son y, plateau dans 0,496-0,501 (jamais plus
        bas que la tôle du Stockage, au plus 5 mm plus haut)."""
        bande = self.reglages.rangement.bande_haut
        if bande is None:
            return "pas de bande du haut dans les réglages (remplissage → rangement)"
        if not self.regles.a(pose.y, bande.y):
            return f"chariot à y {_m(pose.y)}, la bande du haut est à y {_m(bande.y)}"
        debut, fin = bande.plateau_plage_z
        if not debut - _EGAL <= pose.z <= fin + _EGAL:
            return (
                f"plateau à {_m(pose.z)} : pour la bande du haut, entre {_m(debut)} et "
                f"{_m(fin)} (tôle du stockage)"
            )
        return None

    def geste_ranger_en_haut(self) -> Geste:
        """Bande du haut, dans l'ordre a) à f) : a) bras de fermeture rangé ; b) barres ouvertes ;
        c) chariot à y 0,215 ; d) plateau à 0,4985 ; e) poussée ; f) pousseur rentré, plateau
        redescendu."""
        bande = self.reglages.rangement.bande_haut
        if bande is None:
            raise ErreurEtape("remplissage : pas de bande du haut dans les réglages", QUOI_FAIRE)
        seau = self._seau_a_ranger()
        bras = self._bras_galet()
        if bras is not True:
            etat = "pas connu" if bras is None else "pas rangé"
            raise ErreurEtape(
                f"remplissage : bande du haut : bras de fermeture {etat} (a : il doit être rangé)",
                QUOI_FAIRE,
            )
        yield from self._anse_a_son_angle(seau)
        yield from self._barres_ouvertes()  # b)
        yield from self._a_la_place(bande.y, "c) chariot à la bande du haut")
        yield from self._peser("pesée du seau plein")
        yield from self._plateau(bande.plateau_z, "d) plateau à la hauteur de la bande du haut")
        refus = self.refus_poussee_bande(self._pose())
        if refus is not None:
            raise ErreurEtape(f"remplissage : poussée sur la bande du haut refusée : {refus}")
        self._noter(seau, "bande_haut")
        yield Pas(
            "e) le pousseur pousse le seau sur la bande du haut", {"pousseur": bande.pousseur_m}
        )
        self.seau = None
        yield Pas("f) pousseur rentré", {"pousseur": self.reglages.pousseur_rentre_m})
        yield from self._plateau_en_bas()

    def _noter(self, seau: SeauPlateau, file: str) -> None:
        if self._fin_du_seau is not None:
            self._fin_du_seau(seau)
        poids = self.derniere_pesee_kg
        code = seau.code or "?"
        journal.info(
            "Remplissage : seau %s rangé en %s (%s)",
            code,
            file,
            "poids inconnu" if poids is None else f"{poids:.2f} kg",
        )
        self._photo(f"seau {code} rangé en {file}")
        if self.registre is None or seau.code is None:
            return
        try:
            self.registre.objet("seau", seau.code, type_seau=seau.format)
            if poids is not None:
                self.registre.noter_mesure(
                    "poids_seau_plein",
                    round(poids, 3),
                    "kg",
                    capteur="pesee_plateau_remplissage",
                    cycle=seau.cycle,
                    seau=seau.code,
                )
        except ErreurRegistre as erreur:
            journal.error("Remplissage : registre : %s", erreur)

    # ------------------------------------------------------------ gestes simples (essais)

    def geste_aller(self, y: float) -> Geste:
        yield from self._a_la_place(y, f"chariot à y {_m(y)}")

    def geste_plateau(self, z: float) -> Geste:
        yield from self._plateau(z, f"plateau à {_m(z)}")

    def geste_barres(self, hw: float) -> Geste:
        yield from self._barres(hw, f"barres à {_m(hw)}")

    def geste_pousseur(self, position: float) -> Geste:
        # Règle 12 : le pousseur sort à toute hauteur, barres ouvertes.
        if abs(position - self.reglages.pousseur_rentre_m) > self.reglages.tolerance_m:
            yield from self._barres_ouvertes()
        yield Pas(f"pousseur à {_m(position)}", {"pousseur": position})

    def geste_tourner_de(self, degres: float) -> Geste:
        yield from self._orienter(self._pose().a + degres, f"plateau tourné de {degres:g}°")

    # ------------------------------------------------------------ les modes

    def geste_mode_couvercles(self) -> Geste:
        """Retourneur (tâche 21 bis) : chariot à y 0,50, plateau fixe à 0,459, barres ouvertes ;
        le Lavage commande ensuite les barres (`regler_barres`)."""
        if self.seau is not None:
            raise ErreurEtape("remplissage : un seau est sur le plateau, pas de mode couvercles")
        reglage = self.reglages.couvercles
        yield from self._barres_ouvertes()
        yield from self._a_la_place(reglage.y, "chariot au retourneur")
        yield from self._plateau(reglage.plateau_z, "plateau à la hauteur du bac")
        self.mode = "couvercles"

    def geste_mode_inspection(self) -> Geste:
        """Inspection des bocaux : plateau fixe à 0,575, barres ouvertes, rotation libre."""
        if self.seau is not None:
            raise ErreurEtape("remplissage : un seau est sur le plateau, pas d'inspection")
        reglage = self.reglages.inspection
        yield from self._barres_ouvertes()
        yield from self._a_la_place(self.reglages.pose_y, "chariot à l'inspection")
        yield from self._plateau(reglage.plateau_z, "plateau à la hauteur de l'inspection")
        self.mode = "inspection"

    def geste_tourner_inspection(self) -> Geste:
        """Un arrêt de plus (45°) pour l'inspection du bocal."""
        if self.mode != "inspection":
            raise ErreurEtape("remplissage : pas en mode inspection")
        pose = self._pose()
        sens = -1 if pose.a > 0 else 1
        yield from self._orienter(
            pose.a + sens * self.reglages.inspection.pas_deg, "bocal tourné d'un arrêt"
        )

    def geste_peser_bocal(self, poids_tete_kg: float) -> Geste:
        """Le bocal posé par la préhension : sa force (`poids_tete_kg`, porté avant la pose) et
        la balance doivent être d'accord."""
        if self.mode != "inspection":
            raise ErreurEtape("remplissage : pas en mode inspection")
        yield from self._peser("pesée du bocal posé")
        poids = self.derniere_pesee_kg
        accord = self.reglages.pesee.accord_kg
        if poids is None or abs(poids - poids_tete_kg) > accord:
            lu = "pas de pesée" if poids is None else f"{poids:.2f} kg"
            raise ErreurEtape(
                f"remplissage : bocal posé, la balance lit {lu}, la tête portait "
                f"{poids_tete_kg:.2f} kg (± {accord:g})",
                QUOI_FAIRE_BOCAL,
            )

    def geste_fin_de_mode(self) -> Geste:
        """Retour au mode des seaux : plateau en bas, barres ouvertes."""
        yield from self._barres_ouvertes()
        yield from self._plateau_en_bas()
        self.mode = "seaux"
