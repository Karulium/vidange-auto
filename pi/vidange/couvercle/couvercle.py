"""Pose du couvercle sur le seau plein (tâche 41 bis ; fiche pose-couvercle-pour-logiciel.md du
07/11/2026, module Préhension gelé le 27/10).

    couvercle = Couvercle(reglages.machine, stockage=stockage, photo=...)
    prehension.lancer(lambda: couvercle.geste_prendre(prehension, "seau_a"))   # étapes 1 à 6
    prehension.lancer(lambda: couvercle.geste_poser(prehension, "seau_a"))     # étapes 7 à 14
    remplissage.geste_controler_couvercle(...)                                  # étape 13 (balance)

Le chariot de remplissage (Remplissage.geste_preparer_couvercle) est arrêté à y 0,50, plateau à
H_app, barres ouvertes, et note le poids P0 AVANT les gestes ci-dessus. La Préhension prend un
couvercle à la pile du stockage (ventouse seule, électroaimants coupés, contact M8, vide −55 kPa,
contrôle « un seul couvercle » au palier pesé), le porte au-dessus du seau, descend lentement
jusqu'au contact (sans appuyer : c'est la fermeture qui clipse), souffle, se dégage lentement et
remonte. Le vide, le M8 et les pesées ne protègent jamais personne : la sécurité est câblée.

Ce que le Pi garde : le haut de la pile (face au contact de la dernière prise ; sans mémoire,
`couvercle → pile → haut_sans_memoire_z`) et, avec le Stockage, le nombre de couvercles
(`inventaire.couvercles`). Le Pi n'impose pas ce nombre : c'est le contact M8 qui dit « pile vide ».

Alertes (étapes de la fiche) : plus de couvercles (3), vide non atteint (4), deux couvercles collés
(6), couvercle lâché en route (7), couvercle mal posé (10a), pas de contact à la pose (10b),
couvercle resté collé à la ventouse (11, 12), palier pas revenu à vide (13).
"""

from collections.abc import Callable, Generator
from dataclasses import replace

from vidange.chef import ErreurEtape
from vidange.griffe.bras import G
from vidange.journal import donner_journal
from vidange.prehension.prehension import Attente, Prehension
from vidange.prehension.regles import Objet, Pose
from vidange.prehension.tete import Pas, Resultat
from vidange.reglages import Machine
from vidange.stockage import places
from vidange.stockage.stockage import Stockage

journal = donner_journal("couvercle")

Geste = Generator[Pas | Attente, Resultat | None, None]

QUOI_FAIRE_PILE_VIDE = (
    "Il n'y a plus de couvercle sur la pile du stockage : en poser une pile, dire à l'écran "
    "combien, puis acquitter et donner le Go. Le seau plein reste sur le plateau."
)
QUOI_FAIRE_VIDE = (
    "La ventouse ne prend pas le couvercle (vide non atteint) : regarder la ventouse (sale ou "
    "abîmée), le couvercle (fendu ou abîmé) et l'air (compresseur sous tension, vanne d'isolement "
    "ouverte). Puis acquitter et donner le Go : la prise est refaite."
)
QUOI_FAIRE_DOUBLE = (
    "Deux couvercles sont restés collés ensemble (ou le poids n'est pas celui d'un couvercle) : "
    "regarder la pile, séparer les couvercles à la main si besoin, puis acquitter et donner le "
    "Go : la prise est refaite."
)
QUOI_FAIRE_PERDU = (
    "Le couvercle s'est décroché en route : regarder la photo, ramasser le couvercle s'il est "
    "tombé, puis acquitter et donner le Go. La tête ne le tient plus : le geste de prise est à "
    "refaire."
)
QUOI_FAIRE_MAL_POSE = (
    "Le couvercle est mal posé (de travers ou posé sur l'anse) : vérifier l'anse du seau (elle "
    "doit être rabattue vers le bas, côté y+), regarder la vidéo. La tête a remonté avec le "
    "couvercle. Corriger, puis acquitter et donner le Go : la pose est refaite."
)
QUOI_FAIRE_SANS_SEAU = (
    "Pas de contact à la pose : il n'y a pas de seau sous la tête, ou le couvercle est tombé. "
    "Regarder la vidéo et le plateau, puis acquitter et donner le Go : la pose est refaite."
)
QUOI_FAIRE_COLLE = (
    "Le couvercle est resté collé à la ventouse : regarder la ventouse, le tuyau de vide et la "
    "vanne « souffler », détacher le couvercle à la main SANS toucher à la tête, puis acquitter "
    "et donner le Go."
)
QUOI_FAIRE_PALIER = (
    "Le palier pesé de la tête ne revient pas à vide après la pose : regarder la ventouse (un "
    "couvercle est peut-être resté dessus). Corriger, puis acquitter et donner le Go."
)


def _m(valeur: float) -> str:
    return f"{valeur:.3f}".rstrip("0").rstrip(".").replace(".", ",")


class Couvercle:
    def __init__(
        self,
        machine: Machine,
        stockage: Stockage | None = None,
        photo: Callable[[str], object] = lambda raison: None,
    ) -> None:
        """`stockage` : son inventaire compte les couvercles (None : pas de compte).
        `photo(raison)` : photo notée avec une alerte."""
        assert machine.couvercle is not None and machine.stockage is not None
        assert machine.prehension is not None and machine.griffe is not None
        self.machine = machine
        self.reglages = machine.couvercle
        self.prehension = machine.prehension
        self.formats = machine.griffe.formats
        self.stockage = stockage
        self._photo = photo
        self.pile_x, self.pile_y = machine.stockage.piles.couvercles
        # Face de la ventouse au contact de la dernière prise (None : pas de mémoire).
        self.haut_pile_z: float | None = None
        self.fond_pile_z = machine.stockage.plateau_z

    # ------------------------------------------------------------ cotes

    def z_pose(self, format: str) -> float:
        self._exiger_format(format)
        return self.machine.z_pose_couvercle(format)

    def plateau_z(self, format: str) -> float:
        """Le plateau du chariot pendant la pose : H_app du format (comme la fermeture)."""
        assert self.machine.fermeture is not None
        self._exiger_format(format)
        bas = self.machine.axes["plateau_z"].course[0]
        return self.machine.fermeture.h_approche(format, bas)

    def chariot_y(self) -> float:
        assert self.machine.fermeture is not None
        return self.machine.fermeture.chariot_y

    def masse_kg(self, format: str) -> float:
        self._exiger_format(format)
        return self.reglages.formats[format].masse_kg

    def tolerance_kg(self, format: str) -> float:
        self._exiger_format(format)
        return self.reglages.tolerance_kg(format)

    def _exiger_format(self, format: str) -> None:
        if format not in self.reglages.formats:
            raise ErreurEtape(f"couvercle : format de seau inconnu « {format} »")

    def objet(self, prehension: Prehension, format: str) -> Objet:
        """Le couvercle tenu : rayon (Ø du couvercle du format), poids et tolérance attendus. Pris
        hors d'axe : son axe est à `decalage_y_m` de celui de l'outil."""
        self._exiger_format(format)
        base = prehension.objet_par_nom("couvercle")
        diametre = self.formats[format].diametre_couvercle
        assert diametre is not None
        tete_y = places.prise_y(self.machine, self.pile_y)
        return replace(
            base,
            rayon_m=diametre / 2,
            poids_n=self.masse_kg(format) * G,
            tolerance_n=self.tolerance_kg(format) * G,
            decalage_y_m=self.pile_y - tete_y,
        )

    def _vitesse_ok(self, prehension: Prehension) -> None:
        v = prehension.reglages.vitesses
        if v.couvercle_pile is None or v.couvercle_pose is None:
            raise ErreurEtape("couvercle : vitesses couvercle_pile et couvercle_pose absentes")

    # ------------------------------------------------------------ prendre (étapes 1 à 6)

    def geste_prendre(self, prehension: Prehension, format: str) -> Geste:
        """Étapes 1 à 6 de la fiche : au-dessus de la pile (outil en y 0,83), descente rapide
        puis lente jusqu'au contact M8, prise par le vide, décollage lent, un seul couvercle."""
        self._vitesse_ok(prehension)
        if prehension.objet is not None:
            raise ErreurEtape(f"préhension : la tête tient déjà un(e) {prehension.objet.sorte}")
        objet = self.objet(prehension, format)
        reg = self.reglages
        tete = prehension.tete
        vide = prehension.reglages.vide
        tete_y = places.prise_y(self.machine, self.pile_y)
        # 1) au-dessus de la pile, électroaimants coupés, rotation laissée où elle est.
        tete.aimants(False)
        yield from prehension.aller(self.pile_x, tete_y)
        tete.tarer()
        essais_vide, essais_poids = 0, 0
        while True:
            z_contact = yield from self._descendre_a_la_pile(prehension)
            # 4) prise par le vide.
            if not (yield from self._aspirer(prehension)):
                essais_vide += 1
                if essais_vide >= reg.vide.essais_max:
                    yield from prehension.monter()
                    raise ErreurEtape(
                        f"préhension : vide de {vide.prise_kpa:g} kPa pas atteint au couvercle "
                        f"après {essais_vide} essais (air ou couvercle abîmé)",
                        QUOI_FAIRE_VIDE,
                    )
                journal.warning("Couvercle : vide non atteint, nouvel essai")
                yield Pas(
                    "remonter avant le nouvel essai",
                    {"z": z_contact + reg.vide.remontee_reessai_m},
                    vitesse="couvercle_pile",
                )
                continue
            prehension.vide_prise_kpa = tete.vide_kpa()
            journal.info("Couvercle : pris, vide %.1f kPa", prehension.vide_prise_kpa or 0.0)
            # Dès que la ventouse tient, la tête tient le couvercle (règles de l'objet tenu).
            prehension.objet = objet
            # 5) décollage lent sur les premiers cm.
            resultat = yield Pas(
                "décollage lent du couvercle",
                {"z": z_contact + reg.pile.decollage_m},
                vitesse="couvercle_pile",
                vide_perte_kpa=vide.perte_kpa,
            )
            assert resultat is not None
            if resultat.arret == "vide":
                self._perdu(prehension)
            # 6) un seul couvercle : le palier pesé lit la masse d'un couvercle.
            resultat = yield Pas(
                "pesée du couvercle",
                attente_s=prehension.reglages.force.attente_pesee_s,
                pesee=True,
            )
            assert resultat is not None and resultat.force_n is not None
            poids = resultat.force_n
            attendu, tolerance = objet.poids_n or 0.0, objet.tolerance_n
            journal.info(
                "Couvercle : pesé %.2f N (attendu %.2f ± %.2f N)", poids, attendu, tolerance
            )
            if abs(poids - attendu) <= tolerance:
                prehension.poids_porte_n = poids
                break
            double = poids >= 2 * attendu - tolerance
            raison = (
                f"deux couvercles collés ({poids:.2f} N, un couvercle ≈ {attendu:.2f} N)"
                if double
                else f"couvercle pesé {poids:.2f} N, attendu {attendu:.2f} ± {tolerance:.2f} N"
            )
            journal.warning("Couvercle : %s : reposé", raison)
            prehension.poids_porte_n = poids
            # Les reposer sur la pile (contact M8), souffler, puis refaire la prise (une fois).
            yield from prehension.descendre(z_contact, "reposer le(s) couvercle(s)")
            prehension.objet, prehension.poids_porte_n = None, 0.0
            yield from prehension.souffler()
            essais_poids += 1
            if essais_poids >= 2:
                yield from prehension.monter()
                raise ErreurEtape(f"préhension : {raison} ; reposé(s) deux fois", QUOI_FAIRE_DOUBLE)
            yield Pas(
                "remonter avant la nouvelle prise",
                {"z": z_contact + reg.vide.remontee_reessai_m},
                vitesse="couvercle_pile",
            )
        self.haut_pile_z = z_contact
        if self.stockage is not None:
            inventaire = self.stockage.inventaire
            inventaire.changer_couvercles(max(0, inventaire.couvercles - 1))

    def _descendre_a_la_pile(
        self, prehension: Prehension
    ) -> Generator[Pas, Resultat | None, float]:
        """Étapes 2 et 3 : descente rapide jusqu'à 3 cm au-dessus du haut prévu, puis lente
        jusqu'au contact. Rend la face au contact (le nouveau haut de la pile). Pas de contact
        avant fond + épaisseur du dernier couvercle : pile vide."""
        reg = self.reglages
        assert prehension.pose is not None
        haut = self.haut_pile_z if self.haut_pile_z is not None else reg.pile.haut_sans_memoire_z
        rapide = haut + reg.pile.approche_m
        tolerance = prehension.reglages.tolerance_m
        if prehension.pose.z > rapide + tolerance:
            resultat = yield Pas(
                "descente rapide vers la pile des couvercles", {"z": rapide}, palper=True
            )
            assert resultat is not None
            if resultat.contact:
                # La pile est plus haute que prévu : le contact est déjà là.
                journal.info(
                    "Couvercle : contact de la pile à %.4f m (prévu plus bas)", resultat.pose.z
                )
                return resultat.pose.z
        bas = self.fond_pile_z + reg.pile.epaisseur_dernier_m - tolerance
        resultat = yield Pas(
            "approche lente de la pile des couvercles",
            {"z": bas},
            vitesse="couvercle_pile",
            palper=True,
        )
        assert resultat is not None
        if not resultat.contact:
            self.haut_pile_z = None
            if self.stockage is not None:
                self.stockage.inventaire.changer_couvercles(0)
            self._photo("plus de couvercles")
            yield from prehension.monter()
            raise ErreurEtape(
                f"couvercle : plus de couvercles, pas de contact jusqu'à {_m(bas)} m (fond de la "
                f"pile {_m(self.fond_pile_z)} m + {_m(reg.pile.epaisseur_dernier_m)} m)",
                QUOI_FAIRE_PILE_VIDE,
            )
        journal.info("Couvercle : contact de la pile à %.4f m", resultat.pose.z)
        return resultat.pose.z

    def _aspirer(self, prehension: Prehension) -> Generator[Pas | Attente, Resultat | None, bool]:
        """Étape 4 : « aspirer » par impulsions (≈ 1 s) jusqu'à −55 kPa ; pas atteint en
        `impulsions_max` impulsions : « souffler » et rendre faux (la prise est refaite). Entre
        deux impulsions, « aspirer » est fermée (le clapet anti-retour garde le vide)."""
        reg = self.reglages.vide
        tete = prehension.tete
        vide = prehension.reglages.vide

        def atteint() -> bool:
            valeur = tete.vide_kpa()
            return valeur is not None and valeur <= vide.prise_kpa

        for impulsion in range(1, reg.impulsions_max + 1):
            tete.vanne(True)
            resultat = yield Attente(
                "vide de la prise du couvercle",
                atteint,
                reg.impulsion_s,
                f"vide de {vide.prise_kpa:g} kPa pas atteint",
                QUOI_FAIRE_VIDE,
                sans_alarme=True,
            )
            assert resultat is not None
            if not resultat.delai_depasse:
                return True
            if impulsion < reg.impulsions_max:
                tete.vanne(False)
                yield Pas("pause entre deux impulsions", attente_s=vide.relache_s)
        yield from prehension.souffler()
        return False

    def _perdu(self, prehension: Prehension) -> None:
        """Vide perdu en tenant le couvercle (au-dessus de −40 kPa) : la tête s'est arrêtée sur
        place ; le couvercle n'est plus tenu. Photo et alerte."""
        perte = prehension.reglages.vide.perte_kpa
        prehension.objet, prehension.poids_porte_n = None, 0.0
        prehension.tete.vanne(False)
        self._photo("couvercle lâché en route")
        raise ErreurEtape(
            f"couvercle lâché en route : vide au-dessus de {perte:g} kPa, arrêt sur place",
            QUOI_FAIRE_PERDU,
        )

    # ------------------------------------------------------------ poser (étapes 7 à 14)

    def _dans_le_chemin_decale(self, prehension: Prehension, format: str, pose: Pose) -> bool:
        """Format C, couvercle tenu : la tête est-elle dans le chemin de la descente décalée (outil
        au-dessus du seau, entre l'y de la pose et celui du décalage, sous la face du début) ?"""
        decalee = self.reglages.formats[format].descente_decalee
        if decalee is None or prehension.objet is None or prehension.objet.sorte != "couvercle":
            return False
        tolerance = prehension.reglages.tolerance_m
        cible = self.reglages.pose
        bas_y, haut_y = sorted((cible.y, decalee.y))
        return (
            pose.z < decalee.debut_z - 1e-6
            and abs(pose.x - cible.x) <= tolerance
            and bas_y - tolerance <= pose.y <= haut_y + tolerance
        )

    def _remontee_droite_max_z(
        self, prehension: Prehension, format: str, pose: Pose
    ) -> float | None:
        """Pour une remontée après un choc, couvercle C tenu : pas au-dessus de la face du
        recentrage tant que l'outil n'est pas revenu à l'y du décalage (§ 5.1)."""
        decalee = self.reglages.formats[format].descente_decalee
        if decalee is None or not self._dans_le_chemin_decale(prehension, format, pose):
            return None
        if abs(pose.y - decalee.y) <= prehension.reglages.tolerance_m:
            return None
        return max(decalee.recentrage_z, pose.z)

    def _transport(
        self, prehension: Prehension, x: float, y: float, format: str | None = None
    ) -> Geste:
        """Étapes 7 et 8 : Z à vitesse normale, puis X et Y aux vitesses du Portique, le vide
        surveillé pendant tout le trajet (arrêt sur place au-dessus de −40 kPa). Pose refaite
        (après une alarme ou une coupure) avec le couvercle C encore tenu dans le chemin décalé :
        d'abord ce chemin à l'envers (§ 5.1), jamais la remontée droite."""
        perte = prehension.reglages.vide.perte_kpa
        regles = prehension.regles
        tete = prehension.tete
        assert prehension.pose is not None
        if tete.choc:
            tete.oublier_choc()
        if format is not None and self._dans_le_chemin_decale(prehension, format, prehension.pose):
            yield from self._monter_avec_vide(prehension, format)
            assert prehension.pose is not None
        haut = regles.hauteur_trajet(prehension.objet, prehension.pose.y)
        if prehension.pose.z < haut - 1e-6:
            resultat = yield Pas(
                "monter avec le couvercle", {"z": haut}, choc=True, vide_perte_kpa=perte
            )
            assert resultat is not None
            if resultat.arret == "vide":
                self._perdu(prehension)
        assert prehension.pose is not None
        haut = regles.hauteur_trajet(prehension.objet, prehension.pose.y, y)
        if prehension.pose.z > haut + 1e-6:
            resultat = yield Pas(
                "descendre à la hauteur du trajet", {"z": haut}, vide_perte_kpa=perte
            )
            assert resultat is not None
            if resultat.arret == "vide":
                self._perdu(prehension)
        resultat = yield Pas(
            "trajet du couvercle", {"x": x, "y": y}, choc=True, vide_perte_kpa=perte
        )
        assert resultat is not None
        if resultat.arret == "vide":
            self._perdu(prehension)

    def geste_poser(self, prehension: Prehension, format: str) -> Geste:
        """Étapes 7 à 14 de la fiche : transport au-dessus du seau (outil en (0,925 ; 0,49)),
        descente rapide puis à 10 mm/s jusqu'au contact M8 (sans appuyer), souffler, dégagement
        lent, palier à vide, remontée. Le chariot est déjà arrêté à y 0,50, plateau à H_app."""
        self._vitesse_ok(prehension)
        objet = prehension.objet
        if objet is None or objet.sorte != "couvercle":
            raise ErreurEtape("préhension : la tête ne tient pas de couvercle à poser")
        reg = self.reglages
        pose = reg.pose
        perte = prehension.reglages.vide.perte_kpa
        zp = self.z_pose(format)
        # Format C (§ 5.1) : l'outil arrive décalé vers l'allée, descend ainsi jusqu'à la face de
        # recentrage, revient à l'y de la pose à face constante, puis descend comme les autres.
        decalee = reg.formats[format].descente_decalee
        # Toute remontée avant le lâcher (choc compris) garde le chemin décalé du couvercle C.
        prehension.remontee_droite_max_z = lambda tete: self._remontee_droite_max_z(
            prehension, format, tete
        )
        yield from self._transport(
            prehension, pose.x, pose.y if decalee is None else decalee.y, format
        )
        # 9) descente rapide jusqu'à Z_pose + 0,040, 10) lente.
        etapes: list[tuple[str, float, str | None]] = []
        rapide = zp + pose.rapide_m
        if decalee is not None:
            etapes.append(
                ("descente décalée vers l'allée (couvercle C)", decalee.recentrage_z, None)
            )
        etapes.append(("descente rapide vers le seau", rapide, None))
        etapes.append(("approche lente du seau", zp - pose.sans_contact_m, "couvercle_pose"))
        z_contact: float | None = None
        for numero, (texte, z, vitesse) in enumerate(etapes):
            assert prehension.pose is not None
            if prehension.pose.z > z + 1e-6:
                resultat = yield Pas(
                    texte, {"z": z}, vitesse=vitesse, palper=True, vide_perte_kpa=perte
                )
                assert resultat is not None
                if resultat.arret == "vide":
                    self._perdu(prehension)
                if resultat.contact:
                    z_contact = resultat.pose.z
                    break
            if decalee is not None and numero == 0:
                yield from self._vers_y(prehension, pose.y, decalee.vitesse_m_s, "recentrer")
        if z_contact is None:
            # 10b) pas de contact à Z_pose − 0,015 : pas de seau, ou couvercle tombé.
            yield from self._monter_avec_vide(prehension, format)
            self._photo("couvercle : pas de contact à la pose")
            raise ErreurEtape(
                f"couvercle : pas de contact jusqu'à {_m(zp - pose.sans_contact_m)} m (attendu à "
                f"{_m(zp)} m) : pas de seau ou couvercle tombé",
                QUOI_FAIRE_SANS_SEAU,
            )
        ecart = z_contact - zp
        journal.info("Couvercle : contact à la pose à %.4f m (attendu %.4f m)", z_contact, zp)
        if ecart > pose.fenetre_m + 1e-9:
            # 10a) contact trop tôt : couvercle de travers ou posé sur l'anse. La tête remonte
            # AVEC le couvercle (vide gardé).
            yield from self._monter_avec_vide(prehension, format)
            self._photo("couvercle mal posé")
            raise ErreurEtape(
                f"couvercle mal posé : contact à {_m(z_contact)} m, attendu à {_m(zp)} m "
                f"(au plus {pose.fenetre_m * 1000:g} mm plus haut) : vérifier l'anse du seau",
                QUOI_FAIRE_MAL_POSE,
            )
        if ecart < -pose.fenetre_m - 1e-9:
            journal.warning(
                "Couvercle : contact %.1f mm plus bas que Z_pose (fenêtre ± %g mm) : posé",
                -ecart * 1000,
                pose.fenetre_m * 1000,
            )
        # 11) lâcher : électroaimants coupés, souffler un court instant.
        yield from self._lacher(prehension)
        # 12) dégagement lent ; le M8 doit retomber dans les premiers mm.
        yield from self._degager(prehension, z_contact)
        # 13) le palier pesé revient à vide.
        resultat = yield Pas(
            "pesée du palier à vide",
            attente_s=prehension.reglages.force.attente_pesee_s,
            pesee=True,
        )
        assert resultat is not None and resultat.force_n is not None
        if abs(resultat.force_n) > reg.palier_vide_n:
            raise ErreurEtape(
                f"couvercle : le palier pesé lit {resultat.force_n:.2f} N après la pose "
                f"(à vide ± {reg.palier_vide_n:g} N)",
                QUOI_FAIRE_PALIER,
            )
        # 14) la tête remonte et part (la fermeture peut commencer).
        yield from prehension.monter()

    def _vers_y(self, prehension: Prehension, y: float, vitesse: float, quoi: str) -> Geste:
        """Format C : l'outil va à y, face constante, à `vitesse` (m/s), le vide surveillé."""
        assert prehension.pose is not None
        ecart = abs(y - prehension.pose.y)
        if ecart <= 1e-6:
            return
        resultat = yield Pas(
            f"{quoi} le couvercle C à y {_m(y)}, face constante",
            {"y": y},
            vide_perte_kpa=prehension.reglages.vide.perte_kpa,
            duree_s=ecart / vitesse,
        )
        assert resultat is not None
        if resultat.arret == "vide":
            self._perdu(prehension)

    def _monter_avec_vide(self, prehension: Prehension, format: str) -> Geste:
        """La tête remonte avec le couvercle (erreurs 10a et 10b, pose refaite après un arrêt).
        Format C, sous la face du début de la descente décalée : le même chemin à l'envers (fiche
        de la pose, § 5.1, fil Préhension du 07/11/2026) : montée droite à 10 mm/s jusqu'à la face
        du recentrage, décalage à l'y du décalage à face constante, puis montée en haut (la
        remontée droite repasserait à 2,3 mm de la plaque du micropore)."""
        perte = prehension.reglages.vide.perte_kpa
        decalee = self.reglages.formats[format].descente_decalee
        assert prehension.pose is not None
        if decalee is not None and prehension.pose.z < decalee.debut_z - 1e-6:
            ecart = decalee.recentrage_z - prehension.pose.z
            if ecart > 1e-6:
                resultat = yield Pas(
                    "remonter avec le couvercle jusqu'au recentrage",
                    {"z": decalee.recentrage_z},
                    vide_perte_kpa=perte,
                    duree_s=ecart / decalee.vitesse_m_s,
                )
                assert resultat is not None
                if resultat.arret == "vide":
                    self._perdu(prehension)
            yield from self._vers_y(prehension, decalee.y, decalee.vitesse_m_s, "décaler")
        haut = prehension.regles.hauteur_trajet(prehension.objet, prehension.pose.y)
        resultat = yield Pas("remonter avec le couvercle", {"z": haut}, vide_perte_kpa=perte)
        assert resultat is not None
        if resultat.arret == "vide":
            self._perdu(prehension)

    def _lacher(self, prehension: Prehension) -> Geste:
        """Étape 11 : électroaimants coupés, puis le lâcher de la Préhension (souffler, vide
        revenu au-dessus de −5 kPa, un nouveau souffle, puis alerte ; tâche 45 undecies)."""
        prehension.tete.aimants(False)
        yield from prehension.lacher_ventouse("couvercle", QUOI_FAIRE_COLLE)
        journal.info("Couvercle : lâché")
        prehension.objet, prehension.poids_porte_n = None, 0.0
        # Après le lâcher, la tête seule remonte tout droit (§ 5.1).
        prehension.remontee_droite_max_z = lambda tete: None

    def _degager(self, prehension: Prehension, z_contact: float) -> Geste:
        pose = self.reglages.pose
        tete = prehension.tete
        yield Pas(
            "dégagement lent",
            {"z": z_contact + pose.m8_retombe_m},
            vitesse="couvercle_pile",
        )
        if tete.contact_tete():
            # Resté collé à la ventouse : nouveau souffle, puis alerte s'il est encore là.
            journal.warning("Couvercle : le M8 ne retombe pas, nouveau souffle")
            yield from prehension.souffler("nouveau souffle")
            if tete.contact_tete():
                raise ErreurEtape(
                    f"couvercle : le M8 voit encore le couvercle {pose.m8_retombe_m * 1000:g} mm "
                    "au-dessus du contact : resté collé à la ventouse",
                    QUOI_FAIRE_COLLE,
                )
        yield Pas(
            "dégagement lent (suite)",
            {"z": z_contact + pose.degagement_m},
            vitesse="couvercle_pile",
        )
