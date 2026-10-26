"""Tests de la reconnaissance de la fin précédente : premier, propre, plantage, coupure."""

from vidange.fiabilite import Marche
from vidange.fiabilite.marche import NOM_FICHIER


def test_premier_puis_propre(tmp_path):
    marche = Marche(tmp_path, demarrage_pi=lambda: 0, horloge=lambda: 1000)
    assert marche.demarrer().sorte == "premier"
    marche.noter_arret("onduleur")
    fin = Marche(tmp_path, demarrage_pi=lambda: 0, horloge=lambda: 2000).demarrer()
    assert (fin.sorte, fin.raison, fin.brutale) == ("propre", "onduleur", False)


def test_plantage_ou_coupure(tmp_path):
    Marche(tmp_path, demarrage_pi=lambda: 0, horloge=lambda: 1000).demarrer()
    # Le Pi tourne depuis avant le programme : le programme a planté.
    fin = Marche(tmp_path, demarrage_pi=lambda: 500, horloge=lambda: 2000).demarrer()
    assert fin.sorte == "plantage" and fin.brutale
    # Le Pi a redémarré après le démarrage du programme : coupure de courant.
    fin = Marche(tmp_path, demarrage_pi=lambda: 2500, horloge=lambda: 3000).demarrer()
    assert fin.sorte == "coupure"
    assert "coupure de courant" in fin.decrire()


def test_fichier_abime_compte_comme_une_coupure(tmp_path):
    (tmp_path / NOM_FICHIER).write_text("{abîmé", encoding="utf-8")
    assert Marche(tmp_path).demarrer().sorte == "coupure"
