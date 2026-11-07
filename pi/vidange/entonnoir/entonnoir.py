"""L'entonnoir à bocaux : où il est (`entonnoir_place`), et ses gestes avec la Préhension.

    entonnoir = Entonnoir(reglages.machine, donnees / "entonnoir.json", vision=..., photo=...)
    entonnoir.demarrer_lot(["bocal_0_0", "bocal_0_1", ...])      # l'ordre est choisi par le Pi
    prehension.lancer(lambda: entonnoir.geste_prendre(prehension))
    prehension.lancer(lambda: entonnoir.geste_poser(prehension, bocal, centre_du_col))
    entonnoir.refus_versement(bocal)       # la griffe ne verse que dans le bocal noté
    entonnoir.sur_le_plateau()             # pas de photo du fond au hublot tant qu'il y est

L'entonnoir n'a ni capteur ni moteur : c'est un objet que la Préhension prend par l'oreille
(ventouse, électroaimants éteints), que la caméra du plafond situe et que la griffe remplit. Pas
de poste de repos : il reste sur le dernier bocal rempli, Karulium le pose et l'enlève à la main
(Go). Tout passe par les signaux de la Préhension (`vanne_vide`, `contact_tete`, `vide_venturi`,
`electroaimants_capsule`) : l'entonnoir n'a aucun signal à lui.

`entonnoir_place` est un état du Pi, gardé dans un fichier de donnees/ : un nom de bocal,
« hors_machine » ou « inconnu ». Il est mis à « inconnu » quand on n'est plus sûr (vide perdu,
entonnoir absent, introuvable à la caméra, coupure pendant qu'il était tenu). Karulium le
repose alors à la main et donne le Go : le geste 1 recommence.

Ces verrous ne protègent que la MACHINE : la sécurité des personnes reste câblée.
"""

import math
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Protocol

from vidange.chef import Condition, ErreurEtape
from vidange.entonnoir import etat as garde
from vidange.entonnoir.etat import HORS_MACHINE, INCONNU, EtatGarde
from vidange.journal import donner_journal
from vidange.prehension.prehension import Attente, Prehension
from vidange.prehension.tete import Pas, Resultat
from vidange.reglages import Machine
from vidange.stockage import places

journal = donner_journal("entonnoir")

Geste = Generator[Pas | Attente, Resultat | None, None]

QUOI_FAIRE_DEMANDE = (
    "Poser l'entonnoir à la main sur le bocal que l'écran indique, l'oreille vers le fond (côté "
    "+x), puis donner le Go. Sans ce Go, la griffe ne verse dans aucun bocal."
)
QUOI_FAIRE_ENLEVER = "Enlever l'entonnoir à la main avant de fermer les bocaux, puis donner le Go."
QUOI_FAIRE_INTROUVABLE = (
    "La caméra du plafond ne voit pas l'entonnoir sur le bocal : le poser à la main sur le bocal "
    "que l'écran indique (bouche bien centrée sur le col, oreille vers +x), puis acquitter et "
    "donner le Go."
)
QUOI_FAIRE_ABSENT = (
    "Pas d'entonnoir sous la ventouse : regarder la vidéo et la photo. Le poser à la main sur le "
    "bocal que l'écran indique (oreille vers +x), puis acquitter et donner le Go."
)
QUOI_FAIRE_MAL_POSE = (
    "L'entonnoir est mal posé (oreille trop haute : de travers ou pas au fond du col) : le "
    "remettre bien à plat sur son bocal, puis acquitter et donner le Go."
)
QUOI_FAIRE_VIDE = (
    "La ventouse ne prend pas l'entonnoir : regarder la ventouse (sale ou abîmée), l'oreille "
    "(sale) et les tuyaux (fuite). Vérifier aussi l'air : compresseur sous tension, vanne "
    "d'isolement ouverte. Puis acquitter et donner le Go : le geste est refait."
)
QUOI_FAIRE_PERDU = (
    "Le vide a été perdu en tenant l'entonnoir : il est peut-être tombé. Regarder la photo du "
    "plafond. Si un bocal est renversé, arrêter le lot. Sinon, poser l'entonnoir à la main sur le "
    "bocal que l'écran indique, puis acquitter et donner le Go. La griffe ne verse plus tant que "
    "ce n'est pas fait."
)
QUOI_FAIRE_COLLE = (
    "L'entonnoir est resté collé à la ventouse au lâcher : regarder la ventouse et le tuyau de "
    "vide. Le détacher à la main si besoin, puis acquitter et donner le Go."
)
QUOI_FAIRE_POSE = (
    "L'entonnoir tenu n'a pas pu se poser sur le col : regarder la vidéo (pointe sur le bord du "
    "verre, bocal bougé ?). La tête le tient toujours. Corriger, puis acquitter et donner le Go : "
    "la pose est refaite."
)


def lisible(bocal: str) -> str:
    """« bocal_3_5 » → « rangée 4, place 6 » (comme l'écran le dit à Karulium)."""
    try:
        _, rangee, place = bocal.split("_")
        return f"rangée {int(rangee) + 1}, place {int(place) + 1}"
    except ValueError:
        return bocal


class VisionEntonnoir(Protocol):
    """Ce que l'Entonnoir demande à la caméra du plafond (vision, plus tard). La photo se prend
    pont garé à sa place de photo, les deux outils en haut (portique → photo → stockage)."""

    def entonnoir_vu(self, bocal: str) -> bool | None:
        """L'entonnoir est-il vu sur ce bocal (bouche centrée sur le col à ± precision_m) ?
        None : photo pas lue."""
        ...

    def centre_du_col(self, bocal: str) -> tuple[float, float] | None:
        """Centre du col du bocal (x ; y), à ± precision_m ; None : col pas trouvé."""
        ...


class VisionAttendue:
    """En attendant la vraie lecture de la photo (la vision ne sait pas encore la faire) : répond
    ce que le Pi attend, et le dit dans le journal."""

    def __init__(self, entonnoir: "Entonnoir") -> None:
        self._entonnoir = entonnoir
        self._dit = False

    def _dire(self) -> None:
        if not self._dit:
            journal.warning(
                "Entonnoir : la vision ne lit pas encore la photo du plafond ; un faux répond les "
                "places attendues"
            )
            self._dit = True

    def entonnoir_vu(self, bocal: str) -> bool | None:
        self._dire()
        return self._entonnoir.place == bocal

    def centre_du_col(self, bocal: str) -> tuple[float, float] | None:
        self._dire()
        return self._entonnoir.places.get(bocal)


class Entonnoir:
    def __init__(
        self,
        machine: Machine,
        fichier: Path | None = None,
        vision: VisionEntonnoir | None = None,
        photo: Callable[[str], object] = lambda raison: None,
        main: Callable[[str | None], object] = lambda bocal: None,
        marquer_suspect: Callable[[str], object] = lambda bocal: None,
    ) -> None:
        """`fichier` : où garder l'état (donnees/entonnoir.json ; None : nulle part). `vision` :
        la caméra du plafond (None : un faux répond les places attendues). `photo(raison)` : photo
        du plafond notée avec une alerte. `main(bocal)` : Karulium a posé l'entonnoir à la main
        sur ce bocal (None : il l'a enlevé), pour le simulateur. `marquer_suspect(bocal)` : le
        bocal est « suspect » (sur la machine :
        `stockage.inventaire.changer_bocal(bocal, "suspect")`)."""
        assert machine.entonnoir is not None and machine.prehension is not None
        assert machine.stockage is not None
        self.machine = machine
        self.reglages = machine.entonnoir
        self.places = places.places_bocaux(machine)
        suspects, separation = places.coin_inspection(machine)
        # L'entonnoir ne va jamais au coin des suspects ni sur les places de séparation.
        self.interdits = {*suspects, *separation}
        self.fichier = fichier
        self.vision: VisionEntonnoir = vision if vision is not None else VisionAttendue(self)
        self._photo = photo
        self._main = main
        self._marquer_suspect = marquer_suspect
        # Le lot en cours (en mémoire : seul `entonnoir_place` est gardé après une coupure).
        self.restants: list[str] = []
        self.prochain: str | None = None
        self.centre: tuple[float, float] | None = None
        self.verses: set[str] = set()
        self.suspects: list[str] = []
        # La dernière pose a échoué deux fois : l'entonnoir est revenu sur son bocal d'origine.
        self.pose_ratee: str | None = None
        # Ce qui a été dit à l'écran, pour l'historique et les tests.
        self.messages: list[str] = []
        etat, existait = garde.lire(fichier)
        if existait and etat.tenu:
            journal.warning(
                "Entonnoir : coupure pendant qu'il était tenu (il a pu tomber) : place inconnue"
            )
            etat = EtatGarde(INCONNU, False)
            garde.ecrire(fichier, etat)
        self.place = etat.place
        self.tenu = etat.tenu
        if existait and self.place != HORS_MACHINE:
            # Coupure : photo du plafond au redémarrage.
            self._photo("entonnoir : redémarrage")
        self.verse_permis = Condition(
            "entonnoir posé sur le bocal à remplir (entonnoir_place connue)",
            self.versement_possible,
            QUOI_FAIRE_DEMANDE,
        )

    # ------------------------------------------------------------ où est l'entonnoir

    def _changer(self, place: str, tenu: bool) -> None:
        self.place, self.tenu = place, tenu
        garde.ecrire(self.fichier, EtatGarde(place, tenu))
        journal.info("Entonnoir : entonnoir_place = %s%s", place, " (tenu)" if tenu else "")

    def connue(self) -> bool:
        """La place est un bocal."""
        return self.place in self.places

    def sur_le_plateau(self) -> bool:
        """Pas de photo du fond au hublot tant que l'entonnoir est sur le plateau (règle du
        Stockage) : sur un bocal, tenu par la tête, ou de place inconnue (par prudence)."""
        return self.place != HORS_MACHINE

    def versement_possible(self) -> bool:
        return self.connue() and not self.tenu

    def refus_versement(self, bocal: str) -> str | None:
        """La griffe ne verse QUE dans le bocal noté `entonnoir_place` (et une fois)."""
        if self.tenu:
            return "la griffe ne verse pas : la tête de préhension tient l'entonnoir"
        if not self.connue():
            return (
                f"la griffe ne verse pas : entonnoir_place est « {self.place} » (poser "
                "l'entonnoir à la main et donner le Go)"
            )
        if bocal != self.place:
            return (
                f"la griffe ne verse pas dans le bocal {lisible(bocal)} : l'entonnoir est sur le "
                f"bocal {lisible(self.place)}"
            )
        if bocal in self.verses:
            return f"le bocal {lisible(bocal)} a déjà reçu sa dose"
        return None

    def declarer_inconnu(self, raison: str) -> None:
        journal.warning("Entonnoir : place inconnue (%s)", raison)
        self._changer(INCONNU, False)

    def apres_coupure(self, prehension: Prehension) -> None:
        """Au redémarrage : si le carnet de la préhension dit qu'elle tient l'entonnoir, le vide
        est tombé avec le courant (électrovannes NF) : elle ne le tient plus."""
        if prehension.objet is not None and prehension.objet.sorte == "entonnoir":
            prehension.objet, prehension.poids_porte_n = None, 0.0

    # ------------------------------------------------------------ à la main (Go de Karulium)

    def demande(self) -> str:
        """Ce que l'écran dit à Karulium pour le geste 1 (ou 13)."""
        if self.prochain is None:
            return "Enlevez l'entonnoir à la main avant de fermer les bocaux, puis donnez le Go."
        return (
            f"Posez l'entonnoir sur le bocal {lisible(self.prochain)}, oreille vers le fond "
            "(+x), puis donnez le Go."
        )

    def demander_la_pose(self) -> None:
        """Étape du Go : Karulium dit qu'il a posé l'entonnoir sur le bocal demandé."""
        if self.prochain is None:
            raise ErreurEtape("entonnoir : plus de bocal à remplir", QUOI_FAIRE_ENLEVER)
        self._changer(self.prochain, False)
        self._main(self.prochain)

    def enlever_a_la_main(self) -> None:
        """Étape du Go de fin de lot : Karulium dit qu'il a enlevé l'entonnoir."""
        self._changer(HORS_MACHINE, False)
        self._main(None)

    # ------------------------------------------------------------ le lot

    def ordre_de_remplissage(self, bocaux: list[str]) -> list[str]:
        """Rangée par rangée, les voisins de la même rangée à la suite (transports courts), en
        serpentin : une rangée dans un sens, la suivante dans l'autre. Dans le quinconce, deux
        bocaux de rangées voisines au bout du serpentin sont aussi proches que deux voisins."""
        rangees: dict[int, list[tuple[int, str]]] = {}
        for bocal in bocaux:
            _, j, i = bocal.split("_")
            rangees.setdefault(int(j), []).append((int(i), bocal))
        ordre: list[str] = []
        for numero, j in enumerate(sorted(rangees)):
            rang = [bocal for _, bocal in sorted(rangees[j])]
            ordre += rang if numero % 2 == 0 else rang[::-1]
        return ordre

    def demarrer_lot(self, bocaux: list[str]) -> None:
        """Début d'un lot : les bocaux vides sont sur leurs places ; le premier à remplir est le
        `prochain` (l'écran dit à Karulium où poser l'entonnoir)."""
        if len(set(bocaux)) != len(bocaux):
            raise ValueError("lot de bocaux : un bocal est cité deux fois")
        for bocal in bocaux:
            if bocal not in self.places:
                raise ValueError(f"lot de bocaux : « {bocal} » n'est pas une place du quinconce")
            if bocal in self.interdits:
                raise ValueError(
                    f"lot de bocaux : « {bocal} » est dans le coin des suspects ou de la "
                    "séparation : l'entonnoir n'y va jamais"
                )
        if not bocaux:
            raise ValueError("lot de bocaux : aucun bocal")
        self.restants = self.ordre_de_remplissage(bocaux)
        self.prochain = self.restants.pop(0)
        self.centre = None
        self.verses, self.suspects, self.pose_ratee = set(), [], None
        self.messages.append(self.demande())

    def noter_verse(self, bocal: str) -> None:
        self.verses.add(bocal)

    def _suspect(self, bocal: str) -> None:
        journal.warning("Entonnoir : bocal %s marqué suspect", lisible(bocal))
        self.suspects.append(bocal)
        self._marquer_suspect(bocal)

    def passer_au_suivant(self) -> bool:
        """Geste 4 : le bocal suivant, dont la caméra donne le centre du col. Col pas trouvé :
        bocal « suspect », on passe au suivant. Faux : plus de bocal (fin du lot)."""
        while self.restants:
            bocal = self.restants.pop(0)
            centre = self.vision.centre_du_col(bocal)
            if centre is None:
                self._suspect(bocal)
                continue
            self.prochain, self.centre = bocal, centre
            return True
        self.prochain, self.centre = None, None
        self.messages.append(self.demande())
        return False

    def controler_la_camera(self) -> None:
        """Geste 2 : la caméra voit l'entonnoir sur le bocal (bouche centrée sur le col). Sinon
        « entonnoir introuvable » : place inconnue, il faut redemander le geste 1."""
        if not self.connue():
            return
        vu = self.vision.entonnoir_vu(self.place)
        if vu:
            return
        bocal = self.prochain or self.place
        self.declarer_inconnu("introuvable à la caméra")
        self._photo("entonnoir introuvable")
        raison = "photo pas lue" if vu is None else "pas vu"
        self.messages.append(self.demande())
        raise ErreurEtape(
            f"entonnoir introuvable sur le bocal {lisible(bocal)} ({raison})",
            QUOI_FAIRE_INTROUVABLE,
        )

    # ------------------------------------------------------------ positions

    def tete_sur(
        self, bocal: str, centre: tuple[float, float] | None = None
    ) -> tuple[float, float]:
        """L'axe de la tête (x ; y) pour tenir l'oreille de l'entonnoir posé sur ce bocal, ou pour
        poser l'entonnoir sur le col de centre `centre` (caméra ; sinon le centre attendu)."""
        x, y = centre if centre is not None else self.places[bocal]
        return (
            round(x + self.reglages.decalage_oreille_x_m, 6),
            round(y + self.reglages.decalage_oreille_y_m, 6),
        )

    def pont_pour(self, bocal: str) -> float:
        """Le x du pont quand la ventouse est sur l'oreille de ce bocal (x + 0,140 − 0,129)."""
        assert self.machine.prehension is not None
        return self.tete_sur(bocal)[0] - self.machine.prehension.decalage_mat_x

    # ------------------------------------------------------------ prendre (gestes 5 à 8)

    def _exiger_libre(self, prehension: Prehension, bocal: str) -> None:
        if prehension.objet is not None:
            raise ErreurEtape(f"préhension : la tête tient déjà un(e) {prehension.objet.sorte}")
        if self.tenu:
            raise ErreurEtape("entonnoir : noté comme tenu par la tête, qui ne le tient pas")
        if self.place != bocal or bocal not in self.places:
            raise ErreurEtape(
                f"entonnoir : noté sur « {self.place} », pas sur le bocal {lisible(bocal)} : "
                "rien à prendre",
                QUOI_FAIRE_DEMANDE,
            )

    def geste_prendre(self, prehension: Prehension, bocal: str | None = None) -> Geste:
        """Prendre l'entonnoir posé sur `bocal` (défaut : où il est noté) : ventouse sur l'oreille
        (x bocal + 0,140), aimants éteints, descente rapide puis lente jusqu'au contact, contrôle
        de la hauteur, vide de la prise (un seul nouvel essai), levée de transport, pesée."""
        bocal = bocal or self.place
        self._exiger_libre(prehension, bocal)
        reg = self.reglages
        tete = prehension.tete
        vide = prehension.reglages.vide
        objet = prehension.objet_par_nom("entonnoir")
        x, y = self.tete_sur(bocal)
        tete.aimants(False)
        yield from prehension.aller(x, y)
        tete.tarer()
        rapide = reg.oreille_z + reg.approche_m
        assert prehension.pose is not None
        if prehension.pose.z > rapide + prehension.reglages.tolerance_m:
            resultat = yield Pas(
                "descente vers l'oreille de l'entonnoir", {"z": rapide}, palper=True
            )
            assert resultat is not None
            if resultat.contact:
                yield from self._mal_pose(prehension, bocal, resultat.pose.z)
        essais = 0
        while True:
            bas = reg.oreille_z - reg.prise.trop_bas_m
            resultat = yield Pas(
                "approche de l'oreille de l'entonnoir", {"z": bas}, vitesse="approche", palper=True
            )
            assert resultat is not None
            if not resultat.contact:
                yield from self._absent(prehension, bocal, bas)
            z = resultat.pose.z
            journal.info(
                "Entonnoir : contact de l'oreille à %.4f m (attendu %.4f m)", z, reg.oreille_z
            )
            if z - reg.oreille_z > reg.prise.trop_haut_m + 1e-9:
                yield from self._mal_pose(prehension, bocal, z)
            tete.vanne(True)
            resultat = yield Attente(
                "vide de la prise de l'entonnoir",
                lambda: (v := tete.vide_kpa()) is not None and v <= vide.prise_kpa,
                reg.vide.delai_prise_s,
                f"vide de {vide.prise_kpa:g} kPa pas atteint en {reg.vide.delai_prise_s:g} s",
                QUOI_FAIRE_VIDE,
                sans_alarme=True,
            )
            assert resultat is not None
            if not resultat.delai_depasse:
                break
            # Souffler, remonter de 5 mm, redescendre, réessayer une seule fois.
            essais += 1
            tete.vanne(False)
            yield Pas("souffle", attente_s=vide.relache_s)
            if essais > 1:
                yield from prehension.monter()
                raise ErreurEtape(
                    "préhension : la ventouse ne prend pas l'entonnoir (vide de "
                    f"{vide.prise_kpa:g} kPa pas atteint après un nouvel essai)",
                    QUOI_FAIRE_VIDE,
                )
            yield Pas(
                "remonter avant le nouvel essai",
                {"z": z + reg.vide.remontee_reessai_m},
                vitesse="approche",
            )
        prehension.vide_prise_kpa = tete.vide_kpa()
        journal.info("Entonnoir : pris, vide %.1f kPa", prehension.vide_prise_kpa or 0.0)
        # Dès que la tête le tient : une coupure à partir d'ici le met « inconnu ».
        self._changer(bocal, True)
        prehension.objet = objet
        resultat = yield Pas(
            "levée de l'entonnoir",
            {"z": reg.face_transport_z},
            vitesse="approche",
            vide_perte_kpa=vide.perte_kpa,
        )
        assert resultat is not None
        if resultat.arret == "vide":
            yield from self._vide_perdu(prehension)
        resultat = yield Pas(
            "pesée de l'entonnoir", attente_s=prehension.reglages.force.attente_pesee_s, pesee=True
        )
        assert resultat is not None and resultat.force_n is not None
        prehension.poids_porte_n = resultat.force_n
        journal.info("Entonnoir : pesé %.1f N", resultat.force_n)

    def _mal_pose(self, prehension: Prehension, bocal: str, z: float) -> Geste:
        """Contact trop haut : l'entonnoir est mal posé. Tête en haut, photo, alerte ; il reste
        noté sur son bocal."""
        yield from prehension.monter()
        self._photo("entonnoir mal posé")
        raise ErreurEtape(
            f"entonnoir mal posé sur le bocal {lisible(bocal)} : contact à {z:.3f} m, attendu "
            f"{self.reglages.oreille_z:.3f} m (au plus {self.reglages.prise.trop_haut_m * 1000:g} "
            "mm plus haut)",
            QUOI_FAIRE_MAL_POSE,
        )

    def _absent(self, prehension: Prehension, bocal: str, bas: float) -> Geste:
        """Pas de contact : pas d'entonnoir. Tête en haut, photo, alerte, place inconnue."""
        yield from prehension.monter()
        self.declarer_inconnu("absent au contact")
        self._photo("entonnoir absent")
        self.messages.append(self.demande())
        raise ErreurEtape(
            f"entonnoir absent sur le bocal {lisible(bocal)} : pas de contact jusqu'à {bas:.3f} m "
            f"(attendu {self.reglages.oreille_z:.3f} m)",
            QUOI_FAIRE_ABSENT,
        )

    def _vide_perdu(self, prehension: Prehension) -> Geste:
        """Vide perdu en tenant l'entonnoir : arrêt (déjà fait par la tête), tête en haut, photo du
        plafond, alerte. Plus de versement tant que Karulium n'a pas dit où il est."""
        perte = prehension.reglages.vide.perte_kpa
        prehension.objet, prehension.poids_porte_n = None, 0.0
        prehension.tete.vanne(False)
        self.declarer_inconnu("vide perdu en transport")
        yield from prehension.monter()
        self._photo("vide perdu en tenant l'entonnoir")
        self.messages.append(self.demande())
        raise ErreurEtape(
            f"vide perdu en tenant l'entonnoir (au-dessus de {perte:g} kPa) : il est peut-être "
            "tombé",
            QUOI_FAIRE_PERDU,
        )

    # ------------------------------------------------------------ poser (gestes 8 à 11)

    def _exiger_tenu(self, prehension: Prehension) -> None:
        objet = prehension.objet
        if objet is None or objet.sorte != "entonnoir" or not self.tenu:
            raise ErreurEtape("entonnoir : la tête ne tient pas l'entonnoir à poser")

    def _transport(self, prehension: Prehension, x: float | None, y: float | None) -> Geste:
        """À la hauteur de transport (6 cm au-dessus de la pose), puis le pont vers (x ; y), en
        surveillant le vide : au-dessus de −40 kPa, arrêt et alerte."""
        reg = self.reglages
        perte = prehension.reglages.vide.perte_kpa
        assert prehension.pose is not None
        if prehension.pose.z < reg.face_transport_z - prehension.reglages.tolerance_m:
            resultat = yield Pas(
                "hauteur de transport",
                {"z": reg.face_transport_z},
                vitesse="approche",
                vide_perte_kpa=perte,
            )
            assert resultat is not None
            if resultat.arret == "vide":
                yield from self._vide_perdu(prehension)
        assert prehension.pose is not None
        if x is None or y is None:
            return
        if math.isclose(prehension.pose.x, x, abs_tol=1e-6) and math.isclose(
            prehension.pose.y, y, abs_tol=1e-6
        ):
            return
        resultat = yield Pas(
            "trajet de l'entonnoir", {"x": x, "y": y}, choc=True, vide_perte_kpa=perte
        )
        assert resultat is not None
        if resultat.arret == "vide":
            yield from self._vide_perdu(prehension)

    def _descendre_sur_le_col(
        self, prehension: Prehension
    ) -> Generator[Pas | Attente, Resultat | None, bool]:
        """Descente en vitesse d'approche jusqu'au contact. Vrai : posé (contact à l'attendu ±
        tolerance_m) ; faux : la pointe n'est pas dans le col."""
        reg = self.reglages
        resultat = yield Pas(
            "descente de l'entonnoir sur le col",
            {"z": reg.oreille_z - reg.pose.tolerance_m},
            vitesse="approche",
            palper=True,
            vide_perte_kpa=prehension.reglages.vide.perte_kpa,
        )
        assert resultat is not None
        if resultat.arret == "vide":
            yield from self._vide_perdu(prehension)
        if not resultat.contact:
            raise ErreurEtape(
                "entonnoir : pas de contact en le posant jusqu'à "
                f"{reg.oreille_z - reg.pose.tolerance_m:.3f} m (attendu {reg.oreille_z:.3f} m)",
                QUOI_FAIRE_POSE,
            )
        ecart = resultat.pose.z - reg.oreille_z
        journal.info(
            "Entonnoir : contact à la pose à %.4f m (écart %+.1f mm)", resultat.pose.z, ecart * 1000
        )
        if abs(ecart) <= reg.pose.tolerance_m + 1e-9:
            return True
        raison = (
            "la pointe est sur le bord du verre"
            if ecart >= reg.pose.bord_du_verre_m
            else "pas assez bas"
        )
        journal.warning("Entonnoir : pas entré dans le col (%+.1f mm : %s)", ecart * 1000, raison)
        return False

    def _relever(self, prehension: Prehension) -> Geste:
        """Relever de la levée de transport, en vitesse d'approche."""
        resultat = yield Pas(
            "relever l'entonnoir",
            {"z": self.reglages.face_transport_z},
            vitesse="approche",
            vide_perte_kpa=prehension.reglages.vide.perte_kpa,
        )
        assert resultat is not None
        if resultat.arret == "vide":
            yield from self._vide_perdu(prehension)

    def _lacher(self, prehension: Prehension, bocal: str) -> Geste:
        """Geste 11 : vanne fermée (souffle), vide revenu au-dessus de −5 kPa, puis la tête remonte
        de 0,030 en vitesse d'approche (l'entonnoir doit rester posé), puis en rapide."""
        reg = self.reglages
        tete = prehension.tete
        relache = prehension.reglages.vide.relache_s
        assert prehension.pose is not None
        z = prehension.pose.z

        def lache() -> bool:
            valeur = tete.vide_kpa()
            return valeur is not None and valeur > reg.vide.lache_kpa

        tete.vanne(False)
        yield Pas("souffle", attente_s=relache)
        resultat = yield Attente(
            "vide lâché",
            lache,
            reg.vide.delai_lacher_s,
            "vide pas revenu",
            QUOI_FAIRE_COLLE,
            sans_alarme=True,
        )
        assert resultat is not None
        if resultat.delai_depasse:
            tete.vanne(False)
            yield Pas("nouveau souffle", attente_s=relache)
            yield Attente(
                "vide lâché (nouveau souffle)",
                lache,
                reg.vide.delai_lacher_s,
                f"entonnoir resté collé à la ventouse (vide au-dessous de {reg.vide.lache_kpa:g} "
                "kPa après un nouveau souffle)",
                QUOI_FAIRE_COLLE,
            )
        prehension.objet, prehension.poids_porte_n = None, 0.0
        tete.acceleration_seau(False)
        self._changer(bocal, False)
        yield Pas("remontée douce", {"z": z + reg.remontee_lacher_m}, vitesse="approche")
        yield from prehension.monter()

    def geste_poser(
        self,
        prehension: Prehension,
        bocal: str,
        centre: tuple[float, float] | None = None,
    ) -> Geste:
        """Poser l'entonnoir tenu sur le col du bocal `bocal` (`centre` : donné par la caméra, geste
        4). Transport à 6 cm, descente en vitesse d'approche, arrêt au contact, contrôle de la
        hauteur (± 5 mm : posé). Pas entré dans le col : relever et réessayer UNE fois ; encore
        raté : le remettre sur le bocal d'où il vient, le bocal visé devient « suspect » (le lot
        continue ; `pose_ratee`)."""
        self._exiger_tenu(prehension)
        if bocal not in self.places:
            raise ErreurEtape(f"entonnoir : « {bocal} » n'est pas une place du quinconce")
        if bocal in self.interdits:
            raise ErreurEtape(
                f"entonnoir : le bocal {lisible(bocal)} est dans le coin des suspects ou de la "
                "séparation : il n'y va jamais"
            )
        origine = self.place
        self.pose_ratee = None
        x, y = self.tete_sur(bocal, centre)
        for essai in (1, 2):
            yield from self._transport(prehension, x, y)
            if (yield from self._descendre_sur_le_col(prehension)):
                yield from self._lacher(prehension, bocal)
                return
            if essai == 1:
                yield from self._relever(prehension)
        # Deux échecs : retour sur le bocal d'origine (centre attendu, sans caméra).
        self._suspect(bocal)
        self.pose_ratee = bocal
        yield from self._relever(prehension)
        xo, yo = self.tete_sur(origine)
        yield from self._transport(prehension, xo, yo)
        if not (yield from self._descendre_sur_le_col(prehension)):
            raise ErreurEtape(
                f"entonnoir : impossible de le remettre sur le bocal {lisible(origine)} d'où il "
                "vient (la pointe n'entre pas dans le col)",
                QUOI_FAIRE_POSE,
            )
        yield from self._lacher(prehension, origine)

    # ------------------------------------------------------------ pour l'écran et l'essai

    def etat(self) -> dict:
        return {
            "entonnoir_place": self.place,
            "tenu": self.tenu,
            "sur_le_plateau": self.sur_le_plateau(),
            "prochain": self.prochain,
            "demande": self.demande(),
            "suspects": list(self.suspects),
            "verses": sorted(self.verses),
            "restants": list(self.restants),
        }
