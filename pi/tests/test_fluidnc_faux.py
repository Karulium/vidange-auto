"""Tests du faux FluidNC, avec une horloge qu'on avance à la main."""

import pytest

from vidange.fluidnc.faux import BIENVENUE, FauxFluidnc, FauxPort
from vidange.fluidnc.protocole import lire_rapport_etat


class Horloge:
    def __init__(self) -> None:
        self.temps = 0.0

    def __call__(self) -> float:
        return self.temps

    def avancer(self, secondes: float) -> None:
        self.temps += secondes


@pytest.fixture
def horloge() -> Horloge:
    return Horloge()


def nouvelle_carte(horloge: Horloge, **reglages) -> tuple[FauxFluidnc, FauxPort]:
    carte = FauxFluidnc(horloge=horloge, delai_lecture_s=0, **reglages)
    return carte, carte.ouvrir()


def lire(port: FauxPort) -> list[str]:
    lignes = []
    while ligne := port.readline():
        lignes.append(ligne.decode().strip())
    return lignes


def envoyer(port: FauxPort, *lignes: str) -> list[str]:
    for ligne in lignes:
        port.write(ligne.encode() + b"\n")
    return lire(port)


def etat(port: FauxPort):
    port.write(b"?")
    rapports = [lire_rapport_etat(ligne) for ligne in lire(port) if ligne.startswith("<")]
    assert len(rapports) == 1
    return rapports[0]


def test_les_positions_avancent_a_la_vitesse_demandee(horloge):
    carte, port = nouvelle_carte(horloge)
    assert envoyer(port, "G1 X10 F600") == ["ok"]  # 600 mm/min = 10 mm/s
    horloge.avancer(0.5)
    rapport = etat(port)
    assert rapport.etat == "Run"
    assert rapport.positions["X"] == pytest.approx(5)
    assert rapport.vitesse == 600
    horloge.avancer(1)
    rapport = etat(port)
    assert rapport.etat == "Idle"
    assert rapport.positions == {"X": 10, "Y": 0, "Z": 0}


def test_g0_va_a_la_vitesse_rapide_en_diagonale(horloge):
    carte, port = nouvelle_carte(horloge, vitesse_rapide_mm_min=6000)  # 100 mm/s
    envoyer(port, "G0 X30 Y40")  # 50 mm de long
    horloge.avancer(0.25)
    assert etat(port).positions == pytest.approx({"X": 15, "Y": 20, "Z": 0})


def test_relatif_et_mouvements_enchaines(horloge):
    carte, port = nouvelle_carte(horloge)
    assert envoyer(port, "G91", "G1 X5 F600", "X5", "Z-2 (commentaire)") == ["ok"] * 4
    horloge.avancer(10)
    assert etat(port).positions == {"X": 10, "Y": 0, "Z": -2}


def test_file_pleine_le_ok_attend(horloge):
    carte, port = nouvelle_carte(horloge, taille_file=2)
    assert envoyer(port, "G1 X10 F600", "G1 X20", "G1 X30") == ["ok", "ok"]
    horloge.avancer(1.01)  # le premier mouvement est fini : de la place
    assert lire(port) == ["ok"]


def test_debordement_du_tampon_note(horloge):
    carte, port = nouvelle_carte(horloge, taille_file=1, taille_tampon=32)
    envoyer(port, "G1 X10 F600", "G1 X20 F600", "G1 X30 F600")
    assert not carte.debordement
    envoyer(port, "G1 X40 F600")
    assert carte.debordement


def test_g4_repond_a_la_fin_des_mouvements(horloge):
    carte, port = nouvelle_carte(horloge)
    assert envoyer(port, "G1 X10 F600", "G4 P0", "G1 X0") == ["ok"]
    horloge.avancer(0.9)
    assert lire(port) == []
    horloge.avancer(0.2)
    assert lire(port) == ["ok", "ok"]  # G4 fini, puis G1 X0 pris
    horloge.avancer(0.5)
    # Le retour est parti à la fin du G4 (t = 1 s) : 0,6 s à 10 mm/s.
    assert etat(port).positions["X"] == pytest.approx(4)


def test_g4_avec_une_duree(horloge):
    carte, port = nouvelle_carte(horloge)
    assert envoyer(port, "G4 P2") == []
    horloge.avancer(1.9)
    assert lire(port) == []
    horloge.avancer(0.2)
    assert lire(port) == ["ok"]


def test_pause_et_reprise(horloge):
    carte, port = nouvelle_carte(horloge)
    envoyer(port, "G1 X10 F600")
    horloge.avancer(0.5)
    port.write(b"!")
    horloge.avancer(3)
    rapport = etat(port)
    assert rapport.etat == "Hold:0"
    assert rapport.positions["X"] == pytest.approx(5)
    port.write(b"~")
    horloge.avancer(0.5)
    rapport = etat(port)
    assert rapport.positions["X"] == pytest.approx(10)
    assert rapport.etat == "Idle"


def test_alarme_puis_deblocage(horloge):
    carte, port = nouvelle_carte(horloge)
    envoyer(port, "G1 X10 F600")
    horloge.avancer(0.2)
    carte.declencher_alarme(1)
    assert lire(port) == ["ALARM:1"]
    horloge.avancer(1)
    rapport = etat(port)
    assert rapport.etat == "Alarm"
    assert rapport.positions["X"] == pytest.approx(2)  # arrêtée net
    assert envoyer(port, "G1 X0") == ["error:9"]
    assert envoyer(port, "$X") == ["[MSG:Caution: Unlocked]", "ok"]
    assert etat(port).etat == "Idle"


def test_alarme_pendant_une_attente(horloge):
    carte, port = nouvelle_carte(horloge)
    envoyer(port, "G1 X10 F600", "G4 P0")
    carte.declencher_alarme(2)
    assert lire(port) == ["ALARM:2", "ok"]  # comme Grbl : l'alarme d'abord


def test_carte_en_alarme_au_depart(horloge):
    carte, port = nouvelle_carte(horloge, en_alarme_au_depart=True)
    assert etat(port).etat == "Alarm"
    assert envoyer(port, "G0 X1") == ["error:9"]


def test_reinitialisation_pendant_un_mouvement(horloge):
    carte, port = nouvelle_carte(horloge)
    envoyer(port, "G1 X10 F600", "G4 P0")
    horloge.avancer(0.2)
    port.write(b"\x18")
    assert lire(port) == ["ALARM:3", BIENVENUE]
    assert etat(port).etat == "Alarm"


def test_reinitialisation_au_repos(horloge):
    carte, port = nouvelle_carte(horloge)
    port.write(b"\x18")
    assert lire(port) == [BIENVENUE]
    assert etat(port).etat == "Idle"


def test_lignes_refusees(horloge):
    carte, port = nouvelle_carte(horloge)
    assert envoyer(port, "G1 X1") == ["error:22"]  # vitesse jamais donnée
    assert envoyer(port, "G1 A1 F100") == ["error:20"]  # pas d'axe A sur cette carte
    assert envoyer(port, "M3 Q2") == ["error:20"]
    assert envoyer(port, "bonjour") == ["error:2"]
    assert envoyer(port, "G1 X1 F0") == ["error:23"]
    assert envoyer(port, "", "G21 G90 G94", "$$") == ["ok", "ok", "ok"]
    assert carte.lignes_recues[-1] == "$$"


def test_prise_origine(horloge):
    carte, port = nouvelle_carte(horloge, vitesse_rapide_mm_min=6000)
    envoyer(port, "G0 X50 Z50")
    assert envoyer(port, "$H") == ["error:8"]  # pas pendant un mouvement
    horloge.avancer(1)
    assert envoyer(port, "$H") == []
    horloge.avancer(0.3)
    assert etat(port).etat == "Home"
    horloge.avancer(1)
    assert lire(port) == ["ok"]
    assert etat(port).positions == {"X": 0, "Y": 0, "Z": 0}


def test_cable_coupe_puis_rebranche(horloge):
    carte, port = nouvelle_carte(horloge)
    envoyer(port, "G1 X10 F600")
    carte.couper_cable()
    with pytest.raises(OSError):
        port.readline()
    with pytest.raises(OSError):
        port.write(b"?")
    with pytest.raises(OSError):
        carte.ouvrir()
    horloge.avancer(2)
    carte.rebrancher()
    nouveau = carte.ouvrir()
    # La carte a fini son mouvement pendant la coupure.
    assert etat(nouveau).positions["X"] == 10
    # L'ancien port, lui, reste mort.
    with pytest.raises(OSError):
        port.write(b"?")
    nouveau.close()
    with pytest.raises(OSError):
        nouveau.readline()


def test_carte_muette(horloge):
    carte, port = nouvelle_carte(horloge)
    carte.muet = True
    port.write(b"?")
    assert lire(port) == []
    carte.muet = False
    assert len(lire(port)) == 1


def test_redemarrage_de_la_carte(horloge):
    carte, port = nouvelle_carte(horloge)
    envoyer(port, "G1 X10 F600")
    horloge.avancer(0.5)
    carte.redemarrer()
    assert lire(port) == [BIENVENUE]
    rapport = etat(port)
    assert rapport.etat == "Alarm"
    assert rapport.positions["X"] == 0


def test_six_axes(horloge):
    carte, port = nouvelle_carte(horloge, axes="XYZABC")
    envoyer(port, "G0 A10 C-5")
    horloge.avancer(10)
    assert etat(port).positions == {"X": 0, "Y": 0, "Z": 0, "A": 10, "B": 0, "C": -5}


def test_axes_mal_donnes():
    with pytest.raises(ValueError):
        FauxFluidnc(axes="XYQ")
