"""Entonnoir à bocaux (tâche 43) : réglages, état gardé après une coupure, règles de la Préhension
et du Stockage pour l'entonnoir tenu, gestes au simulateur (cas du § 5 de la fiche), lot complet,
outil."""

import json

import pytest

from vidange.chef import ErreurEtape
from vidange.entonnoir import HORS_MACHINE, INCONNU, Entonnoir
from vidange.entonnoir import etat as garde
from vidange.entonnoir.outil import main as outil
from vidange.entonnoir.simulation import ABSENT, TENU, entonnoir_du_simulateur
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.prehension import Contexte, Objet, Pose, ReglesPrehension
from vidange.reglages import charger_reglages
from vidange.simulateur import Simulateur
from vidange.simulateur.outil import main as simulateur
from vidange.stockage import places
from vidange.stockage.regles import ReglesStockage

from .conftest import DOSSIER_PI
from .test_reglages import erreur_de, remplacer

LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
ENTONNOIR = MACHINE.entonnoir
PREHENSION = MACHINE.prehension
assert ENTONNOIR is not None and PREHENSION is not None
REGLES = ReglesPrehension(MACHINE)
REGLES_STOCKAGE = ReglesStockage(MACHINE)
PLACES = places.places_bocaux(MACHINE)
OREILLE = ENTONNOIR.oreille_z
TRANSPORT = ENTONNOIR.face_transport_z


def tenu() -> Objet:
    """L'objet « entonnoir » tel que la Préhension le construit (axe 0,140 m en −x de la tête)."""
    return Objet.depuis(
        "entonnoir",
        PREHENSION.objets["entonnoir"],
        decalage_x_m=-ENTONNOIR.decalage_oreille_x_m,
    )


# ---------------------------------------------------------------- réglages


def test_reglages_de_l_entonnoir_du_depot():
    assert ENTONNOIR.exemple
    assert (ENTONNOIR.decalage_oreille_x_m, ENTONNOIR.decalage_oreille_y_m) == (0.140, 0.0)
    assert ENTONNOIR.levee_m == 0.060
    assert ENTONNOIR.face_transport_z == pytest.approx(0.846)
    assert (ENTONNOIR.col.precision_m, ENTONNOIR.col.capture_m) == (0.005, 0.0095)
    # Les seuils du vide de la prise (−55 kPa) et de la perte (−40 kPa) sont ceux de la Préhension.
    assert (PREHENSION.vide.prise_kpa, PREHENSION.vide.perte_kpa) == (-55, -40)
    assert ENTONNOIR.vide.lache_kpa == -5
    # Aucun signal propre à l'entonnoir : celui de la liste est sans ligne.
    assert not [nom for nom, signal in LISTE.signaux.items() if signal.module == "entonnoir"]


def test_reglages_de_l_entonnoir_verifies(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "  pointe_z: 0.627", "  pointe_z: 0.90")
    remplacer(
        machine, "precision_m: 0.005, capture_m: 0.0095", "precision_m: 0.02, capture_m: 0.0095"
    )
    message = erreur_de(reglages)
    assert "pointe_z doit être plus bas que oreille_z" in message
    assert "precision_m" in message and "plus grande que capture_m" in message


def test_garde_sur_les_cols_voisins_verifiee(reglages):
    remplacer(reglages / "machine.yaml", "  levee_m: 0.060", "  levee_m: 0.040")
    assert "en transport la pointe n'est qu'à 24 mm" in erreur_de(reglages)


def test_vide_et_objet_de_l_entonnoir_verifies(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "lache_kpa: -5", "lache_kpa: -45")
    remplacer(
        machine,
        "    entonnoir: {rayon_m: 0.09, dessus_m: 0, dessous_m: 0.159, poids_n: 8.8, "
        "tolerance_n: 4}\n",
        "",
    )
    message = erreur_de(reglages)
    assert "lache_kpa (-45) doit être au-dessus de prehension → vide → perte_kpa (-40)" in message
    assert "il manque l'objet « entonnoir » dans prehension → objets" in message


def test_la_ventouse_doit_atteindre_chaque_bocal(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "decalage_oreille_x_m: 0.140", "decalage_oreille_x_m: 0.5")
    message = erreur_de(reglages)
    assert "la ventouse n'atteint pas l'oreille du bocal" in message


def test_hauteurs_de_l_entonnoir_dans_la_course_verifiees(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "  oreille_z: 0.786", "  oreille_z: 1.05")
    message = erreur_de(reglages)
    assert "face de transport 1.11 m (oreille_z + levee_m) au-dessus de la butée haute" in message


# ---------------------------------------------------------------- règles de la Préhension


def test_la_tete_ne_tourne_jamais_en_tenant_l_entonnoir():
    depart = Pose(x=1.6, y=0.5, z=TRANSPORT, a=0.0)
    refus = REGLES.refus_mouvement(depart, depart.avec(a=30), Contexte(objet=tenu()))
    assert refus is not None and "ne tourne jamais en tenant l'entonnoir" in refus
    # Tête vide : la rotation reste permise.
    assert (
        REGLES.refus_mouvement(depart.avec(z=1.10), depart.avec(z=1.10, a=30), Contexte()) is None
    )


def test_l_entonnoir_roule_a_six_centimetres_de_sa_pose():
    objet = tenu()
    assert REGLES.hauteur_trajet(objet, 0.5) == pytest.approx(0.846)
    assert REGLES.hauteur_trajet(None, 0.5) == pytest.approx(1.10)
    # Le pont roule à cette hauteur (exception voulue par la fiche), pas plus bas.
    a = Pose(x=1.6, y=0.5, z=0.846, a=0)
    assert REGLES.refus_mouvement(a, a.avec(x=1.8), Contexte(objet=objet)) is None
    bas = a.avec(z=0.80)
    assert "tête basse refusé" in REGLES.refus_mouvement(
        bas, bas.avec(x=1.8), Contexte(objet=objet)
    )


def test_objet_entonnoir_de_la_preh():
    objet = tenu()
    assert (objet.decalage_x_m, objet.rayon_m) == (-0.140, 0.09)


# ---------------------------------------------------------------- règles du Stockage


def refus_stockage(depart, arrivee, objet):
    return REGLES_STOCKAGE.refus_prehension(depart, arrivee, objet, [], True)


def test_axe_de_l_entonnoir_a_1_205_pres_de_la_camera_du_bocal():
    # Le premier bocal est à 1,2075 : tête à 1,3475 (axe de l'entonnoir à 1,2075 ≥ 1,205).
    objet = tenu()
    sur_le_premier = Pose(x=1.3475, y=0.06, z=TRANSPORT, a=0)
    assert refus_stockage(sur_le_premier, sur_le_premier.avec(y=0.30), objet) is None
    # Tête à 1,33 : axe de l'entonnoir à 1,19, trop près du boîtier de la caméra du bocal.
    trop_pres = Pose(x=1.33, y=0.06, z=TRANSPORT, a=0)
    assert "caméra du bocal" in refus_stockage(trop_pres, trop_pres.avec(y=0.30), objet)


def test_l_entonnoir_ne_passe_jamais_au_dessus_des_boites_a_capsules():
    # Boîte à (2,95 ; 0,53), Ø 0,12 : la pointe en transport (0,687) est sous 0,76.
    objet = tenu()
    depart = Pose(x=2.70, y=0.53, z=TRANSPORT, a=0)
    refus = refus_stockage(depart, depart.avec(x=2.99), objet)
    assert refus is not None and "boîte à capsules" in refus
    # La tête seule (face à 0,846) passe : c'est la pointe qui ne passe pas.
    assert refus_stockage(depart, depart.avec(x=2.99), None) is None
    # Le dernier bocal de la rangée (axe 2,6375, à 0,06 de y) est loin des boîtes.
    loin = Pose(x=2.7775, y=0.06, z=TRANSPORT, a=0)
    assert refus_stockage(loin, loin.avec(y=0.20), objet) is None


# ---------------------------------------------------------------- état gardé après une coupure


def faire(fichier=None, photos=None, **options):
    photos = photos if photos is not None else []
    return Entonnoir(MACHINE, fichier, photo=photos.append, **options), photos


def test_premiere_mise_en_route_hors_machine(tmp_path):
    entonnoir, photos = faire(tmp_path / "entonnoir.json")
    assert (entonnoir.place, entonnoir.tenu) == (HORS_MACHINE, False)
    assert not entonnoir.sur_le_plateau()
    assert photos == []


def test_la_place_est_gardee_apres_une_coupure(tmp_path):
    fichier = tmp_path / "donnees" / "entonnoir.json"
    entonnoir, _ = faire(fichier)
    entonnoir.demarrer_lot(["bocal_2_3", "bocal_2_4"])
    entonnoir.demander_la_pose()
    assert json.loads(fichier.read_text(encoding="utf-8")) == {"place": "bocal_2_3", "tenu": False}
    assert not list(fichier.parent.glob("*.tmp"))
    # Coupure de courant, redémarrage : il est gardé, et la caméra photographie le plafond.
    apres, photos = faire(fichier)
    assert (apres.place, apres.tenu) == ("bocal_2_3", False)
    assert apres.sur_le_plateau()
    assert photos == ["entonnoir : redémarrage"]


def test_coupure_pendant_qu_il_etait_tenu_place_inconnue(tmp_path):
    fichier = tmp_path / "entonnoir.json"
    garde.ecrire(fichier, garde.EtatGarde("bocal_1_1", True))
    entonnoir, photos = faire(fichier)
    assert (entonnoir.place, entonnoir.tenu) == (INCONNU, False)
    assert photos == ["entonnoir : redémarrage"]
    # L'état est réécrit : une deuxième coupure ne le « retrouve » pas.
    assert json.loads(fichier.read_text(encoding="utf-8")) == {"place": INCONNU, "tenu": False}
    # Inconnu = sur le plateau par prudence, et la griffe ne verse pas.
    assert entonnoir.sur_le_plateau()
    assert "inconnue" not in (entonnoir.refus_versement("bocal_1_1") or "")
    assert entonnoir.refus_versement("bocal_1_1") is not None


def test_fichier_illisible_place_inconnue(tmp_path):
    fichier = tmp_path / "entonnoir.json"
    fichier.write_text("{pas du json", encoding="utf-8")
    entonnoir, _ = faire(fichier)
    assert entonnoir.place == INCONNU
    fichier.write_text('{"place": 3, "tenu": "oui"}', encoding="utf-8")
    assert faire(fichier)[0].place == INCONNU


def test_hors_machine_est_garde(tmp_path):
    fichier = tmp_path / "entonnoir.json"
    entonnoir, _ = faire(fichier)
    entonnoir.demarrer_lot(["bocal_0_0"])
    entonnoir.demander_la_pose()
    entonnoir.enlever_a_la_main()
    apres, photos = faire(fichier)
    assert apres.place == HORS_MACHINE and photos == []


def test_apres_une_coupure_la_tete_ne_tient_plus_l_entonnoir():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        scenario = entonnoir_du_simulateur(simulation)
        prehension = scenario.prehension
        prehension.objet = prehension.objet_par_nom("entonnoir")
        prehension.poids_porte_n = 8.8
        scenario.entonnoir.apres_coupure(prehension)
        assert prehension.objet is None and prehension.poids_porte_n == 0.0


# ---------------------------------------------------------------- versement et photo du fond


def test_la_griffe_ne_verse_que_dans_le_bocal_ou_est_l_entonnoir():
    entonnoir, _ = faire()
    entonnoir.demarrer_lot(["bocal_0_0", "bocal_0_1"])
    # Pas encore posé à la main : aucun versement dans aucun bocal.
    assert "hors_machine" in entonnoir.refus_versement("bocal_0_0")
    entonnoir.demander_la_pose()
    assert entonnoir.refus_versement("bocal_0_0") is None
    assert "l'entonnoir est sur le bocal rangée 1, place 1" in entonnoir.refus_versement(
        "bocal_0_1"
    )
    entonnoir.noter_verse("bocal_0_0")
    assert "déjà reçu sa dose" in entonnoir.refus_versement("bocal_0_0")
    entonnoir.tenu = True
    assert "tient l'entonnoir" in entonnoir.refus_versement("bocal_0_0")


def test_pas_de_photo_du_fond_tant_que_l_entonnoir_est_sur_le_plateau():
    entonnoir, _ = faire()
    entonnoir.demarrer_lot(["bocal_0_0"])
    assert REGLES_STOCKAGE.refus_photo_du_fond(0.71, entonnoir.sur_le_plateau()) is None
    entonnoir.demander_la_pose()
    assert "l'entonnoir est sur le plateau" in REGLES_STOCKAGE.refus_photo_du_fond(
        0.71, entonnoir.sur_le_plateau()
    )
    entonnoir.enlever_a_la_main()
    assert REGLES_STOCKAGE.refus_photo_du_fond(0.71, entonnoir.sur_le_plateau()) is None


# ---------------------------------------------------------------- le lot


def test_ordre_de_remplissage_voisins_dans_la_meme_rangee_en_serpentin():
    entonnoir, _ = faire()
    ordre = entonnoir.ordre_de_remplissage(
        ["bocal_1_0", "bocal_0_2", "bocal_0_0", "bocal_1_1", "bocal_0_1", "bocal_2_5", "bocal_2_4"]
    )
    assert ordre == [
        "bocal_0_0",
        "bocal_0_1",
        "bocal_0_2",
        "bocal_1_1",
        "bocal_1_0",
        "bocal_2_4",
        "bocal_2_5",
    ]


def test_lot_refuse_les_places_interdites():
    entonnoir, _ = faire()
    coin = places.coin_inspection(MACHINE)[0][0]
    with pytest.raises(ValueError, match="l'entonnoir n'y va jamais"):
        entonnoir.demarrer_lot(["bocal_0_0", coin])
    with pytest.raises(ValueError, match="n'est pas une place du quinconce"):
        entonnoir.demarrer_lot(["bocal_9_9"])
    with pytest.raises(ValueError, match="cité deux fois"):
        entonnoir.demarrer_lot(["bocal_0_0", "bocal_0_0"])
    with pytest.raises(ValueError, match="aucun bocal"):
        entonnoir.demarrer_lot([])


def test_col_pas_trouve_le_bocal_est_suspect_et_on_passe_au_suivant():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        scenario = entonnoir_du_simulateur(simulation)
        entonnoir = scenario.entonnoir
        scenario.monde.cols_introuvables = {"bocal_0_1"}
        assert entonnoir.prochain == "bocal_0_0"
        assert entonnoir.passer_au_suivant()
        assert entonnoir.prochain == "bocal_0_2"
        assert entonnoir.suspects == ["bocal_0_1"] == scenario.suspects
        assert entonnoir.centre == PLACES["bocal_0_2"]
        assert entonnoir.passer_au_suivant()  # bocal_1_0
        assert not entonnoir.passer_au_suivant()
        assert entonnoir.prochain is None
        assert "Enlevez l'entonnoir à la main" in entonnoir.demande()


# ---------------------------------------------------------------- gestes au simulateur


def jouer(simulation, prehension, fabrique):
    prehension.lancer(fabrique)
    for _ in range(4000):
        if prehension.geste_fini():
            return
        simulation.temps += 0.25
    raise AssertionError("geste pas fini")


class Banc:
    """Une préhension simulée, un entonnoir posé à la main sur le premier bocal du lot."""

    def __init__(self, simulation, fichier=None, pose=True):
        self.simulation = simulation
        self.photos: list[str] = []
        self.scenario = entonnoir_du_simulateur(simulation, fichier, photo=self.photos.append)
        self.entonnoir = self.scenario.entonnoir
        self.prehension = self.scenario.prehension
        self.monde = self.scenario.monde
        self.tete = self.prehension.tete
        if pose:
            self.entonnoir.demander_la_pose()  # Go de Karulium : sur bocal_0_0

    def jouer(self, fabrique):
        jouer(self.simulation, self.prehension, fabrique)

    def prendre(self):
        self.jouer(lambda: self.entonnoir.geste_prendre(self.prehension))

    def poser(self, bocal="bocal_0_1", centre="col"):
        if centre == "col":
            centre = self.monde.centre_du_col(bocal)
        self.jouer(lambda: self.entonnoir.geste_poser(self.prehension, bocal, centre))

    def positions(self):
        return self.simulation.etat_axes.positions


def test_prise_de_l_entonnoir_par_l_oreille():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.prendre()
        entonnoir, prehension = banc.entonnoir, banc.prehension
        # Électroaimants éteints d'abord (l'inox 316L ne colle pas), puis la vanne du vide.
        assert banc.tete.sorties[0] == "aimants coupés"
        assert banc.tete.sorties.count("vanne ouverte") == 1
        # Tête sur l'oreille : x bocal + 0,140 ; pont à x bocal + 0,140 − 0,129.
        x, y = PLACES["bocal_0_0"]
        assert prehension.pose.x == pytest.approx(x + 0.140)
        assert prehension.pose.y == pytest.approx(y)
        assert banc.positions()["pont_x"] == pytest.approx(x + 0.140 - 0.129)
        # Levée de transport de 0,060 au-dessus de la pose.
        assert prehension.pose.z == pytest.approx(OREILLE + 0.060)
        # Il est tenu : noté au bocal d'origine, tenu, et la tête sait ce qu'elle porte.
        assert (entonnoir.place, entonnoir.tenu) == ("bocal_0_0", True)
        assert prehension.objet is not None and prehension.objet.sorte == "entonnoir"
        assert prehension.poids_porte_n == pytest.approx(8.8)
        assert banc.monde.ou == TENU
        assert prehension.tient_un_objet()
        assert banc.photos == []


def test_transport_et_pose_sur_le_bocal_suivant():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.prendre()
        banc.poser("bocal_0_1")
        entonnoir, prehension = banc.entonnoir, banc.prehension
        assert (entonnoir.place, entonnoir.tenu) == ("bocal_0_1", False)
        assert banc.monde.ou == "bocal_0_1"
        assert prehension.objet is None and prehension.poids_porte_n == 0.0
        # Tête remontée en haut, vanne fermée : lâché.
        assert prehension.pose.z == pytest.approx(1.10)
        assert banc.tete.sorties[-1] == "vanne fermée"
        # Accélération réduite pendant le transport, rendue ensuite.
        assert banc.tete.accelerations[:3] == [False, True, False]
        assert entonnoir.pose_ratee is None
        # La griffe peut verser dans ce bocal, et pas dans l'ancien.
        assert entonnoir.refus_versement("bocal_0_1") is None
        assert entonnoir.refus_versement("bocal_0_0") is not None


def test_entonnoir_absent_au_contact(caplog):
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.monde.ou = ABSENT
        with pytest.raises(ErreurEtape, match="entonnoir absent sur le bocal rangée 1, place 1"):
            banc.prendre()
        # Tête en haut, photo, place inconnue, plus de versement, pas de vanne ouverte.
        assert banc.positions()["prehension_z"] == pytest.approx(1.10)
        assert banc.photos == ["entonnoir absent"]
        assert banc.entonnoir.place == INCONNU
        assert banc.entonnoir.refus_versement("bocal_0_0") is not None
        assert "vanne ouverte" not in banc.tete.sorties
        assert "Posez l'entonnoir sur le bocal rangée 1, place 1" in banc.entonnoir.messages[-1]


def test_entonnoir_mal_pose_contact_trop_haut():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.monde.ecart_oreille_m = 0.012  # plus de 10 mm au-dessus de l'attendu
        with pytest.raises(ErreurEtape, match="entonnoir mal posé sur le bocal rangée 1"):
            banc.prendre()
        assert banc.photos == ["entonnoir mal posé"]
        # Il reste noté sur son bocal : Karulium le remet droit, puis Go.
        assert banc.entonnoir.place == "bocal_0_0"
        assert "vanne ouverte" not in banc.tete.sorties
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.monde.ecart_oreille_m = 0.03  # contact dès la descente rapide
        with pytest.raises(ErreurEtape, match="mal posé"):
            banc.prendre()


def test_contact_un_peu_haut_mais_acceptable():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.monde.ecart_oreille_m = 0.008  # moins de 10 mm : accepté
        banc.prendre()
        assert banc.entonnoir.tenu


def test_vide_pas_atteint_un_seul_nouvel_essai():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.tete.vides_refuses = 1
        banc.prendre()
        assert banc.entonnoir.tenu
        # Vanne ouverte, souffle, remonté de 5 mm, redescendu, vanne rouverte.
        assert banc.tete.sorties.count("vanne ouverte") == 2
        assert banc.tete.sorties.count("vanne fermée") == 1
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.tete.vides_refuses = 2
        with pytest.raises(ErreurEtape, match="la ventouse ne prend pas l'entonnoir"):
            banc.prendre()
        assert banc.tete.sorties.count("vanne ouverte") == 2
        assert banc.tete.sorties[-1] == "vanne fermée"
        # Il n'a pas bougé de son bocal ; la tête est remontée.
        assert banc.entonnoir.place == "bocal_0_0" and not banc.entonnoir.tenu
        assert banc.monde.ou == "bocal_0_0"
        assert banc.positions()["prehension_z"] == pytest.approx(1.10)


def test_vide_perdu_en_transport():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.prendre()
        banc.tete.pertes_de_vide = 1
        with pytest.raises(ErreurEtape, match="vide perdu en tenant l'entonnoir"):
            banc.poser("bocal_0_1")
        entonnoir, prehension = banc.entonnoir, banc.prehension
        # Arrêt, tête en haut, photo du plafond, alerte ; plus de versement.
        assert banc.positions()["prehension_z"] == pytest.approx(1.10)
        assert banc.photos == ["vide perdu en tenant l'entonnoir"]
        assert (entonnoir.place, entonnoir.tenu) == (INCONNU, False)
        assert prehension.objet is None and not prehension.tient_un_objet()
        assert entonnoir.refus_versement("bocal_0_1") is not None
        assert banc.tete.sorties[-1] == "vanne fermée"
        assert banc.monde.ou == ABSENT


def test_vide_perdu_pendant_la_levee():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.tete.pertes_de_vide = 1
        with pytest.raises(ErreurEtape, match="vide perdu"):
            banc.prendre()
        assert banc.entonnoir.place == INCONNU
        assert banc.photos == ["vide perdu en tenant l'entonnoir"]


def test_vide_surveille_pendant_le_trajet_seulement_avec_l_entonnoir():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.prendre()
        pas = []
        executer = banc.tete.executer
        banc.tete.executer = lambda p, c, w: (pas.append(p), executer(p, c, w))[1]  # type: ignore[method-assign]
        banc.poser("bocal_0_1")
        trajet = next(p for p in pas if p.texte == "trajet de l'entonnoir")
        assert trajet.vide_perte_kpa == -40 and trajet.choc


def test_pose_pas_entree_dans_le_col_un_seul_nouvel_essai():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.prendre()
        banc.monde.poses_sur_le_bord = 1  # la pointe est sur le bord du verre une fois
        banc.poser("bocal_0_1")
        assert banc.entonnoir.place == "bocal_0_1" and banc.entonnoir.pose_ratee is None
        assert banc.monde.ou == "bocal_0_1"
        assert banc.entonnoir.suspects == []


def test_pose_ratee_deux_fois_il_retourne_sur_son_bocal_et_le_bocal_est_suspect():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.prendre()
        banc.monde.poses_sur_le_bord = 2
        banc.poser("bocal_0_1")
        entonnoir = banc.entonnoir
        # Remis sur le bocal d'où il vient ; le bocal visé est suspect ; le lot continue.
        assert (entonnoir.place, entonnoir.tenu) == ("bocal_0_0", False)
        assert banc.monde.ou == "bocal_0_0"
        assert entonnoir.pose_ratee == "bocal_0_1"
        assert entonnoir.suspects == ["bocal_0_1"] == banc.scenario.suspects
        assert banc.prehension.objet is None
        assert banc.positions()["prehension_z"] == pytest.approx(1.10)


def test_camera_qui_se_trompe_de_plus_de_9_mm_la_pointe_reste_sur_le_verre():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.prendre()
        banc.monde.ecart_col_m = 0.02  # le cône ne capte que 9,5 mm
        banc.poser("bocal_0_1")
        assert banc.entonnoir.pose_ratee == "bocal_0_1"
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.prendre()
        banc.monde.ecart_col_m = 0.008  # moins de 9,5 mm : le cône se centre seul
        banc.poser("bocal_0_1")
        assert banc.entonnoir.place == "bocal_0_1"


def test_pose_ratee_aussi_sur_le_bocal_d_origine():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.prendre()
        banc.monde.poses_sur_le_bord = 3
        with pytest.raises(ErreurEtape, match="impossible de le remettre sur le bocal rangée 1"):
            banc.poser("bocal_0_1")
        # La tête le tient toujours : le Go refait la pose.
        assert banc.entonnoir.tenu and banc.prehension.objet is not None


def test_entonnoir_colle_a_la_ventouse_au_lacher():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.prendre()
        banc.tete.vides_colles = 1
        banc.poser("bocal_0_1")
        # Un nouveau souffle de 0,5 s a suffi.
        assert banc.entonnoir.place == "bocal_0_1"
        assert banc.tete.sorties.count("vanne fermée") == 2
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.prendre()
        banc.tete.vides_colles = 2
        with pytest.raises(ErreurEtape, match="resté collé à la ventouse"):
            banc.poser("bocal_0_1")
        assert banc.entonnoir.tenu  # pas lâché : le Go refait le geste


def test_pas_de_pose_sur_le_coin_des_suspects():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.prendre()
        coin = places.coin_inspection(MACHINE)[0][0]
        with pytest.raises(ErreurEtape, match="coin des suspects"):
            banc.poser(coin, centre=None)


def test_la_tete_ne_pivote_pas_en_tenant_l_entonnoir():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        banc.prendre()
        pose = banc.prehension.pose
        refus = banc.prehension.refus_manuel(pose.avec(a=45))
        assert refus is not None and "ne tourne jamais en tenant l'entonnoir" in refus
        assert banc.positions()["prehension_a"] == 0


def test_prendre_sans_place_connue_ou_deja_tenu_refuse():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation, pose=False)
        with pytest.raises(ErreurEtape, match="noté sur « hors_machine »"):
            banc.prendre()
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        banc = Banc(simulation)
        with pytest.raises(ErreurEtape, match="ne tient pas l'entonnoir à poser"):
            banc.poser("bocal_0_1")
        banc.prendre()
        with pytest.raises(ErreurEtape, match="tient déjà"):
            banc.prendre()


# ---------------------------------------------------------------- le module, au simulateur


def jouer_module(modifier=lambda scenario: None, fichier=None):
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        scenario = entonnoir_du_simulateur(simulation, fichier)
        modifier(scenario)
        planning = simulation.jouer([scenario.module])
        return planning, scenario, simulation


def etapes(planning):
    return [ligne.etape for ligne in planning.lignes]


def test_un_lot_complet(tmp_path, caplog):
    caplog.set_level("INFO", logger="vidange.entonnoir")
    fichier = tmp_path / "donnees" / "entonnoir.json"
    planning, scenario, _ = jouer_module(fichier=fichier)
    assert planning.fini, planning.probleme
    # Le Pi choisit l'ordre : rangée 0 de gauche à droite, puis la rangée 1.
    assert scenario.monde.versements == ["bocal_0_0", "bocal_0_1", "bocal_0_2", "bocal_1_0"]
    assert etapes(planning)[0] == "demander_la_pose"
    assert etapes(planning)[-1] == "enlever_a_la_main"
    assert etapes(planning).count("prendre_l_entonnoir") == 3
    assert etapes(planning).count("poser_sur_le_bocal") == 3
    # Rien n'est versé avant le Go de pose, ni après l'enlèvement.
    assert etapes(planning).index("demander_la_pose") < etapes(planning).index("verser")
    # Fin de lot : Karulium l'enlève à la main (Go) ; hors machine, gardé après une coupure.
    assert scenario.entonnoir.place == HORS_MACHINE
    assert scenario.monde.ou == HORS_MACHINE
    assert json.loads(fichier.read_text(encoding="utf-8")) == {"place": HORS_MACHINE, "tenu": False}
    assert not scenario.entonnoir.sur_le_plateau()
    assert scenario.suspects == []
    # La prise est toujours tenue, puis posée : trois « (tenu) » dans le journal.
    assert caplog.text.count("(tenu)") == 3
    assert "entonnoir_place = bocal_1_0" in caplog.text


def test_un_lot_avec_un_col_introuvable_saute_ce_bocal():
    def modifier(scenario):
        scenario.monde.cols_introuvables = {"bocal_0_1"}

    planning, scenario, _ = jouer_module(modifier)
    assert planning.fini, planning.probleme
    assert scenario.monde.versements == ["bocal_0_0", "bocal_0_2", "bocal_1_0"]
    assert scenario.suspects == ["bocal_0_1"]


def test_un_lot_avec_une_pose_ratee_continue_avec_le_suivant():
    def modifier(scenario):
        scenario.monde.poses_sur_le_bord = 2  # la 1re pose (bocal_0_1) rate deux fois

    planning, scenario, _ = jouer_module(modifier)
    assert planning.fini, planning.probleme
    assert scenario.suspects == ["bocal_0_1"]
    assert scenario.monde.versements == ["bocal_0_0", "bocal_0_2", "bocal_1_0"]
    # Pas de versement au retour sur le bocal d'origine (déjà rempli) : "verser" saute.
    assert etapes(planning).count("verser") == 3


def test_caméra_qui_ne_voit_pas_l_entonnoir_au_depart():
    def modifier(scenario):
        scenario.monde.invisible = True

    planning, scenario, _ = jouer_module(modifier)
    assert not planning.fini
    assert etapes(planning)[-1] == "controler_la_camera"
    assert "entonnoir introuvable sur le bocal rangée 1, place 1" in planning.probleme
    assert scenario.entonnoir.place == INCONNU
    assert scenario.monde.versements == []


def test_entonnoir_absent_arrete_le_lot_au_simulateur():
    def modifier(scenario):
        # Karulium a posé l'entonnoir (Go), puis il disparaît avant la prise.
        scenario.entonnoir._main = lambda bocal: setattr(scenario.monde, "ou", ABSENT)

    planning, scenario, _ = jouer_module(modifier)
    assert not planning.fini
    # La caméra ne le voit pas non plus : alarme dès le contrôle de la caméra.
    assert etapes(planning)[-1] == "controler_la_camera"


def test_vide_perdu_arrete_le_lot_et_plus_de_versement():
    def modifier(scenario):
        # Le vide part dès la première levée.
        scenario.prehension.tete.pertes_de_vide = 1

    planning, scenario, _ = jouer_module(modifier)
    assert not planning.fini
    assert etapes(planning)[-1] == "prendre_l_entonnoir"
    assert "vide perdu" in planning.probleme
    assert scenario.entonnoir.place == INCONNU
    # Un seul bocal rempli avant l'alarme (le premier), puis plus rien avant l'avis de Karulium.
    assert scenario.monde.versements == ["bocal_0_0"]


def test_apres_une_perte_le_module_revient_au_geste_1():
    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        scenario = entonnoir_du_simulateur(simulation)
        module, entonnoir = scenario.module, scenario.entonnoir
        etapes_par_nom = {etape.nom: etape for etape in module.etapes}
        entonnoir.demander_la_pose()
        assert etapes_par_nom["controler_la_camera"].ensuite() is None
        assert etapes_par_nom["prendre_l_entonnoir"].ensuite() is None
        assert etapes_par_nom["poser_sur_le_bocal"].ensuite() == "verser"
        # Place inconnue : chacune de ces étapes renvoie au geste 1 (demander la pose).
        entonnoir.declarer_inconnu("essai")
        for nom in ("controler_la_camera", "prendre_l_entonnoir", "poser_sur_le_bocal"):
            assert etapes_par_nom[nom].ensuite() == "demander_la_pose", nom
        # Rien ne bouge : l'action est sans effet quand la place est inconnue.
        etapes_par_nom["prendre_l_entonnoir"].action()
        etapes_par_nom["poser_sur_le_bocal"].action()
        assert scenario.prehension.geste_fini()


def test_air_attendu_avant_la_prise():
    from vidange.chef import Condition
    from vidange.entonnoir import module_entonnoir

    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        scenario = entonnoir_du_simulateur(simulation)
        air = Condition("air en pression", lambda: True)
        module = module_entonnoir(scenario.entonnoir, scenario.prehension, ["bocal_0_0"], air=air)
        prendre = next(e for e in module.etapes if e.nom == "prendre_l_entonnoir")
        poser = next(e for e in module.etapes if e.nom == "poser_sur_le_bocal")
        assert air in prendre.entree and air not in poser.entree


def test_etapes_de_photo_du_portique_avant_chaque_lecture_de_la_camera():
    from vidange.chef import Etape
    from vidange.entonnoir import module_entonnoir

    with Simulateur(REGLAGES, LISTE, "entonnoir") as simulation:
        scenario = entonnoir_du_simulateur(simulation)
        photo = (Etape("portique_outils_en_haut", "x"), Etape("portique_arret_avant_photo", "x"))
        module = module_entonnoir(
            scenario.entonnoir, scenario.prehension, ["bocal_0_0", "bocal_0_1"], photo=photo
        )
        noms = [etape.nom for etape in module.etapes]
        assert noms == [
            "demander_la_pose",
            "portique_outils_en_haut",
            "portique_arret_avant_photo",
            "controler_la_camera",
            "verser",
            "portique_outils_en_haut_col",
            "portique_arret_avant_photo_col",
            "lire_le_col_suivant",
            "prendre_l_entonnoir",
            "poser_sur_le_bocal",
            "enlever_a_la_main",
        ]
        etapes_par_nom = {etape.nom: etape for etape in module.etapes}
        scenario.entonnoir.demander_la_pose()
        scenario.entonnoir.pose_ratee = "bocal_0_1"
        # Une pose ratée renvoie à la lecture du col suivant, photo comprise.
        assert etapes_par_nom["poser_sur_le_bocal"].ensuite() == "portique_outils_en_haut_col"


# ---------------------------------------------------------------- outil et simulateur


def test_simulateur_en_ligne_de_commande(capsys):
    assert simulateur(["entonnoir"]) == 0
    sortie = capsys.readouterr().out
    assert "enlever_a_la_main" in sortie and "prendre_l_entonnoir" in sortie


def test_outil_places_et_hauteurs(capsys):
    assert outil(["places"]) == 0
    sortie = capsys.readouterr().out
    assert "bocal_0_0" in sortie and "tête x 1,3475 y 0,06, pont x 1,2185" in sortie
    assert outil(["places", "bocal_1_12"]) == 0
    assert "tête x 2,7225" in capsys.readouterr().out
    assert outil(["hauteurs"]) == 0
    sortie = capsys.readouterr().out
    assert "face à 0,846 m (levée 0,06)" in sortie and "garde sur les cols voisins 0,044" in sortie
    assert outil(["places", "bocal_9_9"]) == 2


def test_outil_etat_et_noter(tmp_path, capsys):
    donnees = str(tmp_path)
    assert outil(["etat", "--donnees", donnees]) == 0
    assert "absent : hors machine" in capsys.readouterr().out
    assert outil(["noter", "bocal_3_4", "--donnees", donnees]) == 0
    capsys.readouterr()
    assert outil(["etat", "--donnees", donnees]) == 0
    assert "entonnoir_place = bocal_3_4" in capsys.readouterr().out
    assert outil(["noter", "ailleurs", "--donnees", donnees]) == 2
    assert outil(["noter", "--donnees", donnees]) == 2
    # Le programme repart avec cet état.
    assert Entonnoir(MACHINE, tmp_path / "entonnoir.json").place == "bocal_3_4"


def test_outil_reglages_en_erreur(reglages, capsys):
    remplacer(reglages / "machine.yaml", "  pointe_z: 0.627", "  pointe_z: 0.90")
    assert outil(["hauteurs", "--reglages", str(reglages)]) == 2
    assert "pointe_z doit être plus bas" in capsys.readouterr().err


def test_outil_de_la_preh_entonnoir_avec_de_faux_fluidnc(capsys):
    from vidange.prehension.outil import main as outil_prehension

    # Bocal inconnu : refusé avant de bouger.
    assert outil_prehension(["--faux", "entonnoir", "bocal_0_0", "bocal_9_9"]) == 2
    assert "n'est pas une place du quinconce" in capsys.readouterr().err
    # De faux FluidNC n'ont pas d'entonnoir sous la ventouse : « absent », tête en haut.
    assert outil_prehension(["--faux", "entonnoir", "bocal_0_0", "bocal_0_1"]) == 1
    assert "entonnoir absent sur le bocal rangée 1, place 1" in capsys.readouterr().err
