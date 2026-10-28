"""Tests du registre : base SQLite, montées de version, copie de secours quotidienne."""

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from vidange.registre import (
    ErreurRegistre,
    Registre,
    SauvegardeQuotidienne,
    montees,
    ouvrir_registre,
)
from vidange.registre.outil import main as outil
from vidange.reglages import ReglagesRegistre

GUADELOUPE = timezone(timedelta(hours=-4))


class Horloge:
    """Fausse horloge qu'on avance à la main."""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


@pytest.fixture
def horloge() -> Horloge:
    return Horloge(datetime(2026, 10, 26, 14, 0, tzinfo=GUADELOUPE))


@pytest.fixture
def registre(tmp_path: Path, horloge: Horloge):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos", horloge=horloge)
    yield registre
    registre.fermer()


REGLAGES = ReglagesRegistre(heure_sauvegarde=3, copies_gardees=3, periode_verification_min=10)


# ------------------------------------------------------------ création et montées


def test_base_neuve_a_la_derniere_version(registre: Registre):
    assert registre.version == montees.VERSION
    assert all(nombre == 0 for nombre in registre.compter().values())


def test_rouvrir_garde_les_donnees(tmp_path: Path, registre: Registre):
    registre.objet("seau", "S1293")
    registre.fermer()
    autre = ouvrir_registre(tmp_path)
    assert autre.trouver("seau", "S1293") is not None
    autre.fermer()


def test_montee_de_version_avec_copie_avant(tmp_path: Path, registre: Registre, monkeypatch):
    registre.objet("fut", "F3")
    registre.fermer()
    nouvelle = ("ALTER TABLE futs ADD COLUMN volume_l REAL",)
    monkeypatch.setattr("vidange.registre.base.MONTEES", (*montees.MONTEES, nouvelle))
    monkeypatch.setattr("vidange.registre.base.VERSION", montees.VERSION + 1)
    monte = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    assert monte.version == montees.VERSION + 1
    monte.objet("fut", "F3", volume_l=220)
    assert monte.trouver("fut", "F3")["volume_l"] == 220
    monte.fermer()
    copie = tmp_path / f"registre-avant-version-{montees.VERSION + 1}.sqlite"
    with sqlite3.connect(copie) as ancienne:
        assert ancienne.execute("PRAGMA user_version").fetchone()[0] == montees.VERSION
        assert ancienne.execute("SELECT code FROM futs").fetchall() == [("F3",)]
    ancienne.close()


def test_montee_ratee_laisse_la_base_intacte(tmp_path: Path, registre: Registre, monkeypatch):
    registre.objet("fut", "F3")
    registre.fermer()
    fausse = ("ALTER TABLE futs ADD COLUMN volume_l REAL", "CECI N'EST PAS DU SQL")
    monkeypatch.setattr("vidange.registre.base.MONTEES", (*montees.MONTEES, fausse))
    monkeypatch.setattr("vidange.registre.base.VERSION", montees.VERSION + 1)
    with pytest.raises(ErreurRegistre, match="ratée.*restée en version"):
        Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    monkeypatch.undo()
    intacte = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    assert intacte.version == montees.VERSION
    assert "volume_l" not in intacte.trouver("fut", "F3")
    intacte.fermer()


def test_base_plus_recente_que_le_programme(tmp_path: Path, registre: Registre):
    registre.fermer()
    with sqlite3.connect(tmp_path / "registre.sqlite") as cnx:
        cnx.execute(f"PRAGMA user_version = {montees.VERSION + 1}")
    cnx.close()
    with pytest.raises(ErreurRegistre, match="plus récente que ce programme"):
        ouvrir_registre(tmp_path)


def test_base_abimee(tmp_path: Path):
    (tmp_path / "registre.sqlite").write_bytes(b"pas une base SQLite" * 100)
    with pytest.raises(ErreurRegistre, match="abîmée.*copie de secours"):
        ouvrir_registre(tmp_path)


# ------------------------------------------------------------ objets


def test_objet_trouve_ou_ajoute(registre: Registre):
    premier = registre.objet("seau", " S1293 ")
    assert registre.objet("seau", "S1293") == premier
    registre.objet("seau", "S1293", type_seau="opaque_10l")
    fiche = registre.trouver("seau", "S1293")
    assert fiche["type_seau"] == "opaque_10l"
    assert fiche["cree_le"] == "2026-10-26T14:00:00-04:00"
    assert registre.trouver("seau", "S9999") is None


def test_objet_champ_inconnu_ou_code_vide(registre: Registre):
    with pytest.raises(ErreurRegistre, match="champ inconnu pour un fut : couleur"):
        registre.objet("fut", "F1", couleur="bleu")
    with pytest.raises(ErreurRegistre, match="code de seau vide"):
        registre.objet("seau", "  ")
    with pytest.raises(ErreurRegistre, match="sorte d'objet inconnue"):
        registre.objet("tonneau", "T1")  # type: ignore[arg-type]
    # Rien n'a été écrit à moitié.
    assert registre.trouver("fut", "F1") is None


# ------------------------------------------------------------ un cycle complet


def test_cycle_complet(registre: Registre, horloge: Horloge):
    cycle = registre.commencer_cycle("vidange", fut="F3")
    seau_du_cycle = registre.ajouter_seau(cycle, "S1293", bocal="B327")
    registre.ajouter_dose(seau_du_cycle, "B328", quantite_g=120.0)
    debut = horloge()
    horloge.moment += timedelta(seconds=40)
    registre.noter_etape(cycle, "verser", debut, duree_s=32.5)
    registre.noter_mesure("poids_seau", 6.2, "kg", capteur="balance", cycle=cycle, seau="S1293")
    assert [c["id"] for c in registre.cycles_en_cours()] == [cycle]
    registre.finir_cycle(cycle)
    assert registre.cycles_en_cours() == []

    ligne = registre.lire("SELECT * FROM cycles WHERE id = ?", (cycle,))[0]
    assert ligne["issue"] == "termine"
    assert ligne["fut_id"] == registre.trouver("fut", "F3")["id"]
    etape = registre.lire("SELECT * FROM etapes_faites")[0]
    assert (etape["debut"], etape["fin"], etape["duree_s"], etape["issue"]) == (
        "2026-10-26T14:00:00-04:00",
        "2026-10-26T14:00:40-04:00",
        32.5,
        "faite",
    )
    seaux = registre.lire(
        "SELECT seaux.code AS seau, bocaux.code AS bocal, quantite_g FROM doses_mycelium "
        "JOIN seaux_du_cycle ON seaux_du_cycle.id = seau_du_cycle_id "
        "JOIN seaux ON seaux.id = seau_id JOIN bocaux ON bocaux.id = bocal_id "
        "ORDER BY doses_mycelium.id"
    )
    assert seaux == [
        {"seau": "S1293", "bocal": "B327", "quantite_g": None},
        {"seau": "S1293", "bocal": "B328", "quantite_g": 120.0},
    ]
    mesure = registre.lire("SELECT * FROM mesures")[0]
    assert (mesure["valeur"], mesure["unite"], mesure["cycle_id"]) == (6.2, "kg", cycle)


def test_cycle_deja_fini_ou_inconnu(registre: Registre):
    cycle = registre.commencer_cycle("lavage")
    registre.finir_cycle(cycle, "abandonne")
    with pytest.raises(ErreurRegistre, match="inconnu ou déjà fini"):
        registre.finir_cycle(cycle)
    with pytest.raises(ErreurRegistre, match="inconnu ou déjà fini"):
        registre.finir_cycle(999)


def test_reference_inconnue_refusee(registre: Registre):
    with pytest.raises(ErreurRegistre, match="écriture refusée"):
        registre.noter_etape(999, "verser", datetime.now(GUADELOUPE), duree_s=1)
    with pytest.raises(ErreurRegistre, match="écriture refusée"):
        registre.noter_etape(registre.commencer_cycle("x"), "verser", datetime.now(), duree_s=-1)
    # Un seau cité dans une écriture refusée n'est pas resté dans la base.
    with pytest.raises(ErreurRegistre):
        registre.ajouter_seau(999, "S1")
    assert registre.trouver("seau", "S1") is None


# ------------------------------------------------------------ photos


def test_photo_garde_seulement_le_chemin(registre: Registre):
    fichier = registre.dossier_photos / "2026-10-26" / "dose.jpg"
    fichier.parent.mkdir()
    fichier.write_bytes(b"\xff\xd8 faux jpeg")
    photo = registre.noter_photo(fichier, camera="dosage", seau="S1293")
    ligne = registre.lire("SELECT * FROM photos")[0]
    assert ligne["chemin"] == "2026-10-26/dose.jpg"
    assert registre.chemin_photo(photo).read_bytes() == b"\xff\xd8 faux jpeg"
    assert ligne["seau_id"] == registre.trouver("seau", "S1293")["id"]


def test_photo_absente_ou_hors_du_dossier(registre: Registre, tmp_path: Path):
    with pytest.raises(ErreurRegistre, match="photo introuvable"):
        registre.noter_photo(registre.dossier_photos / "absente.jpg")
    ailleurs = tmp_path / "ailleurs.jpg"
    ailleurs.write_bytes(b"x")
    with pytest.raises(ErreurRegistre, match="hors du dossier des photos"):
        registre.noter_photo(ailleurs)
    with pytest.raises(ErreurRegistre, match="photo n° 5 inconnue"):
        registre.chemin_photo(5)


# ------------------------------------------------------------ alarmes et réglages


def test_alarme_et_acquittement(registre: Registre, horloge: Horloge):
    alarme = registre.noter_alarme(
        "griffe", "Délai dépassé", quoi_faire="Regarder la griffe", etape="descendre"
    )
    horloge.moment += timedelta(minutes=5)
    registre.acquitter_alarme(alarme, "karulium")
    ligne = registre.lire("SELECT * FROM alarmes")[0]
    assert ligne["acquittee_le"] == "2026-10-26T14:05:00-04:00"
    assert ligne["acquittee_par"] == "karulium"
    with pytest.raises(ErreurRegistre, match="déjà acquittée"):
        registre.acquitter_alarme(alarme, "karulium")


def test_reglage_applique_ancien_et_nouveau(registre: Registre):
    registre.noter_reglage(
        "karulium", "machine.yaml", "durees.vidange_max", 30, 35.5, raison="fût plus lourd"
    )
    registre.noter_reglage("pi", "machine.yaml", "positions.repos", None, {"x": 0.8})
    lignes = registre.lire("SELECT * FROM reglages_appliques ORDER BY id")
    premier = lignes[0]
    assert (premier["ancien"], premier["nouveau"], premier["qui"]) == ("30", "35.5", "karulium")
    assert (lignes[1]["ancien"], lignes[1]["nouveau"]) == (None, '{"x": 0.8}')


def test_ecritures_depuis_plusieurs_fils(registre: Registre):
    def ecrire(numero: int) -> None:
        for i in range(20):
            registre.noter_mesure("vide", i, "kPa", seau=f"S{numero}")

    fils = [threading.Thread(target=ecrire, args=(n,)) for n in range(5)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join()
    assert registre.compter()["mesures"] == 100
    assert registre.compter()["seaux"] == 5


# ------------------------------------------------------------ copie de secours


def test_copie_complete_et_lisible(registre: Registre, tmp_path: Path):
    registre.objet("bocal", "B327")
    cible = tmp_path / "copies" / "copie.sqlite"
    registre.copier_vers(cible)
    assert not cible.with_name("copie.sqlite.nouveau").exists()
    copie = Registre(cible, tmp_path / "photos")
    assert copie.trouver("bocal", "B327") is not None
    copie.fermer()


def test_sauvegarde_une_fois_par_jour_apres_l_heure(
    registre: Registre, horloge: Horloge, tmp_path: Path
):
    sauvegarde = SauvegardeQuotidienne(registre, tmp_path / "sauvegardes", REGLAGES, horloge)
    horloge.moment = datetime(2026, 10, 26, 2, 59, tzinfo=GUADELOUPE)
    assert sauvegarde.faire_si_besoin() is None
    horloge.moment = datetime(2026, 10, 26, 3, 0, tzinfo=GUADELOUPE)
    faite = sauvegarde.faire_si_besoin()
    assert faite == tmp_path / "sauvegardes" / "registre-2026-10-26.sqlite"
    assert faite.exists()
    horloge.moment += timedelta(hours=10)
    assert sauvegarde.faire_si_besoin() is None
    # Pi éteint à 3 h le lendemain : la copie se fait dès qu'il tourne.
    horloge.moment = datetime(2026, 10, 27, 17, 0, tzinfo=GUADELOUPE)
    assert sauvegarde.faire_si_besoin().name == "registre-2026-10-27.sqlite"


def test_sauvegarde_garde_les_dernieres_copies(
    registre: Registre, horloge: Horloge, tmp_path: Path
):
    dossier = tmp_path / "sauvegardes"
    dossier.mkdir()
    autre = dossier / "a-garder.txt"
    autre.write_text("pas une copie")
    sauvegarde = SauvegardeQuotidienne(registre, dossier, REGLAGES, horloge)
    for jour in range(20, 26):
        horloge.moment = datetime(2026, 10, jour, 4, 0, tzinfo=GUADELOUPE)
        sauvegarde.faire_si_besoin()
    assert [c.name for c in sauvegarde.copies()] == [
        "registre-2026-10-23.sqlite",
        "registre-2026-10-24.sqlite",
        "registre-2026-10-25.sqlite",
    ]
    assert autre.exists()


def test_sauvegarde_ratee_ne_plante_pas_le_fil(registre: Registre, tmp_path: Path, monkeypatch):
    sauvegarde = SauvegardeQuotidienne(
        registre, tmp_path / "sauvegardes", REGLAGES, lambda: datetime(2026, 10, 26, 5, 0)
    )

    def ratee(_cible: Path) -> None:
        raise OSError("disque plein")

    monkeypatch.setattr(registre, "copier_vers", ratee)
    arret = threading.Event()
    arret.set()
    fil = sauvegarde.demarrer(arret)
    fil.join(timeout=5)
    assert not fil.is_alive()
    assert sauvegarde.copies() == []


# ------------------------------------------------------------ outil


def test_outil_etat_et_sauvegarder(reglages: Path, tmp_path: Path, capsys):
    donnees = tmp_path / "donnees"
    arguments = ["--reglages", str(reglages), "--donnees", str(donnees)]
    assert outil(["sauvegarder", *arguments]) == 0
    assert outil(["etat", *arguments]) == 0
    sortie = capsys.readouterr().out
    assert f"version {montees.VERSION}" in sortie
    assert "Copies de secours : 1" in sortie


# ------------------------------------------------------------ tâche 7 : bilans d'alarme


def test_alarme_avec_son_bilan_et_alarmes_ouvertes(registre: Registre):
    premiere = registre.noter_alarme("exemple", "trop long", "Regarder.", bilan="bilans/a.json")
    seconde = registre.noter_alarme("alimentation", "coupure")
    registre.acquitter_alarme(seconde, "karulium")
    ouvertes = registre.alarmes_ouvertes()
    assert [ligne["id"] for ligne in ouvertes] == [premiere]
    assert ouvertes[0]["bilan"] == "bilans/a.json"


def test_montee_de_la_version_1_a_la_derniere(tmp_path: Path):
    """Une base de la tâche 6 (version 1) reçoit la colonne « bilan » (version 2) et la file
    d'envoi (version 3) sans rien perdre."""
    chemin = tmp_path / "registre.sqlite"
    with sqlite3.connect(chemin) as cnx:
        for requete in montees.MONTEES[0]:
            cnx.execute(requete)
        cnx.execute(
            "INSERT INTO alarmes (quand, module, message) VALUES ('2026-10-01', 'vieux', 'avant')"
        )
        cnx.execute("PRAGMA user_version = 1")
    cnx.close()
    registre = Registre(chemin, tmp_path / "photos")
    try:
        assert registre.version == montees.VERSION == 5
        assert registre.alarmes_ouvertes()[0]["message"] == "avant"
        assert registre.alarmes_ouvertes()[0]["bilan"] is None
        assert registre.compter()["envois"] == registre.compter()["prises_griffe"] == 0
    finally:
        registre.fermer()
