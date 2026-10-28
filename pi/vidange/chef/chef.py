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
"""

import json
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

from vidange.chef.carnet import Carnet
from vidange.chef.etapes import ErreurChef, ErreurEtape, Etape, Module
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


@dataclass(frozen=True)
class EtatChef:
    en_pause: bool
    modules: tuple[EtatModule, ...]

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
                )
                for d in self._deroulements.values()
            )
            return EtatChef(en_pause=self._en_pause, modules=modules)

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
            for deroulement in list(self._deroulements.values()):
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
        for condition in d.etape.entree:
            if not condition.test():
                d.attend = condition.texte
                return False
        conflit = self._zones.reserver(d.etape.reserver, d.nom)
        if conflit is not None:
            zone, tenant = conflit
            d.attend = f"zone « {zone} » libre (tenue par « {tenant} »)"
            return False
        d.attend = ""
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
