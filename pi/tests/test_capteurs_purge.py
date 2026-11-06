"""Capteurs de la purge (tâche 38 ter) : SPS30 (particules, SHDLC), SDP810 (pression, I2C), module
PWM → 0-10 V, avec les faux. Capteur muet ou en erreur : condition de purge jamais vraie."""

import math

import pytest

from vidange import trame_sps30 as shdlc
from vidange.entrees_sorties import CapteurParticules, charger_entrees_sorties
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel
from vidange.materiel.faux import FauxSps30
from vidange.materiel.ozone import CapteurMuet
from vidange.materiel.particules import LecteurSps30
from vidange.materiel.puces import crc_sht31
from vidange.nettoyage.capteurs import (
    CapteurDuMateriel,
    ConsigneDuMateriel,
    capteurs_du_materiel,
    verifier_avec_liste,
)
from vidange.reglages import ErreurReglages

from .test_nettoyage import NETTOYAGE, PURGE, Banc
from .test_reglages import remplacer

# ------------------------------------------------------------------ les trames SHDLC


def test_questions_connues_du_sps30():
    # « start measurement » (données 01 03) et « read measured values » de la fiche Sensirion.
    assert shdlc.construire_question(
        shdlc.COMMANDE_DEMARRER, shdlc.DONNEES_DEMARRER
    ) == bytes.fromhex("7E 00 00 02 01 03 F9 7E".replace(" ", ""))
    assert shdlc.construire_question(shdlc.COMMANDE_LIRE) == bytes.fromhex("7E000300FC7E")


def test_octets_echappes_dans_les_deux_sens():
    donnees = bytes([0x7E, 0x7D, 0x11, 0x13, 0x42])
    trame = shdlc.construire_reponse(0x03, donnees)
    # Ni 0x7E ni 0x11 ni 0x13 à l'intérieur de la trame, seulement aux deux bouts.
    assert trame[1:-1].count(0x7E) == 0
    assert b"\x7d\x5e\x7d\x5d\x7d\x31\x7d\x33" in trame
    assert shdlc.decoder_reponse(trame).donnees == donnees


def test_trame_fausse_coupee_ou_de_travers():
    bonne = shdlc.construire_reponse(0x03, shdlc.donnees_de_mesure((1.0,) * 10))
    assert shdlc.decoder_reponse(bonne).etat == 0
    abimee = bytearray(bonne)
    abimee[10] ^= 0x01
    for mauvaise in (bytes(abimee), bonne[:-3], bonne[1:], b"", b"\x7e\x7e"):
        with pytest.raises(shdlc.ErreurTrame):
            shdlc.decoder_reponse(mauvaise)
    with pytest.raises(shdlc.ErreurTrame):
        shdlc.valeurs_mesurees(b"\x00" * 39)


def test_decoupage_des_trames_et_reste():
    a = shdlc.construire_reponse(0x03)
    b = shdlc.construire_reponse(0x00)
    trames, reste = shdlc.decouper_trames(a + b + b"\x7e\x00\x03")
    assert trames == [a, b] and reste == b"\x7e\x00\x03"


def test_somme_de_controle_sdp810_valeur_connue():
    # Exemple de la fiche des capteurs Sensirion : CRC-8 (0x31, départ 0xFF) de BEEF = 92.
    assert crc_sht31(bytes([0xBE, 0xEF])) == 0x92


# --------------------------------------------------------- le lecteur SPS30 seul


class Horloge:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def reglage(**champs):
    base = {"grandeur": "pm2_5", "delai_muet_s": 5.0}
    return CapteurParticules(**{**base, **champs})


def lecteur_avec(**champs):
    r = reglage(**champs)
    faux = FauxSps30(r)
    horloge = Horloge()
    return LecteurSps30(faux.ouvrir, r, nom="sps_x", horloge=horloge), faux, horloge


def test_mesure_de_la_grandeur_choisie():
    for grandeur in ("pm1_0", "pm2_5", "pm4_0", "pm10"):
        lecteur, faux, _ = lecteur_avec(grandeur=grandeur)
        faux.valeur = 23.5
        assert lecteur.lire() == pytest.approx(23.5)  # pas la valeur d'un autre rang


def test_demarrage_une_seule_fois_et_deja_demarre_accepte():
    lecteur, faux, _ = lecteur_avec()
    faux.valeur = 10.0
    lecteur.lire()
    assert faux.demarre
    # Le Pi redémarre mais le capteur mesure encore : « commande pas permise » veut dire « ça va ».
    lecteur2 = LecteurSps30(faux.ouvrir, reglage(), nom="sps_x", horloge=Horloge())
    assert lecteur2.lire() == pytest.approx(10.0)


def test_trame_fausse_ignoree_et_comptee_ancienne_valeur_gardee():
    lecteur, faux, _ = lecteur_avec()
    faux.valeur = 15.0
    assert lecteur.lire() == pytest.approx(15.0)
    # Le capteur ne répond plus que par des trames abîmées : elles sont ignorées et comptées.
    faux.valeur = 99.0
    faux.abimer = True
    assert lecteur.lire() == pytest.approx(15.0)
    assert lecteur.trames_ignorees == 1
    faux.abimer = False
    faux.couper = True  # trame coupée : pas de fin, rien à lire
    assert lecteur.lire() == pytest.approx(15.0)
    faux.couper = False
    assert lecteur.lire() == pytest.approx(99.0)


def test_trames_fausses_sans_jamais_de_bonne_mesure_devient_muet():
    lecteur, faux, horloge = lecteur_avec(delai_muet_s=5)
    faux.abimer = True
    with pytest.raises(ErreurMateriel):
        lecteur.lire()
    horloge.t = 6
    with pytest.raises(CapteurMuet):
        lecteur.lire()


def test_mesure_qui_n_est_pas_un_nombre_refusee():
    for mauvais in (math.nan, math.inf, -3.0):
        lecteur, faux, _ = lecteur_avec()
        faux.valeur = mauvais
        with pytest.raises(ErreurMateriel):
            lecteur.lire()
        assert lecteur.trames_ignorees == 1


def test_capteur_muet_depuis_le_depart_puis_apres_le_delai():
    lecteur, faux, horloge = lecteur_avec(delai_muet_s=5)
    faux.muet = True
    with pytest.raises(ErreurMateriel, match="en attente de la première mesure"):
        lecteur.lire()
    horloge.t = 6
    with pytest.raises(CapteurMuet, match="aucune mesure valable depuis 5 s"):
        lecteur.lire()
    faux.muet = False  # il reparle
    assert lecteur.lire() == pytest.approx(0.0)


def test_capteur_qui_se_tait_garde_sa_valeur_puis_devient_muet():
    lecteur, faux, horloge = lecteur_avec(delai_muet_s=5)
    faux.valeur = 12.0
    lecteur.lire()
    faux.muet = True
    horloge.t = 4
    assert lecteur.lire() == pytest.approx(12.0)
    horloge.t = 6
    with pytest.raises(CapteurMuet):
        lecteur.lire()


def test_pas_de_mesure_nouvelle_puis_muet():
    lecteur, faux, horloge = lecteur_avec()
    faux.valeur = 12.0
    lecteur.lire()
    faux.sans_mesure_nouvelle = True
    horloge.t = 3
    assert lecteur.lire() == pytest.approx(12.0)
    horloge.t = 7
    with pytest.raises(CapteurMuet):
        lecteur.lire()


def test_echo_de_l_adaptateur_rs485_ignore():
    lecteur, faux, _ = lecteur_avec()
    faux.echo = True
    faux.valeur = 8.0
    assert lecteur.lire() == pytest.approx(8.0)
    assert lecteur.trames_ignorees == 0


def test_capteur_redemarre_s_il_ne_mesure_plus():
    lecteur, faux, _ = lecteur_avec()
    faux.valeur = 8.0
    lecteur.lire()
    faux.demarre = False  # le capteur a perdu le courant
    lecteur.lire()  # « commande pas permise » : le Pi le redémarre
    faux.valeur = 9.0
    assert lecteur.lire() == pytest.approx(9.0)
    assert faux.demarre


def test_erreur_du_capteur_leve_une_erreur():
    lecteur, faux, _ = lecteur_avec()
    faux.valeur = 8.0
    lecteur.lire()
    faux.etat_force = 0x03
    with pytest.raises(ErreurMateriel, match="pas le droit"):
        lecteur.lire()
    # Le bit 7 seul (avertissement) ne gêne pas la mesure.
    faux.etat_force = 0x80
    assert lecteur.lire() == pytest.approx(8.0)


def test_adaptateur_debranche_puis_rebranche():
    lecteur, faux, _ = lecteur_avec()
    faux.valeur = 8.0
    lecteur.lire()
    faux.cable_coupe = True
    with pytest.raises(ErreurMateriel, match="port série en panne"):
        lecteur.lire()
    faux.cable_coupe = False
    assert lecteur.lire() == pytest.approx(8.0)
    assert faux.ouvertures == 2


# ---------------------------------------------------- le Materiel sur le faux


@pytest.fixture
def faux_et_materiel(entrees_sorties):
    liste = charger_entrees_sorties(entrees_sorties)
    faux = FausseFabrique(liste)
    with Materiel(liste, faux) as materiel:
        yield faux, materiel


def test_deux_sps30_independants_usb_et_uart(faux_et_materiel):
    faux, materiel = faux_et_materiel
    faux.regler("particules_dedans", 40.0)
    faux.regler("particules_dehors", 12.0)
    assert materiel.lire_particules("particules_dedans") == pytest.approx(40.0)
    assert materiel.lire_particules("particules_dehors") == pytest.approx(12.0)
    assert materiel.mesurer("particules_dehors") == pytest.approx(12.0)
    assert materiel.unite("particules_dedans") == "µg/m³"
    assert materiel.branchements["particules_dedans"].ressource == ("serie", "rs485_sps30")
    assert materiel.branchements["particules_dehors"].ressource == ("uart", "/dev/ttyAMA3")


def test_un_sps30_muet_l_autre_lu(faux_et_materiel):
    faux, materiel = faux_et_materiel
    faux.regler("particules_dedans", 40.0)
    faux.regler("particules_dehors", 12.0)
    faux.debrancher("particules_dedans")
    with pytest.raises(ErreurMateriel, match="particules_dedans"):
        materiel.lire_particules("particules_dedans")
    assert materiel.lire_particules("particules_dehors") == pytest.approx(12.0)


def test_pression_et_sens_des_tuyaux(faux_et_materiel, entrees_sorties):
    faux, materiel = faux_et_materiel
    faux.regler("pression_enceinte", 9.5)
    assert materiel.lire_pression("pression_enceinte") == pytest.approx(9.5, abs=0.01)
    assert materiel.mesurer("pression_enceinte") == pytest.approx(9.5, abs=0.01)
    faux.regler("pression_enceinte", -3.0)
    assert materiel.lire_pression("pression_enceinte") == pytest.approx(-3.0, abs=0.01)
    assert materiel.unite("pression_enceinte") == "Pa"


def test_pression_tuyaux_inverses(entrees_sorties):
    remplacer(entrees_sorties, "inverser: false", "inverser: true")
    liste = charger_entrees_sorties(entrees_sorties)
    faux = FausseFabrique(liste)
    with Materiel(liste, faux) as materiel:
        faux.regler("pression_enceinte", 9.5)
        # La puce voit −9,5 Pa de son côté P, le Pi change le signe : +9,5 (enceinte plus haute).
        assert faux.capteur_pression("pression_enceinte").pascals == pytest.approx(-9.5)
        assert materiel.lire_pression("pression_enceinte") == pytest.approx(9.5, abs=0.01)


def test_pression_puce_debranchee_somme_fausse_et_reprise(faux_et_materiel):
    faux, materiel = faux_et_materiel
    faux.regler("pression_enceinte", 9.0)
    materiel.lire_pression("pression_enceinte")
    faux.debrancher("pression_enceinte")
    with pytest.raises(ErreurMateriel, match="pression_enceinte"):
        materiel.lire_pression("pression_enceinte")
    faux.debrancher("pression_enceinte", False)
    assert materiel.lire_pression("pression_enceinte") == pytest.approx(9.0, abs=0.01)
    faux.capteur_pression("pression_enceinte").abime = True
    with pytest.raises(ErreurMateriel, match="somme de contrôle"):
        materiel.lire_pression("pression_enceinte")
    faux.capteur_pression("pression_enceinte").abime = False
    faux.capteur_pression("pression_enceinte").sans_echelle = True
    with pytest.raises(ErreurMateriel, match="facteur d'échelle"):
        materiel.lire_pression("pression_enceinte")


def test_pression_la_puce_est_redemarree_apres_une_erreur(faux_et_materiel):
    faux, materiel = faux_et_materiel
    faux.regler("pression_enceinte", 5.0)
    materiel.lire_pression("pression_enceinte")
    puce = faux.capteur_pression("pression_enceinte")
    puce.demarre = False  # la puce a perdu le courant
    with pytest.raises(ErreurMateriel):
        materiel.lire_pression("pression_enceinte")
    assert materiel.lire_pression("pression_enceinte") == pytest.approx(5.0, abs=0.01)
    assert puce.demarre


def test_consigne_volts_en_rapport_cyclique(faux_et_materiel):
    faux, materiel = faux_et_materiel
    sortie = faux.consigne("consigne_ventilateur")
    assert sortie.volts() is None
    materiel.regler_consigne("consigne_ventilateur", 5.0)
    assert sortie.rapports == [0.5]
    assert sortie.volts() == pytest.approx(5.0)
    materiel.regler_consigne("consigne_ventilateur", 10.0)
    assert sortie.rapports[-1] == pytest.approx(1.0)


def test_consigne_hors_plage_refusee_et_panne(faux_et_materiel):
    faux, materiel = faux_et_materiel
    for volts in (-0.1, 10.5):
        with pytest.raises(ErreurMateriel, match="hors de 0 à 10 V"):
            materiel.regler_consigne("consigne_ventilateur", volts)
    assert faux.consigne("consigne_ventilateur").rapports == []
    faux.debrancher("consigne_ventilateur")
    with pytest.raises(ErreurMateriel, match="consigne_ventilateur"):
        materiel.regler_consigne("consigne_ventilateur", 5.0)


def test_consigne_remise_a_zero_a_la_fermeture(entrees_sorties):
    liste = charger_entrees_sorties(entrees_sorties)
    faux = FausseFabrique(liste)
    with Materiel(liste, faux) as materiel:
        materiel.regler_consigne("consigne_ventilateur", 7.0)
    assert faux.consigne("consigne_ventilateur").volts() == 0.0
    # Jamais réglée : rien n'est écrit à la fermeture.
    faux2 = FausseFabrique(liste)
    with Materiel(liste, faux2):
        pass
    assert faux2.consigne("consigne_ventilateur").rapports == []


def test_les_raccords_du_nettoyage(faux_et_materiel):
    faux, materiel = faux_et_materiel
    dedans, dehors, pression, consigne = capteurs_du_materiel(materiel)
    assert isinstance(dedans, CapteurDuMateriel) and dedans.nom == "particules_dedans"
    assert isinstance(consigne, ConsigneDuMateriel)
    faux.regler("particules_dehors", 11.0)
    assert dehors.lire() == pytest.approx(11.0)
    faux.regler("pression_enceinte", 8.0)
    assert pression.lire() == pytest.approx(8.0, abs=0.01)
    consigne.regler(5.0)
    assert faux.consigne("consigne_ventilateur").volts() == pytest.approx(5.0)


# --------------------------------------------- les réglages sont vérifiés au démarrage


def erreur_au_chargement(chemin):
    with pytest.raises(ErreurReglages) as erreur:
        charger_entrees_sorties(chemin)
    return str(erreur.value)


def test_sps30_sans_ses_reglages(entrees_sorties):
    remplacer(
        entrees_sorties,
        "    particules:\n      grandeur: pm2_5     # concentration en masse lue : pm1_0, pm2_5, "
        "pm4_0 ou pm10\n      delai_muet_s: 5     # sans mesure valable depuis ce délai : "
        "capteur « muet »\n",
        "",
    )
    assert "doit dire ses réglages" in erreur_au_chargement(entrees_sorties)


def test_vitesse_interdite_sur_l_adaptateur_usb(entrees_sorties):
    remplacer(
        entrees_sorties,
        "      delai_muet_s: 5     # sans mesure",
        "      vitesse_bauds: 9600\n      delai_muet_s: 5     # sans mesure",
    )
    assert "interdites ici" in erreur_au_chargement(entrees_sorties)


def test_vitesse_requise_sur_l_uart_du_pi(entrees_sorties):
    remplacer(entrees_sorties, "      vitesse_bauds: 115200   # UART du Pi seulement", "      # ")
    assert "sont requis" in erreur_au_chargement(entrees_sorties)


def test_grandeur_inconnue_du_sps30(entrees_sorties):
    remplacer(entrees_sorties, "grandeur: pm2_5     #", "grandeur: pm3_0     #")
    assert "grandeur" in erreur_au_chargement(entrees_sorties)


def test_broche_gpio8_prise_deux_fois(entrees_sorties):
    remplacer(entrees_sorties, "broche: [GPIO8, GPIO9]", "broche: [GPIO4, GPIO9]")
    assert "GPIO4" in erreur_au_chargement(entrees_sorties)


def test_adresse_i2c_en_double(entrees_sorties):
    remplacer(entrees_sorties, "adresse: 0x25", "adresse: 0x44")
    assert "adresse 0x44" in erreur_au_chargement(entrees_sorties)


def test_bloc_pwm_sur_un_signal_qui_n_est_pas_pwm(entrees_sorties):
    remplacer(
        entrees_sorties,
        "    unite: Pa\n    pression:",
        "    unite: Pa\n    pwm: {fichier: /sys/class/pwm/pwmchip0, canal: 3, periode_us: 1000, "
        "pleine_echelle_v: 10}\n    pression:",
    )
    assert "« pwm » ne sert qu'aux signaux de type pwm" in erreur_au_chargement(entrees_sorties)


def test_ventilateur_plus_fort_que_le_module(entrees_sorties):
    liste = charger_entrees_sorties(entrees_sorties)
    assert verifier_avec_liste(NETTOYAGE, liste) == []
    remplacer(entrees_sorties, "pleine_echelle_v: 10 ", "pleine_echelle_v: 8 ")
    erreurs = verifier_avec_liste(NETTOYAGE, charger_entrees_sorties(entrees_sorties))
    assert len(erreurs) == 1 and "plein_v" in erreurs[0] and "8 V" in erreurs[0]


# ------------------------------------------ la purge avec les vrais capteurs (faux dessous)


@pytest.fixture
def banc(tmp_path):
    b = Banc(tmp_path)
    dedans, dehors, pression, consigne = capteurs_du_materiel(b.materiel)
    b.n.particules_dedans, b.n.particules_dehors = dedans, dehors
    b.n.capteur_pression, b.n.consigne = pression, consigne
    # Les lecteurs vivent à l'heure du banc, pas à l'heure du Pi.
    for lecteur in b.materiel._particules.values():
        lecteur._horloge = b.horloge
        lecteur._depuis = b.horloge.t
    yield b
    b.registre.fermer()


def bon_air(banc):
    banc.faux.regler("particules_dedans", 12.0)
    banc.faux.regler("particules_dehors", 12.0)
    banc.faux.regler("pression_enceinte", PURGE.pression_fin + 2)


def test_purge_finie_avec_les_vrais_capteurs(banc):
    bon_air(banc)
    banc.store(True)
    banc.avancer(PURGE.duree_min_s + PURGE.stabilite_particules_s + 5)
    assert not banc.n.purge_en_cours
    assert banc.faux.consigne("consigne_ventilateur").volts() == pytest.approx(
        NETTOYAGE.ventilateur.normal_v
    )


@pytest.mark.parametrize("muet", ["particules_dedans", "particules_dehors", "pression_enceinte"])
def test_capteur_muet_la_purge_n_est_jamais_finie(banc, muet):
    bon_air(banc)
    banc.faux.debrancher(muet)
    banc.store(True)
    banc.avancer(PURGE.alerte_s + 5)
    assert banc.n.purge_en_cours and banc.n.etat().purge_alerte


def test_capteur_qui_se_tait_en_cours_de_purge(banc):
    bon_air(banc)
    banc.store(True)
    banc.avancer(30)
    banc.faux.debrancher("particules_dehors")  # plus rien, la purge ne peut pas finir
    banc.faux.debrancher("pression_enceinte")
    banc.avancer(PURGE.alerte_s)
    assert banc.n.purge_en_cours and banc.n.etat().purge_alerte
    assert not banc.n.etat().purge_particules_ok and not banc.n.etat().purge_pression_ok


def test_trames_fausses_la_purge_n_est_jamais_finie(banc):
    bon_air(banc)
    # Le SPS30 du dedans n'envoie que des trames abîmées.
    banc.faux.capteur_particules("particules_dedans").abimer = True
    banc.store(True)
    banc.avancer(PURGE.alerte_s + 5)
    assert banc.n.purge_en_cours and banc.n.etat().purge_alerte
    assert not banc.n.etat().purge_particules_ok
    assert banc.materiel._particules["particules_dedans"].trames_ignorees > 0


def test_pression_trop_basse_la_purge_continue(banc):
    bon_air(banc)
    banc.faux.regler("pression_enceinte", PURGE.pression_fin - 3)
    banc.store(True)
    banc.avancer(PURGE.duree_min_s + PURGE.stabilite_particules_s + 5)
    assert banc.n.purge_en_cours
    banc.faux.regler("pression_enceinte", PURGE.pression_fin + 1)
    banc.avancer(5)
    assert not banc.n.purge_en_cours
