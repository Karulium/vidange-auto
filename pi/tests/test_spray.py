"""Spray, côté Pi (tâche 39) : table des registres, fausse carte n° 5, gestes du Pi, règle d'or
du bras, réglages."""

import json

import pytest
from fastapi.testclient import TestClient

from vidange import entete_spray
from vidange.api.app import Services, creer_app
from vidange.chef import Chef
from vidange.demarrage import constats_spray, preparer_spray
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel
from vidange.materiel import carte_spray as table
from vidange.materiel.modbus import ClientModbus
from vidange.registre import Registre
from vidange.reglages import ReglagesChef, charger_reglages, courants_tmc2209
from vidange.remplissage.regles import Contexte, Pose, ReglesRemplissage
from vidange.simulateur import Simulateur
from vidange.spray import ErreurSpray, Spray, module_nettoyage_tubes, module_spray
from vidange.spray.outil import main as outil
from vidange.spray.spray import QUOI_FAIRE_BRAS

from .conftest import DOSSIER_PI
from .test_api import CLE, LOCAL, reglages_api
from .test_chef import Horloge, nouveau_chef
from .test_reglages import erreur_de, remplacer

LISTE_CHEMIN = DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"
LISTE = charger_entrees_sorties(LISTE_CHEMIN)
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
SPRAY = MACHINE.spray
assert SPRAY is not None
VIDE = SPRAY.flacons.vide_g[1]
DOSE_A = SPRAY.dose.par_format_g["seau_a"]


class Banc:
    """Une fausse carte, le vrai Spray, ce que disent les modules voisins."""

    def __init__(self, tmp_path, registre: bool = False) -> None:
        self.horloge = Horloge()
        self.fabrique = FausseFabrique(LISTE)
        self.materiel = Materiel(LISTE, self.fabrique, seulement=[SPRAY.signal])
        self.carte = self.fabrique.carte_spray()
        self.carte.regler_horloge(self.horloge)
        self.carte.appliquer(SPRAY)
        self.refus_chariot: str | None = None
        self.porte = False
        self.purge = False
        self.rotations: list[float] = []
        self.registre = (
            Registre(tmp_path / "registre.sqlite", tmp_path / "photos") if registre else None
        )
        self.fichier = tmp_path / "spray.json"
        self.spray = self.nouveau_spray()

    def nouveau_spray(self) -> Spray:
        return Spray(
            MACHINE,
            self.materiel,
            self.registre,
            self.fichier,
            horloge=self.horloge,
            refus_chariot=lambda: self.refus_chariot,
            porte_ouverte=lambda: self.porte,
            tourner_seau=self.rotations.append,
            permission=lambda geste: "purge en cours" if self.purge else None,
        )

    def attendre(self, secondes: float, observer: bool = True) -> None:
        fin = self.horloge.t + secondes
        while self.horloge.t < fin - 1e-9:
            self.horloge.t += 0.05
            if observer:
                self.spray.observer()

    def jusqu_a(self, condition, max_s: float = 60.0) -> None:
        fin = self.horloge.t + max_s
        while not condition():
            assert self.horloge.t < fin, "trop long"
            self.horloge.t += 0.05
            self.spray.observer()

    def pret(self) -> None:
        """Carte lue, origine faite."""
        self.spray.lire()
        self.spray.lancer_origine()
        self.jusqu_a(self.spray.origine_faite)

    def bras_dehors(self, format: str = "seau_a") -> None:
        self.pret()
        self.spray.preparer("S1", format)
        self.jusqu_a(self.spray.agitation_faite)
        self.spray.sortir()
        self.jusqu_a(self.spray.bras_sorti)

    def un_seau(self, format: str = "seau_a", seau: str = "S1"):
        self.spray.preparer(seau, format)
        self.jusqu_a(self.spray.agitation_faite)
        self.spray.sortir()
        self.jusqu_a(self.spray.bras_sorti)
        self.spray.pulveriser()
        self.jusqu_a(self.spray.pulverisation_finie)
        self.spray.ranger()
        self.jusqu_a(self.spray.bras_range)
        return self.spray.noter()


@pytest.fixture
def banc(tmp_path):
    banc = Banc(tmp_path)
    yield banc
    banc.materiel.fermer()


# ------------------------------------------------------------ la table et le bus


def test_table_aller_retour():
    flacons = tuple(table.Flacon(-5 + i, 312.4 - i, i == 1, i == 2) for i in range(4))
    etat = table.EtatSpray(
        version=table.VERSION,
        demarrages=3,
        etat=table.ETAT_BRAS_RANGE | table.ETAT_ORIGINE_FAITE,
        erreurs=table.ERREUR_BALANCE_MUETTE[1] | table.ERREUR_BALANCE_INSTABLE[2],
        angle_deg=72.4,
        numero_ordre=7,
        suite_ordre=table.SUITE_FAIT,
        refus=0,
        silence_pi_ms=120,
        flacons=flacons,
        dose=table.Dose(1, 11.0, 10.9, 6.25, table.DOSE_ATTEINTE, 12),
        agitateurs_pct=60,
        trames_abimees=2,
    )
    registres = table.encoder(etat)
    assert len(registres) == table.NB_REGISTRES and registres[0] == 0x5350
    assert table.decoder(registres) == etat
    assert table.ordre(table.ORDRE_SPRAY, 9, 1, 110) == [4, 1, 110, 9]
    with pytest.raises(ValueError):
        table.ordre(table.ORDRE_SORTIR, 1, -1)


def test_table_pas_la_carte_du_spray():
    registres = table.encoder(
        table.EtatSpray(
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            (table.Flacon(0, 0, False, False),) * 4,
            table.Dose(0, 0, 0, 0, 0, 0),
            0,
            0,
        )
    )
    with pytest.raises(ErreurMateriel, match="pas la carte du spray"):
        table.decoder([0x5053, *registres[1:]])
    with pytest.raises(ErreurMateriel, match="table des registres n° 2"):
        table.decoder([registres[0], 2, *registres[2:]])


def test_ecriture_modbus_et_refus(banc):
    client = banc.materiel._clients["rs485_spray"]
    assert isinstance(client, ClientModbus)
    client.ecrire_registres(1, table.REGISTRE_BATTEMENT, [5])
    assert banc.carte.battements == 1
    with pytest.raises(ErreurMateriel, match="écriture refusée"):
        client.ecrire_registres(1, 10, [1])
    banc.carte.debranche = True
    with pytest.raises(ErreurMateriel, match="pas de réponse"):
        banc.materiel.ecrire_spray("carte_spray", table.REGISTRE_BATTEMENT, [6])


def test_la_carte_du_spray_dans_la_liste(entrees_sorties):
    remplacer(entrees_sorties, "    adresse: 1\n    module: spray", "    module: spray")
    with pytest.raises(Exception, match="adresse Modbus"):
        charger_entrees_sorties(entrees_sorties)


def test_la_carte_du_spray_a_son_bus(entrees_sorties):
    remplacer(entrees_sorties, "    carte: rs485_spray", "    carte: rs485_pesee")
    remplacer(
        entrees_sorties, "    adresse: 1\n    module: spray", "    adresse: 9\n    module: spray"
    )
    with pytest.raises(Exception, match="son bus à elle"):
        charger_entrees_sorties(entrees_sorties)


# ------------------------------------------------------------ règle d'or du bras


def test_bras_pas_range_chariot_immobile():
    regles = ReglesRemplissage(MACHINE)
    pose = Pose(y=0.135, z=0.40, a=0, barres=0.30, pousseur=0.0)
    sorti = Contexte(
        True, None, True, bras_spray_sorti=True, hauteur_seau=0.25, micropore_escamote=True
    )
    refus = regles.refus_mouvement(pose, pose.avec(z=0.30), sorti)
    assert "seule la rotation du seau" in refus and "plateau_z" in refus
    assert "barres" in regles.refus_mouvement(pose, pose.avec(barres=0.32), sorti)
    assert "remplissage_y" in regles.refus_mouvement(pose, pose.avec(y=0.155), sorti)
    # La rotation du seau reste permise.
    assert regles.refus_mouvement(pose, pose.avec(a=200), sorti) is None
    range_ = Contexte(
        True, None, True, bras_spray_sorti=False, hauteur_seau=0.25, micropore_escamote=True
    )
    assert regles.refus_mouvement(pose, pose.avec(z=0.30), range_) is None


def test_bras_suppose_sorti_tant_que_pas_vu_range(banc):
    spray = banc.spray
    # Jamais lue : supposé sorti.
    assert spray.bras_spray_sorti()
    banc.pret()
    assert not spray.bras_spray_sorti()
    spray.preparer("S1", "seau_a")
    banc.jusqu_a(spray.agitation_faite)
    spray.sortir()
    # Ordre parti, carte pas relue : déjà « sorti ».
    assert spray.bras_spray_sorti()
    banc.jusqu_a(spray.bras_sorti)
    assert spray.bras_spray_sorti()
    spray.ranger()
    assert spray.bras_spray_sorti()
    banc.jusqu_a(spray.bras_range)
    assert not spray.bras_spray_sorti()


def test_carte_muette_bras_suppose_sorti(banc):
    banc.pret()
    assert not banc.spray.bras_spray_sorti()
    banc.carte.debranche = True
    banc.attendre(0.5)
    # Pas encore « muette » (liaison → muette_s), puis supposé sorti.
    assert not banc.spray.bras_spray_sorti()
    banc.attendre(SPRAY.liaison.muette_s)
    assert banc.spray.bras_spray_sorti()
    assert "muette" in banc.spray.refus_carte()
    with pytest.raises(ErreurSpray, match="muette"):
        banc.spray.preparer("S1", "seau_a")
    banc.carte.debranche = False
    banc.attendre(0.2)
    assert not banc.spray.bras_spray_sorti()


def test_bras_pousse_sans_ordre(banc):
    banc.pret()
    banc.carte.pousser_bras()
    banc.attendre(0.2)
    assert banc.spray.bras_spray_sorti()
    assert "sans ordre" in banc.spray.refus_carte()
    assert any("poussé" in m for m in banc.spray.messages)


def test_regle_6_refusee(banc):
    banc.pret()
    banc.spray.preparer("S1", "seau_a")
    banc.refus_chariot = "bras du spray : plateau ≤ 0,43 (il est à 0,5)"
    assert "plateau ≤ 0,43" in banc.spray.refus_sortie()
    with pytest.raises(ErreurSpray, match="le bras ne sort pas : bras du spray : plateau"):
        banc.spray.sortir()
    assert table.ORDRE_SORTIR not in [code for code, _, _ in banc.carte.ordres]
    banc.refus_chariot = None
    banc.purge = True
    assert banc.spray.refus_sortie() == "purge en cours"
    banc.purge = False
    banc.porte = True
    assert banc.spray.refus_sortie() == "porte du spray ouverte"


def test_la_carte_refuse_sortir_sans_battement(banc):
    banc.pret()
    banc.attendre(5, observer=False)
    banc.spray._ordre(table.ORDRE_SORTIR, 600)
    banc.spray.lire()
    assert banc.spray.etat.suite_ordre == table.SUITE_REFUSE
    assert "battement" in banc.spray.etat.raison_du_refus


# ------------------------------------------------------------ un seau


def test_un_seau_avec_le_module_du_chef(tmp_path):
    banc = Banc(tmp_path, registre=True)
    chef = Chef(MACHINE, ReglagesChef(periode_s=0.05, alarme_pause_tout=True), horloge=banc.horloge)
    seau = ("S1293", "seau_b")
    module = module_spray(
        banc.spray, lambda: seau, zone_libre=lambda: True, micropore_escamote=lambda: True
    )
    chef.lancer(module)
    for _ in range(4000):
        banc.horloge.t += 0.05
        banc.spray.observer()
        chef.avancer()
        etat = chef.etat().modules[0]
        if etat.statut != "en_cours":
            break
    assert etat.statut == "fini", etat
    resultat = banc.spray.resultat
    assert resultat.issue == "faite"
    assert resultat.perdue_g == pytest.approx(SPRAY.dose.par_format_g["seau_b"], abs=0.2)
    assert banc.rotations == [SPRAY.dose.rotation_seau_deg]
    codes = [code for code, _, _ in banc.carte.ordres]
    assert codes.index(table.ORDRE_SORTIR) < codes.index(table.ORDRE_SPRAY)
    assert codes.index(table.ORDRE_SPRAY) < codes.index(table.ORDRE_RANGER)
    sortie = next(o for o in banc.carte.ordres if o[0] == table.ORDRE_SORTIR)
    assert sortie[1] == round(SPRAY.bras.angles["seau_b"] * 10)
    assert not banc.spray.bras_spray_sorti()
    mesures = banc.registre.lire("SELECT nom, valeur FROM mesures ORDER BY id")
    noms = {m["nom"]: m["valeur"] for m in mesures}
    assert noms["spray_emplacement"] == 1
    assert noms["spray_dose_demandee"] == SPRAY.dose.par_format_g["seau_b"]
    assert noms["spray_dose"] == pytest.approx(resultat.perdue_g)
    banc.materiel.fermer()


def test_flacon_presque_vide_puis_sans_spray(banc):
    banc.pret()
    plancher = VIDE + SPRAY.flacons.reserve_g
    banc.carte.grammes[0] = plancher + DOSE_A - 1
    banc.attendre(0.1)
    with pytest.raises(ErreurSpray, match="cartouche 1 presque vide"):
        banc.spray.preparer("S1", "seau_a")
    assert any("Cartouche 1 à changer" in m for m in banc.spray.messages)
    # Karulium choisit « Sans spray » à l'écran.
    banc.spray.continuer_sans_spray()
    assert banc.spray.preparer("S1", "seau_a") is None
    assert banc.spray.resultat.issue == "sans_spray"
    assert "presque vide" in banc.spray.resultat.texte


def test_cartouche_bientot_vide(banc):
    banc.pret()
    banc.carte.grammes[0] = VIDE + SPRAY.flacons.reserve_g + 3 * DOSE_A
    banc.attendre(0.1)
    assert banc.spray.preparer("S1", "seau_a") is not None
    assert any("bientôt vide" in m for m in banc.spray.messages)


def test_balance_muette(banc):
    banc.pret()
    banc.carte.balance_muette[0] = True
    banc.attendre(0.1)
    with pytest.raises(ErreurSpray, match="balance de l'emplacement 1 muette"):
        banc.spray.preparer("S1", "seau_a")


def test_dose_pas_atteinte(banc):
    banc.pret()
    banc.carte.debit_g_s = 0.2
    resultat = banc.un_seau()
    assert resultat.issue == "incomplete"
    assert resultat.perdue_g < DOSE_A
    assert resultat.duree_s == pytest.approx(SPRAY.dose.temps_max_pompage_s, abs=0.1)
    assert any("dose incomplète" in m for m in banc.spray.messages)


def test_dose_trop_forte(banc):
    banc.pret()
    banc.carte.debit_g_s = 100.0  # 5 g par pas de la fausse carte : la pompe dépasse
    resultat = banc.un_seau()
    assert resultat.issue == "trop_forte"
    assert resultat.perdue_g > DOSE_A + SPRAY.dose.tolerance_trop_forte_g


def test_porte_ouverte_pendant_un_spray(banc):
    banc.bras_dehors()
    banc.spray.pulveriser()
    banc.attendre(1.0)
    banc.porte = True
    banc.jusqu_a(banc.spray.pulverisation_finie)
    assert banc.spray.resultat.issue == "interrompue"
    assert "porte du spray ouverte" in banc.spray.resultat.raison
    assert table.ORDRE_ARRET in [code for code, _, _ in banc.carte.ordres]
    # Le bras reste « sorti » tant qu'il n'est pas vu rangé.
    assert banc.spray.bras_spray_sorti()
    banc.spray.ranger()
    banc.jusqu_a(banc.spray.bras_range)


def test_le_pi_se_tait_la_carte_s_arrete_seule(banc):
    banc.bras_dehors()
    banc.spray.pulveriser()
    banc.attendre(SPRAY.liaison.silence_max_s + 1, observer=False)
    banc.attendre(1.0, observer=False)
    banc.spray.lire()
    etat = banc.spray.etat
    assert etat.etat & table.ETAT_SILENCE_PI
    assert etat.dose.resultat == table.DOSE_INTERROMPUE
    assert etat.bras_range


def test_bras_pas_range_un_seul_nouvel_essai(banc):
    banc.bras_dehors()
    banc.carte.capteur_en_panne = True
    banc.spray.ranger()
    with pytest.raises(ErreurSpray, match="bras du spray pas rangé") as erreur:
        banc.jusqu_a(banc.spray.bras_range)
    assert erreur.value.quoi_faire == QUOI_FAIRE_BRAS
    rangers = [code for code, _, _ in banc.carte.ordres if code == table.ORDRE_RANGER]
    assert len(rangers) == 2
    assert banc.spray.bras_spray_sorti()


# ------------------------------------------------------------ cartouche, amorce


def test_amorce_apres_changement_de_cartouche(tmp_path):
    banc = Banc(tmp_path, registre=True)
    banc.pret()
    banc.carte.grammes[0] = 200.0
    banc.attendre(0.1)
    banc.carte.grammes[0] = 450.0  # nouvelle cartouche
    banc.attendre(0.1)
    assert banc.spray.a_confirmer == {1}
    with pytest.raises(ErreurSpray, match="pas encore confirmée"):
        banc.spray.preparer("S1", "seau_a")
    banc.spray.confirmer_cartouche(1)
    assert json.loads(banc.fichier.read_text())["amorces"] == [1]
    dose = banc.spray.preparer("S1", "seau_a")
    assert dose.amorce_g == SPRAY.dose.amorce_g
    assert dose.total_g == DOSE_A + SPRAY.dose.amorce_g
    banc.jusqu_a(banc.spray.agitation_faite)
    banc.spray.sortir()
    banc.jusqu_a(banc.spray.bras_sorti)
    banc.spray.pulveriser()
    banc.jusqu_a(banc.spray.pulverisation_finie)
    banc.spray.ranger()
    banc.jusqu_a(banc.spray.bras_range)
    banc.spray.noter()
    mesures = {m["nom"]: m["valeur"] for m in banc.registre.lire("SELECT * FROM mesures")}
    assert mesures["spray_amorce"] == SPRAY.dose.amorce_g
    assert mesures["spray_dose"] == pytest.approx(DOSE_A, abs=0.2)
    # Amorce faite : plus due, ni maintenant ni après un redémarrage du Pi.
    assert banc.spray.amorces == set()
    assert banc.nouveau_spray().amorces == set()
    assert banc.spray.preparer("S2", "seau_a").amorce_g == 0
    banc.materiel.fermer()


# ------------------------------------------------------------ nettoyage des tubes


def test_compteur_des_nettoyages(tmp_path):
    banc = Banc(tmp_path)
    chef = Chef(MACHINE, ReglagesChef(periode_s=0.05, alarme_pause_tout=True), horloge=banc.horloge)
    banc.spray.nettoyages = 21
    restants_alerte = SPRAY.nettoyage.alerte_nettoyages_restants
    for numero in range(2):
        banc.pret()
        module = module_nettoyage_tubes(
            banc.spray,
            lambda: True,
            lambda: True,
            lambda: "seau_a",
            nom=f"nettoyage_{numero}",
            zone_libre=lambda: True,
        )
        chef.lancer(module)
        for _ in range(4000):
            banc.horloge.t += 0.05
            banc.spray.observer()
            chef.avancer()
            etat = chef.etat().modules[-1]
            if etat.statut != "en_cours":
                break
        assert etat.statut == "fini", etat
    assert banc.spray.nettoyages == 23
    assert json.loads(banc.fichier.read_text())["nettoyages"] == 23
    assert banc.spray.nettoyages_restants() == 2 <= restants_alerte
    assert any("Alcool du nettoyage presque vide" in m for m in banc.spray.messages)
    assert table.ORDRE_NETTOYER in [code for code, _, _ in banc.carte.ordres]
    banc.spray.alcool_rempli()
    assert banc.nouveau_spray().nettoyages == 0
    banc.materiel.fermer()


# ------------------------------------------------------------ agitateurs, origine


def test_agitateurs_avant_la_dose_et_toutes_les_15_minutes(banc):
    banc.pret()
    banc.carte.ordres.clear()
    banc.spray.preparer("S1", "seau_a")
    agiter = [o for o in banc.carte.ordres if o[0] == table.ORDRE_AGITER]
    assert agiter[0][1] == SPRAY.agitateurs.vitesse_pct
    assert agiter[0][2] >= SPRAY.agitateurs.avant_dose_s
    assert not banc.spray.agitation_faite()
    banc.attendre(SPRAY.agitateurs.avant_dose_s)
    assert banc.spray.agitation_faite()
    banc.spray.noter()
    banc.carte.ordres.clear()
    banc.attendre(SPRAY.agitateurs.periode_s + 1)
    agiter = [o for o in banc.carte.ordres if o[0] == table.ORDRE_AGITER]
    assert agiter == [(table.ORDRE_AGITER, SPRAY.agitateurs.vitesse_pct, SPRAY.agitateurs.duree_s)]


def test_carte_redemarree(banc):
    banc.pret()
    banc.carte.redemarrer()
    banc.attendre(0.1)
    assert "prise d'origine" in banc.spray.refus_carte()
    assert any("redémarré" in m for m in banc.spray.messages)


# ------------------------------------------------------------ réglages, outil, simulateur


def test_reglages_du_spray_verifies(reglages):
    remplacer(reglages / "machine.yaml", "seau_b: 72.4", "seau_b: 120")
    assert "bras → angles → seau_b : 120° hors de la course" in erreur_de(reglages)


def test_reglages_du_spray_reserve_et_battement(reglages):
    remplacer(reglages / "machine.yaml", "reserve_g: 20", "reserve_g: 0")
    remplacer(reglages / "machine.yaml", "battement_s: 0.5", "battement_s: 1.5")
    erreur = erreur_de(reglages)
    assert "reserve_g" in erreur and "battement_s" in erreur


def test_reglages_du_spray_format_oublie(reglages):
    remplacer(
        reglages / "machine.yaml",
        "par_format_g: {seau_a: 11, seau_b: 5, seau_c: 10, seau_d: 10}",
        "par_format_g: {seau_a: 11, seau_b: 5, seau_c: 10}",
    )
    assert "dose → par_format_g : il manque le format « seau_d »" in erreur_de(reglages)


def test_reglages_temps_positifs(reglages):
    remplacer(reglages / "machine.yaml", "chasse_s: 4.5", "chasse_s: 0")
    assert "chasse_s" in erreur_de(reglages)


def test_balances_du_spray_dans_pesees(reglages):
    remplacer(reglages / "pesees.yaml", "  4: {zero_brut: 0, brut_par_kg: 400000}\n", "")
    assert "balances_spray" in erreur_de(reglages)


# ------------------------------------------------------------ programme de la carte (tâche 39 bis)


def test_reglages_copies_dans_le_programme_de_la_carte(tmp_path):
    entete_spray.ecrire(DOSSIER_PI / "reglages", LISTE_CHEMIN, tmp_path)
    texte = (tmp_path / "reglages_spray.h").read_text(encoding="utf-8")
    # L'adresse et la vitesse viennent de entrees-sorties.yaml (carte_spray, rs485_spray).
    assert "#define REGLAGE_ADRESSE 1\n" in texte
    assert "#define REGLAGE_VITESSE_BAUDS 115200" in texte
    assert "#define REGLAGE_EXEMPLE 1" in texte
    assert "#define REGLAGE_BROCHES_POMPES_PAS {4, 5, 6, 7}" in texte
    assert "#define REGLAGE_BROCHE_POMPES_SENS -1" in texte
    assert "#define REGLAGE_BROCHE_BRAS_RANGE 42" in texte
    # Le bras : 110° = 1100 dixièmes ; 200 pas × 16 micro-pas = 3200 pas par tour ; 90 °/s.
    assert "#define REGLAGE_BRAS_COURSE_DIXIEMES 1100" in texte
    assert "#define REGLAGE_BRAS_PAS_PAR_TOUR 3200" in texte
    assert "#define REGLAGE_BRAS_VITESSE_PAS_S 800" in texte
    assert "#define REGLAGE_BRAS_TEMPS_MAX_MS 3000" in texte
    # 1,2 A avec 0,11 Ω : IRUN 20 (≈ 1,16 A), maintien à 50 % : IHOLD 9.
    assert "#define REGLAGE_PILOTE_VSENSE 0" in texte
    assert "#define REGLAGE_PILOTE_IRUN 20" in texte
    assert "#define REGLAGE_PILOTE_IHOLD 9" in texte
    assert "#define REGLAGE_SILENCE_MAX_MS 2000" in texte
    assert "#define REGLAGE_CHASSE_MS 4500" in texte
    assert "#define REGLAGE_BALANCES_BRUT_PAR_KG {400000.0f, 400000.0f, 400000.0f, 400000.0f}" in (
        texte
    )
    assert "#define REGLAGE_BALANCES_INSTABLE_DIXIEMES 30" in texte
    # Rien n'est réécrit si rien ne change (le programme n'est pas refait pour rien).
    avant = (tmp_path / "reglages_spray.h").stat().st_mtime_ns
    entete_spray.ecrire(DOSSIER_PI / "reglages", LISTE_CHEMIN, tmp_path)
    assert (tmp_path / "reglages_spray.h").stat().st_mtime_ns == avant


def test_fabrication_de_la_carte_arretee_par_des_reglages_faux(reglages, tmp_path, capsys):
    remplacer(reglages / "machine.yaml", "      bras_sens: 14", "      bras_sens: 13")
    remplacer(reglages / "machine.yaml", "      rs485_rx: 18", "      rs485_rx: 19")
    sortie = tmp_path / "genere"
    assert entete_spray.main([str(reglages), str(LISTE_CHEMIN), str(sortie)]) == 1
    erreur = capsys.readouterr().err
    assert "la broche 13 est prise deux fois (bras_pas et bras_sens)" in erreur
    assert "rs485_rx (19) : broche de l'ESP32-S3 réservée (USB)" in erreur
    assert not (sortie / "reglages_spray.h").exists()
    assert entete_spray.main([]) == 2


def test_fabrication_de_la_carte_sans_carte_du_spray(entrees_sorties, tmp_path, capsys):
    remplacer(entrees_sorties, "    appareil: carte_spray\n", "")
    assert entete_spray.main([str(DOSSIER_PI / "reglages"), str(entrees_sorties), str(tmp_path)])
    assert "appareil: carte_spray" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("ancien", "nouveau", "message"),
    [
        ("pompes_pas: [4, 5, 6, 7]", "pompes_pas: [4, 5, 6, 4]", "prise deux fois"),
        ("hx711_sck: [38, 39, 40, 41]", "hx711_sck: [38, 39, 40, 30]", "(mémoire flash)"),
        ("      micro_pas: 16", "      micro_pas: 12", "le TMC2209 ne sait faire que"),
        ("      rapport: 1  ", "      rapport: 1.0001  ", "nombre entier de pas"),
        ("vitesse_pas_s: 1600", "vitesse_pas_s: 12000", "plus que ce que fait le générateur"),
        ("temps_max_s: 3  ", "temps_max_s: 1.5  ", "pas le temps de faire toute sa course"),
        ("resistance_mesure_ohm: 0.11", "resistance_mesure_ohm: 0.5", "ne peut pas le donner"),
        ("    chien_de_garde_ms: 1000", "    chien_de_garde_ms: 3000", "chien_de_garde_ms"),
        ("sans_mesure_ms: 100\n      instable", "sans_mesure_ms: 30\n      instable", "3 fois"),
    ],
)
def test_reglages_de_la_carte_verifies(reglages, ancien, nouveau, message):
    remplacer(reglages / "machine.yaml", ancien, nouveau)
    assert message in erreur_de(reglages)


def test_courant_du_pilote_du_bras():
    assert SPRAY.carte is not None
    moteur = SPRAY.carte.moteur_bras
    assert courants_tmc2209(1.2, moteur) == (0, 20, 9)
    # Petit courant : la petite échelle (VSENSE 1), plus fine. (CS + 1) / 32 × 0,18 / 0,13 / √2.
    vsense, irun, _ = courants_tmc2209(0.5, moteur)
    assert vsense == 1 and irun == 15
    assert (irun + 1) / 32 * 0.180 / 0.13 / 2**0.5 <= 0.5
    with pytest.raises(ValueError):
        courants_tmc2209(3.0, moteur)


def test_outil_avec_la_fausse_carte(capsys):
    assert outil(["--faux", "etat", "--secondes", "1"]) == 0
    assert "bras" in capsys.readouterr().out
    assert outil(["--faux", "sortir", "72.4"]) == 2
    assert "--etabli" in capsys.readouterr().err
    assert outil(["--faux", "origine"]) == 0
    assert "Fait." in capsys.readouterr().out
    assert outil(["--faux", "zero", "1"]) == 0
    assert "zero_brut" in capsys.readouterr().out
    # --angle : le bras sort d'abord, dans la même commande (une carte neuve n'a pas d'origine).
    assert outil(["--faux", "dose", "1", "10", "--angle", "64.3", "--etabli"]) == 1
    assert "prise d'origine du bras pas faite" in capsys.readouterr().out


def test_simulateur_a_une_fausse_carte_du_spray():
    with Simulateur(REGLAGES, LISTE) as simulateur:
        carte = simulateur.carte_spray()
        assert carte.horloge() == simulateur.temps
        assert carte.vitesse_bras_deg_s == SPRAY.bras.vitesse_deg_s


# ------------------------------------------------------------ page web et démarrage


def test_api_du_spray(tmp_path):
    banc = Banc(tmp_path, registre=True)
    services = Services(
        nouveau_chef(Horloge()), banc.registre, lambda *_: None, list, spray=banc.spray
    )
    client = TestClient(
        creer_app(services, reglages_api(), CLE),
        client=LOCAL,
        headers={"Authorization": f"Bearer {CLE}"},
    )
    banc.pret()
    banc.spray.a_confirmer.add(2)
    etat = client.get("/api/spray").json()
    assert etat["carte"] == "répond" and etat["a_confirmer"] == [2]
    assert client.post("/api/spray/cartouche?emplacement=2").json()["amorces"] == [2]
    assert client.post("/api/spray/cartouche").status_code == 422
    client.post("/api/spray/sans_spray")
    assert banc.spray.preparer("S1", "seau_a") is None
    assert client.post("/api/spray/voler").status_code == 404
    banc.materiel.fermer()


def test_branche_au_demarrage(tmp_path):
    banc = Banc(tmp_path, registre=True)
    chef = nouveau_chef(Horloge())
    spray = preparer_spray(REGLAGES, banc.materiel, tmp_path, banc.registre, chef)
    assert spray is not None and spray._fichier == tmp_path / "spray.json"
    assert preparer_spray(REGLAGES, None, tmp_path, banc.registre, chef) is None
    assert constats_spray(None)[0].niveau == "attention"
    assert constats_spray(spray)[0].sujet == "spray"
    assert chef.permission("spray_seau") is None
    banc.materiel.fermer()


# ------------------------------------------------------------ zone du bras (fil Spray, 07/11/2026)


def test_le_bras_ne_sort_et_ne_rentre_que_zone_libre(tmp_path):
    banc = Banc(tmp_path)
    chef = Chef(MACHINE, ReglagesChef(periode_s=0.05, alarme_pause_tout=True), horloge=banc.horloge)
    seau = ("S1294", "seau_a")
    zone = {"libre": False}
    module = module_spray(
        banc.spray,
        lambda: seau,
        zone_libre=lambda: zone["libre"],
        micropore_escamote=lambda: True,
    )
    chef.lancer(module)

    def tourner(fois, jusqu_a=lambda etat: False):
        for _ in range(fois):
            banc.horloge.t += 0.05
            banc.spray.observer()
            chef.avancer()
            etat = chef.etat().modules[0]
            if etat.statut != "en_cours" or jusqu_a(etat):
                break
        return etat

    def codes():
        return [code for code, _, _ in banc.carte.ordres]

    etat = tourner(4000, lambda etat: etat.etape == "sortir_le_bras")
    # Zone occupée (moins que le délai d'attente de l'entrée, spray_bras_max) : rien ne bouge.
    etat = tourner(100)
    assert etat.etape == "sortir_le_bras" and etat.statut == "en_cours"
    assert "zone du bras du spray libre" in etat.attend
    assert table.ORDRE_SORTIR not in codes()
    zone["libre"] = True
    etat = tourner(4000, lambda etat: etat.etape == "ranger_le_bras")
    assert table.ORDRE_SPRAY in codes()
    # Rentrée : la même zone (quelque chose y est entré pendant la dose).
    zone["libre"] = False
    etat = tourner(100)
    assert etat.etape == "ranger_le_bras" and table.ORDRE_RANGER not in codes()
    zone["libre"] = True
    etat = tourner(4000)
    assert etat.statut == "fini", etat
    assert table.ORDRE_RANGER in codes()


def test_zone_du_bras_reglee():
    zone = SPRAY.bras.zone
    # EXEMPLE tant que la Maquette ne l'a pas balayée.
    assert zone.exemple
    assert (zone.x, zone.y, zone.z_max) == ((0.66, 0.95), (-0.03, 0.24), 0.85)


def test_zone_du_bras_verifiee(reglages):
    remplacer(
        reglages / "machine.yaml",
        "zone: {exemple: true, x: [0.66, 0.95], y: [-0.03, 0.24], z_max: 0.85}",
        "zone: {exemple: true, x: [0.75, 0.95], y: [-0.03, 0.24], z_max: 0.85}",
    )
    assert "bras → zone : elle doit contenir l'axe du bras" in erreur_de(reglages)


def test_griffe_et_prehension_dans_la_zone():
    from vidange.griffe.regles import Pose as PoseGriffe
    from vidange.griffe.regles import ReglesGriffe
    from vidange.prehension.regles import Objet, ReglesPrehension
    from vidange.prehension.regles import Pose as PosePrehension
    from vidange.spray.zone import griffe_dans_la_zone, prehension_dans_la_zone

    zone = SPRAY.bras.zone
    griffe = ReglesGriffe(MACHINE)
    # Griffe au-dessus de la zone, axes à 0,95 (bas du godet à 0,747) : dedans ; en butée haute
    # (bas à 1,087) : dehors, même juste au-dessus.
    basse = PoseGriffe(x=0.80, y=0.10, z=0.95, a=0, b=0)
    assert griffe_dans_la_zone(zone, griffe, basse)
    assert not griffe_dans_la_zone(zone, griffe, basse.avec(z=1.29))
    # À côté en y : dehors fermé ; godet grand ouvert, la tête s'allonge le long du pont.
    assert not griffe_dans_la_zone(zone, griffe, basse.avec(y=0.36))
    assert griffe_dans_la_zone(zone, griffe, basse.avec(y=0.36, b=1.0))
    prehension = ReglesPrehension(MACHINE)
    assert MACHINE.prehension is not None
    seau = Objet.depuis("seau", MACHINE.prehension.objets["seau"])
    tete = PosePrehension(x=0.80, y=0.10, z=0.90, a=0)
    # Tête vide au-dessus de 0,85 : dehors ; plus bas : dedans.
    assert not prehension_dans_la_zone(zone, prehension, tete, None)
    assert prehension_dans_la_zone(zone, prehension, tete.avec(z=0.80), None)
    # Ce qu'elle tient compte : un seau pendu en butée haute (≈ 0,83), à y 0,35 (la tête seule
    # est loin de la zone, le seau de rayon 0,13 y entre).
    pendu = tete.avec(y=0.35, z=0.83)
    assert not prehension_dans_la_zone(zone, prehension, pendu, None)
    assert prehension_dans_la_zone(zone, prehension, pendu, seau)


def test_zone_du_bras_position_inconnue_pas_libre():
    from vidange.spray.zone import ZoneDuBras

    class BrasMuet:
        def position(self):
            raise RuntimeError("carte muette")

    class GriffeMuette:
        bras = BrasMuet()
        regles = None

    zone = ZoneDuBras(MACHINE, griffe=GriffeMuette())
    assert not zone.libre()
    assert "position de la griffe inconnue (carte muette)" in (zone.refus() or "")
    assert ZoneDuBras(MACHINE).libre()
