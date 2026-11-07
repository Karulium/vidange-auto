"""La vraie griffe dans les lots (tâche 45 sexies) : vidange du fût dans les seaux, versement dans
les bocaux, sur le même pont que la Préhension.

    griffe = GriffeDuSeau(machine, bras, poste, prehension, remplissage, lot.seaux, ...)
    modules = [remplissage, mycelium, griffe.module(noter)]    # vidange.cycle.mode_seaux
    brancher_pont(griffe.griffe, prehension)                    # fait par GriffeDuSeau

Ce qui vient de docs/decisions.md et de la tâche, sans rien inventer :
- la griffe ne porte une dose au seau que quand le seau est prêt (`seau_pret`) : le Remplissage
  l'attend au vidage (étape « verser », chariot arrêté, plateau à sa hauteur), la couche de
  mycélium d'avant est versée (le Remplissage ne revient au vidage qu'après le dosage), et le chef
  permet le versement dans un seau ouvert (pas de purge en cours) ;
- elle ne bouge le pont que si la Préhension n'a pas de geste en cours (`pont_libre`) : les deux
  mâts sont sur le même chariot ;
- le seau tourne pendant le tassement et l'essuyage (Remplissage.tourner_seau) ; une couche vidée
  et tassée (ou le seau fini, essuyé) termine l'étape « verser » du Remplissage, et le Mycélium
  dose ensuite ;
- « partie » (la Préhension peut poser le couvercle) : le mât de la griffe n'est plus au-dessus du
  seau du vidage (choix 4). Le bras du spray, lui, ne regarde plus « partie » mais sa zone
  (vidange.spray.zone, fil Spray du 07/11/2026, tâche 45 septies) ;
- la Préhension ne bouge le pont que griffe GARÉE : aucun geste en cours, axes en butée haute,
  godet fermé, tête bras le long du pont (« pas de collision si la griffe est en butée haute »,
  réponse du projet mécanique du 29/10/2026).

Choix de Claude (tâche 45 sexies, dans la PR) :
1. La griffe ne descend dans le fût (raclage, prise) que quand un seau l'attend au vidage
   (`fut_permis`). Sinon elle attendrait dans le fût avec sa dose pendant que la Préhension a
   besoin du pont pour le seau suivant, le couvercle ou le bocal neuf : blocage (chacun attend
   l'autre), ou le mât traîné dans le fût. On perd la prise « d'avance » pendant le spray et le
   dosage ; le solveur pourra la rendre plus tard s'il sait ce que la Préhension va faire.
2. Pont partagé (`brancher_pont`) : un pas de la Préhension qui bouge le pont ou le chariot Y
   traîne le mât de la griffe : les règles de POSITION de la griffe (tables « y minimum du mât »,
   fût, boîtier de la caméra du bocal, stockage...) sont vérifiées le long du trajet, à la hauteur
   où elle est. Pas ses règles de TRAJET (jamais en diagonale entre le fût et le seau) : ce sont
   celles de ses propres trajets. Et l'inverse : un pas de la griffe qui bouge le pont traîne la
   tête de préhension, dont toutes les règles de mouvement sont vérifiées. Un pas refusé ne part
   pas : alarme, rien ne bouge.
3. Fût vide pendant un lot : la griffe finit le seau commencé (tassement, essuyage, comme sa
   fiche), sort de la zone du plateau, puis attend le « Prêt » d'un nouveau fût et continue le
   lot sur le seau suivant. Le seau commencé n'est pas fini : ce qu'on en fait n'est écrit nulle
   part (« gardé tel quel et signalé », PR n° 23) : l'étape « verser » part en alarme et le dit
   (case vide, question de la PR). Après le dernier seau du lot, fût pas vide : le module finit,
   la griffe garée en haut ; le reste du fût sert au lot suivant.
4. « Partie du poste » ne peut pas vouloir dire « au-dessus du fût » : quand la Préhension prend
   ou pose un seau, elle traîne la griffe (même pont) loin du fût. Et avec le choix 1, la griffe ne
   part plus chercher sa prise pendant le spray. On garde ce que le spray demande : la griffe hors
   du seau (mât à plus de griffe → vidage → zone_seau_m du point de vidage). Au poste lui-même
   (y 0,135), le mât de la griffe ne peut jamais être : la table « y minimum du mât » l'interdit.

Ces verrous ne protègent que la MACHINE : la sécurité des personnes reste câblée.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

from vidange.angles_gardes import AnglesGardes
from vidange.chef import Condition, ErreurEtape, Module
from vidange.griffe.bras import Bras
from vidange.griffe.griffe import Griffe
from vidange.griffe.module import module_griffe
from vidange.griffe.regles import Pose as PoseGriffe
from vidange.journal import donner_journal
from vidange.poste_fut import PosteFut
from vidange.prehension.prehension import Prehension
from vidange.prehension.regles import Pose as PosePrehension
from vidange.reglages import Machine
from vidange.remplissage.module import SeauAFaire
from vidange.remplissage.remplissage import Remplissage

journal = donner_journal("cycle.griffe")

GRIFFE = "griffe"
# Délai maximal d'une couche versée par la griffe (plusieurs prises), machine.yaml → durees.
DELAI_COUCHE = "remplissage_couche_griffe_max"
QUOI_FAIRE_COUCHE = (
    "La griffe verse la couche de substrat dans le seau : regarder son module (alarme, poste du "
    "fût pas prêt ?) et la vidéo de la griffe. Corriger, puis acquitter et donner le Go."
)
QUOI_FAIRE_FUT_VIDE = (
    "Le fût s'est vidé pendant ce seau : la griffe l'a fini comme sa fiche le dit (tassé, bord "
    "essuyé), mais il lui manque des couches. Ce que le lot fait d'un tel seau n'est pas encore "
    "décidé (docs/taches.md, tâche 45 sexies) : regarder le seau, puis abandonner le lot à "
    "l'écran ou à la page web et finir ce seau à la main."
)
# Écart sous lequel deux valeurs sont égales (m ou °).
_EGAL = 1e-6


def _points(depart_x: float, depart_y: float, arrivee_x: float, arrivee_y: float, pas: float):
    """Les points (t de 0 à 1) d'un trajet en x, y, tous les `pas` mètres au plus."""
    longueur = math.dist((depart_x, depart_y), (arrivee_x, arrivee_y))
    nombre = max(1, math.ceil(longueur / pas))
    return [i / nombre for i in range(nombre + 1)]


def brancher_pont(griffe: Griffe, prehension: Prehension) -> None:
    """Les deux mâts sont sur le même pont et le même chariot Y : chacun vérifie, à chaque pas qui
    bouge le pont, les règles de l'autre (choix 2 de ce fichier). Position inconnue de l'autre :
    refusé (on ne bouge pas à l'aveugle).

    Tête de préhension basse pendant un versement dans la dernière rangée de bocaux (fiche
    prehension/logiciel/tete-basse-versement-bocaux.md, 07/11/2026 : « le pont peut rouler, ça ne
    change rien au jeu ») : vide, à sa face basse, elle peut être traînée tête basse, seulement
    au-dessus du plateau du haut (x ≥ prehension_x_min_tete_basse) ; ses règles de position sont
    vérifiées le long du trajet."""
    pas = griffe.reglages.pas_verification_m
    versement = griffe.reglages.versement_bocal
    tete_basse = None if versement is None else versement.tete_basse

    def basse_du_versement(pose: PosePrehension) -> bool:
        if tete_basse is None or prehension.objet is not None:
            return False
        face = tete_basse.prehension_face_basse_versement
        return abs(pose.z - face) <= prehension.reglages.tolerance_m + _EGAL

    def refus_basse_trainee(debut: PosePrehension, fin: PosePrehension) -> str | None:
        assert tete_basse is not None
        contexte = prehension.contexte()
        x_min = tete_basse.prehension_x_min_tete_basse
        for t in _points(debut.x, debut.y, fin.x, fin.y, pas):
            pose = debut.avec(x=debut.x + (fin.x - debut.x) * t, y=debut.y + (fin.y - debut.y) * t)
            if pose.x < x_min - _EGAL:
                return (
                    f"tête basse (versement dans la dernière rangée) à x {pose.x:.3f} m : elle "
                    f"ne va qu'au-dessus du plateau du haut (x ≥ {x_min:g})"
                )
            refus = prehension.regles.refus_pose(pose, contexte)
            if refus is not None:
                return refus
        return None

    def refus_griffe_trainee(depart: PosePrehension, arrivee: PosePrehension) -> str | None:
        dx, dy = arrivee.x - depart.x, arrivee.y - depart.y
        if abs(dx) <= _EGAL and abs(dy) <= _EGAL:
            return None
        try:
            # Toujours lue sur le bras : la pose gardée par la griffe ne suit pas le pont quand
            # c'est la préhension qui le bouge.
            debut = griffe.bras.position()
        except Exception as erreur:
            return f"position de la griffe (même pont) inconnue : {erreur}"
        fin = debut.avec(x=debut.x + dx, y=debut.y + dy)
        contexte = griffe.contexte()
        for t in _points(debut.x, debut.y, fin.x, fin.y, pas):
            pose = debut.avec(x=debut.x + dx * t, y=debut.y + dy * t)
            refus = griffe.regles.refus_pose(pose, contexte)
            if refus is not None:
                return f"le mât de la griffe, traîné par le pont, irait là : {refus}"
        refus = griffe.verrou_stockage(debut, fin)
        if refus is not None:
            return f"le mât de la griffe, traîné par le pont : {refus}"
        return None

    def refus_tete_trainee(depart: PoseGriffe, arrivee: PoseGriffe) -> str | None:
        dx, dy = arrivee.x - depart.x, arrivee.y - depart.y
        if abs(dx) <= _EGAL and abs(dy) <= _EGAL:
            return None
        try:
            debut = prehension.tete.position()
        except Exception as erreur:
            return f"position de la tête de préhension (même pont) inconnue : {erreur}"
        fin = debut.avec(x=debut.x + dx, y=debut.y + dy)
        if basse_du_versement(debut):
            refus = refus_basse_trainee(debut, fin)
        else:
            refus = prehension.regles.refus_mouvement(debut, fin, prehension.contexte())
        if refus is None:
            refus = prehension.verrou_chariot(debut, fin)
        if refus is None:
            refus = prehension.verrou_stockage(debut, fin)
        if refus is not None:
            return f"la tête de préhension, traînée par le pont : {refus}"
        return None

    prehension.verrou_pont = refus_griffe_trainee
    griffe.verrou_pont = refus_tete_trainee


def garee(griffe: Griffe) -> bool:
    """La griffe ne gêne pas un trajet du pont fait par la Préhension : aucun geste en cours, axes
    en butée haute, godet fermé, tête bras le long du pont (position inconnue : non)."""
    if griffe.occupee():
        return False
    try:
        pose = griffe.bras.position()
    except Exception:
        return False
    regles = griffe.regles
    return regles.en_butee_haute(pose.z) and pose.b <= _EGAL and regles.bloquee(pose.a)


def condition_garee(griffe: Griffe) -> Condition:
    return Condition(
        "griffe garée : axes en butée haute, godet fermé, aucun geste (même pont que la "
        "préhension)",
        lambda: garee(griffe),
    )


class GriffeDuSeau:
    """La griffe d'un lot de seaux, enchaînée au Remplissage, au Mycélium et à la Préhension.
    `seaux` : ceux du lot (le format de chacun) ; `premier` : le seau où en est le lot (reprise).
    Les autres arguments sont les cases de Griffe : `mode`, `porte_spray_ouverte`,
    `dosage_en_cours`, `camera_dosage_pivote`, `garde`, `horloge` (simulateur)."""

    # Pas de faux versement : la griffe verse elle-même (Plan.versement_s n'est pas utilisé).
    versement_s = 0.0

    def __init__(
        self,
        machine: Machine,
        bras: Bras,
        poste: PosteFut,
        prehension: Prehension,
        remplissage: Remplissage,
        seaux: Sequence[SeauAFaire],
        premier: int = 0,
        registre: Any = None,
        mode: Callable[[], str] = lambda: "production",
        porte_spray_ouverte: Callable[[], bool] = lambda: False,
        dosage_en_cours: Callable[[], bool] = lambda: False,
        camera_dosage_pivote: Callable[[], bool] = lambda: False,
        garde: AnglesGardes | None = None,
        horloge: Callable[[], float] | None = None,
    ) -> None:
        self.machine = machine
        self.prehension = prehension
        self.remplissage = remplissage
        self.seaux = list(seaux)
        # Le seau que la griffe remplit (numéro dans le lot), les couches versées de chaque seau,
        # les seaux finis par un fût vide (il leur manque des couches).
        self.seau = premier
        self.versees: dict[int, int] = {}
        self.interrompus: set[int] = set()
        # Ce que le Remplissage attend (étape « verser ») : (seau, couche), ou None.
        self.attendue: tuple[int, int] | None = None

        def face_z() -> float | None:
            try:
                return prehension.tete.position().z
            except Exception:
                return None

        options: dict[str, Any] = {} if horloge is None else {"horloge": horloge}
        self.griffe = Griffe(
            machine,
            bras,
            poste,
            registre,
            mode=mode,
            porte_spray_ouverte=porte_spray_ouverte,
            dosage_en_cours=dosage_en_cours,
            camera_dosage_pivote=camera_dosage_pivote,
            prochain_format=self._format_du_seau,
            tourner_seau=remplissage.tourner_seau,
            couche_finie=self._couche_finie,
            seau_fini=self._seau_fini,
            prehension_face_z=face_z,
            garde=garde,
            **options,
        )
        # Règle 14 du chariot (mode couvercles) et pont partagé avec la Préhension.
        remplissage.brancher_griffe(self.griffe)
        brancher_pont(self.griffe, prehension)
        self.garee = condition_garee(self.griffe)

    # ------------------------------------------------------------ ce que la griffe sait

    def _format_du_seau(self) -> str | None:
        if 0 <= self.seau < len(self.seaux):
            return self.seaux[self.seau].format
        return None

    def _couches(self, seau: int) -> int:
        format = self.seaux[seau].format if 0 <= seau < len(self.seaux) else None
        formats = self.griffe.reglages.formats
        if format not in formats:
            raise ErreurEtape(f"griffe : format de seau inconnu « {format} »")
        return formats[format].couches

    def _couche_finie(self, couche: int) -> None:
        self.versees[self.seau] = max(self.versees.get(self.seau, 0), couche)
        journal.info("Griffe : seau n° %d, couche %d versée et tassée", self.seau + 1, couche)

    def _seau_fini(self, numero: int) -> None:
        couche = self.griffe.plan.couche
        self.versees[self.seau] = max(self.versees.get(self.seau, 0), couche)
        if self.griffe.plan.vide and couche < self._couches(self.seau):
            self.interrompus.add(self.seau)
            journal.warning(
                "Griffe : fût vide, seau n° %d commencé (%d couches sur %d)",
                self.seau + 1,
                couche,
                self._couches(self.seau),
            )
        self.seau += 1

    # ------------------------------------------------------------ pour le Remplissage

    def attendre(self, seau: int, couche: int) -> None:
        """Action de l'étape « verser » du Remplissage : le seau attend la couche `couche`."""
        self.attendue = (seau, couche)

    def couche_versee(self) -> bool:
        """Fin de l'étape « verser » : la griffe a versé (et tassé) la couche attendue."""
        if self.attendue is None:
            return True
        seau, couche = self.attendue
        if self.versees.get(seau, 0) >= couche:
            self.attendue = None
            return True
        if seau in self.interrompus:
            raise ErreurEtape(
                f"fût vide pendant le seau n° {seau + 1} : il lui manque des couches (la "
                f"griffe en a versé {self.versees.get(seau, 0)})",
                QUOI_FAIRE_FUT_VIDE,
            )
        return False

    def _attendue_par_le_seau(self) -> bool:
        attendue = self.attendue
        return (
            attendue is not None
            and attendue[0] == self.seau
            and self.versees.get(attendue[0], 0) < attendue[1]
        )

    # ------------------------------------------------------------ conditions du module griffe

    def fut_permis(self) -> bool:
        """Choix 1 : la griffe ne descend dans le fût que quand le seau l'attend."""
        return self._attendue_par_le_seau()

    def seau_pret(self) -> bool:
        """Le seau attend la griffe au vidage, arrêté, et le chef permet le versement."""
        remplissage = self.remplissage
        return (
            self._attendue_par_le_seau()
            and remplissage.seau_au_vidage()
            and remplissage.versement_permis()
        )

    def pont_libre(self) -> bool:
        """La Préhension n'a pas de geste en cours (même pont, même chariot Y)."""
        return not self.prehension.occupee()

    def partie(self) -> bool:
        """La griffe est partie du poste (choix 4) : son mât n'est plus au-dessus du seau du
        vidage (position inconnue : non)."""
        griffe = self.griffe
        try:
            pose = griffe.bras.position()
        except Exception:
            return False
        x, y = griffe.reglages.seau_remplissage
        return math.hypot(pose.x - x, pose.y - y) > griffe.reglages.vidage.zone_seau_m + _EGAL

    def module(self, noter: Callable[[], object] = lambda: None) -> Module:
        """Le module « griffe » du lot ; `noter` est appelé à la fin de chaque étape (carnet).
        Après « fût vide », il attend le « Prêt » d'un nouveau fût (choix 3) ; après le dernier
        seau du lot, il finit."""
        module = module_griffe(
            self.griffe,
            seau_pret=self.seau_pret,
            pont_libre=self.pont_libre,
            fut_permis=self.fut_permis,
        )
        etapes = []
        for etape in module.etapes:
            ensuite = etape.ensuite
            if etape.nom == "fut_vide":
                ensuite = self._apres_fut_vide
            elif etape.nom == "essuyer_le_bord":
                ensuite = self._apres_essuyage(ensuite)

            def apres(ensuite=ensuite) -> str | None:
                suivante = ensuite() if ensuite is not None else None
                noter()
                return suivante

            etapes.append(replace(etape, ensuite=apres))
        return replace(module, etapes=tuple(etapes))

    def _apres_essuyage(self, ensuite: Callable[[], str | None]) -> Callable[[], str | None]:
        """Le dernier seau du lot est plein et le fût n'est pas vide : le module finit (la
        griffe reste en haut, garée ; le reste du fût sert au lot suivant)."""

        def suite() -> str | None:
            suivante = ensuite()
            if suivante == "revenir_au_fut" and self.seau >= len(self.seaux):
                journal.info("Griffe : dernier seau du lot plein, le reste du fût attend")
                return None
            return suivante

        return suite

    def _apres_fut_vide(self) -> str | None:
        if self.seau >= len(self.seaux):
            journal.info("Griffe : fût vide et plus de seau à remplir")
            return None
        journal.warning("Griffe : fût vide, elle attend le « Prêt » d'un nouveau fût")
        return "attendre_le_fut"

    # ------------------------------------------------------------ carnet (reprise)

    def memoire(self) -> dict[str, Any]:
        return {
            "plan": self.griffe.memoire(),
            "seau": self.seau,
            "versees": {str(seau): couche for seau, couche in self.versees.items()},
            "interrompus": sorted(self.interrompus),
        }

    def retrouver(self, memoire: dict[str, Any]) -> None:
        if "plan" in memoire:
            self.griffe.retrouver(dict(memoire["plan"]))
        self.seau = int(memoire.get("seau", self.seau))
        self.versees = {int(seau): int(c) for seau, c in memoire.get("versees", {}).items()}
        self.interrompus = {int(seau) for seau in memoire.get("interrompus", [])}
