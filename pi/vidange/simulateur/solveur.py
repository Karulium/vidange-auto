"""Solveur d'ordonnancement (tâche 23, OR-Tools CP-SAT, gratuit).

Décision « La fiabilité d'abord » (28/10/2026) : un gain de vitesse n'est gardé que s'il ne crée
aucune alerte ni aucun écart ; au moindre doute, ordre normal du chef.

1. `taches(planning)` : les étapes faites d'un planning simulé dans l'ordre normal du chef, en
   tâches. Chaque tâche a la durée de son geste (celle du simulateur, plus tard recalée sur les
   vrais temps mesurés), vient après la précédente du même module (`apres`), tient des zones, et
   garde ce qu'elle a attendu dans l'ordre normal : la fin d'une tâche d'un autre module finie au
   même instant (`attend`), sinon le même temps d'attente (`delai_s`). Le solveur ne connaît pas
   les conditions elles-mêmes : c'est pour cela que le simulateur rejoue toujours son programme.
2. `ordonner(taches, ...)` : une variable « intervalle » par tâche, « pas de chevauchement » par
   zone (une zone est tenue d'une tâche à la dernière qui la tient encore, sans trou), « après »
   par module, le temps total le plus court. Une tâche qui demande le Go est un point d'arrêt :
   le solveur n'ordonne que ce qui vient avant (il ne décide jamais à la place de Karulium).
   Temps de calcul limité par `solveur → temps_max_s` : pas de solution = ordre normal.
3. `Ordonnancement.programme()` : pour chaque zone tenue par plusieurs modules, l'ordre de passage
   et l'heure prévue. C'est tout ce que le chef en reçoit (vidange.chef.programme).
4. `comparer(jouer, solveur)` : joue l'ordre normal, ordonne, rejoue le programme trouvé sur le
   simulateur et le vérifie (`verifier_programme`) ; la moindre zone tenue deux fois, règle
   refusée, alarme ou écart = programme rejeté, ordre normal du chef, et le journal dit pourquoi.
   `en_texte()` dit le gain (`vidange-simulateur cycle --solveur`).
"""

import math
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from vidange.chef import Passage, Programme
from vidange.journal import donner_journal
from vidange.reglages import Solveur
from vidange.simulateur.planning import Planning, duree_lisible

journal = donner_journal("solveur")

# Deux heures du simulateur à moins de ça (s) sont le même instant.
MEME_INSTANT_S = 1e-6


@dataclass(frozen=True)
class Tache:
    module: str
    etape: str
    # La combientième fois le module fait cette étape (1, 2...) : une étape qui se répète (un
    # seau, puis un autre) donne une tâche à chaque fois.
    rang: int
    # Durée du geste (s) : de l'action à la condition de fin.
    duree_s: float
    # Zones tenues pendant le geste.
    zones: tuple[str, ...]
    # Tâche qui doit être finie avant (`nom`), ou None pour la première du module.
    apres: str | None
    demande_go: bool
    # Tâches d'autres modules finies au moment où celle-ci a pu partir (dans l'ordre normal, elle
    # attendait une condition).
    attend: tuple[str, ...] = ()
    # Attente d'une condition sans tâche connue qui la libère (s, après `apres`).
    delai_s: float = 0.0
    # Heure de l'action dans l'ordre normal (s).
    heure_s: float = 0.0

    @property
    def nom(self) -> str:
        return f"{self.module}.{self.etape}#{self.rang}"


def taches(planning: Planning) -> list[Tache]:
    """Les étapes finies du planning, en tâches pour le solveur."""
    finies = [ligne for ligne in planning.lignes if ligne.fin is not None]
    noms = []
    rangs: Counter[tuple[str, str]] = Counter()
    for ligne in finies:
        rangs[(ligne.module, ligne.etape)] += 1
        noms.append(f"{ligne.module}.{ligne.etape}#{rangs[(ligne.module, ligne.etape)]}")
    resultat = []
    precedente: dict[str, str] = {}
    for nom, ligne in zip(noms, finies, strict=True):
        assert ligne.fin is not None and ligne.action is not None
        attend: tuple[str, ...] = ()
        delai = 0.0
        if ligne.attend_condition:
            attend = tuple(
                autre_nom
                for autre_nom, autre in zip(noms, finies, strict=True)
                if autre.module != ligne.module
                and autre.fin is not None
                and abs(autre.fin - ligne.action) <= MEME_INSTANT_S
                # Pas celle qui tenait la zone attendue : c'est au solveur de choisir.
                and not set(autre.zones) & {*ligne.zones, *ligne.zones_attendues}
            )
            if not attend:
                delai = ligne.attente_entree
        tache = Tache(
            module=ligne.module,
            etape=ligne.etape,
            rang=int(nom.rsplit("#", 1)[1]),
            duree_s=ligne.geste,
            zones=ligne.zones,
            apres=precedente.get(ligne.module),
            demande_go=ligne.go is not None,
            attend=attend,
            delai_s=delai,
            heure_s=ligne.action,
        )
        precedente[ligne.module] = nom
        resultat.append(tache)
    return resultat


def avant_le_go(liste: list[Tache]) -> list[Tache]:
    """Les tâches qui viennent avant le prochain Go : pour chaque module, tout ce qui précède sa
    première tâche qui demande le Go, sans ce qui dépend d'une tâche coupée."""
    connues = {tache.nom for tache in liste}
    coupees = {tache.nom for tache in liste if tache.demande_go}
    change = True
    while change:
        change = False
        for tache in liste:
            if tache.nom in coupees:
                continue
            avant = [nom for nom in (tache.apres, *tache.attend) if nom is not None]
            if any(nom in coupees or nom not in connues for nom in avant):
                coupees.add(tache.nom)
                change = True
    return [tache for tache in liste if tache.nom not in coupees]


@dataclass(frozen=True)
class Ordonnancement:
    # Les tâches ordonnées (celles d'avant le prochain Go).
    taches: tuple[Tache, ...]
    # Heure de début (action) de chaque tâche, nom → s.
    debuts: dict[str, float]
    temps_total_s: float
    # Vrai : le plus court possible (prouvé) ; faux : le meilleur trouvé dans temps_max_s.
    optimal: bool
    duree_calcul_s: float
    # Zones tenues par plusieurs modules : celles où l'ordre de passage compte.
    zones_partagees: tuple[str, ...] = ()

    def programme(self) -> Programme:
        """L'ordre de passage (et l'heure prévue) dans chaque zone partagée."""
        passages: dict[str, list[Passage]] = {}
        for zone, module, debut, _ in _tenues(list(self.taches)):
            if zone in self.zones_partagees:
                passages.setdefault(zone, []).append(Passage(module, self.debuts[debut.nom]))
        return Programme(
            passages={
                zone: tuple(sorted(liste, key=lambda passage: passage.heure_s))
                for zone, liste in passages.items()
            },
            temps_total_s=self.temps_total_s,
        )


def _tenues(liste: list[Tache]) -> list[tuple[str, str, Tache, Tache]]:
    """Chaque zone tenue d'affilée par un module : (zone, module, première tâche, dernière).

    Un module garde une zone entre deux étapes qui la tiennent (il attend ses conditions en la
    gardant) : c'est une seule tenue, sans trou où un autre module pourrait passer."""
    resultat = []
    par_module: dict[str, list[Tache]] = {}
    for tache in liste:
        par_module.setdefault(tache.module, []).append(tache)
    for module, siennes in par_module.items():
        ouvertes: dict[str, tuple[Tache, Tache]] = {}
        for tache in siennes:
            for zone in [zone for zone in ouvertes if zone not in tache.zones]:
                premiere, derniere = ouvertes.pop(zone)
                resultat.append((zone, module, premiere, derniere))
            for zone in tache.zones:
                premiere = ouvertes[zone][0] if zone in ouvertes else tache
                ouvertes[zone] = (premiere, tache)
        for zone, (premiere, derniere) in ouvertes.items():
            resultat.append((zone, module, premiere, derniere))
    return resultat


def _en_pas(secondes: float, pas_s: float) -> int:
    """Secondes en nombre de pas, arrondi au-dessus (jamais plus court que le vrai geste)."""
    return max(math.ceil(secondes / pas_s - 1e-9), 0)


def ordonner(liste: list[Tache], temps_max_s: float, pas_s: float) -> Ordonnancement | None:
    """L'ordre le plus court des tâches d'avant le prochain Go. None : pas de solution trouvée
    dans `temps_max_s` (le chef garde son ordre normal)."""
    from ortools.sat.python import cp_model

    gardees = avant_le_go(liste)
    tenues = _tenues(gardees)
    modules_par_zone: dict[str, set[str]] = {}
    for zone, module, _, _ in tenues:
        modules_par_zone.setdefault(zone, set()).add(module)
    partagees = tuple(
        sorted(zone for zone, modules in modules_par_zone.items() if len(modules) > 1)
    )
    if not gardees:
        return Ordonnancement((), {}, 0.0, True, 0.0, partagees)
    durees = {tache.nom: _en_pas(tache.duree_s, pas_s) for tache in gardees}
    delais = {tache.nom: _en_pas(tache.delai_s, pas_s) for tache in gardees}
    horizon = sum(durees.values()) + sum(delais.values()) + 1
    modele = cp_model.CpModel()
    debuts, fins = {}, {}
    for tache in gardees:
        nom = tache.nom
        debuts[nom] = modele.new_int_var(0, horizon, f"debut {nom}")
        fins[nom] = modele.new_int_var(0, horizon, f"fin {nom}")
        modele.new_interval_var(debuts[nom], durees[nom], fins[nom], f"geste {nom}")
    for tache in gardees:
        nom = tache.nom
        if tache.apres is not None:
            modele.add(debuts[nom] >= fins[tache.apres] + delais[nom])
        else:
            modele.add(debuts[nom] >= delais[nom])
        for autre in tache.attend:
            modele.add(debuts[nom] >= fins[autre])
        # Indice : l'ordre normal (le solveur part de lui pour chercher mieux).
        modele.add_hint(debuts[nom], _en_pas(tache.heure_s, pas_s))
    par_zone: dict[str, list] = {}
    for zone, module, premiere, derniere in tenues:
        if zone not in partagees:
            continue
        taille = modele.new_int_var(0, horizon, f"tenue {zone} {module} {premiere.nom}")
        par_zone.setdefault(zone, []).append(
            modele.new_interval_var(
                debuts[premiere.nom], taille, fins[derniere.nom], f"zone {zone} {premiere.nom}"
            )
        )
    for intervalles in par_zone.values():
        modele.add_no_overlap(intervalles)
    total = modele.new_int_var(0, horizon, "temps total")
    modele.add_max_equality(total, list(fins.values()))
    modele.minimize(total)
    solveur = cp_model.CpSolver()
    solveur.parameters.max_time_in_seconds = temps_max_s
    depart = time.monotonic()
    statut = solveur.solve(modele)
    if statut not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        journal.warning(
            "Solveur : pas de solution en %g s (%s) : ordre normal du chef",
            temps_max_s,
            solveur.status_name(statut),
        )
        return None
    optimal = statut == cp_model.OPTIMAL
    meilleur = solveur.value(total)
    valeurs = {nom: solveur.value(debut) for nom, debut in debuts.items()}
    # 2e temps : au même temps total, chaque tâche au plus tôt (le chef fait partir chaque étape
    # dès qu'il peut : les heures prévues doivent être celles-là).
    reste = temps_max_s - (time.monotonic() - depart)
    if reste > 0:
        modele.add(total <= meilleur)
        modele.minimize(sum(debuts.values()))
        modele.clear_hints()
        for nom, debut in debuts.items():
            modele.add_hint(debut, valeurs[nom])
        solveur.parameters.max_time_in_seconds = reste
        if solveur.solve(modele) in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            valeurs = {nom: solveur.value(debut) for nom, debut in debuts.items()}
    duree = time.monotonic() - depart
    return Ordonnancement(
        taches=tuple(gardees),
        debuts={nom: valeur * pas_s for nom, valeur in valeurs.items()},
        temps_total_s=meilleur * pas_s,
        optimal=optimal,
        duree_calcul_s=duree,
        zones_partagees=partagees,
    )


def verifier_programme(normal: Planning, rejoue: Planning) -> list[str]:
    """Pourquoi le programme rejoué par le simulateur est rejeté (vide : accepté)."""
    raisons = []
    if rejoue.probleme:
        raisons.append(f"le cycle rejoué s'est arrêté : {rejoue.probleme}")
    if rejoue.recul_programme:
        raisons.append(f"le chef a quitté le programme : {rejoue.recul_programme}")
    raisons += zones_tenues_deux_fois(rejoue)
    faites_normal = _faites(normal)
    faites_rejoue = _faites(rejoue)
    if faites_normal != faites_rejoue:
        raisons.append(
            f"le cycle rejoué n'a pas fait les mêmes étapes ({sum(faites_rejoue.values())} "
            f"contre {sum(faites_normal.values())} dans l'ordre normal)"
        )
    if rejoue.temps_total > normal.temps_total + MEME_INSTANT_S:
        raisons.append(
            f"plus long que l'ordre normal ({duree_lisible(rejoue.temps_total)} contre "
            f"{duree_lisible(normal.temps_total)})"
        )
    return raisons


def _faites(planning: Planning) -> Counter[tuple[str, str]]:
    return Counter(
        (ligne.module, ligne.etape) for ligne in planning.lignes if ligne.fin is not None
    )


def zones_tenues_deux_fois(planning: Planning) -> list[str]:
    """Les zones tenues par deux modules en même temps dans un planning (le chef l'empêche :
    c'est une vérification de plus)."""
    par_zone: dict[str, list[tuple[float, float, str]]] = {}
    for ligne in planning.lignes:
        if ligne.action is None or ligne.fin is None:
            continue
        for zone in ligne.zones:
            par_zone.setdefault(zone, []).append((ligne.action, ligne.fin, ligne.module))
    raisons = []
    for zone, intervalles in par_zone.items():
        intervalles.sort()
        fin_max, tenant = -math.inf, ""
        for debut, fin, module in intervalles:
            if module != tenant and debut < fin_max - MEME_INSTANT_S:
                raisons.append(
                    f"zone « {zone} » tenue par « {tenant} » et « {module} » en même temps "
                    f"(à {debut:.1f} s)"
                )
                break
            if fin > fin_max:
                fin_max, tenant = fin, module
    return raisons


# Joue le cycle sur un nouveau simulateur, sans programme (None) ou avec : rend le planning et
# les écarts à l'ordre du cycle (vidange.cycle.ordre ; vide : aucun).
Jouer = Callable[[Programme | None], tuple[Planning, list[str]]]


@dataclass
class Comparaison:
    """L'ordre normal du chef contre le programme du solveur, rejoué par le simulateur."""

    normal: Planning
    ordonnancement: Ordonnancement | None = None
    nombre_taches: int = 0
    rejoue: Planning | None = None
    # Pourquoi le programme est rejeté (vide : accepté).
    rejets: list[str] = field(default_factory=list)

    @property
    def accepte(self) -> bool:
        return self.rejoue is not None and not self.rejets

    @property
    def gain_s(self) -> float:
        """Temps gagné sur le cycle (s) ; 0 si le programme est rejeté."""
        if not self.accepte or self.rejoue is None:
            return 0.0
        return self.normal.temps_total - self.rejoue.temps_total

    def en_texte(self) -> str:
        lignes = ["Solveur d'ordonnancement (OR-Tools CP-SAT, tâche 23) :"]
        if self.normal.exemple:
            lignes.append(
                "  ATTENTION : réglages d'EXEMPLE, ces temps ne disent rien de la machine."
            )
        lignes.append(f"  ordre normal du chef : {duree_lisible(self.normal.temps_total)}")
        ordo = self.ordonnancement
        if ordo is not None:
            partagees = ", ".join(f"« {zone} »" for zone in ordo.zones_partagees) or "aucune"
            lignes.append(
                f"  tâches ordonnées : {len(ordo.taches)} sur {self.nombre_taches} (celles "
                f"d'avant le prochain Go) ; zones partagées entre modules : {partagees}"
            )
            sorte = "le plus court possible" if ordo.optimal else "le meilleur trouvé"
            lignes.append(
                f"  programme calculé en {duree_lisible(ordo.duree_calcul_s)} ({sorte}) : "
                f"{duree_lisible(ordo.temps_total_s)} prévues pour ces tâches"
            )
            if not ordo.zones_partagees:
                lignes.append(
                    "  aucune zone n'est attendue par deux modules : le programme ne change "
                    "l'ordre de personne"
                )
        if self.rejoue is not None:
            lignes.append(
                f"  programme rejoué par le simulateur : {duree_lisible(self.rejoue.temps_total)}"
            )
        if self.accepte:
            total = self.normal.temps_total
            pourcent = f"{100 * self.gain_s / total:.1f}".replace(".", ",") if total else "0"
            lignes.append(
                f"  programme accepté ; gain : {duree_lisible(self.gain_s)} ({pourcent} %)"
            )
        else:
            lignes.append("  programme REJETÉ, ordre normal du chef ; gain : 0,0 s")
            lignes += [f"    - {raison}" for raison in self.rejets]
        return "\n".join(lignes)


def comparer(jouer: Jouer, solveur: Solveur) -> Comparaison:
    """Ordre normal, programme du solveur, puis vérification du programme rejoué."""
    normal, ecarts = jouer(None)
    comparaison = Comparaison(normal)
    if not normal.fini or ecarts:
        comparaison.rejets = [
            f"l'ordre normal lui-même ne va pas au bout : {normal.probleme or '; '.join(ecarts)}"
        ]
        return _noter(comparaison)
    liste = taches(normal)
    comparaison.nombre_taches = len(liste)
    ordo = ordonner(liste, solveur.temps_max_s, solveur.pas_s)
    comparaison.ordonnancement = ordo
    if ordo is None:
        comparaison.rejets = [f"pas de solution en {solveur.temps_max_s:g} s"]
        return _noter(comparaison)
    rejoue, ecarts = jouer(ordo.programme())
    comparaison.rejoue = rejoue
    comparaison.rejets = verifier_programme(normal, rejoue) + [
        f"ordre du cycle pas suivi : {ecart}" for ecart in ecarts
    ]
    return _noter(comparaison)


def _noter(comparaison: Comparaison) -> Comparaison:
    if comparaison.rejets:
        journal.warning(
            "Programme du solveur rejeté, ordre normal du chef : %s", " ; ".join(comparaison.rejets)
        )
    else:
        journal.info("Programme du solveur accepté : gain %.1f s", comparaison.gain_s)
    return comparaison
