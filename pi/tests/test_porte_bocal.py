"""Porte-bocal (tâche 20) : réglages, origine de la manivelle, vrai porte-bocal sur le faux
FluidNC (mors, demi-tours, pannes), Mycélium au simulateur avec le vrai porte-bocal, outil."""

import time

import pytest

from vidange.chef import ErreurEtape
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.fluidnc import FauxFluidnc, Liaison
from vidange.mycelium import Pas, PoseAgitateur, module_mycelium
from vidange.mycelium.agitateur import trouver_origine
from vidange.mycelium.regles import EtatChariot, ReglesMycelium
from vidange.mycelium.simulation import mycelium_du_simulateur
from vidange.porte_bocal import PorteBocalFluidnc, signaux_porte_bocal
from vidange.porte_bocal.faux import FauxMaterielPorteBocal
from vidange.porte_bocal.outil import main as outil
from vidange.reglages import Machine, charger_reglages
from vidange.simulateur import Simulateur

from .conftest import DOSSIER_PI
from .test_fluidnc_liaison import DELAI, reglages_essai
from .test_mycelium import BancAgitateur, attendre
from .test_reglages import erreur_de, remplacer

LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
CARTE = REGLAGES.fluidnc.cartes["mycelium_lavage"]
ORIGINE = MACHINE.mycelium.manivelle.origine
REGLES = ReglesMycelium(MACHINE)
ECARTE = EtatChariot(y=0.40, plateau_z=0.53)


# ---------------------------------------------------------------- réglages


def test_reglages_du_porte_bocal_du_depot():
    porte_bocal = MACHINE.porte_bocal
    assert porte_bocal is not None and porte_bocal.exemple
    assert (porte_bocal.diametre_bocal_m, porte_bocal.diametre_capsule_m) == (0.095, 0.103)
    assert MACHINE.axes["mors"].course == (0.08, 0.103)
    # Chaque signal de la carte n° 3 cité dans fluidnc.yaml est dans la liste des entrées/sorties.
    for nom in (*CARTE.entrees, *CARTE.sorties):
        assert LISTE.signaux[nom].carte == "fluidnc_mycelium_lavage", nom
    assert LISTE.signaux["verrou_plateau_engage"].module == "porte_bocal"
    assert "PAS en haut" in LISTE.signaux["origine_manivelle"].description


def test_reglages_du_porte_bocal_verifies(reglages):
    machine = reglages / "machine.yaml"
    remplacer(machine, "  diametre_capsule_m: 0.103", "  diametre_capsule_m: 0.11")
    remplacer(machine, "    course: [0.08, 0.103]", "    course: [0.093, 0.103]")
    message = erreur_de(reglages)
    assert "mors ouverts à 0.103 m (fin de la course de « mors »), la capsule (0.11 m)" in message
    assert "le début de la course de « mors » (0.093 m) doit être sous" in message


def test_durees_du_demi_tour_verifiees(reglages):
    remplacer(reglages / "machine.yaml", "    relache_s: 0.5", "    relache_s: 5")
    message = erreur_de(reglages)
    assert "porte_bocal → demi_tour : relache_s doit être plus court que delai_max_s" in message


def test_reglages_entre_fichiers_du_porte_bocal(reglages):
    remplacer(reglages / "machine.yaml", "      vitesse_deg_s: 5", "      vitesse_deg_s: 50")
    remplacer(
        reglages / "machine.yaml",
        "    attente_inclinaison_s: 0.5",
        "    attente_inclinaison_s: 0.2",
    )
    message = erreur_de(reglages)
    assert "vitesse_deg_s : 50 °/s × periode_etat_s de fluidnc.yaml (0.2 s) = 10°" in message
    assert "attente_inclinaison_s (0.2 s) doit valoir au moins 2 fois periode_etat_s" in message


def test_signaux_de_la_carte_verifies(reglages):
    remplacer(
        reglages / "fluidnc.yaml", '      inclinaison_bocal: "1"', '      inclinaison_bocal: "0"'
    )
    message = erreur_de(reglages)
    assert "entrees : « verrou_plateau_engage » et « inclinaison_bocal » ont la même (0)" in message


# ---------------------------------------------------------------- origine de la manivelle


def tour(depart: float, haut: float, demi_zone: float = 95, pas: float = 1, metal=None):
    """Les lectures d'un tour lent (sens +) avec un faux capteur : métal hors de ± demi_zone."""
    lectures = []
    angle = depart
    while angle <= depart + ORIGINE.balayage_deg():
        ecart = abs((angle - haut + 180) % 360 - 180)
        vu = ecart > demi_zone if metal is None else metal(angle, ecart > demi_zone)
        lectures.append((angle, vu))
        angle += pas
    return lectures


@pytest.mark.parametrize("depart", [0, 37, 150, 250, 330])
def test_origine_au_milieu_de_la_zone_sans_metal(depart):
    # Où que parte la manivelle (dans la zone ou pas), « en haut » est trouvé à ≈ 0,5° près.
    haut = trouver_origine(tour(depart, haut=37.0), ORIGINE)
    assert abs((haut - 37 + 180) % 360 - 180) <= 0.5


def test_origine_avec_decalage():
    donnees = ORIGINE.model_dump() | {"decalage_deg": 2.5}
    reglages = type(ORIGINE).model_validate(donnees)
    assert trouver_origine(tour(0, haut=37.0), reglages) == pytest.approx(37 + 2.5 + 360, abs=0.5)


def test_capteur_manivelle_mauvaise_largeur():
    with pytest.raises(ValueError, match="zone sans métal de 15\\d° \\(attendu 190 ± 10°\\)"):
        trouver_origine(tour(0, haut=37.0, demi_zone=75), ORIGINE)


def test_capteur_manivelle_trop_de_bords():
    # Un morceau de métal étranger au milieu de la zone : 4 bords sur un tour.
    lectures = tour(0, 37.0, metal=lambda angle, vu: vu or 30 <= angle % 360 <= 40)
    with pytest.raises(ValueError, match="bords sur un tour \\(2 attendus\\)"):
        trouver_origine(lectures, ORIGINE)


@pytest.mark.parametrize("vu", [True, False])
def test_capteur_manivelle_debranche_ou_toujours_actionne(vu):
    with pytest.raises(ValueError, match="pas vue en entier"):
        trouver_origine(tour(0, 37.0, metal=lambda angle, _: vu), ORIGINE)


def test_origine_sur_le_faux_fluidnc_et_capteur_deregle():
    with BancAgitateur(demi_zone=75) as banc:
        attendre(lambda: "A" in banc.liaison.etat.positions)
        banc.agitateur.executer(Pas("origine", origine=True), None)
        with pytest.raises(ErreurEtape, match="capteur manivelle : zone sans métal") as erreur:
            attendre(lambda: banc.agitateur.fini() and False, 5)
        assert "Capteur manivelle" in erreur.value.quoi_faire
        assert not banc.agitateur.origine_connue()


def test_origine_perdue_si_la_carte_redemarre():
    with BancAgitateur() as banc:
        banc.prendre_origine()
        assert banc.agitateur.origine_connue()
        banc.faux.redemarrer()
        attendre(lambda: not banc.agitateur.origine_connue())
        with pytest.raises(ErreurEtape, match="origine de la manivelle pas faite, ou perdue"):
            banc.agitateur.position()


# ---------------------------------------------------------------- le vrai porte-bocal


def machine_rapide() -> Machine:
    """Durées du demi-tour raccourcies (essais en vrai temps)."""
    donnees = MACHINE.model_dump()
    donnees["porte_bocal"]["demi_tour"] = {
        "relache_s": 0.1,
        "delai_max_s": 1.0,
        "attente_inclinaison_s": 0.1,
    }
    return Machine.model_validate(donnees)


class BancPorteBocal:
    """Le vrai porte-bocal sur un faux FluidNC (mors Y), avec un faux plateau et un faux bocal."""

    def __init__(self, controle: str = "bon") -> None:
        self.machine = machine_rapide()
        self.faux = FauxFluidnc(axes="XY")
        self.materiel = FauxMaterielPorteBocal(
            self.faux, self.machine, CARTE, demi_tour_s=0.4, horloge=time.monotonic
        )
        self.liaison = Liaison("portique", reglages_essai(), ouvrir=self.faux.ouvrir)
        self.photos: list[str] = []
        self.controles = 0
        self.reponse = controle

    def controle(self) -> str:
        self.controles += 1
        return self.reponse

    def __enter__(self) -> "BancPorteBocal":
        self.liaison.demarrer()
        self.liaison.attendre_connexion(DELAI)
        self.porte_bocal = PorteBocalFluidnc(
            self.machine,
            self.liaison,
            signaux_porte_bocal(self.liaison, CARTE),
            photo=self.photos.append,
            controle=self.controle,
        )
        return self

    def __exit__(self, *_: object) -> None:
        self.liaison.arreter()

    def faire(self, geste) -> None:
        geste()
        attendre(self.porte_bocal.fini)

    def echec(self, geste) -> ErreurEtape:
        geste()
        with pytest.raises(ErreurEtape) as erreur:
            attendre(lambda: self.porte_bocal.fini() and False)
        return erreur.value


def test_serrer_et_ouvrir():
    with BancPorteBocal() as banc:
        banc.materiel.poser_bocal()
        banc.faire(banc.porte_bocal.serrer_bocal)
        # Mors ouverts (origine reprise), puis palpage : 2 mors à 10 mm/s chacun = 1200 mm/min.
        assert banc.faux.lignes_recues[-3:] == ["$HY", "G91 G38.3 Y-23.000 F1200", "G90"]
        assert banc.porte_bocal.diametre() == pytest.approx(0.095)
        assert banc.porte_bocal.serre()
        banc.faire(banc.porte_bocal.ouvrir_mors)
        assert banc.porte_bocal.diametre() == pytest.approx(0.103)
        assert not banc.porte_bocal.serre()


@pytest.mark.parametrize("bocal", [None, 0.1])
def test_bocal_absent_ou_mal_pose(bocal):
    with BancPorteBocal() as banc:
        if bocal is not None:
            banc.materiel.poser_bocal(bocal)
        erreur = banc.echec(banc.porte_bocal.serrer_bocal)
        assert "bocal absent, cassé ou mal posé" in str(erreur)
        assert "attendu 95 ± 3 mm" in str(erreur)
        assert "Remettre un bocal bien droit" in erreur.quoi_faire
        # L'alerte a sa photo.
        assert banc.photos and banc.photos[0].startswith("bocal absent")


def test_demi_tours_et_photo_de_controle():
    with BancPorteBocal() as banc:
        banc.materiel.poser_bocal()
        banc.faire(banc.porte_bocal.serrer_bocal)
        banc.faire(banc.porte_bocal.retourner_tete_en_bas)
        assert banc.materiel.tete_en_bas and banc.porte_bocal.tete_en_bas()
        assert banc.controles == 0
        # Les mors ne s'ouvrent jamais bocal tête en bas.
        with pytest.raises(ErreurEtape, match="bocal est tête en bas"):
            banc.porte_bocal.ouvrir_mors()
        banc.faire(banc.porte_bocal.remettre_debout)
        assert not banc.materiel.tete_en_bas
        assert banc.materiel.gestes == ["tete_en_bas", "debout"]
        # Photo de contrôle après le retour debout ; moteur et électroaimant coupés.
        assert banc.controles == 1
        assert not any(banc.faux.sorties.values())
        # Refait (après une alarme) : déjà debout, il ne fait que vérifier.
        banc.faire(banc.porte_bocal.remettre_debout)
        assert banc.materiel.gestes == ["tete_en_bas", "debout"] and banc.controles == 2


def test_photo_de_controle_douteuse():
    with BancPorteBocal(controle="douteux") as banc:
        banc.materiel.poser_bocal()
        banc.faire(banc.porte_bocal.serrer_bocal)
        banc.faire(banc.porte_bocal.retourner_tete_en_bas)
        erreur = banc.echec(banc.porte_bocal.remettre_debout)
        assert "photo de contrôle du bocal douteuse" in str(erreur)
        assert banc.photos == ["photo de contrôle du bocal douteuse"]


def test_verrou_qui_ne_revient_pas():
    with BancPorteBocal() as banc:
        banc.materiel.poser_bocal()
        banc.faire(banc.porte_bocal.serrer_bocal)
        banc.materiel.doigt_coince = True
        erreur = banc.echec(banc.porte_bocal.retourner_tete_en_bas)
        assert "le verrou du plateau n'est pas revenu en 1 s" in str(erreur)
        assert "doigt du verrou coincé" in erreur.quoi_faire
        # Moteur et électroaimant coupés.
        attendre(lambda: not any(banc.faux.sorties.values()))


def test_capteur_d_inclinaison_faux():
    with BancPorteBocal() as banc:
        banc.materiel.poser_bocal()
        banc.faire(banc.porte_bocal.serrer_bocal)
        banc.faire(banc.porte_bocal.retourner_tete_en_bas)
        # Le capteur reste sur « tête en bas » (actionné) : le retour debout n'est pas vu.
        banc.materiel.inclinaison_forcee = True
        erreur = banc.echec(banc.porte_bocal.remettre_debout)
        assert "capteur d'inclinaison : bocal tête en bas, il devait être debout" in str(erreur)


def test_plateau_bloque():
    with BancPorteBocal() as banc:
        banc.materiel.poser_bocal()
        banc.faire(banc.porte_bocal.serrer_bocal)
        banc.materiel.bloque = True
        # Le doigt retombe dans le même trou : le capteur d'inclinaison voit que rien n'a tourné.
        erreur = banc.echec(banc.porte_bocal.retourner_tete_en_bas)
        assert "bocal debout, il devait être tête en bas" in str(erreur)


def test_demi_tour_refuse():
    with BancPorteBocal() as banc:
        # Bocal pas serré.
        with pytest.raises(ErreurEtape, match="bocal pas serré"):
            banc.porte_bocal.retourner_tete_en_bas()
        banc.materiel.poser_bocal()
        banc.faire(banc.porte_bocal.serrer_bocal)
        # Le Mycélium l'interdit (manivelle en haut...).
        banc.porte_bocal.verrou = lambda: "le demi-tour du bocal ne se fait que manivelle en haut"
        with pytest.raises(ErreurEtape, match="refusé : le demi-tour du bocal ne se fait que"):
            banc.porte_bocal.retourner_tete_en_bas()
        assert not any(banc.faux.sorties.values())


def test_regles_du_demi_tour():
    # Agitateur fixe (tâche 19 ter) : demi-tour manivelle en haut, chariot à y ≥ 0,40.
    en_haut = PoseAgitateur(angle=0)
    assert REGLES.refus_demi_tour(en_haut, ECARTE) is None
    assert "manivelle en haut" in REGLES.refus_demi_tour(en_haut.avec(angle=180), ECARTE)
    pas_ecarte = EtatChariot(y=0.2, plateau_z=0.53)
    assert "chariot de remplissage" in REGLES.refus_demi_tour(en_haut, pas_ecarte)


# ---------------------------------------------------------------- Mycélium au simulateur


def jouer(**options):
    with Simulateur(REGLAGES, LISTE, "dosage_mycelium") as simu:
        mycelium = mycelium_du_simulateur(simu, **options)
        textes: list[str] = []
        envoyer = mycelium._envoyer

        def noter(pas):
            textes.append(pas.texte)
            envoyer(pas)

        mycelium._envoyer = noter
        planning = simu.jouer([module_mycelium(mycelium)])
    return planning, mycelium, textes


def test_simulateur_avec_le_vrai_porte_bocal():
    planning, mycelium, textes = jouer(origine_connue=False)
    assert planning.fini, planning.probleme
    assert len(mycelium.doses) == 8
    assert mycelium.materiel_porte_bocal.gestes == ["tete_en_bas", "debout"] * 8
    # Prise d'origine de la manivelle d'abord ; 2 bocaux : mors ouverts, bocal serré.
    assert textes[0] == "origine de la manivelle (tour lent)"
    assert textes.count("mors ouverts") == 2 and textes.count("bocal serré") == 2
    # Pose du bocal manivelle en bas ; elle ne monte que pour le demi-tour, puis redescend
    # (l'attente).
    debut = textes.index("bocal tête en bas")
    assert textes[debut - 3 : debut + 2] == [
        "mors ouverts",
        "bocal serré",
        "manivelle en haut",
        "bocal tête en bas",
        "manivelle en bas",
    ]
    debut = textes.index("bocal remis debout")
    assert textes[debut - 1 : debut + 2] == [
        "manivelle en haut",
        "bocal remis debout",
        "manivelle en bas",
    ]
    # Couche suivante (même bocal) : manivelle en haut, tête en bas, manivelle en bas.
    suivant = textes.index("bocal tête en bas", debut)
    assert textes[suivant - 1 : suivant + 2] == [
        "manivelle en haut",
        "bocal tête en bas",
        "manivelle en bas",
    ]


def test_simulateur_bocal_absent():
    with Simulateur(REGLAGES, LISTE, "dosage_mycelium") as simu:
        mycelium = mycelium_du_simulateur(simu)
        mycelium.materiel_porte_bocal.poser_bocal = lambda: None
        planning = simu.jouer([module_mycelium(mycelium)])
    assert "étape « changer_de_bocal »" in planning.probleme
    assert "bocal absent, cassé ou mal posé : mors arrêtés à 80.0 mm" in planning.probleme


def test_simulateur_photo_de_controle_douteuse():
    planning, mycelium, _ = jouer(controle=lambda: "douteux")
    assert "étape « rentrer »" in planning.probleme
    assert "photo de contrôle du bocal douteuse" in planning.probleme
    assert len(mycelium.doses) == 1


def test_simulateur_demi_tour_refuse_manivelle_en_bas():
    with Simulateur(REGLAGES, LISTE, "dosage_mycelium") as simu:
        mycelium = mycelium_du_simulateur(simu)
        simu.etat_axes.positions.update(manivelle=180)
        assert "manivelle en haut" in mycelium.refus_demi_tour()
        porte_bocal = mycelium.porte_bocal
        with pytest.raises(ErreurEtape, match="refusé : le demi-tour du bocal ne se fait que"):
            porte_bocal.retourner_tete_en_bas()


def test_simulateur_avec_le_faux_porte_bocal():
    planning, mycelium, _ = jouer(faux_porte_bocal=True)
    assert planning.fini, planning.probleme
    assert mycelium.porte_bocal.gestes == ["tete_en_bas", "debout"] * 8
    assert mycelium.porte_bocal.mors == ["ouvrir", "serrer"] * 2


# ---------------------------------------------------------------- outil


def test_outil_sur_le_faux_fluidnc(reglages, capsys):
    # Tour lent plus rapide, et état de la carte lu plus souvent (essai en vrai temps).
    remplacer(reglages / "machine.yaml", "      vitesse_deg_s: 5", "      vitesse_deg_s: 200")
    remplacer(reglages / "fluidnc.yaml", "  periode_etat_s: 0.2", "  periode_etat_s: 0.02")
    remplacer(reglages / "fluidnc.yaml", "  delai_silence_s: 2", "  delai_silence_s: 0.5")
    textes = {}
    # Chaque appel a sa carte imaginaire neuve : bocal serré, debout.
    for commande in ("etat", "ouvrir", "serrer", "tete-en-bas"):
        code = outil(["--faux", "--reglages", str(reglages), commande])
        textes[commande] = capsys.readouterr()
        assert code == 0, textes[commande]
    assert "écart des mors : 95.0 mm" in textes["etat"].out
    assert "Mors ouverts : écart 103.0 mm" in textes["ouvrir"].out
    assert "Mors serrés : écart 95.0 mm" in textes["serrer"].out
    assert "Manivelle en haut : H = " in textes["tete-en-bas"].out
    assert "Bocal tête en bas, manivelle en bas." in textes["tete-en-bas"].out
