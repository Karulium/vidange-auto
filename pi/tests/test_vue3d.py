"""Tests de la vue 3D et du rejeu d'incident (tâche 28) : réglages, scène, rejeux, routes.

Sans navigateur (le test de la page est dans test_vue3d_navigateur.py)."""

import json
from types import SimpleNamespace

import pytest

from vidange.api import Services
from vidange.chef import Alarme
from vidange.fluidnc import EtatCarte
from vidange.reglages import ErreurReglages, RejeuVue3d, charger_reglages
from vidange.vue3d import EnregistreurRejeu, ErreurRejeu, Vue3d

from .conftest import DOSSIER_PI
from .test_api import BancApi, creer_app_de_test
from .test_reglages import erreur_de, remplacer


@pytest.fixture(scope="module")
def reglages_du_depot():
    return charger_reglages(DOSSIER_PI / "reglages")


def fausses_liaisons(positions_mm):
    """Une fausse liaison par carte : seules les positions (mm, par lettre) comptent ici."""
    return {
        carte: SimpleNamespace(etat=EtatCarte(connectee=True, positions=dict(lettres)))
        for carte, lettres in positions_mm.items()
    }


# ---------------------------------------------------------------- réglages


def test_vue3d_du_depot_est_coherent(reglages_du_depot):
    vue = reglages_du_depot.vue3d
    assert vue.boites
    assert vue.rejeu.avant_s == 60 and vue.rejeu.apres_s == 60  # fonction 17 : 60 s avant et après


def test_boite_sur_un_axe_inconnu(reglages):
    remplacer(reglages / "vue3d.yaml", "x: {axe: pont_x}", "x: {axe: pont_zz}")
    assert "boites → pont → x → axe" in erreur_de(reglages)
    assert "pont_zz" in erreur_de(reglages)


def test_boite_sur_un_axe_qui_bouge_dans_un_autre_sens(reglages):
    remplacer(reglages / "vue3d.yaml", "y: {axe: chariot_y, decalage: 0.040}", "y: {axe: pont_x}")
    assert "« pont_x » bouge en x (axes_monde), pas en y" in erreur_de(reglages)


def test_axe_de_la_vue_absent_de_machine(reglages):
    remplacer(reglages / "vue3d.yaml", "  pousseur: x\n", "  pousseur: x\n  fantome: x\n")
    assert "axes_monde → fantome : axe absent de machine.yaml" in erreur_de(reglages)


def test_axe_tournant_dans_axes_monde(reglages):
    remplacer(reglages / "vue3d.yaml", "  pousseur: x\n", "  pousseur: x\n  griffe_a: x\n")
    assert "griffe_a : l'axe tourne" in erreur_de(reglages)


def test_rotation_sur_un_axe_droit(reglages):
    remplacer(reglages / "vue3d.yaml", "tourne: griffe_a", "tourne: pont_x")
    assert "« pont_x » n'est pas un axe tournant" in erreur_de(reglages)


def test_zone_qui_cite_un_axe_sans_sens(reglages):
    remplacer(reglages / "vue3d.yaml", "  exemple_x: x\n", "")
    message = erreur_de(reglages)
    assert "il manque « exemple_x »" in message and "exemple_zone_a" in message


def test_couleur_de_boite_inconnue(reglages):
    remplacer(reglages / "vue3d.yaml", "couleur: fixe", "couleur: rose")
    assert "« rose » absente de couleurs → boites" in erreur_de(reglages)


def test_un_rejeu_doit_tenir_dix_fois_dans_le_dossier(reglages):
    remplacer(reglages / "vue3d.yaml", "dossier_max_mo: 200", "dossier_max_mo: 1")
    assert "doit en garder au moins 10" in erreur_de(reglages)


def test_etendue_a_l_envers(reglages):
    remplacer(reglages / "vue3d.yaml", "x: [0.0, 3.1]", "x: [3.1, 0.0]")
    assert "« x » doit aller du plus petit au plus grand" in erreur_de(reglages)


def test_fichier_vue3d_manquant(reglages):
    (reglages / "vue3d.yaml").unlink()
    with pytest.raises(ErreurReglages, match="vue3d.yaml : fichier manquant"):
        charger_reglages(reglages)


# ---------------------------------------------------------------- scène et positions


def test_scene_decrit_les_boites_et_les_zones(reglages_du_depot):
    vue = Vue3d(reglages_du_depot.vue3d, reglages_du_depot.machine, {})
    scene = vue.scene()
    assert [b["nom"] for b in scene["boites"]] == list(reglages_du_depot.vue3d.boites)
    pont = next(b for b in scene["boites"] if b["nom"] == "pont")
    assert pont["x"]["axe"] == "pont_x" and pont["y"]["axe"] is None
    assert pont["couleur"] == reglages_du_depot.vue3d.couleurs.boites["portique"]
    zones = {z["nom"]: z for z in scene["zones"]}
    machine = reglages_du_depot.machine
    assert zones["exemple_zone_a"]["x"] == list(machine.zones["exemple_zone_a"]["exemple_x"])
    # Un sens que la zone ne cite pas prend tout le volume dessiné.
    assert zones["exemple_zone_b"]["y"] == scene["etendue"]["y"]
    assert scene["rafraichir_s"] == reglages_du_depot.vue3d.rafraichir_s
    assert "pont_x" in scene["axes"] and "exemple_x" in scene["axes"]


def test_positions_en_metres_et_en_degres(reglages_du_depot):
    machine = reglages_du_depot.machine
    pont, griffe_a = machine.axes["pont_x"], machine.axes["griffe_a"]
    assert pont.carte and pont.lettre and griffe_a.carte and griffe_a.lettre
    assert pont.carte == griffe_a.carte  # les deux axes sont sur la carte du portique
    liaisons = fausses_liaisons({pont.carte: {pont.lettre: 1500.0, griffe_a.lettre: 90.0}})
    positions = Vue3d(reglages_du_depot.vue3d, machine, liaisons).positions()
    assert positions["pont_x"] == pytest.approx(1.5)  # mm de FluidNC → m
    assert positions["griffe_a"] == pytest.approx(90.0)  # un axe tournant reste en degrés
    # Un axe dont la carte n'a rien dit : pas de position (jamais une position inventée).
    assert positions["chariot_y"] is None


def test_zones_tenues_viennent_du_chef(reglages_du_depot):
    vue = Vue3d(
        reglages_du_depot.vue3d,
        reglages_du_depot.machine,
        {},
        lambda: {"exemple_zone_a": "essai"},
    )
    assert vue.zones_tenues() == {"exemple_zone_a": "essai"}
    assert Vue3d(reglages_du_depot.vue3d, reglages_du_depot.machine, {}).zones_tenues() == {}


# ---------------------------------------------------------------- enregistreur de rejeux


class Banc3d:
    """Une horloge à la main et des positions qui avancent à chaque relevé."""

    def __init__(self, tmp_path, **reglages):
        valeurs = {
            "avant_s": 3,
            "apres_s": 2,
            "periode_s": 1,
            "dossier_max_mo": 1,
            "alarmes_proposees": 5,
            "vitesses": [1],
        }
        valeurs.update(reglages)
        self.maintenant = 100.0
        self.compte = 0
        self.zones = {}
        self.enregistreur = EnregistreurRejeu(
            tmp_path,
            RejeuVue3d(**valeurs),
            self.lire,
            lambda: dict(self.zones),
            horloge=lambda: self.maintenant,
        )

    def lire(self):
        self.compte += 1
        return {"pont_x": float(self.compte), "griffe_a": None}

    def tour(self, secondes=1):
        self.maintenant += secondes
        self.enregistreur.echantillonner()


def une_alarme(module="essai"):
    return Alarme(module, "un", "tour pas suivi", "Voir la machine.", "2026-11-09T10:00:00")


def test_rejeu_garde_avant_et_apres(tmp_path):
    b = Banc3d(tmp_path)
    for _ in range(6):
        b.tour()
    alarme = une_alarme()
    b.zones = {"exemple_zone_a": "essai"}
    b.enregistreur.recevoir(alarme)
    b.enregistreur.numero(alarme, 7)
    # Rien d'écrit avant la fin des 2 s d'après.
    b.tour()
    assert b.enregistreur.numeros() == []
    b.tour()
    assert b.enregistreur.numeros() == [7]
    fichier = json.loads(b.enregistreur.chemin(7).read_text(encoding="utf-8"))
    assert fichier["version"] == 1 and fichier["alarme"] == 7
    assert fichier["module"] == "essai" and fichier["message"] == "tour pas suivi"
    assert fichier["axes"] == ["griffe_a", "pont_x"]
    assert fichier["zones_tenues"] == {"exemple_zone_a": "essai"}
    temps = [ligne[0] for ligne in fichier["echantillons"]]
    # 3 s avant (-3, -2, -1), l'alarme (0) et 2 s après (1, 2) : dans l'ordre, sans doublon.
    assert temps == [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0]
    # Les positions sont celles de chaque relevé, dans l'ordre des axes (null : pas de position).
    assert [ligne[2] for ligne in fichier["echantillons"]][:3] == [3.0, 4.0, 5.0]
    assert fichier["echantillons"][0][1] is None


def test_rejeu_attend_le_numero_du_registre(tmp_path):
    b = Banc3d(tmp_path)
    alarme = une_alarme()
    b.enregistreur.recevoir(alarme)
    for _ in range(4):
        b.tour()
    assert b.enregistreur.numeros() == []  # le bilan n'a pas encore rendu le numéro
    b.enregistreur.numero(alarme, 3)
    b.tour()
    assert b.enregistreur.numeros() == [3]


def test_rejeu_sans_numero_finit_par_etre_oublie(tmp_path):
    b = Banc3d(tmp_path)
    b.enregistreur.recevoir(une_alarme())
    for _ in range(10):
        b.tour()
    assert b.enregistreur.numeros() == []
    assert b.enregistreur._attentes == []


def test_deux_alarmes_proches_ont_chacune_leur_fichier(tmp_path):
    b = Banc3d(tmp_path)
    b.tour()
    premiere, seconde = une_alarme("a"), une_alarme("b")
    b.enregistreur.recevoir(premiere)
    b.enregistreur.numero(premiere, 1)
    b.tour()
    b.enregistreur.recevoir(seconde)
    b.enregistreur.numero(seconde, 2)
    for _ in range(3):
        b.tour()
    assert b.enregistreur.numeros() == [2, 1]
    assert b.enregistreur.lire(2)["module"] == "b"


def test_la_memoire_est_bornee(tmp_path):
    b = Banc3d(tmp_path, avant_s=3, periode_s=1)
    for _ in range(50):
        b.tour()
    assert len(b.enregistreur._recent) <= 5


def test_purge_des_plus_vieux(tmp_path):
    b = Banc3d(tmp_path, dossier_max_mo=0.0008)  # ~ 800 octets : un ou deux fichiers
    for numero in (1, 2, 3, 4):
        alarme = une_alarme()
        b.enregistreur.recevoir(alarme)
        b.enregistreur.numero(alarme, numero)
        for _ in range(3):
            b.tour()
    restants = b.enregistreur.numeros()
    assert restants and restants[0] == 4  # le plus récent est toujours gardé
    assert 1 not in restants
    total = sum(f.stat().st_size for f in b.enregistreur.dossier.glob("*.json"))
    assert total <= 800 or len(restants) == 1


def test_lire_un_rejeu_absent_ou_abime(tmp_path):
    b = Banc3d(tmp_path)
    with pytest.raises(ErreurRejeu, match="pas de rejeu pour l'alarme n° 9"):
        b.enregistreur.lire(9)
    b.enregistreur.dossier.mkdir(parents=True)
    b.enregistreur.chemin(9).write_text("{pas du json", encoding="utf-8")
    with pytest.raises(ErreurRejeu, match="illisible"):
        b.enregistreur.lire(9)


def test_positions_illisibles_a_l_alarme_ne_plantent_pas(tmp_path):
    b = Banc3d(tmp_path)
    b.tour()

    def casse():
        raise RuntimeError("carte muette")

    b.enregistreur._lire = casse
    b.enregistreur.recevoir(une_alarme())  # ne lève rien : le chef n'est jamais gêné


def test_fin_du_programme_ecrit_ce_qui_attend(tmp_path):
    b = Banc3d(tmp_path)
    b.tour()
    alarme = une_alarme()
    b.enregistreur.recevoir(alarme)
    b.enregistreur.numero(alarme, 5)
    b.enregistreur.terminer()
    assert b.enregistreur.numeros() == [5]


# ---------------------------------------------------------------- routes


@pytest.fixture
def b(tmp_path, reglages_du_depot):
    banc = BancApi(tmp_path)
    machine, vue = reglages_du_depot.machine, reglages_du_depot.vue3d
    pont = machine.axes["pont_x"]
    liaisons = fausses_liaisons({pont.carte: {pont.lettre: 2000.0}})
    banc.vue = Vue3d(vue, machine, liaisons, lambda: {"exemple_zone_a": "essai"})
    banc.rejeux = EnregistreurRejeu(tmp_path, vue.rejeu, banc.vue.positions)
    yield banc
    banc.registre.fermer()


def app_avec_vue(banc, avec_rejeux=True):
    """L'API refaite avec la vue 3D (les Services de BancApi n'ont pas de vue)."""
    services = Services(
        banc.chef,
        banc.registre,
        banc.bilans.acquitter,
        checklist=lambda: banc.constats,
        vue3d=banc.vue,
        rejeux=banc.rejeux if avec_rejeux else None,
    )
    banc.app = creer_app_de_test(services, banc.dossier)
    return banc


def ecrire_rejeu(banc, alarme_id):
    alarme = une_alarme()
    banc.rejeux.recevoir(alarme)
    banc.rejeux.numero(alarme, alarme_id)
    banc.rejeux.terminer()


def test_les_routes_demandent_une_connexion(b):
    app_avec_vue(b)
    client = b.client(nom=None)
    for chemin in (
        "/api/vue3d/scene",
        "/api/vue3d/positions",
        "/api/vue3d/rejeux",
        "/api/vue3d/rejeux/1",
        "/statique/vue3d.js",
    ):
        assert client.get(chemin).status_code == 401, chemin


def test_le_visiteur_peut_regarder(b):
    app_avec_vue(b)
    client = b.client(nom="invite")  # rôle « regarder » seulement
    assert client.get("/api/vue3d/scene").status_code == 200
    assert client.get("/api/vue3d/positions").status_code == 200
    assert client.get("/api/vue3d/rejeux").status_code == 200


def test_route_scene(b):
    app_avec_vue(b)
    scene = b.client().get("/api/vue3d/scene").json()
    assert {boite["nom"] for boite in scene["boites"]} >= {"pont", "griffe"}
    assert scene["rejeu"]["vitesses"]


def test_route_positions(b):
    app_avec_vue(b)
    reponse = b.client().get("/api/vue3d/positions").json()
    assert reponse["axes"]["pont_x"] == pytest.approx(2.0)
    assert reponse["axes"]["chariot_y"] is None
    assert reponse["zones_tenues"] == {"exemple_zone_a": "essai"}
    assert reponse["en_alarme"] is False


def test_sans_vue_3d_les_routes_disent_non(b):
    client = b.client()  # BancApi n'a ni vue ni rejeux
    for chemin in ("/api/vue3d/scene", "/api/vue3d/positions", "/api/vue3d/rejeux"):
        assert client.get(chemin).status_code == 404, chemin


def test_sans_rejeux_la_vue_marche_mais_pas_le_rejeu(b):
    app_avec_vue(b, avec_rejeux=False)
    client = b.client()
    assert client.get("/api/vue3d/scene").status_code == 200
    assert client.get("/api/vue3d/rejeux").status_code == 404


def test_liste_et_lecture_d_un_rejeu(b):
    app_avec_vue(b)
    client = b.client()
    assert client.get("/api/vue3d/rejeux").json() == []
    numero = b.registre.noter_alarme("essai", "tour pas suivi", "Voir.", "un")
    ecrire_rejeu(b, numero)
    liste = client.get("/api/vue3d/rejeux").json()
    assert [a["id"] for a in liste] == [numero]
    assert liste[0]["module"] == "essai" and liste[0]["message"] == "tour pas suivi"
    rejeu = client.get(f"/api/vue3d/rejeux/{numero}").json()
    assert rejeu["alarme"] == numero and rejeu["echantillons"]
    assert client.get("/api/vue3d/rejeux/999").status_code == 404


def test_la_liste_est_bornee_par_le_reglage(b, reglages_du_depot):
    app_avec_vue(b)
    limite = reglages_du_depot.vue3d.rejeu.alarmes_proposees
    for _ in range(limite + 3):
        numero = b.registre.noter_alarme("essai", "m", "q", "un")
        ecrire_rejeu(b, numero)
    liste = b.client().get("/api/vue3d/rejeux").json()
    assert len(liste) == limite
    assert liste[0]["id"] > liste[-1]["id"]


def test_fichiers_de_la_page(b):
    app_avec_vue(b)
    client = b.client()
    reponse = client.get("/statique/vue3d.js")
    assert reponse.status_code == 200 and "javascript" in reponse.headers["content-type"]
    # La bibliothèque est copiée dans le dépôt : elle sort du Pi, pas d'un site.
    assert client.get("/statique/three/three.module.min.js").status_code == 200
    assert client.get("/statique/three/LICENSE").status_code == 200


@pytest.mark.parametrize(
    "chemin", ["../index.html", "..%2Findex.html", "three/../../index.html", "inconnu.js"]
)
def test_pas_de_sortie_du_dossier_statique(b, chemin):
    app_avec_vue(b)
    assert b.client().get("/statique/" + chemin).status_code == 404


def test_la_page_declare_la_bibliotheque_locale_et_aucun_site(b):
    texte = b.client(nom=None).get("/").text
    assert "/statique/three/three.module.min.js" in texte
    # Le Pi tourne sans Internet : aucun script, module ou feuille de style ne vient d'un site.
    assert 'src="http' not in texte and 'href="http' not in texte and "from 'http" not in texte


def test_le_bilan_rend_le_numero_de_l_alarme_au_rejeu(b):
    recus = []
    b.bilans.sur_numero.append(lambda alarme, numero: recus.append((alarme, numero)))
    b.bilans.sur_numero.append(lambda alarme, numero: 1 / 0)  # une suite qui plante gêne personne
    alarme = une_alarme()
    numero = b.bilans.traiter(alarme)
    assert recus == [(alarme, numero)]
