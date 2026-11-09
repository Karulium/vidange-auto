"""Statistiques de la page (tâche 28 bis) : d'après le registre, avec une fausse horloge."""

from datetime import datetime, timedelta, timezone

import pytest

from vidange.registre import Registre
from vidange.reglages import ReglagesStatistiques
from vidange.statistiques import Statistiques

FUSEAU = timezone(timedelta(hours=-4))


def le(jour: int, heure: int, minute: int = 0, mois: int = 11) -> datetime:
    return datetime(2026, mois, jour, heure, minute, tzinfo=FUSEAU)


@pytest.fixture
def banc(tmp_path):
    """Un registre dont l'heure se règle à la main, et les statistiques devant."""
    heure = [le(1, 0)]
    registre = Registre(tmp_path / "r.sqlite", tmp_path / "photos", horloge=lambda: heure[0])
    reglages = ReglagesStatistiques(jours=3, semaines=2, mois=2, cycle_ouvert_max_h=12)
    stats = Statistiques(registre, reglages, horloge=lambda: heure[0])

    def a(moment: datetime) -> None:
        heure[0] = moment

    yield stats, registre, a
    registre.fermer()


def remplir(registre, a) -> None:
    """Dimanche 8/11 : un cycle d'une heure, 2 seaux. Lundi 9/11 : un cycle abandonné (1 seau,
    1 alarme) et un lavage qui le chevauche, puis un cycle encore ouvert. Il est 15 h."""
    a(le(8, 9))
    a_cycle = registre.commencer_cycle("vidange")
    a(le(8, 9, 10))
    registre.ajouter_seau(a_cycle, "S1")
    a(le(8, 9, 20))
    registre.ajouter_seau(a_cycle, "S2")
    a(le(8, 10))
    registre.finir_cycle(a_cycle)
    a(le(9, 8))
    b = registre.commencer_cycle("vidange")
    a(le(9, 8, 30))
    lavage = registre.commencer_cycle("lavage")
    registre.noter_alarme("prehension", "dérapage", cycle=b)
    a(le(9, 8, 40))
    registre.ajouter_seau(b, "S3")
    a(le(9, 9))
    registre.finir_cycle(b, "abandonne")
    a(le(9, 9, 30))
    registre.finir_cycle(lavage)
    a(le(9, 14))
    registre.commencer_cycle("vidange")
    a(le(9, 15))


def test_par_jour(banc):
    stats, registre, a = banc
    remplir(registre, a)
    resultat = stats.calculer("jour")
    assert [p["debut"] for p in resultat["periodes"]] == ["2026-11-07", "2026-11-08", "2026-11-09"]
    vide, dimanche, lundi = resultat["periodes"]
    assert vide["seaux"] == vide["cycles"] == 0 and vide["duree_moyenne_seau_s"] is None
    assert vide["marche_s"] == 0 and vide["arret_s"] == 24 * 3600
    # Dimanche : 2 seaux en 1 h de cycle = 30 min par seau ; marche 1 h.
    assert dimanche["seaux"] == 2 and dimanche["cycles_termines"] == 1
    assert dimanche["duree_moyenne_seau_s"] == 1800
    assert dimanche["marche_s"] == 3600 and dimanche["arret_s"] == 23 * 3600
    # Lundi : le cycle abandonné et le lavage se chevauchent (8 h à 9 h 30 comptées une fois),
    # puis le cycle ouvert de 14 h à 15 h ; l'arrêt ne compte que jusqu'à 15 h.
    assert lundi["en_cours"] is True
    assert lundi["seaux"] == 1 and lundi["cycles"] == 3
    assert (lundi["cycles_termines"], lundi["cycles_abandonnes"], lundi["cycles_ouverts"]) == (
        1,
        1,
        1,
    )
    assert lundi["alarmes"] == {"prehension": 1} and lundi["alarmes_total"] == 1
    assert lundi["marche_s"] == 90 * 60 + 3600
    assert lundi["arret_s"] == 15 * 3600 - lundi["marche_s"]
    # Le seul cycle terminé de lundi (le lavage) n'a pas de seau : pas de durée par seau.
    assert lundi["duree_moyenne_seau_s"] is None
    assert resultat["modules"] == ["prehension"]


def test_par_semaine_et_par_mois(banc):
    stats, registre, a = banc
    remplir(registre, a)
    # Le 9/11/2026 est un lundi : la semaine en cours ne compte que lundi.
    semaines = stats.calculer("semaine")["periodes"]
    assert [p["debut"] for p in semaines] == ["2026-11-02", "2026-11-09"]
    assert semaines[0]["seaux"] == 2 and semaines[1]["seaux"] == 1
    mois = stats.calculer("mois")["periodes"]
    assert [p["debut"] for p in mois] == ["2026-10-01", "2026-11-01"]
    assert mois[0]["seaux"] == 0 and mois[1]["seaux"] == 3
    assert mois[1]["cycles"] == 4
    assert mois[1]["marche_s"] == 3600 + 90 * 60 + 3600


def test_un_cycle_a_cheval_sur_minuit_est_coupe(banc):
    stats, registre, a = banc
    a(le(8, 23))
    cycle = registre.commencer_cycle("vidange")
    a(le(9, 2))
    registre.finir_cycle(cycle)
    a(le(9, 12))
    _, dimanche, lundi = stats.calculer("jour")["periodes"]
    assert dimanche["marche_s"] == 3600 and lundi["marche_s"] == 2 * 3600


def test_un_cycle_reste_ouvert_compte_au_plus_la_duree_reglee(banc):
    stats, registre, a = banc
    a(le(8, 6))
    registre.commencer_cycle("vidange")
    a(le(9, 12))
    _, dimanche, lundi = stats.calculer("jour")["periodes"]
    # 12 h au plus à partir de 6 h : jusqu'à 18 h dimanche, rien lundi.
    assert dimanche["marche_s"] == 12 * 3600 and lundi["marche_s"] == 0


def test_un_registre_vide(banc):
    stats, _, a = banc
    a(le(9, 12))
    for echelle in ("jour", "semaine", "mois"):
        periodes = stats.calculer(echelle)["periodes"]
        assert all(p["seaux"] == 0 and p["marche_s"] == 0 for p in periodes)
