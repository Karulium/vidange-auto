"""Tests : carte trouvée par le numéro de série de son USB, et outil vidange-fluidnc."""

import io
import sys
from types import SimpleNamespace

import pytest

from vidange.fluidnc import outil, ports
from vidange.fluidnc.ports import CarteIntrouvable, ouvrir_port_usb, trouver_port


def port_usb(device: str, numero: str | None) -> SimpleNamespace:
    return SimpleNamespace(device=device, serial_number=numero, description="USB Serial")


PORTS = [
    port_usb("/dev/ttyACM0", "B2"),
    port_usb("/dev/ttyACM1", "A1"),
    port_usb("/dev/ttyS0", None),
]


def test_trouve_par_le_numero_pas_par_l_ordre():
    assert trouver_port("A1", lambda: PORTS) == "/dev/ttyACM1"
    # Les ports ont changé de nom (rebranchement) : la carte est quand même retrouvée.
    echanges = [port_usb("/dev/ttyACM0", "A1"), port_usb("/dev/ttyACM1", "B2")]
    assert trouver_port("A1", lambda: echanges) == "/dev/ttyACM0"


def test_carte_absente():
    with pytest.raises(CarteIntrouvable) as erreur:
        trouver_port("C3", lambda: PORTS)
    message = str(erreur.value)
    assert "« C3 »" in message
    assert "/dev/ttyACM0 (n° de série : B2" in message
    assert "/dev/ttyS0 (n° de série : aucun" in message


def test_numero_en_double():
    doubles = [port_usb("/dev/ttyACM0", "A1"), port_usb("/dev/ttyACM1", "A1")]
    with pytest.raises(CarteIntrouvable, match="plusieurs ports"):
        trouver_port("A1", lambda: doubles)


def test_ouverture_sans_redemarrer_la_carte(monkeypatch):
    ouverts = []

    class FauxSerial:
        def open(self):
            ouverts.append(self)

    monkeypatch.setattr(ports.serial, "Serial", FauxSerial)
    port = ouvrir_port_usb("A1", 115200, 0.2, lister=lambda: PORTS)
    assert ouverts == [port]
    assert port.port == "/dev/ttyACM1"
    assert port.baudrate == 115200
    assert port.timeout == 0.2
    assert port.dtr is False and port.rts is False
    assert port.exclusive is True


def test_outil_lister(monkeypatch, capsys, reglages):
    vus = [port_usb("/dev/ttyACM3", "EXEMPLE-CHARIOT"), port_usb("/dev/ttyUSB0", None)]
    monkeypatch.setattr(outil, "lister_ports_usb", lambda: vus)
    assert outil.main(["--reglages", str(reglages), "lister"]) == 0
    sortie = capsys.readouterr().out
    assert "/dev/ttyACM3 : n° de série « EXEMPLE-CHARIOT », USB Serial → chariot" in sortie
    assert "/dev/ttyUSB0 : n° de série « AUCUN », USB Serial → aucune carte" in sortie


def test_outil_lister_rien(monkeypatch, capsys, reglages):
    monkeypatch.setattr(outil, "lister_ports_usb", lambda: [])
    assert outil.main(["--reglages", str(reglages), "lister"]) == 0
    assert "Aucun port série" in capsys.readouterr().out


def test_outil_console_avec_le_faux(monkeypatch, capsys, reglages):
    lignes = "G1 X2 F6000\nfin\netat\nG1 X1\npause\nreprise\ndebloquer\nquitter\nG0 X9\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(lignes))
    code = outil.main(
        ["--reglages", str(reglages), "console", "portique", "--faux", "--delai", "5"]
    )
    assert code == 0
    sortie = capsys.readouterr().out
    assert "mouvements finis : au repos  X=2.000  Y=0.000  Z=0.000 mm" in sortie
    assert "ÉCHEC" not in sortie


def test_outil_console_fichier(monkeypatch, capsys, reglages, tmp_path):
    programme = tmp_path / "essai.gcode"
    programme.write_text("G91\n" + "G1 X1 F60000\n" * 30 + "\nG1 X1\n", encoding="utf-8")
    entree = f"fichier {programme}\nfichier {tmp_path / 'absent.gcode'}\nfin\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(entree))
    outil.main(["--reglages", str(reglages), "console", "portique", "--faux", "--delai", "5"])
    sortie = capsys.readouterr().out
    assert "32 lignes envoyées en" in sortie
    assert ", 0 échec(s)" in sortie
    assert "ÉCHEC : fichier introuvable" in sortie
    assert "X=31.000" in sortie


def test_outil_carte_inconnue(capsys, reglages):
    assert outil.main(["--reglages", str(reglages), "console", "machin", "--faux"]) == 2
    assert "absente de fluidnc.yaml" in capsys.readouterr().out


def test_outil_reglages_faux(capsys, reglages):
    (reglages / "fluidnc.yaml").unlink()
    assert outil.main(["--reglages", str(reglages), "lister"]) == 2
    assert "fluidnc.yaml : fichier manquant" in capsys.readouterr().out
