"""Tests de l'outil « vidange-es » avec le faux matériel."""

from vidange.materiel import outil


def test_lister(entrees_sorties, capsys):
    assert outil.main(["--entrees-sorties", str(entrees_sorties), "--faux", "lister"]) == 0
    sortie = capsys.readouterr().out
    assert "reed_panneau_poste_fut (entree) : repos" in sortie
    assert "voyant_buzzer (sortie) : repos" in sortie
    assert "sht31_armoire (ambiance) : 25.0 °C, 50 %" in sortie
    assert "vide_venturi (mesure) : 12.49 kPa" in sortie  # 0 V sur la voie → 12,49 kPa (la droite)
    assert "ozone_1 (modbus) : 0 ppm" in sortie
    assert (
        "Pas lus par le Pi lui-même : servo_camera_dosage, ads1115_bus, ecran_nextion, "
        "accelerometre_fil, relais_1_bus" in sortie
    )


def test_commander(entrees_sorties, capsys):
    arguments = ["--entrees-sorties", str(entrees_sorties), "--faux", "commander"]
    assert outil.main([*arguments, "voyant_buzzer", "oui"]) == 0
    assert "voyant_buzzer : COMMANDÉE" in capsys.readouterr().out
    assert outil.main([*arguments, "porte_spray", "oui"]) == 1
    assert "ÉCHEC : signal « porte_spray » : c'est un signal de sorte « entree »" in (
        capsys.readouterr().out
    )


def test_lister_seulement_quelques_signaux(entrees_sorties, capsys):
    arguments = ["--entrees-sorties", str(entrees_sorties), "--faux", "lister"]
    assert outil.main([*arguments, "sht31_armoire", "ozone_2"]) == 0
    sortie = capsys.readouterr().out
    assert "sht31_armoire (ambiance)" in sortie and "ozone_2 (modbus)" in sortie
    assert "porte_spray" not in sortie
    assert outil.main([*arguments, "ecran_nextion"]) == 2
    assert "pas lus par le Pi lui-même : ecran_nextion" in capsys.readouterr().out


def test_surveiller(entrees_sorties, capsys):
    from vidange.entrees_sorties import charger_entrees_sorties
    from vidange.materiel import FausseFabrique, Materiel

    liste = charger_entrees_sorties(entrees_sorties)
    faux = FausseFabrique(liste)
    with Materiel(liste, faux) as materiel:
        faux.actionner("porte_spray")
        outil.surveiller(materiel, periode_s=0, tours=1)
    sortie = capsys.readouterr().out
    assert "porte_spray : ACTIONNÉ" in sortie
    assert "reed_panneau_poste_fut : repos" in sortie


def test_liste_fausse(entrees_sorties, capsys):
    entrees_sorties.write_text("modules: [armoire]\n", encoding="utf-8")
    assert outil.main(["--entrees-sorties", str(entrees_sorties), "--faux", "lister"]) == 2
    assert "le programme ne démarre pas" in capsys.readouterr().out
