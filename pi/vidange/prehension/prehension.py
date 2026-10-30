"""La préhension : les gestes de base de la tête (module validé définitivement le 27/10/2026).

    prehension = Prehension(reglages.machine, tete, porte_bocal=..., poste=...)
    prehension.lancer(lambda: prehension.geste_prendre("seau", x, y, contact_z, "seau_a"))
    prehension.geste_fini()        # condition de fin d'une étape du chef
    prehension.tient_un_objet()    # vide confirmé (verrou du noyau du Lavage)

Les modules qui s'en servent (Stockage, Lavage, Remplissage, Entonnoir) ne sont pas encore
écrits : ils lanceront ces gestes depuis leurs étapes, avec leurs positions (machine.yaml).
Le scénario du simulateur (vidange/prehension/module.py) les montre tous.

Un geste est une suite de pas (vidange.prehension.tete.Pas) et d'attentes (vide, mors du
porte-bocal). Chaque pas est vérifié avant de partir (vidange.prehension.regles) : un pas refusé
met le module en alarme, il ne bouge pas. Un geste part de là où est la tête (d'abord en haut).

Prendre un objet (seau, couvercle, bocal, entonnoir) :
1. tare tête en l'air ; descente, lente sur les derniers cm ;
2. contact de la tête : sa cote Z est notée ; à plus de 5 mm de la cote attendue, arrêt et alerte
   (seau vide : contact trop haut = anse levée ; avant de descendre, la caméra a vérifié
   qu'aucune anse n'est levée : `anse_levee`, tâche 22) ;
3. vanne de vide ouverte ; vide de −55 kPa attendu (délai réglé) ; sa valeur au journal ;
4. levée lente sur les premiers mm, puis normale (lente si le vide est plus faible que
   −55 kPa) ; vide remonté au-dessus de −40 kPa pendant la levée : arrêt (« feed hold »),
   redescendre, reposer, reprendre ; après 2 échecs, alerte ;
5. prise confirmée par le poids (deux seaux emboîtés : reposés, alerte) ; capsule : pas de
   contrôle.
Lâcher : vanne fermée (électroaimants coupés pour une capsule), puis remontée.

Les brosses du lavage (un pas avec `brosses`) ne tournent que si `verrou_brosses` (donné par
le Lavage) l'accepte : tête à sa hauteur de travail au-dessus du fût, objet tenu (vide).

Ces verrous ne protègent que la MACHINE : la sécurité des personnes reste câblée.
"""

import math
import time
from collections.abc import Callable, Generator
from dataclasses import asdict, dataclass
from typing import Protocol

from vidange.chef import ErreurEtape
from vidange.journal import donner_journal
from vidange.prehension.regles import Contexte, Objet, Pose, ReglesPrehension
from vidange.prehension.tete import Pas, Resultat, Tete
from vidange.reglages import Machine

journal = donner_journal("prehension")

QUOI_FAIRE = (
    "Regarder la vidéo de la préhension : la tête est-elle bloquée, l'objet mal posé ou absent ? "
    "Corriger, puis acquitter et donner le Go : le geste est refait depuis le début."
)
QUOI_FAIRE_CONTACT = (
    "Le contact de la tête n'est pas venu à la hauteur attendue : regarder la vidéo (objet absent, "
    "mal posé, deux objets empilés, anse levée ?). Corriger, puis acquitter et donner le Go."
)
QUOI_FAIRE_VIDE = (
    "La ventouse ne tient pas l'objet (vide trop faible) : regarder la vidéo et la ventouse "
    "(usée, sale, objet mouillé ou fendu ?). L'objet a été reposé. Corriger, puis acquitter et "
    "donner le Go."
)
QUOI_FAIRE_POIDS = (
    "Le poids de l'objet pris n'est pas celui attendu (deux seaux emboîtés, objet plein ou "
    "cassé ?) : l'objet a été reposé. Le regarder, séparer les seaux à la main s'il le faut, puis "
    "acquitter et donner le Go."
)
QUOI_FAIRE_VISSAGE = (
    "Le vissage de la capsule s'est mal passé (appui trop fort ou trop faible) : regarder la "
    "vidéo, la capsule et le bocal (filet abîmé, capsule de travers ?). Corriger, puis acquitter "
    "et donner le Go."
)
QUOI_FAIRE_PORTE_BOCAL = (
    "Le porte-bocal n'est pas prêt pour la préhension : regarder la vidéo du porte-bocal (mors, "
    "bocal), corriger, puis acquitter et donner le Go."
)

# Écart sous lequel deux positions sont égales (m ou °).
_EGAL = 1e-6


@dataclass(frozen=True)
class Attente:
    """Attendre que `test` soit vrai, au plus `delai_s` (sinon : alarme avec `erreur`)."""

    texte: str
    test: Callable[[], bool]
    delai_s: float
    erreur: str
    quoi_faire: str = ""


Geste = Generator[Pas | Attente, Resultat | None, None]


class PorteBocal(Protocol):
    """Ce que la préhension demande au porte-bocal (vidange.porte_bocal)."""

    def ouvrir_mors(self) -> None: ...

    def approcher_mors(self) -> None: ...

    def serrer_bocal(self) -> None: ...

    def serre(self) -> bool: ...

    def ouverts(self) -> bool: ...

    def fini(self) -> bool: ...


def _m(valeur: float) -> str:
    return f"{valeur:.3f}".rstrip("0").rstrip(".").replace(".", ",")


class Prehension:
    def __init__(
        self,
        machine: Machine,
        tete: Tete,
        porte_bocal: PorteBocal | None = None,
        horloge: Callable[[], float] = time.monotonic,
        # Cases vides des autres modules (valeurs pour le simulateur et les essais) :
        panneau_rabattu: Callable[[], bool] = lambda: False,
        echange_fut: Callable[[], bool] = lambda: False,
        camera_dosage_pivote: Callable[[], bool] = lambda: False,
        anse_levee: Callable[[], bool] = lambda: False,
        photo: Callable[[str], object] = lambda raison: None,
        agitateur_x: Callable[[], float | None] = lambda: None,
        manivelle_en_bas: Callable[[], bool] = lambda: False,
        griffe_en_butee_haute: Callable[[], bool] = lambda: False,
    ) -> None:
        """`panneau_rabattu`, `echange_fut` : PosteFut.panneau_vu_rabattu, echange_en_cours.
        `camera_dosage_pivote` : la caméra du dosage pivote (Vision, tâche 22). `anse_levee` :
        la caméra voit une anse levée dans le seau à prendre (tâche 22). `photo(raison)` :
        photo notée avec une alerte (choc). `agitateur_x`, `manivelle_en_bas` : ce que dit le
        Mycélium (Mycelium.x_agitateur, en_bas : où est son bocal sur la glissière) ;
        `griffe_en_butee_haute` : ce que dit la griffe. Sans eux, la tête ne descend jamais au
        porte-bocal et ne passe jamais au-dessus de la glissière de l'agitateur."""
        assert machine.prehension is not None and machine.griffe is not None
        self.reglages = machine.prehension
        self.formats = machine.griffe.formats
        self.course_a = machine.axes["prehension_a"].course
        self.regles = ReglesPrehension(machine)
        self.tete = tete
        self.porte_bocal = porte_bocal
        self._horloge = horloge
        self._panneau_rabattu = panneau_rabattu
        self._echange_fut = echange_fut
        self._camera_dosage_pivote = camera_dosage_pivote
        self._anse_levee = anse_levee
        self._photo = photo
        self._agitateur_x = agitateur_x
        self._manivelle_en_bas = manivelle_en_bas
        self._griffe_en_butee_haute = griffe_en_butee_haute
        # Verrou du noyau et de la couronne du lavage (vidange.lavage) : raison du refus, ou
        # None. Sans lavage, les brosses ne tournent jamais.
        self.verrou_brosses: Callable[[Pose], str | None] = lambda pose: "pas de lavage"
        # Ce que tient la tête, son poids pesé (N), et le vide de la dernière prise (kPa).
        self.objet: Objet | None = None
        self.poids_porte_n = 0.0
        self.vide_prise_kpa: float | None = None
        self.pose: Pose | None = None
        self._geste: Geste | None = None
        self._pas: Pas | Attente | None = None
        self._depuis = 0.0
        self._pause_depuis: float | None = None

    # ------------------------------------------------------------ état

    def contexte(self) -> Contexte:
        return Contexte(
            panneau_rabattu=self._panneau_rabattu(),
            camera_dosage_pivote=self._camera_dosage_pivote(),
            echange_fut=self._echange_fut(),
            objet=self.objet,
            agitateur_x=self._agitateur_x(),
            manivelle_en_bas=self._manivelle_en_bas(),
            mors=self._mors_etat(),
            griffe_en_butee_haute=self._griffe_en_butee_haute(),
        )

    def _mors_etat(self) -> str | None:
        porte_bocal = self.porte_bocal
        if porte_bocal is None:
            return None
        if porte_bocal.ouverts():
            return "ouverts"
        return "serres" if porte_bocal.serre() else None

    def tient_un_objet(self) -> bool:
        """Vide confirmé sur l'objet tenu par la ventouse (verrou du noyau du Lavage : sa
        rotation s'arrête à toute perte de vide)."""
        if self.objet is None or self.objet.aimants:
            return False
        vide = self.tete.vide_kpa()
        return vide is not None and vide <= self.reglages.vide.perte_kpa

    def hors_boite_camera_dosage(self) -> bool:
        """Pour le verrou de la caméra du dosage : elle ne pivote que si la tête (et ce qu'elle
        tient) est hors de sa boîte."""
        try:
            pose = self.tete.position()
        except ErreurEtape:
            return False
        return not self.regles.dans_boite_camera_dosage(pose, self.objet)

    def refus_manuel(self, cible: Pose) -> str | None:
        """Pour le mode manuel du téléphone : les mêmes verrous que les gestes."""
        try:
            depart = self.tete.position()
        except ErreurEtape as erreur:
            return str(erreur)
        return self.regles.refus_mouvement(depart, cible, self.contexte())

    def memoire(self) -> dict:
        """Ce que tient la tête, à noter dans le carnet du chef (reprise après coupure)."""
        objet = self.objet
        return {
            "objet": None if objet is None else asdict(objet),
            "poids_porte_n": self.poids_porte_n,
        }

    def retrouver(self, memoire: dict) -> None:
        objet = memoire.get("objet")
        self.objet = None if objet is None else Objet(**objet)
        self.poids_porte_n = memoire.get("poids_porte_n", 0.0)

    def objet_par_nom(self, nom: str, format: str | None = None) -> Objet:
        """L'objet `nom` de machine.yaml ; un seau prend le rayon, la hauteur et la tare de son
        format (table des formats), quand elle les a. Un seau retourné (lavage) pend sous la
        face : sa hauteur est en dessous."""
        if nom not in self.reglages.objets:
            raise ErreurEtape(f"préhension : objet inconnu « {nom} » (machine.yaml → objets)")
        valeurs: dict[str, float] = {}
        if format is not None:
            seau = self.formats.get(format)
            if seau is None:
                raise ErreurEtape(f"préhension : format de seau inconnu « {format} »")
            valeurs["rayon_m"] = seau.rayon_haut
            if seau.hauteur is not None:
                valeurs["dessous_m" if nom == "seau_retourne" else "dessus_m"] = seau.hauteur
            if seau.tare_kg is not None:
                valeurs["poids_n"] = seau.tare_kg * 9.81
        return Objet.depuis(nom, self.reglages.objets[nom], **valeurs)

    # ------------------------------------------------------------ déroulé d'un geste

    def lancer(self, geste: Callable[[], Geste]) -> None:
        """Action d'une étape : le geste part depuis là où est la tête."""
        self.pose = self.tete.position()
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

    def _envoyer(self, pas: Pas | Attente) -> None:
        assert self.pose is not None
        self._pas = pas
        self._depuis = self._horloge()
        if isinstance(pas, Attente) or not (pas.cibles or pas.brosses):
            return
        cible = self.pose.avec(**pas.cibles)
        refus = self.regles.refus_mouvement(self.pose, cible, self.contexte())
        if refus is None and pas.brosses:
            refus = self.verrou_brosses(self.pose)
        if refus is not None:
            self._geste = self._pas = None
            raise ErreurEtape(f"préhension, « {pas.texte} » refusé : {refus}", QUOI_FAIRE)
        journal.debug("Préhension : %s", pas.texte)
        self.tete.executer(pas, cible, self.poids_porte_n)

    def geste_fini(self) -> bool:
        """Condition de fin des étapes : fait partir les pas l'un après l'autre."""
        while self._geste is not None:
            pas = self._pas
            assert pas is not None and self.pose is not None
            ecoule = self._horloge() - self._depuis
            if isinstance(pas, Attente):
                if not pas.test():
                    if ecoule <= pas.delai_s:
                        return False
                    self._geste = self._pas = None
                    raise ErreurEtape(f"préhension : {pas.erreur}", pas.quoi_faire or QUOI_FAIRE)
                resultat = Resultat(pose=self.pose)
            elif not (pas.cibles or pas.brosses):
                if ecoule < pas.attente_s:
                    return False
                force = self.tete.peser() if pas.pesee else None
                resultat = Resultat(pose=self.pose, force_n=force)
            else:
                if not self.tete.fini():
                    return False
                resultat = self.tete.resultat()
                self.pose = resultat.pose
            self._suivant(resultat)
        return True

    def pauser(self) -> None:
        if self._pause_depuis is None:
            self._pause_depuis = self._horloge()
        self.tete.pauser()

    def reprendre(self) -> None:
        # Le temps de la pause ne compte pas dans l'attente en cours (délais, durées).
        if self._pause_depuis is not None:
            self._depuis += self._horloge() - self._pause_depuis
            self._pause_depuis = None
        self.tete.reprendre()

    def arreter(self) -> None:
        """Alarme : le mouvement s'arrête. Après un choc, la tête remonte lentement (droit vers
        le haut, de remontee_choc_m au plus), et une photo est notée avec l'alerte."""
        self._geste = self._pas = None
        self.tete.arreter()
        if not self.tete.choc:
            return
        self._photo("choc de la préhension")
        try:
            pose = self.tete.position()
            haut = min(
                pose.z + self.reglages.force.remontee_choc_m,
                self.regles.hauteur_trajet(self.objet, pose.y),
            )
            if haut <= pose.z + _EGAL:
                return
            cible = pose.avec(z=haut)
            refus = self.regles.refus_mouvement(pose, cible, self.contexte())
            if refus is not None:
                journal.error("Préhension : remontée après le choc refusée : %s", refus)
                return
            journal.warning("Préhension : choc, remontée lente de la tête")
            self.tete.executer(
                Pas("remontée lente après le choc", {"z": haut}, vitesse="remontee_choc"),
                cible,
                self.poids_porte_n,
            )
        except ErreurEtape as erreur:
            journal.error("Préhension : remontée après le choc impossible : %s", erreur)

    # ------------------------------------------------------------ morceaux de gestes

    def _monter(self) -> Geste:
        """La face « en haut » (pour l'objet tenu), sans bouger le pont."""
        assert self.pose is not None
        if self.tete.choc:
            self.tete.oublier_choc()
        haut = self.regles.hauteur_trajet(self.objet, self.pose.y)
        if self.pose.z < haut - _EGAL:
            yield Pas("monter", {"z": haut}, choc=True)

    def _aller(self, x: float, y: float) -> Geste:
        """En haut, puis le pont jusqu'à l'axe (x, y) ; accélération réduite avec un seau."""
        yield from self._monter()
        assert self.pose is not None
        if math.isclose(self.pose.x, x, abs_tol=_EGAL) and math.isclose(
            self.pose.y, y, abs_tol=_EGAL
        ):
            return
        haut = self.regles.hauteur_trajet(self.objet, self.pose.y, y)
        if self.pose.z > haut + _EGAL:
            # Seau tenu : plus bas au-dessus des piles que côté opérateur (règle 3).
            yield Pas("descendre à la hauteur du trajet", {"z": haut})
        self.tete.acceleration_seau(
            self.objet is not None and self.objet.sorte in ("seau", "seau_retourne")
        )
        yield Pas("trajet", {"x": x, "y": y}, choc=True)

    def _orienter(self, angle: float) -> Geste:
        """Tête à l'angle voulu (à 360° près, le plus proche dans la course de la rotation)."""
        assert self.pose is not None
        debut, fin = self.course_a
        candidats = [
            angle + 360 * tour for tour in range(-3, 4) if debut <= angle + 360 * tour <= fin
        ]
        if not candidats:
            raise ErreurEtape(f"orientation {angle:g}° hors de la course de la rotation de la tête")
        voulu = min(candidats, key=lambda a: abs(a - self.pose.a))  # type: ignore[union-attr]
        if abs(self.pose.a - voulu) > _EGAL:
            yield Pas("orienter la tête", {"a": voulu})

    def _descendre(self, contact_z: float, texte: str, seau_a_prendre: bool = False) -> Geste:
        """Descente au contact attendu à `contact_z` (face de la tête), lente sur les derniers
        cm. Rend la cote où le contact est venu (dans self.pose)."""
        assert self.pose is not None
        descente = self.reglages.descente
        approche = contact_z + descente.approche_m
        if self.pose.z > approche + _EGAL:
            resultat = yield Pas(f"descente ({texte})", {"z": approche}, palper=True)
            assert resultat is not None
            if resultat.contact:
                self._contact_faux(resultat.pose.z, contact_z, texte, seau_a_prendre)
        bas = contact_z - descente.ecart_contact_max_m
        resultat = yield Pas(
            f"approche lente ({texte})", {"z": bas}, vitesse="approche", palper=True
        )
        assert resultat is not None
        if not resultat.contact:
            raise ErreurEtape(
                f"préhension, {texte} : contact trop bas, rien touché jusqu'à {_m(bas)} m "
                f"(attendu à {_m(contact_z)} m)",
                QUOI_FAIRE_CONTACT,
            )
        z = resultat.pose.z
        journal.info("Préhension, %s : contact à %.4f m (attendu %.4f m)", texte, z, contact_z)
        if abs(z - contact_z) > descente.ecart_contact_max_m + _EGAL:
            self._contact_faux(z, contact_z, texte, seau_a_prendre)

    def _contact_faux(self, z: float, attendu: float, texte: str, seau_a_prendre: bool) -> None:
        cause = " : anse levée ?" if seau_a_prendre and z > attendu else ""
        raise ErreurEtape(
            f"préhension, {texte} : contact à {_m(z)} m, attendu à {_m(attendu)} m "
            f"(± {_m(self.reglages.descente.ecart_contact_max_m)}){cause}",
            QUOI_FAIRE_CONTACT,
        )

    def _attendre_vide(self) -> Geste:
        vide = self.reglages.vide

        def bon() -> bool:
            valeur = self.tete.vide_kpa()
            return valeur is not None and valeur <= vide.prise_kpa

        yield Attente(
            "vide de la prise",
            bon,
            vide.delai_prise_s,
            f"vide de {vide.prise_kpa:g} kPa pas atteint en {vide.delai_prise_s:g} s",
            QUOI_FAIRE_VIDE,
        )

    def _relacher(self, aimants: bool) -> Geste:
        """Vanne fermée (électroaimants coupés pour une capsule), le temps que l'objet parte."""
        if aimants:
            self.tete.aimants(False)
        else:
            self.tete.vanne(False)
        yield Pas("relâcher", attente_s=self.reglages.vide.relache_s)

    def _prendre_ici(
        self,
        objet: Objet,
        contact_z: float,
        avant_levee: Callable[[], Geste] | None = None,
    ) -> Geste:
        """La tête est au contact de l'objet : vide, levée surveillée, pesée."""
        reglages = self.reglages
        assert self.pose is not None
        z_contact = self.pose.z
        echecs = 0
        while True:
            self.tete.vanne(True)
            yield from self._attendre_vide()
            self.vide_prise_kpa = self.tete.vide_kpa()
            journal.info(
                "Préhension : prise d'un(e) %s, vide %.1f kPa", objet.sorte, self.vide_prise_kpa
            )
            if avant_levee is not None:
                yield from avant_levee()
            # Pendant la levée, la tête tient déjà l'objet (règles du seau tenu...).
            self.objet = objet
            perdu = yield from self._lever(objet, z_contact)
            if not perdu:
                break
            echecs += 1
            journal.warning(
                "Préhension : vide perdu pendant la levée d'un(e) %s (échec n° %d)",
                objet.sorte,
                echecs,
            )
            # Redescendre et reposer.
            yield from self._descendre(contact_z, f"reposer le(la) {objet.sorte}")
            self.objet = None
            yield from self._relacher(aimants=False)
            if echecs >= reglages.vide.essais_max:
                yield from self._monter()
                raise ErreurEtape(
                    f"préhension : vide perdu {echecs} fois pendant la levée d'un(e) "
                    f"{objet.sorte} ({_m(reglages.vide.perte_kpa)} kPa) ; objet reposé",
                    QUOI_FAIRE_VIDE,
                )
        yield from self._confirmer_poids(objet, contact_z)

    def _lever(self, objet: Objet, z_contact: float) -> Generator[Pas, Resultat | None, bool]:
        """Levée lente sur les premiers mm, puis normale (lente si le vide est faible). Rend vrai
        si le vide a été perdu (la tête s'est arrêtée)."""
        assert self.pose is not None
        vide = self.reglages.vide
        haut = self.regles.hauteur_trajet(objet, self.pose.y)
        lente = min(z_contact + self.reglages.levee_lente_m, haut)
        resultat = yield Pas(
            "levée lente", {"z": lente}, vitesse="levee_lente", vide_perte_kpa=vide.perte_kpa
        )
        assert resultat is not None
        if resultat.arret == "vide":
            return True
        valeur = self.tete.vide_kpa()
        vitesse = None if valeur is not None and valeur <= vide.prise_kpa else "levee_lente"
        if haut > lente + _EGAL:
            resultat = yield Pas(
                "levée", {"z": haut}, vitesse=vitesse, vide_perte_kpa=vide.perte_kpa
            )
            assert resultat is not None
            if resultat.arret == "vide":
                return True
        return False

    def _confirmer_poids(self, objet: Objet, contact_z: float) -> Geste:
        """Pesée en l'air : le poids doit être celui attendu (sinon l'objet est reposé)."""
        force = self.reglages.force
        resultat = yield Pas("pesée", attente_s=force.attente_pesee_s, pesee=True)
        assert resultat is not None and resultat.force_n is not None
        poids = resultat.force_n
        journal.info("Préhension : %s pesé(e) %.1f N", objet.sorte, poids)
        if objet.poids_n is None:
            self.poids_porte_n = poids
            return
        attendu, tolerance = objet.poids_n, objet.tolerance_n
        if abs(poids - attendu) <= tolerance:
            self.poids_porte_n = poids
            return
        if objet.sorte == "seau" and poids >= 2 * attendu - tolerance:
            raison = f"deux seaux emboîtés pris ({poids:.1f} N, un seau ≈ {attendu:g} N)"
        else:
            raison = f"{objet.sorte} pesé(e) {poids:.1f} N, attendu {attendu:g} ± {tolerance:g} N"
        journal.warning("Préhension : %s : l'objet est reposé", raison)
        self.poids_porte_n = poids
        yield from self._descendre(contact_z, f"reposer le(la) {objet.sorte}")
        self.objet, self.poids_porte_n = None, 0.0
        yield from self._relacher(objet.aimants)
        yield from self._monter()
        raise ErreurEtape(f"préhension : {raison} ; objet reposé", QUOI_FAIRE_POIDS)

    def _lacher_ici(self) -> Geste:
        objet = self.objet
        assert objet is not None
        journal.info("Préhension : %s lâché(e)", objet.sorte)
        self.objet, self.poids_porte_n = None, 0.0
        yield from self._relacher(objet.aimants)
        self.tete.acceleration_seau(False)

    # ------------------------------------------------------------ pour les autres modules

    # Morceaux de gestes que les modules qui se servent de la tête (Lavage...) enchaînent dans
    # leurs propres gestes, joués par `lancer`.

    def monter(self) -> Geste:
        return self._monter()

    def aller(self, x: float, y: float) -> Geste:
        return self._aller(x, y)

    def orienter(self, angle: float) -> Geste:
        return self._orienter(angle)

    def attendre_vide(self) -> Geste:
        return self._attendre_vide()

    def lacher(self) -> Geste:
        """Lâcher l'objet tenu là où est la tête (retourneur de couvercles)."""
        return self._lacher_ici()

    # ------------------------------------------------------------ les gestes

    def geste_aller(self, x: float, y: float) -> Geste:
        """Tête en haut, puis le pont jusqu'à l'axe (x, y)."""
        yield from self._aller(x, y)

    def geste_prendre(
        self, nom: str, x: float, y: float, contact_z: float, format: str | None = None
    ) -> Geste:
        """Prendre l'objet `nom` (machine.yaml → prehension → objets) dont la face de la tête
        touche le dessus à `contact_z`, sous l'axe (x, y). `format` : format du seau."""
        objet = self.objet_par_nom(nom, format)
        if self.objet is not None:
            raise ErreurEtape(f"préhension : la tête tient déjà un(e) {self.objet.sorte}")
        if nom == "seau" and self._anse_levee():
            raise ErreurEtape(
                "préhension : la caméra voit une anse levée dans le seau", QUOI_FAIRE_CONTACT
            )
        yield from self._aller(x, y)
        self.tete.tarer()
        if objet.aimants:
            yield from self._descendre(contact_z, f"prendre un(e) {nom}")
            self.tete.aimants(True)
            self.objet = objet
            yield from self._monter()
            self.poids_porte_n = objet.poids_n or 0.0
            return
        yield from self._descendre(contact_z, f"prendre un(e) {nom}", seau_a_prendre=nom == "seau")
        yield from self._prendre_ici(objet, contact_z)

    def geste_poser(self, x: float, y: float, contact_z: float) -> Geste:
        """Poser l'objet tenu : la face de la tête est à `contact_z` quand il touche."""
        objet = self.objet
        if objet is None:
            raise ErreurEtape("préhension : la tête ne tient rien à poser")
        yield from self._aller(x, y)
        yield from self._descendre(contact_z, f"poser le(la) {objet.sorte}")
        yield from self._lacher_ici()
        yield from self._monter()

    def _porte_bocal(self) -> PorteBocal:
        if self.porte_bocal is None:
            raise ErreurEtape("préhension : pas de porte-bocal")
        return self.porte_bocal

    def _mors(self, texte: str, geste: Callable[[], None]) -> Geste:
        porte_bocal = self._porte_bocal()
        geste()
        delai = self.reglages.porte_bocal.mors_max_s
        yield Attente(texte, porte_bocal.fini, delai, f"{texte} : pas fini en {delai:g} s")

    def _au_dessus_du_porte_bocal(self) -> Geste:
        """En haut au-dessus du porte-bocal, tête orientée (méplats, ± 3°)."""
        reglages = self.reglages.porte_bocal
        yield from self._aller(reglages.x, reglages.y)
        yield from self._orienter(reglages.orientation_deg)
        assert self.pose is not None
        ecart = abs((self.pose.a - reglages.orientation_deg + 180) % 360 - 180)
        if ecart > reglages.tolerance_orientation_deg:
            raise ErreurEtape(
                f"préhension : tête orientée à {self.pose.a:.1f}°, il faut "
                f"{reglages.orientation_deg:g} ± {reglages.tolerance_orientation_deg:g}° pour le "
                "porte-bocal",
                QUOI_FAIRE_PORTE_BOCAL,
            )

    def geste_poser_bocal(self) -> Geste:
        """Poser le bocal tenu dans le porte-bocal : mors grands ouverts, bocal à sa hauteur
        exacte, mors à « Ø 98 » à faible courant, lâcher, remonter, puis serrer le bocal."""
        reglages = self.reglages.porte_bocal
        porte_bocal = self._porte_bocal()
        if self.objet is None or self.objet.sorte != "bocal":
            raise ErreurEtape("préhension : la tête ne tient pas de bocal")
        yield from self._mors("ouverture des mors", porte_bocal.ouvrir_mors)
        yield from self._au_dessus_du_porte_bocal()
        assert self.pose is not None
        approche = reglages.face_z + self.reglages.descente.approche_m
        if self.pose.z > approche + _EGAL:
            yield Pas("descente vers le porte-bocal", {"z": approche})
        resultat = yield Pas("bocal à sa hauteur", {"z": reglages.face_z}, vitesse="approche")
        assert resultat is not None
        if abs(resultat.pose.z - reglages.face_z) > reglages.tolerance_hauteur_m:
            raise ErreurEtape(
                f"préhension : bocal à {_m(resultat.pose.z)} m, il faut {_m(reglages.face_z)} m "
                f"± {reglages.tolerance_hauteur_m * 1000:g} mm",
                QUOI_FAIRE_PORTE_BOCAL,
            )
        yield from self._mors(
            "approche des mors (Ø 98, faible courant)", porte_bocal.approcher_mors
        )
        yield from self._lacher_ici()
        yield Pas(
            "remonter avant le serrage",
            {"z": reglages.face_z + reglages.remontee_min_m},
            vitesse="approche",
        )
        yield from self._mors("serrage du bocal", porte_bocal.serrer_bocal)
        yield from self._monter()

    def geste_reprendre_bocal(self) -> Geste:
        """Reprendre le bocal serré dans le porte-bocal : descente lente entre les mors, prise,
        mors ouverts, remontée."""
        reglages = self.reglages.porte_bocal
        porte_bocal = self._porte_bocal()
        if self.objet is not None:
            raise ErreurEtape(f"préhension : la tête tient déjà un(e) {self.objet.sorte}")
        if not porte_bocal.serre():
            raise ErreurEtape(
                "préhension : le bocal n'est pas serré dans le porte-bocal", QUOI_FAIRE_PORTE_BOCAL
            )
        yield from self._au_dessus_du_porte_bocal()
        self.tete.tarer()
        yield from self._descendre(reglages.face_z, "reprendre le bocal")

        def ouvrir() -> Geste:
            yield from self._mors("ouverture des mors", porte_bocal.ouvrir_mors)

        yield from self._prendre_ici(self.objet_par_nom("bocal"), reglages.face_z, ouvrir)

    def geste_visser(self, x: float, y: float, contact_z: float, devisser: bool = False) -> Geste:
        """Visser la capsule tenue (électroaimants) sur le bocal sous (x, y), ou la dévisser
        (tête vide : elle la prend). `contact_z` : face de la tête au contact de la capsule.
        Rotation et Z ensemble ; appui lu par le capteur de force."""
        vissage = self.reglages.vissage
        tenue = self.objet
        if devisser and tenue is not None:
            raise ErreurEtape(f"préhension : la tête tient déjà un(e) {tenue.sorte}")
        if not devisser and (tenue is None or tenue.sorte != "capsule"):
            raise ErreurEtape("préhension : la tête ne tient pas de capsule à visser")
        yield from self._aller(x, y)
        if devisser:
            self.tete.tarer()
        quoi = "dévisser" if devisser else "visser"
        yield from self._descendre(contact_z, f"{quoi} la capsule")
        assert self.pose is not None
        z_contact = self.pose.z
        if devisser:
            self.tete.aimants(True)
        resultat = yield Pas(
            "appui sur la capsule",
            {"z": self.pose.z - vissage.course_appui_m},
            vitesse="approche",
            appui_arret_n=vissage.appui_n,
            appui_max_n=vissage.arret_n,
        )
        assert resultat is not None
        self._verifier_appui(resultat, quoi, fin=False)
        assert self.pose is not None
        # Visser = sens horaire vu d'en haut = rotation positive (aucun axe inversé dans
        # FluidNC) ; la capsule descend en se vissant, remonte en se dévissant.
        sens = -1 if devisser else 1
        cible = {
            "a": self.pose.a + sens * vissage.angle_deg,
            "z": self.pose.z - sens * vissage.descente_m,
        }
        resultat = yield Pas(
            quoi, cible, vitesse="approche", vissage=True, appui_max_n=vissage.arret_n
        )
        assert resultat is not None
        self._verifier_appui(resultat, quoi, fin=True)
        if devisser:
            self.objet = self.objet_par_nom("capsule")
            self.poids_porte_n = self.objet.poids_n or 0.0
        else:
            self.objet, self.poids_porte_n = None, 0.0
            yield from self._relacher(aimants=True)
        # L'appui est relâché avant la remontée (sinon la pesée verrait un choc).
        yield Pas(
            "relâcher l'appui",
            {"z": z_contact + self.reglages.descente.ecart_contact_max_m},
            vitesse="approche",
        )
        yield from self._monter()

    def _verifier_appui(self, resultat: Resultat, quoi: str, fin: bool) -> None:
        vissage = self.reglages.vissage
        if resultat.arret == "appui_max":
            raise ErreurEtape(
                f"préhension, {quoi} : appui de {resultat.appui_max_n or 0:.0f} N, au-delà de "
                f"{vissage.arret_n:g} N : arrêt",
                QUOI_FAIRE_VISSAGE,
            )
        appui = resultat.appui_n
        if not fin:
            if resultat.arret != "appui":
                raise ErreurEtape(
                    f"préhension, {quoi} : appui de {vissage.appui_n:g} N pas atteint en "
                    f"{_m(vissage.course_appui_m)} m",
                    QUOI_FAIRE_VISSAGE,
                )
            return
        if appui is None or not vissage.appui_min_n <= appui <= vissage.appui_max_n:
            lu = "inconnu" if appui is None else f"{appui:.0f} N"
            raise ErreurEtape(
                f"préhension, {quoi} : appui {lu} à la fin, accepté de {vissage.appui_min_n:g} à "
                f"{vissage.appui_max_n:g} N",
                QUOI_FAIRE_VISSAGE,
            )
