"""Tests de l'estimation de fin qui apprend (tâche 30, fonction 7)."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from vidange.entrees_sorties import charger_entrees_sorties
from vidange.estimation import BaseSimulee, Estimation, base_du_simulateur
from vidange.registre import Registre
from vidange.reglages import ReglagesEstimation, charger_reglages

from .conftest import DOSSIER_PI
from .test_chef import Banc, Horloge, module_simple, nouveau_chef, tour

FORMAT = "seau_a"
LOT = (FORMAT, 10, object())


def reglages_estimation(**changes) -> ReglagesEstimation:
    base = {
        "actif": True,
        "rafraichir_s": 0.001,
        "moyenne_sur": 5,
        "mesures_min": 3,
        "duree_min_s": 0.5,
        "garde_par_geste": 10,
        "correction_min": 0.5,
        "correction_max": 2.0,
        "fourchette_min_pct": 5,
        "fourchette_max_pct": 40,
        "fourchette_sans_historique_pct": 30,
    }
    base.update(changes)
    return ReglagesEstimation.model_validate(base)


# Un lot simulé de 1000 s : 10 passages de « a » (50 s chacun) et 10 de « b » (30 s chacun), le
# reste est de l'attente.
BASE = BaseSimulee(1000.0, {"m.a": (500.0, 10), "m.b": (300.0, 10)})


class Temps:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 9, 8, 0, 0)

    def __call__(self) -> datetime:
        self.t += timedelta(seconds=1)
        return self.t


@pytest.fixture
def registre(tmp_path):
    return Registre(tmp_path / "registre.sqlite", tmp_path / "photos")


def fabriquer(registre, lot=LOT, base=BASE, **changes) -> Estimation:
    return Estimation(
        reglages_estimation(**changes),
        registre,
        lambda: lot,
        lambda format, nombre: base,
        horloge=Temps(),
        en_fond=False,
    )


def apprendre(estimation, geste: str, duree: float, fois: int) -> None:
    module, etape = geste.split(".")
    for _ in range(fois):
        estimation.sur_etape_finie(module, etape, duree)


# ---------------------------------------------------------------- le registre


def test_le_registre_garde_les_durees_par_geste_et_par_format(registre):
    for duree in (1.0, 2.0, 3.0):
        registre.noter_duree_geste("m.a", duree, "seau_a")
    registre.noter_duree_geste("m.a", 9.0, "seau_b")
    registre.noter_duree_geste("m.a", 8.0, None)
    assert registre.durees_du_geste("m.a", "seau_a", 10) == [3.0, 2.0, 1.0]
    assert registre.durees_du_geste("m.a", "seau_a", 2) == [3.0, 2.0]
    assert registre.durees_du_geste("m.a", "seau_b", 10) == [9.0]
    assert registre.durees_du_geste("m.a", None, 10) == [8.0]
    assert registre.durees_du_geste("m.z", "seau_a", 10) == []


def test_le_registre_n_en_garde_que_le_nombre_demande(registre):
    for numero in range(1, 8):
        registre.noter_duree_geste("m.a", float(numero), "seau_a", garder=3)
        registre.noter_duree_geste("m.a", 99.0, "seau_b", garder=3)
    assert registre.durees_du_geste("m.a", "seau_a", 10) == [7.0, 6.0, 5.0]
    assert len(registre.durees_du_geste("m.a", "seau_b", 10)) == 3
    assert registre.compter()["durees_gestes"] == 6


# ---------------------------------------------------------------- sans historique


def test_sans_historique_c_est_le_calcul_du_simulateur(registre):
    estimation = fabriquer(registre)
    resultat = estimation.calculer()
    assert resultat["disponible"] is True
    assert resultat["reste_s"] == 1000
    assert resultat["simulateur_seul"] is True
    assert resultat["gestes_appris"] == 0
    # Grande fourchette fixe, sans historique.
    assert (resultat["bas_s"], resultat["haut_s"]) == (700, 1300)
    assert "environ 16 min 40 s" in resultat["texte"]
    assert "d'après le simulateur seulement" in resultat["texte"]
    assert resultat["texte_court"].startswith("Fin vers ")


def test_les_reglages_d_exemple_sont_dits():
    base = BaseSimulee(60.0, {"m.a": (60.0, 1)}, exemple=True)
    assert base.exemple


def test_pas_de_lot_pas_d_estimation(registre):
    estimation = Estimation(
        reglages_estimation(), registre, lambda: None, lambda f, n: BASE, en_fond=False
    )
    assert estimation.calculer() is None


def test_coupee_dans_les_reglages(registre):
    estimation = fabriquer(registre, actif=False)
    assert estimation.calculer() is None
    estimation.sur_etape_finie("m", "a", 40.0)
    assert registre.compter()["durees_gestes"] == 0


# ---------------------------------------------------------------- elle apprend


def test_les_vraies_durees_plus_longues_allongent_l_estimation(registre):
    estimation = fabriquer(registre)
    # « a » prend 100 s au lieu de 50 s (rapport 2, la borne), « b » reste à 30 s.
    apprendre(estimation, "m.a", 100.0, 3)
    apprendre(estimation, "m.b", 30.0, 3)
    resultat = estimation.calculer()
    assert resultat["gestes_appris"] == 2
    assert resultat["simulateur_seul"] is False
    # Rapport pondéré (500 × 2 + 300 × 1) / 800 = 1,625 ; avancement (3 × 50 + 3 × 30) / 800 = 0,3.
    assert resultat["rapport"] == 1.625
    assert resultat["avancement_pct"] == 30.0
    assert resultat["reste_s"] == round(1000 * 1.625 * (1 - 0.3))
    assert "corrigée par 2 geste(s) appris sur 2" in resultat["texte"]


def test_la_correction_est_bornee(registre):
    estimation = fabriquer(registre)
    apprendre(estimation, "m.a", 5000.0, 3)  # 100 fois trop long : borné à 2
    apprendre(estimation, "m.b", 0.6, 3)  # 50 fois trop court : borné à 0,5
    resultat = estimation.calculer()
    assert resultat["rapport"] == round((500 * 2 + 300 * 0.5) / 800, 3)


def test_pas_de_correction_sous_le_nombre_minimal_de_mesures(registre):
    estimation = fabriquer(registre)
    apprendre(estimation, "m.a", 100.0, 2)  # mesures_min = 3
    assert estimation.calculer()["gestes_appris"] == 0


def test_une_duree_trop_courte_n_est_pas_gardee(registre):
    estimation = fabriquer(registre)
    apprendre(estimation, "m.a", 0.1, 5)
    assert registre.compter()["durees_gestes"] == 0


def test_moyenne_glissante_les_vieilles_durees_sortent(registre):
    estimation = fabriquer(registre, moyenne_sur=3, correction_max=10.0)
    apprendre(estimation, "m.a", 500.0, 3)
    apprendre(estimation, "m.a", 50.0, 3)  # les 3 dernières seules comptent
    assert estimation.calculer()["rapport"] == 1.0


def test_l_apprentissage_est_par_format(registre):
    ancien = fabriquer(registre, lot=("seau_b", 10, object()))
    apprendre(ancien, "m.a", 100.0, 5)
    resultat = fabriquer(registre).calculer()  # format seau_a : rien appris
    assert resultat["gestes_appris"] == 0


def test_la_fourchette_se_resserre_quand_les_durees_se_ressemblent(registre):
    regulier = fabriquer(registre)
    apprendre(regulier, "m.a", 50.0, 5)
    apprendre(regulier, "m.b", 30.0, 5)
    assert regulier.calculer()["fourchette_pct"] == 5.0  # écart nul : la borne basse


def test_la_fourchette_s_elargit_quand_les_durees_varient(registre):
    irregulier = fabriquer(registre)
    for duree in (20.0, 80.0, 30.0, 70.0, 50.0):
        apprendre(irregulier, "m.a", duree, 1)
    resultat = irregulier.calculer()
    assert 5.0 < resultat["fourchette_pct"] <= 40.0


# ---------------------------------------------------------------- l'avancement


def test_l_avancement_suit_les_gestes_du_lot_en_cours(registre):
    estimation = fabriquer(registre)
    apprendre(estimation, "m.a", 50.0, 5)
    apprendre(estimation, "m.b", 30.0, 5)
    assert estimation.calculer()["reste_s"] == 500
    apprendre(estimation, "m.a", 50.0, 20)  # plus de passages que prévu : plafonné
    # « a » est plafonné à ses 10 passages : (500 + 5 × 30) / 800 du lot est fait.
    assert estimation.calculer()["reste_s"] == round(1000 * (1 - 650 / 800))


def test_un_nouveau_lot_repart_de_zero(registre):
    lots = [LOT]
    estimation = Estimation(
        reglages_estimation(), registre, lambda: lots[0], lambda f, n: BASE, Temps(), False
    )
    apprendre(estimation, "m.a", 50.0, 10)
    assert estimation.calculer()["avancement_pct"] > 0
    lots[0] = (FORMAT, 10, object())
    assert estimation.calculer()["avancement_pct"] == 0


def test_jamais_de_temps_negatif(registre):
    estimation = fabriquer(registre)
    apprendre(estimation, "m.a", 50.0, 50)
    apprendre(estimation, "m.b", 30.0, 50)
    assert estimation.calculer()["reste_s"] == 0


# ---------------------------------------------------------------- la base du simulateur


def test_si_le_simulateur_echoue_on_le_dit_sans_planter(registre):
    def casse(format, nombre):
        raise RuntimeError("piles vides")

    estimation = Estimation(
        reglages_estimation(), registre, lambda: LOT, casse, horloge=Temps(), en_fond=False
    )
    resultat = estimation.calculer()
    assert resultat["disponible"] is False
    assert "piles vides" in resultat["texte"]


def test_la_base_se_calcule_en_fond_puis_est_gardee(registre):
    appels = []

    def base(format, nombre):
        appels.append((format, nombre))
        return BASE

    estimation = Estimation(
        reglages_estimation(rafraichir_s=0.001), registre, lambda: LOT, base, horloge=Temps()
    )
    premier = estimation.calculer()
    for _ in range(200):
        if estimation.calculer()["disponible"]:
            break
        import time

        time.sleep(0.01)
    assert premier["disponible"] in (True, False)
    assert estimation.calculer()["disponible"] is True
    assert appels == [(FORMAT, 10)]


# ---------------------------------------------------------------- le chef raconte ses étapes


def test_le_chef_donne_la_duree_du_geste_sans_les_attentes(registre):
    horloge, banc = Horloge(), Banc()
    chef = nouveau_chef(horloge)
    vues = []
    chef.sur_etape_finie.append(lambda module, etape, duree: vues.append((module, etape, duree)))
    chef.lancer(module_simple(banc))
    tour(chef, horloge, 5)  # attend « pret » : 5 s d'attente, pas un geste
    banc.drapeaux["pret"] = True
    tour(chef, horloge, 1)  # l'action part
    tour(chef, horloge, 2)
    banc.drapeaux["essai.un_fini"] = True
    tour(chef, horloge, 1)
    assert [(m, e) for m, e, _ in vues] == [("essai", "un")]
    assert vues[0][2] == 3.0


def test_un_ecouteur_qui_plante_n_arrete_pas_le_chef(registre):
    horloge, banc = Horloge(), Banc()
    chef = nouveau_chef(horloge)

    def plante(*_):
        raise RuntimeError("disque plein")

    chef.sur_etape_finie.append(plante)
    chef.lancer(module_simple(banc))
    banc.drapeaux["pret"] = True
    banc.drapeaux["essai.un_fini"] = True
    for _ in range(4):
        tour(chef, horloge)
    assert chef.etat().modules[0].etape == "deux"


def test_estimation_branchee_sur_le_chef_garde_les_durees(registre):
    horloge, banc = Horloge(), Banc()
    chef = nouveau_chef(horloge)
    estimation = fabriquer(registre, base=BaseSimulee(100.0, {"essai.un": (10.0, 1)}))
    chef.sur_etape_finie.append(estimation.sur_etape_finie)
    chef.lancer(module_simple(banc))
    banc.drapeaux["pret"] = True
    tour(chef, horloge, 1)
    tour(chef, horloge, 2)
    banc.drapeaux["essai.un_fini"] = True
    tour(chef, horloge, 1)
    assert registre.durees_du_geste("essai.un", FORMAT, 5) == [3.0]


# ---------------------------------------------------------------- avec le vrai simulateur


@pytest.fixture(scope="module")
def base_reelle():
    reglages = charger_reglages(DOSSIER_PI / "reglages")
    liste = charger_entrees_sorties(Path(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"))
    cycle = reglages.simulateur.cycle
    return reglages, base_du_simulateur(reglages, liste, cycle.format, cycle.seaux), cycle


def test_la_base_du_vrai_simulateur_a_les_gestes_du_lot(base_reelle):
    reglages, base, cycle = base_reelle
    assert base.exemple is reglages.simulateur.exemple
    assert base.temps_total_s > 600
    # L'étape qui finit un cycle (réglage de la montée en vitesse) passe une fois par seau.
    _, passages = base.par_geste[reglages.programme.montee_vitesse.etape_de_cycle]
    assert passages == cycle.seaux


def test_un_lot_plus_grand_que_les_piles_est_mis_a_l_echelle(base_reelle):
    reglages, base, cycle = base_reelle
    liste = charger_entrees_sorties(Path(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"))
    petit = base_du_simulateur(reglages, liste, cycle.format, 2)
    assert petit.temps_total_s < base.temps_total_s
    _, passages = petit.par_geste[reglages.programme.montee_vitesse.etape_de_cycle]
    assert passages == 2
