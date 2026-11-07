"""La préhension sur la machine imaginaire du simulateur, avec un faux porte-bocal.

    prehension = prehension_du_simulateur(simulateur)
    module = module_prehension(prehension, simulateur.reglages.simulateur.prehension)

La tête simulée (`TeteSimulee`) bouge les axes imaginaires (pont_x, chariot_y, prehension_z,
prehension_a). Une descente au contact s'arrête à la cote attendue (celle que le geste donne,
5 mm au-dessus du bas de l'approche lente) ; le vide vient quand la vanne s'ouvre au contact ;
la pesée lit le poids estimé de l'objet tenu.

Pannes pour les essais (attributs de TeteSimulee) :
- `decalage_contact_m` : le contact vient tant plus haut (+) ou plus bas (−) ; None : rien ;
- `pertes_de_vide` : tant de levées perdent le vide (la tête s'arrête comme sur un vrai
  « feed hold ») ;
- `poids_n` : poids lu à la place du poids estimé (deux seaux : 10 N) ;
- `choc_au_trajet` : le prochain trajet du pont s'arrête sur un choc ;
- `appui_vissage_n` : appui lu pendant le vissage (au-delà de 150 N : arrêt).
- `traction_n` : traction lue pendant un tirage (séparation de deux seaux du Remplissage).
- `contact_physique(x, y)` : si donné, la cote où la face touche quelque chose sous (x ; y) (None :
  rien) ; remplace `decalage_contact_m` (l'Entonnoir y met sa physique) ;
- `vides_refuses` : tant de fois la vanne s'ouvre sans que le vide vienne (ventouse sale) ;
- `contact_local(x, y)` : (concerne, cote) pour un endroit que la physique du couvercle (tâche
  41 bis) connaît : si concerne, la descente au contact n'a que ce contact-là (None : rien) ;
- `contact_actif()` : ce que voit le M8 en ce moment (dégagement du couvercle) ;
- `vides_colles` : tant de fois la vanne se ferme sans que le vide parte (objet collé) ;
- `cale_apres_deg` : un pas `cale` (vissage du couvercle percé, tâche 19 quater) s'arrête, moteur
  calé, après tant de degrés de rotation (None : il ne cale jamais).
"""

from collections.abc import Callable
from typing import Any

from vidange.chef import Condition, ErreurEtape
from vidange.mycelium.regles import PoseAgitateur, ReglesMycelium
from vidange.prehension.prehension import Prehension
from vidange.prehension.regles import Objet, Pose
from vidange.prehension.tete import BROSSES, QUOI_FAIRE_CHOC, Pas, Resultat
from vidange.reglages import Machine
from vidange.simulateur.axes import EtatAxes
from vidange.simulateur.simulateur import ErreurSimulation, Simulateur

CARTE_PONT = "portique"
CARTE_TETE = "prehension"


class FauxPorteBocalPrehension:
    """Le porte-bocal tout simple, pour la préhension : chaque geste des mors dure `duree_s`."""

    def __init__(self, duree_s: float, horloge: Callable[[], float]) -> None:
        self.duree_s = duree_s
        self._horloge = horloge
        self._fin = 0.0
        self.etat = "ouverts"
        self.gestes: list[str] = []

    def _geste(self, nom: str, etat: str) -> None:
        self.gestes.append(nom)
        self.etat = etat
        self._fin = self._horloge() + self.duree_s

    def ouvrir_mors(self) -> None:
        self._geste("ouvrir", "ouverts")

    def approcher_mors(self) -> None:
        self._geste("approcher", "approches")

    def serrer_bocal(self) -> None:
        self._geste("serrer", "serres")

    def serre(self) -> bool:
        return self.etat == "serres" and self.fini()

    def ouverts(self) -> bool:
        return self.etat == "ouverts" and self.fini()

    def fini(self) -> bool:
        return self._horloge() >= self._fin


class TeteSimulee:
    """La tête sur les axes imaginaires (mêmes noms que TeteFluidnc)."""

    def __init__(self, etat: EtatAxes, machine: Machine, vide_kpa: float) -> None:
        assert machine.prehension is not None
        self._etat = etat
        self.reglages = machine.prehension
        self._vide_prise = vide_kpa
        self._noms = {"x": "pont_x", "y": "chariot_y", "z": "prehension_z", "a": "prehension_a"}
        self._arrivees: dict[str, float] = {}
        self._resultat: Resultat | None = None
        self._pas: Pas | None = None
        self._vanne = False
        # Le vide tient (vanne ouverte sur un objet, pas perdu pendant une levée).
        self._vide = False
        self._aimants = False
        self._choc = False
        # Ce que tient la préhension (pour la pesée simulée : son poids estimé).
        self.objet_tenu: Callable[[], Objet | None] = lambda: None
        # Pannes.
        self.decalage_contact_m: float | None = 0.0
        self.pertes_de_vide = 0
        self.poids_n: float | None = None
        self.choc_au_trajet = False
        self.appui_vissage_n = 80.0
        self.traction_n = 0.0
        self.contact_physique: Callable[[float, float], float | None] | None = None
        self.contact_local: Callable[[float, float], tuple[bool, float | None]] | None = None
        self.contact_actif: Callable[[], bool] = lambda: False
        self.vides_refuses = 0
        self.vides_colles = 0
        self.cale_apres_deg: float | None = None
        self._colle = False
        # Appelé quand le vide est perdu pendant un pas (l'objet tenu tombe).
        self.apres_perte_de_vide: Callable[[], object] = lambda: None
        # Ce qui a été fait, pour les tests.
        self.sorties: list[str] = []
        self.accelerations: list[bool | tuple[bool, float]] = []
        self.pretes = Condition("cartes simulées prêtes", lambda: True)
        self.surveillance = Condition("cartes simulées sans alarme", lambda: True)

    def position(self) -> Pose:
        positions = self._etat.positions
        return Pose(
            x=positions["pont_x"] + self.reglages.decalage_mat_x,
            y=positions["chariot_y"],
            z=positions["prehension_z"],
            a=positions["prehension_a"],
        )

    def _axes(self, pose: Pose) -> dict[str, float]:
        return {
            "pont_x": pose.x - self.reglages.decalage_mat_x,
            "chariot_y": pose.y,
            "prehension_z": pose.z,
            "prehension_a": pose.a,
        }

    def _vitesses(self, pas: Pas) -> dict[str, float]:
        v = self.reglages.vitesses
        vitesses = {"pont_x": v.pont_x, "chariot_y": v.chariot_y, "prehension_z": v.z}
        vitesses["prehension_a"] = v.vissage_deg_s if pas.vissage else v.a
        if pas.vitesse is not None:
            vitesses["prehension_z"] = min(v.z, getattr(v, pas.vitesse))
        return vitesses

    def executer(self, pas: Pas, cible: Pose, poids_porte_n: float) -> None:
        depart = self.position()
        contact, arret = False, None
        appui = appui_max = None
        local = None if self.contact_local is None else self.contact_local(depart.x, depart.y)
        if pas.palper and local is not None and local[0]:
            sous = local[1]
            if sous is not None and cible.z < sous <= depart.z:
                cible, contact = cible.avec(z=sous), True
        elif pas.palper and self.contact_physique is not None:
            sous = self.contact_physique(depart.x, depart.y)
            if sous is not None and cible.z < sous <= depart.z:
                cible, contact = cible.avec(z=sous), True
        elif pas.palper:
            contact_z = None
            if pas.vitesse == "approche" and self.decalage_contact_m is not None:
                attendu = cible.z + self.reglages.descente.ecart_contact_max_m
                contact_z = attendu + self.decalage_contact_m
            elif pas.vitesse != "approche" and self.decalage_contact_m is not None:
                # Descente rapide : contact seulement si l'objet est bien plus haut qu'attendu.
                attendu = cible.z - self.reglages.descente.approche_m
                if attendu + self.decalage_contact_m > cible.z:
                    contact_z = attendu + self.decalage_contact_m
            if contact_z is not None and cible.z < contact_z <= depart.z:
                cible, contact = cible.avec(z=contact_z), True
        if pas.vide_perte_kpa is not None and self.pertes_de_vide > 0:
            self.pertes_de_vide -= 1
            self._vide = False
            self.apres_perte_de_vide()
            cible, arret = cible.avec(z=depart.z + (cible.z - depart.z) / 2), "vide"
        if pas.choc and self.choc_au_trajet and {"x", "y"} & set(pas.cibles):
            self.choc_au_trajet = False
            self._choc = True
            cible, arret = depart, "choc"
        if pas.appui_arret_n is not None or pas.appui_max_n is not None:
            appui = (
                self.appui_vissage_n
                if pas.vissage
                else min(self.appui_vissage_n, pas.appui_arret_n or self.appui_vissage_n)
            )
            appui_max = appui
            if pas.appui_max_n is not None and appui > pas.appui_max_n:
                arret = "appui_max"
            elif pas.appui_arret_n is not None and appui >= pas.appui_arret_n:
                arret = "appui"
        if pas.cale and self.cale_apres_deg is not None and "a" in pas.cibles:
            tourne = cible.a - depart.a
            if abs(tourne) > self.cale_apres_deg:
                sens = 1 if tourne > 0 else -1
                fraction = self.cale_apres_deg / abs(tourne)
                cible = cible.avec(
                    a=depart.a + sens * self.cale_apres_deg,
                    z=depart.z + (cible.z - depart.z) * fraction,
                )
                arret = "cale"
        if pas.traction_max_n is not None and self.traction_n > pas.traction_max_n:
            cible, arret = depart, "traction"
        bougent = {self._noms[cle] for cle in pas.cibles}
        axes = {nom: valeur for nom, valeur in self._axes(cible).items() if nom in bougent}
        positions = self._etat.positions
        # Brosses du lavage : elles tournent de tant de degrés pendant le pas.
        axes.update(
            {BROSSES[cle]: positions[BROSSES[cle]] + degres for cle, degres in pas.brosses.items()}
        )
        vitesses = self._vitesses(pas)
        if pas.duree_s:
            # Durée imposée : chaque axe va à la vitesse qui le fait arriver à temps.
            vitesses = {
                nom: max(abs(valeur - positions[nom]) / pas.duree_s, 1e-6)
                for nom, valeur in axes.items()
            }
        self._arrivees = self._etat.aller_vers(pas.texte, axes, vitesses)
        if pas.attente_s:
            self._arrivees = self._etat.attendre(CARTE_TETE, pas.attente_s)
        self._pas = pas
        self._resultat = Resultat(
            pose=cible,
            contact=contact,
            arret=arret,  # type: ignore[arg-type]
            appui_n=appui,
            appui_max_n=appui_max,
        )

    def fini(self) -> bool:
        if self._choc and self._pas is not None:
            self._pas = None
            raise ErreurEtape("choc pendant un trajet de la préhension", QUOI_FAIRE_CHOC)
        return self._pas is None or self._etat.arrives(self._arrivees)

    def resultat(self) -> Resultat:
        assert self._resultat is not None
        return self._resultat

    def peser(self) -> float:
        if self.poids_n is not None:
            return self.poids_n
        objet = self.objet_tenu()
        return 0.0 if objet is None else objet.poids_n or 0.0

    def tarer(self) -> None:
        pass

    def peut_detecter_le_calage(self) -> bool:
        return True

    def contact_tete(self) -> bool:
        return self.contact_actif()

    def vanne(self, ouverte: bool) -> None:
        self._vanne = self._vide = ouverte
        if ouverte:
            self._colle = False
        if ouverte and self.vides_refuses > 0:
            self.vides_refuses -= 1
            self._vide = False
        if not ouverte:
            self._colle = self.vides_colles > 0
            if self._colle:
                self.vides_colles -= 1
        self.sorties.append(f"vanne {'ouverte' if ouverte else 'fermée'}")

    def aimants(self, actifs: bool) -> None:
        self._aimants = actifs
        self.sorties.append(f"aimants {'actifs' if actifs else 'coupés'}")

    def vide_kpa(self) -> float | None:
        if self._colle:
            return self._vide_prise
        return self._vide_prise if self._vanne and self._vide else 0.0

    def acceleration_seau(self, reduite: bool, facteur: float = 1.0) -> None:
        # Comme la vraie tête : seuls les changements sont envoyés (et notés ici) ; « (réduite,
        # facteur) » quand la tête basse la réduit encore.
        valeur = reduite if facteur == 1.0 else (reduite, facteur)
        if not self.accelerations or self.accelerations[-1] != valeur:
            self.accelerations.append(valeur)

    def pauser(self) -> None:
        self._etat.pauser()

    def reprendre(self) -> None:
        self._etat.reprendre()

    def arreter(self) -> None:
        self._pas = None

    @property
    def choc(self) -> bool:
        return self._choc

    def oublier_choc(self) -> None:
        self._choc = False


def prehension_du_simulateur(simulateur: Simulateur, **options: Any) -> Prehension:
    """La préhension sur la machine imaginaire : tête en haut (position prehension_haut), faux
    porte-bocal, poste du fût du simulateur (panneau, chariot), manivelle du mycélium en bas
    (prête pour le porte-bocal), lue sur les axes imaginaires. `options` :
    cases vides de Prehension (camera_dosage_pivote, anse_levee, photo...)."""
    reglages = simulateur.reglages
    machine = reglages.machine
    simule = reglages.simulateur.prehension
    if simule is None or machine.prehension is None:
        raise ErreurSimulation("simulateur.yaml ou machine.yaml n'a pas de partie « prehension »")
    horloge = lambda: simulateur.temps  # noqa: E731
    etat = simulateur.etat_axes
    if "prehension_haut" in machine.positions:
        etat.positions.update(machine.positions["prehension_haut"])
    tete = TeteSimulee(etat, machine, simule.vide_kpa)
    porte_bocal = FauxPorteBocalPrehension(simule.mors_s, horloge)
    poste = simulateur.poste_fut()
    options.setdefault("panneau_rabattu", poste.panneau_vu_rabattu)
    options.setdefault("echange_fut", lambda: poste.echange_en_cours)
    if machine.mycelium is not None and "manivelle" in machine.axes:
        mycelium = ReglesMycelium(machine)
        etat.positions["manivelle"] = mycelium.angle_proche(0.0, bas=True)

        def manivelle() -> str | None:
            pose = PoseAgitateur(etat.positions["manivelle"])
            if mycelium.en_haut(pose):
                return "haut"
            return "bas" if mycelium.en_bas(pose) else None

        options.setdefault("manivelle", manivelle)
    prehension = Prehension(machine, tete, porte_bocal, horloge=horloge, **options)
    tete.objet_tenu = lambda: prehension.objet
    return prehension
