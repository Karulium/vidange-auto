"""Tâche 41 : la fermeture des seaux côté Pi (bras, gestes, règles 5 et 11, simulateur, outil)."""

from dataclasses import replace

import pytest

from vidange.chef import ErreurEtape
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fermeture import BrasFermeture
from vidange.fermeture.outil import main as outil
from vidange.griffe.bras import G
from vidange.materiel import ErreurMateriel, FausseFabrique, Materiel
from vidange.mycelium.module import module_mycelium
from vidange.registre import Registre
from vidange.reglages import charger_reglages
from vidange.remplissage.module import module_remplissage
from vidange.remplissage.outil import main as outil_remplissage
from vidange.remplissage.regles import Contexte, Pose, ReglesRemplissage
from vidange.remplissage.simulation import remplissage_du_simulateur
from vidange.simulateur import Simulateur

from .conftest import DOSSIER_PI
from .test_reglages import erreur_de, remplacer

LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
FERMETURE = MACHINE.fermeture
I2C = REGLAGES.pesees.i2c
assert FERMETURE is not None and I2C is not None
LIMITE_BRAS = MACHINE.remplissage.verrous.galet_plateau_max_z
COURSE_BASSE = MACHINE.axes["plateau_z"].course[0]


class Temps:
    """Une fausse horloge : attendre(s) la fait avancer."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def attendre(self, secondes: float) -> None:
        self.t += secondes


# ---------------------------------------------------------------- réglages


def test_reglages_de_la_fermeture_sont_ceux_de_la_fiche():
    # Hf figé (fiche), Hc = Hf − 6 mm, approche = Hc − 20 mm sans passer sous la course basse.
    hf = {n: f.hf_m for n, f in FERMETURE.formats.items()}
    assert hf == {"seau_a": 0.201, "seau_b": 0.251, "seau_c": 0.214, "seau_d": 0.194}
    hc = {n: round(FERMETURE.hc(n), 4) for n in hf}
    assert hc == {"seau_a": 0.195, "seau_b": 0.245, "seau_c": 0.208, "seau_d": 0.188}
    app = {n: round(FERMETURE.h_approche(n, COURSE_BASSE), 4) for n in hf}
    assert app == {"seau_a": 0.175, "seau_b": 0.225, "seau_c": 0.188, "seau_d": 0.175}
    # Rangé −160° (horaire), travail = la butée de l'étalonnage + la surcourse de 2,5°.
    assert FERMETURE.bras.range_deg == -160 and FERMETURE.bras.surcourse_deg == 2.5
    assert FERMETURE.servo_travail_deg() - FERMETURE.servo_range_deg() == pytest.approx(162.5)
    # Effort : réglage sous la limite de 200 N, sens horaire, 2 tours à 6 tr/min.
    assert FERMETURE.montee.force_max_n <= FERMETURE.montee.force_max_limite_n == 200
    assert FERMETURE.rotation.tours == 2 and FERMETURE.rotation.tr_min == 6
    # Diamètres des couvercles dans la table des formats (décisions, PR n° 54).
    diametres = {n: f.diametre_couvercle for n, f in MACHINE.griffe.formats.items()}
    assert diametres == {"seau_a": 0.28, "seau_b": 0.23, "seau_c": 0.315, "seau_d": 0.28}
    # Tous les Hf sont sous la limite du bras (règle 5).
    assert all(valeur <= LIMITE_BRAS for valeur in hf.values())


@pytest.mark.parametrize(
    "fichier, ancien, nouveau, message",
    [
        ("machine.yaml", "force_max_n: 150", "force_max_n: 250", "au plus 200 N"),
        ("machine.yaml", "force_contact_n: 10", "force_contact_n: 160", "plus petit que force_max"),
        (
            "machine.yaml",
            "contact_trop_tot_m: 0.010",
            "contact_trop_tot_m: 0.004",
            "plus grand que",
        ),
        ("machine.yaml", "marge_approche_m: 0.020", "marge_approche_m: 0.008", "marge_approche_m"),
        ("machine.yaml", "{hf_m: 0.251}", "{hf_m: 0.30}", "règle 5"),
        ("machine.yaml", "    seau_c: {hf_m: 0.214}", "    seau_z: {hf_m: 0.214}", "seau_z"),
        ("machine.yaml", "chariot_y: 0.50", "chariot_y: 1.50", "hors de la course du chariot"),
        ("machine.yaml", "butee_servo_deg: 200", "butee_servo_deg: 20", "hors de la plage"),
        ("machine.yaml", "butee_servo_deg: 200", "butee_servo_deg: 280", "hors de la plage"),
        ("machine.yaml", "servo: servo_fermeture_seaux", "servo: servo_inconnu", "servo_inconnu"),
        ("machine.yaml", "battement_s: 1.0\n  montee", "battement_s: 2.5\n  montee", "sous 2 s"),
        # La bande du haut du Stockage se contrôle avec le diamètre du couvercle.
        (
            "machine.yaml",
            "      pas_pile_m: 0.030\n      diametre_couvercle: 0.28\n",
            "      pas_pile_m: 0.030\n      diametre_couvercle: 0.30\n",
            "bord du couvercle",
        ),
        ("machine.yaml", "      diametre_couvercle: 0.315\n", "", "diametre_couvercle"),
        (
            "simulateur.yaml",
            "raideur_n_par_m: 10000",
            "raideur_n_par_m: -5",
            "raideur_n_par_m",
        ),
    ],
)
def test_reglages_faux_de_la_fermeture(reglages, fichier, ancien, nouveau, message):
    remplacer(reglages / fichier, ancien, nouveau)
    assert message in erreur_de(reglages)


def test_servo_deja_pris_par_le_micropore(reglages):
    remplacer(
        reglages / "machine.yaml",
        "servo: servo_fermeture_seaux",
        "servo: servo_lame_micropore",
    )
    assert "déjà celle du micropore" in erreur_de(reglages)


# ---------------------------------------------------------------- le bras


class Banc:
    """Le vrai bras sur le faux boîtier (sans simulateur)."""

    def __init__(self) -> None:
        self.temps = Temps()
        fabrique = FausseFabrique(LISTE)
        plages = [(v.angle_min_deg, v.angle_max_deg) for v in I2C.pca9685.voies.values()]
        self.boitier = fabrique.carte_pesee(I2C.carte).brancher_boitier(plages)
        self.materiel = Materiel(LISTE, fabrique, seulement=[I2C.carte])
        self.bras = BrasFermeture(FERMETURE, I2C, self.materiel, self.temps)

    def apres(self, secondes: float) -> None:
        self.temps.attendre(secondes)
        self.bras.observer()


def test_bras_rangé_seulement_ordonné_attente_passée_et_carte_vivante():
    banc = Banc()
    bras = banc.bras
    bras.lire()
    # Jamais ordonné depuis le démarrage : on ne sait pas.
    assert bras.est_range() is None
    bras.commander(bras.angle_range())
    assert banc.boitier.angles_deg[bras.voie] == bras.angle_range()
    bras.lire()
    # Ordonné mais l'attente de 0,5 s n'est pas passée : pas rangé.
    assert bras.est_range() is False
    banc.apres(FERMETURE.bras.attente_s)
    assert bras.est_range() is True
    # Au travail : pas rangé.
    bras.commander(bras.angle_travail())
    banc.apres(FERMETURE.bras.attente_s)
    assert bras.est_range() is False
    # Carte muette : on ne sait plus.
    bras.commander(bras.angle_range())
    banc.apres(FERMETURE.bras.attente_s)
    assert bras.est_range() is True
    banc.boitier.pca9685_muette = True
    banc.apres(0.1)
    assert bras.est_range() is None


def test_le_signal_du_servo_n_est_jamais_coupe_et_est_renvoye():
    banc = Banc()
    bras = banc.bras
    bras.commander(bras.angle_range())
    ordres = banc.boitier.ordres
    banc.apres(FERMETURE.bras.battement_s / 2)
    assert banc.boitier.ordres == ordres
    banc.apres(FERMETURE.bras.battement_s / 2)
    assert banc.boitier.ordres == ordres + 1
    assert banc.boitier.angles_deg[bras.voie] == bras.angle_range()
    assert bras.prochain() == pytest.approx(banc.temps() + FERMETURE.bras.battement_s)
    # Les voies du micropore ne sont jamais touchées par le bras.
    autres = [a for i, a in enumerate(banc.boitier.angles_deg) if i != bras.voie]
    assert all(angle is None for angle in autres)


def test_carte_redemarree_angle_renvoye_et_bras_pas_rangé_pendant_la_stabilisation():
    banc = Banc()
    bras = banc.bras
    bras.commander(bras.angle_range())
    banc.apres(FERMETURE.bras.attente_s)
    assert bras.est_range() is True
    banc.boitier.redemarrer()
    banc.boitier.demarrages += 4  # pas forcément de +1 (décisions, PR n° 84, point 4)
    assert banc.boitier.angles_deg[bras.voie] is None
    banc.apres(0.1)
    assert bras.redemarrages_vus == 1
    assert banc.boitier.angles_deg[bras.voie] == bras.angle_range()
    # Pas cru rangé tant que la carte n'a pas redit « ordre reçu » et que les servos se stabilisent.
    assert bras.est_range() is not True
    banc.apres(FERMETURE.bras.stabilisation_s)
    assert bras.est_range() is True


def test_premier_ordre_perdu_renvoye_et_angle_hors_plage_refuse():
    banc = Banc()
    banc.bras.angle = banc.bras.angle_range()
    banc.bras.lire()
    assert banc.boitier.angles_deg[banc.bras.voie] == banc.bras.angle_range()
    with pytest.raises(ErreurMateriel):
        banc.bras.commander(500.0)


# ---------------------------------------------------------------- règle 11


def test_regle_11_jamais_de_rotation_trigo_en_contact():
    regles = ReglesRemplissage(MACHINE)
    sens = FERMETURE.rotation.sens_horaire
    depart = Pose(y=0.50, z=0.25, a=100.0, barres=0.30, pousseur=0.0)
    contact = Contexte(True, None, True, micropore_escamote=True, fermeture_en_contact=True)
    libre = replace(contact, fermeture_en_contact=False)
    horaire, trigo = replace(depart, a=100.0 + sens * 90), replace(depart, a=100.0 - sens * 90)
    assert regles.refus_mouvement(depart, horaire, contact) is None
    refus = regles.refus_mouvement(depart, trigo, contact)
    assert refus is not None and "trigo" in refus
    # Sans contact, le sens trigo reste permis (pose du micropore, rangement...).
    assert regles.refus_mouvement(depart, trigo, libre) is None


# ---------------------------------------------------------------- scénario du simulateur


def jouer(regler=lambda scenario: None, reglages=REGLAGES, registre=None, journal=None):
    """Le scénario « remplissage » avec la fermeture : A puis B, de la pose au rangement."""
    with Simulateur(reglages, LISTE, "remplissage") as simulation:
        options = {} if registre is None else {"registre": registre}
        scenario = remplissage_du_simulateur(simulation, avec_fermeture=True, **options)
        assert scenario.fermeture is not None
        pas: list[tuple[str, object, bool]] = []
        executer = scenario.chariot.executer

        def noter(un_pas, cible):
            pas.append((un_pas.texte, cible, scenario.fermeture.fermeture.en_contact()))
            executer(un_pas, cible)

        scenario.chariot.executer = noter
        regler(scenario.fermeture)
        modules = [
            module_remplissage(
                scenario.remplissage, scenario.prehension, scenario.mycelium, scenario.plan
            ),
            module_mycelium(scenario.mycelium),
        ]
        planning = simulation.jouer(modules)
    return planning, scenario, pas


def textes(pas):
    return [texte for texte, _, _ in pas]


def test_scenario_fermeture_sur_les_2_seaux(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    planning, scenario, pas = jouer(registre=registre)
    assert planning.fini, planning.probleme
    simule = scenario.fermeture
    assert simule.fermeture.fermes == ["S0101", "S0102"]
    # Les gestes, dans l'ordre de la fiche, pour chaque seau.
    ordre = [
        "fermeture 3) : pesée du seau fermé libre (P0)",
        "fermeture 4) : montée jusqu'au contact du couvercle",
        "fermeture 4) : montée jusqu'à Hf, couvercle clipsé",
        "fermeture 5) : le plateau tourne en sens horaire",
        "fermeture 6) : le plateau redescend",
    ]
    liste = textes(pas)
    positions = [i for i, t in enumerate(liste) if t in ordre]
    assert [liste[i] for i in positions] == ordre * 2
    # Hauteurs : approche, contact dans la fenêtre de Hc, Hf, retour à l'approche.
    course_basse = COURSE_BASSE
    for numero, format in enumerate(("seau_a", "seau_b")):
        base = numero * 5
        z = [pas[i][1].z for i in positions[base : base + 5]]
        hc, hf = FERMETURE.hc(format), FERMETURE.formats[format].hf_m
        h_app = FERMETURE.h_approche(format, course_basse)
        assert z[0] == pytest.approx(h_app)
        # La montée s'arrête au contact (Hc) dans la fenêtre, pas à la fin de la fenêtre.
        assert z[1] == pytest.approx(hc + FERMETURE.montee.fenetre_contact_m)
        assert z[2] == pytest.approx(hf) and z[4] == pytest.approx(h_app)
    # Le bras : rangé (premier ordre, sans rampe) au début, au travail puis rangé pour chaque seau.
    servo = [t for t in liste if t.startswith("fermeture : bras")]
    assert servo[0] == "fermeture : bras rangé"
    assert servo.count("fermeture : bras au travail") >= 2
    assert simule.bras.est_range() is True
    # Aucune alerte, rien à vérifier, un effort noté par seau.
    assert registre.trouver("seau", "S0101")["a_verifier"] is None
    assert registre.trouver("seau", "S0102")["a_verifier"] is None
    assert registre.alarmes_ouvertes() == []
    efforts = registre.lire("SELECT valeur FROM mesures WHERE nom = 'fermeture_effort_clip'")
    assert len(efforts) == 2
    raideur = REGLAGES.simulateur.fermeture.raideur_n_par_m
    attendu = raideur * FERMETURE.montee.enfoncement_clip_m
    assert efforts[0]["valeur"] == pytest.approx(attendu, rel=0.05)
    registre.fermer()


def test_rotation_toujours_horaire_pendant_le_contact():
    planning, scenario, pas = jouer()
    assert planning.fini, planning.probleme
    sens = FERMETURE.rotation.sens_horaire
    angle = None
    en_contact = 0
    for _, cible, contact in pas:
        if contact and angle is not None:
            assert (cible.a - angle) * sens >= -1e-9, "rotation trigo pendant le contact"
            en_contact += 1
        angle = cible.a
    assert en_contact >= 4
    # Les 2 tours de clipsage, dans le sens horaire.
    rotations = [
        (cible.a - pas[i - 1][1].a)
        for i, (texte, cible, _) in enumerate(pas)
        if texte.startswith("fermeture 5)")
    ]
    assert len(rotations) == 2
    for tour in rotations:
        assert tour == pytest.approx(sens * FERMETURE.rotation.tours * 360)


def test_le_plateau_ne_monte_pas_au_dessus_de_la_limite_du_bras_avant_de_le_voir_rangé():
    # Au démarrage le bras est inconnu : jusqu'à « fermeture : bras rangé » (premier ordre, sans
    # rampe, plateau en bas), aucun pas ne monte le plateau au-dessus de la limite du bras.
    planning, scenario, pas = jouer()
    assert planning.fini, planning.probleme
    liste = textes(pas)
    premier = liste.index("fermeture : bras rangé")
    assert all(cible.z <= LIMITE_BRAS + 1e-9 for _, cible, _ in pas[: premier + 1])
    assert pas[premier][1].z <= REGLAGES.machine.remplissage.plateau_en_bas_z
    # Le premier ordre du bras arrive sans rampe : un seul pas « bras rangé » avant l'attente.
    assert liste[premier + 1] != "fermeture : bras rangé"
    # Après, chaque pas qui monte au-dessus de la limite est joué bras vu rangé.
    for i, (_, cible, _) in enumerate(pas):
        if cible.z > LIMITE_BRAS + 1e-9:
            assert i > premier


def test_le_servo_est_refuse_si_le_plateau_est_trop_haut():
    with Simulateur(REGLAGES, LISTE, "remplissage") as simulation:
        scenario = remplissage_du_simulateur(simulation, avec_fermeture=True)
        fermeture = scenario.fermeture.fermeture
        remplissage = scenario.remplissage
        # Le plateau est monté de force au-dessus de la limite du bras.
        simulation.etat_axes.positions["plateau_z"] = LIMITE_BRAS + 0.05
        with pytest.raises(ErreurEtape, match="servo du bras refusé"):
            remplissage.lancer(fermeture.geste_ranger)
        assert scenario.fermeture.bras.angle is None
        # Plateau bas mais pas tout en bas : le premier ordre (sans rampe) est refusé aussi.
        simulation.etat_axes.positions["plateau_z"] = (
            REGLAGES.machine.remplissage.plateau_en_bas_z + 0.03
        )
        with pytest.raises(ErreurEtape, match="plateau en bas"):
            remplissage.lancer(fermeture.geste_ranger)
        assert scenario.fermeture.bras.angle is None


def test_trigo_refuse_par_le_remplissage_tant_que_le_couvercle_touche_le_rouleau():
    with Simulateur(REGLAGES, LISTE, "remplissage") as simulation:
        scenario = remplissage_du_simulateur(simulation, avec_fermeture=True)
        remplissage = scenario.remplissage
        sens = FERMETURE.rotation.sens_horaire
        scenario.fermeture.fermeture._en_contact = True
        with pytest.raises(ErreurEtape, match="trigo"):
            remplissage.lancer(lambda: remplissage.geste_tourner_de(-sens * 90))
        remplissage.arreter()
        remplissage.lancer(lambda: remplissage.geste_tourner_de(sens * 90))
        remplissage.arreter()


def hauteurs_apres(pas, texte_debut):
    i = next(i for i, (t, _, _) in enumerate(pas) if t.startswith(texte_debut))
    return [cible.z for _, cible, _ in pas[i:]]


def test_pas_de_couvercle_pas_de_contact_retour_et_bras_rangé(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")

    def regler(simule):
        simule.physique.couvercle = False

    planning, scenario, pas = jouer(regler, registre=registre)
    # Le cycle continue, seaux « à vérifier », aucune rotation de clipsage.
    assert planning.fini, planning.probleme
    assert not any(t.startswith("fermeture 5)") for t in textes(pas))
    for code in ("S0101", "S0102"):
        assert "pas de contact" in registre.trouver("seau", code)["a_verifier"]
    assert any("pas de contact" in a["message"] for a in registre.alarmes_ouvertes())
    assert scenario.fermeture.bras.est_range() is True
    assert scenario.fermeture.fermeture.en_contact() is False
    registre.fermer()


def test_contact_trop_tot_couvercle_mal_pose(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")

    def regler(simule):
        simule.physique.ecart_contact_m = -(FERMETURE.montee.contact_trop_tot_m + 0.004)

    planning, scenario, pas = jouer(regler, registre=registre)
    assert planning.fini, planning.probleme
    assert not any(t.startswith("fermeture 5)") for t in textes(pas))
    assert "mal posé" in registre.trouver("seau", "S0101")["a_verifier"]
    # Retour à l'approche, bras rangé.
    assert scenario.fermeture.bras.est_range() is True
    registre.fermer()


def test_effort_au_dela_de_f_max_arret_et_descente(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    raideur = 200000
    arrets = []

    def regler(simule):
        # Couvercle dur : l'effort dépasse F_max bien avant Hf.
        simule.physique.raideur_n_par_m = raideur
        chariot = simule.fermeture.remplissage.chariot
        executer = chariot.executer

        def noter(un_pas, cible):
            executer(un_pas, cible)
            if un_pas.texte.startswith(("fermeture 4)", "fermeture : retour")):
                arrets.append((un_pas.texte, chariot._resultat.pose.z))

        chariot.executer = noter

    planning, scenario, pas = jouer(regler, registre=registre)
    assert planning.fini, planning.probleme
    assert "couvercle bloqué" in registre.trouver("seau", "S0101")["a_verifier"]
    # La montée s'arrête là où l'effort atteint F_max (avant Hf), jamais de rotation de clipsage,
    # puis le plateau redescend à H_app.
    texte, z = arrets[1]  # [0] : la montée jusqu'au contact
    assert texte.startswith("fermeture 4) : montée jusqu'à Hf")
    hf = FERMETURE.formats["seau_a"].hf_m
    arret = FERMETURE.hc("seau_a") + FERMETURE.montee.force_max_n / raideur
    assert z < hf and z == pytest.approx(arret, abs=0.0005)
    assert arrets[2][0].startswith("fermeture : retour")
    assert arrets[2][1] == pytest.approx(FERMETURE.h_approche("seau_a", COURSE_BASSE))
    assert not any(t.startswith("fermeture 5)") for t in textes(pas))
    assert scenario.fermeture.bras.est_range() is True
    registre.fermer()


def test_effort_en_rotation_au_dela_de_f_max_arret_de_la_rotation():
    arrivees = []

    def regler(simule):
        simule.physique.effort_rotation_n = FERMETURE.montee.force_max_n + 50
        chariot = simule.fermeture.remplissage.chariot
        executer = chariot.executer

        def noter(un_pas, cible):
            avant = chariot.position().a
            executer(un_pas, cible)
            if un_pas.texte.startswith("fermeture 5)"):
                arrivees.append((avant, chariot._resultat.pose.a))

        chariot.executer = noter

    planning, scenario, pas = jouer(regler)
    assert planning.fini, planning.probleme
    # La rotation n'a pas eu lieu (arrêt tout de suite), puis retour à H_app et bras rangé.
    assert arrivees and all(arrivee == pytest.approx(avant) for avant, arrivee in arrivees)
    assert any("couvercle bloqué" in m for m in scenario.fermeture.fermeture.messages)
    assert scenario.fermeture.bras.est_range() is True


def test_couvercle_qui_reste_contre_le_rouleau_alarme_et_bras_immobile():
    def regler(simule):
        executer = simule.fermeture.remplissage.chariot.executer

        def coller(un_pas, cible):
            executer(un_pas, cible)
            # La descente ne décolle pas le couvercle : la balance lit encore l'effort.
            if un_pas.texte.startswith("fermeture 6)"):
                simule.physique.effort_rotation_n = 0
                simule.physique.ecart_contact_m = -1.0

        simule.fermeture.remplissage.chariot.executer = coller

    planning, scenario, pas = jouer(regler)
    assert not planning.fini
    assert "reste contre le rouleau" in planning.probleme
    # Le bras n'a pas bougé après l'alarme (au travail), le couvercle reste noté en contact.
    assert scenario.fermeture.bras.est_range() is False
    assert scenario.fermeture.fermeture.en_contact() is True
    assert scenario.fermeture.boitier.angles_deg[scenario.fermeture.bras.voie] == pytest.approx(
        scenario.fermeture.bras.angle_travail()
    )


def test_carte_redemarree_pendant_la_fermeture_arret_et_bras_rangé(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")

    def regler(simule):
        executer = simule.fermeture.remplissage.chariot.executer
        fait = []

        def couper(un_pas, cible):
            executer(un_pas, cible)
            if un_pas.texte.startswith("fermeture 4) : montée jusqu'au contact") and not fait:
                fait.append(True)
                simule.boitier.redemarrer()

        simule.fermeture.remplissage.chariot.executer = couper

    planning, scenario, pas = jouer(regler, registre=registre)
    assert planning.fini, planning.probleme
    assert scenario.fermeture.bras.redemarrages_vus == 1
    assert "redémarré" in registre.trouver("seau", "S0101")["a_verifier"]
    # Le 2e seau est fermé normalement.
    assert registre.trouver("seau", "S0102")["a_verifier"] is None
    assert scenario.fermeture.fermeture.fermes == ["S0102"]
    assert scenario.fermeture.bras.est_range() is True
    registre.fermer()


def test_format_inconnu_de_la_fermeture_rempli_sans_fermer(reglages):
    remplacer(reglages / "machine.yaml", "    seau_b: {hf_m: 0.251}\n", "")
    planning, scenario, pas = jouer(reglages=charger_reglages(reglages))
    assert planning.fini, planning.probleme
    assert scenario.fermeture.fermeture.fermes == ["S0101"]
    assert any(
        "seau_b » inconnu de la fermeture" in m for m in scenario.fermeture.fermeture.messages
    )


# ---------------------------------------------------------------- outil


def lancer_outil(*arguments, temps=None, fabrique=None):
    temps = temps or Temps()
    return outil(
        [*(() if fabrique else ("--faux",)), *arguments],
        fabrique=fabrique,
        attendre=temps.attendre,
        horloge=temps,
    )


def test_outil_etat_servo_ranger_travail(capsys):
    fabrique = FausseFabrique(LISTE)
    plages = [(v.angle_min_deg, v.angle_max_deg) for v in I2C.pca9685.voies.values()]
    boitier = fabrique.carte_pesee(I2C.carte).brancher_boitier(plages)
    voie = list(I2C.pca9685.voies).index(FERMETURE.servo)
    lancer = lambda *a: lancer_outil(*a, fabrique=fabrique)  # noqa: E731
    assert lancer("etat") == 0
    sortie = capsys.readouterr().out
    assert "coupé" in sortie and f"rangé {FERMETURE.servo_range_deg():g}°" in sortie
    # Sans --plateau-bas, le bras ne tourne pas.
    assert lancer("ranger") == 2
    assert "--plateau-bas" in capsys.readouterr().err
    assert boitier.angles_deg[voie] is None
    # Premier ordre : sans rampe.
    assert lancer("--plateau-bas", "ranger") == 0
    assert "sans rampe" in capsys.readouterr().out
    assert boitier.angles_deg[voie] == pytest.approx(FERMETURE.servo_range_deg())
    # Ensuite : au travail, puis un angle d'étalonnage.
    assert lancer("--plateau-bas", "travail") == 0
    assert boitier.angles_deg[voie] == pytest.approx(FERMETURE.servo_travail_deg())
    assert lancer("--plateau-bas", "servo", "190") == 0
    assert boitier.angles_deg[voie] == pytest.approx(190)
    # Un angle hors de la plage du servo est refusé par la carte.
    assert lancer("--plateau-bas", "servo", "500") == 1
    assert "ÉCHEC" in capsys.readouterr().err


def test_outil_remplissage_fermer_avec_le_faux(capsys, monkeypatch):
    # Le plateau du fût est en place (règle 7), sans couvercle (la fausse balance ne lit rien) : pas
    # de contact, retour, bras rangé.
    class PosteEnPlace:
        echange_en_cours = False

        def __init__(self, *arguments, **options):
            pass

    monkeypatch.setattr("vidange.remplissage.outil.PosteFut", PosteEnPlace)
    assert (
        outil_remplissage(
            ["--faux", "--manivelle-en-bas", "--micropore-rentre", "fermer", "seau_a"]
        )
        == 0
    )
    sortie = capsys.readouterr().out
    assert "pas de contact" in sortie


# ---------------------------------------------------------------- le vrai chariot, faux FluidNC


def test_chariot_vrai_monte_lentement_et_s_arrete_a_l_effort_maximal():
    import threading

    from vidange.fluidnc import FauxFluidnc, Liaison
    from vidange.griffe.simulation import FausseForce
    from vidange.remplissage.chariot import ChariotFluidnc, Pas, signaux_chariot

    from .test_remplissage import attendre, reglages_carte

    carte = FauxFluidnc(axes="XYZABC", vitesse_rapide_mm_min=60000)
    carte.positions.update(X=-6.0, Y=500.0, Z=195.0, A=0.0, B=-9.0, C=0.0)
    reglages = reglages_carte()
    liaison = Liaison("chariot", reglages, ouvrir=carte.ouvrir)
    liaison.demarrer()
    arret = threading.Event()
    try:
        liaison.attendre_connexion(5)
        # Un couvercle à 20 N par mm au-dessus de 200 mm, sur la fausse balance.
        balance = FausseForce(0.0)
        balance.fonction = lambda: G * 0.5 + 20.0 * max(0.0, carte.positions["Z"] - 200.0)
        chariot = ChariotFluidnc(
            MACHINE, liaison, balance, signaux_chariot(liaison, reglages.cartes["chariot"])
        )
        chariot.demarrer(arret)
        attendre(lambda: chariot.position().z == pytest.approx(0.195))
        attendre(lambda: abs(chariot.peser() - 0.5) < 1e-6)
        depart = chariot.position()
        # Montée à 20 mm/s jusqu'à 230 mm, arrêt dès que la balance lit 0,5 kg + 100 N.
        pas = Pas(
            "montée en appui",
            {"z": 0.230},
            vitesse_z=0.02,
            poids_max_kg=0.5 + 100 / G,
            pesee=True,
        )
        chariot.executer(pas, depart.avec(z=0.230))
        attendre(chariot.fini)
        resultat = chariot.resultat()
        assert resultat.depasse is True and resultat.contact is False
        # Arrêté à 205 mm (100 N à 20 N/mm au-dessus de 200 mm), à quelques mm près.
        assert 0.204 <= resultat.pose.z <= 0.212
        assert resultat.poids_kg is not None and resultat.poids_kg * G >= 0.5 * G + 95
        jog = [ligne for ligne in carte.lignes_recues if ligne.startswith("$J=")][-1]
        assert "Z230" in jog and "F1200" in jog  # 20 mm/s = 1200 mm/min
    finally:
        arret.set()
        liaison.arreter()
