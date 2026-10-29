"""Poste du fût : carte de pesée HX711, pesée, états du poste, bouton « Prêt », mode, verrous."""

import logging

import pytest
from fastapi.testclient import TestClient

from vidange.api import Services, creer_app
from vidange.ecran import Ecran, FauxNextion, LiaisonEcran
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fiabilite import Bilans
from vidange.materiel import ErreurMateriel, FausseFabrique, LectureInterrompue, Materiel
from vidange.materiel.faux import FauxHx711
from vidange.materiel.puces import Hx711, PeseeMuette
from vidange.mode import ModeMachine
from vidange.poste_fut import ABSENT, EN_PLACE, PRET, ErreurPesee, ErreurPoste, PosteFut
from vidange.poste_fut.outil import main as outil_pesee
from vidange.poste_fut.pesee import filtrer, pente
from vidange.registre import Registre
from vidange.reglages import PosteFut as ReglagesPosteFut
from vidange.reglages import ReglagesBilan, charger_reglages
from vidange.simulateur import ErreurSimulation, Simulateur
from vidange.simulateur.outil import main as simulateur

from .conftest import DOSSIER_PI
from .test_api import CLE, LOCAL, reglages_api
from .test_chef import Horloge, nouveau_chef
from .test_ecran import REGLAGES as REGLAGES_ECRAN
from .test_entrees_sorties import erreur_de as erreur_de_liste
from .test_reglages import erreur_de, remplacer

LISTE = DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
POSTE = REGLAGES.machine.poste_fut
assert POSTE is not None
# Réglages du dépôt : 10 000 points par kg, zéro à 0, tare 40 kg.
POINTS_PAR_KG = POSTE.pesee.brut_par_kg


class BancPoste:
    """Le vrai poste du fût sur le faux matériel, avec un vrai registre et une fausse horloge."""

    def __init__(self, dossier, griffe_hors_fut=lambda: True) -> None:
        self.horloge = Horloge()
        liste = charger_entrees_sorties(LISTE)
        self.faux = FausseFabrique(liste)
        self.materiel = Materiel(liste, self.faux)
        self.registre = Registre(dossier / "registre.sqlite", dossier / "photos")
        self.poste = PosteFut(
            POSTE,
            self.materiel,
            self.registre,
            horloge=self.horloge,
            griffe_hors_fut=griffe_hors_fut,
        )

    def peser(self, kg: float) -> None:
        self.faux.regler_pesee("pesee_fut", round(kg * POINTS_PAR_KG))
        self.poste.peser()

    def chariot(self, au_fond: bool = True) -> None:
        self.faux.actionner("chariot_fut_en_place", au_fond)
        self.poste.observer()

    def avancer(self, secondes: float) -> None:
        self.horloge.t += secondes
        self.poste.observer()

    def jusqu_au_pret(self, kg: float = 165) -> None:
        self.chariot()
        self.peser(kg)
        self.avancer(2)
        self.poste.appuyer_pret("essai")

    def mesures(self) -> dict[str, float]:
        return {m["nom"]: m["valeur"] for m in self.registre.lire("SELECT * FROM mesures")}


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


# ---------------------------------------------------------------- carte HX711


def test_hx711_lit_les_mesures_bit_par_bit():
    faux = FauxHx711()
    hx711 = Hx711(faux, horloge_ns=faux.horloge_ns, horloge=faux.horloge, dormir=faux.dormir)
    faux.brut = 1_234_567
    assert hx711.lire(0.5) == 1_234_567
    faux.brut = -5
    assert hx711.lire(0.5) == -5
    assert faux.lectures == 2


def test_hx711_prise_debranchee():
    faux = FauxHx711()
    faux.debranche = True
    hx711 = Hx711(faux, horloge_ns=faux.horloge_ns, horloge=faux.horloge, dormir=faux.dormir)
    with pytest.raises(PeseeMuette, match="prise débranchée"):
        hx711.lire(0.5)
    assert faux.temps == pytest.approx(0.5, abs=0.002)


def test_hx711_impulsion_trop_longue_jetee():
    faux = FauxHx711()
    temps = iter(range(0, 10**9, 60_000))
    hx711 = Hx711(faux, horloge_ns=lambda: next(temps), horloge=faux.horloge, dormir=faux.dormir)
    with pytest.raises(LectureInterrompue, match="impulsion d'horloge de 60 µs"):
        hx711.lire(0.5)


def test_hx711_fil_dt_a_la_masse_et_hors_echelle():
    class DtAZero(FauxHx711):
        def dt(self) -> bool:
            return False

    a_zero = DtAZero()
    with pytest.raises(ErreurMateriel, match="fil DT reste à 0"):
        Hx711(
            a_zero, horloge_ns=a_zero.horloge_ns, horloge=a_zero.horloge, dormir=a_zero.dormir
        ).lire(0.5)
    faux = FauxHx711()
    faux.brut = (1 << 23) - 1
    with pytest.raises(ErreurMateriel, match="hors échelle"):
        Hx711(faux, horloge_ns=faux.horloge_ns, horloge=faux.horloge, dormir=faux.dormir).lire(0.5)


def test_pesee_par_son_nom_dans_le_materiel():
    liste = charger_entrees_sorties(LISTE)
    faux = FausseFabrique(liste)
    with Materiel(liste, faux) as materiel:
        assert materiel.branchements["pesee_fut"].ressource == (
            "hx711",
            "/dev/gpiochip0",
            "GPIO20",
            "GPIO21",
        )
        faux.regler_pesee("pesee_fut", 420_000)
        # Délai large : sur un ordinateur d'essai chargé, des lectures sont jetées puis refaites.
        assert materiel.peser("pesee_fut", 5) == 420_000
        faux.debrancher("pesee_fut")
        with pytest.raises(PeseeMuette, match="signal « pesee_fut » : pas de réponse"):
            materiel.peser("pesee_fut", 0.5)
    assert faux.balances["pesee_fut"].ferme


def test_liste_verifie_la_pesee(entrees_sorties):
    remplacer(entrees_sorties, "broche: [GPIO20, GPIO21]", "broche: GPIO20")
    message = erreur_de_liste(entrees_sorties)
    assert "une pesée (HX711) a 2 broches, dans cet ordre : [DT, SCK]" in message


def test_liste_refuse_une_pesee_en_5_v_ou_sur_une_broche_prise(entrees_sorties):
    remplacer(
        entrees_sorties,
        "broche: [GPIO20, GPIO21]\n    type: pesee\n    tension: 3.3",
        "broche: [GPIO6, GPIO21]\n    type: pesee\n    tension: 5",
    )
    message = erreur_de_liste(entrees_sorties)
    assert "signal « pesee_fut » : 5 V, plus que les 3.3 V acceptés par la carte « pi »" in message
    assert "broche GPIO6 : utilisée par plusieurs signaux (onduleur_sur_batterie, pesee_fut)" in (
        message
    )


# ---------------------------------------------------------------- pesée


def test_filtrer_jette_les_lectures_aberrantes():
    assert filtrer([10, 10.5, 9.8, 50, 10.2], 2, 3) == pytest.approx(10.1)
    with pytest.raises(ErreurPesee, match="trop dispersées"):
        filtrer([0, 10, 20], 2, 2)


def test_pente_de_l_etalonnage():
    assert pente(1000, 201_000, 20) == 10_000
    with pytest.raises(ValueError, match="n'a pas bougé"):
        pente(1000, 1000, 20)
    with pytest.raises(ValueError, match="plus grand que 0"):
        pente(1000, 2000, 0)


def test_outil_d_etalonnage_avec_le_faux_materiel(capsys):
    assert outil_pesee(["--faux", "zero"]) == 0
    assert "    zero_brut: 0" in capsys.readouterr().out
    assert outil_pesee(["--faux", "etalonner", "20"]) == 1
    assert "n'a pas bougé" in capsys.readouterr().err
    assert outil_pesee(["--faux", "tare"]) == 0
    assert "    tare_kg: 0.00" in capsys.readouterr().out


# ---------------------------------------------------------------- états du poste


def test_du_chariot_absent_au_pret(b):
    etat = b.poste.etat()
    assert etat.etat == ABSENT and etat.libelle == "Chariot du fût absent"
    assert "chariot du fût contre les 2 butées du fond" in etat.manque
    with pytest.raises(ErreurPoste, match="« Prêt » refusé, il manque : chariot du fût"):
        b.poste.appuyer_pret("essai")

    b.chariot()
    b.faux.debrancher("pesee_fut")
    b.poste.peser()
    etat = b.poste.etat()
    assert etat.etat == EN_PLACE and not etat.chariot_stable
    assert etat.manque == (
        "chariot immobile depuis 2 s",
        "pesée qui répond : brancher la prise magnétique",
    )
    assert etat.pesee == "pesée débranchée" and etat.poids_lu_kg is None

    b.faux.debrancher("pesee_fut", False)
    b.peser(10)
    b.avancer(2)
    assert b.poste.etat().manque == ("poids plausible : 10,0 kg lus, attendu entre 20 et 400 kg",)

    b.peser(165)
    etat = b.poste.etat()
    assert etat.etat == EN_PLACE and etat.manque == () and etat.poids_net_kg == pytest.approx(125)
    b.poste.appuyer_pret("essai", fut="F3")
    etat = b.poste.etat()
    assert etat.etat == PRET and etat.cycle == 1 and etat.poids_plein_kg == pytest.approx(125)
    assert etat.messages[-1] == "Prêt : fût de 125,0 kg (substrat)."
    cycle = b.registre.lire("SELECT * FROM cycles")[0]
    assert cycle["module"] == "vidange" and cycle["fin"] is None
    mesure = b.registre.lire("SELECT * FROM mesures")[0]
    assert mesure["nom"] == "poids_fut_plein" and mesure["valeur"] == pytest.approx(125)
    assert mesure["capteur"] == "pesee_fut" and mesure["fut_id"] is not None
    # Un deuxième appui ne fait rien.
    b.poste.appuyer_pret("essai")
    assert len(b.registre.lire("SELECT * FROM cycles")) == 1


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
    b.chariot()
    b.peser(165)
    b.faux.actionner("bouton_pret_fut")
    b.poste.observer()
    assert b.poste.etat().etat == EN_PLACE
    assert b.poste.etat().messages[-1] == (
        "« Prêt » refusé, il manque : chariot immobile depuis 2 s."
    )
    # Bouton tenu : pas de nouvel appui. Relâché puis appuyé : prêt.
    b.avancer(2)
    assert b.poste.etat().etat == EN_PLACE
    b.faux.actionner("bouton_pret_fut", False)
    b.avancer(0.1)
    b.faux.actionner("bouton_pret_fut")
    b.avancer(0.1)
    assert b.poste.etat().etat == PRET


def test_chariot_perdu_puis_retire(b):
    b.jusqu_au_pret()
    assert b.poste.surveillance.test() is True
    b.chariot(False)
    etat = b.poste.etat()
    assert etat.etat == ABSENT and etat.cycle == 1
    assert b.poste.surveillance.test() is False
    assert "Le pont doit sortir de la zone du chariot" in b.poste.surveillance.quoi_faire
    assert etat.messages[-1] == "Chariot du fût plus vu : le poste n'est plus prêt."
    # Il revient tout de suite : la même vidange continue après un nouvel appui.
    b.chariot()
    b.avancer(2)
    b.poste.appuyer_pret("essai")
    assert b.poste.etat().cycle == 1
    assert b.poste.etat().messages[-1] == "Prêt de nouveau : la vidange du fût continue."
    # Il s'en va pour de bon : la vidange est abandonnée.
    b.peser(150)
    b.chariot(False)
    b.avancer(2)
    assert b.poste.etat().cycle is None
    assert b.registre.lire("SELECT issue FROM cycles")[0]["issue"] == "abandonne"
    assert b.mesures()["poids_fut_restant"] == pytest.approx(110)
    assert b.poste.etat().messages[-1] == "fût retiré avant la fin de la vidange"


def test_doses_de_la_griffe_et_fut_vide(b, caplog):
    b.jusqu_au_pret()
    b.peser(155)
    assert b.poste.noter_dose(10) is None
    assert b.poste.poids_restant_kg() == pytest.approx(115)
    # La griffe dit 10 kg de plus, mais la pesée n'a pas bougé : avertissement, pas d'arrêt.
    message = b.poste.noter_dose(10)
    assert message is not None and "écart 10,0 kg" in message
    assert b.poste.noter_dose(0) == message
    assert caplog.text.count("Regarder la pesée et la griffe") == 1
    assert b.poste.etat().etat == PRET

    b.peser(145)
    assert b.poste.finir_vidange(2) == "Fût vide : 2 seaux, 20,0 kg vidés. Sortir le chariot."
    assert b.registre.lire("SELECT issue FROM cycles")[0]["issue"] == "termine"
    assert b.mesures()["poids_fut_vide_total"] == pytest.approx(20)
    # Le fût vide doit sortir avant un nouveau « Prêt ».
    etat = b.poste.etat()
    assert etat.etat == EN_PLACE and etat.cycle is None
    assert etat.manque[0] == "sortir le chariot : ce fût est vide"
    assert b.poste.condition_chariot_parti.test() is False
    b.chariot(False)
    b.avancer(2)
    assert b.poste.condition_chariot_parti.test() is True


def test_fin_sans_pesee_d_apres_les_doses(b):
    b.jusqu_au_pret()
    b.poste.noter_dose(12.5)
    b.faux.debrancher("pesee_fut")
    b.poste.peser()
    assert b.poste.finir_vidange(1) == (
        "Fût vide : 1 seaux, 12,5 kg d'après les doses (pesée absente). Sortir le chariot."
    )


def test_pas_de_pesee_quand_la_griffe_est_dans_le_fut(tmp_path):
    dedans = [False]
    banc = BancPoste(tmp_path, griffe_hors_fut=lambda: not dedans[0])
    banc.peser(165)
    dedans[0] = True
    banc.peser(100)
    assert banc.poste.etat().poids_lu_kg == pytest.approx(165)
    banc.registre.fermer()


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
    b.chariot()
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
    donnees["pesee"]["lectures_valides_min"] = 9
    donnees["pesee"]["plausible_kg"] = [400, 20]
    with pytest.raises(ValueError) as erreur:
        ReglagesPosteFut.model_validate(donnees)
    texte = str(erreur.value)
    assert "lectures_valides_min ne peut pas dépasser lectures" in texte
    assert "plausible_kg : aller du plus petit au plus grand" in texte


def test_reglages_fond_sous_le_bord(reglages):
    remplacer(
        reglages / "machine.yaml", "fut_fond_interieur_z: 0.1825", "fut_fond_interieur_z: 1.1"
    )
    assert "le fond du fût (fut_fond_interieur_z) doit être sous son bord" in erreur_de(reglages)


# ---------------------------------------------------------------- simulateur


def test_simulateur_echange_de_fut(capsys):
    with Simulateur(REGLAGES, charger_entrees_sorties(LISTE), "echange_fut") as banc:
        from vidange.poste_fut.module import module_echange_fut

        planning = banc.jouer([module_echange_fut(banc.poste_fut())])
        etat = banc.poste_fut().etat()
    assert planning.fini, planning.probleme
    sortir, pret = planning.lignes
    # Chariot sorti à 40 s, vu absent 2 s plus tard ; Prêt appuyé à 430 s.
    assert sortir.fin == pytest.approx(42)
    assert pret.fin == pytest.approx(430)
    assert (400, "pesée « pesee_fut » : 165 kg") in planning.evenements
    assert etat.etat == PRET and etat.poids_plein_kg == pytest.approx(125)
    assert simulateur(["poste_fut"]) == 0
    assert "« attendre_le_pret »" in capsys.readouterr().out


def test_simulateur_scenario_inconnu_et_evenement_mal_ecrit(reglages):
    with pytest.raises(ErreurSimulation, match="scénario « absent » absent de simulateur.yaml"):
        Simulateur(REGLAGES, charger_entrees_sorties(LISTE), "absent")
    remplacer(
        reglages / "simulateur.yaml",
        "        pesee: pesee_fut\n        kg: 42\n",
        "        pesee: pesee_fut\n        kg: 42\n        capteur: bouton_pret_fut\n",
    )
    assert "une seule chose par événement" in erreur_de(reglages)


# ---------------------------------------------------------------- page web et écran


def test_page_web_du_poste(b, tmp_path):
    chef = nouveau_chef(b.horloge)
    bilans = Bilans(tmp_path, ReglagesBilan(lignes_journal=0), b.registre, chef)
    services = Services(chef, b.registre, bilans.acquitter, checklist=list, poste=b.poste)
    client = TestClient(
        creer_app(services, reglages_api(), CLE),
        client=LOCAL,
        headers={"Authorization": f"Bearer {CLE}"},
    )
    assert client.get("/api/etat").json()["poste_fut"]["etat"] == ABSENT
    reponse = client.post("/api/poste-fut/pret")
    assert reponse.status_code == 409 and "il manque : chariot du fût" in reponse.json()["detail"]
    b.chariot()
    b.peser(165)
    b.avancer(2)
    reponse = client.post("/api/poste-fut/pret")
    assert reponse.status_code == 200 and reponse.json()["etat"] == PRET
    assert client.get("/api/poste-fut").json()["gestes"][-1] == "Appuyer sur « Prêt »"
    sans_poste = Services(chef, b.registre, bilans.acquitter, checklist=list)
    client = TestClient(
        creer_app(sans_poste, reglages_api(), CLE),
        client=LOCAL,
        headers={"Authorization": f"Bearer {CLE}"},
    )
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
    b.chariot()
    b.peser(165)
    tour()
    assert nextion.page == "poste_fut"
    assert nextion.texte("t_titre") == "EN PLACE, PAS PRÊT"
    assert nextion.texte("t_poids") == "Substrat : 125,0 kg"
    assert nextion.texte("t_gestes").startswith("À la main : butées du fond, frein")
    assert nextion.texte("t_manque") == "Il manque : chariot immobile depuis 2 s."
    nextion.appuyer("b_pret")
    tour()
    assert nextion.texte("t_manque") == "« Prêt » refusé, il manque : chariot immobile depuis 2 s."
    b.avancer(2)
    nextion.appuyer("b_pret")
    tour()
    assert b.poste.etat().etat == PRET
    assert nextion.page == "etat"
    assert nextion.texte("t_info") == "Poste du fût prêt."


def test_lectures_interrompues_refaites_puis_signalees(b, monkeypatch):
    pesee = b.poste.pesee
    vraie = b.materiel.peser
    appels = iter(range(1000))

    def une_sur_deux(nom, delai_s):
        if next(appels) % 2:
            raise LectureInterrompue("impulsion d'horloge de 80 µs")
        return vraie(nom, delai_s)

    monkeypatch.setattr(b.materiel, "peser", une_sur_deux)
    b.faux.regler_pesee("pesee_fut", round(165 * POINTS_PAR_KG))
    assert pesee.peser() == pytest.approx(165)
    assert (pesee.lectures, pesee.interrompues) == (9, 4)

    def toujours(nom, delai_s):
        raise LectureInterrompue("impulsion d'horloge de 80 µs")

    monkeypatch.setattr(b.materiel, "peser", toujours)
    with pytest.raises(ErreurPesee, match=r"interrompues par Linux \(10 sur 10\)"):
        pesee.peser()
