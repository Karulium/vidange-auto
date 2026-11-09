"""Tests de la montée en vitesse (tâche 30, fonction 69)."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from vidange.registre import Registre
from vidange.reglages import (
    ErreurReglages,
    ReglagesMonteeVitesse,
    charger_reglages,
    erreurs_montee_vitesse,
    valeur_de_la_machine,
)
from vidange.vitesse import ErreurMontee, MonteeVitesse, appliquer_vitesses

from .test_chef import Banc, Horloge, module_simple, nouveau_chef, tour

CHEMIN_PONT = "griffe.vitesses.pont_x"
CHEMIN_CHARIOT = "griffe.vitesses.chariot_y"


def montee_reglages(**changes) -> ReglagesMonteeVitesse:
    base = {
        "actif": True,
        "palier_pct": 5,
        "cycles_par_palier": 3,
        "paliers_max": 4,
        "etape_de_cycle": "remplissage.ranger",
        "au_recul": "palier",
        "vitesses": {CHEMIN_PONT: 0.30, CHEMIN_CHARIOT: 0.26},
    }
    base.update(changes)
    return ReglagesMonteeVitesse.model_validate(base)


class Temps:
    """Une horloge imaginaire qui avance de 1 s à chaque lecture (les heures se suivent)."""

    def __init__(self) -> None:
        self.t = datetime(2020, 1, 1, 8, 0, 0)

    def __call__(self) -> datetime:
        self.t += timedelta(seconds=1)
        return self.t


@pytest.fixture
def registre(tmp_path):
    return Registre(tmp_path / "registre.sqlite", tmp_path / "photos")


@pytest.fixture
def montee(tmp_path, registre):
    return MonteeVitesse(montee_reglages(), tmp_path / "montee.json", registre, horloge=Temps())


def cycles(montee: MonteeVitesse, nombre: int) -> None:
    for _ in range(nombre):
        montee.sur_etape_finie("remplissage", "ranger", 1.0)


# ---------------------------------------------------------------- les paliers


def test_pas_active_par_defaut_dans_les_reglages_du_depot(reglages):
    programme = charger_reglages(reglages).programme
    assert programme.montee_vitesse is not None
    assert programme.montee_vitesse.actif is False


def test_un_palier_apres_le_bon_nombre_de_cycles(montee):
    cycles(montee, 2)
    assert (montee.palier, montee.cycles) == (0, 2)
    cycles(montee, 1)
    assert (montee.palier, montee.cycles) == (1, 0)
    assert montee.facteur() == 1.05
    # Seule l'étape de cycle compte.
    montee.sur_etape_finie("remplissage", "poser_le_seau", 1.0)
    montee.sur_etape_finie("mycelium", "ranger", 1.0)
    assert montee.cycles == 0


def test_jamais_plus_que_paliers_max(tmp_path, registre):
    montee = MonteeVitesse(
        montee_reglages(paliers_max=2), tmp_path / "m.json", registre, horloge=Temps()
    )
    cycles(montee, 30)
    assert montee.palier == 2


def test_inactive_ne_compte_rien(tmp_path, registre):
    montee = MonteeVitesse(
        montee_reglages(actif=False), tmp_path / "m.json", registre, horloge=Temps()
    )
    cycles(montee, 30)
    montee.sur_alarme(SimpleNamespace(module="x", etape="y"))
    assert (montee.palier, montee.palier_en_vigueur, montee.facteur()) == (0, 0, 1.0)
    assert not (tmp_path / "m.json").exists()


def test_sans_reglage_du_tout(tmp_path):
    montee = MonteeVitesse(None, tmp_path / "m.json")
    cycles(montee, 5)
    assert montee.actif is False
    assert montee.facteur() == 1.0
    assert montee.en_dict() == {"actif": False, "present": False}


# ---------------------------------------------------------------- le recul


def test_alarme_du_chef_recule_d_un_palier(montee):
    cycles(montee, 6)
    assert montee.palier == 2
    montee.sur_alarme(SimpleNamespace(module="remplissage", etape="verser"))
    assert (montee.palier, montee.cycles) == (1, 0)


def test_recul_vers_le_depart_si_regle(tmp_path, registre):
    montee = MonteeVitesse(
        montee_reglages(au_recul="depart"), tmp_path / "m.json", registre, horloge=Temps()
    )
    cycles(montee, 6)
    montee.sur_alarme(SimpleNamespace(module="remplissage", etape="verser"))
    assert montee.palier == 0


def test_une_alerte_du_registre_pendant_les_cycles_fait_reculer(montee, registre):
    cycles(montee, 3)
    assert montee.palier == 1
    # Une alarme d'un autre module (spray...) notée au registre : le cycle suivant recule.
    registre.noter_alarme("spray", "flacon vide")
    cycles(montee, 1)
    assert (montee.palier, montee.cycles) == (0, 0)


def test_l_alarme_du_chef_notee_apres_ne_compte_pas_deux_fois(tmp_path, registre):
    montee = MonteeVitesse(montee_reglages(), tmp_path / "m.json", registre)
    cycles(montee, 6)
    montee.sur_alarme(SimpleNamespace(module="remplissage", etape="verser"))
    assert montee.palier == 1
    # Les bilans notent l'alarme au registre un peu après, puis préviennent la montée.
    registre.noter_alarme("remplissage", "geste raté")
    montee.apres_alarme_notee()
    cycles(montee, 1)
    assert (montee.palier, montee.cycles) == (1, 1)


def test_alarme_au_depart_remet_le_decompte_a_zero(montee):
    cycles(montee, 2)
    montee.sur_alarme(SimpleNamespace(module="a", etape="b"))
    assert (montee.palier, montee.cycles) == (0, 0)


# ---------------------------------------------------------------- noté et annulable


def test_chaque_changement_est_note_au_registre_et_au_journal_des_actions(tmp_path, registre):
    from vidange.api import JournalActions

    actions = JournalActions(tmp_path / "actions.jsonl")
    montee = MonteeVitesse(montee_reglages(), tmp_path / "m.json", registre, actions, Temps())
    cycles(montee, 3)
    lignes = registre.lire("SELECT * FROM reglages_appliques")
    assert len(lignes) == 1
    assert (lignes[0]["reglage"], lignes[0]["ancien"], lignes[0]["nouveau"]) == ("palier", "0", "1")
    assert "3 cycles de suite sans alerte" in lignes[0]["raison"]
    note = actions.dernieres(1)[0]
    assert (note["niveau"], note["avant"], note["apres"]) == ("réglage", 0, 1)


def test_annuler_remet_le_palier_d_avant(montee):
    cycles(montee, 6)
    assert montee.palier == 2
    montee.annuler("karulium")
    assert montee.palier == 1
    # Une annulation ne s'annule pas.
    with pytest.raises(ErreurMontee, match="déjà une annulation"):
        montee.annuler("karulium")


def test_rien_a_annuler_au_debut(montee):
    with pytest.raises(ErreurMontee, match="rien à annuler"):
        montee.annuler("karulium")


def test_le_palier_survit_a_un_redemarrage_et_agit_au_demarrage(tmp_path, registre):
    chemin = tmp_path / "m.json"
    montee = MonteeVitesse(montee_reglages(), chemin, registre, horloge=Temps())
    cycles(montee, 3)
    assert montee.en_dict()["redemarrage_necessaire"] is True
    suivante = MonteeVitesse(montee_reglages(), chemin, registre, horloge=Temps())
    assert (suivante.palier, suivante.palier_en_vigueur) == (1, 1)
    assert suivante.en_dict()["redemarrage_necessaire"] is False


def test_fichier_abime_retour_au_depart(tmp_path):
    chemin = tmp_path / "m.json"
    chemin.write_text("pas du json", encoding="utf-8")
    montee = MonteeVitesse(montee_reglages(), chemin)
    assert montee.palier == 0


def test_palier_au_dessus_du_maximum_est_ramene_au_demarrage(tmp_path):
    chemin = tmp_path / "m.json"
    chemin.write_text(json.dumps({"palier": 9, "cycles": 0, "depuis": None}), encoding="utf-8")
    montee = MonteeVitesse(montee_reglages(paliers_max=2), chemin)
    assert (montee.palier, montee.palier_en_vigueur) == (2, 2)


def test_la_commande_annuler_et_le_programme_partagent_le_fichier(tmp_path, registre):
    chemin = tmp_path / "m.json"
    en_marche = MonteeVitesse(montee_reglages(), chemin, registre, horloge=Temps())
    cycles(en_marche, 6)
    commande = MonteeVitesse(montee_reglages(), chemin, registre, horloge=Temps())
    commande.annuler("commande")
    # Le programme en marche relit le fichier avant de changer : il ne remet pas l'ancien palier.
    cycles(en_marche, 1)
    assert en_marche.palier == 1
    assert en_marche.cycles == 1


# ---------------------------------------------------------------- les vitesses envoyées


def test_les_vitesses_montent_mais_jamais_au_dessus_du_plafond(reglages):
    base = charger_reglages(reglages)
    depart_pont = valeur_de_la_machine(base.machine, CHEMIN_PONT)
    depart_chariot = valeur_de_la_machine(base.machine, CHEMIN_CHARIOT)
    montee = montee_reglages(vitesses={CHEMIN_PONT: depart_pont * 1.06, CHEMIN_CHARIOT: 9.0})
    nouveau = appliquer_vitesses(base, 2, montee)
    # Palier 2 = +10 % : coupé au plafond du pont (+6 %), libre pour le chariot (plafond haut).
    assert valeur_de_la_machine(nouveau.machine, CHEMIN_PONT) == depart_pont * 1.06
    assert valeur_de_la_machine(nouveau.machine, CHEMIN_CHARIOT) == pytest.approx(
        depart_chariot * 1.1
    )


def test_palier_zero_ne_change_rien_et_aucun_autre_reglage_ne_bouge(reglages):
    base = charger_reglages(reglages)
    montee = montee_reglages(vitesses={CHEMIN_PONT: 0.30})
    assert appliquer_vitesses(base, 0, montee) is base
    nouveau = appliquer_vitesses(base, 3, montee)
    avant, apres = base.machine.model_dump(), nouveau.machine.model_dump()
    assert avant["griffe"]["vitesses"]["pont_x"] != apres["griffe"]["vitesses"]["pont_x"]
    apres["griffe"]["vitesses"]["pont_x"] = avant["griffe"]["vitesses"]["pont_x"]
    # Ni zone, ni position, ni seuil, ni autre vitesse : tout le reste est identique.
    assert avant == apres
    assert nouveau.programme == base.programme
    assert nouveau.simulateur == base.simulateur


def test_les_fichiers_de_reglages_ne_sont_jamais_touches(reglages):
    avant = {f.name: f.read_bytes() for f in reglages.glob("*.yaml")}
    appliquer_vitesses(charger_reglages(reglages), 3, montee_reglages())
    assert {f.name: f.read_bytes() for f in reglages.glob("*.yaml")} == avant


# ---------------------------------------------------------------- vérifié au démarrage


def machine_du_depot(reglages):
    return charger_reglages(reglages).machine


def test_chemin_inconnu_refuse(reglages):
    machine = machine_du_depot(reglages)
    with pytest.raises(ErreurReglages, match="n'a pas de « vol »"):
        valeur_de_la_machine(machine, "griffe.vitesses.vol")


@pytest.mark.parametrize(
    "chemin",
    ["griffe.vitesses.descente_lente", "prehension.vitesses.approche", "griffe.vitesses.plongee"],
)
def test_une_vitesse_de_contact_ou_d_approche_est_refusee(reglages, chemin):
    programme = SimpleNamespace(montee_vitesse=montee_reglages(vitesses={chemin: 9.0}))
    erreurs = erreurs_montee_vitesse(machine_du_depot(reglages), programme)
    assert len(erreurs) == 1
    assert "jamais montée" in erreurs[0]


def test_plafond_au_dessous_du_depart_refuse(reglages):
    programme = SimpleNamespace(montee_vitesse=montee_reglages(vitesses={CHEMIN_PONT: 0.01}))
    erreurs = erreurs_montee_vitesse(machine_du_depot(reglages), programme)
    assert "au-dessous de la vitesse de départ" in erreurs[0]


def test_actif_sans_aucune_vitesse_refuse():
    with pytest.raises(ValueError, match="aucune vitesse à monter"):
        montee_reglages(vitesses={})


def test_le_demarrage_refuse_un_plafond_trop_bas_avec_un_message_clair(reglages):
    from vidange.simulateur.essai import copie_provisoire

    copie_provisoire(
        reglages,
        [f"programme.yaml=montee_vitesse.vitesses.{CHEMIN_PONT}=0.01"],
        reglages.parent / "c",
    )
    with pytest.raises(ErreurReglages) as erreur:
        charger_reglages(reglages.parent / "c")
    assert "montee_vitesse → vitesses → griffe.vitesses.pont_x" in str(erreur.value)


# ---------------------------------------------------------------- avec le vrai chef


def test_le_chef_compte_les_cycles_et_recule_sur_alarme(tmp_path, registre):
    horloge, banc = Horloge(), Banc()
    chef = nouveau_chef(horloge)
    montee = MonteeVitesse(
        montee_reglages(etape_de_cycle="essai.un"), tmp_path / "m.json", registre
    )
    chef.sur_etape_finie.append(montee.sur_etape_finie)
    chef.sur_alarme.append(montee.sur_alarme)
    chef.lancer(module_simple(banc))
    banc.drapeaux["pret"] = True
    banc.drapeaux["essai.un_fini"] = True
    for _ in range(4):
        tour(chef, horloge)
    assert montee.cycles == 1
    # Une alarme (étape « deux » trop longue) : le chef appelle la montée.
    chef.donner_go("essai")
    for _ in range(4):
        tour(chef, horloge)
    tour(chef, horloge, 30)
    assert chef.etat().alarmes
    assert (montee.palier, montee.cycles) == (0, 0)


# ---------------------------------------------------------------- la commande « vidange vitesse »


def test_la_commande_dit_l_etat_et_annule(reglages, tmp_path, monkeypatch, capsys):
    from vidange.demarrage import principal

    donnees = tmp_path / "donnees"
    monkeypatch.setenv("VIDANGE_DONNEES", str(donnees))
    monkeypatch.setenv("VIDANGE_REGLAGES", str(reglages))
    # Active la montée dans la copie des réglages et fait monter d'un palier.
    from vidange.simulateur.essai import copie_provisoire

    copie_provisoire(reglages, ["programme.yaml=montee_vitesse.actif=true"], tmp_path / "actifs")
    monkeypatch.setenv("VIDANGE_REGLAGES", str(tmp_path / "actifs"))
    registre = Registre(donnees / "registre.sqlite", donnees / "photos")
    reglages_montee = charger_reglages(tmp_path / "actifs").programme.montee_vitesse
    en_marche = MonteeVitesse(reglages_montee, donnees / "montee_vitesse.json", registre)
    cycles(en_marche, reglages_montee.cycles_par_palier)
    registre.fermer()
    assert principal(["vitesse"]) == 0
    assert "palier 1 sur" in capsys.readouterr().out
    assert principal(["vitesse", "annuler"]) == 0
    sortie = capsys.readouterr().out
    assert "Dernier changement annulé" in sortie
    assert "palier 0 sur" in sortie
    # Une annulation ne s'annule pas.
    assert principal(["vitesse", "annuler"]) == 1
