"""Bocal neuf de semence, du stockage au porte-bocal (tâche 19 quater ; fiche
`prehension/logiciel/bocal-neuf-pour-logiciel.md` du 07/11/2026, module Préhension gelé le 27/10).

    neuf = BocalNeuf(reglages.machine, prehension, stockage, registre=..., lire_qr=...)
    mycelium.brancher_bocal_neuf(neuf)          # l'étape « changer_de_bocal » du Mycélium le lance
    prehension.lancer(lambda: neuf.geste_nouveau_bocal("pleurote_grise"))     # ou à la main

Le geste appartient à la Préhension ; le Mycélium (porte-bocal, manivelle) ne fait que le lancer
quand la manivelle est en bas et attendre sa fin. Les 20 étapes de la fiche, en 6 phases :

    1. dévissage   (étapes 1 à 6)    QR lu et recopié au registre, tête à −270°, descente au M8,
                                     aimants, appui F_devis (80 N), rotation trigo par segments
                                     avec un essai de décollage (palier pesé) dès 120°
    2. capsule     (étape 7)         rangée dans la boîte des capsules (n + 1)
    3. couvercle   (étape 8)         un couvercle percé pris dans l'autre boîte (palier pesé :
                                     un seul)
    4. vissage     (étapes 9 à 11)   tête à +270°, rotation horaire jusqu'au calage du moteur,
                                     hauteur au calage, bocal soulevé de 5 mm : le palier pèse
                                     le bocal plein
    5. pose        (étapes 12 à 19)  bocal porté à face 1,10 jusqu'à (0,925 ; 0,40), méplats,
                                     couloir, pose au M8, mors à Ø 98, lâcher, remontée de 5 mm,
                                     serrage : c'est `Prehension.geste_poser_bocal` (déjà écrit),
                                     avec le palier à vide et le M8 qui retombe
    6. départ      (étape 20)        la tête repart en +y jusqu'à y 0,40 (hors de la zone du
                                     porte-bocal)

Le Pi recopie l'identité du bocal (QR de la capsule) dans le registre AVANT le dévissage : le QR
part avec la capsule. Un geste arrêté par une alarme reprend, après le Go, à sa phase (la phase est
gardée en mémoire du programme : une coupure du programme n'est pas reprise, voir la PR).

Rien de tout cela ne protège personne : l'appui, le M8, les pesées et le calage du moteur ne servent
qu'à la machine ; la sécurité est câblée.
"""

from collections.abc import Callable, Generator
from dataclasses import replace

from vidange.angles_gardes import AnglesGardes  # noqa: F401  (type de Prehension.garde)
from vidange.chef import ErreurEtape
from vidange.griffe.bras import G
from vidange.journal import donner_journal
from vidange.mycelium.mycelium import Bocal
from vidange.prehension.prehension import ROTATION, Attente, Prehension
from vidange.prehension.regles import Objet
from vidange.prehension.tete import Pas, Resultat
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import Machine
from vidange.stockage import places
from vidange.stockage.stockage import Stockage

journal = donner_journal("bocal_neuf")

Geste = Generator[Pas | Attente, Resultat | None, None]

# Les phases du geste, dans l'ordre.
RIEN = "rien"
CAPSULE_TENUE = "capsule_tenue"
CAPSULE_RANGEE = "capsule_rangee"
COUVERCLE_TENU = "couvercle_tenu"
BOCAL_TENU = "bocal_tenu"
BOCAL_POSE = "bocal_pose"
# Ce que la tête doit tenir au début de chaque phase.
TENU = {
    RIEN: None,
    CAPSULE_TENUE: "capsule",
    CAPSULE_RANGEE: None,
    COUVERCLE_TENU: "capsule",
    BOCAL_TENU: "bocal",
    BOCAL_POSE: None,
}
# Contenu d'une place de semence que le Pi ne reprend plus tant qu'on ne l'a pas regardée.
A_VERIFIER = "a_verifier"

QUOI_FAIRE = (
    "Regarder la vidéo de la préhension : le bocal, la capsule, le porte-bocal. Corriger, puis "
    "acquitter et donner le Go : le geste reprend là où il s'est arrêté."
)
QUOI_FAIRE_PLUS_DE_SEMENCE = (
    "Il n'y a plus de bocal de semence de cette variété au stockage : en poser un sur une place "
    "de semence, dire à l'écran sa variété, puis acquitter et donner le Go."
)
QUOI_FAIRE_QR = (
    "Le QR du bocal n'a pas pu être lu, ou il ne correspond pas à la variété de cette place : le "
    "bocal n'est pas pris et sa place est marquée « à vérifier ». Regarder le bocal (QR sale, "
    "décollé, mauvais bocal), le corriger ou le retirer, puis acquitter et donner le Go : un autre "
    "bocal est pris."
)
QUOI_FAIRE_SANS_BOCAL = (
    "Il n'y a pas de bocal sur cette place du stockage, ou il est trop bas : regarder la vidéo. "
    "Mettre le bocal, ou corriger l'inventaire à l'écran, puis acquitter et donner le Go."
)
QUOI_FAIRE_CAPSULE = (
    "La capsule du bocal n'a pas pu être dévissée (elle tient trop fort, le bocal tourne sur la "
    "tôle du stockage, le moteur cale, ou la poussée ne se tient pas) : la tête a reposé la "
    "capsule et s'est éloignée. Le bocal est resté à sa place, "
    "marqué « à vérifier » dans le registre et dans l'inventaire. L'ouvrir à la main ou le "
    "retirer, "
    "puis acquitter et donner le Go : un autre bocal est pris."
)
QUOI_FAIRE_BOITE_CAPSULES = (
    "La capsule ne touche pas la boîte à la hauteur prévue (compte de capsules faux, capsule de "
    "travers, boîte déplacée) : regarder la boîte à capsules, la vider ou la changer, corriger le "
    "nombre à l'écran, puis acquitter et donner le Go : la tête tient toujours la capsule."
)
QUOI_FAIRE_COUVERCLES = (
    "Le couvercle percé n'est pas pris comme prévu (boîte vide, deux couvercles collés, compte "
    "faux) : regarder la boîte des couvercles percés, la remplir et corriger le nombre à l'écran, "
    "puis acquitter et donner le Go."
)
QUOI_FAIRE_VISSAGE = (
    "Le couvercle percé n'est pas vissé comme prévu (filet sauté, couvercle de travers, bocal "
    "abîmé) : regarder la vidéo. Corriger à la main si besoin, puis acquitter et donner le Go."
)
QUOI_FAIRE_POIDS = (
    "Le bocal soulevé n'a pas le poids attendu : regarder le bocal (couvercle vissé, bocal plein "
    "de semence ?) et les masses de machine.yaml (bocal_neuf), puis acquitter et donner le Go."
)
QUOI_FAIRE_VIDE = (
    "Le porte-bocal n'est pas vide : un bocal vide y est encore. Sa reprise par la tête n'est pas "
    "encore écrite. Les mors sont ouverts : enlever le bocal vide à la main, puis acquitter et "
    "donner le Go."
)
QUOI_FAIRE_CODEUR = (
    "La tête ne lit pas l'erreur du codeur de sa rotation (source pas encore branchée) : sans "
    "elle, le dévissage et le vissage ne peuvent pas voir le calage du moteur. Rien n'a bougé. "
    "Voir la PR de la tâche 19 quater (question 1)."
)
QUOI_FAIRE_ORIGINE = (
    "L'origine de la rotation de la tête n'est pas faite (angle inconnu, coupure pendant une "
    "rotation) : refaire la prise d'origine de la tête, puis acquitter et donner le Go."
)


def _m(valeur: float) -> str:
    return f"{valeur:.3f}".rstrip("0").rstrip(".").replace(".", ",")


class BocalNeuf:
    def __init__(
        self,
        machine: Machine,
        prehension: Prehension,
        stockage: Stockage,
        registre: Registre | None = None,
        lire_qr: Callable[[str], str | None] | None = None,
        reprendre_le_vide: Callable[[], None] | None = None,
        photo: Callable[[str], object] = lambda raison: None,
    ) -> None:
        """`stockage` : places des bocaux de semence et des boîtes, inventaire (nombre de capsules
        et de couvercles percés). `registre` : l'identité du bocal y est recopiée.
        `lire_qr(place)` :
        le QR lu par la caméra de la tête de la griffe au-dessus de cette place, juste avant la
        prise (2ᵉ lecture), ou None s'il est illisible ; sans elle, pas de bocal neuf (case vide).
        `reprendre_le_vide()` : reprise du bocal vide resté dans le porte-bocal (fiche, § 4.5, pas
        écrite : case vide) ; sans elle, le geste ouvre les mors et demande de l'enlever à la main.
        `photo(raison)` : photo notée avec une alerte."""
        assert machine.bocal_neuf is not None and machine.stockage is not None
        assert machine.prehension is not None
        self.machine = machine
        self.reglages = machine.bocal_neuf
        self.prehension = prehension
        self.stockage = stockage
        self.registre = registre
        self._lire_qr = lire_qr
        self._reprendre_le_vide = reprendre_le_vide
        self._photo = photo
        self.pretes = prehension.tete.pretes
        # Cote du dessus de la capsule d'un bocal au stockage (z_capsule_stock, fiche § 2).
        self.z_capsule = machine.stockage.bocaux.capsule_haut_z
        vissage = machine.prehension.vissage
        # Montée (ou descente) de Z par degré de rotation : le filet de la capsule.
        self.pas_du_filet_m_par_deg = vissage.descente_m / vissage.angle_deg
        # Où en est le geste (gardé d'un lancement à l'autre : reprise après une alarme).
        self.phase = RIEN
        self.place: str | None = None
        self.variete: str | None = None
        self.code: str | None = None
        self._bocal: Bocal | None = None

    # ------------------------------------------------------------ pour le Mycélium

    def commencer(self, variete: str) -> None:
        """Lance le geste (l'étape « changer_de_bocal » du Mycélium)."""
        if self.prehension.occupee():
            raise ErreurEtape(
                "bocal neuf : la tête de préhension sert déjà à un autre geste", QUOI_FAIRE
            )
        self._bocal = None
        self.prehension.lancer(lambda: self.geste_nouveau_bocal(variete))

    def fini(self) -> bool:
        return self.prehension.geste_fini()

    def bocal(self) -> Bocal:
        if self._bocal is None:
            raise ErreurEtape("bocal neuf : aucun bocal n'a été posé", QUOI_FAIRE)
        return self._bocal

    def arreter(self) -> None:
        if self.prehension.occupee():
            self.prehension.arreter()

    # ------------------------------------------------------------ cotes et pesées

    @property
    def _boites(self):
        return self.reglages.boites

    def _centre_boite(self, nom: str) -> tuple[float, float]:
        return self.stockage.reglages.boites.places[nom]

    def _objet(self, nom: str, masse_kg: float) -> Objet:
        """Ce que la tête tient : capsule (ou couvercle percé) ou bocal, avec sa masse pesée."""
        reg = self.reglages.bocal
        objet = self.prehension.objet_par_nom(nom)
        objet = replace(
            objet,
            poids_n=masse_kg * G,
            tolerance_n=reg.tolerance_n(masse_kg),
            aimants=True,
        )
        if nom == "bocal":
            objet = replace(objet, dessous_m=reg.hauteur_m)
        return objet

    def _pesee(self) -> Generator[Pas, Resultat | None, float]:
        """Une pesée du palier : poids porté − poussée (N)."""
        pesee = yield Pas(
            "pesée du palier",
            attente_s=self.prehension.reglages.force.attente_pesee_s,
            pesee=True,
        )
        assert pesee is not None and pesee.force_n is not None
        return pesee.force_n

    def _origine_connue(self) -> bool:
        """L'angle cumulé de la rotation est connu (sinon l'origine n'est pas faite)."""
        garde = self.prehension.garde
        if garde is None:
            return True
        angle = garde.lire(ROTATION)
        return angle is not None and not angle.en_rotation

    # ------------------------------------------------------------ le geste

    def geste_nouveau_bocal(self, variete: str) -> Geste:
        """Les 6 phases ; relancé après une alarme, le geste reprend à sa phase."""
        if self.phase == RIEN:
            self._avant_de_commencer(variete)
        else:
            self._verifier_la_reprise(variete)
        if self.phase == RIEN:
            yield from self._ouvrir_les_mors_si_bocal_vide()
            yield from self._devisser()
        if self.phase == CAPSULE_TENUE:
            yield from self._ranger_la_capsule()
        if self.phase == CAPSULE_RANGEE:
            yield from self._prendre_un_couvercle()
        if self.phase == COUVERCLE_TENU:
            yield from self._visser()
        if self.phase == BOCAL_TENU:
            yield from self._poser()
        if self.phase == BOCAL_POSE:
            yield from self._s_en_aller()
        assert self.place is not None and self.code is not None
        self._bocal = Bocal(self.code, variete)
        self.phase = RIEN
        journal.info("Bocal neuf : %s (%s) posé sur le porte-bocal", self.code, variete)

    # ------------------------------------------------------------ conditions de départ

    def _avant_de_commencer(self, variete: str) -> None:
        """Les conditions de la fiche (§ 0), la place du bocal et son QR : rien ne bouge avant."""
        p = self.prehension
        if p.objet is not None:
            raise ErreurEtape(f"bocal neuf : la tête tient déjà un(e) {p.objet.sorte}", QUOI_FAIRE)
        if p.porte_bocal is None:
            raise ErreurEtape("bocal neuf : pas de porte-bocal", QUOI_FAIRE)
        if p.contexte().manivelle != "bas":
            raise ErreurEtape(
                "bocal neuf : la manivelle du mycélium n'est pas vue en bas, arrêtée (pose "
                "manivelle en bas)",
                QUOI_FAIRE,
            )
        peut = getattr(p.tete, "peut_detecter_le_calage", None)
        if peut is not None and not peut():
            raise ErreurEtape(
                "bocal neuf : l'erreur du codeur de la rotation de la tête n'est pas lue, le "
                "calage du moteur ne peut pas être vu : pas de mouvement",
                QUOI_FAIRE_CODEUR,
            )
        if not self._origine_connue():
            raise ErreurEtape(
                "bocal neuf : origine de la rotation de la tête pas faite (angle cumulé inconnu)",
                QUOI_FAIRE_ORIGINE,
            )
        inventaire = self.stockage.inventaire
        capsules, couvercles = self._boites.capsules, self._boites.couvercles_perces
        if inventaire.boites[capsules] >= places.capacite_boite(self.machine):
            raise ErreurEtape(
                f"bocal neuf : la boîte des capsules est pleine ({inventaire.boites[capsules]})",
                QUOI_FAIRE_BOITE_CAPSULES,
            )
        if inventaire.boites[couvercles] <= 0:
            raise ErreurEtape(
                "bocal neuf : la boîte des couvercles percés est vide", QUOI_FAIRE_COUVERCLES
            )
        self.place = self._choisir_la_place(variete)
        self.variete = variete
        self.code = self._lire_et_noter_le_qr(self.place, variete)

    def _choisir_la_place(self, variete: str) -> str:
        inventaire = self.stockage.inventaire
        for nom in places.places_semence(self.machine):
            if inventaire.bocaux.get(nom) == variete:
                return nom
        raise ErreurEtape(
            f"bocal neuf : plus de bocal de semence « {variete} » au stockage",
            QUOI_FAIRE_PLUS_DE_SEMENCE,
        )

    def _lire_et_noter_le_qr(self, place: str, variete: str) -> str:
        """2ᵉ lecture du QR, juste avant la prise (la 1ʳᵉ est au chargement) : illisible ou faux
        (variété) ⇒ le bocal n'est pas pris, la place est marquée. Sinon l'identité du bocal est
        recopiée au registre, car le QR part avec la capsule."""
        if self._lire_qr is None:
            raise ErreurEtape(
                "bocal neuf : pas de lecture du QR du bocal (caméra de la tête de la griffe)",
                QUOI_FAIRE_QR,
            )
        code = self._lire_qr(place)
        if not code:
            self._marquer_la_place(place, "QR illisible", None)
            raise ErreurEtape(f"bocal neuf : QR illisible sur la place {place}", QUOI_FAIRE_QR)
        if self.registre is not None:
            try:
                fiche = self.registre.trouver("bocal", code)
                connue = None if fiche is None else fiche.get("variete")
                if connue and connue != variete:
                    self._marquer_la_place(place, f"QR faux (variété {connue})", code)
                    raise ErreurEtape(
                        f"bocal neuf : le QR {code} est celui d'un bocal « {connue} », la place "
                        f"{place} devait avoir « {variete} »",
                        QUOI_FAIRE_QR,
                    )
                self.registre.objet("bocal", code, variete=variete)
            except ErreurRegistre as erreur:
                journal.error("Bocal neuf : registre : %s", erreur)
        journal.info("Bocal neuf : QR %s lu sur la place %s (%s)", code, place, variete)
        return code

    def _marquer_la_place(self, place: str, raison: str, code: str | None) -> None:
        """Le bocal n'est pas repris tant qu'on ne l'a pas regardé : sa place est marquée dans
        l'inventaire et, si on connaît son code, dans le registre."""
        self.stockage.inventaire.changer_bocal(place, A_VERIFIER)
        self._photo(f"bocal neuf : {raison}")
        if self.registre is None or code is None:
            return
        try:
            self.registre.objet("bocal", code, a_verifier=raison)
        except ErreurRegistre as erreur:
            journal.error("Bocal neuf : registre : %s", erreur)

    def _verifier_la_reprise(self, variete: str) -> None:
        """Relancé après une alarme : la tête doit tenir ce que la phase attend."""
        attendu = TENU[self.phase]
        tenu = self.prehension.objet
        if variete != self.variete or (tenu.sorte if tenu else None) != attendu:
            ancien = self.phase
            self.phase = RIEN
            raise ErreurEtape(
                f"bocal neuf : le geste en était à « {ancien} » "
                f"({'rien' if attendu is None else attendu} "
                f"tenu), mais la tête tient {'rien' if tenu is None else tenu.sorte} : il "
                "repart du début",
                QUOI_FAIRE,
            )
        journal.info("Bocal neuf : reprise à la phase « %s »", self.phase)

    def _ouvrir_les_mors_si_bocal_vide(self) -> Geste:
        """Le porte-bocal doit être vide. Un bocal vide y est encore : sa reprise n'est pas écrite
        (fiche, § 4.5) ; sans la case vide `reprendre_le_vide`, les mors s'ouvrent et on demande de
        l'enlever à la main."""
        porte_bocal = self.prehension.porte_bocal
        assert porte_bocal is not None
        if not porte_bocal.serre():
            return
        if self._reprendre_le_vide is not None:
            self._reprendre_le_vide()
            return
        yield from self.prehension._mors("ouverture des mors", porte_bocal.ouvrir_mors)
        raise ErreurEtape(
            "bocal neuf : le porte-bocal n'est pas vide (un bocal vide y est encore serré) ; sa "
            "reprise automatique n'est pas écrite",
            QUOI_FAIRE_VIDE,
        )

    # ------------------------------------------------------------ morceaux de gestes

    def _descendre_au_contact(
        self, cote: float, texte: str, vitesse: str, sous_m: float
    ) -> Generator[Pas, Resultat | None, tuple[float | None, bool]]:
        """Descente rapide jusqu'à `approche_m` au-dessus de la cote prévue du contact, puis lente
        (`vitesse`) jusqu'à `sous_m` sous elle. Rend (cote du contact, ou None s'il n'y en a pas ;
        vrai si le contact est venu pendant la descente rapide, donc plus haut que prévu)."""
        p = self.prehension
        tolerance = p.reglages.tolerance_m
        rapide = cote + self.reglages.approche_m
        assert p.pose is not None
        if p.pose.z > rapide + tolerance:
            resultat = yield Pas(f"descente rapide ({texte})", {"z": rapide}, palper=True)
            assert resultat is not None
            if resultat.contact:
                return resultat.pose.z, True
        resultat = yield Pas(
            f"approche lente ({texte})", {"z": cote - sous_m}, vitesse=vitesse, palper=True
        )
        assert resultat is not None
        return (resultat.pose.z if resultat.contact else None), False

    def _appuyer(self, texte: str) -> Geste:
        """Descente à 2 mm/s jusqu'à la poussée F_devis (80 N) du palier pesé."""
        p = self.prehension
        vissage = p.reglages.vissage
        assert p.pose is not None
        resultat = yield Pas(
            f"appui ({texte})",
            {"z": p.pose.z - vissage.course_appui_m},
            vitesse="bocal_appui",
            appui_arret_n=vissage.appui_n,
            appui_max_n=vissage.arret_n,
        )
        assert resultat is not None
        p.verifier_appui(resultat, texte, fin=False)

    def _relacher_la_poussee(self, cible_n: float, texte: str) -> Geste:
        """La poussée est relâchée par petits pas (Z monte de relache_pas_m, 2 mm/s) jusqu'à
        `cible_n` ; le palier pesé la lit. Pas relâchée en relache_pas_max pas : erreur."""
        p = self.prehension
        dev = self.reglages.devissage
        assert p.pose is not None
        for _ in range(dev.relache_pas_max):
            force = yield from self._pesee()
            if max(0.0, -force) <= cible_n:
                return
            yield Pas(
                f"relâcher la poussée ({texte})",
                {"z": p.pose.z + dev.relache_pas_m},
                vitesse="bocal_appui",
            )
        force = yield from self._pesee()
        if max(0.0, -force) > cible_n:
            raise ErreurEtape(
                f"bocal neuf, {texte} : la poussée ne descend pas à {cible_n:g} N après "
                f"{dev.relache_pas_max} pas de {dev.relache_pas_m * 1000:g} mm (lue : "
                f"{max(0.0, -force):.0f} N)",
                QUOI_FAIRE,
            )

    def _centrer(self, x: float, y: float, texte: str) -> None:
        p = self.prehension
        assert p.pose is not None
        ecart = max(abs(p.pose.x - x), abs(p.pose.y - y))
        if ecart > self._boites.centrage_m + 1e-9:
            raise ErreurEtape(
                f"bocal neuf, {texte} : axe de l'outil à ({_m(p.pose.x)} ; {_m(p.pose.y)}), il "
                f"faut ({_m(x)} ; {_m(y)}) à {self._boites.centrage_m * 1000:g} mm près",
                QUOI_FAIRE,
            )

    def _tourner_en_l_air(self, angle: float, texte: str) -> Geste:
        p = self.prehension
        assert p.pose is not None
        if abs(p.pose.a - angle) > p.reglages.tolerance_deg:
            yield Pas(f"tête à {angle:g}° ({texte})", {"a": angle})

    # ------------------------------------------------------------ 1. dévissage

    def _devisser(self) -> Geste:
        """Étapes 1 à 6."""
        p = self.prehension
        tete = p.tete
        dev = self.reglages.devissage
        bocal = self.reglages.bocal
        assert self.place is not None
        x, y = places.places_semence(self.machine)[self.place]
        tete.aimants(False)
        yield from p.aller(x, y)
        # En l'air, avant de descendre : 360° de dévissage trigo restent dans ± 500°.
        yield from self._tourner_en_l_air(dev.angle_depart_deg, "départ du dévissage")
        tete.tarer()
        z_contact, trop_haut = yield from self._descendre_au_contact(
            self.z_capsule, "capsule du bocal", "approche", dev.sans_bocal_m
        )
        if z_contact is None or trop_haut:
            yield from p.monter()
            if z_contact is None:
                self._photo("bocal neuf : pas de bocal")
                raise ErreurEtape(
                    f"bocal neuf : pas de contact jusqu'à "
                    f"{_m(self.z_capsule - dev.sans_bocal_m)} m sur la place {self.place} "
                    f"(capsule attendue à {_m(self.z_capsule)} m) : pas de bocal",
                    QUOI_FAIRE_SANS_BOCAL,
                )
            raise ErreurEtape(
                f"bocal neuf : contact à {_m(z_contact)} m sur la place {self.place}, plus haut "
                f"que prévu ({_m(self.z_capsule)} m + {_m(self.reglages.approche_m)} m) : bocal "
                "de travers ou autre chose sur la place",
                QUOI_FAIRE_SANS_BOCAL,
            )
        tete.aimants(True)
        try:
            yield from self._appuyer("dévisser la capsule")
            fait = 0.0
            prochain = dev.premier_essai_deg
            while True:
                tour = min(prochain, dev.rotation_max_deg) - fait
                assert p.pose is not None
                avant = p.pose.a
                resultat = yield Pas(
                    "dévissage de la capsule",
                    {
                        "a": p.pose.a + tour,
                        "z": p.pose.z + tour * self.pas_du_filet_m_par_deg,
                    },
                    vitesse="approche",
                    vissage=True,
                    appui_max_n=p.reglages.vissage.arret_n,
                    cale=True,
                )
                assert resultat is not None
                fait += resultat.pose.a - avant
                if resultat.arret == "cale":
                    raise _Echec(f"le moteur cale après {fait:.0f}° de dévissage")
                p.verifier_appui(resultat, "dévisser la capsule", fin=True)
                libre = yield from self._essai_de_decollage(fait)
                if libre:
                    break
                if fait >= dev.rotation_max_deg - 1e-6:
                    raise _Echec(f"la capsule tient encore après {fait:.0f}° de dévissage")
                prochain = fait + dev.pas_essai_deg
        except (_Echec, ErreurEtape) as echec:
            # Calage, capsule qui tient encore à 360°, poussée qui ne se tient pas : étape 5a.
            yield from self._abandonner_le_devissage(str(echec))
        # La capsule est libre, tenue par les aimants : elle part (3 cm lents, puis en haut).
        force = self._dernier_poids
        p.objet = self._objet("capsule", bocal.m_capsule_kg)
        p.poids_porte_n = force
        self.phase = CAPSULE_TENUE
        assert p.pose is not None
        yield Pas(
            "la capsule part",
            {"z": p.pose.z + self._boites.remontee_m},
            vitesse="bocal_levee",
        )
        yield from p.monter()

    _dernier_poids = 0.0
    # Dont la tête est montée pour l'essai de décollage (elle redescend avant de lâcher).
    _decolle_de = 0.0

    def _essai_de_decollage(self, fait: float) -> Generator[Pas, Resultat | None, bool]:
        """Étape 5 : la poussée est relâchée, Z monte de 3 mm à 2 mm/s, le palier pesé doit lire
        la capsule seule (vrai) ; s'il lit aussi le bocal, la capsule tient encore : Z redescend,
        l'appui revient (faux)."""
        p = self.prehension
        dev = self.reglages.devissage
        bocal = self.reglages.bocal
        assert p.pose is not None
        yield from self._relacher_la_poussee(dev.relache_n, "essai de décollage")
        yield Pas(
            "essai de décollage de la capsule",
            {"z": p.pose.z + dev.decollage_m},
            vitesse="bocal_appui",
        )
        self._decolle_de = dev.decollage_m
        force = yield from self._pesee()
        capsule = bocal.m_capsule_kg * G
        avec_bocal = (bocal.m_capsule_kg + bocal.m_bocal_plein_kg) * G
        journal.info(
            "Bocal neuf : décollage après %.0f° : palier %.2f N (capsule %.2f N, avec le bocal "
            "%.2f N)",
            fait,
            force,
            capsule,
            avec_bocal,
        )
        if abs(force - capsule) <= bocal.tolerance_n(bocal.m_capsule_kg):
            self._dernier_poids = force
            self._decolle_de = 0.0
            return True
        if abs(force - avec_bocal) <= bocal.tolerance_n(
            bocal.m_capsule_kg + bocal.m_bocal_plein_kg
        ):
            yield Pas(
                "la capsule tient : redescente",
                {"z": p.pose.z - dev.decollage_m},
                vitesse="bocal_appui",
            )
            self._decolle_de = 0.0
            yield from self._appuyer("dévisser la capsule (reprise)")
            return False
        raise _Echec(
            f"le palier pèse {force:.2f} N au décollage (capsule {capsule:.2f} N, avec le bocal "
            f"{avec_bocal:.2f} N)"
        )

    def _abandonner_le_devissage(self, raison: str) -> Geste:
        """Étape 5a : la capsule reste posée (aimants coupés), la tête remonte, alerte. Le bocal
        reste à sa place, marqué dans le registre et dans l'inventaire."""
        p = self.prehension
        tete = p.tete
        assert self.place is not None and self.code is not None
        if self._decolle_de > 0:
            assert p.pose is not None
            yield Pas(
                "redescente avant de lâcher la capsule",
                {"z": p.pose.z - self._decolle_de},
                vitesse="bocal_appui",
            )
            self._decolle_de = 0.0
        tete.aimants(False)
        yield Pas("capsule laissée sur le bocal", attente_s=self._boites.attente_lacher_s)
        yield from p.monter()
        self._marquer_la_place(self.place, "capsule pas dévissée", self.code)
        self.phase = RIEN
        raise ErreurEtape(
            f"bocal neuf : capsule pas dévissée sur la place {self.place} ({raison})",
            QUOI_FAIRE_CAPSULE,
        )

    # ------------------------------------------------------------ 2. capsule dans sa boîte

    def _ranger_la_capsule(self) -> Geste:
        """Étape 7 : l'axe de l'outil sur la boîte des capsules (± 3 mm), descente jusqu'au M8,
        aimants coupés, attente, remontée. Le Pi fait n + 1."""
        p = self.prehension
        boite = self._boites.capsules
        x, y = self._centre_boite(boite)
        stock = self.stockage.reglages.boites
        n = self.stockage.inventaire.boites[boite]
        attendu = places.hauteur_boite(self.machine, n) + stock.epaisseur_capsule_m
        yield from p.aller(x, y)
        self._centrer(x, y, "boîte des capsules")
        z, _ = yield from self._descendre_au_contact(
            attendu, "boîte des capsules", "approche", self._boites.fenetre_m
        )
        if z is None or abs(z - attendu) > self._boites.fenetre_m + 1e-9:
            lu = "pas de contact" if z is None else f"contact à {_m(z)} m"
            yield from p.monter()
            self._photo("bocal neuf : boîte des capsules")
            raise ErreurEtape(
                f"bocal neuf : boîte des capsules : {lu}, attendu à {_m(attendu)} m ± "
                f"{self._boites.fenetre_m * 1000:g} mm ({n} capsules dans la boîte)",
                QUOI_FAIRE_BOITE_CAPSULES,
            )
        p.tete.aimants(False)
        p.objet, p.poids_porte_n = None, 0.0
        yield Pas("capsule lâchée", attente_s=self._boites.attente_lacher_s)
        self.stockage.capsule_posee(boite)
        self.phase = CAPSULE_RANGEE
        assert p.pose is not None
        yield Pas(
            "remontée lente",
            {"z": p.pose.z + self._boites.remontee_m},
            vitesse="bocal_levee",
        )
        yield from p.monter()

    # ------------------------------------------------------------ 3. couvercle percé

    def _prendre_un_couvercle(self) -> Geste:
        """Étape 8 : l'axe sur la boîte des couvercles percés, contact au haut de la pile, aimants,
        remontée lente de 3 cm, palier pesé : un seul couvercle (deux collés : reposés et pris à
        nouveau ; rien : plus de couvercles)."""
        p = self.prehension
        tete = p.tete
        bocal = self.reglages.bocal
        boite = self._boites.couvercles_perces
        x, y = self._centre_boite(boite)
        inventaire = self.stockage.inventaire
        yield from p.aller(x, y)
        self._centrer(x, y, "boîte des couvercles percés")
        tete.tarer()
        un = bocal.m_couv_perce_kg * G
        tolerance = bocal.tolerance_n(bocal.m_couv_perce_kg)
        for essai in range(1, self._boites.prises_max + 1):
            n = inventaire.boites[boite]
            attendu = places.hauteur_boite(self.machine, n)
            z, _ = yield from self._descendre_au_contact(
                attendu, "boîte des couvercles percés", "approche", self._boites.fenetre_m
            )
            if z is None or abs(z - attendu) > self._boites.fenetre_m + 1e-9:
                lu = "pas de contact" if z is None else f"contact à {_m(z)} m"
                yield from p.monter()
                self._photo("bocal neuf : boîte des couvercles percés")
                raise ErreurEtape(
                    f"bocal neuf : boîte des couvercles percés : {lu}, attendu à {_m(attendu)} m "
                    f"± {self._boites.fenetre_m * 1000:g} mm ({n} couvercles dans la boîte)",
                    QUOI_FAIRE_COUVERCLES,
                )
            tete.aimants(True)
            yield Pas(
                "remontée lente du couvercle percé",
                {"z": z + self._boites.remontee_m},
                vitesse="bocal_levee",
            )
            force = yield from self._pesee()
            journal.info("Bocal neuf : couvercle percé pesé %.2f N (attendu %.2f N)", force, un)
            if abs(force - un) <= tolerance:
                inventaire.changer_boite(boite, max(0, n - 1))
                p.objet = self._objet("capsule", bocal.m_couv_perce_kg)
                p.poids_porte_n = force
                self.phase = COUVERCLE_TENU
                yield from p.monter()
                return
            if force < un - tolerance:
                tete.aimants(False)
                inventaire.changer_boite(boite, 0)
                yield from p.monter()
                raise ErreurEtape(
                    f"bocal neuf : plus de couvercles percés (le palier lit {force:.2f} N)",
                    QUOI_FAIRE_COUVERCLES,
                )
            raison = (
                f"deux couvercles percés collés ({force:.2f} N, un couvercle ≈ {un:.2f} N)"
                if force >= 2 * un - tolerance
                else f"couvercle percé pesé {force:.2f} N, attendu {un:.2f} ± {tolerance:.2f} N"
            )
            journal.warning("Bocal neuf : %s : reposé(s)", raison)
            # Les reposer sur la pile, puis refaire la prise.
            yield Pas("couvercles reposés", {"z": z}, vitesse="approche")
            tete.aimants(False)
            yield Pas("couvercles lâchés", attente_s=self._boites.attente_lacher_s)
            if essai >= self._boites.prises_max:
                yield from p.monter()
                raise ErreurEtape(
                    f"bocal neuf : {raison} ; reposé(s) {essai} fois", QUOI_FAIRE_COUVERCLES
                )
            assert p.pose is not None
            yield Pas(
                "remontée avant la nouvelle prise",
                {"z": z + self._boites.remontee_m},
                vitesse="bocal_levee",
            )

    # ------------------------------------------------------------ 4. vissage

    def _visser(self) -> Geste:
        """Étapes 9 à 11 : le couvercle percé est vissé sur le bocal jusqu'au calage du moteur,
        puis le bocal est soulevé de 5 mm et pesé."""
        p = self.prehension
        vis = self.reglages.vissage
        bocal = self.reglages.bocal
        assert self.place is not None
        x, y = places.places_semence(self.machine)[self.place]
        yield from p.aller(x, y)
        for essai in range(1, vis.essais_max + 1):
            yield from self._tourner_en_l_air(vis.angle_depart_deg, "départ du vissage")
            z_contact, _ = yield from self._descendre_au_contact(
                self.z_capsule, "col du bocal", "bocal_col", self.reglages.devissage.sans_bocal_m
            )
            if z_contact is None:
                yield from p.monter()
                raise ErreurEtape(
                    f"bocal neuf : pas de contact au col du bocal sur la place {self.place} "
                    f"(attendu à {_m(self.z_capsule)} m)",
                    QUOI_FAIRE_SANS_BOCAL,
                )
            yield from self._appuyer("visser le couvercle percé")
            assert p.pose is not None
            tour = vis.rotation_max_deg
            resultat = yield Pas(
                "vissage du couvercle percé",
                {
                    "a": p.pose.a - tour,
                    "z": p.pose.z - tour * self.pas_du_filet_m_par_deg,
                },
                vitesse="approche",
                vissage=True,
                appui_max_n=p.reglages.vissage.arret_n,
                cale=True,
            )
            assert resultat is not None
            if resultat.arret == "appui_max":
                p.verifier_appui(resultat, "visser le couvercle percé", fin=False)
            if resultat.arret == "cale":
                # La poussée doit être restée entre 60 et 100 N pendant le vissage.
                p.verifier_appui(resultat, "visser le couvercle percé", fin=True)
            if resultat.arret != "cale":
                yield from self._remettre_le_couvercle(tour)
                raise ErreurEtape(
                    f"bocal neuf : le moteur n'a pas calé après {tour:g}° de vissage : couvercle "
                    "percé pas vissé (filet sauté) ; il est remis dans sa boîte",
                    QUOI_FAIRE_VISSAGE,
                )
            ecart = resultat.pose.z - self.z_capsule
            if abs(ecart) > vis.hauteur_tolerance_m + 1e-9:
                raise ErreurEtape(
                    f"bocal neuf : face au calage à {_m(resultat.pose.z)} m, il faut "
                    f"{_m(self.z_capsule)} m ± {vis.hauteur_tolerance_m * 1000:g} mm (couvercle de "
                    "travers, ou bocal pas à la bonne hauteur)",
                    QUOI_FAIRE_VISSAGE,
                )
            yield from self._relacher_la_poussee(vis.appui_nul_n, "vissage")
            assert p.pose is not None
            yield Pas(
                "bocal soulevé de quelques mm",
                {"z": p.pose.z + vis.levee_m},
                vitesse="bocal_appui",
            )
            force = yield from self._pesee()
            plein = bocal.m_bocal_plein_kg * G
            couvercle = bocal.m_couv_perce_kg * G
            journal.info(
                "Bocal neuf : bocal soulevé, palier %.2f N (bocal plein %.2f N, couvercle %.2f N)",
                force,
                plein,
                couvercle,
            )
            if abs(force - plein) <= bocal.tolerance_n(bocal.m_bocal_plein_kg):
                p.objet = self._objet("bocal", bocal.m_bocal_plein_kg)
                p.poids_porte_n = force
                self.stockage.enlever_bocal(self.place)
                self.phase = BOCAL_TENU
                return
            if abs(force - couvercle) <= bocal.tolerance_n(bocal.m_couv_perce_kg):
                journal.warning(
                    "Bocal neuf : la tête ne porte que le couvercle (essai %d) : il n'est pas "
                    "vissé",
                    essai,
                )
                continue
            raise ErreurEtape(
                f"bocal neuf : le palier pèse {force:.2f} N avec le bocal soulevé (bocal plein "
                f"{plein:.2f} N ± {bocal.tolerance_n(bocal.m_bocal_plein_kg):.2f} N)",
                QUOI_FAIRE_POIDS,
            )
        yield from p.monter()
        raise ErreurEtape(
            f"bocal neuf : couvercle percé pas vissé après {vis.essais_max} essais",
            QUOI_FAIRE_VISSAGE,
        )

    def _remettre_le_couvercle(self, tour: float) -> Geste:
        """Filet sauté : la tête dévisse le couvercle (même angle en sens inverse), relâche
        l'appui et le remet dans sa boîte ; la phase repart du couvercle à prendre."""
        p = self.prehension
        assert p.pose is not None
        yield Pas(
            "couvercle percé dévissé",
            {"a": p.pose.a + tour, "z": p.pose.z + tour * self.pas_du_filet_m_par_deg},
            vitesse="approche",
            vissage=True,
            appui_max_n=p.reglages.vissage.arret_n,
        )
        yield from p.monter()
        boite = self._boites.couvercles_perces
        x, y = self._centre_boite(boite)
        n = self.stockage.inventaire.boites[boite]
        attendu = (
            places.hauteur_boite(self.machine, n)
            + self.stockage.reglages.boites.epaisseur_capsule_m
        )
        yield from p.aller(x, y)
        self._centrer(x, y, "boîte des couvercles percés")
        z, _ = yield from self._descendre_au_contact(
            attendu, "couvercle remis en boîte", "approche", self._boites.fenetre_m
        )
        p.tete.aimants(False)
        p.objet, p.poids_porte_n = None, 0.0
        yield Pas("couvercle percé lâché", attente_s=self._boites.attente_lacher_s)
        if z is not None:
            self.stockage.inventaire.changer_boite(boite, n + 1)
        self.phase = CAPSULE_RANGEE
        yield from p.monter()

    # ------------------------------------------------------------ 5. pose sur le porte-bocal

    def _poser(self) -> Geste:
        """Étapes 12 à 19 : le bocal monte (3 cm lents, puis en haut), le palier pesé est surveillé
        pendant tout le trajet (une chute de la charge est vue comme un choc : arrêt et alerte),
        puis la pose du porte-bocal (`geste_poser_bocal`)."""
        p = self.prehension
        assert p.pose is not None
        yield Pas(
            "le bocal part",
            {"z": p.pose.z + self._boites.remontee_m},
            vitesse="bocal_levee",
            choc=True,
        )
        yield from p.geste_poser_bocal(palier_vide_n=self.reglages.palier_vide_n, m8_retombe=True)
        self.phase = BOCAL_POSE

    # ------------------------------------------------------------ 6. la tête s'en va

    def _s_en_aller(self) -> Geste:
        """Étape 20 : retour en +y à face 1,10 jusqu'au départ du couloir (y 0,40), hors de la zone
        du porte-bocal. La manivelle ne remonte pas tant que la tête est dans la zone."""
        p = self.prehension
        couloir = p.reglages.porte_bocal.couloir
        assert couloir is not None
        yield from p.aller(p.reglages.porte_bocal.x, couloir.depart[1])


class _Echec(Exception):
    """Le dévissage a échoué (5a) : la capsule est reposée, l'alerte part."""
