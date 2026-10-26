"""Tests de la liaison avec une carte FluidNC, branchée sur le faux FluidNC (en temps réel)."""

import pytest

from vidange.fluidnc import liaison as module_liaison
from vidange.fluidnc.faux import FauxFluidnc
from vidange.fluidnc.liaison import ErreurCommande, ErreurFluidnc, Liaison
from vidange.reglages import Fluidnc

DELAI = 3  # attente maximale dans les tests, en s (bien plus que nécessaire)


def reglages_essai(**liaison) -> Fluidnc:
    valeurs = {
        "vitesse_bauds": 115200,
        "taille_tampon": 128,
        "periode_etat_s": 0.02,
        "delai_silence_s": 0.3,
        "delai_reconnexion_s": 0.05,
        **liaison,
    }
    return Fluidnc.model_validate(
        {"liaison": valeurs, "cartes": {"portique": {"numero_serie_usb": "A1"}}}
    )


@pytest.fixture
def faux() -> FauxFluidnc:
    return FauxFluidnc()


@pytest.fixture
def liaison(faux):
    with Liaison("portique", reglages_essai(), ouvrir=faux.ouvrir) as liaison:
        liaison.attendre_connexion(DELAI)
        yield liaison


def test_connexion_et_etat(liaison):
    etat = liaison.etat
    assert etat.connectee
    assert etat.etat == "Idle"
    assert etat.positions == {"X": 0, "Y": 0, "Z": 0}
    assert etat.au_repos
    assert not etat.en_alarme


def test_mouvement_jusqu_au_bout(liaison):
    liaison.envoyer_et_attendre("G1 X10 Y-5 F6000", DELAI)
    etat = liaison.attendre_fin_mouvements(DELAI)
    assert etat.positions == {"X": 10, "Y": -5, "Z": 0}
    assert etat.au_repos


def test_controle_de_flux_sans_debordement(faux, liaison):
    faux.taille_file = 4  # les lignes s'entassent dans le tampon de la carte
    lignes = [f"G1 X{i} F30000" for i in range(60)]
    commandes = [liaison.envoyer(ligne) for ligne in lignes]
    for commande in commandes:
        commande.attendre(DELAI)
    assert faux.lignes_recues == lignes
    assert not faux.debordement
    # Le tampon de la carte a vraiment été rempli, sans jamais dépasser.
    assert 100 < faux.plus_grand_tampon <= 128


def test_le_faux_voit_un_tampon_trop_grand():
    """Le contrôle de flux réglé plus grand que le tampon de la carte : le faux le voit."""
    faux = FauxFluidnc(taille_tampon=64, taille_file=1)
    with Liaison("portique", reglages_essai(), ouvrir=faux.ouvrir) as liaison:
        liaison.attendre_connexion(DELAI)
        for i in range(20):
            liaison.envoyer(f"G1 X{i} F600")
        liaison.attendre(lambda etat: faux.debordement, DELAI)


def test_erreur_de_la_carte(liaison):
    with pytest.raises(ErreurCommande, match="erreur 22"):
        liaison.envoyer_et_attendre("G1 X1", DELAI)  # pas de vitesse F


@pytest.mark.parametrize(
    ("ligne", "raison"),
    [
        ("G1 X1 F100 ?", "commandes à part"),
        ("G1 X1 (déplacement)", "caractère interdit"),
        ("G1 X1\nG1 X2", "caractère interdit"),
        ("G1 " + "X1 " * 50, "plus longue que le tampon"),
    ],
)
def test_lignes_refusees_avant_envoi(faux, liaison, ligne, raison):
    commande = liaison.envoyer(ligne)
    assert commande.finie and not commande.reussie
    assert raison in commande.erreur
    assert faux.lignes_recues == []


def test_alarme_annule_les_lignes_en_attente(faux):
    # File de la carte d'un seul mouvement et petit tampon : une ligne attend sur la carte,
    # la suivante attend dans la liaison.
    faux.taille_file = 1
    with Liaison("portique", reglages_essai(taille_tampon=16), ouvrir=faux.ouvrir) as liaison:
        liaison.attendre_connexion(DELAI)
        lent = liaison.envoyer("G1 X100 F600")
        sur_la_carte = liaison.envoyer("G1 X1 F600")
        en_attente = liaison.envoyer("G1 X2 F600")
        lent.attendre(DELAI)
        assert not sur_la_carte.finie and not en_attente.finie

        faux.declencher_alarme(1)
        etat = liaison.attendre(lambda etat: etat.alarme == 1, DELAI)
        assert etat.en_alarme
        with pytest.raises(ErreurCommande, match="interrompue : alarme 1"):
            sur_la_carte.attendre(DELAI)
        with pytest.raises(ErreurCommande, match="annulée : alarme 1"):
            en_attente.attendre(DELAI)

        liaison.debloquer().attendre(DELAI)
        etat = liaison.attendre(lambda etat: etat.etat == "Idle", DELAI)
        assert etat.alarme is None
        # Le vieux mouvement n'est jamais parti, même après le déblocage.
        assert "G1 X2 F600" not in faux.lignes_recues
        liaison.envoyer_et_attendre("G1 X0 F60000", DELAI)


def test_pause_et_reprise(faux, liaison):
    liaison.envoyer("G1 X100 F6000")  # 100 mm/s : 1 s
    liaison.attendre(lambda etat: etat.positions["X"] > 5, DELAI)
    liaison.pause()
    etat = liaison.attendre(lambda etat: (etat.etat or "").startswith("Hold"), DELAI)
    arretee, debut = etat.positions["X"], etat.date_rapport
    etat = liaison.attendre(lambda etat: etat.date_rapport > debut + 0.1, DELAI)
    assert etat.positions["X"] == arretee < 100
    liaison.reprendre()
    liaison.attendre_fin_mouvements(DELAI)
    assert faux.positions["X"] == 100


def test_cable_coupe_puis_reconnexion(faux, liaison):
    liaison.envoyer("G1 X20 F6000")  # 0,2 s
    attente = liaison.envoyer("G4 P0")
    faux.couper_cable()
    with pytest.raises(ErreurCommande, match="perdue : liaison coupée"):
        attente.attendre(DELAI)
    etat = liaison.attendre(lambda etat: not etat.connectee, DELAI)
    assert etat.coupures == 1
    commande = liaison.envoyer("G1 X0 F600")
    assert commande.erreur == "carte non connectée"
    with pytest.raises(ErreurFluidnc, match="non connectée"):
        liaison.pause()

    faux.rebrancher()
    etat = liaison.attendre_connexion(DELAI)
    # La carte a fini son mouvement pendant la coupure ; la liaison le voit.
    etat = liaison.attendre(lambda etat: etat.positions["X"] == 20, DELAI)
    assert etat.etat == "Idle"
    liaison.envoyer_et_attendre("G1 X0 F60000", DELAI)


def test_carte_muette_liaison_reprise(faux, liaison):
    faux.muet = True
    liaison.attendre(lambda etat: etat.coupures == 1, DELAI)
    faux.muet = False
    liaison.attendre_connexion(DELAI)
    liaison.envoyer_et_attendre("G0 X1", DELAI)


def test_redemarrage_de_la_carte(faux, liaison):
    liaison.envoyer("G1 X100 F600")
    attente = liaison.envoyer("G4 P0")
    liaison.attendre(lambda etat: etat.positions["X"] > 0, DELAI)
    faux.redemarrer()
    with pytest.raises(ErreurCommande, match="la carte a redémarré"):
        attente.attendre(DELAI)
    etat = liaison.attendre(lambda etat: etat.en_alarme, DELAI)
    assert etat.positions["X"] == 0


def test_reinitialisation(faux, liaison):
    liaison.envoyer("G1 X100 F600")
    attente = liaison.envoyer("G4 P0")
    liaison.reinitialiser()
    with pytest.raises(ErreurCommande, match="réinitialisation"):
        attente.attendre(0)
    etat = liaison.attendre(lambda etat: etat.alarme == 3, DELAI)
    assert etat.lignes_en_cours == 0
    liaison.debloquer().attendre(DELAI)


def test_carte_absente_au_depart_puis_branchee(faux):
    faux.couper_cable()
    with Liaison("portique", reglages_essai(), ouvrir=faux.ouvrir) as liaison:
        with pytest.raises(ErreurFluidnc, match="attente trop longue"):
            liaison.attendre_connexion(0.2)
        faux.rebrancher()
        liaison.attendre_connexion(DELAI)


def test_prise_origine(faux, liaison):
    liaison.envoyer("G0 X50")
    liaison.attendre_fin_mouvements(DELAI)
    liaison.prise_origine().attendre(DELAI)
    assert faux.positions == {"X": 0, "Y": 0, "Z": 0}


def test_arret_puis_envoi(faux):
    liaison = Liaison("portique", reglages_essai(), ouvrir=faux.ouvrir)
    liaison.demarrer()
    liaison.attendre_connexion(DELAI)
    liaison.arreter()
    assert not liaison.etat.connectee
    assert liaison.envoyer("G0 X1").erreur == "carte non connectée"


def test_carte_inconnue():
    with pytest.raises(ErreurFluidnc, match="absente de fluidnc.yaml"):
        Liaison("inconnue", reglages_essai())


def test_carte_trouvee_par_son_numero_de_serie(monkeypatch):
    appels = []

    def ouvrir_port_usb(*arguments):
        appels.append(arguments)
        raise OSError("pas de carte")

    monkeypatch.setattr(module_liaison, "ouvrir_port_usb", ouvrir_port_usb)
    with Liaison("portique", reglages_essai()) as liaison:
        with pytest.raises(ErreurFluidnc):
            liaison.attendre_connexion(0.1)
    assert appels[0] == ("A1", 115200, 0.02)


def test_redemarrage_tout_seul_compte(faux, liaison):
    """Une carte qui redémarre seule est comptée ; une réinitialisation demandée ne l'est pas."""
    liaison.reinitialiser()
    liaison.attendre(lambda etat: etat.rapports_recus > 2, DELAI)
    assert liaison.etat.redemarrages == 0
    faux.redemarrer()
    # Position perdue : la carte se remet en alarme (le faux comme le vrai FluidNC).
    liaison.attendre(lambda etat: etat.redemarrages == 1 and etat.en_alarme, DELAI)
