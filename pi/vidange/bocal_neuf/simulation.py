"""Le bocal neuf de semence sur la machine imaginaire du simulateur (tâche 19 quater).

    neuf, monde = bocal_neuf_du_simulateur(simulateur, scenario, stockage, registre=registre)

Un faux monde (`MondeBocalNeuf`) répond à la Préhension simulée ce que le vrai ferait : le contact
M8 sur la capsule d'un bocal (cote du dessus de la capsule du stockage, qui monte avec le filet
pendant le dévissage), sur le dessus des piles des deux boîtes ; la poussée (la tôle et la capsule
se compriment de `raideur_n_m`) ; le palier pesé (poids porté − poussée) ; la capsule qui se libère
après `devisse_deg` degrés de dévissage ; le couvercle percé qui cale (moteur) après `filet_deg`
degrés de vissage ; la caméra de la tête qui lit le QR du bocal.

Pannes pour les essais (attributs de MondeBocalNeuf) :
- `devisse_deg` : degrés après lesquels la capsule se libère (None : jamais, elle tient trop fort) ;
- `calage_devissage_deg` : le moteur cale après tant de degrés de dévissage (None : jamais) ;
- `filet_deg` : degrés de vissage jusqu'au calage ; `filets_sautes` : tant de prochains vissages ne
  calent pas (filet sauté) ; `couvercle_pas_visse` : le moteur cale mais le bocal ne vient pas ;
- `masse_capsule_kg`, `masse_couvercle_kg`, `masse_bocal_kg` : masses réelles (None : celles des
  réglages) ;
- `ecart_capsule_m` : le dessus de la capsule est tant plus haut (+) ou plus bas (−) que prévu ;
- `poids_leve_n` : le palier lit tant de N quand le bocal vissé est soulevé (None : son poids) ;
- `places_vides` : places où il n'y a pas de bocal, bien que l'inventaire en compte un ;
- `palier_n` : le palier pesé garde tant de N après le lâcher du bocal (resté à la tête) ;
- `qr_illisibles` : places dont le QR ne se lit pas ; `codes` : place → QR lu ;
- `colles` : tant de prochaines prises amènent DEUX couvercles percés ; `rien_au_levage` : tant de
  prises ne lèvent rien ; `couvercles_en_trop`, `capsules_en_trop` : le compte réel d'une boîte
  diffère de l'inventaire du Pi (+ : plus de pièces qu'il ne croit) ;
- `m8_voit_le_bocal` : le M8 voit encore le bocal après la remontée du porte-bocal ;
- `neuf._reprendre_le_vide = None` : pas de reprise du bocal vide (le geste ouvre les mors et
  demande de l'enlever à la main).
"""

import math

from vidange.bocal_neuf.bocal_neuf import BOCAL_TENU, BocalNeuf
from vidange.griffe.bras import G
from vidange.mycelium.mycelium import Bocal
from vidange.prehension.simulation import TeteSimulee
from vidange.simulateur.simulateur import ErreurSimulation, Simulateur
from vidange.stockage import places
from vidange.stockage.stockage import Stockage

# Un endroit « est » sous la tête si elle en est à moins de tant (m) en x et y.
PROXIMITE_M = 0.005
# Au-dessus de la cote de contact de tant (m), la tête a décollé (elle porte ce qui la suit).
DECOLLE_M = 0.0005
# Préfixe des QR imaginaires des bocaux de semence.
PREFIXE_QR = "SEM-"


class EtatPlace:
    """Ce qu'il y a sur une place de semence : la capsule est-elle vissée, de combien de degrés
    elle est dévissée, de combien le couvercle percé est vissé."""

    def __init__(self) -> None:
        self.capsule_vissee = True
        self.devisse_deg = 0.0
        self.capsule_tenue = False
        self.visse_deg = 0.0


class MondeBocalNeuf:
    def __init__(
        self,
        neuf: BocalNeuf,
        scenario,
        stockage: Stockage,
        devisse_deg: float,
        filet_deg: float,
        raideur_n_m: float,
    ) -> None:
        self.neuf = neuf
        self.scenario = scenario
        self.stockage = stockage
        self.machine = neuf.machine
        self.tete = scenario.prehension.tete
        assert isinstance(self.tete, TeteSimulee)
        self.prehension = scenario.prehension
        self.raideur_n_m = raideur_n_m
        self.devisse_deg: float | None = devisse_deg
        self.filet_deg = filet_deg
        # Pannes.
        self.calage_devissage_deg: float | None = None
        self.filets_sautes = 0
        self.couvercle_pas_visse = False
        self.masse_capsule_kg: float | None = None
        self.masse_couvercle_kg: float | None = None
        self.masse_bocal_kg: float | None = None
        self.ecart_capsule_m = 0.0
        self.poids_leve_n: float | None = None
        self.places_vides: set[str] = set()
        self.palier_n = 0.0
        self.qr_illisibles: set[str] = set()
        self.codes: dict[str, str] = {}
        self.colles = 0
        self.rien_au_levage = 0
        self.couvercles_en_trop = 0
        self.capsules_en_trop = 0
        # Ce qui s'est passé, pour les tests.
        self.vides_repris = 0
        self.lectures_qr: list[str] = []
        self.etats: dict[str, EtatPlace] = {}
        self._aimants = False
        # Couvercles percés tenus par les aimants (0 : aucun).
        self._couvercles_tenus = 0
        reglages = neuf.reglages
        self.z_capsule = neuf.z_capsule
        self.pas_du_filet = neuf.pas_du_filet_m_par_deg
        self.places = places.places_semence(self.machine)
        self.boites = {
            reglages.boites.capsules: stockage.reglages.boites.places[reglages.boites.capsules],
            reglages.boites.couvercles_perces: stockage.reglages.boites.places[
                reglages.boites.couvercles_perces
            ],
        }
        tete = self.tete
        self._contact_avant = tete.contact_local
        self._peser_avant = tete.peser
        self._executer_avant = tete.executer
        self._aimants_avant = tete.aimants
        tete.contact_local = self._contact
        tete.peser = self._peser  # type: ignore[method-assign]
        tete.executer = self._executer  # type: ignore[method-assign]
        tete.aimants = self._aimants_suivis  # type: ignore[method-assign]
        # Le M8 : pendant le geste, il ne voit que ce que le bocal neuf lui montre (le M8 du
        # couvercle, même collé, ne le concerne pas).
        self.en_cours = False
        self.m8_voit_le_bocal = False
        self._m8_avant = tete.contact_actif
        tete.contact_actif = self._m8
        geste_avant = neuf.geste_nouveau_bocal

        def geste(variete: str):
            self.en_cours = True
            try:
                yield from geste_avant(variete)
            finally:
                self.en_cours = False

        neuf.geste_nouveau_bocal = geste  # type: ignore[method-assign]
        # Le bocal vide du porte-bocal : repris par un fil à part (fiche, § 4.5, pas écrite).
        neuf._reprendre_le_vide = self._reprendre_le_vide
        neuf._lire_qr = self.lire_qr

    # ------------------------------------------------------------ où est la tête

    def _lieu(self, x: float, y: float) -> tuple[str, str] | None:
        for nom, centre in self.places.items():
            if math.dist(centre, (x, y)) <= PROXIMITE_M:
                return "place", nom
        for nom, centre in self.boites.items():
            if math.dist(centre, (x, y)) <= PROXIMITE_M:
                return "boite", nom
        return None

    def _present(self, place: str) -> bool:
        """Un bocal est sur cette place (l'inventaire du stockage imaginaire, qui est aussi la
        réalité de ce monde) ; une place vidée oublie son état."""
        if self.stockage.inventaire.bocaux.get(place) and place not in self.places_vides:
            return True
        self.etats.pop(place, None)
        return False

    def etat(self, place: str) -> EtatPlace:
        return self.etats.setdefault(place, EtatPlace())

    def _masse(self, nom: str) -> float:
        reglage = self.neuf.reglages.bocal
        valeurs = {
            "capsule": (self.masse_capsule_kg, reglage.m_capsule_kg),
            "couvercle": (self.masse_couvercle_kg, reglage.m_couv_perce_kg),
            "bocal": (self.masse_bocal_kg, reglage.m_bocal_plein_kg),
        }
        reelle, prevue = valeurs[nom]
        return prevue if reelle is None else reelle

    # ------------------------------------------------------------ la physique

    def surface(self, place: str) -> float | None:
        """Cote où la face de la tête touche, sous la tête, sur cette place (None : rien)."""
        if not self._present(place):
            return None
        etat = self.etat(place)
        base = self.z_capsule + self.ecart_capsule_m
        if etat.capsule_vissee:
            return base + etat.devisse_deg * self.pas_du_filet
        if etat.visse_deg < self.filet_deg and (
            self.prehension.objet is not None or etat.visse_deg > 0
        ):
            # Le couvercle percé posé sur le col : le filet reste à descendre.
            return base + (self.filet_deg - etat.visse_deg) * self.pas_du_filet
        return base

    def _compte_reel(self, boite: str) -> int:
        reglages = self.neuf.reglages.boites
        ecart = self.capsules_en_trop if boite == reglages.capsules else self.couvercles_en_trop
        return self.stockage.inventaire.boites[boite] + ecart

    def _contact(self, x: float, y: float) -> tuple[bool, float | None]:
        lieu = self._lieu(x, y)
        if lieu is None:
            return (False, None) if self._contact_avant is None else self._contact_avant(x, y)
        genre, nom = lieu
        if genre == "place":
            return True, self.surface(nom)
        haut = places.hauteur_boite(self.machine, self._compte_reel(nom))
        # Tenant une pièce, la face touche le dessus de la pièce tenue, sur la pile.
        if self.prehension.objet is not None:
            haut += self.stockage.reglages.boites.epaisseur_capsule_m
        return True, haut

    def _poussee(self, surface: float, z: float) -> float:
        return self.raideur_n_m * max(0.0, surface - z)

    def _peser(self) -> float:
        pose = self.tete.position()
        lieu = self._lieu(pose.x, pose.y)
        if lieu is None:
            if self.palier_n and self.neuf.phase == BOCAL_TENU and self.prehension.objet is None:
                return self.palier_n
            return self._peser_avant()
        genre, nom = lieu
        if genre == "boite":
            haut = places.hauteur_boite(self.machine, self._compte_reel(nom))
            if self._aimants and self._couvercles_tenus and pose.z > haut + DECOLLE_M:
                return self._couvercles_tenus * self._masse("couvercle") * G
            return 0.0
        surface = self.surface(nom)
        if surface is None:
            return self._peser_avant()
        if pose.z < surface - 1e-9:
            return -self._poussee(surface, pose.z)
        etat = self.etat(nom)
        if not self._aimants:
            return 0.0
        if etat.capsule_tenue:
            return self._masse("capsule") * G
        decolle = pose.z > surface + DECOLLE_M
        if etat.capsule_vissee:
            if self.devisse_deg is not None and etat.devisse_deg >= self.devisse_deg:
                return self._masse("capsule") * G
            # La capsule tient encore : en montant, la tête lève aussi le bocal.
            return (self._masse("capsule") + self._masse("bocal")) * G if decolle else 0.0
        if etat.visse_deg >= self.filet_deg:
            if not decolle:
                return 0.0
            if self.couvercle_pas_visse:
                return self._masse("couvercle") * G
            if self.poids_leve_n is not None:
                return self.poids_leve_n
            return self._masse("bocal") * G
        return self._couvercles_tenus * self._masse("couvercle") * G

    def _aimants_suivis(self, actifs: bool) -> None:
        self._aimants_avant(actifs)
        self._aimants = actifs
        pose = self.tete.position()
        lieu = self._lieu(pose.x, pose.y)
        if not actifs:
            self._couvercles_tenus = 0
            for etat in self.etats.values():
                etat.capsule_tenue = False
            return
        if lieu is None or lieu[0] != "boite":
            return
        if lieu[1] == self.neuf.reglages.boites.couvercles_perces and self.prehension.objet is None:
            if self.rien_au_levage > 0:
                self.rien_au_levage -= 1
                self._couvercles_tenus = 0
                return
            self._couvercles_tenus = 2 if self.colles > 0 else 1
            if self.colles > 0:
                self.colles -= 1

    def _executer(self, pas, cible, poids_porte_n) -> None:
        tete = self.tete
        depart = tete.position()
        lieu = self._lieu(depart.x, depart.y)
        tete.cale_apres_deg = None
        place = lieu[1] if lieu is not None and lieu[0] == "place" else None
        surface = None if place is None else self.surface(place)
        etat = None if place is None or surface is None else self.etat(place)
        vissage_sur_place = pas.vissage and etat is not None and "a" in pas.cibles
        if pas.appui_arret_n is not None and not pas.vissage and surface is not None:
            # Appui : la tôle et la capsule se compriment jusqu'à la poussée demandée.
            force = min(tete.appui_vissage_n, pas.appui_arret_n)
            cible = cible.avec(z=max(cible.z, surface - force / self.raideur_n_m))
        devissage = vissage_sur_place and cible.a > depart.a
        vissage = vissage_sur_place and cible.a < depart.a
        if devissage and etat is not None and etat.capsule_vissee:
            tete.cale_apres_deg = self.calage_devissage_deg
        if vissage and etat is not None and not etat.capsule_vissee:
            if self.filets_sautes > 0:
                self.filets_sautes -= 1
                vissage = False
            else:
                tete.cale_apres_deg = max(self.filet_deg - etat.visse_deg, 0.0)
        self._executer_avant(pas, cible, poids_porte_n)
        if place is None or etat is None:
            return
        fait = tete.resultat().pose.a - depart.a
        if devissage and etat.capsule_vissee:
            etat.devisse_deg += fait
        elif vissage:
            etat.visse_deg += abs(fait)
        elif pas.vissage and fait > 0 and not etat.capsule_vissee:
            # Le couvercle percé est dévissé (filet sauté : il est remis dans sa boîte).
            etat.visse_deg = max(0.0, etat.visse_deg - fait)
        # La capsule libre part avec la tête dès que la tête décolle.
        if (
            not pas.vissage
            and etat.capsule_vissee
            and self._aimants
            and self.devisse_deg is not None
            and etat.devisse_deg >= self.devisse_deg
            and tete.resultat().pose.z > surface + DECOLLE_M
        ):
            etat.capsule_vissee = False
            etat.capsule_tenue = True

    # ------------------------------------------------------------ le QR et le porte-bocal

    def lire_qr(self, place: str) -> str | None:
        """Ce que lit la caméra de la tête de la griffe au-dessus de la place."""
        self.lectures_qr.append(place)
        if place in self.qr_illisibles:
            return None
        return self.codes.setdefault(place, f"{PREFIXE_QR}{place}")

    def _m8(self) -> bool:
        if self.en_cours:
            return self.m8_voit_le_bocal
        return self._m8_avant()

    def reapprovisionner(self, variete: str, couvercles: int) -> None:
        """Karulium recharge (machine imaginaire du lot) : les places de semence vides ont un bocal
        neuf, la boîte des capsules est vidée, celle des couvercles percés remplie."""
        inventaire = self.stockage.inventaire
        for place in self.places:
            if place not in inventaire.bocaux:
                self.stockage.poser_bocal(place, variete)
        boites = self.neuf.reglages.boites
        if inventaire.boites[boites.capsules] >= places.capacite_boite(self.machine) - 1:
            inventaire.changer_boite(boites.capsules, 0)
        if inventaire.boites[boites.couvercles_perces] <= 1:
            inventaire.changer_boite(boites.couvercles_perces, couvercles)

    def _reprendre_le_vide(self) -> None:
        porte_bocal = self.prehension.porte_bocal
        assert porte_bocal is not None
        porte_bocal.ouvrir_mors()
        self.vides_repris += 1


def bocal_neuf_du_simulateur(
    simulateur: Simulateur,
    scenario,
    stockage: Stockage,
    registre=None,
    **options,
) -> tuple[BocalNeuf, MondeBocalNeuf]:
    """Le BocalNeuf sur la Préhension simulée du scénario (« remplissage » ou « cycle »), branché au
    Mycélium du scénario. Le stockage reçoit les bocaux de semence, les capsules et les couvercles
    percés de simulateur.yaml (cycle → bocal_neuf). `options` : ceux de BocalNeuf (photo...)."""
    machine = simulateur.reglages.machine
    cycle = simulateur.reglages.simulateur.cycle
    if machine.bocal_neuf is None:
        raise ErreurSimulation("machine.yaml n'a pas de partie « bocal_neuf »")
    if cycle is None or cycle.bocal_neuf is None:
        raise ErreurSimulation("simulateur.yaml, cycle : pas de bocaux de semence (bocal_neuf)")
    simule = cycle.bocal_neuf
    libres = list(places.places_semence(machine))
    if simule.bocaux > len(libres):
        raise ErreurSimulation(
            f"simulateur.yaml, cycle → bocal_neuf : {simule.bocaux} bocaux, mais seulement "
            f"{len(libres)} places de semence"
        )
    for place in libres[: simule.bocaux]:
        stockage.poser_bocal(place, cycle.variete)
    boites = machine.bocal_neuf.boites
    stockage.inventaire.changer_boite(boites.capsules, simule.capsules)
    stockage.inventaire.changer_boite(boites.couvercles_perces, simule.couvercles_perces)
    neuf = BocalNeuf(machine, scenario.prehension, stockage, registre=registre, **options)
    monde = MondeBocalNeuf(
        neuf, scenario, stockage, simule.devisse_deg, simule.filet_deg, simule.raideur_n_m
    )
    scenario.mycelium.brancher_bocal_neuf(neuf)
    # Le bocal posé pèse ce que dit simulateur.yaml (mycelium → bocal_kg) sur le faux agitateur.
    simule_mycelium = simulateur.reglages.simulateur.mycelium
    bocal_pose = neuf.bocal

    def bocal() -> Bocal:
        pose = bocal_pose()
        if simule_mycelium is not None:
            scenario.mycelium.agitateur.bocal_kg = simule_mycelium.bocal_kg
        if simule.reapprovisionne:
            monde.reapprovisionner(cycle.variete, simule.couvercles_perces)
        return pose

    neuf.bocal = bocal  # type: ignore[method-assign]
    return neuf, monde
