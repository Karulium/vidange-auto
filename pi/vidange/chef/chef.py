"""Le chef d'orchestre : fait avancer les modules, étape par étape.

    chef = Chef(reglages.machine, reglages.programme.chef, Carnet(donnees / "etat-cycle.json"))
    chef.lancer(module)       # vérifie le module (délais et zones connus), puis le met en route
    chef.demarrer()           # un fil qui appelle avancer() tous les « periode_s »
    chef.donner_go("exemple") # le « Go » de Karulium, quand l'étape le demande
    chef.pause() / chef.reprendre()
    chef.acquitter("exemple") # après une alarme : l'étape sera refaite, après un nouveau Go
    chef.etat()               # pour les écrans : ce que fait chaque module, ce qu'il attend
    chef.memoriser("exemple", seau="S1293", cycle=12)  # gardé dans le carnet (reprise)
    chef.sur_alarme.append(f)  # f(alarme) est appelée à chaque nouvelle alarme (bilan...)
    chef.interdire(refus)      # refus(geste) : pourquoi ce geste est interdit maintenant, ou None
    chef.empecher_go(refus)    # refus() : pourquoi AUCUN Go n'est accepté maintenant, ou None
    chef.permission("dosage_semence")  # demandée par un module avant un geste : None = permis
    chef.conditions_generales.append(Condition("store fermé", test))  # pour toutes les étapes
    chef.jouer_programme(programme)  # programme du solveur (tâche 23) : None = accepté

Plusieurs modules peuvent tourner en même temps : ils se partagent les zones réservées.
Un module « exclusif » (lieu sûr) passe avant tous les autres : tant qu'il est en route,
les autres attendent, et un Go qui leur est donné est refusé.

Le temps d'une pause ne compte pas dans les délais. Une alarme arrête le module (et met toute
la machine en pause si « alarme_pause_tout ») ; elle attend que Karulium l'acquitte, puis l'étape
est refaite depuis le début après un nouveau Go.

À chaque changement (étape, phase, pause, Go, alarme, zones), l'état est noté dans le carnet,
pour la reprise après coupure (`reprendre_cycle`). Après une coupure, rien ne repart sans Go.
La mémoire d'un module (seau en cours, numéro du cycle dans le registre...) est notée avec,
pour reprendre au bon seau. Par convention, « cycle » y est le numéro du cycle du registre.

Les conditions et les actions sont appelées par le chef lui-même : elles doivent être rapides
(lire un capteur, envoyer une ligne), jamais attendre.

Permissions (tâche 38) : certains gestes « à l'air » (GESTES_PROTEGES : dosage de la semence,
ouverture d'une capsule, versement dans un seau ouvert) sont demandés au chef avant de partir
(`permission`). Un autre morceau du programme peut les interdire pour un temps (`interdire` :
le Nettoyage pendant la purge, raison « purge en cours »). Les conditions générales (store de
l'enceinte fermé...) sont attendues avant chaque étape de chaque module, comme ses conditions
d'entrée. Rien de cela ne protège personne : la sécurité est câblée.

Go empêché (tâche 45 nonies) : un autre morceau du programme peut refuser tout Go pour un temps
(`empecher_go` : un objet encore tenu à la ventouse au redémarrage, vidange.fiabilite.objet_tenu).
La raison est dans l'état (`go_empeche`), pour l'écran et la page ; un Go donné est refusé avec
elle. Rien de cela ne protège personne : la sécurité est câblée.

Programme du solveur (tâche 23, `vidange.chef.programme`) : seulement si `solveur → actif` dans
machine.yaml. Il ne change que l'ordre dans lequel le chef regarde les modules qui attendent la même
zone ; au premier écart (alarme, tour pas suivi, heure trop loin de celle prévue), le chef revient
à son ordre normal et le note au journal (`recul_programme`). Le programme n'est pas noté dans le
carnet : après une coupure, c'est l'ordre normal.
"""

import json
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

from vidange.chef.carnet import Carnet
from vidange.chef.etapes import Condition, ErreurChef, ErreurEtape, Etape, Module
from vidange.chef.programme import JeuProgramme, Programme
from vidange.chef.zones import Reservations
from vidange.journal import donner_journal
from vidange.quoi_faire import ERREUR_PROGRAMME, pour_erreur
from vidange.reglages import Machine, ReglagesChef

journal = donner_journal("chef")

# go : attend le Go (si l'étape le demande) ; entree : attend ses conditions et ses zones ;
# fin : action lancée, attend la condition de fin.
Phase = Literal["go", "entree", "fin"]
Statut = Literal["en_cours", "alarme", "fini", "abandonne"]

ATTENTE_GO = "Go de Karulium"

# Gestes « à l'air » qu'un module demande au chef avant de les faire (Chef.permission).
GESTES_PROTEGES = {
    "dosage_semence": "dosage de la semence",
    "ouverture_capsule": "ouverture d'une capsule",
    "versement_seau_ouvert": "versement dans un seau ouvert",
    # Tâche 39 : spray de culture dans le seau ouvert (vidange.spray).
    "spray_seau": "spray de culture dans un seau ouvert",
    # Tâche 42 : tout geste qui consomme de l'air comprimé (vidange.air : mise en pression).
    "air": "geste qui consomme de l'air comprimé",
}


@dataclass(frozen=True)
class Alarme:
    module: str
    etape: str
    # Ce qui s'est passé.
    message: str
    # Ce que Karulium doit faire.
    quoi_faire: str
    # Heure de l'alarme (heure du Pi).
    date: str


@dataclass(frozen=True)
class EtatModule:
    module: str
    statut: Statut
    etape: str
    numero: int  # de 1 à nombre_etapes, pour l'écran
    nombre_etapes: int
    phase: Phase
    # Ce que le module attend, en clair (« Go de Karulium », « zone « x » libre... »), ou "".
    attend: str
    zones: tuple[str, ...]
    alarme: Alarme | None
    # La zone que le module attend parce qu'un autre la tient, ou "" (planning du simulateur).
    attend_zone: str = ""


@dataclass(frozen=True)
class EtatChef:
    en_pause: bool
    modules: tuple[EtatModule, ...]
    # Pourquoi aucun Go n'est accepté maintenant (objet encore tenu au redémarrage...), ou "".
    go_empeche: str = ""

    @property
    def alarmes(self) -> list[Alarme]:
        return [module.alarme for module in self.modules if module.alarme is not None]

    @property
    def attendent_go(self) -> list[str]:
        return [m.module for m in self.modules if m.statut == "en_cours" and m.attend == ATTENTE_GO]


@dataclass
class _Deroulement:
    """Où en est un module (interne au chef)."""

    module: Module
    numero: int = 0
    phase: Phase = "go"
    statut: Statut = "en_cours"
    # Go demandé même si l'étape ne le demande pas : après une alarme ou une coupure.
    go_obligatoire: bool = False
    go_recu: bool = False
    # Temps passé dans la phase et dans l'étape (s), sans les pauses.
    temps_phase: float = 0.0
    temps_etape: float = 0.0
    # La pause a été transmise au module (il faudra lui transmettre la reprise).
    mis_en_pause: bool = False
    attend: str = ""
    # La zone attendue parce qu'un autre module la tient, ou "".
    attend_zone: str = ""
    alarme: Alarme | None = None
    # Ce que le module veut retrouver après une coupure (seau en cours...), noté dans le carnet.
    memoire: dict[str, Any] = field(default_factory=dict)

    @property
    def etape(self) -> Etape:
        return self.module.etapes[self.numero]

    @property
    def nom(self) -> str:
        return self.module.nom

    @property
    def attend_go(self) -> bool:
        return (
            self.statut == "en_cours"
            and self.phase == "go"
            and (self.etape.demande_go or self.go_obligatoire)
            and not self.go_recu
        )


def _maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Chef:
    def __init__(
        self,
        machine: Machine,
        reglages: ReglagesChef,
        carnet: Carnet | None = None,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self._durees = machine.durees
        self._solveur = machine.solveur
        # Le programme du solveur en train d'être joué (None : ordre normal).
        self._jeu: JeuProgramme | None = None
        # Pourquoi le chef est revenu à son ordre normal (None : pas de recul).
        self.recul_programme: str | None = None
        self._reglages = reglages
        self._zones = Reservations(machine.zones)
        self._carnet = carnet
        self._horloge = horloge
        self._verrou = threading.RLock()
        self._deroulements: dict[str, _Deroulement] = {}
        self._en_pause = False
        self._dernier: float | None = None
        self._arret = threading.Event()
        self._fil: threading.Thread | None = None
        # Appelées (sous le verrou du chef : elles doivent être rapides) à chaque nouvelle alarme.
        self.sur_alarme: list[Callable[[Alarme], object]] = []
        # Qui peut interdire un geste protégé : refus(geste) → raison, ou None.
        self._interdictions: list[Callable[[str], str | None]] = []
        # Attendues avant chaque étape de chaque module (rapides, comme toutes les conditions).
        self.conditions_generales: list[Condition] = []
        # Qui peut refuser tout Go : refus() → raison, ou None (rapide : appelé par etat()).
        self._empechements_go: list[Callable[[], str | None]] = []

    # ------------------------------------------------------------ marche / arrêt

    def demarrer(self) -> None:
        """Lance le fil qui fait avancer les modules."""
        if self._fil is not None:
            return
        self._arret.clear()
        self._fil = threading.Thread(target=self._boucle, name="chef", daemon=True)
        self._fil.start()

    def arreter(self) -> None:
        self._arret.set()
        if self._fil is not None:
            self._fil.join()
            self._fil = None

    def _boucle(self) -> None:
        while not self._arret.wait(self._reglages.periode_s):
            self.avancer()

    # ------------------------------------------------------------ permissions

    def interdire(self, refus: Callable[[str], str | None]) -> None:
        """`refus(geste)` dira pourquoi un geste protégé est interdit maintenant (ou None)."""
        self._interdictions.append(refus)

    def permission(self, geste: str) -> str | None:
        """Un module demande s'il peut faire ce geste protégé : None = permis, sinon la raison."""
        if geste not in GESTES_PROTEGES:
            raise ErreurChef(f"geste protégé inconnu « {geste} »")
        for refus in list(self._interdictions):
            raison = refus(geste)
            if raison is not None:
                return raison
        return None

    def empecher_go(self, refus: Callable[[], str | None]) -> None:
        """`refus()` dira pourquoi aucun Go n'est accepté maintenant (ou None). Il doit être
        rapide : l'état du chef le demande à chaque fois."""
        self._empechements_go.append(refus)

    def refus_go(self) -> str | None:
        """Pourquoi aucun Go n'est accepté maintenant (None : un Go attendu peut être donné)."""
        for refus in list(self._empechements_go):
            raison = refus()
            if raison is not None:
                return raison
        return None

    def condition_permission(self, geste: str) -> Condition:
        """La permission d'un geste protégé, comme condition d'entrée d'une étape."""
        return Condition(
            f"permission du chef : {GESTES_PROTEGES[geste]} (pas de purge en cours)",
            lambda: self.permission(geste) is None,
        )

    # ------------------------------------------------------------ programme du solveur

    def jouer_programme(self, programme: Programme) -> str | None:
        """Joue un programme du solveur, vérifié avant par le simulateur. Rend None s'il est pris,
        sinon pourquoi le chef garde son ordre normal (aussi noté au journal)."""
        with self._verrou:
            refus = self._refus_programme(programme)
            if refus is not None:
                journal.warning("Programme du solveur pas joué : %s. Ordre normal du chef.", refus)
                return refus
            assert self._solveur is not None
            self.recul_programme = None
            self._jeu = JeuProgramme(programme, self._horloge(), self._solveur.ecart_max_s)
            journal.info(
                "Programme du solveur joué : %d passage(s) dans %d zone(s), %.1f s prévues",
                programme.nombre_passages,
                len(programme.passages),
                programme.temps_total_s,
            )
            self._verifier_fin_programme()
            return None

    def _refus_programme(self, programme: Programme) -> str | None:
        if self._solveur is None:
            return "machine.yaml n'a pas de partie « solveur »"
        if not self._solveur.actif:
            return "solveur → actif est faux dans machine.yaml"
        if self._jeu is not None:
            return "un programme est déjà en jeu"
        inconnues = self._zones.verifier(programme.passages)
        if inconnues:
            return f"zone(s) absente(s) de machine.yaml : {', '.join(inconnues)}"
        return None

    @property
    def programme_en_jeu(self) -> bool:
        return self._jeu is not None

    def _reculer(self, raison: str) -> None:
        """Retour à l'ordre normal du chef (décision « La fiabilité d'abord »)."""
        if self._jeu is None:
            return
        self._jeu = None
        self.recul_programme = raison
        journal.warning("Programme du solveur abandonné : %s. Retour à l'ordre normal.", raison)

    def _verifier_fin_programme(self) -> None:
        if self._jeu is not None and self._jeu.fini:
            self._jeu = None
            journal.info("Programme du solveur joué jusqu'au bout")

    def _ordre(self) -> list[_Deroulement]:
        """Les modules dans l'ordre où ce tour les regarde. Sans programme : l'ordre de lancement.

        Avec un programme, seuls les modules qui attendent une zone changent de place entre eux
        (celui dont c'est le tour passe le premier) ; les autres gardent la leur."""
        tous = list(self._deroulements.values())
        jeu = self._jeu
        if jeu is None:
            return tous
        places = [n for n, d in enumerate(tous) if self._zones_voulues(d)]
        if len(places) < 2:
            return tous
        voulants = sorted(
            (tous[n] for n in places), key=lambda d: jeu.rang(d.nom, self._zones_voulues(d))
        )
        for n, d in zip(places, voulants, strict=True):
            tous[n] = d
        return tous

    def _zones_voulues(self, d: _Deroulement) -> list[str]:
        """Les zones que le module va réserver à son étape, et qu'il ne tient pas encore."""
        if d.statut != "en_cours" or d.phase == "fin":
            return []
        tenues = self._zones.tenues_par(d.nom)
        return [zone for zone in d.etape.reserver if zone not in tenues]

    # ------------------------------------------------------------ modules

    def verifier(self, module: Module) -> None:
        """Les délais et les zones que le module cite existent dans machine.yaml."""
        erreurs = []
        for etape in module.etapes:
            for delai in (etape.delai_max, etape.attente_entree_max):
                if delai is not None and delai not in self._durees:
                    erreurs.append(
                        f"étape « {etape.nom} » : délai « {delai} » absent de machine.yaml (durees)"
                    )
            for zone in self._zones.verifier([*etape.reserver, *etape.liberer]):
                erreurs.append(f"étape « {etape.nom} » : zone « {zone} » absente de machine.yaml")
        if erreurs:
            raise ErreurChef(f"module « {module.nom} » : " + " ; ".join(erreurs))

    def lancer(self, module: Module) -> None:
        """Met un module en route, à sa première étape."""
        with self._verrou:
            self.verifier(module)
            ancien = self._deroulements.get(module.nom)
            if ancien is not None and ancien.statut in ("en_cours", "alarme"):
                raise ErreurChef(f"le module « {module.nom} » est déjà en route")
            if module.exclusif:
                for autre in self._deroulements.values():
                    if autre.statut == "en_cours" and not autre.attend_go:
                        raise ErreurChef(
                            f"module exclusif « {module.nom} » : « {autre.nom} » est en plein "
                            "geste, le mettre en pause ou attendre qu'il attende un Go"
                        )
            self._deroulements[module.nom] = _Deroulement(module)
            journal.info("Module « %s » lancé (%d étapes)", module.nom, len(module.etapes))
            self._noter()

    def reprendre_cycle(self, modules: Iterable[Module]) -> list[str]:
        """Après une coupure : remet les modules du carnet à l'étape où ils étaient.

        Chaque module refera cette étape depuis le début, après un Go de Karulium.
        Rend les noms des modules repris.
        """
        if self._carnet is None:
            return []
        etat = self._carnet.lire()
        if etat is None:
            return []
        par_nom = {module.nom: module for module in modules}
        repris = []
        with self._verrou:
            for note in etat.get("modules", []):
                if note["statut"] not in ("en_cours", "alarme"):
                    continue
                module = par_nom.get(note["module"])
                if module is None:
                    raise ErreurChef(f"carnet : module « {note['module']} » inconnu du programme")
                self.verifier(module)
                deroulement = _Deroulement(
                    module,
                    numero=module.numero(note["etape"]),
                    go_obligatoire=True,
                    memoire=dict(note.get("memoire") or {}),
                )
                if note.get("alarme"):
                    deroulement.statut = "alarme"
                    deroulement.alarme = Alarme(**note["alarme"])
                conflit = self._zones.reserver(note.get("zones", []), module.nom)
                if conflit is not None:
                    raise ErreurChef(
                        f"carnet : la zone « {conflit[0]} » est notée pour « {module.nom} » "
                        f"et pour « {conflit[1]} »"
                    )
                self._deroulements[module.nom] = deroulement
                repris.append(module.nom)
                journal.warning(
                    "Reprise après coupure : module « %s » à l'étape « %s », attend le Go",
                    module.nom,
                    note["etape"],
                )
            self._noter()
        return repris

    # ------------------------------------------------------------ ordres de Karulium

    def donner_go(self, nom: str) -> None:
        with self._verrou:
            deroulement = self._trouver(nom)
            exclusif = self._exclusif_actif()
            if exclusif is not None and exclusif is not deroulement:
                raise ErreurChef(f"le module « {nom} » attend la fin de « {exclusif.nom} »")
            if not deroulement.attend_go:
                raise ErreurChef(f"le module « {nom} » n'attend pas de Go")
            empeche = self.refus_go()
            if empeche is not None:
                journal.warning("Go pour « %s » refusé : %s", nom, empeche)
                raise ErreurChef(f"Go refusé : {empeche}")
            deroulement.go_recu = True
            journal.info("Go donné à « %s » (étape « %s »)", nom, deroulement.etape.nom)
            self._noter()

    def pause(self) -> None:
        with self._verrou:
            if self._en_pause:
                return
            self._en_pause = True
            journal.warning("Pause de la machine")
            for deroulement in self._deroulements.values():
                if deroulement.statut == "en_cours":
                    deroulement.mis_en_pause = True
                    self._appeler(deroulement, deroulement.module.pauser, "la pause")
            self._noter()

    def reprendre(self) -> None:
        with self._verrou:
            if not self._en_pause:
                return
            self._en_pause = False
            # Le temps de la pause ne compte pas dans les délais.
            self._dernier = self._horloge()
            journal.info("Reprise de la machine")
            for deroulement in self._deroulements.values():
                if deroulement.mis_en_pause:
                    deroulement.mis_en_pause = False
                    if deroulement.statut == "en_cours":
                        self._appeler(deroulement, deroulement.module.reprendre, "la reprise")
            self._noter()

    def acquitter(self, nom: str) -> None:
        """Karulium a vu l'alarme et corrigé : l'étape sera refaite après un nouveau Go."""
        with self._verrou:
            deroulement = self._trouver(nom)
            if deroulement.statut != "alarme":
                raise ErreurChef(f"le module « {nom} » n'est pas en alarme")
            journal.info("Alarme de « %s » acquittée", nom)
            deroulement.statut = "en_cours"
            deroulement.alarme = None
            deroulement.go_obligatoire = True
            deroulement.go_recu = False
            deroulement.temps_etape = 0.0
            self._changer_phase(deroulement, "go")

    def abandonner(self, nom: str) -> None:
        """Arrête le module pour de bon et libère ses zones.

        Avant, vérifier sur place que ses axes ont bien quitté ces zones.
        """
        with self._verrou:
            deroulement = self._trouver(nom)
            if deroulement.statut not in ("en_cours", "alarme"):
                raise ErreurChef(f"le module « {nom} » n'est pas en route")
            if deroulement.statut == "en_cours":
                self._appeler(deroulement, deroulement.module.arreter, "l'arrêt")
            zones = self._zones.tenues_par(nom)
            self._zones.liberer_tout(nom)
            deroulement.statut = "abandonne"
            deroulement.attend = ""
            journal.warning(
                "Module « %s » abandonné à l'étape « %s »%s",
                nom,
                deroulement.etape.nom,
                f", zones libérées : {', '.join(zones)}" if zones else "",
            )
            self._noter()

    # ------------------------------------------------------------ ce qu'on sait

    def memoriser(self, nom: str, **valeurs: Any) -> None:
        """Garde des valeurs du module (seau en cours...) dans le carnet, pour la reprise."""
        with self._verrou:
            deroulement = self._trouver(nom)
            try:
                json.dumps(valeurs)
            except (TypeError, ValueError):
                raise ErreurChef(
                    f"module « {nom} » : mémoire impossible à noter (textes et nombres seulement)"
                ) from None
            deroulement.memoire.update(valeurs)
            self._noter()

    def memoire(self, nom: str) -> dict[str, Any]:
        with self._verrou:
            return dict(self._trouver(nom).memoire)

    @property
    def en_pause(self) -> bool:
        return self._en_pause

    @property
    def dernier_tour(self) -> float | None:
        """Heure (horloge du chef) du dernier tour : sert au chien de garde (chef figé ?)."""
        return self._dernier

    def etat(self) -> EtatChef:
        with self._verrou:
            exclusif = self._exclusif_actif()
            modules = tuple(
                EtatModule(
                    module=d.nom,
                    statut=d.statut,
                    etape=d.etape.nom,
                    numero=d.numero + 1,
                    nombre_etapes=len(d.module.etapes),
                    phase=d.phase,
                    attend=self._attente(d, exclusif),
                    zones=tuple(self._zones.tenues_par(d.nom)),
                    alarme=d.alarme,
                    attend_zone=d.attend_zone if d.statut == "en_cours" else "",
                )
                for d in self._deroulements.values()
            )
            return EtatChef(
                en_pause=self._en_pause, modules=modules, go_empeche=self.refus_go() or ""
            )

    @staticmethod
    def _attente(d: _Deroulement, exclusif: _Deroulement | None) -> str:
        if d.statut == "en_cours" and exclusif is not None and exclusif is not d:
            return f"fin de « {exclusif.nom} »"
        return ATTENTE_GO if d.attend_go else d.attend

    def _exclusif_actif(self) -> _Deroulement | None:
        """Le module exclusif en route (ou en alarme), s'il y en a un."""
        for d in self._deroulements.values():
            if d.module.exclusif and d.statut in ("en_cours", "alarme"):
                return d
        return None

    # ------------------------------------------------------------ fonctionnement

    def avancer(self) -> None:
        """Un tour : chaque module en route regarde ses conditions et avance s'il peut."""
        with self._verrou:
            maintenant = self._horloge()
            ecoule = 0.0 if self._dernier is None else max(maintenant - self._dernier, 0.0)
            self._dernier = maintenant
            exclusif = self._exclusif_actif()
            if self._jeu is not None:
                retard = self._jeu.retard(maintenant)
                if retard is not None:
                    self._reculer(retard)
            for deroulement in self._ordre():
                # Une alarme d'un module peut mettre les autres en pause pendant ce tour.
                if self._en_pause:
                    return
                if exclusif is not None and deroulement is not exclusif:
                    continue
                if deroulement.statut == "en_cours":
                    self._avancer_module(deroulement, ecoule)

    def _avancer_module(self, d: _Deroulement, ecoule: float) -> None:
        d.temps_phase += ecoule
        d.temps_etape += ecoule
        etape = d.etape
        try:
            if d.phase == "go":
                if d.attend_go:
                    d.attend = ATTENTE_GO
                    return
                self._changer_phase(d, "entree")
            if d.phase == "entree":
                if not self._peut_entrer(d):
                    self._verifier_delai(d, etape.attente_entree_max, f"attente de : {d.attend}")
                    return
                journal.info("« %s » : étape « %s »", d.nom, etape.nom)
                if etape.action is not None:
                    etape.action()
                self._changer_phase(d, "fin")
            for surveillance in d.module.surveillances:
                if not surveillance.test():
                    self._alarme(
                        d, f"plus tenu : {surveillance.texte}", surveillance.quoi_faire or None
                    )
                    return
            if etape.fin is None or etape.fin.test():
                self._finir_etape(d)
                return
            d.attend = etape.fin.texte
            self._verifier_delai(d, etape.delai_max, f"pas atteint : {etape.fin.texte}")
        except ErreurEtape as erreur:
            self._alarme(d, str(erreur), erreur.quoi_faire or None)
        except Exception as erreur:
            # Erreur imprévue du code d'un module (ou capteur muet) : alarme, le reste continue.
            journal.exception("« %s », étape « %s » : erreur", d.nom, etape.nom)
            quoi_faire = pour_erreur(erreur)
            if quoi_faire is None:
                quoi_faire = f"{d.etape.quoi_faire} {ERREUR_PROGRAMME}"
            self._alarme(d, f"erreur : {erreur}", quoi_faire)

    def _peut_entrer(self, d: _Deroulement) -> bool:
        for condition in (*self.conditions_generales, *d.etape.entree):
            if not condition.test():
                d.attend = condition.texte
                d.attend_zone = ""
                return False
        nouvelles = self._zones_voulues(d)
        conflit = self._zones.reserver(d.etape.reserver, d.nom)
        if conflit is not None:
            zone, tenant = conflit
            d.attend = f"zone « {zone} » libre (tenue par « {tenant} »)"
            d.attend_zone = zone
            return False
        d.attend = ""
        d.attend_zone = ""
        if self._jeu is not None and nouvelles:
            ecart = self._jeu.passage(d.nom, nouvelles, self._horloge())
            if ecart is not None:
                self._reculer(ecart)
            else:
                self._verifier_fin_programme()
        return True

    def _verifier_delai(self, d: _Deroulement, nom_delai: str | None, quoi: str) -> None:
        if nom_delai is None:
            return
        delai = self._durees[nom_delai]
        if d.temps_phase > delai:
            raise ErreurEtape(f"trop long ({delai:g} s), {quoi}")

    def _finir_etape(self, d: _Deroulement) -> None:
        etape = d.etape
        self._zones.liberer(etape.liberer, d.nom)
        journal.info("« %s » : étape « %s » finie en %.1f s", d.nom, etape.nom, d.temps_etape)
        d.attend = ""
        suivante = etape.ensuite() if etape.ensuite is not None else None
        if suivante is None and d.numero + 1 >= len(d.module.etapes):
            d.statut = "fini"
            self._zones.liberer_tout(d.nom)
            journal.info("Module « %s » fini", d.nom)
            self._noter()
            return
        d.numero = d.numero + 1 if suivante is None else d.module.numero(suivante)
        d.go_obligatoire = False
        d.go_recu = False
        d.temps_etape = 0.0
        self._changer_phase(d, "go")

    def _changer_phase(self, d: _Deroulement, phase: Phase) -> None:
        d.phase = phase
        d.temps_phase = 0.0
        self._noter()

    def _alarme(self, d: _Deroulement, message: str, quoi_faire: str | None = None) -> None:
        d.statut = "alarme"
        d.attend = ""
        d.attend_zone = ""
        self._reculer(f"alarme de « {d.nom} »")
        d.alarme = Alarme(
            module=d.nom,
            etape=d.etape.nom,
            message=message,
            quoi_faire=quoi_faire or d.etape.quoi_faire,
            date=_maintenant(),
        )
        journal.error(
            "ALARME « %s », étape « %s » : %s. Quoi faire : %s",
            d.nom,
            d.etape.nom,
            message,
            d.alarme.quoi_faire,
        )
        self._appeler(d, d.module.arreter, "l'arrêt")
        self._noter()
        for ecouteur in self.sur_alarme:
            try:
                ecouteur(d.alarme)
            except Exception:
                journal.exception("« %s » : le bilan de l'alarme a échoué", d.nom)
        if self._reglages.alarme_pause_tout:
            self.pause()

    def _appeler(self, d: _Deroulement, fonction: Callable[[], object] | None, quoi: str) -> None:
        if fonction is None:
            return
        try:
            fonction()
        except Exception:
            journal.exception("« %s » : %s a échoué", d.nom, quoi)

    def _trouver(self, nom: str) -> _Deroulement:
        if nom not in self._deroulements:
            raise ErreurChef(f"module « {nom} » pas lancé")
        return self._deroulements[nom]

    def _noter(self) -> None:
        """Écrit l'état dans le carnet (une erreur de disque n'arrête pas la machine)."""
        if self._carnet is None:
            return
        etat: dict[str, Any] = {
            "date": _maintenant(),
            "en_pause": self._en_pause,
            "modules": [
                {
                    "module": d.nom,
                    "statut": d.statut,
                    "etape": d.etape.nom,
                    "phase": d.phase,
                    "go_recu": d.go_recu,
                    "zones": self._zones.tenues_par(d.nom),
                    "alarme": asdict(d.alarme) if d.alarme is not None else None,
                    "memoire": d.memoire,
                }
                for d in self._deroulements.values()
            ],
        }
        try:
            self._carnet.ecrire(etat)
        except OSError as erreur:
            journal.error("Impossible de noter l'état du cycle : %s", erreur)
