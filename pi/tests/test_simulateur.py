"""Simulateur de cycle : le vrai chef rejoue le module d'exemple sur la machine imaginaire."""

import json
from dataclasses import replace

import pytest

from vidange.chef.exemple import module_exemple
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.reglages import charger_reglages
from vidange.simulateur import ErreurSimulation, Simulateur, duree_trajet, taches
from vidange.simulateur.outil import main
from vidange.simulateur.planning import duree_lisible, heure_lisible
from vidange.simulateur.solveur import ordonner

from .conftest import DOSSIER_PI
from .test_reglages import erreur_de, remplacer

LISTE = DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"

# Réglages d'exemple : x 0 → 0,8 m à 0,5 m/s et 1 m/s² = 2,1 s ; y 0 → 0,5 m = 1,5 s ;
# z 0,05 → 1,0 m à 0,3 m/s et 0,5 m/s² = 0,95 / 0,3 + 0,6 s. Le plus long : z.
ALLER_AU_REPOS = 0.95 / 0.3 + 0.3 / 0.5
# Repos ↔ zone A : x 0,5 m = 1,5 s, y 0,3 m = 0,6 + 0,5 = 1,1 s, z 0,1 m = 2 × √0,2 = 0,89 s.
REPOS_ZONE_A = 1.5


def simuler(dossier=DOSSIER_PI / "reglages", modules=1):
    reglages = charger_reglages(dossier)
    with Simulateur(reglages, charger_entrees_sorties(LISTE)) as simulateur:
        premier = module_exemple(simulateur.axes(), simulateur.materiel)
        autres = [
            replace(module_exemple(simulateur.axes(), simulateur.materiel), nom=f"exemple_{n}")
            for n in range(2, modules + 1)
        ]
        return simulateur.jouer([premier, *autres])


def test_duree_d_un_trajet():
    assert duree_trajet(0, 0.5, 1) == 0
    # Long : accélération (0,5 s), palier, freinage (0,5 s) ; la distance de 0,25 m s'y perd.
    assert duree_trajet(1.0, 0.5, 1.0) == pytest.approx(2.5)
    assert duree_trajet(-1.0, 0.5, 1.0) == pytest.approx(2.5)
    # Court : pas le temps d'atteindre la vitesse.
    assert duree_trajet(0.04, 0.5, 1.0) == pytest.approx(0.4)


def test_cycle_complet_de_l_exemple():
    planning = simuler()
    assert planning.fini and planning.probleme == ""
    assert planning.exemple
    assert [ligne.etape for ligne in planning.lignes] == [
        "aller_au_repos",
        "entrer_dans_la_zone_a",
        "revenir_au_repos",
    ]
    repos, zone, retour = planning.lignes
    # Le panneau est fermé 10 s après le début (simulateur.yaml) : l'étape 1 l'attend.
    assert repos.debut == 0 and repos.action == pytest.approx(10)
    assert repos.attentes == ["panneau du poste du fût fermé"]
    assert repos.geste == pytest.approx(ALLER_AU_REPOS)
    assert repos.mouvements[0].axes["exemple_z"] == (0.05, 1.0)
    # L'étape 2 demande le Go ; Karulium le donne 20 s plus tard (delai_go_s).
    assert zone.debut == repos.fin
    assert zone.go == pytest.approx(zone.debut + 20)
    assert zone.attente_go == pytest.approx(20)
    assert zone.zones == ("exemple_zone_a",)
    assert zone.geste == pytest.approx(REPOS_ZONE_A)
    assert retour.go is None and retour.zones == ("exemple_zone_a",)
    assert retour.fin == planning.temps_total
    assert planning.temps_total == pytest.approx(10 + ALLER_AU_REPOS + 20 + 2 * REPOS_ZONE_A)
    assert planning.evenements == [(10, "capteur « reed_panneau_poste_fut » actionné")]

    texte = planning.en_texte()
    assert "Temps total : 36,8 s" in texte
    assert "attend le Go de Karulium : 20,0 s" in texte
    assert "réglages d'EXEMPLE" in texte
    donnees = json.loads(json.dumps(planning.en_dict()))
    assert donnees["temps_total_s"] == round(planning.temps_total, 3)
    assert donnees["etapes"][1]["zones"] == ["exemple_zone_a"]


def test_les_durees_se_reglent(reglages):
    remplacer(reglages / "simulateur.yaml", "delai_go_s: 20", "delai_go_s: 0")
    remplacer(reglages / "simulateur.yaml", "attente_s: 10", "attente_s: 0")
    remplacer(reglages / "simulateur.yaml", "exemple_z: {vitesse: 0.3", "exemple_z: {vitesse: 0.5")
    remplacer(reglages / "simulateur.yaml", "acceleration: 0.5}", "acceleration: 1.0}")
    planning = simuler(reglages)
    # Plus d'attente ; z aussi rapide que x et y : 0,95 m = 2,4 s ; puis 2 × 1,5 s.
    assert planning.temps_total == pytest.approx(0.95 / 0.5 + 0.5 + 2 * REPOS_ZONE_A)


def test_depart_a_une_position(reglages):
    remplacer(reglages / "simulateur.yaml", "depart: griffe_attente", "depart: exemple_repos")
    planning = simuler(reglages)
    # Déjà au repos : le premier geste ne dure rien.
    assert planning.lignes[0].geste == 0


def test_cycle_bloque(reglages):
    # Personne ne ferme le panneau : l'étape 1 attend jusqu'à « duree_max_s ».
    remplacer(reglages / "simulateur.yaml", "duree_max_s: 21600", "duree_max_s: 60")
    texte = (reglages / "simulateur.yaml").read_text(encoding="utf-8")
    (reglages / "simulateur.yaml").write_text(
        texte.split("evenements:")[0] + "evenements: []\n", encoding="utf-8"
    )
    planning = simuler(reglages)
    assert not planning.fini
    assert planning.temps_total == 60
    assert "bloqué" in planning.probleme
    assert "attend : panneau du poste du fût fermé" in planning.probleme
    assert planning.lignes[0].fin is None
    assert "CYCLE ARRÊTÉ à 01:00,0" in planning.en_texte()


def test_alarme_d_une_etape_trop_longue(reglages):
    # Délai maximal (machine.yaml) plus court que le geste simulé : le vrai chef lève l'alarme.
    remplacer(
        reglages / "machine.yaml", "exemple_deplacement_max: 30", "exemple_deplacement_max: 2"
    )
    planning = simuler(reglages)
    assert not planning.fini
    assert "alarme de « exemple », étape « aller_au_repos »" in planning.probleme
    assert "trop long" in planning.probleme


def test_axe_sans_vitesse_dans_le_simulateur(reglages):
    remplacer(reglages / "simulateur.yaml", "  exemple_y: {vitesse: 0.5, acceleration: 1.0}\n", "")
    planning = simuler(reglages)
    assert "exemple_y" in planning.probleme and "simulateur.yaml" in planning.probleme


def test_deux_modules_se_partagent_la_zone():
    planning = simuler(modules=2)
    assert planning.fini
    premier = {ligne.etape: ligne for ligne in planning.lignes if ligne.module == "exemple"}
    second = {ligne.etape: ligne for ligne in planning.lignes if ligne.module == "exemple_2"}
    attente = "zone « exemple_zone_a » libre (tenue par « exemple »)"
    assert attente in second["entrer_dans_la_zone_a"].attentes
    assert second["entrer_dans_la_zone_a"].action >= premier["revenir_au_repos"].fin
    assert planning.temps_total > premier["revenir_au_repos"].fin


def test_capteur_ou_etape_inconnus(reglages):
    remplacer(reglages / "simulateur.yaml", "capteurs_actionnes: []", "capteurs_actionnes: [rien]")
    with pytest.raises(ErreurSimulation, match="« rien » n'est pas une entrée"):
        simuler(reglages)
    remplacer(reglages / "simulateur.yaml", "capteurs_actionnes: [rien]", "capteurs_actionnes: []")
    remplacer(reglages / "simulateur.yaml", "apres: exemple.aller_au_repos", "apres: exemple.voler")
    with pytest.raises(ErreurSimulation, match="étape « exemple.voler » inconnue"):
        simuler(reglages)


def test_reglages_du_simulateur_verifies(reglages):
    remplacer(reglages / "simulateur.yaml", "  exemple_x:", "  exemple_w:")
    remplacer(reglages / "simulateur.yaml", "depart: griffe_attente", "depart: ailleurs")
    message = erreur_de(reglages)
    assert "simulateur.yaml, axes → exemple_w : axe absent de machine.yaml" in message
    assert "simulateur.yaml, depart : position « ailleurs » absente de machine.yaml" in message


def test_taches_pour_le_solveur():
    liste = taches(simuler())
    assert [tache.nom for tache in liste] == [
        "exemple.aller_au_repos",
        "exemple.entrer_dans_la_zone_a",
        "exemple.revenir_au_repos",
    ]
    assert [tache.apres for tache in liste] == [
        None,
        "exemple.aller_au_repos",
        "exemple.entrer_dans_la_zone_a",
    ]
    assert [tache.demande_go for tache in liste] == [False, True, False]
    assert liste[1].zones == ("exemple_zone_a",)
    assert liste[0].duree_s == pytest.approx(ALLER_AU_REPOS)
    with pytest.raises(NotImplementedError, match="tâche 23"):
        ordonner(liste)


def test_heures_et_durees_lisibles():
    assert heure_lisible(62.54) == "01:02,5"
    assert heure_lisible(3723.5) == "1:02:03,5"
    assert duree_lisible(4.24) == "4,2 s"
    assert duree_lisible(59.96) == "1 min 00 s"
    assert duree_lisible(185) == "3 min 05 s"
    assert duree_lisible(3725) == "1 h 02 min"


def test_outil(tmp_path, capsys):
    chemin = tmp_path / "planning.json"
    assert main(["exemple", "--delai-go", "0", "--json", str(chemin)]) == 0
    sortie = capsys.readouterr().out
    assert "Temps total : 16,8 s" in sortie
    assert json.loads(chemin.read_text(encoding="utf-8"))["fini"] is True


def test_outil_cycle_bloque(reglages, capsys):
    remplacer(
        reglages / "machine.yaml", "exemple_deplacement_max: 30", "exemple_deplacement_max: 2"
    )
    assert main(["exemple", "--reglages", str(reglages)]) == 1
    assert "CYCLE ARRÊTÉ" in capsys.readouterr().out
