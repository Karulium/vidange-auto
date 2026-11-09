"""Tests de l'essai d'un réglage dans le simulateur (tâche 30, fonction 68)."""

import time

import pytest

from vidange.demarrage import principal
from vidange.simulateur.essai import (
    ErreurEssai,
    EssaiEnFond,
    ResultatLot,
    copie_provisoire,
    essayer,
    jouer_le_lot,
    lire_changement,
)

PONT = "machine.yaml=griffe.vitesses.pont_x=0.2"


def faux_lot(reglages, liste) -> ResultatLot:
    """Un lot « simulé » instantané : plus la vitesse du pont est basse, plus il dure."""
    vitesse = reglages.machine.griffe.vitesses.pont_x
    return ResultatLot(fini=True, temps_total_s=1000 * 0.25 / vitesse)


# ---------------------------------------------------------------- les demandes


def test_lire_un_changement():
    assert lire_changement(PONT) == ("machine.yaml", "griffe.vitesses.pont_x", 0.2)
    assert lire_changement("machine=griffe.vitesses.pont_x=0.2")[0] == "machine.yaml"
    assert lire_changement("programme.yaml=solveur.actif=true")[2] is True
    assert lire_changement("programme.yaml=a=un mot")[2] == "un mot"


@pytest.mark.parametrize(
    "texte",
    ["machine.yaml", "machine.yaml=pont", "=a=1", "inconnu.yaml=a=1", "machine.yaml=a=[1, 2]"],
)
def test_mal_ecrit_refuse(texte):
    with pytest.raises(ErreurEssai):
        lire_changement(texte)


def test_les_vrais_fichiers_ne_bougent_pas(reglages, tmp_path):
    avant = {fichier.name: fichier.read_bytes() for fichier in reglages.glob("*.yaml")}
    faits = copie_provisoire(reglages, [PONT], tmp_path / "copie")
    assert faits[0].avant == 0.25
    assert {fichier.name: fichier.read_bytes() for fichier in reglages.glob("*.yaml")} == avant
    assert "pont_x: 0.2" in (tmp_path / "copie" / "machine.yaml").read_text(encoding="utf-8")


def test_une_cle_avec_des_points_se_change_aussi(reglages, tmp_path):
    faits = copie_provisoire(
        reglages,
        ["programme.yaml=montee_vitesse.vitesses.griffe.vitesses.pont_x=0.28"],
        tmp_path / "copie",
    )
    assert faits[0].avant == 0.30


def test_reglage_inexistant_refuse(reglages, tmp_path):
    with pytest.raises(ErreurEssai, match="n'existe pas"):
        copie_provisoire(reglages, ["machine.yaml=griffe.vitesses.vol=1"], tmp_path / "copie")


def test_aucun_reglage_refuse(reglages, tmp_path):
    with pytest.raises(ErreurEssai, match="aucun réglage"):
        copie_provisoire(reglages, [], tmp_path / "copie")


# ---------------------------------------------------------------- la comparaison


def test_comparaison_normal_contre_essai(reglages, entrees_sorties):
    comparaison = essayer(reglages, entrees_sorties, [PONT], jouer=faux_lot)
    assert comparaison.normal.temps_total_s == 1000
    assert comparaison.essai.temps_total_s == 1250
    assert comparaison.sans_probleme
    texte = comparaison.en_texte()
    assert "griffe.vitesses.pont_x = 0.2 (avant : 0.25)" in texte
    assert "+4 min 10 s (+25,0 %)" in texte
    assert "Alertes" in texte and "Refus du chef" in texte
    assert "rien n'est écrit dans les vrais fichiers" in texte
    assert comparaison.en_dict()["essai"]["temps_total_s"] == 1250


def test_une_alerte_ou_un_refus_rend_l_essai_mauvais(reglages, entrees_sorties):
    def avec_alerte(reglages, liste):
        if reglages.machine.griffe.vitesses.pont_x == 0.2:
            return ResultatLot(
                fini=False, temps_total_s=50, alertes=["alarme de « griffe »"], refus="lot refusé"
            )
        return ResultatLot(fini=True, temps_total_s=100)

    comparaison = essayer(reglages, entrees_sorties, [PONT], jouer=avec_alerte)
    assert not comparaison.sans_probleme
    texte = comparaison.en_texte()
    assert "alarme de « griffe »" in texte
    assert "lot refusé" in texte
    assert "donne une alerte, un refus ou un lot qui ne finit pas" in texte


def test_un_reglage_que_le_demarrage_refuserait_est_refuse(reglages, entrees_sorties):
    # Un rail plus court que la course permise.
    with pytest.raises(ErreurEssai, match="réglage refusé, comme le ferait le démarrage"):
        essayer(
            reglages,
            entrees_sorties,
            ["machine.yaml=axes.pont_x.longueur_rail=0.5"],
            jouer=faux_lot,
        )
    with pytest.raises(ErreurEssai, match="réglage refusé"):
        essayer(
            reglages, entrees_sorties, ["machine.yaml=griffe.vitesses.pont_x=-1"], jouer=faux_lot
        )


# ---------------------------------------------------------------- la commande


def test_la_commande_vidange_simuler_essayer(reglages, entrees_sorties, monkeypatch, capsys):
    monkeypatch.setenv("VIDANGE_REGLAGES", str(reglages))
    monkeypatch.setenv("VIDANGE_ENTREES_SORTIES", str(entrees_sorties))
    monkeypatch.setattr("vidange.simulateur.essai.jouer_le_lot", faux_lot)
    assert principal(["simuler", "--essayer", PONT]) == 0
    assert "Lot avec l'essai" in capsys.readouterr().out


def test_la_commande_refuse_sans_reglage(reglages, entrees_sorties, monkeypatch):
    monkeypatch.setenv("VIDANGE_REGLAGES", str(reglages))
    monkeypatch.setenv("VIDANGE_ENTREES_SORTIES", str(entrees_sorties))
    with pytest.raises(SystemExit):
        principal(["simuler"])


def test_la_commande_dit_un_reglage_faux_et_rend_2(reglages, entrees_sorties, monkeypatch, capsys):
    monkeypatch.setenv("VIDANGE_REGLAGES", str(reglages))
    monkeypatch.setenv("VIDANGE_ENTREES_SORTIES", str(entrees_sorties))
    assert principal(["simuler", "--essayer", "machine.yaml=griffe.vitesses.vol=1"]) == 2
    assert "Essai impossible" in capsys.readouterr().err


# ---------------------------------------------------------------- le bouton de la page


def test_essai_en_fond_un_seul_a_la_fois(reglages, entrees_sorties):
    essai = EssaiEnFond(
        reglages, entrees_sorties, jouer=lambda r, ls: (time.sleep(0.5), faux_lot(r, ls))[1]
    )
    essai.lancer([PONT], "karulium")
    with pytest.raises(ErreurEssai, match="déjà en cours"):
        essai.lancer([PONT], "karulium")
    for _ in range(100):
        if not essai.etat()["en_cours"]:
            break
        time.sleep(0.1)
    etat = essai.etat()
    assert etat["erreur"] is None
    assert etat["resultat"]["essai"]["temps_total_s"] == 1250


def test_essai_refuse_pendant_un_lot(reglages, entrees_sorties):
    essai = EssaiEnFond(
        reglages, entrees_sorties, refus=lambda: "un lot tourne", jouer=faux_lot, en_fond=False
    )
    with pytest.raises(ErreurEssai, match="un lot tourne"):
        essai.lancer([PONT], "karulium")


def test_essai_reglage_mal_ecrit_refuse_tout_de_suite(reglages, entrees_sorties):
    essai = EssaiEnFond(reglages, entrees_sorties, jouer=faux_lot, en_fond=False)
    with pytest.raises(ErreurEssai):
        essai.lancer(["machine.yaml"], "karulium")
    assert essai.etat()["en_cours"] is False


def test_essai_reglage_refuse_par_le_demarrage_est_dit_dans_l_etat(reglages, entrees_sorties):
    essai = EssaiEnFond(reglages, entrees_sorties, jouer=faux_lot, en_fond=False)
    etat = essai.lancer(["machine.yaml=griffe.vitesses.pont_x=-1"], "karulium")
    assert "réglage refusé" in etat["erreur"]


# ---------------------------------------------------------------- avec le vrai simulateur


def test_un_vrai_essai_rejoue_le_lot_simule(reglages, entrees_sorties):
    # La griffe et son axe imaginaire à 0,15 m/s au lieu de 0,25 : le lot est un peu plus long.
    comparaison = essayer(
        reglages,
        entrees_sorties,
        ["machine.yaml=griffe.vitesses.pont_x=0.15", "simulateur.yaml=axes.pont_x.vitesse=0.15"],
        jouer=jouer_le_lot,
    )
    assert comparaison.normal.fini and comparaison.essai.fini
    assert comparaison.normal.alertes == [] and comparaison.normal.refus == ""
    assert comparaison.essai.temps_total_s > comparaison.normal.temps_total_s
    assert "Écart" in comparaison.en_texte()
