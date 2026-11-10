"""Tests des plans d'essais seau par seau (tâche 31, fonctions 6 et 76) : lecture et vérification
d'un plan, réglages d'essais.yaml vérifiés au démarrage, plans du Pi (chargé, accepté, lancé,
retiré), valeurs appliquées notées et envoyées, lancement du lot avec son plan, simulateur,
commande « vidange plan » et API."""

import json
import re
import sqlite3
from typing import Any

import pytest
import yaml

from vidange.api import Services
from vidange.cycle.mode_seaux import Lot, ModeSeaux
from vidange.cycle.ordre import verifier_ordre
from vidange.cycle.simulation import PiecesSimulees, jouer_cycle, lot_du_simulateur
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.envois.expediteurs import ExpediteurCulture
from vidange.essais import ErreurPlan, PlansEssais, appliquer, lire_plan
from vidange.essais.envoi import FORMAT, donnees_plan
from vidange.essais.outil import lancer_plan
from vidange.essais.plan import ERREURS_MAX, Application, valeur_lisible
from vidange.essais.variables import MYCELIUM_G, SPRAY, SPRAY_G, VARIABLES
from vidange.fiabilite import Bilans
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import ReglagesBilan, charger_reglages
from vidange.remplissage.module import SeauAFaire
from vidange.simulateur import Simulateur
from vidange.simulateur.essai import ErreurEssai, EssaiEnFond, ResultatLot, essayer_plan
from vidange.spray.spray import ConsigneSpray

from .conftest import DOSSIER_PI
from .test_api import AIDE, CHEF, INVITE, client_connecte, creer_app_de_test
from .test_chef import Horloge, nouveau_chef
from .test_envois import DJANGO_MD, JETON, cles
from .test_reglages import erreur_de, remplacer

REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
ESSAIS = REGLAGES.essais
LISTE_CHEMIN = DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"
EXEMPLE = (DOSSIER_PI / "systeme" / "plan-essais-exemple.yaml").read_text(encoding="utf-8")
VARIETE = "pleurote_grise"
FORMAT_A = "seau_a"


def normal(nom: str, format: str = FORMAT_A) -> Any:
    return VARIABLES[nom].normal(MACHINE, format)


def bornes(nom: str, format: str = FORMAT_A) -> tuple[float, float]:
    return ESSAIS.variables[nom].bornes(format)


def texte_plan(valeurs: Any = None, nom: str = "Essai", **lot: Any) -> str:
    """Un plan d'essais écrit comme un fichier (YAML)."""
    donnees = {
        "nom": nom,
        "auteur": "PC de bureau",
        "lot": {"variete": VARIETE, "format": FORMAT_A, "seaux": 4, **lot},
        "seaux": {1: {MYCELIUM_G: bornes(MYCELIUM_G)[0]}} if valeurs is None else valeurs,
    }
    return yaml.safe_dump(donnees, allow_unicode=True)


def lire(texte: str):
    return lire_plan(texte, MACHINE, ESSAIS)


# ---------------------------------------------------------------- lire un plan


def test_l_exemple_du_depot_est_un_plan_correct():
    plan = lire(EXEMPLE)
    assert (plan.format, plan.variete, plan.seaux) == ("seau_a", "pleurote_grise", 6)
    assert plan.variables == [MYCELIUM_G, SPRAY, SPRAY_G]
    assert plan.vise("seau_a", "pleurote_grise", 6)
    assert not plan.vise("seau_a", "pleurote_grise", 5)
    assert not plan.vise("seau_a", "shiitake", 6)
    # Seau 6 : pas cité, tout est normal (machine.yaml).
    assert plan.valeurs_du_seau(6, MACHINE) == {
        MYCELIUM_G: normal(MYCELIUM_G),
        SPRAY: True,
        SPRAY_G: normal(SPRAY_G),
    }
    # Seau 4 : sans spray, donc pas de dose de spray.
    assert plan.valeurs_du_seau(4, MACHINE) == {MYCELIUM_G: 200.0, SPRAY: False}
    tableau = plan.tableau(MACHINE)
    assert [ligne["numero"] for ligne in tableau] == [1, 2, 3, 4, 5, 6]
    assert tableau[0]["valeurs"][MYCELIUM_G] == {"valeur": 100.0, "normal": False}
    assert tableau[0]["valeurs"][SPRAY] == {"valeur": True, "normal": True}
    assert tableau[4]["valeurs"][SPRAY_G] == {"valeur": 13.0, "normal": False}
    texte = plan.en_texte(MACHINE, ESSAIS)
    assert "Mycélium par couche (g)" in texte and "* = réglage normal" in texte
    # Le plan gardé au registre (JSON) redonne le même plan.
    assert type(plan).depuis(json.loads(plan.en_json())) == plan


def test_valeur_lisible():
    assert [valeur_lisible(v) for v in (None, True, False, 12.5, 3)] == [
        "—",
        "oui",
        "non",
        "12,5",
        "3",
    ]


def au_dela(nom: str, format: str = FORMAT_A) -> float:
    return bornes(nom, format)[1] + 1


@pytest.mark.parametrize(
    ("seaux", "lot", "message"),
    [
        ({1: {"temperature_c": 30}}, {}, "variable « temperature_c » inconnue"),
        ({1: {MYCELIUM_G: "beaucoup"}}, {}, "n'est pas un nombre"),
        ({1: {MYCELIUM_G: float("nan")}}, {}, "n'est pas un nombre"),
        ({1: {MYCELIUM_G: True}}, {}, "n'est pas un nombre"),
        ({1: {SPRAY: "non"}}, {}, "écrire true (oui) ou false (non)"),
        ({1: {SPRAY: False, SPRAY_G: 5}}, {}, "c'est l'un ou l'autre"),
        ({9: {MYCELIUM_G: 100}}, {}, "le lot n'a que 4 seaux"),
        ({"premier": {MYCELIUM_G: 100}}, {}, "un numéro de seau dans le lot"),
        ({1: {}}, {}, "donner ses valeurs"),
        ({}, {}, "« seaux » manque"),
        (None, {"format": "seau_z"}, "format « seau_z » inconnu"),
        (None, {"seaux": 0}, "il faut de 1 à"),
        (None, {"seaux": "six"}, "un nombre entier"),
        (None, {"variete": " "}, "variete manque"),
        (None, {"couleur": "rouge"}, "lot → « couleur » : nom inconnu"),
    ],
)
def test_un_plan_faux_est_refuse_et_dit_pourquoi(seaux, lot, message):
    with pytest.raises(ErreurPlan, match=re.escape(message)):
        lire(texte_plan(seaux, **lot))


def test_les_bornes_d_essais_yaml_sont_appliquees_par_format():
    trop = au_dela(MYCELIUM_G)
    with pytest.raises(ErreurPlan, match="hors des bornes permises pour seau_a"):
        lire(texte_plan({1: {MYCELIUM_G: trop}}))
    # seau_b a ses propres bornes (formats → seau_b).
    bas_b, haut_b = bornes(MYCELIUM_G, "seau_b")
    assert (bas_b, haut_b) != bornes(MYCELIUM_G)
    with pytest.raises(ErreurPlan, match="pour seau_b"):
        lire(texte_plan({1: {MYCELIUM_G: haut_b + 1}}, format="seau_b"))
    assert lire(texte_plan({1: {MYCELIUM_G: haut_b}}, format="seau_b")).valeurs == {
        1: {MYCELIUM_G: haut_b}
    }
    # Bornes comprises.
    bas, haut = bornes(SPRAY_G)
    assert lire(texte_plan({1: {SPRAY_G: bas}, 2: {SPRAY_G: haut}})).valeurs[2] == {SPRAY_G: haut}


def test_toutes_les_erreurs_sont_dites_en_une_fois():
    seaux = {n: {"inconnue": 1} for n in range(1, ERREURS_MAX + 6)}
    with pytest.raises(ErreurPlan) as erreur:
        lire(texte_plan(seaux, seaux=ERREURS_MAX + 5, nom=""))
    assert len(erreur.value.erreurs) == ERREURS_MAX
    assert "« nom » manque" in erreur.value.erreurs[0]
    assert "autre(s) erreur(s)" in str(erreur.value)


@pytest.mark.parametrize(
    ("texte", "message"),
    [
        ("nom: [pas fermé", "fichier mal écrit, ligne"),
        ("- une liste", "le plan doit être une liste de « nom: valeur »"),
        ("nom: a\nnom: b\n", "fichier mal écrit"),
        ("couleur: rouge\n", "« couleur » : nom inconnu"),
    ],
)
def test_un_fichier_mal_ecrit_est_refuse(texte, message):
    with pytest.raises(ErreurPlan, match=re.escape(message)):
        lire(texte)


def test_un_fichier_trop_gros_ou_un_texte_trop_long_est_refuse():
    with pytest.raises(ErreurPlan, match="fichier trop gros"):
        lire("#" * (ESSAIS.fichier_max_ko * 1024 + 1))
    with pytest.raises(ErreurPlan, match="« nom » trop long"):
        lire(texte_plan(nom="x" * (ESSAIS.texte_max + 1)))


def test_un_plan_en_json_est_lu_aussi():
    donnees = yaml.safe_load(texte_plan({"2": {SPRAY: False}}))
    plan = lire(json.dumps(donnees))
    assert plan.valeurs == {2: {SPRAY: False}}


def test_appliquer_le_plan_aux_seaux_du_lot():
    plan = lire(EXEMPLE)
    lot = Lot(FORMAT_A, tuple(SeauAFaire("", FORMAT_A, VARIETE) for _ in range(6)))
    assert lot.plan_essais is None
    avec = appliquer(12, plan, lot, MACHINE)
    assert avec.plan_essais == 12
    assert [s.plan_essais for s in avec.seaux] == [12] * 6
    assert avec.seaux[3].essai == {MYCELIUM_G: 200.0, SPRAY: False}
    assert avec.seaux[5].essai == plan.valeurs_du_seau(6, MACHINE)
    # Le lot d'origine ne change pas.
    assert lot.seaux[0].essai is None
    # Après une coupure, le lot repris (carnet, JSON) garde le plan seau par seau.
    repris = Lot.depuis(json.loads(json.dumps(avec.memoire())))
    assert repris == avec


# ---------------------------------------------------------------- essais.yaml vérifié au démarrage


def test_les_reglages_d_essais_du_depot_sont_des_exemples():
    assert ESSAIS.exemple is True
    # Chaque variable d'essais.yaml est une variable du code, avec le même genre et le même lue_par.
    for nom, variable in ESSAIS.variables.items():
        assert VARIABLES[nom].genre == variable.genre
        assert VARIABLES[nom].lue_par == variable.lue_par


@pytest.mark.parametrize(
    ("ancien", "nouveau", "message"),
    [
        (
            "  spray_g:\n",
            "  vitesse_pont:\n",
            "variables → vitesse_pont : variable inconnue du code",
        ),
        (
            "    genre: oui_non\n",
            "    genre: nombre\n    unite: g\n    min: 1\n    max: 2\n",
            "spray → genre : « nombre », le code dit « oui_non »",
        ),
        (
            "lue_par: vidange/mycelium/mycelium.py, Mycelium.geste_agiter",
            "lue_par: ailleurs.py",
            "mycelium_g → lue_par : « ailleurs.py »",
        ),
        (
            "seau_b: {min: 40",
            "seau_z: {min: 40",
            "formats → seau_z : format absent de machine.yaml",
        ),
        ("    min: 60\n", "    min: 1\n", "doit dépasser mycelium → dose → arret_avant_kg"),
        ("    max: 14\n", "    max: 100000\n", "plus grand qu'un flacon plein"),
        ("    min: 60\n", "    min: 300\n", "doit être plus petit que max"),
        ("    genre: oui_non\n", "    genre: oui_non\n    min: 1\n", "n'a ni unite, ni min"),
        ("seaux_max: 50", "seaux_max: 0", "seaux_max"),
    ],
)
def test_un_essais_yaml_faux_empeche_de_demarrer(reglages, ancien, nouveau, message):
    remplacer(reglages / "essais.yaml", ancien, nouveau)
    assert message in erreur_de(reglages)


def test_un_essais_yaml_sans_la_partie_de_la_machine_est_refuse(reglages):
    texte = (reglages / "machine.yaml").read_text(encoding="utf-8")
    donnees = yaml.safe_load(texte)
    del donnees["spray"]
    (reglages / "machine.yaml").write_text(yaml.safe_dump(donnees, allow_unicode=True))
    assert "machine.yaml n'a pas de partie « spray »" in erreur_de(reglages)


@pytest.mark.parametrize(
    ("ancien", "nouveau", "message"),
    [
        (
            '    adresse: ""',
            '    adresse: "http://serveur/machine/api/cycles/"',
            "adresse_essais vide",
        ),
        (
            'adresse_essais: ""',
            'adresse_essais: "serveur/essais"',
            "adresse_essais « serveur/essais »",
        ),
    ],
)
def test_l_adresse_des_essais_est_verifiee(reglages, ancien, nouveau, message):
    remplacer(reglages / "programme.yaml", ancien, nouveau)
    assert message in erreur_de(reglages)


# ---------------------------------------------------------------- les plans du Pi


@pytest.fixture
def registre(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    yield registre
    registre.fermer()


@pytest.fixture
def plans(registre):
    return PlansEssais(registre, MACHINE, ESSAIS)


def test_un_plan_charge_n_est_qu_une_proposition(plans):
    numero = plans.charger(EXEMPLE, "karulium")
    plan = plans.en_dict(numero)
    assert plan["etat"] == "propose" and plan["charge"]["qui"] == "karulium"
    assert plan["accepte"] is None and plan["seaux_faits"] == 0
    assert plans.accepte() is None
    assert plans.pour_le_lot("seau_a", "pleurote_grise", 6) is None
    assert plans.texte(numero) == EXEMPLE
    assert [v["nom"] for v in plan["variables"]] == [MYCELIUM_G, SPRAY, SPRAY_G]
    assert len(plan["tableau"]) == 6


def test_accepte_il_vise_seulement_son_lot(plans):
    numero = plans.charger(EXEMPLE, "commande")
    plans.accepter(numero, "karulium")
    plan = plans.en_dict(numero)
    assert plan["etat"] == "accepte" and plan["accepte"]["qui"] == "karulium"
    trouve = plans.pour_le_lot("seau_a", "pleurote_grise", 6)
    assert trouve is not None and trouve[0] == numero
    assert plans.pour_le_lot("seau_a", "pleurote_grise", 5) is None
    assert plans.pour_le_lot("seau_b", "pleurote_grise", 6) is None
    assert plans.pour_le_lot("seau_a", "shiitake", 6) is None
    with pytest.raises(ErreurPlan, match="pas à accepter"):
        plans.accepter(numero, "karulium")


def test_un_seul_plan_accepte_a_la_fois(plans):
    premier = plans.charger(EXEMPLE, "commande")
    second = plans.charger(texte_plan(nom="Autre"), "commande")
    plans.accepter(premier, "karulium")
    with pytest.raises(ErreurPlan, match="est déjà accepté"):
        plans.accepter(second, "karulium")
    plans.retirer(premier, "karulium")
    plans.accepter(second, "karulium")
    assert plans.accepte()[0] == second
    # Un plan retiré ne revient pas.
    with pytest.raises(ErreurPlan, match="retiré, pas à accepter"):
        plans.accepter(premier, "karulium")
    assert [p["numero"] for p in plans.liste()] == [second]
    assert [p["numero"] for p in plans.liste(tous=True)] == [second, premier]


def test_accepter_revérifie_avec_les_bornes_du_jour(registre):
    numero = PlansEssais(registre, MACHINE, ESSAIS).charger(EXEMPLE, "commande")
    # Karulium a resserré les bornes depuis l'arrivée du plan.
    variable = ESSAIS.variables[MYCELIUM_G].model_copy(update={"max": 150.0})
    serres = ESSAIS.model_copy(update={"variables": {**ESSAIS.variables, MYCELIUM_G: variable}})
    with pytest.raises(ErreurPlan, match="hors des bornes"):
        PlansEssais(registre, MACHINE, serres).accepter(numero, "karulium")


def test_trop_de_plans_proposes_est_refuse(registre):
    plans = PlansEssais(registre, MACHINE, ESSAIS.model_copy(update={"proposes_max": 2}))
    plans.charger(EXEMPLE, "a")
    plans.charger(EXEMPLE, "b")
    with pytest.raises(ErreurPlan, match="déjà 2 plans chargés"):
        plans.charger(EXEMPLE, "c")


def test_un_plan_inconnu(plans):
    with pytest.raises(ErreurPlan, match="plan d'essais n° 99 inconnu"):
        plans.en_dict(99)
    with pytest.raises(ErreurPlan, match="inconnu"):
        plans.accepter(99, "karulium")


def test_lance_il_ne_peut_plus_etre_retire_sauf_go_rate(plans):
    numero = plans.charger(EXEMPLE, "commande")
    with pytest.raises(ErreurPlan):
        plans.lancer(numero, "écran")  # pas encore accepté
    plans.accepter(numero, "karulium")
    plans.lancer(numero, "écran")
    plan = plans.en_dict(numero)
    assert plan["etat"] == "lance" and plan["lance"]["qui"] == "écran"
    assert plans.accepte() is None
    with pytest.raises(ErreurPlan, match="il ne peut plus être retiré"):
        plans.retirer(numero, "karulium")
    # Le lot n'a pas pu partir : le plan redevient accepté.
    plans.defaire_lancement(numero)
    plan = plans.en_dict(numero)
    assert plan["etat"] == "accepte" and plan["lance"] is None


def test_les_valeurs_appliquees_sont_notees_et_partent_au_logiciel_de_culture(plans, registre):
    numero = plans.charger(EXEMPLE, "commande")
    plans.accepter(numero, "karulium")
    plans.lancer(numero, "écran")
    plans.noter(numero, Application(1, "S301", MYCELIUM_G, 100.0, 98.5, "g", 1))
    plans.noter(numero, Application(6, "S306", MYCELIUM_G, 150.0, 151.0, "g", 1))
    plans.noter(numero, Application(4, None, SPRAY, False, 0.0, remarque="sans spray"))
    plan = plans.en_dict(numero)
    assert plan["seaux_faits"] == 3
    premier, sixieme, quatrieme = plan["appliques"]
    assert (premier["seau"], premier["voulu"], premier["mesure"]) == ("S301", 100.0, 98.5)
    assert premier["remarque"] == "plan"
    assert sixieme["remarque"] == "réglage normal"
    assert quatrieme["voulu"] is False and quatrieme["remarque"] == "plan ; sans spray"
    # Un seul envoi en attente pour le plan (il part de plus en plus complet).
    envois = registre.lire("SELECT * FROM envois WHERE sorte = 'essais'")
    assert len(envois) == 1 and envois[0]["objet"] == str(numero)
    assert envois[0]["destination"] == "culture"
    # Une valeur appliquée ne s'efface jamais.
    with pytest.raises(ErreurRegistre, match="ne se supprime pas"):
        with registre._ecriture() as cnx:
            cnx.execute("DELETE FROM essais_appliques")


def test_une_valeur_pas_notee_ne_fait_pas_tomber_le_lot(plans, caplog):
    plans.noter(42, Application(1, "S1", MYCELIUM_G, 100.0))
    assert "valeur appliquée pas notée" in caplog.text


def test_un_vieux_plan_dont_la_variable_a_disparu_se_montre_encore(registre):
    numero = PlansEssais(registre, MACHINE, ESSAIS).charger(EXEMPLE, "commande")
    sans_spray_g = {n: v for n, v in ESSAIS.variables.items() if n != SPRAY_G}
    essais = ESSAIS.model_copy(update={"variables": sans_spray_g})
    plan = PlansEssais(registre, MACHINE, essais).en_dict(numero)
    assert plan["variables"][2] == {"nom": SPRAY_G, "libelle": SPRAY_G, "unite": ""}


def test_la_montee_du_registre_garde_la_file_et_accepte_les_essais(tmp_path):
    from vidange.registre import montees

    chemin = tmp_path / "registre.sqlite"
    with sqlite3.connect(chemin) as cnx:
        for montee in montees.MONTEES[:11]:
            for requete in montee:
                cnx.execute(requete)
        cnx.execute(
            "INSERT INTO envois (cle, destination, sorte, objet, cree_le, contenu) "
            "VALUES ('c1', 'ntfy', 'message', 'alarme:1', '2026-11-01', '{}')"
        )
        cnx.execute("PRAGMA user_version = 11")
    cnx.close()
    registre = Registre(chemin, tmp_path / "photos")
    try:
        (vieux,) = registre.lire("SELECT * FROM envois")
        assert (vieux["cle"], vieux["sorte"], vieux["contenu"]) == ("c1", "message", "{}")
        plans = PlansEssais(registre, MACHINE, ESSAIS)
        numero = plans.charger(EXEMPLE, "commande")
        plans.noter(numero, Application(1, None, SPRAY, True, 1.0))
        assert registre.lire("SELECT sorte FROM envois ORDER BY id")[1]["sorte"] == "essais"
    finally:
        registre.fermer()


# ---------------------------------------------------------------- envoi au logiciel de culture


def remplir_un_plan(plans: PlansEssais) -> int:
    numero = plans.charger(EXEMPLE, "commande")
    plans.accepter(numero, "karulium")
    plans.lancer(numero, "écran")
    plans.noter(numero, Application(1, "S1293", MYCELIUM_G, 100.0, 98.5, "g", 1))
    plans.noter(numero, Application(1, "S1293", SPRAY, True, 1.0, remarque="dose faite"))
    return numero


def test_donnees_d_un_plan_envoye(plans, registre):
    numero = remplir_un_plan(plans)
    culture = REGLAGES.programme.envois.culture
    expediteur = ExpediteurCulture(culture, JETON, registre)
    (envoi,) = registre.lire("SELECT * FROM envois WHERE sorte = 'essais'")
    assert expediteur.adresse(envoi) == culture.adresse_essais
    donnees = expediteur.donnees(envoi)
    assert donnees == donnees_plan(
        registre, numero, envoi["cle"], culture.machine, expediteur._fuseau
    )
    assert donnees["format"] == FORMAT and donnees["cle"] == envoi["cle"]
    plan = donnees["plan"]
    assert plan["numero"] == numero and plan["etat"] == "lance"
    assert plan["lot"] == {"variete": "pleurote_grise", "format": "seau_a", "seaux": 6}
    assert plan["prevu"]["4"] == {MYCELIUM_G: 200, SPRAY: False}
    (seau,) = donnees["seaux"]
    assert seau["numero"] == 1 and seau["seau"] == "S1293"
    assert [v["variable"] for v in seau["valeurs"]] == [MYCELIUM_G, SPRAY]
    assert seau["valeurs"][0]["mesure"] == 98.5 and seau["valeurs"][1]["voulu"] is True
    # Heure locale sans fuseau, comme les cycles.
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", seau["valeurs"][0]["quand"])


def test_l_exemple_des_essais_de_django_md_a_exactement_les_champs_envoyes(plans, registre):
    """Le format des plans d'essais écrit dans docs/django.md et celui du code ne divergent pas."""
    texte = DJANGO_MD.read_text(encoding="utf-8")
    partie = texte[texte.index("## Les plans d'essais appliqués") :]
    exemple = json.loads(re.search(r"```json\n(.*?)\n```", partie, re.DOTALL).group(1))
    remplir_un_plan(plans)
    (envoi,) = registre.lire("SELECT * FROM envois WHERE sorte = 'essais'")
    envoye = ExpediteurCulture(REGLAGES.programme.envois.culture, JETON, registre).donnees(envoi)
    # « prevu » : n° de seau → variable → valeur ; ses clés dépendent du plan.
    for donnees in (exemple, envoye):
        prevu = donnees["plan"].pop("prevu")
        assert all(n.isdigit() and set(v) <= set(VARIABLES) for n, v in prevu.items())
    assert cles(exemple) == cles(envoye)
    assert exemple["format"] == FORMAT


# ---------------------------------------------------------------- dans le cycle


def test_verifier_ordre_sait_qu_un_seau_sans_spray_ne_passe_pas_au_spray():
    from vidange.cycle.ordre import Poste

    ordre = (
        Poste("debut", "début du seau", ("r.debut",), coeur=True),
        Poste("spray", "spray", ("r.spray",)),
        Poste("fin", "fin du seau", ("r.fin",), coeur=True),
    )
    faites = ["r.debut", "r.spray", "r.fin", "r.debut", "r.fin"]
    lances = ["debut", "spray", "fin"]
    assert verifier_ordre(faites, lances, ordre, "r.debut") != []
    assert verifier_ordre(faites, lances, ordre, "r.debut", sans={2: ("spray",)}) == []


def test_la_consigne_du_plan_pour_le_spray(tmp_path):
    from .test_spray import Banc

    banc = Banc(tmp_path)
    try:
        banc.pret()
        # Sans spray : rien ne se pompe, c'est noté comme tel.
        assert (
            banc.spray.preparer("S1", "seau_a", ConsigneSpray(sans_spray="plan d'essais")) is None
        )
        assert banc.spray.resultat.issue == "sans_spray"
        assert "plan d'essais" in banc.spray.resultat.texte
        # Une autre dose que celle du format.
        bas, _ = bornes(SPRAY_G)
        dose = banc.spray.preparer("S2", "seau_a", ConsigneSpray(dose_g=bas))
        assert dose is not None and dose.dose_g == bas
        assert dose.dose_g != normal(SPRAY_G)
    finally:
        banc.materiel.fermer()


@pytest.fixture(scope="module")
def liste():
    return charger_entrees_sorties(LISTE_CHEMIN)


class FauxPlans:
    """Reçoit ce que le mode seaux note (à la place du registre)."""

    def __init__(self) -> None:
        self.notes: list[tuple[int, Application]] = []

    def noter(self, numero: int, application: Application) -> None:
        self.notes.append((numero, application))


def test_le_lot_simule_applique_le_plan_seau_par_seau(liste):
    """Le même code que la machine : chaque seau reçoit son mycélium et son spray du plan, et ce
    qui est vraiment fait est noté."""
    cycle = REGLAGES.simulateur.cycle
    bas, haut = bornes(MYCELIUM_G, cycle.format)
    plan = lire(
        texte_plan(
            {
                1: {MYCELIUM_G: bas},
                2: {MYCELIUM_G: haut, SPRAY: False},
                3: {SPRAY_G: bornes(SPRAY_G)[0]},
            },
            format=cycle.format,
            variete=cycle.variete,
            seaux=cycle.seaux,
        )
    )
    faux = FauxPlans()
    with Simulateur(REGLAGES, liste, "cycle") as simulateur:
        mode = ModeSeaux(REGLAGES, PiecesSimulees(simulateur), simulateur.chef, plans=faux)
        lot = appliquer(7, plan, lot_du_simulateur(simulateur), MACHINE)
        planning = simulateur.jouer(mode.modules_du_lot(lot))
        doses = list(mode.en_cours.pieces.mycelium.doses)
    assert planning.fini, planning.probleme
    assert {numero for numero, _ in faux.notes} == {7}
    par_seau: dict[int, dict[str, list[Application]]] = {}
    for _, application in faux.notes:
        par_seau.setdefault(application.numero, {}).setdefault(application.variable, []).append(
            application
        )
    couches = MACHINE.griffe.formats[cycle.format].couches
    # Seau 1 : la dose basse sur chaque couche, pesée.
    mycelium_1 = par_seau[1][MYCELIUM_G]
    assert all(a.voulu == bas and a.unite == "g" for a in mycelium_1)
    assert [a.couche for a in mycelium_1] == list(range(1, couches + 1))
    assert all(a.mesure is not None and a.mesure >= bas * 0.9 for a in mycelium_1)
    # Seau 2 : dose haute et pas de spray.
    assert all(a.voulu == haut for a in par_seau[2][MYCELIUM_G])
    (spray_2,) = par_seau[2][SPRAY]
    assert spray_2.voulu is False and spray_2.mesure == 0.0
    assert SPRAY_G not in par_seau[2]
    # Seau 3 : une autre dose de spray, le poids vraiment perdu noté.
    (spray_g_3,) = par_seau[3][SPRAY_G]
    assert spray_g_3.mesure == pytest.approx(bornes(SPRAY_G)[0], abs=0.5)
    # Les doses de mycélium versées suivent le plan.
    premier = [d for d in doses if d.seau == mycelium_1[0].seau]
    assert premier and all(d.kg * 1000 == pytest.approx(bas, abs=bas * 0.1) for d in premier)


def test_jouer_cycle_avec_un_plan_verifie_l_ordre_sans_le_spray(liste):
    cycle = REGLAGES.simulateur.cycle
    plan = lire(
        texte_plan(
            {2: {SPRAY: False}}, format=cycle.format, variete=cycle.variete, seaux=cycle.seaux
        )
    )
    with Simulateur(REGLAGES, liste, "cycle") as simulateur:
        _, planning, problemes = jouer_cycle(simulateur, plan=plan)
    assert planning.fini and problemes == []


def test_essayer_un_plan_au_simulateur(reglages, entrees_sorties):
    appels = []

    def faux_lot(r, liste, plan=None) -> ResultatLot:
        appels.append((r.simulateur.cycle.seaux, r.simulateur.cycle.variete, plan))
        return ResultatLot(fini=True, temps_total_s=1000.0 if plan is None else 1100.0)

    comparaison = essayer_plan(reglages, entrees_sorties, EXEMPLE, jouer=faux_lot)
    # Le lot du plan (6 seaux) joué normal, puis avec le plan.
    assert [a[:2] for a in appels] == [(6, "pleurote_grise")] * 2
    assert appels[0][2] is None and appels[1][2] is not None
    texte = comparaison.en_texte()
    assert "Essai d'un plan d'essais dans le simulateur" in texte
    assert "essai-plan-essais.md" in texte
    assert comparaison.en_dict()["plan"].startswith("Plan « Dose de mycélium")


def test_essayer_un_plan_refuse_un_plan_faux_ou_un_autre_format(reglages, entrees_sorties):
    with pytest.raises(ErreurEssai, match="hors des bornes"):
        essayer_plan(reglages, entrees_sorties, texte_plan({1: {MYCELIUM_G: au_dela(MYCELIUM_G)}}))
    with pytest.raises(ErreurEssai, match="ne joue que des lots « seau_a »"):
        essayer_plan(reglages, entrees_sorties, texte_plan(format="seau_b"))


def test_un_vrai_essai_du_plan_au_simulateur(reglages, entrees_sorties):
    comparaison = essayer_plan(reglages, entrees_sorties, EXEMPLE)
    assert comparaison.normal.fini and comparaison.essai.fini, comparaison.en_texte()
    assert comparaison.sans_probleme, comparaison.en_texte()
    # Le mycélium versé : le plan (100 g aux seaux 1 et 2, 200 g aux seaux 3 et 4).
    doses = list(comparaison.essai.doses.values())
    assert doses[0][0] == pytest.approx(100, abs=10)
    assert doses[2][0] == pytest.approx(200, abs=20)
    assert "Mycélium versé dans le lot avec le plan" in comparaison.en_texte()


# ---------------------------------------------------------------- lancement du lot avec son plan


@pytest.fixture
def machine(liste):
    from .test_cycle_lot import Machine, remplir_le_stockage

    machine = Machine(liste)
    remplir_le_stockage(machine.stockage)
    yield machine
    machine.fermer()


def lancement_avec(machine, plans):
    from vidange.cycle import Lancement

    from .test_cycle_lot import FauxFond

    return Lancement(
        REGLAGES.programme.lot,
        MACHINE,
        machine.mode_seaux(),
        None,
        machine.stockage,
        FauxFond([]),
        plans=plans,
    )


def test_le_go_montre_le_plan_et_le_lot_part_avec(machine, plans):
    numero = plans.charger(EXEMPLE, "commande")
    lancement = lancement_avec(machine, plans)
    lancement.proposer_seaux(FORMAT_A, 6, VARIETE, "page web")
    # Plan pas encore accepté : rien.
    assert lancement.en_dict()["plan_essais"] is None
    assert "plan d'essais" not in lancement.texte_ecran()[1]
    plans.accepter(numero, "karulium")
    etat = lancement.en_dict()
    # La carte du lot (onglet État) montre le plan et son tableau avant le Go.
    apercu = etat["plan_essais"]
    assert apercu["numero"] == numero and apercu["nom"] == "Dose de mycélium et spray, exemple"
    assert (
        len(apercu["tableau"]) == 6 and apercu["variables"][0]["libelle"] == "Mycélium par couche"
    )
    assert etat["plan_accepte"]["numero"] == numero
    assert "Avec plan d'essais : Dose de mycélium" in lancement.texte_ecran()[1]
    lancement.go("écran")
    assert plans.en_dict(numero)["etat"] == "lance"
    assert "avec plan d'essais" in lancement.dernier
    seaux = lancement.mode_seaux.en_cours.pieces.plan.seaux
    assert [s.plan_essais for s in seaux] == [numero] * 6
    assert seaux[3].essai == {MYCELIUM_G: 200.0, SPRAY: False}


def test_un_plan_pour_un_autre_lot_ne_part_pas(machine, plans):
    numero = plans.charger(EXEMPLE, "commande")
    plans.accepter(numero, "karulium")
    lancement = lancement_avec(machine, plans)
    lancement.proposer_seaux(FORMAT_A, 5, VARIETE, "page web")
    etat = lancement.en_dict()
    assert etat["plan_essais"] is None and etat["plan_accepte"]["numero"] == numero
    lancement.go("écran")
    assert plans.en_dict(numero)["etat"] == "accepte"
    assert all(s.plan_essais is None for s in lancement.mode_seaux.en_cours.pieces.plan.seaux)


def test_un_plan_retire_avant_le_go_ne_part_pas(machine, plans):
    numero = plans.charger(EXEMPLE, "commande")
    plans.accepter(numero, "karulium")
    lancement = lancement_avec(machine, plans)
    lancement.proposer_seaux(FORMAT_A, 6, VARIETE, "page web")
    plans.retirer(numero, "karulium")
    lancement.go("écran")
    assert plans.en_dict(numero)["lance"] is None


def test_un_lot_qui_ne_part_pas_rend_son_plan(machine, plans, monkeypatch):
    from vidange.chef import ErreurChef

    numero = plans.charger(EXEMPLE, "commande")
    plans.accepter(numero, "karulium")
    lancement = lancement_avec(machine, plans)
    lancement.proposer_seaux(FORMAT_A, 6, VARIETE, "page web")

    def rate(lot):
        raise ErreurChef("carte muette")

    monkeypatch.setattr(lancement.mode_seaux, "lancer_lot", rate)
    with pytest.raises(ErreurChef, match="carte muette"):
        lancement.go("écran")
    assert plans.en_dict(numero)["etat"] == "accepte"
    assert lancement.fond.arrets == 1


# ---------------------------------------------------------------- commande « vidange plan »


@pytest.fixture
def commande(tmp_path, reglages, entrees_sorties):
    donnees = tmp_path / "donnees"
    donnees.mkdir()
    fichier = tmp_path / "plan.yaml"
    fichier.write_text(EXEMPLE, encoding="utf-8")

    def lancer(*arguments: str) -> int:
        return lancer_plan(list(arguments), donnees, reglages, entrees_sorties)

    lancer.fichier = str(fichier)
    lancer.donnees = donnees
    return lancer


def test_la_commande_verifie_charge_montre_et_retire(commande, capsys):
    assert commande("verifier", commande.fichier) == 0
    sortie = capsys.readouterr().out
    assert "Plan correct (pas gardé" in sortie and "Mycélium par couche" in sortie
    assert commande() == 0
    assert "Aucun plan d'essais" in capsys.readouterr().out
    assert commande("charger", commande.fichier) == 0
    assert "Plan chargé : n° 1" in capsys.readouterr().out
    assert commande("liste") == 0
    sortie = capsys.readouterr().out
    assert (
        "n° 1 : « Dose de mycélium et spray, exemple »" in sortie and "pas encore accepté" in sortie
    )
    assert commande("montrer", "1") == 0
    assert "chargé, pas encore accepté" in capsys.readouterr().out
    assert commande("retirer", "1") == 0
    assert commande("retirer", "1") == 1
    assert "il ne peut plus être retiré" in capsys.readouterr().err


def test_la_commande_montre_les_valeurs_appliquees(commande, capsys, reglages):
    assert commande("charger", commande.fichier) == 0
    registre = Registre(commande.donnees / "registre.sqlite", commande.donnees / "photos")
    try:
        plans = PlansEssais(registre, MACHINE, ESSAIS)
        plans.accepter(1, "karulium")
        plans.lancer(1, "écran")
        plans.noter(1, Application(1, "S301", MYCELIUM_G, 100.0, 98.5, "g", 2))
    finally:
        registre.fermer()
    capsys.readouterr()
    assert commande("montrer", "1") == 0
    sortie = capsys.readouterr().out
    assert "Valeurs vraiment appliquées" in sortie
    assert "seau n° 1 (S301) : mycelium_g = 100.0, mesuré 98.5 g, couche 2 (plan)" in sortie


def test_la_commande_refuse_un_plan_faux(commande, capsys, tmp_path):
    faux = tmp_path / "faux.yaml"
    faux.write_text(texte_plan({1: {"temperature_c": 30}}), encoding="utf-8")
    assert commande("verifier", str(faux)) == 1
    assert "variable « temperature_c » inconnue" in capsys.readouterr().err
    assert commande("charger", str(faux)) == 1
    assert commande("verifier", str(tmp_path / "absent.yaml")) == 1
    assert "fichier illisible" in capsys.readouterr().err
    assert commande("montrer", "un") == 1
    assert "donner le n° du plan" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        commande("montrer")


def test_la_commande_dit_des_reglages_faux(commande, reglages, capsys):
    remplacer(reglages / "essais.yaml", "  spray_g:\n", "  vitesse_pont:\n")
    assert commande() == 2
    assert "vitesse_pont" in capsys.readouterr().err


def test_vidange_plan_passe_par_les_commandes_a_part(
    commande, reglages, entrees_sorties, monkeypatch
):
    from vidange.demarrage import COMMANDES_A_PART, lancer_commande_a_part

    assert "plan" in COMMANDES_A_PART
    monkeypatch.setenv("VIDANGE_DONNEES", str(commande.donnees))
    monkeypatch.setenv("VIDANGE_REGLAGES", str(reglages))
    monkeypatch.setenv("VIDANGE_ENTREES_SORTIES", str(entrees_sorties))
    assert lancer_commande_a_part("plan", ["verifier", commande.fichier]) == 0


# ---------------------------------------------------------------- l'API de la page


class BancApi:
    def __init__(self, dossier, reglages, entrees_sorties) -> None:
        horloge = Horloge()
        self.chef = nouveau_chef(horloge)
        self.registre = Registre(dossier / "registre.sqlite", dossier / "photos")
        bilans = Bilans(dossier, ReglagesBilan(lignes_journal=0), self.registre, self.chef)
        self.plans = PlansEssais(self.registre, MACHINE, ESSAIS)
        self.joues: list = []

        def jouer(r, liste, plan=None):
            self.joues.append(plan)
            return ResultatLot(fini=True, temps_total_s=100.0)

        essai = EssaiEnFond(reglages, entrees_sorties, jouer=jouer, en_fond=False)
        services = Services(
            self.chef,
            self.registre,
            bilans.acquitter,
            checklist=lambda: [],
            essai=essai,
            plans=self.plans,
        )
        self.app = creer_app_de_test(services, dossier)

    def client(self, nom=CHEF):
        return client_connecte(self.app, nom)


@pytest.fixture
def banc(tmp_path, reglages, entrees_sorties):
    banc = BancApi(tmp_path, reglages, entrees_sorties)
    yield banc
    banc.registre.fermer()


def test_l_api_des_plans_demande_le_role_regler(banc):
    for nom in (AIDE, INVITE):
        client = banc.client(nom)
        assert client.get("/api/plans-essais").status_code == 403
        assert client.post("/api/plans-essais", json={"texte": EXEMPLE}).status_code == 403
    numero = banc.plans.charger(EXEMPLE, "commande")
    assert banc.client(AIDE).post(f"/api/plans-essais/{numero}/accepter").status_code == 403
    assert banc.plans.en_dict(numero)["etat"] == "propose"


def test_charger_accepter_retirer_depuis_la_page(banc):
    client = banc.client()
    etat = client.get("/api/plans-essais").json()
    assert etat["plans"] == [] and etat["exemple"] is True
    assert [v["nom"] for v in etat["variables"]] == list(ESSAIS.variables)
    plan = client.post("/api/plans-essais", json={"texte": EXEMPLE}).json()
    assert plan["etat"] == "propose" and "chef" in plan["charge"]["qui"]
    numero = plan["numero"]
    plan = client.post(f"/api/plans-essais/{numero}/accepter").json()
    assert plan["etat"] == "accepte" and "chef" in plan["accepte"]["qui"]
    # Déjà accepté : refus clair (409).
    reponse = client.post(f"/api/plans-essais/{numero}/accepter")
    assert reponse.status_code == 409 and "pas à accepter" in reponse.json()["detail"]
    plan = client.post(f"/api/plans-essais/{numero}/retirer").json()
    assert plan["etat"] == "retire"
    assert client.get("/api/plans-essais").json()["plans"] == []


def test_un_plan_faux_envoye_par_la_page_est_refuse(banc):
    reponse = banc.client().post(
        "/api/plans-essais", json={"texte": texte_plan({1: {"temperature_c": 30}})}
    )
    assert reponse.status_code == 409
    assert "temperature_c" in reponse.json()["detail"]
    assert banc.client().post("/api/plans-essais/7/accepter").status_code == 409


def test_essayer_un_plan_depuis_la_page(banc):
    numero = banc.plans.charger(EXEMPLE, "commande")
    etat = banc.client().post(f"/api/plans-essais/{numero}/essayer").json()
    assert etat["en_cours"] is False and etat["erreur"] is None
    assert etat["resultat"]["plan"].startswith("Plan « Dose de mycélium")
    assert banc.joues[0] is None and banc.joues[1].nom == "Dose de mycélium et spray, exemple"


def test_sans_plans_sur_ce_programme_l_api_le_dit(tmp_path):
    horloge = Horloge()
    chef = nouveau_chef(horloge)
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    try:
        bilans = Bilans(tmp_path, ReglagesBilan(lignes_journal=0), registre, chef)
        app = creer_app_de_test(
            Services(chef, registre, bilans.acquitter, checklist=lambda: []), tmp_path
        )
        assert client_connecte(app, CHEF).get("/api/plans-essais").status_code == 404
    finally:
        registre.fermer()
