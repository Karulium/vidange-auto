"""Poste du fût (tâches 17 et 17 bis) : pesée sans fil du plateau (boîte du poste sur le bus des
pesées), états du poste, bouton « Prêt », pesée absente, accu du plateau, mode, verrous."""

import logging

import pytest

from vidange.api import Services
from vidange.ecran import Ecran, FauxNextion, LiaisonEcran
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fiabilite import Bilans
from vidange.fiabilite.checklist import constats_registre
from vidange.fiabilite.constats import pire
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel, PeseeMuette
from vidange.materiel.carte_pesee import (
    SIGNATURE,
    MesureCarte,
    Plateau,
    decoder_boite,
    encoder,
)
from vidange.materiel.faux import FausseBoitePosteFut
from vidange.mode import ModeMachine
from vidange.pesees.tour import TourPesees
from vidange.pesees.verification import cartes_de_pesee, verifier_avec_liste
from vidange.poste_fut import ABSENT, EN_PLACE, PRET, ErreurPoste, PosteFut
from vidange.poste_fut.outil import main as outil_pesee
from vidange.poste_fut.pesee import pente
from vidange.registre import Registre
from vidange.reglages import AccuPlateauFut, PeseeLente, ReglagesBilan, charger_reglages
from vidange.reglages import PosteFut as ReglagesPosteFut
from vidange.simulateur import ErreurSimulation, Simulateur
from vidange.simulateur.outil import main as simulateur

from .conftest import DOSSIER_PI
from .test_api import LOCAL, client_connecte, creer_app_de_test
from .test_chef import Horloge, nouveau_chef
from .test_ecran import REGLAGES as REGLAGES_ECRAN
from .test_reglages import erreur_de, remplacer

LISTE = DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
POSTE = REGLAGES.machine.poste_fut
assert POSTE is not None
ACCU = REGLAGES.pesees.accu_plateau_fut
assert ACCU is not None
# Réglages du dépôt (EXEMPLES) : tare 33,4 kg, poids plausible de 25 à 150 kg, absente 5 s après
# l'arrivée du plateau, mesure refusée au-delà de 2 s, une question par seconde.
TARE = POSTE.pesee.tare_kg
SIGNAL = "pesee_fut"


class BancPoste:
    """Le vrai poste du fût sur le faux matériel, avec le vrai tour des pesées, un vrai registre
    et une fausse horloge. `avancer` fait aussi tourner le tour (son fil, sur la machine)."""

    def __init__(self, dossier, griffe_hors_fut=lambda: True) -> None:
        self.horloge = Horloge()
        liste = charger_entrees_sorties(LISTE)
        self.faux = FausseFabrique(liste)
        self.materiel = Materiel(liste, self.faux)
        self.registre = Registre(dossier / "registre.sqlite", dossier / "photos")
        self.tour = TourPesees(REGLAGES.pesees, self.materiel, self.horloge)
        self.poste = PosteFut(
            POSTE,
            self.materiel,
            self.registre,
            horloge=self.horloge,
            griffe_hors_fut=griffe_hors_fut,
            pesees=self.tour,
        )
        self.boite = self.faux.carte_pesee(SIGNAL)
        assert isinstance(self.boite, FausseBoitePosteFut)

    def peser(self, kg: float) -> None:
        """Le plateau pèse ce poids (lu) ; la boîte est interrogée et le poste relu."""
        assert self.poste.pesee is not None
        self.boite.brut = self.poste.pesee.brut(kg)
        self.tour.interroger(SIGNAL)
        self.poste.observer()

    def plateau(self, au_fond: bool = True) -> None:
        self.faux.actionner("plateau_fut_en_place", au_fond)
        self.poste.observer()

    def avancer(self, secondes: float, pas: float = 0.5) -> None:
        fin = self.horloge.t + secondes
        while self.horloge.t < fin - 1e-9:
            self.horloge.t = min(self.horloge.t + pas, fin)
            self.tour.faire_un_tour()
            self.poste.observer()

    def jusqu_au_pret(self, kg: float = 129) -> None:
        self.plateau()
        self.peser(kg)
        self.avancer(2)
        self.poste.appuyer_pret("essai")

    def mesures(self) -> dict[str, float]:
        return {m["nom"]: m["valeur"] for m in self.registre.lire("SELECT * FROM mesures")}

    def alarmes(self) -> list[str]:
        return [a["message"] for a in self.registre.alarmes_ouvertes()]


@pytest.fixture
def b(tmp_path):
    banc = BancPoste(tmp_path)
    banc.poste.observer()
    yield banc
    banc.registre.fermer()


@pytest.fixture
def caplog(caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("vidange"), "propagate", True)
    return caplog


# ------------------------------------------------------- la boîte du poste du fût


def _mesure_boite(**autres) -> MesureCarte:
    valeurs = dict(
        brut=-123456,
        numero=7,
        age_ms=250,
        hx711_muet=False,
        exemple=True,
        par_seconde=2,
        trames_abimees=1,
        radio_muette=False,
        plateau=Plateau(True, True, False, 3912, 81, -63, 4),
    )
    valeurs.update(autres)
    return MesureCarte(**valeurs)


def test_registres_de_la_boite_aller_et_retour():
    mesure = _mesure_boite()
    registres = encoder(mesure, signature=0x5046)
    assert len(registres) == 13 and registres[7] == 0x5046
    # Registre 8 : reed fermé + recharge ; 11 : dBm + 200.
    assert registres[8:13] == [3, 3912, 81, 137, 4]
    assert decoder_boite(registres) == mesure
    muette = encoder(_mesure_boite(radio_muette=True), signature=0x5046)
    assert muette[4] & 4 and decoder_boite(muette).radio_muette


def test_signature_d_une_carte_rp2040_refusee_pour_pesee_fut(b):
    with pytest.raises(ErreurMateriel, match="pas la boîte du poste du fût.*0x5053"):
        decoder_boite(encoder(_mesure_boite(), signature=SIGNATURE))
    # Une carte RP2040 à l'adresse de la boîte : refusée, et le poste dit « pesée absente ».
    b.boite.signature = SIGNATURE
    with pytest.raises(ErreurMateriel, match="signature 0x5053, 0x5046 attendue"):
        b.materiel.lire_carte_pesee(SIGNAL)
    b.plateau()
    b.avancer(5)
    etat = b.poste.etat()
    assert etat.pesee == "pesée absente : la boîte du poste ne répond pas" and etat.pesee_absente


def test_lecture_de_la_boite_par_le_materiel(b):
    b.boite.brut = 1234
    mesure = b.materiel.lire_carte_pesee(SIGNAL)
    assert mesure.brut == 1234 and mesure.plateau is not None
    assert mesure.plateau.accu_mv == 3900 and mesure.plateau.signal_dbm == -60
    assert b.materiel.peser(SIGNAL) == 1234
    b.boite.radio_muette = True
    assert b.materiel.lire_carte_pesee(SIGNAL).age_ms == 0xFFFF
    with pytest.raises(PeseeMuette, match="radio du plateau muette"):
        b.materiel.peser(SIGNAL)


def test_la_boite_est_un_appareil_du_bus_pas_une_carte_rp2040():
    liste = charger_entrees_sorties(LISTE)
    signal = liste.signaux[SIGNAL]
    assert signal.carte == "rs485_pesee" and signal.appareil == "boite_poste_fut"
    assert signal.adresse == 4 and signal.exemple
    # La fabrication du programme des cartes RP2040 ne la prend pas.
    assert SIGNAL not in cartes_de_pesee(liste)
    assert verifier_avec_liste(REGLAGES.pesees, liste) == []
    # Plus de signal « chariot » ni de broche du Pi pour la pesée.
    assert "plateau_fut_en_place" in liste.signaux
    assert "chariot_fut_en_place" not in liste.signaux


def test_la_boite_doit_etre_lente_et_l_accu_regle(reglages, entrees_sorties):
    liste = charger_entrees_sorties(entrees_sorties)
    pesees = REGLAGES.pesees.model_copy(update={"lentes": {}, "accu_plateau_fut": None})
    erreurs = "\n".join(verifier_avec_liste(pesees, liste))
    assert "« pesee_fut » doit être dans « lentes »" in erreurs
    assert "il manque « accu_plateau_fut »" in erreurs
    remplacer(reglages / "pesees.yaml", "    age_max_ms: 2000", "    age_max_ms: 900")
    assert "age_max_ms (900) doit dépasser espacement_s (1 s)" in erreur_de(reglages)


def test_seuils_de_l_accu_dans_le_bon_ordre(reglages):
    with pytest.raises(ValueError, match="seuils de l'accu dans le désordre"):
        AccuPlateauFut(bon_v=3.6, recharger_v=3.3, bientot_absente_v=3.5, sans_recharge_max_s=600)
    with pytest.raises(ValueError, match="dans le désordre"):
        AccuPlateauFut(bon_v=3.4, recharger_v=3.5, bientot_absente_v=3.3, sans_recharge_max_s=600)
    remplacer(reglages / "pesees.yaml", "  recharger_v: 3.5", "  recharger_v: 3.2")
    assert "seuils de l'accu dans le désordre" in erreur_de(reglages)
    assert PeseeLente(espacement_s=1, age_max_ms=2000).age_max_ms == 2000


# --------------------------------------------------------------- le tour des pesées


def test_la_griffe_garde_ses_80_mesures_par_seconde_avec_pesee_fut(tmp_path):
    """Chaque question dure le temps de ses octets sur le bus (115 200 bauds) et l'attente de
    la carte : sur une seconde, la griffe est lue au moins 80 fois, la boîte au plus 2 fois."""
    liste = charger_entrees_sorties(LISTE)
    faux = FausseFabrique(liste)
    horloge = Horloge()
    bauds = liste.cartes["rs485_pesee"].liaison.vitesse_bauds
    attente_s = REGLAGES.pesees.programme.delai_avant_reponse_us / 1e6
    with Materiel(liste, faux) as materiel:
        vraie = materiel.lire_carte_pesee

        def chronometree(nom):
            boite = liste.signaux[nom].appareil == "boite_poste_fut"
            octets = 8 + 5 + 2 * (13 if boite else 8)
            horloge.t += octets * 10 / bauds + attente_s
            return vraie(nom)

        materiel.lire_carte_pesee = chronometree
        tour = TourPesees(REGLAGES.pesees, materiel, horloge)
        assert SIGNAL in REGLAGES.pesees.tour
        while horloge.t < 1.0:
            tour.faire_un_tour()
            horloge.t += REGLAGES.pesees.pause_entre_tours_ms / 1000
    assert faux.carte_pesee("pesee_griffe").questions >= 80
    assert 1 <= faux.carte_pesee(SIGNAL).questions <= 2


def test_mesure_de_2_5_s_absente(b):
    b.plateau()
    b.peser(129)
    assert b.poste.etat().poids_lu_kg == pytest.approx(129)
    b.boite.age_ms = 2500
    b.avancer(1)
    etat = b.poste.etat()
    assert etat.poids_lu_kg is None
    assert etat.pesee == "pesée absente : mesure trop vieille"
    with pytest.raises(ErreurMateriel, match="vieille de 2.50 s"):
        b.tour.capteur(SIGNAL).lire_kg()


def test_boite_qui_ne_repond_plus_absente_apres_2_s(b):
    b.plateau()
    b.peser(129)
    b.faux.debrancher(SIGNAL)
    b.avancer(1.5)
    assert b.poste.etat().poids_lu_kg == pytest.approx(129)
    b.avancer(1)
    assert b.poste.etat().pesee == "pesée absente : la boîte du poste ne répond plus"


# ---------------------------------------------------------------- pesée


def test_pente_de_l_etalonnage():
    assert pente(1000, 201_000, 20) == 10_000
    with pytest.raises(ValueError, match="n'a pas bougé"):
        pente(1000, 1000, 20)
    with pytest.raises(ValueError, match="plus grand que 0"):
        pente(1000, 2000, 0)


def test_valeur_hors_bornes_rejetee(b):
    b.plateau()
    b.peser(20)
    etat = b.poste.etat()
    assert etat.poids_lu_kg is None
    assert etat.pesee == "poids rejeté : 20,0 kg lus, attendu entre 25 et 150 kg"
    b.peser(129)
    etat = b.poste.etat()
    assert etat.pesee == "" and etat.poids_net_kg == pytest.approx(129 - TARE)


def test_outil_d_etalonnage_avec_le_faux_materiel(capsys):
    assert outil_pesee(["--faux", "lire", "--tours", "1"]) == 0
    sortie = capsys.readouterr().out
    # Le faux plateau pèse 0 : hors des bornes plausibles ; l'accu et la radio sont lus.
    assert "ÉCHEC : poids rejeté : 0,0 kg lus" in sortie
    assert "accu 3.90 V  80 % recharge 5 V" in sortie and "radio -60 dBm" in sortie
    assert outil_pesee(["--faux", "zero"]) == 0
    assert "    zero_brut: 0" in capsys.readouterr().out
    assert outil_pesee(["--faux", "etalonner", "20"]) == 1
    assert "n'a pas bougé" in capsys.readouterr().err
    assert outil_pesee(["--faux", "tare"]) == 0
    assert "    tare_kg: 0.00" in capsys.readouterr().out


# ---------------------------------------------------------------- états du poste


def test_du_plateau_absent_au_pret(b):
    etat = b.poste.etat()
    assert etat.etat == ABSENT and etat.libelle == "Plateau du fût absent"
    assert "plateau du fût contre les 2 butées du fond" in etat.manque
    with pytest.raises(ErreurPoste, match="« Prêt » refusé, il manque : plateau du fût"):
        b.poste.appuyer_pret("essai")

    b.plateau()
    b.peser(129)
    etat = b.poste.etat()
    assert etat.etat == EN_PLACE and not etat.plateau_stable
    assert etat.manque == ("plateau immobile depuis 2 s",)
    b.avancer(2)
    etat = b.poste.etat()
    assert etat.etat == EN_PLACE and etat.manque == ()
    assert etat.poids_net_kg == pytest.approx(129 - TARE)
    assert etat.accu_pct == 80 and etat.signal_dbm == -60 and etat.recharge_presente
    assert etat.accu == ""
    b.poste.appuyer_pret("essai", fut="F3")
    etat = b.poste.etat()
    assert etat.etat == PRET and etat.cycle == 1 and etat.poids_plein_kg == pytest.approx(95.6)
    assert not etat.sans_pesee
    assert etat.messages[-1] == "Prêt : fût de 95,6 kg (substrat)."
    cycle = b.registre.lire("SELECT * FROM cycles")[0]
    assert cycle["module"] == "vidange" and cycle["fin"] is None
    mesure = b.registre.lire("SELECT * FROM mesures")[0]
    assert mesure["nom"] == "poids_fut_plein" and mesure["valeur"] == pytest.approx(95.6)
    assert mesure["capteur"] == "pesee_fut" and mesure["fut_id"] is not None
    # Un deuxième appui ne fait rien.
    b.poste.appuyer_pret("essai")
    assert len(b.registre.lire("SELECT * FROM cycles")) == 1


def test_pret_accepte_sans_pesee(b):
    b.boite.radio_muette = True
    b.plateau()
    b.avancer(2)
    etat = b.poste.etat()
    # Avant 5 s : pas encore « absente » (le plateau se réveille), pas d'alerte.
    assert etat.manque == () and not etat.pesee_absente and b.alarmes() == []
    assert etat.pesee == "pesée absente : radio du plateau muette"
    b.poste.appuyer_pret("essai", fut="F4")
    etat = b.poste.etat()
    assert etat.etat == PRET and etat.poids_plein_kg is None and etat.sans_pesee
    assert etat.messages[-1] == (
        "Prêt, sans pesée du fût : la vidange commence sans le poids du fût."
    )
    assert b.mesures() == {"sans_pesee_fut": 1}
    mesure = b.registre.lire("SELECT * FROM mesures")[0]
    assert mesure["fut_id"] is not None and mesure["seau_id"] is None
    # Les doses prises sans pesée : le seau est noté « sans pesée du fût », une fois.
    b.poste.noter_dose(8, seau="S1")
    b.poste.noter_dose(7, seau="S1")
    b.poste.noter_dose(9, seau="S2")
    seaux = b.registre.lire(
        "SELECT s.code FROM mesures m JOIN seaux s ON s.id = m.seau_id "
        "WHERE m.nom = 'sans_pesee_fut'"
    )
    assert [ligne["code"] for ligne in seaux] == ["S1", "S2"]
    # Rien ne s'est arrêté.
    assert b.poste.etat().etat == PRET


def test_pesee_absente_5_s_apres_le_plateau_une_seule_alerte(b, caplog):
    b.faux.debrancher(SIGNAL)
    b.plateau()
    b.avancer(4.5)
    assert b.alarmes() == []
    b.avancer(1)
    etat = b.poste.etat()
    assert etat.pesee_absente
    assert etat.pesee == "pesée absente : la boîte du poste ne répond pas"
    assert b.alarmes() == [
        "Pesée du fût absente (la boîte du poste ne répond pas) : la vidange continue sans les "
        "kilos restants."
    ]
    # Une longue absence : une seule alerte, pas une par seconde.
    b.avancer(120, pas=1)
    assert len(b.alarmes()) == 1
    assert caplog.text.count("Pesée du fût absente") == 1
    alarme = b.registre.alarmes_ouvertes()[0]
    assert alarme["module"] == "poste_fut" and "Rien ne s'arrête" in alarme["quoi_faire"]


def test_retour_de_la_pesee_sans_redemarrer(b):
    b.jusqu_au_pret()
    b.boite.radio_muette = True
    b.avancer(3)
    assert b.poste.etat().pesee == "pesée absente : radio du plateau muette"
    assert len(b.alarmes()) == 1
    assert b.poste.poids_restant_kg() is None
    assert b.poste.etat().etat == PRET
    # La radio revient : le poids revient seul, et le dit.
    b.boite.radio_muette = False
    b.avancer(1)
    etat = b.poste.etat()
    assert etat.pesee == "" and etat.poids_lu_kg == pytest.approx(129)
    assert etat.messages[-1] == "La pesée du fût répond de nouveau."
    # Une nouvelle absence plus tard : une nouvelle alerte.
    b.boite.radio_muette = True
    b.avancer(3)
    assert len(b.alarmes()) == 2


def test_seuils_de_l_accu(b):
    b.plateau()
    b.peser(129)
    b.boite.accu_mv, b.boite.accu_pct = 3550, 30
    b.avancer(1)
    assert b.alarmes() == [] and b.poste.etat().accu == ""
    b.boite.accu_mv, b.boite.accu_pct = 3450, 18
    b.avancer(1)
    assert b.alarmes() == ["Accu du plateau faible (3,45 V, 18 %) : recharger le plateau."]
    assert b.poste.etat().accu == "recharger le plateau"
    b.avancer(5)
    assert len(b.alarmes()) == 1
    b.boite.accu_mv, b.boite.accu_pct = 3250, 4
    b.avancer(1)
    assert b.alarmes()[-1] == "Accu du plateau presque vide (3,25 V, 4 %) : pesée bientôt absente."
    assert b.poste.etat().accu == "pesée bientôt absente : recharger le plateau"
    # Rechargé (au moins 3,6 V), puis de nouveau faible : une nouvelle alerte.
    b.boite.accu_mv = 3700
    b.avancer(1)
    assert b.poste.etat().accu == ""
    b.boite.accu_mv = 3400
    b.avancer(1)
    assert len(b.alarmes()) == 3


def test_plateau_10_min_sans_recharge(b):
    b.plateau()
    b.peser(129)
    b.boite.recharge_presente = False
    b.avancer(590, pas=10)
    assert b.alarmes() == []
    b.avancer(20, pas=10)
    assert b.alarmes() == [
        "Plateau au poste depuis plus de 10 min sans recharge : recharge sans contact en panne ?"
    ]
    b.avancer(600, pas=10)
    assert len(b.alarmes()) == 1
    assert b.poste.etat().recharge_presente is False
    # Le 5 V de la recharge présent (même accu plein) : pas d'alerte, même longtemps.
    b.plateau(False)
    b.plateau()
    b.boite.recharge_presente = True
    b.avancer(1200, pas=10)
    assert len(b.alarmes()) == 1


def test_voyant_clignote_tant_que_ce_n_est_pas_pret(b):
    vu = []
    for _ in range(4):
        vu.append(b.faux.commande("voyant_pret_fut"))
        b.avancer(0.5)
    assert vu == [True, False, True, False]
    b.jusqu_au_pret()
    for _ in range(3):
        b.avancer(0.5)
        assert b.faux.commande("voyant_pret_fut") is True


def test_bouton_lumineux_du_poste(b):
    b.plateau()
    b.peser(129)
    b.faux.actionner("bouton_pret_fut")
    b.poste.observer()
    assert b.poste.etat().etat == EN_PLACE
    assert b.poste.etat().messages[-1] == (
        "« Prêt » refusé, il manque : plateau immobile depuis 2 s."
    )
    # Bouton tenu : pas de nouvel appui. Relâché puis appuyé : prêt.
    b.avancer(2)
    assert b.poste.etat().etat == EN_PLACE
    b.faux.actionner("bouton_pret_fut", False)
    b.avancer(0.1)
    b.faux.actionner("bouton_pret_fut")
    b.avancer(0.1)
    assert b.poste.etat().etat == PRET


def test_plateau_perdu_puis_retire(b):
    b.jusqu_au_pret()
    assert b.poste.surveillance.test() is True
    b.plateau(False)
    etat = b.poste.etat()
    assert etat.etat == ABSENT and etat.cycle == 1
    assert b.poste.surveillance.test() is False
    assert "Le pont doit sortir de la zone du plateau" in b.poste.surveillance.quoi_faire
    assert etat.messages[-1] == "Plateau du fût plus vu : le poste n'est plus prêt."
    # Il revient tout de suite : la même vidange continue après un nouvel appui.
    b.plateau()
    b.avancer(2)
    b.poste.appuyer_pret("essai")
    assert b.poste.etat().cycle == 1
    assert b.poste.etat().messages[-1] == "Prêt de nouveau : la vidange du fût continue."
    # Il s'en va pour de bon : la vidange est abandonnée.
    b.peser(114)
    b.plateau(False)
    b.avancer(2)
    assert b.poste.etat().cycle is None
    assert b.registre.lire("SELECT issue FROM cycles")[0]["issue"] == "abandonne"
    assert b.mesures()["poids_fut_restant"] == pytest.approx(114 - TARE)
    assert b.poste.etat().messages[-1] == "fût retiré avant la fin de la vidange"


def test_doses_de_la_griffe_et_fut_vide(b, caplog):
    b.jusqu_au_pret()
    b.peser(119)
    assert b.poste.noter_dose(10) is None
    assert b.poste.poids_restant_kg() == pytest.approx(119 - TARE)
    # La griffe dit 10 kg de plus, mais la pesée n'a pas bougé : avertissement, pas d'arrêt.
    message = b.poste.noter_dose(10)
    assert message is not None and "écart 10,0 kg" in message
    assert b.poste.noter_dose(0) == message
    assert caplog.text.count("Regarder la pesée et la griffe") == 1
    assert b.poste.etat().etat == PRET

    b.peser(109)
    assert b.poste.finir_vidange(2) == (
        "Fût vide : 2 seaux, 20,0 kg vidés. Relever le volet, desserrer les freins, sortir le "
        "plateau."
    )
    assert b.registre.lire("SELECT issue FROM cycles")[0]["issue"] == "termine"
    assert b.mesures()["poids_fut_vide_total"] == pytest.approx(20)
    # Le fût vide doit sortir avant un nouveau « Prêt ».
    etat = b.poste.etat()
    assert etat.etat == EN_PLACE and etat.cycle is None
    assert etat.manque[0] == "sortir le plateau : ce fût est vide"
    assert b.poste.condition_plateau_parti.test() is False
    b.plateau(False)
    b.avancer(2)
    assert b.poste.condition_plateau_parti.test() is True


def test_alarmes_du_poste_ne_bloquent_jamais(b):
    """Réponse à la PR n° 77 : les alertes du poste sont des alarmes du registre pour
    information seulement. Ni le « Prêt », ni les doses, ni la fin du fût, ni le fût suivant
    n'attendent leur acquittement ; la check-list ne dit jamais « bloquant » pour elles."""
    b.boite.accu_mv, b.boite.accu_pct = 3200, 4
    b.plateau()
    b.peser(129)
    b.avancer(2)
    b.boite.radio_muette = True
    b.avancer(6)
    alarmes = b.alarmes()
    assert any(a.startswith("Accu du plateau presque vide") for a in alarmes)
    assert any(a.startswith("Pesée du fût absente") for a in alarmes)
    assert {a["module"] for a in b.registre.alarmes_ouvertes()} == {"poste_fut"}
    (constat,) = constats_registre(b.registre)
    assert constat.niveau == "attention" and pire([constat]) != "bloquant"
    # « Prêt » accepté, alarmes ouvertes.
    b.poste.appuyer_pret("essai")
    assert b.poste.etat().etat == PRET and b.poste.etat().cycle == 1
    # Les doses et le seau suivant : rien n'attend.
    b.poste.noter_dose(10, seau="S1")
    b.poste.noter_dose(10, seau="S2")
    b.boite.radio_muette = False
    b.peser(109)
    assert b.poste.finir_vidange(2).startswith("Fût vide : 2 seaux")
    # Le fût suivant : nouveau « Prêt » sans avoir rien acquitté.
    b.plateau(False)
    b.avancer(2)
    b.jusqu_au_pret()
    assert b.poste.etat().etat == PRET and b.poste.etat().cycle == 2
    assert len(b.alarmes()) >= 2
    assert all(a["acquittee_le"] is None for a in b.registre.alarmes_ouvertes())


def test_fin_sans_pesee_d_apres_les_doses(b):
    b.jusqu_au_pret()
    b.poste.noter_dose(12.5)
    b.boite.radio_muette = True
    b.avancer(1)
    assert b.poste.finir_vidange(1) == (
        "Fût vide : 1 seaux, 12,5 kg d'après les doses (pesée absente). Relever le volet, "
        "desserrer les freins, sortir le plateau."
    )


def test_pas_de_pesee_quand_la_griffe_est_dans_le_fut(tmp_path):
    dedans = [False]
    banc = BancPoste(tmp_path, griffe_hors_fut=lambda: not dedans[0])
    banc.peser(129)
    dedans[0] = True
    banc.peser(100)
    assert banc.poste.etat().poids_lu_kg == pytest.approx(129)
    banc.registre.fermer()


def test_sans_tour_des_pesees_pas_de_pesee_ni_d_alerte(tmp_path):
    liste = charger_entrees_sorties(LISTE)
    faux = FausseFabrique(liste)
    horloge = Horloge()
    with Materiel(liste, faux) as materiel:
        poste = PosteFut(POSTE, materiel, horloge=horloge, lecture_directe=True)
        faux.actionner("plateau_fut_en_place")
        poste.etat()
        horloge.t += 10
        etat = poste.etat()
    assert poste.pesee is None and etat.pesee == "pas de pesée du fût"
    assert not etat.pesee_absente and etat.manque == ()


# ---------------------------------------------------------------- mode et verrous


def test_mode_permis_par_le_panneau(b):
    assert "vient de bouger, attendre 2 s" in b.poste.refus_lancement("production")
    b.avancer(2)
    assert "n'est pas levé (contact ouvert : rabattu ou entre les deux)" in (
        b.poste.refus_lancement("production")
    )
    assert b.poste.refus_lancement("lavage") is None
    assert b.poste.refus_lancement("uv_ozone") is None
    b.faux.actionner("reed_panneau_poste_fut")
    b.poste.observer()
    assert b.poste.refus_lancement("lavage").startswith("Lavage refusé : le panneau du poste")
    b.avancer(2)
    assert b.poste.refus_lancement("production") is None
    assert b.poste.refus_lancement("lavage") == (
        "Lavage refusé : le panneau long du poste du fût est levé. Le rabattre."
    )
    assert b.poste.condition_mode("production").test() is True


def test_verrous_pendant_l_echange(b):
    assert b.poste.echange_en_cours and b.poste.tiroir_stockage_doit_rester_rentre
    assert "pont interdit en x 0 à 0,8 m" in b.poste.refus_pont(0.5)
    assert b.poste.refus_pont(0.9) is None
    assert "y ≤ 0,875 m" in b.poste.refus_remplissage(0.9)
    assert b.poste.refus_remplissage(0.875) is None
    b.plateau()
    assert b.poste.refus_pont(0.5) is not None
    b.avancer(2)
    assert not b.poste.echange_en_cours
    assert b.poste.refus_pont(0.5) is None and b.poste.refus_remplissage(0.9) is None


def test_verrous_de_la_griffe_et_de_la_prehension(b):
    assert "poignée du volet" in b.poste.refus_griffe(0.55, 1.01, 1.10, "production")
    assert b.poste.refus_griffe(0.55, 1.01, 1.13, "production") is None
    # Contact du panneau ouvert, mode lavage : volet considéré relevé, pas au-dessus du fût.
    assert b.poste.volet_considere_releve("lavage")
    assert "au-dessus du fût" in b.poste.refus_griffe(0.29, 0.57, 1.5, "lavage")
    assert b.poste.refus_griffe(0.29, 0.57, 1.5, "production") is None
    assert b.poste.refus_griffe(0.29, 0.90, 1.5, "lavage") is None
    assert b.poste.refus_passage_paroi_lavage(0.84, 0.86) is None
    assert b.poste.refus_passage_paroi_lavage(0.80, 0.90) == (
        "passage de la paroi côté stockage refusé : fond du seau à 0,8 m (au moins 0,84 m), "
        "axe à y 0,9 m (au plus 0,86 m)"
    )


# ---------------------------------------------------------------- réglages


def test_reglages_du_poste_verifies():
    donnees = POSTE.model_dump()
    donnees["fut_fond_interieur_z"] = 1.1
    donnees["pesee"]["plausible_kg"] = [200, 50]
    with pytest.raises(ValueError) as erreur:
        ReglagesPosteFut.model_validate(donnees)
    assert "plausible_kg : aller du plus petit au plus grand" in str(erreur.value)


def test_l_etalonnage_est_dans_pesees_yaml():
    assert "zero_brut" not in POSTE.pesee.model_dump()
    assert REGLAGES.pesees.etalonnage[SIGNAL].brut_par_kg != 0
    assert REGLAGES.pesees.lentes[SIGNAL].espacement_s == 1


def test_reglages_fond_sous_le_bord(reglages):
    remplacer(
        reglages / "machine.yaml", "fut_fond_interieur_z: 0.1825", "fut_fond_interieur_z: 1.1"
    )
    assert "le fond du fût (fut_fond_interieur_z) doit être sous son bord" in erreur_de(reglages)


# ---------------------------------------------------------------- simulateur


def test_simulateur_echange_de_fut(capsys):
    from vidange.poste_fut.module import module_echange_fut

    with Simulateur(REGLAGES, charger_entrees_sorties(LISTE), "echange_fut") as banc:
        planning = banc.jouer([module_echange_fut(banc.poste_fut())])
        etat = banc.poste_fut().etat()
    assert planning.fini, planning.probleme
    sortir, pret = planning.lignes
    # Plateau sorti à 40 s, vu absent 2 s plus tard ; Prêt appuyé à 430 s.
    assert sortir.fin == pytest.approx(42)
    assert pret.fin == pytest.approx(430)
    assert (70, "pesée « pesee_fut » : radio du plateau muette") in planning.evenements
    assert (342, "pesée « pesee_fut » : 129 kg") in planning.evenements
    assert etat.etat == PRET and etat.poids_plein_kg == pytest.approx(129 - TARE)
    assert simulateur(["poste_fut"]) == 0
    assert "« attendre_le_pret »" in capsys.readouterr().out


def test_simulateur_echange_sans_pesee():
    from vidange.poste_fut.module import module_echange_fut

    with Simulateur(REGLAGES, charger_entrees_sorties(LISTE), "echange_fut_sans_pesee") as banc:
        planning = banc.jouer([module_echange_fut(banc.poste_fut())])
        etat = banc.poste_fut().etat()
    assert planning.fini, planning.probleme
    assert etat.etat == PRET and etat.poids_plein_kg is None and etat.sans_pesee
    assert etat.pesee_absente
    assert any("Pesée du fût absente (radio du plateau muette)" in m for m in etat.messages)


def test_simulateur_scenario_inconnu_et_evenement_mal_ecrit(reglages):
    with pytest.raises(ErreurSimulation, match="scénario « absent » absent de simulateur.yaml"):
        Simulateur(REGLAGES, charger_entrees_sorties(LISTE), "absent")
    remplacer(
        reglages / "simulateur.yaml",
        "        pesee: pesee_fut\n        kg: 36\n",
        "        pesee: pesee_fut\n        kg: 36\n        capteur: bouton_pret_fut\n",
    )
    assert "une seule chose par événement" in erreur_de(reglages)


# ---------------------------------------------------------------- page web et écran


def test_page_web_du_poste(b, tmp_path):
    chef = nouveau_chef(b.horloge)
    bilans = Bilans(tmp_path, ReglagesBilan(lignes_journal=0), b.registre, chef)
    services = Services(chef, b.registre, bilans.acquitter, checklist=list, poste=b.poste)
    client = client_connecte(creer_app_de_test(services), adresse=LOCAL)
    assert client.get("/api/etat").json()["poste_fut"]["etat"] == ABSENT
    reponse = client.post("/api/poste-fut/pret")
    assert reponse.status_code == 409 and "il manque : plateau du fût" in reponse.json()["detail"]
    b.plateau()
    b.peser(129)
    b.avancer(2)
    poste = client.get("/api/poste-fut").json()
    assert poste["accu_pct"] == 80 and poste["signal_dbm"] == -60 and poste["accu_v"] == 3.9
    reponse = client.post("/api/poste-fut/pret")
    assert reponse.status_code == 200 and reponse.json()["etat"] == PRET
    assert client.get("/api/poste-fut").json()["gestes"][-1] == "Appuyer sur « Prêt »"
    sans_poste = Services(chef, b.registre, bilans.acquitter, checklist=list)
    client = client_connecte(creer_app_de_test(sans_poste), adresse=LOCAL)
    assert client.get("/api/poste-fut").status_code == 404


def test_ecran_du_poste(b, tmp_path):
    chef = nouveau_chef(b.horloge)
    bilans = Bilans(tmp_path, ReglagesBilan(lignes_journal=0), b.registre, chef)
    nextion = FauxNextion()
    liaison = LiaisonEcran(REGLAGES_ECRAN, nextion.ouvrir, horloge=b.horloge)
    mode = ModeMachine(tmp_path / "mode.json", chef, b.registre)
    ecran = Ecran(
        REGLAGES_ECRAN,
        liaison,
        chef,
        b.registre,
        bilans.acquitter,
        mode,
        horloge=b.horloge,
        poste=b.poste,
    )

    def tour() -> None:
        ecran.tour()
        ecran.tour()

    tour()
    assert nextion.page == "etat"
    b.plateau()
    b.peser(129)
    tour()
    assert nextion.page == "poste_fut"
    assert nextion.texte("t_titre") == "EN PLACE, PAS PRÊT"
    assert nextion.texte("t_poids") == "Substrat : 95,6 kg · accu 80 % · radio -60 dBm"
    assert nextion.texte("t_gestes").startswith("À la main : fût sur les cales, soupape enlevée")
    assert nextion.texte("t_manque") == "Il manque : plateau immobile depuis 2 s."
    nextion.appuyer("b_pret")
    tour()
    assert nextion.texte("t_manque") == "« Prêt » refusé, il manque : plateau immobile depuis 2 s."
    b.avancer(2)
    nextion.appuyer("b_pret")
    tour()
    assert b.poste.etat().etat == PRET
    assert nextion.page == "etat"
    assert nextion.texte("t_info") == "Poste du fût prêt."
