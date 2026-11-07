"""Solveur d'ordonnancement (tâche 23) : tâches, OR-Tools CP-SAT, jeu par le chef, vérification.

Les modules de ces essais sont des modules « minute » : chaque étape attend un temps simulé, en
tenant ou non une zone d'exemple de machine.yaml. Ils ne décrivent aucun geste de la machine.
"""

import pytest

from vidange.chef import Condition, ErreurEtape, Etape, Module, Passage, Programme
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.reglages import Reglages, charger_reglages
from vidange.simulateur import ErreurSimulation, Simulateur, comparer, ordonner, taches
from vidange.simulateur.outil import main
from vidange.simulateur.planning import LignePlanning, Planning
from vidange.simulateur.solveur import (
    Comparaison,
    Tache,
    avant_le_go,
    verifier_programme,
    zones_tenues_deux_fois,
)

from .conftest import DOSSIER_PI
from .test_reglages import erreur_de, remplacer

LISTE = DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"
ZONE = "exemple_zone_a"
QUOI_FAIRE = "regarder le module d'essai"
# Un scénario sans capteur ni événement (ceux du haut de simulateur.yaml suivent l'exemple).
SCENARIO = "dosage_mycelium"


def reglages_actifs(actif: bool = True) -> Reglages:
    reglages = charger_reglages(DOSSIER_PI / "reglages")
    assert reglages.machine.solveur is not None
    solveur = reglages.machine.solveur.model_copy(update={"actif": actif})
    machine = reglages.machine.model_copy(update={"solveur": solveur})
    return reglages.model_copy(update={"machine": machine})


def module_minute(
    simulateur: Simulateur,
    nom: str,
    gestes: list[tuple[str, float, str | None]],
    panne: str | None = None,
) -> Module:
    """Un module dont chaque étape dure un temps simulé ; `zone` : tenue pendant l'étape.
    `panne` : l'étape qui part en alarme."""
    etapes = []
    for etape, duree, zone in gestes:
        debut: dict[str, float] = {}

        def action(debut=debut, etape=etape) -> None:
            if etape == panne:
                raise ErreurEtape("panne d'essai")
            debut["t"] = simulateur.temps

        def finie(debut=debut, duree=duree) -> bool:
            return simulateur.temps >= debut["t"] + duree

        zones = (zone,) if zone else ()
        etapes.append(
            Etape(
                etape,
                QUOI_FAIRE,
                action=action,
                fin=Condition(f"{duree:g} s passées", finie),
                delai_max="exemple_deplacement_max",
                reserver=zones,
                liberer=zones,
            )
        )
    return Module(nom, tuple(etapes))


# Lancés dans cet ordre, « b » prend la zone le premier (ordre normal) : 45 s. Si « a » passe le
# premier, son long geste suivant part tout de suite : 35 s.
GESTES_B = [("dans_la_zone", 10, ZONE), ("apres", 5, None)]
GESTES_A = [("dans_la_zone", 10, ZONE), ("apres", 25, None)]


def jouer_b_puis_a(
    programme: Programme | None,
    reglages: Reglages | None = None,
    panne: str | None = None,
    attente_a: float = 0,
) -> Planning:
    reglages = reglages or reglages_actifs()
    with Simulateur(reglages, charger_entrees_sorties(LISTE), SCENARIO) as simulateur:
        gestes_a = ([("se_preparer", attente_a, None)] if attente_a else []) + GESTES_A
        modules = [
            module_minute(simulateur, "b", GESTES_B),
            module_minute(simulateur, "a", gestes_a, panne),
        ]
        return simulateur.jouer(modules, programme)


def programme_a_puis_b(heure_b: float = 10) -> Programme:
    return Programme({ZONE: (Passage("a", 0), Passage("b", heure_b))}, 35)


# ---------------------------------------------------------------- tâches


def test_taches_d_un_planning():
    planning = jouer_b_puis_a(None)
    assert planning.fini and planning.temps_total == 45
    liste = taches(planning)
    noms = {tache.nom: tache for tache in liste}
    assert set(noms) == {"b.dans_la_zone#1", "b.apres#1", "a.dans_la_zone#1", "a.apres#1"}
    assert noms["a.apres#1"].apres == "a.dans_la_zone#1"
    assert noms["a.dans_la_zone#1"].zones == (ZONE,)
    assert noms["a.dans_la_zone#1"].heure_s == 10
    # « a » a attendu la zone, pas une condition : rien n'est gardé de cette attente.
    assert noms["a.dans_la_zone#1"].attend == ()
    assert noms["a.dans_la_zone#1"].delai_s == 0
    assert noms["a.apres#1"].duree_s == 25


def test_une_etape_qui_se_repete_donne_une_tache_par_fois():
    reglages = reglages_actifs()
    with Simulateur(reglages, charger_entrees_sorties(LISTE), SCENARIO) as simulateur:
        compte = {"n": 0}
        debut: dict[str, float] = {}

        def encore() -> str | None:
            compte["n"] += 1
            return "geste" if compte["n"] < 3 else None

        module = Module(
            "boucle",
            (
                Etape(
                    "geste",
                    QUOI_FAIRE,
                    action=lambda: debut.update(t=simulateur.temps),
                    fin=Condition("2 s", lambda: simulateur.temps >= debut["t"] + 2),
                    delai_max="exemple_deplacement_max",
                    ensuite=encore,
                ),
            ),
        )
        planning = simulateur.jouer([module])
    liste = taches(planning)
    assert [tache.nom for tache in liste] == ["boucle.geste#1", "boucle.geste#2", "boucle.geste#3"]
    assert [tache.apres for tache in liste] == [None, "boucle.geste#1", "boucle.geste#2"]


def test_une_attente_de_condition_est_gardee():
    """« suit » attend que « mene » ait fini (condition) : le solveur le garde en « attend »."""
    reglages = reglages_actifs()
    with Simulateur(reglages, charger_entrees_sorties(LISTE), SCENARIO) as simulateur:
        mene = module_minute(simulateur, "mene", [("travail", 8, None)])
        debut: dict[str, float] = {}
        suit = Module(
            "suit",
            (
                Etape(
                    "apres_mene",
                    QUOI_FAIRE,
                    action=lambda: debut.update(t=simulateur.temps),
                    fin=Condition("3 s", lambda: simulateur.temps >= debut["t"] + 3),
                    delai_max="exemple_deplacement_max",
                    entree=(Condition("mene fini", lambda: simulateur.temps >= 8),),
                ),
            ),
        )
        planning = simulateur.jouer([mene, suit])
    tache = next(tache for tache in taches(planning) if tache.module == "suit")
    assert tache.attend == ("mene.travail#1",)
    ordo = ordonner(taches(planning), 5, 0.1)
    assert ordo is not None
    assert ordo.debuts["suit.apres_mene#1"] == pytest.approx(8)


def test_une_attente_sans_cause_connue_devient_un_delai():
    reglages = reglages_actifs()
    with Simulateur(reglages, charger_entrees_sorties(LISTE), SCENARIO) as simulateur:
        debut: dict[str, float] = {}
        seul = Module(
            "seul",
            (
                Etape(
                    "plus_tard",
                    QUOI_FAIRE,
                    action=lambda: debut.update(t=simulateur.temps),
                    fin=Condition("1 s", lambda: simulateur.temps >= debut["t"] + 1),
                    delai_max="exemple_deplacement_max",
                    entree=(Condition("6 s passées", lambda: simulateur.temps >= 6),),
                ),
            ),
        )
        planning = simulateur.jouer([seul])
    (tache,) = taches(planning)
    assert tache.attend == ()
    assert tache.delai_s == 6


# ---------------------------------------------------------------- ordonner


def tache(module, etape, duree, zones=(), apres=None, go=False, attend=(), delai=0.0):
    return Tache(module, etape, 1, duree, tuple(zones), apres, go, tuple(attend), delai)


def test_ordonner_le_plus_court():
    liste = [
        tache("b", "z", 10, [ZONE]),
        tache("b", "apres", 5, apres="b.z#1"),
        tache("a", "z", 10, [ZONE]),
        tache("a", "apres", 25, apres="a.z#1"),
    ]
    ordo = ordonner(liste, 5, 0.1)
    assert ordo is not None and ordo.optimal
    assert ordo.temps_total_s == pytest.approx(35)
    assert ordo.zones_partagees == (ZONE,)
    programme = ordo.programme()
    assert [passage.module for passage in programme.passages[ZONE]] == ["a", "b"]
    assert [passage.heure_s for passage in programme.passages[ZONE]] == pytest.approx([0, 10])


def test_une_zone_est_tenue_sans_trou_entre_deux_etapes():
    """« a » garde la zone de sa 1re à sa 3e étape : « b » ne peut pas passer entre deux."""
    liste = [
        tache("a", "un", 4, [ZONE]),
        tache("a", "deux", 0, [ZONE], apres="a.un#1", delai=6),
        tache("a", "trois", 4, [ZONE], apres="a.deux#1"),
        tache("b", "z", 3, [ZONE]),
    ]
    ordo = ordonner(liste, 5, 0.1)
    assert ordo is not None
    debut_b = ordo.debuts["b.z#1"]
    assert debut_b + 3 <= ordo.debuts["a.un#1"] + 1e-9 or debut_b >= ordo.debuts["a.trois#1"] + 4
    assert ordo.temps_total_s == pytest.approx(17)


def test_le_go_est_un_point_d_arret():
    liste = [
        tache("a", "un", 4),
        tache("a", "go", 1, apres="a.un#1", go=True),
        tache("a", "trois", 4, apres="a.go#1"),
        tache("b", "un", 2),
        tache("b", "apres_a", 2, apres="b.un#1", attend=["a.trois#1"]),
        tache("c", "un", 2, attend=["b.apres_a#1"]),
    ]
    assert [t.nom for t in avant_le_go(liste)] == ["a.un#1", "b.un#1"]
    ordo = ordonner(liste, 5, 0.1)
    assert ordo is not None
    assert set(ordo.debuts) == {"a.un#1", "b.un#1"}


def test_les_durees_sont_arrondies_au_pas_superieur():
    ordo = ordonner([tache("a", "un", 1.01)], 5, 0.5)
    assert ordo is not None
    assert ordo.temps_total_s == pytest.approx(1.5)


def test_pas_de_solution_dans_le_temps_garde_l_ordre_normal(monkeypatch):
    from ortools.sat.python import cp_model

    monkeypatch.setattr(cp_model.CpSolver, "solve", lambda *_: cp_model.UNKNOWN)
    assert ordonner([tache("a", "un", 1)], 0.01, 0.1) is None


def test_rien_a_ordonner():
    ordo = ordonner([], 5, 0.1)
    assert ordo is not None
    assert ordo.temps_total_s == 0
    assert ordo.programme().passages == {}


# ---------------------------------------------------------------- le chef joue le programme


def test_le_chef_joue_le_programme():
    planning = jouer_b_puis_a(programme_a_puis_b())
    assert planning.fini and planning.programme_joue
    assert planning.recul_programme == ""
    assert planning.temps_total == 35
    premier = min(
        (ligne for ligne in planning.lignes if ligne.etape == "dans_la_zone"),
        key=lambda ligne: ligne.action,
    )
    assert premier.module == "a"
    assert zones_tenues_deux_fois(planning) == []


def test_pas_actif_pas_de_programme():
    with pytest.raises(ErreurSimulation, match="solveur → actif est faux"):
        jouer_b_puis_a(programme_a_puis_b(), reglages_actifs(False))


def test_le_programme_n_autorise_rien_de_plus():
    """Le programme dit « a » d'abord, mais « a » n'est pas prêt (il se prépare 4 s) : « b » prend
    la zone (le chef ne bloque personne), et le chef revient à son ordre normal."""
    planning = jouer_b_puis_a(programme_a_puis_b(), attente_a=4)
    assert planning.fini
    assert "alors que le programme attendait « a »" in planning.recul_programme
    assert zones_tenues_deux_fois(planning) == []


def test_recul_sur_ecart_de_temps():
    # « b » prévu à 100 s, il prend la zone à 10 s : écart de 90 s (au plus 30 s, EXEMPLE).
    planning = jouer_b_puis_a(programme_a_puis_b(heure_b=100))
    assert "écart de -90.0 s" in planning.recul_programme
    assert planning.fini


def test_recul_sur_retard():
    # Personne ne prend la zone B : au bout de 30 s (EXEMPLE), le passage prévu est en retard.
    programme = Programme({"exemple_zone_b": (Passage("a", 0),)}, 10)
    planning = jouer_b_puis_a(programme)
    assert planning.fini
    assert "« a » devait prendre la zone « exemple_zone_b » à 0.0 s" in planning.recul_programme


def test_recul_sur_alarme():
    planning = jouer_b_puis_a(programme_a_puis_b(), panne="dans_la_zone")
    assert not planning.fini
    assert planning.recul_programme == "alarme de « a »"


def test_zone_inconnue_refusee():
    with pytest.raises(ErreurSimulation, match="zone_qui_n_existe_pas"):
        jouer_b_puis_a(Programme({"zone_qui_n_existe_pas": (Passage("a", 0),)}, 1))


# ---------------------------------------------------------------- vérification et gain


def test_comparer_mesure_le_gain():
    solveur = reglages_actifs().machine.solveur
    assert solveur is not None
    comparaison = comparer(lambda programme: (jouer_b_puis_a(programme), []), solveur)
    assert comparaison.accepte, comparaison.rejets
    assert comparaison.normal.temps_total == 45
    assert comparaison.rejoue is not None and comparaison.rejoue.temps_total == 35
    assert comparaison.gain_s == 10
    texte = comparaison.en_texte()
    assert "programme accepté ; gain : 10,0 s (22,2 %)" in texte
    assert "zones partagées entre modules : « exemple_zone_a »" in texte


def test_comparer_rejette_un_programme_qui_n_est_pas_suivi():
    solveur = reglages_actifs().machine.solveur
    assert solveur is not None

    def jouer(programme):
        # Au rejeu, « a » met 4 s de plus à se préparer : le programme n'est pas suivi.
        return jouer_b_puis_a(programme, attente_a=4 if programme else 0), []

    comparaison = comparer(jouer, solveur)
    assert not comparaison.accepte
    assert comparaison.gain_s == 0
    assert any("le chef a quitté le programme" in raison for raison in comparaison.rejets)
    assert "programme REJETÉ, ordre normal du chef" in comparaison.en_texte()


def test_comparer_rejette_un_ecart_a_l_ordre_du_cycle():
    solveur = reglages_actifs().machine.solveur
    assert solveur is not None

    def jouer(programme):
        return jouer_b_puis_a(programme), ["seau S301 : couvercle avant le mycélium"] * bool(
            programme
        )

    comparaison = comparer(jouer, solveur)
    assert comparaison.rejets == [
        "ordre du cycle pas suivi : seau S301 : couvercle avant le mycélium"
    ]


def ligne(module, etape, action, fin, zones=()):
    return LignePlanning(module, etape, 1, 1, action, action=action, fin=fin, zones=tuple(zones))


def test_verifier_un_programme():
    normal = Planning(["a", "b"], [ligne("a", "un", 0, 10), ligne("b", "un", 0, 5)], 10)
    double = Planning(
        ["a", "b"], [ligne("a", "un", 0, 10, [ZONE]), ligne("b", "un", 4, 9, [ZONE])], 10
    )
    assert verifier_programme(normal, double) == [
        "zone « exemple_zone_a » tenue par « a » et « b » en même temps (à 4.0 s)"
    ]
    moins = Planning(["a", "b"], [ligne("a", "un", 0, 10)], 10)
    assert "pas fait les mêmes étapes (1 contre 2" in verifier_programme(normal, moins)[0]
    long = Planning(["a", "b"], [ligne("a", "un", 0, 12), ligne("b", "un", 0, 5)], 12)
    assert verifier_programme(normal, long) == [
        "plus long que l'ordre normal (12,0 s contre 10,0 s)"
    ]
    arrete = Planning(["a", "b"], normal.lignes, 10, probleme="alarme de « a »")
    assert verifier_programme(normal, arrete) == ["le cycle rejoué s'est arrêté : alarme de « a »"]
    # Une zone laissée par « a » et prise par « b » au même instant : pas de chevauchement.
    suite = Planning(
        ["a", "b"], [ligne("a", "un", 0, 5, [ZONE]), ligne("b", "un", 5, 10, [ZONE])], 10
    )
    assert zones_tenues_deux_fois(suite) == []


def test_comparer_ordre_normal_qui_ne_va_pas_au_bout():
    solveur = reglages_actifs().machine.solveur
    assert solveur is not None
    comparaison = comparer(
        lambda programme: (jouer_b_puis_a(programme, panne="apres"), []), solveur
    )
    assert isinstance(comparaison, Comparaison)
    assert comparaison.ordonnancement is None
    assert "l'ordre normal lui-même ne va pas au bout" in comparaison.rejets[0]


# ---------------------------------------------------------------- réglages et outil


def test_reglages_du_solveur(reglages):
    solveur = charger_reglages(DOSSIER_PI / "reglages").machine.solveur
    assert solveur is not None
    assert solveur.exemple is True
    assert solveur.actif is False
    remplacer(reglages / "machine.yaml", "  pas_s: 0.1", "  pas_s: 60")
    assert "pas_s (60 s) plus grand que ecart_max_s (30 s)" in erreur_de(reglages)
    remplacer(reglages / "machine.yaml", "  temps_max_s: 10", "  temps_max_s: 0")
    assert "solveur → temps_max_s : doit être plus grand que 0" in erreur_de(reglages)


def test_outil_compare_le_lot_de_seaux(capsys):
    """Le lot simulé de 18 seaux : aujourd'hui aucune zone n'y est partagée (le Remplissage et le
    Mycélium se suivent par des conditions), le programme ne change rien et le gain est nul."""
    assert main(["cycle", "--solveur"]) == 0
    sortie = capsys.readouterr().out
    assert "Lot simulé : 18 seaux seau_a" in sortie
    assert "zones partagées entre modules : aucune" in sortie
    assert "programme accepté ; gain : 0,0 s (0,0 %)" in sortie


def test_outil_solveur_et_json_ensemble(capsys):
    with pytest.raises(SystemExit):
        main(["exemple", "--solveur", "--json", "p.json"])
    assert "--solveur ne va pas avec --json" in capsys.readouterr().err
