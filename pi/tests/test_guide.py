"""Tests du mode guidé pour un employé et du manuel tenu à jour (tâche 32, fonctions 84 et 85)."""

import re

import pytest

from vidange.api import Services
from vidange.api.acces import verifier_roles_declares
from vidange.demarrage import erreurs_entre_reglages_et_liste, principal
from vidange.ecran.pages import GUIDE, PAGES
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.guide import ErreurGuide, Guide, en_markdown, sections
from vidange.registre import Registre
from vidange.reglages import ErreurReglages, charger_reglages

from .conftest import DOSSIER_PI
from .test_api import AIDE, CHEF, INVITE, BancApi, creer_app_de_test
from .test_api_comptes import niveaux_des_routes
from .test_ecran import BancEcran
from .test_reglages import erreur_de, remplacer

REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
GUIDE_YAML = REGLAGES.guide
TRAVAIL = "changer_fut"  # 6 étapes, la 3e et la 5e citent un signal
QUI = "page web (Paul, 192.168.1.5)"


class Signaux:
    """Des entrées lues par le guide : un dictionnaire que le test change."""

    def __init__(self) -> None:
        self.valeurs: dict[str, bool | None] = {}

    def __call__(self, nom: str) -> bool | None:
        return self.valeurs.get(nom)


@pytest.fixture
def horloge():
    class Horloge:
        t = 0.0

        def __call__(self) -> float:
            return self.t

    return Horloge()


@pytest.fixture
def registre(tmp_path):
    base = Registre(tmp_path / "registre.sqlite", tmp_path / "photos")
    yield base
    base.fermer()


@pytest.fixture
def guide(horloge, registre):
    signaux = Signaux()
    g = Guide(GUIDE_YAML, signaux, registre, horloge)
    g.signaux = signaux
    return g


# ---------------------------------------------------------------- guide.yaml


def test_les_travaux_d_exemple_sont_marques_exemple():
    assert GUIDE_YAML.exemple is True
    assert all(travail.exemple for travail in GUIDE_YAML.travaux.values())
    assert TRAVAIL in GUIDE_YAML.travaux


def test_les_reglages_du_depot_passent_la_verification_avec_la_liste():
    liste = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
    assert erreurs_entre_reglages_et_liste(REGLAGES, liste) == []


def test_un_signal_inconnu_empeche_de_demarrer(reglages, entrees_sorties):
    remplacer(reglages / "guide.yaml", "signal: plateau_fut_en_place", "signal: plateau_inconnu")
    nouveau = charger_reglages(reglages)
    liste = charger_entrees_sorties(entrees_sorties)
    erreurs = erreurs_entre_reglages_et_liste(nouveau, liste)
    assert any(
        "travaux → changer_fut → étape 3 → signal : « plateau_inconnu »" in e for e in erreurs
    )


def test_un_signal_qui_n_est_pas_une_entree_est_refuse(reglages, entrees_sorties):
    # Un relais est une sortie : le guide ne lit que des entrées.
    remplacer(reglages / "guide.yaml", "signal: plateau_fut_en_place", "signal: relais_1_bus")
    erreurs = erreurs_entre_reglages_et_liste(
        charger_reglages(reglages), charger_entrees_sorties(entrees_sorties)
    )
    assert any("relais_1_bus" in e and "n'est pas une entrée" in e for e in erreurs)


def test_un_texte_plus_long_que_l_ecran_est_refuse(reglages, entrees_sorties):
    remplacer(reglages / "guide.yaml", "texte_max: 140", "texte_max: 200")
    erreurs = erreurs_entre_reglages_et_liste(
        charger_reglages(reglages), charger_entrees_sorties(entrees_sorties)
    )
    assert any("texte_max (200)" in e and "t_texte" in e for e in erreurs)


def test_une_phrase_trop_longue_est_refusee(reglages):
    remplacer(reglages / "guide.yaml", "texte_max: 140", "texte_max: 40")
    assert "étape 1 :" in erreur_de(reglages) and "texte_max" in erreur_de(reglages)


def test_trop_d_etapes_est_refuse(reglages):
    remplacer(reglages / "guide.yaml", "etapes_max: 20", "etapes_max: 3")
    assert "6 étapes, au plus 3" in erreur_de(reglages)


def test_un_titre_trop_long_est_refuse(reglages):
    remplacer(reglages / "guide.yaml", "titre_max: 30", "titre_max: 10")
    assert "→ titre :" in erreur_de(reglages)


def test_un_nom_de_travail_sans_accent_et_une_faute_de_frappe_sont_refuses(reglages):
    remplacer(reglages / "guide.yaml", "changer_fut:", "Changer_fût:")
    assert "nom à écrire en minuscules" in erreur_de(reglages)


def test_une_cle_inconnue_est_une_faute_de_frappe(reglages):
    remplacer(reglages / "guide.yaml", "    quand:", "    quant:")
    with pytest.raises(ErreurReglages):
        charger_reglages(reglages)


def test_demarrer_refuse_un_guide_faux(reglages, tmp_path, capsys):
    remplacer(reglages / "guide.yaml", "etapes_max: 20", "etapes_max: 3")
    code = principal(["--reglages", str(reglages), "--donnees", str(tmp_path), "--verifier"])
    assert code != 0


# ---------------------------------------------------------------- le guide pas à pas


def test_la_liste_des_travaux(guide):
    liste = guide.liste()
    assert [t["travail"] for t in liste] == list(GUIDE_YAML.travaux)
    assert liste[0]["etapes"] == len(GUIDE_YAML.travaux[liste[0]["travail"]].etapes)
    assert not guide.etat().actif


def test_un_travail_pas_a_pas_jusqu_au_carnet(guide, registre):
    travail = GUIDE_YAML.travaux[TRAVAIL]
    etat = guide.demarrer(TRAVAIL, QUI)
    assert (etat.actif, etat.numero, etat.total) == (True, 1, len(travail.etapes))
    assert etat.texte == travail.etapes[0].texte and etat.qui == QUI
    for numero in range(2, len(travail.etapes) + 1):
        guide.signaux.valeurs.update(plateau_fut_en_place=True, reed_panneau_poste_fut=True)
        etat = guide.fait(QUI)
        assert etat.numero == numero and not etat.termine
    guide.signaux.valeurs.update(reed_panneau_poste_fut=True)
    etat = guide.fait(QUI)
    assert etat.termine and etat.actif and "terminé" in etat.texte
    notes = registre.lire_carnet()
    assert len(notes) == 1
    assert travail.titre in notes[0]["texte"] and notes[0]["auteur"] == QUI
    assert "n'a pas vu" not in notes[0]["texte"]
    # Fermer l'écran de fin : plus de travail.
    assert not guide.arreter(QUI).actif


def test_precedent_revient_d_une_etape_et_rouvre_la_derniere(guide):
    guide.demarrer(TRAVAIL, QUI)
    with pytest.raises(ErreurGuide, match="première étape"):
        guide.precedent(QUI)
    guide.fait(QUI)
    assert guide.precedent(QUI).numero == 1
    for _ in GUIDE_YAML.travaux[TRAVAIL].etapes:
        guide.fait(QUI)
    assert guide.etat().termine
    etat = guide.precedent(QUI)
    assert not etat.termine and etat.numero == etat.total


def test_un_seul_travail_a_la_fois(guide):
    guide.demarrer(TRAVAIL, QUI)
    with pytest.raises(ErreurGuide, match="déjà en cours"):
        guide.demarrer("vider_bidon_purge", "écran de l'armoire")
    guide.arreter(QUI)
    assert guide.demarrer("vider_bidon_purge", "écran de l'armoire").actif


def test_travail_inconnu_et_ordres_sans_travail(guide):
    with pytest.raises(ErreurGuide, match="inconnu"):
        guide.demarrer("rien", QUI)
    with pytest.raises(ErreurGuide, match="aucun travail"):
        guide.fait(QUI)
    with pytest.raises(ErreurGuide, match="aucun travail"):
        guide.precedent(QUI)
    assert not guide.arreter(QUI).actif  # arrêter sans travail ne fait rien


def test_fait_sur_un_travail_termine_est_refuse(guide):
    guide.demarrer("vider_bidon_purge", QUI)
    for _ in GUIDE_YAML.travaux["vider_bidon_purge"].etapes:
        guide.fait(QUI)
    with pytest.raises(ErreurGuide, match="déjà terminé"):
        guide.fait(QUI)


def test_la_machine_dit_ce_qu_elle_voit_sans_jamais_bloquer(guide, registre):
    guide.demarrer(TRAVAIL, QUI)
    guide.fait(QUI)
    guide.fait(QUI)  # 3e étape : « plateau_fut_en_place »
    guide.signaux.valeurs["plateau_fut_en_place"] = False
    etat = guide.etat()
    assert etat.signal == "plateau_fut_en_place" and etat.vu is False
    assert etat.machine_d_accord is False
    # Pas de blocage : « Fait » passe quand même, le désaccord est noté.
    suite = guide.fait(QUI)
    assert suite.numero == 4
    assert "ne voit pas « plateau_fut_en_place »" in suite.messages[0]
    guide.signaux.valeurs["reed_panneau_poste_fut"] = True
    guide.fait(QUI)
    guide.fait(QUI)
    guide.fait(QUI)
    assert "La machine n'a pas vu" in registre.lire_carnet()[0]["texte"]


def test_signal_vu_d_accord_inconnu_ou_en_panne(guide):
    guide.demarrer(TRAVAIL, QUI)
    guide.fait(QUI)
    guide.fait(QUI)
    guide.signaux.valeurs["plateau_fut_en_place"] = True
    assert guide.etat().machine_d_accord is True
    guide.signaux.valeurs["plateau_fut_en_place"] = None
    etat = guide.etat()
    assert etat.vu is None and etat.machine_d_accord is None

    def casse(nom):
        raise OSError("carte muette")

    guide._lire_signal = casse
    assert guide.etat().vu is None  # une lecture qui échoue ne gêne jamais le guide
    assert guide.fait(QUI).numero == 4


def test_une_etape_sans_signal_n_a_pas_de_lecture(guide):
    guide.demarrer(TRAVAIL, QUI)
    etat = guide.etat()
    assert etat.signal is None and etat.vu is None and etat.machine_d_accord is None


def test_sans_lecture_de_signaux_le_guide_marche(registre, horloge):
    sans = Guide(GUIDE_YAML, None, registre, horloge)
    sans.demarrer(TRAVAIL, QUI)
    sans.fait(QUI)
    sans.fait(QUI)
    assert sans.etat().vu is None and sans.fait(QUI).numero == 4


def test_un_travail_oublie_s_efface_seul(guide, horloge):
    guide.demarrer(TRAVAIL, QUI)
    horloge.t = GUIDE_YAML.oubli_min * 60 - 1
    assert guide.etat().actif
    guide.fait(QUI)  # une action repart de zéro
    horloge.t += GUIDE_YAML.oubli_min * 60 + 1
    assert not guide.etat().actif
    assert guide.demarrer(TRAVAIL, "écran de l'armoire").numero == 1


def test_sans_registre_le_guide_marche(horloge):
    g = Guide(GUIDE_YAML, None, None, horloge)
    g.demarrer("vider_bidon_purge", QUI)
    for _ in GUIDE_YAML.travaux["vider_bidon_purge"].etapes:
        g.fait(QUI)
    assert g.etat().termine


# ---------------------------------------------------------------- le manuel (85)


def test_le_manuel_est_fabrique_d_apres_ce_que_le_programme_sait():
    texte = en_markdown(REGLAGES)
    for travail in GUIDE_YAML.travaux.values():
        assert travail.titre in texte
        assert all(etape.texte in texte for etape in travail.etapes)
    for piece in REGLAGES.entretien.pieces.values():
        assert piece.description in texte
    from vidange import quoi_faire

    assert quoi_faire.ALARMES_FLUIDNC[1] in texte
    assert quoi_faire.PLANTAGE in texte
    for libelle in ("Production", "Lavage", "UV-ozone", "Maïs"):
        assert libelle in texte
    # La sécurité est dite d'abord, et le guide n'y prétend rien.
    assert sections(REGLAGES)[0].cle == "securite"
    assert "câblée" in texte


def test_le_manuel_suit_les_reglages(reglages):
    remplacer(reglages / "guide.yaml", "Enlever la soupape du couvercle", "Retirer le bouchon")
    nouveau = en_markdown(charger_reglages(reglages))
    assert "Retirer le bouchon" in nouveau and "Enlever la soupape du couvercle" not in nouveau


def test_docs_manuel_md_est_a_jour():
    """Si ce test échoue : lancer « vidange manuel » et ajouter docs/manuel.md à la PR."""
    fichier = DOSSIER_PI.parent / "docs" / "manuel.md"
    assert fichier.read_text(encoding="utf-8") == en_markdown(REGLAGES)


def test_la_commande_manuel_ecrit_et_verifie(reglages, tmp_path, capsys):
    from vidange.guide.outil import lancer_manuel

    fichier = tmp_path / "docs" / "manuel.md"
    assert lancer_manuel(["--verifier"], reglages, fichier) == 1
    assert "n'est plus à jour" in capsys.readouterr().out
    assert lancer_manuel([], reglages, fichier) == 0
    assert fichier.read_text(encoding="utf-8") == en_markdown(charger_reglages(reglages))
    assert lancer_manuel(["--verifier"], reglages, fichier) == 0
    remplacer(reglages / "guide.yaml", "Freiner les 2 roulettes", "Freiner les roulettes")
    assert lancer_manuel(["--verifier"], reglages, fichier) == 1
    remplacer(reglages / "guide.yaml", "etapes_max: 20", "etapes_max: 1")
    assert lancer_manuel([], reglages, fichier) == 2
    assert "Réglages faux" in capsys.readouterr().out


def test_la_commande_est_reconnue_par_le_programme_principal(tmp_path, capsys):
    cible = tmp_path / "m.md"
    assert principal(["manuel", "--fichier", str(cible)]) == 0
    assert cible.read_text(encoding="utf-8") == en_markdown(REGLAGES)


# ---------------------------------------------------------------- l'API : les rôles existants


@pytest.fixture
def b(tmp_path):
    banc = BancApi(tmp_path)
    banc.guide = Guide(GUIDE_YAML, Signaux(), banc.registre)
    services = Services(
        banc.chef,
        banc.registre,
        banc.bilans.acquitter,
        checklist=lambda: banc.constats,
        guide=banc.guide,
        manuel=lambda: [s.en_dict() for s in sections(REGLAGES)],
    )
    banc.app = creer_app_de_test(services, tmp_path)
    yield banc
    banc.registre.fermer()


def test_les_routes_du_guide_ont_un_niveau(b):
    verifier_roles_declares(b.app)
    niveaux = niveaux_des_routes(b.app)
    from vidange.comptes import Niveau

    assert niveaux[("GET", "/api/guide")] is Niveau.REGARDER
    assert niveaux[("GET", "/api/manuel")] is Niveau.REGARDER
    for chemin in (
        "/api/guide/{travail}/commencer",
        "/api/guide/fait",
        "/api/guide/precedent",
        "/api/guide/arreter",
    ):
        assert niveaux[("POST", chemin)] is Niveau.PRODUIRE, chemin


def test_l_employe_suit_un_travail_jusqu_au_bout(b):
    employe = b.client(nom=AIDE)
    reponse = employe.get("/api/guide")
    assert reponse.status_code == 200
    assert reponse.json()["etat"]["actif"] is False
    assert len(reponse.json()["travaux"]) == len(GUIDE_YAML.travaux)
    etat = employe.post(f"/api/guide/{TRAVAIL}/commencer").json()
    assert etat["actif"] and etat["numero"] == 1 and "(" in etat["qui"]
    assert employe.post("/api/guide/precedent").status_code == 409
    for _ in GUIDE_YAML.travaux[TRAVAIL].etapes:
        etat = employe.post("/api/guide/fait").json()
    assert etat["termine"]
    assert employe.post("/api/guide/fait").status_code == 409
    assert employe.post("/api/guide/arreter").json()["actif"] is False
    assert len(b.registre.lire_carnet()) == 1


def test_le_visiteur_regarde_sans_commander(b):
    visiteur = b.client(nom=INVITE)
    assert visiteur.get("/api/guide").status_code == 200
    assert visiteur.get("/api/manuel").status_code == 200
    assert visiteur.post(f"/api/guide/{TRAVAIL}/commencer").status_code == 403
    assert visiteur.post("/api/guide/fait").status_code == 403
    assert not b.guide.etat().actif


def test_karulium_peut_aussi_suivre_un_travail(b):
    assert b.client(nom=CHEF).post(f"/api/guide/{TRAVAIL}/commencer").status_code == 200


def test_personne_de_connecte_est_refuse(b):
    anonyme = b.client(nom=None)
    assert anonyme.get("/api/guide").status_code == 401
    assert anonyme.get("/api/manuel").status_code == 401
    assert anonyme.post("/api/guide/fait").status_code == 401


def test_travail_inconnu_et_deuxieme_travail(b):
    employe = b.client(nom=AIDE)
    assert employe.post("/api/guide/rien/commencer").status_code == 404
    employe.post(f"/api/guide/{TRAVAIL}/commencer")
    reponse = employe.post("/api/guide/vider_bidon_purge/commencer")
    assert reponse.status_code == 409 and "déjà en cours" in reponse.json()["detail"]


def test_le_manuel_par_l_api(b):
    corps = b.client(nom=AIDE).get("/api/manuel").json()
    assert [s["cle"] for s in corps["sections"]][:2] == ["securite", "roles"]
    assert any("Mettre un fût au poste" in "".join(s["lignes"]) for s in corps["sections"])


def test_l_action_de_l_employe_est_au_journal_des_actions(b):
    b.client(nom=AIDE).post(f"/api/guide/{TRAVAIL}/commencer")
    lignes = (b.dossier / "actions.jsonl").read_text(encoding="utf-8")
    assert f"/api/guide/{TRAVAIL}/commencer" in lignes and '"role": "employe"' in lignes


def test_sans_guide_les_routes_disent_pourquoi(tmp_path):
    banc = BancApi(tmp_path)
    try:
        reponse = banc.client(nom=AIDE).get("/api/guide")
        assert reponse.status_code == 404 and "guide.yaml" in reponse.json()["detail"]
        assert banc.client(nom=AIDE).get("/api/manuel").status_code == 404
    finally:
        banc.registre.fermer()


def test_la_page_web_a_son_onglet_aide():
    page = (DOSSIER_PI / "vidange" / "api" / "page" / "index.html").read_text(encoding="utf-8")
    assert 'data-vue="aide"' in page and 'id="vue-aide"' in page
    code = (DOSSIER_PI / "vidange" / "api" / "page" / "statique" / "onglets.js").read_text(
        encoding="utf-8"
    )
    assert "export async function ouvrirAide" in code
    assert not re.search(r"innerHTML", code[code.index("ouvrirAide") :])


# ---------------------------------------------------------------- l'écran de l'armoire


@pytest.fixture
def e(tmp_path):
    banc = BancEcran(tmp_path)
    banc.signaux = Signaux()
    banc.guide = Guide(GUIDE_YAML, banc.signaux, banc.registre, banc.horloge)
    banc.ecran.guide = banc.guide
    banc.tour()
    yield banc
    banc.registre.fermer()


def test_la_page_guide_est_decrite_dans_les_pages():
    assert PAGES["guide"] is GUIDE and GUIDE.numero == 8
    assert GUIDE.boutons == ["b_gauche", "b_droite", "b_ok", "b_retour"]
    assert PAGES["mode"].objet("b_aide").sorte == "bouton"
    assert GUIDE_YAML.texte_max <= GUIDE.objet("t_texte").longueur
    assert GUIDE_YAML.titre_max <= GUIDE.objet("t_titre").longueur


def test_aide_depuis_la_page_mode_choisir_et_commencer(e):
    e.appuyer("b_mode")
    assert e.texte("b_aide") == "AIDE"
    e.appuyer("b_aide")
    assert e.nextion.page == "guide"
    assert e.texte("t_titre") == "AIDE : CHOISIR"
    premier = list(GUIDE_YAML.travaux.values())[0]
    assert e.texte("t_texte").startswith(premier.titre)
    assert e.texte("t_etape") == f"1 sur {len(GUIDE_YAML.travaux)}"
    e.appuyer("b_droite")
    deuxieme = list(GUIDE_YAML.travaux.values())[1]
    assert e.texte("t_texte").startswith(deuxieme.titre)
    e.appuyer("b_gauche")
    e.appuyer("b_gauche")  # tourne : revient au dernier
    assert e.texte("t_etape") == f"{len(GUIDE_YAML.travaux)} sur {len(GUIDE_YAML.travaux)}"
    e.appuyer("b_droite")
    e.appuyer("b_ok")
    assert e.guide.etat().actif and e.guide.etat().travail == TRAVAIL
    assert "écran de l'armoire" in e.guide.etat().qui
    assert e.texte("t_titre") == premier.titre.upper()
    assert e.texte("t_etape") == f"Étape 1 sur {len(premier.etapes)}"
    assert e.texte("t_texte") == premier.etapes[0].texte
    assert e.texte("b_ok") == "FAIT" and e.texte("b_retour") == "ARRÊTER"


def test_a_l_ecran_fait_precedent_et_fin(e):
    e.guide.demarrer(TRAVAIL, "écran de l'armoire")
    e.ecran._aller(GUIDE)
    e.tour()
    travail = GUIDE_YAML.travaux[TRAVAIL]
    assert e.nextion.couleur("b_gauche") != e.nextion.couleur("b_ok")  # gauche éteint à l'étape 1
    e.appuyer("b_gauche")  # rien : première étape
    assert e.guide.etat().numero == 1
    e.appuyer("b_droite")  # éteint : rien
    assert e.guide.etat().numero == 1
    e.appuyer("b_ok")
    assert e.texte("t_etape") == f"Étape 2 sur {len(travail.etapes)}"
    e.appuyer("b_gauche")
    assert e.guide.etat().numero == 1
    for _ in travail.etapes:
        e.appuyer("b_ok")
    assert e.guide.etat().termine
    assert e.texte("t_etape") == f"Les {len(travail.etapes)} étapes sont faites"
    assert e.texte("b_ok") == "FERMER"
    e.appuyer("b_ok")
    assert not e.guide.etat().actif and e.nextion.page == "etat"


def test_arreter_abandonne_le_travail(e):
    e.guide.demarrer(TRAVAIL, "écran de l'armoire")
    e.ecran._aller(GUIDE)
    e.tour()
    e.appuyer("b_retour")
    assert not e.guide.etat().actif and e.nextion.page == "etat"


def test_retour_sans_travail_ne_change_rien_au_guide(e):
    e.appuyer("b_mode")
    e.appuyer("b_aide")
    assert e.texte("b_retour") == "RETOUR"
    e.appuyer("b_retour")
    assert e.nextion.page == "etat" and not e.guide.etat().actif


def test_l_ecran_dit_ce_que_la_machine_voit(e):
    e.guide.demarrer(TRAVAIL, "écran de l'armoire")
    e.ecran._aller(GUIDE)
    e.appuyer("b_ok")
    e.appuyer("b_ok")  # étape 3 : plateau_fut_en_place
    e.signaux.valeurs["plateau_fut_en_place"] = False
    e.tour()
    assert e.texte("t_machine") == "La machine voit : non, étape pas faite"
    e.signaux.valeurs["plateau_fut_en_place"] = True
    e.tour()
    assert e.texte("t_machine") == "La machine voit : oui, étape faite"
    e.signaux.valeurs["plateau_fut_en_place"] = None
    e.tour()
    assert e.texte("t_machine").startswith("La machine voit : ?")
    e.appuyer("b_ok")  # étape sans signal
    assert e.texte("t_machine") == ""


def test_un_travail_commence_sur_la_page_web_fait_venir_la_page(e):
    assert e.nextion.page == "etat"
    e.guide.demarrer(TRAVAIL, QUI)
    e.tour()
    assert e.nextion.page == "guide"
    assert e.texte("t_texte") == GUIDE_YAML.travaux[TRAVAIL].etapes[0].texte
    # Arrêté depuis la page web : l'écran revient à l'état.
    e.guide.arreter(QUI)
    e.tour()
    assert e.nextion.page == "etat"
    assert "fini ou arrêté" in e.texte("t_info")


def test_la_page_ne_vient_pas_par_dessus_une_alarme_ou_ailleurs(e):
    e.appuyer("b_compteurs")
    e.guide.demarrer(TRAVAIL, QUI)
    e.tour()
    assert e.nextion.page == "compteurs"  # pas arraché à ce qu'on lit


def test_sans_guide_le_bouton_aide_est_inactif_et_dit_pourquoi(tmp_path):
    banc = BancEcran(tmp_path)
    try:
        banc.tour()
        banc.appuyer("b_mode")
        banc.appuyer("b_aide")
        assert banc.nextion.page == "mode"
        assert "Pas de mode guidé" in banc.texte("t_info")
    finally:
        banc.registre.fermer()


def test_retour_a_l_etat_sans_appui(e):
    e.appuyer("b_mode")
    e.appuyer("b_aide")
    e.horloge.t += REGLAGES_ECRAN().retour_accueil_s + 1
    e.tour()
    assert e.nextion.page == "etat"


def REGLAGES_ECRAN():
    return REGLAGES.programme.ecran
