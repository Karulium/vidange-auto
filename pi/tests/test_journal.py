"""Tests du journal commun."""

from vidange.journal import NOM_FICHIER, configurer_journal, donner_journal


def test_le_journal_ecrit_a_l_ecran_et_dans_le_fichier(tmp_path, capsys):
    configurer_journal("info", tmp_path / "journal", taille_fichier_mo=1, nombre_fichiers=2)
    donner_journal("essai").info("bonjour")
    donner_journal("essai").debug("trop de détail")
    assert "INFO     vidange.essai : bonjour" in capsys.readouterr().err
    contenu = (tmp_path / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    assert "vidange.essai : bonjour" in contenu
    assert "trop de détail" not in contenu


def test_le_fichier_tourne_et_garde_le_nombre_voulu(tmp_path):
    dossier = tmp_path / "journal"
    configurer_journal("info", dossier, taille_fichier_mo=0.001, nombre_fichiers=2)
    for numero in range(200):
        donner_journal("essai").info("ligne %d", numero)
    assert sorted(f.name for f in dossier.iterdir()) == [
        NOM_FICHIER,
        f"{NOM_FICHIER}.1",
        f"{NOM_FICHIER}.2",
    ]


def test_reconfigurer_n_ecrit_pas_deux_fois(capsys):
    configurer_journal()
    configurer_journal()
    donner_journal("essai").warning("une fois")
    assert capsys.readouterr().err.count("une fois") == 1
