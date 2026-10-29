"""Le lavage des seaux (module validé définitivement le 25/10/2026, fût de 44 cm).

    lavage = Lavage(reglages.machine, prehension, eau, mode=..., refus_panneau=...,
                    panneau_rabattu=...)
    prehension.lancer(lavage.geste_remplir)
    prehension.lancer(lambda: lavage.geste_laver_seau("seau_a"))   # la tête tient le seau
    prehension.lancer(lavage.geste_vider)
    lavage.finir_serie()            # refusé tant que le fût n'est pas vidé

Entre deux fûts de production, un fût de lavage (inox, Ø intérieur 0,45) vient au poste. Dedans :
un noyau à brosses (intérieur du seau) et une couronne de brosses extérieures. La Préhension tient
le seau retourné (bord en bas) par la ventouse et ne le lâche jamais : elle le descend dans les
brosses, il est brossé mouillé, rincé, soufflé, puis repart. La prise et la pose du seau sur les
piles sont au Stockage (pas encore figé).

Mode lavage seulement si le panneau du poste du fût est rabattu et le mode « lavage » choisi
(conditions d'entrée des étapes) ; un changement d'état du panneau pendant un mouvement met le
module en alarme : la tête et le pont s'arrêtent tout de suite (cartes n° 1 et n° 4).

Laver un seau (la tête le tient retourné) :
1. aller au fût par le couloir du seau retourné (en y jusqu'à y 0,74, vers −x jusqu'au coude
   (0,45 ; 0,74), puis en ligne droite vers le fût), ventouse en butée haute ;
2. tête orientée au départ des tours du seau, puis descente : le seau écarte lui-même les brosses
   extérieures ; appui de 80 N lu par le capteur de force (tête décalée de façon fixe vers +x selon
   le format : c'est le seau qui tourne dessous) ;
3. arrosage (bain recyclé dans les rampes), jamais à sec ;
4. passe 1 (paroi et fond, noyau), passe 2 (le bord, couronne en avant) : noyau, couronne et
   rotation de la tête dans la même commande, vide surveillé ;
5. rinçage propre, la pompe garde le même niveau ;
6. remontée selon le vide (−55 / −40 kPa, « feed hold », 2 essais) ;
7. jet d'air du col : seau décalé vers la buse, bord à sa hauteur, un tour ; égouttage ;
8. retour au coude du couloir.

Verrou du noyau et de la couronne : ils ne tournent JAMAIS sans objet tenu. Le Pi n'envoie leur
rotation que si la tête est à sa hauteur de travail au-dessus du fût et que le vide confirme un
objet tenu (`refus_brosses`, branché sur la préhension) ; toute perte de vide arrête noyau et
couronne (la surveillance rapide de la tête arrête le déplacement). Le pilotage à distance ne
pilote pas les axes en degrés : les brosses n'y sont jamais (le mode guidé, tâche 32, appellera
`refus_brosses`).

Ces verrous ne protègent que la MACHINE : la sécurité des personnes reste câblée.
"""

import math
import time
from collections.abc import Callable

from vidange.chef import ErreurEtape
from vidange.journal import donner_journal
from vidange.lavage.eau import EauLavage
from vidange.poste_fut import regles as regles_poste
from vidange.prehension.prehension import Geste, Prehension
from vidange.prehension.regles import Objet, Pose
from vidange.prehension.tete import Pas
from vidange.reglages import Machine, PhaseBrossage

journal = donner_journal("lavage")

QUOI_FAIRE = (
    "Regarder la vidéo du lavage : le seau est-il bien tenu, coincé dans les brosses, le fût "
    "de lavage bien en place ? Corriger, puis acquitter et donner le Go : le geste est refait "
    "depuis le début."
)
QUOI_FAIRE_PANNEAU = (
    "Le panneau du poste du fût a bougé pendant le lavage : la tête et le pont sont arrêtés. "
    "Rabattre le panneau, vérifier que personne n'est près du fût, puis acquitter et donner "
    "le Go."
)
QUOI_FAIRE_VIDE = (
    "La ventouse ne tient plus le seau pendant le lavage : noyau et couronne sont arrêtés. "
    "Regarder le seau (tombé sur le noyau ? coincé ?) et la ventouse (usée, sale ?). Le "
    "reprendre à la main s'il le faut, puis acquitter et donner le Go."
)
QUOI_FAIRE_APPUI = (
    "L'appui du seau sur le noyau n'est pas venu : regarder la vidéo (seau mal tenu, noyau "
    "absent, fût de lavage pas en place ?). Corriger, puis acquitter et donner le Go."
)
QUOI_FAIRE_SERIE = (
    "Le fût de lavage doit être vidé avant d'être échangé : lancer la vidange (étape « vider »), "
    "puis finir la série."
)

# Écart sous lequel deux positions sont égales (m).
_EGAL = 1e-6


def _m(valeur: float) -> str:
    return f"{valeur:.3f}".rstrip("0").rstrip(".").replace(".", ",")


class Lavage:
    def __init__(
        self,
        machine: Machine,
        prehension: Prehension,
        eau: EauLavage,
        mode: Callable[[], str],
        refus_panneau: Callable[[], str | None],
        panneau_rabattu: Callable[[], bool],
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        """`mode` : le mode de la machine (ModeMachine.actuel). `refus_panneau` : pourquoi le
        panneau du poste du fût interdit le lavage (PosteFut.refus_lancement("lavage")).
        `panneau_rabattu` : PosteFut.panneau_vu_rabattu (contact ouvert et stable)."""
        assert machine.lavage is not None and machine.griffe is not None
        assert machine.poste_fut is not None
        self.reglages = machine.lavage
        self.formats = machine.griffe.formats
        self.poste = machine.poste_fut
        self.prehension = prehension
        self.eau = eau
        self._mode = mode
        self._refus_panneau = refus_panneau
        self._panneau_rabattu = panneau_rabattu
        self._horloge = horloge
        # Seaux lavés depuis le dernier remplissage, et depuis le début de la série.
        self.seaux_eau = 0
        self.seaux_serie = 0
        prehension.verrou_brosses = self.refus_brosses

    # ------------------------------------------------------------ verrous et conditions

    def refus_mode(self) -> str | None:
        """Pourquoi le lavage ne peut pas se faire maintenant (mode, panneau), ou None."""
        mode = self._mode()
        if mode != "lavage":
            return f"mode « lavage » pas choisi (mode actuel : {mode})"
        return self._refus_panneau()

    def mode_permis(self) -> bool:
        return self.refus_mode() is None

    def panneau_tenu(self) -> bool:
        """Surveillance : le panneau reste rabattu pendant les gestes du lavage."""
        return self._panneau_rabattu()

    def refus_brosses(self, pose: Pose) -> str | None:
        """Verrou du noyau et de la couronne : raison du refus, ou None s'ils peuvent tourner."""
        verrou = self.reglages.verrou
        centre_x, centre_y = self.reglages.centre_fut
        ecart = math.hypot(pose.x - centre_x, pose.y - centre_y)
        if ecart > verrou.rayon_m + _EGAL:
            return (
                f"noyau et couronne : tête pas au-dessus du fût de lavage (axe à {_m(ecart)} m du "
                f"centre, au plus {_m(verrou.rayon_m)} m)"
            )
        if pose.z > verrou.face_max_z + _EGAL:
            return (
                f"noyau et couronne : tête pas à sa hauteur de travail (face à {_m(pose.z)} m, au "
                f"plus {_m(verrou.face_max_z)} m)"
            )
        if not self.prehension.tient_un_objet():
            return (
                "noyau et couronne : aucun objet tenu (vide pas confirmé) ; ils ne tournent "
                "jamais à vide"
            )
        return None

    def objet_seau(self, format: str) -> Objet:
        return self.prehension.objet_par_nom("seau_retourne", format)

    # ------------------------------------------------------------ eau et série

    def geste_remplir(self) -> Geste:
        yield from self.eau.geste_remplir()
        self.seaux_eau = 0

    def geste_vider(self) -> Geste:
        yield from self.eau.geste_vider()

    def eau_a_changer(self) -> bool:
        """L'eau a lavé seaux_max_par_eau seaux : la vider et la refaire avant le suivant."""
        maximum = self.reglages.eau.seaux_max_par_eau
        return maximum is not None and self.seaux_eau >= maximum

    def finir_serie(self) -> None:
        """La série est finie : refusé tant que le fût de lavage n'est pas vidé (il est toujours
        vidé avant d'être échangé)."""
        if self.eau.eau_dans_le_fut or self.eau.flotteur() is not False:
            raise ErreurEtape(
                "lavage : série pas finie, le fût de lavage n'est pas vidé", QUOI_FAIRE_SERIE
            )
        journal.info("Lavage : série finie, %d seau(x) lavé(s)", self.seaux_serie)
        self.seaux_serie = 0

    def pauser(self) -> None:
        self.prehension.pauser()
        self.eau.pauser()

    def reprendre(self) -> None:
        self.eau.reprendre()
        self.prehension.reprendre()

    def arreter(self) -> None:
        """Alarme : tête, pont, noyau et couronne arrêtés ; eau, pompe, air et chauffage coupés."""
        self.prehension.arreter()
        self.eau.couper()

    # ------------------------------------------------------------ couloir

    def _au_fut(self, pose: Pose) -> bool:
        centre_x, centre_y = self.reglages.centre_fut
        rayon = self.reglages.verrou.rayon_m
        return math.hypot(pose.x - centre_x, pose.y - centre_y) <= rayon + _EGAL

    def _passer(self, x: float, y: float) -> Geste:
        """Un bout du couloir, ventouse en haut (passage de la paroi côté stockage vérifié)."""
        p = self.prehension
        refus = regles_poste.refus_passage_paroi_lavage(self.poste, p.reglages.haut_z, y)
        if refus is not None:
            raise ErreurEtape(f"lavage : {refus}", QUOI_FAIRE)
        yield from p.aller(x, y)

    def _entrer(self, x: float, y: float) -> Geste:
        """Jusqu'à l'axe (x, y) au-dessus du fût, par le couloir du seau retourné."""
        p = self.prehension
        yield from p.monter()
        assert p.pose is not None
        if not self._au_fut(p.pose):
            coude_x, coude_y = self.reglages.coude_couloir
            if abs(p.pose.y - coude_y) > _EGAL:
                if p.pose.x < coude_x - _EGAL:
                    raise ErreurEtape(
                        f"lavage : le seau retourné arrive au fût par le couloir (y {_m(coude_y)} "
                        f"m, depuis x ≥ {_m(coude_x)} m) ; tête à x {_m(p.pose.x)}, y "
                        f"{_m(p.pose.y)} m",
                        QUOI_FAIRE,
                    )
                yield from self._passer(p.pose.x, coude_y)
            yield from self._passer(coude_x, coude_y)
        yield from p.aller(x, y)

    def _sortir(self) -> Geste:
        """Du fût au coude du couloir (le reste du chemin, vers +x à y 0,74, est au module qui
        reprend le seau)."""
        yield from self._passer(*self.reglages.coude_couloir)

    # ------------------------------------------------------------ laver un seau

    def geste_laver_seau(self, format: str) -> Geste:
        """Laver le seau retourné que tient la tête (format de la table des formats)."""
        reglage = self.reglages.formats.get(format)
        seau = self.formats.get(format)
        if reglage is None or seau is None or seau.hauteur is None:
            raise ErreurEtape(f"lavage : format de seau inconnu « {format} »")
        p = self.prehension
        if p.objet is None or p.objet.sorte != "seau_retourne":
            raise ErreurEtape("lavage : la tête ne tient pas de seau retourné", QUOI_FAIRE)
        refus = self.refus_mode()
        if refus is not None:
            raise ErreurEtape(f"lavage refusé : {refus}", QUOI_FAIRE_PANNEAU)
        if not self.eau.eau_dans_le_fut:
            raise ErreurEtape("lavage : le fût de lavage n'est pas rempli", QUOI_FAIRE)
        brossage = self.reglages.brossage
        centre_x, centre_y = self.reglages.centre_fut
        journal.info("Lavage d'un seau %s", format)
        # 1. Au fût par le couloir, ventouse en haut.
        yield from self._entrer(centre_x + reglage.decalage_brossage_m, centre_y)
        # 2. Orientée au départ des tours du seau (en haut), descente dans les brosses, appui.
        assert p.pose is not None
        if abs(p.pose.a - brossage.angle_depart_deg) > p.reglages.tolerance_deg:
            # Angle exact (pas « à 360° près ») : les tours du seau tiennent dans la course.
            yield Pas("tête au départ des tours du seau", {"a": brossage.angle_depart_deg})
        yield Pas(
            "descendre dans les brosses", {"z": brossage.face_contact_z + brossage.approche_m}
        )
        resultat = yield Pas(
            "appui du seau sur le noyau",
            {"z": brossage.face_contact_z - brossage.course_appui_m},
            vitesse="approche",
            appui_arret_n=brossage.appui_n,
        )
        assert resultat is not None and p.pose is not None
        if resultat.arret != "appui":
            raise ErreurEtape(
                f"lavage : appui de {brossage.appui_n:g} N sur le noyau pas atteint (face "
                f"descendue à {_m(p.pose.z)} m)",
                QUOI_FAIRE_APPUI,
            )
        z_appui = p.pose.z
        # 3. et 4. Arrosage, puis les deux passes.
        yield from self.eau.geste_arroser()
        for numero, phase in enumerate(brossage.passe_1, start=1):
            yield from self._brosser(phase, f"passe 1 ({numero})")
        if reglage.remontee_passe_2_m > 0:
            yield Pas("remonter pour la passe 2", {"z": z_appui + reglage.remontee_passe_2_m})
        for numero, phase in enumerate(brossage.passe_2, start=1):
            yield from self._brosser(phase, f"passe 2 ({numero})")
        self.eau.arreter_arrosage()
        # 5. Rinçage propre.
        yield from self.eau.geste_rincer()
        # 6. Remontée selon le vide.
        yield from self._remonter(z_appui)
        # 7. Jet d'air du col, égouttage au-dessus du fût.
        yield from self._jet_air(centre_x + reglage.jet_decalage_m, centre_y, reglage.jet_bord_z)
        yield Pas("égoutter au-dessus du fût", attente_s=self.reglages.jet_air.egouttage_s)
        # 8. Retour au coude du couloir.
        yield from self._sortir()
        self.seaux_eau += 1
        self.seaux_serie += 1
        journal.info("Lavage : seau %s lavé", format)

    def _brosser(self, phase: PhaseBrossage, texte: str) -> Geste:
        """Noyau, couronne et seau ensemble pendant la phase ; arrêt à toute perte de vide."""
        p = self.prehension
        assert p.pose is not None
        if not self.eau.arrosage_en_marche():
            raise ErreurEtape("lavage : arrosage arrêté, on ne brosse jamais à sec", QUOI_FAIRE)
        tours = {"noyau": phase.noyau_tr_min, "couronne": phase.couronne_tr_min}
        brosses = {
            nom: tr_min * 360 * phase.duree_s / 60 for nom, tr_min in tours.items() if tr_min > 0
        }
        resultat = yield Pas(
            f"brossage, {texte} : noyau {phase.noyau_tr_min:g} tr/min, couronne "
            f"{phase.couronne_tr_min:g} tr/min, seau {phase.seau_tours:g} tour(s)",
            {"a": p.pose.a + phase.seau_tours * 360},
            brosses=brosses,
            duree_s=phase.duree_s,
            vide_perte_kpa=p.reglages.vide.perte_kpa,
        )
        assert resultat is not None
        if resultat.arret == "vide":
            raise ErreurEtape(
                f"lavage : vide perdu pendant le brossage ({texte}) : noyau et couronne arrêtés",
                QUOI_FAIRE_VIDE,
            )

    def _remonter(self, z_appui: float) -> Geste:
        """Sortir le seau des brosses : levée lente, puis normale, vide surveillé. Vide perdu :
        arrêt (« feed hold »), redescendre sur le noyau, reprendre le vide, recommencer ; après
        essais_max échecs, alerte (le seau reste dans le fût)."""
        p = self.prehension
        vide = p.reglages.vide
        haut = p.reglages.haut_z
        echecs = 0
        while True:
            lente = min(z_appui + p.reglages.levee_lente_m, haut)
            resultat = yield Pas(
                "sortir le seau des brosses",
                {"z": lente},
                vitesse="levee_lente",
                vide_perte_kpa=vide.perte_kpa,
            )
            assert resultat is not None
            if resultat.arret != "vide":
                resultat = yield Pas("remonter", {"z": haut}, vide_perte_kpa=vide.perte_kpa)
                assert resultat is not None
                if resultat.arret != "vide":
                    return
            echecs += 1
            journal.warning("Lavage : vide perdu en remontant le seau (échec n° %d)", echecs)
            if echecs >= vide.essais_max:
                raise ErreurEtape(
                    f"lavage : vide perdu {echecs} fois en sortant le seau des brosses "
                    f"({vide.perte_kpa:g} kPa) ; le seau est resté dans le fût",
                    QUOI_FAIRE_VIDE,
                )
            yield Pas("redescendre sur le noyau", {"z": z_appui}, vitesse="approche")
            p.tete.vanne(True)
            yield from p.attendre_vide()

    def _jet_air(self, x: float, y: float, bord_z: float) -> Geste:
        """Seau décalé vers la buse, son bord à sa hauteur, air ouvert pendant un tour."""
        p = self.prehension
        objet = p.objet
        assert objet is not None
        yield from p.aller(x, y)
        yield Pas("bord du seau à la hauteur de la buse", {"z": bord_z + objet.dessous_m})
        assert p.pose is not None
        # Le tour part vers le milieu de la course de la tête (elle est limitée).
        debut, fin = p.course_a
        sens = 1 if p.pose.a <= (debut + fin) / 2 else -1
        self.eau.air_col(True)
        resultat = yield Pas(
            "jet d'air du col : un tour du seau",
            {"a": p.pose.a + sens * 360},
            duree_s=self.reglages.jet_air.tour_s,
            vide_perte_kpa=p.reglages.vide.perte_kpa,
        )
        self.eau.air_col(False)
        assert resultat is not None
        if resultat.arret == "vide":
            raise ErreurEtape("lavage : vide perdu pendant le jet d'air", QUOI_FAIRE_VIDE)
        yield from p.monter()
