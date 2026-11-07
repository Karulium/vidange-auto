"""Versement de la griffe dans un bocal de semence, mode bocaux (tâche 43 bis).

    versement = Versement(griffe, entonnoir, fichier=donnees / "versement.json",
                          distance_m=distance_de_la_tete)
    module = module_entonnoir(entonnoir, prehension, bocaux, versement=versement)

Le geste, tel que la fiche du fil Griffe le donne (griffe/logiciel/versement-bocal.md, 07/11) :
1. prise dans le fût d'une dose d'≈ 300 g (maïs : sans mâchouiller), pesée à l'arrêt ; hors de la
   plage, la prise est rendue au fût et refaite à côté ; la tare « godet vide » est pesée à chaque
   prise (godet ouvert, vide, au-dessus du maïs, à l'arrêt) ;
2. la griffe remonte, godet fermé, tête à A = 0 : `p_avant` pesé à l'arrêt ; godet vide ou hors
   de la plage : retour au fût ;
3. JAMAIS de versement si `entonnoir_place` n'est pas ce bocal (Entonnoir.refus_versement) ;
4. mât au-dessus du centre du col (caméra, à centrage_max_m), garde du boîtier de la caméra du
   bocal respectée (règles de la griffe), descente des axes à axes_z, arrêt ;
5. ouverture de « fermé » à ouverture_deg, lente ; attente, tête immobile, aucune rotation ;
6. pesée : poids revenu à la tare → fini, dose versée = p_avant − p_après, notée pour le bocal ;
   la tête remonte (remontee_avant_fermer_m) AVANT de fermer le godet, puis va en haut ;
7. grains restés : secousses (aller-retour entre deux angles), pesée ; grand ouvert, pesée ;
   puis alerte « grains collés », griffe immobile, godet ouvert : jamais refermé au-dessus du
   bocal avec des grains dedans ;
8. capteur de distance de la tête (à travers le godet ouvert) : surface des grains plus haute que
   l'entonnoir vide moins la marge → alerte « entonnoir bouché », bocal « suspect », rien
   d'automatique ; pesée instable (3 essais) → alerte.

Refait après une alarme (Go de Karulium), le versement d'un bocal commencé continue : tant que le
godet ne s'est pas ouvert au-dessus du bocal, la griffe recommence par une prise (ce qui reste dans
le godet retombe au fût) ; une fois ouvert, elle reprend à la pesée, jamais une 2e dose. La phase
« ouvert » (et « fait ») est gardée dans un fichier de donnees/ : elle survit à une coupure.

Les chiffres sont dans machine.yaml (griffe → versement_bocal). Ces verrous ne protègent que la
MACHINE : la sécurité des personnes reste câblée.
"""

import json
import math
import os
from collections.abc import Callable, Generator
from dataclasses import asdict, dataclass
from pathlib import Path

from vidange.chef import Condition, ErreurEtape
from vidange.entonnoir.entonnoir import Entonnoir, lisible
from vidange.griffe.bras import G, Pas, Resultat
from vidange.griffe.griffe import DoseDonnee, Griffe, Pesee
from vidange.griffe.regles import Pose
from vidange.journal import donner_journal
from vidange.registre import ErreurRegistre
from vidange.reglages import VersementBocal

journal = donner_journal("griffe.versement")

Geste = Generator[Pas, Resultat, None]

NOM_FICHIER = "versement.json"
OUVERT = "ouvert"
FAIT = "fait"
# Écart sous lequel deux positions sont égales (m).
_EGAL = 1e-6

QUOI_FAIRE = (
    "Regarder la vidéo de la griffe et de l'entonnoir. Corriger, puis acquitter et donner le Go : "
    "le versement de ce bocal continue (jamais une 2e dose)."
)
QUOI_FAIRE_COLLES = (
    "Des grains sont restés collés dans le godet : la griffe est immobile, godet ouvert au-dessus "
    "de l'entonnoir (elle ne le referme jamais avec des grains dedans). Faire tomber les grains à "
    "la main dans l'entonnoir, puis acquitter et donner le Go : la griffe repèse et finit."
)
QUOI_FAIRE_BOUCHE = (
    "Les grains ne descendent pas dans le col : l'entonnoir est bouché. Rien n'a été fait "
    "d'automatique (il ne peut pas déborder avec une seule dose). Faire descendre le maïs à la "
    "main, vérifier le bocal (noté « suspect »), puis acquitter et donner le Go : le lot continue."
)
QUOI_FAIRE_INSTABLE = (
    "La pesée de la griffe ne se stabilise pas (vibration, chaîne qui tire ?). Regarder la griffe "
    "et ses câbles, puis acquitter et donner le Go : la pesée est refaite."
)
QUOI_FAIRE_FUT_VIDE = (
    "Le fût est vide : changer le fût au poste (plateau, bouton « Prêt »), puis acquitter et "
    "donner le Go : la griffe reprend une dose dans le nouveau fût."
)
QUOI_FAIRE_PAS_FINI = (
    "Regarder la griffe : son godet est peut-être ouvert, avec des grains, au-dessus d'un autre "
    "bocal. Le vider à la main dans l'entonnoir si besoin et vérifier ce bocal, puis acquitter et "
    "donner le Go."
)
QUOI_FAIRE_REFUS = (
    "La griffe ne peut pas verser dans ce bocal (règle de position, voir le message). Regarder "
    "le bocal et l'entonnoir, puis acquitter et donner le Go."
)


@dataclass
class EtatVersement:
    """Ce qui est gardé : le bocal, la phase (« ouvert » : le godet s'est ouvert au-dessus de lui ;
    « fait » : fini), la dose pesée avant d'ouvrir (kg) et la tare « godet vide » (N)."""

    bocal: str | None = None
    phase: str | None = None
    avant_kg: float | None = None
    tare_n: float | None = None


def _lire(fichier: Path | None) -> EtatVersement:
    if fichier is None or not fichier.exists():
        return EtatVersement()
    try:
        return EtatVersement(**json.loads(fichier.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as erreur:
        journal.error("Versement : fichier d'état illisible (%s) : oublié", erreur)
        return EtatVersement()


def _ecrire(fichier: Path | None, etat: EtatVersement) -> None:
    """Réécrit d'un coup (fichier provisoire puis remplacement), comme l'état de l'entonnoir."""
    if fichier is None:
        return
    try:
        fichier.parent.mkdir(parents=True, exist_ok=True)
        provisoire = fichier.with_suffix(".tmp")
        provisoire.write_text(json.dumps(asdict(etat)), encoding="utf-8")
        os.replace(provisoire, fichier)
    except OSError as erreur:
        journal.error("Versement : état pas gardé dans %s : %s", fichier, erreur)


def poses_du_bocal(reglages: VersementBocal, x: float, y: float) -> list[Pose]:
    """Les poses de la tête au-dessus d'un col : godet fermé, à chaque ouverture du geste, et
    remontée avant de fermer."""
    godet, secousses = reglages.godet, reglages.secousses
    angles = (reglages.ouverture_deg, *secousses.angles_deg, secousses.grand_ouvert_deg)
    base = Pose(x=x, y=y, z=reglages.axes_z, a=reglages.a_deg, b=0.0)
    poses = [base, *(base.avec(b=godet.b_pour(angle)) for angle in angles)]
    poses.append(base.avec(z=reglages.axes_z + reglages.ouverture.remontee_avant_fermer_m))
    return poses


class Versement:
    def __init__(
        self,
        griffe: Griffe,
        entonnoir: Entonnoir,
        fichier: Path | None = None,
        distance_m: Callable[[], float | None] | None = None,
        noter_dose: Callable[[str, float], object] | None = None,
    ) -> None:
        """`fichier` : où garder la phase (donnees/versement.json ; None : nulle part).
        `distance_m` : le capteur de distance de la tête (VL53L1X, m ; None : pas branché, le
        bouchage n'est pas vérifié). `noter_dose(bocal, kg)` : la dose versée (sinon le registre
        de la griffe, mesure « dose_bocal »)."""
        reglages = griffe.reglages.versement_bocal
        if reglages is None:
            raise ValueError("machine.yaml : pas de partie griffe → versement_bocal")
        self.reglages = reglages
        self.griffe = griffe
        self.entonnoir = entonnoir
        self.fichier = fichier
        self._distance = distance_m
        self._noter_dose = noter_dose
        self.etat = _lire(fichier)
        # Doses versées dans ce lot, par bocal (kg).
        self.doses: dict[str, float] = {}
        self.dose = DoseDonnee(
            min_kg=reglages.dose.plage_kg[0],
            max_kg=reglages.dose.plage_kg[1],
            reprises_max=reglages.dose.prises_max - 1,
            peser=self.peser,
        )
        poste = griffe.poste
        self.entree: tuple[Condition, ...] = (
            griffe.bras.pretes,
            poste.condition_pret,
            poste.condition_mode("production"),
        )
        # Un nouveau fût : le plan de la griffe repart de zéro (niveau du maïs inconnu).
        griffe.nouveau_fut()
        self._distance_dite = False

    # ------------------------------------------------------------ pour le module

    def commence(self, bocal: str) -> bool:
        return self.etat.bocal == bocal

    def verser(self, bocal: str) -> None:
        """Action de l'étape « verser » : le geste part depuis là où est la tête."""
        # « Déjà reçu sa dose » : c'est le module qui le regarde (il note le bocal juste avant).
        refus = self.entonnoir.refus_versement(bocal, reprise=True)
        if refus is not None:
            raise ErreurEtape(f"entonnoir : {refus}", QUOI_FAIRE)
        if self.commence(bocal) and self.etat.phase == FAIT:
            journal.info("Versement : bocal %s déjà fait, rien à refaire", lisible(bocal))
            return
        ancien = self.etat.bocal
        if self.etat.phase == OUVERT and ancien is not None and ancien != bocal:
            # Coupure en plein versement d'un autre bocal : Karulium regarde (son Go suffit).
            self._changer(EtatVersement())
            self.entonnoir.noter_suspect(ancien, f"versement du bocal {lisible(ancien)} pas fini")
            raise ErreurEtape(
                f"le versement du bocal {lisible(ancien)} n'a pas été fini (coupure ?) : il est "
                "noté « suspect »",
                QUOI_FAIRE_PAS_FINI,
            )
        if not self.commence(bocal):
            self._changer(EtatVersement(bocal=bocal))
        self.griffe.lancer(lambda: self.geste_verser(bocal))

    def fini(self) -> bool:
        return self.griffe.geste_fini()

    def pauser(self) -> None:
        self.griffe.pauser()

    def reprendre(self) -> None:
        self.griffe.reprendre()

    def arreter(self) -> None:
        """Alarme : le mouvement s'arrête là, rien d'autre (godet laissé tel quel : jamais
        refermé au-dessus d'un bocal avec des grains dedans)."""
        griffe = self.griffe
        griffe._geste = griffe._pas = None
        griffe.bras.arreter()

    def _changer(self, etat: EtatVersement) -> None:
        self.etat = etat
        _ecrire(self.fichier, etat)

    # ------------------------------------------------------------ pesée à l'arrêt

    def _lectures(self, entre_s: float) -> Pesee:
        """Deux lectures (moyennes) à `entre_s` d'écart ; instable : attendre, relire."""
        pesee, fin = self.reglages.pesee, self.reglages.fin
        bras = self.griffe.bras
        yield Pas("pesée à l'arrêt", attente_s=pesee.attente_s + pesee.moyenne_s)
        premiere = bras.moyenne_n(pesee.moyenne_s)
        for essai in range(1, fin.essais + 1):
            yield Pas("relire la pesée", attente_s=entre_s)
            seconde = bras.moyenne_n(pesee.moyenne_s)
            if abs(seconde - premiere) <= fin.ecart_kg * G:
                return (premiere + seconde) / 2
            if essai == fin.essais:
                break
            journal.info("Versement : pesée instable, nouvel essai")
            yield Pas("attendre que la pesée se calme", attente_s=fin.attente_en_plus_s)
            premiere = bras.moyenne_n(pesee.moyenne_s)
        raise ErreurEtape(
            f"pesée de la griffe instable (plus de {fin.ecart_kg * 1000:g} g entre deux lectures, "
            f"{fin.essais} essais)",
            QUOI_FAIRE_INSTABLE,
        )

    def peser(self) -> Pesee:
        """Charge pendue (N), à l'arrêt."""
        return self._lectures(self.reglages.fin.entre_s)

    def _net(self, stable_s: float | None = None) -> Generator[Pas, Resultat, float]:
        """Poids dans le godet (kg) : charge − tare « godet vide »."""
        tare = self.etat.tare_n
        if tare is None:
            raise ErreurEtape("versement : tare « godet vide » inconnue", QUOI_FAIRE)
        charge = yield from self._lectures(stable_s or self.reglages.fin.entre_s)
        return (charge - tare) / G

    # ------------------------------------------------------------ le geste

    def _vide(self, kg: float) -> bool:
        return kg <= self.reglages.fin.ecart_tare_kg

    def _refus_au_dessus(self, x: float, y: float) -> str | None:
        """Avant toute prise : la tête peut-elle se tenir au-dessus de ce col à chaque ouverture
        du geste (règles de la griffe : godet ouvert, boîtier de la caméra du bocal...) ?"""
        griffe = self.griffe
        contexte = griffe.contexte()
        poses = poses_du_bocal(self.reglages, x, y)
        haut = poses[0].avec(z=griffe.reglages.trajet.z)
        for depart, arrivee in ((haut, poses[0]), *((poses[0], pose) for pose in poses[1:])):
            refus = griffe.regles.refus_mouvement(depart, arrivee, contexte)
            if refus is None:
                refus = griffe.verrou_stockage(depart, arrivee)
            if refus is not None:
                return refus
        return None

    def geste_verser(self, bocal: str) -> Geste:
        reglages, griffe = self.reglages, self.griffe
        x, y = self.entonnoir.axe_pose(bocal)
        if self.etat.phase == OUVERT:
            yield from self._reprendre_ouvert(bocal, x, y)
            return
        refus = self._refus_au_dessus(x, y)
        if refus is not None:
            raise ErreurEtape(
                f"la griffe ne peut pas verser dans le bocal {lisible(bocal)} : {refus}",
                QUOI_FAIRE_REFUS,
            )
        avant = yield from self._prendre_la_dose()
        yield from griffe._aller_au_dessus(x, y, choc=True)
        assert griffe.pose is not None
        ecart = math.hypot(griffe.pose.x - x, griffe.pose.y - y)
        if ecart > reglages.centrage_max_m + _EGAL:
            raise ErreurEtape(
                f"versement : mât à {ecart:.3f} m du centre du col du bocal {lisible(bocal)} (au "
                f"plus {reglages.centrage_max_m:g})",
                QUOI_FAIRE,
            )
        if abs(griffe.pose.a - reglages.a_deg) > griffe.reglages.rotation.tolerance_deg:
            raise ErreurEtape(f"versement : tête à {griffe.pose.a:g}°, il faut {reglages.a_deg:g}°")
        yield Pas("descendre au-dessus de l'entonnoir", {"z": reglages.axes_z}, choc=True)
        # Juste avant d'ouvrir : l'entonnoir est-il toujours sur ce bocal ?
        refus = self.entonnoir.refus_versement(bocal, reprise=True)
        if refus is not None:
            raise ErreurEtape(f"entonnoir : {refus}", QUOI_FAIRE)
        self._changer(EtatVersement(bocal, OUVERT, avant, self.etat.tare_n))
        journal.info("Versement : %.3f kg dans le bocal %s", avant, lisible(bocal))
        yield Pas(
            f"ouvrir à {reglages.ouverture_deg:g}°",
            {"b": reglages.godet.b_pour(reglages.ouverture_deg)},
            vitesse_b=reglages.ouverture.vitesse_m_s,
        )
        yield from self._vider(bocal)

    def _prendre_la_dose(self) -> Generator[Pas, Resultat, float]:
        """Prise(s) dans le fût jusqu'à une dose dans la plage, pesée en haut, godet fermé, tête à
        A = 0. Rend `p_avant` (kg)."""
        griffe, reglages = self.griffe, self.reglages
        bas, haut = reglages.dose.plage_kg
        if griffe.plan.vide:
            # Après « fût vide » et le Go : un nouveau fût (le poste était prêt pour l'étape).
            griffe.nouveau_fut()
        for _ in range(reglages.dose.prises_max):
            griffe.plan.reprendre = False
            while True:
                yield from griffe.geste_prendre(self.dose)
                if griffe.plan.vide:
                    message = griffe.poste.finir_vidange(len(self.doses), "bocaux")
                    raise ErreurEtape(f"griffe : {message}", QUOI_FAIRE_FUT_VIDE)
                if not griffe.plan.reprendre:
                    break
            self.etat.tare_n = griffe.tare_n
            yield from griffe._monter(choc=True)
            avant = yield from self._net()
            if bas <= avant <= haut:
                griffe.plan.godet_kg = avant
                griffe._noter_dose()
                return avant
            if self._vide(avant):
                journal.warning("Versement : godet vide en haut (%.3f kg) : nouvelle prise", avant)
            else:
                journal.warning(
                    "Versement : %.3f kg en haut, hors de %g à %g kg : retour au fût",
                    avant,
                    bas,
                    haut,
                )
            # Retour au fût : la prise suivante s'ouvre dans le fût, la dose y retombe.
        raise ErreurEtape(
            f"griffe : pas de dose de {bas:g} à {haut:g} kg en haut après "
            f"{reglages.dose.prises_max} prises",
            QUOI_FAIRE,
        )

    def _reprendre_ouvert(self, bocal: str, x: float, y: float) -> Geste:
        """Refait après une alarme ou une coupure, godet déjà ouvert au-dessus de ce bocal : on
        repèse et on finit, sans jamais prendre une 2e dose."""
        griffe = self.griffe
        pose = griffe.bras.position()
        au_dessus = math.hypot(pose.x - x, pose.y - y) <= self.reglages.centrage_max_m + _EGAL
        if pose.b > _EGAL and not au_dessus:
            raise ErreurEtape(
                f"versement du bocal {lisible(bocal)} pas fini, godet ouvert ailleurs qu'au-dessus "
                "de lui (des grains peuvent tomber à côté)",
                QUOI_FAIRE,
            )
        if pose.b <= _EGAL:
            # Godet fermé (prise d'origine après une coupure ?) : en haut, puis la pesée dit s'il
            # reste des grains.
            yield from griffe._monter()
            reste = yield from self._net()
            if not self._vide(reste):
                raise ErreurEtape(
                    f"versement du bocal {lisible(bocal)} interrompu : il reste {reste:.3f} kg "
                    "dans le godet fermé",
                    QUOI_FAIRE,
                )
            self._finir(bocal, reste)
            self._changer(EtatVersement(bocal, FAIT, self.etat.avant_kg, self.etat.tare_n))
            return
        yield from self._vider(bocal)

    def _vider(self, bocal: str) -> Geste:
        """Godet ouvert au-dessus de l'entonnoir : attendre, peser ; secousses, grand ouvert, puis
        alerte s'il reste des grains ; sinon dose notée, bouchage regardé, remontée, fermeture."""
        reglages, griffe = self.reglages, self.griffe
        ouverture, secousses, godet = reglages.ouverture, reglages.secousses, reglages.godet
        yield Pas("attendre, tête immobile", attente_s=ouverture.attente_s)
        reste = yield from self._net(reglages.fin.stable_s)
        if not self._vide(reste):
            journal.warning("Versement : %.3f kg restés dans le godet : secousses", reste)
            petit, grand = secousses.angles_deg
            for _ in range(secousses.fois):
                for angle in (petit, grand):
                    yield Pas(
                        f"secousse à {angle:g}°",
                        {"b": godet.b_pour(angle)},
                        vitesse_b=secousses.vitesse_m_s,
                    )
            yield Pas("attendre après les secousses", attente_s=secousses.attente_s)
            reste = yield from self._net(reglages.fin.stable_s)
        if not self._vide(reste):
            journal.warning("Versement : %.3f kg restés : grand ouvert", reste)
            yield Pas(
                f"grand ouvert ({secousses.grand_ouvert_deg:g}°)",
                {"b": godet.b_pour(secousses.grand_ouvert_deg)},
                vitesse_b=ouverture.vitesse_m_s,
            )
            yield Pas("attendre grand ouvert", attente_s=secousses.attente_s)
            reste = yield from self._net(reglages.fin.stable_s)
        if not self._vide(reste):
            raise ErreurEtape(
                f"grains collés dans le godet ({reste:.3f} kg) au-dessus du bocal {lisible(bocal)}",
                QUOI_FAIRE_COLLES,
            )
        bouche = self._entonnoir_bouche()
        self._finir(bocal, reste)
        assert griffe.pose is not None
        yield Pas(
            "remonter avant de fermer",
            {"z": griffe.pose.z + ouverture.remontee_avant_fermer_m},
        )
        yield Pas("fermer le godet", {"b": 0.0}, vitesse_b=ouverture.vitesse_m_s)
        yield from griffe._monter()
        self._changer(EtatVersement(bocal, FAIT, self.etat.avant_kg, self.etat.tare_n))
        if bouche is not None:
            self.entonnoir.noter_suspect(bocal, f"entonnoir bouché sur le bocal {lisible(bocal)}")
            raise ErreurEtape(
                f"entonnoir bouché, bocal {lisible(bocal)} ({bouche})", QUOI_FAIRE_BOUCHE
            )

    def _entonnoir_bouche(self) -> str | None:
        """Ce que voit le capteur de distance de la tête à travers le godet ouvert : None si la
        surface des grains n'est pas plus haute que l'entonnoir vide moins la marge."""
        if self._distance is None:
            if not self._distance_dite:
                journal.warning(
                    "Versement : capteur de distance de la tête pas branché : bouchage de "
                    "l'entonnoir pas vérifié"
                )
                self._distance_dite = True
            return None
        try:
            distance = self._distance()
        except Exception as erreur:
            journal.warning("Versement : capteur de distance muet (%s) : pas vérifié", erreur)
            return None
        if distance is None:
            journal.warning("Versement : capteur de distance sans mesure : bouchage pas vérifié")
            return None
        bouchage = self.reglages.bouchage
        seuil = bouchage.distance_vide_m - bouchage.marge_m
        if distance < seuil:
            return f"grains à {distance:.3f} m du capteur, plus près que {seuil:.3f} m"
        return None

    def _finir(self, bocal: str, reste: float) -> None:
        """La dose versée (p_avant − p_après), notée une fois pour le bocal."""
        avant = self.etat.avant_kg
        assert avant is not None
        if bocal in self.doses:
            return
        if reste < -self.reglages.fin.ecart_tare_kg:
            journal.warning(
                "Versement : godet plus léger que la tare de %.3f kg (tare prise avec des grains "
                "dedans ?) : dose comptée depuis la pesée d'avant",
                -reste,
            )
        dose = avant - reste
        self.doses[bocal] = dose
        journal.info("Versement : %.3f kg versés dans le bocal %s", dose, lisible(bocal))
        if self._noter_dose is not None:
            self._noter_dose(bocal, dose)
            return
        registre = self.griffe.registre
        if registre is not None:
            try:
                registre.noter_mesure("dose_bocal", round(dose, 4), "kg", capteur="pesee_griffe")
            except ErreurRegistre as erreur:
                journal.error("Versement : registre : %s", erreur)
