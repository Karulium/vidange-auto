"""Tests de la check-list de démarrage et du catalogue des « quoi faire »."""

from vidange.chef import Chef, Condition, Etape, Module
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fiabilite import CheckList, Constat
from vidange.fiabilite.checklist import (
    constats_chef,
    constats_materiel,
    constats_registre,
    constats_reglages,
)
from vidange.fluidnc.liaison import EtatCarte
from vidange.fluidnc.protocole import ALARMES
from vidange.materiel import FausseFabrique, Materiel
from vidange.quoi_faire import ALARMES_FLUIDNC, CARTE_COUPEE, pour_carte
from vidange.registre import Registre
from vidange.reglages import ReglagesChef, charger_reglages

from .conftest import DOSSIER_PI
from .test_reglages import remplacer


def test_chaque_alarme_fluidnc_a_son_quoi_faire():
    assert set(ALARMES) <= set(ALARMES_FLUIDNC)
    assert all(texte.strip() for texte in ALARMES_FLUIDNC.values())
    assert pour_carte(EtatCarte()) == ("pas connectée", CARTE_COUPEE)
    texte, quoi_faire = pour_carte(EtatCarte(connectee=True, etat="Alarm", alarme=1))
    assert texte == "alarme 1 : fin de course matérielle touchée"
    assert quoi_faire == ALARMES_FLUIDNC[1]
    assert pour_carte(EtatCarte(connectee=True, etat="Idle")) is None


def test_prete_seulement_sans_bloquant(caplog):
    sources = {
        "a": lambda: [Constat("disque", "attention", "presque plein", "Faire de la place.")],
        "b": lambda: [Constat("heure", "ok", "juste")],
    }
    checklist = CheckList(sources)
    constats = checklist.verifier()
    assert CheckList.prete(constats)
    checklist.ecrire_au_journal(constats)
    assert "[attention] disque : presque plein → Faire de la place." in caplog.text

    # Une vérification qui plante est bloquante (on ne sait pas : on ne produit pas).
    sources["c"] = lambda: 1 / 0
    constats = CheckList(sources).verifier()
    assert not CheckList.prete(constats)
    assert constats[-1].sujet == "c" and "division by zero" in constats[-1].texte


def test_reglages_d_exemple_bloquants():
    reglages = charger_reglages(DOSSIER_PI / "reglages")
    liste = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
    constats = constats_reglages(reglages, liste)
    assert {c.sujet for c in constats if c.niveau == "bloquant"} == {
        "machine.yaml",
        "fluidnc.yaml",
        "entrees-sorties.yaml",
    }


def test_entrees_dans_leur_etat_au_demarrage(entrees_sorties):
    remplacer(
        entrees_sorties,
        "    module: poste_fut\n",
        "    module: poste_fut\n    au_demarrage: actionne\n",
    )
    liste = charger_entrees_sorties(entrees_sorties)
    fabrique = FausseFabrique(liste)
    with Materiel(liste, fabrique) as materiel:
        constats = {c.sujet: c for c in constats_materiel(materiel, None, liste)}
        assert constats["reed_panneau_poste_fut"].niveau == "bloquant"
        assert "au repos (attendu : actionné)" in constats["reed_panneau_poste_fut"].texte

        fabrique.actionner("reed_panneau_poste_fut")
        fabrique.actionner("porte_spray")  # porte ouverte : attendue « repos »
        constats = {c.sujet: c for c in constats_materiel(materiel, None, liste)}
        assert set(constats) == {"porte_spray"}

        fabrique.actionner("porte_spray", False)
        assert [c.niveau for c in constats_materiel(materiel, None, liste)] == ["ok"]

    constats = constats_materiel(None, "pas de /dev/gpiochip0", liste)
    assert constats[0].niveau == "bloquant" and "pas de /dev/gpiochip0" in constats[0].texte


def test_chef_et_registre(tmp_path):
    reglages = charger_reglages(DOSSIER_PI / "reglages")
    chef = Chef(reglages.machine, ReglagesChef(periode_s=0.01, alarme_pause_tout=False))
    chef.lancer(
        Module("essai", (Etape("un", "Regarder.", entree=(Condition("prêt", lambda: 1 / 0),)),))
    )
    chef.avancer()
    constats = constats_chef(chef, "carnet : module « vieux » inconnu du programme")
    assert [c.niveau for c in constats] == ["bloquant", "bloquant"]

    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    try:
        assert constats_registre(registre)[0].niveau == "ok"
        registre.noter_alarme("alimentation", "coupure de courant")
        constat = constats_registre(registre)[0]
        assert constat.niveau == "attention"
        assert "« alimentation », coupure de courant" in constat.texte
    finally:
        registre.fermer()
