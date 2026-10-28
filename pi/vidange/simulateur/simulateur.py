"""Simulateur de cycle (jumeau numérique, version 0).

Le VRAI chef d'orchestre rejoue un ou plusieurs modules sur une machine imaginaire : axes
imaginaires (vitesses et accélérations de simulateur.yaml), faux capteurs de
docs/entrees-sorties.yaml qui changent quand simulateur.yaml le dit, Go de Karulium donné tout
seul après « delai_go_s ».
Le temps est simulé : une heure de cycle se rejoue en une fraction de seconde.

    with Simulateur(reglages, liste) as simulateur:
        module = module_exemple(simulateur.axes(), simulateur.materiel)
        planning = simulateur.jouer([module])
    print(planning.en_texte())

Le planning dit, pour chaque étape : quand elle commence, combien elle attend (Go, conditions,
zones), quand son geste part et finit, ce qui bouge ; et le temps total. Une alarme ou un blocage
arrête la simulation, et le planning dit pourquoi.

Les modules sont écrits comme pour la vraie machine ; ils reçoivent des axes imaginaires
(`simulateur.axes()`) à la place des vrais, et un poste du fût sur le faux matériel
(`simulateur.poste_fut()`).

Un scénario nommé de simulateur.yaml (« echange_fut »...) remplace les capteurs du départ et les
événements du haut du fichier : `Simulateur(reglages, liste, scenario="echange_fut")`.
"""

from collections.abc import Callable, Iterable
from dataclasses import replace

from vidange.chef import Chef, Condition, Etape, EtatChef, Module
from vidange.chef.chef import ATTENTE_GO
from vidange.entrees_sorties import EntreesSorties
from vidange.materiel import FausseFabrique, Materiel
from vidange.poste_fut import Pesee, PosteFut
from vidange.reglages import EvenementSimule, Reglages
from vidange.simulateur.axes import AxesSimulees, EtatAxes
from vidange.simulateur.planning import LignePlanning, Planning

# Nombre de tours du chef au même instant avant de conclure qu'il tourne en rond.
TOURS_MAX_AU_MEME_INSTANT = 1000


class ErreurSimulation(Exception):
    """Simulation impossible : capteur ou étape inconnus dans simulateur.yaml..."""


class Simulateur:
    def __init__(
        self, reglages: Reglages, liste: EntreesSorties, scenario: str | None = None
    ) -> None:
        self._tous = reglages
        self._reglages = reglages.simulateur
        self._machine = reglages.machine
        if scenario is None:
            depart, self._evenements = self._reglages.capteurs_actionnes, self._reglages.evenements
        elif scenario in self._reglages.scenarios:
            choisi = self._reglages.scenarios[scenario]
            depart, self._evenements = choisi.capteurs_actionnes, choisi.evenements
        else:
            connus = ", ".join(self._reglages.scenarios) or "aucun"
            raise ErreurSimulation(
                f"scénario « {scenario} » absent de simulateur.yaml (scénarios : {connus})"
            )
        self._poste: PosteFut | None = None
        self.temps = 0.0
        self.fabrique = FausseFabrique(liste)
        self.materiel = Materiel(liste, self.fabrique)
        self._axes = EtatAxes(reglages.machine, self._reglages, horloge=self._horloge)
        # Le même chef que sur la machine, à l'heure du simulateur, sans carnet.
        self.chef = Chef(reglages.machine, reglages.programme.chef, horloge=self._horloge)
        self._modules: dict[str, Module] = {}
        self._en_cours: dict[str, LignePlanning] = {}
        self._lignes: list[LignePlanning] = []
        # Go prévus : (module, n° d'étape) → heure.
        self._go: dict[tuple[str, int], float] = {}
        # Changements de capteurs prévus : (heure, événement), et ceux déjà faits (heure, texte).
        self._a_venir: list[tuple[float, EvenementSimule]] = []
        self._faits: list[tuple[float, str]] = []
        self._joue = False
        for capteur in depart:
            self._actionner(capteur, True, "capteurs_actionnes")

    def _horloge(self) -> float:
        return self.temps

    def axes(self) -> AxesSimulees:
        """Axes imaginaires pour un module (un objet par module, comme les vrais Axes)."""
        return AxesSimulees(self._axes)

    @property
    def etat_axes(self) -> EtatAxes:
        """Les positions de la machine imaginaire (pour la griffe, qui va à des positions
        calculées : vidange.griffe.simulation)."""
        return self._axes

    @property
    def reglages(self) -> Reglages:
        return self._tous

    def poste_fut(self) -> PosteFut:
        """Le poste du fût sur le faux matériel, à l'heure du simulateur (toujours le même)."""
        if self._machine.poste_fut is None:
            raise ErreurSimulation("machine.yaml n'a pas de partie « poste_fut »")
        if self._poste is None:
            self._poste = PosteFut(
                self._machine.poste_fut,
                self.materiel,
                horloge=self._horloge,
                lecture_directe=True,
            )
        return self._poste

    # ------------------------------------------------------------ jouer

    def jouer(self, modules: Iterable[Module]) -> Planning:
        """Lance les modules ensemble et rejoue le cycle jusqu'au bout (ou jusqu'au problème)."""
        if self._joue:
            raise ErreurSimulation("un simulateur ne rejoue qu'un cycle : en créer un nouveau")
        self._joue = True
        modules = list(modules)
        if not modules:
            raise ErreurSimulation("aucun module à simuler")
        self._verifier_evenements(modules)
        for evenement in self._evenements:
            if evenement.apres is None:
                self._a_venir.append((evenement.attente_s, evenement))
        for module in modules:
            suivi = self._suivre(module)
            self._modules[module.nom] = suivi
            self.chef.lancer(suivi)
            self._commencer_etape(module.nom, 0)
        probleme = self._boucle()
        return Planning(
            modules=[module.nom for module in modules],
            lignes=sorted(self._lignes, key=lambda ligne: ligne.debut),
            temps_total=self.temps,
            evenements=list(self._faits),
            probleme=probleme,
            exemple=self._reglages.exemple,
        )

    def _boucle(self) -> str:
        """Fait tourner le chef ; rend "" si tout est fini, sinon ce qui a arrêté le cycle."""
        tours_sur_place = 0
        while True:
            avant = _photo(self.chef.etat())
            self._faire_evenements()
            self._donner_les_go()
            self.chef.avancer()
            etat = self.chef.etat()
            self._observer(etat)
            for module in etat.modules:
                if module.alarme is not None:
                    return (
                        f"alarme de « {module.module} », étape « {module.etape} » : "
                        f"{module.alarme.message}. Quoi faire : {module.alarme.quoi_faire}"
                    )
            if all(module.statut == "fini" for module in etat.modules):
                return ""
            if _photo(etat) != avant:
                # Quelque chose a changé : un autre tour au même instant (une étape finie
                # laisse partir la suivante tout de suite).
                tours_sur_place += 1
                if tours_sur_place > TOURS_MAX_AU_MEME_INSTANT:
                    return "le chef change d'état sans cesse au même instant (module mal écrit ?)"
                continue
            tours_sur_place = 0
            if self.temps >= self._reglages.duree_max_s:
                attentes = " ; ".join(
                    f"« {module.module} » (étape « {module.etape} ») attend : "
                    f"{module.attend or 'la fin de son geste'}"
                    for module in etat.modules
                    if module.statut == "en_cours"
                )
                duree_max = self._reglages.duree_max_s
                return f"bloqué au bout de duree_max_s ({duree_max:g} s) : {attentes}"
            self.temps = self._prochain_instant()

    def _prochain_instant(self) -> float:
        """Le prochain événement connu, sans dépasser « pas_max_s » ni « duree_max_s »."""
        candidats = [self.temps + self._reglages.pas_max_s, self._reglages.duree_max_s]
        candidats += [heure for heure in self._go.values() if heure > self.temps]
        candidats += [heure for heure, _ in self._a_venir if heure > self.temps]
        arrivee = self._axes.prochaine_arrivee()
        if arrivee is not None and arrivee > self.temps:
            candidats.append(arrivee)
        return min(candidats)

    def _observer(self, etat: EtatChef) -> None:
        for module in etat.modules:
            if module.statut != "en_cours" or module.module not in self._en_cours:
                continue
            ligne = self._en_cours[module.module]
            if module.attend == ATTENTE_GO:
                cle = (module.module, ligne.numero)
                if cle not in self._go:
                    self._go[cle] = self.temps + self._reglages.delai_go_s
            elif module.phase == "entree" and module.attend and module.attend not in ligne.attentes:
                ligne.attentes.append(module.attend)

    def _donner_les_go(self) -> None:
        attendent = set(self.chef.etat().attendent_go)
        for (nom, numero), heure in self._go.items():
            ligne = self._en_cours.get(nom)
            if heure > self.temps or nom not in attendent or ligne is None:
                continue
            if ligne.numero == numero and ligne.go is None:
                self.chef.donner_go(nom)
                ligne.go = self.temps

    def _faire_evenements(self) -> None:
        restent = []
        for heure, evenement in self._a_venir:
            if heure > self.temps:
                restent.append((heure, evenement))
                continue
            if evenement.capteur is not None:
                self._actionner(evenement.capteur, bool(evenement.actionne), "evenements")
                etat = "actionné" if evenement.actionne else "relâché"
                self._faits.append((self.temps, f"capteur « {evenement.capteur} » {etat}"))
            else:
                self._faits.append((self.temps, self._peser(evenement)))
        self._a_venir = restent

    def _peser(self, evenement: EvenementSimule) -> str:
        """La fausse pesée change : un poids (kg, comme lu par le poste) ou prise débranchée."""
        nom = evenement.pesee
        assert nom is not None
        if self._machine.poste_fut is None:
            raise ErreurSimulation("simulateur.yaml, evenements : pesée sans « poste_fut »")
        try:
            self.fabrique.debrancher(nom, evenement.debranchee)
            if evenement.kg is not None:
                pesee = Pesee(self._machine.poste_fut.pesee, self.materiel)
                self.fabrique.regler_pesee(nom, pesee.brut(evenement.kg))
        except KeyError:
            raise ErreurSimulation(
                f"simulateur.yaml, evenements : « {nom} » n'est pas une pesée "
                "de docs/entrees-sorties.yaml"
            ) from None
        if evenement.debranchee:
            return f"pesée « {nom} » débranchée"
        return f"pesée « {nom} » : {evenement.kg:g} kg"

    def _actionner(self, capteur: str, actionne: bool, ou: str) -> None:
        try:
            self.fabrique.actionner(capteur, actionne)
        except KeyError:
            raise ErreurSimulation(
                f"simulateur.yaml, {ou} : « {capteur} » n'est pas une entrée tout-ou-rien "
                "de docs/entrees-sorties.yaml"
            ) from None

    def _verifier_evenements(self, modules: list[Module]) -> None:
        etapes = {f"{module.nom}.{etape.nom}" for module in modules for etape in module.etapes}
        erreurs = [
            f"simulateur.yaml, evenements n° {numero} : étape « {evenement.apres} » inconnue "
            "(écrire module.etape)"
            for numero, evenement in enumerate(self._evenements, start=1)
            if evenement.apres is not None and evenement.apres not in etapes
        ]
        if erreurs:
            raise ErreurSimulation(" ; ".join(erreurs))

    # ------------------------------------------------------------ suivi des étapes

    def _suivre(self, module: Module) -> Module:
        """Le même module, dont chaque action et chaque fin notent leur heure dans le planning."""
        etapes = []
        for numero, etape in enumerate(module.etapes):
            fin = etape.fin
            if fin is not None:
                fin = replace(fin, test=self._fin_suivie(module.nom, numero, fin))
            action = self._action_suivie(module.nom, numero, etape)
            ensuite = self._ensuite_suivi(module, numero, etape)
            etapes.append(replace(etape, action=action, fin=fin, ensuite=ensuite))
        return replace(module, etapes=tuple(etapes))

    def _ensuite_suivi(self, module: Module, numero: int, etape: Etape) -> Callable[[], str | None]:
        """Appelée par le chef à la fin de l'étape : la ligne de l'étape suivante commence."""

        def ensuite() -> str | None:
            self._finir_etape(module.nom, numero)
            suivante = etape.ensuite() if etape.ensuite is not None else None
            if suivante is not None:
                self._commencer_etape(module.nom, module.numero(suivante))
            elif numero + 1 < len(module.etapes):
                self._commencer_etape(module.nom, numero + 1)
            return suivante

        return ensuite

    def _action_suivie(self, nom: str, numero: int, etape: Etape) -> Callable[[], None]:
        def action() -> None:
            ligne = self._en_cours[nom]
            ligne.action = self.temps
            ligne.zones = next(m.zones for m in self.chef.etat().modules if m.module == nom)
            deja = len(self._axes.mouvements)
            if etape.action is not None:
                etape.action()
            ligne.mouvements.extend(self._axes.mouvements[deja:])
            if etape.fin is None:
                self._finir_etape(nom, numero)

        return action

    def _fin_suivie(self, nom: str, numero: int, fin: Condition) -> Callable[[], bool]:
        def test() -> bool:
            if not fin.test():
                return False
            self._finir_etape(nom, numero)
            return True

        return test

    def _finir_etape(self, nom: str, numero: int) -> None:
        ligne = self._en_cours[nom]
        if ligne.fin is None:
            ligne.fin = self.temps

    def _commencer_etape(self, nom: str, numero: int) -> None:
        module = self._modules[nom]
        etape = module.etapes[numero]
        ligne = LignePlanning(
            module=nom,
            etape=etape.nom,
            numero=numero + 1,
            nombre_etapes=len(module.etapes),
            debut=self.temps,
        )
        self._lignes.append(ligne)
        self._en_cours[nom] = ligne
        for evenement in self._evenements:
            if evenement.apres == f"{nom}.{etape.nom}":
                self._a_venir.append((self.temps + evenement.attente_s, evenement))

    # ------------------------------------------------------------ fin

    def fermer(self) -> None:
        self.materiel.fermer()

    def __enter__(self) -> "Simulateur":
        return self

    def __exit__(self, *_: object) -> None:
        self.fermer()


def _photo(etat: EtatChef) -> tuple:
    return tuple(
        (module.module, module.statut, module.numero, module.phase, module.attend)
        for module in etat.modules
    )
