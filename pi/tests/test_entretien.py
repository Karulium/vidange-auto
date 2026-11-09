"""Entretien (tâche 26) : compteurs par axe et par actionneur, pièces d'usure, calendrier,
alerte, bouton « fait » et page maintenance."""

import json
import threading
from datetime import datetime, timedelta

import pytest

from vidange.api.app import Services
from vidange.demarrage import CODE_OK, CODE_REGLAGES_FAUX, principal
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.entretien import Compteurs, Entretien, verifier_avec_liste
from vidange.fluidnc.faux import FauxFluidnc
from vidange.fluidnc.liaison import Liaison
from vidange.journal import NOM_FICHIER
from vidange.materiel import FausseFabrique, Materiel
from vidange.registre import Registre
from vidange.reglages import ReglagesEntretien, charger_reglages
from vidange.simulateur import Simulateur

from .conftest import DOSSIER_PI
from .test_api import LOCAL, client_connecte, creer_app_de_test
from .test_chef import Horloge, nouveau_chef
from .test_demarrage import options
from .test_fluidnc_liaison import DELAI, reglages_essai
from .test_reglages import ajouter, erreur_de, remplacer
from .test_simulateur import LISTE

REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
ENTRETIEN = REGLAGES.entretien
DEBUT = datetime(2026, 11, 9, 8, 0).astimezone()


def nouveaux_compteurs(fichier=None, maintenant=lambda: DEBUT) -> Compteurs:
    return Compteurs(
        ENTRETIEN.compteurs, REGLAGES.machine, REGLAGES.fluidnc, fichier, maintenant=maintenant
    )


# ------------------------------------------------------------------ les réglages


def test_les_limites_du_depot_sont_toutes_des_exemples():
    assert ENTRETIEN.exemple
    assert ENTRETIEN.pieces and all(piece.exemple for piece in ENTRETIEN.pieces.values())
    # Les pièces citent seulement des axes et des sorties qui existent.
    assert verifier_avec_liste(ENTRETIEN, charger_entrees_sorties(LISTE), REGLAGES.fluidnc) == []


def test_axe_inconnu(reglages):
    remplacer(reglages / "entretien.yaml", "de: pont_x}", "de: axe_fantome}")
    texte = erreur_de(reglages)
    assert "entretien.yaml" in texte and "axe_fantome" in texte and "machine.yaml" in texte


def test_genre_sans_de_ou_avec_de_en_trop(reglages):
    remplacer(reglages / "entretien.yaml", "{genre: distance, de: pont_x}", "{genre: distance}")
    assert "dit « de »" in erreur_de(reglages)


def test_seaux_ne_prend_pas_de_de(reglages):
    remplacer(reglages / "entretien.yaml", "{genre: seaux}", "{genre: seaux, de: pont_x}")
    assert "n'a pas de « de »" in erreur_de(reglages)


def test_limite_nulle_et_avance_trop_grande(reglages):
    remplacer(reglages / "entretien.yaml", "limite: 90\n", "limite: 0\n")
    assert "limite" in erreur_de(reglages)


def test_avance_a_100_pour_cent_refusee(reglages):
    remplacer(reglages / "entretien.yaml", "avance_pourcent: 10", "avance_pourcent: 100")
    assert "avance_pourcent" in erreur_de(reglages)


def test_nom_de_reglage_inconnu(reglages):
    ajouter(reglages / "entretien.yaml", "autre_chose: 1\n")
    assert "autre_chose" in erreur_de(reglages)


def test_sortie_inconnue_dans_la_liste(reglages):
    remplacer(reglages / "entretien.yaml", "de: vanne_vide}", "de: vanne_fantome}")
    nouveau = charger_reglages(reglages)
    erreurs = verifier_avec_liste(
        nouveau.entretien, charger_entrees_sorties(LISTE), nouveau.fluidnc
    )
    assert len(erreurs) == 1 and "vanne_fantome" in erreurs[0]


# ------------------------------------------------------------------ les compteurs d'axes


def test_distance_mouvements_et_heures_d_un_axe():
    c = nouveaux_compteurs()
    # pont_x (carte portique, lettre X) : positions en mm, un rapport toutes les 0,2 s.
    c.noter_rapport("portique", {"X": 0.0, "Y": 0.0, "Z": 0.0}, 10.0)
    for i in range(1, 6):
        c.noter_rapport("portique", {"X": 20.0 * i, "Y": 0.0, "Z": 0.0}, 10.0 + 0.2 * i)
    # Arrêt de 3 s (> arret_s), puis un nouveau mouvement.
    c.noter_rapport("portique", {"X": 100.0}, 14.0)
    c.noter_rapport("portique", {"X": 120.0}, 14.2)
    assert c.valeur_axe("pont_x", "distance") == pytest.approx(0.12)
    assert c.valeur_axe("pont_x", "mouvements") == 2
    assert c.valeur_axe("pont_x", "heures") == pytest.approx(6 * 0.2 / 3600)
    # Les axes qui n'ont pas bougé n'ont rien compté.
    assert c.valeur_axe("chariot_y", "distance") == 0
    assert c.valeur_axe("griffe_z", "mouvements") == 0


def test_le_bruit_de_mesure_n_est_pas_un_mouvement():
    c = nouveaux_compteurs()
    c.noter_rapport("portique", {"X": 100.0}, 1.0)
    for i in range(2, 30):
        c.noter_rapport("portique", {"X": 100.0 + 0.01 * (i % 2)}, float(i))
    assert c.valeur_axe("pont_x", "mouvements") == 0
    assert c.valeur_axe("pont_x", "distance") == 0


def test_un_saut_de_repere_n_est_pas_une_distance():
    c = nouveaux_compteurs()
    c.noter_rapport("portique", {"X": 0.0}, 1.0)
    c.noter_rapport("portique", {"X": ENTRETIEN.compteurs.saut_max_mm + 1}, 1.2)
    assert c.valeur_axe("pont_x", "distance") == 0


def test_carte_coupee_puis_revenue_le_trajet_n_est_pas_compte():
    c = nouveaux_compteurs()
    c.noter_rapport("portique", {"X": 0.0}, 1.0)
    c.noter_rapport("portique", None, 1.2)
    c.noter_rapport("portique", {"X": 300.0}, 9.0)
    assert c.valeur_axe("pont_x", "distance") == 0
    # Puis le comptage reprend normalement.
    c.noter_rapport("portique", {"X": 310.0}, 9.2)
    assert c.valeur_axe("pont_x", "distance") == pytest.approx(0.01)


def test_un_trou_dans_les_rapports_ne_compte_pas_d_heures():
    c = nouveaux_compteurs()
    c.noter_rapport("portique", {"X": 0.0}, 1.0)
    c.noter_rapport("portique", {"X": 100.0}, 1.0 + ENTRETIEN.compteurs.trou_max_s + 5)
    assert c.valeur_axe("pont_x", "heures") == 0
    assert c.valeur_axe("pont_x", "distance") == pytest.approx(0.1)


def test_axe_tournant_compte_en_degres():
    c = nouveaux_compteurs()
    c.noter_rapport("portique", {"A": 0.0}, 1.0)
    c.noter_rapport("portique", {"A": 45.0}, 1.2)
    assert c.valeur_axe("griffe_a", "distance") == pytest.approx(45.0)
    assert c.unite_axe("griffe_a") == "°" and c.unite_axe("pont_x") == "m"


def test_carte_inconnue_ignoree():
    c = nouveaux_compteurs()
    c.noter_rapport("carte_fantome", {"X": 0.0}, 1.0)
    c.noter_rapport("carte_fantome", {"X": 5.0}, 2.0)
    assert all(v["distance"] == 0 for v in c.axes.values())


# ------------------------------------------------------------------ les actionneurs


def test_manoeuvres_d_une_sortie_de_carte_fluidnc():
    c = nouveaux_compteurs()
    # frein_griffe_z : sortie 0 de la carte portique.
    c.noter_ligne("portique", "M64 P0")
    c.noter_ligne("portique", "M64 P0")  # déjà en marche : pas une manœuvre de plus
    c.noter_ligne("portique", "M65 P0")
    c.noter_ligne("portique", "m62 p0")
    assert c.valeur_actionneur("frein_griffe_z") == 2
    # Une ligne qui n'est pas une sortie, ou une sortie inconnue : rien.
    c.noter_ligne("portique", "G1 X10 F600")
    c.noter_ligne("portique", "M64 P9")
    c.noter_ligne("carte_fantome", "M64 P0")
    assert c.actionneurs == {"frein_griffe_z": 2}


def test_manoeuvres_d_un_relais_du_pi():
    liste = charger_entrees_sorties(LISTE)
    c = nouveaux_compteurs()
    materiel = Materiel(liste, FausseFabrique(liste))
    materiel.ecouteur_sortie = c.noter_sortie
    materiel.ecrire("relais_compresseur", True)
    materiel.ecrire("relais_compresseur", False)
    materiel.ecrire("relais_compresseur", True)
    assert c.valeur_actionneur("relais_compresseur") == 2
    materiel.fermer()


def test_un_ecouteur_qui_plante_ne_gene_pas_le_materiel():
    liste = charger_entrees_sorties(LISTE)
    materiel = Materiel(liste, FausseFabrique(liste))

    def plante(*_):
        raise RuntimeError("compteur cassé")

    materiel.ecouteur_sortie = plante
    materiel.ecrire("relais_compresseur", True)
    assert materiel.lire_entrees() is not None
    materiel.fermer()


# ------------------------------------------------------------------ le fichier


def test_ecriture_groupee_et_relecture(tmp_path):
    fichier = tmp_path / "donnees" / "entretien.json"
    c = nouveaux_compteurs(fichier)
    assert not c.ecrire()  # rien n'a changé : pas d'écriture
    assert not fichier.exists()
    c.noter_mouvement("pont_x", 2.5, 3600)
    c.noter_sortie("vanne_vide", True)
    assert not fichier.exists()  # rien n'est écrit à chaque geste
    assert c.ecrire() and fichier.exists()
    assert not c.ecrire()  # déjà écrit
    assert not list(fichier.parent.glob("*.tmp"))
    donnees = json.loads(fichier.read_text(encoding="utf-8"))
    assert donnees["axes"]["pont_x"] == {"distance": 2.5, "mouvements": 1, "heures": 1.0}
    # Au redémarrage : relu.
    relu = nouveaux_compteurs(fichier)
    assert relu.valeur_axe("pont_x", "distance") == 2.5
    assert relu.valeur_actionneur("vanne_vide") == 1
    assert relu.erreur_lecture is None


def test_fichier_illisible_les_compteurs_repartent_de_zero(tmp_path):
    fichier = tmp_path / "entretien.json"
    fichier.write_text("{pas du json", encoding="utf-8")
    c = nouveaux_compteurs(fichier)
    assert c.erreur_lecture and "illisible" in c.erreur_lecture
    assert (tmp_path / "entretien.json.abime").exists()
    entretien = Entretien(ENTRETIEN, c)
    constat = entretien.constats()[0]
    assert constat.niveau == "attention" and "illisible" in constat.texte


def test_le_fichier_est_dans_la_copie_de_secours(tmp_path):
    from vidange.registre.fichiers_hors_git import fichiers_a_garder

    c = nouveaux_compteurs(tmp_path / "entretien.json")
    c.noter_sortie("vanne_vide", True)
    c.ecrire()
    assert (tmp_path / "entretien.json") in fichiers_a_garder(tmp_path)


# ------------------------------------------------------------------ avec une vraie liaison


def test_la_liaison_alimente_les_compteurs():
    faux = FauxFluidnc()
    c = nouveaux_compteurs()
    with Liaison("portique", reglages_essai(), ouvrir=faux.ouvrir) as liaison:
        liaison.ecouteur_rapport = c.noter_rapport_liaison
        liaison.ecouteur_ligne = c.noter_ligne
        liaison.attendre_connexion(DELAI)
        liaison.envoyer_et_attendre("M64 P0", DELAI)
        liaison.envoyer_et_attendre("G1 X100 F3000", DELAI)
        liaison.attendre_fin_mouvements(DELAI)
        liaison.envoyer_et_attendre("M65 P0", DELAI)
        liaison.envoyer_et_attendre("M64 P0", DELAI)
        liaison.attendre_fin_mouvements(DELAI)
    assert c.valeur_axe("pont_x", "distance") == pytest.approx(0.1, abs=0.01)
    assert c.valeur_axe("pont_x", "mouvements") >= 1
    assert c.valeur_actionneur("frein_griffe_z") == 2


def test_une_ligne_refusee_n_est_pas_comptee():
    c = nouveaux_compteurs()
    liaison = Liaison("portique", reglages_essai(), ouvrir=FauxFluidnc().ouvrir)
    liaison.ecouteur_ligne = c.noter_ligne
    # Liaison pas démarrée : « carte non connectée », rien n'est parti.
    liaison.envoyer("M64 P0")
    assert c.actionneurs == {}


# ------------------------------------------------------------------ le simulateur


def test_le_simulateur_fait_bouger_les_compteurs():
    from vidange.chef.exemple import module_exemple

    c = nouveaux_compteurs()
    with Simulateur(REGLAGES, charger_entrees_sorties(LISTE), compteurs=c) as simulateur:
        planning = simulateur.jouer([module_exemple(simulateur.axes(), simulateur.materiel)])
    assert planning.fini
    # L'exemple va au repos, dans la zone A, et revient : l'axe exemple_z fait 3 mouvements.
    assert c.valeur_axe("exemple_z", "mouvements") >= 2
    assert c.valeur_axe("exemple_z", "distance") > 1.0
    assert c.valeur_axe("exemple_z", "heures") > 0


# ------------------------------------------------------------------ les pièces et l'alerte


class BancEntretien:
    """Un Entretien sur de faux compteurs, avec une fausse date."""

    def __init__(self, tmp_path, reglages: ReglagesEntretien = ENTRETIEN) -> None:
        self.maintenant = DEBUT
        self.fichier = tmp_path / "entretien.json"
        self.registre = Registre(
            tmp_path / "registre.sqlite", tmp_path / "photos", horloge=lambda: self.maintenant
        )
        self.reglages = reglages
        self.compteurs = nouveaux_compteurs(self.fichier, lambda: self.maintenant)
        self.entretien = self.nouveau()

    def nouveau(self) -> Entretien:
        return Entretien(
            self.reglages, self.compteurs, self.registre, maintenant=lambda: self.maintenant
        )

    def user_pont(self, fraction: float) -> None:
        """Le pont a parcouru cette fraction de la limite de sa pièce, depuis le dernier fait."""
        limite = self.reglages.pieces["pont_x"].limite
        self.compteurs.noter_mouvement("pont_x", fraction * limite, 60)


@pytest.fixture
def banc(tmp_path):
    banc = BancEntretien(tmp_path)
    yield banc
    banc.registre.fermer()


def piece(banc, nom):
    return banc.entretien.etat_piece(nom)


def test_une_piece_neuve_est_en_bon_etat(banc):
    for etat in banc.entretien.etat():
        assert etat.niveau == "ok" and etat.usure == 0
    assert banc.entretien.constats()[0].niveau == "ok"


def test_bientot_puis_a_faire_selon_l_avance_reglee(banc):
    avance = ENTRETIEN.alerte.avance_pourcent
    banc.user_pont(1 - avance / 100 - 0.01)
    assert piece(banc, "pont_x").niveau == "ok"
    banc.user_pont(0.02)
    assert piece(banc, "pont_x").niveau == "bientot"
    banc.user_pont(avance / 100)
    assert piece(banc, "pont_x").niveau == "a_faire"
    assert piece(banc, "pont_x").pourcent > 100


def test_l_alerte_ne_bloque_jamais_la_check_list(banc):
    banc.user_pont(5)
    banc.compteurs.noter_mouvement("griffe_z", 1e9, 0)
    constats = banc.entretien.constats()
    assert any("à faire" in c.texte for c in constats)
    assert {c.niveau for c in constats} == {"attention"}
    # Rien de bloquant : la production peut être lancée.
    from vidange.fiabilite.checklist import CheckList

    assert CheckList.prete(constats)
    texte = next(c for c in constats if "pont" in c.sujet)
    assert texte.quoi_faire and "limite d'exemple" in texte.texte


def test_les_pieces_urgentes_sont_en_tete(banc):
    banc.user_pont(1.5)
    banc.compteurs.noter_mouvement("chariot_y", 0.95 * ENTRETIEN.pieces["chariot_y"].limite, 1)
    noms = [p.nom for p in banc.entretien.etat()]
    assert noms[:2] == ["pont_x", "chariot_y"]


def test_alerte_au_journal_une_seule_fois_par_passage(banc, caplog):
    caplog.set_level("INFO", logger="vidange.entretien")
    banc.entretien.surveiller()
    assert not [r for r in caplog.records if r.levelname == "WARNING"]
    banc.user_pont(0.95)
    banc.entretien.surveiller()
    banc.entretien.surveiller()
    avertissements = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(avertissements) == 1 and "bientôt à faire" in avertissements[0]
    banc.user_pont(0.1)
    banc.entretien.surveiller()
    avertissements = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(avertissements) == 2 and "À FAIRE" in avertissements[1]


def test_fait_remet_la_piece_a_zero_et_note_qui_et_quand(banc):
    banc.user_pont(1.2)
    avant = banc.compteurs.valeur_axe("pont_x", "distance")
    etat = banc.entretien.fait("pont_x", "page web (karulium, 192.168.1.20)")
    assert etat.usure == 0 and etat.niveau == "ok"
    assert etat.fait_par == "page web (karulium, 192.168.1.20)"
    # Le total à vie ne change pas.
    assert banc.compteurs.valeur_axe("pont_x", "distance") == avant
    # Le registre garde qui et quand.
    ligne = banc.registre.lire("SELECT * FROM reglages_appliques")[-1]
    assert ligne["fichier"] == "entretien" and ligne["reglage"] == "pont_x"
    assert ligne["qui"].startswith("page web (karulium")
    assert "entretien fait" in ligne["raison"] and json.loads(ligne["ancien"])["usure"] > 0
    # Et l'usure repart : un peu d'usure ensuite se compte depuis le fait.
    banc.user_pont(0.5)
    assert piece(banc, "pont_x").pourcent == pytest.approx(50, abs=0.1)


def test_le_fait_survit_a_un_redemarrage(banc):
    banc.user_pont(0.5)
    banc.entretien.fait("pont_x", "Karulium")
    banc.user_pont(0.25)
    banc.compteurs.ecrire()
    banc.compteurs = nouveaux_compteurs(banc.fichier, lambda: banc.maintenant)
    relu = banc.nouveau()
    etat = relu.etat_piece("pont_x")
    assert etat.pourcent == pytest.approx(25, abs=0.1) and etat.fait_par == "Karulium"


def test_piece_inconnue(banc):
    from vidange.entretien import ErreurEntretien

    with pytest.raises(ErreurEntretien, match="inconnue"):
        banc.entretien.fait("piece_fantome", "moi")


def test_calendrier_en_jours(banc):
    limite = ENTRETIEN.pieces["tour_general"].limite
    banc.maintenant = DEBUT + timedelta(days=limite * 0.95)
    etat = piece(banc, "tour_general")
    assert etat.niveau == "bientot" and etat.unite == "jours"
    banc.maintenant = DEBUT + timedelta(days=limite + 1)
    assert piece(banc, "tour_general").niveau == "a_faire"
    banc.entretien.fait("tour_general", "Karulium")
    assert piece(banc, "tour_general").niveau == "ok"


def test_les_seaux_remplis_comptent(banc):
    cycle = banc.registre.commencer_cycle("remplissage")
    banc.maintenant += timedelta(seconds=5)
    for numero in range(3):
        banc.registre.ajouter_seau(cycle, f"S{numero}")
    assert piece(banc, "controle_lavage").usure == 3
    banc.maintenant += timedelta(seconds=5)
    banc.entretien.fait("controle_lavage", "Karulium")
    assert piece(banc, "controle_lavage").usure == 0
    banc.maintenant += timedelta(seconds=5)
    banc.registre.ajouter_seau(cycle, "S9")
    assert piece(banc, "controle_lavage").usure == 1


def test_une_piece_nouvelle_dans_le_fichier_part_de_zero(banc):
    banc.user_pont(0.5)
    banc.compteurs.noter_sortie("vanne_vide", True)
    del banc.compteurs.departs["vanne_vide"]
    # Une pièce ajoutée plus tard à entretien.yaml n'hérite pas des manœuvres déjà passées.
    brut = ENTRETIEN.model_dump()
    brut["pieces"] = {"vanne_vide": brut["pieces"]["vanne_vide"]}
    nouveau = Entretien(ReglagesEntretien.model_validate(brut), banc.compteurs, banc.registre)
    assert nouveau.etat_piece("vanne_vide").usure == 0
    banc.compteurs.noter_sortie("vanne_vide", False)
    banc.compteurs.noter_sortie("vanne_vide", True)
    assert nouveau.etat_piece("vanne_vide").usure == 1


# ------------------------------------------------------------------ l'API et la page


def client_api(banc, nom="chef"):
    services = Services(
        nouveau_chef(Horloge()), banc.registre, lambda *_: None, list, entretien=banc.entretien
    )
    app = creer_app_de_test(services, banc.fichier.parent)
    return client_connecte(app, nom, adresse=LOCAL)


def test_api_regarder_pour_tous_regler_pour_le_bouton(banc):
    banc.user_pont(1.1)
    for nom in ("chef", "aide", "invite"):
        reponse = client_api(banc, nom).get("/api/entretien")
        assert reponse.status_code == 200
        corps = reponse.json()
        assert "pont_x" in corps["a_faire"] and corps["pieces"][0]["nom"] == "pont_x"
        assert corps["compteurs"]["axes"]["pont_x"]["unite"] == "m"
    assert client_api(banc, None).get("/api/entretien").status_code == 401
    # Le bouton « fait » : seulement le rôle « régler ».
    for nom in ("aide", "invite"):
        assert client_api(banc, nom).post("/api/entretien/pont_x/fait").status_code == 403
    assert piece(banc, "pont_x").niveau == "a_faire"
    reponse = client_api(banc, "chef").post("/api/entretien/pont_x/fait")
    assert reponse.status_code == 200 and reponse.json()["niveau"] == "ok"
    assert "chef" in reponse.json()["fait_par"]
    assert client_api(banc).post("/api/entretien/piece_fantome/fait").status_code == 404
    # Noté dans le journal des actions (qui, rôle, chemin).
    actions = client_api(banc).get("/api/actions").json()
    assert any(a.get("chemin") == "/api/entretien/pont_x/fait" for a in actions)


def test_api_sans_entretien(tmp_path):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    services = Services(nouveau_chef(Horloge()), registre, lambda *_: None, list)
    client = client_connecte(creer_app_de_test(services, tmp_path), adresse=LOCAL)
    assert client.get("/api/entretien").status_code == 404
    registre.fermer()


def test_la_page_a_son_onglet_maintenance():
    from vidange.api.app import PAGE

    texte = PAGE.read_text(encoding="utf-8")
    assert 'data-vue="maintenance"' in texte and 'id="vue-maintenance"' in texte
    assert "/api/entretien" in texte


# ------------------------------------------------------------------ le démarrage


def arguments(reglages, entrees_sorties, tmp_path):
    return [*options(reglages, tmp_path), "--entrees-sorties", str(entrees_sorties)]


def test_demarrage_refuse_une_sortie_inconnue(reglages, entrees_sorties, tmp_path, capsys):
    remplacer(reglages / "entretien.yaml", "de: vanne_vide}", "de: vanne_fantome}")
    code = principal([*arguments(reglages, entrees_sorties, tmp_path), "--verifier"])
    assert code == CODE_REGLAGES_FAUX
    assert "vanne_fantome" in capsys.readouterr().err


def test_demarrage_refuse_un_axe_inconnu(reglages, tmp_path, capsys):
    remplacer(reglages / "entretien.yaml", "de: pont_x}", "de: axe_fantome}")
    assert principal([*options(reglages, tmp_path), "--verifier"]) == CODE_REGLAGES_FAUX
    assert "axe_fantome" in capsys.readouterr().err


def test_verifier_dit_que_les_limites_sont_des_exemples(reglages, tmp_path, capsys):
    assert principal([*options(reglages, tmp_path), "--verifier"]) == CODE_OK
    assert "entretien.yaml : limites d'usure d'EXEMPLE" in capsys.readouterr().err


def test_une_piece_a_faire_est_dans_la_check_list_et_le_journal_sans_rien_bloquer(
    reglages, tmp_path
):
    donnees = tmp_path / "donnees"
    donnees.mkdir()
    # Le tour général a été fait en l'an 2000 : il est à faire depuis longtemps.
    (donnees / "entretien.json").write_text(
        json.dumps(
            {
                "version": 1,
                "departs": {"tour_general": {"valeur": 0, "date": "2000-01-01T00:00:00+00:00"}},
            }
        ),
        encoding="utf-8",
    )
    arret = threading.Event()
    arret.set()
    assert principal(options(reglages, tmp_path), arret) == CODE_OK
    contenu = (donnees / "journal" / NOM_FICHIER).read_text(encoding="utf-8")
    assert "[attention] entretien : Tour général de la machine" in contenu
    assert "à faire : limite atteinte" in contenu
